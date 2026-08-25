"""The critic gets receipts — and the burden of proof moves.

The platform's own health check caught the critic rubber-stamping
(dissent under the 5% floor) while one author ran up eight straight
refuted regime calls. It could do nothing else: the context carried a
world snapshot and a trust NUMBER, but not one graded outcome — the
critic audited claim #9 with no idea #1-#8 were all wrong. Now the
author's record and the same-kind history ride the context, a streak
is said in plain words, the prompt puts the burden of proof on the
streak, and selection catches the streak author's next claim first.

Run with:  python manage.py test tests.test_critic_receipts
"""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone


def _graded(source, outcome, *, kind="regime_holds", claim="c",
            minutes_ago=60):
    from brain.knowledge_models import Hypothesis
    h = Hypothesis.objects.create(
        claim_text=claim, source_agent=source, confidence=0.6,
        resolution_criteria={"kind": kind, "regime": "trending"},
        resolution_deadline=timezone.now() - timedelta(minutes=minutes_ago),
        outcome=outcome,
        resolved_at=timezone.now() - timedelta(minutes=minutes_ago),
    )
    return h


def _pending(source, *, kind="regime_holds", confidence=0.6, claim="p"):
    from brain.knowledge_models import Hypothesis
    return Hypothesis.objects.create(
        claim_text=claim, source_agent=source, confidence=confidence,
        resolution_criteria={"kind": kind, "regime": "trending"},
        resolution_deadline=timezone.now() + timedelta(hours=4),
    )


class RecordReaderTests(TestCase):
    def test_the_record_is_graded_only_newest_first(self):
        """Pending rows are not evidence and unresolvable rows are the
        platform's blind spot, not the author's judgment."""
        from brain.critic import _graded_record
        _graded("a1", "refuted", claim="old", minutes_ago=300)
        _graded("a1", "unresolvable", claim="blind", minutes_ago=200)
        _graded("a1", "confirmed", claim="new", minutes_ago=100)
        _pending("a1", claim="open")
        rows = _graded_record(source_agent="a1")
        self.assertEqual([r["claim"] for r in rows], ["new", "old"])
        self.assertEqual([r["outcome"] for r in rows],
                         ["confirmed", "refuted"])

    def test_the_kind_filter_scopes_the_receipts(self):
        from brain.critic import _graded_record
        _graded("a2", "refuted", kind="regime_holds", claim="regime")
        _graded("a2", "refuted", kind="rule_avg_r", claim="rule")
        rows = _graded_record(source_agent="a2", kind="regime_holds")
        self.assertEqual([r["claim"] for r in rows], ["regime"])

    def test_a_confirmed_call_breaks_the_streak(self):
        from brain.critic import _refuted_streak
        _graded("a3", "refuted", minutes_ago=400)
        _graded("a3", "confirmed", minutes_ago=300)
        _graded("a3", "refuted", minutes_ago=200)
        _graded("a3", "refuted", minutes_ago=100)
        self.assertEqual(_refuted_streak("a3"), 2)

    def test_unresolvable_never_enters_the_walk(self):
        """A measurement failure between two refutations must not end
        the streak the way a confirmed call does."""
        from brain.critic import _refuted_streak
        _graded("a4", "refuted", minutes_ago=300)
        _graded("a4", "unresolvable", minutes_ago=200)
        _graded("a4", "refuted", minutes_ago=100)
        self.assertEqual(_refuted_streak("a4"), 2)


class ReceiptsInContextTests(TestCase):
    def _context(self, hyp):
        from brain.critic import CriticAgent
        agent = CriticAgent.__new__(CriticAgent)
        return agent.build_context(hypothesis=hyp, snapshot={},
                                   source_agent_trust=0.0)

    def test_the_author_record_reaches_the_critic(self):
        _graded("sauron_mind", "refuted",
                claim="random walk, nothing to exploit")
        ctx = self._context(_pending("sauron_mind"))
        self.assertIn("Author's graded record", ctx)
        self.assertIn("random walk, nothing to exploit", ctx)
        self.assertIn("refuted", ctx)

    def test_the_same_kind_record_crosses_authors(self):
        """Another agent's graded regime call is a receipt too — the
        critic sees how this KIND of claim has actually been resolving."""
        _graded("someone_else", "confirmed", claim="mean reversion held")
        ctx = self._context(_pending("sauron_mind"))
        self.assertIn("same kind", ctx)
        self.assertIn("mean reversion held", ctx)

    def test_a_streak_is_said_in_plain_words(self):
        for i in range(3):
            _graded("sauron_mind", "refuted", minutes_ago=100 + i * 50)
        ctx = self._context(_pending("sauron_mind"))
        self.assertIn("ALL REFUTED", ctx)
        self.assertIn("burden of proof", ctx)

    def test_no_streak_no_siren(self):
        _graded("sauron_mind", "confirmed")
        ctx = self._context(_pending("sauron_mind"))
        self.assertNotIn("ALL REFUTED", ctx)

    def test_the_claim_under_review_is_not_its_own_receipt(self):
        """A pending row can be graded by a concurrent resolver between
        selection and review — its fresh refutation must appear neither
        in the record sections nor at the head of the streak siren."""
        from brain.critic import _graded_record, _refuted_streak
        h = _graded("a5", "refuted", claim="self")
        self.assertEqual(_graded_record(source_agent="a5",
                                        exclude_id=h.id), [])
        self.assertEqual(_refuted_streak("a5", exclude_id=h.id), 0)

    def test_a_nameless_author_is_nobody_not_everyone(self):
        """source_agent="" is storable; a truthiness check used to drop
        the filter and present EVERY agent's refutations as this
        nameless author's record — fabricated receipts."""
        from brain.critic import _graded_record, _refuted_streak
        _graded("someone", "refuted")
        _graded("someone", "refuted")
        self.assertEqual(_graded_record(source_agent=""), [])
        self.assertEqual(_refuted_streak(""), 0)

    def test_the_prompt_places_the_burden_of_proof(self):
        from brain.critic import CriticAgent
        prompt = CriticAgent.__new__(CriticAgent).get_system_prompt()
        self.assertIn("burden of proof", prompt)
        self.assertIn("EVIDENCE, not", prompt)
        self.assertIn("mis-calibrated", prompt)


class StreakSelectionTests(TestCase):
    def test_a_streak_author_outranks_a_merely_new_one(self):
        """Both authors score +1 for unknown/low trust; the streak adds
        the point that puts the serial offender's next claim first."""
        from brain.critic import select_hypotheses_for_review
        for i in range(3):
            _graded("streaky", "refuted", minutes_ago=100 + i * 50)
        target = _pending("streaky", claim="the ninth claim")
        _pending("fresh_face", claim="first ever")
        picked = select_hypotheses_for_review(max_n=1, sample_pct=0.0)
        self.assertEqual([h.id for h in picked], [target.id])
