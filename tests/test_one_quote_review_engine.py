"""ONE PRICE EVERYWHERE: the review's fixes in the browser's painter, under
node (2026-11-12).

static/js/sv-venue.js, with no page (the sandbox of
tests/test_one_quote_engine). Measured by the consistency review
(scratchpad onequote/review_consistency.md):

  * a 15 s poll that read the database before a stream's write replaced
    the stream's newer 151.260 "live" with the older 151.234 "46 s",
    because a live/delayed difference counted as a server "switch": a
    value of the same source is now ordered by its time, a close (same
    time, shut) by the render's;
  * a stream's tick moved the price and kept the old day change beside
    it: the stream's own change now moves with it;
  * the DAX40 caption called its own stand-in bars "another instrument"
    beside the same stand-in price: only bars of another feed say so;
  * on a chart of the price's own feed, the forming candle trailed the
    "now" line until the next 15 s poll: every paint hands the price to
    the chart's own weld (its guards decide);
  * a returning quote socket asks for the regions again, also when its
    first open came before the deferred painter existed.

Run with:  python manage.py test tests.test_one_quote_review_engine
"""
import unittest

from django.test import SimpleTestCase

from tests.test_one_quote_engine import ENGINE, NODE, _node

PROGRAM = r"""
const R = {};
const t0 = M.t0;
/* The page's clock is the server's (data-sv-now): a tick of t0 + 1 s is
   fresh, "live" within the stream's 15 s. */
V.ingestBlock({ t: t0, q: {} });
const U = { s: 'USDJPY', p: '151.234', v: 151.234, l: '151.234', b: '151.229', a: '151.239',
            side: '', src: 'oanda_stream', fam: 'oanda', who: 'OANDA stream', auth: 'reference',
            basis: 'quote', at: t0 - 25000, state: 'delayed', dp: 3, cls: 'forex', chg: null,
            ls: 15, shut: null, sf: null, slot: null, via: '' };
V.ingest(U, t0);
V.tick({ type: 'quote_stream', data: { symbol: 'USD_JPY', last: 151.260, bid: 151.255, ask: 151.265,
                                        source: 'oanda_stream', ts: new Date(t0 + 1000).toISOString() } });
R.tick = V.get('USDJPY').p;
/* The poll rendered after the tick, from a read before the stream wrote. */
V.ingest(clone(U), t0 + 5000);
R.latePoll = V.get('USDJPY').p;
/* A newer server value of the same source is the price. */
V.ingest(Object.assign(clone(U), { p: '151.300', v: 151.3, l: '151.300', at: t0 + 3000,
                                   state: 'live' }), t0 + 6000);
R.newer = V.get('USDJPY').p;
/* The close: the same reading, now shut, rendered later. */
V.ingest(Object.assign(clone(U), { p: '151.300', v: 151.3, l: '151.300', at: t0 + 3000,
                                   state: 'shut', shut: { since: t0, label: 'market shut',
                                                          opens: 'opens Sun 22:00 UTC' } }), t0 + 9000);
R.shut = V.get('USDJPY').state;
/* The source changes (a Yahoo row after the stream stopped): the server
   decides, by its render time, whatever the times say. */
V.ingest(Object.assign(clone(U), { p: '151.100', v: 151.1, l: '151.100', at: t0 - 90000,
                                   src: 'yfinance', fam: 'yahoo', who: 'Yahoo USDJPY=X',
                                   ls: null, b: null, a: null }), t0 + 12000);
R.switched = [V.get('USDJPY').src, V.get('USDJPY').p];

/* A stream's tick carries its own day change. */
const B = { s: 'BTCUSD', p: '90120.50', v: 90120.5, l: '90120.50', b: null, a: null, side: '',
            src: 'binance_ws', fam: 'binance', who: 'Binance stream', auth: 'reference',
            basis: 'quote', at: t0 - 2000, state: 'live', dp: 2, cls: 'crypto', chg: 1.5,
            ls: 15, shut: null, sf: null, slot: null, via: '' };
V.ingest(B, t0);
V.tick({ type: 'quote_stream', data: { symbol: 'BTCUSDT', last: 90150, change_pct: 1.62,
                                        bid: 90149, ask: 90151, volume: 1, source: 'binance_ws',
                                        ts: new Date(t0 + 500).toISOString() } });
R.chg = [V.get('BTCUSD').p, V.get('BTCUSD').chg];

/* Charts. */
function chartOf(sym, src, bars) {
  const h = { symbol: sym, ticks: [], cap: { textContent: '', hidden: true } };
  const series = { createPriceLine: function (o) { return { o: o, applyOptions: function (x) { Object.assign(this.o, x); } }; },
                   removePriceLine: function () {} };
  h.series = function () { return series; };
  h.bars = function () { return bars; };
  h.source = function () { return src; };
  h.caption = function () { return h.cap; };
  h.setNow = function () {};
  h.tick = function (price, q) { h.ticks.push([price, q]); };
  return h;
}
/* A stand-in price on its own stand-in bars: one feed, one instrument. */
V.ingest({ s: 'DAX40', p: '19210.50', v: 19210.5, l: '19210.50', b: null, a: null, side: '',
           src: 'yfinance', fam: 'yahoo', who: 'Yahoo ^GDAXI, the cash index', auth: 'reference',
           basis: 'quote', at: t0 - 60000, state: 'delayed', dp: 2, cls: 'index', chg: null,
           ls: null, shut: null, sf: null, slot: null, via: '' }, t0);
const dax = chartOf('DAX40', { family: 'yahoo', stand_in: 'cash index', label: 'Yahoo ^GDAXI',
                               what: 'Yahoo ^GDAXI, the cash index', close_side: 'last' },
                    [{ time: 1, close: 19190.0 }]);
V.chart(dax);
R.daxCaption = dax.cap.textContent;
/* A held eToro price on Yahoo's future: another feed and instrument. */
V.ingest({ s: 'XAUUSD', p: '2648.30', v: 2648.3, l: '2648.55', b: '2648.30', a: '2648.80',
           side: 'bid', src: 'etoro', fam: 'etoro', who: 'eToro', auth: 'etoro',
           basis: 'stamp:tick', at: t0 - 40000, state: 'delayed', dp: 2, cls: 'commodity',
           chg: null, ls: null, shut: null, sf: null, slot: null, via: 'tick' }, t0);
const gold = chartOf('XAUUSD', { family: 'yahoo', stand_in: 'future', label: 'Yahoo GC=F',
                                 what: 'Yahoo GC=F, the front-month future', close_side: 'last' },
                     [{ time: 1, close: 2671.3 }]);
V.chart(gold);
R.goldCaption = gold.cap.textContent;
R.goldTicks = gold.ticks.map(function (t) { return [t[0], t[1].source_family, t[1].side]; });
/* The forming candle of the price's own feed follows every paint. */
const btc = chartOf('BTCUSD', { family: 'binance', stand_in: '', label: 'Binance BTCUSDT',
                                what: 'Binance BTCUSDT', close_side: 'last' },
                    [{ time: 1, close: 90099.8 }]);
V.chart(btc);
V.tick({ type: 'quote_stream', data: { symbol: 'BTCUSDT', last: 90210, change_pct: 1.7,
                                        source: 'binance_ws', ts: new Date(t0 + 900).toISOString() } });
V.flush();
R.btcTicks = btc.ticks.map(function (t) {
  return [t[0], t[1].source_family, t[1].side, typeof t[1].quote_age_seconds, t[1].source_words];
});

/* The quote socket. base.html connects while the page is still parsing
   and this script is deferred, so a socket's first open can come before
   the painter exists: the first the painter hears of it is its fall, and
   its return must still ask for the regions (the lost pushes). */
let asked = 0;
sandbox.svLiveRefresh = function () { asked++; };
V.socket(false);
V.socket(true);
R.askedAfterAnUnseenOpen = asked;
V.socket(true);
R.askedAgain = asked;
process.stdout.write(JSON.stringify(R));
"""


@unittest.skipUnless(NODE, "node is not installed")
class TheReviewsEngineFixesTests(SimpleTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.r = _node(PROGRAM, {"engine": ENGINE.read_text(encoding="utf-8"),
                                "t0": 1794510836000})

    def test_a_late_poll_never_replaces_a_newer_tick(self):
        self.assertEqual(self.r["tick"], "151.260")
        self.assertEqual(self.r["latePoll"], "151.260")
        self.assertEqual(self.r["newer"], "151.300")

    def test_the_close_and_a_source_switch_are_the_servers(self):
        self.assertEqual(self.r["shut"], "shut")
        self.assertEqual(self.r["switched"], ["yfinance", "151.100"])

    def test_a_streams_tick_moves_its_own_day_change(self):
        self.assertEqual(self.r["chg"], ["90150.00", 1.62])

    def test_a_stand_in_on_its_own_bars_is_one_instrument(self):
        self.assertTrue(self.r["daxCaption"].startswith("now: "),
                        self.r["daxCaption"])
        self.assertNotIn("another instrument", self.r["daxCaption"])
        self.assertTrue(self.r["goldCaption"].startswith(
            "bars: Yahoo GC=F, the front-month future (another instrument) · "
            "price: eToro bid"), self.r["goldCaption"])

    def test_every_paint_hands_the_price_to_the_charts_weld(self):
        ticks = self.r["btcTicks"]
        self.assertTrue(ticks, "the chart's tick was never called")
        self.assertEqual(ticks[-1][:3], [90210, "binance", "last"])
        self.assertEqual(ticks[-1][3], "number")
        self.assertEqual(ticks[-1][4], "Binance stream")
        # an eToro price goes to the weld as what it is: the widget's
        # guards refuse it on another feed's candles
        self.assertEqual(self.r["goldTicks"][-1], [2648.3, "etoro", "bid"])

    def test_a_socket_opened_before_the_painter_still_resyncs(self):
        """Its first open was never seen; its fall and return ask for the
        regions once, and an open that follows an open asks nothing."""
        self.assertEqual(self.r["askedAfterAnUnseenOpen"], 1)
        self.assertEqual(self.r["askedAgain"], 1)
