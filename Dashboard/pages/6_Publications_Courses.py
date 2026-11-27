"""Publications & Courses — the outputs of the service that the project tracker has no
column for: papers and preprints, courses taken and taught, conference contributions, thesis
juries and outreach.

These used to live in the free-form "beyond projects" cards on the Projects Review page,
which could hold the text but not do anything with it. Here each one is a record with a kind
and a date, logged against a reporting period and optionally against the project tags it came
out of -- so one entry counts for the reporting year and is ready to carry into a CV or an
annual report, instead of being written out twice and drifting.

Publications keep their own older store (publications.json); everything else is in
cv_outputs.json. Both mirror to Excel on every save."""

import streamlit as st

import kpi_cache as kcache
import kpi_charts as kc
import kpi_data as kd
import kpi_style as ks
from kpi_style import page_nav

st.set_page_config(page_title="Publications & Courses", page_icon="📚", layout="wide")
kc.set_theme(dark=st.context.theme.type == "dark")
ks.inject(dark=st.context.theme.type == "dark")

if st.query_params.get("readonly") is not None:
    st.session_state["readonly"] = st.query_params.get("readonly") in ("1", "true", "yes", "True")
READONLY = st.session_state.get("readonly", False)
if READONLY:
    st.info("📖 Read-only view — editing controls are hidden.", icon="📖")

ks.header("Publications & Courses",
          "Papers, courses, conferences and juries — logged per reporting period, tagged with "
          "the projects behind them")

periods = kcache.discover_periods()
if not periods:
    st.error("No reporting-period sheets found in any Sara_KPI*.xlsx file in ../Data.")
    st.stop()

period_labels = [p["label"] for p in periods]
default_period_label = st.session_state.get("selected_period", period_labels[0])
if default_period_label not in period_labels:
    default_period_label = period_labels[0]
period_label = st.selectbox(
    "Reporting period", period_labels, index=period_labels.index(default_period_label),
    key="selected_period",
)

st.caption("Each entry carries a kind, which is what groups it here and what decides the CV "
           "section it belongs to — a course under courses, a poster under conference "
           "contributions. Tag an entry with the project(s) it came out of and it links back "
           "to the tracker.")

page_nav([
    ("Publications", "publications"), ("Courses & training", "courses"),
    ("Teaching & juries", "teaching"), ("Conferences", "conferences"),
    ("Outreach & other", "other"),
])

ACCENT = kd.TL_PALETTE_DARK[2] if st.context.theme.type == "dark" else kd.TL_PALETTE[2]

# Both stores, loaded once: the tiles below count them, and each section edits its own slice.
all_pubs = kcache.load_publications()
all_outputs = kcache.load_cv_outputs()
pub_entries = all_pubs.setdefault(period_label, [])
entries = all_outputs.setdefault(period_label, [])


# The tags an entry can be linked to, taken from the tracker itself so the hint can't drift
# from what the project sheets actually hold.
PROJECT_TAGS = sorted(kcache.build_project_lookup())
TAG_HINT = ("Project tags from the tracker: " + ", ".join(PROJECT_TAGS)) if PROJECT_TAGS else ""


def _count(kinds):
    return sum(1 for e in entries if e.get("kind") in kinds)


t1, t2, t3, t4 = st.columns(4)
t1.metric("Publications", len(pub_entries))
t2.metric("Courses & training", _count(["Course attended", "Certification"]))
t3.metric("Teaching & juries", _count(["Course taught", "Thesis jury"]))
t4.metric("Conference contributions", _count(["Conference poster", "Conference talk"]))


def _clean(value):
    v = "" if value is None else str(value).strip()
    return "" if v in ("nan", "None", "NaT") else v


def tag_chips(tags_text):
    """Project tags as pills — the visible link back to the tracker rows an output came from."""
    tags = [t.strip() for t in str(tags_text or "").split(",") if t.strip()]
    return "".join(
        f"<span style='background:{ACCENT}22; color:{ACCENT}; border-radius:10px; "
        f"padding:1px 9px; margin-right:5px; font-size:0.82em; font-weight:600;'>{t}</span>"
        for t in tags
    )


def render_card(title, url, meta_bits, body, tags, badge=None):
    with st.container(border=True):
        title_html = (f"<a href='{url}' target='_blank'>{title or '(untitled)'}</a>"
                      if url else (title or "(untitled)"))
        badge_html = (f"<span style='opacity:0.6; font-size:0.8em; font-weight:600; "
                      f"text-transform:uppercase; letter-spacing:0.05em'>{badge}</span><br>"
                      if badge else "")
        meta = " · ".join(b for b in meta_bits if b)
        st.markdown(
            f"{badge_html}<b>{title_html}</b><br>"
            + (f"<span style='opacity:0.85'>{meta}</span><br>" if meta else "")
            + (f"<span style='opacity:0.75'>{body}</span><br>" if body else "")
            + (f"<div style='margin-top:4px'>{tag_chips(tags)}</div>" if tags else ""),
            unsafe_allow_html=True,
        )


# --- Publications --------------------------------------------------------------------------
st.subheader(f"Publications — {period_label}", anchor="publications")
st.caption("Papers and preprints this period's work fed into, tagged with the project(s) they "
           f"relate to. Saved to publications.json, mirrored to {kd.PUBLICATIONS_XLSX_PATH.name}.")

if st.session_state.pop("pub_save_warning", None):
    st.warning(f"Saved, but couldn't update {kd.PUBLICATIONS_XLSX_PATH.name} — close it in "
               "Excel to refresh the mirror on the next edit.", icon="⚠️")

if not pub_entries:
    st.caption("No publications logged for this period yet.")
for pub in pub_entries:
    render_card(_clean(pub.get("title")), _clean(pub.get("url")),
                [_clean(pub.get("venue")), _clean(pub.get("date"))], "", pub.get("projects"))

PUB_COLUMNS = ["title", "venue", "date", "url", "projects"]
if not READONLY:
    with st.expander("✏️ Add or edit publications"):
        if TAG_HINT:
            st.caption(TAG_HINT)
        edited = st.data_editor(
            kd.table_frame(pub_entries, PUB_COLUMNS), num_rows="dynamic", width="stretch",
            key=f"pub_editor_{period_label}",
            column_config={
                "title": st.column_config.TextColumn("Title", width="large", required=True),
                "venue": st.column_config.TextColumn("Venue", help="Journal, or 'bioRxiv preprint'"),
                "date": st.column_config.TextColumn("Date", help="YYYY-MM-DD or YYYY-MM"),
                "url": st.column_config.LinkColumn("Link (DOI or URL)"),
                "projects": st.column_config.TextColumn(
                    "Related projects", help="Tracker tags, comma-separated, e.g. STAT_036, STAT_057"),
            },
        )
        if st.button("💾 Save publications", key=f"pub_save_{period_label}"):
            all_pubs[period_label] = kd.table_rows(edited, PUB_COLUMNS, required="title")
            warning = kd.save_publications(all_pubs)
            if warning:
                st.session_state["pub_save_warning"] = warning
            st.rerun()


# --- Everything else: one store, grouped by what the kinds are for --------------------------
if st.session_state.pop("outputs_save_warning", None):
    st.warning(f"Saved, but couldn't update {kd.CV_OUTPUTS_XLSX_PATH.name} — close it in Excel "
               "to refresh the mirror on the next edit.", icon="⚠️")


def save_outputs(kinds, rows):
    """Replace just this group's entries for this period, leaving every other kind alone --
    each section edits its own slice of one shared list."""
    others = [e for e in entries if e.get("kind") not in kinds]
    all_outputs[period_label] = others + rows
    warning = kd.save_cv_outputs(all_outputs)
    if warning:
        st.session_state["outputs_save_warning"] = warning
    st.rerun()


def output_section(heading, anchor_id, kinds, caption, title_label, where_label, detail_label,
                   scale_label=None):
    st.divider()
    st.subheader(f"{heading} — {period_label}", anchor=anchor_id)
    st.caption(caption)

    rows = [e for e in entries if e.get("kind") in kinds]
    rows.sort(key=lambda r: str(r.get("date") or ""), reverse=True)
    if not rows:
        st.caption("Nothing logged for this period yet.")
    for row in rows:
        render_card(
            _clean(row.get("title")), _clean(row.get("url")),
            [_clean(row.get("where")), _clean(row.get("date")), _clean(row.get("scale"))],
            _clean(row.get("detail")), row.get("projects"),
            badge=_clean(row.get("kind")) if len(kinds) > 1 else None,
        )

    if READONLY:
        return
    with st.expander(f"✏️ Add or edit {heading.lower()}"):
        if TAG_HINT:
            st.caption(TAG_HINT)
        columns = kd.CV_OUTPUT_FIELDS
        edited = st.data_editor(
            kd.table_frame(rows, columns), num_rows="dynamic", width="stretch",
            key=f"outputs_{anchor_id}_{period_label}",
            column_config={
                "kind": st.column_config.SelectboxColumn("Kind", options=kinds, required=True,
                                                         default=kinds[0]),
                "title": st.column_config.TextColumn(title_label, width="large", required=True),
                "where": st.column_config.TextColumn(where_label),
                "date": st.column_config.TextColumn("Date", help="YYYY-MM, or YYYY"),
                "detail": st.column_config.TextColumn(detail_label, width="large"),
                "scale": st.column_config.TextColumn(scale_label or "Scale",
                                                     help="Students, attendees, hours — whatever "
                                                          "size means for this kind of output"),
                "projects": st.column_config.TextColumn(
                    "Related projects", help="Tracker tags, comma-separated"),
                "url": st.column_config.LinkColumn("Link"),
            },
        )
        if st.button(f"💾 Save {heading.lower()}", key=f"save_{anchor_id}_{period_label}"):
            saved = kd.table_rows(edited, columns, required="title")
            for row in saved:
                if row.get("kind") not in kinds:
                    row["kind"] = kinds[0]
            save_outputs(kinds, saved)


output_section(
    "Courses & training", "courses", ["Course attended", "Certification"],
    "Courses and certifications taken in this period — these are what keeps the service's "
    "methods current, and they appear on the CV under courses and certifications.",
    "Course or certification", "Provider", "Topics covered", "Length / hours",
)

output_section(
    "Teaching & juries", "teaching", ["Course taught", "Thesis jury"],
    "Teaching done and thesis juries sat on. On the CV these land in the teaching section.",
    "What was taught", "Institution", "Detail", "Students",
)

output_section(
    "Conferences", "conferences", ["Conference poster", "Conference talk"],
    "Posters and talks presented. Tag the project or tool behind one and it ties the "
    "contribution back to the work that produced it.",
    "Title", "Event", "Note (e.g. corresponding author)", "Audience",
)

output_section(
    "Outreach & other", "other", ["Outreach", "Other"],
    "Outreach, volunteering and anything else worth recording for the year. "
    "'Other' is deliberately not carried to the CV — it counts for the reporting year only.",
    "What it was", "Where", "Detail", "Scale",
)

st.divider()
st.caption(f"Stored in publications.json and cv_outputs.json, mirrored to "
           f"{kd.PUBLICATIONS_XLSX_PATH.name} and {kd.CV_OUTPUTS_XLSX_PATH.name} on every save.")
