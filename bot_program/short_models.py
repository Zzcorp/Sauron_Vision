"""THE SHORTS MEASURED AT eToro (2026-10-31).

The operator, 2026-10-31: "je veux les short possible entierement svp"
(I want shorts fully possible, please). Two writers keep one record:

  readback      the TAKE TRADE lane sends a SELL on every class eToro's own
                eligibility allows, whether or not that class's short round
                trip is pinned (asset_engine/base.py ETORO_SHORT_PROVEN),
                and reads each such position back from eToro at the fill
                (bot_program/short_readback.py). A read-back that found
                eToro holding exactly what was sent is one of these rows:
                the facts a developer pins by hand in
                tests/test_etoro_client.py CLASS_SHORT_PROOFS — the
                instrument, the side, the multiplier, the units, the order
                and position ids, the open rate, the fees, the times. A
                record, read by nothing that sends an order.
  proof_runner  the platform's own demo proofs (bot_program/short_proofs.py,
                2026-10-31): a SELL of the venue minimum on eToro's DEMO
                segment, read at the fill, closed, read at the close. Every
                step it takes is a row (proof_state), the refusals too, so
                it never asks the same question twice in a day. A row
                marked demo_proven — read clean at the fill AND proven
                closed, never revoked — is what the BOTS' gate reads
                (base.missing_proofs): a class the runner proved opens to
                the bots at the multiplier measured, and no other. One row
                per class also holds a short across the close
                (`overnight`) to measure its overnight fee, which the cost
                model then charges (risk_levels.short_fee_fraction).
"""
from django.conf import settings
from django.db import models
from django.utils import timezone


class EtoroShortObservation(models.Model):
    """One eToro short, read back clean after a hand-taken fill, or one
    step of the demo proof runner (`source`)."""

    trade = models.ForeignKey(
        "bot_program.AssetBotTrade", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="short_observations")
    #: who wrote it: "readback" (the TAKE TRADE lane) or "proof_runner"
    source = models.CharField(max_length=16, default="readback",
                              db_index=True)
    #: the INSTRUMENT's class, the proof gate's key ("etf", "index", ...)
    asset_class = models.CharField(max_length=12, db_index=True)
    #: the platform's spelling, and eToro's (asset.symbol)
    symbol = models.CharField(max_length=40)
    venue_symbol = models.CharField(max_length=40, blank=True)
    instrument_id = models.BigIntegerField(null=True, blank=True)
    #: "demo" (eToro's virtual segment) or "live" (real money)
    world = models.CharField(max_length=8)
    #: eToro's asset.side ("short") and asset.settlementType ("CFD")
    side = models.CharField(max_length=8)
    settlement = models.CharField(max_length=12, blank=True)
    leverage = models.PositiveSmallIntegerField(default=1)
    units = models.DecimalField(max_digits=24, decimal_places=10)
    order_id = models.CharField(max_length=40)
    position_id = models.CharField(max_length=40)
    #: openingData.avgPrice, openingData.fees, the order's totalCosts and
    #: requestedAmount, the legs eToro holds — as eToro printed them
    open_rate = models.DecimalField(max_digits=24, decimal_places=10,
                                    null=True, blank=True)
    fees = models.DecimalField(max_digits=18, decimal_places=6, null=True,
                               blank=True)
    total_costs = models.DecimalField(max_digits=18, decimal_places=6,
                                      null=True, blank=True)
    requested_amount = models.DecimalField(max_digits=18, decimal_places=6,
                                           null=True, blank=True)
    stop_held = models.DecimalField(max_digits=24, decimal_places=10,
                                    null=True, blank=True)
    target_held = models.DecimalField(max_digits=24, decimal_places=10,
                                      null=True, blank=True)
    #: openingData.openTime and executionTime, and when the platform read
    opened_at = models.DateTimeField(null=True, blank=True)
    executed_at = models.DateTimeField(null=True, blank=True)
    read_at = models.DateTimeField(default=timezone.now, db_index=True)
    #: the whole orders:lookup body as read, less the account's own keys
    lookup = models.JSONField(default=dict, blank=True)

    # ── the demo proof runner's (2026-10-31, bot_program/short_proofs.py) ──
    #: the step: sending, open, closing, proven, mismatch, refused,
    #: not_listed, no_short, no_row, withdrawn, not_sent, in_doubt
    proof_state = models.CharField(max_length=16, blank=True, default="",
                                   db_index=True)
    #: read clean at the fill AND proven closed: what the bots' gate reads
    demo_proven = models.BooleanField(default=False, db_index=True)
    #: eToro's words, or the runner's, when nothing was proven
    refusal = models.CharField(max_length=300, blank=True, default="")
    #: units x the open rate, in USD: what the fees are a share of
    notional = models.DecimalField(max_digits=18, decimal_places=6,
                                   null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    close_order_id = models.CharField(max_length=40, blank=True, default="")
    #: the close's answer, the order read after it, the fill's verdict and,
    #: for an overnight hold, the held /portfolio row — less the account's
    #: own keys
    close_lookup = models.JSONField(default=dict, blank=True)
    #: held across the close to measure the overnight fee (once per class)
    overnight = models.BooleanField(default=False)
    hold_until = models.DateTimeField(null=True, blank=True)
    nights = models.PositiveSmallIntegerField(default=0)
    overnight_fee = models.DecimalField(max_digits=18, decimal_places=6,
                                        null=True, blank=True)
    #: the requests this step sent to eToro (the demo-only wire counts them)
    requests = models.PositiveIntegerField(default=0)
    #: when the operator was told a proof opened a class to the bots
    notified_at = models.DateTimeField(null=True, blank=True)
    #: a superuser's revoke (a proof), or clear (an in-doubt stop), with
    #: the trading PIN on /short-proofs/: the gate reads it no more
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+")
    revoke_reason = models.CharField(max_length=200, blank=True, default="")

    class Meta:
        ordering = ["-read_at"]
        indexes = [models.Index(fields=["asset_class", "world", "-read_at"]),
                   models.Index(fields=["source", "asset_class",
                                        "demo_proven"])]

    def __str__(self):
        return (f"{self.symbol} {self.side} {self.leverage}x "
                f"({self.asset_class}, {self.world})")
