"""Phase-18 AssetBot walk-forward backtester.

Simulates an `AssetBotConfig` over a historical window: replay all qualifying
Phase-1 Signal rows in `[start, end]`, walk PriceData bars forward to find
the SL/TP hit, and aggregate per-trade R-multiples into a stats dict.

Where Phase 9.5's walk-forward scorer measures *rule* quality (would the
signal have been profitable?), Phase 18 measures *bot* quality (given the
config's SL/TP %, cooldown, gating, etc., would the bot have been profitable
acting on those signals?).

WHAT A MISSING BAR USED TO COST (2026-09-14)
--------------------------------------------

`_simulate_exit` returned `(None, 0.0, "expired")` when the feed carried no
bar after the signal, and the caller priced that 0.0 as a fill. A BUY at
100 with a 2% stop therefore booked

    r = (0.0 - 100) / |100 - 98| = -50

as a completed, *expired* trade. Worse, `exit_time` was None, so neither
the one-position-per-symbol guard nor the cooldown was ever armed for that
symbol: every later signal on it booked another -50. A symbol the feed had
never carried could bury a whole run under a four-figure negative total_R,
and `avg_r`, `sharpe_r`, `max_drawdown_r` and `max_consecutive_losses` all
reported it as measured.

A signal with no bars after it is not a losing trade. It is not a trade.
It is now dropped and COUNTED, in `BacktestResult.unmeasured` - because a
run that silently discarded 900 of its 1000 signals is also a lie, just a
quieter one.

Two neighbours of the same defect went with it:

  - A bar that OPENS beyond the stop used to fill AT the stop. A gap does
    not respect a stop order. It now fills at the open, which is the only
    direction of this error that matters: the old behaviour flattered the
    backtest in precisely the events that empty accounts.
  - "Expired" used to mean two different things - the walk ran its full
    length and touched nothing (a measurement), or the bar feed simply ran
    out (not one). The second is now `open_at_data_end`. On a platform
    whose bars have gone stale for fourteen hours at a stretch, the
    difference is between "this bot is flat" and "you have no data".

THE EXIT THE BACKTEST DID NOT KNOW ABOUT (2026-09-14)
-----------------------------------------------------

The live engine flattens a position at `AssetBotConfig.time_stop_setting()`
with reason TIME - `bot_program/asset_engine/base.py::_time_stop_hit`. This
module had never heard of it, and walked up to `max_bars` bars regardless.
So a scalper config with an 8h ceiling was backtested as a bot that holds
for 500 hours: targets reached on day nine were booked as wins that the
live bot could not have collected, and the run graded a strategy nothing
would ever execute.

That is the same defect as the three above wearing different clothes - a
measurement that does not measure the thing. The ceiling is now read off
the config and enforced, and its exits are labelled `time_stop`, the same
word `bot_program/bot_grading.py` already uses for the live ones.

Out of scope for v1:
  - Re-running decide() on every bar (too expensive). We use the Signal stream
    as the trigger source — same as live mode.
  - Concurrent-position cap simulation (one-per-symbol is enforced; the
    config's max_concurrent_positions is approximate).
  - Live broker slippage / spread modelling. Entry uses Signal.price_at_signal
    exactly; exits use the bar's SL/TP price exactly. Real fills will differ.
  - Orchestrator simulation. Phase 15 gating is bypassed in v1 to keep
    backtest results comparable across users; honour it later if needed.
"""
from __future__ import annotations

import logging
import math
import statistics
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

#: Every outcome that is a trade. The last two are NOT interchangeable:
#: `expired` is a measurement - the walk ran `max_bars` bars and touched
#: neither level. `open_at_data_end` is a mark-to-market against the last
#: bar that exists, which is a different claim.
OUTCOMES = ("hit_target", "stopped_out", "time_stop", "expired",
            "open_at_data_end")

#: Not an outcome. The feed carries no bar after the signal, so there is no
#: exit, no price, and nothing to average. The caller drops the signal and
#: counts it; see the module docstring for what pricing it used to cost.
NO_DATA = "no_data"


# ── Inputs / outputs ─────────────────────────────────────────────────────

@dataclass
class BacktestParams:
    config_id: int
    start: datetime
    end: datetime
    symbols: Optional[list] = None
    max_bars_per_trade: int = 500
    # Phase 22 — realism knobs.
    # Round-trip cost as a percent of entry price (e.g. 0.10 = 10 bps total
    # for the round trip — covers commission + half the spread).
    transaction_cost_pct: float = 0.0
    # One-way slippage as a percent of price. Applied at entry AND exit:
    #   BUY entry → entry × (1 + slip)   (you pay more)
    #   BUY exit  → exit  × (1 − slip)   (you receive less)
    #   SELL mirror.
    slippage_pct: float = 0.0
    # Walk-forward train/test split. When `walk_forward=True`, the window is
    # split: trades with entry_time before split point go into train_stats,
    # the remainder into test_stats. Helps detect overfit — a config that
    # blows up only on the test partition isn't shippable.
    walk_forward: bool = False
    train_pct: float = 0.7


@dataclass
class BacktestTrade:
    symbol: str
    side: str
    rule_name: str
    entry_time: Optional[datetime]
    entry_price: float
    stop_loss: float
    take_profit: float
    exit_time: Optional[datetime]
    exit_price: float
    outcome: str
    realized_r: float
    duration_minutes: int


@dataclass
class BacktestResult:
    params: BacktestParams
    trades: list = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    # Phase 22 — populated only when walk_forward=True.
    train_stats: Optional[dict] = None
    test_stats: Optional[dict] = None
    walk_forward_split_at: Optional[datetime] = None
    skipped: dict = field(default_factory=dict)
    #: Signals that qualified but could not be simulated, because the bar
    #: feed carried nothing after them. Always populated, so that zero is a
    #: measurement rather than an absence:
    #:   {"signals_without_bars": int, "by_symbol": {sym: int}}
    unmeasured: dict = field(default_factory=dict)


# ── Engine ───────────────────────────────────────────────────────────────

def run_backtest(params: BacktestParams) -> BacktestResult:
    """Run the simulation and return a `BacktestResult`."""
    from .models import AssetBotConfig
    from instruments.models import Instrument
    from signals.models import Signal

    cfg = AssetBotConfig.objects.get(id=params.config_id)
    symbols = params.symbols or list(cfg.symbols or [])
    if not symbols:
        return BacktestResult(params=params, stats=_empty_stats(),
                              skipped={"reason": "no_symbols"})

    insts = list(Instrument.objects.filter(symbol__in=symbols))
    if not insts:
        return BacktestResult(params=params, stats=_empty_stats(),
                              skipped={"reason": "no_instruments_found"})
    sym_to_inst = {i.symbol: i for i in insts}

    # All qualifying signals in window — match the live `entry_score_min` gate.
    sigs = (Signal.objects
            .filter(instrument__in=insts,
                    created_at__gte=params.start,
                    created_at__lte=params.end,
                    score__gte=cfg.entry_score_min)
            .select_related("instrument")
            .order_by("created_at"))

    # The one exit no broker holds and the live engine fires itself. A
    # backtest that ignores it measures a bot that never lets go, which is
    # not the bot that trades. `hours` is 0.0 exactly when the stop is off,
    # and `time_stop_setting` has already resolved extras / field / class
    # default, so there is nothing to re-derive here.
    time_stop = cfg.time_stop_setting()
    hold_hours = float(time_stop["hours"]) if time_stop["enabled"] else None

    trades: list[BacktestTrade] = []
    unmeasured: dict[str, int] = {}             # sym -> signals with no bars after
    open_until: dict[str, datetime] = {}        # sym → exit time of last open trade
    cooldown_until: dict[str, datetime] = {}    # sym → cooldown expiry
    cooldown_minutes = max(0, cfg.cool_down_minutes or 0)

    for sig in sigs:
        sym = sig.instrument.symbol

        # one position per symbol — skip if open at signal time
        if sym in open_until and sig.created_at < open_until[sym]:
            continue
        # cooldown
        if sym in cooldown_until and sig.created_at < cooldown_until[sym]:
            continue

        side = "BUY" if sig.direction == "bullish" else (
            "SELL" if sig.direction == "bearish" else None)
        if side is None:
            continue

        signal_price = float(sig.price_at_signal or 0)
        if signal_price <= 0:
            continue

        sl_pct = cfg.stop_loss_pct / 100.0
        tp_pct = cfg.take_profit_pct / 100.0
        slip = max(0.0, params.slippage_pct or 0.0) / 100.0

        # Phase 22 — apply entry slippage. SL/TP levels are computed off the
        # SIGNAL price (the level a trader would have set), but we simulate
        # entry at the slipped price, which is the realistic cost basis.
        if side == "BUY":
            entry = signal_price * (1 + slip)
            sl = signal_price * (1 - sl_pct)
            tp = signal_price * (1 + tp_pct)
        else:
            entry = signal_price * (1 - slip)
            sl = signal_price * (1 + sl_pct)
            tp = signal_price * (1 - tp_pct)

        exit_time, raw_exit_price, outcome = _simulate_exit(
            sym_to_inst[sym], cfg.timeframe, sig.created_at,
            side=side, sl=sl, tp=tp,
            max_bars=params.max_bars_per_trade,
            max_hold_hours=hold_hours,
        )

        # No bar after the signal means no exit and no price. Pricing the
        # absence is what booked a -50 R "expired trade" on every signal of
        # every symbol the feed had never carried; see the module docstring.
        if outcome == NO_DATA or raw_exit_price is None:
            unmeasured[sym] = unmeasured.get(sym, 0) + 1
            continue

        # Phase 22 - apply exit slippage. BUY pays slip on top of receiving;
        # SELL pays slip below.
        if side == "BUY":
            exit_price = raw_exit_price * (1 - slip)
        else:
            exit_price = raw_exit_price * (1 + slip)

        # realized R — pnl / |signal_price - sl|. Note we use signal-price-
        # based risk so R-multiples stay comparable across trades regardless
        # of slippage. Slippage just reduces the realised P&L.
        risk = abs(signal_price - sl)
        if risk > 0:
            if side == "BUY":
                pnl_per_unit = exit_price - entry
            else:
                pnl_per_unit = entry - exit_price
            r = pnl_per_unit / risk
        else:
            r = 0.0

        # Phase 22 — round-trip transaction cost as a percent of entry price.
        # Convert to R-multiples by dividing by the SL distance percentage.
        if params.transaction_cost_pct and sl_pct > 0:
            r -= (params.transaction_cost_pct / 100.0) / sl_pct

        duration_min = 0
        if exit_time and sig.created_at:
            try:
                duration_min = max(0, int((exit_time - sig.created_at).total_seconds() / 60))
            except Exception:
                duration_min = 0

        trades.append(BacktestTrade(
            symbol=sym, side=side,
            rule_name=sig.rule_name or "",
            entry_time=sig.created_at, entry_price=entry,
            stop_loss=sl, take_profit=tp,
            exit_time=exit_time, exit_price=exit_price,
            outcome=outcome, realized_r=round(r, 4),
            duration_minutes=duration_min,
        ))

        # mark cooldown + position close
        if exit_time:
            open_until[sym] = exit_time
            cooldown_until[sym] = exit_time + timedelta(minutes=cooldown_minutes)

    # Phase 22 — walk-forward partitioning.
    train_stats: Optional[dict] = None
    test_stats: Optional[dict] = None
    split_at: Optional[datetime] = None
    if params.walk_forward and trades:
        try:
            window_seconds = (params.end - params.start).total_seconds()
            split_at = params.start + timedelta(
                seconds=window_seconds * max(0.05, min(params.train_pct, 0.95)))
            train_t = [t for t in trades
                        if t.entry_time and t.entry_time < split_at]
            test_t = [t for t in trades
                       if t.entry_time and t.entry_time >= split_at]
            train_stats = compute_stats(train_t)
            test_stats = compute_stats(test_t)
        except Exception as e:
            logger.warning("walk-forward partition failed: %s", e)

    return BacktestResult(
        params=params, trades=trades,
        stats=compute_stats(trades),
        train_stats=train_stats, test_stats=test_stats,
        walk_forward_split_at=split_at,
        unmeasured={
            "signals_without_bars": sum(unmeasured.values()),
            "by_symbol": dict(sorted(unmeasured.items())),
        },
    )


def _simulate_exit(instrument, timeframe: str, after: datetime,
                    *, side: str, sl: float, tp: float,
                    max_bars: int, max_hold_hours: Optional[float] = None):
    """Walk PriceData bars after `after`. Return (exit_time, exit_price, outcome).

    Outcome is one of `OUTCOMES`, or `NO_DATA` - in which case the price is
    None and the caller MUST drop the signal rather than price it.

    When a bar's range covers BOTH SL and TP, SL is assumed first: the
    standard worst case, since without intra-bar ticks we cannot know which
    came first.

    A bar that OPENS beyond the stop fills at the open, not at the stop. A
    gap does not respect a stop order, and filling at the stop anyway is
    the one direction of this error that matters - it flatters the backtest
    in exactly the events that empty an account. The mirror case, a gap
    through the TARGET, still fills at the target: charging an unfavourable
    gap while refusing to credit a favourable one is the asymmetry a
    backtest is supposed to have.

    `max_hold_hours` is the config's time-stop ceiling, or None when it is
    off. A bar that OPENS after the ceiling has expired exits at that open
    with outcome `time_stop`, and never gets to show its range: the live
    engine's next tick would have flattened the position before this bar
    traded, so crediting it with the bar's target would be inventing a fill
    the bot could not have taken.
    """
    from market_data.models import PriceData

    bars = list(
        PriceData.objects
        .filter(instrument=instrument, timeframe=timeframe,
                timestamp__gt=after)
        .order_by("timestamp")[:max_bars]
    )

    if not bars:
        return None, None, NO_DATA

    deadline = (after + timedelta(hours=max_hold_hours)
                if max_hold_hours else None)

    for bar in bars:
        # Checked before the levels, deliberately. See the docstring.
        if deadline is not None and bar.timestamp >= deadline:
            return bar.timestamp, float(bar.open), "time_stop"

        h, lo, op = float(bar.high), float(bar.low), float(bar.open)
        if side == "BUY":
            if lo <= sl:                        # worst case first
                return bar.timestamp, min(op, sl), "stopped_out"
            if h >= tp:
                return bar.timestamp, tp, "hit_target"
        else:  # SELL
            if h >= sl:
                return bar.timestamp, max(op, sl), "stopped_out"
            if lo <= tp:
                return bar.timestamp, tp, "hit_target"

    # Neither level touched, and there are two very different reasons for
    # that. A full walk is a measured expiry. A short one means the slice
    # exhausted the table: the position is still open, and the price below
    # is the last close that exists, not a fill.
    last = bars[-1]
    ran_full_course = len(bars) >= max_bars
    return (last.timestamp, float(last.close),
            "expired" if ran_full_course else "open_at_data_end")


# ── Stats ────────────────────────────────────────────────────────────────

def compute_stats(trades: list) -> dict:
    if not trades:
        return _empty_stats()

    rs = [t.realized_r for t in trades]
    n = len(rs)
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r < 0]
    n_wins = len(wins)
    n_losses = len(losses)

    total_r = sum(rs)
    avg_r = total_r / n
    win_rate = n_wins / n if n else 0.0
    avg_win = (sum(wins) / n_wins) if n_wins else 0.0
    avg_loss = (sum(losses) / n_losses) if n_losses else 0.0

    gross_wins = sum(wins)
    gross_losses = -sum(losses)
    profit_factor = (gross_wins / gross_losses) if gross_losses > 0 else None

    # Equity curve in R-multiples → max drawdown.
    equity, peak, max_dd = 0.0, 0.0, 0.0
    for r in rs:
        equity += r
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)

    # Max consecutive losses streak.
    max_streak, streak = 0, 0
    for r in rs:
        if r < 0:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0

    # Sharpe-equivalent in R: mean / stdev * sqrt(n) (no rf adjustment).
    if n > 1 and statistics.stdev(rs) > 0:
        sharpe_r = (avg_r / statistics.stdev(rs)) * math.sqrt(n)
    else:
        sharpe_r = 0.0

    # Outcome counts.
    by_outcome = {key: 0 for key in OUTCOMES}
    for t in trades:
        by_outcome[t.outcome] = by_outcome.get(t.outcome, 0) + 1

    return {
        "n": n,
        "n_wins": n_wins, "n_losses": n_losses,
        "win_rate": round(win_rate, 4),
        "avg_r": round(avg_r, 4),
        "total_r": round(total_r, 4),
        "avg_win_r": round(avg_win, 4),
        "avg_loss_r": round(avg_loss, 4),
        "profit_factor": round(profit_factor, 4) if profit_factor is not None else None,
        "max_drawdown_r": round(max_dd, 4),
        "max_consecutive_losses": max_streak,
        "sharpe_r": round(sharpe_r, 4),
        "by_outcome": by_outcome,
    }


def _empty_stats() -> dict:
    return {
        "n": 0, "n_wins": 0, "n_losses": 0,
        "win_rate": 0, "avg_r": 0, "total_r": 0,
        "avg_win_r": 0, "avg_loss_r": 0,
        "profit_factor": None,
        "max_drawdown_r": 0, "max_consecutive_losses": 0,
        "sharpe_r": 0,
        "by_outcome": {key: 0 for key in OUTCOMES},
    }


# ── Persistence helper — used by the dashboard ──────────────────────────

def serialise_trades(trades: list) -> list[dict]:
    """Convert BacktestTrade list into JSON-safe dicts."""
    out = []
    for t in trades:
        d = asdict(t)
        if d.get("entry_time"):
            d["entry_time"] = d["entry_time"].isoformat()
        if d.get("exit_time"):
            d["exit_time"] = d["exit_time"].isoformat()
        out.append(d)
    return out
