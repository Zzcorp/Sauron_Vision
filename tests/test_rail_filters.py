"""Filters and display choices for the rail's signals and watchlist, kept per
user (2026-11-06).

The operator, 2026-11-06: "Je veux aussi des filtres dans le headband
possible svp, pour les signaux et la watchlist svp, des filtres et des choix
d'affichage par assets classes ou autre par exemple" (filters and display
choices in the bands, for the signals and the watchlist, by asset class or
other criteria).

The filters run in the browser on facts the server renders on every row
(data-asset-class, data-side, data-score-b, data-votes, data-live,
data-held, data-rule-key) and the state sits as attributes on the hosts no
refresh replaces (the signals rail section, the headband SIGNALS dropdown,
the watchlist body and the headband WATCHLIST dropdown); one static
stylesheet hides and orders the rows (static/css/sv-rail.css), and a muted
rule is one generated rule (<style id="svRuleOff">). The choices are stored
on the operator's profile (TraderProfile.rail_prefs), so every browser draws
the same rail and the first paint is already filtered. The watchlist's
hidden limit of 40 becomes a stated 200.

MONEY DIRECTION: none. The filters hide and order what is drawn. They never
write the watchlist flag the scanner reads (Instrument.is_watchlist), and
nothing the engine, the bots, the alerts or the take-trade path read.

Run with:  python manage.py test tests.test_rail_filters
"""
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.test import Client, SimpleTestCase, TestCase

from tests.test_rail_every_signal import (
    BAR_FROM, BAR_TO, DJANGO_TAG_RE, HOST, _ctx, _inst, _page, _partial,
    _quote, _shell, _sig, _upgrade3, _user)

NODE = shutil.which("node")


def _prefs_url():
    return "/api/rail-prefs/"


def _post(client, prefs):
    return client.post(_prefs_url(), data=json.dumps({"prefs": prefs}),
                       content_type="application/json", HTTP_HOST=HOST)


def _star(symbol, asset_class="forex", last="1.08000"):
    inst = _inst(symbol, asset_class)
    inst.is_watchlist = True
    inst.save(update_fields=["is_watchlist"])
    if last is not None:
        _quote(inst, last)
    return inst


class ThePrefsTests(TestCase):
    def setUp(self):
        self.user = _user("rf_prefs")
        self.client.force_login(self.user)

    def test_prefs_default_and_clean(self):
        """A whitelist rebuild on every write: an unknown key or value falls
        back to the default, and the muted rules are bounded."""
        from dashboard.rail_prefs import SIG_DEFAULT, WATCH_DEFAULT, clean
        self.assertEqual(clean(None), {"v": 1, "sig": SIG_DEFAULT,
                                       "watch": WATCH_DEFAULT})
        out = clean({
            "sig": {"cls": ["forex", "crypto", "forex", "junk", 3],
                    "side": "sideways", "score": "7", "stage": "live",
                    "held": "not",
                    "rules_off": ["a" * 101, "ok", "ok"]
                    + [f"r{i}" for i in range(150)],
                    "sort": "score", "group": "1", "dense": True,
                    "gone": 1, "evil": "<script>"},
            "watch": {"sort": "held", "cls": "forex", "side": "long"},
            "other": {"x": 1}})
        sig, watch = out["sig"], out["watch"]
        self.assertEqual(set(out), {"v", "sig", "watch"})
        self.assertEqual(sig["cls"], ["forex", "crypto"])
        self.assertEqual(sig["side"], "all")
        self.assertEqual(sig["score"], 7)
        self.assertEqual(sig["stage"], "live")
        self.assertEqual(sig["held"], "not")
        self.assertEqual(sig["sort"], "score")
        self.assertIs(sig["group"], True)
        self.assertIs(sig["dense"], True)
        self.assertIs(sig["gone"], True)
        self.assertNotIn("evil", sig)
        self.assertEqual(len(sig["rules_off"]), 100)
        self.assertEqual(sig["rules_off"][0], "ok")
        self.assertTrue(all(len(r) <= 100 for r in sig["rules_off"]))
        self.assertEqual(len(set(sig["rules_off"])), 100)
        self.assertEqual(watch, dict(WATCH_DEFAULT, sort="held"))
        self.assertEqual(clean({"sig": {"score": 4}})["sig"]["score"], 0)

    def test_prefs_follow_the_user_not_the_browser(self):
        resp = _post(self.client, {"sig": {"cls": ["forex"], "side": "long"}})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["ok"])
        self.assertEqual(resp.json()["prefs"]["sig"]["cls"], ["forex"])
        phone = Client()
        phone.force_login(self.user)
        got = phone.get(_prefs_url(), HTTP_HOST=HOST).json()["prefs"]
        self.assertEqual(got["sig"]["cls"], ["forex"])
        self.assertEqual(got["sig"]["side"], "long")
        # One section at a time: the other is kept.
        _post(phone, {"watch": {"sort": "symbol"}})
        got = self.client.get(_prefs_url(), HTTP_HOST=HOST).json()["prefs"]
        self.assertEqual(got["sig"]["cls"], ["forex"])
        self.assertEqual(got["watch"]["sort"], "symbol")
        other = Client()
        other.force_login(_user("rf_other"))
        from dashboard.rail_prefs import SIG_DEFAULT
        self.assertEqual(other.get(_prefs_url(), HTTP_HOST=HOST)
                         .json()["prefs"]["sig"], SIG_DEFAULT)
        bad = self.client.post(_prefs_url(), data="[1, 2]",
                               content_type="application/json", HTTP_HOST=HOST)
        self.assertEqual(bad.status_code, 200)
        self.assertEqual(bad.json(), {"ok": False})

    def test_prefs_require_login_and_answer_423_when_locked(self):
        anon = Client()
        self.assertEqual(anon.get(_prefs_url(), HTTP_HOST=HOST).status_code, 302)
        from core.idle_lock import LOCKED_KEY
        session = self.client.session
        session[LOCKED_KEY] = True
        session.save()
        self.assertEqual(self.client.get(_prefs_url(), HTTP_HOST=HOST).status_code, 423)
        self.assertEqual(_post(self.client, {"sig": {"side": "long"}}).status_code, 423)


class TheFirstPaintIsFilteredTests(TestCase):
    def setUp(self):
        self.user = _user("rf_page")
        self.client.force_login(self.user)

    def test_the_page_renders_the_hosts_from_the_prefs(self):
        from dashboard.signal_rail import rule_key
        _post(self.client, {"sig": {"cls": ["forex", "crypto"], "side": "short",
                                    "rules_off": ["rf_muted"], "gone": True}})
        page = _page(self.client)
        for host in ('id="railSignals"', 'id="hbSignalsDD"'):
            tag = re.search(r"<div[^>]*" + host + r"[^>]*>", page).group(0)
            with self.subTest(host=host):
                self.assertIn('data-sv-fhost="signals"', tag)
                self.assertIn('data-f-class="forex crypto"', tag)
                self.assertIn('data-f-side="short"', tag)
                self.assertIn('data-f-gone="1"', tag)
        style = re.search(r'<style id="svRuleOff"[^>]*>(.*?)</style>', page, re.S)
        self.assertIsNotNone(style, "no muted-rule style in the page")
        self.assertIn(f'[data-rule-key="{rule_key("rf_muted")}"]', style.group(1))
        self.assertIn('[data-sv-fhost="signals"]:not([data-f-peek="1"])',
                      style.group(1))
        for host in ('id="railWatchBody"', 'id="hbWatchDD"'):
            tag = re.search(r"<div[^>]*" + host + r"[^>]*>", page).group(0)
            with self.subTest(host=host):
                self.assertIn('data-sv-fhost="watch"', tag)
                self.assertIn('data-f-sort="class"', tag)

    def test_every_class_has_its_hide_rule(self):
        from core.constants import AssetClass
        css = (Path(settings.BASE_DIR) / "static" / "css" / "sv-rail.css"
               ).read_text(encoding="utf-8")
        for key, _label in AssetClass.CHOICES:
            with self.subTest(cls=key):
                self.assertIn(
                    f':not([data-f-class~="{key}"]) :is([data-sv-row],'
                    f'[data-sv-grp])[data-asset-class="{key}"]', css)

    def test_rows_carry_their_facts_and_ranks(self):
        inst = _inst("RFRNK", "crypto")
        low = _sig(inst, rule="rf_low", score=0.55, entry="100", stop="95",
                   target="110", minutes_ago=3)
        high = _sig(inst, rule="rf_high", score=0.91, direction="bearish",
                    entry="100", stop="105", target="90", minutes_ago=2)
        mid = _sig(_inst("RFRNF", "forex"), rule="rf_mid", score=0.7,
                   minutes_ago=1)
        html = _partial(self.client)

        def tag(sig):
            return re.search(r'<div class="sr-signal-wrap[^"]*" data-signal-id="%d"[^>]*>'
                             % sig.pk, html).group(0)
        self.assertIn("--o-score:1;", tag(high))
        self.assertIn("--o-score:2;", tag(mid))
        self.assertIn("--o-score:3;", tag(low))
        self.assertIn('data-score-b="9"', tag(high))
        self.assertIn('data-score-b="5"', tag(low))
        self.assertIn('data-side="short"', tag(high))
        self.assertIn('data-asset-class="forex"', tag(mid))
        # Grouping by class follows the vocabulary's order: forex before
        # crypto, newest first within a class.
        o_cls = {s.pk: int(re.search(r"--o-cls:(\d+)", tag(s)).group(1))
                 for s in (low, high, mid)}
        self.assertLess(o_cls[mid.pk], o_cls[high.pk])
        self.assertLess(o_cls[high.pk], o_cls[low.pk])
        self.assertIn('data-sv-grp data-asset-class="crypto"', html)


class TheWatchlistTests(TestCase):
    def setUp(self):
        self.user = _user("rf_watch")
        self.client.force_login(self.user)

    def _rows(self, page):
        rail = page.split('id="railWatchBody"', 1)[1].split("{# The activity drawer")[0]
        rail_syms = re.findall(r'class="wl-item"[^>]*data-symbol="([^"]+)"', rail)
        dd = page.split('id="hbWatchDD"', 1)[1].split("▸ View Instruments")[0]
        dd_syms = re.findall(r'class="ip-dd-row sv-wl-row"[^>]*data-symbol="([^"]+)"', dd)
        return rail_syms, dd_syms

    def test_the_watchlist_lists_every_star(self):
        """The rail sliced the watchlist at 40 without a word, and the
        headband popup showed six; both list every star now, in the same
        order."""
        for i in range(45):
            _star(f"RFW{i:03d}", ["forex", "crypto", "stock"][i % 3])
        rail_syms, dd_syms = self._rows(_page(self.client))
        self.assertEqual(len(rail_syms), 45)
        self.assertEqual(dd_syms, rail_syms)

    def test_above_the_ceiling_the_rail_says_so(self):
        from instruments.models import Instrument
        Instrument.objects.bulk_create([Instrument(
            symbol=f"RFC{i:03d}", name="c", asset_class="forex",
            is_watchlist=True) for i in range(205)])
        page = _page(self.client)
        rail_syms, dd_syms = self._rows(page)
        self.assertEqual(len(rail_syms), 200)
        self.assertEqual(len(dd_syms), 200)
        self.assertIn("Showing 200 of 205 starred.", page)

    def test_wl_items_stay_paintable(self):
        """The live painter (applyTick, and the coming live feed) finds a
        row by .wl-sym and writes .wl-last / .wl-chg at the row's own
        precision: the filters change none of it."""
        _star("RFPA1", "forex")
        _star("RFPA2", "crypto", last="64000")
        page = _page(self.client)
        body = page.split('id="railWatchBody"', 1)[1].split("{# The activity drawer")[0]
        items = re.findall(r'<a [^>]*class="wl-item"[^>]*>', body)
        self.assertEqual(len(items), 2)
        for tag in items:
            self.assertIn("data-decimals=", tag)
            self.assertIn("data-sv-row", tag)
            self.assertIn("data-held=", tag)
        for cls in ('class="wl-sym"', 'class="wl-last"', 'class="wl-chg'):
            self.assertEqual(body.count(cls), 2, cls)

    def test_filters_never_write_the_watchlist_flag(self):
        """Instrument.is_watchlist widens the scan universe: no filter
        touches it. A guard, not a regression test: it passed before the
        filters existed, by construction."""
        from instruments.models import Instrument
        _star("RFFL1", "forex")
        _star("RFFL2", "stock", last="100")
        before = list(Instrument.objects.order_by("pk").values())
        _post(self.client, {"watch": {"cls": ["forex"], "held": "held",
                                      "sort": "symbol", "group": True}})
        _page(self.client)
        self.assertEqual(list(Instrument.objects.order_by("pk").values()), before)


# ── the filters under node: sv-rail-filters.js on the page as rendered ───

RUN_JS = r"""
'use strict';
const vm = require('vm'), fs = require('fs'), path = require('path');
const D = require(path.join(__dirname, 'dom.js'));
const IN = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const settle = async () => { for (let i = 0; i < 8; i++) await new Promise(r => setImmediate(r)); };

function boot(opts) {
  opts = opts || {};
  D.reset();
  const doc = new D.Document();
  doc.body.innerHTML = IN.page;
  doc.cookie = 'theme=dark; csrftoken=TOKEN123; other=1';
  let now = 0, seq = 0, rails = 0;
  const timers = new Map(), errors = [], posts = [], passes = [], sockets = [], store = {}, engaged = [];
  const st = (f, ms, ...a) => { const id = ++seq; timers.set(id, { at: now + Math.max(0, +ms || 0), f, a, every: 0 }); return id; };
  const si = (f, ms, ...a) => { const id = ++seq; const every = Math.max(1, +ms || 0); timers.set(id, { at: now + every, f, a, every }); return id; };
  const clr = id => { timers.delete(id); };
  const later = (ms, v) => new Promise(res => { st(() => res(v), ms); });
  /* A session that expired: login_required redirects, and the login page
     answers 200 — ok, but redirected, and not JSON. */
  const loginPage = () => later(10, { ok: true, status: 200, redirected: true,
    text: () => Promise.resolve('<html>login</html>'),
    json: () => Promise.reject(new Error('not JSON: the login page')) });
  const fetch = (url, o) => {
    if (url === '/api/rail-prefs/') {
      posts.push({ method: o && o.method, headers: o && o.headers, body: o && o.body });
      if (opts.expired) return loginPage();
      const status = opts.saveStatus || 200;
      return later(10, { ok: status === 200, status, redirected: false, json: () => Promise.resolve({ ok: status === 200 }) });
    }
    if (url === '/api/signal-rail/pass/') {
      passes.push(o && o.body);
      if (opts.expired) return loginPage();
      return later(10, { ok: true, status: 200, redirected: false, json: () => Promise.resolve({ ok: true, reason: 'passed' }) });
    }
    if (url === '/partials/signal-rail/') {
      rails += 1;
      return later(10, { ok: true, status: 200, redirected: false, text: () => Promise.resolve(IN.answer) });
    }
    return Promise.resolve({ ok: false, status: 404, redirected: false,
      text: () => Promise.resolve(''), json: () => Promise.reject(new Error('404')) });
  };
  /* The stylesheet's stand-in. A row the test marks data-x-hidden is one
     some filter hides; the class filter is applied as sv-rail.css writes
     it — a row or a group header whose class the host does not show, unless
     the host peeks (tests/test_rail_filters_css.py evaluates the stylesheet
     itself); an inline display is the element's own. */
  const computed = el => {
    let display = (el.style && el.style.display) || 'block';
    if (el.hasAttribute && el.hasAttribute('data-x-hidden')) display = 'none';
    else if (el.hasAttribute && (el.hasAttribute('data-sv-row') || el.hasAttribute('data-sv-grp'))
             && el.getAttribute('data-asset-class') !== null && display !== 'none') {
      const host = el.closest('[data-sv-fhost]');
      const shown = host ? (host.getAttribute('data-f-class') || '').split(/\s+/).filter(Boolean) : [];
      if (host && host.getAttribute('data-f-peek') !== '1' && shown.length
          && shown.indexOf(el.getAttribute('data-asset-class')) < 0) display = 'none';
    }
    return { display, position: '' };
  };
  class WS { constructor(u) { this.url = u; sockets.push(this); } close() { if (this.onclose) this.onclose({}); } send() {} }
  const win = {
    document: doc, console: { log() {}, warn() {}, error() {}, debug() {}, info() {} },
    setTimeout: st, clearTimeout: clr, setInterval: si, clearInterval: clr,
    requestAnimationFrame: f => st(f, 16), cancelAnimationFrame: clr,
    fetch, WebSocket: WS, CustomEvent: D.CustomEvent, Event: D.Event, JSON,
    location: { protocol: 'http:', host: 'localhost:8000', pathname: '/', search: '', reload() {}, assign() {} },
    localStorage: { getItem: k => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = String(v); }, removeItem: k => { delete store[k]; } },
    innerWidth: 1920, innerHeight: 1080, navigator: { userAgent: 'node' },
    getComputedStyle: computed,
    matchMedia: () => ({ matches: false, addEventListener() {}, addListener() {} }),
    SV: { popup: { opened() {}, closed() {} } },
    svIdleLock: { engage: (x) => { engaged.push(x); } },
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
  const W = {
    doc, win, posts, passes, engaged, store,
    rails: () => rails,
    errors: () => errors.concat(D.errors()),
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
    click(el) { const ev = new D.Event('click', { bubbles: true, button: 0 }); D.dispatch(el, ev); return ev; },
    chip(kindSel, key, val) {
      return doc.querySelectorAll(kindSel + ' [data-f-key="' + key + '"]').filter(c => (c.getAttribute('data-f-val') || '') === val)[0] || null;
    },
    attr: (id, a) => { const e = doc.getElementById(id); return e ? e.getAttribute(a) : null; },
    status: () => doc.querySelectorAll('[data-f-kind="signals"] [data-f-status-text]').map(e => e.textContent.trim()),
    wsSend(msg) { const s = sockets[sockets.length - 1]; s.onmessage({ data: JSON.stringify(msg) }); },
    fire(type, detail) { D.dispatch(doc, new D.CustomEvent(type, { detail })); },
  };
  return W;
}

async function chipsAndSave() {
  const W = boot();
  const out = {};
  const fx = W.chip('#railSigFacets', 'cls', 'forex');
  out.fx_found = !!fx;
  W.click(fx); await W.advance(100);
  out.rail_class = W.attr('railSignals', 'data-f-class');
  out.dd_class = W.attr('hbSignalsDD', 'data-f-class');
  out.pressed = W.doc.querySelectorAll('[data-f-kind="signals"] [data-f-key="cls"][data-f-val="forex"]').map(c => c.getAttribute('aria-pressed'));
  W.click(W.chip('#railSigFacets', 'side', 'short')); await W.advance(100);
  out.side = [W.attr('railSignals', 'data-f-side'), W.attr('hbSignalsDD', 'data-f-side')];
  out.posts_before_pause = W.posts.length;
  await W.advance(600);
  out.posts = W.posts.length;
  out.post = W.posts[0] ? { method: W.posts[0].method, csrf: W.posts[0].headers['X-CSRFToken'], body: JSON.parse(W.posts[0].body) } : null;
  /* A rule muted from the panel is one generated rule. */
  const rule = W.doc.querySelector('#railRuleList [data-f-key="rule"]');
  out.rule_found = !!rule;
  out.rule_key = rule ? rule.getAttribute('data-rule-key') : null;
  if (rule) W.click(rule);
  await W.advance(50);
  out.style = W.doc.getElementById('svRuleOff').textContent;
  out.rule_pressed = rule ? rule.getAttribute('aria-pressed') : null;
  await W.advance(600);
  out.posts_after_rule = W.posts.length;
  out.last_body = W.posts.length ? JSON.parse(W.posts[W.posts.length - 1].body) : null;
  out.errors = W.errors();
  return out;
}

async function lockedSave() {
  const W = boot({ saveStatus: 423 });
  W.click(W.chip('#railSigFacets', 'cls', 'forex')); await W.advance(700);
  return { posts: W.posts.length, engaged: W.engaged.slice(),
           kept: W.attr('railSignals', 'data-f-class'),
           unsaved: W.doc.querySelectorAll('[data-f-kind="signals"] [data-f-unsaved]').length,
           errors: W.errors() };
}

async function survives() {
  const W = boot();
  const out = {};
  W.click(W.chip('#railSigFacets', 'cls', 'forex')); await W.advance(50);
  const cards = W.doc.querySelectorAll('#railSignalsBody .sr-signal-wrap[data-sv-row]');
  out.cards = cards.length;
  cards[0].setAttribute('data-x-hidden', '');
  W.fire('htmx:afterSwap', {}); await W.advance(50);
  out.status_marked = W.status();
  W.wsSend({ type: 'signal' }); await W.advance(1500);
  out.cards_after_refresh = W.doc.querySelectorAll('#railSignalsBody .sr-signal-wrap[data-sv-row]').length;
  out.class_after_refresh = [W.attr('railSignals', 'data-f-class'), W.attr('hbSignalsDD', 'data-f-class')];
  out.status_after_refresh = W.status();
  out.rule_buttons_after_refresh = W.doc.querySelectorAll('#railRuleList [data-f-key="rule"]').length;
  /* Another filter hides the FX card too (the class filter already hides
     the other two): the count must follow the swap. */
  W.doc.querySelector('#railSignalsBody .sr-signal-wrap[data-sv-row][data-asset-class="forex"]').setAttribute('data-x-hidden', '');
  W.fire('sv:live-swapped', { region: 'hb-signals-detail' }); await W.advance(50);
  out.status_after_region_swap = W.status();
  out.class_after_region_swap = W.attr('hbSignalsDD', 'data-f-class');
  /* Peek: show all pauses every filter at once, and is not saved. */
  const peek = W.doc.querySelector('#railSigFacets [data-f-key="peek"]');
  if (peek) W.click(peek);
  await W.advance(50);
  out.peek = [W.attr('railSignals', 'data-f-peek'), W.attr('hbSignalsDD', 'data-f-peek')];
  out.errors = W.errors();
  return out;
}

async function tickOnFilteredWatchlist() {
  const W = boot();
  const out = {};
  const held = W.chip('#railWatchFacets', 'held', 'held');
  out.held_found = !!held;
  if (held) W.click(held);
  await W.advance(50);
  out.watch_held = [W.attr('railWatchBody', 'data-f-held'), W.attr('hbWatchDD', 'data-f-held')];
  const item = W.doc.querySelectorAll('#railWatchBody .wl-item')[0];
  out.symbol = item.querySelector('.wl-sym').textContent.trim();
  out.before = item.querySelector('.wl-last').textContent.trim();
  W.wsSend({ type: 'quote', data: { symbol: out.symbol, last: 1.23456, change_pct: 0.5 } });
  await W.advance(50);
  out.after = item.querySelector('.wl-last').textContent.trim();
  out.chg = item.querySelector('.wl-chg').textContent.trim();
  out.errors = W.errors();
  return out;
}

/* A PASS: the card leaves at once, the counts never call it "hidden by
   your filters", and the rail asks the server again. */
async function passCounts() {
  const W = boot();
  const out = {};
  const ids = W.doc.querySelectorAll('#railSignalsBody .sr-signal-wrap[data-signal-id]').map(w => w.getAttribute('data-signal-id'));
  out.status_before = W.status();
  W.win.dismissSignal(ids[0]);
  await W.advance(100);
  W.fire('sv:live-swapped', { region: 'hb-signals' }); await W.advance(50);
  out.status_after = W.status();
  out.passes = W.passes.length;
  await W.advance(1200);
  out.rails = W.rails();
  /* The server's answer here does not know the pass yet (it still draws
     the card, and a third that arrived): the outbox keeps the card out. */
  out.status_after_refetch = W.status();
  out.passed_drawn = W.doc.querySelectorAll('#railSignalsBody .sr-signal-wrap[data-signal-id="' + ids[0] + '"]').filter(w => w.style.display !== 'none').length;
  out.peek_offered = W.doc.querySelectorAll('#railSigFacets [data-f-key="peek"]').filter(p => !p.hasAttribute('hidden')).length;
  out.errors = W.errors();
  return out;
}

/* A session that expired: the login page answers 200, redirected. Nothing
   was stored, and the page must not say otherwise. */
async function expiredSession() {
  const W = boot({ expired: true });
  const out = {};
  W.click(W.chip('#railSigFacets', 'cls', 'forex')); await W.advance(700);
  out.unsaved = W.doc.querySelectorAll('[data-f-kind="signals"] [data-f-unsaved]').length;
  out.status = W.status();
  const id = W.doc.querySelector('#railSignalsBody .sr-signal-wrap[data-signal-id]').getAttribute('data-signal-id');
  W.win.dismissSignal(id);
  await W.advance(1500);
  out.passes = W.passes.length;
  out.rails_after_pass = W.rails();
  out.outbox = JSON.parse(W.store['sauron_dismissed_signals'] || '[]');
  out.errors = W.errors();
  return out;
}

/* One section changed, one section saved: a stale second tab must not
   write back the other section's choices. */
async function sectionsSaved() {
  const W = boot();
  const out = {};
  W.click(W.chip('#railSigFacets', 'cls', 'forex')); await W.advance(700);
  out.first = W.posts.length ? Object.keys(JSON.parse(W.posts[0].body).prefs).sort() : null;
  W.click(W.chip('#railWatchFacets', 'held', 'held')); await W.advance(700);
  out.second = W.posts.length > 1 ? Object.keys(JSON.parse(W.posts[1].body).prefs).sort() : null;
  out.errors = W.errors();
  return out;
}

/* The "(no rule)" toggle mutes the signals that name no rule. */
async function noRuleMute() {
  const W = boot();
  const out = {};
  const list = W.doc.getElementById('railRuleList');
  const b = W.doc.createElement('button');
  b.setAttribute('type', 'button');
  b.setAttribute('class', 'rf-rule');
  b.setAttribute('data-f-key', 'rule');
  b.setAttribute('data-f-val', '');
  b.setAttribute('data-rule-key', 'r-none');
  list.appendChild(b);
  W.click(b); await W.advance(700);
  out.style = W.doc.getElementById('svRuleOff').textContent;
  out.pressed = b.getAttribute('aria-pressed');
  out.saved = W.posts.length ? JSON.parse(W.posts[W.posts.length - 1].body).prefs.sig.rules_off : null;
  out.errors = W.errors();
  return out;
}

/* LEFT THE RAIL open under a class filter: its hidden rows are counted,
   and "show all" is offered. */
async function leftTally() {
  const W = boot();
  const out = {};
  W.click(W.chip('#railSigFacets', 'gone', '1')); await W.advance(50);
  out.gone_open = W.attr('railSignals', 'data-f-gone');
  out.left_rows = W.doc.querySelectorAll('#railSignalsBody .sr-gone-row').length;
  W.click(W.chip('#railSigFacets', 'cls', 'crypto')); await W.advance(50);
  out.status = W.status();
  out.peek_offered = W.doc.querySelectorAll('#railSigFacets [data-f-key="peek"]').filter(p => !p.hasAttribute('hidden')).length;
  out.errors = W.errors();
  return out;
}

/* A refresh held while the operator reads, under a class filter: the chip
   counts what the filters will show, and says what they will hide. */
async function heldUnderFilter() {
  const W = boot();
  const out = {};
  W.click(W.chip('#railSigFacets', 'cls', 'forex')); await W.advance(50);
  W.pointTo(W.doc.querySelector('#railSignalsBody .sr-signal-wrap a.sr-signal')); await W.advance(100);
  W.wsSend({ type: 'signal' }); await W.advance(1500);
  const chip = W.doc.getElementById('railHeld');
  out.chip = chip ? { shown: !chip.hasAttribute('hidden'), text: chip.textContent.trim() } : null;
  out.probes_left = W.doc.querySelectorAll('[data-sv-probe]').length;
  out.cards = W.doc.querySelectorAll('#railSignalsBody .sr-signal-wrap[data-signal-id]').length;
  out.errors = W.errors();
  return out;
}

/* A fill opens a position on a starred instrument: the sweep re-renders
   the headband WATCHLIST rows, and the rail's items follow them. */
async function watchHeld() {
  const W = boot();
  const out = {};
  const item = W.doc.querySelectorAll('#railWatchBody [data-sv-row][data-symbol]')[0];
  const sym = item.getAttribute('data-symbol');
  out.before = item.getAttribute('data-held');
  out.count_before = W.doc.querySelector('#railWatchFacets [data-sv-wheld]') ? W.doc.querySelector('#railWatchFacets [data-sv-wheld]').textContent.trim() : null;
  const region = W.doc.querySelector('[data-sv-live="hb-watchlist-detail"]');
  const row = region.querySelectorAll('.sv-wl-row[data-symbol]').filter(r => r.getAttribute('data-symbol') === sym)[0];
  row.setAttribute('data-held', '1');
  row.setAttribute('style', '--o-sym:1;--o-cls:1;--o-held:1;--o-cheld:1');
  W.fire('sv:live-swapped', { region: 'hb-watchlist-detail', node: region }); await W.advance(20);
  out.after = item.getAttribute('data-held');
  out.style = item.getAttribute('style');
  const wheld = W.doc.querySelector('#railWatchFacets [data-sv-wheld]');
  out.count_after = wheld ? wheld.textContent.trim() : null;
  out.errors = W.errors();
  return out;
}

/* Grouped by class, a class whose rows another filter hides loses its
   header with them — in the page's <head>, never inside a region. */
async function emptyGroup() {
  const W = boot();
  const out = {};
  W.click(W.chip('#railSigPanel', 'group', '1')); await W.advance(50);
  out.group = W.attr('railSignals', 'data-f-group');
  W.doc.querySelectorAll('#railSignalsBody .sr-list > [data-sv-row][data-asset-class="crypto"]').forEach(r => r.setAttribute('data-x-hidden', ''));
  W.fire('htmx:afterSwap', {}); await W.advance(50);
  const style = W.doc.getElementById('svGrpOff');
  out.style = style ? style.textContent : null;
  out.in_head = !!(style && style.parentNode === W.doc.head);
  out.errors = W.errors();
  return out;
}

(async () => {
  const out = {};
  out.chips_and_save = await chipsAndSave();
  out.locked_save = await lockedSave();
  out.survives = await survives();
  out.tick = await tickOnFilteredWatchlist();
  out.pass_counts = await passCounts();
  out.expired = await expiredSession();
  out.sections = await sectionsSaved();
  out.no_rule = await noRuleMute();
  out.left_tally = await leftTally();
  out.held_filter = await heldUnderFilter();
  out.watch_held = await watchHeld();
  out.empty_group = await emptyGroup();
  process.stdout.write(JSON.stringify(out));
})().catch(e => { console.error(e && e.stack || e); process.exit(1); });
"""


def _inputs():
    from django.template import engines
    from django.test import Client as _Client, RequestFactory
    from core.context_ui import ui_extras
    eng = engines["django"]
    raw = _shell()
    user = _user("rf_node")
    client = _Client()
    client.force_login(user)
    _sig(_inst("RFNDA", "forex"), rule="rf_node_a", minutes_ago=30)
    _sig(_inst("RFNDB", "crypto"), rule="rf_node_b", entry="100", stop="95",
         target="110", minutes_ago=20)
    # One signal in LEFT THE RAIL: its stop crossed.
    gone = _inst("RFNDG", "forex")
    _sig(gone, rule="rf_node_g", minutes_ago=25)
    _quote(gone, "1.07000")
    _star("RFNWA", "forex")
    _star("RFNWB", "crypto", last="64000")
    req = RequestFactory().get("/")
    req.user = user
    ctx = dict(_ctx(user))
    ctx.update(ui_extras(req))
    ctx.update({"user": user, "sv_sweep": False})
    load = "{% load sauron_tags static %}"
    style = re.search(r'<style id="svRuleOff".*?</style>', raw, re.S).group(0)
    bar = raw[raw.index(BAR_FROM):raw.index(BAR_TO)]
    start = raw.index("<!-- Signals Rail (right sidebar)")
    rail = raw[start:raw.index("{# The activity drawer", start)]
    page = (eng.from_string(load + style).render(ctx)
            + eng.from_string(load + bar).render(ctx)
            + '<main id="elsewhere"><p id="page-text">The page</p></main>'
            + eng.from_string(load + rail).render(ctx))
    _sig(_inst("RFNDC", "stock"), rule="rf_node_c", entry="100", stop="95",
         target="110", minutes_ago=1)
    blocks = re.findall(r"<script>(.*?)</script>", raw, re.S)
    rail_js = raw[raw.index("/* ── Phase 62.1"):raw.index("/* ── TAKE TRADE")]
    assert not DJANGO_TAG_RE.search(rail_js)
    filters = (Path(settings.BASE_DIR) / "static" / "js" / "sv-rail-filters.js"
               ).read_text(encoding="utf-8")
    scripts = [{"label": "base.html Phase 62.1-64.4", "source": rail_js},
               {"label": "base.html UPGRADE-3", "source": _upgrade3()},
               {"label": "static/js/sv-rail-filters.js", "source": filters}]
    return {"page": page, "answer": _partial(client), "scripts": scripts}


def _report(inputs):
    from tests.test_headband_hover_lives import DOM_JS
    tmp = Path(tempfile.mkdtemp(prefix="sv-rf-"))
    try:
        (tmp / "dom.js").write_text(DOM_JS, encoding="utf-8")
        (tmp / "run.js").write_text(RUN_JS, encoding="utf-8")
        (tmp / "input.json").write_text(json.dumps(inputs), encoding="utf-8")
        proc = subprocess.run([NODE, str(tmp / "run.js"), str(tmp / "input.json")],
                              capture_output=True, text=True, timeout=300,
                              encoding="utf-8")
        if proc.returncode != 0:
            raise AssertionError("the filters runner failed: %s" % proc.stderr[:3000])
        return json.loads(proc.stdout)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@unittest.skipUnless(NODE, "node is not installed on this machine")
class TheFiltersInTheBrowserTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.report = _report(_inputs())

    def _dump(self, key):
        return json.dumps(self.report[key], indent=1, ensure_ascii=False)[:6000]

    def test_a_chip_sets_both_hosts(self):
        """The rail and the headband popup are one list: a chip pressed on
        one filters both."""
        r = self.report["chips_and_save"]
        self.assertTrue(r["fx_found"], self._dump("chips_and_save"))
        self.assertEqual(r["rail_class"], "forex", self._dump("chips_and_save"))
        self.assertEqual(r["dd_class"], "forex")
        self.assertEqual(set(r["pressed"]), {"true"})
        self.assertGreaterEqual(len(r["pressed"]), 2)
        self.assertEqual(r["side"], ["short", "short"])
        self.assertEqual(r["errors"], [])

    def test_muting_a_rule_writes_the_style(self):
        r = self.report["chips_and_save"]
        self.assertTrue(r["rule_found"], self._dump("chips_and_save"))
        self.assertIn('[data-rule-key="%s"]' % r["rule_key"], r["style"])
        self.assertIn('[data-sv-fhost="signals"]:not([data-f-peek="1"])', r["style"])
        self.assertEqual(r["rule_pressed"], "false")
        self.assertEqual(len(r["last_body"]["prefs"]["sig"]["rules_off"]), 1)

    def test_the_choice_is_saved_once_after_a_pause(self):
        r = self.report["chips_and_save"]
        self.assertEqual(r["posts_before_pause"], 0, self._dump("chips_and_save"))
        self.assertEqual(r["posts"], 1, self._dump("chips_and_save"))
        self.assertEqual(r["post"]["method"], "POST")
        self.assertEqual(r["post"]["csrf"], "TOKEN123")
        sig = r["post"]["body"]["prefs"]["sig"]
        self.assertEqual(sig["cls"], ["forex"])
        self.assertEqual(sig["side"], "short")
        # 2026-11-12, on purpose: "shut_off" joined the saved choices with
        # the SHUT chip (the cards whose market is shut now, shown or
        # hidden), and "shut" with the optional market hold's MARKET SHUT
        # section (tests/test_rail_market_shut.py).
        self.assertEqual(set(sig), {"cls", "side", "score", "stage", "held",
                                    "rules_off", "sort", "group", "dense", "gone",
                                    "shut_off", "shut"})
        self.assertIs(sig["shut_off"], False)
        self.assertIs(sig["shut"], False)
        self.assertEqual(r["posts_after_rule"], 2)

    def test_a_locked_save_engages_the_lock(self):
        r = self.report["locked_save"]
        self.assertEqual(r["posts"], 1, self._dump("locked_save"))
        self.assertEqual(r["engaged"], [False], self._dump("locked_save"))
        self.assertEqual(r["kept"], "forex")
        self.assertGreaterEqual(r["unsaved"], 1)
        self.assertEqual(r["errors"], [])

    def test_filters_survive_a_rail_refresh_and_a_region_swap(self):
        """(2026-11-06, the review) The harness used to ignore the class
        filter when it counted, and asserted "3 shown" for an FX filter over
        an FX, a crypto and a stock card — a line no browser draws. It now
        applies the class filter as the stylesheet writes it: one shown, two
        hidden, and after another filter hides the FX card too, none."""
        r = self.report["survives"]
        self.assertEqual(r["cards"], 2, self._dump("survives"))
        self.assertTrue(any(s.startswith("1 shown · 1 hidden by your filters")
                            for s in r["status_marked"]), self._dump("survives"))
        self.assertEqual(r["cards_after_refresh"], 3, self._dump("survives"))
        self.assertEqual(r["class_after_refresh"], ["forex", "forex"])
        self.assertTrue(all(s.startswith("1 shown · 2 hidden by your filters")
                            for s in r["status_after_refresh"]),
                        self._dump("survives"))
        self.assertEqual(r["rule_buttons_after_refresh"], 3, self._dump("survives"))
        self.assertTrue(any(s.startswith("0 shown · 3 hidden")
                            for s in r["status_after_region_swap"]), self._dump("survives"))
        self.assertEqual(r["class_after_region_swap"], "forex")
        self.assertEqual(r["peek"], ["1", "1"], self._dump("survives"))
        self.assertEqual(r["errors"], [])

    def test_a_pass_is_never_counted_as_filtered(self):
        """(2026-11-06, the review) A passed card left the rail; the status
        line said "1 shown · 1 hidden by your filters" with no filter set,
        and the counts waited for the next sweep. The card is out of every
        count at once, and the rail asks the server again."""
        r = self.report["pass_counts"]
        self.assertEqual(r["status_before"], ["2 shown", "2 shown"],
                         self._dump("pass_counts"))
        self.assertEqual(r["status_after"], ["1 shown", "1 shown"],
                         self._dump("pass_counts"))
        self.assertEqual(r["peek_offered"], 0)
        self.assertEqual(r["passes"], 1)
        self.assertGreaterEqual(r["rails"], 1, "the rail did not ask again")
        self.assertEqual(r["status_after_refetch"], ["2 shown", "2 shown"],
                         self._dump("pass_counts"))
        self.assertEqual(r["passed_drawn"], 0)
        self.assertEqual(r["errors"], [])

    def test_an_expired_session_saves_nothing_and_says_so(self):
        """The login page answers 200 to an expired session: a save there
        is "not saved", and a pass stays in the outbox for the next load."""
        r = self.report["expired"]
        self.assertGreaterEqual(r["unsaved"], 1, self._dump("expired"))
        self.assertTrue(all("not saved" in s for s in r["status"]))
        self.assertEqual(r["passes"], 1)
        self.assertEqual(r["rails_after_pass"], 0, self._dump("expired"))
        self.assertEqual(len(r["outbox"]), 1)
        self.assertEqual(r["errors"], [])

    def test_a_save_carries_only_the_section_that_changed(self):
        r = self.report["sections"]
        self.assertEqual(r["first"], ["sig"], self._dump("sections"))
        self.assertEqual(r["second"], ["watch"], self._dump("sections"))
        self.assertEqual(r["errors"], [])

    def test_the_no_rule_toggle_mutes_and_is_kept(self):
        r = self.report["no_rule"]
        self.assertIn('[data-rule-key="r-none"]', r["style"], self._dump("no_rule"))
        self.assertEqual(r["pressed"], "false")
        self.assertEqual(r["saved"], [""])
        from dashboard.rail_prefs import clean, rule_off_css, rule_rows
        kept = clean({"sig": {"rules_off": ["", "x", ""]}})
        self.assertEqual(kept["sig"]["rules_off"], ["", "x"])
        self.assertIn('[data-rule-key="r-none"]', rule_off_css(kept))
        self.assertIn(("", "r-none", 0, False), rule_rows([], kept))
        self.assertEqual(r["errors"], [])

    def test_left_rows_a_filter_hides_are_counted(self):
        """(2026-11-06, the review) LEFT THE RAIL open under a class filter:
        the rows it hides are counted, and "show all" is offered."""
        r = self.report["left_tally"]
        self.assertEqual(r["gone_open"], "1", self._dump("left_tally"))
        self.assertEqual(r["left_rows"], 1)
        self.assertTrue(any("(1 in LEFT THE RAIL)" in s for s in r["status"]),
                        self._dump("left_tally"))
        self.assertEqual(r["peek_offered"], 1)
        self.assertEqual(r["errors"], [])

    def test_the_held_chip_counts_what_the_filters_show(self):
        """A refresh held while the operator reads, under an FX filter, that
        brings a stock card: nothing new shows, so the chip says it is
        filtered, never "1 new"."""
        r = self.report["held_filter"]
        self.assertEqual(r["chip"], {"shown": True, "text": "↻ 1 filtered"},
                         self._dump("held_filter"))
        self.assertEqual(r["probes_left"], 0)
        self.assertEqual(r["cards"], 2)
        self.assertEqual(r["errors"], [])

    def test_the_watchlist_rail_follows_the_swept_rows(self):
        """(2026-11-06, the review) The headband WATCHLIST rows are re-drawn
        by the 60s sweep; the rail's items were not, so after a fill the
        HELD filter and the held-first sort disagreed between the two."""
        r = self.report["watch_held"]
        self.assertEqual(r["before"], "0", self._dump("watch_held"))
        self.assertEqual(r["after"], "1", self._dump("watch_held"))
        self.assertIn("--o-held:1", r["style"])
        self.assertEqual(r["count_before"], "0")
        self.assertEqual(r["count_after"], "1")
        self.assertEqual(r["errors"], [])

    def test_an_empty_group_loses_its_header(self):
        r = self.report["empty_group"]
        self.assertEqual(r["group"], "1", self._dump("empty_group"))
        self.assertIn('#railSignals [data-sv-grp][data-asset-class="crypto"]',
                      r["style"] or "", self._dump("empty_group"))
        self.assertNotIn('[data-asset-class="forex"]', r["style"] or "")
        self.assertTrue(r["in_head"])
        self.assertEqual(r["errors"], [])

    def test_a_price_tick_still_paints_a_filtered_watchlist(self):
        r = self.report["tick"]
        self.assertTrue(r["held_found"], self._dump("tick"))
        self.assertEqual(r["watch_held"], ["held", "held"], self._dump("tick"))
        self.assertNotEqual(r["after"], r["before"], self._dump("tick"))
        self.assertTrue(r["after"].startswith("1.23"), self._dump("tick"))
        self.assertEqual(r["chg"], "+0.50%")
        self.assertEqual(r["errors"], [])


class TheFilterScriptIsSafeForTheHarnessTests(SimpleTestCase):
    def test_the_script_binds_nothing_to_a_row(self):
        """Clicks are delegated: no row is ever edited, moved or bound, so
        a refresh, a region swap or a price tick has nothing to undo."""
        js = (Path(settings.BASE_DIR) / "static" / "js" / "sv-rail-filters.js"
              ).read_text(encoding="utf-8")
        for word in (".wl-item", ".dh-item", ".ticker-item", "insertAdjacentHTML",
                     "toggleAttribute", "MutationObserver", "innerHTML ="):
            with self.subTest(word=word):
                self.assertNotIn(word, js)
        self.assertIn("'/api/rail-prefs/'", js)
