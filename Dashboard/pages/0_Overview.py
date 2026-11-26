"""Overview — Week / Month / Year views over the live time log and project tracker. Run
the dashboard with:  streamlit run KPI_Report.py  (this page itself is routed to by that
entrypoint's st.navigation, not run directly).
Every rerun re-reads the Excel/CSV files in ../Data, so editing them and refreshing the
page (or touching any control) always shows the latest data."""

import pandas as pd
import streamlit as st

import kpi_cache as kcache
import kpi_charts as kc
import kpi_data as kd
import kpi_style as ks
from kpi_style import anchor, page_nav

st.set_page_config(page_title="KPI Report", page_icon="📊", layout="wide")
kc.set_theme(dark=st.context.theme.type == "dark")
ks.inject(dark=st.context.theme.type == "dark")

# A link with ?readonly=true hides every editing control on every page (session_state keeps
# it in effect across page navigation even if the URL's query string itself gets dropped by
# the sidebar's client-side routing; re-checking query_params each page still lets a direct
# deep-link into another page with ?readonly=true on it work on its own).
if st.query_params.get("readonly") is not None:
    st.session_state["readonly"] = st.query_params.get("readonly") in ("1", "true", "yes", "True")
READONLY = st.session_state.get("readonly", False)
if READONLY:
    st.info("📖 Read-only view — editing controls are hidden.", icon="📖")

# Project work at the CATEGORY level: both project categories together, as opposed to
# org/admin, training, or non-project meeting time.
PROJECT_CATEGORIES = ["Projects", "Projects-Development"]
# "Development" = time spent building things -- tools and AI Skills -- wherever it was
# logged, so it is keyed on the major task rather than the category: a tool built for a
# user project and one built for internal use both count.
DEV_MAJOR_TASKS = ["Tools", "AI Skills"]


df, CATEGORY_ORDER, CATEGORY_COLORS, task_category, raw_df = kcache.load_timelog(dark=st.context.theme.type == "dark")
periods = kcache.discover_periods()

if not periods:
    st.error("No reporting-period sheets found in any KPI*.xlsx file in ../Data (expected names like '2025_CALENDAR').")
    st.stop()

today = pd.Timestamp.now().normalize()

# --- Header: title + period selector -------------------------------------------------------
left, right = st.columns([3, 1])
with left:
    ks.header("KPI Report",
              "Time log · project tracker · special projects · tools inventory")
with right:
    period_labels = [p["label"] for p in periods]
    default_period_label = st.session_state.get("selected_period", period_labels[0])
    if default_period_label not in period_labels:
        default_period_label = period_labels[0]
    period_label = st.selectbox(
        "Reporting period", period_labels, index=period_labels.index(default_period_label), key="selected_period",
    )
period = next(p for p in periods if p["label"] == period_label)
is_active_period = period["start"] <= today < period["end"]

with st.sidebar:
    st.subheader("About this dashboard")
    st.caption(
        "Reads ../Data/track_time.csv, every KPI*.xlsx file, and Special_Projects_Ratings.xlsx live. "
        "Edit a file and rerun (or just interact with any control) to see the update."
    )
    with st.expander("📖 Category & task glossary"):
        st.markdown(kd.GLOSSARY_MD)

df_period = kd.filter_to_period(df, period)
projects = kcache.load_projects(period["file"], period["sheet"])
project_desc = projects.set_index("Project tag")["Short Description"] if "Short Description" in projects.columns else None

# Real, tracker-registered projects -- for "Projects touched" tiles. The time log's own
# distinct Project tags also include non-project buckets (Org & Admin, Consulting,
# Trainning, Seminário, ...) and the occasional mistagged/orphan tag that was never
# actually registered in the tracker; a positive match against the tracker itself catches
# both, with no blocklist to keep growing as new buckets get added.
REAL_PROJECT_TAGS = set(projects["Project tag"].astype(str).str.strip())

tab_week, tab_month, tab_year = st.tabs(["📅 Week", "🗓️ Month", "📈 Year"])

# ============================================================================================
# WEEK
# ============================================================================================
with tab_week:
    weeks = kd.selectable_weeks(df, period, today)
    if not weeks:
        st.info(
            "track_time.csv has no entries for this reporting period — the Week/Month/Year-time "
            "views are empty, but the project tracker itself (received vs finished, complexity, "
            "who-we-work-with, etc.) is unaffected — see the Year tab and the **Projects Review** page."
        )
    else:
        default_start = kd.default_week(weeks, today)
        week_options = [w[0] for w in weeks]
        week_labels = {w[0]: w[1] for w in weeks}
        selected_start = st.selectbox(
            "Week", week_options, index=week_options.index(default_start),
            format_func=lambda s: week_labels[s], key="week_select",
        )
        selected_label = week_labels[selected_start]
        week_df = df[df["_week_sort"] == selected_start]
        previous_start = selected_start - pd.Timedelta(days=7)
        previous_df = df[df["_week_sort"] == previous_start]
        previous_label = kd.format_week_label(previous_start, previous_start + pd.Timedelta(days=6))

        page_nav([
            ("Hours this week", "week-hours"), ("By project & task", "week-by-task"),
            ("Change from last week", "week-change"), ("Time log", "week-timelog"),
        ])

        # Headline numbers for the selected week. No week-on-week delta on the hours tile --
        # the "Change from last week" charts below already cover that comparison.
        total_week_hours = week_df["Hours (exact)"].sum()
        timesheet_week = raw_df.loc[df.index[df["_week_sort"] == selected_start], "Timesheet updated"].astype(str).str.strip()
        n_tracked = int((timesheet_week.isin(["Yes", "No"])).sum())
        n_updated = int((timesheet_week == "Yes").sum())
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Hours logged", kd.format_hm(total_week_hours))
        m2.metric("Projects touched", int(week_df.loc[week_df["Project"].isin(REAL_PROJECT_TAGS), "Project"].nunique()))
        m3.metric("Entries", int(len(week_df)))
        m4.metric("Timesheet updated", f"{n_updated}/{n_tracked}" if n_tracked else "—",
                  help="Week entries marked 'Yes' out of those marked 'Yes'/'No' in the Timesheet "
                       "column below -- entries marked 'N/A' (not supposed to be logged in the "
                       "timesheet) don't count toward either side.")

        anchor("week-hours")
        c1, c2 = st.columns([1.3, 1])
        with c1:
            st.plotly_chart(kc.fig_week_hours_by_project(week_df, selected_label, project_desc), width="stretch")
        with c2:
            cat_hours = kc.category_hours_frame(week_df, CATEGORY_ORDER, CATEGORY_COLORS)
            st.plotly_chart(
                kc.fig_category_donut(cat_hours, f"Category share — week of {selected_label}",
                                       "No hours logged yet for this week"),
                width="stretch",
            )

        anchor("week-by-task")
        st.plotly_chart(
            kc.fig_hours_by_project_task(week_df, selected_label, task_category, CATEGORY_ORDER, CATEGORY_COLORS),
            width="stretch",
        )

        st.subheader("Change from last week", anchor="week-change")
        st.caption(
            "Diverging bars: each project's/category's hour change versus the previous calendar "
            "week — green for an increase, red for a decrease. No hours in one of the two weeks "
            "counts as 0 for that week rather than being dropped."
        )
        delta_p = kc.change_delta(week_df, previous_df, "Project")
        delta_c = kc.change_delta(week_df, previous_df, "Category")
        ch1, ch2 = st.columns(2)
        with ch1:
            st.plotly_chart(
                kc.fig_change_bars(delta_p, f"By project ({previous_label} → {selected_label})",
                                    "No change from last week", height=380),
                width="stretch",
            )
        with ch2:
            st.plotly_chart(
                kc.fig_change_bars(delta_c, f"By category ({previous_label} → {selected_label})",
                                    "No change from last week", height=380),
                width="stretch",
            )

        st.divider()
        st.subheader(f"Time log — week of {selected_label}", anchor="week-timelog")

        week_mask = df["_week_sort"] == selected_start
        week_raw = raw_df.loc[df.index[week_mask], kd.EDIT_COLS].copy()
        # Show the already-renamed major task label (e.g. "AI Skills", not the raw file's
        # stale "AI Agent") so it always matches an option above -- saving this row then
        # naturally migrates it to the current name.
        week_raw["Major task name (chart)"] = df.loc[df.index[week_mask], "Major task name (chart)"]

        # Sort controls -- the editable grid itself can't sort while rows are addable, so
        # reorder the frame before handing it to the editor. orig_index follows the same
        # order, so saving maps each editor row back to the right file row regardless.
        SORT_COLS = {
            "Project": "Weekly entry name (chart)", "Category": "Category",
            "Major task": "Major task name (chart)", "Hrs": "Hrs", "Timesheet": "Timesheet updated",
        }
        if not READONLY:
            # Re-sorting remounts the editor under a new key, which would silently discard
            # any unsaved edits -- so while edits are pending, lock the sort controls and
            # offer an explicit save-or-discard choice instead.
            cur_sort = st.session_state.get("week_sort_col", "(file order)")
            cur_desc = st.session_state.get("week_sort_dir", "⬆ Ascending") == "⬇ Descending"
            editor_key = f"editor_{period_label}_{selected_label}_{cur_sort}_{cur_desc}"
            editor_state = st.session_state.get(editor_key, {})
            has_pending = any(editor_state.get(k) for k in ("edited_rows", "added_rows", "deleted_rows"))

            sc1, sc2, sc3 = st.columns([1.2, 1, 3])
            sort_choice = sc1.selectbox("Sort by", ["(file order)"] + list(SORT_COLS),
                                        key="week_sort_col", disabled=has_pending)
            sort_desc = sc2.selectbox("Direction", ["⬆ Ascending", "⬇ Descending"],
                                      key="week_sort_dir", disabled=has_pending) == "⬇ Descending"
            if has_pending:
                with sc3:
                    st.warning("Unsaved changes in the table — 💾 Save them below, or discard. "
                               "(Sorting and changing week would lose them.)", icon="✏️")
                    if st.button("↩ Discard unsaved changes", key=f"discard_{editor_key}"):
                        st.session_state.pop(editor_key, None)
                        st.rerun()
        else:
            sort_choice, sort_desc = "(file order)", False
        if sort_choice != "(file order)":
            col = SORT_COLS[sort_choice]
            sort_key = (None if col == "Hrs"
                        else lambda s: s.astype(str).str.strip().str.lower().replace("nan", ""))
            week_raw = week_raw.sort_values(col, ascending=not sort_desc, key=sort_key, kind="stable")

        orig_index = list(week_raw.index)
        week_raw = week_raw.reset_index(drop=True)

        if READONLY:
            st.dataframe(week_raw, width="stretch", hide_index=True)
        else:
            st.caption("Edit hours directly, or fill in one of the blank rows at the bottom for a new entry "
                       "(save and reopen the tab for more blank rows once you run out) — nothing is written "
                       "until you save. In the Project / Category / Major task cells you can pick an existing "
                       "tag **or type a brand-new one**, and it's kept when you save.")

            custom_tags = kd.load_custom_tags()
            # str-filtered: a row saved with that cell left blank round-trips through the
            # CSV as NaN (a float), and sorted() can't compare a float against the other
            # tags' strings -- drop it rather than let the whole tab crash on reload.
            def _tag_values(series):
                return {v for v in series.unique() if isinstance(v, str) and v.strip()}
            project_options = sorted(_tag_values(df["Project"]) | set(custom_tags["projects"]))
            category_options = [c for c in CATEGORY_ORDER if c in _tag_values(df["Category"])]
            category_options += sorted(set(custom_tags["categories"]) - set(category_options))
            task_options = sorted(_tag_values(df["Major task name (chart)"]) | set(custom_tags["major_tasks"]))

            # Rendered as MultiselectColumn rather than SelectboxColumn so new tags can be
            # typed straight into a cell -- see kd.tag_to_cell / kd.tag_from_cell.
            TAG_COLS = {
                "Weekly entry name (chart)": ("Project", "projects", project_options),
                "Category": ("Category", "categories", category_options),
                "Major task name (chart)": ("Major task", "major_tasks", task_options),
            }

            # Still worth keeping alongside the in-grid typing: it registers a tag you'll want
            # later without having to log a row for it now, and it lists what already exists so
            # near-duplicates ("code" vs "Code") are easy to spot before adding another one.
            with st.expander("➕ New tag without logging time — add a project / category / major task up front"):
                st.caption("Optional — you can also just type a new tag straight into the table below. "
                           "Tags added here are saved to custom_tags.json, so they stay in the dropdowns "
                           "even before any row uses them.")
                nc1, nc2, nc3 = st.columns(3)
                tag_inputs = [
                    ("projects", nc1.selectbox(
                        "Project tag", project_options, index=None, accept_new_options=True,
                        key="new_project_input", placeholder="type a new project tag")),
                    ("categories", nc2.selectbox(
                        "Category", category_options, index=None, accept_new_options=True,
                        key="new_category_input", placeholder="type a new category")),
                    ("major_tasks", nc3.selectbox(
                        "Major task", task_options, index=None, accept_new_options=True,
                        key="new_task_input", placeholder="type a new major task")),
                ]
                if st.button("Add", key="add_new_tags_btn"):
                    existing = {"projects": project_options, "categories": category_options,
                                "major_tasks": task_options}
                    fresh = {kind: [v] for kind, v in tag_inputs
                             if v and v.strip() not in existing[kind]}
                    known = [v for kind, v in tag_inputs if v and v.strip() in existing[kind]]
                    added = kd.add_custom_tags(**fresh) if fresh else []
                    if added:
                        st.success("Added " + ", ".join(f"'{a}'" for a in added) + " — now selectable below.")
                        st.rerun()
                    elif known:
                        st.info(", ".join(f"'{k}'" for k in known) + " already exists — just pick it in the table.")
                    else:
                        st.info("Type at least one new tag above before clicking Add.")

            # num_rows must stay "fixed": the grid's own row-adding writes each new row with
            # df.loc[i, :] = [list of cell values], which pandas cannot do when one of those
            # values is itself a list -- and the tag cells are lists (see TAG_COLS above). So a
            # fixed pool of blank rows is appended up front instead, always the same size run
            # to run -- changing the editor's own row count between reruns (as an earlier,
            # button-driven version of this did) resets Streamlit's own pending-edit state for
            # the whole widget, silently discarding whatever else was typed and not yet saved.
            N_BLANK_ROWS = 6
            editor_df = week_raw.copy()
            for col in TAG_COLS:
                # dtype=object explicitly: on a week with zero rows the assignment would
                # otherwise keep the column's all-NA float dtype, which the multiselect
                # column config rejects (crashing the whole Week tab for an empty week).
                editor_df[col] = pd.Series([kd.tag_to_cell(v) for v in editor_df[col]],
                                           index=editor_df.index, dtype=object)
            # Built column by column with the frame's own dtypes: a plain DataFrame of blank
            # rows would be all-NA in the numeric columns, which makes concat warn about (and
            # one day change) the resulting dtypes. A numeric column (Hrs, Min) can be pure
            # int64 if every row this week happens to have a value -- int64 can't hold a blank
            # at all, so None there raises in pandas' own Series construction. NaN is the one
            # blank value every dtype accepts, but it still needs a float dtype to carry it,
            # hence the upcast below (harmless: NumberColumn renders a float the same as an int).
            blank_idx = range(len(editor_df), len(editor_df) + N_BLANK_ROWS)
            editor_df = pd.concat([editor_df, pd.DataFrame({
                col: pd.Series(
                    [[] for _ in range(N_BLANK_ROWS)] if col in TAG_COLS
                    else (["No"] * N_BLANK_ROWS if col == "Timesheet updated" else [float("nan")] * N_BLANK_ROWS),
                    index=blank_idx,
                    dtype=(object if col in TAG_COLS
                           else "float64" if pd.api.types.is_integer_dtype(editor_df[col])
                           else editor_df[col].dtype))
                for col in editor_df.columns}, index=blank_idx)])

            edited = st.data_editor(
                editor_df, num_rows="fixed", width="stretch",
                key=f"editor_{period_label}_{selected_label}_{sort_choice}_{sort_desc}",
                column_config={
                    **{col: st.column_config.MultiselectColumn(
                        label, options=opts, accept_new_options=True, color="primary",
                        help="Pick a tag, or type a new one and press Enter. One tag per cell.")
                       for col, (label, _kind, opts) in TAG_COLS.items()},
                    "Hrs": st.column_config.NumberColumn("Hrs", min_value=0, step=1),
                    "Min": st.column_config.NumberColumn("Min", min_value=0, max_value=59, step=1),
                    "Timesheet updated": st.column_config.SelectboxColumn(
                        "Timesheet", options=["Yes", "No", "N/A"],
                        help="Has this time been entered in the timesheet? Pick 'N/A' if it isn't "
                             "supposed to be logged there at all -- it won't count toward the "
                             "Timesheet updated tile above."),
                },
            )
            edited = edited.copy()

            # Row removal: a companion read-only table of the same rows, using Streamlit's own
            # row-selection checkboxes (not a data column mixed into the editable grid itself).
            # Selecting a row here doesn't touch editor_df's shape -- same reasoning as above --
            # so it's only actually dropped once, right before Save.
            del_display = pd.DataFrame({
                "Project": [kd.tag_from_cell(c) for c in edited["Weekly entry name (chart)"]],
                "Category": [kd.tag_from_cell(c) for c in edited["Category"]],
                "Major task": [kd.tag_from_cell(c) for c in edited["Major task name (chart)"]],
                "Hrs": edited["Hrs"], "Min": edited["Min"],
            }, index=edited.index)
            st.caption("To remove a row, select it below (click its row) and then save — "
                       "blank/unfilled rows are harmless to select too.")
            del_state = st.dataframe(
                del_display, width="stretch", hide_index=True, on_select="rerun",
                selection_mode="multi-row",
                key=f"delrows_{period_label}_{selected_label}_{sort_choice}_{sort_desc}",
            )
            rows_to_delete = list(del_state["selection"]["rows"])
            if rows_to_delete:
                st.info(f"{len(rows_to_delete)} row(s) selected for removal on save.")
                edited = edited.drop(index=[i for i in rows_to_delete if i in edited.index])

            overfilled = False
            for col in TAG_COLS:
                cells = list(edited[col])
                overfilled |= any(kd.tag_cell_overfilled(c) for c in cells)
                edited[col] = [kd.tag_from_cell(c) for c in cells]
            if overfilled:
                st.warning("A Project / Category / Major task cell holds more than one tag — "
                           "only the first one is saved.", icon="⚠️")

            if st.button("💾 Save changes to track_time.csv", key=f"save_{period_label}_{selected_label}"):
                updated_raw = kd.apply_week_edits(raw_df, orig_index, edited, selected_start)
                try:
                    updated_raw.to_csv(kd.TIMELOG_PATH, sep=";", index=False, encoding="utf-8-sig")
                except PermissionError:
                    st.error("Couldn't save — track_time.csv is open in Excel (or locked by OneDrive). "
                             "Close it and click Save again; your edits are still in the table above.")
                else:
                    # Typed-in tags also go to custom_tags.json, so they survive deleting the row
                    # that introduced them. Failing to record them is not worth losing the save
                    # that already succeeded.
                    fresh = {kind: sorted({v for v in edited[col] if v and v not in set(opts)})
                             for col, (_label, kind, opts) in TAG_COLS.items()}
                    try:
                        new_tags = kd.add_custom_tags(**fresh) if any(fresh.values()) else []
                    except OSError:
                        new_tags = []
                    st.session_state.pop(f"editor_{period_label}_{selected_label}_{sort_choice}_{sort_desc}", None)
                    st.session_state.pop(f"delrows_{period_label}_{selected_label}_{sort_choice}_{sort_desc}", None)
                    st.success("Saved." + (f" New tags kept: {', '.join(new_tags)}." if new_tags else "")
                               + " Reloading...")
                    st.rerun()

# ============================================================================================
# MONTH
# ============================================================================================
with tab_month:
    df_period_labeled, months_present = kd.label_period_months(df_period)
    if not months_present:
        st.info(
            "track_time.csv has no entries for this reporting period — see the Year tab and the "
            "**Projects Review** page for the project tracker's own data."
        )
    else:
        current_label = today.strftime("%B %Y")
        default_m = kd.default_month(months_present, current_label)
        selected_month = st.selectbox(
            "Month", months_present, index=months_present.index(default_m), key="month_select",
        )
        month_df = df_period_labeled[df_period_labeled["Month"] == selected_month]
        month_name_only = selected_month.split(" ")[0]

        # Real, tracker-cross-referenced active projects for this month -- shared by the
        # chart below and the "Active projects" table further down, so the two can't drift
        # apart. Not the raw time log's distinct Project tags: that set also contains
        # non-project buckets (Org & Admin, Consulting, ...) and the occasional
        # mistagged/orphan entry (a tag that was never actually registered in the tracker).
        year_num = int(selected_month.split(" ")[1])
        month_start = pd.Timestamp(year=year_num, month=kd.MONTH_ORDER.index(month_name_only) + 1, day=1)
        month_end = month_start + pd.offsets.MonthEnd(0)
        active_start = kd.effective_workload_start(projects)
        active_mask = (
            active_start.notna()
            & (active_start <= month_end)
            & (projects["Final Report Sent"].isna() | (projects["Final Report Sent"] >= month_start))
        )

        month_hours = month_df["Hours (exact)"].sum()
        mm1, mm2, mm3, mm4 = st.columns(4)
        mm1.metric("Hours logged", kd.format_hm(month_hours))
        mm2.metric("Projects touched", int(month_df.loc[month_df["Project"].isin(REAL_PROJECT_TAGS), "Project"].nunique()))
        mm3.metric("Entries", int(len(month_df)))
        mm4.metric("Weeks with entries", int(month_df["_week_sort"].nunique()))

        page_nav([
            ("Monthly charts", "month-charts"), ("Weekly breakdown", "month-weekly"),
            ("Active projects", "month-active"),
        ])

        anchor("month-charts")
        c1, c2 = st.columns([1.3, 1.6])
        with c1:
            cat_hours = kc.category_hours_frame(month_df, CATEGORY_ORDER, CATEGORY_COLORS)
            st.plotly_chart(
                kc.fig_category_donut(cat_hours, f"Category share — {selected_month}",
                                       f"No hours logged yet for {selected_month}"),
                width="stretch",
            )

            active_projects = sorted(projects.loc[active_mask, "Project tag"].dropna().unique())
            concluded_mask = (
                projects["Final Report Sent"].notna()
                & (projects["Final Report Sent"].dt.month_name() == month_name_only)
                & (projects["Final Report Sent"].dt.year == int(selected_month.split(" ")[1]))
            )
            concluded_projects = sorted(projects.loc[concluded_mask, "Project tag"].dropna().unique())
            st.plotly_chart(
                kc.fig_active_vs_concluded(active_projects, concluded_projects, selected_month, project_desc),
                width="stretch",
            )
        with c2:
            st.plotly_chart(
                kc.fig_major_task_share_by_category(month_df, selected_month, CATEGORY_ORDER, CATEGORY_COLORS),
                width="stretch",
            )

        anchor("month-weekly")
        st.plotly_chart(
            kc.fig_category_weekly_distribution(month_df, CATEGORY_ORDER, CATEGORY_COLORS,
                                                  title=f"Category distribution by week — {selected_month}"),
            width="stretch",
        )

        st.subheader(f"Active projects — {selected_month}", anchor="month-active")
        st.caption(
            "Active = open from First User Meeting/Shared Data until Final Report Sent "
            "(same definition as the workload line in the Year tab; an Inherited Project "
            "only starts counting at its Begining)."
        )
        LISTING_COLS = [c for c in ["Project tag", "Project Trigger", "Type of Data", "Project Outputs", "Short Description"] if c in projects.columns]
        st.dataframe(projects.loc[active_mask, LISTING_COLS], width="stretch", hide_index=True)

# ============================================================================================
# YEAR
# ============================================================================================
with tab_year:
    page_nav([
        ("Received vs finished", "year-received"), ("Time logged trends", "year-timelog"),
    ])
    weeks_logged = int(df_period["_week_sort"].nunique())
    total_hours = df_period["Hours (exact)"].sum()
    project_hours = df_period.loc[df_period["Category"].isin(PROJECT_CATEGORIES), "Hours (exact)"].sum()
    dev_hours = df_period.loc[
        df_period["Major task name (chart)"].isin(DEV_MAJOR_TASKS), "Hours (exact)"].sum()
    weeks_label = f"{weeks_logged} logged week" + ("" if weeks_logged == 1 else "s")
    project_pct = f" ({project_hours / total_hours * 100:.0f}%)" if total_hours else ""
    dev_pct = f" ({dev_hours / total_hours * 100:.0f}%)" if total_hours else ""
    ym1, ym2, ym3 = st.columns(3)
    ym1.metric("Projects touched",
               int(df_period.loc[df_period["Project"].isin(REAL_PROJECT_TAGS), "Project"].nunique()))
    ym1.caption(f"Distinct projects with logged hours · {weeks_label}")
    ym2.metric("Avg per logged week — projects",
               kd.format_hm(project_hours / weeks_logged) if weeks_logged else "—",
               help="Hours in the **Projects** and **Projects-Development** categories "
                    "(the category, not the major task), divided by the weeks with entries.")
    ym2.caption(f"{kd.format_hm(project_hours)}{project_pct} total · Projects + Projects-Development")
    ym3.metric("Avg per logged week — tools & AI",
               kd.format_hm(dev_hours / weeks_logged) if weeks_logged else "—",
               help="Hours on the **Tools** and **AI Skills** major tasks, wherever they "
                    "were logged — internal work and project work both count — divided "
                    "by the weeks with entries.")
    ym3.caption(f"{kd.format_hm(dev_hours)}{dev_pct} total · internal or project")
    st.subheader(f"Projects received vs finished — {period_label}", anchor="year-received")
    st.caption(
        "Driven by the project tracker sheet for this period. For complexity, who-we-work-with, "
        "and the rest of the project tracker, see the **Projects Review** page in the sidebar."
    )
    period_months = pd.period_range(f"{period['start'].year}-01", f"{period['end'].year}-01", freq="M")
    truncate_at = today.to_period("M") if is_active_period else None
    st.plotly_chart(
        kc.fig_received_vs_finished(projects, period_months, period["start"], truncate_at),
        width="stretch",
    )
    gap_stats = kd.closing_gap_summary(projects)
    if gap_stats["n_finished"]:
        bits = [f"**{gap_stats['n_finished']}** closed this period"]
        if gap_stats["n_same_day"]:
            bits.append(f"{gap_stats['n_same_day']} the same day the final report went out")
        if gap_stats["n_delayed"]:
            bits.append(f"{gap_stats['n_delayed']} took a median {kd.format_days(gap_stats['median_gap_days'])} "
                         "longer to formally close after the report was delivered")
        st.caption(" · ".join(bits) + " — hover a bar above for which.")
    with st.expander("📖 Chart legend"):
        st.markdown(kd.RECEIVED_FINISHED_GLOSSARY_MD)

    st.divider()
    st.subheader(f"Time logged — {period_label}", anchor="year-timelog")
    if not len(df_period):
        st.info("track_time.csv has no entries for this reporting period — the project tracker overview above is unaffected.")
    else:
        df_period_labeled, months_present = kd.label_period_months(df_period)
        st.plotly_chart(
            kc.fig_category_share_stacked(df_period, f"Category share of total hours — {period_label}", CATEGORY_ORDER, CATEGORY_COLORS),
            width="stretch",
        )
        st.plotly_chart(
            kc.fig_major_task_share_stacked(df_period, f"Major task share of total hours — {period_label}", task_category, CATEGORY_ORDER, CATEGORY_COLORS),
            width="stretch",
        )
        st.plotly_chart(
            kc.fig_category_hours_by_month(df_period_labeled, months_present, CATEGORY_ORDER, CATEGORY_COLORS),
            width="stretch",
        )
        st.plotly_chart(
            kc.fig_monthly_major_task_hours(df_period_labeled, months_present, task_category, CATEGORY_ORDER, CATEGORY_COLORS),
            width="stretch",
        )
