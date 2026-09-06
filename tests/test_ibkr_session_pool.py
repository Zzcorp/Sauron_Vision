"""One IBKR session per process and purpose, and the clientId slot that
lets two processes hold one at the same time.

The defect: broker_router built a fresh IBKRTrader — a fresh ib_insync
socket on the SAME trading clientId — on every call, and nothing on the
trading path ever disconnected it. IBKR refuses a second connection on a
held clientId (error 326) rather than evicting the first, so the trader's
own earlier socket refused its later one, five seconds at a time, and the
tick degraded in silence. These tests pin the replacement: a pooled
session per (process, purpose), a leased slot per process, reconnection
when the Gateway drops the socket, and a web request that holds nothing
once it has answered.

Run with:  python manage.py test tests.test_ibkr_session_pool
"""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase

REPO = Path(__file__).resolve().parents[1]


def _reset_pool():
    from bot_program.engine import ibkr_sessions as s
    s._process_sessions.clear()
    s._thread_state.in_request = False
    s._thread_state.sessions = {}
    # The refused-slot memory is process-wide and outlives one test: a slot
    # avoided by an earlier case would silently shift the next case's id.
    s._slot_backoff.clear()
    cache.clear()


class _FakeIB:
    """Just enough of ib_insync.IB for the connect path."""
    instances: list = []
    refuse = False
    connect_attempts = 0

    def __init__(self):
        self.connected = False
        self.clientId = None
        _FakeIB.instances.append(self)

    def connect(self, host, port, clientId, timeout, readonly):
        _FakeIB.connect_attempts += 1
        if _FakeIB.refuse:
            raise ConnectionRefusedError("refused")
        self.clientId = clientId
        self.connected = True

    def isConnected(self):
        return self.connected

    def disconnect(self):
        self.connected = False

    def sleep(self, secs):
        return None


def _fake_ib_module():
    _FakeIB.instances = []
    _FakeIB.refuse = False
    _FakeIB.connect_attempts = 0
    return SimpleNamespace(IB=_FakeIB)


# ═══ 1. One session per (process, purpose) ═════════════════════════════════

class OneSessionPerProcessTests(SimpleTestCase):

    def setUp(self):
        _reset_pool()

    def tearDown(self):
        _reset_pool()

    def test_the_same_key_returns_the_same_trader(self):
        from bot_program.engine.ibkr_sessions import acquire_trader
        a = acquire_trader("ibgateway", 4004, 7, "trade", account_id="DU1")
        b = acquire_trader("ibgateway", 4004, 7, "trade", account_id="DU1")
        self.assertIs(a, b)

    def test_purposes_do_not_share_a_trader_or_an_id(self):
        from bot_program.engine.ibkr_sessions import acquire_trader
        trade = acquire_trader("ibgateway", 4004, 7, "trade")
        data = acquire_trader("ibgateway", 4004, 7, "data")
        self.assertIsNot(trade, data)
        self.assertEqual(trade.client_id, 7)
        self.assertEqual(data.client_id, 107)

    def test_a_re_saved_account_id_reaches_the_open_session(self):
        """An operator who re-saves the account must not keep trading on
        the id the session was opened with."""
        from bot_program.engine.ibkr_sessions import acquire_trader
        a = acquire_trader("ibgateway", 4004, 7, "trade", account_id="DU1")
        b = acquire_trader("ibgateway", 4004, 7, "trade", account_id="U9",
                           paper=False)
        self.assertIs(a, b)
        self.assertEqual(b.account_id, "U9")
        self.assertFalse(b.paper)

    def test_a_data_slot_held_by_another_process_is_skipped(self):
        """Two prefork children must not connect on the same clientId. For
        DATA that is safe to solve with a second slot: nothing it reads is
        scoped to an orderId."""
        from bot_program.engine import ibkr_sessions as s
        cache.set(s._lease_key("ibgateway", 4004, 7, "data", 0),
                  "otherhost:4242:1", 600)
        t = s.acquire_trader("ibgateway", 4004, 7, "data")
        self.assertEqual(t.client_id, 107 + 300)
        self.assertEqual(t._sv_lease["slot"], 1)

    def test_the_trading_id_is_never_slotted(self):
        """An order is visible ONLY to the clientId that placed it, so a
        per-process trading id would make every stored orderId unreadable
        from a sibling process — and the readers cannot tell "not mine"
        from "gone"."""
        from bot_program.engine.ibkr_client import purpose_client_id
        self.assertEqual(purpose_client_id(7, "trade", 0), 7)
        self.assertEqual(purpose_client_id(7, "trade", 3), 7)
        self.assertNotEqual(purpose_client_id(7, "data", 3), 107)

    def test_the_trading_session_is_exclusive_across_processes(self):
        from bot_program.engine import ibkr_sessions as s
        cache.set(s._lease_key("ibgateway", 4004, 7, "trade", 0),
                  "otherhost:4242:1", 600)
        with patch.object(s, "TRADE_LEASE_WAIT_S", 0.0):
            self.assertIsNone(s.acquire_trader("ibgateway", 4004, 7, "trade"))

    def test_no_free_data_slot_refuses_rather_than_colliding(self):
        from bot_program.engine import ibkr_sessions as s
        from bot_program.engine.ibkr_client import IBKRTrader
        for k in range(IBKRTrader.CLIENT_ID_SLOTS):
            cache.set(s._lease_key("ibgateway", 4004, 7, "data", k),
                      f"otherhost:{k}:1", 600)
        self.assertIsNone(s.acquire_trader("ibgateway", 4004, 7, "data"))

    def test_a_cache_that_answered_held_is_believed_over_a_later_fault(self):
        """Falling back to slot 0 after LEARNING it is taken puts two
        sessions on one clientId, which IBKR answers by refusing whichever
        connects second — silently, as a connect timeout."""
        from bot_program.engine import ibkr_sessions as s
        broken = MagicMock()
        broken.add.return_value = False              # slot 0: held
        broken.get.side_effect = [None, RuntimeError("redis died")]
        with patch.object(s, "_cache", return_value=broken):
            self.assertIsNone(s.acquire_trader("ibgateway", 4004, 7, "data"))

    def test_releasing_trade_sessions_leaves_data_pooled(self):
        """The trading id is exclusive so it goes back after every task;
        data reads nothing order-scoped, so reconnecting it would be waste."""
        from bot_program.engine import ibkr_sessions as s
        trade = s.acquire_trader("ibgateway", 4004, 7, "trade")
        data = s.acquire_trader("ibgateway", 4004, 7, "data")
        trade.disconnect = MagicMock()
        data.disconnect = MagicMock()
        key = trade._sv_lease["key"]
        self.assertEqual(s.release_trade_sessions(), 1)
        trade.disconnect.assert_called_once()
        data.disconnect.assert_not_called()
        self.assertIsNone(cache.get(key))            # the lease is free again
        self.assertIn(data, s.held_sessions())
        # And the next caller gets a NEW trading session, not the closed one.
        again = s.acquire_trader("ibgateway", 4004, 7, "trade")
        self.assertIsNot(again, trade)
        self.assertEqual(again.client_id, 7)

    def test_a_refused_data_slot_is_stepped_over_not_retried_forever(self):
        """A clientId whose connect is refused is one another process still
        has a socket on; retrying it forever leaves this process on paper."""
        from bot_program.engine import ibkr_sessions as s
        t = s.acquire_trader("ibgateway", 4004, 7, "data")
        self.assertEqual(t.client_id, 107)
        t._next_connect_at = 1.0          # its connect failed, backoff lapsed
        u = s.acquire_trader("ibgateway", 4004, 7, "data")
        self.assertIsNot(u, t)
        self.assertEqual(u.client_id, 107 + 300)     # the next slot

    def test_the_task_hook_hands_the_trading_session_back(self):
        """One hook, because the next task added would forget a finally —
        and the cost of forgetting is the fleet locked out of its orders."""
        from bot_program.engine import ibkr_sessions as s
        t = s.acquire_trader("ibgateway", 4004, 7, "trade")
        t.disconnect = MagicMock()
        s._on_task_postrun()
        t.disconnect.assert_called_once()
        self.assertEqual(s.held_sessions(), [])

    def test_release_all_disconnects_and_frees_the_slots(self):
        from bot_program.engine import ibkr_sessions as s
        t = s.acquire_trader("ibgateway", 4004, 7, "trade")
        key = t._sv_lease["key"]
        self.assertIsNotNone(cache.get(key))
        t.disconnect = MagicMock()
        n = s.release_all()
        self.assertEqual(n, 1)
        t.disconnect.assert_called_once()
        self.assertIsNone(cache.get(key))
        self.assertEqual(s.held_sessions(), [])

    def test_a_lease_lost_while_idle_drops_the_session(self):
        """A lapsed lease a sibling then took means this process must stop
        using that clientId at once — its open socket is what makes the
        sibling's connects fail."""
        from bot_program.engine import ibkr_sessions as s
        t = s.acquire_trader("ibgateway", 4004, 7, "data")
        key = t._sv_lease["key"]
        t.disconnect = MagicMock()
        cache.set(key, "otherhost:99:1", 600)            # a sibling took it
        t._sv_lease["renewed"] = 0.0                     # the check is due
        u = s.acquire_trader("ibgateway", 4004, 7, "data")
        self.assertIsNot(u, t)
        t.disconnect.assert_called_once()
        self.assertEqual(cache.get(key), "otherhost:99:1")   # not ours to free

    def test_a_trader_whose_connect_failed_is_rebuilt_after_the_backoff(self):
        """Retrying a cached object forever would retry a clientId another
        process may now hold; after the backoff the lease is retaken."""
        from bot_program.engine import ibkr_sessions as s
        t = s.acquire_trader("ibgateway", 4004, 7, "trade")
        t._next_connect_at = 1.0                         # failed, backoff lapsed
        u = s.acquire_trader("ibgateway", 4004, 7, "trade")
        self.assertIsNot(u, t)
        self.assertEqual(u.client_id, 7)                 # same id: exclusive
        v = s.acquire_trader("ibgateway", 4004, 7, "trade")
        self.assertIs(v, u)                              # and stays pooled

    def test_a_lost_cache_falls_back_to_slot_zero(self):
        """Redis blinking must not stop trading — it degrades to the one
        process the platform used to assume."""
        from bot_program.engine import ibkr_sessions as s
        broken = MagicMock()
        broken.add.side_effect = RuntimeError("redis down")
        with patch.object(s, "_cache", return_value=broken):
            t = s.acquire_trader("ibgateway", 4004, 7, "trade")
        self.assertEqual(t.client_id, 7)


# ═══ 2. The socket is asked, not the flag ══════════════════════════════════

class TheSocketIsAskedNotTheFlagTests(SimpleTestCase):

    def _trader(self):
        from bot_program.engine.ibkr_client import IBKRTrader
        return IBKRTrader(host="h", port=4004, client_id=7)

    def test_connect_reuses_an_open_session(self):
        from bot_program.engine import ibkr_client
        with patch.object(ibkr_client, "_IB_AVAILABLE", True), \
             patch.object(ibkr_client, "_ib", _fake_ib_module()):
            t = self._trader()
            self.assertTrue(t._connect())
            self.assertTrue(t._connect())
        self.assertEqual(len(_FakeIB.instances), 1)
        self.assertEqual(_FakeIB.connect_attempts, 1)

    def test_a_dropped_session_is_reconnected(self):
        """The Gateway restarts nightly. The flag still says connected;
        the socket says otherwise, and the socket wins."""
        from bot_program.engine import ibkr_client
        with patch.object(ibkr_client, "_IB_AVAILABLE", True), \
             patch.object(ibkr_client, "_ib", _fake_ib_module()):
            t = self._trader()
            self.assertTrue(t._connect())
            _FakeIB.instances[0].connected = False       # the Gateway dropped us
            self.assertFalse(t.is_connected())
            self.assertTrue(t._connect())
        self.assertEqual(len(_FakeIB.instances), 2)
        self.assertEqual(_FakeIB.connect_attempts, 2)

    def test_a_failed_connect_backs_off(self):
        """A Gateway that is down must not cost the full timeout on every
        open trade of every tick."""
        from bot_program.engine import ibkr_client
        with patch.object(ibkr_client, "_IB_AVAILABLE", True), \
             patch.object(ibkr_client, "_ib", _fake_ib_module()):
            _FakeIB.refuse = True
            t = self._trader()
            self.assertFalse(t._connect())
            self.assertFalse(t._connect())
            self.assertEqual(_FakeIB.connect_attempts, 1)
            t._next_connect_at = 0.0                     # the backoff lapses
            self.assertFalse(t._connect())
            self.assertEqual(_FakeIB.connect_attempts, 2)

    def test_disconnect_lets_the_loop_finish_the_close(self):
        from bot_program.engine import ibkr_client
        with patch.object(ibkr_client, "_IB_AVAILABLE", True), \
             patch.object(ibkr_client, "_ib", _fake_ib_module()):
            t = self._trader()
            self.assertTrue(t._connect())
            ib = _FakeIB.instances[0]
            ib.sleep = MagicMock()
            t.disconnect()
        self.assertFalse(ib.connected)
        ib.sleep.assert_called_once_with(0)
        self.assertIsNone(t._ib)


# ═══ 3. A web request holds nothing between clicks ═════════════════════════

class WebRequestsHoldNothingBetweenClicksTests(SimpleTestCase):

    def setUp(self):
        _reset_pool()

    def tearDown(self):
        _reset_pool()

    def test_a_session_opened_inside_a_request_is_closed_at_its_end(self):
        from bot_program.engine import ibkr_sessions as s
        s._on_request_started()
        t = s.acquire_trader("ibgateway", 4004, 7, "probe")
        key = t._sv_lease["key"]
        self.assertEqual(s._process_sessions, {})
        self.assertEqual(len(s._thread_state.sessions), 1)
        t.disconnect = MagicMock()
        s._on_request_finished()
        t.disconnect.assert_called_once()
        self.assertEqual(s._thread_state.sessions, {})
        self.assertIsNone(cache.get(key))
        self.assertFalse(s._thread_state.in_request)

    def test_the_lifecycle_hooks_are_installed_by_the_app(self):
        from bot_program.engine import ibkr_sessions as s
        self.assertTrue(s._installed["done"])
        s.install_signal_handlers()          # idempotent, never raises


# ═══ 4. The router, the feeds and the probes all use the pool ══════════════

class TheRouterAndTheFeedsUseThePoolTests(TestCase):

    def setUp(self):
        _reset_pool()
        from bot_program.models import IBKRAccount
        self.user = User.objects.create_user("pool_router", password="x")
        self.acct = IBKRAccount.objects.create(
            user=self.user, host="ibgateway", port=4004, client_id=3)
        self.acct.set_credentials("DU777")
        self.acct.save(update_fields=["account_id_enc"])

    def tearDown(self):
        _reset_pool()

    def test_the_router_hands_out_the_pooled_trade_session(self):
        from bot_program.engine.broker_router import _ibkr_client_for
        with patch("bot_program.engine.ibkr_client.is_ibkr_available",
                   return_value=True):
            a = _ibkr_client_for(self.user, None)
            b = _ibkr_client_for(self.user, None)
        self.assertIs(a, b)
        self.assertEqual(a.client_id, 3)
        self.assertEqual(a.account_id, "DU777")

    def test_no_free_slot_falls_back_to_paper(self):
        from bot_program.engine.broker_router import _ibkr_client_for
        from bot_program.engine.paper_trader import PaperTrader
        cfg = SimpleNamespace(mode="live", asset_class="stock", symbols=[],
                              user=self.user, id=0)
        with patch("bot_program.engine.ibkr_client.is_ibkr_available",
                   return_value=True), \
             patch("bot_program.engine.ibkr_sessions.acquire_trader",
                   return_value=None):
            client = _ibkr_client_for(self.user, cfg)
        self.assertIsInstance(client, PaperTrader)

    def test_the_bar_writer_asks_for_the_data_session(self):
        from market_data import bot_bars
        cfg = SimpleNamespace(mode="live", asset_class="stock")
        with patch("bot_program.engine.broker_router.client_for_symbol",
                   return_value=MagicMock()) as router:
            bot_bars._client_for(self.user, "AAPL", cfg)
        self.assertEqual(router.call_args.kwargs.get("purpose"), "data")

    def test_no_caller_builds_an_ibkr_socket_outside_the_pool(self):
        """A site that constructs IBKRTrader itself is a site that opens a
        socket the pool cannot close or keep off a held clientId."""
        for rel in ("bot_program/engine/broker_router.py",
                    "bot_program/ibkr_data_feed.py",
                    "bot_program/tasks.py",
                    "bot_program/reconcile_asset.py",
                    "dashboard/views_admin_hq.py"):
            src = (REPO / rel).read_text(encoding="utf-8")
            self.assertNotIn("IBKRTrader(", src, rel)
            self.assertIn("acquire_trader(", src, rel)

    def test_the_code_no_longer_claims_an_eviction(self):
        """IBKR refuses the newcomer with error 326; it does not evict the
        holder. Three files said the opposite and one said both."""
        src = (REPO / "bot_program/engine/ibkr_client.py").read_text(
            encoding="utf-8")
        self.assertIn("REFUSES the newcomer", src)
        for rel in ("bot_program/tasks.py", "bot_program/reconcile_asset.py"):
            text = (REPO / rel).read_text(encoding="utf-8")
            self.assertIn("326", text, rel)
            self.assertNotIn("EVICT", text, rel)
