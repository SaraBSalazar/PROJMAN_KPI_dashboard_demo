"""
record_demo_video.py -- regenerates media/dashboard_tour.mp4 (and its thumbnail).

Drives a real, local instance of the dashboard with Playwright and records the
browser tab. Captions are an overlay drawn on the live page (injected CSS/DOM),
not burned in afterwards, so they're frame-accurate to what's happening
underneath. Scrolling, cursor movement, and clicks are all animated smoothly
(eased, not instant) so the recording reads as a deliberate walkthrough rather
than a scripted jump-cut reel.

The tour makes several real writes along the way -- a row added to
Data/track_time.csv, a pause note + forgive on Projects Review, a task (with a
finish date) added on Special Projects, and a project edited on Add Data -- so
every "this just changed" moment on screen is a genuine save round-trip, not a
staged one. `git checkout -- Data/` at the end of a successful run reverts all
of it, so the repo's committed demo data stays exactly what
generate_demo_data.py produced.

Setup (one-time):
    pip install playwright pillow
    playwright install chromium
    # ffmpeg must be on PATH (only used to mux the recording + make the thumbnail)

Usage:
    python record_demo_video.py
"""
from __future__ import annotations

import datetime as dt
import socket
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parent
DASHBOARD_DIR = ROOT / "Dashboard"
MEDIA_DIR = ROOT / "media"
VIDEO_TMP_DIR = ROOT / ".video_tmp"
VIEWPORT = {"width": 1600, "height": 1000}
FPS = 24
# The first few real seconds are Streamlit cold-starting (blank tab, spinner, layout
# settling) -- nothing worth watching. run_tour() pads its own startup wait out to
# exactly this many seconds, and the final ffmpeg mux trims the same amount off the
# front, so the published video opens already on the Week tab, fully loaded.
PREROLL_SECONDS = 6.0

OVERLAY_CSS = """
#tour-caption {
  position: fixed; left: 24px; bottom: 24px; max-width: 760px;
  background: rgba(13, 17, 23, 0.92); color: #fff; border-left: 4px solid #3b82f6;
  border-radius: 10px; padding: 16px 22px; font-family: "Source Sans Pro", sans-serif;
  z-index: 999999; opacity: 0; transform: translateY(10px);
  transition: opacity .35s ease, transform .35s ease; pointer-events: none;
}
#tour-caption.show { opacity: 1; transform: translateY(0); }
#tour-caption .tc-label { font-size: 12px; font-weight: 700; letter-spacing: .08em;
  text-transform: uppercase; color: #60a5fa; margin-bottom: 6px; }
#tour-caption .tc-desc { font-size: 19px; font-weight: 600; line-height: 1.35; }
#tour-cursor { position: fixed; width: 26px; height: 26px; border-radius: 50%;
  background: rgba(59,130,246,.30); border: 2px solid #3b82f6; z-index: 1000000;
  pointer-events: none; transform: translate(-50%,-50%); opacity: 0; left: 0; top: 0;
  transition: left .55s cubic-bezier(.4,0,.2,1), top .55s cubic-bezier(.4,0,.2,1),
              transform .15s ease, opacity .25s ease, background .15s ease;
}
#tour-cursor.visible { opacity: 1; }
#tour-cursor.clicking { transform: translate(-50%,-50%) scale(.55); background: rgba(59,130,246,.65); }
#tour-card { position: fixed; inset: 0; background: #0d1117; color: #fff; z-index: 2000000;
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  text-align: center; opacity: 0; pointer-events: none;
  transition: opacity .5s ease; font-family: "Source Sans Pro", sans-serif; }
#tour-card.show { opacity: 1; }
#tour-card .tcard-label { font-size: 13px; font-weight: 700; letter-spacing: .12em;
  text-transform: uppercase; color: #60a5fa; margin-bottom: 18px; }
#tour-card .tcard-title { font-size: 42px; font-weight: 800; margin-bottom: 14px; }
#tour-card .tcard-sub { font-size: 18px; color: #9aa4b2; }
"""

OVERLAY_JS = """
() => {
  if (document.getElementById('tour-style')) return;
  const style = document.createElement('style');
  style.id = 'tour-style';
  style.textContent = `__CSS__`;
  document.head.appendChild(style);

  const caption = document.createElement('div');
  caption.id = 'tour-caption';
  caption.innerHTML = '<div class="tc-label"></div><div class="tc-desc"></div>';
  document.body.appendChild(caption);

  const cursor = document.createElement('div');
  cursor.id = 'tour-cursor';
  document.body.appendChild(cursor);

  const card = document.createElement('div');
  card.id = 'tour-card';
  card.innerHTML = '<div class="tcard-label"></div><div class="tcard-title"></div><div class="tcard-sub"></div>';
  document.body.appendChild(card);
}
""".replace("__CSS__", OVERLAY_CSS.replace("`", "\\`").replace("\n", " "))


def wait_port(port: int, timeout: float = 60.0) -> None:
    start = time.time()
    while time.time() - start < timeout:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                time.sleep(3.0)  # give Streamlit a moment past the TCP accept
                return
        time.sleep(0.5)
    raise RuntimeError(f"Streamlit never came up on port {port}")


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def ensure_overlay(page: Page) -> None:
    page.evaluate(OVERLAY_JS)


def show_caption(page: Page, label: str, desc: str, hold: float = 3.0) -> None:
    ensure_overlay(page)
    page.evaluate(
        """([label, desc]) => {
            const c = document.getElementById('tour-caption');
            c.querySelector('.tc-label').textContent = label;
            c.querySelector('.tc-desc').textContent = desc;
            c.classList.add('show');
        }""",
        [label, desc],
    )
    page.wait_for_timeout(int(hold * 1000))


def hide_caption(page: Page, wait: float = 0.4) -> None:
    page.evaluate("document.getElementById('tour-caption')?.classList.remove('show')")
    page.wait_for_timeout(int(wait * 1000))


def title_card(page: Page, label: str, title: str, sub: str, hold: float = 3.5) -> None:
    ensure_overlay(page)
    page.evaluate(
        """([label, title, sub]) => {
            const c = document.getElementById('tour-card');
            c.querySelector('.tcard-label').textContent = label;
            c.querySelector('.tcard-title').textContent = title;
            c.querySelector('.tcard-sub').textContent = sub;
            c.classList.add('show');
        }""",
        [label, title, sub],
    )
    page.wait_for_timeout(int(hold * 1000))
    page.evaluate("document.getElementById('tour-card')?.classList.remove('show')")
    page.wait_for_timeout(500)


def smooth_scroll_by(page: Page, dy: int, duration: float = 1.3) -> None:
    """Eases the real Streamlit scroll container (NOT window -- Streamlit scrolls
    [data-testid='stMain'], window.scrollY never moves) by dy pixels."""
    page.evaluate(
        """([dy, dur]) => new Promise(resolve => {
            const el = document.querySelector('[data-testid="stMain"]') || document.scrollingElement;
            const start = el.scrollTop;
            const max = el.scrollHeight - el.clientHeight;
            const target = Math.max(0, Math.min(start + dy, max));
            const dist = target - start;
            const t0 = performance.now();
            const ease = t => (t < 0.5 ? 2*t*t : -1 + (4 - 2*t) * t);
            function step(now) {
                const p = Math.min(1, (now - t0) / dur);
                el.scrollTop = start + dist * ease(p);
                if (p < 1) requestAnimationFrame(step); else resolve();
            }
            requestAnimationFrame(step);
        })""",
        [dy, duration * 1000],
    )


def move_cursor(page: Page, x: float, y: float, duration: float = 0.55) -> None:
    ensure_overlay(page)
    page.evaluate(
        """([x, y]) => {
            const c = document.getElementById('tour-cursor');
            c.classList.add('visible');
            c.style.left = x + 'px';
            c.style.top = y + 'px';
        }""",
        [x, y],
    )
    page.wait_for_timeout(int(duration * 1000) + 80)


def hide_cursor(page: Page) -> None:
    page.evaluate("document.getElementById('tour-cursor')?.classList.remove('visible')")


def click_with_cursor(page: Page, x: float, y: float, pulse: float = 0.22) -> None:
    move_cursor(page, x, y)
    page.evaluate("document.getElementById('tour-cursor')?.classList.add('clicking')")
    page.mouse.click(x, y)
    page.wait_for_timeout(int(pulse * 1000))
    page.evaluate("document.getElementById('tour-cursor')?.classList.remove('clicking')")


def click_nav(page: Page, name: str) -> None:
    link = page.get_by_role("link", name=name).first
    link.scroll_into_view_if_needed()
    box = link.bounding_box()
    click_with_cursor(page, box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.wait_for_timeout(900)
    hide_cursor(page)


def click_tab(page: Page, name: str) -> None:
    tab = page.get_by_role("tab", name=name).first
    box = tab.bounding_box()
    click_with_cursor(page, box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.wait_for_timeout(500)
    hide_cursor(page)


def find_plotly_point(page: Page, needle: str):
    return page.evaluate(
        """(needle) => {
            const texts = Array.from(document.querySelectorAll('svg text'));
            const label = texts.find(t => t.textContent && t.textContent.includes(needle));
            if (!label) return null;
            const lr = label.getBoundingClientRect();
            const points = Array.from(document.querySelectorAll('path.point'));
            let best = null, bestD = Infinity;
            for (const p of points) {
                const r = p.getBoundingClientRect();
                if (r.width === 0) continue;
                const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
                const d = Math.hypot(cx - (lr.left + lr.width / 2), cy - (lr.bottom + r.height / 2 + 4));
                if (d < bestD) { bestD = d; best = {x: cx, y: cy}; }
            }
            return best;
        }""",
        needle,
    )


def fill_grid_cell(page: Page, x: float, y: float, text: str) -> None:
    """Clicks then double-clicks a glide-data-grid cell to open its inline text
    editor, types `text`, and commits with Enter. Validated against the Week
    tab's Project / Category / Major task (MultiselectColumn) and Hrs
    (NumberColumn) cells. Uses two separate, spaced clicks rather than
    page.mouse.dblclick(): the grid's own double-click detection needs the two
    events far enough apart to resolve cleanly, and back-to-back synthetic
    clicks landed inside that window flakily (open-then-immediately-close,
    or no editor at all) in testing."""
    for attempt in range(3):
        page.mouse.click(x, y)
        page.wait_for_timeout(130)
        page.mouse.click(x, y)
        page.wait_for_timeout(300)
        editor = page.query_selector("textarea, input:focus")
        if editor:
            break
        page.wait_for_timeout(200)
    page.keyboard.type(text, delay=45)
    page.wait_for_timeout(350)
    page.keyboard.press("Enter")
    page.wait_for_timeout(450)


def _widget_center(locator) -> tuple[float, float]:
    box = locator.bounding_box()
    return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2


def set_date_field(page: Page, date_widget, day: str, month: str, year: str) -> None:
    """Sets an st.date_input's value by clicking each react-aria segment by its
    `data-type` ("day"/"month"/"year") and typing straight into it.

    Deliberately does NOT click just the first segment and rely on auto-advance:
    st.date_input's segment ORDER follows its `format` argument (Special Projects'
    task dates pass format="DD/MM/YYYY"; Add Data's date_or_none() passes none, which
    renders YYYY/MM/DD) -- typing day/month/year in that assumed order silently wrote
    into the wrong segments on the latter. Addressing each span by data-type sidesteps
    that regardless of which order this particular field happens to render in."""
    for data_type, text in [("day", day), ("month", month), ("year", year)]:
        span = date_widget.locator(f'span[data-type="{data_type}"]')
        span.scroll_into_view_if_needed()
        box = span.bounding_box()
        page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        page.wait_for_timeout(100)
        page.keyboard.type(text, delay=70)
        page.wait_for_timeout(150)


def run_tour(page: Page) -> None:
    t0 = time.time()
    # "load" rather than "networkidle": Streamlit keeps a persistent websocket open for
    # live updates, which can make the page never go network-idle and time this out.
    # The explicit wait below is what actually confirms real content is on screen.
    page.goto(f"http://127.0.0.1:{STREAMLIT_PORT}", wait_until="load", timeout=60000)
    # Wait for something only present once the Week tab's own content (not just the
    # page chrome) has rendered, so the preroll below can't run out before it's real.
    page.get_by_role("button", name="Add row").first.wait_for(state="visible", timeout=60000)
    ensure_overlay(page)
    elapsed = time.time() - t0
    page.wait_for_timeout(int(max(0.0, PREROLL_SECONDS - elapsed) * 1000))

    # ---------------------------------------------------------------- WEEK --
    show_caption(page, "KPI Report · Week",
                  "Pick any week to see hours logged, by project and by category.", 3.0)
    hide_caption(page)
    smooth_scroll_by(page, 560, 1.5)
    show_caption(page, "KPI Report · Week",
                  "Every entry breaks down further by the actual task worked on.", 2.8)
    hide_caption(page)
    smooth_scroll_by(page, 620, 1.5)
    page.wait_for_timeout(800)
    smooth_scroll_by(page, 680, 1.5)

    show_caption(page, "KPI Report · Week",
                 "Add a row and the week's KPIs update right away.", 2.6)
    hide_caption(page)

    add_row_btn = page.get_by_role("button", name="Add row").first
    add_row_btn.scroll_into_view_if_needed()
    page.wait_for_timeout(400)
    box = add_row_btn.bounding_box()
    click_with_cursor(page, box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    hide_cursor(page)
    page.wait_for_timeout(1800)  # let the rerun + "unsaved changes" banner settle

    # Scroll the grid's own internal scroller (not window/stMain) straight to the
    # bottom via its scrollTop, deterministically -- a synthetic mouse wheel at a
    # pre-rerun coordinate was a race (the banner reflows the whole page first).
    page.evaluate(
        "document.querySelector('.dvn-scroller.stDataFrameGlideDataEditor')"
        "?.scrollTo(0, 999999)"
    )
    page.wait_for_timeout(500)

    grid = page.query_selector_all("canvas")[0]
    gbox = grid.bounding_box()
    row_y = gbox["y"] + gbox["height"] - 20
    project_x = gbox["x"] + 254
    category_x = gbox["x"] + 449
    hrs_x = gbox["x"] + 756

    move_cursor(page, project_x, row_y)
    fill_grid_cell(page, project_x, row_y, "DEMO_WALKTHROUGH")
    move_cursor(page, category_x, row_y)
    fill_grid_cell(page, category_x, row_y, "Projects")
    move_cursor(page, hrs_x, row_y)
    fill_grid_cell(page, hrs_x, row_y, "3")
    hide_cursor(page)
    page.wait_for_timeout(500)

    save_btn = page.get_by_role("button", name="Save changes to track_time.csv").first
    save_btn.scroll_into_view_if_needed()
    page.wait_for_timeout(400)
    sbox = save_btn.bounding_box()
    click_with_cursor(page, sbox["x"] + sbox["width"] / 2, sbox["y"] + sbox["height"] / 2)
    hide_cursor(page)
    page.wait_for_timeout(2200)

    smooth_scroll_by(page, -2200, 1.8)
    page.wait_for_timeout(500)
    show_caption(page, "KPI Report · Week",
                 "Hours logged jumps immediately -- same for every chart on this tab.", 3.0)
    hide_caption(page)

    # --------------------------------------------------------------- MONTH --
    click_tab(page, "🗓️ Month")
    show_caption(page, "KPI Report · Month",
                 "Zoom out to a month -- category mix and the week-by-week spread.", 2.8)
    hide_caption(page)
    smooth_scroll_by(page, 620, 1.5)
    page.wait_for_timeout(800)
    smooth_scroll_by(page, 620, 1.5)
    page.wait_for_timeout(700)
    # A large dy clamps to the container's real max scrollTop, so this always lands
    # exactly on the bottom of the page regardless of how tall this period's content is.
    smooth_scroll_by(page, 4000, 1.7)
    page.wait_for_timeout(1000)
    smooth_scroll_by(page, -6000, 1.7)

    # ---------------------------------------------------------------- YEAR --
    click_tab(page, "📈 Year")
    show_caption(page, "KPI Report · Year",
                 "The full year -- projects received vs. finished, and the logged-hours trend.", 2.8)
    hide_caption(page)
    smooth_scroll_by(page, 650, 1.5)
    page.wait_for_timeout(800)
    smooth_scroll_by(page, 650, 1.5)
    page.wait_for_timeout(700)
    smooth_scroll_by(page, 4000, 1.7)
    page.wait_for_timeout(1000)
    smooth_scroll_by(page, -6000, 1.7)

    # ------------------------------------------------------- PROJECTS REVIEW --
    click_nav(page, "Projects Review")
    show_caption(page, "Projects Review",
                 "The detail page -- a glance at the year, then every project's own story below.", 2.8)
    hide_caption(page)
    smooth_scroll_by(page, 520, 1.5)
    show_caption(page, "Projects Review · Needs attention",
                 "Projects gone quiet get flagged automatically.", 2.6)
    hide_caption(page)
    smooth_scroll_by(page, 650, 1.5)
    show_caption(page, "Projects Review · Turnaround",
                 "First contact to delivery -- pauses excluded, forgiven pauses tracked separately.", 2.8)
    hide_caption(page)
    smooth_scroll_by(page, 680, 1.5)
    page.wait_for_timeout(800)
    smooth_scroll_by(page, 680, 1.5)

    # --- Pauses: open the expander, explain one, forgive it, and watch the chart
    # above redraw that stretch faded/hatched. All optional/defensive: a demo data
    # refresh with no detected pause shouldn't be able to break the recording.
    page.wait_for_timeout(500)
    try:
        # "Pauses —" alone also matches "Forgiven pauses —" in the "How these numbers
        # are calculated" expander above it (Playwright text matching is case-
        # insensitive), which opened the wrong panel in testing -- the "⏸" leads only
        # the real expander's own label and sidesteps that collision.
        pauses_summary = page.get_by_text("⏸ Pauses", exact=False).first
        if pauses_summary.count():
            pauses_summary.scroll_into_view_if_needed()
            page.wait_for_timeout(300)
            pbox = pauses_summary.bounding_box()
            click_with_cursor(page, pbox["x"] + pbox["width"] / 2, pbox["y"] + pbox["height"] / 2)
            hide_cursor(page)
            page.wait_for_timeout(600)

            note_input = page.locator('input[placeholder="e.g. waiting for user"]').first
            note_input.scroll_into_view_if_needed()
            page.wait_for_timeout(300)
            nbox = note_input.bounding_box()
            move_cursor(page, nbox["x"] + nbox["width"] / 2, nbox["y"] + nbox["height"] / 2)
            note_input.click()
            page.keyboard.type("Waiting on user feedback", delay=55)
            page.keyboard.press("Tab")
            hide_cursor(page)
            page.wait_for_timeout(700)

            forgive_box = page.get_by_role("checkbox", name="Forgive").first
            forgive_box.scroll_into_view_if_needed()
            fbox = forgive_box.bounding_box()
            click_with_cursor(page, fbox["x"] + fbox["width"] / 2, fbox["y"] + fbox["height"] / 2)
            hide_cursor(page)
            page.wait_for_timeout(2200)  # save round-trip + rerun

            smooth_scroll_by(page, -900, 1.4)
            show_caption(page, "Projects Review · Turnaround",
                         "Forgiven -- that stretch redraws faded on the chart, and its days drop "
                         "out of this project's totals.", 3.0)
            hide_caption(page)
            smooth_scroll_by(page, 900, 1.3)
    except Exception:
        pass

    page.wait_for_timeout(600)
    smooth_scroll_by(page, 680, 1.5)
    show_caption(page, "Projects Review",
                 "Further down: hours by project, complexity, who the work is for.", 2.6)
    hide_caption(page)

    # ---------------------------------------------------------- SPECIAL PROJECTS --
    click_nav(page, "Special Projects")
    show_caption(page, "Special Projects",
                 "The strategic side of the work -- internal tools and initiatives, rated by effort and impact.", 2.8)
    hide_caption(page)

    pt = find_plotly_point(page, "Snippet Library")
    if pt:
        move_cursor(page, pt["x"], pt["y"])
        page.evaluate("document.getElementById('tour-cursor')?.classList.add('clicking')")
        page.mouse.click(pt["x"], pt["y"])
        page.wait_for_timeout(900)
        page.evaluate("document.getElementById('tour-cursor')?.classList.remove('clicking')")
        page.mouse.move(100, 950)
        hide_cursor(page)
    page.wait_for_timeout(600)

    show_caption(page, "Special Projects",
                 "Click a bubble and its project card opens below -- either one drives the other.", 2.8)
    hide_caption(page)
    smooth_scroll_by(page, 420, 1.4)

    # "Coming up / Behind" sits between the bubble chart and the project card --
    # call it out on the way past rather than just scrolling through it.
    show_caption(page, "Special Projects · Coming up / Behind",
                 "Every special project's upcoming and overdue tasks, gathered in one place.", 2.8)
    hide_caption(page)
    smooth_scroll_by(page, 420, 1.4)
    page.wait_for_timeout(700)

    # --- Add a task, give it a finish date, and the timeline below picks it up.
    try:
        add_task_btn = page.get_by_role("button", name="➕ Add task").first
        add_task_btn.scroll_into_view_if_needed()
        page.wait_for_timeout(300)
        abox = add_task_btn.bounding_box()
        click_with_cursor(page, abox["x"] + abox["width"] / 2, abox["y"] + abox["height"] / 2)
        hide_cursor(page)
        page.wait_for_timeout(900)

        task_input = page.locator('input[placeholder="Task description"]').last
        task_input.scroll_into_view_if_needed()
        page.wait_for_timeout(300)
        tibox = task_input.bounding_box()
        move_cursor(page, tibox["x"] + tibox["width"] / 2, tibox["y"] + tibox["height"] / 2)
        task_input.click()
        page.keyboard.type("Write onboarding guide", delay=55)
        page.keyboard.press("Tab")
        hide_cursor(page)
        page.wait_for_timeout(700)

        # Start and due are both rendered as stDateInput -- the due field for this
        # (newly appended, last-in-the-DOM) task is the very last one on the page.
        due_widget = page.locator('[data-testid="stDateInput"]').last
        due_widget.scroll_into_view_if_needed()
        page.wait_for_timeout(200)
        move_cursor(page, *_widget_center(due_widget))
        set_date_field(page, due_widget, "15", "12", "2026")
        page.keyboard.press("Escape")
        hide_cursor(page)
        page.wait_for_timeout(1000)

        show_caption(page, "Special Projects",
                     "New task, a finish date, and it drops straight onto the timeline below.", 2.8)
        hide_caption(page)
    except Exception:
        pass

    smooth_scroll_by(page, 560, 1.4)
    page.wait_for_timeout(700)
    smooth_scroll_by(page, -2440, 1.3)

    # ------------------------------------------------------------------- TOOLS --
    click_nav(page, "Tools")
    show_caption(page, "Tools & AI Skills",
                 "A running inventory of everything built along the way -- pipelines, dashboards, skills.", 2.8)
    hide_caption(page)
    smooth_scroll_by(page, 600, 1.4)
    page.wait_for_timeout(900)
    smooth_scroll_by(page, -650, 1.0)

    # --------------------------------------------------------------- ADD DATA --
    click_nav(page, "Add Data")
    show_caption(page, "Add Data",
                 "And this is how it all gets fed in -- no spreadsheet editing required.", 2.8)
    hide_caption(page)
    smooth_scroll_by(page, 300, 1.0)
    page.wait_for_timeout(500)

    # get_by_label matched the adjacent (?) help-tooltip button instead of the
    # input in testing -- the exact aria-label attribute selector is unambiguous.
    tag_input = page.locator('input[aria-label="Project tag *"]').first
    if tag_input.count() == 0:
        tag_input = page.locator('input[aria-label="Project tag"]').first
    try:
        tbox = tag_input.bounding_box()
        move_cursor(page, tbox["x"] + tbox["width"] / 2, tbox["y"] + tbox["height"] / 2)
        tag_input.click()
        page.keyboard.type("DEMO_099", delay=70)
        hide_cursor(page)
    except Exception:
        pass
    page.wait_for_timeout(500)

    show_caption(page, "Add Data",
                 "Filling in a new project here updates the live dashboard immediately -- this one's just for show.",
                 3.0)
    hide_caption(page)

    # --- Editing an existing project works the same way: log one more report and
    # the day it closed, and save.
    try:
        edit_heading = page.get_by_text("Edit a project —", exact=False).first
        edit_heading.scroll_into_view_if_needed()
        page.wait_for_timeout(500)
        show_caption(page, "Add Data · Edit a project",
                     "Editing an existing project works the same way -- log one more report "
                     "and the day it closed.", 2.8)
        hide_caption(page)

        reports_widget = page.locator('[data-testid="stNumberInput"]').filter(
            has=page.get_by_text("Number of Reports", exact=True)
        ).first
        step_up = reports_widget.locator('[data-testid="stNumberInputStepUp"]').first
        step_up.scroll_into_view_if_needed()
        page.wait_for_timeout(300)
        move_cursor(page, *_widget_center(step_up))
        click_with_cursor(page, *_widget_center(step_up))
        hide_cursor(page)
        page.wait_for_timeout(500)

        closing_widget = page.locator('[data-testid="stDateInput"]').filter(
            has=page.get_by_text("Closing Day", exact=False)
        ).first
        closing_widget.scroll_into_view_if_needed()
        page.wait_for_timeout(300)
        move_cursor(page, *_widget_center(closing_widget))
        today = dt.date.today()
        set_date_field(page, closing_widget, f"{today.day:02d}", f"{today.month:02d}", str(today.year))
        page.keyboard.press("Escape")
        hide_cursor(page)
        page.wait_for_timeout(600)

        save_btn = page.get_by_role("button", name="💾 Save changes").first
        save_btn.scroll_into_view_if_needed()
        page.wait_for_timeout(300)
        click_with_cursor(page, *_widget_center(save_btn))
        hide_cursor(page)
        page.wait_for_timeout(1800)

        show_caption(page, "Add Data · Edit a project",
                     "Saved -- the report count and closing date are live everywhere else "
                     "that reads this project.", 3.0)
        hide_caption(page)
    except Exception:
        pass

    # ------------------------------------------------------------------ OUTRO --
    title_card(page, "Thanks for watching", "Fully synthetic data, real workflow.",
               "github.com/SaraBSalazar/PROJMAN_KPI_dashboard_demo", 3.5)


def main() -> None:
    global STREAMLIT_PORT
    STREAMLIT_PORT = free_port()

    VIDEO_TMP_DIR.mkdir(exist_ok=True)
    for f in VIDEO_TMP_DIR.glob("*"):
        f.unlink()

    server = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", "KPI_Report.py",
         "--server.headless", "true", f"--server.port={STREAMLIT_PORT}",
         "--server.runOnSave=false", "--server.fileWatcherType=none"],
        cwd=str(DASHBOARD_DIR),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        wait_port(STREAMLIT_PORT)

        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context(
                viewport=VIEWPORT,
                record_video_dir=str(VIDEO_TMP_DIR),
                record_video_size=VIEWPORT,
            )
            page = context.new_page()
            try:
                run_tour(page)
            finally:
                page.close()
                context.close()
            browser.close()

        webm_files = list(VIDEO_TMP_DIR.glob("*.webm"))
        if not webm_files:
            raise RuntimeError("Playwright produced no video file")
        webm_path = webm_files[0]

        MEDIA_DIR.mkdir(exist_ok=True)
        mp4_path = MEDIA_DIR / "dashboard_tour.mp4"
        subprocess.run(
            # -ss before -i trims the cold-start preroll (see PREROLL_SECONDS) off the
            # front; run_tour() pads its own startup wait to the same length, so the
            # published video opens already on the Week tab, fully loaded.
            # crf=30 (not a sharper-looking 20): GitHub only renders an inline preview
            # up to ~10MB, and 20 pushed this past 22MB -- 30 lands around 6-7MB for
            # this ~3min tour with no visible loss on static dashboard-UI content.
            ["ffmpeg", "-y", "-ss", str(PREROLL_SECONDS), "-i", str(webm_path),
             "-vf", f"fps={FPS},format=yuv420p",
             "-c:v", "libx264", "-crf", "30", "-preset", "slow",
             "-movflags", "+faststart", str(mp4_path)],
            check=True,
        )

        make_thumbnail(mp4_path, MEDIA_DIR / "dashboard_tour_thumb.png")
        print(f"Wrote {mp4_path} and its thumbnail.")

        # The tour writes real rows/notes/tasks/edits across several tracked files
        # (Week's "Add row", Projects Review's pause note + forgive, Special
        # Projects' new task, Add Data's project edit) so the recording shows a
        # genuine save round-trip at each step. Revert the whole tree rather than
        # naming each file -- simpler, and automatically covers whatever the tour
        # touches next. Only the tracked demo data is ever at risk; this never
        # touches anything the tour doesn't itself write.
        subprocess.run(["git", "checkout", "--", "Data/"], cwd=str(ROOT), check=True)

    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()


def make_thumbnail(mp4_path: Path, out_path: Path, at_seconds: float = 2.0) -> None:
    from PIL import Image, ImageDraw

    frame_path = out_path.with_suffix(".raw.png")
    subprocess.run(
        ["ffmpeg", "-y", "-ss", str(at_seconds), "-i", str(mp4_path),
         "-frames:v", "1", str(frame_path)],
        check=True,
    )
    img = Image.open(frame_path).convert("RGB")
    overlay = Image.new("RGB", img.size, (60, 60, 60))
    dimmed = Image.blend(img, overlay, 0.35)

    draw = ImageDraw.Draw(dimmed, "RGBA")
    w, h = dimmed.size
    cx, cy, r = w // 2, h // 2, 70
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(255, 255, 255, 255))
    tri = r * 0.5
    draw.polygon(
        [(cx - tri * 0.45, cy - tri), (cx - tri * 0.45, cy + tri), (cx + tri * 0.9, cy)],
        fill=(20, 20, 20, 255),
    )
    dimmed.save(out_path)
    frame_path.unlink()


if __name__ == "__main__":
    main()
