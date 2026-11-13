"""ONE PRICE EVERYWHERE: the review's fixes, measured in Chromium
(2026-11-12).

The real /positions/ page as the test client renders it (the shell, its
quote block, the painter; every other script stripped, the pattern of
tests/test_one_quote_browser), then one probe:

  * a region sweep rendered after a newer reading is swapped in: every
    cell shows the newer price, the Current cell included (measured on the
    branch: the painter put the page-load price back over it, because the
    sweep carried no quote block);
  * an identical sweep inserted into the region writes nothing outside it
    (one settle repainted every cell and every spark of the page, about
    4,100 attribute writes at 200 symbols);
  * the live region's comparison ignores what the painter itself wrote
    (every sweep swapped the table because of the painter's attributes);
  * the quote socket going down says so on the region chips ("live
    prices paused"), and its return asks the server for the regions
    again;
  * the move since entry is worked out again from the price shown;
  * a cell's hover follows the price;
  * a spark built after the page (the position card's) is drawn by the
    painter, with whose bars it draws.

And a small page for the two timings: a hidden tab settles when it comes
back, and a shut market's cells flip at its reopening by themselves; and
for the colour of the move since entry, which follows its sign.

Synthetic fixture (tests/one_quote_fixture.py). Skipped without Chromium.

Run with:  python manage.py test tests.test_one_quote_review_browser
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

from tests.one_quote_fixture import T, daily_bar, seed_measured, stamp
from tests.test_close_advice import CHROME, _Chrome


def _ms(dt):
    return int(round(dt.timestamp() * 1000))


PROBE = r"""(async function () {
    const M = __M__;
    function frame() {
        return new Promise(function (r) {
            requestAnimationFrame(function () { requestAnimationFrame(r); });
        });
    }
    const text = function (sel, root) {
        return Array.prototype.map.call((root || document).querySelectorAll(sel),
                                        function (e) { return e.textContent.trim(); });
    };
    await frame();
    const R = {};
    const region = document.querySelector('[data-sv-live="pos-open"]');
    const served = new DOMParser().parseFromString(M.page, 'text/html')
        .querySelector('[data-sv-live="pos-open"]');

    /* the live region's comparison: the painter's own writes do not count */
    R.canon = !!(window.SVVenue && SVVenue.canon);
    if (R.canon) {
        const a = region.cloneNode(true), b = served.cloneNode(true);
        SVVenue.canon(a); SVVenue.canon(b);
        R.canonEqual = a.innerHTML === b.innerHTML;
    }

    /* an identical sweep: nothing outside the region is written. Taken
       just after a second's age tick, so the next one (which rewrites the
       ages everywhere, as it should) is a second away. */
    const ageCell = Array.prototype.filter.call(
        document.querySelectorAll('[data-q-f="age"], [data-q-f="words"]'),
        function (e) { return !region.contains(e) && /\d s$/.test(e.textContent.trim()); })[0];
    if (ageCell) {
        const was = ageCell.textContent;
        for (let i = 0; i < 150 && ageCell.textContent === was; i++) {
            await new Promise(function (r) { setTimeout(r, 10); });
        }
    }
    const outside = [];
    const mo = new MutationObserver(function (rs) {
        rs.forEach(function (r) {
            const el = r.target.nodeType === 3 ? r.target.parentNode : r.target;
            if (el && !region.contains(el)) outside.push((el.className && el.className.baseVal !== undefined
                ? el.className.baseVal : el.className) + ':' + r.type + ':' + (r.attributeName || ''));
        });
    });
    mo.observe(document.body, { subtree: true, childList: true, characterData: true, attributes: true });
    region.innerHTML = served.innerHTML;
    await frame();
    mo.disconnect();
    R.outside = outside.slice(0, 20);
    R.outsideN = outside.length;

    /* the quote socket */
    R.socket = !!(window.SVVenue && SVVenue.socket);
    if (R.socket) {
        let asked = 0;
        window.svLiveRefresh = function () { asked++; };
        SVVenue.socket(true);                     /* the first open */
        R.firstOpenAsked = asked;
        SVVenue.socket(false);
        R.paused = document.body.classList.contains('sv-quotes-paused');
        const chip = document.querySelector('[data-sv-live-status]');
        R.chipWords = chip ? getComputedStyle(chip, '::after').content : null;
        SVVenue.socket(true);
        R.resumed = !document.body.classList.contains('sv-quotes-paused');
        R.asked = asked;
    }

    /* a spark built after the page */
    R.drawSpark = !!(window.SVVenue && SVVenue.drawSpark);
    if (R.drawSpark) {
        const box = document.createElement('div');
        box.className = 'pop-spark';
        box.setAttribute('data-q-spark', 'EURUSD');
        box.setAttribute('data-points', '1.08300,1.08480');
        box.setAttribute('data-q-fam', 'yahoo');
        box.setAttribute('data-q-bars', 'Yahoo EURUSD=X daily closes');
        box.setAttribute('data-w', '330'); box.setAttribute('data-h', '34');
        box.innerHTML = '<svg viewBox="0 0 330 34" preserveAspectRatio="none"><path d=""/></svg>';
        SVVenue.drawSpark(box);
        R.spark = { d: !!box.querySelector('path').getAttribute('d'),
                    dot: !!box.querySelector('circle[data-q-dot]'),
                    title: box.getAttribute('title') };
    }

    /* the sweep rendered after a newer reading */
    const doc = new DOMParser().parseFromString(M.sweep, 'text/html');
    SVVenue.ingestDoc(doc);                   /* what svDhIngest does first */
    region.innerHTML = doc.querySelector('[data-sv-live="pos-open"]').innerHTML;
    await frame();
    R.afterSweep = {
        current: text('[data-sv-live="pos-open"] [data-q="EURUSD"][data-q-side="bid"]:not([data-q-f])'),
        headband: text('.dh-item [data-q="EURUSD"]:not([data-q-f])'),
        since: text('[data-q="EURUSD"][data-q-f="since"]')
    };

    /* the hovers follow the price */
    await new Promise(function (r) { setTimeout(r, 1250); });
    const cur = document.querySelector('[data-sv-live="pos-open"] .pos-price[data-q="EURUSD"]');
    const hb = document.querySelector('.dh-item .dh-val[data-q="EURUSD"]');
    R.titles = { current: cur ? cur.title : null, headband: hb ? hb.title : null,
                 words: text('[data-sv-live="pos-open"] [data-q="EURUSD"][data-q-f="words"]')[0] };
    return JSON.stringify(R);
})()"""


@unittest.skipUnless(CHROME, "no headless Chromium on this machine")
class TheReviewsFixesInChromiumTests(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            "oq_review_browser", password="x", is_staff=True)
        self.rows = seed_measured(self.user)
        for days, close in ((2, "1.08300"), (1, "1.08480")):
            daily_bar("EURUSD", T - timedelta(days=days), close)
        from django.core.cache import cache
        cache.clear()
        from instruments.models import Instrument
        Instrument.objects.filter(symbol__in=("EURUSD", "GBPUSD", "XAUUSD",
                                              "AAPL")).update(is_watchlist=True)
        for patch in (mock.patch("django.utils.timezone.now", return_value=T),
                      mock.patch("market_data.one_quote.now", return_value=T)):
            patch.start()
            self.addCleanup(patch.stop)
        self.client.force_login(self.user)
        self.tmp = tempfile.mkdtemp(prefix="sv-oq-review-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    @staticmethod
    def _keep(m):
        """The painter and the quote blocks only, judged by the opening
        tag: an inline script that merely names sv-venue.js in a comment
        (the shell's socket, the live region) is stripped too, so nothing
        but the probe moves the page."""
        s = m.group(0)
        tag = s[:s.find(">") + 1]
        return s if ("data-sv-quotes" in tag or "sv-venue.js" in tag) else ""

    def _strip(self, html):
        html = re.sub(r"<script\b.*?</script>", self._keep, html, flags=re.S)
        html = re.sub(r'<link\b[^>]*href="https?://[^>]*>', "", html)
        return html.replace("/static/", "file://%s/static/" % settings.BASE_DIR)

    def test_the_reviews_fixes_on_the_positions_page(self):
        page = self.client.get("/positions/", HTTP_HOST="127.0.0.1").content.decode()
        page = self._strip(page)
        # a newer eToro reading, then the region sweep the page would fetch
        t = self.rows["EURUSD"]
        meta = dict(t.metadata)
        meta["venue_mark"] = stamp("1.08505", "1.08500", "1.08510", 2)
        t.metadata = meta
        t.save(update_fields=["metadata"])
        sweep = self.client.get("/positions/live/", HTTP_HOST="127.0.0.1",
                                HTTP_X_SV_SWEEP="1").content.decode()
        path = pathlib.Path(self.tmp) / "positions.html"
        path.write_text(page, encoding="utf-8")
        m = {"page": page, "sweep": sweep}
        chrome = _Chrome(CHROME)
        try:
            sid = chrome.page(1440, 900, False)
            chrome.open(sid, path.as_uri())
            got = json.loads(chrome.eval(sid, PROBE.replace("__M__", json.dumps(m))))
        finally:
            chrome.close()
        # MC6: the comparison sees the server's markup, not the painter's
        self.assertTrue(got["canon"], "SVVenue.canon")
        self.assertTrue(got["canonEqual"])
        # MC3: an identical sweep writes nothing outside its region
        self.assertEqual(got["outsideN"], 0, got["outside"])
        # C3: the quote socket
        self.assertTrue(got["socket"], "SVVenue.socket")
        self.assertEqual(got["firstOpenAsked"], 0, "the first open asks nothing")
        self.assertTrue(got["paused"])
        self.assertIn("live prices paused", got["chipWords"] or "")
        self.assertTrue(got["resumed"])
        self.assertEqual(got["asked"], 1, "the return asks for the regions")
        # C11: a spark built after the page
        self.assertTrue(got["drawSpark"], "SVVenue.drawSpark")
        self.assertEqual(got["spark"], {
            "d": True, "dot": True,
            "title": "Yahoo EURUSD=X daily closes · dot: eToro bid now"})
        # C2: the sweep's newer price stands, everywhere
        a = got["afterSweep"]
        self.assertEqual(set(a["current"]), {"1.08500"}, a)
        self.assertEqual(set(a["headband"]), {"1.08500"}, a)
        # C6: since entry from the price shown
        self.assertTrue(a["since"])
        self.assertEqual(set(a["since"]), {"+0.27% since entry"}, a)
        # C13: the hovers follow the price
        ti = got["titles"]
        self.assertTrue((ti["current"] or "").startswith(ti["words"]), ti)
        self.assertTrue(re.match(r"eToro bid · [34] s", ti["current"] or ""), ti)
        self.assertTrue((ti["headband"] or "").startswith("eToro bid · "), ti)


SMALL = """{% load quote_tags %}<!doctype html><html><head><meta charset="utf-8"></head><body>
<span id="px" data-q="EURUSD">{% q "EURUSD" %}</span>
<span id="wd" data-q="EURUSD" data-q-f="words">{% q "EURUSD" "words" %}</span>
<span id="since" class="pos-price-pct sign-up" data-q="EURUSD" data-q-f="since" data-q-side="bid" data-q-ref="1.09000">+0.10% since entry</span>
<div id="region"></div>
{% include "_partials/sv_venue.html" %}
</body></html>"""

SMALL_PROBE = r"""(async function () {
    const M = __M__;
    function frame() {
        return new Promise(function (r) {
            requestAnimationFrame(function () { requestAnimationFrame(r); });
        });
    }
    await frame();
    const R = {};
    /* the move since entry keeps its colour with its sign: the price
       (1.08447) is below the entry the cell carries (1.09000) */
    const sc = document.getElementById('since');
    R.since = { text: sc.textContent, up: sc.classList.contains('sign-up'),
                down: sc.classList.contains('sign-down') };
    /* a hidden tab: a region inserted while hidden waits for the return */
    let H = true;
    Object.defineProperty(document, 'hidden', { configurable: true, get: function () { return H; } });
    document.getElementById('region').innerHTML = '<span id="ins" data-q="EURUSD">1.00000</span>';
    await Promise.resolve();
    await new Promise(function (r) { setTimeout(r, 60); });
    R.hidden = document.getElementById('ins').textContent;
    H = false;
    document.dispatchEvent(new Event('visibilitychange'));
    await frame();
    R.back = document.getElementById('ins').textContent;

    /* a shut market reopens by the clock, on every tab, by itself */
    const p = Object.assign({}, SVVenue.get('EURUSD'));
    p.state = 'shut';
    p.shut = { since: SVVenue.now() - 3600000, label: 'market shut · opens Sun 22:00 UTC',
               opens: 'opens Sun 22:00 UTC', reopens: SVVenue.now() + 1500 };
    SVVenue.ingest(p, M.t + 1000);
    await frame();
    R.shut = { words: document.getElementById('wd').textContent,
               state: document.getElementById('px').getAttribute('data-q-state') };
    await new Promise(function (r) { setTimeout(r, 2600); });
    R.open = { words: document.getElementById('wd').textContent,
               state: document.getElementById('px').getAttribute('data-q-state') };
    return JSON.stringify(R);
})()"""


@unittest.skipUnless(CHROME, "no headless Chromium on this machine")
class TheTimingsInChromiumTests(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_user("oq_review_small",
                                                         password="x")
        seed_measured(self.user)
        self.clock = mock.patch("market_data.one_quote.now", return_value=T)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.tmp = tempfile.mkdtemp(prefix="sv-oq-small-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_a_hidden_tab_and_a_reopening(self):
        req = RequestFactory().get("/")
        req.user = self.user
        page = Template(SMALL).render(Context({"request": req}))
        page = page.replace("/static/", "file://%s/static/" % settings.BASE_DIR)
        path = pathlib.Path(self.tmp) / "small.html"
        path.write_text(page, encoding="utf-8")
        chrome = _Chrome(CHROME)
        try:
            sid = chrome.page(1024, 600, False)
            chrome.open(sid, path.as_uri())
            got = json.loads(chrome.eval(sid, SMALL_PROBE.replace(
                "__M__", json.dumps({"t": _ms(T)}))))
        finally:
            chrome.close()
        # C6: the figure beside the price, its sign and its colour
        self.assertEqual(got["since"], {"text": "-0.51% since entry",
                                        "up": False, "down": True})
        # MC7
        self.assertEqual(got["hidden"], "1.00000",
                         "nothing is settled in a hidden tab")
        self.assertEqual(got["back"], "1.08447", "settled on its return")
        # C17
        self.assertTrue(got["shut"]["words"].startswith("closed · eToro bid"),
                        got["shut"])
        self.assertEqual(got["shut"]["state"], "shut")
        self.assertTrue(got["open"]["words"].startswith("eToro bid · "),
                        got["open"])
        self.assertEqual(got["open"]["state"], "delayed")
