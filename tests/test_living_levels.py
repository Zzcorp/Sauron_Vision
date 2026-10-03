"""The living levels on the chart (2026-10-03).

The operator: "identify the liquidity pools too... and give them a visual
like the pivot points and reaction prices, removing or changing them as
you go". smart_money.living_levels reads the crowd's levels on BOTH sides
of the mark — the SAME crowd_levels the position care moves a stop beyond
— and the chart draws them with every overlay refresh: a swing a bar has
traded through is not sent any more, so it is gone on the next paint.

Run with:  python manage.py test tests.test_living_levels
"""
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
        self.assertIn("lvlLines = [];", src[died:died + 120])
        # the early returns repaint them too, with the positions
        self.assertEqual(
            src.count("applyPositions(lastBars); applyLevels();"), 2)

    def test_pools_are_drawn_heavier_and_nothing_takes_the_axis(self):
        src = widget_source()
        i = src.find("function applyLevels() {")
        body = src[i:i + 1500]
        self.assertIn("lineWidth: pool ? 2 : 1", body)
        self.assertIn("axisLabelVisible: false", body)
        self.assertIn("mainSeries.removePriceLine(pl)", body)
        self.assertIn("if (!activeInds.levels) return;", body)

    def test_the_title_names_the_pool_and_its_touches(self):
        src = widget_source()
        i = src.find("function levelTitle(l) {")
        body = src[i:i + 600]
        self.assertIn("'POOL '", body)
        self.assertIn("/\\((\\d+) touches\\)/", body)
        self.assertIn("'ROUND'", body)
