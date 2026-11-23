"""Generate every fake data file this demo dashboard needs, under Data/.

Everything here is INVENTED: project tags, group names, dates, hours, ratings, tools --
nothing is copied or derived from any real KPI tracker. Shapes (columns, sheet names,
JSON structure) match what Dashboard/kpi_data.py actually reads, so the dashboard opens
with a full year of realistic-looking activity rather than an empty or broken state.

Covers the most recently completed calendar year relative to TODAY below (edit TODAY to
regenerate a different "current" year). Re-run any time to get a fresh random year:

    python generate_demo_data.py

Deliberately does NOT reuse any real project-tag naming (no DNA_/STAT_/CONSULT_-style
codes) -- the fake tags below use different prefixes on purpose, so nothing here can be
mistaken for a real project.
"""

import json
import random
from datetime import date, timedelta
from pathlib import Path

import openpyxl
import pandas as pd

random.seed(20250101)  # fixed seed -> reproducible demo data across re-runs

TODAY = date(2026, 11, 17)
YEAR = TODAY.year - 1  # most recently completed calendar year -> 2025
DATA_DIR = Path(__file__).resolve().parent / "Data"
DATA_DIR.mkdir(exist_ok=True)

MONTHS = ["January", "February", "March", "April", "May", "June",
          "July", "August", "September", "October", "November", "December"]

# --- Vocabulary: same categories/major tasks as the real tracker, so the charts and the
# glossary stay meaningful; project tags, groups and people are all invented. -------------
USER_TYPES = ["Internal Team", "External Research Group", "Facility", "Internal Research Group"]
USER_LOCATIONS = ["Oeiras", "Lisbon", "Coimbra", "Porto"]
PROJECT_TRIGGERS = ["Internal", "Follow-up", "User-Requested", "Proactive Proposal",
                    "Inherited Project", "Outreach-Driven", "Consulting"]
TYPES_OF_DATA = ["MultiOMICS", "Lipidomics", "Metabolomics", "Proteomics", "Transcriptomics", "Other"]
PROJECT_OUTPUTS = ["Pipeline", "Dashboard", "Report", "Figures", "AI Skill", "Consulting note"]
GROUPS = ["Genomics Unit", "Cell Signalling Lab", "Structural Biology Group", "Clinical Research Core",
          "Immunology Facility", "Plant Sciences Group", "Microbiome Lab", "Imaging Facility"]

# Fake project tags: a few different invented naming styles so the gallery doesn't look
# like one template -- underscore-coded (common in the real tracker), and a couple of
# "XX - description" style tags.
FAKE_PROJECT_TAGS = [
    "GEN_014", "GEN_021", "PROT_005", "PROT_011", "LIP_003", "META_008", "META_012",
    "SEQ_019", "SEQ_022", "IMG_006", "IMG_015", "STRUCT_002", "MICR_009",
    "XX - general consulting", "YY - general support", "ZZ - general outreach",
    "CRC_030", "CRC_031", "PLNT_004", "IMMU_017",
]

# A handful of tags are reserved as deterministic examples of each "Needs attention" kind
# the Projects Review page can show, instead of letting ~40% of all projects land there by
# chance: one with no hours logged at all (-> "Not started"), a couple left genuinely
# ongoing with some stale activity (-> "Quiet"), and one with a report sent but no Closing
# Day set (-> "Ready to close"). Every other tag finishes and closes cleanly within the
# year so the section stays readable instead of listing most of the portfolio.
NOT_STARTED_TAG = "MICR_009"
QUIET_TAGS = {"PLNT_004", "IMG_006"}
TO_CLOSE_TAG = "SEQ_022"

SHORT_DESCRIPTIONS = {
    "GEN_014": "Variant calling pipeline for a non-model organism.",
    "GEN_021": "RNA-seq differential expression re-analysis.",
    "PROT_005": "Mass-spec proteomics QC and normalization.",
    "PROT_011": "Interaction network from co-IP proteomics.",
    "LIP_003": "Lipidomics profiling across treatment groups.",
    "META_008": "Metabolomics pathway enrichment report.",
    "META_012": "Targeted metabolomics panel, dose-response.",
    "SEQ_019": "Long-read assembly QC for a draft genome.",
    "SEQ_022": "Amplicon sequencing taxonomic classification.",
    "IMG_006": "Image-analysis pipeline for high-content screening.",
    "IMG_015": "Cell segmentation and feature extraction.",
    "STRUCT_002": "Structural model comparison across conditions.",
    "MICR_009": "Microbiome diversity analysis, 16S.",
    "XX - general consulting": "Ad-hoc statistics consulting, no single deliverable.",
    "YY - general support": "Recurring light support across several small requests.",
    "ZZ - general outreach": "Outreach session, no project deliverable attached.",
    "CRC_030": "Clinical cohort summary statistics.",
    "CRC_031": "Survival analysis for a clinical follow-up study.",
    "PLNT_004": "Transcriptomics in a stress-response time course.",
    "IMMU_017": "Flow cytometry panel analysis and figures.",
}

NON_QUANT_OUTPUTS = [
    "", "Presented at group meeting.", "Shared internal how-to guide.",
    "Informal feedback only, no written report.", "Used to shape a later grant application.",
]


def _rand_date(start: date, end: date):
    span = (end - start).days
    return start + timedelta(days=random.randint(0, max(span, 0)))


def _fmt(d):
    return pd.Timestamp(d) if d else None


# --- 1) Project tracker: Data/KPI_<year>.xlsx, sheets "<year>_CALENDAR" + "_meetings" ----
def build_project_tracker():
    year_start, year_end = date(YEAR, 1, 1), date(YEAR, 12, 31)
    rows = []
    for tag in FAKE_PROJECT_TAGS:
        trigger = random.choice(PROJECT_TRIGGERS)
        first_contact = _rand_date(year_start, year_end - timedelta(days=30))
        register = first_contact + timedelta(days=random.randint(0, 10))
        begin = register + timedelta(days=random.randint(0, 21))
        if tag in (NOT_STARTED_TAG, *QUIET_TAGS):
            # left genuinely open -- no report, no closing -- so the page's "Not started"
            # / "Quiet" examples are these specific projects, not whichever ones happen to
            # roll that way at random.
            report_sent = closing = None
        elif tag == TO_CLOSE_TAG:
            # finished the work and sent the report, but Closing Day was never filled in --
            # the "Ready to close" example.
            report_sent = begin + timedelta(days=random.randint(14, 60))
            if report_sent > year_end - timedelta(days=5):
                report_sent = year_end - timedelta(days=5)
            closing = None
        else:
            # everyone else finishes and closes cleanly within the year, so the "needs
            # attention" section stays limited to the handful of examples above.
            report_sent = begin + timedelta(days=random.randint(7, 90))
            if report_sent > year_end - timedelta(days=5):
                report_sent = year_end - timedelta(days=5)
            closing = report_sent + timedelta(days=random.randint(0, 5))
            if closing > year_end:
                closing = year_end
        if trigger == "Inherited Project":
            # inherited work is attributed to when she/they actually picked it up, which can
            # sit a little after the (older) registration date
            begin = register + timedelta(days=random.randint(10, 40))

        rows.append({
            "Project tag": tag,
            "Short Description": SHORT_DESCRIPTIONS.get(tag, ""),
            "User Type": random.choice(USER_TYPES),
            "User Location": random.choice(USER_LOCATIONS),
            "Grupo": random.choice(GROUPS),
            "User": f"User {chr(65 + FAKE_PROJECT_TAGS.index(tag) % 20)}.",
            "Project Outputs": random.choice(PROJECT_OUTPUTS),
            "Type of Data": random.choice(TYPES_OF_DATA),
            "Project Trigger": trigger,
            "First User Meeting/Shared Data": _fmt(first_contact),
            "Register Project": _fmt(register),
            "Begining": _fmt(begin),
            "Lead Time: Request to Project Start": "",
            "Final Report Sent": _fmt(report_sent),
            "Closing Day": _fmt(closing),
            "Hours in Timesheet": 0.0 if tag == NOT_STARTED_TAG else round(random.uniform(2, 70), 1),
            "Number of Reports": 0 if tag == NOT_STARTED_TAG else random.randint(0, 3),
            "Number of Meetings": 0 if tag == NOT_STARTED_TAG else random.randint(0, 6),
            "Price Charged": 0 if tag == NOT_STARTED_TAG else random.choice([0, 0, 0, 150, 300, 450, 600]),
            "Non-quantifiable outputs": random.choice(NON_QUANT_OUTPUTS),
            "Notas": "",
        })

    projects = pd.DataFrame(rows)

    meetings_rows = []
    for _ in range(14):
        tag = random.choice(FAKE_PROJECT_TAGS)
        meetings_rows.append({
            "Project tag": tag,
            "User Type": random.choice(USER_TYPES),
            "Date": _fmt(_rand_date(year_start, year_end)),
            "User Location": random.choice(USER_LOCATIONS),
            "Grupo": random.choice(GROUPS),
            "User": f"User {chr(65 + FAKE_PROJECT_TAGS.index(tag) % 20)}.",
            "Meeting Outputs": random.choice(
                ["Scope agreed.", "Data shared.", "Results discussed.", "Follow-up planned."]),
            "Time": round(random.uniform(0.5, 2.0), 1),
        })
    meetings = pd.DataFrame(meetings_rows)

    path = DATA_DIR / f"KPI_{YEAR}.xlsx"
    with pd.ExcelWriter(path, engine="openpyxl") as xl:
        projects.to_excel(xl, sheet_name=f"{YEAR}_CALENDAR", index=False)
        meetings.to_excel(xl, sheet_name=f"{YEAR}_CALENDAR_meetings", index=False)
    print(f"wrote {path} ({len(projects)} projects, {len(meetings)} meetings)")
    return projects


# --- 2) Personal time log: Data/track_time.csv -------------------------------------------
NON_PROJECT_MAJOR_TASKS = {
    "Meetings (non-project)": ["Internal Meeting", "External Meeting"],
    "Org & Admin": ["Internal org", "Burocracy", "Seminar"],
    "Trainning": ["Trainning"],
}
PROJECT_MAJOR_TASKS = ["code", "Meetings/Comms", "ProjectOrg", "Report", "Review", "Plan/Study"]
WEEKLY_HOURS_TARGET = (27, 34)  # a full working week, roughly -- also what keeps every
                                 # month comfortably over 40h and the year averaging ~30-35h/week


def _week_label(d):
    """('January', '1st January') for the Monday `d` -- the ordinal matches
    kpi_data.week_bounds's own Monday-of-the-month numbering, and only the leading
    digit of the returned label is ever parsed back out of it."""
    month_name = MONTHS[d.month - 1]
    month_start = date(d.year, d.month, 1)
    first_monday_offset = (7 - month_start.weekday()) % 7
    first_monday = month_start + timedelta(days=first_monday_offset)
    ordinal = (d - first_monday).days // 7 + 1 if d >= first_monday else 1
    suffix = "st" if ordinal == 1 else "nd" if ordinal == 2 else "rd" if ordinal == 3 else "th"
    return month_name, f"{ordinal}{suffix} {month_name}"


def build_time_log(projects):
    """Mostly-continuous weekly logging per project across its own Begining -> report/
    today window (an occasional genuine pause, not one scattered into almost every week),
    topped up with non-project hours so every week lands around a full working week
    (WEEKLY_HOURS_TARGET) regardless of how many projects happen to be active that week.
    Generating hours independently-per-week regardless of each project's own active
    window -- the first version of this script did that -- produces a "paused" gap nearly
    everywhere once fed through kpi_data.lead_time_table's gap detector, which doesn't
    resemble a real time log at all. And a flat few non-project hours per week (the second
    version) left early months -- before most projects have even started -- reading as
    almost no work at all; topping up to a target each week is what keeps every month's
    total healthy and gives non-project categories a real, visible share instead of a
    token one. Per-project hours are generated week-major (every project scheduled for a
    week takes its turn in random order before the per-week cap kicks in), not
    project-major (the third version did that -- whichever project happened to be last in
    the list got silently crowded out of the same weeks every time by the cap, reading as
    that one project abandoned for months when it was really just list order)."""
    year_start, year_end = date(YEAR, 1, 1), date(YEAR, 12, 31)
    today = date.today()
    rows = []
    entry_id = 1
    week_hours = {}  # monday -> running total, across every category, so the top-up below
                      # knows how much more a week actually needs

    def add_entry(monday, category, major_task, tag, hrs, mins):
        nonlocal entry_id
        month_name, week_label = _week_label(monday)
        rows.append({
            "Entry": f"DEMO_{entry_id:03d}", "Timesheet updated": random.choice(["Yes", "Yes", "Yes", "No"]),
            "Category": category, "Hours (exact)": hrs + mins / 60, "Major task name (chart)": major_task,
            "Hrs": hrs, "Min": mins, "Month": month_name, "Month and year (chart)": f"{month_name} {YEAR}",
            "Notes": "", "Week": week_label, "Weekly entry name (chart)": tag, "Year": YEAR,
            "Unnamed: 13": "",
        })
        entry_id += 1
        week_hours[monday] = week_hours.get(monday, 0.0) + hrs + mins / 60

    # Pass 1: each project's own schedule -- which weeks it's active, minus one internal
    # pause -- computed independently of every other project's schedule.
    project_windows = {}  # tag -> (begin_d, end_d), reused below for the dev-side entries
    project_weeks = {}    # tag -> [Monday, ...], the weeks that project WANTS to log in

    for _, p in projects.iterrows():
        begin = p["Begining"]
        if pd.isna(begin):
            continue
        if p["Project tag"] == NOT_STARTED_TAG:
            # deliberately never logged against -- the "Not started" needs-attention example
            continue
        begin_d = begin.date()
        end_raw = p["Final Report Sent"] if pd.notna(p["Final Report Sent"]) else p["Closing Day"]
        end_d = end_raw.date() if pd.notna(end_raw) else min(today, year_end)
        end_d = min(max(end_d, begin_d), year_end)
        project_windows[p["Project tag"]] = (begin_d, end_d)

        monday = begin_d - timedelta(days=begin_d.weekday())
        weeks = []
        while monday <= end_d:
            weeks.append(monday)
            monday += timedelta(days=7)
        if not weeks:
            continue

        # One genuine pause for a minority of long-enough projects -- a real 2-3 week
        # stretch with nothing logged, strictly inside the span -- rather than a gap
        # showing up almost everywhere.
        pause = set()
        if len(weeks) > 6 and random.random() < 0.25:
            pause_len = min(random.randint(2, 3), len(weeks) - 5)
            start_idx = random.randint(2, len(weeks) - pause_len - 2)
            pause = set(range(start_idx, start_idx + pause_len))

        project_weeks[p["Project tag"]] = [wk for i, wk in enumerate(weeks) if i not in pause]

    # Pass 2: week-major, not project-major. For any week where several projects are
    # scheduled, who gets crowded out by the per-week cap below needs to be random, not
    # always whichever project happens to be listed last -- a fixed iteration order would
    # silently starve the same late-listed projects week after week, reading as a project
    # quietly abandoned when it's really just where it sits in a list.
    by_week = {}
    for tag, weeks in project_weeks.items():
        for wk in weeks:
            by_week.setdefault(wk, []).append(tag)

    for wk, tags_here in sorted(by_week.items()):
        random.shuffle(tags_here)
        for tag in tags_here:
            if random.random() < 0.02:  # a rare single skipped week -- kept low since
                continue                 # PAUSE_MIN_WEEKS=1 means even one counts as a pause
            if week_hours.get(wk, 0) >= 20:  # already a full day's worth from other active
                continue                      # projects this week -- one person, one week
            for _ in range(random.randint(1, 3)):
                hrs, mins = random.choice([1, 2, 2, 3, 4, 4]), random.choice([0, 0, 15, 30])
                add_entry(wk, "Projects", random.choice(PROJECT_MAJOR_TASKS), tag, hrs, mins)
                if week_hours.get(wk, 0) >= 20:  # leave room for other active projects and
                    break                        # non-project hours -- one person, one week

    # A handful of Projects-Development entries (tool-building side work). Still tagged to
    # a project tag (so it counts as that project's hours), but only to one already in its
    # active window that week -- an entry logged before a project has even begun, or long
    # after it closed, would read as its own multi-month "pause" either side of it.
    monday = year_start - timedelta(days=year_start.weekday())
    while monday <= year_end:
        active_tags = [t for t, (b, e) in project_windows.items() if b <= monday <= e]
        if active_tags and random.random() < 0.35:
            tag = random.choice(active_tags)
            hrs, mins = random.choice([1, 2, 3, 4]), random.choice([0, 0, 30])
            add_entry(monday, "Projects-Development", random.choice(["Tools", "AI Skills"]), tag, hrs, mins)
        monday += timedelta(days=7)

    # Non-project categories: org/admin, non-project meetings, training. A light baseline
    # every week regardless (people have *some* meetings and admin even in a heavy project
    # week), then topped up until the week reaches WEEKLY_HOURS_TARGET -- which is what
    # carries the early months (before most projects have started) up to a real week's
    # worth of hours, mostly as org/admin and meetings rather than invented project work.
    monday = year_start - timedelta(days=year_start.weekday())
    while monday <= year_end:
        target = random.uniform(*WEEKLY_HOURS_TARGET)

        def add_non_project():
            category = random.choices(list(NON_PROJECT_MAJOR_TASKS), weights=[40, 45, 15])[0]
            major_task = random.choice(NON_PROJECT_MAJOR_TASKS[category])
            hrs, mins = random.choice([1, 1, 2, 2, 3]), random.choice([0, 0, 30])
            add_entry(monday, category, major_task, category, hrs, mins)

        for _ in range(random.randint(2, 4)):
            add_non_project()
        guard = 0  # belt-and-braces: WEEKLY_HOURS_TARGET is well above what a handful of
        while week_hours.get(monday, 0) < target and guard < 25:  # 1-3h entries could ever
            add_non_project()                                      # fail to reach, but never loop forever
            guard += 1
        monday += timedelta(days=7)

    df = pd.DataFrame(rows)
    path = DATA_DIR / "track_time.csv"
    df.to_csv(path, sep=";", index=False, encoding="utf-8-sig")
    print(f"wrote {path} ({len(df)} rows across {YEAR}, "
          f"{df['Hours (exact)'].sum():.0f}h total, {df['Hours (exact)'].sum()/52:.1f}h/week avg)")


# --- 3) Special projects: ratings + task checklists ---------------------------------------
SPECIAL_PROJECTS = [
    ("01 - Reach more research groups", "Open Analysis Toolkit", "Reusable analysis toolkit open to any group.",
     "Easy to demo, clear visibility gain.", "Needs a stable place to be hosted.",
     "Could absorb more data types over time.", 2, 3, 1, 4),
    ("01 - Reach more research groups", "Hands-on Workshop", "Recurring workshop on common analysis patterns.",
     "Cheap to run, good word-of-mouth.", "", "Materials can be reused across editions.", 1, 4, 1, 5),
    ("02 - Reduce turnaround time", "Request Triage Tool", "Lightweight intake form that pre-sorts new requests.",
     "Cuts back-and-forth at project start.", "Only helps the intake step, not delivery.",
     "Could auto-suggest the right Project Trigger.", 2, 3, 2, 2),
    ("02 - Reduce turnaround time", "Template Library", "Standard report/figure templates per data type.",
     "Saves repeat setup work on similar projects.", "Templates drift if not kept up to date.",
     "Versioned templates with a changelog.", 1, 3, 2, 2),
    ("03 - Build internal tooling", "Dataset Browser", "Internal explorer for QC'd analysis datasets.",
     "Centralizes what's otherwise scattered notebooks.", "Needs ongoing maintenance as formats change.",
     "Could plug directly into the analysis workflow.", 3, 4, 3, 3),
    ("03 - Build internal tooling", "Snippet Library", "Curated, reusable code snippets for common tasks.",
     "Low effort, immediate reuse value.", "Only useful if people actually contribute back.",
     "Could become a small internal package.", 1, 2, 2, 1),
]


def build_special_projects():
    cols = ["Goal", "Project", "Description", "Advantages", "Limitations", "Future gain",
            "Development", "Impact", "Maintenance", "Visibility"]
    df = pd.DataFrame(SPECIAL_PROJECTS, columns=cols)
    path = DATA_DIR / "Special_Projects_Ratings.xlsx"
    df.to_excel(path, sheet_name="Special Projects Ratings", index=False)
    print(f"wrote {path} ({len(df)} goal/project rows)")

    # Anchored on the REAL current date, not the fake year above -- kpi_data.task_schedule
    # splits tasks into "coming up" / "behind" against whatever day the dashboard is
    # actually opened on. Dates fixed to the 2025 demo year would all read as overdue no
    # matter when someone runs this, which is exactly backwards from a healthy task list.
    today = date.today()
    tasks = {}
    for _, project, *_ in SPECIAL_PROJECTS:
        n_tasks = random.randint(3, 5)
        # start a little in the past, so the first milestone or two are already behind us,
        # then run on well past today -- most of what's left open should be upcoming, not
        # overdue.
        cursor = today - timedelta(days=random.randint(20, 60))
        task_list = []
        for i in range(n_tasks):
            start = cursor
            due = start + timedelta(days=random.randint(20, 45))
            if due < today - timedelta(days=7):
                done = random.random() < 0.9   # safely in the past -> almost certainly done
            elif due < today:
                done = random.random() < 0.3   # just past -> a few genuinely overdue ones
            else:
                done = False                     # in the future -> can't be done yet
            task_list.append({
                "id": f"{random.getrandbits(32):08x}",
                "text": f"{project}: milestone {i + 1}",
                "level": 0,
                "done": done,
                "start": start.isoformat(),
                "due": due.isoformat(),
            })
            cursor = due + timedelta(days=1)
        tasks[project] = task_list

    tasks_json_path = DATA_DIR / "special_project_tasks.json"
    tasks_json_path.write_text(json.dumps(tasks, indent=2), encoding="utf-8")
    print(f"wrote {tasks_json_path}")

    with pd.ExcelWriter(DATA_DIR / "Special_Projects_Tasks.xlsx", engine="openpyxl") as xl:
        for project, task_list in tasks.items():
            pd.DataFrame(task_list).to_excel(xl, sheet_name=project[:31], index=False)
    print(f"wrote {DATA_DIR / 'Special_Projects_Tasks.xlsx'}")


# --- 4) Beyond-projects cards ----------------------------------------------------------------
def build_beyond_projects():
    period_label = f"{YEAR}"
    cards = [
        {"title": "Guest lecture · Summer School", "value": "~16 h in total", "color": "#0B3C49",
         "description": "16 h bioinformatics module for visiting students."},
        {"title": "Pipeline outreach", "value": "2", "color": "#2A9D8F",
         "description": "Pipeline showcased at 2 seminars · opened 1 new project."},
        {"title": "Internal tools", "value": "2", "color": "#E76F51",
         "description": "Two small internal helper scripts (personal use)."},
    ]
    data = {period_label: cards}
    path = DATA_DIR / "beyond_projects.json"
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {path}")

    rows = [{"Period": period_label, **c} for c in cards]
    pd.DataFrame(rows).to_excel(DATA_DIR / "Beyond_Projects.xlsx", sheet_name="Beyond projects", index=False)
    print(f"wrote {DATA_DIR / 'Beyond_Projects.xlsx'}")


# --- 4b) Publications ------------------------------------------------------------------------
def build_publications():
    period_label = f"{YEAR}"
    pubs = [
        {"title": "A multiomics pipeline for routine lipidomics QC",
         "venue": "Journal of Open Bioinformatics (example)", "date": f"{YEAR}-09-12",
         "url": "https://example.org/jobi/2025/example-lipidomics-qc",
         "projects": "LIP_003, META_008"},
        {"title": "Benchmarking structural variant callers on facility sequencing data",
         "venue": "bioRxiv preprint (example)", "date": f"{YEAR}-11-03",
         "url": "https://example.org/biorxiv/2025.11.03.example",
         "projects": "SEQ_019, STRUCT_002"},
    ]
    data = {period_label: pubs}
    path = DATA_DIR / "publications.json"
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {path}")

    rows = [{"Period": period_label, **p} for p in pubs]
    pd.DataFrame(rows).to_excel(DATA_DIR / "Publications.xlsx", sheet_name="Publications", index=False)
    print(f"wrote {DATA_DIR / 'Publications.xlsx'}")


# --- 5) Tools & AI Skills inventory ------------------------------------------------------
TOOLS = [
    ("QC Dashboard", "Adaptation of the internal pipeline into a facility-specific QC dashboard.",
     "Tool Dashboard", f"{YEAR}", "Facility", "User Project", "", "Could absorb more facility-specific checks."),
    ("variant-highlighter-skill", "Interactive variant highlighter letting users pick samples and tweak output figures.",
     "AI Skill", f"{YEAR}", "User", "User Project", "Limited sandbox network access.",
     "Faster deployment across more genome builds."),
    ("intake-formatter-agent", "Turns user-submitted sample sheets into pipeline-ready standardized tables.",
     "AI Skill", f"{YEAR}", "Internal Team", "Internal pipeline tool", "Needs tighter dashboard integration.",
     "Cuts manual cleanup on recurring requests."),
    ("Report Builder", "Generates the standard PDF report from a project's tracked outputs.",
     "Internal Tool", f"{YEAR}", "Internal Team", "Internal pipeline tool", "", "Could template more report types."),
]


def build_tools():
    cols = ["Name", "Description", "Type of tool", "Built in", "Use", "Project Origin",
            "Limitations", "Future gain"]
    df = pd.DataFrame(TOOLS, columns=cols)
    path = DATA_DIR / "tools.xlsx"
    df.to_excel(path, sheet_name="Tools", index=False)
    print(f"wrote {path} ({len(df)} tools)")


# --- 6) Custom tags (dropdown memory) ------------------------------------------------------
def build_custom_tags():
    data = {"projects": [], "categories": [], "major_tasks": []}
    path = DATA_DIR / "custom_tags.json"
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"wrote {path}")


# --- --empty: a blank starting point for real use, not fake content -----------------------
PROJECT_COLS = [
    "Project tag", "Short Description", "User Type", "User Location", "Grupo", "User",
    "Project Outputs", "Type of Data", "Project Trigger", "First User Meeting/Shared Data",
    "Register Project", "Begining", "Lead Time: Request to Project Start", "Final Report Sent",
    "Closing Day", "Hours in Timesheet", "Number of Reports", "Number of Meetings", "Price Charged",
    "Non-quantifiable outputs", "Notas",
]
MEETING_COLS = ["Project tag", "User Type", "Date", "User Location", "Grupo", "User",
                "Meeting Outputs", "Time"]
TIMELOG_COLS = ["Entry", "Timesheet updated", "Category", "Hours (exact)", "Major task name (chart)",
                 "Hrs", "Min", "Month", "Month and year (chart)", "Notes", "Week",
                 "Weekly entry name (chart)", "Year", "Unnamed: 13"]
GOALS_COLS = ["Goal", "Project", "Description", "Advantages", "Limitations", "Future gain",
              "Development", "Impact", "Maintenance", "Visibility"]
TOOLS_COLS = ["Name", "Description", "Type of tool", "Built in", "Use", "Project Origin",
              "Limitations", "Future gain"]


def build_empty(year=None):
    """Write every file Dashboard/kpi_data.py needs, with the right columns/sheets but
    ZERO rows of content -- a real starting point instead of fake placeholder activity.
    Some files (the two JSON task/beyond-projects files and their Excel mirrors) have no
    safe "empty but present" state worth writing, since kpi_data.py already creates them
    correctly (empty, or via a small generic seed) the first time it finds them missing --
    see README.md's "Starting fresh with your own data" for exactly which is which."""
    year = year or date.today().year
    print(f"Writing an EMPTY starting point for calendar year {year} (no fake content)...\n")

    path = DATA_DIR / f"KPI_{year}.xlsx"
    with pd.ExcelWriter(path, engine="openpyxl") as xl:
        pd.DataFrame(columns=PROJECT_COLS).to_excel(xl, sheet_name=f"{year}_CALENDAR", index=False)
        pd.DataFrame(columns=MEETING_COLS).to_excel(xl, sheet_name=f"{year}_CALENDAR_meetings", index=False)
    print(f"wrote {path} (0 projects, 0 meetings)")

    tl_path = DATA_DIR / "track_time.csv"
    pd.DataFrame(columns=TIMELOG_COLS).to_csv(tl_path, sep=";", index=False, encoding="utf-8-sig")
    print(f"wrote {tl_path} (0 rows)")

    pd.DataFrame(columns=GOALS_COLS).to_excel(
        DATA_DIR / "Special_Projects_Ratings.xlsx", sheet_name="Special Projects Ratings", index=False)
    print(f"wrote {DATA_DIR / 'Special_Projects_Ratings.xlsx'} (0 rows)")

    pd.DataFrame(columns=TOOLS_COLS).to_excel(DATA_DIR / "tools.xlsx", sheet_name="Tools", index=False)
    print(f"wrote {DATA_DIR / 'tools.xlsx'} (0 rows)")

    build_custom_tags()  # already writes an empty {"projects": [], ...} unconditionally

    for stray in ("special_project_tasks.json", "Special_Projects_Tasks.xlsx",
                  "beyond_projects.json", "Beyond_Projects.xlsx",
                  "publications.json", "Publications.xlsx", "KPI_2025.xlsx"):
        p = DATA_DIR / stray
        if p.exists():
            p.unlink()
            print(f"removed {p} (the app recreates the JSON ones correctly on first use)")

    print(f"\nDone. Data/ is now a blank {year} starting point -- open the dashboard and use "
          "Add Data to fill it in, or edit the Excel/CSV files directly.")


if __name__ == "__main__":
    import sys
    if "--empty" in sys.argv:
        build_empty()
    else:
        projects = build_project_tracker()
        build_time_log(projects)
        build_special_projects()
        build_beyond_projects()
        build_publications()
        build_tools()
        build_custom_tags()
        print(f"\nDone. Demo data covers calendar year {YEAR}.")
