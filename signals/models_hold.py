"""A signal's announcement held until its market opens (2026-11-12).

One row per signal whose banner, bell and Telegram message waited for the
market (signals/market_hold.py, the switch signal_market_hold, OFF on
arrival). A signal announced at its birth has no row: with the switch off
this table stays empty.

The row is the hold's whole memory: why the announcement waited, when the
market was due to open, and what the release pass decided (announced
once, or dropped with a named reason and the price it judged). It is
never read by a bot, the grader, the ladder or the ticket, and holding a
signal writes no field of the Signal itself.
"""
from django.db import models


class SignalHold(models.Model):
    HELD, RELEASED, DROPPED = "held", "released", "dropped"
    STATE_CHOICES = [
        (HELD, "Held: its market cannot trade yet"),
        (RELEASED, "Released: announced once, at the open"),
        (DROPPED, "Dropped: never announced"),
    ]
    #: Why it was held at birth.
    MARKET_SHUT, MARKET_SETTLING = "market_shut", "market_settling"
    #: Why it was released: its levels held against the first price of the
    #: session, or no price came and they were not re-checked.
    VALID, UNCHECKED = "valid", "unchecked"
    #: Released, and its announcement reached nobody (the banner, the bell
    #: and the channels all failed): the row says so, where it would
    #: otherwise read "announced at the open".
    ANNOUNCE_FAILED = "announce_failed"
    #: Why it was dropped: the engine closed it before the open; its 24
    #: hours ran out while it waited; or the first price was already past
    #: its plan (the three price rules of the rail's own lifecycle).
    CLOSED, AGED_SHUT = "closed", "aged_shut"
    STOP_CROSSED, TARGET_REACHED, CHASED = (
        "stop_crossed", "target_reached", "chased")

    signal = models.OneToOneField("signals.Signal", on_delete=models.CASCADE,
                                  related_name="hold")
    state = models.CharField(max_length=10, choices=STATE_CHOICES,
                             default=HELD, db_index=True)
    #: The latest reason: the hold's while held, the decision's after.
    reason = models.CharField(max_length=30, default=MARKET_SHUT)
    #: The latest words: the market's while held, the decision's after.
    words = models.CharField(max_length=300, blank=True, default="")
    #: When the market was due to open, as the clock said at the hold
    #: (null when the clock did not know, and for a signal held in a
    #: market's first quarter hour).
    reopens_at = models.DateTimeField(null=True, blank=True)
    held_at = models.DateTimeField()
    decided_at = models.DateTimeField(null=True, blank=True)
    #: The first price of the session the levels were judged against
    #: (null while held, and when it was released unchecked or dropped
    #: without a price).
    mark = models.DecimalField(max_digits=20, decimal_places=8, null=True,
                               blank=True)

    class Meta:
        ordering = ["-held_at", "-pk"]

    def __str__(self):
        return f"signal #{self.signal_id}: {self.state} ({self.reason})"
