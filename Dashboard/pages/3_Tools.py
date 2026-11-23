"""Tools & AI Skills — inventory of the tools, dashboards and AI Skills built, read live
from ../Data/tools.xlsx, with a visual breakdown by type of tool, use, and project origin
plus a filterable gallery and a full-table editor."""

import pandas as pd
import streamlit as st

import kpi_cache as kcache
import kpi_charts as kc
import kpi_data as kd
import kpi_style as ks
from kpi_style import anchor, page_nav

st.set_page_config(page_title="Tools & AI Skills", page_icon="🛠️", layout="wide")
kc.set_theme(dark=st.context.theme.type == "dark")
ks.inject(dark=st.context.theme.type == "dark")
PALETTE = kd.TL_PALETTE_DARK if st.context.theme.type == "dark" else kd.TL_PALETTE

if st.query_params.get("readonly") is not None:
    st.session_state["readonly"] = st.query_params.get("readonly") in ("1", "true", "yes", "True")
READONLY = st.session_state.get("readonly", False)


def _clean(value):
    v = str(value).strip()
    return "" if v in ("", "nan", "None") else v


def render_tool_card(row, faded=False):
    """`faded=True` (the Deprecated section) grays the whole card out via markdown's :gray[]
    rather than real CSS opacity -- Streamlit widgets can't be wrapped in an injected <div>
    across multiple st calls, so this is the robust way to make a card read as secondary."""
    deprecated = _clean(row["Status"]) == "Deprecated"
    name = _clean(row["Name"])
    title = f"### {name}" if not faded else f"### :gray[{name}]"
    st.markdown(title)
    if deprecated:
        reason = _clean(row["Why deprecated"])
        st.caption("🗃️ Deprecated" + (f" — {reason}" if reason else ""))

    meta = " · ".join(
        part for part in (
            _clean(row["Type of tool"]),
            f"built in {_clean(row['Built in'])}" if _clean(row["Built in"]) else "",
            f"use: {_clean(row['Use'])}" if _clean(row["Use"]) else "",
            f"origin: {_clean(row['Project Origin'])}" if _clean(row["Project Origin"]) else "",
        ) if part
    )
    if meta:
        st.caption(meta)

    desc_lines = [p.strip() for p in _clean(row["Description"]).split(";") if p.strip()]
    if faded:
        for part in desc_lines:
            st.markdown(f":gray[- {part}]")
        if _clean(row["Limitations"]):
            st.markdown(f":gray[**-** {_clean(row['Limitations'])}]")
        if _clean(row["Future gain"]):
            st.markdown(f":gray[**→** {_clean(row['Future gain'])}]")
    else:
        for part in desc_lines:
            st.markdown(f"- {part}")
        if _clean(row["Limitations"]):
            st.markdown(f":red[**-** {_clean(row['Limitations'])}]")
        if _clean(row["Future gain"]):
            st.markdown(f":blue[**→** {_clean(row['Future gain'])}]")

    steps = kd.parse_tool_steps(row["Steps"])
    if steps:
        st.dataframe(pd.DataFrame(steps, columns=kd.TOOL_STEPS_COLUMNS),
                     hide_index=True, width="stretch")


def pick_or_new(label, options, current, key):
    """One dropdown that also accepts a brand-new value typed into it. Deliberately not a
    dropdown plus a separate text box: inside an st.form, pressing Enter in a text box
    submits the whole form, which would save the record half-filled."""
    choices = sorted({o for o in options if o})
    if current and current not in choices:
        choices = [current] + choices
    value = st.selectbox(
        label, choices, index=choices.index(current) if current in choices else None,
        key=f"{key}_sel", accept_new_options=True, placeholder="pick one, or type a new value",
    )
    return (value or "").strip()


def render_tool_editor(tools_df, row):
    """The pencil under a tool's card: opens that tool's full record for editing in place,
    renaming included, and saves straight back to tools.xlsx."""
    current = _clean(row["Name"])
    key = "".join(ch for ch in current if ch.isalnum()) or "tool"
    names = sorted({_clean(n) for n in tools_df["Name"] if _clean(n)})

    with st.expander("✏️ Edit this tool"):
        with st.form(f"edit_tool_{key}"):
            new_name = st.text_input("Name", value=current, key=f"tname_{key}")
            description = st.text_area(
                "Description (use ';' to split into bullet points)",
                value=_clean(row["Description"]), height=90, key=f"tdesc_{key}",
            )
            type_of_tool = pick_or_new("Type of tool", tools_df["Type of tool"].map(_clean),
                                       _clean(row["Type of tool"]), f"ttype_{key}")
            built_in = pick_or_new("Built in", tools_df["Built in"].map(_clean),
                                   _clean(row["Built in"]), f"tbuilt_{key}")
            use = pick_or_new("Use", tools_df["Use"].map(_clean), _clean(row["Use"]), f"tuse_{key}")
            origin = pick_or_new("Project Origin", tools_df["Project Origin"].map(_clean),
                                 _clean(row["Project Origin"]), f"torigin_{key}")
            limitations = st.text_area("Limitations", value=_clean(row["Limitations"]), key=f"tlim_{key}")
            future_gain = st.text_area("Future gain", value=_clean(row["Future gain"]), key=f"tgain_{key}")
            steps = st.text_area(
                "Steps breakdown (optional) — one row per line",
                value=_clean(row["Steps"]), key=f"tsteps_{key}", height=100,
                help="One row per line, as Step / How / AI involved?. Paste straight out of "
                     "Excel (tab-separated), or type a row by hand with ' | ' between columns, "
                     "e.g. 'GitHub repo + push | Cookiecutter + git, on qds | No'.",
            )
            st.caption("Deprecated = still on record, but not the thing to reach for anymore -- "
                       "it moves to its own (faded) section below instead of the gallery/overview.")
            dep_col, sup_col = st.columns([1, 2])
            current_status = _clean(row["Status"])
            deprecated = dep_col.checkbox("Deprecated", value=current_status == "Deprecated",
                                          key=f"tdep_{key}")
            why_deprecated = sup_col.text_input(
                "Why deprecated", value=_clean(row["Why deprecated"]), key=f"tsup_{key}",
                placeholder="e.g. integrated into Project Closer, or no longer needed",
                disabled=not deprecated,
            )

            if st.form_submit_button("💾 Save tool"):
                clean_name = new_name.strip()
                others = [n for n in names if n != current]
                if not clean_name:
                    st.error("Name can't be empty.")
                elif clean_name in others:
                    st.error(f"Another tool is already called \"{clean_name}\" — pick a different name.")
                else:
                    edited = tools_df.copy()
                    mask = edited["Name"].astype(str).str.strip() == current
                    for col, value in (("Name", clean_name), ("Description", description),
                                       ("Type of tool", type_of_tool), ("Built in", built_in),
                                       ("Use", use), ("Project Origin", origin),
                                       ("Limitations", limitations), ("Future gain", future_gain),
                                       ("Status", "Deprecated" if deprecated else ""),
                                       ("Why deprecated", why_deprecated if deprecated else ""),
                                       ("Steps", steps)):
                        edited.loc[mask, col] = value
                    try:
                        kd.save_tools(edited)
                    except PermissionError:
                        st.error("Couldn't save — tools.xlsx is open in Excel (or locked by "
                                 "OneDrive). Close it and save again.")
                    else:
                        # The grid below caches its own edits against the old values.
                        st.session_state.pop("tools_editor", None)
                        st.success("Saved to tools.xlsx. Reloading...")
                        st.rerun()


ks.header("Tools & AI Skills")
page_nav([("Overview", "tools-overview"), ("Gallery", "tools-gallery"), ("All tools", "tools-table")])
st.caption("Everything built along the way — pipelines, dashboards, and AI Skills — read live from tools.xlsx.")

try:
    tools_df = kcache.load_tools()
except FileNotFoundError:
    st.error(f"tools.xlsx not found in {kd.DATA_DIR} — create it with at least the columns: "
             + ", ".join(kd.TOOLS_COLS) + ".")
    st.stop()
except PermissionError:
    st.error("Couldn't read tools.xlsx — it's open in Excel (or locked by OneDrive). "
             "Close it and refresh this page.")
    st.stop()

if not len(tools_df):
    st.info("tools.xlsx has no rows yet — add your first tool below.")
else:
    is_deprecated = tools_df["Status"].astype(str).str.strip() == "Deprecated"
    active_tools = tools_df[~is_deprecated]
    deprecated_tools = tools_df[is_deprecated]

    # --- Overview: headline numbers + breakdown charts --------------------------------------
    # Deprecated tools are still on record (full table, editable), but a retired tool isn't
    # part of "what's built and in use" -- the overview/gallery count and chart only active
    # ones, the same way a closed project drops out of the turnaround page's live figures.
    anchor("tools-overview")
    types = active_tools["Type of tool"].astype(str).str.strip()
    n_ai_skills = int(types.str.contains("AI Skill", case=False, na=False).sum())
    built_vals = active_tools["Built in"].astype(str).str.strip().replace("nan", "")
    latest_period = max((v for v in built_vals if v), default="")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Tools built", len(active_tools),
              delta=f"{len(deprecated_tools)} deprecated" if len(deprecated_tools) else None,
              delta_color="off")
    m2.metric("AI Skills", n_ai_skills)
    m3.metric("Tool types", int(types.replace("", pd.NA).nunique(dropna=True)))
    m4.metric(f"Built in {latest_period}" if latest_period else "Built this period",
              int((built_vals == latest_period).sum()) if latest_period else 0)

    st.caption("Hover a bar to see which tools it covers.")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.plotly_chart(kc.fig_tools_counts(active_tools["Type of tool"], "By type of tool",
                                            PALETTE[0], names=active_tools["Name"]), width="stretch")
    with c2:
        st.plotly_chart(kc.fig_tools_counts(active_tools["Use"], "By use",
                                            PALETTE[2], names=active_tools["Name"]), width="stretch")
    with c3:
        st.plotly_chart(kc.fig_tools_counts(active_tools["Project Origin"], "By project origin",
                                            PALETTE[1], names=active_tools["Name"]), width="stretch")

    # --- Gallery: filterable cards -----------------------------------------------------------
    st.subheader("Gallery", anchor="tools-gallery")
    f1, f2, _ = st.columns([1.2, 1.2, 2])
    type_options = sorted({_clean(v) for v in active_tools["Type of tool"] if _clean(v)})
    use_options = sorted({_clean(v) for v in active_tools["Use"] if _clean(v)})
    type_filter = f1.multiselect("Type of tool", type_options, key="tools_type_filter")
    use_filter = f2.multiselect("Use", use_options, key="tools_use_filter")
    if not READONLY:
        st.caption("Use the ✏️ under a card to edit that tool — changes save to tools.xlsx.")

    shown = active_tools
    if type_filter:
        shown = shown[shown["Type of tool"].astype(str).str.strip().isin(type_filter)]
    if use_filter:
        shown = shown[shown["Use"].astype(str).str.strip().isin(use_filter)]

    if not len(shown):
        st.caption("No tools match the selected filters.")
    cols = st.columns(2)
    for i, (_, row) in enumerate(shown.iterrows()):
        with cols[i % 2]:
            with st.container(border=True):
                render_tool_card(row)
                if not READONLY:
                    render_tool_editor(tools_df, row)

    # --- Deprecated: same full card, just faded, and out of the counts/charts above ---------
    if len(deprecated_tools):
        with st.expander(f"🗃️ Deprecated ({len(deprecated_tools)})", expanded=False):
            st.caption("No longer the thing to reach for, for whatever reason — kept here "
                       "for the record rather than deleted.")
            dep_cols = st.columns(2)
            for i, (_, row) in enumerate(deprecated_tools.iterrows()):
                with dep_cols[i % 2]:
                    with st.container(border=True):
                        render_tool_card(row, faded=True)
                        if not READONLY:
                            render_tool_editor(tools_df, row)

# --- Full table ------------------------------------------------------------------------------
st.subheader("All tools", anchor="tools-table")
if READONLY:
    st.dataframe(tools_df, width="stretch", hide_index=True)
else:
    st.caption("Edit any cell, or add a new row (Name is required), then save.")
    edited = st.data_editor(
        tools_df, num_rows="dynamic", width="stretch", key="tools_editor",
        column_config={
            "Name": st.column_config.TextColumn("Name", required=True),
            "Description": st.column_config.TextColumn("Description", width="large"),
            "Status": st.column_config.SelectboxColumn("Status", options=kd.TOOL_STATUS_OPTIONS),
            "Why deprecated": st.column_config.TextColumn("Why deprecated"),
        },
    )
    if st.button("💾 Save changes to tools.xlsx"):
        try:
            kd.save_tools(edited)
        except PermissionError:
            st.error("Couldn't save — tools.xlsx is open in Excel (or locked by OneDrive). "
                     "Close it and click Save again; your edits are still in the table above.")
        else:
            st.success("Saved. Reloading...")
            st.rerun()
