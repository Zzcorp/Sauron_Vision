"""Phase 61 — the open-position watcher, layer 1: the free deterministic pass.

The gap this closes
-------------------
Before this module, an open position was watched by exactly four things, all
mechanical and all blind: the stop, the target, an opt-in trailing stop, and a
time stop keyed to `extras["max_hold_hours"]` that no config sets. The earnings
reviewer looks at a HELD symbol only when an earnings event lands for it, and
the daily strategist reasons about the book once a day as prose a human reads.
Nobody re-asked, while the position was on, whether the reasons it was opened
still hold.

This pass re-asks. It runs often, it costs nothing, it calls no model, and for
each open position it computes the facts that would make a human reconsider,
then emits a structured verdict naming the reasons that fired. It is the gate
in front of the expensive layer: `position_review_agent` only spends money on
positions this pass flagged.

Two rules that outrank everything else here
-------------------------------------------
1. It never closes anything. Not a single call in this module can. The verdict
   is a proposal; the operator acts from the card and the notification through
   dashboard/views_close.py, which is the one close path that grades, audits,
   and notifies identically to a bot-tick close.
2. No verdict on a stale mark. A recommendation computed from yesterday's
   price is worse than silence, because it looks exactly like one computed
   from today's. Positions whose mark is unusable get an explicit `no_quote`
   verdict that says so, and no trigger is even evaluated for them.

R is always denominated by the stop the trade OPENED with
(`metadata["initial_stop_loss"]`, read through the same helper the close
dialog uses), never the current one — a trailing stop rewrites the current
stop, and grading against that makes every trailed exit score ~1.0R.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from typing import Optional

from django.utils import timezone

logger = logging.getLogger(__name__)


# ── Book identifiers (mirrored on PositionReview so callers need one name) ─

BOOK_BOT = "bot"
BOOK_PORTFOLIO = "pf"

# Both statuses the rest of the platform counts as live exposure:
# CLOSE_PENDING is still open at the broker while the bot wants it flat.
OPEN_BOT_STATUSES = ("OPEN", "CLOSE_PENDING")


# ══════════════════════════════════════════════════════════════════════════
# Trigger thresholds — every one of these is a number a human would defend
# ══════════════════════════════════════════════════════════════════════════

# T1 give_back — a won trade round-tripping.
# 1.0R of open profit is the floor because below one R the excursion is inside
# ordinary noise: the trade has not yet earned anything worth protecting and
# the stop is still the right instrument. 50% is the give-back point because
# it is where the position has surrendered more than it still holds — "was
# +2R, now +0.9R" makes a human reach for the mouse; "+2R to +1.8R" does not.
GIVE_BACK_MIN_MFE_R = 1.0
GIVE_BACK_FRACTION = 0.5

# T2 risk_exceeds_reward — the forward leg has inverted.
# At entry the trade was taken at some R:R. If what is still at risk to the
# stop is more than 1.5x what is still on the table to the target, the FORWARD
# expectancy is upside-down even though the trade is a winner. 1.5 rather than
# 1.0 so this does not fire on every position that ticks past halfway.
RISK_REWARD_INVERSION = 1.5

# T3 adverse_excursion — the thesis has been paying nothing.
# -0.75R means the position has spent three quarters of the risk it was
# granted without ever going onside. The stop will still do its job; this is
# the state in which a human asks whether the thesis is simply wrong. Gated on
# the position still being under water so a dip-and-recover does not fire it.
ADVERSE_EXCURSION_R = -0.75

# T4/T5 near_stop / near_target — say it BEFORE the bracket decides.
# Inside a quarter of the original risk of either level, the mechanical exit
# is about to make the decision. Anything worth saying has to be said first.
NEAR_LEVEL_R = 0.25

# T6 horizon_exceeded — time has refuted the setup.
# The threshold is the SETUP'S OWN suggested_horizon_days, not a constant: a
# 3-day mean-reversion setup at day 9 has been refuted by the clock, a 30-day
# macro setup at day 9 has not. The ±0.5R band exists because a position 2R
# onside past its horizon is not stale, it is working. Unknown horizon means
# no fire — unknown is not zero.
HORIZON_FLAT_BAND_R = 0.5

# T7 regime_flip — the world changed under the position.
# 0.5 confidence because below it the brain is guessing, and a guess must not
# put a flag on live capital. `brain_trust_band` softens it further downstream.
REGIME_FLIP_MIN_CONFIDENCE = 0.5

# T8 vol_expansion — the position was sized for a calmer market.
# 1.5x the entry-window sigma means the same stop distance is now about two
# thirds of the volatility it was drawn against: the dollar loss is unchanged,
# the probability of taking it is not.
VOL_EXPANSION_RATIO = 1.5
VOL_WINDOW_BARS = 90        # enough daily closes for garch_lite (needs ≥30)

# T9 event_imminent — a gap the operator can still act before.
# 24h and high-impact only: it is the window in which acting is still possible,
# and medium/low events do not carry a position through its stop.
EVENT_HORIZON_HOURS = 24
EVENT_IMPACT = "high"

# T11 concentration — several positions expressing one bet.
# 3.0 is the platform's OWN "too much of one theme" number: it is the default
# `max_usd_theme_exposure` / `max_equity_theme_exposure` on TraderProfile, the
# level at which the orchestrator already refuses to ADD. This says the same
# thing about what is already on. 0.7 theme pressure is where the brain's
# 0..1 saturation scale starts squeezing caps materially.
THEME_EXPOSURE_LIMIT = 3.0
THEME_PRESSURE_LIMIT = 0.7
OVERLAP_MIN_RULES = 2

# T12 self_hedge — the book holds both sides of one instrument.
# No threshold to tune: one opposing position is the whole condition. The
# overlap audit T11 reads answers "same symbol and SAME side", so this case
# — the more expensive one, since the pair is flat and still paying both
# spreads — was visible to nothing. It was live in the book when this was
# written: USDCHF held BUY by one rule and SELL by another at the same time.

# Bars for the excursion window. 1h first, then 4h, then 1d — the finest
# timeframe that actually has rows since entry, because a daily bar hides the
# intraday spike that took a position to -0.9R and back.
EXCURSION_TIMEFRAMES = ("1h", "4h", "1d")
# No bar cap. There was one — the newest 400 — and it made `mae_r`/`mfe_r`
# lie about the window they name: on the 1h feed 400 bars is ~17 trading
# days, so anything held longer had its opening weeks dropped out of an
# answer labelled "since entry". The extremes are aggregated in the database
# now, which reads the whole window AND returns two numbers instead of four
# hundred rows, so there is nothing left for a cap to protect.


# ══════════════════════════════════════════════════════════════════════════
# The two books, read as one
# ══════════════════════════════════════════════════════════════════════════

def _dir_sign(side: str) -> int:
    """+1 for a long, -1 for a short.

    The two books spell the same idea differently — AssetBotTrade uses
    BUY/SELL, portfolio.Position uses long/short — and a sign error here
    would invert every R in the file.
    """
    s = str(side or "").strip().lower()
    return -1 if s in ("sell", "short", "bearish") else +1


def _side_label(side: str) -> str:
    """BUY / SELL, the spelling `orchestrator.classify_position` expects."""
    return "SELL" if _dir_sign(side) < 0 else "BUY"


def _f(value) -> Optional[float]:
    """float(value) or None — never raises, never invents a 0."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError, InvalidOperation):
        return None


def _bot_positions() -> list[dict]:
    """Open AssetBotTrade rows, normalised."""
    out: list[dict] = []
    try:
        from bot_program.models import AssetBotTrade
        from bot_program.manual_close import _initial_stop
    except Exception:  # pragma: no cover - app not installed
        return out
    qs = (AssetBotTrade.objects
          .filter(status__in=OPEN_BOT_STATUSES)
          .select_related("config", "config__user"))
    for t in qs:
        out.append({
            "book": BOOK_BOT,
            "position_id": t.id,
            "symbol": (t.symbol or "").upper(),
            "asset_class": t.asset_class or "",
            "side": _side_label(t.side),
            "dir_sign": _dir_sign(t.side),
            "qty": _f(t.qty),
            "entry": _f(t.entry_price),
            # The stop the trade OPENED with — the only correct R denominator.
            "initial_stop": _initial_stop(t),
            "stop": _f(t.stop_loss),
            "target": _f(t.take_profit),
            "opened_at": t.opened_at,
            "rule_name": t.rule_name or "",
            "reason": t.reason or "",
            "paper": bool(t.paper),
            "status": t.status,
            "user": getattr(t.config, "user", None),
            "metadata": dict(t.metadata or {}),
        })
    return out


def _portfolio_positions() -> list[dict]:
    """Open portfolio.Position rows, normalised.

    portfolio.Portfolio carries no user FK, so these rows have no owner to
    notify. They are still measured and still surfaced on the card — the book
    is real exposure whether or not anything can be pushed at somebody.
    """
    out: list[dict] = []
    try:
        from portfolio.models import Position
    except Exception:  # pragma: no cover
        return out
    qs = (Position.objects.filter(closed_at__isnull=True)
          .select_related("instrument", "strategy"))
    for p in qs:
        symbol = getattr(p.instrument, "symbol", "") or ""
        out.append({
            "book": BOOK_PORTFOLIO,
            "position_id": p.id,
            "symbol": symbol.upper(),
            "asset_class": getattr(p.instrument, "asset_class", "") or "",
            "side": _side_label(p.direction),
            "dir_sign": _dir_sign(p.direction),
            "qty": _f(p.quantity),
            "entry": _f(p.entry_price),
            # No metadata on this table: the current stop is all it ever had,
            # so it doubles as the initial one. A trailed row would flatter
            # its own R here, which is why the bot book does not do this.
            "initial_stop": _f(p.stop_loss),
            "stop": _f(p.stop_loss),
            "target": _f(p.take_profit),
            "opened_at": p.opened_at,
            "rule_name": getattr(p.strategy, "name", "") or "",
            "reason": "",
            "paper": True,
            "status": "OPEN",
            "user": None,
            "metadata": {},
        })
    return out


def open_positions() -> list[dict]:
    """Every live position across BOTH books.

    Any read side that looks at only one of them is describing half the
    exposure, which is how a watcher ends up quietly ignoring the book the
    operator actually trades.
    """
    return _bot_positions() + _portfolio_positions()


# ══════════════════════════════════════════════════════════════════════════
# The mark — and the refusal to work without one
# ══════════════════════════════════════════════════════════════════════════

def usable_mark(symbol: str) -> tuple[Optional[float], str]:
    """(price, source) for `symbol`, or (None, reason) when nothing is usable.

    Routed through PaperTrader.ticker rather than re-derived: that method is
    already the platform's definition of a usable mark — a LiveQuote inside
    MAX_QUOTE_AGE_SECONDS, else the newest bar inside MAX_BAR_AGE_SECONDS,
    else the literal answer "0" meaning no price. Re-implementing freshness
    here would let this module and the close dialog disagree about whether a
    price exists, and the disagreement would surface as advice on a fossil.

    No broker credentials are involved, which is why this can run for every
    position in the book on a beat.
    """
    sym = (symbol or "").strip()
    if not sym:
        return None, "no symbol"
    try:
        from bot_program.engine.paper_trader import PaperTrader
        tick = PaperTrader(None).ticker(sym) or {}
    except Exception as e:  # noqa: BLE001
        logger.warning("[position-review] mark lookup failed for %s: %s", sym, e)
        return None, f"mark lookup failed: {e}"
    price = _f(tick.get("lastPrice"))
    if price is None or price <= 0:
        return None, "no fresh quote and no recent bar"
    return price, str(tick.get("source") or "quote")


# ══════════════════════════════════════════════════════════════════════════
# Measurement — everything a human would look at, computed once
# ══════════════════════════════════════════════════════════════════════════

def _instrument_for(symbol: str):
    try:
        from instruments.models import Instrument
        return Instrument.objects.filter(symbol__iexact=symbol).first()
    except Exception:  # pragma: no cover
        return None


def _excursion(instrument, pos: dict, mark: float) -> tuple[Optional[float],
                                                             Optional[float]]:
    """(worst, best) traded price since entry, including the current mark.

    Including the mark matters for a position younger than one bar: without
    it a brand-new trade reports no excursion at all and the adverse-excursion
    trigger is structurally unable to fire on the day it is needed most.
    """
    worst = best = mark
    opened_at = pos.get("opened_at")
    if instrument is None or opened_at is None:
        return worst, best
    try:
        from django.db.models import Max, Min
        from market_data.models import PriceData
    except Exception:  # pragma: no cover
        return worst, best
    for tf in EXCURSION_TIMEFRAMES:
        # AGGREGATED, not sliced. This used to pull `.order_by("-timestamp")
        # [:400]` — the NEWEST 400 bars — and then take the extremes of that
        # window, while calling the answer "since entry". On the 1h feed 400
        # bars is about 17 trading days, and this changeset's own time-stop
        # ceilings run to 720 hours, so a month-old position silently had its
        # first week amputated. The trade that spikes to +3R in week one and
        # round-trips to +0.2R is exactly the trade `give_back` exists to
        # catch, and it was the trade the truncation hid. Max/Min in the
        # database reads the whole window and returns two numbers instead of
        # four hundred rows, so the correct answer is also the cheaper one.
        agg = (PriceData.objects
               .filter(instrument=instrument, timeframe=tf,
                       timestamp__gte=opened_at)
               .aggregate(hi=Max("high"), lo=Min("low")))
        hi, lo = _f(agg.get("hi")), _f(agg.get("lo"))
        if hi is None and lo is None:
            continue
        best_candidate = max([v for v in (hi, mark) if v is not None])
        worst_candidate = min([v for v in (lo, mark) if v is not None])
        if pos["dir_sign"] > 0:
            return worst_candidate, best_candidate
        # A short's worst excursion is the highest print, its best the
        # lowest — the mirror, not the same two numbers.
        return best_candidate, worst_candidate
    return worst, best


def _daily_closes(instrument, *, limit: int = VOL_WINDOW_BARS) -> list[float]:
    if instrument is None:
        return []
    try:
        from market_data.models import PriceData
    except Exception:  # pragma: no cover
        return []
    rows = list(PriceData.objects
                .filter(instrument=instrument, timeframe="1d")
                .order_by("-timestamp")[:limit]
                .values_list("timestamp", "close"))
    rows.reverse()  # oldest first — garch_lite_forecast walks forward
    return [c for c in (_f(c) for _, c in rows) if c is not None]


def _daily_closes_up_to(instrument, when, *, limit: int = VOL_WINDOW_BARS) -> list[float]:
    """Daily closes ending at `when` — the volatility the position was sized
    against, not the volatility it is living in now."""
    if instrument is None or when is None:
        return []
    try:
        from market_data.models import PriceData
    except Exception:  # pragma: no cover
        return []
    rows = list(PriceData.objects
                .filter(instrument=instrument, timeframe="1d",
                        timestamp__lte=when)
                .order_by("-timestamp")[:limit]
                .values_list("timestamp", "close"))
    rows.reverse()
    return [c for c in (_f(c) for _, c in rows) if c is not None]


def _regime_at(when):
    """(label, confidence) from the BrainReport that was current at `when`.

    The entry-time regime is not stamped on the trade, but the platform keeps
    every report with its timestamp — so "has the regime flipped since this
    opened" is answerable from the record we already have rather than needing
    new plumbing on the entry path.
    """
    if when is None:
        return None, None
    try:
        from .models import BrainReport
        report = (BrainReport.objects.filter(error="", created_at__lte=when)
                  .order_by("-created_at").first())
    except Exception:  # pragma: no cover
        return None, None
    if report is None:
        return None, None
    return report.regime_label, float(report.regime_confidence or 0)


def _setup_horizon_days(rule_name: str) -> Optional[int]:
    """The setup's own suggested_horizon_days, or None when unknown.

    None is a real answer and must not collapse to a default: a fabricated
    horizon would let the age trigger fire on setups that never claimed one.
    """
    if not rule_name:
        return None
    try:
        from signals.models_opportunity import OpportunitySetup
        row = (OpportunitySetup.objects.filter(name=rule_name)
               .values_list("suggested_horizon_days", flat=True).first())
        if row:
            return int(row)
    except Exception:  # pragma: no cover
        pass
    try:
        from .generator_models import GeneratedSetupProposal
        row = (GeneratedSetupProposal.objects.filter(name=rule_name)
               .values_list("suggested_horizon_days", flat=True).first())
        if row:
            return int(row)
    except Exception:  # pragma: no cover
        pass
    return None


def _origin_signal(pos: dict) -> Optional[dict]:
    """The Signal that most plausibly opened this position.

    There is no FK from either book to signals.Signal, so this matches on
    (instrument, rule_name) at or before the open. It is a heuristic and is
    labelled as one in the snapshot the model reads — a wrong thesis quoted
    confidently is worse than no thesis.
    """
    rule = pos.get("rule_name") or ""
    opened_at = pos.get("opened_at")
    if not rule or opened_at is None:
        return None
    try:
        from signals.models import Signal
        row = (Signal.objects
               .filter(instrument__symbol__iexact=pos["symbol"],
                       rule_name=rule, created_at__lte=opened_at)
               .order_by("-created_at")
               .values("id", "title", "score", "sub_scores", "direction",
                       "created_at").first())
    except Exception:  # pragma: no cover
        return None
    if not row:
        return None
    row["created_at"] = row["created_at"].isoformat()
    row["match"] = "heuristic: newest signal for this rule+symbol before entry"
    return row


def _rule_state(pos: dict) -> dict:
    """What the platform now thinks of the rule that opened this position."""
    rule = pos.get("rule_name") or ""
    state = {"rule_name": rule, "control_status": "", "advisory": "allow",
             "advisory_reason": "", "open_decay_alert": False}
    if not rule:
        return state
    try:
        from signals.models_control import RuleControl
        row = (RuleControl.objects.filter(rule_name=rule)
               .values("status", "promotion_stage").first())
        if row:
            state["control_status"] = row["status"]
            state["promotion_stage"] = row["promotion_stage"]
    except Exception:  # pragma: no cover
        pass
    try:
        from .context import brain_rule_advisory
        status, reason = brain_rule_advisory(rule)
        state["advisory"] = status
        state["advisory_reason"] = reason
    except Exception:  # pragma: no cover
        pass
    try:
        from bot_program.track_record_models import RuleTrackRecordAlert
        state["open_decay_alert"] = RuleTrackRecordAlert.objects.filter(
            rule_name=rule, resolved_at__isnull=True).exists()
    except Exception:  # pragma: no cover
        pass
    return state


def _macro_calendar_has_ever_run() -> bool:
    """Has anything ever written a macro event?

    `_imminent_events` derives {EUR, USD} from EURUSD and queries
    `currency_affected`, with a comment noting that "the currency carries
    the macro print that moves an FX leg". A repo-wide search finds exactly
    ONE non-test writer of EconomicEvent — the earnings scraper — and it
    stores the equity TICKER in that column. The field holds "AAPL", never
    "USD", so the forex branch cannot match a row, ever.

    An empty list from that query renders as "checked, nothing imminent",
    which is the reassuring answer to a question nobody asked. It ships on
    every forex position through NFP, CPI and FOMC.
    """
    from market_data.models import EconomicEvent
    try:
        return EconomicEvent.objects.filter(
            currency_affected__in=("USD", "EUR", "GBP", "JPY", "CHF",
                                   "CAD", "AUD", "NZD")).exists()
    except Exception:  # noqa: BLE001 — a blind marker must never raise
        return False


def _imminent_events(pos: dict) -> list[dict]:
    """High-impact calendar entries inside EVENT_HORIZON_HOURS for this symbol.

    Title match plus currency match: the title carries single-name earnings,
    the currency carries the macro print that moves an FX leg. Same table the
    earnings blackout reads, so the two cannot disagree about what is coming.
    """
    now = timezone.now()
    try:
        from django.db.models import Q
        from market_data.models import EconomicEvent
    except Exception:  # pragma: no cover
        return []
    symbol = pos["symbol"]
    currencies = set()
    if (pos.get("asset_class") or "").lower() == "forex":
        norm = symbol.replace("/", "").replace("_", "")
        if len(norm) == 6 and norm.isalpha():
            currencies = {norm[:3], norm[3:]}
    # A one-character symbol matches almost every headline, which would put a
    # permanent event flag on that position and train the operator to ignore
    # the trigger everywhere else.
    q = Q(title__icontains=symbol) if len(symbol) >= 2 else Q(pk__in=[])
    if currencies:
        q = q | Q(currency_affected__in=sorted(currencies))
    rows = list(EconomicEvent.objects
                .filter(q, impact__iexact=EVENT_IMPACT,
                        datetime__gte=now,
                        datetime__lte=now + timedelta(hours=EVENT_HORIZON_HOURS))
                .order_by("datetime")[:5]
                .values("title", "datetime", "impact", "currency_affected"))
    for r in rows:
        r["datetime"] = r["datetime"].isoformat() if r["datetime"] else None

    # BLIND, not clear. On a forex position the currency branch is the only
    # one that can match, and no macro source has ever written a row it
    # could match — the sole non-test writer of this table is the earnings
    # scraper, which stores the equity TICKER in `currency_affected`. So an
    # empty list here has been rendering as "checked, nothing imminent" on
    # every forex position, through NFP, CPI and FOMC.
    #
    # Naming the absence costs an hour and is the doctrine fix; sourcing a
    # real macro calendar is the separate, larger job.
    if not rows and currencies and not _macro_calendar_has_ever_run():
        return [{
            "title": "NO MACRO CALENDAR SOURCE HAS EVER RUN",
            "datetime": None, "impact": EVENT_IMPACT,
            "currency_affected": "/".join(sorted(currencies)),
            "blind": True,
            "note": ("event risk on this pair is UNCHECKED, not clear — "
                     "nothing has ever written a macro event"),
        }]
    return rows


def _overlap_index() -> dict:
    """{(symbol, side): [rules]} — the Phase-52 position-overlap audit, once.

    Computed for the whole pass rather than per position: the detector walks
    every open trade, so calling it inside the loop would make a pass over N
    positions do N full scans of the same table.
    """
    index: dict = {}
    try:
        from .correlation_audit import detect_position_overlap
        for row in detect_position_overlap(min_overlap=OVERLAP_MIN_RULES):
            key = ((row.get("symbol") or "").upper(), row.get("side"))
            index[key] = row.get("rules") or []
    except Exception:  # pragma: no cover
        pass
    return index


def _concentration(pos: dict, cache: Optional[dict] = None) -> dict:
    """How much of the book is expressing this position's bet.

    Three independent readings, because they catch different failures:
    the orchestrator's own net theme exposure (the number the entry gate
    already enforces), the brain's theme pressure (its 0..1 saturation read),
    and rule-level position overlap from the Phase-52 correlation audit
    (several rules holding the same symbol and side).

    `cache` holds the two book-wide reads (per-user exposure, the overlap
    index) so a pass over N positions does not recompute them N times.
    """
    cache = {} if cache is None else cache
    out = {"themes": {}, "dominant_theme": "", "dominant_exposure": None,
           "brain_pressure": None, "overlap_rules": []}
    try:
        from bot_program.orchestrator import classify_position
        contrib = classify_position(pos.get("asset_class", ""), pos["symbol"],
                                    pos["side"])
    except Exception:  # pragma: no cover
        contrib = {}
    user = pos.get("user")
    exposures = {}
    if user is not None:
        by_user = cache.setdefault("exposures", {})
        if user.pk not in by_user:
            try:
                from bot_program.orchestrator import current_exposures
                by_user[user.pk] = (
                    (current_exposures(user) or {}).get("themes", {}) or {})
            except Exception:  # pragma: no cover
                by_user[user.pk] = {}
        exposures = by_user[user.pk]
    out["themes"] = {k: round(float(v), 3) for k, v in exposures.items()}

    # The dominant theme is the one this position actually contributes to,
    # scored by how loaded the whole book already is on it.
    best_key, best_val = "", None
    for key, own in (contrib or {}).items():
        if not own:
            continue
        net = exposures.get(key)
        if net is None:
            continue
        if best_val is None or abs(net) > abs(best_val):
            best_key, best_val = key, float(net)
    out["dominant_theme"] = best_key
    out["dominant_exposure"] = round(best_val, 3) if best_val is not None else None

    try:
        from .context import get_brain_context
        ctx = get_brain_context() or {}
        pressures = ctx.get("theme_pressures") or {}
        if best_key and best_key in pressures:
            out["brain_pressure"] = float(pressures[best_key])
        elif pressures:
            out["brain_pressure"] = max(float(v) for v in pressures.values())
    except Exception:  # pragma: no cover
        pass

    if "overlap" not in cache:
        cache["overlap"] = _overlap_index()
    out["overlap_rules"] = cache["overlap"].get((pos["symbol"], pos["side"]), [])
    return out


def _self_hedge(pos: dict, cache: Optional[dict] = None) -> list[dict]:
    """Open positions on this symbol pointing the OTHER way.

    The overlap audit `_concentration` reads asks "how many rules hold this
    same symbol and side" — the doubling-up case. It cannot see the opposite
    one, and the opposite one is the more expensive mistake: a long and a
    short on the same instrument are flat, and flat still pays two spreads,
    two sets of costs and two stop distances to sit there. It also makes the
    risk engine count two positions where the net exposure is zero.

    Found in the live book before this existed: USDCHF held BUY by one rule
    and SELL by another, at the same time, by the same operator.

    Scoped to ONE owner's book. Two different users each running their own
    side of a pair is not a hedge, it is two people trading.

    A consequence worth stating rather than discovering: legacy
    portfolio.Position rows carry no owner (that book has no user FK), so
    they group under a single ownerless key. Two opposing legacy rows DO
    flag each other — correct, it is one shared book — but a bot position
    is never matched against a legacy one. Closing that gap needs an owner
    on the legacy book, not a looser test here; a looser test would flag one
    operator's long against another's short.
    """
    cache = {} if cache is None else cache
    if "book_by_symbol" not in cache:
        index: dict = {}
        for row in open_positions():
            key = (getattr(row.get("user"), "pk", None), row["symbol"])
            index.setdefault(key, []).append(row)
        cache["book_by_symbol"] = index
    key = (getattr(pos.get("user"), "pk", None), pos["symbol"])
    mine = pos["side"]
    return [
        {"book": row["book"], "position_id": row["position_id"],
         "side": row["side"], "rule_name": row.get("rule_name", ""),
         "qty": row.get("qty")}
        for row in cache["book_by_symbol"].get(key, [])
        if row["side"] != mine
        and not (row["book"] == pos["book"]
                 and row["position_id"] == pos["position_id"])
    ]


def measure(pos: dict, cache: Optional[dict] = None) -> dict:
    """Every fact the triggers read, computed once per position.

    Returns a dict that is JSON-serialisable as-is, because it is persisted
    verbatim as the evidence behind whatever verdict follows.

    `cache` is the per-pass memo for the book-wide reads; omit it and every
    lookup is done fresh, which is what a single-position caller wants.
    """
    now = timezone.now()
    cache = {} if cache is None else cache
    mark, mark_source = usable_mark(pos["symbol"])
    instrument = _instrument_for(pos["symbol"])

    facts: dict = {
        "as_of": now.isoformat(),
        "book": pos["book"],
        "position_id": pos["position_id"],
        "symbol": pos["symbol"],
        "side": pos["side"],
        "asset_class": pos.get("asset_class", ""),
        "venue": "paper" if pos.get("paper") else "live",
        "status": pos.get("status", ""),
        "qty": pos.get("qty"),
        "entry": pos.get("entry"),
        "initial_stop": pos.get("initial_stop"),
        "stop": pos.get("stop"),
        "target": pos.get("target"),
        "rule_name": pos.get("rule_name", ""),
        "entry_reason": (pos.get("reason") or "")[:1000],
        "mark": mark,
        "mark_source": mark_source,
        "stale_quote": mark is None,
        # Everything below stays None when it cannot be measured. None is
        # rendered as an em-dash upstream; a 0 here would read as a fact.
        "unrealized_r": None, "r_to_stop": None, "r_to_target": None,
        "mae_r": None, "mfe_r": None, "risk_per_unit": None,
        "age_hours": 0.0, "age_days": 0.0,
        "horizon_days": _setup_horizon_days(pos.get("rule_name", "")),
    }

    opened_at = pos.get("opened_at")
    if opened_at is not None:
        age_hours = max(0.0, (now - opened_at).total_seconds() / 3600.0)
        facts["age_hours"] = round(age_hours, 2)
        facts["age_days"] = round(age_hours / 24.0, 3)
        facts["opened_at"] = opened_at.isoformat()

    if mark is None:
        # Deliberately incomplete: no R, no excursion, no regime comparison.
        # Everything downstream is arithmetic on a price, and there is no
        # price. Saying "no verdict" is the whole content of this row.
        facts["no_verdict_reason"] = (
            f"no usable mark for {pos['symbol']} — {mark_source}")
        return facts

    entry = pos.get("entry")
    initial_stop = pos.get("initial_stop")
    sign = pos["dir_sign"]
    risk = None
    if entry is not None and initial_stop is not None:
        risk = abs(entry - initial_stop)
        if risk <= 0:
            risk = None
    facts["risk_per_unit"] = risk

    if risk and entry is not None:
        facts["unrealized_r"] = round(sign * (mark - entry) / risk, 4)
        if pos.get("stop") is not None:
            facts["r_to_stop"] = round(sign * (mark - pos["stop"]) / risk, 4)
        if pos.get("target") is not None:
            facts["r_to_target"] = round(sign * (pos["target"] - mark) / risk, 4)
        worst, best = _excursion(instrument, pos, mark)
        if worst is not None:
            facts["mae_r"] = round(sign * (worst - entry) / risk, 4)
        if best is not None:
            facts["mfe_r"] = round(sign * (best - entry) / risk, 4)

    # Regime then vs now.
    entry_regime, entry_conf = _regime_at(opened_at)
    now_regime, now_conf = _regime_at(now)
    facts["regime_at_entry"] = entry_regime
    facts["regime_confidence_at_entry"] = entry_conf
    facts["regime_now"] = now_regime
    facts["regime_confidence_now"] = now_conf
    try:
        from .context import brain_trust_band
        facts["brain_trust_band"] = brain_trust_band()
    except Exception:  # pragma: no cover
        facts["brain_trust_band"] = "unknown"

    # Volatility then vs now.
    facts["vol_now"] = facts["vol_at_entry"] = facts["vol_ratio"] = None
    try:
        from signals.quant_primitives import garch_lite_forecast
        sigma_now = garch_lite_forecast(_daily_closes(instrument))
        sigma_entry = garch_lite_forecast(
            _daily_closes_up_to(instrument, opened_at))
        facts["vol_now"] = round(sigma_now, 6) if sigma_now else None
        facts["vol_at_entry"] = round(sigma_entry, 6) if sigma_entry else None
        if sigma_now and sigma_entry and sigma_entry > 0:
            facts["vol_ratio"] = round(sigma_now / sigma_entry, 4)
    except Exception:  # pragma: no cover
        pass

    facts["rule_state"] = _rule_state(pos)
    facts["imminent_events"] = _imminent_events(pos)
    facts["concentration"] = _concentration(pos, cache)
    facts["self_hedge"] = _self_hedge(pos, cache)
    facts["origin_signal"] = _origin_signal(pos)
    return facts


# ══════════════════════════════════════════════════════════════════════════
# Triggers
# ══════════════════════════════════════════════════════════════════════════

def _t(code: str, severity: float, text: str, **values) -> dict:
    return {"code": code, "severity": round(float(severity), 3),
            "text": text, "values": values}


def evaluate_triggers(facts: dict) -> list[dict]:
    """The reasons, if any, a human would reconsider this position now.

    Empty list means the deterministic pass found nothing worth paying a
    model to think about — which is the common case and the whole point of
    having this layer in front of the expensive one.
    """
    if facts.get("stale_quote"):
        # Not "no triggers": no evaluation at all happened. Returning [] here
        # is what stops a stale row from being read as a clean bill of health.
        return []

    fired: list[dict] = []
    ur = facts.get("unrealized_r")
    mfe = facts.get("mfe_r")
    mae = facts.get("mae_r")
    r_stop = facts.get("r_to_stop")
    r_target = facts.get("r_to_target")

    # T1 — a won trade giving its winnings back.
    if ur is not None and mfe is not None and mfe >= GIVE_BACK_MIN_MFE_R:
        if ur <= mfe * GIVE_BACK_FRACTION:
            given = mfe - ur
            fired.append(_t(
                "give_back", min(1.0, 0.4 + given / max(mfe, 1e-9) * 0.6),
                f"Peaked at +{mfe:.2f}R and is back to {ur:+.2f}R — more than "
                f"half the open profit has been handed back.",
                mfe_r=mfe, unrealized_r=ur, given_back_r=round(given, 4)))

    # T2 — the forward leg has inverted: risking more than is left to win.
    if (r_stop is not None and r_target is not None
            and r_target > 0 and r_stop > 0
            and r_stop > r_target * RISK_REWARD_INVERSION):
        fired.append(_t(
            "risk_exceeds_reward",
            min(1.0, 0.35 + min(r_stop / max(r_target, 1e-9), 6.0) / 12.0),
            f"{r_stop:.2f}R still at risk to the stop against {r_target:.2f}R "
            f"left to the target — the remaining leg is upside-down.",
            r_to_stop=r_stop, r_to_target=r_target))

    # T3 — deep adverse excursion with nothing to show for it.
    if mae is not None and mae <= ADVERSE_EXCURSION_R and (ur is None or ur <= 0):
        fired.append(_t(
            "adverse_excursion", min(1.0, 0.4 + abs(mae) * 0.4),
            f"Has been {mae:.2f}R against entry since it opened and is still "
            f"{'—' if ur is None else f'{ur:+.2f}R'} — the thesis has paid nothing.",
            mae_r=mae, unrealized_r=ur))

    # T4 — the stop is about to decide this, or already should have.
    # A NEGATIVE r_to_stop means the mark is through the stop and the position
    # is still open: the bracket did not fill, or the row is CLOSE_PENDING at
    # a broker that still holds it. That is louder than "nearly there", not
    # quieter, so it fires here rather than falling outside the band.
    if r_stop is not None and r_stop <= NEAR_LEVEL_R:
        if r_stop < 0:
            fired.append(_t(
                "near_stop", 1.0,
                f"The mark is {abs(r_stop):.2f}R BEYOND the stop and the "
                f"position is still open — the mechanical exit did not fire.",
                r_to_stop=r_stop, through_stop=True))
        else:
            fired.append(_t(
                "near_stop", min(1.0, 0.6 + (NEAR_LEVEL_R - r_stop)),
                f"Only {r_stop:.2f}R from the stop — the mechanical exit is "
                f"about to make this decision.",
                r_to_stop=r_stop, through_stop=False))

    # T5 — the target is about to decide this, or already should have.
    if r_target is not None and r_target <= NEAR_LEVEL_R:
        if r_target < 0:
            fired.append(_t(
                "near_target", 0.8,
                f"The mark is {abs(r_target):.2f}R past the target and the "
                f"position is still open — the profit is unbooked.",
                r_to_target=r_target, through_target=True))
        else:
            fired.append(_t(
                "near_target", min(1.0, 0.45 + (NEAR_LEVEL_R - r_target)),
                f"Only {r_target:.2f}R from the target — take-part or "
                f"let-it-run has to be answered before the bracket answers it.",
                r_to_target=r_target, through_target=False))

    # T6 — the setup's own clock has run out and nothing happened.
    horizon = facts.get("horizon_days")
    age_days = facts.get("age_days") or 0.0
    if horizon and age_days > float(horizon):
        if ur is None or abs(ur) <= HORIZON_FLAT_BAND_R:
            fired.append(_t(
                "horizon_exceeded",
                min(1.0, 0.35 + (age_days / float(horizon) - 1.0) * 0.3),
                f"Day {age_days:.1f} of a setup that asked for {horizon} and "
                f"it is flat at {'—' if ur is None else f'{ur:+.2f}R'} — the "
                f"clock has refuted it.",
                age_days=age_days, horizon_days=horizon, unrealized_r=ur))

    # T7 — the world changed under the position.
    entry_regime = facts.get("regime_at_entry")
    now_regime = facts.get("regime_now")
    now_conf = facts.get("regime_confidence_now") or 0.0
    if (entry_regime and now_regime and entry_regime != now_regime
            and now_regime != "unknown" and entry_regime != "unknown"
            and now_conf >= REGIME_FLIP_MIN_CONFIDENCE):
        fired.append(_t(
            "regime_flip", min(1.0, 0.35 + now_conf * 0.5),
            f"Opened in a {entry_regime} regime; the brain now reads "
            f"{now_regime} at {now_conf:.2f} confidence "
            f"(trust: {facts.get('brain_trust_band', 'unknown')}).",
            regime_at_entry=entry_regime, regime_now=now_regime,
            confidence=now_conf))

    # T8 — the market got louder than the size assumed.
    ratio = facts.get("vol_ratio")
    if ratio is not None and ratio >= VOL_EXPANSION_RATIO:
        fired.append(_t(
            "vol_expansion", min(1.0, 0.3 + (ratio - 1.0) * 0.3),
            f"Forecast volatility is {ratio:.2f}x what it was at entry — the "
            f"stop is the same distance in price and much closer in vol.",
            vol_ratio=ratio, vol_now=facts.get("vol_now"),
            vol_at_entry=facts.get("vol_at_entry")))

    # T9 — a gap is coming and there is still time to act before it.
    events = facts.get("imminent_events") or []
    if events:
        fired.append(_t(
            "event_imminent", 0.6,
            f"{len(events)} high-impact event(s) inside {EVENT_HORIZON_HOURS}h: "
            f"{'; '.join(e.get('title', '')[:60] for e in events[:2])}.",
            events=events))

    # T10 — the rule holding this capital has already been judged.
    rs = facts.get("rule_state") or {}
    reasons = []
    if rs.get("control_status") in ("paused", "reduced"):
        reasons.append(f"RuleControl says {rs['control_status']}")
    if rs.get("advisory") == "pause_recommended":
        reasons.append("the brain recommends pausing it")
    if rs.get("open_decay_alert"):
        reasons.append("an unresolved track-record decay alert is open")
    if reasons:
        fired.append(_t(
            "rule_decayed", 0.7,
            f"The rule that opened this ({rs.get('rule_name') or '—'}) has "
            f"since been judged: {', '.join(reasons)}.",
            rule_state=rs))

    # T11 — several positions saying the same thing.
    conc = facts.get("concentration") or {}
    exposure = conc.get("dominant_exposure")
    pressure = conc.get("brain_pressure")
    overlap = conc.get("overlap_rules") or []
    conc_reasons = []
    if exposure is not None and abs(exposure) >= THEME_EXPOSURE_LIMIT:
        conc_reasons.append(
            f"net {conc.get('dominant_theme')} exposure {exposure:+.1f} is at "
            f"the level the entry gate already refuses to add to")
    if pressure is not None and pressure >= THEME_PRESSURE_LIMIT:
        conc_reasons.append(f"brain theme pressure {pressure:.2f}")
    if len(overlap) >= OVERLAP_MIN_RULES:
        conc_reasons.append(
            f"{len(overlap)} rules hold this same symbol and side "
            f"({', '.join(overlap[:3])})")
    if conc_reasons:
        fired.append(_t(
            "concentration", 0.65,
            f"This is not an independent bet: {'; '.join(conc_reasons)}.",
            **{k: v for k, v in conc.items() if k != "themes"}))

    # T12 — the book is holding both sides of the same instrument.
    # Severity above concentration because this one is not a judgement call
    # about correlation: the two positions are literally flat against each
    # other, and flat still pays both spreads, both cost models and both
    # stop distances to sit there. Whichever leg goes, going costs less than
    # staying.
    hedges = facts.get("self_hedge") or []
    if hedges:
        against = "; ".join(
            f"#{h['position_id']} {h['side']} via {h.get('rule_name') or '—'}"
            for h in hedges[:3])
        fired.append(_t(
            "self_hedge", 0.75,
            f"The book is {facts.get('side')} this symbol here and the other "
            f"way in {len(hedges)} other position(s) — {against}. The pair is "
            f"flat and paying both spreads to stay that way.",
            opposing=hedges))

    return fired


# ══════════════════════════════════════════════════════════════════════════
# Fingerprint — what makes "the same facts" mean something
# ══════════════════════════════════════════════════════════════════════════

def _bucket(value, step: float):
    """Round to a step, or None. Bucketing is the point: raw floats move on
    every tick, so a fingerprint built from them would differ every cycle and
    the model pass would re-answer the identical question forever."""
    v = _f(value)
    if v is None:
        return None
    return round(round(v / step) * step, 4)


def facts_fingerprint(facts: dict, triggers: list[dict]) -> str:
    """A stable hash of the facts as a human would summarise them."""
    conc = facts.get("concentration") or {}
    rs = facts.get("rule_state") or {}
    payload = {
        "key": f"{facts.get('book')}:{facts.get('position_id')}",
        "codes": sorted(t.get("code", "") for t in triggers),
        # Quarter-R buckets: a position has to move a meaningful fraction of
        # its own risk before it is a new question.
        "ur": _bucket(facts.get("unrealized_r"), 0.25),
        "stop": _bucket(facts.get("r_to_stop"), 0.25),
        "target": _bucket(facts.get("r_to_target"), 0.25),
        "mae": _bucket(facts.get("mae_r"), 0.25),
        "mfe": _bucket(facts.get("mfe_r"), 0.25),
        # Whole days: a position does not become a new question every hour.
        "age": int(facts.get("age_days") or 0),
        "regime": facts.get("regime_now"),
        "vol": _bucket(facts.get("vol_ratio"), 0.25),
        "rule": f"{rs.get('control_status', '')}/{rs.get('advisory', '')}"
                f"/{int(bool(rs.get('open_decay_alert')))}",
        "events": len(facts.get("imminent_events") or []),
        "overlap": len(conc.get("overlap_rules") or []),
        "hedge": len(facts.get("self_hedge") or []),
        "theme": _bucket(conc.get("dominant_exposure"), 1.0),
    }
    blob = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# ══════════════════════════════════════════════════════════════════════════
# The pass
# ══════════════════════════════════════════════════════════════════════════

def deterministic_pass() -> list[dict]:
    """Measure every open position and emit one structured verdict each.

    Returns a list of {position, facts, triggers, severity, facts_hash,
    stale_quote}, sorted worst-first so the caller's budget is spent on the
    positions that most need it. Costs nothing and calls no model.
    """
    verdicts: list[dict] = []
    cache: dict = {}  # book-wide reads computed once for the whole pass
    for pos in open_positions():
        try:
            facts = measure(pos, cache)
            triggers = evaluate_triggers(facts)
        except Exception as e:  # noqa: BLE001 — one bad row must not blind the pass
            logger.warning("[position-review] measuring %s:%s failed: %s",
                           pos.get("book"), pos.get("position_id"), e)
            continue
        severity = max((float(t.get("severity") or 0) for t in triggers),
                       default=0.0)
        verdicts.append({
            "position": pos,
            "facts": facts,
            "triggers": triggers,
            "severity": round(severity, 3),
            "stale_quote": bool(facts.get("stale_quote")),
            "facts_hash": facts_fingerprint(facts, triggers),
        })
    verdicts.sort(key=lambda v: v["severity"], reverse=True)
    return verdicts


# ══════════════════════════════════════════════════════════════════════════
# Read side — what the position hover card consumes
# ══════════════════════════════════════════════════════════════════════════

# A flag older than this is history, not advice: the facts that raised it have
# had a full day to change and nothing re-raised it.
CARD_TTL_HOURS = 24


def latest_verdicts(*, keys=None, user=None,
                     ttl_hours: int = CARD_TTL_HOURS) -> dict:
    """{position_key: card_payload} for the freshest review per position.

    This is the whole contract the position hover card needs — it does not
    import this module's internals and it never recomputes anything. Keys are
    "bot:<AssetBotTrade.id>" and "pf:<portfolio.Position.id>".

    A position with no live review is simply absent from the dict, which is
    the correct render: nothing to say.
    """
    from .position_review_models import PositionReview

    qs = PositionReview.objects.filter(
        created_at__gte=timezone.now() - timedelta(hours=max(1, int(ttl_hours))))
    if user is not None:
        qs = qs.filter(user=user)
    if keys:
        wanted = set(keys)
        pairs = [k.split(":", 1) for k in wanted if ":" in k]
        if not pairs:
            return {}
        from django.db.models import Q
        clause = Q()
        for book, pid in pairs:
            try:
                clause |= Q(book=book, position_id=int(pid))
            except (TypeError, ValueError):
                continue
        qs = qs.filter(clause)

    out: dict = {}
    # Ordered newest-last so the newest row wins the key it lands on.
    for review in qs.order_by("created_at"):
        out[review.position_key] = review.card_payload()
    return out
