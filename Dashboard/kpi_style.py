"""Shared visual identity for the KPI dashboard pages.

The base theme (colors, fonts, radii) lives in .streamlit/config.toml; this module adds the
polish config.toml can't express -- the IBM Plex webfonts (the snapshot page's faces, so the
live app and the shared page read as one product), metric tiles rendered as cards,
pill-style in-page navigation, and heading rhythm -- plus the small page helpers (header,
anchor, page_nav) that every page shares. Call inject() once per page, right after
st.set_page_config, with the same dark flag handed to kpi_charts.set_theme."""

from pathlib import Path

import streamlit as st

# Images that belong to the app itself (not exported charts, which live in ../Images). The
# demo ships none: the CV page asks for a mark by name and simply leaves it out when the
# file isn't there, so dropping one in is all it takes. Streamlit serves this folder at
# app/static/<name> (enableStaticServing in .streamlit/config.toml), so pages reference the
# URL rather than the path -- an <img> keeps an animated GIF animated, st.image does not.
STATIC = Path(__file__).resolve().parent / "static"


def static_url(name):
    """The served URL for a file in static/, or None when it isn't there."""
    return f"app/static/{name}" if (STATIC / name).exists() else None

# Same token values as export_snapshot.py's CSS and kpi_charts' light/dark themes.
LIGHT = dict(card="#ffffff", ink2="#52514e", ink3="#898781", line="#e1e0d9",
             accent="#1f5c99", accent_soft="#eef3f8")
DARK = dict(card="#232321", ink2="#d0cec7", ink3="#938f87", line="#3c3b38",
            accent="#4a84c9", accent_soft="#223042")

# Same token values as export_snapshot.py's CSS and kpi_charts' light/dark themes.
LIGHT = dict(card="#ffffff", ink2="#52514e", ink3="#898781", line="#e1e0d9",
             accent="#1f5c99", accent_soft="#eef3f8")
DARK = dict(card="#232321", ink2="#d0cec7", ink3="#938f87", line="#3c3b38",
            accent="#4a84c9", accent_soft="#223042")


def inject(dark: bool):
    """Load the webfont and apply the page polish for the active (light/dark) theme."""
    t = DARK if dark else LIGHT
    st.markdown(
        f"""<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;600&display=swap');

/* Headings: tighter and a touch heavier than Streamlit's default */
h1 {{ font-weight: 700 !important; letter-spacing: -0.015em; }}
h2, h3 {{ font-weight: 650 !important; letter-spacing: -0.01em; }}

/* Metric tiles as cards */
[data-testid="stMetric"] {{
  background: {t['card']};
  border: 1px solid {t['line']};
  border-radius: 12px;
  padding: 0.85rem 1.1rem;
}}
/* Long titles (several tiles run two or three words past what the column can show in one
   line) wrap instead of truncating with an ellipsis -- unreadable beats ugly. */
[data-testid="stMetricLabel"] {{
  overflow: visible;
}}
[data-testid="stMetricLabel"] p {{
  font-size: 0.75rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: {t['ink3']};
  white-space: normal;
  overflow-wrap: break-word;
  text-overflow: clip;
  overflow: visible;
}}
[data-testid="stMetricValue"] {{
  font-family: "IBM Plex Mono", ui-monospace, monospace;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}}

/* Tabs: clearer labels, a little air between them */
[data-testid="stTabs"] [data-baseweb="tab-list"] {{ gap: 0.35rem; }}
[data-testid="stTabs"] [data-baseweb="tab"] {{ font-weight: 600; }}

/* In-page jump links (page_nav) as pill chips */
.page-nav {{ display: flex; flex-wrap: wrap; gap: 0.45rem; margin: 0.15rem 0 0.9rem; }}
.page-nav a {{
  background: {t['accent_soft']};
  color: {t['accent']} !important;
  border: 1px solid transparent;
  border-radius: 999px;
  padding: 0.22rem 0.85rem;
  font-size: 0.84rem;
  font-weight: 600;
  text-decoration: none !important;
}}
.page-nav a:hover {{ border-color: {t['accent']}; }}

/* Page header block */
.kpi-sub {{ color: {t['ink2']}; font-size: 0.95rem; margin: -0.35rem 0 0.9rem; }}

</style>""",
        unsafe_allow_html=True,
    )


def header(title, subtitle=None):
    """Page title with an optional one-line subtitle under it."""
    st.title(title)
    if subtitle:
        st.markdown(f'<p class="kpi-sub">{subtitle}</p>', unsafe_allow_html=True)


def anchor(id_):
    """An invisible jump target -- lets page_nav() link here without adding a visible header."""
    st.markdown(f'<div id="{id_}"></div>', unsafe_allow_html=True)


def page_nav(links):
    """links: list of (label, anchor_id). A row of pill-style in-page jump links."""
    chips = "".join(f'<a href="#{aid}">{label}</a>' for label, aid in links)
    st.markdown(f'<div class="page-nav">{chips}</div>', unsafe_allow_html=True)
