"""Mtime-keyed st.cache_data wrappers around kpi_data's file readers.

Streamlit reruns the whole page script on every widget interaction, and kpi_data reads the
Excel/CSV files fresh each call -- correct, but it makes every click pay the full file-read
cost (the Add Data page alone re-opens every period workbook six times for its dropdowns).
These wrappers cache each reader keyed on the source file's modification time (`mtime_key`),
so:

  - repeated reruns with unchanged files hit the cache (fast), and
  - any change to a file -- a dashboard save, or editing it directly in Excel -- bumps the
    mtime, which changes the cache key, which transparently reloads. The "edit a file and
    just interact with any control to see the update" behavior is preserved.

Note: parameters named with a leading underscore (like `_periods`) are deliberately
EXCLUDED from the cache key by st.cache_data -- the mtime_key params must NOT start with
an underscore or the cache would never invalidate.

kpi_data itself deliberately stays streamlit-free (the snapshot exporter imports it
headless); only this module and the pages know about st.cache_data.
"""

from pathlib import Path

import streamlit as st

import kpi_data as kd


def _mtime(path):
    try:
        return Path(path).stat().st_mtime
    except OSError:
        return 0.0


def _period_files_key():
    return tuple(sorted((str(f), _mtime(f)) for f in kd.DATA_DIR.glob("KPI*.xlsx")))


@st.cache_data(show_spinner=False)
def _load_timelog(dark, mtime_key):
    return kd.load_timelog(dark=dark)


def load_timelog(dark=False):
    return _load_timelog(dark, _mtime(kd.TIMELOG_PATH))


@st.cache_data(show_spinner=False)
def _load_time_entries(mtime_key):
    return kd.load_time_entries()


def load_time_entries():
    """The stopwatch store behind the Time Tracker page. st.cache_data hands back a copy per
    caller, so the page's start/stop/edit paths are free to mutate what they get before
    writing it back -- which is exactly what they all do. The file changes on nearly every
    interaction with that page, so this mostly earns its keep on the OTHER pages' reruns and
    on the tracker's own once-a-second running-clock fragment."""
    return _load_time_entries(_mtime(kd.TIME_ENTRIES_PATH))


@st.cache_data(show_spinner=False)
def _discover_periods(mtime_key):
    return kd.discover_periods()


def discover_periods():
    return _discover_periods(_period_files_key())


@st.cache_data(show_spinner=False)
def _load_projects(xlsx_path, sheet_name, mtime_key):
    return kd.load_projects(xlsx_path, sheet_name)


def load_projects(xlsx_path, sheet_name):
    return _load_projects(str(xlsx_path), sheet_name, _mtime(xlsx_path))


@st.cache_data(show_spinner=False)
def _load_meetings(xlsx_path, meetings_sheet, mtime_key):
    return kd.load_meetings(xlsx_path, meetings_sheet)


def load_meetings(xlsx_path, meetings_sheet):
    return _load_meetings(str(xlsx_path), meetings_sheet, _mtime(xlsx_path))


@st.cache_data(show_spinner=False)
def _load_goals(mtime_key):
    return kd.load_goals()


def load_goals():
    return _load_goals(_mtime(kd.GOALS_PATH))


@st.cache_data(show_spinner=False)
def _load_tools(mtime_key):
    return kd.load_tools()


def load_tools():
    return _load_tools(_mtime(kd.TOOLS_PATH))


@st.cache_data(show_spinner=False)
def _build_project_lookup(mtime_key):
    # discover_periods()/load_projects() are called directly (not through this module's own
    # cached wrappers) to avoid one cached function calling another under the hood -- this is
    # already cached at this level, keyed on every period file's own mtime below.
    return kd.build_project_lookup(kd.discover_periods(), kd.load_projects)


def build_project_lookup():
    return _build_project_lookup(_period_files_key())


@st.cache_data(show_spinner=False)
def _load_expected_gains(mtime_key, period_key):
    # goals_df/tools_df/project_lookup are DataFrames/dicts -- not hashable, so they can't be
    # cache-key params. Loaded here instead; this function's own cache still only recomputes
    # when one of the source files (gains workbook, ratings sheet, tools inventory, or any
    # period workbook the Reuse-to-tracker join reads) actually changes.
    return kd.load_expected_gains(kd.load_goals(), kd.load_tools(), _build_project_lookup(period_key))


def load_expected_gains():
    period_key = _period_files_key()
    mtime_key = (_mtime(kd.EXPECTED_GAINS_PATH), _mtime(kd.GOALS_PATH), _mtime(kd.TOOLS_PATH))
    return _load_expected_gains(mtime_key, period_key)

@st.cache_data(show_spinner=False)
def _load_gains_sheets(mtime_key):
    return kd.load_gains_sheets()


def load_gains_sheets():
    """The raw gains.xlsx sheets the editors read (kpi_gains_editor). Cached on the file's own
    mtime for the same reason every other loader here is, but it matters more for this one: the
    Tools page draws a reuse editor inside EVERY card, so an uncached read would re-open the
    workbook sixteen times per rerun. A save bumps the mtime, so the next rerun sees the change
    with no cache clearing at the call site.

    st.cache_data hands back a copy per caller, so an editor is free to mutate what it gets
    before writing it back -- which is exactly what they all do."""
    return _load_gains_sheets(_mtime(kd.GAINS_PATH))


@st.cache_data(show_spinner=False)
def _load_project_tasks(mtime_key):
    return kd.load_project_tasks()


def load_project_tasks():
    """Cached task checklists. The file lives in a OneDrive-synced folder, where a read can
    block while OneDrive uploads the copy an edit just produced -- so re-reading it several
    times per rerun (and on every rerun that didn't change it) is what made the page stall.
    st.cache_data hands back a copy, so callers can still mutate what they get."""
    return _load_project_tasks(_mtime(kd.TASKS_PATH))


@st.cache_data(show_spinner=False)
def _field_options(col, _periods, mtime_key):
    return kd.project_field_options(_periods, col)


def project_field_options(periods, col):
    return _field_options(col, periods, _period_files_key())


@st.cache_data(show_spinner=False)
def _meeting_field_options(col, _periods, mtime_key):
    return kd.meeting_field_options(_periods, col)


def meeting_field_options(periods, col):
    return _meeting_field_options(col, periods, _period_files_key())


@st.cache_data(show_spinner=False)
def _load_cv(mtime_key):
    return kd.load_cv()


def load_cv():
    """The CV content store. st.cache_data hands back a copy per caller, so the CV page is
    free to mutate what it gets before saving it -- which is exactly what its editors do."""
    return _load_cv(_mtime(kd.CV_PATH))


@st.cache_data(show_spinner=False)
def _load_cv_outputs(mtime_key):
    return kd.load_cv_outputs()


def load_cv_outputs():
    return _load_cv_outputs(_mtime(kd.CV_OUTPUTS_PATH))


@st.cache_data(show_spinner=False)
def _load_publications(mtime_key):
    return kd.load_publications()


def load_publications():
    return _load_publications(_mtime(kd.PUBLICATIONS_PATH))


@st.cache_data(show_spinner=False)
def _cv_role_metrics(period_key, mtime_key):
    # Reads every period workbook, the tools inventory, the time log, the pause notes and
    # both output stores, then runs the turnaround maths per period -- by far the heaviest
    # thing the CV page asks for, and all of it keyed on the files it actually reads, so a
    # rerun that changed none of them costs nothing.
    return kd.cv_role_metrics(
        kd.discover_periods(), tools_df=kd.load_tools(), timelog=kd.load_timelog(dark=False)[0],
        pause_notes=kd.load_pause_notes(), all_pubs=kd.load_publications(),
        all_outputs=kd.load_cv_outputs(),
    )


def cv_role_metrics():
    mtime_key = (_mtime(kd.TOOLS_PATH), _mtime(kd.TIMELOG_PATH), _mtime(kd.PAUSE_NOTES_PATH),
                 _mtime(kd.PUBLICATIONS_PATH), _mtime(kd.CV_OUTPUTS_PATH))
    return _cv_role_metrics(_period_files_key(), mtime_key)
