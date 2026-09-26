"""Margin honesty (Stage 2: E2.1, GAP 2, GAP 3 — 2026-09-27): the gates,
the capital card and the positions page count an eToro row at ITS OWN
multiplier — notional / L, and the FULL notional at 1 — MEASURED 2026-09-23
(used margin 84.8 on 84.8 of exposure at 1x; 42.39 at 2x; doc §2, §5) —
floored at the class table where the table models margin (forex 1/30: a
row stamped 50 still counts 1/30); a class the table settles in full has no
margin model there, so a 5x stock CFD counts a fifth — the venue's number.
Every other carrier keeps the table; a legacy portfolio.Position (no
metadata) keeps it too.

Before this a forex row sent at 1 on eToro was counted at 1/30 by MAX
SINGLE POSITION, concentration and MAX TOTAL EXPOSURE while the venue held
its full notional: /capital/ printed a "free" the next entry could not draw.

Run with:  python manage.py test tests.test_capital_summary_margin
"""
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase

from tests.test_capital_truth import _config, _open, _quote, _user


def _stamp(trade, **meta):
    """Stamp a row the way execute_entry does: metadata["broker"] and,
    when the order carried one, metadata["leverage"]."""
    md = dict(trade.metadata or {})
    md.update(meta)
    trade.metadata = md
    trade.save(update_fields=["metadata"])
    return trade


class CapitalAtWorkTests(SimpleTestCase):

    def test_the_class_table_is_unchanged_without_a_stamp(self):
        from portfolio.risk_gate import capital_at_work
        self.assertAlmostEqual(capital_at_work("forex", 1000), 33.33, places=2)
        self.assertEqual(capital_at_work("stock", 1000), 1000)
        # a multiplier on a carrier that is not eToro reads the table
        self.assertAlmostEqual(capital_at_work("forex", 1000, leverage=5),
                               33.33, places=2)
        self.assertAlmostEqual(capital_at_work("forex", 1000, leverage=5,
                                               carrier="oanda"), 33.33,
                               places=2)

    def test_an_etoro_row_counts_its_own_multiplier(self):
        """None (no key) is 1 at the venue: the full notional. 5 is a
        fifth — on a stock too (the table settles it in full on a cash
        venue; eToro's 5x is a CFD, margin measured at notional / L). 50 on
        forex is the class table's 1/30 — the floor where the table models
        margin, never looser."""
        from portfolio.risk_gate import capital_at_work
        self.assertEqual(capital_at_work("forex", 1000, carrier="etoro"), 1000)
        self.assertEqual(capital_at_work("forex", 1000, carrier="etoro",
                                         leverage=None), 1000)
        self.assertEqual(capital_at_work("forex", 1000, carrier="etoro",
                                         leverage=1), 1000)
        self.assertAlmostEqual(capital_at_work("forex", 1000, carrier="etoro",
                                               leverage=5), 200.0)
        self.assertAlmostEqual(capital_at_work("forex", 1000, carrier="etoro",
                                               leverage=50), 33.33, places=2)
        self.assertAlmostEqual(capital_at_work("stock", 1000, carrier="etoro",
                                               leverage=5), 200.0)
        self.assertEqual(capital_at_work("stock", 1000, carrier="etoro"), 1000)

    def test_a_stamp_past_the_platform_cap_counts_at_the_cap(self):
        """No order here can carry more than MAX_ORDER_LEVERAGE (5): a
        stock row stamped 100 (or 10) is counted at a fifth, never at 1 %
        — a stamp can tighten the count, never loosen it past what the
        platform may send. forex keeps its table floor: 50 is 1/30. The
        cap is the refusal it mirrors: an order at 10 is refused before
        anything is sent, not clamped."""
        from types import SimpleNamespace

        from bot_program.asset_engine.base import (MAX_ORDER_LEVERAGE,
                                                   judge_order_leverage)
        from portfolio.risk_gate import capital_at_work
        self.assertEqual(MAX_ORDER_LEVERAGE, 5)
        lev, why = judge_order_leverage(
            SimpleNamespace(extras={"leverage": 10}), "stock", "etoro")
        self.assertIsNone(lev)
        self.assertIn("past the platform cap of 5x — refused, not clamped",
                      why)
        for lev in (10, 100, "100"):
            with self.subTest(lev=lev):
                self.assertAlmostEqual(capital_at_work(
                    "stock", 1000, carrier="etoro", leverage=lev), 200.0)
        self.assertAlmostEqual(capital_at_work("forex", 1000, carrier="etoro",
                                               leverage=100), 33.33, places=2)

    def test_an_unreadable_or_sub_one_multiplier_is_the_full_notional(self):
        """Unmeasured is not free: a stamp nothing can read counts as 1."""
        from portfolio.risk_gate import capital_at_work
        for bad in ("x", 0, -2, 0.5, "", float("nan"), float("inf")):
            with self.subTest(bad=bad):
                self.assertEqual(capital_at_work("stock", 1000, carrier="etoro",
                                                 leverage=bad), 1000)
        self.assertAlmostEqual(capital_at_work("stock", 1000, carrier="etoro",
                                               leverage="5"), 200.0)


class PnlOnCapitalTests(SimpleTestCase):

    def test_the_second_percentage_follows_the_rows_stamp(self):
        """[GAP 2] An eToro forex row sent at 1 has NO second percentage
        (capital == notional, suppressed at the source); at 5 it is P&L
        over a fifth; the class table stays without a stamp."""
        from portfolio.services import pnl_on_capital_pct
        self.assertIsNone(pnl_on_capital_pct(10, "forex", 1000, leverage=1,
                                             carrier="etoro"))
        self.assertAlmostEqual(pnl_on_capital_pct(10, "forex", 1000,
                                                  leverage=5, carrier="etoro"),
                               5.0)
        self.assertAlmostEqual(pnl_on_capital_pct(10, "forex", 1000), 30.0)
        self.assertIsNone(pnl_on_capital_pct(None, "forex", 1000, leverage=5,
                                             carrier="etoro"))


class ConcentrationCountsTheMultiplierTests(TestCase):

    def setUp(self):
        self.user = _user("conc_lev_u")
        self.fx = _config(self.user, "forex", 10000)

    def test_the_ticket_added_is_counted_at_its_multiplier(self):
        from portfolio.risk_gate import concentration_state
        kw = dict(symbol="EURUSD", side="BUY", asset_class="forex",
                  notional=1000.0, capital_base=10000.0, base_label="pool")
        self.assertAlmostEqual(
            concentration_state(self.user, leverage=5, carrier="etoro",
                                **kw)["adding"], 200.0)
        self.assertAlmostEqual(
            concentration_state(self.user, leverage=1, carrier="etoro",
                                **kw)["adding"], 1000.0)
        self.assertAlmostEqual(concentration_state(self.user, **kw)["adding"],
                               33.33, places=2)

    def test_what_is_held_is_counted_off_each_rows_own_stamp(self):
        from portfolio.risk_gate import concentration_state, symbol_side_exposure
        _stamp(_open(self.fx, "EURUSD", 1000, 1.0), broker="etoro", leverage=1)
        _stamp(_open(self.fx, "EURUSD", 1000, 1.0), broker="etoro", leverage=5)
        _open(self.fx, "EURUSD", 1000, 1.0)            # no stamp: the table
        held = symbol_side_exposure(self.user, "EURUSD", "BUY")
        self.assertAlmostEqual(held["committed"], 1000 + 200 + 33.33, places=2)
        self.assertEqual(held["n"], 3)
        state = concentration_state(
            self.user, symbol="EURUSD", side="BUY", asset_class="forex",
            notional=1000.0, capital_base=10000.0, base_label="pool",
            leverage=5, carrier="etoro")
        self.assertAlmostEqual(state["after"], 1233.33 + 200, places=2)


class CapitalSummaryMarginTests(TestCase):
    """[GAP 2] The pools/used/free the operator reads on /capital/ and the
    headband: an eToro forex row sent at 1 is USED in full."""

    def setUp(self):
        self.user = _user("cap_lev_u")
        self.fx = _config(self.user, "forex", 10000)

    def _used(self):
        from portfolio.services import capital_summary
        cap = capital_summary(self.user)
        return {c["asset_class"]: c for c in cap["classes"]}["forex"]["used"]

    def test_an_etoro_forex_row_at_one_is_used_in_full(self):
        _stamp(_open(self.fx, "EURUSD", 1000, 1.0), broker="etoro", leverage=1)
        self.assertAlmostEqual(self._used(), 1000.0, places=2)

    def test_an_etoro_forex_row_at_five_is_used_at_a_fifth(self):
        _stamp(_open(self.fx, "EURUSD", 1000, 1.0), broker="etoro", leverage=5)
        self.assertAlmostEqual(self._used(), 200.0, places=2)

    def test_an_oanda_stamped_forex_row_keeps_the_table(self):
        _stamp(_open(self.fx, "EURUSD", 1000, 1.0), broker="oanda")
        self.assertAlmostEqual(self._used(), round(1000 / 30.0, 2), places=2)
        _stamp(_open(self.fx, "GBPUSD", 1000, 1.0), broker="etoro")
        self.assertAlmostEqual(self._used(), round(1000 / 30.0, 2) + 1000.0,
                               places=2)


class TheBookAllocatesEachRowsStampTests(TestCase):
    """[GAP 2 — the lens-1 finding, 2026-09-27] The portfolio overview's
    ALLOCATED / free / "% of the book" strip sums _open_book's rows — the
    BOT rows too — through services._capital_at_work: an eToro forex bot
    row sent at 1 is allocated in full (the venue pledges the full
    notional at 1, MEASURED 2026-09-23), at 5 a fifth; an OANDA-stamped
    or unstamped row keeps the table's 1/30."""

    def setUp(self):
        self.user = _user("book_lev_u")
        self.fx = _config(self.user, "forex", 10000, name="book_fx")
        _quote("EURUSD", 1.0, "forex")

    def _allocated(self):
        from portfolio.services import live_book_value
        return live_book_value(self.user).allocated

    def test_an_etoro_forex_row_at_one_is_allocated_in_full(self):
        _stamp(_open(self.fx, "EURUSD", 1000, 1.0), broker="etoro", leverage=1)
        self.assertAlmostEqual(self._allocated(), 1000.0, places=2)

    def test_an_etoro_forex_row_that_recorded_no_multiplier_is_in_full(self):
        _stamp(_open(self.fx, "EURUSD", 1000, 1.0), broker="etoro")
        self.assertAlmostEqual(self._allocated(), 1000.0, places=2)

    def test_an_etoro_forex_row_at_five_is_allocated_a_fifth(self):
        _stamp(_open(self.fx, "EURUSD", 1000, 1.0), broker="etoro", leverage=5)
        self.assertAlmostEqual(self._allocated(), 200.0, places=2)

    def test_an_oanda_stamped_or_unstamped_row_keeps_the_table(self):
        _stamp(_open(self.fx, "EURUSD", 1000, 1.0), broker="oanda")
        _open(self.fx, "EURUSD", 1000, 1.0)
        self.assertAlmostEqual(self._allocated(), 2 * 1000 / 30.0, places=2)


class TheTakeTradeLaneChargesTheTicketTests(TestCase):
    """[the lens-1 finding, 2026-09-27] The TAKE TRADE lane's OWN pool
    arithmetic — the pool check, the funding proposal, MAX SINGLE POSITION
    and the popup's leverage fact — charges the gates' number
    (capital_at_work): a held eToro forex row at 1 in full, and a ticket
    on an eToro-routed forex config in full (the lane sends at 1, and the
    venue pledges the full notional there — MEASURED 2026-09-23); every
    other carrier keeps the table's 1/30."""

    def setUp(self):
        from bot_program.manual_trade import manual_config_for
        self.user = _user("lane_lev_u")
        self.fx = manual_config_for(self.user, "forex")

    def test_a_held_row_is_charged_its_own_stamp(self):
        from bot_program.manual_trade import _trade_capital_use
        at1 = _stamp(_open(self.fx, "EURUSD", 1000, 1.0), broker="etoro",
                     leverage=1)
        at5 = _stamp(_open(self.fx, "EURUSD", 1000, 1.0), broker="etoro",
                     leverage=5)
        oanda = _stamp(_open(self.fx, "EURUSD", 1000, 1.0), broker="oanda")
        bare = _open(self.fx, "EURUSD", 1000, 1.0)
        self.assertAlmostEqual(_trade_capital_use(at1), 1000.0)
        self.assertAlmostEqual(_trade_capital_use(at5), 200.0)
        self.assertAlmostEqual(_trade_capital_use(oanda), 33.33, places=2)
        self.assertAlmostEqual(_trade_capital_use(bare), 33.33, places=2)

    def test_a_typed_size_on_etoro_is_charged_its_full_notional(self):
        """1,000 EURUSD at 1.10 is 1,100 of notional: 36.67 of margin on
        the table (it fits a 100 pool — tests/test_signal_acted_and_sizing
        pins that), 1,100 on eToro at 1 — refused naming both numbers;
        at 5, 220 — still refused. Nothing is clamped."""
        from bot_program.manual_trade import validate_qty_override
        args = dict(asset_class="forex", raw=1000.0, entry=1.10, stop=1.0967,
                    value_per_unit=1.0, available=100.0,
                    round_qty=lambda q, p: round(float(q), 8))
        qty, why = validate_qty_override(self.fx, **args)
        self.assertIsNone(why, why)
        self.assertEqual(qty, 1000.0)
        qty, why = validate_qty_override(self.fx, carrier="etoro", **args)
        self.assertIsNone(qty)
        self.assertIn("ties up $1,100.00 of capital but only $100.00 is free",
                      why)
        qty, why = validate_qty_override(self.fx, carrier="etoro", leverage=5,
                                         **args)
        self.assertIsNone(qty)
        self.assertIn("ties up $220.00 of capital", why)

    def _preview(self, *, etoro):
        from bot_program.manual_trade import preview_take_trade
        from tests.test_take_trade_live import _arm_live, _components_on
        from tests.test_take_trade_live import _quote as _lane_quote
        from tests.test_take_trade_live import _signal
        if etoro:
            from bot_program.models import EtoroAccount
            acct = EtoroAccount.objects.create(
                user=self.user, demo=True, label="Main",
                is_primary_for_forex=True)
            acct.set_credentials("k", "u")
            acct.save()
        _components_on()
        _arm_live(self.user, "forex")
        fx = _lane_quote("EURUSD", 1.10, "forex")
        client = MagicMock(name="live_fx")
        client.ticker.return_value = {"lastPrice": "1.10"}
        with patch("bot_program.engine.broker_router.client_for_symbol",
                   return_value=client):
            return preview_take_trade(self.user, _signal(
                fx, entry=1.10, stop=1.0967, target=1.1066))

    def test_the_preview_on_an_etoro_routed_config_charges_the_notional(self):
        """The carrier broker_name_for_symbol names (the row flagged for
        forex): capital_use IS the notional and the leverage fact reads
        1:1 — margin_fraction 1.0, not the table's 1/30."""
        p = self._preview(etoro=True)
        self.assertNotIn("error", p, p)
        self.assertAlmostEqual(p["capital_use"], p["notional"], places=2)
        self.assertAlmostEqual(p["capital_use_per_unit"],
                               p["notional_per_unit"], places=8)
        self.assertAlmostEqual(p["leverage"]["effective"], 1.0, places=4)
        self.assertAlmostEqual(p["leverage"]["margin_fraction"], 1.0)
        self.assertIn("No leverage", p["leverage"]["note"])

    def test_the_preview_on_any_other_carrier_keeps_the_table(self):
        p = self._preview(etoro=False)
        self.assertNotIn("error", p, p)
        self.assertAlmostEqual(p["capital_use"], round(p["notional"] / 30.0, 2),
                               places=2)
        self.assertAlmostEqual(p["leverage"]["effective"], 30.0, places=4)


class PositionsPageMarginTests(TestCase):
    """[GAP 3] The positions card prints the ROW's multiplier and the
    margin the gate counted — notional over that margin — not the
    class's 30x on every forex row."""

    def setUp(self):
        self.user = _user("pos_lev_u")
        self.client.force_login(self.user)
        self.fx = _config(self.user, "forex", 10000, name="pos_fx")
        _quote("EURUSD", 1.0, "forex")

    def _card(self, symbol):
        resp = self.client.get("/positions/")
        self.assertEqual(resp.status_code, 200)
        for _row, d in resp.context["positions_detailed"]:
            if d["symbol"] == symbol:
                return d
        self.fail(f"{symbol} is not on the page")

    def test_an_etoro_forex_row_at_one_prints_one_and_its_full_notional(self):
        _stamp(_open(self.fx, "EURUSD", 1000, 1.0), broker="etoro", leverage=1)
        d = self._card("EURUSD")
        self.assertEqual(d["leverage"], "1")
        self.assertEqual(d["committed"], "1,000.00")
        self.assertEqual(d["committed_kind"], "margin")

    def test_an_etoro_forex_row_at_five_prints_five_and_a_fifth(self):
        _stamp(_open(self.fx, "EURUSD", 1000, 1.0), broker="etoro", leverage=5)
        d = self._card("EURUSD")
        self.assertEqual(d["leverage"], "5")
        self.assertEqual(d["committed"], "200.00")
        self.assertEqual(d["committed_kind"], "margin")

    def test_an_etoro_forex_row_at_fifty_prints_the_tables_thirty(self):
        _stamp(_open(self.fx, "EURUSD", 1000, 1.0), broker="etoro", leverage=50)
        d = self._card("EURUSD")
        self.assertEqual(d["leverage"], "30")
        self.assertEqual(d["committed"], "33.33")

    def test_an_oanda_stamped_forex_row_still_prints_thirty(self):
        _stamp(_open(self.fx, "EURUSD", 1000, 1.0), broker="oanda")
        d = self._card("EURUSD")
        self.assertEqual(d["leverage"], "30")
        self.assertEqual(d["committed"], "33.33")
        self.assertEqual(d["committed_kind"], "margin")

    def test_an_etoro_stock_row_at_five_carries_margin_not_cash(self):
        stocks = _config(self.user, "stock", 10000, name="pos_st")
        _quote("AAPL", 100.0, "stock")
        _stamp(_open(stocks, "AAPL", 10, 100.0), broker="etoro", leverage=5)
        d = self._card("AAPL")
        self.assertEqual(d["leverage"], "5")
        self.assertEqual(d["committed"], "200.00")
        self.assertEqual(d["committed_kind"], "margin")
        self.assertEqual(d["notional"], "1,000.00")

    def test_a_stock_row_without_a_stamp_is_cash_at_one(self):
        stocks = _config(self.user, "stock", 10000, name="pos_st2")
        _quote("MSFT", 100.0, "stock")
        _open(stocks, "MSFT", 10, 100.0)
        d = self._card("MSFT")
        self.assertEqual(d["leverage"], "1")
        self.assertEqual(d["committed"], "1,000.00")
        self.assertEqual(d["committed_kind"], "cost")

    def test_the_helpers_read_the_stamp_directly(self):
        from dashboard.views import _pos_leverage, _pos_modelled_margin
        meta = {"broker": "etoro", "leverage": 5}
        self.assertEqual(_pos_modelled_margin("stock", 1000.0, meta=meta), 200.0)
        self.assertEqual(_pos_leverage("stock", meta=meta, notional=1000.0), "5")
        self.assertEqual(_pos_leverage("stock", meta=meta), "5")
        self.assertEqual(_pos_leverage("forex", meta={"broker": "etoro"},
                                       notional=1000.0), "1")
        self.assertEqual(_pos_leverage("forex"), "30")
        self.assertIsNone(_pos_modelled_margin("stock", 1000.0))
        self.assertAlmostEqual(_pos_modelled_margin("forex", 1000.0), 33.33,
                               places=2)
