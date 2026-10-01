"""The live TAKE TRADE ticket carries a leverage, the highest by default
(2026-10-01).

The operator, on learning his live positions were at 1x: "I choose, but I
want the max by default". A hand-taken ticket went at 1x whatever the
account — a 900 EURUSD pledged its full 1,016, 45% of the account alone.

manual_trade._ticket_leverage offers 1 and every multiplier on the
instrument's LIVE list that clears every gate a typed number meets (the
bots' judge_order_leverage: the switch, the class ceiling, the own book;
the instrument's own entry: the LIVE list and the stop band), the highest
by default. The preview stamps the ticket with it (the pool counts
notional / L), execute judges it once more at the stop actually sent and
sends it, and the row records it. The size never moves: the risk is the
stop's.

Run with:  python manage.py test tests.test_manual_ticket_leverage
"""
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase

from tests.test_take_trade_live import (ROUTER, _arm_live, _components_on,
                                        _fake_live_client, _quote, _signal)

ADAPTER = "bot_program.engine.capabilities.adapter_key"
CAPABLE = "bot_program.engine.capabilities.has_capability"
JUDGE = "bot_program.asset_engine.base.judge_order_leverage"
INSTRUMENT = ("bot_program.asset_engine.base.AssetBot."
              "_instrument_leverage_check")
TICKET = "bot_program.manual_trade._ticket_leverage"


def _client(listed=(1, 2, 5, 10, 20, 30)):
    client = MagicMock(name="etoro_like")
    client.settlement_for.return_value = "cfd"
    client.leverage_values.return_value = list(listed)
    return client


def _judge(ceiling=20):
    def judge(proxy, icls, carrier, pick=None):
        lev = proxy.extras["leverage"]
        if lev > ceiling:
            return None, f"at {lev}x: past the {ceiling}x ceiling"
        return lev, ""
    return judge


class TheChoicesTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("lev_c",
                                                        password="x")

    def setUp(self):
        from bot_program.asset_engine.base import make_bot
        from bot_program.manual_trade import manual_config_for
        self.cfg = manual_config_for(self.user, "forex")
        self.bot = make_bot(self.cfg)

    def _ask(self, asked=None, *, carrier="etoro", band=lambda lev: "",
             listed=(1, 2, 5, 10, 20, 30)):
        from bot_program.manual_trade import _ticket_leverage
        with patch(ADAPTER, return_value=carrier), \
                patch(CAPABLE, return_value=True), \
                patch(JUDGE, side_effect=_judge(20)), \
                patch(INSTRUMENT, side_effect=lambda c, s, side, lev, p, st:
                      band(lev)), \
                patch.object(type(self.bot), "_instrument_class",
                             return_value="forex"):
            return _ticket_leverage(self.bot, self.cfg, _client(listed),
                                    "EURUSD", "BUY", 1.13, 1.12, asked=asked)

    def test_the_default_is_the_highest_every_gate_allows(self):
        out = self._ask()
        self.assertTrue(out["control"])
        self.assertEqual(out["choices"], [1, 2, 5, 10, 20])
        self.assertEqual((out["max"], out["chosen"]), (20, 20))
        self.assertEqual(out["error"], "")

    def test_the_operators_pick_is_taken(self):
        self.assertEqual(self._ask(5)["chosen"], 5)
        self.assertEqual(self._ask("10")["chosen"], 10)
        self.assertEqual(self._ask(1)["chosen"], 1)

    def test_a_pick_that_is_not_open_is_refused_naming_the_choices(self):
        out = self._ask(30)
        self.assertIn("30x is not open for EURUSD BUY at this stop — choose "
                      "one of [1, 2, 5, 10, 20]", out["error"])
        self.assertIn("nothing was sent", out["error"])
        self.assertIn("whole number", self._ask("2.5")["error"])
        self.assertIn("whole number", self._ask("abc")["error"])

    def test_the_stop_band_closes_the_highest(self):
        out = self._ask(band=lambda lev: ("the stop is past the band"
                                          if lev > 5 else ""))
        self.assertEqual(out["choices"], [1, 2, 5])
        self.assertEqual(out["chosen"], 5)

    def test_nothing_above_one_says_why(self):
        out = self._ask(listed=(1,))
        self.assertEqual((out["choices"], out["chosen"]), ([1], 1))
        self.assertIn("carries nothing above 1", out["why"])

    def test_another_carrier_offers_no_control(self):
        out = self._ask(carrier="binance")
        self.assertFalse(out["control"])
        self.assertEqual(out["chosen"], 1)

    def test_a_config_carrying_its_own_key_offers_no_control(self):
        self.cfg.extras = {"leverage": 5}
        out = self._ask()
        self.assertFalse(out["control"])
        self.assertIn("carries extras['leverage']", out["why"])


def _ticket(chosen=5, choices=(1, 2, 5), control=True):
    return {"choices": list(choices), "max": max(choices), "chosen": chosen,
            "why": "", "error": "", "control": control}


class TheLiveTicketTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("lev_t",
                                                        password="x")

    def setUp(self):
        cache.clear()
        self.inst = _quote("BTCUSD", 60000)
        _components_on()
        self.cfg = _arm_live(self.user)

    def test_the_preview_offers_the_control_and_stamps_the_ticket(self):
        from bot_program.manual_trade import preview_take_trade
        with patch(ROUTER, return_value=_fake_live_client()), \
                patch(TICKET, return_value=_ticket()) as asked:
            p = preview_take_trade(self.user, _signal(self.inst), leverage=5)
        self.assertNotIn("error", p, p)
        self.assertEqual(asked.call_args.kwargs["asked"], 5)
        lev = p["leverage"]
        self.assertTrue(lev["adjustable"])
        self.assertEqual((lev["chosen"], lev["max"], lev["choices"]),
                         (5, 5, [1, 2, 5]))
        self.assertIn("5x — eToro locks notional / 5 as margin", lev["note"])

    def test_a_refused_pick_refuses_the_preview(self):
        from bot_program.manual_trade import preview_take_trade
        refused = dict(_ticket(), error="30x is not open — nothing was sent")
        with patch(ROUTER, return_value=_fake_live_client()), \
                patch(TICKET, return_value=refused):
            p = preview_take_trade(self.user, _signal(self.inst), leverage=30)
        self.assertEqual(p["error"], "30x is not open — nothing was sent")

    def test_execute_sends_the_multiplier_and_the_row_records_it(self):
        from bot_program.manual_trade import execute_take_trade
        from bot_program.models import AssetBotTrade
        fake = _fake_live_client()
        with patch(ROUTER, return_value=fake), \
                patch(TICKET, return_value=_ticket()), \
                patch(INSTRUMENT, return_value=""):
            out = execute_take_trade(self.user, _signal(self.inst),
                                     pin_ok=True, leverage=5)
        self.assertNotIn("error", out, out)
        fake.market_order.assert_called_once()
        self.assertEqual(fake.market_order.call_args.kwargs["leverage"], 5)
        row = AssetBotTrade.objects.get(config=self.cfg, symbol="BTCUSD")
        self.assertEqual(row.metadata["leverage"], 5)

    def test_one_x_sends_no_multiplier(self):
        from bot_program.manual_trade import execute_take_trade
        fake = _fake_live_client()
        with patch(ROUTER, return_value=fake), \
                patch(TICKET, return_value=_ticket(chosen=1)):
            out = execute_take_trade(self.user, _signal(self.inst),
                                     pin_ok=True, leverage=1)
        self.assertNotIn("error", out, out)
        self.assertNotIn("leverage", fake.market_order.call_args.kwargs)

    def test_the_band_at_the_stop_sent_is_judged_again(self):
        from bot_program.manual_trade import execute_take_trade
        fake = _fake_live_client()
        with patch(ROUTER, return_value=fake), \
                patch(TICKET, return_value=_ticket()), \
                patch(INSTRUMENT, return_value="the stop is past the band"):
            out = execute_take_trade(self.user, _signal(self.inst),
                                     pin_ok=True, leverage=5)
        self.assertIn("at 5x: the stop is past the band — lower the "
                      "leverage or tighten the stop; nothing was sent",
                      out.get("error", ""))
        fake.market_order.assert_not_called()


class TheBodyTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("lev_b",
                                                        password="x")

    def test_the_body_takes_a_whole_number_or_nothing(self):
        import json

        from django.test import RequestFactory

        from dashboard.views import _parse_trade_body

        def parse(body):
            req = RequestFactory().post("/x", data=json.dumps(body),
                                        content_type="application/json")
            return _parse_trade_body(req)

        self.assertEqual(parse({})[0]["leverage"], None)
        self.assertEqual(parse({"leverage": 20})[0]["leverage"], 20)
        self.assertEqual(parse({"leverage": "5"})[0]["leverage"], 5)
        for bad in (0, 2.5, -1, True, "x"):
            out, err = parse({"leverage": bad})
            self.assertIsNone(out, bad)
            self.assertTrue(err, bad)

    def test_the_popup_offers_the_selector_and_sends_the_pick(self):
        from pathlib import Path

        from django.conf import settings
        src = Path(settings.BASE_DIR, "templates", "base.html").read_text()
        self.assertIn('<select data-role="lev">', src)
        self.assertIn("finish({ relever: Number(levSel.value) });", src)
        self.assertIn("if (choice.leverage != null) body.leverage = "
                      "choice.leverage;", src)
        self.assertIn("{ leverage: choice.relever }", src)
