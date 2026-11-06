"""Signal and watchlist popups open on click, stay open and fit the screen
(2026-11-06).

The operator, 2026-11-06 (point 2 of the rail work): the rail's signal card,
the rail's watchlist card, the data headband's card and the bottom bar's
dropdowns opened on hover only and closed when the hand left, so a long
card could not be scrolled to its end, and the bottom of a card sat under
the bottom band where its buttons could not be reached.

Now a click or a tap opens each of them PINNED: it stays while the hand
leaves, the page scrolls, the live sweep runs or the tab is switched, and
closes on an outside click or tap, Esc, its × or a second click on what
opened it. Hover still previews on a desktop, exactly as before (the hover
harness, tests/test_headband_hover_lives.py, is unchanged). One card is
pinned at a time, and while it is, no hover preview opens anywhere. A card
fits the screen: capped at the height left and scrolling inside, the signal
card keeping TAKE TRADE and PASS in view while its body scrolls. A row of
the headband SIGNALS popup opens its card in the rail; the dropdown footers
navigate again; the rail waits while a card is pinned.

These tests load the page's REAL inline scripts — the Phase 62.1 card
binder with its passes (64.4), the UPGRADE-3 block and the UPGRADE-9 popup
engine — under node, against the ticker, the data headband, the bottom bar
and both rail sections exactly as Django renders them, on the minimal DOM
of tests/test_headband_hover_lives.py.

Run with:  python manage.py test tests.test_popups_open_on_click
"""
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase, TestCase

from tests.test_rail_every_signal import (
    BAR_FROM, BAR_TO, DJANGO_TAG_RE, _ctx, _inst, _partial, _shell, _sig,
    _upgrade3, _user)

NODE = shutil.which("node")
RAIL_FROM = "<!-- Signals Rail (right sidebar)"
RAIL_TO = "{# The activity drawer"

RUN_JS = r"""
'use strict';
const vm = require('vm'), fs = require('fs'), path = require('path');
const D = require(path.join(__dirname, 'dom.js'));
const IN = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const settle = async () => { for (let i = 0; i < 8; i++) await new Promise(r => setImmediate(r)); };

function boot() {
  D.reset();
  const doc = new D.Document();
  doc.body.innerHTML = IN.page;
  let now = 0, seq = 0, fetches = 0;
  const timers = new Map(), errors = [], queue = [], sockets = [], store = {}, assigned = [], reg = [];
  const st = (f, ms, ...a) => { const id = ++seq; timers.set(id, { at: now + Math.max(0, +ms || 0), f, a, every: 0 }); return id; };
  const si = (f, ms, ...a) => { const id = ++seq; const every = Math.max(1, +ms || 0); timers.set(id, { at: now + every, f, a, every }); return id; };
  const clr = id => { timers.delete(id); };
  const later = (ms, v) => new Promise(res => { st(() => res(v), ms); });
  const fetch = (url) => {
    if (url === '/partials/signal-rail/') {
      fetches += 1;
      const body = queue.length ? queue.shift() : IN.answer;
      return later(10, { ok: true, status: 200, redirected: false, text: () => Promise.resolve(body) });
    }
    return Promise.resolve({ ok: false, status: 404, redirected: false,
      text: () => Promise.resolve(''), json: () => Promise.reject(new Error('404')) });
  };
  class WS { constructor(u) { this.url = u; sockets.push(this); } close() { if (this.onclose) this.onclose({}); } send() {} }
  const win = {
    document: doc, console: { log() {}, warn() {}, error() {}, debug() {}, info() {} },
    setTimeout: st, clearTimeout: clr, setInterval: si, clearInterval: clr,
    requestAnimationFrame: f => st(f, 16), cancelAnimationFrame: clr,
    fetch, WebSocket: WS, CustomEvent: D.CustomEvent, Event: D.Event,
    location: { protocol: 'http:', host: 'localhost:8000', pathname: '/', search: '', reload() {},
                assign(u) { assigned.push(u); } },
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
  const page = doc.getElementById('page-text');
  const W = {
    doc, win, queue, reg, assigned, page,
    fetches: () => fetches,
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
    /* A press: pointerdown where the hand is, then the click. */
    click(el, init) {
      D.dispatch(el, new D.Event('pointerdown', Object.assign({ bubbles: true }, init || {})));
      const ev = new D.Event('click', Object.assign({ bubbles: true, button: 0 }, init || {}));
      D.dispatch(el, ev);
      return { prevented: ev.defaultPrevented };
    },
    key(k) { D.dispatch(doc, new D.Event('keydown', { bubbles: true, key: k })); },
    wsSend(msg) { const s = sockets[sockets.length - 1]; s.onmessage({ data: JSON.stringify(msg) }); },
    wraps: () => doc.getElementById('railSignalsBody').querySelectorAll('.sr-signal-wrap[data-signal-id]'),
    cards: () => W.wraps().map(w => w.getAttribute('data-signal-id')),
    srState(wrap) {
      const pop = wrap.querySelector('.sr-popup');
      return { shown: pop.classList.contains('show'), pinned: pop.classList.contains('sv-pinned') };
    },
    shownSr: () => doc.getElementById('railSignalsBody').querySelectorAll('.sr-popup.show').length,
    portalShown: () => doc.body.children.filter(p => p.matches('.dh-pop') && p.style.display === 'block'),
    dd: () => doc.getElementById('hbSignalsDD'),
    ddOpen: () => { const d = doc.getElementById('hbSignalsDD'); return !!d && d.style.display === 'block'; },
    signalsCat: () => doc.querySelectorAll('.info-panel-wrap .ip-cat').filter(c => (c.textContent || '').indexOf('SIGNALS') >= 0 && c.querySelector('.ip-label') && c.querySelector('.ip-label').textContent.trim() === 'SIGNALS')[0],
    chip: () => { const c = doc.getElementById('railHeld'); return { shown: !c.hasAttribute('hidden'), text: c.textContent.trim() }; },
  };
  return W;
}

async function signalCard() {
  const W = boot();
  const out = {};
  const wrap = W.wraps()[0];
  const a = wrap.querySelector('a.sr-signal');
  const pop = wrap.querySelector('.sr-popup');
  W.pointTo(a);
  out.click = W.click(a);
  await W.advance(20);
  out.pinned = W.srState(wrap);
  out.expanded = a.getAttribute('aria-expanded');
  out.registered = W.reg.indexOf(pop) >= 0;
  out.max_height = parseFloat(pop.style.maxHeight);
  out.top = parseFloat(pop.style.top);
  W.pointTo(W.page); await W.advance(3000);
  out.after_leaving = W.srState(wrap);
  W.key('Escape'); await W.advance(20);
  out.after_escape = W.srState(wrap);
  out.registered_after_escape = W.reg.indexOf(pop) >= 0;
  W.click(a); await W.advance(20);
  out.repinned = W.srState(wrap);
  W.click(W.page); await W.advance(20);
  out.after_outside = W.srState(wrap);
  W.click(a); await W.advance(20);
  const x = pop.querySelector('.sv-pop-x');
  out.has_x = !!x;
  if (x) { W.click(x); await W.advance(20); }
  out.after_x = W.srState(wrap);
  W.click(a); await W.advance(20);
  W.click(a); await W.advance(20);
  out.after_second_click = W.srState(wrap);
  out.modified = W.click(a, { ctrlKey: true });
  await W.advance(20);
  out.after_modified = W.srState(wrap);
  out.errors = W.errors();
  return out;
}

async function onePinned() {
  const W = boot();
  const out = {};
  const [w1, w2] = W.wraps();
  W.click(w1.querySelector('a.sr-signal')); await W.advance(20);
  out.first = W.srState(w1);
  /* No hover preview while a card is pinned: not on another rail card,
     not on a headband card, not on a dropdown. */
  W.pointTo(w2.querySelector('a.sr-signal')); await W.advance(700);
  out.second_hovered = W.srState(w2);
  const item = W.doc.querySelectorAll('#dhTrack .dh-item')[0];
  W.pointTo(item.querySelector('.dh-sym')); await W.advance(700);
  out.dh_hovered = W.portalShown().length;
  W.pointTo(W.signalsCat()); await W.advance(700);
  out.dd_hovered = W.ddOpen();
  out.first_still = W.srState(w1);
  /* Pinning another closes the first. */
  W.click(item); await W.advance(20);
  out.first_after_other = W.srState(w1);
  out.dh_pinned = W.portalShown().map(p => p.classList.contains('sv-pinned'));
  out.errors = W.errors();
  return out;
}

async function watchlistCard() {
  const W = boot();
  const out = {};
  const item = W.doc.querySelectorAll('#railWatchBody .wl-item')[0];
  const pop = item.querySelector('.wl-pop');
  out.click = W.click(item);
  await W.advance(20);
  out.portalled = pop.parentNode === W.doc.body;
  out.display = pop.style.display;
  out.pinned = pop.classList.contains('sv-pinned');
  W.pointTo(W.page); await W.advance(3000);
  out.after_leaving = pop.style.display === 'block';
  W.click(W.page); await W.advance(20);
  out.after_outside = pop.style.display === 'block';
  out.back_in_item = pop.parentNode === item;
  W.click(item); await W.advance(20);
  W.key('Escape'); await W.advance(20);
  out.after_escape = pop.style.display === 'block';
  out.errors = W.errors();
  return out;
}

async function headbandCard() {
  const W = boot();
  const out = {};
  const item = W.doc.querySelectorAll('#dhTrack .dh-item')[1];
  const pop = item.querySelector('.dh-pop');
  out.click = W.click(item);
  await W.advance(20);
  const r = item.getBoundingClientRect();
  out.top = pop.style.top;
  out.expected_top = (r.bottom + 4) + 'px';
  out.max_height = pop.style.maxHeight;
  out.expected_max = (1080 - (r.bottom + 4) - 12) + 'px';
  out.pinned = pop.classList.contains('sv-pinned');
  out.has_x = !!pop.querySelector('.sv-pop-x');
  W.pointTo(W.page); await W.advance(3000);
  out.after_leaving = pop.style.display === 'block';
  /* A tab switch closes hover cards, never a pinned one. */
  W.doc.hidden = true; W.doc.visibilityState = 'hidden';
  D.dispatch(W.doc, new D.Event('visibilitychange', {}));
  out.after_tab_switch = pop.style.display === 'block';
  W.doc.hidden = false; W.doc.visibilityState = 'visible';
  W.click(item); await W.advance(20);
  out.after_second_click = pop.style.display === 'block';
  out.errors = W.errors();
  return out;
}

async function dropdown() {
  const W = boot();
  const out = {};
  const cat = W.signalsCat();
  const dd = W.dd();
  out.portalled = dd.parentNode === W.doc.body;
  out.click = W.click(cat);
  await W.advance(20);
  out.open = W.ddOpen();
  out.pinned = dd.classList.contains('sv-pinned');
  out.max_height = dd.style.maxHeight;
  W.pointTo(W.page); await W.advance(2000);
  out.after_leaving = W.ddOpen();
  const foot = dd.querySelectorAll('.ip-dd-item').filter(e => e.textContent.indexOf('View Signals') >= 0)[0];
  W.click(foot); await W.advance(20);
  out.assigned = W.assigned.slice();
  W.click(W.page); await W.advance(300);
  out.after_outside = W.ddOpen();
  out.errors = W.errors();
  return out;
}

async function railWaits() {
  const W = boot();
  const out = { cards_before: W.cards() };
  const wrap = W.wraps()[0];
  W.click(wrap.querySelector('a.sr-signal')); await W.advance(20);
  W.pointTo(W.page); await W.advance(400);
  W.wsSend({ type: 'signal' }); await W.advance(1500);
  out.fetches = W.fetches();
  out.cards_while_pinned = W.cards();
  out.chip_while_pinned = W.chip();
  const x = wrap.querySelector('.sr-popup .sv-pop-x');
  if (x) W.click(x);
  await W.advance(100);
  out.cards_after_unpin = W.cards();
  out.chip_after = W.chip();
  out.errors = W.errors();
  return out;
}

async function rowOpensCard() {
  const W = boot();
  const out = {};
  const rail = W.doc.getElementById('signalsRail');
  const sec = W.doc.getElementById('railSignals');
  rail.classList.remove('open');
  sec.classList.add('collapsed');
  const id = W.cards()[1];
  W.click(W.signalsCat()); await W.advance(20);
  const row = W.doc.querySelector('#hbSignalRows .sv-sig-row[data-signal-id="' + id + '"]');
  out.row_found = !!row;
  if (row) W.click(row.querySelector('.ipr-sym') || row);
  await W.advance(500);
  out.rail_open = rail.classList.contains('open');
  out.collapsed = sec.classList.contains('collapsed');
  const wrap = W.doc.querySelector('#railSignalsBody .sr-signal-wrap[data-signal-id="' + id + '"]');
  out.card = wrap ? W.srState(wrap) : null;
  out.dd_open = W.ddOpen();
  out.errors = W.errors();
  return out;
}

(async () => {
  const out = {};
  out.signal_card = await signalCard();
  out.one_pinned = await onePinned();
  out.watchlist_card = await watchlistCard();
  out.headband_card = await headbandCard();
  out.dropdown = await dropdown();
  out.rail_waits = await railWaits();
  out.row_opens_card = await rowOpensCard();
  process.stdout.write(JSON.stringify(out));
})().catch(e => { console.error(e && e.stack || e); process.exit(1); });
"""


def _scripts(raw):
    rail = raw[raw.index("/* ── Phase 62.1"):raw.index("/* ── TAKE TRADE")]
    assert not DJANGO_TAG_RE.search(rail), "Phase 62.1-64.4 carries Django tags"
    blocks = re.findall(r"<script>(.*?)</script>", raw, re.S)
    up9 = [b for b in blocks if "UPGRADE-9: headband popup escape + hover arrows" in b]
    assert len(up9) == 1 and not DJANGO_TAG_RE.search(up9[0])
    return [{"label": "base.html Phase 62.1-64.4", "source": rail},
            {"label": "base.html UPGRADE-3", "source": _upgrade3()},
            {"label": "base.html UPGRADE-9", "source": up9[0]}]


def _inputs():
    from django.template import engines
    from django.test import Client
    from tests.test_headband_hover_lives import (BANDS_FROM, BANDS_TO,
                                                 _instrument, _news)
    eng = engines["django"]
    raw = _shell()
    user = _user("pop_node")
    client = Client()
    client.force_login(user)
    _sig(_inst("PPFXA", "forex"), rule="pp_a", minutes_ago=40)
    _sig(_inst("PPFXB", "forex"), rule="pp_b", minutes_ago=20)
    ctx = dict(_ctx(user))
    ctx.update({
        "user": user, "sv_sweep": False,
        "ticker_items": [_news(4000 + i) for i in range(4)],
        "ui_headband": [_instrument(s, i) for i, s in enumerate(
            ["EURUSD", "GBPUSD", "AAPL", "BTCUSD"])],
        "ui_watchlist": [_instrument(s, i) for i, s in enumerate(
            ["EURCAD", "GLDM", "AAPL"])],
    })
    load = "{% load sauron_tags static %}"
    bands = raw[raw.index(BANDS_FROM):raw.index(BANDS_TO)]
    bar = raw[raw.index(BAR_FROM):raw.index(BAR_TO)]
    start = raw.index(RAIL_FROM)
    rail = raw[start:raw.index(RAIL_TO, start)]
    page = (eng.from_string(load + bands).render(ctx)
            + eng.from_string(load + bar).render(ctx)
            + '<main id="elsewhere"><p id="page-text">The page</p></main>'
            + eng.from_string(load + rail).render(ctx))
    _sig(_inst("PPFXC", "forex"), rule="pp_c", minutes_ago=1)
    return {"page": page, "answer": _partial(client), "scripts": _scripts(raw)}


def _report(inputs):
    from tests.test_headband_hover_lives import DOM_JS
    tmp = Path(tempfile.mkdtemp(prefix="sv-pin-"))
    try:
        (tmp / "dom.js").write_text(DOM_JS, encoding="utf-8")
        (tmp / "run.js").write_text(RUN_JS, encoding="utf-8")
        (tmp / "input.json").write_text(json.dumps(inputs), encoding="utf-8")
        proc = subprocess.run([NODE, str(tmp / "run.js"), str(tmp / "input.json")],
                              capture_output=True, text=True, timeout=300,
                              encoding="utf-8")
        if proc.returncode != 0:
            raise AssertionError("the popup runner failed: %s" % proc.stderr[:3000])
        return json.loads(proc.stdout)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@unittest.skipUnless(NODE, "node is not installed on this machine")
class PopupsOpenOnClickTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.report = _report(_inputs())

    def _dump(self, key):
        return json.dumps(self.report[key], indent=1, ensure_ascii=False)[:6000]

    def test_a_click_pins_the_signal_card(self):
        r = self.report["signal_card"]
        self.assertTrue(r["click"]["prevented"], "the click still navigated:\n"
                        + self._dump("signal_card"))
        self.assertEqual(r["pinned"], {"shown": True, "pinned": True},
                         self._dump("signal_card"))
        self.assertEqual(r["expanded"], "true")
        self.assertTrue(r["registered"], "SV.popup does not know the card is open")
        self.assertEqual(r["errors"], [])

    def test_a_pinned_card_survives_the_hand_leaving(self):
        r = self.report["signal_card"]
        self.assertEqual(r["after_leaving"], {"shown": True, "pinned": True},
                         self._dump("signal_card"))

    def test_escape_outside_and_the_x_close_it(self):
        r = self.report["signal_card"]
        closed = {"shown": False, "pinned": False}
        self.assertEqual(r["after_escape"], closed, self._dump("signal_card"))
        self.assertFalse(r["registered_after_escape"])
        self.assertEqual(r["repinned"], {"shown": True, "pinned": True})
        self.assertEqual(r["after_outside"], closed, self._dump("signal_card"))
        self.assertTrue(r["has_x"], "the pinned card has no close button")
        self.assertEqual(r["after_x"], closed, self._dump("signal_card"))
        self.assertEqual(r["after_second_click"], closed, self._dump("signal_card"))

    def test_a_modified_click_still_navigates(self):
        """Ctrl/Cmd/Shift-click keeps the browser's own meaning: open the
        link in a new tab, never pin."""
        r = self.report["signal_card"]
        self.assertFalse(r["modified"]["prevented"], self._dump("signal_card"))
        self.assertEqual(r["after_modified"], {"shown": False, "pinned": False})

    def test_the_card_fits_the_screen_and_keeps_its_actions(self):
        r = self.report["signal_card"]
        self.assertLessEqual(r["max_height"], 1080 - 24, self._dump("signal_card"))
        self.assertGreaterEqual(r["top"], 12)
        src = (Path(settings.BASE_DIR) / "templates" / "_partials"
               / "signal_rail_items.html").read_text(encoding="utf-8")
        foot = src.split('<div class="sr-pop-foot">', 1)
        self.assertEqual(len(foot), 2, "no .sr-pop-foot in the card")
        self.assertIn("sr-pop-actions-react", foot[1].split("</div>\n                    </div>\n                </div>")[0])
        self.assertIn("▸ INSTRUMENT", foot[1])
        self.assertIn("▸ ALL SIGNALS", foot[1])
        css = (Path(settings.BASE_DIR) / "static" / "css" / "sv-rail.css"
               ).read_text(encoding="utf-8")
        block = css.split(".sr-pop-foot {", 1)[1].split("}", 1)[0]
        self.assertIn("position: sticky", block)
        self.assertIn("bottom: -13px", block)
        head = css.split(".sr-popup .sr-pop-head {", 1)[1].split("}", 1)[0]
        self.assertIn("position: sticky", head)

    def test_one_pinned_popup_at_a_time(self):
        r = self.report["one_pinned"]
        self.assertEqual(r["first"], {"shown": True, "pinned": True}, self._dump("one_pinned"))
        self.assertEqual(r["first_after_other"], {"shown": False, "pinned": False},
                         self._dump("one_pinned"))
        self.assertEqual(r["dh_pinned"], [True], self._dump("one_pinned"))
        self.assertEqual(r["errors"], [])

    def test_no_hover_preview_while_pinned(self):
        r = self.report["one_pinned"]
        self.assertEqual(r["second_hovered"], {"shown": False, "pinned": False},
                         self._dump("one_pinned"))
        self.assertEqual(r["dh_hovered"], 0, self._dump("one_pinned"))
        self.assertFalse(r["dd_hovered"], self._dump("one_pinned"))
        self.assertEqual(r["first_still"], {"shown": True, "pinned": True})

    def test_the_watchlist_card_pins_on_click(self):
        r = self.report["watchlist_card"]
        self.assertTrue(r["click"]["prevented"], self._dump("watchlist_card"))
        self.assertTrue(r["portalled"])
        self.assertEqual(r["display"], "block")
        self.assertTrue(r["pinned"])
        self.assertTrue(r["after_leaving"], self._dump("watchlist_card"))
        self.assertFalse(r["after_outside"])
        self.assertTrue(r["back_in_item"])
        self.assertFalse(r["after_escape"], self._dump("watchlist_card"))
        self.assertEqual(r["errors"], [])

    def test_the_headband_card_pins_and_keeps_its_place(self):
        """Under its cell as before (the hover harness pins r.bottom + 4),
        and capped at the height left below it."""
        r = self.report["headband_card"]
        self.assertTrue(r["click"]["prevented"], self._dump("headband_card"))
        self.assertTrue(r["pinned"])
        self.assertTrue(r["has_x"])
        self.assertEqual(r["top"], r["expected_top"], self._dump("headband_card"))
        self.assertEqual(r["max_height"], r["expected_max"], self._dump("headband_card"))
        self.assertTrue(r["after_leaving"])
        self.assertTrue(r["after_tab_switch"], self._dump("headband_card"))
        self.assertFalse(r["after_second_click"])
        self.assertEqual(r["errors"], [])

    def test_the_bottom_bar_dropdown_pins_on_click(self):
        r = self.report["dropdown"]
        self.assertTrue(r["portalled"])
        self.assertTrue(r["click"]["prevented"], self._dump("dropdown"))
        self.assertTrue(r["open"], self._dump("dropdown"))
        self.assertTrue(r["pinned"])
        self.assertTrue(r["after_leaving"], self._dump("dropdown"))
        self.assertTrue(r["max_height"].endswith("px"), self._dump("dropdown"))
        self.assertGreaterEqual(float(r["max_height"][:-2]), 160)
        self.assertFalse(r["after_outside"], self._dump("dropdown"))
        self.assertEqual(r["errors"], [])

    def test_its_footer_navigates(self):
        """The "▸ View Signals" footer was dead once the dropdown left its
        cell for <body>."""
        r = self.report["dropdown"]
        self.assertEqual(r["assigned"], ["/signals/"], self._dump("dropdown"))

    def test_the_rail_waits_while_a_card_is_pinned(self):
        r = self.report["rail_waits"]
        self.assertEqual(r["fetches"], 1, self._dump("rail_waits"))
        self.assertEqual(r["cards_while_pinned"], r["cards_before"],
                         "the rail was swapped under a pinned card:\n"
                         + self._dump("rail_waits"))
        self.assertEqual(r["chip_while_pinned"], {"shown": True, "text": "↻ 1 new"})
        self.assertEqual(len(r["cards_after_unpin"]), 3, self._dump("rail_waits"))
        self.assertFalse(r["chip_after"]["shown"])
        self.assertEqual(r["errors"], [])

    def test_a_headband_row_opens_its_rail_card(self):
        r = self.report["row_opens_card"]
        self.assertTrue(r["row_found"], self._dump("row_opens_card"))
        self.assertTrue(r["rail_open"], self._dump("row_opens_card"))
        self.assertFalse(r["collapsed"])
        self.assertEqual(r["card"], {"shown": True, "pinned": True},
                         self._dump("row_opens_card"))
        self.assertFalse(r["dd_open"], "the dropdown stayed pinned under the card")
        self.assertEqual(r["errors"], [])


class PinnedCardsOnTouchScreensTests(SimpleTestCase):
    def test_pinned_cards_show_on_touch_screens(self):
        """A hover card stays hidden on touch (a tap must not be swallowed
        by a preview); a card the operator TAPPED open shows."""
        css = (Path(settings.BASE_DIR) / "static" / "css" / "sv-rail.css"
               ).read_text(encoding="utf-8")
        flat = re.sub(r"\s+", " ", css)
        for media in ("@media (hover: none)", "@media (max-width: 640px)"):
            block = flat.split(media, 1)[1].split("} }", 1)[0] if media in flat else ""
            with self.subTest(media=media):
                self.assertIn(".sr-popup.sv-pinned", block)
                self.assertIn(".dh-pop.sv-pinned", block)
                self.assertIn("display: block !important", block)
        block = flat.split("@media (max-width: 900px)", 1)[1].split("} }", 1)[0]
        self.assertIn(".sr-popup.sv-pinned", block)
        self.assertIn("touch-action: pan-y", flat)
