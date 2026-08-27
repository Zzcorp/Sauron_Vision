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
from zoneinfo import ZoneInfo

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


def _in_zone(moment: datetime, zone: str) -> Optional[datetime]:
    """`moment` read on `zone`'s clock, or None if the tz database is absent."""
    try:
        return moment.astimezone(ZoneInfo(zone))
    except Exception as e:  # noqa: BLE001 - missing tzdata must not kill a tick
        logger.warning("[forex] no timezone data for %s (%s) — session "
                       "windows unavailable", zone, e)
        return None


# Major forex session windows, in each centre's OWN clock: (zone, open, close)
# in local hours. Floats for the half-hours (the London 16:30 fix).
#
# They used to be a fixed UTC table — tokyo [0,6), london [7,15.5),
# new_york [13.5,20), sydney [21,24)+[0,5) — which no clock keeps. Those
# numbers are the liquid windows read in each centre's SUMMER time, so from
# November to mid-March the table refused the 16:00 London fix and cut New
# York off at 15:00 local, mid-session: the opposite of the liquidity
# rationale this module exists for, twice a year, for four months at a time.
#
# The WIDTHS are the old ones exactly — Tokyo 6h, London 8.5h, New York 6.5h,
# Sydney 8h. This is a correction to WHEN each window falls, not an opening
# of the filter: a session filter that admits more hours is a different risk
# posture than the operator configured, and nothing here was asked to change
# that.
SESSION_WINDOWS_LOCAL: dict[str, tuple[str, float, float]] = {
    "tokyo":     ("Asia/Tokyo",        9.0, 15.0),   # 6h   (was 00:00-06:00Z)
    "london":    ("Europe/London",     8.0, 16.5),   # 8.5h (was 07:00-15:30Z)
    "new_york":  ("America/New_York",  9.5, 16.0),   # 6.5h (was 13:30-20:00Z)
    "sydney":    ("Australia/Sydney",  8.0, 16.0),   # 8h   (was 21:00-05:00Z)
}

# The weekly window, anchored to New York because that is where the
# convention is set: FX opens Sunday 17:00 ET and closes Friday 17:00 ET.
# Anchoring it to a zone rather than to fixed UTC hours means the boundary
# does not drift by an hour twice a year.
MARKET_TZ = "America/New_York"
MARKET_OPEN_HOUR_LOCAL = 17.0


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


def forex_market_open(now: Optional[datetime] = None) -> bool:
    """True while the FX week is running: Sunday 17:00 ET -> Friday 17:00 ET.

    Separate from `_active_forex_sessions` on purpose. The two questions have
    different answers for a couple of hours every weekday — no major centre
    is in session between the New York close and the Sydney open — and
    conflating them is what had the fleet reporting an open market as the
    weekend.
    """
    now = now or timezone.now()
    local = _in_zone(now, MARKET_TZ)
    if local is None:  # no tz database — assume open rather than halt the fleet
        return True
    hour = local.hour + local.minute / 60.0
    weekday = local.weekday()  # Monday=0, Sunday=6
    if weekday == 5:                                        # Saturday
        return False
    if weekday == 6 and hour < MARKET_OPEN_HOUR_LOCAL:      # Sunday pre-open
        return False
    if weekday == 4 and hour >= MARKET_OPEN_HOUR_LOCAL:     # Friday post-close
        return False
    return True


def _active_forex_sessions(now: Optional[datetime] = None) -> set[str]:
    """The set of major centres currently in session.

    Empty over the weekend, and empty during the genuine quiet hours between
    one centre's close and the next one's open. Callers must not read "empty"
    as "weekend" — ask `forex_market_open()` for that.
    """
    now = now or timezone.now()
    if not forex_market_open(now):
        return set()

    active: set[str] = set()
    for name, (zone, start, end) in SESSION_WINDOWS_LOCAL.items():
        local = _in_zone(now, zone)
        if local is None:
            continue
        if local.weekday() >= 5:  # no centre trades its own weekend
            continue
        hour = local.hour + local.minute / 60.0
        if start <= hour < end:
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

        now = timezone.now()
        if not forex_market_open(now):
            return BotDecision("HOLD", 0, ["forex market closed (weekend)"])

        # An empty session set is NOT the weekend. Reporting it as one sent
        # the operator into the weekend logic to explain refusals that were
        # really "no major centre is open right now" — a real state for an
        # hour or two each weekday, and the message has to say so.
        active = _active_forex_sessions(now)
        if not active:
            return BotDecision("HOLD", 0, [
                "no major forex session is open right now — the market is "
                "running but every centre this filter watches is closed"
            ])

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
