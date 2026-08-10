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
  - outcome ∈ {hit_target, stopped_out, manual_close, expired}
  - realized_r (P&L normalised by initial risk = |entry - stop_loss| × qty)
  - duration_minutes

`bot_performance_summary(rule_name=, asset_class=, days=180)` aggregates the
graded population and returns win_rate / expectancy / count for a rule on
a given asset class.

`bot_trade_track_record(rule_name, asset_class, min_n=10)` returns a
confidence multiplier in [0.5, 1.5] — used by AssetBot.decide() when the
config opts in via `extras["use_bot_track_record"]=True`.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal
from typing import Optional

from django.utils import timezone

logger = logging.getLogger(__name__)


# ── Per-trade grading ────────────────────────────────────────────────────

def grade_bot_trade(trade) -> bool:
    """Compute outcome/realized_r/duration_minutes on a closed trade.

    Returns True on success, False on degenerate input. Idempotent — calling
    twice on the same trade just overwrites the same values.

    Outcome rules:
      - exit_price ≥ take_profit (BUY) or ≤ TP (SELL)        → hit_target
      - exit_price ≤ stop_loss (BUY) or ≥ SL (SELL)          → stopped_out
      - reason contains 'EXPIRY_CLOSE' (options, Phase 14)   → expired
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
                             since=None) -> list[dict]:
    """Return per-(rule_name, asset_class) stats for closed bot trades within
    the last `days`. Filterable by rule_name, asset_class, user, or an
    explicit `since` datetime that overrides `days`.

    Each row:
        {rule_name, asset_class, n, n_wins, n_losses, win_rate,
         avg_r, expectancy, avg_duration_min, last_traded_at}

    "n" here is *graded* trades only — open trades and not-yet-graded closes
    are excluded.
    """
    from .models import AssetBotTrade
    cutoff = since if since is not None else timezone.now() - timedelta(days=days)
    qs = (AssetBotTrade.objects
          .filter(status="CLOSED", closed_at__gte=cutoff,
                   outcome__in=["hit_target", "stopped_out", "manual_close", "expired"])
          .exclude(rule_name=""))
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

def bot_trade_track_record(rule_name: str, asset_class: str,
                            *, days: int = 180, min_n: int = 10,
                            floor: float = 0.5, ceiling: float = 1.5) -> float:
    """Return a confidence multiplier in [floor, ceiling] for a rule's
    *bot-trade* track record on a given asset class.

    Uses two ingredients:
      - win_rate vs 0.50 baseline
      - average realized_r vs 0 baseline

    Combined into a single multiplier such that:
      - 50% win rate AND zero avg_r → 1.0 (no boost, no penalty)
      - 70% win rate AND +0.5 avg_r → ~1.4 (boost)
      - 30% win rate AND -0.5 avg_r → ~0.6 (penalty)

    With fewer than `min_n` graded trades, returns 1.0 (no signal).
    """
    rows = bot_performance_summary(
        rule_name=rule_name, asset_class=asset_class, days=days, min_n=min_n,
    )
    if not rows:
        return 1.0
    r = rows[0]
    if r["n"] < min_n:
        return 1.0

    wr_delta = r["win_rate"] - 0.50
    r_signal = max(min(r["avg_r"], 1.0), -1.0)

    raw = 1.0 + (wr_delta * 0.6) + (r_signal * 0.4)
    return max(floor, min(ceiling, round(raw, 3)))
