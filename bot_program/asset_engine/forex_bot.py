"""ForexBot — FX pairs via OANDA (per Phase-4 broker_router).

Session-aware: skips entries outside preferred sessions per pair. Liquidity is
the dominant factor for FX edge — a EURUSD breakout fired at 03:00 UTC (Tokyo
session, no euro-zone activity) behaves very differently from the same setup
at 14:00 UTC (London/NY overlap). The bot respects this by default; admin can
disable or override via `extras`.

OANDA quotes in *units* of base currency. A "standard lot" = 100,000 units.
"""
from datetime import datetime
from typing import Optional

from django.utils import timezone

from .base import AssetBot, BotDecision


# A standard lot in OANDA convention.
STANDARD_LOT = 100_000

# Round units to the nearest multiple of this for OANDA. 1 unit is technically
# the smallest tradable, but we round to 100 for tidier paper trades.
UNIT_ROUNDING = 100


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

    def _round_qty(self, qty: float, price: float) -> float:
        """Round to a tidy unit boundary, with a floor of one boundary.

        NB: for a pair whose quote currency is not the account currency, the
        stop distance is in QUOTE units, so the risk budget is only correct
        after conversion. USDJPY at 150 with a 1.5% stop is 2.25 JPY per
        unit, not 2.25 USD. Until the conversion exists, forex risk is
        denominated in the quote currency — recorded in entry_meta so the
        distortion is visible rather than silent.
        """
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
