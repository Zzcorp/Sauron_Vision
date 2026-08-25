"""Every IBKR order says which account it belongs to.

An IB session can manage several accounts; an order with no `account`
field lands on the session DEFAULT — whichever account TWS considers
primary. An unstamped BUY trades the wrong book; an unstamped CLOSE
against the wrong book closes nothing and OPENS a position there. Both
order paths (kill-switch closes route through them) stamp
order.account from the trader's account_id, and a multi-account
session with no account_id is refused, not guessed.

Run with:  python manage.py test tests.test_ibkr_account_binding
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

from django.test import TestCase


def _trader(**kw):
    from bot_program.engine.ibkr_client import IBKRTrader
    return IBKRTrader(timeout=0.1, **kw)


class AccountBindingTests(TestCase):
    def test_a_named_account_rides_every_order(self):
        t = _trader(account_id="DU111")
        order = SimpleNamespace()
        self.assertIsNone(t._bind_order_account(order))
        self.assertEqual(order.account, "DU111")

    def test_a_single_account_session_passes(self):
        t = _trader()
        t._ib = MagicMock()
        t._ib.managedAccounts.return_value = ["DU111"]
        order = SimpleNamespace()
        self.assertIsNone(t._bind_order_account(order))

    def test_a_multi_account_session_without_a_name_is_refused(self):
        t = _trader()
        t._ib = MagicMock()
        t._ib.managedAccounts.return_value = ["DU111", "DU222"]
        refusal = t._bind_order_account(SimpleNamespace())
        self.assertIn("ambiguous_account", refusal)

    def test_an_unreadable_account_list_fails_open_loudly(self):
        """Every current deployment is single-account; bricking them on
        a flaky library call would strand real exposure. Loud, not
        silent."""
        t = _trader()
        t._ib = MagicMock()
        t._ib.managedAccounts.side_effect = RuntimeError("socket hiccup")
        with self.assertLogs("bot_program.engine.ibkr_client",
                             level="WARNING"):
            self.assertIsNone(t._bind_order_account(SimpleNamespace()))

    def test_market_order_refuses_before_placing(self):
        """The refusal must arrive BEFORE placeOrder — a rejected dict
        after the wire call would be a receipt for damage done."""
        from bot_program.engine import ibkr_client
        t = _trader()
        t._connected = True
        t._ib = MagicMock()
        t._ib.isConnected.return_value = True
        t._ib.managedAccounts.return_value = ["DU111", "DU222"]
        fake_mod = MagicMock()
        fake_mod.MarketOrder.return_value = SimpleNamespace()
        from unittest.mock import patch
        with patch.object(ibkr_client, "_ib", fake_mod), \
                patch.object(t, "_connect", return_value=True), \
                patch.object(t, "_build_contract",
                             return_value=MagicMock()):
            out = t.market_order("AAPL", "BUY", 1)
        self.assertEqual(out["status"], "REJECTED")
        self.assertIn("ambiguous_account", out["raw"]["reason"])
        t._ib.placeOrder.assert_not_called()

    def test_every_order_path_is_bound_before_it_places(self):
        """Paired counts, not a fixed 2: a future order path that calls
        placeOrder without the binder must FAIL this suite, not slip
        past a stale count. And in every method that places, the binder
        comes first."""
        from pathlib import Path

        from django.conf import settings
        src = (Path(settings.BASE_DIR) / "bot_program" / "engine"
               / "ibkr_client.py").read_text(encoding="utf-8")
        self.assertEqual(src.count("self._bind_order_account(order)"),
                         src.count("self._ib.placeOrder("))
        for seg in src.split("def ")[1:]:
            if "self._ib.placeOrder(" not in seg:
                continue
            self.assertLess(seg.index("_bind_order_account"),
                            seg.index("self._ib.placeOrder("), seg[:40])

    def test_the_options_order_refuses_before_placing_too(self):
        from unittest.mock import patch

        from bot_program.engine import ibkr_client
        t = _trader()
        t._connected = True
        t._ib = MagicMock()
        t._ib.isConnected.return_value = True
        t._ib.managedAccounts.return_value = ["DU111", "DU222"]
        fake_mod = MagicMock()
        fake_mod.Option.return_value = MagicMock()
        fake_mod.MarketOrder.return_value = SimpleNamespace()
        with patch.object(ibkr_client, "_ib", fake_mod), \
                patch.object(t, "_connect", return_value=True):
            out = t.market_order_option("AAPL", 180.0, "2026-06-19",
                                        "C", "SELL", 1)
        self.assertEqual(out["status"], "REJECTED")
        self.assertIn("ambiguous_account", out["raw"]["reason"])
        t._ib.placeOrder.assert_not_called()

    def test_a_dead_order_comes_back_rejected_not_pending(self):
        """TWS rejections say Cancelled/Inactive, never REJECTED — raw,
        they booked a full-size phantom live fill at the pre-order
        ticker. The boundary normalizes them, and the consumers'
        existing REJECTED checks (base.py, options_bot) now include the
        dead vocabulary too."""
        from pathlib import Path
        from unittest.mock import patch

        from django.conf import settings

        from bot_program.engine import ibkr_client
        t = _trader(account_id="DU111")
        t._connected = True
        t._ib = MagicMock()
        t._ib.isConnected.return_value = True
        dead_trade = SimpleNamespace(
            order=SimpleNamespace(orderId=7),
            orderStatus=SimpleNamespace(status="Cancelled", filled=0,
                                        avgFillPrice=0),
            log=[SimpleNamespace(message="account DU111 rejected")],
        )
        t._ib.placeOrder.return_value = dead_trade
        fake_mod = MagicMock()
        fake_mod.MarketOrder.return_value = SimpleNamespace()
        with patch.object(ibkr_client, "_ib", fake_mod), \
                patch.object(t, "_connect", return_value=True), \
                patch.object(t, "_build_contract",
                             return_value=MagicMock()):
            out = t.market_order("AAPL", "BUY", 3)
        self.assertEqual(out["status"], "REJECTED")
        self.assertEqual(out["executedQty"], "0")
        self.assertIn("broker_rejected", out["raw"]["reason"])
        self.assertIn("account DU111 rejected", out["raw"]["reason"])
        base = Path(settings.BASE_DIR)
        engine = (base / "bot_program" / "asset_engine"
                  / "base.py").read_text(encoding="utf-8")
        self.assertIn('"INACTIVE", "EXPIRED"', engine)
        opt_bot = (base / "bot_program" / "asset_engine"
                   / "options_bot.py").read_text(encoding="utf-8")
        self.assertIn('"REJECTED", "DUPLICATE", "CANCELLED",', opt_bot)
