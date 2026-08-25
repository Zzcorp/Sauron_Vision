"""The hypothesis market stops accepting bets nobody can settle.

65% of graded hypotheses died UNRESOLVABLE and 176 sat PENDING — many of
them claims that could NEVER be graded: an unknown resolver kind, a
regime label the classifier doesn't speak, a rule bet with no rule name.
The gate refuses those at creation with UnmeasurableClaim (every posting
site already wraps the call), and resolve_due stops skipping legacy
unknown-kind rows forever — past deadline, they grade UNRESOLVABLE with
an honest note instead of haunting the pending count.

Run with:  python manage.py test tests.test_hypothesis_gate
"""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone


def _post(**kw):
    from brain.hypotheses import post_hypothesis
    defaults = dict(
        claim_text="the trending regime holds",
        source_agent="test_agent",
        resolution_criteria={"kind": "regime_holds", "regime": "trending"},
    )
    defaults.update(kw)
    return post_hypothesis(**defaults)


class CreationGateTests(TestCase):
    def test_a_measurable_claim_still_posts(self):
        hyp = _post()
        self.assertEqual(hyp.resolution_criteria["kind"], "regime_holds")

    def test_an_unknown_kind_is_refused(self):
        from brain.hypotheses import UnmeasurableClaim
        with self.assertRaises(UnmeasurableClaim):
            _post(resolution_criteria={"kind": "vibes_hold"})

    def test_no_criteria_at_all_is_refused(self):
        """The old default — free-form dict, empty allowed — is exactly
        how unresolvable claims got minted."""
        from brain.hypotheses import UnmeasurableClaim
        with self.assertRaises(UnmeasurableClaim):
            _post(resolution_criteria=None)

    def test_a_regime_the_classifier_does_not_speak_is_refused(self):
        from brain.hypotheses import UnmeasurableClaim
        with self.assertRaises(UnmeasurableClaim):
            _post(resolution_criteria={"kind": "regime_holds",
                                       "regime": "sideways_chop"})

    def test_a_rule_bet_without_a_rule_name_is_refused(self):
        from brain.hypotheses import UnmeasurableClaim
        with self.assertRaises(UnmeasurableClaim):
            _post(resolution_criteria={"kind": "rule_avg_r"})

    def test_a_comparator_the_resolver_cannot_read_is_refused(self):
        from brain.hypotheses import UnmeasurableClaim
        with self.assertRaises(UnmeasurableClaim):
            _post(resolution_criteria={"kind": "rule_avg_r",
                                       "rule_name": "r1",
                                       "comparator": "=="})

    def test_a_non_numeric_threshold_is_refused(self):
        from brain.hypotheses import UnmeasurableClaim
        with self.assertRaises(UnmeasurableClaim):
            _post(resolution_criteria={"kind": "rule_avg_r",
                                       "rule_name": "r1",
                                       "threshold": "break-even"})

    def test_a_non_integer_window_or_min_n_is_refused(self):
        """The resolver int()-casts both; a poisoned value used to crash
        it on every nightly pass forever — pending pollution one field
        to the left of the gated ones."""
        from brain.hypotheses import UnmeasurableClaim
        with self.assertRaises(UnmeasurableClaim):
            _post(resolution_criteria={"kind": "rule_avg_r",
                                       "rule_name": "r1",
                                       "window_days": "14d"})
        with self.assertRaises(UnmeasurableClaim):
            _post(resolution_criteria={"kind": "rule_avg_r",
                                       "rule_name": "r1",
                                       "min_n": "three"})

    def test_a_non_finite_threshold_is_refused(self):
        """NaN loses every comparison and inf decides them by direction:
        the grade would be fixed at creation, not by evidence."""
        from brain.hypotheses import UnmeasurableClaim
        for bad in ("NaN", "inf", float("inf"), float("nan")):
            with self.assertRaises(UnmeasurableClaim, msg=repr(bad)):
                _post(resolution_criteria={"kind": "rule_avg_r",
                                           "rule_name": "r1",
                                           "threshold": bad})

    def test_an_anomaly_bet_without_a_key_is_refused(self):
        from brain.hypotheses import UnmeasurableClaim
        with self.assertRaises(UnmeasurableClaim):
            _post(resolution_criteria={"kind": "anomaly_persists"})

    def test_the_refusal_is_a_value_error_every_caller_survives(self):
        """All eight posting sites wrap post_hypothesis in try/except;
        the gate must stay inside that contract."""
        from brain.hypotheses import UnmeasurableClaim
        self.assertTrue(issubclass(UnmeasurableClaim, ValueError))

    def test_valid_rule_and_anomaly_claims_still_post(self):
        h1 = _post(resolution_criteria={
            "kind": "rule_avg_r", "rule_name": "r1",
            "comparator": "<", "threshold": 0.0, "window_days": 14})
        h2 = _post(resolution_criteria={
            "kind": "anomaly_persists", "anomaly_key": "rvol:TSLA"})
        self.assertEqual(h1.resolution_criteria["rule_name"], "r1")
        self.assertEqual(h2.resolution_criteria["anomaly_key"],
                         "rvol:TSLA")


class ZombieGradingTests(TestCase):
    def _legacy(self, criteria, hours_past=1, agent_prediction=None):
        """A row minted before the gate existed — created directly, the
        way the pending mountain actually accumulated."""
        from brain.knowledge_models import Hypothesis
        return Hypothesis.objects.create(
            claim_text="legacy claim",
            source_agent="old_agent",
            resolution_criteria=criteria,
            confidence=0.5,
            resolution_deadline=timezone.now() - timedelta(hours=hours_past),
            agent_prediction=agent_prediction,
        )

    def test_an_unknown_kind_past_deadline_grades_unresolvable(self):
        from brain.hypotheses import resolve_due
        from brain.knowledge_models import Hypothesis
        hyp = self._legacy({"kind": "vibes_hold"})
        counts = resolve_due()
        hyp.refresh_from_db()
        self.assertEqual(hyp.outcome, Hypothesis.OUTCOME_UNRESOLVABLE)
        self.assertIn("no resolver registered", hyp.resolution_notes)
        self.assertEqual(counts["unresolvable"], 1)
        self.assertEqual(counts["skipped"], 0)

    def test_an_unresolvable_zombie_leaves_was_correct_null(self):
        """UNRESOLVABLE must never reach the Brier maths — the invariant
        the module docstring stakes everything on. The prediction is
        REALLY linked here: the mirror block must run, write the
        ungradeable note, and stamp neither verdict nor evaluation."""
        from ai_agents.models import AgentPrediction
        from brain.hypotheses import resolve_due
        from brain.knowledge_models import Hypothesis
        pred = AgentPrediction.objects.create(
            agent="sauron_mind", prediction_type="regime_persistence",
            predicted_value="trending", confidence=0.7,
            expected_resolution_at=timezone.now() - timedelta(hours=1),
        )
        hyp = self._legacy({"kind": "vibes_hold"}, agent_prediction=pred)
        resolve_due()
        hyp.refresh_from_db()
        pred.refresh_from_db()
        self.assertEqual(hyp.outcome, Hypothesis.OUTCOME_UNRESOLVABLE)
        self.assertIsNone(pred.was_correct)
        self.assertIsNone(pred.evaluated_at)
        self.assertTrue(pred.actual_value.startswith("ungradeable:"))

    def test_a_zombie_is_dated_when_it_came_due(self):
        """resolved_at = the deadline, not cleanup night — stamping the
        whole backlog "now" would flood every recent-resolved window
        (research snapshot, dashboard list) the night this deploys."""
        from brain.hypotheses import resolve_due
        hyp = self._legacy({"kind": "vibes_hold"}, hours_past=72)
        resolve_due()
        hyp.refresh_from_db()
        self.assertEqual(hyp.resolved_at, hyp.resolution_deadline)

    def test_a_poisoned_legacy_window_grades_unresolvable(self):
        """Pre-gate rows with non-numeric window/min_n crashed the
        resolver into `skipped` on every pass, forever."""
        from brain.hypotheses import resolve_due
        from brain.knowledge_models import Hypothesis
        hyp = self._legacy({"kind": "rule_avg_r", "rule_name": "r1",
                            "window_days": "14d"})
        counts = resolve_due()
        hyp.refresh_from_db()
        self.assertEqual(hyp.outcome, Hypothesis.OUTCOME_UNRESOLVABLE)
        self.assertEqual(counts["skipped"], 0)

    def test_a_non_finite_legacy_threshold_grades_unresolvable(self):
        from brain.hypotheses import resolve_due
        from brain.knowledge_models import Hypothesis
        hyp = self._legacy({"kind": "rule_avg_r", "rule_name": "r1",
                            "threshold": "NaN"})
        resolve_due()
        hyp.refresh_from_db()
        self.assertEqual(hyp.outcome, Hypothesis.OUTCOME_UNRESOLVABLE)
        self.assertIn("non-finite", hyp.resolution_notes)

    def test_malformed_criteria_do_not_abort_the_pass(self):
        """A non-dict criteria blob (direct DB write, corruption) used to
        raise OUTSIDE the per-row try and kill the whole nightly pass —
        every later row silently ungraded."""
        from brain.hypotheses import resolve_due
        from brain.knowledge_models import Hypothesis
        bad = self._legacy("regime_holds")
        other = self._legacy({"kind": "vibes_hold"})
        counts = resolve_due()
        bad.refresh_from_db()
        other.refresh_from_db()
        self.assertEqual(bad.outcome, Hypothesis.OUTCOME_UNRESOLVABLE)
        self.assertEqual(other.outcome, Hypothesis.OUTCOME_UNRESOLVABLE)
        self.assertEqual(counts["unresolvable"], 2)


    def test_a_gradeable_row_still_grades_normally(self):
        """The zombie path must not swallow the real resolvers."""
        from brain.models import BrainReport
        from brain.hypotheses import resolve_due
        from brain.knowledge_models import Hypothesis
        hyp = self._legacy({"kind": "regime_holds", "regime": "trending"})
        BrainReport.objects.create(regime_label="trending",
                                   regime_confidence=0.8)
        resolve_due()
        hyp.refresh_from_db()
        self.assertEqual(hyp.outcome, Hypothesis.OUTCOME_CONFIRMED)

    def test_a_crashing_resolver_is_still_skipped_not_burned(self):
        """Transient failures retry next pass; only the permanently
        unmeasurable get graded away."""
        from unittest.mock import patch

        from brain.hypotheses import resolve_due
        from brain.knowledge_models import Hypothesis
        hyp = self._legacy({"kind": "regime_holds", "regime": "trending"})
        with patch.dict("brain.hypotheses.RESOLVERS",
                        {"regime_holds": lambda h: 1 / 0}):
            counts = resolve_due()
        hyp.refresh_from_db()
        self.assertEqual(hyp.outcome, Hypothesis.OUTCOME_PENDING)
        self.assertEqual(counts["skipped"], 1)


class RegimeVocabularyTests(TestCase):
    """LLM regime tokens meet the classifier's vocabulary at the mapping
    layer — not at the gate (refusal) and not at grading (unresolvable)."""

    def test_near_canonical_tokens_are_normalized(self):
        from brain.hypotheses import canonical_regime
        self.assertEqual(canonical_regime("Risk-On"), "risk_on")
        self.assertEqual(canonical_regime("mean-reversion"),
                         "mean_reverting")
        self.assertEqual(canonical_regime(" Trending "), "trending")
        self.assertIsNone(canonical_regime("sideways chop"))
        self.assertIsNone(canonical_regime(None))

    def test_the_synthesizer_maps_or_declines_never_mints_garbage(self):
        from brain.synthesizer import _prediction_to_hypothesis_criteria
        good = _prediction_to_hypothesis_criteria("regime_persistence",
                                                  "Risk-Off")
        self.assertEqual(good, {"kind": "regime_holds",
                                "regime": "risk_off"})
        self.assertIsNone(_prediction_to_hypothesis_criteria(
            "regime_persistence", "choppy vibes"))

