"""List, then on request delete, the public feed's 4h bars left on an old
grid beside the bars of the fixed UTC grid (2026-10-31).

    python manage.py prune_offgrid_4h                  # a dry run: the list, nothing deleted
    python manage.py prune_offgrid_4h --symbol XAUUSD  # one symbol
    python manage.py prune_offgrid_4h --yes            # delete what the dry run listed

Yahoo has no 4h bar; the public feed builds it from 1h. It used to anchor
the 4h grid at the first midnight of its ~200-day window in the exchange's
zone, so the grid moved by an hour in UTC whenever that window started
across a daylight-saving change, and the bars of both grids stayed in the
table (the timestamp is part of the key): pairs of near-identical 4h
candles an hour apart, read by the chart and by every rule on the symbol.
The feed now writes one grid, 00, 04, 08... UTC (public_feed.YFinanceFeed).

A row is listed when it is the PUBLIC FEED's (its source ends in
"_public"), is off the UTC 4h grid, and overlaps a 4h row of the same
instrument that is on it: the duplicate. Off-grid history with nothing
beside it stays (deleting it would cut the history short), and a venue's
own bars are never touched, on any grid. Until the bar refresh has written
the new grid for a symbol, nothing of that symbol is listed.

The deletion is destructive and changes the bars the bots read (once,
toward one grid): it runs only with --yes, after the operator has read the
dry run.
"""
from django.core.management.base import BaseCommand

FOUR_H = 4 * 3600


def offgrid_duplicates(symbol=""):
    """{instrument symbol: [(pk, timestamp, source), ...]} of the public
    feed's off-grid 4h rows that overlap an on-grid 4h row."""
    from market_data.models import PriceData

    qs = PriceData.objects.filter(timeframe="4h")
    if symbol:
        qs = qs.filter(instrument__symbol=symbol)
    rows = (qs.order_by("instrument_id", "timestamp")
            .values_list("pk", "instrument__symbol", "timestamp", "source"))
    by_inst = {}
    for pk, sym, ts, source in rows:
        by_inst.setdefault(sym, []).append((pk, ts, source))
    out = {}
    for sym, items in by_inst.items():
        on_grid = [int(ts.timestamp()) for _pk, ts, _s in items
                   if int(ts.timestamp()) % FOUR_H == 0]
        if not on_grid:
            continue
        on_grid.sort()
        found = []
        for pk, ts, source in items:
            t = int(ts.timestamp())
            if t % FOUR_H == 0 or not str(source or "").endswith("_public"):
                continue
            if any(abs(g - t) < FOUR_H for g in _near(on_grid, t)):
                found.append((pk, ts, source))
        if found:
            out[sym] = found
    return out


def _near(sorted_stamps, t):
    """The on-grid stamps that could overlap `t` (the two around it)."""
    import bisect
    i = bisect.bisect_left(sorted_stamps, t)
    return sorted_stamps[max(0, i - 1):i + 1]


class Command(BaseCommand):
    help = ("List the public feed's off-grid 4h bars that sit beside the UTC "
            "grid's (dry run by default); --yes deletes them.")

    def add_arguments(self, parser):
        parser.add_argument("--yes", action="store_true",
                            help="delete the listed rows")
        parser.add_argument("--symbol", default="",
                            help="one instrument symbol")

    def handle(self, *args, **opts):
        from market_data.models import PriceData

        symbol = (opts.get("symbol") or "").strip().upper()
        found = offgrid_duplicates(symbol)
        total = sum(len(v) for v in found.values())
        if not total:
            self.stdout.write("No off-grid 4h duplicates of the public feed"
                              + (f" for {symbol}" if symbol else "") + ".")
            return
        for sym in sorted(found):
            items = found[sym]
            sources = sorted({s for _pk, _ts, s in items})
            first = min(ts for _pk, ts, _s in items)
            last = max(ts for _pk, ts, _s in items)
            self.stdout.write(
                f"  {sym}: {len(items)} off-grid 4h row(s) of "
                f"{', '.join(sources)} beside the UTC grid's, "
                f"{first:%Y-%m-%d %H:%M} to {last:%Y-%m-%d %H:%M} UTC")
        if not opts.get("yes"):
            self.stdout.write(
                f"Dry run: {total} row(s) in {len(found)} symbol(s) would be "
                f"deleted, nothing was. Run again with --yes to delete them.")
            return
        pks = [pk for items in found.values() for pk, _ts, _s in items]
        deleted, _ = PriceData.objects.filter(pk__in=pks).delete()
        self.stdout.write(self.style.SUCCESS(
            f"Deleted {deleted} off-grid 4h row(s) in {len(found)} "
            f"symbol(s)."))
