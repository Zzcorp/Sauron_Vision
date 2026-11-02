"""THE BACKFILL NEVER WRITES THE PUBLIC FEED OVER OR BESIDE A VENUE'S BARS
(2026-11-01).

backfill_bars handed every Yahoo row (Binance's, for crypto) to
bot_bars._upsert_rows, an update_or_create on (instrument, timeframe,
timestamp) that replaces the OHLC and the source, with no venue guard,
unlike the bar pass and the watchlist pass. With --proving it took every
enabled bot's symbols and every open row, so on an eToro-routed live
symbol it relabelled eToro's 1h candles as the public feed's where the
hours met (XAUUSD became GC=F, BTCUSD became BTCUSDT), and it put Yahoo's
:30 bars beside eToro's :00 bars for US stocks and indices. The next pass
gave back at most the venue's 200-bar window, and the bots read 1h bars
of any source: venue_exit books an eToro-side exit at a stop or a target
a 1h bar reached, risk_levels.atr_for reads 1h, Morgul's G4 too.

Now a series a venue wrote (any source that is not a public feed's, the
test the bar pass reads) gets the public feed's rows only OUTSIDE the
venue's span: bars that have ended by the time the venue's first bar
opens, and bars after its last by the pass's own rule
(_after_the_venues_last_bar) once that bar is stale by the pass's bound;
while the venue is live, its next bars are the bar pass's. The writer
itself never lets a public feed's row replace a venue's, so a bar the
pass writes between the backfill's check and its write stays the
venue's. The Yahoo EOD's own daily bars ("yfinance") are the public
feed's, never a venue's. The run says, per symbol, how many it kept out
and why; the --proving footer cites the interval it filled and invites
no step that sizes real money. The bar pass's own keyless branch (a
config whose client IS the public feed) gets the pass's rule too. No
test reaches a network: the feeds are fakes.

Run with:  python manage.py test tests.test_backfill_venue_guard
"""
from datetime import timedelta
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from tests.test_backfill_bars_every_class import _cfg, _instrument

H = timedelta(hours=1)
D = timedelta(days=1)

#: The closing words of a per-symbol line, as the run prints them for a
#: class other than crypto (bot_bars.STALE_VENUE_AFTER_S) and for crypto
#: (bot_bars.STALE_VENUE_BARS_CRYPTO).
WHY = ("public bars go only before its first bar, and after its last once "
       "that bar is stale ({}, the bar pass's bound): while the venue is "
       "live, its next bars are the bar pass's")


def _hour():
    """The current hour's open, UTC."""
    return timezone.now().replace(minute=0, second=0, microsecond=0)


def _ms(ts):
    return int(ts.timestamp() * 1000)


def _row(ts, px):
    """A kline the writer accepts: low < open = close < high."""
    return [_ms(ts), str(px), str(round(px * 1.001, 6)),
            str(round(px * 0.999, 6)), str(px), "10"]


def _put(inst, ts, source, px, timeframe="1h"):
    from market_data.models import PriceData
    PriceData.objects.create(instrument=inst, timeframe=timeframe,
                             timestamp=ts, open=px, high=px + 1,
                             low=px - 1, close=px, volume=1, source=source)


def _series(inst, timeframe="1h"):
    """{timestamp: (source, close)} of a stored series."""
    from market_data.models import PriceData
    return {ts: (src, float(c)) for ts, src, c in
            PriceData.objects.filter(instrument=inst, timeframe=timeframe)
            .values_list("timestamp", "source", "close")}


def _whole(inst, timeframe="1h"):
    """Every stored column of a series, by timestamp."""
    from market_data.models import PriceData
    return {r[0]: r[1:] for r in
            PriceData.objects.filter(instrument=inst, timeframe=timeframe)
            .values_list("timestamp", "open", "high", "low", "close",
                         "volume", "source")}


class YFinanceFeed:
    """The keyless feed's fake, named like the real one (the source tag is
    read off the class): it answers the rows the test gave it for a symbol
    and remembers what it was asked."""
    _sv_public_feed = True

    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def klines(self, symbol, interval="1h", limit=200, **kw):
        self.calls.append((symbol, interval, limit))
        return list(self.rows.get(symbol, []))


def _run(feed, *args):
    out, err = StringIO(), StringIO()
    with patch("market_data.public_feed.public_feed_for", return_value=feed):
        call_command("backfill_bars", *args, stdout=out, stderr=err)
    return out.getvalue(), err.getvalue()


def _the_pass_lands_first(landed_row, inst):
    """A stand-in for bot_bars._upsert_rows that lets the bar pass (another
    process) write the venue's bar `landed_row` for `inst` right before the
    backfill's first public write: after the backfill read the venue's
    span, before it wrote. Then it writes what it was given."""
    from market_data import bot_bars
    real = bot_bars._upsert_rows
    landed = []

    def upsert(target, interval, rows, source, **kw):
        if str(source).endswith("_public") and not landed:
            landed.append(real(inst, interval, [landed_row], "etoro"))
        return real(target, interval, rows, source, **kw)
    return upsert, landed


class _Venue(TestCase):
    """eToro's own 1h candles for gold and NVDA, on the hour, from six
    hours back to the last closed hour: a live venue."""

    def setUp(self):
        self.now = _hour()
        self.gold = _instrument("XAUUSD", "commodity")
        self.nvda = _instrument("NVDA", "stock")
        for h in range(1, 7):
            _put(self.gold, self.now - h * H, "etoro", 4000 + h)
            _put(self.nvda, self.now - h * H, "etoro", 200 + h)
        self.first, self.last = self.now - 6 * H, self.now - H

    def _gold_rows(self):
        """Yahoo's GC=F (the future, another price), on the hour: the
        forming hour and eight closed ones."""
        return [_row(self.now - h * H, 4030 + h) for h in range(8, -1, -1)]

    def _nvda_rows(self):
        """Yahoo's US equity hour bars open at :30."""
        return [_row(self.now - h * H + H / 2, 200.5 + h)
                for h in range(8, 0, -1)]

    def _both(self):
        return YFinanceFeed({"XAUUSD": self._gold_rows(),
                             "NVDA": self._nvda_rows()})


class TheVenuesBarsAreNeverWrittenOverTests(_Venue):

    def test_a_venue_hour_is_never_replaced_and_keeps_its_source(self):
        before = _whole(self.gold)
        _run(YFinanceFeed({"XAUUSD": self._gold_rows()}),
             "--symbols", "XAUUSD", "--intervals", "1h", "--bars", "9000")
        after = _whole(self.gold)
        for ts, kept in before.items():
            self.assertEqual(after[ts], kept,
                             f"eToro's {ts:%H:%M} candle was replaced")

    def test_no_public_bar_lands_between_the_venues_bars_whatever_the_minute(self):
        _run(YFinanceFeed({"NVDA": self._nvda_rows()}),
             "--symbols", "NVDA", "--intervals", "1h", "--bars", "9000")
        inside = sorted(ts for ts, (src, _c) in _series(self.nvda).items()
                        if not src == "etoro"
                        and self.first <= ts <= self.last)
        self.assertEqual(inside, [], "a :30 bar beside eToro's :00 bars")

    def test_older_history_before_the_venues_first_bar_is_written(self):
        _run(self._both(), "--symbols", "XAUUSD,NVDA", "--intervals", "1h",
             "--bars", "9000")
        gold, nvda = _series(self.gold), _series(self.nvda)
        self.assertEqual(gold[self.now - 7 * H], ("yfinance_public", 4037.0))
        self.assertEqual(gold[self.now - 8 * H], ("yfinance_public", 4038.0))
        self.assertEqual(nvda[self.now - 8 * H + H / 2],
                         ("yfinance_public", 208.5))

    def test_a_public_bar_that_runs_into_the_venues_first_bar_is_not_written(self):
        """Before the venue's first bar means ENDED by the time it opens:
        the :30 bar that opened half an hour before eToro's first :00 bar
        runs half an hour beside it."""
        _run(YFinanceFeed({"NVDA": self._nvda_rows()}),
             "--symbols", "NVDA", "--intervals", "1h", "--bars", "9000")
        self.assertNotIn(self.first - H / 2, _series(self.nvda))

    def test_after_a_live_venues_newest_bar_nothing_is_written(self):
        """THE TAIL IS THE BAR PASS'S WHILE THE VENUE IS LIVE (2026-11-01).
        The pass writes the public feed after a venue's newest bar only
        when the venue gave nothing usable or a stale window; the backfill
        wrote that tail while eToro was live and simply not asked for the
        new hour yet: gold's forming hour became GC=F's, NVDA's :30 bar
        ran beside eToro's last :00 bar, and a real row's exit booking
        read them until the next pass."""
        from bot_program import venue_exit
        from market_data.bot_bars import STALE_VENUE_AFTER_S
        self.assertLess((timezone.now() - self.last).total_seconds(),
                        STALE_VENUE_AFTER_S)
        _run(self._both(), "--symbols", "XAUUSD,NVDA", "--intervals", "1h",
             "--bars", "9000")
        self.assertNotIn(self.now, _series(self.gold))
        self.assertNotIn(self.now - H / 2, _series(self.nvda))
        for inst in (self.gold, self.nvda):
            got = _series(inst)
            self.assertEqual(max(got), self.last, inst.symbol)
            self.assertEqual(got[max(got)][0], "etoro", inst.symbol)
        # A real eToro BUY last seen open two minutes before the hour, its
        # target reached by GC=F's forming hour (high 4034) and never by
        # eToro's own price: no bar of the backfill's books it.
        trade = SimpleNamespace(symbol="XAUUSD", side="BUY")
        self.assertIsNone(venue_exit._bars_reached(
            trade, {"stop": 3990.0, "target": 4030.0},
            since=self.now - timedelta(minutes=2),
            until=self.now + timedelta(minutes=8)))

    def test_a_rerun_leaves_the_venue_rows_untouched(self):
        venue = {i.symbol: _whole(i) for i in (self.gold, self.nvda)}
        args = ("--symbols", "XAUUSD,NVDA", "--intervals", "1h", "--bars",
                "9000")
        _run(self._both(), *args)
        once = {i.symbol: _whole(i) for i in (self.gold, self.nvda)}
        _run(self._both(), *args)
        twice = {i.symbol: _whole(i) for i in (self.gold, self.nvda)}
        self.assertEqual(twice, once, "a re-run changes nothing")
        for sym, rows in venue.items():
            for ts, kept in rows.items():
                self.assertEqual(twice[sym][ts], kept, (sym, ts))

    def test_the_run_says_per_symbol_what_it_kept_out_for_the_venue_and_why(self):
        out, _err = _run(self._both(), "--symbols", "XAUUSD,NVDA",
                         "--intervals", "1h", "--bars", "9000")
        span = (f"etoro wrote this series from {self.first:%Y-%m-%d %H:%M} "
                f"to {self.last:%Y-%m-%d %H:%M} UTC")
        self.assertIn("XAUUSD 1h: 7 public bar(s) skipped for the venue: "
                      + span + " (6 at its own timestamps, 0 beside its "
                      "bars, 1 after its newest bar); " + WHY.format("72 h"),
                      out)
        self.assertIn("NVDA 1h: 7 public bar(s) skipped for the venue: "
                      + span + " (0 at its own timestamps, 6 beside its "
                      "bars, 1 after its newest bar); " + WHY.format("72 h"),
                      out)
        self.assertIn("XAUUSD     1h       9 bars fetched (public feed), 2 "
                      "written", out)
        self.assertIn("14 public bar(s) skipped for a venue's bars", out)
        self.assertNotIn("the public feed's bars after it", out)

    def test_the_dry_run_counts_what_it_would_write_after_the_guard(self):
        before = _whole(self.gold)
        out, _err = _run(YFinanceFeed({"XAUUSD": self._gold_rows()}),
                         "--symbols", "XAUUSD", "--intervals", "1h",
                         "--bars", "9000", "--dry-run")
        self.assertIn("would write 2 bars", out)
        self.assertIn("XAUUSD 1h: 7 public bar(s) skipped for the venue", out)
        self.assertEqual(_whole(self.gold), before, "a dry run writes nothing")

    def test_the_guard_holds_for_from_configs_and_proving_alike(self):
        user = User.objects.create_user("guard_u", password="x")
        _cfg(user, "commodity", ["XAUUSD"])
        before = _whole(self.gold)
        for how in ("--from-configs", "--proving"):
            out, _err = _run(YFinanceFeed({"XAUUSD": self._gold_rows()}),
                             how, "--intervals", "1h", "--bars", "9000")
            self.assertIn("XAUUSD 1h: 7 public bar(s) skipped for the venue",
                          out, how)
            after = _whole(self.gold)
            for ts, kept in before.items():
                self.assertEqual(after[ts], kept, (how, ts))
            self.assertNotIn(self.now, _series(self.gold), how)

    def test_the_guard_holds_at_4h_too(self):
        step = 4 * H
        grid = self.now.replace(hour=self.now.hour - self.now.hour % 4)
        for k in (1, 2, 3):
            _put(self.gold, grid - k * step, "etoro", 4100 + k, "4h")
        rows = [_row(grid - k * step, 4130 + k) for k in range(4, -1, -1)]
        out, _err = _run(YFinanceFeed({"XAUUSD": rows}), "--symbols",
                         "XAUUSD", "--intervals", "4h", "--bars", "4000")
        got = _series(self.gold, "4h")
        for k in (1, 2, 3):
            self.assertEqual(got[grid - k * step], ("etoro", 4100.0 + k))
        self.assertEqual(got[grid - 4 * step], ("yfinance_public", 4134.0),
                         "it ends as the venue's first bar opens")
        self.assertNotIn(grid, got, "after a live venue's newest bar: the "
                                    "bar pass's")
        self.assertIn("XAUUSD 4h: 4 public bar(s) skipped for the venue", out)


class AStaleVenuesTailTests(TestCase):
    """A venue whose newest bar is stale by the bar pass's own bound
    (bot_bars.STALE_VENUE_AFTER_S) gets the public feed after it, by the
    pass's rule (_after_the_venues_last_bar): the pass writes that tail
    itself, its stale-window fallback. Its own bars, and the hours between
    them, stay its own."""

    def setUp(self):
        self.now = _hour()
        self.quiet = self.now - 100 * H
        self.gold = _instrument("XAUUSD", "commodity")
        self.nvda = _instrument("NVDA", "stock")
        for h in range(0, 6):
            _put(self.gold, self.quiet - h * H, "etoro", 4000 + h)
            _put(self.nvda, self.quiet - h * H, "etoro", 200 + h)

    def test_bars_after_a_stale_venues_last_are_written_by_the_pass_rule(self):
        from market_data.bot_bars import (STALE_VENUE_AFTER_S,
                                          _after_the_venues_last_bar)
        self.assertGreater((timezone.now() - self.quiet).total_seconds(),
                           STALE_VENUE_AFTER_S)
        gold_rows = [_row(self.quiet + k * H, 4030 + k) for k in range(-2, 4)]
        nvda_rows = [_row(self.quiet + k * H + H / 2, 200.5 + k)
                     for k in range(-2, 4)]
        want_gold = {r[0] for r in
                     _after_the_venues_last_bar(self.gold, "1h", gold_rows)}
        want_nvda = {r[0] for r in
                     _after_the_venues_last_bar(self.nvda, "1h", nvda_rows)}
        self.assertEqual(want_gold, {_ms(self.quiet + k * H)
                                     for k in (1, 2, 3)})
        self.assertEqual(want_nvda, {_ms(self.quiet + k * H + H / 2)
                                     for k in (0, 1, 2, 3)})
        venue = {i.symbol: _whole(i) for i in (self.gold, self.nvda)}
        out, _err = _run(YFinanceFeed({"XAUUSD": gold_rows,
                                       "NVDA": nvda_rows}),
                         "--symbols", "XAUUSD,NVDA", "--intervals", "1h",
                         "--bars", "9000")
        for inst, want in ((self.gold, want_gold), (self.nvda, want_nvda)):
            got = {_ms(ts) for ts, (src, _c) in _series(inst).items()
                   if src == "yfinance_public"}
            self.assertEqual(got, want, inst.symbol)
            whole = _whole(inst)
            for ts, kept in venue[inst.symbol].items():
                self.assertEqual(whole[ts], kept, (inst.symbol, ts))
        # 100 h old, 101 if the hour turned while the test ran
        stale = (rf"the venue's newest bar \(etoro, "
                 rf"{self.quiet:%Y-%m-%d %H:%M} UTC\) is stale, 10[01] h old: "
                 rf"the public feed's bars after it are written, the bar "
                 rf"pass's own rule")
        self.assertRegex(out, "XAUUSD 1h: " + stale)
        self.assertRegex(out, "NVDA 1h: " + stale)
        self.assertIn("XAUUSD 1h: 3 public bar(s) skipped for the venue", out)
        self.assertIn("NVDA 1h: 2 public bar(s) skipped for the venue", out)

    def test_the_dry_run_says_what_it_would_write_after_a_stale_venue(self):
        rows = [_row(self.quiet + k * H, 4030 + k) for k in range(1, 4)]
        out, _err = _run(YFinanceFeed({"XAUUSD": rows}), "--symbols",
                         "XAUUSD", "--intervals", "1h", "--bars", "9000",
                         "--dry-run")
        self.assertRegex(out, r"is stale, 10[01] h old: the public feed's "
                              r"bars after it would be written, the bar "
                              r"pass's own rule")
        self.assertIn("would write 3 bars", out)
        self.assertNotIn("skipped for the venue", out)


class TheWriteNeverReplacesAVenuesBarTests(TestCase):
    """THE GUARD HOLDS AT THE WRITE (2026-11-01). The command reads the
    venue's span, then writes, and the bar pass runs every ten minutes in
    another process: an eToro bar it wrote in between was replaced, OHLC
    and source, by the public feed's bar at that timestamp, until a later
    pass gave it back. The writer itself now never lets a public feed's
    row replace a venue's, whoever calls it and whenever the venue's bar
    landed."""

    def setUp(self):
        self.now = _hour()

    def test_the_writer_never_lets_a_public_row_replace_a_venue_row(self):
        from market_data.bot_bars import _upsert_rows
        gold = _instrument("XAUUSD", "commodity")
        t = self.now - 3 * H
        _put(gold, t, "etoro", 4000)
        before = _whole(gold)
        for tag in ("yfinance_public", "binance_public"):
            self.assertEqual(
                _upsert_rows(gold, "1h", [_row(t, 4030)], tag), (0, 0), tag)
            self.assertEqual(_whole(gold), before, tag)
        held = []
        written, skipped = _upsert_rows(
            gold, "1h", [_row(t, 4030), _row(t + H, 4031)],
            "yfinance_public", held=held)
        self.assertEqual((written, skipped, held), (1, 0, [_ms(t)]))
        self.assertEqual(_whole(gold)[t], before[t])
        self.assertEqual(_series(gold)[t + H], ("yfinance_public", 4031.0))

    def test_a_public_row_still_rewrites_a_public_row_and_a_venue_still_wins(self):
        from market_data.bot_bars import _upsert_rows
        eur = _instrument("EURUSD", "forex")
        t = self.now - 2 * H
        _put(eur, t, "yfinance_public", 1.0)
        self.assertEqual(_upsert_rows(eur, "1h", [_row(t, 1.1),
                                                  _row(t + H, 1.2)],
                                      "yfinance_public"), (2, 0))
        self.assertEqual(_series(eur)[t], ("yfinance_public", 1.1))
        self.assertEqual(_series(eur)[t + H], ("yfinance_public", 1.2))
        self.assertEqual(_upsert_rows(eur, "1h", [_row(t, 1.15)],
                                      "binance_public"), (1, 0))
        self.assertEqual(_series(eur)[t], ("binance_public", 1.15))
        # The venue's own bars still replace a stand-in (the pass's window).
        self.assertEqual(_upsert_rows(eur, "1h", [_row(t, 1.05)], "etoro"),
                         (1, 0))
        self.assertEqual(_series(eur)[t], ("etoro", 1.05))

    def test_a_venue_bar_the_pass_writes_after_the_check_stays_the_venues(self):
        """eToro's gold went quiet four days ago (its newest bar is stale,
        so the backfill writes after it, the pass's rule). It answers again
        while the backfill runs: the bar pass writes eToro's last closed
        hour after the backfill read the span and before it wrote."""
        from market_data import bot_bars
        gold = _instrument("XAUUSD", "commodity")
        quiet = self.now - 96 * H
        for h in range(0, 6):
            _put(gold, quiet - h * H, "etoro", 4000 + h)
        landed = self.now - H
        rows = [_row(quiet + k * H, 4030 + k) for k in range(-2, 97)]
        upsert, done = _the_pass_lands_first(_row(landed, 4011), gold)
        with patch.object(bot_bars, "_upsert_rows", side_effect=upsert):
            out, _err = _run(YFinanceFeed({"XAUUSD": rows}), "--symbols",
                             "XAUUSD", "--intervals", "1h", "--bars", "9000")
        self.assertEqual(done, [(1, 0)], "the pass wrote eToro's bar first")
        self.assertEqual(_series(gold)[landed], ("etoro", 4011.0),
                         "the venue's bar was replaced")
        self.assertEqual(_series(gold)[self.now], ("yfinance_public",
                                                   4126.0))
        self.assertIn("XAUUSD 1h: 4 public bar(s) skipped for the venue", out)
        self.assertIn("(4 at its own timestamps, 1 of them written by the "
                      "venue during this run, 0 beside its bars, 0 after its "
                      "newest bar)", out)
        self.assertIn("XAUUSD     1h      99 bars fetched (public feed), 95 "
                      "written", out)

    def test_the_binance_path_keeps_a_venue_bar_written_between_pages(self):
        from bot_program.engine.binance_client import BinanceClient
        from market_data.bot_bars import STALE_VENUE_BARS_CRYPTO, _upsert_rows
        btc = _instrument("BTCUSD", "crypto")
        for h in range(10, 16):            # quiet for ten hours: stale
            _put(btc, self.now - h * H, "etoro", 60000 + h)
        self.assertGreater(10, STALE_VENUE_BARS_CRYPTO)
        landed = self.now - H
        page1 = [_row(self.now - h * H, 60100 + h) for h in range(30, 10, -1)]
        page2 = [_row(self.now - h * H, 60100 + h) for h in range(10, -1, -1)]
        asked = []

        def pages(*_a, **_kw):
            asked.append(1)
            if len(asked) == 2:            # the pass, between two pages
                _upsert_rows(btc, "1h", [_row(landed, 60001)], "etoro")
            return [page1, page2, []][len(asked) - 1]
        out, err = StringIO(), StringIO()
        with patch.object(BinanceClient, "klines", side_effect=pages), \
                patch("market_data.management.commands.backfill_bars"
                      ".SLEEP_BETWEEN_PAGES", 0):
            call_command("backfill_bars", "--symbols", "BTCUSD",
                         "--intervals", "1h", "--bars", "40", stdout=out,
                         stderr=err)
        got = _series(btc)
        self.assertEqual(got[landed], ("etoro", 60001.0))
        for h in range(10, 16):
            self.assertEqual(got[self.now - h * H], ("etoro", 60000.0 + h))
        for ts in (self.now - 30 * H, self.now - 16 * H, self.now - 9 * H,
                   self.now):
            self.assertEqual(got[ts][0], "binance_public", ts)
        self.assertIn("BTCUSD 1h: 7 public bar(s) skipped for the venue",
                      out.getvalue())
        self.assertIn("1 of them written by the venue during this run",
                      out.getvalue())


class TheYahooEodIsThePublicFeedTests(TestCase):
    """THE YAHOO EOD'S DAILY BARS ARE THE PUBLIC FEED'S (2026-11-01). The
    nightly EOD (market_data/adapters/yfinance_adapter) stores Yahoo's
    daily series as "yfinance": the very series backfill_bars writes as
    "yfinance_public", at the same timestamps, and no venue writes a 1d
    bar. Counted as a venue's, it froze a 1d backfill out of the EOD's
    span: a hole the EOD left (it re-reads five days) stayed a hole, a
    daily bar it stored mid-session stayed partial, and the run named
    Yahoo "the venue". Alpha Vantage's "alpha_vantage" daily bars are a
    public feed's too."""

    def test_a_1d_backfill_fills_a_hole_and_rewrites_a_partial_bar(self):
        spx = _instrument("SPX500", "index")
        day0 = _hour().replace(hour=4) - 12 * D
        for k in (0, 1, 5, 6, 7):          # days 2 to 4: the EOD was off
            # day 1 stored mid-session: a partial close
            _put(spx, day0 + k * D, "yfinance", 5050 if k == 1 else 5100 + k,
                 "1d")
        rows = [_row(day0 + k * D, 5100 + k) for k in range(-3, 9)]
        out, _err = _run(YFinanceFeed({"SPX500": rows}), "--symbols",
                         "SPX500", "--intervals", "1d", "--bars", "1600")
        got = _series(spx, "1d")
        self.assertEqual(len(got), 12)
        for k in range(-3, 9):
            self.assertEqual(got[day0 + k * D], ("yfinance_public",
                                                 5100.0 + k), k)
        self.assertIn("12 bars fetched (public feed), 12 written", out)
        self.assertNotIn("skipped for the venue", out)
        self.assertNotIn("skipped for a venue's bars", out)

    def test_the_shared_test_reads_the_daily_writers_as_public_feeds(self):
        from market_data.bot_bars import (_after_the_venues_last_bar,
                                          _upsert_rows, _venue_rows,
                                          _venue_span)
        gold = _instrument("XAUUSD", "commodity")
        day = _hour().replace(hour=4) - 3 * D
        _put(gold, day, "yfinance", 4000, "1d")
        _put(gold, day + D, "alpha_vantage", 4001, "1d")
        self.assertEqual(list(_venue_rows(gold, "1d")), [])
        self.assertIsNone(_venue_span(gold, "1d"))
        rows = [_row(day, 4030), _row(day + D, 4031)]
        self.assertEqual(_after_the_venues_last_bar(gold, "1d", rows), rows)
        # The writer reads them the same: the public feed rewrites them.
        self.assertEqual(_upsert_rows(gold, "1d", rows, "yfinance_public"),
                         (2, 0))
        self.assertEqual(_series(gold, "1d"),
                         {day: ("yfinance_public", 4030.0),
                          day + D: ("yfinance_public", 4031.0)})
        # A venue's own tag is still a venue's.
        _put(gold, day, "etoro", 4002, "1h")
        self.assertEqual(_venue_span(gold, "1h")["sources"], ["etoro"])


class APublicOnlySeriesIsUnchangedTests(TestCase):

    def test_every_row_is_written_and_a_public_row_is_rewritten_as_before(self):
        eur = _instrument("EURUSD", "forex")
        now = _hour()
        _put(eur, now - 2 * H, "yfinance_public", 1.0)
        rows = [_row(now - h * H, 1.10 + h / 100) for h in range(3, -1, -1)]
        out, _err = _run(YFinanceFeed({"EURUSD": rows}), "--symbols",
                         "EURUSD", "--intervals", "1h", "--bars", "600")
        got = _series(eur)
        self.assertEqual(len(got), 4)
        self.assertEqual({src for src, _c in got.values()},
                         {"yfinance_public"})
        self.assertAlmostEqual(got[now - 2 * H][1], 1.12)
        self.assertIn("EURUSD     1h       4 bars fetched (public feed), 4 "
                      "written", out)
        self.assertNotIn("skipped for the venue", out)
        self.assertNotIn("skipped for a venue's bars", out)


class CryptoThroughBinanceTests(TestCase):

    def test_binance_rows_keep_out_of_the_venues_span_the_same(self):
        from bot_program.engine.binance_client import BinanceClient
        btc = _instrument("BTCUSD", "crypto")
        now = _hour()
        for h in range(1, 7):
            _put(btc, now - h * H, "etoro", 60000 + h)
        before = _whole(btc)
        rows = [_row(now - h * H, 60100 + h) for h in range(8, -1, -1)]
        out, err = StringIO(), StringIO()
        with patch.object(BinanceClient, "klines",
                          side_effect=[rows, []]) as klines, \
                patch("market_data.management.commands.backfill_bars"
                      ".SLEEP_BETWEEN_PAGES", 0), \
                patch("market_data.public_feed.public_feed_for") as pf:
            call_command("backfill_bars", "--symbols", "BTCUSD",
                         "--intervals", "1h", "--bars", "10", stdout=out,
                         stderr=err)
        pf.assert_not_called()
        self.assertEqual(klines.call_args.args[0], "BTCUSDT")
        got = _whole(btc)
        for ts, kept in before.items():
            self.assertEqual(got[ts], kept, f"eToro's {ts:%H:%M} candle")
        series = _series(btc)
        for ts in (now - 8 * H, now - 7 * H):
            self.assertEqual(series[ts][0], "binance_public", ts)
        # eToro's newest bar is an hour old, live by the crypto bound
        # (STALE_VENUE_BARS_CRYPTO bars): the forming hour is the pass's.
        self.assertNotIn(now, series)
        self.assertEqual(len(series), 8)
        self.assertIn("BTCUSD 1h: 7 public bar(s) skipped for the venue",
                      out.getvalue())
        self.assertIn("(6 at its own timestamps, 0 beside its bars, 1 after "
                      "its newest bar); " + WHY.format("3 bars"),
                      out.getvalue())


class TheKeylessConfigNeverWritesOverTheVenueTests(TestCase):
    """The bar pass's own keyless branch: a config whose client IS the
    public feed (no venue for that class this pass: credentials unread,
    the class's venue switched off) wrote its whole window as it came,
    over the bars a venue had written for that symbol."""

    def setUp(self):
        from django.core.cache import cache
        cache.clear()

    def test_it_writes_only_after_the_venues_last_bar(self):
        from market_data.bot_bars import refresh_bars_for_config
        user = User.objects.create_user("keyless_u", password="x")
        gold = _instrument("XAUUSD", "commodity")
        cfg = _cfg(user, "commodity", ["XAUUSD"])
        now = _hour()
        for h in range(1, 7):
            _put(gold, now - h * H, "etoro", 4000 + h)
        before = _whole(gold)
        feed = YFinanceFeed({"XAUUSD": [_row(now - h * H, 4030 + h)
                                        for h in range(6, -1, -1)]})
        with patch("market_data.bot_bars._client_for", return_value=feed), \
                patch("market_data.bot_bars._pace"):
            out = refresh_bars_for_config(cfg, intervals=("1h",), limit=7)
        got = _whole(gold)
        for ts, kept in before.items():
            self.assertEqual(got[ts], kept, f"eToro's {ts:%H:%M} candle")
        self.assertEqual(_series(gold)[now], ("yfinance_public", 4030.0))
        self.assertEqual(out["bars"], 1)


class TheProvingFooterTests(TestCase):

    def setUp(self):
        user = User.objects.create_user("footer_u", password="x")
        _instrument("EURUSD", "forex")
        _cfg(user, "forex", ["EURUSD"])
        now = _hour()
        self.feed = YFinanceFeed({"EURUSD": [_row(now - h * H, 1.1)
                                             for h in range(3, 0, -1)]})

    def test_the_minimums_are_the_interval_backfilled(self):
        from backtester.proving.data import MIN_BARS, MIN_SPAN_DAYS
        self.assertEqual((MIN_SPAN_DAYS["1h"], MIN_BARS["1h"]), (365, 2000))
        self.assertEqual((MIN_SPAN_DAYS["4h"], MIN_BARS["4h"]), (540, 800))
        for dry in ((), ("--dry-run",)):
            out, _err = _run(self.feed, "--proving", "--intervals", "1h",
                             "--bars", "9000", *dry)
            self.assertIn("The proving ground needs 365 days and 2000 bars "
                          "at 1h per symbol.", out, dry)
            self.assertIn("`python manage.py prove data --timeframe 1h` "
                          "(read only) says who is still short.", out, dry)
            self.assertNotIn("540 days", out, dry)
            self.assertNotIn("800 bars", out, dry)
        out, _err = _run(self.feed, "--proving", "--dry-run")
        self.assertIn("The proving ground needs 540 days and 800 bars at 4h "
                      "per symbol.", out)
        self.assertNotIn("2000 bars", out)
        out, _err = _run(self.feed, "--proving", "--intervals", "1h,4h",
                         "--dry-run")
        self.assertIn("365 days and 2000 bars at 1h", out)
        self.assertIn("540 days and 800 bars at 4h", out)

    def test_an_interval_the_judge_never_reads_is_said_so(self):
        out, _err = _run(self.feed, "--proving", "--intervals", "15m",
                         "--dry-run")
        self.assertIn("The proving ground judges no 15m bars", out)
        self.assertNotIn("540 days", out)

    def test_no_step_that_sizes_real_money_is_invited(self):
        for dry in ((), ("--dry-run",)):
            out, _err = _run(self.feed, "--proving", "--intervals", "1h",
                             *dry)
            footer = out[out.index("The proving ground needs"):]
            for line in footer.splitlines():
                if "Next" in line:
                    self.assertNotIn("prove", line, dry)
                    self.assertNotIn("component", line, dry)
            self.assertIn("The nightly judge (03:40 UTC) runs on its own "
                          "while the proving_ground component is on", footer)
            self.assertIn("`python manage.py prove rules --save` changes "
                          "real-money sizing", footer)
            self.assertIn("It is the operator's decision, never a routine "
                          "next step", footer)


class TheDryRunSaysItDownloadsTests(TestCase):

    def test_the_help_says_the_dry_run_downloads_everything(self):
        from market_data.management.commands.backfill_bars import Command
        parser = Command().create_parser("manage.py", "backfill_bars")
        dry = next(a for a in parser._actions if a.dest == "dry_run")
        self.assertIn("write nothing", dry.help)
        self.assertIn("downloads everything", dry.help)
