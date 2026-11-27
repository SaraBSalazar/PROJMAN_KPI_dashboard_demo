"""The CV page's read view, as HTML.

A CV laid out the way a standalone CV page would be -- stat cards, a year-by-year table,
then collapsible sections -- but as markup the dashboard fills from live data, wearing the
dashboard's own palette and typography so the page belongs to the app.

Streamlit-free on purpose (like kpi_data): every function here returns a string, so the page
just prints them and the same builders could feed an export later. Everything that comes from
the tracker is passed in already computed -- this module never reads a file.
"""

import html as html_mod
import re

# Dashboard tokens, same values as kpi_style/.streamlit/config.toml. Kept as one dict per
# theme so the whole sheet below is written once against token names.
LIGHT = dict(surface="#ffffff", ink="#1a1a1a", ink2="#52514e", muted="#898781",
             line="#e1e0d9", accent="#1f5c99", accent_soft="#eef3f8")
DARK = dict(surface="#232321", ink="#e8e8e6", ink2="#d0cec7", muted="#938f87",
            line="#3c3b38", accent="#4a84c9", accent_soft="#223042")

SANS = '"IBM Plex Sans", "Segoe UI", system-ui, sans-serif'
MONO = '"IBM Plex Mono", ui-monospace, monospace'


def css(dark=False):
    """The one <style> block the view needs. Class names are cv-prefixed where they could
    collide with Streamlit's own, and the markup below uses no id selectors at all."""
    t = DARK if dark else LIGHT
    return f"""<style>
.cv h1 {{ font: 700 30px/1.15 {SANS}; letter-spacing: -0.015em; margin: 0 0 2px; color: {t['ink']}; }}
.cv .role {{ color: {t['accent']}; font-weight: 600; margin: 0 0 6px; }}
.cv .contact {{ margin: 0 0 12px; font-size: 14px; }}
.cv .about {{ margin: 0 0 26px; max-width: 70ch; color: {t['ink']}; }}
.cv .who {{ display: flex; align-items: center; gap: 22px; }}
.cv .who .mark {{ flex: none; width: 180px; height: auto; }}
.cv .who > div {{ min-width: 0; }}
@media (max-width: 680px) {{ .cv .who {{ flex-direction: column; align-items: flex-start; gap: 10px; }}
  .cv .who .mark {{ width: 120px; }} }}
.cv h2 {{ font: 650 18px/1.2 {SANS}; letter-spacing: -0.01em; margin: 26px 0 10px; color: {t['ink']}; }}
.cv .grp {{ font: 600 15px/1.2 {SANS}; margin: 0 0 10px; color: {t['muted']};
  text-transform: uppercase; letter-spacing: 0.06em; }}
.cv .stats {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(170px, 1fr));
  gap: 12px; margin-bottom: 26px; }}
.cv .stat {{ background: {t['surface']}; border: 1px solid {t['line']}; border-radius: 12px;
  padding: 14px; }}
.cv .stat b {{ display: block; font: 600 32px/1 {MONO}; font-variant-numeric: tabular-nums;
  color: {t['accent']}; }}
.cv .stat.sm b {{ font: 650 20px/1.25 {SANS}; }}
.cv .stat span {{ display: block; margin-top: 6px; font-size: 13px; color: {t['muted']};
  line-height: 1.35; }}
.cv .stat.w {{ grid-column: span 2; }}
.cv .stat.f {{ grid-column: 1 / -1; }}
.cv .stat.cur {{ border-left: 3px solid {t['accent']}; }}
.cv .stat .lab {{ font-weight: 600; color: {t['ink']}; font-size: 14px; margin: 0; }}
.cv .stat ul.mini {{ list-style: none; margin: 10px 0 0; padding: 0; font-size: 13px; }}
.cv .stat ul.mini li {{ display: flex; justify-content: space-between; gap: 10px;
  padding: 4px 0; border-top: 1px solid {t['line']}; }}
.cv .stat ul.mini li span {{ display: inline; margin: 0; font-size: 13px; color: {t['ink2']}; }}
.cv .stat ul.mini li b {{ display: inline; font: 600 13px/1.3 {SANS}; color: {t['accent']};
  white-space: nowrap; }}
.cv .chips {{ display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }}
.cv .chips i {{ font-style: normal; background: {t['accent_soft']}; color: {t['accent']};
  border-radius: 99px; padding: 2px 10px; font-size: 13px; }}
.cv .bar {{ display: flex; align-items: center; gap: 10px; margin-top: 10px; }}
.cv .bar > span {{ display: block; flex: none; width: 58px; margin: 0; color: {t['ink2']};
  font-weight: 600; font-size: 13px; }}
.cv .trk {{ flex: 1; height: 8px; background: {t['line']}; border-radius: 99px; overflow: hidden; }}
.cv .trk i {{ display: block; height: 100%; background: {t['accent']}; border-radius: 99px; }}
.cv .bar b {{ display: inline; flex: none; font: 600 13px/1 {SANS}; color: {t['accent']}; }}
.cv .yt {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
.cv .yt th, .cv .yt td {{ text-align: left; padding: 8px 16px; border-top: 1px solid {t['line']};
  vertical-align: top; color: {t['ink2']}; }}
.cv .yt tr:first-child th {{ border-top: 0; color: {t['muted']}; font-weight: 600; }}
.cv .yt th.sec {{ color: {t['muted']}; font-weight: 600; padding-top: 16px; }}
.cv .yt .n {{ text-align: right; font-variant-numeric: tabular-nums; font-family: {MONO}; }}
.cv .yt small {{ display: block; color: {t['muted']}; font-size: 12px; font-family: {SANS}; }}
.cv details {{ background: {t['surface']}; border: 1px solid {t['line']}; border-radius: 12px;
  margin-bottom: 8px; }}
.cv details details {{ border: 0; border-top: 1px solid {t['line']}; border-radius: 0; margin: 0;
  background: none; }}
.cv summary {{ cursor: pointer; list-style: none; padding: 13px 16px; display: flex;
  align-items: center; gap: 10px; font-weight: 600; color: {t['ink']}; }}
.cv summary::-webkit-details-marker {{ display: none; }}
.cv summary::before {{ content: ""; flex: none; width: 7px; height: 7px;
  border-right: 2px solid {t['accent']}; border-bottom: 2px solid {t['accent']};
  transform: rotate(-45deg); transition: transform .15s; }}
.cv details[open] > summary::before {{ transform: rotate(45deg); }}
.cv summary .n {{ margin-left: auto; background: {t['accent_soft']}; color: {t['accent']};
  border-radius: 99px; padding: 1px 10px; font-size: 13px; font-weight: 600; }}
.cv summary .t {{ flex: 1; min-width: 0; }}
.cv summary .t small {{ display: block; font-weight: 400; color: {t['muted']}; font-size: 13px; }}
.cv summary .d {{ flex: none; font-weight: 400; color: {t['muted']}; font-size: 13px;
  text-align: right; }}
.cv ul {{ list-style: none; margin: 0; padding: 0 16px 8px; }}
.cv li {{ padding: 9px 0; border-top: 1px solid {t['line']}; color: {t['ink']}; }}
.cv li small {{ display: block; color: {t['muted']}; font-size: 13px; }}
.cv .lead {{ margin: 0; padding: 0 16px 6px 33px; color: {t['ink2']}; font-style: italic; }}
.cv ul.out {{ list-style: disc; padding: 0 16px 14px 52px; }}
.cv ul.out li {{ border: 0; padding: 3px 0; color: {t['ink2']}; }}
.cv h3 {{ font: 600 13px/1.3 {SANS}; margin: 0; padding: 12px 16px 0; color: {t['muted']};
  text-transform: uppercase; letter-spacing: 0.06em; }}
.cv .note {{ padding: 0 16px 10px; color: {t['muted']}; font-size: 13px; margin: 0; }}
.cv p.note.loose {{ padding: 0; margin: -16px 0 18px; }}
.cv a {{ color: {t['accent']}; }}
.cv li a.pt {{ color: {t['ink']}; text-decoration: none; }}
.cv li a.pt:hover {{ color: {t['accent']}; text-decoration: underline; }}
.cv .tag {{ display: inline-block; margin-left: 6px; background: {t['accent_soft']};
  color: {t['accent']}; border-radius: 99px; padding: 0 8px; font-size: 12px; font-weight: 600; }}
.cv .tag.ada {{ background: {t['accent']}; color: {t['surface']}; }}
.cv .tg {{ font-style: normal; font-weight: 600; font-size: 12px; color: {t['accent']};
  background: {t['accent_soft']}; border-radius: 99px; padding: 0 8px; margin-left: 8px;
  white-space: nowrap; }}
.cv .tg.e {{ background: {t['line']}; color: {t['muted']}; }}
@media (max-width: 560px) {{ .cv summary .d {{ display: none; }} .cv .stat.w {{ grid-column: span 1; }} }}
</style>"""


def esc(value):
    text = "" if value is None else str(value).strip()
    return html_mod.escape("" if text in ("nan", "None", "NaT") else text)


_ISO = re.compile(r"^(\d{4})-(\d{2})(?:-(\d{2}))?$")


def fmt_date(value):
    """'2026-10' -> 'Oct 2026', '2026-06-30' -> '30 Jun 2026'. Anything else (a year, a range,
    'May – Jun 2026') is left exactly as written -- the CV's own phrasing wins."""
    text = "" if value is None else str(value).strip()
    match = _ISO.match(text)
    if not match:
        return text
    year, month, day = match.group(1), int(match.group(2)), match.group(3)
    name = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
            "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")[month - 1]
    return f"{int(day)} {name} {year}" if day else f"{name} {year}"


def _join(parts, sep=" · "):
    return sep.join(p for p in parts if p)


# --- small pieces ---------------------------------------------------------------------------
def stat(value=None, label="", mini=None, chips=None, lab=None, bars=None,
         wide=False, full=False, current=False):
    """One card in a stat grid. `value`+`label` is the plain number-and-caption form; `lab`
    replaces the number with a bold heading (the "Programming" / "Main research topics" form);
    `mini` is the name→value list, `chips` the pill row, `bars` the proficiency meters."""
    # A value that isn't a short number ("7 in 4 countries", "28 → 24 days") is a phrase, not
    # a display figure: at 32px it wraps into the caption and stops reading as one.
    long_value = value is not None and len(str(value)) > 5
    classes = ("stat" + (" w" if wide else "") + (" f" if full else "")
               + (" cur" if current else "") + (" sm" if long_value else ""))
    out = [f'<div class="{classes}">']
    if value is not None:
        out.append(f"<b>{esc(value)}</b>")
    if lab:
        out.append(f'<span class="lab">{lab}</span>')
    if label:
        out.append(f"<span>{esc(label)}</span>")
    for name, level, pct in bars or []:
        out.append(f'<div class="bar"><span>{esc(name)}</span><div class="trk">'
                   f'<i style="width:{pct}%"></i></div><b>{esc(level)}</b></div>')
    if mini:
        out.append('<ul class="mini">' + "".join(
            f"<li><span>{esc(name)}</span><b>{esc(val)}</b></li>" for name, val in mini) + "</ul>")
    if chips:
        out.append('<div class="chips">' + "".join(f"<i>{esc(c)}</i>" for c in chips if c) + "</div>")
    out.append("</div>")
    return "".join(out)


def stats_grid(cards, heading=None):
    head = f'<p class="grp">{esc(heading)}</p>' if heading else ""
    return head + '<div class="stats">' + "".join(cards) + "</div>"


def details(summary, body, count=None, open_=False):
    badge = f'<span class="n">{esc(count)}</span>' if count is not None else ""
    return (f'<details{" open" if open_ else ""}><summary>{summary}{badge}</summary>'
            f"{body}</details>")


def li(main, small=None, tag=None, link=None):
    body = f'<a class="pt" href="{esc(link)}" target="_blank" rel="noopener">{main}</a>' if link else main
    tag_html = f'<span class="tag">{esc(tag)}</span>' if tag else ""
    small_html = f"<small>{small}</small>" if small else ""
    return f"<li>{body}{tag_html}{small_html}</li>"


def ul(items):
    return "<ul>" + "".join(items) + "</ul>"


def ada_tag(row):
    """The "logged in the service's own records" mark: the reporting period, plus the project
    tags the entry was linked to. Only ever set by the merge in kpi_data, so an entry that
    only exists on the CV never carries one."""
    if not row.get("ada"):
        return ""
    bits = [f'<span class="tag ada">ADA {esc(row.get("period"))}</span>' if row.get("period") else ""]
    tags = [t.strip() for t in str(row.get("projects") or "").split(",") if t.strip()]
    bits += [f'<span class="tag">{esc(t)}</span>' for t in tags]
    return "".join(bits)


# --- the page's sections ----------------------------------------------------------------------
def header(profile, mark_url=None):
    """Name, role line, contact and summary -- with the ADA mark beside them when one is
    given. The mark is an <img> in this markup rather than an st.image so an animated GIF
    stays animated; Streamlit serves it out of the app's static/ folder."""
    email = esc(profile.get("email"))
    who = (f'<h1>{esc(profile.get("name"))}</h1>'
           f'<p class="role">{esc(profile.get("role"))}</p>'
           f'<p class="contact"><a href="mailto:{email}">{email}</a></p>'
           f'<p class="about">{esc(profile.get("about"))}</p>')
    if not mark_url:
        return who
    return (f'<div class="who"><img class="mark" src="{esc(mark_url)}" alt="" aria-hidden="true">'
            f"<div>{who}</div></div>")


def written_stats(cv_stats, section, heading):
    """The stat cards the CV itself carries (Institutional experience, Specific expertise) --
    one card per row of the cv_stats section, value and caption as written."""
    # A long caption needs the room: these cards are written by hand, so their length is the
    # only signal available for how much space one wants.
    cards = [stat(value=row.get("value"), label=row.get("label"),
                  wide=len(str(row.get("label", ""))) > 58)
             for row in cv_stats if str(row.get("section", "")).strip() == section]
    return stats_grid(cards, heading) if cards else ""


def _arrow(values, suffix=""):
    """'9 → 7' across reporting periods, oldest first -- the shape the original CV used to
    show a figure moving between years, and it degrades to just the number for one period."""
    parts = [v for v in values if v not in (None, "")]
    return " → ".join(str(p) for p in parts) + (f" {suffix}" if parts and suffix else "")


def current_role(metrics, outputs, format_days, heading="Current role"):
    """The live block: nothing here is written down anywhere, it is all computed from the
    tracker, the tools inventory and the output stores.

    `heading` is the caller's to choose -- it is the one line on this page that names the
    institution, and not every copy of this dashboard is at the same one."""
    periods = metrics["periods"]
    totals = metrics["totals"]
    if not periods:
        return ""
    oldest_first = list(reversed(periods))
    latest = periods[0]

    def kind(kinds):
        return [o for o in outputs if o.get("kind") in kinds]

    cards = [
        stat(value=totals["delivered"],
             label=f"projects delivered with a final report since "
                   f"{totals['since'].strftime('%b %Y') if totals.get('since') is not None else '—'}"
                   f" ({latest['delivered']} so far in {latest['label']})"),
        stat(value=totals["consulting"],
             label=f"consulting projects · {totals['meetings']} consultation meetings"),
        stat(value=_arrow([p["groups"] for p in oldest_first]),
             label=f"research groups engaged ({_arrow([p['label'] for p in oldest_first])})"),
        stat(value=_arrow([round(p["median_working_days"]) for p in oldest_first
                           if p["median_working_days"] is not None], suffix="days"),
             label="typical time to deliver: from data in hand to final report sent"),
        stat(value=totals["tools"],
             label="tools and AI skills built for projects and for internal project organisation"),
    ]

    taught = kind(["Course taught"])
    if taught:
        cards.append(stat(
            value=len(taught), wide=True,
            label=("course" if len(taught) == 1 else "courses") + " built and taught",
            mini=[(_join([t.get("title"), t.get("where")]),
                   _join([t.get("scale"), fmt_date(t.get("date"))])) for t in taught]))

    posters = kind(["Conference poster", "Conference talk"])
    if posters:
        cards.append(stat(
            value=len(posters), wide=True, label="conference contributions",
            mini=[(_join([p.get("title"), p.get("where")], " — "), fmt_date(p.get("date")))
                  for p in posters]))

    courses = kind(["Course attended", "Certification"])
    if courses:
        cards.append(stat(
            value=len(courses), wide=True, label="courses and certifications since the role began",
            mini=[(_join([c.get("title"), c.get("where")], " — "), fmt_date(c.get("date")))
                  for c in courses]))

    as_of = totals.get("as_of")
    note = (f'<p class="note loose">From the ADA group KPI tracking, '
            f'{totals["since"].strftime("%d %b %Y") if totals.get("since") is not None else "—"} to '
            f'{as_of.strftime("%d %b %Y") if as_of is not None else "—"}. '
            f'The {latest["label"]} reporting year is still running. Everything in this block is '
            f'read from the live files — it is never stored in the CV.</p>')
    return stats_grid(cards, heading) + note


def year_table(metrics, outputs_by_period, format_days):
    """The original's "Year by year" table, now built from the same live figures."""
    periods = metrics["periods"]
    if not periods:
        return ""
    labels = [p["label"] for p in periods]
    rows = [("Projects in the period", [p["projects_total"] for p in periods], None),
            ("Active / concluded", [f"{p['active']} / {p['concluded']}" for p in periods], None),
            ("Delivered with a final report", [p["delivered"] for p in periods], None),
            ("Consulting projects", [p["consulting"] for p in periods], None),
            ("Research groups engaged", [p["groups"] for p in periods], None),
            ("Time to deliver<small>data in hand to final report sent</small>",
             [format_days(p["median_working_days"]) for p in periods], None),
            ("Full turnaround<small>first contact to final report</small>",
             [format_days(p["median_total_days"]) for p in periods], None)]
    for i, band in enumerate(periods[0]["bands"]):
        rows.append((f"Turnaround, {band['label'].lower()} projects ({band['range_label']})",
                     [(f"{format_days(p['bands'][i]['median_days'])}"
                       f"<small>{p['bands'][i]['n']} project"
                       f"{'s' if p['bands'][i]['n'] != 1 else ''}</small>")
                      if p["bands"][i]["median_days"] is not None else "none" for p in periods],
                     None))
    rows.append(("Tools and AI skills built",
                 [(f"{len(p['tools'])}<small>{esc(', '.join(p['tools']))}</small>"
                   if p["tools"] else "none") for p in periods], None))

    def count(label, kinds):
        entries = [o for o in outputs_by_period.get(label, []) if o.get("kind") in kinds]
        return (f"{len(entries)}<small>{esc(', '.join(e.get('where') or e.get('title') or '' for e in entries))}</small>"
                if entries else "none")

    rows.append(("Teaching and learning", None, "section"))
    rows.append(("Courses taught", [count(l, ["Course taught"]) for l in labels], None))
    rows.append(("Thesis juries", [count(l, ["Thesis jury"]) for l in labels], None))
    rows.append(("Courses and certifications attended",
                 [count(l, ["Course attended", "Certification"]) for l in labels], None))
    rows.append(("Conference contributions",
                 [count(l, ["Conference poster", "Conference talk"]) for l in labels], None))
    rows.append(("Publications", [p["publications"] for p in periods], None))

    body = ["<tr><th>Metric</th>" + "".join(f'<th class="n">{esc(l)}</th>' for l in labels) + "</tr>"]
    for name, values, mode in rows:
        if mode == "section":
            body.append(f'<tr><th class="sec" colspan="{len(labels) + 1}">{name}</th></tr>')
            continue
        body.append(f"<tr><td>{name}</td>"
                    + "".join(f'<td class="n">{v}</td>' for v in values) + "</tr>")
    table = ('<div style="overflow-x:auto;padding-bottom:8px"><table class="yt">'
             + "".join(body) + "</table></div>")
    note = ('<p class="note">Medians leave out internal projects and any project whose dates '
            "can't be read — the same basis as the Projects Review turnaround section.</p>")
    return details(f'Year by year <span class="n">{esc(" vs ".join(labels))}</span>',
                   table + note)


def outputs_stats(counts, cv_stats, extra=None):
    """The "Outputs" grid, counted from the lists rather than written down."""
    cards = [
        stat(value=counts["papers"],
             label=f"peer-reviewed papers ({counts['first_author']} first author)"
                   + (f", plus {counts['preprints']} preprint" if counts["preprints"] else "")),
        stat(value=counts["contributions"],
             label=f"conference contributions: {counts['posters']} posters, {counts['talks']} orals"),
    ]
    cards += extra or []
    return stats_grid(cards, "Outputs")


def experience(entries, bullets_for, date_label):
    """Roles as nested collapsibles, exactly the original's shape: title and organisation on
    the left of the summary, dates on the right, summary line and bullets inside."""
    inner = []
    for entry in entries:
        body = ""
        if str(entry.get("lead") or "").strip():
            body += f'<p class="lead">{esc(entry["lead"])}</p>'
        points = bullets_for(entry.get("id"))
        if points:
            body += '<ul class="out">' + "".join(f"<li>{esc(p)}</li>" for p in points) + "</ul>"
        summary = (f'<span class="t">{esc(entry.get("title"))}'
                   f'<small>{esc(_join([entry.get("organisation"), entry.get("location")]))}</small>'
                   f'</span><span class="d">{esc(date_label(entry))}</span>')
        inner.append(f"<details><summary>{summary}</summary>{body or ''}</details>")
    return details("Experience", "".join(inner), count=len(entries), open_=True)


def publications(rows):
    items = []
    preprints = sum(1 for r in rows if str(r.get("type", "")).lower() == "preprint")
    for row in rows:
        doi = esc(row.get("doi"))
        url = esc(row.get("url")) or (f"https://doi.org/{doi}" if doi else "")
        venue = esc(row.get("venue"))
        year = esc(row.get("year"))
        doi_link = (f'<a href="https://doi.org/{doi}" target="_blank" rel="noopener">doi {doi}</a>'
                    if doi else "")
        small = _join([venue, year, doi_link]) + ada_tag(row)
        items.append(li(esc(row.get("title")), small=small,
                        tag="First author" if row.get("first_author") else None,
                        link=url or None))
    count = f"{len(rows) - preprints}" + (f" + {preprints} preprint" if preprints else "")
    return details("Publications", ul(items), count=count)


def conferences(rows, rollup_count):
    """Orals first, then posters, like the original -- and the roll-up row ("14 further
    posters") becomes the closing note rather than a list entry."""
    orals, posters, note_rows = [], [], []
    for row in rows:
        if rollup_count(row) > 1:
            note_rows.append(row)
        elif str(row.get("type", "")).lower() in ("oral", "talk"):
            orals.append(row)
        else:
            posters.append(row)

    def item(row):
        note = esc(row.get("note"))
        small = _join([esc(row.get("event")), esc(fmt_date(row.get("date")))]) + ada_tag(row)
        return li(esc(row.get("title")), small=small, tag=note or None)

    body = ""
    if orals:
        body += f'<h3>Oral presentations ({len(orals)})</h3>' + ul([item(r) for r in orals])
    if posters:
        body += f'<h3>Posters ({len(posters)} listed)</h3>' + ul([item(r) for r in posters])
    for row in note_rows:
        body += (f'<p class="note">{esc(row.get("title"))} — {esc(row.get("event"))}'
                 f'{", " + esc(row.get("date")) if row.get("date") else ""}.</p>')
    total = sum(rollup_count(r) for r in rows)
    return details("Conference contributions", body, count=total)


def simple_section(title, rows, main_key, small_keys, count=None, tag_key=None):
    """Teaching, education, courses, awards, volunteering -- all the same shape: one bold
    line, a muted meta line under it, and the ADA mark when the entry came from the service's
    own records."""
    items = []
    for row in rows:
        small = _join([esc(fmt_date(row.get(k)) if k == "date" else row.get(k))
                       for k in small_keys]) + ada_tag(row)
        items.append(li(esc(row.get(main_key)), small=small,
                        tag=esc(row.get(tag_key)) if tag_key and row.get(tag_key) else None))
    return details(title, ul(items), count=len(rows) if count is None else count)


_LEVELS = {"high": 90, "medium": 60, "basic": 35, "low": 25}
_LEVEL_RE = re.compile(r"^(.*?)\s*\((High|Medium|Basic|Low)\)$", re.I)


def course_topics(courses, limit=None):
    """The distinct topics a career's worth of courses covered, in the order they were last
    studied -- the original CV listed these by hand; here they are read off the course list,
    so a course logged on the Publications & Courses page adds its topics by itself."""
    seen = []
    for course in courses:
        for topic in str(course.get("topics") or "").split(","):
            topic = topic.strip()
            key = topic.lower()
            if topic and key not in [t.lower() for t in seen]:
                seen.append(topic[:1].upper() + topic[1:])
    return seen[:limit] if limit else seen


def expertise(cv_stats, skill_rows, courses, heading="Specific expertise"):
    """What this person can do, as one block: the CV's own expertise cards, the skill areas (which
    used to be a separate section at the foot of the page and read thin split in two), and a
    full-width card of everything the courses covered, counted live.

    Skills live here rather than at the bottom because this *is* the expertise section -- the
    original kept a short version up here and the detail far below, and the two halves only
    made sense read together."""
    written = [stat(value=row.get("value"), label=row.get("label"),
                    wide=len(str(row.get("label", ""))) > 58)
               for row in cv_stats if str(row.get("section", "")).strip() == heading]
    topics = course_topics(courses)
    extra = [stat(value=len(courses), label="courses and certifications, and what they covered",
                  chips=topics, full=True)] if courses else []
    return stats_grid(written + _skill_cards(skill_rows) + extra, heading)


def _skill_cards(rows):
    """One card per skill area, current focus first -- with "Python (High)" style entries
    pulled out into the original's proficiency meters instead of being chips like the rest."""
    areas, status_of = {}, {}
    for row in rows:
        area = str(row.get("area", "")).strip()
        areas.setdefault(area, []).append(str(row.get("item", "")).strip())
        status_of.setdefault(area, str(row.get("status", "")).strip())

    cards = []
    for area, items in sorted(areas.items(), key=lambda kv: status_of[kv[0]] != "Current focus"):
        status = status_of[area]
        bars, chips = [], []
        for item in items:
            match = _LEVEL_RE.match(item)
            if match:
                name, level = match.group(1), match.group(2)
                bars.append((name, level, _LEVELS.get(level.lower(), 50)))
            else:
                chips.append(item)
        tag_class = "tg" if status == "Current focus" else "tg e"
        lab = f'{esc(area)}<em class="{tag_class}">{esc(status)}</em>'
        cards.append(stat(lab=lab, bars=bars, chips=chips, wide=True,
                          current=status == "Current focus"))
    return cards


def wrap(*blocks):
    """Everything the view prints goes inside one .cv container, which is what every selector
    in the sheet above hangs off."""
    return '<div class="cv">' + "".join(b for b in blocks if b) + "</div>"
