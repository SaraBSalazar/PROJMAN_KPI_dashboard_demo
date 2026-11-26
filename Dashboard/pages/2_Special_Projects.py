"""Special Projects — goal ratings bubble chart, read live from Special_Projects_Ratings.xlsx.
Click a bubble to open its project card plus a per-project completion checklist (stored in
../Data/special_project_tasks.json, independent of the ratings spreadsheet, and mirrored to
../Data/Special_Projects_Tasks.xlsx -- one sheet per project -- on every edit)."""

import datetime as dt

import pandas as pd
import streamlit as st
from streamlit.errors import StreamlitAPIException

import kpi_cache as kcache
import kpi_charts as kc
import kpi_data as kd
import kpi_style as ks
from kpi_style import anchor, page_nav

st.set_page_config(page_title="Special Projects", page_icon="🎯", layout="wide")
kc.set_theme(dark=st.context.theme.type == "dark")
ks.inject(dark=st.context.theme.type == "dark")

if st.query_params.get("readonly") is not None:
    st.session_state["readonly"] = st.query_params.get("readonly") in ("1", "true", "yes", "True")
READONLY = st.session_state.get("readonly", False)

MAX_TASK_LEVEL = 2  # top level + 2 nested levels


def render_card(row):
    st.markdown(f"### {'✅ ' if row.get('_finished') else ''}{row['Project']}")
    st.caption(row["Goal"])

    if row.get("_finished"):
        when = row.get("_completed")
        st.success(
            "**Finished**" + (f" — {when.strftime('%d %b %Y')}" if when else ""), icon="✅",
        )

    stars = " · ".join(
        f"**{label}** {'★' * int(row[label])}"
        for label in ["Development", "Impact", "Maintenance", "Visibility"]
        if pd.notna(row.get(label))
    )
    if stars:
        st.markdown(stars)

    if pd.notna(row.get("Description")) and row["Description"]:
        for part in str(row["Description"]).split(";"):
            part = part.strip()
            if part:
                st.markdown(f"- {part}")

    if pd.notna(row.get("Advantages")) and row["Advantages"]:
        st.markdown(f":green[**+** {row['Advantages']}]")
    if pd.notna(row.get("Limitations")) and row["Limitations"]:
        st.markdown(f":red[**-** {row['Limitations']}]")
    if pd.notna(row.get("Future gain")) and row["Future gain"]:
        st.markdown(f":blue[**→** {row['Future gain']}]")


def _span_label(start, due):
    """Read-only rendering of a task's planned dates: a range when both are set, a single
    date when only one is, nothing when neither."""
    if start and due:
        return f"📅 {start.strftime('%d %b')} → {due.strftime('%d %b %Y')}"
    if due:
        return f"📅 {due.strftime('%d %b %Y')}"
    if start:
        return f"▶ {start.strftime('%d %b %Y')}"
    return ""


def _task_index(tasks, task_id):
    return next(i for i, t in enumerate(tasks) if t["id"] == task_id)


def _save_tasks(all_tasks):
    """Save and stash any Excel-mirror lock warning so it survives the st.rerun() that
    usually follows (shown and cleared by render_tasks on the next run)."""
    warning = kd.save_project_tasks(all_tasks)
    if warning:
        st.session_state["tasks_save_warning"] = warning


def _rerun(charts=False):
    """Redraw after a task edit.

    The checklist lives in an st.fragment, so by default only the checklist is redrawn --
    the three Plotly charts on this page are left alone, which is what made editing feel
    slow (every tick or keystroke re-rendered all of them in the browser). Edits that
    genuinely change the charts (a date, a done flag, a deletion) pass charts=True to
    redraw the whole page instead."""
    if not charts:
        try:
            st.rerun(scope="fragment")
        except StreamlitAPIException:
            # Only legal during a fragment rerun; on a full page run redraw everything.
            pass
    st.rerun()


def render_task_row(all_tasks, project_name, task, structure=False):
    """One checklist row. `structure` adds the four layout buttons (add / outdent / indent /
    delete); they stay off by default because they were the page's main cost -- four buttons
    and four extra columns per task, which is what the browser spends its time mounting."""
    tasks = all_tasks[project_name]
    start_date, due_date = kd.task_span(task)

    if READONLY:
        spacer, done_col, text_col, date_col = st.columns([0.3 + 0.5 * task["level"], 0.5, 4.6, 2.2])
        done_col.checkbox("Done", value=task["done"], key=f"ro_done_{task['id']}", label_visibility="collapsed", disabled=True)
        text_col.markdown(task["text"] or "*(untitled task)*")
        date_col.markdown(_span_label(start_date, due_date))
        return

    if structure:
        (spacer, done_col, text_col, start_col, date_col,
         add_col, out_col, in_col, del_col) = st.columns(
            [0.3 + 0.5 * task["level"], 0.5, 3.2, 1.6, 1.6, 0.6, 0.6, 0.6, 0.6]
        )
    else:
        spacer, done_col, text_col, start_col, date_col = st.columns(
            [0.3 + 0.5 * task["level"], 0.5, 4.4, 1.7, 1.7]
        )

    done = done_col.checkbox("Done", value=task["done"], key=f"done_{task['id']}", label_visibility="collapsed")
    if done != task["done"]:
        task["done"] = done
        _save_tasks(all_tasks)
        _rerun(charts=True)

    text = text_col.text_input(
        "Task text", value=task["text"], key=f"text_{task['id']}", label_visibility="collapsed",
        placeholder="Task description",
    )
    if text != task["text"]:
        task["text"] = text
        _save_tasks(all_tasks)
        # Rerun so a top-level task's new text immediately becomes its section heading --
        # without this the heading kept showing the previous text (or "(untitled task)").
        _rerun()

    start = start_col.date_input(
        "Planned start", value=start_date, key=f"start_{task['id']}", label_visibility="collapsed",
        format="DD/MM/YYYY", help="Planned START date (leave empty if not scheduled yet)",
    )
    if start != start_date:
        task["start"] = start.isoformat() if start else None
        _save_tasks(all_tasks)
        _rerun(charts=True)

    due = date_col.date_input(
        "Planned finish", value=due_date, key=f"due_{task['id']}", label_visibility="collapsed",
        format="DD/MM/YYYY", help="Planned FINISH date (leave empty if not scheduled yet)",
    )
    if due != due_date:
        task["due"] = due.isoformat() if due else None
        _save_tasks(all_tasks)
        _rerun(charts=True)

    if not structure:
        return

    if add_col.button("➕", key=f"add_{task['id']}", help="Add a sub-task below this one"):
        idx = _task_index(tasks, task["id"])
        tasks.insert(idx + 1, kd.new_task(level=min(task["level"] + 1, MAX_TASK_LEVEL)))
        _save_tasks(all_tasks)
        _rerun()

    if out_col.button("⬅", key=f"out_{task['id']}", help="Outdent", disabled=task["level"] == 0):
        task["level"] = max(task["level"] - 1, 0)
        _save_tasks(all_tasks)
        _rerun()

    idx = _task_index(tasks, task["id"])
    can_indent = idx > 0 and task["level"] < min(tasks[idx - 1]["level"] + 1, MAX_TASK_LEVEL)
    if in_col.button("➡", key=f"in_{task['id']}", help="Indent", disabled=not can_indent):
        task["level"] += 1
        _save_tasks(all_tasks)
        _rerun()

    if del_col.button("🗑️", key=f"del_{task['id']}", help="Delete (and any sub-tasks)"):
        level = task["level"]
        end = idx + 1
        while end < len(tasks) and tasks[end]["level"] > level:
            end += 1
        del tasks[idx:end]
        _save_tasks(all_tasks)
        _rerun(charts=True)


@st.fragment
def render_tasks(project_name):
    """Fragment, so ticking a box or typing a task redraws only this panel instead of the
    whole page (which would re-render every chart in the browser on each keystroke)."""
    st.markdown("#### Tasks for completion")
    st.caption("Each row: done · task · **start** · **finish**. "
               "Either date can be left empty.")
    if st.session_state.pop("tasks_save_warning", None):
        st.warning(f"Saved, but couldn't update {kd.TASKS_XLSX_PATH.name} — close it in Excel "
                   "to refresh the mirror on the next edit.", icon="⚠️")
    all_tasks = kcache.load_project_tasks()
    tasks = all_tasks.setdefault(project_name, [])

    done_count = sum(1 for t in tasks if t.get("done"))
    pred = kd.predicted_end(tasks)
    status_bits = [f"**{done_count}/{len(tasks)}** tasks done"] if tasks else []
    if pred:
        status_bits.append(f"📅 Predicted completion: **{pred.strftime('%d %b %Y')}**")
    if status_bits:
        st.markdown(" · ".join(status_bits))

    structure = False
    if not READONLY:
        add_col, mode_col = st.columns([1, 1.4])
        if add_col.button("➕ Add task", key=f"add_top_{project_name}"):
            tasks.append(kd.new_task(level=0))
            _save_tasks(all_tasks)
            _rerun()
        structure = mode_col.toggle(
            "Rearrange", key=f"structure_{project_name}",
            help="Show the add / indent / outdent / delete buttons on each row. Off by "
                 "default -- they are four extra widgets per task and make the panel slower "
                 "to draw, and day-to-day you only tick boxes and set dates.",
        )

    backwards = [t for t in tasks if kd.task_dates_inconsistent(t)]
    if backwards:
        st.warning(
            f"{len(backwards)} task{'' if len(backwards) == 1 else 's'} finish before they "
            "start — check the dates. The timeline draws them over the span they cover.",
            icon="⚠️",
        )

    if not tasks:
        st.caption("No tasks yet.")
        return

    # Group into foldable sections: each top-level task starts a section holding itself
    # and every deeper-level task that follows, up to the next top-level task.
    sections = []
    for t in tasks:
        if t["level"] == 0 or not sections:
            sections.append([t])
        else:
            sections[-1].append(t)

    for section in sections:
        head = section[0]
        label = ("✅ " if head["done"] else "⬜ ") + (head["text"] or "(untitled task)")
        with st.expander(label, expanded=True):
            for t in section:
                render_task_row(all_tasks, project_name, t, structure=structure)


def render_goal_editor(goals_df, row, project_names):
    """Edit everything about the selected special project in place -- including its name,
    which also moves its task checklist so the tasks follow the rename."""
    old_name = str(row["Project"]).strip()
    goal_options = sorted({str(g).strip() for g in goals_df["Goal"] if str(g).strip() and str(g) != "nan"})
    current_goal = str(row.get("Goal") or "").strip()

    # A toggle, not an expander: a collapsed expander still mounts every widget inside it in
    # the browser, and this form is eleven of them (four sliders included). Off by default it
    # costs nothing to draw.
    if not st.toggle("✏️ Edit this project", key=f"edit_goal_toggle_{old_name}"):
        return

    with st.container(border=True):
        with st.form(f"edit_goal_{old_name}"):
            new_name = st.text_input("Project name", value=old_name, key=f"gname_{old_name}")

            # One widget that also takes a new value typed in: a separate "…or a new goal"
            # text box would submit this whole form the moment Enter was pressed in it.
            goal_choices = goal_options if current_goal in goal_options else [current_goal] + goal_options
            picked_goal = st.selectbox(
                "Goal", goal_choices,
                index=goal_choices.index(current_goal) if current_goal in goal_choices else None,
                key=f"ggoal_{old_name}", accept_new_options=True,
                placeholder="pick one, or type a new goal (e.g. 02 - New goal name)",
                help="The leading number groups and colours the bubble chart.",
            )

            def _text(label, col, height=None):
                value = "" if pd.isna(row.get(col)) else str(row.get(col) or "")
                key = f"g{col}_{old_name}".replace(" ", "")
                if height:
                    return st.text_area(label, value=value, key=key, height=height)
                return st.text_input(label, value=value, key=key)

            description = _text("Description (use ';' to split into bullet points)", "Description", height=90)
            advantages = _text("Advantages", "Advantages")
            limitations = _text("Limitations", "Limitations")
            future_gain = _text("Future gain", "Future gain")

            st.caption("Mark the project finished once it is delivered — its bubble then wears "
                       "a green ring and a ✓ on the goals chart.")
            fin_col, when_col = st.columns([1, 1])
            finished = fin_col.checkbox(
                "✅ Project finished", value=bool(row.get("_finished")), key=f"gfin_{old_name}",
            )
            completed_on = when_col.date_input(
                "Finished on", value=row.get("_completed") or dt.date.today(),
                key=f"gfindate_{old_name}", format="DD/MM/YYYY",
                help="Only used when the box on the left is ticked.",
            )

            st.caption("Star ratings — Development and Impact place the bubble, Visibility sizes it.")
            s1, s2, s3, s4 = st.columns(4)
            stars = {}
            for col, container in zip(["Development", "Impact", "Maintenance", "Visibility"], (s1, s2, s3, s4)):
                current = pd.to_numeric(row.get(col), errors="coerce")
                stars[col] = container.slider(
                    col, 1, 5, int(current) if pd.notna(current) else 1, key=f"gstar{col}_{old_name}",
                )

            if st.form_submit_button("💾 Save project"):
                clean_name = new_name.strip()
                others = [n for n in project_names if n != old_name]
                if not clean_name:
                    st.error("Project name can't be empty.")
                elif clean_name in others:
                    st.error(f"Another project is already called \"{clean_name}\" — pick a different name.")
                else:
                    edited = goals_df[kd.GOALS_EDIT_COLS].copy()
                    mask = edited["Project"].astype(str).str.strip() == old_name
                    edited.loc[mask, "Project"] = clean_name
                    edited.loc[mask, "Goal"] = (picked_goal or "").strip()
                    edited.loc[mask, "Description"] = description
                    edited.loc[mask, "Advantages"] = advantages
                    edited.loc[mask, "Limitations"] = limitations
                    edited.loc[mask, "Future gain"] = future_gain
                    edited.loc[mask, "Completed"] = (
                        completed_on.isoformat() if (finished and completed_on) else ""
                    )
                    for col, value in stars.items():
                        edited.loc[mask, col] = value
                    try:
                        kd.save_goals(edited)
                    except PermissionError:
                        st.error("Couldn't save — Special_Projects_Ratings.xlsx is open in Excel "
                                 "(or locked by OneDrive). Close it and save again.")
                    else:
                        if clean_name != old_name:
                            warning = kd.rename_project_tasks(old_name, clean_name)
                            if warning:
                                st.session_state["tasks_save_warning"] = warning
                            st.session_state["_renamed_to"] = clean_name
                        # The ratings grid below caches its own edits against the old values.
                        st.session_state.pop("goals_editor", None)
                        st.success("Saved. Reloading...")
                        st.rerun()


st.markdown(
    """
    <style>
    .st-key-tasks-panel, .st-key-tasks-panel * { font-size: 0.82rem !important; }
    .st-key-tasks-panel button { font-size: 0.82rem !important; }
    </style>
    """,
    unsafe_allow_html=True,
)

ks.header("Special Projects",
          "Goal ratings, per-project task checklists, and predicted timelines")
page_nav([("What's next", "whats-next"), ("Goals chart", "goals-chart"),
          ("Project card", "project-card"), ("Timeline", "timeline"),
          ("All projects", "timeline-all"), ("All ratings", "all-ratings")])

# --- What's next / what's late, across every special project -------------------------------
# Leads the page: this is the one actionable, time-sensitive panel here, so it comes before
# the overview chart and project drill-down rather than being buried under them.
anchor("whats-next")
sched_tasks = kcache.load_project_tasks()
upcoming, overdue = kd.task_schedule(sched_tasks, within_days=60)


def render_schedule(entries, empty_text, late):
    if not entries:
        st.caption(empty_text)
        return
    for e in entries:
        when = (f"{abs(e['days'])} day{'' if abs(e['days']) == 1 else 's'} late" if late
                else "today" if e["days"] == 0
                else f"in {e['days']} day{'' if e['days'] == 1 else 's'}")
        colour = "red" if late else "blue"
        st.markdown(
            f"**{e['due'].strftime('%d %b %Y')}** · :{colour}[{when}]  \n"
            f"{e['text']} — *{e['project']}*"
        )


n1, n2 = st.columns(2)
with n1:
    st.markdown(f"#### ⏭️ Coming up in 2 months ({len(upcoming)})")
    render_schedule(upcoming, "No dated tasks in the next 2 months — add planned dates to a project's tasks.", late=False)
with n2:
    st.markdown(f"#### ⚠️ Behind ({len(overdue)})")
    render_schedule(overdue, "Nothing overdue.", late=True)

st.caption(
    "x = Development stars, y = Impact stars, bubble size = Visibility stars, colored by Goal. "
    "The four shaded quadrants read effort against impact (key below the chart). "
    "Maintenance isn't plotted as an axis but shows up on hover alongside each project's "
    "description, advantages and limitations."
)


def quadrant_key():
    """The four effort/impact quadrants spelled out under the chart -- built from
    kc.GOAL_QUADRANTS so the wording and tints can't drift from what's drawn."""
    items = "".join(
        "<li style='margin:0 0 2px'>"
        f"<span style='display:inline-block;width:9px;height:9px;border-radius:2px;"
        f"background:{tint};opacity:.55;margin-right:6px'></span>"
        f"<b>{label}</b> — {meaning}</li>"
        for label, meaning, _qx, _qy, tint in kc.GOAL_QUADRANTS
    )
    st.markdown(
        "<ul style='list-style:none;padding:0;margin:-.5rem 0 .8rem;font-size:.8rem;"
        f"opacity:.85;columns:2;column-gap:2rem'>{items}</ul>",
        unsafe_allow_html=True,
    )

# Editing throttles the Excel mirror (see kd.TASKS_MIRROR_MAX_LAG), so catch it up once
# when the page is first opened in a session rather than on every rerun.
if not READONLY and not st.session_state.get("_tasks_excel_synced"):
    st.session_state["_tasks_excel_synced"] = True
    if kd.sync_tasks_excel():
        st.session_state["tasks_save_warning"] = True

goals_df = kcache.load_goals()

if not len(goals_df):
    st.info("Special_Projects_Ratings.xlsx has no rows yet.")
else:
    anchor("goals-chart")
    fig = kc.fig_goals_at_a_glance(goals_df)
    event = st.plotly_chart(
        fig, key="goals_chart", on_select="rerun", selection_mode="points", width="stretch",
    )
    quadrant_key()

    points = (event or {}).get("selection", {}).get("points", [])
    clicked_project = points[0]["customdata"][0] if points else None
    project_names = sorted(goals_df["Project"].astype(str).str.strip().unique())

    # A rename from the edit panel below can't set the selectbox's own session key directly
    # (that widget has already been created by then), so it parks the new name here and the
    # selection follows it on this next run.
    renamed_to = st.session_state.pop("_renamed_to", None)
    if renamed_to in project_names:
        st.session_state["selected_project_name"] = renamed_to

    # A bubble click's selection state persists across every later rerun (not just the one
    # right after the click), so only push it into the dropdown the first time we see it --
    # otherwise it would keep stomping a manual dropdown change made afterwards.
    last_synced = st.session_state.get("_last_synced_click")
    if clicked_project is not None:
        clicked_clean = str(clicked_project).strip()
        if clicked_clean in project_names and clicked_clean != last_synced:
            st.session_state["selected_project_name"] = clicked_clean
            st.session_state["_last_synced_click"] = clicked_clean

    st.subheader("Project card", anchor="project-card")
    default_name = st.session_state.get("selected_project_name", project_names[0])
    if default_name not in project_names:
        default_name = project_names[0]
    selected_name = st.selectbox(
        "Select project", project_names, index=project_names.index(default_name), key="selected_project_name",
    )
    st.caption("Pick a project here, or click its bubble above -- either one updates the other.")

    row = goals_df.loc[goals_df["Project"].astype(str).str.strip() == selected_name].iloc[0]
    left, right = st.columns([1, 1.3])
    with left:
        with st.container(border=True):
            render_card(row)
        if not READONLY:
            render_goal_editor(goals_df, row, project_names)
    with right:
        with st.container(key="tasks-panel"):
            # Always the trimmed name: checklists are keyed by project name, and keying them
            # by the raw sheet value stranded them whenever the name got trimmed later.
            render_tasks(selected_name)

    anchor("timeline")
    # Stable keys let Streamlit reuse the existing chart elements across reruns instead of
    # tearing them down and rebuilding them in the browser.
    st.plotly_chart(
        kc.fig_task_timeline(sched_tasks.get(selected_name, []), selected_name),
        width="stretch", key="chart_project_timeline",
    )

    st.subheader("All special projects", anchor="timeline-all")
    # Pin the axis to the whole reporting year so projects sit on a stable calendar rather
    # than on a window that shifts with whatever dates happen to be set. The chart widens it
    # past the year when a project is planned to finish later, so no bar gets cut off.
    periods = kcache.discover_periods()
    year_range = (periods[0]["start"], periods[0]["end"]) if periods else None
    st.caption(
        "Each project from the month its first planned task falls in to the month it should "
        "finish, labelled with tasks done; hover a bar for its tasks. "
        + (f"The axis covers the full {periods[0]['label']} reporting year, extended to the "
           "last planned month when a project runs past it. " if periods else "")
        + "Projects without planned dates don't appear — add dates to a project's tasks to place it here."
    )
    st.plotly_chart(
        kc.fig_all_projects_timeline(sched_tasks, project_names, axis_range=year_range),
        width="stretch", key="chart_all_timelines",
    )

    st.subheader("All ratings", anchor="all-ratings")
    edit_df = goals_df[kd.GOALS_EDIT_COLS].copy()
    # Collapsed by default: the editable grid is the heaviest thing on the page to draw, and
    # day-to-day editing now happens in the per-project pencil above.
    if st.toggle("Show the full ratings table (add or bulk-edit projects here)",
                 key="show_ratings_table"):
        if READONLY:
            st.dataframe(edit_df, width="stretch", hide_index=True)
        else:
            st.caption("Edit any cell, or add a new row (only Project is required — blank star "
                       "ratings default to 1), then save.")
            edited = st.data_editor(edit_df, num_rows="dynamic", width="stretch", key="goals_editor")
            if st.button("💾 Save changes to Special_Projects_Ratings.xlsx"):
                try:
                    kd.save_goals(edited)
                except PermissionError:
                    st.error("Couldn't save — Special_Projects_Ratings.xlsx is open in Excel (or "
                             "locked by OneDrive). Close it and click Save again; your edits are "
                             "still in the table above.")
                else:
                    st.success("Saved. Reloading...")
                    st.rerun()
