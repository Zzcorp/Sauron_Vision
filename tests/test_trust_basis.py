"""A trust score arrives with the arithmetic that produced it.

On 2026-09-07 the briefing told its operator:

    sauron_mind's trust score is 0.0 — but that's because every one of its
    last 30 hypotheses graded unresolvable, not wrong. [...] Trust the
    brain's diagnosis, not its confidence.

The code says the opposite. `agent_trust_score` excludes UNRESOLVABLE and
PENDING and returns None when nothing is left, and `_build_strategist_snapshot`
OMITS a None from the map. So a printed 0.0 cannot come from unresolvable
claims — it requires resolved ones with a Brier at or above 0.5, which is
confident MISSES on claims that did grade. The advice was exactly inverted.

Nothing hallucinated a number. The model had a 0.0 here and thirty
unresolvable rows in `recent_resolved_hypotheses`, and stitched a relation
between them that does not exist, because nothing in the snapshot said how the
score is computed. It is the same failure the age labels fixed for staleness:
give a model a bare number and it will explain it.

Run with:  python manage.py test tests.test_trust_basis
"""
from datetime import timedelta

from django.test import SimpleTestCase, TestCase
from django.utils import timezone


def _hyp(agent, outcome, *, confidence=0.8, resolved=True):
    from brain.knowledge_models import Hypothesis
    h = Hypothesis.objects.create(
        source_agent=agent, claim_text="x", confidence=confidence,
        outcome=outcome,
        resolution_deadline=timezone.now() + timedelta(hours=24))
    if resolved and outcome != Hypothesis.OUTCOME_PENDING:
        Hypothesis.objects.filter(pk=h.pk).update(
            resolved_at=timezone.now() - timedelta(hours=1))
    return h


def _snap():
    from brain.strategist import _build_strategist_snapshot
    return _build_strategist_snapshot()


class TheBasisTravelsWithTheScoreTests(TestCase):

    def test_an_agent_with_only_unresolvable_claims_is_absent_not_zero(self):
        """The fact the briefing got backwards, pinned at the source."""
        from brain.hypotheses import agent_trust_score
        from brain.knowledge_models import Hypothesis
        for _ in range(5):
            _hyp("sauron_mind", Hypothesis.OUTCOME_UNRESOLVABLE)
        self.assertIsNone(agent_trust_score("sauron_mind"))
        snap = _snap()
        self.assertNotIn("sauron_mind", snap["agent_trust_scores"])

    def test_the_basis_still_reports_it(self):
        """Absent from the score is not absent from the page: the operator
        still needs to see that the agent has been talking and not scoring."""
        from brain.knowledge_models import Hypothesis
        for _ in range(5):
            _hyp("sauron_mind", Hypothesis.OUTCOME_UNRESOLVABLE)
        basis = _snap()["agent_trust_basis"]["sauron_mind"]
        self.assertEqual(basis["unresolvable_n"], 5)
        self.assertEqual(basis["graded_n"], 0)
        self.assertFalse(basis["in_trust_score"])

    def test_a_zero_score_really_is_confident_misses(self):
        """Confidence 0.8 on claims that were all refuted gives a Brier of
        0.64, so 1 - 2*Brier floors at 0.0 — and every row counted is one the
        resolver actually graded."""
        from brain.hypotheses import agent_trust_score
        from brain.knowledge_models import Hypothesis
        for _ in range(4):
            _hyp("sauron_mind", Hypothesis.OUTCOME_REFUTED, confidence=0.8)
        self.assertEqual(agent_trust_score("sauron_mind"), 0.0)
        snap = _snap()
        self.assertEqual(snap["agent_trust_scores"]["sauron_mind"], 0.0)
        self.assertEqual(
            snap["agent_trust_basis"]["sauron_mind"]["graded_n"], 4)

    def test_the_two_populations_are_counted_apart(self):
        from brain.knowledge_models import Hypothesis
        for _ in range(3):
            _hyp("critic", Hypothesis.OUTCOME_CONFIRMED, confidence=0.7)
        for _ in range(7):
            _hyp("critic", Hypothesis.OUTCOME_UNRESOLVABLE)
        for _ in range(2):
            _hyp("critic", Hypothesis.OUTCOME_PENDING, resolved=False)
        basis = _snap()["agent_trust_basis"]["critic"]
        self.assertEqual(basis["graded_n"], 3)
        self.assertEqual(basis["unresolvable_n"], 7)
        self.assertEqual(basis["pending_n"], 2)
        self.assertTrue(basis["in_trust_score"])

    def test_the_note_states_the_rule_that_was_got_backwards(self):
        note = _snap()["agent_trust_note"]
        self.assertIn("UNRESOLVABLE and PENDING are excluded", note)
        self.assertIn("confident MISSES", note)
        self.assertIn("never mean", note)

    def test_the_scores_map_keeps_its_flat_shape(self):
        """Additive on purpose. Anything already reading
        agent_trust_scores expects {agent: float} and must keep getting it."""
        from brain.knowledge_models import Hypothesis
        _hyp("critic", Hypothesis.OUTCOME_CONFIRMED, confidence=0.7)
        scores = _snap()["agent_trust_scores"]
        self.assertIsInstance(scores["critic"], float)

    def test_an_empty_platform_does_not_raise(self):
        snap = _snap()
        self.assertEqual(snap["agent_trust_scores"], {})
        self.assertEqual(snap["agent_trust_basis"], {})


class TheModelIsToldNotToInventACauseTests(SimpleTestCase):
    """Adding the basis to the JSON is half a fix — the same half that was
    missing for staleness. The prompt lists its inputs explicitly, and a field
    absent from that list is one the model has no reason to consult."""

    def test_the_prompt_names_the_basis_and_forbids_the_invention(self):
        from brain.strategist import StrategistAgent
        prompt = StrategistAgent().get_system_prompt()
        self.assertIn("agent_trust_basis", prompt)
        self.assertIn("agent_trust_note", prompt)
        self.assertIn("never 'unresolvable'", prompt)

    def test_it_forbids_deriving_a_cause_from_neighbouring_numbers(self):
        from brain.strategist import StrategistAgent
        self.assertIn("invent a cause for a number",
                      StrategistAgent().get_system_prompt())
