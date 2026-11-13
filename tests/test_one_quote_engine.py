"""ONE PRICE EVERYWHERE: the browser's one painter, its rules (2026-11-12).

static/js/sv-venue.js keeps the newest value per symbol and paints every
cell of a symbol from it. Measured before it existed (scratchpad
onequote/measure_before.md, table D): a tick ten minutes old replaced one
five seconds old on the headband; a tick with no time froze the card on
another feed's price; an OANDA tick for a held pair painted the headband
over eToro's price. Here, under node, with no page:

  * a value replaces the entry only when its `at` is newer; a server value
    that switches the source replaces it when rendered after the entry;
  * an outside stream's tick never paints an instrument held at eToro, and
    moves an outside price only when it is the stream that wrote it;
  * every field a cell can print is the server's own text for it
    (one_quote.Shown.field_text, compared on the measured fixture);
  * a chart gets ONE "now" line at the shown price, moved by each newer
    value, and a caption that names another feed's bars and their gap.

Run with:  python manage.py test tests.test_one_quote_engine
"""
import json
import shutil
import subprocess
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

from tests.one_quote_fixture import T, quote, seed_measured

ENGINE = Path(settings.BASE_DIR) / "static" / "js" / "sv-venue.js"
NODE = shutil.which("node")

PRELUDE = r"""
const fs = require('fs'), vm = require('vm');
const M = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const sandbox = { setTimeout: function () { return 0; }, setInterval: function () { return 0; },
                  console: console, Date: Date };
sandbox.window = sandbox;
vm.createContext(sandbox);
vm.runInContext(M.engine, sandbox, { filename: 'sv-venue.js' });
const V = sandbox.SVVenue;
const clone = function (o) { return JSON.parse(JSON.stringify(o)); };
"""


def _ms(dt):
    return int(round(dt.timestamp() * 1000))


def _node(program, manifest):
    tmp = Path(tempfile.mkdtemp(prefix="sv-oq-engine-"))
    try:
        (tmp / "run.js").write_text(PRELUDE + program, encoding="utf-8")
        (tmp / "m.json").write_text(json.dumps(manifest), encoding="utf-8")
        out = subprocess.run([NODE, str(tmp / "run.js"), str(tmp / "m.json")],
                             capture_output=True, text=True, encoding="utf-8",
                             timeout=120)
        if out.returncode != 0:
            raise AssertionError("node failed: %s" % out.stderr[-2000:])
        return json.loads(out.stdout)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _payload(**kw):
    base = {"s": "EURUSD", "p": "1.08447", "v": 1.08447, "l": "1.08452",
            "b": "1.08447", "a": "1.08457", "side": "bid", "src": "etoro",
            "fam": "etoro", "who": "eToro", "auth": "etoro",
            "basis": "stamp:tick", "at": _ms(T) - 25000, "state": "delayed",
            "dp": 5, "cls": "forex", "chg": None, "ls": None, "shut": None,
            "sf": None, "slot": None, "via": "tick"}
    base.update(kw)
    return base


ORDER = r"""
const R = {};
const t0 = M.t0;
const P = M.p;
V.ingest(P, t0);
R.first = V.get('EURUSD').p;
V.ingest(Object.assign(clone(P), { p: '1.08460', v: 1.0846, b: '1.08460', at: P.at + 5000 }), t0 + 5000);
R.newer = V.get('EURUSD').p;
V.ingest(Object.assign(clone(P), { p: '1.08300', v: 1.083, b: '1.08300', at: P.at - 60000 }), t0 + 9000);
R.older = V.get('EURUSD').p;
/* The position closed: the server's next render shows the reference row,
   older in `at` but rendered later, and it is the price now. */
V.ingest(Object.assign(clone(M.g), { s: 'EURUSD' }), t0 + 20000);
R.switched = [V.get('EURUSD').src, V.get('EURUSD').p];
/* An older render of the held reading comes back: refused. */
V.ingest(Object.assign(clone(P), { at: P.at + 9000 }), t0 + 1000);
R.oldRender = V.get('EURUSD').src;

/* I10: an OANDA tick for an instrument held at eToro paints nothing. */
V.ingest(P, t0 + 30000);
V.ingest(Object.assign(clone(P), { at: P.at + 30000 }), t0 + 30000);
V.tick({ type: 'quote_stream', data: { symbol: 'EUR_USD', last: 1.2, bid: 1.19, ask: 1.21,
                                        source: 'oanda_stream', ts: new Date(t0 + 60000).toISOString() } });
R.heldTick = V.get('EURUSD').p;

/* An outside pair the OANDA stream wrote: its ticks move it forward. */
const G = clone(M.g);
V.ingest(G, t0);
V.tick({ type: 'quote_stream', data: { symbol: 'GBP_USD', last: 1.29455, bid: 1.2945, ask: 1.2946,
                                        source: 'oanda_stream', ts: new Date(G.at + 5000).toISOString() } });
R.streamTick = [V.get('GBPUSD').p, V.get('GBPUSD').b, V.get('GBPUSD').at - G.at];
V.tick({ type: 'quote_stream', data: { symbol: 'GBPUSD', last: 1.293, source: 'oanda_stream',
                                        ts: new Date(G.at - 600000).toISOString() } });
R.olderTick = V.get('GBPUSD').p;
V.tick({ type: 'quote_stream', data: { symbol: 'GBPUSD', last: 1.299, source: 'binance_ws',
                                        ts: new Date(G.at + 60000).toISOString() } });
R.otherStream = V.get('GBPUSD').p;
/* A Finnhub print (no time, no source) for a row Finnhub wrote. */
V.ingest(Object.assign(clone(G), { s: 'AAPL', p: '227.94', v: 227.94, b: null, a: null,
                                    src: 'finnhub_ws', fam: 'finnhub', who: 'Finnhub stream',
                                    dp: 2, cls: 'stock', ls: 65, at: Date.now() - 60000 }), t0);
V.tick({ type: 'quote_stream', data: { symbol: 'AAPL', last: 228.01, volume: 3 } });
R.finnhub = V.get('AAPL').p;
/* The relay's message: a server value under data.q. */
V.tick({ type: 'quote', data: { symbol: 'XAUUSD', price: '2648.30', source: 'etoro', t: t0 + 40000,
                                q: Object.assign(clone(P), { s: 'XAUUSD', p: '2648.30', v: 2648.3, dp: 2 }) } });
R.relay = V.get('XAUUSD').p;
process.stdout.write(JSON.stringify(R));
"""

CHART = r"""
const R = {};
const lines = [];
function Line(o) { this.o = Object.assign({}, o); }
Line.prototype.applyOptions = function (o) { Object.assign(this.o, o); };
const series = { createPriceLine: function (o) { const l = new Line(o); lines.push(l); return l; },
                 removePriceLine: function (l) { lines.splice(lines.indexOf(l), 1); } };
const caption = { textContent: '', hidden: true };
let nowSet = 'unset';
const handle = { symbol: 'EURUSD', series: function () { return series; },
                 bars: function () { return [{ time: 1, close: 1.08512 }]; },
                 source: function () { return { family: 'yahoo', label: 'Yahoo EURUSD=X',
                                                what: 'Yahoo EURUSD=X', stand_in: '' }; },
                 caption: function () { return caption; },
                 setNow: function (v) { nowSet = v; } };
const P = M.p;
V.ingest(P, M.t0);
V.chart(handle);
R.first = { n: lines.length, price: lines[0].o.price, title: lines[0].o.title,
            style: lines[0].o.lineStyle, axis: lines[0].o.axisLabelVisible,
            caption: caption.textContent, nowSet: nowSet };
V.ingest(Object.assign(clone(P), { p: '1.08470', v: 1.0847, b: '1.08470', at: P.at + 5000 }), M.t0 + 5000);
V.flush();
R.moved = { n: lines.length, price: lines[0].o.price };
V.ingest(Object.assign(clone(P), { v: null, p: null, b: null, a: null, state: 'none', at: null }), M.t0 + 9000);
V.flush();
R.none = { n: lines.length, caption: caption.textContent, hidden: caption.hidden, nowSet: nowSet };

const lines2 = [];
const s2 = { createPriceLine: function (o) { const l = new Line(o); lines2.push(l); return l; },
             removePriceLine: function () {} };
const cap2 = { textContent: '', hidden: true };
V.ingest(M.g, M.t0);
V.chart({ symbol: 'GBPUSD', series: function () { return s2; },
          bars: function () { return [{ time: 1, close: 1.29440 }]; },
          source: function () { return { family: 'yahoo', label: 'Yahoo GBPUSD=X', stand_in: '' }; },
          caption: function () { return cap2; } });
R.same = { price: lines2[0].o.price, title: lines2[0].o.title, caption: cap2.textContent };

const lines3 = [];
const s3 = { createPriceLine: function (o) { const l = new Line(o); lines3.push(l); return l; },
             removePriceLine: function () {} };
const cap3 = { textContent: '', hidden: true };
V.ingest(Object.assign(clone(P), { s: 'XAUUSD', p: '2648.30', v: 2648.3, b: '2648.30', a: '2648.80', dp: 2 }), M.t0);
V.chart({ symbol: 'XAUUSD', series: function () { return s3; },
          bars: function () { return [{ time: 1, close: 2671.30 }]; },
          source: function () { return { family: 'yahoo', label: 'Yahoo GC=F',
                                          what: 'Yahoo GC=F, the front-month future', stand_in: 'future' }; },
          caption: function () { return cap3; } });
R.standIn = cap3.textContent;
process.stdout.write(JSON.stringify(R));
"""

FIELDS = r"""
const out = {};
Object.keys(M.cases).forEach(function (sym) {
    const c = M.cases[sym];
    V.ingest(c.payload, M.t0);
    out[sym] = {};
    c.asks.forEach(function (a) {
        out[sym][a.join('|')] = V.fieldText(V.get(sym), a[0], a[1], M.now);
    });
});
process.stdout.write(JSON.stringify(out));
"""

FIELD_ASKS = [("price", ""), ("price", "bid"), ("price", "ask"),
              ("price", "mid"), ("price", "last"), ("bid", ""), ("ask", ""),
              ("spread", ""), ("sides", ""), ("chg", ""), ("who", ""),
              ("words", ""), ("words", "ask"), ("age", ""), ("asof", ""),
              ("slot", "")]


@unittest.skipUnless(NODE, "node is not installed")
class TheMapOrderTests(SimpleTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        g = _payload(s="GBPUSD", p="1.29410", v=1.2941, l="1.29410",
                     b="1.29405", a="1.29415", side="", src="oanda_stream",
                     fam="oanda", who="OANDA stream", auth="reference",
                     basis="quote", at=_ms(T) - 240000, ls=15, via="")
        cls.r = _node(ORDER, {"engine": ENGINE.read_text(encoding="utf-8"),
                              "p": _payload(), "g": g, "t0": _ms(T)})

    def test_a_newer_value_wins_and_an_older_one_is_dropped(self):
        self.assertEqual(self.r["first"], "1.08447")
        self.assertEqual(self.r["newer"], "1.08460")
        self.assertEqual(self.r["older"], "1.08460")

    def test_the_server_decides_a_switch_of_source(self):
        self.assertEqual(self.r["switched"], ["oanda_stream", "1.29410"])
        self.assertEqual(self.r["oldRender"], "oanda_stream")

    def test_an_outside_tick_never_paints_an_etoro_instrument(self):
        self.assertEqual(self.r["heldTick"], "1.08447")

    def test_the_stream_that_wrote_an_outside_price_moves_it_forward(self):
        self.assertEqual(self.r["streamTick"], ["1.29455", "1.29450", 5000])
        self.assertEqual(self.r["olderTick"], "1.29455", "an older tick")
        self.assertEqual(self.r["otherStream"], "1.29455", "another stream")
        self.assertEqual(self.r["finnhub"], "228.01")

    def test_the_relays_message_is_a_server_value(self):
        self.assertEqual(self.r["relay"], "2648.30")


@unittest.skipUnless(NODE, "node is not installed")
class TheChartsNowLineTests(SimpleTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        g = _payload(s="GBPUSD", p="1.29410", v=1.2941, l="1.29410", b=None,
                     a=None, side="", src="yfinance", fam="yahoo",
                     who="Yahoo GBPUSD=X", auth="reference", basis="quote",
                     at=_ms(T) - 240000, via="")
        cls.r = _node(CHART, {"engine": ENGINE.read_text(encoding="utf-8"),
                              "p": _payload(), "g": g, "t0": _ms(T)})

    def test_one_dashed_line_at_the_shown_price_named_by_its_side(self):
        f = self.r["first"]
        self.assertEqual((f["n"], f["price"], f["title"], f["style"], f["axis"]),
                         (1, 1.08447, "eToro bid", 2, True))
        self.assertEqual(f["nowSet"], 1.08447, "the autoscale includes it")

    def test_another_feeds_bars_are_named_with_their_gap(self):
        cap = self.r["first"]["caption"]
        self.assertTrue(cap.startswith("bars: Yahoo EURUSD=X · price: eToro bid · "), cap)
        self.assertTrue(cap.endswith(" · bars +0.06%"), cap)

    def test_a_newer_value_moves_the_same_line(self):
        self.assertEqual(self.r["moved"], {"n": 1, "price": 1.0847})

    def test_no_price_takes_the_line_away(self):
        n = self.r["none"]
        self.assertEqual((n["n"], n["caption"], n["hidden"], n["nowSet"]),
                         (0, "", True, None))

    def test_the_candles_own_feed_needs_no_bars_words(self):
        s = self.r["same"]
        self.assertEqual((s["price"], s["title"]), (1.2941, "Yahoo GBPUSD=X"))
        self.assertTrue(s["caption"].startswith("now: Yahoo GBPUSD=X · "), s)

    def test_a_stand_ins_bars_are_another_instrument_always_measured(self):
        self.assertTrue(self.r["standIn"].startswith(
            "bars: Yahoo GC=F, the front-month future (another instrument) · "
            "price: eToro bid · "), self.r["standIn"])
        self.assertTrue(self.r["standIn"].endswith(" · bars +0.87%"),
                        self.r["standIn"])


@unittest.skipUnless(NODE, "node is not installed")
class EveryFieldIsTheServersTextTests(TestCase):
    """Each field a cell can print, through the engine, equals the server's
    own text for it (one_quote.Shown.field_text), on the measured fixture
    and a hedged, a sideless, a shut-free stand-in and an empty one."""

    def test_every_field_of_every_symbol(self):
        from market_data.one_quote import shown_many
        user = get_user_model().objects.create_user("oq_fields", password="x")
        seed_measured(user)
        quote("USDJPY", "151.234", "oanda_stream", 5, bid="151.230",
              ask="151.238", chg="0.40", chg_src="oanda_stream")
        syms = ["EURUSD", "XAUUSD", "AAPL", "GBPUSD", "USDJPY", "NOPE"]
        now = T + timedelta(seconds=7)
        got = shown_many(syms, user=user, now=T)
        cases, want = {}, {}
        for sym in syms:
            s = got[sym]
            cases[sym] = {"payload": s.payload(), "asks": FIELD_ASKS}
            want[sym] = {f"{f}|{side}": s.field_text(f, side=side or None,
                                                     now_at=now)
                         for f, side in FIELD_ASKS}
        r = _node(FIELDS, {"engine": ENGINE.read_text(encoding="utf-8"),
                           "cases": cases, "t0": _ms(T),
                           "now": _ms(now)})
        for sym in syms:
            for k, w in want[sym].items():
                with self.subTest(sym=sym, field=k):
                    self.assertEqual(r[sym][k], w)
