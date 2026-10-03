"""The positioning map (bot_program/positioning.py, 2026-10-03): who is
already placed, where their stops are, where the market is pulled — and
what that means for one side.

The operator: "calculate the chances other bot teams take those trades or
the contrary one... understand how other actors are already placed and
how they will behave depending on their targets and stops... identify the
liquidity pools... give them a visual". Said honestly: nobody sees another
desk's orders; what is read is the crowd (COT, funding, flow, sentiment),
the pools where its stops sit, the hunt and the draw, and the proving
ground's word on whether a pool sweep reverses (the `pool_sweep` family).

Run with:  python manage.py test tests.test_positioning
"""
from datetime import timedelta
from decimal import Decimal
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
from django.conf import settings
from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from bot_program import positioning as P


# ── fixtures ──────────────────────────────────────────────────────────────

def _df(rows):
    idx = pd.date_range("2026-09-01", periods=len(rows), freq="4h")
    return pd.DataFrame([{"open": o, "high": h, "low": lo, "close": c,
                          "volume": v} for o, h, lo, c, v in rows], index=idx)


def _flat(n, c=100.0, half=1.0, v=1.0):
    return [(c, c + half, c - half, c, v)] * n


def _seed(symbol, closes, *, asset_class="crypto"):
    """4h bars, oldest first; equal lows at 96 (bars 15 and 35) and a
    swing high at 104 (bar 25) when `closes` is the default tape."""
    from instruments.models import Instrument
    from market_data.models import PriceData
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class})
    start = timezone.now() - timedelta(hours=4 * len(closes))
    PriceData.objects.bulk_create([PriceData(
        instrument=inst, timeframe="4h",
        timestamp=start + timedelta(hours=4 * i), open=c, high=c + 1,
        low=c - 1, close=c, volume=100, source="t")
        for i, c in enumerate(closes)])
    return inst


def _tape():
    closes = [100.0] * 60
    closes[15] = closes[35] = 97.0
    closes[25] = 103.0
    return closes


def _cot(inst, weeks=60, *, top=True, latest_age_days=3):
    """COT rows: the newest at a 3-year extreme (specs long when `top`)."""
    from scraping.models import COTReport
    today = timezone.now().date()
    for w in range(weeks):
        net = 1000 * (w % 7) if w else (9000 if top else -9000)
        COTReport.objects.create(
            instrument=inst,
            report_date=today - timedelta(days=latest_age_days + 7 * w),
            commercial_long=10000, commercial_short=10000 + net,
            non_commercial_long=10000 + net, non_commercial_short=10000,
            open_interest=100000, net_speculative=net)


def _funding(symbol, rate, hours_ago=1):
    from market_data.models_live import FundingRate
    FundingRate.objects.create(
        symbol=symbol, mark_price=Decimal("100"),
        funding_rate=Decimal(str(rate)),
        timestamp=timezone.now() - timedelta(hours=hours_ago))


def _canned_map(**over):
    base = {"ok": True, "symbol": "X", "asset_class": "forex", "why": "",
            "mark": 100.0, "atr": 2.0,
            "crowd": {"score": 0.7, "label": "crowded long",
                      "components": {"cot_speculators": {
                          "score": 0.7, "weight": 1.0, "words": "COT 85"}}},
            "stops": {"below": {"price": 96.0, "kind": "equal lows (2 touches)",
                                "side": "below", "pool": True, "touches": 2,
                                "atr_away": 2.0}, "above": None},
            "bias": None, "bias_confidence": None,
            "path": [{"leg": "hunt", "side": "below", "price": 96.0,
                      "kind": "equal lows (2 touches)", "pool": True,
                      "touches": 2, "atr_away": 2.0, "why": "the longs' stops"},
                     {"leg": "draw", "side": "above", "why": "no bias"}],
            "odds": {"verdict": "unjudged", "why": "not yet"},
            "words": "Crowd crowded long (COT 85). Its stops sit under the "
                     "equal lows 96 (2 touches), 2 ATR: a hunt runs there "
                     "first.", "levels_n": 3}
    base.update(over)
    return base


# ═══ 1. the crowd ═════════════════════════════════════════════════════════

class TheCrowdTests(TestCase):

    def test_cot_and_funding_make_a_crowded_long(self):
        inst = _seed("PC1USD", _tape())
        _cot(inst, top=True)
        _funding("PC1USDT", 0.0004)
        crowd = P.crowd_read("PC1USD", "crypto")
        self.assertEqual(crowd["label"], "crowded long")
        self.assertGreaterEqual(crowd["score"], P.CROWDED)
        c = crowd["components"]
        self.assertEqual(c["cot_speculators"]["score"], 1.0)
        self.assertEqual(c["cot_speculators"]["weight"], 1.0)
        self.assertIn("speculators' COT index 100", c["cot_speculators"]["words"])
        # the hedgers are the other side of the crowd's trade: sign flipped
        self.assertEqual(c["cot_commercials"]["score"], 1.0)
        self.assertEqual(c["cot_commercials"]["weight"], 0.5)
        self.assertAlmostEqual(c["funding"]["score"], 0.8)
        self.assertIn("longs pay", c["funding"]["words"])

    def test_a_short_crowd_reads_the_other_way(self):
        inst = _seed("PC2USD", _tape())
        _cot(inst, top=False)
        _funding("PC2USDT", -0.0006)
        crowd = P.crowd_read("PC2USD", "crypto")
        self.assertEqual(crowd["label"], "crowded short")
        self.assertEqual(crowd["components"]["cot_speculators"]["score"], -1.0)
        self.assertEqual(crowd["components"]["funding"]["score"], -1.0)
        self.assertIn("shorts pay", crowd["components"]["funding"]["words"])

    def test_what_cannot_be_read_is_said_and_weighs_nothing(self):
        _seed("PC3", _tape(), asset_class="forex")
        crowd = P.crowd_read("PC3", "forex")
        self.assertEqual(crowd["label"], "unread")
        self.assertIsNone(crowd["score"])
        spec = crowd["components"]["cot_speculators"]
        self.assertIsNone(spec["score"])
        self.assertIn("no COT report", spec["words"])
        self.assertNotIn("weight", spec)
        self.assertNotIn("funding", crowd["components"], "forex has none")

    def test_a_stale_funding_print_is_not_read(self):
        _seed("PC4USD", _tape())
        _funding("PC4USDT", 0.0004, hours_ago=P.FUNDING_MAX_AGE_H + 1)
        crowd = P.crowd_read("PC4USD", "crypto")
        self.assertIsNone(crowd["components"]["funding"]["score"])
        self.assertIn("no funding print", crowd["components"]["funding"]["words"])

    def test_the_flow_is_the_share_of_volume_on_up_closes(self):
        rows = []
        for i in range(30):
            up = i % 3 != 0                      # two up-closes for one down
            rows.append((100.0, 101.0, 99.0, 100.5 if up else 99.5,
                         300.0 if up else 100.0))
        crowd = P.crowd_read("NOSYM", "stock", _df(rows))
        v = crowd["components"]["volume"]
        self.assertGreater(v["score"], 0.5)
        self.assertEqual(v["weight"], 0.5)
        self.assertIn("% of the recent volume on up-closes", v["words"])
        flat = P.crowd_read("NOSYM", "stock", _df(_flat(30)))
        self.assertIsNone(flat["components"]["volume"]["score"])

    def test_a_social_snapshot_counts_half_and_is_clipped(self):
        from scraping.models import SentimentSnapshot
        inst = _seed("PC5", _tape(), asset_class="stock")
        SentimentSnapshot.objects.create(
            instrument=inst, source="x", timestamp=timezone.now(),
            composite_score=1.7)
        crowd = P.crowd_read("PC5", "stock")
        s = crowd["components"]["sentiment"]
        self.assertEqual((s["score"], s["weight"]), (1.0, 0.5))
        self.assertEqual(crowd["label"], "crowded long")

    def test_the_labels_and_the_weights(self):
        self.assertEqual([P._label(x) for x in (0.6, 0.3, 0.0, -0.3, -0.6, None)],
                         ["crowded long", "leaning long", "balanced",
                          "leaning short", "crowded short", "unread"])
        self.assertEqual(P.WEIGHTS, {"cot_speculators": 1.0,
                                     "cot_commercials": 0.5, "funding": 1.0,
                                     "volume": 0.5, "sentiment": 0.5})


# ═══ 2. the map ═══════════════════════════════════════════════════════════

class TheMapTests(TestCase):

    def test_a_crowded_long_s_stops_are_the_hunt_and_the_other_side_the_draw(self):
        inst = _seed("PM1USD", _tape())
        _cot(inst, top=True)
        _funding("PM1USDT", 0.0004)
        pm = P.positioning_map("PM1USD", asset_class="crypto", direction="BUY")
        self.assertTrue(pm["ok"])
        self.assertEqual(pm["crowd"]["label"], "crowded long")
        below = pm["stops"]["below"]
        self.assertEqual((below["price"], below["pool"], below["touches"]),
                         (96.0, True, 2))
        hunt, draw = pm["path"]
        self.assertEqual((hunt["leg"], hunt["side"], hunt["price"]),
                         ("hunt", "below", 96.0))
        self.assertEqual(hunt["why"], "the longs' stops")
        self.assertEqual((draw["leg"], draw["side"]), ("draw", "above"))
        self.assertIn("no bias", draw["why"])
        self.assertIn("Crowd crowded long", pm["words"])
        self.assertIn("Its stops sit under the equal lows 96 (2 touches)",
                      pm["words"])
        self.assertIn("a hunt runs there first", pm["words"])
        self.assertEqual(pm["words"].count("touches"), 1, pm["words"])
        self.assertIn("not yet judged", pm["words"])
        self.assertEqual(pm["odds"]["verdict"], "unjudged")
        self.assertIn("prove generate --families pool_sweep", pm["odds"]["why"])

    def test_a_crowded_short_hunts_the_pools_above(self):
        closes = _tape()
        closes[15] = closes[35] = 103.0                # equal highs at 104
        closes[25] = 97.0
        inst = _seed("PM2USD", closes)
        _cot(inst, top=False)
        _funding("PM2USDT", -0.0005)
        pm = P.positioning_map("PM2USD", asset_class="crypto")
        hunt = pm["path"][0]
        self.assertEqual((hunt["side"], hunt["price"], hunt["why"]),
                         ("above", 104.0, "the shorts' stops"))
        self.assertIn("sit over the equal highs 104", pm["words"])

    def test_a_balanced_crowd_hunts_the_nearer_pool(self):
        _seed("PM3", _tape(), asset_class="forex")      # no COT, no funding
        pm = P.positioning_map("PM3", asset_class="forex")
        self.assertEqual(pm["crowd"]["label"], "unread")
        hunt = pm["path"][0]
        self.assertIn("the nearer pool", hunt["why"])
        self.assertEqual(hunt["side"], "above")          # the recent high, 0.5 ATR
        self.assertIn("Crowd unread", pm["words"])

    def test_the_proving_ground_s_word_is_quoted_when_it_exists(self):
        from backtester.models_proving import ProvingVerdict
        inst = _seed("PM4USD", _tape())
        _cot(inst, top=True)
        ProvingVerdict.objects.create(
            run_id="g1", family="pool_sweep", direction="long",
            asset_class="crypto", timeframe="4h", policy="care",
            generated=True, filter="none", verdict="proven",
            expectancy=0.21, win_rate=0.58, trades_n=120,
            why="+0.21R a trade")
        pm = P.positioning_map("PM4USD", asset_class="crypto")
        self.assertEqual(pm["odds"]["verdict"], "proven")
        self.assertEqual(pm["odds"]["n"], 120)
        self.assertIn("Pool sweeps on crypto: PROVEN (+0.21R a trade, 58% won)",
                      pm["words"])

    def test_no_bars_is_unread_said(self):
        pm = P.positioning_map("NOBARS", asset_class="forex", direction="BUY")
        self.assertFalse(pm["ok"])
        self.assertIn("Positioning unread", pm["words"])
        c = P.compact(pm)
        self.assertFalse(c["ok"])
        self.assertIn("too few bars", c["why"])

    def test_compact_carries_what_the_surfaces_need(self):
        c = P.compact(_canned_map(side=P.side_read(_canned_map(), "BUY")))
        self.assertEqual(sorted(c), ["bias", "bias_confidence", "components",
                                     "label", "odds", "ok", "path", "score",
                                     "side", "stops", "words"])
        self.assertEqual(c["components"]["cot_speculators"],
                         {"score": 0.7, "words": "COT 85"})


class TheSideTests(SimpleTestCase):

    def test_with_the_crowd_your_stop_is_where_the_hunt_goes(self):
        s = P.side_read(_canned_map(), "BUY")
        self.assertTrue(s["with_crowd"])
        self.assertFalse(s["against_crowd"])
        self.assertAlmostEqual(s["share_on_your_side"], 0.85)
        self.assertTrue(s["hunt_hits_you"])
        self.assertIn("You join the crowd (85%", s["words"])
        self.assertIn("under 96", s["words"])
        self.assertIn("wait for the sweep", s["words"])

    def test_against_the_crowd_the_hunt_works_for_you(self):
        s = P.side_read(_canned_map(), "SELL")
        self.assertTrue(s["against_crowd"])
        self.assertAlmostEqual(s["share_on_your_side"], 0.15)
        self.assertFalse(s["hunt_hits_you"])
        self.assertIn("You fade the crowd (15%", s["words"])
        self.assertIn("the hunt of 96 works for you", s["words"])

    def test_a_balanced_or_unread_crowd_leaves_it_to_the_pools(self):
        pm = _canned_map()
        pm["crowd"] = dict(pm["crowd"], score=0.1, label="balanced")
        s = P.side_read(pm, "BUY")
        self.assertFalse(s["with_crowd"])
        self.assertIn("the pools decide", s["words"])
        pm["crowd"] = dict(pm["crowd"], score=None, label="unread")
        s = P.side_read(pm, "BUY")
        self.assertIsNone(s["share_on_your_side"])
        self.assertIn("cannot be read", s["words"])
        self.assertIn("Yours would sit under 96", s["words"])


# ═══ 3. the family the judge sees ═════════════════════════════════════════

class ThePoolSweepFamilyTests(SimpleTestCase):

    def _rows(self):
        rows = _flat(70)
        rows[15] = (97.0, 98.0, 96.0, 97.0, 1.0)
        rows[35] = (97.0, 98.0, 96.0, 97.0, 1.0)
        return rows

    def test_the_first_bar_through_equal_lows_that_closes_back_fires(self):
        from backtester.proving import families as F
        rows = self._rows()
        rows[50] = (100.0, 100.5, 95.5, 100.2, 1.0)
        fires = F.FAMILIES["pool_sweep"].fires(_df(rows), F.LONG)
        self.assertEqual(list(np.flatnonzero(fires)), [50])

    def test_a_close_through_the_pool_is_a_break_and_a_single_swing_no_pool(self):
        from backtester.proving import families as F
        rows = self._rows()
        rows[50] = (100.0, 100.2, 95.0, 95.5, 1.0)
        self.assertEqual(F.FAMILIES["pool_sweep"].fires(_df(rows), F.LONG).sum(), 0)
        rows = _flat(70)
        rows[15] = (97.0, 98.0, 96.0, 97.0, 1.0)
        rows[50] = (100.0, 100.5, 95.5, 100.2, 1.0)
        self.assertEqual(F.FAMILIES["pool_sweep"].fires(_df(rows), F.LONG).sum(), 0)

    def test_the_short_mirror_sweeps_equal_highs(self):
        from backtester.proving import families as F
        rows = _flat(70)
        rows[15] = (103.0, 104.0, 102.0, 103.0, 1.0)
        rows[35] = (103.0, 104.0, 102.0, 103.0, 1.0)
        rows[50] = (100.0, 104.5, 99.5, 99.8, 1.0)
        fires = F.FAMILIES["pool_sweep"].fires(_df(rows), F.SHORT)
        self.assertEqual(list(np.flatnonzero(fires)), [50])

    def test_it_is_a_generator_family_not_a_live_rule(self):
        from backtester.proving import families as F
        fam = F.FAMILIES["pool_sweep"]
        self.assertEqual(fam.live_rules, {})
        self.assertEqual(fam.defaults, {"touches": 2})
        self.assertEqual(fam.grid, [{"touches": 2}, {"touches": 3}])


# ═══ 4. the surfaces ══════════════════════════════════════════════════════

class TheSurfacesTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("pos_u", password="x")
        self.client.force_login(self.user)

    def test_the_ticket_carries_the_map_as_a_note_never_a_gate(self):
        from bot_program.manual_trade import _positioning
        unread = _positioning("NOBARS", "forex", "BUY")
        self.assertFalse(unread["ok"])
        with patch("bot_program.positioning.positioning_map",
                   return_value=_canned_map(side=P.side_read(_canned_map(),
                                                             "BUY"))):
            note = _positioning("X", "forex", "BUY", 100.0)
        self.assertTrue(note["ok"])
        self.assertIn("a hunt runs there first", note["words"])
        self.assertIn("You join the crowd", note["side"]["words"])
        html = (Path(settings.BASE_DIR) / "templates" / "base.html").read_text(
            encoding="utf-8")
        self.assertIn("p.positioning", html)
        self.assertIn("POSITIONING", html)
        self.assertIn("sz-positioning", html)

    def test_the_chart_reply_carries_the_caption(self):
        from instruments.models import Instrument
        Instrument.objects.get_or_create(
            symbol="POSCH", defaults={"name": "P", "asset_class": "forex"})
        body = self.client.get("/api/chart-data/",
                               {"symbol": "POSCH", "timeframe": "1d",
                                "overlays": "1"}).json()
        self.assertIn("positioning", body)
        self.assertFalse(body["positioning"]["ok"])
        self.assertNotIn("positioning", self.client.get(
            "/api/chart-data/", {"symbol": "POSCH", "timeframe": "1d"}).json())
        with patch("dashboard.views._chart_positioning",
                   side_effect=RuntimeError("boom")):
            body = self.client.get("/api/chart-data/",
                                   {"symbol": "POSCH", "timeframe": "1d",
                                    "overlays": "1"}).json()
        self.assertIn("boom", body["positioning_error"])
        self.assertIn("positions", body)

    def test_the_widget_draws_the_caption_from_the_reply(self):
        src = (Path(settings.BASE_DIR) / "templates" / "_partials"
               / "chart_widget.html").read_text(encoding="utf-8")
        self.assertIn('class="sv-pos-legend" id="{{ chart_id }}-pos-legend" hidden',
                      src)
        self.assertIn("applyPositioning(json.positioning)", src)
        self.assertIn("json.positioning_error", src)
        i = src.find("function applyPositioning(map) {")
        self.assertGreater(i, 0)
        self.assertIn("posLegendEl.hidden = !words", src[i:i + 600])

    def test_the_review_reads_it_and_the_model_sees_it(self):
        from brain.position_review import bot_position, measure
        from brain.position_review_agent import (PositionReviewerAgent,
                                                 build_snapshot)
        from tests.test_position_review import _quote, _trade
        trade = _trade("POSRV", entry="100", initial_stop="99", stop="99",
                       target="103")
        _quote("POSRV", 101.0)
        with patch("bot_program.positioning.positioning_map",
                   return_value=_canned_map()), \
                patch("brain.thesis_check.structure_read",
                      return_value={"ok": False, "why": "none"}):
            facts = measure(bot_position(trade))
        self.assertTrue(facts["positioning"]["ok"])
        self.assertEqual(facts["positioning"]["label"], "crowded long")
        snap = build_snapshot({"position": bot_position(trade),
                               "facts": facts, "triggers": []})
        self.assertEqual(snap["positioning"]["label"], "crowded long")
        from types import SimpleNamespace
        prompt = PositionReviewerAgent.get_system_prompt(SimpleNamespace())
        self.assertIn("`positioning` is the crowd map", prompt)
        self.assertIn("No field in it is a probability", prompt)

    def test_a_failed_read_leaves_the_review_whole(self):
        from brain.position_review import bot_position, measure
        from tests.test_position_review import _quote, _trade
        trade = _trade("POSRV2", entry="100", initial_stop="99", stop="99",
                       target="103")
        _quote("POSRV2", 101.0)
        with patch("bot_program.positioning.positioning_map",
                   side_effect=RuntimeError("down")), \
                patch("brain.thesis_check.structure_read",
                      return_value={"ok": False, "why": "none"}):
            facts = measure(bot_position(trade))
        self.assertFalse(facts["positioning"]["ok"])
        self.assertIn("positioning unread", facts["positioning"]["why"])
        self.assertEqual(facts["unrealized_r"], 1.0)


class TheWeekendMarkTests(TestCase):
    """2026-10-03, a Saturday: every forex and stock position read "no
    usable mark" from the Friday bell to the Sunday open, and the review
    went blind. A shut market's last close is its mark."""

    def _bar(self, symbol, close, hours_ago):
        from instruments.models import Instrument
        from market_data.models import PriceData
        inst, _ = Instrument.objects.get_or_create(
            symbol=symbol, defaults={"name": symbol, "asset_class": "forex"})
        PriceData.objects.create(
            instrument=inst, timeframe="4h",
            timestamp=timezone.now() - timedelta(hours=hours_ago),
            open=close, high=close + 1, low=close - 1, close=close, source="t")

    def test_a_shut_market_s_last_close_is_the_mark(self):
        from brain.position_review import usable_mark
        self._bar("WKND", 1.2345, hours_ago=30)
        with patch("core.exchange_status.market_clock",
                   return_value={"is_open": False}):
            price, source = usable_mark("WKND")
        self.assertAlmostEqual(price, 1.2345)
        self.assertEqual(source, "last close (market shut)")

    def test_an_open_market_with_a_stale_quote_is_still_no_mark(self):
        from brain.position_review import usable_mark
        self._bar("WKND2", 1.2345, hours_ago=30)
        with patch("core.exchange_status.market_clock",
                   return_value={"is_open": True}):
            price, reason = usable_mark("WKND2")
        self.assertIsNone(price)
        self.assertIn("no fresh quote", reason)

    def test_a_bar_older_than_the_window_is_a_dead_feed_not_a_mark(self):
        from brain.position_review import SHUT_MARK_MAX_AGE_DAYS, usable_mark
        self._bar("WKND3", 1.2345,
                  hours_ago=24 * SHUT_MARK_MAX_AGE_DAYS + 1)
        with patch("core.exchange_status.market_clock",
                   return_value={"is_open": False}):
            price, _reason = usable_mark("WKND3")
        self.assertIsNone(price)


class TheCommandTests(TestCase):

    def test_the_map_is_printed(self):
        inst = _seed("PMCMD", _tape())
        _cot(inst, top=True)
        _funding("PMCMDT", 0.0004)
        out = StringIO()
        call_command("positioning", "PMCMD", "--side", "BUY", stdout=out)
        text = out.getvalue()
        self.assertIn("crowd: crowded long", text)
        self.assertIn("cot_speculators", text)
        self.assertIn("pool below 96", text)
        self.assertIn("hunt  below", text)
        self.assertIn("UNJUDGED", text)
        self.assertIn("You join the crowd", text)
        out = StringIO()
        call_command("positioning", "NOPE", stdout=out)
        self.assertIn("no instrument NOPE", out.getvalue())

    def test_json_and_the_registry(self):
        import json
        from core import ops_commands
        _seed("PMJSON", _tape())
        out = StringIO()
        call_command("positioning", "PMJSON", "--json", stdout=out)
        self.assertTrue(json.loads(out.getvalue())["ok"])
        entry = ops_commands.get("positioning")
        self.assertTrue(entry["read_only"])
        self.assertFalse(ops_commands.is_runnable(entry), "takes a symbol")
