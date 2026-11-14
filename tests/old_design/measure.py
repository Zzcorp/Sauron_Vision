"""The measured half's machinery (tests/test_zero_old_design.py, B0):
Chromium over its DevTools pipe, every request answered from the test
client, the synthetic book, the scenes and the held clock."""
import base64
import builtins
import collections
import contextlib
import copy
import datetime as _dtm
import importlib
import json
import mimetypes
import os
import pathlib
import re
import select
import subprocess
import sys
import time
import types
import urllib.parse
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client, RequestFactory

from tests.old_design.rules import ROOT, TOKENS_SHEET
from tests.test_close_advice import CHROME, HOST, _Chrome

# ══════════════════════════════════════════════════════════════════════════
# THE MEASURED HALF: every routed page and the shell's states, in Chromium
# ══════════════════════════════════════════════════════════════════════════
#
# Chromium over its DevTools pipe (tests/test_close_advice._Chrome), on a
# synthetic book, at one frozen instant (the one-price fixture's T,
# Thursday 2026-11-12 19:13:56 UTC, with NYSE, NASDAQ, TSX, the forex and
# the CME open: the instant the budgets were measured at): every clock the
# server reads (freeze_patches: the market hours', the calendar's, the
# "... ago" words', the models' stamps', the idle lock's) and the page's
# own Date, timers and idle callbacks (INIT) read T, so a page measured on
# a Saturday is the page measured on a Thursday.
#
# THE CRITIC'S HOLE 1 (pages opened as files load nothing after the HTML):
# every request the page makes is answered from the test client through the
# DevTools Fetch domain, before it can leave the machine (no host resolves
# either): the document, its sheets and scripts from static/, its fetch()
# and XHR calls (the rail, the bell, the live regions, /eye/'s body, the
# chart's data, the instrument preview) from the views themselves. A POST
# is never sent to a view that could move anything: the previews the
# states need are synthetic or read-only, every other POST is answered 204.
# The regions htmx fills on load (the KPI strips, the bot panel, /command/'s
# tabs, /eye/'s body) are filled the way htmx fills them, from their own
# routes, before the page is served: the CDN libraries (htmx, Chart.js,
# lightweight-charts) are not fetched, so the chart's canvas stays empty
# (B10 brings its pixel census with a copy of the library).
#
# THE CRITIC'S HOLE 2 (rest state only): a forced pass puts :hover,
# :focus-visible and :active on every button, link, row and checkbox of the
# shell and of the §10 money controls, and measures again.
# THE CRITIC'S HOLE 3 (1440 only): the shell and the §10 controls at 390 x 844
# too: money targets under 44 px, sideways scroll, red fills outside REAL.
# THE CRITIC'S HOLE 4: accent-color, caret-color, ::placeholder, ::marker,
# and the states the lists missed (below, STATES).
#
# THE SAME COUNT IN EVERY RUN. Each page is read at the same instant of its
# life: every timer the page sets (but setTimeout(fn, 0)) and every idle
# callback it asks for runs on a held clock the run moves by fixed steps
# (2.6 s after the load, 1.6 s after an act; INIT), firing them in their
# order and letting each one's fetches land before the next, so the live
# pill's first poll, the nav dots', Gollum's whisper, the Horde's first
# tab, the Wall's labels, a hover's 450 ms beat, /intro/'s steps have all
# happened, and nothing later has.
# The page's Date reads T plus the held clock, its Math.random is seeded,
# a marquee strip (claude/marquee, when it lands) is held at its start.
# What the motion layer hid below the fold is shown, finite animations end
# where they end, endless ones are stopped at their start (the census), and
# each scene's writes to the book and the cache are undone after it
# (_scene_apart), so a scene reads the same page whichever came before it.
# The census user has finished the guided tour (it is measured once, in
# state:tour), so the tour card is in no page's count.
#
# Per page and per state, each marker's count is held to its budget in
# tests/old_design_budget.json ("measured"), both ways: a count above it
# fails, naming the page, the state, the selector, the property and the
# value; a count below it fails too, until the budget is lowered with it
# (lower_measured_budgets()), but for the markers that follow the layout
# (LAYOUT_MARKERS: the faces that drew the glyphs, sizes, overlaps), which
# may sit up to their slack under. The budget records the machine it was
# measured on (browser, faces): the CI job installs the same.

CENSUS_JS = ROOT / "tests" / "old_design_census.js"
ORIGIN_HOST = "sv.census"
ORIGIN = "http://" + ORIGIN_HOST
#: The measured markers (old_design_census.js).
MEASURED = ("font_share_tech", "font_orbitron", "font_rajdhani", "font_other", "tiny", "figs", "prose_mono",
            "eye_text", "color_off", "contrast", "eye_fill", "eye_wash", "bg_off", "see_through", "red_fill",
            "glass", "gradient", "eye_border", "border_off", "glow", "shadow", "text_glow", "accent_color",
            "radius", "anim_loop", "inline_visual", "glyph_face", "first_line_low",
            "chrome_over_content", "sideways", "target_small")
#: The §10 money controls: the forced pass hovers them, the phone pass
#: measures them.
MONEY = (".tk-side, .tk-long, .tk-short, [data-sv-close-trade], #svCloseAll, .sr-pop-btn, .sr-gone-btn-ticket, "
         ".btn-buy, .btn-sell, .btn-stop, .sz-confirm, .sz-dialog .sv-dialog-btn, input[type=\"password\"], "
         "form[action*=\"toggle\"] button, form[action*=\"component\"] button, .sv-armed-pill, .ip-pos-close")
#: The shell's interactive parts (the forced pass).
SHELL_INTERACTIVE = (".sidebar a, .sidebar button, .topbar a, .topbar button, .info-panel-wrap a, "
                     ".info-panel-wrap button, .signals-rail a, .signals-rail button, .data-headband a, "
                     ".ticker-bar a, input[type=\"checkbox\"], tr")
#: And every control of the page itself (the review of B0: the bot panel's
#: Toggle and Reset circuit, /withdrawals/' Reserve, /setup/'s Save, FLATTEN
#: ALL, /asset-bots/' Follow), forced with the shell's.
PAGE_INTERACTIVE = (".page-content a, .page-content button, .page-content summary, .page-content [role=\"button\"], "
                    ".page-content input, .page-content select, .page-content label, .page-content [tabindex]")
FORCED_SELECTOR = SHELL_INTERACTIVE + ", " + PAGE_INTERACTIVE + ", " + MONEY
#: The faces a glyph may be drawn in (the four; Orbitron and Rajdhani are
#: not installed anywhere these tests run, and fall to the next face).
FACES = ("Inter", "JetBrains Mono", "Orbitron", "Rajdhani")


def _frozen_instant():
    from tests.one_quote_fixture import T
    return T


# ── the server's one instant ────────────────────────────────────────────
#
# EVERY CLOCK THE SERVER READS (2026-11-14). The hold named six clocks:
# django.utils.timezone.now, the one price's, and the datetime of the
# market hours, the calendar, the charts and the bars. Every other reader
# of the machine's clock read the real one: Django's timesince and
# timeuntil (the "... ago" words of some forty templates), the models'
# default stamps (default=timezone.now keeps the function, which asks
# datetime itself), the idle lock's gap (int(time.time()) against the
# session's first stamp: a shard slower than the census user's 10 minutes
# would send every later scene to /locked/), the Oculus's probe ages, the
# quote seams' time.time(). Their words aged with the machine's clock, and
# one more scene could fall to the lock on a slow runner. Now the hold
# swaps the time module's own readers (time.time and time.time_ns, and
# time.localtime, gmtime, ctime, asctime and strftime asked without a
# time), and in Django's modules and this project's every name for one of
# them, for datetime.datetime or datetime.date (now, utcnow, today), or
# for the datetime module itself (a copy holding the swapped classes:
# timesince's datetime.datetime.now()). A module a page imports while the
# census runs is held from the end of that import on. The datetime module's
# own names stay the machine's, and so do the site packages': a C
# extension takes the datetime types by name while it imports (pandas,
# first imported under a swapped datetime.datetime, broke for the rest of
# the process). The swapped classes answer isinstance and issubclass as the
# real ones do, and make real datetimes only. Once the hold is over every
# name is back, and a name a module took meanwhile reads the machine's
# clock again.

#: The machine's clock as Python reads it, kept in a dict: a swap replaces
#: the names modules hold, never what a dict holds.
_WALL = {"datetime": _dtm.datetime, "date": _dtm.date, "module": _dtm, "time": time.time,
         "time_ns": time.time_ns, "localtime": time.localtime, "gmtime": time.gmtime, "ctime": time.ctime,
         "asctime": time.asctime, "strftime": time.strftime}
#: id -> (kind, reader): every reader a swap has put in place, kept alive
#: so that an id names one reader for good.
_SWAPPED = {}
#: The modules whose clocks the old hold named, imported before a hold
#: looks: their names are swapped from its first moment.
_NAMED = ("core.exchange_status", "core.market_calendar", "dashboard.chart_source", "market_data.bot_bars")
_ROOT_PREFIX = tuple({str(ROOT) + os.sep, os.path.realpath(str(ROOT)) + os.sep})
#: Never swapped in: the datetime module (a C extension reads its types
#: there), and this one.
_NEVER = ("datetime", "_datetime", __name__)


def _reached(mod, synthetic=False):
    """Whether a swap reaches a module's names: Django's, and this
    project's own files (not a site package's); a move also reaches a
    module made in memory (missed_reader's)."""
    name = getattr(mod, "__name__", None) or ""
    if not isinstance(mod, types.ModuleType) or name in _NEVER:
        return False
    if name == "django" or name.startswith("django."):
        return True
    path = getattr(mod, "__file__", None)
    if not path:
        return synthetic
    return path.startswith(_ROOT_PREFIX) and "-packages" not in path


class _Like(type):
    """A swapped class answers isinstance and issubclass as the real one
    does; a class made from it while it is in place (Django's
    datetimeobject, when its module is first imported then) as itself."""

    def __instancecheck__(cls, obj):
        real = cls.__dict__.get("_real")
        return isinstance(obj, real) if real else type.__instancecheck__(cls, obj)

    def __subclasscheck__(cls, sub):
        real = cls.__dict__.get("_real")
        return issubclass(sub, real) if real else type.__subclasscheck__(cls, sub)


def _readers(clock, live):
    """{kind: reader} reading clock() (epoch seconds) while live["on"], and
    the machine's clock once it is off."""
    real_dt, real_date = _WALL["datetime"], _WALL["date"]

    def secs():
        return clock() if live["on"] else _WALL["time"]()

    class SwappedDatetime(real_dt, metaclass=_Like):
        _real = real_dt

        def __new__(cls, *args, **kwargs):
            if cls is SwappedDatetime:
                return real_dt(*args, **kwargs)
            return real_dt.__new__(cls, *args, **kwargs)

        @classmethod
        def now(cls, tz=None):
            return real_dt.fromtimestamp(secs(), tz)

        @classmethod
        def utcnow(cls):
            return real_dt.fromtimestamp(secs(), _dtm.timezone.utc).replace(tzinfo=None)

        @classmethod
        def today(cls):
            return real_dt.fromtimestamp(secs())

    class SwappedDate(real_date, metaclass=_Like):
        _real = real_date

        def __new__(cls, *args, **kwargs):
            if cls is SwappedDate:
                return real_date(*args, **kwargs)
            return real_date.__new__(cls, *args, **kwargs)

        @classmethod
        def today(cls):
            return real_date.fromtimestamp(secs())

    def time_():
        return secs()

    def time_ns_():
        return int(round(secs() * 1e9)) if live["on"] else _WALL["time_ns"]()

    def localtime_(seconds=None):
        return _WALL["localtime"](secs() if seconds is None else seconds)

    def gmtime_(seconds=None):
        return _WALL["gmtime"](secs() if seconds is None else seconds)

    def ctime_(seconds=None):
        return _WALL["ctime"](secs() if seconds is None else seconds)

    def asctime_(t=None):
        return _WALL["asctime"](_WALL["localtime"](secs()) if t is None else t)

    def strftime_(fmt, t=None):
        return _WALL["strftime"](fmt, _WALL["localtime"](secs()) if t is None else t)

    module = types.ModuleType(_dtm.__name__, _dtm.__doc__)
    module.__dict__.update({k: v for k, v in vars(_dtm).items() if k not in ("__name__", "__doc__", "__spec__",
                                                                             "__loader__")})
    module.datetime, module.date = SwappedDatetime, SwappedDate
    return {"datetime": SwappedDatetime, "date": SwappedDate, "module": module, "time": time_,
            "time_ns": time_ns_, "localtime": localtime_, "gmtime": gmtime_, "ctime": ctime_,
            "asctime": asctime_, "strftime": strftime_}


class _ClockSwap:
    """From start() to stop(), the time module's readers, and every name
    that the modules a swap reaches (_reached) hold for one of the machine
    clock's readers, swapped for readers of clock(). The hold (over=True)
    swaps the machine's own readers and any a move put in place, in the
    modules loaded when it starts and in each one loaded after, at the end
    of the import that loaded it (or, for a module still running then, of
    the next import); a move (over=False) swaps only the machine's own, in
    the modules loaded when it starts. The hold wins, whichever started
    first, and a move reaches only what the hold missed."""

    def __init__(self, clock, over):
        self.over, self.live = over, {"on": False}
        self.readers = _readers(clock, self.live)
        self.done, self.seen, self.waiting = [], {}, {}
        self.size, self.depth, self.imp = 0, 0, None

    def _wanted(self):
        wanted = {id(obj): kind for kind, obj in _WALL.items()}
        if self.over:
            wanted.update({i: kind for i, (kind, _r) in _SWAPPED.items()})
        for obj in self.readers.values():
            wanted.pop(id(obj), None)
        return wanted

    def _swap(self, mods):
        wanted = self._wanted()
        for mod in mods:
            for attr, value in list(vars(mod).items()):
                kind = wanted.get(id(value))
                if kind is None:
                    continue
                try:
                    setattr(mod, attr, self.readers[kind])
                except Exception:       # a module that refuses the name keeps it (MeasuredClockTests would see it)
                    continue
                self.done.append((mod, attr, value))

    def _look(self):
        """The modules loaded since the last look, once each has run."""
        out = []
        for key, mod in list(self.waiting.items()):
            if not getattr(getattr(mod, "__spec__", None), "_initializing", False):
                del self.waiting[key]
                out.append(mod)
        if len(sys.modules) != self.size:
            for mod in list(sys.modules.values()):
                key = id(mod)
                if key in self.seen:
                    continue
                self.seen[key] = mod     # kept, so its id names it for good
                if getattr(getattr(mod, "__spec__", None), "_initializing", False):
                    self.waiting[key] = mod
                else:
                    out.append(mod)
            self.size = len(sys.modules)
        self._swap([m for m in out if _reached(m, synthetic=not self.over)])

    def _import(self, name, globals=None, locals=None, fromlist=(), level=0):
        self.depth += 1
        try:
            return self.imp(name, globals, locals, fromlist, level)
        finally:
            self.depth -= 1
            if not self.depth and self.live["on"] and (self.waiting or len(sys.modules) != self.size):
                self._look()

    def start(self):
        if self.over:
            for name in _NAMED:
                try:
                    importlib.import_module(name)
                except ImportError:
                    pass
        for kind, obj in self.readers.items():
            _SWAPPED[id(obj)] = (kind, obj)
        mods = list(sys.modules.values())
        self.seen, self.size = {id(m): m for m in mods}, len(sys.modules)
        self._swap([sys.modules["time"]] + [m for m in mods if _reached(m, synthetic=not self.over)])
        if self.over:
            self.imp, builtins.__import__ = builtins.__import__, self._import
        self.live["on"] = True
        return self

    def stop(self):
        self.live["on"] = False
        if self.imp is not None:
            builtins.__import__, self.imp = self.imp, None
        for mod, attr, value in reversed(self.done):
            try:
                setattr(mod, attr, value)
            except Exception:       # put every other name back all the same
                pass
        self.done, self.seen, self.waiting = [], {}, {}

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()


def freeze_patches():
    """The patches that hold the server at T, started by the caller in this
    order: every clock the process reads (_ClockSwap), then the two seams
    the tests name (timezone.now, the one price's now)."""
    T = _frozen_instant()
    return [_ClockSwap(T.timestamp, over=True),
            mock.patch("django.utils.timezone.now", return_value=T),
            mock.patch("market_data.one_quote.now", return_value=T)]


def machine_clock(at):
    """The machine's own clock moved to `at` (an aware datetime), ticking on
    from there, for every reader the hold has not swapped (a context
    manager): under the hold it reaches nothing (MeasuredClockTests, and
    SV_OLD_DESIGN_MACHINE_CLOCK on the measured shards)."""
    offset = at.timestamp() - _WALL["time"]()
    return _ClockSwap(lambda: _WALL["time"]() + offset, over=False)


@contextlib.contextmanager
def missed_reader():
    """A loaded module holding the machine's own time.time and datetime, as
    one the hold had missed would (a module the hold, started before it,
    did not swap): what a move of the machine's clock does reach."""
    mod = types.ModuleType("sv_census_missed_reader")
    mod.time, mod.datetime = _WALL["time"], _WALL["datetime"]
    sys.modules[mod.__name__] = mod
    try:
        yield mod
    finally:
        sys.modules.pop(mod.__name__, None)


def instant(text):
    """An ISO 8601 instant ("2026-11-14T12:00:00Z") as an aware datetime."""
    at = _WALL["datetime"].fromisoformat(text.strip().replace("Z", "+00:00"))
    return at if at.tzinfo else at.replace(tzinfo=_dtm.timezone.utc)


def coming(weekday, hour, minute=0):
    """The next instant on `weekday` (0 is Monday) at hour:minute UTC that is
    more than a day ahead of the machine's clock."""
    now = _WALL["datetime"].fromtimestamp(_WALL["time"](), _dtm.timezone.utc)
    for days in range(1, 10):
        at = (now + timedelta(days=days)).replace(hour=hour, minute=minute, second=0, microsecond=0)
        if at.weekday() == weekday and at - now > timedelta(days=1):
            return at
    raise AssertionError("no weekday %d ahead" % weekday)


def token_rgbs():
    """{name: [r, g, b]} of every colour token of sv-tokens.css's :root (the
    dark palette the census holds colours to)."""
    text = (ROOT / TOKENS_SHEET).read_text(encoding="utf-8")
    root = text[text.index(":root"):]
    root = root[:root.index("}")]
    out = {}
    for name, hexv in re.findall(r"--sv-([\w-]+)\s*:\s*#([0-9a-fA-F]{6})\b", root):
        out[name] = [int(hexv[i:i + 2], 16) for i in (0, 2, 4)]
    return out


def token_radii():
    text = (ROOT / TOKENS_SHEET).read_text(encoding="utf-8")
    return sorted({0.0} | {float(v) for v in re.findall(r"--sv-radius-[\w-]+\s*:\s*([\d.]+)px", text) if float(v) < 99})


#: The census's element groups per marker per scene: all of them, so a
#: failure names the new offender (the review of B0 found 143 scene and
#: marker pairs at the old cap of 40, where a new one could go unnamed).
EXAMPLES = 100000
#: The shell's regions, in the order the census assigns an element to the
#: first that holds it (the card or menu before the band it opened from):
#: a batch that empties its region of every page puts "*@<region>" on
#: STRICT (budget.py), whatever the page's other regions still hold.
REGIONS = (
    ("popovers", ".sr-popup, .dh-pop, .ticker-popup, .nf-pop, .pos-pop, .instrument-preview, .ip-dropdown, "
                 ".notif-dropdown, .user-menu-dropdown, .exchange-dropdown, .lsp-dropdown, .sv-popover, .sv-menu"),
    ("dialogs", ".sv-dialog, .sz-dialog, .lvl-dlg, .kbd-modal-overlay, .il-overlay, .sv-deeplink-note"),
    ("floating", ".sv-horde-tab, .sv-council-band-tab, .sv-activity-tab, .gollum-fab, .gollum-bubble, .se-eye-fab"),
    ("panels", ".sv-horde, .sv-council-band, .sv-activity, .se-chat-panel, .gollum-dialog, .sv-tour-card, "
               ".sv-tour-spot, .sv-tour-veil"),
    ("banners", "#svBannerStack"),
    ("topbar", ".topbar"),
    ("sidebar", ".sidebar, #navMiniTip"),
    ("bands", ".ticker-bar, .data-headband, .hb-restore-tab"),
    ("bar", ".info-panel-wrap, .ip-restore-pill"),
    ("rail", ".signals-rail, .rail-toggle-btn"),
    ("phone_nav", ".sv-phone-nav"),
    ("page", ".page-content"),
)


def census_opts():
    return {"tokens": token_rgbs(), "radii": token_radii(), "money": MONEY, "examples": EXAMPLES,
            "regions": [list(r) for r in REGIONS]}


class _Driver(_Chrome):
    """_Chrome with every request answered here (the DevTools Fetch domain)
    and no host that resolves: nothing the page asks for leaves the
    machine."""

    ARGS = _Chrome.ARGS + ("--host-resolver-rules=MAP * ~NOTFOUND", "--disable-background-networking",
                           "--disable-component-update", "--disable-default-apps", "--disable-sync",
                           "--no-pings", "--lang=en-US", "--force-color-profile=srgb",
                           # The operator's desk: a mouse (hover, a fine pointer). Headless
                           # Chromium has none and answers (hover: none), so the shell drew
                           # its touch look (a card shows only pinned: the ticker's never
                           # opened on a hover). The phone pass emulates touch on its tab.
                           "--blink-settings=primaryHoverType=2,availableHoverTypes=2,"
                           "primaryPointerType=4,availablePointerTypes=4")

    def __init__(self, binary, answer):
        self.answer = answer
        self.ignored = set()
        self.served, self.last_served = 0, time.monotonic()
        super().__init__(binary)

    def _write(self, data):
        view = memoryview(data)
        while view:
            ready_r, ready_w, _x = select.select([self.out_r], [self.cmd_w], [], 60)
            if ready_r:
                chunk = os.read(self.out_r, 1 << 16)
                if not chunk:
                    raise RuntimeError("Chromium closed its pipe")
                self.buf += chunk
            if ready_w:
                n = os.write(self.cmd_w, view[:1 << 16])
                view = view[n:]

    def _send(self, method, params, session, keep):
        self.n += 1
        msg = {"id": self.n, "method": method, "params": params or {}}
        if session:
            msg["sessionId"] = session
        if not keep:
            self.ignored.add(self.n)
        self._write(json.dumps(msg).encode("utf-8") + b"\0")
        return self.n

    def _handled(self, got):
        if got.get("method") == "Fetch.requestPaused":
            self._fulfil(got["params"], got.get("sessionId"))
            return True
        if got.get("id") in self.ignored:
            self.ignored.discard(got["id"])
            return True
        return False

    def call(self, method, params=None, session=None, timeout=90):
        mine = self._send(method, params, session, keep=True)
        while True:
            got = self._recv(timeout)
            if self._handled(got):
                continue
            if got.get("id") == mine:
                if "error" in got:
                    raise RuntimeError("%s: %r" % (method, got["error"]))
                return got.get("result", {})
            self.events.append(got)

    def call_many(self, calls, session, timeout=90):
        """Many commands sent at once, their answers collected in order: a
        forced pass on a thousand nodes costs one round trip, not a
        thousand."""
        ids = [self._send(m, p, session, keep=True) for m, p in calls]
        want, got_by_id = set(ids), {}
        while want:
            got = self._recv(timeout)
            if self._handled(got):
                continue
            if got.get("id") in want:
                want.discard(got["id"])
                got_by_id[got["id"]] = got.get("result", {}) if "error" not in got else {"__error__": got["error"]}
                continue
            self.events.append(got)
        return [got_by_id[i] for i in ids]

    def wait(self, event, session, timeout=45):
        deadline = time.monotonic() + timeout
        while True:
            for i, got in enumerate(self.events):
                if got.get("method") == event and got.get("sessionId") == session:
                    del self.events[i]
                    return got.get("params", {})
            left = deadline - time.monotonic()
            if left <= 0:
                raise TimeoutError("no %s in %ss" % (event, timeout))
            got = self._recv(left)
            if not self._handled(got):
                self.events.append(got)

    def _fulfil(self, p, session):
        self.served += 1
        self.last_served = time.monotonic()
        try:
            got = self.answer(p["request"], p.get("resourceType", ""))
        except Exception as exc:     # a view that raised: a 500, as the server would say
            got = (500, {"Content-Type": "text/plain"}, ("census: %r" % exc).encode("utf-8"))
        if got is None:
            self._send("Fetch.failRequest", {"requestId": p["requestId"], "errorReason": "BlockedByClient"},
                       session, keep=False)
            return
        status, headers, body = got
        self._send("Fetch.fulfillRequest", {
            "requestId": p["requestId"], "responseCode": int(status),
            "responseHeaders": [{"name": k, "value": str(v)} for k, v in headers.items()],
            "body": base64.b64encode(body).decode("ascii")}, session, keep=False)

    def tab(self, width, height, mobile=False, init=""):
        tid = self.call("Target.createTarget", {"url": "about:blank"})["targetId"]
        sid = self.call("Target.attachToTarget", {"targetId": tid, "flatten": True})["sessionId"]
        for method in ("Page.enable", "Runtime.enable", "DOM.enable", "CSS.enable"):
            self.call(method, session=sid)
        self.call("Fetch.enable", {"patterns": [{"urlPattern": "*", "requestStage": "Request"}]}, session=sid)
        self.call("Emulation.setDeviceMetricsOverride", {"width": width, "height": height, "deviceScaleFactor": 1,
                                                         "mobile": mobile}, session=sid)
        if mobile:
            self.call("Emulation.setTouchEmulationEnabled", {"enabled": True, "maxTouchPoints": 5}, session=sid)
        if init:
            self.call("Page.addScriptToEvaluateOnNewDocument", {"source": init}, session=sid)
        return tid, sid

    def quiet(self, sid, still=0.4, cap=15.0):
        """Wait until the page has asked for nothing for `still` seconds
        (or `cap` has passed): what a script fetches after the load, the
        rail's cards, a drawer's rows, a panel's thread, is in the page
        before it is read, on a fast machine as on a slow one."""
        start = time.monotonic()
        while time.monotonic() - start < cap:
            before = self.served
            self.js(sid, "(window.__svClock ? window.__svClock.sleep(120)"
                         " : new Promise(function (r) { setTimeout(r, 120); }))")
            if self.served == before and time.monotonic() - self.last_served >= still:
                return round(time.monotonic() - start, 2)
        return None

    def close_tab(self, tid):
        try:
            self.call("Target.closeTarget", {"targetId": tid})
        except RuntimeError:
            pass

    def go(self, sid, url, timeout=45):
        self.call("Page.navigate", {"url": url}, session=sid)
        self.wait("Page.loadEventFired", sid, timeout)

    def js(self, sid, expression, timeout=90):
        got = self.call("Runtime.evaluate", {"expression": expression, "awaitPromise": True,
                                             "returnByValue": True}, session=sid, timeout=timeout)
        if got.get("exceptionDetails"):
            d = got["exceptionDetails"]
            raise RuntimeError((d.get("exception") or {}).get("description") or d.get("text") or repr(d))
        return got["result"].get("value")

    def nodes(self, sid, selector):
        doc = self.call("DOM.getDocument", {"depth": 0}, session=sid)["root"]["nodeId"]
        return self.call("DOM.querySelectorAll", {"nodeId": doc, "selector": selector}, session=sid)["nodeIds"]

    def force(self, sid, selector, states):
        ids = self.nodes(sid, selector)
        self.call_many([("CSS.forcePseudoState", {"nodeId": nid, "forcedPseudoClasses": list(states)})
                        for nid in ids], sid)
        return len(ids)

    def mouse(self, sid, x, y):
        """The pointer moved to (x, y): a real hover, :hover included."""
        self.call("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y, "button": "none"}, session=sid)

    def key(self, sid, key, code, vk, text="", shift=False):
        mods = 8 if shift else 0
        for kind in ("keyDown", "keyUp"):
            params = {"type": kind, "key": key, "code": code, "windowsVirtualKeyCode": vk, "modifiers": mods}
            if kind == "keyDown" and text:
                params["text"] = text
            self.call("Input.dispatchKeyEvent", params, session=sid)

    def version(self):
        return self.call("Browser.getVersion").get("product", "")

    def faces(self, sid, index):
        ids = self.nodes(sid, '[data-svc="%d"]' % index)
        if not ids:
            return []
        got = self.call("CSS.getPlatformFontsForNode", {"nodeId": ids[0]}, session=sid)
        return [(f["familyName"], f.get("isCustomFont", False), f["glyphCount"]) for f in got["fonts"]]


# ── the book ────────────────────────────────────────────────────────────

def tour_done(user):
    """The guided tour finished (its autostart is a sub-second timer that
    put its card on every page, wherever the read caught it: the review of
    B0). It is measured once, started by hand, in state:tour."""
    from portfolio.trader_profile import TraderProfile
    prof, _ = TraderProfile.objects.get_or_create(user=user)
    prof.tour_completed_at = _frozen_instant()
    prof.save(update_fields=["tour_completed_at"])


def census_book():
    """The synthetic book the pages are measured on (round, invented
    instruments, sizes and ages; nobody's data): real-money eToro longs and
    a paper lane, signals on each side, switches on and off, a legacy row,
    notifications, a news item, a strategy, a letter, a backtest, a
    scenario, an answer from Ask Sauron. Returns the staff user."""
    from tests.one_quote_fixture import T, daily_bar, quote, seed_measured
    from tests.test_close_advice import _legacy, _pin, _quote, _trade
    from tests.test_ops_cockpit import _component
    from tests.test_signal_acted_and_sizing import _signal
    user = get_user_model().objects.create_user("census", password="x", is_staff=True, is_superuser=True)
    _pin(user)
    tour_done(user)
    held = seed_measured(user)
    quote("GBPUSD", "1.29410", "yfinance", 240, chg="-0.21")
    for days, close in ((3, "1.08120"), (2, "1.08300"), (1, "1.08480")):
        daily_bar("EURUSD", T - timedelta(days=days), close)
    _quote("BTCUSD", 64200)
    _quote("ETHUSD", 2600)
    from instruments.models import Instrument
    from market_data.models import LiveQuote
    LiveQuote.objects.filter(instrument__symbol__in=("BTCUSD", "ETHUSD")).update(updated_at=T - timedelta(seconds=20))
    Instrument.objects.filter(symbol__in=("EURUSD", "GBPUSD", "XAUUSD", "AAPL", "BTCUSD")).update(is_watchlist=True)
    paper = _trade(user, symbol="BTCUSD", qty="0.05", entry=63800, stop=62500, target=66500)
    _trade(user, symbol="ETHUSD", side="SELL", qty="1", entry=2650, stop=2720, target=2500)
    _trade(user, symbol="BTCUSD", status="CLOSED", entry=61000, stop=60000, target=63000)
    btc = Instrument.objects.get(symbol="BTCUSD")
    eth = Instrument.objects.get(symbol="ETHUSD")
    _signal(btc, direction="bullish", entry=64200, stop=62400, target=67800, rule="census_up")
    _signal(eth, direction="bearish", entry=2600, stop=2690, target=2420, rule="census_down")
    _component("census_on_switch", is_enabled=True)
    _component("census_off_switch", is_enabled=False)
    _component("orcs", is_enabled=True)          # the Orcs' pages exist while their switch is ON
    _legacy(user)
    # The admin bot panel's rows (/admin-dashboard/, htmx/admin/bots/): its
    # Toggle, Shadow, Reset circuit and Reconcile are §10 money controls the
    # forced pass hovers (the critic's #107), and a panel with no config
    # renders none. Two legacy crypto bots of two other users, both off.
    from bot_program.models import BotConfig
    for name, mode in (("census_bot_paper", "paper"), ("census_bot_live", "live")):
        other = get_user_model().objects.create_user(name, password="x")
        BotConfig.objects.create(user=other, name="Census %s bot" % mode, mode=mode, enabled=False,
                                 symbols=["BTCUSDT"], capital_usdt=Decimal("1000"))
    from alerts.models import Notification
    for title, kind in (("BTCUSD opened 0.05 at 63,800", "trade"), ("New signal: ETHUSD bearish", "signal"),
                        ("Daily summary ready", "system")):
        Notification.objects.create(user=user, notification_type=kind, title=title, body="synthetic", url="/positions/")
    from scraping.models import NewsArticle
    NewsArticle.objects.create(title="Synthetic: central bank holds rates", source="Census wire",
                               url="https://example.com/census-rates", published_at=T - timedelta(hours=2),
                               ai_urgency="high")
    from strategies.models import Strategy
    Strategy.objects.create(name="Census momentum", description="A synthetic strategy.", time_horizon="swing",
                            status="active", pnl=Decimal("120.50"), pnl_pct=1.2, max_drawdown=-2.5)
    from alerts.models import Newsletter
    Newsletter.objects.create(title="Census weekly letter", frequency="weekly", status="sent",
                              content_markdown="## The week\n\nA synthetic letter.")
    from lore.models import LoreEntry
    LoreEntry.objects.create(slug="census-lesson", kind="lesson", title="Census lesson",
                             summary="A synthetic lesson.", mechanism="m", works_when="w", evidence_grade="none",
                             origin="sauron", status="reviewed", regimes_works_flat="|risk_off|", tags_flat="|trend|")
    from bot_program.models import BotBacktestRun, BotScenario
    BotBacktestRun.objects.create(user=user, config_name_snapshot="Crypto", asset_class_snapshot="crypto",
                                  status="complete", stats={"n": 12, "win_rate": 0.5, "total_r": 3.4})
    BotScenario.objects.create(user=user, name="Census scenario", symbols=["BTCUSD"],
                               start_date=(T - timedelta(days=30)).date(), end_date=T.date())
    from bot_program.orcs.models import Orc, OrcLeg, OrcSeat, OrcTrack
    seat, _ = OrcSeat.objects.get_or_create(venue="paper", asset_class=paper.asset_class, rule_key="*")
    orc = Orc.objects.create(seat=seat, user=user, config=paper.config, root_trade=paper, symbol=paper.symbol,
                             side=paper.side, asset_class=paper.asset_class, paper=True, army_type="line", state="born")
    OrcLeg.objects.create(orc=orc, trade=paper, kind="root", seq=1)
    OrcTrack.objects.create(orc=orc, arm="care", state={}, open=True)
    from brain.research_models import ResearchConversation, ResearchMessage
    conv = ResearchConversation.objects.create(user=user, title="Census question")
    ResearchMessage.objects.create(conversation=conv, role="user", content="How is the book doing?")
    ResearchMessage.objects.create(conversation=conv, role="assistant", content=(
        "## The book\n\nTwo **paper** positions and three held at eToro.\n\n"
        "| Symbol | Side |\n|---|---|\n| BTCUSD | LONG |\n| ETHUSD | SHORT |\n\n- a synthetic answer\n- for the census"))
    return user, held, paper


# ── serving the page from the test client ──────────────────────────────

def _static(path):
    from django.contrib.staticfiles import finders
    rel = urllib.parse.unquote(path[len(settings.STATIC_URL):])
    found = finders.find(rel)
    if not found and settings.STATIC_ROOT:
        p = pathlib.Path(settings.STATIC_ROOT) / rel
        found = str(p) if p.is_file() else None
    if not found:
        return 404, {"Content-Type": "text/plain"}, b"not found"
    ctype = mimetypes.guess_type(found)[0] or "application/octet-stream"
    if ctype.startswith("text/") or ctype in ("application/javascript",):
        ctype += "; charset=utf-8"
    return 200, {"Content-Type": ctype, "Cache-Control": "max-age=3600"}, pathlib.Path(found).read_bytes()


_HX = re.compile(r"<(?P<tag>[a-z]+)\b(?P<attrs>[^>]*\bhx-get=\"(?P<url>[^\"]+)\"[^>]*)>", re.I)


def _fill_htmx(markup, get):
    """The regions htmx fills by itself (hx-trigger load or every), filled
    from their own routes as htmx would: innerHTML, or the hx-target's."""
    out, pos = [], 0
    for m in _HX.finditer(markup):
        attrs = m.group("attrs")
        trig = re.search(r'hx-trigger="([^"]*)"', attrs)
        if not trig or not re.search(r"\b(load|every)\b", trig.group(1)):
            continue
        if re.search(r'hx-target="', attrs):
            continue
        tag = m.group("tag").lower()
        # the element's own end: count its kind open and shut
        depth, i = 1, m.end()
        opener, closer = re.compile(r"<%s\b" % tag, re.I), re.compile(r"</%s\s*>" % tag, re.I)
        while depth and i < len(markup):
            a, b = opener.search(markup, i), closer.search(markup, i)
            if not b:
                break
            if a and a.start() < b.start():
                depth += 1
                i = a.end()
            else:
                depth -= 1
                i = b.end() if depth else b.start()
        body = get(m.group("url").replace("&amp;", "&"))
        if body is None:
            continue
        out.append(markup[pos:m.end()])
        out.append(body)
        pos = i
    out.append(markup[pos:])
    return "".join(out)


class _Server:
    """Answers Chromium's requests for one scene: the census origin from the
    test client (or static/), Google's font sheet with nothing (the faces
    of the machine draw), every other host refused."""

    def __init__(self, client):
        self.client = client
        self.post = {}          # path regex -> (status, JSON) for a synthetic preview
        self.seen = []

    def get_body(self, path):
        resp = self.client.get(path, HTTP_HOST=HOST, HTTP_HX_REQUEST="true")
        if resp.status_code != 200 or getattr(resp, "streaming", False):
            return None
        return resp.content.decode("utf-8")

    def __call__(self, request, rtype):
        url = urllib.parse.urlsplit(request["url"])
        method = request.get("method", "GET")
        if url.scheme in ("data", "blob"):
            return None
        if url.hostname == "fonts.googleapis.com":
            return 200, {"Content-Type": "text/css; charset=utf-8"}, b""
        if url.hostname != ORIGIN_HOST:
            self.seen.append("refused " + request["url"][:80])
            return None
        path = url.path + ("?" + url.query if url.query else "")
        if url.path.startswith(settings.STATIC_URL):
            return _static(url.path)
        if url.path.startswith("/ws/"):
            return None
        if method not in ("GET", "HEAD"):
            for pattern, (status, payload) in self.post.items():
                if re.search(pattern, url.path):
                    self.seen.append("synthetic %s %s" % (method, url.path))
                    return status, {"Content-Type": "application/json"}, json.dumps(payload).encode("utf-8")
            self.seen.append("withheld %s %s" % (method, url.path))
            return 204, {"Content-Type": "text/plain"}, b""
        headers = {"HTTP_HOST": HOST}
        for k, v in (request.get("headers") or {}).items():
            if k.lower() in ("accept", "x-requested-with", "hx-request", "hx-target", "hx-current-url"):
                headers["HTTP_" + k.upper().replace("-", "_")] = v
        resp = self.client.get(path, **headers)
        if getattr(resp, "streaming", False):
            return None
        body = resp.content
        out = {"Content-Type": resp.get("Content-Type", "text/html; charset=utf-8")}
        if resp.status_code in (301, 302, 303, 307, 308):
            loc = urllib.parse.urlsplit(resp["Location"])
            out["Location"] = ORIGIN + loc.path + ("?" + loc.query if loc.query else "")
        if rtype == "Document" and resp.status_code == 200 and out["Content-Type"].startswith("text/html"):
            body = _fill_htmx(body.decode("utf-8"), self.get_body).encode("utf-8")
        return resp.status_code, out, body


# ── the scenes: every routed page, and the states ──────────────────────

#: The routes measured as pages: every page route but the ones that end
#: the session or are not a page. Parameters come from the book: each
#: detail route is reached by the first link its list page prints.
DETAIL_LINKS = {
    "/bot-backtest/<int:run_id>/": ("/bot-backtest/", r'href="(/bot-backtest/\d+/)"'),
    "/bot/scenarios/<int:pk>/": ("/bot/scenarios/", r'(?:href="|location=\')(/bot/scenarios/\d+/)'),
    "/knowledge/<str:kind>/<path:key>/": ("/knowledge/", r'href="(/knowledge/[a-z_]+/[^"/]+/)"'),
    "/lore/<slug:slug>/": ("/lore/", r'href="(/lore/[\w-]+/)"'),
    "/news/<int:pk>/": ("/news/", r'href="(/news/\d+/)"'),
    "/newsletters/<int:pk>/": ("/newsletters/", r'href="(/newsletters/\d+/)"'),
    "/orcs/<int:trade_id>/": ("/orcs/", r'href="(/orcs/\d+/)"'),
    "/strategies/<int:pk>/": ("/strategies/", r'href="(/strategies/\d+/)"'),
}
#: Anonymous pages, and the pages a session in a given state opens.
ANON = ("/login/", "/wall/", "/book/")
SESSION_STATE = {"/login/pin/": "pending", "/login/pin/forgot/": "pending", "/locked/": "locked", "/intro/": "intro",
                 "/investor/": "investor"}
#: A detail route whose list page prints no link for it: the path asked.
DETAIL_FALLBACK = {"/knowledge/<str:kind>/<path:key>/": "/knowledge/rule/census_up/"}


#: Every routed page: the 105 routes of the old-design sweep (94 under
#: base.html, 11 standalone; read from the URL conf at 349b1ca), but
#: /logout/, which ends the session; and the two whose template's name
#: starts with "_", which the sweep took for partials (the review of B0):
#: /popout/ (_popout.html, B15) and /strategies/new/ (_strategy_wizard.html
#: under base.html, B17). tests/old_design/routes.py holds this list to the
#: URL conf.
PAGES = (
    "/admin-dashboard/", "/admin-dashboard/books/", "/admin-dashboard/eye/", "/admin-dashboard/newsletters/",
    "/admin-dashboard/system-map/", "/ai-journal/", "/ai-models/", "/ai/", "/ai/tasks/", "/allocator/",
    "/asset-bots/", "/audit/", "/backtest/", "/big-money/", "/book/", "/bot-backtest/",
    "/bot-backtest/<int:run_id>/", "/bot-charts/", "/bot-performance/", "/bot/", "/bot/configure/",
    "/bot/console/", "/bot/link/", "/bot/scenarios/", "/bot/scenarios/<int:pk>/", "/bot/scenarios/new/",
    "/brain/", "/briefing/", "/brokers/", "/calendar/", "/calibration/", "/command/", "/consolidation/",
    "/council/", "/design/kit/", "/desk/", "/discoveries/", "/earnings-reviews/", "/events/", "/evidence/",
    "/evolution/", "/eye/", "/eye/exposure/", "/eye/fills/", "/eye/gate-events/", "/forensics/",
    "/forensics/<int:trade_id>/", "/generated/", "/getting-started/", "/health/", "/horizon/", "/hypotheses/",
    "/instruments/", "/instruments/<str:symbol>/", "/intelligence/", "/intro/", "/investor/",
    "/investor/live/", "/knowledge/", "/knowledge/<str:kind>/<path:key>/", "/liquidations/", "/locked/",
    "/login/", "/login/pin/", "/login/pin/forgot/", "/lore/", "/lore/<slug:slug>/", "/news/",
    "/news/<int:pk>/", "/newsletter/unsubscribe/<str:token>/", "/newsletters/", "/newsletters/<int:pk>/",
    "/notifications/", "/notifications/settings/", "/oculus/", "/opportunities/", "/ops/", "/orcs/",
    "/orcs/<int:trade_id>/", "/orcs/seats/", "/passation/", "/performance/", "/personas/", "/popout/", "/portfolio/",
    "/portfolio/live/", "/positions/", "/positions/live/", "/profile/", "/promotions/", "/research/", "/risk/",
    "/risk/live/", "/rule-control/", "/setup/", "/setups/", "/shares/", "/short-proofs/", "/signals/",
    "/strategies/", "/strategies/<int:pk>/", "/strategies/new/", "/tax-lots/", "/treasury/", "/wall/", "/withdrawals/",
)

#: The live shells: the same view and template as their page, without the
#: shell (dashboard/_live_shell.html), refreshed into the page's live
#: regions. Their markup is the page's own, measured with it.
IN_HOST = {"/positions/live/": "/positions/", "/portfolio/live/": "/portfolio/", "/risk/live/": "/risk/",
           "/investor/live/": "/investor/"}

#: The partial routes, measured in the page that loads them (the critic's
#: hole 1): /command/'s four tabs (live is the page itself), the KPI strips
#: and the bot panel (filled with their pages), /eye/'s body (with /eye/).
PARTIAL_SCENES = (("/command/?tab=portfolio", "/command/tab/portfolio/"),
                  ("/command/?tab=history", "/command/tab/history/"),
                  ("/command/?tab=bots", "/command/tab/bots/"))

#: A browser's start: the clock at T, the saved choices this scene wants,
#: and the live socket this scene wants: one that opens and stays quiet, as
#: the live pipe does between pushes ("quiet"), one that opens and drops,
#: and never comes back ("drop": the bell offline), or none at all.
#:
#: And the page's timers held. Every timer it sets with a delay (the live
#: pill's first poll at 1.5 s, the nav dots' and Gollum's at 2 s, the
#: Horde's first tab, the Wall's labels every 1.1 s, a whisper hidden after
#: 6 s, every poll, a hover's 450 ms beat, /intro/'s steps every 150 to
#: 400 ms) waits on a clock of its own that only the run moves
#: (__svClock.advance), firing them in their order and letting each one's
#: fetches land before the next. A census read on either side of the
#: 1.5 s poll counted the pill's glow in one run and not in the next, the
#: Gollum whisper on 34 pages, and /intro/'s step text, under a second
#: and random, once in six (the review of B0); on the held clock every run
#: reads every page at the same instant of its life, on a fast machine as
#: on a slow one. setTimeout(fn) and setTimeout(fn, 0) run as they are.
#:
#: And its idle callbacks (2026-11-14). Chromium runs a requestIdleCallback
#: on the real clock: at the renderer's first idle moment, or at its
#: timeout in wall time. The Horde's first tab read rides on one
#: (sv-horde.js firstTab, timeout 1.5 s): on a runner too busy to idle, the
#: census read the tab before it, still its skeleton "THE HORDE · 6 seats",
#: whose name fits the widest tier and shows in the Eye's green
#: (/ai-journal/: eye_text 13, budget 12, on PR #109; the painted tab drops
#: a tier and hides the name). Held, each one runs when the held clock
#: reaches its timeout (1 ms without one), as an idle period that timed
#: out, in order with the timers.
#:
#: The page's Date reads T plus the held clock (not the wall clock's
#: elapsed time), and Math.random is seeded: the same draws in every run.
INIT = r"""(function () {
  var nST = window.setTimeout, nCT = window.clearTimeout, nSI = window.setInterval, nCI = window.clearInterval;
  var nFetch = window.fetch, vnow = 0, seq = 0, held = {}, flying = 0;
  function hold(fn, ms, args, every) {
    seq += 1;
    var id = 1000000000 + seq;
    held[id] = {due: vnow + ms, fn: fn, args: args, every: every ? Math.max(ms, 1) : 0, seq: seq};
    return id;
  }
  window.setTimeout = function (fn, ms) {
    ms = +ms || 0;
    if (ms <= 0) return nST.apply(window, arguments);
    return hold(fn, ms, Array.prototype.slice.call(arguments, 2), false);
  };
  window.setInterval = function (fn, ms) {
    ms = +ms || 0;
    return hold(fn, Math.max(ms, 1), Array.prototype.slice.call(arguments, 2), true);
  };
  window.clearTimeout = function (id) { if (held[id]) delete held[id]; else nCT.call(window, id); };
  window.clearInterval = function (id) { if (held[id]) delete held[id]; else nCI.call(window, id); };
  window.requestIdleCallback = function (fn, opts) {
    var ms = Math.max(+(opts && opts.timeout) || 0, 1);
    return hold(function () { fn({didTimeout: true, timeRemaining: function () { return 0; }}); }, ms, [], false);
  };
  window.cancelIdleCallback = function (id) { delete held[id]; };
  if (nFetch) {
    window.fetch = function () {
      flying += 1;
      var p = nFetch.apply(this, arguments);
      var done = function () { flying -= 1; };
      p.then(done, done);
      return p;
    };
  }
  var nSend = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.send = function () {
    flying += 1;
    this.addEventListener('loadend', function () { flying -= 1; });
    return nSend.apply(this, arguments);
  };
  function sleep(ms) { return new Promise(function (r) { nST.call(window, r, ms); }); }
  function landed() {
    return new Promise(function (r) {
      var t0 = performance.now();
      (function poll() {
        if (flying <= 0 || performance.now() - t0 > 8000) { nST.call(window, r, flying > 0 ? 0 : 40); return; }
        nST.call(window, poll, 10);
      })();
    });
  }
  window.__svClock = {
    native: function (fn, ms) { return nST.call(window, fn, ms); },
    sleep: sleep,
    now: function () { return vnow; },
    advance: async function (ms) {
      var to = vnow + ms, fired = 0;
      await landed();
      for (var guard = 0; guard < 2000; guard++) {
        var next = null, nid = null;
        for (var k in held) {
          var h = held[k];
          if (h.due <= to && (!next || h.due < next.due || (h.due === next.due && h.seq < next.seq))) { next = h; nid = k; }
        }
        if (!next) break;
        vnow = next.due;
        if (next.every) next.due += next.every; else delete held[nid];
        try { if (typeof next.fn === 'function') next.fn.apply(window, next.args); else if (typeof next.fn === 'string') (0, eval)(next.fn); }
        catch (e) { (window.__svClockErrors = window.__svClockErrors || []).push(String(e).slice(0, 200)); }
        fired += 1;
        // What the timer started lands before the next one fires; a timer
        // that started nothing costs one turn of the event loop.
        if (flying > 0) await landed(); else await sleep(0);
      }
      vnow = to;
      await landed();
      return fired;
    }
  };
  var T0 = %(t)d, D = Date;
  function SvDate(a, b, c, d, e, f, g) {
    if (!(this instanceof SvDate)) return new D(T0 + vnow).toString();
    var x = arguments.length === 0 ? new D(T0 + vnow)
          : arguments.length === 1 ? new D(a) : new D(a, b, c === undefined ? 1 : c, d || 0, e || 0, f || 0, g || 0);
    Object.setPrototypeOf(x, SvDate.prototype);
    return x;
  }
  SvDate.prototype = D.prototype;
  SvDate.now = function () { return T0 + vnow; };
  SvDate.parse = D.parse; SvDate.UTC = D.UTC;
  window.Date = SvDate;
  var seed = 0x5eed1e55;
  Math.random = function () {
    seed = (seed + 0x6D2B79F5) | 0;
    var r = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    r = (r + Math.imul(r ^ (r >>> 7), 61 | r)) ^ r;
    return ((r ^ (r >>> 14)) >>> 0) / 4294967296;
  };
  try {
    localStorage.clear(); sessionStorage.clear();
    var prefs = %(prefs)s;
    for (var k in prefs) localStorage.setItem(k, prefs[k]);
  } catch (e) {}
  var ws = %(ws)s, opened = {};
  if (ws !== 'none') {
    window.WebSocket = function (url) {
      var self = this; this.url = url; this.readyState = 0;
      var first = !opened[url];
      opened[url] = true;
      if (ws === 'drop' && !first) return;          // each pipe, once dropped, stays down
      nST.call(window, function () {
        self.readyState = 1; if (self.onopen) self.onopen({});
        if (ws === 'drop') nST.call(window, function () { self.readyState = 3; if (self.onclose) self.onclose({}); }, 30);
      }, 30);
    };
    window.WebSocket.prototype.send = function () {};
    window.WebSocket.prototype.close = function () { this.readyState = 3; };
    window.WebSocket.prototype.addEventListener = function () {};
    window.WebSocket.OPEN = 1; window.WebSocket.CONNECTING = 0; window.WebSocket.CLOSED = 3;
  }
})();"""

#: The held clock moved on by this many ms, its timers fired in order.
ADVANCE = "(window.__svClock ? window.__svClock.advance(%d) : 0)"
LOAD_MS, ACT_MS = 2600, 1600

#: A page that sets a timer and asks for idle callbacks (one with a
#: timeout, one without, one cancelled), each noting the held clock and
#: its deadline when it runs (MeasuredClockTests).
CLOCK_PAGE = b"""<!doctype html><html><head><meta charset="utf-8"></head><body><script>
window.__ran = [];
function note(what) {
  return function (deadline) { window.__ran.push([what, window.__svClock.now(), deadline ? deadline.didTimeout : null]); };
}
setTimeout(note('timer 500'), 500);
requestIdleCallback(note('idle 1500'), {timeout: 1500});
requestIdleCallback(note('idle'));
cancelIdleCallback(requestIdleCallback(note('idle cancelled'), {timeout: 100}));
</script></body></html>"""


def held_clock_trace(wait_s=2.0):
    """What CLOCK_PAGE's timer and idle callbacks did under INIT: once
    loaded and left `wait_s` on the real clock (nothing, when every one
    waits for the held clock), then with the held clock moved 1 s, then
    2 s."""
    def answer(request, rtype):
        url = urllib.parse.urlsplit(request["url"])
        if url.hostname == ORIGIN_HOST and url.path == "/__census__/clock/":
            return 200, {"Content-Type": "text/html; charset=utf-8"}, CLOCK_PAGE
        return None
    driver = _Driver(CHROME, answer=answer)
    try:
        tid, sid = driver.tab(800, 600, False, INIT % {"t": int(_frozen_instant().timestamp() * 1000),
                                                       "prefs": "{}", "ws": json.dumps("none")})
        driver.go(sid, ORIGIN + "/__census__/clock/")
        driver.js(sid, "window.__svClock.sleep(%d)" % int(wait_s * 1000))
        out = {"real": driver.js(sid, "window.__ran.slice()")}
        for held in (1000, 2000):
            driver.js(sid, ADVANCE % 1000)
            out["held %d" % held] = driver.js(sid, "window.__ran.slice()")
        driver.close_tab(tid)
    finally:
        driver.close()
    return out

#: The page at rest, whatever the clock did. A card the motion layer
#: (sv-motion.js) hid below the fold until it scrolls in, or until its
#: safety timer 2.5 s after the load, is shown now, as the operator sees
#: it once there: the census measured it in one run and not in the next
#: when it ran either side of that timer. A count-up the scroll of an
#: act started is let finish. Finite animations end where they end; a
#: loop is left running, it is what anim_loop counts.
SETTLE = r"""(async function (ms) {
  try { await document.fonts.ready; } catch (e) {}
  var frame = function () { return new Promise(function (r) { requestAnimationFrame(function () { requestAnimationFrame(r); }); }); };
  var sleep = function (t) {
    return window.__svClock ? window.__svClock.sleep(t) : new Promise(function (r) { setTimeout(r, t); });
  };
  await frame();
  await sleep(ms);
  /* The marquee (claude/marquee, when it lands) moves its strips on every
     frame: held at their start, they read the same in every run. */
  if (window.SVMarquee) {
    document.querySelectorAll('.ticker-track, .dh-track').forEach(function (track) {
      try { window.SVMarquee.hold(track, 'census', true); window.SVMarquee.to(track, 0); } catch (e) {}
    });
  }
  document.querySelectorAll('.sv-rv').forEach(function (el) {
    el.classList.remove('sv-rv', 'in'); el.style.removeProperty('--sv-i');
  });
  if (document.body) document.body.classList.remove('sv-leaving');
  var counting = function () {
    return Array.prototype.filter.call(document.querySelectorAll('[data-sv-count]'), function (e) { return e.__svCounted; })
      .map(function (e) { return e.textContent; }).join('|');
  };
  var was = counting();
  for (var tick = 0; was && tick < 15; tick++) {
    await sleep(120);
    var now = counting();
    if (now === was) break;
    was = now;
  }
  for (var round = 0; round < 6; round++) {
    var moving = 0;
    document.getAnimations().forEach(function (a) {
      var t = a.effect && a.effect.getComputedTiming();
      if (t && t.iterations !== Infinity && a.playState !== 'finished') { moving++; try { a.finish(); } catch (e) {} }
    });
    await frame();
    if (!moving) break;
  }
  return 1;
})(%d)"""


#: What the critic's hole 1 is about, read after the census: regions htmx
#: or a script fills, and whether they were filled.
PROBE = r"""(function () {
  function n(sel) { return document.querySelectorAll(sel).length; }
  return {metricsEmpty: n('.sv-metrics-wrapper:empty'), metricsFilled: n('.sv-metrics-wrapper > *'),
          ocLoading: n('#ocTabBody .oc-loading, .oc-loading'), ocBody: n('#ocTabBody > *'),
          adminBots: n('.admin-bots'), eyeBody: n('#eyeBody > *, [hx-get*="/eye/partial/"] > *'),
          railCards: n('.signals-rail .sr-signal'), dialogs: n('.sv-dialog'), popups: n('.sr-popup.show, .sr-popup.sv-pinned'),
          width: innerWidth, hover: matchMedia('(hover: hover)').matches, coarse: matchMedia('(pointer: coarse)').matches};
})()"""


#: What is on the screen, in short: a state's act must change it.
FINGERPRINT = r"""(function () {
  var keys = [], h = 2166136261;
  document.querySelectorAll('body *').forEach(function (e) {
    if (e.tagName === 'SCRIPT' || e.tagName === 'STYLE' || !e.checkVisibility({checkOpacity: true, checkVisibilityCSS: true})) return;
    var r = e.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) return;
    var c = typeof e.className === 'string' ? e.className : '';
    var k = e.tagName + (e.id ? '#' + e.id : '') + (c ? '.' + c.trim().split(/\s+/).slice(0, 3).join('.') : '');
    keys.push(k);
    for (var i = 0; i < k.length; i++) { h ^= k.charCodeAt(i); h = Math.imul(h, 16777619); }
  });
  return {n: keys.length, h: (h >>> 0).toString(16), keys: keys.slice(-40)};
})()"""

#: Whether what a state opens is on the screen: one visible match of the
#: selector, or the text in the page's visible text.
SHOWN = r"""(function (sel, text) {
  if (sel) {
    return Array.prototype.some.call(document.querySelectorAll(sel), function (e) {
      var r = e.getBoundingClientRect();
      return e.checkVisibility({checkOpacity: true, checkVisibilityCSS: true}) && r.width >= 1 && r.height >= 1;
    });
  }
  return (document.body.innerText || '').indexOf(text) >= 0;
})(%s, %s)"""


def _click(sel, nth=0, text=None):
    return ("(function () { var all = Array.prototype.filter.call(document.querySelectorAll(%s), function (e) {"
            " return e.checkVisibility() && (!%s || (e.innerText || '').toUpperCase().indexOf(%s) >= 0); });"
            " var e = all[%d]; if (!e) throw new Error('nothing to click: ' + %s);"
            " e.scrollIntoView({block: 'center'}); e.click(); return all.length; })()"
            % (json.dumps(sel), json.dumps(text), json.dumps(text or ""), nth, json.dumps(sel)))


def _hover(sel, text=None):
    """A real hover (the pointer moved over the first visible match, by
    DevTools): CSS :hover holds, and the page's own mouse events fire. A
    synthetic MouseEvent set neither (the sessions menu, the live-status
    list and the ticker card open on :hover: the review of B0)."""
    return ("mouse", sel, text)


def _key(key, code, vk, text="", shift=False):
    """A real key press, by DevTools."""
    return ("key", key, code, vk, text, shift)


#: Where the pointer goes: the first visible match, scrolled to the middle.
POINT = ("(function () { var all = Array.prototype.filter.call(document.querySelectorAll(%s), function (e) {"
         " return e.checkVisibility() && (!%s || (e.innerText || '').toUpperCase().indexOf(%s) >= 0); });"
         " var e = all[0]; if (!e) throw new Error('nothing to hover: ' + %s);"
         " e.scrollIntoView({block: 'center'}); var r = e.getBoundingClientRect();"
         " var y = r.top + r.height / 2, fx = [0.5, 0.3, 0.7, 0.15, 0.85];"
         " for (var i = 0; i < fx.length; i++) { var x = Math.min(innerWidth - 2, Math.max(1, r.left + r.width * fx[i]));"
         "   var hit = document.elementFromPoint(x, y); if (hit && (hit === e || e.contains(hit))) return [x, y]; }"
         " return [Math.min(innerWidth - 2, Math.max(1, r.left + r.width / 2)), y]; })()")


def _then(*steps):
    """Steps run in order, each followed by STEP_MS of the held clock (a
    menu that opens on a timer is open before the next step)."""
    return list(steps)


class Scene(dict):
    """One measurement: a path, the client that asks it, the saved choices,
    what is done on the page (`act`: a script, a real hover or key, or a
    list of them), and how it is read (rest, forced, phone, light). A state
    names what its act opens (`shows`: a selector that must be on screen,
    or `shows_text`), and an act that changes nothing on the page fails:
    a state that never opened is not measured as itself (the review of B0
    found nine that read as their page)."""

    def __init__(self, key, path, **kw):
        super().__init__(key=key, path=path, client=kw.pop("client", "main"), rail=kw.pop("rail", "closed"),
                         sidebar=kw.pop("sidebar", "full"), bands=kw.pop("bands", False), ws=kw.pop("ws", "quiet"),
                         act=kw.pop("act", None), post=kw.pop("post", {}), real_post=kw.pop("real_post", ()),
                         mode=kw.pop("mode", "rest"), width=kw.pop("width", 1440), height=kw.pop("height", 900),
                         mobile=kw.pop("mobile", False), cookie=kw.pop("cookie", None), need=kw.pop("need", None),
                         shows=kw.pop("shows", None), shows_text=kw.pop("shows_text", None),
                         prefs=kw.pop("prefs", {}))
        assert not kw, kw


#: The forced pass's pages: the §10 money controls' (the critic's §3 table
#: and its hole 2), each with every control of its page forced.
FORCED_PAGES = ("/positions/", "/ops/", "/instruments/EURUSD/", "/brokers/", "/setup/", "/withdrawals/",
                "/asset-bots/", "/command/", "/admin-dashboard/", "/shares/", "/personas/", "/promotions/",
                "/knowledge/", "/short-proofs/", "/treasury/")
PHONE_PAGES = ("/positions/", "/ops/", "/instruments/EURUSD/", "/brokers/", "/setup/", "/withdrawals/",
               "/asset-bots/", "/command/")
LIGHT_PAGES = ("/positions/", "/ops/", "/command/")
#: What the light pass reads (§10's meanings in light mode, the critic's
#: hole 4, #116): the phone pass reads every marker (the review of B0).
LIGHT_MARKERS = ("red_fill",)
#: The held clock between two steps of one act.
STEP_MS = 600

#: Synthetic close previews (the shape base.html's closeFlow reads; never
#: sent to the server): a live EURUSD row and a paper BTCUSD row.
CLOSE_PREVIEW = {
    "live": {"ok": True, "side": "BUY", "qty": "10,000", "symbol": "EURUSD", "entry": "1.08210", "mark": 1.08452,
             "exit": "1.08447", "pnl": "+23.70", "r": "0.76", "venue": "live", "asset_class": "forex"},
    "paper": {"ok": True, "side": "BUY", "qty": "0.05", "symbol": "BTCUSD", "entry": "63,800.00", "mark": 64200.0,
              "exit": "64,190.00", "pnl": "+19.50", "r": "0.30", "venue": "paper", "asset_class": "crypto"},
}


def build_scenes(details, live_id, paper_id):
    """Every scene of a run: the pages, the partial routes, the states, the
    forced, phone and light passes, the error pages."""
    out = []
    for route in PAGES:
        if route in IN_HOST:
            continue
        if route == "/instruments/<str:symbol>/":
            out += [Scene("/instruments/EURUSD/", "/instruments/EURUSD/"), Scene("/instruments/BTCUSD/", "/instruments/BTCUSD/")]
        elif route == "/forensics/<int:trade_id>/":
            out += [Scene("/forensics/<live>/", "/forensics/%d/" % live_id),
                    Scene("/forensics/<paper>/", "/forensics/%d/" % paper_id)]
        elif route == "/newsletter/unsubscribe/<str:token>/":
            out.append(Scene(route, details.get(route) or "/newsletter/unsubscribe/census/", client="anon"))
        elif route in DETAIL_LINKS:
            out.append(Scene(route, details.get(route), need=route))
        elif route in ANON:
            out.append(Scene(route, route, client="anon"))
        elif route in SESSION_STATE:
            out.append(Scene(route, route, client=SESSION_STATE[route]))
        else:
            out.append(Scene(route, route))
    for path, partial in PARTIAL_SCENES:
        out.append(Scene(partial, path))
    S = lambda key, path="/command/", **kw: out.append(Scene("state:" + key, path, **kw))
    S("rail_bullish", "/positions/", rail="open", shows=".sr-popup.show, .sr-popup.sv-pinned",
      act=_click(".signals-rail .sr-signal-wrap:not(:has(.sr-badge-bearish)) .sr-signal"))
    S("rail_bearish", "/positions/", rail="open", shows=".sr-popup.show, .sr-popup.sv-pinned",
      act=_click(".signals-rail .sr-signal-wrap:has(.sr-badge-bearish) .sr-signal"))
    # The closed rail (its dock) is every page's; the open rail with both
    # its sections folded is the rail's other resting state.
    S("rail_folded", rail="open", prefs={"sauron_rail_sig": "1", "sauron_rail_watch": "1"},
      shows="#signalsRail.open #railSignals.collapsed")
    S("quote_card", act=_then(_hover(".data-headband .dh-item"), _click(".data-headband .dh-item")), shows=".dh-pop")
    S("news_card", act=_hover(".ticker-bar .ticker-item"), shows=".ticker-popup")
    # The bar's dropdowns are portalled to <body> (base.html), pinned on a
    # click. B1 (the desk v2 board, 2026-11-13): POSITIONS waits in "N more"
    # (the Horde stands in its place), which opens first; SIGNALS left the
    # bar for the dock and the rail (its cell waits unseen, .sv-more-gone),
    # whose states are measured above, so the bar has no SIGNALS state.
    S("bar_portfolio", act=_click(".info-panel-wrap .ip-cat", text="PORTFOLIO"), shows=".ip-dropdown.sv-pinned")
    S("bar_positions", act=_then(_click("#svMoreBtn"), _click(".info-panel-wrap .ip-cat", text="POSITIONS")),
      shows=".ip-dropdown.sv-pinned")
    S("bell", act=_click("#notifBell"), shows="#notifPanel")
    S("bell_offline", ws="drop", act=_click("#notifBell"), shows="#notifBell.is-offline")
    S("user_menu", act=_click("#userMenuTrigger"), shows=".user-menu-dropdown")
    S("sessions_menu", act=_hover(".exchange-indicator"), shows=".exchange-dropdown")
    S("live_status", act=_hover("#liveStatusPill"), shows="#liveStatusDropdown")
    S("instrument_preview", "/instruments/", act=_hover(".page-content [data-instrument]"), shows=".instrument-preview")
    S("fill_banner", act="window.svBanner('fill_open', {symbol: 'BTCUSD', side: 'BUY', qty: '0.05', entry: '64,200.00',"
                         " asset_class: 'crypto', rule_name: 'census_up', paper: true}) || 1", shows="#svBannerStack > *")
    # B1 (the desk v2 board): the Horde opens from its cell in the bar, the
    # Council and the activity from the dock on the right edge; the old
    # edge tabs are gone from 769 px up.
    S("horde", "/positions/", act=_click("#svHordeCell"), shows=".sv-horde-panel")
    S("council", act=_click('.sv-dock-btn[data-sv-dock="council"]'), shows=".sv-council-band-panel")
    S("activity", act=_click('.sv-dock-btn[data-sv-dock="activity"]'), shows=".sv-activity-panel")
    S("ask_sauron", act=_click("#seEyeFab"), shows="#seChatPanel")
    S("gollum", act=_click("#gollumFab"), shows="#gollumDialog")
    S("tour", act="(window.SV && SV.tour && SV.tour.start(), 1)", shows="#svTourCard")
    S("kbd_help", act=_key("?", "Slash", 191, text="?", shift=True), shows="#kbdModalOverlay.open")
    S("idle_lock", act="(window.svIdleLock && window.svIdleLock.engage(false), 1)", shows="#idleLockOverlay")
    S("sidebar_mini", sidebar="mini", act=_hover(".sidebar .nav-link:not(.active)"), shows="#navMiniTip")
    # The bar is always shown from 769 px up (B1, the desk v2 board): no
    # minimise tab, no restore pill, so no minimised state.
    S("bands_hidden", bands=True, shows=".hb-restore-tab")
    S("take_trade_paper", "/instruments/BTCUSD/", act=_click(".tk-side.tk-long"), shows=".sz-dialog",
      real_post=(r"^/instruments/BTCUSD/take-trade/preview/$",))
    # Made from the paper preview at run time ("@live", "@short").
    S("take_trade_live", "/instruments/EURUSD/", act=_click(".tk-side.tk-long"), shows=".sz-dialog",
      post={r"/take-trade/preview/$": (200, "@live")})
    S("take_trade_short", "/instruments/BTCUSD/", act=_click(".tk-side.tk-long"), shows=".sz-dialog .sz-fund",
      post={r"/take-trade/preview/$": (200, "@short")})
    S("close_live", "/positions/", act=_click('[data-sv-close-trade="%d"]' % live_id), shows=".sv-dialog",
      post={r"/positions/\d+/close/preview/$": (200, CLOSE_PREVIEW["live"])})
    S("close_paper", "/positions/", act=_click('[data-sv-close-trade="%d"]' % paper_id), shows=".sv-dialog",
      post={r"/positions/\d+/close/preview/$": (200, CLOSE_PREVIEW["paper"])})
    S("close_all_preview", "/positions/", act=_click("#svCloseAll"), shows=".sv-dialog",
      real_post=(r"^/positions/close-all/preview/$",))
    S("close_selected_preview", "/positions/", shows=".sv-dialog",
      act=_then(_click("[data-sv-select-trade]"), _click("[data-sv-select-bar] button", text="CLOSE")),
      real_post=(r"^/positions/close-selected/preview/$", r"^/positions/close-advice/$"))
    S("level_editor", "/positions/", act=_click(".lvl-edit"), shows=".lvl-dlg")
    S("deep_link", "/positions/%d/close-dialog/" % live_id, shows=".sv-deeplink-note, .sv-dialog")
    S("messages", "/withdrawals/", cookie="messages", shows_text="Saved: the synthetic reservation.")
    S("wall_signin", "/wall/", client="anon", act=_click("a.btn-access"), shows=".login-overlay")
    S("wall_pin", "/wall/", client="anon", act=_then(_click("a.btn-access"), "document.body.classList.add('pin-mode') || 1"),
      shows=".pin-overlay")
    S("empty_positions", "/positions/", client="empty")
    S("empty_command", "/command/", client="empty")
    for page in FORCED_PAGES:
        out.append(Scene("hover:" + page, page, mode="forced"))
    out.append(Scene("hover:state:take_trade_paper", "/instruments/BTCUSD/", mode="forced", act=_click(".tk-side.tk-long"),
                     shows=".sz-dialog", real_post=(r"^/instruments/BTCUSD/take-trade/preview/$",)))
    out.append(Scene("hover:state:close_live", "/positions/", mode="forced", act=_click('[data-sv-close-trade="%d"]' % live_id),
                     shows=".sv-dialog", post={r"/positions/\d+/close/preview/$": (200, CLOSE_PREVIEW["live"])}))
    for page in PHONE_PAGES:
        out.append(Scene("390:" + page, page, mode="phone", width=390, height=844, mobile=True))
    for page in LIGHT_PAGES:
        out.append(Scene("light:" + page, page, mode="light"))
    for code in ("404", "403", "403_csrf", "500"):
        out.append(Scene("error:" + code, "/__census__/error/%s/" % code, client="anon"))
    return out


# ── the run ─────────────────────────────────────────────────────────────

def faces_present():
    """Whether the machine draws Inter and JetBrains Mono itself (the glyph
    census reads which face drew each glyph; on a machine without them
    every glyph would fall to another face). The CI job installs both."""
    try:
        out = subprocess.run(["fc-list", ":", "family"], capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return "Inter" in out and "JetBrains Mono" in out


#: What the machine draws with, as the budget records it (the review of
#: B0: the budgets were taken in Chrome for Testing 153 with this machine's
#: faces, and a CI runner with another browser or other faces counts
#: otherwise). The CI job installs the same browser (Playwright 1.63.0's
#: Chromium 1243, Chrome for Testing 153.0.8010.12), the same faces and the
#: same fontconfig preference (tests/old_design/fonts/).
FONT_PROBES = (("sans-serif", "sans-serif"), ("serif", "serif"), ("monospace", "monospace"),
               ("system-ui", "system-ui"), ("Orbitron", "Orbitron"), ("Rajdhani", "Rajdhani"),
               ("glyph ▶", "sans-serif:charset=25b6"), ("glyph ⚙", "sans-serif:charset=2699"),
               ("glyph ✓", "sans-serif:charset=2713"), ("emoji", "sans-serif:charset=1f525"))


def machine(browser=""):
    """{browser, faces: {probe: family}} of this machine."""
    out = {"browser": browser, "faces": {}}
    for name, pattern in FONT_PROBES:
        try:
            got = subprocess.run(["fc-match", "-f", "%{family[0]}", pattern], capture_output=True, text=True,
                                 timeout=30).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            got = ""
        out["faces"][name] = got
    return out


def _error_page(code):
    from django.core.exceptions import PermissionDenied
    from django.http import Http404
    from django.views import defaults
    from django.views.csrf import csrf_failure
    req = RequestFactory().get("/signals/999999/ticket/")
    if code == "404":
        return defaults.page_not_found(req, Http404("census"))
    if code == "403":
        return defaults.permission_denied(req, PermissionDenied("census"))
    if code == "403_csrf":
        return csrf_failure(req, reason="CSRF token from POST incorrect.")
    return defaults.server_error(req)


def _messages_cookie():
    from django.contrib.messages import constants
    from django.contrib.messages.storage.base import Message
    from django.contrib.messages.storage.cookie import CookieStorage
    st = CookieStorage(RequestFactory().get("/"))
    return st.cookie_name, st._encode([Message(constants.SUCCESS, "Saved: the synthetic reservation."),
                                       Message(constants.ERROR, "Refused: a synthetic error, nothing was changed.")])


class _SceneOver(Exception):
    pass


@contextlib.contextmanager
def _scene_apart():
    """One scene's writes undone after it: the database (a transaction
    rolled back) and the in-memory cache (put back as it was). A page writes
    as it loads (the nav dots stamp it seen, which changes the dots and
    Gollum's whisper on every page after it; a preview leaves its row), and
    a scene read after another must read the same book as one read first,
    whatever shard the order of the scenes puts it in."""
    from django.core.cache import caches
    from django.core.cache.backends.locmem import LocMemCache
    from django.db import transaction
    kept = [(c, collections.OrderedDict(c._cache), dict(c._expire_info))
            for c in caches.all() if isinstance(c, LocMemCache)]
    box = {}
    try:
        with transaction.atomic():
            yield box
            raise _SceneOver
    except _SceneOver:
        pass
    finally:
        for c, data, expiry in kept:
            with c._lock:
                c._cache.clear()
                c._cache.update(data)
                c._expire_info.clear()
                c._expire_info.update(expiry)


class CensusRun:
    """One Chromium, every scene in turn, each apart from the others
    (_scene_apart). results[key] = {counts, examples, geo, status, seen,
    error}."""

    def __init__(self, clients, scenes, glyphs=True, previews=None):
        self.clients, self.scenes, self.glyphs = clients, scenes, glyphs
        self.made = previews or {}
        self.results, self.previews, self.timing = {}, {}, {}
        self.source = CENSUS_JS.read_text(encoding="utf-8")
        self.opts = census_opts()

    def answer_for(self, scene, server):
        status = {}

        def answer(request, rtype):
            url = urllib.parse.urlsplit(request["url"])
            if url.hostname == ORIGIN_HOST and url.path.startswith("/__census__/error/"):
                resp = _error_page(url.path.strip("/").rsplit("/", 1)[-1])
                status["doc"] = resp.status_code
                return resp.status_code, {"Content-Type": resp.get("Content-Type", "text/html")}, resp.content
            if url.hostname == ORIGIN_HOST and request.get("method") == "POST" and any(
                    re.search(p, url.path) for p in scene["real_post"]):
                body = (request.get("postData") or "").encode("utf-8")
                ctype = (request.get("headers") or {}).get("Content-Type", "application/x-www-form-urlencoded")
                resp = server.client.generic("POST", url.path, data=body, content_type=ctype, HTTP_HOST=HOST,
                                             HTTP_X_REQUESTED_WITH="XMLHttpRequest")
                try:
                    self.previews[url.path] = json.loads(resp.content)
                except ValueError:
                    pass
                server.seen.append("previewed POST %s %s" % (url.path, resp.status_code))
                return resp.status_code, {"Content-Type": resp.get("Content-Type", "application/json")}, resp.content
            got = server(request, rtype)
            if rtype == "Document" and got is not None and "doc" not in status:
                status["doc"] = got[0]
            return got
        return answer, status

    def run(self):
        driver = _Driver(CHROME, answer=lambda r, t: None)
        self.browser = driver.version()
        t0 = time.monotonic()
        try:
            for scene in self.scenes:
                t1 = time.monotonic()
                # The clients' cookies too: a session a scene turned over
                # would point at a row the rollback took away.
                jars = {name: copy.deepcopy(c.cookies) for name, c in self.clients.items()}
                try:
                    with _scene_apart() as box:
                        box["res"] = self.one(driver, scene)
                finally:
                    for name, jar in jars.items():
                        self.clients[name].cookies = jar
                self.results[scene["key"]] = box["res"]
                self.timing[scene["key"]] = round(time.monotonic() - t1, 2)
        finally:
            driver.close()
        self.timing["__total__"] = round(time.monotonic() - t0, 1)
        return self.results

    def step(self, driver, sid, step):
        """One step of an act: a script, a real hover, a real key."""
        if isinstance(step, tuple) and step[0] == "mouse":
            _kind, sel, text = step
            x, y = driver.js(sid, POINT % (json.dumps(sel), json.dumps(text), json.dumps((text or "").upper()),
                                           json.dumps(sel)))
            driver.mouse(sid, x, y)
        elif isinstance(step, tuple) and step[0] == "key":
            _kind, key, code, vk, text, shift = step
            driver.key(sid, key, code, vk, text, shift)
        else:
            driver.js(sid, step)

    def one(self, driver, scene):
        res = {"counts": {}, "examples": {}, "geo": {}, "regions": {}, "status": None, "seen": [], "error": None}
        if scene["path"] is None:
            res["error"] = "no %s in the book" % scene["need"]
            return res
        client = self.clients[scene["client"]]
        if scene["cookie"] == "messages":
            name, value = _messages_cookie()
            client.cookies[name] = value
        server = _Server(client)
        for pattern, (code, payload) in scene["post"].items():
            if isinstance(payload, str) and payload.startswith("@"):
                if payload[1:] not in self.made:
                    res["error"] = "no paper preview to make the %s one from" % payload[1:]
                    return res
                payload = self.made[payload[1:]]
            server.post[pattern] = (code, payload)
        answer, status = self.answer_for(scene, server)
        driver.answer = answer
        prefs = {"sauron_signals_rail": scene["rail"], "sauron_sidebar": scene["sidebar"]}
        if scene["bands"]:
            prefs.update({"sauron_hb_ticker": "1", "sauron_hb_data": "1"})
        prefs.update(scene["prefs"])
        init = INIT % {"t": int(_frozen_instant().timestamp() * 1000), "prefs": json.dumps(prefs),
                       "ws": json.dumps(scene["ws"])}
        tid, sid = driver.tab(scene["width"], scene["height"], scene["mobile"], init)
        try:
            driver.go(sid, ORIGIN + scene["path"])
            # The page read 2.6 s into its life on the held clock (INIT):
            # its first polls answered, the motion layer's safety passed.
            driver.js(sid, ADVANCE % LOAD_MS)
            res["quiet"] = driver.quiet(sid)
            driver.js(sid, SETTLE % 100)
            if scene["act"]:
                before = driver.js(sid, FINGERPRINT)
                steps = scene["act"] if isinstance(scene["act"], list) else [scene["act"]]
                try:
                    for k, st in enumerate(steps):
                        if k:
                            driver.js(sid, ADVANCE % STEP_MS)
                        self.step(driver, sid, st)
                except RuntimeError as exc:
                    res["error"] = "the state was not reached: %s" % str(exc)[:200]
                # A state read 1.6 s into its life: what it starts a second
                # later is in (the Horde's first tab), what it ends after
                # 1.8 s and more (a toast, a banner's ttl) is not yet over.
                driver.js(sid, ADVANCE % ACT_MS)
                driver.quiet(sid)
                driver.js(sid, SETTLE % 300)
                after = driver.js(sid, FINGERPRINT)
                if not res["error"] and before["h"] == after["h"]:
                    res["error"] = "the state was not reached: its act changed nothing on the page"
            if scene["shows"] or scene["shows_text"]:
                shown = driver.js(sid, SHOWN % (json.dumps(scene["shows"] or ""), json.dumps(scene["shows_text"] or "")))
                if not shown and not res["error"]:
                    new = driver.js(sid, FINGERPRINT)["keys"]
                    res["error"] = ("the state was not reached: %s is not on the screen (on it: %s)"
                                    % (scene["shows"] or repr(scene["shows_text"]), ", ".join(new[-8:])))
            if scene["mode"] == "forced":
                # Hover and press first, then focus alone: forced together,
                # an Eye border on hover read as a focus ring (the review
                # of B0: the bot panel's Toggle).
                res["forced"] = driver.force(sid, FORCED_SELECTOR, ["hover", "active"])
                driver.quiet(sid)
                driver.js(sid, SETTLE % 100)
            if scene["mode"] == "light":
                driver.js(sid, "document.body.classList.add('light-mode') || 1")
                driver.js(sid, SETTLE % 100)
            opts = dict(self.opts, phone=scene["mode"] == "phone")
            got = driver.js(sid, self.source + "\n;census(%s)" % json.dumps(opts))
            if scene["mode"] == "forced":
                driver.force(sid, FORCED_SELECTOR, ["focus-visible"])
                driver.js(sid, SETTLE % 100)
                focus = driver.js(sid, self.source + "\n;census(%s)" % json.dumps(opts))
                for marker, n in focus["counts"].items():
                    got["counts"][marker] = got["counts"].get(marker, 0) + n
                for region, rc in focus.get("regions", {}).items():
                    into = got.setdefault("regions", {}).setdefault(region, {})
                    for marker, n in rc.items():
                        into[marker] = into.get(marker, 0) + n
                for marker, rows in focus["examples"].items():
                    got["examples"].setdefault(marker, []).extend(
                        [[k, sel, "focus " + prop, value, text] for k, sel, prop, value, text in rows])
            counts = got["counts"]
            regions = got.get("regions", {})
            if self.glyphs and scene["mode"] == "rest" and got["glyphs"]:
                doc = driver.call("DOM.getDocument", {"depth": 0}, session=sid)["root"]["nodeId"]
                found = driver.call_many([("DOM.querySelector", {"nodeId": doc, "selector": '[data-svc="%d"]' % g[0]})
                                          for g in got["glyphs"]], sid)
                held = [(g, f.get("nodeId")) for g, f in zip(got["glyphs"], found) if f.get("nodeId")]
                faces = driver.call_many([("CSS.getPlatformFontsForNode", {"nodeId": nid}) for _g, nid in held], sid)
                for (g, _nid), answer in zip(held, faces):
                    # One per text holder some glyph of which no face of the
                    # four drew (the colour emoji included): which face of the
                    # machine stood in differs from one machine to another, that
                    # the four could not draw it does not.
                    index, signature, key, text, region = g
                    fonts = answer.get("fonts", [])
                    other = [f for f in fonts if not any(f["familyName"].startswith(face) for face in FACES)]
                    if other:
                        counts["glyph_face"] = counts.get("glyph_face", 0) + 1
                        rc = regions.setdefault(region, {})
                        rc["glyph_face"] = rc.get("glyph_face", 0) + 1
                        ex = got["examples"].setdefault("glyph_face", [])
                        drawn = ", ".join("%s (%d)" % (f["familyName"], f["glyphCount"]) for f in other)
                        for row in ex:
                            if row[1] == key and row[3] == drawn:
                                row[0] += 1
                                break
                        else:
                            ex.append([1, key, "drawn by", drawn, text])
            if scene["mode"] == "light":
                counts = {k: v for k, v in counts.items() if k in LIGHT_MARKERS}
                regions = {r: {k: v for k, v in c.items() if k in LIGHT_MARKERS} for r, c in regions.items()}
            res.update(counts=dict(sorted(counts.items())), examples=got["examples"], geo=got["geo"],
                       regions={r: c for r, c in sorted(regions.items()) if c},
                       n=got["n"], url=got["url"], probe=driver.js(sid, PROBE))
        except (RuntimeError, TimeoutError) as exc:
            res["error"] = str(exc)[:300]
        finally:
            driver.close_tab(tid)
        res["status"] = status.get("doc")
        res["seen"] = server.seen[:30]
        return res


def census_clients(user):
    """The test clients a run asks with: the operator, a stranger, a
    session at the PIN step, a locked session, one before the intro, and a
    reader with an empty book."""
    from dashboard.auth_views import PENDING_KEY
    main = Client()
    main.force_login(user)
    anon = Client()
    pending = Client()
    s = pending.session
    s[PENDING_KEY] = user.id
    s.save()
    locked = Client()
    locked.force_login(user)
    s = locked.session
    s["pin_locked"] = True
    s.save()
    intro = Client()
    intro.force_login(user)
    empty_user = get_user_model().objects.create_user("census_empty", password="x", is_staff=True)
    tour_done(empty_user)
    empty = Client()
    empty.force_login(empty_user)
    from portfolio.investor_models import InvestorAccess
    lp = get_user_model().objects.create_user("census_lp", password="x")
    InvestorAccess.objects.create(investor=lp, owner=user, label="Census fund")
    investor = Client()
    investor.force_login(lp)
    return {"main": main, "anon": anon, "pending": pending, "locked": locked, "intro": intro, "empty": empty,
            "investor": investor}


def resolve_details(client, user):
    """Each detail route's path, from the first link its list page prints
    (None where the book gives the list page no row)."""
    from alerts.models import Newsletter
    fallback = dict(DETAIL_FALLBACK)
    letter = Newsletter.objects.order_by("pk").first()
    if letter:      # the archive lists what was mailed to a reader; staff open any edition
        fallback["/newsletters/<int:pk>/"] = "/newsletters/%d/" % letter.pk
    out = {}
    for route, (listing, pattern) in DETAIL_LINKS.items():
        resp = client.get(listing, HTTP_HOST=HOST)
        m = re.search(pattern, resp.content.decode("utf-8")) if resp.status_code == 200 else None
        out[route] = m.group(1) if m else fallback.get(route)
    try:
        from alerts.newsletter_service import unsubscribe_path
        out["/newsletter/unsubscribe/<str:token>/"] = unsubscribe_path(user)
    except Exception:       # the letter's signer needs a setting this machine lacks: a token that does not verify
        out["/newsletter/unsubscribe/<str:token>/"] = None
    return out


def live_previews(paper, paper_id=None):
    """A TAKE TRADE preview on a live world, and a paper one short of
    capital with a position it can close first, made from the paper preview
    the view answered (never sent to a broker: the browser receives them
    from here)."""
    if not isinstance(paper, dict):
        return {}
    live = json.loads(json.dumps(paper))
    for k in ("venue", "world", "mode"):
        if k in live:
            live[k] = "live"
    for k in ("paper", "is_paper"):
        if k in live:
            live[k] = False
    for k in ("live", "is_live", "requires_pin"):
        if k in live:
            live[k] = True
    short = json.loads(json.dumps(paper))
    short["sufficient"] = False
    short["deficit"] = 500
    # base.html offers "Close first" only with a row it can close (the
    # review of B0: closable=[] left the short preview the paper one).
    short["closable"] = [{"trade_id": paper_id or 1, "symbol": "ETHUSD", "side": "SELL", "qty": "1",
                          "freed": 2600.0, "proposed": True}]
    return {"live": live, "short": short}


_RUN = {}


def measured_run():
    """The run every measured class reads (one per test process)."""
    return _RUN


#: The measured half runs in four shards (one Chromium and one book each),
#: so a parallel run spreads it over the machine's workers: scene k falls
#: to shard k mod 4, every group (pages, states, passes) across all four.
SHARDS = 4


def shard_of(scenes, i, n=SHARDS):
    return [s for k, s in enumerate(scenes) if k % n == i]

