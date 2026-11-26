"""Editors for the dashboard-owned gains store (Data/gains.xlsx).

Everything the Gains & Outputs page draws used to be hand-maintained in an Excel workbook that
this dashboard could only ever READ (it carried charts and formulas openpyxl would destroy on
save -- see kd.GAINS_PATH's comment). gains.xlsx replaced it as a plain, writable store, and
these are the controls that write it:

  - render_reuse_editor   -- on every Special Project and Tool card (pages 2 and 3): what user
                             projects fed this development, what it serves, whether it's
                             constant-use, and which other development it grew out of. The last
                             of those is what grows the lineage tree, so the two live in one
                             control rather than two: they are one cell on the Reuse sheet.
  - render_gain_toggles   -- the Gains page's own grid: developments down, gain types across,
                             a checkbox per cell. Also where a new development gets its row.
  - render_value_editor   -- the Value sheet's market-equivalent prices as an editable table.

They all write through kd.save_gains_sheets, which rewrites the whole file: the sheets
cross-reference each other by ID, and a part-written file would leave the page reading a Gains
row for a development Overview no longer lists.

None of them are cached. Reads go through kpi_cache.load_gains_sheets (mtime-keyed, so one read
is shared by all 16 cards on the Tools page rather than one read per card), and a save bumps
that mtime, so the next rerun picks the change up with no explicit cache clearing anywhere.
"""

import pandas as pd
import streamlit as st

import kpi_cache as kcache
import kpi_data as kd

# What "Category" means on the Overview sheet -- the two series ids are numbered in
# (see kd.next_development_id). Spelled here rather than inline so the Add form and the id
# generator can't drift apart.
CATEGORIES = ["Special Project", "Tools"]

_LOCKED_MSG = ("Couldn't save — gains.xlsx is open in Excel (or locked by OneDrive). Close it "
               "and save again; your edits are still on screen.")


def _clean(value):
    """One cell -> a trimmed string, with pandas' several flavours of empty all collapsing to
    "". Excel round-trips a blank as NaN, a cleared data_editor cell as None, and a
    never-filled object column as the literal "nan", and all three mean the same thing here."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).strip()
    return "" if text.lower() in ("nan", "none") else text


def _dev_row(name, overview):
    """The Overview row for a live Special Project / tool name, or None if it has no row yet.

    Matched through kd._name_variants, not on the literal text: the gains store and the live
    ratings sheet / tools.xlsx spell a few of these differently on purpose (NAME_ALIASES), and
    an editor that missed those would offer to "add" a development that is already tracked."""
    wanted = kd._name_variants(name)
    for _, row in overview.iterrows():
        if kd._name_variants(row["Project"]) & wanted:
            return row
    return None


def _split_tokens(cell):
    """A "Came from"/"served" cell -> its comma-separated tokens, blanks dropped."""
    return [t.strip() for t in _clean(cell).split(",") if t.strip()]


# --- Reuse + lineage, as one control -------------------------------------------------------

def _project_options(project_lookup):
    """{display label: project id} for every project tag the tracker knows, across all
    reporting periods. The label carries the real title so picking DNA_031 out of a list of
    forty ids is possible; the id is what gets written."""
    options = {}
    for pid in sorted(project_lookup or {}):
        options[kd.project_lookup_label(pid, project_lookup)] = pid
    return options


def _parent_options(overview, tools_df, exclude_id):
    """{display label: token} for everything that could be named as a lineage PARENT.

    Two kinds, deliberately in one list: a development this store already tracks (written as
    its own id, e.g. SP01 -- stable across renames) and a live tool with no row here at all
    (written by name, e.g. motif-scan-from-github -- which is how a retired tool that a
    tracked development grew out of gets onto the lineage tree without needing gains of its
    own). `exclude_id` keeps a development out of its own parent list."""
    options, seen = {}, set()
    for _, row in overview.iterrows():
        if row["ID"] == exclude_id:
            continue
        options[f"{row['Project']}  ·  {row['ID']}"] = row["ID"]
        seen |= kd._name_variants(row["Project"])
    if tools_df is not None:
        for name in tools_df["Name"]:
            name = _clean(name)
            if not name or kd._name_variants(name) & seen:
                continue
            options[f"{name}  ·  not tracked here"] = name
    return options


def _labels_for(tokens, options):
    """Pre-select the multiselect: the labels whose token is already in the cell. A token with
    no option (a project id since removed from the tracker, a typo from the Excel days) is
    carried through as its own label so saving doesn't silently delete it."""
    by_token = {v: k for k, v in options.items()}
    return [by_token.get(t, t) for t in tokens]


def _save_reuse(dev_id, project_ids, parent_tokens, serves_ids, constant_use):
    """Write one Reuse row back. Both lists go into the SAME "Came from" cell -- user project
    ids and lineage parents are one column by design (kd._classify_lineage_token sorts them
    out on read), with the ids first so the cell still reads naturally in Excel.

    "Came from (n)" is only touched when ids are actually listed. A handful of rows carry a
    typed count with no ids (OmicsXplorer, Curated MS-omics tools, omics-inputs-agent: "built
    out of 1 project, we never wrote down which"), and clearing the list must not throw that
    away -- it is real information this editor has no way to recover."""
    sheets = kd.load_gains_sheets()
    reuse = sheets["Reuse"]
    mask = reuse["ID"] == dev_id
    if not mask.any():
        raise KeyError(dev_id)
    # A column that happens to be empty in the file comes back from pandas as float64 (all
    # NaN), and writing text into one row of it is deprecated and will raise in a later
    # pandas. Both of these genuinely hold text -- "User projects served (n)" carries the
    # literal "Constant use" alongside numbers -- so cast up front rather than per write.
    for col in ("Came from: user projects", "User projects served: list",
                 "User projects served (n)"):
        if col in reuse.columns:
            reuse[col] = reuse[col].astype(object)
    reuse.loc[mask, "Came from: user projects"] = ", ".join(project_ids + parent_tokens)
    reuse.loc[mask, "User projects served: list"] = ", ".join(serves_ids)
    if project_ids:
        reuse.loc[mask, "Came from (n)"] = len(project_ids)
    reuse.loc[mask, "User projects served (n)"] = (
        "Constant use" if constant_use else (len(serves_ids) if serves_ids else "")
    )
    kd.save_gains_sheets(sheets)


def add_development(name, category, goal, status, output_level):
    """Give a live tool / Special Project a row in the gains store, and return its new id.

    Adds the row to Overview, Gains and Reuse together -- all three are keyed by ID and the
    page joins across them, so a development present in one and missing from another is the
    one state that actually breaks a chart. Gains and Reuse start empty: a new development
    claims no gains until someone ticks them, which is the honest default and is exactly what
    the grid is for. Value stays untouched -- most developments never get a price."""
    sheets = kd.load_gains_sheets()
    overview = sheets["Overview"]
    dev_id = kd.next_development_id(overview, category)
    sheets["Overview"] = pd.concat([overview, pd.DataFrame([{
        "ID": dev_id, "Category": category, "Goal": goal, "Project": name,
        "Status": status, "Output level": output_level, "Expected gains": "",
        "Use pattern": "Project-specific",
    }])], ignore_index=True)
    for sheet_name, extra in (("Gains", {"Project": name}),
                               ("Reuse", {"Development / tool": name})):
        df = sheets[sheet_name]
        sheets[sheet_name] = pd.concat(
            [df, pd.DataFrame([{"ID": dev_id, **extra}])], ignore_index=True)
    kd.save_gains_sheets(sheets)
    return dev_id


def render_reuse_editor(name, key_prefix, readonly=False):
    """The "what fed this, what it serves" control for one development, for the card on the
    Special Projects or Tools page. Draws nothing in readonly mode.

    `name` is the live name as that page knows it (ratings sheet / tools.xlsx spelling);
    `key_prefix` only has to be unique on its page, since Streamlit widget keys are global."""
    if readonly:
        return
    try:
        sheets = kcache.load_gains_sheets()
        project_lookup = kcache.build_project_lookup()
        tools_df = kcache.load_tools()
    except (FileNotFoundError, PermissionError):
        return  # the Gains page itself reports this properly; a card just stays quiet
    overview = sheets["Overview"]
    row = _dev_row(name, overview)

    with st.expander("🔗 Reuse & lineage"):
        if row is None:
            st.caption(f"**{name}** has no row in the gains store yet, so it doesn't appear on "
                       "the Gains & Outputs page at all. Add one to start recording what it "
                       "was built out of and what it delivers.")
            st.caption("You can also add it from the Gains & Outputs page, where you can tick "
                       "its gains at the same time.")
            return

        dev_id = row["ID"]
        reuse_row = sheets["Reuse"].loc[sheets["Reuse"]["ID"] == dev_id]
        if not len(reuse_row):
            st.caption("This development is in the gains store but has no Reuse row — open the "
                       "Gains & Outputs page once to rebuild it.")
            return
        reuse_row = reuse_row.iloc[0]

        came_from = _split_tokens(reuse_row["Came from: user projects"])
        serves = _split_tokens(reuse_row["User projects served: list"])
        project_opts = _project_options(project_lookup)
        parent_opts = _parent_options(overview, tools_df, dev_id)
        # One cell, two kinds of token: anything matching a user-project id is a project, the
        # rest is a lineage parent (same split kd._classify_lineage_token makes on read).
        from_projects = [t for t in came_from if kd._USER_PROJECT_ID_RE.match(t)]
        from_parents = [t for t in came_from if not kd._USER_PROJECT_ID_RE.match(t)]

        with st.form(f"reuse_{key_prefix}"):
            st.caption(f"Recorded against **{dev_id}** in the gains store.")
            picked_from = st.multiselect(
                "Built out of — user projects", list(project_opts),
                default=_labels_for(from_projects, project_opts), key=f"rf_{key_prefix}",
                help="The user projects whose work this was built out of. Each one also counts "
                     "toward 'built out of real user projects' on the Gains page.",
            )
            picked_parents = st.multiselect(
                "Grew out of — another tool or special project", list(parent_opts),
                default=_labels_for(from_parents, parent_opts), key=f"rp_{key_prefix}",
                help="Names the parent this one evolved from. This is what draws the Lineage "
                     "tree, and it also counts as proof the parent is in use.",
            )
            picked_serves = st.multiselect(
                "Benefits — user projects that build on it", list(project_opts),
                default=_labels_for(serves, project_opts), key=f"rs_{key_prefix}",
                help="Listing even one here is enough to move this development out of "
                     "'Potential' on the Gains page.",
            )
            constant = st.checkbox(
                "Constant use — used daily / by everyone, not tied to countable projects",
                value=bool(reuse_row["User projects served (n)"] == "Constant use"),
                key=f"rc_{key_prefix}",
            )
            if st.form_submit_button("💾 Save reuse & lineage"):
                try:
                    _save_reuse(
                        dev_id,
                        [project_opts.get(p, p) for p in picked_from],
                        [parent_opts.get(p, p) for p in picked_parents],
                        [project_opts.get(p, p) for p in picked_serves],
                        constant,
                    )
                except PermissionError:
                    st.error(_LOCKED_MSG)
                else:
                    st.success("Saved to gains.xlsx. Reloading...")
                    st.rerun()


# --- The Gains page's own grid and tables --------------------------------------------------

def render_gain_toggles(sheets, gain_columns, state_by_id):
    """Developments x gain types as a checkbox grid, plus the form that adds a development.

    This is the editable face of exactly what "What delivers what" draws: tick a box and a dot
    appears there. Rows are shown in the store's own order (not the chart's state-sorted one)
    so a row doesn't jump somewhere else the moment ticking a box changes its state."""
    gains = sheets["Gains"]
    display = pd.DataFrame({
        "Development": [_clean(v) for v in gains["Project"]],
        "State": [kd.GAIN_STATE_LABELS.get(state_by_id.get(i), "") for i in gains["ID"]],
    })
    for gain in gain_columns:
        display[gain] = [_clean(v).lower() == "x" for v in gains.get(gain, "")]

    edited = st.data_editor(
        display, hide_index=True, width="stretch", key="gain_toggles",
        disabled=["Development", "State"],
        column_config={
            "Development": st.column_config.TextColumn("Development / tool", width="medium"),
            "State": st.column_config.TextColumn("State", width="small", help=
                "Decided from live Special Projects / Tools status — not editable here."),
            **{g: st.column_config.CheckboxColumn(g, width="small") for g in gain_columns},
        },
    )
    if st.button("💾 Save gains", key="save_gain_toggles"):
        out = sheets["Gains"].copy()
        for gain in gain_columns:
            out[gain] = ["x" if bool(v) else "" for v in edited[gain]]
        sheets["Gains"] = out
        try:
            kd.save_gains_sheets(sheets)
        except PermissionError:
            st.error(_LOCKED_MSG)
        else:
            st.success("Saved to gains.xlsx. Reloading...")
            st.rerun()


def render_add_development(sheets, candidates):
    """Give something a row in the gains store. `candidates` is what the Data health check
    already knows is missing (live tools and Special Projects with no row here), offered as a
    dropdown so the name matches the live one exactly -- a typed name that differs by a word
    creates a second, unlinked development whose state can never resolve."""
    overview = sheets["Overview"]
    with st.form("add_development"):
        if candidates:
            name = st.selectbox(
                "Development / tool", candidates,
                help="Everything on the Tools or Special Projects pages that has no row here yet.",
            )
        else:
            name = st.text_input("Development / tool")
            st.caption("Every live tool and Special Project already has a row — typing a name "
                       "here creates one that nothing else on the dashboard knows about, so "
                       "its state will stay Potential until a matching one exists.")
        col_a, col_b = st.columns(2)
        category = col_a.selectbox("Category", CATEGORIES)
        goal = col_b.selectbox("Goal", sorted({_clean(g) for g in overview["Goal"] if _clean(g)}))
        col_c, col_d = st.columns(2)
        status = col_c.selectbox(
            "Status", sorted({_clean(s) for s in overview["Status"] if _clean(s)}))
        output_level = col_d.selectbox(
            "Output level", sorted({_clean(o) for o in overview["Output level"] if _clean(o)}))
        if st.form_submit_button("➕ Add to the gains store"):
            clean_name = _clean(name)
            if not clean_name:
                st.error("Pick or type a name first.")
            elif _dev_row(clean_name, overview) is not None:
                st.error(f"\"{clean_name}\" already has a row here.")
            else:
                try:
                    new_id = add_development(clean_name, category, goal, status, output_level)
                except PermissionError:
                    st.error(_LOCKED_MSG)
                else:
                    st.success(f"Added as {new_id}. Tick its gains in the grid above. Reloading...")
                    st.rerun()


def render_value_editor(sheets):
    """The Value sheet as an editable table: which developments have a researched
    market-equivalent price, and what it's based on.

    Development is a dropdown over what the store already tracks, not free text -- the row is
    stored by ID, so a name that matches nothing has nowhere to attach and would vanish on the
    next save."""
    overview = sheets["Overview"]
    names = [_clean(p) for p in overview["Project"]]
    id_by_name = dict(zip(names, overview["ID"]))
    value = sheets["Value"]
    display = pd.DataFrame({
        "Project": [_clean(v) for v in value["Project"]],
        "Audience": [_clean(v) for v in value["Audience"]],
        "Value basis": [_clean(v) for v in value["Value basis"]],
        "Unit price (€)": pd.to_numeric(value["Unit price (€)"], errors="coerce"),
        "Unit": [_clean(v) for v in value["Unit"]],
    })
    edited = st.data_editor(
        display, hide_index=True, width="stretch", num_rows="dynamic", key="value_editor",
        column_config={
            "Project": st.column_config.SelectboxColumn(
                "Development / tool", options=names, width="medium", required=True),
            "Audience": st.column_config.TextColumn("Audience", width="small"),
            "Value basis": st.column_config.TextColumn(
                "What the price is based on", width="large"),
            "Unit price (€)": st.column_config.NumberColumn(
                "Market equivalent (€)", min_value=0, step=1, format="%.0f",
                help="Leave blank when no price was researched — the basis text still shows."),
            "Unit": st.column_config.TextColumn("per", width="small",
                                                 help="e.g. sample, analysis, month"),
        },
    )
    if st.button("💾 Save value potential", key="save_value"):
        rows = edited[[bool(_clean(p)) for p in edited["Project"]]]
        unknown = [_clean(p) for p in rows["Project"] if _clean(p) not in id_by_name]
        if unknown:
            st.error("Not a development this store tracks: " + ", ".join(sorted(set(unknown))))
            return
        sheets["Value"] = pd.DataFrame({
            "ID": [id_by_name[_clean(p)] for p in rows["Project"]],
            "Project": [_clean(p) for p in rows["Project"]],
            "Audience": [_clean(v) for v in rows["Audience"]],
            "Value basis": [_clean(v) for v in rows["Value basis"]],
            "Unit price (€)": list(rows["Unit price (€)"]),
            "Unit": [_clean(v) for v in rows["Unit"]],
        })
        try:
            kd.save_gains_sheets(sheets)
        except PermissionError:
            st.error(_LOCKED_MSG)
        else:
            st.success("Saved to gains.xlsx. Reloading...")
            st.rerun()
