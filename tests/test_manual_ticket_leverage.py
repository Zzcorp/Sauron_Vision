"""The live TAKE TRADE ticket carries a leverage, the highest by default
(2026-10-01).

The operator, on learning his live positions were at 1x: "I choose, but I
want the max by default". A hand-taken ticket went at 1x whatever the
account — one EURUSD ticket pledged its full notional, nearly half of the
account alone.

manual_trade._ticket_leverage offers 1 and every multiplier on the
instrument's LIVE list that clears every gate a typed number meets (the
bots' judge_order_leverage: the switch, the class ceiling, the own book;
the instrument's own entry: the LIVE list and the stop band), the highest
by default. The preview stamps the ticket with it (the pool counts
notional / L), execute judges it once more at the stop actually sent and
sends it, and the row records it. The size never moves: the risk is the
stop's.

A SELL too (2026-11-04). The operator: "restaurer achat et vente manuel en
leverage max" (restore manual buy and sell at max leverage). A SELL with no
pick had defaulted, since 2026-10-31, to what its class's short has been
measured at (1x); it now proposes the highest choice exactly like a BUY,
and says in a note when that is above what is measured for shorts.

Run with:  python manage.py test tests.test_manual_ticket_leverage
"""
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase

from tests.test_take_trade_live import (ROUTER, _arm_live, _components_on,
                                        _fake_live_client, _filled_response,
                                        _quote, _signal)

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


def _real_ticket(instrument_class=None, ceiling=20):
    """TICKET patched with the REAL _ticket_leverage (2026-11-04), run with
    an eToro carrier, the leverage_values capability and _judge(ceiling)
    stated for its own call only: the rest of the lane runs on the fake
    live client as everywhere in this file, and the ticket's default is
    the code's own answer, never a dict handed in."""
    from contextlib import ExitStack

    from bot_program import manual_trade
    real = manual_trade._ticket_leverage

    def ticket(bot, *args, **kwargs):
        with ExitStack() as stack:
            stack.enter_context(patch(ADAPTER, return_value="etoro"))
            stack.enter_context(patch(CAPABLE, return_value=True))
            stack.enter_context(patch(JUDGE, side_effect=_judge(ceiling)))
            if instrument_class:
                stack.enter_context(patch.object(
                    type(bot), "_instrument_class",
                    return_value=instrument_class))
            return real(bot, *args, **kwargs)
    return patch(TICKET, side_effect=ticket)


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

    # ── A SHORT DEFAULTS TO THE HIGHEST, LIKE A BUY (2026-11-04) ────────
    # The operator, 2026-11-04: "restaurer achat et vente manuel en
    # leverage max" (restore manual buy and sell at max leverage). From
    # 2026-10-31 a SELL ticket defaulted to the highest choice at or under
    # ETORO_PROVEN_SHORT_LEVERAGE for its class (1 when absent). It now
    # defaults to the highest choice, exactly like a BUY. The choices do
    # not move (the same gates judge them), a pick that is not a choice is
    # still an error, and when the default goes above what is measured
    # for shorts (no eToro short above 1x has been measured: the AAPL and
    # EURUSD SELLs of 2026-10-01 went at 1x) the note says so, as a note.

    def _ask_sell(self, asked=None, *, band=lambda lev: ""):
        from bot_program.manual_trade import _ticket_leverage
        with patch(ADAPTER, return_value="etoro"), \
                patch(CAPABLE, return_value=True), \
                patch(JUDGE, side_effect=_judge(20)), \
                patch(INSTRUMENT, side_effect=lambda c, s, side, lev, p, st:
                      band(lev)), \
                patch.object(type(self.bot), "_instrument_class",
                             return_value="forex"):
            return _ticket_leverage(self.bot, self.cfg, _client(), "EURUSD",
                                    "SELL", 1.13, 1.14, asked=asked)

    def test_a_short_defaults_to_the_highest_like_a_buy(self):
        """Changed 2026-11-04 (the operator's order): this test pinned the
        1x default of 2026-10-31; it now pins the highest, a BUY's."""
        out = self._ask_sell()
        buy = self._ask()
        self.assertEqual(out["choices"], [1, 2, 5, 10, 20])
        self.assertEqual(out["choices"], buy["choices"],
                         "the same gates judge both sides")
        self.assertEqual((out["max"], out["chosen"]), (20, 20))
        self.assertEqual(out["chosen"], buy["chosen"])
        self.assertEqual(out["error"], "")
        self.assertEqual(out["short_measured"], 1)
        self.assertEqual(out["short_note"],
                         "Only 1x is measured for shorts on forex at eToro; "
                         "the ticket proposes the highest, 20x, as the "
                         "operator asked. Pick a lower one if you want.")
        self.assertEqual(self._ask_sell(5)["chosen"], 5,
                         "the operator's pick is taken")
        self.assertEqual(self._ask_sell(1)["chosen"], 1,
                         "a lower pick is taken")
        self.assertNotIn("short_note", buy)

    def test_a_short_pick_that_is_not_open_is_still_refused(self):
        out = self._ask_sell(30)
        self.assertIn("30x is not open for EURUSD SELL at this stop — choose "
                      "one of [1, 2, 5, 10, 20]", out["error"])
        self.assertIn("nothing was sent", out["error"])
        self.assertIn("whole number", self._ask_sell("2.5")["error"])

    def test_the_stop_band_closes_the_highest_short_too(self):
        out = self._ask_sell(band=lambda lev: ("the stop is past the band"
                                               if lev > 5 else ""))
        self.assertEqual(out["choices"], [1, 2, 5])
        self.assertEqual((out["max"], out["chosen"]), (5, 5))
        self.assertIn("the ticket proposes the highest, 5x,",
                      out["short_note"])

    def test_a_short_measured_at_l_still_defaults_to_the_highest(self):
        """Changed 2026-11-04 (the operator's order): this test pinned the
        default at the measured 5x; the measure is now a note only."""
        with patch("bot_program.asset_engine.base."
                   "ETORO_PROVEN_SHORT_LEVERAGE", {"forex": 5}):
            out = self._ask_sell()
        self.assertEqual((out["chosen"], out["short_measured"]), (20, 5))
        self.assertIn("Only 5x is measured for shorts on forex",
                      out["short_note"])
        self.assertEqual(out["short_note"],
                         "Only 5x is measured for shorts on forex at eToro; "
                         "the ticket proposes the highest, 20x, as the "
                         "operator asked. Pick a lower one if you want.")
        for measured in (20, 30):
            with patch("bot_program.asset_engine.base."
                       "ETORO_PROVEN_SHORT_LEVERAGE", {"forex": measured}):
                out = self._ask_sell()
            self.assertEqual(out["chosen"], 20)
            self.assertNotIn("short_note", out, measured)

    def test_the_preview_note_says_it(self):
        """The ticket's leverage note carries the short's words. Changed
        2026-11-04: the ticket is the real _ticket_leverage (eToro's list
        and its gates stated for its own call), so the preview is pinned
        at the highest, 5x, where it was handed a 1x ticket."""
        from tests.test_take_trade_live import _fake_live_client
        from bot_program.manual_trade import _preview
        self.cfg.mode = "live"
        self.cfg.save(update_fields=["mode"])
        _components_on()
        inst = _quote("EURUSD", 1.13, asset_class="forex")
        fake = _fake_live_client()
        fake.ticker.return_value = {"lastPrice": "1.13"}
        fake.settlement_for.return_value = "cfd"
        fake.leverage_values.return_value = [1, 2, 5]
        with patch(ROUTER, return_value=fake), \
                _real_ticket(instrument_class="forex"), \
                patch(INSTRUMENT, return_value=""):
            p = _preview(self.user, inst, "SELL")
        self.assertNotIn("error", p, p)
        self.assertEqual(p["leverage"]["chosen"], 5)
        self.assertIn("Only 1x is measured for shorts on forex",
                      p["leverage"]["note"])
        self.assertIn("Only 1x is measured for shorts on forex at eToro; "
                      "the ticket proposes the highest, 5x, as the operator "
                      "asked. Pick a lower one if you want.",
                      p["leverage"]["note"])


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


#: A bearish BTCUSD signal whose levels bracket the 60,000 mark.
BEAR = {"direction": "bearish", "entry": 60000, "stop": 60900,
        "target": 58200}
#: The FIRST SHORT warning, as short_readback.ticket_advisory words it.
FIRST_SHORT = {"ok": False, "class": "crypto",
               "reason": ("First shorts on crypto at eToro are not measured "
                          "yet. The platform reads the position back right "
                          "after the fill and alarms at once if eToro holds "
                          "something else.")}


class TheSellTicketTests(TestCase):
    """A SELL ticket proposes the highest multiplier, like a BUY
    (2026-11-04; the operator: "restaurer achat et vente manuel en
    leverage max"), on every path that takes one by hand: a bearish
    signal's TAKE TRADE, its send with no pick, and the instrument popup's
    SELL. The real _ticket_leverage decides (_real_ticket); eToro's LIVE
    list on the fake is 1, 2, 5, 10, 20 and 30, and the judge closes 30."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("lev_s",
                                                        password="x")

    def setUp(self):
        cache.clear()
        self.inst = _quote("BTCUSD", 60000)
        _components_on()
        self.cfg = _arm_live(self.user)

    @staticmethod
    def _fake():
        fake = _fake_live_client(_filled_response(side="SELL"))
        fake.settlement_for.return_value = "cfd"
        fake.leverage_values.return_value = [1, 2, 5, 10, 20, 30]
        return fake

    def test_a_bearish_signal_previews_at_the_highest(self):
        from bot_program.manual_trade import preview_take_trade
        with patch(ROUTER, return_value=self._fake()), _real_ticket(), \
                patch(INSTRUMENT, return_value=""):
            p = preview_take_trade(self.user, _signal(self.inst, **BEAR))
        self.assertNotIn("error", p, p)
        self.assertEqual(p["side"], "SELL")
        lev = p["leverage"]
        self.assertTrue(lev["adjustable"])
        self.assertEqual((lev["chosen"], lev["max"], lev["choices"]),
                         (20, 20, [1, 2, 5, 10, 20]))
        self.assertIn("20x — eToro locks notional / 20 as margin", lev["note"])
        self.assertIn("Only 1x is measured for shorts on crypto at eToro; "
                      "the ticket proposes the highest, 20x, as the operator "
                      "asked. Pick a lower one if you want.", lev["note"])

    def test_a_bearish_signal_sent_with_no_pick_goes_at_the_highest(self):
        from bot_program.manual_trade import execute_take_trade
        from bot_program.models import AssetBotTrade
        fake = self._fake()
        with patch(ROUTER, return_value=fake), _real_ticket(), \
                patch(INSTRUMENT, return_value=""):
            out = execute_take_trade(self.user, _signal(self.inst, **BEAR),
                                     pin_ok=True)
        self.assertNotIn("error", out, out)
        fake.market_order.assert_called_once()
        self.assertEqual(fake.market_order.call_args.args[:2],
                         ("BTCUSD", "SELL"))
        self.assertEqual(fake.market_order.call_args.kwargs["leverage"], 20)
        row = AssetBotTrade.objects.get(pk=out["trade_id"])
        self.assertEqual(row.side, "SELL")
        self.assertEqual(row.metadata["leverage"], 20)

    def test_a_lower_pick_is_sent_as_picked(self):
        from bot_program.manual_trade import execute_take_trade
        for pick, sent in ((5, 5), (1, None)):
            cache.clear()
            fake = self._fake()
            with patch(ROUTER, return_value=fake), _real_ticket(), \
                    patch(INSTRUMENT, return_value=""):
                out = execute_take_trade(
                    self.user, _signal(self.inst, **BEAR), pin_ok=True,
                    leverage=pick)
            self.assertNotIn("error", out, out)
            self.assertEqual(
                fake.market_order.call_args.kwargs.get("leverage"), sent,
                pick)
            from bot_program.models import AssetBotTrade
            AssetBotTrade.objects.filter(pk=out["trade_id"]).delete()

    def test_the_instrument_popups_sell_previews_at_the_highest(self):
        from bot_program.manual_trade import preview_asset_trade
        with patch(ROUTER, return_value=self._fake()), _real_ticket(), \
                patch(INSTRUMENT, return_value=""):
            p = preview_asset_trade(self.user, self.inst, "SELL")
            buy = preview_asset_trade(self.user, self.inst, "BUY")
        self.assertNotIn("error", p, p)
        self.assertNotIn("error", buy, buy)
        self.assertEqual((p["leverage"]["chosen"], p["leverage"]["max"]),
                         (20, 20))
        self.assertEqual(p["leverage"]["chosen"], buy["leverage"]["chosen"])

    def test_the_first_short_warning_reads_the_highest_and_stays_a_warning(
            self):
        """The FIRST SHORT ON THIS CLASS AT eTORO box is asked at the
        multiplier the ticket proposes, and stays a warning: the ticket
        previews, the PIN is asked, nothing refuses."""
        from bot_program.manual_trade import preview_take_trade
        with patch(ROUTER, return_value=self._fake()), _real_ticket(), \
                patch(INSTRUMENT, return_value=""), \
                patch("bot_program.short_readback.ticket_advisory",
                      return_value=dict(FIRST_SHORT)) as advisory:
            p = preview_take_trade(self.user, _signal(self.inst, **BEAR))
        self.assertNotIn("error", p, p)
        self.assertEqual(advisory.call_args.kwargs["leverage"], 20)
        self.assertEqual(p["short_advisory"], FIRST_SHORT)
        self.assertTrue(p["requires_pin"])


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
