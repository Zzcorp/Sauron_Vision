"""THE VENUE HEALTH (2026-10-05): while eToro is sick, no new real entry
leaves the box — and nothing that protects money is held.

The operator asked for more resilience in taking positions. Until today a
sick venue — a burst of 429s, 5xx answers or requests that never came back
— met the engine one call at a time: every lane read its own failure, logged
it and asked again on the next tick, and the adapter kept no memory of the
burst from one call to the next. The platform now keeps ONE memory per
(venue, world) in the Django cache, written by the adapter at the sites
where a read or a write failed for a reason that is the VENUE's (HTTP 429,
HTTP >= 500, a transport failure — never a 4xx about the order itself, and
never the orders:lookup 500s a close answers while it is being processed,
measured 2026-09-23), and read by the bot lane before a new real entry:

  SICK      SICK_BURST failures inside BURST_WINDOW_S, or ONE failed order
            POST (a write that failed for the venue's reason is enough on
            its own: the next write may be a double): the venue is sick
            for VENUE_QUIET_MINUTES past its LAST failure. Every further
            failure extends the quiet; a quiet that expires with no new
            failure ends it. A read that fails once in a quiet hour is
            noted and makes nothing sick.
  THE GATE  AssetBot.execute_entry refuses a new LIVE entry while the
            carrier is sick (skips.VENUE_SICK) — a decision with the
            venue's words, never "order_error". Closes, stop moves, the
            mirror, the scale-out and the working-entry poll are NOT held:
            what protects money goes. The TAKE TRADE ticket shows the
            warning and stays pressable (the operator keeps the last
            word).
  THE ALERT the staff are told ONCE per episode (notify_staff, no money
            figures): the failures that made it sick and the minute it
            clears by itself.

Never raises: a cache that cannot be read is a venue nobody can call sick,
and a note that cannot be written is logged and lost.
"""
import logging
from datetime import timedelta

from django.utils import timezone
from django.utils.dateparse import parse_datetime

logger = logging.getLogger(__name__)

#: The quiet a sick venue keeps past its LAST failure, in minutes.
VENUE_QUIET_MINUTES = 10
#: Read failures inside BURST_WINDOW_S that make the venue sick.
SICK_BURST = 3
BURST_WINDOW_S = 180
#: Sites whose ONE failure makes the venue sick at once (a write).
WRITE_SITES = frozenset({"order"})
#: Failures kept on the memory, newest last.
KEEP_FAILURES = 12
#: The cache key and the memory's life (the quiet is far shorter).
KEY = "venue_health:{venue}:{world}"
TTL_S = 6 * 3600
#: The venues this memory knows the words for.
VENUE_NAMES = {"etoro": "eToro"}


def _now(now=None):
    return now or timezone.now()


def _when(s):
    if not s:
        return None
    try:
        return parse_datetime(str(s))
    except (TypeError, ValueError):
        return None


def _key(venue: str, world: str) -> str:
    return KEY.format(venue=str(venue or "").lower(),
                      world=str(world or "").lower() or "live")


def _load(key: str) -> dict:
    from django.core.cache import cache
    try:
        value = cache.get(key)
    except Exception:  # noqa: BLE001 — a cache down calls nobody sick
        logger.warning("[venue health] the cache could not be read")
        return {}
    return dict(value) if isinstance(value, dict) else {}


def _store(key: str, state: dict) -> bool:
    from django.core.cache import cache
    try:
        cache.set(key, state, TTL_S)
        return True
    except Exception:  # noqa: BLE001
        logger.warning("[venue health] the cache could not be written")
        return False


def world_of(client) -> str:
    """"demo" or "live", read off the client the way the router builds it
    (EtoroTrader.demo); a client with no such flag answers "live"."""
    return "demo" if getattr(client, "demo", False) is True else "live"


def venue_name(venue: str) -> str:
    return VENUE_NAMES.get(str(venue or "").lower(), str(venue or "the venue"))


def _stamp(at) -> str:
    try:
        return at.astimezone(timezone.utc).strftime("%H:%M UTC")
    except Exception:  # noqa: BLE001
        return "?"


def note(venue: str, world: str, where: str, *, code=None, detail: str = "",
         now=None) -> dict:
    """Record ONE failure of `venue`'s `world` at `where` (ticker, account,
    portfolio, search, eligibility, order) for a reason that is the venue's.
    Returns the memory after the note: {"sick": bool, "since", "until",
    "failures": [...]}. Never raises."""
    try:
        now = _now(now)
        key = _key(venue, world)
        state = _load(key)
        failures = [f for f in (state.get("failures") or [])
                    if isinstance(f, dict)]
        failures.append({"at": now.isoformat(), "where": str(where or "?"),
                         "code": (int(code) if code not in (None, "", 0)
                                  else None),
                         "detail": str(detail or "")[:120]})
        failures = failures[-KEEP_FAILURES:]
        state["failures"] = failures
        window = now - timedelta(seconds=BURST_WINDOW_S)
        recent = [f for f in failures
                  if (_when(f.get("at")) or window) >= window]
        write = str(where or "") in WRITE_SITES
        was_until = _when(state.get("sick_until"))
        still = bool(was_until and was_until > now)
        became = False
        # a write's failure, a burst of reads, or ANY failure while the
        # venue is already sick: the quiet runs VENUE_QUIET_MINUTES past
        # this failure
        if write or still or len(recent) >= SICK_BURST:
            until = now + timedelta(minutes=VENUE_QUIET_MINUTES)
            if not still:
                state["sick_since"] = now.isoformat()
                became = True
            state["sick_until"] = until.isoformat()
        if not _store(key, state):
            # a memory nobody can write is a memory nobody reads: the
            # failure is logged (above) and lost, and nobody is called sick
            return {"sick": False, "failures": []}
        if became:
            _tell_staff(venue, world, state, now=now)
        return _view(state, now)
    except Exception as e:  # noqa: BLE001 — a lost note must not raise
        logger.warning("[venue health] could not note %s/%s at %s: %s",
                       venue, world, where, e)
        return {"sick": False}


def _view(state: dict, now) -> dict:
    until = _when(state.get("sick_until"))
    sick = bool(until and until > now)
    return {"sick": sick,
            "since": state.get("sick_since") if sick else None,
            "until": state.get("sick_until") if sick else None,
            "failures": list(state.get("failures") or [])}


def sick(venue: str, world: str, now=None):
    """The memory while `venue`'s `world` is sick — {"since", "until",
    "failures", "words"} — or None. Never raises."""
    try:
        now = _now(now)
        state = _load(_key(venue, world))
        view = _view(state, now)
        if not view["sick"]:
            return None
        view["words"] = words(venue, world, view, now=now)
        return view
    except Exception:  # noqa: BLE001
        return None


def words(venue: str, world: str, view: dict, now=None) -> str:
    """One sentence for a skip, a ticket or an alert. No money figures."""
    now = _now(now)
    name = venue_name(venue)
    failures = [f for f in (view.get("failures") or []) if isinstance(f, dict)]
    window = now - timedelta(seconds=BURST_WINDOW_S)
    recent = [f for f in failures if (_when(f.get("at")) or window) >= window]
    last = failures[-1] if failures else {}
    last_words = ""
    if last:
        code = last.get("code")
        last_words = (f"{last.get('where') or '?'} "
                      + (f"HTTP {code}" if code else
                         (str(last.get("detail") or "")[:40] or "failed"))
                      + f" at {_stamp(_when(last.get('at')) or now)}")
    until = _when(view.get("until"))
    return (f"{name} ({world}) is sick: {len(recent)} failure"
            f"{'s' if len(recent) != 1 else ''} in the last "
            f"{BURST_WINDOW_S // 60} min"
            + (f" (last: {last_words})" if last_words else "")
            + (f" — new real entries held until {_stamp(until)}"
               if until else "")
            + "; closes and stop moves still go")


def refusal(client, symbol: str = "", now=None) -> tuple:
    """(skips.VENUE_SICK, words) while the client's venue and world are
    sick, else ("", ""). Keyed on the ADAPTER (capabilities.adapter_key:
    the class name), so a MagicMock or a PaperTrader is never refused."""
    try:
        from bot_program.asset_engine import skips
        from bot_program.engine.capabilities import adapter_key
        venue = adapter_key(client)
        if not venue:
            return "", ""
        view = sick(venue, world_of(client), now=now)
        if not view:
            return "", ""
        return skips.VENUE_SICK, (
            (f"{symbol}: " if symbol else "") + view["words"]
            + " — nothing sent")
    except Exception:  # noqa: BLE001
        return "", ""


def advisory(venue: str, world: str, now=None) -> dict:
    """{"ok": bool, "reason": str} for the TAKE TRADE preview — a warning,
    never a refusal: the operator keeps the last word on their own lane."""
    try:
        view = sick(venue, world, now=now)
    except Exception:  # noqa: BLE001
        view = None
    if not view:
        return {"ok": True, "reason": ""}
    return {"ok": False, "reason": view["words"]}


def clear(venue: str, world: str) -> None:
    from django.core.cache import cache
    try:
        cache.delete(_key(venue, world))
    except Exception:  # noqa: BLE001
        logger.warning("[venue health] the cache could not be cleared")


def reset() -> None:
    """Forget every venue's memory (tests)."""
    for venue in VENUE_NAMES:
        for world in ("demo", "live"):
            clear(venue, world)


def _tell_staff(venue: str, world: str, state: dict, now=None) -> None:
    """Once per episode. No money figures."""
    try:
        from bot_program.notifications import notify_staff
        view = _view(state, _now(now))
        name = venue_name(venue)
        recent = [f for f in view["failures"] if isinstance(f, dict)][-SICK_BURST:]
        listed = ", ".join(
            f"{f.get('where') or '?'} "
            + (f"HTTP {f.get('code')}" if f.get("code")
               else (str(f.get("detail") or "")[:40] or "failed"))
            for f in recent) or "a failed call"
        notify_staff(
            title=f"⚠ {name} ({world}) is sick — new real entries held",
            body=(f"{words(venue, world, view, now=now)}. What made it sick: "
                  f"{listed}. The bots send no new real entry on this venue "
                  f"until the quiet ends ({VENUE_QUIET_MINUTES} min past "
                  f"the last failure); closes, stop moves and the TAKE "
                  f"TRADE lane are not held. An order that did not come "
                  f"back is noted IN DOUBT on its symbol — check the broker "
                  f"for it before arming the symbol again."),
            url="/brokers/")
    except Exception as e:  # noqa: BLE001
        logger.warning("[venue health] the staff alert failed: %s", e)
