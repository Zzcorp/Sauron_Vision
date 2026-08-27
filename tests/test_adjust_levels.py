"""Moving a stop is the one edit that can turn a defined loss into an
open-ended one.

Writing a number onto a row is trivial. The validation is the feature,
and every refusal here answers "what would the operator have meant, and
what would the platform then do":

  * A stop on the WRONG SIDE of the mark closes the position at market
    on the next tick and books it as a stop-out — a loss the thesis
    never took.
  * A stop that WIDENS risk is allowed, because an operator who has read
    the news and wants room is making a real decision — but it is named
    in the audit trail rather than filed silently beside the tightenings.
  * `initial_stop_loss` is never touched. Grading measures R against the
    stop the trade OPENED with; rewriting it would make risk and reward
    the same quantity and every managed winner would score 1R.
  * A broker-held stop moves AT THE BROKER FIRST. Moving only our copy
    would leave the row claiming a level the broker never heard of.

Run with:  python manage.py test tests.test_adjust_levels
"""
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone


class _Base(TestCase):
    def setUp(self):
        from bot_program.models import AssetBotConfig
        from instruments.models import Instrument
        from market_data.models import LiveQuote
        self.user = User.objects.create_user("lv_u", password="x")
        self.inst = Instrument.objects.create(
            symbol="BRNUSD", name="Brent", asset_class="commodity",
            is_active=True)
        LiveQuote.objects.create(instrument=self.inst, last=Decimal("84.00"),
                                 source="ibkr")
        self.cfg = AssetBotConfig.objects.create(
            user=self.user, asset_class="commodity", name="C", mode="paper",
            symbols=["BRNUSD"], capital=Decimal("10000"), enabled=True)

    def _trade(self, side="BUY", **kw):
        from bot_program.models import AssetBotTrade
        d = dict(config=self.cfg, asset_class="commodity", symbol="BRNUSD",
                 side=side, qty=Decimal("10"), entry_price=Decimal("82"),
                 stop_loss=Decimal("80"), take_profit=Decimal("88"),
                 status="OPEN", paper=True, opened_at=timezone.now(),
                 metadata={"initial_stop_loss": 80.0})
        d.update(kw)
        return AssetBotTrade.objects.create(**d)

    def _adjust(self, trade, **kw):
        from bot_program.adjust_levels import adjust_levels
        return adjust_levels(self.user, trade, **kw)


class AStopOnTheWrongSideIsRefusedTests(_Base):
    def test_a_long_stop_above_the_mark(self):
        """It would close at market next tick and book a stop-out."""
        r = self._adjust(self._trade(), stop="85")
        self.assertFalse(r["ok"])
        self.assertIn("above the current price", r["error"])

    def test_a_short_stop_below_the_mark(self):
        r = self._adjust(self._trade(side="SELL", stop_loss=Decimal("86")),
                         stop="82")
        self.assertFalse(r["ok"])
        self.assertIn("below the current price", r["error"])

    def test_a_long_target_below_the_mark_would_fill_at_once(self):
        r = self._adjust(self._trade(), target="83")
        self.assertFalse(r["ok"])
        self.assertIn("fill immediately", r["error"])

    def test_a_stop_above_its_own_target(self):
        r = self._adjust(self._trade(), stop="83", target="82.5")
        self.assertFalse(r["ok"])

    def test_a_refused_edit_changes_nothing(self):
        t = self._trade()
        self._adjust(t, stop="85")
        t.refresh_from_db()
        self.assertEqual(t.stop_loss, Decimal("80"))


class AValidEditLandsTests(_Base):
    def test_tightening_a_stop_works(self):
        t = self._trade()
        r = self._adjust(t, stop="83")
        self.assertTrue(r["ok"], r.get("error"))
        t.refresh_from_db()
        self.assertEqual(t.stop_loss, Decimal("83"))

    def test_moving_a_target_works(self):
        t = self._trade()
        self.assertTrue(self._adjust(t, target="92")["ok"])
        t.refresh_from_db()
        self.assertEqual(t.take_profit, Decimal("92"))

    def test_a_target_can_be_cleared(self):
        t = self._trade()
        self.assertTrue(self._adjust(t, clear_target=True)["ok"])
        t.refresh_from_db()
        self.assertIsNone(t.take_profit)

    def test_the_edit_is_recorded_on_the_row(self):
        t = self._trade()
        self._adjust(t, stop="83")
        t.refresh_from_db()
        edits = t.metadata["level_edits"]
        self.assertEqual(edits[-1]["stop"], "83")
        self.assertEqual(edits[-1]["by"], "lv_u")

    def test_the_log_is_bounded(self):
        t = self._trade()
        for i in range(30):
            self._adjust(t, stop=str(80.5 + i * 0.05))
            t.refresh_from_db()
        self.assertLessEqual(len(t.metadata["level_edits"]), 20)


class TheOpeningStopIsNeverRewrittenTests(_Base):
    def test_grading_still_measures_against_the_original(self):
        """Rewriting it would make risk and reward the same quantity and
        every managed winner would score 1R."""
        t = self._trade()
        self._adjust(t, stop="83")
        t.refresh_from_db()
        self.assertEqual(t.metadata["initial_stop_loss"], 80.0)


class AWideningIsAllowedButNamedTests(_Base):
    def test_widening_is_permitted(self):
        """An operator who has read the news and wants room is making a
        real decision."""
        t = self._trade()
        r = self._adjust(t, stop="78")
        self.assertTrue(r["ok"], r.get("error"))
        self.assertTrue(r["widened"])

    def test_it_is_marked_in_the_audit_trail(self):
        t = self._trade()
        self._adjust(t, stop="78")
        t.refresh_from_db()
        self.assertTrue(t.metadata["level_edits"][-1]["widened"])

    def test_a_tightening_is_not_marked_as_one(self):
        t = self._trade()
        self._adjust(t, stop="81")
        t.refresh_from_db()
        self.assertFalse(t.metadata["level_edits"][-1]["widened"])


class AClosedRowIsNotEditableTests(_Base):
    def test_a_closed_position_refuses(self):
        r = self._adjust(self._trade(status="CLOSED"), stop="83")
        self.assertFalse(r["ok"])
        self.assertIn("no longer be changed", r["error"])

    def test_a_close_pending_row_refuses(self):
        """A close is working at the broker; the two would race."""
        r = self._adjust(self._trade(status="CLOSE_PENDING"), stop="83")
        self.assertFalse(r["ok"])


class ABrokerHeldStopMovesAtTheBrokerFirstTests(_Base):
    def _protected(self):
        return self._trade(metadata={"initial_stop_loss": 80.0,
                                     "protected": True,
                                     "protective_order_ids": ["77"]})

    def test_the_row_is_not_touched_when_the_broker_refuses(self):
        """Otherwise the row claims a level the broker never heard of and
        the operator believes they are protected where they are not."""
        t = self._protected()
        client = MagicMock()
        client.modify_protective.return_value = {"ok": False,
                                                 "reason": "no session"}
        with patch("bot_program.engine.broker_router.client_for_symbol",
                   return_value=client):
            r = self._adjust(t, stop="83")
        self.assertFalse(r["ok"])
        self.assertIn("could not be moved", r["error"])
        t.refresh_from_db()
        self.assertEqual(t.stop_loss, Decimal("80"))

    def test_a_successful_broker_move_writes_the_row(self):
        t = self._protected()
        client = MagicMock()
        client.modify_protective.return_value = {"ok": True, "price": 83.0,
                                                 "reason": ""}
        with patch("bot_program.engine.broker_router.client_for_symbol",
                   return_value=client):
            r = self._adjust(t, stop="83")
        self.assertTrue(r["ok"], r.get("error"))
        t.refresh_from_db()
        self.assertEqual(t.stop_loss, Decimal("83"))

    def test_a_broker_that_cannot_modify_is_named_not_faked(self):
        """Falling back to a row-only write is how a row starts
        disagreeing with the venue."""
        t = self._protected()
        client = MagicMock(spec=[])          # no modify_protective
        with patch("bot_program.engine.broker_router.client_for_symbol",
                   return_value=client):
            r = self._adjust(t, stop="83")
        self.assertFalse(r["ok"])
        self.assertIn("cannot modify a resting order", r["error"])


class TheEndpointGuardsLiveMoneyTests(_Base):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)

    def _post(self, trade, body):
        import json
        return self.client.post(f"/positions/{trade.pk}/levels/",
                                data=json.dumps(body),
                                content_type="application/json")

    def test_a_paper_position_needs_no_pin(self):
        """Gating a simulation teaches the operator to type the PIN
        reflexively, which is the opposite of what a PIN is for."""
        r = self._post(self._trade(), {"stop": "83"})
        self.assertEqual(r.status_code, 200)

    def test_a_live_position_demands_the_pin(self):
        r = self._post(self._trade(paper=False), {"stop": "83"})
        self.assertEqual(r.status_code, 403)
        self.assertTrue(r.json().get("pin_required"))

    def test_another_users_position_is_not_reachable(self):
        other = User.objects.create_user("other_u", password="x")
        self.client.force_login(other)
        self.assertEqual(self._post(self._trade(), {"stop": "83"}).status_code,
                         404)

    def test_get_is_not_allowed(self):
        t = self._trade()
        self.assertEqual(
            self.client.get(f"/positions/{t.pk}/levels/").status_code, 405)
