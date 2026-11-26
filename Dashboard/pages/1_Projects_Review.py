"""Projects Review — hours by project, complexity, definition, who-we-work-with, impact,
consulting. Split out from the Year tab so those stay a quick overview and this holds the
deeper per-project detail. Entirely driven by the KPI*.xlsx project tracker for the
selected period -- unlike the main page's Week/Month/Year tabs, nothing here depends on the
personal time log, so it works even for a period that predates it."""

import pandas as pd
import streamlit as st

import kpi_cache as kcache
import kpi_charts as kc
import kpi_data as kd
import kpi_style as ks
from kpi_style import anchor, page_nav

st.set_page_config(page_title="Projects Review", page_icon="🗂️", layout="wide")
kc.set_theme(dark=st.context.theme.type == "dark")
ks.inject(dark=st.context.theme.type == "dark")

if st.query_params.get("readonly") is not None:
    st.session_state["readonly"] = st.query_params.get("readonly") in ("1", "true", "yes", "True")
READONLY = st.session_state.get("readonly", False)
if READONLY:
    st.info("📖 Read-only view — editing controls are hidden.", icon="📖")


ks.header("Projects Review",
          "Per-project detail from the tracker — complexity, definition, collaborations, impact")

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
st.caption("Driven by the project tracker sheet for this period.")

df, *_ = kcache.load_timelog(dark=st.context.theme.type == "dark")
df_period_for_hours = kd.filter_to_period(df, period)

projects = kcache.load_projects(period["file"], period["sheet"])
meetings = kcache.load_meetings(period["file"], period["meetings_sheet"])

page_nav([
    ("Year at a glance", "year-at-a-glance"), ("Needs attention", "needs-attention"),
    ("Turnaround", "lead-time"), ("Hours by project", "hours-by-project"),
    ("Complexity", "project-complexity"), ("Definition", "project-definition"),
    ("Who we work with", "who-we-work-with"), ("Impact", "non-quantifiable-outputs"),
    ("Consulting", "consulting"), ("Beyond projects", "beyond-projects"),
    ("Publications", "publications"),
])

st.subheader(f"Year at a glance — {period_label}", anchor="year-at-a-glance")
glance = kd.year_at_a_glance(projects, meetings, df_period_for_hours)
# height="stretch" (not a fixed px height): the row grows to its tallest card, so every
# card still lines up but a long caption is read in full instead of needing a scroll.
CARD_HEIGHT = "stretch"
c1, c2, c3, c4 = st.columns(4)
with c1, st.container(border=True, height=CARD_HEIGHT):
    st.metric("Projects", glance["projects_total"])
    st.caption(f"*{glance['projects_concluded']} concluded · {glance['projects_active']} active*")
with c2, st.container(border=True, height=CARD_HEIGHT):
    st.metric("Consultation meetings", glance["meetings_total"])
    st.caption(f"*{kd.format_hm(glance['meeting_hours'])} logged*")
with c3, st.container(border=True, height=CARD_HEIGHT):
    st.metric("Hours in Timesheet", kd.format_hm(glance["total_hours"]))
    st.caption(f"*{kd.format_hm(glance['project_hours'])} projects · {kd.format_hm(glance['meeting_hours'])} consulting*")
with c4, st.container(border=True, height=CARD_HEIGHT):
    st.metric("Groups reached", glance["groups_total"])
    st.caption(f"*{glance['groups_with_projects']} with projects · {glance['groups_consultation_only']} consultation-only*")

st.divider()
st.subheader("Needs attention", anchor="needs-attention")

ATTENTION_STYLE = {
    "not started": ("🚩", "Not started"),
    "quiet": ("⏳", "Quiet"),
    "to close": ("📋", "Ready to close"),
}
quiet_days = st.slider(
    "Flag an open project after this many days with no logged hours", 7, 60,
    kd.ATTENTION_QUIET_DAYS, step=7, key="attention_quiet_days",
)
attention = kd.project_attention(projects, df_period_for_hours, quiet_days=quiet_days)

if not len(attention):
    st.success("Nothing stalling — every open project has had hours logged recently, and "
               "all delivered projects have a Closing Day.", icon="✅")
else:
    counts = attention["kind"].value_counts()
    summary = " · ".join(f"{ATTENTION_STYLE[k][0]} {counts[k]} {ATTENTION_STYLE[k][1].lower()}"
                         for k in ATTENTION_STYLE if k in counts)
    st.caption(f"{len(attention)} open project{'' if len(attention) == 1 else 's'} to look at — {summary}. "
               "Hours come from the time log, so logging a week's work clears a 'quiet' flag.")
    for _, r in attention.iterrows():
        icon, label = ATTENTION_STYLE[r["kind"]]
        with st.container(border=True):
            left, right = st.columns([3, 2])
            left.markdown(f"{icon} **{r['Project tag']}** — {label}")
            right.caption(r["detail"])

st.divider()
st.subheader(f"Turnaround — {period_label}", anchor="lead-time")
st.caption(
    "How long projects take — **waiting** = first contact until the tracker's work start, "
    "**working** = from there until the final report. The **◆ diamond** marks when work "
    "*really* began per the time log (first week with hours), which can sit before or after "
    f"the tracker's Timesheet-fed date; pauses ({kd.PAUSE_MIN_WEEKS}+ week"
    f"{'' if kd.PAUSE_MIN_WEEKS == 1 else 's'} with no hours) show in gray."
)
with st.expander("ℹ️ How these numbers are calculated"):
    st.markdown(f"""
- **First contact** — the tracker's *First User Meeting/Shared Data* date, or *Register
  Project* when that's blank.
- **Work started** — the tracker's *Begining* date (the formal record, fed by Timesheet), used
  for the waiting/working stages and the medians below, exactly as before.
- **Really working since (◆)** — the start of the project's **first week with logged hours**
  in the personal time log. It doesn't change any of the day figures; it sits on the chart
  (and in the table) so you can see when work *actually* began — before or after the formal
  start. It's blank for a project with no logged hours, and for one already active in the
  log's very first week with an earlier *Begining* (work that predates the log is invisible
  to it — marked *before the log* in the table).
- **Waiting (days)** = work started − first contact. **Working (days)** = final report −
  work started, or up to **today** while the project is still running. **Total** = waiting +
  working. All are plain calendar days — weekends count.
- **Inherited projects** — their waiting span ran under the project's previous owner, so it
  draws **faded and hatched** on the chart (the days still count in the waiting median;
  say the word if you'd rather exclude them).
- **Internal projects** — drawn **faded and hatched in blue** across both stages, and left
  out of all four tiles: there's no external user waiting, so their days aren't service
  turnaround. They also have no report to send, so the **Closing Day** ends their working
  stage (and is what shows under *Report sent* in the table below).
- **Forgiven pauses** — each pause (below) is forgiven **week by week**, not as a single
  block: a pause spanning several weeks can have one week forgiven and another not. Every
  week carries two separate forgive checkboxes, one for *effective working time*, one for
  *total turnaround to user*: tick either (or both) to draw that week **faded and hatched
  in gray** and subtract its days from just that figure, without excusing the rest of the
  project the way Internal does. They're independent on purpose — a week that shouldn't
  count as real work might still be time the user genuinely spent waiting (forgive working
  time only), or the reverse.
- **Consulting blocks** don't appear here at all — a standing advisory thread has no start
  and no report to deliver, so there's no turnaround to measure. They're still counted in
  the project total above, and have their own section further down.
- **Very short bars** are drawn at a minimum width so a project delivered in a day or two
  stays visible on a year-long axis; the tooltip and the table always give the real days.
- **Weeks active** — how many distinct weeks have logged hours; a better feel for real
  effort than the day span, since a project can be open for months but touched in few weeks.
- **Paused** — a run of **{kd.PAUSE_MIN_WEEKS}+ consecutive weeks with no logged hours**
  between two active weeks. Pauses are drawn in gray on the chart; each one can carry a note
  explaining why (e.g. *waiting for user*) below.
- **These are medians** (not averages, so one slow project can't distort them). *Wait to
  start* covers every project with usable dates; the delivery figures only projects with a
  Final Report Sent. Rows with impossible dates are flagged and left out, as are internal
  projects; forgiven pauses (above) are subtracted rather than excluding the project.
- **The second row is three ways of measuring the same projects' duration** — the headline
  *total turnaround to user* (first contact → final report), the work-only span inside it
  (*time to deliver — effective working time*), and the administrative span (*Timesheet
  tracking*, Register Project → Closing Day, which starts after first contact and runs
  past the report to the close). If Final Report Sent ever lands after Closing Day, that
  date is used in place of Closing Day here, so a report that trailed the recorded close
  doesn't shrink the span.
- **Turnaround by project size** answers "how long for a job this size?" by splitting the
  projects into bands — under 10 h, 10–30 h, over 30 h — and taking a median in each. It's
  the size-adjusted view, done by comparing like with like rather than dividing days by
  hours: a large project taking longer is expected, so the thing worth spotting is a small
  project sitting in a large project's range. Band edges are fixed round numbers, not this
  period's own terciles, so a band means the same thing from year to year.
- **Hours** behind it come from the time log where it covers the period and the tracker's
  Timesheet column otherwise — for any period that predates the time log, every hours figure
  here is Timesheet. Projects with no hours on record sit it out.
""")
pause_notes = kd.load_pause_notes()
lead_df = kd.lead_time_table(projects, df_period_for_hours, period_end=period["end"], pause_notes=pause_notes)
lead_stats = kd.lead_time_summary(lead_df)

lead_cov = kd.lead_time_coverage(projects, lead_df, lead_stats)
lt1, lt2, lt3 = st.columns(3)
lt1.metric("Typical wait to start", kd.format_days(lead_stats["median_waiting"]),
           help="The queue — median days from first contact to work starting. This is the "
                "part the user spends waiting on us before anything begins.")
lt2.metric("Projects measured", f"{lead_stats['n_shown_delivered']}/{lead_stats['n_shown']}",
           help="Delivered out of the projects on the chart. Internal projects are counted "
                "here, but their days stay out of the medians; a forgiven pause (below) "
                "subtracts just its own days instead.")
lt3.metric("Consulting", lead_cov["consulting"],
           help="Standing advisory threads. They have no start and no report to deliver, so "
                "there's no turnaround to measure and they aren't on the chart — they're "
                "still part of the project total, and have their own section below.")

# These tiles cover fewer projects than the period has, so spell out where the rest went --
# otherwise "17/19" against a headline of 20 reads as a project having gone missing.
st.caption(kd.lead_time_coverage_note(lead_cov))

# Second row -- total turnaround leads, because it is the headline figure and the one the
# effort-weighted tile at the end re-averages; then the work-only span inside it, then the
# administrative span Timesheet tracks.
lead_effort = kd.lead_time_effort(lead_df)
ef1, ef2, ef3, ef4 = st.columns(4)
ef1.metric("Typical total turnaround to user", kd.format_days(lead_stats["median_total"]),
           help="What the user experiences end to end — median days from first contact to "
                "the final report, so it carries the time waiting on us as well as the work "
                "itself. This is the figure the effort-weighted tile re-averages. A pause "
                "ticked \"forgive\" for total turnaround (below) is excused from this one.")
ef2.metric("Typical time to deliver — effective working time",
           kd.format_days(lead_stats["median_working"]),
           help="The real workload time — median days from work starting to the final "
                "report, for delivered projects. The work-only part of the total turnaround "
                "on its left. Calendar days across the working span, not hours of effort. A "
                "pause ticked \"forgive\" for working time (below) is excused from this one.")
ef3.metric("Timesheet tracking", kd.format_days(lead_effort["median_timesheet"]),
           help="Median days from Register Project to Closing Day — the span Timesheet tracks. "
                "Longer than the two on its left by design: it starts at registration and "
                "runs past the report to the administrative close.")

# Same question the two rate metrics were trying to answer -- how long for the hours a job
# takes -- but by comparing like with like. A big project taking longer isn't news; what's
# worth seeing is a small one that took a large one's time.
st.caption("**Typical total turnaround to user by project size** — what to expect for the "
           "job in front of you, rather than one median across jobs of every size.")
size_bands = kd.turnaround_by_size(lead_df)
for col, band in zip(st.columns(len(size_bands)), size_bands):
    col.metric(f"Typical total turnaround to user — {band['label']} ({band['range_label']})",
               kd.format_days(band["median_days"]),
               delta=f"{band['n']} project{'' if band['n'] == 1 else 's'}",
               delta_color="off",
               help="Median total turnaround — first contact to final report — for "
                    f"delivered projects of **{band['range_label']}**.\n\n"
                    "Hours come from the time log where it covers the period, and the "
                    "tracker's Timesheet column otherwise. A project with no hours on record "
                    "can't be placed in a band and sits these out.")

flagged = lead_df[lead_df["flag"] != ""] if len(lead_df) else lead_df
if len(flagged):
    issues = "; ".join(f"**{r['Project tag']}** ({r['flag']})" for _, r in flagged.iterrows())
    st.warning(f"Excluded from the figures above — dates look wrong: {issues}. "
               "Fix them on the **Add Data** page.", icon="📅")

st.plotly_chart(kc.fig_lead_time_stages(lead_df, f"Project turnaround — {period_label}",
                                        pause_notes=pause_notes, period_start=period["start"]),
                width="stretch")

with st.expander("Per-project turnaround table"):
    table = lead_df.copy()
    if len(table):
        table = pd.DataFrame({
            "Project tag": table["Project tag"],
            "First contact": table["first_contact"].dt.strftime("%d %b %Y"),
            "Started (tracker)": table["start"].dt.strftime("%d %b %Y"),
            "Really working since": table["real_start"].dt.strftime("week of %d %b %Y")
                .fillna("—").mask(table["pre_log"], "before the log"),
            "Report sent": table["report"].dt.strftime("%d %b %Y").fillna("— ongoing"),
            "Waiting (days)": table["waiting_days"],
            "Working (days)": table["working_days"],
            "Total (days)": table["total_days"],
            "Working, counted": table["working_days_counted"],
            "Total, counted": table["total_days_counted"],
            "Weeks active": table["weeks_active"].astype("Int64"),
            "Weeks paused": table["weeks_paused"],
            "Data issue": table["flag"].replace("", "—"),
        })
    st.dataframe(table, width="stretch", hide_index=True)

# --- Pauses & why: every detected 2+-week hole in a project's logged weeks, each with an
# optional user note ("waiting for user", "on hold for X") stored in project_pause_notes.json.
paused_rows = [r for _, r in lead_df.iterrows() if r.get("gaps")] if len(lead_df) else []
if paused_rows:
    with st.expander(f"⏸ Pauses — {sum(len(r['gaps']) for r in paused_rows)} detected "
                     f"across {len(paused_rows)} project{'s' if len(paused_rows) != 1 else ''}"):
        pause_def = (f"A pause = {kd.PAUSE_MIN_WEEKS}+ consecutive week"
                     f"{'' if kd.PAUSE_MIN_WEEKS == 1 else 's'} with no hours logged for the "
                     "project, between two active weeks.")
        st.caption(
            f"{pause_def} Add a note saying why (e.g. *waiting for user*), and tick either "
            "**forgive** box if it shouldn't count toward that figure below — *working* "
            "excuses it from Typical time to deliver (effective working time), *total* "
            "excuses it from Typical total turnaround to user. They're independent: tick "
            "one, both, or neither, without excusing the rest of the project the way "
            "Internal does. A pause spanning more than one week is forgiven **week by "
            "week** — tick a box for one week of a two-week pause without ticking it for "
            "the other. Kept in project_pause_notes.json; both show in the chart's "
            "tooltip, and a forgiven week draws faded and hatched."
            if not READONLY else pause_def
        )
        default_entry = {"note": "", "forgive_working": False, "forgive_total": False}
        changed = False
        for r in paused_rows:
            tag = r["Project tag"]
            for g in r["gaps"]:
                weeks_detail = g.get("weeks_detail") or [g]
                multi = len(weeks_detail) > 1
                span = f"{g['start'].strftime('%d %b %Y')} → {g['end'].strftime('%d %b %Y')}"
                header = f"**{tag}** — paused {g['weeks']} week{'s' if g['weeks'] != 1 else ''} ({span})"
                if multi:
                    st.markdown(header)
                for i, w in enumerate(weeks_detail, start=1):
                    key = kd.pause_key(w)
                    existing = pause_notes.get(tag, {}).get(key, default_entry)
                    week_span = f"{w['start'].strftime('%d %b %Y')} → {w['end'].strftime('%d %b %Y')}"
                    label = f"— week {i} of {g['weeks']} ({week_span})" if multi else header
                    if READONLY:
                        bits = []
                        if existing["note"]:
                            bits.append(f"*{existing['note']}*")
                        if existing["forgive_working"] and existing["forgive_total"]:
                            bits.append("forgiven (working + total)")
                        elif existing["forgive_working"]:
                            bits.append("forgiven (working time)")
                        elif existing["forgive_total"]:
                            bits.append("forgiven (total turnaround)")
                        st.markdown(label + (f" — {', '.join(bits)}" if bits else ""))
                        continue
                    c1, c2, c3, c4 = st.columns([1.3, 1.8, 0.65, 0.65])
                    c1.markdown(label)
                    note = c2.text_input("Why did it stop?", value=existing["note"],
                                         key=f"pause_{tag}_{key}", placeholder="e.g. waiting for user",
                                         label_visibility="collapsed")
                    forgive_working = c3.checkbox("Forgive (working)", value=existing["forgive_working"],
                                                  key=f"forgive_working_{tag}_{key}")
                    forgive_total = c4.checkbox("Forgive (total)", value=existing["forgive_total"],
                                                key=f"forgive_total_{tag}_{key}")
                    if (note != existing["note"] or forgive_working != existing["forgive_working"]
                            or forgive_total != existing["forgive_total"]):
                        pause_notes.setdefault(tag, {})[key] = {
                            "note": note, "forgive_working": forgive_working, "forgive_total": forgive_total,
                        }
                        changed = True
        if not READONLY and changed:
            try:
                kd.save_pause_notes(pause_notes)
            except PermissionError:
                st.error("Couldn't save — project_pause_notes.json is locked "
                         "(OneDrive sync?). Try again in a moment.")
            else:
                st.toast("Saved.", icon="💾")
                st.rerun()  # redraw so the chart and tiles above pick the change up immediately

st.divider()
anchor("hours-by-project")
st.caption("Only projects the tracker has registered — the time log's other buckets "
           "(org and admin time, consulting, training, seminars) are real work but not "
           "projects, and they're counted in the Week/Month/Year views instead. Hours use "
           "the personal time log when a project has entries there, falling back to "
           "Timesheet otherwise (hover a bar to see which).")
st.plotly_chart(kc.fig_hours_by_project(projects, df_period_for_hours), width="stretch")

if not READONLY:
    if st.button("🔄 Write these hours into Excel as a 'Hours (auto)' column", key=f"sync_hours_{period_label}"):
        kd.sync_auto_hours_column(period["file"], period["sheet"], projects, df_period_for_hours)
        st.success(f"Wrote '{kd.AUTO_HOURS_COL}' to {period['sheet']}. 'Hours in Timesheet' itself was not touched.")
        st.rerun()
anchor("project-complexity")
st.plotly_chart(kc.fig_project_complexity(projects, df_period_for_hours), width="stretch")
anchor("project-definition")
st.plotly_chart(kc.fig_project_definition(projects), width="stretch")
anchor("who-we-work-with")
st.plotly_chart(kc.fig_who_we_work_with(projects), width="stretch")

st.subheader("Non-quantifiable project outputs", anchor="non-quantifiable-outputs")
if "Non-quantifiable outputs" in projects.columns:
    impact_cols = ["Project tag"] + (["Short Description"] if "Short Description" in projects.columns else []) + ["Grupo", "Non-quantifiable outputs"]
    impact_table = projects[impact_cols].copy()
    impact_table = impact_table[
        impact_table["Non-quantifiable outputs"].notna() & (impact_table["Non-quantifiable outputs"].astype(str).str.strip() != "")
    ].reset_index(drop=True)

    if READONLY:
        st.dataframe(impact_table, width="stretch", hide_index=True)
    elif not len(impact_table):
        st.caption("No project has a recorded non-quantifiable output yet.")
    else:
        st.caption(
            "Edit and save -- to add an entry for a project not listed here (it has none "
            "recorded yet), use the **Add Data** page's \"Edit a project\" form instead."
        )
        edited_impact = st.data_editor(
            impact_table, width="stretch", hide_index=True, key=f"impact_editor_{period_label}",
            disabled=["Project tag"],
        )
        if st.button("💾 Save changes", key=f"save_impact_{period_label}"):
            editable_cols = [c for c in impact_cols if c != "Project tag"]
            errors = []
            for i in range(len(impact_table)):
                tag = impact_table.loc[i, "Project tag"]
                changes = {c: (None if pd.isna(edited_impact.loc[i, c]) else edited_impact.loc[i, c]) for c in editable_cols}
                try:
                    kd.update_project_row(period["file"], period["sheet"], tag, changes)
                except ValueError as e:
                    errors.append(str(e))
            if errors:
                for e in errors:
                    st.error(e)
            else:
                st.success("Saved.")
                st.rerun()
else:
    st.caption("No 'Non-quantifiable outputs' column in this period's sheet.")

anchor("consulting")
st.plotly_chart(kc.fig_consulting_overview(meetings), width="stretch")

st.divider()
st.subheader(f"Beyond projects — {period_label}", anchor="beyond-projects")
st.caption("Free-form cards for work the project tracker has no column for (teaching, outreach, "
           "courses, internal tools, ...). Saved to beyond_projects.json and mirrored to "
           f"{kd.BEYOND_XLSX_PATH.name}.")

if st.session_state.pop("beyond_save_warning", None):
    st.warning(f"Saved, but couldn't update {kd.BEYOND_XLSX_PATH.name} — close it in Excel to "
               "refresh the mirror on the next edit.", icon="⚠️")

all_beyond = kd.load_beyond_projects()
beyond_cards = all_beyond.setdefault(period_label, [])


def _save_beyond(all_cards):
    warning = kd.save_beyond_projects(all_cards)
    if warning:
        st.session_state["beyond_save_warning"] = warning

card_cols = st.columns(2)
for i, card in enumerate(beyond_cards):
    with card_cols[i % 2]:
        with st.container(border=True):
            st.markdown(
                f"<div style='border-left:6px solid {card['color']}; padding-left:10px;'>"
                f"<span style='color:{card['color']}; font-size:1.5em; font-weight:bold;'>{card['value'] or '—'}</span><br>"
                f"<b>{card['title'] or '(untitled card)'}</b><br>"
                f"<span style='opacity:0.85'>{card['description']}</span></div>",
                unsafe_allow_html=True,
            )
            if not READONLY:
                with st.expander("✏️ Edit"):
                    with st.form(f"beyond_form_{period_label}_{i}"):
                        title = st.text_input("Title", value=card["title"], key=f"beyond_title_{period_label}_{i}")
                        value = st.text_input("Headline value", value=card["value"], key=f"beyond_value_{period_label}_{i}")
                        desc = st.text_area("Description", value=card["description"], key=f"beyond_desc_{period_label}_{i}")
                        color = st.color_picker("Accent color", value=card["color"], key=f"beyond_color_{period_label}_{i}")
                        b_save, b_del = st.columns(2)
                        saved = b_save.form_submit_button("💾 Save card")
                        removed = b_del.form_submit_button("🗑️ Remove card")
                    if saved:
                        card.update(title=title, value=value, description=desc, color=color)
                        _save_beyond(all_beyond)
                        st.rerun()
                    if removed:
                        beyond_cards.pop(i)
                        _save_beyond(all_beyond)
                        st.rerun()

if not READONLY and st.button("➕ Add card", key=f"beyond_add_{period_label}"):
    beyond_cards.append(kd.new_beyond_card())
    _save_beyond(all_beyond)
    st.rerun()

st.subheader(f"Publications — {period_label}", anchor="publications")
st.caption("Papers and preprints this period's work fed into, tagged with the project(s) "
           f"they relate to. Saved to publications.json and mirrored to {kd.PUBLICATIONS_XLSX_PATH.name}.")

if st.session_state.pop("pub_save_warning", None):
    st.warning(f"Saved, but couldn't update {kd.PUBLICATIONS_XLSX_PATH.name} — close it in Excel "
               "to refresh the mirror on the next edit.", icon="⚠️")

all_pubs = kd.load_publications()
pub_entries = all_pubs.setdefault(period_label, [])


def _save_pubs(all_entries):
    warning = kd.save_publications(all_entries)
    if warning:
        st.session_state["pub_save_warning"] = warning


if not pub_entries:
    st.caption("No publications logged for this period yet.")

for i, pub in enumerate(pub_entries):
    with st.container(border=True):
        tags = [t.strip() for t in str(pub.get("projects", "")).split(",") if t.strip()]
        tag_html = "".join(
            f"<span style='background:#2A9D8F22; color:#2A9D8F; border-radius:10px; "
            f"padding:1px 9px; margin-right:5px; font-size:0.82em; font-weight:600;'>{t}</span>"
            for t in tags
        )
        title_html = (f"<a href='{pub['url']}' target='_blank'>{pub['title'] or '(untitled)'}</a>"
                      if pub.get("url") else (pub["title"] or "(untitled)"))
        meta_bits = [b for b in (pub.get("venue"), pub.get("date")) if b]
        st.markdown(
            f"<b>{title_html}</b><br>"
            f"<span style='opacity:0.85'>{' · '.join(meta_bits)}</span><br>"
            f"<div style='margin-top:4px'>{tag_html}</div>",
            unsafe_allow_html=True,
        )
        if not READONLY:
            with st.expander("✏️ Edit"):
                with st.form(f"pub_form_{period_label}_{i}"):
                    title = st.text_input("Title", value=pub["title"], key=f"pub_title_{period_label}_{i}")
                    venue = st.text_input("Venue (e.g. bioRxiv preprint, journal name)",
                                           value=pub["venue"], key=f"pub_venue_{period_label}_{i}")
                    date = st.text_input("Date", value=pub["date"], key=f"pub_date_{period_label}_{i}")
                    url = st.text_input("Link (DOI or URL)", value=pub["url"], key=f"pub_url_{period_label}_{i}")
                    projects = st.text_input("Related project tags (comma-separated)",
                                              value=pub["projects"], key=f"pub_projects_{period_label}_{i}")
                    p_save, p_del = st.columns(2)
                    saved = p_save.form_submit_button("💾 Save")
                    removed = p_del.form_submit_button("🗑️ Remove")
                if saved:
                    pub.update(title=title, venue=venue, date=date, url=url, projects=projects)
                    _save_pubs(all_pubs)
                    st.rerun()
                if removed:
                    pub_entries.pop(i)
                    _save_pubs(all_pubs)
                    st.rerun()

if not READONLY and st.button("➕ Add publication", key=f"pub_add_{period_label}"):
    pub_entries.append(kd.new_publication())
    _save_pubs(all_pubs)
    st.rerun()
