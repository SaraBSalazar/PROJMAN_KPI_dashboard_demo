# Running and sharing the dashboard

## 1. Just for you

```
cd "PROJMAN_KPI_dashboard_demo\Dashboard"
streamlit run KPI_Report.py
```

Opens automatically at `http://localhost:8501`. Only reachable from this computer.
Stop it with `Ctrl+C` in the terminal.

### Page structure

`KPI_Report.py` is just the router (`st.navigation({...})`) — it stays the file you run,
but its own Week/Month/Year content lives in `pages/0_Overview.py` so the sidebar can group
pages under section headings instead of listing them flat:

- **Reporting** — Overview (`pages/0_Overview.py`, the default page),
  Projects Review (`pages/1_Projects_Review.py`) and Publications & Courses
  (`pages/6_Publications_Courses.py` — papers, courses taken and taught, conference
  contributions, juries and outreach, logged per reporting period and tagged with the
  projects behind them)
- **Development** — 🎯 Special Projects (`pages/2_Special_Projects.py`),
  🛠️ Tools & AI Skills (`pages/3_Tools.py`), and 💡 Gains & Outputs
  (`pages/5_Gains.py` — what the special projects and tools are expected to
  deliver, and how much of that is **Delivered** (finished, gains banked), **In use &
  developing** (not finished, but already serving a real user project, or having spawned
  another development, or a tool that isn't deprecated), or still **Potential**)
- **Profile** — CV (`pages/7_CV.py` — the career record, with everything about the current
  role computed from the live files rather than written down, and every section editable
  behind the **✏️ Edit mode** toggle)
- **Data** — ⏱ Time Tracker (`pages/8_Time_Tracker.py` — a stopwatch over the same
  project / category / major-task vocabulary the Week editor uses, with the week drawn as
  a calendar and as a per-day breakdown, idle detection while a timer runs, an optional
  read-only Google Calendar layer, and an explicit, previewed push of that week into
  `track_time.csv`) and Add Data (`pages/4_Add_Data.py`)

Sidebar icons are Material Symbols (`":material/name:"`), which stay monochrome and take the
theme's ink colour; the browser-tab icon each page sets in its own `st.set_page_config` stays
an emoji, where a flat glyph is what's legible at 16px.

Because `st.navigation` is used, Streamlit's older "every file in `pages/` becomes a page"
discovery is switched off — a page appears in the sidebar only if it is listed in the
router, which is why the files can stay in `pages/` without being listed twice.

## Testing this demo

The real test is cloning it fresh somewhere else entirely, not just running it from a
folder that's already set up — that's what proves the repo is actually self-contained.

```powershell
cd $env:TEMP
git clone https://github.com/SaraBSalazar/PROJMAN_KPI_dashboard_demo.git
cd PROJMAN_KPI_dashboard_demo
pip install -r Dashboard\requirements.txt
cd Dashboard
streamlit run KPI_Report.py
```

It should open straight into a full fake year of data — no setup step, no missing-file
errors.

**A clone is a one-time snapshot, not a live link** — it won't pick up later pushes on
its own. If you already cloned it before and want the latest, go to the clone's root
folder (the one with `.git` in it — one level up if you're sitting inside `Dashboard`)
and pull:

```powershell
git pull
```

or delete it and clone again (simplest for a disposable test copy):

```powershell
cd $env:TEMP
Remove-Item -Recurse -Force PROJMAN_KPI_dashboard_demo
git clone https://github.com/SaraBSalazar/PROJMAN_KPI_dashboard_demo.git
```

**Fast check:** `python test_dashboard.py` (from the `Dashboard` folder) loads every page's
script with Streamlit's own `AppTest` and confirms none of them raised — seconds, no
browser needed. It only catches "a page crashed," not "a chart looks wrong," so it's a
first check, not a replacement for actually clicking around. What to check by hand, on
each page:

- **Week / Month / Year** (main page): switch tabs, pick a different week from the
  dropdown, confirm charts render and numbers look sane.
- **Projects Review**: the turnaround chart, complexity bubble chart, "who we work with" —
  the ones most likely to break if a chart function gets an unexpected column.
- **Special Projects**: click a bubble, confirm its project card and task checklist open.
- **Add Data**: add a dummy project, confirm it writes back to `Data/KPI_2025.xlsx`
- **Time Tracker**: start the timer, stop it, confirm the block appears on the Calendar
  tab and the row in the Entries table; then open "⬆ Send this week to the time log" and
  check the proposed row before writing it
  without error.
- **Tools & AI Skills**: table and gallery render.

Also try `http://localhost:8501/?readonly=true` and confirm every editing control
disappears. Stop the server with `Ctrl+C` when done.

Then the snapshot exporter, from the repo root:

```powershell
cd ..
python Dashboard\export_snapshot.py
```

Should write `Share\KPI_Report_snapshot.html` — open it directly in a browser (no server
needed) and click through its tabs the same way.

And the data generator, which should exactly reproduce the same fake year (fixed random
seed) — a good way to undo any test edits made above:

```powershell
python generate_demo_data.py
```

Since this is a fresh clone, any error here is either a real bug or a genuinely missing
file, not an artifact of wherever it was developed.

## The CV page and where its numbers come from

The CV page reads as a CV — stat cards, a year-by-year table, then collapsible Details
sections — built as live markup by `kpi_cv_view.py` and wearing the dashboard's own palette
and typography. A mark can sit beside the name: put `logo.gif` (and optionally
`logo_dark.gif`) in `Dashboard/static/` and it appears; the demo ships none.

**✏️ Edit mode** (top right) is the only thing that changes the page: on, an editor appears
under each section — each role's summary line and bullets as a form, every list section as
a table — and the view itself stays exactly where it was. Off, there is nothing to click.

It mixes two kinds of content on purpose, and the line between them matters:

- **What the dashboard already knows** — projects delivered, research groups, tools and AI
  skills built, time to deliver, turnaround by project size, publications and courses
  logged. None of this is stored in the CV. It is recomputed on every load by
  `kd.cv_role_metrics()` from the period workbooks, the time log, `tools.xlsx` and the two
  output stores, so the CV cannot fall behind the tracker. `cv_data.json`'s own README says
  the same thing from the other side: those figures are deliberately *not* in the file.
  (In this demo they come from invented data, like everything else here.)
- **What only the CV knows** — roles, education, skills, awards, profiles. That is
  `Data/cv_data.json`, editable on the page, mirrored to `cv_data.xlsx`.

Publications, courses, teaching and conference contributions sit across both: the lifetime
list lives in the CV store, and anything logged against a reporting period on the
Publications & Courses page is folded into the matching CV section at display time, tagged
with its period and project tags (the blue "ADA 2025–2026" mark). Matching is on title (and
venue, for conferences), ignoring case and punctuation — so logging a paper that is already
on the CV annotates that line instead of adding a second one. Nothing is copied between the
stores; each stays the single source of truth for what it holds.

If you keep a standalone, hand-built CV page of your own at `Data/CV_dashboard.html` — one
that marks the dashboard's figures with `data-metric` spans fed by a single JSON block — an
**⬇️ export** button appears at the foot of the page: it fills those in with what the tracker
says right now and hands back a copy to send or print, leaving the file in `Data/` untouched.
Without that file there is simply no export section.

The CV is **not** in the exported snapshot in `Share/`. A CV is personal, so it stays in the
live app only.

### Connecting a Google Calendar to the Time Tracker (no coding needed)

The Time Tracker can draw your calendar's events behind your tracked time, so you can see
what the week was meant to be next to what it actually was. It only ever *reads* — it
cannot change, add or delete anything in your calendar.

1. Open **Google Calendar** in a browser on a computer (not the phone app).
2. In the left-hand list, hover the calendar you want, click its **⋮** menu, and choose
   **Settings and sharing**.
3. Scroll down to **Integrate calendar**.
4. Copy **Secret address in iCal format** — the long one ending in `.ics`. Click the eye
   icon first if it's hidden.
5. In the dashboard, open **Time Tracker → 📅 Connect your Google Calendar**, paste it in
   the box, and click **Save**.

That's it. Your meetings appear as grey blocks behind the week.

**Secret or public?** Either works — the dashboard just downloads the file. The **public**
address (`…/public/basic.ics`) only exists while the calendar is shared publicly with the
whole internet, which a work calendar shouldn't be; if it isn't, Google answers `404`. The
**secret** address works whatever the sharing settings are, which is why it's the one to
use. Treat it like a password — anyone holding it can read that calendar. It is stored on
that computer only, never in the project folder and never in git.

**Other calendars.** Anything that publishes an `.ics` URL works the same way — Outlook /
Microsoft 365 ("Publish a calendar"), Apple iCloud ("Public Calendar"), Nextcloud, and so
on. If the link ends in `.ics` and starts with `https://`, paste it in.

### What keeps counting when things stop

A running timer is **a start timestamp in a file**, not a process counting. So:

| What happens | The timer | Why |
| --- | --- | --- |
| **Internet drops** | unaffected | Everything the tracker touches is a local file. |
| **You close the browser tab** | still running | The entry is open in `time_entries.csv`; reopen the page and it is still going, with the right elapsed time. |
| **You stop `streamlit run`, or reboot** | still "running" when you come back | Nothing wrote an end time, so the entry stays open. This is the one case that over-counts — and it is what the away prompt catches: the stretch shows up as *the tracker wasn't running*, with a button to cut it. |
| **The machine sleeps** | same as above | A poll arriving late is read as a gap, not as work. |
| **The calendar can't be reached** | unaffected | The planned layer falls back to the last downloaded copy and says when that was. Nothing else on the page needs a network. |

## 2. Sharing with someone on the same WiFi/network

`localhost` always means "this machine" to whoever opens the link — on someone else's
computer, `http://localhost:8501` points at *their* machine, not yours. To actually let
them reach your dashboard, start it bound to your network interface instead:

```
streamlit run KPI_Report.py --server.address 0.0.0.0
```

Then find your computer's LAN IP:

```
ipconfig
```

Look for "IPv4 Address" (e.g. `192.168.1.175`). Give the other person:

```
http://192.168.1.175:8501
```

This only works while:

- your computer is on and the `streamlit run` command is still running in a terminal
- both of you are on the same WiFi/network (or same VPN)
- Windows Firewall isn't blocking the connection (it may prompt the first time — allow it)

## 3. Read-only link (view-only, no editing controls)

**The Time Tracker is deliberately absent from both kinds of sharing.** It is not in the
exported snapshot — `export_snapshot.py` builds its own fixed list of tabs and emits static
HTML with no editing controls in it at all. And `?readonly=true` doesn't offer the page
either: a stopwatch with every control hidden is a blank page, so the router leaves it out
of the sidebar entirely. A test asserts both.

Append `?readonly=true` to any page's URL, e.g.:

```
http://192.168.1.175:8501/?readonly=true
```

This is **not a password or a login** — it's a display flag. Anyone who has the plain link
(without `?readonly=true`) still gets the full editable dashboard; anyone who edits the URL
in their own browser to remove `?readonly=true` gets the editable version too. It only
stops a *casual* viewer from accidentally clicking a save button — it does not stop someone
who deliberately wants to edit. If you ever need a real access boundary (so a specific
person genuinely *cannot* edit even on purpose), that needs actual authentication, which
isn't built here.

You don't start a different process or run a different command for this — it's the exact
same running server either way. Just:

- keep using the plain link (`http://192.168.1.175:8501`) yourself
- hand out the `?readonly=true` version to whoever you only want viewing

**Sharing the read-only link beyond your own network** (e.g. someone at home, you at the
office) needs actual hosting — Streamlit Community Cloud, a tunnel like ngrok, or a server
— which is a separate step since your data files live locally. Ask if you want that set up
for the read-only view.

## 4. Does the link keep working if you close VS Code / shut down?

**No.** The dashboard only exists while the `streamlit run` command is actively running in
a terminal, on your computer. If you:

- close the terminal / close VS Code's integrated terminal running it → the server stops
- put the computer to sleep or shut it down → the server stops

the link (local or shared on LAN) stops working immediately for everyone, including you.
There's no "keep it running in the background permanently" without either leaving the
computer on with the command running, or moving to real hosting (see the note in section 3).

## Sharing when the computer is off (read-only snapshot)

The live dashboard needs `streamlit run` going on your machine — but you can export a
**static, read-only snapshot** that works anywhere, anytime, with nothing running:

```
cd PROJMAN_KPI_dashboard_demo\Dashboard
python export_snapshot.py
```

This writes `../Share/KPI_Report_snapshot.html` — one self-contained file with the
week/month/year charts, the project turnaround, the special-projects cards, tasks and
predicted timelines, and the tools inventory, frozen at the moment you export. Nothing in
it is editable.

**It browses like the dashboard, not like a report.** The page carries the same navigation
you use in Streamlit: a reporting-period selector, tabs for Overview / Week / Month / Year /
Turnaround / Special projects / Tools, and pickers for the week, the month and the special
project. Every one of those views is built at export time and the browser just switches
between them, so clicking around is instant and still needs no server — you are not
scrolling through one long page any more. It follows the reader's light/dark theme, and old
links like `…snapshot.html#week` still open that tab.

What it is *not*: live. The numbers are whatever the Excel/CSV files said at export time, so
a week logged after the export only appears once the snapshot is rebuilt (weekly, below).
Nothing on the page can be edited — editing stays in the Streamlit dashboard.

Two ways to share it:

1. **Hosted web page (recommended)** — the snapshot is published as a private Claude
   artifact at a stable link; open it from `/artifacts` in Claude Code (or
   claude.ai/code/artifacts) and use the page's share menu to give colleagues access.
   The link keeps working with your computer off. It refreshes itself weekly (below), or
   ask Claude to "re-export and republish the KPI snapshot" — the link stays the same.
2. **The file itself** — send `KPI_Report_snapshot.html` by email/OneDrive; it opens
   in any browser with no internet needed (recipients download it first — OneDrive
   previews HTML as text rather than rendering it).

### Optional: scheduled auto-refresh

`publish_snapshot.ps1` re-exports the snapshot and republishes it to an existing Claude
artifact link, so viewers always see recent data without anyone re-running anything by
hand. It's not configured out of the box — you need your own artifact link, a local
Python, and the Claude Code CLI. Fill those in as parameters (see the comment at the top
of the script) and run it once to confirm it works:

```
powershell -ExecutionPolicy Bypass -File publish_snapshot.ps1 -ArtifactUrl "https://claude.ai/code/artifact/..." -Python "C:\path\to\python.exe"
```

Then point a Windows Task Scheduler job at that same command on whatever cadence you
want (weekly, daily, ...). A few things worth knowing:

- **Computer off at the scheduled time?** Set the task to *start when available* so it
  runs the next time the machine is on. (Refreshing needs the local Excel/CSV files, so
  it can only happen while the machine is on — the shared link itself stays up regardless.)
- **A data file open in Excel?** The run skips cleanly and leaves the existing link alone
  rather than publishing a half-built page.
- **Check what happened:** `Dashboard/publish_snapshot.log` (or wherever `-LogFile` points).

## What gets saved where

| What you edit in the dashboard                                       | Saved to                                                                                                               |
| -------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| Week tab's time log table                                            | `Data/track_time.csv`                                                                                                |
| Time Tracker → clicking a block on the calendar (Save / Delete / "start a new timer like this") | `Data/time_entries.csv`. Clicking a grey *calendar* block offers to track the meeting instead — there is no Save on one, because the dashboard only ever reads a calendar. |
| Time Tracker → "📌 Which projects the pickers offer" | `Data/tracker_prefs.json` — the pinned list and the hide-finished toggle. Finished means the project tracker gave it a Closing Day. |
| Time Tracker → ▶ Start / ⏹ Stop / 🗑 Discard, the Entries table, "➕ Add an entry by hand" | `Data/time_entries.csv` (one row per stretch; a blank `end` is the timer still running). Any brand-new tag typed in also goes to `Data/custom_tags.json`. |
| Time Tracker → "⬆ Send this week to the time log"                   | `Data/track_time.csv` — the **only** place the tracker touches the time log. One row per project / category / major task per week: a matching row is overwritten in place, an unmatched one is appended, everything else left alone. Previewed and editable before it writes; pushing a week twice changes nothing. |
| Time Tracker → away prompt and ⚙ Away detection                     | `Data/time_entries.csv` for the split entries, plus the watcher's own record (watch/idle spans, the threshold, what you've already dismissed) in your user app-data folder — machine-local, never in the project folder. Deleting it loses nothing but the ability to ask about stretches already past. |
| Time Tracker → "📅 Connect your Google Calendar"                    | the calendar address and options, in that same machine-local folder, with the last downloaded copy of the calendar beside it. **Never** in the project folder or git: the secret iCal address is a credential. The dashboard only ever downloads — it has no way to change a calendar. |
| Special Projects → "All ratings" table                              | `Data/Special_Projects_Ratings.xlsx`                                                                                 |
| Projects Review → "Non-quantifiable project outputs" table          | the period's`Data/KPI_*.xlsx`                                                                                   |
| Add Data → new project / edit project / new meeting                 | the period's`Data/KPI_*.xlsx`                                                                                   |
| Special Projects → "✏️ Edit this project" (incl. renaming, ✅ finished)        | `Data/Special_Projects_Ratings.xlsx` (a rename also moves that project's task checklist, so its tasks follow it)     |
| Special Projects → per-project task checklist (incl. planned dates) | `Data/special_project_tasks.json` (source of truth, mirrored to `Data/Special_Projects_Tasks.xlsx` on every edit)  |
| Projects Review → "Beyond projects" cards                           | `Data/beyond_projects.json` (source of truth, mirrored to `Data/Beyond_Projects.xlsx` on every save)               |
| Publications & Courses → "Publications"                              | `Data/publications.json` (source of truth, mirrored to `Data/Publications.xlsx` on every save). This section used to sit on Projects Review, which no longer carries it. |
| Publications & Courses → courses, teaching & juries, conferences, outreach | `Data/cv_outputs.json` (source of truth, mirrored to `Data/CV_Outputs.xlsx` on every save) — one record per output, with a *kind* that groups it |
| CV → "✏️ Edit this role" (summary line and bullets), and every section's "✏️ Edit" table | `Data/cv_data.json` (source of truth, mirrored to `Data/cv_data.xlsx` on every save). **The workbook is never read back** — edit the CV on the page, not in Excel, or the next save will overwrite what you typed there. |
| Week tab → "➕ New tag" (project / category / major task)           | `Data/custom_tags.json` (so new tags stay in the dropdowns across restarts, even before they're used in a saved row) |
| Tools & AI Skills → "Edit a tool" and the "All tools" table         | `Data/tools.xlsx`                                                                                                    |
| Projects Review → Turnaround → "⏸ Pauses" note / forgive checkbox  | `Data/project_pause_notes.json` (forgiving a pause subtracts just its days from that project's turnaround figures, rather than excluding the whole project) |
| Gains & Outputs → "✏️ Edit what delivers what" / "✏️ Edit value potential" | `Data/gains.xlsx` |
| Special Projects / Tools card → "🔗 Reuse & lineage"                | `Data/gains.xlsx` (Reuse sheet) — the same control on both pages |

Everything in the table above writes to disk immediately when you click its Save/Add
button — nothing is held only in the browser session, and everything you can change ends up
in an Excel file (the JSON files are the dashboard's working copy and are mirrored to
`Special_Projects_Tasks.xlsx`, `Beyond_Projects.xlsx`, `Publications.xlsx`, and
`CV_Outputs.xlsx`). The one exception is
`custom_tags.json`, which just remembers dropdown options until you use them in a row — once
used, the tag lives in `track_time.csv` like any other value.

The per-task checkboxes and dates on the Special Projects page save the moment you change
them (there's no button, so nothing can be lost by navigating away); everything else has an
explicit Save button.

One caveat: a file that is open in
Excel (or being synced by OneDrive/Dropbox/etc.) is write-locked — the dashboard will tell
you with a friendly message instead of crashing; close the file in Excel and click Save
again. The JSON files are deliberately separate from the Excel files since they track
things (a nested to-do list, free-text cards) that don't correspond to any existing column.
