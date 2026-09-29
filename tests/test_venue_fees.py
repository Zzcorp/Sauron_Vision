"""What eToro charges beside the spread, counted at the size sent.

2026-09-29. The cost filter charged a per-class table (10 bps for a crypto
round trip, 5 for a stock) and the venue's quoted spread, whichever was
wider. eToro also takes, MEASURED:
  - 1% of the notional on each side of a crypto trade (the real BTC round
    trip, 2026-09-26: 0.33 on 16.83);
  - 1.00 USD on each side of a stock order, whatever its size (the demo
    AAPL round trips of 2026-09-29: 1.00 on 4 units and on 0.05 units; the
    0.05 round trip cost 1.98 of 16.86).
Neither reaches a quote. A flat fee is a fraction only once the notional
is known, so execute_entry asks the filter again at the size it sends
(AssetBot._venue_fee_refusal) and a trade the fee turns negative-edge
sends nothing.

Run with:  python manage.py test tests.test_venue_fees
"""
import inspect
from unittest import mock

from django.test import SimpleTestCase, TestCase

from tests.test_execution_trust import _cfg, _instrument, _user


class TheFeeTableTests(SimpleTestCase):

    def test_etoro_crypto_is_one_percent_a_side(self):
        from bot_program.asset_engine.risk_levels import venue_fee_fraction
        fee, words = venue_fee_fraction("etoro", "crypto", 45.0)
        self.assertAlmostEqual(fee, 0.02)
        self.assertIn("1%", words)

    def test_an_etoro_stock_pays_a_flat_dollar_a_side(self):
        from bot_program.asset_engine.risk_levels import venue_fee_fraction
        fee, words = venue_fee_fraction("etoro", "stock", 30.0)
        self.assertAlmostEqual(fee, 2.0 / 30.0)
        self.assertIn("1.00 USD on each side", words)
        self.assertIn("2.00 on 30.00", words)
        big, _ = venue_fee_fraction("etoro", "stock", 2000.0)
        self.assertAlmostEqual(big, 0.001, msg="a flat fee shrinks with size")

    def test_the_classes_measured_without_a_fee_charge_nothing(self):
        from bot_program.asset_engine.risk_levels import venue_fee_fraction
        for icls in ("forex", "index", "commodity", "etf", "options", ""):
            self.assertEqual(venue_fee_fraction("etoro", icls, 1000.0),
                             (0.0, ""), icls)

    def test_another_carrier_charges_nothing_here(self):
        from bot_program.asset_engine.risk_levels import venue_fee_fraction
        for carrier in ("ibkr", "saxo", "binance", "paper", "", None):
            self.assertEqual(venue_fee_fraction(carrier, "crypto", 100.0),
                             (0.0, ""), carrier)

    def test_no_notional_is_no_fraction(self):
        from bot_program.asset_engine.risk_levels import venue_fee_fraction
        for notional in (0, -5, None, "x"):
            self.assertEqual(venue_fee_fraction("etoro", "stock", notional),
                             (0.0, ""), notional)

    def test_the_constants_are_the_measured_numbers(self):
        from bot_program.asset_engine import risk_levels
        self.assertEqual(risk_levels.ETORO_CRYPTO_FEE_PER_SIDE, 0.01)
        self.assertEqual(risk_levels.ETORO_STOCK_FEE_USD_PER_SIDE, 1.00)


class TheRefusalAtTheSizeSentTests(TestCase):
    """AssetBot._venue_fee_refusal on the REAL eToro adapter (adapter_key
    reads the class name) and on a carrier the map does not call eToro."""

    def setUp(self):
        self.user = _user("fee_u")

    def _stock_bot(self):
        from bot_program.asset_engine.stock_bot import StockBot
        _instrument("AAPL", "stock")
        return StockBot(_cfg(self.user, "stock", name="FEE STOCK"))

    def _crypto_bot(self):
        from bot_program.asset_engine.crypto_bot import CryptoBot
        _instrument("BTCUSD", "crypto")
        cfg = _cfg(self.user, "crypto", name="FEE BTC")
        cfg.symbols = ["BTCUSD"]
        cfg.save(update_fields=["symbols"])
        return CryptoBot(cfg)

    @staticmethod
    def _etoro():
        from tests.test_etoro_client import _client
        t, _fake = _client([])
        return t

    def test_a_thirty_dollar_stock_position_is_refused_for_its_fee(self):
        """The 150 USD pool's 30 USD position: 2.00 of fees is 6.7% of it,
        more than a 3.6% target can carry."""
        bot = self._stock_bot()
        price = 337.21
        fee, why = bot._venue_fee_refusal(
            self._etoro(), "AAPL", qty=0.089, price=price,
            target=price * 1.036, stop=price * 0.982)
        self.assertAlmostEqual(fee, 2.0 / (0.089 * price), places=6)
        self.assertTrue(why.startswith("planned move 3.60%"), why)
        self.assertIn("1.00 USD on each side", why)
        self.assertLessEqual(len(why), 200)

    def test_a_large_stock_position_carries_the_same_fee(self):
        bot = self._stock_bot()
        price = 337.21
        fee, why = bot._venue_fee_refusal(
            self._etoro(), "AAPL", qty=10, price=price,
            target=price * 1.036, stop=price * 0.982)
        self.assertAlmostEqual(fee, 2.0 / (10 * price), places=8)
        self.assertEqual(why, "")

    def test_a_btc_swing_target_does_not_cover_two_percent(self):
        """A 3.6% 4h target against 0.1% of table plus 2% of eToro fees:
        1.7x the cost, under the 2x the filter asks."""
        bot = self._crypto_bot()
        price = 84000.0
        fee, why = bot._venue_fee_refusal(
            self._etoro(), "BTCUSD", qty=0.0005, price=price,
            target=price * 1.036, stop=price * 0.982)
        self.assertAlmostEqual(fee, 0.02)
        self.assertIn("1% of the notional on each side", why)

    def test_a_btc_target_that_covers_the_fee_goes(self):
        bot = self._crypto_bot()
        price = 84000.0
        fee, why = bot._venue_fee_refusal(
            self._etoro(), "BTCUSD", qty=0.0005, price=price,
            target=price * 1.12, stop=price * 0.98)
        self.assertAlmostEqual(fee, 0.02)
        self.assertEqual(why, "")

    def test_a_carrier_that_is_not_etoro_is_not_charged(self):
        bot = self._stock_bot()
        other = mock.MagicMock(name="IBKRTrader")
        price = 337.21
        self.assertEqual(bot._venue_fee_refusal(
            other, "AAPL", qty=0.089, price=price, target=price * 1.036,
            stop=price * 0.982), (0.0, ""))

    def test_the_charge_already_counted_is_the_base(self):
        """The proposal's charge (table or wider quote) is what the fee is
        added to, never replaced: a measured 1% spread plus the fee."""
        bot = self._stock_bot()
        price = 337.21
        _fee, why_table = bot._venue_fee_refusal(
            self._etoro(), "AAPL", qty=10, price=price,
            target=price * 1.036, stop=price * 0.982)
        _fee, why_wide = bot._venue_fee_refusal(
            self._etoro(), "AAPL", qty=10, price=price,
            target=price * 1.036, stop=price * 0.982,
            charge={"fraction": 0.02})
        self.assertEqual(why_table, "")
        # 2% charged + 2.00 / 3,372.10 of fee = 2.06%: added, not replaced
        self.assertIn("the 2.06% round-trip cost", why_wide)

    def test_the_fee_can_decide_the_net_reward_to_risk(self):
        """A 500 USD position: 2.00 of fees is 0.4%. The gross edge still
        clears 2x, but the net reward:risk passes without the fee (1.92)
        and fails with it (1.40): the fee decided, so the fee refuses."""
        bot = self._stock_bot()
        price = 337.21
        fee, why = bot._venue_fee_refusal(
            self._etoro(), "AAPL", qty=500 / price, price=price,
            target=price * 1.036, stop=price * 0.982)
        self.assertAlmostEqual(fee, 0.004, places=6)
        self.assertTrue(why.startswith("reward:risk falls to 1.40"), why)
        self.assertIn("1.00 USD on each side", why)

    def test_a_widened_stop_is_not_judged_again_here(self):
        """Sizing may widen the stop after the proposal's filter judged the
        levels: at a 35% stop a 3% target fails net reward:risk with no fee
        at all, a trade the lane has always sent. Only the fee's own effect
        is judged here, and a 0.1% fee does not break a 3% gross edge."""
        bot = self._stock_bot()
        price = 100.0
        fee, why = bot._venue_fee_refusal(
            self._etoro(), "AAPL", qty=20, price=price,
            target=price * 1.03, stop=price * 0.65)
        self.assertAlmostEqual(fee, 0.001)
        self.assertEqual(why, "")

    def test_the_operator_switch_that_turns_the_filter_off_turns_this_off(self):
        bot = self._stock_bot()
        bot.cfg.extras = {"use_cost_filter": False}
        price = 337.21
        fee, why = bot._venue_fee_refusal(
            self._etoro(), "AAPL", qty=0.089, price=price,
            target=price * 1.036, stop=price * 0.982)
        self.assertGreater(fee, 0)
        self.assertEqual(why, "")


class TheOrderOfTheLaneTests(SimpleTestCase):

    def test_execute_entry_asks_after_the_proof_gate_and_before_the_floor(self):
        """At the size sent, on the client that carries it, before the
        venue floor, the idempotency id, the multiplier and the POST."""
        from bot_program.asset_engine.base import AssetBot
        src = inspect.getsource(AssetBot.execute_entry)
        self.assertEqual(src.count("self._venue_fee_refusal("), 1)
        order = [src.index(n) for n in ("_etoro_entry_refusal(",
                                        "self._venue_fee_refusal(",
                                        "_venue_size_floor(",
                                        "make_client_order_id(",
                                        "_order_leverage(")]
        self.assertEqual(order, sorted(order), order)
        self.assertIn("return self._skip(symbol, skips.COST_FILTER, _fee_why)",
                      src)
        self.assertIn('entry_meta["venue_fee_fraction"]', src)
