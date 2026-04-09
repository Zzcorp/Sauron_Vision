"""Circuit breakers — fail-safe halts for the bot.

These are CHECKED before opening any new position and (optionally) before
managing existing ones. They never force-close positions on their own.
"""
from datetime import timedelta
from django.utils import timezone


class CircuitBreaker:
    """Container for the breaker checks. Returns (allowed, reason)."""

    def __init__(self, config):
        self.cfg = config

    def check_consecutive_losses(self, max_streak=4):
        """Halt new entries after N consecutive losing closes."""
        try:
            from ..models import BotTrade
            recent = BotTrade.objects.filter(
                config=self.cfg, status="CLOSED",
            ).order_by("-closed_at")[:max_streak]
            if recent.count() < max_streak:
                return True, "ok"
            if all(t.pnl_usdt < 0 for t in recent):
                return False, f"consecutive loss streak ({max_streak})"
            return True, "ok"
        except Exception:
            return True, "ok"

    def check_drawdown_from_peak(self, halt_at_pct=10.0):
        """Halt new entries if running drawdown from peak exceeds threshold."""
        try:
            from ..models import BotTrade
            from decimal import Decimal
            trades = list(BotTrade.objects.filter(
                config=self.cfg, status="CLOSED",
            ).order_by("closed_at"))
            equity = float(self.cfg.capital_usdt)
            peak = equity
            for t in trades:
                equity += float(t.pnl_usdt)
                peak = max(peak, equity)
            dd = (peak - equity) / peak * 100 if peak > 0 else 0
            if dd >= halt_at_pct:
                return False, f"drawdown {dd:.1f}% from peak"
            return True, "ok"
        except Exception:
            return True, "ok"

    def check_volatility_spike(self, symbol, multiplier=3.0):
        """Halt new entries on a symbol if 1h ATR > multiplier x 30d ATR."""
        try:
            from signals.smc.dataframe import load_ohlcv
            from signals.smc.pivots import atr
            df_short = load_ohlcv(symbol, "1h", bars=24)
            df_long = load_ohlcv(symbol, "1h", bars=720)
            if df_short is None or df_long is None:
                return True, "ok"
            atr_short = atr(df_short, period=14)
            atr_long = atr(df_long, period=14)
            if len(atr_short) == 0 or len(atr_long) == 0:
                return True, "ok"
            short_val = float(atr_short[-1]) if atr_short[-1] else 0
            long_val = float(atr_long[-1]) if atr_long[-1] else 0
            if long_val > 0 and short_val > long_val * multiplier:
                return False, f"vol spike {short_val/long_val:.1f}x baseline"
            return True, "ok"
        except Exception:
            return True, "ok"

    def check_exchange_error_backoff(self, max_errors=5, window_minutes=10):
        """Halt new entries after N exchange errors in M minutes."""
        try:
            from ..models_v2 import BotCircuitState
            state = BotCircuitState.objects.filter(config=self.cfg).first()
            if not state:
                return True, "ok"
            since = timezone.now() - timedelta(minutes=window_minutes)
            if state.last_error_burst_started and state.last_error_burst_started > since \
                    and state.error_count_in_burst >= max_errors:
                return False, f"{state.error_count_in_burst} exchange errors in {window_minutes}min"
            return True, "ok"
        except Exception:
            return True, "ok"

    def check_all(self, symbol=None):
        """Run all checks; return (allowed, list_of_reasons)."""
        results = [
            self.check_consecutive_losses(),
            self.check_drawdown_from_peak(),
            self.check_exchange_error_backoff(),
        ]
        if symbol:
            results.append(self.check_volatility_spike(symbol))
        reasons = [r for ok, r in results if not ok]
        return (len(reasons) == 0, reasons)


def record_exchange_error(config):
    """Increment the exchange-error counter for circuit breaker tracking."""
    try:
        from ..models_v2 import BotCircuitState
        state, _ = BotCircuitState.objects.get_or_create(config=config)
        now = timezone.now()
        if not state.last_error_burst_started \
                or (now - state.last_error_burst_started) > timedelta(minutes=10):
            state.last_error_burst_started = now
            state.error_count_in_burst = 1
        else:
            state.error_count_in_burst += 1
        state.last_error_at = now
        state.save()
    except Exception:
        pass
