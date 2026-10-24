"""THE COMPLEXITY SCORE (bot_program/orcs/complexity.py, spec §7.5.1-7.5.2):
pure, every component through its breakpoints, the weights summing to 1,
stakes added, the floors, the bands with their hysteresis and the hour
held after an urgent wake, and F5 only on a stale mark, stale decision
bars or an unreadable row. No input reads a rank, a scar, probation or a
White Hand. O1 journals the score on every detected wake and routes
nothing.

Run with:  python manage.py test tests.orcs.test_orc_complexity
"""
import ast
import inspect
from datetime import datetime, timedelta
from datetime import timezone as dt_tz
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

NOW = datetime(2026, 10, 21, 15, 0, tzinfo=dt_tz.utc)


def _s(**values):
    """Components with these sub-scores and every other at 0."""
    from bot_program.orcs.constants import COMPLEXITY_WEIGHTS
    return {k: {"s": float(values.get(k, 0.0)), "x": None, "why": "",
                "dash": ""} for k in COMPLEXITY_WEIGHTS}


class TheBreakpointTests(SimpleTestCase):

    def test_weights_sum_to_one_and_the_market_terms(self):
        from bot_program.orcs.complexity import MARKET_KEYS
        from bot_program.orcs.constants import COMPLEXITY_WEIGHTS
        self.assertAlmostEqual(sum(COMPLEXITY_WEIGHTS.values()), 1.0)
        self.assertEqual(set(MARKET_KEYS), {"vol", "regime", "prints",
                                            "news", "stress", "gap"})
        self.assertAlmostEqual(sum(COMPLEXITY_WEIGHTS[k]
                                   for k in MARKET_KEYS), 0.58)

    def test_piecewise(self):
        from bot_program.orcs.complexity import piecewise
        pts = [(1.0, 0), (1.25, 40), (1.6, 75), (2.2, 100)]
        self.assertEqual(piecewise(0.5, pts), 0)
        self.assertEqual(piecewise(1.25, pts), 40)
        self.assertAlmostEqual(piecewise(1.425, pts), 57.5)
        self.assertEqual(piecewise(9.0, pts), 100)
        down = [(0.5, 100), (1.0, 60), (2.0, 20), (3.0, 0)]
        self.assertEqual(piecewise(0.2, down), 100)
        self.assertEqual(piecewise(1.5, down), 40)
        self.assertEqual(piecewise(4.0, down), 0)

    def test_each_component(self):
        from bot_program.orcs.complexity import components
        c = components({
            "atr_ratio": 1.6,
            "regime": {"posture_changed_h": 2.0, "brain_changed": True,
                       "brain_conf": 0.4},
            "prints": {"in_24h": 1, "within_3h": 0, "in_window": False},
            "news": {"blind": False, "ratio": 2.0},
            "stress": {"fresh": True, "score": 40.0, "vix_term": 1.02},
            "gap": {"shut_within_6h": True, "gap_r": 0.5},
            "stop_atr": 1.0,
            "decision_points": 2,
            "size_share": 0.15,
            "disagreement": {"dispersion": 0.5, "flags": ["a drum heard"]},
            "reversibility": {"r": "R4", "shadow": False},
        })
        self.assertEqual(c["vol"]["s"], 75)
        self.assertEqual(c["regime"]["s"], 50, "posture 100 decayed over 4h")
        self.assertEqual(c["prints"]["s"], 20)
        self.assertEqual(c["news"]["s"], 50)
        self.assertEqual(c["stress"]["s"], 60)
        self.assertEqual(c["gap"]["s"], 60)
        self.assertEqual(c["stop"]["s"], 60)
        self.assertEqual(c["decision_point"]["s"], 100)
        self.assertEqual(c["size"]["s"], 40)
        self.assertEqual(c["disagreement"]["s"], 80)
        self.assertEqual(c["reversibility"]["s"], 75)

    def test_the_print_ladder(self):
        from bot_program.orcs.complexity import components
        for prints, want in (
                ({"in_24h": 0, "within_3h": 0, "in_window": False}, 0),
                ({"in_24h": 1, "within_3h": 1, "in_window": False}, 50),
                ({"in_24h": 1, "within_3h": 1, "in_window": True}, 80),
                ({"in_24h": 2, "within_3h": 2, "in_window": False}, 100),
                ({"in_24h": 1, "within_3h": 1, "in_window": False,
                  "major": True}, 100)):
            with self.subTest(prints=prints):
                self.assertEqual(components({"prints": prints})["prints"]["s"],
                                 want)

    def test_a_missing_input_is_a_dash_never_a_silent_zero(self):
        from bot_program.orcs.complexity import components
        c = components({
            "news": {"blind": True, "since": "2026-10-21 09:00"},
            "stress": {"fresh": False, "score": None},
            "prints": {"unread": True},
            "gap": {"shut_within_6h": True, "gap_r": None},
        })
        self.assertEqual(c["news"]["s"], 0, "a blind analyst zeroes news")
        self.assertEqual(c["news"]["dash"],
                         "— (tags blind since 2026-10-21 09:00 UTC)")
        self.assertEqual(c["stress"]["s"], 0)
        self.assertEqual(c["stress"]["dash"],
                         "— (not measured: crisis_mode off)")
        self.assertEqual(c["prints"]["dash"], "— (calendar unread)")
        self.assertEqual(c["gap"]["s"], 60, "an unmeasured gap reads 60")
        for key in ("vol", "stop", "size"):
            self.assertEqual(c[key]["s"], 0)
            self.assertTrue(c[key]["dash"].startswith("— ("), key)

    def test_shadow_candidates_count_half(self):
        from bot_program.orcs.complexity import components
        c = components({"reversibility": {"r": "R4", "shadow": True}})
        self.assertEqual(c["reversibility"]["s"], 37.5)


class TheWorkedExamplesTests(SimpleTestCase):
    """The three examples of §7.5.2, pinned."""

    def test_calm_tuesday_hand_ticket(self):
        from bot_program.orcs.complexity import band, score, stakes
        c = _s(vol=10, prints=20, stop=20, reversibility=40, stress=5)
        st = stakes(real=True, hand=True)
        self.assertEqual(st, 15)
        sc = score(c, st)
        self.assertAlmostEqual(sc, 25.1)
        self.assertEqual(band(sc), "routine")

    def test_nfp_friday(self):
        from bot_program.orcs.complexity import band, score, stakes
        c = _s(vol=55, prints=100, news=50, stress=25, gap=60, stop=40,
               decision_point=60, size=32, disagreement=40,
               reversibility=55)
        self.assertAlmostEqual(score(c, 0), 47.76)
        sc = score(c, stakes(real=True, hand=False))
        self.assertAlmostEqual(sc, 57.76)
        self.assertEqual(round(sc), 58)
        self.assertEqual(band(sc), "complex")

    def test_crisis_day_add_confirm(self):
        from bot_program.orcs.complexity import band, score, stakes
        from bot_program.orcs.constants import COMPLEXITY_WEIGHTS
        c = _s(**{k: 80 for k in COMPLEXITY_WEIGHTS})
        sc = score(c, stakes(real=True, hand=False, level=3))
        self.assertAlmostEqual(sc, 95.0)
        self.assertEqual(band(sc), "extreme")

    def test_clamped(self):
        from bot_program.orcs.complexity import score
        from bot_program.orcs.constants import COMPLEXITY_WEIGHTS
        self.assertEqual(score(_s(**{k: 100 for k in COMPLEXITY_WEIGHTS}),
                               30), 100.0)


class TheBandTests(SimpleTestCase):

    def test_boundaries(self):
        from bot_program.orcs.complexity import band
        for sc, want in ((0, "routine"), (29.9, "routine"),
                         (30, "material"), (54.9, "material"),
                         (55, "complex"), (74.9, "complex"),
                         (75, "extreme"), (100, "extreme")):
            self.assertEqual(band(sc), want, sc)

    def test_hysteresis_of_five_points(self):
        from bot_program.orcs.complexity import band
        self.assertEqual(band(57, prev_band="material"), "material")
        self.assertEqual(band(60, prev_band="material"), "complex")
        self.assertEqual(band(26, prev_band="material"), "material")
        self.assertEqual(band(24.9, prev_band="material"), "routine")
        self.assertEqual(band(90, prev_band="routine"), "extreme")

    def test_held_an_hour_after_an_urgent_wake(self):
        from bot_program.orcs.complexity import band
        until = NOW + timedelta(minutes=60)
        self.assertEqual(band(10, prev_band="complex", hold_until=until,
                              now=NOW), "complex")
        self.assertEqual(band(80, prev_band="complex", hold_until=until,
                              now=NOW), "extreme", "it may still rise")
        self.assertEqual(band(10, prev_band="complex", hold_until=until,
                              now=until + timedelta(seconds=1)), "routine")

    def test_floors_raise_never_lower(self):
        from bot_program.orcs.complexity import band, floors
        self.assertEqual(floors(kind="birth", real=True,
                                binding_on_table=False, day_class="calm",
                                birth=True), "complex", "F2")
        self.assertIsNone(floors(kind="birth", real=False,
                                 binding_on_table=False, day_class="calm",
                                 birth=True))
        self.assertEqual(floors(kind="routine", real=True,
                                binding_on_table=True, day_class="stormy",
                                birth=False), "material", "F3/F4")
        self.assertIsNone(floors(kind="routine", real=True,
                                 binding_on_table=False, day_class="stormy",
                                 birth=False), "nothing binds at L0 in O1")
        self.assertEqual(floors(kind="confirm", real=True,
                                binding_on_table=True, day_class="calm",
                                birth=False), "complex", "F1")
        self.assertEqual(band(10, floor="complex"), "complex")
        self.assertEqual(band(90, floor="material"), "extreme")


class TheFloorF5F6Tests(SimpleTestCase):

    def test_f5_false_with_crisis_mode_off_and_the_analyst_idle(self):
        from bot_program.orcs.complexity import f5
        from bot_program.orcs.integrity import verdict
        v = verdict(mark_source="venue", mark_age_s=30, real=True,
                    decision_tf="4h", frame_fresh=True,
                    frame_end=NOW - timedelta(hours=1), row_ok=True,
                    stale=["— (not measured: crisis_mode off)",
                           "— (tags blind since 2026-10-21 09:00 UTC)"])
        self.assertEqual(f5(v), (False, []))

    def test_f5_on_each_critical_item(self):
        from bot_program.orcs.complexity import f5
        from bot_program.orcs.integrity import verdict
        base = dict(mark_source="venue", mark_age_s=30, real=True,
                    decision_tf="4h", frame_fresh=True,
                    frame_end=NOW - timedelta(hours=1), row_ok=True)
        for change in ({"mark_age_s": 121}, {"mark_source": "quote"},
                       {"frame_fresh": False}, {"row_ok": False}):
            with self.subTest(change=change):
                on, items = f5(verdict(**{**base, **change}))
                self.assertTrue(on)
                self.assertEqual(len(items), 1)

    def test_f6_quiet_only_for_w2_and_w11_on_the_same_hash(self):
        from bot_program.orcs.complexity import f6
        self.assertTrue(f6(["W2"], "h", "h"))
        self.assertTrue(f6(["W2", "W11"], "h", "h"))
        self.assertFalse(f6(["W2"], "h", "g"))
        self.assertFalse(f6(["W2", "W4"], "h", "h"))
        self.assertFalse(f6(["W11"], "h", ""))


class TheDayScoreTests(SimpleTestCase):

    def test_renormalised_over_the_market_terms(self):
        from bot_program.orcs.complexity import day_score
        c = _s(vol=100, regime=100, prints=100, news=100, stress=100,
               gap=100)
        self.assertAlmostEqual(day_score(c), 100.0)
        self.assertAlmostEqual(day_score(_s(prints=50)),
                               50 * 0.12 / 0.58, places=2)

    def test_day_classes(self):
        from bot_program.orcs.complexity import day_class
        kw = dict(posture_level="calm", posture_fresh=True, prints_today=0)
        self.assertEqual(day_class(29.9, **kw), "calm")
        self.assertEqual(day_class(30, **kw), "eventful")
        self.assertEqual(day_class(55, **kw), "stormy")
        self.assertEqual(day_class(5, **{**kw, "posture_level": "crisis"}),
                         "stormy")
        self.assertEqual(day_class(5, **{**kw, "posture_level": "crisis",
                                         "posture_fresh": False}), "calm",
                         "a stale posture is not measured")
        self.assertEqual(day_class(5, **{**kw, "prints_today": 3}),
                         "stormy")


class ThePurityTests(SimpleTestCase):

    def test_no_input_reads_a_rank_scar_probation_or_white_hand(self):
        from bot_program.orcs import complexity
        tree = ast.parse(inspect.getsource(complexity))
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                names.add(node.id.lower())
            elif isinstance(node, ast.Attribute):
                names.add(node.attr.lower())
            elif isinstance(node, ast.alias):
                names.add(node.name.lower())
            elif isinstance(node, ast.ImportFrom):
                names.add((node.module or "").lower())
            elif isinstance(node, ast.Constant) and isinstance(node.value,
                                                               str):
                names.add(node.value.lower())
        for bad in ("rank", "scar", "scars", "probation", "white_hand",
                    "objects", "ai_agents"):
            self.assertNotIn(bad, names)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                self.assertIn(node.module, ("bot_program.orcs.constants",
                                            "datetime", "__future__"),
                              node.module)


class TheReviewTermsTests(SimpleTestCase):
    """Review (O1c): the stop term reads the SIGNED distance (a mark
    already through the stop scores 100, never "far away"), and the regime
    term counts the row's own flip within six bars."""

    def test_a_mark_through_the_stop_scores_one_hundred(self):
        from bot_program.orcs.complexity import components
        self.assertEqual(components({"stop_atr": -2.0})["stop"]["s"], 100.0)
        self.assertEqual(components({"stop_atr": 0.3})["stop"]["s"], 100.0)
        self.assertEqual(components({"stop_atr": 2.0})["stop"]["s"], 20.0)
        self.assertIn("through the stop",
                      components({"stop_atr": -2.0})["stop"]["why"])

    def test_the_signed_distance_on_each_side(self):
        from types import SimpleNamespace

        from bot_program.orcs import wake
        orc = SimpleNamespace(thesis={}, user=None, r_money=None)
        for side, m, want in (("BUY", 97.0, -1.0), ("BUY", 100.0, 2.0),
                              ("SELL", 103.0, -1.0), ("SELL", 100.0, 2.0)):
            trade = SimpleNamespace(side=side, symbol="BTCUSD",
                                    asset_class="crypto", metadata={},
                                    entry_price=100, stop_loss=None)
            stop = 98.0 if side == "BUY" else 102.0
            ctx = {"effective": stop, "m": m, "atr1h": 1.0,
                   "calendar": {"dash": "— (calendar unread)"}}
            with patch("bot_program.orcs.sources.book",
                       return_value={"dash": "— (book unreadable)"}), \
                    patch.object(wake, "_symbol_flip", return_value=True):
                got = wake._position_inputs(orc, trade, ctx, [], None, {})
            with self.subTest(side=side, m=m):
                self.assertAlmostEqual(got["stop_atr"], want)
                self.assertEqual(got["regime"], {"symbol_flip": True})

    def test_the_rows_own_regime_flip(self):
        import pandas as pd

        from bot_program.orcs import wake
        frame = SimpleNamespace(tf="4h")
        df = pd.DataFrame({"close": range(60)})
        with patch("bot_program.orcs.bars.final_df", return_value=df), \
                patch("backtester.proving.simulate.regimes",
                      return_value=["range"] * 55 + ["trend"] * 5):
            self.assertTrue(wake._symbol_flip(frame, None))
        with patch("bot_program.orcs.bars.final_df", return_value=df), \
                patch("backtester.proving.simulate.regimes",
                      return_value=["trend"] * 60):
            self.assertFalse(wake._symbol_flip(frame, None))
        self.assertIsNone(wake._symbol_flip(None, None))

    def test_the_regime_term_is_the_higher_of_the_class_and_the_row(self):
        from bot_program.orcs import wake
        cls_low = {"s": 30.0, "x": None, "why": "the Mind's confidence",
                   "dash": ""}
        got = wake._components({"regime": {"symbol_flip": True},
                                "_market_regime": cls_low})
        self.assertEqual(got["regime"]["s"], 70.0)
        cls_high = {**cls_low, "s": 100.0, "why": "the posture changed"}
        got = wake._components({"regime": {"symbol_flip": True},
                                "_market_regime": cls_high})
        self.assertEqual(got["regime"]["s"], 100.0)
        got = wake._components({"regime": {"symbol_flip": False},
                                "_market_regime": cls_low})
        self.assertEqual(got["regime"]["s"], 30.0)
