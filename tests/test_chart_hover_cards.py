"""The level and position cards on the chart (2026-10-03).

The operator: "small hover details for the new content on the graphs,
without it being too messy; also for the trade entries". One card, the
signal dot's, re-used: the pointer resting on a living level or on a
position's line (entry, stop, target, the care's soft stop) fills it with
three to five facts — the pure half (window.svHoverCards) under node, the
server's facts on each position, and the widget's wiring pinned.

Run with:  python manage.py test tests.test_chart_hover_cards
"""
import unittest
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase

from tests.test_chart_signal_markers import NODE, _blocks, _node, widget, widget_source

PURE_RUN = r"""
var H = window.svHoverCards;
var out = {};
function toY(p) { return p * 100; }
var items = [{price: 1.0, id: 'a'}, {price: 1.05, id: 'b'}, {price: 1.2, id: 'c'}];
out.near = H.nearestLine(items, 106, toY, 6);
out.none = H.nearestLine(items, 113, toY, 6);
out.ties = H.nearestLine(items, 103, toY, 6);
out.empty = H.nearestLine([], 100, toY, 6);
out.level = H.levelCard(
    {price: 1.09, text: '1.09000', kind: 'equal lows (2 touches)', side: 'below',
     pool: true, atr_away: 1.2},
    {path: [{leg: 'hunt', price: 1.09, why: "the longs' stops"},
            {leg: 'draw', price: 1.105, why: 'the bias is long at 0.60'}]});
out.draw = H.levelCard(
    {price: 1.105, text: '1.10500', kind: 'swing high', side: 'above',
     pool: false, atr_away: 2.1},
    {path: [{leg: 'hunt', price: 1.09}, {leg: 'draw', price: 1.105, why: 'the bias is long at 0.60'}]});
out.round = H.levelCard({price: 1.1, text: '1.10000', kind: 'round number',
                         side: 'above', pool: false, atr_away: 0.4}, null);
out.pos = H.positionCard({side: 'long', rule: 'golden <b>cross</b>', entry: 1.08,
    entry_text: '1.08000', stop: 1.075, stop_text: '1.07500', tp: 1.09,
    tp_text: '1.09000', r_now: 0.37, pnl_pct: 1.2, age_s: 3600 * 30,
    leverage: '5', soft_stop: 1.078, soft_stop_text: '1.07800', paper: false,
    protected: true, thesis: {verdict: 'adjust', words: 'Thesis ALIVE — adjust: the lows were swept.'}});
out.paperPos = H.positionCard({side: 'short', via: 'x', entry: 100, stop: 101,
    tp: 97, paper: true, r_now: null, age_s: 120, thesis: {verdict: 'watch'}});
out.age = [H.ageWords(120), H.ageWords(3600 * 30), H.ageWords(3600 * 72), H.ageWords(null)];
out.r = [H.rWords(0.37), H.rWords(-1.5), H.rWords(null)];
process.stdout.write(JSON.stringify(out));
"""


@unittest.skipUnless(NODE, "node is not installed")
class ThePureHalfTests(SimpleTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        pure, _main = _blocks(widget())
        cls.out = _node("var window = {};\n" + pure + "\n" + PURE_RUN)

    def test_the_nearest_line_within_reach_or_nothing(self):
        self.assertEqual(self.out["near"]["id"], "b")
        self.assertIsNone(self.out["none"])
        self.assertEqual(self.out["ties"]["id"], "b")
        self.assertIsNone(self.out["empty"])

    def test_a_pool_s_card_names_its_role_in_the_path(self):
        html = self.out["level"]
        self.assertIn('<span class="sv-sig-side">POOL</span>', html)
        self.assertIn('<span class="sv-sig-rule">equal lows</span>', html)
        self.assertIn("<dt>Price</dt><dd>1.09000</dd>", html)
        self.assertIn("<dt>Distance</dt><dd>1.2 ATR under the mark</dd>", html)
        self.assertIn("<dt>Touches</dt><dd>2</dd>", html)
        self.assertIn("Where the stops pile up", html)
        self.assertIn("The hunt runs here first — the longs&#39; stops", html)
        self.assertIn("Recomputed every minute", html)

    def test_a_swing_and_a_round_number(self):
        draw = self.out["draw"]
        self.assertIn('<span class="sv-sig-side">LEVEL</span>', draw)
        self.assertIn("The last swing still held", draw)
        self.assertIn("The draw after the hunt — the bias is long at 0.60", draw)
        self.assertNotIn("Touches", draw)
        rnd = self.out["round"]
        self.assertIn("A round number the crowd watches", rnd)
        self.assertNotIn("sv-sig-chip--live", rnd, "no role: not in the path")

    def test_a_position_s_card_has_its_levels_r_age_leverage_and_thesis(self):
        html = self.out["pos"]
        self.assertIn('<span class="sv-sig-side">LONG</span>', html)
        self.assertIn("golden &lt;b&gt;cross&lt;/b&gt;", html, "escaped")
        self.assertIn("<b>1.08000</b>", html)
        self.assertIn("<b>1.07500</b>", html)
        self.assertIn("<b>1.09000</b>", html)
        self.assertIn("<dt>Now</dt><dd>+0.37R · +1.20%</dd>", html)
        self.assertIn("<dt>Open for</dt><dd>30 h</dd>", html)
        self.assertIn("<dt>Leverage</dt><dd>5x</dd>", html)
        self.assertIn("<dt>Soft stop</dt><dd>1.07800</dd>", html)
        self.assertIn("REAL MONEY", html)
        self.assertIn("Stop at the broker", html)
        self.assertIn('sv-sig-chip--win">Thesis adjust', html)
        self.assertIn("Thesis ALIVE — adjust: the lows were swept.", html)

    def test_a_paper_short_with_little_known_stays_honest(self):
        html = self.out["paperPos"]
        self.assertIn('<span class="sv-sig-side">SHORT</span>', html)
        self.assertIn("Simulated", html)
        self.assertNotIn("REAL MONEY", html)
        self.assertIn("<dt>Now</dt><dd>—</dd>", html)
        self.assertIn("<dt>Open for</dt><dd>2 min</dd>", html)
        self.assertNotIn("Leverage", html)
        self.assertNotIn("Thesis", html, "watch is no verdict to show")

    def test_the_words(self):
        self.assertEqual(self.out["age"], ["2 min", "30 h", "3 d", "—"])
        self.assertEqual(self.out["r"], ["+0.37R", "-1.50R", "—"])


class TheServerFactsTests(TestCase):

    def setUp(self):
        from tests.test_position_review import _quote, _trade
        self.trade = _trade("HOVR", entry="100", initial_stop="99", stop="99",
                            target="103", rule_name="golden_cross",
                            opened_hours_ago=30)
        meta = dict(self.trade.metadata)
        meta.update({"leverage": 5, "care": {"soft_stop": 99.5},
                     "thesis": {"verdict": "adjust", "stop": 99.5,
                                "words": "Thesis ALIVE — adjust: x" * 20}})
        type(self.trade).objects.filter(pk=self.trade.pk).update(metadata=meta)
        self.trade.refresh_from_db()
        _quote("HOVR", 101.0)
        self.user = self.trade.config.user

    def test_each_position_carries_the_card_s_facts(self):
        from dashboard.views import _chart_positions
        from instruments.models import Instrument
        inst = Instrument.objects.get(symbol="HOVR")
        inst.refresh_from_db()
        rows = _chart_positions(self.user, inst)
        self.assertEqual(len(rows), 1)
        p = rows[0]
        self.assertEqual(p["rule"], "golden_cross")
        self.assertEqual((p["entry_text"], p["stop_text"], p["tp_text"]),
                         ("100.00", "99.00", "103.00"))
        self.assertEqual(p["r_now"], 1.0)              # (101-100)/(100-99)
        self.assertGreaterEqual(p["age_s"], 29 * 3600)
        self.assertEqual(p["soft_stop"], 99.5)
        self.assertEqual(p["soft_stop_text"], "99.50")
        self.assertEqual(p["thesis"]["verdict"], "adjust")
        self.assertLessEqual(len(p["thesis"]["words"]), 200)
        self.assertTrue(p["leverage"])

    def test_the_facts_ride_the_chart_reply(self):
        self.client.force_login(self.user)
        body = self.client.get("/api/chart-data/",
                               {"symbol": "HOVR", "timeframe": "1d",
                                "overlays": "1"}).json()
        p = body["positions"][0]
        self.assertEqual(p["r_now"], 1.0)
        self.assertEqual(p["thesis"]["verdict"], "adjust")

    def test_a_row_without_the_extras_is_whole(self):
        from dashboard.views import _chart_positions
        from instruments.models import Instrument
        from tests.test_position_review import _trade
        t = _trade("HOVR2", entry="50", initial_stop="49", stop="49",
                   target=None, cfg_name="hovr2")
        type(t).objects.filter(pk=t.pk).update(metadata={})
        inst = Instrument.objects.get(symbol="HOVR2")
        p = [r for r in _chart_positions(t.config.user, inst)
             if r["id"] == f"bot-{t.pk}"][0]
        self.assertIsNone(p["tp_text"])
        self.assertIsNone(p["r_now"], "no mark: no R")
        self.assertIsNone(p["soft_stop"])
        self.assertIsNone(p["thesis"])


class TheWiringTests(SimpleTestCase):

    def test_the_widget_tries_the_lines_when_no_dot_is_under_the_pointer(self):
        src = widget_source()
        self.assertIn("window.svHoverCards = {", src)
        i = src.find("function onSignalHover(param) {")
        body = src[i:i + 900]
        self.assertIn("if (!sigHover && !sigPin) {", body)
        self.assertIn("showLineCard(lh, param.point.x, param.point.y)", body)
        self.assertIn("function lineHit(param) {", src)
        self.assertIn("mainSeries.priceToCoordinate(price)", src)
        self.assertIn("['soft stop', p.soft_stop]", src)

    def test_positions_first_then_the_levels_each_behind_its_toggle(self):
        src = widget_source()
        i = src.find("function lineHit(param) {")
        body = src[i:i + 1500]
        self.assertLess(body.find("if (activeInds.positions) {"),
                        body.find("if (activeInds.levels) {"))

    def test_the_level_card_takes_the_pools_gold_and_the_map_s_role(self):
        src = widget_source()
        self.assertIn(".sv-sig-card--level {", src)
        self.assertIn("api.levelCard(hit.item, POSMAP)", src)
        self.assertIn("POSMAP = (map && map.ok) ? map : null;", src)

    def test_the_caption_s_components_are_its_tooltip(self):
        src = widget_source()
        self.assertIn("posLegendEl.title = said.join('\\n');", src)
