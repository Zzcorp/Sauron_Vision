"""A local lock is not a broker failure.

The IBKR trading session is EXCLUSIVE across the whole deployment: an order
is visible only to the clientId that placed it, so every process that needs
to place, read or cancel one has to use the same id, and IBKR allows one
connection per id. A process that loses the race is handed a PaperTrader.

That is safe — every live path refuses to trade through a PaperTrader — but
only if the refusal is not mistaken for "the broker is unreachable". It was:
the pending-close drain counted a lost race as a failed attempt, and twelve
of those (about an hour) flipped a perfectly closable live position to ERROR
with "close it by hand". Nothing had ever been sent, and the broker was
reachable the whole time.

Run with:  python manage.py test tests.test_trade_session_contention
"""
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase


def _reset_pool():
    from bot_program.engine import ibkr_sessions as s
    s._process_sessions.clear()
    s._thread_state.in_request = False
    s._thread_state.sessions = {}
    s._slot_backoff.clear()
    cache.clear()


# ═══ 1. The router says WHY it fell back ═══════════════════════════════════

class TheRouterNamesABusySessionTests(TestCase):

    def setUp(self):
        _reset_pool()
        from bot_program.models import IBKRAccount
        self.user = User.objects.create_user("busy_u", password="x")
        self.acct = IBKRAccount.objects.create(
            user=self.user, host="ibgateway", port=4004, client_id=3)
        self.acct.set_credentials("DU777")
        self.acct.save(update_fields=["account_id_enc"])

    def tearDown(self):
        _reset_pool()

    def _client(self):
        from bot_program.engine.broker_router import _ibkr_client_for
        from bot_program.engine import ibkr_sessions as s
        cache.set(s._lease_key("ibgateway", 4004, 3, "trade", 0),
                  "otherhost:999:1", 600)
        with patch("bot_program.engine.ibkr_client.is_ibkr_available",
                   return_value=True), \
             patch.object(s, "TRADE_LEASE_WAIT_S", 0.0):
            return _ibkr_client_for(self.user, None)

    def test_a_held_session_yields_a_paper_client_marked_busy(self):
        from bot_program.engine.broker_router import session_busy
        from bot_program.engine.paper_trader import PaperTrader
        client = self._client()
        self.assertIsInstance(client, PaperTrader)
        self.assertTrue(session_busy(client))

    def test_a_missing_credential_is_NOT_marked_busy(self):
        """The distinction is the whole point: one means nothing was asked,
        the other means the operator must fix something."""
        from bot_program.engine.broker_router import (_ibkr_client_for,
                                                      session_busy)
        self.acct.account_id_enc = ""
        self.acct.save(update_fields=["account_id_enc"])
        with patch("bot_program.engine.ibkr_client.is_ibkr_available",
                   return_value=True):
            client = _ibkr_client_for(self.user, None)
        self.assertFalse(session_busy(client))


# ═══ 2. The close drain does not spend its budget on a lock ════════════════

class ABusySessionIsNotAFailedAttemptTests(TestCase):

    def setUp(self):
        from instruments.models import Instrument
        from bot_program.models import AssetBotConfig
        Instrument.objects.get_or_create(
            symbol="NVDA", defaults={"name": "NVDA", "asset_class": "stock"})
        self.user = User.objects.create_user("drain_u", password="x")
        self.cfg = AssetBotConfig.objects.create(
            user=self.user, asset_class="stock", name="DRAIN", mode="live",
            symbols=["NVDA"], capital=Decimal("10000"), enabled=True)

    def _pending(self, attempts=0):
        from bot_program.models import AssetBotTrade
        return AssetBotTrade.objects.create(
            config=self.cfg, asset_class="stock", symbol="NVDA", side="BUY",
            qty=Decimal("5"), entry_price=Decimal("100"),
            stop_loss=Decimal("98"), take_profit=Decimal("104"),
            status="CLOSE_PENDING", paper=False,
            metadata={"close_retry_attempts": attempts})

    def _retry(self, trade, *, busy):
        from bot_program.engine.paper_trader import PaperTrader
        from bot_program.pending_closes import retry_trade_close
        paper = PaperTrader(self.cfg)
        if busy:
            from bot_program.engine.broker_router import SESSION_BUSY
            paper._sv_unavailable = SESSION_BUSY
        with patch("bot_program.engine.broker_router.client_for_symbol",
                   return_value=paper):
            return retry_trade_close(trade)

    def test_a_busy_session_costs_no_attempt_and_keeps_the_row_pending(self):
        trade = self._pending(attempts=3)
        self._retry(trade, busy=True)
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSE_PENDING")
        self.assertEqual(trade.metadata["close_retry_attempts"], 3)
        self.assertIn("close_session_busy_since", trade.metadata)

    def test_a_busy_session_can_never_abandon_a_live_position(self):
        """The old behaviour: twelve lost races and the row was ERROR with
        'close it by hand' — while the broker was reachable throughout."""
        from bot_program.pending_closes import MAX_RETRY_ATTEMPTS
        trade = self._pending(attempts=MAX_RETRY_ATTEMPTS - 1)
        for _ in range(4):
            self._retry(trade, busy=True)
            trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSE_PENDING")
        self.assertNotEqual(trade.status, "ERROR")

    def test_a_real_broker_failure_still_counts(self):
        """The guard must not disarm the abandon path it narrows."""
        trade = self._pending(attempts=0)
        self._retry(trade, busy=False)
        trade.refresh_from_db()
        self.assertEqual(int(trade.metadata.get("close_retry_attempts") or 0), 1)

    def test_a_long_stall_reaches_the_operator(self):
        """Not counting it must not mean saying nothing: a drain that can
        never take the session is as stuck as one the broker refuses."""
        from datetime import timedelta

        from django.utils import timezone

        from bot_program.pending_closes import (
            SESSION_BUSY_ALERT_AFTER_MINUTES, _note_session_busy)
        User.objects.create_user("drain_staff", password="x", is_staff=True)
        trade = self._pending()
        old = timezone.now() - timedelta(
            minutes=SESSION_BUSY_ALERT_AFTER_MINUTES + 5)
        trade.metadata = {**trade.metadata,
                          "close_session_busy_since": old.isoformat()}
        trade.save(update_fields=["metadata"])
        _note_session_busy(trade)
        from alerts.models import Notification
        self.assertTrue(Notification.objects.filter(
            title__icontains="busy IBKR session").exists())


# ═══ 3. Read-only callers do not take the trading session ══════════════════

class ReadOnlyCallersUseADataSessionTests(SimpleTestCase):
    """Winning the trading mutex to render a page or refresh a chain would
    starve the tick of the one clientId that can act on an order."""

    def test_the_named_read_only_callers_ask_for_data(self):
        import re
        from pathlib import Path

        from django.conf import settings
        root = Path(settings.BASE_DIR)
        for rel, fn in (
            ("dashboard/views_system_health.py", "client_for_symbol"),
            ("bot_program/tasks.py", "client_for_symbol"),
            ("bot_program/capital_truth.py", "client_for_symbol"),
            ("market_data/bot_bars.py", "client_for_symbol"),
        ):
            src = (root / rel).read_text(encoding="utf-8")
            for call in re.findall(r"client_for_symbol\((?:[^()]|\([^()]*\))*\)",
                                   src, re.S):
                if "def " in call:
                    continue
                self.assertIn('purpose="data"', call,
                              f"{rel}: a read-only call must not take the "
                              f"exclusive trading session: {call[:120]}")


# ═══ 4. The wait does not block the whole process ══════════════════════════

class TheLeaseWaitDoesNotHoldTheProcessLockTests(SimpleTestCase):

    def setUp(self):
        _reset_pool()

    def tearDown(self):
        _reset_pool()

    def test_a_data_session_is_served_while_a_trade_lease_is_waited_on(self):
        """N threads waiting for the trading lease used to cost N x the wait,
        and blocked every unrelated session and every release path with it."""
        import threading

        from bot_program.engine import ibkr_sessions as s
        cache.set(s._lease_key("ibgateway", 4004, 7, "trade", 0),
                  "otherhost:999:1", 600)
        got = {}

        def _waiter():
            got["trade"] = s.acquire_trader("ibgateway", 4004, 7, "trade")

        t = threading.Thread(target=_waiter, daemon=True)
        with patch.object(s, "TRADE_LEASE_WAIT_S", 3.0):
            t.start()
            # While that thread is inside its wait, an unrelated data
            # session must still be obtainable — promptly.
            import time as _t
            _t.sleep(0.3)
            start = _t.monotonic()
            data = s.acquire_trader("ibgateway", 4004, 7, "data")
            elapsed = _t.monotonic() - start
            t.join(timeout=10)
        self.assertIsNotNone(data)
        self.assertLess(elapsed, 1.5, "the data session waited on the "
                                      "trading lease's lock")
        self.assertIsNone(got.get("trade"))
