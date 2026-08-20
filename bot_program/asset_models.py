"""Phase-13 multi-asset bot models.

Parallel structure to the existing crypto-only `BotConfig` / `BotTrade`:
  - The crypto bot stays untouched (same models, same runner).
  - This module introduces `AssetBotConfig` + `AssetBotTrade` for stocks,
    forex, and commodities, routed through Phase-4's broker_router.

Options are not modelled here — they require Greeks/IV/chain handling
that belongs in a dedicated phase.
"""
import logging

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models

logger = logging.getLogger(__name__)


# ── The one exit no broker can fire ─────────────────────────────────────────
# A bracket holds the stop and the target; nothing at any broker releases
# capital from a thesis that simply never moved. The engine has always had a
# time stop and nothing ever set its ceiling, so it was off everywhere and
# positions were unbounded in time.
#
# These are the ceilings a config INHERITS when its own `max_hold_hours` is
# blank. Each is the longest thesis its class declares in the seeded strategy
# packs (signals/management/commands/seed_strategies.py and
# seed_advanced_strategies.py), read on the wall clock the time stop actually
# measures: `suggested_horizon_days` is calendar days — opportunity_scanner
# resolves a flag at `scanned_at + timedelta(days=horizon_days)` — but a
# thesis only advances while its market is open, so a class that shuts at the
# weekend needs the calendar allowance or the ceiling fires INSIDE the horizon
# it exists to outlive.
#
# They are backstops, not exit strategies. A config that trades one narrow
# family of setups should be tightened by hand — which is the entire reason
# `max_hold_hours` is now a visible field instead of a key buried in a JSON
# blob nobody sets.
DEFAULT_MAX_HOLD_HOURS = {
    # Longest equity thesis: starter_stock_momentum at 10 days. Equities
    # advance a thesis for ~6.5h of each of 5 days a week, so 10 market days
    # is ~14 days on the clock (10 x 7/5) — two weekends. 336h lets the
    # longest equity setup run its full declared length; anything shorter can
    # fire with a trading week still to go once a holiday lands in the window.
    "stock": 336.0,
    # FX carries the widest spread of theses in the fleet: a 3-day breakout on
    # a 1.0% stop (starter_forex_breakout) and a 21-day macro composite on a
    # 2.0% stop (starter_usd_weakness_macro) trade the SAME symbol lists, and
    # decide() only reveals which rule won after the entry exists. A class
    # default that suited the breakout would silently truncate every macro
    # trade — converting winners into TIME exits and poisoning the macro
    # rule's own track record — so the default covers the longest: 21 days on
    # a 24/5 calendar is ~29.4 days, rounded up to 30. The honest ceiling for
    # a breakout-only book is nearer 96h, and that is exactly the number an
    # operator now types into a field instead of discovering there was none.
    "forex": 720.0,
    # Same two setups reach commodities (starter_commodity_vol_compression at
    # 14 days, starter_usd_weakness_macro at 21), on a near-24/5 calendar.
    "commodity": 720.0,
    # Longest crypto thesis: advanced_capitulation_buy at 7 days. Crypto is
    # 24/7, so there is no calendar stretch to absorb the slack every other
    # class gets for free — one whole day is added instead, because the trade
    # opens up to a bar after the signal and the manage loop skips any tick
    # where the mark is missing. A ceiling equal to the horizon would cut
    # theses that are still inside it.
    "crypto": 192.0,
    # OptionsBot has no setups of its own — it takes the base decide() verdict
    # on the UNDERLYING, so its theses are the equity pack's and the longest
    # is again 10 days. It does NOT get the equity calendar stretch: options
    # are the one class where waiting costs money outright, so past the
    # literal 10 days the contract is paying theta on a view that never
    # appeared. Note the interaction with the expiry gate — a 14-DTE contract
    # (DEFAULT_MIN_DTE) is force-closed at DEFAULT_CLOSE_BEFORE_DTE, i.e. day
    # 9, so on the shortest contracts the more specific rule fires first and
    # this ceiling only binds on longer-dated ones, which is the right way
    # round.
    "options": 240.0,
    # No AssetBot implementation exists for cfd (make_bot raises on it), but a
    # config can still be created for the class. CFDs here wrap equities and
    # indices, so they inherit the equity ceiling rather than being the one
    # row in this table with no answer at all.
    "cfd": 336.0,
}

# An asset_class this table has never heard of still gets a ceiling. The
# alternative is `.get(...) or 0`, and 0 means "no time stop" — a typo in an
# asset_class would then silently restore the unbounded behaviour this whole
# table exists to end.
UNKNOWN_CLASS_MAX_HOLD_HOURS = 336.0

# The pre-field home of this setting. Still read at runtime (see
# `time_stop_setting`) so an install that already set it keeps the ceiling it
# was running with; the migration and the settings form both drain it into the
# field, so it is an inlet, not a second source of truth.
LEGACY_MAX_HOLD_EXTRAS_KEY = "max_hold_hours"


class AssetBotConfig(models.Model):
    """One bot configuration per (user, asset_class, name).

    Asset-class is the discriminator that drives broker routing and the
    concrete `AssetBot` subclass that owns this config's tick.
    """

    ASSET_CLASS_CHOICES = [
        ("stock", "Stocks"),
        ("forex", "Forex"),
        ("commodity", "Commodities"),
        ("options", "Options"),
        # Crypto is the only class whose market data is free and keyless, so
        # it is the one route from a fresh install to a graded paper trade
        # without a broker relationship.
        ("crypto", "Crypto"),
        ("cfd", "CFDs"),
    ]
    MODE_CHOICES = [
        ("paper", "Paper Trading (simulated, safe)"),
        ("live", "Live Trading (real funds)"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="asset_bot_configs",
    )
    asset_class = models.CharField(max_length=12, choices=ASSET_CLASS_CHOICES, db_index=True)
    name = models.CharField(max_length=80, default="Asset Bot")
    enabled = models.BooleanField(default=False)
    mode = models.CharField(max_length=8, choices=MODE_CHOICES, default="paper")

    # Universe + capital.
    symbols = models.JSONField(default=list, help_text='Symbols, e.g. ["AAPL","MSFT"] for stocks.')
    capital = models.DecimalField(max_digits=14, decimal_places=2, default=10000)
    base_currency = models.CharField(max_length=10, default="USD")

    # Sizing & risk.
    position_size_pct = models.FloatField(default=2.0,
        help_text="% of capital per new position.")
    max_concurrent_positions = models.IntegerField(default=5)
    max_daily_loss_pct = models.FloatField(default=2.0)
    stop_loss_pct = models.FloatField(default=1.5)
    take_profit_pct = models.FloatField(default=3.0)

    # Decision thresholds — used by `decide()` when consuming Signal rows.
    entry_score_min = models.FloatField(default=0.60)
    exit_score_max = models.FloatField(default=0.35)
    min_signals_for_entry = models.IntegerField(default=1,
        help_text="Minimum number of active Signals confirming the same direction to enter.")

    # Timing.
    timeframe = models.CharField(max_length=8, default="1h")
    cool_down_minutes = models.IntegerField(default=60)
    max_hold_hours = models.FloatField(
        null=True, blank=True, validators=[MinValueValidator(0.0)],
        help_text=(
            "Hours a position may stay open before the engine flattens it "
            "with reason TIME. 0 = no time stop (positions are then unbounded "
            "in time — only the stop, the target or an operator will close "
            "them). Leave blank to inherit the asset-class default."))

    # Safety toggles.
    halt_on_drawdown = models.BooleanField(default=True)
    halt_on_high_impact_news = models.BooleanField(default=False)

    # Asset-class-specific extras (overnight handling, lot sizing rules, etc.).
    extras = models.JSONField(default=dict, blank=True)

    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["asset_class", "name"]
        unique_together = [("user", "asset_class", "name")]
        indexes = [
            models.Index(fields=["enabled", "asset_class"]),
        ]

    def __str__(self):
        return f"{self.user.username} · {self.asset_class.upper()} · {self.name} [{self.mode}]"

    # ── time stop resolution ─────────────────────────────────────────────

    @classmethod
    def default_max_hold_hours(cls, asset_class: str) -> float:
        """The ceiling a config of `asset_class` inherits when its own is blank."""
        return float(DEFAULT_MAX_HOLD_HOURS.get(
            (asset_class or "").lower(), UNKNOWN_CLASS_MAX_HOLD_HOURS))

    def time_stop_setting(self) -> dict:
        """The ceiling this config actually enforces, and where it came from.

        Returns {"hours": float, "enabled": bool, "source": str}. `hours` is
        0.0 exactly when the time stop is off, so callers never have to
        distinguish "unset" from "disabled" — this method already did.

        Precedence, and why it is this way round:

          1. `extras["max_hold_hours"]`, when present and numeric. This is
             where the setting used to live. An install that already set it is
             running with a ceiling it chose, and a schema change that
             silently swapped that for a class default would move a live
             risk knob without anyone asking. So the legacy key still wins —
             but both writers that this platform owns (the migration that
             introduced the field, and the settings form) LIFT it into the
             field and delete it, so it drains rather than accumulating.
          2. `max_hold_hours`, when set. The visible setting.
          3. `DEFAULT_MAX_HOLD_HOURS[asset_class]`. Blank means "track what
             the platform believes about this class", so a correction to the
             table reaches every unset config instead of only new ones.

        A present-but-unparseable legacy value falls THROUGH to 2/3 rather
        than to "off". extras is hand-edited JSON and `"24h"` is the obvious
        typo; treating it as a disabled time stop would let a typo silently
        remove risk management, which is the one outcome worth ruling out.
        """
        extras = self.extras or {}
        if LEGACY_MAX_HOLD_EXTRAS_KEY in extras:
            raw = extras.get(LEGACY_MAX_HOLD_EXTRAS_KEY)
            try:
                hours = float(raw)
            except (TypeError, ValueError):
                logger.warning(
                    "[asset_bot] cfg %s: extras[%r]=%r is not numeric — "
                    "falling back to the configured/class ceiling rather than "
                    "disabling the time stop", self.pk,
                    LEGACY_MAX_HOLD_EXTRAS_KEY, raw)
            else:
                hours = max(0.0, hours)
                return {"hours": hours, "enabled": hours > 0,
                        "source": "extras"}

        if self.max_hold_hours is not None:
            hours = max(0.0, float(self.max_hold_hours))
            return {"hours": hours, "enabled": hours > 0, "source": "config"}

        hours = self.default_max_hold_hours(self.asset_class)
        return {"hours": hours, "enabled": hours > 0, "source": "class-default"}

    def effective_max_hold_hours(self) -> float:
        """Hours before the time stop fires; 0.0 when it is off."""
        return self.time_stop_setting()["hours"]


class AssetBotTrade(models.Model):
    """A trade opened by an AssetBot. Parallel to the crypto BotTrade."""

    SIDE_CHOICES = [("BUY", "Buy"), ("SELL", "Sell")]
    STATUS_CHOICES = [
        ("OPEN", "Open"),
        # Broker close order failed — the position is still open at the
        # broker while the bot wants it flat. Drained by the
        # retry_pending_closes beat task; counts as exposure everywhere.
        ("CLOSE_PENDING", "Close pending"),
        ("CLOSED", "Closed"),
        ("CANCELED", "Canceled"),
        ("ERROR", "Error"),
    ]

    config = models.ForeignKey(AssetBotConfig, on_delete=models.CASCADE,
                                related_name="trades")
    # Denormalized for fast filtering even when config is deleted.
    asset_class = models.CharField(max_length=12, db_index=True)
    symbol = models.CharField(max_length=40, db_index=True)
    side = models.CharField(max_length=4, choices=SIDE_CHOICES)

    qty = models.DecimalField(max_digits=18, decimal_places=8)
    entry_price = models.DecimalField(max_digits=18, decimal_places=8)
    exit_price = models.DecimalField(max_digits=18, decimal_places=8, null=True, blank=True)
    stop_loss = models.DecimalField(max_digits=18, decimal_places=8, null=True, blank=True)
    take_profit = models.DecimalField(max_digits=18, decimal_places=8, null=True, blank=True)

    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="OPEN")
    pnl = models.DecimalField(max_digits=14, decimal_places=4, default=0,
        help_text="Realized P&L in the config's base_currency.")
    composite_score = models.FloatField(default=0)
    reason = models.TextField(blank=True)

    # Tag the rule that triggered this trade so Phase 1–12 grade it
    # the same way they grade Signal rows.
    rule_name = models.CharField(max_length=100, blank=True, db_index=True)

    paper = models.BooleanField(default=True)
    broker_order_id = models.CharField(max_length=128, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    opened_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    # ── Phase 17 self-grading (parallel to Signal.realized_r) ───────
    # Set on close. realized_r normalises P&L by initial-risk (entry-to-stop
    # distance) so trades across symbols, asset classes, and sizes are
    # directly comparable. duration_minutes feeds time-to-outcome stats.
    OUTCOME_CHOICES = [
        ("hit_target", "Hit Target"),
        ("stopped_out", "Stopped Out"),
        ("manual_close", "Manually Closed"),
        ("expired", "Expired"),
        # A time-stop exit is its own answer, not a variant of the others.
        # Before this it graded as `manual_close` — the engine's own risk
        # decision recorded as a human's — and a rule whose trades keep
        # timing out says something a stop-out does not: the setup fires on
        # moves that never materialise, so the fix is the entry or the
        # horizon, not the stop. `expired` is already taken by the options
        # expiry gate, which is a different event (the CONTRACT ran out, not
        # the thesis).
        ("time_stop", "Time Stop"),
    ]
    outcome = models.CharField(max_length=20, choices=OUTCOME_CHOICES, blank=True, db_index=True)
    realized_r = models.FloatField(null=True, blank=True)
    duration_minutes = models.IntegerField(null=True, blank=True)

    class Meta:
        ordering = ["-opened_at"]
        indexes = [
            models.Index(fields=["config", "status"]),
            models.Index(fields=["asset_class", "-opened_at"]),
            models.Index(fields=["rule_name", "-opened_at"]),
        ]

    def __str__(self):
        return f"{self.asset_class}/{self.symbol} {self.side} {self.qty} @ {self.entry_price}"
