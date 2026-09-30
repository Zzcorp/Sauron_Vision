"""A manual lane may carry its own MAX SINGLE POSITION (2026-09-30).

The operator: "I want bots on and manual too". A manual forex ticket goes
at 1x (the lane refuses leverage) and eToro refuses one under 1,000 USD,
so against a 1,100 USD pool the book's 20% ceiling (220) refused every
ticket that could fill. Raising the book's percentage would have raised it
for every bot too. extras['max_single_position_pct'] on the manual config
raises it for that lane's hand-taken tickets only.

Pinned here: the key's parsing (a bad value keeps the book's percentage);
both gates honour an explicit lane ceiling and keep the book's without
one; the manual preview and execute read the lane's; a bot's gate never
does.

Run with:  python manage.py test tests.test_manual_lane_ceiling
"""
from decimal import Decimal
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.test import TestCase

from tests.test_risk_limits_bind import _book, _quote


class TheKeyTests(TestCase):

    def _pct(self, extras):
        from bot_program.manual_trade import lane_single_position_pct
        return lane_single_position_pct(SimpleNamespace(extras=extras))

    def test_a_number_in_range_is_the_lane_ceiling(self):
        self.assertEqual(self._pct({"max_single_position_pct": 100}), 100.0)
        self.assertEqual(self._pct({"max_single_position_pct": "50"}), 50.0)

    def test_anything_else_keeps_the_books_percentage(self):
        for raw in (None, 0, -5, 150, "abc", True, [], {}):
            self.assertIsNone(self._pct({"max_single_position_pct": raw}),
                              raw)
        self.assertIsNone(self._pct({}))
        self.assertIsNone(self._pct(None))


class TheGatesTests(TestCase):
    """The forex arithmetic of the live box: 900 EURUSD at ~1.137 is
    1,023 USD at 1x against a 1,100 USD manual pool."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("lane_g",
                                                        password="x")

    def test_the_book_refuses_a_ticket_that_could_fill(self):
        from portfolio.risk_gate import limits_book, single_position_state
        _book(current_value=Decimal("10000"), max_single_position_pct=20.0)
        state = single_position_state(
            limits_book(), asset_class="forex", notional=1023.0,
            capital_base=1100.0, base_label="manual pool", leverage=1,
            carrier="etoro")
        self.assertFalse(state["ok"])
        self.assertEqual(state["cap_money"], 220.0)

    def test_the_lane_ceiling_lets_it_through(self):
        from portfolio.risk_gate import limits_book, single_position_state
        _book(current_value=Decimal("10000"), max_single_position_pct=20.0)
        state = single_position_state(
            limits_book(), asset_class="forex", notional=1023.0,
            capital_base=1100.0, base_label="manual pool", leverage=1,
            carrier="etoro", lane_limit_pct=100.0)
        self.assertTrue(state["ok"], state["reason"])
        self.assertEqual(state["limit_pct"], 100.0)
        self.assertEqual(state["cap_money"], 1100.0)

    def test_the_lane_ceiling_is_still_a_ceiling(self):
        from portfolio.risk_gate import limits_book, single_position_state
        _book(current_value=Decimal("10000"), max_single_position_pct=20.0)
        self.assertFalse(single_position_state(
            limits_book(), asset_class="forex", notional=1200.0,
            capital_base=1100.0, leverage=1, carrier="etoro",
            lane_limit_pct=100.0)["ok"])

    def test_concentration_follows_the_same_percentage(self):
        from portfolio.risk_gate import concentration_state
        _book(current_value=Decimal("10000"), max_single_position_pct=20.0)
        kw = dict(symbol="EURUSD", side="BUY", asset_class="forex",
                  notional=1023.0, capital_base=1100.0,
                  base_label="manual pool", leverage=1, carrier="etoro")
        self.assertFalse(concentration_state(self.user, **kw)["ok"])
        lane = concentration_state(self.user, lane_limit_pct=100.0, **kw)
        self.assertTrue(lane["ok"], lane["reason"])
        self.assertEqual(lane["limit_pct"], 100.0)


class TheManualPathTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("lane_m",
                                                        password="x")

    def setUp(self):
        self.inst = _quote("BTCUSD", 60000)
        _book(current_value=Decimal("10000"), max_single_position_pct=0.5)

    def _lane(self, pct):
        from bot_program.manual_trade import manual_config_for
        cfg = manual_config_for(self.user, "crypto")
        cfg.extras = dict(cfg.extras or {}, max_single_position_pct=pct)
        cfg.save(update_fields=["extras"])
        return cfg

    def test_the_preview_reads_the_books_ceiling_without_the_key(self):
        from bot_program.manual_trade import preview_asset_trade
        out = preview_asset_trade(self.user, self.inst, "BUY")
        self.assertEqual(out["book_single_position"]["limit_pct"], 0.5)

    def test_the_preview_reads_the_lanes_ceiling_with_it(self):
        from bot_program.manual_trade import preview_asset_trade
        self._lane(100)
        out = preview_asset_trade(self.user, self.inst, "BUY")
        self.assertNotIn("error", out)
        self.assertEqual(out["book_single_position"]["limit_pct"], 100.0)
        self.assertTrue(out["book_single_position"]["ok"])

    def test_execute_refuses_on_the_book_and_opens_on_the_lane(self):
        from bot_program.manual_trade import execute_asset_trade
        from bot_program.models import AssetBotTrade
        refused = execute_asset_trade(self.user, self.inst, "BUY")
        self.assertIn("single position may hold", refused.get("error", ""))
        self.assertFalse(AssetBotTrade.objects.filter(
            symbol="BTCUSD", status="OPEN").exists())
        self._lane(100)
        out = execute_asset_trade(self.user, self.inst, "BUY")
        self.assertNotIn("error", out)
        self.assertTrue(AssetBotTrade.objects.filter(
            symbol="BTCUSD", status="OPEN").exists())

    def test_a_bots_gate_never_reads_a_lane_key(self):
        """The bot path passes no lane ceiling: the book's percentage is
        what every bot sizes under, whatever a manual lane carries."""
        import inspect

        from bot_program.asset_engine import base
        self.assertNotIn("lane_limit_pct", inspect.getsource(base))
        self.assertNotIn("lane_single_position_pct", inspect.getsource(base))
