"""Phase-13 multi-asset bot models.

Parallel structure to the existing crypto-only `BotConfig` / `BotTrade`:
  - The crypto bot stays untouched (same models, same runner).
  - This module introduces `AssetBotConfig` + `AssetBotTrade` for stocks,
    forex, and commodities, routed through Phase-4's broker_router.

Options are not modelled here — they require Greeks/IV/chain handling
that belongs in a dedicated phase.
"""
from django.conf import settings
from django.db import models


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
