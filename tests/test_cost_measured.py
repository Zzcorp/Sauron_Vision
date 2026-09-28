"""THE COST WAS ASSUMED WHERE THE VENUE HAD ALREADY QUOTED IT.

`DEFAULT_COST_BPS` is one number per asset class and `paper_fill_price`'s own
docstring calls it what it is: "a model, not a measurement". Meanwhile the
venue's quoted spread sat in `tk` three lines above the filter, unread — so
the same EURUSD setup was charged 2 bps at eToro and 2 bps at Saxo.

The measurement may only ever make the charge WIDER. The table is not a spread
estimate for every class: it bundles commission and fees a quote cannot show
("stock 5.0 = commission + typical spread", "crypto 10.0 = taker fee both
sides + spread"). Letting a tight quote pull the charge below the table would
assert those are zero, and nobody measured that. A wide quote, unlike a narrow
one, is never flattering.

Four of these tests exist because a refuter killed the first draft:

  * it did not COMPILE — `charge` was bound in `propose_entry` and read in
    `execute_entry`, so every entry would have raised NameError;
  * `cost_applied_fraction` claimed a haircut on a live config whose stage
    forces paper, where `paper_fill_price` never ran;
  * both Binance clients return `bidPrice`/`askPrice`, so crypto — the class
    with the widest assumption — could never have been measured;
  * and the design denied a second-order effect it has: on the paper path the
    adjusted price feeds both the level maker and the sizer.

And one the refuters missed: bid 0.01 / ask 100 passes every other check and
measures ~198%, which would haircut a paper entry to nothing and then size and
stop off that price. Refused against a bound that already existed in the file.
"""
from decimal import Decimal
from unittest import mock

from django.test import TestCase

from tests.test_execution_trust import _cfg as _live_cfg
from tests.test_execution_trust import _instrument, _signal, _user


def _spread(tick, asset_class=""):
    from bot_program.asset_engine.risk_levels import spread_cost_fraction
    return spread_cost_fraction(tick, asset_class)


class TheMeasurementHasThreeStates(TestCase):

    def test_a_one_pip_major_measures_under_a_basis_point(self):
        self.assertAlmostEqual(
            _spread({"bid": "1.1000", "ask": "1.1001"}, "forex"),
            0.0001 / 1.10005, places=9)

    def test_a_locked_market_is_an_answer_of_zero(self):
        """0.0 is a measurement. It must never be written as unmeasured, and
        unmeasured must never be written as 0."""
        self.assertEqual(_spread({"bid": "1.1", "ask": "1.1"}, "forex"), 0.0)

    def test_a_tick_with_no_sides_is_unmeasured(self):
        """PaperTrader returns neither side."""
        self.assertIsNone(_spread({"lastPrice": "100"}, "stock"))

    def test_the_binance_spelling_is_read_too(self):
        """Both Binance clients hand back the venue's raw payload. Crypto
        carries the widest assumption in the table at 10 bps, so leaving it
        unmeasurable would have been the one class this cannot reach."""
        self.assertAlmostEqual(
            _spread({"bidPrice": "49999", "askPrice": "50001"}, "crypto"),
            2.0 / 50000.0, places=9)

    def test_a_crossed_book_is_unmeasured(self):
        self.assertIsNone(_spread({"bid": "100", "ask": "99"}, "stock"))

    def test_a_non_positive_side_is_unmeasured(self):
        """The shape a Saxo NoAccess quote arrives in."""
        self.assertIsNone(_spread({"bid": "0", "ask": "100"}, "stock"))

    def test_an_unparseable_side_is_unmeasured(self):
        self.assertIsNone(_spread({"bid": "abc", "ask": "1"}, "stock"))

    def test_a_delayed_quote_is_unmeasured(self):
        """A fifteen-minute-old spread is not the spread this order crosses.
        Read through pending_closes.mark_quality, the one normaliser."""
        self.assertIsNone(_spread(
            {"bid": "1.1000", "ask": "1.1001", "delayed_minutes": 15},
            "forex"))
        self.assertIsNone(_spread(
            {"bid": "1.1000", "ask": "1.1001", "delayed": True}, "forex"))

    def test_a_venue_reporting_zero_delay_is_still_measured(self):
        """Saying zero is saying real-time, which is not saying nothing."""
        self.assertIsNotNone(_spread(
            {"bid": "1.1000", "ask": "1.1001", "delayed_minutes": 0},
            "forex"))

    def test_a_broken_quote_is_refused_not_clamped(self):
        """bid 0.01 / ask 100 passes every other check and measures ~198%.
        Unrefused it would haircut a paper entry to nothing, and the levels
        and the size are both derived from that haircut price."""
        self.assertIsNone(_spread({"bid": "0.01", "ask": "100"}, "stock"))

    def test_the_ceiling_is_the_class_own_sane_stop_band(self):
        """No new constant: a round trip wider than the widest stop the
        platform accepts costs more than 1R at that stop. 4.4% is past
        forex's 3% band and inside a stock's 25%."""
        quote = {"bid": "1.10", "ask": "1.15"}
        self.assertIsNone(_spread(quote, "forex"))
        self.assertAlmostEqual(_spread(quote, "stock"), 0.05 / 1.125,
                               places=9)

    def test_a_non_dict_is_unmeasured(self):
        self.assertIsNone(_spread(None, "stock"))
        self.assertIsNone(_spread("1.10/1.15", "stock"))


class TheChargeTakesTheWiderLeg(TestCase):

    def setUp(self):
        self.user = _user("cost_u")
        self.cfg = _live_cfg(self.user, name="COST")

    def _charge(self, tick):
        from bot_program.asset_engine.risk_levels import cost_to_charge
        return cost_to_charge(self.cfg, "AAPL", tick)

    def test_no_measurement_charges_the_table_and_says_so(self):
        from bot_program.asset_engine.risk_levels import COST_SOURCE_ASSUMED
        c = self._charge({"lastPrice": "100"})
        self.assertEqual(c["source"], COST_SOURCE_ASSUMED)
        self.assertIsNone(c["spread"])
        self.assertAlmostEqual(c["fraction"], 0.0005, places=9)

    def test_a_narrow_quote_does_not_lower_the_charge(self):
        """The table bundles commission a quote cannot show. Letting a tight
        spread pull the charge down would assert the commission is zero."""
        from bot_program.asset_engine.risk_levels import COST_SOURCE_ASSUMED
        c = self._charge({"bid": "100.00", "ask": "100.01"})
        self.assertEqual(c["source"], COST_SOURCE_ASSUMED)
        self.assertAlmostEqual(c["fraction"], 0.0005, places=9)
        self.assertIsNotNone(c["spread"],
                             "the measurement is still recorded when it loses")
        self.assertLess(c["spread"], c["assumed"])

    def test_a_wide_quote_raises_the_charge_and_is_labelled_measured(self):
        from bot_program.asset_engine.risk_levels import COST_SOURCE_MEASURED
        c = self._charge({"bid": "100.0", "ask": "100.5"})
        self.assertEqual(c["source"], COST_SOURCE_MEASURED)
        self.assertGreater(c["fraction"], 0.0005)
        self.assertEqual(c["fraction"], c["spread"])
        self.assertIn("wider than", c["note"])

    def test_a_locked_market_is_measured_at_zero_and_changes_no_charge(self):
        c = self._charge({"bid": "100", "ask": "100"})
        self.assertEqual(c["spread"], 0.0)
        self.assertAlmostEqual(c["fraction"], 0.0005, places=9)

    def test_an_explicit_cost_bps_override_still_wins_as_the_assumption(self):
        self.cfg.extras = {"cost_bps": 50.0}
        self.cfg.save(update_fields=["extras"])
        c = self._charge({"bid": "100.00", "ask": "100.01"})
        self.assertAlmostEqual(c["assumed"], 0.005, places=9)
        self.assertAlmostEqual(c["fraction"], 0.005, places=9)


class TheChargeReachesTheRow(TestCase):
    """End to end through propose_entry and execute_entry — the seam whose
    absence made the first draft raise NameError on every single entry."""

    def setUp(self):
        self.user = _user("cost_e2e_u")
        self.inst = _instrument()
        _signal(self.inst)

    def _scan(self, tick, *, mode="live"):
        from bot_program.asset_engine.stock_bot import StockBot
        from bot_program.models import AssetBotTrade
        cfg = _live_cfg(self.user, mode=mode, name="E2E" + mode)
        client = mock.MagicMock()
        client.ticker = mock.MagicMock(return_value=tick)
        client.market_order = mock.MagicMock(return_value={
            "orderId": "o1", "status": "FILLED",
            "avgPrice": tick.get("lastPrice", "100"), "executedQty": "10"})
        client.get_positions = mock.MagicMock(return_value=[])
        with mock.patch("bot_program.engine.broker_router.client_for_symbol",
                        return_value=client):
            StockBot(cfg).scan_symbol("AAPL")
        cfg.refresh_from_db()
        return cfg, AssetBotTrade.objects.filter(config=cfg).first()

    def test_a_live_entry_records_what_it_was_charged(self):
        # 0.2% — four times the 5 bps table, and inside what the gate allows:
        # with stop 1.5% / target 3.0%, min_net_rr 1.5 refuses any charge
        # above 0.3%. A wider quote is refused, which is the test below.
        _cfg, trade = self._scan({"lastPrice": "100", "bid": "100.0",
                                  "ask": "100.2"})
        self.assertIsNotNone(trade, "the entry must actually be placed")
        self.assertEqual(trade.metadata["cost_source"], "measured")
        self.assertGreater(trade.metadata["cost_fraction_charged"], 0.0005)
        self.assertIn("cost_spread_fraction", trade.metadata)

    def test_an_unmeasurable_quote_records_the_assumption(self):
        _cfg, trade = self._scan({"lastPrice": "100"})
        self.assertIsNotNone(trade)
        self.assertEqual(trade.metadata["cost_source"], "assumed")
        self.assertNotIn("cost_spread_fraction", trade.metadata,
                         "absent is the third state; 0.0 means locked")
        self.assertAlmostEqual(trade.metadata["cost_fraction_charged"],
                               0.0005, places=9)

    def test_a_paper_entry_is_haircut_at_the_number_it_records(self):
        """One cost feeds the fill, the gate and the row. Three copies of it
        is how they start disagreeing."""
        cfg, trade = self._scan(
            {"lastPrice": "100", "bid": "100.0", "ask": "100.2"},
            mode="paper")
        self.assertIsNotNone(trade)
        self.assertTrue(trade.metadata["paper_fill"])
        charged = trade.metadata["cost_fraction_charged"]
        self.assertAlmostEqual(trade.metadata["cost_applied_fraction"],
                               round(charged / 2.0, 8), places=9)
        # A buy pays up by half the measured round trip, off the raw ticker.
        self.assertAlmostEqual(float(trade.entry_price),
                               100.0 * (1 + charged / 2.0), places=4)
        self.assertAlmostEqual(trade.metadata["market_price"], 100.0,
                               places=6)

    def test_a_wide_quote_can_refuse_the_entry_and_the_refusal_says_why(self):
        """The provenance travels with the refusal: /signal-surface/ has no
        venue client and still shows the assumed table cost, so when it says a
        setup clears its costs and the bot refuses, the refusal must say the
        venue quoted wider."""
        from bot_program.asset_engine import skips
        cfg, trade = self._scan({"lastPrice": "100", "bid": "99.0",
                                 "ask": "101.0"})
        self.assertIsNone(trade, "a 2% round trip must not be traded")
        recorded = (cfg.extras.get("skips") or {}).get("AAPL", {})
        self.assertEqual(recorded.get("code"), skips.COST_FILTER)
        self.assertIn("measured", recorded.get("detail", ""))

    def test_a_hand_built_candidate_writes_no_cost_keys(self):
        """The desk tests build EntryCandidate by keyword. An absent charge is
        a third state — not a cost of zero and not 'assumed'."""
        from bot_program.asset_engine.candidates import EntryCandidate
        cfg = _live_cfg(self.user, name="HAND")
        cand = EntryCandidate(
            bot=None, cfg_id=cfg.id, user_id=self.user.id, symbol="AAPL",
            instrument_id=self.inst.id, asset_class="stock", venue="live",
            decision=mock.MagicMock(direction="BUY", score=0.9,
                                    rule_name=""),
            price=100.0, market_price=100.0, stop=98.0, target=104.0,
            level_meta={}, cost_reason="", stage={}, sizing={},
            qty_default=10.0, per_unit_risk=2.0, risk_dollars_default=20.0,
            notional_default=1000.0, value_per_unit=1.0)
        self.assertEqual(cand.cost, {})


class ThePaperHaircutIsNotWrittenWhereItDidNotRun(TestCase):
    """`cost_applied_fraction` means APPLIED. On a LIVE config whose rule's
    promotion stage forces paper, `paper` is True and no haircut was taken —
    and the first draft wrote the key anyway."""

    def test_the_key_is_gated_on_the_branch_that_haircuts(self):
        import inspect

        from bot_program.asset_engine.base import AssetBot
        src = inspect.getsource(AssetBot.execute_entry)
        both = src.index("if paper or paper_now:")
        alone = src.index("if paper_now:")
        applied = src.index('entry_meta["cost_applied_fraction"]')
        # paper_fill / market_price stay under the wide branch; the haircut
        # key sits under the narrow one, which opens after it and before the
        # write. No `if paper or paper_now:` may reopen in between.
        self.assertLess(both, alone)
        self.assertLess(alone, applied)
        self.assertNotIn("if paper or paper_now:", src[alone:applied])


class NothingIsResizedOnTheLivePath(TestCase):
    """The measurement can only skip a trade, never size one. On the live path
    the fill is the broker's own, so the charge touches no quantity at all."""

    def setUp(self):
        self.inst = _instrument()
        _signal(self.inst)

    def test_a_wide_quote_does_not_change_a_live_quantity(self):
        """One USER per case: a second pool of the same user on the same
        symbol is correctly refused because the first position is open, and
        that refusal has nothing to do with the cost."""
        from bot_program.asset_engine.stock_bot import StockBot
        from bot_program.models import AssetBotTrade
        sizes = {}
        for label, tick in (("narrow", {"lastPrice": "100", "bid": "100.00",
                                        "ask": "100.01"}),
                            ("wide", {"lastPrice": "100", "bid": "100.0",
                                      "ask": "100.2"})):
            cfg = _live_cfg(_user("cost_size_" + label), name="SZ" + label)
            client = mock.MagicMock()
            client.ticker = mock.MagicMock(return_value=tick)
            client.market_order = mock.MagicMock(return_value={
                "orderId": "o1", "status": "FILLED",
                "avgPrice": "100", "executedQty": "10"})
            client.get_positions = mock.MagicMock(return_value=[])
            with mock.patch(
                    "bot_program.engine.broker_router.client_for_symbol",
                    return_value=client):
                StockBot(cfg).scan_symbol("AAPL")
            trade = AssetBotTrade.objects.filter(config=cfg).first()
            self.assertIsNotNone(trade, label)
            sizes[label] = Decimal(trade.qty)
        self.assertEqual(sizes["narrow"], sizes["wide"])
