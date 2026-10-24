"""One grader per Mind prediction (2026-10-24, PR2 item 3).

The bots read ONE number about the Mind: `_brain_trust_score`
(brain/context.py), 1 - 2*Brier over its last 50 graded AgentPredictions.
Its band softens report pauses (the bot entry gate, the review trigger on
open positions), the theme squeeze and the share allocator's risk-off cut.

Each of those rows was graded twice: the hourly pass (brain/calibration.py)
and the nightly mirror of its Hypothesis (brain/hypotheses.py resolve_due)
wrote over each other on different evidence. The hourly pass compared
regimes as raw strings ("Risk-On" against risk_on is a miss), measured a
rule on the seven days BEFORE the claim, graded a venue-less rule on the
pooled record, and re-graded every row the market had just called
unresolvable. A third grader (ai_agents/calibration.py) also took any
Mind row whose free-text type happened to be "direction".

Now a linked row is the market's alone; an orphan is graded hourly in the
classifier's words, from the claim on, on its venue; a row that can never
be graded is closed ungraded, not walked for ever.

Run with:  python manage.py test tests.test_mind_one_grader
"""
import io
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone


def _report(regime, *, minutes_ago=0):
    from brain.models import BrainReport
    r = BrainReport.objects.create(regime_label=regime,
                                   regime_confidence=0.8)
    if minutes_ago:
        BrainReport.objects.filter(pk=r.pk).update(
            created_at=timezone.now() - timedelta(minutes=minutes_ago))
        r.refresh_from_db()
    return r


def _pred(ptype="regime_persistence", value="trending", *, hours_due=0.1,
          conf=0.8, agent="sauron_mind", **kw):
    """A Mind prediction whose deadline passed `hours_due` hours ago."""
    from ai_agents.models import AgentPrediction
    return AgentPrediction.objects.create(
        agent=agent, prediction_type=ptype, predicted_value=value,
        confidence=conf,
        expected_resolution_at=timezone.now() - timedelta(hours=hours_due),
        **kw)


def _linked(pred, criteria, *, hours_due=0.1):
    """The market's twin of `pred`, due `hours_due` hours ago."""
    from brain.knowledge_models import Hypothesis
    h = Hypothesis.objects.create(
        claim_text=f"[{pred.prediction_type}] {pred.predicted_value}",
        source_agent="sauron_mind", resolution_criteria=criteria,
        confidence=pred.confidence, agent_prediction=pred,
        resolution_deadline=timezone.now() - timedelta(hours=hours_due))
    Hypothesis.objects.filter(pk=h.pk).update(
        created_at=timezone.now() - timedelta(hours=hours_due + 12))
    h.refresh_from_db()
    return h


def _hourly():
    from brain.calibration import resolve_due_brain_predictions
    return resolve_due_brain_predictions()


def _nightly():
    from brain.hypotheses import resolve_due
    return resolve_due()


def _perf(n=5, avg_r=-0.5):
    return [{"rule_name": "rule_x", "asset_class": "stock", "n": n,
             "n_wins": 1, "n_losses": n - 1, "win_rate": 0.2,
             "avg_r": avg_r, "expectancy": avg_r, "avg_duration_min": 60,
             "last_traded_at": timezone.now()}]


class OneGraderPerRowTests(TestCase):

    def test_the_hourly_grader_leaves_a_linked_row_to_the_market(self):
        p = _pred(value="Risk-On")
        _linked(p, {"kind": "regime_holds", "regime": "risk_on"})
        _report("risk_on")
        _hourly()
        p.refresh_from_db()
        self.assertIsNone(p.was_correct)
        self.assertIsNone(p.evaluated_at)
        _nightly()
        p.refresh_from_db()
        self.assertIs(p.was_correct, True)
        _hourly()
        p.refresh_from_db()
        self.assertIs(p.was_correct, True)

    def test_a_linked_unresolvable_claim_stays_ungraded(self):
        from brain.context import _brain_trust_score
        p = _pred(value="trending", hours_due=13)
        _linked(p, {"kind": "regime_holds", "regime": "trending"},
                hours_due=13)
        _nightly()          # no report witnessed the deadline: unresolvable
        p.refresh_from_db()
        self.assertIsNone(p.was_correct)
        _report("trending")  # a report lands afterwards
        _hourly()
        p.refresh_from_db()
        self.assertIsNone(p.was_correct)
        self.assertIsNone(_brain_trust_score())

    def test_the_two_numbers_agree_over_linked_rows(self):
        """Critique L1: the parity only breaks when an hourly pass follows
        the mirror on an UNRESOLVABLE linked row, so that pass is here."""
        from brain.context import _brain_trust_score
        from brain.hypotheses import agent_trust_score
        ok = _pred(value="risk_on", conf=0.9, hours_due=20)
        _linked(ok, {"kind": "regime_holds", "regime": "risk_on"},
                hours_due=20)
        _report("risk_on", minutes_ago=19 * 60)
        lost = _pred(value="trending", conf=0.9, hours_due=13)
        _linked(lost, {"kind": "regime_holds", "regime": "trending"},
                hours_due=13)
        _nightly()          # ok confirmed; lost: nothing witnessed it
        ok.refresh_from_db()
        lost.refresh_from_db()
        self.assertIs(ok.was_correct, True)
        self.assertIsNone(lost.was_correct)
        _report("risk_off")  # a report lands afterwards
        _hourly()
        self.assertIsNotNone(agent_trust_score("sauron_mind"))
        self.assertEqual(_brain_trust_score(),
                         agent_trust_score("sauron_mind"))


class OrphansAreGradedOnTheirOwnEvidenceTests(TestCase):

    def test_an_orphan_regime_is_read_in_the_classifiers_words(self):
        good = _pred(value="Risk-On")
        odd = _pred(value="choppy")
        _report("risk_on")
        _hourly()
        good.refresh_from_db()
        odd.refresh_from_db()
        self.assertIs(good.was_correct, True)
        self.assertIsNone(odd.was_correct)
        self.assertIsNotNone(odd.evaluated_at)
        self.assertEqual(odd.actual_value, "ungradeable_off_vocabulary")
        stamped = odd.evaluated_at
        _hourly()
        odd.refresh_from_db()
        self.assertEqual(odd.evaluated_at, stamped)

    def test_the_hourly_rule_measurement_starts_at_the_claim(self):
        p = _pred("rule_decay_continues", "rule_x@live")
        with patch("bot_program.bot_grading.world_performance_summary",
                   return_value=_perf()) as m:
            _hourly()
        self.assertTrue(m.called)
        self.assertIn("since", m.call_args.kwargs)
        self.assertGreaterEqual(m.call_args.kwargs["since"], p.created_at)
        p.refresh_from_db()
        self.assertIs(p.was_correct, True)

    def test_a_venue_less_rule_orphan_is_never_graded_on_the_pooled_record(self):
        p = _pred("rule_decay_continues", "rule_x")
        with patch("bot_program.bot_grading.bot_performance_summary",
                   return_value=_perf()) as pooled:
            result = _hourly()
        pooled.assert_not_called()
        p.refresh_from_db()
        self.assertIsNone(p.was_correct)
        self.assertIsNotNone(p.evaluated_at)
        self.assertEqual(p.actual_value, "ungradeable_no_venue")
        self.assertEqual(result["ungradeable"], 1)

    def test_a_thin_live_sample_leaves_the_row_open(self):
        """A guard: the thin-sample path on a venue-named rule (the sibling
        of tests/test_hypothesis_grading.py's pooled one, which now ends
        on the no-venue rule)."""
        p = _pred("rule_decay_continues", "rule_x@live")
        with patch("bot_program.bot_grading.world_performance_summary",
                   return_value=_perf(n=1, avg_r=-2.0)):
            result = _hourly()
        p.refresh_from_db()
        self.assertIsNone(p.was_correct)
        self.assertIsNone(p.evaluated_at)
        self.assertEqual(result["ungradeable"], 1)

    def test_an_orphan_ungradeable_twelve_hours_past_its_deadline_is_closed_ungraded(self):
        p = _pred(value="trending", hours_due=13)
        _hourly()           # no report since the deadline
        p.refresh_from_db()
        self.assertIsNone(p.was_correct)
        self.assertIsNotNone(p.evaluated_at)

    def test_an_orphan_ungradeable_within_twelve_hours_is_retried(self):
        """A guard: the retry inside the grace holds today and must keep
        holding once rows are closed past it."""
        p = _pred(value="trending", hours_due=2)
        _hourly()
        p.refresh_from_db()
        self.assertIsNone(p.evaluated_at)
        _report("trending")
        _hourly()
        p.refresh_from_db()
        self.assertIs(p.was_correct, True)

    def test_a_row_with_no_resolver_is_closed_ungraded(self):
        """Critique M6: walked and skipped every hour for ever, and held in
        /brain/'s pending count."""
        p = _pred("totally_made_up", "x")
        result = _hourly()
        self.assertEqual(result["skipped"], 1)
        p.refresh_from_db()
        self.assertIsNone(p.was_correct)
        self.assertIsNotNone(p.evaluated_at)
        self.assertEqual(p.actual_value, "ungradeable_no_resolver")

    def test_the_agents_grader_leaves_the_minds_rows_alone(self):
        """Critique M6: ai_agents/calibration.py grades any agent's
        "direction" row; the Mind's type is free text."""
        from ai_agents.calibration import resolve_pending_predictions
        mind = _pred("direction", "up", hours_due=24 * 30,
                     instrument_symbol="MOG1")
        other = _pred("direction", "up", hours_due=24 * 30,
                      instrument_symbol="MOG1", agent="council_hand")
        resolve_pending_predictions()
        mind.refresh_from_db()
        other.refresh_from_db()
        self.assertIsNone(mind.evaluated_at)
        self.assertEqual(mind.actual_value, "")
        self.assertIsNotNone(other.evaluated_at)


class TheNumbersAreSaidTests(TestCase):

    def test_the_strategist_snapshot_names_the_bots_number(self):
        from brain.strategist import _build_strategist_snapshot
        p = _pred(value="risk_on", conf=0.9)
        _report("risk_on")
        _hourly()
        snap = _build_strategist_snapshot()
        bots = snap["mind_trust_bots"]
        self.assertIn("score", bots)
        self.assertIn("band", bots)
        self.assertEqual(bots["graded_n"], 1)
        self.assertIn("the number the bots act on", bots["note"])
        p.refresh_from_db()

    def test_the_brain_page_pending_count_skips_rows_that_can_never_be_graded(self):
        from brain.calibration import awaiting_grade
        from ai_agents.models import AgentPrediction
        _pred(value="choppy")                       # closed by the pass
        _pred("totally_made_up", "x")               # closed by the pass
        _pred(value="trending", hours_due=-5)        # not yet due: pending
        lost = _pred(value="trending", hours_due=13)
        _linked(lost, {"kind": "regime_holds", "regime": "trending"},
                hours_due=13)
        _nightly()                                  # unresolvable: done
        _hourly()
        qs = AgentPrediction.objects.filter(agent="sauron_mind")
        self.assertEqual(awaiting_grade(qs).count(), 1)
        user = User.objects.create_user(username="og_page", password="x")
        self.client.force_login(user)
        r = self.client.get("/brain/")
        self.assertEqual(r.context["n_pending"], 1)

    def test_mind_contract_trust_writes_nothing_and_projects_the_band(self):
        from ai_agents.models import AgentPrediction
        from brain.knowledge_models import Hypothesis
        # an hourly grade that disagrees with its hypothesis (pre-fix rows)
        p = _pred(value="Risk-On", conf=0.9)
        h = _linked(p, {"kind": "regime_holds", "regime": "risk_on"})
        AgentPrediction.objects.filter(pk=p.pk).update(
            was_correct=False, evaluated_at=timezone.now())
        Hypothesis.objects.filter(pk=h.pk).update(
            outcome="confirmed", resolved_at=timezone.now())
        before = (AgentPrediction.objects.count(),
                  Hypothesis.objects.count(),
                  list(AgentPrediction.objects.values_list(
                      "was_correct", flat=True)))
        out = io.StringIO()
        call_command("mind_contract", "trust", stdout=out)
        text = out.getvalue()
        after = (AgentPrediction.objects.count(),
                 Hypothesis.objects.count(),
                 list(AgentPrediction.objects.values_list(
                     "was_correct", flat=True)))
        self.assertEqual(before, after)
        self.assertIn("disagrees with their hypothesis: 1", text)
        self.assertIn("projected bots' number", text)
        self.assertIn("band high", text)
