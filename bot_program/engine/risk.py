"""Risk manager — enforces per-trade and account-level limits."""
from __future__ import annotations
from decimal import Decimal
from django.utils import timezone
from datetime import timedelta

class RiskManager:
    def __init__(self, config):
        self.c = config

    def can_open_new(self) -> tuple[bool, str]:
        from ..models import BotTrade
        open_trades = BotTrade.objects.filter(config=self.c, status="OPEN").count()
        if open_trades >= self.c.max_concurrent_positions:
            return (False, f"max {self.c.max_concurrent_positions} concurrent positions reached")

        # Daily loss limit
        since = timezone.now() - timedelta(hours=24)
        closed = BotTrade.objects.filter(config=self.c, status="CLOSED", closed_at__gte=since)
        pnl = sum((t.pnl_usdt for t in closed), Decimal(0))
        limit = -self.c.capital_usdt * Decimal(self.c.max_daily_loss_pct / 100)
        if pnl <= limit and self.c.halt_on_drawdown:
            return (False, f"daily loss limit hit ({pnl:.2f} USDT)")
        return (True, "ok")

    def position_size(self, price: float) -> float:
        cap = float(self.c.capital_usdt)
        dollars = cap * (self.c.position_size_pct / 100.0) * self.c.leverage
        if price <= 0: return 0
        return round(dollars / price, 6)
