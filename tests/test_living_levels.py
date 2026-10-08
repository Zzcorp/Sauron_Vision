"""The living levels on the chart (2026-10-03).

The operator: "identify the liquidity pools too... and give them a visual
like the pivot points and reaction prices, removing or changing them as
you go". smart_money.living_levels reads the crowd's levels on BOTH sides
of the mark — the SAME crowd_levels the position care moves a stop beyond
— and the chart draws them with every overlay refresh: a swing a bar has
traded through is not sent any more, so it is gone on the next paint.

Run with:  python manage.py test tests.test_living_levels
"""
import unittest
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import User
from django.core.cache import cache
from django.template.loader import render_to_string
from django.test import TestCase
from django.utils import timezone

from tests.test_chart_signal_markers import NODE, _blocks, _node


def _seed(symbol, closes, *, asset_class="stock", half=1.0):
    """4h bars, oldest first, each `half` either side of its close."""
    from instruments.models import Instrument
    from market_data.models import PriceData
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class})
    start = timezone.now() - timedelta(hours=4 * len(closes))
    PriceData.objects.bulk_create([PriceData(
        instrument=inst, timeframe="4h",
        timestamp=start + timedelta(hours=4 * i), open=c, high=c + half,
        low=c - half, close=c, source="t") for i, c in enumerate(closes)])
    return inst


def _tape(swept=False):
    """Flat at 100 with a swing low (96) at bar 20 and a swing high (104)
    at bar 35; with `swept`, bar 45 trades down through the swing low."""
    closes = [100.0] * 60
    closes[20] = 97.0
    closes[35] = 103.0
    if swept:
        closes[45] = 94.0
    return closes


def _pairs(read, *fields):
    return {tuple(lvl[f] for f in fields) for lvl in read["levels"]}


def widget(**ctx):
    base = {"chart_id": "t", "symbol": "EURUSD", "height": "420",
            "timeframe": "1d"}
    base.update(ctx)
    return render_to_string("_partials/chart_widget.html", base)


def widget_source():
    return (Path(settings.BASE_DIR) / "templates" / "_partials"
            / "chart_widget.html").read_text(encoding="utf-8")


# ═══ A. The read ══════════════════════════════════════════════════════════

class TheReadTests(TestCase):

    def test_both_sides_of_the_mark_in_the_care_s_own_vocabulary(self):
        from bot_program.smart_money import living_levels
        _seed("LVL_A", _tape())
        read = living_levels("LVL_A")
        self.assertEqual(read["price"], 100.0)
        self.assertGreater(read["atr"], 0)
        got = _pairs(read, "price", "kind", "side")
        self.assertIn((96.0, "swing low", "below"), got)
        self.assertIn((104.0, "swing high", "above"), got)
        self.assertIn((99.0, "recent low", "below"), got)
        self.assertIn((101.0, "recent high", "above"), got)
        self.assertIn((95.0, "round number", "below"), got)
        self.assertIn((105.0, "round number", "above"), got)
        # sorted by price, each with its distance in ATRs
        prices = [lvl["price"] for lvl in read["levels"]]
        self.assertEqual(prices, sorted(prices))
        swing = [lvl for lvl in read["levels"] if lvl["price"] == 96.0][0]
        self.assertAlmostEqual(swing["atr_away"], 4.0 / read["atr"], places=1)
        self.assertFalse(swing["pool"])

    def test_a_swept_swing_is_not_a_level_any_more(self):
        """Bar 45 trades through the 96 swing low: whoever kept a stop
        under it has been taken. The new low it printed is the level now."""
        from bot_program.smart_money import living_levels
        _seed("LVL_B", _tape(swept=True))
        got = _pairs(living_levels("LVL_B"), "price", "kind")
        self.assertNotIn((96.0, "swing low"), got)
        self.assertIn((93.0, "swing low"), got)
        self.assertIn((104.0, "swing high"), got)

    def test_the_sides_follow_the_mark_given(self):
        """At a live mark of 102 the 100 round number is under the price
        and the 101 extreme is no longer over it."""
        from bot_program.smart_money import living_levels
        _seed("LVL_C", _tape())
        read = living_levels("LVL_C", Decimal("102"))
        self.assertEqual(read["price"], 102.0)
        got = _pairs(read, "price", "kind", "side")
        self.assertIn((100.0, "round number", "below"), got)
        self.assertIn((96.0, "swing low", "below"), got)
        self.assertIn((104.0, "swing high", "above"), got)
        self.assertNotIn((101.0, "recent high", "above"), got)

    def test_a_pool_is_marked_as_one(self):
        """Two swing lows at the same price are equal lows: the stops
        pile up under them, and the chart draws them heavier."""
        from bot_program.smart_money import living_levels
        closes = [100.0] * 60
        closes[15] = closes[35] = 97.0
        _seed("LVL_D", closes)
        pools = [lvl for lvl in living_levels("LVL_D")["levels"]
                 if lvl["pool"]]
        self.assertEqual(len(pools), 1, pools)
        self.assertEqual(pools[0]["price"], 96.0)
        self.assertEqual(pools[0]["kind"], "equal lows (2 touches)")
        self.assertEqual(pools[0]["side"], "below")

    def test_no_bars_no_levels(self):
        from bot_program.smart_money import living_levels
        self.assertIsNone(living_levels("LVL_NOBARS"))
        _seed("LVL_THIN", [100.0] * 10)
        self.assertIsNone(living_levels("LVL_THIN"))

    def test_the_reach_is_the_position_care_s(self):
        from bot_program import smart_money as sm
        self.assertEqual(sm.LIVING_REACH_ATR,
                         3.0 + sm.HUNT_DEPTH_ATR + sm.MAX_WIDEN_ATR)


# ═══ B. The endpoint ══════════════════════════════════════════════════════

class TheEndpointTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("lvl_u", password="x")
        self.client.force_login(self.user)
        for sym in ("LVL_E", "LVL_F", "LVL_G", "LVL_H"):
            cache.delete("chart:levels:" + sym)

    def _get(self, symbol, **extra):
        q = {"symbol": symbol, "timeframe": "1d"}
        q.update(extra)
        return self.client.get("/api/chart-data/", q).json()

    def test_the_levels_ride_the_overlay_reply(self):
        _seed("LVL_E", _tape())
        rows = self._get("LVL_E", overlays="1")["levels"]
        swing = [r for r in rows if r["kind"] == "swing low"]
        self.assertEqual(len(swing), 1, rows)
        self.assertEqual(swing[0]["price"], 96.0)
        self.assertEqual(swing[0]["side"], "below")
        self.assertEqual(float(swing[0]["text"]), 96.0)
        self.assertIn("atr_away", swing[0])

    def test_not_asked_not_sent(self):
        _seed("LVL_F", _tape())
        self.assertNotIn("levels", self._get("LVL_F"))

    def test_no_bars_is_an_empty_list_not_a_missing_key(self):
        """The widget clears its lines on [] and leaves them alone on a
        missing key; a symbol with no 4h bars has no level to draw."""
        from instruments.models import Instrument
        Instrument.objects.get_or_create(
            symbol="LVL_G", defaults={"name": "G", "asset_class": "stock"})
        self.assertEqual(self._get("LVL_G", overlays="1")["levels"], [])

    def test_a_levels_failure_costs_neither_the_chart_nor_the_positions(self):
        _seed("LVL_H", _tape())
        with patch("dashboard.views._chart_levels",
                   side_effect=RuntimeError("boom")):
            body = self._get("LVL_H", overlays="1")
        self.assertIn("bars", body)
        self.assertIn("positions", body)
        self.assertNotIn("levels", body)
        self.assertIn("boom", body["levels_error"])

    def test_one_read_a_minute_per_symbol(self):
        from dashboard.views import LEVELS_TTL
        _seed("LVL_E", _tape())
        with patch("bot_program.smart_money.living_levels",
                   return_value={"price": 100.0, "atr": 2.0, "timeframe": "4h",
                                 "levels": [{"price": 96.0, "kind": "swing low",
                                             "side": "below", "pool": False,
                                             "atr_away": 2.0}]}) as read:
            first = self._get("LVL_E", overlays="1")["levels"]
            second = self._get("LVL_E", overlays="1")["levels"]
        self.assertEqual(read.call_count, 1)
        self.assertEqual(first, second)
        self.assertEqual(LEVELS_TTL, 60)


# ═══ C. The widget ════════════════════════════════════════════════════════

#: the chips' words (2026-10-07): a pool with the server's anchors and the
#: map's hunt on it, and a pool row cached before the anchors (no touches,
#: no members), digested and named by the pure svLevels.
CHIP_RUN = r"""
var L = window.svLevels;
var rows = [
    {price: 1.08226, text: '1.08226', kind: 'equal lows (2 touches)', side: 'below',
     pool: true, atr_away: 2.05, touches: 2, top: 1.08241, bottom: 1.08211,
     members: [{price: 1.08211, origin: 1791000000}, {price: 1.08241, origin: 1791100000}],
     origin: 1791000000},
    {price: 1.092, text: '1.09200', kind: 'equal highs (2 touches)', side: 'above',
     pool: true, atr_away: 4.08}
];
var map = {path: [{leg: 'hunt', price: 1.08226, why: "the longs' stops"}]};
var items = L.digest(rows, map, function (v) { return v.toFixed(5); });
var hunt = items.filter(function (l) { return l.role === 'hunt'; })[0];
var eqh = items.filter(function (l) { return l.price === 1.092; })[0];
process.stdout.write(JSON.stringify({
    hunt: L.chipText(hunt, false), hunt_phone: L.chipText(hunt, true),
    eqh: L.chipText(eqh, false), eqh_touches: eqh.touches}));
"""


class TheWidgetTests(TestCase):

    def test_the_button_is_there_and_on_by_default(self):
        html = widget()
        self.assertIn('data-ind="levels"', html)
        self.assertIn('class="sv-ind-btn active" data-ind="levels"', html)
        self.assertIn("activeInds.levels === undefined) activeInds.levels = true",
                      html)

    def test_the_levels_are_adopted_like_the_positions(self):
        """An array (empty included) replaces what is on screen, a missing
        key leaves it alone, and a levels_error is said in the console
        without blanking the positions in the same reply."""
        src = widget_source()
        i = src.find("var overlayFresh = false;")
        self.assertGreater(i, 0)
        block = src[i:i + 2000]
        self.assertIn("Array.isArray(json.levels)", block)
        self.assertIn("LEVELS = json.levels; overlayFresh = true;", block)
        self.assertIn("json.levels_error", block)
        guard = src.find("if (seq !== loadSeq) return;")
        self.assertGreater(src.find("LEVELS = json.levels;"), guard)

    def test_they_are_redrawn_on_every_paint_and_die_with_the_series(self):
        src = widget_source()
        i = src.find("function applyOverlays(bars) {")
        body = src[i:i + 400]
        self.assertLess(body.find("applyPositions(bars);"),
                        body.find("applyLevels();"))
        died = src.find("posLines = []; /* they died with the series */")
        self.assertGreater(died, 0)
        # one layer, no price line (2026-10-07): the layer is dropped with
        # the series and re-attached on the new one
        self.assertIn("lvlLayer = null;", src[died:died + 160])
        a = src.find("function addSeries(")
        self.assertGreater(a, 0)
        add = src[a:].split("\n    function ")[0]
        detach = add.find("mainSeries.detachPrimitive(lvlLayer)")
        self.assertGreater(detach, 0)
        self.assertLess(detach, add.find("chart.removeSeries(mainSeries)"))
        # the early returns repaint them too, with the positions
        self.assertEqual(
            src.count("applyPositions(lastBars); applyLevels();"), 2)

    def test_levels_are_one_layer_and_nothing_takes_the_axis(self):
        """The levels are ONE primitive under the candles (2026-10-07):
        digested by the pure svLevels, painted by the layer, never a price
        line — so none takes the axis. "Heavier" is the node tests' now."""
        src = widget_source()
        i = src.find("function applyLevels() {")
        self.assertGreater(i, 0)
        body = src[i:].split("\n    function ")[0]
        self.assertIn("svLevels.digest(LEVELS, POSMAP, fmtPrice)", body)
        self.assertIn("ensureLevelLayer()", body)
        self.assertIn("activeInds.levels", body)
        self.assertNotIn("createPriceLine", body)
        self.assertIn("'sv-sig-card sv-sig-card--level sv-sig-card--'", src)

    @unittest.skipUnless(NODE, "node is not installed")
    def test_the_title_names_the_pool_and_its_touches(self):
        """The chip names the pool, its touches and its role; a row cached
        before the anchors (no `touches`) still reads its count from its
        kind."""
        pure, _main = _blocks(widget())
        out = _node("var window = {};\n" + pure + "\n" + CHIP_RUN)
        self.assertEqual(out["hunt"], "EQL ×2 · ① HUNT  1.08226")
        self.assertEqual(out["hunt_phone"], "EQL×2 ①HUNT")
        self.assertEqual(out["eqh"], "EQH ×2  1.09200")
        self.assertEqual(out["eqh_touches"], 2)
        self.assertIn("/\\((\\d+) touches\\)/", widget_source())


# ═══ D. The anchors (2026-10-07) ══════════════════════════════════════════
# The operator: "could we improve the visibility and design of liquidity
# areas and pivot points etc. They are too similar and messy". The chart
# draws a pool as an area from its first touch and a swing on the candle
# that printed it, so each row says where it FORMED — keys ADDED for the
# drawing only; what the care, the ticket and the map read is unchanged.

ANCHOR_KEYS = ("origin", "label", "touches", "members", "top", "bottom",
               "zone")
ORIGINAL_FIELDS = ("price", "kind", "side", "pool", "atr_away")


def _epochs(inst):
    """Each seeded 4h bar's stamp as epoch seconds, oldest first."""
    from market_data.models import PriceData
    return [int(r.timestamp.timestamp()) for r in PriceData.objects.filter(
        instrument=inst, timeframe="4h").order_by("timestamp")]


def _row(rows, price, kind):
    got = [r for r in rows if r["kind"] == kind and abs(r["price"] - price) < 1e-9]
    assert len(got) == 1, (price, kind, rows)
    return got[0]


def _crowded_tape():
    """The tape with equal lows (bars 15 and 35, 96.0 and 96.05) and equal
    highs (bars 25 and 45, 104): pools and their swings on both sides."""
    closes = [100.0] * 60
    closes[15], closes[35] = 97.0, 97.05
    closes[25] = closes[45] = 103.0
    return closes


class TheAnchorsTests(TestCase):

    def test_a_swing_row_says_where_it_formed(self):
        from bot_program.smart_money import living_levels
        at = _epochs(_seed("ANC_A", _tape()))
        rows = living_levels("ANC_A")["levels"]
        low, high = _row(rows, 96.0, "swing low"), _row(rows, 104.0, "swing high")
        self.assertEqual(low["origin"], at[20])
        self.assertEqual(low["label"], "L")
        self.assertEqual(high["origin"], at[35])
        self.assertEqual(high["label"], "H")

    def test_every_swing_and_recent_row_gets_an_integer_origin(self):
        from bot_program.smart_money import living_levels
        _seed("ANC_B", _tape())
        rows = [r for r in living_levels("ANC_B")["levels"]
                if r["kind"] in ("swing low", "swing high", "recent low",
                                 "recent high")]
        self.assertEqual(len(rows), 4, rows)
        for r in rows:
            self.assertIsInstance(r["origin"], int, r)
            self.assertNotIsInstance(r["origin"], bool, r)

    def test_the_recent_extreme_is_anchored_in_the_last_five_bars(self):
        """The tail is flat: the first of its five bars printed the low."""
        from bot_program.smart_money import RECENT_EXTREME_BARS, living_levels
        at = _epochs(_seed("ANC_C", _tape()))
        rows = living_levels("ANC_C")["levels"]
        self.assertEqual(RECENT_EXTREME_BARS, 5)
        self.assertEqual(_row(rows, 99.0, "recent low")["origin"], at[55])
        self.assertEqual(_row(rows, 101.0, "recent high")["origin"], at[55])

    def test_a_pool_row_carries_its_members_band_and_touches(self):
        from bot_program.smart_money import living_levels
        closes = [100.0] * 60
        closes[15] = closes[35] = 97.0
        at = _epochs(_seed("ANC_D", closes))
        pool = _row(living_levels("ANC_D")["levels"], 96.0,
                    "equal lows (2 touches)")
        self.assertEqual(pool["touches"], 2)
        self.assertEqual((pool["top"], pool["bottom"]), (96.0, 96.0))
        self.assertEqual([m["origin"] for m in pool["members"]],
                         [at[15], at[35]])
        self.assertEqual([m["price"] for m in pool["members"]], [96.0, 96.0])
        self.assertEqual(pool["origin"], at[15])

    def test_an_uneven_pool_band_spans_its_members(self):
        from bot_program.smart_money import living_levels
        closes = [100.0] * 60
        closes[15], closes[35] = 97.0, 97.05
        _seed("ANC_E", closes)
        read = living_levels("ANC_E")
        pools = [r for r in read["levels"] if r["pool"]]
        self.assertEqual(len(pools), 1, pools)
        pool = pools[0]
        self.assertEqual(pool["bottom"], 96.0)
        self.assertAlmostEqual(pool["top"], 96.05, places=9)
        # The hunt zone is built around the BAND, not the average: under the
        # mark half an ATR past its bottom, a quarter over its top.
        atr = read["atr"]
        self.assertEqual(pool["zone"], [round(96.0 - .5 * atr, 10), round(pool["top"] + .25 * atr, 10)])
        self.assertLess(pool["zone"][0], round(pool["price"] - .5 * atr, 10))
        self.assertAlmostEqual(pool["price"], (96.0 + 96.05) / 2, places=9)
        self.assertLess(pool["bottom"], pool["price"])
        self.assertLess(pool["price"], pool["top"])
        self.assertEqual(sorted(m["price"] for m in pool["members"]),
                         [pool["bottom"], pool["top"]])

    def test_every_row_carries_its_hunt_zone(self):
        """stop_beyond_the_crowd's own zone: under the mark half an ATR
        past the level and a quarter short of it, the mirror over it."""
        from bot_program.smart_money import living_levels
        _seed("ANC_F", _tape())
        read = living_levels("ANC_F")
        atr, rows = read["atr"], read["levels"]
        self.assertEqual(_row(rows, 96.0, "swing low")["zone"],
                         [round(96 - .5 * atr, 10), round(96 + .25 * atr, 10)])
        self.assertEqual(_row(rows, 104.0, "swing high")["zone"],
                         [round(104 - .25 * atr, 10), round(104 + .5 * atr, 10)])
        self.assertEqual(_row(rows, 95.0, "round number")["zone"],
                         [round(95 - .5 * atr, 10), round(95 + .25 * atr, 10)])
        self.assertEqual(_row(rows, 105.0, "round number")["zone"],
                         [round(105 - .25 * atr, 10), round(105 + .5 * atr, 10)])
        for r in rows:
            self.assertLessEqual(r["zone"][0], r["price"], r)
            self.assertLessEqual(r["price"], r["zone"][1], r)

    def test_the_five_original_fields_are_unchanged(self):
        from bot_program import smart_money as sm
        _seed("ANC_G", _crowded_tape())
        anchored = sm.living_levels("ANC_G")["levels"]
        with patch("bot_program.smart_money._anchor_levels",
                   lambda *a, **k: None):
            bare = sm.living_levels("ANC_G")["levels"]
        self.assertTrue(all(set(r) == set(ORIGINAL_FIELDS) for r in bare))
        self.assertTrue(any(r.get("members") for r in anchored))
        self.assertEqual([tuple(r[f] for f in ORIGINAL_FIELDS) for r in anchored],
                         [tuple(r[f] for f in ORIGINAL_FIELDS) for r in bare])

    def test_crowd_levels_still_returns_bare_tuples(self):
        from bot_program import smart_money as sm
        from signals.smc.pivots import atr as _atr
        _seed("ANC_H", _crowded_tape())
        sm.living_levels("ANC_H")
        df, swings = sm._bars("ANC_H", "4h")
        atr = float(_atr(df)[-1])
        for direction, stop in (("BUY", 97.0), ("SELL", 103.0)):
            got = sm.crowd_levels(direction, 100.0, stop, atr, df, swings)
            self.assertTrue(got, direction)
            for lv in got:
                self.assertIs(type(lv), tuple, lv)
                self.assertEqual(len(lv), 2, lv)
                self.assertIsInstance(lv[0], float, lv)
                self.assertIsInstance(lv[1], str, lv)

    def test_the_map_reads_the_same_with_the_anchors(self):
        from bot_program import positioning as P
        from bot_program.smart_money import living_levels
        _seed("ANC_I", _crowded_tape())
        read = living_levels("ANC_I")
        rows = read["levels"]
        self.assertTrue(any(k in r for r in rows for k in ANCHOR_KEYS))
        stripped = [{k: v for k, v in r.items() if k not in ANCHOR_KEYS}
                    for r in rows]
        for side in ("below", "above"):
            got = P._nearest(rows, side, read["price"])
            self.assertIsNotNone(got, side)
            self.assertTrue(got["pool"], got)
            self.assertEqual(got, P._nearest(stripped, side, read["price"]))

    def test_a_failed_anchor_leaves_the_read(self):
        from bot_program.smart_money import living_levels
        _seed("ANC_J", _tape())
        with patch("bot_program.smart_money._anchor_levels",
                   side_effect=RuntimeError("boom")):
            read = living_levels("ANC_J")
        self.assertIsNotNone(read)
        got = _pairs(read, "price", "kind", "side")
        self.assertIn((96.0, "swing low", "below"), got)
        self.assertIn((104.0, "swing high", "above"), got)
        prices = [r["price"] for r in read["levels"]]
        self.assertEqual(prices, sorted(prices))
        self.assertFalse(any(k in r for r in read["levels"] for k in ANCHOR_KEYS))

    def test_the_reply_passes_the_anchors_through(self):
        user = User.objects.create_user("anc_u", password="x")
        self.client.force_login(user)
        cache.delete("chart:levels:ANC_K")
        at = _epochs(_seed("ANC_K", _tape()))
        rows = self.client.get("/api/chart-data/", {
            "symbol": "ANC_K", "timeframe": "1d", "overlays": "1"}).json()["levels"]
        swings = [r for r in rows if r["kind"] in ("swing low", "swing high")]
        self.assertEqual(len(swings), 2, rows)
        for r in swings:
            self.assertIsInstance(r["origin"], int, r)
            self.assertEqual(len(r["zone"]), 2, r)
            self.assertLess(r["zone"][0], r["price"])
            self.assertLess(r["price"], r["zone"][1])
        low = [r for r in swings if r["kind"] == "swing low"][0]
        self.assertEqual(low["origin"], at[20])
        self.assertEqual(low["label"], "L")
