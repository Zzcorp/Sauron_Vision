"""The reward:risk warning on the TAKE TRADE ticket (2026-10-02).

The week's live book: five tickets taken by hand from an instrument view,
-1.98R between them. One, EURUSD, risked 1.7% to make 0.6% — a ticket that
must win 73% of the time to stand still. The operator asked for a guard
that warns and leaves the last choice to them ("juste avertissant, laissant
last choice to user"):

  - manual_trade.reward_risk_advisory: the ratio, gross of costs, from the
    entry, and the win rate it needs to break even;
  - the preview carries it (`reward_risk`) and the threshold the popup
    judges by (`levels.reward_risk_warn`);
  - the popup re-judges it live as the levels move, says so in a warning
    block and on the button ("... ANYWAY"), and never disables the button
    for it;
  - `_execute` records the ratio of the levels actually SENT on the trade
    (`reward_risk_at_entry`), so a review can ask whether tickets taken
    past it paid.

Run with:  python manage.py test tests.test_reward_risk_warning
"""
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

from bot_program.manual_trade import REWARD_RISK_WARN, reward_risk_advisory


# The fixtures of tests/test_take_trade.py, copied rather than imported:
# importing that module would put its TestCase classes in this namespace
# and the loader would run them twice.
def _quote(symbol, last, asset_class):
    from decimal import Decimal
    from instruments.models import Instrument
    from market_data.models import LiveQuote
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class})
    LiveQuote.objects.update_or_create(
        instrument=inst, defaults={"last": Decimal(str(last)),
                                   "source": "binance_public"})
    return inst


def _signal(inst, *, entry, stop, target):
    from decimal import Decimal
    from signals.models import Signal
    return Signal.objects.create(
        instrument=inst, signal_type="technical", direction="bullish",
        urgency="high", title=f"{inst.symbol} bullish", description="d",
        rule_name="test_rule", score=0.8, sub_scores={},
        price_at_signal=Decimal(str(entry)),
        suggested_entry=Decimal(str(entry)),
        suggested_stop=Decimal(str(stop)),
        suggested_target=Decimal(str(target)), is_active=True)


class TheRatioTests(SimpleTestCase):

    def test_the_eurusd_ticket_is_flagged_with_its_arithmetic(self):
        """#124: entry 1.12946, stop 1.11, target 1.13656642."""
        adv = reward_risk_advisory("BUY", 1.12946, 1.11, 1.13656642)
        self.assertFalse(adv["ok"])
        self.assertAlmostEqual(adv["ratio"], 0.3652, places=3)
        self.assertAlmostEqual(adv["breakeven_win_rate"], 0.7325, places=3)
        self.assertIn("risks 1.72% to make 0.63%", adv["reason"])
        self.assertIn("reward:risk 0.37", adv["reason"])
        self.assertIn("win 73% of the time just to break even",
                      adv["reason"])

    def test_a_sell_is_measured_the_other_way(self):
        adv = reward_risk_advisory("SELL", 100.0, 102.0, 99.0)
        self.assertFalse(adv["ok"])
        self.assertAlmostEqual(adv["ratio"], 0.5)
        ok = reward_risk_advisory("SELL", 100.0, 102.0, 95.0)
        self.assertTrue(ok["ok"])
        self.assertAlmostEqual(ok["ratio"], 2.5)
        self.assertEqual(ok["reason"], "")

    def test_one_to_one_is_not_warned(self):
        adv = reward_risk_advisory("BUY", 100.0, 98.0, 102.0)
        self.assertEqual(adv["ratio"], 1.0)
        self.assertTrue(adv["ok"])
        self.assertEqual(adv["threshold"], REWARD_RISK_WARN)

    def test_no_risk_is_no_ratio_and_no_warning(self):
        adv = reward_risk_advisory("BUY", 100.0, 100.0, 105.0)
        self.assertTrue(adv["ok"])
        self.assertIsNone(adv["ratio"])

    def test_a_target_on_the_losing_side_counts_as_no_reward(self):
        adv = reward_risk_advisory("BUY", 100.0, 98.0, 99.0)
        self.assertEqual(adv["ratio"], 0.0)
        self.assertFalse(adv["ok"])


class ThePreviewCarriesItTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("rr_u", password="x")

    def setUp(self):
        self.inst = _quote("EURUSD", "1.1000", asset_class="forex")

    def _preview_with(self, *, stop, target):
        from bot_program.manual_trade import _preview
        sig = _signal(self.inst, entry="1.1000", stop=stop, target=target)
        p = _preview(self.user, self.inst, "BUY", signal=sig)
        if "error" in p:
            self.skipTest(f"no forex preview in this environment: {p}")
        return p

    def test_a_ticket_that_risks_more_than_it_can_make_is_warned(self):
        p = self._preview_with(stop="1.0900", target="1.1050")
        self.assertFalse(p["reward_risk"]["ok"])
        self.assertLess(p["reward_risk"]["ratio"], 1.0)
        self.assertIn("break even", p["reward_risk"]["reason"])
        self.assertEqual(p["levels"]["reward_risk_warn"], REWARD_RISK_WARN)

    def test_but_it_is_a_warning_and_not_a_refusal(self):
        """The operator's whole ask. If this ever errors, the warning has
        started deciding for them."""
        p = self._preview_with(stop="1.0900", target="1.1050")
        self.assertNotIn("error", p)
        self.assertGreater(p["qty"], 0)

    def test_healthy_levels_are_not_warned(self):
        p = self._preview_with(stop="1.0900", target="1.1300")
        self.assertTrue(p["reward_risk"]["ok"])
        self.assertGreater(p["reward_risk"]["ratio"], 2.0)
        self.assertEqual(p["reward_risk"]["reason"], "")

    def test_it_is_measured_from_the_fill_the_popup_quotes(self):
        p = self._preview_with(stop="1.0900", target="1.1050")
        expected = reward_risk_advisory("BUY", p["levels"]["fill"],
                                        p["stop"], p["target"])
        self.assertEqual(p["reward_risk"], expected)


class TheTradeRecordsItTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("rr_x", password="x")

    def setUp(self):
        self.inst = _quote("EURUSD", "1.1000", asset_class="forex")

    def _take(self, **overrides):
        from bot_program.manual_trade import execute_take_trade
        from bot_program.models import AssetBotTrade
        sig = _signal(self.inst, entry="1.1000", stop="1.0900",
                      target="1.1050")
        res = execute_take_trade(self.user, sig, **overrides)
        if res.get("error"):
            self.skipTest(f"no forex execution in this environment: {res}")
        return AssetBotTrade.objects.get(pk=res["trade_id"])

    def test_a_ticket_taken_past_the_warning_is_booked_and_recorded(self):
        trade = self._take()
        self.assertEqual(trade.status, "OPEN")
        rec = trade.metadata["reward_risk_at_entry"]
        self.assertFalse(rec["ok"])
        self.assertLess(rec["ratio"], 1.0)

    def test_the_record_judges_the_levels_actually_sent(self):
        """A warning the operator fixed in the popup (target moved out) is
        not recorded as one they took past."""
        trade = self._take(target=1.1300)
        rec = trade.metadata["reward_risk_at_entry"]
        self.assertTrue(rec["ok"], rec)
        self.assertGreater(rec["ratio"], 2.0)
        self.assertEqual(float(trade.take_profit), 1.13)


class ThePopupRendersItTests(SimpleTestCase):
    """A verdict the server computes and the popup never shows is a verdict
    nobody acts on."""

    @staticmethod
    def _base_html():
        from pathlib import Path
        from django.conf import settings
        return (Path(settings.BASE_DIR) / "templates" / "base.html").read_text(
            encoding="utf-8")

    def test_the_warning_is_rendered_live(self):
        html = self._base_html()
        self.assertIn('data-role="rrwarn"', html)
        self.assertIn("YOU RISK MORE THAN YOU", html)
        self.assertIn("L.reward_risk_warn", html)
        self.assertIn("(rrLow ? ' ANYWAY' : '')", html)

    def test_the_button_stays_pressable(self):
        """The last choice is the operator's: the warning never reaches the
        expression that disables the button."""
        html = self._base_html()
        expr = html.split("okBtn.disabled = ", 1)[1].split(";", 1)[0]
        self.assertNotIn("rrLow", expr)
        self.assertNotIn("rewardRisk", expr)
        self.assertIn("lvlWhy || sizeWhy", expr)
