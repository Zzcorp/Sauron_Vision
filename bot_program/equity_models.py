"""The account's equity, one row per stored sync — the drawdown's memory.

`IBKRAccount.last_equity` is a single cell: every sync overwrites it, so
the platform could say what the account holds NOW and nothing about the
road it took there. The share allocator needs the road — its drawdown
governor compares today's reading against the high-water mark of the
last 90 days, and a governor with no history is a governor that always
answers 1.0.

Written ONLY inside `sync_broker_account`, in the same block that stores
the reading on the account row (2026-09-12): the history and the cell
then quote the same broker call, and a row here is proof a reading
landed. Nothing writes a zero or a placeholder for a missed sync — an
unreachable gateway leaves a GAP, and a gap is the honest record of
"unmeasured". A zero row would read as a 100% drawdown and pin the
governor to its floor for 90 days on the strength of a 2FA restart.
"""
from django.db import models


class BrokerEquityReading(models.Model):
    account = models.ForeignKey(
        "bot_program.IBKRAccount", on_delete=models.CASCADE,
        related_name="equity_readings")
    value = models.DecimalField(max_digits=18, decimal_places=2)
    # The currency rides with the value, as on the account row: a GBP ISA
    # re-denominated to EUR would otherwise read as a 15% drawdown that
    # never happened. The drawdown reader only compares rows in the
    # current reading's currency.
    currency = models.CharField(max_length=8, blank=True, default="")
    # 'paper' / 'live' at the moment of the sync, so a port switch does
    # not mix a paper balance into a live account's high-water mark.
    env = models.CharField(max_length=5, blank=True, default="")
    at = models.DateTimeField(db_index=True)

    class Meta:
        ordering = ["-at"]
        indexes = [
            models.Index(fields=["account", "-at"]),
        ]
        constraints = [
            # One sync stores one reading. The task stamps `now` once per
            # account and passes it here, so a retried sync in the same
            # instant cannot double a row.
            models.UniqueConstraint(fields=["account", "at"],
                                    name="one_reading_per_sync"),
        ]

    def __str__(self):
        return (f"<BrokerEquityReading {self.account_id} {self.value} "
                f"{self.currency} @ {self.at:%Y-%m-%d %H:%M}>")
