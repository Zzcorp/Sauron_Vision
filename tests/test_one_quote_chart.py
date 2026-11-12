"""ONE PRICE EVERYWHERE: the charts agree with the numbers (2026-11-12).

The operator, a minute after "they need to be similar alltogether":
"between charts and numbers also mostly". Measured on the synthetic
fixture (scratchpad/onequote/measure_before.md, table B): the only "now"
on a chart was the series' own last-value line, i.e. whatever the last
bar's close was; the 15-second tick welded an 8-minute-old eToro quote
onto Yahoo's EURUSD candles (a wick Yahoo never printed), Finnhub's print
onto eToro's own AAPL 4h candle, and an older eToro quote over a newer
eToro close; the gold chart sat 0.87% from the hero beside it.

Now, the widget's real script and the one painter (static/js/sv-venue.js)
under node, on the fake chart of tests.test_chart_signal_markers:

  * ONE "now" line, at the price every number beside the chart prints
    (the payload's v), named by its source and side, dashed, on the axis;
    the series' own last-value line is off; the autoscale includes it;
    a newer value moves the same line;
  * a quote is welded onto the forming candle only when the candles are
    its own feed AND its own side (source.close_side): an eToro price is
    never welded onto Yahoo's candles, nor onto eToro's own before M5
    measures their close side; a Yahoo price on Yahoo's candles is, on the
    forming bar only; a past bar is never touched;
  * bars of another feed say so, with their gap: "bars: Yahoo EURUSD=X ·
    price: eToro bid · ... · bars +0.06%".

Run with:  python manage.py test tests.test_one_quote_chart
"""
import json
import unittest
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from tests.test_chart_one_price_widget import SCENARIO_HEAD
from tests.test_chart_signal_markers import (NODE, WIDGET_PRELUDE, _blocks,
                                             _node, widget)

ENGINE = Path(settings.BASE_DIR) / "static" / "js" / "sv-venue.js"

SCENARIO = SCENARIO_HEAD + r"""
vm.runInContext(M.engine, sandbox, { filename: 'sv-venue.js' });
const V = sandbox.SVVenue;
const hourS = nowS - nowS % 3600;
const yahooBars = function (last) {
    const bars = [];
    for (let i = 5; i >= 0; i--) {
        const c = last - i * 0.0001;
        bars.push({ time: hourS - i * 3600, open: c - 0.00005, high: c + 0.0001,
                    low: c - 0.0001, close: c, volume: 0 });
    }
    return bars;
};
const lines = function () {
    return candle().lines.map(function (l) {
        return { title: l.o.title, price: l.o.price, style: l.o.lineStyle,
                 axis: l.o.axisLabelVisible };
    });
};
(async function () {
    const R = {};
    const EUR = M.eur, GBP = M.gbp;
    V.ingest(EUR, M.t0);
    V.ingest(GBP, M.t0);

    /* A held EURUSD (eToro's bid) over Yahoo's hourly candles. */
    PAYLOAD = { symbol: 'EURUSD', timeframe: '1h', bars: yahooBars(1.08512),
                source: { family: 'yahoo', label: 'Yahoo EURUSD=X', words: 'Yahoo EURUSD=X',
                          what: 'Yahoo EURUSD=X', stand_in: '', route: 'etoro', tick_bar: 0.02,
                          notes: [], positions: '', close_side: 'last' },
                positions: [], signals: [] };
    vm.runInContext(M.pure, sandbox, { filename: 'pure.js' });
    vm.runInContext(M.main, sandbox, { filename: 'widget.js' });
    for (let i = 0; i < 6; i++) await flush();
    const api = sandbox.svCharts[ID];
    R.handle = { symbol: api.symbol, hasSeries: typeof api.series === 'function',
                 hasBars: typeof api.bars === 'function',
                 hasSource: typeof api.source === 'function' };
    R.opts = { priceLineVisible: log.candleOpts && log.candleOpts.priceLineVisible,
               lastValueVisible: log.candleOpts && log.candleOpts.lastValueVisible };
    R.lines = lines();
    R.caption = role('now');
    const prov = log.candleOpts && log.candleOpts.autoscaleInfoProvider;
    R.autoscale = prov ? prov(function () {
        return { priceRange: { minValue: 1.0849, maxValue: 1.0853 }, margins: { above: 0.1, below: 0.1 } };
    }) : null;

    let n0 = log.updates.length;
    api.tick(1.08447, { source_family: 'etoro', side: 'bid', stand_in: '', quote_age_seconds: 5,
                        source_words: 'eToro' });
    R.etoroOnYahoo = { n: log.updates.length - n0, tick: role('tick') };

    /* A newer eToro reading: the same line moves. */
    V.ingest(Object.assign(JSON.parse(JSON.stringify(EUR)), { p: '1.08470', v: 1.0847, b: '1.08470',
                                                             at: EUR.at + 5000 }), M.t0 + 5000);
    V.flush();
    R.moved = lines();

    /* eToro's own candles: no weld until M5 measures their close side. */
    const etoro = JSON.parse(JSON.stringify(PAYLOAD));
    etoro.source = Object.assign({}, etoro.source, { family: 'etoro', label: 'eToro',
                                                     words: "eToro's own candles", what: 'eToro',
                                                     close_side: null });
    await refresh(etoro);
    n0 = log.updates.length;
    api.tick(1.0847, { source_family: 'etoro', side: 'bid', stand_in: '', quote_age_seconds: 5,
                       source_words: 'eToro' });
    R.etoroOnEtoro = { n: log.updates.length - n0, tick: role('tick'), lines: lines(),
                       caption: role('now') };
    process.stdout.write(JSON.stringify(R));
})().catch(function (e) { process.stderr.write(String((e && e.stack) || e)); process.exit(1); });
"""

UNHELD = SCENARIO_HEAD + r"""
vm.runInContext(M.engine, sandbox, { filename: 'sv-venue.js' });
const V = sandbox.SVVenue;
const hourS = nowS - nowS % 3600;
(async function () {
    const R = {};
    V.ingest(M.gbp, M.t0);
    const bars = [];
    for (let i = 5; i >= 0; i--) {
        const c = 1.2944 - i * 0.0001;
        bars.push({ time: hourS - i * 3600, open: c, high: c + 0.0002, low: c - 0.0002,
                    close: c, volume: 0 });
    }
    PAYLOAD = { symbol: 'GBPUSD', timeframe: '1h', bars: bars,
                source: { family: 'yahoo', label: 'Yahoo GBPUSD=X', words: 'Yahoo GBPUSD=X',
                          what: 'Yahoo GBPUSD=X', stand_in: '', route: '', tick_bar: 0.02,
                          notes: [], positions: '', close_side: 'last' },
                positions: [], signals: [] };
    vm.runInContext(M.pure, sandbox, { filename: 'pure.js' });
    vm.runInContext(M.main, sandbox, { filename: 'widget.js' });
    for (let i = 0; i < 6; i++) await flush();
    const api = sandbox.svCharts[ID];
    R.lines = candle().lines.map(function (l) { return { title: l.o.title, price: l.o.price }; });
    R.caption = role('now');
    api.tick(1.2941, { source_family: 'yahoo', side: '', stand_in: '', quote_age_seconds: 20,
                       source_words: 'Yahoo GBPUSD=X' });
    R.weld = { n: log.updates.length, last: lastUpdate(), lastBar: bars[bars.length - 1].time };
    process.stdout.write(JSON.stringify(R));
})().catch(function (e) { process.stderr.write(String((e && e.stack) || e)); process.exit(1); });
"""


def _payload(**kw):
    base = {"s": "EURUSD", "p": "1.08447", "v": 1.08447, "l": "1.08452",
            "b": "1.08447", "a": "1.08457", "side": "bid", "src": "etoro",
            "fam": "etoro", "who": "eToro", "auth": "etoro",
            "basis": "stamp:tick", "at": None, "state": "delayed", "dp": 5,
            "cls": "forex", "chg": None, "ls": None, "shut": None, "sf": None,
            "slot": None, "via": "tick"}
    base.update(kw)
    return base


def _run(scenario, symbol):
    import time
    t0 = int(time.time() * 1000)
    pure, main = _blocks(widget(timeframe="1h", decimals=5, symbol=symbol))
    eur = _payload(at=t0 - 25000)
    gbp = _payload(s="GBPUSD", p="1.29410", v=1.2941, l="1.29410", b=None,
                   a=None, side="", src="yfinance", fam="yahoo",
                   who="Yahoo GBPUSD=X", auth="reference", basis="quote",
                   at=t0 - 60000, via="")
    return _node(WIDGET_PRELUDE + scenario, {
        "pure": pure, "main": main, "payload": {"bars": []},
        "engine": ENGINE.read_text(encoding="utf-8"), "eur": eur,
        "gbp": gbp, "t0": t0})


@unittest.skipUnless(NODE, "node is not installed")
class TheNowLineTests(SimpleTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.r = _run(SCENARIO, "EURUSD")

    def test_the_widget_hands_the_painter_its_chart(self):
        self.assertEqual(self.r["handle"], {"symbol": "EURUSD", "hasSeries": True,
                                            "hasBars": True, "hasSource": True})

    def test_one_now_line_at_the_numbers_price(self):
        now = [l for l in self.r["lines"] if l["title"] == "eToro bid"]
        self.assertEqual(now, [{"title": "eToro bid", "price": 1.08447,
                                "style": 2, "axis": True}])

    def test_the_series_own_last_value_line_is_off(self):
        self.assertIs(self.r["opts"]["priceLineVisible"], False)

    def test_the_autoscale_includes_the_now_line(self):
        rng = self.r["autoscale"]["priceRange"]
        self.assertEqual(rng["minValue"], 1.08447)
        self.assertEqual(rng["maxValue"], 1.0853)

    def test_bars_of_another_feed_say_so_with_their_gap(self):
        cap = self.r["caption"]
        self.assertFalse(cap["hidden"])
        self.assertTrue(cap["text"].startswith(
            "bars: Yahoo EURUSD=X · price: eToro bid · "), cap)
        self.assertTrue(cap["text"].endswith(" · bars +0.06%"), cap)

    def test_an_etoro_price_is_never_welded_on_yahoo_candles(self):
        r = self.r["etoroOnYahoo"]
        self.assertEqual(r["n"], 0)
        self.assertFalse(r["tick"]["hidden"])
        self.assertIn("not drawn", r["tick"]["text"])

    def test_a_newer_value_moves_the_same_line(self):
        now = [l for l in self.r["moved"] if l["title"] == "eToro bid"]
        self.assertEqual([l["price"] for l in now], [1.0847])

    def test_eToros_own_candles_take_no_weld_before_m5(self):
        r = self.r["etoroOnEtoro"]
        self.assertEqual(r["n"], 0)
        self.assertIn("not drawn", r["tick"]["text"])
        self.assertEqual([l["price"] for l in r["lines"] if l["title"] == "eToro bid"],
                         [1.0847], "the line survives a refresh")
        self.assertTrue(r["caption"]["text"].startswith("now: eToro bid · "),
                        r["caption"])


@unittest.skipUnless(NODE, "node is not installed")
class TheSameFeedWeldTests(SimpleTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.r = _run(UNHELD, "GBPUSD")

    def test_the_line_and_the_caption(self):
        self.assertIn({"title": "Yahoo GBPUSD=X", "price": 1.2941},
                      self.r["lines"])
        self.assertTrue(self.r["caption"]["text"].startswith(
            "now: Yahoo GBPUSD=X · "), self.r["caption"])

    def test_a_yahoo_price_on_yahoo_candles_is_welded_on_the_forming_bar(self):
        w = self.r["weld"]
        self.assertEqual(w["n"], 1)
        self.assertEqual(w["last"]["close"], 1.2941)
        self.assertEqual(w["last"]["time"], w["lastBar"])
