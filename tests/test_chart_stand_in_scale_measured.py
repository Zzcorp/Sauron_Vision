"""Another instrument's candles keep their own scale, measured in Chromium
(2026-11-19).

The operator, 2026-11-19: "il y a un probleme d'affichage des prix sur
certaines charts comme la 30min ... sur d'autres pareil.... fix it". In
the chart-prices reproduction, gold's 1 min chart drew Yahoo GC=F's
candles (the front-month future, the keyless feed's stand-in) under
eToro's ask, 0.6 % lower: the price scale always stretched to hold the
"now" line (nowAware), so the candles filled 41 % of the pane, the line
floated under every candle, and most axis labels sat where no candle was.

Now, on a stand-in's candles under another feed's price, the scale is the
candles' own, and the price, when it falls off the pane, is pinned to the
pane's edge as a chip with its arrow, like his stop off the view ("eToro
ask 4124.54"). eToro's own candles, and a same-instrument feed's under an
eToro price (EURUSD=X), keep the line in the scale.

The scene: the desk v2 deploy note's invented book (tests/desk_scenes.py),
the clock held at its instant, the page served with every script, the
chart library from its pinned copy, 1440 x 900 at deviceScaleFactor 1.
Gold there: a REAL eToro short marked at eToro's ask 4124.54 (40 s old),
its LiveQuote Yahoo's GC=F at 4152.24, 240 invented 1 min GC=F candles
between 4149.56 and 4181.21 from the keyless feed (a fake: no request
leaves the machine), and 240 invented eToro 1h candles over 4130. The
scale is read through the library: priceToCoordinate on the visible bars'
extremes and on the price, and the pane's height (paneSize).

Display only: nothing here posts, trades, or calls a broker or a model.
"""
import json
import math
import unittest
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.test import Client, TestCase

from tests import desk_scenes as S
from tests.test_close_advice import CHROME

CID = "instrument-main-chart"
ETORO_ASK = 4124.54

#: The chart's instance, through the library's own createChart (a read of
#: the scale only; nothing of the chart is changed).
CAPTURE = r"""(function () {
  var lw;
  Object.defineProperty(window, 'LightweightCharts', {
    configurable: true,
    get: function () { return lw; },
    set: function (v) {
      var make = v.createChart, w = Object.create(v);
      Object.defineProperty(w, 'createChart', { enumerable: true, value: function (el, opts) {
        var c = make.call(v, el, opts);
        (window.__svLwc = window.__svLwc || []).push({ el: el, chart: c });
        return c;
      }});
      lw = w;
    }
  });
})();"""

#: The main chart as drawn: whose candles, the visible bars' extremes and
#: their y, the price and its y, the pane, the money chips (pane px).
READ = r"""(function (cid) {
  var h = window.svCharts && window.svCharts[cid];
  var rec = (window.__svLwc || []).filter(function (r) { return r.el && r.el.id === cid; })[0];
  if (!h || !rec || !h.series()) return JSON.stringify({ error: 'no chart' });
  var chart = rec.chart, series = h.series(), pane = chart.paneSize();
  var lr = chart.timeScale().getVisibleLogicalRange();
  var bars = h.bars() || [];
  var from = Math.max(0, Math.floor(lr.from)), to = Math.min(bars.length - 1, Math.ceil(lr.to));
  var lo = Infinity, hi = -Infinity;
  for (var i = from; i <= to; i++) {
    var b = bars[i];
    if (b) { lo = Math.min(lo, b.low); hi = Math.max(hi, b.high); }
  }
  var src = h.source() || {};
  var v = (h._svNowV === undefined) ? null : h._svNowV;
  var el = document.getElementById(cid), box = el.getBoundingClientRect();
  var chips = Array.prototype.map.call(el.querySelectorAll('.sv-mchip'), function (c) {
    var r = c.getBoundingClientRect();
    return { text: c.textContent.replace(/\s+/g, ' ').trim(), cls: c.className,
             edge: c.getAttribute('data-edge'), top: r.top - box.top, bottom: r.bottom - box.top };
  });
  var cap = document.querySelector('#' + cid + '-src [data-role="now"]');
  return JSON.stringify({ family: src.family, standIn: src.stand_in, n: bars.length,
                          low: lo, high: hi, paneH: pane.height,
                          yLow: series.priceToCoordinate(lo), yHigh: series.priceToCoordinate(hi),
                          now: v, yNow: v === null ? null : series.priceToCoordinate(v),
                          foot: Math.round(pane.height * 0.86) - 6, chips: chips,
                          caption: cap ? cap.textContent : '' });
})(%s)"""


def _minutes(n, mid, swing, half_range, period, low=None, high=None):
    """`n` one-minute candles up to the scene's instant: a slow swing of
    `swing` around `mid`, each candle `half_range` either side of its
    middle; the lowest low and the highest high set to `low` and `high`."""
    end = S.T.replace(second=0, microsecond=0)
    rows = []
    for k in range(n):
        m = mid + swing * math.sin(k / period)
        o, c = (m - half_range / 2, m + half_range / 2) if k % 2 else \
            (m + half_range / 2, m - half_range / 2)
        rows.append([end - timedelta(minutes=n - 1 - k), o, m + half_range,
                     m - half_range, c])
    if low is not None:
        min(rows, key=lambda r: r[3])[3] = low
    if high is not None:
        max(rows, key=lambda r: r[2])[2] = high
    return rows


class _Feed:
    """The keyless feed, answering the scene's minute candles per symbol."""

    def __init__(self):
        self.asked = []
        self.rows = {
            "XAUUSD": _minutes(240, 4165.385, 13.0, 2.3, 19.0,
                               low=4149.56, high=4181.21),
            "EURUSD": _minutes(240, 1.08225, 0.0003, 0.00008, 17.0),
        }

    def klines(self, symbol, interval="1m", limit=240):
        self.asked.append((symbol, interval, limit))
        return [[int(t.timestamp()) * 1000, str(round(o, 5)), str(round(h, 5)),
                 str(round(lo, 5)), str(round(c, 5)), "120"]
                for t, o, h, lo, c in self.rows.get(symbol, [])[-limit:]]


def _gold_on_the_scene(book):
    """Gold as the reproduction had it: the REAL short marked at eToro's
    ask 4124.54, the LiveQuote Yahoo's GC=F (no sides), eToro's own 1h
    candles over 4130, no signal."""
    from bot_program.models import AssetBotTrade
    from instruments.models import Instrument
    from market_data.models import LiveQuote, PriceData
    from signals.models import Signal
    gold = Instrument.objects.get(symbol="XAUUSD")
    # The scene's gold signal (at the book's 2650 level) would hang its dot
    # on these candles; a marker's room widens the scale by itself.
    Signal.objects.filter(instrument=gold).delete()
    LiveQuote.objects.filter(instrument=gold).update(
        last=Decimal("4152.24"), bid=None, ask=None, source="yfinance",
        change_source="yfinance", updated_at=S.T - timedelta(seconds=90))
    t = AssetBotTrade.objects.get(pk=book["ids"]["live_XAUUSD"])
    meta = dict(t.metadata, initial_stop_loss=4230.0)
    meta["venue_mark"] = {"price": ETORO_ASK, "bid": 4124.04, "ask": ETORO_ASK,
                          "source": "etoro", "via": "tick",
                          "at": (S.T - timedelta(seconds=40)).isoformat()}
    AssetBotTrade.objects.filter(pk=t.pk).update(
        entry_price=Decimal("4186.97"), stop_loss=Decimal("4230.00"),
        take_profit=Decimal("4100.00"), metadata=meta)
    hour = S.T.replace(minute=0, second=0, microsecond=0)
    rows = []
    for k in range(240):
        m = 4157 + 20 * math.sin(k / 23)
        o, c = (m - 1.5, m + 1.5) if k % 2 else (m + 1.5, m - 1.5)
        rows.append(PriceData(instrument=gold, timeframe="1h", source="etoro",
                              timestamp=hour - timedelta(hours=239 - k),
                              open=Decimal(str(round(o, 2))),
                              high=Decimal(str(round(m + 4, 2))),
                              low=Decimal(str(round(m - 4, 2))),
                              close=Decimal(str(round(c, 2))), volume=300))
    PriceData.objects.bulk_create(rows)


class _Browser(S.SceneBrowser):
    """The scene's browser, each tab also keeping the chart's instance."""

    def __init__(self, client):
        super().__init__(client)
        tab = self.driver.tab

        def with_capture(width, height, mobile=False, init=""):
            return tab(width, height, mobile, init + "\n" + CAPTURE)
        self.driver.tab = with_capture


@unittest.skipUnless(CHROME, "no headless Chromium on this machine")
class TheStandInScaleMeasuredTests(TestCase):
    """/instruments/XAUUSD/ on 1 min (the stand-in's candles) and 1H
    (eToro's own), /instruments/EURUSD/ on 1 min (Yahoo EURUSD=X under
    eToro's bid): 1440 x 900, the rail shut."""

    maxDiff = None
    PAGES = (("gold_1min", "XAUUSD", "1min"), ("gold_1h", "XAUUSD", "1h"),
             ("eur_1min", "EURUSD", "1min"))

    @classmethod
    def setUpTestData(cls):
        S.hold_the_clock(cls)
        book = S.scene_book()
        _gold_on_the_scene(book)
        client = Client()
        client.force_login(book["user"])
        cls.feed = _Feed()
        cls.got, cls.drew = {}, {}
        with mock.patch("market_data.public_feed.public_feed_for",
                        return_value=cls.feed), \
                mock.patch("bot_program.engine.broker_router."
                           "broker_name_for_symbol", return_value="etoro"):
            desk = _Browser(client)
            try:
                for name, sym, tf in cls.PAGES:
                    pref = {"sv-chart:%s:%s" % (CID, sym): json.dumps({"tf": tf})}
                    tid, sid = desk.open("/instruments/%s/" % sym, 1440, 900,
                                         prefs=pref)
                    cls.drew[name] = desk.chart(sid)
                    cls.got[name] = json.loads(desk.js(sid, READ % json.dumps(CID)))
                    desk.close_tab(tid)
            finally:
                desk.close()

    def test_the_scenes_were_reached(self):
        for name, _sym, _tf in self.PAGES:
            with self.subTest(page=name):
                self.assertTrue(self.drew[name], "the chart drew")
                self.assertNotIn("error", self.got[name])
                self.assertEqual(self.got[name]["n"], 240, self.got[name])
        gold = self.got["gold_1min"]
        self.assertEqual((gold["family"], gold["standIn"]), ("yahoo", "future"))
        self.assertEqual(gold["now"], ETORO_ASK)
        self.assertEqual((gold["low"], gold["high"]), (4149.56, 4181.21))
        self.assertTrue(gold["caption"].startswith(
            "bars: Yahoo GC=F, the front-month future (another instrument)"
            " · price: eToro ask"), gold["caption"])
        self.assertEqual(self.got["gold_1h"]["family"], "etoro")
        self.assertEqual((self.got["eur_1min"]["family"],
                          self.got["eur_1min"]["standIn"]), ("yahoo", ""))
        self.assertIn(("XAUUSD", "1m", 240), self.feed.asked)

    def test_a_the_stand_in_s_candles_fill_the_pane(self):
        """(a) The candles fill at least 70 % of the pane (41 % before)."""
        g = self.got["gold_1min"]
        fill = (g["yLow"] - g["yHigh"]) / g["paneH"]
        self.assertGreaterEqual(fill, 0.70, g)

    def test_b_the_price_off_the_pane_is_pinned_to_its_edge(self):
        """(b) eToro's ask falls under the pane; a chip that names it sits
        inside the pane, above the volume band, with its arrow down."""
        g = self.got["gold_1min"]
        self.assertGreater(g["yNow"], g["paneH"], g)
        chips = [c for c in g["chips"] if "4124.54" in c["text"]]
        self.assertEqual(len(chips), 1, g["chips"])
        chip = chips[0]
        self.assertIn("eToro ask", chip["text"])
        self.assertIn("↓", chip["text"])
        self.assertEqual(chip["edge"], "bottom")
        self.assertGreaterEqual(chip["top"], 0)
        self.assertLessEqual(chip["bottom"], g["foot"] + 0.5, (chip, g["foot"]))

    def test_c_etoros_own_candles_keep_the_price_in_the_scale(self):
        g = self.got["gold_1h"]
        self.assertEqual(g["now"], ETORO_ASK)
        self.assertLess(g["now"], g["low"], "the price is under every candle")
        self.assertTrue(0 <= g["yNow"] <= g["paneH"], g)

    def test_d_a_same_instrument_feed_keeps_the_price_in_the_scale(self):
        g = self.got["eur_1min"]
        self.assertLess(g["now"], g["low"], "eToro's bid is under every candle")
        self.assertTrue(0 <= g["yNow"] <= g["paneH"], g)
