"""ICT primitives: displacement, OTE, SMT, inducement, mitigation blocks,
session concepts, bias, IPDA and opening gaps.

Every frame in here is hand-built so the right answer is known before the code
runs, and every primitive is tested on the negative case as well as the
positive one — a pattern detector that only ever sees the pattern is a detector
that has not been tested at all.

Run with:  python manage.py test tests.test_ict_primitives
"""
import datetime as dt

import pandas as pd
from django.test import SimpleTestCase


def frame(bars, start="2024-07-01", freq="15min", tz="UTC"):
    """DataFrame from (open, high, low, close) tuples on a UTC index.

    UTC because that is what the codebase stores; the session tests convert to
    New York themselves rather than being handed a pre-converted index.
    """
    idx = pd.date_range(start, periods=len(bars), freq=freq, tz=tz)
    return pd.DataFrame(
        [{"open": o, "high": h, "low": l, "close": c, "volume": 1.0}
         for o, h, l, c in bars],
        index=idx,
    )


def quiet(n, price=100.0):
    """n identical one-point-range bars — enough to warm ATR up to ~1.0."""
    return [(price, price + 0.5, price - 0.5, price) for _ in range(n)]


def zigzag(points, n, wick=0.3):
    """Bars interpolated between (bar_index, close) control points."""
    closes = []
    for i in range(n):
        for (x0, y0), (x1, y1) in zip(points, points[1:]):
            if x0 <= i <= x1:
                closes.append(y0 + (y1 - y0) * (i - x0) / (x1 - x0))
                break
        else:
            closes.append(points[-1][1])
    bars, prev = [], points[0][1]
    for close in closes:
        bars.append((prev, max(prev, close) + wick, min(prev, close) - wick, close))
        prev = close
    return bars


def swings_of(df):
    from signals.smc.pivots import classify_swings, get_swings
    return classify_swings(get_swings(df))


# The mitigation-block shape, shared by several tests: low 94.5, high 110.5,
# higher low 99.8 that never trades through 94.5, then a close above 110.5.
MITIGATION_BARS = [
    (100, 100.3, 99.7, 100), (100, 100.3, 99.7, 100), (100, 100.3, 99.7, 100),
    (100, 100.3, 98.8, 99), (99, 99.2, 94.5, 95), (95, 99.3, 94.9, 99),
    (99, 103.3, 98.8, 103), (103, 107.3, 102.8, 107), (107, 110.5, 106.8, 110),
    (110, 110.2, 105.8, 106), (106, 106.2, 102.8, 103), (103, 103.2, 100.8, 101),
    (101, 101.2, 99.8, 100), (100, 103.2, 99.9, 103), (103, 106.2, 102.8, 106),
    (106, 109.2, 105.8, 109), (109, 112.2, 108.8, 112), (112, 112.2, 109.8, 110),
    (110, 110.2, 106.8, 107), (107, 107.2, 103.8, 104), (104, 104.2, 101.5, 102),
    (102, 102.2, 100.5, 101), (101, 104.2, 100.8, 104), (104, 107.2, 103.8, 107),
    (107, 110.2, 106.8, 110), (110, 113.2, 109.8, 113),
]


class DisplacementTests(SimpleTestCase):
    """20 quiet bars give ATR ~= 1.0, so the 21st bar's numbers are readable."""

    def test_expansion_is_displacement(self):
        from signals.smc.displacement import measure_displacement
        df = frame(quiet(20) + [(100.0, 106.2, 99.9, 106.0)])
        leg = measure_displacement(df, 20, direction="up")
        self.assertTrue(leg["is_displacement"])
        self.assertEqual(leg["bars"], 1)
        self.assertGreater(leg["atr_multiple"], 4.0)
        self.assertGreater(leg["body_ratio"], 0.9)
        self.assertTrue(0.0 <= leg["score"] <= 1.0)

    def test_drift_beyond_a_level_is_not_displacement(self):
        # The bug this whole module exists for: a 0.3-point close beyond a
        # swing is a break to detect_market_structure_breaks and nothing at all
        # to a trader.
        from signals.smc.displacement import measure_displacement
        df = frame(quiet(20) + [(100.0, 100.9, 99.4, 100.3)])
        leg = measure_displacement(df, 20, direction="up")
        self.assertFalse(leg["is_displacement"])
        self.assertLess(leg["atr_multiple"], 0.5)

    def test_wide_but_wicky_bar_is_not_displacement(self):
        # An 8-point range delivered as a 0.2-point body: violent, indecisive,
        # and not displacement. Size alone must not be enough.
        from signals.smc.displacement import measure_displacement
        df = frame(quiet(20) + [(100.0, 104.0, 96.0, 100.2)])
        leg = measure_displacement(df, 20, direction="up")
        self.assertFalse(leg["is_displacement"])
        self.assertLess(leg["body_ratio"], 0.1)

    def test_a_qualifying_window_survives_a_bigger_non_qualifying_one(self):
        # Bar 20 is a 12.5-point flush and full recovery — 44% body, no
        # displacement. Bar 21 is a clean 3-point expansion: 1.59 ATR, 91% body,
        # displacement by both gates. Measured together the two bars travel
        # 3.7 ATR, which saturates the size score and puts the two-bar window
        # ahead on points (0.63 to 0.54) while it fails the body gate outright.
        # Ranking every window and only then asking whether the winner
        # qualified answered "no displacement" for a chart holding one.
        from signals.smc.displacement import measure_displacement
        df = frame(quiet(20) + [(96.0, 100.5, 88.0, 100.0),
                                (100.0, 103.2, 99.9, 103.0)])
        leg = measure_displacement(df, 21)
        self.assertTrue(leg["is_displacement"])
        self.assertEqual(leg["bars"], 1)
        self.assertEqual(leg["direction"], "up")
        self.assertGreater(leg["body_ratio"], 0.9)
        # The window that outscored it is still the higher-scoring window; it
        # simply is not the answer to "was this displacement".
        two_bar = measure_displacement(df, 21, min_atr_multiple=0.0,
                                       min_body_ratio=0.0)
        self.assertEqual(two_bar["bars"], 2)
        self.assertGreater(two_bar["score"], leg["score"])
        self.assertLess(two_bar["body_ratio"], 0.5)

    def test_a_single_bar_leg_can_carry_its_own_imbalance(self):
        # Bar 20 opens away from bar 19 and never trades back: high[18] 100.5
        # against low[20] 101.5 is a fair value gap, and bar 20 is the bar that
        # completed it. Requiring all three bars of the gap to sit inside the
        # leg made that unreachable for a one-bar leg — the loop had no
        # iterations at all — so the most violent shape ICT recognises always
        # scored zero on imbalance. Nothing past bar 20 is read to see it.
        from signals.smc.displacement import measure_displacement
        df = frame(quiet(20) + [(102.0, 106.0, 101.5, 105.8)])
        leg = measure_displacement(df, 20, direction="up")
        self.assertEqual(leg["bars"], 1)
        self.assertTrue(leg["has_imbalance"])
        self.assertEqual(leg["imbalance"]["type"], "FVG_BULL")
        self.assertEqual(leg["imbalance"]["idx"], 19)
        self.assertAlmostEqual(leg["imbalance"]["low"], 100.5)
        self.assertAlmostEqual(leg["imbalance"]["high"], 101.5)

    def test_cold_atr_returns_none_not_zero(self):
        from signals.smc.displacement import measure_displacement
        df = frame(quiet(20) + [(100.0, 106.2, 99.9, 106.0)])
        self.assertIsNone(measure_displacement(df, 5))
        self.assertIsNone(measure_displacement(df, 999))

    def test_direction_is_signed(self):
        from signals.smc.displacement import measure_displacement
        df = frame(quiet(20) + [(100.0, 106.2, 99.9, 106.0)])
        self.assertFalse(measure_displacement(df, 20, direction="down")["is_displacement"])

    def test_qualify_breaks_copies_and_does_not_mutate(self):
        from signals.smc.displacement import qualify_breaks_with_displacement
        df = frame(quiet(20) + [(100.0, 106.2, 99.9, 106.0)])
        breaks = [{"idx": 20, "type": "BOS_UP", "broken_swing_idx": 3,
                   "broken_swing_price": 100.5}]
        qualified = qualify_breaks_with_displacement(df, breaks)
        self.assertTrue(qualified[0]["displaced"])
        self.assertEqual(qualified[0]["broken_swing_idx"], 3)
        self.assertNotIn("displacement", breaks[0])

    def test_break_inside_atr_warmup_is_unknown_not_false(self):
        from signals.smc.displacement import qualify_breaks_with_displacement
        df = frame(quiet(20) + [(100.0, 106.2, 99.9, 106.0)])
        qualified = qualify_breaks_with_displacement(
            df, [{"idx": 4, "type": "BOS_UP", "broken_swing_idx": 1}])
        self.assertIsNone(qualified[0]["displaced"])
        self.assertIsNone(qualified[0]["displacement_score"])


class OptimalTradeEntryTests(SimpleTestCase):
    IMPULSE_CLOSES = [
        110.0, 109.5, 109.0, 108.5, 108.0, 107.5, 107.0, 106.5, 106.0, 105.5,
        105.0, 104.5, 104.0, 103.5, 103.0, 102.0, 101.0, 100.2, 106.0, 112.0,
        117.0, 119.8, 116.0, 113.0, 111.0, 109.5, 108.5, 107.5, 106.5, 106.0,
    ]

    def impulse_frame(self):
        bars, prev = [], 110.5
        for close in self.IMPULSE_CLOSES:
            bars.append((prev, max(prev, close) + 0.2, min(prev, close) - 0.2, close))
            prev = close
        return frame(bars)

    def test_band_geometry_on_a_100_point_leg(self):
        from signals.smc.fibonacci import ote_zone, retracement_price
        zone = ote_zone(100, 200, "up")
        self.assertAlmostEqual(zone["high"], 138.0)   # 62% back from the high
        self.assertAlmostEqual(zone["low"], 121.0)    # 79% back from the high
        self.assertAlmostEqual(zone["sweet_spot"], 129.5)
        self.assertAlmostEqual(retracement_price(100, 200, "down", 0.705), 170.5)

    def test_sweet_spot_is_the_midpoint_of_the_band(self):
        from signals.smc.fibonacci import OTE_MAX_RATIO, OTE_MIN_RATIO, OTE_SWEET_SPOT
        self.assertAlmostEqual(OTE_SWEET_SPOT, (OTE_MIN_RATIO + OTE_MAX_RATIO) / 2)

    def test_ratio_and_membership(self):
        from signals.smc.fibonacci import in_ote, retracement_ratio
        self.assertAlmostEqual(retracement_ratio(100, 200, "up", 129.5), 0.705)
        self.assertTrue(in_ote(100, 200, "up", 130))
        self.assertFalse(in_ote(100, 200, "up", 150))   # only a 50% retrace

    def test_flat_leg_answers_none_everywhere(self):
        from signals.smc import fibonacci as fib
        self.assertIsNone(fib.ote_zone(100, 100, "up"))
        self.assertIsNone(fib.retracement_ratio(100, 100, "up", 100))
        self.assertIsNone(fib.in_ote(100, 100, "up", 100))
        self.assertIsNone(fib.retracement_levels(100, 100, "up"))
        self.assertIsNone(fib.retracement_price(100, 100, "up", 0.705))
        self.assertIsNone(fib.ote_zone(100, 200, "sideways"))

    def test_impulse_leg_carries_displacement(self):
        from signals.smc.fibonacci import find_impulse_legs
        df = self.impulse_frame()
        legs = find_impulse_legs(df, swings_of(df))
        self.assertEqual(len(legs), 1)
        leg = legs[0]
        self.assertEqual((leg["start_idx"], leg["end_idx"], leg["direction"]),
                         (17, 21, "up"))
        self.assertAlmostEqual(leg["low"], 100.0)
        self.assertAlmostEqual(leg["high"], 120.0)
        self.assertIsNotNone(leg["displacement"])

    def test_entry_fires_only_when_price_is_in_the_band(self):
        from signals.smc.fibonacci import detect_ote_entries
        df = self.impulse_frame()
        swings = swings_of(df)
        setups = detect_ote_entries(df, swings)
        self.assertEqual(len(setups), 1)
        setup = setups[0]
        self.assertEqual(setup["direction"], "LONG")
        self.assertAlmostEqual(setup["entry"], 105.9)          # 70.5% of 100->120
        self.assertAlmostEqual(setup["stop"], 99.0)            # origin less 5% of leg
        self.assertAlmostEqual(setup["target"], 120.0)
        # The reason ICT trades this band at all: ~2R before anything else.
        self.assertAlmostEqual(setup["r_multiple"], 2.04, places=2)

        # Bar 24 sits at a 45% retrace — above the band, so nothing fires.
        self.assertEqual(detect_ote_entries(df, swings, current_idx=24), [])

    def test_no_swings_no_legs(self):
        from signals.smc.fibonacci import detect_ote_entries, find_impulse_legs
        df = frame(quiet(30))
        self.assertEqual(find_impulse_legs(df, []), [])
        self.assertEqual(detect_ote_entries(df, []), [])


class SmtDivergenceTests(SimpleTestCase):
    LEADER = [(0, 100), (8, 110), (16, 102), (24, 115), (32, 104),
              (40, 112), (48, 103), (59, 110)]
    LAGGARD = [(0, 100), (8, 110), (16, 102), (24, 108), (32, 104),
               (40, 112), (48, 103), (59, 110)]

    def test_higher_high_on_one_leg_only(self):
        from signals.smc.smt import detect_smt_divergence
        es = frame(zigzag(self.LEADER, 60))
        nq = frame(zigzag(self.LAGGARD, 60))
        events = detect_smt_divergence(es, nq, "ES", "NQ")
        first = events[0]
        self.assertEqual(first["type"], "SMT_BEAR")
        self.assertEqual(first["idx"], 24)
        self.assertEqual((first["leader"], first["laggard"]), ("ES", "NQ"))
        self.assertGreater(first["leader_curr"], first["leader_prev"])
        self.assertLessEqual(first["laggard_curr"], first["laggard_prev"])
        self.assertGreater(first["divergence_pct"], 0)

    def test_instruments_that_agree_produce_nothing(self):
        from signals.smc.smt import detect_smt_divergence
        es = frame(zigzag(self.LEADER, 60))
        clone = frame(zigzag(self.LEADER, 60))
        self.assertEqual(detect_smt_divergence(es, clone, "ES", "ES2"), [])

    def test_thin_or_disjoint_history_answers_empty(self):
        from signals.smc.smt import align_frames, detect_smt_divergence
        es = frame(zigzag(self.LEADER, 60))
        nq = frame(zigzag(self.LAGGARD, 60))
        self.assertEqual(detect_smt_divergence(es.iloc[:30], nq.iloc[:30], "ES", "NQ"), [])
        self.assertIsNone(align_frames(es.iloc[:30], nq.iloc[:30]))

        elsewhere = nq.copy()
        elsewhere.index = pd.date_range("2025-01-01", periods=60, freq="15min", tz="UTC")
        self.assertEqual(detect_smt_divergence(es, elsewhere, "ES", "NQ"), [])
        self.assertIsNone(align_frames(es, None))

    def test_naive_index_is_read_as_utc_so_alignment_still_works(self):
        from signals.smc.smt import detect_smt_divergence
        es = frame(zigzag(self.LEADER, 60))
        naive = frame(zigzag(self.LAGGARD, 60))
        naive.index = naive.index.tz_localize(None)
        self.assertTrue(detect_smt_divergence(es, naive, "ES", "NQ"))


class InducementTests(SimpleTestCase):
    def setUp(self):
        # Price sits at 110 with a 103 pool below it, and only dips through the
        # pool at bar 27 — so "swept" has a single unambiguous answer.
        self.df = frame(quiet(27, 110.0) + [(110, 110.5, 102.0, 103)] + quiet(2, 103.0))
        self.pool = [{"idx": 10, "type": "L", "price": 103.0}]

    def test_pool_between_zone_and_break_is_the_inducement(self):
        from signals.smc.inducement import find_inducement, zone_is_armed
        found = find_inducement(self.df, self.pool, 99.0, 100.0, 5, 20, "LONG")
        self.assertEqual(found["side"], "sell_side")
        self.assertAlmostEqual(found["price"], 103.0)
        self.assertAlmostEqual(found["separation"], 3.0)
        self.assertTrue(found["swept"])
        self.assertEqual(found["swept_idx"], 27)
        self.assertTrue(zone_is_armed(found))

    def test_pool_too_close_to_the_zone_is_not_a_separate_event(self):
        from signals.smc.inducement import find_inducement
        touching = [{"idx": 10, "type": "L", "price": 100.1}]
        self.assertIsNone(find_inducement(self.df, touching, 99.0, 100.0, 5, 20, "LONG"))

    def test_a_swing_on_the_far_side_of_the_zone_is_not_the_pool(self):
        # A demand zone at 99-100 with two minor lows behind it: one at 97,
        # below the zone entirely, and the real inducement at 103. min() over
        # the pair picks 97, whose separation from the zone is -3 points, and
        # the separation test then answered None for a chart whose inducement
        # was sitting three points overhead. The wrong-side swing is not a
        # near miss, it is not a candidate.
        from signals.smc.inducement import find_inducement
        mixed = [{"idx": 8, "type": "L", "price": 97.0},
                 {"idx": 10, "type": "L", "price": 103.0}]
        found = find_inducement(self.df, mixed, 99.0, 100.0, 5, 20, "LONG")
        self.assertAlmostEqual(found["price"], 103.0)
        self.assertAlmostEqual(found["separation"], 3.0)

        # The short case mirrors it: supply at 109-110, a minor high at 112
        # above the zone and the real pool at 105 below it.
        supply_df = frame(quiet(27, 100.0) + [(100, 108.0, 99.5, 107)]
                          + quiet(2, 107.0))
        mixed_highs = [{"idx": 8, "type": "H", "price": 112.0},
                       {"idx": 10, "type": "H", "price": 105.0}]
        short = find_inducement(supply_df, mixed_highs, 109.0, 110.0, 5, 20, "SHORT")
        self.assertAlmostEqual(short["price"], 105.0)
        self.assertAlmostEqual(short["separation"], 4.0)
        self.assertEqual(short["side"], "buy_side")

    def test_missing_pool_and_cold_atr_both_answer_none(self):
        from signals.smc.inducement import find_inducement, zone_is_armed
        after = [{"idx": 25, "type": "L", "price": 103.0}]
        self.assertIsNone(find_inducement(self.df, after, 99.0, 100.0, 5, 20, "LONG"))
        self.assertIsNone(find_inducement(self.df, self.pool, 99.0, 100.0, 1, 5, "LONG"))
        self.assertIsNone(find_inducement(self.df, self.pool, 99.0, 100.0, 5, 20, "sideways"))
        # No inducement is not "not armed" — the question does not apply.
        self.assertIsNone(zone_is_armed(None))

    def test_detect_inducements_skips_blocks_with_nothing_in_front(self):
        from signals.smc.inducement import detect_inducements
        obs = [{"type": "OB_BULL", "idx": 5, "low": 99.0, "high": 100.0,
                "created_by_break_idx": 20}]
        found = detect_inducements(self.df, self.pool, obs)
        self.assertEqual(len(found), 1)
        self.assertIs(found[0]["order_block"], obs[0])
        self.assertEqual(detect_inducements(self.df, self.pool, []), [])


class MitigationBlockTests(SimpleTestCase):
    def structure(self, bars):
        from signals.smc.structure import detect_market_structure_breaks
        df = frame(bars)
        swings = swings_of(df)
        return df, swings, detect_market_structure_breaks(df, swings)

    def test_unswept_higher_low_makes_a_mitigation_block(self):
        from signals.smc.mitigation import detect_mitigation_blocks
        df, swings, breaks = self.structure(MITIGATION_BARS)
        blocks = detect_mitigation_blocks(df, swings, breaks)
        first = blocks[0]
        self.assertEqual(first["type"], "MB_BULL")
        self.assertEqual(first["idx"], 12)
        self.assertAlmostEqual(first["low"], 99.8)
        self.assertAlmostEqual(first["high"], 101.2)
        self.assertEqual(first["origin_swing_idx"], 12)
        self.assertEqual(first["prior_swing_idx"], 4)
        self.assertEqual(first["created_by_break_idx"], 16)
        self.assertFalse(first["prior_swing_swept"])
        self.assertTrue(first["mitigated"])
        self.assertEqual(first["mitigated_idx"], 21)
        self.assertFalse(first["invalidated"])

    def test_a_swept_low_is_breaker_territory_not_a_mitigation_block(self):
        # The single distinguishing fact: move the higher low to 94.0 so it
        # takes the prior low's liquidity, and this zone stops qualifying.
        from signals.smc.mitigation import detect_mitigation_blocks
        swept = list(MITIGATION_BARS)
        swept[12] = (101, 101.2, 94.0, 100)
        df, swings, breaks = self.structure(swept)
        blocks = detect_mitigation_blocks(df, swings, breaks)
        self.assertNotIn(16, [b["created_by_break_idx"] for b in blocks])

    def test_a_sweep_event_in_the_span_also_vetoes(self):
        from signals.smc.mitigation import detect_mitigation_blocks
        df, swings, breaks = self.structure(MITIGATION_BARS)
        vetoed = detect_mitigation_blocks(
            df, swings, breaks,
            sweeps=[{"type": "SWEEP_LOW", "idx": 10, "swept_swing_idx": 4}],
        )
        self.assertNotIn(16, [b["created_by_break_idx"] for b in vetoed])

    def test_retest_setup_aims_at_a_swing_this_structure_printed(self):
        from signals.smc.mitigation import (
            detect_mitigation_blocks, detect_mitigation_retest_setups,
        )
        df, swings, breaks = self.structure(MITIGATION_BARS)
        blocks = detect_mitigation_blocks(df, swings, breaks)
        setups = detect_mitigation_retest_setups(df, blocks, swings, current_idx=21)
        self.assertEqual(len(setups), 1)
        setup = setups[0]
        self.assertEqual(setup["direction"], "LONG")
        self.assertAlmostEqual(setup["entry"], 100.5)
        # The stop clears the origin swing rather than resting on it: 99.8 less
        # a quarter of the 2.8553 ATR at bar 21. On this pattern the origin
        # swing and the zone's low are the same 99.8, so a stop on the swing
        # would be a stop on the zone edge — the level the pattern gets run at.
        self.assertAlmostEqual(setup["stop"], 99.0862, places=4)
        self.assertLess(setup["stop"], blocks[0]["origin_swing_price"])
        self.assertLess(setup["stop"], blocks[0]["low"])
        self.assertAlmostEqual(setup["target"], 112.2)  # the high the break made
        self.assertGreater(setup["r_multiple"], 1.0)

    def test_a_stop_that_cannot_be_buffered_is_not_offered(self):
        # ATR over 26 bars has not warmed up at bar 21, so the buffer is
        # unmeasurable. The setup is withheld rather than shipped with the stop
        # parked on the swing, which is the one placement it exists to avoid.
        from signals.smc.mitigation import (
            detect_mitigation_blocks, detect_mitigation_retest_setups,
        )
        df, swings, breaks = self.structure(MITIGATION_BARS)
        blocks = detect_mitigation_blocks(df, swings, breaks)
        self.assertTrue(blocks)
        self.assertEqual(
            detect_mitigation_retest_setups(df, blocks, swings, current_idx=21,
                                            atr_period=26), [])

    def test_no_breaks_no_blocks(self):
        from signals.smc.mitigation import (
            detect_mitigation_blocks, detect_mitigation_retest_setups,
        )
        df = frame(quiet(30))
        self.assertEqual(detect_mitigation_blocks(df, swings_of(df), []), [])
        self.assertEqual(detect_mitigation_retest_setups(df, [], []), [])


class SessionTimezoneTests(SimpleTestCase):
    """The tests that catch the mistake a fixed-UTC killzone table makes."""

    def test_ten_am_new_york_is_a_different_utc_hour_in_each_season(self):
        from signals.smc.sessions import new_york_index
        summer = frame(quiet(8), start="2024-07-01 13:00", freq="1h")
        winter = frame(quiet(8), start="2024-01-15 13:00", freq="1h")
        self.assertEqual(new_york_index(summer)[1].hour, 10)   # 14:00 UTC, EDT
        self.assertEqual(new_york_index(winter)[2].hour, 10)   # 15:00 UTC, EST

    def test_silver_bullet_window_tracks_the_offset_change(self):
        from signals.smc.sessions import session_windows
        summer = frame(quiet(8), start="2024-07-01 13:00", freq="1h")
        winter = frame(quiet(8), start="2024-01-15 13:00", freq="1h")
        self.assertEqual(
            [w["positions"] for w in session_windows(summer, "silver_bullet_am")], [[1]])
        self.assertEqual(
            [w["positions"] for w in session_windows(winter, "silver_bullet_am")], [[2]])

    def test_in_ny_session_separates_false_from_unanswerable(self):
        from signals.smc.sessions import in_ny_session
        self.assertTrue(in_ny_session(pd.Timestamp("2024-07-01 14:30", tz="UTC"),
                                      "silver_bullet_am"))
        self.assertFalse(in_ny_session(pd.Timestamp("2024-01-15 14:30", tz="UTC"),
                                       "silver_bullet_am"))
        self.assertIsNone(in_ny_session(pd.Timestamp("2024-01-15 14:30", tz="UTC"),
                                        "not_a_session"))

    def test_asian_session_stays_one_window_across_midnight(self):
        from signals.smc.sessions import session_windows
        df = frame(quiet(48), start="2024-07-01 20:00", freq="1h")
        windows = session_windows(df, "asia")
        self.assertEqual([w["date"] for w in windows],
                         [dt.date(2024, 7, 1), dt.date(2024, 7, 2)])
        self.assertEqual(windows[0]["positions"], [4, 5, 6, 7])

    def test_midnight_open_tolerance_is_the_frame_s_own_bar(self):
        from signals.smc.sessions import ny_midnight_open
        hourly = frame(quiet(40), start="2024-06-30 12:00", freq="1h")
        reference = ny_midnight_open(hourly)
        self.assertEqual(reference["idx"], 16)
        self.assertEqual(reference["ny_ts"].hour, 0)

        # An equity-hours feed never prints a bar near New York midnight, so
        # the reference is genuinely unobservable rather than "the 09:30 bar".
        idx = pd.DatetimeIndex([
            pd.Timestamp(f"2024-07-0{day} {hour}:30", tz="UTC")
            for day in (1, 2) for hour in (13, 14, 15, 16, 17, 18, 19)
        ])
        equities = pd.DataFrame(
            {"open": [100.0] * len(idx), "high": [100.5] * len(idx),
             "low": [99.5] * len(idx), "close": [100.0] * len(idx)}, index=idx)
        self.assertIsNone(ny_midnight_open(equities))


class JudasSwingTests(SimpleTestCase):
    PRE_SESSION = quiet(10) + [
        (100, 100.3, 98.0, 98), (98, 98.3, 96.5, 97), (97, 97.2, 95.5, 96),
        (96, 97.3, 95.8, 97), (97, 98.3, 96.8, 98), (98, 99.3, 97.8, 99),
    ] + quiet(8)
    TRAP_SESSION = [
        (100, 100.8, 99.8, 100.7), (100.7, 101.6, 100.5, 101.5),
        (101.5, 102.3, 101.2, 102.0), (102.0, 102.1, 100.8, 101.0),
        (101.0, 101.2, 99.5, 99.8), (99.8, 100.0, 98.5, 98.8),
        (98.8, 99.0, 97.8, 98.0), (98.0, 98.2, 97.0, 97.2),
        (97.2, 97.4, 96.5, 96.8), (96.8, 97.0, 96.0, 96.3),
        (96.3, 96.5, 95.8, 96.0), (96.0, 96.6, 95.9, 96.5),
    ]

    def build(self, session_bars):
        # Bars 24-35 are 06:00-08:45 UTC, which is 02:00-04:45 New York — the
        # London window, in summer.
        return frame(self.PRE_SESSION + session_bars + quiet(12, 96.5),
                     start="2024-07-01 00:00", freq="15min")

    def test_fake_high_then_reversal_through_the_open(self):
        from signals.smc.session_setups import detect_judas_swings
        df = self.build(self.TRAP_SESSION)
        setups = detect_judas_swings(df, swings_of(df))
        self.assertEqual(len(setups), 1)
        setup = setups[0]
        self.assertEqual(setup["direction"], "SHORT")
        self.assertEqual(setup["session"], "london")
        self.assertEqual(setup["session_date"], dt.date(2024, 7, 1))
        self.assertAlmostEqual(setup["session_open"], 100.0)
        self.assertEqual(setup["judas_idx"], 26)
        self.assertAlmostEqual(setup["judas_price"], 102.3)
        self.assertAlmostEqual(setup["entry"], 101.15)   # midpoint of the trap leg
        self.assertAlmostEqual(setup["target"], 95.5)    # the swing low below it
        self.assertGreater(setup["stop"], setup["judas_price"])
        self.assertGreater(setup["r_multiple"], 1.0)

    def test_a_session_that_never_leaves_the_open_is_not_a_judas(self):
        from signals.smc.session_setups import detect_judas_swings
        df = self.build(quiet(12))
        self.assertEqual(detect_judas_swings(df, swings_of(df)), [])

    def test_unknown_session_and_missing_swings_answer_empty(self):
        from signals.smc.session_setups import detect_judas_swings
        df = self.build(self.TRAP_SESSION)
        self.assertEqual(detect_judas_swings(df, swings_of(df), session="nope"), [])
        self.assertEqual(detect_judas_swings(df, []), [])


class SilverBulletTests(SimpleTestCase):
    """Bars 24-27 are 14:00-14:45 UTC = 10:00-10:45 New York, in summer."""

    SESSION = [
        (100, 100.5, 99.5, 100),          # the gap's left bar, high 100.5
        (100, 104.5, 99.9, 104.2),        # displacement
        (104.2, 105.0, 101.0, 104.5),     # right bar, low 101.0 -> gap 100.5-101.0
        (104.5, 104.7, 103.0, 103.2),
    ]
    RETRACE = [
        (103.2, 103.4, 102.0, 102.2), (102.2, 102.4, 101.5, 101.8),
        (101.8, 102.2, 100.8, 101.5),     # bar 30 taps the gap
    ]

    def build(self, tail=()):
        return frame(quiet(24) + self.SESSION + self.RETRACE + list(tail),
                     start="2024-07-01 08:00", freq="15min")

    def test_gap_formed_inside_the_window_with_displacement(self):
        from signals.smc.session_setups import detect_silver_bullet_fvgs
        df = self.build()
        found = detect_silver_bullet_fvgs(df, current_idx=30)
        self.assertEqual(len(found), 1)
        gap = found[0]
        self.assertEqual(gap["type"], "FVG_BULL")
        self.assertEqual(gap["idx"], 25)
        self.assertAlmostEqual(gap["low"], 100.5)
        self.assertAlmostEqual(gap["high"], 101.0)
        self.assertEqual(gap["session"], "silver_bullet_am")
        self.assertTrue(gap["displacement"]["is_displacement"])

    def test_setup_aims_at_the_leg_that_opened_the_gap(self):
        from signals.smc.session_setups import detect_silver_bullet_setups
        df = self.build()
        setups = detect_silver_bullet_setups(df, swings_of(df), current_idx=30)
        self.assertEqual(len(setups), 1)
        setup = setups[0]
        self.assertEqual(setup["direction"], "LONG")
        self.assertAlmostEqual(setup["entry"], 100.75)   # consequent encroachment
        self.assertAlmostEqual(setup["target"], 105.0)   # the displacement high
        self.assertLess(setup["stop"], 100.5)
        self.assertGreater(setup["r_multiple"], 1.0)

    def test_opposing_bias_filters_but_a_missing_bias_does_not(self):
        from signals.smc.session_setups import detect_silver_bullet_setups
        df = self.build()
        swings = swings_of(df)
        self.assertEqual(
            detect_silver_bullet_setups(df, swings, bias="short", current_idx=30), [])
        self.assertEqual(
            len(detect_silver_bullet_setups(df, swings, bias=None, current_idx=30)), 1)

    def test_a_gap_goes_stale_after_the_session(self):
        from signals.smc.session_setups import detect_silver_bullet_setups
        df = self.build(tail=[(101.5, 102.0, 100.8, 101.5)] * 14)
        swings = swings_of(df)
        self.assertEqual(len(detect_silver_bullet_setups(df, swings, current_idx=30)), 1)
        self.assertEqual(detect_silver_bullet_setups(df, swings, current_idx=38), [])

    def test_a_four_hour_frame_cannot_hold_a_one_hour_window(self):
        from signals.smc.session_setups import detect_silver_bullet_fvgs
        coarse = frame(quiet(40), start="2024-07-01 00:00", freq="4h")
        self.assertEqual(detect_silver_bullet_fvgs(coarse), [])

    def test_a_gap_without_displacement_is_not_a_silver_bullet(self):
        from signals.smc.session_setups import detect_silver_bullet_fvgs
        limp = frame(quiet(24) + [
            (100, 100.1, 99.9, 100.0), (100.0, 100.4, 99.95, 100.3),
            (100.3, 100.5, 100.2, 100.4), (100.4, 100.6, 100.3, 100.5),
        ], start="2024-07-01 08:00", freq="15min")
        self.assertEqual(detect_silver_bullet_fvgs(limp), [])


class DailyBiasTests(SimpleTestCase):
    CHOP = [(0, 100), (10, 105), (20, 98), (30, 107),
            (40, 96), (50, 103), (60, 99), (70, 101)]

    def test_bias_from_a_displaced_break(self):
        from signals.smc.bias import daily_bias
        df = frame(MITIGATION_BARS)
        result = daily_bias(df, swings_of(df))
        self.assertEqual(result["bias"], "long")
        self.assertEqual(result["structure"], "up")
        self.assertTrue(0.0 <= result["confidence"] <= 1.0)
        self.assertTrue(any("displaced" in reason for reason in result["reasons"]))

    def test_no_evidence_means_no_bias_and_no_confidence(self):
        from signals.smc.bias import daily_bias
        df = frame(zigzag(self.CHOP, 71, wick=0.6))
        result = daily_bias(df, swings_of(df))
        self.assertIsNone(result["bias"])
        self.assertIsNone(result["confidence"])   # not 0.0 — nothing was measured
        self.assertEqual(result["structure"], "range")
        self.assertIn("ranging", result["reasons"][0])

    def test_unswept_pools_exclude_levels_price_has_traded_through(self):
        from signals.smc.bias import draw_on_liquidity, unswept_pools
        df = frame(MITIGATION_BARS)
        swings = swings_of(df)
        pools = unswept_pools(df, swings)
        self.assertTrue(pools)
        self.assertTrue(all(p["side"] == "sell_side" for p in pools))
        for pool in pools:
            self.assertGreaterEqual(
                float(df["low"].iloc[pool["swing_idx"] + 1:].min()), pool["price"])
        # Every high in this frame has been taken out, so there is no buy-side
        # draw left — reported as None, never as a price of zero.
        self.assertIsNone(draw_on_liquidity(df, swings)["buy_side"])
        self.assertEqual(unswept_pools(df, []), [])
        self.assertIsNone(draw_on_liquidity(df, []))

    def test_structure_is_read_only_from_swings_that_had_printed(self):
        # MITIGATION_BARS labels its swings L, H, HL, HH, HL. By bar 13 only
        # the first three exist and they read "range"; the HH at 16 and the HL
        # at 21 are what turn the sequence "up". Handing `current_trend` the
        # whole list let those two set the bias at bar 13 — and with no
        # displaced break yet, structure *is* the bias there, so the answer
        # came back "long" on the strength of bars the market had not printed.
        from signals.smc.bias import daily_bias
        from signals.smc.structure import current_trend
        df = frame(MITIGATION_BARS)
        swings = swings_of(df)
        self.assertEqual(current_trend(swings), "up")

        early = daily_bias(df, swings, current_idx=13)
        self.assertEqual(early["structure"], "range")
        self.assertIsNone(early["bias"])
        self.assertIsNone(early["confidence"])

        # And the answer at any bar has to match the answer a frame truncated
        # at that bar would give — the definition of no lookahead.
        for idx in range(13, len(df)):
            point_in_time = daily_bias(df, swings, current_idx=idx)
            visible = [s for s in swings if s["idx"] <= idx]
            self.assertEqual(point_in_time["structure"], current_trend(visible))

    def test_touch_counts_do_not_borrow_swings_from_the_future(self):
        # Two swing lows at the same 100.0, one at bar 5 and one at bar 25, on
        # a frame that never trades below 104.5 so both stay unswept. At bar 10
        # the shelf is one swing deep, not two: the second low has not printed.
        # `find_equal_levels` counts across whatever list it is given, and a
        # touch count is worth BIAS_W_POOL_STRENGTH of the daily bias.
        from signals.smc.bias import unswept_pools
        df = frame(quiet(30, 105.0))
        swings = [{"idx": 5, "type": "L", "price": 100.0},
                  {"idx": 25, "type": "L", "price": 100.0}]
        self.assertEqual([(p["swing_idx"], p["touches"])
                          for p in unswept_pools(df, swings, current_idx=10)],
                         [(5, 1)])
        self.assertEqual([(p["swing_idx"], p["touches"])
                          for p in unswept_pools(df, swings, current_idx=29)],
                         [(5, 2), (25, 2)])

    def test_filtering_never_silently_kills_everything(self):
        from signals.smc.bias import filter_setups_to_bias
        setups = [{"direction": "LONG"}, {"direction": "SHORT"}]
        self.assertEqual(len(filter_setups_to_bias(setups, None)), 2)
        self.assertEqual(filter_setups_to_bias(setups, "long"), [{"direction": "LONG"}])
        self.assertEqual(
            len(filter_setups_to_bias(setups, {"bias": "long", "confidence": 0.2},
                                      min_confidence=0.5)), 2)
        self.assertEqual(
            len(filter_setups_to_bias(setups, {"bias": "long", "confidence": 0.8},
                                      min_confidence=0.5)), 1)


class IpdaTests(SimpleTestCase):
    def test_bars_per_day_reads_the_index_spacing(self):
        from signals.smc.ipda import bars_per_day
        self.assertEqual(bars_per_day(frame(quiet(20))), 96.0)          # 15 minutes
        self.assertEqual(bars_per_day(frame(quiet(20), freq="4h")), 6.0)
        plain = pd.DataFrame({"open": [1, 2, 3, 4], "high": [1, 2, 3, 4],
                              "low": [1, 2, 3, 4], "close": [1, 2, 3, 4]})
        self.assertIsNone(bars_per_day(plain))   # no time on the index to read

    def test_dealing_range_and_its_refusals(self):
        from signals.smc.ipda import dealing_range
        df = frame(quiet(20, 100.0) + [(100, 110, 99, 108)] + quiet(9, 108.0))
        found = dealing_range(df, 30)
        self.assertAlmostEqual(found["high"], 110.0)
        self.assertAlmostEqual(found["low"], 99.0)
        self.assertAlmostEqual(found["equilibrium"], 104.5)
        self.assertEqual(found["zone"], "premium")
        self.assertIsNone(dealing_range(df, 5))               # under MIN_RANGE_BARS
        self.assertIsNone(dealing_range(df, 500, require_full=True))

    def test_day_labelled_ranges_refuse_to_stand_in_for_missing_history(self):
        from signals.smc.ipda import ipda_dealing_ranges
        # Eight hours of 15-minute bars is not a 20-day range under any label.
        self.assertEqual(ipda_dealing_ranges(frame(quiet(32))), [])
        long_frame = frame(zigzag([(0, 100), (100, 130), (200, 110),
                                   (300, 140), (399, 120)], 400), freq="4h")
        ranges = ipda_dealing_ranges(long_frame)
        self.assertEqual([r["lookback_days"] for r in ranges], [20, 40, 60])
        self.assertEqual([r["bars"] for r in ranges], [120, 240, 360])

    def test_standard_deviation_projections(self):
        from signals.smc.ipda import std_dev_projections
        levels = std_dev_projections(100, 90, (1.0, 2.0))
        self.assertEqual([lvl["price"] for lvl in levels], [90.0, 80.0])
        self.assertIsNone(std_dev_projections(100, 100))   # no leg to multiply
        self.assertIsNone(std_dev_projections(None, 90))

    def test_projection_needs_a_leg_the_sweep_actually_produced(self):
        from signals.smc.ipda import project_from_swept_leg
        df = frame(quiet(20) + [
            (100, 103, 99.8, 100.2), (100.2, 100.4, 95.0, 95.2),
            (95.2, 95.4, 92.0, 92.2),
        ] + quiet(7, 92.2))
        sweep = {"idx": 20, "type": "SWEEP_HIGH", "wick_high": 103.0}
        projection = project_from_swept_leg(df, sweep)
        self.assertAlmostEqual(projection["anchor"], 103.0)
        self.assertAlmostEqual(projection["leg_end"], 92.0)
        self.assertEqual(projection["direction"], "down")
        by_multiple = {lvl["multiple"]: lvl["price"] for lvl in projection["levels"]}
        self.assertAlmostEqual(by_multiple[1.0], 92.0)
        self.assertAlmostEqual(by_multiple[2.0], 81.0)

        # A sweep followed by nothing has no leg, so there is nothing to project.
        self.assertIsNone(project_from_swept_leg(frame(quiet(30)), sweep))
        self.assertIsNone(project_from_swept_leg(frame(quiet(30)), None))


class OpeningGapTests(SimpleTestCase):
    def test_new_day_gap_is_measured_across_the_new_york_boundary(self):
        from signals.smc.gaps import opening_gaps
        # Hourly bars from 6/30 12:00 UTC: bar 16 is 7/1 04:00 UTC, which is
        # midnight in New York, and it opens 2 points above the prior close.
        df = frame(quiet(16, 100.0) + [(102, 102.5, 101.5, 102)] + quiet(11, 102.0)
                   + [(101, 101.5, 99.0, 99.5)] + quiet(5, 99.5),
                   start="2024-06-30 12:00", freq="1h")
        found = opening_gaps(df, scope="day")
        self.assertEqual(len(found), 1)
        gap = found[0]
        self.assertEqual(gap["type"], "NDOG")
        self.assertEqual(gap["idx"], 16)
        self.assertEqual(gap["direction"], "up")
        self.assertAlmostEqual(gap["low"], 100.0)
        self.assertAlmostEqual(gap["high"], 102.0)
        self.assertAlmostEqual(gap["consequent_encroachment"], 101.0)
        self.assertTrue(gap["filled"])
        self.assertEqual(gap["filled_idx"], 28)

    def test_a_continuous_market_has_no_gaps_to_report(self):
        from signals.smc.gaps import opening_gaps
        df = frame(quiet(40), start="2024-06-30 12:00", freq="1h")
        self.assertEqual(opening_gaps(df, scope="day"), [])
        self.assertEqual(opening_gaps(df, scope="fortnight"), [])

    def test_trading_week_starts_on_sunday_not_on_the_iso_monday(self):
        from signals.smc.gaps import trading_week_start
        self.assertEqual(trading_week_start(dt.date(2024, 7, 7)), dt.date(2024, 7, 7))
        self.assertEqual(trading_week_start(dt.date(2024, 7, 8)), dt.date(2024, 7, 7))
        self.assertEqual(trading_week_start(dt.date(2024, 7, 12)), dt.date(2024, 7, 7))


class TurtleSoupTests(SimpleTestCase):
    def test_old_level_raided_and_reclaimed(self):
        from signals.smc.gaps import detect_turtle_soup
        df = frame(quiet(12) + [(100, 100.2, 95.0, 99)] + quiet(17)
                   + [(100, 100.2, 94.5, 99.8)] + quiet(3, 99.8))
        events = detect_turtle_soup(df)
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event["type"], "TURTLE_SOUP_LONG")
        self.assertEqual(event["idx"], 30)
        self.assertAlmostEqual(event["level"], 95.0)
        self.assertEqual(event["level_idx"], 12)
        self.assertEqual(event["level_age_bars"], 18)
        self.assertAlmostEqual(event["raid_price"], 94.5)

    def test_a_two_bar_old_level_is_not_settled_liquidity(self):
        from signals.smc.gaps import detect_turtle_soup
        df = frame(quiet(28) + [(100, 100.2, 95.0, 99)]
                   + [(99, 99.5, 94.5, 99.2)] + quiet(3, 99.2))
        self.assertEqual(detect_turtle_soup(df), [])

    def test_a_frame_shorter_than_the_lookback_answers_empty(self):
        from signals.smc.gaps import detect_turtle_soup
        self.assertEqual(detect_turtle_soup(frame(quiet(10))), [])
