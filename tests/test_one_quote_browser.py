"""ONE PRICE EVERYWHERE, measured in Chromium (2026-11-12).

The one painter (static/js/sv-venue.js) in a real browser, on a page the
test client renders with the quote tags, its scripts stripped but the
painter's include, /static/ read from the disk (the pattern of
tests/test_close_advice.SelectionBarMeasuredTests). A probe then:

  1. reads every cell of a held and an unheld instrument;
  2. tags each mutation of a price cell with a frame counter and sends the
     display relay's own message: every cell shows the new price and
     words, and all their mutations carry ONE frame number;
  3. sends the same symbol with an older time: no cell mutates;
  4. swaps a region back to the page's own earlier render (with its quote
     block): the cells never step back;
  5. sends an OANDA tick for the instrument held at eToro: no cell moves;
     the same stream's tick for the unheld pair it wrote: every cell does;
  6. waits 1.2 s: the age has advanced by a second; a value 1000 s old
     reads stale.

Synthetic fixture (tests/one_quote_fixture.py). Skipped without Chromium.

Run with:  python manage.py test tests.test_one_quote_browser
"""
import json
import pathlib
import re
import shutil
import tempfile
import unittest
from datetime import timedelta
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.template import Context, Template
from django.test import RequestFactory, TestCase

from tests.one_quote_fixture import T, quote, seed_measured
from tests.test_close_advice import CHROME, _Chrome


def _ms(dt):
    return int(round(dt.timestamp() * 1000))


PAGE = """{% load quote_tags %}<!doctype html><html><head><meta charset="utf-8"></head><body>
<div id="shell">
 <span id="eur-hb" data-q="EURUSD">{% q "EURUSD" %}</span>
 <span id="eur-rail" data-q="EURUSD">{% q "EURUSD" %}</span>
 <span id="eur-words" data-q="EURUSD" data-q-f="words">{% q "EURUSD" "words" %}</span>
 <span id="gbp-hb" data-q="GBPUSD">{% q "GBPUSD" %}</span>
 <span id="gbp-words" data-q="GBPUSD" data-q-f="words">{% q "GBPUSD" "words" %}</span>
</div>
<div id="region">REGION</div>
{% include "_partials/sv_venue.html" %}
</body></html>"""

REGION = """{% load quote_tags %}<span id="eur-cur" data-q="EURUSD" data-q-side="bid">{% q "EURUSD" side="BUY" %}</span><span id="eur-cur-words" data-q="EURUSD" data-q-f="words" data-q-side="bid">{% q "EURUSD" "words" side="BUY" %}</span><span id="gbp-row" data-q="GBPUSD">{% q "GBPUSD" %}</span>{% q_json %}"""

PROBE = r"""(async function () {
    const M = __M__;
    function frame() {
        return new Promise(function (r) {
            requestAnimationFrame(function () { requestAnimationFrame(r); });
        });
    }
    const text = function (sel) {
        return Array.prototype.map.call(document.querySelectorAll(sel),
                                        function (e) { return e.textContent; });
    };
    await frame();
    const R = {};
    R.engine = !!window.SVVenue;
    R.before = { eur: text('[data-q="EURUSD"]:not([data-q-f])'),
                 eurWords: text('#eur-words')[0], eurCur: text('#eur-cur')[0],
                 gbp: text('[data-q="GBPUSD"]:not([data-q-f])') };
    let f = 0;
    (function loop() { f++; requestAnimationFrame(loop); })();
    const seen = [];
    new MutationObserver(function (rs) {
        rs.forEach(function (r) {
            const el = r.target.nodeType === 3 ? r.target.parentNode : r.target;
            if (el && el.matches && el.matches('[data-q="EURUSD"]:not([data-q-f])')) seen.push(f);
        });
    }).observe(document.body, { subtree: true, childList: true, characterData: true });

    SVVenue.tick(M.relay);
    await frame(); await frame();
    R.relay = { eur: text('[data-q="EURUSD"]:not([data-q-f])'),
                words: text('#eur-words')[0], curWords: text('#eur-cur-words')[0],
                frames: Array.from(new Set(seen)), n: seen.length };

    seen.length = 0;
    SVVenue.tick(M.older);
    await frame(); await frame();
    R.older = { eur: text('[data-q="EURUSD"]:not([data-q-f])'), n: seen.length };

    document.getElementById('region').innerHTML = M.oldRegion;
    await Promise.resolve();          /* the observer's microtask, no frame */
    R.swapNow = text('#eur-cur')[0];
    await frame();
    R.swap = { cur: text('#eur-cur')[0], words: text('#eur-cur-words')[0] };

    SVVenue.tick(M.heldTick);
    SVVenue.tick(M.gbpTick);
    await frame(); await frame();
    R.ticks = { eur: text('[data-q="EURUSD"]:not([data-q-f])'),
                gbp: text('[data-q="GBPUSD"]:not([data-q-f])') };

    const w0 = text('#eur-words')[0];
    await new Promise(function (r) { setTimeout(r, 1250); });
    R.aged = { before: w0, after: text('#eur-words')[0] };
    SVVenue.ingest(M.aged, M.agedT);
    await frame();
    R.stale = { words: text('#gbp-words')[0],
                cls: document.getElementById('gbp-words').className };
    return JSON.stringify(R);
})()"""


@unittest.skipUnless(CHROME, "no headless Chromium on this machine")
class TheEngineInChromiumTests(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_user("oq_browser",
                                                         password="x")
        self.clock = mock.patch("market_data.one_quote.now", return_value=T)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        seed_measured(self.user)
        quote("GBPUSD", "1.29410", "oanda_stream", 240, bid="1.29405",
              ask="1.29415", chg="-0.21")
        self.tmp = tempfile.mkdtemp(prefix="sv-oq-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _render(self, src, region=""):
        req = RequestFactory().get("/")
        req.user = self.user
        out = Template(src).render(Context({"request": req}))
        return out.replace("REGION", region)

    def _payload(self, sym):
        from market_data.one_quote import shown
        return shown(sym, user=self.user, now=T).payload()

    def _messages(self):
        eur = self._payload("EURUSD")
        newer = dict(eur, p="1.08460", v=1.0846, b="1.08460", a="1.08470",
                     at=_ms(T) - 2000)
        older = dict(eur, p="1.08300", v=1.083, b="1.08300", a="1.08310",
                     at=_ms(T) - 60000)

        def relay(p):
            return {"type": "quote", "data": {
                "symbol": "EURUSD", "price": p["p"], "source": "etoro",
                "change_pct": None, "t": _ms(T), "q": p}}
        gbp = self._payload("GBPUSD")
        iso = lambda dt: dt.isoformat()
        return {
            "relay": relay(newer), "older": relay(older),
            "heldTick": {"type": "quote_stream", "data": {
                "symbol": "EUR_USD", "last": 1.2, "bid": 1.19, "ask": 1.21,
                "source": "oanda_stream", "ts": iso(T + timedelta(seconds=5))}},
            "gbpTick": {"type": "quote_stream", "data": {
                "symbol": "GBP_USD", "last": 1.29455, "bid": 1.2945,
                "ask": 1.2946, "source": "oanda_stream",
                "ts": iso(T + timedelta(seconds=1))}},
            # the server's next render: Yahoo's row, 1000 s old (a switch
            # of source, rendered after the stream's value)
            "aged": dict(gbp, p="1.29300", v=1.293, b=None, a=None,
                         src="yfinance", fam="yahoo", who="Yahoo GBPUSD=X",
                         at=_ms(T) - 1000 * 1000, ls=None, state="delayed"),
            "agedT": _ms(T) + 60000,
        }

    def _url(self):
        region = self._render(REGION)
        page = self._render(PAGE, region)
        page = page.replace("/static/", "file://%s/static/" % settings.BASE_DIR)
        path = pathlib.Path(self.tmp) / "page.html"
        path.write_text(page, encoding="utf-8")
        return path.as_uri(), region

    def test_the_engine_in_a_browser(self):
        url, region = self._url()
        m = self._messages()
        m["oldRegion"] = region
        chrome = _Chrome(CHROME)
        try:
            sid = chrome.page(1280, 900, False)
            chrome.open(sid, url)
            got = json.loads(chrome.eval(sid, PROBE.replace(
                "__M__", json.dumps(m))))
        finally:
            chrome.close()
        self.assertTrue(got["engine"])
        b = got["before"]
        self.assertEqual(b["eur"], ["1.08447"] * 3)
        self.assertEqual(b["eurWords"], "eToro bid · 25 s")
        self.assertEqual(b["gbp"], ["1.29410"] * 2)
        r = got["relay"]
        self.assertEqual(r["eur"], ["1.08460"] * 3, "every cell, the relay's price")
        self.assertEqual(r["words"], "eToro bid · 2 s")
        self.assertEqual(r["curWords"], "eToro bid · 2 s")
        self.assertEqual(len(r["frames"]), 1, r)
        self.assertGreaterEqual(r["n"], 3)
        self.assertEqual(got["older"], {"eur": ["1.08460"] * 3, "n": 0},
                         "an older value moves nothing")
        self.assertEqual(got["swapNow"], "1.08460",
                         "repainted before the browser shows the swap")
        self.assertEqual(got["swap"], {"cur": "1.08460",
                                       "words": "eToro bid · 2 s"})
        self.assertEqual(got["ticks"]["eur"], ["1.08460"] * 3,
                         "an OANDA tick never paints eToro's price")
        self.assertEqual(got["ticks"]["gbp"], ["1.29455"] * 2)
        aged = got["aged"]
        self.assertNotEqual(aged["before"], aged["after"])
        self.assertTrue(re.match(r"eToro bid · [34] s", aged["after"]), aged)
        self.assertEqual(got["stale"]["words"], "Yahoo GBPUSD=X · 17 min")
        self.assertIn("sv-age--stale", got["stale"]["cls"])
