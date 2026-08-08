"""Phase-18 AssetBot walk-forward backtester.

Simulates an `AssetBotConfig` over a historical window: replay all qualifying
Phase-1 Signal rows in `[start, end]`, walk PriceData bars forward to find
the SL/TP hit, and aggregate per-trade R-multiples into a stats dict.

Where Phase 9.5's walk-forward scorer measures *rule* quality (would the
signal have been profitable?), Phase 18 measures *bot* quality (given the
config's SL/TP %, cooldown, gating, etc., would the bot have been profitable
acting on those signals?).

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

    trades: list[BacktestTrade] = []
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
        )

        # Phase 22 — apply exit slippage. BUY pays slip on top of receiving;
        # SELL pays slip below.
        if outcome in ("hit_target", "stopped_out", "expired"):
            if side == "BUY":
                exit_price = raw_exit_price * (1 - slip)
            else:
                exit_price = raw_exit_price * (1 + slip)
        else:
            exit_price = raw_exit_price

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
    )


def _simulate_exit(instrument, timeframe: str, after: datetime,
                    *, side: str, sl: float, tp: float,
                    max_bars: int):
    """Walk PriceData bars after `after`. Return (exit_time, exit_price, outcome).

    Outcome ∈ {hit_target, stopped_out, expired}. When a bar's range covers
    BOTH SL and TP, we conservatively assume SL hits first (the standard
    backtest worst-case assumption — without intra-bar tick data we can't
    know which actually happened first).
    """
    from market_data.models import PriceData

    bars = list(
        PriceData.objects
        .filter(instrument=instrument, timeframe=timeframe,
                timestamp__gt=after)
        .order_by("timestamp")[:max_bars]
    )

    if not bars:
        return None, 0.0, "expired"

    for bar in bars:
        h = float(bar.high)
        lo = float(bar.low)
        if side == "BUY":
            hit_sl = lo <= sl
            hit_tp = h >= tp
            if hit_sl:  # worst case first
                return bar.timestamp, sl, "stopped_out"
            if hit_tp:
                return bar.timestamp, tp, "hit_target"
        else:  # SELL
            hit_sl = h >= sl
            hit_tp = lo <= tp
            if hit_sl:
                return bar.timestamp, sl, "stopped_out"
            if hit_tp:
                return bar.timestamp, tp, "hit_target"

    # No SL / TP hit within window — close at last bar's close.
    last = bars[-1]
    return last.timestamp, float(last.close), "expired"


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
    by_outcome = {"hit_target": 0, "stopped_out": 0, "expired": 0}
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
        "by_outcome": {"hit_target": 0, "stopped_out": 0, "expired": 0},
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
