"""Sauron reads its own reports (ai_agents/next_steps.py, 2026-10-03).

The operator: "Weekly Review — couldn't we make Sauron get it, so that he
can arrange the situation and get ready for the next steps? Same for the
morning and end-of-day brief." Every report now gets a second, cheap
reading that proposes at most seven structured steps; nothing acts until
the operator approves.

What the file pins:
  * only known rules and symbols survive; unknown refs are dropped;
  * one standing step per (kind, ref); the switch OFF reads nothing;
  * the staff group hears once, with the count and never the money;
  * approving a pause makes a RuleAction PROPOSAL (never applied here),
    approving a watch stars the instrument, rejecting records the no;
  * the page, the two staff-only POSTs and the command;
  * every report task calls the reader.

Run with:  python manage.py test tests.test_next_steps
"""
from datetime import timedelta
from io import StringIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from ai_agents import next_steps as ns
from ai_agents.models import ReportNextStep

STEPS = {"steps": [
    {"kind": "pause_rule", "ref": "golden_cross", "why": "Four losers in a row.",
     "confidence": 0.8},
    {"kind": "reduce_size", "ref": "made_up_rule", "why": "x", "confidence": 0.5},
    {"kind": "watch", "ref": "eurusd", "why": "ECB on Thursday.", "confidence": 0.6},
    {"kind": "watch", "ref": "ZZZZ", "why": "nothing", "confidence": 0.2},
    {"kind": "note", "ref": "", "why": "Keep size small into the NFP.",
     "confidence": 0.7},
    {"kind": "sell_everything", "ref": "", "why": "no", "confidence": 1.0},
]}


def _read(*parts):
    from pathlib import Path
    from django.conf import settings
    return Path(settings.BASE_DIR, *parts).read_text(encoding="utf-8")


class _On(TestCase):
    def setUp(self):
        from instruments.models import Instrument
        Instrument.objects.create(symbol="EURUSD", name="EURUSD",
                                  asset_class="forex")
        self.user = get_user_model().objects.create_user(
            "ns_u", password="x", is_staff=True)

    def _extract(self, kind="weekly_review", steps=STEPS, on=True):
        with mock.patch("core.platform_control.is_component_enabled",
                        return_value=on), \
                mock.patch("signals.rule_actuator.governed_rule_names",
                           return_value={"golden_cross", "rsi_bull_divergence"}), \
                mock.patch.object(ns.NextStepsAgent, "run",
                                  return_value=steps) as run, \
                mock.patch("bot_program.notifications.notify_staff") as say:
            made = ns.extract(kind, "Four losers in a row on golden cross...",
                              source_ref="Week of 28 Sep 2026")
        return made, run, say


class ReadingTests(_On):

    def test_only_known_refs_survive_and_the_group_hears_once(self):
        made, run, say = self._extract()
        self.assertEqual([(s.kind, s.ref) for s in made],
                         [("pause_rule", "golden_cross"), ("watch", "EURUSD"),
                          ("note", "")])
        self.assertEqual(made[0].report_kind, "weekly_review")
        self.assertEqual(made[0].source_ref, "Week of 28 Sep 2026")
        run.assert_called_once()
        ctx = run.call_args.kwargs
        self.assertIn("golden_cross", ctx["rules"])
        self.assertIn("EURUSD", ctx["symbols"])
        say.assert_called_once()
        body = say.call_args.kwargs["body"]
        self.assertIn("3 from the weekly review", body)
        self.assertIn("1 pause the rule", body)
        self.assertIn("Nothing is applied until you approve it", body)

    def test_a_standing_step_is_not_stacked(self):
        self._extract()
        made, _run, say = self._extract(kind="daily_briefing")
        self.assertEqual([s.kind for s in made], ["note"])
        self.assertEqual(ReportNextStep.objects.filter(
            kind="pause_rule", ref="golden_cross").count(), 1)
        say.assert_called_once()

    def test_the_switch_off_reads_nothing(self):
        made, run, say = self._extract(on=False)
        self.assertEqual(made, [])
        run.assert_not_called()
        say.assert_not_called()

    def test_a_reader_that_fails_fails_nothing(self):
        with mock.patch("core.platform_control.is_component_enabled",
                        return_value=True), \
                mock.patch.object(ns.NextStepsAgent, "run",
                                  side_effect=RuntimeError("boom")):
            self.assertEqual(ns.extract("weekly_review", "text"), [])

    def test_an_unanswered_step_expires(self):
        made, _r, _s = self._extract()
        ReportNextStep.objects.filter(pk=made[0].pk).update(
            created_at=timezone.now() - timedelta(days=ns.EXPIRE_DAYS + 1))
        self.assertEqual(ns.expire(), 1)
        self.assertEqual(ReportNextStep.objects.get(pk=made[0].pk).status,
                         ReportNextStep.EXPIRED)

    def test_the_parser_wants_strict_json(self):
        agent = ns.NextStepsAgent.__new__(ns.NextStepsAgent)
        self.assertEqual(agent.parse_response('```json\n{"steps": []}\n```'),
                         {"steps": []})
        with self.assertRaises(ValueError):
            agent.parse_response("Sure! Here are the steps: ...")
        with self.assertRaises(ValueError):
            agent.parse_response('{"nope": 1}')
        self.assertIn("No code fences", agent.get_system_prompt())


class AnsweringTests(_On):

    def test_approving_a_pause_proposes_a_rule_action_never_applies(self):
        from signals.models_control import RuleAction
        made, _r, _s = self._extract()
        pause = made[0]
        step = ns.approve(pause, self.user)
        self.assertEqual(step.status, ReportNextStep.APPROVED)
        self.assertEqual(step.reviewed_by, self.user)
        ra = RuleAction.objects.get(pk=step.rule_action_id)
        self.assertEqual((ra.rule_name, ra.action, ra.state),
                         ("golden_cross", "pause_rule", RuleAction.STATE_PROPOSED))
        self.assertIn("Four losers in a row", ra.rationale)
        self.assertIn("the weekly review", ra.rationale)
        # idempotent: a second yes changes nothing and makes no second row
        ns.approve(step, self.user)
        self.assertEqual(RuleAction.objects.count(), 1)

    def test_approving_a_watch_stars_the_instrument(self):
        from instruments.models import Instrument
        made, _r, _s = self._extract()
        watch = [s for s in made if s.kind == "watch"][0]
        with mock.patch("dashboard.consumers.push_watchlist_update") as push:
            ns.approve(watch, self.user)
        self.assertTrue(Instrument.objects.get(symbol="EURUSD").is_watchlist)
        push.assert_called_once_with("EURUSD", True)

    def test_rejecting_records_the_no(self):
        made, _r, _s = self._extract()
        step = ns.reject(made[2], self.user)
        self.assertEqual(step.status, ReportNextStep.REJECTED)
        self.assertEqual(len(ns.for_page()), 2)

    def test_the_page_lists_them_and_the_posts_are_staff_only(self):
        made, _r, _s = self._extract()
        self.client.force_login(self.user)
        resp = self.client.get("/briefing/", HTTP_HOST="127.0.0.1")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'id="next-steps"')
        self.assertContains(resp, "golden_cross")
        self.assertContains(resp, "creates a pause proposal for HQ")
        resp = self.client.post(f"/briefing/next-steps/{made[0].pk}/approve/",
                                HTTP_HOST="127.0.0.1")
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(ReportNextStep.objects.get(pk=made[0].pk).status,
                         ReportNextStep.APPROVED)
        plain = get_user_model().objects.create_user("ns_p", password="x")
        self.client.force_login(plain)
        resp = self.client.post(f"/briefing/next-steps/{made[1].pk}/reject/",
                                HTTP_HOST="127.0.0.1")
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(ReportNextStep.objects.get(pk=made[1].pk).status,
                         ReportNextStep.PENDING)

    def test_the_command(self):
        made, _r, _s = self._extract()
        out = StringIO()
        call_command("next_steps", "list", stdout=out)
        self.assertIn("3 next step(s) waiting", out.getvalue())
        self.assertIn("golden_cross", out.getvalue())
        out = StringIO()
        call_command("next_steps", "approve", str(made[0].pk), stdout=out)
        self.assertIn("pending → approved", out.getvalue())
        self.assertIn("RuleAction #", out.getvalue())
        out = StringIO()
        call_command("next_steps", "approve", str(made[0].pk), stdout=out)
        self.assertIn("already approved", out.getvalue())


class WiringTests(SimpleTestCase):

    def test_every_report_calls_the_reader(self):
        src = _read("ai_agents", "tasks.py")
        for kind, var in (("daily_briefing", "briefing_text"),
                          ("weekly_review", "review_text"),
                          ("monday_plan", "plan_text")):
            self.assertIn(f'_extract_steps("{kind}", {var})', src)
        self.assertIn('_extract_steps("eod_digest"', _read("alerts", "tasks.py"))

    def test_the_page_and_the_switch_exist(self):
        self.assertIn('_next_steps.html', _read("templates", "dashboard",
                                                "briefing.html"))
        from core.platform_control import DEFAULT_COMPONENTS
        entry = [c for c in DEFAULT_COMPONENTS if c["key"] == ns.COMPONENT_KEY]
        self.assertEqual(len(entry), 1)
        self.assertEqual(entry[0]["category"], "agent")
        self.assertLessEqual(len(entry[0]["description"]), 300)
