"""The harm counters' one table (the eToro feed spec, F1, §6.2; 2026-11-07).

One row per harm today's code did — a mark-sanity skip of a real row, a
CLOSE refused for no usable price mark, the kill switch's wait before a
close, a poller's previousClose or out-of-session price, a zero or crossed
side stored, an exit booked at the mark, at an outside quote, at a level,
unpriced or left pending (bot_program.feed_harms.KINDS). The evidence the
later phases' switches are judged on: `manage.py feed_harms --days N`
prints the counts by kind and nothing else.

Written only by bot_program.feed_harms, after the money path's own
transaction has committed and in a short transaction of its own; no
foreign key, so an insert never waits on a money row's lock.
"""
from django.db import models
from django.db.models import Q
from django.utils import timezone


class FeedHarmEvent(models.Model):
    at = models.DateTimeField(default=timezone.now, db_index=True)
    kind = models.CharField(max_length=40)
    #: a real row's harm (True), a paper row's (False), or no row (None)
    real = models.BooleanField(null=True, blank=True)
    symbol = models.CharField(max_length=40, blank=True, default="")
    #: the quote's or the booking's source, where one is meant
    source = models.CharField(max_length=50, blank=True, default="")
    #: the kill switch's wait before a close
    seconds = models.FloatField(null=True, blank=True)
    #: why, and the levels; read by hand on the server, never printed
    detail = models.JSONField(default=dict, blank=True)
    #: one row per (kind, ref) when set: a booking counted once per row
    ref = models.CharField(max_length=64, blank=True, default="")

    class Meta:
        ordering = ("at", "id")
        indexes = [models.Index(fields=["kind", "at"],
                                name="feed_harm_kind_at")]
        constraints = [models.UniqueConstraint(
            fields=["kind", "ref"], condition=~Q(ref=""),
            name="feed_harm_once_per_ref")]

    def __str__(self):
        return f"{self.kind} at {self.at:%Y-%m-%d %H:%M}"
