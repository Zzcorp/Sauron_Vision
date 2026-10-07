"""THE PROVENANCE, BATCHED (2026-10-07, the review of SIZE BY PROOF).

provenance_notes read promotion_provenance once per live rule: a
PromotionEvent, one to three graded-signal reads and a ProvingVerdict, so
the evidence ledger (and every caller of evidence.rule_rows: the signal
engine's scan, /signals/, the brain's horizon, the strategy generator) and
/strategies/ grew by about four queries per live rule — 7 queries became
151 on the ladder for 36 live rules. Now:

  - evidence.rule_rows reads the provenance only when asked
    (with_provenance=True, /evidence/ alone shows it);
  - provenance_notes costs a fixed number of queries whatever the rule
    count: one PromotionEvent read, one graded read (none when the caller
    hands its own all-time stats) and one ProvingVerdict read
    (proof.proven_cases_for);
  - the words are the per-rule read's own, case for case.

Run with:  python manage.py test tests.test_provenance_batch
"""
from datetime import timedelta

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from tests.test_bar_losers import _hand_promoted, _seed_record
from tests.test_promotion_pipeline import _seed_signals, _set_stage
from tests.test_size_by_proof import _verdict


def _event(rule, reason, *, to_stage="live_full", days_ago=1, n=0,
           exp=None):
    from signals.models import PromotionEvent
    ev = PromotionEvent.objects.create(
        rule_name=rule, from_stage="paper", to_stage=to_stage, reason=reason,
        n_at_transition=n, expectancy_at_transition=exp)
    PromotionEvent.objects.filter(pk=ev.pk).update(
        created_at=timezone.now() - timedelta(days=days_ago))
    return ev


def _seed_every_case():
    """{rule: the note the per-rule read gives} over every branch."""
    expected = {}

    def live(rule, note, stage="live_full"):
        _set_stage(rule, stage)
        expected[rule] = note

    live("pb_hand", "by hand, unproven")
    _hand_promoted("pb_hand", 2)
    live("pb_hand_rec", "by hand, proven since")
    _hand_promoted("pb_hand_rec", 2)
    _seed_record("pb_hand_rec", 43, 14, 0.26, "PBREC")
    live("pb_hand_pg", "by hand, proven since")
    _hand_promoted("pb_hand_pg", 2)
    _verdict("pb_hand_pg", "etf", "long", "proven", age_h=5)
    live("pb_hand_pg_failed", "by hand, unproven")
    _hand_promoted("pb_hand_pg_failed", 2)
    _verdict("pb_hand_pg_failed", "stock", "long", "proven", age_h=10)
    _verdict("pb_hand_pg_failed", "stock", "long", "failed", age_h=1,
             exp=-0.1, oe=-0.1)
    live("pb_hand_sub", "by hand, unproven")
    _hand_promoted("pb_hand_sub", 2)
    _verdict("pb_hand_sub", "forex", "long", "failed", age_h=10, exp=-0.1,
             oe=-0.1)
    _verdict("pb_hand_sub", "forex", "long", "proven", run="rulesub-x",
             age_h=1)
    live("pb_then", "")
    _event("pb_then", "manual_promote", n=25, exp=0.30)
    live("pb_auto", "")
    _event("pb_auto", "auto_promote")
    live("pb_none", "no promotion recorded, unproven")
    live("pb_none_rec", "")
    _seed_record("pb_none_rec", 30, 12, 0.30, "PBNREC")
    live("pb_demo", "by hand, unproven", stage="live_small")
    _hand_promoted("pb_demo", 5)
    _event("pb_demo", "auto_demote", to_stage="live_small", days_ago=1)
    live("pb_newer_auto", "")
    _hand_promoted("pb_newer_auto", 9)
    _event("pb_newer_auto", "auto_promote", days_ago=1)
    live("pb_loser", "by hand, unproven")
    _hand_promoted("pb_loser", 2)
    _seed_signals("pb_loser", [-1.0] * 22)
    live("pb_thin", "by hand, unproven")
    _hand_promoted("pb_thin", 2)
    _seed_record("pb_thin", 25, 10, 0.05, "PBTHIN")
    live("pb_few", "by hand, unproven")
    _hand_promoted("pb_few", 2)
    _seed_signals("pb_few", [2.0] * 19)
    for rule, stage in (("pb_paper", "paper"), ("pb_research", "research")):
        _set_stage(rule, stage)
        _hand_promoted(rule, 2)
        expected[rule] = ""
    return expected


def _live_rules(n, prefix):
    """`n` live_full rules promoted by hand without proof, each with two
    graded signals and a proving-ground row, half of them PROVEN."""
    from tests.test_strategies_page import _closed_signals, _rule
    for i in range(n):
        name = f"{prefix}_{i}"
        _rule(name, "live_full")
        _hand_promoted(name, 2)
        _closed_signals(name, [1.0, -1.0])
        _verdict(name, "stock", "long", "proven" if i % 2 else "promising")


class TheSameWordsTests(TestCase):

    def setUp(self):
        from signals.models import RuleControl
        self.expected = _seed_every_case()
        self.ctrls = {c.rule_name: c for c in RuleControl.objects.all()}
        self.names = sorted(self.expected) + ["pb_ghost"]

    def _per_rule(self, controls=True):
        from signals.promotion_pipeline import promotion_provenance
        out = {}
        for name in self.names:
            if controls:
                if name not in self.ctrls:
                    continue
                out[name] = promotion_provenance(
                    name, ctrl=self.ctrls[name])["note"]
            else:
                out[name] = promotion_provenance(name)["note"]
        return out

    def test_the_batch_says_what_the_per_rule_read_says(self):
        from signals.promotion_pipeline import provenance_notes
        per_rule = self._per_rule()
        self.assertEqual(per_rule, self.expected)
        self.assertEqual(provenance_notes(self.names, controls=self.ctrls),
                         per_rule)
        # with no controls handed in: one read of them, and a name with no
        # control row reads "" as the per-rule read does
        loose = self._per_rule(controls=False)
        self.assertEqual(loose["pb_ghost"], "")
        self.assertEqual(provenance_notes(self.names), loose)

    def test_the_callers_stats_say_the_same(self):
        from bot_program import evidence
        from dashboard.views import _promotion_ladder
        rows = {r["rule"]: r
                for r in evidence.rule_rows(with_provenance=True)}
        for name, note in self.expected.items():
            with self.subTest(rule=name):
                self.assertEqual(rows[name]["stage_note"], note)
        cards = {c["rule"]: c for g in _promotion_ladder()["stage_groups"]
                 for c in g["cards"]}
        for name, note in self.expected.items():
            with self.subTest(rule=name):
                self.assertEqual(cards[name]["stage_note"], note)

    def test_an_unread_part_reads_as_the_per_rule_read_would(self):
        from backtester.models_proving import ProvingVerdict
        from signals import promotion_pipeline as pp
        from unittest import mock
        # unread verdicts prove nothing; the graded record still does
        with mock.patch.object(ProvingVerdict.objects, "filter",
                               side_effect=RuntimeError("db gone")), \
                self.assertLogs("backtester.proving.proof", "WARNING"):
            notes = pp.provenance_notes(self.names, controls=self.ctrls)
        self.assertEqual(notes["pb_hand_pg"], "by hand, unproven")
        self.assertEqual(notes["pb_hand_rec"], "by hand, proven since")
        # an unread graded record is no proof; the verdicts still are
        with mock.patch.object(pp, "_stats_by_rule",
                               side_effect=RuntimeError("db gone")), \
                self.assertLogs("signals.promotion_pipeline", "WARNING"):
            notes = pp.provenance_notes(self.names, controls=self.ctrls)
        self.assertEqual(notes["pb_hand_rec"], "by hand, unproven")
        self.assertEqual(notes["pb_hand_pg"], "by hand, proven since")
        self.assertEqual(notes["pb_none_rec"],
                         "no promotion recorded, unproven")


class TheFixedBudgetTests(TestCase):
    """evidence.rule_rows: 3 queries (graded, fills, controls); 5 with the
    provenance (its graded record is the one read above, + the promotion
    events and the proving ground's verdicts) — at 3 live rules and at 9
    alike. Before the batch: 3 + about 5 per live rule, every caller."""

    RULE_ROWS = 3
    WITH_PROVENANCE = 5

    def _count(self, fn):
        with CaptureQueriesContext(connection) as ctx:
            fn()
        return len(ctx)

    def test_rule_rows_with_the_provenance_does_not_grow(self):
        from bot_program import evidence
        _live_rules(3, "pbb")
        with self.assertNumQueries(self.WITH_PROVENANCE):
            small = evidence.rule_rows(with_provenance=True)
        self.assertEqual({r["stage_note"] for r in small
                          if r["rule"].startswith("pbb_")},
                         {"by hand, unproven", "by hand, proven since"})
        _live_rules(6, "pbc")
        with self.assertNumQueries(self.WITH_PROVENANCE):
            large = evidence.rule_rows(with_provenance=True)
        self.assertEqual(len([r for r in large if r["stage_note"]]), 9)

    def test_rule_rows_without_it_reads_none_of_it(self):
        from bot_program import evidence
        from signals.rule_scope import rule_records
        _live_rules(9, "pbd")
        with self.assertNumQueries(self.RULE_ROWS):
            rows = evidence.rule_rows()
        self.assertEqual({r["stage_note"] for r in rows}, {""})
        # the signal engine's read, once per scan
        with self.assertNumQueries(self.RULE_ROWS):
            records = rule_records()
        self.assertEqual(records["pbd_0"]["n"], 2)

    def test_provenance_notes_alone_is_three_whatever_the_count(self):
        from signals.models import RuleControl
        from signals.promotion_pipeline import provenance_notes
        _live_rules(3, "pbe")
        ctrls = {c.rule_name: c for c in RuleControl.objects.all()}
        small = self._count(lambda: provenance_notes(list(ctrls),
                                                     controls=ctrls))
        _live_rules(6, "pbf")
        ctrls = {c.rule_name: c for c in RuleControl.objects.all()}
        large = self._count(lambda: provenance_notes(list(ctrls),
                                                     controls=ctrls))
        self.assertEqual((small, large), (3, 3))
        # below the live stages: no query at all
        _set_stage("pbe_0", "paper")
        _set_stage("pbe_1", "paper")
        paper = {c.rule_name: c for c in RuleControl.objects.filter(
            rule_name__in=["pbe_0", "pbe_1"])}
        with self.assertNumQueries(0):
            self.assertEqual(provenance_notes(list(paper), controls=paper),
                             {"pbe_0": "", "pbe_1": ""})
