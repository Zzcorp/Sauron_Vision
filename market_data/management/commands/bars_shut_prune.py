"""List, then on request delete, the eToro bars stored for slots the market
was shut for (2026-11-19).

    python manage.py bars_shut_prune                 # dry run: counts only
    python manage.py bars_shut_prune --symbols       # + each symbol's count
    python manage.py bars_shut_prune --since 2026-11-01   # from that day
    python manage.py bars_shut_prune --apply         # delete, recompute

A day given to --since is a UTC day: the bars opening on or after its
00:00 UTC; with none, all history.

WHY. Until 2026-11-19 the bar writer (market_data/bot_bars.py) stored every
candle eToro answered, and eToro answers a 1h and a 4h candle for every
slot it is asked for, a weekend's included: flat at Friday's close or
moving. Every reader took them for traded bars: the ATR the entry stops
and sizes are set from (risk_levels.atr_for: the indicator task's stored
atr_14 first, else the bars), the Orcs' frames, wakes and gap model, the
chart. The writer now drops such a candle (_without_shut_candles); the
rows it stored before are still in the table, and the ATR reads them until
traded bars push them out of its window, about 44 hours after a reopen.

WHAT IT DELETES. Exactly the stored rows the writer's own rule rejects,
market_data.shut_bars.holds_no_open_time: a bar whose whole span holds no
open time inside a shut of a day or more (a currency pair on eToro's
17:00 New York week, a commodity on its own market clock), and nothing
else:
  - source "etoro" only: the keyless feed ("..._public"), the daily
    writers ("yfinance", "alpha_vantage") and IBKR keep every row;
  - currency pairs and commodities only (shut_bars.COVERED_CLASSES):
    crypto, stocks, ETFs and indices are never read;
  - never one of eToro's all-week instruments (shut_bars
    .ALL_WEEK_ETORO_IDS: GOLD, OIL, SILVER and NATGAS trade on Saturday
    and Sunday too), never even read;
  - never a bar that holds open time: the Sunday 20:00 UTC 4h bar that
    holds the reopen, the Friday 21:00-22:00 UTC FX hour in winter, a
    CME daily break (a shut shorter than a day).
The class, source, timeframe and window are filtered in SQL; the rule is
asked row by row, CHUNK rows per round trip, so the table is never held
in memory, only the rows that go. --apply deletes them series by series,
BATCH rows per transaction, the source read again at the delete.

WHAT ELSE HOLDS THEM (read 2026-11-19, so the delete leaves nothing
dangling and nothing stale):
  - No model has a ForeignKey to PriceData, nor to TechnicalIndicator: a
    deleted bar cascades nothing.
  - TechnicalIndicator (indicators/models.py) is tied to no bar by a key.
    The indicator task (indicators/tasks.recalculate_for_instruments,
    every 15 minutes for the watchlist and the bots' symbols, config/
    celery.py "recalculate-technicals-watchlist", and nightly for every
    active instrument) writes ONE row per (instrument, timeframe), keyed
    by the newest bar's timestamp, from the newest 250 bars of every
    source (signals.smc.dataframe.load_ohlcv). So --apply:
      * deletes the indicator rows keyed at a deleted bar, with it;
      * recomputes, with that same function and right after its delete,
        every series it changed whose indicators were stored: the newest
        row is rewritten from the cleaned bars (atr_for and the
        instrument page read the newest row);
      * on a series left with too few bars to compute (MIN_BARS), deletes
        the rows keyed at or after its first deleted bar (their windows
        held one), so atr_for computes from the cleaned bars;
      * leaves the older rows keyed at traded bars as they are: history
        no stop, size or page reads.
    A run cut short leaves at most one series half done; run --apply
    again and it finishes and recomputes that series.
  - The Orcs' frames (bot_program/orcs/bars.frame) live in one tick's own
    dict: none outlives the tick.
  - The Orcs' gap memos (bot_program/orcs/gaps.py) are kept in the Django
    cache for the UTC day, measured on the 1h venue bars: weekend bars
    leave no hole between Friday's bars and Sunday's, so the weekend gap
    read unmeasured, and a print dated inside a deleted bar measured that
    bar. --apply clears today's weekend memo of every symbol whose 1h
    bars it changed, and the print memos of each print dated inside one
    of its deleted 1h bars (gap_memo_key: the key is spelled here, since
    no module outside the Orcs' package may start importing it).
  - The chart's live frames ("chart:v2:...") are the keyless feed's own
    bars, never a stored row. The sparks ("wl:spark3:", "pos:spark2:",
    "hb:sparks3", 300 s) and the chart's levels and positioning
    ("chart:levels:", "chart:positioning:", 60 s) are read from the
    stored bars and age out within five minutes. The council band's
    panels keep reports other jobs wrote (dashboard/council_band.py), no
    bar.
  - The writer's answer notes ("bars:answered:", "bars:venue_answered:",
    six hours) say what eToro answered and when, not what is stored:
    they stay.
  - The Orcs remember the last decision bar they woke on (seen
    "w2_bar"). Run during a weekend, the prune moves a frame's newest
    final bar back to Friday's, and an Orc's next tick may wake once on
    it (a key already woken is not woken again). Run it on a weekday.

The deletion changes the bars the bots read (toward the traded bars): it
runs only with --apply, after the operator has read the dry run. It is
idempotent: a second --apply finds nothing and changes nothing. The
words print counts by class and timeframe, never a price or an id, and a
symbol only with --symbols.
"""
import hashlib
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone as dt_tz

from django.core.management.base import BaseCommand, CommandError

from market_data.shut_bars import (COVERED_CLASSES, holds_no_open_time,
                                   trades_all_week)

#: The rows it judges: the venue's own (bot_bars._source_tag of eToro's
#: adapter, EtoroTrader).
VENUE_SOURCE = "etoro"
#: Rows read per database round trip while judging.
CHUNK = 2000
#: Rows deleted per transaction.
BATCH = 500
#: What the rule covers, as the header says it.
SCOPE = ("currency pairs and commodities, source eToro; eToro's all-week "
         "instruments are kept")


def _cls(inst) -> str:
    return str(getattr(inst, "asset_class", "") or "").strip().lower()


def judged_instruments() -> dict:
    """{instrument id: Instrument} of every instrument the rule can drop a
    bar of: a covered class, and not one of eToro's all-week instruments.
    The instrument table is small; PriceData is read through these ids."""
    from instruments.models import Instrument
    return {i.pk: i for i in Instrument.objects.only(
                "id", "symbol", "asset_class", "exchange")
            if _cls(i) in COVERED_CLASSES and not trades_all_week(i)}


def shut_bars(since=None):
    """([(pk, instrument id, timeframe, timestamp)], judged): the stored
    eToro bars the writer's rule rejects (holds_no_open_time), in pk
    order, opening on or after `since` when given, and the instruments
    judged (judged_instruments). Reads only."""
    from market_data.bot_bars import INTERVAL_SECONDS
    from market_data.models import PriceData
    judged = judged_instruments()
    qs = PriceData.objects.filter(source=VENUE_SOURCE,
                                  instrument_id__in=sorted(judged),
                                  timeframe__in=sorted(INTERVAL_SECONDS))
    if since is not None:
        qs = qs.filter(timestamp__gte=since)
    found = []
    rows = (qs.order_by("pk")
            .values_list("pk", "instrument_id", "timeframe", "timestamp")
            .iterator(chunk_size=CHUNK))
    for pk, iid, tf, ts in rows:
        if holds_no_open_time(judged[iid], tf, ts):
            found.append((pk, iid, tf, ts))
    return found, judged


def _tf_order(tf):
    from market_data.bot_bars import INTERVAL_SECONDS
    return INTERVAL_SECONDS.get(tf, 0), tf


def _prune_series(inst, tf, rows, had):
    """Delete one series' listed rows (BATCH per transaction, the source
    read again at the delete) and the indicator rows keyed at them, then,
    when the series had indicators stored (`had`), recompute them with the
    indicator task's own function. (bars deleted, indicator rows deleted
    at them, "recomputed" | "cleared" | "", indicator rows cleared on a
    series too short to recompute, the timestamps deleted)."""
    from django.db import transaction

    from indicators.models import TechnicalIndicator
    from indicators.tasks import recalculate_for_instruments
    from market_data.models import PriceData
    bars = indicators = 0
    stamps = []
    for start in range(0, len(rows), BATCH):
        pks = [r[0] for r in rows[start:start + BATCH]]
        with transaction.atomic():
            alive = list(PriceData.objects
                         .filter(pk__in=pks, source=VENUE_SOURCE,
                                 instrument=inst, timeframe=tf)
                         .values_list("pk", "timestamp"))
            if not alive:
                continue
            n, _ = PriceData.objects.filter(
                pk__in=[pk for pk, _ts in alive]).delete()
            bars += n
            at = [ts for _pk, ts in alive]
            stamps.extend(at)
            n, _ = TechnicalIndicator.objects.filter(
                instrument=inst, timeframe=tf, timestamp__in=at).delete()
            indicators += n
    if not stamps or not had:
        return bars, indicators, "", 0, stamps
    done = recalculate_for_instruments([inst], timeframes=(tf,))
    if done.get("written"):
        return bars, indicators, "recomputed", 0, stamps
    # Too few bars left (or the computation failed): the rows whose window
    # held a deleted bar go, and the stops read the bars themselves.
    n, _ = TechnicalIndicator.objects.filter(
        instrument=inst, timeframe=tf, timestamp__gte=min(stamps)).delete()
    return bars, indicators, "cleared", n, stamps


def gap_memo_key(kind, symbol, key, now) -> str:
    """The Django cache key of an Orcs gap memo, as bot_program/orcs/gaps
    ._key spells it: kept for the UTC day of `now`. Spelled here, not
    imported: the modules outside the Orcs' package that import it are a
    frozen list (tests/orcs/test_orc_o2a_shadow_pins), and a one-off
    prune is not one of them. tests/test_bars_shut_prune sets the memos
    with gaps._key and reads them cleared, so the two spellings cannot
    drift apart unseen."""
    digest = hashlib.sha1(f"{symbol}|{key}".encode()).hexdigest()[:20]
    return f"orcs:gap:{kind}:{digest}:{now:%Y-%m-%d}"


def _clear_gap_memos(hours, now) -> int:
    """Clear today's Orcs gap memos measured on deleted 1h bars: the
    weekend memo of every symbol in `hours` ({symbol: the opens of its
    deleted 1h bars}), and the print memos ("<title>|<currency>" and
    "<title>|") of each economic print dated inside one of them. How
    many symbols."""
    from django.core.cache import cache

    from market_data.models import EconomicEvent
    if not hours:
        return 0
    keys = {gap_memo_key("weekend", sym, "weekend", now) for sym in hours}
    lo = min(min(v) for v in hours.values())
    hi = max(max(v) for v in hours.values()) + timedelta(hours=1)
    events = (EconomicEvent.objects
              .filter(datetime__gte=lo, datetime__lt=hi)
              .values_list("title", "datetime", "currency_affected")
              .iterator(chunk_size=CHUNK))
    for title, at, ccy in events:
        hour = at.replace(minute=0, second=0, microsecond=0)
        for sym, opens in hours.items():
            if hour in opens:
                for c in {"", str(ccy or "")}:
                    keys.add(gap_memo_key("print", sym, f"{title}|{c}",
                                          now))
    cache.delete_many(sorted(keys))
    return len(hours)


class Command(BaseCommand):
    help = ("Count the eToro bars stored for slots the market was shut for "
            "(currency pairs and commodities; dry run by default); --apply "
            "deletes them and recomputes the indicators.")

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true",
                            help="delete the counted bars, then recompute "
                                 "the stored indicators of their series")
        parser.add_argument("--since", default="",
                            help="only bars opening on or after this day, "
                                 "YYYY-MM-DD (UTC); all history by default")
        parser.add_argument("--symbols", action="store_true",
                            help="add each symbol's count")

    def handle(self, *args, **opts):
        since = self._since(opts.get("since"))
        window = (f"since {since:%Y-%m-%d}" if since is not None
                  else "all history")
        found, judged = shut_bars(since)
        if not found:
            self.stdout.write(f"bars_shut_prune: no eToro bar is stored for "
                              f"a slot the market was shut for a day or "
                              f"more ({SCOPE}), {window}.")
            self.stdout.write("Nothing was deleted.")
            return
        by_class = Counter((_cls(judged[iid]), tf) for _pk, iid, tf, _t
                           in found)
        series = defaultdict(list)
        for row in found:
            series[(row[1], row[2])].append(row)
        self.stdout.write(f"bars_shut_prune: the eToro bars stored for "
                          f"slots the market was shut for a day or more "
                          f"({SCOPE}), {window}:")
        for (cls, tf), n in sorted(by_class.items(),
                                   key=lambda kv: (kv[0][0],
                                                   _tf_order(kv[0][1]))):
            self.stdout.write(f"  {cls} {tf}: {n}")
        self.stdout.write(f"Total: {len(found)} bars in {len(series)} "
                          f"series.")
        if opts.get("symbols"):
            self.stdout.write("By symbol:")
            per = sorted(((judged[iid].symbol, tf), len(rows))
                         for (iid, tf), rows in series.items())
            for (sym, tf), n in sorted(per, key=lambda kv: (
                    kv[0][0], _tf_order(kv[0][1]))):
                self.stdout.write(f"  {sym} {tf}: {n}")
        again = f" --since {since:%Y-%m-%d}" if since is not None else ""
        if not opts.get("apply"):
            self.stdout.write(
                f"Dry run: nothing was deleted. To delete these bars and "
                f"recompute the indicators: python manage.py bars_shut_prune "
                f"--apply{again}")
            return
        self._apply(series, judged)

    def _apply(self, series, judged):
        from django.utils import timezone

        from indicators.models import TechnicalIndicator
        had = set(TechnicalIndicator.objects
                  .filter(instrument_id__in={iid for iid, _tf in series})
                  .order_by().values_list("instrument_id", "timeframe")
                  .distinct())
        bars = indicators = cleared = 0
        changed, outcome = set(), Counter()
        hours = defaultdict(set)
        for (iid, tf), rows in sorted(series.items(),
                                      key=lambda kv: (kv[0][0],
                                                      _tf_order(kv[0][1]))):
            inst = judged[iid]
            n, k, what, c, stamps = _prune_series(inst, tf, rows,
                                                  (iid, tf) in had)
            bars, indicators, cleared = bars + n, indicators + k, cleared + c
            if n:
                changed.add((iid, tf))
            if what:
                outcome[what] += 1
            if tf == "1h" and stamps:
                hours[inst.symbol].update(stamps)
        self.stdout.write(f"Deleted {bars} bars in {len(changed)} series, "
                          f"and {indicators} indicator rows stored at them.")
        self.stdout.write(f"Indicators recomputed from the cleaned bars: "
                          f"{outcome['recomputed']} series.")
        if outcome["cleared"]:
            self.stdout.write(
                f"Too few bars left to recompute: {outcome['cleared']} "
                f"series; their {cleared} indicator rows since the first "
                f"deleted bar were deleted, and the stops read the bars "
                f"themselves.")
        try:
            memos = _clear_gap_memos(hours, timezone.now())
        except Exception as e:  # noqa: BLE001 — the bars are gone already
            self.stdout.write(f"The Orcs' gap memos were not cleared ({e}); "
                              f"they are measured again at 00:00 UTC.")
        else:
            self.stdout.write(f"The Orcs' gap memos of today were cleared "
                              f"for {memos} symbols.")

    def _since(self, value):
        value = str(value or "").strip()
        if not value:
            return None
        try:
            day = datetime.strptime(value, "%Y-%m-%d")
        except ValueError:
            raise CommandError(f"--since takes a day as YYYY-MM-DD (UTC), "
                               f"not {value!r}") from None
        return day.replace(tzinfo=dt_tz.utc)
