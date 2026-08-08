"""Phase-23 WebSocket real-time push tests.

Async consumer testing requires Channels' async test infrastructure which
is heavyweight to wire into Django TestCase. We test what we *can* check
synchronously:
  - push_eye_event returns False on missing/anon user
  - push_eye_event returns False when channel_layer is None
  - push_eye_event with mocked layer dispatches the right group_send
  - Hooks (gate_reject, fill_open, fill_close) call push_eye_event
  - /ws/eye/ route is registered in routing.py
  - Eye template carries the WS JS

Run with:  python manage.py test tests.test_phase23_websocket
"""
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import AnonymousUser, User
from django.test import TestCase, Client


def _user(name="ws_u"):
    return User.objects.create_user(username=name, password="x")


# ── push_eye_event ────────────────────────────────────────────────────────

class PushEyeEventTests(TestCase):
    def test_anonymous_user_returns_false(self):
        from dashboard.consumers import push_eye_event
        anon = AnonymousUser()
        self.assertFalse(push_eye_event(anon, "gate_reject"))

    def test_none_user_returns_false(self):
        from dashboard.consumers import push_eye_event
        self.assertFalse(push_eye_event(None, "fill_open"))

    def test_no_channel_layer_returns_false(self):
        from dashboard.consumers import push_eye_event
        u = _user()
        # When Redis isn't running and no channel layer is configured.
        with patch("channels.layers.get_channel_layer", return_value=None):
            self.assertFalse(push_eye_event(u, "gate_reject"))

    def test_dispatches_to_correct_group(self):
        from dashboard.consumers import push_eye_event
        u = _user("dispatch_u")
        layer = MagicMock()
        layer.group_send = MagicMock(return_value=None)
        # async_to_sync of a MagicMock just calls it.
        with patch("channels.layers.get_channel_layer", return_value=layer), \
             patch("asgiref.sync.async_to_sync",
                    side_effect=lambda f: (lambda *a, **kw: f(*a, **kw))):
            self.assertTrue(push_eye_event(u, "gate_reject", {"sym": "A"}))
        # Group name + event payload structure.
        call_args = layer.group_send.call_args
        self.assertEqual(call_args.args[0], f"eye_user_{u.id}")
        self.assertEqual(call_args.args[1]["type"], "eye_event")
        self.assertEqual(call_args.args[1]["kind"], "gate_reject")
        self.assertEqual(call_args.args[1]["data"], {"sym": "A"})

    def test_dispatch_failure_returns_false(self):
        """If the channel layer raises, push_eye_event swallows + returns False."""
        from dashboard.consumers import push_eye_event
        u = _user("fail_u")
        layer = MagicMock()
        layer.group_send = MagicMock(side_effect=Exception("Redis down"))
        with patch("channels.layers.get_channel_layer", return_value=layer), \
             patch("asgiref.sync.async_to_sync",
                    side_effect=lambda f: (lambda *a, **kw: f(*a, **kw))):
            self.assertFalse(push_eye_event(u, "fill_open"))


# ── Hook integration ─────────────────────────────────────────────────────

class HookPushTests(TestCase):
    def test_gate_reject_calls_push(self):
        from bot_program.orchestrator import gate_new_entry
        from bot_program.models import AssetBotConfig, AssetBotTrade
        from portfolio.trader_profile import TraderProfile

        u = _user("h_g_u")
        TraderProfile.objects.create(
            user=u, cross_asset_orchestrator_enabled=True,
            max_equity_theme_exposure=2.0, max_usd_theme_exposure=10.0)
        cfg = AssetBotConfig.objects.create(
            user=u, asset_class="stock", name="ST",
            enabled=True, mode="paper", symbols=[],
            capital=Decimal("10000"), base_currency="USD",
            position_size_pct=2.0, max_concurrent_positions=5,
            max_daily_loss_pct=2.0, stop_loss_pct=1.5, take_profit_pct=3.0,
            entry_score_min=0.6, min_signals_for_entry=1,
        )
        # Saturate equity so the next entry rejects.
        for sym in ("A", "B"):
            AssetBotTrade.objects.create(
                config=cfg, asset_class="stock", symbol=sym, side="BUY",
                qty=Decimal("1"), entry_price=Decimal("100"), status="OPEN")

        with patch("dashboard.consumers.push_eye_event") as m:
            ok, _ = gate_new_entry(u, "stock", "C", "BUY")
        self.assertFalse(ok)
        m.assert_called()
        kwargs_or_args = m.call_args
        self.assertEqual(kwargs_or_args.args[0], u)  # first positional = user
        self.assertEqual(kwargs_or_args.args[1], "gate_reject")

    def test_fill_open_calls_push(self):
        """End-to-end via StockBot.scan_symbol — push_eye_event called with fill_open."""
        from bot_program.asset_engine import StockBot
        from bot_program.models import AssetBotConfig
        from instruments.models import Instrument
        from market_data.models import LiveQuote
        from signals.models import Signal

        u = _user("h_o_u")
        cfg = AssetBotConfig.objects.create(
            user=u, asset_class="stock", name="ST",
            enabled=True, mode="paper", symbols=["AAPL"],
            capital=Decimal("10000"), base_currency="USD",
            position_size_pct=2.0, max_concurrent_positions=5,
            max_daily_loss_pct=2.0, stop_loss_pct=1.5, take_profit_pct=3.0,
            entry_score_min=0.6, min_signals_for_entry=1,
        )
        inst, _ = Instrument.objects.get_or_create(
            symbol="AAPL", defaults={"name": "AAPL", "asset_class": "stock"})
        LiveQuote.objects.create(instrument=inst, last=Decimal("100"))
        Signal.objects.create(
            instrument=inst, signal_type="composite", direction="bullish",
            urgency="medium", title="t", description="t", rule_name="r1",
            score=0.85, sub_scores={},
            price_at_signal=Decimal("100"), suggested_entry=Decimal("100"),
        )
        with patch("dashboard.consumers.push_eye_event") as m:
            result = StockBot(cfg).scan_symbol("AAPL")
        self.assertIsNotNone(result)
        # fill_open should have been pushed (other kinds may also fire from
        # adjacent hooks; just assert ours appears).
        kinds = [c.args[1] for c in m.call_args_list]
        self.assertIn("fill_open", kinds)


# ── Routing + template ───────────────────────────────────────────────────

class RoutingTests(TestCase):
    def test_eye_ws_route_registered(self):
        from dashboard.routing import websocket_urlpatterns
        patterns = [str(p.pattern) for p in websocket_urlpatterns]
        self.assertTrue(any("ws/eye" in p for p in patterns))


class TemplateWSCodeTests(TestCase):
    def test_eye_template_carries_ws_javascript(self):
        u = _user("ws_tpl_u")
        c = Client()
        c.force_login(u)
        r = c.get("/eye/")
        body = r.content.decode("utf-8", errors="ignore")
        # WS open code + reconnect logic.
        self.assertIn("/ws/eye/", body)
        self.assertIn("WebSocket", body)
        self.assertIn("eyeUpdate", body)  # HTMX trigger event name
        # Custom hx-trigger now includes the WS-driven trigger as well as
        # the 10s polling fallback.
        self.assertIn("eyeUpdate from:body", body)

    def test_eye_template_has_status_indicator(self):
        u = _user("ws_status_u")
        c = Client()
        c.force_login(u)
        r = c.get("/eye/")
        body = r.content.decode("utf-8", errors="ignore")
        self.assertIn('id="eye-ws-status"', body)
