"""The signal rail: every signal that can be acted on now, and why each one
left it (2026-11-06).

The operator, 2026-11-06: the rail was capped (the five newest active
signals), so when many arrived at once he could not act on some of them;
and he asked for "a real system where the signal leaves if it is no longer
voted, or seen as effective and profitable, or simply past".

THE RAIL lists every candidate the lifecycle below has not retired, newest
first: an ACTIVE signal created in the last 48 hours, or flagged again by
the opportunity scanner in the last 48 hours (a composite signal is reused
and re-flagged daily). 48 is the 24 hours a signal can stay on the rail
plus the 24 hours LEFT THE RAIL keeps. The only bound is a stated safety
ceiling against a runaway writer, and the rail says so in words when it
binds.

THE LIFECYCLE, first match wins:

   1  yours            your own PASS or take              (stored, by the pass view)
   2  recorded         a departure already written        (sticky: never slides back)
   3  superseded       a newer signal from its own rule on its instrument
   4  aged             24h past when it fired, or past when the scanner last
                       matched a reused composite
   5  stop_crossed     a fresh mark at or through the stop
   6  target_reached   a fresh mark at or through the target
   7  chased           reward:risk from the mark under the ticket's 1.00,
                       when the plan cleared it at its entry
   8  rule_paused      its rule is paused
   9  rule_demoted     its rule was demoted after it fired
  10  rule_losing      its rule is a measured loser on the promotion floor
  11  rule_losing_live its rule lost real money on this class: at least ten
                       real-money closes in 180 days, expectancy at or under 0R

Every departure but age is written once, with its reason in words, to
dashboard.RailDeparture the first time the rail sees it — words that say
their moment ("At 14:32 UTC the price ... was through its stop"), because
they are read for a day; a fact that can change after them (the rule's
pause, the operator's own position) is said as it is NOW, beside them. Age
is a clock and is re-read on each render. The engine's own closes (target,
stop, 7-day expiry) are read from the Signal row as they are. The
lifecycle is the rail's, not one operator's: a signal you passed is still
judged, so an undo brings back only what the rail would show.

THE VOTE (2026-11-06, the review). decide() counts a signal for
max_signal_age_hours (24 by default) from when it FIRED, and so does the
hand ticket's backing; the opportunity scanner reuses a composite row and
only re-flags it. A re-match keeps the card on the rail — the setup holds
— but never brings its vote back: `votes` and `live` end 24h after the
signal fired, and the words speak for "a default bot" (a persona's own age
limit can be 4 hours or 72).

LEFT THE RAIL draws every departure the engine still holds, each with its
ticket, so a burst of departures never takes the operator's last way to
act on one; only the engine's own closes, which no ticket can take, are
drawn up to GONE_ROWS and counted past it. A pass of yours on a setup the
scanner has matched again since is listed too, as of the re-match, so it
can always be brought back.

THE RULE FACTS (the stage badge, the graded and the real-money records)
are cached RULE_FACTS_TTL seconds and stamped with the moment they were
read. A departure is permanent, so a fact never judges a signal that
reached the rail after it was read: such a rule is read again now (a pause
lifted, a record recovered).

NOTHING HERE IS A SECOND IMPLEMENTATION. The 24 hours are
manual_trade.SIGNAL_BACKING_HOURS (and decide()'s default
max_signal_age_hours); the quote bound is signals.performance's
MAX_QUOTE_AGE_SECONDS; the reward:risk is manual_trade.reward_risk_advisory
against REWARD_RISK_WARN, the ticket's own; "votes" is decide()'s may_vote,
read through dashboard.signal_surface.stage_badge, which calls the two
functions the entry path calls; the loser is promotion_pipeline's
measured_loser on the floor's own grouped record; the real-money record is
bot_grading's own summary, world="live".

THE MARKET'S STATE (2026-11-12). The operator asked to keep receiving
every signal the moment it fires, also when its market is shut, so a
signal whose market is shut stays a card, and says so: MARKET SHUT and the
hour the market opens, on the card, in its popup and on the headband row
(signals.market_hold.market_state, the bots' own clock, read once per
instrument and never from the database). One chip, SHUT, shows or hides
those cards (shown by default, the `shut_off` choice of the operator's
prefs) and counts them. An open market's card carries nothing new.

THE OPTIONAL HOLD (the switch signal_market_hold, OFF on arrival; with it
off none of this runs). For an operator who would rather see what can be
traded now, the lifecycle stays as it is and a candidate it would show as
a card waits under MARKET SHUT instead while its market cannot trade
(shut, or in its first quarter hour): off the cards, the rail's count and
the headband list, with the hour the market opens, whether its 24 hours
end before that, and its ticket (a paper ticket is refused until the
market has opened and settled, or outside the cash session for an index;
a live one warns and is the operator's to send). It is a
card again by itself once the market has opened and settled. While a
market cannot trade, the price rules (5 to 7) judge nothing: a quote
re-stamped before the open used to record a sticky STOP departure. The
title counts the waiting signals, and the counts still add up: on the
rail + waiting + left and still active + left earlier + not evaluated =
active in the engine.

DISPLAY ONLY. It never writes Signal (any field), RuleControl,
PromotionEvent, AssetBotConfig, AssetBotTrade, Instrument, alerts or
notification preferences, and it never pushes or announces. A retired
signal stays active in the engine, votes exactly as before, and keeps its
TAKE TRADE ticket in LEFT THE RAIL while the engine holds it.
"""
from __future__ import annotations

import hashlib
import logging
import math
import sys
from dataclasses import dataclass, field
from datetime import timedelta, timezone as dt_timezone
from typing import Optional

from django.db.models import Max, Q
from django.utils import timezone

from bot_program.manual_trade import (
    EXECUTABLE_CLASS, REWARD_RISK_WARN, SIGNAL_BACKING_HOURS,
    reward_risk_advisory)
from core.constants import AssetClass

logger = logging.getLogger(__name__)

#: How long a signal stays on the rail without being affirmed again: the
#: hours in which a hand ticket counts it as backing, and decide()'s default
#: max_signal_age_hours (asset_engine/base.py).
RAIL_FRESH_HOURS = SIGNAL_BACKING_HOURS
#: The candidates: the hours a signal can stay on, plus the hours LEFT THE
#: RAIL keeps.
RAIL_WINDOW_HOURS = 2 * RAIL_FRESH_HOURS
#: A guard against a runaway writer (a replay, a bulk insert), never a
#: display limit: the rail says so in words when it binds.
RAIL_SAFETY_CEILING = 500
#: The engine's own closes drawn in full in LEFT THE RAIL; every departure
#: the engine still holds is drawn whatever their number (the candidates'
#: ceiling bounds them), and the counts cover all of them.
GONE_ROWS = 60
#: Engine closes of the last 24h read for LEFT THE RAIL; past it, a count
#: says how many more there were, in words.
GONE_CLOSED_FETCH = 400
#: Per-rule facts (stage badge, graded and real-money records).
RULE_FACTS_TTL = 300
#: bot_grading.bot_track_record_detail's own floor for a live record.
LIVE_RECORD_DAYS, LIVE_RECORD_MIN_N = 180, 10

#: The class order, chips and group headers alike: the vocabulary's own.
CLASS_ORDER = [key for key, _label in AssetClass.CHOICES]
CLASS_SHORT = {"stock": "STOCK", "forex": "FX", "commodity": "CMDTY",
               "index": "INDEX", "etf": "ETF", "crypto": "CRYPTO",
               "bond": "BOND", "options": "OPTIONS", "cfd": "CFD"}

#: The tag chip of each departure in LEFT THE RAIL.
TAGS = {
    "superseded": "REPLACED", "aged": "AGED", "stop_crossed": "STOP",
    "target_reached": "TARGET", "chased": "CHASED",
    "rule_paused": "PAUSED", "rule_demoted": "DEMOTED",
    "rule_losing": "LOSING", "rule_losing_live": "LOSING LIVE",
    "passed": "PASSED", "taken": "TAKEN",
    # the MARKET SHUT section's rows (the optional hold)
    "market_shut": "SHUT", "market_settling": "SETTLING",
    "closed_target": "TARGET", "closed_stop": "STOP",
    "closed_expired": "CLOSED", "closed_manual": "CLOSED", "closed": "CLOSED",
}
#: The engine's own closes, in words (dashboard/views_links.py says the
#: same of a signal no longer active).
CLOSE_REASON = {"hit_target": "closed_target", "stopped_out": "closed_stop",
                "expired": "closed_expired", "manual_close": "closed_manual"}
CLOSE_WORDS = {"hit_target": "target reached", "stopped_out": "stopped out",
               "expired": "expired after 7 days without its target or stop",
               "manual_close": "closed by hand in the engine"}

_DEMOTE_WORDS = {"auto_demote": "auto demotion",
                 "manual_demote": "manual demotion", "rollback": "rollback"}
#: The ladder's stages in the operator's words (signals/rule_actuator
#: stage_policy says the same of each).
STAGE_WORDS = {"research": "watched, no orders", "paper": "the paper venue",
               "live_small": "live at quarter size",
               "live_full": "live at full size"}
LIVE_STAGES = ("live_small", "live_full")


@dataclass
class RailFacts:
    """What a row says about itself, as the filters read it (data-*)."""
    asset_class: str = ""
    side: str = "flat"
    score_band: int = 0
    stage: str = ""
    stage_label: str = ""
    stage_tone: str = ""
    stage_reason: str = ""
    #: The rule may vote (decide()'s may_vote: a voting stage, not paused).
    may_vote: bool = False
    #: A default bot counts its vote now: may_vote, and fired in the last
    #: 24 hours (decide() and the hand ticket count from created_at).
    votes: bool = False
    live: bool = False
    vote_until: object = None
    vote_words: str = ""
    leaves_words: str = ""
    held: bool = False
    held_venue: str = ""
    rule_key: str = ""
    mark: Optional[float] = None
    mark_fresh: bool = False
    progress_r: Optional[float] = None
    rr_now: Optional[float] = None
    affirmed_at: object = None
    leaves_at: object = None
    contra: Optional[dict] = None
    record_words: str = ""
    live_words: str = ""
    #: "shut" while the instrument's market is shut now, "settling" in the
    #: quarter hour after an open, "" while it can trade (2026-11-12,
    #: signals.market_hold.market_state). The MARKET SHUT badge is drawn
    #: for "shut" alone: a settling market is open.
    market: str = ""
    #: One sentence for a market that cannot trade now, else "".
    market_words: str = ""
    #: "opens Sun 22:00 UTC" beside the badge; "" when the clock does not
    #: know the hour, and while the market is open.
    opens: str = ""
    opens_at: object = None
    #: Its hours on the rail end before its market opens: it will have
    #: left the rail before anything can trade it.
    misses_open: bool = False
    o_score: int = 0
    o_cls: int = 0
    o_cscore: int = 0


@dataclass
class Gone:
    """One LEFT THE RAIL row."""
    signal_id: int
    symbol: str
    asset_class: str
    side: str
    direction: str
    rule: str
    rule_key: str
    reason: str
    tag: str
    words: str
    at: object
    score: float = 0.0
    created_at: object = None
    closed_words: str = ""
    engine_active: bool = False
    takeable: bool = False
    yours: bool = False
    position_words: str = ""
    facts: RailFacts = field(default_factory=RailFacts)


# ── small helpers ─────────────────────────────────────────────────────────

def _testing() -> bool:
    """The test runner rolls primary keys back between tests, so a cache
    keyed on a rule name would serve one test's facts to the next (the
    reason core.context_processors._panel_detail bypasses its cache)."""
    return "test" in sys.argv or any("pytest" in a for a in sys.argv)


def rule_key(name) -> str:
    """A CSS-safe key for a rule name: "r" + 10 hex of its sha1, so no
    selector ever needs escaping; the empty name is "r-none"."""
    if not name:
        return "r-none"
    return "r" + hashlib.sha1(str(name).encode("utf-8")).hexdigest()[:10]


def _f(value):
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _hhmm(dt) -> str:
    return dt.astimezone(dt_timezone.utc).strftime("%H:%M UTC") if dt else "—"


def _when(dt, now=None) -> str:
    """'14:32 UTC' on the day of `now`, 'Nov 05 14:32 UTC' on another."""
    if not dt:
        return "—"
    now = now or timezone.now()
    d = dt.astimezone(dt_timezone.utc)
    if d.date() == now.astimezone(dt_timezone.utc).date():
        return d.strftime("%H:%M UTC")
    return d.strftime("%b %d %H:%M UTC")


def _on_day(dt) -> str:
    """'on Nov 05 at 14:32 UTC' — for words written once and read later."""
    if not dt:
        return "at an unknown time"
    d = dt.astimezone(dt_timezone.utc)
    return d.strftime("on %b %d at %H:%M UTC")


def _px(value, inst) -> str:
    from core.price_format import format_price
    return format_price(value, getattr(inst, "asset_class", ""),
                        getattr(inst, "symbol", ""))


def _age(seconds) -> str:
    """'25h', '24h 30m', '45m' — whole minutes, so a signal half an hour
    past the 24 hours never reads as on them; the first minute past reads
    'just over 24h'."""
    mins = max(0, int(seconds // 60))
    h, m = divmod(mins, 60)
    if h == RAIL_FRESH_HOURS and m == 0:
        return f"just over {h}h"
    if h == 0:
        return f"{m}m"
    return f"{h}h" + (f" {m}m" if m else "")


def _shown_under(value, line) -> float:
    """`value` at two decimals, never rounded up onto a line it is under
    (promotion_pipeline.loser_numbers does the same for the floor): 0.997
    under the ticket's 1.00 reads 0.99, not 1.00."""
    shown = round(float(value), 2)
    if float(value) < line <= shown:
        shown = round(line - 0.01, 2)
    return shown


def _side_of(direction) -> str:
    return {"bullish": "long", "bearish": "short"}.get(direction or "", "flat")


def _order_side(side) -> Optional[str]:
    return {"long": "BUY", "short": "SELL"}.get(side)


def _quote_of(inst):
    try:
        return inst.live_quote
    except Exception:  # noqa: BLE001 — no quote row is no mark
        return None


def _fresh_mark(inst, now):
    """(mark, fresh): the quote's last when it is within the engine's own
    freshness bound — a frozen feed judges nothing."""
    from signals.performance import MAX_QUOTE_AGE_SECONDS
    q = _quote_of(inst)
    last = _f(getattr(q, "last", None)) if q is not None else None
    if not last or last <= 0:
        return None, False
    at = getattr(q, "updated_at", None)
    fresh = bool(at and (now - at).total_seconds() <= MAX_QUOTE_AGE_SECONDS)
    return last, fresh


def _levels(s):
    """entry, stop, target as floats — entry is the suggested entry or the
    price at the signal, the convention signals.performance grades with."""
    entry = s.suggested_entry if s.suggested_entry is not None else s.price_at_signal
    return _f(entry), _f(s.suggested_stop), _f(s.suggested_target)


def _score_band(score) -> int:
    try:
        return max(0, min(10, int(math.floor(float(score or 0) * 10 + 1e-9))))
    except (TypeError, ValueError):
        return 0


def _pool_class(asset_class) -> str:
    """The pool a hand ticket on this class rides: an index and an ETF ride
    the stock pool (manual_trade.EXECUTABLE_CLASS)."""
    return EXECUTABLE_CLASS.get(asset_class or "", asset_class or "")


def held_symbols(request) -> dict:
    """{SYMBOL: "LIVE"|"DEMO"|"PAPER"|"BOOK"} the operator holds open now,
    memoised on the request: the AssetBotTrade book (by money world,
    dashboard.position_summary.world_of) and the legacy Position book."""
    cached = getattr(request, "_sv_held", None)
    if cached is not None:
        return cached
    out = {}
    user = getattr(request, "user", None)
    if user is not None and getattr(user, "is_authenticated", False):
        try:
            from bot_program.models import AssetBotTrade
            from dashboard.position_summary import world_of
            for t in (AssetBotTrade.objects
                      .filter(config__user=user,
                              status__in=("OPEN", "CLOSE_PENDING"))
                      .only("symbol", "paper", "metadata")):
                out.setdefault((t.symbol or "").upper(),
                               (world_of(t) or "live").upper())
        except Exception as e:  # noqa: BLE001 — held is a filter fact
            logger.debug("[rail] held trades unread: %s", e)
        try:
            from portfolio.models import Position
            # The legacy book is the user's own "<username>_main" portfolio
            # (portfolio.services.get_or_create_default_portfolio).
            for sym in (Position.objects
                        .filter(portfolio__name=f"{user.username}_main",
                                closed_at__isnull=True)
                        .values_list("instrument__symbol", flat=True)):
                out.setdefault((sym or "").upper(), "BOOK")
        except Exception as e:  # noqa: BLE001
            logger.debug("[rail] held positions unread: %s", e)
    try:
        request._sv_held = out
    except Exception:  # noqa: BLE001
        pass
    return out


# ── the per-rule facts ────────────────────────────────────────────────────

def graded_records(rule_names) -> dict:
    """{rule: the floor's all-time graded record} in one grouped query —
    promotion_pipeline._stats_by_rule, the same filter, rounding and event
    counting `measured_loser` reads (tests/test_rail_lifecycle.py pins that
    the verdicts are the floor's own, rule by rule)."""
    from signals.promotion_pipeline import _stats_by_rule
    return _stats_by_rule([r for r in rule_names if r])


def _live_rows() -> dict:
    """{(rule, class): row} of real-money closes over LIVE_RECORD_DAYS —
    bot_grading's own summary, world="live" (no demo, no paper)."""
    from bot_program.bot_grading import VENUE_LIVE, bot_performance_summary
    rows = bot_performance_summary(venue=VENUE_LIVE, world="live",
                                   days=LIVE_RECORD_DAYS)
    return {(r["rule_name"], r["asset_class"]): r for r in rows}


def _rule_facts(rules, arrived=None) -> dict:
    """{rule: {"name", "at", "badge", "stats", "loser", "live"}} — per
    distinct rule, cached RULE_FACTS_TTL seconds outside the test runner,
    read from the cache in one call.

    A fact speaks for the moment it was read (`at`), and a departure is
    permanent: `arrived` maps a rule to the latest moment one of its
    candidates reached the rail (fired, or matched again by the scanner),
    and a cached fact read before that moment is read again now — so a
    pause lifted or a record recovered never retires a signal that arrived
    after it (2026-11-06, the review)."""
    from django.core.cache import cache
    from dashboard.signal_surface import badges_for
    from signals.promotion_pipeline import measured_loser

    testing = _testing()
    arrived = arrived or {}
    keys = {r: f"sv:rail:rule:{rule_key(r)}" for r in rules}
    hits = {}
    if not testing and keys:
        try:
            hits = cache.get_many(list(keys.values())) or {}
        except Exception as e:  # noqa: BLE001 — an unread cache is a miss
            logger.debug("[rail] rule facts cache unread: %s", e)
    out, missing = {}, []
    for r in rules:
        hit = hits.get(keys[r])
        came = arrived.get(r)
        if (isinstance(hit, dict) and hit.get("name") == r
                and hit.get("at") is not None
                and (came is None or came < hit["at"])):
            out[r] = hit
        else:
            missing.append(r)
    if not missing:
        return out
    # Stamped BEFORE the reads: every fact below is at least this fresh.
    read_at = timezone.now()
    badges = badges_for(missing)
    try:
        stats = graded_records(missing)
    except Exception as e:  # noqa: BLE001 — an unread record judges nothing
        logger.warning("[rail] graded records unread: %s", e)
        stats = {}
    try:
        live = _live_rows()
    except Exception as e:  # noqa: BLE001
        logger.warning("[rail] real-money records unread: %s", e)
        live = {}
    fresh = {}
    for r in missing:
        st = stats.get(r) or {"n": 0, "expectancy": None, "hit_rate": None}
        try:
            loser = measured_loser(r, stats=st) if r else ""
        except Exception:  # noqa: BLE001
            loser = ""
        fact = {"name": r, "at": read_at, "badge": badges.get(r) or {},
                "stats": st, "loser": loser,
                "live": {cls: row for (rn, cls), row in live.items() if rn == r}}
        out[r] = fact
        fresh[keys[r]] = fact
    if not testing and fresh:
        try:
            cache.set_many(fresh, RULE_FACTS_TTL)
        except Exception as e:  # noqa: BLE001 — the render stands
            logger.debug("[rail] rule facts not cached: %s", e)
    return out


def _record_words(rule, st) -> str:
    from signals.promotion_pipeline import LOSER_MIN_N, count_words, needs_words
    n = int((st or {}).get("n") or 0)
    if not rule:
        return "no rule named on this signal: no graded record"
    if n < LOSER_MIN_N:
        return (f"{count_words(rule, st)}: not judged, the floor is "
                f"{needs_words(rule)}")
    hit, exp = st.get("hit_rate"), st.get("expectancy")
    return (f"{count_words(rule, st)}, "
            f"{float(hit or 0) * 100:.0f}% hit, {float(exp or 0):+.2f}R")


def _live_words(rule, cls, row) -> str:
    if not rule:
        return ""
    if not row:
        return f"no real-money close on {cls or 'this class'} in {LIVE_RECORD_DAYS} days"
    n = int(row.get("n") or 0)
    if n < LIVE_RECORD_MIN_N:
        return (f"{n} real-money close{'' if n == 1 else 's'} on {cls} in "
                f"{LIVE_RECORD_DAYS} days: not judged, the floor is "
                f"{LIVE_RECORD_MIN_N}")
    return (f"{n} real-money closes on {cls} in {LIVE_RECORD_DAYS} days, "
            f"expectancy {float(row.get('expectancy') or 0):+.2f}R")


# ── the verdict ───────────────────────────────────────────────────────────

def _affirmed(s, last_flag):
    flag = last_flag.get(s.pk)
    return max(s.created_at, flag) if flag else s.created_at


def _aged_words(s, aff, now, last_flag) -> str:
    """Why an active signal aged off the rail, as of `now` (never stored:
    a clock). A default bot's age limit (decide()'s max_signal_age_hours) is
    24 hours; a persona's own can differ, so the words never say "the
    bots". A reused composite is let go 24h after the scanner last matched
    it — its vote ended 24h after it fired, which says nothing more here."""
    age = (now - aff).total_seconds()
    if last_flag.get(s.pk) and aff > s.created_at:
        return (f"The scanner last matched this setup {_age(age)} ago: the "
                f"rail keeps a signal {RAIL_FRESH_HOURS}h after the scanner "
                f"last saw it.")
    return (f"{_age(age)} old: past the {RAIL_FRESH_HOURS}h in which a "
            f"default bot counts its vote and an instrument-view ticket "
            f"counts it as backing.")


def _aged_at_words(s, aff, aged_at, last_flag) -> str:
    """The same, for a signal the engine closed after it aged: said at the
    moment it aged, never as an age."""
    if last_flag.get(s.pk) and aff > s.created_at:
        return (f"The scanner last matched this setup at {_hhmm(aff)}; the "
                f"rail let it go {RAIL_FRESH_HOURS}h later, at "
                f"{_hhmm(aged_at)}.")
    return (f"It passed {RAIL_FRESH_HOURS}h old at {_hhmm(aged_at)}: a "
            f"default bot no longer counted its vote, nor an instrument-view "
            f"ticket as backing.")


def _price_verdict(s, mark, side, now):
    """(reason, words) when a fresh mark says the plan is past, else None.
    The words are written once and read for a day, so they say their
    moment: the price may come back, and the row's ticket is priced then."""
    entry, stop, target = _levels(s)
    inst = s.instrument
    order = _order_side(side)
    if order is None or mark is None:
        return None
    at = _hhmm(now)
    if stop is not None and ((order == "BUY" and mark <= stop)
                             or (order == "SELL" and mark >= stop)):
        return ("stop_crossed",
                f"At {at} the price, {_px(mark, inst)}, was at or through its "
                f"stop, {_px(stop, inst)}: a ticket at that price is refused "
                f"(levels on the wrong side of the price).")
    if target is not None and ((order == "BUY" and mark >= target)
                               or (order == "SELL" and mark <= target)):
        return ("target_reached",
                f"At {at} the price, {_px(mark, inst)}, reached its target, "
                f"{_px(target, inst)}.")
    if None in (entry, stop, target):
        return None
    now_rr = reward_risk_advisory(order, mark, stop, target).get("ratio")
    born_rr = reward_risk_advisory(order, entry, stop, target).get("ratio")
    if (now_rr is not None and born_rr is not None
            and now_rr < REWARD_RISK_WARN <= born_rr):
        span = (target - entry) if order == "BUY" else (entry - target)
        ran = ((mark - entry) if order == "BUY" else (entry - mark))
        pct = (ran / span * 100) if span else 0.0
        risk = abs(mark - stop)
        reward = abs(target - mark)
        return ("chased",
                f"At {at} the price had run {pct:.0f}% of the way to its "
                f"target: from {_px(mark, inst)} it risked {_px(risk, inst)} "
                f"to make {_px(reward, inst)}, reward:risk "
                f"{_shown_under(now_rr, REWARD_RISK_WARN):.2f}, under the "
                f"ticket's {REWARD_RISK_WARN:.2f} line (it was {born_rr:.2f} "
                f"at the entry).")
    return None


def _demotion_after(s, demotions):
    for ev in demotions.get(s.rule_name or "", ()):
        if ev.created_at >= s.created_at:
            return ev
    return None


def _is_demotion(ev) -> bool:
    from signals.promotion_pipeline import STAGE_ORDER
    try:
        return STAGE_ORDER.index(ev.to_stage) < STAGE_ORDER.index(ev.from_stage)
    except ValueError:
        return False


@dataclass
class Verdict:
    """The rail's own verdict on a candidate: why it left, when, and
    whether the departure is written (every one but age)."""
    reason: str
    words: str
    at: object
    mark: Optional[float] = None
    store: bool = False


def _paused_words(s, rule, now) -> str:
    """What a pause does, and only that. The bots drop a paused rule's
    vote (decide()'s may_vote) and refuse its entries (the entry path's
    pause check); the RULE ENGINE writes no new signal for it — but the
    opportunity scanner never reads the pause, and keeps writing and
    re-matching a paused setup's composite signals."""
    stops = "the bots no longer count its vote or open an entry on it"
    if (s.signal_type or "") != "composite":
        stops = "the rule engine writes no new signal for it, and " + stops
    return f"At {_hhmm(now)} its rule ({rule}) was paused: {stops}."


def _stage_words(stage) -> str:
    return STAGE_WORDS.get(stage or "", stage or "an unknown stage")


def _lifecycle(s, ctx):
    """The rail's verdict on `s` (rules 2-11), the operator's own choice
    left out — a pass is one operator's, the lifecycle is the rail's. None:
    it stays."""
    rec = ctx["life"].get(s.pk)
    if rec is not None:
        return Verdict(rec.reason, rec.words, rec.departed_at, _f(rec.mark))
    now = ctx["now"]
    side = _side_of(s.direction)
    if s.rule_name:
        newer = ctx["newest"].get((s.instrument_id, s.rule_name))
        if newer is not None and newer.pk != s.pk and (
                (newer.created_at, newer.pk) > (s.created_at, s.pk)):
            new_side = _side_of(newer.direction)
            verb = ("Replaced" if new_side == side or new_side == "flat"
                    or side == "flat" else "Reversed")
            word = {"long": "LONG", "short": "SHORT"}.get(new_side, "signal")
            return Verdict("superseded",
                           f"{verb} by a newer {word} from the same rule "
                           f"({s.rule_name}) at {_hhmm(newer.created_at)}.",
                           newer.created_at, None, True)
    aff = _affirmed(s, ctx["last_flag"])
    if (now - aff) > timedelta(hours=RAIL_FRESH_HOURS):
        return Verdict("aged", _aged_words(s, aff, now, ctx["last_flag"]),
                       aff + timedelta(hours=RAIL_FRESH_HOURS))
    mark, fresh = _fresh_mark(s.instrument, now)
    # THE OPTIONAL HOLD: while a market is shut or settling a quote is not
    # a market price (a stream re-stamps the last one), so it judges
    # nothing and records no departure. Off, the rules read every fresh
    # quote, as they always did.
    if fresh and ctx.get("hold") and not _market(s.instrument, ctx,
                                                 now)["tradeable"]:
        fresh = False
    if fresh:
        hit = _price_verdict(s, mark, side, now)
        if hit is not None:
            return Verdict(hit[0], hit[1], now, mark, True)
    rf = ctx["rules"].get(s.rule_name or "") or {}
    badge = rf.get("badge") or {}
    rule = s.rule_name or ""
    if badge.get("label") == "PAUSED":
        return Verdict("rule_paused", _paused_words(s, rule, now), now,
                       None, True)
    ev = _demotion_after(s, ctx["demotions"])
    if ev is not None:
        return Verdict("rule_demoted",
                       f"Its rule ({rule}) was demoted from {ev.from_stage} "
                       f"to {ev.to_stage} ({_stage_words(ev.from_stage)} to "
                       f"{_stage_words(ev.to_stage)}) {_on_day(ev.created_at)} "
                       f"({_DEMOTE_WORDS.get(ev.reason, ev.reason)}).",
                       ev.created_at, None, True)
    if rf.get("loser"):
        return Verdict("rule_losing",
                       f"At {_hhmm(now)} its rule's graded record was a "
                       f"measured loser: " + rf["loser"], now, None, True)
    cls = _pool_class(s.instrument.asset_class)
    row = (rf.get("live") or {}).get(cls)
    if (rule and row and int(row.get("n") or 0) >= LIVE_RECORD_MIN_N
            and float(row.get("expectancy") or 0) <= 0):
        exp = float(row.get("expectancy") or 0)
        # At or under 0R is not profitable; only under it lost money.
        verb = ("had lost real money" if exp < 0
                else "had made nothing with real money")
        return Verdict("rule_losing_live",
                       f"At {_hhmm(now)} {rule} {verb} on {cls}: "
                       f"{int(row['n'])} closed real-money trades in "
                       f"{LIVE_RECORD_DAYS} days, expectancy {exp:+.2f}R.",
                       now, None, True)
    return None


def _close_words(s) -> str:
    what = CLOSE_WORDS.get(s.outcome or "")
    r = s.realized_r
    tail = f" ({r:+.2f}R)" if r is not None and s.outcome in (
        "hit_target", "stopped_out", "manual_close") else ""
    return f"{what}{tail}" if what else "closed"


def _vote_words(s, may_vote, votes, vote_until, aff, now) -> str:
    if not may_vote:
        return "no bot counts its vote"
    if votes:
        return f"a default bot counts its vote until {_when(vote_until, now)}"
    stopped = (f"a default bot stopped counting its vote at "
               f"{_when(vote_until, now)}, {RAIL_FRESH_HOURS}h after it fired")
    if aff > s.created_at:
        return (f"{stopped}; the scanner matched it again "
                f"{_age((now - aff).total_seconds())} ago")
    return stopped


def _facts(s, ctx, now) -> RailFacts:
    inst = s.instrument
    rf = ctx["rules"].get(s.rule_name or "") or {}
    badge = rf.get("badge") or {}
    side = _side_of(s.direction)
    # decide()'s may_vote, and its age bound: a default bot counts a
    # signal for 24 hours from when it FIRED (created_at), whatever the
    # scanner re-matched since (2026-11-06, the review).
    may_vote = bool(badge.get("may_trade")) and badge.get("label") != "PAUSED"
    vote_until = s.created_at + timedelta(hours=RAIL_FRESH_HOURS)
    votes = may_vote and now <= vote_until
    stage = badge.get("stage") or ""
    held = ctx["held"].get((inst.symbol or "").upper(), "")
    mark, fresh = _fresh_mark(inst, now)
    entry, stop, target = _levels(s)
    progress = rr_now = None
    order = _order_side(side)
    if fresh and order and entry is not None and stop is not None \
            and abs(entry - stop) > 1e-12:
        sign = 1 if order == "BUY" else -1
        progress = round((mark - entry) * sign / abs(entry - stop), 2)
    if fresh and order and stop is not None and target is not None:
        rr_now = reward_risk_advisory(order, mark, stop, target).get("ratio")
    aff = _affirmed(s, ctx["last_flag"])
    cls = inst.asset_class or ""
    pool = _pool_class(cls)
    market = _market(inst, ctx, now)
    if aff > s.created_at:
        leaves = (f"It leaves the rail {RAIL_FRESH_HOURS}h after the scanner "
                  f"last matched its setup, unless the scanner matches it "
                  f"again")
    else:
        leaves = (f"It leaves the rail {RAIL_FRESH_HOURS}h after it fired: "
                  f"past that a default bot no longer counts its vote, nor "
                  f"an instrument-view ticket as backing")
    return RailFacts(
        asset_class=cls, side=side, score_band=_score_band(s.score),
        stage=stage, stage_label=badge.get("label") or "",
        stage_tone=badge.get("tone") or "",
        stage_reason=badge.get("reason") or "",
        may_vote=may_vote, votes=votes,
        live=votes and stage in LIVE_STAGES,
        vote_until=vote_until,
        vote_words=_vote_words(s, may_vote, votes, vote_until, aff, now),
        leaves_words=leaves,
        held=bool(held), held_venue=held, rule_key=rule_key(s.rule_name),
        mark=mark, mark_fresh=fresh, progress_r=progress, rr_now=rr_now,
        affirmed_at=aff, leaves_at=aff + timedelta(hours=RAIL_FRESH_HOURS),
        record_words=_record_words(s.rule_name, rf.get("stats")),
        live_words=_live_words(s.rule_name, pool,
                               (rf.get("live") or {}).get(pool)),
        market="" if market["tradeable"] else market["state"],
        market_words=market["words"], opens=market["opens"],
        opens_at=market["reopens"],
        misses_open=bool(market["reopens"] is not None and (
            aff + timedelta(hours=RAIL_FRESH_HOURS)) < market["reopens"]))


def _market(inst, ctx, now) -> dict:
    """The instrument's market state, read once per instrument and render
    (signals.market_hold.market_state: the market clock, no query)."""
    seen = ctx.setdefault("markets", {})
    key = getattr(inst, "pk", None) or id(inst)
    if key not in seen:
        from signals.market_hold import market_state
        seen[key] = market_state(inst, now=now)
    return seen[key]


def _class_index(cls) -> int:
    try:
        return CLASS_ORDER.index(cls)
    except ValueError:
        return len(CLASS_ORDER)


def _rank(cards) -> None:
    """The order variables CSS sorts by (`order:`): by score, by class
    newest first, and by class then score. DOM order stays newest first."""
    at = {s.pk: i for i, s in enumerate(cards)}
    by_score = sorted(cards, key=lambda s: (-(s.score or 0), at[s.pk]))
    for i, s in enumerate(by_score, 1):
        s.rail.o_score = i
    seen, seen_score = {}, {}
    for s in cards:
        k = _class_index(s.rail.asset_class)
        seen[k] = seen.get(k, 0) + 1
        s.rail.o_cls = k * 10000 + seen[k]
    for s in by_score:
        k = _class_index(s.rail.asset_class)
        seen_score[k] = seen_score.get(k, 0) + 1
        s.rail.o_cscore = k * 10000 + seen_score[k]


def _contras(cards) -> None:
    """A newer opposite-side signal from ANOTHER rule on the same
    instrument is a badge on the older card, never a departure: the bots
    net the two sides, and the operator decides."""
    for s in cards:
        side = s.rail.side
        if side == "flat":
            continue
        best = None
        for o in cards:
            if (o.instrument_id == s.instrument_id and o.pk != s.pk
                    and (o.rule_name or "") != (s.rule_name or "")
                    and o.rail.side not in ("flat", side)
                    and (o.created_at, o.pk) > (s.created_at, s.pk)
                    and (best is None or o.created_at > best.created_at)):
                best = o
        if best is not None:
            s.rail.contra = {"rule": best.rule_name or best.signal_type or "",
                             "side": best.rail.side.upper(),
                             "at": best.created_at}


# ── the snapshot ──────────────────────────────────────────────────────────

def _empty(error="") -> dict:
    classes = [(k, CLASS_SHORT.get(k, k.upper()), 0) for k in CLASS_ORDER]
    meta = {"ok": not error, "n": 0, "long": 0, "short": 0, "active": 0,
            "gone": 0, "older": 0, "new24": 0, "classes": [], "rules": [],
            "votes": 0, "live": 0, "held": 0, "shut": 0, "ceiling": False,
            "title": "The rail could not be read." if error else "No signal on the rail."}
    return {"cards": [], "rows": [], "gone": [], "gone_n": 0, "gone_more": 0,
            "waiting": [], "waiting_n": 0, "hold": False,
            "gone_tags": [], "gone_tags_words": "", "n": 0, "long_n": 0,
            "short_n": 0, "active_n": 0, "older_n": 0, "new24": 0,
            "classes": classes, "rules": [], "groups": [], "votes_n": 0, "live_n": 0,
            "held_n": 0, "shut_n": 0, "ceiling_hit": False, "evaluated": 0, "total": 0,
            "unevaluated": 0, "closed_unread": 0,
            "closed_fetch": GONE_CLOSED_FETCH,
            "ceiling": RAIL_SAFETY_CEILING, "error": error, "meta": meta,
            "title": meta["title"]}


def rail_snapshot(request) -> dict:
    """The rail, the headband popup's rows, LEFT THE RAIL and every count,
    from ONE read per request (memoised on it). Never raises: on an error
    it answers an empty rail that says so."""
    cached = getattr(request, "_sv_rail", None)
    if cached is not None:
        return cached
    try:
        snap = _build(request)
    except Exception as e:  # noqa: BLE001 — a rail must not 500 a page
        logger.warning("[rail] snapshot failed: %s", e, exc_info=True)
        snap = _empty(error=f"{type(e).__name__}: {e}"[:200])
    try:
        request._sv_rail = snap
    except Exception:  # noqa: BLE001
        pass
    return snap


def _build(request) -> dict:
    from dashboard.models import RailDeparture
    from signals.models import OpportunityFlag, PromotionEvent, Signal

    now = timezone.now()
    window_start = now - timedelta(hours=RAIL_WINDOW_HOURS)
    gone_start = now - timedelta(hours=RAIL_FRESH_HOURS)
    user = getattr(request, "user", None)
    if user is not None and not getattr(user, "is_authenticated", False):
        user = None

    # 1. The candidates: active, and born or affirmed by the scanner in the
    #    window. Newest first; the ceiling binds only on a runaway writer.
    flagged = (OpportunityFlag.objects
               .filter(scanned_at__gte=window_start, signal__isnull=False)
               .values("signal_id"))
    cand_qs = (Signal.objects.filter(is_active=True)
               .filter(Q(created_at__gte=window_start) | Q(pk__in=flagged))
               .select_related("instrument", "instrument__live_quote")
               .order_by("-created_at", "-pk"))
    candidates = list(cand_qs[:RAIL_SAFETY_CEILING + 1])
    ceiling_hit = len(candidates) > RAIL_SAFETY_CEILING
    candidates = candidates[:RAIL_SAFETY_CEILING]
    total = cand_qs.count() if ceiling_hit else len(candidates)
    # Past the ceiling: not evaluated, so never counted as "left earlier".
    unevaluated = max(0, total - len(candidates))

    # 2. The engine's own closes of the last 24 hours, read up to a bound;
    #    past it, one count says how many more there were.
    closed_qs = Signal.objects.filter(is_active=False,
                                      expired_at__gte=gone_start)
    closed = list(closed_qs
                  .select_related("instrument", "instrument__live_quote")
                  .order_by("-expired_at", "-pk")[:GONE_CLOSED_FETCH + 1])
    closed_unread = 0
    if len(closed) > GONE_CLOSED_FETCH:
        closed = closed[:GONE_CLOSED_FETCH]
        last = closed[-1]
        closed_unread = closed_qs.filter(
            Q(expired_at__lt=last.expired_at)
            | Q(expired_at=last.expired_at, pk__lt=last.pk)).count()

    ids = [s.pk for s in candidates] + [s.pk for s in closed]
    last_flag = dict(OpportunityFlag.objects.filter(signal_id__in=ids)
                     .order_by().values("signal_id")
                     .annotate(last=Max("scanned_at"))
                     .values_list("signal_id", "last")) if ids else {}

    # 3. What was recorded: the rail's own lifecycle rows and this
    #    operator's own passes and takes.
    who = Q(user__isnull=True) | Q(user=user) if user is not None \
        else Q(user__isnull=True)
    rows = list(RailDeparture.objects
                .filter(Q(signal_id__in=ids) | Q(departed_at__gte=gone_start))
                .filter(who)
                .select_related("signal", "signal__instrument",
                                "signal__instrument__live_quote"))
    mine = {r.signal_id: r for r in rows if r.user_id is not None}
    life = {r.signal_id: r for r in rows if r.user_id is None}

    id_set = set(ids)
    extra = {r.signal_id: r.signal for r in rows if r.signal_id not in id_set}
    rules = sorted({s.rule_name or "" for s in candidates + closed}
                   | {s.rule_name or "" for s in extra.values()})
    # When each rule's newest candidate reached the rail: a cached fact
    # read before that moment is read again (_rule_facts).
    arrived = {}
    for s in candidates:
        if s.rule_name:
            came = _affirmed(s, last_flag)
            if arrived.get(s.rule_name) is None or came > arrived[s.rule_name]:
                arrived[s.rule_name] = came
    rule_facts = _rule_facts(rules, arrived)

    demotions = {}
    if candidates:
        oldest = min(s.created_at for s in candidates)
        for ev in (PromotionEvent.objects
                   .filter(rule_name__in=[r for r in rules if r],
                           created_at__gte=oldest)
                   .order_by("created_at")):
            if _is_demotion(ev):
                demotions.setdefault(ev.rule_name, []).append(ev)

    Signal.prime_acted(candidates)
    held = held_symbols(request)

    newest = {}
    for s in candidates + closed:
        if not s.rule_name:
            continue
        key = (s.instrument_id, s.rule_name)
        cur = newest.get(key)
        if cur is None or (s.created_at, s.pk) > (cur.created_at, cur.pk):
            newest[key] = s

    ctx = {"now": now, "mine": mine, "life": life, "newest": newest,
           "last_flag": last_flag, "rules": rule_facts,
           "demotions": demotions, "held": held, "hold": _hold_on()}

    # 4. The verdicts. The rail's own lifecycle judges every candidate, the
    #    ones this operator passed included (the lifecycle is the rail's, a
    #    pass is one operator's); your own pass or take is the first match.
    cards, gone, to_store, waiting = [], [], [], []
    for s in candidates:
        v = _lifecycle(s, ctx)
        if v is not None and v.store:
            to_store.append(RailDeparture(
                signal=s, user=None, reason=v.reason, words=v.words[:300],
                mark=(None if v.mark is None else round(v.mark, 8)),
                departed_at=v.at))
        own = mine.get(s.pk)
        if own is None:
            if v is None:
                s.rail = _facts(s, ctx, now)
                if ctx["hold"] and s.rail.market:
                    # THE OPTIONAL HOLD: its market cannot trade now, so it
                    # waits under MARKET SHUT, off the cards.
                    waiting.append(_waiting_row(s, ctx, now))
                else:
                    cards.append(s)
            elif v.at >= gone_start:
                gone.append(_gone_row(s, v.reason, v.words, v.at, False, ctx,
                                      now, active=True))
            continue
        at, words = own.departed_at, own.words
        if at < gone_start:
            if v is not None:
                continue            # past on its own as well
            # A setup the scanner matched again after your pass: it would be
            # on the rail but for the pass, so it is listed — as of the
            # re-match — and can always be brought back.
            aff = _affirmed(s, last_flag)
            did = "took" if own.reason == "taken" else "passed"
            at = aff
            words = (f"You {did} it {_on_day(own.departed_at)}; the scanner "
                     f"matched its setup again at {_hhmm(aff)}.")
        gone.append(_gone_row(s, own.reason, words, at, True, ctx, now,
                              active=True))

    if to_store:
        try:
            from django.db import transaction
            with transaction.atomic():
                RailDeparture.objects.bulk_create(to_store,
                                                  ignore_conflicts=True)
        except Exception as e:  # noqa: BLE001 — the render stands
            logger.warning("[rail] departures not recorded: %s", e)

    seen = {g.signal_id for g in gone} | {s.pk for s in cards}
    # The rest of LEFT THE RAIL — the engine's closes and the departures of
    # signals no longer candidates — read their positions in one query,
    # as the cards do (a row's position line, the taken words).
    Signal.prime_acted([c for c in closed if c.pk not in seen]
                       + [sig for sid, sig in extra.items()
                          if sig is not None and sid not in seen])
    for c in closed:
        if c.pk in seen:
            continue
        seen.add(c.pk)
        dep = mine.get(c.pk) or life.get(c.pk)
        closed_words = ""
        if dep is not None:
            if dep.departed_at < gone_start:
                continue
            reason, words, at, yours = (dep.reason, dep.words,
                                        dep.departed_at, dep.user_id is not None)
            closed_words = (f"closed by the engine at {_hhmm(c.expired_at)}: "
                            f"{_close_words(c)}")
        else:
            aff = _affirmed(c, last_flag)
            aged_at = aff + timedelta(hours=RAIL_FRESH_HOURS)
            if c.expired_at and aged_at < c.expired_at:
                if aged_at < gone_start:
                    continue
                reason, words, at, yours = ("aged", _aged_at_words(
                    c, aff, aged_at, last_flag), aged_at, False)
                closed_words = (f"closed by the engine at "
                                f"{_hhmm(c.expired_at)}: {_close_words(c)}")
            else:
                reason = CLOSE_REASON.get(c.outcome or "", "closed")
                words = f"The engine closed it: {_close_words(c)}."
                at, yours = c.expired_at or now, False
        g = _gone_row(c, reason, words, at, yours, ctx, now, active=False)
        g.closed_words = closed_words
        gone.append(g)

    for sid, sig in extra.items():
        if sid in seen or sig is None:
            continue
        seen.add(sid)
        dep = mine.get(sid) or life.get(sid)
        if dep is None or dep.departed_at < gone_start:
            continue
        g = _gone_row(sig, dep.reason, dep.words, dep.departed_at,
                      dep.user_id is not None, ctx, now,
                      active=bool(sig.is_active))
        if not sig.is_active and sig.expired_at:
            g.closed_words = (f"closed by the engine at "
                              f"{_hhmm(sig.expired_at)}: {_close_words(sig)}")
        gone.append(g)

    gone.sort(key=lambda g: (g.at, g.signal_id), reverse=True)
    tags = {}
    for g in gone:
        tags[g.tag] = tags.get(g.tag, 0) + 1
    gone_tags = sorted(tags.items(), key=lambda kv: (-kv[1], kv[0]))
    # Every departure the engine still holds is drawn, its ticket with it:
    # a burst of departures must never take the operator's last way to act
    # on one. The engine's own closes, which no ticket can take, are drawn
    # up to GONE_ROWS and counted past it.
    shown, closes_drawn = [], 0
    for g in gone:
        if g.engine_active:
            shown.append(g)
        elif closes_drawn < GONE_ROWS:
            shown.append(g)
            closes_drawn += 1
    gone_n = len(gone) + closed_unread
    _contras(cards)
    _rank(cards)

    # 5. The counts.
    active_n = Signal.objects.filter(is_active=True).count()
    new24 = Signal.objects.filter(created_at__gte=gone_start).count()
    gone_active = sum(1 for g in gone if g.engine_active)
    n = len(cards)
    waiting_n = len(waiting)
    long_n = sum(1 for s in cards if s.rail.side == "long")
    short_n = sum(1 for s in cards if s.rail.side == "short")
    older_n = max(0, active_n - n - waiting_n - gone_active - unevaluated)
    per_class = {}
    for s in cards:
        per_class[s.rail.asset_class] = per_class.get(s.rail.asset_class, 0) + 1
    classes = [(k, CLASS_SHORT.get(k, k.upper()), per_class.get(k, 0))
               for k in CLASS_ORDER]
    classes += [(k, (k or "OTHER").upper(), v) for k, v in per_class.items()
                if k not in CLASS_ORDER]
    per_rule = {}
    for s in cards:
        per_rule[s.rule_name or ""] = per_rule.get(s.rule_name or "", 0) + 1
    rule_list = sorted(((name, rule_key(name), cnt)
                        for name, cnt in per_rule.items()),
                       key=lambda t: (-t[2], t[0]))
    votes_n = sum(1 for s in cards if s.rail.votes)
    live_n = sum(1 for s in cards if s.rail.live)
    held_n = sum(1 for s in cards if s.rail.held)
    # The cards whose market is shut now: the SHUT chip's number.
    shut_n = sum(1 for s in cards if s.rail.market == "shut")
    title = (f"{n} on the rail · {active_n} active in the engine · "
             f"{gone_n} left in the last 24h · {older_n} left earlier")
    if ctx["hold"]:
        title = (f"{n} on the rail · {waiting_n} waiting for their market "
                 f"· {active_n} active in the engine · {gone_n} left in the "
                 f"last 24h · {older_n} left earlier")
    if closed_unread:
        title += (f" ({closed_unread} more engine closes not read: the "
                  f"newest {GONE_CLOSED_FETCH} were)")
    if ceiling_hit:
        title += (f" · showing the newest {RAIL_SAFETY_CEILING} of {total} "
                  f"signals from the last {RAIL_WINDOW_HOURS}h")

    groups, seen_cls = [], set()
    for s in cards:
        cls = s.rail.asset_class
        if cls in seen_cls:
            continue
        seen_cls.add(cls)
        groups.append({"asset_class": cls,
                       "label": CLASS_SHORT.get(cls, (cls or "other").upper()),
                       "o_cls": _class_index(cls) * 10000})

    rows_out = [{
        "id": s.pk,
        "symbol": s.instrument.symbol,
        "asset_class": s.rail.asset_class,
        "direction": s.direction,
        "side": s.rail.side,
        "score_pct": int(round((s.score or 0) * 100)),
        "rule": s.rule_name or s.signal_type or "",
        "created_at": s.created_at,
        "entry": s.suggested_entry,
        "stop": s.suggested_stop,
        "rail": s.rail,
    } for s in cards]

    meta = {"ok": True, "n": n, "long": long_n, "short": short_n,
            "active": active_n, "gone": gone_n, "older": older_n,
            "new24": new24,
            "classes": [[k, c] for k, _label, c in classes if c],
            "rules": [[name, key, cnt] for name, key, cnt in rule_list],
            "votes": votes_n, "live": live_n, "held": held_n,
            "shut": shut_n, "ceiling": ceiling_hit, "title": title}
    if ctx["hold"]:
        meta["waiting"] = waiting_n

    tags_words = " · ".join(f"{t.lower()} {c}" for t, c in gone_tags)
    if closed_unread:
        tags_words = " · ".join(filter(None, [
            tags_words, f"{closed_unread} engine closes not read"]))
    return {
        "cards": cards, "rows": rows_out, "gone": shown,
        "waiting": waiting, "waiting_n": waiting_n, "hold": ctx["hold"],
        "gone_n": gone_n, "gone_more": max(0, len(gone) - len(shown)),
        "gone_tags": gone_tags,
        "gone_tags_words": tags_words,
        "n": n, "long_n": long_n, "short_n": short_n, "active_n": active_n,
        "older_n": older_n, "new24": new24, "classes": classes,
        "rules": rule_list, "groups": groups,
        "votes_n": votes_n, "live_n": live_n,
        "held_n": held_n, "shut_n": shut_n, "ceiling_hit": ceiling_hit,
        "evaluated": len(candidates), "total": total,
        "unevaluated": unevaluated, "closed_unread": closed_unread,
        "closed_fetch": GONE_CLOSED_FETCH,
        "ceiling": RAIL_SAFETY_CEILING, "error": "", "meta": meta,
        "title": title,
    }


def _hold_on() -> bool:
    """The optional hold's switch, read once per render; never asked while
    the market gate is off (the test suite), so no query is spent there."""
    try:
        from signals import market_hold
        return bool(market_hold.GATE and market_hold.enabled())
    except Exception:  # noqa: BLE001 — an unread switch is off
        return False


def _waiting_row(s, ctx, now) -> Gone:
    """One MARKET SHUT row: a candidate the rail would show as a card,
    whose market cannot trade now. The words say when it opens, and when
    the signal's hours on the rail end before that."""
    facts = s.rail
    words = (facts.market_words[:1].upper() + facts.market_words[1:] + "."
             if facts.market_words else "Its market cannot trade now.")
    if facts.misses_open:
        from core.exchange_status import utc_words
        words += (f" Its {RAIL_FRESH_HOURS} hours end "
                  f"{utc_words(facts.leaves_at)}, before the market opens.")
    return _gone_row(s, "market_" + facts.market, words,
                     facts.opens_at or now, False, ctx, now, active=True)


def _gone_row(s, reason, words, at, yours, ctx, now, *, active) -> Gone:
    """One LEFT THE RAIL row. The stored words say their moment; what can
    change after them is said as it is now: your own position (TAKEN reads
    the book, not the words written at the take) and a paused rule."""
    inst = s.instrument
    facts = _facts(s, ctx, now)
    # Primed with everyone else's (prime_acted); asked alone only if the
    # batched read failed.
    acted = s._acted_cache if hasattr(s, "_acted_cache") else s.acted
    own_hand = bool(acted and acted.get("by") == "manual" and acted.get("exact"))
    closing = bool(acted) and acted.get("status") == "CLOSE_PENDING"
    position = ""
    if yours and reason == "taken":
        if own_hand:
            words = (f"You took it at {_hhmm(acted.get('opened_at'))}: "
                     f"position #{acted.get('trade_id')} "
                     + ("is closing (close pending)." if closing
                        else "is open."))
        else:
            words = words.rstrip(".") + "; you hold no position on it now."
    elif acted:
        who = "BY HAND" if acted.get("by") == "manual" else "BY BOT"
        state = "is closing, close pending" if closing else "is still open"
        position = f"position #{acted.get('trade_id')} {state} ({who})"
    if reason == "rule_paused":
        badge = ((ctx["rules"].get(s.rule_name or "") or {}).get("badge")
                 or {})
        words = (f"{words} Its rule is paused now."
                 if badge.get("label") == "PAUSED"
                 else f"{words} Its rule is no longer paused.")
    return Gone(
        signal_id=s.pk, symbol=inst.symbol, asset_class=inst.asset_class or "",
        side=facts.side, direction=s.direction, rule=s.rule_name or "",
        rule_key=facts.rule_key, reason=reason,
        tag=TAGS.get(reason, reason.upper()), words=words, at=at,
        score=float(s.score or 0), created_at=s.created_at,
        engine_active=bool(active),
        takeable=bool(active and facts.side != "flat" and not own_hand),
        yours=bool(yours), position_words=position, facts=facts)


def pass_words(signal, now=None) -> tuple:
    """(reason, words) for the operator's own departure of `signal`: TAKEN
    when the book shows their own exact hand position on it, PASSED
    otherwise. Written once, so said in the past: the take at the moment the
    position opened, never "is open" (LEFT THE RAIL says that from the book,
    as it is when the row is read)."""
    now = now or timezone.now()
    acted = signal.acted
    if acted and acted.get("by") == "manual" and acted.get("exact"):
        return ("taken", f"You took it at "
                         f"{_hhmm(acted.get('opened_at') or now)} "
                         f"(position #{acted.get('trade_id')}).")
    return ("passed", f"You passed it at {_hhmm(now)}.")
