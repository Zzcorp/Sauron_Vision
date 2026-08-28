"""Tests for the hypothesis grading fix — a measurement failure is not a
refutation.

The bug: `_resolve_regime_holds` returned `report.regime_label == expected`
outright, so a claim of "trending" graded against a BrainReport that stored
REGIME_UNKNOWN (the "we could not classify it" sentinel) came back REFUTED
with the note `actual=unknown`. Six such rows dragged sauron_mind's trust to
0.424 and had the platform's own strategist telling the operator to discount
its brain.

Covers:
  - unknown actual vs a trending claim → unresolvable, never refuted
  - a claim OF "unknown" against an unknown actual → confirmed
  - a genuinely wrong claim → still refuted
  - the other resolvers with the same shape (thin sample, missing node,
    missing report)
  - grading against the report that witnessed the DEADLINE, not the newest
  - the AgentPrediction mirror leaves unresolvable rows unevaluated so the
    Brier maths cannot score them as misses
  - repair_hypothesis_grading finds exactly the mis-refuted rows, is a no-op
    on a clean database, and appends to the audit chain instead of editing it
"""
from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone


# ── Helpers ───────────────────────────────────────────────────────────────

def _due_hypothesis(*, criteria, confidence=0.7, source="sauron_mind",
                    claim="claim", deadline_minutes_ago=5,
                    agent_prediction=None):
    """Mint a due hypothesis DIRECTLY, bypassing the creation gate.

    Several tests here exercise the resolvers against malformed legacy
    criteria the gate now refuses at post time — and the resolvers must
    stay robust to rows that predate it."""
    from brain.knowledge_models import Hypothesis
    return Hypothesis.objects.create(
        claim_text=claim, claim_payload={},
        resolution_criteria=dict(criteria or {}),
        confidence=confidence, source_agent=source,
        resolution_deadline=(timezone.now()
                             - timedelta(minutes=deadline_minutes_ago)),
        agent_prediction=agent_prediction,
    )


def _report(regime, *, minutes_ago=0, error=""):
    """Create a BrainReport at a controlled timestamp (created_at is
    auto_now_add, so it has to be rewritten after insert)."""
    from brain.models import BrainReport
    r = BrainReport.objects.create(regime_label=regime, regime_confidence=0.8,
                                    error=error)
    if minutes_ago:
        BrainReport.objects.filter(id=r.id).update(
            created_at=timezone.now() - timedelta(minutes=minutes_ago))
        r.refresh_from_db()
    return r


def _perf_rows(**overrides):
    row = {"rule_name": "rule_x", "asset_class": "stock", "n": 5,
           "n_wins": 2, "n_losses": 3, "win_rate": 0.4, "avg_r": -0.5,
           "expectancy": -0.5, "avg_duration_min": 60,
           "last_traded_at": timezone.now()}
    row.update(overrides)
    return [row]


# ── regime_holds ──────────────────────────────────────────────────────────

class RegimeHoldsGradingTests(TestCase):
    def test_unknown_actual_is_unresolvable_not_refuted(self):
        """The heart of the bug: an unclassified regime cannot refute."""
        from brain.hypotheses import resolve_due
        from brain.knowledge_models import Hypothesis

        h = _due_hypothesis(
            criteria={"kind": "regime_holds", "regime": "trending"})
        _report("unknown")

        result = resolve_due()

        h.refresh_from_db()
        self.assertEqual(h.outcome, Hypothesis.OUTCOME_UNRESOLVABLE)
        self.assertEqual(result["refuted"], 0)
        self.assertEqual(result["unresolvable"], 1)
        # The note has to say plainly why, not just "actual=unknown".
        self.assertIn("never classified", h.resolution_notes)
        self.assertIn("trending", h.resolution_notes)

    def test_unknown_claim_against_unknown_actual_is_confirmed(self):
        """A claim about our own blindness comes true when we are blind."""
        from brain.hypotheses import resolve_due
        from brain.knowledge_models import Hypothesis

        h = _due_hypothesis(
            criteria={"kind": "regime_holds", "regime": "unknown"})
        _report("unknown")

        result = resolve_due()

        h.refresh_from_db()
        self.assertEqual(h.outcome, Hypothesis.OUTCOME_CONFIRMED)
        self.assertEqual(result["confirmed"], 1)

    def test_genuinely_wrong_claim_is_still_refuted(self):
        from brain.hypotheses import resolve_due
        from brain.knowledge_models import Hypothesis

        h = _due_hypothesis(
            criteria={"kind": "regime_holds", "regime": "trending"})
        _report("risk_off")

        result = resolve_due()

        h.refresh_from_db()
        self.assertEqual(h.outcome, Hypothesis.OUTCOME_REFUTED)
        self.assertEqual(result["refuted"], 1)
        self.assertIn("actual=risk_off", h.resolution_notes)

    def test_matching_claim_is_confirmed(self):
        from brain.hypotheses import resolve_due
        from brain.knowledge_models import Hypothesis

        h = _due_hypothesis(
            criteria={"kind": "regime_holds", "regime": "trending"})
        _report("trending")

        resolve_due()

        h.refresh_from_db()
        self.assertEqual(h.outcome, Hypothesis.OUTCOME_CONFIRMED)

    def test_missing_regime_in_criteria_is_unresolvable(self):
        from brain.hypotheses import resolve_due
        from brain.knowledge_models import Hypothesis

        h = _due_hypothesis(criteria={"kind": "regime_holds"})
        _report("trending")

        resolve_due()

        h.refresh_from_db()
        self.assertEqual(h.outcome, Hypothesis.OUTCOME_UNRESOLVABLE)


# ── Deadline as the evidence window ───────────────────────────────────────

class DeadlineEvidenceTests(TestCase):
    def test_grades_against_the_report_that_witnessed_the_deadline(self):
        """Newest ≠ relevant. A report a day later answers a different
        question than the one the claim was written against."""
        from brain.hypotheses import resolve_due
        from brain.knowledge_models import Hypothesis

        h = _due_hypothesis(
            criteria={"kind": "regime_holds", "regime": "trending"},
            deadline_minutes_ago=120)
        # Witness at the deadline: trending. Newest report: risk_off.
        _report("trending", minutes_ago=110)
        _report("risk_off", minutes_ago=1)

        resolve_due()

        h.refresh_from_db()
        self.assertEqual(h.outcome, Hypothesis.OUTCOME_CONFIRMED)
        self.assertIn("actual=trending", h.resolution_notes)

    def test_report_before_the_deadline_is_not_evidence(self):
        """A reading taken before the horizon closed says nothing about
        whether the claim held to the deadline."""
        from brain.hypotheses import resolve_due
        from brain.knowledge_models import Hypothesis

        h = _due_hypothesis(
            criteria={"kind": "regime_holds", "regime": "trending"},
            deadline_minutes_ago=30)
        _report("trending", minutes_ago=90)   # pre-deadline only

        result = resolve_due()

        h.refresh_from_db()
        # Grace window still open → stays pending for the next pass.
        self.assertEqual(h.outcome, Hypothesis.OUTCOME_PENDING)
        self.assertEqual(result["deferred"], 1)

    def test_defers_while_the_grace_window_is_open(self):
        from brain.hypotheses import resolve_due
        from brain.knowledge_models import Hypothesis

        h = _due_hypothesis(
            criteria={"kind": "regime_holds", "regime": "trending"})

        result = resolve_due()

        h.refresh_from_db()
        self.assertEqual(h.outcome, Hypothesis.OUTCOME_PENDING)
        self.assertEqual(result["deferred"], 1)
        self.assertEqual(result["unresolvable"], 0)

    def test_unresolvable_once_the_grace_window_has_elapsed(self):
        from brain.hypotheses import REPORT_GRACE_HOURS, resolve_due
        from brain.knowledge_models import Hypothesis

        h = _due_hypothesis(
            criteria={"kind": "regime_holds", "regime": "trending"},
            deadline_minutes_ago=(REPORT_GRACE_HOURS * 60) + 30)

        result = resolve_due()

        h.refresh_from_db()
        self.assertEqual(h.outcome, Hypothesis.OUTCOME_UNRESOLVABLE)
        self.assertEqual(result["unresolvable"], 1)
        self.assertIn("no brain report", h.resolution_notes)

    def test_errored_reports_are_not_evidence(self):
        from brain.hypotheses import resolve_due
        from brain.knowledge_models import Hypothesis

        h = _due_hypothesis(
            criteria={"kind": "regime_holds", "regime": "trending"})
        _report("risk_off", error="synthesis blew up")

        result = resolve_due()

        h.refresh_from_db()
        self.assertEqual(h.outcome, Hypothesis.OUTCOME_PENDING)
        self.assertEqual(result["deferred"], 1)


# ── rule_avg_r ────────────────────────────────────────────────────────────

class RuleAvgRGradingTests(TestCase):
    def _resolve_with(self, rows, criteria):
        from brain.hypotheses import resolve_due
        h = _due_hypothesis(criteria=criteria)
        with patch("bot_program.bot_grading.bot_performance_summary",
                   return_value=rows):
            result = resolve_due()
        h.refresh_from_db()
        return h, result

    def test_thin_sample_is_unresolvable(self):
        """One closed trade measures that trade, not the rule."""
        from brain.knowledge_models import Hypothesis
        h, result = self._resolve_with(
            _perf_rows(n=1, avg_r=-0.9),
            {"kind": "rule_avg_r", "rule_name": "rule_x",
             "comparator": ">=", "threshold": 0.0})
        self.assertEqual(h.outcome, Hypothesis.OUTCOME_UNRESOLVABLE)
        self.assertEqual(result["refuted"], 0)
        self.assertIn("only 1 graded trade", h.resolution_notes)

    def test_sufficient_sample_still_refutes_a_wrong_claim(self):
        from brain.knowledge_models import Hypothesis
        h, _ = self._resolve_with(
            _perf_rows(n=6, avg_r=-0.5),
            {"kind": "rule_avg_r", "rule_name": "rule_x",
             "comparator": ">=", "threshold": 0.0})
        self.assertEqual(h.outcome, Hypothesis.OUTCOME_REFUTED)
        self.assertIn("n=6", h.resolution_notes)

    def test_empty_window_is_unresolvable(self):
        from brain.knowledge_models import Hypothesis
        h, _ = self._resolve_with(
            [], {"kind": "rule_avg_r", "rule_name": "rule_x",
                 "comparator": ">=", "threshold": 0.0})
        self.assertEqual(h.outcome, Hypothesis.OUTCOME_UNRESOLVABLE)
        self.assertIn("closed since the claim was posted",
                      h.resolution_notes)

    def test_the_window_is_measured_from_the_claim_not_from_now(self):
        """A 7-day window passed as `days` covered ~156 of 168 hours the
        model had ALREADY READ before writing the claim, so the score
        measured "did the agent restate the last fortnight"."""
        from brain.hypotheses import resolve_due
        _due_hypothesis(criteria={"kind": "rule_avg_r",
                                  "rule_name": "rule_x",
                                  "comparator": ">=", "threshold": 0.0})
        # Its own patch, not _resolve_with's — that helper opens one on the
        # same target, which would shadow this one and leave it uncalled.
        with patch("bot_program.bot_grading.bot_performance_summary",
                   return_value=_perf_rows()) as m:
            resolve_due()
        self.assertTrue(m.called)
        self.assertIn("since", m.call_args.kwargs,
                      "graded on a window, not on the post-claim record")
        self.assertIsNotNone(m.call_args.kwargs["since"])

    def test_missing_rule_name_is_unresolvable(self):
        from brain.knowledge_models import Hypothesis
        h, _ = self._resolve_with(_perf_rows(), {"kind": "rule_avg_r"})
        self.assertEqual(h.outcome, Hypothesis.OUTCOME_UNRESOLVABLE)

    def test_unknown_comparator_is_unresolvable(self):
        from brain.knowledge_models import Hypothesis
        h, _ = self._resolve_with(
            _perf_rows(n=8), {"kind": "rule_avg_r", "rule_name": "rule_x",
                              "comparator": "≈", "threshold": 0.0})
        self.assertEqual(h.outcome, Hypothesis.OUTCOME_UNRESOLVABLE)

    def test_asset_class_buckets_are_pooled_n_weighted(self):
        """Two buckets, opposite signs — grading off rows[0] would score
        whichever bucket was built first."""
        from brain.knowledge_models import Hypothesis
        rows = _perf_rows(n=2, avg_r=1.0) + _perf_rows(
            n=8, avg_r=-1.0, asset_class="forex")
        h, _ = self._resolve_with(
            rows, {"kind": "rule_avg_r", "rule_name": "rule_x",
                   "comparator": ">=", "threshold": 0.0})
        # Pooled avg_r = (2*1.0 + 8*-1.0)/10 = -0.6 → claim of ">= 0" fails.
        self.assertEqual(h.outcome, Hypothesis.OUTCOME_REFUTED)
        self.assertIn("n=10", h.resolution_notes)


# ── anomaly_persists ──────────────────────────────────────────────────────

class AnomalyPersistsGradingTests(TestCase):
    def test_never_recorded_anomaly_is_unresolvable(self):
        from brain.hypotheses import resolve_due
        from brain.knowledge_models import Hypothesis

        h = _due_hypothesis(
            criteria={"kind": "anomaly_persists", "anomaly_key": "ghost"})

        result = resolve_due()

        h.refresh_from_db()
        self.assertEqual(h.outcome, Hypothesis.OUTCOME_UNRESOLVABLE)
        self.assertEqual(result["refuted"], 0)
        self.assertIn("never recorded", h.resolution_notes)

    def test_faded_anomaly_is_still_refuted(self):
        from brain.hypotheses import resolve_due
        from brain.knowledge_models import Hypothesis, KnowledgeNode

        KnowledgeNode.upsert(kind=KnowledgeNode.KIND_ANOMALY, key="fading",
                              payload={"key": "fading"}, confidence=0.1,
                              source="t")
        h = _due_hypothesis(
            criteria={"kind": "anomaly_persists", "anomaly_key": "fading"})

        resolve_due()

        h.refresh_from_db()
        self.assertEqual(h.outcome, Hypothesis.OUTCOME_REFUTED)


# ── Trust maths ───────────────────────────────────────────────────────────

class TrustMathsTests(TestCase):
    def _linked_prediction(self, predicted="trending"):
        from ai_agents.models import AgentPrediction
        return AgentPrediction.objects.create(
            agent="sauron_mind", prediction_type="regime_persistence",
            predicted_value=predicted, confidence=0.8,
            expected_resolution_at=timezone.now() + timedelta(hours=1),
        )

    def test_unresolvable_leaves_the_mirror_unevaluated(self):
        """was_correct=False on an ungraded claim is the same bug one table
        over: both Brier consumers select on was_correct__isnull=False."""
        from brain.hypotheses import resolve_due

        pred = self._linked_prediction()
        _due_hypothesis(criteria={"kind": "regime_holds", "regime": "trending"},
                        agent_prediction=pred)
        _report("unknown")

        resolve_due()

        pred.refresh_from_db()
        self.assertIsNone(pred.was_correct)
        self.assertIsNone(pred.evaluated_at)

    def test_refuted_still_mirrors_as_a_miss(self):
        from brain.hypotheses import resolve_due

        pred = self._linked_prediction()
        _due_hypothesis(criteria={"kind": "regime_holds", "regime": "trending"},
                        agent_prediction=pred)
        _report("risk_off")

        resolve_due()

        pred.refresh_from_db()
        self.assertIs(pred.was_correct, False)
        self.assertIsNotNone(pred.evaluated_at)

    def test_brain_trust_score_ignores_ungraded_mirrors(self):
        from brain.context import _brain_trust_score
        from brain.hypotheses import resolve_due

        pred = self._linked_prediction()
        _due_hypothesis(criteria={"kind": "regime_holds", "regime": "trending"},
                        agent_prediction=pred)
        _report("unknown")
        resolve_due()

        # Unknown renders as no-data, never as a 0.0 score.
        self.assertIsNone(_brain_trust_score())

    def test_agent_trust_score_excludes_unresolvable(self):
        from brain.hypotheses import agent_trust_score
        from brain.knowledge_models import Hypothesis

        # Four confident hits...
        for i in range(4):
            h = _due_hypothesis(criteria={"kind": "regime_holds",
                                          "regime": "trending"},
                                 confidence=0.9, source="A", claim=f"hit{i}")
            Hypothesis.objects.filter(id=h.id).update(
                outcome=Hypothesis.OUTCOME_CONFIRMED,
                resolved_at=timezone.now())
        clean = agent_trust_score("A")

        # ...plus a confident claim we simply failed to measure.
        h = _due_hypothesis(criteria={"kind": "regime_holds",
                                      "regime": "trending"},
                             confidence=0.9, source="A", claim="unmeasured")
        Hypothesis.objects.filter(id=h.id).update(
            outcome=Hypothesis.OUTCOME_UNRESOLVABLE,
            resolved_at=timezone.now())

        self.assertEqual(agent_trust_score("A"), clean)


# ── brain.calibration resolvers (AgentPrediction path) ────────────────────

class BrainCalibrationResolverTests(TestCase):
    def _pred(self, ptype="regime_persistence", value="trending"):
        from ai_agents.models import AgentPrediction
        return AgentPrediction.objects.create(
            agent="sauron_mind", prediction_type=ptype,
            predicted_value=value, confidence=0.8,
            expected_resolution_at=timezone.now() - timedelta(minutes=5),
        )

    def test_unclassified_regime_leaves_prediction_unevaluated(self):
        from brain.calibration import resolve_due_brain_predictions

        pred = self._pred()
        _report("unknown")

        result = resolve_due_brain_predictions()

        pred.refresh_from_db()
        self.assertIsNone(pred.was_correct)
        self.assertEqual(result["ungradeable"], 1)
        self.assertEqual(result["resolved"], 0)
        self.assertIn("unclassified", pred.actual_value)

    def test_no_report_yet_leaves_prediction_unevaluated(self):
        from brain.calibration import resolve_due_brain_predictions

        pred = self._pred()

        result = resolve_due_brain_predictions()

        pred.refresh_from_db()
        self.assertIsNone(pred.was_correct)
        self.assertEqual(result["ungradeable"], 1)

    def test_measured_mismatch_is_still_wrong(self):
        from brain.calibration import resolve_due_brain_predictions

        pred = self._pred()
        _report("risk_off")

        result = resolve_due_brain_predictions()

        pred.refresh_from_db()
        self.assertIs(pred.was_correct, False)
        self.assertEqual(result["resolved"], 1)

    def test_thin_rule_sample_leaves_prediction_unevaluated(self):
        from brain.calibration import resolve_due_brain_predictions

        pred = self._pred(ptype="rule_decay_continues", value="rule_x")
        with patch("bot_program.bot_grading.bot_performance_summary",
                   return_value=_perf_rows(n=1, avg_r=-2.0)):
            result = resolve_due_brain_predictions()

        pred.refresh_from_db()
        self.assertIsNone(pred.was_correct)
        self.assertEqual(result["ungradeable"], 1)


# ── Repair command ────────────────────────────────────────────────────────

class RepairCommandTests(TestCase):
    """The operator's live shape: six regime hypotheses refuted with
    `actual=unknown`, alongside genuine grades that must not move."""

    N_MIS_REFUTED = 6

    def _legacy_mis_refuted(self, i, *, with_prediction=False):
        from ai_agents.models import AgentPrediction
        from brain.knowledge_models import Hypothesis

        pred = None
        if with_prediction:
            pred = AgentPrediction.objects.create(
                agent="sauron_mind", prediction_type="regime_persistence",
                predicted_value="trending", confidence=0.7,
                expected_resolution_at=timezone.now() - timedelta(hours=2),
                was_correct=False, actual_value="actual=unknown",
                evaluated_at=timezone.now(),
            )
        h = _due_hypothesis(
            criteria={"kind": "regime_holds", "regime": "trending"},
            claim=f"[regime_persistence] trending #{i}",
            agent_prediction=pred)
        # Exactly what the old resolver wrote.
        Hypothesis.objects.filter(id=h.id).update(
            outcome=Hypothesis.OUTCOME_REFUTED,
            resolved_at=timezone.now(),
            resolution_notes="actual=unknown")
        h.refresh_from_db()
        return h, pred

    def _genuinely_refuted(self):
        from brain.knowledge_models import Hypothesis
        h = _due_hypothesis(
            criteria={"kind": "regime_holds", "regime": "trending"},
            claim="honestly wrong")
        Hypothesis.objects.filter(id=h.id).update(
            outcome=Hypothesis.OUTCOME_REFUTED,
            resolved_at=timezone.now(),
            resolution_notes="actual=risk_off expected=trending")
        h.refresh_from_db()
        return h

    def _seed(self):
        rows = [self._legacy_mis_refuted(i, with_prediction=(i < 2))
                for i in range(self.N_MIS_REFUTED)]
        return [h for h, _ in rows], [p for _, p in rows if p], self._genuinely_refuted()

    @staticmethod
    def _run(*args):
        out = StringIO()
        call_command("repair_hypothesis_grading", *args, stdout=out)
        return out.getvalue()

    def test_no_op_on_a_clean_database(self):
        from bot_program.audit_models import AuditLogEntry
        out = self._run("--apply")
        self.assertIn("Nothing to repair", out)
        self.assertFalse(AuditLogEntry.objects.filter(
            kind="hypothesis_resolution_corrected").exists())

    def test_clean_grades_are_left_alone(self):
        from brain.knowledge_models import Hypothesis
        honest = self._genuinely_refuted()
        self._run("--apply")
        honest.refresh_from_db()
        self.assertEqual(honest.outcome, Hypothesis.OUTCOME_REFUTED)

    def test_dry_run_writes_nothing(self):
        from brain.knowledge_models import Hypothesis
        from bot_program.audit_models import AuditLogEntry

        mis, _, _ = self._seed()
        out = self._run()

        self.assertIn("DRY RUN", out)
        self.assertEqual(
            Hypothesis.objects.filter(
                outcome=Hypothesis.OUTCOME_REFUTED).count(),
            self.N_MIS_REFUTED + 1)
        self.assertEqual(AuditLogEntry.objects.count(), 0)
        for h in mis:
            h.refresh_from_db()
            self.assertEqual(h.outcome, Hypothesis.OUTCOME_REFUTED)

    def test_apply_repairs_exactly_the_mis_refuted_rows(self):
        from brain.knowledge_models import Hypothesis

        mis, preds, honest = self._seed()
        out = self._run("--apply")

        self.assertIn(f"Repaired {self.N_MIS_REFUTED}", out)
        for h in mis:
            h.refresh_from_db()
            self.assertEqual(h.outcome, Hypothesis.OUTCOME_UNRESOLVABLE)
            # Original note preserved, correction appended.
            self.assertIn("actual=unknown", h.resolution_notes)
            self.assertIn("repair_hypothesis_grading", h.resolution_notes)
        honest.refresh_from_db()
        self.assertEqual(honest.outcome, Hypothesis.OUTCOME_REFUTED)
        for p in preds:
            p.refresh_from_db()
            self.assertIsNone(p.was_correct)
            self.assertIsNone(p.evaluated_at)

    def test_apply_is_idempotent(self):
        from brain.knowledge_models import Hypothesis
        from bot_program.audit_models import AuditLogEntry

        self._seed()
        self._run("--apply")
        n_audit = AuditLogEntry.objects.count()
        outcomes = list(Hypothesis.objects.order_by("id")
                        .values_list("id", "outcome"))

        second = self._run("--apply")

        self.assertIn("Nothing to repair", second)
        self.assertEqual(AuditLogEntry.objects.count(), n_audit)
        self.assertEqual(
            list(Hypothesis.objects.order_by("id").values_list("id", "outcome")),
            outcomes)

    def test_audit_history_is_appended_not_rewritten(self):
        from bot_program.audit import record_hypothesis_resolved, verify_chain
        from bot_program.audit_models import AuditLogEntry

        mis, _, _ = self._seed()
        # The original resolutions as the live log would hold them.
        for h in mis:
            record_hypothesis_resolved(hypothesis=h, outcome="refuted",
                                        resolution_notes="actual=unknown")
        originals = list(AuditLogEntry.objects
                         .filter(kind="hypothesis_resolved")
                         .order_by("id")
                         .values("id", "payload_hash", "data"))

        self._run("--apply")

        # Every original entry is byte-identical afterwards.
        self.assertEqual(
            list(AuditLogEntry.objects.filter(kind="hypothesis_resolved")
                 .order_by("id").values("id", "payload_hash", "data")),
            originals)
        corrections = AuditLogEntry.objects.filter(
            kind="hypothesis_resolution_corrected")
        self.assertEqual(corrections.count(), self.N_MIS_REFUTED)
        entry = corrections.order_by("id").first()
        self.assertEqual(entry.data["previous_outcome"], "refuted")
        self.assertEqual(entry.data["corrected_outcome"], "unresolvable")
        self.assertIn("not-measured", entry.data["reason"])
        # And the chain still verifies end to end.
        self.assertTrue(verify_chain()["ok"])

    def test_repairs_standalone_ungradeable_predictions(self):
        from ai_agents.models import AgentPrediction

        pred = AgentPrediction.objects.create(
            agent="sauron_mind", prediction_type="regime_persistence",
            predicted_value="trending", confidence=0.8,
            expected_resolution_at=timezone.now() - timedelta(hours=2),
            was_correct=False, actual_value="unknown",
            evaluated_at=timezone.now(),
        )
        honest = AgentPrediction.objects.create(
            agent="sauron_mind", prediction_type="regime_persistence",
            predicted_value="trending", confidence=0.8,
            expected_resolution_at=timezone.now() - timedelta(hours=2),
            was_correct=False, actual_value="risk_off",
            evaluated_at=timezone.now(),
        )

        self._run("--apply")

        pred.refresh_from_db()
        honest.refresh_from_db()
        self.assertIsNone(pred.was_correct)
        self.assertIs(honest.was_correct, False)

    def test_trust_score_recovers_after_repair(self):
        from brain.hypotheses import agent_trust_score
        from brain.knowledge_models import Hypothesis

        # Two honest hits alongside the six mis-refuted rows.
        for i in range(2):
            h = _due_hypothesis(
                criteria={"kind": "regime_holds", "regime": "trending"},
                claim=f"hit{i}", confidence=0.7)
            Hypothesis.objects.filter(id=h.id).update(
                outcome=Hypothesis.OUTCOME_CONFIRMED,
                resolved_at=timezone.now())
        self._seed()

        corrupted = agent_trust_score("sauron_mind")
        self._run("--apply")
        repaired = agent_trust_score("sauron_mind")

        self.assertIsNotNone(corrupted)
        self.assertIsNotNone(repaired)
        self.assertGreater(repaired, corrupted)
