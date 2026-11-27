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
PUBLICATIONS_XLSX_PATH = DATA_DIR / "Publications.xlsx"

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

# Gains & Outputs page: a named maturity/status palette for the 3 ordered states (Potential ->
# In use -> Delivered) -- Delivered green, In use blue, Potential a muted neutral grey, a
# deliberate choice (yellow on Potential was tried first and rejected).
# Deliberately NOT TL_GOOD/TL_CRITICAL-style saturated traffic-light hues (TL_GOOD "#0ca30c"
# was rejected as unprofessional) -- these are the same muted, desaturated family as TL_PALETTE
# (OKLCH L/C checked against it) and TL_BASELINE (Potential's grey is a slightly darker step of
# that same neutral so it still clears 3:1 contrast as a bar fill, not just a gridline). The "/"
# hatch on Potential (see _POTENTIAL_HATCH in kpi_charts.py) stays -- with 3 distinct hues now
# instead of one ramp's light/dark steps, the hatch is what keeps Potential readable to a viewer
# who can't use hue at all, same as before. Both triples re-validated with the dataviz skill's
# validate_palette.js (OKLab CVD + normal-vision + contrast checks) against each other and
# against ADA_PERSONAL_COLOR/_DARK below; the dark triple's own L/C were picked independently
# of the light triple's (not just "the same hue, lighter") specifically so Delivered's green
# stays the most prominent against a dark surface.
GAIN_STATE_COLORS = {"Delivered": "#1a8f6b", "In use": "#1f5c99", "Potential": "#8c8a7a"}
GAIN_STATE_COLORS_DARK = {"Delivered": "#29ab82", "In use": "#4a84c9", "Potential": "#726e66"}

# Gains & Outputs page: one hue per GAIN_GROUPS theme, used ONLY to colour group labels/bands
# (the axis band, bracket and header strip that say "these rows/columns belong together") --
# never the data marks themselves, which must keep reading Delivered/In use/Potential via
# GAIN_STATE_COLORS[_DARK] above. Re-picked from scratch (all 4, not just Efficiency) when the
# state palette moved to green/blue/grey above: the old Efficiency "#1a8f6b" was the exact same
# hex as the new Delivered green, and the old Capability/Innovation/Reach hues (gold/purple/
# pink) turned out -- per validate_palette.js, not by eye -- to sit too close to the new
# Delivered/In use for CVD and even normal vision to tell apart.
#
# Checked ONLY against GAIN_STATE_COLORS[_DARK] (Delivered/In use/Potential) -- NOT against
# ADA_PERSONAL_COLOR[_DARK): ADA/Personal's orange only ever appears in fig_audience_outputs,
# group colours only ever appear in fig_gains_matrix/fig_audience_outputs, and those are
# three different figures -- no render ever puts the two palettes in the same picture, so
# constraining against ADA's orange too was over-constraining the search for no real payoff
# (an earlier pass did include it and it meaningfully shrank the usable hue space, forcing two
# groups into neighbouring violet/magenta shades that were too close to each other).
#
# All 4 are from clearly different families (sienna/burnt-red, violet, gold, rose/magenta),
# every pairwise combination clears validate_palette.js's normal-vision floor (>=15, several
# with 20-30+ to spare) in BOTH themes, and the group->colour assignment itself was chosen so
# the groups that actually sit NEXT TO each other on screen (GAIN_GROUP_ORDER's adjacent pairs:
# Efficiency-Capability, Capability-Innovation, Innovation-Reach) get the MOST distinct pairing
# available, while the single weakest pair in each theme's palette (still >=15, just the
# relative minimum) lands on a NON-adjacent pair instead -- Efficiency sienna sits next to
# Capability violet (light ΔE 22.9 / dark ΔE 25.4), not next to whichever colour happens to be
# its closest match that theme.
GAIN_GROUP_COLORS = {
    "Efficiency": "#e45268",
    "Capability": "#986feb",
    "Innovation & visibility": "#bb8a00",
    "Reach & relationships": "#982480",
}
GAIN_GROUP_COLORS_DARK = {
    "Efficiency": "#c73e1a",
    "Capability": "#6f44bc",
    "Innovation & visibility": "#b08700",
    "Reach & relationships": "#c44a9e",
}

# Gains & Outputs page: label shown to the user for the "In use" state -- the internal value
# (GAIN_STATE_COLORS keys, STATE_ORDER, developments["state"]/gain_summary comparisons) stays
# the plain "In use" string everywhere in the data/logic layer; only the RENDERED text changes,
# so nothing has to migrate and nothing is left half-comparing against an old string. "In use"
# alone reads as "finished and running," which hides exactly what this label makes explicit:
# the state also covers something still being actively built/iterated on. Kept short on purpose -- it still has to fit a legend entry and an axis tick label
# without wrapping or overflowing (checked by rendering, not just by eye).
GAIN_STATE_LABELS = {"Delivered": "Delivered", "In use": "In use & developing", "Potential": "Potential"}

# Gains & Outputs page: the "ADA / Personal" audience row (fig_audience_outputs) -- the
# inward-facing counterpart to Internal/External users, built from Output level rather than a
# boolean flag. TL_PALETTE[1]/_DARK[1], named rather than inlined so the one spot that needs an
# "audience" hue distinct from both the state ramp and the group colors above has a single
# source of truth.
ADA_PERSONAL_COLOR = TL_PALETTE[1]
ADA_PERSONAL_COLOR_DARK = TL_PALETTE_DARK[1]

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


# Every pd.Timedelta in this codebase is written positionally with an explicit unit --
# pd.Timedelta(6, "D"), never pd.Timedelta(days=6). The keyword form builds a NumPy timedelta
# with the "generic" unit, which NumPy deprecated and says it will eventually raise on; under
# pandas 2.3 / NumPy 2.5 it already emits a DeprecationWarning on every call, and these run on
# every page load. The two forms are exactly equivalent today, so this is purely about not
# shipping a dashboard that stops loading on a future NumPy. Please don't "tidy" it back.
def week_bounds(month_name, year, ordinal):
    """Monday/Sunday bounds of the `ordinal`-th Monday-start week overlapping `month_name year`."""
    month_start = pd.Timestamp(year=int(year), month=MONTH_ORDER.index(month_name) + 1, day=1)
    mondays = pd.date_range(month_start, month_start + pd.offsets.MonthEnd(0), freq="W-MON")
    start = mondays[int(ordinal) - 1]
    return start, start + pd.Timedelta(6, "D")


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


def build_project_lookup(periods, load_projects_fn=load_projects):
    """Project tag ("GEN_014", "PROT_005", ...) -> {"description", "period"} across EVERY
    reporting period, not just the current one -- the Gains page's Reuse/Lineage charts cite
    ids spanning more than one period (e.g. a tag could exist only in one year while another
    spans several), so a lookup scoped to "the current period" would silently go blank for half of
    them. `periods` is normally kd.discover_periods()'s result (newest-first); the first
    period that has a tag wins, so a project keeps whatever its most recent tracker entry
    says even if an older period also used the same tag for something else. `load_projects_fn`
    is injectable (kpi_cache passes its own cached wrapper so this join doesn't mean re-reading
    every period workbook on every rerun) and defaults to this module's own uncached reader for
    headless callers (the snapshot exporter, tests).

    Never raises: a period workbook that's locked/missing/malformed is skipped rather than
    failing the whole lookup -- this is a "nice to have" join, not a required one, and a
    tracker hiccup must never take down the Gains page's Reuse section with it."""
    lookup = {}
    for period in periods:
        try:
            projects = load_projects_fn(period["file"], period["sheet"])
        except Exception:
            continue
        if "Project tag" not in projects.columns:
            continue
        has_desc = "Short Description" in projects.columns
        for _, row in projects.iterrows():
            tag = str(row.get("Project tag") or "").strip()
            if not tag or tag.lower() == "nan":
                continue
            key = tag.upper()
            if key in lookup:
                continue  # a newer period already claimed this tag; keep its info
            desc = row.get("Short Description") if has_desc else None
            desc = str(desc).strip() if pd.notna(desc) and str(desc).strip().lower() != "nan" else ""
            lookup[key] = {"description": desc, "period": period["label"]}
    return lookup


def project_lookup_label(tag, project_lookup):
    """A Reuse-chart user-project id -> what to show on hover: the id alone, or the id plus
    its tracker description/period when `project_lookup` (build_project_lookup's result, or
    None) has a match. Degrades gracefully by design -- an unmatched id, or no lookup at all,
    still renders as a plain id, never a crash and never a literal "nan"."""
    tag = str(tag).strip()
    info = (project_lookup or {}).get(tag.upper())
    if not info:
        return tag
    # Built piece by piece rather than by joining a list: the em-dash belongs between the id
    # and its DESCRIPTION, and only then. A tracker sheet with no Short Description column
    # at all would otherwise join positionally and put the dash in front of the period
    # instead -- "GEN_014 — (2025)", a dash introducing nothing.
    label = tag
    if info.get("description"):
        label += f" — {info['description']}"
    if info.get("period"):
        label += f" ({info['period']})"
    return label


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


def new_timelog_row(week_start, project, category, major_task, hrs, mins,
                    timesheet="No", notes=""):
    """One track_time.csv row, with the file's Month / Month-and-year / Week / Year columns
    derived from the week's Monday. Shared by the Week editor's new rows and the time
    tracker's push, so both write exactly the same shape.

    Hrs/Min are normalized through their total: "1h and 90min" is stored as 2h30, and a
    fractional Hrs (2.5) keeps its half hour instead of being truncated to 2 by the int()
    the file's integer columns need."""
    month_name = week_start.strftime("%B")
    hrs, mins = split_hm(float(hrs or 0) + float(mins or 0) / 60)
    return {
        "Entry": project,
        "Timesheet updated": timesheet if timesheet in ("Yes", "No", "N/A") else "No",
        "Category": category,
        "Hours (exact)": hrs + mins / 60,
        "Major task name (chart)": major_task,
        "Hrs": hrs,
        "Min": mins,
        "Month": month_name,
        "Month and year (chart)": f"{month_name} {week_start.year}",
        "Notes": notes,
        "Week": ordinal_week_label(week_start),
        "Weekly entry name (chart)": project,
        "Year": week_start.year,
    }


def split_hm(hours):
    """Hours -> the (Hrs, Min) pair the time log stores, rounded to the minute as one
    number so 1.9999 h becomes (2, 0) and never (1, 60)."""
    total_minutes = int(round(float(hours or 0) * 60))
    return divmod(total_minutes, 60)


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
    for _, r in new_rows.iterrows():
        if not str(r.get("Weekly entry name (chart)", "") or "").strip():
            continue
        hrs, mins = _row_hours(r)
        timesheet = str(r.get("Timesheet updated", "") or "").strip()
        rows_to_add.append(new_timelog_row(
            week_start, project=r.get("Weekly entry name (chart)", ""),
            category=r.get("Category", ""), major_task=r.get("Major task name (chart)", ""),
            hrs=hrs, mins=mins, timesheet=str(r.get("Timesheet updated", "") or "").strip(),
            notes=r.get("Notes", ""),
        ))
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
    this_monday = today - pd.Timedelta(today.dayofweek, "D")
    for i in range(lookahead + 1):
        candidate = this_monday + pd.Timedelta(7 * i, "D")
        if period["start"] <= candidate < period["end"]:
            starts.add(candidate)
    ordered = sorted(starts)
    return [(s, format_week_label(s, s + pd.Timedelta(6, "D"))) for s in ordered]


def default_week(weeks, today):
    """Current week if it's in `weeks`, else the most recent one on/before today, else the latest available."""
    this_monday = today - pd.Timedelta(today.dayofweek, "D")
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
    trailing space ("Dataset Browser ") used to be stored verbatim, so trimming the
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

    # Completion stamp: a project counts as finished once "Completed" holds a date. The
    # column was added later than the sheet, so a file saved before it existed (or a row
    # left blank) simply reads as not finished.
    if "Completed" not in goals_df.columns:
        goals_df["Completed"] = pd.NaT
    completed = pd.to_datetime(goals_df["Completed"], errors="coerce")
    goals_df["_completed"] = [d.date() if pd.notna(d) else None for d in completed]
    goals_df["_finished"] = [d is not None for d in goals_df["_completed"]]
    # Keep the source column as plain text, so an editor writing "" back into it (to unmark
    # a project) isn't fighting a datetime64 column.
    goals_df["Completed"] = [d.isoformat() if d else "" for d in goals_df["_completed"]]

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
    "Development", "Impact", "Maintenance", "Visibility", "Completed",
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
    if "Completed" in out.columns:
        # Always written back as a plain ISO date (or blank), whatever the caller passed --
        # a Timestamp, a date, a typed-in string in the ratings grid.
        out["Completed"] = [
            d.date().isoformat() if pd.notna(d) else ""
            for d in pd.to_datetime(out["Completed"], errors="coerce")
        ]
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


# --- Special Projects & Tools: expected gains -------------------------------------------
# gains.xlsx is the live, DASHBOARD-OWNED store: plain sheets, a header on row 1, no formulas,
# no charts -- so this module can rewrite it the same way it rewrites the ratings sheet or
# tools.xlsx, and the Gains page can offer real editors instead of "go and edit Excel".
#
# It is seeded once, automatically, from SEED_GAINS_PATH below -- the hand-built
# SpecialProjects_Tools_expected_gains_v5.xlsx this page read directly until now. That
# workbook could never be written from here: it carries 4 real Excel charts, formula-linked
# Summary/Reuse/Gains sheets and conditional formatting, and openpyxl drops the charts and
# blanks every cached formula value on save -- which would leave pandas reading None out of
# every formula cell. It stays on disk, untouched, as the archived original; nothing reads it
# again once gains.xlsx exists.
GAINS_PATH = DATA_DIR / "gains.xlsx"
SEED_GAINS_PATH = DATA_DIR / "SpecialProjects_Tools_expected_gains_v5.xlsx"
# Kept as the old name so existing callers (kpi_cache's mtime key) keep working; it now points
# at the live file, not the seed.
EXPECTED_GAINS_PATH = GAINS_PATH

# The SEED workbook has a title row and a note row above the real header on every sheet (the
# hand-built formatting that makes it readable as an Excel file also makes pandas's default
# header guess wrong on all of them) -- each sheet's real header lands on raw row 3
# (0-indexed). gains.xlsx has none of that: header on row 0, data straight after.
_SEED_HEADER_ROW = 3

# The sheets gains.xlsx holds, and the columns each one owns. Derived numbers the seed
# workbook computed with formulas ("Gain types (n)", "Reuse level", the Summary sheet) are
# deliberately NOT stored: this page computes all of them on every load, and a stored copy
# could only ever drift from the lists it is supposed to be counting. The two count columns
# that DO survive are the ones that aren't purely derived -- "Came from (n)" carries a typed
# count for the handful of rows that record a number without listing the ids, and "User
# projects served (n)" carries the literal text "Constant use".
GAINS_SHEETS = ("Overview", "Gains", "Reuse", "Value", "Notes")
GAINS_OVERVIEW_COLS = [
    "ID", "Category", "Goal", "Project", "Status", "Output level", "Expected gains",
    "Internal users", "External users", "Facility use / collaboration",
    "Publication potential", "Market-equivalent value", "Use pattern",
]
GAINS_REUSE_COLS = [
    "ID", "Development / tool", "Came from (n)", "Came from: user projects",
    "User projects served (n)", "User projects served: list",
]
GAINS_VALUE_COLS = ["ID", "Project", "Audience", "Value basis", "Unit price (€)", "Unit"]
# The 5 x/blank audience-and-output columns of the Overview sheet, as one list rather than the
# same literal retyped in each place that needs it (load_expected_gains parses them to bool,
# kpi_charts.fig_audience_outputs draws one row per flag, the Gains page counts how many
# developments carry none of them). They are a SUBSET of GAINS_OVERVIEW_COLS above, not a
# separate set of columns -- adding a flag means adding it to both.
GAIN_AUDIENCE_FLAGS = [
    "Internal users", "External users", "Facility use / collaboration",
    "Publication potential", "Market-equivalent value",
]
# "Output level" values that mean the development was built for ADA or personal/internal use
# rather than for anyone it would call a "user" -- the audience dimension the 5 flags above
# never ask about. Drawn as fig_audience_outputs' own pinned first row.
GAIN_ADA_OUTPUT_LEVELS = frozenset({"Internal ADA", "Internal Worker"})

# The Gains sheet groups its gain columns under merged headers (row 2, not read as data since
# the header row is 3) -- GAIN_GROUPS is the dashboard's own record of that grouping (hardcoded
# since openpyxl would be needed to recover merged-cell labels, and the grouping is a thematic
# call, not something read off the sheet). Order matters: it drives the display order of
# gain_summary via GAIN_GROUP_ORDER (kpi_charts.py), built from this dict's value order.
#
# The actual set of gain COLUMNS is read fresh from the workbook on every load (see
# load_expected_gains's `gain_columns`/`gain_groups` below) -- whatever sits between "Project"
# and "Gain types (n)" on the Gains sheet, not a fixed list of 10 -- so this dict only needs to
# cover every NAME that's ever been a column header, known or not-yet-added, and never has to
# be "complete" in the sense of matching column count. A column whose header isn't a key here
# at load time falls back to GAIN_FALLBACK_GROUP (and is surfaced in the page's Data health
# section) rather than crashing or silently mis-grouping.
#
# "Training & capability building" used to be one conflated column. It was narrowed to
# "User capacitation" (giving users a tool that lets them work independently) rather than
# split in two -- teaching/catalogue work is already carried by "Cataloguing & outreach" and
# "New users / projects reached". The old combined name is KEPT mapped to Capability so an
# older copy of the workbook still groups correctly, and a separate "Training" (outreach that
# reaches NEW people) is recognized ahead of time should one ever be added as its own column.
GAIN_GROUPS = {
    "Faster project completion": "Efficiency",
    "Internal management": "Efficiency",
    "Training & capability building": "Capability",  # the column's old name; kept so an
    # older copy of the workbook still groups correctly.
    "User capacitation": "Capability",   # the live column: handing users a tool/dashboard that
    # lets them work independently -- deliberately narrower than the old name it replaces.
    "AI skills (Bigorna Project)": "Capability",
    "Pioneering development": "Innovation & visibility",
    "Flagship project": "Innovation & visibility",
    "Scientific publication": "Innovation & visibility",
    "New users / projects reached": "Reach & relationships",
    "Training": "Reach & relationships",   # not a column on today's Gains sheet -- recognized
    # ahead of time so adding one (teaching/outreach that reaches NEW people, as opposed to
    # "User capacitation" above) groups correctly the moment it appears, with no code change.
    "Cataloguing & outreach": "Reach & relationships",
    "Collaboration with other facilities": "Reach & relationships",
}

# Where an unrecognized gain column (a header not in GAIN_GROUPS above) lands, so a newly
# added column the dashboard doesn't know about yet still renders somewhere sensible
# instead of crashing. Also reported by name in the page's Data health section ("gain not assigned to a
# group yet") so the gap stays visible rather than silently absorbed.
GAIN_FALLBACK_GROUP = "Capability"

# Genuine spelling/naming differences between this workbook and tools.xlsx/the ratings sheet
# for the exact same thing (verified by hand, not a typo to "fix") -- without this, a plain
# name match would call both sides "unmatched". Keyed by the gains workbook's spelling,
# normalized (stripped + lowercased); _NAME_ALIASES_REV below is the other direction.
# Empty in this demo: its data is generated in one pass (generate_demo_data.py), so every
# file already spells every development the same way and there is nothing to reconcile. A
# real tracker grows the opposite way -- a tool typed into tools.xlsx one day and into the
# gains workbook another, or a rename finished in one file and not yet in the next -- and
# each such pair goes here as {gains-workbook spelling: other file's spelling}, normalized
# (stripped + lowercased). Without the entry a plain name match reports BOTH sides as
# unmatched and the development drops to the Status-column fallback (see _decide_state).
NAME_ALIASES = {
    # "snippet library (templates)": "snippet libary",
}
_NAME_ALIASES_REV = {v: k for k, v in NAME_ALIASES.items()}

# Status strings (Excel fallback) that count as "already delivering its gains" -- split by
# which of the two non-Potential states they map to (see _decide_state's fallback branch).
_FALLBACK_DELIVERED_STATUSES = {"completed"}
_FALLBACK_IN_USE_STATUSES = {"in use", "in use/in development"}

# An entry in a Reuse-sheet "Came from" cell either names a real user project (GEN_014,
# PROT_005, ...) or it names something that ITSELF has gains tracked here -- lineage, not
# reuse of a user's own work. The latter can be written as this workbook's own development
# ID (SP01, T04, ...) or, now, as a plain name matching a live tool/Special Project that has
# no row in this workbook at all yet (see _classify_lineage_token) -- either way it must never
# be counted as a "built out of real user projects" number.
# This demo's fake project tags are deliberately a different shape from the private
# original's (no DNA_/STAT_-style codes -- see generate_demo_data.py's module docstring),
# so the pattern below matches THIS repo's own tag convention: 3-6 letters, underscore,
# a 3-digit number (GEN_014, PROT_005, STRUCT_002, ...) -- swap it for your own tracker's
# tag shape if you adapt this dashboard.
_USER_PROJECT_ID_RE = re.compile(r"^[A-Z]{2,6}_\d{3}$", re.IGNORECASE)
_DEVELOPMENT_ID_RE = re.compile(r"^(SP\d+|T\d+)$", re.IGNORECASE)


def _norm_name(name):
    return str(name).strip().lower()


def _name_variants(name):
    """A name plus its known alias (if any), normalized -- the set of spellings that should
    all be treated as "the same development" when matching across files."""
    norm = _norm_name(name)
    variants = {norm}
    if norm in NAME_ALIASES:
        variants.add(NAME_ALIASES[norm])
    if norm in _NAME_ALIASES_REV:
        variants.add(_NAME_ALIASES_REV[norm])
    return variants


def _parse_count_or_constant(value):
    """A Reuse-sheet "(n)" cell: a number, blank, or the literal text "Constant use" (tools
    used daily/by everyone were never meaningfully "n projects served"). Returns
    (count_or_None, is_constant_use)."""
    if pd.isna(value):
        return None, False
    text = str(value).strip()
    if text.lower() == "constant use":
        return None, True
    try:
        return int(float(text)), False
    except ValueError:
        return None, False


def _parse_id_list(value):
    """A comma-separated cell (e.g. "GEN_014, PROT_005, CRC_030") -> a real Python list of
    raw tokens, so callers don't all re-split the same string. What each token MEANS (a user
    project, another development, a bare name) is for _classify_lineage_token to decide --
    this just un-joins the cell."""
    if pd.isna(value):
        return []
    return [part.strip() for part in str(value).split(",") if part.strip()]


# How a development came out of its parent. Two different stories the lineage tree used to
# draw identically: SP04 REPLACED SP03 (an evolution -- the parent is done),
# while SP11 is an adaptation of SP01 that runs alongside it (an output -- the parent is very
# much alive and just produced something). A parent token can say which by carrying one of
# these words in brackets, e.g. "SP01 (output)"; with nothing in brackets it is an evolution,
# which is what every token written before this existed meant.
LINEAGE_EVOLVED, LINEAGE_OUTPUT = "evolved", "output"
_LINEAGE_RELATION_WORDS = {
    LINEAGE_EVOLVED: {"evolved", "evolution", "evolved into", "evolved from", "replaced"},
    LINEAGE_OUTPUT: {"output", "output of", "adaptation", "adapted", "adapted from",
                     "instance", "spin-off", "spinoff", "branch"},
}
_LINEAGE_BRACKET_RE = re.compile(r"^(?P<token>.*?)\s*\((?P<relation>[^()]*)\)\s*$")


def split_lineage_relation(token):
    """'SP01 (output)' -> ('SP01', 'output'); 'SP01' -> ('SP01', 'evolved').

    Only a bracket whose contents are a KNOWN relation word is treated as one. Several real
    developments can carry brackets in their own names -- "Snippet Library (templates)",
    "QC Dashboard (per-run)" -- and stripping those would quietly break the name
    match that resolves them to a node, so anything unrecognised is left on the token."""
    text = str(token or "").strip()
    match = _LINEAGE_BRACKET_RE.match(text)
    if not match:
        return text, LINEAGE_EVOLVED
    word = match.group("relation").strip().lower()
    for relation, words in _LINEAGE_RELATION_WORDS.items():
        if word in words:
            return match.group("token").strip(), relation
    return text, LINEAGE_EVOLVED


def format_lineage_token(token, relation):
    """The inverse: what to write back into the cell for one parent."""
    return f"{token} ({LINEAGE_OUTPUT})" if relation == LINEAGE_OUTPUT else token


def _classify_lineage_token(token, valid_ids, live_name_lookup):
    """One raw token from a "Came from" cell -> (kind, key, label, relation).

    `kind` is "project" (an id matching _USER_PROJECT_ID_RE -- counts toward came_from_n) or
    "development" (anything else: this workbook's own SP../T.. ids, OR a free-text name that
    matches a live tool/Special Project which may not even have a row in this workbook yet,
    e.g. "variant-highlighter-skill" naming a tool that's only in tools_df). `key` is the
    identity used to index led_to (a development ID as written, or the token's normalized
    name) and `label` is what to show a person (resolved to the live table's own spelling
    for a name match, otherwise the token/ID as given).

    `valid_ids` restricts the ID-pattern branch to IDs this workbook actually has (SP01,
    T04, ...) -- a stray "SP99" that doesn't exist falls through to the name-match / bare-text
    branch instead of silently being treated as a real development. `live_name_lookup` maps
    every normalized name variant seen in tools_df/goals_df to that source's own display
    name (built once by the caller, not per token)."""
    token, relation = split_lineage_relation(token)
    if _USER_PROJECT_ID_RE.match(token):
        # A user project is never a lineage edge, so it has no relation to carry.
        return "project", token.upper(), token.upper(), LINEAGE_EVOLVED
    upper = token.upper()
    if _DEVELOPMENT_ID_RE.match(upper) and upper in valid_ids:
        return "development", upper, upper, relation
    norm = _norm_name(token)
    if norm in live_name_lookup:
        return "development", norm, live_name_lookup[norm], relation
    # Unrecognized text: still "not a user project", so it never counts toward came_from_n,
    # but it won't resolve to anything in led_to either (nothing named it as a live match).
    return "development", norm, token, relation


def _is_parent(dev_id, project_name, led_to_by_name):
    """True if some OTHER development's "Came from" names this one -- by this workbook's own
    ID, or by any of this development's own live-name variants (a Came from cell can name a
    parent either way, see _classify_lineage_token). On its own this is sufficient for "In
    use" (criterion 2): the thing it spawned is proof it's being used, even with zero user
    projects served directly (e.g. a platform, once a tool built on it names it)."""
    if led_to_by_name.get(dev_id):
        return True
    return any(led_to_by_name.get(v) for v in _name_variants(project_name))


def _read_gains_sheet(sheet_name, valid_ids):
    """Read one sub-sheet of the live gains.xlsx, then keep only rows whose ID is a real
    development ID from Overview -- a cheap guard against a stray row typed under the data,
    and the one place a sheet that has drifted out of step with Overview gets pruned."""
    df = pd.read_excel(GAINS_PATH, sheet_name=sheet_name)
    df = df[df["ID"].isin(valid_ids)].reset_index(drop=True)
    return df


def _seed_gains_workbook():
    """Build gains.xlsx once, from the hand-made SpecialProjects_Tools_expected_gains_v5.xlsx.

    Reads the seed through pandas (its formula cells come back as the values Excel last
    cached, which is exactly what this page was already reading) and writes them out flat:
    header on row 0, one sheet per GAINS_SHEETS entry, no formulas and no charts, so every
    later write is a plain DataFrame.to_excel. The seed is never touched, and never read
    again once this has run.

    Columns the seed computed with formulas and this page recomputes anyway ("Gain types
    (n)", "Reuse level (served)", the whole Summary sheet) are dropped here rather than
    frozen into the new file -- see GAINS_SHEETS' comment. The Gains sheet's own gain columns
    are copied as-found, whatever they happen to be: that set is read fresh on every load and
    must stay free to change.
    """
    overview = pd.read_excel(SEED_GAINS_PATH, sheet_name="Overview", header=_SEED_HEADER_ROW)
    overview.columns = [str(c).strip() for c in overview.columns]
    overview = overview[overview["ID"].astype(str).str.strip().str.match(r"^(SP|T)\d+$", na=False)]
    valid_ids = set(overview["ID"])

    def seed_sheet(name):
        df = pd.read_excel(SEED_GAINS_PATH, sheet_name=name, header=_SEED_HEADER_ROW)
        df.columns = [str(c).strip() for c in df.columns]
        return df[df["ID"].isin(valid_ids)].reset_index(drop=True)

    gains = seed_sheet("Gains")
    gain_cols = [c for c in gains.columns
                 if c not in ("ID", "Project", "Gain types (n)") and not c.startswith("Unnamed")]
    reuse, value = seed_sheet("Reuse"), seed_sheet("Value")
    notes_raw = pd.read_excel(SEED_GAINS_PATH, sheet_name="Notes", header=None)
    notes = [str(v).strip() for v in notes_raw.iloc[1:, 0] if pd.notna(v) and str(v).strip()]

    sheets = {
        "Overview": overview[[c for c in GAINS_OVERVIEW_COLS if c in overview.columns]],
        "Gains": gains[["ID", "Project"] + gain_cols],
        "Reuse": reuse[[c for c in GAINS_REUSE_COLS if c in reuse.columns]],
        "Value": value[[c for c in GAINS_VALUE_COLS if c in value.columns]],
        "Notes": pd.DataFrame({"Note": notes}),
    }
    _write_gains_sheets(sheets)
    return sheets


def _write_gains_sheets(sheets):
    """Write every sheet of gains.xlsx in one pass. Always all of them, never one in place:
    the sheets cross-reference each other by ID, and a part-written file would leave the page
    reading a Gains row for a development Overview no longer lists. Writing the lot keeps the
    file valid at every point a reader could see it.

    May raise PermissionError -- callers show the usual "it's open in Excel" message."""
    with pd.ExcelWriter(GAINS_PATH, engine="openpyxl") as writer:
        for name in GAINS_SHEETS:
            df = sheets.get(name)
            if df is None:
                continue
            df.to_excel(writer, sheet_name=name, index=False)


def load_gains_sheets():
    """The raw sheets of gains.xlsx as DataFrames, keyed by sheet name -- what the EDITORS
    read and write back. Seeds the file from the archived v5 workbook the first time.

    Deliberately raw: no state decided, no names resolved, no derived counts. load_expected_gains
    below is the one that folds in live Special Projects/Tools status for DISPLAY; an editor
    saving a row must not write any of that back into the store."""
    if not GAINS_PATH.exists():
        return _seed_gains_workbook()
    sheets = pd.read_excel(GAINS_PATH, sheet_name=None)
    for df in sheets.values():
        df.columns = [str(c).strip() for c in df.columns]
    return sheets


def save_gains_sheets(sheets):
    """Write the gains store back, re-syncing the name columns first.

    Overview owns each development's name; the Gains/Reuse/Value sheets each carry a copy for
    readability (the seed workbook had them as `=Overview!D5` formulas, which is exactly the
    same thing done with less ceremony). Rewriting them from Overview on every save is what
    stops a rename in one place leaving three sheets labelled with the old name."""
    sheets = {name: df.copy() for name, df in sheets.items()}
    overview = sheets.get("Overview")
    if overview is not None:
        name_by_id = dict(zip(overview["ID"], overview["Project"]))
        for sheet_name, col in (("Gains", "Project"), ("Reuse", "Development / tool"),
                                 ("Value", "Project")):
            df = sheets.get(sheet_name)
            if df is not None and len(df):
                df[col] = [name_by_id.get(i, n) for i, n in zip(df["ID"], df.get(col, df["ID"]))]
    _write_gains_sheets(sheets)


def next_development_id(overview, category):
    """The next free SP../T.. id for a new development, numbered within its own series so the
    ids stay meaningful (SP = Special Project, T = Tool). Counts from the highest existing
    number rather than the row count, so deleting a row never hands the next one a duplicate."""
    prefix = "SP" if category == "Special Project" else "T"
    used = [
        int(m.group(1))
        for m in (re.match(rf"^{prefix}(\d+)$", str(i).strip(), re.IGNORECASE)
                  for i in overview["ID"])
        if m
    ]
    return f"{prefix}{max(used, default=0) + 1:02d}"


def _decide_state(category, project_name, status, goals_by_name, tools_by_name,
                   served_ids, is_parent):
    """The core Delivered / In use / Potential call for one development -- a pure function of
    plain values (no DataFrame access), so every branch is directly unit-testable.

    Delivered only ever comes from a Special Project's own Completed date
    (`goals_by_name[name]` is `_finished`), or, as a fallback with no live match at all, the
    workbook's own Status column reading "Completed" -- there's no "delivered because XYZ"
    shortcut the way there is for In use.

    In use is Delivered's weaker sibling -- demonstrably being used, but not (yet) finished
    and banked -- and ANY of these is enough on its own, independent of how the base status
    below was decided:
      1. `served_ids` is non-empty (it serves at least one real user project), or
      2. `is_parent` is True (some OTHER development names this one as where it came from --
         itself proof of use, with no served project required), or
      3. it's matched as a Tool whose live Status isn't Deprecated.
    Live dashboard data wins the BASE status when it's available and matches by name; the
    Excel's own Status column is only a fallback for the base -- the workbook's Notes sheet
    says those statuses were filled in as a blanket guess ("Tools = In use, Special Projects
    = In development"), not verified per row. Criteria 1/2 above can still elevate that
    fallback-decided base from Potential to In use.

    Returns (state, match_source) -- match_source ("ratings"/"tools"/"status") names which
    live table decided the BASE status, same meaning as before the 3-state split."""
    variants = _name_variants(project_name)
    delivered = False
    in_use = False
    match_source = "status"

    if category == "Special Project" and goals_by_name is not None:
        for v in variants:
            if v in goals_by_name:
                delivered = bool(goals_by_name[v])
                match_source = "ratings"
                break

    if match_source == "status" and category == "Tools" and tools_by_name is not None:
        for v in variants:
            if v in tools_by_name:
                in_use = tools_by_name[v] != "deprecated"
                match_source = "tools"
                break

    if match_source == "status":
        norm_status = _norm_name(status)
        if norm_status in _FALLBACK_DELIVERED_STATUSES:
            delivered = True
        elif norm_status in _FALLBACK_IN_USE_STATUSES:
            in_use = True

    if delivered:
        return "Delivered", match_source
    if in_use or bool(served_ids) or is_parent:
        return "In use", match_source
    return "Potential", match_source


def load_expected_gains(goals_df=None, tools_df=None, project_lookup=None):
    """Read SpecialProjects_Tools_expected_gains_v5.xlsx -- the catalogue of Special
    Projects' and Tools' expected (or already-delivered) gains -- and fold it together with
    whatever's live on the dashboard. Optional `goals_df` (load_goals()) and `tools_df`
    (load_tools()) let a Special Project / Tool's real status override the Excel's own
    Status column for the Delivered/In use/Potential call (see _decide_state); pass neither
    to fall back to the Excel alone, e.g. from a context that hasn't loaded them. Optional
    `project_lookup` (build_project_lookup()'s result) joins the Reuse sheet's project-tag
    ids to the real project tracker, across every reporting period -- see "unmatched_reuse_ids"
    below for what happens when an id has no match.

    Returns a dict:
      - "developments": one row per Overview row, all its columns cleaned (the 5 x/blank
        flag columns parsed to bool), plus "active" (bool, state != "Potential"), "state"
        ("Delivered"/"In use"/"Potential"), "match_source" ("ratings"/"tools"/"status" --
        which rule decided the BASE status, see _decide_state), "led_to" (readable names of
        other developments naming this one as a parent), and "constant_use" (bool, from Use
        pattern).
      - "gains_long": tidy, one row per (development, gain) marked "x" -- ID, Project,
        Category, Gain, Group, active, state.
      - "gain_summary": one row per gain ACTUALLY present on the Gains sheet (even ones with
        zero rows) -- Gain, Group, n_delivered, n_in_use, n_potential, n_active (= delivered +
        in use), n_total, active_projects, potential_projects, delivered_projects,
        in_use_projects (name lists, for chart hover), sorted by n_total descending. The gain
        set is read fresh from the sheet every load (see "gain_columns" below), not a fixed
        list of 10 -- works whether the sheet has 9, 10, 11 or 12 gain columns.
      - "gain_columns": the gain column headers actually found between "Project" and "Gain
        types (n)" on the Gains sheet, in sheet order -- what gain_summary/gains_long iterate
        over, and what the charts need to size/order themselves instead of assuming GAIN_GROUPS'
        historical 10.
      - "gain_groups": {gain column name: group name} for exactly the columns in
        "gain_columns" (GAIN_GROUPS' mapping where the name is recognized, else
        GAIN_FALLBACK_GROUP) -- what the charts use to band/colour columns, instead of
        consulting the static GAIN_GROUPS dict directly.
      - "ungrouped_gains": gain column names present on the sheet but NOT in GAIN_GROUPS --
        i.e. silently mapped to GAIN_FALLBACK_GROUP above rather than a group actually
        picked for them. Surfaced in the page's Data health section so a newly-added column
        with an unrecognized name doesn't quietly land in the wrong theme unnoticed.
      - "reuse": the Reuse sheet, come_from/serves columns as real lists, came_from_n /
        serves_n as nullable ints (came_from_n counts ONLY ids matching
        _USER_PROJECT_ID_RE -- see
        came_from_projects below), constant_use bool, led_to, came_from_relations
        (parent label -> "evolved"/"output", see split_lineage_relation), joined to
        active/state.
        came_from_ids / serves_ids keep their old meaning (the raw token lists); on top of
        those: came_from_projects (_USER_PROJECT_ID_RE matches only), came_from_developments (this
        workbook's own ids, or a bare name, for anything in "Came from" that is NOT a user
        project -- lineage, not reuse).
      - "value": the Value sheet, unit_price numeric-or-None, joined to active/state.
      - "notes": the Notes sheet's free-text lines as a list of strings (title row dropped).
      - "unmatched_tools": non-deprecated tools_df names with no row in this workbook at all
        (by name, alias included) -- a data-health check, not restricted to rows categorized
        "Tools" (e.g. a tool that's actually catalogued here as a Special Project still
        counts as matched).
      - "unmatched_projects": same idea for goals_df project names.
      - "unmatched_reuse_ids": project-tag ids used in the Reuse sheet's "Came from" or
        "User projects served" columns that match no project in `project_lookup` across any
        period -- a typo catcher (only populated when `project_lookup` is given; empty, not
        wrongly "all unmatched", when it's None).
      - "lineage_parent_status": for a lineage parent with no row in this workbook, its live
        tools.xlsx status (today only ever "Deprecated"), keyed by normalized name. Lets the
        lineage chart say why such a node has no Delivered/In use/Potential state of its own.
      - "lineage_parent_status": for a lineage parent with no row in this workbook, its live
        tools.xlsx status (today only ever "Deprecated"), keyed by normalized name. Lets the
        lineage chart say why such a node has no Delivered/In use/Potential state of its own.
      - "led_to_by_name": the full lineage reverse-index, keyed by EVERY parent identity seen
        in any "Came from" cell (a workbook ID like "SP01", or a normalized free-text name) --
        not just ones with their own Overview row, so a tool like "variant-highlighter-skill"
        that isn't catalogued here at all can still be looked up (`led_to_by_name[norm_name]`)
        without KeyError. "developments"/"reuse"["led_to"] is this same dict filtered down to
        workbook rows and resolved to display names, for the page to render directly.
    May raise FileNotFoundError / PermissionError -- callers show a friendly message, same
    as load_tools().
    """
    if not GAINS_PATH.exists():
        _seed_gains_workbook()  # first run: build the live store from the archived workbook
    overview = pd.read_excel(GAINS_PATH, sheet_name="Overview")
    overview.columns = [str(c).strip() for c in overview.columns]
    overview = overview[overview["ID"].astype(str).str.strip() != ""].reset_index(drop=True)
    for col in ["ID", "Category", "Goal", "Project", "Status", "Output level", "Expected gains"]:
        overview[col] = overview[col].astype(str).str.strip()
    for col in GAIN_AUDIENCE_FLAGS:
        overview[col] = overview[col].astype(str).str.strip().str.lower() == "x"
    overview["constant_use"] = overview["Use pattern"].astype(str).str.strip() == "Constant use"

    valid_ids = set(overview["ID"])
    category_by_id = dict(zip(overview["ID"], overview["Category"]))
    project_name_by_id = dict(zip(overview["ID"], overview["Project"]))

    # Name -> live-status lookups, built once rather than per-row.
    goals_by_name = None
    if goals_df is not None:
        goals_by_name = {_norm_name(p): f for p, f in zip(goals_df["Project"], goals_df["_finished"])}
    tools_by_name = None
    if tools_df is not None:
        tools_by_name = {_norm_name(n): _norm_name(s) for n, s in zip(tools_df["Name"], tools_df["Status"])}

    # Every live name (tool or Special Project) this dashboard knows about, normalized ->
    # that source's own display spelling -- lets a "Came from" cell name a parent that has NO
    # row in this workbook at all (e.g. "variant-highlighter-skill") and still have it resolve as
    # lineage instead of being silently miscounted as an unrecognized user project.
    live_name_lookup = {}
    if tools_df is not None:
        for n in tools_df["Name"]:
            for v in _name_variants(n):
                live_name_lookup.setdefault(v, n)
    if goals_df is not None:
        for n in goals_df["Project"]:
            for v in _name_variants(n):
                live_name_lookup.setdefault(v, n)

    # --- Reuse: parsed early, since the lineage it records (who's a parent of whom, who
    # serves a real user project) feeds directly into the Delivered/In use/Potential call
    # below, not just into the Reuse section's own chart. ---------------------------------
    reuse = _read_gains_sheet("Reuse", valid_ids)
    came_from_counted = [_parse_count_or_constant(v) for v in reuse["Came from (n)"]]
    served_counted = [_parse_count_or_constant(v) for v in reuse["User projects served (n)"]]
    reuse["serves_n"] = pd.array([c for c, _ in served_counted], dtype="Int64")
    # "Constant use" can show up under either count column (today it's only ever the
    # "served" one) -- either is enough to call the development constant-use.
    reuse["constant_use"] = [a or b for (_, a), (_, b) in zip(came_from_counted, served_counted)]
    reuse["came_from_ids"] = reuse["Came from: user projects"].map(_parse_id_list)
    reuse["serves_ids"] = reuse["User projects served: list"].map(_parse_id_list)
    reuse["serves_project_ids"] = reuse["serves_ids"].map(
        lambda ids: [i for i in ids if _USER_PROJECT_ID_RE.match(i)]
    )

    came_from_projects_col, came_from_developments_col, came_from_relations_col = [], [], []
    led_to_by_name = {}
    # A lineage parent with no row in THIS workbook still has a live status in tools.xlsx --
    # most usefully "Deprecated", with its reason, which is exactly what a parent that got
    # folded into its own child looks like (Request Triage Tool -> Template Library). Collected here,
    # keyed by the parent's normalized name, so the lineage chart can say WHY a node has no
    # Delivered/In use/Potential state instead of just "not tracked". Only non-blank statuses
    # are recorded; a parent that's simply absent from this workbook stays out of the dict.
    lineage_parent_status = {}
    for dev_id, tokens in zip(reuse["ID"], reuse["came_from_ids"]):
        child_name = project_name_by_id.get(dev_id, dev_id)
        projects, developments_here, relations_here = [], [], {}
        for token in tokens:
            kind, key, label, relation = _classify_lineage_token(token, valid_ids, live_name_lookup)
            if kind == "project":
                projects.append(key)
            else:
                developments_here.append(label)
                # Keyed by the same label came_from_developments carries, so the lineage
                # chart can look up an edge's relation with what it already iterates.
                relations_here[label] = relation
                led_to_by_name.setdefault(key, []).append(child_name)
                if key not in valid_ids and tools_by_name:
                    for variant in _name_variants(label):
                        status = tools_by_name.get(variant, "")
                        if status and status != "nan":
                            lineage_parent_status[_norm_name(label)] = status.title()
                            break
        came_from_projects_col.append(projects)
        came_from_developments_col.append(developments_here)
        came_from_relations_col.append(relations_here)
    reuse["came_from_projects"] = came_from_projects_col
    reuse["came_from_developments"] = came_from_developments_col
    reuse["came_from_relations"] = came_from_relations_col
    # Trust the parsed ids over the "(n)" column's cached Excel-formula value whenever ids
    # were actually listed (see module docstring note on load_expected_gains) -- only fall
    # back to the typed number for rows that have a count with no ids at all. Crucially this
    # counts came_from_PROJECTS only -- a lineage parent named in the same cell
    # (came_from_developments) must never inflate this number, and a row whose "Came from"
    # cell holds ONLY a lineage parent must stay BLANK here rather than falling through to the
    # typed count: the sheet's own "(n)" formula is a plain comma count, so it says 1 for that
    # row, which would wrongly book the development as "built out of real user projects" on
    # the Gains page's headline metric. Hence the three-way split -- ids listed / cell empty /
    # cell holds lineage only -- instead of a plain `projs or typed`.
    came_from_n_col = []
    for projs, tokens, (typed, _) in zip(came_from_projects_col, reuse["came_from_ids"], came_from_counted):
        if projs:
            came_from_n_col.append(len(projs))
        elif tokens:
            came_from_n_col.append(None)  # lineage parent(s) only -- no user project behind it
        else:
            came_from_n_col.append(typed)
    reuse["came_from_n"] = pd.array(came_from_n_col, dtype="Int64")

    served_project_ids_by_id = dict(zip(reuse["ID"], reuse["serves_project_ids"]))
    is_parent_by_id = {
        dev_id: _is_parent(dev_id, project_name_by_id.get(dev_id, dev_id), led_to_by_name)
        for dev_id in overview["ID"]
    }

    decided = [
        _decide_state(cat, proj, status, goals_by_name, tools_by_name,
                       served_project_ids_by_id.get(dev_id, []), is_parent_by_id.get(dev_id, False))
        for dev_id, cat, proj, status in
        zip(overview["ID"], overview["Category"], overview["Project"], overview["Status"])
    ]
    overview["state"] = [d[0] for d in decided]
    overview["match_source"] = [d[1] for d in decided]
    overview["active"] = overview["state"] != "Potential"
    overview["led_to"] = overview["ID"].map(lambda i: led_to_by_name.get(i, []))

    active_by_id = dict(zip(overview["ID"], overview["active"]))
    state_by_id = dict(zip(overview["ID"], overview["state"]))

    # --- Gains: wide x-marks -> tidy one-row-per-(development, gain) -------------------
    gains_raw = _read_gains_sheet("Gains", valid_ids)

    # The gain columns are whatever actually sits between "Project" and "Gain types (n)" on
    # this sheet -- never assumed to be a fixed set of 10, so the Gains sheet can gain (or, in
    # principle, lose) a column -- e.g. adding a "Training" gain alongside "User capacitation"
    # -- without any code change. Falls back to whichever of
    # GAIN_GROUPS' historically-known names are actually present if the sheet's own "Project"/
    # "Gain types (n)" boundary headers are ever renamed or missing, rather than raising.
    _cols = list(gains_raw.columns)
    try:
        _start = _cols.index("Project") + 1
        _end = _cols.index("Gain types (n)")
        gain_columns = [c for c in _cols[_start:_end] if c and not str(c).startswith("Unnamed")]
    except ValueError:
        gain_columns = [c for c in GAIN_GROUPS if c in _cols]

    # Group assignment is name-based (matched case/whitespace-insensitively against GAIN_GROUPS)
    # so a column's position on the sheet never matters, only its header text. A column whose
    # name isn't recognized at all still gets a group (GAIN_FALLBACK_GROUP) rather than crashing
    # or being dropped -- and is listed in ungrouped_gains so it doesn't silently go unnoticed.
    _known_groups = {_norm_name(k): v for k, v in GAIN_GROUPS.items()}
    gain_groups = {}
    ungrouped_gains = []
    for gain in gain_columns:
        group = _known_groups.get(_norm_name(gain))
        if group is None:
            group = GAIN_FALLBACK_GROUP
            ungrouped_gains.append(gain)
        gain_groups[gain] = group

    long_rows = []
    for _, row in gains_raw.iterrows():
        for gain in gain_columns:
            if str(row.get(gain, "")).strip().lower() == "x":
                long_rows.append({
                    "ID": row["ID"],
                    "Project": row["Project"],
                    "Category": category_by_id.get(row["ID"], ""),
                    "Gain": gain,
                    "Group": gain_groups[gain],
                    "active": active_by_id.get(row["ID"], False),
                    "state": state_by_id.get(row["ID"], "Potential"),
                })
    gains_long = pd.DataFrame(long_rows, columns=["ID", "Project", "Category", "Gain", "Group", "active", "state"])

    summary_rows = []
    for gain in gain_columns:
        subset = gains_long[gains_long["Gain"] == gain]
        delivered_rows = subset[subset["state"] == "Delivered"]
        in_use_rows = subset[subset["state"] == "In use"]
        potential_rows = subset[subset["state"] == "Potential"]
        active_rows = subset[subset["active"]]
        summary_rows.append({
            "Gain": gain,
            "Group": gain_groups[gain],
            "n_delivered": len(delivered_rows),
            "n_in_use": len(in_use_rows),
            "n_potential": len(potential_rows),
            "n_active": len(active_rows),
            "n_total": len(subset),
            "active_projects": list(active_rows["Project"]),
            "potential_projects": list(potential_rows["Project"]),
            "delivered_projects": list(delivered_rows["Project"]),
            "in_use_projects": list(in_use_rows["Project"]),
        })
    gain_summary = pd.DataFrame(summary_rows).sort_values("n_total", ascending=False).reset_index(drop=True)

    # --- Reuse (continued): now that state is decided, join it back in -------------------
    reuse["led_to"] = reuse["ID"].map(lambda i: led_to_by_name.get(i, []))
    reuse["active"] = reuse["ID"].map(active_by_id)
    reuse["state"] = reuse["ID"].map(state_by_id)

    # --- Value -----------------------------------------------------------------------------
    value = _read_gains_sheet("Value", valid_ids)
    unit_price = pd.to_numeric(value["Unit price (€)"], errors="coerce")
    # Plain "object" dtype on purpose: a float column would silently turn this None back
    # into NaN (pandas has no non-NA-extension-array way to hold a real None alongside
    # floats), and callers checking "is None" (a blank price, like Hands-on workshop's)
    # should get exactly that.
    value["unit_price"] = pd.array(
        [float(p) if pd.notna(p) else None for p in unit_price], dtype=object
    )
    value["active"] = value["ID"].map(active_by_id)
    value["state"] = value["ID"].map(state_by_id)

    # --- Notes: free text, title row dropped ------------------------------------------------
    notes_raw = pd.read_excel(GAINS_PATH, sheet_name="Notes")
    notes = [
        str(v).strip() for v in notes_raw.iloc[:, 0]
        if pd.notna(v) and str(v).strip()
    ]

    # --- Data-health: names on the live side with no row here at all -----------------------
    overview_variants = set()
    for name in overview["Project"]:
        overview_variants |= _name_variants(name)
    unmatched_tools = []
    if tools_df is not None:
        # Deprecated tools are deliberately NOT reported as missing: this list exists to
        # prompt "that one still needs a gains row", and a retired tool never will -- it has
        # no gains left to expect. Flagging it would be a to-do item that can't be closed.
        live_tools = tools_df[tools_df["Status"].astype(str).str.strip() != "Deprecated"]
        unmatched_tools = [
            name for name in live_tools["Name"]
            if not (_name_variants(name) & overview_variants)
        ]
    unmatched_projects = []
    if goals_df is not None:
        unmatched_projects = [
            name for name in goals_df["Project"]
            if not (_name_variants(name) & overview_variants)
        ]

    # A Reuse-sheet user-project id that matches no tracker entry in ANY period is usually a
    # typo (GEN_014 vs GEN_O14, a stray space, ...) -- worth flagging, but only when there's
    # something to check against; with no project_lookup at all this is silently empty rather
    # than wrongly flagging every id as unmatched.
    unmatched_reuse_ids = []
    if project_lookup is not None:
        seen_ids = set()
        for ids in reuse["came_from_projects"]:
            seen_ids.update(ids)
        for ids in reuse["serves_project_ids"]:
            seen_ids.update(ids)
        unmatched_reuse_ids = sorted(i for i in seen_ids if i.upper() not in project_lookup)

    return {
        "developments": overview,
        "gains_long": gains_long,
        "gain_summary": gain_summary,
        "gain_columns": gain_columns,
        "gain_groups": gain_groups,
        "ungrouped_gains": ungrouped_gains,
        "reuse": reuse,
        "value": value,
        "notes": notes,
        "unmatched_tools": unmatched_tools,
        "unmatched_projects": unmatched_projects,
        "unmatched_reuse_ids": unmatched_reuse_ids,
        "project_lookup": project_lookup,
        "led_to_by_name": led_to_by_name,
        "lineage_parent_status": lineage_parent_status,
    }


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


# --- Publications (per period, dashboard-only state like the beyond-projects cards) -------
PUBLICATIONS_PATH = DATA_DIR / "publications.json"

# Invented papers, only used the first time the file doesn't exist yet -- same fake-tag
# naming convention as generate_demo_data.py's FAKE_PROJECT_TAGS, keyed by the calendar-year
# period label this demo uses.
_PUBLICATIONS_SEED = {
    "2025": [
        {"title": "A multiomics pipeline for routine lipidomics QC",
         "venue": "Journal of Open Bioinformatics (example)", "date": "2025-09-12",
         "url": "https://example.org/jobi/2025/example-lipidomics-qc",
         "projects": "LIP_003, META_008"},
        {"title": "Benchmarking structural variant callers on facility sequencing data",
         "venue": "bioRxiv preprint (example)", "date": "2025-11-03",
         "url": "https://example.org/biorxiv/2025.11.03.example",
         "projects": "SEQ_019, STRUCT_002"},
    ],
}


def load_publications():
    if not PUBLICATIONS_PATH.exists():
        save_publications(dict(_PUBLICATIONS_SEED))
        return dict(_PUBLICATIONS_SEED)
    try:
        return json.loads(PUBLICATIONS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def export_publications_to_excel(all_pubs):
    """Mirror the publications (held in PUBLICATIONS_PATH as the source of truth) into
    PUBLICATIONS_XLSX_PATH -- one row per publication, every reporting period in a single
    sheet -- so this content lives somewhere Excel-readable too, like the beyond-projects
    cards do."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Publications"
    ws.append(["Period", "Title", "Venue", "Date", "URL", "Related projects"])
    for period_label, pubs in all_pubs.items():
        for pub in pubs:
            ws.append([period_label, pub.get("title", ""), pub.get("venue", ""),
                       pub.get("date", ""), pub.get("url", ""), pub.get("projects", "")])
    for col, width in zip("ABCDEF", (18, 45, 18, 14, 45, 20)):
        ws.column_dimensions[col].width = width
    wb.save(PUBLICATIONS_XLSX_PATH)


def save_publications(all_pubs):
    """Write the JSON source of truth, then mirror to Excel. Returns a warning string if
    the Excel mirror couldn't be written (file open in Excel / locked by OneDrive) -- the
    JSON save still succeeded, so edits are never lost to a lock."""
    PUBLICATIONS_PATH.write_text(json.dumps(all_pubs, indent=2, ensure_ascii=False), encoding="utf-8")
    try:
        export_publications_to_excel(all_pubs)
    except PermissionError:
        return (f"Saved, but couldn't update {PUBLICATIONS_XLSX_PATH.name} (close it in Excel "
                "to refresh the mirror on the next edit).")
    return None


# --- CV: the career record the service sits inside ------------------------------------------
# cv_data.json is the source of truth and cv_data.xlsx its Excel mirror -- the same split the
# beyond-projects cards and publications already use: the dashboard writes the JSON, then
# rewrites the workbook from it so the content is readable (and printable) outside the app.
# The workbook is never read back, so hand-editing it is a dead end; the CV page says so, and
# offers every section as an editable table instead.
CV_PATH = DATA_DIR / "cv_data.json"
CV_XLSX_PATH = DATA_DIR / "cv_data.xlsx"
# No standalone CV page ships with the demo, so the export at the foot of the CV page
# stays hidden; drop one in under this name and it appears.
CV_HTML_PATH = DATA_DIR / "CV_dashboard.html"

# Section -> the field order its sheet/table uses. The order matters twice over: it is the
# column order in the mirror workbook and the column order in the page's editors. A section
# missing from here still loads -- it just falls back to whatever key order the JSON has.
CV_SECTIONS = {
    "profile": ["field", "value"],
    "cv_stats": ["section", "key", "value", "label"],
    "experience": ["id", "title", "organisation", "location", "start", "end",
                   "date_note", "lead"],
    "experience_bullets": ["experience_id", "order", "text"],
    "publications": ["title", "venue", "year", "type", "first_author", "doi", "url"],
    "conference_contributions": ["title", "event", "date", "type", "note"],
    "teaching": ["item", "institution", "date", "students", "detail"],
    "education": ["degree", "institution", "years", "grade", "thesis"],
    "courses_certifications": ["title", "provider", "date", "topics"],
    "awards": ["award", "event", "year"],
    "skills": ["area", "status", "item"],
    "skill_matrix": ["skill"],  # the era columns are discovered from the data, not fixed here
    "volunteering_languages": ["item", "date"],
    "profiles_ids": ["name", "id", "url"],
}

def load_cv():
    """The CV content store. Always returns every section key (an absent one as an empty
    list), so callers never have to guard."""
    cv = {}
    if CV_PATH.exists():
        try:
            cv = json.loads(CV_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            cv = {}
    cv.setdefault("meta", {})
    for section in CV_SECTIONS:
        cv.setdefault(section, [])
    return cv


def cv_section_columns(section, rows):
    """Declared field order first, then any extra key a row actually carries -- so a field
    added by hand in the JSON still reaches the mirror and the editor instead of being
    silently dropped (this is what keeps skill_matrix's era columns working)."""
    columns = list(CV_SECTIONS.get(section, []))
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(key)
    return columns


def export_cv_to_excel(cv):
    """Mirror cv_data.json into cv_data.xlsx -- a README sheet built from `meta`, then one
    sheet per section. Rewritten whole on every save: unlike the project tracker there are no
    formulas in here to flatten, and the file exists to be read, not edited."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "README"
    ws.append(["topic", "note"])
    for topic, note in (cv.get("meta") or {}).items():
        ws.append([topic, note])
    ws.column_dimensions["A"].width = 44
    ws.column_dimensions["B"].width = 110

    for section, rows in cv.items():
        if section == "meta" or not isinstance(rows, list):
            continue
        sheet = wb.create_sheet(section[:31])
        columns = cv_section_columns(section, rows)
        sheet.append(columns)
        for row in rows:
            sheet.append([row.get(col, "") for col in columns])
        for i, col in enumerate(columns, start=1):
            widest = max([len(str(col))] + [len(str(r.get(col, ""))) for r in rows])
            sheet.column_dimensions[openpyxl.utils.get_column_letter(i)].width = min(70, max(12, widest + 2))
    wb.save(CV_XLSX_PATH)


def save_cv(cv, stamp_today=True):
    """Write the JSON source of truth, then mirror to Excel. Returns a warning string if the
    mirror couldn't be written (file open in Excel / locked by OneDrive) -- the JSON save
    still succeeded, so an edit is never lost to a lock."""
    if stamp_today:
        cv.setdefault("meta", {})["Updated"] = pd.Timestamp.now().strftime("%Y-%m-%d")
    CV_PATH.write_text(json.dumps(cv, indent=2, ensure_ascii=False), encoding="utf-8")
    try:
        export_cv_to_excel(cv)
    except PermissionError:
        return (f"Saved, but couldn't update {CV_XLSX_PATH.name} (close it in Excel to refresh "
                "the mirror on the next edit).")
    return None


def cv_profile(cv):
    """The profile section's field/value rows as a plain dict (name, role, email, about)."""
    return {str(r.get("field", "")): r.get("value", "") for r in cv.get("profile", [])}


def set_cv_profile(cv, values):
    """Write those fields back, keeping any field the page didn't offer and the original
    row order."""
    for row in cv.get("profile", []):
        field = str(row.get("field", ""))
        if field in values:
            row["value"] = values[field]
    known = {str(r.get("field", "")) for r in cv.get("profile", [])}
    for field, value in values.items():
        if field not in known:
            cv.setdefault("profile", []).append({"field": field, "value": value})
    return cv


def cv_bullets_for(cv, experience_id):
    """One role's bullet texts, in `order`. The join cv_data.json's own README documents:
    experience_bullets.experience_id -> experience.id."""
    rows = [r for r in cv.get("experience_bullets", []) if r.get("experience_id") == experience_id]
    rows.sort(key=lambda r: r.get("order") or 0)
    return [str(r.get("text", "")) for r in rows]


def set_cv_bullets(cv, experience_id, bullets):
    """Replace one role's bullets wholesale, leaving every other role's untouched and
    renumbering `order` from 1 -- the editor hands back a block of text, not row ids.

    Rebuilt in experience order so the JSON and its mirror stay grouped by role and readable,
    rather than drifting into 'every edited role last'."""
    kept = [r for r in cv.get("experience_bullets", []) if r.get("experience_id") != experience_id]
    added = [{"experience_id": experience_id, "order": i, "text": text.strip()}
             for i, text in enumerate(bullets, start=1) if text.strip()]
    order = {e.get("id"): i for i, e in enumerate(cv.get("experience", []))}
    rows = kept + added
    rows.sort(key=lambda r: (order.get(r.get("experience_id"), 99), r.get("order") or 0))
    cv["experience_bullets"] = rows
    return cv


# --- ADA outputs: publications' siblings, logged per reporting period ----------------------
# Courses, conference contributions, juries and outreach done in the ADA role. They used to
# go into the free-form "beyond projects" cards, which can hold the text but not count it;
# here each one is a record with a kind and a date, logged against a reporting period and
# optionally against the project tags it came out of. Publications keep their own older
# store (publications.json); the Publications & Courses page edits both.
CV_OUTPUTS_PATH = DATA_DIR / "cv_outputs.json"
CV_OUTPUTS_XLSX_PATH = DATA_DIR / "CV_Outputs.xlsx"

CV_OUTPUT_KINDS = ["Course attended", "Certification", "Course taught", "Conference poster",
                   "Conference talk", "Thesis jury", "Outreach", "Other"]

# kind -> the section of a CV such an entry belongs in: it is what groups the kinds on the
# page, and what a CV view would fold them into. "Other" maps to nothing on purpose -- a
# record worth keeping for the reporting year, but not a CV line.
CV_OUTPUT_SECTION = {
    "Course attended": "courses_certifications",
    "Certification": "courses_certifications",
    "Course taught": "teaching",
    "Conference poster": "conference_contributions",
    "Conference talk": "conference_contributions",
    "Thesis jury": "teaching",
    "Outreach": "volunteering_languages",
    "Other": None,
}

CV_OUTPUT_FIELDS = ["kind", "title", "where", "date", "detail", "scale", "projects", "url"]


def load_cv_outputs():
    if not CV_OUTPUTS_PATH.exists():
        return {}
    try:
        return json.loads(CV_OUTPUTS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def export_cv_outputs_to_excel(all_outputs):
    """One row per output, every reporting period in a single sheet -- the same shape as the
    publications and beyond-projects mirrors."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "ADA outputs"
    ws.append(["Period", "Kind", "Title", "Where", "Date", "Detail", "Scale",
               "Related projects", "URL"])
    for period_label, entries in all_outputs.items():
        for entry in entries:
            ws.append([period_label] + [entry.get(f, "") for f in CV_OUTPUT_FIELDS])
    for col, width in zip("ABCDEFGHI", (18, 20, 50, 30, 14, 50, 18, 20, 40)):
        ws.column_dimensions[col].width = width
    wb.save(CV_OUTPUTS_XLSX_PATH)


def save_cv_outputs(all_outputs):
    """Write the JSON source of truth, then mirror to Excel. Same lock-tolerant contract as
    save_publications: a warning string back, never a lost edit."""
    CV_OUTPUTS_PATH.write_text(json.dumps(all_outputs, indent=2, ensure_ascii=False), encoding="utf-8")
    try:
        export_cv_outputs_to_excel(all_outputs)
    except PermissionError:
        return (f"Saved, but couldn't update {CV_OUTPUTS_XLSX_PATH.name} (close it in Excel to "
                "refresh the mirror on the next edit).")
    return None


def cv_outputs_flat(all_outputs, kinds=None, period_label=None):
    """Every logged output as one list, each row carrying the period it was logged under.
    `kinds` / `period_label` narrow it; newest date first, undated last."""
    rows = []
    for label, entries in (all_outputs or {}).items():
        if period_label and label != period_label:
            continue
        for entry in entries:
            if kinds and entry.get("kind") not in kinds:
                continue
            row = dict(entry)
            row["period"] = label
            rows.append(row)
    rows.sort(key=lambda r: str(r.get("date") or ""), reverse=True)
    return rows


def _match_key(*parts):
    """Loose equality for merging a logged output with its CV entry: case, spacing and
    punctuation differences shouldn't produce a duplicate line on the CV."""
    text = " ".join(str(p or "") for p in parts).lower()
    return re.sub(r"[^a-z0-9]+", "", text)


def _merge_cv_rows(cv_rows, ada_rows, key_fields):
    """Fold `ada_rows` (already converted into a CV section's own field names, each carrying
    `period` / `projects`) into that section's lifetime list. A row already on the CV is
    annotated rather than repeated -- the same title at the same venue is the same thing,
    however it got in -- and anything new is appended.

    Returns a new list and writes nothing: the merge exists for display, so each store stays
    the single source of truth for what it holds."""
    merged = [dict(r) for r in cv_rows]
    index = {_match_key(*(r.get(f) for f in key_fields)): r for r in merged}
    for row in ada_rows:
        key = _match_key(*(row.get(f) for f in key_fields))
        existing = index.get(key)
        if existing is not None:
            existing.update({k: v for k, v in row.items()
                             if k in ("period", "projects", "url") and v})
            existing["ada"] = True
        else:
            new_row = dict(row)
            new_row["ada"] = True
            merged.append(new_row)
            index[key] = new_row
    return merged


def cv_publications(cv, all_pubs):
    """The CV's lifetime publication list with the per-period ADA publications folded in --
    each tagged with its reporting period and the project tags it came out of, so the CV and
    the publications page can never disagree about what was published."""
    ada = []
    for pub in cv_outputs_flat(all_pubs):
        venue = str(pub.get("venue") or "")
        date = str(pub.get("date") or "")
        ada.append({
            "title": pub.get("title", ""), "venue": venue,
            "year": int(date[:4]) if date[:4].isdigit() else "",
            "type": "preprint" if "preprint" in venue.lower() else "article",
            "first_author": "", "doi": "", "url": pub.get("url", ""),
            "period": pub.get("period", ""), "projects": pub.get("projects", ""),
        })
    merged = _merge_cv_rows(cv.get("publications", []), ada, ["title"])
    merged.sort(key=lambda r: str(r.get("year") or ""), reverse=True)
    return merged


def cv_section_with_outputs(cv, section, all_outputs):
    """One CV section (courses, teaching, conference contributions, volunteering) with the
    ADA outputs belonging to it folded in, converted into that section's own field names."""
    kinds = [k for k, s in CV_OUTPUT_SECTION.items() if s == section]
    converted = []
    for row in cv_outputs_flat(all_outputs, kinds=kinds):
        common = {"period": row.get("period", ""), "projects": row.get("projects", ""),
                  "url": row.get("url", "")}
        if section == "courses_certifications":
            converted.append({"title": row.get("title", ""), "provider": row.get("where", ""),
                              "date": row.get("date", ""), "topics": row.get("detail", ""),
                              **common})
        elif section == "teaching":
            converted.append({"item": row.get("title", ""), "institution": row.get("where", ""),
                              "date": row.get("date", ""), "students": row.get("scale", ""),
                              "detail": row.get("detail", ""), **common})
        elif section == "conference_contributions":
            converted.append({"title": row.get("title", ""), "event": row.get("where", ""),
                              "date": row.get("date", ""),
                              "type": "poster" if row.get("kind") == "Conference poster" else "oral",
                              "note": row.get("detail", ""), **common})
        else:
            converted.append({"item": row.get("title", ""), "date": row.get("date", ""),
                              **common})

    key_fields = {"courses_certifications": ["title"], "teaching": ["item"],
                  "conference_contributions": ["title", "event"],
                  "volunteering_languages": ["item"]}[section]
    merged = _merge_cv_rows(cv.get(section, []), converted, key_fields)
    merged.sort(key=lambda r: str(r.get("date") or ""), reverse=True)
    return merged


# --- Shapes for the table editors ----------------------------------------------------------
def table_frame(rows, columns):
    """A DataFrame for st.data_editor with one column per field, typed from what the rows
    actually hold: a column whose values are all booleans stays boolean (so a tick box keeps
    working and never round-trips into the string "False", which is truthy), an all-numeric
    one stays numeric, and everything else is text.

    Lives here rather than in a page because it is plain pandas -- no Streamlit -- and
    because a page editing a list-of-dict store needs both halves of the round trip."""
    frame = pd.DataFrame([{c: row.get(c, "") for c in columns} for row in rows], columns=columns)
    for col in columns:
        values = [v for v in frame[col] if v not in ("", None) and not _is_blank(v)]
        if values and all(isinstance(v, bool) for v in values):
            frame[col] = frame[col].apply(bool)
        elif values and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in values):
            frame[col] = pd.to_numeric(frame[col], errors="coerce")
        else:
            frame[col] = frame[col].apply(lambda v: "" if _is_blank(v) else str(v))
    return frame


def _is_blank(value):
    return value is None or (isinstance(value, float) and pd.isna(value))


def table_rows(frame, columns, required=None):
    """`table_frame`'s inverse: back to a list of dicts, dropping rows left entirely blank
    (st.data_editor's dynamic mode always leaves one at the end) and any row with nothing in
    the column that identifies it. Numbers come back as ints where they are whole, so the
    JSON doesn't fill up with 2026.0."""
    required = required or (columns[0] if columns else None)
    rows = []
    for record in frame.to_dict("records"):
        row = {}
        for col in columns:
            value = record.get(col, "")
            if _is_blank(value):
                value = ""
            elif isinstance(value, bool):
                pass
            elif isinstance(value, (int, float)):
                value = int(value) if float(value).is_integer() else float(value)
            else:
                value = str(value).strip()
            row[col] = value
        if required and not str(row.get(required, "")).strip():
            continue
        rows.append(row)
    return rows


# --- Output counts -------------------------------------------------------------------------
# A CV's conference list is usually "the ones worth naming, plus N more" -- cv_data.json keeps
# that as one row with note "count only" and the number in its title. Counting rows would
# quietly under-report by 13, so the number is read out of the row instead, in the one place
# both the tiles and the chart ask.
def rollup_count(row):
    """How many contributions a row actually stands for: 1, unless it is a 'count only'
    roll-up, in which case the first number in its title."""
    if str(row.get("note", "")).strip().lower() != "count only":
        return 1
    match = re.search(r"\d+", str(row.get("title", "")))
    return int(match.group()) if match else 1


def cv_output_counts(publications, conferences):
    """The headline output numbers, counted from the lists themselves so they move when a new
    paper or poster is logged instead of being retyped into the CV."""
    pubs = list(publications or [])
    papers = [p for p in pubs if str(p.get("type", "article")).lower() != "preprint"]
    confs = list(conferences or [])
    posters = sum(rollup_count(c) for c in confs
                  if str(c.get("type", "")).lower() not in ("oral", "talk"))
    talks = sum(rollup_count(c) for c in confs
                if str(c.get("type", "")).lower() in ("oral", "talk"))
    return {
        "papers": len(papers),
        "first_author": sum(1 for p in papers if p.get("first_author")),
        "preprints": len(pubs) - len(papers),
        "posters": posters, "talks": talks, "contributions": posters + talks,
    }


# --- The CV's "current role" numbers, read live from the tracker ---------------------------
def _period_key_from_text(value):
    """The tools inventory's own 'Built in' spelling -> the label discover_periods uses, so
    the two join: '2025/2026' or '2025-2026' -> '2025–2026' (en dash), and a single '2025' ->
    '2025'. Both spellings matter -- a reporting period that runs on a fiscal year is written
    with two years, one that runs on the calendar with one."""
    years = re.findall(r"\d{4}", str(value or ""))
    if len(years) >= 2:
        return f"{years[0]}–{years[1]}"
    return years[0] if years else ""


def tools_built_by_period(tools_df):
    """period label -> names of the tools built in it. Deprecated tools are left out, the
    same call the Tools page's own counts make: a retired tool isn't something the service
    has."""
    built = {}
    if tools_df is None or not len(tools_df):
        return built
    status = tools_df.get("Status", pd.Series("", index=tools_df.index)).astype(str).str.strip()
    for _, row in tools_df[status != "Deprecated"].iterrows():
        label = _period_key_from_text(row.get("Built in"))
        if label:
            built.setdefault(label, []).append(str(row.get("Name", "")).strip())
    return built


def cv_role_metrics(periods, load_projects_fn=load_projects, load_meetings_fn=load_meetings,
                    tools_df=None, timelog=None, pause_notes=None, all_pubs=None,
                    all_outputs=None):
    """Everything the CV says about the current role, computed from the live files instead
    of being retyped into the CV: one entry per reporting period, plus the across-period
    totals the headline stats quote.

    Nothing here is stored. The CV's own cv_stats section deliberately holds no service numbers
    (its README says as much) -- those are exactly the figures that go stale in a written CV,
    so the page renders them from this and the CV store never gets a copy that can drift.

    Never raises on a period: a workbook that's locked or malformed is skipped, the same
    tolerance build_project_lookup takes, so one bad file can't blank the page."""
    per_period, groups_all, last_activity = [], set(), None
    tools_by_period = tools_built_by_period(tools_df)

    for period in periods:
        try:
            projects = load_projects_fn(period["file"], period["sheet"])
            meetings = load_meetings_fn(period["file"], period["meetings_sheet"])
        except Exception:
            continue

        df_period = filter_to_period(timelog, period) if timelog is not None else None
        glance = year_at_a_glance(projects, meetings, df_period)
        lead_df = lead_time_table(projects, df_period, period_end=period["end"],
                                  pause_notes=pause_notes)
        stats = lead_time_summary(lead_df)

        trigger = projects.get("Project Trigger", pd.Series(dtype=str)).astype(str).str.strip()
        delivered = (int(projects["Final Report Sent"].notna().sum())
                     if "Final Report Sent" in projects.columns else 0)
        groups = set(projects.get("Grupo", pd.Series(dtype=str)).dropna()) - {"ADA"}
        groups |= set(meetings.get("Grupo", pd.Series(dtype=str)).dropna()) - {"ADA"}
        groups_all |= groups

        # "Data as of" = the newest tracker date that has actually happened. Capped at today
        # on purpose: a Closing Day can be booked ahead (the bureaucratic close of a project
        # already delivered), and a CV stamped with a date in the future reads as a mistake.
        today = pd.Timestamp.now().normalize()
        for col in DATE_COLS:
            if col in projects.columns and projects[col].notna().any():
                newest = projects.loc[projects[col] <= today, col].max()
                if pd.notna(newest):
                    last_activity = newest if last_activity is None else max(last_activity, newest)

        per_period.append({
            "label": period["label"], "start": period["start"], "end": period["end"],
            "projects_total": glance["projects_total"],
            "active": glance["projects_active"], "concluded": glance["projects_concluded"],
            "delivered": delivered,
            "consulting": int((trigger == "Consulting").sum()),
            "meetings": glance["meetings_total"],
            "groups": len(groups),
            "hours": glance["total_hours"],
            # Two different questions, both asked of the CV: "how long until I get my
            # results" (working -- data in hand to final report, the figure the CV quotes as
            # time to deliver) and "how long from my first email" (total, which includes the
            # queue). Kept apart rather than blended into one number.
            "median_working_days": stats["median_working"],
            "median_total_days": stats["median_total"],
            "median_waiting_days": stats["median_waiting"],
            "delivered_measured": stats["n_delivered"],
            "bands": turnaround_by_size(lead_df),
            "tools": sorted(tools_by_period.get(period["label"], [])),
            "publications": len((all_pubs or {}).get(period["label"], [])),
            "outputs": cv_outputs_flat(all_outputs, period_label=period["label"]),
        })

    totals = {
        "periods": len(per_period),
        "projects_total": sum(p["projects_total"] for p in per_period),
        "delivered": sum(p["delivered"] for p in per_period),
        "consulting": sum(p["consulting"] for p in per_period),
        "meetings": sum(p["meetings"] for p in per_period),
        "groups": len(groups_all),
        "tools": sum(len(names) for names in tools_by_period.values()),
        "publications": sum(p["publications"] for p in per_period),
        "outputs": sum(len(p["outputs"]) for p in per_period),
        "since": min((p["start"] for p in per_period), default=None),
        "as_of": last_activity,
    }
    return {"periods": per_period, "totals": totals}


def cv_html_with_live_metrics(metrics, src=None):
    """A hand-built standalone CV page (Data/CV_dashboard.html, if one is there) with its live
    figures filled in from `cv_role_metrics`. That file already marks them -- every number
    the dashboard owns is a `data-metric` span, read at load time out of a JSON block the
    page carries -- so refreshing it means rewriting that one block, not the page.

    Returns the HTML text for the caller to offer as a download. A copy with no metrics block
    (an older or hand-trimmed page) comes back unchanged rather than failing: the page is
    still perfectly valid, it just has nothing live in it."""
    src = Path(src or CV_HTML_PATH)
    html = src.read_text(encoding="utf-8")
    totals = metrics["totals"]
    as_of = totals.get("as_of")
    # These keys are a contract with the CV page itself: each one has to match a
    # `data-metric="..."` attribute in Data/CV_dashboard.html, or that number simply never
    # gets filled in (silently -- the page stays valid either way). Rename one here and you
    # must rename it there in the same commit.
    live = {
        "org_deliverables_total": totals["delivered"],
        "org_projects_total": totals["projects_total"],
        "org_tools_total": totals["tools"],
        "org_updated": pd.Timestamp(as_of).strftime("%d %b %Y") if as_of is not None else "",
    }
    block = json.dumps(live, ensure_ascii=False)
    updated, n = re.subn(
        r'(<script type="application/json" id="cv-metrics">).*?(</script>)',
        lambda m: m.group(1) + block + m.group(2), html, count=1, flags=re.DOTALL,
    )
    return updated if n else html


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
    a glance' cards so both report the same total.

    Only tags the PROJECT TRACKER has registered count. The time log's Project column is not
    a list of projects -- it is where every hour goes, projects and non-projects alike (org
    and admin time, consulting, training, seminars, personal-organisation work), plus the
    occasional mistagged entry that was never registered anywhere. Those are real work and
    they belong in the Week/Month/Year hour views; they are not projects, and a bar for one
    of them sitting in "Hours by project" said they were. This is the same rule "Projects
    touched" and "Active/concluded" already use -- deliberately the rule rather than a list
    of bucket names to exclude, which is what the previous hardcoded trio had become: it went
    stale the moment a new bucket was added, and silently let it through."""
    registered = {str(t).strip() for t in projects["Project tag"] if str(t).strip()}
    timesheet_hours = pd.to_numeric(projects.get("Hours in Timesheet"), errors="coerce").fillna(0).clip(lower=0)
    timesheet_hours.index = [str(t).strip() for t in projects["Project tag"]]

    timelog_hours = pd.Series(dtype=float)
    if df_period is not None and len(df_period):
        logged = df_period.copy()
        logged["Project"] = logged["Project"].astype(str).str.strip()
        timelog_hours = (
            logged[logged["Project"].isin(registered)]
            .groupby("Project")["Hours (exact)"].sum()
        )

    hours, source = {}, {}
    for tag in sorted(registered):
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
                gaps.append({"start": prev + pd.Timedelta(7, "D"),
                             "end": nxt - pd.Timedelta(1, "D"), "weeks": missing})
        activity[str(project)] = {
            "first": weeks[0], "last_end": weeks[-1] + pd.Timedelta(6, "D"),
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

    `pause_notes` (from load_pause_notes: {project: {week-key: {"note", "forgive_working",
    "forgive_total"}}}) lets any individual pause be excused from either median
    independently, without excusing the whole project: "forgive_working" subtracts its days
    from `working_days_counted` alone (Typical time to deliver / effective working time),
    "forgive_total" subtracts them from the working-portion of `total_days_counted` alone
    (Typical total turnaround to user) -- a pause can be forgiven from one, the other,
    both, or neither. Each gap is split week by week (see gap_weeks) before this lookup, so
    a multi-week pause can have one week forgiven and the next not: every week carries its
    own note and its own two forgive flags, under its own `pause_key`.
    `working_days_counted` and `total_days_counted` are what
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
                gaps.append({"start": act["last_end"] + pd.Timedelta(1, "D"),
                             "end": work_end, "weeks": trailing_weeks})

        # A multi-week pause is forgiven week by week, not as a single all-or-nothing block
        # (see gap_weeks): each week gets its own note/forgive_working/forgive_total looked
        # up under its own pause_key, so one week of a two-week pause can be forgiven while
        # the other isn't. A 1-week gap's single week is identical to the gap itself, so the
        # common case (PAUSE_MIN_WEEKS == 1) is unaffected.
        tag_notes = pause_notes.get(tag, {})
        forgiven_days_working = forgiven_days_total = 0
        for g in gaps:
            weeks_detail = gap_weeks(g)
            for w in weeks_detail:
                note = tag_notes.get(pause_key(w), {})
                w["note"] = note.get("note", "")
                w["forgiven_working"] = bool(note.get("forgive_working"))
                w["forgiven_total"] = bool(note.get("forgive_total"))
                w["forgiven"] = w["forgiven_working"] or w["forgiven_total"]
                week_days = (w["end"] - w["start"]).days + 1
                if w["forgiven_working"]:
                    forgiven_days_working += week_days
                if w["forgiven_total"]:
                    forgiven_days_total += week_days
            g["weeks_detail"] = weeks_detail
            # Gap-level flags for anything that still wants the whole pause at once: "fully
            # forgiven" only when every week in it is, "any forgiven" when at least one is.
            g["forgiven_working"] = all(w["forgiven_working"] for w in weeks_detail)
            g["forgiven_total"] = all(w["forgiven_total"] for w in weeks_detail)
            g["forgiven"] = any(w["forgiven"] for w in weeks_detail)
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
            "weeks_paused": sum(1 for g in gaps for w in g["weeks_detail"] if not w["forgiven"]),
            "gaps": gaps,
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


def pause_key(week):
    """Stable id for one empty week -- of a single-week pause, or of one week inside a
    multi-week one (see gap_weeks). The same week keeps the same key across reruns as long
    as the surrounding logged weeks don't change."""
    return week["start"].date().isoformat()


def gap_weeks(gap):
    """Split a detected pause into its individual 7-day weeks, each independently forgivable
    -- so a 2-week pause can have its first week forgiven and the second not, rather than
    being an all-or-nothing block. A 1-week gap (the common case, since PAUSE_MIN_WEEKS == 1)
    returns a single week identical to the gap itself, so nothing changes for it."""
    weeks = []
    for i in range(gap["weeks"]):
        week_start = gap["start"] + pd.Timedelta(7 * i, "D")
        week_end = min(week_start + pd.Timedelta(6, "D"), gap["end"])
        weeks.append({"start": week_start, "end": week_end})
    return weeks


def load_pause_notes():
    """{project: {week-start ISO date: {"note": str, "forgive_working": bool,
    "forgive_total": bool}}} -- one entry per individual empty week (see gap_weeks), not per
    whole pause, so a multi-week pause can have some weeks forgiven and others not. Also
    reads the two older formats so nothing written under
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
    forgiven_days = (int(sum((w["end"] - w["start"]).days + 1
                              for gaps in lead_df["gaps"] for g in (gaps or [])
                              for w in g.get("weeks_detail", []) if w.get("forgiven")))
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


# ============================================================================================
# TIME TRACKER -- Data/time_entries.csv
# ============================================================================================
# A second, finer-grained store sitting *under* the time log: one row per stretch of work
# with a real start and end timestamp, the way a stopwatch app records it. track_time.csv
# stays what it has always been -- one row per (project, category, major task) per week --
# and the tracker folds a week's stretches into exactly that shape when you push it
# (timelog_push_preview / apply_timelog_push). Nothing here writes the time log by itself:
# the push is an explicit, previewed step, and the Week editor keeps the last word.
#
# Times are stored as naive local ISO text ("2026-11-27T09:35:00") because every consumer
# here is local wall clock: the calendar grid, the weekly rollup and the reporting weeks all
# mean "the hour it said on the clock", which is what a time sheet records.

TIME_ENTRIES_PATH = DATA_DIR / "time_entries.csv"

TIME_ENTRY_COLS = [
    "id", "start", "end", "project", "category", "major_task", "description", "notes",
]

# Tracker field -> the track_time.csv column it folds into. These three are also the key a
# week's entries are rolled up on, and the key a proposed row is matched against the log on.
TRACKER_TO_TIMELOG = {
    "project": "Weekly entry name (chart)",
    "category": "Category",
    "major_task": "Major task name (chart)",
}
ROLLUP_KEYS = list(TRACKER_TO_TIMELOG)
# The same five columns under the names load_timelog's PARSED frame uses: it renames
# "Weekly entry name (chart)" to "Project" and leaves the other four alone. Matching reads
# the parsed frame (renamed major tasks, stripped blanks); writing targets the raw one.
TRACKER_TO_PARSED = dict(TRACKER_TO_TIMELOG, project="Project")

# What a block shorter than this is drawn as on the calendar. A 2-minute entry is a real
# entry -- it just has no height to speak of, and a block you cannot see or hover is the
# same as a lost one. Only the drawn height is floored; `hours` stays exact everywhere.
MIN_DRAWN_MINUTES = 7


def iso_stamp(ts):
    """A Timestamp -> the text the store holds. Seconds precision: the file is read by
    people too, and a tracker that logs microseconds is logging noise."""
    return pd.Timestamp(ts).strftime("%Y-%m-%dT%H:%M:%S")


def new_entry_id():
    return f"te_{uuid.uuid4().hex[:12]}"


def load_time_entries():
    """Read time_entries.csv -> a frame with TIME_ENTRY_COLS plus the derived `start_dt`,
    `end_dt`, `running`, `hours`, `date` and `week_start` (that day's Monday), sorted
    oldest-first. A missing file is an empty tracker, not an error -- the page has to work
    on the day it is first opened -- and a row with no parseable start is dropped, since
    there is nothing a timeline could do with it."""
    if TIME_ENTRIES_PATH.exists():
        raw = pd.read_csv(TIME_ENTRIES_PATH, sep=";", encoding="utf-8-sig", dtype=str)
    else:
        raw = pd.DataFrame(columns=TIME_ENTRY_COLS)
    for col in TIME_ENTRY_COLS:
        if col not in raw.columns:
            raw[col] = ""
    df = raw[TIME_ENTRY_COLS].copy()
    for col in TIME_ENTRY_COLS:
        df[col] = df[col].fillna("").astype(str).str.strip()

    df["start_dt"] = pd.to_datetime(df["start"], errors="coerce")
    df["end_dt"] = pd.to_datetime(df["end"], errors="coerce")
    df = df[df["start_dt"].notna()].copy()

    # A blank end means "still running", which is a state, not a duration -- it contributes
    # 0 hours to every sum until it is stopped. (The calendar draws it up to `now` instead;
    # see entry_segments.) A negative span can only come from a hand-edited file, and is
    # clamped rather than left to quietly subtract hours from a week's total.
    df["running"] = df["end_dt"].isna()
    df["hours"] = (df["end_dt"] - df["start_dt"]).dt.total_seconds() / 3600
    df["hours"] = pd.to_numeric(df["hours"], errors="coerce").fillna(0.0).clip(lower=0.0)

    df["date"] = df["start_dt"].dt.normalize()
    df["week_start"] = df["date"] - pd.to_timedelta(df["start_dt"].dt.weekday, unit="D")
    return df.sort_values("start_dt", kind="stable").reset_index(drop=True)


def save_time_entries(df):
    """Write the tracker store, dropping the derived columns load_time_entries adds. Raises
    PermissionError if the file is open elsewhere, same as every other save here."""
    out = df.copy()
    for col in TIME_ENTRY_COLS:
        if col not in out.columns:
            out[col] = ""
    out[TIME_ENTRY_COLS].to_csv(TIME_ENTRIES_PATH, sep=";", index=False, encoding="utf-8-sig")


def _stored(entries):
    """Just the columns the file holds, dropping the derived ones load_time_entries adds.

    Everything that appends a row concatenates onto this rather than onto the loaded frame:
    concatenating a plain dict-frame onto one carrying datetime64 columns makes pandas
    invent an NaT for them, which it builds with NumPy's deprecated "generic" timedelta unit
    and warns about every single time. Nothing wants those columns in the result anyway --
    save_time_entries would drop them -- so they are gone before the concat, not after."""
    out = entries.copy()
    for col in TIME_ENTRY_COLS:
        if col not in out.columns:
            out[col] = ""
    return out[TIME_ENTRY_COLS]


def _is_running(entries):
    """Running-ness read off the stored `end` column rather than the derived `running` one,
    so these helpers also work on a frame rebuilt by hand (the editor's save path) that
    never went through load_time_entries."""
    return entries["end"].fillna("").astype(str).str.strip() == ""


def running_entry(entries):
    """The entry still running, or None. If several are somehow running at once -- two
    browser tabs, a hand-edited file -- the most recently started one wins: it is the one
    the Start button would have just created."""
    live = entries[_is_running(entries)]
    if live.empty:
        return None
    return live.sort_values("start", kind="stable").iloc[-1]


def stop_entry(entries, now, entry_id=None):
    """Close the running entry (or `entry_id`) at `now`. Returns the updated frame; a frame
    with nothing running comes back unchanged. The end is never written before the start --
    a clock change, or a start hand-edited into the future, would otherwise store a negative
    span that every later sum silently eats."""
    out = entries.copy()
    mask = _is_running(out) if entry_id is None else (out["id"] == entry_id)
    for idx in out.index[mask]:
        start = pd.to_datetime(out.loc[idx, "start"], errors="coerce")
        end = pd.Timestamp(now)
        if pd.notna(start) and end < start:
            end = start
        out.loc[idx, "end"] = iso_stamp(end)
    return out


def start_entry(entries, now, **fields):
    """Append a new running entry starting at `now`, after stopping whatever was running --
    one timer at a time, the way a stopwatch works. `fields` are any of the TIME_ENTRY_COLS
    text fields (project, category, major_task, description, tool, special_project, notes).
    Returns the updated frame, ready for save_time_entries."""
    out = stop_entry(entries, now)
    row = {col: "" for col in TIME_ENTRY_COLS}
    row.update({k: str(v or "").strip() for k, v in fields.items() if k in TIME_ENTRY_COLS})
    row["id"] = new_entry_id()
    row["start"] = iso_stamp(now)
    row["end"] = ""
    return pd.concat([_stored(out), pd.DataFrame([row], columns=TIME_ENTRY_COLS)],
                     ignore_index=True)


def add_entry(entries, start, end, **fields):
    """Append a finished entry spanning `start`..`end` (the by-hand form, and the editor's
    blank rows). An end at or before the start is read as crossing midnight and pushed to
    the next day -- "22:30 to 00:15" is the one way a day's last entry gets typed."""
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    if end <= start:
        end = end + pd.Timedelta(1, "D")
    row = {col: "" for col in TIME_ENTRY_COLS}
    row.update({k: str(v or "").strip() for k, v in fields.items() if k in TIME_ENTRY_COLS})
    row["id"] = fields.get("id") or new_entry_id()
    row["start"], row["end"] = iso_stamp(start), iso_stamp(end)
    return pd.concat([_stored(entries), pd.DataFrame([row], columns=TIME_ENTRY_COLS)],
                     ignore_index=True)


def delete_entries(entries, ids):
    return entries[~entries["id"].isin(list(ids))].copy()


def split_entry(entries, entry_id, stretches, keep_running=False):
    """Replace one entry with one entry per (start, end) in `stretches` -- what is left of a
    tracked stretch once the time away from the machine is cut out of it.

    It has to become several entries rather than one shorter one, because a stretch with its
    middle removed is two pieces of work and there is nowhere in an entry to record a hole.
    Every piece keeps the original's tags and description; the first keeps its id too, so an
    entry that only had time trimmed off its end keeps its identity.

    `keep_running` leaves the last piece open -- the "I'm back at my desk, carry on" case.
    No stretches at all means nothing survived (she walked away immediately), and the entry
    is removed. Returns the updated frame."""
    out = entries.copy()
    match = out[out["id"] == entry_id]
    if match.empty:
        return out

    template = {col: match.iloc[0].get(col, "") for col in TIME_ENTRY_COLS}
    out = out[out["id"] != entry_id]
    stretches = [(pd.Timestamp(a), pd.Timestamp(b)) for a, b in stretches
                 if pd.Timestamp(b) > pd.Timestamp(a)]

    rows = []
    for i, (start, end) in enumerate(stretches):
        row = dict(template)
        row["id"] = entry_id if i == 0 else new_entry_id()
        row["start"] = iso_stamp(start)
        row["end"] = "" if (keep_running and i == len(stretches) - 1) else iso_stamp(end)
        rows.append(row)
    if rows:
        out = pd.concat([_stored(out), pd.DataFrame(rows, columns=TIME_ENTRY_COLS)],
                        ignore_index=True)
    return out


def week_start_of(day):
    """The Monday of `day`'s week -- the same Monday-start weeks the time log's own
    '3rd November' labels resolve to (week_bounds / ordinal_week_label)."""
    day = pd.Timestamp(day).normalize()
    return day - pd.Timedelta(int(day.weekday()), "D")


def entry_segments(entries, week_start, now=None):
    """One drawable block per (entry, day) for the week beginning `week_start`.

    An entry running past midnight is cut at the day boundary and drawn once in each day it
    touches: a single block spanning two columns is not something a calendar grid can draw,
    and splitting it is also what makes a Sunday-night-into-Monday stretch land its hours in
    the right week when the week is pushed to the time log.

    The still-running entry is drawn up to `now`, so the calendar shows what is happening
    right now. Pass `now=None` to leave it out entirely -- which is what the push does: time
    that has not stopped yet is not time you can report.

    Returns a frame with every TIME_ENTRY_COL plus `day` (0 = Monday), `start_min`/`end_min`
    (minutes from that day's midnight), `hours`, `running`, and the `lane`/`lanes` that
    pack_lanes assigns."""
    cols = TIME_ENTRY_COLS + ["day", "start_min", "end_min", "hours", "running"]
    week_start = pd.Timestamp(week_start).normalize()
    week_end = week_start + pd.Timedelta(7, "D")

    rows = []
    for _, e in entries.iterrows():
        start = pd.to_datetime(e.get("start"), errors="coerce")
        end = pd.to_datetime(e.get("end"), errors="coerce")
        running = bool(pd.isna(end))
        if pd.isna(start):
            continue
        if running:
            if now is None:
                continue
            end = max(pd.Timestamp(now), start)
        if end <= week_start or start >= week_end:
            continue
        seg_start, seg_end = max(start, week_start), min(end, week_end)

        day = seg_start.normalize()
        while day < seg_end:
            nxt = day + pd.Timedelta(1, "D")
            a, b = max(seg_start, day), min(seg_end, nxt)
            if b > a:
                rows.append({
                    **{c: e.get(c, "") for c in TIME_ENTRY_COLS},
                    "day": int((day - week_start).days),
                    "start_min": (a - day).total_seconds() / 60,
                    "end_min": (b - day).total_seconds() / 60,
                    "hours": (b - a).total_seconds() / 3600,
                    "running": running,
                })
            day = nxt

    segments = pd.DataFrame(rows, columns=cols)
    return pack_lanes(segments)


def pack_lanes(segments):
    """Side-by-side lanes for blocks that overlap within the same day, the way a calendar
    app lays out a double-booked hour. A block overlapping nothing keeps the whole column
    (`lanes` = 1); a run of mutually-overlapping blocks splits its column `lanes` ways and
    each takes `lane`. Clusters are per day and chained -- A overlapping B and B overlapping
    C puts all three in one cluster even when A and C don't touch, which is what keeps every
    block in the group the same width instead of two of them sharing an edge."""
    segments = segments.copy()
    segments["lane"] = 0
    segments["lanes"] = 1
    if segments.empty:
        return segments

    for _day, day_rows in segments.groupby("day", sort=False):
        order = day_rows.sort_values(["start_min", "end_min"], kind="stable").index
        cluster, lane_ends, cluster_end = [], [], None
        for idx in order:
            start = segments.loc[idx, "start_min"]
            # Packed against the DRAWN height, not the true one: two 1-minute entries a
            # minute apart don't overlap in the data but do once both are floored to
            # MIN_DRAWN_MINUTES, and lanes exist to stop drawn blocks covering each other.
            end = max(segments.loc[idx, "end_min"], start + MIN_DRAWN_MINUTES)
            if cluster_end is not None and start >= cluster_end:
                segments.loc[cluster, "lanes"] = len(lane_ends)
                cluster, lane_ends, cluster_end = [], [], None
            lane = next((k for k, free_at in enumerate(lane_ends) if start >= free_at),
                        len(lane_ends))
            if lane == len(lane_ends):
                lane_ends.append(end)
            else:
                lane_ends[lane] = end
            segments.loc[idx, "lane"] = lane
            cluster.append(idx)
            cluster_end = end if cluster_end is None else max(cluster_end, end)
        segments.loc[cluster, "lanes"] = len(lane_ends)

    return segments


def _group_label(value):
    """A blank project/task/tool cell is a real state (an entry started before it was
    labelled), so it groups under one visible name instead of vanishing into an empty row."""
    text = str(value or "").strip()
    return text if text and text.lower() != "nan" else "(unlabelled)"


def day_row(frame):
    """Hours per weekday (Monday first) for a frame of segments -- the row the breakdown
    grid draws, and the same split the push preview shows against each proposed time-log
    row. Shared so the two can never disagree about which day an hour landed on."""
    by_day = frame.groupby("day")["hours"].sum()
    return [float(by_day.get(d, 0.0)) for d in range(7)]


def tracker_breakdown(segments, level1, level2=None):
    """The week's hours as the two-level day grid the breakdown table draws.

    `level1`/`level2` are tracker field names ("project", "category", "major_task", "tool",
    "special_project", "description"). Returns
    {"groups": [{"label", "total", "days": [7 floats], "children": [same, minus children]}],
     "day_totals": [7 floats], "total": float} -- groups and children both ordered by hours
    descending, so the week reads top-down as where the time actually went.

    A still-running block counts the time it has run so far (whatever `now` entry_segments
    was given), which is why the breakdown and the calendar always agree."""
    if segments.empty:
        return {"groups": [], "day_totals": [0.0] * 7, "total": 0.0}

    df = segments.copy()
    df["_l1"] = df[level1].map(_group_label)
    if level2:
        df["_l2"] = df[level2].map(_group_label)

    groups = []
    for label, rows in df.groupby("_l1", sort=False):
        children = []
        if level2:
            for sub_label, sub_rows in rows.groupby("_l2", sort=False):
                children.append({"label": sub_label, "total": float(sub_rows["hours"].sum()),
                                 "days": day_row(sub_rows)})
            children.sort(key=lambda c: -c["total"])
        groups.append({"label": label, "total": float(rows["hours"].sum()),
                       "days": day_row(rows), "children": children})
    groups.sort(key=lambda g: -g["total"])

    return {"groups": groups, "day_totals": day_row(df), "total": float(df["hours"].sum())}


def _key_text(value):
    return str(value or "").strip()


def timelog_push_preview(timelog_df, timelog_raw, segments, week_start):
    """What pushing this tracker week into track_time.csv would do, row by row.

    The week's blocks are folded into one proposed row per
    (project, category, major task) -- the shape the time log
    already has -- and each is matched against that same week's existing rows on the same
    three values. Matching reads the *parsed* log (`timelog_df`), so a row still carrying a
    renamed major task ("AI Agent" -> "AI Skills") still matches the tracker's current name;
    writing targets `timelog_raw`, which is the frame that goes back to disk.

    Each returned dict carries the three key fields, `hours` / `hrs` / `min`, `descriptions`
    (what was typed against those blocks), `current_hours` / `current_timesheet` /
    `current_notes` (what the log holds now -- None/"" when nothing matches, so a push can
    offer back the Timesheet flag and the note that are already there instead of resetting
    them), `row_index` (the raw_df label to overwrite, None for a new row) and `status`:
      "new"       -- nothing in the log for this combination yet
      "changed"   -- the log has it, with different hours
      "same"      -- the log already agrees, to the minute
      "duplicate" -- the week holds more than one row for this combination, so there is no
                     single row to update. Left for you to merge in the Week editor rather
                     than guessed at.
    A still-running entry is excluded: time that has not stopped yet is not time you can
    report. Rows the log has and the tracker doesn't are never touched or reported either --
    time typed straight into the Week editor is just as real as time that went through a
    stopwatch, and the push is not a mirror."""
    week_start = pd.Timestamp(week_start).normalize()
    finished = segments[~segments["running"].astype(bool)] if len(segments) else segments

    existing = {}
    if len(timelog_df):
        for idx in timelog_df.index[timelog_df["_week_sort"] == week_start]:
            key = tuple(_key_text(timelog_df.loc[idx, col]) for col in TRACKER_TO_PARSED.values())
            existing.setdefault(key, []).append(idx)

    proposals = []
    if len(finished):
        grouped = finished.groupby([finished[k].map(_key_text) for k in ROLLUP_KEYS], sort=False)
        for key, rows in grouped:
            key = tuple(key) if isinstance(key, tuple) else (key,)
            hours = float(rows["hours"].sum())
            hrs, mins = split_hm(hours)
            matches = existing.get(key, [])
            timesheet, notes = "", ""
            if len(matches) > 1:
                status, row_index, current = "duplicate", None, None
            elif matches:
                row_index = matches[0]
                current = pd.to_numeric(timelog_df.loc[row_index, "Hours (exact)"], errors="coerce")
                current = 0.0 if pd.isna(current) else float(current)
                status = "same" if split_hm(current) == (hrs, mins) else "changed"
                timesheet = _key_text(timelog_raw.loc[row_index, "Timesheet updated"])
                notes = _key_text(timelog_raw.loc[row_index, "Notes"])
            else:
                status, row_index, current = "new", None, None
            descriptions = [d for d in dict.fromkeys(rows["description"].map(_key_text)) if d]
            fields = dict(zip(ROLLUP_KEYS, key))
            proposals.append({
                **fields,
                "hours": hours, "hrs": hrs, "min": mins,
                # Which days these hours came off, split by the breakdown's own function.
                # A row proposed for the time log is only checkable if you can see where it
                # came from, and "where" for a weekly row means which days.
                "days": day_row(rows),
                "descriptions": descriptions, "current_hours": current,
                "current_timesheet": timesheet, "current_notes": notes,
                "row_index": row_index, "status": status,
                # The Week editor holds back a new row with a blank Category or Major task
                # (apply_week_edits), because every chart that colours by category assumes
                # neither is ever blank. The push has to respect the same rule, so it marks
                # such a proposal rather than writing a half-filled row by the back door.
                # It is a flag, not a refusal: the caller can still send one deliberately.
                "unfiled": not all(fields[k] for k in ("project", "category", "major_task")),
            })
    proposals.sort(key=lambda p: (p["status"] == "same", -p["hours"]))
    return proposals


def apply_timelog_push(timelog_raw, proposals, week_start):
    """Write the accepted proposals into the raw time-log frame: a matched row has its
    Hrs / Min / Hours (exact) (and Timesheet / Notes, when given) overwritten in place; an
    unmatched one is appended as a new row for that week. Every other row in the file --
    including the week's rows the tracker knows nothing about -- is left exactly as it was.
    A "duplicate" proposal has no single row to write to and is skipped here too, so
    accepting one by mistake cannot pick a row at random.
    Returns (updated frame, rows updated, rows appended)."""
    week_start = pd.Timestamp(week_start).normalize()
    out = timelog_raw.copy()
    n_updated, to_add = 0, []

    for p in proposals:
        if p.get("status") == "duplicate":
            continue
        hrs, mins = int(p["hrs"]), int(p["min"])
        idx = p.get("row_index")
        if idx is not None and idx in out.index:
            out.loc[idx, "Hrs"] = hrs
            out.loc[idx, "Min"] = mins
            out.loc[idx, "Hours (exact)"] = hrs + mins / 60
            if p.get("timesheet"):
                out.loc[idx, "Timesheet updated"] = p["timesheet"]
            if p.get("notes") is not None:
                out.loc[idx, "Notes"] = p["notes"]
            n_updated += 1
        else:
            to_add.append(new_timelog_row(
                week_start, project=p.get("project", ""), category=p.get("category", ""),
                major_task=p.get("major_task", ""), hrs=hrs, mins=mins,
                timesheet=p.get("timesheet", "No"), notes=p.get("notes", "") or "",
            ))

    if to_add:
        out = pd.concat([out, pd.DataFrame(to_add)], ignore_index=True)
    return out, n_updated, len(to_add)


def tag_options(timelog_df, custom_tags, category_order=()):
    """The three dropdown vocabularies the Week editor and the time tracker share: every
    tag already used in the time log, plus the ones typed up front into custom_tags.json.

    Categories come back in `category_order` -- the palette's own order, so the dropdown
    reads the way the charts do -- with anything outside it sorted on the end; the other four
    two are sorted. Returns {"projects", "categories", "major_tasks"}."""
    def used(col):
        if col not in getattr(timelog_df, "columns", []):
            return set()
        return {str(v).strip() for v in timelog_df[col].dropna().unique() if str(v).strip()}

    projects = used("Project") | used("Weekly entry name (chart)")
    categories = used("Category") | set(custom_tags.get("categories", []))
    major_tasks = used("Major task name (chart)")

    ordered_categories = [c for c in category_order if c in categories]
    ordered_categories += sorted(categories - set(ordered_categories))
    return {
        "projects": sorted(projects | set(custom_tags.get("projects", []))),
        "categories": ordered_categories,
        "major_tasks": sorted(major_tasks | set(custom_tags.get("major_tasks", []))),
    }
