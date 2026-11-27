"""Gains & Outputs — what the Special Projects and Tools built along the way are expected to
deliver, and how much of that is Delivered / In use / still Potential, read live from
SpecialProjects_Tools_expected_gains_v5.xlsx (kd.load_expected_gains, folded together with the
live Special Projects and Tools status). The charts are read-only; the gain toggles, the
value table and the per-development Reuse/lineage control (that last one lives on the Special
Projects and Tools cards, not here) all write back to gains.xlsx through kpi_gains_editor.
The 3-state rule is never editable anywhere -- it is derived, in kpi_data.py (kd._decide_state).
"""

import streamlit as st

import kpi_cache as kcache
import kpi_charts as kc
import kpi_data as kd
import kpi_gains_editor as kge
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
# drawn in fig_gains_matrix, since fig_gains_active_potential was folded into it) -- re-picked
# per-theme now that the state palette above needed its own dark variant (see
# kd.GAIN_GROUP_COLORS' docstring for the full story, including why ADA's orange is
# deliberately NOT part of this constraint set).
GROUP_COLORS = kd.GAIN_GROUP_COLORS_DARK if st.context.theme.type == "dark" else kd.GAIN_GROUP_COLORS
# The ADA/Personal audience row's own identity colour -- orange, used ONLY in
# fig_audience_outputs (never alongside the group colours above, which live in two different
# charts), kept theme-matched the same way STATE_COLORS is.
ADA_COLOR = kd.ADA_PERSONAL_COLOR_DARK if st.context.theme.type == "dark" else kd.ADA_PERSONAL_COLOR

if st.query_params.get("readonly") is not None:
    st.session_state["readonly"] = st.query_params.get("readonly") in ("1", "true", "yes", "True")
READONLY = st.session_state.get("readonly", False)


ks.header(
    "Gains & Outputs",
    "What the Special Projects and tools built along the way are expected to deliver -- "
    "and how much of that is already being delivered, vs. still ahead.",
)
page_nav([
    ("Overview", "gains-overview"),
    ("What delivers what", "gains-matrix"),
    ("Audience & outputs", "gains-audience"),
    ("Value potential", "gains-value"),
    ("Reuse", "gains-reuse"),
    ("Lineage", "gains-lineage-tree"),
    ("Data health", "gains-health"),
])
st.caption("Read live from Data/gains.xlsx -- editable right here on this page and on the "
           "Special Projects / Tools cards -- cross-checked against live Special Projects "
           "and Tools status.")

try:
    data = kcache.load_expected_gains()
except FileNotFoundError:
    st.error(f"Neither gains.xlsx nor the workbook it is first built from "
             f"(SpecialProjects_Tools_expected_gains_v5.xlsx) is in {kd.DATA_DIR} -- this page "
             "has nothing to read from until one of them exists.")
    st.stop()
except PermissionError:
    st.error("Couldn't read gains.xlsx (or one of the files it cross-checks against -- "
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
# Not "with external users" -- the workbook's x marks a development that COULD reach past the
# institution, which is a potential, not a count of users who already exist out there (same
# rename as kc._AUDIENCE_FLAG_LABELS applies to the audience chart's own row, so they agree).
r2[2].metric("With potential external reach", n_external)
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
        "too, e.g. OMICs Pipelines). Any ONE of these moves it here: it serves a "
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

# The "Delivered, in use & potential gains" stacked bar chart used to sit here. It was
# fig_gains_matrix's COLUMN MARGIN drawn as a second picture -- a bar's length was the number
# of dots in that gain's column and its segments were those dots' own state colours -- so the
# page carried two renderings of one table that had to be kept in agreement. The matrix now
# carries the margins itself (row totals right, column totals below), which is the whole of
# what the bar chart said. Its one piece of genuinely derived commentary survives below.


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


def _vb(n, singular, plural):
    """Number agreement for the derived captions below -- they are assembled from live counts,
    so a count that happens to be 1 ("1 of the 16 developments are drawn") would otherwise read
    as a typo in exactly the situation a reader is most likely to notice it."""
    return singular if n == 1 else plural


def _names(rows, limit=4):
    """A readable inline list of development names, capped -- a coverage caption naming 3
    developments is useful, one naming 14 is a wall of text where the NUMBER was the point."""
    names = list(rows["Project"])
    if len(names) > limit:
        return ", ".join(names[:limit]) + f", +{len(names) - limit} more"
    return ", ".join(names)


def _audience_coverage_caption(developments):
    """How much of the "What delivers what" set the audience chart actually speaks for.
    Derived every load like _insight_caption, never hardcoded. The counts a reader would
    otherwise have to get by counting bars -- and, for the developments that land in NO row
    at all, couldn't get from the chart however long they looked at it, since a development
    with no audience is drawn as nothing rather than as an empty row."""
    n_total = len(developments)
    has_flag = developments[kd.GAIN_AUDIENCE_FLAGS].any(axis=1)
    is_ada = developments["Output level"].isin(kd.GAIN_ADA_OUTPUT_LEVELS)
    ada_only = developments[~has_flag & is_ada]
    nowhere = developments[~has_flag & ~is_ada]

    n_flagged = int(has_flag.sum())
    parts = [f"**{n_flagged} of the {n_total} "
             f"{_vb(n_total, 'development', 'developments')}** in *What delivers what* "
             f"{_vb(n_flagged, 'claims', 'claim')} at least one of the 5 audience/output "
             f"flags above."]
    if len(ada_only):
        parts.append(f"**{len(ada_only)}** {_vb(len(ada_only), 'claims', 'claim')} none of "
                     f"them and {_vb(len(ada_only), 'appears', 'appear')} only in the **ADA / "
                     f"Personal** row -- built for ADA or personal/internal use, no outside "
                     f"audience claimed yet ({_names(ada_only)}).")
    if len(nowhere):
        # Not a styling choice: this is the one case the chart genuinely cannot show, so the
        # caption is the only place it can be said. Reads as a data-health nudge on purpose.
        parts.append(f"**{len(nowhere)}** {_vb(len(nowhere), 'appears', 'appear')} in **no "
                     f"row of this chart at all** -- neither "
                     f"a flag nor an ADA/Personal output level, so nothing on record says who "
                     f"they are for ({_names(nowhere)}).")
    return " ".join(parts)


def _reuse_coverage_caption(reuse, developments):
    """Same idea for the reuse butterfly: how many of the developments in "What delivers what"
    the chart draws at all, split by which side they land on. Rows with nothing on either side
    are dropped by fig_reuse_both_directions (by design -- an all-zero row is noise), so
    without this the chart silently speaks for a subset and looks like it speaks for all."""
    n_developments = len(developments)
    left_n = reuse["came_from_projects"].map(len)
    right_n = reuse["serves_project_ids"].map(len)
    n_built = int((left_n > 0).sum())
    n_benefits = int((right_n > 0).sum())
    n_both = int(((left_n > 0) & (right_n > 0)).sum())
    drawn_ids = set(reuse.loc[(left_n + right_n) > 0, "ID"])
    n_drawn = len(drawn_ids)
    # Counted off the DEVELOPMENTS, not off the Reuse sheet: a development with no Reuse row
    # at all (hand-deleted in Excel -- the editors always write the three sheets together)
    # has nothing recorded just as much as one with a row of two empty cells, and only
    # Overview's own "Use pattern" column can still say whether it is constant-use.
    absent = developments[~developments["ID"].isin(drawn_ids)]
    n_absent = len(absent)
    absent_constant = int(absent["constant_use"].sum())

    benefits_txt = (f"**{n_benefits}** with at least one project benefiting from them"
                    if n_benefits else "**none** yet with a project recorded as benefiting from it")
    parts = [f"**{n_drawn} of the {n_developments} "
             f"{_vb(n_developments, 'development', 'developments')}** in *What delivers what* "
             f"{_vb(n_drawn, 'appears', 'appear')} above -- **{n_built}** built out of real "
             f"user projects, {benefits_txt}" + (f", **{n_both}** both" if n_both else "") + "."]
    if n_absent > 0:
        tail = (f" -- {absent_constant} of those {_vb(absent_constant, 'is', 'are')} "
                f"constant-use, which the workbook's own convention leaves uncounted on "
                f"purpose, leaving "
                f"**{n_absent - absent_constant}** with reuse genuinely unrecorded so far"
                if absent_constant else "")
        parts.append(f"Nothing is recorded in either direction for the other "
                     f"**{n_absent}**{tail}.")
    return " ".join(parts)


# --- What delivers what ------------------------------------------------------------------
st.subheader("What delivers what", anchor="gains-matrix")
st.caption(f"Every dot in a row shares that development's state -- Delivered developments read "
           f"green, {IN_USE_LABEL} blue, Potential grey, top to bottom. Every dot is filled: a "
           "gap here means that development doesn't deliver that gain, never that it's only "
           f"potential. The coloured header strip groups the {len(gain_columns)} gains into "
           "their 4 themes. **Totals** sit on both margins -- gain types per development down "
           "the right, developments per gain along the bottom; hover a column total for its "
           f"Delivered/{IN_USE_LABEL}/Potential split.")
st.plotly_chart(
    kc.fig_gains_matrix(gains_long, developments, STATE_COLORS, gain_columns, gain_groups, GROUP_COLORS),
    width="stretch",
)
st.caption(_insight_caption(gain_summary))

if not READONLY:
    # Directly under the chart it feeds, not in a settings corner: ticking a box here is the
    # same action as adding a dot up there, and the two being adjacent is what makes that
    # obvious without explaining it.
    with st.expander("✏️ Edit what delivers what"):
        st.caption("Tick a box and that development claims that gain. **State** is derived "
                   "from live Special Projects / Tools status and can't be set here -- mark a "
                   "project finished on its own page, or record reuse on its card, to move it.")
        try:
            gains_sheets = kcache.load_gains_sheets()
        except (FileNotFoundError, PermissionError):
            st.error("Couldn't open gains.xlsx to edit — it's open in Excel (or locked by "
                     "OneDrive). Close it and refresh.")
        else:
            state_by_id = dict(zip(developments["ID"], developments["state"]))
            kge.render_gain_toggles(gains_sheets, gain_columns, state_by_id)
            st.divider()
            st.markdown("**Add a development**")
            st.caption("Anything on the Tools or Special Projects pages with no row here "
                       "doesn't appear on this page at all. These are the ones missing:")
            kge.render_add_development(
                kcache.load_gains_sheets(), sorted(unmatched_tools + unmatched_projects))

# --- Audience & outputs -------------------------------------------------------------------
st.subheader("Audience & outputs", anchor="gains-audience")
st.plotly_chart(kc.fig_audience_outputs(developments, STATE_COLORS, ADA_COLOR), width="stretch")
st.caption("**ADA / Personal** (orange marker) is the innermost tier -- built for ADA or "
           "personal/internal use (`Output level` = Internal ADA or Internal Worker), "
           "inward-facing in a way even the **Internal users** row below it isn't: that row "
           "and **Potential external reach** are both about people outside ADA, just at "
           "different distances, while ADA/Personal is about work that never left the "
           "building at all. That last row is a *potential* -- the development could reach "
           "past the institution -- not a count of external users it already has.")
st.caption(_audience_coverage_caption(developments))

# --- Value potential: its own full-width section ------------------------------------------
# Used to sit squeezed into the narrow right column beside the audience chart, under a bare
# bold line rather than a real heading -- which buried the one place on this page that puts a
# number on what these developments would cost to buy. It's a section in its own right now:
# own subheader, own page-nav entry, full page width, and every row visible without scrolling.
st.subheader("Value potential", anchor="gains-value")
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
    # The live Delivered/In use/Potential wording, not the raw internal state string -- "In
    # use" alone is the one state whose label spells out more than its key does (see
    # kd.GAIN_STATE_LABELS), and this table should read the same as every chart above it.
    display["Status"] = [kd.GAIN_STATE_LABELS.get(st_, st_) for st_ in display["state"]]
    st.dataframe(
        display[["Project", "Audience", "Value basis", "Price", "Status"]],
        hide_index=True, width="stretch",
        # Explicit height = header + every row, so a 4-row table never renders inside its own
        # scrollbox (Streamlit's default caps the body at ~10 rows and scrolls past that --
        # fine for a long table, needless chrome for this one).
        height=38 * (len(display) + 1) + 3,
        column_config={
            "Project": st.column_config.TextColumn("Development / tool", width="medium"),
            "Audience": st.column_config.TextColumn("Audience", width="small"),
            "Value basis": st.column_config.TextColumn("What the price is based on", width="large"),
            "Price": st.column_config.TextColumn("Market equivalent", width="small"),
            "Status": st.column_config.TextColumn("Status", width="small"),
        },
    )
else:
    st.caption("No value rows recorded yet.")

if not READONLY:
    with st.expander("✏️ Edit value potential"):
        st.caption("A development can only be picked from the list -- the row is stored "
                   "against its id, so a free-typed name would have nothing to attach to. "
                   "Leave the price blank when none was researched; the basis text still shows.")
        try:
            value_sheets = kcache.load_gains_sheets()
        except (FileNotFoundError, PermissionError):
            st.error("Couldn't open gains.xlsx to edit — it's open in Excel (or locked by "
                     "OneDrive). Close it and refresh.")
        else:
            kge.render_value_editor(value_sheets)

# --- Reuse: built out of real user work, and who benefits from it --------------------------
st.subheader("Reuse: built out of real user work, and who benefits", anchor="gains-reuse")
st.plotly_chart(kc.fig_reuse_both_directions(reuse, STATE_COLORS, project_lookup), width="stretch")
st.caption(_reuse_coverage_caption(reuse, developments))
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

# --- Lineage: a TREE of development -> development lineage, and nothing else ---------------
# Deliberately split out of the reuse picture above: "built from user work" (14 edges) and
# "benefits" (0) used to share a chart with "evolved into" (3), and the handful of "evolved
# into" edges this chart exists to surface were the least visible thing in it. User-project
# ids never appear here at all -- that's the whole point of the split; they live in the Reuse
# chart above, which already says in full which user work fed each development and who
# benefits from it. (An earlier "development cards" section repeated those same two lists as
# chips below this chart; it was dropped for exactly that reason -- it added no information
# the Reuse chart didn't already carry, it just made the page longer.)
st.subheader("Lineage: development evolution", anchor="gains-lineage-tree")
st.caption("ONLY development/tool -> development/tool edges -- a Special Project or tool "
           "literally spawning another, e.g. an AI skill later rebuilt as a full Special "
           "Project. No user-project id is ever drawn on this chart (that's the Reuse chart "
           "above). Shape is Special Project / Tool / AI Skill; fill is the same "
           f"Delivered/{IN_USE_LABEL}/Potential colour as every other chart on this page; a "
           "hollow node has no state to show -- it's either deprecated (the usual, healthy "
           "end for a parent its child took over -- the Tools page holds the reason) or just "
           "not tracked in the gains workbook. Hover any node to see which.")
st.caption("The **arrow** says how the child came about. A violet solid arrow is an "
           "**evolution** -- the parent became the child and is usually retired afterwards "
           "(notion-to-elab → Project Closer). A sienna open arrow is an **output** -- the "
           "parent produced it and carries on itself (OMICs Pipelines → Metabolomics "
           "Facility Dashboard). Set it on the development's own card, under "
           "**🔗 Reuse & lineage**.")
n_evolved = int(reuse["came_from_developments"].map(len).sum())
if not n_evolved:
    st.info("No development has evolved into another yet -- every **Came from** entry on the "
            "Reuse sheet today names a user project, never another development/tool. Add a "
            "development id (e.g. `SP01`) or a tool/Special-Project name under another "
            "development's **Came from** column there to grow this tree.")
else:
    st.plotly_chart(
        kc.fig_lineage_tree(developments, reuse, STATE_COLORS,
                            parent_status=data["lineage_parent_status"]),
        width="stretch",
    )
    st.caption("A development can be expected to spawn more than one tool -- each new one "
               "joins this chart on its own the moment its card names that parent under "
               "**Grew out of**.")

# --- Data health: only worth a section if there's actually something to flag ---------------
# Shrinking by design. Three of its checks existed because this data was typed into Excel by
# hand, where a mistyped "GEN_O31" silently vanished from a chart with no error anywhere; now
# that projects are picked from a dropdown and developments from the live list, those three
# can only fire on rows that predate the editors (or a hand edit made in Excel afterwards).
# What it still earns its place for is the last check -- a gain column the code has never been
# told about, which no editor can catch because the column set is deliberately open-ended.
if unmatched_tools or unmatched_projects or unmatched_reuse_ids or ungrouped_gains or notes:
    st.subheader("Data health", anchor="gains-health")
    if unmatched_tools:
        st.caption("Tools with no row in the gains store at all (not counted on this page "
                   "until they get one -- add them under **✏️ Edit what delivers what** above): "
                   + ", ".join(unmatched_tools))
    if unmatched_projects:
        st.caption("Special Projects with no row in the gains store at all (not counted on "
                   "this page until they get one -- add them under **✏️ Edit what delivers "
                   "what** above): " + ", ".join(unmatched_projects))
    if unmatched_reuse_ids:
        st.caption("Reuse user project ids with no match in the project tracker (any "
                   "reporting period) -- a leftover typo from before these were picked from a "
                   "list; fix it on that development's card: " + ", ".join(unmatched_reuse_ids))
    if ungrouped_gains:
        st.caption("Gain column(s) in the gains store not yet assigned to a group (shown under "
                   f"**{kd.GAIN_FALLBACK_GROUP}** for now until the code recognizes the name): "
                   + ", ".join(ungrouped_gains))
    if notes:
        with st.expander("Notes & assumptions"):
            st.markdown("\n".join(f"- {n}" for n in notes))
else:
    anchor("gains-health")
