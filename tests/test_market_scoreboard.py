"""The hypothesis market stops lying about its own scoreboard.

The page reported CONFIRMED 0 beside "3.5% of resolved" — arithmetically
impossible, and it read as "this market has never once been right". The
count and the rate came from the same variable, but the leaderboard loop
below them rebound the name, so the tile showed whichever agent sorted
last while the rate kept the true figure. Solving 77/(C+77+142) = 0.339
gives C = 8: eight confirmations the operator was told did not exist.

Two more, found in the same pass: an anomaly claim was judged against a
confidence floor its own writer can never reach on a fresh promotion,
and the grader sat downstream of five graph steps inside their shared
try — so one of them raising meant nothing was graded that night, with
a dashboard that looked exactly like a quiet one.

Run with:  python manage.py test tests.test_market_scoreboard
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone


def _hyp(agent, outcome, **kw):
    from brain.knowledge_models import Hypothesis
    defaults = dict(
        claim_text="c", source_agent=agent, confidence=0.6,
        resolution_criteria={"kind": "regime_holds", "regime": "trending"},
        resolution_deadline=timezone.now() - timedelta(hours=2),
        outcome=outcome, resolved_at=timezone.now())
    defaults.update(kw)
    return Hypothesis.objects.create(**defaults)


class TheTileTellsTheMarketsTruthTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            "mkt_op", "op@x.x", "x")
        self.client.force_login(self.user)

    def test_the_headline_count_is_the_market_not_the_last_agent(self):
        """`aaa` confirmed one; `zzz` confirmed none and sorts last. The
        tile used to report zzz's count as the market's."""
        from brain.knowledge_models import Hypothesis
        _hyp("aaa", Hypothesis.OUTCOME_CONFIRMED)
        _hyp("zzz", Hypothesis.OUTCOME_REFUTED)
        resp = self.client.get("/hypotheses/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["n_confirmed"], 1)

    def test_the_count_and_the_rate_cannot_disagree(self):
        """Zero cannot be 3.5% of anything — the tile and the rate beside
        it must be computed from the same number."""
        from brain.knowledge_models import Hypothesis
        for _ in range(3):
            _hyp("aaa", Hypothesis.OUTCOME_CONFIRMED)
        _hyp("zzz", Hypothesis.OUTCOME_REFUTED)
        ctx = self.client.get("/hypotheses/").context
        n, rate = ctx["n_confirmed"], ctx["confirmed_rate"]
        self.assertEqual(n, 3)
        self.assertGreater(rate, 0)
        self.assertAlmostEqual(rate, 75.0, places=1)

    def test_the_leaderboard_still_reports_per_agent(self):
        """The fix must not cost the leaderboard its own numbers."""
        from brain.knowledge_models import Hypothesis
        _hyp("aaa", Hypothesis.OUTCOME_CONFIRMED)
        _hyp("aaa", Hypothesis.OUTCOME_REFUTED)
        _hyp("zzz", Hypothesis.OUTCOME_REFUTED)
        rows = {r["agent"]: r for r in
                self.client.get("/hypotheses/").context["leaderboard"]}
        self.assertEqual(rows["aaa"]["n_confirmed"], 1)
        self.assertEqual(rows["zzz"]["n_confirmed"], 0)


class AnAnomalyIsJudgedByItsOwnFloorTests(TestCase):
    def _node(self, key, confidence, minutes_ago=0):
        from brain.knowledge_models import KnowledgeNode
        node = KnowledgeNode.upsert(kind="anomaly", key=key,
                                    payload={"key": key},
                                    confidence=confidence, source="t")
        if minutes_ago:
            KnowledgeNode.objects.filter(id=node.id).update(
                created_at=timezone.now() - timedelta(minutes=minutes_ago))
        return node

    def _claim(self, key, deadline_minutes_ago=60):
        from brain.knowledge_models import Hypothesis
        return Hypothesis.objects.create(
            claim_text="persists", source_agent="critic", confidence=0.6,
            resolution_criteria={"kind": "anomaly_persists",
                                 "anomaly_key": key},
            resolution_deadline=(timezone.now()
                                 - timedelta(minutes=deadline_minutes_ago)))

    def test_a_freshly_promoted_anomaly_is_not_a_refutation(self):
        """Consolidation promotes at >=3 fires/24h and stores count/10,
        so the cheapest node that can exist scores 0.30. Judged against
        0.4 it graded REFUTED for existing at exactly the strength its
        own promotion rule demands."""
        from brain.hypotheses import _resolve_anomaly_persists
        self._node("rvol:TSLA", 0.30)
        result, note = _resolve_anomaly_persists(self._claim("rvol:TSLA"))
        self.assertTrue(result, note)

    def test_a_faded_anomaly_still_refutes(self):
        from brain.hypotheses import _resolve_anomaly_persists
        self._node("rvol:NVDA", 0.10)
        result, _ = _resolve_anomaly_persists(self._claim("rvol:NVDA"))
        self.assertFalse(result)

    def test_a_node_nobody_refreshed_answers_for_nothing(self):
        """KnowledgeNode.current never expires and consolidation only
        touches keys that fired in the last 24h — so a long-silent
        anomaly kept grading True on a stale confidence. That measures
        'was it hot once', not 'is it hot now'."""
        from brain.hypotheses import _resolve_anomaly_persists
        self._node("rvol:STALE", 0.8, minutes_ago=600)
        result, note = _resolve_anomaly_persists(
            self._claim("rvol:STALE", deadline_minutes_ago=60))
        self.assertIsNone(result)
        self.assertIn("refreshed", note)


class GradingOwesNothingToTheGraphTests(TestCase):
    def test_a_broken_graph_step_does_not_cost_the_night_of_grading(self):
        """resolve_due sat after five graph steps in their shared try;
        one raising meant nothing was graded, silently."""
        from unittest.mock import patch

        from brain.consolidation import consolidate_now
        with patch("brain.consolidation._consolidate_regime",
                   side_effect=RuntimeError("graph is down")), \
                patch("brain.hypotheses.resolve_due",
                      return_value={"confirmed": 2, "refuted": 1,
                                    "unresolvable": 0, "deferred": 0,
                                    "skipped": 0}) as graded:
            consolidate_now()
        graded.assert_called_once()

    def test_the_run_records_the_counters_it_used_to_discard(self):
        """A resolver crashing deterministically reports `skipped` every
        pass forever; with only confirmed+refuted stored, that stuck row
        was invisible."""
        from unittest.mock import patch

        from brain.consolidation import consolidate_now
        from brain.knowledge_models import ConsolidationRun
        with patch("brain.hypotheses.resolve_due",
                   return_value={"confirmed": 1, "refuted": 0,
                                 "unresolvable": 4, "deferred": 2,
                                 "skipped": 3}):
            consolidate_now()
        notes = ConsolidationRun.objects.latest("id").notes
        self.assertIn("4 unresolvable", notes)
        self.assertIn("2 deferred", notes)
        self.assertIn("3 skipped", notes)
