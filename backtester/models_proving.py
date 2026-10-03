"""The proving ground's verdicts (backtester/proving)."""
from django.db import models


class ProvingVerdict(models.Model):
    """One judged candidate: a family, its parameters, a direction and a
    filter, pooled over one asset class at one timeframe."""

    VERDICTS = [("proven", "Proven"), ("promising", "Promising"),
                ("failed", "Failed"), ("insufficient", "Insufficient")]

    run_id = models.CharField(max_length=40, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    family = models.CharField(max_length=40, db_index=True)
    #: The live rule this candidate IS (the family at its defaults, no
    #: filter, in a direction the rule trades); blank for a generated one.
    live_rule = models.CharField(max_length=100, blank=True, db_index=True)
    params = models.JSONField(default=dict)
    direction = models.CharField(max_length=5)
    filter = models.CharField(max_length=12, default="none")
    #: The exit policy the trades were run under (simulate.EXIT_POLICIES).
    policy = models.CharField(max_length=20, default="care")
    asset_class = models.CharField(max_length=20, db_index=True)
    timeframe = models.CharField(max_length=4, default="4h")
    generated = models.BooleanField(default=False)
    n_candidates = models.IntegerField(default=1)
    symbols_n = models.IntegerField(default=0)
    trades_n = models.IntegerField(default=0)
    holdout_n = models.IntegerField(default=0)
    expectancy = models.FloatField(null=True)
    holdout_expectancy = models.FloatField(null=True)
    lower_bound = models.FloatField(null=True)
    stressed_expectancy = models.FloatField(null=True)
    win_rate = models.FloatField(null=True)
    payoff = models.FloatField(null=True)
    max_dd_r = models.FloatField(null=True)
    positive_folds = models.IntegerField(default=0)
    verdict = models.CharField(max_length=12, choices=VERDICTS, db_index=True)
    why = models.TextField(blank=True)
    #: {regime: stats}, {exit reason: count}, the folds, the data window.
    detail = models.JSONField(default=dict)

    class Meta:
        app_label = "backtester"
        ordering = ["-created_at", "-lower_bound"]
        indexes = [models.Index(fields=["live_rule", "asset_class",
                                        "-created_at"])]

    def __str__(self):
        return (f"{self.family}/{self.direction}/{self.filter} "
                f"{self.asset_class}: {self.verdict}")


class ProvingTrade(models.Model):
    """One simulated trade behind a saved verdict — the setup memory
    (backtester/proving/memory.py) reads the newest ones back. 2026-10-03."""

    verdict = models.ForeignKey(ProvingVerdict, on_delete=models.CASCADE,
                                related_name="trades")
    symbol = models.CharField(max_length=40)
    entry_ts = models.DateTimeField()
    exit_ts = models.DateTimeField()
    #: Net of the round trip, in R against the stop the trade opened with.
    r = models.FloatField()
    #: The best R seen while open.
    mfe = models.FloatField(default=0.0)
    regime = models.CharField(max_length=16, default="")
    reason = models.CharField(max_length=24, default="")
    bars = models.IntegerField(default=0)

    class Meta:
        app_label = "backtester"
        indexes = [models.Index(fields=["verdict", "-entry_ts"]),
                   models.Index(fields=["verdict", "regime", "-entry_ts"])]
