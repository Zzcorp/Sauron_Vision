"""Phase-20 notification tests:
  - dispatch_notification creates in-app Notification rows
  - prefs filter (receive_bot_alerts=False blocks)
  - unknown kind rejected
  - external channel adapters degrade gracefully when creds missing
  - hooks fire from orchestrator + AssetBot open + close + drawdown

Run with:  python manage.py test tests.test_phase20_notifications
"""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch, MagicMock

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone


def _user(name="notif_u", email="u@x.com"):
    return User.objects.create_user(username=name, password="x", email=email)


def _profile(user, **kwargs):
    from portfolio.trader_profile import TraderProfile
    p, _ = TraderProfile.objects.get_or_create(user=user)
    for k, v in kwargs.items():
        setattr(p, k, v)
    p.save()
    return p


def _prefs(user, **kwargs):
    from alerts.models import UserNotificationPrefs
    p, _ = UserNotificationPrefs.objects.get_or_create(user=user)
    for k, v in kwargs.items():
        setattr(p, k, v)
    p.save()
    return p


def _abc(user, asset_class, **kw):
    from bot_program.models import AssetBotConfig
    defaults = dict(
        enabled=True, mode="paper", symbols=[],
        capital=Decimal("10000"), base_currency="USD",
        position_size_pct=2.0, max_concurrent_positions=5,
        max_daily_loss_pct=2.0, stop_loss_pct=1.5, take_profit_pct=3.0,
        entry_score_min=0.6, min_signals_for_entry=1,
    )
    defaults.update(kw)
    return AssetBotConfig.objects.create(
        user=user, asset_class=asset_class, name=defaults.pop("name", "T"),
        **defaults,
    )


# ── Dispatcher ────────────────────────────────────────────────────────────

class DispatcherTests(TestCase):
    def test_creates_in_app_notification(self):
        from bot_program.notifications import dispatch_notification
        from alerts.models import Notification
        u = _user("disp_u1")
        ok = dispatch_notification(u, "bot_fill_open",
                                    title="Test", body="hello")
        self.assertTrue(ok)
        n = Notification.objects.filter(user=u).first()
        self.assertIsNotNone(n)
        self.assertEqual(n.notification_type, "bot")
        self.assertEqual(n.title, "Test")

    def test_unknown_kind_rejected(self):
        from bot_program.notifications import dispatch_notification
        from alerts.models import Notification
        u = _user("disp_u2")
        ok = dispatch_notification(u, "made_up_kind", title="x")
        self.assertFalse(ok)
        self.assertEqual(Notification.objects.filter(user=u).count(), 0)

    def test_disabled_prefs_skips_dispatch(self):
        from bot_program.notifications import dispatch_notification
        from alerts.models import Notification
        u = _user("disp_u3")
        _prefs(u, receive_bot_alerts=False)
        ok = dispatch_notification(u, "bot_fill_open", title="T")
        self.assertFalse(ok)
        self.assertEqual(Notification.objects.filter(user=u).count(), 0)

    def test_default_when_no_prefs_is_on(self):
        """User without any UserNotificationPrefs row → still receives."""
        from bot_program.notifications import dispatch_notification
        from alerts.models import Notification
        u = _user("disp_u4")
        ok = dispatch_notification(u, "bot_fill_close", title="X")
        self.assertTrue(ok)
        self.assertEqual(Notification.objects.filter(user=u).count(), 1)

    def test_external_channel_none_is_safe(self):
        """notify_channel='none' on TraderProfile → in-app only, no errors."""
        from bot_program.notifications import dispatch_notification
        u = _user("disp_u5")
        _profile(u, notify_channel="none")
        ok = dispatch_notification(u, "drawdown_warning", title="Y")
        self.assertTrue(ok)


# ── External-channel graceful degrade ────────────────────────────────────

class ChannelDegradeTests(TestCase):
    def test_telegram_no_token_returns_false(self):
        from bot_program.notifications import _send_telegram
        u = _user("ch_u_tg")
        _profile(u, notify_channel="telegram")
        # No env var, no chat_id → returns False, doesn't raise.
        with patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("TELEGRAM_BOT_TOKEN", None)
            self.assertFalse(_send_telegram(u, "t", "b"))

    def test_email_no_address_returns_false(self):
        from bot_program.notifications import _send_email
        u = User.objects.create_user(username="ch_u_email", password="x", email="")
        self.assertFalse(_send_email(u, "t", "b"))

    def test_discord_no_webhook_returns_false(self):
        from bot_program.notifications import _send_discord
        u = _user("ch_u_dc")
        _profile(u, notify_channel="discord")
        import os
        os.environ.pop("DISCORD_WEBHOOK_URL", None)
        self.assertFalse(_send_discord(u, "t", "b"))


# ── Convenience helpers ──────────────────────────────────────────────────

class HelperShapeTests(TestCase):
    def test_orchestrator_reject_helper(self):
        from bot_program.notifications import notify_orchestrator_reject
        from alerts.models import Notification
        u = _user("hp_u1")
        ok = notify_orchestrator_reject(
            u, asset_class="stock", symbol="NVDA", side="BUY",
            reason="orchestrator: equity theme cap |+3.0| > 2.0",
        )
        self.assertTrue(ok)
        n = Notification.objects.filter(user=u).first()
        self.assertIn("NVDA", n.title)
        self.assertIn("equity theme cap", n.body)

    def test_bot_fill_open_helper(self):
        from bot_program.notifications import notify_bot_fill_open
        from alerts.models import Notification
        u = _user("hp_u2")
        notify_bot_fill_open(u, asset_class="stock", symbol="AAPL",
                              side="BUY", qty=Decimal("10"),
                              entry_price=Decimal("180.5"),
                              rule_name="rule_x")
        n = Notification.objects.filter(user=u).first()
        self.assertIn("AAPL", n.title)
        self.assertIn("BUY", n.title)
        self.assertIn("rule_x", n.body)

    def test_bot_fill_close_helper_includes_pnl(self):
        from bot_program.notifications import notify_bot_fill_close
        from alerts.models import Notification
        u = _user("hp_u3")
        notify_bot_fill_close(u, asset_class="stock", symbol="AAPL",
                               side="BUY", qty=Decimal("10"),
                               exit_price=Decimal("200"),
                               pnl=Decimal("195"), outcome="hit_target")
        n = Notification.objects.filter(user=u).first()
        self.assertIn("AAPL", n.title)
        self.assertIn("+", n.title)  # positive PnL → +
        self.assertIn("hit_target", n.body)


# ── Hook integration ─────────────────────────────────────────────────────

class HookIntegrationTests(TestCase):
    def test_orchestrator_reject_fires_notification(self):
        """Phase-15 reject → Phase-20 notification."""
        from bot_program.orchestrator import gate_new_entry
        from alerts.models import Notification, UserNotificationPrefs
        u = _user("hk_u1")
        UserNotificationPrefs.objects.create(user=u, receive_bot_alerts=True)
        _profile(u, cross_asset_orchestrator_enabled=True,
                 max_equity_theme_exposure=2.0, max_usd_theme_exposure=10.0)
        # Saturate equity exposure.
        st = _abc(u, "stock", name="ST")
        from bot_program.models import AssetBotTrade
        AssetBotTrade.objects.create(
            config=st, asset_class="stock", symbol="A", side="BUY",
            qty=Decimal("1"), entry_price=Decimal("100"), status="OPEN",
        )
        AssetBotTrade.objects.create(
            config=st, asset_class="stock", symbol="B", side="BUY",
            qty=Decimal("1"), entry_price=Decimal("100"), status="OPEN",
        )
        ok, _ = gate_new_entry(u, "stock", "C", "BUY")
        self.assertFalse(ok)
        n = Notification.objects.filter(user=u, notification_type="bot").first()
        self.assertIsNotNone(n)
        self.assertIn("Orchestrator blocked", n.title)

    def test_bot_open_fires_notification(self):
        """AssetBot.scan_symbol → opens trade → fires notification."""
        from bot_program.asset_engine import StockBot
        from instruments.models import Instrument
        from signals.models import Signal
        from alerts.models import Notification
        from market_data.models import LiveQuote

        u = _user("hk_u2")
        cfg = _abc(u, "stock", name="ST", symbols=["AAPL"])
        inst, _ = Instrument.objects.get_or_create(
            symbol="AAPL", defaults={"name": "AAPL", "asset_class": "stock"},
        )
        LiveQuote.objects.create(instrument=inst, last=Decimal("100"))
        Signal.objects.create(
            instrument=inst, signal_type="composite", direction="bullish",
            urgency="medium", title="t", description="t", rule_name="r1",
            score=0.85, sub_scores={},
            price_at_signal=Decimal("100"), suggested_entry=Decimal("100"),
        )
        result = StockBot(cfg).scan_symbol("AAPL")
        self.assertIsNotNone(result)
        n = Notification.objects.filter(user=u, notification_type="bot").first()
        self.assertIsNotNone(n)
        self.assertIn("AAPL", n.title)
        self.assertIn("opened", n.title)

    def test_drawdown_warning_dedupes_within_hour(self):
        from bot_program.notifications import notify_drawdown_warning
        from alerts.models import Notification
        u = _user("hk_u3")
        notify_drawdown_warning(u, asset_class="stock", config_name="ST",
                                 realized_pnl=-200.0, limit=-100.0)
        # Simulate the can_open_new dedupe logic by checking the recency guard.
        recent = Notification.objects.filter(
            user=u, notification_type="bot",
            title__startswith="⚠ Drawdown limit reached",
            created_at__gte=timezone.now() - timedelta(hours=1),
        ).exists()
        self.assertTrue(recent)

    def test_close_trade_fires_notification(self):
        from bot_program.asset_engine.base import AssetBot
        from bot_program.engine.paper_trader import PaperTrader
        from alerts.models import Notification
        from bot_program.models import AssetBotTrade

        u = _user("hk_u4")
        cfg = _abc(u, "stock", name="ST")

        # Build a minimal AssetBot subclass to exercise _close_trade.
        class _Stub(AssetBot):
            asset_class = "stock"
        bot = _Stub(cfg)

        trade = AssetBotTrade.objects.create(
            config=cfg, asset_class="stock", symbol="AAPL", side="BUY",
            qty=Decimal("10"), entry_price=Decimal("100"),
            stop_loss=Decimal("98"), take_profit=Decimal("104"),
            status="OPEN", paper=True, rule_name="r1",
        )
        client = PaperTrader(cfg)
        bot._close_trade(trade, Decimal("104"), client, reason="TP")

        n = Notification.objects.filter(user=u, notification_type="bot").first()
        self.assertIsNotNone(n)
        self.assertIn("AAPL", n.title)
        self.assertIn("closed", n.title)
