"""ONE AGGREGATE AN HOUR, FROM THE RAW READS ONLY (2026-10-24).

SentimentSnapshot holds two kinds of row. A RAW read is one feed's
answer: a StockTwits page, a Reddit pass, a TradingView rating
(scraping/scrapers). An AGGREGATE (source AGGREGATED) is the hourly sum of
the raw reads of the last WINDOW per watchlist instrument, written by
scraping.tasks.aggregate_sentiment.

The aggregation used to read every row of the window, its own earlier
aggregates included: each hour summed the hours before it, so the volume
and the bull and bear counts roughly doubled every hour (the score stayed
an average) until the integer column refused the insert on Postgres. It
now reads the raw rows only, and a second run in the same clock hour
rewrites that hour's row instead of adding a twin, so the same raw rows
always give the same aggregate.

The readers choose on purpose:
  * one read per instrument (the positioning map's crowd score, which the
    council and the position review read; the news page): `latest`, the
    aggregate while it is fresh (AGGREGATE_FRESH), else the newest raw
    read, so a switched-off aggregation never freezes the read;
  * a series or an average over raw reads (the crowd_extreme and
    sentiment_snapshot conditions, the sentiment index): `raw`, every
    source but AGGREGATED, unless the caller names a source.

`manage.py rebuild_sentiment_aggregates` rebuilds the aggregates stored
before this fix (dry run by default).
"""
from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

#: The source the hourly aggregation writes. Every other source is a raw
#: read of one feed.
AGGREGATED = "aggregated"
#: The raw reads one aggregate sums: the 24 hours up to its own time.
WINDOW = timedelta(hours=24)
#: An aggregate older than this is not the current one: the aggregation
#: runs hourly, so a fresh one is never more than an hour and a little old.
AGGREGATE_FRESH = timedelta(hours=2)


def raw(qs=None):
    """The raw reads of `qs` (every SentimentSnapshot by default): never an
    aggregate, which would count the raw reads it was made from twice."""
    if qs is None:
        from scraping.models import SentimentSnapshot
        qs = SentimentSnapshot.objects.all()
    return qs.exclude(source=AGGREGATED)


def aggregate_fields(instrument, end) -> dict | None:
    """The aggregate of `instrument`'s raw reads in [end - WINDOW, end], as
    the fields of its row; None when there is no raw read in it."""
    from django.db.models import Avg, Count, Sum
    from scraping.models import SentimentSnapshot
    agg = raw(SentimentSnapshot.objects.filter(
        instrument=instrument, timestamp__gte=end - WINDOW,
        timestamp__lte=end)).aggregate(
        n=Count("id"), avg_score=Avg("composite_score"),
        total_volume=Sum("volume"), total_bullish=Sum("bullish_count"),
        total_bearish=Sum("bearish_count"),
        total_neutral=Sum("neutral_count"))
    if not agg["n"]:
        return None
    volume = agg["total_volume"] or 0
    return {"composite_score": agg["avg_score"] or 0,
            "volume": volume,
            "bullish_count": agg["total_bullish"] or 0,
            "bearish_count": agg["total_bearish"] or 0,
            "neutral_count": agg["total_neutral"] or 0,
            "trending": volume > 100}


def write_aggregate(instrument, now=None):
    """Write `instrument`'s aggregate at `now`: the clock hour's row
    rewritten when there is one, else a new row. Returns the row, or None
    when there is no raw read in the window (nothing is written)."""
    from scraping.models import SentimentSnapshot
    now = now or timezone.now()
    fields = aggregate_fields(instrument, now)
    if fields is None:
        return None
    hour = now.replace(minute=0, second=0, microsecond=0)
    row = (SentimentSnapshot.objects
           .filter(instrument=instrument, source=AGGREGATED,
                   timestamp__gte=hour,
                   timestamp__lt=hour + timedelta(hours=1))
           .order_by("-timestamp").first())
    if row is None:
        return SentimentSnapshot.objects.create(
            instrument=instrument, source=AGGREGATED, timestamp=now, **fields)
    for name, value in fields.items():
        setattr(row, name, value)
    row.timestamp = now
    row.save(update_fields=[*fields, "timestamp"])
    return row


def latest(instrument, *, now=None, max_age=None):
    """The one sentiment read of `instrument`: its aggregate when the newest
    one is no older than AGGREGATE_FRESH, else its newest raw read no
    older than `max_age` (any age when None). None when there is neither."""
    from scraping.models import SentimentSnapshot
    now = now or timezone.now()
    mine = SentimentSnapshot.objects.filter(instrument=instrument)
    agg = (mine.filter(source=AGGREGATED,
                       timestamp__gte=now - AGGREGATE_FRESH)
           .order_by("-timestamp").first())
    if agg is not None:
        return agg
    reads = raw(mine)
    if max_age is not None:
        reads = reads.filter(timestamp__gte=now - max_age)
    return reads.order_by("-timestamp").first()
