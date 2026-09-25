"""StockBot — equities + ETFs via Alpaca (per Phase-4 broker_router).

Earnings-aware: skips new entries within the earnings blackout window.
Earnings nights produce gaps that blow through stop levels — opening fresh
positions into that risk is rarely intentional. Default is conservative
(skip 3 days before earnings); admin can disable or tune via `extras`.

Sizing rounds to whole shares in live mode — unless the client the router
hands the entry declares the `fractional_units` tier (eToro, as a belief
from the public reference) AND the fractional_units_live switch is
on, in which case the four decimals paper keeps; fractional ok in paper.
"""
import logging
from datetime import timedelta

from django.utils import timezone

from .base import AssetBot, BotDecision

logger = logging.getLogger(__name__)


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

    def decide(self, symbol: str, *,
               signal_stats: dict | None = None) -> BotDecision:
        """Skip new entries inside the earnings blackout window; otherwise delegate."""
        extras = self.cfg.extras or {}
        if extras.get("earnings_blackout_disabled"):
            return super().decide(symbol, signal_stats=signal_stats)

        try:
            days = int(extras.get("earnings_blackout_days", DEFAULT_EARNINGS_BLACKOUT_DAYS))
        except (TypeError, ValueError):
            days = DEFAULT_EARNINGS_BLACKOUT_DAYS

        in_blackout, ev_title = _has_upcoming_earnings(symbol, days_ahead=days)
        if in_blackout:
            return BotDecision("HOLD", 0, [
                f"{symbol} in earnings blackout (≤{days}d): \"{ev_title[:120]}\""
            ])

        return super().decide(symbol, signal_stats=signal_stats)

    # ── sizing ───────────────────────────────────────────────────────────

    def position_size(self, price: float) -> float:
        """LEGACY notional sizing — see AssetBot.position_size. Not on the
        entry path; _round_qty below is."""
        cap = float(self.cfg.capital)
        dollars = cap * (self.cfg.position_size_pct / 100.0)
        if price <= 0:
            return 0.0
        if self.cfg.mode == "live":
            return float(int(dollars / price))
        return round(dollars / price, 4)

    #: THIS platform's granularity on a venue that takes fractions — the four
    #: decimals paper keeps below, not the venue's step. eToro's step is
    #: unmeasured (its portfolio example carries six decimals); four is
    #: coarser than six, and a venue that takes 0.049485 takes 0.0495.
    #: crypto_bot.QTY_DECIMALS is the same kind of number.
    FRACTIONAL_DECIMALS = 4

    def _round_qty(self, qty: float, price: float, *,
                   fractional=None) -> float:
        """Whole shares live — unless the venue takes fractions; fractional
        tolerated in paper.

        `fractional` is THREE STATES, answered by the base class off the
        CLIENT the router handed the entry (`_venue_fractional_units`) and
        carried on the candidate so the second rounding in execute_entry
        uses the same answer: True (the client declares the
        `fractional_units` tier, said so for this symbol, and the
        fractional_units_live switch is ON — eToro, measured on its
        eligibility row, 2026-09-25), False (declared and said whole), None
        (declares nothing, raised, the switch is OFF, or nobody asked — the
        manual lane's `_qty_step` probe, every positional caller). None
        rounds exactly as before this seam existed: whole shares, the
        conservative reading of unmeasured. Only True changes the
        arithmetic, and only in live mode.

        int() truncation is why a live $10,000 config at 2% could not buy a
        $201 stock: int(200/201) == 0, and a zero qty exits the entry path
        with no log line. Risk sizing makes that far less likely — a 1.5%
        stop on a 0.25% risk budget buys ~$1,667 of notional, not $200 — but
        the floor still bites on very expensive shares, so it now says so.
        """
        if self.cfg.mode == "live":
            if fractional is True:
                snapped = round(float(qty), self.FRACTIONAL_DECIMALS)
                if snapped <= 0 and qty > 0:
                    logger.info(
                        "[stock_bot] %s at %.2f rounds to 0 at this "
                        "platform's %d-decimal granularity from %.8f — the "
                        "risk budget buys less than one ten-thousandth of "
                        "a share (the venue's own floor is asked next)",
                        self.cfg.name, price, self.FRACTIONAL_DECIMALS, qty)
                return snapped
            whole = float(int(qty))
            if whole <= 0 and qty > 0:
                logger.info(
                    "[stock_bot] %s at %.2f rounds to 0 whole shares from "
                    "%.4f — the risk budget is smaller than one share",
                    self.cfg.name, price, qty)
            return whole
        return round(float(qty), self.FRACTIONAL_DECIMALS)
