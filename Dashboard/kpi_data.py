"""Data loading and shared computation for the KPI dashboard.

Everything here reads straight from the Excel/CSV files in ../Data each time it's
called — there's no caching, so editing a file and rerunning the app (or clicking
any widget, which reruns the whole script) always reflects the latest data on disk.
"""

import json
import math
import re
import uuid
from pathlib import Path

import openpyxl
import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent / "Data"
TIMELOG_PATH = DATA_DIR / "track_time.csv"
GOALS_PATH = DATA_DIR / "Special_Projects_Ratings.xlsx"
TASKS_PATH = DATA_DIR / "special_project_tasks.json"
TASKS_XLSX_PATH = DATA_DIR / "Special_Projects_Tasks.xlsx"
BEYOND_XLSX_PATH = DATA_DIR / "Beyond_Projects.xlsx"

MONTH_ORDER = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

# --- Colors -----------------------------------------------------------------------------
RECEIVED_COLOR = "#1a6090"   # navy — IN
FINISHED_COLOR = "#1f9e8a"   # teal — OUT
WORKLOAD_COLOR = "#c9701e"   # orange — running "real workload" line
INK = "#1a1a1a"
MUTED = "#6b6b6b"
GRID = "#d8d8d8"
BASELINE = "#444444"

TL_INK_PRIMARY = "#0b0b0b"
TL_INK_SECONDARY = "#52514e"
TL_INK_MUTED = "#898781"
TL_GRID = "#e1e0d9"
TL_BASELINE = "#c3c2b7"
TL_SURFACE = "#fcfcfb"
TL_GOOD = "#0ca30c"      # status: increase
TL_CRITICAL = "#d03b3b"  # status: decrease

# A more muted/deeper variant of the dataviz skill's validated default categorical theme
# (same method, re-stepped for a less bright, more "professional" feel) -- re-validated
# with the skill's validator (all 6 checks PASS, both modes, light surface #fcfcfb / dark
# surface #1a1a19): worst adjacent CVD ΔE 8.9 light / 9.2 dark, worst adjacent
# normal-vision ΔE 18.1 light / 17.1 dark, contrast >= 3:1 on all 8 slots in both modes
# (an improvement over the original default, which needed a contrast-relief WARN for 3 slots).
TL_PALETTE = ["#1f5c99", "#c1622e", "#1a8f6b", "#b8860b", "#b5577a", "#3a7d2c", "#5c4a8f", "#b23a3a"]
TL_PALETTE_DARK = ["#4a84c9", "#c76a35", "#29ab82", "#a87910", "#b2567d", "#5c9c4a", "#7a68b3", "#c75555"]

RAW_COLUMNS = [
    "Entry", "Timesheet updated", "Category", "Hours (exact)", "Major task name (chart)",
    "Hrs", "Min", "", "Month", "Month and year (chart)", "Notes", "Week",
    "Weekly entry name (chart)", "Year",
]

# Historical major-task values renamed on load; saving a row afterwards migrates the file.
MAJOR_TASK_RENAMES = {"AI Agent": "AI Skills", "Study": "Plan/Study"}

# A task that should read as one consistent color on the merged by-month/by-task charts
# even though its real rows legitimately span categories -- see _task_category_priority's
# use of this below. Doesn't touch the rows' own logged Category. Empty here since this
# demo's fake data has no task that genuinely needs the override.
TASK_CATEGORY_COLOR_OVERRIDES = {}

# Shared with both KPI_Report.py's sidebar and the Add Data page -- picking a category or
# major task for a new row is exactly where this reference is most useful.
GLOSSARY_MD = """
**Categories**
- **Projects** — hands-on work tied to a specific tracked project: coding, project-specific
  meetings/comms, project organization, and project-related study or tooling.
- **Projects-Development** — projects centered on building tools or **AI Skills** (e.g. Claude
  Code skills/agents), rather than a specific data/analysis deliverable.
- **Meetings (non-project)** — meetings not tied to a specific tracked project: internal group
  meetings, external meetings whether or not correlated with an active project, or strategic
  meetings (e.g. a cross-team or facility meeting).
- **Org & Admin** — organizational and administrative matters: seminars, bureaucracy, and
  group or personal organization tasks.
- **Trainning** — training attended or given.

**Notable major tasks**
- **Meetings/Comms** — project-specific meetings, but counts as communications as well
  (emails, Slack, async check-ins about the project), not just the meeting itself.
- **Internal org** — communications, emails, and group organization requirements (including
  Timesheet and other time-tracking upkeep).
- **AI Skills** (formerly logged as "AI Agent") — development of AI-based tools/skills as part
  of a Projects-Development initiative.
- **Plan/Study** (formerly logged as "Study") — planning work and studying documentation,
  methods, or background material.
"""

# Shared with both the main page's Year tab (right by the chart) and the Add Data page --
# explains the "Projects received vs finished" chart's bars/line and the different date
# columns behind them, since those don't map one-to-one onto anything in the glossary above.
RECEIVED_FINISHED_GLOSSARY_MD = """
**Bars**
- **Received (navy, top half)** — counted by *received date*: normally Register Project,
  except an Inherited Project, which counts from Begining instead (its registration ran
  under whoever had it before).
- **Finished (teal, bottom half)** — counted by **Closing Day**: the administrative close,
  not the deliverable itself. A project can finish its real work (Final Report Sent) well
  before it's formally closed — hover a bar to see which projects closed the same day
  their report went out vs. later, and by how much.

**Orange dashed line — real workload**
A project counts as *open* for a month if it had already started by that month's end and
hadn't yet ended by then — "started" is first contact (First User Meeting/Shared Data,
or Begining for an Inherited Project), "ended" is Final Report Sent, falling back to
Closing Day if no report was ever sent. Consulting-trigger projects are left off this line
entirely (a standing advisory thread has no start/end to be "open" between).

**Different time tracking, in one place**
Several distinct dates feed this chart, each answering a different question:
- *Register Project* / *Begining* — when the project entered the tracker vs. when work on
  it actually began (not always the same day).
- *Final Report Sent* — the real deliverable going out.
- *Closing Day* — the administrative close, which can lag the report by days or weeks.
- *Register → Closing Day* — the full span Timesheet tracks, used for the effort view on the
  Projects Review page rather than this chart.
"""


def format_hm(hours, signed=False):
    """3.9166 -> '3h55min'; 4.0 -> '4h'; -1.1 -> '-1h06min'; signed=True adds a '+' for > 0."""
    sign = "-" if hours < 0 else ("+" if signed and hours > 0 else "")
    total_minutes = round(abs(hours) * 60)
    h, m = divmod(total_minutes, 60)
    return f"{sign}{h}h" if m == 0 else f"{sign}{h}h{m:02d}min"


def _lighten(hex_color, amount):
    """Blend `hex_color` toward white by `amount` (0 = unchanged, 1 = white)."""
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    r, g, b = (round(c + (255 - c) * amount) for c in (r, g, b))
    return f"#{r:02x}{g:02x}{b:02x}"


# Categories that are related but don't share a name prefix (so build_category_palette's
# prefix heuristic can't group them on its own): {category: the family it tints toward}.
# Empty here since this demo's fake categories don't need one -- fill in a {category: family}
# pairing if your own data has a related category that isn't already a name prefix match.
CATEGORY_FAMILY_ALIASES = {}


def build_category_palette(df, category_col="Category", value_col="Hours (exact)", dark=False):
    """Category display order and a color per category, both derived from whatever
    categories are actually present in `df`. Related categories (one name a prefix of
    another, e.g. "Projects" / "Projects-Development", or an explicit pairing in
    CATEGORY_FAMILY_ALIASES) get tints of one hue and sit next to each other; every other
    family gets its own palette hue."""
    palette = TL_PALETTE_DARK if dark else TL_PALETTE
    totals = df.groupby(category_col)[value_col].sum()
    names = list(totals.index)

    def family_key(name):
        alias = CATEGORY_FAMILY_ALIASES.get(name)
        if alias and alias in names:
            return alias
        prefixes = [n for n in names if n != name and name.lower().startswith(n.lower())]
        return min(prefixes, key=len) if prefixes else name

    families = {}
    for cat in totals.sort_values(ascending=False).index:
        families.setdefault(family_key(cat), []).append(cat)
    family_order = sorted(families, key=lambda k: -totals[families[k]].max())

    order = []
    colors = {}
    for i, key in enumerate(family_order):
        base = palette[i % len(palette)]
        members = sorted(families[key], key=lambda c: -totals[c])
        for j, cat in enumerate(members):
            order.append(cat)
            colors[cat] = base if j == 0 else _lighten(base, 0.35 * j)
    return order, colors


def week_bounds(month_name, year, ordinal):
    """Monday/Sunday bounds of the `ordinal`-th Monday-start week overlapping `month_name year`."""
    month_start = pd.Timestamp(year=int(year), month=MONTH_ORDER.index(month_name) + 1, day=1)
    mondays = pd.date_range(month_start, month_start + pd.offsets.MonthEnd(0), freq="W-MON")
    start = mondays[int(ordinal) - 1]
    return start, start + pd.Timedelta(days=6)


def format_week_label(start, end):
    """'Oct 5-11', or 'Oct 26 - Nov 1' / 'Dec 28, 2026 - Jan 3, 2027' across a month/year boundary."""
    if start.year != end.year:
        return f"{start.strftime('%b')} {start.day}, {start.year} - {end.strftime('%b')} {end.day}, {end.year}"
    if start.month != end.month:
        return f"{start.strftime('%b')} {start.day} - {end.strftime('%b')} {end.day}"
    return f"{start.strftime('%b')} {start.day}-{end.day}"


def load_timelog(dark=False):
    """Read track_time.csv and return (df, category_order, category_colors, task_category,
    raw_df). `raw_df` keeps the original columns/row order so edits can be written back
    without reshuffling the file. `dark` picks the light/dark variant of the category
    palette (TL_PALETTE / TL_PALETTE_DARK)."""
    raw_df = pd.read_csv(TIMELOG_PATH, sep=";", encoding="utf-8-sig")
    df = raw_df.rename(columns={"Weekly entry name (chart)": "Project"}).copy()

    df["Hrs"] = pd.to_numeric(df["Hrs"], errors="coerce").fillna(0)
    df["Min"] = pd.to_numeric(df["Min"], errors="coerce").fillna(0)
    df["Hours (exact)"] = df["Hrs"] + df["Min"] / 60

    df["Week"] = df["Week"].astype(str).str.replace(r"\s*\(https?://\S+\)", "", regex=True).str.strip()
    df["Major task name (chart)"] = df["Major task name (chart)"].replace(MAJOR_TASK_RENAMES)
    df["Month"] = pd.Categorical(df["Month"], categories=MONTH_ORDER, ordered=True)

    week_ordinal = df["Week"].str.extract(r"^(\d+)").astype(int)[0]
    if len(df):
        week_start, week_end = zip(*(
            week_bounds(month, year, ordinal)
            for month, year, ordinal in zip(df["Month"], df["Year"], week_ordinal)
        ))
    else:
        # zip(*()) can't unpack into two names -- an empty log (a brand-new tracker with
        # no entries yet) is valid, not an error. Typed as datetime64, not a bare [], so
        # later Timestamp comparisons (weeks_in_period etc.) don't get a dtype they can't
        # compare against.
        week_start = week_end = pd.Series([], dtype="datetime64[ns]")
    df["_week_sort"] = week_start
    df["_week_end"] = week_end
    df["Week"] = [format_week_label(s, e) for s, e in zip(week_start, week_end)]

    category_order, category_colors = build_category_palette(df, dark=dark)

    def _task_category_priority(categories):
        """A major task name maps to exactly one category for coloring purposes (one
        wedge/bar = one color). Normally that's whichever category the task appears under
        most often, but "Projects-Development" always wins outright, even as a minority of
        that task's rows -- a task logged as Projects-Development even once still gets
        counted there rather than folded into "Projects"."""
        if "Projects-Development" in set(categories):
            return "Projects-Development"
        return categories.mode().iat[0]

    task_category = df.groupby("Major task name (chart)")["Category"].agg(_task_category_priority)
    # TASK_CATEGORY_COLOR_OVERRIDES: some tasks' real rows legitimately span categories (a
    # project-specific "Plan/Study" or "External Meeting" can land under Projects-Development
    # just because that's the project's own category) -- the rows themselves are correct as
    # logged, and this doesn't touch them. It only overrides which single color this task
    # resolves to for the *merged* charts (Major-task hours by month, Major task share of
    # total hours), so one task reads as one consistent color over time instead of flipping
    # to Projects-Development's shade because of a single project's categorization. Charts
    # that split a task by its rows' real Category (the Month donut, hours-by-project-task)
    # are unaffected -- they never consult this map for color, only this one's row order.
    for task, cat in TASK_CATEGORY_COLOR_OVERRIDES.items():
        if task in task_category.index and cat in category_order:
            task_category.loc[task] = cat

    return df, category_order, category_colors, task_category, raw_df


def parse_tracker_date(series):
    """Notion exports these columns as JS `Date.toString()` text (e.g. "Wed Oct 07 2026
    01:00:00 GMT+0100 (British Summer Time)") -- strip the trailing parenthetical and parse
    the fixed JS format explicitly, falling back to the generic parser otherwise."""
    as_str = series.astype(str).str.strip()
    js_format = as_str.str.replace(r"\s*\([^)]*\)\s*$", "", regex=True)
    parsed = pd.to_datetime(js_format, format="%a %b %d %Y %H:%M:%S GMT%z", errors="coerce", utc=True)
    parsed = parsed.dt.tz_localize(None)
    fallback = pd.to_datetime(series, format="mixed", errors="coerce")
    return parsed.fillna(fallback)


DATE_COLS = [
    "First User Meeting/Shared Data", "Register Project", "Begining",
    "Final Report Sent", "Closing Day",
]


def discover_periods():
    """Find every reporting-period sheet pair across every KPI*.xlsx file in ../Data,
    e.g. "2025_CALENDAR" + "2025_CALENDAR_meetings" -> the full calendar year 2025
    (2025-01-01 up to, but not including, 2026-01-01). This demo build uses plain
    calendar years rather than a fiscal year starting mid-month, since there's no
    institutional fiscal date to anchor to here -- swap the regex/dates below for your
    own convention if you have one.
    A period can live in more than one file (e.g. while splitting one workbook into a
    file per period, each copy still carries every sheet for a while) -- the file whose
    name itself starts with that period's year is preferred; otherwise whichever file
    has it first, so nothing breaks mid-split.
    Returns a list of dicts sorted newest-first, each with: label, sheet, meetings_sheet,
    file (Path to read `sheet`/`meetings_sheet` from), start (Timestamp), end (Timestamp)."""
    candidates = {}  # year -> list of (file_path, sheet_names)
    for xlsx_path in sorted(DATA_DIR.glob("KPI*.xlsx")):
        wb = openpyxl.load_workbook(xlsx_path, read_only=True)
        names = wb.sheetnames
        wb.close()
        for name in names:
            m = re.match(r"^(\d{4})_CALENDAR$", name)
            if not m:
                continue
            year = int(m.group(1))
            candidates.setdefault(year, []).append((xlsx_path, names))

    periods = []
    for year, matches in candidates.items():
        preferred = next(
            (fp for fp, _ in matches if fp.stem == f"KPI_{year}"), matches[0][0],
        )
        names = next(names for fp, names in matches if fp == preferred)
        meetings_name = f"{year}_CALENDAR_meetings"
        periods.append({
            "label": f"{year}",
            "sheet": f"{year}_CALENDAR",
            "meetings_sheet": meetings_name if meetings_name in names else None,
            "file": preferred,
            "start": pd.Timestamp(year=year, month=1, day=1),
            "end": pd.Timestamp(year=year + 1, month=1, day=1),
        })
    periods.sort(key=lambda p: p["start"], reverse=True)
    return periods


_SIMPLE_FORMULA_RE = re.compile(r"^[\d\s+\-*/().]+$")


def _eval_simple_formula(formula):
    """Evaluate a simple numeric-only Excel formula (e.g. '=2+1', '=-5') for when no
    cached result is available for pandas/openpyxl to read -- the file hasn't been
    recalculated and saved by actual Excel since the formula was typed, which leaves
    pandas reading a blank. Returns None for anything beyond plain arithmetic on
    literals -- this never evaluates a real formula that references other cells, only a
    self-contained expression, so there's no risk of running arbitrary code."""
    if not isinstance(formula, str) or not formula.startswith("="):
        return None
    body = formula[1:].strip()
    if not body or not _SIMPLE_FORMULA_RE.match(body):
        return None
    try:
        return float(eval(body, {"__builtins__": {}}, {}))
    except Exception:
        return None


def _fill_blank_formula_cells(xlsx_path, sheet_name, df, columns):
    """For any column in `columns` where pandas read a blank (no cached formula result
    yet), try reading the raw formula from the cell directly and evaluating it if it's
    simple arithmetic. Read-only: never writes anything back to the file -- this only
    improves what the dashboard itself sees in memory for this one load."""
    missing_cols = [c for c in columns if c in df.columns and df[c].isna().any()]
    if not missing_cols:
        return df
    wb = openpyxl.load_workbook(xlsx_path, data_only=False)
    ws = wb[sheet_name]
    headers = [cell.value for cell in ws[1]]
    for col in missing_cols:
        col_idx = headers.index(col) + 1
        for i in df.index[df[col].isna()]:
            cell = ws.cell(row=i + 2, column=col_idx)  # +2: header row, then 0-based index
            value = _eval_simple_formula(cell.value)
            if value is not None:
                df.loc[i, col] = value
    wb.close()
    return df


def load_projects(xlsx_path, sheet_name):
    """The 20-ish-row project tracker for one reporting-period sheet."""
    projects = pd.read_excel(xlsx_path, sheet_name=sheet_name, header=0, nrows=20, engine="openpyxl")
    projects = projects.replace("AI Agent", "AI Skills")
    projects["Project tag"] = projects["Project tag"].astype(str).str.strip()

    for col in DATE_COLS:
        if col in projects.columns:
            projects[col] = parse_tracker_date(projects[col])

    bad_close = projects["Closing Day"] < projects["Register Project"]
    projects.loc[bad_close, "Closing Day"] = pd.NaT

    projects = _fill_blank_formula_cells(
        xlsx_path, sheet_name, projects, ["Hours in Timesheet", "Number of Meetings", "Number of Reports"],
    )
    return projects


def load_meetings(xlsx_path, meetings_sheet):
    if not meetings_sheet:
        return pd.DataFrame(columns=["Grupo", "Meeting Outputs"])
    return pd.read_excel(xlsx_path, sheet_name=meetings_sheet, header=0, engine="openpyxl")


def ordinal_week_label(week_start):
    """Reverse of week_bounds: the 'Nth Month'-style label Notion would give the week
    starting on this Monday (e.g. Timestamp('2026-10-19') -> '4th October')."""
    month_name = week_start.strftime("%B")
    month_start = pd.Timestamp(year=week_start.year, month=week_start.month, day=1)
    mondays = pd.date_range(month_start, month_start + pd.offsets.MonthEnd(0), freq="W-MON")
    ordinal = list(mondays).index(week_start) + 1
    suffix = "th" if 11 <= ordinal % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(ordinal % 10, "th")
    return f"{ordinal}{suffix} {month_name}"


EDIT_COLS = [
    "Weekly entry name (chart)", "Category", "Major task name (chart)",
    "Hrs", "Min", "Timesheet updated", "Notes",
]


def _row_hours(row):
    hrs = pd.to_numeric(row.get("Hrs"), errors="coerce")
    mins = pd.to_numeric(row.get("Min"), errors="coerce")
    hrs = 0 if pd.isna(hrs) else hrs
    mins = 0 if pd.isna(mins) else mins
    return hrs, mins


def apply_week_edits(raw_df, orig_index, edited, week_start):
    """Merge a data_editor result for one week back into the raw time-log frame.

    The editor is fed the week's rows with a 0..n-1 index (orig_index[i] is the raw_df
    label behind editor position i); st.data_editor(num_rows="dynamic") keeps those labels
    on surviving rows, drops the labels of deleted rows, and gives added rows labels >= n.
    So: surviving labels < n overwrite their raw row (Hours (exact) recomputed), labels
    missing from `edited` delete their raw row, and labels >= n append brand-new entries
    with Month/Year/Week filled in from `week_start`. Returns the updated raw frame --
    caller is responsible for writing it to disk."""
    n_orig = len(orig_index)
    updated_raw = raw_df.copy()

    to_delete = []
    for i, idx in enumerate(orig_index):
        if i in edited.index:
            for col in EDIT_COLS:
                updated_raw.loc[idx, col] = edited.loc[i, col]
            hrs, mins = _row_hours(edited.loc[i])
            updated_raw.loc[idx, "Hrs"] = hrs
            updated_raw.loc[idx, "Min"] = mins
            updated_raw.loc[idx, "Hours (exact)"] = hrs + mins / 60
        else:
            to_delete.append(idx)
    if to_delete:
        updated_raw = updated_raw.drop(index=to_delete)

    new_rows = edited.loc[[i for i in edited.index if i >= n_orig]]
    rows_to_add = []
    week_text = ordinal_week_label(week_start)
    month_name = week_start.strftime("%B")
    for _, r in new_rows.iterrows():
        if not str(r.get("Weekly entry name (chart)", "") or "").strip():
            continue
        hrs, mins = _row_hours(r)
        timesheet = str(r.get("Timesheet updated", "") or "").strip()
        rows_to_add.append({
            "Entry": r.get("Weekly entry name (chart)", ""),
            "Timesheet updated": timesheet if timesheet in ("Yes", "No", "N/A") else "No",
            "Category": r.get("Category", ""),
            "Hours (exact)": hrs + mins / 60,
            "Major task name (chart)": r.get("Major task name (chart)", ""),
            "Hrs": hrs,
            "Min": mins,
            "Month": month_name,
            "Month and year (chart)": f"{month_name} {week_start.year}",
            "Notes": r.get("Notes", ""),
            "Week": week_text,
            "Weekly entry name (chart)": r.get("Weekly entry name (chart)", ""),
            "Year": week_start.year,
        })
    if rows_to_add:
        updated_raw = pd.concat([updated_raw, pd.DataFrame(rows_to_add)], ignore_index=True)
    return updated_raw


# --- Tag cells in the week editor ---------------------------------------------------------
# The Project / Category / Major task columns hold one tag each, but the grid renders them
# as MultiselectColumn -- the only st.column_config type that takes accept_new_options, and
# so the only one a brand-new tag can be typed into (SelectboxColumn still has no such
# parameter as of Streamlit 1.67). These convert between the stored text and the one-item
# lists the multiselect cells want.
def tag_to_cell(value):
    """Stored tag text -> the list a multiselect cell expects ([] when blank)."""
    text = "" if value is None else str(value).strip()
    return [text] if text and text.lower() != "nan" else []


def tag_from_cell(value):
    """A multiselect cell -> the single tag to store. Keeps the first entry: the column is
    single-valued by convention, but the cell will happily accept several."""
    if value is None or isinstance(value, float):  # float covers NaN on untouched new rows
        return ""
    if isinstance(value, str):
        return value.strip()
    picked = [str(v).strip() for v in value if str(v).strip()]
    return picked[0] if picked else ""


def tag_cell_overfilled(value):
    """True when a multiselect cell holds more than one tag, so the editor can say that
    only the first will be saved."""
    if value is None or isinstance(value, (str, float)):
        return False
    return len([v for v in value if str(v).strip()]) > 1


# --- Persistent custom tags for the week editor dropdowns ---------------------------------
CUSTOM_TAGS_PATH = DATA_DIR / "custom_tags.json"
_TAG_KINDS = ("projects", "categories", "major_tasks")


def load_custom_tags():
    """User-added dropdown tags that aren't (yet) used in any saved row, so they survive
    app restarts: {"projects": [...], "categories": [...], "major_tasks": [...]}."""
    empty = {k: [] for k in _TAG_KINDS}
    if not CUSTOM_TAGS_PATH.exists():
        return empty
    try:
        data = json.loads(CUSTOM_TAGS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return empty
    return {k: [str(v) for v in data.get(k, [])] for k in _TAG_KINDS}


def add_custom_tags(projects=(), categories=(), major_tasks=()):
    """Append new tags (deduplicated, blanks dropped) and persist. Returns the list of
    tags actually added."""
    tags = load_custom_tags()
    added = []
    for kind, values in (("projects", projects), ("categories", categories), ("major_tasks", major_tasks)):
        for v in values:
            v = str(v).strip()
            if v and v not in tags[kind]:
                tags[kind].append(v)
                added.append(v)
    if added:
        CUSTOM_TAGS_PATH.write_text(json.dumps(tags, indent=2, ensure_ascii=False), encoding="utf-8")
    return added


def filter_to_period(df, period):
    """Time-log rows whose week starts within [period.start, period.end)."""
    mask = (df["_week_sort"] >= period["start"]) & (df["_week_sort"] < period["end"])
    return df.loc[mask].copy()


def label_period_months(df_period):
    """Replace the plain 'Month' column with a 'October 2026'-style label, ordered
    chronologically -- needed because a reporting period spans a year boundary (Oct-Oct),
    so the bare month name alone can't tell e.g. Oct 2026 apart from Oct 2027. Returns
    (labeled_df, months_present_in_order)."""
    df_period = df_period.copy()
    pairs = df_period[["Year", "Month"]].drop_duplicates()
    if pairs.empty:
        return df_period, []
    pairs["_period"] = [
        pd.Period(year=int(y), month=MONTH_ORDER.index(str(m)) + 1, freq="M")
        for y, m in zip(pairs["Year"], pairs["Month"])
    ]
    pairs = pairs.sort_values("_period")
    labels_in_order = [f"{row.Month} {row.Year}" for row in pairs.itertuples()]
    label_map = {(int(r.Year), str(r.Month)): f"{r.Month} {r.Year}" for r in pairs.itertuples()}
    df_period["Month"] = pd.Categorical(
        [label_map[(int(y), str(m))] for y, m in zip(df_period["Year"], df_period["Month"])],
        categories=labels_in_order, ordered=True,
    )
    return df_period, labels_in_order


def weeks_in_period(df, period):
    """Distinct (week_start, label) pairs within `period`, oldest first."""
    sub = df.loc[(df["_week_sort"] >= period["start"]) & (df["_week_sort"] < period["end"])]
    pairs = sub[["_week_sort", "Week"]].drop_duplicates().sort_values("_week_sort")
    return list(pairs.itertuples(index=False, name=None))


def selectable_weeks(df, period, today, lookahead=2):
    """Weeks with logged entries, plus the current week and a short lookahead window --
    so upcoming weeks are always choosable for pre-filling, even before any hours are
    logged for them. Past/closed periods just get their existing weeks (today won't fall
    inside them, so the lookahead loop below is a no-op there)."""
    starts = {s for s, _ in weeks_in_period(df, period)}
    this_monday = today - pd.Timedelta(days=today.dayofweek)
    for i in range(lookahead + 1):
        candidate = this_monday + pd.Timedelta(days=7 * i)
        if period["start"] <= candidate < period["end"]:
            starts.add(candidate)
    ordered = sorted(starts)
    return [(s, format_week_label(s, s + pd.Timedelta(days=6))) for s in ordered]


def default_week(weeks, today):
    """Current week if it's in `weeks`, else the most recent one on/before today, else the latest available."""
    this_monday = today - pd.Timedelta(days=today.dayofweek)
    starts = [w[0] for w in weeks]
    if this_monday in starts:
        return this_monday
    past = [s for s in starts if s <= this_monday]
    if past:
        return max(past)
    return max(starts) if starts else None


def default_month(months, current_label):
    if current_label in months:
        return current_label
    return months[-1] if months else None


def _task_is_blank(task):
    return (not str(task.get("text") or "").strip() and not task.get("due")
            and not task.get("start") and not task.get("done"))


def _normalize_task_keys(all_tasks):
    """Fold project names that differ only by surrounding whitespace into one checklist.

    Checklists are keyed by project name. A name typed into the ratings sheet with a
    trailing space ("MultiOMICs Dashboard ") used to be stored verbatim, so trimming the
    name later left its tasks stranded under a key nothing looked up any more -- the tasks
    appeared to vanish. Everything is keyed by the stripped name now; this folds any older
    stranded entries back in (richer list first) and drops the empty placeholder rows a
    merge would otherwise leave behind."""
    merged = {}
    for name, tasks in all_tasks.items():
        key = str(name).strip()
        if key in merged:
            combined = merged[key] + list(tasks)
            if any(not _task_is_blank(t) for t in combined):
                combined = [t for t in combined if not _task_is_blank(t)]
            merged[key] = combined
        else:
            merged[key] = list(tasks)
    return merged


def load_project_tasks():
    """Per-project completion checklists, keyed by (stripped) project name. Lives in its own
    JSON file (not the Excel) since it's dashboard-only state, not part of the ratings data."""
    if not TASKS_PATH.exists():
        return {}
    try:
        return _normalize_task_keys(json.loads(TASKS_PATH.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, OSError):
        return {}


# How far the Excel mirror may trail the JSON while you're editing. Rewriting a workbook
# inside a OneDrive-synced folder stalls the page for seconds (OneDrive locks the file while
# it uploads), so editing never waits on it: the JSON is written immediately and the mirror
# is refreshed when the page is opened, when the snapshot is exported, and -- as a backstop
# for a very long editing session -- at most once per this interval.
TASKS_MIRROR_MAX_LAG = 600.0  # seconds


def sync_tasks_excel(all_tasks=None, max_lag=0.0):
    """Refresh TASKS_XLSX_PATH from the JSON if it has fallen behind by more than
    `max_lag` seconds (0 = always refresh when there is anything to catch up). Returns a
    warning string if the workbook is locked, else None."""
    try:
        json_mtime = TASKS_PATH.stat().st_mtime
    except OSError:
        return None
    xlsx_mtime = TASKS_XLSX_PATH.stat().st_mtime if TASKS_XLSX_PATH.exists() else 0.0
    if json_mtime - xlsx_mtime <= max_lag:
        return None
    try:
        export_tasks_to_excel(load_project_tasks() if all_tasks is None else all_tasks)
    except PermissionError:
        return (f"Saved, but couldn't update {TASKS_XLSX_PATH.name} (close it in Excel to "
                "refresh the mirror on the next edit).")
    return None


def save_project_tasks(all_tasks):
    """Write the JSON source of truth immediately, and refresh the Excel mirror if it has
    fallen more than TASKS_MIRROR_MAX_LAG behind. Returns a warning string if the mirror
    couldn't be written (file open in Excel / locked by OneDrive) -- the JSON save still
    succeeded, so task edits are never lost to a lock."""
    all_tasks = _normalize_task_keys(all_tasks)
    TASKS_PATH.write_text(json.dumps(all_tasks, indent=2, ensure_ascii=False), encoding="utf-8")
    return sync_tasks_excel(all_tasks, max_lag=TASKS_MIRROR_MAX_LAG)


def new_task(level=0, text="", start=None, due=None):
    """A blank checklist task. `start` and `due` are the planned start and finish dates --
    `due` keeps its original key so every date already stored stays exactly where it was."""
    return {"id": uuid.uuid4().hex[:8], "text": text, "level": level, "done": False,
            "start": start, "due": due}


def rename_project_tasks(old_name, new_name):
    """Follow a special project's rename: task checklists are keyed by project name, so
    renaming the project in the ratings sheet without this would orphan its tasks. Returns
    save_project_tasks' Excel-mirror warning (or None); a no-op when the name is unchanged
    or nothing is stored under `old_name`."""
    old_name, new_name = str(old_name).strip(), str(new_name).strip()
    if not new_name or old_name == new_name:
        return None
    all_tasks = load_project_tasks()
    moved = all_tasks.pop(old_name, None)
    if moved is None:
        return None
    all_tasks[new_name] = all_tasks.get(new_name, []) + moved
    return save_project_tasks(all_tasks)


def _task_date(task, key):
    value = task.get(key)
    if not value:
        return None
    parsed = pd.to_datetime(value, errors="coerce")
    return None if pd.isna(parsed) else parsed.date()


def task_due_date(task):
    """The task's planned finish date as a datetime.date, or None if unset/unparseable."""
    return _task_date(task, "due")


def task_start_date(task):
    """The task's planned start date as a datetime.date, or None if unset/unparseable."""
    return _task_date(task, "start")


def task_span(task):
    """(start, finish) for a task, either of which may be None. A task with only a finish
    date is a milestone; one with both is a span that can be drawn as a bar."""
    return task_start_date(task), task_due_date(task)


def task_dates_inconsistent(task):
    """True when both dates are set and the task is planned to finish before it starts."""
    start, due = task_span(task)
    return bool(start and due and start > due)


def project_start(tasks):
    """Earliest planned date across a project's tasks -- a task's start if it has one, else
    its finish date. None when nothing is dated."""
    dates = [d for t in tasks if (d := (task_start_date(t) or task_due_date(t)))]
    return min(dates) if dates else None


def task_schedule(all_tasks, today=None, within_days=None):
    """Split every dated, unfinished task across all special projects into (upcoming,
    overdue), each sorted by date -- soonest first for upcoming, most overdue first for
    behind. Entries carry project, text, due and days (days until / days late), so a
    caller can render both lists without re-deriving anything. `within_days` caps how far
    ahead "upcoming" looks; overdue is always returned in full."""
    today = (today or pd.Timestamp.now().normalize()).date()
    upcoming, overdue = [], []
    for project, tasks in all_tasks.items():
        for task in tasks:
            if task.get("done"):
                continue
            due = task_due_date(task)
            if due is None:
                continue
            entry = {"project": project, "text": (task.get("text") or "").strip() or "(untitled task)",
                     "due": due, "days": (due - today).days}
            (upcoming if due >= today else overdue).append(entry)
    if within_days is not None:
        upcoming = [e for e in upcoming if e["days"] <= within_days]
    upcoming.sort(key=lambda e: e["due"])
    overdue.sort(key=lambda e: e["due"])
    return upcoming, overdue


def predicted_end(tasks):
    """Predicted completion date for a project: the latest planned date among its not-done
    tasks (if none are dated, the latest planned date overall; None if no task has one)."""
    pending = [d for t in tasks if not t.get("done") and (d := task_due_date(t))]
    if pending:
        return max(pending)
    all_dates = [d for t in tasks if (d := task_due_date(t))]
    return max(all_dates) if all_dates else None


_INVALID_SHEET_CHARS = re.compile(r"[\[\]:*?/\\]")


def _sheet_name(project_name, used):
    """A valid, unique (<=31 char) Excel sheet name derived from a project name."""
    name = _INVALID_SHEET_CHARS.sub("-", project_name).strip() or "Project"
    name = name[:31]
    base, i = name, 2
    while name.lower() in used:
        suffix = f" ({i})"
        name = base[: 31 - len(suffix)] + suffix
        i += 1
    used.add(name.lower())
    return name


def export_tasks_to_excel(all_tasks):
    """Mirror the per-project task checklists (held in TASKS_PATH as the source of truth)
    into TASKS_XLSX_PATH, one sheet per project, so the completion plan -- task, nesting
    level, done flag, planned start and completion dates -- also lives somewhere
    Excel-readable. Called
    automatically from save_project_tasks on every edit, so the two files never drift."""
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    used_names = set()

    for project_name, tasks in all_tasks.items():
        ws = wb.create_sheet(_sheet_name(project_name, used_names))
        ws.append(["Task", "Level", "Done", "Planned start date", "Planned completion date"])
        for t in tasks:
            indent = "    " * t.get("level", 0)
            ws.append([
                indent + (t.get("text") or ""),
                t.get("level", 0),
                "Yes" if t.get("done") else "No",
                t.get("start") or "",
                t.get("due") or "",
            ])
        for col, width in zip("ABCDE", (45, 8, 8, 20, 24)):
            ws.column_dimensions[col].width = width

    if not wb.sheetnames:
        wb.create_sheet("No projects yet")
    wb.save(TASKS_XLSX_PATH)


def load_goals():
    goals_df = pd.read_excel(GOALS_PATH, sheet_name="Special Projects Ratings")

    # A row saved without a name or star ratings (e.g. added through the editor and left
    # half-filled) must not crash the bubble chart or the project card: drop nameless rows,
    # default blank ratings to 1.
    goals_df = goals_df[goals_df["Project"].astype(str).str.strip().replace({"nan": "", "None": ""}) != ""].copy()
    # Store the trimmed name everywhere: task checklists are keyed by project name, so a
    # stray trailing space in the sheet would file them under a name nothing looks up.
    goals_df["Project"] = goals_df["Project"].astype(str).str.strip()
    for col in ["Development", "Impact", "Maintenance", "Visibility"]:
        goals_df[col] = pd.to_numeric(goals_df[col], errors="coerce").fillna(1).clip(lower=1)
    goals_df = goals_df.reset_index(drop=True)

    goal_group_colors = {
        "01": ("01 - Reach more research groups", "#2C6E7F"),
        "03": ("03 - Development", "#2A9D8F"),
    }

    def goal_group(goal):
        return goal_group_colors.get(str(goal).strip()[:2], ("Optional - side project", "#8A979C"))

    if len(goals_df):
        goals_df["_group_label"], goals_df["_group_color"] = zip(*goals_df["Goal"].map(goal_group))
    else:
        # zip(*()) can't unpack into two names -- a tracker with no goals yet is valid.
        goals_df["_group_label"], goals_df["_group_color"] = [], []

    coord = pd.Series(list(zip(goals_df["Development"], goals_df["Impact"])), index=goals_df.index)
    group_sizes = coord.map(coord.value_counts())
    group_rank = coord.groupby(coord).cumcount()
    jitter_radius = 0.32
    angle = 2 * math.pi * group_rank / group_sizes.where(group_sizes > 1, 1)
    goals_df["_x"] = goals_df["Development"] + jitter_radius * angle.apply(math.cos) * (group_sizes > 1)
    goals_df["_y"] = goals_df["Impact"] + jitter_radius * angle.apply(math.sin) * (group_sizes > 1)

    def angle_to_textposition(rad):
        sectors = [
            "middle right", "top right", "top center", "top left",
            "middle left", "bottom left", "bottom center", "bottom right",
        ]
        degrees = math.degrees(rad) % 360
        return sectors[int(((degrees + 22.5) % 360) // 45)]

    goals_df["_textpos"] = [
        angle_to_textposition(a) if gs > 1 else "top center"
        for a, gs in zip(angle, group_sizes)
    ]
    return goals_df


GOALS_EDIT_COLS = [
    "Goal", "Project", "Description", "Advantages", "Limitations", "Future gain",
    "Development", "Impact", "Maintenance", "Visibility",
]


GOALS_RATING_COLS = ["Development", "Impact", "Maintenance", "Visibility"]


def save_goals(edited_df):
    """Overwrite the (only) sheet in Special_Projects_Ratings.xlsx with `edited_df`,
    restricted to the real source columns (drops any derived _x/_y/_textpos/etc. columns
    a caller might still be carrying). Rows without a project name are dropped and blank
    star ratings default to 1 so a freshly added row can't leave NaNs that break the
    bubble chart on the next load."""
    cols = [c for c in GOALS_EDIT_COLS if c in edited_df.columns]
    out = edited_df[cols].copy()
    out["Project"] = out["Project"].astype(str).str.strip()
    out = out[out["Project"].replace({"nan": "", "None": ""}) != ""]
    for col in GOALS_RATING_COLS:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce").fillna(1).clip(lower=1).astype(int)
    out.to_excel(GOALS_PATH, sheet_name="Special Projects Ratings", index=False)


# --- Tools & AI Skills inventory -----------------------------------------------------------
TOOLS_PATH = DATA_DIR / "tools.xlsx"
TOOLS_COLS = [
    "Name", "Description", "Type of tool", "Built in", "Use", "Project Origin",
    "Limitations", "Future gain", "Status", "Why deprecated", "Steps",
]
# "Steps" is an optional per-tool breakdown table (e.g. what a multi-step automation creates
# and how), stored as one line per row -- columns separated by a tab (so pasting straight out
# of Excel just works) or, failing that, by "|" (so typing a row by hand in the editor's text
# area works too, since a literal Tab keypress there would just move focus out of the box).
TOOL_STEPS_COLUMNS = ["Step", "How", "AI involved?"]
# "Status" is "" (active) or "Deprecated" -- a tool that's still real and worth keeping on
# record, but no longer the thing to reach for. "Why deprecated" is a free-text reason, only
# meaningful once Status is "Deprecated" -- it isn't always "folded into another tool"
# (e.g. "integrated into Project Closer"); it could just as well be "no longer needed" or
# "replaced by a manual process", so it's left open rather than framed as a successor field.
TOOL_STATUS_OPTIONS = ["", "Deprecated"]


def load_tools():
    """Read the tools/AI-skills inventory from tools.xlsx (first sheet, whatever its name).
    Headers are stripped, expected columns are added if missing, and rows without a Name
    are dropped. May raise FileNotFoundError / PermissionError -- callers show a friendly
    message (the file is often open in Excel)."""
    tools_df = pd.read_excel(TOOLS_PATH, sheet_name=0)
    tools_df.columns = [str(c).strip() for c in tools_df.columns]
    # "Superseded by" was this column's name before it was generalized -- migrate anything
    # already written under it rather than silently dropping it.
    if "Why deprecated" not in tools_df.columns and "Superseded by" in tools_df.columns:
        tools_df["Why deprecated"] = tools_df["Superseded by"]
    for col in TOOLS_COLS:
        if col not in tools_df.columns:
            tools_df[col] = ""
    tools_df = tools_df[TOOLS_COLS]
    tools_df = tools_df[tools_df["Name"].astype(str).str.strip().replace({"nan": "", "None": ""}) != ""]
    return tools_df.reset_index(drop=True)


def save_tools(edited_df):
    """Overwrite tools.xlsx (single sheet) with the edited inventory, restricted to the
    real columns; rows without a Name are dropped."""
    out = edited_df[[c for c in TOOLS_COLS if c in edited_df.columns]].copy()
    out = out[out["Name"].astype(str).str.strip().replace({"nan": "", "None": ""}) != ""]
    out.to_excel(TOOLS_PATH, sheet_name="Tools", index=False)


def parse_tool_steps(text):
    """A tool's "Steps" cell -> a list of [Step, How, AI involved?] rows for display, padding
    short rows and ignoring blank lines. See TOOL_STEPS_COLUMNS for the delimiter rules."""
    text = "" if text is None else str(text).strip()
    if not text or text.lower() == "nan":
        return []
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        delim = "\t" if "\t" in line else "|"
        cells = [c.strip() for c in line.split(delim)]
        cells = (cells + ["", "", ""])[:3]
        rows.append(cells)
    return rows


# --- Beyond-projects cards (per period, dashboard-only state like the task checklists) ----
BEYOND_PATH = DATA_DIR / "beyond_projects.json"

# Generic placeholder, only used the first time the file doesn't exist yet; after that,
# whatever's on disk (and however it's been edited) is authoritative. Matches the shape
# generate_demo_data.py writes, keyed by the calendar-year period label this demo uses.
_BEYOND_SEED = {
    "2025": [
        {"title": "Guest lecture · Summer School", "value": "~16 h in total", "color": "#0B3C49",
         "description": "16 h bioinformatics module for visiting students."},
        {"title": "Pipeline outreach", "value": "2", "color": "#2A9D8F",
         "description": "Pipeline showcased at 2 seminars · opened 1 new project."},
        {"title": "Internal tools", "value": "2", "color": "#E76F51",
         "description": "Two small internal helper scripts (personal use)."},
    ],
}


def load_beyond_projects():
    if not BEYOND_PATH.exists():
        save_beyond_projects(dict(_BEYOND_SEED))
        return dict(_BEYOND_SEED)
    try:
        return json.loads(BEYOND_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def export_beyond_to_excel(all_cards):
    """Mirror the beyond-projects cards (held in BEYOND_PATH as the source of truth) into
    BEYOND_XLSX_PATH -- one row per card, every reporting period in a single sheet -- so
    this content lives somewhere Excel-readable too, like the task checklists do."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Beyond projects"
    ws.append(["Period", "Title", "Headline value", "Description", "Accent color"])
    for period_label, cards in all_cards.items():
        for card in cards:
            ws.append([period_label, card.get("title", ""), card.get("value", ""),
                       card.get("description", ""), card.get("color", "")])
    for col, width in zip("ABCDE", (18, 28, 18, 60, 14)):
        ws.column_dimensions[col].width = width
    wb.save(BEYOND_XLSX_PATH)


def save_beyond_projects(all_cards):
    """Write the JSON source of truth, then mirror to Excel. Returns a warning string if
    the Excel mirror couldn't be written (file open in Excel / locked by OneDrive) -- the
    JSON save still succeeded, so edits are never lost to a lock."""
    BEYOND_PATH.write_text(json.dumps(all_cards, indent=2, ensure_ascii=False), encoding="utf-8")
    try:
        export_beyond_to_excel(all_cards)
    except PermissionError:
        return (f"Saved, but couldn't update {BEYOND_XLSX_PATH.name} (close it in Excel to "
                "refresh the mirror on the next edit).")
    return None


def new_beyond_card():
    return {"title": "", "value": "", "color": "#2A9D8F", "description": ""}


# --- Quick-add for the project tracker -----------------------------------------------------
# "Hours in Timesheet" holds live Excel formulas in the project sheet (confirmed by inspecting
# the sheet with openpyxl, data_only=False) -- a pandas-based rewrite of the whole sheet
# would flatten every row's formula to a frozen static number. These functions use openpyxl
# to touch only the one row being added or edited, leaving every other cell -- formulas
# included -- untouched.
PROJECT_SHEET_ROW_CAP = 20  # load_projects()'s own nrows=20 convention, to stay clear of
# the small unrelated lookup table that follows the real data further down the sheet.


def _row_is_empty(ws, row, n_cols):
    """A row counts as empty only if EVERY column in it is blank -- checking just one
    column (e.g. Project tag) is unsafe, since that column can be legitimately blank on a
    real row (a one-off meeting with no project tag, for instance) while other columns on
    that same row still hold real data."""
    return all(ws.cell(row=row, column=c).value in (None, "") for c in range(1, n_cols + 1))


def append_project_row(xlsx_path, sheet_name, values):
    """Append one new row to a project-tracker sheet. `values` is {column: value} for
    hand-typed columns only; any column not included (e.g. a formula column) is left
    blank. Raises ValueError if the sheet is already at PROJECT_SHEET_ROW_CAP, rather than
    risk inserting into the lookup table that follows."""
    wb = openpyxl.load_workbook(xlsx_path)
    ws = wb[sheet_name]
    headers = [cell.value for cell in ws[1]]
    n_cols = len(headers)

    target_row = next(
        (row for row in range(2, 2 + PROJECT_SHEET_ROW_CAP) if _row_is_empty(ws, row, n_cols)), None,
    )
    if target_row is None:
        raise ValueError(
            f"This sheet already has {PROJECT_SHEET_ROW_CAP} projects (the conventional cap, "
            "to avoid overwriting the lookup table further down the sheet) -- add this one "
            "directly in Excel instead."
        )

    for col_name, value in values.items():
        if col_name in headers and value not in (None, ""):
            ws.cell(row=target_row, column=headers.index(col_name) + 1, value=value)
    wb.save(xlsx_path)


# Only "Hours in Timesheet" is genuinely formula-driven. "Number of Meetings" was long treated
# as one too, but inspecting every KPI*.xlsx sheet (openpyxl, data_only=False) shows it
# holds hand-typed numbers -- at most a typed sum like "=2+1", which is shorthand, not a live
# link. It feeds the complexity bubble chart's y-axis, so it is editable (see
# update_project_row's caller, which only writes it when the value actually changed).
PROJECT_FORMULA_COLS = {"Hours in Timesheet"}


def project_field_options(periods, col):
    """Distinct historical values for `col` across every period's project sheet, to
    populate a dropdown (with a free-text field alongside it for a genuinely new value)."""
    values = set()
    for p in periods:
        proj = load_projects(p["file"], p["sheet"])
        if col in proj.columns:
            values |= set(proj[col].dropna().astype(str).str.strip())
    # "nan"/"None" survive dropna() as literal strings when a blank round-trips through
    # pandas, and would otherwise show up as a pickable option (same guard as
    # meeting_field_options).
    return sorted(v for v in values if v and v.lower() not in ("nan", "none"))


def meeting_field_options(periods, col):
    """Distinct historical values for `col` across every period's MEETINGS sheet -- the
    consultation-meeting counterpart of project_field_options, so a field like "Meeting
    Outputs" can offer what's already been used (including from older periods) instead of
    being typed from scratch every time."""
    values = set()
    for p in periods:
        meetings = load_meetings(p["file"], p["meetings_sheet"])
        if col in meetings.columns:
            values |= set(meetings[col].dropna().astype(str).str.strip())
    return sorted(v for v in values if v and v.lower() != "nan")


def update_project_row(xlsx_path, sheet_name, project_tag, values):
    """Update specific hand-maintained columns of an EXISTING project row (found by its
    Project tag) in place. Refuses to touch Hours in Timesheet -- that one is a live Excel
    formula (see append_project_row) -- or a tag that isn't found."""
    bad = set(values) & PROJECT_FORMULA_COLS
    if bad:
        raise ValueError(f"Refusing to overwrite live formula column(s): {', '.join(sorted(bad))}.")

    wb = openpyxl.load_workbook(xlsx_path)
    ws = wb[sheet_name]
    headers = [cell.value for cell in ws[1]]
    tag_col = headers.index("Project tag") + 1

    target_row = next(
        (row for row in range(2, 2 + PROJECT_SHEET_ROW_CAP)
         if str(ws.cell(row=row, column=tag_col).value or "").strip() == project_tag.strip()),
        None,
    )
    if target_row is None:
        raise ValueError(f'Project tag "{project_tag}" not found in {sheet_name}.')

    for col_name, value in values.items():
        if col_name in headers:
            ws.cell(row=target_row, column=headers.index(col_name) + 1, value=value)
    wb.save(xlsx_path)


AUTO_HOURS_COL = "Hours (auto)"


def sync_auto_hours_column(xlsx_path, sheet_name, projects, df_period=None):
    """Write the same time-log-preferring hours used throughout the dashboard (see
    project_hours_with_source) into a dedicated 'Hours (auto)' column -- added at the end
    of the sheet if it doesn't exist yet. Deliberately a SEPARATE column rather than
    overwriting 'Hours in Timesheet': that one may hold a real (if currently just a simple
    typed formula) Timesheet-linked value, and overwriting it would destroy that permanently
    with no way back. This only ever touches the 'Hours (auto)' column -- nothing else on
    the sheet, formulas included, is affected. Explicit/on-demand (a button click), not run
    automatically on every page load, so the file is never written to just from viewing."""
    hours_by_tag, _source = project_hours_with_source(projects, df_period)

    wb = openpyxl.load_workbook(xlsx_path)
    ws = wb[sheet_name]
    headers = [cell.value for cell in ws[1]]

    if AUTO_HOURS_COL in headers:
        col_idx = headers.index(AUTO_HOURS_COL) + 1
    else:
        col_idx = len(headers) + 1
        ws.cell(row=1, column=col_idx, value=AUTO_HOURS_COL)

    tag_col = headers.index("Project tag") + 1
    for row in range(2, 2 + PROJECT_SHEET_ROW_CAP):
        tag = str(ws.cell(row=row, column=tag_col).value or "").strip()
        if not tag:
            continue
        if tag in hours_by_tag:
            ws.cell(row=row, column=col_idx, value=round(hours_by_tag[tag], 2))
    wb.save(xlsx_path)


def append_meeting_row(xlsx_path, sheet_name, values):
    """Append one new row to a meetings sheet (no formula columns there, so this just
    finds the first fully-empty row and writes into it)."""
    wb = openpyxl.load_workbook(xlsx_path)
    ws = wb[sheet_name]
    headers = [cell.value for cell in ws[1]]
    n_cols = len(headers)

    target_row = 2
    while not _row_is_empty(ws, target_row, n_cols):
        target_row += 1
    for col_name, value in values.items():
        if col_name in headers and value not in (None, ""):
            ws.cell(row=target_row, column=headers.index(col_name) + 1, value=value)
    wb.save(xlsx_path)


def effective_received_date(projects):
    """The date a project counts as 'received' for the monthly received/workload view.
    Normally that's Register Project -- but an "Inherited Project" was already
    registered (by whoever had it before the current owner) long before it reached them, so using that
    date would attribute it to a month before their involvement even started. For
    Project Trigger == "Inherited Project", use Begining (when they actually started the
    work) instead. General and automatic by trigger type, not a per-project list -- any
    future inherited project is handled the same way with no override needed."""
    received = projects["Register Project"].copy()
    if "Project Trigger" in projects.columns and "Begining" in projects.columns:
        is_inherited = projects["Project Trigger"] == "Inherited Project"
        received = received.where(~is_inherited, projects["Begining"])
    return received


def effective_workload_start(projects):
    """When a project starts counting as open/active (the Year tab's workload line and the
    Month tab's active-projects list): First User Meeting/Shared Data, falling back to
    Begining, then Register Project. Inherited Projects are the exception: their
    first-meeting and registration dates belong to whoever had the project before, so --
    same principle as effective_received_date -- they only start counting at Begining
    (when Begining is filled in; otherwise the normal chain still applies)."""
    start = projects["First User Meeting/Shared Data"].copy()
    if "Begining" in projects.columns:
        start = start.fillna(projects["Begining"])
    start = start.fillna(projects["Register Project"])
    if "Project Trigger" in projects.columns and "Begining" in projects.columns:
        inherited = (projects["Project Trigger"] == "Inherited Project") & projects["Begining"].notna()
        start = start.where(~inherited, projects["Begining"])
    return start


def effective_closing_date(projects):
    """The date a project counts as administratively closed, for the turnaround/Timesheet-
    tracking math: normally Closing Day, but if Final Report Sent was logged *after* it
    (the report trailed the recorded close -- e.g. hours kept being logged under the
    project after Closing Day was set), use Final Report Sent instead so the tracked span
    isn't understated by a Closing Day that didn't actually mark the end of the work.
    Doesn't change whether a project counts as concluded (that's still Closing Day's mere
    presence, everywhere else) -- only which date the duration is measured to."""
    closing = projects["Closing Day"].copy()
    if "Final Report Sent" in projects.columns:
        report = projects["Final Report Sent"]
        later_report = closing.notna() & report.notna() & (report > closing)
        closing = closing.where(~later_report, report)
    return closing


def project_hours_with_source(projects, df_period=None):
    """Per-project hours, as {project_tag: hours} and {project_tag: source}, source being
    'time log' or 'Timesheet'. Prefers the personal time log (`df_period`, already filtered to
    the relevant reporting period) for any project it covers -- this updates live as hours
    get logged -- and falls back to the project tracker's own 'Hours in Timesheet' column
    (clipped at 0: a just-registered project can show a stale negative/blank value before
    Timesheet settles) for a project the time log doesn't cover, e.g. one from a period that
    predates the time log entirely. Shared by the 'Hours by project' chart and the 'year at
    a glance' cards so both report the same total."""
    timesheet_hours = pd.to_numeric(projects.get("Hours in Timesheet"), errors="coerce").fillna(0).clip(lower=0)
    timesheet_hours.index = projects["Project tag"]

    timelog_hours = pd.Series(dtype=float)
    if df_period is not None and len(df_period):
        timelog_hours = (
            df_period[~df_period["Project"].isin(["Org & Admin", "Trainning", "Seminário"])]
            .groupby("Project")["Hours (exact)"].sum()
        )

    hours, source = {}, {}
    for tag in sorted(set(timesheet_hours.index) | set(timelog_hours.index)):
        tl = timelog_hours.get(tag, 0.0)
        if tl > 0:
            hours[tag], source[tag] = tl, "time log"
        else:
            hours[tag], source[tag] = timesheet_hours.get(tag, 0.0), "Timesheet"
    return hours, source


ATTENTION_QUIET_DAYS = 21       # ~3 weeks with no logged hours before a project counts as quiet
ATTENTION_CLOSE_GRACE_DAYS = 7  # grace after a report goes out before chasing its Closing Day


def project_attention(projects, df_period=None, quiet_days=ATTENTION_QUIET_DAYS, today=None):
    """Open projects that look like they need a nudge, newest problem first.

    Three things get flagged, all derived from data already tracked -- no new columns:
      * "not started"  -- work was due to begin but no hours have ever been logged
      * "quiet"        -- hours were logged once, but not in the last `quiet_days`
      * "to close"     -- the final report went out but Closing Day is still blank

    A project with a Closing Day is finished and never appears. Projects whose Begining is
    still in the future are ignored (they aren't late, they haven't started). Returns a
    DataFrame with Project tag, kind, detail, last_activity and days (the staleness used
    for sorting); empty when everything is moving."""
    today = today if today is not None else pd.Timestamp.now().normalize()

    last_activity = {}
    if df_period is not None and len(df_period) and "_week_end" in df_period.columns:
        last_activity = df_period.groupby("Project")["_week_end"].max().to_dict()

    rows = []
    for _, p in projects.iterrows():
        tag = str(p.get("Project tag") or "").strip()
        if not tag:
            continue
        report, closing, begun = p.get("Final Report Sent"), p.get("Closing Day"), p.get("Begining")

        if pd.notna(closing):
            continue  # concluded

        if pd.notna(report):
            days = (today - report).days
            if days >= ATTENTION_CLOSE_GRACE_DAYS:
                rows.append({"Project tag": tag, "kind": "to close",
                             "detail": f"Report sent {format_days(days)} ago — Closing Day still blank",
                             "last_activity": report, "days": days})
            continue

        if pd.notna(begun) and begun > today:
            continue  # scheduled to start later, not late

        last = last_activity.get(tag)
        if last is None or pd.isna(last):
            if pd.isna(begun):
                continue
            days = (today - begun).days
            if days >= quiet_days:
                rows.append({"Project tag": tag, "kind": "not started",
                             "detail": f"Began {format_days(days)} ago, no hours ever logged",
                             "last_activity": pd.NaT, "days": days})
        else:
            days = (today - last).days
            if days >= quiet_days:
                rows.append({"Project tag": tag, "kind": "quiet",
                             "detail": f"No hours logged for {format_days(days)}",
                             "last_activity": last, "days": days})

    attention = pd.DataFrame(rows, columns=["Project tag", "kind", "detail", "last_activity", "days"])
    return attention.sort_values("days", ascending=False).reset_index(drop=True) if len(attention) else attention


LEAD_TIME_MAX_DAYS = 730  # a stage longer than ~2 years is a data-entry error, not a lead time
PAUSE_MIN_WEEKS = 1  # a single empty week between two active ones already reads as stopped


def project_activity(df_period):
    """Per-project weekly activity from the personal time log: when work really started and
    stopped, regardless of what the tracker's Timesheet-fed 'Begining' says.

    Returns {project: {"first": ts, "last_end": ts, "n_active": int, "gaps": [...]}} where
    `first` is the start of the first week with logged hours, `last_end` the end of the last
    one, `n_active` the number of distinct weeks with hours, and `gaps` the pauses — runs of
    >= PAUSE_MIN_WEEKS consecutive empty weeks strictly between two active weeks, each as
    {"start": ts, "end": ts, "weeks": int} (end = last day of the empty run)."""
    activity = {}
    if df_period is None or not len(df_period):
        return activity
    for project, weeks in df_period.groupby("Project")["_week_sort"].unique().items():
        weeks = sorted(pd.Timestamp(w) for w in weeks)
        gaps = []
        for prev, nxt in zip(weeks, weeks[1:]):
            missing = int((nxt - prev).days // 7) - 1
            if missing >= PAUSE_MIN_WEEKS:
                gaps.append({"start": prev + pd.Timedelta(days=7),
                             "end": nxt - pd.Timedelta(days=1), "weeks": missing})
        activity[str(project)] = {
            "first": weeks[0], "last_end": weeks[-1] + pd.Timedelta(days=6),
            "n_active": len(weeks), "gaps": gaps,
        }
    return activity


def lead_time_table(projects, df_period=None, period_end=None, pause_notes=None):
    """Per-project turnaround, computed from the tracker's own date columns rather than its
    'Lead Time: Request to Project Start' column (which is a Notion text field, usually
    blank, and holds a date rather than a duration).

    Two stages per project, both from the tracker's dates (the formal record):
      waiting  = first contact -> Begining   (request sitting before work starts)
      working  = Begining -> Final Report Sent (or -> today while still running)
    These (`working_days`, `total_days`, `done`, `work_end`) are the real-work metric the
    medians below are built on, and don't change based on Closing Day.

    `admin_done` / `bar_end` are the administrative counterpart, used only by the chart to
    draw the bar itself as Begining -> Closing Day (or -> today while not yet closed) --
    the formal Timesheet record, kept deliberately separate from the real-work math above.

    `period_end` caps that "today" at the end of the reporting period being reviewed, so a
    closed period doesn't sprout bars into the months after it -- for a period still running
    today comes first and nothing changes.

    'First contact' is First User Meeting/Shared Data, falling back to Register Project.

    Two kinds of row are treated specially, both by Project Trigger rather than by a
    per-project list, so future rows are handled with no override needed:
      Consulting -- dropped entirely. A consulting block (CONSULT_x_y_z) is a standing
                    advisory thread, not a project with a start and a report to deliver,
                    so it has no turnaround to measure. (The workload line in kpi_charts
                    leaves Consulting out for the same reason.)
      Internal   -- kept, and marked `internal` so the chart can draw it muted, but left
                    out of every median by lead_time_summary: internal work has no external
                    user waiting on it, so its days aren't service turnaround.
                    There is also nobody to send a report to, so 'Final Report Sent' stays
                    blank by nature -- its Closing Day ends the working stage instead, and
                    lands in `report`. Without that it would read as still running today,
                    months after it actually wrapped up.

    When `df_period` is given, each row also carries what the personal time log says —
    not replacing the tracker's dates, but annotating them:
      real_start   = start of the first week with logged hours: when work *really* began,
                     which can sit before or after the tracker's Timesheet-fed 'Begining'.
                     NaT when the project has no logged hours — or when it was already
                     active in the log's first-ever week with an earlier 'Begining'
                     (`pre_log` True then: the real start predates the log, so the log
                     can't see it).
      weeks_active = distinct weeks with hours; gaps / weeks_paused = pauses of
                     >= PAUSE_MIN_WEEKS consecutive empty weeks (see project_activity), plus
                     a trailing gap from the last logged week to work_end when that's also
                     >= PAUSE_MIN_WEEKS -- project_activity alone only catches a
                     stop-and-RESTART; a project touched once and never again needs this to
                     show up as paused at all.

    `pause_notes` (from load_pause_notes: {project: {gap-key: {"note", "forgive_working",
    "forgive_total"}}}) lets any individual pause be excused from either median
    independently, without excusing the whole project: "forgive_working" subtracts its days
    from `working_days_counted` alone (Typical time to deliver / effective working time),
    "forgive_total" subtracts them from the working-portion of `total_days_counted` alone
    (Typical total turnaround to user) -- a pause can be forgiven from one, the other,
    both, or neither. `working_days_counted` and `total_days_counted` are what
    lead_time_summary and turnaround_by_size use instead of
    the raw `working_days` / `total_days` (kept as-is for the chart and the per-project
    table, since the time off still really happened).

    Rows whose dates are impossible (out of order, or a stage longer than
    LEAD_TIME_MAX_DAYS -- almost always a mistyped year) are kept but marked in `flag`, so
    callers can report them to the user instead of letting them poison the medians."""
    today = pd.Timestamp.now().normalize()
    activity = project_activity(df_period)
    pause_notes = pause_notes or {}
    has_desc = "Short Description" in projects.columns
    hours_by_tag, _hours_source = project_hours_with_source(projects, df_period)
    effective_closing = effective_closing_date(projects)
    # The log's very first week ever: a project already active then may well have started
    # earlier, before time tracking existed -- the log simply can't see it.
    log_start = (df_period["_week_sort"].min()
                 if df_period is not None and len(df_period) else None)
    rows = []
    for idx, p in projects.iterrows():
        tag = str(p.get("Project tag") or "").strip()
        if not tag:
            continue
        trigger = str(p.get("Project Trigger") or "").strip()
        if trigger == "Consulting":
            continue
        first = p.get("First User Meeting/Shared Data")
        if pd.isna(first):
            first = p.get("Register Project")
        start, report = p.get("Begining"), p.get("Final Report Sent")
        if trigger == "Internal" and pd.isna(report):
            report = p.get("Closing Day")
        if pd.isna(first) or pd.isna(start):
            continue

        act = activity.get(tag)
        real_start, pre_log = pd.NaT, False
        if act:
            if act["first"] == log_start and start < log_start:
                # No log evidence reaches back far enough to say when work really began --
                # fall back to the tracker's own Begining (the best date actually on
                # record) rather than leaving the chart's diamond blank. `pre_log` still
                # flags this for the table ("before the log"): it's a known date, not a
                # measured one.
                pre_log = True
                real_start = start
            else:
                real_start = act["first"]

        done = pd.notna(report)
        open_until = today if period_end is None else min(today, pd.Timestamp(period_end))
        work_end = report if done else max(start, open_until)
        waiting = (start - first).days
        working = (work_end - start).days

        # The chart draws the bar itself as the *formal* record (Begining -> Closing Day,
        # both Timesheet-fed), separately from the day-count math above (which stays on
        # Final Report Sent, the real metric the medians are built on). admin_done mirrors
        # `done` but keyed to Closing Day instead of the report, for that bar's own color.
        closing_raw = p.get("Closing Day")
        admin_done = pd.notna(closing_raw)
        bar_end = closing_raw if admin_done else max(start, open_until)

        flag = ""
        if waiting < 0:
            flag = "work started before first contact"
        elif done and working < 0:
            flag = "report sent before work started"
        elif max(abs(waiting), abs(working)) > LEAD_TIME_MAX_DAYS:
            flag = "a stage spans over 2 years — check for a mistyped year"

        # project_activity's gaps only catch a stop-and-RESTART (a hole strictly between
        # two active weeks) -- a project touched once and never again has no second active
        # week to bound a gap against, so it would otherwise show zero pauses no matter how
        # long it's been quiet. This trailing gap covers exactly that: silence from the
        # last logged week up to work_end (today/period end if still running, the report
        # date if delivered), the same way a mid-project hole would.
        gaps = [dict(g) for g in act["gaps"]] if act else []
        if act:
            trailing_weeks = int((work_end - act["last_end"]).days // 7)
            if trailing_weeks >= PAUSE_MIN_WEEKS:
                gaps.append({"start": act["last_end"] + pd.Timedelta(days=1),
                             "end": work_end, "weeks": trailing_weeks})

        tag_notes = pause_notes.get(tag, {})
        for g in gaps:
            note = tag_notes.get(pause_key(g), {})
            g["forgiven_working"] = bool(note.get("forgive_working"))
            g["forgiven_total"] = bool(note.get("forgive_total"))
            g["forgiven"] = g["forgiven_working"] or g["forgiven_total"]  # any forgiveness, for the chart
        forgiven_days_working = sum(g["weeks"] * 7 for g in gaps if g["forgiven_working"])
        forgiven_days_total = sum(g["weeks"] * 7 for g in gaps if g["forgiven_total"])
        working_counted = max(0, working - forgiven_days_working)
        working_counted_for_total = max(0, working - forgiven_days_total)

        rows.append({
            "Project tag": tag, "first_contact": first, "start": start,
            "work_end": work_end, "report": report if done else pd.NaT,
            "waiting_days": waiting, "working_days": working,
            "total_days": waiting + working, "done": done, "flag": flag,
            # working_days_counted feeds "Typical time to deliver (effective working time)";
            # total_days_counted feeds "Typical total turnaround to user" -- independently,
            # since a pause can be forgiven from one, the other, both, or neither.
            "working_days_counted": working_counted,
            "total_days_counted": waiting + working_counted_for_total,
            "real_start": real_start, "pre_log": pre_log,
            "admin_done": admin_done, "bar_end": bar_end,
            # Register -> Closing Day is the span Timesheet tracks, which is neither of the
            # two stages above: it starts at registration (after first contact) and runs past
            # the report to the administrative close. `closing` is the effective closing date
            # (see effective_closing_date), used for that span's math; `closing_raw` is the
            # tracker's actual Closing Day, kept separately so the chart can draw the
            # formal/Timesheet bar (Begining -> Closing Day) on its own, apart from the
            # real-dates math above.
            "register": p.get("Register Project"), "closing": effective_closing.get(idx),
            "closing_raw": closing_raw,
            "hours": float(hours_by_tag.get(tag, 0.0)),
            "description": (p.get("Short Description") if has_desc else None),
            "inherited": trigger == "Inherited Project",
            "internal": trigger == "Internal",
            "weeks_active": act["n_active"] if act else None,
            "weeks_paused": sum(g["weeks"] for g in gaps if not g["forgiven"]), "gaps": gaps,
        })
    return pd.DataFrame(rows)


# --- Pause notes: why a project stopped ("waiting for user", ...), and whether to forgive
# that pause -- excuse its days from the turnaround medians without excusing the rest of
# the project. Forgiveness is tracked separately for the two medians it can feed --
# "forgive_working" excuses it from Typical time to deliver (effective working time) only,
# "forgive_total" excuses it from Typical total turnaround to user only -- since a pause
# that shouldn't count as real work might still be time the user was genuinely waiting
# through (and so should stay in), or vice versa. A pause can be explained without being
# forgiven from either (a note for context, but the time still counts both places), or
# forgiven from one, the other, or both, with or without a note.
PAUSE_NOTES_PATH = DATA_DIR / "project_pause_notes.json"


def pause_key(gap):
    """Stable id for one detected pause: the ISO date of its first empty week. The same gap
    keeps the same key across reruns as long as the surrounding logged weeks don't change."""
    return gap["start"].date().isoformat()


def load_pause_notes():
    """{project: {gap-start ISO date: {"note": str, "forgive_working": bool,
    "forgive_total": bool}}}. Also reads the two older formats so nothing written under
    them is lost: the plain-string format from before "forgive" existed (note only), and
    the single-"forgive" format from before it split in two (that one value, applied to
    both -- the combination that reproduced the old behavior exactly)."""
    if not PAUSE_NOTES_PATH.exists():
        return {}
    try:
        data = json.loads(PAUSE_NOTES_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}

    def normalize(entry):
        if isinstance(entry, str):
            return {"note": entry, "forgive_working": False, "forgive_total": False}
        if "forgive_working" in entry or "forgive_total" in entry:
            return {"note": str(entry.get("note", "")),
                    "forgive_working": bool(entry.get("forgive_working")),
                    "forgive_total": bool(entry.get("forgive_total"))}
        old = bool(entry.get("forgive"))
        return {"note": str(entry.get("note", "")), "forgive_working": old, "forgive_total": old}

    return {str(proj): {str(k): normalize(v) for k, v in (notes or {}).items()}
            for proj, notes in data.items()}


def save_pause_notes(notes):
    """Persist pause notes, dropping an entry once it has neither a note nor either
    "forgive" ticked (nothing left to keep). Callers should guard with PermissionError like
    every other save."""
    cleaned = {}
    for proj, gap_notes in notes.items():
        kept = {}
        for key, entry in gap_notes.items():
            note = (entry.get("note") or "").strip()
            forgive_working = bool(entry.get("forgive_working"))
            forgive_total = bool(entry.get("forgive_total"))
            if note or forgive_working or forgive_total:
                kept[key] = {"note": note, "forgive_working": forgive_working,
                             "forgive_total": forgive_total}
        if kept:
            cleaned[proj] = kept
    PAUSE_NOTES_PATH.write_text(json.dumps(cleaned, indent=2, ensure_ascii=False),
                                encoding="utf-8")


def lead_time_summary(lead_df):
    """Median turnaround figures from `lead_time_table`, ignoring flagged (bad-date) rows
    and internal projects (no external user waits on those, so they aren't turnaround --
    the chart still draws them, muted). The working/total medians use
    `working_days_counted` / `total_days_counted`, not the raw day counts, so a pause
    ticked "forgive_working" / "forgive_total" (see load_pause_notes) doesn't inflate the
    one(s) it was ticked for. Each value is None when nothing qualifies, so callers can
    show an em dash."""
    clean = lead_df[lead_df["flag"] == ""] if len(lead_df) else lead_df
    if len(clean) and "internal" in clean.columns:
        clean = clean[~clean["internal"].fillna(False).astype(bool)]

    def med(series):
        return None if not len(series) else float(series.median())

    delivered = clean[clean["done"]] if len(clean) else clean

    # Internal projects sit out of the three medians but are still drawn and still real
    # work, so they belong in the "projects measured" headcount -- `n_shown` is every row
    # on the chart, `n_clean` only the ones the medians are computed from.
    shown = lead_df[lead_df["flag"] == ""] if len(lead_df) else lead_df
    shown_delivered = shown[shown["done"]] if len(shown) else shown
    forgiven_days = (int(sum(g["weeks"] * 7 for gaps in lead_df["gaps"] for g in (gaps or []) if g.get("forgiven")))
                      if len(lead_df) and "gaps" in lead_df.columns else 0)
    return {
        "median_waiting": med(clean["waiting_days"]) if len(clean) else None,
        "median_working": med(delivered["working_days_counted"]) if len(delivered) else None,
        "median_total": med(delivered["total_days_counted"]) if len(delivered) else None,
        "n_clean": int(len(clean)), "n_delivered": int(len(delivered)),
        "n_flagged": int((lead_df["flag"] != "").sum()) if len(lead_df) else 0,
        "n_internal": (int(lead_df["internal"].fillna(False).astype(bool).sum())
                       if len(lead_df) and "internal" in lead_df.columns else 0),
        "forgiven_days": forgiven_days,
        "n_shown": int(len(shown)), "n_shown_delivered": int(len(shown_delivered)),
    }


def lead_time_coverage(projects, lead_df, stats):
    """Reconciles the period's project count to the number actually behind the turnaround
    medians. Every project the section sets aside is counted under a reason, so the four
    tiles can never look like projects quietly went missing: the reasons plus `measured`
    always add back up to `total`.

    `undated` catches anything lead_time_table skipped for want of a first-contact or
    Begining date -- a just-registered project, usually."""
    tags = projects["Project tag"].astype(str).str.strip() if len(projects) else pd.Series(dtype=str)
    tagged = projects[tags.ne("") & tags.ne("nan")] if len(projects) else projects
    total, charted = len(tagged), len(lead_df)

    trigger = (tagged["Project Trigger"].astype(str).str.strip()
               if "Project Trigger" in tagged.columns else pd.Series("", index=tagged.index))
    consulting = int((trigger == "Consulting").sum())
    return {
        "total": total,
        "charted": charted,
        "consulting": consulting,
        "undated": max(0, total - charted - consulting),
        "internal": stats["n_internal"],
        "forgiven_days": stats["forgiven_days"],
        "flagged": stats["n_flagged"],
        "measured": stats["n_shown"],
    }


def lead_time_coverage_note(cov):
    """`lead_time_coverage` as one sentence, listing only the reasons that actually apply."""
    reasons = [
        (cov["consulting"], "consulting"),
        (cov["undated"], "not started yet (no dates to measure)"),
        (cov["flagged"], "set aside — the dates look wrong"),
    ]
    listed = [f"**{n}** {why}" for n, why in reasons if n]
    tail = (" · ".join(listed) + "." if listed else "all of them.")
    note = (f"**{cov['total']}** projects this period — **{cov['measured']}** on the chart, "
            + tail)
    if cov["internal"]:
        is_plural = cov["internal"] != 1
        noun = "projects" if is_plural else "project"
        verb = "are" if is_plural else "is"
        stay = "stay" if is_plural else "stays"
        note += (f" The **{cov['internal']}** internal {noun} {verb} counted above and "
                 f"drawn, but {stay} out of the three medians.")
    if cov["forgiven_days"]:
        note += (f" **{format_days(cov['forgiven_days'])}** of paused time, forgiven by "
                 "hand, is also left out.")
    return note


def lead_time_effort(lead_df):
    """The effort counterpart to `lead_time_summary`: same projects, but asking how much work
    went in rather than how much calendar passed. Same basis as the medians there -- usable
    dates, internal projects left out -- so the two rows describe one population.

      median_timesheet    -- Register Project -> Closing Day, the span Timesheet tracks. Longer
                          than the delivery medians by design: it runs past the report to
                          the administrative close. `closing` here is already the effective
                          closing date (see effective_closing_date): if Final Report Sent
                          trailed Closing Day, the report date is used instead, so a report
                          logged after the tracker's close doesn't understate the span.

    Values are None when nothing qualifies, so callers can show an em dash."""
    clean = lead_df[lead_df["flag"] == ""] if len(lead_df) else lead_df
    if len(clean) and "internal" in clean.columns:
        clean = clean[~clean["internal"].fillna(False).astype(bool)]
    if not len(clean):
        return {"median_timesheet": None, "n_timesheet": 0}

    def med(series):
        series = pd.to_numeric(series, errors="coerce").dropna()
        return float(series.median()) if len(series) else None

    timesheet = clean[clean["register"].notna() & clean["closing"].notna()]
    timesheet_days = (timesheet["closing"] - timesheet["register"]).dt.days if len(timesheet) else pd.Series(dtype=float)

    return {"median_timesheet": med(timesheet_days), "n_timesheet": int(len(timesheet))}


# Hours that split a project into small / medium / large. Fixed round numbers rather than
# this period's own terciles, so a band means the same thing from one year to the next.
SIZE_BANDS = ((None, 10, "Small"), (10, 30, "Medium"), (30, None, "Large"))


def turnaround_by_size(lead_df):
    """Median total turnaround per project-size band -- the size-adjusted view done by
    comparing like with like rather than by dividing days by hours.

    A big project taking longer isn't news, so a single median across every size tells you
    little; three medians say what to expect for the job in front of you, and make a small
    project that took a large project's time obvious. Same basis as the other medians:
    delivered projects with usable dates, internal ones left out, and only those with hours
    on record (a project with no hours can't be placed in a band).

    Returns one dict per band: label, range_label, median_days (None when empty), n."""
    clean = lead_df[lead_df["flag"] == ""] if len(lead_df) else lead_df
    if len(clean) and "internal" in clean.columns:
        clean = clean[~clean["internal"].fillna(False).astype(bool)]
    if len(clean):
        clean = clean[clean["done"] & (clean["hours"].fillna(0) > 0)]

    bands = []
    for low, high, label in SIZE_BANDS:
        if not len(clean):
            sub = clean
        else:
            keep = pd.Series(True, index=clean.index)
            if low is not None:
                keep &= clean["hours"] >= low
            if high is not None:
                keep &= clean["hours"] < high
            sub = clean[keep]
        if low is None:
            range_label = f"under {high} h"
        elif high is None:
            range_label = f"over {low} h"
        else:
            range_label = f"{low}\u2013{high} h"
        bands.append({
            "label": label, "range_label": range_label, "n": int(len(sub)),
            "median_days": float(sub["total_days_counted"].median()) if len(sub) else None,
        })
    return bands





def format_days(days):
    """42 -> '42 days'; 1 -> '1 day'; None -> '—'."""
    if days is None:
        return "—"
    d = int(round(days))
    return f"{d} day" + ("" if d == 1 else "s")


def closing_gap_summary(projects):
    """How much bureaucratic closing (Closing Day) lags behind the actual final deliverable
    (Final Report Sent), for the "Projects received vs finished" chart -- "finished" there
    is Closing Day alone, which can make a project look freshly wrapped up on a month it
    was really just paperwork catching up to work delivered earlier (or, for an Internal
    project with no report to send at all, Closing Day IS the delivery).
    n_finished: everything with a Closing Day this data covers.
    n_same_day / n_delayed: of those that also have a Final Report Sent, how many closed
    the same day (or before) vs strictly later.
    median_gap_days: median lag, in days, across the delayed ones only (None if none)."""
    if "Closing Day" not in projects.columns:
        return {"n_finished": 0, "n_same_day": 0, "n_delayed": 0, "median_gap_days": None}
    n_finished = int(projects["Closing Day"].notna().sum())
    if "Final Report Sent" not in projects.columns:
        return {"n_finished": n_finished, "n_same_day": 0, "n_delayed": 0, "median_gap_days": None}
    both = projects[projects["Closing Day"].notna() & projects["Final Report Sent"].notna()]
    if not len(both):
        return {"n_finished": n_finished, "n_same_day": 0, "n_delayed": 0, "median_gap_days": None}
    gap = (both["Closing Day"] - both["Final Report Sent"]).dt.days
    delayed = gap[gap > 0]
    return {
        "n_finished": n_finished,
        "n_same_day": int((gap <= 0).sum()),
        "n_delayed": int(len(delayed)),
        "median_gap_days": float(delayed.median()) if len(delayed) else None,
    }


def year_at_a_glance(projects, meetings, df_period=None):
    """The 4 headline numbers from the deck's 'year at a glance' slide, computed straight
    from the project tracker and meetings sheets (no manual corrections/overrides applied,
    unlike the one-off deck build -- this is meant to always reflect the live Excel)."""
    n_total = len(projects)
    n_concluded = int(projects["Closing Day"].notna().sum()) if "Closing Day" in projects.columns else 0
    n_active = n_total - n_concluded

    n_meetings = len(meetings)
    meeting_hours = pd.to_numeric(meetings.get("Time"), errors="coerce").fillna(1).sum() if len(meetings) else 0.0

    hours, _source = project_hours_with_source(projects, df_period)
    project_hours = sum(hours.values())
    total_hours = project_hours + meeting_hours

    project_groups = set(projects.get("Grupo", pd.Series(dtype=str)).dropna()) - {"ADA"}
    meeting_groups = set(meetings.get("Grupo", pd.Series(dtype=str)).dropna()) - {"ADA"}
    consultation_only = meeting_groups - project_groups
    n_groups = len(project_groups | meeting_groups)

    return {
        "projects_total": n_total, "projects_concluded": n_concluded, "projects_active": n_active,
        "meetings_total": n_meetings, "meeting_hours": meeting_hours,
        "total_hours": total_hours, "project_hours": project_hours,
        "groups_total": n_groups, "groups_with_projects": len(project_groups),
        "groups_consultation_only": len(consultation_only),
    }
