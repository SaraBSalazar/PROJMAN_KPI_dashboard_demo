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
import sys
import random
from datetime import date, datetime, timedelta
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


# --- 2b) Stopwatch store: Data/time_entries.csv --------------------------------------------
# The Time Tracker page's own store: one row per STRETCH of work with real start and end
# timestamps, as against track_time.csv's one row per project/category/major task per week.
# Only the last few weeks are generated -- the tracker is a day-to-day tool, and a year of
# fake stopwatch entries would say the dashboard had been stopwatched all year, which is not
# the story the demo is telling. Times are naive local ISO text, the shape kpi_data reads.
TIME_ENTRY_COLS = ["id", "start", "end", "project", "category", "major_task",
                   "description", "notes"]
TRACKER_WEEKS = 3
DAY_SHAPES = [  # (start hour, start minute, minutes) -- a plausible working day
    (9, 15, 75), (10, 45, 50), (11, 45, 35), (14, 0, 95), (15, 50, 60), (17, 5, 45),
]
TRACKER_DESCRIPTIONS = {
    "code": ["intake parser", "rewriting the normalisation step", "debugging the merge",
             "pipeline tidy-up", "unit tests for the loader"],
    "Plan/Study": ["reading the method paper", "sketching the analysis plan",
                   "comparing two approaches"],
    "Report": ["first draft of the report", "figures for the report", "report revisions"],
    "Review": ["reviewing the draft", "second pass on the results"],
    "ProjectOrg": ["filing the project notes", "chasing the sample sheet"],
    "Meetings/Comms": ["catch-up with the group", "email round"],
    "Internal Meeting": ["team meeting"], "External Meeting": ["call with the requester"],
    "Internal org": ["inbox and admin"], "Burocracy": ["expense forms"],
    "Seminar": ["department seminar"], "Trainning": ["course exercises"],
}


def build_time_entries(projects):
    """A few recent weeks of stopwatch entries, filed with the same project / category /
    major task vocabulary the time log uses -- so the Time Tracker's "send this week to the
    time log" panel has something real to propose, and the week views have something to
    draw. The most recent entry is left RUNNING (blank end) only if that would land on a
    weekday within working hours; a demo that opens with a timer that has apparently been
    going since the weekend is just confusing."""
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    tags = [p["Project tag"] for p in projects] or ["DEMO_001"]

    rows, n = [], 0
    for week in range(TRACKER_WEEKS - 1, -1, -1):
        week_monday = monday - timedelta(weeks=week)
        for weekday in range(5):
            day = week_monday + timedelta(days=weekday)
            if day > today:
                continue
            for hour, minute, length in DAY_SHAPES:
                if random.random() < 0.25:        # not every slot every day
                    continue
                start = datetime(day.year, day.month, day.day, hour, minute)
                start += timedelta(minutes=random.randint(-10, 10))
                end = start + timedelta(minutes=length + random.randint(-15, 20))
                if start > datetime.now():
                    continue
                if random.random() < 0.72:
                    category, major_task = "Projects", random.choice(PROJECT_MAJOR_TASKS)
                    tag = random.choice(tags)
                else:
                    category = random.choice(list(NON_PROJECT_MAJOR_TASKS))
                    major_task = random.choice(NON_PROJECT_MAJOR_TASKS[category])
                    tag = category
                n += 1
                rows.append({
                    "id": f"te_demo{n:04d}",
                    "start": start.strftime("%Y-%m-%dT%H:%M:%S"),
                    "end": end.strftime("%Y-%m-%dT%H:%M:%S"),
                    "project": tag, "category": category, "major_task": major_task,
                    "description": random.choice(
                        TRACKER_DESCRIPTIONS.get(major_task, ["work"])),
                    "notes": "",
                })

    # One timer left running, but only when "now" is somewhere a timer plausibly would be.
    now = datetime.now()
    if rows and now.weekday() < 5 and 8 <= now.hour < 19:
        rows[-1]["start"] = (now - timedelta(minutes=random.randint(12, 48))
                             ).strftime("%Y-%m-%dT%H:%M:%S")
        rows[-1]["end"] = ""

    path = DATA_DIR / "time_entries.csv"
    pd.DataFrame(rows, columns=TIME_ENTRY_COLS).to_csv(
        path, sep=";", index=False, encoding="utf-8-sig")
    print(f"wrote {path} ({len(rows)} stretches over the last {TRACKER_WEEKS} weeks"
          + (", one still running)" if rows and not rows[-1]["end"] else ")"))
    return rows


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

    # Anchored on the REAL current date, not the fake year above -- kpi_data.task_schedule
    # splits tasks into "coming up" / "behind" against whatever day the dashboard is
    # actually opened on. Dates fixed to the 2025 demo year would all read as overdue no
    # matter when someone runs this, which is exactly backwards from a healthy task list.
    today = date.today()

    # Two projects are already delivered, so the demo shows the finished state: a date in
    # "Completed" puts a green ring and a ✓ on the bubble and a finish date on the card.
    # One big bubble and one of the smallest, since the ✓ is sized off the bubble's own
    # diameter and both ends of that range are worth seeing.
    finished_on = {
        "Hands-on Workshop": today - timedelta(days=12),
        "Snippet Library": today - timedelta(days=40),
    }
    df["Completed"] = [finished_on[p].isoformat() if p in finished_on else ""
                       for p in df["Project"]]

    path = DATA_DIR / "Special_Projects_Ratings.xlsx"
    df.to_excel(path, sheet_name="Special Projects Ratings", index=False)
    print(f"wrote {path} ({len(df)} goal/project rows, {len(finished_on)} finished)")

    tasks = {}
    for _, project, *_ in SPECIAL_PROJECTS:
        n_tasks = random.randint(3, 5)
        # start a little in the past, so the first milestone or two are already behind us,
        # then run on well past today -- most of what's left open should be upcoming, not
        # overdue.
        # A finished project instead gets its whole checklist in the past, ticked and
        # landing on its finish date: "delivered" with overdue tasks still open would read
        # as a bug rather than as a demo.
        end = finished_on.get(project)
        cursor = (end - timedelta(days=25 * n_tasks) if end
                  else today - timedelta(days=random.randint(20, 60)))
        task_list = []
        for i in range(n_tasks):
            start = cursor
            due = start + timedelta(days=random.randint(18, 24) if end else random.randint(20, 45))
            if end:
                done = True
            elif due < today - timedelta(days=7):
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


# --- 4b) Publications' siblings: courses, conferences, juries, outreach ------------------
# Same shape as the publications above and the same page edits both: one record per output,
# with a `kind` that decides which group it shows up under (and which CV section it would
# belong to). Tagged with fake project ids so the link back to the tracker resolves.
CV_OUTPUTS = [
    ("Course taught", "Introduction to reproducible analysis, 2-day module",
     "Example University", "-05", "Designed from scratch; project-based, in Python.",
     "18 students", "", ""),
    ("Thesis jury", "Main arguer, MSc thesis defence on sequencing QC",
     "Example University", "-12", "", "", "", ""),
    ("Conference poster", "A reusable QC dashboard for facility sequencing runs",
     "Example Bioinformatics Open Days", "-03", "Corresponding author", "",
     "SEQ_019, LIP_003", ""),
    ("Conference talk", "What a small data-analysis service can measure about itself",
     "Example National Bioinformatics Meeting", "-10", "", "", "", ""),
    ("Course attended", "Machine learning for multi-omics integration",
     "Example Courses", "-09", "machine learning, multi-omics integration, Python", "", "", ""),
    ("Course attended", "Statistics and data analysis with R",
     "Example Training Centre", "-02", "R, statistics, data analysis", "", "", ""),
    ("Certification", "Research data management, practitioner level",
     "Example Institute", "-06", "data management, FAIR data", "", "", ""),
    ("Outreach", "Open day demo: what the service does, for first-year students",
     "Example Institute", "-11", "", "~40 visitors", "", ""),
]


def build_cv_outputs():
    period_label = f"{YEAR}"
    entries = [
        {"kind": kind, "title": title, "where": where, "date": f"{YEAR}{month}",
         "detail": detail, "scale": scale, "projects": projects, "url": url}
        for kind, title, where, month, detail, scale, projects, url in CV_OUTPUTS
    ]
    data = {period_label: entries}
    path = DATA_DIR / "cv_outputs.json"
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {path}")

    rows = [{"Period": period_label, "Kind": e["kind"], "Title": e["title"], "Where": e["where"],
             "Date": e["date"], "Detail": e["detail"], "Scale": e["scale"],
             "Related projects": e["projects"], "URL": e["url"]} for e in entries]
    pd.DataFrame(rows).to_excel(DATA_DIR / "CV_Outputs.xlsx", sheet_name="ADA outputs", index=False)
    print(f"wrote {DATA_DIR / 'CV_Outputs.xlsx'}")


# --- 4c) CV content: an invented career for the CV page ----------------------------------
# Every name, place and paper below is made up, in the same "(example)" register as the rest
# of this file -- the point is to show the page working, not to publish anyone's record. The
# service half of that page is never stored anyway: it is computed from the tracker, the
# tools inventory and the two output stores on every load, so this file holds only the parts
# a CV knows on its own.
DEMO_CV_EXPERIENCE = [
    ("service", "Data Analyst, Advanced Data Analysis group", "Example Institute",
     "Example City", f"{YEAR - 1}-01", "present",
     "Embedded analyst supporting research groups across the institute with sequencing, "
     "imaging and multi-omics data, from raw files to interpretation.",
     ["Deliver end-to-end analyses for user projects: data processing, cleaning, "
      "normalisation, differential analysis and visualisation.",
      "Built and maintain the group's reusable pipelines and the dashboards that track "
      "the service's own work.",
      "Consult with researchers on study design and interpretation; write and deliver the "
      "final report on every project."]),
    ("postdoc", "Postdoctoral Researcher, Computational Genomics", "Example University",
     "Example City", f"{YEAR - 4}-09", f"{YEAR - 1}-12",
     "Moved from bench work to computational analysis of sequencing and proteomics data.",
     ["Wrote Python and R workflows to integrate sequencing, proteomics and metabolomics "
      "data in a microbial infection model.",
      "Mentored two MSc students through their thesis analyses.",
      "Co-authored three peer-reviewed papers and presented at four conferences."]),
    ("visiting", "Visiting Researcher, Systems Biology", "Example Institute of Technology",
     "Another Example City", f"{YEAR - 3}-09", f"{YEAR - 3}-11", "",
     ["Three-month stay building proteomics analysis skills in Python.",
      "Started the collaboration that produced the benchmarking paper below."]),
    ("phd", "PhD Researcher, Molecular Biology", "Example University", "Example City",
     f"{YEAR - 9}-09", f"{YEAR - 4}-06", "",
     ["Thesis on stress-response regulation, combining wet-lab work with the first "
      "sequencing analyses done in the lab.",
      "Taught practical sessions to around 40 MSc students across four years."]),
]

DEMO_CV = {
    "meta": {
        "What this is": "Invented CV content for the demo's CV page. Nobody's real record: "
                        "every name, place and output below is made up.",
        "Not included (comes from the dashboard)": "Everything about the current role -- "
                                                   "projects delivered, groups reached, time "
                                                   "to deliver, turnaround by size, tools "
                                                   "built, courses and posters. Those are "
                                                   "computed from the live files on every "
                                                   "page load.",
        "Join key": "experience_bullets.experience_id -> experience.id",
        "Ordering": "All lists are newest first. Dates are YYYY or YYYY-MM text.",
    },
    "profile": [
        {"field": "name", "value": "Alex Rivera (example)"},
        {"field": "role", "value": "Data Analyst · Advanced Data Analysis · Example Institute"},
        {"field": "email", "value": "alex.rivera@example.org"},
        {"field": "about", "value":
            "Data analyst with 10+ years in research across genomics, proteomics and imaging. "
            "I turn complex datasets into answers for researchers: end-to-end analysis, "
            "reusable Python/R pipelines and clear reporting. I also design and teach "
            "practical data-analysis courses. Author of 6 peer-reviewed articles, 2 as first "
            "author. (Invented demo content.)"},
    ],
    "cv_stats": [
        {"section": "Institutional experience", "key": "years_research", "value": "10+",
         "label": f"years in research (since {YEAR - 10})"},
        {"section": "Institutional experience", "key": "students_taught", "value": "60+",
         "label": "students taught across 3 courses"},
        {"section": "Institutional experience", "key": "courses_designed", "value": 1,
         "label": "course designed from scratch: Introduction to reproducible analysis"},
        {"section": "Institutional experience", "key": "students_mentored", "value": 4,
         "label": "BSc/MSc students informally mentored"},
        {"section": "Institutional experience", "key": "thesis_juries", "value": 1,
         "label": "MSc thesis jury (main arguer)"},
        {"section": "Institutional experience", "key": "institutions", "value": 3,
         "label": "institutions in 2 countries (both invented)"},
        {"section": "Specific expertise", "key": "data_layers", "value": 4,
         "label": "data layers analysed, and integrated across layers: sequencing, "
                  "proteomics, metabolomics, imaging"},
    ],
    "experience": [
        {"id": eid, "title": title, "organisation": org, "location": loc, "start": start,
         "end": end, "date_note": "", "lead": lead}
        for eid, title, org, loc, start, end, lead, _ in DEMO_CV_EXPERIENCE
    ],
    "experience_bullets": [
        {"experience_id": eid, "order": i, "text": text}
        for eid, _, _, _, _, _, _, bullets in DEMO_CV_EXPERIENCE
        for i, text in enumerate(bullets, start=1)
    ],
    "publications": [
        {"title": "A multiomics pipeline for routine lipidomics QC",
         "venue": "Journal of Open Bioinformatics (example)", "year": YEAR, "type": "article",
         "first_author": True, "doi": "", "url": "https://example.org/jobi/example-lipidomics-qc"},
        {"title": "Benchmarking structural variant callers on facility sequencing data",
         "venue": "bioRxiv preprint (example)", "year": YEAR, "type": "preprint",
         "first_author": False, "doi": "", "url": "https://example.org/biorxiv/example"},
        {"title": "Reporting standards for small data-analysis services",
         "venue": "Journal of Research Infrastructure (example)", "year": YEAR - 1,
         "type": "article", "first_author": True, "doi": "", "url": ""},
        {"title": "Integrated proteomics and metabolomics of a microbial stress response",
         "venue": "Example Journal of Microbiology", "year": YEAR - 2, "type": "article",
         "first_author": False, "doi": "", "url": ""},
        {"title": "A reusable workflow for differential expression in small cohorts",
         "venue": "Example Methods", "year": YEAR - 3, "type": "article",
         "first_author": False, "doi": "", "url": ""},
        {"title": "Transcriptional regulation under acid stress",
         "venue": "Example Journal of Microbiology", "year": YEAR - 5, "type": "article",
         "first_author": False, "doi": "", "url": ""},
    ],
    "conference_contributions": [
        {"title": "A reusable QC dashboard for facility sequencing runs",
         "event": "Example Bioinformatics Open Days", "date": f"{YEAR}-03", "type": "poster",
         "note": "Corresponding author"},
        {"title": "What a small data-analysis service can measure about itself",
         "event": "Example National Bioinformatics Meeting", "date": f"{YEAR}-10",
         "type": "oral", "note": ""},
        {"title": "Integrating proteomics and metabolomics in a stress-response model",
         "event": "Example Systems Biology Conference", "date": f"{YEAR - 2}", "type": "poster",
         "note": ""},
        {"title": "Transcriptional regulation under acid stress",
         "event": "Example Microbiology Congress", "date": f"{YEAR - 5}", "type": "oral",
         "note": "Best early-career talk"},
        {"title": "(6 further posters, not listed individually)",
         "event": "National and international meetings", "date": f"{YEAR - 9}–{YEAR - 3}",
         "type": "poster", "note": "count only"},
    ],
    "teaching": [
        {"item": "Introduction to reproducible analysis, 2-day module (designed from scratch)",
         "institution": "Example University", "date": f"{YEAR}-05", "students": "18",
         "detail": "Project-based, taught in Python."},
        {"item": "Main arguer, MSc thesis defence on sequencing QC",
         "institution": "Example University", "date": f"{YEAR}-12", "students": "", "detail": ""},
        {"item": "Molecular biology, practical sessions",
         "institution": "Example University", "date": f"{YEAR - 9}–{YEAR - 4} (during PhD)",
         "students": "40+", "detail": ""},
    ],
    "education": [
        {"degree": "PhD in Molecular Biology", "institution": "Example University",
         "years": f"{YEAR - 9}–{YEAR - 4}", "grade": "With distinction",
         "thesis": "Thesis on transcriptional regulation of the microbial stress response"},
        {"degree": "MSc in Biotechnology", "institution": "Example University",
         "years": f"{YEAR - 12}–{YEAR - 10}", "grade": "17/20", "thesis": ""},
        {"degree": "BSc in Biology", "institution": "Example University",
         "years": f"{YEAR - 15}–{YEAR - 12}", "grade": "15/20", "thesis": ""},
    ],
    "courses_certifications": [
        {"title": "Machine learning for multi-omics integration", "provider": "Example Courses",
         "date": f"{YEAR}-09", "topics": "machine learning, multi-omics integration, Python"},
        {"title": "Statistics and data analysis with R", "provider": "Example Training Centre",
         "date": f"{YEAR}-02", "topics": "R, statistics, data analysis"},
        {"title": "Research data management, practitioner level", "provider": "Example Institute",
         "date": f"{YEAR}-06", "topics": "data management, FAIR data"},
        {"title": "Scientific communication for researchers", "provider": "Example Academy",
         "date": f"{YEAR - 1}-04", "topics": "scientific communication"},
        {"title": "Analysis of high-throughput sequencing data", "provider": "Example Courses",
         "date": f"{YEAR - 3}", "topics": "sequencing data analysis, QC, variant calling"},
        {"title": "Introduction to Python", "provider": "Example Online School",
         "date": f"{YEAR - 5}", "topics": "Python basics"},
    ],
    "awards": [
        {"award": "Best talk by an early-career researcher",
         "event": "Example Microbiology Congress", "year": YEAR - 5},
    ],
    "skills": [
        ("Programming", "Current focus", ["Python (High)", "R (Medium)", "Git", "Linux",
                                          "Statistics"]),
        ("Data analysis", "Current focus", ["Sequencing", "Proteomics", "Metabolomics",
                                            "Imaging", "Multi-omics integration",
                                            "Normalisation", "Differential analysis",
                                            "Data visualisation", "Reusable pipelines"]),
        ("User support and project work", "Current focus", ["Scoping analyses", "Consulting",
                                                            "Written reports",
                                                            "Project organisation",
                                                            "KPI tracking"]),
        ("Teaching and communication", "Current focus", ["Course design",
                                                         "Project-based learning",
                                                         "Practical teaching",
                                                         "Informal mentoring",
                                                         "Oral and poster presentations"]),
        ("Wet lab", "Earlier work", ["Molecular biology", "Cloning", "RT-qPCR",
                                     "Protein purification", "Microbial culture"]),
    ],
    "skill_matrix": [
        ("User support and consulting", "not used", "not used", "used"),
        ("Pipeline and tool building", "not used", "used", "used"),
        ("Python", "basic", "used", "used"),
        ("R", "not used", "used", "used"),
        ("Multi-omics integration", "not used", "used", "used"),
        ("Teaching and mentoring", "used", "used", "used"),
        ("Sequencing analysis", "used", "used", "not used"),
        ("Wet lab and microbiology", "used", "not used", "not used"),
    ],
    "volunteering_languages": [
        {"item": "Local science fair: ran a hands-on data-analysis stand for school students",
         "date": f"{YEAR - 1}-05"},
        {"item": "Example language: native · English: advanced (C1)", "date": ""},
    ],
    "profiles_ids": [
        {"name": "ORCID", "id": "0000-0000-0000-0000", "url": "https://orcid.org/0000-0000-0000-0000"},
        {"name": "GitHub", "id": "example-analyst", "url": "https://github.com/example-analyst"},
    ],
}


def build_cv_data():
    """Write the invented CV content the CV page reads (and its Excel mirror)."""
    cv = dict(DEMO_CV)
    cv["skills"] = [{"area": area, "status": status, "item": item}
                    for area, status, items in DEMO_CV["skills"] for item in items]
    eras = (f"PhD era {YEAR - 9}–{YEAR - 4}", f"Postdoc {YEAR - 4}–{YEAR - 1}",
            f"Service {YEAR - 1}–now")
    cv["skill_matrix"] = [dict(zip(("skill",) + eras, row)) for row in DEMO_CV["skill_matrix"]]

    path = DATA_DIR / "cv_data.json"
    path.write_text(json.dumps(cv, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {path}")

    # The mirror is written by the app's own exporter, so the demo file matches what a save
    # would produce rather than a second, drifting implementation of the same layout.
    sys.path.insert(0, str(Path(__file__).resolve().parent / "Dashboard"))
    import kpi_data as kd

    kd.export_cv_to_excel(cv)
    print(f"wrote {DATA_DIR / 'cv_data.xlsx'}")


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


# --- 5b) Expected gains workbook: Data/SpecialProjects_Tools_expected_gains_v5.xlsx --------
# Read by Dashboard/kpi_data.py's load_expected_gains() and shown on the Gains & Outputs page.
# Column shapes here mirror the private original's own workbook exactly (same sheet names,
# same "title row + note row + blank row + real header on raw row 3" layout every sheet uses --
# see kd._GAINS_HEADER_ROW) since that's the contract the loader actually depends on; the
# CONTENT is entirely invented, but it deliberately reuses THIS script's own generated names --
# SPECIAL_PROJECTS' project names, TOOLS' tool names, FAKE_PROJECT_TAGS' project tags -- rather
# than inventing a separate vocabulary, since the loader joins this workbook to the live ratings
# sheet / tools inventory / project tracker purely BY NAME, and a mismatched name here would
# silently fall back to the workbook's own provisional Status column instead of the real
# Delivered/In use/Potential call, or drop a Reuse id as "unmatched".
EXPECTED_GAINS_IDS = {
    "Open Analysis Toolkit": "SP01", "Hands-on Workshop": "SP02", "Request Triage Tool": "SP03",
    "Template Library": "SP04", "Dataset Browser": "SP05", "Snippet Library": "SP06",
    "QC Dashboard": "T01", "variant-highlighter-skill": "T02", "intake-formatter-agent": "T03",
}
# "Report Builder" (TOOLS' 4th entry) is deliberately NOT given a row here -- a live, non-
# deprecated tool with nothing catalogued in this workbook, so the Gains page's Data health
# section has something real to flag ("unmatched_tools").

# One column per gain, grouped exactly like the private original's kd.GAIN_GROUPS -- including
# "Training" and "User capacitation" as the two already-split columns (not the old combined
# "Training & capability building"), so the demo shows off the split the loader's dynamic
# gain-column discovery exists for, straight out of the box.
GAIN_COLUMNS = [
    ("Faster project completion", "Efficiency"), ("Internal management", "Efficiency"),
    ("User capacitation", "Capability"), ("AI skills (Bigorna Project)", "Capability"),
    ("Pioneering development", "Innovation & visibility"), ("Flagship project", "Innovation & visibility"),
    ("Scientific publication", "Innovation & visibility"),
    ("New users / projects reached", "Reach & relationships"), ("Training", "Reach & relationships"),
    ("Cataloguing & outreach", "Reach & relationships"), ("Collaboration with other facilities", "Reach & relationships"),
]

# Overview rows: (Project, Category, Goal, Status, Output level, Expected gains, flags..., gains
# marked, Came from (n)/cell, served (n)/cell, Reuse level, Use pattern). Two developments
# (Hands-on Workshop, Snippet Library) are Delivered purely because build_special_projects()
# above gives them a Completed date -- this workbook's own "Status" text never overrides that.
# Lineage ("Came from: user projects" naming ANOTHER development by its own ID here, not a user
# project) gives two development-to-development chains: QC Dashboard (a TOOL) -> Dataset
# Browser, and Request Triage Tool -> Template Library -- so the evolution tree has real edges
# to draw instead of the empty state. One of them is written "T01 (output)" rather than plain
# "T01": the Dataset Browser came OUT of the QC Dashboard, which carries on, where Template
# Library replaced the Request Triage Tool. The tree draws the two with different arrows. Served/came-from ids are real FAKE_PROJECT_TAGS, so the
# project-tracker join resolves them instead of leaving them "unmatched".
EXPECTED_GAINS_OVERVIEW = [
    # Project, Category, Goal, Status, Output level, Expected gains,
    # [Internal, External, Facility, Publication, Market] flags,
    # gains marked (subset of GAIN_COLUMNS names),
    # came_from_cell, served_cell, reuse_level, use_pattern
    ("Open Analysis Toolkit", "Special Project", "01 - Reach more research groups", "In development",
     "Internal ADA", "Reusable toolkit reaching new research groups; cataloguing & outreach materials.",
     [True, True, False, False, False],
     ["Faster project completion", "New users / projects reached", "Cataloguing & outreach"],
     "META_012, SEQ_022", "", "Not defined", "Project-specific"),
    ("Hands-on Workshop", "Special Project", "01 - Reach more research groups", "Completed",
     "Internal ADA", "Hands-on outreach training; builds user capacitation among participants.",
     [True, True, False, False, True],
     ["Training", "User capacitation", "New users / projects reached"],
     "IMMU_017", "CRC_030", "Not defined", "Project-specific"),
    ("Request Triage Tool", "Special Project", "02 - Reduce turnaround time", "In use",
     "Internal ADA", "Faster project completion via automated intake triage; less admin overhead.",
     [True, False, True, False, True],
     ["Faster project completion", "Internal management"],
     "CRC_031, PLNT_004", "GEN_014, PROT_005", "Not defined", "Project-specific"),
    ("Template Library", "Special Project", "02 - Reduce turnaround time", "In development",
     "Internal ADA", "Faster, more consistent report/figure templates; less repeat setup work.",
     [True, False, False, False, False],
     ["Faster project completion", "Internal management"],
     "SP03", "", "Not defined", "Project-specific"),
    ("Dataset Browser", "Special Project", "03 - Build internal tooling", "In development",
     "Internal ADA", "Internal dataset exploration; early AI-assisted QC'd-dataset browsing.",
     [True, False, False, False, False],
     ["Internal management", "AI skills (Bigorna Project)"],
     "T01 (output)", "", "Not defined", "Project-specific"),
    ("Snippet Library", "Special Project", "03 - Build internal tooling", "Completed",
     "Internal Worker", "Faster onboarding via reusable code snippets; builds user capacitation.",
     [True, False, False, False, True],
     ["Faster project completion", "User capacitation"],
     "", "IMG_015", "Not defined", "Project-specific"),
    ("QC Dashboard", "Tools", "Tool infrastructure", "In use",
     "Facility", "Pioneering facility-specific QC dashboard; strengthens facility collaboration.",
     [True, True, True, False, True],
     ["Pioneering development", "Flagship project", "Collaboration with other facilities"],
     "", "LIP_003, META_008, SEQ_019", "Not defined", "Project-specific"),
    ("variant-highlighter-skill", "Tools", "Tool infrastructure", "In use",
     "User", "AI-assisted variant visualization; potential scientific publication.",
     [False, True, False, True, True],
     ["AI skills (Bigorna Project)", "Scientific publication"],
     "", "IMG_006, STRUCT_002", "Not defined", "Project-specific"),
    ("intake-formatter-agent", "Tools", "Tool infrastructure", "In use",
     "Internal ADA", "Faster project completion via automated intake formatting; constant internal use.",
     [True, False, False, False, False],
     ["Internal management", "Faster project completion"],
     "", "", "Constant use", "Constant use"),
]

# Value sheet: researched market-equivalent prices for a handful of developments (by name --
# joined to EXPECTED_GAINS_IDS below). Snippet Library deliberately has NO price, the same way
# the private original's own Hands-on workshop row does, to exercise the page's blank-price
# ("-") rendering.
EXPECTED_GAINS_VALUE = [
    ("Hands-on Workshop", "Internal + External", "Equivalent paid training workshop", 450, "per session"),
    ("Snippet Library", "Internal Team", "Developer onboarding time saved", None, ""),
    ("Request Triage Tool", "Facility", "Equivalent admin intake triage service", 120, "per month"),
    ("QC Dashboard", "Facility", "Equivalent commercial QC dashboard licence", 2000, "per year"),
    ("variant-highlighter-skill", "External Research Group",
     "Equivalent bioinformatics visualization consulting", 80, "per hour"),
]

EXPECTED_GAINS_NOTES = [
    "Notes & assumptions",  # title row -- dropped by the loader
    "Status column is this workbook's own provisional guess (Tools = In use, Special Projects "
    "= In development) -- not verified per row; the dashboard's live Delivered/In use/Potential "
    "call (kd._decide_state) overrides it wherever a name match is found in the ratings sheet "
    "or tools inventory.",
    "Market-equivalent values are invented, illustrative prices for this demo only -- not real "
    "income, and nothing on the page ever totals them.",
    "Report Builder (tools.xlsx) is intentionally NOT catalogued here, to demonstrate the "
    "Gains page's Data health 'unmatched tools' check.",
    "'Came from: user projects' on Template Library and Dataset Browser names another "
    "development's own ID (Request Triage Tool / QC Dashboard) rather than a user project -- "
    "that's lineage, not reuse, and QC Dashboard being a Tool shows a tool can be the parent "
    "of a Special Project too.",
]


def _write_gains_sheet_header(ws, title, note, header_cols, group_row=None):
    """Shared 'title row (1) + note row (2) + blank row (3) + real header (row 4)' layout
    every sheet in this workbook uses -- kd._GAINS_HEADER_ROW (0-indexed 3) is where pandas is
    told to start reading. `group_row`, if given, is written into row 3 instead of left blank
    (the Gains sheet's merged Efficiency/Capability/... band -- cosmetic only, kd.GAIN_GROUPS
    is the dashboard's own hardcoded record of that grouping, not read off this row)."""
    ws.append([title])
    ws.append([note])
    ws.append(group_row or [])
    ws.append(header_cols)


def build_expected_gains():
    sp_names = {p[1] for p in SPECIAL_PROJECTS}
    tool_names = {t[0] for t in TOOLS}
    for name, dev_id in EXPECTED_GAINS_IDS.items():
        if dev_id.startswith("SP"):
            assert name in sp_names, f"{name!r} (gains workbook) isn't a SPECIAL_PROJECTS name"
        else:
            assert name in tool_names, f"{name!r} (gains workbook) isn't a TOOLS name"
    for cell in (row[8] for row in EXPECTED_GAINS_OVERVIEW):
        for tok in (t.strip() for t in cell.split(",") if t.strip()):
            # A lineage parent can carry its relation in brackets ("T01 (output)"); the id
            # is what has to be real, so check the token with the relation stripped off.
            bare = tok[:tok.rindex("(")].strip() if tok.endswith(")") and "(" in tok else tok
            if bare in EXPECTED_GAINS_IDS.values():
                continue  # a lineage reference to another development's ID, not a project tag
            assert bare in FAKE_PROJECT_TAGS, f"{tok!r} (Came from) isn't a FAKE_PROJECT_TAGS tag"
    for cell in (row[9] for row in EXPECTED_GAINS_OVERVIEW):
        for tok in (t.strip() for t in cell.split(",") if t.strip()):
            assert tok in FAKE_PROJECT_TAGS, f"{tok!r} (served) isn't a FAKE_PROJECT_TAGS tag"

    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    # --- Overview ---------------------------------------------------------------------------
    ws = wb.create_sheet("Overview")
    _write_gains_sheet_header(
        ws, "Special Projects & Tools: expected gains and potential outputs (demo)",
        "All content below is invented for this public demo -- see generate_demo_data.py.",
        ["ID", "Category", "Goal", "Project", "Status", "Output level", "Expected gains",
         "Internal users", "External users", "Facility use / collaboration",
         "Publication potential", "Market-equivalent value",
         "Came from: user projects (n)", "User projects served (n)", "Reuse level (served)",
         "Gain types (n)", "Use pattern"],
    )
    for project, category, goal, status, output_level, gains_text, flags, gains_marked, \
            came_from_cell, served_cell, reuse_level, use_pattern in EXPECTED_GAINS_OVERVIEW:
        dev_id = EXPECTED_GAINS_IDS[project]
        came_from_n = (None if not came_from_cell else
                       0 if any(t.strip() in EXPECTED_GAINS_IDS.values()
                                for t in came_from_cell.split(",")) else
                       len([t for t in came_from_cell.split(",") if t.strip()]))
        served_n = ("Constant use" if use_pattern == "Constant use" else
                    (len([t for t in served_cell.split(",") if t.strip()]) or None))
        ws.append([
            dev_id, category, goal, project, status, output_level, gains_text,
            *(["x" if f else None for f in flags]),
            ("n/a" if use_pattern == "Constant use" and not came_from_cell else came_from_n),
            served_n, reuse_level, len(gains_marked), use_pattern,
        ])

    # --- Gains (wide x-marks, one column per gain, grouped under a merged-style row 3) -------
    ws = wb.create_sheet("Gains")
    group_row = [None, None]
    for name, group in GAIN_COLUMNS:
        group_row.append(group)
    group_row.append(None)
    _write_gains_sheet_header(
        ws, "Expected gains by project (demo)",
        "x = development is expected to deliver this gain.",
        ["ID", "Project"] + [name for name, _ in GAIN_COLUMNS] + ["Gain types (n)"],
        group_row=group_row,
    )
    for row in EXPECTED_GAINS_OVERVIEW:
        project, gains_marked = row[0], row[7]
        dev_id = EXPECTED_GAINS_IDS[project]
        marks = ["x" if name in gains_marked else None for name, _ in GAIN_COLUMNS]
        ws.append([dev_id, project, *marks, len(gains_marked)])

    # --- Reuse --------------------------------------------------------------------------------
    ws = wb.create_sheet("Reuse")
    _write_gains_sheet_header(
        ws, "Reuse: where each development came from and who it serves (demo)",
        "Came from = user projects (or another development's ID, for lineage) that led to it "
        "being built. User projects served = user projects that build upon it. Comma-separated.",
        ["ID", "Development / tool", "Came from (n)", "Came from: user projects",
         "User projects served (n)", "User projects served: list"],
    )
    for row in EXPECTED_GAINS_OVERVIEW:
        project, came_from_cell, served_cell, use_pattern = row[0], row[8], row[9], row[11]
        dev_id = EXPECTED_GAINS_IDS[project]
        is_lineage_only = bool(came_from_cell) and any(
            t.strip() in EXPECTED_GAINS_IDS.values() for t in came_from_cell.split(","))
        came_from_n = (None if not came_from_cell else
                        0 if is_lineage_only else
                        len([t for t in came_from_cell.split(",") if t.strip()]))
        if use_pattern == "Constant use" and not came_from_cell:
            came_from_n = "n/a"
        served_n = ("Constant use" if use_pattern == "Constant use" else
                    (len([t for t in served_cell.split(",") if t.strip()]) or None))
        ws.append([dev_id, project, came_from_n, came_from_cell or None,
                   served_n, served_cell or None])

    # --- Value --------------------------------------------------------------------------------
    ws = wb.create_sheet("Value")
    _write_gains_sheet_header(
        ws, "Value potential (market equivalents, demo)",
        "Invented, illustrative prices only -- not real income, never totalled.",
        ["ID", "Project", "Audience", "Value basis", "Unit price (€)", "Unit"],
    )
    for project, audience, basis, price, unit in EXPECTED_GAINS_VALUE:
        ws.append([EXPECTED_GAINS_IDS[project], project, audience, basis, price, unit or None])

    # --- Notes ----------------------------------------------------------------------------------
    ws = wb.create_sheet("Notes")
    for line in EXPECTED_GAINS_NOTES:
        ws.append([line])

    for name in wb.sheetnames:
        wb[name].column_dimensions["A"].width = 10
        wb[name].column_dimensions["B"].width = 26
        wb[name].column_dimensions["D" if name == "Overview" else "C"].width = 26

    path = DATA_DIR / "SpecialProjects_Tools_expected_gains_v5.xlsx"
    wb.save(path)
    print(f"wrote {path} ({len(EXPECTED_GAINS_OVERVIEW)} developments, "
          f"{len(GAIN_COLUMNS)} gain columns, {len(EXPECTED_GAINS_VALUE)} value rows)")

    # This workbook is only ever a SEED now: the dashboard builds Data/gains.xlsx from it on
    # first load and reads (and writes) that from then on, never this file again. So a
    # regenerated seed means nothing at all unless the store built from the old one is
    # cleared -- otherwise the app keeps serving the previous run's data and this script
    # looks broken. Deleting it is safe precisely because it is derived here.
    store = DATA_DIR / "gains.xlsx"
    if store.exists():
        store.unlink()
        print(f"removed {store} (rebuilt from the seed above on the next page load)")


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
              "Development", "Impact", "Maintenance", "Visibility", "Completed"]
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

    te_path = DATA_DIR / "time_entries.csv"
    pd.DataFrame(columns=TIME_ENTRY_COLS).to_csv(
        te_path, sep=";", index=False, encoding="utf-8-sig")
    print(f"wrote {te_path} (0 rows)")

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
                  "publications.json", "Publications.xlsx",
                  "cv_outputs.json", "CV_Outputs.xlsx",
                  "cv_data.json", "cv_data.xlsx", "KPI_2025.xlsx"):
        p = DATA_DIR / stray
        if p.exists():
            p.unlink()
            print(f"removed {p} (the app recreates the JSON ones correctly on first use)")

    # The Gains & Outputs page is read-only and never writes this workbook itself (openpyxl
    # would destroy hand-built charts/formulas on a real one) -- there's no "empty but present"
    # shape worth faking, so it's removed rather than written blank. The page shows a friendly
    # "workbook not found" message until one exists; see HOW_TO_RUN.md for the real shape to
    # recreate it by hand, or re-run this script without --empty for a fake example of it.
    gains_path = DATA_DIR / "SpecialProjects_Tools_expected_gains_v5.xlsx"
    if gains_path.exists():
        gains_path.unlink()
        print(f"removed {gains_path} (Gains & Outputs page shows a friendly empty-state message without it)")

    print(f"\nDone. Data/ is now a blank {year} starting point -- open the dashboard and use "
          "Add Data to fill it in, or edit the Excel/CSV files directly.")


if __name__ == "__main__":
    if "--empty" in sys.argv:
        build_empty()
    else:
        projects = build_project_tracker()
        build_time_log(projects)
        build_time_entries(projects)
        build_special_projects()
        build_beyond_projects()
        build_publications()
        build_cv_outputs()
        build_cv_data()
        build_tools()
        build_expected_gains()
        build_custom_tags()
        print(f"\nDone. Demo data covers calendar year {YEAR}.")
