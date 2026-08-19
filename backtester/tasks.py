"""The worker side of the backtest button.

`dashboard.views.backtest_create` used to write a BacktestRun row with
status="pending" and stop there — the three lines that were supposed to
hand the row to a worker were commented out and this module did not
exist. Every launch filed a request nothing ever picked up: the row sat
on "pending" forever, the list page never showed a completed run, and
the operator had no way to tell "queued" from "abandoned".

The contract this module now guarantees is narrow and absolute: a row
handed to `run_backtest` NEVER stays pending. It ends on "completed"
with every result field written, or on "failed" with an `error` a human
can act on. A run that produces no trades is a RESULT, not a failure —
it completes, with the trade statistics left NULL because they are
genuinely unknown rather than zero.

Honesty rules borrowed from signals.evolution_backtest, which is how
this platform already runs a backtest it is willing to trust:

  * As-of data only. Every bar the strategy sees at index i was closed
    at or before index i; nothing in the loop reads a live table or a
    now()-relative query.
  * Warm-up is measured in BARS, not days. The indicator needs N closes
    before it can speak, so N bars are fetched from BEFORE the window
    and prepended. The strategy therefore cannot act until the first bar
    the operator actually asked about, and no trade is ever booked
    outside the requested window.
  * Metrics come from `backtester.metrics`. There is exactly one Sharpe
    and one drawdown implementation in this codebase and this module
    calls it rather than growing a second one.

Deliberately NOT wrapped in @guarded_task. That decorator refuses to run
when its PlatformComponent is disabled, every DEFAULT_COMPONENTS entry is
seeded is_enabled=False, and a skipped task returns without touching the
row. Gating an explicitly operator-initiated backtest behind a default-off
switch would reproduce the exact bug this module fixes — a button that
files a row and never runs it — and the operator has no reason to expect
a kill switch to swallow a click they just made. The scheduled, unattended
tasks are what that gate is for; this one is neither.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


class BacktestConfigError(ValueError):
    """The run cannot be executed as configured — an operator can fix it."""


# ── Strategy resolution ──────────────────────────────────────────────────

# The create form speaks in trading vocabulary ("trend_follow"); the engine
# registry speaks in indicator vocabulary ("sma_crossover"). This table is
# the whole translation, and it is deliberately short: an entry here is a
# promise that the named engine strategy really is the thing the form
# label describes. Anything not listed is rejected by name rather than
# quietly mapped onto a strategy it is not — a run labelled "Breakout"
# that secretly ran an SMA cross is worse than a run that refused.
STRATEGY_ALIASES = {
    "mean_reversion": "rsi_mean_reversion",
    "trend_follow": "sma_crossover",
    "momentum": "macd_crossover",
}

# Form values with no honest implementation behind them, and the reason.
# Surfaced to the operator verbatim so the failure explains itself.
UNSUPPORTED_STRATEGIES = {
    "smc_signals": (
        "the SMC path runs through backtester.engine_v2 → "
        "bot_program.engine.strategy.decide(), which scores each bar from "
        "live tables with now()-relative filters (signals from the last 6h, "
        "news from the last 12h, an order book from the last 30s). Replayed "
        "over a historical window those reads return TODAY's data at every "
        "past bar, so the result would be look-ahead, not a backtest"
    ),
    "breakout": (
        "no breakout strategy is implemented in backtester.engine — the "
        "registry holds RSI, MACD and SMA only"
    ),
    "custom": (
        "'custom' names no strategy; pick a concrete one, or register a "
        "function in backtester.engine.STRATEGY_REGISTRY first"
    ),
}


def _warmup_bars(registry_key: str, params: dict) -> int:
    """Bars of history the strategy needs before it may speak.

    Mirrors the guard clause at the top of each strategy function. Getting
    this wrong in either direction is a real error: too few and the first
    signals fire off half-formed indicators, too many and bars the operator
    asked about are spent warming up instead of trading.
    """
    if registry_key == "rsi_mean_reversion":
        return int(params.get("period", 14)) + 1
    if registry_key == "macd_crossover":
        return int(params.get("slow", 26)) + int(params.get("signal", 9)) + 1
    if registry_key == "sma_crossover":
        return int(params.get("slow_period", 50)) + 1
    return 0


def resolve_strategy(strategy_type: str, parameters: dict):
    """(registry_key, strategy_func, params, warmup_bars) or raise.

    Accepts both the form's vocabulary and the engine registry's own keys,
    so a row created by a script or an older form still runs.
    """
    from .engine import STRATEGY_REGISTRY

    key = (strategy_type or "").strip().lower()
    if key in UNSUPPORTED_STRATEGIES:
        raise BacktestConfigError(
            f"Strategy '{key}' cannot be backtested here: "
            f"{UNSUPPORTED_STRATEGIES[key]}. Runnable strategies: "
            f"{', '.join(sorted(STRATEGY_ALIASES))}."
        )
    registry_key = STRATEGY_ALIASES.get(key, key)
    entry = STRATEGY_REGISTRY.get(registry_key)
    if entry is None:
        raise BacktestConfigError(
            f"Unknown strategy '{strategy_type}'. Runnable strategies: "
            f"{', '.join(sorted(STRATEGY_ALIASES))}."
        )

    # Registry defaults first, operator overrides on top — but only for keys
    # the strategy function actually accepts. The form also posts sizing and
    # risk knobs, and passing those through as strategy kwargs would raise
    # TypeError inside the loop instead of being handled where they belong.
    params = dict(entry["params"])
    for k in list(params):
        if k in (parameters or {}):
            params[k] = parameters[k]
    return registry_key, entry["func"], params, _warmup_bars(registry_key, params)


# ── Bars ─────────────────────────────────────────────────────────────────

# Sharpe annualisation factor per timeframe. metrics._sharpe defaults to
# 365*6 (4h bars, calendar year) and the whole table stays on that calendar
# convention so two runs on this page are comparable to each other.
BARS_PER_YEAR = {
    "1m": 365 * 24 * 60, "5m": 365 * 24 * 12, "15m": 365 * 24 * 4,
    "30m": 365 * 24 * 2, "1h": 365 * 24, "4h": 365 * 6,
    "1d": 365, "1w": 52,
}


def _as_utc(d, end_of_day: bool = False):
    """A DateField boundary as an aware datetime.

    `end_of_day` returns the START of the following day, so the filter can
    stay a half-open `< ` and still include every bar stamped on the end
    date — an operator who types today's date means today's bars.

    Accepts a str because a freshly `create()`d row still holds whatever the
    form posted until it is read back from the database.
    """
    if isinstance(d, str):
        d = date.fromisoformat(d)
    if isinstance(d, datetime):
        base = d
    else:
        base = datetime.combine(d + (timedelta(days=1) if end_of_day else timedelta()),
                                time.min)
    # settings.TIME_ZONE is UTC, so the default zone IS the bar timezone.
    return timezone.make_aware(base) if timezone.is_naive(base) else base


def load_bars(symbol: str, timeframe: str, start_date, end_date, warmup_bars: int):
    """OHLCV DataFrame for one symbol: `warmup_bars` of history, then the window.

    Returns (df, n_warmup_rows). Raises BacktestConfigError when the symbol
    or its bars are missing — a backtest with no data is a configuration
    problem the operator can fix, not a crash to bury in a traceback.
    """
    import pandas as pd

    from instruments.models import Instrument
    from market_data.models import PriceData

    inst = Instrument.objects.filter(symbol=symbol).first()
    if inst is None:
        raise BacktestConfigError(
            f"No instrument named '{symbol}' — check the symbol, or add it "
            f"to the instrument catalogue first.")

    window_start = _as_utc(start_date)
    window_end = _as_utc(end_date, end_of_day=True)
    cols = ("timestamp", "open", "high", "low", "close", "volume")

    # PriceData.Meta.ordering is ["-timestamp"]; both queries state their own
    # order explicitly so neither inherits newest-first by accident.
    in_window = list(
        PriceData.objects.filter(instrument=inst, timeframe=timeframe,
                                 timestamp__gte=window_start,
                                 timestamp__lt=window_end)
        .order_by("timestamp").values(*cols))
    if not in_window:
        have = (PriceData.objects.filter(instrument=inst, timeframe=timeframe)
                .order_by("timestamp").values_list("timestamp", flat=True))
        first, last = have.first(), have.last()
        span = (f" The stored {timeframe} history for {symbol} runs "
                f"{first:%Y-%m-%d} → {last:%Y-%m-%d}." if first else
                f" There are no {timeframe} bars stored for {symbol} at all.")
        raise BacktestConfigError(
            f"No {timeframe} bars for {symbol} between {start_date} and "
            f"{end_date}.{span}")

    warm = []
    if warmup_bars > 0:
        warm = list(
            PriceData.objects.filter(instrument=inst, timeframe=timeframe,
                                     timestamp__lt=window_start)
            .order_by("-timestamp").values(*cols)[:warmup_bars])
        warm.reverse()

    rows = warm + in_window
    df = pd.DataFrame([{
        "timestamp": r["timestamp"],
        "open": float(r["open"]), "high": float(r["high"]),
        "low": float(r["low"]), "close": float(r["close"]),
        "volume": float(r["volume"] or 0),
    } for r in rows]).set_index("timestamp")
    return df, len(warm)


# ── Result assembly ──────────────────────────────────────────────────────

class _TradeView:
    """Adapter so `metrics.compute_metrics` can read v1-engine trades.

    compute_metrics was written against engine_v2's BacktestTrade dataclass
    and reads `.pnl` / `.r_multiple`; the v1 engine emits dicts. Six lines of
    adapter buy the portfolio-level win rate, profit factor and counts from
    the implementation that already exists, instead of a second copy of each
    drifting quietly out of agreement with it.
    """
    __slots__ = ("pnl", "r_multiple")

    def __init__(self, pnl, r_multiple=None):
        self.pnl = pnl
        self.r_multiple = r_multiple


def _merge_equity(per_symbol_curves: dict, idle_cash: dict, sleeve: float,
                  start_date):
    """One portfolio equity curve from N per-symbol curves.

    Symbols share a timeframe, so their bar stamps usually line up; where
    one has a gap its last known equity is carried forward rather than
    dropping out of the total. Keys are the engine's own date strings —
    fixed-width ISO in a single timezone, so lexicographic order IS
    chronological order and no re-parsing is needed.

    Warm-up points are dropped here. That is exact, not an approximation:
    warm-up is sized so the strategy's first possible signal lands on the
    first in-window bar, so every trimmed point is flat at the starting
    sleeve by construction.
    """
    cutoff = str(start_date)[:10]
    stamps = sorted({p["date"] for c in per_symbol_curves.values() for p in c})
    # Seeded at the full stake, not at zero: a symbol whose curve starts
    # later must contribute its untouched capital to the earlier totals,
    # or the portfolio appears to begin below what was actually staked.
    last = {sym: idle_cash[sym] + sleeve for sym in per_symbol_curves}
    by_stamp = {sym: {p["date"]: p["value"] for p in c}
                for sym, c in per_symbol_curves.items()}

    curve = []
    for stamp in stamps:
        for sym in per_symbol_curves:
            if stamp in by_stamp[sym]:
                last[sym] = idle_cash[sym] + by_stamp[sym][stamp]
        if stamp[:10] >= cutoff:
            curve.append({"date": stamp, "value": round(sum(last.values()), 2)})
    return curve


def execute_run(run) -> dict:
    """Run one BacktestRun and return the result fields. Pure — no writes.

    Split out from the task so the arithmetic can be exercised without a
    broker, and so the task's only job is the status contract.
    """
    from .metrics import _max_dd, _sharpe, compute_metrics
    from .engine import BacktestEngine

    params = dict(run.parameters or {})
    timeframe = str(params.get("timeframe") or "4h")
    if timeframe not in BARS_PER_YEAR:
        raise BacktestConfigError(
            f"Unknown timeframe '{timeframe}'. Supported: "
            f"{', '.join(BARS_PER_YEAR)}.")

    symbols = [s for s in dict.fromkeys(run.symbols or []) if s]
    if not symbols:
        raise BacktestConfigError(
            "No symbols selected — a backtest needs at least one instrument.")
    if run.end_date <= run.start_date:
        raise BacktestConfigError(
            f"End date ({run.end_date}) must be after the start date "
            f"({run.start_date}).")

    registry_key, strategy_func, strat_params, warmup = resolve_strategy(
        run.strategy_type, params)

    # Sizing: the v1 engine holds at most one position and commits the whole
    # sleeve to it, so "position size %" is exactly a smaller sleeve with the
    # remainder held as idle cash. Returns are reported on the FULL capital,
    # idle cash included, which is the number the operator staked.
    capital = float(run.initial_capital or 0)
    if capital <= 0:
        raise BacktestConfigError("Initial capital must be greater than zero.")
    size_pct = float(params.get("position_size_pct") or 100.0)
    size_pct = max(0.5, min(100.0, size_pct))
    commission_pct = float(params.get("commission_pct") or 0.1)

    def _pct(key):
        """A risk level as a float, or None when it was not asked for.

        These arrive through a JSONField, so a value written by anything
        other than the form can be a string. Coercing here turns that into
        a sentence about the field instead of a TypeError from inside the
        bar loop.
        """
        raw = params.get(key)
        if raw in (None, "", 0, 0.0):
            return None
        try:
            value = float(raw)
        except (TypeError, ValueError):
            raise BacktestConfigError(
                f"{key} must be a number, got {raw!r}.") from None
        if value <= 0:
            return None
        return value

    stop_loss_pct = _pct("stop_loss_pct")
    take_profit_pct = _pct("take_profit_pct")

    allocation = capital / len(symbols)
    sleeve = allocation * size_pct / 100.0
    idle = {sym: allocation - sleeve for sym in symbols}

    curves, trades, bars_used, warm_used = {}, [], {}, {}
    final_value = 0.0
    for sym in symbols:
        df, n_warm = load_bars(sym, timeframe, run.start_date, run.end_date, warmup)
        bars_used[sym] = len(df) - n_warm
        warm_used[sym] = n_warm
        engine = BacktestEngine(initial_capital=sleeve,
                                commission_pct=commission_pct)

        def _strategy(frame, i, _f=strategy_func, _p=strat_params):
            return _f(frame, i, **_p)

        result = engine.run(df, _strategy,
                            stop_loss_pct=stop_loss_pct,
                            take_profit_pct=take_profit_pct)
        curves[sym] = result["equity_curve"]
        final_value += result["final_value"] + idle[sym]
        for t in result["trades_log"]:
            trades.append({**t, "symbol": sym})

    equity_curve = _merge_equity(curves, idle, sleeve, run.start_date)
    closed = [t for t in trades if t["action"] == "SELL"]

    # r_multiple is only meaningful when a stop defined the risk. Without
    # one it stays None and compute_metrics skips it, rather than inventing
    # an R against a denominator that does not exist.
    views = [_TradeView(t["pnl"],
                        (t["pnl_pct"] / stop_loss_pct) if stop_loss_pct else None)
             for t in closed]
    curve_for_metrics = [{"equity": p["value"]} for p in equity_curve]
    stats = compute_metrics(views, curve_for_metrics, capital)

    wins = [t["pnl_pct"] for t in closed if t["pnl"] > 0]
    losses = [abs(t["pnl_pct"]) for t in closed if t["pnl"] < 0]

    fields = {
        "final_value": Decimal(str(round(final_value, 2))),
        "total_return_pct": round((final_value - capital) / capital * 100, 4),
        "max_drawdown_pct": round(_max_dd(curve_for_metrics), 4),
        "sharpe_ratio": None,
        "total_trades": len(closed),
        "winning_trades": len(wins),
        "losing_trades": len(losses),
        # Trade statistics with no trades behind them are UNKNOWN, not zero.
        # A 0% win rate reads as "it lost every trade"; there were no trades.
        "win_rate": None, "avg_win_pct": None, "avg_loss_pct": None,
        "profit_factor": None,
        "equity_curve": equity_curve,
        "trades_log": trades,
    }
    sharpe = _sharpe(curve_for_metrics,
                     periods_per_year=BARS_PER_YEAR[timeframe])
    if sharpe is not None:
        fields["sharpe_ratio"] = round(sharpe, 4)
    if closed:
        fields["win_rate"] = round(stats["win_rate"] * 100, 2)
        fields["profit_factor"] = stats["profit_factor"]
        fields["avg_win_pct"] = round(sum(wins) / len(wins), 4) if wins else None
        fields["avg_loss_pct"] = round(sum(losses) / len(losses), 4) if losses else None

    # What the engine actually did, kept next to what was asked for, so a
    # stored run stays auditable long after the form that made it changed.
    fields["_resolved"] = {
        "strategy": registry_key, "strategy_params": strat_params,
        "timeframe": timeframe, "warmup_bars_required": warmup,
        "warmup_bars_found": warm_used, "bars_in_window": bars_used,
        "position_size_pct": size_pct, "commission_pct": commission_pct,
        "stop_loss_pct": stop_loss_pct, "take_profit_pct": take_profit_pct,
        "symbols": symbols,
    }
    return fields


# ── The task ─────────────────────────────────────────────────────────────

@shared_task(name="backtester.tasks.run_backtest")
def run_backtest(run_id):
    """Execute BacktestRun `run_id`. The row never stays pending."""
    from .models import BacktestRun

    run = BacktestRun.objects.filter(pk=run_id).first()
    if run is None:
        # Nothing to mark; say so rather than raising into a retry loop.
        logger.warning("[backtest] run %s no longer exists", run_id)
        return {"status": "error", "error": f"BacktestRun {run_id} not found"}
    if run.status == "completed":
        return {"status": "skipped", "reason": "already completed",
                "run_id": run.id}

    run.status = "running"
    run.error = ""
    run.save(update_fields=["status", "error"])

    try:
        fields = execute_run(run)
    except Exception as e:  # noqa: BLE001 — a failed run must still SETTLE
        # BacktestConfigError carries an operator-readable sentence; anything
        # else gets its type prepended so an opaque message is still traceable
        # back to the code that raised it.
        detail = (str(e) if isinstance(e, BacktestConfigError)
                  else f"{type(e).__name__}: {e}")
        logger.exception("[backtest] run %s failed", run_id)
        run.status = "failed"
        run.error = detail[:2000]
        run.completed_at = timezone.now()
        run.save(update_fields=["status", "error", "completed_at"])
        return {"status": "error", "run_id": run.id, "error": detail[:200]}

    resolved = fields.pop("_resolved")
    for field, value in fields.items():
        setattr(run, field, value)
    params = dict(run.parameters or {})
    params["_resolved"] = resolved
    run.parameters = params
    run.status = "completed"
    run.completed_at = timezone.now()
    run.save()

    return {
        "status": "ok", "run_id": run.id,
        "trades": run.total_trades,
        "return_pct": run.total_return_pct,
        # A zero-trade run completed; it did not fail. Saying so here puts
        # the sentence in the operator's completion banner, where "0 trades"
        # alone would read as a malfunction.
        "note": ("completed with no trades — the strategy never triggered "
                 "on this window" if run.total_trades == 0 else ""),
    }
