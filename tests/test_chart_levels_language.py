"""The chart levels' visual language (2026-10-07).

The operator: "could we improve the visibility and design of liquidity
areas and pivot points etc. They are too similar and messy at the moment."

Each kind of level gets its own hue and its own shape: a liquidity pool is
a gold AREA from its first touch, a swing (the operator's "pivot points")
a blue tick on the candle that printed it with one ray per side, the Asian
range a violet box over its own session, a round number a neutral dotted
guide. The money (entry, SL, TP) stays the loudest thing on the chart, and
the hunt and the draw are always named.

This module drives the PURE half (window.svLevels in the widget's
template-tag-free block) under node, exactly as the page ships it:
  digest()      the server's rows -> items: a pool's own swings folded in
                by the server's membership, the pullback's extreme folded
                into its swing or band, the map's hunt and draw by band
                containment, reach and caps as flags, one ray per side, a
                round number inside a band is that pool's (◎);
  layout()      items -> pixels: what is drawn (caps, reach, money-held,
                kind toggles, daily frames), alphas (fade, pin, focus), the
                hunt hatch, the Asia box and its label, edge counts and the
                chips with their keep-outs (the title-box lane, money rows,
                marker boxes, the page's boxes over the canvas, the newest
                candles, the roles' bands, other chips); the ASIA label on
                its box or nowhere, clear of the title boxes themselves;
  hit(), keyAnswer(), moneyFacts(), markerBoxes(), titleBoxes() (the
  price lines' title boxes stacked as the axis stacks them), and the
  level and position cards' new facts.

The fixture is the EURUSD scene the screenshots were shot on (18 rows,
mark 1.08552, 4h ATR 0.0015894669), with the keys the server now adds
(members, top, bottom, touches, origin, label, zone).

Run with:  python manage.py test tests.test_chart_levels_language
"""
import math
import re
import unittest
from datetime import datetime, timezone as dt_timezone
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from tests.test_chart_signal_markers import (
    HEX, NODE, _blocks, _node, _strip_vars, widget, widget_source)

# ── The fixture ────────────────────────────────────────────────────────
NOW = int(datetime(2026, 10, 7, 14, 35, tzinfo=dt_timezone.utc).timestamp())
ATR = 0.0015894669
MARK = 1.08552
HUNT_DEPTH_ATR, NEAR_ATR = 0.5, 0.25          # bot_program.smart_money


def _bar4h(days_ago):
    """The 4h bar's open stamp `days_ago` days before NOW (epoch s)."""
    t = NOW - int(days_ago * 86400)
    return t - t % 14400


def _zone(side, lo, hi):
    """stop_beyond_the_crowd's zone around a level (smart_money §5.1)."""
    if side == "below":
        return [round(lo - HUNT_DEPTH_ATR * ATR, 10), round(hi + NEAR_ATR * ATR, 10)]
    return [round(lo - NEAR_ATR * ATR, 10), round(hi + HUNT_DEPTH_ATR * ATR, 10)]


def _row(price, kind, side, atr_away, **extra):
    row = {"price": price, "kind": kind, "side": side, "atr_away": atr_away,
           "pool": "touches" in kind, "text": "%.5f" % price}
    row.update(extra)
    return row


def _swing(price, side, atr_away, days_ago, label):
    return _row(price, "swing low" if side == "below" else "swing high", side,
                atr_away, origin=_bar4h(days_ago), label=label,
                zone=_zone(side, price, price))


def _pool(price, side, atr_away, members):
    """members: [(price, days_ago)], oldest first, as the server sends them."""
    ms = [{"price": p, "origin": _bar4h(d)} for p, d in members]
    lo, hi = min(p for p, _ in members), max(p for p, _ in members)
    kind = ("equal lows" if side == "below" else "equal highs") + " (%d touches)" % len(ms)
    return _row(price, kind, side, atr_away, touches=len(ms), members=ms,
                top=hi, bottom=lo, origin=ms[0]["origin"], zone=_zone(side, lo, hi))


def _round(price, side, atr_away):
    return _row(price, "round number", side, atr_away, zone=_zone(side, price, price))


def _recent(price, side, atr_away, days_ago):
    return _row(price, "recent low" if side == "below" else "recent high", side,
                atr_away, origin=_bar4h(days_ago), zone=_zone(side, price, price))


FIXTURE_ROWS = [
    _swing(1.07676, "below", 5.51, 9.5, "LL"),
    _swing(1.07986, "below", 3.56, 8.0, "LL"),
    _round(1.08000, "below", 3.47),
    _pool(1.08001, "below", 3.47, [(1.07986, 8.0), (1.08016, 7.0)]),
    _swing(1.08016, "below", 3.37, 7.0, "HL"),
    _swing(1.08211, "below", 2.15, 6.0, "HL"),
    _pool(1.08226, "below", 2.05, [(1.08211, 6.0), (1.08241, 4.0)]),
    _swing(1.08241, "below", 1.96, 4.0, "HL"),
    _recent(1.08288, "below", 1.66, 0.5),
    _round(1.08500, "below", 0.33),
    _recent(1.08775, "above", 1.40, 0.7),
    _swing(1.08934, "above", 2.40, 5.0, "LH"),
    _pool(1.08954, "above", 2.53, [(1.08934, 5.0), (1.08974, 3.0)]),
    _swing(1.08974, "above", 2.65, 3.0, "HH"),
    _round(1.09000, "above", 2.82),
    _swing(1.09184, "above", 3.98, 11.0, "LH"),     # before the loaded bars
    _pool(1.09200, "above", 4.08, [(1.09184, 11.0), (1.09216, 9.0)]),
    _swing(1.09216, "above", 4.18, 9.0, "HH"),
]
PATH = [{"leg": "hunt", "price": 1.08226, "why": "the longs' stops"},
        {"leg": "draw", "price": 1.08954, "why": "the bias is long at 0.70"}]
POSITION = {"side": "long", "entry": 1.08395, "stop": 1.08185, "tp": 1.0894,
            "qty": 25000}
PINNED = {"entry": 1.0852, "stop": 1.0836, "target": 1.0896}
ASIA = {"high": 1.08608, "low": 1.08441}

# The level and position cards as the widget printed them BEFORE
# 2026-10-07, for the rows tests/test_chart_hover_cards.py pins: a row
# without the new keys must still read byte for byte the same.
BEFORE_CARDS = {
    "level": '<div class="sv-sig-head"><span class="sv-sig-side">POOL</span><span class="sv-sig-rule">equal lows</span></div><dl class="sv-sig-facts"><div><dt>Price</dt><dd>1.09000</dd></div><div><dt>Distance</dt><dd>1.2 ATR under the mark</dd></div><div><dt>Touches</dt><dd>2</dd></div></dl><div class="sv-sig-status"><span class="sv-sig-chip">Where the stops pile up</span><span class="sv-sig-chip sv-sig-chip--live">The hunt runs here first — the longs&#39; stops</span></div><div class="sv-sig-foot">Recomputed every minute · gone once the price trades through it</div>',  # noqa: E501
    "draw": '<div class="sv-sig-head"><span class="sv-sig-side">LEVEL</span><span class="sv-sig-rule">swing high</span></div><dl class="sv-sig-facts"><div><dt>Price</dt><dd>1.10500</dd></div><div><dt>Distance</dt><dd>2.1 ATR over the mark</dd></div></dl><div class="sv-sig-status"><span class="sv-sig-chip">The last swing still held</span><span class="sv-sig-chip sv-sig-chip--live">The draw after the hunt — the bias is long at 0.60</span></div><div class="sv-sig-foot">Recomputed every minute · gone once the price trades through it</div>',  # noqa: E501
    "round": '<div class="sv-sig-head"><span class="sv-sig-side">LEVEL</span><span class="sv-sig-rule">round number</span></div><dl class="sv-sig-facts"><div><dt>Price</dt><dd>1.10000</dd></div><div><dt>Distance</dt><dd>0.4 ATR over the mark</dd></div></dl><div class="sv-sig-status"><span class="sv-sig-chip">A round number the crowd watches</span></div><div class="sv-sig-foot">Recomputed every minute · gone once the price trades through it</div>',  # noqa: E501
    "pos": '<div class="sv-sig-head"><span class="sv-sig-side">LONG</span><span class="sv-sig-rule">golden &lt;b&gt;cross&lt;/b&gt;</span></div><div class="sv-sig-levels"><span class="sv-sig-level sv-sig-level--entry"><span>Entry</span><b>1.08000</b></span><span class="sv-sig-level sv-sig-level--stop"><span>Stop</span><b>1.07500</b></span><span class="sv-sig-level sv-sig-level--target"><span>Target</span><b>1.09000</b></span></div><dl class="sv-sig-facts"><div><dt>Now</dt><dd>+0.37R · +1.20%</dd></div><div><dt>Open for</dt><dd>30 h</dd></div><div><dt>Leverage</dt><dd>5x</dd></div><div><dt>Soft stop</dt><dd>1.07800</dd></div></dl><div class="sv-sig-status"><span class="sv-sig-chip sv-sig-chip--live">REAL MONEY</span><span class="sv-sig-chip">Stop at the broker</span><span class="sv-sig-chip sv-sig-chip--win">Thesis adjust</span></div><div class="sv-sig-foot">Thesis ALIVE — adjust: the lows were swept.</div>',  # noqa: E501
    "paperPos": '<div class="sv-sig-head"><span class="sv-sig-side">SHORT</span><span class="sv-sig-rule">x</span></div><div class="sv-sig-levels"><span class="sv-sig-level sv-sig-level--entry"><span>Entry</span><b>100</b></span><span class="sv-sig-level sv-sig-level--stop"><span>Stop</span><b>101</b></span><span class="sv-sig-level sv-sig-level--target"><span>Target</span><b>97</b></span></div><dl class="sv-sig-facts"><div><dt>Now</dt><dd>—</dd></div><div><dt>Open for</dt><dd>2 min</dd></div></dl><div class="sv-sig-status"><span class="sv-sig-chip">Simulated</span></div>',  # noqa: E501
}

# Signal dots and the position arrow over the fixture's bars (epoch, the
# bar's high and low, as markerBoxes takes them once in pixels).
MARKERS = [
    {"t": _bar4h(6.0) + 3600, "high": 1.08330, "low": 1.08214, "position": "belowBar",
     "size": 1.25, "text": "▲"},
    {"t": _bar4h(6.0) + 3600, "high": 1.08330, "low": 1.08214, "position": "belowBar",
     "size": 0.9, "text": "▲"},
    {"t": _bar4h(5.0) + 7200, "high": 1.08936, "low": 1.08850, "position": "aboveBar",
     "size": 1.7, "text": "▼"},
    {"t": _bar4h(3.0), "high": 1.08976, "low": 1.08880, "position": "aboveBar",
     "size": 0.6, "text": "▼"},
    {"t": _bar4h(0.5), "high": 1.08350, "low": 1.08290, "position": "belowBar",
     "size": 1.25, "text": "▲"},
    {"t": _bar4h(0.83), "high": 1.08470, "low": 1.08380, "position": "belowBar",
     "size": 1, "text": "LONG @ 1.08395"},       # the position's arrow
]

PURE_RUN = r"""
const fs = require('fs');
const M = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
var L = window.svLevels, HC = window.svHoverCards, LV = L.LV;
var out = {};
var T0 = M.now - 240 * 3600;                          /* 240 1h bars loaded */
function toYs(scale, shift) { return function (p) { return 200 + (shift || 0) - (p - 1.0855) * scale; }; }
var toY = toYs(20000, 0);                             /* 1 pip = 2 px */
function toXw(W) { return function (t) { return t < T0 ? -1 : (t - T0) / 3600 * (W - 68) / 240; }; }
function fmt(v) { return Number(v).toFixed(5); }
function measure(t) { return String(t).length * LV.CHAR_W; }
function env(o) {
    o = o || {};
    var W = o.width || 740, ty = o.toY || toY;
    var e = { toY: ty, toX: toXw(W), width: W, height: 384, theme: 'dark', phone: false,
              highTf: false, showAll: false, hidden: {}, hover: null, focus: null, pinned: false,
              mark: M.mark, money: [], labels: false, laneW: 80, hlines: [], lastY: ty(M.mark),
              boxes: [], asia: null, measure: measure };
    for (var k in o) e[k] = o[k];
    return e;
}
function clone(x) { return JSON.parse(JSON.stringify(x)); }
function digest(rows, path) {
    return L.digest(rows || M.rows, { path: path === undefined ? M.path : path }, fmt);
}
function brief(items) {
    return items.map(function (l) {
        return { id: l.id, lv: l.lv, price: l.price, top: l.top === undefined ? null : l.top,
                 bottom: l.bottom === undefined ? null : l.bottom, far: !!l.far,
                 capped: !!l.capped, ray: !!l.ray, role: l.role || null, quiet: !!l.quiet,
                 round: l.round == null ? null : l.round, recent: !!l.recent,
                 touches: l.touches == null ? null : l.touches,
                 origin: l.origin == null ? null : l.origin, zoneText: l.zoneText || null,
                 why: l.why || null, chip: L.chipText(l, false), phone: L.chipText(l, true) };
    });
}
function geo(g) { return clone(g); }
function money(ty, pos, pin) {
    var m = [];
    if (pos) {
        m.push({ price: pos.entry, y: ty(pos.entry), held: false });
        m.push({ price: pos.stop, y: ty(pos.stop), held: true, stop: true });
        m.push({ price: pos.tp, y: ty(pos.tp), held: true });
    }
    if (pin) ['entry', 'stop', 'target'].forEach(function (k) {
        m.push({ price: pin[k], y: ty(pin[k]), held: false });
    });
    return m;
}
function markerPoints(ty, W) {
    var tx = toXw(W);
    return M.markers.map(function (m) {
        return { x: tx(m.t), yHigh: ty(m.high), yLow: ty(m.low), position: m.position,
                 size: m.size, text: m.text };
    });
}
var items = digest();
var byId = {};
items.forEach(function (l) { byId[l.id] = l; });
var HUNT = items.filter(function (l) { return l.role === 'hunt'; })[0];
var DRAW = items.filter(function (l) { return l.role === 'draw'; })[0];

/* 1, 7, 9: the fixture digested; 19: its chips */
out.items = brief(items);
out.fix = geo(L.layout(items, env()));
out.fixPhone = geo(L.layout(items, env({ phone: true, width: 330 })));

/* 2. two pools side by side, members interleaved */
function pool(price, side, atr, members, extra) {
    var r = { price: price, kind: (side === 'below' ? 'equal lows' : 'equal highs') + ' (' + members.length + ' touches)',
              side: side, pool: true, atr_away: atr, text: fmt(price),
              members: members.map(function (p, i) { return { price: p, origin: M.now - (10 - i) * 86400 }; }) };
    for (var k in (extra || {})) r[k] = extra[k];
    return r;
}
function swing(price, side, atr, extra) {
    var r = { price: price, kind: side === 'below' ? 'swing low' : 'swing high', side: side,
              pool: false, atr_away: atr, text: fmt(price) };
    for (var k in (extra || {})) r[k] = extra[k];
    return r;
}
out.twoPools = brief(L.digest([
    pool(1.08025, 'below', 1.0, [1.08000, 1.08050]),
    pool(1.08095, 'below', 0.8, [1.08040, 1.08150]),
    swing(1.08000, 'below', 1.1), swing(1.08040, 'below', 0.9), swing(1.08050, 'below', 0.85),
    swing(1.08150, 'below', 0.6), swing(1.07900, 'below', 1.5)
], null, fmt));

/* 3. an uneven three-touch pool */
out.three = brief(L.digest([
    pool((1.08000 + 1.08104 + 1.08107) / 3, 'below', 1.0, [1.08000, 1.08104, 1.08107]),
    swing(1.08000, 'below', 1.1), swing(1.08104, 'below', 0.95), swing(1.08107, 'below', 0.94)
], null, fmt));

/* 4 and 13. a row cached before the change: no members, no band */
var oldRows = [
    { price: 1.08226, kind: 'equal lows (2 touches)', side: 'below', pool: true, atr_away: 2.05, text: '1.08226' },
    swing(1.08211, 'below', 2.15), swing(1.08241, 'below', 1.96)
];
var oldItems = L.digest(oldRows, null, fmt);
out.old = brief(oldItems);
out.oldGeo = geo(L.layout(oldItems, env()));

/* 5. the pullback's extreme on a swing's price, in a band, and alone */
out.recent = brief(L.digest([
    swing(1.08300, 'below', 1.58, { label: 'HL' }),
    { price: 1.08300, kind: 'recent low', side: 'below', pool: false, atr_away: 1.58, text: '1.08300' },
    pool(1.08226, 'below', 2.05, [1.08211, 1.08241], { top: 1.08241, bottom: 1.08211 }),
    { price: 1.08230, kind: 'recent low', side: 'below', pool: false, atr_away: 2.03, text: '1.08230' },
    { price: 1.08775, kind: 'recent high', side: 'above', pool: false, atr_away: 1.40, text: '1.08775' }
], null, fmt));

/* 6. reach and caps are flags */
out.showAll = geo(L.layout(items, env({ showAll: true })));
var four = [swing(1.08390, 'below', 1.0, { origin: M.now - 86400 }),
            swing(1.08310, 'below', 1.5, { origin: M.now - 2 * 86400 }),
            swing(1.08230, 'below', 2.0, { origin: M.now - 3 * 86400 }),
            swing(1.08150, 'below', 2.5, { origin: M.now - 4 * 86400 })];
var fourItems = L.digest(four, null, fmt);
out.four = brief(fourItems);
out.fourGeo = geo(L.layout(fourItems, env()));

/* 8. the hunt and the draw by band containment */
out.containment = brief(digest(null, [{ leg: 'hunt', price: 1.08230, why: 'x' },
                                      { leg: 'draw', price: 1.08954, why: 'y' }]));

/* 10. money holds levels past the caps and the reach */
var extra = [swing(1.08480, 'below', 0.45, { origin: M.now - 86400, label: 'HL', zone: [1.08401, 1.08520] }),
             swing(1.08420, 'below', 0.83, { origin: M.now - 2 * 86400, label: 'HL', zone: [1.08341, 1.08460] }),
             swing(1.08360, 'below', 1.20, { origin: M.now - 3 * 86400, label: 'HL', zone: [1.08281, 1.08400] }),
             swing(1.08300, 'below', 1.58, { origin: M.now - 4 * 86400, label: 'HL', zone: [1.08221, 1.08340] })];
var heldItems = digest(M.rows.concat(extra));
out.held = {
    items: brief(heldItems),
    bare: geo(L.layout(heldItems, env())),
    pos: geo(L.layout(heldItems, env({ money: money(toY, M.pos, null) }))),
    pin: geo(L.layout(heldItems, env({ money: money(toY, null, { entry: 1.0852, stop: 1.08240, target: 1.0896 }),
                                       pinned: true })))
};

/* 11. within 8 px of a money row (rule c): rows without a zone */
var noZone = extra.map(function (r) { var c = clone(r); delete c.zone; return c; });
var czItems = digest(M.rows.concat(noZone));
function sigAt(price) { return [{ price: price, y: toY(price), held: false }]; }
out.near8 = {
    six: geo(L.layout(czItems, env({ money: sigAt(1.08270) }))),      /* 6 px under 1.08300 */
    twelve: geo(L.layout(czItems, env({ money: sigAt(1.08240) })))    /* 12 px under it */
};

/* 12. kind toggles hide kinds, never a role */
out.noPools = geo(L.layout(items, env({ hidden: { pool: true } })));
out.noSwings = geo(L.layout(items, env({ hidden: { swing: true, round: true } })));

/* 14. daily frames: pools, roles and the two rays only */
out.daily = geo(L.layout(items, env({ highTf: true, hover: HUNT.id,
                                      asia: { high: M.asia.high, low: M.asia.low, x0: 500, x1: 560 } })));

/* 15. the role chips survive money right next to them */
var crowd = [
    { price: 1.08191, y: toY(1.08191), held: true, stop: true },   /* SL 4 px under the HUNT band */
    { price: 1.08950, y: toY(1.08950), held: true },               /* TP inside the DRAW band */
    { price: 1.08395, y: toY(1.08395), held: false },              /* the entry */
    { price: 1.08260, y: toY(1.08260), held: false },              /* the pinned stop over HUNT */
    { price: 1.09010, y: toY(1.09010), held: false },              /* the pinned target over DRAW */
    { price: 1.08520, y: toY(1.08520), held: false }               /* the pinned entry */
];
var crowdBoxes = [{ x0: 255, x1: 300, y0: 236, y1: 300 },         /* dots on HUNT's first touch */
                  { x0: 320, x1: 360, y0: 80, y1: 140 }];          /* and on DRAW's */
out.crowd = { W: 740, laneW: 96, boxes: crowdBoxes, rows: crowd.map(function (m) { return m.y; }),
              g: geo(L.layout(items, env({ money: crowd, labels: true, laneW: 96, pinned: true,
                                           hlines: [toY(1.08900)], boxes: crowdBoxes }))) };
/* the same crowd on a phone */
var crowdPhoneBoxes = [{ x0: 100, x1: 130, y0: 236, y1: 300 }];
out.crowdPhone = { W: 330, laneW: 96, boxes: crowdPhoneBoxes, rows: crowd.map(function (m) { return m.y; }),
                   g: geo(L.layout(items, env({ money: crowd, labels: true, laneW: 96, pinned: true,
                                                phone: true, width: 330, hlines: [toY(1.08900)],
                                                boxes: crowdPhoneBoxes }))) };

/* 16. money rows and markers are never covered: many zooms and shifts */
out.sweep = [];
[20000, 12000, 30000].forEach(function (scale) {
    [0, -40, 40].forEach(function (shift) {
        [false, true].forEach(function (phone) {
            var W = phone ? 330 : 740, ty = toYs(scale, shift);
            var m = money(ty, M.pos, M.pinned), hl = [ty(1.08700)];
            var boxes = L.markerBoxes(markerPoints(ty, W), phone ? 6 : 10, 10);
            var lastY = ty(M.mark);
            var g = L.layout(items, env({ toY: ty, width: W, phone: phone, money: m, labels: true,
                                         laneW: 96, hlines: hl, lastY: lastY, boxes: boxes, pinned: true,
                                         asia: { high: M.asia.high, low: M.asia.low, x0: W * 0.6, x1: W * 0.68 } }));
            out.sweep.push({ scale: scale, shift: shift, phone: phone, W: W, laneW: 96, labels: true,
                             rows: m.map(function (r) { return r.y; }).concat(hl, [lastY]),
                             boxes: boxes, g: geo(g) });
        });
    });
});

/* 17. the title-box lane */
var topPool = pool(1.09480, 'above', 5.8, [1.09470, 1.09490], { top: 1.09490, bottom: 1.09470 });
topPool.members = [{ price: 1.09470, origin: M.now - 20 * 3600 }, { price: 1.09490, origin: M.now - 6 * 3600 }];
var laneItems = digest(M.rows.concat([topPool]));
out.laneOpen = geo(L.layout(laneItems, env({ showAll: true, labels: false })));
out.laneShut = geo(L.layout(laneItems, env({ showAll: true, labels: true, laneW: 120 })));

/* 18. chip caps count the roles and never refuse them */
function nearPool(price, side, atr) {
    return pool(price, side, atr, [price - 0.00008, price + 0.00008],
                { top: price + 0.00008, bottom: price - 0.00008 });
}
var many = M.rows.concat([nearPool(1.08480, 'below', 0.45), nearPool(1.08420, 'below', 0.83),
                          nearPool(1.08360, 'below', 1.2), nearPool(1.08620, 'above', 0.44),
                          nearPool(1.08680, 'above', 0.8), nearPool(1.08740, 'above', 1.18)]);
var manyItems = digest(many);
out.many = { items: brief(manyItems),
             desk: geo(L.layout(manyItems, env({ showAll: true }))),
             phone: geo(L.layout(manyItems, env({ showAll: true, phone: true, width: 330 }))) };

/* 19. the stubs: a pane too narrow for the full words */
out.narrow = geo(L.layout(items, env({ width: 140, lastY: null })));

/* 20. no obstacle: the chip sits at the origin, outside the band */
out.free = geo(L.layout(items, env({ lastY: null })));

/* 21. off-pane levels are counted on their edge */
out.offPane = geo(L.layout(items, env({ toY: toYs(20000, -130) })));
out.offPanePhone = geo(L.layout(items, env({ toY: toYs(20000, -130), phone: true, width: 330 })));

/* 22. alphas */
out.fade = { near: L.fade(1.0, 'dark'), floorDark: L.fade(4.5, 'dark'), floorLight: L.fade(4.5, 'light'),
             mid: L.fade(3.0, 'dark'), far: L.fade(9, 'dark'), none: L.fade(undefined, 'dark'),
             at408dark: L.fade(4.08, 'dark'), at408light: L.fade(4.08, 'light') };
out.pinDark = geo(L.layout(items, env({ pinned: true })));
out.pinLight = geo(L.layout(items, env({ pinned: true, theme: 'light' })));
out.light = geo(L.layout(items, env({ theme: 'light' })));
out.focusSwing = geo(L.layout(items, env({ focus: 'swing' })));
out.focusHunt = geo(L.layout(items, env({ focus: 'id:' + HUNT.id })));
out.hover = geo(L.layout(items, env({ hover: byId['sv-lvl-pool-1.09200000000'].id, pinned: true })));

/* 23. the hunt zone's hatch */
out.hatch = {
    none: geo(L.layout(items, env())).hatch,
    stop: geo(L.layout(items, env({ money: money(toY, M.pos, null) }))).hatch,
    sigStop: geo(L.layout(items, env({ money: money(toY, null, { entry: 1.0852, stop: 1.0820, target: 1.0896 }) }))).hatch,
    hover: geo(L.layout(items, env({ hover: HUNT.id }))).hatch,
    focus: geo(L.layout(items, env({ focus: 'id:' + HUNT.id }))).hatch,
    zone: [toY(HUNT.zone[1]), toY(HUNT.zone[0])], huntX0: geo(L.layout(items, env())).bands[0].x0
};

/* 24. marker boxes */
out.boxes = {
    one: L.markerBoxes([{ x: 100, yHigh: 200, yLow: 220, position: 'aboveBar', size: 1.25, text: '▲' }], 10, 10),
    two: L.markerBoxes([{ x: 100, yHigh: 200, yLow: 220, position: 'aboveBar', size: 1.25, text: '▲' },
                        { x: 100, yHigh: 200, yLow: 220, position: 'aboveBar', size: 1, text: '' }], 10, 10),
    below: L.markerBoxes([{ x: 100, yHigh: 200, yLow: 220, position: 'belowBar', size: 1.25, text: '▲' }], 10, 10),
    skip: L.markerBoxes([{ x: 100, yHigh: 200, yLow: 220, position: 'inBar', size: 1 }, null,
                         { x: null, yHigh: 1, yLow: 2, position: 'aboveBar' }], 10, 10)
};

/* 25. hits on the shapes as drawn */
var gh = L.layout(items, env({ showAll: true, asia: { high: M.asia.high, low: M.asia.low, x0: 500, x1: 560 } }));
function onChip(x, y) { return gh.chips.some(function (c) { return x >= c.x0 && x <= c.x1 && y >= c.y0 && y <= c.y1; }); }
function freeX(y, from, to) { for (var x = to; x >= from; x -= 2) if (!onChip(x, y)) return x; return null; }
var drawBand = gh.bands.filter(function (b) { return b.id === DRAW.id; })[0];
var bandMid = (drawBand.y0 + drawBand.y1) / 2, bx = freeX(bandMid, drawBand.x0 + 10, 730);
var farTick = gh.ticks.filter(function (t) { return t.id === 'sv-lvl-swing-1.07676000000'; })[0];
var lowRay = gh.rays.filter(function (r) { return r.id === 'sv-lvl-recent-1.08288000000'; })[0];
var huntChip = gh.chips.filter(function (c) { return c.role === 'hunt'; })[0];
/* the ray where no chip lies: above it, else under it (its chip keeps off
   the HUNT band under it, so it may sit on the ray's upper side) */
var ry = lowRay.y - 3, rx = freeX(ry, lowRay.x0 + 2, 730);
if (rx === null) { ry = lowRay.y + 3; rx = freeX(ry, lowRay.x0 + 2, 730); }
out.hit = {
    band: L.hit(gh, items, bx, bandMid, 6),
    leftOfTouch: L.hit(gh, items, drawBand.x0 - 20, bandMid, 6),
    tick: L.hit(gh, items, farTick.x + 10, farTick.y + 4, 6),
    tickFar6: L.hit(gh, items, farTick.x + 10, farTick.y + 9, 6),
    tickFar12: L.hit(gh, items, farTick.x + 10, farTick.y + 9, 12),
    ray: L.hit(gh, items, rx, ry, 6),
    asiaHigh: L.hit(gh, items, 620, gh.asia.yh + 2, 6),
    asiaLow: L.hit(gh, items, 620, gh.asia.yl - 2, 6),
    asiaIn: L.hit(gh, items, 530, gh.asia.yh + 3, 6),
    chip: L.hit(gh, items, (huntChip.x0 + huntChip.x1) / 2, (huntChip.y0 + huntChip.y1) / 2, 6),
    round: L.hit(gh, items, 300, toY(1.08500) + 2, 6),
    roundMiss: L.hit(gh, items, 300, toY(1.08500) + 4, 6),
    nothing: L.hit(gh, items, 10, 10, 6),
    noGeom: L.hit(null, items, 10, 10, 6)
};
['band', 'leftOfTouch', 'tick', 'tickFar6', 'tickFar12', 'ray', 'chip', 'round', 'roundMiss'].forEach(function (k) {
    if (out.hit[k]) out.hit[k] = { id: out.hit[k].id, item: !!out.hit[k].item };
});

/* 26. the key's live answers */
var noPath = digest(null, null);
out.key = {
    below: L.keyAnswer(items, 'below', false), above: L.keyAnswer(items, 'above', false),
    belowNoPath: L.keyAnswer(noPath, 'below', false), aboveNoPath: L.keyAnswer(noPath, 'above', false),
    phone: L.keyAnswer(items, 'below', true),
    swingOnly: L.keyAnswer(digest([M.rows[10]], null), 'above', false),
    empty: L.keyAnswer([], 'below', false)
};

/* 27. where the money meets the levels, on the position card */
var facts = L.moneyFacts(M.pos, items, fmt);
out.money = {
    facts: facts,
    other: L.moneyFacts({ side: 'long', entry: 1.084, stop: 1.08000, tp: 1.09200 }, items, fmt),
    none: L.moneyFacts({ side: 'long', entry: 1.084, stop: 1.0850, tp: 1.0860 }, items, fmt),
    empty: L.moneyFacts(M.pos, [], fmt),
    card: HC.positionCard(M.pos, facts),
    plain: HC.positionCard(M.pos),
    blank: HC.positionCard(M.pos, [])
};

/* 28. the level card's new facts, and today's rows unchanged */
var swingLL = digest(M.rows.concat([]), null).filter(function (l) { return l.id === 'sv-lvl-swing-1.07676000000'; })[0];
out.cards = {
    hunt: HC.levelCard(HUNT, { path: M.path }, M.now),
    huntNoNow: HC.levelCard(HUNT, { path: M.path }),
    draw: HC.levelCard(DRAW, { path: M.path }, M.now),
    swing: HC.levelCard(swingLL, null, M.now),
    recent: HC.levelCard(byId['sv-lvl-recent-1.08288000000'], null, M.now),
    oldPool: HC.levelCard(oldItems[0], null, M.now),
    today: {
        level: HC.levelCard(
            { price: 1.09, text: '1.09000', kind: 'equal lows (2 touches)', side: 'below', pool: true, atr_away: 1.2 },
            { path: [{ leg: 'hunt', price: 1.09, why: "the longs' stops" },
                     { leg: 'draw', price: 1.105, why: 'the bias is long at 0.60' }] }),
        draw: HC.levelCard(
            { price: 1.105, text: '1.10500', kind: 'swing high', side: 'above', pool: false, atr_away: 2.1 },
            { path: [{ leg: 'hunt', price: 1.09 }, { leg: 'draw', price: 1.105, why: 'the bias is long at 0.60' }] }),
        round: HC.levelCard({ price: 1.1, text: '1.10000', kind: 'round number', side: 'above', pool: false, atr_away: 0.4 }, null),
        pos: HC.positionCard({ side: 'long', rule: 'golden <b>cross</b>', entry: 1.08,
            entry_text: '1.08000', stop: 1.075, stop_text: '1.07500', tp: 1.09,
            tp_text: '1.09000', r_now: 0.37, pnl_pct: 1.2, age_s: 3600 * 30,
            leverage: '5', soft_stop: 1.078, soft_stop_text: '1.07800', paper: false,
            protected: true, thesis: { verdict: 'adjust', words: 'Thesis ALIVE — adjust: the lows were swept.' } }),
        paperPos: HC.positionCard({ side: 'short', via: 'x', entry: 100, stop: 101,
            tp: 97, paper: true, r_now: null, age_s: 120, thesis: { verdict: 'watch' } })
    }
};
out.cards.todayWithNow = HC.levelCard(
    { price: 1.09, text: '1.09000', kind: 'equal lows (2 touches)', side: 'below', pool: true, atr_away: 1.2 },
    { path: [{ leg: 'hunt', price: 1.09, why: "the longs' stops" },
             { leg: 'draw', price: 1.105, why: 'the bias is long at 0.60' }] }, M.now);

/* 29. malformed rows are skipped, never thrown on */
var bad = [null, undefined, 7, 'x', {}, { price: NaN, kind: 'swing low', side: 'below', atr_away: 1 },
           { price: '1.08', kind: 'swing low', side: 'below', atr_away: 1 },
           { price: Infinity, kind: 'swing high', side: 'above', atr_away: 1 },
           { price: 1.081, kind: 'fair value gap', side: 'below', atr_away: 1 },
           { price: 1.082, kind: 'swing low', side: 'below' },
           { price: 1.083, kind: 'equal lows (2 touches)', side: 'below', pool: true, atr_away: 1,
             members: [null, { price: 'x' }, { price: 1.0829, origin: 'yesterday' }], zone: ['a', 1] }];
var badItems = L.digest(bad, { path: [null, { leg: 'hunt' }, { leg: 'hunt', price: 'x' }] }, fmt);
var badGeo = L.layout(badItems, env());
out.bad = { items: brief(badItems), geo: geo(badGeo),
            key: L.keyAnswer(badItems, 'below', false),
            keySwing: L.keyAnswer(badItems.filter(function (l) { return l.lv === 'swing'; }), 'below', false),
            nothing: brief(L.digest(null, null)), nothingGeo: geo(L.layout([], env())),
            noMap: brief(L.digest(M.rows.slice(0, 3))) };

/* ── The acceptance fixes (2026-10-07) ────────────────────────────── */

/* 30. the newest candles: no chip of a non-role hides them. A block of 30
   bars at the right, from 1.08260 to 1.08780: both rays start inside it. */
var newest = [];
for (var nb = 0; nb < 30; nb++) {
    var cxb = 470 + nb * 9;
    newest.push({ x0: cxb - 4.5, x1: cxb + 4.5, y0: toY(1.0878) - 1, y1: toY(1.0826) + 1 });
}
out.candles = { boxes: newest, g: geo(L.layout(items, env({ candles: newest }))) };
/* ...and a pane that is all candles: the roles are still named, nothing else */
out.candleWall = geo(L.layout(items, env({ candles: [{ x0: 0, x1: 740, y0: 0, y1: 384 }] })));

/* 31. an edge count slides clear of a dot (top and bottom), then a row in */
function edgeOf(g, side) { return g.edges.filter(function (e) { return e.side === side; })[0] || null; }
out.edgeDots = [['above', toYs(20000, -130)], ['below', toYs(20000, 130)]].map(function (sc) {
    var home = edgeOf(L.layout(items, env({ toY: sc[1] })), sc[0]);
    var dot = { x0: home.x0 + 10, x1: home.x0 + 30, y0: home.y0 - 6, y1: home.y1 + 6 };
    var row = { x0: 0, x1: 740, y0: home.y0 - 2, y1: home.y1 + 2 };      /* the whole row taken */
    return { side: sc[0], home: geo(home), dot: dot, row: row,
             slid: edgeOf(L.layout(items, env({ toY: sc[1], boxes: [dot] })), sc[0]),
             inward: edgeOf(L.layout(items, env({ toY: sc[1], overlays: [row] })), sc[0]) };
});

/* 32. the ASIA label names a one-bar box; under it at the pane's top; with
   the whole lane closed (no title rows given) and today's box inside it,
   no label rather than one slid off the box */
var A = function (x0, x1) { return { high: M.asia.high, low: M.asia.low, x0: x0, x1: x1 }; };
out.asiaNarrow = geo(L.layout(items, env({ asia: A(500, 504) }))).asia;
out.asiaTop = geo(L.layout(items, env({ toY: toYs(20000, -180), asia: A(500, 504) }))).asia;
out.asiaLane = geo(L.layout(items, env({ labels: true, laneW: 80, asia: A(700, 716) }))).asia;
/* ...a box just left of the closed lane keeps its label beside it */
out.asiaByLane = geo(L.layout(items, env({ labels: true, laneW: 80, asia: A(640, 656) }))).asia;

/* 35. the title boxes, stacked as the axis stacks its labels (LWC 4.1.0
   _fixLabelOverlap): away from the last price's own label */
var TB = function (rows, center) { return L.titleBoxes(rows, center, 740, 384); };
out.titleBoxes = {
    lone: TB([{ y: 100, w: 40 }], 300),
    above: TB([{ y: 150, w: 40 }, { y: 147, w: 60 }], 300),
    below: TB([{ y: 250, w: 40 }, { y: 253, w: 60 }], 200),
    center: TB([{ y: 203, w: 40 }], 200),
    silent: TB([{ y: 104, w: 0 }, { y: 100, w: 40 }], 300),
    edge: TB([{ y: 3, w: 40 }], 300),
    noCenter: TB([{ y: 100, w: 40 }, { y: 102, w: 40 }], null),
    none: TB(null, 200)
};

/* 36. the ASIA label beside the title boxes. The harness's views of
   2026-10-07 (pane px, rows as the axis printed them, the last price's
   row, the newest candles a wall from the box's left): with a position
   or a pinned signal up, the label slid left of the closed lane onto
   other days' candles. Now: on its box clear of every title box, or no
   label. */
function wall(W, H, from) {
    var c = [];
    for (var wx = from; wx < W; wx += 4) c.push({ x0: wx, x1: wx + 4, y0: 0, y1: H });
    return c;
}
function asiaCase(c, legacy) {
    var e = env({ toY: function (p) { return p; }, width: c.W, height: c.H, phone: c.W < LV.PHONE_W,
                  money: c.rows.map(function (r) { return { price: r.y, y: r.y, held: false }; }),
                  labels: c.rows.length > 0, laneW: 80, lastY: c.last, mark: null,
                  candles: c.candles || [], boxes: c.boxes || [],
                  asia: { high: c.yh, low: c.yl, x0: c.x0, x1: c.x1 } });
    if (!legacy) e.titles = c.rows.map(function (r) { return { y: r.y, w: measure(r.t) + 16 }; });
    var g = L.layout([], e);
    return { asia: geo(g.asia), titles: g.keep.titles, W: c.W, laneX: c.W - 80,
             candles: c.candles || [] };
}
var R = function (y, t) { return { y: y, t: t }; };
var D1 = { W: 1014, H: 327, x0: 952, x1: 968, yh: 172, yl: 200, last: 181.44, candles: wall(1014, 327, 880),
           rows: [R(115, 'TP'), R(208.3, 'LONG 25000'), R(244.3, 'SL')] };
var D1F = clone(D1); D1F.rows = D1F.rows.concat([R(111.6, 'Target'), R(186.9, 'Entry'), R(214.3, 'Stop')]);
var D4F = { W: 1014, H: 327, x0: 998, x1: 1002, yh: 211, yl: 222, last: 214.99, candles: wall(1014, 327, 880),
            rows: [R(187.9, 'Target'), R(189.2, 'TP'), R(217.1, 'Entry'), R(225.4, 'LONG 25000'),
                   R(227.7, 'Stop'), R(239.4, 'SL')] };
var P1 = { W: 268, H: 240, x0: 252, x1: 257, yh: 127, yl: 147, last: 133.64, candles: wall(268, 240, 150),
           rows: [R(88.6, 'TP'), R(151.8, 'LONG'), R(176.2, 'SL')] };
var P4F = { W: 268, H: 240, x0: 264, x1: 266, yh: 154, yl: 161, last: 156.37, candles: wall(268, 240, 150),
            rows: [R(138, 'Target'), R(138.9, 'TP'), R(157.8, 'Entry'), R(163.4, 'LONG'), R(165, 'Stop'),
                   R(172.9, 'SL')] };
out.asiaViews = { d1hPosition: asiaCase(D1), d1hFull: asiaCase(D1F), d4hFull: asiaCase(D4F),
                  p1hPosition: asiaCase(P1), p4hFull: asiaCase(P4F),
                  d1hWholeLane: asiaCase(D1, true), p1hWholeLane: asiaCase(P1, true) };
/* ...on-box slots under wide title boxes above and below (their lines
   inside the box, clear of the slots): the nearest slot left of the box,
   clear of the candles; with candles there too, none */
var NEAR = { W: 740, H: 384, x0: 600, x1: 612, yh: 200, yl: 230, last: 350,
             rows: [R(205, 'LONG 25000 ·· 00000'), R(225, 'LONG 25000 ·· 00000')] };
var NEARC = clone(NEAR); NEARC.candles = [{ x0: 540, x1: 600, y0: 0, y1: 384 }];
out.asiaNear = { free: asiaCase(NEAR), candles: asiaCase(NEARC) };
/* ...and a sweep: boxes across the right of the pane, 4 to 40 px wide,
   title rows clear of it, at its edges, in a knot round it; the newest
   candles a wall over the right 40 %, or none */
out.asiaSweep = [];
[[], [R(172, 'TP')], [R(172, 'TP'), R(208, 'LONG 25000')], [R(150, 'SL')],
 [R(176, 'Target'), R(177, 'TP'), R(202, 'Entry'), R(204, 'Stop')]].forEach(function (rows) {
    [4, 16, 40].forEach(function (bw) {
        [true, false].forEach(function (walled) {
            [false, true].forEach(function (legacy) {
                for (var bx = 420; bx + bw <= 740; bx += 18) {
                    var c = asiaCase({ W: 740, H: 384, x0: bx, x1: bx + bw, yh: 180, yl: 200, last: 260,
                                       rows: rows, candles: walled ? wall(740, 384, 444) : [] }, legacy);
                    out.asiaSweep.push({ label: c.asia.label || null, x0: bx, x1: bx + bw, legacy: legacy,
                                         walled: walled, titles: c.titles, rows: rows.length,
                                         ys: rows.map(function (r) { return r.y; }).concat([260]) });
                }
            });
        });
    });
});
out.asiaSweepWall = wall(740, 384, 444);

/* 33. a role tries its stub at its origin before its full words at the
   left edge: a dot right of the origin leaves room for the stub only */
var huntBand = out.free.bands.filter(function (b) { return b.role === 'hunt'; })[0];
var block = { x0: huntBand.x0 + 8 + 60, x1: huntBand.x0 + 8 + 150, y0: huntBand.y0 - 40, y1: huntBand.y1 + 40 };
out.stubFirst = { x0: huntBand.x0, block: block,
                  g: geo(L.layout(items, env({ labels: true, laneW: 80, lastY: null, boxes: [block] }))) };

/* 34. the crosshair's legend: no chip under it */
var legendBox = { x0: 0, x1: 450, y0: 0, y1: 34 }, upTy = toYs(20000, -30);
out.overlay = { box: legendBox, bare: geo(L.layout(items, env({ toY: upTy }))),
                g: geo(L.layout(items, env({ toY: upTy, overlays: [legendBox] }))) };

/* ── The review fixes (2026-10-08) ─────────────────────────────────── */

/* 37. Hovering never moves a chip out from under the pointer. For every
   point a level is hit at, the layout with THAT level hovered hits the
   same level there (no A -> B -> A flicker), and a hovered chip that held
   a slot keeps it, as does every other chip. */
function rectsOf(g) { return g.chips.map(function (c) { return [c.id, c.text, c.x0, c.y0, c.x1, c.y1].join('|'); }); }
function stability(its, e, step, tol) {
    var cache = {}, g0 = L.layout(its, e);
    function gFor(id) {
        if (!cache[id]) { var h = {}; for (var k in e) h[k] = e[k]; h.hover = id; cache[id] = L.layout(its, h); }
        return cache[id];
    }
    var base = rectsOf(g0), moved = [], unstable = [], probes = 0;
    g0.chips.forEach(function (c) {
        var now = rectsOf(gFor(c.id));
        if (now.join('\n') !== base.join('\n')) moved.push(c.text);
    });
    for (var x = 0; x < e.width; x += step) {
        for (var yy = 0; yy < e.height; yy += step) {
            var a = L.hit(g0, its, x, yy, tol);
            if (!a) continue;
            probes++;
            var b = L.hit(gFor(a.id), its, x, yy, tol);
            if (!b || b.id !== a.id) unstable.push([x, yy, a.id, b ? b.id : null]);
        }
    }
    return { chips: g0.chips.length, moved: moved, probes: probes, unstable: unstable.slice(0, 5),
             nUnstable: unstable.length };
}
/* a crowded scene: the fixture plus 60 seeded levels across the pane */
var seed = 7;
function rnd() { seed = (seed * 1103515245 + 12345) % 2147483648; return seed / 2147483648; }
var crowdRows = M.rows.slice(), crowdSeen = {};
M.rows.forEach(function (r) { crowdSeen[r.price.toFixed(5)] = true; });
for (var ci = 0; ci < 60; ci++) {
    var cp = Math.round((1.0775 + rnd() * 0.0165) * 100000) / 100000, cside = cp < M.mark ? 'below' : 'above';
    if (crowdSeen[cp.toFixed(5)]) { ci--; continue; }           /* one level per price, as the server sends */
    crowdSeen[cp.toFixed(5)] = true;
    var catr = Math.round(Math.abs(cp - M.mark) / 0.0015894669 * 100) / 100, cdays = 0.3 + rnd() * 9;
    if (rnd() < 0.35) {
        var cm = [cp - 0.00008, cp + 0.00008];
        crowdRows.push(pool(cp, cside, catr, cm, { top: cm[1], bottom: cm[0],
            members: [{ price: cm[0], origin: M.now - Math.round(cdays * 86400) },
                      { price: cm[1], origin: M.now - Math.round(cdays * 0.5 * 86400) }] }));
    } else {
        crowdRows.push(swing(cp, cside, catr, { origin: M.now - Math.round(cdays * 86400),
                                                label: cside === 'below' ? 'HL' : 'LH' }));
    }
}
var crowdItems = digest(crowdRows);
out.flicker = {
    fix: stability(items, env(), 2, 6),
    phone: stability(items, env({ phone: true, width: 330 }), 2, 12),
    crowd: stability(crowdItems, env({ showAll: true }), 2, 6),
    crowdPhone: stability(crowdItems, env({ showAll: true, phone: true, width: 330 }), 2, 12),
    crowdMoney: stability(crowdItems, env({ showAll: true, money: money(toY, M.pos, M.pinned), labels: true,
                                            laneW: 96, pinned: true,
                                            boxes: L.markerBoxes(markerPoints(toY, 740), 10, 10),
                                            asia: { high: M.asia.high, low: M.asia.low, x0: 440, x1: 500 } }), 2, 6),
    sweep: out.sweep.slice(0, 6).map(function (c, i) {
        var ty = toYs(c.scale, c.shift), W = c.W, m = money(ty, M.pos, M.pinned);
        return stability(items, env({ toY: ty, width: W, phone: c.phone, money: m, labels: true, laneW: 96,
                                      hlines: [ty(1.08700)], lastY: ty(M.mark), boxes: c.boxes, pinned: true,
                                      asia: { high: M.asia.high, low: M.asia.low, x0: W * 0.6, x1: W * 0.68 } }),
                         3, c.phone ? 12 : 6);
    })
};

/* ...a hovered plain tick (no chip by the rules) is forced in last: every
   other chip stays where it was */
var farTickId = 'sv-lvl-swing-1.07676000000';
out.hotTick = { bare: geo(L.layout(items, env({ showAll: true }))),
                hot: geo(L.layout(items, env({ showAll: true, hover: farTickId }))) };

/* 38. The hunt and the draw on ONE pool: both named. */
var samePath = [{ leg: 'hunt', price: 1.08226, why: "the longs' stops" },
                { leg: 'draw', price: 1.08226, why: 'the bias is short at 0.70' }];
var sameItems = digest(null, samePath);
var sameHunt = sameItems.filter(function (l) { return l.role; });
out.same = {
    roles: sameHunt.map(function (l) { return [l.id, l.role, l.role2 || null, l.why2 || null]; }),
    chip: L.chipText(sameHunt[0], false), phone: L.chipText(sameHunt[0], true),
    keyBelow: L.keyAnswer(sameItems, 'below', false), keyAbove: L.keyAnswer(sameItems, 'above', false),
    keyPhone: L.keyAnswer(sameItems, 'below', true),
    card: HC.levelCard(sameHunt[0], { path: samePath }, M.now),
    fix: geo(L.layout(sameItems, env())),
    narrow: geo(L.layout(sameItems, env({ width: 140, lastY: null }))),
    offPane: geo(L.layout(sameItems, env({ toY: toYs(20000, 130) }))),
    facts: L.moneyFacts({ side: 'short', entry: 1.0850, stop: 1.0870, tp: 1.08230 }, sameItems, fmt),
    hatch: geo(L.layout(sameItems, env({ money: money(toY, M.pos, null) }))).hatch
};

/* 39. The off-pane count under the page's own boxes: a 1014 px pane whose
   top band is all crosshair legend and countdown, a TP at y 9. */
var wideOverlays = [{ x0: 0, x1: 867, y0: 0, y1: 34 }, { x0: 867, x1: 1006, y0: 0, y1: 34 }];
var upTy130 = toYs(20000, -130);
var tpRow = { price: 1.08855, y: upTy130(1.08855), held: true };
out.edgeUnder = { overlays: wideOverlays, rows: [tpRow.y, upTy130(M.mark)],
                  g: geo(L.layout(items, env({ toY: upTy130, width: 1014, overlays: wideOverlays,
                                               money: [tpRow], labels: true, laneW: 96 }))) };
/* ...and no slot at all: no count placed blind, the role said unplaced */
out.edgeNone = geo(L.layout(items, env({ toY: upTy130, overlays: [{ x0: 0, x1: 740, y0: 0, y1: 34 }],
                                         boxes: [{ x0: 0, x1: 740, y0: 34, y1: 384 }] })));

/* 40. The ASIA label never crosses a money row (only a role's stub may). */
out.asiaRows = asiaCase({ W: 740, H: 384, x0: 560, x1: 600, yh: 200, yl: 230, last: 350,
                          rows: [R(192, 'LONG 25000'), R(238, 'SL')] });

/* 41. A level formed after the visible range (scrolled back): nothing of
   it on this pane. */
function toXshift(W, dx) { var f = toXw(W); return function (t) { var x = f(t); return x < 0 ? x : x + dx; }; }
out.past = geo(L.layout(items, env({ toX: toXshift(740, 500) })));

/* 42. Phone 4h: the role chips keep off the neighbouring pools' bands,
   dots and rays (the DRAW chip printed on the EQH 1.09200 band). */
var T04 = M.now - 240 * 14400;
function toX4h(W) { return function (t) { return t < T04 ? -1 : (t - T04) / 14400 * (W - 68) / 240; }; }
var ty4 = function (p) { return 140 - (p - 1.08954) * 5894; };
out.phone4 = {
    levels: geo(L.layout(items, env({ toY: ty4, toX: toX4h(268), width: 268, height: 240, phone: true,
                                      lastY: ty4(M.mark) }))),
    position: geo(L.layout(items, env({ toY: ty4, toX: toX4h(268), width: 268, height: 240, phone: true,
                                        lastY: ty4(M.mark), money: money(ty4, M.pos, null), labels: true,
                                        laneW: 80 }))),
    full: geo(L.layout(items, env({ toY: ty4, toX: toX4h(268), width: 268, height: 240, phone: true,
                                    lastY: ty4(M.mark), money: money(ty4, M.pos, M.pinned), labels: true,
                                    laneW: 80, pinned: true }))),
    desk: geo(L.layout(items, env({ toY: ty4, toX: toX4h(1014), width: 1014, height: 327,
                                    lastY: ty4(M.mark), money: money(ty4, M.pos, M.pinned), labels: true,
                                    laneW: 96, pinned: true })))
};

/* 43. The TP in the draw's zone and a nearer pool's: the draw is named. */
var tpItems = L.digest([
    pool(1.08850, 'above', 1.88, [1.0884, 1.0886], { top: 1.0886, bottom: 1.0884,
        zone: [Math.round((1.0884 - 0.25 * 0.00159) * 1e10) / 1e10, Math.round((1.0886 + 0.5 * 0.00159) * 1e10) / 1e10] }),
    pool(1.08954, 'above', 2.53, [1.08934, 1.08974], { top: 1.08974, bottom: 1.08934,
        zone: [Math.round((1.08934 - 0.25 * 0.00159) * 1e10) / 1e10, Math.round((1.08974 + 0.5 * 0.00159) * 1e10) / 1e10] })
], { path: [{ leg: 'draw', price: 1.08954, why: 'w' }] }, fmt);
out.tpDraw = L.moneyFacts({ side: 'long', entry: 1.084, stop: 1.0800, tp: 1.0890 }, tpItems, fmt);

/* 44. The chip under a point, by its exact box (the widget asks it first). */
out.hitChip = { on: L.hitChip(gh, items, (huntChip.x0 + huntChip.x1) / 2, (huntChip.y0 + huntChip.y1) / 2),
                off: L.hitChip(gh, items, 10, 10), none: L.hitChip(null, items, 1, 1) };
if (out.hitChip.on) out.hitChip.on = { id: out.hitChip.on.id, item: !!out.hitChip.on.item };

/* ── The acceptance fixes, round 2 (2026-10-08) ────────────────────── */

/* 45. The harness's levels views, modelled (a 1016×327 desktop pane and
   a 268×240 phone pane, 240 bars across, 1h and 4h): the newest 30 bars
   as the layer hands them (high to low, one box a bar), today's Asia box
   at the right edge, the page's boxes over the top band, the last
   price's row. The latest swing high and low sit inside the newest bars
   on every frame, as they nearly always do, so no clear slot exists for
   either ray chip: it sits on its ray over the candles rather than being
   dropped (the rays were anonymous blue dashes in every default view). */
function view(tf, phone) {
    var W = phone ? 268 : 1016, H = phone ? 240 : 327, per = tf === '4h' ? 14400 : 3600;
    var bar = W / 240, newest = M.now - M.now % per;                /* the newest bar's open */
    var tx = function (t) { var n = (newest - t) / per; return n > 239 ? -1 : W - (n + 0.5) * bar; };
    var ty = tf === '4h' ? (phone ? ty4 : function (p) { return 190 - (p - 1.08954) * 8140; })
                         : (phone ? function (p) { return 69 - (p - 1.08974) * 15465; }
                                  : function (p) { return 97.5 - (p - 1.08954) * 20972; });
    var hiBar = Math.round((newest - M.rows[10].origin) / per), loBar = Math.round((newest - M.rows[8].origin) / per);
    var candles = [];
    for (var i = 29; i >= 0; i--) {                                   /* i bars back from the newest */
        var c = 1.0853 + 0.0022 * Math.sin(i * 0.7), hi = c + 0.0006, lo = c - 0.0006;
        if (i === hiBar) hi = 1.08775; if (i === loBar) lo = 1.08288;
        hi = Math.min(hi, 1.08775); lo = Math.max(lo, 1.08288);
        var x = W - (i + 0.5) * bar;
        candles.push({ x0: x - bar / 2, x1: x + bar / 2, y0: ty(hi) - 1, y1: ty(lo) + 1 });
    }
    var aBars = tf === '4h' ? [4, 4] : [15, 12];                     /* today's session: one 4h bar, four 1h bars */
    var asia = { high: M.asia.high, low: M.asia.low, x0: W - (aBars[0] + 1) * bar, x1: W - aBars[1] * bar };
    var overlays = phone ? [{ x0: W - 140, x1: W - 6, y0: 0, y1: 34 }]
                         : [{ x0: 0, x1: 416, y0: 0, y1: 34 }, { x0: W - 145, x1: W - 6, y0: 0, y1: 34 }];
    var e = env({ toY: ty, toX: tx, width: W, height: H, phone: phone, lastY: ty(M.mark),
                  candles: candles, overlays: overlays, asia: asia, titles: [] });
    return { W: W, H: H, candles: candles, g: geo(L.layout(items, e)) };
}
out.views = { desk1h: view('1h', false), desk4h: view('4h', false),
              phone1h: view('1h', true), phone4h: view('4h', true) };

/* 46. A role's chip at its origin may touch a neighbour's band edge. A
   pool whose band top sits `overlap` px into the HUNT chip's outside slot
   (the 4h view: the EQL 1.08001 band grazed by 0.3 px sent the HUNT chip
   850 px away, to the left edge): under LV.GRAZE it is no clash; a little
   more and the slot is nudged into the HUNT band's edge; more still and
   the next slot. */
function grazeCase(overlap) {
    var huntOut = toY(1.08211) + 1 + LV.CHIP_H;                       /* the HUNT chip's bottom in its outside slot */
    var top = Math.round((1.0855 - (huntOut - overlap - 200) / 20000) * 1e6) / 1e6, bottom = top - 0.0003;
    var price = Math.round((top + bottom) / 2 * 1e6) / 1e6;
    var rows = M.rows.concat([pool(price, 'below', (M.mark - price) / 0.0015894669, [bottom, top],
                                   { top: top, bottom: bottom })]);
    var g = L.layout(digest(rows), env());
    var hunt = g.chips.filter(function (c) { return c.role === 'hunt'; })[0] || null;
    var band = g.bands.filter(function (b) { return b.role === 'hunt'; })[0];
    var next = g.bands.filter(function (b) { return Math.abs(b.y0 - toY(top)) < 1e-6; })[0] || null;
    return { chip: geo(hunt), band: geo(band), neighbour: geo(next), out: toY(1.08211) + 1, g: geo(g) };
}
out.graze = { touch: grazeCase(0.5), nudge: grazeCase(2.5), next: grazeCase(6) };

/* 47. A ray's chip falls back to its short words at the ray's start: a
   marker box over the left part of the full chip's only slots (the lane
   closed, so every origin slot ends at the lane). */
var rayBox = { x0: 540, x1: 600, y0: toY(1.08775) - 40, y1: toY(1.08775) + 40 };
out.rayShort = { box: rayBox, laneX: 740 - 80,
                 g: geo(L.layout(items, env({ labels: true, laneW: 80, boxes: [rayBox] }))) };

process.stdout.write(JSON.stringify(out));
"""


def _js_round(v):
    """Math.round: half up, not Python's half to even."""
    return math.floor(v + 0.5)


def _age_words(seconds):
    """window.svHoverCards.ageWords, for the expected Formed fact."""
    h = seconds / 3600
    if h < 1:
        return "%d min" % _js_round(seconds / 60)
    if h < 48:
        return "%s h" % _js_num(_js_round(h * 10) / 10)
    return "%s d" % _js_num(_js_round(h / 24 * 10) / 10)


def _js_num(v):
    return str(int(v)) if float(v).is_integer() else str(v)


def _meets(a, b, gx=0, gy=0):
    return (a["x0"] < b["x1"] + gx and a["x1"] > b["x0"] - gx
            and a["y0"] < b["y1"] + gy and a["y1"] > b["y0"] - gy)


@unittest.skipUnless(NODE, "node is not installed")
class TheLevelsLanguageTests(SimpleTestCase):
    """window.svLevels and the cards' new facts, under node, as shipped."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        pure, _main = _blocks(widget())
        cls.out = _node("var window = {};\n" + pure + "\n" + PURE_RUN, {
            "rows": FIXTURE_ROWS, "path": PATH, "now": NOW, "mark": MARK,
            "pos": POSITION, "pinned": PINNED, "asia": ASIA,
            "markers": MARKERS})
        cls.items = {i["price"]: i for i in cls.out["items"]}

    def _ids(self, shapes):
        return sorted(s["id"] for s in shapes)

    # 1
    def test_a_pool_absorbs_exactly_its_members(self):
        items = self.out["items"]
        self.assertEqual(len(items), 10)
        kinds = sorted(i["lv"] for i in items)
        self.assertEqual(kinds, ["pool"] * 4 + ["recent"] * 2 + ["round"] * 3 + ["swing"])
        members = {1.07986, 1.08016, 1.08211, 1.08241, 1.08934, 1.08974, 1.09184, 1.09216}
        swings = [i for i in items if i["lv"] == "swing"]
        self.assertFalse(members & {s["price"] for s in swings})
        self.assertEqual([(s["price"], s["far"]) for s in swings], [(1.07676, True)])
        hunt = self.items[1.08226]
        self.assertEqual((hunt["bottom"], hunt["top"], hunt["touches"]), (1.08211, 1.08241, 2))
        self.assertEqual(hunt["origin"], _bar4h(6.0), "the first touch")

    # 2
    def test_two_pools_side_by_side_keep_their_own_members(self):
        by = {i["price"]: i for i in self.out["twoPools"]}
        a, b = by[1.08025], by[1.08095]
        self.assertEqual((a["bottom"], a["top"]), (1.08000, 1.08050))
        self.assertEqual((b["bottom"], b["top"]), (1.08040, 1.08150))
        # Only the swing that is nobody's member is left; neither pool
        # swallowed the other's.
        self.assertEqual([i["price"] for i in self.out["twoPools"] if i["lv"] == "swing"],
                         [1.07900])

    # 3
    def test_an_uneven_three_touch_pool_is_one_band(self):
        items = self.out["three"]
        self.assertEqual(len(items), 1)
        p = items[0]
        self.assertEqual((p["lv"], p["bottom"], p["top"], p["touches"]),
                         ("pool", 1.08000, 1.08107, 3))

    # 4
    def test_a_row_from_before_the_change_draws_unfolded(self):
        by = {(i["lv"], i["price"]): i for i in self.out["old"]}
        p = by[("pool", 1.08226)]
        self.assertEqual((p["top"], p["bottom"], p["touches"], p["origin"]),
                         (1.08226, 1.08226, 2, None))
        self.assertIn(("swing", 1.08211), by)
        self.assertIn(("swing", 1.08241), by)
        band = self.out["oldGeo"]["bands"][0]
        self.assertEqual((band["x0"], band["clipped"]), (0, True), "no origin: from the left edge")

    # 5
    def test_the_extreme_on_a_swing_or_in_a_band_is_one_item(self):
        items = self.out["recent"]
        by = {(i["lv"], i["price"]): i for i in items}
        self.assertNotIn(("recent", 1.08300), by)
        self.assertNotIn(("recent", 1.08230), by)
        self.assertTrue(by[("swing", 1.08300)]["recent"])
        self.assertTrue(by[("pool", 1.08226)]["recent"])
        self.assertIn(("recent", 1.08775), by, "an extreme on its own stays")
        self.assertEqual(by[("swing", 1.08300)]["chip"], "HL · LAST  1.08300")
        self.assertEqual(by[("swing", 1.08300)]["phone"], "HL LAST")

    # 6
    def test_reach_and_caps_are_flags(self):
        far = "sv-lvl-swing-1.07676000000"
        self.assertTrue(self.items[1.07676]["far"])
        fix = self.out["fix"]
        self.assertNotIn(far, self._ids(fix["ticks"] + fix["rays"]))
        self.assertIn(far, self._ids(self.out["showAll"]["ticks"]), "Show all draws it as a tick")
        self.assertNotIn(far, self._ids(self.out["showAll"]["rays"]))
        four = self.out["four"]
        self.assertEqual([i["capped"] for i in four], [False, False, False, True])
        self.assertEqual([i["far"] for i in four], [False] * 4)
        drawn = self._ids(self.out["fourGeo"]["ticks"])
        self.assertEqual(len(drawn), 3)
        self.assertNotIn("sv-lvl-swing-1.08150000000", drawn)

    # 7
    def test_one_ray_per_side_the_nearest(self):
        rays = sorted(i["price"] for i in self.out["items"] if i["ray"])
        self.assertEqual(rays, [1.08288, 1.08775])
        self.assertEqual(self._ids(self.out["fix"]["rays"]),
                         ["sv-lvl-recent-1.08288000000", "sv-lvl-recent-1.08775000000"])
        # Every other swing is a tick only: a ray is the nearest's alone.
        self.assertEqual(len(self.out["showAll"]["rays"]), 2)

    # 8
    def test_hunt_and_draw_by_band_containment(self):
        roles = {i["price"]: i["role"] for i in self.out["items"] if i["role"]}
        self.assertEqual(roles, {1.08226: "hunt", 1.08954: "draw"})
        self.assertEqual(self.items[1.08226]["why"], "the longs' stops")
        # A leg at 1.08230: inside the band, not equal to the average.
        roles = {i["price"]: i["role"] for i in self.out["containment"] if i["role"]}
        self.assertEqual(roles, {1.08226: "hunt", 1.08954: "draw"})

    # 9
    def test_a_round_inside_a_band_is_quiet_and_marks_the_pool(self):
        self.assertTrue(self.items[1.08]["quiet"])
        self.assertTrue(self.items[1.09]["quiet"])
        self.assertFalse(self.items[1.085]["quiet"])
        self.assertIn("◎", self.items[1.08001]["chip"])
        self.assertIn("◎", self.items[1.08954]["chip"])
        self.assertNotIn("◎", self.items[1.092]["chip"])
        # All three lines are still drawn; only 1.08500 has a chip.
        self.assertEqual(len(self.out["fix"]["rounds"]), 3)
        round_chips = [c["text"] for c in self.out["fix"]["chips"] if c["lv"] == "round"]
        self.assertEqual(round_chips, ["1.08500"])

    # 10
    def test_money_holds_levels_past_the_caps_and_reach(self):
        held = {i["price"]: i for i in self.out["held"]["items"]}
        self.assertTrue(held[1.083]["capped"], "the 4th swing below")
        bare = self._ids(self.out["held"]["bare"]["ticks"])
        self.assertNotIn("sv-lvl-swing-1.08300000000", bare)
        pos = self._ids(self.out["held"]["pos"]["ticks"])
        for p in ("1.08480", "1.08420", "1.08360", "1.08300"):
            self.assertIn("sv-lvl-swing-%s000000" % p, pos, p)
        # Rule (b): the pinned signal's stop inside the capped level's zone.
        pin = self._ids(self.out["held"]["pin"]["ticks"])
        self.assertIn("sv-lvl-swing-1.08300000000", pin)

    # 11
    def test_a_level_within_8px_of_a_money_row_is_drawn(self):
        six = self._ids(self.out["near8"]["six"]["ticks"])
        twelve = self._ids(self.out["near8"]["twelve"]["ticks"])
        self.assertIn("sv-lvl-swing-1.08300000000", six)
        self.assertNotIn("sv-lvl-swing-1.08300000000", twelve)

    # 12
    def test_kind_toggles_hide_kinds_but_never_a_role(self):
        self.assertEqual(self._ids(self.out["noPools"]["bands"]),
                         ["sv-lvl-pool-1.08226000000", "sv-lvl-pool-1.08954000000"])
        self.assertEqual(self.out["noPools"]["count"]["pool"], 2)
        no_swings = self.out["noSwings"]
        self.assertEqual(no_swings["ticks"] + no_swings["rays"] + no_swings["rounds"], [])
        self.assertEqual(len(no_swings["bands"]), 4)

    # 13
    def test_layout_band_floor_and_left_clip(self):
        band = self.out["oldGeo"]["bands"][0]
        self.assertAlmostEqual(band["y1"] - band["y0"], 4.0, places=6)
        clipped = [b for b in self.out["fix"]["bands"] if b["id"] == "sv-lvl-pool-1.09200000000"][0]
        self.assertEqual((clipped["x0"], clipped["clipped"]), (0, True))
        hunt = [b for b in self.out["fix"]["bands"] if b["role"] == "hunt"][0]
        self.assertFalse(hunt["clipped"])
        self.assertGreater(hunt["x0"], 0)
        self.assertAlmostEqual(hunt["y1"] - hunt["y0"], 6.0, places=6, msg="the band spans its members")
        dots = [d for d in self.out["fix"]["dots"] if d["id"] == "sv-lvl-pool-1.09200000000"]
        self.assertEqual(len(dots), 1, "the touch before the loaded bars has no dot")

    # 14
    def test_daily_frames_keep_pools_and_two_rays(self):
        d = self.out["daily"]
        self.assertEqual(len(d["bands"]), 4)
        self.assertEqual(len(d["rays"]), 2)
        self.assertEqual(d["ticks"], [])
        self.assertEqual(d["rounds"], [])
        self.assertIsNone(d["asia"])
        self.assertIsNone(d["hatch"])
        self.assertFalse([c for c in d["chips"] if c["lv"] == "round"])

    def _assert_clean(self, case, where):
        """No chip on a money row unless it is a role crossing it; none
        on a marker box, none in the lane, none on another chip."""
        g, W, laneW = case["g"], case["W"], case["laneW"]
        chips = g["chips"]
        for c in chips:
            self.assertLessEqual(c["x1"], W - laneW + 1e-9, (where, c))
            self.assertGreaterEqual(c["x0"], 0, (where, c))
            self.assertGreaterEqual(c["y0"], 0, (where, c))
            self.assertLessEqual(c["y1"], 384, (where, c))
            for b in case["boxes"]:
                self.assertFalse(_meets(c, b), (where, c, b))
            if c["cross"]:
                self.assertTrue(c["role"], (where, c))
            else:
                for y in case["rows"]:
                    self.assertFalse(c["y0"] - 2 <= y <= c["y1"] + 2, (where, c, y))
        for i, a in enumerate(chips):
            for b in chips[i + 1:]:
                self.assertFalse(_meets(a, b), (where, a, b))

    # 15
    def test_role_chips_survive_money_next_to_them(self):
        for key in ("crowd", "crowdPhone"):
            case = self.out[key]
            g = case["g"]
            roles = sorted(c["role"] for c in g["chips"] if c["role"])
            self.assertEqual(roles, ["draw", "hunt"], key)
            self.assertEqual(g["unplaced"], [], key)
            self._assert_clean(case, key)
            for c in g["chips"]:
                if c["cross"]:
                    self.assertIn(c["text"], ("①HUNT", "②DRAW"), "a crossing chip is a stub")
        # The SL 4 px under the HUNT band pushed its chip off the band's
        # outside slot.
        hunt = [c for c in self.out["crowd"]["g"]["chips"] if c["role"] == "hunt"][0]
        band = [b for b in self.out["crowd"]["g"]["bands"] if b["role"] == "hunt"][0]
        self.assertFalse(hunt["y0"] == band["y1"] + 1 and not hunt["cross"])

    # 16
    def test_money_rows_and_markers_are_never_covered(self):
        self.assertEqual(len(self.out["sweep"]), 18)
        boxes = 0
        for case in self.out["sweep"]:
            where = (case["scale"], case["shift"], case["phone"])
            self._assert_clean(case, where)
            boxes += len(case["boxes"])
            for e in case["g"]["edges"]:            # an edge count never covers a dot either
                for b in case["boxes"]:
                    self.assertFalse(_meets(e, b), (where, e["text"], b))
            named = {c["role"] for c in case["g"]["chips"] if c["role"]}
            for e in case["g"]["edges"]:
                named.update(e["roles"])
            named.update(case["g"]["unplaced"])
            self.assertEqual(named, {"hunt", "draw"}, where)
        self.assertGreater(boxes, 0, "the sweep carried marker boxes")
        # The fixture's own scale: both roles are chips, nothing unplaced.
        first = self.out["sweep"][0]
        self.assertEqual(first["g"]["unplaced"], [])

    # 17
    def test_the_lane_is_closed_whenever_a_titled_line_exists(self):
        W = 740
        shut = self.out["laneShut"]["chips"]
        self.assertTrue(shut)
        for c in shut:
            self.assertLessEqual(c["x1"], W - 120 + 1e-9, c)
        opened = self.out["laneOpen"]["chips"]
        self.assertTrue([c for c in opened if c["x1"] > W - 80], "the open lane is used")
        for c in shut + opened + self.out["fix"]["chips"]:
            self.assertFalse(c["x1"] > W - 80 and c["y0"] < 34, ("the countdown's corner", c))
        # The level by the countdown: no slot on its own shape clears the
        # corner, and the left edge is 600 px off its band (a chip there
        # named the wrong lines, 2026-10-08), so it has no chip; the hover
        # card still names it.
        band = [b for b in self.out["laneOpen"]["bands"] if b["id"] == "sv-lvl-pool-1.09480000000"][0]
        for c in opened:
            if c["id"] == band["id"]:
                self.assertGreaterEqual(c["x1"], band["x0"], c)

    # 18
    def test_chip_caps_count_roles_and_never_refuse_them(self):
        many = self.out["many"]
        scored = [i for i in many["items"] if i["lv"] == "pool" and not i["role"]
                  and i["price"] not in (1.08001, 1.092)]
        self.assertEqual(len(scored), 6, "six pools that outscore the roles")
        desk, phone = many["desk"]["chips"], many["phone"]["chips"]
        self.assertLessEqual(len(desk), 8)
        self.assertLessEqual(len(phone), 4)
        for chips in (desk, phone):
            self.assertEqual(sorted(c["role"] for c in chips if c["role"]), ["draw", "hunt"])
        self.assertEqual(len(desk), 8, "the cap is reached, roles included")
        self.assertEqual(len(phone), 4)

    # 19
    def test_chip_texts(self):
        texts = sorted(c["text"] for c in self.out["fix"]["chips"])
        self.assertEqual(texts, sorted([
            "EQL ×2 · ① HUNT  1.08226", "EQH ×2 ◎ · ② DRAW  1.08954",
            "LAST HIGH  1.08775", "LAST LOW  1.08288", "1.08500",
            "EQL ×2 ◎  1.08001", "EQH ×2  1.09200"]))
        self.assertEqual(len(self.out["fix"]["chips"]), 7, "under the desktop cap of 8")
        phone = sorted(c["text"] for c in self.out["fixPhone"]["chips"])
        self.assertEqual(phone, sorted(["EQL×2 ①HUNT", "EQH×2 ◎ ②DRAW", "LAST H", "LAST L"]))
        self.assertEqual(self.items[1.08288]["chip"], "LAST LOW  1.08288")
        self.assertEqual(self.items[1.08288]["phone"], "LAST L")
        self.assertEqual(self.items[1.07676]["chip"], "LL  1.07676")
        stubs = sorted(c["text"] for c in self.out["narrow"]["chips"] if c["role"])
        self.assertEqual(stubs, ["①HUNT", "②DRAW"])

    # 20
    def test_origin_slot_prefers_outside_the_band(self):
        g = self.out["free"]
        for role, outside in (("hunt", "below"), ("draw", "above")):
            chip = [c for c in g["chips"] if c["role"] == role][0]
            band = [b for b in g["bands"] if b["role"] == role][0]
            self.assertAlmostEqual(chip["x0"], band["x0"] + 8, places=6)
            if outside == "above":
                self.assertLessEqual(chip["y1"], band["y0"])
            else:
                self.assertGreaterEqual(chip["y0"], band["y1"])

    # 21
    def test_off_pane_levels_are_counted_on_their_edge(self):
        g = self.out["offPane"]
        top = [e for e in g["edges"] if e["side"] == "above"]
        self.assertEqual(len(top), 1)
        self.assertTrue(top[0]["text"].startswith("▲ ② DRAW 1.08954"), top[0]["text"])
        self.assertEqual(top[0]["text"], "▲ ② DRAW 1.08954 · +2")
        self.assertEqual(top[0]["roles"], ["draw"])
        self.assertEqual(g["count"]["total"], 10)
        self.assertEqual(g["count"]["shown"] + sum(e["n"] for e in g["edges"]), 9,
                         "drawn plus off-pane is every wanted level")
        self.assertNotIn("sv-lvl-pool-1.08954000000", self._ids(g["bands"]))
        for c in g["chips"]:
            for e in g["edges"]:
                self.assertFalse(_meets(c, e), (c, e))
        phone = [e for e in self.out["offPanePhone"]["edges"] if e["side"] == "above"][0]
        self.assertEqual(phone["text"], "▲ ②DRAW · +2")

    # 22
    def test_fade_pin_and_focus_alphas(self):
        f = self.out["fade"]
        self.assertEqual(f["near"], 1)
        self.assertAlmostEqual(f["floorDark"], 0.5)
        self.assertAlmostEqual(f["floorLight"], 0.7)
        self.assertAlmostEqual(f["mid"], 0.75)
        self.assertAlmostEqual(f["far"], 0.5)
        self.assertEqual(f["none"], 1)

        def band(g, price):
            return [b for b in g["bands"] if b["id"] == "sv-lvl-pool-%.11f" % price][0]
        fix, pin, light, pin_l = (self.out[k] for k in ("fix", "pinDark", "light", "pinLight"))
        for g in (fix, pin, light, pin_l):
            self.assertEqual(band(g, 1.08226)["k"], 1, "HUNT is never faded or dimmed")
            self.assertEqual(band(g, 1.08954)["k"], 1, "nor DRAW")
        self.assertAlmostEqual(band(fix, 1.092)["k"], f["at408dark"])
        self.assertAlmostEqual(band(pin, 1.092)["k"], 0.55 * f["at408dark"])
        self.assertAlmostEqual(band(light, 1.092)["k"], f["at408light"])
        self.assertAlmostEqual(band(pin_l, 1.092)["k"], 0.8 * f["at408light"])
        for c in pin["chips"] + pin_l["chips"]:
            self.assertEqual(c["k"], 1, "chips are never pin-dimmed")
        focus = self.out["focusSwing"]
        self.assertAlmostEqual(band(focus, 1.08226)["k"], 0.2)
        for c in focus["chips"]:
            self.assertEqual(c["k"], 1 if c["lv"] == "recent" else 0.2, c)
        hunt_focus = self.out["focusHunt"]
        self.assertEqual(band(hunt_focus, 1.08226)["k"], 1)
        self.assertAlmostEqual(band(hunt_focus, 1.08954)["k"], 0.2)
        hover = self.out["hover"]
        self.assertEqual(band(hover, 1.092)["k"], 1, "the hovered level glows, pinned or not")
        self.assertTrue(band(hover, 1.092)["hot"])

    # 23
    def test_hunt_zone_hatch_only_when_asked(self):
        h = self.out["hatch"]
        self.assertIsNone(h["none"])
        self.assertIsNone(h["sigStop"], "a signal's stop is not the operator's money")
        for k in ("stop", "hover", "focus"):
            self.assertIsNotNone(h[k], k)
            self.assertAlmostEqual(h[k]["y0"], h["zone"][0], places=6)
            self.assertAlmostEqual(h[k]["y1"], h["zone"][1], places=6)
            self.assertEqual(h[k]["x0"], h["huntX0"])
            self.assertEqual(h[k]["lv"], "pool")

    # 24
    def test_marker_boxes_follow_lwc_geometry(self):
        b = self.out["boxes"]
        one = b["one"][0]
        self.assertEqual(one["y1"], 200 - 1)
        self.assertEqual(one["y1"] - one["y0"], 15 + 12 + 4)
        self.assertEqual(one["x1"] - one["x0"], 15 + 4)
        first, second = b["two"]
        self.assertEqual(first, one)
        self.assertLessEqual(second["y1"], first["y0"] + 4)
        self.assertLess(second["y0"], first["y0"])
        below = b["below"][0]
        self.assertEqual(below["y0"], 220 + 1)
        self.assertEqual(below["y1"] - below["y0"], 31)
        self.assertEqual(b["skip"], [])

    # 25
    def test_hit_tests_the_shapes_as_drawn(self):
        h = self.out["hit"]
        self.assertEqual(h["band"], {"id": "sv-lvl-pool-1.08954000000", "item": True})
        self.assertIsNone(h["leftOfTouch"])
        self.assertEqual(h["tick"], {"id": "sv-lvl-swing-1.07676000000", "item": True})
        self.assertIsNone(h["tickFar6"])
        self.assertEqual(h["tickFar12"]["id"], "sv-lvl-swing-1.07676000000")
        self.assertEqual(h["ray"]["id"], "sv-lvl-recent-1.08288000000")
        self.assertEqual(h["asiaHigh"], {"id": "sv-lvl-asia", "edge": "high"})
        self.assertEqual(h["asiaLow"], {"id": "sv-lvl-asia", "edge": "low"})
        self.assertEqual(h["asiaIn"], {"id": "sv-lvl-asia", "edge": "high"})
        self.assertEqual(h["chip"], {"id": "sv-lvl-pool-1.08226000000", "item": True})
        self.assertEqual(h["round"]["id"], "sv-lvl-round-1.08500000000")
        self.assertIsNone(h["roundMiss"])
        self.assertIsNone(h["nothing"])
        self.assertIsNone(h["noGeom"])

    # 26
    def test_key_answers_name_the_roles_or_the_nearest(self):
        k = self.out["key"]
        self.assertEqual(k["below"]["text"], "▼ ① HUNT 1.08226 EQL×2 · 2.05 ATR")
        self.assertEqual(k["above"]["text"], "▲ ② DRAW 1.08954 EQH×2 · 2.53 ATR")
        self.assertEqual((k["below"]["role"], k["below"]["kind"], k["below"]["why"]),
                         ("hunt", "pool", "the longs' stops"))
        self.assertEqual(k["belowNoPath"]["text"], "▼ 1.08226 EQL×2 · 2.05 ATR")
        self.assertEqual(k["aboveNoPath"]["text"], "▲ 1.08954 EQH×2 · 2.53 ATR")
        self.assertIsNone(k["belowNoPath"]["role"])
        self.assertEqual(k["phone"]["text"], "▼ ① HUNT 1.08226 · 2.05 ATR")
        self.assertEqual(k["swingOnly"]["text"], "▲ 1.08775 LAST H · 1.40 ATR")
        self.assertEqual(k["swingOnly"]["kind"], "swing")
        self.assertIsNone(k["empty"])

    # 27
    def test_money_facts_on_the_position_card(self):
        m = self.out["money"]
        self.assertEqual([f["text"] for f in m["facts"]],
                         ["Stop inside the hunt zone 1.08132–1.08281",
                          "TP at the draw: the equal highs pool 1.08954"])
        self.assertEqual([f["tone"] for f in m["facts"]], ["loss", ""])
        self.assertEqual([f["text"] for f in m["other"]],
                         ["Stop inside the zone of the equal lows pool 1.08001",
                          "TP at the equal highs pool 1.09200"])
        self.assertEqual(m["none"], [])
        self.assertEqual(m["empty"], [])
        self.assertIn('<span class="sv-sig-chip sv-sig-chip--loss">'
                      'Stop inside the hunt zone 1.08132–1.08281</span>', m["card"])
        self.assertIn('<span class="sv-sig-chip">'
                      'TP at the draw: the equal highs pool 1.08954</span>', m["card"])
        self.assertEqual(m["plain"], m["blank"])
        self.assertNotIn("hunt zone", m["plain"])

    # 28
    def test_level_card_facts(self):
        c = self.out["cards"]
        hunt = c["hunt"]
        self.assertIn("<dt>Band</dt><dd>1.08211 – 1.08241</dd>", hunt)
        self.assertIn("<dt>Touches</dt><dd>2</dd>", hunt)
        formed = _age_words(NOW - _bar4h(6.0))
        self.assertIn("<dt>Formed</dt><dd>%s ago</dd>" % formed, hunt)
        self.assertIn("<dt>Hunt zone</dt><dd>1.08132–1.08281</dd>", hunt)
        self.assertIn("The hunt runs here first — the longs&#39; stops", hunt)
        self.assertNotIn("Formed", c["huntNoNow"])
        self.assertIn("The draw after the hunt — the bias is long at 0.70", c["draw"])
        self.assertNotIn("Hunt zone", c["draw"])
        self.assertIn("<dt>Structure</dt><dd>LL</dd>", c["swing"])
        self.assertIn("The last swing still held", c["swing"])
        self.assertIn("The latest pullback&#39;s extreme", c["recent"])
        self.assertNotIn("Band", c["oldPool"], "a band with no height is no fact")
        self.assertNotIn("Formed", c["oldPool"])
        for key, before in BEFORE_CARDS.items():
            self.assertEqual(c["today"][key], before, key)
        self.assertEqual(c["todayWithNow"], BEFORE_CARDS["level"],
                         "a row without an origin has no Formed")

    # 29
    def test_malformed_rows_are_skipped(self):
        bad = self.out["bad"]
        kinds = sorted((i["lv"], i["price"]) for i in bad["items"])
        self.assertEqual(kinds, [("pool", 1.083), ("swing", 1.082)])
        swing = [i for i in bad["items"] if i["lv"] == "swing"][0]
        self.assertEqual((swing["far"], swing["capped"], swing["zoneText"]), (False, False, None))
        pool = [i for i in bad["items"] if i["lv"] == "pool"][0]
        self.assertEqual((pool["bottom"], pool["top"], pool["origin"], pool["zoneText"]),
                         (1.0829, 1.083, None, None))
        self.assertIsNone(pool["role"])
        self.assertEqual(bad["geo"]["count"]["total"], 2)
        self.assertEqual(bad["key"]["text"], "▼ 1.083 EQL×2 · 1.00 ATR")
        self.assertEqual(bad["keySwing"]["text"], "▼ 1.082 SWING L", "no distance, no ATR")
        self.assertEqual(bad["nothing"], [])
        self.assertEqual(bad["nothingGeo"]["chips"], [])
        # No map at all (digest(rows) alone): every row kept, no role.
        self.assertEqual(len(bad["noMap"]), 3)
        self.assertEqual([i["role"] for i in bad["noMap"]], [None] * 3)

    # ── The acceptance fixes (2026-10-07, after the AFTER shots) ─────────

    def _assert_off_the_roles(self, g, where):
        """A non-role chip never sits on a role's band: a tap there must
        reach the role (the phone's LAST L took the HUNT band and the tap
        opened the recent low)."""
        bands = [b for b in g["bands"] if b["role"]]
        self.assertTrue(bands, where)
        for c in g["chips"]:
            if c["role"]:
                continue
            for b in bands:
                self.assertFalse(_meets(c, b, 0, 2), (where, c["text"], b["role"]))

    def test_a_non_role_chip_keeps_off_the_roles_bands(self):
        self._assert_off_the_roles(self.out["fix"], "fix")
        self._assert_off_the_roles(self.out["fixPhone"], "phone")
        for case in self.out["sweep"]:
            self._assert_off_the_roles(case["g"], (case["scale"], case["shift"], case["phone"]))
        # The phone still names its four, LAST L off the HUNT band.
        phone = {c["text"]: c for c in self.out["fixPhone"]["chips"]}
        self.assertIn("LAST L", phone)
        # ...and a tap on the HUNT band right of its chip finds the HUNT.
        hunt = [b for b in self.out["fixPhone"]["bands"] if b["role"] == "hunt"][0]
        for c in self.out["fixPhone"]["chips"]:
            if not c["role"]:
                self.assertFalse(c["x0"] <= 257 <= c["x1"] and c["y0"] <= hunt["y0"] <= c["y1"])

    def _assert_on_ray(self, c, r, where):
        """The chip sits on its ray: never ending left of the ray's start,
        and within 4 px of its row (a slot is 1 px off the ray or across
        it, nudged up to LV.NUDGE = 3 px)."""
        self.assertGreaterEqual(c["x1"], r["x0"], (where, c["text"]))
        self.assertLessEqual(c["x0"], r["x1"], (where, c["text"]))
        self.assertTrue(c["y0"] - 4 <= r["y"] <= c["y1"] + 4, (where, c["text"], c["y0"], c["y1"], r["y"]))

    def test_no_chip_hides_the_newest_candles(self):
        case = self.out["candles"]
        g, boxes = case["g"], case["boxes"]
        self.assertEqual(g["keep"]["candles"], boxes, "the layout says what it kept clear of")
        rays = {r["id"]: r for r in g["rays"]}
        self.assertEqual(len(rays), 2)
        self.assertEqual(sorted(c["role"] for c in g["chips"] if c["role"]), ["draw", "hunt"])
        for c in g["chips"]:
            if c["id"] in rays:
                continue
            for b in boxes:
                self.assertFalse(_meets(c, b), (c["text"], b))
        # Both rays start inside the block: the origin and the open right
        # edge cover candles, and the left edge is 450 px off the ray (the
        # review's shots: 'LAST LOW' at x 4 read as the SL's label), which
        # stays refused. So a ray chip sits on its own ray over the candles
        # — a late pass, as the ASIA label's — rather than being dropped:
        # the latest swing nearly always sits in the last 30 bars, and a
        # ray with no chip is an anonymous blue dash.
        on = {c["text"]: c for c in g["chips"] if c["id"] in rays}
        self.assertEqual(sorted(on), ["LAST HIGH  1.08775", "LAST LOW  1.08288"])
        for c in on.values():
            self._assert_on_ray(c, rays[c["id"]], "candles")
        # LAST HIGH's outside slot overlapped the block by 1 px: nudged 3 px
        # off its ray it is clear, and a clear slot beats a loose one.
        high, low = on["LAST HIGH  1.08775"], on["LAST LOW  1.08288"]
        self.assertFalse(any(_meets(high, b) for b in boxes), "a clear slot, nudged off the ray")
        self.assertAlmostEqual(high["y1"], rays[high["id"]]["y"] - 3, places=6)
        self.assertTrue(any(_meets(low, b) for b in boxes), "no clear slot: on its ray over the candles")
        # Over a pane that is all candles the pools' and the round's chips
        # are dropped (the hover card still names them); the roles and the
        # rays are named all the same.
        wall = self.out["candleWall"]
        self.assertEqual(sorted(c["role"] for c in wall["chips"] if c["role"]), ["draw", "hunt"])
        self.assertEqual(sorted(c["id"] for c in wall["chips"] if not c["role"]), sorted(rays))
        self.assertEqual(wall["unplaced"], [])

    def test_an_edge_count_slides_clear_of_a_dot(self):
        for case in self.out["edgeDots"]:
            home, slid, inward = case["home"], case["slid"], case["inward"]
            where = case["side"]
            self.assertTrue(_meets(home, case["dot"]), "the dot is where the count would sit")
            self.assertFalse(_meets(slid, case["dot"]), where)
            self.assertEqual((slid["y0"], slid["text"], slid["n"], slid["roles"]),
                             (home["y0"], home["text"], home["n"], home["roles"]), where)
            self.assertLess(slid["x1"], home["x1"], "slid left along its own row")
            self.assertLessEqual(slid["x1"], case["dot"]["x0"], where)
            # The whole row taken: one row inward.
            self.assertFalse(_meets(inward, case["row"]), where)
            if where == "above":
                self.assertGreater(inward["y0"], home["y1"])
            else:
                self.assertLess(inward["y1"], home["y0"])
        self.assertEqual(self.out["edgeDots"][0]["home"]["roles"], ["draw"])

    def test_the_asia_label_names_even_a_one_bar_box(self):
        narrow = self.out["asiaNarrow"]
        self.assertEqual(narrow["x1"] - narrow["x0"], 4)
        label = narrow["label"]
        self.assertEqual(label["text"], "ASIA")
        self.assertEqual(label["x0"], 502, "2 px in from the box's left corner, overhanging it")
        self.assertLessEqual(label["y1"], narrow["yh"], "above the box")
        top = self.out["asiaTop"]
        self.assertLess(top["yh"], 15, "no room above")
        self.assertGreaterEqual(top["label"]["y0"], top["yl"], "so under it")
        # The whole lane closed (no title rows given) and the box inside
        # it: nothing on the box or within LV.ASIA_NEAR of it is free, so
        # no label — never one slid 40 px off the box onto other bars.
        lane = self.out["asiaLane"]
        self.assertNotIn("label", lane)
        by = self.out["asiaByLane"]
        self.assertEqual(by["label"]["text"], "ASIA")
        self.assertLessEqual(by["label"]["x1"], 740 - 80, "never in the closed title-box lane")
        self.assertEqual(max(0, by["x0"] - by["label"]["x1"], by["label"]["x0"] - by["x1"]), 0,
                         "on its box")
        self.assertLessEqual(by["label"]["y1"], by["yh"])

    def test_title_boxes_stack_as_the_axis_does(self):
        tb = self.out["titleBoxes"]
        h = 10 * 17 / 12

        def box(y, w):
            return {"x0": 740 - w - 1, "x1": 740, "y0": y - h / 2 - 1, "y1": y + h / 2 + 1}

        def same(got, want):
            self.assertEqual(len(got), len(want), got)
            for g, w in zip(got, want):
                for k in ("x0", "x1", "y0", "y1"):
                    self.assertAlmostEqual(g[k], w[k], places=6, msg=(k, g, w))

        same(tb["lone"], [box(100, 40)])
        # Both above the last price: the upper one goes up, a label's height off.
        same(tb["above"], [box(150, 40), box(150 - h, 60)])
        # Both below it: the lower one goes down.
        same(tb["below"], [box(250, 40), box(250 + h, 60)])
        # The last price's own label pushes a title 3 px under it.
        same(tb["center"], [box(200 + h, 40)])
        # A label with no title box paints nothing but still takes its place.
        same(tb["silent"], [box(104 - h, 40)])
        # A row in the top 7 px sits at 7, as the axis keeps its label in.
        same(tb["edge"], [box(7, 40)])
        same(tb["noCenter"], [box(100, 40), box(100 + h, 40)])
        self.assertEqual(tb["none"], [])

    def test_the_asia_label_stays_on_its_box_beside_the_title_boxes(self):
        """The harness, 2026-10-07: with a position or a pinned signal up,
        the ASIA label slid left of the closed lane — 18 px off its box on
        desktop 1h, 64 px on desktop 4h and phone 1h, 76 px on phone 4h —
        and covered other days' candles. It keeps off the title boxes
        themselves now: on its box, or no label."""
        v = self.out["asiaViews"]

        def gap(a):
            label = a["label"]
            return max(0, a["x0"] - label["x1"], label["x0"] - a["x1"])

        for name in ("d1hPosition", "d1hFull", "p1hPosition"):
            case = v[name]
            a = case["asia"]
            self.assertIn("label", a, name)
            self.assertEqual(gap(a), 0, name)
            self.assertLessEqual(a["label"]["y1"], a["yh"], (name, "above the box"))
            self.assertGreater(a["label"]["x1"], case["laneX"], (name, "inside the lane"))
            self.assertLessEqual(a["label"]["x1"], case["W"])
            self.assertTrue(case["titles"])
            for t in case["titles"]:
                self.assertFalse(_meets(a["label"], t), (name, t))
        self.assertAlmostEqual(v["d1hPosition"]["asia"]["label"]["x0"], 954, places=6,
                               msg="2 px in from its left corner")
        self.assertAlmostEqual(v["p1hPosition"]["asia"]["label"]["x1"], 266, places=6,
                               msg="the pane's edge less 2 px, overhanging a 5 px box")
        # Title boxes over and under a 4 px box: the word would touch one.
        for name in ("d4hFull", "p4hFull"):
            self.assertNotIn("label", v[name]["asia"], name)
        # Without the title rows the whole lane stays closed: no label,
        # never the old one 18 or 64 px off the box.
        for name in ("d1hWholeLane", "p1hWholeLane"):
            self.assertIsNone(v[name]["titles"])
            self.assertNotIn("label", v[name]["asia"], name)

    def test_the_asia_label_never_slides_off_its_box_onto_candles(self):
        near = self.out["asiaNear"]
        a = near["free"]["asia"]
        label = a["label"]
        self.assertLessEqual(label["x1"], a["x0"], "left of the box")
        self.assertLessEqual(a["x0"] - label["x1"], 8, "LV.ASIA_NEAR")
        for t in near["free"]["titles"]:
            self.assertFalse(_meets(label, t), t)
        self.assertNotIn("label", near["candles"]["asia"], "off the box over candles: none")
        placed = dropped = 0
        wall = self.out["asiaSweepWall"]
        for case in self.out["asiaSweep"]:
            label = case["label"]
            if label is None:
                dropped += 1
                continue
            placed += 1
            where = (case["x0"], case["x1"], case["rows"], case["walled"], case["legacy"])
            off = max(0, case["x0"] - label["x1"], label["x0"] - case["x1"])
            self.assertLessEqual(off, 8, where)
            if off and case["walled"]:
                self.assertFalse([c for c in wall if _meets(label, c)], where)
            self.assertGreaterEqual(label["x0"], 0, where)
            self.assertLessEqual(label["x1"], 740, where)
            if case["legacy"] and case["rows"]:
                self.assertLessEqual(label["x1"], 740 - 80, where)
            for t in case["titles"] or []:
                self.assertFalse(_meets(label, t), where)
        self.assertGreater(placed, 100)
        self.assertGreater(dropped, 20)

    def test_a_role_tries_its_stub_at_its_origin_before_the_left_edge(self):
        case = self.out["stubFirst"]
        hunt = [c for c in case["g"]["chips"] if c["role"] == "hunt"][0]
        self.assertEqual(hunt["text"], "①HUNT")
        self.assertAlmostEqual(hunt["x0"], case["x0"] + 8, places=6)
        self.assertFalse(hunt["cross"])
        self.assertFalse(_meets(hunt, case["block"]))

    def test_no_chip_under_the_crosshair_legend(self):
        o = self.out["overlay"]
        self.assertTrue([c for c in o["bare"]["chips"] if _meets(c, o["box"])],
                        "without the keep-out a chip sits where the legend shows")
        self.assertEqual(o["g"]["keep"]["overlays"], [o["box"]])
        for c in o["g"]["chips"]:
            self.assertFalse(_meets(c, o["box"]), c)
        self.assertEqual(sorted(c["role"] for c in o["g"]["chips"] if c["role"]), ["draw", "hunt"])


    # ── The review fixes (2026-10-08) ──────────────────────────────────────

    def test_hovering_a_level_never_moves_a_chip_from_under_the_pointer(self):
        """Promoted to the head of the order, a hovered chip that held a
        fallback slot jumped to its preferred one: the pointer was then
        over nothing (or another level), the next move dropped the hover,
        the chip jumped back, and the card and the glow flickered on every
        1 px move. Every point a level is hit at hits the SAME level once
        it is hovered, and no chip moves when its level is hovered."""
        f = self.out["flicker"]
        cases = [("fix", f["fix"]), ("phone", f["phone"]), ("crowd", f["crowd"]),
                 ("crowdPhone", f["crowdPhone"]), ("crowdMoney", f["crowdMoney"])]
        cases += [("sweep%d" % i, c) for i, c in enumerate(f["sweep"])]
        probes = 0
        for where, c in cases:
            self.assertEqual(c["moved"], [], where)
            self.assertEqual(c["nUnstable"], 0, (where, c["unstable"]))
            self.assertGreater(c["chips"], 0, where)
            probes += c["probes"]
        self.assertEqual(f["crowd"]["chips"], 8, "the crowded scene fills the desktop cap")
        self.assertGreater(probes, 100000)
        # A hovered plain tick still gets its chip, forced in after the rest.
        bare, hot = self.out["hotTick"]["bare"]["chips"], self.out["hotTick"]["hot"]["chips"]
        self.assertNotIn("sv-lvl-swing-1.07676000000", [c["id"] for c in bare])
        self.assertEqual(hot[-1]["id"], "sv-lvl-swing-1.07676000000")
        self.assertEqual(hot[-1]["text"], "LL  1.07676")
        strip = lambda cs: [(c["id"], c["x0"], c["y0"], c["text"]) for c in cs]
        self.assertEqual(strip(hot[:-1]), strip(bare))

    def test_the_hunt_and_the_draw_on_one_pool_are_both_named(self):
        same = self.out["same"]
        self.assertEqual(same["roles"], [["sv-lvl-pool-1.08226000000", "hunt", "draw",
                                          "the bias is short at 0.70"]])
        self.assertEqual(same["chip"], "EQL ×2 · ① HUNT ② DRAW  1.08226")
        self.assertEqual(same["phone"], "EQL×2 ①HUNT②DRAW")
        self.assertEqual(same["keyBelow"]["text"], "▼ ① HUNT ② DRAW 1.08226 EQL×2 · 2.05 ATR")
        self.assertEqual(same["keyPhone"]["text"], "▼ ① HUNT ② DRAW 1.08226 · 2.05 ATR")
        self.assertEqual(same["keyBelow"]["why"], "the longs' stops · the bias is short at 0.70")
        self.assertIsNone(same["keyAbove"]["role"], "no role over the mark: the nearest pool")
        self.assertIn("The hunt runs here first — the longs&#39; stops", same["card"])
        self.assertIn("The draw after the hunt — the bias is short at 0.70", same["card"])
        self.assertIn("<dt>Hunt zone</dt>", same["card"])
        chips = {c["text"]: c for c in same["fix"]["chips"]}
        self.assertIn("EQL ×2 · ① HUNT ② DRAW  1.08226", chips)
        self.assertEqual(chips["EQL ×2 · ① HUNT ② DRAW  1.08226"]["role2"], "draw")
        self.assertIn("②DRAW", [c["text"] for c in same["narrow"]["chips"] if c["role"]][0])
        below = [e for e in same["offPane"]["edges"] if e["side"] == "below"][0]
        self.assertTrue(below["text"].startswith("▼ ① HUNT ② DRAW 1.08226"), below["text"])
        self.assertEqual(below["roles"], ["hunt", "draw"])
        self.assertEqual([x["text"] for x in same["facts"]],
                         ["TP at the draw: the equal lows pool 1.08226"])
        self.assertIsNotNone(same["hatch"], "the position's stop in its zone still hatches it")

    def test_an_off_pane_count_never_lands_blind_under_the_page_boxes(self):
        """A 1014 px pane whose top band is all crosshair legend and
        countdown: the count went under the countdown, over the TP line,
        placed with no check at all. It now takes a row under the boxes;
        with no slot anywhere none is placed and the key names the role."""
        case = self.out["edgeUnder"]
        top = [e for e in case["g"]["edges"] if e["side"] == "above"]
        self.assertEqual(len(top), 1)
        e = top[0]
        self.assertEqual(e["text"], "▲ ② DRAW 1.08954 · +2")
        for b in case["overlays"]:
            self.assertFalse(_meets(e, b), b)
        for y in case["rows"]:
            self.assertFalse(e["y0"] - 2 <= y <= e["y1"] + 2, y)
        self.assertGreaterEqual(e["y0"], 34)
        none = self.out["edgeNone"]
        self.assertEqual(none["edges"], [])
        self.assertIn("draw", none["unplaced"])

    def test_the_asia_label_never_crosses_a_money_row(self):
        a = self.out["asiaRows"]["asia"]
        self.assertNotIn("label", a, "the entry over the box and the SL under it: no label")
        crossed = 0
        for case in self.out["asiaSweep"]:
            label = case["label"]
            if label is None:
                continue
            for y in case["ys"]:
                if label["y0"] - 2 <= y <= label["y1"] + 2:
                    crossed += 1
        self.assertEqual(crossed, 0)

    def test_a_round_number_is_quiet_only_while_its_pool_is_drawn(self):
        rounds = sorted(c["text"] for c in self.out["noPools"]["chips"] if c["lv"] == "round")
        self.assertIn("1.08000", rounds, "its pool hidden by the Pools switch: the round names itself")
        self.assertNotIn("1.09000", rounds, "the DRAW (a role) is still drawn and carries its ◎")
        self.assertEqual([c["text"] for c in self.out["fix"]["chips"] if c["lv"] == "round"],
                         ["1.08500"])
        # Scrolled back past the DRAW's band: 1.09000 names itself.
        past = sorted(c["text"] for c in self.out["past"]["chips"] if c["lv"] == "round")
        self.assertIn("1.09000", past)

    def test_a_level_formed_after_the_visible_range_draws_nothing(self):
        """Scrolled back so the pane ends days ago: a level that formed
        later drew a zero-width band at the right edge and kept a chip
        (and a hover target) floating over nothing."""
        g = self.out["past"]
        self.assertEqual(self._ids(g["bands"]), ["sv-lvl-pool-1.08001000000", "sv-lvl-pool-1.09200000000"])
        self.assertEqual(g["rays"], [])
        self.assertEqual(g["ticks"], [])
        ids = {c["id"] for c in g["chips"]}
        for gone in ("sv-lvl-pool-1.08226000000", "sv-lvl-pool-1.08954000000",
                     "sv-lvl-recent-1.08775000000", "sv-lvl-recent-1.08288000000"):
            self.assertNotIn(gone, ids)
        for b in g["bands"]:
            self.assertLess(b["x0"], 740)
        self.assertEqual(g["count"]["shown"], 5, "two pools and three rounds")
        self.assertEqual(sorted(g["unplaced"]), ["draw", "hunt"], "the key names them")
        self.assertIsNone(g["hatch"])

    def _assert_off_the_neighbours(self, g, where):
        """No chip meets another level's band, touch dot or ray. A role's
        chip may graze one by under LV.GRAZE (1 px): the 4h HUNT chip, 0.3
        px into the EQL 1.08001 band's top, was sent 850 px to the left edge."""
        dot = 2.5
        for c in g["chips"]:
            gap = -1 if c["role"] else 0
            for b in g["bands"]:
                if b["id"] != c["id"]:
                    self.assertFalse(_meets(c, b, gap, gap), (where, c["text"], b["id"]))
            for d in g["dots"]:
                if d["id"] != c["id"]:
                    box = {"x0": d["x"] - dot, "x1": d["x"] + dot, "y0": d["y"] - dot, "y1": d["y"] + dot}
                    self.assertFalse(_meets(c, box, gap, gap), (where, c["text"], d["id"]))
            for r in g["rays"]:
                if r["id"] != c["id"]:
                    ray = {"x0": r["x0"], "x1": r["x1"], "y0": r["y"] - 0.5, "y1": r["y"] + 0.5}
                    self.assertFalse(_meets(c, ray, gap, gap), (where, c["text"], r["id"]))

    def test_role_chips_keep_off_the_neighbouring_pools(self):
        """Phone 4h, bands 4 px apart: '②DRAW' printed on the EQH 1.09200
        band and hid its touch dot, '①HUNT' on the EQL 1.08001 band. A
        chip now keeps off every other level's shapes."""
        p4 = self.out["phone4"]
        lev = p4["levels"]
        eqh = [b for b in lev["bands"] if b["id"] == "sv-lvl-pool-1.09200000000"][0]
        draw = [b for b in lev["bands"] if b["role"] == "draw"][0]
        self.assertAlmostEqual(eqh["y0"], 123.5, delta=0.6)
        self.assertAlmostEqual(draw["y0"], 138, delta=0.6)
        for key in ("levels", "position", "full", "desk"):
            g = p4[key]
            self._assert_off_the_neighbours(g, key)
            named = {c["role"] for c in g["chips"] if c["role"]}
            for e in g["edges"]:
                named.update(e["roles"])
            named.update(g["unplaced"])
            self.assertEqual(named, {"hunt", "draw"}, key)
        for g, where in [(self.out["fix"], "fix"), (self.out["fixPhone"], "phone"),
                         (self.out["crowd"]["g"], "crowd"), (self.out["crowdPhone"]["g"], "crowdPhone")]:
            self._assert_off_the_neighbours(g, where)

    def test_a_chip_never_ends_left_of_its_own_shape(self):
        """'LAST LOW 1.08288' sat at x 4, 900 px from its ray and 2 px over
        the SL, and read as the SL's label. A non-role chip sits on its own
        band or ray (or a clipped shape's left edge), or is dropped."""
        scenes = [("fix", self.out["fix"]), ("phone", self.out["fixPhone"]),
                  ("candles", self.out["candles"]["g"]), ("showAll", self.out["showAll"])]
        scenes += [(str((c["scale"], c["shift"], c["phone"])), c["g"]) for c in self.out["sweep"]]
        for where, g in scenes:
            shapes = {b["id"]: b["x0"] for b in g["bands"]}
            shapes.update({r["id"]: r["x0"] for r in g["rays"]})
            for c in g["chips"]:
                if c["role"] or c["lv"] == "round" or c["id"] not in shapes:
                    continue
                self.assertGreaterEqual(c["x1"], shapes[c["id"]], (where, c["text"]))

    def test_the_tp_in_the_draws_zone_names_the_draw(self):
        self.assertEqual([f["text"] for f in self.out["tpDraw"]],
                         ["TP at the draw: the equal highs pool 1.08954"])

    def test_the_chip_hit_by_its_exact_box(self):
        h = self.out["hitChip"]
        self.assertEqual(h["on"], {"id": "sv-lvl-pool-1.08226000000", "item": True})
        self.assertIsNone(h["off"])
        self.assertIsNone(h["none"])

    # ── The acceptance fixes, round 2 (2026-10-08) ─────────────────────

    RAYS = {"sv-lvl-recent-1.08775000000": ("LAST HIGH  1.08775", "LAST H"),
            "sv-lvl-recent-1.08288000000": ("LAST LOW  1.08288", "LAST L")}

    def _assert_view(self, name, v):
        """What every fixture view must hold: the roles named at full
        strength, every chip off the page's boxes and the neighbours'
        shapes, the non-ray chips off the newest candles, the cap kept,
        and the ASIA label (if any) on its box and clear of every chip."""
        g = v["g"]
        self.assertEqual(sorted(c["role"] for c in g["chips"] if c["role"]), ["draw", "hunt"], name)
        self.assertEqual(g["unplaced"], [], name)
        self._assert_off_the_neighbours(g, name)
        self._assert_off_the_roles(g, name)
        self.assertLessEqual(len(g["chips"]), 4 if name.startswith("phone") else 8, name)
        for c in g["chips"]:
            for b in g["keep"]["overlays"]:
                self.assertFalse(_meets(c, b), (name, c["text"]))
            self.assertFalse(c["cross"], (name, c["text"]))
            if c["id"] not in self.RAYS and not c["role"]:
                for b in v["candles"]:
                    self.assertFalse(_meets(c, b), (name, c["text"]))
        a = g["asia"]
        if a.get("label"):
            self.assertEqual(max(0, a["x0"] - a["label"]["x1"], a["label"]["x0"] - a["x1"]), 0, name)
            for c in g["chips"]:
                self.assertFalse(_meets(c, a["label"], 4, 1), (name, c["text"]))
        return g

    def test_the_ray_chips_sit_on_their_rays_in_the_fixture_views(self):
        """The harness's levels views (§3.13): the latest swing high and
        low sit inside the newest 30 bars on every frame, and the review's
        candle keep-out left both rays anonymous in every default view.
        Now each ray chip sits on its own ray (over the candles when no
        clear slot exists), with its full words on a desktop and its
        short words on a phone, where it makes the fourth chip."""
        rays = sorted(self.RAYS)
        for name in ("desk1h", "desk4h", "phone1h"):
            v = self.out["views"][name]
            g = self._assert_view(name, v)
            self.assertEqual(sorted(r["id"] for r in g["rays"]), rays, name)
            by = {r["id"]: r for r in g["rays"]}
            on = {c["id"]: c for c in g["chips"] if c["id"] in by}
            self.assertEqual(sorted(on), rays, (name, [c["text"] for c in g["chips"]]))
            phone = name.startswith("phone")
            for cid, c in on.items():
                self._assert_on_ray(c, by[cid], name)
                self.assertEqual(c["text"], self.RAYS[cid][1 if phone else 0], name)
            if phone:
                self.assertEqual(len(g["chips"]), 4, (name, [c["text"] for c in g["chips"]]))
        self.assertEqual(len(self.out["views"]["desk1h"]["g"]["chips"]), 7, "§3.13: 7 chips on 1h desktop")

    def test_the_phone_4h_view_has_no_honest_slot_for_a_ray_chip(self):
        """Phone 4h: the LAST LOW tick prints 3 px from the pane's right
        edge, so no chip can end at or right of it inside the 4 px margin
        (a chip never ends left of its own shape), and the LAST HIGH ray
        has the DRAW chip 4 px over it and the last price's row 13 px
        under it: no 14 px row. Both stay plain rays (the key says Swings
        2, a tap opens the card); the roles sit at their origins and the
        two slots left go to the nearest pool and the round number."""
        v = self.out["views"]["phone4h"]
        g = self._assert_view("phone4h", v)
        by = {r["id"]: r for r in g["rays"]}
        self.assertGreater(by["sv-lvl-recent-1.08288000000"]["x0"], v["W"] - 4, "the tick inside the margin")
        self.assertEqual([c["id"] for c in g["chips"] if c["id"] in by], [])
        self.assertEqual([c["text"] for c in g["chips"]],
                         ["EQL×2 ①HUNT", "EQH×2 ◎ ②DRAW", "1.08500", "EQL×2 ◎"])
        for c in g["chips"]:
            if c["role"]:
                self.assertGreater(c["x0"], v["W"] / 2, c["text"])

    def test_the_role_chips_sit_at_their_origins_in_the_4h_view(self):
        """Desktop 4h: the HUNT chip's outside slot grazed the EQL 1.08001
        band's top (0.3 px) and the DRAW chip's sat 1 px under the EQH
        1.09200 band, so both went to the left edge, 850 px from their
        bands. A role's chip may touch a neighbour's band edge: both sit
        beside their bands, their full words, clamped at the right edge."""
        v = self.out["views"]["desk4h"]
        g, W = v["g"], v["W"]
        bands = {b["role"]: b for b in g["bands"] if b["role"]}
        for c in g["chips"]:
            if not c["role"]:
                continue
            band = bands[c["role"]]
            self.assertAlmostEqual(c["x1"], W - 4, places=6, msg=c["text"])
            self.assertGreater(c["x0"], W - 200, c["text"])
            self.assertGreater(c["x1"], band["x0"], "over its own band")
            self.assertNotIn(c["text"], ("①HUNT", "②DRAW"), "the full words, not the stub")
            if c["role"] == "hunt":
                self.assertTrue(band["y1"] + 1 - 3 <= c["y0"] <= band["y1"] + 1, (c["y0"], band))
            else:
                self.assertTrue(band["y0"] - 1 <= c["y1"] <= band["y0"] - 1 + 3, (c["y1"], band))

    def test_a_grazing_band_edge_does_not_evict_an_origin_slot(self):
        """A neighbour's band top 0.5 px into the HUNT chip's outside slot
        is no clash (LV.GRAZE); 2.5 px in, the slot is nudged into the HUNT
        band's edge (LV.NUDGE); 6 px in, the next slot at the origin."""
        cases = self.out["graze"]
        for name, case in cases.items():
            chip, band, nb = case["chip"], case["band"], case["neighbour"]
            self.assertIsNotNone(chip, name)
            self.assertIsNotNone(nb, name)
            self.assertAlmostEqual(chip["x0"], band["x0"] + 8, places=6, msg=name)
            self.assertEqual(chip["text"], "EQL ×2 · ① HUNT  1.08226", name)
            self._assert_off_the_neighbours(case["g"], name)
        touch, nudge, nxt = cases["touch"], cases["nudge"], cases["next"]
        self.assertAlmostEqual(touch["chip"]["y0"], touch["out"], places=6, msg="the outside slot, grazing")
        self.assertLess(touch["neighbour"]["y0"], touch["chip"]["y1"], "it does overlap, under 1 px")
        self.assertAlmostEqual(nudge["chip"]["y0"], nudge["out"] - 2, places=6, msg="nudged 2 px into its band")
        self.assertLess(abs(nudge["chip"]["y1"] - nudge["neighbour"]["y0"]), 1)
        self.assertAlmostEqual(nxt["chip"]["y1"], nxt["band"]["y0"] - 1, places=6, msg="the inside slot")

    def test_a_ray_chip_falls_back_to_its_short_words_at_the_rays_start(self):
        """A marker box over the left part of the full chip's only slots
        (the lane closed): 'LAST H' ending at the lane, on its ray."""
        case = self.out["rayShort"]
        g = case["g"]
        texts = [c["text"] for c in g["chips"]]
        self.assertIn("LAST H", texts)
        self.assertNotIn("LAST HIGH  1.08775", texts)
        short = [c for c in g["chips"] if c["text"] == "LAST H"][0]
        ray = [r for r in g["rays"] if r["id"] == "sv-lvl-recent-1.08775000000"][0]
        self._assert_on_ray(short, ray, "short")
        self.assertAlmostEqual(short["x1"], case["laneX"] - 4, places=6)
        self.assertFalse(_meets(short, case["box"]))
        self.assertIn("LAST LOW  1.08288", texts, "the other ray keeps its full words")


# ═══ The widget's own script: the parts a fake chart cannot prove ═════════

class TheWiringTests(SimpleTestCase):
    """Pins on the main script and the stylesheet (§6.3 C-1 to C-8): the
    layer's paint passes, its lifecycle around a series switch, the
    volume's axis label, the key's markup, the themed CSS, the signal and
    H-line inks, the tokens in both themes, and the cached palette."""

    def setUp(self):
        self.src = widget_source().replace("\r\n", "\n")

    def _fn(self, name):
        seg = self.src.split("function %s(" % name)[1]
        end = seg.find("\n    function ")
        return seg[:end] if end > 0 else seg

    def _method(self, name):
        i = self.src.index("LevelLayer.prototype.%s = function" % name)
        return self.src[i:self.src.index("\n    };", i)]

    # C-1
    def test_the_layer_paints_shapes_under_and_chips_over(self):
        """zOrder 'normal' runs after the grid; drawBackground for every
        source comes before draw for any, so the shapes sit under the
        candles and every price line. The chips are a second view, zOrder
        'top', drawn after every series (in 'normal' they painted inside
        the candles' source, under the volume histogram and the indicator
        lines created after it). 'bottom' would paint under the grid. No
        hitTest: a normal-layer hit would beat the series markers and
        steal the dots' object ids."""
        i = self.src.index("function LevelLayer() {")
        ctor = self.src[i:self.src.index("LevelLayer.prototype.attached", i)]
        normal = ctor.index("zOrder: function () { return 'normal'; }")
        top = ctor.index("zOrder: function () { return 'top'; }")
        self.assertLess(normal, top)
        back = ctor.index("drawBackground: function (t) { self.paintBack(t); }")
        chips = ctor.index("draw: function (t) { self.paintChips(t); }")
        self.assertLess(normal, back)
        self.assertLess(back, top, "the shapes in the normal view")
        self.assertLess(top, chips, "the chips in the top view")
        self.assertEqual(ctor.count("self.paintChips("), 1)
        self.assertEqual(ctor.count("self.paintBack("), 1)
        layer = self.src[i:self.src.index("function applyLevels() {", i)]
        for absent in ("hitTest", "autoscaleInfo", "'bottom'", "priceAxisViews",
                       "timeAxisViews", "createPriceLine"):
            self.assertNotIn(absent, layer, absent)
        self.assertIn("LevelLayer.prototype.paneViews = function () { return this.views; };",
                      self.src, "the same array on every call")
        self.assertIn("typeof mainSeries.attachPrimitive !== 'function'", self.src)
        self.assertIn("mainSeries.attachPrimitive(lvlLayer)", self._fn("ensureLevelLayer"))

    # C-2
    def test_add_series_detaches_then_reattaches(self):
        add = self._fn("addSeries")
        self.assertLess(add.index("mainSeries.detachPrimitive(lvlLayer)"),
                        add.index("chart.removeSeries(mainSeries)"))
        died = self.src.index("posLines = []; /* they died with the series */")
        self.assertIn("lvlLayer = null;", self.src[died:died + 160])
        self.assertIn("amdLines = [];", self.src[died:died + 160])
        self.assertEqual(add.count("priceFormat: seriesPriceFormat(lastBars),"), 3)
        self.assertEqual(add.count("priceLineStyle: LightweightCharts.LineStyle.Dotted,"), 3)
        self.assertIn("lvlPalette = getThemeColors();", add)
        # The axis follows the bars on every load, not only the first.
        load = self.src[self.src.index("mainSeries.setData(seriesData(bars));"):][:200]
        self.assertIn("mainSeries.applyOptions({ priceFormat: seriesPriceFormat(bars) })", load)
        dec = self._fn("axisDecimals")
        self.assertIn("if (DECIMALS !== null) return DECIMALS;", dec)
        self.assertIn("Math.min(8, m[1].length)", dec)

    # C-3
    def test_volume_prints_no_last_value(self):
        i = self.src.index("volumeSeries = chart.addHistogramSeries({")
        block = self.src[i:self.src.index("});", i)]
        self.assertIn("lastValueVisible: false, priceLineVisible: false,", block)

    # C-4
    def test_the_key_markup(self):
        html = widget()
        sig, lvl, pos = (html.index('id="t-%s-legend"' % k) for k in ("sig", "lvl", "pos"))
        self.assertLess(sig, lvl)
        self.assertLess(lvl, pos)
        tag = re.search(r'<div class="sv-lvl-legend"[^>]*>', html).group(0)
        self.assertIn(' role="group"', tag)
        self.assertIn(" hidden", tag, "hidden until the first level data")
        block = html[lvl:html.index("</div>", lvl)]
        keys = re.findall(r'data-lvl="([a-z]+)"', block)
        self.assertEqual(keys, ["levels", "below", "above", "pool", "swing", "asia",
                                "round", "all"])
        for button in re.findall(r"<button[^>]*>", block):
            self.assertIn('aria-pressed="', button)
            self.assertIn('type="button"', button)
        self.assertIn("Levels (4h):", block)
        self.assertIn("activeInds.levels === undefined) activeInds.levels = true", html)
        self.assertIn("var lvlLegendEl = document.getElementById(CHART_ID + '-lvl-legend');",
                      self.src)

    # C-5
    def test_new_css_has_no_bare_hex(self):
        css = self.src.split("<style>")[1].split("</style>")[0]
        css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
        own = re.compile(r"\.sv-lvl|\.sv-sig-card--(pool|swing|asia|round)\b")
        offenders, seen = [], 0
        for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
            if not own.search(selector):
                continue
            seen += 1
            for hit in HEX.findall(_strip_vars(body)):
                offenders.append((selector.strip()[:50], hit))
        self.assertEqual(offenders, [])
        self.assertGreaterEqual(seen, 25, "the rules were found")
        self.assertNotIn("var(--bg-elevated", css)

    def test_only_the_kind_switches_strike_through(self):
        """The AFTER shots: the answer chips start aria-pressed="false" (not
        focused), so the key's strike and dim made '▼ ① HUNT 1.08226' read
        as cancelled, and Show all too. Strike and dim are the kind
        switches' 'hidden'; the answer and Show all take neither."""
        css = self.src.split("<style>")[1].split("</style>")[0]
        css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
        rules = [(sel.strip(), body.strip()) for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css)]

        def rule(selector_part):
            got = [(i, s, b) for i, (s, b) in enumerate(rules) if selector_part in s]
            self.assertTrue(got, selector_part)
            return got[-1]
        strike_i, _s, strike = rule('.sv-lvl-key[aria-pressed="false"]')
        self.assertIn("line-through", strike)
        plain_i, sel, plain = rule('.sv-lvl-key--answer[aria-pressed="false"]')
        self.assertIn('.sv-lvl-key--all[aria-pressed="false"]', sel)
        self.assertIn("text-decoration: none", plain)
        self.assertIn("opacity: 1", plain)
        self.assertGreater(plain_i, strike_i, "later in the sheet, so it wins at equal weight")
        _i, _s, sticky = rule('.sv-lvl-key--answer[aria-pressed="true"]')
        self.assertIn("border-color: currentColor", sticky)
        _i, _s, on = rule('.sv-lvl-key--all[aria-pressed="true"]')
        self.assertIn("border-color: currentColor", on)

    def test_keyboard_focus_shows_on_a_pressed_chip(self):
        """outline: none took the platform's focus ring, and a pressed
        chip's currentColor border hid the border-colour cue: a focused
        pressed chip looked exactly like an unfocused one (WCAG 2.4.7)."""
        css = self.src.split("<style>")[1].split("</style>")[0]
        css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
        rules = [(sel.strip(), body.strip()) for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css)]
        for sel, body in rules:
            if ".sv-lvl" in sel and "focus-visible" in sel:
                self.assertNotIn("outline: none", body, sel)
        idx = {sel: i for i, (sel, _b) in enumerate(rules)}
        ring = ".sv-lvl-legend .sv-lvl-key:focus-visible"
        self.assertIn(ring, idx)
        body = rules[idx[ring]][1]
        self.assertIn("outline: 2px solid var(--accent, #00e868)", body)
        self.assertIn("outline-offset: 2px", body)
        for pressed in ('.sv-lvl-key--answer[aria-pressed="true"]', '.sv-lvl-key--all[aria-pressed="true"]'):
            self.assertLess(idx[pressed], idx[ring], pressed)

    # C-6
    def test_signal_and_hline_inks(self):
        sig = self._fn("drawSignalLevels")
        self.assertIn("[['entry', 'Entry', c.ink]", sig)
        self.assertIn("axisLabelColor: c.bg, axisLabelTextColor: lv[2],", sig)
        self.assertIn("LightweightCharts.LineStyle.Dashed", sig)
        self.assertNotIn("c.gold", sig)
        hl = self._fn("hlineOptions")
        self.assertIn("color: c.alpha(c.neutral, 0.9)", hl)
        self.assertIn("axisLabelColor: c.bg, axisLabelTextColor: c.neutral", hl)
        self.assertIn("title: 'H'", hl)
        # both H-line paths: the click and the restore after a load
        self.assertEqual(self.src.count("createPriceLine(hlineOptions(price, c))"), 2)
        self.assertIn("ink:          token('--text-primary', isDark ? '#daf0e6' : '#1a2a1a'),",
                      self.src)
        self.assertIn("swing:        token('--lvl-swing'", self.src)
        self.assertIn("session:      token('--lvl-session'", self.src)
        # The signal card's entry price is never gold either.
        self.assertIn(".sv-sig-level--entry > b { color: var(--text-primary, #daf0e6); }",
                      self.src)

    # C-7
    def test_tokens_exist_in_both_themes(self):
        css = (Path(settings.BASE_DIR) / "static" / "css" / "sauron.css").read_text(
            encoding="utf-8")
        roots = re.findall(r"(?:^|\n)\s*:root\s*\{([^}]*)\}", css)
        light = re.findall(r"(?:^|\n)\s*body\.light-mode\s*\{([^}]*)\}", css)
        self.assertTrue(roots and light)
        for token in ("--lvl-swing:", "--lvl-session:"):
            self.assertTrue(any(token in b for b in roots), token)
            self.assertTrue(any(token in b for b in light), token)
        self.assertTrue(any("--lvl-swing: #1f6fb2;" in b for b in light))
        self.assertTrue(any("--lvl-session: #a878f0;" in b for b in roots))

    # C-8
    def test_the_palette_is_cached(self):
        """LWC repaints the pane on every hover move over a hittable item:
        the paint reads the palette cached once per data paint."""
        self.assertIn("lvlPalette = getThemeColors();", self._fn("applyLevels"))
        for name in ("paintBack", "paintChips", "computeGeom"):
            body = self._method(name)
            self.assertNotIn("getThemeColors(", body, name)
            self.assertIn("levelPalette()", body, name)
        self.assertIn("function levelPalette() { return lvlPalette || (lvlPalette = getThemeColors()); }",
                      self.src)
        i = self.src.index("new MutationObserver(")
        self.assertIn("lvlPalette = null;", self.src[i:i + 400])
        self.assertIn("attributeFilter: ['class']", self.src[i:i + 500])
        # The count in the key is written only when it changes.
        self.assertIn("if (said === lvlCountSaid) return;", self._fn("updateLevelCount"))
