"""T4, THE RENDER PASS MERGES BEFORE IT RENDERS (the O2 spec A.7, A.11
step 9, A.14, P1, P15; §1.1.7 T4; 2026-11-05).

The render pass (wake.render_queued) takes each recorded wake, oldest
first, through three short transactions: scheduler.absorb, the render,
scheduler.admit. Here the tick records each wake (wake.record) and the
render pass does the rest; the fake model answers what the claim serves.

- a newer routine wake absorbs the Orc's older urgent one BEFORE its
  render: the survivor's reasons are the union by key, each keeping its
  own urgency; its dossier lists every reason; it is urgent, so it skips
  the spacing; it keeps the older wake's first send; the older wake is
  `merged` with merged_into and finished_at, and the claim serves the
  survivor alone
- a plan's watch never makes the survivor urgent
- the database holds one pending wake per Orc, whatever the pass meets
- the merge commits before the render: a render that fails afterwards
  leaves the older wake merged and the survivor answered by code
  (`render_failed`), never silence
- wake.py imports the scheduler inside render_queued only

Run with:  python manage.py test tests.orcs.test_orc_o2a_merge
"""
import ast
import inspect
from datetime import timedelta
from unittest.mock import patch

from django.db import IntegrityError, transaction
from django.utils import timezone

from tests.orcs.helpers_o2 import fake_answer
from tests.orcs.test_orc_o2a_admission import PLAN, W2, W4, QueueFixture
from tests.orcs.test_orc_o2a_call import answer


class _Merge(QueueFixture):

    def record(self, reasons, *, at=None):
        """The tick records one wake (wake.record), as of `at`."""
        from bot_program.orcs import wake
        self.orc.refresh_from_db()
        return wake.record(self.orc, self.orc.root_trade, list(reasons),
                           now=at or timezone.now(), price="100.5")

    def render_pass(self):
        from bot_program.orcs import wake
        return wake.render_queued()

    def fresh(self, w):
        from bot_program.orcs.models import OrcWake
        return OrcWake.objects.get(pk=w.pk)


class TheMergeInTheRenderPassTests(_Merge):

    def test_a_newer_routine_wake_absorbs_an_older_urgent_one(self):
        """P15: the survivor is urgent, skips the spacing, keeps the older
        first send, and its dossier lists both reasons."""
        from bot_program.orcs.models import Orc, OrcDossierBlock
        first = timezone.now() - timedelta(minutes=12)
        older = self.record([W4], at=first)
        with patch("django.utils.timezone.now", return_value=first):
            out = self.render_pass()
        self.assertEqual(out.admitted, 1)
        older = self.fresh(older)
        self.assertEqual((older.status, older.queued_at), ("pending", first))
        Orc.objects.filter(pk=self.orc.pk).update(
            last_wake_at=timezone.now() - timedelta(minutes=3))
        newer = self.record([W2])
        out = self.render_pass()
        self.assertEqual((tuple(out), out.admitted), ((1, 0), 1))
        newer, older = self.fresh(newer), self.fresh(older)
        self.assertEqual([r["key"] for r in newer.reasons],
                         [W2["key"], W4["key"]])
        self.assertEqual([r["urgent"] for r in newer.reasons],
                         [False, True])
        self.assertEqual(newer.kind, "material", "the union's kind")
        self.assertEqual((newer.status, newer.priority), ("pending", 1.0),
                         "urgent: no spacing; paper urgent's rank")
        self.assertEqual(newer.queued_at, first, "the older first send")
        self.assertEqual(newer.components["queued_at_inherited"],
                         first.isoformat())
        self.assertEqual((older.status, older.components["merged_into"]),
                         ("merged", newer.pk))
        self.assertIsNotNone(older.finished_at)
        # the merge ran before the render: the dossier lists both
        tail = OrcDossierBlock.objects.get(hash=newer.block_hashes[-1])
        for r in (W2, W4):
            self.assertIn(r["t"], tail.text)
        got = self.serve(script=fake_answer(answer()))
        self.assertEqual(got["wake"].pk, newer.pk)
        self.assert_one_call()
        self.assertEqual(self.fresh(older).status, "merged")

    def test_a_plan_watch_never_makes_the_survivor_urgent(self):
        older = self.record([PLAN])
        self.render_pass()
        self.assertEqual(self.fresh(older).status, "pending")
        newer = self.record([W2])
        self.render_pass()
        newer = self.fresh(newer)
        self.assertEqual({r["key"] for r in newer.reasons},
                         {W2["key"], PLAN["key"]})
        self.assertFalse(any(r.get("urgent") for r in newer.reasons))
        self.assertEqual((newer.status, newer.priority), ("pending", 0.0))
        self.assertEqual(self.fresh(older).status, "merged")

    def test_the_database_holds_one_pending_wake_per_orc(self):
        from bot_program.orcs.models import OrcWake
        a = self.record([W4], at=timezone.now() - timedelta(minutes=3))
        b = self.record([W2], at=timezone.now() - timedelta(minutes=2))
        self.render_pass()
        c = self.record([W2, {**W4, "key": "W4:-0.75", "t": "-0.75R "
                                                          "reached"}])
        self.render_pass()
        pending = list(OrcWake.objects.filter(orc=self.orc,
                                              status="pending"))
        self.assertEqual([w.pk for w in pending], [c.pk])
        self.assertEqual(self.fresh(a).status, "merged")
        self.assertEqual(self.fresh(b).status, "merged")
        self.assertEqual(self.fresh(a).components["merged_into"], b.pk)
        self.assertEqual(self.fresh(b).components["merged_into"], c.pk)
        self.assertEqual({r["key"] for r in self.fresh(c).reasons},
                         {W4["key"], W2["key"], "W4:-0.75"})
        with self.assertRaises(IntegrityError), transaction.atomic():
            OrcWake.objects.create(orc=self.orc, reasons=[], status="pending",
                                   dedupe_key=f"orc{self.orc.pk}:pending")

    def test_the_merge_commits_before_the_render(self):
        """A.7: absorb holds its own transaction. A render that then fails
        leaves the older wake merged, and the survivor answered by code
        with `render_failed`: never pending, never silence."""
        older = self.record([W4])
        self.render_pass()
        newer = self.record([W2])
        with patch("bot_program.orcs.dossier.render",
                   side_effect=RuntimeError("the dossier broke")):
            out = self.render_pass()
        self.assertEqual((tuple(out), out.admitted), ((0, 1), 0))
        older, newer = self.fresh(older), self.fresh(newer)
        self.assertEqual((older.status, older.components["merged_into"]),
                         ("merged", newer.pk))
        self.assertEqual((newer.status, newer.skipped_reason),
                         ("skipped", "render_failed"))
        self.assertEqual(newer.components["render"], "failed")
        self.assertIsNone(self.serve()["wake"], "nothing left to claim")

    def test_wake_imports_the_scheduler_inside_render_queued_only(self):
        from bot_program.orcs import wake
        tree = ast.parse(inspect.getsource(wake))
        top = [n for n in tree.body
               if isinstance(n, (ast.Import, ast.ImportFrom))]
        for node in top:
            names = [a.name for a in node.names] + [
                getattr(node, "module", "") or ""]
            self.assertFalse([n for n in names if "scheduler" in n],
                             ast.unparse(node))
        where = []
        for fn in (n for n in ast.walk(tree)
                   if isinstance(n, ast.FunctionDef)):
            for sub in ast.walk(fn):
                if isinstance(sub, (ast.Import, ast.ImportFrom)) and any(
                        "scheduler" in a.name for a in sub.names):
                    where.append(fn.name)
        self.assertEqual(sorted(set(where)), ["render_queued"])
