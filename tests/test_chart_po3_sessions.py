"""The Power of Three's three sessions on the chart, every day (2026-10-24).

The operator, after the stages of 2026-10-08: "I still only have on chart
the Asia session marked, not the 2 others, fix too please."

London and New York were drawn only as the evidence of a stage: a faint
full-height column (4.5% alpha, no edge, no name) once the day had run an
Asian edge, New York on a distribution day alone, for the read's own day
and never on a 4h chart; the server sent one day. Now every day in view
marks its three sessions, whatever the day's phase:

  ASIA      a box over its bars, high to low, in the session violet; the
            read's own Asia stays the A box (`A · ASIA`, its card);
  LONDON    a box in the session orchid;
  NEW YORK  a box in the session periwinkle, from the bar holding 08:30
            New York to its close, or to the newest bar while it is open.

Each is named on its box (LONDON, NEW YORK; a phone LDN, NY), the newest
day at full strength, the days before dimmer. The M and D marks stay the
stages': drawn when they happen; a hover on M lights the read day's London
box, on D its New York box. Times are the server's (power_of_three.
session_days, the sessions table: two epochs a window, the last 70 days,
so a seven-hour tape's 240 1h bars are covered). A 4h bar straddles Asia's
close and London's open, so a 4h chart holds no session box: each session
is a strip in its tone along the pane's foot, placed by time, and the key
says where the boxes are. A phone at 1h (London under 8 px) wears the same
strip under its boxes; a name never sits on another session's box or the
A box. An exchange-hours tape (a US stock: no Asia, no London) draws no
session. A 4h read's A box stands on the read day's Asia window on a finer
chart. The key's `Sessions · Power of Three` switch (data-lvl "asia", the
saved preference) shows and hides all three.

Three classes, as tests/test_chart_po3_stages.py:
  ThePo3SessionsLanguageTests  the pure window.svLevels under node;
  ThePo3SessionsWidgetTests    the widget's real script against the fake
                               chart (WIDGET_PRELUDE + LEVELS_PATCH): the
                               boxes on the bars, the paint, the frames,
                               the switch, the key — the three sessions
                               render in the paint pass;
  ThePo3SessionsWiringTests    the colour tokens, the key's markup, the
                               fixture against the server's calendar.

Run with:  python manage.py test tests.test_chart_po3_sessions
"""
import copy
import re
import unittest
from datetime import datetime, timedelta, timezone as dt_timezone
from pathlib import Path

import pandas as pd
from django.conf import settings
from django.test import SimpleTestCase

from bot_program import power_of_three as P3
from tests.test_chart_levels_language import (
    FIXTURE_ROWS, MARKERS, NOW, PATH, PINNED, POSITION, _meets)
from tests.test_chart_levels_widget import LEVELS_PATCH, PREF_KEY, y as y_of
from tests.test_chart_po3_stages import (
    HUNT_ID, SESSIONS, STAGES, _hourly_bars, _po3_payload, _quarter_bars, _utc, _xq)
from tests.test_chart_signal_markers import (
    HEX, NODE, WIDGET_PRELUDE, _blocks, _node, _strip_vars, widget, widget_source)

CHIP_H, ROW_CLEAR, GAP_X, GAP_Y = 14, 2, 4, 1
NAMES = ("asia", "london", "new_york")
#: The palette's fallbacks (dark): the fake page carries no session tokens.
VIOLET, ORCHID, PERIWINKLE = "#a878f0", "#d870e0", "#7c88f8"
TONE = {"asia": VIOLET, "london": ORCHID, "new_york": PERIWINKLE}

#: The sessions in pane pixels, as the widget's sessionEnv hands them to
#: layout (W 740): yesterday's three, today's London and New York (today's
#: Asia is the A box, 470-510). Today's at the old bands' x's.
SES_BOXES = [
    {"date": "2026-10-06", "name": "asia", "x0": 60, "x1": 100, "high": 1.0860, "low": 1.0846},
    {"date": "2026-10-06", "name": "london", "x0": 120, "x1": 142, "high": 1.0858, "low": 1.0842},
    {"date": "2026-10-06", "name": "new_york", "x0": 180, "x1": 260, "high": 1.0866, "low": 1.0848},
    {"date": "2026-10-07", "name": "london", "x0": 520, "x1": 560, "high": 1.0852, "low": 1.08288},
    {"date": "2026-10-07", "name": "new_york", "x0": 600, "x1": 700, "high": 1.0861, "low": 1.0841},
]
SES_IDS = ["sv-ses-%s-%s" % (b["name"], b["date"]) for b in SES_BOXES]


def toY(p):
    """The pure tests' scale: 1 pip is 2 px, 1.0855 at y 200."""
    return 200 - (p - 1.0855) * 20000


SES_PURE_RUN = r"""
const fs = require('fs');
const M = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
var L = window.svLevels, LV = L.LV;
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
              boxes: [], asia: null, po3: null, sessions: null, measure: measure };
    for (var k in o) e[k] = o[k];
    return e;
}
function clone(x) { return JSON.parse(JSON.stringify(x)); }
function geo(g) { return clone(g); }
function mapWith(stages) { var m = { path: M.path }; if (stages) m.po3 = { stages: stages }; return m; }
var ITEMS = L.digest(M.rows, mapWith(M.stages), fmt);
var UP = { high: 1.08608, low: 1.08441 };
function box(a, x0, x1) { return { high: a.high, low: a.low, x0: x0 === undefined ? 470 : x0, x1: x1 === undefined ? 510 : x1 }; }
function run(side, price, edge, x, back) {
    return { side: side, price: price, edge: edge, x: x, tip: price, back: back, text: fmt(price) };
}
function po3(phase, o) {
    var p = { phase: phase, direction: null, date: '2026-10-07', sweeps: [], judas: null, ret: null, draw: null };
    for (var k in (o || {})) p[k] = o[k];
    return p;
}
/* the sessions as sessionEnv hands them, scaled to a pane of width W */
function ses(o) {
    o = o || {};
    var f = (o.width || 740) / 740;
    return { wide: !!o.wide, list: M.boxes.map(function (b) { var q = clone(b); q.x0 *= f; q.x1 *= f; return q; }) };
}
function scaled(p, W) {
    var f = W / 740, q = clone(p);
    q.sweeps.forEach(function (s) { s.x *= f; });
    if (q.judas) { q.judas.x0 *= f; q.judas.x1 *= f; }
    if (q.ret) q.ret.x *= f;
    return q;
}
var JUD = { x0: 522, open: 1.08500, x1: 545, extreme: 1.08288 };
var ACC = po3('accumulation');
var MAN = po3('manipulation', { sweeps: [run('low', 1.08288, 1.08441, 545, false)], judas: JUD });
var DIS = po3('distribution', { direction: 'up', sweeps: [run('low', 1.08288, 1.08441, 545, true)],
                               judas: JUD, ret: { x: 605, from: 1.08441, to: 1.08608 }, draw: 'agrees' });
var UNC = po3('unclear', { sweeps: [run('low', 1.08288, 1.08441, 545, true), run('high', 1.08650, 1.08608, 640, false)],
                           judas: JUD });
var STATES = [['acc', ACC], ['man', MAN], ['dis', DIS], ['unc', UNC], ['none', null]];

/* S1: every phase, the same five boxes; and the same pane without them */
out.phases = {}; out.without = {};
STATES.forEach(function (p) {
    var a = p[1] ? box(UP) : null;
    out.phases[p[0]] = geo(L.layout(ITEMS, env({ po3: p[1], asia: a, sessions: ses() })));
    out.without[p[0]] = geo(L.layout(ITEMS, env({ po3: p[1], asia: a })));
});
/* a free pane: no level, so every name finds its box */
out.free = geo(L.layout([], env({ po3: DIS, asia: box(UP), sessions: ses() })));
out.freeAcc = geo(L.layout([], env({ po3: ACC, asia: box(UP), sessions: ses() })));
/* S3: dims */
out.dims = {
    pinDark: geo(L.layout([], env({ po3: DIS, asia: box(UP), sessions: ses(), pinned: true }))),
    pinLight: geo(L.layout([], env({ po3: DIS, asia: box(UP), sessions: ses(), pinned: true, theme: 'light' }))),
    focusPool: geo(L.layout([], env({ po3: DIS, asia: box(UP), sessions: ses(), focus: 'pool' }))),
    focusAsia: geo(L.layout([], env({ po3: DIS, asia: box(UP), sessions: ses(), focus: 'asia' })))
};
/* S4: a hover on a stage lights its session; nothing moves */
out.hover = {};
[null, 'sv-po3-m-low', 'sv-po3-judas', 'sv-po3-d', M.huntId].forEach(function (h) {
    out.hover[String(h)] = geo(L.layout(ITEMS, env({ po3: DIS, asia: box(UP), sessions: ses(), hover: h })));
});
out.hoverNoDay = geo(L.layout([], env({ po3: null, asia: null, sessions: ses(), hover: 'sv-po3-m-low' })));
/* S5: a phone */
out.phone = geo(L.layout(ITEMS, env({ po3: scaled(DIS, 330), asia: box(UP, 210, 228), phone: true, width: 330,
                                      sessions: ses({ width: 330 }) })));
out.phoneWithout = geo(L.layout(ITEMS, env({ po3: scaled(DIS, 330), asia: box(UP, 210, 228), phone: true, width: 330 })));
out.phoneFree = geo(L.layout([], env({ po3: scaled(DIS, 330), asia: box(UP, 210, 228), phone: true, width: 330,
                                       sessions: ses({ width: 330 }) })));
/* S5b: a box too narrow for any name: the newest day's short name
   overhangs it, an older day's has none */
out.narrow = geo(L.layout([], env({ sessions: { wide: false, list: [
    { date: '2026-10-06', name: 'london', x0: 120, x1: 126, high: 1.0858, low: 1.0842 },
    { date: '2026-10-07', name: 'london', x0: 520, x1: 526, high: 1.0858, low: 1.0842 }] } })));
/* S6: frames and the switch */
out.daily = geo(L.layout(ITEMS, env({ po3: DIS, asia: box(UP), sessions: ses(), highTf: true })));
out.switched = geo(L.layout(ITEMS, env({ po3: DIS, asia: box(UP), sessions: ses(), hidden: { asia: true } })));
out.wide = geo(L.layout(ITEMS, env({ po3: DIS, asia: box(UP), sessions: ses({ wide: true }) })));
out.wideWithout = geo(L.layout(ITEMS, env({ po3: DIS, asia: box(UP) })));
/* S7: the pane's edges */
out.edge = geo(L.layout([], env({ sessions: { wide: false, list: [
    { date: '2026-10-05', name: 'new_york', x0: -90, x1: -10, high: 1.0860, low: 1.0850 },
    { date: '2026-10-06', name: 'asia', x0: -20, x1: 30, high: 1.0860, low: 1.0850 },
    { date: '2026-10-06', name: 'london', x0: 60, x1: 90, high: 1.1000, low: 1.0990 },
    { date: '2026-10-07', name: 'new_york', x0: 745, x1: 800, high: 1.0860, low: 1.0850 },
    { date: '2026-10-07', name: 'london', x0: 300, x1: 340, high: 1.0860, low: 1.0850 }] } })));
/* S8: never hit */
var gh = L.layout([], env({ po3: DIS, asia: box(UP), sessions: ses() }));
var b6 = gh.sessions.boxes.filter(function (b) { return b.id === 'sv-ses-new_york-2026-10-06'; })[0];
var cx = (b6.x0 + b6.x1) / 2, cy = (b6.yh + b6.yl) / 2;
out.hit = { stage: L.hitStage(gh, cx, cy, 12, false), level: L.hit(gh, [], cx, cy, 12) };

/* S9: every keep-out, many zooms and shifts, money, titles, markers, overlays, candles */
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
function newest(ty, W) {
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
                [DIS, MAN, ACC].forEach(function (state, si) {
                    var W = phone ? 330 : 740, ty = toYs(scale, shift), f = W / 740;
                    var m = money(ty, withPos ? M.pos : null, M.pinned), hl = [ty(1.08700)], lastY = ty(M.mark);
                    var e = { toY: ty, width: W, phone: phone, money: m, labels: true, laneW: 96, hlines: hl,
                              lastY: lastY, boxes: L.markerBoxes(markerPoints(ty, W), phone ? 6 : 10, 10),
                              pinned: true, titles: m.map(function (r) { return { y: r.y, w: measure(r.t) + 16 }; }),
                              overlays: phone ? [{ x0: W - 140, x1: W - 6, y0: 0, y1: 34 }]
                                              : [{ x0: 0, x1: 416, y0: 0, y1: 34 }, { x0: W - 145, x1: W - 6, y0: 0, y1: 34 }],
                              candles: newest(ty, W), po3: scaled(state, W), asia: box(UP, 470 * f, 510 * f) };
                    var withS = clone(e); withS.toY = ty; withS.measure = measure; withS.sessions = ses({ width: W });
                    out.rules.push({ W: W, phone: phone, scale: scale, shift: shift, state: si, pos: withPos,
                                     rows: m.map(function (r) { return r.y; }).concat(hl, [lastY]),
                                     g: geo(L.layout(ITEMS, env(withS))), bare: geo(L.layout(ITEMS, env(e))) });
                });
            });
        });
    });
});

/* S10: the 390 px chart at 1h (a 298 px pane): today's thin London and
   New York at the right edge beside the A box, yesterday's three just
   left of them, a wide New York mid-pane */
var PW = 298;
out.phoneEdge = geo(L.layout([], env({ width: PW, phone: true, po3: po3('accumulation'),
    asia: box(UP, PW - 22.6, PW - 16.9), sessions: { wide: false, list: [
    { date: '2026-10-05', name: 'new_york', x0: 100, x1: 160, high: 1.0866, low: 1.0848 },
    { date: '2026-10-06', name: 'asia', x0: PW - 52.6, x1: PW - 46.9, high: 1.0860, low: 1.0846 },
    { date: '2026-10-06', name: 'london', x0: PW - 44.5, x1: PW - 40, high: 1.0858, low: 1.0842 },
    { date: '2026-10-06', name: 'new_york', x0: PW - 37.1, x1: PW - 27.6, high: 1.0866, low: 1.0848 },
    { date: '2026-10-07', name: 'london', x0: PW - 14.5, x1: PW - 10, high: 1.0852, low: 1.08288 },
    { date: '2026-10-07', name: 'new_york', x0: PW - 7.1, x1: PW - 2.6, high: 1.0861, low: 1.0841 }] } })));
/* ...the same at 740 px, the boxes as narrow at its right edge */
out.deskEdge = geo(L.layout([], env({ po3: po3('accumulation'), asia: box(UP, 740 - 22.6, 740 - 16.9),
    sessions: { wide: false, list: [
    { date: '2026-10-07', name: 'london', x0: 740 - 14.5, x1: 740 - 10, high: 1.0852, low: 1.08288 },
    { date: '2026-10-07', name: 'new_york', x0: 740 - 7.1, x1: 740 - 2.6, high: 1.0861, low: 1.0841 }] } })));

/* S11: a thin pane's strip (London's three hours under 8 px), a wide pane's none */
var PHONE_DAY = [
    { date: '2026-10-07', name: 'asia', x0: 200, x1: 205.6, high: 1.0860, low: 1.0846 },
    { date: '2026-10-07', name: 'london', x0: 208, x1: 212.4, high: 1.0858, low: 1.0842 },
    { date: '2026-10-07', name: 'new_york', x0: 216, x1: 226.4, high: 1.0866, low: 1.0848 },
    { date: '2026-10-07', name: 'asia', x0: 230, x1: 235, high: 1.2000, low: 1.1990 }];
PHONE_DAY[3].date = '2026-10-08';
out.strip = geo(L.layout([], env({ sessions: { wide: false, pxh: 1.25, list: PHONE_DAY } })));
out.noStrip = geo(L.layout([], env({ sessions: { wide: false, pxh: 4.8, list: PHONE_DAY } })));
process.stdout.write(JSON.stringify(out));
"""


def _box(g, name, date):
    got = [b for b in (g.get("sessions") or {}).get("boxes", []) if b["name"] == name and b["date"] == date]
    return got[0] if got else None


def _labels(g):
    return [b["label"] for b in ((g.get("sessions") or {}).get("boxes") or []) if b.get("label")]


def _rect(b):
    """A session box (or the A box) as a rectangle."""
    return {"x0": b["x0"], "x1": b["x1"], "y0": b["yh"], "y1": b["yl"]}


def _others(g):
    """Everything on a pane but the sessions: chips, edges, the A label,
    the stages' marks and letters — what a session must never move."""
    p = g.get("po3") or {}
    return {"chips": g["chips"], "edges": g["edges"],
            "asia": g.get("asia"), "bands": g["bands"], "rays": g["rays"], "ticks": g["ticks"],
            "po3": {k: p.get(k) for k in ("sweeps", "judas", "arrow", "labels", "folded")} if p else None}


@unittest.skipUnless(NODE, "node is not installed")
class ThePo3SessionsLanguageTests(SimpleTestCase):
    """The pure half (window.svLevels) under node."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        pure, _main = _blocks(widget())
        cls.out = _node("var window = {};\n" + pure + "\n" + SES_PURE_RUN, {
            "rows": FIXTURE_ROWS, "path": PATH, "now": NOW, "mark": 1.08552,
            "pos": POSITION, "pinned": PINNED, "markers": MARKERS, "stages": STAGES,
            "boxes": SES_BOXES, "huntId": HUNT_ID})

    # S1
    def test_every_day_s_three_sessions_draw_whatever_the_phase(self):
        """The operator's quiet day (accumulation) draws London and New York
        as a run day does: the phase gates the M and D marks, never a
        session."""
        want = [(i, b["x0"], b["x1"], toY(b["high"]), toY(b["low"])) for i, b in zip(SES_IDS, SES_BOXES)]
        for key, g in self.out["phases"].items():
            s = g["sessions"]
            self.assertFalse(s["wide"], key)
            got = [(b["id"], b["x0"], b["x1"], b["yh"], b["yl"]) for b in s["boxes"]]
            self.assertEqual([x[0] for x in got], SES_IDS, key)
            for (gi, gx0, gx1, gyh, gyl), (wi, wx0, wx1, wyh, wyl) in zip(got, want):
                self.assertEqual((gx0, gx1), (wx0, wx1), (key, gi))
                self.assertAlmostEqual(gyh, wyh, places=9, msg=(key, gi))
                self.assertAlmostEqual(gyl, wyl, places=9, msg=(key, gi))
            self.assertEqual(s["newest"], "2026-10-07", key)
        # the stage marks still follow the phase: none on a quiet day
        acc = self.out["phases"]["acc"]["po3"]
        self.assertEqual((acc["sweeps"], acc["judas"], acc["arrow"], acc["labels"]), ([], None, None, []))
        self.assertEqual(self.out["phases"]["acc"]["asia"]["label"]["text"], "A · ASIA")
        self.assertIsNotNone(self.out["phases"]["dis"]["po3"]["arrow"])
        # an unread day (the weekend): no stage, every session
        self.assertIsNone(self.out["phases"]["none"]["po3"])

    # S2
    def test_nothing_else_on_the_pane_moves_for_a_session(self):
        for key in self.out["phases"]:
            self.assertEqual(_others(self.out["phases"][key]), _others(self.out["without"][key]), key)
            self.assertIsNone(self.out["without"][key]["sessions"], key)
        self.assertEqual(_others(self.out["phone"]), _others(self.out["phoneWithout"]))
        n = 0
        for case in self.out["rules"]:
            self.assertEqual(_others(case["g"]), _others(case["bare"]),
                             (case["scale"], case["shift"], case["phone"], case["state"], case["pos"]))
            n += 1
        self.assertEqual(n, 108)

    # S3
    def test_the_newest_day_is_full_strength_the_days_before_dimmer(self):
        g = self.out["phases"]["dis"]
        k = {b["id"]: b["k"] for b in g["sessions"]["boxes"]}
        for i in SES_IDS:
            self.assertAlmostEqual(k[i], 1 if i.endswith("2026-10-07") else 0.6, msg=i)
        self.assertEqual([b["newest"] for b in g["sessions"]["boxes"]], [False, False, False, True, True])
        d = self.out["dims"]
        for key, f in (("pinDark", 0.55), ("pinLight", 0.8), ("focusPool", 0.2), ("focusAsia", 1)):
            for b in d[key]["sessions"]["boxes"]:
                self.assertAlmostEqual(b["k"], f * (1 if b["newest"] else 0.6), msg=(key, b["id"]))

    # S4
    def test_a_hover_on_a_stage_lights_its_session_and_moves_nothing(self):
        h = self.out["hover"]

        def hot(g):
            return [b["id"] for b in g["sessions"]["boxes"] if b["hot"]]
        self.assertEqual(hot(h["null"]), [])
        self.assertEqual(hot(h["sv-po3-m-low"]), ["sv-ses-london-2026-10-07"])
        self.assertEqual(hot(h["sv-po3-judas"]), ["sv-ses-london-2026-10-07"])
        self.assertEqual(hot(h["sv-po3-d"]), ["sv-ses-new_york-2026-10-07"])
        self.assertEqual(hot(h[HUNT_ID]), [])
        lit = [b for b in h["sv-po3-d"]["sessions"]["boxes"] if b["hot"]][0]
        self.assertEqual(lit["k"], 1)
        self.assertEqual(hot(self.out["hoverNoDay"]), [], "no read day: no stage to light")

        def rects(g):
            return sorted((l["text"], l["x0"], l["y0"]) for l in _labels(g))
        for key, g in h.items():
            self.assertEqual(rects(g), rects(h["null"]), key)

    # S5
    def test_each_session_is_named_on_its_box(self):
        free = self.out["free"]
        names = {b["id"]: (b.get("label") or {}).get("text") for b in free["sessions"]["boxes"]}
        self.assertEqual(names, {
            "sv-ses-asia-2026-10-06": "ASIA",
            # yesterday's London is 22 px: LONDON's 36.6 px of words would
            # sit on its neighbours, LDN's 18.3 fit
            "sv-ses-london-2026-10-06": "LDN",
            "sv-ses-new_york-2026-10-06": "NEW YORK",
            # today's names may overhang their box
            "sv-ses-london-2026-10-07": "LONDON",
            "sv-ses-new_york-2026-10-07": "NEW YORK"})
        acc = {b["id"]: (b.get("label") or {}).get("text") for b in self.out["freeAcc"]["sessions"]["boxes"]}
        self.assertEqual(acc, names, "a quiet day names the same sessions")
        for b in free["sessions"]["boxes"]:
            l = b["label"]
            self.assertTrue(l["x1"] > b["x0"] and l["x0"] < b["x1"], (b["id"], "over its own box"))
            outside = l["y1"] <= b["yh"] or l["y0"] >= b["yl"]
            inside = abs(l["y0"] - (b["yh"] + 1)) < 1e-9 or abs(l["y1"] - (b["yl"] - 1)) < 1e-9
            if b["newest"]:
                self.assertTrue(outside or inside, (b["id"], "above, under or inside an edge"))
            else:
                self.assertTrue(outside, (b["id"], "above or under it"))
            # its words no wider than its box and a chip's padding each side
            self.assertLessEqual(len(l["text"]) * 6.1, b["x1"] - b["x0"] + 8, b["id"])
            self.assertAlmostEqual((l["x0"] + l["x1"]) / 2, (b["x0"] + b["x1"]) / 2, places=9,
                                   msg=(b["id"], "centred on its box"))
        # today's London: the last price runs over it and its swept low under
        # it, so its name sits inside its top edge
        lon = _box(free, "london", "2026-10-07")
        self.assertAlmostEqual(lon["label"]["y0"], lon["yh"] + 1, places=9)
        for l in _labels(free):
            self.assertEqual(l["k"], 1 if l in [b["label"] for b in free["sessions"]["boxes"] if b["newest"]] else 0.8)
        # a phone: the short names, where they fit
        for g in (self.out["phone"], self.out["phoneFree"]):
            for b in g["sessions"]["boxes"]:
                self.assertIn((b.get("label") or {}).get("text"), (None, "ASIA", "LDN", "NY"), b["id"])
        phone = {b["id"]: (b.get("label") or {}).get("text") for b in self.out["phoneFree"]["sessions"]["boxes"]}
        self.assertEqual(phone["sv-ses-london-2026-10-07"], "LDN")
        self.assertEqual(phone["sv-ses-new_york-2026-10-07"], "NY")
        self.assertIsNone(phone["sv-ses-london-2026-10-06"], "10 px: no name fits, the tone says it")
        # too narrow for any name: the newest day's short name overhangs it,
        # as the A label does; an older day's box goes unnamed
        narrow = {b["date"]: (b.get("label") or {}).get("text") for b in self.out["narrow"]["sessions"]["boxes"]}
        self.assertEqual(narrow, {"2026-10-06": None, "2026-10-07": "LDN"})

    # S6
    def test_daily_the_switch_and_a_wide_frame(self):
        self.assertIsNone(self.out["daily"]["sessions"])
        self.assertIsNone(self.out["switched"]["sessions"], "the Power of Three switch hides all three")
        self.assertIsNone(self.out["switched"]["asia"])
        # a 4h pane (2026-10-24): every session a strip by time, no price
        # box, no name
        w = self.out["wide"]["sessions"]
        self.assertTrue(w["wide"])
        self.assertTrue(w["strip"])
        self.assertEqual([b["id"] for b in w["boxes"]], SES_IDS)
        for b in w["boxes"]:
            self.assertEqual((b["priced"], b["ribbon"], b["yh"], b["yl"], b.get("label")),
                             (False, True, None, None, None), b["id"])
        self.assertEqual(_others(self.out["wide"]), _others(self.out["wideWithout"]))

    # S7
    def test_the_pane_s_edges(self):
        s = self.out["edge"]["sessions"]
        self.assertEqual([b["id"] for b in s["boxes"]], ["sv-ses-asia-2026-10-06", "sv-ses-london-2026-10-07"])
        a = s["boxes"][0]
        self.assertEqual((a["x0"], a["x1"], a["clipped"]), (0, 30, True))
        self.assertFalse(s["boxes"][1]["clipped"])
        self.assertEqual(s["newest"], "2026-10-07")

    # S8
    def test_a_session_is_never_hit(self):
        """Over the candles a session is everywhere: a box that answered the
        pointer would pop a card at every rest. The names, the colours and
        the key say which session it is."""
        self.assertEqual(self.out["hit"], {"stage": None, "level": None})

    # S9
    def test_every_name_keeps_every_keep_out(self):
        seen = 0
        for case in self.out["rules"]:
            g, W = case["g"], case["W"]
            ctx = (case["scale"], case["shift"], case["phone"], case["state"], case["pos"])
            others = g["chips"] + g["edges"] + ((g["po3"] or {}).get("labels") or [])
            if g["asia"] and g["asia"].get("label"):
                others.append(g["asia"]["label"])
            marks = [s["box"] for s in (g["po3"] or {}).get("sweeps", [])]
            if (g["po3"] or {}).get("arrow"):
                marks.append(g["po3"]["arrow"]["box"])
            labels = _labels(g)
            for b in g["sessions"]["boxes"]:
                l = b.get("label")
                if not l:
                    continue
                seen += 1
                self.assertGreaterEqual(l["x0"], 0, ctx)
                self.assertLessEqual(l["x1"], W, ctx)
                self.assertGreaterEqual(l["y0"], 0, ctx)
                self.assertLessEqual(l["y1"], 384, ctx)
                self.assertTrue(b["x0"] <= (l["x0"] + l["x1"]) / 2 <= b["x1"], (ctx, b["id"], "centred on its box"))
                # never on another session's box, nor on the A box
                for b2 in g["sessions"]["boxes"]:
                    if b2 is not b and b2["priced"]:
                        self.assertFalse(_meets(l, _rect(b2)), (ctx, b["id"], b2["id"]))
                if g["asia"] and not g["asia"].get("wash"):
                    self.assertFalse(_meets(l, _rect(g["asia"])), (ctx, b["id"], "the A box"))
                for o in others + marks + g["keep"]["marks"] + g["keep"]["overlays"]:
                    self.assertFalse(_meets(l, o), (ctx, b["id"], o.get("text")))
                for t in g["keep"]["titles"]:
                    self.assertFalse(_meets(l, t, GAP_X, GAP_Y), (ctx, b["id"], t))
                for row in case["rows"]:
                    self.assertFalse(l["y0"] - ROW_CLEAR <= row <= l["y1"] + ROW_CLEAR, (ctx, b["id"], row))
                for other in labels:
                    if other is not l:
                        self.assertFalse(_meets(l, other), (ctx, b["id"]))
                if case["phone"]:
                    self.assertIn(l["text"], ("ASIA", "LDN", "NY"), ctx)
        self.assertGreater(seen, 100, "names were placed in the sweep")

    # S10
    def test_a_phone_never_writes_a_name_on_the_neighbouring_session(self):
        """Today's boxes stand at the right edge. On the 390 px chart at 1h
        the pane's edge slid today's 'NY' left onto London's box and 'LDN'
        across the A box: a name stays centred on its own box and meets no
        other session's box nor the A box, or it has no name (the strip and
        the key's swatch say which)."""
        for key in ("phoneEdge", "deskEdge"):
            g = self.out[key]
            boxes = g["sessions"]["boxes"]
            for b in boxes:
                l = b.get("label")
                if not l:
                    continue
                self.assertTrue(b["x0"] <= (l["x0"] + l["x1"]) / 2 <= b["x1"], (key, b["id"]))
                for b2 in boxes:
                    if b2 is not b:
                        self.assertFalse(_meets(l, _rect(b2)), (key, b["id"], "on", b2["id"]))
                self.assertFalse(_meets(l, _rect(g["asia"])), (key, b["id"], "on the A box"))
            names = {b["id"]: (b.get("label") or {}).get("text") for b in boxes}
            self.assertIsNone(names["sv-ses-london-2026-10-07"], key)
            self.assertIsNone(names["sv-ses-new_york-2026-10-07"], key)
        names = {b["id"]: (b.get("label") or {}).get("text") for b in self.out["phoneEdge"]["sessions"]["boxes"]}
        self.assertEqual(names["sv-ses-new_york-2026-10-05"], "NY", "a box with room is still named")

    # S11
    def test_a_thin_pane_wears_the_strip_and_its_thin_boxes_no_edge(self):
        """Where London's three hours span fewer than 8 px (a phone at 1h)
        a 1 px violet edge and a 1 px orchid one cannot be told apart:
        every session also wears a solid strip in its tone along the pane's
        foot, and a box under 8 px drops its edge. A box off the pane's
        prices keeps its strip alone."""
        s = self.out["strip"]["sessions"]
        self.assertTrue(s["strip"])
        got = {(b["date"], b["name"]): (b["priced"], b["thin"], b["ribbon"]) for b in s["boxes"]}
        self.assertEqual(got, {("2026-10-07", "asia"): (True, True, True),
                               ("2026-10-07", "london"): (True, True, True),
                               ("2026-10-07", "new_york"): (True, False, True),
                               ("2026-10-08", "asia"): (False, False, True)})
        n = self.out["noStrip"]["sessions"]
        self.assertFalse(n["strip"])
        self.assertEqual([(b["name"], b["ribbon"]) for b in n["boxes"]],
                         [("asia", False), ("london", False), ("new_york", False)],
                         "a wide pane: boxes alone, one off its prices dropped")


# ═══ The widget's real script against the fake chart ═════════════════════

SES_SCENARIO = r"""
/* The key's Power of Three switch: its phase and its sessions note, two
   recorded elements (LEVELS_PATCH's El answers no querySelector). */
const phaseEl = new El(''), noteEl = new El('');
keyEls.asia.querySelector = function (sel) {
    return sel === '[data-role="phase"]' ? phaseEl : sel === '[data-role="sessions"]' ? noteEl : null;
};
const noteState = function () { return { text: noteEl.textContent, hidden: !!noteEl.hidden, title: noteEl.title || '' }; };
/* A narrower bar spacing than the fake's 10 px (a phone's 1h chart, a
   long tape on one pane): x = 20 + spacing * i. */
if (M.spacing) {
    ts.timeToCoordinate = function (t) {
        const i = BARS.findIndex(function (b) { return b.time === t; });
        return i < 0 ? null : 20 + i * M.spacing;
    };
    ts.logicalToCoordinate = function (i) { return 20 + i * M.spacing; };
    ts.options = function () { return { barSpacing: M.spacing }; };
}
const SCENES = {};

SCENES.boot = async function (R) {
    renderLayer();
    const p = prim();
    R.data = p ? { sessions: p.data.sessions || null, asia: p.data.asia } : null;
    R.geom = geom(); R.ops = ops(); R.texts = CTX.texts.slice();
    R.note = noteState(); R.phase = phaseEl.textContent; R.key = keyState();
};

SCENES.toggle = async function (R) {
    renderLayer();
    R.before = { geom: geom(), note: noteState() };
    keyClick('asia');
    renderLayer();
    R.after = { geom: geom(), saved: savedPrefs(), key: keyState(), note: noteState() };
    keyClick('asia');
    renderLayer();
    R.again = { geom: geom() };
};

SCENES.phone = async function (R) {
    els[ID + '-container'].clientWidth = M.width || 400;
    await refresh(M.payload);
    renderLayer();
    R.geom = geom(); R.texts = CTX.texts.slice(); R.note = noteState(); R.ops = ops();
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

SES_HARNESS = WIDGET_PRELUDE + LEVELS_PATCH + SES_SCENARIO


def _ses_run(mode, payload=None, prefs=None, spacing=None, width=None, **ctx):
    ctx.setdefault("timeframe", "1h")
    pure, main = _blocks(widget(**ctx))
    return _node(SES_HARNESS, {"mode": mode, "pure": pure, "main": main,
                               "payload": payload if payload is not None else _po3_payload(),
                               "prefs": prefs, "prefKey": PREF_KEY, "coarse": False, "noPrims": False,
                               "spacing": spacing, "width": width})


def _unread(p):
    """A day the server cannot read (no Asian range: a stock, the weekend)."""
    p["positioning"]["po3"].update(ok=False, phase="unread", direction=None, asia=None, run=None)
    p["positioning"]["po3"].pop("stages", None)
    return p


def _tape(days, hours_utc, minute=0):
    """Made-up 1h bars on `days` (dates) at `hours_utc`, gently waving
    around 1.0850."""
    bars, i = [], 0
    for d in days:
        for h in hours_utc:
            t = _utc(d.year, d.month, d.day, h, minute)
            c = round(1.0850 + 0.0004 * ((i % 5) - 2) / 2, 5)
            bars.append({"time": t, "open": c - 0.0001, "high": c + 0.0005, "low": c - 0.0005,
                         "close": c, "volume": 0})
            i += 1
    return bars


def _weekdays(last, n):
    """The `n` weekdays up to `last`, oldest first."""
    out, d = [], last
    while len(out) < n:
        if d.weekday() < 5:
            out.insert(0, d)
        d -= timedelta(days=1)
    return out


def _at(bars, t, spacing=10):
    """sessionEnv's x of a time on a frame of `bars` (the fake chart: x =
    20 + spacing i): its bar's left edge plus the time's share of it."""
    tf = bars[1]["time"] - bars[0]["time"]
    i = max(k for k, b in enumerate(bars) if b["time"] <= t)
    return 20 + spacing * i - spacing / 2 + min(1, (t - bars[i]["time"]) / tf) * spacing


def _span(bars, t0, t1):
    """The fake chart's box over the bars inside [t0, t1): its x's (20 +
    10 i, half a bar each side) and the bars' high and low."""
    i = [k for k, b in enumerate(bars) if b["time"] + (bars[1]["time"] - bars[0]["time"]) > t0
         and b["time"] < t1]
    sub = bars[i[0]:i[-1] + 1]
    return (20 + 10 * i[0] - 5, 20 + 10 * i[-1] + 5, max(b["high"] for b in sub), min(b["low"] for b in sub))


def _win(date, name):
    return [d for d in SESSIONS if d["date"] == date][0][name]


@unittest.skipUnless(NODE, "node is not installed")
class ThePo3SessionsWidgetTests(SimpleTestCase):
    """The widget's real script, the fake chart, LEVELS_PATCH unedited."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.boot = _ses_run("boot")

    def _boxes(self, out):
        return {(b["date"], b["name"]): b for b in out["geom"]["sessions"]["boxes"]}

    # W1
    def test_the_sessions_ride_the_layer_and_stand_on_the_bars(self):
        r = self.boot
        self.assertEqual(r["data"]["sessions"], SESSIONS)
        bars = _hourly_bars()
        boxes = self._boxes(r)
        want = {}
        for date in ("2026-10-06", "2026-10-07"):
            for name in NAMES:
                w = _win(date, name)
                want[(date, name)] = _span(bars, w["opened"], w["closed"])
        # today's Asia is the A box, the 5th before the tape: none of theirs
        del want[("2026-10-07", "asia")]
        self.assertEqual(sorted(boxes), sorted(want))
        for key, (x0, x1, hi, lo) in want.items():
            b = boxes[key]
            self.assertEqual((b["x0"], b["x1"]), (x0, x1), key)
            self.assertAlmostEqual(b["yh"], y_of(hi), places=9, msg=key)
            self.assertAlmostEqual(b["yl"], y_of(lo), places=9, msg=key)
        # New York is open: from the bar holding 08:30 New York to the newest bar, nothing past it
        ny = boxes[("2026-10-07", "new_york")]
        self.assertEqual((ny["x0"], ny["x1"]), (20 + 36 * 10 - 5, 20 + 38 * 10 + 5))
        # the A box is unchanged
        self.assertEqual(r["geom"]["asia"]["label"]["text"], "A · ASIA")
        self.assertTrue(r["note"]["hidden"], "a 1h chart draws the sessions: nothing to say")

    # W2
    def test_the_three_sessions_render_under_the_candles_and_are_named_over_them(self):
        ops, texts = self.boot["ops"], self.boot["texts"]
        top0 = next(i for i, o in enumerate(ops) if o["op"] == "fillText")
        fills = {n: [o for o in ops[:top0] if o["op"] == "fillRect" and o["fill"] == TONE[n]
                     and o["args"][1] != 0] for n in NAMES}
        frames = {n: [o for o in ops[:top0] if o["op"] == "strokeRect" and o["stroke"] == TONE[n]]
                  for n in NAMES}
        # yesterday's three and today's London and New York; today's Asia
        # is the A box (its own violet fill at .09)
        self.assertEqual(len(fills["london"]), 2)
        self.assertEqual(len(fills["new_york"]), 2)
        asia = [o for o in fills["asia"] if abs(o["alpha"] - 0.08 * 0.6) < 1e-9]
        self.assertEqual(len(asia), 1, "yesterday's Asia box")
        self.assertEqual(len(frames["london"]), 2)
        self.assertEqual(len(frames["new_york"]), 2)
        for n in ("london", "new_york"):
            self.assertEqual(sorted(round(o["alpha"], 9) for o in fills[n]), [0.048, 0.08], n)
        # the tones are three, and none is the swing blue or the pool gold
        self.assertEqual(len({VIOLET, ORCHID, PERIWINKLE}), 3)
        # first of the level shapes: before the A box's fill
        a_box = next(i for i, o in enumerate(ops) if o["op"] == "fillRect" and o["fill"] == VIOLET
                     and abs(o["alpha"] - 0.09) < 1e-9)
        self.assertLess(max(i for i, o in enumerate(ops) if o in fills["london"] + fills["new_york"] + asia), a_box)
        # named in the top pass, each in its own tone
        for t in ("LONDON", "NEW YORK", "ASIA", "A · ASIA"):
            self.assertIn(t, texts)
        named = {o["args"][0]: o["fill"] for o in ops[top0:] if o["op"] == "fillText"}
        self.assertEqual(named["LONDON"], ORCHID)
        self.assertEqual(named["NEW YORK"], PERIWINKLE)
        self.assertEqual(named["ASIA"], VIOLET)
        # the stages' letters as before
        for t in ("M · SWEEP  1.08288", "D ▲ · ② DRAW"):
            self.assertIn(t, texts)

    # W3
    def test_a_quiet_day_and_an_unread_day_mark_every_session(self):
        """The operator's chart: an accumulation day drew the A box alone.
        A quiet day now draws London and New York too; a day the server
        cannot read (the weekend's, no A box) draws the newest day's Asia as
        a session box of its own."""
        p = _po3_payload()
        po3 = p["positioning"]["po3"]
        po3.update(phase="accumulation", direction=None,
                   run={"below": False, "above": False, "low": None, "high": None})
        po3["stages"]["sweeps"] = []
        quiet = _ses_run("boot", payload=p)
        self.assertEqual(sorted(self._boxes(quiet)), sorted(self._boxes(self.boot)))
        self.assertEqual(quiet["geom"]["po3"]["labels"], [])
        self.assertIn("LONDON", quiet["texts"])
        self.assertIn("NEW YORK", quiet["texts"])
        p = _po3_payload(stages=False)
        p["positioning"]["po3"].update(ok=False, phase="unread", direction=None, asia=None, run=None)
        unread = _ses_run("boot", payload=p)
        self.assertIsNone(unread["geom"]["asia"])
        self.assertIsNone(unread["geom"]["po3"])
        boxes = self._boxes(unread)
        self.assertEqual(len(boxes), 6)
        bars = _hourly_bars()
        w = _win("2026-10-07", "asia")
        x0, x1, hi, lo = _span(bars, w["opened"], w["closed"])
        a = boxes[("2026-10-07", "asia")]
        self.assertEqual((a["x0"], a["x1"]), (x0, x1))
        self.assertAlmostEqual(a["yh"], y_of(hi), places=9)
        self.assertNotIn("A · ASIA", unread["texts"])

    # W4
    def test_a_four_hour_chart_marks_each_session_by_time_a_daily_none(self):
        """The operator reads the Power of Three on 4H too: there the A box,
        M and D stood alone. A 4h bar's high and low belong to more than one
        session, so no box: every day's Asia, London and New York are a
        strip in their tone along the pane's foot, from the open to the
        close placed inside their bars by time."""
        bars = _hourly_bars(step_hours=4)
        out = _ses_run("boot", payload=dict(_po3_payload(bars=bars), timeframe="4h"), timeframe="4h")
        s = out["geom"]["sessions"]
        self.assertTrue(s["wide"])
        got = {(b["date"], b["name"]): b for b in s["boxes"]}
        # the 5th is before the tape; the 6th and the 7th, three each
        # (today's Asia too: a strip is a time, the A box a price)
        self.assertEqual(sorted(got), sorted((d, n) for d in ("2026-10-06", "2026-10-07") for n in NAMES))
        for (date, name), b in got.items():
            w = _win(date, name)
            self.assertAlmostEqual(b["x0"], _at(bars, w["opened"]), places=9, msg=(date, name))
            self.assertAlmostEqual(b["x1"], _at(bars, w["closed"]), places=9, msg=(date, name))
            self.assertEqual((b["priced"], b["ribbon"], b.get("label")), (False, True, None), (date, name))
        # London 06:00 to 09:00 UTC: half of the 04:00 bar, a quarter of the 08:00 one
        lon = got[("2026-10-06", "london")]
        self.assertEqual((lon["x0"], lon["x1"]), (30, 37.5))
        # New York, open: to the newest bar's right edge, nothing past it
        self.assertEqual(got[("2026-10-07", "new_york")]["x1"], 20 + 10 * (len(bars) - 1) + 5)
        # painted under the candles, a solid strip at the foot in each tone
        ops = out["ops"]
        top0 = next(i for i, o in enumerate(ops) if o["op"] == "fillText")
        for n in NAMES:
            strips = [o for o in ops[:top0] if o["op"] == "fillRect" and o["fill"] == TONE[n]
                      and o["args"][1] == 380 and o["args"][3] == 4]
            self.assertEqual(len(strips), 2, n)
        # no session's edge: the one violet frame under the candles is the A box's
        frames = {n: len([o for o in ops[:top0] if o["op"] == "strokeRect" and o["stroke"] == TONE[n]])
                  for n in NAMES}
        self.assertEqual(frames, {"asia": 1, "london": 0, "new_york": 0})
        self.assertFalse(out["note"]["hidden"])
        self.assertEqual(out["note"]["text"], "· session boxes on 1h or finer")
        self.assertIn("4h bar", out["note"]["title"])
        self.assertIn("strip", out["note"]["title"])
        # the stages and the A box as before (tests/test_chart_po3_stages W3)
        self.assertEqual(out["geom"]["asia"]["label"]["text"], "A · ASIA")
        self.assertEqual(len(out["geom"]["po3"]["sweeps"]), 1)
        for t in ("LONDON", "NEW YORK", "LDN", "NY"):
            self.assertNotIn(t, out["texts"])
        daily = _ses_run("boot", payload=dict(_po3_payload(), timeframe="1d"), timeframe="1d")
        self.assertIsNone(daily["geom"]["sessions"])
        self.assertFalse(daily["note"]["hidden"], "a daily chart says it too")
        # an old reply (no sessions) says nothing
        old = _ses_run("boot", payload=dict(_po3_payload(sessions=False, bars=_hourly_bars(step_hours=4)),
                                            timeframe="4h"), timeframe="4h")
        self.assertTrue(old["note"]["hidden"])

    # W5
    def test_the_switch_hides_all_three_and_persists(self):
        out = _ses_run("toggle")
        self.assertEqual(len(out["before"]["geom"]["sessions"]["boxes"]), 5)
        after = out["after"]
        self.assertIs(after["saved"]["indicators"]["lvl_asia"], False, "the saved key is the same")
        self.assertIsNone(after["geom"]["sessions"])
        self.assertIsNone(after["geom"]["asia"])
        self.assertIsNone(after["geom"]["po3"])
        self.assertEqual(after["key"]["keys"]["asia"]["pressed"], "false")
        self.assertEqual(len(out["again"]["geom"]["sessions"]["boxes"]), 5)
        again = _ses_run("boot", prefs=after["saved"])
        self.assertIsNone(again["geom"]["sessions"])

    # W6
    def test_a_finer_chart_puts_each_box_on_its_own_quarters(self):
        bars = _quarter_bars(end=(12, 15), late_return=False)
        p = _po3_payload(bars=bars)
        p["timeframe"] = "15min"
        out = _ses_run("boot", payload=p, timeframe="15min")
        boxes = self._boxes(out)
        lon = boxes[("2026-10-07", "london")]
        self.assertEqual((lon["x0"], lon["x1"]), (_xq(bars, 6, 0) - 5, _xq(bars, 8, 45) + 5))
        sub = [b for b in bars if _utc(2026, 10, 7, 6) <= b["time"] < _utc(2026, 10, 7, 9)]
        self.assertAlmostEqual(lon["yl"], y_of(min(b["low"] for b in sub)), places=9)
        self.assertNotIn(("2026-10-07", "new_york"), boxes, "New York has no quarter yet")
        # the 6th's London is before this tape (22:00Z on the 6th): none
        self.assertNotIn(("2026-10-06", "london"), boxes)
        bars = _quarter_bars(end=(12, 30), late_return=False)
        p = _po3_payload(bars=bars)
        p["timeframe"] = "15min"
        ny = self._boxes(_ses_run("boot", payload=p, timeframe="15min"))[("2026-10-07", "new_york")]
        self.assertEqual((ny["x0"], ny["x1"]), (_xq(bars, 12, 30) - 5, _xq(bars, 12, 30) + 5),
                         "the 12:30 quarter opens New York, nothing past the newest bar")

    # W7
    def test_an_upcoming_window_draws_nothing(self):
        p = _po3_payload(bars=[b for b in _hourly_bars() if b["time"] < _utc(2026, 10, 7, 12)])
        p["positioning"]["po3"]["sessions"] = copy.deepcopy(SESSIONS)
        boxes = self._boxes(_ses_run("boot", payload=p))
        self.assertNotIn(("2026-10-07", "new_york"), boxes)
        self.assertIn(("2026-10-07", "london"), boxes)

    # W8
    def test_an_old_reply_draws_no_session_and_nothing_else_changes(self):
        old = _ses_run("boot", payload=_po3_payload(sessions=False))
        self.assertIsNone(old["geom"]["sessions"])
        self.assertIsNone(old["data"]["sessions"])
        for k in ("chips", "edges", "asia", "bands", "rays", "ticks"):
            self.assertEqual(old["geom"][k], self.boot["geom"][k], k)
        for k in ("sweeps", "judas", "arrow", "labels", "folded"):
            self.assertEqual(old["geom"]["po3"][k], self.boot["geom"]["po3"][k], k)
        self.assertEqual(sorted(t for t in self.boot["texts"]
                                if t not in ("ASIA", "LDN", "LONDON", "NEW YORK")), sorted(old["texts"]))

    # W9
    def test_a_phone_names_them_short(self):
        out = _ses_run("phone")
        texts = out["texts"]
        self.assertIn("LDN", texts)
        self.assertIn("NY", texts)
        self.assertNotIn("LONDON", texts)
        self.assertNotIn("NEW YORK", texts)
        self.assertEqual(len(out["geom"]["sessions"]["boxes"]), 5)

    # W10
    def test_a_phone_s_thin_boxes_wear_the_strip_in_all_three_tones(self):
        """The 390 px chart at 1h: 1.2 px a bar, so Asia and London were 4
        to 6 px outlines in near-identical violet and orchid. Every session
        now also paints a solid strip in its tone along the pane's foot,
        and a box under 8 px drops its 1 px edge."""
        out = _ses_run("phone", spacing=1.2, width=390)
        s = out["geom"]["sessions"]
        self.assertTrue(s["strip"])
        self.assertEqual(len(s["boxes"]), 5)
        self.assertTrue(all(b["ribbon"] for b in s["boxes"]))
        ops = out["ops"]
        top0 = next(i for i, o in enumerate(ops) if o["op"] == "fillText")
        for n in NAMES:
            strips = [o for o in ops[:top0] if o["op"] == "fillRect" and o["fill"] == TONE[n]
                      and o["args"][1] == 380 and o["args"][3] == 4]
            self.assertEqual(len(strips), sum(1 for b in s["boxes"] if b["name"] == n), n)
        # the newest day's strips at 0.75, the day before's at 0.6 of it
        alphas = sorted(round(o["alpha"], 9) for o in ops[:top0] if o["op"] == "fillRect"
                        and o["args"][1] == 380 and o["args"][3] == 4)
        self.assertEqual(alphas, [0.45, 0.45, 0.45, 0.75, 0.75])
        thin = [b for b in s["boxes"] if b["thin"]]
        self.assertEqual(len(thin), 4, "every box but yesterday's New York (8 bars)")
        frames = {n: len([o for o in ops[:top0] if o["op"] == "strokeRect" and o["stroke"] == TONE[n]])
                  for n in ("london", "new_york")}
        self.assertEqual(frames, {"london": 0, "new_york": 1}, "the one box wide enough keeps its edge")
        # the desktop's 10 px a bar: boxes alone, no strip
        desk = _ses_run("boot")
        self.assertFalse(desk["geom"]["sessions"]["strip"])
        self.assertFalse([o for o in desk["ops"] if o["op"] == "fillRect" and o["args"][1] == 380
                          and o["args"][3] == 4])

    # W11
    def test_an_exchange_hours_tape_draws_no_session(self):
        """A US stock or cash index (09:30 to 15:30 New York, no Asia, no
        London): one NEW YORK box around every whole trading day says
        nothing, so none is drawn, on 1h nor on 4h."""
        days = _weekdays(datetime(2026, 10, 23).date(), 10)
        bars = _tape(days, range(13, 20), minute=30)
        p = _unread(_po3_payload(bars=bars))
        p["positioning"]["po3"]["sessions"] = P3.session_days(pd.Timestamp("2026-10-23 20:30", tz="UTC"))
        out = _ses_run("boot", payload=p)
        self.assertEqual(out["geom"]["sessions"]["boxes"], [])
        self.assertNotIn("NEW YORK", out["texts"])
        four = [b for b in bars if (b["time"] - 1800) % 14400 == 0]
        p4 = dict(p, bars=four, timeframe="4h")
        self.assertEqual(_ses_run("boot", payload=p4, timeframe="4h")["geom"]["sessions"]["boxes"], [])
        # the same days on a 24/5 tape mark every session
        fx = _unread(_po3_payload(bars=_tape(days[-3:], range(24))))
        fx["positioning"]["po3"]["sessions"] = p["positioning"]["po3"]["sessions"]
        names = {b["name"] for b in _ses_run("boot", payload=fx, spacing=10)["geom"]["sessions"]["boxes"]}
        self.assertEqual(names, set(NAMES))

    # W12
    def test_every_day_of_a_seven_hour_tape_is_marked(self):
        """240 1h bars of a market open seven hours a day are 35 trading
        days, seven weeks of calendar: the server's 16 days marked the last
        two weeks alone (bot_program/power_of_three.SESSION_DAYS). A made-up
        exchange on London's morning (07:00 to 13:00 UTC): every trading day
        on the tape has its London and its New York box."""
        days = _weekdays(datetime(2026, 10, 23).date(), 35)
        bars = _tape(days, range(7, 14))[-240:]
        p = _unread(_po3_payload(bars=bars))
        p["positioning"]["po3"]["sessions"] = P3.session_days(pd.Timestamp("2026-10-23 13:30", tz="UTC"))
        out = _ses_run("boot", payload=p, spacing=3)
        boxes = out["geom"]["sessions"]["boxes"]
        on_tape = sorted({datetime.fromtimestamp(b["time"], tz=dt_timezone.utc).date().isoformat()
                          for b in bars})
        self.assertGreaterEqual(len(on_tape), 35)
        ny = {b["date"] for b in boxes if b["name"] == "new_york"}
        lon = {b["date"] for b in boxes if b["name"] == "london"}
        self.assertEqual([d for d in on_tape if d not in ny], [], "a trading day with no New York box")
        # the oldest day's London is before the tape (its last two bars)
        self.assertEqual([d for d in on_tape if d not in lon], on_tape[:1])
        self.assertFalse([b for b in boxes if b["name"] == "asia"], "no bar in Asia")

    # W13
    def test_a_four_hour_read_after_the_clock_change_keeps_asia_on_its_bars(self):
        """On standard time Asia is 01:00 to 05:00 UTC; a 4h read (a short
        1h tape) stamps its box on the 04:00 to 08:00 UTC bar, which ran
        into London (07:00 UTC) and hid the day's real Asia. On a 1h chart
        the A box stands on the read day's Asia window, at the read's
        prices; London keeps its own box beside it."""
        start = _utc(2026, 11, 2)
        bars = []
        for i in range(37):                                  # 11-02 00:00 to 11-03 12:00 UTC
            c = round(1.0850 + 0.0004 * ((i % 5) - 2) / 2, 5)
            bars.append({"time": start + 3600 * i, "open": c - 0.0001, "high": c + 0.0005,
                         "low": c - 0.0005, "close": c, "volume": 0})
        now = pd.Timestamp("2026-11-03 12:05", tz="UTC")
        sessions = P3.session_days(now, days=3)
        nov3 = [d for d in sessions if d["date"] == "2026-11-03"][0]
        self.assertEqual((nov3["asia"]["opened"], nov3["london"]["opened"]),
                         (_utc(2026, 11, 3, 1), _utc(2026, 11, 3, 7)))

        def payload(read_date):
            p = _po3_payload(bars=bars)
            po3 = p["positioning"]["po3"]
            po3.update(phase="accumulation", direction=None, sessions=copy.deepcopy(sessions),
                       run={"below": False, "above": False, "low": None, "high": None},
                       asia={"high": 1.0859, "low": 1.0843, "date": "2026-11-02",
                             "opened": _utc(2026, 11, 3, 4), "closed": _utc(2026, 11, 3, 8)})
            po3["stages"] = {"date": read_date, "bar": 14400, "london": nov3["london"],
                             "new_york": nov3["new_york"], "sweeps": [], "judas": None}
            return p

        def x(h, d=3):
            return 20 + 10 * [b["time"] for b in bars].index(_utc(2026, 11, d, h))
        out = _ses_run("boot", payload=payload("2026-11-03"))
        a = out["geom"]["asia"]
        self.assertEqual((a["x0"], a["x1"]), (x(1) - 5, x(4) + 5), "the A box on the Asia bars")
        self.assertAlmostEqual(a["yh"], y_of(1.0859), places=9, msg="at the read's prices")
        self.assertEqual(a["label"]["text"], "A · ASIA")
        boxes = self._boxes(out)
        self.assertNotIn(("2026-11-03", "asia"), boxes, "the A box is that day's Asia")
        self.assertIn(("2026-11-02", "asia"), boxes)
        lon = boxes[("2026-11-03", "london")]
        self.assertEqual((lon["x0"], lon["x1"]), (x(7) - 5, x(9) + 5))
        self.assertGreater(lon["x0"], a["x1"], "the A box no longer runs into London")
        # no read day to stand on: the box stays on its 4h bar, and the day's
        # true Asia, which the box only overlaps, keeps its own box
        out = _ses_run("boot", payload=payload("2026-10-30"))
        a = out["geom"]["asia"]
        self.assertEqual((a["x0"], a["x1"]), (x(4) - 5, x(7) + 5))
        own = self._boxes(out)[("2026-11-03", "asia")]
        self.assertEqual((own["x0"], own["x1"]), (x(1) - 5, x(4) + 5))


class ThePo3SessionsWiringTests(SimpleTestCase):

    def setUp(self):
        self.src = widget_source().replace("\r\n", "\n")

    def _method(self, name):
        i = self.src.index("LevelLayer.prototype.%s = function" % name)
        return self.src[i:self.src.index("\n    };", i)]

    def test_the_fixture_is_the_server_s_calendar(self):
        from bot_program import power_of_three as P3
        self.assertEqual(P3.session_days(pd.Timestamp("2026-10-07 14:30", tz="UTC"), days=3), SESSIONS)
        self.assertEqual([(d["date"], d["london"]) for d in SESSIONS if d["date"] == STAGES["date"]],
                         [(STAGES["date"], {k: STAGES["london"][k] for k in ("opened", "closed")})])

    def test_the_tones_exist_in_both_themes_and_differ(self):
        css = (Path(settings.BASE_DIR) / "static" / "css" / "sauron.css").read_text(encoding="utf-8")
        roots = re.findall(r"(?:^|\n)\s*:root\s*\{([^}]*)\}", css)
        light = re.findall(r"(?:^|\n)\s*body\.light-mode\s*\{([^}]*)\}", css)

        def value(blocks, token):
            for b in blocks:
                m = re.search(re.escape(token) + r":\s*([^;]+);", b)
                if m:
                    return m.group(1).strip()
            return None
        for blocks, theme in ((roots, "dark"), (light, "light")):
            got = [value(blocks, t) for t in ("--lvl-session", "--lvl-session-london", "--lvl-session-ny",
                                              "--lvl-swing")]
            self.assertTrue(all(got), (theme, got))
            self.assertEqual(len(set(got)), 4, (theme, got))
        self.assertEqual(value(roots, "--lvl-session-london"), ORCHID, "the palette's dark fallback")
        self.assertEqual(value(roots, "--lvl-session-ny"), PERIWINKLE)
        for line in ("sessionLondon: token('--lvl-session-london', isDark ? '#d870e0' : ",
                     "sessionNy:     token('--lvl-session-ny', isDark ? '#7c88f8' : "):
            self.assertIn(line, self.src)

    def test_the_paint_reads_the_tones_from_the_palette(self):
        back = self._method("paintBack")
        for tone in ("c.session", "c.sessionLondon", "c.sessionNy", "g.sessions"):
            self.assertIn(tone, back)
        self.assertEqual(HEX.findall(_strip_vars(back)), [])
        chips = self._method("paintChips")
        self.assertIn("g.sessions", chips)
        self.assertEqual(HEX.findall(_strip_vars(chips)), [])
        # the faint full-height columns are gone
        self.assertNotIn("BAND_A", self.src)
        self.assertNotIn("P3.bands", back)

    def test_the_key_names_the_sessions_and_keeps_its_saved_key(self):
        html = widget()
        lvl = html.index('id="t-lvl-legend"')
        block = html[lvl:html.index("</div>", lvl)]
        self.assertEqual(re.findall(r'data-lvl="([a-z]+)"', block),
                         ["levels", "below", "above", "pool", "swing", "asia", "round", "all"])
        btn = re.search(r'<button[^>]*data-lvl="asia"[^>]*>.*?</button>', block, re.S).group(0)
        self.assertIn("Sessions · Power of Three", btn)
        self.assertIn('<b data-role="phase"></b>', btn)
        self.assertIn('data-role="sessions"', btn)
        title = re.search(r'title="([^"]*)"', btn).group(1)
        for word in ("Asia", "London", "New York", "every day", "1h"):
            self.assertIn(word, title)
        css = self.src.split("<style>")[1].split("</style>")[0]
        css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
        rules = {s.strip(): b for s, b in re.findall(r"([^{}]+)\{([^{}]*)\}", css)}
        sw = rules[".sv-lvl-sw--asia"]
        for token in ("--lvl-session,", "--lvl-session-london", "--lvl-session-ny"):
            self.assertIn(token, sw)
        self.assertEqual(HEX.findall(_strip_vars(sw)), [])
        levels = re.search(r'<button class="sv-ind-btn active" data-ind="levels" title="([^"]*)"', html).group(1)
        self.assertIn("London", levels)
        self.assertIn("New York", levels)
