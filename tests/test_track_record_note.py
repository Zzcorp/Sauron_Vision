"""An empty track record has to say WHICH kind of empty it is.

A live briefing read `rule_track_records: []` and told the operator the
telemetry was broken — "the highest-leverage fix on the list". It wasn't
broken. The book was young: twelve positions open, nothing closed, so there
was no realized R to measure. An empty list cannot distinguish "nothing has
closed" from "closes are not being graded", and the strategist guessed the
alarming one.

Run with:  python manage.py test tests.test_track_record_note
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from brain.synthesizer import (TRACK_RECORD_WINDOW_DAYS,
                               _build_world_snapshot,
                               _no_track_record_reason)


def _cfg(user):
    from bot_program.models import AssetBotConfig
    cfg, _ = AssetBotConfig.objects.get_or_create(
        user=user, asset_class="stock", name="tr bot",
        defaults={"capital": Decimal("10000")})
    return cfg


def _trade(cfg, **kw):
    from bot_program.models import AssetBotTrade
    closed_at = kw.pop("closed_at", timezone.now())
    trade = AssetBotTrade.objects.create(
        config=cfg, asset_class="stock",
        symbol=kw.pop("symbol", "AAPL"), side=kw.pop("side", "BUY"),
        qty=Decimal("10"), entry_price=Decimal("100"),
        exit_price=kw.pop("exit_price", Decimal("110")),
        status=kw.pop("status", "CLOSED"), pnl=Decimal("100"),
        rule_name=kw.pop("rule_name", "some_rule"),
        outcome=kw.pop("outcome", "hit_target"),
        realized_r=kw.pop("realized_r", 1.0), paper=True, **kw)
    from bot_program.models import AssetBotTrade as T
    T.objects.filter(pk=trade.pk).update(closed_at=closed_at)
    return trade


class EmptyBecauseYoungTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("tr_u")
        self.cfg = _cfg(self.user)

    def test_nothing_closed_reads_as_no_evidence_yet(self):
        _trade(self.cfg, status="OPEN", exit_price=None, closed_at=None,
               outcome="", realized_r=None)
        note = _no_track_record_reason()
        self.assertIn("NO REALIZED R YET", note)
        # And it says so in the words that stop a reader escalating it.
        self.assertIn("not broken", note)

    def test_it_counts_the_open_book_so_the_reader_can_see_why(self):
        for i in range(3):
            _trade(self.cfg, symbol=f"SYM{i}", status="OPEN", exit_price=None,
                   closed_at=None, outcome="", realized_r=None)
        self.assertIn("3 position(s) still open", _no_track_record_reason())

    def test_a_close_outside_the_window_is_still_no_evidence(self):
        _trade(self.cfg, closed_at=timezone.now()
               - timedelta(days=TRACK_RECORD_WINDOW_DAYS + 5))
        self.assertIn("NO REALIZED R YET", _no_track_record_reason())


class EmptyBecauseBrokenTests(TestCase):
    """The other kind of empty — the one that IS a fault."""

    def setUp(self):
        self.user = User.objects.create_user("tr_broken")
        self.cfg = _cfg(self.user)

    def test_closes_with_no_rule_name_are_named_as_a_fault(self):
        _trade(self.cfg, rule_name="")
        note = _no_track_record_reason()
        self.assertIn("GRADING GAP", note)
        self.assertIn("no rule_name", note)
        self.assertIn("IS a fault", note)

    def test_closes_with_no_realized_r_are_named_as_a_fault(self):
        _trade(self.cfg, realized_r=None)
        note = _no_track_record_reason()
        self.assertIn("GRADING GAP", note)
        self.assertIn("no stop", note)


class SnapshotCarriesTheNoteTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("tr_snap")
        self.cfg = _cfg(self.user)

    def test_an_empty_table_arrives_with_its_reason(self):
        snap = _build_world_snapshot()
        self.assertEqual(snap["rule_track_records"], [])
        self.assertIn("rule_track_records_note", snap)

    def test_the_window_travels_with_the_numbers(self):
        """A note quoting a different window than the query used is worse
        than no note."""
        snap = _build_world_snapshot()
        self.assertEqual(snap["rule_track_records_window_days"],
                         TRACK_RECORD_WINDOW_DAYS)
        self.assertIn(str(TRACK_RECORD_WINDOW_DAYS),
                      snap["rule_track_records_note"])

    def test_a_populated_table_carries_no_note(self):
        """Nothing to explain when there is evidence."""
        _trade(self.cfg)
        snap = _build_world_snapshot()
        self.assertTrue(snap["rule_track_records"])
        self.assertNotIn("rule_track_records_note", snap)
