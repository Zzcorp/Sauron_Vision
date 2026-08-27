"""Backtester v2 — drives the bot's actual decide() function bar by bar.

Key principle: the only way a backtest result is trustworthy is if it runs
the exact same code path the live bot will run. This engine wraps
bot_program.engine.strategy.decide() and feeds it OHLCV/orderbook windows
that mimic what the live runner would have seen at each bar.
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class BacktestPosition:
    symbol: str
    side: str               # "BUY" or "SELL"
    entry_price: float
    qty: float
    stop_loss: float
    take_profit: float
    entry_idx: int
    entry_ts: object        # pd.Timestamp
    score: float = 0.0
    reasons: list = field(default_factory=list)
    high_water: float = 0.0  # for trailing
    low_water: float = 1e18  # for trailing
    # The stop this position OPENED with. `stop_loss` is ratcheted by the
    # trailing logic, so it is not the risk the trade was taken with —
    # measuring R against it makes pnl and risk the same quantity and every
    # trailing winner scores ~1R, which is how a strategy that trails comes
    # to look identical to one that does not.
    initial_stop_loss: float = 0.0


@dataclass
class BacktestTrade:
    symbol: str
    side: str
    entry_price: float
    exit_price: float
    qty: float
    entry_ts: object
    exit_ts: object
    pnl: float
    pnl_pct: float
    r_multiple: float
    exit_reason: str        # "TP", "SL", "TRAIL", "EOD", "FORCE_CLOSE"
    funding_paid: float = 0.0
    slippage_cost: float = 0.0
    score: float = 0.0


class BacktestEngineV2:
    """Multi-position, multi-symbol backtester driven by the bot strategy."""

    def __init__(
        self,
        initial_capital: float = 10_000.0,
        position_size_pct: float = 5.0,
        max_concurrent: int = 4,
        max_daily_loss_pct: float = 3.0,
        leverage: float = 1.0,
        spread_bps: float = 5.0,
        impact_bps: float = 5.0,
        funding_apr: float = 0.10,    # ~10% annualized funding cost for futures
        is_futures: bool = False,
        weights: Optional[dict] = None,
        entry_min: float = 0.5,
        exit_max: float = -0.3,
    ):
        self.initial_capital = initial_capital
        self.capital = initial_capital
        self.position_size_pct = position_size_pct
        self.max_concurrent = max_concurrent
        self.max_daily_loss_pct = max_daily_loss_pct
        self.leverage = leverage
        self.spread_bps = spread_bps
        self.impact_bps = impact_bps
        self.funding_apr = funding_apr
        self.is_futures = is_futures
        self.weights = weights or {
            "technical": 0.30, "sauron_signals": 0.25, "news": 0.15,
            "liquidity": 0.15, "macro": 0.10, "sentiment": 0.05,
        }
        self.entry_min = entry_min
        self.exit_max = exit_max

        self.open_positions: dict[str, BacktestPosition] = {}
        self.trades: list[BacktestTrade] = []
        self.equity_curve: list[dict] = []
        self.daily_pnl: dict = {}    # date -> pnl
        self.peak = initial_capital
        self.max_dd = 0.0

    # -- Slippage / spread / funding ----------------------------------------
    def _apply_slippage(self, price: float, side: str, qty: float) -> float:
        from .slippage import realistic_fill_price
        return realistic_fill_price(
            price, side, qty,
            spread_bps=self.spread_bps,
            impact_bps=self.impact_bps,
        )

    def _funding_for_bar(self, position: BacktestPosition, bar_value: float,
                         bar_seconds: float) -> float:
        """Funding cost paid (or earned) on this bar for an open position."""
        if not self.is_futures:
            return 0.0
        annualized = self.funding_apr
        per_bar = bar_value * (annualized * bar_seconds / (365 * 24 * 3600))
        return per_bar

    # -- Execution mechanics ------------------------------------------------
    def _open_position(self, symbol, side, price, qty, sl, tp, idx, ts, decision):
        fill = self._apply_slippage(price, side, qty)
        pos = BacktestPosition(
            symbol=symbol, side=side, entry_price=fill, qty=qty,
            stop_loss=sl, initial_stop_loss=sl,
            take_profit=tp, entry_idx=idx, entry_ts=ts,
            score=getattr(decision, "score", 0.0),
            reasons=list(getattr(decision, "reasons", [])),
            high_water=fill, low_water=fill,
        )
        self.open_positions[symbol] = pos

    def _close_position(self, pos, exit_price, exit_ts, reason):
        fill = self._apply_slippage(
            exit_price,
            "SELL" if pos.side == "BUY" else "BUY",
            pos.qty,
        )
        if pos.side == "BUY":
            pnl = (fill - pos.entry_price) * pos.qty
            pnl_pct = (fill - pos.entry_price) / pos.entry_price * 100
        else:
            pnl = (pos.entry_price - fill) * pos.qty
            pnl_pct = (pos.entry_price - fill) / pos.entry_price * 100

        risk_per_unit = abs(pos.entry_price - (pos.initial_stop_loss
                                                or pos.stop_loss))
        r_mult = ((fill - pos.entry_price) / risk_per_unit) if risk_per_unit > 0 else 0
        if pos.side == "SELL":
            r_mult = -r_mult

        slip = (abs(fill - exit_price) + abs(pos.entry_price - pos.entry_price)) * pos.qty

        self.trades.append(BacktestTrade(
            symbol=pos.symbol, side=pos.side,
            entry_price=pos.entry_price, exit_price=fill,
            qty=pos.qty, entry_ts=pos.entry_ts, exit_ts=exit_ts,
            pnl=round(pnl, 4), pnl_pct=round(pnl_pct, 4),
            r_multiple=round(r_mult, 3),
            exit_reason=reason,
            slippage_cost=round(slip, 4),
            score=pos.score,
        ))
        self.capital += pnl
        del self.open_positions[pos.symbol]

    # -- Per-bar update -----------------------------------------------------
    def _check_exits(self, symbol, bar, bar_idx, ts, trail_pct=None):
        if symbol not in self.open_positions:
            return
        pos = self.open_positions[symbol]
        high, low = float(bar["high"]), float(bar["low"])

        # Exits resolve against the levels as they stood when this bar
        # OPENED. Ratcheting the stop on this bar's high and then testing
        # this bar's low against the new level assumes the high came first
        # — a coin flip the backtest always wins. That look-ahead turns
        # round-trip bars into exits at the trailed price and flatters
        # every trailing strategy, which then clears a promotion gate the
        # live version cannot.
        if pos.side == "BUY":
            if low <= pos.stop_loss:
                self._close_position(pos, pos.stop_loss, ts, "SL")
                return
            if high >= pos.take_profit:
                self._close_position(pos, pos.take_profit, ts, "TP")
                return
        else:
            if high >= pos.stop_loss:
                self._close_position(pos, pos.stop_loss, ts, "SL")
                return
            if low <= pos.take_profit:
                self._close_position(pos, pos.take_profit, ts, "TP")
                return

        # Survived the bar: now record its extremes and ratchet the stop
        # for the NEXT one.
        pos.high_water = max(pos.high_water, high)
        pos.low_water = min(pos.low_water, low)
        if trail_pct and trail_pct > 0:
            if pos.side == "BUY":
                trail_sl = pos.high_water * (1 - trail_pct / 100)
                if trail_sl > pos.stop_loss:
                    pos.stop_loss = trail_sl
            else:
                trail_sl = pos.low_water * (1 + trail_pct / 100)
                if trail_sl < pos.stop_loss:
                    pos.stop_loss = trail_sl

    def _update_equity(self, current_prices, ts):
        equity = self.capital
        for sym, pos in self.open_positions.items():
            mark = current_prices.get(sym, pos.entry_price)
            if pos.side == "BUY":
                equity += (mark - pos.entry_price) * pos.qty
            else:
                equity += (pos.entry_price - mark) * pos.qty
        self.equity_curve.append({"ts": ts, "equity": round(equity, 4)})
        if equity > self.peak:
            self.peak = equity
        dd = (self.peak - equity) / self.peak * 100
        if dd > self.max_dd:
            self.max_dd = dd

    # -- Main run loop ------------------------------------------------------
    def run(self, dataframes: dict, lookback: int = 200, trail_pct: float = 0.0):
        """Run the backtest.

        dataframes: {symbol: pd.DataFrame indexed by ts with OHLCV columns}
        lookback: bars of history fed to decide() each step (mimics live)
        trail_pct: trailing stop percent (0 = disabled)
        """
        try:
            from bot_program.engine.strategy import decide
        except Exception as e:
            logger.error("could not import bot strategy: %s", e)
            return self._results()

        symbols = sorted(dataframes.keys())
        if not symbols:
            return self._results()

        common_index = None
        for sym in symbols:
            idx = dataframes[sym].index
            common_index = idx if common_index is None else common_index.intersection(idx)
        if common_index is None or len(common_index) < lookback + 10:
            return self._results()

        ts_list = list(common_index)

        for i, ts in enumerate(ts_list):
            if i < lookback:
                continue

            current_prices = {sym: float(dataframes[sym].loc[ts]["close"])
                              for sym in symbols if ts in dataframes[sym].index}

            for sym in symbols:
                if ts not in dataframes[sym].index:
                    continue
                bar = dataframes[sym].loc[ts]
                self._check_exits(sym, bar, i, ts, trail_pct=trail_pct)

            if len(self.open_positions) >= self.max_concurrent:
                self._update_equity(current_prices, ts)
                continue
            if self._daily_loss_breached(ts):
                self._update_equity(current_prices, ts)
                continue

            for sym in symbols:
                if sym in self.open_positions:
                    continue
                df = dataframes[sym]
                if ts not in df.index:
                    continue
                window = df.loc[:ts].iloc[-lookback:]
                ohlcv = [
                    [float(r["open"]), float(r["high"]), float(r["low"]),
                     float(r["close"]), float(r["volume"])]
                    for _, r in window.iterrows()
                ]
                ob = {"bids": [], "asks": []}    # synthetic empty book

                try:
                    decision = decide(
                        sym, ohlcv, ob, self.weights,
                        entry_min=self.entry_min, exit_max=self.exit_max,
                        # The bar being decided. Without it the news leg
                        # reads today's headlines for every historical bar,
                        # which is lookahead, not noise.
                        as_of=ts,
                    )
                except Exception as e:
                    logger.debug("decide() failed for %s at %s: %s", sym, ts, e)
                    continue

                if decision.direction == "HOLD":
                    continue

                price = float(window["close"].iloc[-1])
                dollars = self.capital * (self.position_size_pct / 100) * self.leverage
                qty = dollars / price if price > 0 else 0
                if qty <= 0:
                    continue

                if decision.direction == "BUY":
                    sl = price * (1 - decision.sl_pct / 100)
                    tp = price * (1 + decision.tp_pct / 100)
                else:
                    sl = price * (1 + decision.sl_pct / 100)
                    tp = price * (1 - decision.tp_pct / 100)

                self._open_position(sym, decision.direction, price, qty,
                                    sl, tp, i, ts, decision)

                if len(self.open_positions) >= self.max_concurrent:
                    break

            self._update_equity(current_prices, ts)

        # Force-close anything still open at the end
        if ts_list:
            final_ts = ts_list[-1]
            for sym in list(self.open_positions.keys()):
                if final_ts in dataframes[sym].index:
                    final_price = float(dataframes[sym].loc[final_ts]["close"])
                    self._close_position(
                        self.open_positions[sym], final_price, final_ts, "FORCE_CLOSE"
                    )

        return self._results()

    def _daily_loss_breached(self, ts):
        """Stop opening new positions after daily loss limit."""
        if not hasattr(ts, "date"):
            return False
        day = ts.date()
        day_pnl = sum(
            t.pnl for t in self.trades
            if hasattr(t.exit_ts, "date") and t.exit_ts.date() == day
        )
        limit = -self.initial_capital * (self.max_daily_loss_pct / 100)
        return day_pnl <= limit

    def _results(self):
        from .metrics import compute_metrics
        return {
            "trades": self.trades,
            "equity_curve": self.equity_curve,
            "metrics": compute_metrics(
                self.trades, self.equity_curve, self.initial_capital
            ),
            "final_capital": round(self.capital, 4),
            "max_drawdown_pct": round(self.max_dd, 4),
        }
