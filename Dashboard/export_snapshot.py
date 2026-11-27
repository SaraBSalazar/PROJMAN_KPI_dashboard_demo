"""Build a static, read-only snapshot of the KPI dashboard as one self-contained HTML file.

Unlike `streamlit run`, the result needs no server: share the file itself (OneDrive, email)
or publish it as a hosted web page -- it keeps working with your computer off, and nothing
in it is editable.

The page mirrors the dashboard's own navigation instead of being one long scroll: a
reporting-period selector, tabs for Week / Month / Year / Turnaround / Special projects /
Tools, and week / month / project pickers inside them. Every view is built at export time
and the browser only switches between them, so browsing feels live while the numbers stay
frozen at the moment of export.

Charts are stored once as figure specs (light + dark, the same validated themes as the
Streamlit dashboard) and drawn on demand in the viewer's theme -- only what is on screen is
ever plotted, which is what keeps a page holding every view at once fast to open.

Run from the Dashboard folder:

    python export_snapshot.py

Writes two files to ../Share/:
  KPI_Report_snapshot.html   full standalone page (open directly in any browser)
  _artifact_snapshot.html         same content, formatted for publishing as a Claude artifact
"""

import datetime
import html as html_mod
import json
from pathlib import Path

import pandas as pd
import plotly.utils
from plotly.offline import get_plotlyjs

import kpi_charts as kc
import kpi_data as kd

SHARE_DIR = Path(__file__).resolve().parent.parent / "Share"

# The dashboard's own design tokens (kpi_data/kpi_charts light + dark themes), reused as
# the page palette. Light lives on bare :root; the dark blocks redefine ONLY tokens,
# guarded so an explicit data-theme choice wins over the OS.
CSS = """
:root {
  --surface: #fcfcfb; --card: #ffffff; --ink: #0b0b0b; --ink-2: #52514e;
  --ink-3: #898781; --line: #e1e0d9; --accent: #1f5c99; --accent-soft: #eef3f8;
  --good: #0ca30c; --critical: #d03b3b;
  --pill-yes-bg: #e7f6e7; --pill-yes-ink: #07650a;
  --pill-no-bg: #fbeaea; --pill-no-ink: #9c2424;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --surface: #1a1a19; --card: #232321; --ink: #f2f1ee; --ink-2: #d0cec7;
    --ink-3: #938f87; --line: #3c3b38; --accent: #4a84c9; --accent-soft: #223042;
    --good: #4db34d; --critical: #e06c6c;
    --pill-yes-bg: #1e3a1e; --pill-yes-ink: #8fd48f;
    --pill-no-bg: #452222; --pill-no-ink: #e8a0a0;
  }
}
:root[data-theme="dark"] {
  --surface: #1a1a19; --card: #232321; --ink: #f2f1ee; --ink-2: #d0cec7;
  --ink-3: #938f87; --line: #3c3b38; --accent: #4a84c9; --accent-soft: #223042;
  --good: #4db34d; --critical: #e06c6c;
  --pill-yes-bg: #1e3a1e; --pill-yes-ink: #8fd48f;
  --pill-no-bg: #452222; --pill-no-ink: #e8a0a0;
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--surface); color: var(--ink);
  font-family: "IBM Plex Sans", "Segoe UI", system-ui, sans-serif;
  font-size: 15px; line-height: 1.55;
}
.wrap { max-width: 1100px; margin: 0 auto; padding: 32px 28px 80px; }
.eyebrow {
  font-size: 12px; letter-spacing: 0.14em; text-transform: uppercase;
  color: var(--accent); font-weight: 600; margin: 0 0 6px;
}
h1 { font-size: 34px; font-weight: 700; margin: 0 0 4px; letter-spacing: -0.01em; text-wrap: balance; }
.stamp { color: var(--ink-3); font-size: 13px; margin: 0 0 18px; max-width: 78ch; }

/* Navigation: tab bar + period picker, sticky so switching view never means scrolling back up. */
.toolbar {
  position: sticky; top: 0; z-index: 20; background: var(--surface);
  border-top: 1px solid var(--line); border-bottom: 1px solid var(--line);
  display: flex; flex-wrap: wrap; align-items: center; gap: 4px 20px;
  padding: 4px 0; margin-bottom: 26px;
}
.tabs { display: flex; flex-wrap: wrap; gap: 2px; flex: 1 1 auto; }
.tab {
  appearance: none; background: none; border: 0; border-bottom: 2px solid transparent;
  color: var(--ink-2); font: inherit; font-size: 13.5px; font-weight: 500;
  padding: 8px 11px 7px; cursor: pointer; border-radius: 6px 6px 0 0;
}
.tab:hover { color: var(--accent); background: var(--accent-soft); }
.tab.on { color: var(--accent); border-bottom-color: var(--accent); font-weight: 600; }
.tab:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }
.picker { display: flex; align-items: center; gap: 9px; margin: 0 0 18px; flex-wrap: wrap; }
.toolbar .picker { margin: 0; }
.picker label {
  font-size: 11.5px; letter-spacing: 0.1em; text-transform: uppercase;
  color: var(--ink-3); font-weight: 600;
}
select {
  font: inherit; font-size: 13.5px; color: var(--ink); background: var(--card);
  border: 1px solid var(--line); border-radius: 6px; padding: 5px 10px; max-width: 100%;
}
select:focus-visible { outline: 2px solid var(--accent); outline-offset: 1px; }
.panel { display: none; }
.panel.on { display: block; }
.panel > h2:first-child { margin-top: 6px; }
.opt { display: none; }
.opt.on { display: block; }

h2 { font-size: 22px; font-weight: 700; margin: 40px 0 4px; letter-spacing: -0.01em; }
h3 { font-size: 16.5px; font-weight: 600; margin: 26px 0 8px; }
.section-note { color: var(--ink-3); font-size: 13.5px; margin: 0 0 16px; max-width: 72ch; }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin: 20px 0 8px; }
.tile { background: var(--card); border: 1px solid var(--line); border-radius: 8px; padding: 14px 16px 12px; }
.tile .label { font-size: 11.5px; letter-spacing: 0.1em; text-transform: uppercase; color: var(--ink-3); font-weight: 600; }
.tile .value { font-family: "IBM Plex Mono", ui-monospace, monospace; font-size: 24px; font-weight: 600; margin-top: 2px; font-variant-numeric: tabular-nums; }
.tile .sub { font-size: 12.5px; color: var(--ink-2); margin-top: 2px; }
.chart { margin: 10px 0 26px; }
.grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; align-items: start; }
@media (max-width: 860px) { .grid-2 { grid-template-columns: 1fr; } }
.tablewrap { overflow-x: auto; border: 1px solid var(--line); border-radius: 8px; background: var(--card); margin: 10px 0 26px; }
table { border-collapse: collapse; width: 100%; font-size: 13.5px; }
th { text-align: left; font-size: 11.5px; letter-spacing: 0.08em; text-transform: uppercase; color: var(--ink-3); font-weight: 600; padding: 10px 14px; border-bottom: 1px solid var(--line); white-space: nowrap; }
td { padding: 8px 14px; border-bottom: 1px solid var(--line); vertical-align: top; }
tr:last-child td { border-bottom: none; }
td.num { font-family: "IBM Plex Mono", ui-monospace, monospace; font-variant-numeric: tabular-nums; text-align: right; }
.pill { display: inline-block; font-size: 11.5px; font-weight: 600; padding: 1px 9px; border-radius: 99px; }
.pill.yes { background: var(--pill-yes-bg); color: var(--pill-yes-ink); }
.pill.no { background: var(--pill-no-bg); color: var(--pill-no-ink); }
.cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 16px; margin: 14px 0 26px; }
.cards.single { grid-template-columns: minmax(320px, 620px); }
.card { background: var(--card); border: 1px solid var(--line); border-radius: 8px; padding: 18px 20px; }
.card h4 { margin: 0 0 2px; font-size: 15.5px; font-weight: 600; }
.card .meta { font-size: 12.5px; color: var(--ink-3); margin-bottom: 8px; }
.card ul { margin: 6px 0; padding-left: 18px; }
.card li { margin: 2px 0; }
.minus { color: var(--critical); font-size: 13.5px; margin: 4px 0 0; }
.plus { color: var(--good); font-size: 13.5px; margin: 4px 0 0; }
.gain { color: var(--accent); font-size: 13.5px; margin: 4px 0 0; }
.tasks { list-style: none; padding: 0; margin: 8px 0 4px; font-size: 13.5px; }
.tasks li { padding: 3px 0; display: flex; gap: 8px; align-items: baseline; }
.tasks .due { margin-left: auto; color: var(--ink-3); font-family: "IBM Plex Mono", ui-monospace, monospace; font-size: 12px; white-space: nowrap; }
.tasks .done-task { color: var(--ink-3); text-decoration: line-through; }
.predicted { background: var(--accent-soft); color: var(--accent); border-radius: 6px; display: inline-block; padding: 3px 10px; font-size: 13px; font-weight: 600; margin: 4px 0 2px; }
.finished { background: rgba(12,163,12,.12); color: #0ca30c; border-radius: 6px; display: inline-block; padding: 3px 10px; font-size: 13px; font-weight: 600; margin: 4px 0 2px; }
footer { margin-top: 60px; border-top: 1px solid var(--line); padding-top: 14px; color: var(--ink-3); font-size: 12.5px; }
"""

FONTS = '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;600&display=swap">'

# Without JavaScript nothing can be plotted anyway, so fall back to every view's text and
# tables at once rather than a page that looks empty.
NOSCRIPT = """
<noscript>
<style>.panel, .opt { display: block !important; } .fig, .toolbar { display: none !important; }</style>
<p class="section-note">JavaScript is off, so the charts and the view switcher are
unavailable — every section's text and tables are shown one after another instead.</p>
</noscript>
"""

# The page holds every view at once, so plotting them all up front would cost seconds and a
# lot of memory. Figures are kept as specs and drawn only when their view is on screen, in
# whichever theme the viewer is using; a theme flip redraws what is visible and leaves the
# rest to redraw when it is next shown.
RUNTIME_JS = """
<script>
(function () {
  var FIGS = JSON.parse(document.getElementById("figdata").textContent);

  function isDark() {
    var explicit = document.documentElement.getAttribute("data-theme");
    if (explicit) return explicit === "dark";
    return window.matchMedia("(prefers-color-scheme: dark)").matches;
  }

  function draw(el) {
    var spec = FIGS[el.dataset.fig];
    if (!spec || !window.Plotly) return;
    var want = isDark() ? "dark" : "light";
    if (el.dataset.drawn === want) {
      try { Plotly.Plots.resize(el); } catch (e) {}
      return;
    }
    // Marked drawn either way: a chart that cannot plot must not retry on every switch.
    try {
      Plotly.react(el, spec[want].data, spec[want].layout,
                   { displayModeBar: false, responsive: true });
    } catch (e) {}
    el.dataset.drawn = want;
    el.style.minHeight = "";
  }

  // "On screen" is decided by the panel/option classes rather than by layout
  // (offsetParent), so it holds before first paint and stays checkable headlessly.
  function isShown(el) {
    for (var n = el; n && n !== document.body; n = n.parentElement) {
      if ((n.classList.contains("panel") || n.classList.contains("opt"))
          && !n.classList.contains("on")) return false;
    }
    return true;
  }

  function drawVisible() {
    document.querySelectorAll(".fig").forEach(function (el) {
      if (isShown(el)) draw(el);
    });
  }

  var periodSelect = document.getElementById("period-select");
  // With only one reporting period there is no picker to read a value from, but the
  // period-scoped panels still carry their data-period -- default to that one instead of
  // "", or nothing with a data-period would ever match and every such panel would stay
  // hidden despite being fully built into the page.
  var firstPeriodEl = document.querySelector("[data-period]");
  var state = {
    tab: "overview",
    period: periodSelect ? periodSelect.value : (firstPeriodEl ? firstPeriodEl.dataset.period : ""),
  };

  function apply() {
    document.querySelectorAll(".tab").forEach(function (b) {
      var on = b.dataset.tab === state.tab;
      b.classList.toggle("on", on);
      b.setAttribute("aria-selected", on ? "true" : "false");
    });
    document.querySelectorAll("section.panel").forEach(function (p) {
      p.classList.toggle("on", p.dataset.tab === state.tab
                               && (!p.dataset.period || p.dataset.period === state.period));
    });
    // Special projects and Tools are not period-scoped: hide the period picker there
    // rather than leaving a control that does nothing.
    var picker = document.querySelector(".toolbar .picker");
    if (picker) {
      picker.style.visibility = document.querySelector(
        'section.panel[data-tab="' + state.tab + '"][data-period]') ? "" : "hidden";
    }
    drawVisible();
  }

  document.querySelectorAll(".tab").forEach(function (b) {
    b.addEventListener("click", function () {
      state.tab = b.dataset.tab;
      try { history.replaceState(null, "", "#" + state.tab); } catch (e) {}
      apply();
    });
  });

  if (periodSelect) {
    periodSelect.addEventListener("change", function () {
      state.period = periodSelect.value;
      apply();
    });
  }

  // Week / month / project pickers: each .switch owns its select and its own .opt views.
  document.querySelectorAll(".switch").forEach(function (sw) {
    var sel = sw.querySelector("select");
    if (!sel) return;
    function show() {
      sw.querySelectorAll(":scope > .opt").forEach(function (o) {
        o.classList.toggle("on", o.dataset.value === sel.value);
      });
      drawVisible();
    }
    sel.addEventListener("change", show);
    show();
  });

  // Keep the old anchor links (#week, #tools, ...) working as "open that tab".
  var fromHash = (location.hash || "").replace("#", "");
  if (fromHash && document.querySelector('.tab[data-tab="' + fromHash + '"]')) {
    state.tab = fromHash;
  }

  var mq = window.matchMedia("(prefers-color-scheme: dark)");
  if (mq.addEventListener) mq.addEventListener("change", function () { setTimeout(drawVisible, 60); });
  new MutationObserver(function () { setTimeout(drawVisible, 60); })
    .observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });

  apply();
})();
</script>
"""

TABS = [
    ("overview", "Overview"),
    ("week", "Week"),
    ("month", "Month"),
    ("year", "Year"),
    ("turnaround", "Turnaround"),
    ("special", "Special projects"),
    ("tools", "Tools &amp; AI Skills"),
]

# fid -> {"light": {...}, "dark": {...}}, serialised into the page once at the end.
FIGS = {}


def esc(value):
    v = "" if value is None or (isinstance(value, float) and pd.isna(value)) else str(value)
    return html_mod.escape("" if v in ("nan", "None") else v)


def fig(build_fig):
    """Register one figure in both themes and return the placeholder the runtime draws into.
    `build_fig(dark)` must return a freshly built plotly figure for that theme (kpi_charts
    globals are switched around the call)."""
    fid = "f%d" % (len(FIGS) + 1)
    spec, height = {}, 450
    for dark, key in ((False, "light"), (True, "dark")):
        kc.set_theme(dark=dark)
        built = build_fig(dark)
        built.update_layout(autosize=True, width=None)
        payload = built.to_plotly_json()
        layout = payload.get("layout", {}) or {}
        height = layout.get("height") or height
        spec[key] = {"data": payload.get("data", []), "layout": layout}
    kc.set_theme(dark=False)
    FIGS[fid] = spec
    return f'<div class="chart fig" data-fig="{fid}" style="min-height:{int(height)}px"></div>'


def tile(label, value, sub=""):
    sub_html = f'<div class="sub">{esc(sub)}</div>' if sub else ""
    return (f'<div class="tile"><div class="label">{esc(label)}</div>'
            f'<div class="value">{esc(value)}</div>{sub_html}</div>')


def tiles(*items):
    return '<div class="tiles">' + "".join(items) + "</div>"


def note(inner_html):
    return f'<p class="section-note">{inner_html}</p>'


def panel(tab, body, period=None):
    period_attr = f' data-period="{esc(period)}"' if period else ""
    return f'<section class="panel" data-tab="{esc(tab)}"{period_attr}>{body}</section>'


def switch(group, label, options, build_body):
    """A picker plus one pre-built view per option: `options` is a list of
    (value, label, is_default) and `build_body(value)` returns that option's HTML."""
    opts = "".join(
        f'<option value="{esc(value)}"{" selected" if default else ""}>{esc(text)}</option>'
        for value, text, default in options
    )
    bodies = "".join(f'<div class="opt" data-value="{esc(value)}">{build_body(value)}</div>'
                     for value, _, _ in options)
    return (f'<div class="switch" data-group="{esc(group)}">'
            f'<div class="picker"><label for="sel-{esc(group)}">{esc(label)}</label>'
            f'<select id="sel-{esc(group)}">{opts}</select></div>{bodies}</div>')


# ================================================================================================
# Period-dependent views: Overview / Week / Month / Year / Turnaround for one reporting period
# ================================================================================================

def period_panels(pkey, period, df, raw_df, category_order, cat_colors, task_category, today):
    """Every panel belonging to one reporting period, keyed so the period picker can swap
    the whole set at once (as choosing another period in the dashboard would)."""
    df_period = kd.filter_to_period(df, period)
    projects = kd.load_projects(period["file"], period["sheet"])
    # Real, tracker-registered projects -- for "Projects touched" tiles (see the same set
    # in KPI_Report.py). A positive match against the tracker, not a blocklist of known
    # non-project buckets, so a mistagged/orphan tag doesn't get counted either.
    real_project_tags = set(projects["Project tag"].astype(str).str.strip())
    meetings = kd.load_meetings(period["file"], period["meetings_sheet"])
    project_desc = (projects.set_index("Project tag")["Short Description"]
                    if "Short Description" in projects.columns else None)
    glance = kd.year_at_a_glance(projects, meetings, df_period)
    df_period_labeled, months_present = kd.label_period_months(df_period)
    empty_note = note("No time-log entries for this reporting period — the project tracker's "
                      "own data (Year and Turnaround) is unaffected.")
    out = []

    # ---- Overview ------------------------------------------------------------------------
    # The reporting year runs Oct->Oct, so every count on this page is "this window", not a
    # calendar year -- spelled out here and again on the Turnaround tiles.
    window = (f'{period["start"].strftime("%d %b %Y")} → '
              f'{(period["end"] - pd.Timedelta(1, "D")).strftime("%d %b %Y")}')
    out.append(panel("overview", (
        f'<h2>Year at a glance — {esc(period["label"])}</h2>'
        + note(f'The whole reporting year, <strong>{esc(window)}</strong>. Use the tabs above '
               'for the week-by-week detail, the project turnaround, the special projects and '
               'the tools inventory.')
        + tiles(
            tile("Projects", glance["projects_total"],
                 f"{glance['projects_active']} active · {glance['projects_concluded']} concluded"),
            tile("Consultation meetings", glance["meetings_total"]),
            tile("Research groups", glance["groups_total"],
                 f"{glance['groups_with_projects']} with projects"),
        )
    ), period=pkey))

    # ---- Week ----------------------------------------------------------------------------
    week_starts = sorted(df_period["_week_sort"].unique()) if len(df_period) else []
    if not week_starts:
        out.append(panel("week", "<h2>Week</h2>" + empty_note, period=pkey))
    else:
        week_pairs = [(start, kd.format_week_label(start, start + pd.Timedelta(6, "D")))
                      for start in week_starts]
        default_start = kd.default_week(week_pairs, today)
        labels = {start: label for start, label in week_pairs}

        def week_body(value, _labels=labels):
            start = pd.Timestamp(value)
            label = _labels[start]
            week_df = df[df["_week_sort"] == start]
            timesheet_col = raw_df.loc[df.index[df["_week_sort"] == start],
                                    "Timesheet updated"].astype(str).str.strip()
            n_tracked = int(timesheet_col.isin(["Yes", "No"]).sum())
            n_updated = int((timesheet_col == "Yes").sum())
            rows = []
            for _, r in week_df.sort_values("Hours (exact)", ascending=False).iterrows():
                raw_r = raw_df.loc[r.name]
                timesheet = str(raw_r.get("Timesheet updated", "") or "").strip()
                timesheet_html = (f'<span class="pill {"yes" if timesheet == "Yes" else "no"}">{esc(timesheet)}</span>'
                               if timesheet in ("Yes", "No") else "")
                rows.append(f"<tr><td>{esc(r['Project'])}</td><td>{esc(r['Category'])}</td>"
                            f"<td>{esc(r['Major task name (chart)'])}</td>"
                            f"<td class=\"num\">{esc(kd.format_hm(r['Hours (exact)']))}</td>"
                            f"<td>{timesheet_html}</td><td>{esc(raw_r.get('Notes', ''))}</td></tr>")
            return (
                tiles(
                    tile("Hours logged", kd.format_hm(week_df["Hours (exact)"].sum())),
                    tile("Projects touched", int(week_df.loc[week_df["Project"].isin(real_project_tags), "Project"].nunique())),
                    tile("Entries", int(len(week_df))),
                    tile("Timesheet updated", f"{n_updated}/{n_tracked}" if n_tracked else "-",
                         "entries marked Yes in the time log"),
                )
                + '<div class="grid-2">'
                + fig(lambda d, _w=week_df, _l=label: kc.fig_week_hours_by_project(_w, _l, project_desc))
                + fig(lambda d, _w=week_df, _l=label: kc.fig_category_donut(
                    kc.category_hours_frame(_w, category_order, cat_colors(d)),
                    f"Category share — week of {_l}", "No hours logged yet"))
                + "</div>"
                + fig(lambda d, _w=week_df, _l=label: kc.fig_hours_by_project_task(
                    _w, _l, task_category, category_order, cat_colors(d)))
                + f'<h3>Time log — week of {esc(label)}</h3>'
                '<div class="tablewrap"><table><thead><tr><th>Project</th><th>Category</th>'
                '<th>Major task</th><th>Time</th><th>Timesheet</th><th>Notes</th></tr></thead>'
                f'<tbody>{"".join(rows)}</tbody></table></div>'
            )

        options = [(start.strftime("%Y-%m-%d"), label, start == default_start)
                   for start, label in week_pairs]
        out.append(panel("week", "<h2>Week</h2>" + switch(f"week-{pkey}", "Week", options, week_body),
                         period=pkey))

    # ---- Month ---------------------------------------------------------------------------
    if not months_present:
        out.append(panel("month", "<h2>Month</h2>" + empty_note, period=pkey))
    else:
        default_m = kd.default_month(months_present, today.strftime("%B %Y"))

        def month_body(month):
            month_df = df_period_labeled[df_period_labeled["Month"] == month]
            return (
                tiles(
                    tile("Hours logged", kd.format_hm(month_df["Hours (exact)"].sum())),
                    tile("Projects touched", int(month_df.loc[month_df["Project"].isin(real_project_tags), "Project"].nunique())),
                    tile("Entries", int(len(month_df))),
                    tile("Weeks with entries", int(month_df["_week_sort"].nunique())),
                )
                + fig(lambda d, _m=month_df, _l=month: kc.fig_major_task_share_by_category(
                    _m, _l, category_order, cat_colors(d)))
                + '<div class="grid-2">'
                + fig(lambda d, _m=month_df, _l=month: kc.fig_category_donut(
                    kc.category_hours_frame(_m, category_order, cat_colors(d)),
                    f"Category share — {_l}", "No hours logged yet"))
                + fig(lambda d, _m=month_df, _l=month: kc.fig_category_weekly_distribution(
                    _m, category_order, cat_colors(d),
                    title=f"Category distribution by week — {_l}"))
                + "</div>"
            )

        options = [(m, m, m == default_m) for m in months_present]
        out.append(panel("month", "<h2>Month</h2>" + switch(f"month-{pkey}", "Month", options, month_body),
                         period=pkey))

    # ---- Year ----------------------------------------------------------------------------
    period_months = pd.period_range(f"{period['start'].year}-01", f"{period['end'].year}-01", freq="M")
    truncate_at = today.to_period("M") if period["start"] <= today < period["end"] else None
    year_body = [f'<h2>Year — {esc(period["label"])}</h2>',
                 fig(lambda d: kc.fig_received_vs_finished(
                     projects, period_months, period["start"], truncate_at))]
    gap_stats = kd.closing_gap_summary(projects)
    if gap_stats["n_finished"]:
        bits = [f"<b>{gap_stats['n_finished']}</b> closed this period"]
        if gap_stats["n_same_day"]:
            bits.append(f"{gap_stats['n_same_day']} the same day the final report went out")
        if gap_stats["n_delayed"]:
            bits.append(f"{gap_stats['n_delayed']} took a median {esc(kd.format_days(gap_stats['median_gap_days']))} "
                         "longer to formally close after the report was delivered")
        year_body.append(note(" &middot; ".join(bits) + " &mdash; hover a bar above for which."))
    if len(df_period):
        year_body.append(fig(lambda d: kc.fig_category_share_stacked(
            df_period, f"Category share of total hours — {period['label']}",
            category_order, cat_colors(d))))
        year_body.append(fig(lambda d: kc.fig_category_hours_by_month(
            df_period_labeled, months_present, category_order, cat_colors(d))))
    out.append(panel("year", "".join(year_body), period=pkey))

    # ---- Turnaround ------------------------------------------------------------------------
    # The per-project journey and the median turnaround figures -- worth sharing. The
    # dashboard's "Needs attention" list is deliberately NOT exported: stalling-project
    # tracking is internal working state, not something to hand to a reader.
    # pause_notes has to go INTO lead_time_table, not just to the chart afterwards: that's
    # where each paused week picks up its note and its two forgive flags, and where the
    # forgiven days come out of working_days_counted / total_days_counted. Building the
    # table without it left the snapshot's medians un-forgiven and its pause list unnamed,
    # while the live dashboard (which does pass it) showed something different.
    pause_notes = kd.load_pause_notes()
    lead_df = kd.lead_time_table(projects, df_period, period_end=period["end"],
                                 pause_notes=pause_notes)
    stats = kd.lead_time_summary(lead_df)
    cov = kd.lead_time_coverage(projects, lead_df, stats)
    effort = kd.lead_time_effort(lead_df)
    turn = ['<h2>Turnaround</h2>']
    turn.append(note(
        f'Everything below covers the whole <strong>{esc(period["label"])}</strong> reporting '
        f'year — <strong>{esc(window)}</strong> — not the week or month chosen elsewhere.'))
    turn.append(note(
        '<strong>Waiting</strong> = first user meeting until the tracker\'s work start; '
        '<strong>working</strong> = from there until the final report (or today while '
        'running). The <strong>◆ diamond</strong> marks when work <em>really</em> '
        'began per the time log — the first week with logged hours, which can sit before or '
        'after the tracker\'s date. A faded, hatched waiting span is an <strong>inherited '
        'project</strong>: that time ran under its previous owner; a blue hatched row is an '
        '<strong>internal project</strong>, shown for context but left out of the medians '
        '(its Closing Day ends the working stage, since there is no report to send). '
        'Consulting blocks are not shown here at all — a standing advisory thread has no '
        'turnaround to measure. Gray segments are <strong>pauses</strong>: '
        f'{kd.PAUSE_MIN_WEEKS}+ consecutive weeks with no hours logged (hover one for the '
        'reason, when noted). Tiles are medians over projects with usable dates; delivery '
        'medians count delivered projects only.'))
    turn.append(tiles(
        tile("Typical wait to start", kd.format_days(stats["median_waiting"])),
        tile("Projects measured — whole year", f"{stats['n_shown_delivered']}/{stats['n_shown']}",
             f"delivered / on the chart · {window}"),
        tile("Consulting", str(cov["consulting"]), "no turnaround to measure"),
    ))
    turn.append(tiles(
        tile("Typical total turnaround", kd.format_days(stats["median_total"]),
             "first contact → final report"),
        tile("Typical time to deliver", kd.format_days(stats["median_working"]),
             "the real workload time"),
        tile("Timesheet tracking", kd.format_days(effort["median_timesheet"]),
             "Register Project → Closing Day"),
    ))
    turn.append(note('<strong>Typical total turnaround by project size</strong> — what to '
                     'expect for the job in front of you, rather than one median across jobs '
                     'of every size.'))
    turn.append(tiles(*[tile(f"{b['label']} ({b['range_label']})", kd.format_days(b["median_days"]),
                             f"{b['n']} project" + ("" if b["n"] == 1 else "s"))
                        for b in kd.turnaround_by_size(lead_df)]))
    turn.append(note(html_mod.escape(kd.lead_time_coverage_note(cov)).replace("**", "")))
    turn.append(fig(lambda d: kc.fig_lead_time_stages(
        lead_df, f"Project turnaround — {period['label']}", pause_notes=pause_notes,
        period_start=period["start"])))
    def week_bits(w):
        """Note + forgiveness for one week of a pause, as display fragments -- each week is
        forgiven independently (see kd.gap_weeks), so a multi-week pause can read differently
        week to week."""
        bits = []
        if w.get("note"):
            bits.append(esc(w["note"]))
        if w.get("forgiven_working") and w.get("forgiven_total"):
            bits.append("forgiven (working + total)")
        elif w.get("forgiven_working"):
            bits.append("forgiven (working time)")
        elif w.get("forgiven_total"):
            bits.append("forgiven (total turnaround)")
        return bits

    pause_lines = []
    for _, r in (lead_df.iterrows() if len(lead_df) else []):
        for g in (r.get("gaps") or []):
            weeks_detail = g.get("weeks_detail") or [g]
            header = (f"<strong>{esc(r['Project tag'])}</strong> — paused {g['weeks']} week"
                      f"{'' if g['weeks'] == 1 else 's'} ({g['start'].strftime('%d %b')} → "
                      f"{g['end'].strftime('%d %b %Y')})")
            # Every week the same note/forgiveness (the common case, including every 1-week
            # pause) reads as one line; a week that differs from the rest gets its own
            # sub-list so the split is visible without listing every week separately by default.
            signature = {(w.get("note", ""), w.get("forgiven_working"), w.get("forgiven_total"))
                         for w in weeks_detail}
            if len(signature) <= 1:
                bits = week_bits(weeks_detail[0]) if weeks_detail else []
                pause_lines.append(f"<li>{header}" + (f": <em>{'; '.join(bits)}</em>" if bits else "") + "</li>")
            else:
                sub_items = "".join(
                    f"<li>Week of {w['start'].strftime('%d %b %Y')}"
                    + (f": <em>{'; '.join(week_bits(w))}</em>" if week_bits(w) else "") + "</li>"
                    for w in weeks_detail
                )
                pause_lines.append(f"<li>{header}<ul>{sub_items}</ul></li>")
    if pause_lines:
        turn.append('<h3>Pauses</h3><ul class="section-note">' + "".join(pause_lines) + "</ul>")
    out.append(panel("turnaround", "".join(turn), period=pkey))

    return out


# ================================================================================================
# Period-independent views: Special projects, Tools
# ================================================================================================

def special_panel():
    try:
        goals_df = kd.load_goals()
    except (FileNotFoundError, PermissionError):
        goals_df = pd.DataFrame()
    all_tasks = kd.load_project_tasks()
    kd.sync_tasks_excel(all_tasks)  # catch the Excel mirror up if editing left it behind
    body = ['<h2>Special projects</h2>']
    if not len(goals_df):
        body.append(note("No special projects rated yet."))
        return panel("special", "".join(body))

    def project_card(row, with_timeline=False):
        name = str(row["Project"]).strip()
        tasks = all_tasks.get(name, [])
        stars = " · ".join(f"{lbl} {'★' * int(row[lbl])}"
                           for lbl in ["Development", "Impact", "Maintenance", "Visibility"]
                           if pd.notna(row.get(lbl)))
        desc_items = "".join(f"<li>{esc(p.strip())}</li>"
                             for p in str(row.get("Description") or "").split(";") if p.strip())
        pred = kd.predicted_end(tasks)
        done_n = sum(1 for t in tasks if t.get("done"))
        task_items = []
        for t in tasks:
            start, due = kd.task_span(t)
            indent = "&nbsp;" * 4 * int(t.get("level", 0))
            mark = "✅" if t.get("done") else "⬜"
            cls = ' class="done-task"' if t.get("done") else ""
            if start and due:
                when = f'{start.strftime("%d %b")} → {due.strftime("%d %b %Y")}'
            elif due:
                when = due.strftime("%d %b %Y")
            elif start:
                when = f'from {start.strftime("%d %b %Y")}'
            else:
                when = ""
            due_html = f'<span class="due">{when}</span>' if when else ""
            task_items.append(f"<li>{indent}{mark} <span{cls}>"
                              f"{esc(t.get('text') or '(untitled task)')}</span>{due_html}</li>")
        # A finished project shows what it finished *on* instead of a predicted completion:
        # the prediction is about work still to come, and there isn't any.
        if row.get("_finished"):
            when = row.get("_completed")
            pred_html = ('<div class="finished">✅ Finished'
                         + (f' — {when.strftime("%d %b %Y")}' if when else "") + "</div>")
        else:
            pred_html = (f'<div class="predicted">📅 Predicted completion: {pred.strftime("%d %b %Y")}</div>'
                         if pred else "")
        progress = f'<div class="meta">{done_n}/{len(tasks)} tasks done</div>' if tasks else ""
        tick = "✅ " if row.get("_finished") else ""
        card = (f'<div class="card"><h4>{tick}{esc(name)}</h4>'
                f'<div class="meta">{esc(row.get("Goal"))}<br>{stars}</div>'
                f"<ul>{desc_items}</ul>{pred_html}{progress}"
                f'<ul class="tasks">{"".join(task_items)}</ul></div>')
        # The timeline is returned alongside the card, never inside the card grid: a Gantt
        # squeezed into a 320px column is unreadable.
        timeline = ""
        if with_timeline and any(kd.task_due_date(t) or kd.task_start_date(t) for t in tasks):
            timeline = fig(lambda d, _t=tasks, _n=name: kc.fig_task_timeline(_t, _n))
        return card, timeline

    body.append(fig(lambda d: kc.fig_goals_at_a_glance(goals_df)))
    body.append(note("The shaded quadrants read effort against impact: "
                     + " · ".join(f"<b>{label}</b> ({meaning})"
                                  for label, meaning, _qx, _qy, _tint in kc.GOAL_QUADRANTS)
                     + "."))
    names = sorted(goals_df["Project"].astype(str).str.strip().unique())
    body.append(fig(lambda d: kc.fig_all_projects_timeline(all_tasks, names)))

    rows_by_name = {str(r["Project"]).strip(): r for _, r in goals_df.iterrows()}

    def body_for(value):
        if value == "__all__":
            return ('<div class="cards">'
                    + "".join(project_card(rows_by_name[n])[0] for n in names if n in rows_by_name)
                    + "</div>")
        card, timeline = project_card(rows_by_name[value], with_timeline=True)
        return f'<div class="cards single">{card}</div>{timeline}'

    options = ([("__all__", "All projects", True)]
               + [(n, n, False) for n in names if n in rows_by_name])
    body.append(switch("special-project", "Project", options, body_for))
    return panel("special", "".join(body))


def tools_panel(tl_palette):
    try:
        tools_df = kd.load_tools()
    except (FileNotFoundError, PermissionError):
        tools_df = pd.DataFrame(columns=kd.TOOLS_COLS)
    body = ['<h2>Tools &amp; AI Skills</h2>']
    if not len(tools_df):
        body.append(note("No tools inventoried yet (or tools.xlsx was locked while exporting)."))
        return panel("tools", "".join(body))

    # A deprecated tool is still on record, but no longer counted as one of "what's built
    # and in use" -- same split as the live Tools page (3_Tools.py).
    is_deprecated = tools_df["Status"].astype(str).str.strip() == "Deprecated"
    active_tools = tools_df[~is_deprecated]
    deprecated_tools = tools_df[is_deprecated]

    n_ai = int(active_tools["Type of tool"].astype(str).str.contains("AI Skill", case=False, na=False).sum())
    body.append(tiles(
        tile("Tools built", len(active_tools)),
        tile("AI Skills", n_ai),
        tile("Tool types", int(active_tools["Type of tool"].astype(str).str.strip()
                               .replace("", pd.NA).nunique(dropna=True))),
    ))
    body.append('<div class="grid-2">'
                + fig(lambda d: kc.fig_tools_counts(active_tools["Type of tool"], "By type of tool",
                                                    tl_palette(d)[0], names=active_tools["Name"]))
                + fig(lambda d: kc.fig_tools_counts(active_tools["Use"], "By use",
                                                    tl_palette(d)[2], names=active_tools["Name"]))
                + "</div>")
    body.append(fig(lambda d: kc.fig_tools_counts(active_tools["Project Origin"], "By project origin",
                                                  tl_palette(d)[1], names=active_tools["Name"])))
    cards = []
    for _, row in active_tools.iterrows():
        meta = " · ".join(p for p in (
            esc(row["Type of tool"]),
            f"built in {esc(row['Built in'])}" if esc(row["Built in"]) else "",
            f"use: {esc(row['Use'])}" if esc(row["Use"]) else "",
            f"origin: {esc(row['Project Origin'])}" if esc(row["Project Origin"]) else "",
        ) if p)
        desc_items = "".join(f"<li>{esc(p.strip())}</li>"
                             for p in str(row.get("Description") or "").split(";") if p.strip())
        lim = f'<p class="minus">− {esc(row["Limitations"])}</p>' if esc(row["Limitations"]) else ""
        gain = f'<p class="gain">→ {esc(row["Future gain"])}</p>' if esc(row["Future gain"]) else ""
        cards.append(f'<div class="card"><h4>{esc(row["Name"])}</h4><div class="meta">{meta}</div>'
                     f"<ul>{desc_items}</ul>{lim}{gain}</div>")
    body.append(f'<div class="cards">{"".join(cards)}</div>')

    if len(deprecated_tools):
        body.append(note(f"<strong>Deprecated ({len(deprecated_tools)})</strong> — no longer the thing "
                         "to reach for, for whatever reason, kept here for the record rather "
                         "than deleted."))
        dep_cards = []
        for _, row in deprecated_tools.iterrows():
            reason = esc(row["Why deprecated"])
            reason_html = f'<p class="meta">🗃️ Deprecated — {reason}</p>' if reason else '<p class="meta">🗃️ Deprecated</p>'
            meta = " · ".join(p for p in (
                esc(row["Type of tool"]),
                f"built in {esc(row['Built in'])}" if esc(row["Built in"]) else "",
                f"use: {esc(row['Use'])}" if esc(row["Use"]) else "",
                f"origin: {esc(row['Project Origin'])}" if esc(row["Project Origin"]) else "",
            ) if p)
            desc_items = "".join(f"<li>{esc(p.strip())}</li>"
                                 for p in str(row.get("Description") or "").split(";") if p.strip())
            dep_cards.append(f'<div class="card"><h4>{esc(row["Name"])}</h4>{reason_html}'
                             f'<div class="meta">{meta}</div><ul>{desc_items}</ul></div>')
        body.append(f'<div class="cards" style="opacity:0.55">{"".join(dep_cards)}</div>')
    return panel("tools", "".join(body))


def build():
    df, category_order, colors_light, task_category, raw_df = kd.load_timelog(dark=False)
    _, _, colors_dark, _, _ = kd.load_timelog(dark=True)
    cat_colors = lambda dark: colors_dark if dark else colors_light
    tl_palette = lambda dark: kd.TL_PALETTE_DARK if dark else kd.TL_PALETTE

    today = pd.Timestamp.now().normalize()
    periods = kd.discover_periods()
    generated = datetime.datetime.now().strftime("%d %b %Y, %H:%M")

    panels, period_options = [], []
    for i, period in enumerate(periods):
        pkey = f"p{i}"
        period_options.append(f'<option value="{pkey}"{" selected" if i == 0 else ""}>'
                              f'{esc(period["label"])}</option>')
        panels.extend(period_panels(pkey, period, df, raw_df, category_order, cat_colors,
                                    task_category, today))
    panels.append(special_panel())
    panels.append(tools_panel(tl_palette))

    tab_buttons = "".join(
        f'<button class="tab" type="button" role="tab" data-tab="{key}" '
        f'aria-selected="false">{label}</button>' for key, label in TABS)
    period_picker = (f'<div class="picker"><label for="period-select">Period</label>'
                     f'<select id="period-select">{"".join(period_options)}</select></div>'
                     if len(periods) > 1 else "")

    head = (f'<p class="eyebrow">Read-only snapshot</p>'
            f'<h1>KPI Report</h1>'
            f'<p class="stamp">Generated {generated} from the live tracking files. Browse it like '
            f'the dashboard — switch period, tab, week, month or project and the page responds '
            f'instantly — but the numbers are frozen at that moment. To edit anything, or to see '
            f'data logged since, use the Streamlit dashboard.</p>')

    figdata = json.dumps(FIGS, cls=plotly.utils.PlotlyJSONEncoder).replace("</", "<\\/")
    body = ('<div class="wrap">' + head
            + f'<div class="toolbar"><div class="tabs" role="tablist">{tab_buttons}</div>{period_picker}</div>'
            + NOSCRIPT + "".join(panels)
            + f"<footer>Static snapshot generated {generated} · "
            "KPI dashboard (demo)</footer></div>"
            + f'<script id="figdata" type="application/json">{figdata}</script>')

    plotly_js = f"<script>{get_plotlyjs()}</script>"

    SHARE_DIR.mkdir(exist_ok=True)
    standalone = (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
                  f'<meta name="viewport" content="width=device-width, initial-scale=1">'
                  f"<title>KPI Report</title>{FONTS}<style>{CSS}</style>{plotly_js}</head>"
                  f"<body>{body}{RUNTIME_JS}</body></html>")
    (SHARE_DIR / "KPI_Report_snapshot.html").write_text(standalone, encoding="utf-8")

    artifact = f"<title>KPI Report</title>{FONTS}<style>{CSS}</style>{plotly_js}{body}{RUNTIME_JS}"
    (SHARE_DIR / "_artifact_snapshot.html").write_text(artifact, encoding="utf-8")

    for name in ("KPI_Report_snapshot.html", "_artifact_snapshot.html"):
        size = (SHARE_DIR / name).stat().st_size / 1e6
        print(f"wrote {SHARE_DIR / name}  ({size:.1f} MB, {len(FIGS)} charts)")


if __name__ == "__main__":
    import sys

    try:
        build()
    except PermissionError as exc:
        # A source file is open in Excel / locked by OneDrive. Exit 2 (not a crash) so a
        # scheduled run can skip publishing and simply try again next time, rather than
        # pushing a half-built page.
        print(f"SKIPPED: a data file is locked ({exc.filename or exc}). "
              "Close it in Excel and run again.", file=sys.stderr)
        sys.exit(2)
