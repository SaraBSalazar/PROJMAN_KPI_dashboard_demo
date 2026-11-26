"""Plotly figure builders for the KPI dashboard — ported from the analysis notebook,
parameterized so each chart takes already-filtered data instead of reading module globals."""

import math
import textwrap

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from kpi_data import (
    BASELINE, FINISHED_COLOR, GAIN_GROUPS, GAIN_STATE_LABELS, GRID, INK, MUTED,
    RECEIVED_COLOR, TL_BASELINE, TL_CRITICAL, TL_GOOD, TL_GRID, TL_INK_MUTED, TL_INK_PRIMARY,
    TL_INK_SECONDARY, TL_PALETTE, TL_PALETTE_DARK, TL_SURFACE, WORKLOAD_COLOR,
    _name_variants, effective_received_date, effective_workload_start, format_hm,
    project_hours_with_source, project_lookup_label,
)

# --- Light/dark theming ---------------------------------------------------------------------
# Every chart function below reads these color names as plain module globals (not frozen at
# def time), so reassigning them here -- once, before building any charts on a page -- is
# enough to re-theme every chart that follows, with no per-chart changes needed.
_LIGHT_THEME = dict(
    INK=INK, MUTED=MUTED, GRID=GRID, BASELINE=BASELINE,
    TL_INK_PRIMARY=TL_INK_PRIMARY, TL_INK_SECONDARY=TL_INK_SECONDARY, TL_INK_MUTED=TL_INK_MUTED,
    TL_GRID=TL_GRID, TL_BASELINE=TL_BASELINE, TL_SURFACE=TL_SURFACE,
)
_DARK_THEME = dict(
    INK="#e8e8e6", MUTED="#a3a39e", GRID="#3c3b38", BASELINE="#8a8a86",
    TL_INK_PRIMARY="#f2f1ee", TL_INK_SECONDARY="#d0cec7", TL_INK_MUTED="#938f87",
    TL_GRID="#3c3b38", TL_BASELINE="#59564f", TL_SURFACE="#20201e",
)


_DARK = False


def set_theme(dark):
    """Call once near the top of a page, before building any charts, so the whole page's
    charts match Streamlit's current light/dark setting."""
    global _DARK
    _DARK = bool(dark)
    globals().update(_DARK_THEME if dark else _LIGHT_THEME)


# Matches the UI font set in .streamlit/config.toml and loaded by kpi_style.inject() (the
# snapshot page loads the same face), so chart text and page text read as one system.
FONT_FAMILY = "IBM Plex Sans, Segoe UI, sans-serif"


def base_layout(title, width, height, bgcolor=None, font_color=None):
    bgcolor = bgcolor or TL_SURFACE
    font_color = font_color or TL_INK_PRIMARY
    return dict(
        title=dict(text=title, font=dict(family=FONT_FAMILY, color=font_color, size=17), x=0.01, xanchor="left"),
        font=dict(family=FONT_FAMILY, color=font_color, size=13),
        plot_bgcolor=bgcolor,
        paper_bgcolor=bgcolor,
        width=width,
        height=height,
        hoverlabel=dict(
            bgcolor=bgcolor, bordercolor=TL_BASELINE,
            font=dict(family=FONT_FAMILY, color=font_color, size=12),
        ),
    )


def _as_id_list(value):
    """Coerce whatever's in a lineage/served-ids cell into a real list of ids. kpi_data's
    loader (_parse_id_list) always hands back a list -- even a blank cell becomes [] -- so this
    is unreachable with today's data, but it's a cheap guard against a quietly different future:
    if a cell ever held a plain STRING instead (a DataFrame built or edited some other way), the
    naive `for id in cell` below would iterate it character by character and draw one node per
    LETTER -- visible nonsense with no error raised, not a crash. A bare string becomes a single-
    element list instead; anything else that isn't already a list/tuple is treated as empty
    rather than guessed at."""
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, (list, tuple)):
        return list(value)
    return []


def _empty(fig, text):
    fig.add_annotation(text=text, x=0.5, y=0.5, xref="paper", yref="paper",
                        showarrow=False, font=dict(color=TL_INK_MUTED, size=13))


def _rgba(hex_color, alpha):
    """"#1a6090" -> "rgba(26,96,144,0.09)" -- for wash/tint fills, where a solid hex would
    cover the marks sitting on top of it."""
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha})"


def _relative_luminance(hex_color):
    h = hex_color.lstrip("#")
    def lin(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(int(h[i:i + 2], 16)) for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast_ratio(hex_a, hex_b):
    la, lb = _relative_luminance(hex_a), _relative_luminance(hex_b)
    la, lb = max(la, lb), min(la, lb)
    return (la + 0.05) / (lb + 0.05)


def _label_on(bg_hex, light="#ffffff", dark="#141414"):
    """White or near-black -- whichever reads better as label text painted on a solid
    `bg_hex` fill (used for fig_gains_matrix's group header strips, where GAIN_GROUP_COLORS
    is a fixed palette some of whose members are mid-brightness, e.g. goldenrod for
    Capability, where white text undershoots WCAG AA and black does not)."""
    return light if _contrast_ratio(bg_hex, light) >= _contrast_ratio(bg_hex, dark) else dark


def _wrap_label(text, width=16):
    """Break a long y-axis category label onto multiple lines at word boundaries, so a
    long name (a group, a full meeting-outputs sentence) gets more legible space instead
    of overlapping its neighbors or getting clipped."""
    wrapped = textwrap.wrap(str(text), width=width)
    return "<br>".join(wrapped) if wrapped else str(text)


_TEXTPOS_SECTORS = [
    "middle right", "top right", "top center", "top left",
    "middle left", "bottom left", "bottom center", "bottom right",
]


def spread_overlapping(x, y, radius=None):
    """For points sharing the exact same (x, y), spread them evenly on a small circle
    around the true point so they don't fully overlap -- same technique as the goals
    bubble chart. Returns (jittered_x, jittered_y, textpositions); a point with a unique
    coordinate is returned unchanged with a plain "top center" label position. `radius`
    defaults to ~6% of the larger of the two data ranges, so it scales with whatever's
    being plotted instead of assuming a fixed axis range."""
    if radius is None:
        x_range = (x.max() - x.min()) or 1
        y_range = (y.max() - y.min()) or 1
        radius = 0.06 * max(x_range, y_range)

    coord = pd.Series(list(zip(x, y)), index=x.index)
    group_sizes = coord.map(coord.value_counts())
    group_rank = coord.groupby(coord).cumcount()
    multi = group_sizes > 1
    angle = 2 * math.pi * group_rank / group_sizes.where(multi, 1)
    jx = x + radius * angle.apply(math.cos) * multi
    jy = y + radius * angle.apply(math.sin) * multi

    def angle_to_textposition(rad):
        degrees = math.degrees(rad) % 360
        return _TEXTPOS_SECTORS[int(((degrees + 22.5) % 360) // 45)]

    textpos = [angle_to_textposition(a) if gs > 1 else "top center" for a, gs in zip(angle, group_sizes)]
    return jx, jy, textpos


# --- Week tab ----------------------------------------------------------------------------

def fig_week_hours_by_project(week_df, label, project_desc=None):
    project_totals = week_df.groupby("Project")["Hours (exact)"].sum().sort_values(ascending=True)
    fig = go.Figure()
    if len(project_totals):
        has_desc = project_desc is not None
        hovertext = [
            f"<b>{p}</b><br>{format_hm(v)}"
            + (f"<br>{project_desc[p]}" if has_desc and p in project_desc.index and pd.notna(project_desc[p]) else "")
            for p, v in project_totals.items()
        ]
        fig.add_trace(go.Bar(
            x=project_totals.values, y=project_totals.index, orientation="h",
            marker_color="#2a78d6", marker_line=dict(color=TL_SURFACE, width=1),
            text=[format_hm(v) for v in project_totals.values], textposition="outside",
            textfont=dict(color=TL_INK_SECONDARY, size=11), cliponaxis=False,
            hovertext=hovertext, hoverinfo="text",
        ))
        fig.update_xaxes(visible=True, range=[0, project_totals.max() * 1.3])
    else:
        _empty(fig, "No hours logged yet for this week")
        fig.update_xaxes(visible=True)
    fig.update_yaxes(showgrid=False)
    fig.update_layout(**base_layout(f"Hours per project — week of {label}", width=900, height=450,
                                     bgcolor=TL_SURFACE, font_color=TL_INK_PRIMARY))
    return fig


def fig_hours_by_project_task(week_df, label, task_category, category_order, category_colors):
    """Stacked horizontal bar, one row per project, segmented by major task. A task that's
    actually logged under more than one Category (e.g. "Tools" under both Projects and
    Projects-Development) draws as adjacent sub-segments -- one per Category it genuinely
    appears under for that project, each in
    that Category's own color -- rather than the whole task being forced into a single
    color via `task_category`'s one-task-one-category simplification (still used only to
    decide the left-to-right *order* tasks stack in, so related tasks still cluster)."""
    grouped = week_df.groupby(["Major task name (chart)", "Category", "Project"])["Hours (exact)"].sum()
    fig = go.Figure()
    if len(grouped):
        cat_rank = {c: i for i, c in enumerate(category_order)}
        task_totals = grouped.groupby("Major task name (chart)").sum()
        task_order = list(pd.DataFrame({
            "category_rank": task_category.reindex(task_totals.index).map(cat_rank),
            "hours": task_totals,
        }).sort_values(["category_rank", "hours"], ascending=[True, False]).index)

        project_order = grouped.groupby("Project").sum().sort_values(ascending=True).index

        shown_categories = set()
        for task in task_order:
            task_slice = grouped.loc[task]  # index: (Category, Project)
            cats_for_task = sorted(task_slice.index.get_level_values("Category").unique(),
                                    key=lambda c: cat_rank.get(c, len(category_order)))
            for category in cats_for_task:
                values = task_slice.xs(category, level="Category").reindex(project_order, fill_value=0)
                first_of_category = category not in shown_categories
                shown_categories.add(category)
                fig.add_trace(go.Bar(
                    x=values.values, y=values.index, orientation="h",
                    name=category, legendgroup=category, showlegend=first_of_category,
                    marker=dict(color=category_colors[category], line=dict(color=TL_SURFACE, width=1)),
                    text=[task if v > 0 else "" for v in values.values],
                    textposition="inside", insidetextanchor="middle", textfont=dict(color="white", size=9),
                    customdata=[format_hm(v) for v in values.values],
                    hovertemplate=f"<b>{task}</b> — {category}<br>" + "%{y}: %{customdata}<extra></extra>",
                ))
        fig.update_xaxes(visible=True)
    else:
        _empty(fig, "No hours logged yet for this week")
        fig.update_xaxes(visible=True)
    fig.update_yaxes(showgrid=False)
    fig.update_layout(
        **base_layout(f"Hours per project by major task — week of {label}", width=1000, height=500,
                      bgcolor=TL_SURFACE, font_color=TL_INK_PRIMARY),
        barmode="stack",
        legend=dict(title=dict(text="Category"), x=1.02, y=1, xanchor="left"),
    )
    return fig


def fig_category_donut(cat_hours, title, empty_text):
    """Shared by the week- and month-level 'category share of hours' donuts."""
    fig = go.Figure()
    if len(cat_hours):
        total = cat_hours["hours"].sum()
        pct = cat_hours["hours"] / total * 100
        fig.add_trace(go.Pie(
            labels=cat_hours.index, values=cat_hours["hours"],
            hole=0.55, sort=False, rotation=90, direction="clockwise",
            marker=dict(colors=list(cat_hours["color"]), line=dict(color=TL_SURFACE, width=2)),
            # Built by hand (textinfo="text") rather than "label+text", so a long category
            # name (e.g. "Meetings (non-project)") can be wrapped -- plotly has no wrap
            # option for the auto-rendered `label`.
            text=[f"{_wrap_label(cat, 14)} ({p:.0f}%)" for cat, p in zip(cat_hours.index, pct)],
            textinfo="text", textposition="outside",
            textfont=dict(color=TL_INK_SECONDARY, size=11),
            customdata=[format_hm(h) for h in cat_hours["hours"]],
            hovertemplate="<b>%{label}</b><br>%{customdata} (%{percent})<extra></extra>",
        ))
        fig.add_annotation(text=f"<b>{format_hm(total)}</b><br>total", x=0.5, y=0.5, xref="paper", yref="paper",
                            showarrow=False, font=dict(size=15, color=TL_INK_PRIMARY))
    else:
        _empty(fig, empty_text)
    fig.update_layout(**base_layout(title, width=460, height=460, bgcolor=TL_SURFACE, font_color=TL_INK_PRIMARY),
                       showlegend=False)
    return fig


def category_hours_frame(data_df, category_order, category_colors):
    hours = data_df.groupby("Category")["Hours (exact)"].sum().reindex(category_order).dropna()
    return pd.DataFrame({"hours": hours, "color": [category_colors[c] for c in hours.index]})


def fig_change_bars(delta, title, empty_text, height=420):
    fig = go.Figure()
    if len(delta):
        fig.add_trace(go.Bar(
            x=delta.values, y=delta.index, orientation="h",
            marker_color=[TL_GOOD if v >= 0 else TL_CRITICAL for v in delta.values],
            text=[format_hm(v, signed=True) for v in delta.values], textposition="outside",
            textfont=dict(color=TL_INK_SECONDARY, size=11), cliponaxis=False,
            hoverinfo="skip",
        ))
        fig.add_vline(x=0, line_color=TL_BASELINE, line_width=1)
        pad = delta.abs().max() * 0.4 or 1
        fig.update_xaxes(visible=False, range=[delta.min() - pad, delta.max() + pad])
    else:
        _empty(fig, empty_text)
        fig.update_xaxes(visible=False)
    fig.update_yaxes(showgrid=False)
    fig.update_layout(
        **base_layout(title, width=1000, height=height, bgcolor=TL_SURFACE, font_color=TL_INK_PRIMARY),
        margin=dict(l=20, r=80, t=60, b=40),
    )
    return fig


def change_delta(current_df, previous_df, group_col):
    current_totals = current_df.groupby(group_col)["Hours (exact)"].sum()
    previous_totals = previous_df.groupby(group_col)["Hours (exact)"].sum()
    all_keys = sorted(set(current_totals.index) | set(previous_totals.index))
    delta = current_totals.reindex(all_keys, fill_value=0) - previous_totals.reindex(all_keys, fill_value=0)
    return delta[delta != 0].sort_values()


# --- Month tab ----------------------------------------------------------------------------

def fig_major_task_share_by_category(month_df, label, category_order, category_colors):
    """Donut of hours by major task, each wedge colored by Category. Wedges are grouped
    into contiguous blocks by Category (all of one Category's wedges adjacent, in
    category_order), with the biggest task leading each block -- rather than ordering by
    task first, which would scatter a given Category's wedges across the ring wherever its
    tasks happened to rank. A task logged under more than one Category (see
    fig_hours_by_project_task) still draws as one wedge per Category it genuinely appears
    under, each its own correct color and its own share of the total."""
    grouped = month_df.groupby(["Major task name (chart)", "Category"])["Hours (exact)"].sum()
    fig = go.Figure()
    if len(grouped):
        cat_rank = {c: i for i, c in enumerate(category_order)}
        rows = grouped.reset_index(name="hours")
        rows["category_rank"] = rows["Category"].map(cat_rank).fillna(len(category_order))
        rows = rows.sort_values(["category_rank", "hours"], ascending=[True, False])
        tasks = rows["Major task name (chart)"].tolist()
        categories = rows["Category"].tolist()
        hours = rows["hours"].tolist()

        total = sum(hours)
        pct = [h / total * 100 for h in hours]
        wedge_colors = [category_colors[c] for c in categories]

        fig.add_trace(go.Pie(
            labels=tasks, values=hours,
            hole=0.55, sort=False, rotation=90, direction="clockwise",
            marker=dict(colors=wedge_colors, line=dict(color=TL_SURFACE, width=1.5)),
            text=[f"{_wrap_label(t, 14)} ({p:.0f}%)" for t, p in zip(tasks, pct)],
            textinfo="text", textposition="outside", textfont=dict(color=TL_INK_SECONDARY, size=10),
            showlegend=False,
            hovertext=[f"<b>{t}</b> — {c}<br>{format_hm(h)} ({p:.0f}%)"
                       for t, c, h, p in zip(tasks, categories, hours, pct)],
            hoverinfo="text",
        ))
        fig.add_annotation(text=f"<b>{format_hm(total)}</b><br>total", x=0.5, y=0.5, xref="paper", yref="paper",
                            showarrow=False, font=dict(size=15, color=TL_INK_PRIMARY))
    else:
        _empty(fig, f"No hours logged yet for {label}")

    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    fig.update_layout(
        **base_layout(f"Major-task share by category — {label}", width=780, height=560,
                      bgcolor=TL_SURFACE, font_color=TL_INK_PRIMARY),
        showlegend=False,
    )
    return fig


def fig_active_vs_concluded(active_projects, concluded_projects, label, project_desc=None):
    def _bullets(tags, empty):
        if not tags:
            return empty
        lines = []
        for t in tags:
            desc = project_desc.get(t) if project_desc is not None else None
            lines.append(f"• {t}" + (f" — {desc}" if pd.notna(desc) and desc else ""))
        return "<br>".join(lines)

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=["Active"], y=[len(active_projects)], marker_color=RECEIVED_COLOR, width=0.5,
        text=[len(active_projects)], textposition="outside", textfont=dict(color=INK, size=14), cliponaxis=False,
        hovertext=["<b>Active this month</b><br>" + _bullets(active_projects, "(none)")],
        hoverinfo="text",
    ))
    fig.add_trace(go.Bar(
        x=["Concluded"], y=[len(concluded_projects)], marker_color=FINISHED_COLOR, width=0.5,
        text=[len(concluded_projects)], textposition="outside", textfont=dict(color=INK, size=14), cliponaxis=False,
        hovertext=["<b>Concluded this month</b><br>" + _bullets(concluded_projects, "(none)")],
        hoverinfo="text",
    ))
    fig.update_yaxes(visible=False, range=[0, max(len(active_projects), len(concluded_projects)) * 1.3 or 1])
    fig.update_xaxes(showgrid=False)
    fig.update_layout(
        **base_layout(f"Active and concluded projects — {label}", width=480, height=420,
                      bgcolor=TL_SURFACE, font_color=TL_INK_PRIMARY),
        showlegend=False,
    )
    return fig


# --- Year tab: time-log trend charts -------------------------------------------------------

def fig_category_share_stacked(df_period, title, category_order, category_colors):
    """100%-wide single stacked bar, one segment per Category. No legend -- instead, every
    segment keeps its own label: big enough to hold "Category (NN%)" draws it inside,
    anything narrower draws the same text just outside its own slice (plotly positions
    "outside" text relative to each trace's own segment, not the bar as a whole, so a tiny
    sliver still gets a legible label right next to it)."""
    category_totals = df_period.groupby("Category")["Hours (exact)"].sum().reindex(category_order).dropna()
    fig = go.Figure()
    if len(category_totals):
        category_pct = category_totals / category_totals.sum() * 100
        for cat in category_totals.index:
            pct = category_pct[cat]
            inside = pct >= 6
            fig.add_trace(go.Bar(
                y=[""], x=[pct], orientation="h", name=cat,
                marker=dict(color=category_colors[cat], line=dict(color=TL_SURFACE, width=1)),
                text=f"{cat} ({pct:.0f}%)",
                textposition="inside" if inside else "outside",
                insidetextanchor="middle",
                textfont=dict(color="white" if inside else TL_INK_SECONDARY, size=11),
                showlegend=False,
                customdata=[format_hm(category_totals[cat])],
                hovertemplate=f"<b>{cat}</b><br>%{{customdata}} (%{{x:.0f}}%)<extra></extra>",
            ))
        fig.update_xaxes(visible=False, range=[0, 100])
    else:
        _empty(fig, "No hours logged yet")
        fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    fig.update_layout(
        **base_layout(title, width=1000, height=220, bgcolor=TL_SURFACE, font_color=TL_INK_PRIMARY),
        barmode="stack", showlegend=False, margin=dict(l=10, r=40, t=60, b=10),
    )
    return fig


def fig_major_task_share_stacked(df_period, title, task_category, category_order, category_colors):
    """100%-wide single stacked bar, one segment per major task -- merged across Category
    the same way fig_monthly_major_task_hours is (one task = one segment = one color via
    `task_category`'s single-category-per-task rule), rather than split per Category like
    fig_hours_by_project_task and fig_major_task_share_by_category. Keeps this one simple
    and consistent with the Year tab's other by-month task view."""
    task_totals = df_period.groupby("Major task name (chart)")["Hours (exact)"].sum()
    fig = go.Figure()
    if len(task_totals):
        task_order = pd.DataFrame({
            "category_rank": task_category.reindex(task_totals.index).map(
                {c: i for i, c in enumerate(category_order)}),
            "hours": task_totals,
        }).sort_values(["category_rank", "hours"], ascending=[True, False])
        task_totals = task_order["hours"]
        task_pct = task_totals / task_totals.sum() * 100
        for task in task_totals.index:
            pct = task_pct[task]
            fig.add_trace(go.Bar(
                y=[""], x=[pct], orientation="h", name=task,
                marker=dict(color=category_colors[task_category[task]], line=dict(color=TL_SURFACE, width=1)),
                text=task if pct >= 3 else "",
                textposition="inside", insidetextanchor="middle", textfont=dict(color="white", size=10),
                showlegend=False,
                customdata=[format_hm(task_totals[task])],
                hovertemplate=f"<b>{task}</b><br>%{{customdata}} (%{{x:.0f}}%)<extra></extra>",
            ))
        fig.update_xaxes(visible=False, range=[0, 100])
    else:
        _empty(fig, "No hours logged yet")
        fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    fig.update_layout(
        **base_layout(title, width=1000, height=250, bgcolor=TL_SURFACE, font_color=TL_INK_PRIMARY),
        barmode="stack", showlegend=False,
    )
    return fig


def _month_grouped_bar(pivot, bar_colors, title, y_title, extra_legend=None):
    months_present = list(pivot.columns)
    n_months = len(months_present)
    bar_width = 0.8 / max(n_months, 1)
    month_alphas = [1.0] if n_months <= 1 else [1.0 - 0.55 * i / (n_months - 1) for i in range(n_months)]
    x = list(range(len(pivot)))

    fig = go.Figure()
    for i, month in enumerate(months_present):
        offset = (i - (n_months - 1) / 2) * bar_width
        values = pivot[month].values
        fig.add_trace(go.Bar(
            x=[xi + offset for xi in x], y=values, width=bar_width,
            marker=dict(color=bar_colors, opacity=month_alphas[i], line=dict(color=TL_SURFACE, width=1)),
            showlegend=False,
            text=[month[:3] if v > 0 else "" for v in values],
            textposition="outside", textfont=dict(color=TL_INK_SECONDARY, size=9),
            hovertext=[f"<b>{row}</b><br>{month}: {format_hm(v)}" for row, v in zip(pivot.index, values)],
            hoverinfo="text",
        ))

    fig.update_xaxes(tickvals=x, ticktext=list(pivot.index), tickangle=-30, showgrid=False)
    fig.update_yaxes(title_text=y_title, showgrid=True, gridcolor=TL_GRID)
    fig.update_layout(
        **base_layout(title, width=950, height=520, bgcolor=TL_SURFACE, font_color=TL_INK_PRIMARY),
        barmode="overlay", showlegend=False,
    )
    return fig


def fig_category_hours_by_month(df_period, months_present, category_order, category_colors):
    category_month = (
        df_period.groupby(["Category", "Month"], observed=True)["Hours (exact)"].sum()
        .unstack("Month", fill_value=0)
    )
    category_month = category_month.reindex(columns=months_present, fill_value=0).reindex(category_order).dropna(how="all")
    colors = [category_colors[c] for c in category_month.index]
    return _month_grouped_bar(category_month, colors, "Category hours by month", "Hours")


def fig_monthly_major_task_hours(df_period, months_present, task_category, category_order, category_colors):
    """Horizontal, not vertical: the task list is a fixed ~11 items, but months keep
    growing toward 13 over the year -- horizontal bars let the figure grow TALLER to fit
    them (natural on a page that scrolls vertically) instead of squeezing each month's bar
    thinner inside a fixed-width cluster."""
    task_month = (
        df_period.groupby(["Major task name (chart)", "Month"], observed=True)["Hours (exact)"].sum()
        .unstack("Month", fill_value=0)
    )
    present = [m for m in months_present if m in task_month.columns]
    task_month = task_month[present] if present else task_month
    order = pd.DataFrame({
        "category_rank": task_category.reindex(task_month.index).map({c: i for i, c in enumerate(category_order)}),
        "total": task_month.sum(axis=1),
    }).sort_values(["category_rank", "total"], ascending=[True, False])
    task_month = task_month.loc[order.index]
    colors = [category_colors.get(task_category.get(t), TL_INK_MUTED) for t in task_month.index]

    n_tasks = len(task_month)
    n_months = len(present)
    bar_height = 0.8 / max(n_months, 1)
    month_alphas = [1.0] if n_months <= 1 else [1.0 - 0.55 * i / (n_months - 1) for i in range(n_months)]
    y = list(range(n_tasks))

    fig = go.Figure()
    for i, month in enumerate(present):
        offset = (i - (n_months - 1) / 2) * bar_height
        values = task_month[month].values
        fig.add_trace(go.Bar(
            y=[yi + offset for yi in y], x=values, orientation="h", width=bar_height,
            marker=dict(color=colors, opacity=month_alphas[i], line=dict(color=TL_SURFACE, width=1)),
            showlegend=False,
            text=[month[:3] if v > 0 else "" for v in values],
            textposition="outside", textfont=dict(color=TL_INK_SECONDARY, size=9),
            hovertext=[f"<b>{row}</b><br>{month}: {format_hm(v)}" for row, v in zip(task_month.index, values)],
            hoverinfo="text",
        ))

    fig.update_yaxes(tickvals=y, ticktext=list(task_month.index), showgrid=False, autorange="reversed")
    fig.update_xaxes(title_text="Hours", showgrid=True, gridcolor=TL_GRID)
    height = 160 + n_tasks * max(38, 9 * n_months + 24)
    fig.update_layout(
        **base_layout("Major-task hours by month", width=1100, height=height, bgcolor=TL_SURFACE, font_color=TL_INK_PRIMARY),
        barmode="overlay", showlegend=False,
        margin=dict(l=170),
    )
    return fig


def fig_category_weekly_distribution(df_period, category_order, category_colors, title="Category distribution by week"):
    cat_week = (
        df_period.groupby(["_week_sort", "Week", "Category"])["Hours (exact)"].sum().reset_index()
    )
    pivot = cat_week.pivot_table(
        index=["_week_sort", "Week"], columns="Category", values="Hours (exact)", fill_value=0
    ).sort_index(level="_week_sort")
    pivot.index = pivot.index.get_level_values("Week")
    order = [c for c in category_order if c in pivot.columns] + [c for c in pivot.columns if c not in category_order]
    pivot = pivot[order] if order else pivot

    fig = go.Figure()
    if len(pivot):
        week_totals = pivot.sum(axis=1).replace(0, pd.NA)
        for cat in order:
            pct = (pivot[cat] / week_totals * 100).fillna(0)
            fig.add_trace(go.Bar(
                x=pivot.index, y=pivot[cat], name=cat, width=0.6,
                marker=dict(color=category_colors.get(cat, TL_INK_MUTED), line=dict(color=TL_SURFACE, width=1)),
                text=[f"{p:.0f}%" if p >= 8 else "" for p in pct],
                textposition="inside", insidetextanchor="middle", textfont=dict(color="white", size=9),
                customdata=list(zip([format_hm(v) for v in pivot[cat]], pct)),
                hovertemplate=f"<b>{cat}</b><br>" + "%{x}: %{customdata[0]} (%{customdata[1]:.0f}%)<extra></extra>",
            ))
        fig.update_xaxes(showgrid=False, tickangle=-30)
    else:
        _empty(fig, "No hours logged yet")
        fig.update_xaxes(visible=False)
    fig.update_yaxes(title_text="Hours", showgrid=True, gridcolor=TL_GRID)
    fig.update_layout(
        **base_layout(title, width=950, height=480, bgcolor=TL_SURFACE, font_color=TL_INK_PRIMARY),
        barmode="stack",
        legend=dict(x=1.02, y=1, xanchor="left"),
    )
    return fig


# --- Year tab: project-tracker charts -------------------------------------------------------

def fig_hours_by_project(projects, df_period=None):
    """Hours per project, preferring the personal time log (`df_period`, already filtered
    to this reporting period) for any project it covers -- updates live as hours get
    logged -- and falling back to the project tracker's own 'Hours in Timesheet' column
    (clipped at 0: it can show a stale negative/blank value for a just-registered project
    before Timesheet settles) for a project the time log doesn't cover, e.g. one from a period
    that predates the time log entirely."""
    project_desc = projects.set_index("Project tag")["Short Description"] if "Short Description" in projects.columns else pd.Series(dtype=str)

    hours, source = project_hours_with_source(projects, df_period)
    project_hours = pd.Series(hours, dtype=float)
    project_hours = project_hours[project_hours > 0].sort_values(ascending=False)

    fig = go.Figure()
    if len(project_hours):
        fig.add_trace(go.Bar(
            x=project_hours.index, y=project_hours.values,
            marker_color="#2a78d6", marker_line=dict(color=TL_SURFACE, width=1), width=0.6,
            text=[format_hm(v) for v in project_hours.values], textposition="outside",
            textfont=dict(color=TL_INK_SECONDARY, size=11), cliponaxis=False,
            hovertext=[
                f"<b>{p}</b> ({source[p]})"
                + (f"<br>{project_desc[p]}" if p in project_desc.index and pd.notna(project_desc[p]) else "")
                for p in project_hours.index
            ],
            hoverinfo="text",
        ))
        fig.update_yaxes(range=[0, project_hours.max() * 1.15])
    else:
        _empty(fig, "No hours recorded yet")
    fig.update_xaxes(showgrid=False)
    fig.update_yaxes(title_text="Hours in Timesheet", showgrid=True, gridcolor=TL_GRID)
    fig.update_layout(**base_layout("Hours by project", width=900, height=450, bgcolor=TL_SURFACE, font_color=TL_INK_PRIMARY))
    return fig


def _project_bullets(projects, mask, empty_text="(none)"):
    """'• DNA_031 — Short description' per matching row, one per line, for a hover list."""
    sub = projects.loc[mask]
    if not len(sub):
        return empty_text
    has_desc = "Short Description" in projects.columns
    lines = []
    for _, r in sub.iterrows():
        desc = r.get("Short Description") if has_desc else None
        lines.append(f"• {r['Project tag']}" + (f" — {desc}" if pd.notna(desc) and desc else ""))
    return "<br>".join(lines)


def _finished_bullets(projects, mask, empty_text="No projects finished"):
    """Like _project_bullets, but for the "Finished" trace specifically: names the actual
    bureaucratic closing date, and -- when the final report went out on a different day --
    how long closing lagged behind the real deliverable, so "finished this month" doesn't
    read as "the work happened this month" when it was really just the paperwork catching
    up (see kd.closing_gap_summary for the chart-wide version of this same distinction)."""
    sub = projects.loc[mask]
    if not len(sub):
        return empty_text
    has_desc = "Short Description" in projects.columns
    has_report = "Final Report Sent" in projects.columns
    lines = []
    for _, r in sub.iterrows():
        desc = r.get("Short Description") if has_desc else None
        line = f"• {r['Project tag']}" + (f" — {desc}" if pd.notna(desc) and desc else "")
        closing = r.get("Closing Day")
        if pd.notna(closing):
            line += f" — closed {pd.Timestamp(closing).strftime('%d %b')}"
        report = r.get("Final Report Sent") if has_report else None
        if pd.notna(report) and pd.notna(closing):
            gap = (pd.Timestamp(closing) - pd.Timestamp(report)).days
            if gap > 0:
                line += f" (report sent {gap}d earlier)"
            else:
                line += " (same day as final report)"
        elif has_report and pd.isna(report):
            line += " (no report sent -- internal/no-deliverable work)"
        lines.append(line)
    return "<br>".join(lines)


def fig_received_vs_finished(projects, period_months, period_start, truncate_at):
    """`truncate_at` is the last period-month whose workload count is a settled fact
    (None to show every month, e.g. for a fully-closed past period). "Received" uses
    effective_received_date (kpi_data) rather than the raw Register Project column, so an
    Inherited Project is attributed to the month work actually began for the current owner,
    not its original (pre-handoff) registration date -- which also means the period_start cutoff
    below is checked against that same effective date, not the raw one."""
    received_date = effective_received_date(projects)
    received = (
        received_date[received_date >= period_start]
        .dt.to_period("M").value_counts().reindex(period_months, fill_value=0)
    )
    finished = projects["Closing Day"].dt.to_period("M").value_counts().reindex(period_months, fill_value=0)

    # Real workload line: starts at effective_workload_start (kpi_data) -- First User
    # Meeting/Shared Data, falling back to Begining, then Register Project, except an
    # Inherited Project, which only starts counting at Begining (its meeting/registration
    # dates belong to whoever had it before); ends at Final Report Sent, falling back to
    # Closing Day if no report was ever sent (not "open forever" when Final Report Sent is
    # blank); and Consulting-trigger rows stay off this line entirely.
    workload_start = effective_workload_start(projects)

    workload_end = projects["Final Report Sent"]
    if "Closing Day" in projects.columns:
        workload_end = workload_end.fillna(projects["Closing Day"])

    if "Project Trigger" in projects.columns:
        in_workload = projects["Project Trigger"] != "Consulting"
    else:
        in_workload = pd.Series(True, index=projects.index)

    workload = []
    received_hover, finished_hover, workload_hover = [], [], []
    for month in period_months:
        received_mask = (
            (received_date >= period_start)
            & (received_date.dt.to_period("M") == month)
        )
        finished_mask = projects["Closing Day"].dt.to_period("M") == month
        # Month-end snapshot, matching the reference deck script exactly: open at month M
        # if it had already started by M's last day and had NOT yet ended by M's last day
        # (a project delivered mid-month still counts as open for that month; it drops off
        # starting the month after -- not the month it closes in, which is what "one less
        # closed in Sep, one more in Oct" turned out to be pointing at: that one's a data
        # typo (DNA_018), not this formula, but the formula itself needed this fix too).
        open_mask = (
            in_workload
            & (workload_start <= month.end_time)
            & ~(workload_end <= month.end_time)
        )
        workload.append(open_mask.sum())
        received_hover.append(_project_bullets(projects, received_mask, "No projects received"))
        finished_hover.append(_finished_bullets(projects, finished_mask, "No projects finished"))
        workload_hover.append(_project_bullets(projects, open_mask, "Nothing open"))
    workload = pd.Series(workload, index=period_months, dtype=float)
    if truncate_at is not None:
        workload[workload.index > truncate_at] = float("nan")
        for i, month in enumerate(period_months):
            if month > truncate_at:
                workload_hover[i] = "Not yet known (future month)"

    month_labels = [
        m.strftime("%b<br>%Y") if m.month == 1 or m == period_months[0] or m == period_months[-1] else m.strftime("%b")
        for m in period_months
    ]
    y_max = max(6, int(max(received.max(), finished.max(), pd.Series(workload).max(skipna=True) or 0)) + 1)
    tick_range = range(-y_max, y_max + 1, 2)

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=month_labels, y=received.values, marker_color=RECEIVED_COLOR, width=0.6,
        text=[str(v) if v > 0 else "" for v in received.values],
        textposition="inside", insidetextanchor="end", textfont=dict(color="white", size=13),
        name="Received (registered in Timesheet)",
        customdata=received_hover,
        hovertemplate="<b>%{x} — Received: %{y}</b><br>%{customdata}<extra></extra>",
    ))
    fig.add_trace(go.Bar(
        x=month_labels, y=-finished.values, marker_color=FINISHED_COLOR, width=0.6,
        text=[str(v) if v > 0 else "" for v in finished.values],
        textposition="inside", insidetextanchor="end", textfont=dict(color="white", size=13),
        name="Finished (closing day)",
        customdata=list(zip(finished.values, finished_hover)),
        hovertemplate="<b>%{x} — Finished: %{customdata[0]}</b><br>%{customdata[1]}<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=month_labels, y=workload.values, mode="lines+markers",
        line=dict(color=WORKLOAD_COLOR, dash="dash", width=2),
        marker=dict(color="white", size=9, line=dict(color=WORKLOAD_COLOR, width=2)),
        name="Real workload: open from first data until final report sent",
        customdata=workload_hover,
        hovertemplate="<b>%{x} — Workload: %{y}</b><br>%{customdata}<extra></extra>",
    ))
    fig.add_hline(y=0, line_color=BASELINE, line_width=1)
    fig.add_annotation(x=0.01, y=0.98, xref="paper", yref="paper", text="IN ↑", showarrow=False,
                        font=dict(color=RECEIVED_COLOR, size=13), xanchor="left", yanchor="top")
    fig.add_annotation(x=0.01, y=0.02, xref="paper", yref="paper", text="OUT ↓", showarrow=False,
                        font=dict(color=FINISHED_COLOR, size=13), xanchor="left", yanchor="bottom")
    fig.update_yaxes(range=[-y_max, y_max], tickvals=list(tick_range), ticktext=[abs(v) for v in tick_range],
                      title_text="Projects", showgrid=True, gridcolor=GRID, zeroline=False)
    fig.update_xaxes(showgrid=False)
    fig.update_layout(
        **base_layout("Projects received vs finished", width=1000, height=600),
        barmode="overlay",
        legend=dict(orientation="h", yanchor="top", y=-0.18, xanchor="center", x=0.5),
    )
    return fig


def fig_project_complexity(projects, df_period=None):
    """Plots a project as soon as it has EITHER Number of Reports or Number of Meetings
    recorded -- not both -- since a project commonly gets one of the two before the other.
    A metric that's genuinely missing (not just zero) is plotted as 0 on that axis but
    flagged as "not yet recorded" in the hover, so a real zero and "not tracked yet" still
    read differently on inspection even though they share a position. Bubble size and the
    hover's hours line use the same time-log-preferring hours as "Hours by project" and
    "year at a glance" (see project_hours_with_source), not the raw Timesheet column alone."""
    bubble = projects.copy()
    bubble["Number of Reports"] = pd.to_numeric(bubble.get("Number of Reports"), errors="coerce")
    bubble["Number of Meetings"] = pd.to_numeric(bubble.get("Number of Meetings"), errors="coerce")
    bubble = bubble.dropna(subset=["Number of Reports", "Number of Meetings"], how="all")

    fig = go.Figure()
    if len(bubble):
        reports_known = bubble["Number of Reports"].notna()
        meetings_known = bubble["Number of Meetings"].notna()
        bubble["Number of Reports"] = bubble["Number of Reports"].fillna(0)
        bubble["Number of Meetings"] = bubble["Number of Meetings"].fillna(0)

        hours_by_tag, hours_source = project_hours_with_source(projects, df_period)
        has_desc = "Short Description" in bubble.columns
        bubble_size = bubble["Project tag"].map(hours_by_tag).fillna(1).clip(lower=1)

        def _metric_text(value, known, label):
            return f"{label}: {value:.0f}" if known else f"{label}: not yet recorded"

        hover_text = [
            (
                f"<b>{r['Project tag']}</b><br>"
                f"{_metric_text(r['Number of Reports'], reports_known.loc[i], 'Reports')}<br>"
                f"{_metric_text(r['Number of Meetings'], meetings_known.loc[i], 'Meetings')}<br>"
                + (
                    f"Hours: {format_hm(hours_by_tag[r['Project tag']])} ({hours_source[r['Project tag']]})"
                    if r["Project tag"] in hours_by_tag and hours_by_tag[r["Project tag"]] > 0
                    else "Hours: n/a"
                )
                + (f"<br>{r['Short Description']}" if has_desc and pd.notna(r.get("Short Description")) else "")
            )
            for i, r in bubble.iterrows()
        ]
        jx, jy, textpos = spread_overlapping(bubble["Number of Reports"], bubble["Number of Meetings"])
        fig.add_trace(go.Scatter(
            x=jx, y=jy, mode="markers+text",
            marker=dict(size=bubble_size, sizemode="area", sizeref=2.0 * bubble_size.max() / (60.0 ** 2),
                        sizemin=6, color=FINISHED_COLOR, opacity=0.85, line=dict(color="white", width=1.5)),
            text=bubble["Project tag"], textposition=textpos, textfont=dict(size=10, color=INK),
            hovertext=hover_text, hoverinfo="text",
        ))
        x_pad = (bubble["Number of Reports"].max() - bubble["Number of Reports"].min()) * 0.25 or 1
        y_pad = (bubble["Number of Meetings"].max() - bubble["Number of Meetings"].min()) * 0.25 or 1
        fig.update_xaxes(title_text="Number of reports", showgrid=True, gridcolor=GRID,
                          range=[bubble["Number of Reports"].min() - x_pad, bubble["Number of Reports"].max() + x_pad])
        fig.update_yaxes(title_text="Number of meetings", showgrid=True, gridcolor=GRID,
                          range=[bubble["Number of Meetings"].min() - y_pad, bubble["Number of Meetings"].max() + y_pad])
        fig.add_annotation(x=0.98, y=0.98, xref="paper", yref="paper",
                            text="Bubble size = hours. A missing metric plots as 0 (hover for details).",
                            showarrow=False, font=dict(color=MUTED, size=11), xanchor="right", yanchor="top")
    else:
        _empty(fig, "No project has Number of Reports or Number of Meetings recorded yet")
        fig.update_xaxes(visible=False)
        fig.update_yaxes(visible=False)
    fig.update_layout(**base_layout("Project complexity", width=900, height=620))
    return fig


def category_hover(df, col, desc_col="Short Description"):
    hovers = {}
    for cat, group in df.groupby(col):
        items = group[desc_col].dropna().astype(str) if desc_col in group.columns else pd.Series([], dtype=str)
        bullets = "<br>".join(f"• {d}" for d in items) if len(items) else "(no description)"
        hovers[cat] = f"<b>{cat}</b> ({len(group)})<br>{bullets}"
    return hovers


def fig_project_definition(projects):
    panels = [c for c in ["Type of Data", "Project Trigger", "Project Outputs"] if c in projects.columns]
    fig = make_subplots(rows=1, cols=len(panels), subplot_titles=panels, horizontal_spacing=0.15)
    for i, col in enumerate(panels, start=1):
        counts = projects[col].value_counts().sort_values(ascending=True)
        hovers = category_hover(projects, col)
        fig.add_trace(
            go.Bar(x=counts.values, y=[_wrap_label(v) for v in counts.index], orientation="h",
                   marker_color=RECEIVED_COLOR, width=0.4,
                   text=counts.values, textposition="outside", textfont=dict(color=INK, size=11), cliponaxis=False,
                   hovertext=[hovers[c] for c in counts.index], hoverinfo="text", showlegend=False),
            row=1, col=i,
        )
        fig.update_xaxes(visible=False, range=[0, (counts.max() or 1) * 1.3], row=1, col=i)
    fig.update_yaxes(showgrid=False)
    fig.update_layout(
        **base_layout("Definition of Project", width=1300, height=480),
        margin=dict(l=60, r=30, t=70, b=30), bargap=0.05,
    )
    return fig


# "Project Outputs" is a categorical field (what a project produced), so each value gets its
# own HUE from the dashboard's categorical palette. It used to use a monochrome blue ramp,
# which is a sequential scale doing a categorical job: its adjacent steps measured ΔE 13.4 in
# normal vision -- under the 15 floor -- so "Tool", "AI Skill" and "User-Project Only" were
# genuinely hard to tell apart. The replacement passes every check of the palette validator
# in both light and dark (worst adjacent pair ΔE 21.8 normal / 9.0 CVD).
# Slots are pinned to the VALUE, never to its rank in value_counts(): a project changing its
# output, or a new period with different counts, must not repaint the other categories.
OUTPUT_HUE_SLOTS = {"Tool": 0, "AI Skill": 1, "User-Project Only": 2}


def output_colors(values):
    """{Project Outputs value: hex} for the active theme, stable per value. Unpinned values
    (a new output type) take the remaining palette slots in alphabetical order, so they are
    deterministic too."""
    palette = TL_PALETTE_DARK if _DARK else TL_PALETTE
    spare = [i for i in range(len(palette)) if i not in set(OUTPUT_HUE_SLOTS.values())]
    colors = {}
    for value in sorted(values):
        if value in OUTPUT_HUE_SLOTS:
            colors[value] = palette[OUTPUT_HUE_SLOTS[value] % len(palette)]
        else:
            colors[value] = palette[spare.pop(0) % len(palette)] if spare else palette[-1]
    return colors


def fig_who_we_work_with(projects):
    projects = projects.copy()
    # projects.get("Project Outputs", fallback) is the wrong tool when the column is simply
    # absent (an older period's sheet): the fallback is an EMPTY series with no index, and
    # assigning it to a column on a 20-row frame aligns by index -- every row becomes NaN,
    # not "", because the fallback never had any rows to begin with. That silently made
    # every "_output" value NaN -> both stacked panels below got zero categories -> zero
    # bars, for any period without a "Project Outputs" column.
    if "Project Outputs" in projects.columns:
        projects["_output"] = projects["Project Outputs"].fillna("").astype(str).str.strip()
    else:
        projects["_output"] = ""
    projects["_output"] = projects["_output"].replace("", "No output yet")
    output_values = [v for v in projects["_output"].value_counts().index if v != "No output yet"]
    stack_order = output_values + (["No output yet"] if "No output yet" in set(projects["_output"]) else [])
    stack_colors = output_colors(output_values)
    # Absence of an output isn't a category of its own -- muted gray keeps it recessive.
    stack_colors["No output yet"] = TL_INK_MUTED

    fig = make_subplots(rows=1, cols=3, subplot_titles=["User type", "Group", "User location"], horizontal_spacing=0.18)
    for i, col in enumerate(["User Type", "Grupo"], start=1):
        pivot = projects.groupby([col, "_output"]).size().unstack("_output", fill_value=0)
        pivot = pivot.reindex(columns=[c for c in stack_order if c in pivot.columns])
        order = pivot.sum(axis=1).sort_values(ascending=True).index
        pivot = pivot.loc[order]
        wrapped_y = [_wrap_label(v) for v in pivot.index]
        for out in pivot.columns:
            out_df = projects[projects["_output"] == out]
            hovers = category_hover(out_df, col)
            fig.add_trace(
                go.Bar(x=pivot[out], y=wrapped_y, orientation="h", name=out,
                       marker=dict(color=stack_colors[out],
                                   line=dict(color=TL_SURFACE, width=2)),  # gap between segments
                       width=0.4, showlegend=(i == 1),
                       hovertext=[hovers.get(v, f"<b>{v}</b> (0)<br>(no projects)") for v in pivot.index],
                       hoverinfo="text"),
                row=1, col=i,
            )
        row_totals = pivot.sum(axis=1)
        fig.add_trace(
            go.Scatter(x=row_totals, y=wrapped_y, mode="text", text=row_totals.values,
                       textposition="middle right", textfont=dict(color=INK, size=11),
                       hoverinfo="skip", showlegend=False),
            row=1, col=i,
        )
        fig.update_xaxes(visible=False, range=[0, (pivot.sum(axis=1).max() or 1) * 1.3], row=1, col=i)

    counts = projects["User Location"].value_counts().sort_values(ascending=True)
    hovers = category_hover(projects, "User Location")
    fig.add_trace(
        go.Bar(x=counts.values, y=[_wrap_label(v) for v in counts.index], orientation="h",
               marker_color=RECEIVED_COLOR, width=0.4,
               text=counts.values, textposition="outside", textfont=dict(color=INK, size=11), cliponaxis=False,
               hovertext=[hovers[c] for c in counts.index], hoverinfo="text", showlegend=False),
        row=1, col=3,
    )
    fig.update_xaxes(visible=False, range=[0, (counts.max() or 1) * 1.3], row=1, col=3)
    fig.update_yaxes(showgrid=False)
    fig.update_layout(
        **base_layout("Who we work with and why", width=1300, height=500),
        barmode="stack", bargap=0.05,
        legend=dict(title=dict(text="Project Outputs"), orientation="h",
                    yanchor="bottom", y=1.1, xanchor="center", x=0.5),
        margin=dict(l=70, r=40, t=120, b=40),
    )
    return fig


def fig_consulting_overview(meetings):
    fig = make_subplots(rows=1, cols=2, subplot_titles=["Consultation meetings per group", "Meeting outputs"],
                         horizontal_spacing=0.18)
    if len(meetings):
        group_meetings = meetings["Grupo"].value_counts().sort_values(ascending=True)
        fig.add_trace(
            go.Bar(x=group_meetings.values, y=[_wrap_label(v) for v in group_meetings.index], orientation="h",
                   marker_color=FINISHED_COLOR, width=0.4,
                   text=group_meetings.values, textposition="outside", textfont=dict(color=INK, size=11), cliponaxis=False,
                   customdata=group_meetings.index,
                   hovertemplate="<b>%{customdata}</b><br>Consultation meetings: %{x}<extra></extra>", showlegend=False),
            row=1, col=1,
        )
        fig.update_xaxes(visible=False, range=[0, group_meetings.max() * 1.3], row=1, col=1)

        outputs_counts = meetings["Meeting Outputs"].value_counts().sort_values(ascending=True)
        fig.add_trace(
            go.Bar(x=outputs_counts.values, y=[_wrap_label(v, width=24) for v in outputs_counts.index], orientation="h",
                   marker_color=FINISHED_COLOR, width=0.4,
                   text=outputs_counts.values, textposition="outside", textfont=dict(color=INK, size=11), cliponaxis=False,
                   customdata=outputs_counts.index,
                   hovertemplate="<b>%{customdata}</b><br>Meetings: %{x}<extra></extra>", showlegend=False),
            row=1, col=2,
        )
        fig.update_xaxes(visible=False, range=[0, outputs_counts.max() * 1.3], row=1, col=2)
    else:
        for c in (1, 2):
            fig.add_annotation(text="No consultation meetings logged yet this period", x=0.5, y=0.5,
                                xref="paper", yref="paper", showarrow=False, font=dict(color=MUTED, size=13),
                                row=1, col=c)
            fig.update_xaxes(visible=False, row=1, col=c)
    fig.update_yaxes(showgrid=False)
    fig.update_layout(**base_layout("Consulting", width=1100, height=480), margin=dict(l=70, r=30, t=70, b=30), bargap=0.05)
    return fig


def _hover_description(text):
    """Split on ';' into one hover line each, trimming whitespace and dropping empties."""
    parts = [p.strip() for p in str(text).split(";")]
    return "<br>".join(p for p in parts if p)


def _hover_note(symbol, text, color):
    return f'<span style="color:{color}">{symbol} {text}</span>'


# --- Goals: the effort / impact matrix -----------------------------------------------------
# The bubble chart plots development effort against impact, which makes it a classic
# effort/impact matrix -- so the four quadrants carry the standard reading below. Ratings are
# whole stars, so the split sits at 2.5 ("1-2 stars = low, 3-5 = high"): that keeps every
# bubble, jitter included, on one definite side instead of straddling a divider at 3.
GOAL_SPLIT = 2.5

# (label, what it means, low/high half on x, low/high half on y, tint hue)
GOAL_QUADRANTS = [
    ("Quick wins", "little effort, big payoff — do these first",
     "low", "high", "#0ca30c"),
    ("Big bets", "heavy effort, big payoff — worth it, but plan and resource them",
     "high", "high", "#1a6090"),
    ("Fill-ins", "little effort, small payoff — slot them around the real work",
     "low", "low", "#898781"),
    ("Money pits", "heavy effort, small payoff — shrink the scope, rethink or drop",
     "high", "low", "#c9701e"),
]


def goal_quadrant(development, impact):
    """Which of GOAL_QUADRANTS a project's (Development, Impact) rating falls in."""
    halves = ("high" if development > GOAL_SPLIT else "low",
              "high" if impact > GOAL_SPLIT else "low")
    for label, _meaning, qx, qy, _tint in GOAL_QUADRANTS:
        if (qx, qy) == halves:
            return label
    return ""


def fig_goals_at_a_glance(goals_df):
    """Finished projects (a date in the ratings sheet's Completed column) keep their goal
    color but wear a green ring and a white check inside the bubble, so "what's done" reads
    at a glance without adding a second color scale on top of the goal one."""
    finished = (goals_df["_finished"] if "_finished" in goals_df.columns
                else pd.Series(False, index=goals_df.index))

    def _finished_note(r):
        if not r.get("_finished"):
            return ""
        when = r.get("_completed")
        return f"<br><b>✓ Finished</b>" + (f" {when.strftime('%d %b %Y')}" if when else "")

    hover_text = goals_df.apply(
        lambda r: (
            f"<b>{r['Project']}</b><br>{r['Goal']}<br>"
            f"Development {r['Development']:.0f}★ · Impact {r['Impact']:.0f}★ · "
            f"Maintenance {r['Maintenance']:.0f}★ · Visibility {r['Visibility']:.0f}★<br>"
            f"<i>{goal_quadrant(r['Development'], r['Impact'])}</i>"
            + _finished_note(r)
            + (f"<br><br>{_hover_description(r['Description'])}" if pd.notna(r.get("Description")) and r["Description"] else "")
            + (f"<br>{_hover_note('+', r['Advantages'], TL_GOOD)}" if pd.notna(r.get("Advantages")) and r["Advantages"] else "")
            + (f"<br>{_hover_note('-', r['Limitations'], TL_CRITICAL)}" if pd.notna(r.get("Limitations")) and r["Limitations"] else "")
            + (f"<br>{_hover_note('→', r['Future gain'], RECEIVED_COLOR)}" if pd.notna(r.get("Future gain")) and r["Future gain"] else "")
        ), axis=1,
    )
    fig = go.Figure()

    # Quadrant washes: very low alpha so they read as a background, never competing with
    # the goal-colored bubbles. Labels wear muted ink rather than the tint hue, which would
    # be unreadable against one of the two surfaces.
    axis_lo, axis_hi = 0, 6
    tint_alpha = 0.13 if _DARK else 0.10
    for label, _meaning, qx, qy, tint in GOAL_QUADRANTS:
        x0, x1 = (axis_lo, GOAL_SPLIT) if qx == "low" else (GOAL_SPLIT, axis_hi)
        y0, y1 = (axis_lo, GOAL_SPLIT) if qy == "low" else (GOAL_SPLIT, axis_hi)
        fig.add_shape(type="rect", x0=x0, x1=x1, y0=y0, y1=y1, layer="below",
                      fillcolor=_rgba(tint, tint_alpha), line_width=0)
        fig.add_annotation(
            x=(x0 + 0.12) if qx == "low" else (x1 - 0.12),
            y=(y1 - 0.12) if qy == "high" else (y0 + 0.12),
            xanchor="left" if qx == "low" else "right",
            yanchor="top" if qy == "high" else "bottom",
            text=f"<b>{label.upper()}</b>", showarrow=False,
            font=dict(color=MUTED, size=11),
        )
    for axis in ("x", "y"):
        fig.add_shape(
            type="line", layer="below", line=dict(color=TL_BASELINE, width=1, dash="dot"),
            **(dict(x0=GOAL_SPLIT, x1=GOAL_SPLIT, y0=axis_lo, y1=axis_hi) if axis == "x"
               else dict(x0=axis_lo, x1=axis_hi, y0=GOAL_SPLIT, y1=GOAL_SPLIT)),
        )

    max_visibility = goals_df["Visibility"].max()
    for group_label in goals_df["_group_label"].unique():
        sub = goals_df[goals_df["_group_label"] == group_label]
        sub_finished = finished.loc[sub.index]
        fig.add_trace(go.Scatter(
            x=sub["_x"], y=sub["_y"], mode="markers+text",
            marker=dict(size=sub["Visibility"], sizemode="area",
                        sizeref=2.0 * max_visibility / (55.0 ** 2), sizemin=8,
                        color=sub["_group_color"].iloc[0], opacity=0.8,
                        line=dict(color=[TL_GOOD if f else "white" for f in sub_finished],
                                  width=[2.5 if f else 1.5 for f in sub_finished])),
            text=sub["Project"], textposition=sub["_textpos"], textfont=dict(size=9, color=INK),
            hovertext=hover_text.loc[sub.index], hoverinfo="text",
            customdata=[[p] for p in sub["Project"]], name=group_label,
        ))

    # The check rides in its own text trace on top of the bubbles (a marker can't carry a
    # glyph), sized off each bubble's own diameter so it still fits a 1-star-visibility dot.
    done = goals_df[finished]
    if len(done):
        # Plotly's own area sizing: with sizeref = 2*max/(55**2) a bubble's drawn diameter
        # is 55*sqrt(v / (2*max)) px, floored at sizemin=8.
        glyph_sizes = [
            min(15.0, max(8.0, 0.62 * max(8.0, 55.0 * math.sqrt(v / (2.0 * max_visibility)))))
            for v in done["Visibility"]
        ]
        fig.add_trace(go.Scatter(
            x=done["_x"], y=done["_y"], mode="text", text=["✓"] * len(done),
            textposition="middle center",
            textfont=dict(size=glyph_sizes, color="white", family=FONT_FAMILY),
            hovertext=hover_text.loc[done.index], hoverinfo="text",
            customdata=[[p] for p in done["Project"]], showlegend=False,
        ))
        # Legend-only entry: an empty bubble wearing the same green ring, so the chart
        # explains its own mark instead of needing a caption to.
        fig.add_trace(go.Scatter(
            x=[None], y=[None], mode="markers", name="✓ Finished",
            marker=dict(size=13, color="rgba(0,0,0,0)", line=dict(color=TL_GOOD, width=2.5)),
            hoverinfo="skip",
        ))
    fig.update_xaxes(title_text="Development effort (stars)", range=[axis_lo, axis_hi], dtick=1,
                      showgrid=True, gridcolor=GRID)
    fig.update_yaxes(title_text="Impact (stars)", range=[axis_lo, axis_hi], dtick=1,
                      showgrid=True, gridcolor=GRID)
    layout = base_layout("Goals at a glance", width=950, height=650)
    layout["title"]["text"] = (
        "Goals at a glance<br>"
        f"<span style='font-size:11px;color:{MUTED}'>Quadrants split low (1-2★) from high "
        "(3-5★) effort and impact · bubble size = visibility · projects sharing a rating are "
        "spread apart slightly</span>"
    )
    fig.update_layout(**layout, legend=dict(title=dict(text="Goal")),
                       margin=dict(l=70, r=30, t=100, b=60))
    return fig


# --- Lead time ------------------------------------------------------------------------------

MIN_BAR_SPAN = 0.012  # shortest drawn bar, as a fraction of the date range on screen


def fig_lead_time_stages(lead_df, title="Project turnaround", pause_notes=None, period_start=None):
    """One row per project on a date axis, split into two stages: waiting (first contact ->
    work started) and working, the latter drawn as the *formal/Timesheet* record -- Begining ->
    Closing Day, or -> today while not yet administratively closed (`bar_end`/`admin_done`
    from kd.lead_time_table) -- since that's the record kept by others, not derived from the
    personal time log. With only a handful of projects a distribution would be meaningless,
    so this shows every project individually -- and it still reads at 20+ rows. Rows flagged
    as bad-date by lead_time_table are excluded (the caller reports them).
    When the rows carry time-log `gaps` (see kd.lead_time_table), each pause is drawn week by
    week over the working bar -- a 2+-week pause isn't one segment but one per week, each
    with its own note and forgiveness, since kd.lead_time_table splits every gap that way
    (gap_weeks) before looking up `pause_notes`
    ({project: {week-start ISO: {"note", "forgive_working", "forgive_total"}}}). That's how a
    stopped-and-restarted project doesn't read as continuous work, and how one week of a
    multi-week pause can be forgiven while another isn't. Every week's tooltip always carries
    two lines regardless of state: the reason (or "No reason given yet" when none was
    entered) and the forgiveness status ("Not forgiven -- still counts in both medians", or
    which median(s) it's excused from) -- so hovering never comes up blank just because a
    pause hasn't been annotated or forgiven. A week ticked forgiven from either median is its
    own legend entry ("Paused (forgiven)") and draws hatched -- but the same solid gray fill
    as a plain pause, not faded toward white the way Internal mutes its (much more saturated)
    color, since lead_time_summary excuses its days from whichever median(s) it was forgiven
    for the same way. The hovertext names which one(s), since a week can now be forgiven from
    Typical time to deliver (effective working time), Typical total turnaround to user, both,
    or neither.
    The two *real* dates -- as opposed to the bar's formal ones -- draw as diamonds on the
    row: a solid black diamond at `real_start` (first week with logged hours: when work
    *really* began, before or after the tracker's Begining), and a hollow black diamond at
    `report` (Final Report Sent: when the deliverable *really* went out, before or after
    Closing Day). Hollow vs. solid marks end vs. start; both stay black since both are the
    same kind of thing -- the real-world date -- next to the bar's formal one.
    Internal projects draw faded + hatched across both stages -- the same visual language
    as an inherited wait, in blue rather than orange -- because lead_time_summary leaves
    them out of the medians.
    Every hovertext also carries the project's `description` (Short Description), when set.
    A span too short to see at this zoom is widened to MIN_BAR_SPAN (tooltips keep the real
    figure), so a project delivered in a day still shows up instead of vanishing.
    Rows are ordered by Register Project, earliest first. `period_start` (the reporting
    year's own 15 Oct boundary), when given and inside the drawn span, gets a dotted vline
    alongside the dashed "today" one."""
    fig = go.Figure()
    clean = lead_df[lead_df["flag"] == ""] if len(lead_df) else lead_df
    if not len(clean):
        _empty(fig, "No projects with usable dates yet")
        fig.update_xaxes(visible=False)
        fig.update_yaxes(visible=False)
        fig.update_layout(**base_layout(title, width=950, height=240))
        return fig

    # Earliest Register Project first (first_contact as a tiebreaker when two projects
    # registered the same day) -- so the chart reads chronologically top-to-bottom rather
    # than by whichever project happened to make first contact earliest.
    clean = clean.sort_values(["register", "first_contact"], ascending=True).copy()
    ms = 86_400_000  # one day

    # The chart's right edge: normally the latest bar_end (the formal bar), but the `report`
    # diamond can sit past that when a report trailed Closing Day -- an anomaly, but the
    # axis still has to stretch to it, or the marker draws off the visible range.
    right_edge = clean["bar_end"].max() if "bar_end" in clean.columns else clean["work_end"].max()
    if "report" in clean.columns and clean["report"].notna().any():
        right_edge = max(right_edge, clean["report"].max())

    # Shortest bar the eye can still catch, in days -- taken as a fraction of the range the
    # chart actually covers rather than a fixed number of days, so it stays about the same
    # number of pixels whether what's on screen spans a year or a month.
    span = max(1, (right_edge - clean["first_contact"].min()).days)
    min_days = max(1.0, span * MIN_BAR_SPAN)
    today = pd.Timestamp.now().normalize()

    def widths(days, keep_zero=True):
        """Bar lengths in ms: the real days, widened to `min_days` where the bar would be
        too thin to see. `keep_zero=True` leaves a genuine zero-day span at zero -- drawing
        a several-day wait where there was none would read as a delay that never happened;
        the working stage passes False, since a project delivered the same day it started
        did do the work and should still get a mark. Tooltips always show the real days."""
        return [0 if (keep_zero and d <= 0) else max(d, min_days) * ms for d in days]

    def flag_col(name):
        return (clean[name].fillna(False).astype(bool) if name in clean.columns
                else pd.Series(False, index=clean.index))

    def desc_line(desc):
        """'<br>Short description' when there is one, else '' -- appended to every hover
        below so a row reads as a project, not just a tag."""
        return f"<br>{desc}" if pd.notna(desc) and str(desc).strip() else ""

    # Inherited projects get their waiting span faded + hatched: that time (first meeting /
    # registration until Begining) ran under the project's previous owner, so it shouldn't
    # read with the same visual weight as waiting that was actually ours. Internal projects
    # get the same treatment across *both* stages -- they're out of the medians entirely
    # (see kd.lead_time_summary), so the row should read as context, not as a measurement.
    clean["_inherited"], clean["_internal"] = flag_col("inherited"), flag_col("internal")
    regular = clean[~clean["_internal"]]

    def muted_marker(color):
        """Faded + hatched: present, but visibly not a measurement. `color` keys which kind
        it is -- orange for a wait that ran under a previous owner, blue for an internal
        project. The hatch, not the hue, is what says 'not counted'."""
        return dict(color=_rgba(color, 0.18), cornerradius=4,
                    line=dict(color=TL_SURFACE, width=2),
                    pattern=dict(shape="/", fgcolor=color, solidity=0.3, size=7))

    for is_inh, name in ((False, "Waiting to start"), (True, "Waiting (inherited)")):
        sub = regular[regular["_inherited"] == is_inh]
        if not len(sub):
            continue
        marker = (muted_marker(WORKLOAD_COLOR) if is_inh else
                  dict(color=WORKLOAD_COLOR, cornerradius=4, line=dict(color=TL_SURFACE, width=2)))
        fig.add_trace(go.Bar(
            y=[_wrap_label(t, 20) for t in sub["Project tag"]],
            base=sub["first_contact"], x=widths(sub["waiting_days"]),
            orientation="h", name=name, marker=marker,
            hovertext=[f"<b>{t}</b>{desc_line(desc)}<br>Waiting {d} day{'' if d == 1 else 's'}<br>"
                       f"{f.strftime('%d %b %Y')} → {s.strftime('%d %b %Y')}"
                       + ("<br><i>Inherited project — this span ran under its previous owner</i>"
                          if is_inh else "")
                       for t, desc, d, f, s in zip(sub["Project tag"], sub["description"], sub["waiting_days"],
                                                    sub["first_contact"], sub["start"])],
            hoverinfo="text",
        ))

    bar_days = (clean["bar_end"] - clean["start"]).dt.days
    for done, name, color in ((True, "Working (closed)", FINISHED_COLOR),
                              (False, "Working (open)", RECEIVED_COLOR)):
        sub = regular[regular["admin_done"] == done]
        if not len(sub):
            continue
        sub_days = bar_days.loc[sub.index]
        fig.add_trace(go.Bar(
            y=[_wrap_label(t, 20) for t in sub["Project tag"]],
            base=sub["start"], x=widths(sub_days, keep_zero=False),
            orientation="h", name=name,
            marker=dict(color=color, cornerradius=4, line=dict(color=TL_SURFACE, width=2)),
            hovertext=[f"<b>{t}</b>{desc_line(desc)}<br>{'Closed in' if done else 'Open for'} "
                       f"{d} day{'' if d == 1 else 's'} (Begining → Closing Day)<br>"
                       f"{s.strftime('%d %b %Y')} → {e.strftime('%d %b %Y')}"
                       + ("" if done else (" (today)" if e == today else " (end of period)"))
                       for t, desc, d, s, e in zip(sub["Project tag"], sub["description"], sub_days,
                                                    sub["start"], sub["bar_end"])],
            hoverinfo="text",
        ))

    # Internal projects: one muted style over the whole row, one legend entry. The working
    # trace carries the legend, because a zero-day wait draws nothing to hang it on.
    internal = clean[clean["_internal"]]
    if len(internal):
        internal_bar_days = bar_days.loc[internal.index]
        for stage, base, days, end, keep_zero, legend in (
            ("Waiting", internal["first_contact"], internal["waiting_days"],
             internal["start"], True, False),
            ("Working", internal["start"], internal_bar_days,
             internal["bar_end"], False, True),
        ):
            fig.add_trace(go.Bar(
                y=[_wrap_label(t, 20) for t in internal["Project tag"]],
                base=base, x=widths(days, keep_zero=keep_zero), orientation="h",
                name="Internal project (not in the medians)", legendgroup="internal",
                showlegend=legend, marker=muted_marker(RECEIVED_COLOR),
                hovertext=[f"<b>{t}</b>{desc_line(desc)}<br>{stage} {d} day{'' if d == 1 else 's'}<br>"
                           f"{b.strftime('%d %b %Y')} → {e.strftime('%d %b %Y')}"
                           "<br><i>Internal project — no external user waiting on it, so "
                           "it stays out of the turnaround medians</i>"
                           for t, desc, d, b, e in zip(internal["Project tag"], internal["description"],
                                                        days, base, end)],
                hoverinfo="text",
            ))

    if "gaps" in clean.columns:
        # Drawn week by week, not one segment per whole pause: kd.lead_time_table splits
        # every gap into its individual weeks (gap_weeks) and looks up each week's own
        # note/forgive_working/forgive_total, so a 2-week pause can have one week forgiven
        # and the other not -- each draws its own hatched-or-solid segment and hovers with
        # its own text. A forgiven week draws hatched -- but the same solid gray fill as a
        # plain pause, not faded toward white the way Internal/Inherited mute their (much
        # more saturated) colors: TL_BASELINE is already a pale, understated gray, so fading
        # it further the same way would read as "this bar vanished," not "this bar is
        # excused." The hatch lines alone are the signal here. Every tooltip always carries
        # a reason line and a forgiveness line, even when neither applies, so hovering never
        # comes up blank.
        #
        # One go.Bar trace PER WEEK, not one trace per forgiveness-state holding every week:
        # a multi-week pause puts the same project on several rows of one trace, and
        # Plotly's hover lookup -- keyed to the nearest point on a categorical axis -- only
        # ever resolved to the first point at a repeated category, leaving every later week
        # silently unhoverable no matter the barmode/hovermode. A trace can't collide with
        # itself this way when it holds exactly one point, so each week gets its own trace;
        # `legendgroup` plus `showlegend` on only the first keeps the legend down to the
        # usual two entries ("Paused" / "Paused (forgiven)"), and clicking either still
        # toggles every week in that group at once.
        legend_shown = {False: False, True: False}
        # ...and even then the pause bar still loses the *tooltip* to the working bar it sits
        # on: Plotly scores a bar hover by how near the cursor is to that bar's END, so a
        # week-wide pause only wins where its own end is nearer than the working bar's --
        # which is why the reason only ever showed on whichever pause sat closest to the end
        # of its project's bar, and never on the last one. `pause_hover` collects an
        # invisible scatter point per day of every paused week; a scatter hover is scored by
        # plain pixel distance to the point, so the week actually under the cursor always
        # wins, anywhere across it. It carries the same text the bar does.
        pause_hover = {"x": [], "y": [], "text": []}
        for _, r in clean.iterrows():
            for g in (r["gaps"] or []):
                weeks_detail = g.get("weeks_detail") or [g]
                multi = len(weeks_detail) > 1
                for i, w in enumerate(weeks_detail, start=1):
                    forgiven = bool(w.get("forgiven"))
                    fw, ft = bool(w.get("forgiven_working")), bool(w.get("forgiven_total"))
                    excused = (", ".join(filter(None, [
                                   "effective working time" if fw else "",
                                   "total turnaround to user" if ft else "",
                               ])))
                    note = w.get("note") or (pause_notes or {}).get(r["Project tag"], {}).get(
                        w["start"].date().isoformat(), {}).get("note", "")
                    forgive_line = (f"Forgiven from: {excused}" if forgiven
                                     else "Not forgiven — still counts in both medians")
                    span_line = (f"Week {i} of {len(weeks_detail)} in a {g['weeks']}-week pause"
                                 if multi else
                                 f"Paused {g['weeks']} week{'' if g['weeks'] == 1 else 's'}")
                    week_days = (w["end"] - w["start"]).days + 1
                    text = (f"<b>{r['Project tag']}</b>{desc_line(r.get('description'))}<br>"
                            f"{span_line} — no hours logged<br>"
                            f"{w['start'].strftime('%d %b %Y')} → {w['end'].strftime('%d %b %Y')}<br>"
                            f"<i>{note if note else 'No reason given yet'}</i><br>"
                            f"<i>{forgive_line}</i>")
                    name = "Paused (forgiven)" if forgiven else "Paused"
                    fig.add_trace(go.Bar(
                        y=[_wrap_label(r["Project tag"], 20)], base=[w["start"]],
                        x=[week_days * ms], orientation="h", name=name, legendgroup=name,
                        showlegend=not legend_shown[forgiven],
                        marker=dict(color=TL_BASELINE, cornerradius=4,
                                    line=dict(color=TL_SURFACE, width=2),
                                    pattern=dict(shape="/" if forgiven else "", fgcolor=TL_INK_MUTED,
                                                solidity=0.35, size=7)),
                        hovertext=[text], hoverinfo="text",
                    ))
                    legend_shown[forgiven] = True
                    for d in range(week_days):
                        pause_hover["x"].append(w["start"] + pd.Timedelta(days=d, hours=12))
                        pause_hover["y"].append(_wrap_label(r["Project tag"], 20))
                        pause_hover["text"].append(text)

        if pause_hover["x"]:
            fig.add_trace(go.Scatter(
                x=pause_hover["x"], y=pause_hover["y"], mode="markers", showlegend=False,
                marker=dict(size=1, color="rgba(0,0,0,0)"),
                hovertext=pause_hover["text"], hoverinfo="text",
            ))

    if "real_start" in clean.columns:
        sub = clean[clean["real_start"].notna()]
        if len(sub):
            pre_log_col = sub["pre_log"] if "pre_log" in sub.columns else pd.Series(False, index=sub.index)
            deltas = [(rs - s).days for rs, s in zip(sub["real_start"], sub["start"])]
            hovertext = []
            for t, rs, d, pl in zip(sub["Project tag"], sub["real_start"], deltas, pre_log_col):
                if pl:
                    # No log evidence reaches this far back -- real_start is the tracker's
                    # own Begining, a known date rather than one measured from hours logged.
                    hovertext.append(f"<b>{t}</b><br>Already underway by {rs.strftime('%d %b %Y')} "
                                      "(the tracker's Begining) -- before the time log began, "
                                      "so there's no earlier evidence to show")
                else:
                    hovertext.append(f"<b>{t}</b><br>First hours logged in the week of "
                                      f"{rs.strftime('%d %b %Y')}<br>"
                                      + ("same week as the tracker's start" if abs(d) < 7 else
                                         f"{abs(d)} days {'before' if d < 0 else 'after'} the tracker's start"))
            fig.add_trace(go.Scatter(
                x=sub["real_start"], y=[_wrap_label(t, 20) for t in sub["Project tag"]],
                mode="markers", name="Really working (time log)",
                marker=dict(symbol="diamond", size=11, color=TL_INK_PRIMARY,
                            line=dict(color=TL_SURFACE, width=1.5)),
                hovertext=hovertext,
                hoverinfo="text",
            ))

    if "report" in clean.columns:
        sub = clean[clean["report"].notna()]
        if len(sub):
            deltas = [((r - c).days if pd.notna(c) else None)
                      for r, c in zip(sub["report"], sub["closing_raw"])]
            fig.add_trace(go.Scatter(
                x=sub["report"], y=[_wrap_label(t, 20) for t in sub["Project tag"]],
                mode="markers", name="Final report sent (real)",
                marker=dict(symbol="diamond-open", size=11, color=TL_INK_PRIMARY,
                            line=dict(color=TL_INK_PRIMARY, width=2)),
                hovertext=[f"<b>{t}</b><br>Final report sent: {r.strftime('%d %b %Y')}"
                           + ("" if d is None else
                              "<br>Same day as Closing Day" if d == 0 else
                              f"<br>{abs(d)} day{'' if abs(d) == 1 else 's'} "
                              f"{'before' if d < 0 else 'after'} Closing Day")
                           for t, r, d in zip(sub["Project tag"], sub["report"], deltas)],
                hoverinfo="text",
            ))

    # The reporting year's own start (15 Oct) -- only when it actually falls inside the
    # span being drawn, same reasoning as "today" below.
    if period_start is not None and clean["first_contact"].min() <= period_start <= right_edge:
        fig.add_vline(x=period_start, line=dict(color=TL_BASELINE, width=1, dash="dot"))
        fig.add_annotation(x=period_start, y=1.02, yref="paper",
                           text=period_start.strftime("%d %b"), showarrow=False,
                           font=dict(color=TL_INK_MUTED, size=11), yanchor="bottom")

    # "today" only belongs here while it falls inside the span being drawn. For a closed
    # reporting period it sits months to the right, and marking it would stretch the axis
    # out past the period just to label a date the review doesn't cover.
    if clean["first_contact"].min() <= today <= right_edge:
        fig.add_vline(x=today, line=dict(color=TL_BASELINE, width=1, dash="dash"))
        fig.add_annotation(x=today, y=1.02, yref="paper", text="today", showarrow=False,
                           font=dict(color=TL_INK_MUTED, size=11), yanchor="bottom")

    # type="date" is required, not cosmetic: the bars carry numeric day-lengths in `x` and
    # their dates in `base`, so plotly.js autotypes this axis as linear, fails to parse the
    # date bases, and draws every bar from 0. (px.timeline forces the same thing.)
    # Close the axis on the data rather than letting plotly autorange: it pads a few weeks
    # past the last bar, and for a closed reporting period (whose bars already stop at the
    # period end) that padding reads as calendar the review doesn't cover.
    left_pad = pd.Timedelta(days=max(2, round(span * 0.02)))
    fig.update_xaxes(type="date", showgrid=True, gridcolor=TL_GRID, tickformat="%d %b",
                     range=[clean["first_contact"].min() - left_pad, right_edge])
    fig.update_yaxes(showgrid=False, tickfont=dict(size=12, color=TL_INK_SECONDARY))
    fig.update_layout(
        **base_layout(title, width=950, height=max(260, 120 + 34 * len(clean))),
        # "overlay", not "stack": every bar trace here sets its own explicit `base` (an
        # absolute date), so nothing actually needs Plotly's stacking math -- these bars are
        # positioned, not accumulated. "stack" matters because a multi-week pause puts
        # several bars at the *same* y-category (the same project) within one trace (the
        # "Paused"/"Paused (forgiven)" trace), and Plotly's stack bookkeeping is built around
        # one value per category per trace: with a repeated category it only keeps the first
        # occurrence hoverable, silently dropping the rest -- exactly why only the first week
        # of a multi-week pause ever showed a tooltip. "overlay" has no such per-category
        # bookkeeping, so every week's own segment stays independently hoverable.
        barmode="overlay", bargap=0.35, margin=dict(l=10, r=30, t=80, b=40),
        legend=dict(orientation="h", yanchor="bottom", y=1.04, xanchor="right", x=1),
        hovermode="closest",
    )
    return fig


# --- Tools & AI Skills page ----------------------------------------------------------------

HOVER_NAME_LIMIT = 12  # keep a tooltip readable when a category holds many tools
HOVER_TASK_LIMIT = 10  # ditto for a project's task list in the timeline tooltip


def fig_tools_counts(series, title, color, names=None, empty_text="No tools yet"):
    """Horizontal count-per-value bars for one dimension of the tools inventory (Type of
    tool / Use / Project Origin). Single series, one hue -- the title names it, counts are
    direct-labeled at the bar ends. Pass `names` (the parallel Name column) to list which
    tools make up each bar in its tooltip."""
    cleaned = series.astype(str).str.strip().replace({"": "—", "nan": "—", "None": "—"})
    counts = cleaned.value_counts().sort_values(ascending=True)

    members = {}
    if names is not None:
        for category, name in zip(cleaned, names.astype(str)):
            members.setdefault(category, []).append(name.strip())

    def hover_for(category, count):
        head = f"<b>{category}</b><br>{count} tool{'s' if count != 1 else ''}"
        listed = members.get(category, [])
        if not listed:
            return head
        shown = listed[:HOVER_NAME_LIMIT]
        body = "<br>".join(f"• {n}" for n in shown)
        if len(listed) > len(shown):
            body += f"<br>• …and {len(listed) - len(shown)} more"
        return f"{head}<br>{body}"

    fig = go.Figure()
    if len(counts):
        fig.add_trace(go.Bar(
            x=counts.values, y=[_wrap_label(v, 22) for v in counts.index], orientation="h",
            marker=dict(color=color, cornerradius=4),
            text=counts.values, textposition="outside", textfont=dict(color=TL_INK_SECONDARY, size=12),
            hovertext=[hover_for(v, c) for v, c in counts.items()],
            hoverinfo="text",
        ))
        fig.update_xaxes(visible=False, range=[0, counts.max() * 1.25])
    else:
        _empty(fig, empty_text)
        fig.update_xaxes(visible=False)
        fig.update_yaxes(visible=False)
    fig.update_yaxes(showgrid=False, tickfont=dict(size=12, color=TL_INK_SECONDARY))
    fig.update_layout(
        **base_layout(title, width=420, height=max(240, 90 + 34 * len(counts))),
        margin=dict(l=10, r=20, t=60, b=20), bargap=0.35, showlegend=False,
    )
    return fig


def fig_all_projects_timeline(all_tasks, project_names=None,
                               title="Predicted timeline — all special projects",
                               axis_range=None):
    """Overview companion to fig_task_timeline: one bar per special project, spanning its
    first planned task date to its predicted completion (the latest date still outstanding),
    labelled with done/total tasks. Status is encoded as complete / on track / overdue --
    colour plus the label, never colour alone. Projects with no dated tasks are skipped,
    since there is nothing to place on a date axis."""
    today = pd.Timestamp.now().normalize()
    names = list(project_names) if project_names is not None else list(all_tasks)

    def month_start(ts):
        return pd.Timestamp(ts.year, ts.month, 1)

    def month_end(ts):
        return month_start(ts) + pd.offsets.MonthEnd(1)

    def ts(value):
        parsed = pd.to_datetime(value, errors="coerce")
        return None if pd.isna(parsed) else parsed

    rows = []
    for name in names:
        tasks = all_tasks.get(name, [])
        # Each dated task contributes its planned start (when it has one) and its planned
        # finish; a task with only one of the two still places the project on the axis.
        dated = [(t, ts(t.get("start")), ts(t.get("due"))) for t in tasks]
        dated = [(t, a, b) for t, a, b in dated if a is not None or b is not None]
        if not dated:
            continue
        # Where each task sits earliest: its start if planned, otherwise its finish date.
        anchors = [a if a is not None else b for _, a, b in dated]
        dues = [b for _, _, b in dated if b is not None]
        pending = [b for t, _, b in dated if b is not None and not t.get("done")]
        total, done = len(tasks), sum(1 for t in tasks if t.get("done"))
        predicted = max(pending) if pending else (max(dues) if dues else max(anchors))
        status = ("Complete" if done == total else
                  "Overdue" if predicted < today else "On track")
        rows.append({
            "name": name,
            # Snap to whole months: a bar begins at the start of the month its first task
            # is planned to start in and runs to the end of the month it should finish in,
            # so every bar lines up with the month gridlines rather than an arbitrary day.
            "start": month_start(min(anchors)), "end": month_end(predicted),
            "first": min(anchors), "predicted": predicted,
            "done": done, "total": total, "status": status,
            "tasks": sorted(dated, key=lambda r: r[1] if r[1] is not None else r[2]),
        })

    fig = go.Figure()
    if not rows:
        _empty(fig, "No special project has planned task dates yet")
        fig.update_xaxes(visible=False)
        fig.update_yaxes(visible=False)
        fig.update_layout(**base_layout(title, width=950, height=240))
        return fig

    rows.sort(key=lambda r: r["end"], reverse=True)
    ms = 86_400_000
    colors = {"Complete": TL_GOOD, "On track": RECEIVED_COLOR, "Overdue": TL_CRITICAL}

    def hover_for(r):
        head = (f"<b>{r['name']}</b><br>{r['done']}/{r['total']} tasks done · {r['status']}"
                f"<br>{r['start'].strftime('%b %Y')} → {r['predicted'].strftime('%b %Y')}<br>")
        lines = []
        for task, start, due in r["tasks"][:HOVER_TASK_LIMIT]:
            mark = "✓" if task.get("done") else "•"
            text = (task.get("text") or "").strip() or "(untitled task)"
            when = (f"{start.strftime('%d %b')}–{due.strftime('%d %b')}"
                    if start is not None and due is not None
                    else (start if start is not None else due).strftime("%d %b"))
            lines.append(f"{mark} {when} — {text}")
        if len(r["tasks"]) > HOVER_TASK_LIMIT:
            lines.append(f"• …and {len(r['tasks']) - HOVER_TASK_LIMIT} more")
        return head + "<br>".join(lines)

    for status, color in colors.items():
        sub = [r for r in rows if r["status"] == status]
        if not sub:
            continue
        fig.add_trace(go.Bar(
            y=[_wrap_label(r["name"], 26) for r in sub], base=[r["start"] for r in sub],
            x=[(r["end"] - r["start"]).days * ms for r in sub], orientation="h", name=status,
            marker=dict(color=color, cornerradius=4, line=dict(color=TL_SURFACE, width=2)),
            text=[f"{r['done']}/{r['total']}" for r in sub], textposition="outside",
            textfont=dict(size=11, color=TL_INK_SECONDARY), cliponaxis=False,
            hovertext=[hover_for(r) for r in sub], hoverinfo="text",
        ))

    fig.add_vline(x=today, line=dict(color=TL_BASELINE, width=1, dash="dash"))
    fig.add_annotation(x=today, y=1.02, yref="paper", text="today", showarrow=False,
                        font=dict(color=TL_INK_MUTED, size=11), yanchor="bottom")

    # Whole-month axis: a gridline and a label on the 1st of each month (the label marks
    # where the month starts, not the middle of a band), spanning `axis_range` when the
    # caller pins it to a reporting year, otherwise just the months actually in play.
    axis_start, axis_end = min(r["start"] for r in rows), max(r["end"] for r in rows)
    if axis_range:
        # The reporting year pins where the axis starts and sets its minimum width, but it
        # only ever widens it: a project planned to finish in a later year has to stay on
        # the chart, so the window grows to the last planned month instead of clipping it.
        axis_start = min(axis_start, month_start(pd.Timestamp(axis_range[0])))
        axis_end = max(axis_end, month_end(pd.Timestamp(axis_range[1])))
    # One label per month only while they still fit; past ~2 years the angled "Mon YYYY"
    # labels collide, so thin them to every other / every third month. Gridlines stay
    # monthly either way, so the bars keep lining up with month boundaries.
    months = (axis_end.year - axis_start.year) * 12 + axis_end.month - axis_start.month + 1
    dtick = "M1" if months <= 26 else "M2" if months <= 48 else "M3"
    fig.update_xaxes(
        type="date",  # REQUIRED: the bars carry numeric durations in `x` (the dates live in
        # `base`), so plotly.js would autotype this axis as linear, fail to parse the date
        # bases, and draw every bar from the origin. px.timeline forces this for the same reason.
        showgrid=True, gridcolor=TL_GRID, dtick=dtick, tickformat="%b %Y",
        range=[axis_start, axis_end], ticks="outside", tickangle=-45,
        tickcolor=TL_GRID, tickfont=dict(size=10, color=TL_INK_SECONDARY),
        minor=dict(dtick="M1", showgrid=True, gridcolor=TL_GRID),
    )
    fig.update_yaxes(showgrid=False, tickfont=dict(size=12, color=TL_INK_SECONDARY))
    fig.update_layout(
        **base_layout(title, width=950, height=max(300, 150 + 36 * len(rows))),
        # "overlay", never "stack": stacking makes Plotly lay bars end-to-end from the axis
        # origin and ignore each bar's `base`, so every project started at the same x
        # instead of in its own month. Each project appears in exactly one trace anyway.
        barmode="overlay", bargap=0.35,
        margin=dict(l=10, r=60, t=80, b=70),  # room for the angled month labels
        legend=dict(orientation="h", yanchor="bottom", y=1.04, xanchor="right", x=1),
    )
    return fig


def fig_task_timeline(tasks, project_name):
    """Predicted timeline for one special project, one row per dated task (soonest first).

    A task with both a planned start and a planned finish is drawn as a bar spanning them;
    one with only a single date stays a milestone dot, so a half-planned checklist still
    reads. Status is encoded as done / planned / overdue -- reserved status colors plus a
    marker symbol or a bar, never color alone -- with a dashed 'today' line."""
    today = pd.Timestamp.now().normalize()

    def ts(value):
        parsed = pd.to_datetime(value, errors="coerce")
        return None if pd.isna(parsed) else parsed

    rows = []
    for t in tasks:
        start, due = ts(t.get("start")), ts(t.get("due"))
        if start is None and due is None:
            continue
        # A task planned to finish before it starts would draw a negative-width bar; show it
        # as the span it actually covers rather than silently dropping or inverting it.
        if start is not None and due is not None and start > due:
            start, due = due, start
        rows.append({"text": t.get("text") or "(untitled task)", "start": start, "due": due,
                     "done": bool(t.get("done")), "anchor": start if start is not None else due})

    fig = go.Figure()
    if not rows:
        _empty(fig, "Add planned dates to tasks to see the predicted timeline")
        fig.update_xaxes(visible=False)
        fig.update_yaxes(visible=False)
        fig.update_layout(**base_layout(f"Predicted timeline — {project_name}", width=950, height=240))
        return fig

    rows.sort(key=lambda r: r["anchor"])
    seen = {}
    for r in rows:
        label = _wrap_label(r["text"], width=34)
        seen[label] = seen.get(label, 0) + 1
        r["label"] = label + "​" * (seen[label] - 1)  # duplicate task names stay on separate rows

    statuses = {
        "Done ✓": dict(color=TL_GOOD, symbol="circle"),
        "Planned": dict(color=RECEIVED_COLOR, symbol="circle-open"),
        "Overdue !": dict(color=TL_CRITICAL, symbol="diamond"),
    }

    def status_of(r):
        if r["done"]:
            return "Done ✓"
        deadline = r["due"] if r["due"] is not None else r["start"]
        return "Overdue !" if deadline < today else "Planned"

    for r in rows:
        r["status"] = status_of(r)

    ms = 86_400_000  # one day
    shown = set()  # one legend entry per status, whether it first appears as a bar or a dot

    for status, spec in statuses.items():
        group = [r for r in rows if r["status"] == status]
        spans = [r for r in group if r["start"] is not None and r["due"] is not None]
        points = [r for r in group if r not in spans]

        if spans:
            fig.add_trace(go.Bar(
                y=[r["label"] for r in spans], base=[r["start"] for r in spans],
                # +1 day so a task that starts and finishes on the same day is still a
                # visible bar rather than a zero-width sliver.
                x=[((r["due"] - r["start"]).days + 1) * ms for r in spans],
                orientation="h", name=status, legendgroup=status,
                showlegend=status not in shown,
                marker=dict(color=spec["color"], cornerradius=4,
                            line=dict(color=TL_SURFACE, width=2)),
                hovertext=[f"<b>{r['text']}</b><br>{r['start'].strftime('%d %b %Y')} → "
                           f"{r['due'].strftime('%d %b %Y')}"
                           f"<br>{(r['due'] - r['start']).days + 1} day"
                           f"{'' if (r['due'] - r['start']).days == 0 else 's'} · {status}"
                           for r in spans],
                hoverinfo="text",
            ))
            shown.add(status)

        if points:
            fig.add_trace(go.Scatter(
                x=[r["due"] if r["due"] is not None else r["start"] for r in points],
                y=[r["label"] for r in points], mode="markers", name=status,
                legendgroup=status, showlegend=status not in shown,
                marker=dict(size=11, color=spec["color"], symbol=spec["symbol"],
                            line=dict(color=TL_SURFACE, width=2)),
                hovertext=[f"<b>{r['text']}</b><br>"
                           f"{(r['due'] if r['due'] is not None else r['start']).strftime('%d %b %Y')}"
                           f" · {'finish' if r['due'] is not None else 'start'} only · {status}"
                           for r in points],
                hoverinfo="text",
            ))
            shown.add(status)

    fig.add_vline(x=today, line=dict(color=TL_BASELINE, width=1, dash="dash"))
    fig.add_annotation(x=today, y=1.02, yref="paper", text="today", showarrow=False,
                        font=dict(color=TL_INK_MUTED, size=11), yanchor="bottom")

    # type="date" is required: the bars carry numeric day-lengths in `x` with their dates in
    # `base`, so plotly.js would autotype this axis as linear and draw every bar from 0.
    fig.update_xaxes(type="date", showgrid=True, gridcolor=TL_GRID, dtick="M1",
                      tickformat="%b %Y", ticklabelmode="period")
    fig.update_yaxes(autorange="reversed", showgrid=True, gridcolor=TL_GRID,
                      tickfont=dict(size=11, color=TL_INK_SECONDARY))
    height = max(260, 110 + 30 * len(rows))
    fig.update_layout(
        **base_layout(f"Predicted timeline — {project_name}", width=950, height=height),
        barmode="overlay", bargap=0.4,
        margin=dict(l=10, r=30, t=70, b=40),
        legend=dict(orientation="h", yanchor="bottom", y=1.04, xanchor="right", x=1),
    )
    return fig


# --- Gains & Outputs page -------------------------------------------------------------------
# Every chart below shares one visual grammar: Delivered / In use / Potential is a named
# status palette (green / blue / grey -- kd.GAIN_STATE_COLORS / _DARK, never imported fixed
# here, same pattern fig_hours_by_project_task etc. use for category_colors), not three
# arbitrary categorical hues. Potential ALSO gets a "/" hatch on top (the same device
# fig_lead_time_stages uses for a forgiven pause) -- this is NOT just belt and braces: green
# vs. blue is exactly the one pair a red-green colourblind viewer (deuteranopia/protanopia,
# the most common forms) can struggle to tell apart, so the hatch is real redundancy on the
# one state pair that needs it, not decoration. Delivered and In use are both solid; only
# Potential is ever hatched. All three states always get their own legend entry so a chart
# explains its own colors without a caption. (Earlier draft used TL_GOOD/TL_CRITICAL-style
# traffic-light colors and hollow rings for Potential in the dot matrix -- dropped: green reads
# as a status judgement rather than a maturity stage, and a hollow marker in a dot grid reads
# as missing data, not as "potential".)


def _potential_hatch():
    """The Potential state's "/" hatch, built fresh on every call (NOT a frozen module-level
    dict) so it actually follows set_theme() -- a plain `dict(..., fgcolor=TL_INK_MUTED, ...)`
    assigned once at import time bakes in whatever TL_INK_MUTED equals at IMPORT, before any
    page has called set_theme(), and then never changes again no matter how many times the
    theme is switched afterwards (dict values don't track a reassigned global). That exact bug
    is also why the hatch went invisible in light mode after the state palette moved from a
    pale-blue sequential ramp to a true grey: TL_INK_MUTED ("#898781") and the new Potential
    fill ("#8c8a7a") are nearly identical greys (WCAG contrast ~1.0:1), so the hatch lines were
    being drawn in almost exactly the fill's own colour. fgcolor is TL_INK_PRIMARY instead of
    any of the muted inks -- the strongest ink/background contrast this theme has, verified
    >=4.5:1 against the Potential fill in BOTH modes (not just "different enough on paper" --
    rendered and inspected at 1:1 pixels in both themes)."""
    return dict(shape="/", fgcolor=TL_INK_PRIMARY, solidity=0.35, size=7)


_SOLID_HATCH = dict(shape="")
STATE_ORDER = ["Delivered", "In use", "Potential"]

# The Gains sheet's 4 merged group headers, in the order GAIN_GROUPS lists them in --
# Efficiency, Capability, Innovation & visibility, Reach & relationships -- pulled out once as
# the canonical row order for any chart that groups gains thematically, so the thematic split
# (inward-facing vs outward-facing) reads top to bottom instead of being buried in an
# alphabetical or frequency sort. Stays exactly these 4 names regardless of how many gain
# COLUMNS a given load finds (kd.load_expected_gains's gain_columns/gain_groups are read fresh
# from the sheet and can vary; GAIN_GROUPS' set of possible GROUP names does not) -- including
# GAIN_FALLBACK_GROUP, which is one of these 4 by construction.
GAIN_GROUP_ORDER = list(dict.fromkeys(GAIN_GROUPS.values()))


def _capped_list_hover(head, items, limit=HOVER_NAME_LIMIT):
    """`head` (already-built HTML lines) plus a bulleted, length-capped list of names/IDs --
    the same "…and N more" trick fig_tools_counts uses so a gain or flag shared by many
    developments still gets a readable tooltip instead of one giant unbroken block."""
    if not items:
        return head
    shown = items[:limit]
    body = "<br>".join(f"• {item}" for item in shown)
    if len(items) > len(shown):
        body += f"<br>• …and {len(items) - len(shown)} more"
    return f"{head}<br>{body}"


def _group_blocks(labels):
    """[a, a, b, b, b, c] -> [("a", 0, 2), ("b", 2, 5), ("c", 5, 6)] -- the contiguous runs
    in an already-grouped list, as (value, start, end) integer index ranges. Shared by every
    chart that bands a grouped axis (fig_gains_active_potential's rows, fig_gains_matrix's
    columns): both rely on their data already being sorted into blocks, this just finds where
    each block starts and ends so a shape/annotation can be drawn once per block."""
    blocks = []
    start = 0
    labels = list(labels)
    for i in range(1, len(labels) + 1):
        if i == len(labels) or labels[i] != labels[start]:
            blocks.append((labels[start], start, i))
            start = i
    return blocks


def _add_row_group_bands(fig, groups, group_colors, label_xref="paper", label_x=1.02):
    """Bands a horizontal chart's categorical y-axis by `groups` (one value per row, already
    sorted into contiguous blocks): a light wash across the full plot width behind each
    block, a solid boundary line between blocks, and the group's own name in its own colour
    just outside the plot -- so the thematic grouping a chart is already sorted by is
    visible at a glance instead of relying on a caption. Never touches the bars/markers
    themselves, which must keep encoding state (or whatever else) via their own colour --
    this only decorates the row AXIS. Rows whose group isn't in `group_colors` (blank, or an
    unrecognized value) are left undecorated rather than erroring."""
    blocks = _group_blocks(groups)
    for group, start_i, end_i in blocks:
        if not group or group not in group_colors:
            continue
        color = group_colors[group]
        fig.add_shape(
            type="rect", xref="paper", x0=0, x1=1, yref="y",
            y0=start_i - 0.5, y1=end_i - 0.5,
            fillcolor=_rgba(color, 0.12), line=dict(width=0), layer="below",
        )
        fig.add_annotation(
            xref=label_xref, x=label_x, yref="y", y=(start_i + end_i - 1) / 2,
            text=f"<b>{group}</b>", showarrow=False, align="left",
            font=dict(color=color, size=12), xanchor="left", yanchor="middle",
        )
    for i in range(1, len(groups)):
        if groups[i] != groups[i - 1]:
            fig.add_shape(type="line", xref="paper", x0=0, x1=1, yref="y",
                          y0=i - 0.5, y1=i - 0.5, line=dict(color=TL_BASELINE, width=1.5))


def _state_stack_traces(fig, df, label_col, state_colors, group_colors=None):
    """Shared innards of fig_gains_active_potential and fig_audience_outputs: both are a
    horizontal stacked bar, one row per category, split Delivered/In use/Potential with a
    direct-labeled row total -- the only real difference between the two charts is what the
    rows ARE (a gain type vs. an audience/output flag), so the bar-building logic lives once
    here. `df` must carry Group/n_delivered/n_in_use/n_potential/n_total/delivered_projects/
    in_use_projects/potential_projects/label_col; `state_colors` is the page's theme-matched
    {"Delivered": ..., "In use": ..., "Potential": ...} dict (kd.GAIN_STATE_COLORS[_DARK]).
    `group_colors` (optional {Group value: hex}), when given, bands the y-axis via
    _add_row_group_bands using df["Group"] -- fig_gains_active_potential's 4 gain-theme
    blocks, or fig_audience_outputs's single "inward-facing" block. Left out entirely
    (df["Group"] all blank) draws nothing, same as the old group_sep=False."""
    wrapped = [_wrap_label(v, 20) for v in df[label_col]]

    def hover(row, state, n, projects):
        group_line = f"<br>{row['Group']}" if row["Group"] else ""
        head = f"<b>{row[label_col]}</b>{group_line}<br>{GAIN_STATE_LABELS.get(state, state)}: {n}"
        return _capped_list_hover(head, projects)

    state_specs = [
        ("Delivered", "n_delivered", "delivered_projects", _SOLID_HATCH),
        ("In use", "n_in_use", "in_use_projects", _SOLID_HATCH),
        ("Potential", "n_potential", "potential_projects", _potential_hatch()),
    ]
    for state, n_col, proj_col, pattern in state_specs:
        fig.add_trace(go.Bar(
            x=df[n_col], y=wrapped, orientation="h", name=GAIN_STATE_LABELS.get(state, state),
            marker=dict(color=state_colors[state], cornerradius=4,
                        line=dict(color=TL_SURFACE, width=2), pattern=pattern),
            hovertext=[hover(r, state, r[n_col], r[proj_col]) for _, r in df.iterrows()],
            hoverinfo="text",
        ))
    fig.add_trace(go.Scatter(
        x=df["n_total"], y=wrapped, mode="text", text=df["n_total"],
        textposition="middle right", textfont=dict(color=TL_INK_SECONDARY, size=11),
        hoverinfo="skip", showlegend=False,
    ))
    if group_colors:
        _add_row_group_bands(fig, list(df["Group"]), group_colors)

    fig.update_xaxes(title_text="Developments", showgrid=True, gridcolor=TL_GRID)
    fig.update_yaxes(showgrid=False, tickfont=dict(size=12, color=TL_INK_SECONDARY),
                      autorange="reversed")
    fig.update_layout(
        barmode="stack", bargap=0.3,
        legend=dict(orientation="h", yanchor="bottom", y=1.04, xanchor="right", x=1),
        margin=dict(l=10, r=60, t=70, b=40),
    )


def fig_gains_active_potential(gain_summary, state_colors, group_colors):
    """The centrepiece of the Gains page: one row per gain type, split into Delivered / In use
    / Potential. Rows are grouped by theme (GAIN_GROUP_ORDER) rather than sorted by raw count,
    because the count alone hides the actual story -- within each group the biggest gain still
    comes first (n_total descending), but the GROUPING is what makes "efficiency is largely
    banked, everything outward-facing is still ahead" visible at a glance instead of requiring
    the reader to mentally regroup these rows themselves. Works with however many gains
    gain_summary actually has (9, 10, 11, 12, ...) -- nothing here assumes a fixed count any
    more. `state_colors` / `group_colors` are the page's theme-matched kd.GAIN_STATE_COLORS /
    _DARK and kd.GAIN_GROUP_COLORS / _DARK dicts."""
    df = gain_summary.copy()
    group_rank = {g: i for i, g in enumerate(GAIN_GROUP_ORDER)}
    df["_group_rank"] = df["Group"].map(group_rank)
    df = df.sort_values(["_group_rank", "n_total"], ascending=[True, False]).reset_index(drop=True)

    fig = go.Figure()
    if not len(df) or not df["n_total"].sum():
        _empty(fig, "No gains recorded yet")
        fig.update_xaxes(visible=False)
        fig.update_yaxes(visible=False)
        fig.update_layout(**base_layout("Delivered, in use & potential gains", width=950, height=320))
        return fig

    _state_stack_traces(fig, df, "Gain", state_colors, group_colors=group_colors)
    fig.update_layout(
        **base_layout("Delivered, in use & potential gains", width=1120, height=max(340, 90 + 42 * len(df))),
        margin=dict(r=190),
    )
    return fig


def fig_gains_matrix(gains_long, developments, state_colors, gain_columns, gain_groups, group_colors):
    """Developments (rows) x the gain types actually present (columns) as a dot grid -- a dot
    wherever that development delivers that gain. State is a property of the DEVELOPMENT, not
    the individual gain, so every dot in one row shares the same state; sorting Delivered rows
    to the top, then In use, then Potential makes the maturity read top-to-bottom at a glance.
    Every dot is a solid filled marker, colour-only from `state_colors` (the page's theme-matched
    kd.GAIN_STATE_COLORS / _DARK dict) -- deliberately NOT a hollow ring for Potential the way
    an earlier draft had it: a hollow marker in a dot grid reads as missing data, not as
    "potential". Within each state, developments with more gains riding on them sort first,
    since those are the ones where "what does this actually deliver" matters most.

    `gain_columns` (kd.load_expected_gains's result, in sheet order) and `gain_groups`
    ({gain: group}, same source) replace what used to be the fixed kd.GAIN_COLUMNS / a direct
    kd.GAIN_GROUPS lookup -- the column set is read fresh from the workbook on every load (9,
    10, 11, 12 gains, whatever is actually there), so nothing here assumes a count or a position
    any more. `group_colors` is the page's theme-matched kd.GAIN_GROUP_COLORS / _DARK dict."""
    gains_by_id = gains_long.groupby("ID")["Gain"].apply(set).to_dict()
    dev = developments.copy()
    dev["_n_gains"] = dev["ID"].map(lambda i: len(gains_by_id.get(i, set())))
    state_rank = {s: i for i, s in enumerate(STATE_ORDER)}
    dev["_state_rank"] = dev["state"].map(state_rank)
    dev = dev.sort_values(["_state_rank", "_n_gains"], ascending=[True, False]).reset_index(drop=True)

    wrapped_x = [_wrap_label(g, 14) for g in gain_columns]
    # 34, not 26: wide enough that today's longest development names ("Metabolomics Facility
    # Dashboard", "Lipidomics toolkit (metabolomics)") stay on ONE line -- a two-line wrapped
    # label needs roughly double the row's vertical room, which is what was colliding with its
    # neighbours before. The per-row height bump below is the backstop for whatever still does
    # wrap (a future longer name), not the fix on its own.
    wrapped_y = [_wrap_label(p, 34) for p in dev["Project"]]

    by_state = {s: ([], [], []) for s in STATE_ORDER}
    for yi, (_, row) in enumerate(dev.iterrows()):
        gains_here = gains_by_id.get(row["ID"], set())
        xs, ys, hs = by_state[row["state"]]
        for xi, gain in enumerate(gain_columns):
            if gain not in gains_here:
                continue
            state_label = GAIN_STATE_LABELS.get(row["state"], row["state"])
            hover = f"<b>{row['Project']}</b> ({row['Category']})<br>{gain}<br>{state_label}"
            xs.append(wrapped_x[xi]); ys.append(wrapped_y[yi]); hs.append(hover)

    fig = go.Figure()
    if not any(xs for xs, _, _ in by_state.values()):
        _empty(fig, "No gains recorded yet")
        fig.update_xaxes(visible=False)
        fig.update_yaxes(visible=False)
        fig.update_layout(**base_layout("What delivers what", width=950, height=320))
        return fig

    for state in STATE_ORDER:
        xs, ys, hs = by_state[state]
        if not xs:
            continue
        fig.add_trace(go.Scatter(
            x=xs, y=ys, mode="markers", name=GAIN_STATE_LABELS.get(state, state),
            marker=dict(size=13, color=state_colors[state], symbol="circle",
                        line=dict(color=TL_SURFACE, width=1)),
            hovertext=hs, hoverinfo="text",
        ))

    # Column banding: the gains are already in gain_columns order, which is already grouped
    # (Efficiency, Capability, Innovation & visibility, Reach & relationships) -- a wash down
    # each block's columns, a solid header strip naming the group just above the plot, and a
    # boundary line between blocks, so the grouping that's otherwise only implicit in column
    # order reads at a glance. Colour here is group_colors, deliberately never the dots'
    # own colour (state_colors) -- see fig_gains_active_potential for why.
    col_groups = [gain_groups[g] for g in gain_columns]
    header_y0, header_y1 = 1.0, 1.1
    for group, start_i, end_i in _group_blocks(col_groups):
        color = group_colors.get(group)
        if not color:
            continue
        fig.add_shape(type="rect", xref="x", x0=start_i - 0.5, x1=end_i - 0.5, yref="paper",
                      y0=0, y1=1, fillcolor=_rgba(color, 0.08), line=dict(width=0), layer="below")
        fig.add_shape(type="rect", xref="x", x0=start_i - 0.5, x1=end_i - 0.5, yref="paper",
                      y0=header_y0, y1=header_y1, fillcolor=color, line=dict(width=0))
        fig.add_annotation(
            xref="x", x=(start_i + end_i - 1) / 2, yref="paper", y=(header_y0 + header_y1) / 2,
            text=_wrap_label(group, 16), showarrow=False, align="center",
            font=dict(color=_label_on(color), size=10), xanchor="center", yanchor="middle",
        )
    for i in range(1, len(col_groups)):
        if col_groups[i] != col_groups[i - 1]:
            fig.add_shape(type="line", xref="x", x0=i - 0.5, x1=i - 0.5, yref="paper",
                          y0=0, y1=1, line=dict(color=TL_BASELINE, width=1.5))

    fig.update_xaxes(categoryorder="array", categoryarray=wrapped_x, showgrid=True, gridcolor=TL_GRID,
                      tickfont=dict(size=11, color=TL_INK_SECONDARY))
    fig.update_yaxes(categoryorder="array", categoryarray=wrapped_y, showgrid=True, gridcolor=TL_GRID,
                      tickfont=dict(size=11, color=TL_INK_SECONDARY), autorange="reversed")
    fig.update_layout(
        # 36px/row (was 30): the old pitch was sized for a one-line label and collided the
        # moment a name wrapped to two lines (e.g. "Functional enrichment analysis" running
        # into "Lipidomics toolkit (metabolomics)" above it). 36px comfortably fits a two-line
        # 11pt label with clearance even though width=34 above means almost nothing wraps today.
        **base_layout("What delivers what", width=1000, height=max(420, 140 + 36 * len(dev))),
        legend=dict(orientation="h", yanchor="bottom", y=1.2, xanchor="right", x=1),
        margin=dict(l=10, r=20, t=115, b=110),
    )
    return fig


_ADA_OUTPUT_LEVELS = {"Internal ADA", "Internal Worker"}


def fig_audience_outputs(developments, state_colors, ada_color):
    """The 5 boolean audience/output flags (Internal users, External users, Facility use /
    collaboration, Publication potential, Market-equivalent value) PLUS one more row built
    from a different column -- "ADA / Personal", `Output level` in {Internal ADA, Internal
    Worker} -- the audience dimension those 5 flags never actually asked about: not "is there
    an internal user" but "is this output for ADA/Sara herself rather than for anyone it would
    call a 'user' at all." Same Delivered/In use/Potential split as fig_gains_active_potential
    throughout; `state_colors` is the page's theme-matched kd.GAIN_STATE_COLORS / _DARK dict.

    ADA / Personal is always pinned to the FIRST row, not sorted in by its count like the
    other 5 -- the point it makes (inward-facing, as against the Internal/External USERS rows
    right below it) is about what kind of audience it is, not how big it is, and a future count
    change shuffling it mid-pack would bury that contrast. Its bars still split Delivered/In
    use/Potential by the same ramp as every other row here -- recolouring just this row's
    SEGMENTS would break the one visual rule this whole chart (and the gains chart above it)
    relies on, that colour always means maturity. Instead `ada_color` (the page's theme-matched
    kd.ADA_PERSONAL_COLOR / _DARK, TL_PALETTE[1]) marks the row's own IDENTITY: a small colour
    chip baked into its tick label text (not a hand-placed shape -- Plotly auto-sizes the
    left margin around its own tick text, so a shape positioned by guessed paper-coordinates
    would risk clipping or drifting across screen sizes in a way text-in-the-label can't)."""
    flag_cols = [
        "Internal users", "External users", "Facility use / collaboration",
        "Publication potential", "Market-equivalent value",
    ]

    def _row(flag, flagged):
        delivered_rows = flagged[flagged["state"] == "Delivered"]
        in_use_rows = flagged[flagged["state"] == "In use"]
        potential_rows = flagged[flagged["state"] == "Potential"]
        return dict(
            Flag=flag, Group="",
            n_delivered=len(delivered_rows), n_in_use=len(in_use_rows), n_potential=len(potential_rows),
            n_total=len(flagged),
            delivered_projects=list(delivered_rows["Project"]), in_use_projects=list(in_use_rows["Project"]),
            potential_projects=list(potential_rows["Project"]),
        )

    ada_mask = developments["Output level"].isin(_ADA_OUTPUT_LEVELS)
    rows = [_row("ADA / Personal", developments[ada_mask])]
    for col in flag_cols:
        rows.append(_row(col, developments[developments[col]]))
    ada_row, rest = rows[:1], rows[1:]
    rest.sort(key=lambda r: r["n_total"], reverse=True)
    df = pd.DataFrame(ada_row + rest).reset_index(drop=True)

    fig = go.Figure()
    if not df["n_total"].sum():
        _empty(fig, "No audience/output flags set yet")
        fig.update_xaxes(visible=False)
        fig.update_yaxes(visible=False)
        fig.update_layout(**base_layout("Audience & outputs", width=950, height=260))
        return fig

    _state_stack_traces(fig, df, "Flag", state_colors)

    # Override just the ADA/Personal tick label with a colour chip + bold text; every other
    # label is handed back exactly as _state_stack_traces already wrapped it, so this changes
    # nothing about how they render.
    wrapped = [_wrap_label(v, 20) for v in df["Flag"]]
    ticktext = [
        f'<span style="color:{ada_color}">■</span> <b>{w}</b>' if flag == "ADA / Personal" else w
        for flag, w in zip(df["Flag"], wrapped)
    ]
    fig.update_yaxes(tickmode="array", tickvals=wrapped, ticktext=ticktext)

    fig.update_layout(
        **base_layout("Audience & outputs", width=950, height=max(260, 90 + 42 * len(df))),
    )
    return fig


_PRINT_ID_LIMIT = 5  # more ids than this on one side of one row and the bar just states the
# count instead -- printing all of them would overflow the row. Smaller than HOVER_NAME_LIMIT
# (12): a tooltip can afford a scroll-free bulleted list, a bar label sitting next to other
# rows' labels can't.


def _side_text(ids):
    """The actual project ids, printed directly on/beside a reuse bar -- the point of this
    chart is to let the ids be SEEN, not just counted, so this is preferred over a bare number
    whenever there are few enough to stay legible (_PRINT_ID_LIMIT); past that it falls back
    to a plain count, same idea as _capped_list_hover's "...and N more" but for bar text,
    which has no room for a real list at all past a handful of entries."""
    if not ids:
        return ""
    if len(ids) <= _PRINT_ID_LIMIT:
        return ", ".join(ids)
    return f"{len(ids)} projects"


def fig_reuse_both_directions(reuse, state_colors, project_lookup=None):
    """Diverging ("butterfly") bars, one row per development: projects involved in BUILDING it
    (`came_from_projects` -- user-project ids only; a lineage parent named in the same "Came
    from" cell, `came_from_developments`, is a different development, never a user project, so
    it's excluded here exactly like in the chart this replaces) to the LEFT of zero, and
    projects that BENEFIT from it (`serves_project_ids` -- the same user-project-id filter
    mirrored onto the "User projects served" side, for symmetry) to the RIGHT. Replaces the old
    one-sided fig_reuse_origins, which only ever drew the left half -- "built out of" was never
    the whole reuse story, just the half that happened to have data typed in so far.

    Both halves of one row share that development's own state colour (a development is wholly
    one state, same rule as the chart it replaces, so this stays a plain ranked bar per side,
    never a stack); the actual ids are printed directly on each bar (see _side_text) rather
    than left to hover alone, falling back to hover only when a side has too many to print
    legibly -- the whole point of drawing both directions is to let the ids be SEEN.

    `serves_project_ids` is empty for EVERY row in today's workbook (nothing has been typed
    under "User projects served" yet), so the right half renders empty -- deliberately: the
    axis frame stays two-sided and symmetric around zero rather than collapsing to a one-sided
    bar chart just because one side currently has nothing, so "empty, for now" reads as half a
    picture waiting to be filled in rather than as something broken. The page-level caption
    spells this out in words; this function only has to not break when it happens, which a
    plain "sum to 0 on this side -> skip adding a trace for it" guard handles cleanly.

    Rows with nothing on EITHER side are dropped (same spirit as the old chart's notna()
    filter); the rest are sorted by combined involvement (both sides) descending, so the
    developments doing the most reuse work -- in either direction -- lead. `state_colors` is
    the page's theme-matched kd.GAIN_STATE_COLORS / _DARK dict. `project_lookup`
    (kd.build_project_lookup's result, or None) joins each printed id to the real project
    tracker for the HOVER text -- so hovering a bar shows what DNA_032 (say) actually was, not
    just its id; degrades to bare ids with no lookup, same as kd.project_lookup_label."""
    work = reuse.copy()
    # _as_id_list: cheap guard, not a fix for a real bug -- kd._parse_id_list always returns a
    # list, so this is unreachable today, but a bare string here would otherwise iterate
    # character-by-character into one bar-label per letter with no error raised.
    work["_left_ids"] = work["came_from_projects"].map(_as_id_list)
    work["_right_ids"] = work["serves_project_ids"].map(_as_id_list)
    work["_left_n"] = work["_left_ids"].map(len)
    work["_right_n"] = work["_right_ids"].map(len)
    work["_total"] = work["_left_n"] + work["_right_n"]
    df = work[work["_total"] > 0].sort_values("_total", ascending=False).reset_index(drop=True)

    fig = go.Figure()
    if not len(df):
        _empty(fig, "No reuse recorded yet -- neither 'Came from' nor 'User projects served' has any ids")
        fig.update_xaxes(visible=False)
        fig.update_yaxes(visible=False)
        fig.update_layout(**base_layout("Reuse: built from & benefits", width=950, height=260))
        return fig

    wrapped_all = [_wrap_label(n, 24) for n in df["Development / tool"]]

    def hover(name, direction, ids):
        n = len(ids)
        head = f"<b>{name}</b><br>{direction}: {n} user project{'s' if n != 1 else ''}"
        labels = [project_lookup_label(i, project_lookup) for i in ids]
        return _capped_list_hover(head, labels) if labels else f"{head}<br><i>none recorded yet</i>"

    for state, pattern in (
        ("Delivered", _SOLID_HATCH),
        ("In use", _SOLID_HATCH),
        ("Potential", _potential_hatch()),
    ):
        mask = df["state"] == state
        if not mask.any():
            continue
        sub = df[mask]
        sub_wrapped = [w for w, m in zip(wrapped_all, mask) if m]
        left_present = sub["_left_n"].sum() > 0
        right_present = sub["_right_n"].sum() > 0

        if left_present:
            fig.add_trace(go.Bar(
                x=-sub["_left_n"], y=sub_wrapped, orientation="h",
                name=GAIN_STATE_LABELS.get(state, state),
                legendgroup=state, showlegend=True,
                marker=dict(color=state_colors[state], cornerradius=4,
                            line=dict(color=TL_SURFACE, width=2), pattern=pattern),
                text=[_side_text(ids) for ids in sub["_left_ids"]], textposition="outside",
                textfont=dict(color=TL_INK_SECONDARY, size=11), cliponaxis=False,
                hovertext=[hover(name, "Built from", ids)
                           for name, ids in zip(sub["Development / tool"], sub["_left_ids"])],
                hoverinfo="text",
            ))
        if right_present:
            fig.add_trace(go.Bar(
                x=sub["_right_n"], y=sub_wrapped, orientation="h",
                name=GAIN_STATE_LABELS.get(state, state),
                legendgroup=state, showlegend=not left_present,
                marker=dict(color=state_colors[state], cornerradius=4,
                            line=dict(color=TL_SURFACE, width=2), pattern=pattern),
                text=[_side_text(ids) for ids in sub["_right_ids"]], textposition="outside",
                textfont=dict(color=TL_INK_SECONDARY, size=11), cliponaxis=False,
                hovertext=[hover(name, "Benefits", ids)
                           for name, ids in zip(sub["Development / tool"], sub["_right_ids"])],
                hoverinfo="text",
            ))

    # Symmetric axis frame even when the right side is entirely empty (today) -- max_n covers
    # whichever side is bigger, so BOTH sides keep the same visual scale and the zero line
    # stays dead centre. `pad` leaves room for the printed id text to sit past the bar tips
    # without clipping (see cliponaxis=False above).
    max_n = max(int(df["_left_n"].max()), int(df["_right_n"].max()), 1)
    pad = max(4, max_n)
    tick_step = max(1, -(-max_n // 5))  # ceil(max_n / 5): at most ~5 ticks per side
    tick_range = list(range(-max_n, max_n + 1, tick_step))
    if tick_range[-1] != max_n:
        tick_range.append(max_n)

    fig.add_vline(x=0, line_color=TL_BASELINE, line_width=1)
    fig.update_xaxes(
        range=[-(max_n + pad), max_n + pad], tickvals=tick_range, ticktext=[abs(v) for v in tick_range],
        title_text="built out of ←     |     → benefits",
        showgrid=True, gridcolor=TL_GRID, zeroline=False,
    )
    fig.update_yaxes(showgrid=False, tickfont=dict(size=12, color=TL_INK_SECONDARY),
                      categoryorder="array", categoryarray=wrapped_all, autorange="reversed")
    fig.update_layout(
        **base_layout("Reuse: built from & benefits", width=1050, height=max(280, 90 + 34 * len(df))),
        margin=dict(l=10, r=30, t=70, b=60), bargap=0.35,
        legend=dict(orientation="h", yanchor="bottom", y=1.04, xanchor="right", x=1),
    )
    return fig


# --- Lineage tree (development -> development evolution only; see fig_lineage_tree) -----------
# Single flat edge colour -- fig_lineage_tree draws exactly one relationship ("evolved into"),
# unlike the old combined fig_lineage it replaces (which needed 3: "built from user work" and
# "benefits" now live only in fig_reuse_both_directions / the page's development cards, never
# here -- the whole point of the split is that nothing else competes with this one relationship
# on this chart). Same palette slot as the old chart's "evolved into" line (TL_PALETTE[6], its
# most saturated of the three -- GAIN_GROUP_COLORS and ADA_PERSONAL_COLOR don't touch it).
_LINEAGE_EVOLVED_EDGE_COLOR = TL_PALETTE[6]
_LINEAGE_EVOLVED_EDGE_COLOR_DARK = TL_PALETTE_DARK[6]
# Marker shape = kind, independent of both the edge colour above and the state fill below. No
# "User project" entry -- this chart never draws a user-project node (see fig_lineage_tree).
_LINEAGE_KIND_SYMBOLS = {
    "Special Project": "circle",
    "Tool / AI Skill": "diamond",   # also used for an "untracked" lineage parent -- see
                                     # _lineage_resolve_parent
}


def _ordinal(n):
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _depth_col_label(depth):
    """x-axis tick text for one development column -- "Depth 0"/"Depth 1" is this function's
    OWN internal vocabulary (depth_of, dev_col) leaking into the UI; a reader has no reason to
    know what "depth" means here. depth 0 (no development parent of its own) reads as plain
    "Developments"; every column past it names the RELATIONSHIP that got it there instead of
    a number -- "Evolved into" for one hop, "Evolved into (Nth step)" for N, so it still reads
    correctly whether there's 1, 2, or 5 development columns."""
    if depth == 0:
        return "Developments"
    if depth == 1:
        return "Evolved into"
    return f"Evolved into<br>({_ordinal(depth)} step)"


def _norm(s):
    return str(s).strip().lower()


def _lineage_resolve_parent(label, dev_by_id, dev_by_name):
    """One label from reuse["came_from_developments"] -> (node_id, display_name, kind, state).
    kpi_data already resolved the raw "Came from" token to one of: this workbook's own ID
    (e.g. "SP01"), a live tool/Special-Project display name that may have NO row here at all
    (e.g. "motif-scan-from-github" -- a real tool, just not one with its own gains tracked),
    or -- if nothing matched at load time -- the raw text as typed. Try an ID match first,
    then a name match against this workbook's own Project column; anything else becomes an
    "untracked" node: real, just with no Category/state of its own, so it draws as a neutral
    Tool/AI-Skill-shaped node rather than being silently dropped.

    `dev_by_name` is keyed by every kd._name_variants() spelling of each development's Project
    column, not just its own literal text -- kd.load_expected_gains may have already resolved
    the raw "Came from" token to the LIVE dashboard's spelling via NAME_ALIASES (e.g. "Pipeline"
    -> "OMICs Pipelines" once that rename lands in Special_Projects_Ratings.xlsx but before
    anyone edits this read-only workbook's own Project cell to match) -- without the alias
    applied here too, a tracked development would wrongly fall through to "untracked" the
    moment its two name spellings disagree, discarding its real Category/state for no reason
    other than the workbook and the ratings sheet being mid-rename."""
    upper = str(label).strip().upper()
    if upper in dev_by_id:
        row = dev_by_id[upper]
        kind = "Special Project" if row["Category"] == "Special Project" else "Tool / AI Skill"
        return upper, row["Project"], kind, row["state"]
    norm = _norm(label)
    if norm in dev_by_name:
        row = dev_by_name[norm]
        kind = "Special Project" if row["Category"] == "Special Project" else "Tool / AI Skill"
        return row["ID"], row["Project"], kind, row["state"]
    return f"untracked::{norm}", str(label), "Tool / AI Skill", None


def fig_lineage_tree(developments, reuse, state_colors, project_lookup=None):
    """Left-to-right layered tree of development -> development evolution ONLY -- no
    user-project id anywhere on this chart. Replaces the old combined fig_lineage, which drew
    "built from user work" (14 edges in today's workbook) and "benefits" (0) in the same
    picture as "evolved into" (also 0, but the one relationship this chart exists to surface):
    the 14 reuse edges visually swamped the handful of lineage ones, and the column layout was
    role-based, so the same KIND of entity (a Special Project, say) split across two columns
    purely depending on whether it happened to have a parent. Splitting it out means every
    node and edge here is part of an evolution chain, full stop -- "built from"/"benefits" now
    live only in fig_reuse_both_directions and the page's per-development cards (see
    pages/5_Gains.py).

    Columns = lineage DEPTH, not role: depth 0 is a development/tool with no development
    parent of its own (via `came_from_developments`); depth N is 1 + max(depth(parents)) --
    same cycle-safe recursion as the old fig_lineage (a node still mid-calculation counts as
    depth 0 rather than recursing forever, guarding against a malformed workbook that names a
    cycle). A chain like "motif-scan-from-github -> FT Motif Search" reads as exactly two
    nodes, one column apart, joined by one arrow.

    Two independent encodings, same "colour always means one thing" rule as the rest of this
    page:
      - SHAPE = kind (circle Special Project / diamond Tool-AI-Skill) -- _LINEAGE_KIND_SYMBOLS.
      - FILL = state (`state_colors`, the page's theme-matched kd.GAIN_STATE_COLORS / _DARK
        dict) for a tracked development; a flat neutral (TL_BASELINE) for an "untracked"
        lineage parent (a real tool/Special Project named under some development's Came from
        that has no row of its own in this workbook, e.g. "motif-scan-from-github" -- see
        _lineage_resolve_parent), which has no Delivered/In use/Potential state to show.
    There's only one relationship left to draw (no edge-colour legend needed): a single flat
    "evolved into" colour (_LINEAGE_EVOLVED_EDGE_COLOR), drawn as a real annotation ARROW (not
    a plain Scatter line) so direction always reads unambiguously -- both ends held back from
    the node markers (`standoff`) in pixels, and the tail held back FAR more (`startstandoff`)
    so a same-row edge (the common case for a simple one-parent one-child chain, e.g. the
    motif-scan example above, where the single parent and single child both land at the span's
    midpoint) doesn't run straight through the source node's own label -- which sits
    immediately beside it, at the identical height, by design (see LABEL_XSHIFT below).

    Only developments/tools that participate in at least one "evolved into" edge are drawn --
    with nothing recorded (today's workbook: 0 edges, every one of the 16 developments) this
    returns a deliberate empty-state figure (see _empty) instead of 16 floating, disconnected
    dots. The page prefers to skip calling this entirely in that case and show a richer
    markdown explainer instead (see pages/5_Gains.py's own n_evolved check), but this function
    stays safe to call directly either way -- tests, or a future caller.

    `project_lookup` is accepted for call-site symmetry with this page's other reuse-aware
    chart functions but genuinely unused here: Part A of this redesign draws no user-project
    node at all, by design (see module docstring above) -- kept so a caller wiring up both this
    and fig_reuse_both_directions doesn't need two different calling conventions.

    Every id/name list pulled from `reuse` is passed through _as_id_list first -- kd's loader
    (_parse_id_list) always returns a real list, so this is unreachable with today's data, but
    it's a cheap guard against a cell that ever held a bare STRING instead: without it,
    iterating a string directly draws one node per LETTER (visible nonsense, no error raised)."""
    dev_by_id = {row["ID"]: row for _, row in developments.iterrows()}
    # Keyed by every alias spelling (kd._name_variants), not just each row's own literal Project
    # text -- see _lineage_resolve_parent's docstring for why a plain _norm(row["Project"]) key
    # alone would silently misclassify a tracked development as "untracked" the moment this
    # read-only workbook's spelling and the live ratings sheet's spelling disagree mid-rename.
    dev_by_name = {}
    for _, row in developments.iterrows():
        for variant in _name_variants(row["Project"]):
            dev_by_name.setdefault(variant, row)
    reuse_by_id = {row["ID"]: row for _, row in reuse.iterrows()}

    parents_by_id = {}   # dev ID -> [resolved parent node ids] (development/tool parents only)
    parent_info = {}     # resolved parent node id -> (display name, kind, state)
    for dev_id, row in dev_by_id.items():
        reuse_row = reuse_by_id.get(dev_id)
        if reuse_row is None:
            continue
        resolved = []
        for label in _as_id_list(reuse_row["came_from_developments"]):
            node_id, name, kind, state = _lineage_resolve_parent(label, dev_by_id, dev_by_name)
            if node_id == dev_id:
                continue  # a malformed self-reference is never drawn as an edge to itself
            resolved.append(node_id)
            parent_info.setdefault(node_id, (name, kind, state))
        parents_by_id[dev_id] = resolved

    depth_memo = {}

    def depth_of(node_id, visiting):
        if node_id in depth_memo:
            return depth_memo[node_id]
        if node_id in visiting:
            return 0  # cycle guard: a node already mid-calculation counts as depth 0 here
        parents = parents_by_id.get(node_id, [])
        d = 0 if not parents else 1 + max(depth_of(p, visiting | {node_id}) for p in parents)
        depth_memo[node_id] = d
        return d

    for node_id in set(parents_by_id) | set(parent_info):
        depth_of(node_id, frozenset())

    active_dev_ids = {dev_id for dev_id, parents in parents_by_id.items() if parents}
    # Every development that's a resolved PARENT of an active one belongs in the tree too, even
    # with no parent of its own (e.g. a tracked development that only ever appears as someone
    # else's "Came from"). parents_by_id/parent_info already cover every ancestor reached while
    # resolving every tracked row above, so one more pass over direct parents is enough -- no
    # separate transitive-closure walk needed.
    all_node_ids = set(active_dev_ids)
    for dev_id in list(active_dev_ids):
        all_node_ids |= set(parents_by_id.get(dev_id, []))

    fig = go.Figure()
    if not all_node_ids:
        _empty(fig, "No development has evolved into another yet.<br>"
                     "Add a development id (e.g. <b>SP01</b>) or a tool/Special-Project name "
                     "under another development's <b>Came from</b> column on the Reuse sheet "
                     "to populate this tree.")
        fig.update_xaxes(visible=False)
        fig.update_yaxes(visible=False)
        fig.update_layout(**base_layout("Lineage: development evolution", width=950, height=320))
        return fig

    def node_label(node_id):
        return dev_by_id[node_id]["Project"] if node_id in dev_by_id else parent_info[node_id][0]

    def node_kind_state(node_id):
        if node_id in dev_by_id:
            row = dev_by_id[node_id]
            kind = "Special Project" if row["Category"] == "Special Project" else "Tool / AI Skill"
            return kind, row["state"]
        return parent_info[node_id][1], parent_info[node_id][2]

    columns = {}
    for node_id in all_node_ids:
        columns.setdefault(depth_memo.get(node_id, 0), []).append(node_id)
    max_depth = max(columns)

    edges = [(parent_id, dev_id) for dev_id in all_node_ids for parent_id in parents_by_id.get(dev_id, [])]
    parents_of = {}
    for src, dst in edges:
        parents_of.setdefault(dst, []).append(src)

    # One barycentre pass, left to right: depth 0 gets a stable alphabetical baseline (nothing
    # upstream of it to sort by), and every later column is ordered by the mean y of ITS OWN
    # parents -- good enough to untangle the common cases without the complexity of a real
    # crossing-minimizer, which a tree this size never needs.
    #
    # y positions are then SPREAD across the full vertical span shared by every column (0 to
    # max_rows-1), not packed into a dense 0..len(column)-1 range -- a column with many nodes
    # sitting next to one with few must not visually bunch into the top half of the plot.
    max_rows = max(len(v) for v in columns.values())
    y_pos = {}

    def _barycenter_key(node_id):
        ys = [y_pos[p] for p in parents_of.get(node_id, []) if p in y_pos]
        return (sum(ys) / len(ys), node_label(node_id)) if ys else (0.0, node_label(node_id))

    for depth in range(max_depth + 1):
        key_fn = node_label if depth == 0 else _barycenter_key
        ordered = sorted(columns.get(depth, []), key=key_fn)
        n = len(ordered)
        span = max_rows - 1
        for i, node_id in enumerate(ordered):
            y_pos[node_id] = (i * span / (n - 1)) if n > 1 else span / 2
        columns[depth] = ordered

    # --- Draw: edges first (so markers sit on top), then nodes by kind -----------------------
    # Edge colour follows the module's own light/dark flag (set once per page via set_theme),
    # same as every other theme-dependent constant in this file (e.g. output_colors) -- not a
    # dict-identity check against the caller's state_colors, which would be fragile.
    edge_color = _LINEAGE_EVOLVED_EDGE_COLOR_DARK if _DARK else _LINEAGE_EVOLVED_EDGE_COLOR
    ARROW_HEAD_STANDOFF = 14    # px clear of the target marker's own radius+line (markers are
    # size=16, same clearance LABEL_XSHIFT below uses for the same reason)
    ARROW_TAIL_STANDOFF = 120   # px clear of the SOURCE node's own label -- generous on purpose:
    # a same-row edge (parent and child both landing at the span's midpoint, the common case for
    # a simple one-parent one-child chain -- see this function's own docstring) would otherwise
    # run the arrow straight through the source's own label text, which sits immediately beside
    # it at the identical height. 120px comfortably clears a label wrapped at _wrap_label's
    # 16-character width in this chart's 10pt font even at its longest.
    for src, dst in edges:
        fig.add_annotation(
            x=depth_memo[dst], y=y_pos[dst], ax=depth_memo[src], ay=y_pos[src],
            xref="x", yref="y", axref="x", ayref="y",
            showarrow=True, arrowhead=2, arrowsize=1.1, arrowwidth=1.8, arrowcolor=edge_color,
            standoff=ARROW_HEAD_STANDOFF, startstandoff=ARROW_TAIL_STANDOFF,
        )

    node_groups = {"Special Project": [], "Tool / AI Skill": []}
    for node_id in all_node_ids:
        kind, state = node_kind_state(node_id)
        tracked = node_id in dev_by_id
        state_label = GAIN_STATE_LABELS.get(state, state)
        hover = f"<b>{node_label(node_id)}</b><br>{kind}" + (
            f"<br>State: {state_label}" if tracked else "<br>(untracked -- no row in this workbook)"
        )
        node_groups[kind].append((node_id, hover))

    # A development/tool label is a layout ANNOTATION, not scatter text, sitting BESIDE its
    # marker (horizontally), not above it -- preserved from the old fig_lineage, which already
    # solved the ambiguity this avoids: a label floating above one dot can look like it's
    # floating above a neighbouring column's dot instead, the moment two nodes in adjacent
    # columns land at a similar height (seen for real with "FT Motif Search" and "OMICs
    # Pipelines"). Horizontal adjacency on the dot's own baseline doesn't have that failure
    # mode -- the label is unambiguously attached to whichever dot sits level with it.
    # `yanchor="middle"` keeps a 2-3 line wrapped name centred on its dot as a block.
    LABEL_XSHIFT = 14  # px clear of the marker's own radius (markers are size=16) + a gap

    for kind, entries in node_groups.items():
        if not entries:
            continue
        xs = [depth_memo[node_id] for node_id, _ in entries]
        ys = [y_pos[node_id] for node_id, _ in entries]
        colors = [
            state_colors[node_kind_state(node_id)[1]] if node_kind_state(node_id)[1] else TL_BASELINE
            for node_id, _ in entries
        ]
        hovers = [h for _, h in entries]
        fig.add_trace(go.Scatter(
            x=xs, y=ys, mode="markers", name=kind, showlegend=False,
            marker=dict(symbol=_LINEAGE_KIND_SYMBOLS[kind], size=16, color=colors,
                        line=dict(color=TL_SURFACE, width=1.5)),
            hovertext=hovers, hoverinfo="text",
        ))
        for (node_id, _), x, y in zip(entries, xs, ys):
            fig.add_annotation(
                x=x, y=y, xref="x", yref="y", xanchor="left", yanchor="middle",
                xshift=LABEL_XSHIFT, showarrow=False, align="left",
                text=_wrap_label(node_label(node_id), 16),
                font=dict(size=10, color=TL_INK_SECONDARY),
            )

    # Dummy legend-only entries for shape/kind -- the real node traces above are showlegend=
    # False because their marker colour varies per point (state or neutral), which Plotly's
    # legend swatch doesn't reliably reflect; a single-point proxy trace per kind, drawn in a
    # fixed neutral colour at (None, None) (truly empty x=[]/y=[] renders NO legend entry at
    # all, verified against this exact Plotly/kaleido version), is the robust way to explain
    # shape regardless of that.
    for kind, symbol in _LINEAGE_KIND_SYMBOLS.items():
        fig.add_trace(go.Scatter(
            x=[None], y=[None], mode="markers", name=kind, showlegend=True,
            marker=dict(symbol=symbol, size=11, color=TL_INK_SECONDARY),
        ))

    tick_positions = list(range(max_depth + 1))
    tick_labels = [_depth_col_label(d) for d in tick_positions]
    fig.update_xaxes(
        range=[-0.3, max_depth + 1.3], tickvals=tick_positions, ticktext=tick_labels,
        showgrid=True, gridcolor=TL_GRID, zeroline=False,
        tickfont=dict(size=11, color=TL_INK_SECONDARY),
    )
    fig.update_yaxes(visible=False, range=[-1, max_rows + 1])
    fig.update_layout(
        **base_layout("Lineage: development evolution",
                      width=max(700, round(260 * (max_depth + 1.8))),
                      height=max(360, 110 + 60 * max_rows)),
        margin=dict(l=20, r=70, t=70, b=70),
        # Bottom, not top -- a top legend collides with the title text at the left (both
        # compete for the same narrow top band); the bottom has nothing else in it.
        legend=dict(orientation="h", yanchor="top", y=-0.12, xanchor="center", x=0.5),
    )
    return fig
