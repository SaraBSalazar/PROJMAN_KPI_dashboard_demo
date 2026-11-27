"""CV — a CV page rebuilt over live data.

Stat cards, a year-by-year table, then collapsible sections. What makes it worth having in a
dashboard is where the content comes from.

  * Everything about the current role -- projects delivered, groups reached, tools built,
    time to deliver, turnaround by size, courses, posters -- is computed on every load
    (kd.cv_role_metrics) from the tracker, time log, tools inventory and output stores.
    None of it is stored in the CV, which is exactly what cv_data.json's own README asks for.
  * Everything only the CV knows -- roles, education, skills, awards, profiles -- lives in
    Data/cv_data.json and is mirrored to cv_data.xlsx on every save.
  * Publications, courses, teaching and conference contributions are the lifetime list with
    the period-tagged ADA entries folded in and marked, matched on title so nothing is
    listed twice.

The page reads as a CV by default. **✏️ Edit mode** (top right) opens an editor under each
section -- the same content, as forms and tables -- and nothing else changes, so you edit
what you were just reading."""

import pandas as pd
import streamlit as st

import kpi_cache as kcache
import kpi_charts as kc
import kpi_cv_view as cvv
import kpi_data as kd
import kpi_style as ks
from kpi_style import page_nav

st.set_page_config(page_title="CV", page_icon="🧬", layout="wide")
DARK = st.context.theme.type == "dark"
kc.set_theme(dark=DARK)
ks.inject(dark=DARK)
MUTED_INK = "#938f87" if DARK else "#898781"

if st.query_params.get("readonly") is not None:
    st.session_state["readonly"] = st.query_params.get("readonly") in ("1", "true", "yes", "True")
READONLY = st.session_state.get("readonly", False)

cv = kcache.load_cv()
all_pubs = kcache.load_publications()
all_outputs = kcache.load_cv_outputs()
metrics = kcache.cv_role_metrics()
totals = metrics["totals"]
profile = kd.cv_profile(cv)

publications = kd.cv_publications(cv, all_pubs)
conferences = kd.cv_section_with_outputs(cv, "conference_contributions", all_outputs)
teaching = kd.cv_section_with_outputs(cv, "teaching", all_outputs)
courses = kd.cv_section_with_outputs(cv, "courses_certifications", all_outputs)
volunteering = kd.cv_section_with_outputs(cv, "volunteering_languages", all_outputs)
counts = kd.cv_output_counts(publications, conferences)
ada_outputs = kd.cv_outputs_flat(all_outputs)

if st.session_state.pop("cv_save_warning", None):
    st.warning(f"Saved, but couldn't update {kd.CV_XLSX_PATH.name} — close it in Excel to "
               "refresh the mirror on the next edit.", icon="⚠️")

top_left, top_right = st.columns([3, 1])
with top_right:
    EDIT = False if READONLY else st.toggle(
        "✏️ Edit mode", value=False, key="cv_edit_mode",
        help="Opens an editor under each section. Off, the page is just the CV.")
if READONLY:
    top_left.info("📖 Read-only view — editing controls are hidden.", icon="📖")

st.markdown(cvv.css(DARK), unsafe_allow_html=True)


def save(message="Saved."):
    warning = kd.save_cv(cv)
    if warning:
        st.session_state["cv_save_warning"] = warning
    st.toast(message)
    st.rerun()


def clean(value):
    v = "" if value is None else str(value).strip()
    return "" if v in ("nan", "None", "NaT") else v


def show(*blocks):
    st.markdown(cvv.wrap(*blocks), unsafe_allow_html=True)


def section_editor(section, label, required=None, caption=None):
    """One CV section as an editable table. Every list section gets the same treatment, so
    there is nothing in cv_data.json that can only be changed by opening the file."""
    if not EDIT:
        return
    rows = cv.get(section, [])
    columns = kd.cv_section_columns(section, rows)
    with st.expander(f"✏️ {label}"):
        if caption:
            st.caption(caption)
        edited = st.data_editor(
            kd.table_frame(rows, columns), num_rows="dynamic", width="stretch",
            key=f"cv_editor_{section}",
        )
        if st.button("💾 Save", key=f"cv_save_{section}"):
            cv[section] = kd.table_rows(edited, columns, required=required or columns[0])
            save(f"{label} saved.")


def date_label(entry):
    """'Oct 2025 – present', or whatever `date_note` says when a role ran in separate stints."""
    note = clean(entry.get("date_note"))
    if note:
        return note

    def fmt(value):
        text = clean(value)
        if not text or text.lower() == "present":
            return "present"
        parsed = pd.to_datetime(text, errors="coerce")
        return parsed.strftime("%b %Y") if not pd.isna(parsed) else text

    return f"{fmt(entry.get('start'))} – {fmt(entry.get('end'))}"


page_nav([
    ("Current role", "current-role"), ("Expertise", "expertise"), ("Details", "details"),
    ("Skills by era", "skills"), ("Profiles & export", "links"),
])

# --- Who ---------------------------------------------------------------------------------
# A mark beside the name if the app has one: put logo.gif (and optionally logo_dark.gif, for
# a flat two-tone image that would read as a solid block in the other theme) in
# Dashboard/static/ and it appears. The demo ships none.
show(cvv.header(profile, ks.static_url("logo_dark.gif" if DARK else "logo.gif")
                or ks.static_url("logo.gif")))
if EDIT:
    with st.expander("✏️ Name, role line, contact and summary"):
        with st.form("cv_profile_form"):
            name = st.text_input("Name", value=profile.get("name", ""))
            role = st.text_input("Role line", value=profile.get("role", ""))
            email = st.text_input("Email", value=profile.get("email", ""))
            about = st.text_area("Summary", value=profile.get("about", ""), height=150)
            if st.form_submit_button("💾 Save"):
                kd.set_cv_profile(cv, {"name": name, "role": role, "email": email, "about": about})
                save("Summary saved.")

show(cvv.written_stats(cv["cv_stats"], "Institutional experience", "Institutional experience"))

# --- The live block ------------------------------------------------------------------------
ks.anchor("current-role")
show(cvv.current_role(metrics, ada_outputs, kd.format_days,
                      heading="Current role: Advanced Data Analysis group"),
     cvv.year_table(metrics, all_outputs, kd.format_days))

if EDIT:
    st.caption("These numbers aren't editable anywhere — they are read from the tracker, the "
               "time log, the tools inventory and the output stores every time the page loads.")
    e1, e2, e3 = st.columns(3)
    e1.page_link("pages/1_Projects_Review.py", label="Projects behind them",
                 icon=":material/folder_open:")
    e2.page_link("pages/3_Tools.py", label="Tools & AI skills", icon=":material/handyman:")
    e3.page_link("pages/6_Publications_Courses.py", label="Log a publication or course",
                 icon=":material/menu_book:")

ks.anchor("expertise")
show(cvv.expertise(cv["cv_stats"], cv["skills"], courses))
if EDIT:
    section_editor("skills", "Skills", required="item",
                   caption="One row per skill: area, status (Current focus / Earlier work) and "
                           "the item itself. Write a proficiency as 'Python (High)' and it "
                           "draws as a meter instead of a chip. The course topics card next to "
                           "them is read from the course list — nothing to edit there.")
    section_editor("cv_stats", "The written-down headline numbers", required="label",
                   caption="The stat cards as written in the CV. Anything about the current role "
                           "is deliberately NOT kept here — those come from the tracker.")

show(cvv.outputs_stats(counts, cv["cv_stats"]))

# --- Details ---------------------------------------------------------------------------------
st.markdown('<div class="cv"><h2 id="details">Details</h2></div>', unsafe_allow_html=True)

show(cvv.experience(cv["experience"], lambda i: kd.cv_bullets_for(cv, i), date_label))
if EDIT:
    st.caption("Each role's summary line and bullets:")
    for i, entry in enumerate(cv["experience"]):
        with st.expander(f"✏️ {clean(entry.get('title'))} — {clean(entry.get('organisation'))}"):
            with st.form(f"cv_exp_{entry.get('id') or i}"):
                title = st.text_input("Title", value=clean(entry.get("title")))
                org = st.text_input("Organisation", value=clean(entry.get("organisation")))
                location = st.text_input("Location / context", value=clean(entry.get("location")))
                d1, d2, d3 = st.columns(3)
                start = d1.text_input("Start (YYYY-MM)", value=clean(entry.get("start")))
                end = d2.text_input("End (YYYY-MM or 'present')", value=clean(entry.get("end")))
                note = d3.text_input("Date note", value=clean(entry.get("date_note")),
                                     help="Shown instead of the start–end range when a role ran "
                                          "in separate stints, e.g. 'Sep – Nov 2023, Sep – Nov 2024'.")
                lead = st.text_area("Summary line", value=clean(entry.get("lead")), height=80)
                bullets = st.text_area("Bullets — one per line",
                                       value="\n".join(kd.cv_bullets_for(cv, entry.get("id"))),
                                       height=200)
                saved = st.form_submit_button("💾 Save role")
            if saved:
                entry.update(title=title, organisation=org, location=location,
                             start=start, end=end, date_note=note, lead=lead)
                kd.set_cv_bullets(cv, entry.get("id"), bullets.split("\n"))
                save("Role saved.")
    section_editor("experience", "Add or remove roles", required="title",
                   caption="The id links a role to its bullets — give a new role a short "
                           "lowercase id. Text for an existing role is easier to edit above.")

show(cvv.publications(publications))
section_editor("publications", "Publications", required="title",
               caption="The lifetime list. Papers logged against a reporting period are edited "
                       "on the Publications & Courses page and shown here with their ADA tag.")

show(cvv.conferences(conferences, kd.rollup_count))
section_editor("conference_contributions", "Conference contributions", required="title")

teaching_rows = [dict(row, students_label=(f"{clean(row.get('students'))} students"
                                           if clean(row.get("students")) else ""))
                 for row in teaching]
show(cvv.simple_section("Teaching and mentoring", teaching_rows, "item",
                        ["institution", "date", "students_label", "detail"]))
section_editor("teaching", "Teaching and mentoring", required="item")

show(cvv.simple_section("Education", cv["education"], "degree",
                        ["institution", "years", "grade", "thesis"]))
section_editor("education", "Education", required="degree")

show(cvv.simple_section("Courses and certifications", courses, "title",
                        ["provider", "date", "topics"]))
section_editor("courses_certifications", "Courses and certifications", required="title",
               caption="Courses taken in the ADA role are logged on the Publications & Courses "
                       "page; the rest live here.")

show(cvv.simple_section("Awards", cv["awards"], "award", ["event", "year"]))
section_editor("awards", "Awards", required="award")

show(cvv.simple_section("Volunteering and languages", volunteering, "item", ["date"]))
section_editor("volunteering_languages", "Volunteering and languages", required="item")

# --- Where each skill was used ---------------------------------------------------------------
st.markdown('<div class="cv"><h2 id="skills">Where each skill was used</h2></div>',
            unsafe_allow_html=True)
st.plotly_chart(kc.fig_cv_skill_matrix(cv["skill_matrix"]), width="content")
section_editor("skill_matrix", "Where each skill was used", required="skill",
               caption="One row per skill, one column per era. Values: used, basic, not used. "
                       "Add a column to add an era.")

# --- Profiles & export ------------------------------------------------------------------------
st.divider()
st.subheader("Profiles & export", anchor="links")
link_cols = st.columns(len(cv["profiles_ids"]) or 1)
for col, pid in zip(link_cols, cv["profiles_ids"]):
    col.markdown(f"[{clean(pid.get('name'))}]({clean(pid.get('url'))})  \n"
                 f"<span style='color:{MUTED_INK}; font-size:0.8em'>{clean(pid.get('id'))}</span>",
                 unsafe_allow_html=True)
section_editor("profiles_ids", "Profiles and IDs", required="name")

# The export only exists when there's a standalone CV page to refresh. That file is a
# hand-built artefact, not something the dashboard creates, so its absence is a normal state
# (a fresh copy of this app has none) rather than an error worth a warning.
if kd.CV_HTML_PATH.exists():
    st.markdown("##### Export")
    st.caption(f"The standalone CV page in Data/{kd.CV_HTML_PATH.name} carries the dashboard's "
               "numbers as placeholders. This fills them in with what the tracker says right "
               "now and hands you a copy to send or print — the file in Data/ is left untouched.")
    try:
        html = kd.cv_html_with_live_metrics(metrics)
    except OSError:
        st.warning(f"Couldn't read Data/{kd.CV_HTML_PATH.name} — close it and reload.")
    else:
        st.download_button(
            "⬇️ CV page with today's numbers", data=html,
            file_name=f"{kd.CV_HTML_PATH.stem}_{pd.Timestamp.now():%Y%m%d}.html",
            mime="text/html",
        )

st.divider()
st.caption(f"CV content: Data/{kd.CV_PATH.name} (source of truth), mirrored to "
           f"{kd.CV_XLSX_PATH.name} on every save — edit it here, not in Excel, since the "
           "workbook is never read back. Service numbers: the live tracker, time log, tools "
           "inventory and output stores.")
