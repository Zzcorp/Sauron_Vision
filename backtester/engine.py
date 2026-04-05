"""Backtesting engine — runs strategies against historical data."""
import pandas as pd
import numpy as np
import logging
from datetime import datetime
from decimal import Decimal
from indicators.calculator import calculate_rsi, calculate_macd, calculate_bollinger_bands, calculate_sma

logger = logging.getLogger(__name__)


class BacktestEngine:
    """Run a strategy against historical price data."""

    def __init__(self, initial_capital=10000, commission_pct=0.1):
        self.initial_capital = float(initial_capital)
        self.commission_pct = commission_pct / 100
        self.capital = self.initial_capital
        self.position = 0  # Number of units held
        self.entry_price = 0
        self.trades = []
        self.equity_curve = []

    def run(self, df, strategy_func):
        """
        Run backtest on DataFrame with OHLCV columns.
        strategy_func(df, i) should return: "buy", "sell", or "hold"
        """
        self.capital = self.initial_capital
        self.position = 0
        self.trades = []
        self.equity_curve = []

        for i in range(1, len(df)):
            price = float(df.iloc[i]["close"])
            date = str(df.index[i] if hasattr(df.index[i], "strftime") else df.iloc[i].get("date", i))

            signal = strategy_func(df, i)

            if signal == "buy" and self.position == 0:
                # Open long
                cost = price * (1 + self.commission_pct)
                units = self.capital / cost
                self.position = units
                self.entry_price = price
                self.capital = 0
                self.trades.append({"date": date, "action": "BUY", "price": price, "units": units})

            elif signal == "sell" and self.position > 0:
                # Close long
                proceeds = self.position * price * (1 - self.commission_pct)
                pnl = proceeds - (self.position * self.entry_price)
                pnl_pct = (price - self.entry_price) / self.entry_price * 100
                self.capital = proceeds
                self.trades.append({
                    "date": date, "action": "SELL", "price": price,
                    "pnl": round(pnl, 2), "pnl_pct": round(pnl_pct, 2),
                })
                self.position = 0

            # Track equity
            equity = self.capital + (self.position * price if self.position > 0 else 0)
            self.equity_curve.append({"date": date, "value": round(equity, 2)})

        # Force close any open position
        if self.position > 0 and len(df) > 0:
            final_price = float(df.iloc[-1]["close"])
            self.capital = self.position * final_price * (1 - self.commission_pct)
            self.position = 0

        return self._calculate_results()

    def _calculate_results(self):
        """Calculate performance metrics."""
        final = self.capital
        total_return = (final - self.initial_capital) / self.initial_capital * 100

        wins = [t for t in self.trades if t.get("pnl", 0) > 0]
        losses = [t for t in self.trades if t.get("pnl", 0) < 0]
        sell_trades = [t for t in self.trades if t["action"] == "SELL"]

        # Max drawdown
        peak = self.initial_capital
        max_dd = 0
        for point in self.equity_curve:
            if point["value"] > peak:
                peak = point["value"]
            dd = (peak - point["value"]) / peak * 100
            if dd > max_dd:
                max_dd = dd

        # Sharpe ratio (simplified, annualized)
        if len(self.equity_curve) > 1:
            returns = []
            for i in range(1, len(self.equity_curve)):
                r = (self.equity_curve[i]["value"] - self.equity_curve[i-1]["value"]) / self.equity_curve[i-1]["value"]
                returns.append(r)
            if returns and np.std(returns) > 0:
                sharpe = np.mean(returns) / np.std(returns) * np.sqrt(252)
            else:
                sharpe = 0
        else:
            sharpe = 0

        avg_win = np.mean([t["pnl_pct"] for t in wins]) if wins else 0
        avg_loss = np.mean([abs(t["pnl_pct"]) for t in losses]) if losses else 0
        profit_factor = (sum(t["pnl"] for t in wins) / abs(sum(t["pnl"] for t in losses))) if losses and sum(t["pnl"] for t in losses) != 0 else 0

        return {
            "final_value": round(final, 2),
            "total_return_pct": round(total_return, 2),
            "max_drawdown_pct": round(max_dd, 2),
            "sharpe_ratio": round(sharpe, 2),
            "total_trades": len(sell_trades),
            "winning_trades": len(wins),
            "losing_trades": len(losses),
            "win_rate": round(len(wins) / max(len(sell_trades), 1) * 100, 1),
            "avg_win_pct": round(avg_win, 2),
            "avg_loss_pct": round(avg_loss, 2),
            "profit_factor": round(profit_factor, 2),
            "equity_curve": self.equity_curve,
            "trades_log": self.trades,
        }


# ── Pre-built strategy functions ────────────────────────

def rsi_strategy(df, i, oversold=30, overbought=70, period=14):
    """RSI mean reversion: buy when oversold, sell when overbought."""
    close = df["close"].astype(float)
    if i < period + 1:
        return "hold"
    rsi = calculate_rsi(close[:i+1], period).iloc[-1]
    if pd.isna(rsi):
        return "hold"
    if rsi < oversold:
        return "buy"
    elif rsi > overbought:
        return "sell"
    return "hold"


def macd_crossover_strategy(df, i, fast=12, slow=26, signal=9):
    """MACD crossover: buy on bullish cross, sell on bearish cross."""
    close = df["close"].astype(float)
    if i < slow + signal + 1:
        return "hold"
    macd_line, signal_line, _ = calculate_macd(close[:i+1], fast, slow, signal)
    if pd.isna(macd_line.iloc[-1]) or pd.isna(signal_line.iloc[-1]):
        return "hold"
    # Crossover detection
    if macd_line.iloc[-1] > signal_line.iloc[-1] and macd_line.iloc[-2] <= signal_line.iloc[-2]:
        return "buy"
    elif macd_line.iloc[-1] < signal_line.iloc[-1] and macd_line.iloc[-2] >= signal_line.iloc[-2]:
        return "sell"
    return "hold"


def sma_crossover_strategy(df, i, fast_period=20, slow_period=50):
    """SMA crossover: buy when fast crosses above slow."""
    close = df["close"].astype(float)
    if i < slow_period + 1:
        return "hold"
    fast = calculate_sma(close[:i+1], fast_period)
    slow = calculate_sma(close[:i+1], slow_period)
    if pd.isna(fast.iloc[-1]) or pd.isna(slow.iloc[-1]):
        return "hold"
    if fast.iloc[-1] > slow.iloc[-1] and fast.iloc[-2] <= slow.iloc[-2]:
        return "buy"
    elif fast.iloc[-1] < slow.iloc[-1] and fast.iloc[-2] >= slow.iloc[-2]:
        return "sell"
    return "hold"


STRATEGY_REGISTRY = {
    "rsi_mean_reversion": {"func": rsi_strategy, "name": "RSI Mean Reversion", "params": {"oversold": 30, "overbought": 70}},
    "macd_crossover": {"func": macd_crossover_strategy, "name": "MACD Crossover", "params": {"fast": 12, "slow": 26, "signal": 9}},
    "sma_crossover": {"func": sma_crossover_strategy, "name": "SMA Crossover", "params": {"fast_period": 20, "slow_period": 50}},
}
