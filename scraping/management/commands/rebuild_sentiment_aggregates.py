"""Rebuild, or drop, the hourly sentiment aggregates stored before the fix
of 2026-10-24 (scraping/sentiment.py).

Until then each hourly aggregate summed the aggregates before it, so the
stored rows with source "aggregated" carry volumes and bull and bear counts
that doubled every hour. This command fixes the rows already stored; the
task writes correct ones from now on.

  python manage.py rebuild_sentiment_aggregates            dry run: what
                                                            would change
  python manage.py rebuild_sentiment_aggregates --apply    rebuild each
      stored aggregate from the raw reads of its own 24-hour window; one
      with no raw read in its window is deleted (the fixed aggregation
      would never have written it)
  python manage.py rebuild_sentiment_aggregates --drop [--apply]
      delete every stored aggregate instead; the next hourly run writes a
      correct one

A dry run by default; nothing is written without --apply. A raw read
(StockTwits, Reddit, TradingView) is never touched. No order, size, stop
or gate reads these rows.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

#: Rows rewritten per bulk_update.
BATCH = 500


class Command(BaseCommand):
    help = ("Rebuild (default) or drop (--drop) the stored hourly sentiment "
            "aggregates from the raw reads. Dry run unless --apply.")

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true",
                            help="Write the change. Without it, a dry run.")
        parser.add_argument("--drop", action="store_true",
                            help="Delete every stored aggregate instead of "
                                 "rebuilding them.")

    def handle(self, *args, **opts):
        from scraping.models import SentimentSnapshot
        from scraping.sentiment import AGGREGATED

        apply, drop = opts["apply"], opts["drop"]
        rows = SentimentSnapshot.objects.filter(source=AGGREGATED)
        total = rows.count()
        head = ("Applied" if apply else "Dry run") + (
            f": {total} aggregated row{'' if total == 1 else 's'} stored.")
        self.stdout.write(head)
        if not total:
            self.stdout.write("Nothing to do.")
            return

        if drop:
            if apply:
                rows.delete()
                self.stdout.write(self.style.SUCCESS(
                    f"{total} deleted. The next hourly run writes a correct "
                    f"aggregate per watchlist instrument."))
            else:
                self.stdout.write(f"{total} would be deleted. Run again with "
                                  f"--drop --apply to delete them.")
            return

        changed, orphans, same, worst_before, worst_after = self._plan(rows)
        verb = "" if apply else "would be "
        self.stdout.write(
            f"{len(changed)} {verb}rebuilt from the raw reads of their own "
            f"window, {len(orphans)} {verb}deleted (no raw read behind "
            f"them), {same} already right.")
        self.stdout.write(f"Largest stored volume: {worst_before:,}; "
                          f"largest after the rebuild: {worst_after:,}.")
        if not apply:
            self.stdout.write("Run again with --apply to write it.")
            return
        fields = ["composite_score", "volume", "bullish_count",
                  "bearish_count", "neutral_count", "trending"]
        with transaction.atomic():
            for i in range(0, len(changed), BATCH):
                SentimentSnapshot.objects.bulk_update(
                    changed[i:i + BATCH], fields)
            if orphans:
                SentimentSnapshot.objects.filter(pk__in=orphans).delete()
        self.stdout.write(self.style.SUCCESS("Done."))

    def _plan(self, rows):
        """([rows with their rebuilt fields set], [pks to delete], the
        count already right, the largest stored volume, the largest
        rebuilt volume)."""
        from scraping.sentiment import aggregate_fields
        changed, orphans, same = [], [], 0
        worst_before = worst_after = 0
        for row in rows.select_related("instrument").order_by("pk").iterator():
            worst_before = max(worst_before, row.volume or 0)
            fields = aggregate_fields(row.instrument, row.timestamp)
            if fields is None:
                orphans.append(row.pk)
                continue
            worst_after = max(worst_after, fields["volume"])
            if all(getattr(row, k) == v for k, v in fields.items()):
                same += 1
                continue
            for k, v in fields.items():
                setattr(row, k, v)
            changed.append(row)
        return changed, orphans, same, worst_before, worst_after
