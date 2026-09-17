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
    # KEYED ON (broker, account_pk) SINCE 2026-09-17. This was a foreign key
    # to IBKRAccount and nothing else could land a reading here — so an
    # eToro account's equity had no road, and the drawdown governor would
    # have answered 1.0 for it forever. A foreign key cannot point at two
    # models; a pair can. The FK stays, nullable, for the rows already
    # written (migration 0032 backfills the pair from it), and every reader
    # filters on the pair.
    broker = models.CharField(max_length=16, default="ibkr", db_index=True)
    account_pk = models.IntegerField(null=True, blank=True)
    account = models.ForeignKey(
        "bot_program.IBKRAccount", on_delete=models.CASCADE,
        related_name="equity_readings", null=True, blank=True)
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
            models.Index(fields=["broker", "account_pk", "-at"]),
        ]
        constraints = [
            # One sync stores one reading. The task stamps `now` once per
            # account and passes it here, so a retried sync in the same
            # instant cannot double a row.
            models.UniqueConstraint(fields=["broker", "account_pk", "at"],
                                    name="one_reading_per_sync_v2"),
        ]

    def save(self, *args, **kwargs):
        """A row written through the FK alone still gets its pair.

        Found by the readers' own tests the moment they filtered on the
        pair: every fixture seeded `account=acct` and nothing else, the
        readers saw no history at all, and the high-water mark read as the
        current value — a drawdown of zero, forever, for any row created
        the old way. Migration 0032 backfills the rows that already exist;
        this covers every row created after it by any caller that still
        passes the FK. The FK is a convenience that fills the key, never a
        second key the readers cannot see.
        """
        if self.account_pk is None and self.account_id is not None:
            self.broker = "ibkr"
            self.account_pk = self.account_id
        super().save(*args, **kwargs)

    def __str__(self):
        return (f"<BrokerEquityReading {self.broker}:{self.account_pk} "
                f"{self.value} {self.currency} @ {self.at:%Y-%m-%d %H:%M}>")
