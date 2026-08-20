"""Plan 2.3 — the ICT lane detects everything and can finally trade some of it.

Three defects, one lane:

  * `signals.bot_bridge` imported `signals.performance.get_hit_rate`, a name
    that did not exist. The ImportError was caught by a blanket
    `except Exception: return (0.0, [])` at the top of `smc_score_for_symbol`,
    so the SMC composite score was 0.0 on every call, for every symbol,
    forever — and `bot_program.engine.strategy` blends it only
    `if smc_score != 0`. The whole SMC lane has never once contributed to a
    trading decision. `performance` now measures the hit rate it was always
    supposed to expose, and the bridge tells a missing dependency apart from
    an unavailable model instead of treating both as a silent zero.

  * A structure break was a single close beyond a swing. No size, no body, no
    velocity — so a one-tick drift and a violent expansion arrived at the
    detectors as the same event, and every zone drawn off a drift was traded
    like a shift. `scan_symbol` qualifies breaks through
    `signals.smc.displacement` now and drops the measured drifts.

  * Every detector was free to fire in both directions on the same chart at
    the same moment, which is right for a primitive and useless for a trading
    day. `signals.smc.bias` gives the scan one direction to answer with, and
    `smc_rules.bias_may_refuse` decides when that direction has earned the
    right to delete the other side of the book — a question about two named
    terms rather than about the number they happen to add up to. See
    `TheBiasBarIsTwoTermsNotASum`.

Two invariants hold all of it together. The card's own trail has to sum to the
conviction it displays (`TheTrailStillAddsUp`), and nothing on the card may be
scored as agreement with itself — which is what the multi-timeframe pass was
doing to its top frame (`TheTopTimeframeIsNotItsOwnConfluence`).

Run with:  python manage.py test tests.test_smc_armed
"""
import re
from datetime import datetime, timedelta, timezone as dt_timezone
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase
from django.utils import timezone


# 12:00 UTC in January is 07:00 in New York — the dead hour between the London
# and AM killzones. Cards stamped here keep the killzone term out of the sum.
BAR_ONE = datetime(2024, 1, 15, 12, 0, tzinfo=dt_timezone.utc)


def _trail_total(reasons):
    """Sum the conviction terms a card lists, the way a reader would.

    Every scorer's line ends in a signed number except the "base N" opener, so
    this is what the card's own "How this scored N/100" summary is claiming.
    """
    total = 0
    for reason in reasons:
        if reason.startswith("base "):
            total += int(reason.split()[1])
            continue
        term = re.search(r"([+-]\d+)$", reason)
        if term:
            total += int(term.group(1))
    return total


# ── frames ──────────────────────────────────────────────────────────────────

def _frame(rows, start="2024-01-01 00:00"):
    import pandas as pd
    idx = pd.date_range(start, periods=len(rows), freq="4h", tz="UTC")
    return pd.DataFrame(
        {"open": [r[0] for r in rows], "high": [r[1] for r in rows],
         "low": [r[2] for r in rows], "close": [r[3] for r in rows],
         "volume": [1000.0] * len(rows)}, index=idx)


def _bar(o, c, pad=0.2):
    return (o, max(o, c) + pad, min(o, c) - pad, c)


def _flat_frame(bars=120):
    """A quiet series: no pivots, no gaps, nothing for a detector to find."""
    return _frame([(100.0, 100.5, 99.5, 100.0)] * bars)


def _sfp_frame():
    """A swing high at bar 100 and a last bar that fails to hold above it.

    The only card this frame produces in either direction is a SHORT, which is
    what makes it the cheap fixture for the bias filter.
    """
    df = _flat_frame()
    last = len(df) - 1
    df.iloc[90, df.columns.get_loc("low")] = 95.0     # swing low
    df.iloc[100, df.columns.get_loc("high")] = 105.0  # swing high to be taken
    df.iloc[last, df.columns.get_loc("high")] = 106.0
    df.iloc[last, df.columns.get_loc("low")] = 99.8
    df.iloc[last, df.columns.get_loc("open")] = 100.0
    df.iloc[last, df.columns.get_loc("close")] = 100.2
    return df


def _zone_frame(displaced=True):
    """One order block, one break above the swing high, one retest of the zone.

    Bars 0-59 are a sawtooth that gives the frame swings and an ATR of about
    one point. Then a push to a swing high at 104.20, a pullback whose last red
    candle IS the order block (100.20-101.50), a rise that stalls in a shelf,
    the dip at 103.00 that becomes the inducement pool guarding the zone, and
    the break of 104.20.

    `displaced` changes ONE thing: whether that break is a single 2.4-ATR
    expansion candle or five bars crawling 0.35 of an ATR over the same level.
    Everything after it — the walk back down, the bar tagging the zone — is the
    same trade in the same place. It is the difference between the two the
    filter is supposed to see.
    """
    rows = []
    price = 100.0
    for i in range(60):
        step = 0.8 if (i // 5) % 2 == 0 else -0.8
        rows.append(_bar(price, price + step))
        price += step
    for _ in range(5):                       # up to the 104.20 swing high
        rows.append(_bar(price, price + 0.8))
        price += 0.8
    for _ in range(4):                       # pullback; the last red bar is the OB
        rows.append(_bar(price, price - 0.9))
        price -= 0.9
    rows += [
        (100.40, 101.30, 100.30, 101.20),
        (101.20, 102.10, 101.10, 102.00),
        (102.00, 102.90, 101.90, 102.80),
        (102.80, 103.50, 102.70, 103.40),
        (103.40, 103.55, 103.30, 103.45),
        (103.45, 103.60, 103.35, 103.50),
        (103.50, 103.65, 103.40, 103.55),
        (103.55, 103.70, 103.00, 103.60),    # the inducement low
        (103.60, 103.75, 103.45, 103.65),
        (103.65, 103.80, 103.50, 103.70),
        (103.70, 103.85, 103.55, 103.75),
    ]
    if displaced:
        rows.append((103.75, 106.10, 103.65, 106.00))
        rows += [
            (106.00, 106.10, 104.80, 104.90),
            (104.90, 105.00, 103.70, 103.80),
        ]
    else:
        rows += [
            (103.75, 103.90, 103.65, 103.85),
            (103.85, 104.00, 103.75, 103.95),
            (103.95, 104.10, 103.85, 104.05),
            (104.05, 104.20, 103.95, 104.15),
            (104.15, 104.35, 104.05, 104.30),  # the break, 0.35 of an atr
            (104.30, 104.40, 103.20, 103.30),
        ]
    rows += [
        (103.80, 103.90, 102.60, 102.70),
        (102.70, 102.80, 101.50, 101.60),
        (101.60, 101.70, 100.90, 101.40),      # tags the zone
    ]
    return _frame(rows)


_NOT_GIVEN = object()


def _bias(direction="long", confidence=0.8, structure=_NOT_GIVEN,
          location=_NOT_GIVEN):
    """What `daily_bias` hands back, cut down to the keys the scan reads.

    `structure` and `location` default to the pair that agrees with
    `direction`, because `daily_bias` derives its confidence from those very
    terms — a fixture naming 0.80 with the sequence pointing the other way
    describes a chart the scan will never be handed. Pass either explicitly to
    build the bias whose confidence came from somewhere else, and None to say
    the term could not be measured at all.
    """
    if structure is _NOT_GIVEN:
        structure = "up" if direction == "long" else "down"
    if location is _NOT_GIVEN:
        location = ("discount", 0.2) if direction == "long" else ("premium", 0.8)
    return {
        "bias": direction, "confidence": confidence, "structure": structure,
        "draw": {"price": 110.0, "touches": 2}, "opposing": None,
        "dealing_range": None, "location": location, "price": 100.0,
        "last_break": None, "reasons": ["fixture"],
    }


def _ob_retest(cards):
    """The order-block retest card in a scan result, or None."""
    return next((c for c in cards if c["setup"] == "OB_RETEST"), None)


def _closed_signal(setup="OB_RETEST", status="TARGET_HIT", bar=None):
    from signals.models_smc import SmcSignal
    return SmcSignal.objects.create(
        symbol="AAA", timeframe="4h", setup=setup, direction="LONG",
        headline="h", thesis="t", why_now="w", invalidation="i",
        entry=100.0, stop=99.0, target=102.0, r_multiple=2.0,
        status=status, closed_at=timezone.now(),
        realized_r=2.0 if status == "TARGET_HIT" else -1.0,
        trigger_ts=bar,
    )


def _open_signal(direction="LONG", conviction=80, setup="OB_RETEST", bar=None):
    from signals.models_smc import SmcSignal
    return SmcSignal.objects.create(
        symbol="AAA", timeframe="4h", setup=setup, direction=direction,
        headline="h", thesis="t", why_now="w", invalidation="i",
        entry=100.0, stop=99.0, target=102.0, r_multiple=2.0,
        conviction=conviction, status="ACTIVE", trigger_ts=bar,
    )


# ── the dead import ─────────────────────────────────────────────────────────

class TheDeadImportIsGone(SimpleTestCase):
    def test_performance_exports_the_name_the_bridge_imports(self):
        """The whole defect in one assertion: this name did not exist."""
        import inspect

        from signals import bot_bridge
        from signals.performance import get_hit_rate

        self.assertTrue(callable(get_hit_rate))
        self.assertIn("get_hit_rate", inspect.getsource(bot_bridge))

    def test_the_hit_rate_is_not_counted_twice(self):
        """One implementation, or the card and the bot eventually disagree."""
        import inspect

        from signals import performance

        source = inspect.getsource(performance.get_hit_rate)
        self.assertIn("setup_performance_summary", source)
        self.assertNotIn("TARGET_HIT", source,
                         "get_hit_rate is counting closed rows itself instead "
                         "of reading the one function that already does")

    def test_a_missing_dependency_is_loud_now_and_not_a_zero_score(self):
        """The bug class, re-run: hide this ImportError and the lane dies.

        `strategy.py` blends the composite score only when it is non-zero, so
        an exception swallowed here does not degrade the lane, it deletes it —
        silently, and for as long as nobody re-reads this file.
        """
        from signals import performance
        from signals.bot_bridge import smc_score_for_symbol

        saved = performance.get_hit_rate
        del performance.get_hit_rate
        try:
            with self.assertLogs("signals.bot_bridge", level="ERROR"):
                with self.assertRaises(ImportError):
                    smc_score_for_symbol("AAA")
        finally:
            performance.get_hit_rate = saved


class MeasuredSetupHitRate(TestCase):
    def test_a_thin_sample_is_not_a_hit_rate(self):
        """Two closed cards is noise wearing a percent sign."""
        from signals.performance import get_hit_rate
        _closed_signal(status="TARGET_HIT", bar=BAR_ONE)
        _closed_signal(status="STOPPED", bar=BAR_ONE + timedelta(hours=4))
        self.assertIsNone(get_hit_rate("OB_RETEST"))

    def test_a_real_sample_is(self):
        from signals.performance import MIN_EMPIRICAL_N, get_hit_rate
        for i in range(3):
            _closed_signal(status="TARGET_HIT",
                           bar=BAR_ONE + timedelta(hours=4 * i))
        for i in range(3, 6):
            _closed_signal(status="STOPPED",
                           bar=BAR_ONE + timedelta(hours=4 * i))
        self.assertGreaterEqual(6, MIN_EMPIRICAL_N)
        self.assertEqual(get_hit_rate("OB_RETEST"), 0.5)

    def test_it_reports_the_same_number_the_dashboard_shows(self):
        from signals.performance import get_hit_rate, setup_performance_summary
        for i in range(5):
            _closed_signal(status="TARGET_HIT" if i < 4 else "STOPPED",
                           bar=BAR_ONE + timedelta(hours=4 * i))
        summary = setup_performance_summary()
        self.assertEqual(get_hit_rate("OB_RETEST"),
                         summary["OB_RETEST"]["hit_rate"])

    def test_a_setup_with_no_record_is_not_a_setup_that_loses(self):
        from signals.performance import get_hit_rate
        self.assertIsNone(get_hit_rate("PO3"))

    def test_an_unreadable_record_reports_nothing_not_zero(self):
        from signals.performance import get_hit_rate
        with patch("signals.performance.setup_performance_summary",
                   side_effect=RuntimeError("db down")):
            with self.assertLogs("signals.performance", level="WARNING"):
                self.assertIsNone(get_hit_rate("OB_RETEST"))


class TheCompositeScoreReachesTheBot(TestCase):
    """`smc_score_for_symbol("EURUSD") == (0.0, [])` was true for every input."""

    def test_the_lane_finally_scores_something(self):
        from signals.bot_bridge import smc_score_for_symbol
        _open_signal(direction="LONG", conviction=80, bar=BAR_ONE)
        score, reasons = smc_score_for_symbol("AAA")
        self.assertNotEqual(score, 0.0,
                            "a zero here is the whole defect: strategy.py "
                            "blends this score only when it is non-zero")
        self.assertAlmostEqual(score, 0.8)
        self.assertTrue(reasons)

    def test_an_unmeasured_setup_weighs_the_same_as_a_coin_flip(self):
        """None is NOT MEASURED. Weighting it at zero would delete the setup
        from the average — and on a fresh install, every setup."""
        from signals.bot_bridge import UNMEASURED_SETUP_WEIGHT, smc_score_for_symbol
        _open_signal(direction="LONG", conviction=80, bar=BAR_ONE)
        with patch("signals.performance.get_hit_rate", return_value=None):
            unmeasured, _ = smc_score_for_symbol("AAA")
        with patch("signals.performance.get_hit_rate",
                   return_value=UNMEASURED_SETUP_WEIGHT):
            neutral, _ = smc_score_for_symbol("AAA")
        self.assertEqual(unmeasured, neutral)
        self.assertAlmostEqual(unmeasured, 0.8)

    def test_a_measured_zero_is_a_verdict_and_is_kept(self):
        """0.0 measured is a record, and a bad one — not a missing one."""
        from signals.bot_bridge import smc_score_for_symbol
        _open_signal(direction="LONG", conviction=80, bar=BAR_ONE)
        with patch("signals.performance.get_hit_rate", return_value=0.0):
            score, reasons = smc_score_for_symbol("AAA")
        self.assertEqual(score, 0.0)
        self.assertTrue(any("0%" in r for r in reasons), reasons)

    def test_the_measured_record_actually_weights_the_score(self):
        """A 100%-hit setup and a 60%-hit setup must not score identically."""
        from signals.bot_bridge import smc_score_for_symbol
        _open_signal(direction="LONG", conviction=80, setup="OB_RETEST",
                     bar=BAR_ONE)
        _open_signal(direction="SHORT", conviction=80, setup="FVG_TAP",
                     bar=BAR_ONE)

        def by_setup(setup):
            return 1.0 if setup == "OB_RETEST" else 0.2

        with patch("signals.performance.get_hit_rate", side_effect=by_setup):
            score, _ = smc_score_for_symbol("AAA")
        # The long carries five times the weight of the short, so the net is
        # long — where an unweighted average of the two would be exactly zero.
        self.assertGreater(score, 0.4)

    def test_a_symbol_with_no_cards_says_nothing(self):
        from signals.bot_bridge import smc_score_for_symbol
        self.assertEqual(smc_score_for_symbol("AAA"), (0.0, []))


# ── displacement qualifies the break ────────────────────────────────────────

class DisplacementQualifiesTheBreak(TestCase):
    def test_a_break_with_energy_behind_it_still_produces_its_zone(self):
        from signals.rules.smc_rules import scan_symbol
        card = _ob_retest(scan_symbol("AAA", "4h", df=_zone_frame(displaced=True)))
        self.assertIsNotNone(card, "the displaced fixture must produce a card, "
                                   "or the drift test below proves nothing")
        self.assertEqual(card["direction"], "LONG")

    def test_the_same_trade_off_a_drift_is_not_offered(self):
        """Identical zone, identical retest, a break that crawled over the
        level instead of expanding through it."""
        from signals.rules.smc_rules import scan_symbol
        cards = scan_symbol("AAA", "4h", df=_zone_frame(displaced=False))
        self.assertIsNone(_ob_retest(cards))

    def test_the_drift_was_dropped_by_the_filter_and_not_by_the_fixture(self):
        """With the filters off the same frame hands the same card back, which
        is what makes the test above a statement about the filter."""
        from signals.rules.smc_rules import scan_symbol
        cards = scan_symbol("AAA", "4h", df=_zone_frame(displaced=False),
                            ict_filters=False)
        self.assertIsNotNone(_ob_retest(cards))

    def test_the_card_says_what_the_displacement_measured(self):
        from signals.rules.smc_rules import scan_symbol
        card = _ob_retest(scan_symbol("AAA", "4h", df=_zone_frame()))
        line = next(r for r in card["reasons"] if "displaced" in r)
        self.assertIn("atr", line)
        self.assertGreater(card["ict"]["displacement"]["score"], 0)
        self.assertTrue(card["ict"]["displacement"]["displaced"])

    def test_the_bonus_is_proportional_to_the_energy_measured(self):
        from signals.rules.smc_rules import DISPLACEMENT_MAX_BONUS, _displacement_term
        weak = _displacement_term({"type": "BOS_UP", "displaced": True,
                                   "displacement_score": 0.4,
                                   "displacement": {"atr_multiple": 1.6, "bars": 3}})
        strong = _displacement_term({"type": "BOS_UP", "displaced": True,
                                     "displacement_score": 0.9,
                                     "displacement": {"atr_multiple": 3.4, "bars": 1,
                                                      "has_imbalance": True}})
        self.assertLess(weak[1][0], strong[1][0])
        self.assertLessEqual(strong[1][0], DISPLACEMENT_MAX_BONUS)
        self.assertIn("imbalance", strong[1][1])

    def test_an_unmeasurable_displacement_is_not_a_drift(self):
        """A break inside the ATR warm-up was never measured. Calling it a
        drift would retire every early break in the frame."""
        from signals.rules.smc_rules import _displacement_term
        fact, (delta, why) = _displacement_term(
            {"type": "BOS_UP", "displaced": None, "displacement_score": None,
             "displacement": None})
        self.assertIsNone(fact["displaced"])
        self.assertEqual(delta, 0)
        self.assertIn("not measurable", why)

    def test_a_setup_built_on_no_break_at_all_is_not_scored_for_one(self):
        from signals.rules.smc_rules import _displacement_term, structure_break_for
        self.assertIsNone(structure_break_for({"setup": "SFP"}, {}))
        self.assertEqual(_displacement_term(None), (None, None))


# ── the daily bias picks a side ─────────────────────────────────────────────

class DailyBiasStopsBothDirectionsAtOnce(TestCase):
    """The SFP frame's only cards are SHORTs, so the filter is visible."""

    def _scan(self, bias):
        from signals.rules.smc_rules import scan_symbol
        with patch("signals.smc.bias.daily_bias", return_value=bias):
            return scan_symbol("AAA", "4h", df=_sfp_frame())

    def test_a_confident_bias_refuses_the_other_side(self):
        cards = self._scan(_bias("long", 0.8))
        self.assertEqual([c["setup"] for c in cards], [])

    def test_a_setup_running_with_that_bias_is_scored_for_it(self):
        from signals.rules.smc_rules import BIAS_AGREE_BONUS
        cards = self._scan(_bias("short", 0.8))
        self.assertTrue(cards)
        for card in cards:
            self.assertEqual(card["direction"], "SHORT")
            self.assertTrue(any("short daily bias" in r for r in card["reasons"]),
                            card["reasons"])
            self.assertTrue(any(r.endswith("+%d" % BIAS_AGREE_BONUS)
                                for r in card["reasons"]), card["reasons"])

    def test_a_thin_bias_refuses_nothing_and_scores_nothing(self):
        """Below the confidence bar the bias is reported, not acted on: a weak
        read is not evidence enough to delete half the book."""
        from signals.rules.smc_rules import BIAS_MIN_CONFIDENCE
        thin = round(BIAS_MIN_CONFIDENCE - 0.2, 2)
        against = self._scan(_bias("long", thin))
        self.assertTrue(against)
        for card in against:
            line = next(r for r in card["reasons"] if "daily bias" in r)
            self.assertTrue(line.endswith("+0"), line)

    def test_an_unmeasured_bias_is_not_evidence_against_either_side(self):
        cards = self._scan({"bias": None, "confidence": None,
                            "structure": "range", "draw": None,
                            "reasons": ["no displaced break and the swing "
                                        "sequence is ranging"]})
        self.assertTrue(cards)
        line = next(r for r in cards[0]["reasons"] if "daily bias" in r)
        self.assertIn("no daily bias measured", line)
        self.assertTrue(line.endswith("+0"), line)

    def test_the_real_bias_runs_on_the_real_frame(self):
        """Not the patched dict: `daily_bias` itself has to survive the frames
        this scan hands it, and its verdict has to reach the card."""
        from signals.rules.smc_rules import scan_symbol
        card = _ob_retest(scan_symbol("AAA", "4h", df=_zone_frame()))
        self.assertIn("bias", card["ict"])
        self.assertTrue(any("daily bias" in r for r in card["reasons"]),
                        card["reasons"])

    def test_the_bias_is_not_read_when_no_detector_found_anything(self):
        """The order the scan's docstring describes, as behaviour.

        `daily_bias` qualifies every break, walks the pools and measures the
        IPDA ranges — the most expensive read in the scan — so it runs after
        the detectors and a frame with nothing on it never pays for it.
        """
        from signals.rules.smc_rules import scan_symbol
        with patch("signals.smc.bias.daily_bias") as read:
            self.assertEqual(scan_symbol("AAA", "4h", df=_flat_frame()), [])
        read.assert_not_called()


class TheBiasBarIsTwoTermsNotASum(SimpleTestCase):
    """`BIAS_MIN_CONFIDENCE` is 0.70 because that is where the higher-timeframe
    sequence and the location in the dealing range land together — and the
    comment defending it said a bias may only delete the other side of the book
    with both of those behind it. A sum cannot say that. Structure plus the two
    refinements reaches the same 0.70 from a direction being taken at a poor
    price, and that bias deleted the whole counter-direction book.
    """

    def test_the_bar_is_reachable_without_the_location(self):
        """The defect is arithmetic. If this stops holding, the guards below
        are testing nothing and the threshold wants re-deriving."""
        from signals.smc.bias import (BIAS_W_LOCATION, BIAS_W_POOL_STRENGTH,
                                      BIAS_W_ROOM, BIAS_W_STRUCTURE)
        from signals.rules.smc_rules import BIAS_MIN_CONFIDENCE
        self.assertAlmostEqual(BIAS_W_STRUCTURE + BIAS_W_LOCATION,
                               BIAS_MIN_CONFIDENCE)
        self.assertGreaterEqual(
            BIAS_W_STRUCTURE + BIAS_W_POOL_STRENGTH + BIAS_W_ROOM,
            BIAS_MIN_CONFIDENCE)

    def test_both_named_terms_are_required(self):
        from signals.rules.smc_rules import BIAS_MIN_CONFIDENCE, bias_may_refuse
        at_the_bar = BIAS_MIN_CONFIDENCE
        self.assertTrue(bias_may_refuse(_bias("long", at_the_bar)))
        self.assertFalse(bias_may_refuse(
            _bias("long", at_the_bar, location=("premium", 0.82))))
        self.assertFalse(bias_may_refuse(
            _bias("long", at_the_bar, structure="range")))

    def test_an_unmeasured_location_is_not_a_discount(self):
        """No readable dealing range means the term was never scored, and an
        unscored term must not be read as one that passed."""
        from signals.rules.smc_rules import bias_may_refuse
        self.assertFalse(bias_may_refuse(_bias("long", 0.9, location=None)))

    def test_a_bias_with_no_direction_refuses_nothing(self):
        from signals.rules.smc_rules import bias_may_refuse
        self.assertFalse(bias_may_refuse(None))
        self.assertFalse(bias_may_refuse(
            {"bias": None, "confidence": None, "structure": "range"}))


class ABiasAtAPoorLocationKeepsTheOtherSide(TestCase):
    """The same SFP frame, whose only cards are SHORTs."""

    def _scan(self, bias):
        from signals.rules.smc_rules import scan_symbol
        with patch("signals.smc.bias.daily_bias", return_value=bias):
            return scan_symbol("AAA", "4h", df=_sfp_frame())

    def test_structure_and_the_refinements_do_not_add_up_to_a_refusal(self):
        from signals.rules.smc_rules import BIAS_MIN_CONFIDENCE
        cards = self._scan(_bias("long", BIAS_MIN_CONFIDENCE,
                                 location=("premium", 0.82)))
        self.assertTrue(cards, "a long bias chasing a premium deleted the "
                               "whole counter-direction book")
        self.assertEqual({c["direction"] for c in cards}, {"SHORT"})

    def test_the_two_named_terms_still_refuse(self):
        """The other half of the same statement: with both behind it the bias
        does exactly what it always did."""
        from signals.rules.smc_rules import BIAS_MIN_CONFIDENCE
        self.assertEqual(self._scan(_bias("long", BIAS_MIN_CONFIDENCE)), [])

    def test_the_card_names_the_term_the_bias_is_short_of(self):
        """Quoting the 0.70 threshold at a reader looking at a 0.70 confidence
        explains nothing, so the trail says which test came up short."""
        from signals.rules.smc_rules import BIAS_MIN_CONFIDENCE
        cards = self._scan(_bias("short", BIAS_MIN_CONFIDENCE,
                                 location=("discount", 0.2)))
        self.assertTrue(cards)
        for card in cards:
            line = next(r for r in card["reasons"] if "daily bias" in r)
            self.assertIn("location", line)
            self.assertTrue(line.endswith("+0"), line)

    def test_a_bias_it_cannot_act_on_does_not_pay_the_agreement_bonus(self):
        from signals.rules.smc_rules import BIAS_MIN_CONFIDENCE
        cards = self._scan(_bias("short", BIAS_MIN_CONFIDENCE,
                                 structure="range"))
        self.assertTrue(cards)
        for card in cards:
            line = next(r for r in card["reasons"] if "daily bias" in r)
            self.assertIn("sequence", line)
            self.assertTrue(line.endswith("+0"), line)


# ── the highest timeframe has nothing above it ──────────────────────────────

class TheTopTimeframeIsNotItsOwnConfluence(SimpleTestCase):
    """`min(i + 1, len(timeframes) - 1)` made the last frame its own higher
    frame, so a 1d card banked HTF_AGREE_BONUS and told the reader "1d trend up
    agrees with the LONG" — about itself. A self-comparison is not the second
    opinion this whole pass exists to fetch.
    """

    BASE_REASONS = ["base 30", "1 confluence chip(s) +10",
                    "3.00R geometry +20"]

    def _by_timeframe(self, timeframes=("4h", "1d"), trend="up",
                      direction="LONG"):
        from signals import mtf

        def one_card(symbol, timeframe=None, bars=None):
            return [{
                "symbol": symbol, "timeframe": timeframe, "setup": "SFP",
                "direction": direction, "conviction": 60,
                "chips": {"structure": 1, "momentum": 0, "flow": 0,
                          "macro": 0, "sentiment": 0},
                "components": ["sweep_high", "sfp"],
                "reasons": list(self.BASE_REASONS),
            }]

        with patch.object(mtf, "scan_symbol", side_effect=one_card), \
                patch.object(mtf, "htf_trend", return_value=trend):
            cards = mtf.scan_symbol_mtf("AAA", timeframes=list(timeframes))
        return {c["timeframe"]: c for c in cards}

    def test_the_top_frame_banks_nothing_for_agreeing_with_itself(self):
        top = self._by_timeframe()["1d"]
        self.assertEqual(top["conviction"], 60)
        self.assertEqual(top["chips"]["macro"], 0)
        self.assertFalse(any("agrees with the" in r for r in top["reasons"]),
                         top["reasons"])

    def test_the_top_frame_says_the_question_was_not_asked(self):
        """None, not False: False reads as a higher timeframe that looked and
        disagreed, and there was no higher timeframe to look."""
        top = self._by_timeframe()["1d"]
        self.assertIsNone(top["htf_agrees"])
        self.assertIsNone(top["htf_timeframe"])
        self.assertIsNone(top["htf_trend"])
        self.assertTrue(any("highest timeframe" in r for r in top["reasons"]),
                        top["reasons"])

    def test_the_frame_below_it_still_gets_its_second_opinion(self):
        from signals.mtf import HTF_AGREE_BONUS
        cards = self._by_timeframe()
        self.assertEqual(cards["4h"]["conviction"], 60 + HTF_AGREE_BONUS)
        self.assertEqual(cards["4h"]["htf_timeframe"], "1d")
        self.assertTrue(cards["4h"]["htf_agrees"])

    def test_a_conflicting_top_frame_is_not_penalised_against_itself(self):
        """The mirror of the bonus. A 1d SHORT under a 1d uptrend must not be
        docked for conflicting with the frame it was read from."""
        top = self._by_timeframe(trend="up", direction="SHORT")["1d"]
        self.assertEqual(top["conviction"], 60)
        self.assertEqual(top["chips"]["macro"], 0)

    def test_the_trail_on_the_top_frame_still_sums_to_its_conviction(self):
        top = self._by_timeframe()["1d"]
        self.assertEqual(_trail_total(top["reasons"]), top["conviction"])

    def test_one_timeframe_confirms_nothing_either(self):
        only = self._by_timeframe(timeframes=("4h",))["4h"]
        self.assertEqual(only["conviction"], 60)
        self.assertIsNone(only["htf_agrees"])


# ── inducement: the zone is armed once the pool in front of it is taken ─────

class TheZoneIsArmed(TestCase):
    def test_the_scan_asks_whether_the_zone_was_armed(self):
        from signals.rules.smc_rules import INDUCEMENT_ARMED_BONUS, scan_symbol
        card = _ob_retest(scan_symbol("AAA", "4h", df=_zone_frame()))
        self.assertTrue(card["ict"]["inducement"]["armed"])
        self.assertTrue(any("inducement" in r and r.endswith(
            "+%d" % INDUCEMENT_ARMED_BONUS) for r in card["reasons"]),
            card["reasons"])

    def test_a_zone_with_nothing_in_front_of_it_is_scored_zero_not_penalised(self):
        """No pool is not a failed arming test — the question does not apply,
        and answering False would hold back a valid entry forever."""
        from signals.rules.smc_rules import _inducement_term
        fact, (delta, why) = _inducement_term(
            {"setup": "OB_RETEST", "direction": "LONG",
             "order_block": {"idx": 4}}, None)
        self.assertIsNone(fact)
        self.assertEqual(delta, 0)
        self.assertIn("no inducement pool", why)

    def test_a_setup_with_no_zone_is_asked_nothing(self):
        from signals.rules.smc_rules import _inducement_term
        self.assertEqual(_inducement_term({"setup": "SFP", "direction": "SHORT"},
                                          None), (None, None))

    def test_a_breaker_is_not_asked_about_the_pool_that_guarded_its_zone(self):
        """A breaker's liquidity was already taken and its polarity flipped;
        the pool that once guarded the approach is a different question."""
        from signals.rules.smc_rules import inducement_for
        guards = {(4, 9): {"price": 1.0}}
        breaker = {"setup": "RP_BREAKER",
                   "breaker": {"origin_ob": {"idx": 4, "created_by_break_idx": 9}}}
        self.assertIsNone(inducement_for(breaker, guards))
        self.assertEqual(
            inducement_for({"order_block": {"idx": 4, "created_by_break_idx": 9}},
                           guards),
            {"price": 1.0})


# ── the arithmetic on the card still checks out ─────────────────────────────

class TheTrailStillAddsUp(TestCase):
    """The card's <summary> reads "How this scored N/100" and invites the
    arithmetic to be checked. Three new terms are applied after `build_card`
    has already clamped and written its trail, which is exactly where the sum
    breaks if they are applied carelessly."""

    def test_every_card_on_every_frame_sums_to_its_own_conviction(self):
        from signals.rules.smc_rules import scan_symbol
        for name, df in (("sfp", _sfp_frame()),
                         ("zone", _zone_frame(displaced=True)),
                         ("drift", _zone_frame(displaced=False))):
            for card in scan_symbol("AAA", "4h", df=df):
                self.assertEqual(
                    _trail_total(card["reasons"]), card["conviction"],
                    "%s/%s trail does not sum to its own conviction: %r"
                    % (name, card["setup"], card["reasons"]))

    def test_a_clamped_bonus_reports_what_it_actually_moved(self):
        from signals.rules.smc_rules import apply_conviction_term
        card = {"conviction": 94, "reasons": ["base 30"]}
        apply_conviction_term(card, 12, "armed")
        self.assertEqual(card["conviction"], 100)
        self.assertTrue(card["reasons"][-1].endswith("+6"), card["reasons"])

    def test_a_clamped_penalty_reports_what_it_actually_moved(self):
        from signals.rules.smc_rules import apply_conviction_term
        card = {"conviction": 5, "reasons": ["base 30"]}
        apply_conviction_term(card, -15, "against the bias")
        self.assertEqual(card["conviction"], 0)
        self.assertTrue(card["reasons"][-1].endswith("-5"), card["reasons"])

    def test_the_higher_timeframe_pass_shares_the_same_clamp(self):
        """`signals.mtf` kept a private copy of this; two clamps drift apart."""
        import inspect

        from signals import mtf
        source = inspect.getsource(mtf)
        self.assertIn("apply_conviction_term", source)
        self.assertNotIn("def _apply(", source)


class WhatThePlatformStores(TestCase):
    def test_the_new_evidence_is_persisted_with_the_card(self):
        from signals.models_smc import SmcSignal
        from signals.rules.smc_rules import persist_cards, scan_symbol
        cards = scan_symbol("AAA", "4h", df=_zone_frame())
        persist_cards(cards, "AAA", "4h")
        row = SmcSignal.objects.filter(setup="OB_RETEST").get()
        for key in ("displacement", "bias", "inducement"):
            self.assertIn(key, row.raw["ict"])
        self.assertTrue(row.raw["ict"]["displacement"]["displaced"])

    def test_the_nominal_deltas_are_not_stored_beside_the_landed_ones(self):
        """`terms` holds what each term asked for; the trail holds what it got.
        Storing both invites a reader to add up the wrong one."""
        from signals.rules.smc_rules import scan_symbol
        card = _ob_retest(scan_symbol("AAA", "4h", df=_zone_frame()))
        self.assertNotIn("terms", card["ict"])

    def test_a_quiet_market_still_produces_no_cards(self):
        """The fixtures are doing work — a flat series must find nothing."""
        from signals.rules.smc_rules import scan_symbol
        self.assertEqual(scan_symbol("AAA", "4h", df=_flat_frame()), [])
