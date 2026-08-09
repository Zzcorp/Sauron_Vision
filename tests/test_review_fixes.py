"""Regressions for the blockers an adversarial review found.

Each test here reproduces a specific way the first cut of the
execution-trust / bars / health work was wrong. They are written to fail
against that earlier behaviour.

Run with:  python manage.py test tests.test_review_fixes
"""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone


def _user(name="rf_u"):
    return User.objects.create_user(username=name, password="x")


def _instrument(symbol="AAPL", asset_class="stock"):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class})
    return inst


def _cfg(user, **kw):
    from bot_program.models import AssetBotConfig
    defaults = dict(user=user, asset_class="stock", name="RF", mode="live",
                    symbols=["AAPL"], capital=Decimal("10000"), enabled=True)
    defaults.update(kw)
    return AssetBotConfig.objects.create(**defaults)


def _trade(cfg, **kw):
    from bot_program.models import AssetBotTrade
    defaults = dict(
        config=cfg, asset_class=cfg.asset_class, symbol="AAPL", side="BUY",
        qty=Decimal("10"), entry_price=Decimal("100"),
        stop_loss=Decimal("98"), take_profit=Decimal("104"),
        status="OPEN", paper=False)
    defaults.update(kw)
    return AssetBotTrade.objects.create(**defaults)


# ── Alpaca bracket legs ─────────────────────────────────────────────────

class AlpacaBracketLegTests(TestCase):
    def _trader_with(self, post_json, get_json):
        from bot_program.engine.alpaca_client import AlpacaTrader
        trader = AlpacaTrader("k", "s", env="paper")
        post = MagicMock()
        post.json = MagicMock(return_value=post_json)
        post.raise_for_status = MagicMock()
        get = MagicMock()
        get.json = MagicMock(return_value=get_json)
        get.raise_for_status = MagicMock()
        sess = MagicMock()
        sess.post = MagicMock(return_value=post)
        sess.get = MagicMock(return_value=get)
        return trader, sess

    def test_legs_survive_the_fill_poll(self):
        """The realistic case: POST returns 'accepted' with no fill price and
        the legs; the poll response has the price. Losing the leg ids there
        made every later cancel a no-op."""
        trader, sess = self._trader_with(
            {"id": "o1", "status": "accepted", "filled_avg_price": None,
             "legs": [{"id": "leg_sl"}, {"id": "leg_tp"}]},
            {"id": "o1", "status": "filled", "filled_qty": "10",
             "filled_avg_price": "101.0"},
        )
        with patch.object(trader, "_sess", return_value=sess), \
                patch("time.sleep", return_value=None):
            out = trader.market_order("AAPL", "BUY", 10,
                                       stop_loss=98.0, take_profit=104.0)
        self.assertEqual(out["protectiveOrders"], ["leg_sl", "leg_tp"])
        self.assertEqual(out["avgPrice"], "101.0")

    def test_fill_poll_requests_nested_orders(self):
        """Alpaca only nests bracket legs under the parent with nested=true."""
        trader, sess = self._trader_with(
            {"id": "o1", "status": "accepted", "filled_avg_price": None},
            {"id": "o1", "status": "filled", "filled_qty": "10",
             "filled_avg_price": "101.0"},
        )
        with patch.object(trader, "_sess", return_value=sess), \
                patch("time.sleep", return_value=None):
            trader.market_order("AAPL", "BUY", 10,
                                 stop_loss=98.0, take_profit=104.0)
        self.assertEqual(sess.get.call_args.kwargs["params"], {"nested": "true"})

    def test_unconfirmed_fill_reports_zero_qty_not_requested_qty(self):
        """Reporting the requested size as filled records a position the
        broker may not hold."""
        trader, sess = self._trader_with(
            {"id": "o1", "status": "accepted", "filled_avg_price": None,
             "filled_qty": "0"},
            {"id": "o1", "status": "accepted", "filled_qty": "0",
             "filled_avg_price": None},
        )
        with patch.object(trader, "_sess", return_value=sess), \
                patch("time.sleep", return_value=None):
            out = trader.market_order("AAPL", "BUY", 1.111)
        self.assertEqual(out["executedQty"], "0")


# ── close ordering: never strip protection on a failed close ────────────

class CloseOrderingTests(TestCase):
    def setUp(self):
        self.user = _user("co_u")
        self.cfg = _cfg(self.user)

    def test_protective_legs_are_not_cancelled_when_close_succeeds(self):
        from bot_program.asset_engine.stock_bot import StockBot
        trade = _trade(self.cfg, metadata={"protective_order_ids": ["sl1"]})
        client = MagicMock()
        client.market_order = MagicMock(return_value={"orderId": "1"})
        StockBot(self.cfg)._close_trade(trade, Decimal("101"), client,
                                         reason="MANUAL")
        client.cancel_order.assert_not_called()

    def test_legs_cancelled_then_close_retried_when_broker_rejects(self):
        """Alpaca rejects a close while the bracket holds the shares — the
        recovery is cancel-then-retry, not cancel-up-front."""
        from bot_program.asset_engine.stock_bot import StockBot
        trade = _trade(self.cfg, metadata={"protective_order_ids": ["sl1", "tp1"]})
        client = MagicMock()
        client.market_order = MagicMock(
            side_effect=[RuntimeError("held qty"), {"orderId": "2"}])
        ok = StockBot(self.cfg)._close_trade(trade, Decimal("101"), client,
                                              reason="SL")
        self.assertTrue(ok)
        self.assertEqual(client.cancel_order.call_count, 2)
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSED")


# ── CLOSE_PENDING must be visible everywhere it means "live" ────────────

class ClosePendingVisibilityTests(TestCase):
    def setUp(self):
        self.user = _user("cp_u")
        self.cfg = _cfg(self.user)

    def test_kill_switch_flattens_close_pending_trades(self):
        """The one status meaning 'live and unaccounted for' must not be
        invisible to the emergency flatten."""
        from bot_program.engine.kill_switch import execute_kill_switch
        trade = _trade(self.cfg, status="CLOSE_PENDING")
        client = MagicMock()
        client.market_order = MagicMock(return_value={"orderId": "1"})
        with patch("bot_program.engine.broker_router.client_for_symbol",
                    return_value=client):
            res = execute_kill_switch(user=self.user, reason="test")
        self.assertEqual(res["asset_positions_closed"], 1)
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSED")

    def test_options_bot_will_not_double_up_on_a_close_pending_underlying(self):
        from bot_program.asset_engine.options_bot import OptionsBot
        cfg = _cfg(self.user, asset_class="options", name="OPT")
        _trade(cfg, asset_class="options", status="CLOSE_PENDING",
               metadata={"right": "C", "strike": 190.0,
                          "expiry": "2026-06-20", "multiplier": 100})
        self.assertIsNone(OptionsBot(cfg).scan_symbol("AAPL"))


# ── retry safety ────────────────────────────────────────────────────────

class RetrySafetyTests(TestCase):
    def setUp(self):
        self.user = _user("rs_u")
        self.cfg = _cfg(self.user)

    def test_no_new_order_when_broker_is_already_flat(self):
        """Resubmitting after the original close actually filled would open
        a naked reverse position."""
        from bot_program.pending_closes import retry_all_pending_closes
        trade = _trade(self.cfg, status="CLOSE_PENDING")
        client = MagicMock()
        client.get_positions = MagicMock(return_value=[])  # broker is flat
        client.ticker = MagicMock(return_value={"lastPrice": "103"})
        with patch("bot_program.engine.broker_router.client_for_symbol",
                    return_value=client):
            out = retry_all_pending_closes()
        client.market_order.assert_not_called()
        self.assertEqual(out["closed"], 1)
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSED")

    def test_order_is_resubmitted_when_broker_still_holds(self):
        from bot_program.pending_closes import retry_all_pending_closes
        _trade(self.cfg, status="CLOSE_PENDING")
        client = MagicMock()
        client.get_positions = MagicMock(return_value=[{"symbol": "AAPL"}])
        client.market_order = MagicMock(return_value={"orderId": "9"})
        client.ticker = MagicMock(return_value={"lastPrice": "103"})
        with patch("bot_program.engine.broker_router.client_for_symbol",
                    return_value=client):
            retry_all_pending_closes()
        client.market_order.assert_called_once()

    def test_retry_uses_a_stable_idempotency_key(self):
        from bot_program.pending_closes import retry_all_pending_closes
        _trade(self.cfg, status="CLOSE_PENDING")
        client = MagicMock()
        client.get_positions = MagicMock(return_value=[{"symbol": "AAPL"}])
        client.market_order = MagicMock(return_value={"orderId": "9"})
        client.ticker = MagicMock(return_value={"lastPrice": "103"})
        seen = []
        with patch("bot_program.engine.broker_router.client_for_symbol",
                    return_value=client):
            retry_all_pending_closes()
            seen.append(client.market_order.call_args.kwargs["client_order_id"])
        from bot_program.models import AssetBotTrade
        AssetBotTrade.objects.update(status="CLOSE_PENDING", closed_at=None)
        with patch("bot_program.engine.broker_router.client_for_symbol",
                    return_value=client):
            retry_all_pending_closes()
            seen.append(client.market_order.call_args.kwargs["client_order_id"])
        self.assertEqual(seen[0], seen[1])

    def test_retries_stop_after_the_cap(self):
        from bot_program.pending_closes import (
            retry_all_pending_closes, MAX_RETRY_ATTEMPTS)
        trade = _trade(self.cfg, status="CLOSE_PENDING",
                       metadata={"close_retry_attempts": MAX_RETRY_ATTEMPTS - 1})
        client = MagicMock()
        client.get_positions = MagicMock(return_value=[{"symbol": "AAPL"}])
        client.market_order = MagicMock(side_effect=RuntimeError("dead"))
        with patch("bot_program.engine.broker_router.client_for_symbol",
                    return_value=client):
            retry_all_pending_closes()
        trade.refresh_from_db()
        self.assertEqual(trade.status, "ERROR")

    def test_retry_task_is_not_gated_by_the_bot_component(self):
        """Switching the bots off must not disable the only drain for
        stranded live positions."""
        from bot_program import tasks
        self.assertFalse(hasattr(tasks.retry_pending_closes, "_guarded_component"))
        from core.platform_control import PlatformComponent
        PlatformComponent.objects.update_or_create(
            key="pipeline_asset_bots", defaults={"is_enabled": False,
                                                  "name": "Asset bots",
                                                  "category": "pipeline"})
        _trade(self.cfg, status="CLOSE_PENDING")
        client = MagicMock()
        client.market_order = MagicMock(return_value={"orderId": "1"})
        client.ticker = MagicMock(return_value={"lastPrice": "101"})
        with patch("bot_program.engine.broker_router.client_for_symbol",
                    return_value=client):
            res = tasks.retry_pending_closes()
        self.assertEqual(res.get("closed"), 1)


# ── OANDA timestamps ────────────────────────────────────────────────────

class OandaTimestampTests(TestCase):
    def test_whole_second_candles_parse(self):
        """rstrip('0') ate the whole fraction and left a trailing '.', so
        every OANDA candle timestamp came back 0 and no forex bar was ever
        written."""
        from bot_program.engine.oanda_client import _to_iso_ms
        for ts in ("2026-04-30T12:00:00.000000000Z",
                   "2026-04-30T12:30:00.123456789Z",
                   "2026-04-30T12:00:00Z"):
            self.assertGreater(_to_iso_ms(ts), 0, ts)


# ── paper pricing must not go dark ──────────────────────────────────────

class PaperBarFallbackTests(TestCase):
    def setUp(self):
        self.user = _user("pb_u")
        self.inst = _instrument("MSFT")
        self.cfg = _cfg(self.user, symbols=["MSFT"], mode="paper")

    def test_stale_quote_falls_back_to_a_recent_bar(self):
        """LiveQuote pollers only cover watchlist symbols; without the bar
        fallback a paper bot on any other symbol is permanently priceless."""
        from bot_program.engine.paper_trader import PaperTrader
        from market_data.models import LiveQuote, PriceData
        q = LiveQuote.objects.create(instrument=self.inst, last=Decimal("50"),
                                      source="test")
        LiveQuote.objects.filter(pk=q.pk).update(
            updated_at=timezone.now() - timedelta(hours=2))
        PriceData.objects.create(
            instrument=self.inst, timeframe="1h",
            timestamp=timezone.now() - timedelta(minutes=20),
            open=1, high=2, low=1, close=Decimal("77.5"), volume=1,
            source="alpaca")
        tk = PaperTrader(self.cfg).ticker("MSFT")
        self.assertEqual(tk["lastPrice"], "77.50000000")
        self.assertEqual(tk["source"], "bars")

    def test_no_quote_and_no_bar_still_reports_no_price(self):
        from bot_program.engine.paper_trader import PaperTrader
        tk = PaperTrader(self.cfg).ticker("MSFT")
        self.assertEqual(tk["lastPrice"], "0")


# ── health checks must not report false greens ──────────────────────────

class HealthAccuracyTests(TestCase):
    def setUp(self):
        self.user = _user("ha_u")
        self.client.force_login(self.user)

    def test_bars_check_fails_when_only_one_symbol_is_fed(self):
        from dashboard.views_system_health import check_bot_bars
        from market_data.models import PriceData
        a, b = _instrument("AAA"), _instrument("BBB")
        _cfg(self.user, symbols=["AAA", "BBB"])
        PriceData.objects.create(
            instrument=a, timeframe="4h", timestamp=timezone.now(),
            open=1, high=1, low=1, close=1, volume=0, source="t")
        c = check_bot_bars(self.user)
        self.assertEqual(c["state"], "fail")
        self.assertIn("BBB", c["detail"])

    def test_bars_check_is_scoped_to_the_requesting_user(self):
        from dashboard.views_system_health import check_bot_bars
        _instrument("AAA")
        _cfg(self.user, symbols=["AAA"])
        other = _user("ha_other")
        _instrument("ZZZ")
        _cfg(other, symbols=["ZZZ"], name="OTHER")
        c = check_bot_bars(self.user)
        self.assertNotIn("ZZZ", c["detail"])

    def test_live_readiness_checks_every_symbol_not_just_the_first(self):
        from dashboard.views_system_health import check_live_mode_readiness
        from bot_program.engine.paper_trader import PaperTrader
        cfg = _cfg(self.user, symbols=["AAPL", "EURUSD"])

        def route(user, symbol, c=None):
            return MagicMock() if symbol == "AAPL" else PaperTrader(cfg)

        with patch("bot_program.engine.broker_router.client_for_symbol",
                    side_effect=route):
            res = check_live_mode_readiness(self.user)
        self.assertEqual(res["state"], "fail")
        self.assertIn("EURUSD", res["detail"])

    def test_commodity_paper_routing_is_not_reported_as_broken(self):
        from dashboard.views_system_health import check_live_mode_readiness
        _cfg(self.user, asset_class="commodity", symbols=["XAUUSD"], name="Gold")
        self.assertEqual(check_live_mode_readiness(self.user)["state"], "ok")

    def test_heartbeat_check_warns_when_some_bots_are_silent(self):
        from bot_program.asset_engine.safety import write_heartbeat
        from dashboard.views_system_health import check_bot_heartbeats
        cfg_a = _cfg(self.user, name="A", symbols=["AAA"])
        cfg_b = _cfg(self.user, name="B", symbols=["BBB"])
        # Both bots are alive and ticking; the difference is that only A
        # found something to trade. A bot that ticks and holds is quiet,
        # not broken — that distinction is what this asserts.
        write_heartbeat(cfg_a)
        write_heartbeat(cfg_b)
        _trade(cfg_a)  # only A traded
        self.assertEqual(check_bot_heartbeats(self.user)["state"], "warn")

    def test_close_pending_check_survives_null_attempt_counter(self):
        from dashboard.views_system_health import check_close_pending
        cfg = _cfg(self.user)
        _trade(cfg, status="CLOSE_PENDING",
               metadata={"close_retry_attempts": None})
        self.assertEqual(check_close_pending(self.user)["state"], "fail")

    def test_platform_wide_checks_are_staff_only(self):
        r = self.client.get("/health/")
        self.assertNotContains(r, "Beat schedule")
        staff = User.objects.create_user(username="ha_staff", password="x",
                                          is_staff=True)
        self.client.force_login(staff)
        self.assertContains(self.client.get("/health/"), "Beat schedule")


# ── forensics attribution ───────────────────────────────────────────────

class ForensicsAttributionTests(TestCase):
    def setUp(self):
        self.user = _user("fa_u")
        self.cfg = _cfg(self.user)
        self.client.force_login(self.user)

    def test_audit_rows_of_another_trade_are_not_attributed(self):
        from bot_program.audit import record_trade_open
        from dashboard.views_forensics import _audit_entries
        mine = _trade(self.cfg)
        theirs = _trade(self.cfg)
        record_trade_open(self.user, trade=theirs)
        rows = _audit_entries(mine)
        for row in rows:
            self.assertNotEqual(str((row.data or {}).get("trade_id")),
                                str(theirs.id))

    def test_neutral_signals_do_not_count_as_agreeing(self):
        from signals.models import Signal
        inst = _instrument()
        trade = _trade(self.cfg, side="SELL")
        for direction in ("bullish", "bearish", "neutral"):
            Signal.objects.create(
                instrument=inst, signal_type="composite", direction=direction,
                urgency="medium", title=f"{direction} sig", description="d",
                rule_name="r", score=0.7, sub_scores={},
                price_at_signal=Decimal("100"), suggested_entry=Decimal("100"))
        r = self.client.get(f"/forensics/{trade.id}/")
        self.assertContains(r, "1 of 3 agreed")


# ── model picker keys ───────────────────────────────────────────────────

class ModelPickerKeyTests(TestCase):
    def test_brain_agent_keys_match_runtime_agent_names(self):
        """A friendly-but-wrong key writes an override nothing ever reads."""
        from dashboard.views_ai_models import AGENT_GROUPS
        from brain.synthesizer import SauronMindAgent
        from brain.critic import CriticAgent

        keys = {name for _, rows in AGENT_GROUPS for name, _, _ in rows}
        self.assertIn(SauronMindAgent.agent_name, keys)
        self.assertIn(CriticAgent.agent_name, keys)

    def test_unknown_agent_key_is_rejected(self):
        from ai_agents.models import AIModelSetting
        staff = User.objects.create_user(username="mp_staff", password="x",
                                          is_staff=True, is_superuser=True)
        self.client.force_login(staff)
        self.client.post("/ai-models/", {
            "scope": "agent", "key": "brain_critic",  # old, wrong key
            "model_id": "claude-opus-5", "effort": ""})
        self.assertFalse(AIModelSetting.objects.filter(
            scope="agent", key="brain_critic").exists())

    def test_live_but_older_models_stay_selectable(self):
        """_validated must not discard a deliberate pin to a served model."""
        from ai_agents.catalog import known_model
        for model_id in ("claude-opus-4-6", "claude-opus-4-7",
                         "claude-sonnet-4-5"):
            self.assertTrue(known_model(model_id), model_id)


# ── provider must not silently succeed on empty output ──────────────────

class ProviderFailureTests(TestCase):
    def _provider_with(self, blocks, stop_reason="end_turn"):
        from ai_agents.providers.claude_provider import ClaudeProvider
        provider = ClaudeProvider()
        client = MagicMock()
        client.messages.create = MagicMock(return_value=MagicMock(
            content=blocks, stop_reason=stop_reason, stop_details=None,
            usage=MagicMock(input_tokens=5, output_tokens=5)))
        return provider, client

    def test_empty_response_raises_instead_of_returning_blank(self):
        provider, client = self._provider_with([])
        with patch.object(provider, "_get_client", return_value=client):
            with self.assertRaises(RuntimeError):
                provider.complete("s", "m", model="claude-opus-5")

    def test_refusal_raises(self):
        block = MagicMock()
        block.type = "text"
        block.text = ""
        provider, client = self._provider_with([block], stop_reason="refusal")
        with patch.object(provider, "_get_client", return_value=client):
            with self.assertRaises(RuntimeError):
                provider.complete("s", "m", model="claude-opus-5")

    def test_thinking_models_get_token_headroom(self):
        block = MagicMock()
        block.type = "text"
        block.text = "ok"
        provider, client = self._provider_with([block])
        with patch.object(provider, "_get_client", return_value=client):
            provider.complete("s", "m", model="claude-opus-5")
            thinking_budget = client.messages.create.call_args.kwargs["max_tokens"]
            provider.complete("s", "m", model="claude-haiku-4-5")
            haiku_budget = client.messages.create.call_args.kwargs["max_tokens"]
        self.assertGreater(thinking_budget, haiku_budget)
