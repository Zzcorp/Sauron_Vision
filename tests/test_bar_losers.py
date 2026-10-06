"""BAR THE MEASURED LOSERS (2026-10-05): a rule that loses, measured, does
not keep the live venue.

The nightly sweep compared a live rule's recent window with the baseline
it was promoted on and returned nothing when that baseline was None or at
or under zero — what a bulk promotion leaves behind — so a measured loser
kept real money until a human acted. THE FLOOR (promotion_pipeline
.measured_loser, is_due_for_demotion): LOSER_MIN_N graded signals all time
and an expectancy at or under zero, or a hit rate under LOSER_HIT_MAX with
an expectancy under LOSER_THIN_EDGE_R (a thin edge under a low hit rate),
sends a live rule to PAPER at once, whatever its baseline; the operator's
own promotion stands for MANUAL_DWELL_DAYS. `manage.py bar_losers` reads
the table and, with --apply, applies the same floor by hand.

EXPECTANCY-LED (2026-10-06): the first floor barred on a hit rate under
35% alone and flagged bollinger_squeeze_breakout (43 graded, hit 33%,
+0.26R, PROVEN by the proving ground) — the one rule with a measured edge.
A low hit rate with a large payoff is a breakout's normal shape; the six
server rows of 2026-10-06 are pinned below as a table.

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
        self.assertEqual(pp.LOSER_THIN_EDGE_R, 0.10)

    def test_a_measured_loser_is_named_with_its_numbers(self):
        from signals.promotion_pipeline import measured_loser
        # under the floor's n: unmeasured, whatever the record
        _seed_signals("bl_few", [-1.0] * 19)
        self.assertEqual(measured_loser("bl_few"), "")
        # 24 graded, 6 hits (25%) at -0.25R: a loser, and the arm that
        # fires is the expectancy (it is checked first)
        _seed_signals("bl_hit", [2.0] * 6 + [-1.0] * 18)
        why = measured_loser("bl_hit")
        self.assertEqual(why, "24 graded signals all time: hit 25%, "
                              "expectancy -0.25R — expectancy at or under "
                              "zero")
        # 40% hits but the losers are bigger: a loser by the expectancy
        _seed_signals("bl_exp", [0.5] * 8 + [-1.0] * 12)
        self.assertIn("hit 40%, expectancy -0.40R — expectancy at or under "
                      "zero", measured_loser("bl_exp"))
        # healthy: 45% hits at +2R
        _seed_signals("bl_ok", [2.0] * 9 + [-1.0] * 11)
        self.assertEqual(measured_loser("bl_ok"), "")
        self.assertEqual(measured_loser("bl_none"), "")

    def test_a_low_hit_rate_alone_is_not_a_loser(self):
        from signals.promotion_pipeline import measured_loser
        # 20 graded, 5 hits (25%) at +4R: expectancy +0.25R — a breakout's
        # shape, healthy (the old floor barred this on the hit rate)
        _seed_signals("bl_brk", [4.0] * 5 + [-1.0] * 15)
        self.assertEqual(measured_loser("bl_brk"), "")
        # the same hit rate on a thin edge (+0.05R): the second arm fires
        _seed_signals("bl_thin", [3.2] * 5 + [-1.0] * 15)
        self.assertEqual(measured_loser("bl_thin"),
                         "20 graded signals all time: hit 25%, expectancy "
                         "+0.05R — a thin edge under a low hit rate "
                         "(expectancy under +0.10R, hit under 35%)")
        # a thin edge at a high hit rate is not barred by the floor
        _seed_signals("bl_hi", [1.1] * 10 + [-1.0] * 10)
        self.assertEqual(measured_loser("bl_hi"), "")

    def test_the_floor_edges_are_pinned(self):
        """Each comparison at its edge, on values exact in binary: a
        50%-hit rule at 0.00R is barred by `exp <= 0` alone."""
        from signals.promotion_pipeline import measured_loser
        _seed_signals("bl_zero", [1.0] * 10 + [-1.0] * 10)
        self.assertEqual(measured_loser("bl_zero"),
                         "20 graded signals all time: hit 50%, expectancy "
                         "+0.00R — expectancy at or under zero")
        # exactly 35% hits (7 of 20) on a thin +0.05R: not a low hit rate
        _seed_signals("bl_h35", [2.0] * 7 + [-1.0] * 13)
        self.assertEqual(measured_loser("bl_h35"), "")
        # exactly +0.10R (2.0 over 20) at 20% hits: not a thin edge
        _seed_signals("bl_e10", [4.5] * 4 + [-1.0] * 16)
        self.assertEqual(measured_loser("bl_e10"), "")

    def test_a_value_under_a_floor_never_prints_as_the_floor(self):
        """17 hits of 49 (34.69%) at +0.0963R: barred, and said so in
        numbers that agree with the reason."""
        from signals.promotion_pipeline import loser_numbers, measured_loser
        _seed_signals("bl_round", [2.16] * 17 + [-1.0] * 32)
        self.assertEqual(measured_loser("bl_round"),
                         "49 graded signals all time: hit 34%, expectancy "
                         "+0.09R — a thin edge under a low hit rate "
                         "(expectancy under +0.10R, hit under 35%)")
        self.assertEqual(loser_numbers(0.3469, 0.0951), ("34%", "+0.09R"))
        self.assertEqual(loser_numbers(0.35, 0.10), ("35%", "+0.10R"))
        self.assertEqual(loser_numbers(0.5, -0.004), ("50%", "-0.00R"))

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
        self.assertIn("floor: 20 graded signals and expectancy <= 0R, or "
                      "hit < 35% with expectancy < 0.10R", text)
        self.assertNotIn("hit < 35% or expectancy", text)
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


def _seed_record(rule, n, hits, exp, symbol):
    """`n` graded signals for `rule`: `hits` winners and the rest stopped
    out at -1R, the winners sized so the all-time expectancy is `exp`."""
    from decimal import Decimal
    from instruments.models import Instrument
    from signals.models import Signal
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": "stock"})
    losses = n - hits
    win = (exp * n + losses) / hits
    now = timezone.now()
    Signal.objects.bulk_create([
        Signal(instrument=inst, signal_type="composite", direction="bullish",
               urgency="medium", title="t", description="t", rule_name=rule,
               score=0.7, sub_scores={}, price_at_signal=Decimal("100"),
               suggested_entry=Decimal("100"), suggested_stop=Decimal("95"),
               suggested_target=Decimal("110"), risk_reward_ratio=2.0,
               is_active=False,
               outcome="hit_target" if i < hits else "stopped_out",
               realized_r=win if i < hits else -1.0,
               expired_at=now - timedelta(days=20 + i))
        for i in range(n)])


# The live server, 2026-10-06 (`manage.py bar_losers`): rule, n, hits,
# expectancy, the printed hit rate, and the verdict the floor must give.
SERVER_ROWS = [
    ("bollinger_squeeze_breakout", 43, 14, 0.26, "33%", None),
    ("golden_cross", 31, 4, 0.01, "13%", "thin edge"),
    ("macd_bullish_crossover", 128, 31, -0.04, "24%", "at or under zero"),
    ("rsi_bull_divergence", 200, 52, -0.03, "26%", "at or under zero"),
    ("starter_stock_momentum", 21, 3, -0.57, "14%", "at or under zero"),
    ("starter_forex_breakout", 17, 4, -0.30, "24%", "unmeasured"),
]


class TheServerRowsTests(TestCase):
    """The six rows `bar_losers` printed on the live server on 2026-10-06:
    the one rule with a measured edge stays live, the rest come out as the
    expectancy-led floor reads them."""

    def setUp(self):
        for i, (rule, n, hits, exp, _hit, _v) in enumerate(SERVER_ROWS):
            _set_stage(rule, "live_full", baseline=None)
            _seed_record(rule, n, hits, exp, f"SRV{i}")

    def test_the_table(self):
        from signals.promotion_pipeline import _stats_since, measured_loser
        for rule, n, _hits, exp, hit, verdict in SERVER_ROWS:
            with self.subTest(rule=rule):
                s = _stats_since(rule)
                self.assertEqual(s["n"], n)
                self.assertEqual(f"{s['hit_rate']:.0%}", hit)
                self.assertAlmostEqual(s["expectancy"], exp, places=6)
                why = measured_loser(rule)
                if verdict is None or verdict == "unmeasured":
                    self.assertEqual(why, "", f"{rule} must not be a loser")
                else:
                    self.assertTrue(why.startswith(f"{n} graded signals all "
                                                   f"time: hit {hit}, "
                                                   f"expectancy {exp:+.2f}R"),
                                    why)
                    self.assertIn(verdict, why)

    def test_the_breakout_keeps_the_live_venue_when_the_dwell_ends(self):
        from signals.promotion_pipeline import is_due_for_demotion
        _hand_promoted("bollinger_squeeze_breakout", 8)
        self.assertIsNone(is_due_for_demotion("bollinger_squeeze_breakout"))
        self.assertEqual(is_due_for_demotion("golden_cross"), "paper")

    def test_the_command_reads_the_rows_and_bars_the_four(self):
        from signals.models import RuleControl
        _hand_promoted("bollinger_squeeze_breakout", 2)
        out = StringIO()
        call_command("bar_losers", stdout=out)
        lines = {l.split()[0]: l for l in out.getvalue().splitlines()
                 if l.startswith("  ") and l.split()[0] in
                 {r[0] for r in SERVER_ROWS}}
        self.assertTrue(lines["bollinger_squeeze_breakout"].rstrip()
                        .endswith("ok"), "healthy, not a loser left alone")
        for rule in ("golden_cross", "macd_bullish_crossover",
                     "rsi_bull_divergence", "starter_stock_momentum"):
            self.assertTrue(lines[rule].rstrip().endswith("LOSER"), rule)
        self.assertIn("unmeasured (n 17 < 20)",
                      lines["starter_forex_breakout"])
        out = StringIO()
        call_command("bar_losers", "--apply", stdout=out)
        self.assertIn("Barred 4 rule(s) to paper.", out.getvalue())
        self.assertIn("a thin edge under a low hit rate", out.getvalue())
        stages = dict(RuleControl.objects.filter(
            rule_name__in=[r[0] for r in SERVER_ROWS])
            .values_list("rule_name", "promotion_stage"))
        self.assertEqual(stages["bollinger_squeeze_breakout"], "live_full")
        self.assertEqual(stages["starter_forex_breakout"], "live_full")
        self.assertEqual({r for r, s in stages.items() if s == "paper"},
                         {"golden_cross", "macd_bullish_crossover",
                          "rsi_bull_divergence", "starter_stock_momentum"})


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
