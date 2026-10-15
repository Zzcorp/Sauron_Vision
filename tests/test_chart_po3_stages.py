"""The Power of Three's three stages on the chart (2026-10-08).

The operator, after the levels redesign (PR51): "I only have the Asia
session noted on the chart, not the 3 stages of manipulation, accumulation
and distribution."

The day's three stages are drawn in the session violet, and each is named
by its letter on the mark that proves it:
  A  the Asian box, labelled `A · ASIA`;
  M  London's window as a faint time band, a diamond just beyond the wick
     that ran the Asian edge (`M · SWEEP  1.08288`, or `M · RUN` while the
     run holds) and London's Judas swing as a thin line;
  D  New York's window as a faint time band and a vertical arrow at the bar
     that closed back inside, from the swept edge to the far one (`D ▲`,
     `D ▲ · ② DRAW` when the map's draw points the same way).
A stage that has not happened draws nothing; an unclear day draws both
runs and no direction. The key's `Power of Three` switch names the phase.
Display only: nothing that trades reads any of it (tests/test_power_of_three
pins the server side, TheMapTests M1 to M3).

Three classes:
  ThePo3LanguageTests  the pure window.svLevels / svHoverCards under node:
                       what each phase draws, the fold of the run into the
                       LAST LOW chip, the M and D labels on their marks under
                       PR51's keep-outs, hover stability, dims, the hit test,
                       the key's words, the cards, the arrow's floor, the
                       draw's agreement;
  ThePo3WidgetTests    the widget's real script against the fake chart of
                       tests/test_chart_levels_widget.py (WIDGET_PRELUDE +
                       LEVELS_PATCH, unedited): the layer carries the stages
                       and adds no price line, shapes under and labels over,
                       4h frames, the switch, the key, the cards, an old
                       reply, a type switch, no primitives, a pin;
  ThePo3WiringTests    pins on the markup, the CSS and the server's wiring.

Run with:  python manage.py test tests.test_chart_po3_stages
"""
import copy
import inspect
import math
import re
import unittest
from datetime import datetime, timedelta, timezone as dt_timezone

from django.test import SimpleTestCase

from tests.test_chart_levels_language import (
    FIXTURE_ROWS, MARKERS, NOW, PATH, PINNED, POSITION, _meets, _pool)
from tests.test_chart_levels_widget import (
    LEVELS_PATCH, PREF_KEY, _levels_payload, y as y_of)
from tests.test_chart_signal_markers import (
    HEX, NODE, WIDGET_PRELUDE, _blocks, _node, _payload, _strip_vars, widget, widget_source)

HUNT_ID = "sv-lvl-pool-1.08226000000"
LOW_ID = "sv-lvl-recent-1.08288000000"
STAGE_IDS = ["sv-po3-london", "sv-po3-ny", "sv-po3-m-low", "sv-po3-judas", "sv-po3-d"]
CHIP_H, ROW_CLEAR, ROLE_GAP, GAP_X, GAP_Y = 14, 2, 2, 4, 1


def _utc(*a):
    return int(datetime(*a, tzinfo=dt_timezone.utc).timestamp())


#: The harness day (2026-10-07, EURUSD): London ran the Asian lows to
#: 1.08288 on the 08:00 UTC bar and the 12:00 bar closed back inside at
#: 1.08510. The server's shape (bot_program/power_of_three.read_day).
STAGES = {"date": "2026-10-07", "bar": 3600,
          "london": {"opened": 1791352800, "closed": 1791363600, "state": "closed",
                     "ny": "02:00–05:00"},
          "new_york": {"opened": 1791376200, "closed": 1791403200, "state": "open",
                       "ny": "08:30–16:00"},
          "sweeps": [{"side": "low", "edge": 1.08441, "price": 1.08288, "at": 1791360000,
                      "ny": "04:00", "session": "london", "back_at": 1791374400,
                      "back_close_at": 1791378000, "back_price": 1.0851, "back_ny": "08:00"}],
          "judas": None}
JUDAS = {"direction": "LONG", "open": 1.0852, "open_at": 1791352800, "open_ny": "02:00",
         "extreme": 1.08288, "extreme_at": 1791360000, "extreme_ny": "04:00",
         "words": "London opened 1.0852, faked to 1.0829 early in the window, reversed back "
                  "through the open."}
WORDS = ("Power of Three (the ny am session, the day's distribution): Asia "
         "consolidated 1.08441–1.08608; the lows of the Asian range were run.")
#: The old `judas` key's clause, as words_for appends it: the London of the
#: Asian session's own New York date (F1, decision D1), left unchanged.
OLD_JUDAS = " London's Judas swing: opened 100, faked to 99, reversed (long)."
#: Two pools nearer the mark than the LAST LOW ray: on a phone (four chips)
#: they take its chip, so a hover on the ray forces it in late.
LATE_ROWS = FIXTURE_ROWS + [_pool(1.08690, "above", 0.9, [(1.08680, 2.0), (1.08700, 1.5)]),
                            _pool(1.08850, "above", 1.9, [(1.08840, 2.5), (1.08860, 1.2)])]


def toY(p):
    """The pure tests' scale: 1 pip is 2 px, 1.0855 at y 200."""
    return 200 - (p - 1.0855) * 20000


PO3_PURE_RUN = r"""
const fs = require('fs');
const M = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
var L = window.svLevels, HC = window.svHoverCards, LV = L.LV;
var out = {};
var T0 = M.now - 240 * 3600;
function toYs(scale, shift) { return function (p) { return 200 + (shift || 0) - (p - 1.0855) * scale; }; }
var toY = toYs(20000, 0);
function toXw(W) { return function (t) { return t < T0 ? -1 : (t - T0) / 3600 * (W - 68) / 240; }; }
function fmt(v) { return Number(v).toFixed(5); }
function measure(t) { return String(t).length * LV.CHAR_W; }
function env(o) {
    o = o || {};
    var W = o.width || 740, ty = o.toY || toY;
    var e = { toY: ty, toX: toXw(W), width: W, height: 384, theme: 'dark', phone: false,
              highTf: false, showAll: false, hidden: {}, hover: null, focus: null, pinned: false,
              mark: M.mark, money: [], labels: false, laneW: 80, hlines: [], lastY: ty(M.mark),
              boxes: [], asia: null, po3: null, measure: measure };
    for (var k in o) e[k] = o[k];
    return e;
}
function clone(x) { return JSON.parse(JSON.stringify(x)); }
function geo(g) { return clone(g); }
function mapWith(stages) { var m = { path: M.path }; if (stages) m.po3 = { stages: stages }; return m; }
var ITEMS = L.digest(M.rows, mapWith(M.stages), fmt);
var BARE = L.digest(M.rows, mapWith(null), fmt);
var UNC_STAGES = clone(M.stages);
UNC_STAGES.sweeps.push({ side: 'high', edge: 1.08608, price: 1.08650, at: M.stages.sweeps[0].at,
                         ny: '04:00', session: 'london', back_at: null, back_close_at: null,
                         back_price: null, back_ny: null });
var UNC_ITEMS = L.digest(M.rows, mapWith(UNC_STAGES), fmt);

/* env.po3 per state, the pixel x's given directly (W 740) */
var UP = { high: 1.08608, low: 1.08441 }, DOWN = { high: 1.08559, low: 1.08392 };
function box(a, x0, x1) { return { high: a.high, low: a.low, x0: x0 === undefined ? 470 : x0, x1: x1 === undefined ? 510 : x1 }; }
function run(side, price, edge, x, back) {
    return { side: side, price: price, edge: edge, x: x, tip: price, back: back, text: fmt(price) };
}
function po3(phase, o) {
    var p = { phase: phase, direction: null, london: { x0: 520, x1: 560 }, ny: { x0: 600, x1: 700 },
              sweeps: [], judas: null, ret: null, draw: null };
    for (var k in (o || {})) p[k] = o[k];
    return p;
}
var JUD = { x0: 522, open: 1.08500, x1: 545, extreme: 1.08288 };
var ACC = po3('accumulation');
var MAN = po3('manipulation', { sweeps: [run('low', 1.08288, 1.08441, 545, false)], judas: JUD });
var DIS = po3('distribution', { direction: 'up', sweeps: [run('low', 1.08288, 1.08441, 545, true)],
                               judas: JUD, ret: { x: 605, from: 1.08441, to: 1.08608 }, draw: 'agrees' });
var DISNO = clone(DIS); DISNO.draw = 'disagrees';
var DOWNP = po3('distribution', { direction: 'down', sweeps: [run('high', 1.08712, 1.08559, 545, true)],
                                 ret: { x: 605, from: 1.08559, to: 1.08392 }, draw: null });
var UNC = po3('unclear', { sweeps: [run('low', 1.08288, 1.08441, 545, true), run('high', 1.08650, 1.08608, 640, false)],
                           judas: JUD });

/* P1-P5 and P7: each state over the fixture's levels */
out.acc = geo(L.layout(ITEMS, env({ po3: ACC, asia: box(UP) })));
out.man = geo(L.layout(ITEMS, env({ po3: MAN, asia: box(UP) })));
out.dis = geo(L.layout(ITEMS, env({ po3: DIS, asia: box(UP) })));
out.down = geo(L.layout(L.digest(M.rows, mapWith(null), fmt), env({ po3: DOWNP, asia: box(DOWN) })));
out.unc = geo(L.layout(UNC_ITEMS, env({ po3: UNC, asia: box(UP) })));
/* a free pane: no level at all, so M is a label of its own */
out.free = geo(L.layout([], env({ po3: DIS, asia: box(UP) })));
out.freeNo = geo(L.layout([], env({ po3: DISNO, asia: box(UP) })));
out.freeDown = geo(L.layout([], env({ po3: DOWNP, asia: box(DOWN) })));
out.freeMan = geo(L.layout([], env({ po3: MAN, asia: box(UP) })));
/* P29: a manipulation day whose run came back once and left again: the
   server's back_at is set, the phase says the run holds */
out.manBack = geo(L.layout([], env({ po3: po3('manipulation', { sweeps: [run('low', 1.08288, 1.08441, 545, true)] }),
                                     asia: box(UP) })));
/* P6: no day */
out.none = geo(L.layout(ITEMS, env({ po3: null, asia: box(UP) })));
out.phaseNone = [L.phaseAnswer({ ok: false }), L.phaseAnswer(null), L.phaseAnswer({ ok: true, phase: 'unread' })];
/* P7: the fold, flagged by digest */
function brief(items) {
    return items.map(function (l) { return { id: l.id, price: l.price, lv: l.lv, sweep: l.sweep || null,
                                             hasSweepKey: Object.prototype.hasOwnProperty.call(l, 'sweep') }; });
}
out.items = brief(ITEMS);
out.bareItems = brief(BARE);
out.bareDigest = JSON.stringify(BARE) === JSON.stringify(L.digest(M.rows, { path: M.path }, fmt));
out.bare = geo(L.layout(BARE, env({ po3: null, asia: box(UP) })));
out.barePlain = geo(L.layout(BARE, env({ asia: box(UP) })));
/* P7b: the lane closed beside the ray's start, its diamond under the
   wick there (the harness's position zoom): neither M · SWEEP  1.08288
   nor M · SWEEP fits off the diamond, the letter does */
var TIGHT = clone(DIS); TIGHT.sweeps[0].x = 625;
out.foldTight = geo(L.layout(ITEMS, env({ po3: TIGHT, asia: box(UP), labels: true, laneW: 80,
                                          boxes: [{ x0: 530, x1: 634, y0: 230, y1: 252 }] })));
/* P8: a run at a price no level carries */
var LONE = po3('manipulation', { sweeps: [run('low', 1.08320, 1.08441, 400, false)] });
out.lone = geo(L.layout(ITEMS, env({ po3: LONE, asia: box(UP) })));
var LONE_HI = po3('manipulation', { sweeps: [run('high', 1.08700, 1.08608, 300, false)] });
out.loneHigh = geo(L.layout([], env({ po3: LONE_HI, asia: box(UP) })));

/* P9: every PR51 rule, many zooms and shifts, money, titles, markers, overlays, candles */
function money(ty, pos, pin) {
    var m = [];
    if (pos) {
        m.push({ price: pos.entry, y: ty(pos.entry), held: false, t: 'LONG 25000' });
        m.push({ price: pos.stop, y: ty(pos.stop), held: true, stop: true, t: 'SL' });
        m.push({ price: pos.tp, y: ty(pos.tp), held: true, t: 'TP' });
    }
    if (pin) [['entry', 'Entry'], ['stop', 'Stop'], ['target', 'Target']].forEach(function (k) {
        m.push({ price: pin[k[0]], y: ty(pin[k[0]]), held: false, t: k[1] });
    });
    return m;
}
function markerPoints(ty, W) {
    var tx = toXw(W);
    return M.markers.map(function (m) {
        return { x: tx(m.t), yHigh: ty(m.high), yLow: ty(m.low), position: m.position, size: m.size, text: m.text };
    });
}
function scaled(p, W) {                        /* the states' x's on a pane of width W */
    var f = W / 740, q = clone(p);
    if (q.london) q.london = { x0: q.london.x0 * f, x1: q.london.x1 * f };
    if (q.ny) q.ny = { x0: q.ny.x0 * f, x1: q.ny.x1 * f };
    q.sweeps.forEach(function (s) { s.x *= f; });
    if (q.judas) { q.judas.x0 *= f; q.judas.x1 *= f; }
    if (q.ret) q.ret.x *= f;
    return q;
}
function newest(ty, W) {                       /* the newest 30 candles, around the mark */
    var c = [], bar = (W - 68) / 240;
    for (var i = 0; i < 30; i++) {
        var x = W - 68 - (i + 0.5) * bar, mid = 1.0850 + 0.0012 * Math.sin(i * 0.7);
        c.push({ x0: x - bar / 2, x1: x + bar / 2, y0: ty(mid + 0.0005) - 1, y1: ty(mid - 0.0005) + 1 });
    }
    return c;
}
out.rules = [];
[20000, 12000, 30000].forEach(function (scale) {
    [0, -40, 40].forEach(function (shift) {
        [false, true].forEach(function (phone) {
          [true, false].forEach(function (withPos) {
            [DIS, DOWNP, MAN].forEach(function (state, si) {
                var W = phone ? 330 : 740, ty = toYs(scale, shift);
                var m = money(ty, withPos ? M.pos : null, M.pinned), hl = [ty(1.08700)], lastY = ty(M.mark);
                var boxes = L.markerBoxes(markerPoints(ty, W), phone ? 6 : 10, 10);
                var overlays = phone ? [{ x0: W - 140, x1: W - 6, y0: 0, y1: 34 }]
                                     : [{ x0: 0, x1: 416, y0: 0, y1: 34 }, { x0: W - 145, x1: W - 6, y0: 0, y1: 34 }];
                var titles = m.map(function (r) { return { y: r.y, w: measure(r.t) + 16 }; });
                var a = si === 1 ? DOWN : UP, f = W / 740;
                var g = L.layout(si === 1 ? BARE : ITEMS, env({
                    toY: ty, width: W, phone: phone, money: m, labels: true, laneW: 96, hlines: hl,
                    lastY: lastY, boxes: boxes, pinned: true, titles: titles, overlays: overlays,
                    candles: newest(ty, W), po3: scaled(state, W), asia: box(a, 470 * f, 510 * f) }));
                out.rules.push({ W: W, H: 384, scale: scale, shift: shift, phone: phone, state: si,
                                 pos: withPos, rows: m.map(function (r) { return r.y; }).concat(hl, [lastY]),
                                 g: geo(g) });
            });
          });
        });
    });
});
/* ...the candles over every first-pass slot: the loose pass, on the mark */
out.wall = geo(L.layout([], env({ po3: DIS, asia: box(UP), candles: [{ x0: 0, x1: 740, y0: 0, y1: 384 }] })));
/* ...money rows every 3 px: no letter at all, the key still says the phase */
var rowsAll = [];
for (var ry = 0; ry <= 384; ry += 3) rowsAll.push({ price: 1.0855 - (ry - 200) / 20000, y: ry, held: false });
out.blocked = geo(L.layout([], env({ po3: DIS, asia: box(UP), money: rowsAll, labels: true })));
out.blockedPhase = L.phaseAnswer({ ok: true, phase: 'distribution', direction: 'up', words: 'w' });

/* P10: crowded panes (Show all) */
out.crowdDis = geo(L.layout(ITEMS, env({ po3: DIS, asia: box(UP), showAll: true })));
out.crowdUnc = geo(L.layout(UNC_ITEMS, env({ po3: UNC, asia: box(UP), showAll: true })));

/* P11: hover never moves a chip or a label */
out.hover = {};
[null].concat(M.stageIds, [M.huntId, M.lowId]).forEach(function (h) {
    out.hover[String(h)] = geo(L.layout(ITEMS, env({ po3: DIS, asia: box(UP), hover: h })));
});
out.hoverPhone = {};
[null, 'sv-po3-d', 'sv-po3-m-low', M.lowId].forEach(function (h) {
    out.hoverPhone[String(h)] = geo(L.layout(ITEMS, env({ po3: scaled(DIS, 330), asia: box(UP, 210, 228),
                                                          hover: h, phone: true, width: 330 })));
});

/* P12: a phone */
out.phone = geo(L.layout(ITEMS, env({ po3: scaled(DIS, 330), asia: box(UP, 210, 228), phone: true, width: 330 })));
out.phoneFree = geo(L.layout([], env({ po3: scaled(DIS, 330), asia: box(UP, 210, 228), phone: true, width: 330 })));

/* P13: daily frames and the switch */
out.daily = geo(L.layout(ITEMS, env({ po3: DIS, asia: box(UP), highTf: true })));
out.switched = geo(L.layout(ITEMS, env({ po3: DIS, asia: box(UP), hidden: { asia: true } })));

/* P14: dims */
out.dims = {
    pinDark: geo(L.layout([], env({ po3: DIS, asia: box(UP), pinned: true }))),
    pinLight: geo(L.layout([], env({ po3: DIS, asia: box(UP), pinned: true, theme: 'light' }))),
    focusPool: geo(L.layout([], env({ po3: DIS, asia: box(UP), focus: 'pool' }))),
    focusAsia: geo(L.layout([], env({ po3: DIS, asia: box(UP), focus: 'asia' }))),
    hotD: geo(L.layout([], env({ po3: DIS, asia: box(UP), pinned: true, hover: 'sv-po3-d' }))),
    hotM: geo(L.layout([], env({ po3: DIS, asia: box(UP), pinned: true, hover: 'sv-po3-m-low' }))),
    /* P31: the chip that names M dims as the stage, not as its swing */
    focusAsiaFold: geo(L.layout(ITEMS, env({ po3: DIS, asia: box(UP), focus: 'asia' }))),
    focusSwingFold: geo(L.layout(ITEMS, env({ po3: DIS, asia: box(UP), focus: 'swing' }))),
    focusSwingHot: geo(L.layout(ITEMS, env({ po3: DIS, asia: box(UP), focus: 'swing', hover: M.lowId })))
};

/* P30: the hovered LAST LOW ray past a phone's four chips (two nearer
   pools take its chip): forced in late, as PR51's own chip */
var LATE_ITEMS = L.digest(M.lateRows, mapWith(M.stages), fmt), LATE_BARE = L.digest(M.lateRows, mapWith(null), fmt);
function lateEnv(h, p) { return env({ po3: p, asia: box(UP, 210, 228), hover: h, phone: true, width: 330 }); }
out.late = { rest: geo(L.layout(LATE_ITEMS, lateEnv(null, scaled(DIS, 330)))),
             hot: geo(L.layout(LATE_ITEMS, lateEnv(M.lowId, scaled(DIS, 330)))),
             pr51: geo(L.layout(LATE_BARE, lateEnv(M.lowId, null))) };
var lateChip = out.late.hot.chips.filter(function (c) { return c.id === M.lowId; })[0];
out.late.hit = lateChip ? L.hitChip(L.layout(LATE_ITEMS, lateEnv(M.lowId, scaled(DIS, 330))), LATE_ITEMS,
                                     (lateChip.x0 + lateChip.x1) / 2, (lateChip.y0 + lateChip.y1) / 2) : null;
if (out.late.hit) out.late.hit.item = !!out.late.hit.item;

/* P15: the hit test */
var gh = L.layout([], env({ po3: DIS, asia: box(UP) }));
var ml = gh.po3.labels.filter(function (l) { return l.stage === 'm'; })[0];
var dm = gh.po3.sweeps[0], ar = gh.po3.arrow, jd = gh.po3.judas;
var jmx = (jd.x0 + jd.x1) / 2, jmy = (jd.y0 + jd.y1) / 2, jl = Math.sqrt(Math.pow(jd.x1 - jd.x0, 2) + Math.pow(jd.y1 - jd.y0, 2));
var nx = -(jd.y1 - jd.y0) / jl, ny = (jd.x1 - jd.x0) / jl;          /* the segment's normal */
out.hit = {
    label: L.hitStage(gh, (ml.x0 + ml.x1) / 2, (ml.y0 + ml.y1) / 2, 0, true),
    labelOnlyOnDiamond: L.hitStage(gh, dm.x, dm.cy, 6, true),
    diamond6: L.hitStage(gh, dm.box.x1 + 6, dm.cy, 6, false),
    diamond7: L.hitStage(gh, dm.box.x1 + 7, dm.cy, 6, false),
    diamond12: L.hitStage(gh, dm.box.x1 + 12, dm.cy, 12, false),
    arrow: L.hitStage(gh, ar.x, (ar.y0 + ar.y1) / 2, 6, false),
    judas: L.hitStage(gh, jmx + 3 * nx, jmy + 3 * ny, 6, false),
    judasFar: L.hitStage(gh, jmx + 9 * nx, jmy + 9 * ny, 6, false),
    band: L.hitStage(gh, 690, 40, 12, false),
    none: L.hitStage(null, 1, 1, 6, false)
};
/* a chip that names M answers its stage by its exact box */
var gf = L.layout(ITEMS, env({ po3: DIS, asia: box(UP) }));
var fc = gf.chips.filter(function (c) { return c.stage; })[0];
out.hit.chip = fc ? L.hitChip(gf, ITEMS, (fc.x0 + fc.x1) / 2, (fc.y0 + fc.y1) / 2) : null;
if (out.hit.chip) out.hit.chip.item = !!out.hit.chip.item;

/* P16: the key's words */
function day(phase, o) { var d = { ok: true, phase: phase, direction: null, words: 'the words', run: null };
                         for (var k in (o || {})) d[k] = o[k]; return d; }
out.key = {};
[['acc', day('accumulation')],
 ['manLow', day('manipulation', { run: { below: true, above: false } })],
 ['manHigh', day('manipulation', { run: { below: false, above: true } })],
 ['disUp', day('distribution', { direction: 'up' })],
 ['disDown', day('distribution', { direction: 'down' })],
 ['unc', day('unclear')]].forEach(function (p) {
    out.key[p[0]] = { desk: L.phaseAnswer(p[1], false), phone: L.phaseAnswer(p[1], true) };
});

/* P17: the cards */
var D = { high: 1.08608, low: 1.08441, phase: 'distribution', direction: 'up', words: M.words,
          stages: M.stages, odds: { verdict: 'unjudged' }, mark: M.mark };
var MANDAY = clone(D); MANDAY.phase = 'manipulation'; MANDAY.direction = null;
MANDAY.stages = clone(M.stages);
MANDAY.stages.sweeps[0].back_at = null; MANDAY.stages.sweeps[0].back_price = null; MANDAY.stages.sweeps[0].back_ny = null;
var JDAY = clone(D); JDAY.stages = clone(M.stages); JDAY.stages.judas = M.judas;
var map = { path: M.path };
var NY = M.stages.new_york;
out.cards = {
    m: HC.stageCard({ stage: 'm', side: 'low', part: 'mark' }, JDAY, map, M.now, fmt),
    mMan: HC.stageCard({ stage: 'm', side: 'low', part: 'label' }, MANDAY, map, M.now, fmt),
    judas: HC.stageCard({ stage: 'm', side: null, part: 'judas' }, JDAY, map, M.now, fmt),
    d: HC.stageCard({ stage: 'd', side: 'low', part: 'mark' }, D, map, M.now, fmt),
    dOther: HC.stageCard({ stage: 'd', side: 'low', part: 'mark' }, D,
                         { path: [{ leg: 'draw', price: 1.0800, side: 'below' }] }, M.now, fmt),
    dJudged: HC.stageCard({ stage: 'd', side: 'low', part: 'label' }, (function () { var x = clone(D); x.odds = { verdict: 'proven' }; return x; })(), map, M.now, fmt),
    dBefore: HC.stageCard({ stage: 'd', side: 'low', part: 'mark' }, D, map, NY.opened - 60, fmt),
    dDuring: HC.stageCard({ stage: 'd', side: 'low', part: 'mark' }, D, map, NY.opened + 60, fmt),
    dAfter: HC.stageCard({ stage: 'd', side: 'low', part: 'mark' }, D, map, NY.closed + 60, fmt),
    /* a 4h read, as the server says it (2026-10-15): the run's bar as its
       span on the New York clock, the return by that bar's close */
    fourH: HC.stageCard({ stage: 'm', side: 'low', part: 'mark' },
                        (function () { var x = clone(D); x.stages.bar = 14400;
                                       x.stages.sweeps[0] = { side: 'low', edge: 1.08441, price: 1.08288, at: 1791360000,
                                                              ny: '04:00–08:00', session: 'london', back_at: 1791374400,
                                                              back_close_at: 1791388800, back_price: 1.0851, back_ny: '12:00' };
                                       return x; })(), map, M.now, fmt),
    fourHD: HC.stageCard({ stage: 'd', side: 'low', part: 'mark' },
                         (function () { var x = clone(D); x.stages.bar = 14400;
                                        x.stages.sweeps[0] = { side: 'low', edge: 1.08441, price: 1.08288, at: 1791360000,
                                                               ny: '04:00–08:00', session: 'london', back_at: 1791374400,
                                                               back_close_at: 1791388800, back_price: 1.0851, back_ny: '12:00' };
                                        return x; })(), map, M.now, fmt),
    /* P32: the day's sentence carrying the old `judas` key's clause */
    mOldJudas: HC.stageCard({ stage: 'm', side: 'low', part: 'mark' },
                            (function () { var x = clone(JDAY); x.words = M.words + M.oldJudas; return x; })(), map, M.now, fmt),
    dOldJudas: HC.stageCard({ stage: 'd', side: 'low', part: 'mark' },
                            (function () { var x = clone(D); x.words = M.words + M.oldJudas; return x; })(), map, M.now, fmt),
    unc: HC.stageCard({ stage: 'm', side: 'high', part: 'mark' },
                      (function () { var x = clone(D); x.phase = 'unclear'; x.stages = UNC_STAGES; return x; })(), map, M.now, fmt),
    hostile: HC.stageCard({ stage: 'm', side: 'low', part: 'mark' },
                          (function () { var x = clone(D); x.words = '<img src=x onerror=alert(1)>'; return x; })(), map, M.now, fmt)
};

/* P18: the arrow's floor and the pane */
out.arrow = {
    short: geo(L.layout([], env({ po3: po3('distribution', { direction: 'up', sweeps: [run('low', 1.08288, 1.08441, 545, true)],
                                   ret: { x: 605, from: 1.08441, to: 1.08450 } }), asia: box(UP) }))).po3.arrow,
    shortDown: geo(L.layout([], env({ po3: po3('distribution', { direction: 'down', sweeps: [run('high', 1.08712, 1.08559, 545, true)],
                                       ret: { x: 605, from: 1.08559, to: 1.08550 } }), asia: box(DOWN) }))).po3.arrow,
    tailOff: geo(L.layout([], env({ po3: po3('distribution', { direction: 'up', sweeps: [],
                                     ret: { x: 605, from: 1.0700, to: 1.08608 } }), asia: box(UP) }))).po3.arrow,
    headOff: geo(L.layout([], env({ po3: po3('distribution', { direction: 'up', sweeps: [],
                                     ret: { x: 605, from: 1.08441, to: 1.1000 } }), asia: box(UP) }))).po3.arrow,
    xOff: geo(L.layout([], env({ po3: po3('distribution', { direction: 'up', sweeps: [],
                                  ret: { x: 760, from: 1.08441, to: 1.08608 } }), asia: box(UP) }))).po3.arrow
};

/* P20 (2026-10-08 acceptance): a position's entry marker just beyond the
   swept wick (London's usual entry, on the sweep bar): the diamond sits on
   the wick's end, over its candle, clear of the marker; a money row there
   keeps it where it was */
var TIP = toY(1.08288), MK = { x0: 500, x1: 590, y0: TIP + 1, y1: TIP + 31 };
out.marker = geo(L.layout([], env({ po3: DIS, asia: box(UP), boxes: [MK] })));
out.markerRow = geo(L.layout([], env({ po3: DIS, asia: box(UP), boxes: [MK],
                                       money: [{ price: 1.08300, y: toY(1.08300), held: false }] })));
out.markerHigh = geo(L.layout([], env({ po3: DOWNP, asia: box(DOWN),
                                        boxes: [{ x0: 500, x1: 590, y0: toY(1.08712) - 31, y1: toY(1.08712) - 1 }] })));
/* P21: the marks whole on the pane, the newest bar at its edge */
out.edge = geo(L.layout([], env({ po3: po3('distribution', { direction: 'up',
                                   sweeps: [run('low', 1.08288, 1.08441, 739, true)],
                                   ret: { x: 739.5, from: 1.08441, to: 1.08608 } }), asia: box(UP) })));
out.edgeLeft = geo(L.layout([], env({ po3: po3('manipulation', { sweeps: [run('low', 1.08288, 1.08441, 1, false)] }),
                                      asia: box(UP) })));
/* P22: the zoomed 1h: the ray's own right-edge slot lies right of the D
   arrow; M names its diamond, so the letters read A, M, D */
var WZ = 1400, fz = (WZ - 68) / (740 - 68);
var ZITEMS = L.digest(M.rows, mapWith(M.stages), fmt);
var zLow = L.layout(ZITEMS, env({ width: WZ, po3: null, asia: null })).rays
    .filter(function (r) { return r.id === M.lowId; })[0];
var ZOOM = po3('distribution', { direction: 'up', london: { x0: zLow.x0 - 40, x1: zLow.x0 + 10 },
                                 ny: { x0: zLow.x0 + 15, x1: zLow.x0 + 60 },
                                 sweeps: [run('low', 1.08288, 1.08441, zLow.x0, true)],
                                 ret: { x: zLow.x0 + 20, from: 1.08441, to: 1.08608 }, draw: 'agrees' });
/* the bars after the sweep sit on the ray (they hold its slots beside the
   diamond); the newest bar is up by the mark */
var ZCANDLES = [{ x0: zLow.x0 + 5, x1: zLow.x0 + 25, y0: 230, y1: 262 },
                { x0: WZ - 80, x1: WZ - 70, y0: 100, y1: 120 }];
out.zoom = geo(L.layout(ZITEMS, env({ width: WZ, po3: ZOOM, asia: box(UP, zLow.x0 - 90, zLow.x0 - 50),
                                      candles: ZCANDLES })));
out.zoomOrigin = zLow.x0;
/* P23: a role's chip at the right edge slides left of today's diamond and
   keeps its words (the 4h HUNT), where PR51's slot is the same without it */
var HUNTRUN = po3('distribution', { direction: 'up', sweeps: [run('low', 1.08245, 1.08441, 732, true)],
                                    ret: null });
var BLOCK = [{ x0: 200, x1: 450, y0: 250, y1: 300 }];
out.roleSlide = geo(L.layout(ITEMS, env({ po3: HUNTRUN, asia: box(UP), overlays: BLOCK })));
out.roleBare = geo(L.layout(BARE, env({ po3: null, asia: box(UP), overlays: BLOCK })));
/* P24: the forming bar spared before the loose pass; D's short words
   before its long ones cover a candle */
var FORMING = [{ x0: 0, x1: 599, y0: 0, y1: 384 }, { x0: 600, x1: 612, y0: 0, y1: 384 }];
out.spare = geo(L.layout([], env({ po3: DIS, asia: box(UP), candles: FORMING })));
out.dShort = geo(L.layout([], env({ po3: DIS, asia: box(UP), candles: [
    { x0: 520, x1: 560, y0: 150, y1: 200 }, { x0: 640, x1: 700, y0: 150, y1: 200 }] })));
/* P25: a finger beside the diamond, on the band under it: the drawn
   diamond (+ LV.MARK_HIT) misses where its box reached */
var gd = L.layout([], env({ po3: DIS, asia: box(UP) })), sd = gd.po3.sweeps[0];
out.hitDrawn = {
    corner: L.hitStage(gd, sd.x - 4.5, sd.cy + 4.5, LV.MARK_HIT, false, true),
    cornerBox: L.hitStage(gd, sd.x - 4.5, sd.cy + 4.5, LV.MARK_HIT, false),
    centre: L.hitStage(gd, sd.x, sd.cy, LV.MARK_HIT, false, true),
    reach: L.hitStage(gd, sd.x + LV.SWEEP_R + LV.MARK_HIT, sd.cy, LV.MARK_HIT, false, true),
    arrow: L.hitStage(gd, gd.po3.arrow.x, (gd.po3.arrow.y0 + gd.po3.arrow.y1) / 2, LV.MARK_HIT, false, true)
};

/* P26 (2026-10-08 acceptance): a chip that names M keeps the level chip's
   plate over the older candles; over the forming bar alone it leaves that
   bar's column open */
out.foldOlder = geo(L.layout(ITEMS, env({ po3: DIS, asia: box(UP),
    candles: [{ x0: 0, x1: 739, y0: 200, y1: 300 }, { x0: 730, x1: 740, y0: 0, y1: 10 }] })));
out.foldForming = geo(L.layout(ITEMS, env({ po3: DIS, asia: box(UP),
    candles: [{ x0: 0, x1: 649, y0: 200, y1: 300 }, { x0: 650, x1: 662, y0: 200, y1: 300 }] })));
/* P27: a 4h pane (0.8 px a pip, 4 px a bar): the D arrow stands on the
   very next bar, over PR51's LAST LOW slot; the chip that names M ends
   just before it, over its own diamond */
var TY4 = toYs(8000, 0);
var RAY4 = L.layout(ITEMS, env({ toY: TY4, po3: null, asia: null })).rays
    .filter(function (r) { return r.id === M.lowId; })[0].x0;
function four(ret) {
    return po3('distribution', { direction: 'up', london: null, ny: null, draw: 'agrees',
                                 sweeps: [run('low', 1.08288, 1.08441, RAY4, true)], ret: ret });
}
out.four = geo(L.layout(ITEMS, env({ toY: TY4, po3: four({ x: RAY4 + 4.2, from: 1.08441, to: 1.08608 }),
                                     asia: box(UP, RAY4 - 14, RAY4 - 10) })));
out.fourFree = geo(L.layout(ITEMS, env({ toY: TY4, po3: four(null), asia: box(UP, RAY4 - 14, RAY4 - 10) })));
out.fourBare = geo(L.layout(BARE, env({ toY: TY4, po3: null, asia: box(UP, RAY4 - 14, RAY4 - 10) })));
/* P28: the diamond lifted onto the wick's end keeps off a price line's
   title box (the pinned signal's 'Stop', stacked there): it stays beyond
   the wick, under the marker, and the money wins */
out.markerTitle = geo(L.layout([], env({ po3: DIS, asia: box(UP), boxes: [MK],
                                         titles: [{ y: TIP - 4, w: 205 }] })));

/* P19: the draw's agreement */
out.agree = {
    up: L.drawAgrees({ path: M.path }, 'up', M.mark),
    down: L.drawAgrees({ path: M.path }, 'down', M.mark),
    sideBelow: L.drawAgrees({ path: [{ leg: 'draw', price: 1.09, side: 'below' }] }, 'up', M.mark),
    sideNoPrice: L.drawAgrees({ path: [{ leg: 'draw', side: 'above' }] }, 'up', M.mark),
    noLeg: L.drawAgrees({ path: [M.path[0]] }, 'up', M.mark),
    noDir: L.drawAgrees({ path: M.path }, null, M.mark),
    noMap: L.drawAgrees(null, 'up', M.mark)
};
process.stdout.write(JSON.stringify(out));
"""


def _label(g, stage):
    got = [l for l in (g["po3"] or {}).get("labels", []) if l["stage"] == stage]
    return got[0] if got else None


def _texts(g):
    """Every word a geometry puts on the pane: chips, edges, labels."""
    out = [c["text"] for c in g["chips"]] + [e["text"] for e in g["edges"]]
    if g.get("asia") and g["asia"].get("label"):
        out.append(g["asia"]["label"]["text"])
    if g.get("po3"):
        out += [l["text"] for l in g["po3"]["labels"]]
    return out


def _on_mark(label, g):
    """A label covers its own mark's centre x, or starts within 2 px of its
    right edge on its row (the M label's last slot)."""
    p = g["po3"]
    if label["stage"] == "d":
        return label["x0"] <= p["arrow"]["x"] <= label["x1"]
    s = [s for s in p["sweeps"] if s["side"] == label["side"]][0]
    return (label["x0"] <= s["x"] <= label["x1"]
            or (abs(label["x0"] - s["box"]["x1"] - 2) < 1e-9
                and label["y0"] <= s["cy"] <= label["y1"]))


@unittest.skipUnless(NODE, "node is not installed")
class ThePo3LanguageTests(SimpleTestCase):
    """The pure half (window.svLevels, window.svHoverCards) under node."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        pure, _main = _blocks(widget())
        cls.out = _node("var window = {};\n" + pure + "\n" + PO3_PURE_RUN, {
            "rows": FIXTURE_ROWS, "path": PATH, "now": NOW, "mark": 1.08552,
            "pos": POSITION, "pinned": PINNED, "markers": MARKERS, "stages": STAGES,
            "judas": JUDAS, "words": WORDS, "stageIds": STAGE_IDS, "huntId": HUNT_ID,
            "lowId": LOW_ID, "lateRows": LATE_ROWS, "oldJudas": OLD_JUDAS})

    # P1
    def test_accumulation_draws_the_box_alone(self):
        g = self.out["acc"]
        p = g["po3"]
        self.assertEqual((p["bands"], p["sweeps"], p["judas"], p["arrow"], p["labels"]),
                         ([], [], None, None, []))
        self.assertEqual(p["phase"], "accumulation")
        self.assertEqual(g["asia"]["label"]["text"], "A · ASIA")
        self.assertIn("LAST LOW  1.08288", _texts(g), "no stage, no fold")

    # P2
    def test_a_run_holding_draws_london_a_hollow_mark_and_no_d(self):
        for g in (self.out["man"], self.out["freeMan"]):
            p = g["po3"]
            self.assertEqual([b["id"] for b in p["bands"]], ["sv-po3-london"],
                             "no New York band although its window was given")
            self.assertEqual((p["bands"][0]["x0"], p["bands"][0]["x1"]), (520, 560))
            self.assertEqual(len(p["sweeps"]), 1)
            s = p["sweeps"][0]
            self.assertFalse(s["filled"], "a run that holds is hollow")
            self.assertAlmostEqual(s["cy"], toY(1.08288) + 6, places=9)
            self.assertAlmostEqual(s["tipY"], toY(1.08288), places=9)
            self.assertIsNone(p["arrow"])
            self.assertIsNone(_label(g, "d"))
            self.assertIsNotNone(p["judas"])
        texts = _texts(self.out["man"]) + _texts(self.out["freeMan"])
        self.assertIn("M · RUN  1.08288", texts)
        self.assertFalse([t for t in texts if t.startswith("D")])
        self.assertFalse([t for t in texts if "SWEEP" in t])

    # P3
    def test_distribution_up_draws_the_three_stages(self):
        for g in (self.out["dis"], self.out["free"]):
            p = g["po3"]
            self.assertEqual([b["id"] for b in p["bands"]], ["sv-po3-london", "sv-po3-ny"])
            self.assertEqual((p["bands"][1]["x0"], p["bands"][1]["x1"]), (600, 700))
            self.assertTrue(p["sweeps"][0]["filled"], "a run that came back is a sweep: solid")
            a = p["arrow"]
            self.assertEqual(a["x"], 605)
            self.assertAlmostEqual(a["y0"], toY(1.08441), places=9)
            self.assertAlmostEqual(a["y1"], toY(1.08608), places=9)
            self.assertEqual((a["dir"], a["side"]), ("up", "low"))
            self.assertEqual(g["asia"]["label"]["text"], "A · ASIA")
        free = self.out["free"]
        self.assertEqual(_label(free, "m")["text"], "M · SWEEP  1.08288")
        self.assertEqual(_label(free, "d")["text"], "D ▲ · ② DRAW")
        self.assertEqual(_label(self.out["freeNo"], "d")["text"], "D ▲")
        self.assertEqual(_label(self.out["dis"], "d")["text"], "D ▲ · ② DRAW")
        for l in free["po3"]["labels"]:
            self.assertTrue(_on_mark(l, free), l)

    # P4
    def test_distribution_down_mirrors(self):
        for g in (self.out["down"], self.out["freeDown"]):
            p = g["po3"]
            a = p["arrow"]
            self.assertEqual((a["dir"], a["side"]), ("down", "high"))
            self.assertGreater(a["y1"], a["y0"])
            self.assertAlmostEqual(a["y0"], toY(1.08559), places=9)
            self.assertAlmostEqual(a["y1"], toY(1.08392), places=9)
            s = p["sweeps"][0]
            self.assertAlmostEqual(s["cy"], toY(1.08712) - 6, places=9, msg="over the high")
        self.assertEqual(_label(self.out["freeDown"], "d")["text"], "D ▼")
        self.assertEqual(_label(self.out["freeDown"], "m")["text"], "M · SWEEP  1.08712")

    # P5
    def test_unclear_draws_both_runs_and_no_direction(self):
        g = self.out["unc"]
        p = g["po3"]
        self.assertEqual([(s["side"], s["filled"]) for s in p["sweeps"]],
                         [("low", True), ("high", False)], "both runs, filled by their own return")
        self.assertIsNone(p["arrow"])
        self.assertEqual([b["id"] for b in p["bands"]], ["sv-po3-london"])
        self.assertEqual(p["labels"], [])
        self.assertEqual(p["folded"], {})
        for t in _texts(g):
            self.assertIsNone(re.match(r"^(M|D)\b", t), t)
        self.assertIn("LAST LOW  1.08288", _texts(g))
        self.assertEqual(self.out["key"]["unc"]["desk"]["text"], "unclear · both sides run")
        self.assertEqual(self.out["key"]["unc"]["phone"]["text"], "unclear")

    # P6
    def test_no_day_draws_nothing(self):
        g = self.out["none"]
        self.assertIsNone(g["po3"])
        self.assertEqual(g["asia"]["label"]["text"], "ASIA")
        self.assertEqual(self.out["phaseNone"], [None, None, None])
        self.assertIn("LAST LOW  1.08288", _texts(g))

    # P7
    def test_the_sweep_folds_into_the_last_low_chip(self):
        by = {i["id"]: i for i in self.out["items"]}
        self.assertEqual(by[LOW_ID]["sweep"], "low")
        self.assertEqual([i["id"] for i in self.out["items"] if i["sweep"]], [LOW_ID])
        # Without stages the digest is PR51's, byte for byte: no flag at all.
        self.assertFalse([i for i in self.out["bareItems"] if i["hasSweepKey"]])
        self.assertTrue(self.out["bareDigest"])
        dis = self.out["dis"]
        chip = [c for c in dis["chips"] if c["id"] == LOW_ID][0]
        self.assertEqual(chip["text"], "M · SWEEP  1.08288")
        self.assertEqual((chip["stage"], chip["sweep"]), ("m", "low"))
        self.assertEqual(dis["po3"]["folded"], {"low": LOW_ID})
        self.assertIsNone(_label(dis, "m"), "no second M on the same price")
        man = [c for c in self.out["man"]["chips"] if c["id"] == LOW_ID][0]
        self.assertEqual(man["text"], "M · RUN  1.08288")
        phone = [c for c in self.out["phone"]["chips"] if c["id"] == LOW_ID][0]
        self.assertEqual(phone["text"], "M")
        for g in (self.out["bare"], self.out["barePlain"]):
            plain = [c for c in g["chips"] if c["id"] == LOW_ID][0]
            self.assertEqual(plain["text"], "LAST LOW  1.08288")
            self.assertNotIn("stage", plain)
        # The lane closed and the diamond under the ray's start: the letter
        # alone, where PR51's LAST L fitted (the harness's position zoom).
        tight = self.out["foldTight"]
        m = [c for c in tight["chips"] if c["id"] == LOW_ID][0]
        self.assertEqual((m["text"], m["stage"]), ("M", "m"))
        self.assertEqual(tight["po3"]["folded"], {"low": LOW_ID})
        self.assertFalse(_meets(m, tight["po3"]["sweeps"][0]["box"]))
        self.assertGreaterEqual(m["x0"], tight["rays"][[r["id"] for r in tight["rays"]].index(LOW_ID)]["x0"])
        # Every other chip keeps its PR51 words.
        self.assertEqual(sorted(t for t in (c["text"] for c in dis["chips"]) if not t.startswith("M")),
                         sorted(t for t in (c["text"] for c in self.out["bare"]["chips"])
                                if t != "LAST LOW  1.08288"))

    # P8
    def test_an_unfolded_sweep_gets_its_own_label_on_its_mark(self):
        for key in ("lone", "loneHigh"):
            g = self.out[key]
            labels = [l for l in g["po3"]["labels"] if l["stage"] == "m"]
            self.assertEqual(len(labels), 1, key)
            self.assertTrue(_on_mark(labels[0], g), (key, labels[0]))
            self.assertEqual(g["po3"]["folded"], {})
        self.assertEqual(_label(self.out["lone"], "m")["text"], "M · RUN  1.08320")
        self.assertIn("LAST LOW  1.08288", _texts(self.out["lone"]),
                      "the ray keeps its own chip: the run is at another price")
        hi = _label(self.out["loneHigh"], "m")
        self.assertLessEqual(hi["y1"], self.out["loneHigh"]["po3"]["sweeps"][0]["box"]["y0"],
                             "over a high's diamond")

    # P9
    def test_stage_labels_keep_every_pr51_rule(self):
        seen = 0
        for case in self.out["rules"]:
            g, W = case["g"], case["W"]
            p = g["po3"]
            placed = g["chips"] + g["edges"]
            for l in p["labels"]:
                seen += 1
                ctx = (case["scale"], case["shift"], case["phone"], case["state"], case["pos"], l["text"])
                self.assertLessEqual(l["x1"], W, ctx)
                self.assertGreaterEqual(l["x0"], 0, ctx)
                self.assertTrue(_on_mark(l, g), ctx)
                for t in g["keep"]["titles"]:
                    self.assertFalse(_meets(l, t, GAP_X, GAP_Y), (ctx, t))
                for b in g["keep"]["marks"] + g["keep"]["overlays"]:
                    self.assertFalse(_meets(l, b), (ctx, b))
                for c in placed:
                    self.assertFalse(_meets(l, c), (ctx, c["text"]))
                for other in p["labels"]:
                    if other is not l:
                        self.assertFalse(_meets(l, other), ctx)
                for row in case["rows"]:
                    self.assertFalse(l["y0"] - ROW_CLEAR <= row <= l["y1"] + ROW_CLEAR, (ctx, row))
                for b in g["bands"]:
                    self.assertFalse(_meets(l, b, 0, ROLE_GAP), (ctx, b["id"]))
                for r in g["rays"]:
                    self.assertFalse(_meets(l, {"x0": r["x0"], "x1": r["x1"], "y0": r["y"] - 1,
                                                "y1": r["y"] + 1}, 0, ROLE_GAP), (ctx, r["id"]))
                for s in p["sweeps"]:
                    self.assertFalse(_meets(l, s["box"]), (ctx, "covers a diamond"))
                if p["arrow"]:
                    self.assertFalse(_meets(l, p["arrow"]["box"]), (ctx, "covers the arrow"))
            # the money's rows are never covered by a level chip either
            for c in g["chips"]:
                if not c["cross"]:
                    for row in case["rows"]:
                        self.assertFalse(c["y0"] - ROW_CLEAR <= row <= c["y1"] + ROW_CLEAR, (c["text"], row))
            if case["phone"]:
                self.assertLessEqual(len(g["chips"]), 4)
                for l in p["labels"]:
                    self.assertIn(l["text"], ("M", "D▲", "D▼"))
        self.assertGreater(seen, 30, "labels were placed in the sweep")
        # M is named by its label or by the level chip it folds into (on its
        # diamond either way since 2026-10-08)
        stages = ({(c["state"], l["stage"]) for c in self.out["rules"] for l in c["g"]["po3"]["labels"]}
                  | {(c["state"], ch["stage"]) for c in self.out["rules"] for ch in c["g"]["chips"]
                     if ch.get("stage")})
        # (the DOWN arrow's head sits beside the pinned signal's Stop row in
        # every one of these scenes: its D letter is refused, as it must be)
        self.assertTrue({(0, "d"), (1, "m"), (2, "m")} <= stages, stages)
        # Candles over every first-pass slot: the loose pass, still on the mark.
        wall = self.out["wall"]
        self.assertEqual(sorted(l["stage"] for l in wall["po3"]["labels"]), ["d", "m"])
        for l in wall["po3"]["labels"]:
            self.assertTrue(_on_mark(l, wall), l)
        # Money rows over every slot: no letter, never across a row.
        blocked = self.out["blocked"]
        self.assertEqual(blocked["po3"]["labels"], [])
        self.assertNotIn("label", blocked["asia"])
        self.assertEqual(self.out["blockedPhase"]["text"], "D ▲ distribution")

    # P10
    def test_no_level_chip_covers_a_stage_mark(self):
        n = 0
        for key in ("dis", "unc", "crowdDis", "crowdUnc", "man", "down", "phone"):
            g = self.out[key]
            marks = [s["box"] for s in g["po3"]["sweeps"]]
            if g["po3"]["arrow"]:
                marks.append(g["po3"]["arrow"]["box"])
            self.assertTrue(marks, key)
            for c in g["chips"] + g["edges"]:
                for b in marks:
                    n += 1
                    self.assertFalse(_meets(c, b), (key, c["text"], b))
            if g["asia"].get("label"):
                for b in marks:
                    self.assertFalse(_meets(g["asia"]["label"], b), (key, "A label"))
        self.assertGreater(n, 30)

    # P11
    def test_hover_never_moves_a_chip_or_a_label(self):
        def rects(g, hover):
            chips = sorted("%s|%s|%.6f|%.6f|%.6f|%.6f" % (c["id"], c["text"], c["x0"], c["y0"], c["x1"], c["y1"])
                           for c in g["chips"])
            edges = sorted("%s|%.6f|%.6f" % (e["text"], e["x0"], e["y0"]) for e in g["edges"])
            label = g["asia"].get("label") if g["asia"] else None
            labels = sorted("%s|%s|%.6f|%.6f" % (l["id"], l["text"], l["x0"], l["y0"]) for l in g["po3"]["labels"])
            return chips, edges, label and (label["x0"], label["y0"], label["text"]), labels
        for family in ("hover", "hoverPhone"):
            views = self.out[family]
            base = rects(views["null"], None)
            for h, g in views.items():
                got = rects(g, h)
                chips = [c for c in got[0] if not (c.startswith(h + "|") and c not in base[0])]
                self.assertEqual(chips, base[0], (family, h))
                self.assertEqual(got[1:], base[1:], (family, h))
        # ...and a hovered stage glows: its mark and its band
        hot = self.out["hover"]["sv-po3-m-low"]["po3"]
        self.assertTrue(hot["sweeps"][0]["hot"])
        self.assertEqual([b["id"] for b in hot["bands"] if b["hot"]], ["sv-po3-london"])
        hot_d = self.out["hover"]["sv-po3-d"]["po3"]
        self.assertTrue(hot_d["arrow"]["hot"])
        self.assertEqual([b["id"] for b in hot_d["bands"] if b["hot"]], ["sv-po3-ny"])
        hot_j = self.out["hover"]["sv-po3-judas"]["po3"]
        self.assertTrue(hot_j["judas"]["hot"])
        self.assertEqual([b["id"] for b in hot_j["bands"] if b["hot"]], ["sv-po3-london"])

    # P12
    def test_phone_texts_are_letters(self):
        g = self.out["phone"]
        self.assertEqual(g["asia"]["label"]["text"], "A")
        texts = _texts(g)
        self.assertIn("M", texts, "the LAST L chip names M")
        self.assertIn("D▲", [l["text"] for l in g["po3"]["labels"]])
        self.assertLessEqual(len(g["chips"]), 4)
        free = self.out["phoneFree"]
        self.assertEqual(sorted(l["text"] for l in free["po3"]["labels"]), ["D▲", "M"])
        self.assertEqual(free["asia"]["label"]["text"], "A")
        for t in texts:
            self.assertNotIn("SWEEP", t)
            self.assertNotIn("DRAW", t if t.startswith("D") else "")

    # P13
    def test_daily_frames_and_the_switch_draw_no_stage(self):
        self.assertIsNone(self.out["daily"]["po3"])
        self.assertIsNone(self.out["daily"]["asia"])
        self.assertIsNone(self.out["switched"]["po3"])
        self.assertIsNone(self.out["switched"]["asia"])
        for g in (self.out["daily"], self.out["switched"]):
            self.assertNotIn("M · SWEEP  1.08288", _texts(g), "no fold without the drawn stage")

    # P14
    def test_the_marks_dim_with_a_pin_and_a_focus(self):
        d = self.out["dims"]

        def shapes(g):
            p = g["po3"]
            return p["bands"] + p["sweeps"] + [p["judas"], p["arrow"]]
        for key, k in (("pinDark", 0.55), ("pinLight", 0.8), ("focusPool", 0.2), ("focusAsia", 1)):
            for s in shapes(d[key]):
                self.assertAlmostEqual(s["k"], k, msg=(key, s["id"]))
        for l in d["pinDark"]["po3"]["labels"] + d["pinLight"]["po3"]["labels"]:
            self.assertEqual(l["k"], 1, "labels are never pin-dimmed")
        for l in d["focusPool"]["po3"]["labels"]:
            self.assertAlmostEqual(l["k"], 0.2)
        hot = d["hotD"]["po3"]
        self.assertEqual(hot["arrow"]["k"], 1)
        self.assertEqual([b["k"] for b in hot["bands"] if b["id"] == "sv-po3-ny"], [1])
        self.assertAlmostEqual(hot["sweeps"][0]["k"], 0.55)
        hm = d["hotM"]["po3"]
        self.assertEqual(hm["sweeps"][0]["k"], 1)
        self.assertEqual([b["k"] for b in hm["bands"] if b["id"] == "sv-po3-london"], [1])

    # P15
    def test_hit_the_stages_as_drawn(self):
        h = self.out["hit"]
        self.assertEqual(h["label"], {"id": "sv-po3-m-low", "stage": "m", "side": "low", "part": "label"})
        self.assertIsNone(h["labelOnlyOnDiamond"], "labels only: the diamond waits for the money")
        self.assertEqual(h["diamond6"], {"id": "sv-po3-m-low", "stage": "m", "side": "low", "part": "mark"})
        self.assertIsNone(h["diamond7"])
        self.assertEqual(h["diamond12"]["id"], "sv-po3-m-low", "a finger reaches 12 px")
        self.assertEqual(h["arrow"], {"id": "sv-po3-d", "stage": "d", "side": "low", "part": "mark"})
        self.assertEqual(h["judas"], {"id": "sv-po3-judas", "stage": "m", "side": None, "part": "judas"})
        self.assertIsNone(h["judasFar"])
        self.assertIsNone(h["band"], "a band is never hit")
        self.assertIsNone(h["none"])
        self.assertEqual(h["chip"], {"id": LOW_ID, "item": True, "stage": "m", "sweep": "low"})

    # P16
    def test_the_key_names_the_phase(self):
        k = self.out["key"]
        want = {"acc": ("A · accumulating", "A"), "manLow": ("M · the lows run", "M"),
                "manHigh": ("M · the highs run", "M"), "disUp": ("D ▲ distribution", "D▲"),
                "disDown": ("D ▼ distribution", "D▼"), "unc": ("unclear · both sides run", "unclear")}
        for key, (desk, phone) in want.items():
            self.assertEqual(k[key]["desk"]["text"], desk, key)
            self.assertEqual(k[key]["phone"]["text"], phone, key)
            self.assertEqual(k[key]["desk"]["title"], "the words")
        self.assertEqual(k["disUp"]["desk"]["phase"], "distribution")

    # P17
    def test_the_stage_cards_say_what_happened_when_and_where(self):
        c = self.out["cards"]
        m = c["m"]
        for part in ('<span class="sv-sig-side">MANIPULATION</span>',
                     '<span class="sv-sig-rule">Sweep of the Asian lows</span>',
                     "<dt>Ran to</dt><dd>1.08288</dd>", "<dt>Asian low</dt><dd>1.08441</dd>",
                     "<dt>When</dt><dd>08:00 UTC · 04:00 New York, London</dd>",
                     "<dt>Back inside</dt><dd>1.08510 at 12:00 UTC · 08:00 New York</dd>",
                     "<dt>London</dt><dd>02:00–05:00 New York · closed</dd>",
                     "<dt>Judas</dt><dd>London opened 1.08520, faked to 1.08288 at 08:00 UTC</dd>",
                     "The stops under the Asian low were taken", "read on the 1h bars",
                     "Power of Three (the ny am session"):
            self.assertIn(part, m)
        self.assertIn("not yet: the price holds under the range", c["mMan"])
        self.assertIn("Run of the Asian lows", c["mMan"])
        # a 4h read (2026-10-15): the run as its bar's span, the return by
        # the bar's close, where it printed, and never the bar's open clock
        self.assertIn("read on the 4h bars", c["fourH"])
        self.assertIn("<dt>When</dt><dd>the 4h bar from 08:00 UTC · 04:00–08:00 New York, London</dd>", c["fourH"])
        self.assertIn("<dt>Back inside</dt><dd>1.08510 by 16:00 UTC · 12:00 New York, the 4h bar&#39;s close</dd>",
                      c["fourH"])
        self.assertNotIn("at 12:00 UTC", c["fourH"])
        self.assertIn("<dt>Back inside</dt><dd>1.08510 by 16:00 UTC · 12:00 New York, the 4h bar&#39;s close</dd>",
                      c["fourHD"])
        self.assertIn("<dt>When</dt><dd>08:00 UTC · 04:00 New York, London</dd>", m, "the 1h read: the bar")
        self.assertIn("Run of the Asian highs · both sides run", c["unc"])
        self.assertIn("not yet: the price holds over the range", c["unc"])
        self.assertIn("The stops over the Asian high were taken", c["unc"])
        j = c["judas"]
        for part in ("MANIPULATION", "London's Judas swing",
                     "<dt>Opened</dt><dd>1.08520 at 06:00 UTC · 02:00 New York</dd>",
                     "<dt>Faked to</dt><dd>1.08288 at 08:00 UTC</dd>", "<dt>Turned</dt><dd>up</dd>",
                     "The false move that traps the early side", "London opened 1.0852, faked to 1.0829"):
            self.assertIn(part, j)
        d = c["d"]
        for part in ('<span class="sv-sig-side">DISTRIBUTION</span>',
                     "Back inside after the lows&#39; run · pointing up".replace("&#39;", "'"),
                     "<dt>Back inside</dt><dd>1.08510 at 12:00 UTC · 08:00 New York</dd>",
                     "<dt>Pointing</dt><dd>up, to the Asian high 1.08608 first</dd>",
                     "<dt>The draw</dt><dd>② 1.08954 · the same way</dd>",
                     "<dt>Odds</dt><dd>not yet judged (the po3 family)</dd>",
                     "The manipulation is done: the real move points up",
                     "nothing is drawn past the last bar",
                     "drawn at the first close back inside after the run&#39;s extreme".replace("&#39;", "'")):
            self.assertIn(part, d)
        self.assertIn("② 1.08000 · the other way: wait for them to agree", c["dOther"])
        self.assertIn("<dt>Odds</dt><dd>proven</dd>", c["dJudged"])
        self.assertIn("<dt>New York</dt><dd>08:30–16:00 New York · opens 12:30 UTC</dd>", c["dBefore"])
        self.assertIn("08:30–16:00 New York · open now", c["dDuring"])
        self.assertIn("08:30–16:00 New York · closed", c["dAfter"])
        self.assertNotIn("<img", c["hostile"])
        self.assertIn("&lt;img src=x", c["hostile"])

    # P18
    def test_the_arrow_has_a_floor_and_stays_on_the_pane(self):
        a = self.out["arrow"]
        self.assertAlmostEqual(a["short"]["y0"] - a["short"]["y1"], 16, places=9, msg="up, at least 16 px")
        self.assertAlmostEqual(a["shortDown"]["y1"] - a["shortDown"]["y0"], 16, places=9)
        self.assertIsNone(a["tailOff"])
        self.assertIsNone(a["xOff"])
        self.assertEqual(a["headOff"]["y1"], 2)
        self.assertAlmostEqual(a["headOff"]["y0"], toY(1.08441), places=9)

    # P19
    def test_draw_agreement(self):
        a = self.out["agree"]
        self.assertEqual((a["up"], a["down"]), ("agrees", "disagrees"))
        self.assertEqual(a["sideBelow"], "disagrees", "the leg's side before its price")
        self.assertEqual(a["sideNoPrice"], "agrees")
        self.assertEqual((a["noLeg"], a["noDir"], a["noMap"]), (None, None, None))

    # ── The acceptance fixes (2026-10-08) ─────────────────────────────────

    # P20
    def test_a_marker_on_the_swept_wick_lifts_the_diamond_onto_the_wick(self):
        """A position opened on the sweep bar puts its entry marker just
        beyond the swept wick, where the diamond was drawn: the diamond then
        sits on the wick's end (its far point on the tip), clear of the
        marker, and M is still named on it."""
        tip = toY(1.08288)
        mk = {"x0": 500, "x1": 590, "y0": tip + 1, "y1": tip + 31}
        g = self.out["marker"]
        s = g["po3"]["sweeps"][0]
        self.assertTrue(s["over"])
        self.assertAlmostEqual(s["cy"], tip - 4, places=9, msg="its far point on the wick's tip")
        drawn = {"x0": s["x"] - 4, "x1": s["x"] + 4, "y0": s["cy"] - 4, "y1": s["cy"] + 4}
        self.assertFalse(_meets(drawn, mk), "never under the money's marker")
        m = _label(g, "m")
        self.assertEqual(m["text"], "M · SWEEP  1.08288")
        self.assertTrue(_on_mark(m, g))
        self.assertFalse(_meets(m, mk))
        self.assertFalse(_meets(m, s["box"]))
        # ...a high's mirror: on the wick's end under the tip
        hs = self.out["markerHigh"]["po3"]["sweeps"][0]
        self.assertTrue(hs["over"])
        self.assertAlmostEqual(hs["cy"], toY(1.08712) + 4, places=9)
        # ...but never across a money row: there it stays where it was
        r = self.out["markerRow"]["po3"]["sweeps"][0]
        self.assertFalse(r["over"])
        self.assertAlmostEqual(r["cy"], tip + 6, places=9)
        # ...and without a marker it is beyond the wick, as specified
        self.assertFalse(self.out["free"]["po3"]["sweeps"][0]["over"])

    # P21
    def test_the_marks_stay_whole_on_the_pane(self):
        p = self.out["edge"]["po3"]
        s, a = p["sweeps"][0], p["arrow"]
        self.assertEqual(s["x"], 740 - 4 - 1, "the newest bar at the pane's edge: the diamond whole")
        self.assertLessEqual(s["box"]["x1"], 740)
        self.assertEqual(a["x"], 740 - 5, "the arrow's head whole")
        self.assertLessEqual(a["box"]["x1"], 740)
        left = self.out["edgeLeft"]["po3"]["sweeps"][0]
        self.assertEqual(left["x"], 5)
        self.assertGreaterEqual(left["box"]["x0"], 0)

    # P22
    def test_m_is_named_on_its_mark_so_the_letters_read_a_m_d(self):
        """The zoomed 1h: the LAST LOW ray's right-edge slot lies right of
        the D arrow. The chip that names M covers its diamond or starts
        beside it, so A, M and D read left to right."""
        g = self.out["zoom"]
        p = g["po3"]
        s, a = p["sweeps"][0], p["arrow"]
        chip = [c for c in g["chips"] if c.get("stage")][0]
        self.assertEqual(chip["text"], "M · SWEEP  1.08288")
        self.assertTrue(chip["x0"] <= s["x"] <= chip["x1"] or chip["x0"] <= s["box"]["x1"] + 3, chip)
        self.assertLess(chip["x0"], a["x"], "M starts before the D arrow, not right of it")
        d = _label(g, "d")
        self.assertEqual(d["text"], "D ▲ · ② DRAW")
        self.assertTrue(_on_mark(d, g))
        a_label = g["asia"]["label"]
        self.assertLess(a_label["x0"], chip["x0"])
        self.assertGreaterEqual(d["x0"], min(chip["x0"], s["x"]), "D never starts left of M")
        for c in g["chips"] + g["edges"]:
            self.assertFalse(_meets(c, s["box"]) or _meets(c, a["box"]), c["text"])

    # P23
    def test_a_role_chip_slides_left_of_today_s_mark_and_keeps_its_words(self):
        """The 4h HUNT chip: PR51's right-edge slot met today's diamond. It
        now ends just before the diamond with its full words, where the
        stub went before; without a stage the slot is PR51's."""
        g = self.out["roleSlide"]
        s = g["po3"]["sweeps"][0]
        hunt = [c for c in g["chips"] if c["id"] == HUNT_ID][0]
        self.assertEqual(hunt["text"], "EQL ×2 · ① HUNT  1.08226")
        self.assertFalse(_meets(hunt, s["box"]))
        self.assertAlmostEqual(hunt["x1"], s["box"]["x0"] - 1, places=9)
        bare = [c for c in self.out["roleBare"]["chips"] if c["id"] == HUNT_ID][0]
        self.assertEqual(bare["text"], hunt["text"])
        self.assertEqual(bare["x1"], 736, "PR51's right edge, unchanged without a stage")
        self.assertEqual((bare["y0"], bare["y1"]), (hunt["y0"], hunt["y1"]))

    # P24
    def test_the_forming_bar_is_spared_and_d_shortens_before_covering_candles(self):
        g = self.out["spare"]
        newest = {"x0": 600, "x1": 612, "y0": 0, "y1": 384}
        m = _label(g, "m")
        self.assertEqual(m["text"], "M · SWEEP  1.08288")
        self.assertFalse(_meets(m, newest), "the forming bar is spared first")
        self.assertTrue(_on_mark(m, g))
        self.assertTrue(m["bare"], "over the older candles: bare words, no plate")
        self.assertTrue(g["asia"]["label"]["bare"])
        self.assertFalse(self.out["free"]["asia"]["label"]["bare"], "a plate where no candle is under it")
        d = _label(self.out["dShort"], "d")
        self.assertEqual(d["text"], "D ▲", "the short words clear before the long ones cover a candle")
        self.assertFalse(d["bare"])

    # P25
    def test_a_mark_answers_as_drawn_before_the_level_shapes(self):
        h = self.out["hitDrawn"]
        self.assertIsNone(h["corner"], "the box's corner is not the diamond")
        self.assertEqual(h["cornerBox"]["id"], "sv-po3-m-low", "the box still reaches it (after the level shapes)")
        self.assertEqual(h["centre"]["part"], "mark")
        self.assertEqual(h["reach"]["id"], "sv-po3-m-low", "R + MARK_HIT from the centre")
        self.assertEqual(h["arrow"]["id"], "sv-po3-d")

    # P26
    def test_a_chip_that_names_m_keeps_its_plate_and_opens_it_over_the_forming_bar(self):
        """Bare violet words over the candles read '1.0?2?8' on the default
        1h (the harness's M · SWEEP  1.08288 over the 08:00 and 09:00
        bodies). The chip that names M keeps the level chip's style — its
        plate, its border in violet (§4.2) — wherever it sits. Over the
        forming bar alone (a run that holds, on its own bar) the plate
        leaves that bar's column open and the paint halos the words."""
        older = [c for c in self.out["foldOlder"]["chips"] if c.get("stage")][0]
        self.assertEqual(older["text"], "M · SWEEP  1.08288")
        self.assertNotIn("bare", older)
        self.assertNotIn("through", older, "over older candles the plate is whole, as PR51's chips")
        forming = [c for c in self.out["foldForming"]["chips"] if c.get("stage")][0]
        self.assertEqual(forming["text"], "M · SWEEP  1.08288")
        self.assertNotIn("bare", forming)
        self.assertEqual(forming["through"], {"x0": 650, "x1": 662}, "the forming bar's column, open")
        for key in ("dis", "man", "phone", "foldTight", "zoom"):
            for c in self.out[key]["chips"]:
                self.assertNotIn("bare", c, key)
                self.assertNotIn("through", c, key)

    # P27
    def test_on_a_four_hour_pane_m_ends_just_before_the_d_arrow_over_its_diamond(self):
        """The 4h levels view: the return bar is the very next bar, 4 px on,
        and the D arrow's box took PR51's LAST LOW slot — neither M nor the
        price was named. The chip that names M now also tries each slot
        ending just before the arrow: it ends over its own diamond, on PR51's
        row, clear of both marks."""
        g, free, bare = self.out["four"], self.out["fourFree"], self.out["fourBare"]
        s, a = g["po3"]["sweeps"][0], g["po3"]["arrow"]
        self.assertAlmostEqual(a["x"] - s["x"], 4.2, places=9, msg="the next 4h bar")
        m = [c for c in g["chips"] if c.get("stage")][0]
        self.assertEqual(m["text"], "M · SWEEP  1.08288")
        self.assertEqual(g["po3"]["folded"], {"low": LOW_ID})
        self.assertAlmostEqual(m["x1"], a["box"]["x0"] - 1, places=9, msg="ends just before the arrow")
        self.assertGreaterEqual(m["x1"], s["x"] - 4, "over its own diamond (its near point)")
        self.assertFalse(_meets(m, a["box"]))
        self.assertFalse(_meets(m, s["box"]))
        self.assertLess(m["y1"], s["tipY"], "on the candles' side of its ray")
        # without the arrow it is PR51's chip, slot for slot, renamed
        last = [c for c in bare["chips"] if c["id"] == LOW_ID][0]
        self.assertEqual(last["text"], "LAST LOW  1.08288")
        fm = [c for c in free["chips"] if c.get("stage")][0]
        self.assertEqual((fm["x1"], fm["y0"]), (last["x1"], last["y0"]))
        self.assertEqual(m["y0"], last["y0"], "PR51's row")

    # ── The review's findings (2026-10-15) ────────────────────────────────

    # P29
    def test_a_manipulation_day_s_diamond_is_hollow_even_after_one_return(self):
        """The server's back_at is the FIRST close back inside: a run that
        came back once and closed outside again reads manipulation with a
        back_at. The diamond follows the phase (spec §4.1: hollow while the
        run holds); an unclear day keeps each run's own return (P5)."""
        s = self.out["manBack"]["po3"]["sweeps"][0]
        self.assertFalse(s["filled"])
        self.assertTrue(self.out["dis"]["po3"]["sweeps"][0]["filled"])
        self.assertEqual([x["filled"] for x in self.out["unc"]["po3"]["sweeps"]], [True, False])

    # P30
    def test_a_level_forced_in_late_is_pr51_s_chip_never_a_second_m(self):
        """A phone's four chips taken by HUNT, DRAW and two nearer pools: the
        LAST LOW ray has no chip, and a hover on it forces one in late.
        That chip wore M (a second violet M beside the diamond's own, and a
        pointer moving onto it flickered it away). It is PR51's `LAST L`,
        slot for slot, and hits as a level."""
        rest, hot, pr51 = self.out["late"]["rest"], self.out["late"]["hot"], self.out["late"]["pr51"]
        self.assertEqual(len(rest["chips"]), 4)
        self.assertNotIn(LOW_ID, [c["id"] for c in rest["chips"]], "past the cap at rest")
        late = [c for c in hot["chips"] if c["id"] == LOW_ID]
        self.assertEqual(len(late), 1, "forced in when hovered")
        late = late[0]
        self.assertEqual(late["text"], "LAST L")
        self.assertNotIn("stage", late)
        self.assertNotIn("sweep", late)
        plain = [c for c in pr51["chips"] if c["id"] == LOW_ID][0]
        self.assertEqual([late[k] for k in ("text", "x0", "x1", "y0", "y1")],
                         [plain[k] for k in ("text", "x0", "x1", "y0", "y1")], "PR51's slot")
        self.assertEqual(hot["po3"]["folded"], {})
        self.assertLessEqual(len([c for c in hot["chips"] if c.get("stage")]), 0)
        self.assertEqual(self.out["late"]["hit"], {"id": LOW_ID, "item": True})

    # P31
    def test_the_chip_that_names_m_dims_as_the_stage(self):
        """The key's Power of Three switch (focus 'asia') shows the three
        stages: the folded M chip faded to .2 with the swings while the
        diamond and D stayed lit; the Swings switch did the reverse."""
        d = self.out["dims"]

        def fold(g):
            return [c for c in g["chips"] if c.get("stage")][0]
        asia, swing, hot = d["focusAsiaFold"], d["focusSwingFold"], d["focusSwingHot"]
        self.assertEqual(fold(asia)["text"], "M · SWEEP  1.08288")
        self.assertEqual(fold(asia)["k"], 1)
        self.assertEqual(asia["po3"]["sweeps"][0]["k"], 1)
        self.assertEqual(_label(asia, "d")["k"], 1)
        self.assertAlmostEqual(fold(swing)["k"], 0.2)
        self.assertAlmostEqual(swing["po3"]["sweeps"][0]["k"], 0.2)
        self.assertAlmostEqual(_label(swing, "d")["k"], 0.2)
        self.assertEqual(fold(hot)["k"], 1, "hovered: lit")
        # the other level chips keep PR51's dims under either focus
        hunt = [c for c in asia["chips"] if c["id"] == HUNT_ID][0]
        self.assertAlmostEqual(hunt["k"], 0.2)

    # P32
    def test_the_stage_cards_say_one_judas_swing(self):
        """words_for appends the old `judas` key's clause, the London 18 h
        before the range (F1, D1 pending); the M card already states the
        trading day's swing from stages.judas. The clause stays off the M
        and D cards; the rest of the sentence stays."""
        c = self.out["cards"]
        for key in ("mOldJudas", "dOldJudas"):
            self.assertNotIn("London&#39;s Judas swing: opened 100", c[key], key)
            self.assertNotIn("Judas swing: opened 100", c[key], key)
            self.assertIn("Power of Three (the ny am session", c[key], key)
            self.assertIn("the lows of the Asian range were run.", c[key], key)
        self.assertIn("<dt>Judas</dt><dd>London opened 1.08520, faked to 1.08288 at 08:00 UTC</dd>", c["mOldJudas"])
        self.assertIn("Power of Three (the ny am session", c["m"], "without the clause: as before")

    # P28
    def test_the_lifted_diamond_keeps_off_a_title_box(self):
        """The full views: the LONG marker holds the far side of the wick and
        the pinned signal's 'Stop' title is stacked over the wick's end; the
        diamond lifted there painted over the 'S'. It now keeps off the title
        boxes as a label does, and stays beyond the wick, under the marker."""
        tip = toY(1.08288)
        g = self.out["markerTitle"]
        s = g["po3"]["sweeps"][0]
        self.assertEqual(len(g["keep"]["titles"]), 1)
        lifted = {"x0": s["x"] - 5, "x1": s["x"] + 5, "y0": tip - 9, "y1": tip + 1}
        self.assertTrue(_meets(lifted, g["keep"]["titles"][0], GAP_X, GAP_Y),
                        "the wick's end lies under the title box")
        self.assertFalse(s["over"])
        self.assertAlmostEqual(s["cy"], tip + 6, places=9, msg="beyond the wick, under the marker")
        self.assertTrue(self.out["marker"]["po3"]["sweeps"][0]["over"], "no title there: lifted")


# ═══ The widget's real script against the fake chart ═════════════════════

PO3_SCENARIO = r"""
/* The Power of Three switch's phase: a recorded element inside the key's
   asia button (LEVELS_PATCH's El answers no querySelector). */
const phaseEl = new El('');
keyEls.asia.querySelector = function (sel) { return sel === '[data-role="phase"]' ? phaseEl : null; };
const phaseState = function () { return { text: phaseEl.textContent, title: phaseEl.title || '' }; };
const SCENES = {};
const X = function (t) { const i = BARS.findIndex(function (b) { return b.time === t; }); return 20 + i * 10; };

SCENES.main = async function (R) {
    const p0 = prim();
    R.prims = chart.series.map(function (s) { return [s.kind, primsOf(s)]; });
    R.others = otherLines();
    R.data = p0 ? { po3: p0.data.po3, asia: p0.data.asia } : null;
    renderLayer();
    R.geom = geom();
    R.ops = ops();
    R.texts = CTX.texts.slice();
    R.x = { l6: X(M.t.l6), l8: X(M.t.l8), n12: X(M.t.n12), n14: X(M.t.n14) };
    R.phase = phaseState();
    R.key = keyState();
};

SCENES.toggle = async function (R) {
    renderLayer();
    R.before = { geom: geom(), phase: phaseState() };
    keyClick('asia');
    renderLayer();
    R.after = { geom: geom(), phase: phaseState(), saved: savedPrefs(), key: keyState(),
                others: otherLines() };
};

SCENES.boot = async function (R) {
    renderLayer();
    R.geom = geom(); R.phase = phaseState(); R.key = keyState();
};

SCENES.phone = async function (R) {
    R.desk = phaseState();
    els[ID + '-container'].clientWidth = 400;
    await refresh(M.payload);
    renderLayer();
    R.phone = phaseState();
    R.geom = geom();
};

SCENES.cards = async function (R) {
    renderLayer();
    const g = geom();
    R.geom = g;
    const s = g.po3.sweeps[0], a = g.po3.arrow;
    move(s.x, s.cy, M.t.l8);
    R.diamond = cardState();
    R.diamondGlow = geom() && (renderLayer(), geom().po3.sweeps[0].hot);
    /* the level chip that names M (the folded LAST LOW), by its exact box */
    const fc = g.chips.filter(function (c) { return c.stage; })[0];
    R.chip = null;
    if (fc) { move((fc.x0 + fc.x1) / 2, (fc.y0 + fc.y1) / 2, M.t.l8); R.chip = cardState(); }
    move(a.x, (a.y0 + a.y1) / 2, M.t.n12);
    R.arrow = cardState();
    move(600, 30, M.t.n14);
    R.away = cardState();
    if (M.slY !== null) {
        move(s.x, M.slY, M.t.l8);
        R.sl = cardState();
    }
};

SCENES.tap = async function (R) {
    renderLayer();
    const a = geom().po3.arrow;
    click(a.x, (a.y0 + a.y1) / 2, M.t.n12);
    R.opened = cardState();
    click(a.x, (a.y0 + a.y1) / 2, M.t.n12);
    R.closed = cardState();
};

/* (2026-10-08) A finger on the HUNT band just beside the diamond, then on
   the diamond itself: the hunt's card, then M's. */
SCENES.tapBeside = async function (R) {
    renderLayer();
    const g = geom(), s = g.po3.sweeps[0];
    R.geom = g;
    R.at = { x: s.x - 4, y: M.huntY };
    click(s.x - 4, M.huntY, M.t.l8);
    R.band = cardState();
    click(s.x - 4, M.huntY, M.t.l8);
    R.bandClosed = cardState();
    click(s.x, s.cy, M.t.l8);
    R.mark = cardState();
};

/* (2026-10-08) A position opened on the sweep bar: its marker beyond the
   wick, the diamond on the wick's end, painted in the top pass. */
SCENES.passes = async function (R) {
    renderLayer();
    R.geom = geom();
    const p = prim();
    CTX.ops = []; CTX.texts = [];
    p.paneViews().filter(function (v) { return v.zOrder() === 'normal'; }).forEach(function (v) {
        const r = v.renderer(); if (r.drawBackground) r.drawBackground(TARGET); r.draw(TARGET); });
    R.back = ops();
    CTX.ops = []; CTX.texts = [];
    p.paneViews().filter(function (v) { return v.zOrder() === 'top'; }).forEach(function (v) {
        v.renderer().draw(TARGET); });
    R.top = ops();
};

/* (2026-10-08) The chip that names M, painted: the level chip's plate and
   violet border; over the forming bar (`through`) the plate leaves that
   column open and the words wear a bg halo — where the context strokes
   text at all (this fake has no strokeText until the scene lends one). */
SCENES.through = async function (R) {
    renderLayer();
    const p = prim();
    const m = p.geom.chips.filter(function (c) { return c.stage; })[0];
    R.chip = JSON.parse(JSON.stringify(m));
    const top = function () {
        CTX.ops = []; CTX.texts = [];
        p.paneViews().filter(function (v) { return v.zOrder() === 'top'; }).forEach(function (v) {
            v.renderer().draw(TARGET); });
        return ops();
    };
    R.whole = top();
    m.through = { x0: m.x0 + 20, x1: m.x0 + 30 };
    R.noHalo = top();
    CTX.strokeText = function () {
        CTX.ops.push({ op: 'strokeText', fill: CTX.fillStyle, stroke: CTX.strokeStyle, lw: CTX.lineWidth,
                       alpha: CTX.globalAlpha, args: Array.from(arguments) });
    };
    R.open = top();
    delete CTX.strokeText;
};

SCENES.swap = async function (R) {
    chartType('line');
    for (let i = 0; i < 6; i++) await flush();
    renderLayer();
    R.ops = log.ops.slice();
    R.prims = chart.series.map(function (s) { return [s.kind, primsOf(s)]; });
    R.stages = prim() ? !!(prim().data.po3 && prim().data.po3.stages) : null;
    R.geom = geom();
};

SCENES.noPrims = async function (R) {
    R.others = otherLines();
    R.lines = lineOpts();
    R.phase = phaseState();
};

SCENES.pin = async function (R) {
    renderLayer();
    const money = function () { return lineOpts().filter(function (l) { return ['LONG 1000', 'SL', 'TP'].indexOf(l.title) >= 0; }); };
    R.before = { geom: geom(), money: money() };
    click(M.sigX, 200, M.t.sig);
    renderLayer();
    R.after = { geom: geom(), money: money(), cls: card.className, sigLines: sigLines() };
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

PO3_HARNESS = WIDGET_PRELUDE + LEVELS_PATCH + PO3_SCENARIO
T = {"l6": _utc(2026, 10, 7, 6), "l8": _utc(2026, 10, 7, 8), "n12": _utc(2026, 10, 7, 12),
     "n14": _utc(2026, 10, 7, 14), "sig": _utc(2026, 10, 7, 9)}


def _hourly_bars(step_hours=1):
    """2026-10-06 00:00Z to 2026-10-07 14:00Z: the harness day. Today's
    Asian bars inside 1.08441-1.08608, the 08:00Z bar's low 1.08288, the
    lows held under the range until the 12:00Z bar closes back inside at
    1.08510; every close today within 1.0838-1.0860."""
    start = datetime(2026, 10, 6, tzinfo=dt_timezone.utc)
    today = {0: (1.0852, 1.0858, 1.0846, 1.0853), 1: (1.0853, 1.0859, 1.0848, 1.0855),
             2: (1.0855, 1.0860, 1.0849, 1.0851), 3: (1.0851, 1.0856, 1.0845, 1.0850),
             4: (1.0850, 1.0853, 1.0846, 1.0848), 5: (1.0848, 1.0851, 1.0845, 1.0846),
             6: (1.0846, 1.0848, 1.0838, 1.0840), 7: (1.0840, 1.0842, 1.0833, 1.0838),
             8: (1.0838, 1.0840, 1.08288, 1.0839), 9: (1.0839, 1.0843, 1.0836, 1.0841),
             10: (1.0841, 1.0844, 1.0838, 1.0842), 11: (1.0842, 1.0846, 1.0839, 1.0843),
             12: (1.0843, 1.0853, 1.0841, 1.0851), 13: (1.0851, 1.0857, 1.0849, 1.0855),
             14: (1.0855, 1.0858, 1.0851, 1.08552)}
    bars, t = [], start
    end = datetime(2026, 10, 7, 14, tzinfo=dt_timezone.utc)
    i = 0
    while t <= end:
        if t.date().isoformat() == "2026-10-07":
            o, h, l, c = today[t.hour]
        else:
            c = round(1.0850 + 0.0004 * ((i % 5) - 2) / 2, 5)
            o, h, l = c - 0.0001, c + 0.0005, c - 0.0005
        bars.append({"time": int(t.timestamp()), "open": o, "high": h, "low": l, "close": c,
                     "volume": 0})
        t += timedelta(hours=1)
        i += 1
    if step_hours == 1:
        return bars
    out = []
    for b in bars:
        if (b["time"] // 3600) % step_hours == 0 or not out:
            out.append(dict(b))
        else:
            k = out[-1]
            k["high"], k["low"], k["close"] = max(k["high"], b["high"]), min(k["low"], b["low"]), b["close"]
    return out


def _quarter_bars(end=(14, 0), late_return=True, same_bar=False):
    """The harness day on 15min bars (2026-10-15), 2026-10-06 22:00Z to
    `end` on the 7th (the fake pane is 740 px, 10 px a bar: the 7th's bars
    must fit on it): each hour of _hourly_bars as four quarters inside it.
    The 08:00Z hour prints its low 1.08288 on the 08:30 quarter alone (the
    others 1.0836). London's first quarter opens 1.0852 (JUDAS.open) and
    the 06:30 quarter's LOW 1.08515 is the nearest to that open. The 12:00Z
    hour closes back inside on its 12:45 quarter alone when `late_return`
    (its first three quarters close 1.0843, under the Asian low 1.08441),
    on every quarter otherwise. `same_bar`: the 08:45 quarter closes back
    inside at 1.0846, so the sweep's hour is itself the return."""
    start = datetime(2026, 10, 6, 22, tzinfo=dt_timezone.utc)
    end_t = datetime(2026, 10, 7, end[0], end[1], tzinfo=dt_timezone.utc)
    today = {h: v for h, v in zip(range(15), [b for b in _hourly_bars() if b["time"] >= _utc(2026, 10, 7)])}
    bars, t, i = [], start, 0
    while t <= end_t:
        if t.date().isoformat() == "2026-10-07":
            h, q = t.hour, t.minute // 15
            b = today[h]
            o, hi, lo, c = b["open"], b["high"], b["low"], b["close"]
            if h == 6:
                o, hi, lo, c = [(1.0852, 1.0853, 1.0846, 1.0848), (1.0848, 1.0850, 1.0838, 1.0840),
                                (1.0853, 1.0856, 1.08515, 1.0854), (1.0854, 1.0855, 1.0838, 1.0840)][q]
            elif h == 8:
                lo = 1.08288 if q == 2 else 1.0836
                o, hi, c = 1.0838, 1.0840, 1.0838
                if q == 3:
                    hi, c = (1.0847, 1.0846) if same_bar else (1.0840, 1.0839)
            elif same_bar and 9 <= h <= 12:
                o, hi, lo, c = 1.0846, 1.0853, 1.0845, 1.0851 if h == 12 else 1.0847
            elif h == 12:
                o, hi, lo, c = (1.0842, 1.0846, 1.0840, 1.0843) if late_return and q < 3 \
                    else (1.0843, 1.0853, 1.0841, 1.0851)
        else:
            c = round(1.0850 + 0.0004 * ((i % 5) - 2) / 2, 5)
            o, hi, lo = c - 0.0001, c + 0.0005, c - 0.0005
        bars.append({"time": int(t.timestamp()), "open": o, "high": hi, "low": lo, "close": c,
                     "volume": 0})
        t += timedelta(minutes=15)
        i += 1
    return bars


def _xq(bars, h, m=0):
    """The fake chart's x of the bar opening at h:m on the 7th (20 + 10 i)."""
    return 20 + 10 * [b["time"] for b in bars].index(_utc(2026, 10, 7, h, m))


def _po3_payload(stages=True, positions=None, bars=None, signals=None):
    p = _levels_payload(positions=positions)
    p["timeframe"] = "1h"
    p["bars"] = bars if bars is not None else _hourly_bars()
    p["signals"] = signals if signals is not None else []
    po3 = p["positioning"]["po3"]
    po3["words"] = WORDS
    po3["session"] = "ny_am"
    po3["run"] = {"below": True, "above": False, "low": 1.08288, "high": None}
    po3["odds"] = {"verdict": "unjudged", "why": "x"}
    if stages:
        po3["stages"] = copy.deepcopy(STAGES)
    return p


def _po3_run(mode, payload=None, prefs=None, coarse=False, no_prims=False, extra=None, **ctx):
    ctx.setdefault("timeframe", "1h")
    pure, main = _blocks(widget(**ctx))
    m = {"mode": mode, "pure": pure, "main": main,
         "payload": payload if payload is not None else _po3_payload(),
         "prefs": prefs, "prefKey": PREF_KEY, "coarse": coarse, "noPrims": no_prims,
         "t": T, "slY": None, "sigX": None, "huntY": None}
    m.update(extra or {})
    return _node(PO3_HARNESS, m)


@unittest.skipUnless(NODE, "node is not installed")
class ThePo3WidgetTests(SimpleTestCase):
    """The widget's real script, the fake chart, LEVELS_PATCH unedited."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.main = _po3_run("main")

    # W1
    def test_the_stages_ride_the_level_layer_and_add_no_price_line(self):
        r = self.main
        self.assertEqual(r["prims"], [["candle", 1], ["hist", 0]])
        self.assertEqual(r["others"], ["LONG 1000", "SL", "TP"])
        self.assertEqual(r["data"]["po3"]["stages"], STAGES)
        self.assertEqual((r["data"]["po3"]["phase"], r["data"]["po3"]["direction"]), ("distribution", "up"))
        self.assertEqual(set(r["data"]["asia"]), {"high", "low", "opened", "closed"})
        x = r["x"]
        p = r["geom"]["po3"]
        bands = {b["id"]: b for b in p["bands"]}
        self.assertEqual((bands["sv-po3-london"]["x0"], bands["sv-po3-london"]["x1"]), (x["l6"] - 5, x["l8"] + 5))
        self.assertEqual((bands["sv-po3-ny"]["x0"], bands["sv-po3-ny"]["x1"]), (x["n12"] - 5, x["n14"] + 5),
                         "from the bar holding 08:30 New York to the newest bar, nothing past it")
        self.assertEqual(p["sweeps"][0]["x"], x["l8"])
        self.assertAlmostEqual(p["sweeps"][0]["tipY"], y_of(1.08288), places=9)
        self.assertTrue(p["sweeps"][0]["filled"])
        self.assertEqual(p["arrow"]["x"], x["n12"])
        self.assertAlmostEqual(p["arrow"]["y0"], y_of(1.08441), places=9)
        self.assertAlmostEqual(p["arrow"]["y1"], y_of(1.08608), places=9)
        self.assertIsNone(p["judas"], "the detector names none on the harness day")
        self.assertLessEqual(max(b["x1"] for b in p["bands"]), x["n14"] + 5)

    # W2
    def test_shapes_paint_under_and_labels_over(self):
        ops, texts = self.main["ops"], self.main["texts"]
        violet = "#a878f0"
        top0 = next(i for i, o in enumerate(ops) if o["op"] == "fillText")
        bands = [o for o in ops if o["op"] == "fillRect" and o["fill"] == violet
                 and abs(o["alpha"] - 0.045) < 1e-9]
        self.assertEqual(len(bands), 2, "London and New York, the faint columns")
        for o in bands:
            self.assertEqual((o["args"][1], o["args"][3]), (0, 384), "full height")
        idx = [i for i, o in enumerate(ops) if o in bands]
        self.assertTrue(all(i < top0 for i in idx))
        # the diamond (filled), the arrow's shaft and head: violet, all before the top pass
        fills = [i for i, o in enumerate(ops) if o["op"] == "fill" and o["fill"] == violet]
        strokes = [i for i, o in enumerate(ops) if o["op"] == "stroke" and o["stroke"] == violet]
        self.assertGreaterEqual(len(fills), 2, "the diamond and the arrow's head")
        self.assertTrue(strokes, "the arrow's shaft")
        self.assertTrue(all(i < top0 for i in fills + strokes))
        # the bands come before every other level shape (the Asia box's fill)
        box = next(i for i, o in enumerate(ops) if o["op"] == "fillRect" and o["fill"] == violet
                   and abs(o["alpha"] - 0.09) < 1e-9)
        self.assertLess(max(idx), box)
        for t in ("A · ASIA", "M · SWEEP  1.08288", "D ▲ · ② DRAW"):
            self.assertIn(t, texts)
        self.assertNotIn("ASIA", texts)
        self.assertNotIn("LAST LOW  1.08288", texts)
        stage_ops = [i for i, o in enumerate(ops)
                     if o["op"] in ("fill", "stroke") and (o["fill"] == violet or o["stroke"] == violet)]
        self.assertTrue(all(i < top0 for i in stage_ops), "no stage shape in the top pass")

    # W3
    def test_four_hour_frames_keep_the_marks_and_drop_the_bands(self):
        bars = _hourly_bars(step_hours=4)
        out = _po3_run("boot", payload=_po3_payload(bars=bars), timeframe="4h")
        p = out["geom"]["po3"]
        self.assertEqual(p["bands"], [])
        self.assertEqual(len(p["sweeps"]), 1)
        self.assertIsNotNone(p["arrow"])
        self.assertEqual(out["geom"]["asia"]["label"]["text"], "A · ASIA")
        daily = _po3_run("boot", payload=_po3_payload(), timeframe="1d")
        self.assertIsNone(daily["geom"]["po3"])
        self.assertEqual(daily["phase"]["text"], "D ▲ distribution", "the key names the phase on a daily frame")

    # W4
    def test_the_power_of_three_switch_persists(self):
        out = _po3_run("toggle")
        self.assertIsNotNone(out["before"]["geom"]["po3"])
        after = out["after"]
        self.assertIs(after["saved"]["indicators"]["lvl_asia"], False)
        self.assertIsNone(after["geom"]["po3"])
        self.assertIsNone(after["geom"]["asia"])
        self.assertEqual(after["phase"]["text"], "D ▲ distribution", "the phase still said while hidden")
        self.assertEqual(after["key"]["keys"]["asia"]["pressed"], "false")
        self.assertEqual(after["others"], ["LONG 1000", "SL", "TP"])
        again = _po3_run("boot", prefs=after["saved"])
        self.assertIsNone(again["geom"]["po3"])
        self.assertIsNone(again["geom"]["asia"])
        self.assertEqual(again["phase"]["text"], "D ▲ distribution")
        self.assertEqual(again["key"]["keys"]["asia"]["pressed"], "false")

    # W5
    def test_the_key_names_the_phase(self):
        self.assertEqual(self.main["phase"], {"text": "D ▲ distribution", "title": WORDS})
        out = _po3_run("phone")
        self.assertEqual(out["desk"]["text"], "D ▲ distribution")
        self.assertEqual(out["phone"]["text"], "D▲")
        self.assertEqual(out["geom"]["asia"]["label"]["text"], "A")
        old = _po3_run("boot", payload=_po3_payload(stages=False))
        self.assertEqual(old["phase"]["text"], "D ▲ distribution", "the key reads po3, stages or not")

    # W6
    def test_hover_and_tap_open_the_stage_cards(self):
        out = _po3_run("cards")
        d = out["diamond"]
        self.assertFalse(d["hidden"])
        self.assertEqual(d["cls"], "sv-sig-card sv-sig-card--level sv-sig-card--asia")
        for part in ("MANIPULATION", "Sweep of the Asian lows", "08:00 UTC · 04:00 New York, London",
                     "1.08510 at 12:00 UTC · 08:00 New York"):
            self.assertIn(part, d["html"])
        self.assertTrue(out["diamondGlow"])
        # the level chip that names M (the folded LAST LOW, spec F4): the
        # only path from a chip to the M card is stageHit's `lc.stage`
        chip = out["chip"]
        self.assertIsNotNone(chip, "the harness day folds M into the LAST LOW chip")
        self.assertFalse(chip["hidden"])
        self.assertEqual(chip["cls"], "sv-sig-card sv-sig-card--level sv-sig-card--asia")
        self.assertIn("MANIPULATION", chip["html"])
        self.assertIn("Sweep of the Asian lows", chip["html"])
        self.assertNotIn("recent low", chip["html"])
        a = out["arrow"]
        self.assertIn("DISTRIBUTION", a["html"])
        self.assertIn("pointing up", a["html"])
        self.assertIn("② 1.08954 · the same way", a["html"])
        self.assertTrue(out["away"]["hidden"])
        tap = _po3_run("tap", coarse=True)
        self.assertFalse(tap["opened"]["hidden"])
        self.assertIn("DISTRIBUTION", tap["opened"]["html"])
        self.assertIn("not yet judged", tap["opened"]["html"])
        self.assertTrue(tap["closed"]["hidden"], "a second tap closes it")
        # Money first: an SL on the diamond's row opens the position's card.
        pos = dict(_payload()["positions"][0], stop=1.08258)
        money = _po3_run("cards", payload=_po3_payload(positions=[pos]),
                         extra={"slY": y_of(1.08258)})
        self.assertFalse(money["sl"]["hidden"])
        self.assertEqual(money["sl"]["cls"], "sv-sig-card sv-sig-card--bull")
        self.assertNotIn("MANIPULATION", money["sl"]["html"])

    # W7
    def test_an_old_reply_draws_the_pr51_box(self):
        out = _po3_run("main", payload=_po3_payload(stages=False))
        self.assertIsNone(out["data"]["po3"])
        self.assertIsNone(out["geom"]["po3"])
        self.assertEqual(out["geom"]["asia"]["label"]["text"], "ASIA")
        self.assertIn("ASIA", out["texts"])
        self.assertIn("LAST LOW  1.08288", out["texts"])

    # W8
    def test_a_type_switch_keeps_the_stages(self):
        out = _po3_run("swap")
        ops = out["ops"]
        detach = [o for o in ops if o["op"] == "detach" and o["kind"] == "candle"]
        removed = [o for o in ops if o["op"] == "removeSeries" and o["kind"] == "candle"]
        self.assertEqual((len(detach), len(removed)), (1, 1))
        self.assertLess(detach[0]["order"], removed[0]["order"])
        self.assertEqual(out["prims"], [["hist", 0], ["line", 1]])
        self.assertTrue(out["stages"])
        self.assertEqual(len(out["geom"]["po3"]["sweeps"]), 1)

    # W9
    def test_without_primitives_only_the_two_asia_lines(self):
        out = _po3_run("noPrims", no_prims=True)
        self.assertEqual(out["others"], ["LONG 1000", "SL", "TP", "", ""])
        self.assertEqual([l["price"] for l in out["lines"][3:]], [1.08608, 1.08441])
        self.assertEqual(out["phase"]["text"], "D ▲ distribution")

    # W10
    def test_a_pin_dims_the_stages_never_the_money(self):
        sig = dict(_payload()["signals"][0], id=21, at=T["sig"] + 1800)
        bars = _hourly_bars()
        x = 20 + [b["time"] for b in bars].index(T["sig"]) * 10
        out = _po3_run("pin", payload=_po3_payload(signals=[sig]), extra={"sigX": x})
        self.assertIn("is-pinned", out["after"]["cls"])
        self.assertEqual(len(out["after"]["sigLines"]), 3)
        p = out["after"]["geom"]["po3"]
        shapes = p["bands"] + p["sweeps"] + [p["arrow"]]
        for s in shapes:
            self.assertAlmostEqual(s["k"], 0.55, msg=s["id"])
        for s in out["before"]["geom"]["po3"]["bands"]:
            self.assertEqual(s["k"], 1)
        self.assertEqual(out["after"]["money"], out["before"]["money"])
        self.assertEqual(len(out["before"]["money"]), 3)

    # W11 (2026-10-08 acceptance, PR51 L§7.3's tap probe)
    def test_a_finger_on_the_hunt_band_beside_the_diamond_opens_the_hunt(self):
        """The phone probe's tap on the HUNT pool ran through the diamond's
        box corner and opened M. A stage mark now answers as drawn (+2 px)
        before the level shapes, so the band's tap opens the hunt; a tap on
        the diamond still opens M."""
        y_hunt = y_of(1.08214)                 # inside the HUNT band (1.08211-1.08241)
        out = _po3_run("tapBeside", coarse=True, extra={"huntY": y_hunt})
        g = out["geom"]
        s = g["po3"]["sweeps"][0]
        hunt = [b for b in g["bands"] if b["id"] == HUNT_ID][0]
        self.assertLessEqual(hunt["x0"], out["at"]["x"], "the band runs under the tap")
        self.assertLessEqual(hunt["y0"], y_hunt)
        self.assertLessEqual(y_hunt, hunt["y1"])
        box = s["box"]
        self.assertTrue(abs(y_hunt - box["y1"]) < 12, "a finger's 12 px from the diamond's box")
        self.assertFalse(out["band"]["hidden"])
        self.assertNotIn("MANIPULATION", out["band"]["html"])
        self.assertIn("equal lows", out["band"]["html"])
        self.assertTrue(out["bandClosed"]["hidden"], "a second tap closes it")
        self.assertFalse(out["mark"]["hidden"])
        self.assertIn("MANIPULATION", out["mark"]["html"])

    # W12
    def test_a_position_on_the_sweep_bar_keeps_the_diamond_in_sight(self):
        pos = dict(_payload()["positions"][0], opened_at=T["l8"], entry=1.08395, stop=1.08185, tp=1.0894)
        out = _po3_run("passes", payload=_po3_payload(positions=[pos]))
        s = out["geom"]["po3"]["sweeps"][0]
        self.assertTrue(s["over"], "the entry marker holds the far side of the wick")
        self.assertAlmostEqual(s["cy"], y_of(1.08288) - 4, places=9)
        violet = "#a878f0"
        back = [o for o in out["back"] if o["op"] == "fill" and o["fill"] == violet]
        top = [o for o in out["top"] if o["op"] == "fill" and o["fill"] == violet]
        self.assertEqual(len(top), 1, "the diamond, over its candle")
        self.assertEqual(len(back), 1, "the arrow's head alone stays under the candles")
        self.assertEqual(out["top"].index(top[0]), min(i for i, o in enumerate(out["top"]) if o["op"] == "fill"),
                         "under every chip and label")

    # ── Frames finer than the read (2026-10-15) ───────────────────────────

    def _fine(self, bars, stages=None, mode="boot", **po3):
        p = _po3_payload(bars=bars)
        p["timeframe"] = "15min"
        if stages is not None:
            p["positioning"]["po3"]["stages"] = stages
        p["positioning"]["po3"].update(po3)
        return _po3_run(mode, payload=p, timeframe="15min")

    # W14
    def test_a_finer_chart_puts_each_mark_on_the_bar_that_printed_it(self):
        """A 15min chart under the 1h read (spec §4.5): the diamond on the
        quarter that printed the hour's low, the London band edge to edge
        over its quarters, and New York's band only once New York has a
        bar (§4.1 ³, F5): the tape cut at 12:15Z draws the D arrow and no
        New York band; one more quarter, and the band starts on it."""
        bars = _quarter_bars(end=(12, 15), late_return=False)
        p = self._fine(bars)["geom"]["po3"]
        self.assertEqual(p["sweeps"][0]["x"], _xq(bars, 8, 30), "the 08:30 quarter printed 1.08288")
        self.assertAlmostEqual(p["sweeps"][0]["tipY"], y_of(1.08288), places=9)
        bands = {b["id"]: b for b in p["bands"]}
        self.assertEqual(list(bands), ["sv-po3-london"], "New York has no bar yet")
        self.assertEqual((bands["sv-po3-london"]["x0"], bands["sv-po3-london"]["x1"]),
                         (_xq(bars, 6, 0) - 5, _xq(bars, 8, 45) + 5))
        self.assertIsNotNone(p["arrow"], "the return is drawn inside London's quarters")
        self.assertEqual(p["arrow"]["x"], _xq(bars, 12, 0), "the 12:00 quarter closed back inside")
        bars = _quarter_bars(end=(12, 30), late_return=False)
        p = self._fine(bars)["geom"]["po3"]
        bands = {b["id"]: b for b in p["bands"]}
        self.assertEqual(list(bands), ["sv-po3-london", "sv-po3-ny"])
        self.assertEqual((bands["sv-po3-ny"]["x0"], bands["sv-po3-ny"]["x1"]),
                         (_xq(bars, 12, 30) - 5, _xq(bars, 12, 30) + 5))

    # W15
    def test_the_d_arrow_stands_on_the_first_close_back_inside(self):
        """The server's back_at is the read bar's OPEN. On a 15min chart the
        arrow stood on the hour's first quarter, which closed under the
        range, and when the sweep's own hour came back (back_at == at, the
        classic London candle) it stood LEFT of the diamond: A, D, M. It
        stands on the first quarter at or after the diamond whose close is
        back inside: the 12:45 quarter here; the 08:45 quarter after the
        08:30 diamond on the same-bar day."""
        bars = _quarter_bars()
        p = self._fine(bars)["geom"]["po3"]
        self.assertEqual(p["sweeps"][0]["x"], _xq(bars, 8, 30))
        self.assertEqual(p["arrow"]["x"], _xq(bars, 12, 45), "the 12:00, 12:15 and 12:30 quarters closed under")
        at = [b for b in bars if b["time"] == _utc(2026, 10, 7, 12, 45)][0]
        self.assertGreater(at["close"], 1.08441)
        self.assertAlmostEqual(p["arrow"]["y0"], y_of(1.08441), places=9)
        self.assertAlmostEqual(p["arrow"]["y1"], y_of(1.08608), places=9)
        bars = _quarter_bars(same_bar=True)
        st = copy.deepcopy(STAGES)
        st["sweeps"][0].update(back_at=st["sweeps"][0]["at"], back_close_at=st["sweeps"][0]["at"] + 3600,
                               back_price=1.0846, back_ny="04:00")
        p = self._fine(bars, stages=st)["geom"]["po3"]
        self.assertEqual(p["sweeps"][0]["x"], _xq(bars, 8, 30))
        self.assertEqual(p["arrow"]["x"], _xq(bars, 8, 45), "the quarter that came back, after the diamond")
        self.assertGreater(p["arrow"]["x"], p["sweeps"][0]["x"], "never D before M")
        # the same tape on 1h: the one bar is both, as W1 has it
        hourly = _po3_payload(bars=_hourly_bars())
        hourly["positioning"]["po3"]["stages"] = st
        p1 = _po3_run("boot", payload=hourly)["geom"]["po3"]
        self.assertEqual(p1["arrow"]["x"], p1["sweeps"][0]["x"])

    # W16
    def test_no_chart_bar_in_the_read_s_bar_draws_no_mark(self):
        """The 15min tape is another feed's (yfinance or Binance, 240 bars):
        a chart with no London or early New York bars is reachable. The
        marks stood on the last Asian bar, inside the A box, at a price it
        never traded. With nowhere honest to stand, the diamond, the arrow
        and the Judas line draw nothing, as spanX's band already did; the
        key still names the phase and the ray keeps PR51's chip."""
        bars = [b for b in _quarter_bars()
                if not (_utc(2026, 10, 7, 4) <= b["time"] < _utc(2026, 10, 7, 13))]
        st = copy.deepcopy(STAGES)
        st["judas"] = copy.deepcopy(JUDAS)
        out = self._fine(bars, stages=st, mode="main")
        p = out["geom"]["po3"]
        self.assertEqual((p["sweeps"], p["arrow"], p["judas"], p["labels"]), ([], None, None, []))
        self.assertEqual([(b["id"], b["x0"]) for b in p["bands"]], [("sv-po3-ny", _xq(bars, 13, 0) - 5)])
        self.assertEqual(out["phase"]["text"], "D ▲ distribution")
        self.assertIn("LAST LOW  1.08288", out["texts"])
        self.assertFalse([t for t in out["texts"] if t.startswith("M") or t.startswith("D ")])
        self.assertEqual(out["geom"]["asia"]["label"]["text"], "A · ASIA")

    # W17
    def test_the_judas_line_is_built_from_the_server_s_swing(self):
        """stages.judas -> geom.po3.judas: from the chart bar holding
        London's open at the open price to the bar that printed the extreme.
        On 15min the open end stood on the 06:30 quarter, whose LOW was the
        nearest to the open price (the open is no low); it stands on the
        06:00 quarter, and the extreme on the 08:30 quarter."""
        p = _po3_payload()
        p["positioning"]["po3"]["stages"]["judas"] = copy.deepcopy(JUDAS)
        out = _po3_run("main", payload=p)
        j = out["geom"]["po3"]["judas"]
        self.assertEqual((j["x0"], j["x1"]), (out["x"]["l6"], out["x"]["l8"]))
        self.assertAlmostEqual(j["y0"], y_of(1.0852), places=9)
        self.assertAlmostEqual(j["y1"], y_of(1.08288), places=9)
        self.assertEqual(j["id"], "sv-po3-judas")
        bars = _quarter_bars()
        st = copy.deepcopy(STAGES)
        st["judas"] = copy.deepcopy(JUDAS)
        j = self._fine(bars, stages=st)["geom"]["po3"]["judas"]
        self.assertEqual((j["x0"], j["x1"]), (_xq(bars, 6, 0), _xq(bars, 8, 30)))
        # a SHORT swing's extreme is a high: the quarter whose high is nearest
        st["judas"].update(direction="SHORT", extreme=1.0856, extreme_at=_utc(2026, 10, 7, 6))
        j = self._fine(bars, stages=st)["geom"]["po3"]["judas"]
        self.assertEqual((j["x0"], j["x1"]), (_xq(bars, 6, 0), _xq(bars, 6, 30)))
        self.assertAlmostEqual(j["y1"], y_of(1.0856), places=9)

    # W18
    def test_a_high_run_s_arrow_mirrors_from_the_stages(self):
        """A down day from the server's shape: the arrow from the Asian high
        (the swept edge) down to the Asian low, the diamond over the high."""
        p = _po3_payload()
        po3 = p["positioning"]["po3"]
        po3["direction"] = "down"
        po3["run"] = {"below": False, "above": True, "low": None, "high": 1.08712}
        po3["stages"]["sweeps"][0].update(side="high", edge=1.08608, price=1.08712)
        out = _po3_run("boot", payload=p)
        g = out["geom"]["po3"]
        a, s = g["arrow"], g["sweeps"][0]
        self.assertEqual((a["dir"], a["side"]), ("down", "high"))
        self.assertAlmostEqual(a["y0"], y_of(1.08608), places=9)
        self.assertAlmostEqual(a["y1"], y_of(1.08441), places=9)
        self.assertEqual(a["x"], 20 + [b["time"] for b in p["bars"]].index(T["n12"]) * 10)
        self.assertEqual((s["side"], s["filled"]), ("high", True))
        self.assertAlmostEqual(s["tipY"], y_of(1.08712), places=9)
        self.assertLess(s["cy"], s["tipY"], "over the high")
        self.assertEqual(out["phase"]["text"], "D ▼ distribution")

    # W19
    def test_the_d_label_names_the_draw_only_with_a_price(self):
        """drawAgrees answers 'agrees' for a draw leg with a side and no
        price (P19); the label carries ② DRAW only when the leg has a price
        to name (spec §4.3)."""
        p = _po3_payload()
        path = p["positioning"]["path"]
        p["positioning"]["path"] = [l for l in path if l.get("leg") != "draw"] + [{"leg": "draw", "side": "above"}]
        out = _po3_run("main", payload=p)
        self.assertNotIn("D ▲ · ② DRAW", out["texts"])
        self.assertIn("D ▲", out["texts"])
        self.assertIn("D ▲ · ② DRAW", self.main["texts"], "with the price: named")

    # W13
    def test_the_chip_that_names_m_wears_its_plate_and_opens_it_over_the_forming_bar(self):
        """Bare, its price over the bars read '1.0?2?8'. The chip that names
        M paints as every level chip — bg plate at .85, 1 px border, words —
        in violet. Over the forming bar the plate leaves that column open
        and the words are haloed in the bg (only where the context strokes
        text: a context without strokeText paints the rest unharmed)."""
        out = _po3_run("through")
        violet, bg = "#a878f0", "#030806"
        c = out["chip"]
        self.assertEqual((c["text"], c["stage"]), ("M · SWEEP  1.08288", "m"))
        self.assertNotIn("bare", c)

        def jr(v):                                     # JS Math.round
            return math.floor(v + 0.5)
        x0, x1, y0, y1 = jr(c["x0"]), jr(c["x1"]), jr(c["y0"]), jr(c["y1"])

        def plates(ops):
            return [o["args"] for o in ops if o["op"] == "fillRect" and o["fill"] == bg
                    and o["args"][1] == y0 and o["args"][3] == y1 - y0
                    and x0 <= o["args"][0] < x1]

        def words(ops):
            return [i for i, o in enumerate(ops) if o["op"] == "fillText" and o["args"][0] == c["text"]]
        whole = out["whole"]
        self.assertEqual(plates(whole), [[x0, y0, x1 - x0, y1 - y0]], "one plate, the chip's own")
        for o in [o for o in whole if o["op"] == "fillRect" and o["args"] == [x0, y0, x1 - x0, y1 - y0]]:
            self.assertAlmostEqual(o["alpha"], 0.85)
        self.assertTrue([o for o in whole if o["op"] == "strokeRect" and o["stroke"] == violet
                         and o["args"][0] == x0 + 0.5], "the violet border")
        [w] = words(whole)
        self.assertEqual(whole[w]["fill"], violet)
        o0, o1 = jr(c["x0"] + 20), jr(c["x0"] + 30)
        for key in ("open", "noHalo"):
            ops = out[key]
            self.assertEqual(plates(ops), [[x0, y0, o0 - x0, y1 - y0], [o1, y0, x1 - o1, y1 - y0]],
                             (key, "the plate around the forming bar's column"))
            self.assertTrue([o for o in ops if o["op"] == "strokeRect" and o["stroke"] == violet
                             and o["args"][0] == x0 + 0.5], (key, "the border whole"))
            self.assertEqual(len(words(ops)), 1, key)
        halo = [i for i, o in enumerate(out["open"]) if o["op"] == "strokeText"]
        self.assertEqual(len(halo), 1)
        h = out["open"][halo[0]]
        self.assertEqual((h["args"][0], h["stroke"]), (c["text"], bg))
        self.assertLess(halo[0], words(out["open"])[0], "the halo under the words")
        self.assertFalse([o for o in out["noHalo"] if o["op"] == "strokeText"])


# ═══ The wiring ══════════════════════════════════════════════════════════

class ThePo3WiringTests(SimpleTestCase):

    def setUp(self):
        self.src = widget_source().replace("\r\n", "\n")

    def _method(self, name):
        i = self.src.index("LevelLayer.prototype.%s = function" % name)
        return self.src[i:self.src.index("\n    };", i)]

    def test_the_key_names_the_power_of_three(self):
        html = widget()
        lvl = html.index('id="t-lvl-legend"')
        block = html[lvl:html.index("</div>", lvl)]
        self.assertEqual(re.findall(r'data-lvl="([a-z]+)"', block),
                         ["levels", "below", "above", "pool", "swing", "asia", "round", "all"])
        asia = re.search(r'<button[^>]*data-lvl="asia"[^>]*>.*?</button>', block, re.S).group(0)
        self.assertIn("Power of Three", asia)
        self.assertIn('<b data-role="phase"></b>', asia)
        self.assertNotIn("Asia range", asia)
        self.assertIn("title=", asia)
        self.assertIn("lvl_asia", self.src, "the saved switch carries over")
        levels = re.search(r'<button class="sv-ind-btn active" data-ind="levels" title="([^"]*)"', html).group(1)
        self.assertIn("Power of Three in violet", levels)
        self.assertNotIn("the Asian range (violet box)", levels)

    def test_the_phase_css_follows_the_theme(self):
        css = self.src.split("<style>")[1].split("</style>")[0]
        css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
        rules = [(s.strip(), b) for s, b in re.findall(r"([^{}]+)\{([^{}]*)\}", css)
                 if '[data-role="phase"]' in s]
        self.assertEqual(len(rules), 1)
        self.assertIn("var(--lvl-session", rules[0][1])
        self.assertEqual(HEX.findall(_strip_vars(rules[0][1])), [])

    def test_a_stage_card_s_head_wraps_rather_than_clipping(self):
        """'Sweep of the A…' on a phone: the stage cards' head rule wraps."""
        css = self.src.split("<style>")[1].split("</style>")[0]
        css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
        rules = {s.strip(): b for s, b in re.findall(r"([^{}]+)\{([^{}]*)\}", css)}
        rule = rules.get(".sv-sig-head--stage .sv-sig-rule", "")
        self.assertIn("white-space: normal", rule)
        self.assertIn("text-overflow: clip", rule)
        self.assertEqual(HEX.findall(_strip_vars(rule)), [])
        self.assertIn('<div class="sv-sig-head sv-sig-head--stage">', self.src)
        # every other card keeps PR51's one-line head
        self.assertIn("white-space: nowrap", rules[".sv-sig-rule"])

    def test_the_stage_paint_reads_the_session_tone_from_the_palette(self):
        """The stages' violet is the palette's session tone, read once
        (levelPalette) by the back pass and the chip pass alike: no literal
        colour in either, no second theme read (PR51's C-8 pins the rest)."""
        for name in ("paintBack", "paintChips"):
            body = self._method(name)
            self.assertIn("var c = levelPalette()", body, name)
            self.assertIn("c.session", body, name)
            self.assertEqual(HEX.findall(_strip_vars(body)), [], name)
        back = self._method("paintBack")
        for shape in ("P3.bands.forEach", "P3.judas", "P3.arrow", "paintDiamond(ctx, s"):
            self.assertIn(shape, back)
        self.assertIn("ch.stage ? c.session", self._method("paintChips"), "the chip that names M")

    def test_the_pure_block_carries_no_template_tags(self):
        pure, _main = _blocks(widget())
        src_pure = self.src[self.src.index("(function () {\n    if (window.svSignalDots) return;"):]
        src_pure = src_pure[:src_pure.index("</script>")]
        for tag in ("{#", "{{", "{%"):
            self.assertNotIn(tag, src_pure)
        self.assertIn("function stageShapes(", pure)
        self.assertIn("hitStage: hitStage", pure)

    def test_the_chart_s_copy_alone_carries_the_stages(self):
        from bot_program import positioning
        from dashboard import views
        body = inspect.getsource(views._chart_positioning)
        self.assertIn("compact(pm)", body)
        self.assertIn("po3_stages", body)
        self.assertNotIn("stages", inspect.getsource(positioning.compact))
        self.assertNotIn("stages", inspect.getsource(positioning.side_read))
        self.assertNotIn("stages", inspect.getsource(positioning._day_words_for_side))

    def test_no_stage_is_a_price_line(self):
        i = self.src.index("function LevelLayer() {")
        layer = self.src[i:self.src.index("function applyLevels() {", i)]
        for absent in ("hitTest", "createPriceLine", "priceAxisViews", "timeAxisViews"):
            self.assertNotIn(absent, layer)
        self.assertIn("stageEnv(", layer)
        back = self._method("paintBack")
        self.assertIn("g.po3", back)
        self.assertIn("layer.set({ asia: { high: a.high", self.src)
