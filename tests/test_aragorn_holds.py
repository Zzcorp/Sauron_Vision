"""ARAGORN HONOURS WHAT WAS SET (R22, 2026-10-24).

Aragorn's step 3 took every paper-stage rule with a proven paper pair to
live_full, whatever had put it on paper: the operator's own demotion
(the HQ down button, manual_demote) was overturned at the next pass, the
loser floor and Aragorn flip-flopped a measured loser between paper and
live_full every day (restarting its probation each time), a bench a day
old was lifted, and a pair benched in a pass was put back on probation in
the same pass. The nightly sweep's paper -> live_small read neither a
hand demotion nor the floor either.

Now one hold (signals.promotion_pipeline.stage_hold) stands against both
automatic paths to real money: a rule whose newest hand move is a
demotion stays off until a hand promotion, and a measured loser on its
all-time signal record is never taken live automatically. Aragorn's
step 3 also leaves a benched pair to step 2, and a pair benched in the
same pass where it is. Every hold is said: journaled once a day,
listed in the 07:10 report and printed by `manage.py aragorn run`; an
unread hold is a hold, and is said too.

Run with:  python manage.py test tests.test_aragorn_holds
"""
from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from tests.test_aragorn import _closed, _switch
from tests.test_bar_losers import _seed_record
from tests.test_risk_limits_bind import _config

PROVEN = (1.0, -1.0, 1.5)


class _Holds(TestCase):

    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user("hold_u", password="x")
        self.staff = User.objects.create_user("hold_s", password="x",
                                              is_staff=True)
        self.cfg = _config(self.user, symbols=["BTCUSD"], mode="live")
        _switch("aragorn")

    def _proof(self, rule="vol_squeeze", days_ago=1.0):
        for i in range(21):
            _closed(self.cfg, PROVEN[i % 3], paper=True, rule=rule,
                    days_ago=days_ago)

    def _stage(self, rule="vol_squeeze"):
        from signals.models_control import RuleControl
        return RuleControl.objects.get(rule_name=rule).promotion_stage

    def _rule(self, stage, rule="vol_squeeze", **kw):
        from signals.models_control import RuleControl
        return RuleControl.objects.create(rule_name=rule,
                                          promotion_stage=stage, **kw)

    def _held(self, rule="vol_squeeze"):
        from bot_program.aragorn_models import AragornAction
        return list(AragornAction.objects.filter(kind="held",
                                                 rule_name=rule))


class AHandDemotionTests(_Holds):

    def test_a_hand_demotion_to_paper_stands_against_aragorn(self):
        from bot_program.aragorn import evaluate
        from bot_program.aragorn_models import PairVerdict
        from signals.models_control import PromotionEvent
        from signals.promotion_pipeline import demote_rule
        self._rule("live_small")
        demote_rule("vol_squeeze", user=self.staff, reason="manual_demote")
        self.assertEqual(self._stage(), "paper")
        self._proof()
        held = []
        self.assertEqual(evaluate(apply=True, held=held), [])
        self.assertEqual(self._stage(), "paper")
        self.assertFalse(PromotionEvent.objects.filter(
            rule_name="vol_squeeze", reason="auto_promote").exists())
        self.assertFalse(PairVerdict.objects.filter(
            rule_name="vol_squeeze").exists())
        self.assertEqual([(h["rule"], h["asset_class"]) for h in held],
                         [("vol_squeeze", "crypto")])
        rows = self._held()
        self.assertEqual(len(rows), 1)
        self.assertIn("demoted by hand", rows[0].detail)
        self.assertIn("live_small → paper", rows[0].detail)

    def test_a_hand_demotion_holds_through_a_later_automatic_demotion(self):
        from bot_program.aragorn import evaluate
        from signals.promotion_pipeline import _transition, demote_rule
        self._rule("live_full")
        demote_rule("vol_squeeze", user=self.staff, reason="manual_demote")
        self.assertEqual(self._stage(), "live_small")
        _transition("vol_squeeze", "paper", user=None, reason="auto_demote",
                    tell=False)
        self._proof()
        evaluate(apply=True)
        self.assertEqual(self._stage(), "paper",
                         "the newest HAND move decides, not the newest move")
        self.assertIn("live_full → live_small", self._held()[0].detail)

    def test_a_hand_promotion_after_the_demotion_lifts_the_hold(self):
        from bot_program.aragorn import evaluate
        from bot_program.aragorn_models import PairVerdict
        from signals.promotion_pipeline import demote_rule, promote_rule
        self._rule("paper")
        demote_rule("vol_squeeze", "research", user=self.staff,
                    reason="manual_demote")
        promote_rule("vol_squeeze", "paper", user=self.staff,
                     reason="manual_promote")
        self._proof()
        evaluate(apply=True)
        self.assertEqual(self._stage(), "live_full")
        self.assertEqual(PairVerdict.objects.get(
            rule_name="vol_squeeze", asset_class="crypto").state, "probation")
        self.assertEqual(self._held(), [])

    def test_a_hand_promotion_to_paper_is_no_vote_for_real_money(self):
        """Taken off real money by hand, then let back onto paper by hand
        (one HQ ↑ from research): the hand promotion is the newest hand
        move, and it is no vote for real money. Only a hand promotion TO a
        live stage brings it back."""
        from bot_program.aragorn import evaluate
        from bot_program.aragorn_models import PairVerdict
        from signals.promotion_pipeline import (demote_rule, promote_rule,
                                                stage_hold)
        self._rule("live_full")
        for _ in range(3):                        # three HQ ↓ clicks
            demote_rule("vol_squeeze", user=self.staff,
                        reason="manual_demote")
        self.assertEqual(self._stage(), "research")
        promote_rule("vol_squeeze", "paper", user=self.staff,
                     reason="manual_promote")
        self._proof(days_ago=20)
        held = []
        self.assertEqual(evaluate(apply=True, held=held), [])
        self.assertEqual(self._stage(), "paper")
        self.assertFalse(PairVerdict.objects.filter(
            rule_name="vol_squeeze").exists())
        rows = self._held()
        self.assertEqual(len(rows), 1)
        self.assertIn("taken off real money by hand (live_small → paper",
                      rows[0].detail)
        self.assertLessEqual(len(rows[0].detail), 160)
        # the HQ ↑ from paper (to live_small) is the release
        promote_rule("vol_squeeze", user=self.staff, reason="manual_promote")
        self.assertEqual(self._stage(), "live_small")
        self.assertEqual(stage_hold("vol_squeeze"), "")

    def test_a_one_rung_hand_demotion_then_back_by_hand_is_released(self):
        """A regression pin: live_full -> live_small by hand, then
        live_small -> live_full by hand, holds nothing."""
        from signals.promotion_pipeline import (demote_rule, promote_rule,
                                                stage_hold)
        self._rule("live_full")
        demote_rule("vol_squeeze", user=self.staff, reason="manual_demote")
        promote_rule("vol_squeeze", user=self.staff, reason="manual_promote")
        self.assertEqual(self._stage(), "live_full")
        self.assertEqual(stage_hold("vol_squeeze"), "")

    def test_the_words_say_what_was_decided_and_how_to_undo_it(self):
        from signals.promotion_pipeline import demote_rule, stage_hold
        self._rule("live_full")
        demote_rule("vol_squeeze", user=self.staff, reason="manual_demote")
        why = stage_hold("vol_squeeze")
        self.assertIn("demoted by hand (live_full → live_small", why)
        self.assertIn("until one by hand (HQ ↑, one rung", why)
        # a "*" bench Aragorn left survives HQ ↑: no class is promised
        self.assertIn("Aragorn's pair verdicts still bind each class", why)
        self.assertNotIn("every class", why)
        self.assertLessEqual(len(why), 160, "the sweep summary cuts at 160")
        self._rule("live_full", rule="macd_x")
        _seed_record("macd_x", 40, 10, -0.04, "TSTH")
        why = stage_hold("macd_x")
        self.assertTrue(why.startswith(
            "a measured loser on its all-time signal record: 40 graded"), why)
        self.assertNotIn("loser floor", why)
        self._rule("paper", rule="clean_rule")
        self.assertEqual(stage_hold("clean_rule"), "")


class TheLoserFloorTests(_Holds):

    def test_the_floor_is_not_overturned_by_aragorn(self):
        from bot_program.aragorn import evaluate
        from bot_program.aragorn_models import PairVerdict
        from signals.promotion_pipeline import auto_evaluate_all_rules
        self._rule("live_full")
        _seed_record("vol_squeeze", 40, 10, -0.04, "TSTA")
        PairVerdict.objects.create(
            rule_name="vol_squeeze", asset_class="crypto", state="probation",
            since=timezone.now() - timedelta(days=3))
        since = PairVerdict.objects.get(asset_class="crypto").since
        call_command("bar_losers", "--apply", stdout=StringIO())
        self.assertEqual(self._stage(), "paper")
        self._proof()
        evaluate(apply=True)
        self.assertEqual(self._stage(), "paper")
        auto_evaluate_all_rules()
        evaluate(apply=True)
        self.assertEqual(self._stage(), "paper", "no daily flip-flop")
        self.assertEqual(PairVerdict.objects.get(asset_class="crypto").since,
                         since, "the probation clock is not restarted")
        self.assertIn("measured loser", self._held()[0].detail)


class TheBenchTests(_Holds):

    def test_a_bench_set_this_pass_is_not_overturned_in_it(self):
        from bot_program.aragorn import evaluate
        from bot_program.aragorn_models import PairVerdict
        self._rule("paper")
        PairVerdict.objects.create(
            rule_name="vol_squeeze", asset_class="crypto", state="probation",
            since=timezone.now() - timedelta(days=3))
        for _ in range(3):
            _closed(self.cfg, -1.0, rule="vol_squeeze", days_ago=0.5)
        self._proof()
        self.assertEqual([m["kind"] for m in evaluate(apply=False)],
                         ["bench"])
        evaluate(apply=True)
        self.assertEqual(PairVerdict.objects.get(asset_class="crypto").state,
                         "bench")
        self.assertEqual(self._stage(), "paper")

    def test_step_three_never_lifts_a_bench(self):
        from bot_program.aragorn import evaluate, set_by_operator
        from bot_program.aragorn_models import PairVerdict
        self._rule("paper")
        set_by_operator("vol_squeeze", "crypto", "bench", by="aragorn")
        PairVerdict.objects.update(since=timezone.now() - timedelta(days=1))
        self._proof(days_ago=2)
        self.assertEqual(evaluate(apply=False), [],
                         "a day on the bench: step 2 waits, step 3 too")
        # the dwell served and fresh proof since: step 2 lifts it, and
        # only the next pass may take the rule live
        PairVerdict.objects.update(since=timezone.now() - timedelta(days=8))
        self.assertEqual([m["kind"] for m in evaluate(apply=True)],
                         ["probation"])
        self.assertEqual(self._stage(), "paper")
        self.assertEqual([m["kind"] for m in evaluate(apply=True)],
                         ["rule_live"])
        self.assertEqual(self._stage(), "live_full")

    def test_a_paused_rule_and_a_pinned_pair_still_hold(self):
        from bot_program.aragorn import evaluate, set_by_operator
        from signals.models_control import RuleControl
        self._rule("paper", status="paused")
        self._proof()
        self.assertEqual(evaluate(apply=False), [])
        RuleControl.objects.filter(rule_name="vol_squeeze").update(
            status="active")
        set_by_operator("vol_squeeze", "crypto", "live", by="gandalf",
                        pin=True)
        self.assertEqual(evaluate(apply=False), [])


class AnUnreadHoldTests(_Holds):

    def test_an_unreadable_hold_is_a_hold_and_the_pass_goes_on(self):
        from bot_program.aragorn import evaluate
        from bot_program.aragorn_models import PairVerdict
        self._rule("paper")
        self._proof()
        for _ in range(8):
            _closed(self.cfg, -0.4)                   # golden_cross, real
        held = []
        with patch("signals.promotion_pipeline.measured_loser",
                   side_effect=RuntimeError("db gone")):
            moves = evaluate(apply=True, held=held)
        self.assertEqual([(m["kind"], m["rule"]) for m in moves],
                         [("bench", "golden_cross")])
        self.assertEqual(self._stage(), "paper")
        self.assertEqual(PairVerdict.objects.get(
            rule_name="golden_cross").state, "bench")
        self.assertEqual([h["rule"] for h in held], ["vol_squeeze"])
        self.assertIn("could not be read", held[0]["reason"])
        self.assertIn("could not be read", self._held()[0].detail)


class TheHoldIsSaidTests(_Holds):

    def test_a_hold_is_journaled_once_a_day_and_a_plan_writes_nothing(self):
        from bot_program.aragorn import evaluate, report_lines
        from bot_program.aragorn_models import AragornAction
        from signals.promotion_pipeline import demote_rule
        self._rule("live_small")
        demote_rule("vol_squeeze", user=self.staff, reason="manual_demote")
        self._proof()
        held = []
        evaluate(apply=False, held=held)
        self.assertEqual(len(held), 1)
        self.assertEqual(self._held(), [], "a plan writes nothing")
        evaluate(apply=True)
        evaluate(apply=True)
        self.assertEqual(len(self._held()), 1, "once a day")
        # never twice: with one older care row (so "Last 24h:" has room),
        # the hold is not a Last 24h row
        AragornAction.objects.create(kind="care_close", rule_name="x",
                                     detail="older care row",
                                     at=timezone.now() - timedelta(hours=1))
        first = report_lines()
        tail = first[first.index("Last 24h:"):]
        self.assertFalse(any(" held " in ln for ln in tail),
                         "never twice: the hold is not a Last 24h row")
        # a busy day of care rows does not push the hold out of the report
        for i in range(20):
            AragornAction.objects.create(kind="care_close", rule_name="x",
                                         detail=f"close {i}")
        lines = report_lines()
        self.assertIn("Held off real money:", lines)
        at = lines.index("Held off real money:")
        self.assertTrue(lines[at + 1].startswith("  vol_squeeze/crypto: "
                                                 "demoted by hand"))
        self.assertLess(at, lines.index("Last 24h:"))
        self.assertIn("Last 24h:", lines)

    def test_a_standing_hold_is_said_every_morning_whatever_the_beat(self):
        """The pass runs every four hours from the beat, and the task's
        own start time is `now`: a pass that starts a few hundred
        milliseconds earlier than yesterday's still journals the hold, and
        the 07:10 report lists it."""
        from bot_program.aragorn import evaluate, report_lines
        from signals.promotion_pipeline import demote_rule
        self._rule("live_small")
        demote_rule("vol_squeeze", user=self.staff, reason="manual_demote")
        self._proof(days_ago=3)
        d1 = (timezone.now() + timedelta(days=1)).replace(
            hour=4, minute=20, second=0, microsecond=500000)
        evaluate(apply=True, now=d1)
        evaluate(apply=True, now=d1 + timedelta(hours=4))
        self.assertEqual(len(self._held()), 1, "once a day")
        d2 = d1 + timedelta(hours=24, seconds=-0.4)
        evaluate(apply=True, now=d2)
        self.assertEqual(len(self._held()), 2, "the same slot, next day")
        lines = report_lines(now=d2 + timedelta(hours=2, minutes=50))
        self.assertIn("Held off real money:", lines)
        self.assertEqual(self._stage(), "paper")

    def test_a_released_hold_is_not_listed(self):
        """The block is the hold as it stands, not a replay of the
        journal: after HQ ↑ the rule is not listed, and a re-read that
        fails keeps the journal's line."""
        from bot_program.aragorn import evaluate, report_lines
        from signals.promotion_pipeline import demote_rule, promote_rule
        self._rule("live_small")
        demote_rule("vol_squeeze", user=self.staff, reason="manual_demote")
        self._proof()
        evaluate(apply=True)
        self.assertIn("Held off real money:", report_lines())
        with patch("signals.promotion_pipeline.stage_hold",
                   side_effect=RuntimeError("db gone")):
            lines = report_lines()
        self.assertIn("Held off real money:", lines)
        promote_rule("vol_squeeze", user=self.staff, reason="manual_promote")
        self.assertEqual(self._stage(), "live_small")
        self.assertNotIn("Held off real money:", report_lines())

    def test_the_command_names_the_holds(self):
        from signals.promotion_pipeline import demote_rule
        self._rule("live_small")
        demote_rule("vol_squeeze", user=self.staff, reason="manual_demote")
        self._proof()
        out = StringIO()
        call_command("aragorn", "run", stdout=out)
        text = out.getvalue()
        self.assertIn("Nothing to move.", text)
        self.assertIn("held       vol_squeeze/crypto · demoted by hand", text)


class TheSweepHoldsTests(_Holds):
    """M1: the nightly sweep's paper -> live_small read neither a hand
    demotion nor the floor; it reads the same hold now, and a held rule
    is listed among the sweep's held back."""

    def _sweep(self):
        from signals.promotion_pipeline import auto_evaluate_all_rules
        with patch("signals.promotion_pipeline.is_due_for_demotion",
                   return_value=None), \
                patch("signals.promotion_pipeline.is_eligible_for_promotion",
                      return_value="live_small"), \
                patch("signals.promotion_evidence.gate_promotion",
                      return_value=(True, "out-of-sample edge")):
            return auto_evaluate_all_rules()

    def test_the_sweep_holds_a_hand_demoted_rule(self):
        from signals.promotion_pipeline import demote_rule
        self._rule("live_small")
        demote_rule("vol_squeeze", user=self.staff, reason="manual_demote")
        out = self._sweep()
        self.assertEqual(out["promoted"], [])
        self.assertEqual(self._stage(), "paper")
        self.assertEqual([(b["rule_name"], b["target"]) for b in
                          out["blocked"]], [("vol_squeeze", "live_small")])
        self.assertIn("demoted by hand", out["blocked"][0]["reason"])
        # the sweep summary and the 07:00 digest name no wrong cause
        from alerts.scheduled_digests import (digest_lines,
                                              generate_morning_digest)
        from signals.promotion_pipeline import ladder_sweep_words
        body = ladder_sweep_words(out)[1]
        self.assertIn("Held back:", body)
        self.assertIn("demoted by hand", body)
        text = "\n".join(str(x) for x in
                         digest_lines(generate_morning_digest(user=None)))
        self.assertIn("Held back: 1", text)
        self.assertIn("a hand demotion", text)
        self.assertNotIn("by the evidence gate", text)

    def test_the_sweep_holds_a_rule_its_owner_let_back_onto_paper_only(self):
        from signals.promotion_pipeline import demote_rule, promote_rule
        self._rule("live_small")
        demote_rule("vol_squeeze", user=self.staff, reason="manual_demote")
        demote_rule("vol_squeeze", user=self.staff, reason="manual_demote")
        promote_rule("vol_squeeze", "paper", user=self.staff,
                     reason="manual_promote")
        out = self._sweep()
        self.assertEqual(out["promoted"], [])
        self.assertEqual(self._stage(), "paper")
        self.assertIn("taken off real money by hand",
                      out["blocked"][0]["reason"])

    def test_the_sweep_holds_a_measured_loser(self):
        self._rule("paper")
        _seed_record("vol_squeeze", 40, 10, -0.04, "TSTB")
        out = self._sweep()
        self.assertEqual(out["promoted"], [])
        self.assertEqual(self._stage(), "paper")
        self.assertIn("measured loser", out["blocked"][0]["reason"])

    def test_the_sweep_still_promotes_a_clean_rule_and_paper_is_not_held(self):
        from signals.promotion_pipeline import (auto_evaluate_all_rules,
                                                demote_rule)
        self._rule("paper")
        out = self._sweep()
        self.assertEqual(out["promoted"], ["vol_squeeze"])
        self.assertEqual(self._stage(), "live_small")
        # research -> paper is never real money: a hand demotion to
        # research does not stop the ladder's paper step
        self._rule("live_small", rule="rsch")
        demote_rule("rsch", "research", user=self.staff,
                    reason="manual_demote")
        with patch("signals.promotion_pipeline.is_due_for_demotion",
                   return_value=None), \
                patch("signals.promotion_pipeline.is_eligible_for_promotion",
                      side_effect=lambda r: "paper" if r == "rsch" else None):
            out = auto_evaluate_all_rules()
        self.assertEqual(out["promoted"], ["rsch"])

    def test_an_unreadable_hold_holds_the_sweep(self):
        self._rule("paper")
        with patch("signals.promotion_pipeline.stage_hold",
                   side_effect=RuntimeError("db gone")):
            out = self._sweep()
        self.assertEqual(out["promoted"], [])
        self.assertIn("could not be read", out["blocked"][0]["reason"])


class ThePromotionsPageSaysItTests(_Holds):
    """/promotions/ is where the HQ ↑ that releases a hold lives: its
    Status cell says the hold, not "eligible to promote"."""

    def _page(self):
        from django.test import Client
        admin = get_user_model().objects.create_superuser(
            "hold_a", "a@x.invalid", "x")
        c = Client()
        c.force_login(admin)
        with patch("signals.promotion_pipeline.is_eligible_for_promotion",
                   return_value="live_small"), \
                patch("signals.promotion_pipeline.is_due_for_demotion",
                      return_value=None), \
                patch("signals.promotion_evidence.gate_promotion",
                      return_value=(True, "walk-forward gate passed: ok")):
            html = c.get("/promotions/").content.decode()
        i = html.find('data-label="Status"')
        return html[i:i + 600]

    def test_a_held_rule_reads_held_with_its_reason(self):
        from signals.promotion_pipeline import demote_rule
        self._rule("live_small")
        demote_rule("vol_squeeze", user=self.staff, reason="manual_demote")
        cell = self._page()
        self.assertIn("held — demoted by hand (live_small → paper", cell)
        self.assertNotIn("eligible to promote", cell)

    def test_an_unread_hold_reads_held(self):
        self._rule("paper")
        with patch("signals.promotion_pipeline.stage_hold",
                   side_effect=RuntimeError("db gone")):
            cell = self._page()
        self.assertIn("could not be read", cell)

    def test_a_clean_rule_still_reads_eligible(self):
        """A regression pin."""
        self._rule("paper")
        cell = self._page()
        self.assertIn("eligible to promote", cell)
        self.assertIn("walk-forward gate passed: ok", cell)


class TheBookSaysItTests(TestCase):

    def test_the_book_says_a_hand_demotion_stands(self):
        from core import book_content as book
        chapter = [c for c in book.CHAPTERS if c["id"] == "safeguards"][0]
        text = [i for i in chapter["items"] if i["title"] == "Aragorn"][0][
            "text"]
        self.assertIn("A rule its owner took off real money by hand stays "
                      "off until its owner brings it back by hand", text)
        self.assertIn("never brings back a rule the loser floor would bar",
                      text)
