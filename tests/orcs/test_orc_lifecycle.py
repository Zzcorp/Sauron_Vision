"""DEATH (spec §1.2, O1a): every close path ends the idea — the tick's
close, the reconcile (a venue stop, an app close), the CLOSE_PENDING drain,
the kill switch, a queryset update caught by the census sweep — through a
post_save receiver that waits for the grade, the census sweep and an
explicit kill-switch call. In O1 every idea ends dead: the re-entry window
needs an L3 seat and arrives with O5.

Run with:  python manage.py test tests.orcs.test_orc_lifecycle
"""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.utils import timezone

from tests.orcs.helpers import (_config, _manual_config, _manual_row, _on,
                                _row, _user, born, headlines, journal)
from tests.test_risk_limits_bind import _quote

ROUTER = "bot_program.engine.broker_router.client_for_symbol"
SHUT = "bot_program.engine.paper_trader.paper_market_shut"
NO_WINDOW = ("This idea is over: its last leg closed. No re-entry window: "
             "its seat is at L0; a re-entry needs L3.")


class TheClosePathsTests(TestCase):

    def setUp(self):
        _on()
        self.user = _user("orc_life")
        self.cfg = _config(self.user)
        from bot_program.asset_engine.base import make_bot
        self.bot = make_bot(self.cfg)

    def _close(self, trade, price, reason):
        with patch(SHUT, return_value=""), \
                self.captureOnCommitCallbacks(execute=True):
            return self.bot._close_trade(trade, Decimal(price), None,
                                         reason=reason)

    def test_close_trade_ends_the_idea(self):
        row = _row(self.cfg)
        orc = born(self, row)
        self.assertTrue(self._close(row, "110", "TP"))
        orc.refresh_from_db()
        row.refresh_from_db()
        self.assertEqual(orc.state, "dead")
        self.assertFalse(orc.hand_touched)
        self.assertEqual(orc.died_at, row.closed_at)
        facts = headlines(orc, kind="fact")
        from core.price_format import format_price
        self.assertIn(f"The position closed at "
                      f"{format_price(row.exit_price, 'crypto', 'BTCUSD')} "
                      f"(target), {row.realized_r:+.2f}R booked.", facts)
        self.assertEqual(facts[-1], NO_WINDOW)

    def test_a_platform_hand_close_is_a_hand_act(self):
        row = _row(self.cfg)
        orc = born(self, row)
        self._close(row, "101", "MANUAL")
        orc.refresh_from_db()
        self.assertTrue(orc.hand_touched)
        self.assertEqual(orc.state, "dead")
        self.assertTrue(any("(by hand)" in h for h in headlines(orc)))

    def test_a_venue_stop_booked_by_the_reconcile_ends_the_idea(self):
        from bot_program.reconcile_asset import _close_as_orphan
        real = _config(self.user, mode="live", name="real")
        row = _row(real, paper=False)
        orc = born(self, row)
        client = MagicMock()
        client.ticker = MagicMock(return_value={"lastPrice": "97"})
        client.closing_fill = None
        with patch(ROUTER, return_value=client), \
                self.captureOnCommitCallbacks(execute=True):
            _close_as_orphan(row)
        orc.refresh_from_db()
        self.assertEqual(orc.state, "dead")
        self.assertFalse(orc.hand_touched, "the venue's stop is no hand")
        self.assertTrue(any("(stop at the venue, found by the reconcile)" in h
                            for h in headlines(orc)), headlines(orc))

    def test_an_app_close_found_by_the_reconcile_is_a_hand_act(self):
        from bot_program.reconcile_asset import _close_as_orphan
        real = _config(self.user, mode="live", name="real")
        row = _manual_row(real, paper=False)
        orc = born(self, row)
        client = MagicMock()
        client.ticker = MagicMock(return_value={"lastPrice": "101"})
        client.closing_fill = None
        with patch(ROUTER, return_value=client), \
                self.captureOnCommitCallbacks(execute=True):
            _close_as_orphan(row)
        orc.refresh_from_db()
        row.refresh_from_db()
        self.assertEqual(row.outcome, "manual_close")
        self.assertTrue(orc.hand_touched)
        self.assertEqual(orc.state, "dead")
        self.assertTrue(any("(a hand close at the venue, found by the "
                            "reconcile)" in h for h in headlines(orc)))

    def test_the_close_pending_drain_ends_the_idea(self):
        from bot_program.pending_closes import _finalise_closed
        row = _row(self.cfg, status="CLOSE_PENDING")
        orc = born(self, _row(self.cfg, symbol="ETHUSD"))
        self.assertIsNone(born(self, row), "a closing row is not born")
        pending = _row(self.cfg, symbol="SOLUSD")
        orc2 = born(self, pending)
        pending.status = "CLOSE_PENDING"
        pending.save(update_fields=["status"])
        with self.captureOnCommitCallbacks(execute=True):
            _finalise_closed(pending, fill={"price": Decimal("97"),
                                            "metadata": {}}, reason="SL")
        orc2.refresh_from_db()
        self.assertEqual(orc2.state, "dead")
        orc.refresh_from_db()
        self.assertEqual(orc.state, "born", "another idea is untouched")

    def test_the_kill_switch_kills_every_idea_with_no_window(self):
        from bot_program.engine.kill_switch import execute_kill_switch
        from bot_program.orcs.models import Orc
        _quote("BTCUSD", "101")
        _quote("ETHUSD", "101")
        a = born(self, _row(self.cfg))
        b = born(self, _row(self.cfg, symbol="ETHUSD"))
        other = _user("orc_life_other")
        c = born(self, _row(_config(other), symbol="BTCUSD"))
        with patch(SHUT, return_value=""), \
                self.captureOnCommitCallbacks(execute=True):
            execute_kill_switch(user=self.user, reason="test")
        for orc in (a, b):
            orc.refresh_from_db()
            self.assertEqual((orc.state, orc.killed), ("dead", True))
            facts = headlines(orc, kind="fact")
            self.assertEqual(facts.count("The kill switch ended this idea: "
                                         "no re-entry window."), 1)
            self.assertTrue(any("(the kill switch)" in h for h in facts),
                            facts)
        c.refresh_from_db()
        self.assertEqual(c.state, "born", "another user's idea lives on")
        self.assertEqual(Orc.objects.filter(killed=True).count(), 2)

    def test_kill_all_ignores_the_switch_and_reads_once_when_empty(self):
        from bot_program.orcs.lifecycle import kill_all
        orc = born(self, _row(self.cfg))
        _on(False)
        self.assertEqual(kill_all(self.user, reason="t"), 1)
        orc.refresh_from_db()
        self.assertEqual((orc.state, orc.killed), ("dead", True))
        self.assertIsNotNone(orc.died_at)
        with self.assertNumQueries(1):
            self.assertEqual(kill_all(self.user, reason="t"), 0)

    def test_a_queryset_update_is_caught_by_the_census_sweep(self):
        from bot_program.models import AssetBotTrade
        from bot_program.orcs import census
        row = _row(self.cfg)
        orc = born(self, row)
        AssetBotTrade.objects.filter(pk=row.pk).update(
            status="CLOSED", exit_price=Decimal("99"), outcome="manual_close",
            closed_at=timezone.now())
        orc.refresh_from_db()
        self.assertEqual(orc.state, "born", "an update sends no signal")
        with self.captureOnCommitCallbacks(execute=True):
            out = census.run()
        self.assertEqual(out["died"], 1)
        orc.refresh_from_db()
        self.assertEqual(orc.state, "dead")
        self.assertEqual(headlines(orc, kind="fact")[-1], NO_WINDOW)

    def test_the_receiver_waits_for_the_grade(self):
        row = _row(self.cfg)
        orc = born(self, row)
        row.status = "CLOSED"
        row.exit_price = Decimal("103")
        row.closed_at = timezone.now()
        with self.captureOnCommitCallbacks(execute=True) as cbs:
            row.save()
        self.assertEqual(cbs, [], "no outcome yet: the grade comes next")
        orc.refresh_from_db()
        self.assertEqual(orc.state, "born")
        row.outcome = "hit_target"
        row.realized_r = 1.5
        with self.captureOnCommitCallbacks(execute=True) as cbs:
            row.save(update_fields=["outcome", "realized_r"])
        self.assertEqual(len(cbs), 1)
        orc.refresh_from_db()
        self.assertEqual(orc.state, "dead")

    def test_on_leg_closed_is_idempotent(self):
        from bot_program.orcs.lifecycle import on_leg_closed
        row = _row(self.cfg)
        orc = born(self, row)
        self._close(row, "104", "TP")
        n = len(journal(orc))
        on_leg_closed(row.pk)
        on_leg_closed(row.pk)
        self.assertEqual(len(journal(orc)), n)
        self.assertEqual(sum(h.startswith("The position closed")
                             for h in headlines(orc)), 1)

    def test_an_l0_seat_never_opens_a_reentry_window(self):
        from bot_program.orcs.lifecycle import _reentry_open
        bot_row = _row(self.cfg)
        orc = born(self, bot_row)
        self.assertEqual(_reentry_open(orc, bot_row),
                         (False, "its seat is at L0; a re-entry needs L3"))
        hand = born(self, _manual_row(_manual_config(self.user),
                                      symbol="ETHUSD"))
        self.assertEqual(_reentry_open(hand, hand.root_trade),
                         (False, "a hand idea never re-enters on its own"))
        orc.seat.level = 3
        orc.seat.save(update_fields=["level"])
        self.assertEqual(_reentry_open(orc, bot_row),
                         (False, "the re-entry arrives with O5"))
        orc.reentries_used = 1
        self.assertEqual(_reentry_open(orc, bot_row),
                         (False, "its one re-entry is used"))
        orc.killed = True
        self.assertEqual(_reentry_open(orc, bot_row),
                         (False, "the kill switch ended it"))

    def test_died_at_is_the_last_legs_close_time(self):
        from bot_program.models import AssetBotTrade
        from bot_program.orcs.lifecycle import on_leg_closed
        from bot_program.orcs.models import OrcLeg
        root = _row(self.cfg)
        orc = born(self, root)
        add = _row(self.cfg, meta={"orc": {"idea": orc.pk, "leg": 2,
                                           "kind": "add"}})
        OrcLeg.objects.create(orc=orc, trade=add, kind="add", seq=2)
        late = timezone.now() - timedelta(minutes=5)
        early = late - timedelta(hours=2)
        AssetBotTrade.objects.filter(pk=root.pk).update(
            status="CLOSED", outcome="stopped_out", closed_at=early,
            exit_price=Decimal("98"), realized_r=-1.0)
        on_leg_closed(root.pk)
        orc.refresh_from_db()
        self.assertEqual(orc.state, "born", "one leg is still open")
        AssetBotTrade.objects.filter(pk=add.pk).update(
            status="CLOSED", outcome="stopped_out", closed_at=late,
            exit_price=Decimal("98"), realized_r=-1.0)
        on_leg_closed(add.pk)
        orc.refresh_from_db()
        self.assertEqual(orc.state, "dead")
        self.assertEqual(orc.died_at, late)

    def test_the_receiver_is_silent_while_off(self):
        from bot_program.orcs import census
        row = _row(self.cfg)
        orc = born(self, row)
        n = len(journal(orc))
        _on(False)
        self._close(row, "104", "TP")
        orc.refresh_from_db()
        self.assertEqual(orc.state, "born")
        self.assertEqual(len(journal(orc)), n)
        _on()
        with self.captureOnCommitCallbacks(execute=True):
            census.run()
        orc.refresh_from_db()
        self.assertEqual(orc.state, "dead", "the sweep catches it later")

    def test_a_missing_price_and_a_missing_r_are_said(self):
        from bot_program.models import AssetBotTrade
        from bot_program.orcs.lifecycle import on_leg_closed
        row = _row(self.cfg)
        orc = born(self, row)
        AssetBotTrade.objects.filter(pk=row.pk).update(
            status="CLOSED", outcome="manual_close", closed_at=timezone.now(),
            exit_price=None, realized_r=None)
        on_leg_closed(row.pk)
        self.assertIn("The position closed (other: manual_close); the exit "
                      "is not priced.", headlines(orc))
        second = _row(self.cfg, symbol="ETHUSD")
        orc2 = born(self, second)
        AssetBotTrade.objects.filter(pk=second.pk).update(
            status="CLOSED", outcome="manual_close", closed_at=timezone.now(),
            exit_price=Decimal("101"), realized_r=None)
        on_leg_closed(second.pk)
        self.assertTrue(any(h.endswith("; its R is not measured.")
                            for h in headlines(orc2)))
