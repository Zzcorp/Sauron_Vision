"""The chart's live tick only touches a candle it belongs to (2026-10-31).

Every 15 seconds sv-instrument-live.js handed the chart the platform quote
(LiveQuote.last, whichever feed won the row last) and `tick` welded it onto
the last candle: close = price, high = max, low = min. Nothing asked
whether the quote and the candle were the same feed, the same instrument,
the same bar, or whether the quote was fresh. On a gold chart drawn from
eToro's candles the Yahoo future's price grew a wick every 15 seconds that
the 60-second refresh took away again: the operator's "spikes up or down
for no reason".

Now the tick welds only when:
  * the quote's feed is the candles' feed, or neither is a stand-in (the
    same instrument from two feeds) and the candles are not crypto, whose
    candles take their own feed's quote alone (Binance's BTCUSDT is
    another exchange's, in USDT);
  * the last candle is the forming one (an intraday bar whose period has
    not ended; a daily bar the server built as today's forming candle);
  * the quote is fresh (STALE_S) and was taken inside that bar;
  * the move from the candle's close is within the class's jump bar
    (bot_program.mark_sanity.bar_for);
and the welded candle is rebuilt from the bar the server served, so a
failed background refresh puts that bar back (skeptic M5) instead of
leaving a wick that grows with every quote. Otherwise nothing is drawn and
the caption under the chart says why, in words, until a new series or a
chart type that takes no tick clears it. A suspect bar is drawn hollow on
Heikin-Ashi too, from its body (2026-10-31).

The widget's real script runs under node against the fake chart of
tests.test_chart_signal_markers.

Run with:  python manage.py test tests.test_chart_one_price_widget
"""
import unittest

from django.test import SimpleTestCase

from tests.test_chart_signal_markers import (NODE, WIDGET_PRELUDE, _blocks,
                                             _node, widget)

SCENARIO_HEAD = r"""
log.updates = [];
log.candleOpts = null;
chart.addCandlestickSeries = function (o) { log.candleOpts = o || null; return this.add('candle'); };
Series.prototype.update = function (b) {
    if (this.kind !== 'hist') log.updates.push(JSON.parse(JSON.stringify(b)));
};
const srcEl = new El(ID + '-src');
els[ID + '-src'] = srcEl;
const roles = {};
srcEl.querySelector = function (sel) {
    const m = /data-role="(\w+)"/.exec(sel);
    if (!m) return null;
    return roles[m[1]] || (roles[m[1]] = new El('role-' + m[1]));
};
const nowS = Math.floor(Date.now() / 1000);
const role = function (n) { return roles[n] ? { text: roles[n].textContent, hidden: roles[n].hidden } : null; };
const lastUpdate = function () { return log.updates[log.updates.length - 1] || null; };
const SRC = { family: 'etoro', label: 'eToro', words: "eToro's own candles",
              stand_in: '', route: 'etoro', tick_bar: 0.02, notes: [],
              positions: '' };
"""

INTRADAY = SCENARIO_HEAD + r"""
(async function () {
    const hourS = nowS - nowS % 3600;
    const bars = [];
    for (let i = 5; i >= 0; i--) {
        const c = 4003 - i;
        bars.push({ time: hourS - i * 3600, open: c - 0.5, high: c + 1,
                    low: c - 1, close: c, volume: 0 });
    }
    bars[2].low = 0;   /* stored before the writer refused such bars */
    bars[2].suspect = 'suspect bar from eToro: its low is at or under zero';
    PAYLOAD = { symbol: 'XAUUSD', timeframe: '1h', bars: bars, source: SRC,
                positions: [], signals: [] };
    vm.runInContext(M.pure, sandbox, { filename: 'pure.js' });
    vm.runInContext(M.main, sandbox, { filename: 'widget.js' });
    for (let i = 0; i < 6; i++) await flush();
    const api = sandbox.svCharts[ID];
    const R = {};
    R.caption = { feed: role('feed'), hidden: srcEl.hidden };
    const rows = candle().rows;
    R.hollow = rows[2];
    R.solid = rows[3];
    move(100, 100, bars[2].time);
    R.legendSuspect = legendEl.innerHTML;
    /* The price scale, as the library would build it from every bar (the
       zero wick included), and as the series' provider answers it. */
    const prov = log.candleOpts && log.candleOpts.autoscaleInfoProvider;
    R.autoscale = prov ? prov(function () {
        return { priceRange: { minValue: 0, maxValue: 4004 }, margins: { above: 0.1, below: 0.1 } };
    }) : null;

    const fresh = { source_family: 'etoro', stand_in: '', quote_age_seconds: 5,
                    source_words: 'eToro (synced)' };
    api.tick(4003.5, fresh);
    R.same = { n: log.updates.length, last: lastUpdate(), tick: role('tick') };
    api.tick(4004.6, fresh);
    R.grown = lastUpdate();
    api.tick(4003.2, fresh);
    R.kept = lastUpdate();

    const before = log.updates.length;
    api.tick(4036.4, { source_family: 'yahoo', stand_in: 'future', quote_age_seconds: 5,
                       source_words: 'Yahoo GC=F, the front-month future' });
    R.other = { n: log.updates.length - before, tick: role('tick') };

    api.tick(4003.4, { source_family: 'oanda', stand_in: '', quote_age_seconds: 3,
                       source_words: 'OANDA stream' });
    R.sameInstrument = { n: log.updates.length - before, last: lastUpdate(), tick: role('tick') };

    let n0 = log.updates.length;
    api.tick(4003.3, { source_family: 'etoro', stand_in: '', quote_age_seconds: 1200,
                       source_words: 'eToro (synced)' });
    R.stale = { n: log.updates.length - n0, tick: role('tick') };

    n0 = log.updates.length;
    api.tick(4003 * 1.05, fresh);
    R.jump = { n: log.updates.length - n0, tick: role('tick') };

    n0 = log.updates.length;
    api.tick(4003.1, null);
    R.unknown = { n: log.updates.length - n0 };

    /* A background refresh that fails puts the served bar back. */
    api.tick(4006.0, fresh);
    R.beforeFail = lastUpdate();
    sandbox.fetch = function () { return Promise.reject(new Error('down')); };
    api.refresh();
    for (let i = 0; i < 6; i++) await flush();
    R.afterFail = lastUpdate();
    api.tick(4003.6, fresh);
    R.afterFailTick = lastUpdate();

    /* A last candle whose hour has ended takes no tick. */
    sandbox.fetch = fetchStub;
    const closed = JSON.parse(JSON.stringify(PAYLOAD));
    closed.bars = closed.bars.map(function (b) { return Object.assign({}, b, { time: b.time - 3 * 3600 }); });
    await refresh(closed);
    n0 = log.updates.length;
    api.tick(4003.5, fresh);
    R.closed = { n: log.updates.length - n0, tick: role('tick') };
    process.stdout.write(JSON.stringify(R));
})().catch(function (e) { process.stderr.write(String((e && e.stack) || e)); process.exit(1); });
"""

DAILY = SCENARIO_HEAD + r"""
(async function () {
    const day = function (k) { return new Date((nowS - k * 86400) * 1000).toISOString().slice(0, 10); };
    const bars = [3, 2, 1].map(function (k) {
        return { time: day(k), open: 250, high: 253, low: 249, close: 252, volume: 0 };
    });
    bars.push({ time: day(0), open: 255, high: 258, low: 254, close: 256, volume: 0,
                forming: true });
    const src = Object.assign({}, SRC, { family: 'yahoo', label: 'Yahoo AAPL',
                                         words: 'Yahoo AAPL', route: '', tick_bar: 0.03,
                                         notes: ["today's candle is forming from Yahoo AAPL hourly bars"],
                                         positions: 'Your position lines are eToro prices; these candles are Yahoo AAPL.' });
    PAYLOAD = { symbol: 'AAPL', timeframe: '1d', bars: bars, source: src,
                positions: [], signals: [] };
    vm.runInContext(M.pure, sandbox, { filename: 'pure.js' });
    vm.runInContext(M.main, sandbox, { filename: 'widget.js' });
    for (let i = 0; i < 6; i++) await flush();
    const api = sandbox.svCharts[ID];
    const R = {};
    R.caption = { feed: role('feed'), notes: role('notes'), positions: role('positions') };
    move(100, 100, day(0));
    R.legendForming = legendEl.innerHTML;
    const q = { source_family: 'yahoo', stand_in: '', quote_age_seconds: 20,
                source_words: 'Yahoo AAPL' };
    api.tick(256.5, q);
    R.forming = { n: log.updates.length, last: lastUpdate() };
    const settled = JSON.parse(JSON.stringify(PAYLOAD));
    settled.bars.pop();
    await refresh(settled);
    const n0 = log.updates.length;
    api.tick(256.6, q);
    R.settled = { n: log.updates.length - n0, tick: role('tick') };
    process.stdout.write(JSON.stringify(R));
})().catch(function (e) { process.stderr.write(String((e && e.stack) || e)); process.exit(1); });
"""


# The review of the first cut (2026-10-31): a Binance USDT quote welded
# onto eToro's crypto candles; the caption kept the reason it gave for the
# last series or chart type; Heikin-Ashi drew a suspect bar solid, its
# wick to zero setting the scale, under a legend that said "hollow".
REVIEW = SCENARIO_HEAD + r"""
(async function () {
    const hourS = nowS - nowS % 3600;
    const bars = [];
    for (let i = 5; i >= 0; i--) {
        const c = 4003 - i;
        bars.push({ time: hourS - i * 3600, open: c - 0.5, high: c + 1,
                    low: c - 1, close: c, volume: 0 });
    }
    bars[2].low = 0;
    bars[2].suspect = 'suspect bar from eToro: its low is at or under zero';
    const errDiv = new El('error-text');
    els[ID + '-error'].querySelector = function () { return errDiv; };
    const crypto = Object.assign({}, SRC, { same_feed_only: true, tick_bar: 0.03 });
    PAYLOAD = { symbol: 'BTCUSD', timeframe: '1h', bars: bars, source: crypto,
                positions: [], signals: [] };
    vm.runInContext(M.pure, sandbox, { filename: 'pure.js' });
    vm.runInContext(M.main, sandbox, { filename: 'widget.js' });
    for (let i = 0; i < 6; i++) await flush();
    const api = sandbox.svCharts[ID];
    const R = {};

    let n0 = log.updates.length;
    api.tick(4003.4, { source_family: 'binance', stand_in: '', quote_age_seconds: 3,
                       source_words: 'Binance stream' });
    R.binanceOnEtoro = { n: log.updates.length - n0, tick: role('tick') };
    n0 = log.updates.length;
    api.tick(4003.5, { source_family: 'etoro', stand_in: '', quote_age_seconds: 3,
                       source_words: 'eToro (synced)' });
    R.etoroOnEtoro = { n: log.updates.length - n0 };

    /* A refused tick's reason, then a new series adopted: the reason goes. */
    const first = PAYLOAD;
    const future = { source_family: 'yahoo', stand_in: 'future', quote_age_seconds: 3,
                     source_words: 'Yahoo GC=F, the front-month future' };
    api.tick(4036.4, future);
    R.beforeSwitch = role('tick');
    const yahoo = JSON.parse(JSON.stringify(first));
    yahoo.source = Object.assign({}, SRC, { family: 'oanda', label: 'OANDA',
                                            words: 'OANDA XAUUSD', route: '' });
    await refresh(yahoo);
    R.afterSwitch = role('tick');

    /* A reason left by candles, then a line chart whose load failed: the
       next tick (which a line chart never draws) clears it. */
    await refresh(first);
    api.tick(4036.4, future);
    R.beforeLine = role('tick');
    sandbox.fetch = function () { return Promise.reject(new Error('down')); };
    chartType('line');
    for (let i = 0; i < 6; i++) await flush();
    R.lineKept = role('tick');
    api.tick(4036.4, future);
    R.lineTick = role('tick');

    /* Heikin-Ashi: the suspect bar is drawn hollow from its body. */
    sandbox.fetch = fetchStub;
    chartType('heikin');
    for (let i = 0; i < 6; i++) await flush();
    const ha = candle().rows;
    R.ha = { n: ha.length, minLow: Math.min.apply(null, ha.map(function (r) { return r.low; })),
             suspect: ha[2], next: ha[3] };
    process.stdout.write(JSON.stringify(R));
})().catch(function (e) { process.stderr.write(String((e && e.stack) || e)); process.exit(1); });
"""

def _run(scenario, timeframe):
    pure, main = _blocks(widget(timeframe=timeframe, decimals=2))
    return _node(WIDGET_PRELUDE + scenario, {"pure": pure, "main": main,
                                             "payload": {"bars": []}})


@unittest.skipUnless(NODE, "node is not installed")
class TheTickOnAnIntradayChartTests(SimpleTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.r = _run(INTRADAY, "1h")

    def test_the_caption_names_the_candles_feed(self):
        self.assertIn("eToro's own candles", self.r["caption"]["feed"]["text"])
        self.assertFalse(self.r["caption"]["hidden"])

    def test_a_quote_of_the_candles_feed_is_welded(self):
        same = self.r["same"]
        self.assertEqual(same["n"], 1)
        self.assertEqual(same["last"]["close"], 4003.5)
        self.assertEqual(same["last"]["high"], 4004)       # the bar's own
        self.assertTrue(same["tick"]["hidden"] or not same["tick"]["text"])
        self.assertEqual(self.r["grown"]["high"], 4004.6)
        # The wick a print drew stays until the refresh, as on any chart:
        self.assertEqual(self.r["kept"]["high"], 4004.6)
        self.assertEqual(self.r["kept"]["close"], 4003.2)

    def test_another_feeds_stand_in_is_not_drawn_and_the_caption_says_so(self):
        other = self.r["other"]
        self.assertEqual(other["n"], 0)
        self.assertFalse(other["tick"]["hidden"])
        self.assertIn("Yahoo GC=F", other["tick"]["text"])
        self.assertIn("another feed", other["tick"]["text"])

    def test_the_same_instrument_from_another_feed_is_welded(self):
        s = self.r["sameInstrument"]
        self.assertEqual(s["n"], 1)
        self.assertEqual(s["last"]["close"], 4003.4)

    def test_a_stale_quote_is_not_drawn(self):
        self.assertEqual(self.r["stale"]["n"], 0)
        self.assertIn("old", self.r["stale"]["tick"]["text"])

    def test_a_move_past_the_class_bar_is_not_drawn(self):
        self.assertEqual(self.r["jump"]["n"], 0)
        self.assertIn("from the candle", self.r["jump"]["tick"]["text"])

    def test_a_quote_that_says_nothing_of_its_feed_is_not_drawn(self):
        self.assertEqual(self.r["unknown"]["n"], 0)

    def test_a_failed_refresh_puts_the_served_bar_back(self):
        self.assertEqual(self.r["beforeFail"]["high"], 4006.0)
        back = self.r["afterFail"]
        self.assertEqual((back["open"], back["high"], back["low"],
                          back["close"]), (4002.5, 4004, 4002, 4003))
        again = self.r["afterFailTick"]
        self.assertEqual(again["high"], 4004, "the old wick came back")
        self.assertEqual(again["close"], 4003.6)

    def test_a_closed_last_candle_takes_no_tick(self):
        self.assertEqual(self.r["closed"]["n"], 0)
        self.assertIn("closed", self.r["closed"]["tick"]["text"])

    def test_a_suspect_bar_does_not_squash_the_price_scale(self):
        """Drawn hollow, its wick to zero still set the autoscale, and the
        whole tape lay flat along the top of the pane. The scale is built
        from the other bars and the suspect bar's body; its wick runs off
        the pane, still drawn."""
        rng = self.r["autoscale"]["priceRange"]
        self.assertGreater(rng["minValue"], 3990)
        self.assertEqual(rng["maxValue"], 4004)
        self.assertEqual(self.r["autoscale"]["margins"],
                         {"above": 0.1, "below": 0.1})

    def test_a_suspect_bar_is_drawn_hollow_and_named(self):
        hollow, solid = self.r["hollow"], self.r["solid"]
        self.assertEqual(hollow["color"], "rgba(0,0,0,0)")
        self.assertTrue(hollow.get("borderColor"))
        self.assertTrue(hollow.get("wickColor"))
        self.assertNotIn("color", solid)
        self.assertIn("suspect bar from eToro", self.r["legendSuspect"])


@unittest.skipUnless(NODE, "node is not installed")
class TheTickOnADailyChartTests(SimpleTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.r = _run(DAILY, "1d")

    def test_todays_forming_candle_takes_the_tick(self):
        f = self.r["forming"]
        self.assertEqual(f["n"], 1)
        self.assertEqual(f["last"]["close"], 256.5)

    def test_a_settled_session_takes_none(self):
        self.assertEqual(self.r["settled"]["n"], 0)
        self.assertIn("closed", self.r["settled"]["tick"]["text"])

    def test_the_caption_carries_the_notes_and_the_position_lines(self):
        cap = self.r["caption"]
        self.assertIn("forming", cap["notes"]["text"])
        self.assertIn("eToro prices", cap["positions"]["text"])
        self.assertFalse(cap["positions"]["hidden"])

    def test_the_crosshair_says_forming(self):
        self.assertIn("forming", self.r["legendForming"].lower())


@unittest.skipUnless(NODE, "node is not installed")
class TheReviewOfTheFirstCutTests(SimpleTestCase):
    """(2026-10-31) What the first cut of the tick and the caption left
    wrong."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.r = _run(REVIEW, "1h")

    def test_binance_usdt_is_not_welded_on_etoros_crypto_candles(self):
        """Another exchange, quoted in USDT: not the instrument of eToro's
        BTC candles, and well inside crypto's 3% bar, so nothing else
        caught it."""
        b = self.r["binanceOnEtoro"]
        self.assertEqual(b["n"], 0)
        self.assertIn("another feed", b["tick"]["text"])
        self.assertEqual(self.r["etoroOnEtoro"]["n"], 1,
                         "the candles' own feed is still welded")

    def test_a_new_series_clears_the_last_reason(self):
        self.assertIn("another feed", self.r["beforeSwitch"]["text"])
        after = self.r["afterSwitch"]
        self.assertTrue(after["hidden"] and not after["text"], after)

    def test_a_chart_that_takes_no_tick_clears_the_reason(self):
        self.assertIn("another feed", self.r["beforeLine"]["text"])
        line = self.r["lineTick"]
        self.assertTrue(line["hidden"] and not line["text"], line)

    def test_heikin_ashi_draws_a_suspect_bar_hollow_from_its_body(self):
        ha = self.r["ha"]
        self.assertEqual(ha["n"], 6)
        self.assertGreater(ha["minLow"], 3990,
                           "the suspect bar's wick to zero set the HA scale")
        self.assertEqual(ha["suspect"]["color"], "rgba(0,0,0,0)")
        self.assertNotIn("color", ha["next"])
