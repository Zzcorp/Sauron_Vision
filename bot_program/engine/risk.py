"""Risk manager — enforces per-trade and account-level limits.

Phase-2 upgrade adds graduated drawdown throttling: instead of binary halt at
the daily-loss limit, position size is scaled down linearly as drawdown grows
toward the limit. The binary halt still fires *at* the limit (when
`halt_on_drawdown` is True), but the throttle starts much earlier so a bad day
does not require a single binary decision.
"""
from __future__ import annotations
from decimal import Decimal
from django.utils import timezone
from datetime import timedelta


# Throttle starts at this fraction of the daily loss limit (0.0 = no throttle yet,
# 1.0 = at the limit). Below DRAWDOWN_THROTTLE_FLOOR_FRAC, scale = 1.0.
DRAWDOWN_THROTTLE_FLOOR_FRAC = 0.25

# Position size never scales below this fraction once the throttle engages.
# Set to 0 if you want the throttle to fully zero out before the binary halt.
DRAWDOWN_SCALE_MIN = 0.10


class RiskManager:
    def __init__(self, config):
        self.c = config

    # ── primary gates ──────────────────────────────────────────────────────

    def can_open_new(self) -> tuple[bool, str]:
        from ..models import BotTrade
        open_trades = BotTrade.objects.filter(config=self.c, status="OPEN").count()
        if open_trades >= self.c.max_concurrent_positions:
            return (False, f"max {self.c.max_concurrent_positions} concurrent positions reached")

        pnl = self._daily_pnl()
        limit = -self._daily_loss_limit_usdt()
        if pnl <= limit and self.c.halt_on_drawdown:
            return (False, f"daily loss limit hit ({pnl:.2f} USDT)")
        return (True, "ok")

    def position_size(self, price: float) -> float:
        """Position size in base units, with graduated drawdown throttle applied."""
        cap = float(self.c.capital_usdt)
        dollars = cap * (self.c.position_size_pct / 100.0) * self.c.leverage
        dollars *= self.drawdown_scale()
        if price <= 0:
            return 0
        return round(dollars / price, 6)

    # ── drawdown introspection ─────────────────────────────────────────────

    def _daily_pnl(self) -> Decimal:
        """Realized P&L over the last 24h (sum of CLOSED trades)."""
        from ..models import BotTrade
        since = timezone.now() - timedelta(hours=24)
        closed = BotTrade.objects.filter(config=self.c, status="CLOSED", closed_at__gte=since)
        return sum((t.pnl_usdt for t in closed), Decimal(0))

    def _daily_loss_limit_usdt(self) -> Decimal:
        return self.c.capital_usdt * Decimal(self.c.max_daily_loss_pct / 100)

    def drawdown_fraction(self) -> float:
        """Loss as fraction of the daily loss limit. 0 = no loss, 1 = at the limit.

        Capped to [0, 1]. Profit (pnl > 0) returns 0.
        """
        pnl = self._daily_pnl()
        if pnl >= 0:
            return 0.0
        limit = self._daily_loss_limit_usdt()
        if limit <= 0:
            return 0.0
        return min(1.0, float(abs(pnl) / limit))

    def drawdown_scale(self) -> float:
        """0..1 size scale based on graduated drawdown throttle.

        Scale is 1.0 below DRAWDOWN_THROTTLE_FLOOR_FRAC of the daily limit, then
        decays linearly to DRAWDOWN_SCALE_MIN at the limit.
        """
        f = self.drawdown_fraction()
        if f <= DRAWDOWN_THROTTLE_FLOOR_FRAC:
            return 1.0
        # Linear from 1.0 at FLOOR → DRAWDOWN_SCALE_MIN at 1.0 (the limit).
        excess = f - DRAWDOWN_THROTTLE_FLOOR_FRAC
        room = max(1.0 - DRAWDOWN_THROTTLE_FLOOR_FRAC, 1e-6)
        scale = 1.0 - (1.0 - DRAWDOWN_SCALE_MIN) * (excess / room)
        return max(DRAWDOWN_SCALE_MIN, min(1.0, scale))

    def state_snapshot(self) -> dict:
        """Diagnostic snapshot for the risk dashboard."""
        return {
            "daily_pnl_usdt": float(self._daily_pnl()),
            "daily_loss_limit_usdt": float(self._daily_loss_limit_usdt()),
            "drawdown_fraction": round(self.drawdown_fraction(), 4),
            "drawdown_scale": round(self.drawdown_scale(), 4),
            "halt_on_drawdown": bool(self.c.halt_on_drawdown),
            "max_concurrent_positions": self.c.max_concurrent_positions,
        }
