"""ForexBot — FX pairs via OANDA (per Phase-4 broker_router).

Session-aware: skips entries outside preferred sessions per pair. Liquidity is
the dominant factor for FX edge — a EURUSD breakout fired at 03:00 UTC (Tokyo
session, no euro-zone activity) behaves very differently from the same setup
at 14:00 UTC (London/NY overlap). The bot respects this by default; admin can
disable or override via `extras`.

OANDA quotes in *units* of base currency. A "standard lot" = 100,000 units.
"""
import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional

from django.utils import timezone

from .base import AssetBot, BotDecision

logger = logging.getLogger(__name__)


# A standard lot in OANDA convention.
STANDARD_LOT = 100_000

# Round units to the nearest multiple of this for OANDA. 1 unit is technically
# the smallest tradable, but we round to 100 for tidier paper trades.
UNIT_ROUNDING = 100

# Freshness rules for the conversion rate, mirroring PaperTrader: a LiveQuote
# older than 15 minutes is a fossil, a bar older than 6 hours likewise.
RATE_MAX_QUOTE_AGE_SECONDS = 900
RATE_MAX_BAR_AGE_HOURS = 6


def quote_ccy_usd_rate(quote: str) -> Optional[float]:
    """USD per one unit of `quote` currency, from the freshest source.

    Tries the direct pair (GBPUSD for GBP), then the inverse (USDJPY for
    JPY) — LiveQuote first, then the newest 1h/4h bar. The forex quote
    poller covers the whole catalogue keylessly, so in practice the direct
    or inverse major is always marked. None when nothing usable exists.
    """
    quote = (quote or "").upper()
    if quote == "USD":
        return 1.0

    def _live(sym):
        from market_data.models import LiveQuote
        lq = LiveQuote.objects.filter(instrument__symbol=sym).first()
        if lq and lq.last:
            age = (timezone.now() - lq.updated_at).total_seconds()
            if age <= RATE_MAX_QUOTE_AGE_SECONDS:
                return float(lq.last)
        return None

    def _bar(sym):
        from market_data.models import PriceData
        cutoff = timezone.now() - timedelta(hours=RATE_MAX_BAR_AGE_HOURS)
        pd = (PriceData.objects
              .filter(instrument__symbol=sym, timeframe__in=("1h", "4h"),
                      timestamp__gte=cutoff)
              .order_by("-timestamp").first())
        return float(pd.close) if pd else None

    direct, inverse = f"{quote}USD", f"USD{quote}"
    for getter in (_live, _bar):
        rate = getter(direct)
        if rate and rate > 0:
            return rate
        inv = getter(inverse)
        if inv and inv > 0:
            return 1.0 / inv
    return None


def forex_usd_multiplier(trade) -> Decimal:
    """USD per quote-currency unit for this trade — FIXED AT ENTRY.

    The forex analogue of option_pnl_multiplier, and it must be applied the
    same way: to the P&L on EVERY close path (bot close, kill switch,
    pending-close retries, reconciliation) AND to the risk denominator in
    grading. Both sides multiplying by the SAME number is what keeps
    realized_r exactly price-based — the first version converted only the
    bot-path P&L at a close-time rate, so a JPY stop-out graded at −0.0067
    instead of −1.0 and the daily-loss gate summed yen next to dollars.

    The entry-time rate is read from metadata["value_per_unit"], recorded
    by sizing at open (a forex trade cannot open without it — no rate sizes
    to zero). Legacy rows without it fall back to the live rate, then to 1
    (quote-currency, the pre-conversion behaviour, still self-consistent).
    """
    if getattr(trade, "asset_class", "") != "forex":
        return Decimal("1")
    meta = getattr(trade, "metadata", None) or {}
    rate = meta.get("value_per_unit")
    if not rate:
        rate = quote_ccy_usd_rate((trade.symbol or "").upper()[3:])
    try:
        rate = Decimal(str(rate))
        return rate if rate > 0 else Decimal("1")
    except Exception:
        return Decimal("1")


# Major forex session windows in UTC (open_hour, close_hour). Floats so we can
# express the 30-min half-hours like London 15:30 close. close_hour > 24 means
# the session wraps past midnight UTC (used for Sydney).
SESSION_WINDOWS_UTC: dict[str, tuple[float, float]] = {
    "tokyo":     (0.0, 6.0),
    "london":    (7.0, 15.5),
    "new_york":  (13.5, 20.0),
    "sydney":    (21.0, 24.0 + 5.0),  # 21:00 UTC -> 05:00 UTC next day
}


# Default preferred sessions per pair. Pairs absent from this map default to
# {"london", "new_york"} (the highest-liquidity overlap window for most pairs).
DEFAULT_PREFERRED_SESSIONS: dict[str, set[str]] = {
    # Majors
    "EURUSD": {"london", "new_york"},
    "GBPUSD": {"london", "new_york"},
    "USDJPY": {"tokyo", "new_york"},
    "USDCHF": {"london", "new_york"},
    "USDCAD": {"new_york"},
    "AUDUSD": {"sydney", "tokyo"},
    "NZDUSD": {"sydney", "tokyo"},
    # JPY crosses
    "EURJPY": {"tokyo", "london"},
    "GBPJPY": {"tokyo", "london"},
    "AUDJPY": {"sydney", "tokyo"},
    # Crosses
    "EURGBP": {"london"},
    "EURAUD": {"sydney", "london"},
}


def _active_forex_sessions(now: Optional[datetime] = None) -> set[str]:
    """Return the set of currently-active forex sessions in UTC.

    Returns an empty set on weekends — forex is closed Friday 21:00 UTC through
    Sunday 21:00 UTC.
    """
    now = now or timezone.now()
    weekday = now.weekday()  # Monday=0, Sunday=6
    hour_utc = now.hour + now.minute / 60.0

    # Closed all day Saturday.
    if weekday == 5:
        return set()
    # Closed Sunday before 21:00 UTC.
    if weekday == 6 and hour_utc < 21.0:
        return set()
    # Closed Friday from 21:00 UTC onward.
    if weekday == 4 and hour_utc >= 21.0:
        return set()

    active: set[str] = set()
    for name, (start, end) in SESSION_WINDOWS_UTC.items():
        if end > 24:
            # Session wraps past midnight.
            if hour_utc >= start or hour_utc < (end - 24):
                active.add(name)
        elif start <= hour_utc < end:
            active.add(name)
    return active


class ForexBot(AssetBot):
    asset_class = "forex"

    # ── decide(): session-aware override ─────────────────────────────────

    def decide(self, symbol: str) -> BotDecision:
        """Skip entry outside the pair's preferred sessions; otherwise delegate."""
        extras = self.cfg.extras or {}
        if extras.get("session_filter_disabled"):
            return super().decide(symbol)

        active = _active_forex_sessions()
        if not active:
            return BotDecision("HOLD", 0, ["forex market closed (weekend)"])

        # Optional per-config override: extras["preferred_sessions"]["EURUSD"] = ["london"]
        config_override = (extras.get("preferred_sessions") or {}).get(symbol)
        if config_override:
            preferred = set(config_override)
        else:
            preferred = DEFAULT_PREFERRED_SESSIONS.get(symbol, {"london", "new_york"})

        if not (preferred & active):
            return BotDecision("HOLD", 0, [
                f"{symbol} outside preferred sessions "
                f"(prefer: {','.join(sorted(preferred))}; active: {','.join(sorted(active))})"
            ])

        # Inside a preferred session — fall through to default Signal-consuming decide().
        return super().decide(symbol)

    # ── sizing ───────────────────────────────────────────────────────────

    def _value_per_unit(self, symbol: str) -> float:
        """Account-currency (USD) value of one quote-currency point, per unit.

        The stop distance handed to sizing is in the pair's QUOTE currency:
        USDJPY at 150 with a 2.25-point stop risks 2.25 JPY per unit, not
        2.25 USD. Dividing a USD risk budget by a JPY distance under-sized
        JPY pairs ~150x — 11 units, rounded to zero, so the bot ticked
        forever logging SIZED_TO_ZERO — and mis-sized every other cross by
        its rate (EURGBP by ~27%). The conversion is the quote->USD rate;
        with no usable rate the position sizes to zero rather than to a
        wrong number.
        """
        quote = (symbol or "").upper()[3:]
        rate = quote_ccy_usd_rate(quote)
        if rate is None:
            logger.warning("[forex sizing] no fresh %s->USD rate — %s sizes "
                           "to zero rather than to a wrong number",
                           quote, symbol)
            return 0.0
        return rate

    def _trade_pnl(self, trade, price: Decimal) -> Decimal:
        """Quote-currency P&L converted at the trade's ENTRY-TIME rate —
        the same shape as OptionsBot applying its contract multiplier.
        Grading multiplies its risk denominator by the identical number,
        so realized_r stays exactly price-based whatever the rate does."""
        return super()._trade_pnl(trade, price) * forex_usd_multiplier(trade)

    def _round_qty(self, qty: float, price: float) -> float:
        """Round to a tidy unit boundary; a fraction below half a boundary
        sizes to zero (recorded as SIZED_TO_ZERO upstream)."""
        units = round(float(qty) / UNIT_ROUNDING) * UNIT_ROUNDING
        return float(max(units, 0.0))

    def position_size(self, price: float) -> float:
        """LEGACY notional sizing — see AssetBot.position_size.

        For forex the "qty" is units of the base currency, not shares. The bot's
        sizing here intentionally errs on the small side — admin can scale up via
        position_size_pct or explicit `extras = {"forex_units_per_pct": 1000}`
        in the AssetBotConfig.

        Override extras['forex_units_per_pct'] to use unit-count sizing directly
        (skipping the dollar conversion) — useful when the broker accounts for
        leverage internally.
        """
        cap = float(self.cfg.capital)
        forced_units_per_pct = (self.cfg.extras or {}).get("forex_units_per_pct")
        if forced_units_per_pct:
            try:
                units = float(forced_units_per_pct) * float(self.cfg.position_size_pct)
            except (TypeError, ValueError):
                units = 0
        else:
            dollars = cap * (self.cfg.position_size_pct / 100.0)
            if price <= 0:
                return 0.0
            units = dollars / price

        if units <= 0:
            return 0.0
        # Round to a tidy unit boundary.
        units = round(units / UNIT_ROUNDING) * UNIT_ROUNDING
        return float(max(units, UNIT_ROUNDING))
