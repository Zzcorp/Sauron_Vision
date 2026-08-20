"""Phase-17 reinforcement loop — bot-trade self-grading.

Phase-1 already grades Signals (signals/grading.py). This module does the
same for AssetBotTrade rows: the bots learn whether each rule_name actually
worked *for them* — which can differ from how it worked at the signal level.

Key idea:
  Signal grading answers "did this signal eventually move favourably?"
  Bot-trade grading answers "did this rule produce profitable trades when
  the bot acted on it, given its sizing, gating, and execution slippage?"

A rule can grade well at the signal level but poorly at the bot level if:
  - the bot's stop placement keeps getting whipsawed
  - position sizing was wrong for the volatility regime
  - the rule fires on signals that materialise too slowly to hit TP

`grade_bot_trade(trade)` is called from `_close_trade` in AssetBot. It sets:
  - outcome ∈ {hit_target, stopped_out, manual_close, expired, time_stop}
  - realized_r (P&L normalised by initial risk = |entry - stop_loss| × qty)
  - duration_minutes

`bot_performance_summary(rule_name=, asset_class=, days=180, venue=)`
aggregates the graded population and returns win_rate / expectancy / count
for a rule on a given asset class, optionally restricted to one venue.

`bot_trade_track_record(rule_name, asset_class, min_n=10, venue=)` returns a
confidence multiplier in [0.5, 1.5] — used by AssetBot.decide() when the
config opts in via `extras["use_bot_track_record"]=True`.
`bot_track_record_detail(...)` is the same computation with the reasoning
attached, so a neutral 1.0 can be told apart from a measured 1.0.

`paper_live_expectancy_gap(...)` reports how much of a rule's measured edge
survives real execution.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal
from typing import Optional

from django.utils import timezone

logger = logging.getLogger(__name__)


# ── Venues ───────────────────────────────────────────────────────────────
# Paper and live are two different measurements of the same rule, not two
# samples of one measurement. A paper fill is charged a modelled half-spread
# on both sides (risk_levels.paper_fill_price) and has no resting stop at a
# broker; a live fill books the raw mark against a real bracket that can be
# hit intrabar. The two therefore produce different realized_r distributions
# by construction, and their average describes neither venue — which is fine
# for a dashboard that wants "everything this rule has ever done" and wrong
# for anything that sizes or directs real money.
VENUE_LIVE = "live"
VENUE_PAPER = "paper"
VENUE_ALL = "all"      # pooled — the dashboards' question, not the book's
_VENUES = (VENUE_LIVE, VENUE_PAPER, VENUE_ALL)

# No boost, no penalty. Returned whenever the venue's evidence is absent or
# too thin to act on — the honest answer there is "I have not measured this",
# which multiplies to 1.0 and comes with a reason attached rather than
# silently borrowing the other venue's number.
NEUTRAL_MULTIPLIER = 1.0


def _venue_filter(qs, venue: str):
    """Narrow `qs` to one execution venue. Raises on an unknown venue.

    Raising rather than defaulting: a typo'd venue that quietly pooled would
    reinstate exactly the bug this argument exists to prevent, and it would
    do so invisibly.

    This raise is the ledger's own backstop and it fires for every direct
    caller — dashboards, the promotion ladder, `bot_track_record_detail`. It
    is NOT what protects the decision path: `aggregation.rule_weight` decides
    the venue before it ever gets here and validates it there, because its
    own guard would skip this query and its own `except` would log the
    failure away. Two layers, and the one nearest the money is the one that
    has to be reachable.
    """
    if venue not in _VENUES:
        raise ValueError(
            f"venue must be one of {_VENUES}, got {venue!r}")
    if venue == VENUE_LIVE:
        return qs.filter(paper=False)
    if venue == VENUE_PAPER:
        return qs.filter(paper=True)
    return qs


# ── Per-trade grading ────────────────────────────────────────────────────

def grade_bot_trade(trade) -> bool:
    """Compute outcome/realized_r/duration_minutes on a closed trade.

    Returns True on success, False on degenerate input. Idempotent — calling
    twice on the same trade just overwrites the same values.

    Outcome rules:
      - exit_price ≥ take_profit (BUY) or ≤ TP (SELL)        → hit_target
      - exit_price ≤ stop_loss (BUY) or ≥ SL (SELL)          → stopped_out
      - reason contains 'EXPIRY_CLOSE' (options, Phase 14)   → expired
      - reason contains 'closed:TIME' (the time stop)        → time_stop
      - else                                                  → manual_close
    """
    if trade.status != "CLOSED" or trade.exit_price is None:
        return False

    entry = float(trade.entry_price or 0)
    exit_p = float(trade.exit_price or 0)
    # The INITIAL stop, not the current one: a trailing stop mutates
    # trade.stop_loss, and grading against the trailed value makes pnl and
    # risk the same quantity — every trailing exit would score ~1.0R no
    # matter the true multiple, inflating the track record that sizes live
    # positions. entry_meta records the stop the trade was opened with.
    # Two different stops, for two different questions.
    #   effective_sl — where the stop actually sat when the trade closed.
    #     This is what classifies the OUTCOME: a trade closed at its trailed
    #     stop was stopped out, and labelling it manual_close would misreport
    #     it in the audit log, the notifications and every dashboard.
    #   sl — the stop the trade OPENED with, which is the risk it was taken
    #     with and therefore the only correct denominator for realized_r.
    # Before the split these were one variable, so grading against the
    # trailed stop made pnl and risk the same quantity and every trailing
    # exit scored ~1.0R.
    effective_sl = float(trade.stop_loss) if trade.stop_loss is not None else 0.0
    sl = effective_sl
    _initial_sl = (trade.metadata or {}).get("initial_stop_loss")
    if _initial_sl is not None:
        try:
            sl = float(_initial_sl)
        except (TypeError, ValueError):
            pass
    tp = float(trade.take_profit) if trade.take_profit is not None else 0.0
    qty = float(trade.qty or 0)

    # ── duration ─────────────────────────────────────────────────
    if trade.opened_at and trade.closed_at:
        delta = trade.closed_at - trade.opened_at
        trade.duration_minutes = max(0, int(delta.total_seconds() / 60))

    # ── outcome ──────────────────────────────────────────────────
    side = (trade.side or "").upper()
    outcome = "manual_close"
    reason = trade.reason or ""

    # Prefer the reason the bot recorded over re-deriving it from the exit
    # price. `_close_trade` already knows whether the mark crossed the stop
    # or the target; inferring it again from the FILL is unreliable, because
    # the fill includes costs and can land a hair the wrong side of a level
    # the trade genuinely reached. The outcome describes why the position
    # closed; pnl describes what was actually received. Conflating them
    # turned take-profit exits into "manual_close".
    if "EXPIRY_CLOSE" in reason:
        outcome = "expired"
    elif "closed:TIME" in reason:
        # The time stop, and nothing else. Without this branch the exit fell
        # through to the price comparisons below and graded `manual_close` —
        # the engine's own risk decision recorded as an operator's, in the
        # audit log, the notification icon and every dashboard. It also hid
        # the one thing the exit is evidence FOR: a rule whose trades keep
        # timing out fires on moves that never materialise, which is a fault
        # in the entry or the horizon, not in the stop. `expired` would have
        # been closer but is already the options expiry gate's answer, and
        # a contract running out is a different event from a thesis doing
        # nothing.
        outcome = "time_stop"
    elif "closed:TP" in reason:
        outcome = "hit_target"
    elif "closed:SL" in reason:
        outcome = "stopped_out"
    elif side == "BUY":
        if tp and exit_p >= tp:
            outcome = "hit_target"
        elif effective_sl and exit_p <= effective_sl:
            outcome = "stopped_out"
    elif side == "SELL":
        if tp and exit_p <= tp:
            outcome = "hit_target"
        elif effective_sl and exit_p >= effective_sl:
            outcome = "stopped_out"
    trade.outcome = outcome

    # ── realized_r ───────────────────────────────────────────────
    # R-multiple = P&L / initial_risk_dollars
    # initial_risk_dollars = |entry - stop_loss| × qty
    if sl > 0 and entry > 0 and qty > 0:
        risk_per_unit = abs(entry - sl)
        if risk_per_unit > 0:
            risk_dollars = risk_per_unit * qty
            if trade.asset_class == "options":
                # Options pnl is dollar-denominated (premium × qty × contract
                # multiplier); scale the risk the same way or R is inflated
                # by the multiplier (~100×).
                try:
                    from bot_program.asset_engine.options_bot import option_pnl_multiplier
                    risk_dollars *= float(option_pnl_multiplier(trade))
                except Exception:
                    pass
            elif trade.asset_class == "forex":
                # Forex pnl is converted to USD at the trade's entry-time
                # rate; the risk here is |entry - stop| × qty, a QUOTE-
                # currency amount. Scale it by the SAME rate or realized_r
                # is true_R × rate — a JPY stop-out would grade at −0.0067
                # instead of −1.0 and the promotion evidence goes blind.
                try:
                    from bot_program.asset_engine.forex_bot import forex_usd_multiplier
                    risk_dollars *= float(forex_usd_multiplier(trade))
                except Exception:
                    pass
            if risk_dollars > 0:
                pnl = float(trade.pnl or 0)
                trade.realized_r = round(pnl / risk_dollars, 4)

    trade.save(update_fields=["outcome", "realized_r", "duration_minutes"])
    return True


# ── Aggregate stats per rule × asset_class ───────────────────────────────

def bot_performance_summary(*, rule_name: Optional[str] = None,
                             asset_class: Optional[str] = None,
                             days: int = 180,
                             min_n: int = 1,
                             user=None,
                             since=None,
                             venue: str = VENUE_ALL) -> list[dict]:
    """Return per-(rule_name, asset_class) stats for closed bot trades within
    the last `days`. Filterable by rule_name, asset_class, user, venue, or an
    explicit `since` datetime that overrides `days`.

    Each row:
        {rule_name, asset_class, venue, n, n_wins, n_losses, win_rate,
         avg_r, expectancy, avg_duration_min, last_traded_at}

    "n" here is *graded* trades only — open trades and not-yet-graded closes
    are excluded.

    `venue` is one of VENUE_LIVE / VENUE_PAPER / VENUE_ALL and defaults to
    the pooled row, which is what the dashboards and the promotion ladder
    ask for. Anything that weights or sizes a real order must name the venue
    it is about to trade on — see `bot_track_record_detail`. The chosen
    venue is echoed back in every row so a caller can never mistake a pooled
    number for a single-venue one; that was the silent half of the bug.
    """
    from .models import AssetBotTrade
    cutoff = since if since is not None else timezone.now() - timedelta(days=days)
    # `time_stop` belongs in the population, not outside it. An outcome
    # missing from this list is invisible to expectancy, to the promotion
    # ladder and to every dashboard that reads this — and a rule that keeps
    # timing out is precisely the one whose measured expectancy should be
    # falling. Dropping it would let a rule with a flat record be judged on
    # only the trades that happened to reach a level.
    qs = (AssetBotTrade.objects
          .filter(status="CLOSED", closed_at__gte=cutoff,
                   outcome__in=["hit_target", "stopped_out", "manual_close",
                                 "expired", "time_stop"])
          .exclude(rule_name=""))
    qs = _venue_filter(qs, venue)
    if rule_name:
        qs = qs.filter(rule_name=rule_name)
    if asset_class:
        qs = qs.filter(asset_class=asset_class)
    if user is not None:
        qs = qs.filter(config__user=user)

    buckets: dict[tuple[str, str], list] = defaultdict(list)
    for t in qs.only("rule_name", "asset_class", "outcome", "realized_r",
                       "duration_minutes", "closed_at"):
        if t.realized_r is None:
            continue
        buckets[(t.rule_name, t.asset_class)].append(t)

    rows = []
    for (rn, ac), trades in buckets.items():
        n = len(trades)
        if n < min_n:
            continue
        wins = sum(1 for t in trades if t.realized_r is not None and t.realized_r > 0)
        losses = sum(1 for t in trades if t.realized_r is not None and t.realized_r < 0)
        avg_r = sum((t.realized_r or 0) for t in trades) / n
        # Expectancy in R-multiples — same as average since each trade is 1R-normalised.
        expectancy = avg_r
        durations = [t.duration_minutes for t in trades if t.duration_minutes is not None]
        avg_dur = sum(durations) / len(durations) if durations else None
        rows.append({
            "rule_name": rn,
            "asset_class": ac,
            "venue": venue,
            "n": n,
            "n_wins": wins,
            "n_losses": losses,
            "win_rate": round(wins / n, 4) if n else 0,
            "avg_r": round(avg_r, 4),
            "expectancy": round(expectancy, 4),
            "avg_duration_min": int(avg_dur) if avg_dur else None,
            "last_traded_at": max(t.closed_at for t in trades),
        })
    rows.sort(key=lambda r: -r["n"])
    return rows


# ── Confidence multiplier (feedback into decide()) ───────────────────────

def bot_track_record_detail(rule_name: str, asset_class: str,
                             *, days: int = 180, min_n: int = 10,
                             floor: float = 0.5, ceiling: float = 1.5,
                             venue: str = VENUE_ALL) -> dict:
    """The confidence multiplier plus the reasoning that produced it.

    Returns:
        {multiplier, venue, n, win_rate, expectancy, measured, reason}

    `measured` is True only when the multiplier was computed from `min_n` or
    more closed trades ON `venue`. When it is False the multiplier is exactly
    NEUTRAL_MULTIPLIER and `reason` says why — the caller can log it, and a
    reviewer reading a 1.0 in the ledger can tell "no evidence" apart from
    "evidence that came out neutral". A bare float cannot carry that, which
    is why this function exists alongside `bot_trade_track_record`.

    Cold start is the case that matters. A rule newly promoted to live has a
    fat paper record and zero live closes; asking for VENUE_LIVE returns n=0
    and a neutral 1.0, NOT the paper multiplier (which would let simulated
    fills size the first real order) and NOT 0.0 (which would silently veto
    every rule on its first live day). `win_rate` and `expectancy` are None
    there because nothing was measured, per the house rule.
    """
    # min_n=1 rather than min_n, so a rule that traded four times can be
    # reported as "4 closes, need 10" instead of collapsing into the same
    # empty result as a rule that has never traded here at all. Same query
    # either way; the threshold is applied below.
    rows = bot_performance_summary(
        rule_name=rule_name, asset_class=asset_class, days=days, min_n=1,
        venue=venue,
    )
    where = asset_class or "any asset class"
    if not rows:
        return {
            "multiplier": NEUTRAL_MULTIPLIER, "venue": venue, "n": 0,
            "win_rate": None, "expectancy": None, "measured": False,
            "reason": (f"no closed {venue} trades for {rule_name!r} on "
                       f"{where} in {days}d — neutral, not measured"),
        }
    # Rows are sorted by descending n; with both rule_name and asset_class
    # given there is only ever one bucket, and callers that omit asset_class
    # get the best-evidenced one, which is the pre-existing behaviour.
    r = rows[0]
    if r["n"] < min_n:
        return {
            "multiplier": NEUTRAL_MULTIPLIER, "venue": venue, "n": r["n"],
            "win_rate": r["win_rate"], "expectancy": r["expectancy"],
            "measured": False,
            "reason": (f"{r['n']} closed {venue} trades for {rule_name!r} on "
                       f"{where} in {days}d, below min_n={min_n} — neutral"),
        }

    wr_delta = r["win_rate"] - 0.50
    r_signal = max(min(r["avg_r"], 1.0), -1.0)

    raw = 1.0 + (wr_delta * 0.6) + (r_signal * 0.4)
    multiplier = max(floor, min(ceiling, round(raw, 3)))
    return {
        "multiplier": multiplier, "venue": venue, "n": r["n"],
        "win_rate": r["win_rate"], "expectancy": r["expectancy"],
        "measured": True,
        "reason": (f"{r['n']} closed {venue} trades for {rule_name!r} on "
                   f"{where}: win_rate {r['win_rate']:.2f}, "
                   f"expectancy {r['expectancy']:+.2f}R → ×{multiplier}"),
    }


def bot_trade_track_record(rule_name: str, asset_class: str,
                            *, days: int = 180, min_n: int = 10,
                            floor: float = 0.5, ceiling: float = 1.5,
                            venue: str = VENUE_ALL) -> float:
    """Return a confidence multiplier in [floor, ceiling] for a rule's
    *bot-trade* track record on a given asset class and venue.

    Uses two ingredients:
      - win_rate vs 0.50 baseline
      - average realized_r vs 0 baseline

    Combined into a single multiplier such that:
      - 50% win rate AND zero avg_r → 1.0 (no boost, no penalty)
      - 70% win rate AND +0.5 avg_r → ~1.4 (boost)
      - 30% win rate AND -0.5 avg_r → ~0.6 (penalty)

    With fewer than `min_n` graded trades on `venue`, returns 1.0 (no
    signal). `venue` defaults to the pooled record for backwards
    compatibility; a caller about to place an order must pass the venue it
    will actually trade on, or it is weighting one venue's order with the
    other venue's fills. `bot_track_record_detail` returns the same number
    with the reason attached.
    """
    return bot_track_record_detail(
        rule_name, asset_class, days=days, min_n=min_n,
        floor=floor, ceiling=ceiling, venue=venue,
    )["multiplier"]


# ── Execution drag: what survives the trip from paper to live ────────────

def paper_live_expectancy_gap(*, rule_name: Optional[str] = None,
                               asset_class: Optional[str] = None,
                               days: int = 180,
                               min_n: int = 1,
                               user=None,
                               since=None) -> list[dict]:
    """Per-(rule, asset_class), how much of the paper edge survives live.

    Each row:
        {rule_name, asset_class, n_paper, n_live,
         paper_expectancy, live_expectancy, gap}

    `gap` is live_expectancy − paper_expectancy in R-multiples: negative
    means real execution ate edge the simulator promised, which is the
    normal direction (the paper fill is charged a modelled half-spread, but
    it never suffers a queue, a gap through the stop, or a partial). A rule
    whose gap is large and negative is not a rule that stopped working — it
    is a rule whose edge is smaller than its costs, and the two call for
    completely different fixes.

    `gap` is None whenever either side has no closed trades, because a gap
    against an unmeasured venue is not a small gap, it is no measurement at
    all.

    `n_paper` / `n_live` count every closed trade on that venue, reported
    whether or not the venue cleared `min_n`. That distinction is the whole
    point of the function: 0 means the rule has genuinely never traded there,
    while a nonzero count beside a None expectancy means the evidence exists
    and is too thin to state. `min_n` censors the EXPECTANCY, never the
    count — a rule with nine live closes and min_n=10 previously came back as
    `n_live: 0`, indistinguishable from one that had never gone live, which
    is the opposite of what this function is for. A pair where neither venue
    clears `min_n` is dropped entirely, since it has nothing to report on
    either side.

    Nothing in the decision path consumes this yet — it is a diagnostic the
    ledger can already answer, exposed so a dashboard or the promotion
    ladder can pick it up without re-deriving the split.
    """
    # min_n=1 on the query, applied by hand below. Letting the summary drop
    # thin buckets made a censored venue come back MISSING, and a missing
    # bucket read as a count of zero — see the docstring.
    common = dict(rule_name=rule_name, asset_class=asset_class, days=days,
                  min_n=1, user=user, since=since)
    paper_by_key = {(r["rule_name"], r["asset_class"]): r
                    for r in bot_performance_summary(venue=VENUE_PAPER, **common)}
    live_by_key = {(r["rule_name"], r["asset_class"]): r
                   for r in bot_performance_summary(venue=VENUE_LIVE, **common)}

    rows = []
    for key in sorted(set(paper_by_key) | set(live_by_key)):
        rn, ac = key
        p = paper_by_key.get(key)
        live = live_by_key.get(key)
        n_paper = p["n"] if p else 0
        n_live = live["n"] if live else 0
        if n_paper < min_n and n_live < min_n:
            continue
        # Below min_n the venue was observed but not measured, so the
        # expectancy is None rather than a number nobody should read. The
        # `p and` is not decoration: at min_n=0 a venue with no bucket at all
        # would otherwise satisfy `0 >= 0` and be dereferenced.
        p_exp = p["expectancy"] if (p and n_paper >= min_n) else None
        l_exp = live["expectancy"] if (live and n_live >= min_n) else None
        rows.append({
            "rule_name": rn,
            "asset_class": ac,
            "n_paper": n_paper,
            "n_live": n_live,
            "paper_expectancy": p_exp,
            "live_expectancy": l_exp,
            "gap": (round(l_exp - p_exp, 4)
                    if p_exp is not None and l_exp is not None else None),
        })
    rows.sort(key=lambda r: -(r["n_paper"] + r["n_live"]))
    return rows
