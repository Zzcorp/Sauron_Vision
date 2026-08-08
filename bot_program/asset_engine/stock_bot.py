"""StockBot — equities + ETFs via Alpaca (per Phase-4 broker_router).

Earnings-aware: skips new entries within the earnings blackout window.
Earnings nights produce gaps that blow through stop levels — opening fresh
positions into that risk is rarely intentional. Default is conservative
(skip 3 days before earnings); admin can disable or tune via `extras`.

Sizing rounds to whole shares in live mode; fractional ok in paper.
"""
from datetime import timedelta

from django.utils import timezone

from .base import AssetBot, BotDecision


# Default lookahead window: skip entries when earnings are this close.
DEFAULT_EARNINGS_BLACKOUT_DAYS = 3


def _has_upcoming_earnings(symbol: str, days_ahead: int = DEFAULT_EARNINGS_BLACKOUT_DAYS,
                           now=None) -> tuple[bool, str]:
    """Check if `symbol` has an upcoming earnings event within `days_ahead`.

    Looks at `EconomicEvent` rows where the title mentions both the symbol and
    "earnings". Returns (True, event_title) if found, else (False, "").

    Defensive: if EconomicEvent isn't available or the query fails, returns
    (False, "") so the bot doesn't HOLD on infrastructure problems.
    """
    if not symbol:
        return False, ""
    try:
        from market_data.models import EconomicEvent
    except Exception:
        return False, ""

    now = now or timezone.now()
    deadline = now + timedelta(days=days_ahead)

    from django.db.models import Q
    qs = EconomicEvent.objects.filter(
        datetime__gte=now, datetime__lte=deadline,
    ).filter(
        Q(title__icontains=symbol) | Q(currency_affected__iexact=symbol),
    ).filter(title__icontains="earnings")
    ev = qs.order_by("datetime").first()
    if ev is None:
        return False, ""
    return True, ev.title


class StockBot(AssetBot):
    asset_class = "stock"

    # ── decide(): earnings-aware override ────────────────────────────────

    def decide(self, symbol: str) -> BotDecision:
        """Skip new entries inside the earnings blackout window; otherwise delegate."""
        extras = self.cfg.extras or {}
        if extras.get("earnings_blackout_disabled"):
            return super().decide(symbol)

        try:
            days = int(extras.get("earnings_blackout_days", DEFAULT_EARNINGS_BLACKOUT_DAYS))
        except (TypeError, ValueError):
            days = DEFAULT_EARNINGS_BLACKOUT_DAYS

        in_blackout, ev_title = _has_upcoming_earnings(symbol, days_ahead=days)
        if in_blackout:
            return BotDecision("HOLD", 0, [
                f"{symbol} in earnings blackout (≤{days}d): \"{ev_title[:120]}\""
            ])

        return super().decide(symbol)

    # ── sizing ───────────────────────────────────────────────────────────

    def position_size(self, price: float) -> float:
        """Dollar-based, rounded to whole shares (paper mode tolerates fractional)."""
        cap = float(self.cfg.capital)
        dollars = cap * (self.cfg.position_size_pct / 100.0)
        if price <= 0:
            return 0.0
        # Whole shares for live; fractional ok in paper.
        if self.cfg.mode == "live":
            return float(int(dollars / price))
        return round(dollars / price, 4)
