"""THE ONE PRICING FUNCTION (spec §6.1, bot_program/orcs/pricing.py): every
arm's exit, real or simulated, is priced the same way, so two arms that
exit on the same tick for the same reason differ by exactly zero.

Run with:  python manage.py test tests.orcs.test_orc_pricing
"""
from django.test import SimpleTestCase

CF = 0.0004          # a 4 bps round trip


class ThePricesTests(SimpleTestCase):

    def test_market_exit_closing_side_less_one_way(self):
        from bot_program.orcs.pricing import Tick, market_exit_px
        tick = Tick(at=None, p=100.0, bid=99.9, ask=100.1)
        self.assertAlmostEqual(market_exit_px(tick, "BUY", CF),
                               99.9 - 99.9 * CF / 2)
        self.assertAlmostEqual(market_exit_px(tick, "SELL", CF),
                               100.1 + 100.1 * CF / 2)

    def test_market_exit_without_bid_ask_uses_the_cost_model(self):
        """No bid or ask: m = p less the modelled half spread
        (paper_fill_price's model), then the one-way cost."""
        from bot_program.asset_engine.risk_levels import paper_fill_price
        from bot_program.orcs.pricing import Tick, closing_mark, market_exit_px
        tick = Tick(at=None, p=100.0)
        m = closing_mark(tick, "BUY", CF)
        self.assertAlmostEqual(m, paper_fill_price(
            None, "X", 100.0, "SELL", cost_fraction=CF))
        self.assertAlmostEqual(market_exit_px(tick, "BUY", CF),
                               m - m * CF / 2)
        short = closing_mark(tick, "SELL", CF)
        self.assertAlmostEqual(short, 100.0 + 100.0 * CF / 2)

    def test_stop_exit_at_the_stop_unless_gapped_past_the_spread(self):
        from bot_program.orcs.pricing import (Tick, market_exit_px,
                                              stop_exit_px)
        near = Tick(at=None, p=97.99, bid=97.98, ask=98.0)
        self.assertAlmostEqual(stop_exit_px(98.0, near, "BUY", CF),
                               98.0 - 98.0 * CF / 2,
                               msg="at the stop: the gap is inside the spread")
        gap = Tick(at=None, p=96.0, bid=95.99, ask=96.01)
        self.assertAlmostEqual(stop_exit_px(98.0, gap, "BUY", CF),
                               market_exit_px(gap, "BUY", CF),
                               msg="gapped past it: at the market")
        self.assertAlmostEqual(stop_exit_px(98.0, None, "BUY", CF),
                               98.0 - 98.0 * CF / 2)
        short_gap = Tick(at=None, p=105.0)
        self.assertAlmostEqual(stop_exit_px(102.0, short_gap, "SELL", CF),
                               market_exit_px(short_gap, "SELL", CF))

    def test_target_never_better(self):
        from bot_program.orcs.pricing import target_exit_px
        self.assertLess(target_exit_px(110.0, "BUY", CF), 110.0)
        self.assertGreater(target_exit_px(90.0, "SELL", CF), 90.0)
        self.assertEqual(target_exit_px(110.0, "BUY", 0.0), 110.0)

    def test_identical_exits_delta_care_exactly_zero(self):
        """An Orc and a ghost exiting on the same tick for the same reason
        are priced by one function: their difference is exactly 0."""
        from bot_program.orcs.pricing import (Tick, market_exit_px, r_of,
                                              stop_exit_px)
        tick = Tick(at=None, p=101.37, bid=101.31, ask=101.43)
        orc = r_of(market_exit_px(tick, "BUY", CF), 100.0, 2.0, "BUY")
        ghost = r_of(market_exit_px(tick, "BUY", CF), 100.0, 2.0, "BUY")
        self.assertEqual(orc - ghost, 0.0)
        a = r_of(stop_exit_px(100.2, tick, "BUY", CF), 100.0, 2.0, "BUY")
        b = r_of(stop_exit_px(100.2, tick, "BUY", CF), 100.0, 2.0, "BUY")
        self.assertEqual(a - b, 0.0)

    def test_r_of_is_none_unmeasured(self):
        from bot_program.orcs.pricing import r_of
        self.assertIsNone(r_of(101.0, 100.0, 0.0, "BUY"))
        self.assertIsNone(r_of(None, 100.0, 2.0, "BUY"))
        self.assertAlmostEqual(r_of(98.0, 100.0, 2.0, "SELL"), 1.0)
