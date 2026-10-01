"""The manual ticket meets the broker's own minimum (2026-10-01).

The operator: a manual forex or commodity ticket at 1x was risk-sized at
~180 USD and sent to eToro, which refuses anything under its
minPositionExposure (1,000 USD on forex, indices and commodities) — "the
broker refused the order" unless the size was typed by hand. The bot lane
already asked (AssetBot._venue_size_floor); the TAKE TRADE lane now asks
the same read through manual_trade._venue_min_qty and:

- on a LIVE ticket, raises the DEFAULT size to the minimum when the risk
  cap allows, and says so on the ticket (venue_min_note);
- refuses in the preview when no takeable size reaches it;
- keeps the minimum when the size is re-derived at the fill, and refuses a
  typed size under it with the number to type — nothing sent;
- never asks on a paper ticket; an unstated minimum refuses nothing.

Run with:  python manage.py test tests.test_manual_venue_minimum
"""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase

from tests.test_take_trade_live import (ROUTER, _arm_live, _components_on,
                                        _fake_live_client, _quote, _signal)

FLOOR = "bot_program.manual_trade._venue_min_qty"


class TheHelperTests(TestCase):

    def test_the_floor_is_rounded_up_to_the_step(self):
        from bot_program.manual_trade import _venue_min_qty
        with patch("bot_program.asset_engine.base.AssetBot._venue_size_floor",
                   return_value=(885.4, "")):
            self.assertEqual(_venue_min_qty(object(), "EURUSD", 1.1295, 1.0,
                                            100.0), (900.0, ""))

    def test_unstated_or_unreadable_is_none_never_zero(self):
        from bot_program.manual_trade import _venue_min_qty
        with patch("bot_program.asset_engine.base.AssetBot._venue_size_floor",
                   return_value=(None, "no eligibility row today")):
            self.assertEqual(_venue_min_qty(object(), "X", 1.0, 1.0, 1.0),
                             (None, "no eligibility row today"))
        with patch("bot_program.asset_engine.base.AssetBot._venue_size_floor",
                   side_effect=RuntimeError("wire")):
            units, why = _venue_min_qty(object(), "X", 1.0, 1.0, 1.0)
        self.assertIsNone(units)
        self.assertIn("unreadable", why)
        with patch("bot_program.asset_engine.base.AssetBot._venue_size_floor",
                   return_value=(0.0, "")):
            self.assertIsNone(_venue_min_qty(object(), "X", 1.0, 1.0,
                                             1.0)[0])


class TheLiveTicketTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("vmin_u",
                                                        password="x")

    def setUp(self):
        cache.clear()
        self.inst = _quote("BTCUSD", 60000)
        _components_on()
        self.cfg = _arm_live(self.user)

    def _default(self):
        from bot_program.manual_trade import preview_take_trade
        with patch(ROUTER, return_value=_fake_live_client()), \
                patch(FLOOR, return_value=(None, "unstated")):
            p = preview_take_trade(self.user, _signal(self.inst))
        self.assertNotIn("error", p, p)
        self.assertIsNone(p["venue_min_qty"])
        return p

    @staticmethod
    def _between(p):
        """A minimum above the risk-sized default and inside every cap."""
        floor = round((p["qty"] + p["max_qty"]) / 2, 8)
        assert p["qty"] < floor <= p["max_qty"], p
        return floor

    def test_the_default_is_raised_to_the_brokers_minimum(self):
        from bot_program.manual_trade import preview_take_trade
        before = self._default()
        floor = self._between(before)
        with patch(ROUTER, return_value=_fake_live_client()), \
                patch(FLOOR, return_value=(floor, "")):
            p = preview_take_trade(self.user, _signal(self.inst))
        self.assertNotIn("error", p, p)
        self.assertEqual(p["qty"], floor)
        self.assertEqual(p["venue_min_qty"], floor)
        self.assertIn("Raised from", p["venue_min_note"])
        self.assertGreater(p["risk_dollars"], before["risk_dollars"])
        self.assertGreater(p["notional"], before["notional"])

    def test_no_takeable_size_reaching_it_is_refused_in_the_preview(self):
        from bot_program.manual_trade import preview_take_trade
        with patch(ROUTER, return_value=_fake_live_client()), \
                patch(FLOOR, return_value=(1000.0, "")):
            p = preview_take_trade(self.user, _signal(self.inst))
        self.assertIn("The broker's minimum for BTCUSD is 1000", p["error"])
        self.assertIn("Nothing was sent", p["error"])

    def test_execute_sends_the_minimum_not_the_risk_size(self):
        from bot_program.manual_trade import execute_take_trade
        floor = self._between(self._default())
        fake = _fake_live_client()
        with patch(ROUTER, return_value=fake), \
                patch(FLOOR, return_value=(floor, "")):
            out = execute_take_trade(self.user, _signal(self.inst),
                                     pin_ok=True)
        self.assertNotIn("error", out, out)
        fake.market_order.assert_called_once()
        call = fake.market_order.call_args
        sent = call.kwargs.get("quantity", call.args[2] if len(call.args) > 2
                               else None)
        self.assertGreaterEqual(float(sent), floor - 1e-9)

    def test_a_typed_size_under_the_minimum_is_refused(self):
        from bot_program.manual_trade import execute_take_trade
        before = self._default()
        floor = self._between(before)
        fake = _fake_live_client()
        with patch(ROUTER, return_value=fake), \
                patch(FLOOR, return_value=(floor, "")):
            out = execute_take_trade(self.user, _signal(self.inst),
                                     qty=str(before["qty"]), pin_ok=True)
        self.assertIn("Raise the size to at least", out.get("error", ""))
        self.assertIn("nothing was sent", out["error"])
        fake.market_order.assert_not_called()


class ThePaperTicketTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("vmin_p",
                                                        password="x")

    def test_a_paper_ticket_never_asks(self):
        from bot_program.manual_trade import preview_take_trade
        inst = _quote("BTCUSD", 60000)
        with patch(FLOOR, side_effect=AssertionError("asked")) as asked:
            p = preview_take_trade(self.user, _signal(inst))
        asked.assert_not_called()
        self.assertEqual(p.get("venue"), "paper")
        self.assertIsNone(p["venue_min_qty"])
