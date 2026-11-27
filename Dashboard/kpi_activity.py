"""Were you actually at the machine while the timer ran?

Toggl answers this from a desktop app that can see OS-level input activity. The dashboard is
a browser page, but the `streamlit run` process behind it is ordinary Python on the same
machine -- so it can ask Windows the same question directly, with no extra packages and no
permissions: GetLastInputInfo reports how long it has been since the last keyboard or mouse
event in this desktop session.

A background thread polls that while the app is up and keeps two records:

  watch -- the stretches during which this watcher was actually running and looking. Any
           time NOT covered by one of these is time nobody was watching: the app was shut,
           the machine slept, the laptop lid was closed. That is a different thing from
           "idle", and far more often the thing that ruins a time log -- a timer left
           running overnight -- so it is reported separately rather than folded in.
  idle  -- the stretches where no input arrived for longer than the threshold.

Deliberately Streamlit-free, like kpi_data: the page wraps the watcher in st.cache_resource
so exactly one runs per server process, and nothing here knows about that.

Only the Time Tracker page uses this, and only while a timer is running. On a platform where
the idle query isn't available, os_idle_seconds() returns None, the watcher records watch
spans only, and the page quietly offers nothing but the unwatched-gap half.
"""

import copy
import json
import os
import platform
import tempfile
import threading
from datetime import datetime, timedelta
from pathlib import Path

# Machine-local operational state, NOT data -- so it deliberately does not live in ../Data.
# It is rewritten every minute while the app is up, and none of it describes the work being
# tracked: it is about this computer, and it belongs with this computer. (In the private
# tree Data/ is also a synced folder, which makes keeping it out of there doubly right.)
STATE_DIR = Path(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()) / "kpi_dashboard"
STATE_PATH = STATE_DIR / "tracker_activity.json"

POLL_SECONDS = 20
# Minutes with no input before a stretch counts as "away". Toggl's own default is 5.
DEFAULT_IDLE_MINUTES = 5
# A poll arriving more than this many times late means the process was not running normally
# in between -- asleep, suspended, or shut. The watch span is closed before the gap rather
# than stretched across it, which is what turns "the laptop was shut" into a visible gap
# instead of silently-counted work.
GAP_TOLERANCE = 3
# How much history is kept. Long enough to cover a timer left running over a weekend.
KEEP_DAYS = 10


def _iso(dt_):
    return dt_.strftime("%Y-%m-%dT%H:%M:%S")


def _parse(text):
    try:
        return datetime.strptime(str(text), "%Y-%m-%dT%H:%M:%S")
    except (TypeError, ValueError):
        return None


def os_idle_seconds():
    """Seconds since the last keyboard/mouse event in this desktop session, or None when
    the platform can't say.

    The arithmetic is done in 32 bits on purpose. LASTINPUTINFO.dwTime is a DWORD on the
    same clock as GetTickCount(), which wraps every ~49.7 days; subtracting it from the
    64-bit GetTickCount64() would come out astronomically wrong for the few polls after a
    machine passes that uptime. Masking the difference back to 32 bits wraps with it."""
    if platform.system() != "Windows":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class LASTINPUTINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

        user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
        kernel32.GetTickCount.restype = wintypes.DWORD
        info = LASTINPUTINFO()
        info.cbSize = ctypes.sizeof(info)
        if not user32.GetLastInputInfo(ctypes.byref(info)):
            return None
        return ((kernel32.GetTickCount() - info.dwTime) & 0xFFFFFFFF) / 1000.0
    except (OSError, AttributeError, ImportError):
        return None


def available():
    """True when this machine can actually report idle time, so the page can say so rather
    than offer a feature that would silently never fire."""
    return os_idle_seconds() is not None


# --- the store --------------------------------------------------------------------------

def _empty_state():
    return {"idle_minutes": DEFAULT_IDLE_MINUTES, "watch": [], "idle": [],
            "acknowledged_until": None}


def load_state():
    """The persisted watch/idle spans. A missing or unreadable file is an empty history, not
    an error: this is a convenience that must never be the reason a page won't load."""
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return _empty_state()
    state = _empty_state()
    if isinstance(data, dict):
        state.update({k: data[k] for k in state if k in data})
    for key in ("watch", "idle"):
        state[key] = [s for s in state[key]
                      if isinstance(s, dict) and _parse(s.get("from")) and _parse(s.get("to"))]
    return state


def save_state(state):
    """Rewritten whole, through a temp file so a kill mid-write can't leave invalid JSON
    behind (which would silently reset the history on the next read)."""
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = STATE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=1), encoding="utf-8")
        tmp.replace(STATE_PATH)
    except OSError:
        pass  # see load_state: never the reason a page fails


def _trim(spans, cutoff):
    return [s for s in spans if (_parse(s["to"]) or cutoff) >= cutoff]


def set_idle_minutes(minutes):
    state = load_state()
    state["idle_minutes"] = max(1, int(minutes))
    save_state(state)
    return state["idle_minutes"]


def acknowledge(until):
    """Remember that everything up to `until` has been dealt with, so reopening the page
    doesn't ask about the same stretch again. Kept in the file rather than in the session,
    because a browser refresh is exactly when it would otherwise come back."""
    state = load_state()
    state["acknowledged_until"] = _iso(until)
    save_state(state)


# --- the watcher ------------------------------------------------------------------------

class ActivityWatcher(threading.Thread):
    """Polls the OS idle clock and keeps the watch/idle spans up to date.

    Started once per Streamlit server process (the page holds it in st.cache_resource) and
    runs as a daemon, so it never keeps a shutting-down server alive. It writes at most once
    a minute while nothing changes -- a span being extended is just a new end timestamp, and
    there is no reason to put that on disk three times a minute."""

    def __init__(self, poll_seconds=POLL_SECONDS, persist_seconds=60):
        super().__init__(name="kpi-activity-watcher", daemon=True)
        self.poll_seconds = poll_seconds
        self.persist_seconds = persist_seconds
        # NOT self._stop: threading.Thread uses that name for its own internal method,
        # and shadowing it breaks is_alive() and the interpreter's thread cleanup.
        self._stopping = threading.Event()
        self._lock = threading.RLock()
        self._state = None  # the live spans; snapshot() hands out a copy
        self.started_at = datetime.now()

    def stop(self):
        self._stopping.set()

    def snapshot(self):
        """The live spans, not the ones on disk. The file is only rewritten once a minute,
        so reading it would miss up to a minute of the stretch the page most needs to know
        about -- the one that just ended when you came back and clicked something."""
        with self._lock:
            state = copy.deepcopy(self._state) if self._state is not None else load_state()
        # ...except for the two fields the PAGE owns, which it writes straight to the file.
        # Those have to come from disk, or dismissing a prompt would appear to do nothing
        # until this thread's next persist tick picked the change up a minute later -- which
        # looks exactly like the dismiss button being broken.
        on_disk = load_state()
        state["idle_minutes"] = on_disk.get("idle_minutes", DEFAULT_IDLE_MINUTES)
        state["acknowledged_until"] = on_disk.get("acknowledged_until")
        return state

    def run(self):
        state = self._state = load_state()
        threshold = timedelta(minutes=state.get("idle_minutes", DEFAULT_IDLE_MINUTES))
        last_poll = None
        last_saved = datetime.min
        # A fresh watch span every start: the process was not running before this moment,
        # whatever the file says, so the time up to here is unwatched by definition.
        watch = {"from": _iso(self.started_at), "to": _iso(self.started_at)}
        state["watch"].append(watch)
        open_idle = None  # the idle span currently being extended, held by reference

        while not self._stopping.is_set():
            now = datetime.now()
            idle_seconds = os_idle_seconds()
            gapped = (last_poll is not None
                      and (now - last_poll).total_seconds() > self.poll_seconds * GAP_TOLERANCE)

            with self._lock:
                if gapped:
                    # Asleep, suspended, or the clock moved. Close the watch span where it
                    # was last seen alive and open a new one here; the space between is the
                    # gap. Any idle span open across it ends there too -- what the machine
                    # was doing while nobody was looking is not something to claim.
                    watch["to"] = _iso(last_poll)
                    watch = {"from": _iso(now), "to": _iso(now)}
                    state["watch"].append(watch)
                    open_idle = None
                else:
                    watch["to"] = _iso(now)

                if idle_seconds is not None:
                    if timedelta(seconds=idle_seconds) >= threshold:
                        if open_idle is None:
                            # Starts where input actually stopped -- not at `now`. By the
                            # time a poll notices, the stretch is already `idle_seconds` old.
                            open_idle = {"from": _iso(now - timedelta(seconds=idle_seconds)),
                                         "to": _iso(now)}
                            state["idle"].append(open_idle)
                        else:
                            open_idle["to"] = _iso(now)
                    elif open_idle is not None:
                        # Input is back: the stretch ended when the key was pressed, which is
                        # `idle_seconds` ago. Capped at `from` so a clock change can't invert
                        # the span.
                        resumed = now - timedelta(seconds=idle_seconds)
                        open_idle["to"] = _iso(max(_parse(open_idle["from"]), resumed))
                        open_idle = None

                if (now - last_saved).total_seconds() >= self.persist_seconds:
                    cutoff = now - timedelta(days=KEEP_DAYS)
                    state["watch"] = _trim(state["watch"], cutoff)
                    state["idle"] = _trim(state["idle"], cutoff)
                    # Re-read the two fields the PAGE writes, so changing the threshold or
                    # dismissing a prompt takes effect without restarting the app, instead of
                    # being overwritten by the copy this thread has held since it started.
                    on_disk = load_state()
                    state["idle_minutes"] = on_disk.get("idle_minutes", DEFAULT_IDLE_MINUTES)
                    state["acknowledged_until"] = on_disk.get("acknowledged_until")
                    threshold = timedelta(minutes=state["idle_minutes"])
                    save_state(state)
                    last_saved = now

            last_poll = now
            self._stopping.wait(self.poll_seconds)


# --- reading it back ----------------------------------------------------------------------

def _overlap(a_from, a_to, b_from, b_to):
    lo, hi = max(a_from, b_from), min(a_to, b_to)
    return (lo, hi) if hi > lo else None


def _merge(spans):
    """Overlapping or touching spans collapsed into one. Two separate records of the same
    quarter hour must not be offered as two things to cut."""
    out = []
    for lo, hi in sorted(spans):
        if out and lo <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], hi))
        else:
            out.append((lo, hi))
    return [tuple(s) for s in out]


def away_periods(start, end, state=None, min_minutes=None, watcher_started=None):
    """The stretches between `start` and `end` that shouldn't be assumed to be work.

    Returns a list of dicts, earliest first, each with `kind` ("idle" or "unwatched"),
    `from`, `to` and `minutes`:

      idle      -- the machine was on and being watched, and nothing was typed or clicked
                   for longer than the threshold.
      unwatched -- nobody was looking: the dashboard wasn't running, the machine was asleep,
                   the lid was shut. The commonest real case is a timer left running
                   overnight, which is why it is surfaced at all rather than assumed to be
                   either work or idleness.

    Anything the page has already dealt with (acknowledged_until) is dropped, and so is
    anything shorter than `min_minutes` (the idle threshold by default) -- a 40-second gap
    between two polls is not a question worth asking.
    """
    state = state or load_state()
    threshold = min_minutes if min_minutes is not None else state.get("idle_minutes", DEFAULT_IDLE_MINUTES)
    floor = timedelta(minutes=threshold)

    acknowledged = _parse(state.get("acknowledged_until"))
    if acknowledged is not None:
        start = max(start, acknowledged)
    if end <= start:
        return []

    idle = _merge([(f, t) for f, t in (
        (_parse(s["from"]), _parse(s["to"])) for s in state.get("idle", [])) if f and t])
    watch = _merge([(f, t) for f, t in (
        (_parse(s["from"]), _parse(s["to"])) for s in state.get("watch", [])) if f and t])
    # The live span is only persisted once a minute, so the file always lags the truth by up
    # to that. Without this the last minute of every session reads as a gap.
    if watcher_started is not None:
        watch = _merge(watch + [(watcher_started, max(end, watcher_started))])

    periods = []
    for lo, hi in idle:
        span = _overlap(lo, hi, start, end)
        if span and span[1] - span[0] >= floor:
            periods.append({"kind": "idle", "from": span[0], "to": span[1]})

    # Unwatched = the complement of the watch spans inside [start, end].
    cursor = start
    for lo, hi in watch:
        if hi <= start:
            continue
        if lo >= end:
            break
        if lo > cursor and lo - cursor >= floor:
            periods.append({"kind": "unwatched", "from": cursor, "to": lo})
        cursor = max(cursor, hi)
    if end - cursor >= floor:
        periods.append({"kind": "unwatched", "from": cursor, "to": end})

    # An idle stretch inside a window nobody was watching is one fact, not two.
    unwatched = [(p["from"], p["to"]) for p in periods if p["kind"] == "unwatched"]
    periods = [p for p in periods
               if p["kind"] == "unwatched"
               or not any(lo <= p["from"] and p["to"] <= hi for lo, hi in unwatched)]

    # A zero-length period is an artifact of a boundary landing exactly on a span edge,
    # not something to put a checkbox next to. (Only reachable with min_minutes=0.)
    periods = [p for p in periods if p["to"] > p["from"]]
    for p in periods:
        p["minutes"] = (p["to"] - p["from"]).total_seconds() / 60
    return sorted(periods, key=lambda p: p["from"])


def active_stretches(start, end, away):
    """What's left of [start, end] once `away` is taken out -- the stretches actually worked.
    This is what an entry becomes when the away time is cut out of it: one entry per stretch,
    rather than one entry with a hole in it, because a time log has no way to record a hole."""
    out = []
    cursor = start
    for period in sorted(away, key=lambda p: p["from"]):
        lo, hi = max(period["from"], start), min(period["to"], end)
        if hi <= cursor:
            continue
        if lo > cursor:
            out.append((cursor, lo))
        cursor = max(cursor, hi)
    if end > cursor:
        out.append((cursor, end))
    return out
