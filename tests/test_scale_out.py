"""THE SCALE-OUT: half at +1R, the rest to break-even and trailed
(2026-10-04, the operator's list, item 4).

A PAPER bot row whose mark reaches +1R banks half its size at the modelled
fill, once; the remainder rides the break-even and the trail the position
care already runs. The row stays ONE trade: its qty shrinks, the banked
half lives in metadata["scale_out"], the final close adds the banked
money back and grading divides by the ORIGINAL size, so the ledger reads
one blended R. Never a LIVE row — eToro closes a position whole
(UnitsToDeduct accepted and never executed, measured 2026-09-23) — never
the manual lane, never options, never a stock row too small to split in
whole shares. Under the aragorn_scale_out switch, beside Aragorn's own.

Run with:  python manage.py test tests.test_scale_out
"""
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from tests.test_aragorn import _row, _switch
from tests.test_risk_limits_bind import _config, _quote


def _trade(cfg, *, qty="1", entry="100", stop="98", side="BUY",
           paper=True, cls=None, symbol="BTCUSD", meta=None):
    from bot_program.models import AssetBotTrade
    return AssetBotTrade.objects.create(
        config=cfg, asset_class=cls or cfg.asset_class, symbol=symbol,
        side=side, qty=Decimal(qty), entry_price=Decimal(entry),
        stop_loss=Decimal(stop), take_profit=Decimal("110"), status="OPEN",
        paper=paper, rule_name="golden_cross",
        metadata={"initial_stop_loss": float(stop), **(meta or {})})


class TheConstantsTests(SimpleTestCase):

    def test_half_at_one_r_whole_shares_and_the_switch(self):
        from bot_program import position_care as pc
        self.assertEqual((pc.SCALE_OUT_AT_R, pc.SCALE_OUT_FRACTION), (1.0, 0.5))
        self.assertEqual(pc.WHOLE_UNIT_CLASSES, frozenset({"stock", "etf"}))
        self.assertEqual(pc.SCALE_OUT_SWITCH, "aragorn_scale_out")
        from core.platform_control import DEFAULT_COMPONENTS
        entry = next(c for c in DEFAULT_COMPONENTS
                     if c["key"] == "aragorn_scale_out")
        self.assertEqual(entry["category"], "system")
        self.assertLess(len(entry["description"]), 300)
        self.assertIn("Off (default)", entry["description"])

    def test_the_size_to_bank(self):
        from bot_program.position_care import scale_out_qty
        crypto = SimpleNamespace(qty=Decimal("1"), asset_class="crypto")
        self.assertEqual(scale_out_qty(crypto), Decimal("0.5"))
        forex = SimpleNamespace(qty=Decimal("6400"), asset_class="forex")
        self.assertEqual(scale_out_qty(forex), Decimal("3200"))
        self.assertEqual(scale_out_qty(forex, 0.25), Decimal("1600"))
        one_share = SimpleNamespace(qty=Decimal("1"), asset_class="stock")
        self.assertEqual(scale_out_qty(one_share), Decimal(0))
        three = SimpleNamespace(qty=Decimal("3"), asset_class="stock")
        self.assertEqual(scale_out_qty(three), Decimal(1))
        etf = SimpleNamespace(qty=Decimal("7"), asset_class="etf")
        self.assertEqual(scale_out_qty(etf), Decimal(3))
        self.assertEqual(scale_out_qty(crypto, 1.0), Decimal(0))
        self.assertEqual(scale_out_qty(SimpleNamespace(qty=Decimal("0"),
                                                       asset_class="crypto")),
                         Decimal(0))


class ThePlanTests(SimpleTestCase):
    """Entry 100, stop 98: 102 is +1R."""

    def test_the_scale_out_is_asked_at_one_r_once_and_only_when_allowed(self):
        from bot_program.position_care import plan
        p = plan(_row(paper=True), 102.2, scale=True)
        self.assertEqual(p["action"], "hold")
        self.assertEqual(p["scale_out"]["fraction"], 0.5)
        self.assertAlmostEqual(p["scale_out"]["r_now"], 1.1)
        self.assertIn("rest to break-even", p["scale_out"]["why"])
        # the break-even lock still arrives with it
        self.assertEqual(p["care"]["soft_why"], "breakeven")
        # under +1R: nothing
        self.assertNotIn("scale_out", plan(_row(paper=True), 101.8, scale=True))
        # not asked (a live row's caller never asks): nothing
        self.assertNotIn("scale_out", plan(_row(), 102.2))
        # already banked: nothing
        self.assertNotIn("scale_out",
                         plan(_row(paper=True, care={"scaled_out": True}),
                              102.2, scale=True))
        # the manual lane: nothing
        self.assertNotIn("scale_out",
                         plan(_row(paper=True), 102.2, scale=True, manual=True))
        # options: nothing
        self.assertNotIn("scale_out",
                         plan(_row(paper=True, cls="options"), 102.2, scale=True))

    def test_the_peak_does_not_count_only_the_mark_now(self):
        """A half banked at a price the market has left is a fiction: the
        soft stop reads the peak, the scale-out reads the mark."""
        from bot_program.position_care import plan
        p = plan(_row(paper=True, care={"peak": 102.5}), 101.0, scale=True)
        self.assertNotIn("scale_out", p)
        self.assertEqual(p["care"]["soft_why"], "breakeven")

    def test_a_close_wins_over_a_scale_out(self):
        from bot_program.position_care import plan
        # soft stop (break-even 100.2) crossed at 100.1 — a close, no banking
        p = plan(_row(paper=True, care={"peak": 102.5, "soft_stop": 100.2,
                                        "soft_why": "breakeven"}),
                 100.1, scale=True)
        self.assertEqual(p["action"], "close")
        self.assertNotIn("scale_out", p)


class TheBookingTests(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_user("so_u", password="x")
        self.cfg = _config(self.user, symbols=["BTCUSD"])
        _quote("BTCUSD", "102.2")
        from bot_program.asset_engine.base import make_bot
        self.bot = make_bot(self.cfg)

    def _scale(self, trade, price=102.2, fraction=0.5):
        with patch("bot_program.engine.paper_trader.paper_market_shut",
                   return_value=""):
            return self.bot._scale_out_paper(trade, price, fraction,
                                             why="scale-out test")

    def test_half_is_banked_once_and_the_row_shrinks(self):
        from bot_program.asset_engine.risk_levels import paper_fill_price
        t = _trade(self.cfg)
        self.assertTrue(self._scale(t))
        t.refresh_from_db()
        self.assertEqual(t.qty, Decimal("0.5"))
        self.assertEqual(t.status, "OPEN")
        so = t.metadata["scale_out"]
        fill = Decimal(str(paper_fill_price(self.cfg, "BTCUSD", 102.2, "SELL")))
        self.assertEqual(Decimal(so["price"]), fill)
        self.assertEqual(Decimal(so["qty"]), Decimal("0.5"))
        self.assertEqual(Decimal(so["original_qty"]), Decimal("1"))
        self.assertEqual(so["fraction"], 0.5)
        self.assertAlmostEqual(Decimal(so["pnl"]), (fill - 100) * Decimal("0.5"),
                               places=6)
        self.assertAlmostEqual(so["r"], float((fill - 100) / 2), places=3)
        self.assertLess(fill, Decimal("102.2"), "a seller sells down")
        self.assertTrue(t.metadata["care"]["scaled_out"])
        # once
        self.assertFalse(self._scale(t))
        t.refresh_from_db()
        self.assertEqual(t.qty, Decimal("0.5"))

    def test_never_on_a_live_row_a_shut_market_or_an_unsplittable_size(self):
        live = _trade(self.cfg, paper=False)
        self.assertFalse(self._scale(live))
        live.refresh_from_db()
        self.assertEqual((live.qty, "scale_out" in live.metadata),
                         (Decimal("1"), False))
        shut = _trade(self.cfg, symbol="ETHUSD")
        with patch("bot_program.engine.paper_trader.paper_market_shut",
                   return_value="the market is shut"):
            self.assertFalse(self.bot._scale_out_paper(shut, 102.2, 0.5))
        from bot_program.asset_engine.base import make_bot
        stock_cfg = _config(self.user, asset_class="stock", name="s",
                            symbols=["AAPL"])
        one_share = _trade(stock_cfg, symbol="AAPL", cls="stock")
        with patch("bot_program.engine.paper_trader.paper_market_shut",
                   return_value=""):
            self.assertFalse(make_bot(stock_cfg)._scale_out_paper(
                one_share, 102.2, 0.5))

    def test_the_final_close_adds_the_banked_half_and_grades_the_whole(self):
        """Banked +1.1R on half, the rest closed at +0.1R: about +0.6R on the
        original size, one trade, minus the modelled costs."""
        from bot_program.asset_engine.risk_levels import paper_fill_price
        t = _trade(self.cfg)
        self.assertTrue(self._scale(t))
        t.refresh_from_db()
        banked = Decimal(t.metadata["scale_out"]["pnl"])
        with patch("bot_program.engine.paper_trader.paper_market_shut",
                   return_value=""):
            closed = self.bot._close_trade(t, Decimal("100.2"), None,
                                           reason="SL")
        self.assertTrue(closed)
        t.refresh_from_db()
        self.assertEqual(t.status, "CLOSED")
        fill2 = Decimal(str(paper_fill_price(self.cfg, "BTCUSD", 100.2, "SELL")))
        expected = (fill2 - 100) * Decimal("0.5") + banked
        self.assertAlmostEqual(Decimal(str(t.pnl)), expected, places=6)
        # realized_r on the ORIGINAL size (risk 2 x 1), not the half left
        self.assertAlmostEqual(t.realized_r, float(expected) / 2.0, places=3)
        self.assertGreater(t.realized_r, 0.5)
        self.assertLess(t.realized_r, 0.7)

    def test_the_kill_switch_and_the_manual_preview_count_the_banked_half(self):
        from bot_program.engine.kill_switch import _close_asset_trade
        from bot_program.manual_close import preview_close
        t = _trade(self.cfg)
        self.assertTrue(self._scale(t))
        t.refresh_from_db()
        banked = float(t.metadata["scale_out"]["pnl"])
        with patch("bot_program.engine.paper_trader.paper_market_shut",
                   return_value=""):
            prev = preview_close(self.user, t)
        self.assertNotIn("error", prev)
        self.assertGreater(prev["pnl"], banked - 1e-6,
                           "the preview forgot the banked half")
        _close_asset_trade(t, timezone.now())
        t.refresh_from_db()
        self.assertEqual(t.status, "CLOSED")
        self.assertGreater(float(t.pnl), banked - 1e-6)

    def test_grading_reads_the_original_size(self):
        from bot_program.bot_grading import grade_bot_trade
        t = _trade(self.cfg, meta={"scale_out": {"original_qty": "1",
                                                 "pnl": "1.0"}})
        t.qty = Decimal("0.5")
        t.status = "CLOSED"
        t.exit_price = Decimal("100.2")
        t.pnl = Decimal("1.1")           # 0.1 on the half + 1.0 banked
        t.closed_at = timezone.now()
        t.save()
        self.assertTrue(grade_bot_trade(t))
        self.assertAlmostEqual(t.realized_r, 1.1 / 2.0, places=4)


class TheCareTests(TestCase):
    """The care runs the scale-out on a paper bot row, journals it, and
    leaves the row to the rest of the tick."""

    def setUp(self):
        self.user = get_user_model().objects.create_user("so_care", password="x")
        self.cfg = _config(self.user, symbols=["BTCUSD"])
        _switch("aragorn")
        _switch("aragorn_scale_out")
        _quote("BTCUSD", "102.2")
        from bot_program.asset_engine.base import make_bot
        self.bot = make_bot(self.cfg)

    def _care(self, trade, price=102.2):
        from bot_program.position_care import care
        with patch("bot_program.engine.paper_trader.paper_market_shut",
                   return_value=""):
            return care(self.bot, trade, price, None)

    def test_a_paper_row_at_one_r_is_scaled_out_and_journaled(self):
        from bot_program.aragorn_models import AragornAction
        t = _trade(self.cfg)
        self.assertEqual(self._care(t), "", "the row stays with the tick")
        t.refresh_from_db()
        self.assertEqual(t.qty, Decimal("0.5"))
        self.assertTrue(t.metadata["care"]["scaled_out"])
        self.assertEqual(t.metadata["care"]["soft_why"], "breakeven")
        act = AragornAction.objects.get(kind="scale_out")
        self.assertEqual((act.trade_id, act.symbol), (t.id, "BTCUSD"))
        self.assertEqual(Decimal(act.stats["banked_qty"]), Decimal("0.5"))
        self.assertEqual(Decimal(act.stats["remaining_qty"]), Decimal("0.5"))
        # the next tick banks nothing more
        self.assertEqual(self._care(t, 102.5), "")
        t.refresh_from_db()
        self.assertEqual(t.qty, Decimal("0.5"))
        self.assertEqual(AragornAction.objects.filter(kind="scale_out").count(), 1)

    def test_the_switch_off_and_a_live_row_bank_nothing(self):
        from bot_program.aragorn_models import AragornAction
        _switch("aragorn_scale_out", on=False)
        t = _trade(self.cfg)
        self._care(t)
        t.refresh_from_db()
        self.assertEqual(t.qty, Decimal("1"))
        self.assertNotIn("scale_out", t.metadata)
        _switch("aragorn_scale_out")
        live = _trade(self.cfg, paper=False, symbol="ETHUSD")
        _quote("ETHUSD", "102.2")
        with patch("bot_program.position_care._venue_still_holds",
                   return_value=False):
            self._care(live)
        live.refresh_from_db()
        self.assertEqual(live.qty, Decimal("1"))
        self.assertNotIn("scale_out", live.metadata)
        self.assertFalse(AragornAction.objects.filter(kind="scale_out").exists())

    def test_the_manual_lane_is_never_scaled_out(self):
        from bot_program.manual_trade import MANUAL_CONFIG_NAME
        manual = _config(self.user, name=MANUAL_CONFIG_NAME, symbols=[])
        from bot_program.asset_engine.base import make_bot
        t = _trade(manual)
        from bot_program.position_care import care
        with patch("bot_program.engine.paper_trader.paper_market_shut",
                   return_value=""):
            care(make_bot(manual), t, 102.2, None)
        t.refresh_from_db()
        self.assertEqual(t.qty, Decimal("1"))
        self.assertNotIn("scale_out", t.metadata)


class TheWiringTests(SimpleTestCase):

    def test_every_close_path_reads_the_realised_pnl(self):
        import inspect
        from bot_program import manual_close
        from bot_program.asset_engine import base
        from bot_program.engine import kill_switch
        self.assertIn("pnl = self._realised_pnl(trade, price)",
                      inspect.getsource(base.AssetBot._close_trade))
        self.assertIn("bot._realised_pnl(trade, Decimal(str(fill)))",
                      inspect.getsource(manual_close.preview_close))
        self.assertIn("AssetBot.banked_pnl(trade)",
                      inspect.getsource(kill_switch._close_asset_trade))
        from bot_program.asset_engine.forex_bot import ForexBot
        from bot_program.asset_engine.options_bot import OptionsBot
        for cls in (ForexBot, OptionsBot):
            self.assertNotIn("_realised_pnl", cls.__dict__,
                             "the multipliers must never reach the banked half")
