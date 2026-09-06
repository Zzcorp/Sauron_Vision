"""The daily briefing stops narrating a frozen window as today's tape.

The feed gate in synthesizer.py stops the brain paying Opus rates to read
stale bars. It does not cover the strategist, which builds its OWN snapshot
and calls Opus unconditionally once a day — and every number in a briefing is
second-hand: the Hurst range, the vol forecasts, the rule R-multiples and even
the list of open positions all arrive through BrainReports and KnowledgeNodes
rather than being measured at briefing time.

`_build_strategist_snapshot` selects "the last 6 reports", with no time floor.
That reads as "the last 3 hours" right up to the moment the brain stops, after
which the same six rows are served every morning, ageing a day at a time,
under a heading that says Today. The 2026-09-05 and 2026-09-06 briefings both
opened on a Hurst range of 0.446–0.544 — identical to three decimals at both
ends across two trading days, with fresh token counts each morning — because
the bar feed had frozen and one window was being re-read.

The feed gate makes this WORSE rather than better: silencing the brain leaves
those six rows to age indefinitely. So this gate is required by that one, not
merely adjacent to it.

Run with:  python manage.py test tests.test_strategist_history_gate
"""
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.utils import timezone


def _report(*, age_hours, regime="mean_reverting", error=""):
    """One BrainReport whose created_at is `age_hours` in the past.

    Written through a queryset update because created_at is auto_now_add:
    assigning it on the instance is silently overwritten on save, which would
    make every row in this file fresh and every assertion below vacuous.
    """
    from brain.models import BrainReport
    r = BrainReport.objects.create(
        regime_label=regime, regime_confidence=0.55,
        portfolio_health_score=0.5, narrative_md="Hurst 0.446-0.544.",
        error=error)
    stamp = timezone.now() - timedelta(hours=age_hours)
    BrainReport.objects.filter(pk=r.pk).update(created_at=stamp)
    return r


def _node(*, age_hours, kind="regime", key="global"):
    from brain.knowledge_models import KnowledgeNode
    n = KnowledgeNode.objects.create(
        kind=kind, key=key, payload={"hurst": 0.492}, confidence=0.6)
    stamp = timezone.now() - timedelta(hours=age_hours)
    KnowledgeNode.objects.filter(pk=n.pk).update(created_at=stamp)
    return n


class EveryRowTheStrategistReadsCarriesItsAgeTests(TestCase):

    def _snap(self):
        from brain.strategist import _build_strategist_snapshot
        return _build_strategist_snapshot()

    def test_a_fresh_report_reports_its_age_and_the_history_is_not_stale(self):
        _report(age_hours=0.5)
        snap = self._snap()
        self.assertEqual(len(snap["recent_brain_reports"]), 1)
        self.assertLess(snap["recent_brain_reports"][0]["age_hours"], 2)
        self.assertLess(snap["brain_history_age_hours"], 2)
        self.assertFalse(snap["brain_history_stale"])

    def test_an_aged_history_is_labelled_stale_with_its_age(self):
        from brain.strategist import STALE_BRAIN_HISTORY_HOURS
        _report(age_hours=STALE_BRAIN_HISTORY_HOURS + 30)
        snap = self._snap()
        self.assertTrue(snap["brain_history_stale"])
        self.assertGreater(snap["brain_history_age_hours"],
                           STALE_BRAIN_HISTORY_HOURS)

    def test_the_freshest_report_governs_not_the_oldest(self):
        """Six rows span a window; the question is only how long ago the brain
        last spoke."""
        from brain.strategist import STALE_BRAIN_HISTORY_HOURS
        _report(age_hours=STALE_BRAIN_HISTORY_HOURS + 40)
        _report(age_hours=0.5)
        snap = self._snap()
        self.assertFalse(snap["brain_history_stale"])
        self.assertLess(snap["brain_history_age_hours"], 2)

    def test_knowledge_nodes_carry_their_age_too(self):
        """"Current" means un-superseded, which is not the same as recent: a
        regime node stays current forever if nothing supersedes it."""
        _report(age_hours=0.5)
        _node(age_hours=200)
        snap = self._snap()
        node = next(n for n in snap["knowledge_graph"] if n["kind"] == "regime")
        self.assertGreater(node["age_hours"], 100)

    def test_an_empty_history_leaves_the_age_unknown_not_zero(self):
        snap = self._snap()
        self.assertEqual(snap["recent_brain_reports"], [])
        self.assertIsNone(snap["brain_history_age_hours"])
        self.assertFalse(snap["brain_history_stale"])


class AStaleBrainHistorySkipsTheBriefingTests(TestCase):

    def setUp(self):
        User.objects.create_user("strat_staff", password="x", is_staff=True)

    def _run(self):
        from brain.strategist import run_strategist_now
        return run_strategist_now()

    def test_a_silent_brain_makes_no_llm_call_and_writes_no_briefing(self):
        from unittest.mock import patch

        from brain.briefing_models import StrategistBriefing
        from brain.strategist import STALE_BRAIN_HISTORY_HOURS
        _report(age_hours=STALE_BRAIN_HISTORY_HOURS + 30)
        before = StrategistBriefing.objects.count()
        with patch("ai_agents.providers.claude_provider.ClaudeProvider"
                   ".complete") as complete:
            out = self._run()
        complete.assert_not_called()
        self.assertEqual(out["status"], "skipped")
        self.assertTrue(out["ok"])
        # No row at all — not an error row. An error row is a claim about the
        # strategist, and the strategist is working perfectly; it is being fed
        # a corpse.
        self.assertEqual(StrategistBriefing.objects.count(), before)

    def test_the_operator_is_told_and_pointed_at_the_feed(self):
        from brain.strategist import STALE_BRAIN_HISTORY_HOURS
        _report(age_hours=STALE_BRAIN_HISTORY_HOURS + 30)
        self._run()
        from alerts.models import Notification
        note = Notification.objects.filter(
            title__icontains="brain has gone quiet").first()
        self.assertIsNotNone(note)
        # The brain going quiet is a SYMPTOM — the feed gate fired upstream.
        # An alert that stops at the symptom sends the operator to the wrong
        # subsystem.
        self.assertIn("check_feeds", note.body)

    def test_a_fresh_history_and_the_briefing_runs(self):
        """The gate must refuse a corpse, not the ordinary morning."""
        from unittest.mock import patch

        _report(age_hours=0.4)
        with patch("ai_agents.providers.claude_provider.ClaudeProvider"
                   ".complete",
                   return_value=('{"outlook_md": "x", "posture": "balanced"}',
                                 {"input_tokens": 1, "output_tokens": 1,
                                  "cost_usd": 0.0})) as complete:
            out = self._run()
        complete.assert_called_once()
        self.assertNotEqual(out.get("status"), "skipped")

    def test_no_history_at_all_does_not_trip_the_gate(self):
        """A fresh install has no brain reports; that is the "not set up yet"
        state the health page already reports, and skipping here would hide it
        behind a staleness complaint about a brain that has never run."""
        from unittest.mock import patch

        with patch("ai_agents.providers.claude_provider.ClaudeProvider"
                   ".complete",
                   return_value=('{"outlook_md": "x", "posture": "balanced"}',
                                 {"input_tokens": 1, "output_tokens": 1,
                                  "cost_usd": 0.0})) as complete:
            out = self._run()
        complete.assert_called_once()
        self.assertNotEqual(out.get("status"), "skipped")

    def test_an_error_row_is_not_fresh_history(self):
        """`filter(error="")` already excludes them, and it must stay that
        way: a brain that fails every half hour is writing rows constantly
        while saying nothing, and counting those as a live history would let
        the briefing narrate a regime nobody computed."""
        from unittest.mock import patch

        from brain.strategist import STALE_BRAIN_HISTORY_HOURS
        _report(age_hours=STALE_BRAIN_HISTORY_HOURS + 30)
        _report(age_hours=0.2, error="provider timeout")
        with patch("ai_agents.providers.claude_provider.ClaudeProvider"
                   ".complete") as complete:
            out = self._run()
        complete.assert_not_called()
        self.assertEqual(out["status"], "skipped")


class TheModelIsToldTheAgesExistTests(SimpleTestCase):
    """Adding `age_hours` to the JSON is half a fix. The strategist's prompt
    lists its inputs explicitly, and a field absent from that list is a field
    the model has no reason to read — it produced a confident regime narration
    off two-day-old rows whose timestamps were already in its context."""

    def test_the_system_prompt_names_the_age_fields(self):
        from brain.strategist import StrategistAgent
        prompt = StrategistAgent().get_system_prompt()
        self.assertIn("age_hours", prompt)
        self.assertIn("brain_history_age_hours", prompt)

    def test_the_prompt_says_the_strategist_measures_nothing_itself(self):
        """The reason the ages matter: there is no live number anywhere in the
        snapshot to fall back on."""
        from brain.strategist import StrategistAgent
        self.assertIn("measure nothing yourself",
                      StrategistAgent().get_system_prompt())


class TheTwoGatesAreOneMechanismTests(SimpleTestCase):
    """A pin on the relationship, because it is the part that is easy to
    regress: whoever removes the feed gate must know this one depends on it,
    and whoever tunes either threshold must see both."""

    def test_the_strategist_limit_is_bounded_at_BOTH_ends(self):
        """A lower bound alone is not a pin — it is half a pin, and the open
        half is the dangerous one.

        This test asserted only `>= 6.0`. An adversarial probe set the
        constant to 1200.0 — fifty days, which is an off switch wearing a
        threshold's name — and every test in this file still passed, because
        the behavioural tests above are all written RELATIVE to the constant
        (`age_hours=STALE_BRAIN_HISTORY_HOURS + 30`) and therefore follow it
        anywhere it goes. A gate is only a gate at a plausible value, so the
        plausible range is what has to be pinned.

        Upper bound of 48h: the claim this constant makes is "the brain has
        stopped", and past two days that claim is no longer a diagnosis.
        """
        from brain.strategist import STALE_BRAIN_HISTORY_HOURS
        self.assertGreaterEqual(STALE_BRAIN_HISTORY_HOURS, 6.0)
        self.assertLessEqual(STALE_BRAIN_HISTORY_HOURS, 48.0)

    def test_the_two_gates_together_bound_the_blind_window(self):
        """How long a dead feed can still produce confident output.

        The bars freeze; the brain keeps synthesising until they are
        STALE_PROBE_HOURS old; its last report then ages for
        STALE_BRAIN_HISTORY_HOURS before the briefing stops too. The sum is
        the whole exposure, and it is the number that actually matters — a
        previous version of this test compared the two constants with an
        arbitrary factor of four, which pinned nothing and accepted 60h on
        one side and 1200h on the other.
        """
        from brain.strategist import STALE_BRAIN_HISTORY_HOURS
        from brain.synthesizer import STALE_PROBE_HOURS
        self.assertLessEqual(STALE_PROBE_HOURS + STALE_BRAIN_HISTORY_HOURS,
                             48.0)

    def test_the_brain_goes_quiet_first(self):
        """Ordering matters for the alerts: the feed gate must fire before
        this one, so the operator's first notification names the bar feed
        rather than the briefing three steps downstream of it. Structural,
        not numeric — the strategist's clock only starts once the brain stops
        writing — so what is pinned is that the brain's alert is the cheaper
        one to reach: its cooldown must be no longer than this one's."""
        import inspect

        from brain import strategist, synthesizer
        brain_cooldown = inspect.getsource(synthesizer).split(
            "cooldown_hours=")[1].split(")")[0]
        strat_cooldown = inspect.getsource(strategist).split(
            "cooldown_hours=")[1].split(")")[0]
        self.assertLessEqual(int(brain_cooldown), int(strat_cooldown))
