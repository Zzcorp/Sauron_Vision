"""BAR THE MEASURED LOSERS (2026-10-05): a rule that loses, measured, does
not keep the live venue.

The nightly sweep compared a live rule's recent window with the baseline
it was promoted on and returned nothing when that baseline was None or at
or under zero — what a bulk promotion leaves behind — so a measured loser
kept real money until a human acted. THE FLOOR (promotion_pipeline
.measured_loser, is_due_for_demotion): LOSER_MIN_N graded signals all time
and a hit rate under LOSER_HIT_MAX or an expectancy at or under zero sends
a live rule to PAPER at once, whatever its baseline; the operator's own
promotion stands for MANUAL_DWELL_DAYS. `manage.py bar_losers` reads the
table and, with --apply, applies the same floor by hand.

Run with:  python manage.py test tests.test_bar_losers
"""
from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from tests.test_promotion_pipeline import _seed_signals, _set_stage


def _hand_promoted(rule, days_ago):
    from signals.models import PromotionEvent
    ev = PromotionEvent.objects.create(rule_name=rule, from_stage="paper",
                                       to_stage="live_full",
                                       reason="manual_promote")
    PromotionEvent.objects.filter(pk=ev.pk).update(
        created_at=timezone.now() - timedelta(days=days_ago))
    return ev


class TheFloorTests(TestCase):

    def test_the_constants(self):
        from signals import promotion_pipeline as pp
        self.assertEqual((pp.LOSER_MIN_N, pp.LOSER_HIT_MAX, pp.MANUAL_DWELL_DAYS),
                         (20, 0.35, 7))

    def test_a_measured_loser_is_named_with_its_numbers(self):
        from signals.promotion_pipeline import measured_loser
        # under the floor's n: unmeasured, whatever the record
        _seed_signals("bl_few", [-1.0] * 19)
        self.assertEqual(measured_loser("bl_few"), "")
        # 24 graded, 6 hits (25%): a loser by the hit rate
        _seed_signals("bl_hit", [2.0] * 6 + [-1.0] * 18)
        why = measured_loser("bl_hit")
        self.assertEqual(why, "24 graded signals all time: hit 25% (floor "
                              "35%), expectancy -0.25R")
        # 40% hits but the losers are bigger: a loser by the expectancy
        _seed_signals("bl_exp", [0.5] * 8 + [-1.0] * 12)
        self.assertIn("hit 40% (floor 35%), expectancy -0.40R",
                      measured_loser("bl_exp"))
        # healthy: 45% hits at +2R
        _seed_signals("bl_ok", [2.0] * 9 + [-1.0] * 11)
        self.assertEqual(measured_loser("bl_ok"), "")
        self.assertEqual(measured_loser("bl_none"), "")

    def test_the_floor_sends_a_live_loser_to_paper_whatever_its_baseline(self):
        from signals.promotion_pipeline import is_due_for_demotion
        _set_stage("bl_f1", "live_full", baseline=None)
        _seed_signals("bl_f1", [2.0] * 5 + [-1.0] * 20, days_ago_start=20)
        self.assertEqual(is_due_for_demotion("bl_f1"), "paper",
                         "straight to paper, not one rung")
        _set_stage("bl_f2", "live_small", baseline=1.5)
        _seed_signals("bl_f2", [2.0] * 5 + [-1.0] * 20, days_ago_start=20)
        self.assertEqual(is_due_for_demotion("bl_f2"), "paper",
                         "the floor wins over a positive baseline")
        # a healthy rule with no baseline: untouched, as before
        _set_stage("bl_f3", "live_full", baseline=None)
        _seed_signals("bl_f3", [2.0] * 12 + [-1.0] * 10, days_ago_start=20)
        self.assertIsNone(is_due_for_demotion("bl_f3"))
        # a paper-stage loser keeps the paper rule (30-day negative window)
        _set_stage("bl_f4", "paper")
        _seed_signals("bl_f4", [-1.0] * 25, days_ago_start=40)
        self.assertIsNone(is_due_for_demotion("bl_f4"),
                          "old losses: the paper window is 30 days, and the "
                          "floor is a live-stage rule")

    def test_the_operators_own_promotion_stands_for_the_dwell(self):
        from signals.promotion_pipeline import (hand_promoted_recently,
                                                is_due_for_demotion)
        _set_stage("bl_d1", "live_full", baseline=None)
        _seed_signals("bl_d1", [-1.0] * 22, days_ago_start=30)
        _hand_promoted("bl_d1", 3)
        self.assertTrue(hand_promoted_recently("bl_d1"))
        self.assertIsNone(is_due_for_demotion("bl_d1"))
        _set_stage("bl_d2", "live_full", baseline=None)
        _seed_signals("bl_d2", [-1.0] * 22, days_ago_start=30)
        _hand_promoted("bl_d2", 8)
        self.assertFalse(hand_promoted_recently("bl_d2"))
        self.assertEqual(is_due_for_demotion("bl_d2"), "paper")

    def test_the_sweep_bars_the_loser_in_one_pass_and_says_why(self):
        from signals.models import PromotionEvent, RuleControl
        from signals.promotion_pipeline import auto_evaluate_all_rules
        _set_stage("bl_s1", "live_full", baseline=None)
        _seed_signals("bl_s1", [-1.0] * 22, days_ago_start=30)
        _set_stage("bl_s2", "live_full", baseline=None)
        _seed_signals("bl_s2", [2.0] * 12 + [-1.0] * 10, days_ago_start=30)
        out = auto_evaluate_all_rules()
        self.assertEqual(out["demoted"], ["bl_s1"])
        self.assertEqual(RuleControl.objects.get(rule_name="bl_s1")
                         .promotion_stage, "paper")
        self.assertEqual(RuleControl.objects.get(rule_name="bl_s2")
                         .promotion_stage, "live_full")
        ev = PromotionEvent.objects.get(rule_name="bl_s1")
        self.assertEqual((ev.from_stage, ev.to_stage, ev.reason),
                         ("live_full", "paper", "auto_demote"))
        self.assertIn("measured loser: 22 graded signals all time", ev.notes)


class TheCommandTests(TestCase):

    def _run(self, *args):
        out = StringIO()
        call_command("bar_losers", *args, stdout=out)
        return out.getvalue()

    def test_the_table_and_the_dry_run(self):
        from signals.models import PromotionEvent
        _set_stage("bc_loser", "live_full", baseline=None)
        _seed_signals("bc_loser", [2.0] * 5 + [-1.0] * 20, days_ago_start=20)
        _set_stage("bc_ok", "live_small", baseline=1.0)
        _seed_signals("bc_ok", [2.0] * 12 + [-1.0] * 10)
        _set_stage("bc_few", "live_full")
        _seed_signals("bc_few", [-1.0] * 5)
        _set_stage("bc_hand", "live_full")
        _seed_signals("bc_hand", [-1.0] * 22, days_ago_start=30)
        _hand_promoted("bc_hand", 2)
        _set_stage("bc_paper", "paper")
        _seed_signals("bc_paper", [-1.0] * 22)
        text = self._run()
        self.assertIn("4 rule(s) at a live stage", text)
        self.assertIn("floor: 20 graded signals and hit < 35% or expectancy "
                      "<= 0R", text)
        lines = {l.split()[0]: l for l in text.splitlines() if l.startswith("  bc_")}
        self.assertIn("LOSER", lines["bc_loser"])
        self.assertIn("hit  20%", lines["bc_loser"])
        self.assertTrue(lines["bc_ok"].rstrip().endswith("ok"), lines["bc_ok"])
        self.assertIn("unmeasured (n 5 < 20)", lines["bc_few"])
        self.assertIn("promoted by hand within 7 days — left alone",
                      lines["bc_hand"])
        self.assertNotIn("bc_paper", text)
        self.assertIn("Dry run — nothing written", text)
        self.assertEqual(PromotionEvent.objects.filter(
            reason="auto_demote").count(), 0)

    def test_apply_bars_the_loser_and_leaves_the_rest(self):
        from signals.models import PromotionEvent, RuleControl
        _set_stage("ba_loser", "live_full", baseline=None)
        _seed_signals("ba_loser", [-1.0] * 22, days_ago_start=30)
        _set_stage("ba_ok", "live_full", baseline=None)
        _seed_signals("ba_ok", [2.0] * 12 + [-1.0] * 10)
        _set_stage("ba_hand", "live_full")
        _seed_signals("ba_hand", [-1.0] * 22, days_ago_start=30)
        _hand_promoted("ba_hand", 2)
        text = self._run("--apply")
        self.assertIn("-> barred to paper", text)
        self.assertIn("Barred 1 rule(s) to paper.", text)
        stages = dict(RuleControl.objects.filter(
            rule_name__startswith="ba_").values_list("rule_name",
                                                     "promotion_stage"))
        self.assertEqual(stages, {"ba_loser": "paper", "ba_ok": "live_full",
                                  "ba_hand": "live_full"})
        ev = PromotionEvent.objects.get(rule_name="ba_loser",
                                        reason="auto_demote")
        self.assertEqual(ev.to_stage, "paper")
        self.assertIn("bar_losers: measured loser: 22 graded signals",
                      ev.notes)
        # a second apply finds nothing to bar
        self.assertIn("Barred 0 rule(s) to paper.", self._run("--apply"))

    def test_no_live_rule_says_so(self):
        self.assertIn("no rule is at a live stage", self._run())


class TheWordsTests(SimpleTestCase):

    def test_demote_rule_carries_the_note(self):
        import inspect
        from signals.promotion_pipeline import demote_rule
        src = inspect.getsource(demote_rule)
        self.assertIn('notes: str = ""', src)
        self.assertIn("notes=notes", src)

    def test_the_command_names_the_next_cut(self):
        from signals.management.commands import bar_losers
        self.assertIn("its signals still vote", bar_losers.__doc__)
