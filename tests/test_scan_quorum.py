"""A composite must rest on the setup its author wrote.

Dropping an unmeasured leg from both sides of the weighted average is right —
an unmeasured leg is not a zero, and weighting it as one dilutes every leg
that did answer. But the same drop RENORMALISES the composite over the
survivors, so a two-leg setup whose second leg cannot answer silently becomes
a one-leg setup scoring the first at full confidence, and fires on evidence
its author never authorised alone.

The companion bug points the other way: an unknown metric or an out-of-range
percentage is a TYPO, not a market declining to answer, and excusing it from
the denominator lets a broken condition be carried over the line by the legs
that still work.

Run with:  python manage.py test tests.test_scan_quorum
"""
from datetime import timedelta
from decimal import Decimal

from django.test import SimpleTestCase, TestCase
from django.utils import timezone


class QuorumConstantTests(SimpleTestCase):
    def test_the_quorum_is_a_majority_and_not_unanimity(self):
        """Compared with `>`, so the constant is the line a majority must
        CLEAR, not reach. At `>=` a two-leg setup with one leg answering
        lands exactly on it and passes, which is the case the quorum exists
        to stop. Unanimity is the other wrong answer: a setup needing every
        leg every time goes dark on the first quiet data source."""
        from signals.opportunity_scanner import MEASURED_WEIGHT_QUORUM
        self.assertGreater(MEASURED_WEIGHT_QUORUM, 0.0)
        self.assertLess(MEASURED_WEIGHT_QUORUM, 1.0)
        self.assertEqual(MEASURED_WEIGHT_QUORUM, 0.5)


class RankRefusalShapeTests(SimpleTestCase):
    """The two refusals differ in exactly one field, and it decides whether a
    broken setup is held back or carried."""

    def test_a_data_refusal_is_not_measured(self):
        from signals.opportunity_scanner import _rank_refusal
        out = _rank_refusal({}, "outside the ranked field")
        self.assertIs(out["measured"], False)
        self.assertIs(out["authoring_error"], False)

    def test_an_authoring_error_stays_in_the_denominator(self):
        from signals.opportunity_scanner import _rank_refusal
        out = _rank_refusal({}, "unknown metric 'momentumm'", authoring=True)
        self.assertIs(out["measured"], True)
        self.assertIs(out["authoring_error"], True)

    def test_neither_is_ever_a_match(self):
        from signals.opportunity_scanner import _rank_refusal
        for kwargs in ({}, {"authoring": True}):
            out = _rank_refusal({}, "r", **kwargs)
            self.assertFalse(out["matched"])
            self.assertEqual(out["score"], 0.0)

    def test_a_typo_in_the_metric_is_an_authoring_error(self):
        """The evaluator's own exits, not just the helper."""
        from signals.opportunity_scanner import _eval_cross_sectional_rank
        out = _eval_cross_sectional_rank(
            {"metric": "momentumm", "side": "top", "scope": "universe"},
            None, timezone.now())
        self.assertIs(out.get("authoring_error"), True)
        self.assertIs(out["measured"], True)

    def test_an_out_of_range_selection_is_an_authoring_error(self):
        from signals.opportunity_scanner import _eval_cross_sectional_rank
        out = _eval_cross_sectional_rank(
            {"metric": "momentum", "side": "top", "scope": "universe",
             "select_pct": 5.0}, None, timezone.now())
        self.assertIs(out.get("authoring_error"), True)


class QuorumGatesTheCompositeTests(TestCase):
    """The behaviour, through the real scan loop."""

    def _setup(self, conditions, *, min_score=0.0):
        from signals.models_opportunity import OpportunitySetup
        return OpportunitySetup.objects.create(
            name="quorum_probe", description="d", direction="bullish",
            conditions=conditions, min_match_score=min_score,
            is_active=True, asset_classes=["stock"],
            suggested_horizon_days=5)

    def _instrument(self):
        from instruments.models import Instrument
        from market_data.models import PriceData
        inst, _ = Instrument.objects.get_or_create(
            symbol="QUOR", defaults={"name": "Quorum", "asset_class": "stock",
                                     "is_active": True})
        # A price, so a setup that CLEARS the quorum gets far enough to be
        # judged on its score rather than stopping at "no price data" — the
        # passing cases below would otherwise pass for the wrong reason.
        PriceData.objects.get_or_create(
            instrument=inst, timeframe="1d",
            timestamp=timezone.now() - timedelta(hours=1),
            defaults={"open": Decimal("100"), "high": Decimal("101"),
                      "low": Decimal("99"), "close": Decimal("100"),
                      "volume": 1000})
        return inst

    def _scan(self, setup):
        from signals.opportunity_scanner import scan_setup
        return scan_setup(setup, self._instrument(), now=timezone.now(),
                          emit=False)

    def test_one_of_two_legs_measured_does_not_reach_quorum(self):
        """Exactly the renormalisation case: a strong leg beside a leg that
        could not answer must not carry the setup alone."""
        from unittest.mock import patch
        setup = self._setup([{"kind": "a", "weight": 1.0},
                             {"kind": "b", "weight": 1.0}])
        answers = {"a": {"matched": True, "score": 1.0},
                   "b": {"matched": False, "score": 0.0, "measured": False}}
        with patch("signals.opportunity_scanner.has_kind", return_value=True), \
             patch.dict("signals.opportunity_scanner.EVALUATOR_REGISTRY",
                        {k: (lambda p, i, n, _v=v, **kw: _v)
                         for k, v in answers.items()}, clear=False):
            out = self._scan(setup)
        self.assertFalse(out["matched"])
        self.assertEqual(out.get("reason"), "not_enough_measured")

    def test_both_legs_measured_still_scores_normally(self):
        from unittest.mock import patch
        setup = self._setup([{"kind": "a", "weight": 1.0},
                             {"kind": "b", "weight": 1.0}])
        answers = {"a": {"matched": True, "score": 1.0},
                   "b": {"matched": True, "score": 1.0}}
        with patch("signals.opportunity_scanner.has_kind", return_value=True), \
             patch.dict("signals.opportunity_scanner.EVALUATOR_REGISTRY",
                        {k: (lambda p, i, n, _v=v, **kw: _v)
                         for k, v in answers.items()}, clear=False):
            out = self._scan(setup)
        self.assertTrue(out["matched"])
        self.assertEqual(out["score"], 1.0)

    def test_a_minor_leg_going_quiet_does_not_silence_the_setup(self):
        """Quorum is a majority of WEIGHT, not a headcount — a small leg
        failing must not take the setup down with it."""
        from unittest.mock import patch
        setup = self._setup([{"kind": "a", "weight": 4.0},
                             {"kind": "b", "weight": 1.0}])
        answers = {"a": {"matched": True, "score": 1.0},
                   "b": {"matched": False, "score": 0.0, "measured": False}}
        with patch("signals.opportunity_scanner.has_kind", return_value=True), \
             patch.dict("signals.opportunity_scanner.EVALUATOR_REGISTRY",
                        {k: (lambda p, i, n, _v=v, **kw: _v)
                         for k, v in answers.items()}, clear=False):
            out = self._scan(setup)
        self.assertTrue(out["matched"], out.get("reason"))

    def test_the_result_says_how_much_of_the_setup_answered(self):
        from unittest.mock import patch
        setup = self._setup([{"kind": "a", "weight": 1.0},
                             {"kind": "b", "weight": 1.0}])
        answers = {"a": {"matched": True, "score": 1.0},
                   "b": {"matched": False, "score": 0.0, "measured": False}}
        with patch("signals.opportunity_scanner.has_kind", return_value=True), \
             patch.dict("signals.opportunity_scanner.EVALUATOR_REGISTRY",
                        {k: (lambda p, i, n, _v=v, **kw: _v)
                         for k, v in answers.items()}, clear=False):
            out = self._scan(setup)
        self.assertEqual(out["authored_weight"], 2.0)
        self.assertEqual(out["measured_weight"], 1.0)
