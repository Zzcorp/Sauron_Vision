"""The chart's new divisions in the widget (2026-11-01).

10 min, 30 min and 2h are intraday frames: their forming bar is the one
whose period has not ended, by the frame's seconds, and the live tick welds
onto it under C1's guards (the same feed, fresh, taken inside the bar,
within the class's jump bar); a bar whose period has ended takes none, and
the bar-close countdown runs. The weekly candle is a daily-family frame,
handled the way 1d is: the server marks this week's candle forming, the
tick welds only onto it, and only while it holds today's forming day (the
server's `no_tick` says why not, and the caption says it), and no
countdown runs. A weekly bar holds a week:
a position opened on Wednesday sits on this week's candle, where a daily
bar's single day left it off the chart.

The widget's real script runs under node against the fake chart of
tests.test_chart_signal_markers, with C1's scenario head.

Run with:  python manage.py test tests.test_chart_divisions_widget
"""
import unittest

from django.test import SimpleTestCase

from tests.test_chart_one_price_widget import SCENARIO_HEAD
from tests.test_chart_signal_markers import (NODE, WIDGET_PRELUDE, _blocks,
                                             _node, widget)

FINE = SCENARIO_HEAD + r"""
(async function () {
    const span = M.span;
    /* the forming bar opened 90 s ago: forming for the rest of its period */
    const open = nowS - 90;
    const bars = [];
    for (let i = 5; i >= 0; i--) {
        const c = 4003 - i;
        bars.push({ time: open - i * span, open: c - 0.5, high: c + 1,
                    low: c - 1, close: c, volume: 0 });
    }
    PAYLOAD = { symbol: 'XAUUSD', timeframe: M.tf, bars: bars, source: SRC,
                positions: [], signals: [] };
    vm.runInContext(M.pure, sandbox, { filename: 'pure.js' });
    vm.runInContext(M.main, sandbox, { filename: 'widget.js' });
    for (let i = 0; i < 6; i++) await flush();
    const api = sandbox.svCharts[ID];
    const R = {};
    const fresh = { source_family: 'etoro', stand_in: '', quote_age_seconds: 5,
                    source_words: 'eToro (synced)' };
    api.tick(4003.5, fresh);
    R.forming = { n: log.updates.length, last: lastUpdate(), tick: role('tick') };

    let n0 = log.updates.length;
    api.tick(4003.6, Object.assign({}, fresh, { quote_age_seconds: 120 }));
    R.before = { n: log.updates.length - n0, tick: role('tick') };

    n0 = log.updates.length;
    api.tick(4003 * 1.05, fresh);
    R.jump = { n: log.updates.length - n0, tick: role('tick') };

    n0 = log.updates.length;
    api.tick(4036.4, { source_family: 'yahoo', stand_in: 'future', quote_age_seconds: 5,
                       source_words: 'Yahoo GC=F, the front-month future' });
    R.other = { n: log.updates.length - n0, tick: role('tick') };

    R.countdown = els[ID + '-countdown'].textContent;

    /* the same bars a period older: the last one has closed */
    const closed = JSON.parse(JSON.stringify(PAYLOAD));
    closed.bars = closed.bars.map(function (b) { return Object.assign({}, b, { time: b.time - span }); });
    await refresh(closed);
    n0 = log.updates.length;
    api.tick(4003.5, fresh);
    R.closed = { n: log.updates.length - n0, tick: role('tick') };
    process.stdout.write(JSON.stringify(R));
})().catch(function (e) { process.stderr.write(String((e && e.stack) || e)); process.exit(1); });
"""

WEEKLY = SCENARIO_HEAD + r"""
(async function () {
    const DAY = 86400;
    const today = nowS - nowS % DAY;
    const monday = today - ((new Date(today * 1000).getUTCDay() + 6) % 7) * DAY;
    const iso = function (s) { return new Date(s * 1000).toISOString().slice(0, 10); };
    const bars = [3, 2, 1].map(function (k) {
        return { time: iso(monday - k * 7 * DAY), open: 250, high: 260, low: 245,
                 close: 255, volume: 0 };
    });
    bars.push({ time: iso(monday), open: 255, high: 258, low: 254, close: 256,
                volume: 0, forming: true });
    const src = Object.assign({}, SRC, { family: 'yahoo', label: 'Yahoo AAPL',
                                         words: 'Yahoo AAPL', route: '', tick_bar: 0.03,
                                         notes: ["this week's candle is forming"] });
    /* opened on this week's Wednesday, and on the Thursday of last week */
    const positions = [
        { id: 1, source: 'real', side: 'long', entry: 256, qty: 1, label: 'this week',
          opened_at: monday + 2 * DAY + 3600 },
        { id: 2, source: 'real', side: 'short', entry: 257, qty: 1, label: 'last week',
          opened_at: monday - 4 * DAY + 3600 },
    ];
    PAYLOAD = { symbol: 'AAPL', timeframe: '1wk', bars: bars, source: src,
                positions: positions, signals: [] };
    vm.runInContext(M.pure, sandbox, { filename: 'pure.js' });
    vm.runInContext(M.main, sandbox, { filename: 'widget.js' });
    for (let i = 0; i < 6; i++) await flush();
    const api = sandbox.svCharts[ID];
    const R = { monday: iso(monday), lastMonday: iso(monday - 7 * DAY) };
    R.markers = lastMarkers().filter(function (m) { return /^(LONG|SHORT) @/.test(m.text || ''); })
        .map(function (m) { return { time: m.time, shape: m.shape }; });
    move(100, 100, iso(monday));
    R.legend = legendEl.innerHTML;
    R.countdown = els[ID + '-countdown'].textContent;
    const q = { source_family: 'yahoo', stand_in: '', quote_age_seconds: 20,
                source_words: 'Yahoo AAPL' };
    api.tick(256.5, q);
    R.forming = { n: log.updates.length, last: lastUpdate(), tick: role('tick') };
    const settled = JSON.parse(JSON.stringify(PAYLOAD));
    settled.bars[settled.bars.length - 1].forming = false;
    await refresh(settled);
    const n0 = log.updates.length;
    api.tick(256.6, q);
    R.settled = { n: log.updates.length - n0, tick: role('tick') };
    process.stdout.write(JSON.stringify(R));
})().catch(function (e) { process.stderr.write(String((e && e.stack) || e)); process.exit(1); });
"""

WEEK_WITHOUT_TODAY = SCENARIO_HEAD + r"""
(async function () {
    const DAY = 86400;
    const today = nowS - nowS % DAY;
    const monday = today - ((new Date(today * 1000).getUTCDay() + 6) % 7) * DAY;
    const iso = function (s) { return new Date(s * 1000).toISOString().slice(0, 10); };
    const bars = [3, 2, 1].map(function (k) {
        return { time: iso(monday - k * 7 * DAY), open: 1.1, high: 1.11, low: 1.09,
                 close: 1.105, volume: 0 };
    });
    /* this week's candle as the server serves EURUSD routed to eToro:
       Yahoo's days, forming, and today's hours eToro's, so not in it */
    bars.push({ time: iso(monday), open: 1.105, high: 1.109, low: 1.103, close: 1.107,
                volume: 0, forming: true, no_tick: M.no_tick });
    const src = Object.assign({}, SRC, { family: 'yahoo', label: 'Yahoo EURUSD=X',
        words: "Yahoo EURUSD=X, not eToro's price", route: 'etoro', stand_in: '',
        same_feed_only: false, tick_bar: 0.005, notes: [M.note] });
    PAYLOAD = { symbol: 'EURUSD', timeframe: '1wk', bars: bars, source: src,
                positions: [], signals: [] };
    vm.runInContext(M.pure, sandbox, { filename: 'pure.js' });
    vm.runInContext(M.main, sandbox, { filename: 'widget.js' });
    for (let i = 0; i < 6; i++) await flush();
    const api = sandbox.svCharts[ID];
    const last = function () { const r = candle().rows; return r[r.length - 1]; };
    const R = { served: last() };
    move(100, 100, iso(monday));
    R.legend = legendEl.innerHTML;
    /* eToro's quote, +0.31%: inside forex's 0.5% bar, and no stand-in */
    const etoro = { source_family: 'etoro', stand_in: '', quote_age_seconds: 5,
                    source_words: 'eToro' };
    api.tick(1.1104, etoro);
    R.first = { n: log.updates.length, tick: role('tick'), last: last() };
    /* the 60 s refresh, the same reply, then the next 15 s tick */
    await refresh(JSON.parse(JSON.stringify(PAYLOAD)));
    api.tick(1.1105, etoro);
    R.second = { n: log.updates.length, tick: role('tick'), last: last() };
    api.tick(1.1106, { source_family: 'yahoo', stand_in: '', quote_age_seconds: 20,
                       source_words: 'Yahoo EURUSD=X' });
    R.sameFeed = { n: log.updates.length, tick: role('tick') };
    process.stdout.write(JSON.stringify(R));
})().catch(function (e) { process.stderr.write(String((e && e.stack) || e)); process.exit(1); });
"""


def _run(scenario, timeframe, **extra):
    pure, main = _blocks(widget(timeframe=timeframe, decimals=2))
    manifest = {"pure": pure, "main": main, "payload": {"bars": []}}
    manifest.update(extra)
    return _node(WIDGET_PRELUDE + scenario, manifest)


class _FineFrame:
    TF = ""
    SPAN = 0

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.r = _run(FINE, cls.TF, tf=cls.TF, span=cls.SPAN)

    def test_the_forming_bar_takes_a_fresh_quote_of_its_feed(self):
        f = self.r["forming"]
        self.assertEqual(f["n"], 1, f)
        self.assertEqual(f["last"]["close"], 4003.5)
        self.assertEqual(f["last"]["high"], 4004)
        self.assertTrue(f["tick"]["hidden"] or not f["tick"]["text"], f)

    def test_a_quote_taken_before_the_bar_opened_is_not_drawn(self):
        self.assertEqual(self.r["before"]["n"], 0)
        self.assertIn("before this candle opened", self.r["before"]["tick"]["text"])

    def test_a_move_past_the_class_bar_is_not_drawn(self):
        self.assertEqual(self.r["jump"]["n"], 0)
        self.assertIn("from the candle", self.r["jump"]["tick"]["text"])

    def test_another_feeds_stand_in_is_not_drawn(self):
        self.assertEqual(self.r["other"]["n"], 0)
        self.assertIn("another feed", self.r["other"]["tick"]["text"])

    def test_a_bar_whose_period_has_ended_takes_none(self):
        self.assertEqual(self.r["closed"]["n"], 0)
        self.assertIn("the last candle has closed", self.r["closed"]["tick"]["text"])

    def test_the_bar_close_countdown_runs(self):
        self.assertTrue(self.r["countdown"].startswith("BAR CLOSE "),
                        self.r["countdown"])


@unittest.skipUnless(NODE, "node is not installed")
class TheTenMinuteTickTests(_FineFrame, SimpleTestCase):
    TF, SPAN = "10min", 600


@unittest.skipUnless(NODE, "node is not installed")
class TheThirtyMinuteTickTests(_FineFrame, SimpleTestCase):
    TF, SPAN = "30min", 1800


@unittest.skipUnless(NODE, "node is not installed")
class TheTwoHourTickTests(_FineFrame, SimpleTestCase):
    TF, SPAN = "2h", 7200


@unittest.skipUnless(NODE, "node is not installed")
class TheWeeklyCandleTests(SimpleTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.r = _run(WEEKLY, "1wk")

    def test_this_weeks_forming_candle_takes_the_tick(self):
        f = self.r["forming"]
        self.assertEqual(f["n"], 1, f)
        self.assertEqual(f["last"]["close"], 256.5)
        self.assertEqual(f["last"]["time"], self.r["monday"])

    def test_a_settled_week_takes_none(self):
        self.assertEqual(self.r["settled"]["n"], 0)
        self.assertIn("closed", self.r["settled"]["tick"]["text"])

    def test_a_position_opened_this_week_sits_on_this_weeks_candle(self):
        """A weekly bar holds seven days: with a daily bar's span, a
        position opened on Wednesday fell past the last bar's close and was
        drawn nowhere."""
        self.assertEqual(self.r["markers"], [
            {"time": self.r["lastMonday"], "shape": "arrowDown"},
            {"time": self.r["monday"], "shape": "arrowUp"},
        ])

    def test_no_countdown_runs(self):
        self.assertEqual(self.r["countdown"], "")

    def test_the_crosshair_names_the_week_and_says_forming(self):
        self.assertIn("week of " + self.r["monday"], self.r["legend"])
        self.assertIn("FORMING", self.r["legend"])


@unittest.skipUnless(NODE, "node is not installed")
class TheWeekWithoutTodayTests(SimpleTestCase):
    """This week's candle, served forming but without today (2026-11-01):
    EURUSD routed to eToro, Yahoo EURUSD=X's days, today's hours eToro's.
    The widget read `forming` on a daily-family bar as "the tick may
    weld": an eToro quote, no stand-in, passed as the same instrument, and
    the week's close and high took today's price every 15 s, the 60 s
    refresh put Tuesday's figures back, and the next tick welded again.
    The server says why the bar takes no tick (`no_tick`); the caption
    says it, and nothing flips across a refresh."""

    #: The server's words (tests.test_chart_divisions pins them there).
    words = "this week's candle leaves today out"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.r = _run(WEEK_WITHOUT_TODAY, "1wk", no_tick=cls.words,
                     note=cls.words + ": today's intraday bars are eToro's, "
                                      "not Yahoo EURUSD=X's")

    def test_the_venue_s_quote_is_not_welded_and_the_caption_says_why(self):
        first = self.r["first"]
        self.assertEqual(first["n"], 0, first)
        self.assertEqual(first["tick"],
                         {"text": "live quote not drawn: " + self.words,
                          "hidden": False})
        self.assertEqual(first["last"], self.r["served"])

    def test_nothing_flips_across_a_refresh(self):
        second = self.r["second"]
        self.assertEqual(second["n"], 0, second)
        self.assertEqual(second["last"], self.r["served"])
        self.assertEqual((second["last"]["close"], second["last"]["high"]),
                         (1.107, 1.109))
        self.assertEqual(second["tick"]["text"],
                         "live quote not drawn: " + self.words)

    def test_the_same_feed_s_quote_is_not_welded_either(self):
        same = self.r["sameFeed"]
        self.assertEqual(same["n"], 0, same)
        self.assertEqual(same["tick"]["text"],
                         "live quote not drawn: " + self.words)

    def test_the_week_still_reads_forming(self):
        self.assertIn("week of ", self.r["legend"])
        self.assertIn("FORMING", self.r["legend"])
