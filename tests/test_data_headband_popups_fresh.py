"""The data headband's cards say the current quote.

The operator, 2026-09-27: "also the data feed popup on hover, please put
them up to date".

What it was (templates/base.html and templates/_partials/dh_item.html on
3994ffc with the news-band hover fix):
  * every value in a data-headband card (.dh-pop) was server text rendered
    once at page load, and nothing ever wrote to it again: a tick repainted
    the cell beside it and left the card on the page load's price, day
    change, badge, bar, spread, volume, source and "Updated 4 seconds ago"
    — open or closed, first open or tenth, in both halves of the loop;
  * the shell's live-region sweep fetched a whole fresh render of the band
    every minute and threw it away;
  * no crypto or forex tick reached the band at all: the streamers
    broadcast BTCUSDT and EUR_USD, the band carries BTCUSD and EURUSD;
  * a 'quote' message (price, not last) painted 0.

These tests load the page's REAL inline scripts — the WebSocket block
(applyTick and the card sync), the UPGRADE-9 popup engine (the portal that
moves an open card to <body>), the shell's live-region sweep exactly as
Django renders it for the shell, and the spark renderer — under node,
against the data headband exactly as Django renders it, on the minimal DOM
of tests/test_headband_hover_lives.py, with a fake clock, a fake fetch and
a fake socket. Ticks go through the page's own socket handler; the periodic
refresh through the sweep's own timer, fetch and apply(). A hand opens a
card, a tick or a sweep lands, the card is read open, closed, reopened and
in the loop's other half. Every test that reads a value fails on 3994ffc;
the three guards (the page runs clean, the page load's card is the
baseline, nothing is bound per item) hold on both.

Run with:  python manage.py test tests.test_data_headband_popups_fresh
"""
import asyncio
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.test import RequestFactory, SimpleTestCase, TestCase

from tests.test_headband_hover_lives import DOM_JS

NODE = shutil.which("node")
DJANGO_TAG_RE = re.compile(r"\{%|\{\{")
BANDS_FROM = "<!-- Ticker Bar (fixed, always visible) -->"
BANDS_TO = "<!-- Info Bar (fixed, labels always visible, hover for dropdowns) -->"
# The blocks the band runs on, found by their own words.
SCRIPTS = (
    ("websocket+applyTick", "UPGRADE-3: WebSocket live ticks."),
    ("upgrade9-popup-engine", "UPGRADE-9: headband popup escape + hover arrows"),
)
SPARKS_FROM = "/* Phase 62 — render sparkline paths from data-points attrs."
LIVE_URL = "/getting-started/"



def _moments():
    """Taken when the page runs, not when the module is imported: a card
    says "just now" of a tick seconds old, and the runner may reach this
    class minutes after discovery."""
    now = datetime.now(dt_timezone.utc).replace(microsecond=123456)
    return {
        "load": now - timedelta(minutes=10),   # the records the page rendered
        "tick": now,                           # every socket tick here
        "sweep": now - timedelta(seconds=5),   # the sweep's newer records
        "old": now - timedelta(seconds=60),    # a sweep record older than a tick
    }


def _clock(t):
    return t.astimezone(dt_timezone.utc).strftime("%H:%M:%S")


def _quote(symbol, asset_class, last, pct, at, source, bid=None, ask=None,
           volume=0, spark=None):
    """One ui_headband entry, the shape core/context_ui.py builds."""
    spark = spark or []
    return {
        "symbol": symbol, "name": symbol + " name", "last": last,
        "change_pct": pct, "asset_class": asset_class, "volume": volume,
        "bid": bid, "ask": ask, "source": source,
        "updated": at.isoformat(), "updated_utc": _clock(at),
        "updated_human": "10 minutes ago", "spark": spark,
        "spark_min": min(spark) if spark else 0,
        "spark_max": max(spark) if spark else 0,
    }


def _no_quote(symbol):
    return {"symbol": symbol, "last": None, "change_pct": 0, "name": symbol,
            "asset_class": "", "volume": 0, "updated": "", "spark": [],
            "spark_min": 0, "spark_max": 0}


def _band_at_load(t):
    return [
        _quote("EURUSD", "forex", 1.1, 0.5, t["load"], "oanda", 1.0999,
               1.1001, 1000, [1.0, 1.05, 1.1]),
        _quote("USDJPY", "forex", 148.1, -0.2, t["load"], "oanda", 148.09,
               148.11),
        _quote("BTCUSD", "crypto", 60000.0, 1.5, t["load"], "binance_ws",
               59999.0, 60001.0, 5000, [58000.0, 59000.0, 60000.0]),
        _quote("XAUUSD", "commodity", 2400.5, 0.1, t["load"], "yfinance",
               2400.0, 2401.0),
        _no_quote("GBPUSD"),
    ]


def _band_at_sweep(t):
    """What /getting-started/ renders a minute later: EURUSD moved (a newer
    record), USDJPY did not (the same record), BTCUSD's record is OLDER
    than the tick the page already has, XAUUSD's is newer but only its
    source and spread changed."""
    return [
        _quote("EURUSD", "forex", 1.2, 0.75, t["sweep"], "yfinance", 1.1999,
               1.2001, 1000, [1.0, 1.1, 1.2, 1.3]),
        _quote("USDJPY", "forex", 148.1, -0.2, t["load"], "oanda", 148.09,
               148.11),
        _quote("BTCUSD", "crypto", 59000.0, -2.0, t["old"], "binance_ws",
               58999.0, 59001.0, 5000, [58000.0, 59000.0, 60000.0]),
        _quote("XAUUSD", "commodity", 2400.5, 0.1, t["sweep"], "oanda_rest",
               2400.2, 2400.8),
        _no_quote("GBPUSD"),
    ]


def _base():
    return (Path(settings.BASE_DIR) / "templates" / "base.html").read_text(
        encoding="utf-8")


def _inputs(t):
    """The bands as Django renders them, the answer the sweep gets, and the
    script blocks verbatim: base.html's own, the spark renderer's IIFE and
    the shell's live-region sweep as the shell renders it."""
    from django.template import engines
    from django.template.loader import render_to_string
    eng = engines["django"]
    raw = _base()
    bands = eng.from_string("{% load sauron_tags %}"
                            + raw[raw.index(BANDS_FROM):raw.index(BANDS_TO)])
    page = (bands.render({"ticker_items": [], "ui_headband": _band_at_load(t)})
            + '<main id="elsewhere"><p id="page-text">The page</p></main>')
    sweep = bands.render({"ticker_items": [], "ui_headband": _band_at_sweep(t)})
    blocks = re.findall(r"<script>(.*?)</script>", raw, re.S)
    scripts = []
    start = raw.index(SPARKS_FROM)
    end = raw.index("\n})();", start) + len("\n})();")
    scripts.append({"label": "base.html spark renderer",
                    "source": raw[start:end]})
    live = render_to_string("_partials/live_region.html",
                            {"live_url": LIVE_URL})
    live_js = re.findall(r"<script>(.*?)</script>", live, re.S)
    assert len(live_js) == 1, "live_region.html: %d scripts" % len(live_js)
    scripts.append({"label": "live_region.html (the shell's sweep)",
                    "source": live_js[0]})
    for label, marker in SCRIPTS:
        hits = [b for b in blocks if marker in b]
        assert len(hits) == 1, "%s: %d blocks" % (label, len(hits))
        scripts.append({"label": "base.html " + label, "source": hits[0]})
    for s in scripts:
        assert not DJANGO_TAG_RE.search(s["source"]), s["label"] + " has tags"
    return {"page": page, "sweep": sweep, "scripts": scripts,
            "live_url": LIVE_URL, "t_tick": t["tick"].isoformat()}


# ── the page: a fake clock, a fake fetch, a fake socket, a hand ───────────
RUN_JS = r"""
'use strict';
const vm = require('vm'), fs = require('fs'), path = require('path');
const D = require(path.join(__dirname, 'dom.js'));
const IN = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const settle = async () => { for (let i = 0; i < 8; i++) await new Promise(r => setImmediate(r)); };
const norm = s => String(s == null ? '' : s).replace(/\s+/g, ' ').trim();

function boot() {
  D.reset();
  const doc = new D.Document();
  doc.body.innerHTML = IN.page;
  let now = 0, seq = 0;
  const timers = new Map(), errors = [], sockets = [], store = {}, fetched = [];
  const st = (f, ms, ...a) => { const id = ++seq; timers.set(id, { at: now + Math.max(0, +ms || 0), f, a, every: 0 }); return id; };
  const si = (f, ms, ...a) => { const id = ++seq; const every = Math.max(1, +ms || 0); timers.set(id, { at: now + every, f, a, every }); return id; };
  const clr = id => { timers.delete(id); };
  const later = (ms, v) => new Promise(res => { st(() => res(v), ms); });
  /* The sweep's endpoint answers the fresh render; anything else is a 404
     the page already handles. */
  const fetch = (url) => {
    fetched.push(String(url));
    if (String(url) === IN.live_url) {
      return later(0, { ok: true, status: 200, redirected: false, text: () => Promise.resolve(IN.sweep) });
    }
    return Promise.resolve({ ok: false, status: 404, redirected: false,
      text: () => Promise.resolve(''), json: () => Promise.reject(new Error('404')) });
  };
  class WS { constructor(u) { this.url = u; sockets.push(this); } close() { if (this.onclose) this.onclose({}); } send() {} }
  /* The sweep parses its answer with DOMParser: the same minimal DOM. */
  class DOMParser { parseFromString(html) { const d = new D.Document(); d.body.innerHTML = String(html); return d; } }
  const reg = [];
  const win = {
    document: doc, console: { log() {}, warn() {}, error() {}, debug() {}, info() {} },
    setTimeout: st, clearTimeout: clr, setInterval: si, clearInterval: clr,
    requestAnimationFrame: f => st(f, 16), cancelAnimationFrame: clr,
    fetch, WebSocket: WS, DOMParser, CustomEvent: D.CustomEvent, Event: D.Event,
    location: { protocol: 'http:', host: 'localhost:8000', pathname: '/', search: '', reload() {}, assign() {} },
    localStorage: { getItem: k => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = String(v); }, removeItem: k => { delete store[k]; } },
    innerWidth: 1920, innerHeight: 1080, navigator: { userAgent: 'node' },
    getComputedStyle: el => el.style,
    matchMedia: () => ({ matches: false, addEventListener() {}, addListener() {} }),
    SV: { popup: { opened: p => { if (reg.indexOf(p) < 0) reg.push(p); },
                   closed: p => { const i = reg.indexOf(p); if (i >= 0) reg.splice(i, 1); } } },
    SV_HOVER_BEAT_MS: 450,
    _l: {},
  };
  win.addEventListener = D.Element.prototype.addEventListener;
  win.removeEventListener = D.Element.prototype.removeEventListener;
  win.window = win; win.self = win;
  doc.defaultView = win;
  const ctx = vm.createContext(win);
  for (const s of IN.scripts) {
    try { vm.runInContext(s.source, ctx, { filename: s.label }); }
    catch (e) { errors.push('LOAD ' + s.label + ': ' + (e && e.stack || e)); }
  }
  const page = () => doc.getElementById('page-text');
  const W = {
    doc, win,
    get now() { return now; },
    fetched: () => fetched.slice(),
    errors: () => errors.concat(D.errors()),
    async advance(ms) {
      const end = now + ms;
      for (;;) {
        let best = null;
        for (const [id, t] of timers) if (t.at <= end && (!best || t.at < best.t.at || (t.at === best.t.at && id < best.id))) best = { id, t };
        if (!best) break;
        now = best.t.at;
        if (best.t.every) best.t.at += best.t.every; else timers.delete(best.id);
        try { best.t.f(...best.t.a); } catch (e) { errors.push('TIMER: ' + (e && e.stack || e)); }
        await settle();
      }
      now = end; await settle();
    },
    async advanceTo(t) { if (t > now) await W.advance(t - now); },
    /* The hand moves: boundary events as a browser sends them. */
    pointTo(el) {
      const chain = n => { const a = []; while (n && n.nodeType === 1) { a.push(n); n = n.parentNode; } return a; };
      const old = D.getPointer();
      const oldLive = old && old.isConnected ? old : null;
      const oldC = oldLive ? chain(oldLive) : [];
      const newC = el ? chain(el) : [];
      if (oldLive) D.dispatch(oldLive, new D.Event('mouseout', { bubbles: true, relatedTarget: el }));
      oldC.filter(n => !newC.includes(n)).forEach(n => D.dispatch(n, new D.Event('mouseleave', { relatedTarget: el })));
      D.setPointer(el);
      if (el) D.dispatch(el, new D.Event('mouseover', { bubbles: true, relatedTarget: oldLive }));
      newC.filter(n => !oldC.includes(n)).reverse().forEach(n => D.dispatch(n, new D.Event('mouseenter', { relatedTarget: oldLive })));
    },
    async open(item) { W.pointTo(page()); await W.advance(400); W.pointTo(item.querySelector('span') || item); await W.advance(500); },
    async leave() { W.pointTo(page()); await W.advance(400); },
    items() { const t = doc.getElementById('dhTrack'); return t ? t.children.filter(e => e.matches('.dh-item')) : []; },
    by(sym, half) { return W.items().filter(e => e.getAttribute('data-symbol') === sym)[half]; },
    cards() { return doc.body.children.filter(p => p.matches('.dh-pop') && p.style.display === 'block'); },
    wsSend(msg) { const s = sockets[sockets.length - 1]; s.onmessage({ data: JSON.stringify(msg) }); },
  };
  return W;
}

/* What a reader sees in an item's card, wherever the card is — read by
   the card's own classes and row labels, so the page as it was reads too. */
function snap(item) {
  const pop = item.querySelector('.dh-pop') || item._portalPop;
  const one = sel => (pop ? pop.querySelector(sel) : null);
  const txt = sel => { const n = one(sel); return n ? norm(n.textContent) : null; };
  const rows = {};
  (pop ? pop.querySelectorAll('.dh-pop-row') : []).forEach(r => {
    const k = r.querySelector('.k'), v = r.querySelector('.v');
    if (k && v) rows[norm(k.textContent)] = norm(v.textContent);
  });
  const row = k => (rows[k] === undefined ? null : rows[k]);
  const pct = one('.dh-pop-pct'), badge = one('.dh-pop-badge'), bar = one('.dh-pop-bar-fill');
  const age = one('[data-sv-at]'), spark = one('.pop-spark');
  const sparkPath = spark && spark.querySelector('path');
  const cell = item.querySelector('.dh-val');
  return {
    open: !!pop && pop.parentNode === item.ownerDocument.body && pop.style.display === 'block',
    price: txt('.dh-pop-price'), pct: txt('.dh-pop-pct'),
    pct_class: pct ? pct.className : null, pct_color: pct ? pct.style.color : null,
    badge: txt('.dh-pop-badge'), badge_class: badge ? badge.className : null,
    bar_width: bar ? bar.style.width : null,
    volume: row('24h volume'), bidask: row('Bid / Ask'), source: row('Source'),
    as_of: row('As of') !== null ? row('As of') : row('Updated'),
    age_at: age ? age.getAttribute('data-sv-at') : null,
    age_text: age ? norm(age.textContent) : null,
    spark_points: spark ? spark.getAttribute('data-points') : null,
    spark_up: spark ? spark.getAttribute('data-up') : null,
    spark_path: sparkPath ? sparkPath.getAttribute('d') : null,
    cell: cell ? norm(cell.textContent) : null,
    cell_chg: norm((item.querySelector('.dh-chg') || {}).textContent),
    cell_flash: cell ? cell.style.textShadow : null,
  };
}

/* Socket ticks, each in the spelling its streamer really sends, landing
   under an open card, before a reopen, in the loop's other half. */
async function ticks() {
  const W = boot();
  const out = {};
  const items = W.items();
  const eu1 = W.by('EURUSD', 0), eu2 = W.by('EURUSD', 1);
  const pop1 = eu1.querySelector('.dh-pop');
  out.second_copy_in_second_half = items.indexOf(eu2) >= items.length / 2;
  out.load = snap(eu1);
  await W.open(eu1);
  out.open_before = snap(eu1);
  W.wsSend({ type: 'quote_stream', data: { symbol: 'EUR_USD', last: 1.25432, change_pct: null,
    bid: 1.2543, ask: 1.25434, source: 'oanda_stream', ts: IN.t_tick } });
  await W.advance(10);
  out.open_during = snap(eu1);
  out.second_half_cell_during = snap(eu2).cell;
  await W.leave();
  out.closed_after = snap(eu1);
  out.card_back_in_its_item = pop1.parentNode === eu1;
  await W.open(eu1);
  out.reopened = snap(eu1);
  out.same_card_node = (eu1.querySelector('.dh-pop') || eu1._portalPop) === pop1;
  await W.leave();
  await W.open(eu2);
  out.second_half = snap(eu2);
  await W.leave();
  const bt2 = W.by('BTCUSD', 1);
  await W.open(bt2);
  W.wsSend({ type: 'quote_stream', data: { symbol: 'BTCUSDT', last: 65432.1, change_pct: -1.25,
    bid: 65432.0, ask: 65432.2, volume: 12345.6, source: 'binance_ws', ts: IN.t_tick } });
  await W.advance(10);
  out.btc_open_second_half = snap(bt2);
  await W.leave();
  out.btc_first_half = snap(W.by('BTCUSD', 0));
  const jp = W.by('USDJPY', 0);
  await W.open(jp);
  W.wsSend({ type: 'quote_stream', data: { symbol: 'USD_JPY', last: 148.3254, change_pct: null,
    bid: 148.325, ask: 148.327, source: 'oanda_stream', ts: IN.t_tick } });
  await W.advance(10);
  out.jpy_open = snap(jp);
  await W.leave();
  /* push_quote_update's shape: price, not last; no time, source or spread. */
  W.wsSend({ type: 'quote', data: { symbol: 'EURUSD', price: '1.3', change_pct: '0.25' } });
  await W.advance(10);
  out.quote_message = snap(eu1);
  W.wsSend({ type: 'quote', data: { symbol: 'EURUSD', change_pct: '9.99' } });
  W.wsSend({ type: 'quote_stream', data: { symbol: 'EURUSD', last: 0, change_pct: 5 } });
  await W.advance(10);
  out.no_price = snap(eu1);
  const gb = W.by('GBPUSD', 1);
  out.empty_at_load = snap(gb);
  W.wsSend({ type: 'quote_stream', data: { symbol: 'GBP_USD', last: 1.33333, change_pct: null,
    bid: 1.3333, ask: 1.33336, source: 'oanda_stream', ts: IN.t_tick } });
  await W.advance(10);
  out.empty_filled = snap(gb);
  out.items_with_listeners = items.filter(e => Object.keys(e._l).some(k => e._l[k].length)).length;
  out.cards_open = W.cards().length;
  out.errors = W.errors();
  return out;
}

/* The periodic refresh: the shell's own sweep, its own timer and fetch,
   with a card open on the moving symbol and a tick already newer than one
   of the records it brings. */
async function sweep() {
  const W = boot();
  const out = {};
  const track = W.doc.getElementById('dhTrack');
  const kids = track ? track.children.slice() : [];
  const eu1 = W.by('EURUSD', 0), eu2 = W.by('EURUSD', 1);
  out.load = snap(eu1);
  await W.advance(10000);
  W.wsSend({ type: 'quote_stream', data: { symbol: 'BTCUSDT', last: 61000.5, change_pct: 2.0,
    bid: 61000.4, ask: 61000.6, volume: 7000, source: 'binance_ws', ts: IN.t_tick } });
  await W.advance(10);
  out.btc_after_tick = snap(W.by('BTCUSD', 0));
  await W.open(eu1);
  out.open_before = snap(eu1);
  await W.advanceTo(20100);           // the sweep fires at 20 s
  out.sweeps = W.fetched().filter(u => u === IN.live_url).length;
  out.open_during = snap(eu1);
  out.second_half = snap(eu2);
  out.btc = snap(W.by('BTCUSD', 0));
  out.btc_second_half = snap(W.by('BTCUSD', 1));
  out.xau = snap(W.by('XAUUSD', 0));
  out.jpy = snap(W.by('USDJPY', 0));
  out.items_kept = !!track && track.children.length === kids.length
    && track.children.every((c, i) => c === kids[i]);
  await W.leave();
  out.cards_open_after_leaving = W.cards().length;
  await W.advanceTo(40100);           // the next sweep: the same answer
  out.sweeps_at_end = W.fetched().filter(u => u === IN.live_url).length;
  out.after_same_answer = snap(eu1);
  out.errors = W.errors();
  return out;
}

(async () => {
  const out = {};
  out.ticks = await ticks();
  out.sweep = await sweep();
  process.stdout.write(JSON.stringify(out));
})().catch(e => { console.error(e && e.stack || e); process.exit(1); });
"""


def _report(t):
    tmp = Path(tempfile.mkdtemp(prefix="sv-dhpop-"))
    try:
        (tmp / "dom.js").write_text(DOM_JS, encoding="utf-8")
        (tmp / "run.js").write_text(RUN_JS, encoding="utf-8")
        (tmp / "input.json").write_text(json.dumps(_inputs(t)), encoding="utf-8")
        proc = subprocess.run([NODE, str(tmp / "run.js"), str(tmp / "input.json")],
                              capture_output=True, text=True, timeout=300,
                              encoding="utf-8")
        if proc.returncode != 0:
            raise AssertionError("the page runner failed: %s" % proc.stderr[:3000])
        return json.loads(proc.stdout)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@unittest.skipUnless(NODE, "node is not installed on this machine")
class TheCardsFollowTheQuoteTests(SimpleTestCase):
    """The page's own scripts, as shipped: socket ticks and the sweep."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.t = _moments()
        cls.report = _report(cls.t)

    def _dump(self, *keys):
        r = self.report
        for k in keys:
            r = r[k]
        return json.dumps(r, indent=1, ensure_ascii=False)[:6000]

    def assertCard(self, got, want, where):
        for key, value in want.items():
            with self.subTest(where=where, field=key):
                self.assertEqual(got[key], value, "%s — %s:\n%s" % (
                    where, key, json.dumps(got, indent=1, ensure_ascii=False)))

    def test_the_page_ran_clean(self):
        for part in ("ticks", "sweep"):
            with self.subTest(part=part):
                self.assertEqual(self.report[part]["errors"], [])

    def test_the_card_rendered_at_load_is_the_page_loads_quote(self):
        """The baseline the rest moves away from."""
        self.assertCard(self.report["ticks"]["load"], {
            "price": "1.10000", "pct": "+0.50%", "badge": "▲",
            "bidask": "1.09990 / 1.10010", "volume": "1000",
            "source": "oanda", "cell": "1.10000",
        }, "page load")
        self.assertTrue(self.report["ticks"]["second_copy_in_second_half"])

    def test_an_open_card_shows_the_tick_that_lands_under_it(self):
        """The first stale step: a tick while the operator reads the card.
        OANDA's own spelling (EUR_USD), its own day change (none: the
        card keeps the one it had), its spread, source and time."""
        r = self.report["ticks"]
        self.assertTrue(r["open_before"]["open"], self._dump("ticks", "open_before"))
        self.assertCard(r["open_during"], {
            "open": True, "price": "1.25432", "pct": "+0.50%",
            "bidask": "1.25430 / 1.25434", "source": "oanda_stream",
            "as_of": "%s UTC · just now" % _clock(self.t["tick"]),
            "age_at": self.t["tick"].isoformat(), "cell": "1.25432",
        }, "open card, tick under it")
        self.assertEqual(r["second_half_cell_during"], "1.25432")

    def test_a_closed_card_reopens_on_the_new_quote(self):
        """The card goes back into its item when the hand leaves — the
        same node, carrying the new quote, and the next open shows it."""
        r = self.report["ticks"]
        self.assertTrue(r["card_back_in_its_item"])
        self.assertTrue(r["same_card_node"])
        for step in ("closed_after", "reopened"):
            self.assertCard(r[step], {
                "price": "1.25432", "bidask": "1.25430 / 1.25434",
                "source": "oanda_stream",
                "as_of": "%s UTC · just now" % _clock(self.t["tick"]),
            }, step)
        self.assertTrue(r["reopened"]["open"])

    def test_the_loops_second_half_shows_it_too(self):
        """Each half owns its own card; both follow the quote."""
        r = self.report["ticks"]
        self.assertCard(r["second_half"], {
            "open": True, "price": "1.25432", "pct": "+0.50%",
            "bidask": "1.25430 / 1.25434", "source": "oanda_stream",
            "as_of": "%s UTC · just now" % _clock(self.t["tick"]), "cell": "1.25432",
        }, "second half")

    def test_every_value_in_the_card_follows_a_falling_tick(self):
        """Binance's spelling (BTCUSDT), under the second half's open card:
        price, day change and its colour, badge, bar, spread, volume,
        source, time and the spark's tone."""
        r = self.report["ticks"]
        want = {
            "price": "65432.10", "pct": "-1.25%",
            "pct_class": "dh-pop-pct down", "pct_color": "var(--accent-red)",
            "badge": "▼", "badge_class": "dh-pop-badge down",
            "bar_width": "0%", "bidask": "65432.00 / 65432.20",
            "volume": "12346", "source": "binance_ws",
            "as_of": "%s UTC · just now" % _clock(self.t["tick"]),
            "spark_up": "0", "cell": "65432.10", "cell_chg": "-1.25%",
        }
        self.assertCard(r["btc_open_second_half"], dict(want, open=True),
                        "BTCUSDT tick, open card, second half")
        self.assertCard(r["btc_first_half"], want, "BTCUSDT tick, first half")

    def test_the_precision_is_the_items_own_even_on_body(self):
        """An open card sits on <body>, outside every [data-decimals]: a
        JPY cross still reads three decimals, not the magnitude rule's
        two."""
        self.assertCard(self.report["ticks"]["jpy_open"], {
            "open": True, "price": "148.325", "bidask": "148.325 / 148.327",
            "cell": "148.325",
        }, "USD_JPY tick, open card")

    def test_no_time_source_or_spread_is_invented(self):
        """A 'quote' message says price (not last) and nothing else: the
        card shows the price, and "—" for what the message did not say —
        never the last record's, never the browser's clock."""
        self.assertCard(self.report["ticks"]["quote_message"], {
            "price": "1.30000", "pct": "+0.25%", "cell": "1.30000",
            "bidask": "—", "source": "—", "as_of": "—", "age_at": None,
        }, "'quote' message")

    def test_a_tick_without_a_price_paints_nothing(self):
        r = self.report["ticks"]
        self.assertCard(r["no_price"], {
            "price": "1.30000", "pct": "+0.25%", "cell": "1.30000",
        }, "no price")

    def test_a_card_empty_at_load_fills_from_a_tick(self):
        """No quote at load: every row "—", the spread row included — and
        the first tick fills it."""
        r = self.report["ticks"]
        self.assertCard(r["empty_at_load"], {
            "price": "—", "bidask": "—", "source": "—", "as_of": "—",
        }, "no quote at load")
        filled = r["empty_filled"]
        self.assertCard(filled, {
            "source": "oanda_stream",
            "as_of": "%s UTC · just now" % _clock(self.t["tick"]),
        }, "GBP_USD tick")
        # A quote-less item has no asset class at render, so its precision
        # is the magnitude rule's — the cell's, whatever it is: the card
        # reads what the cell reads.
        self.assertTrue(filled["price"].startswith("1.33"), filled)
        self.assertEqual(filled["price"], filled["cell"])
        self.assertNotEqual(filled["bidask"], "—")

    def test_nothing_is_bound_per_item_and_no_card_is_left_open(self):
        r = self.report["ticks"]
        self.assertEqual(r["items_with_listeners"], 0)
        self.assertEqual(r["cards_open"], 0)

    def test_the_sweep_brings_the_fresh_quote_to_an_open_card_and_both_halves(self):
        """The periodic refresh: the shell's sweep fetched a whole fresh
        render of the band every minute and threw it away."""
        r = self.report["sweep"]
        self.assertGreaterEqual(r["sweeps"], 1)
        self.assertTrue(r["open_before"]["open"], self._dump("sweep", "open_before"))
        want = {
            "price": "1.20000", "pct": "+0.75%", "badge": "▲",
            "bar_width": "8%", "bidask": "1.19990 / 1.20010",
            "source": "yfinance", "age_at": self.t["sweep"].isoformat(),
            "as_of": "%s UTC · just now" % _clock(self.t["sweep"]),
            "cell": "1.20000", "cell_chg": "+0.75%",
        }
        self.assertCard(r["open_during"], dict(want, open=True),
                        "open card, sweep under it")
        self.assertCard(r["second_half"], want, "second half, sweep")
        self.assertTrue(r["items_kept"], "the band's items were replaced")
        self.assertEqual(r["cards_open_after_leaving"], 0)

    def test_an_older_record_never_overwrites_a_newer_tick(self):
        r = self.report["sweep"]
        want = {"price": "61000.50", "cell": "61000.50", "pct": "+2.00%",
                "source": "binance_ws", "volume": "7000",
                "as_of": "%s UTC · just now" % _clock(self.t["tick"])}
        self.assertCard(r["btc_after_tick"], want, "BTCUSDT tick")
        self.assertCard(r["btc"], want, "after a sweep with an older record")
        self.assertCard(r["btc_second_half"], want, "second half")

    def test_only_what_moved_moves(self):
        """A newer record with the same price refreshes the card's time,
        source and spread without flashing the cell; the same record
        changes nothing; the moved price flashes once."""
        r = self.report["sweep"]
        self.assertTrue(r["open_during"]["cell_flash"],
                        "the moved price did not flash")
        self.assertCard(r["xau"], {
            "price": "2400.50", "cell": "2400.50", "cell_flash": "",
            "source": "oanda_rest", "bidask": "2400.20 / 2400.80",
            "as_of": "%s UTC · just now" % _clock(self.t["sweep"]),
        }, "XAUUSD: newer record, same price")
        self.assertCard(r["jpy"], {
            "price": "148.100", "cell": "148.100", "cell_flash": "",
            "as_of": "%s UTC · 10 minutes ago" % _clock(self.t["load"]),
        }, "USDJPY: the same record")
        self.assertGreaterEqual(r["sweeps_at_end"], 2)
        self.assertCard(r["after_same_answer"], {
            "price": "1.20000", "cell_flash": "",
            "as_of": "%s UTC · just now" % _clock(self.t["sweep"]),
        }, "the same answer again")

    def test_fresh_closes_redraw_the_spark(self):
        r = self.report["sweep"]
        self.assertEqual(r["open_during"]["spark_points"],
                         "1.000000,1.100000,1.200000,1.300000")
        self.assertTrue(r["load"]["spark_path"])
        self.assertNotEqual(r["open_during"]["spark_path"], r["load"]["spark_path"])


class TheCardSaysWhenTests(TestCase):
    """The card's time is the record's, on the UTC clock face, with an age
    SV.ages keeps true — not a relative string frozen at render."""

    def setUp(self):
        from instruments.models import Instrument
        from market_data.models import LiveQuote
        self.inst = Instrument.objects.create(
            symbol="EURUSD", name="Euro / Dollar", asset_class="forex",
            is_active=True)
        self.q = LiveQuote.objects.create(
            instrument=self.inst, last=Decimal("1.08425"),
            bid=Decimal("1.08420"), ask=Decimal("1.08430"),
            change_pct=Decimal("0.4200"), volume=1234, source="oanda")

    def _band(self):
        from core.context_ui import ui_extras
        band = ui_extras(RequestFactory().get("/"))["ui_headband"]
        return {m["symbol"]: m for m in band}

    def test_the_context_carries_the_utc_clock(self):
        m = self._band()["EURUSD"]
        self.q.refresh_from_db()
        self.assertEqual(m["updated"], self.q.updated_at.isoformat())
        self.assertEqual(m["updated_utc"], _clock(self.q.updated_at))

    def test_the_item_carries_its_record_and_the_card_its_hooks(self):
        from django.template.loader import render_to_string
        m = self._band()["EURUSD"]
        html = render_to_string("_partials/dh_item.html", {"m": m})
        for attr in ('data-last="1.08425"', 'data-pct="0.4200"',
                     'data-bid="1.08420"', 'data-ask="1.08430"',
                     'data-vol="1234"', 'data-src="oanda"',
                     'data-at="%s"' % m["updated"]):
            self.assertIn(attr, html)
        for hook in ("badge", "price", "pct", "bidask", "vol", "src",
                     "asof", "age", "bar"):
            self.assertIn('data-dh-f="%s"' % hook, html)
        self.assertIn(">%s UTC ·</span>" % m["updated_utc"], html)
        self.assertIn('data-sv-at="%s"' % m["updated"], html)
        self.assertNotIn(">Updated<", html)

    def test_no_quote_no_time(self):
        from django.template.loader import render_to_string
        html = render_to_string("_partials/dh_item.html", {"m": {
            "symbol": "GBPUSD", "last": None, "change_pct": 0,
            "name": "GBPUSD", "asset_class": "", "volume": 0,
            "updated": "", "spark": []}})
        self.assertIn('data-at=""', html)
        self.assertNotIn("data-sv-at", html)
        self.assertIn('<span data-dh-f="asof">—</span>', html)
        self.assertIn('<span class="v" data-dh-f="bidask">—</span>', html)


class TheStreamsSayWhenAndFromWhereTests(SimpleTestCase):
    """A card never invents a quote's time or source, so the ticks that
    reach the band carry them."""

    def _sent(self, fn, *args):
        sent = []

        class Layer:
            async def group_send(self, group, msg):
                sent.append((group, msg))

        with mock.patch("channels.layers.get_channel_layer",
                        return_value=Layer()):
            asyncio.run(fn(*args))
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0][0], "dashboard_live")
        self.assertEqual(sent[0][1]["type"], "quote_stream")
        return sent[0][1]["data"]

    def _assert_now(self, ts):
        at = datetime.fromisoformat(ts)
        self.assertIsNotNone(at.tzinfo)
        self.assertLess(abs((datetime.now(dt_timezone.utc) - at).total_seconds()), 60)

    def test_an_oanda_tick_says_when_and_from_where(self):
        from market_data.management.commands import stream_oanda
        data = self._sent(stream_oanda.broadcast, "EUR_USD", 1.1, None,
                          1.0999, 1.1001)
        self.assertEqual(data["source"], "oanda_stream")
        self._assert_now(data["ts"])
        self.assertIsNone(data["change_pct"])

    def test_a_binance_tick_says_when_and_from_where(self):
        from market_data.management.commands import stream_binance
        data = self._sent(stream_binance.broadcast, "BTCUSDT", 60000.0, 1.5,
                          59999.0, 60001.0, 1000.0)
        self.assertEqual(data["source"], "binance_ws")
        self._assert_now(data["ts"])
