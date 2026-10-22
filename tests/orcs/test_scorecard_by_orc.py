"""THE SCORECARD AND THE ORCS (bot_program/scorecard.py, spec §6.8):
`exit_of` reads an Orc's own exit first; `shadow_r` is the care ghost's R
once an idea is graded (and the row's own while the switch is OFF, with no
Orc table read); `scorecard --by orc` groups by class, venue, bar source
and level, never pooled, in R only.

Run with:  python manage.py test tests.orcs.test_scorecard_by_orc
"""
import re
from decimal import Decimal
from io import StringIO
from types import SimpleNamespace

from django.core.management import call_command
from django.db import connection
from django.test import SimpleTestCase, TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from tests.orcs.helpers import _config, _on, _row, _user, born


def _closed(**kw):
    base = dict(reason="", outcome="", metadata={}, stop_loss=None)
    base.update(kw)
    return SimpleNamespace(**base)


class TheExitTests(SimpleTestCase):

    def test_exit_of_orc_exit_first_and_orc_stop(self):
        from bot_program.scorecard import exit_of
        self.assertEqual(exit_of(_closed(
            reason="x | closed:MANUAL",
            metadata={"orc_exit": {"action": "exit"}})), "orc: exit")
        self.assertEqual(exit_of(_closed(
            metadata={"care_exit": "orc: T-STRUCT S4h-L1"})),
            "orc stop: T-STRUCT S4h-L1")
        self.assertEqual(exit_of(_closed(metadata={"care_exit": "orc"})),
                         "orc stop: its stop")

    def test_exit_of_unchanged_without_orc_keys(self):
        from bot_program.scorecard import exit_of
        self.assertEqual(exit_of(_closed(reason="x | closed:MANUAL")),
                         "by hand")
        self.assertEqual(exit_of(_closed(metadata={"care_exit": "trail"})),
                         "care: trail")
        self.assertEqual(exit_of(_closed(outcome="time_stop")), "time stop")
        self.assertEqual(exit_of(_closed(outcome="hit_target")), "target")
        self.assertEqual(exit_of(_closed(outcome="stopped_out")), "stop")
        self.assertEqual(exit_of(_closed(metadata={"orc_exit": {}})),
                         "other: ungraded")


class _Base(TestCase):

    def setUp(self):
        self.user = _user("orc_card")
        self.cfg = _config(self.user)

    def _graded(self, symbol="BTCUSD", *, ghost_r=1.2, delta=-0.2,
                source="etoro", venue="paper", capture=None, r_avail=None):
        from bot_program.models import AssetBotTrade
        from bot_program.orcs.models import Orc, OrcGrade
        _on()
        row = _row(self.cfg, symbol=symbol)
        orc = born(self, row)
        AssetBotTrade.objects.filter(pk=row.pk).update(
            status="CLOSED", closed_at=timezone.now(), realized_r=0.9,
            outcome="stopped_out", exit_price=Decimal("101"))
        Orc.objects.filter(pk=orc.pk).update(state="dead")
        OrcGrade.objects.create(
            orc=orc, r_money=Decimal("2"), ghost_r=ghost_r,
            orc_r_gross=ghost_r + delta, delta_care=delta, delta_play=0.1,
            bar_source=source, venue=venue, r_avail=r_avail,
            capture_orc=capture, capture_ghost=capture, capture_play=capture)
        return row


class TheRowsTests(_Base):

    def test_shadow_r_ghost_when_graded_on_else_realized(self):
        from bot_program import scorecard as sc
        row = self._graded()
        plain = _row(self.cfg, symbol="ETHUSD")
        from bot_program.models import AssetBotTrade
        AssetBotTrade.objects.filter(pk=plain.pk).update(
            status="CLOSED", closed_at=timezone.now(), realized_r=0.4)
        by = {r["id"]: r for r in sc.rows(days=1)}
        self.assertEqual(by[row.pk]["shadow_r"], 1.2)
        self.assertEqual(by[row.pk]["r"], 0.9)
        self.assertEqual(by[plain.pk]["shadow_r"], 0.4)
        _on(False)
        by = {r["id"]: r for r in sc.rows(days=1)}
        self.assertEqual(by[row.pk]["shadow_r"], 0.9, "OFF: the row's own")

    def test_rows_off_no_orc_query(self):
        from bot_program import scorecard as sc
        self._graded()
        _on(False)
        with CaptureQueriesContext(connection) as q:
            sc.rows(days=1)
        self.assertFalse([x for x in q.captured_queries
                          if "bot_program_orc" in x["sql"]])

    def test_by_orc_groups_never_pooled_no_money(self):
        self._graded("BTCUSD", source="etoro", capture=0.5, r_avail=1.0)
        self._graded("ETHUSD", source="etoro", delta=0.1)
        self._graded("SOLUSD", source="platform")
        out = StringIO()
        call_command("scorecard", "--by", "orc", stdout=out)
        text = out.getvalue()
        self.assertIn("── orc crypto · paper · etoro · L0 ──", text)
        self.assertIn("── orc crypto · paper · platform · L0 ──", text)
        self.assertIn("ideas 2 · Δ care -0.05R · Δ playbook +0.10R", text)
        self.assertIn("capture: Orc 0.50 · care 0.50 · playbook 0.50 (1 "
                      "ideas with at least +0.5R available)", text)
        self.assertIn("add legs: — (no add before O5)", text)
        self.assertIn("AI cost per idea: +0.000R", text)
        self.assertIn("inferred exit price: 0 of 2", text)
        self.assertNotRegex(text, re.compile(r"[$€£]|USD\s?\d|\d\s?USD"))

    def test_no_graded_idea_says_so(self):
        out = StringIO()
        call_command("scorecard", "--by", "orc", stdout=out)
        self.assertIn("no graded Orc idea in this window", out.getvalue())
