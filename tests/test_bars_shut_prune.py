"""THE PRUNE OF THE SHUT BARS ALREADY STORED (2026-11-19): bars_shut_prune.

Until the bar writer dropped them (market_data/bot_bars.py,
_without_shut_candles), it stored a 1h and a 4h eToro candle for every
weekend slot of a currency pair or a commodity, flat or moving, and every
reader took them for traded bars: the ATR the entry stops and sizes are
set from (bot_program/asset_engine/risk_levels.atr_for reads the indicator
task's stored atr_14 first), the Orcs' frames and gap model, the chart.
The writer keeps them out now; the rows stored before it stay in the
table until this command deletes them
(market_data/management/commands/bars_shut_prune.py):

  - the dry run, the default, deletes nothing and prints counts by class
    and timeframe only: no price, no id, no symbol;
  - --apply deletes exactly the stored eToro rows the writer's own
    predicate rejects (market_data.shut_bars.holds_no_open_time) and the
    indicator rows stored at them, then recomputes the stored indicators
    of every series it changed with the indicator task's own code: the
    stored atr_14 at the reopen is the traded week's;
  - a second --apply finds nothing and changes nothing;
  - it never touches, nor even judges, eToro's all-week instruments
    (gold, silver, OIL), crypto, stocks, indices or another source's
    rows, and it keeps every bar that holds open time: the Sunday reopen
    bar, the Friday FX hour in winter, the CME daily break;
  - --since limits the window.

The stored rows are the fixture of tests/test_weekend_bars.py (_candles):
what the writer stored before its rule, eToro's candles for every slot.
Fakes only, sqlite, no network; every price is invented.

Run with:  python manage.py test tests.test_bars_shut_prune
"""
import itertools
import re
from datetime import datetime, timedelta, timezone as dt_tz
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from tests.test_weekend_bars import (FRI_21, FRI_22, SAT_12, SPAN, SUN_20,
                                     SUN_2315, SYMBOLS, TUE_22, _atr_of,
                                     _candles, _pinned, _shut_bar)

UTC = dt_tz.utc
M15 = timedelta(minutes=15)
SAT_1201 = SAT_12 + timedelta(minutes=1)
NOW = datetime(2026, 11, 19, 10, 0, tzinfo=UTC)    # the operator runs it
SPANS = dict(SPAN, **{"15m": M15})
COMMAND = "market_data.management.commands.bars_shut_prune"

#: PriceData and Instrument ids far from any count the command prints, so
#: an id that leaked into its words could never pass for a count.
_IDS = itertools.count(900001)
_INST_IDS = itertools.count(7001)


def _store(inst, series, weekend, *, intervals=("1h", "4h"), source="etoro",
           since=None, until=SUN_2315):
    """eToro's candles of `series` (tests.test_weekend_bars._candles) from
    `since` to `until`, stored for `inst` under `source` as the writer
    stored them before its rule: every candle answered."""
    from market_data.models import PriceData
    rows = []
    for iv in intervals:
        for c in _candles(series, iv, weekend):
            if c.open <= until and (since is None or c.open >= since):
                rows.append(PriceData(
                    id=next(_IDS), instrument=inst, timeframe=iv,
                    timestamp=c.open, open=Decimal(str(c.o)),
                    high=Decimal(str(c.h)), low=Decimal(str(c.l)),
                    close=Decimal(str(c.c)), volume=c.v, source=source))
    PriceData.objects.bulk_create(rows)
    return len(rows)


def _flat(inst, tf, at, price, source="etoro"):
    from market_data.models import PriceData
    p = Decimal(str(price))
    return PriceData.objects.create(
        id=next(_IDS), instrument=inst, timeframe=tf, timestamp=at, open=p,
        high=p, low=p, close=p, volume=0, source=source)


def _bars():
    """{(symbol, timeframe, timestamp): (o, h, l, c, volume, source)} of
    every stored bar."""
    from market_data.models import PriceData
    return {(r.instrument.symbol, r.timeframe, r.timestamp):
            (r.open, r.high, r.low, r.close, r.volume, r.source)
            for r in PriceData.objects.select_related("instrument")}


def _indicators():
    from indicators.models import TechnicalIndicator
    return {(r.instrument.symbol, r.timeframe, r.timestamp):
            (r.atr_14, r.rsi_14, r.sma_20, r.bollinger_upper, r.obv)
            for r in TechnicalIndicator.objects.select_related("instrument")}


def _gone_by_the_rule(bars):
    """The test's own oracle: the stored eToro bars of a currency pair or a
    weekday-only commodity whose whole span lies inside its weekend shut
    (tests.test_weekend_bars._shut_bar, written from the venues' published
    hours), every other row kept."""
    return {k for k, v in bars.items()
            if v[-1] == "etoro" and k[0] in SYMBOLS
            and _shut_bar(k[0], k[2], k[2] + SPANS[k[1]])}


def _counts(keys):
    """{(class, timeframe): n} of bar keys."""
    out = {}
    for sym, tf, _ts in keys:
        cls = SYMBOLS[sym][0]
        out[(cls, tf)] = out.get((cls, tf), 0) + 1
    return out


class _Prune(TestCase):

    def setUp(self):
        from instruments.models import Instrument
        cache.clear()
        self.addCleanup(cache.clear)
        self.inst = {}
        for sym, (cls, exch, *_rest) in SYMBOLS.items():
            self.inst[sym] = Instrument.objects.create(
                id=next(_INST_IDS), symbol=sym, name=sym, asset_class=cls,
                exchange=exch)
        # eToro's OIL (17), its platform symbol read from the pin
        _label, oil = _pinned(17)
        self.oil = Instrument.objects.create(
            id=next(_INST_IDS), symbol=oil, name="Oil", asset_class="commodity",
            exchange="NYMEX")

    def prune(self, *args, now=NOW):
        out = StringIO()
        with patch("django.utils.timezone.now", return_value=now):
            call_command("bars_shut_prune", *args, stdout=out)
        return out.getvalue()

    def store_week(self):
        """Three weeks of eToro's candles as the old writer stored them:
        weekday markets with flat and with moving weekends, the all-week
        instruments with moving ones, crypto, a stock and an index with
        their weekend candles, and a few Orcs' tape 15m bars."""
        _store(self.inst["EURUSD"], "EURUSD", "flat")
        _store(self.inst["GBPUSD"], "GBPUSD", "wide")
        _store(self.inst["HGUSD"], "HGUSD", "flat")
        _store(self.inst["XAUUSD"], "XAUUSD", "wide")
        _store(self.inst["XAGUSD"], "XAGUSD", "flat")
        _store(self.oil, "XAUUSD", "narrow")
        for sym in ("BTCUSD", "AAPL", "SPX500"):
            _store(self.inst[sym], sym, "wide")
        eur, gold = self.inst["EURUSD"], self.inst["XAUUSD"]
        for at in (FRI_21 + 3 * M15, FRI_22, SAT_12, SAT_12 + M15,
                   SUN_20 + 7 * M15, SUN_20 + 8 * M15):
            _flat(eur, "15m", at, 1.1)
            _flat(gold, "15m", at, 2000.0)


class TheDryRunTests(_Prune):

    def test_the_dry_run_deletes_nothing_and_prints_counts_only(self):
        from indicators.tasks import recalculate_for_instruments
        self.store_week()
        recalculate_for_instruments(
            [self.inst[s] for s in ("HGUSD", "EURUSD")], timeframes=("4h",))
        bars, inds = _bars(), _indicators()
        self.assertEqual(len(inds), 2)
        gone = _gone_by_the_rule(bars)
        want = _counts(gone)
        self.assertEqual(set(want), {("forex", "1h"), ("forex", "4h"),
                                     ("forex", "15m"), ("commodity", "1h"),
                                     ("commodity", "4h")})
        out = self.prune()
        self.assertEqual(_bars(), bars, "the dry run deleted something")
        self.assertEqual(_indicators(), inds)
        for (cls, tf), n in want.items():
            self.assertRegex(out, rf"(?m)^\s+{cls} {tf}: {n}$")
        self.assertRegex(out, rf"(?m)^Total: {len(gone)} bars in "
                              rf"{len({k[:2] for k in gone})} series\.$")
        # counts only: no price, no id, no symbol
        self.assertNotRegex(out, r"\d[.,]\d")
        for sym in list(SYMBOLS) + [self.oil.symbol]:
            self.assertNotIn(sym, out)
        numbers = re.sub(r"\b\d+[mhdw]\b", "", out)
        allowed = {str(n) for n in want.values()} | {
            str(len(gone)), str(len({k[:2] for k in gone}))}
        self.assertLessEqual(set(re.findall(r"\d+", numbers)), allowed,
                             out)
        last = out.strip().splitlines()[-1]
        self.assertIn("nothing was deleted", last.lower())
        self.assertIn("bars_shut_prune --apply", last)

    def test_the_words_give_the_server_form_and_the_weekday(self):
        """The operator runs it inside docker, as the RUNBOOK does, and on a
        weekday: the dry run's last line and --help both say so."""
        from market_data.management.commands.bars_shut_prune import Command
        self.store_week()
        last = self.prune().strip().splitlines()[-1]
        self.assertIn("on a weekday", last)
        self.assertIn("./deploy/dc exec -T web python manage.py "
                      "bars_shut_prune --apply", last)
        self.assertIn("weekday", Command.help)
        self.assertIn("ten minutes", Command.help)

    def test_symbols_adds_each_symbols_count(self):
        self.store_week()
        gone = _gone_by_the_rule(_bars())
        out = self.prune("--symbols")
        per = {}
        for sym, tf, _ts in gone:
            per[(sym, tf)] = per.get((sym, tf), 0) + 1
        for (sym, tf), n in per.items():
            self.assertRegex(out, rf"(?m)^\s+{sym} {tf}: {n}$")
        for sym in ("XAUUSD", "XAGUSD", "BTCUSD", "AAPL", "SPX500",
                    self.oil.symbol):
            self.assertNotIn(sym, out)
        self.assertNotRegex(out, r"\d[.,]\d")
        self.assertIn("nothing was deleted", out.strip().splitlines()[-1]
                      .lower())

    def test_nothing_to_prune_says_so(self):
        _store(self.inst["EURUSD"], "EURUSD", None)
        bars = _bars()
        out = self.prune()
        self.assertEqual(_bars(), bars)
        self.assertIn("nothing was deleted", out.strip().splitlines()[-1]
                      .lower())
        self.assertNotIn("--apply", out)

    def test_a_bad_since_is_refused(self):
        _store(self.inst["EURUSD"], "EURUSD", "flat")
        bars = _bars()
        for bad in ("2026-13-01", "last week", "19/11/2026"):
            with self.assertRaisesRegex(CommandError, "--since"):
                self.prune("--apply", "--since", bad)
        self.assertEqual(_bars(), bars)


class TheApplyTests(_Prune):

    def test_apply_deletes_exactly_the_bars_the_rule_rejects(self):
        self.store_week()
        bars = _bars()
        gone = _gone_by_the_rule(bars)
        out = self.prune("--apply")
        after = _bars()
        self.assertEqual(set(bars) - set(after), gone)
        self.assertEqual(set(after) - set(bars), set())
        for k, v in after.items():
            self.assertEqual(v, bars[k], k)
        self.assertRegex(out, rf"(?m)^Deleted {len(gone)} bars in "
                              rf"{len({k[:2] for k in gone})} series")
        self.assertNotRegex(out, r"\d[.,]\d")
        for sym in SYMBOLS:
            self.assertNotIn(sym, out)

    def test_apply_recomputes_the_stored_indicators_from_the_cleaned_bars(
            self):
        """The indicator task stored a row on Saturday (keyed at the
        weekend bar that was the newest then) and one at the reopen, its
        ATR(4h) moved by the weekend's candles: deflated by Friday's close
        repeated all weekend, inflated by wide moving candles, deflated by
        narrow ones. After --apply no indicator row is left at a deleted
        bar, and the stored atr_14 the entry stops and sizes read first
        (risk_levels.atr_for) is the traded week's: it rises after a flat or
        a narrow weekend (stops wider, sizes smaller) and falls after a wide
        one (stops tighter, sizes larger)."""
        from bot_program.asset_engine import risk_levels
        from indicators.models import TechnicalIndicator
        from indicators.tasks import recalculate_for_instruments
        from market_data.models import PriceData
        for weekend in ("flat", "wide", "narrow"):
            with self.subTest(weekend=weekend):
                PriceData.objects.all().delete()
                TechnicalIndicator.objects.all().delete()
                for sym in ("HGUSD", "EURUSD"):
                    inst = self.inst[sym]
                    _store(inst, sym, weekend, intervals=("4h",),
                           until=SAT_1201)
                    recalculate_for_instruments([inst], timeframes=("4h",))
                    _store(inst, sym, weekend, intervals=("4h",),
                           since=SAT_1201, until=SUN_2315)
                    recalculate_for_instruments([inst], timeframes=("4h",))
                before = _indicators()
                for sym in ("HGUSD", "EURUSD"):
                    traded = _atr_of(_candles(sym, "4h"))
                    self.assertIn((sym, "4h", SAT_12), before)
                    was = float(before[(sym, "4h", SUN_20)][0])
                    if weekend == "flat":
                        self.assertLess(was, 0.5 * traded, sym)
                    elif weekend == "wide":
                        self.assertGreater(was, 1.5 * traded, sym)
                    else:
                        self.assertLess(was, traded, sym)
                self.prune("--apply")
                after = _indicators()
                for sym in ("HGUSD", "EURUSD"):
                    traded = _atr_of(_candles(sym, "4h"))
                    was = float(before[(sym, "4h", SUN_20)][0])
                    self.assertNotIn((sym, "4h", SAT_12), after)
                    self.assertFalse(any(k[0] == sym and _shut_bar(
                        sym, k[2], k[2] + SPAN["4h"]) for k in after), sym)
                    now = float(after[(sym, "4h", SUN_20)][0])
                    self.assertAlmostEqual(now, traded, places=6)
                    self.assertAlmostEqual(risk_levels.atr_for(sym, "4h"),
                                           traded, places=6)
                    if weekend == "wide":
                        self.assertLess(now, was, sym)
                    else:
                        self.assertGreater(now, was, sym)

    def test_a_series_left_too_short_loses_every_indicator_row(self):
        """A short 4h series with indicators stored, whose weekend rows
        leave fewer than MIN_BARS bars: nothing can be recomputed, so every
        indicator row of the series goes, an older one too (atr_for reads
        the newest row left, whatever its age), the words name it, and the
        stops read the cleaned bars themselves."""
        from bot_program.asset_engine import risk_levels
        from indicators.models import TechnicalIndicator
        from indicators.tasks import MIN_BARS, recalculate_for_instruments
        from market_data.models import PriceData
        eur = self.inst["EURUSD"]
        since = datetime(2026, 11, 10, 20, tzinfo=UTC)
        _store(eur, "EURUSD", "flat", intervals=("4h",), since=since)
        stored = PriceData.objects.filter(instrument=eur).count()
        shut = len(_gone_by_the_rule(_bars()))
        self.assertGreaterEqual(stored, MIN_BARS)
        self.assertLess(stored - shut, MIN_BARS)
        recalculate_for_instruments([eur], timeframes=("4h",))
        self.assertIn(("EURUSD", "4h", SUN_20), _indicators())
        TechnicalIndicator.objects.create(
            instrument=eur, timeframe="4h", timestamp=since + 4 * SPAN["1h"],
            atr_14=Decimal("0.0099"))
        out = self.prune("--apply")
        self.assertRegex(out, r"(?m)^Too few bars left to recompute: 1 "
                              r"series; all their 2 indicator rows were "
                              r"deleted")
        self.assertNotIn("recompute failed", out)
        self.assertFalse(TechnicalIndicator.objects.filter(
            instrument=eur, timeframe="4h").exists())
        left = [c for c in _candles("EURUSD", "4h", "flat")
                if since <= c.open <= SUN_2315
                and not _shut_bar("EURUSD", c.open, c.open + SPAN["4h"])]
        self.assertEqual(len(left), stored - shut)
        self.assertAlmostEqual(risk_levels.atr_for("EURUSD", "4h"),
                               _atr_of(left), places=9)

    def test_a_failed_recompute_is_said_and_leaves_no_stale_row(self):
        """The recompute can fail (the indicator task counts an error). The
        words say so, never "too few bars", and every indicator row of the
        series goes: with --since, the rows older than the window used to
        survive, and atr_for read the newest of them, days old."""
        from bot_program.asset_engine import risk_levels
        from indicators.models import TechnicalIndicator
        from indicators.tasks import recalculate_for_instruments
        copper = self.inst["HGUSD"]
        wednesday = datetime(2026, 11, 11, 12, tzinfo=UTC)
        _store(copper, "HGUSD", "flat", intervals=("4h",), until=wednesday)
        recalculate_for_instruments([copper], timeframes=("4h",))
        _store(copper, "HGUSD", "flat", intervals=("4h",),
               since=wednesday + timedelta(minutes=1))
        recalculate_for_instruments([copper], timeframes=("4h",))
        self.assertEqual(set(k[2] for k in _indicators()),
                         {wednesday, SUN_20})
        with patch("indicators.calculator.compute_all_indicators",
                   side_effect=ValueError("invented")):
            out = self.prune("--apply", "--since", "2026-11-09")
        self.assertRegex(out, r"(?m)^The recompute failed for 1 series")
        self.assertNotIn("Too few bars", out)
        self.assertFalse(TechnicalIndicator.objects.filter(
            instrument=copper, timeframe="4h").exists())
        since = datetime(2026, 11, 9, tzinfo=UTC)
        left = [c for c in _candles("HGUSD", "4h", "flat")
                if c.open <= SUN_2315 and not (
                    c.open >= since
                    and _shut_bar("HGUSD", c.open, c.open + SPAN["4h"]))]
        self.assertAlmostEqual(risk_levels.atr_for("HGUSD", "4h"),
                               _atr_of(left), places=9)

    def test_a_run_cut_before_its_recompute_is_finished_by_the_next(self):
        """A series' last delete batch and its recompute are one
        transaction: a run cut while the indicators are recomputed leaves
        that batch stored, and the next --apply deletes it and recomputes,
        so the stored atr_14 the stops read first is the traded week's
        (before, the next run found nothing and left it deflated)."""
        from bot_program.asset_engine import risk_levels
        from indicators.tasks import recalculate_for_instruments

        class Cut(Exception):
            """The process stopped mid-run."""

        copper = self.inst["HGUSD"]
        _store(copper, "HGUSD", "flat", intervals=("4h",))
        recalculate_for_instruments([copper], timeframes=("4h",))
        traded = _atr_of(_candles("HGUSD", "4h"))
        self.assertLess(risk_levels.atr_for("HGUSD", "4h"), 0.5 * traded)
        gone = _gone_by_the_rule(_bars())
        self.assertGreater(len(gone), 10)
        with patch(f"{COMMAND}.BATCH", 5), \
                patch("indicators.tasks.recalculate_for_instruments",
                      side_effect=Cut):
            with self.assertRaises(Cut):
                self.prune("--apply")
        left = _gone_by_the_rule(_bars())
        self.assertTrue(left, "the cut batch was deleted all the same")
        self.assertLess(len(left), len(gone))
        self.assertLess(risk_levels.atr_for("HGUSD", "4h"), 0.5 * traded)
        out = self.prune("--apply")
        self.assertRegex(out, rf"(?m)^Deleted {len(left)} bars in 1 series")
        self.assertRegex(out, r"(?m)^Indicators recomputed from the cleaned "
                              r"bars: 1 series\.$")
        self.assertEqual(_gone_by_the_rule(_bars()), set())
        self.assertAlmostEqual(risk_levels.atr_for("HGUSD", "4h"), traded,
                               places=6)

    def test_a_second_apply_finds_nothing_and_changes_nothing(self):
        from indicators.tasks import recalculate_for_instruments
        self.store_week()
        recalculate_for_instruments(
            [self.inst[s] for s in ("HGUSD", "EURUSD", "XAUUSD")],
            timeframes=("4h",))
        self.prune("--apply")
        bars, inds = _bars(), _indicators()
        self.assertTrue(bars and inds)
        out = self.prune("--apply")
        self.assertEqual(_bars(), bars)
        self.assertEqual(_indicators(), inds)
        self.assertNotRegex(out, r"(?m)^Deleted [1-9]")
        self.assertIn("nothing was deleted", out.strip().splitlines()[-1]
                      .lower())
        self.assertNotIn("--apply", out)

    def test_it_never_touches_nor_judges_what_the_rule_does_not_cover(self):
        """eToro's all-week instruments (gold, silver, OIL), crypto, a stock
        and an index keep every eToro row, the weekend's included, and
        another source's weekend rows of a currency pair stay: none of
        them is even offered to the predicate. Of the rows it judges, the
        bars that hold open time stay: the Sunday 20:00 UTC 4h bar that
        holds the reopen, the Friday 21:00 UTC 1h EURUSD bar in winter
        (eToro's FX week runs to 22:00 UTC) and the CME daily break."""
        from market_data.shut_bars import holds_no_open_time
        self.store_week()
        gbp, copper = self.inst["GBPUSD"], self.inst["HGUSD"]
        from market_data.models import PriceData
        PriceData.objects.filter(instrument=gbp, timeframe="1h").delete()
        others = ("yfinance_public", "yfinance", "alpha_vantage", "ibkr")
        for n, source in enumerate(others):
            _flat(gbp, "1h", SAT_12 + n * timedelta(hours=1), 1.3, source)
        PriceData.objects.filter(instrument=copper, timeframe="1h",
                                 timestamp=TUE_22).update(
            open=Decimal("4.01"), high=Decimal("4.01"), low=Decimal("4.01"),
            close=Decimal("4.01"), volume=0)
        bars = _bars()
        offered = []

        def spy(inst, tf, at):
            offered.append((inst.symbol, tf, at))
            return holds_no_open_time(inst, tf, at)
        with patch(f"{COMMAND}.holds_no_open_time", spy):
            self.prune("--apply")
        after = _bars()
        untouched = {k for k, v in bars.items()
                     if k[0] in ("XAUUSD", "XAGUSD", self.oil.symbol,
                                 "BTCUSD", "AAPL", "SPX500")
                     or v[-1] != "etoro"}
        self.assertGreater(len(untouched), 1000)
        self.assertTrue(any(k[0] == "XAUUSD" and _shut_bar(
            "HGUSD", k[2], k[2] + SPANS[k[1]]) for k in untouched),
            "the fixture holds no weekend gold")
        for k in untouched:
            self.assertEqual(after.get(k), bars[k], k)
        self.assertEqual(set(offered) & untouched, set())
        self.assertTrue(offered)
        for k in (("EURUSD", "4h", SUN_20), ("HGUSD", "4h", SUN_20),
                  ("GBPUSD", "4h", SUN_20), ("EURUSD", "1h", FRI_21),
                  ("GBPUSD", "4h", SUN_20 - timedelta(days=2)),
                  ("HGUSD", "1h", TUE_22),
                  ("EURUSD", "15m", FRI_21 + 3 * M15),
                  ("EURUSD", "15m", SUN_20 + 8 * M15)):
            self.assertIn(k, bars, k)
            self.assertEqual(after.get(k), bars[k], k)
        self.assertEqual(bars[("HGUSD", "1h", TUE_22)][1],
                         bars[("HGUSD", "1h", TUE_22)][2], "a flat break bar")
        for k in (("EURUSD", "1h", FRI_22), ("EURUSD", "15m", FRI_22),
                  ("EURUSD", "15m", SUN_20 + 7 * M15),
                  ("HGUSD", "4h", SAT_12)):
            self.assertIn(k, bars, k)
            self.assertNotIn(k, after, k)

    def test_since_limits_the_window(self):
        """--since YYYY-MM-DD: only the bars opening on or after that day
        (UTC) are counted and deleted; the weekends before it stay."""
        self.store_week()
        since = datetime(2026, 11, 9, tzinfo=UTC)
        bars = _bars()
        gone = _gone_by_the_rule(bars)
        late = {k for k in gone if k[2] >= since}
        early = gone - late
        self.assertTrue(late and early)
        out = self.prune("--since", "2026-11-09")
        self.assertEqual(_bars(), bars)
        self.assertRegex(out, rf"(?m)^Total: {len(late)} bars in ")
        self.assertIn("--since 2026-11-09", out.strip().splitlines()[-1])
        self.prune("--apply", "--since", "2026-11-09")
        after = _bars()
        self.assertEqual(set(bars) - set(after), late)
        for k in early:
            self.assertIn(k, after)
        out = self.prune()
        self.assertRegex(out, rf"(?m)^Total: {len(early)} bars in ")

    def test_the_orcs_gap_memos_of_the_changed_symbols_are_cleared(self):
        """The Orcs keep each symbol's weekend gap and print gaps for the
        UTC day (bot_program/orcs/gaps.py), measured on its 1h venue bars:
        weekend bars leave no hole to measure, so today's memo would read
        the old bars until midnight. --apply clears today's weekend memo of
        every symbol whose 1h bars it changed, and the print memo of a
        print dated inside a deleted bar; another symbol's memo stays."""
        from bot_program.orcs import gaps
        from market_data.models import EconomicEvent
        self.store_week()
        EconomicEvent.objects.create(
            title="Invented print", country="US", currency_affected="USD",
            datetime=SAT_12 + timedelta(minutes=30), impact="High",
            source="test")
        keys = {
            "eur_weekend": gaps._key(gaps.KIND_WEEKEND, "EURUSD", "weekend",
                                     NOW),
            "copper_weekend": gaps._key(gaps.KIND_WEEKEND, "HGUSD",
                                        "weekend", NOW),
            "eur_print": gaps._key(gaps.KIND_PRINT, "EURUSD",
                                   "Invented print|USD", NOW),
            "eur_print_any": gaps._key(gaps.KIND_PRINT, "EURUSD",
                                       "Invented print|", NOW),
            "gold_weekend": gaps._key(gaps.KIND_WEEKEND, "XAUUSD", "weekend",
                                      NOW),
            "btc_range": gaps._key(gaps.KIND_RANGE, "BTCUSD", "range", NOW),
        }
        for key in keys.values():
            cache.set(key, ("weekend", "weekend", 0, None, "etoro"), 3600)
        self.prune()
        self.assertTrue(all(cache.get(k) for k in keys.values()),
                        "the dry run cleared a memo")
        self.prune("--apply")
        for name in ("eur_weekend", "copper_weekend", "eur_print",
                     "eur_print_any"):
            self.assertIsNone(cache.get(keys[name]), name)
        for name in ("gold_weekend", "btc_range"):
            self.assertIsNotNone(cache.get(keys[name]), name)

    def test_a_memo_clearing_that_fails_is_said_by_its_kind_only(self):
        """The cache's own words name its host and port; the output prints
        the error's kind only, and the bars are deleted all the same."""
        self.store_week()
        gone = _gone_by_the_rule(_bars())
        err = ConnectionError("Error 111 connecting to invented-cache-host:"
                              "6379. Connection refused.")
        with patch(f"{COMMAND}._clear_gap_memos", side_effect=err):
            out = self.prune("--apply")
        self.assertIn("The Orcs' gap memos were not all cleared "
                      "(ConnectionError); they are measured again at 00:00 "
                      "UTC.", out)
        for leaked in ("invented-cache-host", "6379", "Error 111",
                       "refused"):
            self.assertNotIn(leaked, out)
        self.assertEqual(_gone_by_the_rule(_bars()), set())
        self.assertRegex(out, rf"(?m)^Deleted {len(gone)} bars in ")

    def test_apply_warns_while_a_market_it_judges_is_shut(self):
        """Run during a weekend, the prune moves a frame's newest final bar
        back to Friday's and an Orc may wake once on it: --apply says so,
        and goes on. On a weekday it says nothing of it."""
        saturday = datetime(2026, 11, 21, 12, tzinfo=UTC)
        for now, warned in ((saturday, True), (NOW, False)):
            with self.subTest(now=f"{now:%a}"):
                from market_data.models import PriceData
                PriceData.objects.all().delete()
                self.store_week()
                out = self.prune("--apply", now=now)
                self.assertEqual("Warning: some of the markets it judges "
                                 "are shut now" in out, warned, out)
                self.assertRegex(out, r"(?m)^Deleted [1-9]")
                self.assertEqual(_gone_by_the_rule(_bars()), set())
        dry = self.prune(now=saturday)
        self.assertNotIn("Warning", dry)
