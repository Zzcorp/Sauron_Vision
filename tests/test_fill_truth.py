"""A broker that has filled nothing must say nothing filled.

Two clients answered a market order that had printed ZERO by reporting
the size we ASKED for. IBKR: `str(filled_qty or quantity)` — and `0.0 or
quantity` is `quantity`. OANDA: `fill.get("units", units)` — and `fill`
is `{}` whenever OANDA answers 201 with no orderFillTransaction, which
is what a FOK market order cancelled for liquidity, a halt, or a FIFO
violation looks like.

`broker_filled_qty` in pending_closes states the opposite contract in so
many words: "A reported 0 is therefore 'nothing gone yet', which is
still a very different answer from silence: it says the position is
live." Alpaca has always honoured it and carries a comment explaining
why. IBKR and OANDA were the outliers.

The cost was not cosmetic. A fabricated quantity makes `complete` True
in `resolve_exit_fill`, which short-circuits the `order_still_working`
branch, cancels the resting broker bracket, and books the row CLOSED —
leaving a full-size order still working at the broker against a position
that is still on the account, naked, and scanned by neither
`reconcile_asset` (OPEN/CLOSE_PENDING only) nor the pending-close retry
beat (CLOSE_PENDING only). It also disabled the refusal gate itself:
`_submit_close_or_raise` raises only when `filled <= 0`.

Run with:  python manage.py test tests.test_fill_truth
"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import TestCase


# ── IBKR ─────────────────────────────────────────────────────────────
class _FakeOrder:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def _ibkr(filled, status):
    """A connected IBKRTrader whose placeOrder prints `filled` at `status`."""
    from bot_program.engine.ibkr_client import IBKRTrader
    t = IBKRTrader.__new__(IBKRTrader)
    t.host, t.port, t.client_id = "127.0.0.1", 7497, 1
    t.account_id = "DU111"
    t._connected = True
    t._ib = MagicMock()
    t._ib.isConnected.return_value = True
    t._ib.managedAccounts.return_value = ["DU111"]
    t._ib.bracketOrder.side_effect = AttributeError("plain order path")
    t._ib.reqContractDetails.return_value = [SimpleNamespace(minTick=0.01)]
    t._ib.client = SimpleNamespace(getReqId=lambda: 4242)

    def _place(contract, order):
        order.orderId = 77
        return SimpleNamespace(
            order=order,
            orderStatus=SimpleNamespace(status=status, filled=filled,
                                        avgFillPrice=0.0),
            log=[])

    t._ib.placeOrder.side_effect = _place
    return t


def _order(t, **kw):
    from bot_program.engine import ibkr_client
    with patch.object(ibkr_client, "_ib", MagicMock()), \
            patch.object(t, "_connect", return_value=True), \
            patch.object(t, "_build_contract", return_value=MagicMock()):
        return t.market_order("AAPL", "SELL", 300, **kw)


class IBKRReportsWhatPrintedTests(TestCase):
    def test_a_working_order_that_printed_nothing_reports_zero(self):
        """PreSubmitted with 0 filled is a live order, not a fill. This is
        a market order held pre-open or on a thin book."""
        res = _order(_ibkr(filled=0, status="PreSubmitted"))
        self.assertEqual(float(res["executedQty"]), 0.0)
        self.assertNotEqual(float(res["executedQty"]), 300.0)

    def test_a_submitted_order_that_printed_nothing_reports_zero(self):
        res = _order(_ibkr(filled=0, status="Submitted"))
        self.assertEqual(float(res["executedQty"]), 0.0)

    def test_a_partial_fill_reports_the_partial(self):
        res = _order(_ibkr(filled=120, status="Submitted"))
        self.assertEqual(float(res["executedQty"]), 120.0)

    def test_a_real_fill_is_untouched(self):
        res = _order(_ibkr(filled=300, status="Filled"))
        self.assertEqual(float(res["executedQty"]), 300.0)


class IBKROptionsReportWhatPrintedTests(TestCase):
    """Not opt-in: options and CFDs route to IBKR unconditionally, and a
    thin option book is where an unfilled market order is likeliest."""

    def _opt(self, t):
        from bot_program.engine import ibkr_client
        with patch.object(ibkr_client, "_ib", MagicMock()), \
                patch.object(t, "_connect", return_value=True):
            return t.market_order_option(
                underlying="AAPL", expiry="20261218", strike=200.0,
                right="C", side="SELL", contracts=5)

    def test_an_unfilled_option_close_reports_zero(self):
        res = self._opt(_ibkr(filled=0, status="PreSubmitted"))
        self.assertEqual(float(res["executedQty"]), 0.0)
        self.assertNotEqual(float(res["executedQty"]), 5.0)

    def test_a_filled_option_close_reports_its_contracts(self):
        res = self._opt(_ibkr(filled=5, status="Filled"))
        self.assertEqual(float(res["executedQty"]), 5.0)


# ── OANDA ────────────────────────────────────────────────────────────
def _oanda(payload):
    from bot_program.engine.oanda_client import OANDATrader
    t = OANDATrader("k", "101-004-1-001")
    sess = MagicMock()
    sess.post.return_value = SimpleNamespace(
        status_code=201, text="", raise_for_status=lambda: None,
        json=lambda: payload)
    t._session = sess
    return t


class OANDAReportsWhatPrintedTests(TestCase):
    def test_a_cancelled_fok_reports_zero_not_the_request(self):
        """201 with only an orderCancelTransaction: OANDA accepted the
        order and immediately killed it. Nothing printed."""
        t = _oanda({"orderCreateTransaction": {"id": "9"},
                    "orderCancelTransaction": {"id": "10",
                                               "reason": "FIFO_VIOLATION"}})
        res = t.market_order("EURUSD", "BUY", 100000)
        self.assertEqual(float(res["executedQty"]), 0.0)
        self.assertEqual(res["status"], "PENDING")

    def test_a_real_fill_still_reports_its_units(self):
        t = _oanda({"orderFillTransaction": {"id": "11", "units": "-100000",
                                             "price": "1.0850"}})
        res = t.market_order("EURUSD", "SELL", 100000)
        self.assertEqual(float(res["executedQty"]), 100000.0)
        self.assertEqual(res["status"], "FILLED")


# ── the contract the fabrication broke ───────────────────────────────
class AZeroFillNeverClosesTheRowTests(TestCase):
    """The downstream machinery was always right; it was being lied to."""

    def _trade(self):
        return SimpleNamespace(id=1, qty=300, side="BUY", asset_class="stock",
                               metadata={}, entry_price=100.0)

    def test_resolve_exit_fill_calls_a_zero_fill_incomplete(self):
        from bot_program.pending_closes import resolve_exit_fill
        fill = resolve_exit_fill(
            self._trade(),
            {"executedQty": "0", "avgPrice": "0", "status": "PRESUBMITTED"},
            mark=101.0)
        self.assertFalse(fill["complete"],
                         "a close that printed nothing must not book CLOSED")

    def test_a_full_fill_is_complete(self):
        from bot_program.pending_closes import resolve_exit_fill
        fill = resolve_exit_fill(
            self._trade(),
            {"executedQty": "300", "avgPrice": "101", "status": "FILLED"},
            mark=101.0)
        self.assertTrue(fill["complete"])

    def test_broker_filled_qty_reads_zero_as_a_measurement(self):
        """0 is 'nothing gone yet'; None is 'the broker did not say'."""
        from bot_program.pending_closes import broker_filled_qty
        self.assertEqual(broker_filled_qty({"executedQty": "0"}), 0)
        self.assertIsNone(broker_filled_qty({}))


class TheEntryPathIsUnharmedTests(TestCase):
    """The fix must not cost the way IN anything. The entry only
    overwrites its quantity `if fill_qty > 0`, and it already holds the
    size we asked for — so a truthful 0 books exactly what it booked."""

    def test_the_entry_keeps_the_requested_size_on_a_silent_broker(self):
        import re
        from pathlib import Path

        from django.conf import settings
        src = (Path(settings.BASE_DIR) / "bot_program" / "asset_engine"
               / "base.py").read_text(encoding="utf-8")
        self.assertTrue(
            re.search(r"if fill_qty > 0:\s*\n\s*qty = fill_qty", src),
            "the entry must only adopt a POSITIVE broker quantity")


class NoBrokerFabricatesAFillTests(TestCase):
    """A tripwire on the shape itself, so this cannot come back by a
    different route. `x or requested` is the whole bug."""

    def test_no_client_falls_back_to_the_requested_size(self):
        from pathlib import Path

        from django.conf import settings
        eng = Path(settings.BASE_DIR) / "bot_program" / "engine"
        for name in ("ibkr_client.py", "oanda_client.py", "alpaca_client.py",
                     "binance_client.py"):
            p = eng / name
            if not p.exists():
                continue
            src = p.read_text(encoding="utf-8")
            for bad in ('str(filled_qty or quantity)',
                        'str(trade.orderStatus.filled or contracts)',
                        'fill.get("units", units)'):
                self.assertNotIn(
                    bad, src,
                    f"{name} fabricates a fill quantity: {bad}")
