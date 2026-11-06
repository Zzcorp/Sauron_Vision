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
   4  aged             past the 24h the bots and the hand ticket count it
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
dashboard.RailDeparture the first time the rail sees it. Age is a clock and
is re-read on each render. The engine's own closes (target, stop, 7-day
expiry) are read from the Signal row as they are.

NOTHING HERE IS A SECOND IMPLEMENTATION. The 24 hours are
manual_trade.SIGNAL_BACKING_HOURS (and decide()'s default
max_signal_age_hours); the quote bound is signals.performance's
MAX_QUOTE_AGE_SECONDS; the reward:risk is manual_trade.reward_risk_advisory
against REWARD_RISK_WARN, the ticket's own; "votes" is decide()'s may_vote,
read through dashboard.signal_surface.stage_badge, which calls the two
functions the entry path calls; the loser is promotion_pipeline's
measured_loser on the floor's own grouped record; the real-money record is
bot_grading's own summary, world="live".

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
#: LEFT THE RAIL rows drawn in full; the counts cover all of them.
GONE_ROWS = 60
#: Engine closes of the last 24h read for LEFT THE RAIL.
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
    votes: bool = False
    live: bool = False
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


def _px(value, inst) -> str:
    from core.price_format import format_price
    return format_price(value, getattr(inst, "asset_class", ""),
                        getattr(inst, "symbol", ""))


def _hours(seconds) -> str:
    return f"{int(seconds // 3600)}h"


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


def _rule_facts(rules) -> dict:
    """{rule: {"badge", "stats", "loser", "live"}} — per distinct rule,
    cached RULE_FACTS_TTL seconds outside the test runner."""
    from django.core.cache import cache
    from dashboard.signal_surface import badges_for
    from signals.promotion_pipeline import measured_loser

    testing = _testing()
    out, missing = {}, []
    for r in rules:
        hit = None if testing else cache.get(f"sv:rail:rule:{rule_key(r)}")
        if isinstance(hit, dict) and hit.get("name") == r:
            out[r] = hit
        else:
            missing.append(r)
    if not missing:
        return out
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
    for r in missing:
        st = stats.get(r) or {"n": 0, "expectancy": None, "hit_rate": None}
        try:
            loser = measured_loser(r, stats=st) if r else ""
        except Exception:  # noqa: BLE001
            loser = ""
        fact = {"name": r, "badge": badges.get(r) or {}, "stats": st,
                "loser": loser,
                "live": {cls: row for (rn, cls), row in live.items() if rn == r}}
        out[r] = fact
        if not testing:
            cache.set(f"sv:rail:rule:{rule_key(r)}", fact, RULE_FACTS_TTL)
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
    age = (now - aff).total_seconds()
    if last_flag.get(s.pk) and aff > s.created_at:
        return (f"The scanner last matched this setup {_hours(age)} ago, past "
                f"the {RAIL_FRESH_HOURS}h in which the bots count its vote "
                f"and a hand ticket counts it as backing.")
    return (f"{_hours(age)} old, past the {RAIL_FRESH_HOURS}h in which the bots "
            f"count its vote and a hand ticket counts it as backing.")


def _price_verdict(s, mark, side):
    """(reason, words) when a fresh mark says the plan is past, else None."""
    entry, stop, target = _levels(s)
    inst = s.instrument
    order = _order_side(side)
    if order is None or mark is None:
        return None
    if stop is not None and ((order == "BUY" and mark <= stop)
                             or (order == "SELL" and mark >= stop)):
        return ("stop_crossed",
                f"Price {_px(mark, inst)} went through its stop "
                f"{_px(stop, inst)}; a ticket here is refused (levels on the "
                f"wrong side of the price).")
    if target is not None and ((order == "BUY" and mark >= target)
                               or (order == "SELL" and mark <= target)):
        return ("target_reached",
                f"Price {_px(mark, inst)} reached its target {_px(target, inst)}.")
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
                f"Price ran {pct:.0f}% of the way to its target: from "
                f"{_px(mark, inst)} it risks {_px(risk, inst)} to make "
                f"{_px(reward, inst)}, reward:risk {now_rr:.2f}, under the "
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


def _verdict(s, ctx):
    """(reason, words, departed_at, mark, store, yours) or None (stays)."""
    mine = ctx["mine"].get(s.pk)
    if mine is not None:
        return (mine.reason, mine.words, mine.departed_at, _f(mine.mark),
                False, True)
    rec = ctx["life"].get(s.pk)
    if rec is not None:
        return (rec.reason, rec.words, rec.departed_at, _f(rec.mark),
                False, False)
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
            return ("superseded",
                    f"{verb} by a newer {word} from the same rule "
                    f"({s.rule_name}) at {_hhmm(newer.created_at)}.",
                    newer.created_at, None, True, False)
    aff = _affirmed(s, ctx["last_flag"])
    if (now - aff) > timedelta(hours=RAIL_FRESH_HOURS):
        return ("aged", _aged_words(s, aff, now, ctx["last_flag"]),
                aff + timedelta(hours=RAIL_FRESH_HOURS), None, False, False)
    mark, fresh = _fresh_mark(s.instrument, now)
    if fresh:
        hit = _price_verdict(s, mark, side)
        if hit is not None:
            return (hit[0], hit[1], now, mark, True, False)
    rf = ctx["rules"].get(s.rule_name or "") or {}
    badge = rf.get("badge") or {}
    rule = s.rule_name or ""
    if badge.get("label") == "PAUSED":
        return ("rule_paused",
                f"Its rule ({rule}) is paused: the engine writes no new "
                f"signal for it and the bots no longer count its vote.",
                now, None, True, False)
    ev = _demotion_after(s, ctx["demotions"])
    if ev is not None:
        return ("rule_demoted",
                f"Its rule ({rule}) was demoted from {ev.from_stage} to "
                f"{ev.to_stage} at {_hhmm(ev.created_at)} "
                f"({_DEMOTE_WORDS.get(ev.reason, ev.reason)}).",
                ev.created_at, None, True, False)
    if rf.get("loser"):
        return ("rule_losing",
                "Its rule's graded record is a measured loser: " + rf["loser"],
                now, None, True, False)
    cls = _pool_class(s.instrument.asset_class)
    row = (rf.get("live") or {}).get(cls)
    if (rule and row and int(row.get("n") or 0) >= LIVE_RECORD_MIN_N
            and float(row.get("expectancy") or 0) <= 0):
        return ("rule_losing_live",
                f"{rule} lost real money on {cls}: {int(row['n'])} closed "
                f"real-money trades in {LIVE_RECORD_DAYS} days, expectancy "
                f"{float(row['expectancy']):+.2f}R.",
                now, None, True, False)
    return None


def _close_words(s) -> str:
    what = CLOSE_WORDS.get(s.outcome or "")
    r = s.realized_r
    tail = f" ({r:+.2f}R)" if r is not None and s.outcome in (
        "hit_target", "stopped_out", "manual_close") else ""
    return f"{what}{tail}" if what else "closed"


def _facts(s, ctx, now) -> RailFacts:
    inst = s.instrument
    rf = ctx["rules"].get(s.rule_name or "") or {}
    badge = rf.get("badge") or {}
    side = _side_of(s.direction)
    votes = bool(badge.get("may_trade")) and badge.get("label") != "PAUSED"
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
    return RailFacts(
        asset_class=cls, side=side, score_band=_score_band(s.score),
        stage=stage, stage_label=badge.get("label") or "",
        stage_tone=badge.get("tone") or "",
        stage_reason=badge.get("reason") or "",
        votes=votes, live=votes and stage in ("live_small", "live_full"),
        held=bool(held), held_venue=held, rule_key=rule_key(s.rule_name),
        mark=mark, mark_fresh=fresh, progress_r=progress, rr_now=rr_now,
        affirmed_at=aff, leaves_at=aff + timedelta(hours=RAIL_FRESH_HOURS),
        record_words=_record_words(s.rule_name, rf.get("stats")),
        live_words=_live_words(s.rule_name, pool,
                               (rf.get("live") or {}).get(pool)))


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
            "votes": 0, "live": 0, "held": 0, "ceiling": False,
            "title": "The rail could not be read." if error else "No signal on the rail."}
    return {"cards": [], "rows": [], "gone": [], "gone_n": 0, "gone_more": 0,
            "gone_tags": [], "gone_tags_words": "", "n": 0, "long_n": 0,
            "short_n": 0, "active_n": 0, "older_n": 0, "new24": 0,
            "classes": classes, "rules": [], "votes_n": 0, "live_n": 0,
            "held_n": 0, "ceiling_hit": False, "evaluated": 0, "total": 0,
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

    # 2. The engine's own closes of the last 24 hours.
    closed = list(Signal.objects
                  .filter(is_active=False, expired_at__gte=gone_start)
                  .select_related("instrument", "instrument__live_quote")
                  .order_by("-expired_at", "-pk")[:GONE_CLOSED_FETCH])

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
                .select_related("signal", "signal__instrument"))
    mine = {r.signal_id: r for r in rows if r.user_id is not None}
    life = {r.signal_id: r for r in rows if r.user_id is None}

    id_set = set(ids)
    extra = {r.signal_id: r.signal for r in rows if r.signal_id not in id_set}
    rules = sorted({s.rule_name or "" for s in candidates + closed}
                   | {s.rule_name or "" for s in extra.values()})
    rule_facts = _rule_facts(rules)

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
           "demotions": demotions, "held": held}

    # 4. The verdicts.
    cards, gone, to_store = [], [], []
    for s in candidates:
        v = _verdict(s, ctx)
        if v is None:
            s.rail = _facts(s, ctx, now)
            cards.append(s)
            continue
        reason, words, at, mark, store, yours = v
        if store:
            to_store.append(RailDeparture(
                signal=s, user=None, reason=reason, words=words[:300],
                mark=(None if mark is None else round(mark, 8)),
                departed_at=at))
        if at >= gone_start:
            gone.append(_gone_row(s, reason, words, at, yours, ctx, now,
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
                reason, words, at, yours = ("aged", _aged_words(
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
    shown = gone[:GONE_ROWS]
    _contras(cards)
    _rank(cards)

    # 5. The counts.
    active_n = Signal.objects.filter(is_active=True).count()
    new24 = Signal.objects.filter(created_at__gte=gone_start).count()
    gone_active = sum(1 for g in gone if g.engine_active)
    n = len(cards)
    long_n = sum(1 for s in cards if s.rail.side == "long")
    short_n = sum(1 for s in cards if s.rail.side == "short")
    older_n = max(0, active_n - n - gone_active)
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
    title = (f"{n} on the rail · {active_n} active in the engine · "
             f"{len(gone)} left in the last 24h · {older_n} left earlier")
    if ceiling_hit:
        title += (f" · showing the newest {RAIL_SAFETY_CEILING} of {total} "
                  f"signals from the last {RAIL_WINDOW_HOURS}h")

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
            "active": active_n, "gone": len(gone), "older": older_n,
            "new24": new24,
            "classes": [[k, c] for k, _label, c in classes if c],
            "rules": [[name, key, cnt] for name, key, cnt in rule_list],
            "votes": votes_n, "live": live_n, "held": held_n,
            "ceiling": ceiling_hit, "title": title}

    return {
        "cards": cards, "rows": rows_out, "gone": shown,
        "gone_n": len(gone), "gone_more": max(0, len(gone) - len(shown)),
        "gone_tags": gone_tags,
        "gone_tags_words": " · ".join(f"{t.lower()} {c}" for t, c in gone_tags),
        "n": n, "long_n": long_n, "short_n": short_n, "active_n": active_n,
        "older_n": older_n, "new24": new24, "classes": classes,
        "rules": rule_list, "votes_n": votes_n, "live_n": live_n,
        "held_n": held_n, "ceiling_hit": ceiling_hit,
        "evaluated": len(candidates), "total": total,
        "ceiling": RAIL_SAFETY_CEILING, "error": "", "meta": meta,
        "title": title,
    }


def _gone_row(s, reason, words, at, yours, ctx, now, *, active) -> Gone:
    inst = s.instrument
    facts = _facts(s, ctx, now)
    acted = getattr(s, "_acted_cache", None) if active else None
    if active and not hasattr(s, "_acted_cache"):
        acted = s.acted
    own_hand = bool(acted and acted.get("by") == "manual" and acted.get("exact"))
    position = ""
    if acted:
        who = "BY HAND" if acted.get("by") == "manual" else "BY BOT"
        position = f"position #{acted.get('trade_id')} still open ({who})"
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
    otherwise."""
    now = now or timezone.now()
    acted = signal.acted
    if acted and acted.get("by") == "manual" and acted.get("exact"):
        return ("taken", f"You took it at {_hhmm(now)}: position "
                         f"#{acted.get('trade_id')} is open.")
    return ("passed", f"You passed it at {_hhmm(now)}.")
