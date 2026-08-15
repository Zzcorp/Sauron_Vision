"""Tests for the Admin HQ Console additions:
  - AI gate component drives `_apply_risk_gate` (use_ai_check flag)
  - run-now endpoints are superuser-only and POST-only
  - OANDA/Alpaca credential forms create encrypted accounts
  - Position-management loop routes per-symbol via broker_router

Run with:  python manage.py test tests.test_admin_hq
"""
from decimal import Decimal
from unittest.mock import patch, MagicMock

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.utils import timezone


def _superuser(username="hq_admin"):
    u, _ = User.objects.get_or_create(
        username=username, defaults={"is_staff": True, "is_superuser": True},
    )
    u.set_password("x")
    u.is_staff = True
    u.is_superuser = True
    u.save()
    return u


def _seed_components():
    from core.platform_control import seed_components
    seed_components()


# ── AI gate component drives runner ────────────────────────────────────────

class AIGateComponentToggleTests(TestCase):
    def setUp(self):
        _seed_components()
        from instruments.models import Instrument
        self.user = User.objects.create_user(username="bot_ai", password="x")
        self.inst = Instrument.objects.create(symbol="AIGATE", name="AIGATE", asset_class="forex")

    def _set_gate(self, enabled: bool):
        from core.platform_control import PlatformComponent
        c, _ = PlatformComponent.objects.get_or_create(
            key="feature_ai_pretrade_gate",
            defaults={"name": "AI Pre-Trade Sanity Gate", "category": "agent"},
        )
        c.is_enabled = enabled
        c.save()

    @patch("portfolio.risk_gate.evaluate_proposed_trade")
    def test_gate_off_passes_use_ai_check_false(self, mock_eval):
        from bot_program.engine.runner import _apply_risk_gate
        mock_eval.return_value = {"scale": 1.0, "reasons": []}
        self._set_gate(False)
        _apply_risk_gate(self.user, "AIGATE", qty=1.0, price=100.0)
        # First positional + kwargs
        kwargs = mock_eval.call_args.kwargs
        self.assertFalse(kwargs.get("use_ai_check"))

    @patch("portfolio.risk_gate.evaluate_proposed_trade")
    def test_gate_on_passes_use_ai_check_true(self, mock_eval):
        from bot_program.engine.runner import _apply_risk_gate
        mock_eval.return_value = {"scale": 1.0, "reasons": []}
        self._set_gate(True)
        _apply_risk_gate(self.user, "AIGATE", qty=1.0, price=100.0)
        kwargs = mock_eval.call_args.kwargs
        self.assertTrue(kwargs.get("use_ai_check"))


# ── Run-now endpoint authorization ──────────────────────────────────────────

class RunNowAuthorizationTests(TestCase):
    def setUp(self):
        _seed_components()
        self.client = Client()
        self.admin = _superuser()
        self.regular = User.objects.create_user(username="regular", password="x")

    def test_get_method_disallowed(self):
        self.client.force_login(self.admin)
        r = self.client.get("/admin-dashboard/run/signal-scan/")
        self.assertEqual(r.status_code, 405)

    def test_non_superuser_forbidden(self):
        self.client.force_login(self.regular)
        r = self.client.post("/admin-dashboard/run/signal-scan/")
        self.assertEqual(r.status_code, 403)

    def test_anonymous_redirected_to_login(self):
        r = self.client.post("/admin-dashboard/run/signal-scan/")
        # @login_required → 302 to login
        self.assertEqual(r.status_code, 302)

    def test_superuser_redirects_to_admin_dashboard(self):
        """Hit a low-side-effect endpoint to verify the redirect contract."""
        self.client.force_login(self.admin)
        r = self.client.post("/admin-dashboard/run/seed-components/")
        self.assertEqual(r.status_code, 302)
        self.assertIn("admin-dashboard", r.url)


# ── Broker credential forms ────────────────────────────────────────────────

class BrokerCredentialFormTests(TestCase):
    """Saving credentials now VERIFIES them: `connected` means the broker
    answered an authenticated call, not "written down". Tests patch the
    client ping so no test ever leaves the process."""

    def setUp(self):
        self.client = Client()
        self.admin = _superuser()
        self.target = User.objects.create_user(username="alice", password="x")
        self.client.force_login(self.admin)

    def test_save_oanda_creates_encrypted_account(self):
        from unittest.mock import patch
        from bot_program.models import OANDAAccount
        with patch("bot_program.engine.oanda_client.OANDATrader.ping",
                   return_value=True):
            r = self.client.post("/admin-dashboard/brokers/oanda/save/", {
                "target_username": "alice",
                "oanda_api_key": "sk-test-oanda",
                "oanda_account_id": "101-001-1234567-001",
                "practice": "on",
            })
        self.assertEqual(r.status_code, 302)
        acct = OANDAAccount.objects.get(user=self.target)
        # Encrypted fields are non-empty and round-trip back to plaintext.
        self.assertTrue(acct.api_key_enc)
        self.assertTrue(acct.account_id_enc)
        k, aid = acct.get_credentials()
        self.assertEqual(k, "sk-test-oanda")
        self.assertEqual(aid, "101-001-1234567-001")
        self.assertTrue(acct.practice)
        self.assertTrue(acct.connected)
        self.assertIsNotNone(acct.last_sync)

    def test_save_oanda_with_bad_keys_stores_but_not_connected(self):
        """The row survives (the operator can fix a typo without retyping
        everything) but `connected` tells the truth."""
        from unittest.mock import patch
        from bot_program.models import OANDAAccount
        with patch("bot_program.engine.oanda_client.OANDATrader.ping",
                   return_value=False):
            r = self.client.post("/admin-dashboard/brokers/oanda/save/", {
                "target_username": "alice",
                "oanda_api_key": "wrong-key",
                "oanda_account_id": "101-001-0000000-001",
                "practice": "on",
            })
        self.assertEqual(r.status_code, 302)
        acct = OANDAAccount.objects.get(user=self.target)
        self.assertFalse(acct.connected)
        self.assertIsNone(acct.last_sync)
        k, _ = acct.get_credentials()
        self.assertEqual(k, "wrong-key")

    def test_save_alpaca_creates_encrypted_account(self):
        from unittest.mock import patch
        from bot_program.models import AlpacaAccount
        with patch("bot_program.engine.alpaca_client.AlpacaTrader.ping",
                   return_value=True):
            r = self.client.post("/admin-dashboard/brokers/alpaca/save/", {
                "target_username": "alice",
                "alpaca_api_key": "AKTEST",
                "alpaca_api_secret": "secret-test",
                # paper checkbox omitted → live
            })
        self.assertEqual(r.status_code, 302)
        acct = AlpacaAccount.objects.get(user=self.target)
        k, s = acct.get_credentials()
        self.assertEqual(k, "AKTEST")
        self.assertEqual(s, "secret-test")
        self.assertFalse(acct.paper)  # checkbox unchecked → live
        self.assertTrue(acct.connected)

    def test_a_verification_exception_reads_as_not_connected(self):
        """ping() never raises by contract, but the wrapper must survive a
        constructor blowing up — a save that 500s loses the operator's
        form input."""
        from unittest.mock import patch
        from bot_program.models import AlpacaAccount
        with patch("bot_program.engine.alpaca_client.AlpacaTrader.__init__",
                   side_effect=RuntimeError("no network")):
            r = self.client.post("/admin-dashboard/brokers/alpaca/save/", {
                "target_username": "alice",
                "alpaca_api_key": "AKTEST",
                "alpaca_api_secret": "secret-test",
            })
        self.assertEqual(r.status_code, 302)
        self.assertFalse(AlpacaAccount.objects.get(user=self.target).connected)

    def test_disconnect_clears_credentials_without_deleting_row(self):
        from unittest.mock import patch
        from bot_program.models import AlpacaAccount
        # First save
        with patch("bot_program.engine.alpaca_client.AlpacaTrader.ping",
                   return_value=True):
            self.client.post("/admin-dashboard/brokers/alpaca/save/", {
                "target_username": "alice",
                "alpaca_api_key": "AKTEST",
                "alpaca_api_secret": "secret",
                "paper": "on",
            })
        # Then disconnect
        r = self.client.post("/admin-dashboard/brokers/disconnect/", {
            "target_username": "alice",
            "broker": "alpaca",
        })
        self.assertEqual(r.status_code, 302)
        acct = AlpacaAccount.objects.get(user=self.target)
        self.assertEqual(acct.api_key_enc, "")
        self.assertEqual(acct.api_secret_enc, "")
        self.assertFalse(acct.connected)

    def test_save_with_unknown_user_flashes_error(self):
        r = self.client.post("/admin-dashboard/brokers/oanda/save/", {
            "target_username": "ghost_user",
            "oanda_api_key": "k", "oanda_account_id": "a",
        })
        self.assertEqual(r.status_code, 302)
        from bot_program.models import OANDAAccount
        self.assertEqual(OANDAAccount.objects.count(), 0)


# ── Position-management routing ────────────────────────────────────────────

class PositionManagementRoutingTests(TestCase):
    """The `_close` helper is now broker-agnostic and the management loop
    fetches a per-symbol client. Verify the helper accepts a duck-typed
    client without requiring `BinanceClient`."""

    def test_close_uses_provided_client_for_market_order(self):
        from bot_program.engine.runner import _close
        from bot_program.models import BotConfig, BotTrade
        user = User.objects.create_user(username="closeuser", password="x")
        cfg = BotConfig.objects.create(
            user=user, capital_usdt=Decimal("1000"),
            mode="live", market_type="spot",
        )
        trade = BotTrade.objects.create(
            config=cfg, symbol="AAPL", side="BUY",
            qty=Decimal("10"), entry_price=Decimal("180"),
            stop_loss=Decimal("170"), take_profit=Decimal("200"),
            paper=False, status="OPEN",
        )

        fake_client = MagicMock()
        fake_client.market_order.return_value = {"orderId": "alp-1"}
        # No `ensure_config` attr → reduce_only kwarg should NOT be passed.
        del fake_client.ensure_config

        _close(trade, Decimal("200"), fake_client, "TP")

        fake_client.market_order.assert_called_once()
        args, kwargs = fake_client.market_order.call_args
        self.assertNotIn("reduce_only", kwargs)
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSED")
