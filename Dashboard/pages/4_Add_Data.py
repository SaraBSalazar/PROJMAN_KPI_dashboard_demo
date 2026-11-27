"""Add Data — quick-add and light-edit forms for the project tracker and the
consultation-meetings log.

Deliberately NOT a full spreadsheet editor: "Hours in Timesheet" in the project sheet holds
live Excel formulas (confirmed with openpyxl), so a pandas-based rewrite of the whole sheet
would flatten every row's formula to a frozen static number. Every write here goes through
openpyxl and only ever touches the one row being added or edited -- and the edit form
explicitly refuses to touch that formula column.
track_time.csv already has its own editor on the main page's Week tab, and
Special_Projects_Ratings.xlsx on the Special Projects page -- both are plain flat tables
with no formulas, so those stayed full editors.
"""

import datetime

import pandas as pd
import streamlit as st

import kpi_cache as kcache
import kpi_data as kd
import kpi_style as ks
from kpi_style import anchor, page_nav

st.set_page_config(page_title="Add Data", page_icon="➕", layout="wide")
ks.inject(dark=st.context.theme.type == "dark")


def _clean_cell(value):
    """A tracker cell as display text. Blank for a real blank -- which reaches us either as
    NaN/None or as the literal "nan"/"None" strings a blank picks up on its way through
    pandas (the Notas column already holds a few). Without this, editing such a project
    would show "nan" in the field and then write that string back to the sheet."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).strip()
    return "" if text in ("nan", "None") else text


def field_with_options(container, label, options, key, current=""):
    """One dropdown that also accepts a brand-new value typed straight into it.

    This deliberately does NOT use a separate "…or a new value" text box: inside an
    st.form, pressing Enter in any text box submits the whole form, so a half-filled
    entry would be saved as its own row and clear_on_submit would wipe the rest."""
    choices = [o for o in options if o]
    if current and current not in choices:
        choices = [current] + choices
    value = container.selectbox(
        label, choices,
        index=choices.index(current) if current in choices else None,
        key=f"{key}_sel", accept_new_options=True,
        placeholder="pick one, or type a new value",
    )
    return (value or "").strip()


def date_or_none(container, label, current, key):
    """An optional date: an empty, clearable date field (st.date_input(value=None)) that
    returns None when left blank -- works inside st.form, unlike the old checkbox+disabled
    pattern, which couldn't enable the field until the form was submitted."""
    return container.date_input(
        f"{label} (leave empty if none)",
        value=(current.date() if pd.notna(current) else None),
        key=f"{key}_date",
    )


def clear_fields(keys):
    """Empty a finished form by dropping its widget state, so the widgets fall back to
    their defaults on the next run. Used instead of st.form(clear_on_submit=True), which
    would also wipe everything when a submission is REJECTED -- losing what was typed."""
    for k in keys:
        st.session_state.pop(k, None)


ks.header("Add Data",
          "Quick-add and light-edit forms for the project tracker and meetings log")

if st.query_params.get("readonly") is not None:
    st.session_state["readonly"] = st.query_params.get("readonly") in ("1", "true", "yes", "True")
if st.session_state.get("readonly", False):
    st.info("📖 This page is unavailable in the read-only shared view.", icon="📖")
    st.stop()

page_nav([("New project", "new-project"), ("Edit a project", "edit-project"), ("Consultation meeting", "new-meeting")])
st.caption(
    "Every save here touches only the one row being added or edited, via openpyxl -- nothing "
    "else on the sheet (including formulas) is rewritten. For anything beyond that, use Excel directly."
)
with st.expander("📖 Category & task glossary"):
    st.markdown(kd.GLOSSARY_MD)
with st.expander("📖 Projects received vs finished — chart legend"):
    st.markdown(kd.RECEIVED_FINISHED_GLOSSARY_MD)

periods = kcache.discover_periods()
if not periods:
    st.error("No reporting-period sheets found in any KPI*.xlsx file in ../Data.")
    st.stop()

period_labels = [p["label"] for p in periods]
default_period_label = st.session_state.get("selected_period", period_labels[0])
if default_period_label not in period_labels:
    default_period_label = period_labels[0]
period_label = st.selectbox(
    "Reporting period", period_labels, index=period_labels.index(default_period_label), key="selected_period",
)
period = next(p for p in periods if p["label"] == period_label)

TRIGGER_OPTIONS = kcache.project_field_options(periods, "Project Trigger")
TYPE_OPTIONS = kcache.project_field_options(periods, "Type of Data")
OUTPUT_OPTIONS = kcache.project_field_options(periods, "Project Outputs")
USER_TYPE_OPTIONS = kcache.project_field_options(periods, "User Type")
LOCATION_OPTIONS = kcache.project_field_options(periods, "User Location")
GRUPO_OPTIONS = kcache.project_field_options(periods, "Grupo")
USER_OPTIONS = kcache.project_field_options(periods, "User")
# Meeting Outputs comes from the meetings sheets (every period, so older ones like 2025-2026
# keep their vocabulary available), not the project sheets.
MEETING_OUTPUT_OPTIONS = kcache.meeting_field_options(periods, "Meeting Outputs")

# --- New project -----------------------------------------------------------------------
anchor("new-project")
st.subheader(f"New project — {period_label}")

projects_now = kcache.load_projects(period["file"], period["sheet"])
st.caption(f"{len(projects_now)} of {kd.PROJECT_SHEET_ROW_CAP} project rows used in this sheet.")

NEW_PROJECT_KEYS = [
    "new_project_tag", "new_project_desc", "new_first", "new_register", "new_begin",
    "new_trigger_sel", "new_type_sel", "new_output_sel", "new_usertype_sel",
    "new_location_sel", "new_grupo_sel", "new_user_sel",
]

with st.form("new_project_form"):
    c1, c2 = st.columns(2)
    project_tag = c1.text_input("Project tag *", help="e.g. GEN_014", key="new_project_tag")
    short_description = c2.text_input("Short description", key="new_project_desc")

    c3, c4, c4b = st.columns(3)
    project_trigger = field_with_options(c3, "Project Trigger", TRIGGER_OPTIONS, "new_trigger")
    type_of_data = field_with_options(c4, "Type of Data", TYPE_OPTIONS, "new_type")
    project_outputs = field_with_options(
        c4b, "Project Outputs", OUTPUT_OPTIONS, "new_output",
    )

    c5, c6, c7, c8 = st.columns(4)
    user_type = field_with_options(c5, "User Type", USER_TYPE_OPTIONS, "new_usertype")
    user_location = field_with_options(c6, "User Location", LOCATION_OPTIONS, "new_location")
    grupo = field_with_options(c7, "Grupo", GRUPO_OPTIONS, "new_grupo")
    user = field_with_options(c8, "User", USER_OPTIONS, "new_user")

    c9, c10, c11 = st.columns(3)
    first_meeting = c9.date_input("First User Meeting/Shared Data", value=datetime.date.today(), key="new_first")
    register_date = c10.date_input("Register Project", value=datetime.date.today(), key="new_register")
    begin_date = c11.date_input("Begining", value=datetime.date.today(), key="new_begin")

    st.caption(
        "Project Outputs is here because the expected output is usually known upfront -- "
        "leave it empty if it isn't yet. Hours in Timesheet, Number of Reports/Meetings, Final "
        "Report Sent, Closing Day, and the rest are left blank -- fill those in as the "
        "project actually progresses (via **Edit a project** below; the hours column is a "
        "live formula and populates on its own)."
    )

    submitted = st.form_submit_button("➕ Add project")
    if submitted:
        if not project_tag.strip():
            st.error("Project tag is required.")
        else:
            try:
                kd.append_project_row(period["file"], period["sheet"], {
                    "Project tag": project_tag.strip(),
                    "Short Description": short_description.strip(),
                    "Project Trigger": project_trigger,
                    "Type of Data": type_of_data,
                    "Project Outputs": project_outputs,
                    "User Type": user_type,
                    "User Location": user_location,
                    "Grupo": grupo,
                    "User": user,
                    "First User Meeting/Shared Data": first_meeting,
                    "Register Project": register_date,
                    "Begining": begin_date,
                })
                st.success(f"Added \"{project_tag}\" to {period['sheet']}.")
                clear_fields(NEW_PROJECT_KEYS)
                st.rerun()
            except ValueError as e:
                st.error(str(e))
            except PermissionError:
                st.error(f"Couldn't save — {period['file'].name} is open in Excel (or locked "
                         "by OneDrive). Close it and submit again.")

st.divider()

# --- Edit an existing project ------------------------------------------------------------
anchor("edit-project")
st.subheader(f"Edit a project — {period_label}")
st.caption(
    "Hours in Timesheet isn't editable here -- it's a live Timesheet formula; edit it in Excel "
    "only. Number of Reports and Number of Meetings are the two axes of the complexity "
    "bubble chart on **Projects Review**, so keeping them current is what puts a project "
    "on that chart."
)

project_tags = projects_now["Project tag"].dropna().astype(str).tolist()
if not project_tags:
    st.caption("No projects in this sheet yet.")
else:
    edit_tag = st.selectbox("Project to edit", project_tags, key="edit_project_select")
    row = projects_now.loc[projects_now["Project tag"] == edit_tag].iloc[0]

    with st.form(f"edit_project_form_{period_label}_{edit_tag}"):
        c1, c2, c2b = st.columns([2, 1, 1])
        e_desc = c1.text_input(
            "Short description", value=_clean_cell(row.get("Short Description")), key=f"edit_desc_{edit_tag}",
        )
        reports_now = pd.to_numeric(row.get("Number of Reports"), errors="coerce")
        e_reports = c2.number_input(
            "Number of Reports", min_value=0, step=1,
            value=int(reports_now) if pd.notna(reports_now) else 0,
            key=f"edit_reports_{edit_tag}",
        )
        meetings_now = pd.to_numeric(row.get("Number of Meetings"), errors="coerce")
        e_meetings = c2b.number_input(
            "Number of Meetings", min_value=0, step=1,
            value=int(meetings_now) if pd.notna(meetings_now) else 0,
            key=f"edit_meetings_{edit_tag}",
            help="Project meetings held so far — the y-axis of the complexity bubble chart.",
        )

        c3, c4, c4b = st.columns(3)
        e_trigger = field_with_options(
            c3, "Project Trigger", TRIGGER_OPTIONS, f"edit_trigger_{edit_tag}", current=_clean_cell(row.get("Project Trigger")),
        )
        e_type = field_with_options(
            c4, "Type of Data", TYPE_OPTIONS, f"edit_type_{edit_tag}", current=_clean_cell(row.get("Type of Data")),
        )
        e_outputs = field_with_options(
            c4b, "Project Outputs", OUTPUT_OPTIONS, f"edit_output_{edit_tag}",
            current=_clean_cell(row.get("Project Outputs")),
        )

        c5, c6, c7, c8 = st.columns(4)
        e_user_type = field_with_options(c5, "User Type", USER_TYPE_OPTIONS, f"edit_usertype_{edit_tag}", current=_clean_cell(row.get("User Type")))
        e_location = field_with_options(c6, "User Location", LOCATION_OPTIONS, f"edit_location_{edit_tag}", current=_clean_cell(row.get("User Location")))
        e_grupo = field_with_options(c7, "Grupo", GRUPO_OPTIONS, f"edit_grupo_{edit_tag}", current=_clean_cell(row.get("Grupo")))
        e_user = field_with_options(c8, "User", USER_OPTIONS, f"edit_user_{edit_tag}", current=_clean_cell(row.get("User")))

        c9, c10, c11 = st.columns(3)
        e_first = c9.date_input(
            "First User Meeting/Shared Data",
            value=row["First User Meeting/Shared Data"].date() if pd.notna(row.get("First User Meeting/Shared Data")) else datetime.date.today(),
            key=f"edit_first_{edit_tag}",
        )
        e_register = c10.date_input(
            "Register Project",
            value=row["Register Project"].date() if pd.notna(row.get("Register Project")) else datetime.date.today(),
            key=f"edit_register_{edit_tag}",
        )
        e_begin = c11.date_input(
            "Begining",
            value=row["Begining"].date() if pd.notna(row.get("Begining")) else datetime.date.today(),
            key=f"edit_begin_{edit_tag}",
        )

        c12, c13 = st.columns(2)
        e_final = date_or_none(c12, "Final Report Sent", row.get("Final Report Sent"), f"edit_finalreport_{edit_tag}")
        e_closing = date_or_none(c13, "Closing Day", row.get("Closing Day"), f"edit_closing_{edit_tag}")

        price_now = pd.to_numeric(row.get("Price Charged"), errors="coerce")
        e_price = st.number_input(
            "Price Charged", min_value=0.0, step=1.0,
            value=float(price_now) if pd.notna(price_now) else 0.0,
            key=f"edit_price_{edit_tag}",
        )
        e_notes = st.text_area("Notas", value=_clean_cell(row.get("Notas")), key=f"edit_notes_{edit_tag}")

        if st.form_submit_button("💾 Save changes"):
            try:
                # Number of Meetings is hand-typed, but a cell can hold a typed sum like
                # "=2+1" -- writing the plain total back would quietly flatten that, so it
                # only goes in the payload when the number actually changed.
                meetings_edit = ({} if pd.notna(meetings_now) and int(meetings_now) == e_meetings
                                 else {"Number of Meetings": e_meetings})
                kd.update_project_row(period["file"], period["sheet"], edit_tag, {
                    "Short Description": e_desc.strip(),
                    "Number of Reports": e_reports,
                    **meetings_edit,
                    "Project Trigger": e_trigger,
                    "Type of Data": e_type,
                    "Project Outputs": e_outputs,
                    "User Type": e_user_type,
                    "User Location": e_location,
                    "Grupo": e_grupo,
                    "User": e_user,
                    "First User Meeting/Shared Data": e_first,
                    "Register Project": e_register,
                    "Begining": e_begin,
                    "Final Report Sent": e_final,
                    "Closing Day": e_closing,
                    "Price Charged": e_price,
                    "Notas": e_notes.strip(),
                })
                st.success(f"Updated \"{edit_tag}\".")
                st.rerun()
            except ValueError as e:
                st.error(str(e))
            except PermissionError:
                st.error(f"Couldn't save — {period['file'].name} is open in Excel (or locked "
                         "by OneDrive). Close it and submit again; your entries are still in "
                         "the form above.")

st.divider()

# --- New consultation meeting ------------------------------------------------------------
anchor("new-meeting")
st.subheader(f"New consultation meeting — {period_label}")

meetings_now = kcache.load_meetings(period["file"], period["meetings_sheet"])
st.caption(f"{len(meetings_now)} meetings logged in this sheet.")

NEW_MEETING_KEYS = [
    "new_meeting_date", "new_meeting_hours", "new_meeting_tag",
    "new_meeting_outputs_sel", "new_meeting_grupo_sel", "new_meeting_user_sel",
    "new_meeting_usertype_sel", "new_meeting_location_sel",
]

with st.form("new_meeting_form"):
    c1, c2, c3 = st.columns([1, 1, 2])
    m_date = c1.date_input("Date", value=datetime.date.today(), key="new_meeting_date")
    m_hours = c2.number_input("Time (hours)", min_value=0.0, value=1.0, step=0.5, key="new_meeting_hours")
    m_outputs = field_with_options(c3, "Meeting Outputs", MEETING_OUTPUT_OPTIONS, "new_meeting_outputs")

    c4, c5, c6, c7 = st.columns(4)
    m_grupo = field_with_options(c4, "Grupo", GRUPO_OPTIONS, "new_meeting_grupo")
    m_user = field_with_options(c5, "User", USER_OPTIONS, "new_meeting_user")
    m_user_type = field_with_options(c6, "User Type", USER_TYPE_OPTIONS, "new_meeting_usertype")
    m_user_location = field_with_options(c7, "User Location", LOCATION_OPTIONS, "new_meeting_location")

    # Consultation meetings usually aren't tied to a tracked project -- keep the tag out of
    # the way, clearly optional, instead of leading the form with it.
    m_project_tag = st.text_input(
        "Project tag (optional)", key="new_meeting_tag",
        help="Most consultation meetings aren't tied to a tracked project — leave blank. "
             "Fill it only when the meeting belongs to a project in the tracker.",
    )

    st.caption("Fill the meeting in, then click Add meeting — one click writes one row.")
    m_submitted = st.form_submit_button("➕ Add meeting")
    if m_submitted and not any(v.strip() for v in (m_grupo, m_user, m_outputs, m_project_tag)):
        # Pressing Enter in a text box submits a Streamlit form, so without this a stray
        # Enter mid-typing would append a row holding nothing but today's date and 1 hour.
        st.warning("Nothing to add yet — fill in at least a Grupo, User, Meeting Output or "
                   "Project tag first. (Pressing Enter in a text box submits the form.)")
    elif m_submitted:
        try:
            kd.append_meeting_row(period["file"], period["meetings_sheet"], {
                "Project tag": m_project_tag.strip(),
                "Grupo": m_grupo,
                "User Type": m_user_type,
                "User Location": m_user_location,
                "User": m_user,
                "Date": m_date,
                "Meeting Outputs": m_outputs.strip(),
                "Time": m_hours,
            })
        except PermissionError:
            st.error(f"Couldn't save — {period['file'].name} is open in Excel (or locked by "
                     "OneDrive). Close it and submit again.")
        else:
            st.success("Added.")
            clear_fields(NEW_MEETING_KEYS)
            st.rerun()
