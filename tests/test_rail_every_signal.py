"""The signal rail lists every signal that can be acted on now (2026-11-06).

The operator, 2026-11-06: "les signaux dans le bandeau signal sont limiter a
un certain nombre non? Regler ce soucis car je ne peux agir sur certain
signaux si trop arrive d'un coup" (the signals in the signal band are capped,
so when many arrive at once he cannot act on some of them).

What it was (d81a035):
  * core/context_processors.py built the rail from the five newest active
    signals, `[:5]`, so a burst pushed earlier ones out before the operator
    could act on them;
  * the headband SIGNALS popup built its own five inside a cache keyed on the
    position book, so it could lag the rail and never listed more;
  * the rail head counted every active signal while the rail showed five;
  * the refresh dropped every call made while a fetch was in flight, swapped
    the cards under an open card, and swept every five minutes;
  * every 60s headband sweep rendered the whole shell, rail cards included,
    and threw the cards away.

Now the rail lists every actionable signal, newest first, scrolling inside
the rail, with a count per asset class; the headband popup is the same list
painted from the same fetch; a burst costs at most two fetches and never
ends partial; the swap waits while a card is read; the sweep renders no
card. DISPLAY ONLY: nothing here writes a Signal field.

Run with:  python manage.py test tests.test_rail_every_signal
"""
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import RequestFactory, SimpleTestCase, TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

HOST = "127.0.0.1"
NODE = shutil.which("node")
DJANGO_TAG_RE = re.compile(r"\{%|\{\{")
CARD_RE = re.compile(r'class="sr-signal-wrap[^"]*"\s+data-signal-id="(\d+)"')
ROW_RE = re.compile(r'class="ip-dd-row sv-sig-row"[^>]*?data-signal-id="(\d+)"')


# ── fixtures shared with tests/test_rail_lifecycle.py ─────────────────────

def _user(name="rail_u"):
    return get_user_model().objects.create_user(name, password="x")


def _inst(symbol="RLFXA", asset_class="forex"):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol + " name",
                                 "asset_class": asset_class})
    return inst


def _quote(inst, last, *, age_s=0):
    """A quote, fresh unless `age_s` says how old it is."""
    from market_data.models import LiveQuote
    LiveQuote.objects.update_or_create(
        instrument=inst, defaults={"last": Decimal(str(last)),
                                   "source": "test"})
    if age_s:
        LiveQuote.objects.filter(instrument=inst).update(
            updated_at=timezone.now() - timedelta(seconds=age_s))


def _sig(inst, *, rule="rl_rule", direction="bullish", score=0.7,
         entry="1.08000", stop="1.07500", target="1.09000", minutes_ago=0,
         active=True, signal_type="technical", **extra):
    """An active signal with a live plan: entry 1.08, risk 0.005, reward
    0.01 (reward:risk 2.00), born `minutes_ago`."""
    from signals.models import Signal
    s = Signal.objects.create(
        instrument=inst, signal_type=signal_type, direction=direction,
        urgency="medium", title=f"{inst.symbol} {direction}",
        description="d", rule_name=rule, score=score, sub_scores={},
        price_at_signal=Decimal(entry) if entry else Decimal("1"),
        suggested_entry=Decimal(entry) if entry else None,
        suggested_stop=Decimal(stop) if stop else None,
        suggested_target=Decimal(target) if target else None,
        is_active=active, **extra)
    if minutes_ago:
        Signal.objects.filter(pk=s.pk).update(
            created_at=timezone.now() - timedelta(minutes=minutes_ago))
        s.refresh_from_db()
    return s


def _ctx(user, **headers):
    from core.context_processors import sauron_context
    req = RequestFactory().get("/", **headers)
    req.user = user
    return sauron_context(req)


def _partial(client):
    resp = client.get("/partials/signal-rail/", HTTP_HOST=HOST)
    assert resp.status_code == 200, resp.status_code
    return resp.content.decode("utf-8", "replace")


def _page(client, url="/getting-started/", **headers):
    resp = client.get(url, HTTP_HOST=HOST, **headers)
    assert resp.status_code == 200, resp.status_code
    return resp.content.decode("utf-8", "replace")


def _cards(html):
    return [int(i) for i in CARD_RE.findall(html)]


def _shell():
    return (Path(settings.BASE_DIR) / "templates" / "base.html").read_text(
        encoding="utf-8")


def _upgrade3():
    blocks = re.findall(r"<script>(.*?)</script>", _shell(), re.S)
    hits = [b for b in blocks if "UPGRADE-3: WebSocket live ticks." in b]
    assert len(hits) == 1, len(hits)
    return hits[0]


class EverySignalIsOnTheRailTests(TestCase):
    def setUp(self):
        self.user = _user()
        self.client.force_login(self.user)

    def test_the_rail_lists_every_actionable_signal(self):
        """The `[:5]` slice was the only limit, and it is gone: twelve live
        plans are twelve cards, newest first."""
        inst = _inst()
        made = [_sig(inst, rule=f"rl_rule_{i}", minutes_ago=60 - i)
                for i in range(12)]
        html = _partial(self.client)
        self.assertEqual(_cards(html), [s.pk for s in reversed(made)])

    def test_a_burst_of_130_is_all_on_the_rail(self):
        """A writer that lands 130 signals at once (a replay, a bulk insert,
        a scanner pass) puts 130 cards on the rail, not five."""
        from signals.models import Signal
        insts = [_inst(f"RLBU{i:03d}", "crypto") for i in range(130)]
        Signal.objects.bulk_create([Signal(
            instrument=inst, signal_type="technical", direction="bullish",
            urgency="medium", title="burst", description="d",
            rule_name="rl_burst", score=0.6, sub_scores={},
            price_at_signal=Decimal("100"), suggested_entry=Decimal("100"),
            suggested_stop=Decimal("95"), suggested_target=Decimal("110"),
            is_active=True) for inst in insts])
        html = _partial(self.client)
        self.assertEqual(len(_cards(html)), 130)

    def test_the_headband_popup_is_the_rail(self):
        """The SIGNALS popup in the bottom bar is the rail's list: the same
        objects in the same order, and the page's rows carry the same ids."""
        inst = _inst()
        for i in range(7):
            _sig(inst, rule=f"rl_pop_{i}", score=0.5 + i / 20,
                 minutes_ago=90 - i * 7)
        ctx = _ctx(self.user)
        rail_ids = [s.id for s in ctx["panel_recent_signals"]]
        pop_ids = [row["id"] for row in ctx["panel_top_signals"]]
        self.assertEqual(len(rail_ids), 7)
        self.assertEqual(pop_ids, rail_ids)
        page = _page(self.client)
        rows = page.split('id="hbSignalRows"', 1)[1].split("▸ View Signals")[0]
        self.assertEqual([int(i) for i in ROW_RE.findall(rows)], rail_ids)

    def test_counts_per_asset_class(self):
        """The facet strip says how many there are per class, from the
        server over everything on the rail."""
        for i in range(3):
            _sig(_inst(f"RLFX{i}", "forex"), minutes_ago=10 + i)
        for i in range(2):
            _sig(_inst(f"RLCR{i}", "crypto"), entry="100", stop="95",
                 target="110", minutes_ago=20 + i)
        page = _page(self.client)
        self.assertIn('data-sv-fc="forex">3<', page)
        self.assertIn('data-sv-fc="crypto">2<', page)
        # Every class of the vocabulary is drawn, a zero hidden by CSS, so
        # a refresh can light one up without new markup.
        from core.constants import AssetClass
        for key, _label in AssetClass.CHOICES:
            self.assertIn(f'data-sv-fc="{key}"', page, key)
        self.assertIn('data-sv-fc="stock">0<', page)
        meta = json.loads(re.search(
            r'<div data-sv-rail-meta hidden><script[^>]*>(.*?)</script>',
            _partial(self.client), re.S).group(1))
        self.assertIn(["forex", 3], meta["classes"])
        self.assertIn(["crypto", 2], meta["classes"])

    def test_the_rail_count_is_what_the_rail_shows(self):
        """The head counted every active signal while the rail showed five.
        It now counts the cards, and its title says the rest."""
        inst = _inst()
        for i in range(5):
            _sig(inst, rule=f"rl_cnt_{i}", minutes_ago=30 + i)
        for i in range(2):          # past the 24 hours: they left the rail
            _sig(inst, rule=f"rl_old_{i}", minutes_ago=30 * 60 + i)
        page = _page(self.client)
        head = re.search(r'<span class="rh-count" id="railSigCount"'
                         r'[^>]*title="([^"]*)"[^>]*>(\d+)<', page)
        self.assertIsNotNone(head, "the rail head has no count of its own")
        self.assertEqual(head.group(2), "5")
        self.assertIn("5 on the rail", head.group(1))
        self.assertIn("7 active in the engine", head.group(1))
        self.assertIn("2 left in the last 24h", head.group(1))
        # The bottom bar's cell is the same number.
        cell = re.search(r'data-sv-live="hb-signals"[^>]*>([^<]*)<', page)
        self.assertEqual(cell.group(1).strip(), "5")

    def test_the_query_count_does_not_grow_with_the_rail(self):
        """Three cards or thirty cost the same queries: the acted join and
        the quote are batched, not asked per card."""
        insts = [_inst(f"RLQC{i:02d}") for i in range(30)]
        for inst in insts:
            _quote(inst, "1.08000")
        for inst in insts[:3]:
            _sig(inst, rule="rl_qc")
        _partial(self.client)                     # warm the session
        with CaptureQueriesContext(connection) as three:
            self.assertEqual(len(_cards(_partial(self.client))), 3)
        for inst in insts[3:]:
            _sig(inst, rule="rl_qc")
        with CaptureQueriesContext(connection) as thirty:
            self.assertEqual(len(_cards(_partial(self.client))), 30)
        self.assertEqual(len(three.captured_queries),
                         len(thirty.captured_queries),
                         "\n".join(q["sql"][:160] for q in
                                   thirty.captured_queries))

    def test_the_sweep_render_skips_the_cards_but_keeps_the_regions(self):
        """The 60s headband sweep fetches the whole shell and keeps only its
        regions. It now says so (X-SV-Sweep), and the shell renders no card
        for it — while every region, the SIGNALS count included, renders."""
        inst = _inst()
        _sig(inst, rule="rl_sw_a", minutes_ago=5)
        _sig(inst, rule="rl_sw_b", minutes_ago=6)
        normal = _page(self.client)
        self.assertIn('class="sr-signal-wrap', normal)
        swept = _page(self.client, HTTP_X_SV_SWEEP="1")
        self.assertNotIn('class="sr-signal-wrap', swept)
        self.assertNotIn('class="ip-dd-row sv-sig-row"', swept)
        found = set(re.findall(r'data-sv-live="([^"]+)"', swept))
        for name in ("hb-pf-value", "hb-pf-pnl", "hb-pf-sub", "hb-pf-detail",
                     "hb-pos-count", "hb-pos-sub", "hb-pos-detail",
                     "hb-bot-state", "hb-bot-sub", "hb-bot-detail",
                     "hb-signals", "hb-signals-sub", "hb-signals-detail",
                     "hb-news", "hb-alerts", "hb-watchlist", "hb-strategies",
                     "hb-funding", "hb-liq", "hb-dd", "hb-vol"):
            self.assertIn(name, found, name)
        cell = re.search(r'data-sv-live="hb-signals"[^>]*>([^<]*)<', swept)
        self.assertEqual(cell.group(1).strip(), "2")
        live = (Path(settings.BASE_DIR) / "templates" / "_partials"
                / "live_region.html").read_text(encoding="utf-8")
        self.assertIn("'X-SV-Sweep': '1'", live)


class TheRefreshKeepsUpWithABurstTests(SimpleTestCase):
    def test_a_burst_is_never_dropped(self):
        """A call made while a fetch is in flight used to be dropped, so a
        burst ended partial. Now it sets a flag and exactly one more fetch
        runs when the first settles; a socket burst is debounced."""
        js = _upgrade3()
        fn = js.split("function refreshSignalRail()")[1][:900]
        self.assertIn("railAgain = true", fn)
        self.assertIn("if (railAgain) { railAgain = false; refreshSignalRail(); }",
                      fn)
        self.assertIn("else if (msg.type === 'signal') railSoon();", js)
        soon = js.split("function railSoon()")[1][:300]
        # Exactly 400, not 4000 or 1400 (the clock itself is measured under
        # node: TheSwapWaitsForTheReaderTests.test_the_clock_is_measured).
        self.assertRegex(soon, r"\}, 400\);")

    def test_the_rail_sweeps_every_minute(self):
        """Price and age departures have no push: they reach the rail on the
        sweep, which runs every minute, as the headband sweep does."""
        seg = _shell().split("function refreshSignalRail()")[1][:4200]
        self.assertRegex(seg, r"refreshSignalRail\(\);\s*\}, 60000\)")
        self.assertNotIn("}, 300000)", seg.split("window.refreshSignalRail")[0])
        self.assertIn("visibilityState === 'visible'", seg)


# ── the swap waits for the reader: the page's own scripts under node ─────

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
  const timers = new Map(), errors = [], queue = [], sockets = [], store = {}, posts = [];
  const st = (f, ms, ...a) => { const id = ++seq; timers.set(id, { at: now + Math.max(0, +ms || 0), f, a, every: 0 }); return id; };
  const si = (f, ms, ...a) => { const id = ++seq; const every = Math.max(1, +ms || 0); timers.set(id, { at: now + every, f, a, every }); return id; };
  const clr = id => { timers.delete(id); };
  const later = (ms, v) => new Promise(res => { st(() => res(v), ms); });
  const fetch = (url, opts) => {
    if (url === '/partials/signal-rail/') {
      fetches += 1;
      const a = queue.length ? queue.shift() : { body: IN.answers[IN.answers.length - 1] };
      return later(a.delay || 10, { ok: true, status: 200, redirected: false, text: () => Promise.resolve(a.body) });
    }
    if (url === '/api/signal-rail/pass/') {
      posts.push(opts && opts.body);
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ ok: true }) });
    }
    return Promise.resolve({ ok: false, status: 404, redirected: false,
      text: () => Promise.resolve(''), json: () => Promise.reject(new Error('404')) });
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
    getComputedStyle: el => el.style,
    matchMedia: () => ({ matches: false, addEventListener() {}, addListener() {} }),
    SV: { popup: { opened() {}, closed() {} } },
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
  const body = () => doc.getElementById('railSignalsBody');
  const W = {
    doc, queue, posts,
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
    cards: () => body().querySelectorAll('.sr-signal-wrap[data-signal-id]').map(w => w.getAttribute('data-signal-id')),
    rows: () => { const r = doc.getElementById('hbSignalRows'); return r ? r.querySelectorAll('.sv-sig-row[data-signal-id]').map(w => w.getAttribute('data-signal-id')) : null; },
    chip: () => { const c = doc.getElementById('railHeld'); return c ? { shown: !c.hasAttribute('hidden'), text: c.textContent.trim() } : null; },
    text: sel => { const e = doc.querySelector(sel); return e ? e.textContent.trim() : null; },
    shown: () => body().querySelectorAll('.sr-popup.show').length,
    wsSend(msg) { const s = sockets[sockets.length - 1]; s.onmessage({ data: JSON.stringify(msg) }); },
  };
  return W;
}

async function readerHolds() {
  const W = boot();
  const page = W.doc.getElementById('page-text');
  const out = { cards_before: W.cards(), chip_before: W.chip() };
  const card = W.doc.querySelector('#railSignalsBody .sr-signal-wrap a.sr-signal');
  W.pointTo(card.querySelector('.sr-sym') || card); await W.advance(600);
  out.popup_shown = W.shown();
  W.queue.push({ body: IN.answers[0] });
  W.wsSend({ type: 'signal', data: { id: 1 } }); await W.advance(1200);
  out.fetches_while_read = W.fetches();
  out.cards_while_read = W.cards();
  out.chip_while_read = W.chip();
  W.pointTo(page); await W.advance(1200);
  out.cards_after = W.cards();
  out.chip_after = W.chip();
  out.rows_after = W.rows();
  out.hb_signals = W.text('[data-sv-live="hb-signals"]');
  out.hb_sub = W.text('[data-sv-live="hb-signals-sub"]');
  out.rail_count = W.text('#railSigCount');
  out.slid_in = W.doc.querySelectorAll('#railSignalsBody .sr-signal-wrap.sr-slide-in').map(w => w.getAttribute('data-signal-id'));
  out.mirror_left_in_body = W.doc.querySelectorAll('#railSignalsBody [data-sv-mirror]').length;
  out.errors = W.errors();
  return out;
}

async function chipApplies() {
  const W = boot();
  const card = W.doc.querySelector('#railSignalsBody .sr-signal-wrap a.sr-signal');
  W.pointTo(card); await W.advance(300);
  W.queue.push({ body: IN.answers[0] });
  W.wsSend({ type: 'signal' }); await W.advance(1200);
  const out = { cards_while_read: W.cards(), chip_while_read: W.chip() };
  const chip = W.doc.getElementById('railHeld');
  D.dispatch(chip, new D.Event('click', { bubbles: true }));
  await W.advance(50);
  out.cards_after_click = W.cards();
  out.chip_after_click = W.chip();
  out.errors = W.errors();
  return out;
}

async function burst() {
  const W = boot();
  W.queue.push({ body: IN.answers[0], delay: 1500 }, { body: IN.answers[1], delay: 100 });
  for (let i = 0; i < 6; i++) { W.wsSend({ type: 'signal' }); await W.advance(60); }
  await W.advance(700);
  const out = { fetches_after_first_wave: W.fetches() };
  for (let i = 0; i < 6; i++) { W.wsSend({ type: 'signal' }); await W.advance(60); }
  await W.advance(5000);
  out.fetches = W.fetches();
  out.cards = W.cards();
  out.rows = W.rows();
  out.errors = W.errors();
  return out;
}

/* The clock, measured rather than read off the code (2026-11-06, the
   review): a socket announcement waits 400ms for the rest of a burst, and
   the sweep asks every minute, never while the tab is hidden, and at once
   when it comes back. */
async function cadence() {
  const out = {};
  let W = boot();
  W.wsSend({ type: 'signal' }); await W.advance(399);
  out.at_399ms = W.fetches();
  await W.advance(2);
  out.at_401ms = W.fetches();
  W = boot();
  await W.advance(59990);
  out.sweep_before_1min = W.fetches();
  await W.advance(20);
  out.sweep_at_1min = W.fetches();
  W.doc.hidden = true; W.doc.visibilityState = 'hidden';
  await W.advance(60000);
  out.sweep_hidden = W.fetches();
  W.doc.hidden = false; W.doc.visibilityState = 'visible';
  D.dispatch(W.doc, new D.Event('visibilitychange', {}));
  await W.advance(50);
  out.on_return = W.fetches();
  out.errors = W.errors();
  return out;
}

(async () => {
  const out = {};
  out.reader_holds = await readerHolds();
  out.chip_applies = await chipApplies();
  out.burst = await burst();
  out.cadence = await cadence();
  process.stdout.write(JSON.stringify(out));
})().catch(e => { console.error(e && e.stack || e); process.exit(1); });
"""

RAIL_FROM = '<div class="rail-section sig-section" id="railSignals"'
RAIL_TO = '<div class="rail-resizer"'
BAR_FROM = '<div class="info-panel-wrap" id="infoPanelWrap">'
BAR_TO = "{% url 'getting_started' as live_url %}"


def _scripts(raw):
    """Phase 62.1 and 64.4 (the rail's card binder and its passes) and the
    UPGRADE-3 block, verbatim."""
    rail = raw[raw.index("/* ── Phase 62.1"):raw.index("/* ── TAKE TRADE")]
    assert not DJANGO_TAG_RE.search(rail), "Phase 62.1-64.4 carries Django tags"
    up3 = _upgrade3()
    assert not DJANGO_TAG_RE.search(up3), "UPGRADE-3 carries Django tags"
    return [{"label": "base.html Phase 62.1-64.4", "source": rail},
            {"label": "base.html UPGRADE-3", "source": up3}]


def _inputs():
    """The rail and the bottom bar as Django renders them for one signal,
    then the partial's answers after a second and a third arrive."""
    from django.template import engines
    from django.test import Client
    eng = engines["django"]
    raw = _shell()
    user = _user("rail_node")
    client = Client()
    client.force_login(user)
    inst = _inst("RLNDA", "forex")
    _sig(inst, rule="rl_node_a", minutes_ago=30)
    ctx = dict(_ctx(user))
    ctx.update({"user": user, "sv_sweep": False})
    rail = raw[raw.index(RAIL_FROM):raw.index(RAIL_TO)]
    bar = raw[raw.index(BAR_FROM):raw.index(BAR_TO)]
    page = (eng.from_string("{% load sauron_tags static %}" + bar).render(ctx)
            + '<main id="elsewhere"><p id="page-text">The page</p></main>'
            + '<div class="signals-rail open" id="signalsRail">'
            + eng.from_string("{% load sauron_tags static %}" + rail).render(ctx)
            + "</div>")
    answers = []
    _sig(_inst("RLNDB", "crypto"), rule="rl_node_b", entry="100",
         stop="95", target="110", minutes_ago=2)
    answers.append(_partial(client))
    _sig(_inst("RLNDC", "crypto"), rule="rl_node_c", entry="100",
         stop="95", target="110", minutes_ago=1)
    answers.append(_partial(client))
    return {"page": page, "answers": answers, "scripts": _scripts(raw)}


def _report(inputs):
    from tests.test_headband_hover_lives import DOM_JS
    tmp = Path(tempfile.mkdtemp(prefix="sv-rail-"))
    try:
        (tmp / "dom.js").write_text(DOM_JS, encoding="utf-8")
        (tmp / "run.js").write_text(RUN_JS, encoding="utf-8")
        (tmp / "input.json").write_text(json.dumps(inputs), encoding="utf-8")
        proc = subprocess.run([NODE, str(tmp / "run.js"), str(tmp / "input.json")],
                              capture_output=True, text=True, timeout=300,
                              encoding="utf-8")
        if proc.returncode != 0:
            raise AssertionError("the rail runner failed: %s" % proc.stderr[:3000])
        return json.loads(proc.stdout)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@unittest.skipUnless(NODE, "node is not installed on this machine")
class TheSwapWaitsForTheReaderTests(TestCase):
    """The page's own scripts, on the rail and the bottom bar exactly as
    Django renders them, with the partial's real answers."""

    @classmethod
    def setUpTestData(cls):
        inputs = _inputs()
        cls.ids = [int(i) for i in CARD_RE.findall(inputs["answers"][1])]
        cls.report = _report(inputs)

    def _dump(self, key):
        return json.dumps(self.report[key], indent=1, ensure_ascii=False)[:6000]

    def test_the_swap_waits_for_the_reader(self):
        """A card open under the hand holds the fetched rail: the chip says
        what waits, and the rail lands the moment the hand leaves — the
        headband rows, the counts and the slide-in with it."""
        r = self.report["reader_holds"]
        newest, middle, first = (str(i) for i in self.ids)
        self.assertEqual(r["cards_before"], [first], self._dump("reader_holds"))
        self.assertEqual(r["popup_shown"], 1, self._dump("reader_holds"))
        self.assertEqual(r["fetches_while_read"], 1, self._dump("reader_holds"))
        self.assertEqual(r["cards_while_read"], [first],
                         "the rail was swapped under an open card:\n"
                         + self._dump("reader_holds"))
        self.assertEqual(r["chip_while_read"], {"shown": True, "text": "↻ 1 new"},
                         self._dump("reader_holds"))
        self.assertEqual(r["cards_after"], [middle, first], self._dump("reader_holds"))
        self.assertEqual(r["chip_after"]["shown"], False)
        self.assertEqual(r["rows_after"], [middle, first])
        self.assertEqual(r["hb_signals"], "2")
        self.assertEqual(r["hb_sub"], "2 long · 0 short")
        self.assertEqual(r["rail_count"], "2")
        self.assertEqual(r["slid_in"], [middle])
        self.assertEqual(r["mirror_left_in_body"], 0)
        self.assertEqual(r["errors"], [])

    def test_the_chip_applies_what_waits_at_once(self):
        r = self.report["chip_applies"]
        _newest, middle, first = (str(i) for i in self.ids)
        self.assertEqual(r["cards_while_read"], [first], self._dump("chip_applies"))
        self.assertTrue(r["chip_while_read"]["shown"], self._dump("chip_applies"))
        self.assertEqual(r["cards_after_click"], [middle, first],
                         self._dump("chip_applies"))
        self.assertFalse(r["chip_after_click"]["shown"])
        self.assertEqual(r["errors"], [])

    def test_the_clock_is_measured(self):
        """(2026-11-06, the review) The debounce and the sweep, by the
        page's own timers rather than by the text of the code."""
        r = self.report["cadence"]
        self.assertEqual(r["at_399ms"], 0, self._dump("cadence"))
        self.assertEqual(r["at_401ms"], 1, self._dump("cadence"))
        self.assertEqual(r["sweep_before_1min"], 0, self._dump("cadence"))
        self.assertEqual(r["sweep_at_1min"], 1, self._dump("cadence"))
        self.assertEqual(r["sweep_hidden"], 1, self._dump("cadence"))
        self.assertEqual(r["on_return"], 2, self._dump("cadence"))
        self.assertEqual(r["errors"], [])

    def test_a_burst_costs_two_fetches_and_ends_complete(self):
        """Twelve announcements, two of them while a fetch is in flight:
        two fetches, and the rail ends on the last answer."""
        r = self.report["burst"]
        self.assertEqual(r["fetches_after_first_wave"], 1, self._dump("burst"))
        self.assertEqual(r["fetches"], 2, self._dump("burst"))
        self.assertEqual(r["cards"], [str(i) for i in self.ids], self._dump("burst"))
        self.assertEqual(r["rows"], [str(i) for i in self.ids])
        self.assertEqual(r["errors"], [])
