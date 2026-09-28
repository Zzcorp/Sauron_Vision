"""A delayed mark beats no mark — and says which it is.

An IBKR account with no market-data subscription gets error 10089 on every
quote request:

    Requested market data requires additional subscription for API.
    Delayed market data is available.

Every field comes back unset, so `last` is 0 and the manual lane refuses with
"No usable price mark for GLDM — the quote feeds have nothing fresh". True,
and unhelpful: the operator had a funded Gateway logged into a live account, a
contract IBKR had just qualified, and historical bars arriving normally. The
data was available one flag away — `reqMarketDataType(3)`.

WHY IT IS NEVER SILENT. A delayed mark is roughly fifteen minutes old. A
market order still fills at the real price, so the mark is not what gets
traded — but the stop, the target and the quantity that follows from the stop
distance ARE derived from it. A stop computed off a stale mark can be born on
the wrong side of the market. So the payload carries the fact and the dialog
shows it: the doctrine of this codebase is that a number arrives with what it
is, and a price with no provenance beside it is the lie removed everywhere
else in it.

Run with:  python manage.py test tests.test_delayed_mark
"""
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase


class _Tick:
    """An ib_insync Ticker stands in as an attribute bag."""

    def __init__(self, last=0.0, bid=0.0, ask=0.0):
        self.last, self.bid, self.ask = last, bid, ask


def _trader(real, delayed):
    """An IBKRTrader whose reqMktData answers `real` first, `delayed` after
    reqMarketDataType(3) — exactly how IBKR behaves without a subscription."""
    from bot_program.engine.ibkr_client import IBKRTrader

    t = IBKRTrader(timeout=0.1)
    t._connected = True
    t._ib = MagicMock()
    t._ib.isConnected.return_value = True
    t._ib.sleep.return_value = None
    state = {"mode": 1}

    def _set_type(n):
        state["mode"] = n

    t._ib.reqMarketDataType.side_effect = _set_type
    t._ib.reqMktData.side_effect = lambda *a, **k: (
        delayed if state["mode"] == 3 else real)
    return t


class TheDelayedFallbackTests(SimpleTestCase):

    def _ticker(self, real, delayed, symbol="GLDM"):
        t = _trader(real, delayed)
        with patch.object(type(t), "_build_contract",
                          return_value=MagicMock()):
            return t.ticker(symbol), t

    def test_no_subscription_falls_back_and_returns_a_price(self):
        out, _t = self._ticker(_Tick(), _Tick(last=87.65))
        self.assertEqual(float(out["lastPrice"]), 87.65)

    def test_the_fallback_is_labelled_delayed(self):
        out, _t = self._ticker(_Tick(), _Tick(last=87.65))
        self.assertTrue(out["delayed"])

    def test_a_real_time_quote_is_not_labelled_delayed(self):
        out, t = self._ticker(_Tick(last=320.01), _Tick(last=1.0))
        self.assertEqual(float(out["lastPrice"]), 320.01)
        self.assertFalse(out["delayed"])
        t._ib.reqMarketDataType.assert_not_called()

    def test_the_midpoint_still_works_before_any_fallback(self):
        """FX on IDEALPRO has no last trade at all — only a bid and an ask."""
        out, t = self._ticker(_Tick(bid=1.0800, ask=1.0802), _Tick(last=9.9))
        self.assertAlmostEqual(float(out["lastPrice"]), 1.0801, places=4)
        self.assertFalse(out["delayed"])
        t._ib.reqMarketDataType.assert_not_called()

    def test_the_session_is_put_back_on_real_time(self):
        """One unsubscribed symbol must not quietly downgrade every later
        call on a session that other callers share."""
        _out, t = self._ticker(_Tick(), _Tick(last=87.65))
        calls = [c.args[0] for c in t._ib.reqMarketDataType.call_args_list]
        self.assertEqual(calls, [3, 1])

    def test_it_is_restored_even_when_delayed_also_returns_nothing(self):
        _out, t = self._ticker(_Tick(), _Tick())
        calls = [c.args[0] for c in t._ib.reqMarketDataType.call_args_list]
        self.assertEqual(calls[-1], 1, "real time must be restored regardless")

    def test_both_empty_still_yields_a_zero_mark_not_a_crash(self):
        out, _t = self._ticker(_Tick(), _Tick())
        self.assertEqual(float(out["lastPrice"]), 0.0)
        self.assertFalse(out["delayed"])


class TheDialogIsToldTests(SimpleTestCase):
    """Adding the flag to the client is half a fix. The number the operator
    acts on is in the preview payload, and the levels in that payload are
    derived from the mark — so the payload is where the fact has to arrive."""

    def test_the_mark_resolver_reports_it(self):
        import inspect

        from bot_program import manual_trade
        src = inspect.getsource(manual_trade._mark_for)
        self.assertIn('tk.get("delayed")', src)
        self.assertIn("return (price if price > 0 else None), client, delayed",
                      src)

    def test_the_preview_payload_carries_it(self):
        import inspect

        from bot_program import manual_trade
        src = inspect.getsource(manual_trade)
        self.assertIn('"mark_delayed": bool(mark_delayed)', src)

    def test_the_close_path_still_unpacks_correctly(self):
        """The resolver grew a third element; every caller must have followed,
        or the close path raises ValueError at the worst possible moment."""
        import inspect

        from bot_program import manual_trade
        src = inspect.getsource(manual_trade)
        for line in src.splitlines():
            if "= _mark_for(" in line and "def " not in line:
                # LEFT of the "=" only — the call's own arguments carry
                # commas too, which is what made the first version of this
                # assertion count four.
                targets = line.split("= _mark_for(", 1)[0]
                self.assertEqual(targets.count(","), 2,
                                 f"not a 3-tuple unpack: {line.strip()}")
