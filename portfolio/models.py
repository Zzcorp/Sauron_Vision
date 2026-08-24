"""Portfolio tracking models."""
from django.db import models
from instruments.models import Instrument
from strategies.models import Strategy


class Portfolio(models.Model):
    name = models.CharField(max_length=100, default="Main")
    initial_capital = models.DecimalField(max_digits=20, decimal_places=2)
    current_value = models.DecimalField(max_digits=20, decimal_places=2)
    cash_available = models.DecimalField(max_digits=20, decimal_places=2)
    currency = models.CharField(max_length=10, default="EUR")

    max_total_exposure_pct = models.FloatField(default=100)
    # 20, to agree with sizing.DEFAULT_MAX_NOTIONAL_FRACTION.
    #
    # These four fields enforced nothing until the risk gate was wired: their
    # only reader was a legacy runner with no beat entry. The moment they
    # became real gates, the shipped 10 refused the platform's OWN default
    # trade — AssetBotConfig.capital and a fresh book are both seeded at
    # 10,000, so a 10% single-position ceiling is 1,000 while the sizing
    # engine allows 20% of the pool, 2,000. Two numbers describing different
    # pools that happen to seed identically, contradicting each other.
    #
    # The sizing fraction is the tuned one — it carries per-class overrides
    # and is what every position has actually been sized by. The 10 here was
    # a form default that had never been tested against a real entry, so it
    # moves. An operator who wants a tighter ceiling than the sizing engine
    # still sets one; what they no longer get is a first trade refused by
    # arithmetic between two of our own defaults.
    max_single_position_pct = models.FloatField(default=20)
    max_sector_exposure_pct = models.FloatField(default=30)
    max_correlation_threshold = models.FloatField(default=0.7)
    max_daily_loss_pct = models.FloatField(default=3.0)
    # How many open tickets may express the same directional currency bet
    # (long EUR, short USD, ...) before the next one is refused. A COUNT,
    # not a percentage: the failure it exists for is six tickets wearing
    # the costume of six decisions when they are one EUR bet, each leg
    # individually inside every money limit. 0 disables the gate — read
    # through `risk_gate._limit_pct` like its siblings, enforced by
    # `risk_gate.theme_state`. Default 3: the number the concentration
    # briefings kept asking for while nothing bound it.
    max_theme_legs = models.IntegerField(default=3)

    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} ({self.currency} {self.current_value})"


class Position(models.Model):
    portfolio = models.ForeignKey(Portfolio, on_delete=models.CASCADE, related_name="positions")
    instrument = models.ForeignKey(Instrument, on_delete=models.CASCADE)
    strategy = models.ForeignKey(Strategy, on_delete=models.SET_NULL, null=True, blank=True, related_name="positions")

    direction = models.CharField(max_length=10)
    quantity = models.DecimalField(max_digits=20, decimal_places=8)
    entry_price = models.DecimalField(max_digits=20, decimal_places=8)
    current_price = models.DecimalField(max_digits=20, decimal_places=8)
    stop_loss = models.DecimalField(max_digits=20, decimal_places=8, null=True)
    take_profit = models.DecimalField(max_digits=20, decimal_places=8, null=True)

    unrealized_pnl = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    unrealized_pnl_pct = models.FloatField(default=0)

    opened_at = models.DateTimeField()
    closed_at = models.DateTimeField(null=True, blank=True)

    @property
    def pnl_on_capital_pct(self):
        """P&L as % of the capital this row ties up — the same second
        percentage every UnifiedPosition carries, so the two row kinds
        stay interchangeable in the templates. Legacy rows are the setup
        form's and the eToro sync's (stocks/ETFs, no value_per_unit), so
        capital_at_work usually equals notional here — but a forex row a
        migration ever lands in this table must not silently print the
        levered number as its cash return."""
        from portfolio.services import pnl_on_capital_pct
        notional = abs(float(self.entry_price or 0)
                       * float(self.quantity or 0))
        # None passes THROUGH: the column is non-nullable but the live
        # re-price writes None in memory for an unpriced row, and `or 0`
        # here turned that unmeasured value into a confident +0.00% — the
        # exact zero the service's own fence exists to refuse.
        pnl = self.unrealized_pnl
        return pnl_on_capital_pct(
            None if pnl is None else float(pnl),
            getattr(self.instrument, "asset_class", ""), notional)

    class Meta:
        ordering = ["-opened_at"]


class PortfolioSnapshot(models.Model):
    portfolio = models.ForeignKey(Portfolio, on_delete=models.CASCADE, related_name="snapshots")
    date = models.DateField()
    total_value = models.DecimalField(max_digits=20, decimal_places=2)
    cash = models.DecimalField(max_digits=20, decimal_places=2)
    daily_pnl = models.DecimalField(max_digits=20, decimal_places=2)
    daily_pnl_pct = models.FloatField()
    cumulative_pnl_pct = models.FloatField()
    max_drawdown = models.FloatField()
    sharpe_ratio = models.FloatField(null=True)

    exposure_by_asset_class = models.JSONField(default=dict)
    exposure_by_sector = models.JSONField(default=dict)
    exposure_by_currency = models.JSONField(default=dict)
    correlation_matrix = models.JSONField(default=dict)

    class Meta:
        unique_together = ["portfolio", "date"]
        ordering = ["-date"]
