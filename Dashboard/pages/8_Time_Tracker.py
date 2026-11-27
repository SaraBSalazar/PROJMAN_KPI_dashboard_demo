"""Time Tracker — a stopwatch over the same vocabulary the rest of the dashboard uses, and
the two views that make a week of it readable. Run the dashboard with:
  streamlit run KPI_Report.py  (this page is routed to by that entrypoint's
st.navigation, not run directly).

Why a second time store: track_time.csv is one row per (project, category, major task) per
WEEK, which is the right shape to report and a hopeless shape to record in — by Friday
nobody remembers how Tuesday actually went. Data/time_entries.csv holds the other half:
one row per stretch of work with a real start and end. The two meet in "Send this week to
the time log", which folds the week's stretches into exactly the weekly rows the log
already has, shows you every row it would write first, and leaves the Week editor on the
Overview page as the last word. Nothing here writes track_time.csv on its own.

The project / category / major task dropdowns are the same vocabulary the Week editor
offers (kd.tag_options), and a tag typed here is saved to
custom_tags.json like one typed there — so time tracked on this page arrives in the time
log already filed the way every chart in the dashboard expects."""

import datetime as dt
import html

import pandas as pd
import streamlit as st

import kpi_activity as ka
import kpi_cache as kcache
import kpi_calendar as kcal
import kpi_charts as kc
import kpi_data as kd
import kpi_style as ks

st.set_page_config(page_title="Time Tracker", page_icon="⏱", layout="wide")
DARK = st.context.theme.type == "dark"
kc.set_theme(dark=DARK)
ks.inject(dark=DARK)

# A link with ?readonly=true hides every editing control on every page (session_state keeps
# it in effect across page navigation even if the URL's query string itself gets dropped by
# the sidebar's client-side routing; re-checking query_params each page still lets a direct
# deep-link into another page with ?readonly=true on it work on its own).
if st.query_params.get("readonly") is not None:
    st.session_state["readonly"] = st.query_params.get("readonly") in ("1", "true", "yes", "True")
READONLY = st.session_state.get("readonly", False)

TOKENS = ks.DARK if DARK else ks.LIGHT
NOW = pd.Timestamp.now().floor("s")

# Which tracker field each "group by" choice reads. The first three are what the rest of the
# dashboard is keyed on; the last is whatever was typed on the stretch itself.
LEVELS = {
    "Project": "project", "Category": "category", "Major task": "major_task",
    "Description": "description",
}
NONE_LEVEL = "— just the totals —"
DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

st.markdown(
    f"""<style>
.tt-clock {{
  font-family: "IBM Plex Mono", ui-monospace, monospace;
  font-size: 2.1rem; font-weight: 600; font-variant-numeric: tabular-nums;
  line-height: 1.1; color: {TOKENS['accent']};
}}
.tt-live {{ color: {TOKENS['ink3']}; font-size: 0.78rem; font-weight: 600;
            text-transform: uppercase; letter-spacing: 0.08em; }}
.tt-filed {{ color: {TOKENS['ink2']}; font-size: 0.9rem; }}

/* The breakdown grid. Wide weeks scroll inside this box rather than the page. */
.tt-table-wrap {{ overflow-x: auto; }}
.tt-table {{ width: 100%; border-collapse: collapse; font-size: 0.9rem; }}
.tt-table th, .tt-table td {{ padding: 0.42rem 0.7rem; text-align: right; white-space: nowrap; }}
.tt-table th:first-child, .tt-table td:first-child {{ text-align: left; width: 32%; min-width: 14rem; }}
.tt-table thead th {{
  color: {TOKENS['ink3']}; font-size: 0.72rem; font-weight: 600;
  text-transform: uppercase; letter-spacing: 0.06em;
  border-bottom: 1px solid {TOKENS['line']};
}}
.tt-table td {{ font-variant-numeric: tabular-nums; }}
.tt-l1 td {{ font-weight: 600; border-top: 1px solid {TOKENS['line']}; }}
.tt-l2 td {{ color: {TOKENS['ink2']}; font-weight: 400; }}
.tt-l2 td:first-child {{ padding-left: 2.1rem; }}
.tt-zero {{ color: {TOKENS['ink3']}; }}
.tt-table tfoot th {{
  border-top: 2px solid {TOKENS['line']}; color: {TOKENS['ink2']};
  font-variant-numeric: tabular-nums; font-size: 0.9rem;
}}
.tt-dot {{ display: inline-block; width: 0.6rem; height: 0.6rem; border-radius: 50%;
           margin-right: 0.5rem; vertical-align: middle; }}
</style>""",
    unsafe_allow_html=True,
)

ks.header(
    "⏱ Time Tracker",
    "Start a timer, see the week as a calendar and as a breakdown, then send it to the time log",
)
if READONLY:
    st.info("📖 Read-only view — the timer, the entry table and the push to the time log are hidden.",
            icon="📖")

# ============================================================================================
# DATA + SHARED VOCABULARY
# ============================================================================================
entries = kcache.load_time_entries()
timelog_df, CATEGORY_ORDER, CATEGORY_COLORS, _task_category, timelog_raw = kcache.load_timelog(dark=DARK)
custom_tags = kd.load_custom_tags()
options = kd.tag_options(timelog_df, custom_tags, CATEGORY_ORDER)

# Tags used in the tracker but not (yet) anywhere else: a stretch filed under a brand-new
# project is pickable again tomorrow without having to be pushed to the time log first.
TAG_FIELDS = {"project": "projects", "category": "categories", "major_task": "major_tasks"}
for field, key in TAG_FIELDS.items():
    extra = sorted({str(v).strip() for v in entries[field].unique() if str(v).strip()}
                   - set(options[key]))
    options[key] = options[key] + extra  # appended, so the ordered category list stays ordered


def extend_palette(base_colors, names):
    """Keep every colour the rest of the dashboard already uses for these values, and give
    anything the tracker knows about but the time log doesn't a palette slot the log isn't
    using yet — so a category is the same colour here as on the Overview page, and two
    brand-new ones aren't both silently the same grey."""
    palette = kd.TL_PALETTE_DARK if DARK else kd.TL_PALETTE
    out = dict(base_colors)
    free = [c for c in palette if c not in set(out.values())] or palette
    for i, name in enumerate(sorted(n for n in names if n and n not in out)):
        out[name] = free[i % len(free)]
    return out


# Projects are coloured from their ALL-TIME hours, not this week's, for the same reason every
# other chart here does it that way: a project that keeps its colour week to week is one you
# can recognise, and a palette rebuilt per week repaints the survivors every time.
_project_hours = pd.concat([
    timelog_df[["Project", "Hours (exact)"]].rename(columns={"Project": "_n", "Hours (exact)": "_h"}),
    entries[["project", "hours"]].rename(columns={"project": "_n", "hours": "_h"}),
], ignore_index=True)
_project_hours["_n"] = _project_hours["_n"].fillna("").astype(str).str.strip()
_, PROJECT_COLORS = kd.build_category_palette(
    _project_hours[_project_hours["_n"] != ""], category_col="_n", value_col="_h", dark=DARK)
CATEGORY_COLORS = extend_palette(CATEGORY_COLORS, set(entries["category"]))
OTHER_COLORS = {
    "major_task": extend_palette({}, set(entries["major_task"])),
    "description": extend_palette({}, set(entries["description"])),
}


def colors_for(field):
    if field == "category":
        return CATEGORY_COLORS
    if field == "project":
        return PROJECT_COLORS
    return OTHER_COLORS.get(field, {})


def tag_cells(series):
    """A tracker text column -> the one-item lists a MultiselectColumn cell wants."""
    return pd.Series([kd.tag_to_cell(v) for v in series], index=series.index, dtype=object)


def remember_tags(frame, cols=TAG_FIELDS):
    """Persist any tag typed into the tracker to custom_tags.json, so it stays in the
    dropdowns here AND in the Week editor even before a row in the time log uses it.
    Failing to record one is never worth losing a save that already succeeded."""
    fresh = {key: sorted({str(v).strip() for v in frame[field]
                          if str(v).strip() and str(v).strip() not in set(options[key])})
             for field, key in cols.items()}
    if not any(fresh.values()):
        return []
    try:
        return kd.add_custom_tags(**fresh)
    except OSError:
        return []


# ============================================================================================
# THE TIMER
# ============================================================================================
running = kd.running_entry(entries)


@st.fragment(run_every="1s")
def running_clock(started_iso):
    """The elapsed-time readout, in a fragment so it ticks once a second without rerunning
    the whole page (and without touching a file). Every button lives outside it — a control
    inside a fragment that reruns every second is a control you can lose a click on."""
    started = pd.Timestamp(started_iso)
    seconds = max(int((pd.Timestamp.now() - started).total_seconds()), 0)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    st.markdown('<div class="tt-live">running</div>'
                f'<div class="tt-clock">{h}:{m:02d}:{s:02d}</div>', unsafe_allow_html=True)


def save_entries(frame, success, remember=True):
    """Write the tracker store and rerun, or explain why it couldn't be written."""
    try:
        kd.save_time_entries(frame)
    except PermissionError:
        st.error("Couldn't save — time_entries.csv is open in Excel or another program. "
                 "Close it and try again.")
        return False
    if remember:
        remember_tags(frame)
    st.session_state["tt_flash"] = success
    st.rerun()


flash = st.session_state.pop("tt_flash", None)
if flash:
    st.success(flash)


# --- "were you actually here?" ----------------------------------------------------------
# One watcher per Streamlit server process, which is exactly what st.cache_resource is for.
# It polls the OS idle clock in a daemon thread for as long as the app is up -- including
# while another page is open, which is the whole point: the timer runs while you work, not
# while you look at this page.
@st.cache_resource(show_spinner=False)
def activity_watcher():
    watcher = ka.ActivityWatcher()
    watcher.start()
    return watcher


watcher = None if READONLY else activity_watcher()
away = []
if running is not None and watcher is not None:
    away = ka.away_periods(pd.Timestamp(running["start"]).to_pydatetime(), NOW.to_pydatetime(),
                           state=watcher.snapshot(), watcher_started=watcher.started_at)

if away:
    run_start = pd.Timestamp(running["start"]).to_pydatetime()
    with st.container(border=True):
        st.markdown("#### ⏸ You were away while this timer ran")
        st.caption("Tick what shouldn't count as work. Cutting a stretch out of the middle "
                   "splits the entry in two — the work before it and the work after — since "
                   "there's nowhere in one entry to record a hole.")
        away_rows = pd.DataFrame([{
            # Idle is ticked by default: it is what you asked to be asked about. A window
            # nobody was watching is only ticked when it is long enough to be suspicious --
            # restarting the dashboard mid-morning leaves a short one that IS work.
            "Cut": p["kind"] == "idle" or p["minutes"] >= 15,
            "What happened": ("no keyboard or mouse" if p["kind"] == "idle"
                              else "the tracker wasn't running"),
            "From": p["from"].strftime("%a %H:%M"), "To": p["to"].strftime("%a %H:%M"),
            "How long": kd.format_hm(p["minutes"] / 60),
        } for p in away])
        picked_rows = st.data_editor(
            away_rows, hide_index=True, width="stretch", num_rows="fixed", key="tt_away",
            disabled=["What happened", "From", "To", "How long"],
            column_config={"Cut": st.column_config.CheckboxColumn(
                "Cut", default=False, width="small", help="Tick to take this time off the entry.")},
        )
        picked = [p for p, cut in zip(away, picked_rows["Cut"]) if bool(cut)]
        stretches = ka.active_stretches(run_start, NOW.to_pydatetime(), picked)
        kept = sum((b - a).total_seconds() for a, b in stretches) / 3600
        total = (NOW.to_pydatetime() - run_start).total_seconds() / 3600

        if not picked:
            st.caption(f"Nothing ticked — the entry stays at {kd.format_hm(total)}.")
        elif not stretches:
            st.caption(f"Everything ticked — all {kd.format_hm(total)} goes, and the entry "
                       "with it.")
        else:
            st.caption(f"**{kd.format_hm(kept)}** of {kd.format_hm(total)} would be kept, as "
                       f"{len(stretches)} entr{'y' if len(stretches) == 1 else 'ies'}.")

        a1, a2, a3, _ = st.columns([1.5, 1.3, 1.2, 2])
        if a1.button("✂ Cut it, keep tracking", key="tt_away_cut_go", type="primary",
                     disabled=not picked,
                     help="The timer carries on from the moment you came back."):
            ka.acknowledge(NOW.to_pydatetime())
            st.session_state.pop("tt_away", None)
            save_entries(kd.split_entry(entries, running["id"], stretches, keep_running=True),
                         f"Away time cut — {kd.format_hm(kept)} kept, still tracking.")
        if a2.button("✂ Cut it and stop", key="tt_away_cut_stop", disabled=not picked):
            ka.acknowledge(NOW.to_pydatetime())
            st.session_state.pop("tt_away", None)
            save_entries(kd.split_entry(entries, running["id"], stretches, keep_running=False),
                         f"Away time cut — {kd.format_hm(kept)} kept, timer stopped.")
        if a3.button("✓ Keep it all", key="tt_away_keep"):
            ka.acknowledge(NOW.to_pydatetime())
            st.session_state.pop("tt_away", None)
            st.session_state["tt_flash"] = "Kept as tracked."
            st.rerun()

if not READONLY:
    with st.container(border=True):
        if running is not None:
            c_desc, c_clock, c_stop = st.columns([3.2, 1.3, 1.5], vertical_alignment="center")
            filed = " · ".join(v for v in (running["project"], running["category"],
                                           running["major_task"]) if str(v).strip())
            started = pd.Timestamp(running["start"])
            c_desc.markdown(
                f"**{html.escape(str(running['description']).strip() or '(no description)')}**  \n"
                f'<span class="tt-filed">{html.escape(filed or "not filed yet")} · '
                f'started {started.strftime("%H:%M")}</span>', unsafe_allow_html=True)
            with c_clock:
                running_clock(running["start"])
            with c_stop:
                if st.button("⏹ Stop", type="primary", key="tt_stop", width="stretch"):
                    stopped = kd.stop_entry(entries, pd.Timestamp.now().floor("s"))
                    elapsed = (pd.Timestamp.now() - started).total_seconds() / 3600
                    save_entries(stopped, f"Stopped — {kd.format_hm(max(elapsed, 0))} logged.")
                if st.button("🗑 Discard", key="tt_discard",
                             help="Delete this running entry without recording it.", width="stretch"):
                    save_entries(kd.delete_entries(entries, [running["id"]]),
                                 "Running entry discarded.", remember=False)
        else:
            c = st.columns([3.2, 1.6, 1.5, 1.6, 1.1], vertical_alignment="bottom")
            desc = c[0].text_input("What are you working on?", key="tt_desc",
                                   placeholder="e.g. rewriting the intake parser")
            project = c[1].selectbox("Project", options["projects"], index=None,
                                     accept_new_options=True, key="tt_project",
                                     placeholder="pick or type")
            category = c[2].selectbox("Category", options["categories"], index=None,
                                      accept_new_options=True, key="tt_category",
                                      placeholder="pick or type")
            task = c[3].selectbox("Major task", options["major_tasks"], index=None,
                                  accept_new_options=True, key="tt_task",
                                  placeholder="pick or type")
            start_clicked = c[4].button("▶ Start", type="primary", key="tt_start", width="stretch")

            note = st.text_input("Notes (optional)", key="tt_note",
                                 placeholder="anything worth remembering about this stretch")

            if start_clicked:
                save_entries(
                    kd.start_entry(entries, pd.Timestamp.now().floor("s"), description=desc,
                                   project=project, category=category, major_task=task,
                                   notes=note),
                    "Timer started." + (" The one that was running was stopped."
                                        if running is not None else ""))

    st.caption("Starting a timer stops whatever was running — one at a time, like a stopwatch. "
               "You can leave the tags blank now and fill them in on the table below; only the "
               "ones you eventually fill reach the time log.")

    with st.expander("⚙ Away detection — when should the tracker ask whether you were here?"):
        if not ka.available():
            st.info("This machine can't report keyboard/mouse activity, so idle stretches "
                    "won't be detected. Stretches where the dashboard itself wasn't running "
                    "are still spotted — those need no help from the operating system.",
                    icon="ℹ️")
        activity_state = ka.load_state()
        current = int(activity_state.get("idle_minutes", ka.DEFAULT_IDLE_MINUTES))
        s1, s2 = st.columns([1.2, 3])
        chosen = s1.number_input("Minutes with no keyboard or mouse", min_value=1, max_value=120,
                                 value=current, step=1, key="tt_idle_minutes")
        if int(chosen) != current:
            ka.set_idle_minutes(int(chosen))
            st.rerun()
        with s2:
            st.caption(
                f"While a timer runs, a stretch longer than this with nothing typed or clicked "
                f"is offered back to you to keep or cut — you are asked when you come back, not "
                f"interrupted while you're away. Toggl's own default is 5 minutes. "
                f"The watcher has been looking since "
                f"**{watcher.started_at.strftime('%H:%M') if watcher else '—'}**; anything "
                f"before that, or while the dashboard was shut or the machine asleep, shows up "
                f"as *the tracker wasn't running* rather than being quietly counted as work. "
                f"None of this is in `Data/` — it's about this computer, so it lives in "
                f"`{ka.STATE_PATH.parent}`.")

# ============================================================================================
# THE WEEK
# ============================================================================================
st.divider()
PICK = "tt_week_pick"
if PICK not in st.session_state:
    st.session_state[PICK] = kd.week_start_of(NOW).date()

nav = st.columns([0.5, 0.5, 0.8, 1.7, 4.5], vertical_alignment="center")
# These write the date widget's own session_state key, which is why they are called BEFORE it
# is instantiated below: setting a widget's value after it exists in the same run is an error.
if nav[0].button("◀", key="tt_prev", help="Previous week", width="stretch"):
    st.session_state[PICK] = st.session_state[PICK] - dt.timedelta(7)
if nav[1].button("▶", key="tt_next", help="Next week", width="stretch"):
    st.session_state[PICK] = st.session_state[PICK] + dt.timedelta(7)
if nav[2].button("Today", key="tt_today", width="stretch"):
    st.session_state[PICK] = kd.week_start_of(NOW).date()
nav[3].date_input("Week", key=PICK, format="DD/MM/YYYY", label_visibility="collapsed",
                  help="Any day in the week — it snaps to that week's Monday.")

week_start = kd.week_start_of(st.session_state[PICK])
week_end = week_start + pd.Timedelta(7, "D")
week_label = kd.format_week_label(week_start, week_start + pd.Timedelta(6, "D"))
nav[4].markdown(f"**Week of {week_label}**"
                + ("  ·  this week" if week_start == kd.week_start_of(NOW) else ""))

# Drawn with `now`, so a timer that is still going is drawn growing. Pushed WITHOUT it, so
# time that hasn't stopped yet never reaches the time log — see kd.timelog_push_preview.
segments = kd.entry_segments(entries, week_start, now=NOW)
week_entries = entries[(entries["start_dt"] >= week_start) & (entries["start_dt"] < week_end)]
proposals = kd.timelog_push_preview(timelog_df, timelog_raw,
                                    kd.entry_segments(entries, week_start, now=None), week_start)
n_to_push = sum(1 for p in proposals if p["status"] in ("new", "changed"))

tracked_hours = float(segments["hours"].sum()) if len(segments) else 0.0
m1, m2, m3, m4 = st.columns(4)
m1.metric("Tracked this week", kd.format_hm(tracked_hours))
m2.metric("Entries", int(week_entries["id"].nunique()))
m3.metric("Days with time on them", int(segments["day"].nunique()) if len(segments) else 0)
m4.metric("Rows the time log is missing", n_to_push,
          help="Combinations of project / category / major task whose "
               "tracked hours this week aren't in track_time.csv yet, or no longer match it. "
               "Send them down in the panel at the bottom of this page.")

# --- the work calendar ----------------------------------------------------------------------
# Read-only, over the calendar's own iCal address. This is the ONLY thing on the page that
# needs a network: the timer, both views and the push to the time log are local files, and
# a dropped connection never reaches them. kcal.load_calendar falls back to the last copy it
# fetched, so an outage costs the planned layer its freshness, not its existence.
@st.cache_data(show_spinner=False, ttl=600)
def fetch_calendar(url, bust):
    """`bust` is a counter the refresh button bumps -- it is part of the cache key on
    purpose, which is how a manual refresh gets past the ten-minute TTL."""
    return kcal.load_calendar(url)


cal_settings = kcal.load_settings()
cal_payload, cal_error = None, None
if cal_settings["url"]:
    try:
        cal_payload = fetch_calendar(cal_settings["url"], st.session_state.get("tt_cal_bust", 0))
    except kcal.CalendarError as exc:
        cal_error = str(exc)

planned_events, all_day_titles = [], []
if cal_payload:
    try:
        planned_events, all_day_titles = kcal.events_in_week(
            cal_payload["ics"], week_start, cal_settings)
    except (ValueError, KeyError, TypeError) as exc:
        cal_error = f"The calendar downloaded, but couldn't be read: {exc}"
planned_blocks = kcal.planned_blocks(planned_events, week_start) if planned_events else []
planned_hours = sum(b["hours"] for b in planned_blocks)

tab_cal, tab_break = st.tabs(["📅 Calendar", "📊 Breakdown"])

# --- View 1: the calendar -------------------------------------------------------------------
with tab_cal:
    c_opt1, c_opt2 = st.columns([2, 2])
    color_by_label = c_opt1.radio("Colour blocks by", ["Category", "Project"], horizontal=True,
                                  key="tt_color_by",
                                  help="Category uses the same colours as every chart on the "
                                       "Overview page, so a week reads the same way here as it does there.")
    show_planned = bool(planned_blocks) and c_opt2.toggle(
        "Show what the calendar planned", value=True, key="tt_show_planned",
        help="Your work calendar's events, drawn as a grey wash behind the tracked blocks.")
    color_by = LEVELS[color_by_label]

    if cal_error and cal_settings["url"]:
        st.warning(f"Calendar: {cal_error}", icon="📅")
    elif cal_payload and cal_payload["stale"]:
        st.info(f"Showing the calendar as it was at "
                f"**{cal_payload['fetched_at'].strftime('%a %d %b, %H:%M')}** — it couldn't be "
                f"refreshed just now ({cal_payload['error']}). Everything else on this page is "
                f"local files and is unaffected.", icon="📶")

    st.plotly_chart(
        kc.fig_week_calendar(segments, week_start, color_by=color_by,
                             colors=colors_for(color_by), now=NOW,
                             title=f"Week of {week_label}",
                             planned=planned_blocks if show_planned else None),
        width="stretch", key="tt_calendar")
    st.caption("One block per stretch of work, placed at the hour it happened. Overlapping "
               "stretches sit side by side; a stretch running past midnight is drawn in both "
               "days. Hover a block for the description, how it's filed, and its exact span. "
               "Day totals are in the column headers.")

    if show_planned:
        share = f" — {tracked_hours / planned_hours:.0%} of it" if planned_hours else ""
        st.caption(f"Grey blocks are calendar events: **{kd.format_hm(planned_hours)}** planned "
                   f"this week against **{kd.format_hm(tracked_hours)}** tracked{share}. "
                   "They're drawn for comparison only — nothing from the calendar counts as "
                   "tracked time until you add it below."
                   + (f"  \nAll-day events this week (not drawn, they aren't blocks of work): "
                      f"*{', '.join(all_day_titles)}*." if all_day_titles else ""))

    # --- turning a calendar event into a tracked entry ---------------------------------------
    if planned_events and not READONLY:
        st.divider()
        st.markdown("##### 📅 Track something from the calendar")
        st.caption("Tick a meeting you actually attended, file it the way the rest of the "
                   "dashboard expects, and it becomes a tracked entry with the event's own "
                   "times. The ✓ column says how much of it you've already tracked, so a "
                   "meeting doesn't get added twice.")
        event_rows = pd.DataFrame([{
            "Track": False,
            "✓": ("already tracked" if kcal.tracked_overlap(e, entries) >= 0.9 * max(e["hours"], 1e-9)
                  else ("partly" if kcal.tracked_overlap(e, entries) > 0.05 else "")),
            "Event": e["title"].replace("\n", " ")[:70],
            "When": f"{e['from']:%a %d} {e['from']:%H:%M}–{e['to']:%H:%M}",
            "Hours": kd.format_hm(e["hours"]),
            "Project": [], "Category": [], "Major task": [],
        } for e in planned_events])
        picked_events = st.data_editor(
            event_rows, hide_index=True, width="stretch", num_rows="fixed",
            key=f"tt_events_{week_start.date()}",
            disabled=["✓", "Event", "When", "Hours"],
            column_config={
                "Track": st.column_config.CheckboxColumn("Track", default=False, width="small"),
                "✓": st.column_config.TextColumn("✓", width="small",
                                                 help="Whether tracked time already covers this event."),
                **{label: st.column_config.MultiselectColumn(
                    label, options=options[key], accept_new_options=True, color="primary")
                   for label, key in (("Project", "projects"), ("Category", "categories"),
                                      ("Major task", "major_tasks"))},
            },
        )
        if st.button("➕ Add the ticked events as entries", key=f"tt_events_add_{week_start.date()}",
                     type="primary"):
            updated, added = entries, 0
            for event, (_, row) in zip(planned_events, picked_events.iterrows()):
                if not bool(row["Track"]):
                    continue
                updated = kd.add_entry(
                    updated, event["from"], event["to"],
                    description=event["title"].replace("\n", " "),
                    project=kd.tag_from_cell(row["Project"]),
                    category=kd.tag_from_cell(row["Category"]),
                    major_task=kd.tag_from_cell(row["Major task"]))
                added += 1
            if not added:
                st.info("Nothing ticked — nothing added.")
            else:
                st.session_state.pop(f"tt_events_{week_start.date()}", None)
                save_entries(updated, f"Added {added} entr{'y' if added == 1 else 'ies'} from the "
                                      "calendar. Edit their times in the table below if they ran over.")

    # --- connecting it ------------------------------------------------------------------------
    if not READONLY:
        connected = bool(cal_settings["url"])
        with st.expander("📅 " + ("Google Calendar — connected" if connected
                                  else "Connect your Google Calendar (no coding needed)"),
                         expanded=not connected):
            st.markdown("""
**What this does.** It *reads* your calendar and draws your meetings behind the tracked
blocks, so you can see what the week was meant to be next to what it actually was. It can
never change, add or delete anything in your calendar — the address below is read-only.

**Getting the address — six clicks, no coding:**

1. Open **Google Calendar** in a browser on a computer (this can't be done in the phone app).
2. Hover the calendar you want in the left-hand list, click its **⋮** menu, and choose
   **Settings and sharing**.
3. Scroll right down to **Integrate calendar**.
4. Copy **Secret address in iCal format** — the long one ending in `.ics`. Click the eye
   icon first if it's hidden.
5. Paste it in the box below and click **Save**.
6. That's it. Your meetings appear behind the week.

**Secret or public?** Either works — the dashboard just downloads the file. The **public**
address (`.../public/basic.ics`) only exists while the calendar is shared publicly with the
whole internet, which a work calendar shouldn't be; if it isn't, Google answers 404. The
**secret** address works whatever the sharing settings are, which is why it's the one to use.
Treat it like a password: anyone who has it can read that calendar. It's stored on this
computer only, and never in the project folder.
""")
            new_url = st.text_input(
                "Secret iCal address", value=cal_settings["url"], type="password",
                placeholder="https://calendar.google.com/calendar/ical/…/private-…/basic.ics",
                help="Shown as dots because it's a credential. Paste over it to replace it.")
            e1, e2 = st.columns([2, 1.4])
            new_email = e1.text_input(
                "Your email on that calendar (optional)", value=cal_settings["email"],
                placeholder="you@example.org",
                help="Only used to drop meetings you declined — they're not planned work. "
                     "Leave it blank and every event is shown.")
            new_skip = e2.checkbox("Skip meetings I declined", value=cal_settings["skip_declined"],
                                   disabled=not new_email)

            b1, b2, b3 = st.columns([1, 1, 2])
            if b1.button("💾 Save", key="tt_cal_save", type="primary"):
                try:
                    kcal.save_settings(url=new_url.strip(), email=new_email.strip(),
                                       skip_declined=bool(new_skip))
                except kcal.CalendarError as exc:
                    st.error(str(exc))
                else:
                    fetch_calendar.clear()
                    st.session_state["tt_flash"] = ("Calendar settings saved."
                                                    if new_url.strip() else "Calendar disconnected.")
                    st.rerun()
            if b2.button("🔄 Refresh now", key="tt_cal_refresh", disabled=not connected,
                         help="The calendar is re-downloaded every 10 minutes anyway."):
                st.session_state["tt_cal_bust"] = st.session_state.get("tt_cal_bust", 0) + 1
                st.rerun()
            if connected and cal_payload:
                b3.caption(f"Last downloaded **{cal_payload['fetched_at']:%a %d %b, %H:%M}** · "
                           f"{len(planned_events)} event(s) this week.")
            elif connected and cal_error:
                b3.caption("Not reachable right now.")

# --- View 2: the breakdown ------------------------------------------------------------------
with tab_break:
    g1, g2, _ = st.columns([1.3, 1.3, 3])
    level1_label = g1.selectbox("Group by", list(LEVELS), index=0, key="tt_level1")
    level2_label = g2.selectbox("Then by", [NONE_LEVEL] + list(LEVELS), index=3, key="tt_level2")
    level1 = LEVELS[level1_label]
    level2 = LEVELS.get(level2_label) if level2_label != NONE_LEVEL else None
    if level2 == level1:
        level2 = None

    grid = kd.tracker_breakdown(segments, level1, level2)
    group_colors = colors_for(level1)

    def cell(hours):
        return (f"{kd.format_hm(hours)}" if hours
                else '<span class="tt-zero">–</span>')

    if not grid["groups"]:
        st.info("Nothing tracked this week yet — the calendar tab says the same thing with "
                "more space.")
    else:
        head = "".join(f"<th>{DAY_NAMES[d]} {(week_start + pd.Timedelta(d, 'D')).day}</th>"
                       for d in range(7))
        body = []
        for group in grid["groups"]:
            dot = group_colors.get(group["label"], TOKENS["ink3"])
            days = "".join(f"<td>{cell(h)}</td>" for h in group["days"])
            body.append(
                f'<tr class="tt-l1"><td><span class="tt-dot" style="background:{dot}"></span>'
                f'{html.escape(group["label"])}</td>{days}'
                f'<td>{kd.format_hm(group["total"])}</td></tr>')
            for child in group["children"]:
                child_days = "".join(f"<td>{cell(h)}</td>" for h in child["days"])
                body.append(f'<tr class="tt-l2"><td>{html.escape(child["label"])}</td>'
                            f'{child_days}<td>{kd.format_hm(child["total"])}</td></tr>')
        foot = "".join(f"<th>{cell(h)}</th>" for h in grid["day_totals"])
        st.markdown(
            f'<div class="tt-table-wrap"><table class="tt-table">'
            f'<thead><tr><th>{html.escape(level1_label)}</th>{head}<th>Total</th></tr></thead>'
            f'<tbody>{"".join(body)}</tbody>'
            f'<tfoot><tr><th>Total</th>{foot}<th>{kd.format_hm(grid["total"])}</th></tr></tfoot>'
            f'</table></div>', unsafe_allow_html=True)
        st.caption(f"Hours per day for every {level1_label.lower()} this week"
                   + (f", split by {level2_label.lower()}." if level2 else ".")
                   + " Ordered by total, so the week reads top-down as where the time went. "
                     "A still-running timer counts the time it has run so far.")

# ============================================================================================
# THE ENTRIES — the table the two views are drawn from
# ============================================================================================
st.divider()
st.subheader(f"Entries — week of {week_label}")

editable = week_entries[~week_entries["running"]].sort_values("start_dt", kind="stable")
orig_ids = list(editable["id"])

if READONLY:
    st.dataframe(
        pd.DataFrame({
            "Date": [d.date() for d in editable["start_dt"]],
            "Start": [d.strftime("%H:%M") for d in editable["start_dt"]],
            "End": [d.strftime("%H:%M") for d in editable["end_dt"]],
            "Duration": [kd.format_hm(h) for h in editable["hours"]],
            "Project": list(editable["project"]), "Category": list(editable["category"]),
            "Major task": list(editable["major_task"]),
            "Description": list(editable["description"]),
        }), width="stretch", hide_index=True)
else:
    N_BLANK_ROWS = 5
    blanks = range(len(editable), len(editable) + N_BLANK_ROWS)
    editor_df = pd.concat([
        pd.DataFrame({
            "🗑": False,
            "Date": [d.date() for d in editable["start_dt"]],
            "Start": [d.time() for d in editable["start_dt"]],
            "End": [d.time() for d in editable["end_dt"]],
            "Duration": [kd.format_hm(h) for h in editable["hours"]],
            "Project": tag_cells(editable["project"]),
            "Category": tag_cells(editable["category"]),
            "Major task": tag_cells(editable["major_task"]),
            "Description": list(editable["description"]),
            "Notes": list(editable["notes"]),
        }).reset_index(drop=True),
        # dtype=object on the tag columns explicitly: on a week with no entries the blanks
        # would otherwise come out all-NA float, which MultiselectColumn rejects.
        pd.DataFrame({
            "🗑": pd.Series([False] * N_BLANK_ROWS, index=blanks),
            "Date": pd.Series([None] * N_BLANK_ROWS, index=blanks, dtype=object),
            "Start": pd.Series([None] * N_BLANK_ROWS, index=blanks, dtype=object),
            "End": pd.Series([None] * N_BLANK_ROWS, index=blanks, dtype=object),
            "Duration": pd.Series([""] * N_BLANK_ROWS, index=blanks, dtype=object),
            **{col: pd.Series([[] for _ in range(N_BLANK_ROWS)], index=blanks, dtype=object)
               for col in ("Project", "Category", "Major task")},
            **{col: pd.Series([""] * N_BLANK_ROWS, index=blanks, dtype=object)
               for col in ("Description", "Notes")},
        })[["🗑", "Date", "Start", "End", "Duration", "Project", "Category", "Major task",
            "Description", "Notes"]],
    ])

    st.caption("Edit a stretch's times or tags, or fill a blank row at the bottom for one you "
               "forgot to track — nothing is written until you save. An End earlier than the "
               "Start is read as crossing midnight. Tick 🗑 to remove a row on save. The timer "
               "that's running now isn't listed: stop it first.")
    editor_key = f"tt_editor_{week_start.date()}"
    edited = st.data_editor(
        editor_df, num_rows="fixed", width="stretch", key=editor_key,
        column_config={
            "🗑": st.column_config.CheckboxColumn("🗑", default=False, width="small",
                                                  help="Tick to delete this row when you save."),
            "Date": st.column_config.DateColumn("Date", format="ddd DD MMM"),
            "Start": st.column_config.TimeColumn("Start", format="HH:mm", step=60),
            "End": st.column_config.TimeColumn("End", format="HH:mm", step=60),
            "Duration": st.column_config.TextColumn(
                "Duration", disabled=True, width="small",
                help="Worked out from Start and End — it catches up when you save."),
            **{label: st.column_config.MultiselectColumn(
                label, options=options[key], accept_new_options=True, color="primary",
                help="Pick a tag, or type a new one and press Enter. One tag per cell.")
               for label, key in (("Project", "projects"), ("Category", "categories"),
                                  ("Major task", "major_tasks"))},
        },
    )

    if st.button("💾 Save entries", key=f"tt_save_{week_start.date()}", type="primary"):
        rows, incomplete, overfilled = [], 0, False
        for i in edited.index:
            row = edited.loc[i]
            if bool(row["🗑"]):
                continue
            tags = {}
            for field, label in (("project", "Project"), ("category", "Category"),
                                 ("major_task", "Major task")):
                overfilled |= kd.tag_cell_overfilled(row[label])
                tags[field] = kd.tag_from_cell(row[label])
            date, start_t, end_t = row["Date"], row["Start"], row["End"]
            is_new = i >= len(orig_ids)

            if date is None or start_t is None or end_t is None:
                if is_new:
                    # An untouched blank row is just an unused row; a half-filled one is a
                    # mistake worth saying out loud rather than writing a nonsense span.
                    if any([date, start_t, end_t, tags["project"], str(row["Description"] or "").strip()]):
                        incomplete += 1
                    continue
                # An original row whose Date/Start/End got cleared keeps the times it already
                # had: blanking a cell should never silently relocate (or delete) a real entry.
                original = editable.iloc[i]
                start_dt, end_dt = original["start_dt"], original["end_dt"]
                incomplete += 1
            else:
                start_dt = pd.Timestamp.combine(date, start_t)
                end_dt = pd.Timestamp.combine(date, end_t)
                if end_dt <= start_dt:
                    end_dt = end_dt + pd.Timedelta(1, "D")

            rows.append({
                "id": orig_ids[i] if not is_new else kd.new_entry_id(),
                "start": kd.iso_stamp(start_dt), "end": kd.iso_stamp(end_dt),
                "description": str(row["Description"] or "").strip(),
                "notes": str(row["Notes"] or "").strip(), **tags,
            })

        # Every row the editor was showing is replaced wholesale by what came back, so a
        # ticked row is a row that simply isn't in `rows`. Entries from other weeks, and the
        # running one, are untouched.
        kept = kd.delete_entries(entries, orig_ids)
        updated = pd.concat([kept, pd.DataFrame(rows, columns=kd.TIME_ENTRY_COLS)],
                            ignore_index=True) if rows else kept
        if overfilled:
            st.warning("A tag cell holds more than one tag — only the first one is saved.", icon="⚠️")
        if incomplete:
            st.warning(f"{incomplete} row(s) were missing a Date, Start or End. A new row like "
                       "that was skipped; an existing one kept the times it already had.", icon="⚠️")
        st.session_state.pop(editor_key, None)
        n_deleted = len(orig_ids) - sum(1 for r in rows if r["id"] in set(orig_ids))
        save_entries(updated, f"Saved {len(rows)} entr{'y' if len(rows) == 1 else 'ies'}"
                              + (f", removed {n_deleted}." if n_deleted else "."))

    with st.expander("➕ Add an entry by hand"):
        with st.form("tt_manual", clear_on_submit=True):
            f1, f2, f3, f4 = st.columns([1.4, 1, 1, 2.6])
            f_date = f1.date_input("Date", value=min(NOW.date(), (week_end - pd.Timedelta(1, "D")).date())
                                   if week_start.date() <= NOW.date() else week_start.date())
            f_start = f2.time_input("Start", value=dt.time(9, 0), step=300)
            f_end = f3.time_input("End", value=dt.time(10, 0), step=300)
            f_desc = f4.text_input("Description", placeholder="what the stretch was")
            g1_, g2_, g3_ = st.columns(3)
            f_project = g1_.selectbox("Project", options["projects"], index=None,
                                      accept_new_options=True, placeholder="pick or type")
            f_category = g2_.selectbox("Category", options["categories"], index=None,
                                       accept_new_options=True, placeholder="pick or type")
            f_task = g3_.selectbox("Major task", options["major_tasks"], index=None,
                                   accept_new_options=True, placeholder="pick or type")
            f_notes = st.text_input("Notes", placeholder="optional")
            if st.form_submit_button("➕ Add entry", type="primary"):
                save_entries(
                    kd.add_entry(entries, pd.Timestamp.combine(f_date, f_start),
                                 pd.Timestamp.combine(f_date, f_end), description=f_desc,
                                 project=f_project, category=f_category, major_task=f_task,
                                 notes=f_notes),
                    "Entry added.")

# ============================================================================================
# THE PUSH — tracker week -> track_time.csv
# ============================================================================================
if not READONLY:
    st.divider()
    with st.expander(f"⬆ Send week of {week_label} to the time log"
                     + (f"  —  {n_to_push} row(s) to write" if n_to_push else "  —  up to date"),
                     expanded=False):
        st.caption(
            "The week's stretches folded into the shape track_time.csv already has: one row "
            "per project / category / major task. Everything here is "
            "a proposal — untick a row to leave it alone, and change the hours, the Timesheet flag "
            "or the note before writing. Rows the time log has and the tracker doesn't are "
            "never touched, and a timer still running isn't counted. Afterwards the Overview "
            "page's Week editor still has the last word on every row.")

        if not proposals:
            st.info("Nothing finished to send for this week yet.")
        else:
            STATUS_LABEL = {"new": "➕ new", "changed": "✏️ changed", "same": "✓ already matches",
                            "duplicate": "⚠️ duplicate rows"}
            preview = pd.DataFrame([{
                "Send": p["status"] in ("new", "changed") and not p["unfiled"],
                "Status": "⚠️ not filed" if p["unfiled"] else STATUS_LABEL[p["status"]],
                "Project": p["project"] or "—", "Category": p["category"] or "—",
                "Major task": p["major_task"] or "—",
                "Tracked": kd.format_hm(p["hours"]),
                "In the log now": "—" if p["current_hours"] is None else kd.format_hm(p["current_hours"]),
                "Hrs": p["hrs"], "Min": p["min"],
                "Timesheet": p["current_timesheet"] or "No",
                "Notes": (p["current_notes"] if p["row_index"] is not None
                          else "; ".join(p["descriptions"])),
            } for p in proposals])

            edited_preview = st.data_editor(
                preview, num_rows="fixed", width="stretch", hide_index=True, key=f"tt_push_{week_start.date()}",
                disabled=["Status", "Project", "Category", "Major task", "Tracked",
                          "In the log now"],
                column_config={
                    "Send": st.column_config.CheckboxColumn("Send", default=False, width="small"),
                    "Hrs": st.column_config.NumberColumn("Hrs", min_value=0, step=1, width="small"),
                    "Min": st.column_config.NumberColumn("Min", min_value=0, max_value=59, step=1,
                                                         width="small"),
                    "Timesheet": st.column_config.SelectboxColumn("Timesheet", options=["Yes", "No", "N/A"],
                                                               width="small"),
                },
            )

            unfiled = [p for p in proposals if p["unfiled"]]
            if unfiled:
                st.warning(
                    f"{len(unfiled)} row(s) are missing a project, category or major task, so "
                    "they start unticked — every chart that colours by category assumes a row "
                    "has all three, and the Week editor refuses a half-filled row for the same "
                    "reason. Fill them in on the Entries table above (the push will pick the "
                    "change up), or tick one anyway if a blank really is right.", icon="⚠️")

            dupes = [p for p in proposals if p["status"] == "duplicate"]
            if dupes:
                st.warning(
                    "This week already holds more than one time-log row for "
                    + ", ".join(f"**{p['project'] or '—'} / {p['category'] or '—'} / "
                                f"{p['major_task'] or '—'}**" for p in dupes)
                    + ". There's no single row to update, so these are skipped — merge them in "
                      "the Overview page's Week editor and come back.", icon="⚠️")

            if st.button("⬆ Write the ticked rows to track_time.csv",
                         key=f"tt_push_go_{week_start.date()}", type="primary"):
                accepted = [
                    {**p, "hrs": int(row["Hrs"] or 0), "min": int(row["Min"] or 0),
                     "timesheet": str(row["Timesheet"] or "No"), "notes": str(row["Notes"] or "")}
                    for p, (_, row) in zip(proposals, edited_preview.iterrows())
                    if bool(row["Send"])
                ]
                if not accepted:
                    st.info("Nothing ticked — nothing written.")
                else:
                    updated_raw, n_up, n_new = kd.apply_timelog_push(timelog_raw, accepted, week_start)
                    try:
                        updated_raw.to_csv(kd.TIMELOG_PATH, sep=";", index=False, encoding="utf-8-sig")
                    except PermissionError:
                        st.error("Couldn't save — track_time.csv is open in Excel or another "
                                 "program. Close it and click the button again.")
                    else:
                        st.session_state.pop(f"tt_push_{week_start.date()}", None)
                        st.session_state["tt_flash"] = (
                            f"Time log updated — {n_new} row(s) added, {n_up} updated. "
                            "They're on the Overview page's Week tab now.")
                        st.rerun()

st.caption("Tracked time lives in `Data/time_entries.csv`; the weekly time log every other "
           "page reads stays `Data/track_time.csv`. The two only meet in the panel above.")
