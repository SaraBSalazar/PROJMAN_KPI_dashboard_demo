"""Gains & Outputs — what the Special Projects and Tools built along the way are expected to
deliver, and how much of that is Delivered / In use / still Potential, read live from
SpecialProjects_Tools_expected_gains_v5.xlsx (kd.load_expected_gains, folded together with the
live Special Projects and Tools status). Entirely read-only: this page has no editor, no
save button, nothing it writes back -- the workbook and the 3-state rule both live in
kpi_data.py (kd._decide_state)."""

import html as _html

import pandas as pd
import streamlit as st

import kpi_cache as kcache
import kpi_charts as kc
import kpi_data as kd
import kpi_style as ks
from kpi_style import anchor, page_nav

st.set_page_config(page_title="Gains & Outputs", page_icon="💡", layout="wide")
kc.set_theme(dark=st.context.theme.type == "dark")
ks.inject(dark=st.context.theme.type == "dark")
# Delivered green / In use blue / Potential grey -- a named status palette, not a sequential
# ramp (see kd.GAIN_STATE_COLORS' own docstring comment for why). The dark triple is picked
# independently so Delivered stays the most prominent against a dark surface too.
STATE_COLORS = kd.GAIN_STATE_COLORS_DARK if st.context.theme.type == "dark" else kd.GAIN_STATE_COLORS
# The 4 gain-theme group colours (axis bands/labels only, never the data marks -- only ever
# drawn in fig_gains_active_potential/fig_gains_matrix) -- re-picked per-theme now that the
# state palette above needed its own dark variant (see kd.GAIN_GROUP_COLORS' docstring for the
# full story, including why ADA's orange is deliberately NOT part of this constraint set).
GROUP_COLORS = kd.GAIN_GROUP_COLORS_DARK if st.context.theme.type == "dark" else kd.GAIN_GROUP_COLORS
# The ADA/Personal audience row's own identity colour -- orange, used ONLY in
# fig_audience_outputs (never alongside the group colours above, which live in two different
# charts), kept theme-matched the same way STATE_COLORS is.
ADA_COLOR = kd.ADA_PERSONAL_COLOR_DARK if st.context.theme.type == "dark" else kd.ADA_PERSONAL_COLOR

if st.query_params.get("readonly") is not None:
    st.session_state["readonly"] = st.query_params.get("readonly") in ("1", "true", "yes", "True")
READONLY = st.session_state.get("readonly", False)  # no editing controls live here either way


ks.header(
    "Gains & Outputs",
    "What the Special Projects and tools built along the way are expected to deliver -- "
    "and how much of that is already being delivered, vs. still ahead.",
)
page_nav([
    ("Overview", "gains-overview"),
    ("Delivered / in use / potential", "gains-active-potential"),
    ("What delivers what", "gains-matrix"),
    ("Audience & value", "gains-audience"),
    ("Reuse", "gains-reuse"),
    ("Lineage: evolution", "gains-lineage-tree"),
    ("Lineage: cards", "gains-lineage-cards"),
    ("Data health", "gains-health"),
])
st.caption("Read live from Data/SpecialProjects_Tools_expected_gains_v5.xlsx, cross-checked "
           "against live Special Projects and Tools status.")

try:
    data = kcache.load_expected_gains()
except FileNotFoundError:
    st.error(f"SpecialProjects_Tools_expected_gains_v5.xlsx not found in {kd.DATA_DIR} -- "
             "this page has nothing to read from until that workbook exists.")
    st.stop()
except PermissionError:
    st.error("Couldn't read the gains workbook (or one of the files it cross-checks against -- "
             "Special_Projects_Ratings.xlsx, tools.xlsx). It's open in Excel (or locked by "
             "OneDrive) -- close it and refresh this page.")
    st.stop()

developments = data["developments"]
gains_long = data["gains_long"]
gain_summary = data["gain_summary"]
gain_columns = data["gain_columns"]
gain_groups = data["gain_groups"]
ungrouped_gains = data["ungrouped_gains"]
reuse = data["reuse"]
value = data["value"]
notes = data["notes"]
unmatched_tools = data["unmatched_tools"]
unmatched_projects = data["unmatched_projects"]
unmatched_reuse_ids = data["unmatched_reuse_ids"]
project_lookup = data["project_lookup"]
IN_USE_LABEL = kd.GAIN_STATE_LABELS["In use"]

# --- Overview: headline numbers + the Delivered/In use/Potential rule, in plain language ----
anchor("gains-overview")
n_dev = len(developments)
n_delivered = int((developments["state"] == "Delivered").sum())
n_in_use = int((developments["state"] == "In use").sum())
n_potential = int((developments["state"] == "Potential").sum())
n_gain_types = len(gain_summary)
n_untouched = int((gain_summary["n_active"] == 0).sum())
n_built_out = int(reuse["came_from_n"].notna().sum())
n_external = int(developments["External users"].sum())
n_market = int(developments["Market-equivalent value"].sum())

r1 = st.columns(4)
r1[0].metric("Developments", n_dev)
r1[1].metric("Delivered", n_delivered)
r1[2].metric(IN_USE_LABEL, n_in_use)
r1[3].metric("Still potential", n_potential)

r2 = st.columns(4)
r2[0].metric("Gains with nothing delivered yet", f"{n_untouched} of {n_gain_types}")
r2[1].metric("Built out of real user projects", n_built_out)
r2[2].metric("With external users", n_external)
r2[3].metric("With a market equivalent", n_market)

with st.expander(f"ℹ️ How 'Delivered', '{IN_USE_LABEL}' and 'Potential' are decided"):
    st.markdown(
        "Every development sits on a 3-step ladder, and the call is made from LIVE dashboard "
        "data wherever possible, not from this workbook's own say-so:\n\n"
        "- **Delivered** -- a Special Project you've ticked **✅ Project finished** on the "
        "Special Projects page (saved to `Special_Projects_Ratings.xlsx`). Its gains are "
        "banked; there's no more work expected.\n"
        f"- **{IN_USE_LABEL}** -- not finished, but demonstrably being used already (the "
        "underlying state is still called \"In use\" everywhere in the data -- only this "
        "label spells out that it covers something still being actively built/iterated on "
        "too, e.g. Pipeline/OMICs Pipelines). Any ONE of these moves it here: it serves a "
        "real user project (listed under **User projects served** on the Reuse sheet), OR "
        "another development names it as where **it** came from (listed under that other "
        "development's **Came from**, on the Reuse sheet -- having spawned something else is "
        "itself proof of use), OR it's a **Tool** not marked **Deprecated** on the Tools page "
        "(tools are living things with no \"Completed\" concept -- they're in use until "
        "retired).\n"
        "- **Potential** -- none of the above yet; the gains are real but still ahead of it.\n\n"
        f"So to move a Special Project from Potential to {IN_USE_LABEL} without waiting for "
        "it to finish: add a user project id (`GEN_###` / `PROT_###`) under **User projects "
        "served**, or add it to another development's **Came from** list, on the Reuse sheet.\n\n"
        "Where none of this finds a match by name (a development this workbook tracks but the "
        "other pages don't recognize the same way), it falls back to the workbook's own "
        "**Status** column as a best guess -- shown as `match_source = \"status\"` in the "
        "underlying data, versus `\"ratings\"` or `\"tools\"` for a live match."
    )

# --- Delivered / in use / potential gains --------------------------------------------------
st.subheader("Delivered, in use & potential gains", anchor="gains-active-potential")


def _insight_caption(gain_summary):
    """Derived from the data each time, not hardcoded to today's counts -- stays true to the
    rule ('inward-facing gains are largely banked, outward-facing ones are still ahead') even
    as the underlying numbers shift."""
    efficiency = gain_summary[gain_summary["Group"] == "Efficiency"]
    outward = gain_summary[gain_summary["Group"].isin(["Innovation & visibility", "Reach & relationships"])]
    eff_active, eff_total = int(efficiency["n_active"].sum()), int(efficiency["n_total"].sum())
    out_active, out_total = int(outward["n_active"].sum()), int(outward["n_total"].sum())
    eff_pct = f"{eff_active / eff_total:.0%}" if eff_total else "—"
    out_pct = f"{out_active / out_total:.0%}" if out_total else "—"
    return (f"Efficiency gains are {eff_pct} delivered so far ({eff_active}/{eff_total}) -- "
            f"outward-facing gains (innovation & visibility, reach & relationships) are "
            f"only {out_pct} delivered ({out_active}/{out_total}). The internal payoff is "
            f"largely banked; the outward-facing one is still ahead.")


st.plotly_chart(kc.fig_gains_active_potential(gain_summary, STATE_COLORS, GROUP_COLORS), width="stretch")
st.caption(f"Bar colour is still Delivered/{IN_USE_LABEL}/Potential throughout -- the coloured "
           "band and name on the right mark which of the 4 gain themes (Efficiency, Capability, "
           "Innovation & visibility, Reach & relationships) each block of rows belongs to.")
st.caption(_insight_caption(gain_summary))

# --- What delivers what ------------------------------------------------------------------
st.subheader("What delivers what", anchor="gains-matrix")
st.caption(f"Every dot in a row shares that development's state -- Delivered developments read "
           f"green, {IN_USE_LABEL} blue, Potential grey (and hatched), top to bottom. Every dot "
           "is filled: a gap here means that development doesn't deliver that gain, never that "
           f"it's only potential. The coloured header strip above the columns groups the "
           f"{len(gain_columns)} gains into their 4 themes -- same colours and same grouping as "
           "the chart above.")
st.plotly_chart(
    kc.fig_gains_matrix(gains_long, developments, STATE_COLORS, gain_columns, gain_groups, GROUP_COLORS),
    width="stretch",
)

# --- Audience & outputs, alongside the value-potential block ------------------------------
st.subheader("Audience & outputs", anchor="gains-audience")
col_a, col_b = st.columns([1.3, 1])
with col_a:
    st.plotly_chart(kc.fig_audience_outputs(developments, STATE_COLORS, ADA_COLOR), width="stretch")
    st.caption("**ADA / Personal** (orange marker) is the innermost tier -- built for ADA or "
               "personal/internal use (`Output level` = Internal ADA or Internal Worker), inward-facing in a "
               "way even the **Internal users** row below it isn't: that row and **External "
               "users** are both about outside *users*, just at different distances, while "
               "ADA/Personal is about work that never left the building at all.")
with col_b:
    st.markdown("**Value potential**")
    st.caption(
        "Researched market prices for what an equivalent service would cost elsewhere -- "
        "shown only to convey *potentiality*, the scale of what these developments stand in "
        "for. They are not income, and nothing below is ever totalled."
    )
    if len(value):
        display = value.copy()

        def _price(row):
            """Blank rather than an invented number when no price was researched -- the basis
            text already sits in its own column, so repeating it here would just read as a
            price that isn't one."""
            if row["unit_price"] is None:
                return "—"
            unit = str(row.get("Unit", "")).strip()
            unit = "" if unit.lower() in ("", "nan", "none") else f" / {unit}"
            return f"€{row['unit_price']:,.0f}{unit}"

        display["Price"] = [_price(row) for _, row in display.iterrows()]
        display["Status"] = display["state"]
        st.dataframe(
            display[["Project", "Value basis", "Price", "Status"]],
            hide_index=True, width="stretch",
        )
    else:
        st.caption("No value rows recorded yet.")

# --- Reuse: built out of real user work, and who benefits from it --------------------------
st.subheader("Reuse: built out of real user work, and who benefits", anchor="gains-reuse")
st.plotly_chart(kc.fig_reuse_both_directions(reuse, STATE_COLORS, project_lookup), width="stretch")
if not reuse["serves_project_ids"].map(len).sum():
    st.caption("The right-hand 'benefits' side is empty because nothing is listed yet under "
               "**User projects served** on the Reuse sheet -- it's not broken, there's just "
               "no data there yet. Add user project ids (`GEN_###` / `PROT_###`) to that column "
               "for a development and this chart's right half fills in on its own.")
constant_use_names = list(reuse.loc[reuse["constant_use"], "Development / tool"])
if constant_use_names:
    st.caption("Constant-use (no project count, by the workbook's own convention -- these are "
               "used daily/by everyone rather than tied to a countable number of projects): "
               + ", ".join(constant_use_names))

# --- Lineage Part A: a TREE of development -> development evolution, and nothing else -------
# Deliberately split out of the reuse picture above: "built from user work" (14 edges in
# today's workbook) and "benefits" (0) used to share a chart with "evolved into" (also 0 today),
# and the handful of "evolved into" edges this chart exists to surface were the least visible
# thing in it. User-project ids never appear here at all -- that's the whole point of the split
# -- they live in the Reuse chart above and the development cards below instead.
st.subheader("Lineage: development evolution", anchor="gains-lineage-tree")
st.caption("ONLY development/tool -> development/tool edges -- a Special Project or tool "
           "literally spawning another, e.g. a tool later folded into a dashboard. No "
           "user-project id is ever drawn on this chart. Shape is Special Project / Tool / AI "
           f"Skill; fill is the same Delivered/{IN_USE_LABEL}/Potential colour as every other "
           "chart on this page; the arrow is the one relationship this chart exists to show.")
n_evolved = int(reuse["came_from_developments"].map(len).sum())
if not n_evolved:
    st.info("No development has evolved into another yet -- every **Came from** entry on the "
            "Reuse sheet today names a user project, never another development/tool. Add a "
            "development id (e.g. `SP01`) or a tool/Special-Project name under another "
            "development's **Came from** column there to grow this tree.")
else:
    st.plotly_chart(kc.fig_lineage_tree(developments, reuse, STATE_COLORS), width="stretch")

# --- Lineage Part B: one card per development, all 4 relationships as chips -----------------
_CHIP_TEXT_LIMIT = 42  # chars -- past this a chip's own text would stretch the card; show the
# bare id instead and move the full tracker title into the chip's hover (title attribute) and,
# so it's never ONLY a hover-only reader's privilege, into a per-card expander too.


def _chip(text, muted=False, title_attr=None):
    cls = "rel-chip rel-chip-muted" if muted else "rel-chip"
    title = f' title="{_html.escape(title_attr)}"' if title_attr else ""
    return f'<span class="{cls}"{title}>{_html.escape(text)}</span>'


def _name_chip(name):
    """A development/tool name, already resolved to its live display spelling by
    kd.load_expected_gains (NAME_ALIASES applied, see kd._lineage_resolve_parent) -- no further
    lookup needed, unlike a user-project id below."""
    return _chip(name)


def _project_chip(pid, project_lookup, overflow):
    """A user-project id -- its real tracker title inline when it's short enough to fit
    (`kd.project_lookup_label` already degrades to the bare id with no match), otherwise just
    the id, muted-styled when truly unmatched, with the full title available on hover (and
    appended to `overflow` so the card's own expander can show it too, for a reader who can't
    hover)."""
    full_label = kd.project_lookup_label(pid, project_lookup)
    muted = full_label.strip().upper() == pid.strip().upper()  # no tracker match at all
    if len(full_label) <= _CHIP_TEXT_LIMIT:
        return _chip(full_label, muted=muted)
    overflow.append((pid, full_label))
    return _chip(pid, muted=muted, title_attr=full_label)


def _relationship_row(label, chips):
    body = " ".join(chips) if chips else '<span class="rel-none">none yet</span>'
    return f'<div class="rel-row"><span class="rel-label">{label}</span>{body}</div>'


def _lineage_card_rows(developments, reuse):
    """One row per development -- name, state, and the 4 lineage relationship lists, read
    straight from `reuse` (already alias-resolved -- see kd.load_expected_gains) and joined
    onto EVERY development in `developments`, not just the ones reuse happens to have
    populated, so a development with nothing recorded at all still gets a card (4 dashes) --
    that's the whole point of Part B: the gaps are exactly what's meant to be visible.
    `_as_id_list` guards every list the same way kc.fig_lineage_tree does -- kd's loader
    always hands back a real list, so this is unreachable today, but a bare string would
    otherwise iterate character by character into one chip per LETTER."""
    reuse_by_id = {row["ID"]: row for _, row in reuse.iterrows()}
    rows = []
    for _, dev in developments.iterrows():
        r = reuse_by_id.get(dev["ID"])
        evolved_from = kc._as_id_list(r["came_from_developments"]) if r is not None else []
        fed_by = kc._as_id_list(r["came_from_projects"]) if r is not None else []
        benefits = kc._as_id_list(r["serves_project_ids"]) if r is not None else []
        led_to = kc._as_id_list(dev["led_to"])
        rows.append({
            "name": dev["Project"], "state": dev["state"],
            "evolved_from": evolved_from, "fed_by": fed_by, "led_to": led_to, "benefits": benefits,
            "_total": len(evolved_from) + len(fed_by) + len(led_to) + len(benefits),
        })
    return sorted(rows, key=lambda r: (-r["_total"], r["name"]))


def render_lineage_card(row, project_lookup, state_colors):
    color = state_colors.get(row["state"], kd.TL_INK_MUTED)
    state_label = kd.GAIN_STATE_LABELS.get(row["state"], row["state"])
    st.markdown(f"#### {row['name']}")
    st.markdown(
        f'<p style="margin:-0.5rem 0 0.5rem;">'
        f'<span style="color:{color}; font-weight:700;">●</span> '
        f'<span style="color:{color}; font-weight:600;">{state_label}</span></p>',
        unsafe_allow_html=True,
    )
    overflow = []
    rows_html = "".join([
        _relationship_row("Evolved from", [_name_chip(n) for n in row["evolved_from"]]),
        _relationship_row("Fed by", [_project_chip(p, project_lookup, overflow) for p in row["fed_by"]]),
        _relationship_row("Led to", [_name_chip(n) for n in row["led_to"]]),
        _relationship_row("Benefits", [_project_chip(p, project_lookup, overflow) for p in row["benefits"]]),
    ])
    st.markdown(rows_html, unsafe_allow_html=True)
    if overflow:
        with st.expander(f"Full project titles ({len(overflow)})"):
            for pid, full_label in overflow:
                st.caption(f"**{pid}** — " + full_label.split("—", 1)[-1].strip())


st.subheader("Lineage: development cards", anchor="gains-lineage-cards")
st.caption("Every development, most-connected first -- evolved from / fed by / led to / "
           "benefits, each as a chip. A dash means nothing's recorded there yet, which is "
           "exactly what tells you what to fill in next on the Reuse sheet.")
card_rows = _lineage_card_rows(developments, reuse)
card_cols = st.columns(2)
for i, row in enumerate(card_rows):
    with card_cols[i % 2]:
        with st.container(border=True):
            render_lineage_card(row, project_lookup, STATE_COLORS)

# --- Data health: only worth a section if there's actually something to flag ---------------
if unmatched_tools or unmatched_projects or unmatched_reuse_ids or ungrouped_gains or notes:
    st.subheader("Data health", anchor="gains-health")
    if unmatched_tools:
        st.caption("Tools with no row in the gains workbook at all (not counted on this page "
                   "until they get one): " + ", ".join(unmatched_tools))
    if unmatched_projects:
        st.caption("Special Projects with no row in the gains workbook at all (not counted on "
                   "this page until they get one): " + ", ".join(unmatched_projects))
    if unmatched_reuse_ids:
        st.caption("Reuse-sheet user project ids with no match in the project tracker (any "
                   "reporting period) -- likely a typo: " + ", ".join(unmatched_reuse_ids))
    if ungrouped_gains:
        st.caption("Gain column(s) on the Gains sheet not yet assigned to a group (shown under "
                   f"**{kd.GAIN_FALLBACK_GROUP}** for now until the code recognizes the name): "
                   + ", ".join(ungrouped_gains))
    if notes:
        with st.expander("Notes & assumptions"):
            st.markdown("\n".join(f"- {n}" for n in notes))
else:
    anchor("gains-health")
