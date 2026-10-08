"""The chart levels' layer, against a fake chart (2026-10-07).

The operator: "could we improve the visibility and design of liquidity
areas and pivot points etc. They are too similar and messy at the moment."

Every level is now ONE series primitive (the LevelLayer): its shapes paint
under the candles and under every price line, its chips over them, and no
level is a price line any more — so the operator's money (entry, SL, TP)
stays the loudest thing on the chart. This module runs the widget's real
script against the stub page and fake lightweight-charts of
tests/test_chart_signal_markers.py (its WIDGET_PRELUDE), extended by
LEVELS_PATCH below with what the layer needs: primitives that record their
attach/detach order, a linear price scale (1 pip = 2 px), logical x,
localStorage, matchMedia, a MutationObserver stub, the levels' key under
the chart, a counted getComputedStyle, a double-click subscription with
dblclick(), and renderLayer(), which plays the library's two paint passes
into a recording 2D context.

  the layer      one primitive on the candles, none elsewhere, and no level
                 price line; re-attached on the new series after a type
                 switch, detached BEFORE the old series is removed;
  the fallback   without primitives the Asian range is two faint untitled
                 lines on intraday frames, none on daily ones;
  the money      the soft stop is a quiet untitled line only when it is not
                 the stop; the entry 3 px, SL and TP 2 px solid;
  the switches   LEVELS off leaves exactly the position's lines; the key's
                 kind toggles and Show all persist in the prefs; an answer
                 chip focuses its level;
  the pointer    a tap on a level opens its card and the next tap closes
                 it, a quick one too (the library sends it as a double tap;
                 a mouse's double click stays the library's); a pin dims
                 the levels but never the hunt and the draw; a level under
                 the pointer still glows while pinned;
  the keep-outs  the chips stay clear of the crosshair legend, the
                 bar-close countdown and the newest candles; the ASIA
                 label of the price lines' title boxes (not the whole
                 lane), on its box or not at all;
  the paint      the palette is read once per data paint, and again after
                 the theme changes; the axis takes the bars' decimals when
                 the page has no count; a phone width re-plans the entry's
                 title and the key.

Run with:  python manage.py test tests.test_chart_levels_widget
"""
import copy
import unittest
from datetime import date, datetime, timedelta, timezone as dt_timezone

from django.test import SimpleTestCase

from tests.test_chart_levels_language import FIXTURE_ROWS, PATH, _js_round, _meets
from tests.test_chart_signal_markers import (
    NODE, WIDGET_PRELUDE, _blocks, _node, _payload, widget)

PREF_KEY = "sv-chart:t:EURUSD"
ASIA_OPENED = int(datetime(2026, 10, 7, 0, 0, tzinfo=dt_timezone.utc).timestamp())
ASIA_CLOSED = ASIA_OPENED + 4 * 3600
HUNT_ID = "sv-lvl-pool-1.08226000000"
DRAW_ID = "sv-lvl-pool-1.08954000000"
FAR_TICK_ID = "sv-lvl-swing-1.07676000000"
EQH_ID = "sv-lvl-pool-1.09200000000"


def y(price):
    """LEVELS_PATCH's price scale: 1 pip is 2 px, 1.0855 at y 200."""
    return 200 - (price - 1.0855) * 20000


def fade(d, theme="dark"):
    """svLevels.fade: 1 up to 1.5 ATR, then down to the floor at 4.5."""
    if d <= 1.5:
        return 1
    floor = 0.5 if theme == "dark" else 0.7
    return 1 - min(1, (d - 1.5) / 3) * (1 - floor)


# ── LEVELS_PATCH: what the level layer needs of the fake chart ──────────
# Appended after WIDGET_PRELUDE and before this module's scenario; set
# here only (the signal markers' harness keeps its constant 100 px scale).
LEVELS_PATCH = r"""
/* ── LEVELS_PATCH ──────────────────────────────────────────────────── */
log.seq = 0; log.updates = 0; log.ops = []; log.gcs = 0;
if (!M.noPrims) {
    Series.prototype.attachPrimitive = function (p) {
        (this.prims = this.prims || []).push(p);
        log.ops.push({ op: 'attach', kind: this.kind, order: log.seq++ });
        if (p.attached) p.attached({ chart: chart, series: this,
                                     requestUpdate: function () { log.updates++; } });
    };
    Series.prototype.detachPrimitive = function (p) {
        this.prims = (this.prims || []).filter(function (x) { return x !== p; });
        log.ops.push({ op: 'detach', kind: this.kind, order: log.seq++ });
        if (p.detached) p.detached();
    };
}
const _removeSeries = chart.removeSeries;
chart.removeSeries = function (s) {
    log.ops.push({ op: 'removeSeries', kind: s && s.kind, order: log.seq++ });
    return _removeSeries.call(this, s);
};
/* the options each series was created with */
['addCandlestickSeries', 'addHistogramSeries', 'addLineSeries', 'addAreaSeries'].forEach(function (name) {
    const make = chart[name];
    chart[name] = function (o) {
        const s = make.call(this, o);
        s.created = JSON.parse(JSON.stringify(o || {}));
        return s;
    };
});
/* lightweight-charts 4.1 sends a second tap (or click) inside its
   double-tap window as a double click, never as a click. */
handlers.dbl = [];
chart.subscribeDblClick = function (fn) { handlers.dbl.push(fn); };
const dblclick = function (x, y, time, objectId) {
    handlers.dbl.forEach(function (f) { f(param(x, y, time, objectId)); });
};
Series.prototype.priceToCoordinate = function (p) { return 200 - (p - 1.0855) * 20000; };
Series.prototype.applyOptions = function (o) {
    (this.opts = this.opts || []).push(JSON.parse(JSON.stringify(o || {})));
};
ts.logicalToCoordinate = function (i) { return 20 + i * 10; };
/* Another series' point before bars[0] (a measure line kept across a
   background refresh): every logical index is one bar off. The levels go
   by time, so nothing of theirs may move. */
if (M.shiftLogical) ts.logicalToCoordinate = function (i) { return 20 + (i - 1) * 10; };
/* a price line answers options() as the library's does: what it was
   created with, over the library's defaults */
const _createPriceLine = Series.prototype.createPriceLine;
Series.prototype.createPriceLine = function (o) {
    const pl = _createPriceLine.call(this, o);
    pl.options = function () { return Object.assign({ axisLabelVisible: true, title: '' }, pl.o); };
    return pl;
};

/* The toolbar's indicator buttons (the volume's) */
const indButtons = ['volume'].map(function (k) { const b = new El(''); b.dataset.ind = k; return b; });
const _containerAll = els[ID + '-container'].querySelectorAll;
els[ID + '-container'].querySelectorAll = function (sel) {
    return sel === '.sv-ind-btn' ? indButtons : _containerAll.call(this, sel);
};
const toggleIndBtn = function (k) {
    indButtons.find(function (b) { return b.dataset.ind === k; }).l.click.forEach(function (f) { f({}); });
};

const STORE = {};
if (M.prefs) STORE[M.prefKey] = JSON.stringify(M.prefs);
sandbox.localStorage = {
    getItem: function (k) { return Object.prototype.hasOwnProperty.call(STORE, k) ? STORE[k] : null; },
    setItem: function (k, v) { STORE[k] = String(v); }
};
const savedPrefs = function () { return STORE[M.prefKey] ? JSON.parse(STORE[M.prefKey]) : null; };
sandbox.matchMedia = function () { return { matches: !!M.coarse }; };
let MO = null;
sandbox.MutationObserver = function (cb) {
    MO = { cb: cb };
    this.observe = function (el, opts) { MO.el = el; MO.opts = opts; };
};
const _gcs = sandbox.getComputedStyle;
sandbox.getComputedStyle = function () { log.gcs++; return _gcs.apply(null, arguments); };

/* Attributes, recorded (aria-pressed on the key's buttons). */
El.prototype.setAttribute = function (k, v) { (this.attrs = this.attrs || {})[k] = String(v); };
El.prototype.getAttribute = function (k) {
    return (this.attrs && Object.prototype.hasOwnProperty.call(this.attrs, k)) ? this.attrs[k] : null;
};
/* The levels' key under the chart. */
const lvlLegend = new El(ID + '-lvl-legend');
lvlLegend.hidden = true;
const keyEls = {};
['levels', 'below', 'above', 'pool', 'swing', 'asia', 'round', 'all'].forEach(function (k) {
    const b = new El(''); b.dataset.lvl = k; keyEls[k] = b;
});
const countEl = new El(''), countOf = { pool: new El(''), swing: new El(''), round: new El('') };
lvlLegend.querySelector = function (sel) {
    let m = /^\[data-lvl="(\w+)"\]$/.exec(sel);
    if (m) return keyEls[m[1]] || null;
    if (sel === '[data-role="count"]') return countEl;
    m = /^\[data-count="(\w+)"\]$/.exec(sel);
    return m ? (countOf[m[1]] || null) : null;
};
els[ID + '-lvl-legend'] = lvlLegend;
const keyEvent = function (type, k) {
    (lvlLegend.l[type] || []).forEach(function (f) {
        f({ target: { closest: function () { return k ? keyEls[k] : null; } } });
    });
};
const keyClick = function (k) { keyEvent('click', k); };
const keyState = function () {
    const out = { hidden: lvlLegend.hidden, cls: Array.from(lvlLegend.classList.s),
                  count: countEl.textContent, counts: {}, keys: {} };
    Object.keys(countOf).forEach(function (k) { out.counts[k] = countOf[k].textContent; });
    Object.keys(keyEls).forEach(function (k) {
        const b = keyEls[k];
        out.keys[k] = { pressed: b.getAttribute('aria-pressed'), hidden: b.hidden,
                        text: b.textContent, id: b.dataset.id, kind: b.dataset.kind,
                        title: b.title };
    });
    return out;
};

/* The library's paint passes, into a recording 2D context: every op with
   the state it drew in (fill, stroke, width, dash, font) and its args. */
const CTX = { calls: {}, texts: [], ops: [], _dash: [], font: '', globalAlpha: 1, fillStyle: '',
              strokeStyle: '', lineWidth: 1, textAlign: 'start', textBaseline: 'alphabetic' };
['fillRect', 'strokeRect', 'beginPath', 'moveTo', 'lineTo', 'stroke', 'arc', 'fill', 'rect',
 'clip', 'save', 'restore', 'setLineDash', 'fillText'].forEach(function (n) {
    CTX[n] = function () {
        CTX.calls[n] = (CTX.calls[n] || 0) + 1;
        if (n === 'setLineDash') CTX._dash = Array.from(arguments[0] || []);
        if (n === 'fillText') CTX.texts.push(String(arguments[0]));
        CTX.ops.push({ op: n, fill: CTX.fillStyle, stroke: CTX.strokeStyle, lw: CTX.lineWidth,
                       dash: CTX._dash.slice(), font: CTX.font, alpha: CTX.globalAlpha,
                       args: Array.from(arguments) });
    };
});
CTX.measureText = function (t) { return { width: 6.1 * String(t).length }; };
let RATIO = 1;
const TARGET = {
    useBitmapCoordinateSpace: function (cb) {
        cb({ context: CTX, mediaSize: { width: 740, height: 384 },
             bitmapSize: { width: Math.round(740 * RATIO), height: Math.round(384 * RATIO) },
             horizontalPixelRatio: RATIO, verticalPixelRatio: RATIO });
    }
};
const primsOf = function (s) { return (s && s.prims) ? s.prims.length : 0; };
const prim = function () { const s = candle(); return (s && s.prims && s.prims[0]) || null; };
/* As the pane paints (LWC 4.1 PaneWidget._internal_paint): the main
   canvas's normal views, every drawBackground then every draw, then the
   top canvas's views. */
const renderLayer = function () {
    const p = prim();
    if (!p) return null;
    CTX.texts = []; CTX.ops = [];
    const views = p.paneViews();
    const normal = views.filter(function (v) { return v.zOrder() === 'normal'; }).map(function (v) { return v.renderer(); });
    const top = views.filter(function (v) { return v.zOrder() === 'top'; }).map(function (v) { return v.renderer(); });
    normal.forEach(function (r) { if (r.drawBackground) r.drawBackground(TARGET); });
    normal.forEach(function (r) { r.draw(TARGET); });
    top.forEach(function (r) { if (r.drawBackground) r.drawBackground(TARGET); });
    top.forEach(function (r) { r.draw(TARGET); });
    return p;
};
const ops = function () { return JSON.parse(JSON.stringify(CTX.ops)); };
const geom = function () { const p = prim(); return p && p.geom ? JSON.parse(JSON.stringify(p.geom)) : null; };
/* the hover the widget hands the layer, read through its next geometry */
const geomHover = function () {
    renderLayer();
    const g = geom();
    return g ? g.bands.concat(g.ticks, g.rays, g.rounds).filter(function (s) { return s.hot; })
                 .map(function (s) { return s.id; }) : null;
};
const lineOpts = function () {
    return candle().lines.map(function (l) {
        return { title: l.o.title, price: l.o.price, style: l.o.lineStyle, width: l.o.lineWidth,
                 axis: l.o.axisLabelVisible, color: l.o.color,
                 labelColor: l.o.axisLabelColor || null, labelText: l.o.axisLabelTextColor || null };
    });
};
const LIGHT = { '--accent': '#00994d', '--accent-red': '#e83030', '--text-secondary': '#4a6a4a',
                '--text-muted': '#8aaa8a', '--accent-gold-ink': '#8a6a00', '--border': '#c0d0c0',
                '--bg-void': '#f0f2f0', '--text-primary': '#1a2a1a', '--lvl-swing': '#1f6fb2',
                '--lvl-session': '#8840d0' };
"""

LEVELS_SCENARIO = r"""
const SCENES = {};

/* The default: candles on the daily frame, the position, the levels and
   the Asian range in the reply. */
SCENES.main = async function (R) {
    const p0 = prim();
    R.first = { prims: chart.series.map(function (s) { return [s.kind, primsOf(s)]; }),
                others: otherLines(), lines: lineOpts(),
                items: p0 ? p0.data.items.length : null, asia: p0 ? p0.data.asia : null,
                zOrder: p0 ? p0.paneViews().map(function (v) { return v.zOrder(); }) : null,
                sameViews: p0 ? p0.paneViews() === p0.paneViews() : null,
                hasHitTest: p0 ? typeof p0.hitTest : null,
                hasAutoscale: p0 ? typeof p0.autoscaleInfo : null,
                created: candle().created,
                volume: chart.series.filter(function (s) { return s.kind === 'hist'; })[0].created,
                volOpts: chart.series.filter(function (s) { return s.kind === 'hist'; })[0].opts || [],
                volRows: chart.series.filter(function (s) { return s.kind === 'hist'; })[0].rows.length,
                key: keyState() };
    renderLayer();
    R.render = { geom: geom(), texts: CTX.texts.slice(), calls: JSON.parse(JSON.stringify(CTX.calls)),
                 key: keyState() };
    const g0 = log.gcs;
    for (let i = 0; i < 20; i++) renderLayer();
    R.gcsPerTwentyPaints = log.gcs - g0;
    /* Pin the BUY signal of 2026-08-10. */
    click(111, 200, M.barS1);
    renderLayer();
    R.pinned = { geom: geom(), cls: card.className, sigLines: sigLines(), lines: lineOpts() };
    /* Peek: the pointer on the EQH 1.09200 band while pinned. */
    const u0 = log.updates;
    move(700, M.yEqh, M.barFar);
    R.peekRequested = log.updates - u0;
    renderLayer();
    R.peek = { geom: geom(), cls: card.className, hidden: card.hidden };
    move(700, M.yEqh + 1, M.barFar);
    R.peekSameIdRequests = log.updates - u0;
    /* The pointer leaves the band for empty space, and clicks there: unpinned. */
    move(600, M.yEmpty, M.barFar);
    R.peekLeft = geomHover();
    click(600, M.yEmpty, M.barFar);
    renderLayer();
    R.unpinned = { geom: geom(), sigLines: sigLines() };
    /* A chart-type switch: the candles go, the layer follows. */
    chartType('line');
    for (let i = 0; i < 6; i++) await flush();
    R.swapped = { ops: log.ops.slice(), prims: chart.series.map(function (s) { return [s.kind, primsOf(s)]; }),
                  kind: candle().kind, others: otherLines(), created: candle().created,
                  items: prim() ? prim().data.items.length : null };
    /* The theme changes under the live chart. */
    document.body.classList.add('light-mode');
    Object.keys(LIGHT).forEach(function (k) { TOKENS[k] = LIGHT[k]; });
    const g1 = log.gcs;
    if (MO) MO.cb([{ attributeName: 'class' }]);
    renderLayer();
    R.light = { theme: prim() && prim().geom ? prim().geom.theme : null, gcs: log.gcs - g1,
                observed: MO ? MO.opts : null };
};

/* The volume histogram: drawn only when the tape has a volume. */
SCENES.volume = async function (R) {
    const h = chart.series.filter(function (s) { return s.kind === 'hist'; })[0];
    R.opts = h.opts || []; R.rows = h.rows.length;
    toggleIndBtn('volume'); toggleIndBtn('volume');           /* off and on again from the toolbar */
    R.optsAfter = h.opts || [];
};

/* Levels switched off in the saved prefs. */
SCENES.off = async function (R) {
    const p0 = prim();
    R.off = { others: otherLines(), items: p0 ? p0.data.items : null, asia: p0 ? p0.data.asia : 'none',
              key: keyState() };
    renderLayer();
    R.off.geom = geom();
    /* ...and back on from the key's LEVELS chip (the toolbar's twin). */
    keyClick('levels');
    for (let i = 0; i < 2; i++) await flush();
    renderLayer();
    R.on = { items: prim().data.items.length, key: keyState(), saved: savedPrefs().indicators,
             bands: geom().bands.length };
};

/* No primitives at all (a stale library): the lines are the fallback. */
SCENES.noPrims = async function (R) {
    R.lines = lineOpts();
    R.others = otherLines();
    R.prims = chart.series.map(function (s) { return primsOf(s); });
};

/* Lines only: the position's three (and its soft stop). */
SCENES.lines = async function (R) {
    R.lines = lineOpts();
    R.others = otherLines();
};

/* A finger: a tap on a level opens its card, the next tap closes it. */
SCENES.tap = async function (R) {
    renderLayer();
    click(700, M.yHunt, M.barFar);
    R.opened = cardState();
    renderLayer();
    R.glow = geom().bands.filter(function (b) { return b.hot; }).map(function (b) { return b.id; });
    click(700, M.yHunt, M.barFar);
    R.closed = cardState();
    R.closedGlow = geomHover();            /* a finger sends no move to clear it */
    click(700, M.yHunt, M.barFar);
    R.reopened = cardState();
    click(700, M.yEmpty, M.barFar);
    R.elsewhere = cardState();
    /* 5 px under the band's bottom edge: inside a finger's 12 px reach */
    renderLayer();
    R.underGeom = geom();
    click(700, M.yHuntLow + 5, M.barFar);
    R.under = cardState();
    R.underGlow = geomHover();
    /* a dot pinned after a level card: the pin's dim reaches that level */
    click(111, 200, M.barS1);
    R.pin = { cls: card.className, glow: geomHover() };
    click(600, M.yEmpty, M.barFar);
    /* a refresh hides the card a tap opened: the glow goes with it */
    click(700, M.yHunt, M.barFar);
    R.beforeRefresh = { card: cardState(), glow: geomHover() };
    await refresh(M.payload);
    R.afterRefresh = { card: cardState(), glow: geomHover() };
};

/* A mouse: its reach is 6 px. */
SCENES.hoverTol = async function (R) {
    renderLayer();
    R.geom = geom();
    move(700, M.yHuntLow + 5, M.barFar);
    R.five = cardState();
    move(700, M.yHuntLow + 2, M.barFar);
    R.two = cardState();
};

/* A chip beside a money line: the chip is hit before the line. */
SCENES.chipTap = async function (R) {
    renderLayer();
    R.geom = geom();
    if (M.tapAt) {
        click(M.tapAt[0], M.tapAt[1], M.barFar);
        R.card = cardState();
        R.glow = geomHover();
    }
};

/* The pointer on a position line: its card, with where the money meets
   the levels. */
SCENES.posHover = async function (R) {
    renderLayer();
    R.geom = geom();
    move(M.at[0], M.at[1], M.barFar);
    R.card = cardState();
};

/* A sticky answer focus, then a refresh that names another level there. */
SCENES.focusRefresh = async function (R) {
    renderLayer();
    keyClick('above');
    renderLayer();
    R.sticky = { key: keyState(), geom: geom() };
    await refresh(M.payload2);
    renderLayer();
    R.after = { key: keyState(), geom: geom() };
};

/* Heikin-Ashi: the keep-outs follow the candles as drawn. */
SCENES.heikin = async function (R) {
    chartType('heikin');
    for (let i = 0; i < 6; i++) await flush();
    renderLayer();
    R.geom = geom();
    R.bars = BARS.map(function (b) { return { open: b.open, high: b.high, low: b.low, close: b.close }; });
};

/* Display scaling: the chips' font and borders on the bitmap. */
SCENES.dpr = async function (R) {
    R.out = {};
    [1, 1.25, 2].forEach(function (k) {
        RATIO = k;
        renderLayer();
        R.out[String(k)] = { geom: geom(), ops: ops().filter(function (o) {
            return o.op === 'fillText' || o.op === 'strokeRect' || o.op === 'fillRect'; }) };
    });
    RATIO = 1;
};

/* Levels switched off in the saved prefs. */

/* A finger's second tap inside the library's 500 ms window: a double tap. */
SCENES.doubleTap = async function (R) {
    R.subscribed = handlers.dbl.length;
    renderLayer();
    click(700, M.yHunt, M.barFar);
    R.opened = cardState();
    dblclick(700, M.yHunt, M.barFar);
    R.closed = cardState();
    /* A double tap on a dot pins it as a tap does. */
    dblclick(111, 200, M.barS1);
    R.dot = { card: cardState(), sigLines: sigLines() };
};
/* A mouse: its double click is the library's, it neither unpins nor opens. */
SCENES.mouseDouble = async function (R) {
    R.subscribed = handlers.dbl.length;
    click(111, 200, M.barS1);
    R.pinned = { card: cardState(), sigLines: sigLines() };
    dblclick(600, M.yEmpty, M.barFar);
    R.after = { card: cardState(), sigLines: sigLines() };
};
/* What the chips kept clear of: the page's boxes and the newest candles. */
SCENES.keep = async function (R) {
    renderLayer();
    R.geom = geom();
    R.bars = BARS.map(function (b) { return { high: b.high, low: b.low }; });
};

/* The axis and the decimals. */
SCENES.axis = async function (R) {
    const c = candle();
    R.created = c.created;
    R.opts = c.opts || [];
};

/* The key's switches, saved with the other toggles. */
SCENES.toggles = async function (R) {
    renderLayer();
    R.before = { geom: geom(), key: keyState(), ops: ops(), texts: CTX.texts.slice() };
    keyClick('pool');
    R.saved = savedPrefs();
    renderLayer();
    R.after = { geom: geom(), key: keyState() };
};
SCENES.toggles2 = async function (R) {
    renderLayer();
    R.booted = { geom: geom(), key: keyState() };
    keyClick('all');
    R.saved = savedPrefs();
    renderLayer();
    R.all = { geom: geom(), key: keyState() };
    /* An answer chip: hover focuses its level, a click keeps it. */
    keyEvent('mouseover', 'below');
    renderLayer();
    R.hoverBelow = geom();
    keyEvent('mouseout', 'below');
    keyClick('below');
    renderLayer();
    R.stickyBelow = { geom: geom(), key: keyState() };
    keyClick('below');
    renderLayer();
    R.released = { geom: geom(), key: keyState() };
    keyEvent('mouseover', 'swing');
    renderLayer();
    R.focusSwing = geom();
    keyEvent('mouseout', 'swing');
};

/* A phone's width: the entry's title, the key and the chips re-plan. */
SCENES.phone = async function (R) {
    R.desk = { others: otherLines(), key: keyState() };
    els[ID + '-container'].clientWidth = 400;
    await refresh(M.payload);
    renderLayer();
    R.phone = { others: otherLines(), key: keyState(), geom: geom() };
};

(async function () {
    vm.runInContext(M.pure, sandbox, { filename: 'pure.js' });
    vm.runInContext(M.main, sandbox, { filename: 'widget.js' });
    for (let i = 0; i < 6; i++) await flush();
    const R = { mode: M.mode };
    await SCENES[M.mode](R);
    process.stdout.write(JSON.stringify(R));
})().catch(function (e) { process.stderr.write(String((e && e.stack) || e)); process.exit(1); });
"""

LEVELS_HARNESS = WIDGET_PRELUDE + LEVELS_PATCH + LEVELS_SCENARIO


def _levels_payload(positions=None, bars=None):
    p = _payload()
    p["levels"] = copy.deepcopy(FIXTURE_ROWS)
    p["positioning"] = {
        "ok": True, "words": "w", "path": copy.deepcopy(PATH),
        "odds": {"verdict": "unjudged"},
        "po3": {"ok": True, "phase": "distribution", "direction": "up",
                "asia": {"high": 1.08608, "low": 1.08441, "date": "2026-10-06",
                         "opened": ASIA_OPENED, "closed": ASIA_CLOSED}}}
    if positions is not None:
        p["positions"] = positions
    if bars is not None:
        p["bars"] = bars
    return p


# Without a position: its SL (1.075) would hold the far swing 1.07676 on
# the chart by itself (§3.5 money-held), and Show all would prove nothing.
NO_MONEY = _levels_payload(positions=[])


def _run(mode, payload=None, prefs=None, coarse=False, no_prims=False, extra=None, **ctx):
    pure, main = _blocks(widget(**ctx))
    m = {"mode": mode, "pure": pure, "main": main,
         "payload": payload if payload is not None else _levels_payload(),
         "prefs": prefs, "prefKey": PREF_KEY, "coarse": coarse, "noPrims": no_prims,
         "barS1": "2026-08-10", "barS2": "2026-08-25", "barFar": "2026-09-08",
         "yEqh": y(1.092), "yHunt": y(1.08226), "yHuntLow": y(1.08211), "yEmpty": y(1.0935)}
    m.update(extra or {})
    return _node(LEVELS_HARNESS, m)


def _band(g, ident):
    got = [b for b in g["bands"] if b["id"] == ident]
    assert len(got) == 1, (ident, [b["id"] for b in g["bands"]])
    return got[0]


@unittest.skipUnless(NODE, "node is not installed")
class TheLevelLayerTests(SimpleTestCase):
    """The widget's real script, the fake chart, and LEVELS_PATCH."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.main = _run("main")

    # §6.3 D 1
    def test_levels_attach_one_layer_and_add_no_price_line(self):
        first = self.main["first"]
        self.assertEqual(first["prims"], [["candle", 1], ["hist", 0]])
        self.assertEqual(first["others"], ["LONG 1000", "SL", "TP"])
        self.assertEqual(first["items"], 10, "the 18 rows digested into 10 items")
        self.assertEqual(first["asia"], {"high": 1.08608, "low": 1.08441,
                                         "opened": ASIA_OPENED, "closed": ASIA_CLOSED})
        # The shapes 'normal', the chips 'top' (over every series), the
        # same array on every call, nothing hittable.
        self.assertEqual(first["zOrder"], ["normal", "top"])
        self.assertTrue(first["sameViews"])
        self.assertEqual(first["hasHitTest"], "undefined")
        self.assertEqual(first["hasAutoscale"], "undefined")
        # The layer painted: four gold bands, their chips over them.
        g = self.main["render"]["geom"]
        self.assertEqual(len(g["bands"]), 4)
        self.assertIn("EQL ×2 · ① HUNT  1.08226", self.main["render"]["texts"])
        self.assertIn("EQH ×2 ◎ · ② DRAW  1.08954", self.main["render"]["texts"])
        self.assertEqual(sorted(c["role"] for c in g["chips"] if c["role"]), ["draw", "hunt"])
        self.assertGreaterEqual(self.main["render"]["calls"].get("fillRect", 0), 4, "the bands were painted")
        # ...and every chip kept out of the title-box lane (titled lines exist).
        for c in g["chips"]:
            self.assertLessEqual(c["x1"], 740 - 80 + 1e-9, c)

    def test_the_money_lines_are_the_loudest(self):
        """Entry 3 px in its side's colour; SL and TP 2 px SOLID; the
        last price dotted; the volume prints no last value."""
        lines = {l["title"]: l for l in self.main["first"]["lines"]}
        self.assertEqual((lines["LONG 1000"]["width"], lines["LONG 1000"]["style"],
                          lines["LONG 1000"]["color"]), (3, 0, "#00e868"))
        self.assertEqual((lines["SL"]["width"], lines["SL"]["style"], lines["SL"]["axis"]),
                         (2, 0, True))
        self.assertEqual((lines["TP"]["width"], lines["TP"]["style"], lines["TP"]["axis"]),
                         (2, 0, True))
        created = self.main["first"]["created"]
        self.assertEqual(created["priceLineStyle"], 1, "the last price is dotted")
        self.assertEqual(created["priceFormat"],
                         {"type": "price", "precision": 5, "minMove": 0.00001})
        volume = self.main["first"]["volume"]
        self.assertEqual((volume["lastValueVisible"], volume["priceLineVisible"]),
                         (False, False))
        # A forex tape's volume is all 0: no histogram at all (its zero-height
        # columns painted a red and green dashed hairline across the pane).
        self.assertEqual(self.main["first"]["volRows"], 0)
        self.assertEqual(self.main["first"]["volOpts"][-1], {"visible": False})

    def test_the_pinned_signal_is_an_ink_idea_with_ghost_labels(self):
        """The pinned Entry is ink, never gold (gold is the pools'), and
        its three axis labels are ghosts: the chart's ground, the tone as
        text — an idea, where the position's filled labels are money."""
        raw = {l["title"]: l for l in self.main["pinned"]["lines"]
               if l["title"] in ("Entry", "Stop", "Target")}
        self.assertEqual(sorted(raw), ["Entry", "Stop", "Target"])
        self.assertEqual((raw["Entry"]["color"], raw["Entry"]["labelColor"],
                          raw["Entry"]["labelText"]), ("#daf0e6", "#030806", "#daf0e6"))
        self.assertEqual((raw["Stop"]["labelColor"], raw["Stop"]["labelText"]),
                         ("#030806", "#e83030"))
        self.assertEqual((raw["Target"]["labelColor"], raw["Target"]["labelText"]),
                         ("#030806", "#00e868"))
        self.assertTrue(all(l["style"] == 2 and l["width"] == 1 for l in raw.values()),
                        "dashed, 1 px: an idea")
        # The position's own labels stay filled: no ghost on the money.
        money = [l for l in self.main["pinned"]["lines"] if l["title"] in ("LONG 1000", "SL", "TP")]
        self.assertEqual(len(money), 3)
        self.assertTrue(all(l["labelColor"] is None for l in money))

    # §6.3 D 2
    def test_a_type_switch_reattaches_on_the_new_series(self):
        sw = self.main["swapped"]
        ops = sw["ops"]
        detach = [o for o in ops if o["op"] == "detach" and o["kind"] == "candle"]
        removed = [o for o in ops if o["op"] == "removeSeries" and o["kind"] == "candle"]
        attached = [o for o in ops if o["op"] == "attach" and o["kind"] == "line"]
        self.assertEqual((len(detach), len(removed), len(attached)), (1, 1, 1))
        self.assertLess(detach[0]["order"], removed[0]["order"], "detached BEFORE removeSeries")
        self.assertLess(removed[0]["order"], attached[0]["order"])
        self.assertEqual(sw["kind"], "line")
        self.assertEqual(sw["prims"], [["hist", 0], ["line", 1]])
        self.assertEqual(sw["others"], ["LONG 1000", "SL", "TP"])
        self.assertEqual(sw["items"], 10)
        self.assertEqual((sw["created"]["priceLineStyle"], sw["created"]["priceFormat"]["precision"]),
                         (1, 5))

    # §6.3 D 8
    def test_the_palette_is_read_once_per_data_paint(self):
        """LWC repaints the pane on every hover move: twenty paints read
        no style at all. A theme change (the body's class) is followed on
        the next paint."""
        self.assertEqual(self.main["gcsPerTwentyPaints"], 0)
        light = self.main["light"]
        self.assertEqual(light["theme"], "light")
        self.assertEqual(light["gcs"], 1, "read once, then cached again")
        self.assertEqual(light["observed"], {"attributes": True, "attributeFilter": ["class"]})
        self.assertEqual(self.main["render"]["geom"]["theme"], "dark")

    # §6.3 D 9
    def test_a_pin_dims_levels_but_not_the_hunt_and_draw(self):
        g = self.main["pinned"]["geom"]
        self.assertIn("is-pinned", self.main["pinned"]["cls"])
        self.assertEqual(_band(g, HUNT_ID)["k"], 1)
        self.assertEqual(_band(g, DRAW_ID)["k"], 1)
        self.assertAlmostEqual(_band(g, EQH_ID)["k"], 0.55 * fade(4.08), places=9)
        # Unpinned again: the fade alone.
        self.assertAlmostEqual(_band(self.main["unpinned"]["geom"], EQH_ID)["k"], fade(4.08),
                               places=9)
        self.assertEqual(self.main["unpinned"]["sigLines"], [])
        # The chips are never pin-dimmed.
        for c in g["chips"]:
            self.assertEqual(c["k"], 1, c)

    # §6.3 D 10
    def test_peek_while_pinned(self):
        peek = self.main["peek"]
        self.assertIn("is-pinned", peek["cls"], "the card stays the signal's")
        self.assertFalse(peek["hidden"])
        self.assertIn(EQH_ID, [c["id"] for c in peek["geom"]["chips"]])
        band = _band(peek["geom"], EQH_ID)
        self.assertTrue(band["hot"])
        self.assertEqual(band["k"], 1, "the level under the pointer glows, pinned or not")
        self.assertEqual(self.main["peekRequested"], 1, "one repaint for the new hover")
        self.assertEqual(self.main["peekSameIdRequests"], 1, "none for the same id")
        self.assertEqual(self.main["peekLeft"], [], "a miss clears the glow, pinned or not")


@unittest.skipUnless(NODE, "node is not installed")
class TheSwitchesTests(SimpleTestCase):

    # §6.3 D 5
    def test_levels_off_leaves_exactly_the_position_lines(self):
        out = _run("off", prefs={"indicators": {"positions": True, "levels": False}})
        off = out["off"]
        self.assertEqual(off["others"], ["LONG 1000", "SL", "TP"])
        self.assertEqual(off["items"], [])
        self.assertIsNone(off["asia"])
        self.assertEqual((off["geom"]["bands"], off["geom"]["chips"], off["geom"]["asia"]),
                         ([], [], None))
        key = off["key"]
        self.assertFalse(key["hidden"], "the key stays, so the layer can come back")
        self.assertIn("is-off", key["cls"])
        self.assertEqual(key["keys"]["levels"]["pressed"], "false")
        self.assertTrue(key["keys"]["below"]["hidden"])
        # The key's LEVELS chip is the toolbar's switch.
        on = out["on"]
        self.assertTrue(on["saved"]["levels"])
        self.assertEqual(on["items"], 10)
        self.assertEqual(on["bands"], 4)
        self.assertNotIn("is-off", on["key"]["cls"])
        self.assertEqual(on["key"]["keys"]["levels"]["pressed"], "true")

    # §6.3 D 6
    def test_the_key_toggles_persist(self):
        first = _run("toggles", payload=NO_MONEY, timeframe="1h")
        self.assertIs(first["saved"]["indicators"]["lvl_pool"], False)
        self.assertEqual(first["after"]["key"]["keys"]["pool"]["pressed"], "false")
        self.assertEqual(sorted(b["id"] for b in first["after"]["geom"]["bands"]),
                         [HUNT_ID, DRAW_ID], "a kind switch never hides a role")
        # A second visit, with those prefs.
        second = _run("toggles2", payload=NO_MONEY, prefs=first["saved"], timeframe="1h")
        self.assertEqual(sorted(b["id"] for b in second["booted"]["geom"]["bands"]),
                         [HUNT_ID, DRAW_ID])
        self.assertEqual(second["booted"]["key"]["keys"]["pool"]["pressed"], "false")
        self.assertNotIn(FAR_TICK_ID, [t["id"] for t in second["booted"]["geom"]["ticks"]])
        self.assertIs(second["saved"]["indicators"]["lvl_all"], True)
        self.assertIs(second["saved"]["indicators"]["lvl_pool"], False)
        self.assertIn(FAR_TICK_ID, [t["id"] for t in second["all"]["geom"]["ticks"]],
                      "Show all lifts the reach")
        self.assertEqual(second["all"]["key"]["keys"]["all"]["pressed"], "true")

    def test_the_key_says_the_answer_and_the_count(self):
        first = _run("toggles", payload=NO_MONEY, timeframe="1h")
        key, g = first["before"]["key"], first["before"]["geom"]
        self.assertFalse(key["hidden"])
        self.assertEqual(key["keys"]["below"]["text"], "▼ ① HUNT 1.08226 EQL×2 · 2.05 ATR")
        self.assertEqual(key["keys"]["above"]["text"], "▲ ② DRAW 1.08954 EQH×2 · 2.53 ATR")
        self.assertEqual(key["keys"]["below"]["title"],
                         "the longs' stops · the pool-sweep odds are not yet judged")
        self.assertEqual(key["keys"]["below"]["id"], HUNT_ID)
        self.assertEqual(key["count"], "%d of %d shown · nearest first"
                         % (g["count"]["shown"], g["count"]["total"]))
        self.assertEqual(g["count"]["total"], 10)
        self.assertEqual(key["counts"], {k: str(g["count"][k]) for k in ("pool", "swing", "round")})

    def test_an_answer_chip_focuses_its_level_until_the_next_click(self):
        out = _run("toggles2", payload=NO_MONEY, prefs={"indicators": {"positions": True}},
                   timeframe="1h")
        hover = out["hoverBelow"]
        self.assertEqual(_band(hover, HUNT_ID)["k"], 1)
        self.assertAlmostEqual(_band(hover, DRAW_ID)["k"], 0.2)
        self.assertIsNotNone(hover["hatch"], "the hunt zone shows with its focus")
        sticky = out["stickyBelow"]
        self.assertEqual(sticky["key"]["keys"]["below"]["pressed"], "true")
        self.assertAlmostEqual(_band(sticky["geom"], DRAW_ID)["k"], 0.2)
        released = out["released"]
        self.assertEqual(released["key"]["keys"]["below"]["pressed"], "false")
        self.assertEqual(_band(released["geom"], DRAW_ID)["k"], 1)
        # A kind's chip focuses the kind: the swings at full, the pools at a fifth.
        swing = out["focusSwing"]
        self.assertAlmostEqual(_band(swing, HUNT_ID)["k"], 0.2)
        self.assertTrue(swing["rays"])
        for r in swing["rays"]:
            self.assertGreater(r["k"], 0.2)


@unittest.skipUnless(NODE, "node is not installed")
class TheFallbacksAndTheMoneyTests(SimpleTestCase):

    # §6.3 D 3
    def test_without_primitives_asia_falls_back_to_two_lines(self):
        hourly = _run("noPrims", no_prims=True, timeframe="1h")
        self.assertEqual(hourly["prims"], [0, 0])
        self.assertEqual(hourly["others"], ["LONG 1000", "SL", "TP", "", ""])
        asia = hourly["lines"][3:]
        self.assertEqual([(l["price"], l["style"], l["title"], l["axis"], l["width"])
                          for l in asia],
                         [(1.08608, 3, "", False, 1), (1.08441, 3, "", False, 1)])
        self.assertEqual(asia[0]["color"], "rgba(168,120,240,0.55)", "the session's violet")
        daily = _run("noPrims", no_prims=True, timeframe="1d")
        self.assertEqual(daily["others"], ["LONG 1000", "SL", "TP"])

    # §6.3 D 4
    def test_soft_stop_draws_a_quiet_line_only_when_it_differs(self):
        pos = _payload()["positions"][0]
        apart = _run("lines", payload=_levels_payload(positions=[dict(pos, soft_stop=1.079)]))
        self.assertEqual(apart["others"], ["LONG 1000", "SL", "TP", ""])
        soft = apart["lines"][3]
        self.assertEqual((soft["price"], soft["style"], soft["axis"], soft["width"]),
                         (1.079, 4, False, 1))
        self.assertEqual(soft["color"], "rgba(232,48,48,0.7)")
        same = _run("lines", payload=_levels_payload(positions=[dict(pos, soft_stop=1.075)]))
        self.assertEqual(same["others"], ["LONG 1000", "SL", "TP"])

    # §6.3 D 7
    def test_a_tap_on_a_level_opens_its_card_and_the_next_tap_closes_it(self):
        out = _run("tap", payload=_levels_payload(positions=[]), coarse=True)
        opened = out["opened"]
        self.assertFalse(opened["hidden"])
        self.assertEqual(opened["cls"], "sv-sig-card sv-sig-card--level sv-sig-card--pool")
        self.assertIn("equal lows", opened["html"])
        self.assertIn("The hunt runs here first", opened["html"])
        self.assertIn("<dt>Band</dt><dd>1.08211 – 1.08241</dd>", opened["html"])
        self.assertIn("<dt>Hunt zone</dt><dd>1.08132–1.08281</dd>", opened["html"])
        self.assertEqual(out["glow"], [HUNT_ID], "the tapped level glows")
        self.assertTrue(out["closed"]["hidden"], "the second tap closes it")
        self.assertEqual(out["closedGlow"], [], "and lets the glow go: a finger sends no move")
        self.assertFalse(out["reopened"]["hidden"], "and a third opens it again")
        self.assertTrue(out["elsewhere"]["hidden"], "a tap on nothing closes it")

    def test_a_finger_reaches_12_px_and_leaves_no_glow_behind(self):
        """hitTol(): 12 px on a coarse pointer, 6 for a mouse. A tap 5 px
        under the HUNT band's bottom edge opens it; the mouse there finds
        nothing (2 px under, it does). A dot pinned after a level card, or
        a refresh, leaves no level glowing past the pin's dim."""
        out = _run("tap", payload=_levels_payload(positions=[]), coarse=True)
        for c in out["underGeom"]["chips"]:          # the point is on the band's reach, no chip
            self.assertFalse(c["x0"] <= 700 <= c["x1"] and c["y0"] <= y(1.08211) + 5 <= c["y1"], c)
        self.assertFalse(out["under"]["hidden"])
        self.assertEqual(out["under"]["cls"], "sv-sig-card sv-sig-card--level sv-sig-card--pool")
        self.assertIn("equal lows", out["under"]["html"])
        self.assertEqual(out["underGlow"], [HUNT_ID])
        self.assertIn("is-pinned", out["pin"]["cls"])
        self.assertEqual(out["pin"]["glow"], [], "the pinned dot clears the tapped level's glow")
        self.assertFalse(out["beforeRefresh"]["card"]["hidden"])
        self.assertEqual(out["beforeRefresh"]["glow"], [HUNT_ID])
        self.assertTrue(out["afterRefresh"]["card"]["hidden"], "the refresh hides the card")
        self.assertEqual(out["afterRefresh"]["glow"], [], "...and its glow")
        mouse = _run("hoverTol", payload=_levels_payload(positions=[]))
        self.assertTrue(mouse["five"]["hidden"], "a mouse 5 px under the band: nothing")
        self.assertFalse(mouse["two"]["hidden"])
        self.assertEqual(mouse["two"]["cls"], "sv-sig-card sv-sig-card--level sv-sig-card--pool")

    def test_a_tap_on_a_chip_beside_a_money_line_opens_the_level(self):
        """A finger's 12 px reach from the SL or TP covered every chip
        beside them: the position lines were tested first, so a tap on the
        HUNT chip next to the stop opened the position's card."""
        pos = _payload()["positions"][0]
        far = dict(pos, entry=1.07, stop=1.065, tp=1.075)            # off the pane, titled
        first = _run("chipTap", payload=_levels_payload(positions=[far]), timeframe="1h", coarse=True)
        hunt = [c for c in first["geom"]["chips"] if c["role"] == "hunt"][0]
        # The entry 5 px under the HUNT chip: off its row, inside a finger's reach of its middle.
        entry_y = hunt["y1"] + 5
        entry = round(1.0855 - (entry_y - 200) / 20000, 6)
        at = [(hunt["x0"] + hunt["x1"]) / 2, (hunt["y0"] + hunt["y1"]) / 2]
        near = _run("chipTap", payload=_levels_payload(positions=[dict(far, entry=entry)]),
                    timeframe="1h", coarse=True, extra={"tapAt": at})
        moved = [c for c in near["geom"]["chips"] if c["role"] == "hunt"][0]
        self.assertEqual((moved["x0"], moved["y0"], moved["text"]), (hunt["x0"], hunt["y0"], hunt["text"]))
        self.assertLessEqual(abs(y(entry) - at[1]), 12, "the entry line is inside the finger's reach")
        self.assertEqual(near["card"]["cls"], "sv-sig-card sv-sig-card--level sv-sig-card--pool")
        self.assertIn("equal lows", near["card"]["html"])
        self.assertEqual(near["glow"], [HUNT_ID])

    def test_the_position_card_says_where_the_money_meets_the_levels(self):
        """§4.6 through the widget's own hover path: the pointer on the SL."""
        pos = dict(_payload()["positions"][0], entry=1.08395, stop=1.08185, tp=1.0894)
        out = _run("posHover", payload=_levels_payload(positions=[pos]), timeframe="1h",
                   extra={"at": [300, y(1.08185)]})
        for c in out["geom"]["chips"]:
            self.assertFalse(c["x0"] <= 300 <= c["x1"] and c["y0"] <= y(1.08185) <= c["y1"], c)
        card = out["card"]
        self.assertFalse(card["hidden"])
        self.assertEqual(card["cls"], "sv-sig-card sv-sig-card--bull")
        self.assertIn('<span class="sv-sig-chip sv-sig-chip--loss">'
                      'Stop inside the hunt zone 1.08132–1.08281</span>', card["html"])
        self.assertIn("TP at the draw: the equal highs pool 1.08954", card["html"])

    def test_a_stop_or_soft_stop_in_the_hunt_zone_hatches_it(self):
        """moneyRows' `stop` flag: the position's SL in the zone hatches it
        (the 'position' acceptance shot), and so does its soft stop; the
        soft stop's row is a chip keep-out like any money row."""
        pos = dict(_payload()["positions"][0], entry=1.08395, stop=1.08185, tp=1.0894)
        g = _run("keep", payload=_levels_payload(positions=[pos]), timeframe="1h")["geom"]
        self.assertIsNotNone(g["hatch"])
        self.assertEqual(g["hatch"]["id"], HUNT_ID)
        self.assertAlmostEqual(g["hatch"]["y0"], y(1.08281), delta=0.1)
        self.assertAlmostEqual(g["hatch"]["y1"], y(1.08132), delta=0.1)
        soft = dict(pos, stop=1.0750, soft_stop=1.0820)
        g2 = _run("keep", payload=_levels_payload(positions=[soft]), timeframe="1h")["geom"]
        self.assertIsNotNone(g2["hatch"], "the soft stop alone sits in the zone")
        for c in g2["chips"]:
            if not c["cross"]:
                self.assertFalse(c["y0"] - 2 <= y(1.082) <= c["y1"] + 2, c)
        # Both outside the zone: no hatch.
        g3 = _run("keep", payload=_levels_payload(positions=[dict(pos, stop=1.0750)]), timeframe="1h")["geom"]
        self.assertIsNone(g3["hatch"])

    def test_a_second_tap_inside_the_double_tap_window_closes_the_card(self):
        """The AFTER shots: the probe tapped again 250 ms after the first
        tap, inside lightweight-charts 4.1's double-tap window (500 ms,
        under 30 px). The library sent a double tap and no click, and the
        card stayed open. On a touch pointer the double tap IS that tap."""
        out = _run("doubleTap", payload=_levels_payload(positions=[]), coarse=True)
        self.assertEqual(out["subscribed"], 1)
        self.assertFalse(out["opened"]["hidden"])
        self.assertIn("equal lows", out["opened"]["html"])
        self.assertTrue(out["closed"]["hidden"], "the double tap closes it")
        # On a dot it pins the signal, as a tap does.
        self.assertIn("is-pinned", out["dot"]["card"]["cls"])
        self.assertEqual(len(out["dot"]["sigLines"]), 3)

    def test_a_mouse_double_click_is_left_to_the_library(self):
        out = _run("mouseDouble", payload=_levels_payload(positions=[]))
        self.assertEqual(out["subscribed"], 1)
        self.assertIn("is-pinned", out["pinned"]["card"]["cls"])
        self.assertEqual(out["after"], out["pinned"], "no unpin, no card")

    def test_chips_keep_clear_of_the_page_boxes_and_the_newest_candles(self):
        """The crosshair's OHLC legend covered the EQH 1.09200 chip while
        the mouse rested on the chart, and four chips hid the newest 4h
        candles. The layer hands the layout both: the legend and the
        bar-close countdown worked out from their CSS and text, and the
        last svLevels.LV.NOW_BARS candles."""
        mouse = _run("keep", payload=NO_MONEY, timeframe="1h")
        g = mouse["geom"]
        overlays = g["keep"]["overlays"]
        self.assertEqual(len(overlays), 2, "the crosshair legend and the bar-close countdown")
        legend, countdown = overlays
        self.assertEqual((legend["x0"], legend["y0"], legend["y1"]), (0, 0, 34))
        self.assertGreater(legend["x1"], 300, "a date and four prices at five decimals")
        self.assertEqual((countdown["y0"], countdown["y1"]), (0, 34))
        self.assertLessEqual(countdown["x1"], 740)
        self.assertLess(countdown["x0"], 740 - 80, "wider than the lane's top corner")
        bars, candles = mouse["bars"], g["keep"]["candles"]
        self.assertEqual(len(candles), 30)
        i = len(bars) - 30                       # the fake's logical x is 20 + 10 i, 10 px a bar
        self.assertAlmostEqual(candles[0]["x0"], 20 + i * 10 - 5)
        self.assertAlmostEqual(candles[0]["y0"], y(bars[i]["high"]) - 1)
        self.assertAlmostEqual(candles[0]["y1"], y(bars[i]["low"]) + 1)
        self.assertEqual(sorted(c["role"] for c in g["chips"] if c["role"]), ["draw", "hunt"])
        for c in g["chips"]:
            for b in overlays:
                self.assertFalse(_meets(c, b), (c["text"], b))
            if not c["role"]:
                for b in candles:
                    self.assertFalse(_meets(c, b), (c["text"], b))
        # A finger raises no legend; a daily frame has no countdown.
        touch = _run("keep", payload=NO_MONEY, timeframe="1h", coarse=True)
        self.assertEqual(touch["geom"]["keep"]["overlays"], [countdown])
        daily = _run("keep", payload=NO_MONEY)["geom"]["keep"]["overlays"]
        self.assertEqual(len(daily), 1)
        self.assertEqual((daily[0]["x0"], daily[0]["y1"]), (0, 34))

    def test_the_asia_label_keeps_off_the_title_boxes_not_the_whole_lane(self):
        """The harness, 2026-10-07: with a position up, today's Asian box
        sits inside the closed title-box lane, and the ASIA label slid
        left of the lane onto other days' candles. The layer now hands
        the layout every price line's row and title width; the label sits
        on its box clear of the title boxes, or not at all."""
        bars = []
        for i in range(72):          # x 20 .. 730; the last, 2026-10-07, holds the session
            c = 1.08 + 0.001 * (i % 7)
            bars.append({"time": (date(2026, 7, 28) + timedelta(days=i)).isoformat(),
                         "open": c - 0.0005, "high": c + 0.002, "low": c - 0.002,
                         "close": c, "volume": 0})
        base = _payload()["positions"][0]
        # The TP's title box over the box's top (1.0866 is y 178; the box's top 188.4).
        pos = dict(base, tp=1.0866)
        g = _run("keep", payload=_levels_payload(positions=[pos], bars=bars), timeframe="1h")["geom"]
        titles = sorted(g["keep"]["titles"], key=lambda t: t["y0"])
        h = 10 * 17 / 12
        rows = [(y(1.0866), "TP"), (y(1.08), "LONG 1000"), (y(1.075), "SL")]
        self.assertEqual(len(titles), 3)
        for t, (row, title) in zip(titles, rows):
            self.assertAlmostEqual(t["x0"], 740 - (len(title) * 6.1 + 16) - 1, places=6)
            self.assertEqual(t["x1"], 740)
            self.assertAlmostEqual((t["y0"] + t["y1"]) / 2, row, places=6, msg=title)
            self.assertAlmostEqual(t["y1"] - t["y0"], h + 2, places=6)
        a = g["asia"]
        self.assertEqual((a["x0"], a["x1"]), (725, 735), "today's box on the newest bar, in the lane")
        label = a["label"]
        self.assertEqual(max(0, a["x0"] - label["x1"], label["x0"] - a["x1"]), 0, "on its box")
        self.assertGreaterEqual(label["y0"], a["yl"], "under it: the TP's title box is over it")
        self.assertGreater(label["x1"], 740 - 80)
        for t in titles:
            self.assertFalse(_meets(label, t), t)
        # The entry's title box under the box as well: no label at all.
        low = dict(pos, entry=1.084)
        g2 = _run("keep", payload=_levels_payload(positions=[low], bars=bars), timeframe="1h")["geom"]
        self.assertGreater(g2["asia"]["x0"], 740 - 80)
        self.assertNotIn("label", g2["asia"])
        # Without a position the lane is open: the label sits over the box.
        g3 = _run("keep", payload=_levels_payload(positions=[], bars=bars), timeframe="1h")["geom"]
        self.assertEqual(g3["keep"]["titles"], [])
        self.assertLessEqual(g3["asia"]["label"]["y1"], g3["asia"]["yh"])

    # §6.3 D 11
    def test_the_axis_takes_the_bars_decimals_without_a_page_count(self):
        bars = copy.deepcopy(_payload()["bars"])
        for i, b in enumerate(bars):
            c = round(1.08552 + 0.00011 * (i % 7), 5)
            b.update(open=round(c - 0.0005, 5), high=round(c + 0.002, 5),
                     low=round(c - 0.002, 5), close=c)
        out = _run("axis", payload=_levels_payload(bars=bars), decimals=None)
        fmt = [o["priceFormat"] for o in out["opts"] if "priceFormat" in o]
        self.assertTrue(fmt)
        self.assertEqual((fmt[-1]["precision"], fmt[-1]["minMove"]), (5, 0.00001))
        self.assertEqual(out["created"]["priceFormat"]["precision"], 2,
                         "no bars yet at creation: the library's 2")
        two = copy.deepcopy(_payload()["bars"])
        for i, b in enumerate(two):
            c = 1.08 + 0.01 * (i % 3)
            b.update(open=round(c, 2), high=round(c + 0.01, 2), low=round(c - 0.01, 2),
                     close=round(c, 2))
        page = _run("axis", payload=_levels_payload(bars=two), decimals=5)
        fmt = [o["priceFormat"] for o in page["opts"] if "priceFormat" in o]
        self.assertEqual((fmt[-1]["precision"], fmt[-1]["minMove"]), (5, 0.00001),
                         "the page's count wins")

    def test_a_phone_width_replans_the_entry_title_and_the_key(self):
        out = _run("phone")
        self.assertEqual(out["desk"]["others"], ["LONG 1000", "SL", "TP"])
        self.assertNotIn("is-phone", out["desk"]["key"]["cls"])
        phone = out["phone"]
        self.assertEqual(phone["others"], ["LONG", "SL", "TP"], "the size stays in the card")
        self.assertIn("is-phone", phone["key"]["cls"])
        self.assertEqual(phone["key"]["keys"]["below"]["text"], "▼ ① HUNT 1.08226 · 2.05 ATR")
        self.assertLessEqual(len(phone["geom"]["chips"]), 4)
        self.assertEqual(sorted(c["role"] for c in phone["geom"]["chips"] if c["role"]),
                         ["draw", "hunt"])


def _heikin(bars):
    """The widget's heikinAshi: the candles as a Heikin-Ashi chart draws them."""
    out, prev = [], None
    for b in bars:
        close = (b["open"] + b["high"] + b["low"] + b["close"]) / 4
        op = (prev["open"] + prev["close"]) / 2 if prev else (b["open"] + b["close"]) / 2
        ha = {"open": op, "close": close, "high": max(b["high"], op, close),
              "low": min(b["low"], op, close)}
        out.append(ha)
        prev = ha
    return out


@unittest.skipUnless(NODE, "node is not installed")
class ThePaintTests(SimpleTestCase):
    """What the layer actually paints, op by op (the recorder keeps each
    op's fill, stroke, width, dash and font), and where it measures from."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.toggles = _run("toggles", payload=NO_MONEY, timeframe="1h")

    def test_each_kind_paints_in_its_own_hue_and_weight(self):
        """The operator's complaint was 'too similar': gold areas for the
        pools, the role's stop-side edge at 2 px, blue dashed rays, blue
        2 px ticks, the Asian box named ASIA."""
        before = self.toggles["before"]
        g, ops = before["geom"], before["ops"]
        gold, blue = "#d8b020", "#30a0e8"
        fills = [o for o in ops if o["op"] == "fillRect" and o["fill"] == gold]
        self.assertEqual(len(fills), 4, "one fill per band")
        self.assertEqual(sorted(tuple(o["args"][:2]) for o in fills),
                         sorted((_js_round(b["x0"]), _js_round(b["y0"])) for b in g["bands"]))
        heavy = [o for o in ops if o["op"] == "lineTo" and o["stroke"] == gold and o["lw"] == 2]
        hunt, draw = _band(g, HUNT_ID), _band(g, DRAW_ID)
        self.assertEqual(sorted(o["args"][1] for o in heavy),
                         sorted([_js_round(hunt["y1"]), _js_round(draw["y0"])]),
                         "2 px on the stop side of the HUNT (under its lows) and the DRAW (over its highs)")
        for other in ("sv-lvl-pool-1.08001000000", EQH_ID):
            b = _band(g, other)
            self.assertNotIn(_js_round(b["y0"]), [o["args"][1] for o in heavy])
            self.assertNotIn(_js_round(b["y1"]), [o["args"][1] for o in heavy])
        rays = [o for o in ops if o["op"] == "lineTo" and o["stroke"] == blue and o["dash"] == [4, 3]]
        self.assertEqual(len(rays), len(g["rays"]))
        # 1 px on the half pixel (crisp)
        self.assertEqual(sorted(o["args"][1] for o in rays), sorted(_js_round(r["y"]) + 0.5 for r in g["rays"]))
        self.assertEqual({o["lw"] for o in rays}, {1})
        ticks = [o for o in ops if o["op"] == "lineTo" and o["stroke"] == blue and o["lw"] == 2]
        self.assertTrue(g["ticks"])
        self.assertEqual(sorted(o["args"][1] for o in ticks), sorted(_js_round(t["y"]) for t in g["ticks"]))
        self.assertEqual({tuple(o["dash"]) for o in ticks}, {()}, "a tick is solid")
        self.assertTrue(g["asia"]["label"])
        self.assertIn("ASIA", before["texts"])
        self.assertTrue([o for o in ops if o["op"] == "fillRect" and o["fill"] == "#a878f0"],
                        "the Asian box in the session's violet")

    def test_the_chips_fit_their_boxes_at_any_display_scaling(self):
        """The text took Math.round(10 × ratio) px (13 at 125 %, 18 at
        175 %) in a box measured at 10 × ratio: it ran out of the box. The
        1 px border, at DPR 2 a 2 px stroke on the half pixel, blurred."""
        out = _run("dpr", payload=NO_MONEY, timeframe="1h")["out"]
        for k, font in (("1", "600 10px monospace"), ("1.25", "600 12.5px monospace"),
                        ("2", "600 20px monospace")):
            texts = [o for o in out[k]["ops"] if o["op"] == "fillText"]
            self.assertTrue(texts, k)
            self.assertEqual({o["font"] for o in texts}, {font}, k)
        two = out["2"]
        chip = [c for c in two["geom"]["chips"] if c["role"] == "hunt"][0]
        x0, y0 = _js_round(chip["x0"] * 2), _js_round(chip["y0"] * 2)
        x1, y1 = _js_round(chip["x1"] * 2), _js_round(chip["y1"] * 2)
        border = [o for o in two["ops"] if o["op"] == "strokeRect" and o["args"][:2] == [x0 + 1, y0 + 1]]
        self.assertEqual(len(border), 1, "a 2 px border inside the box, on whole pixels")
        self.assertEqual((border[0]["lw"], border[0]["args"][2:]), (2, [x1 - x0 - 2, y1 - y0 - 2]))
        a = two["geom"]["asia"]
        box = [o for o in two["ops"] if o["op"] == "strokeRect" and o["stroke"] == "#a878f0"]
        self.assertEqual(box[0]["args"][:2], [_js_round(a["x0"] * 2) + 1, _js_round(a["yh"] * 2) + 1])
        one = [o for o in out["1"]["ops"] if o["op"] == "strokeRect" and o["stroke"] == "#a878f0"]
        self.assertEqual(one[0]["args"][:2], [_js_round(a["x0"]) + 0.5, _js_round(a["yh"]) + 0.5])

    def test_heikin_ashi_keeps_out_the_candles_as_drawn(self):
        out = _run("heikin", payload=NO_MONEY, timeframe="1h")
        g, bars = out["geom"], out["bars"]
        ha = _heikin(bars)
        n = len(bars)
        boxes = g["keep"]["candles"]
        self.assertEqual(len(boxes), 30)
        differ = 0
        for j, box in enumerate(boxes):
            i = n - 30 + j
            self.assertAlmostEqual(box["y0"], y(ha[i]["high"]) - 1, places=6)
            self.assertAlmostEqual(box["y1"], y(ha[i]["low"]) + 1, places=6)
            if abs(ha[i]["high"] - bars[i]["high"]) > 1e-12 or abs(ha[i]["low"] - bars[i]["low"]) > 1e-12:
                differ += 1
        self.assertGreater(differ, 0, "the fixture has Heikin-Ashi candles beyond their raw range")
        self.assertAlmostEqual(g["keep"]["lastY"], y(ha[-1]["close"]), places=6,
                               msg="the last-price row is the close drawn")
        self.assertNotAlmostEqual(g["keep"]["lastY"], y(bars[-1]["close"]), places=3)

    def test_levels_go_by_time_whatever_the_logical_index(self):
        """Another series' point before bars[0] (a measure line kept over a
        background refresh) shifts every logical index by one: the levels
        were drawn a bar left of the candles that printed them."""
        plain = _run("keep", payload=NO_MONEY, timeframe="1h")["geom"]
        shifted = _run("keep", payload=NO_MONEY, timeframe="1h", extra={"shiftLogical": True})["geom"]
        self.assertEqual(shifted, plain)
        n = len(NO_MONEY["bars"])
        self.assertAlmostEqual(shifted["keep"]["candles"][0]["x0"], 20 + (n - 30) * 10 - 5)
        self.assertAlmostEqual(shifted["asia"]["x0"], 20 + (n - 1) * 10 - 5)

    def test_a_sticky_focus_ends_with_its_answer(self):
        """The ▲ answer clicked (the DRAW 1.08954 focused), then a refresh
        names the draw at EQH 1.09200: the focus is let go — kept, it
        dimmed everything, the new DRAW included, with no chip pressed."""
        moved = copy.deepcopy(NO_MONEY)
        moved["positioning"]["path"][1]["price"] = 1.092
        out = _run("focusRefresh", payload=NO_MONEY, timeframe="1h", extra={"payload2": moved})
        sticky = out["sticky"]
        self.assertEqual(sticky["key"]["keys"]["above"]["pressed"], "true")
        self.assertAlmostEqual(_band(sticky["geom"], HUNT_ID)["k"], 0.2)
        after = out["after"]
        self.assertEqual(after["key"]["keys"]["above"]["id"], EQH_ID)
        self.assertEqual(after["key"]["keys"]["above"]["pressed"], "false")
        self.assertEqual(after["key"]["keys"]["below"]["pressed"], "false")
        self.assertEqual(_band(after["geom"], EQH_ID)["k"], 1, "the new DRAW at full strength")
        self.assertEqual(_band(after["geom"], HUNT_ID)["k"], 1)
        self.assertAlmostEqual(_band(after["geom"], DRAW_ID)["k"], fade(2.53))

    def test_the_volume_histogram_only_with_a_volume(self):
        flat = _run("volume", payload=NO_MONEY, timeframe="1h")
        self.assertEqual(flat["rows"], 0)
        self.assertEqual(flat["opts"][-1], {"visible": False})
        self.assertEqual(flat["optsAfter"][-1], {"visible": False}, "the toolbar cannot raise an empty one")
        traded = copy.deepcopy(NO_MONEY)
        for i, b in enumerate(traded["bars"]):
            b["volume"] = 1000 + i
        full = _run("volume", payload=traded, timeframe="1h")
        self.assertEqual(full["rows"], len(traded["bars"]))
        self.assertEqual(full["opts"][-1], {"visible": True})
        self.assertEqual(full["optsAfter"][-1], {"visible": True})
