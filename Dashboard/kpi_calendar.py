"""What your work calendar says she planned to be doing, read straight from Google.

Google Calendar publishes each calendar at a private iCal URL (Settings -> the calendar ->
"Secret address in iCal format"). Fetching that needs no OAuth, no Google Cloud project and
no Workspace admin approval -- which is the whole reason this route exists rather than the
API one. It is read-only by construction: the dashboard can see the calendar and can never
change it.

The URL is a credential. Anyone holding it can read that calendar, so it is kept in
%LOCALAPPDATA% alongside the activity watcher's state -- never in Data/, never in the repo,
and never in the OneDrive-synced tree.

ICS is parsed here rather than with a library, because the subset Google emits is small and
the two genuinely hard parts are already installed: dateutil.rrule (which pandas brings in)
expands recurrence, and stdlib zoneinfo resolves the IANA zone names Google writes. Adding
a dependency to requirements.txt for the rest would buy very little -- but see
`parse_calendar`: anything it can't read degrades to "couldn't read the calendar", never to
a wrong time on the grid, because a planned block drawn at the wrong hour is worse than no
planned block at all.

Everything comes back as naive local time, which is the convention the whole tracker uses.
Streamlit-free, like kpi_data -- the page does the caching.
"""

import json
import re
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests
from dateutil.rrule import rrulestr

# The same machine-local folder the activity watcher uses: both hold state about THIS
# computer rather than about the service, and neither belongs in Data/ or in git.
from kpi_activity import STATE_DIR

SETTINGS_PATH = STATE_DIR / "calendar.json"
# The last calendar that came back from Google, kept so a dropped connection costs the
# planned layer its freshness rather than its existence. The tracker itself needs no network
# at all -- this is the one part of the page that does.
CACHE_PATH = STATE_DIR / "calendar_cache.ics"
FETCH_TIMEOUT = 20
MAX_ICS_BYTES = 12 * 1024 * 1024


class CalendarError(Exception):
    """Anything that stops the calendar being read, with a message meant for the page."""


# --- settings -------------------------------------------------------------------------------

def load_settings():
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        data = {}
    return {"url": str(data.get("url") or ""), "email": str(data.get("email") or ""),
            "skip_declined": bool(data.get("skip_declined", True)),
            "skip_all_day": bool(data.get("skip_all_day", True))}


def save_settings(**fields):
    settings = load_settings()
    settings.update({k: v for k, v in fields.items() if k in settings})
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        SETTINGS_PATH.write_text(json.dumps(settings, indent=1), encoding="utf-8")
    except OSError as exc:
        raise CalendarError(f"Couldn't save the calendar settings: {exc}") from exc
    return settings


def looks_like_ics_url(url):
    """Google's secret address is https and ends in .ics. Checked before anything is fetched
    so a pasted *web* link (the 'public URL to this calendar' one, which returns an HTML
    page) is rejected with a useful message instead of a parse error."""
    url = (url or "").strip()
    return url.startswith("https://") and url.split("?")[0].lower().endswith(".ics")


def fetch_ics(url):
    """The raw ICS text. Raises CalendarError with something worth showing a person."""
    if not looks_like_ics_url(url):
        raise CalendarError(
            "That doesn't look like a secret iCal address. It should start with https:// and "
            "end in .ics — in Google Calendar: Settings → the calendar → "
            "'Secret address in iCal format'.")
    try:
        response = requests.get(url, timeout=FETCH_TIMEOUT,
                                headers={"Accept": "text/calendar"})
    except requests.RequestException as exc:
        raise CalendarError(f"Couldn't reach Google Calendar: {exc}") from exc
    if response.status_code == 404:
        raise CalendarError("Google returned 404 — the secret address has been reset, or the "
                            "calendar was deleted. Copy the current one and paste it again.")
    if not response.ok:
        raise CalendarError(f"Google returned {response.status_code} for that address.")
    if len(response.content) > MAX_ICS_BYTES:
        raise CalendarError("That calendar is enormous (over 12 MB of events) — narrow it "
                            "down to a single calendar rather than a combined one.")
    text = response.text
    if "BEGIN:VCALENDAR" not in text:
        raise CalendarError("That address returned something that isn't a calendar. Make sure "
                            "it's the *secret iCal* address, not the public web link.")
    return text


def _read_cache():
    try:
        return CACHE_PATH.read_text(encoding="utf-8"), datetime.fromtimestamp(CACHE_PATH.stat().st_mtime)
    except (OSError, ValueError):
        return None, None


def load_calendar(url):
    """The calendar's ICS, from Google when it can be reached and from the last good copy
    when it can't.

    Nothing else on this page needs the network: the timer, the week views and the push to
    the time log are all local files, and a dropped connection doesn't reach them. The
    calendar is the exception, so it degrades rather than disappears -- a planned layer from
    this morning is far more use than an error where the planned layer was, as long as the
    page says which it is showing.

    Returns {"ics", "fetched_at", "stale", "error"}. Raises CalendarError only when the
    fetch failed AND there is no cached copy to fall back on."""
    try:
        text = fetch_ics(url)
    except CalendarError as exc:
        cached, fetched_at = _read_cache()
        if cached is None:
            raise
        return {"ics": cached, "fetched_at": fetched_at, "stale": True, "error": str(exc)}
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(text, encoding="utf-8")
    except OSError:
        pass  # a cache that can't be written is a slower next outage, not an error now
    return {"ics": text, "fetched_at": datetime.now(), "stale": False, "error": None}


def tracked_overlap(event, entries):
    """How much of one calendar event already has tracked time against it, in hours.

    Calendar events and tracked stretches are different things that happen to share a clock,
    so this is only a hint -- but it is the hint that stops a meeting being added twice,
    which is the obvious way this feature would otherwise go wrong."""
    covered = timedelta(0)
    for _, row in entries.iterrows():
        start, end = row.get("start_dt"), row.get("end_dt")
        if start is None or end is None or str(end) == "NaT" or str(start) == "NaT":
            continue
        lo = max(event["from"], start.to_pydatetime() if hasattr(start, "to_pydatetime") else start)
        hi = min(event["to"], end.to_pydatetime() if hasattr(end, "to_pydatetime") else end)
        if hi > lo:
            covered += hi - lo
    return covered.total_seconds() / 3600


# --- ICS parsing ------------------------------------------------------------------------------

def _unfold(text):
    """ICS wraps long lines by starting the continuation with a space or tab. Undo that
    first; every later step assumes one property per line."""
    out = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and out:
            out[-1] += raw[1:]
        else:
            out.append(raw)
    return out


def _split_property(line):
    """'DTSTART;TZID=Europe/Lisbon:20261123T100000' -> ('DTSTART', {'TZID': ...}, '2026...').
    The split is on the first colon OUTSIDE double quotes -- a quoted parameter value is
    allowed to contain one (CN="Lee: Research" does happen), and splitting naively on the first
    colon would cut the property in the wrong place."""
    in_quotes = False
    for i, char in enumerate(line):
        if char == '"':
            in_quotes = not in_quotes
        elif char == ":" and not in_quotes:
            head, value = line[:i], line[i + 1:]
            break
    else:
        return None, {}, ""

    parts, params, buf, in_quotes = [], {}, "", False
    for char in head:
        if char == '"':
            in_quotes = not in_quotes
            buf += char
        elif char == ";" and not in_quotes:
            parts.append(buf)
            buf = ""
        else:
            buf += char
    parts.append(buf)

    for param in parts[1:]:
        if "=" in param:
            key, val = param.split("=", 1)
            params[key.upper()] = val.strip('"')
    return parts[0].upper(), params, value


def _unescape(text):
    out = re.sub(r"\\n", "\n", text, flags=re.IGNORECASE)
    return out.replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\")


def _zone(tzid):
    try:
        return ZoneInfo(tzid)
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        return None


def _parse_dt(value, params):
    """One DTSTART/DTEND/EXDATE value -> (datetime, all_day).

    Three shapes exist and they mean different things:
      20261123          VALUE=DATE, an all-day event -- a date, not a moment
      20261123T100000Z  UTC
      20261123T100000   local to TZID when there is one, otherwise 'floating' (whatever the
                        clock says wherever it is read, which for a personal calendar is
                        exactly the right reading)."""
    value = value.strip()
    if params.get("VALUE", "").upper() == "DATE" or re.fullmatch(r"\d{8}", value):
        parsed = datetime.strptime(value[:8], "%Y%m%d")
        return parsed, True
    match = re.fullmatch(r"(\d{8}T\d{6})(Z?)", value)
    if not match:
        return None, False
    naive = datetime.strptime(match.group(1), "%Y%m%dT%H%M%S")
    if match.group(2) == "Z":
        return naive.replace(tzinfo=timezone.utc), False
    zone = _zone(params["TZID"]) if params.get("TZID") else None
    return (naive.replace(tzinfo=zone) if zone else naive), False


def _to_local_naive(value):
    """Every time in this codebase is naive local -- a time sheet records the hour the clock
    showed. A tz-aware moment is converted; a floating one already is one."""
    if value is None or value.tzinfo is None:
        return value
    return value.astimezone().replace(tzinfo=None)


def parse_calendar(ics_text):
    """VEVENTs as dicts: uid, title, start, end (tz-aware or floating), all_day, rrule,
    exdates, recurrence_id, cancelled, declined_by (the attendee addresses that said no).

    A VEVENT that can't be read is skipped rather than guessed at -- the rest of the
    calendar is still worth drawing, and a block at the wrong hour would be believed."""
    events, current = [], None
    for line in _unfold(ics_text):
        upper = line.strip().upper()
        if upper == "BEGIN:VEVENT":
            current = {"uid": "", "title": "", "start": None, "end": None, "all_day": False,
                       "rrule": "", "exdates": [], "recurrence_id": None, "cancelled": False,
                       "declined_by": set(), "duration": None}
            continue
        if upper == "END:VEVENT":
            if current and current["start"] is not None:
                events.append(current)
            current = None
            continue
        if current is None:
            continue

        name, params, value = _split_property(line)
        if name is None:
            continue
        try:
            if name == "UID":
                current["uid"] = value.strip()
            elif name == "SUMMARY":
                current["title"] = _unescape(value).strip()
            elif name == "DTSTART":
                current["start"], current["all_day"] = _parse_dt(value, params)
            elif name == "DTEND":
                current["end"], _ = _parse_dt(value, params)
            elif name == "RRULE":
                current["rrule"] = value.strip()
            elif name == "EXDATE":
                for piece in value.split(","):
                    parsed, _ = _parse_dt(piece, params)
                    if parsed is not None:
                        current["exdates"].append(parsed)
            elif name == "RECURRENCE-ID":
                current["recurrence_id"], _ = _parse_dt(value, params)
            elif name == "STATUS":
                current["cancelled"] = value.strip().upper() == "CANCELLED"
            elif name == "ATTENDEE" and params.get("PARTSTAT", "").upper() == "DECLINED":
                current["declined_by"].add(value.strip().lower().removeprefix("mailto:"))
        except (ValueError, KeyError):
            continue  # one unreadable property shouldn't cost the whole event
    return events


def _instances(event, window_start, window_end):
    """Every occurrence of one VEVENT whose span overlaps the window, as (start, end) pairs
    in the event's own frame of reference.

    A recurring event is expanded with dateutil in ITS OWN timezone, not in local naive time.
    That matters across a DST change: a 10:00 Lisbon meeting is at 10:00 Lisbon on both sides
    of the switch, and expanding it as a naive local series would drift it by an hour for
    half the year once another zone is involved."""
    start, end = event["start"], event["end"]
    if start is None:
        return []
    if end is None:
        end = start + (timedelta(1) if event["all_day"] else timedelta(hours=1))
    duration = max(end - start, timedelta(0))

    if not event["rrule"]:
        return [(start, start + duration)]

    # The window has to be widened by the duration at the front, or an event that started
    # before Monday and runs into it would be missed entirely.
    lo, hi = window_start - duration, window_end
    if start.tzinfo is not None:
        zone = start.tzinfo
        lo = lo.replace(tzinfo=zone) if lo.tzinfo is None else lo.astimezone(zone)
        hi = hi.replace(tzinfo=zone) if hi.tzinfo is None else hi.astimezone(zone)
    try:
        rule = rrulestr(event["rrule"], dtstart=start)
        occurrences = rule.between(lo, hi, inc=True)
    except (ValueError, TypeError, OverflowError):
        return [(start, start + duration)]

    excluded = {ex for ex in event["exdates"]}
    return [(occ, occ + duration) for occ in occurrences if occ not in excluded]


def events_in_week(ics_text, week_start, settings=None):
    """The calendar's timed events for the Monday-start week, as dicts with `title`, `from`,
    `to` (naive local) and `hours`, earliest first -- plus, separately, the titles of any
    all-day events touching the week.

    All-day events are kept OUT of the drawn week on purpose: a birthday or a public holiday
    is not a seven-hour block of planned work, and drawing it as one would swamp the grid.
    They are named in a line underneath instead.

    Returns (timed_events, all_day_titles)."""
    settings = settings or load_settings()
    week_start = datetime.combine(_as_date(week_start), time.min)
    week_end = week_start + timedelta(7)
    me = (settings.get("email") or "").strip().lower()

    raw = parse_calendar(ics_text)
    # An edited single occurrence arrives as its own VEVENT carrying RECURRENCE-ID; it
    # REPLACES the generated instance rather than joining it, or the meeting shows twice.
    overrides = {(e["uid"], _to_local_naive(e["recurrence_id"]))
                 for e in raw if e["recurrence_id"] is not None}

    timed, all_day = [], []
    for event in raw:
        if event["cancelled"]:
            continue
        if settings.get("skip_declined", True) and me and me in event["declined_by"]:
            continue
        for start, end in _instances(event, week_start, week_end):
            local_start, local_end = _to_local_naive(start), _to_local_naive(end)
            if local_start is None or local_end is None:
                continue
            if local_end <= week_start or local_start >= week_end:
                continue
            if event["rrule"] and (event["uid"], local_start) in overrides:
                continue
            if event["all_day"]:
                all_day.append(event["title"] or "(no title)")
                continue
            timed.append({
                "uid": event["uid"], "title": event["title"] or "(no title)",
                "from": local_start, "to": local_end,
                "hours": (local_end - local_start).total_seconds() / 3600,
            })

    timed.sort(key=lambda e: (e["from"], e["title"]))
    return timed, sorted(dict.fromkeys(all_day))


def _as_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.fromisoformat(str(value)).date()


def planned_blocks(events, week_start):
    """Calendar events cut into one drawable block per day, the same shape
    kpi_data.entry_segments produces for tracked time -- so the week grid can draw both
    against one pair of axes. Returns a list of dicts with day / start_min / end_min /
    title / hours / event_index.

    `event_index` points back into `events`, because one event past midnight becomes two
    blocks and clicking either of them has to offer the WHOLE meeting to track, not the
    half that happens to be on the day that was clicked."""
    week_start = datetime.combine(_as_date(week_start), time.min)
    blocks = []
    for index, event in enumerate(events):
        start, end = event["from"], max(event["to"], event["from"])
        day = datetime.combine(start.date(), time.min)
        while day < end and day < week_start + timedelta(7):
            nxt = day + timedelta(1)
            lo, hi = max(start, day, week_start), min(end, nxt)
            if hi > lo:
                blocks.append({
                    "day": (day - week_start).days, "title": event["title"],
                    "event_index": index,
                    "start_min": (lo - day).total_seconds() / 60,
                    "end_min": (hi - day).total_seconds() / 60,
                    "hours": (hi - lo).total_seconds() / 3600,
                })
            day = nxt
    return [b for b in blocks if 0 <= b["day"] <= 6]
