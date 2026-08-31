"""TAKE TRADE, wave 2 — the LIVE ticket.

Wave 1's manual lane never touched a broker: the "fill" was a modelled
DB row on the paper venue, and _config_error hard-refused a manual
config in live mode. Wave 2 lifts that refusal and builds the missing
execution leg on the bots' proven pattern — one market_order call
carrying the stop and target as a broker-side bracket — wrapped in a
refuse-first ceremony, because from here a wrong number is real money:

  * the trading PIN on every live ticket (the close path's asymmetry,
    now on the open);
  * no funding closes on live — a live close can finish minutes later,
    and capital that may arrive is not capital;
  * no entry while nothing would manage it (platform switches off);
  * a broker that cannot be reached is a REFUSAL — the router's silent
    PaperTrader fallback must never wear a live label;
  * the row is booked from the broker's own numbers (avgPrice,
    executedQty), protection is PROVEN before it is claimed, and an
    unproven bracket is said out loud instead of assumed.

Run with:  python manage.py test tests.test_take_trade_live
"""
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase


def _instrument(symbol="BTCUSD", asset_class="crypto"):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class})
    return inst


def _quote(symbol, last, asset_class="crypto"):
    from market_data.models import LiveQuote
    inst = _instrument(symbol, asset_class)
    LiveQuote.objects.update_or_create(
        instrument=inst, defaults={"last": Decimal(str(last)),
                                   "source": "binance_public"})
    return inst


def _signal(inst, *, direction="bullish", entry=60000, stop=59100,
            target=61800, score=0.8):
    from signals.models import Signal
    return Signal.objects.create(
        instrument=inst, signal_type="technical", direction=direction,
        urgency="high", title=f"{inst.symbol} {direction}", description="d",
        rule_name="test_rule", score=score, sub_scores={},
        price_at_signal=Decimal(str(entry)),
        suggested_entry=Decimal(str(entry)),
        suggested_stop=Decimal(str(stop)),
        suggested_target=Decimal(str(target)), is_active=True)


def _components_on():
    from core.platform_control import PlatformComponent
    for key in ("platform_master", "pipeline_asset_bots"):
        PlatformComponent.objects.get_or_create(
            key=key, defaults={"name": key, "category": "system",
                               "is_enabled": True})
        PlatformComponent.objects.filter(key=key).update(is_enabled=True)


def _arm_live(user, asset_class="crypto"):
    from bot_program.manual_trade import manual_config_for
    cfg = manual_config_for(user, asset_class)
    cfg.mode = "live"
    cfg.save(update_fields=["mode"])
    return cfg


def _filled_response(**overrides):
    """The broker's answer to a good bracket order, bots'-contract shape."""
    res = {"orderId": "7", "symbol": "BTCUSD", "side": "BUY",
           "executedQty": "0.0004", "avgPrice": "60012.5",
           "status": "FILLED", "raw": {},
           "protectedOnFill": True, "protectiveOrders": ["8", "9"],
           "protectiveStopId": "9", "protectiveTargetId": "8"}
    res.update(overrides)
    return res


def _fake_live_client(response=None):
    """A live-looking broker client: NOT a PaperTrader, quotes the mark,
    answers market_order with the given response."""
    client = MagicMock(name="fake_live_client")
    client.ticker.return_value = {"lastPrice": "60000"}
    client.market_order.return_value = response or _filled_response()
    return client


ROUTER = "bot_program.engine.broker_router.client_for_symbol"


class TheLiveTicketCeremonyTests(TestCase):
    """Every refusal that must land BEFORE money can move."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("lv_u", password="x")

    def setUp(self):
        cache.clear()
        self.inst = _quote("BTCUSD", 60000)
        _components_on()
        self.cfg = _arm_live(self.user)

    def test_preview_names_the_live_venue_and_demands_the_pin(self):
        from bot_program.manual_trade import preview_take_trade
        with patch(ROUTER, return_value=_fake_live_client()):
            p = preview_take_trade(self.user, _signal(self.inst))
        self.assertNotIn("error", p)
        self.assertEqual(p["venue"], "live")
        self.assertTrue(p["requires_pin"])

    def test_preview_refuses_when_the_live_route_falls_back_to_paper(self):
        """The router substitutes PaperTrader for every missing
        credential — the dialog must not offer what execute will
        refuse."""
        from bot_program.manual_trade import preview_take_trade
        p = preview_take_trade(self.user, _signal(self.inst))
        self.assertIn("error", p)
        self.assertIn("LIVE route unavailable", p["error"])

    def test_execute_without_the_pin_refuses_and_sends_nothing(self):
        from bot_program.manual_trade import execute_take_trade
        from bot_program.models import AssetBotTrade
        fake = _fake_live_client()
        with patch(ROUTER, return_value=fake):
            out = execute_take_trade(self.user, _signal(self.inst))
        self.assertIn("error", out)
        self.assertIn("PIN", out["error"])
        fake.market_order.assert_not_called()
        self.assertEqual(AssetBotTrade.objects.count(), 0)

    def test_funding_closes_are_not_offered_on_live(self):
        from bot_program.manual_trade import execute_take_trade
        fake = _fake_live_client()
        with patch(ROUTER, return_value=fake):
            out = execute_take_trade(self.user, _signal(self.inst),
                                     close_ids=[12345], pin_ok=True)
        self.assertIn("error", out)
        self.assertIn("positions page", out["error"])
        fake.market_order.assert_not_called()

    def test_an_unmanaged_platform_refuses_a_live_entry(self):
        """If the broker refuses the bracket, the 5-minute tick is the
        only protection there is. Switched off, there would be NOTHING —
        so the entry is refused, not merely warned about."""
        from core.platform_control import PlatformComponent
        PlatformComponent.objects.filter(
            key="pipeline_asset_bots").update(is_enabled=False)
        from bot_program.manual_trade import execute_take_trade
        fake = _fake_live_client()
        with patch(ROUTER, return_value=fake):
            out = execute_take_trade(self.user, _signal(self.inst),
                                     pin_ok=True)
        self.assertIn("error", out)
        self.assertIn("manage", out["error"])
        fake.market_order.assert_not_called()

    def test_the_paper_fallback_at_order_time_refuses(self):
        """End to end: an armed live config whose route resolves to
        PaperTrader books NOTHING — a paper fill wearing a live label is
        the one lie this lane exists to never tell."""
        from bot_program.engine.paper_trader import PaperTrader
        from bot_program.manual_trade import execute_take_trade
        from bot_program.models import AssetBotTrade
        with patch(ROUTER, return_value=PaperTrader(self.cfg)):
            out = execute_take_trade(self.user, _signal(self.inst),
                                     pin_ok=True)
        self.assertIn("error", out)
        self.assertIn("LIVE route unavailable", out["error"])
        self.assertEqual(AssetBotTrade.objects.count(), 0)

    def test_a_double_click_is_stopped_by_the_claim(self):
        """The broker enforces no idempotency key, so the server half of
        the double-click guard is a short cache claim."""
        from bot_program.manual_trade import execute_take_trade
        cache.set(f"manual_open:{self.cfg.pk}:BTCUSD:BUY", 1, 120)
        fake = _fake_live_client()
        with patch(ROUTER, return_value=fake):
            out = execute_take_trade(self.user, _signal(self.inst),
                                     pin_ok=True)
        self.assertIn("error", out)
        self.assertIn("already in flight", out["error"])
        fake.market_order.assert_not_called()


class TheLiveFillIsTheBrokersTests(TestCase):
    """What gets booked is what the broker said happened."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("lv_f", password="x")

    def setUp(self):
        cache.clear()
        self.inst = _quote("BTCUSD", 60000)
        _components_on()
        self.cfg = _arm_live(self.user)

    def _execute(self, response=None, signal=None):
        from bot_program.manual_trade import execute_take_trade
        fake = _fake_live_client(response)
        with patch(ROUTER, return_value=fake):
            out = execute_take_trade(
                self.user, signal or _signal(self.inst), pin_ok=True)
        return out, fake

    def test_a_live_fill_is_booked_from_the_brokers_own_numbers(self):
        from bot_program.manual_trade import MANUAL_RULE
        from bot_program.models import AssetBotTrade
        out, fake = self._execute()
        self.assertTrue(out.get("ok"), out)
        self.assertEqual(out["venue"], "live")
        trade = AssetBotTrade.objects.get(pk=out["trade_id"])
        self.assertFalse(trade.paper)
        self.assertEqual(trade.rule_name, MANUAL_RULE)
        # The broker's avgPrice, NOT the adverse paper model.
        self.assertEqual(float(trade.entry_price), 60012.5)
        self.assertEqual(trade.metadata.get("fill_source"), "broker")
        self.assertNotIn("paper_fill", trade.metadata)
        self.assertTrue(str(trade.metadata.get("client_order_id",
                                               "")).startswith("sv-"))
        # The order went out with both protective levels attached.
        kwargs = fake.market_order.call_args.kwargs
        self.assertGreater(kwargs["stop_loss"], 0)
        self.assertGreater(kwargs["take_profit"], kwargs["stop_loss"])

    def test_proven_protection_rides_the_row(self):
        from bot_program.models import AssetBotTrade
        out, _ = self._execute()
        trade = AssetBotTrade.objects.get(pk=out["trade_id"])
        self.assertTrue(trade.metadata.get("protected"))
        self.assertEqual(trade.metadata.get("protective_stop_id"), "9")
        self.assertEqual(trade.metadata.get("protective_order_ids"),
                         ["8", "9"])
        self.assertNotIn("protection_note", out)

    def test_unproven_protection_is_said_out_loud(self):
        """The entry went in, the bracket did not rest: the operator must
        hear it from the confirmation, not discover it when a stop fails
        to fire."""
        from bot_program.models import AssetBotTrade
        res = _filled_response()
        for key in ("protectedOnFill", "protectiveOrders",
                    "protectiveStopId", "protectiveTargetId"):
            res.pop(key, None)
        out, _ = self._execute(response=res)
        self.assertTrue(out.get("ok"), out)
        trade = AssetBotTrade.objects.get(pk=out["trade_id"])
        self.assertNotIn("protected", trade.metadata)
        self.assertIn("protection_note", out)
        self.assertIn("5-minute tick", out["protection_note"])

    def test_the_broker_refusal_books_no_row(self):
        from bot_program.models import AssetBotTrade
        out, _ = self._execute(response=_filled_response(
            status="REJECTED", executedQty="0", avgPrice="0",
            raw={"reason": "broker_rejected: margin"}))
        self.assertIn("error", out)
        self.assertIn("refused", out["error"])
        self.assertEqual(AssetBotTrade.objects.count(), 0)

    def test_a_partial_fill_still_books_the_units(self):
        """Partial-then-cancelled is real units in the account — a row
        MUST exist or reconciliation can never find them."""
        from bot_program.models import AssetBotTrade
        out, _ = self._execute(response=_filled_response(
            status="CANCELLED", executedQty="0.0002", avgPrice="60010"))
        self.assertTrue(out.get("ok"), out)
        trade = AssetBotTrade.objects.get(pk=out["trade_id"])
        self.assertEqual(float(trade.qty), 0.0002)
        self.assertEqual(float(trade.entry_price), 60010.0)


class ThePaperPathIsUntouchedTests(TestCase):
    """Wave 2 must change nothing about the rehearsal stage."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("lv_p", password="x")

    def setUp(self):
        cache.clear()
        self.inst = _quote("BTCUSD", 60000)

    def test_paper_tickets_still_need_no_pin_and_stay_paper(self):
        from bot_program.manual_trade import (execute_take_trade,
                                              preview_take_trade)
        from bot_program.models import AssetBotTrade
        p = preview_take_trade(self.user, _signal(self.inst))
        self.assertEqual(p["venue"], "paper")
        self.assertFalse(p["requires_pin"])
        out = execute_take_trade(self.user, _signal(self.inst))
        self.assertTrue(out.get("ok"), out)
        self.assertEqual(out["venue"], "paper")
        trade = AssetBotTrade.objects.get(pk=out["trade_id"])
        self.assertTrue(trade.paper)
        self.assertTrue(trade.metadata.get("paper_fill"))


class TheViewsHandThePinVerdictDownTests(TestCase):
    """The PIN string rides the JSON body; the VIEW computes the verdict
    (views_close._pin_ok — the same check the kill switch trusts) and the
    engine only ever sees a bool."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("lv_v", password="x")
        from portfolio.trader_profile import get_or_create_profile
        prof = get_or_create_profile(cls.user)
        prof.set_pin("4321")
        prof.save()

    def setUp(self):
        cache.clear()
        self.inst = _quote("BTCUSD", 60000)
        _components_on()
        _arm_live(self.user)
        self.client.force_login(self.user)

    def _post(self, body):
        return self.client.post(
            "/instruments/BTCUSD/take-trade/", data=body,
            content_type="application/json", HTTP_HOST="127.0.0.1").json()

    def test_a_wrong_pin_is_a_refusal_with_nothing_sent(self):
        from bot_program.models import AssetBotTrade
        with patch(ROUTER, return_value=_fake_live_client()):
            out = self._post({"side": "BUY", "pin": "9999"})
        self.assertIn("error", out)
        self.assertIn("PIN", out["error"])
        self.assertEqual(AssetBotTrade.objects.count(), 0)

    def test_the_right_pin_opens_the_live_position(self):
        from bot_program.models import AssetBotTrade
        with patch(ROUTER, return_value=_fake_live_client()):
            out = self._post({"side": "BUY", "pin": "4321"})
        self.assertTrue(out.get("ok"), out)
        trade = AssetBotTrade.objects.get(pk=out["trade_id"])
        self.assertFalse(trade.paper)


class ArmingTheManualLaneTests(TestCase):
    """Arming live is its own PIN-confirmed act, refuse-first — the
    moment a chart button starts being able to move real funds."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("lv_a", password="x")

    def setUp(self):
        cache.clear()
        _quote("BTCUSD", 60000)

    def _arm(self, **kw):
        from bot_program.manual_trade import arm_manual_lane
        args = dict(asset_class="crypto", mode="live", pin_ok=True)
        args.update(kw)
        return arm_manual_lane(self.user, **args)

    def test_unknown_class_and_mode_are_refused(self):
        self.assertIn("error", self._arm(asset_class="index"))
        self.assertIn("error", self._arm(mode="turbo"))

    def test_arming_live_without_the_pin_refuses(self):
        out = self._arm(pin_ok=False)
        self.assertIn("PIN", out["error"])

    def test_a_paper_fallback_route_cannot_be_armed(self):
        """No credentials -> the router would hand PaperTrader -> arming
        would arm a simulator wearing a live label. Refused, and the
        config stays paper."""
        out = self._arm()
        self.assertIn("LIVE route unavailable", out["error"])
        from bot_program.manual_trade import manual_config_for
        self.assertEqual(manual_config_for(self.user, "crypto").mode,
                         "paper")

    def test_a_live_route_arms_and_records(self):
        with patch(ROUTER, return_value=_fake_live_client()):
            out = self._arm()
        self.assertTrue(out.get("ok"), out)
        from bot_program.manual_trade import manual_config_for
        self.assertEqual(manual_config_for(self.user, "crypto").mode, "live")
        from alerts.models import Notification
        self.assertTrue(Notification.objects.filter(
            user=self.user, title__contains="ARMED LIVE").exists(),
            "arming live left no durable record")

    def test_disarming_needs_no_pin(self):
        """Stopping must never be gated."""
        with patch(ROUTER, return_value=_fake_live_client()):
            self._arm()
        out = self._arm(mode="paper", pin_ok=False)
        self.assertTrue(out.get("ok"), out)
        from bot_program.manual_trade import manual_config_for
        self.assertEqual(manual_config_for(self.user, "crypto").mode,
                         "paper")

    def _ibkr_backed(self, equity="500.00", age_seconds=0):
        from datetime import timedelta as _td
        from django.utils import timezone as _tz
        from bot_program.models import IBKRAccount
        acct = IBKRAccount.objects.create(
            user=self.user, label="ISA", host="ibgateway", port=4003,
            client_id=1)
        acct.set_credentials("U28134395")
        if equity is not None:
            acct.last_equity = Decimal(equity)
            acct.last_equity_currency = "EUR"
            acct.last_equity_at = _tz.now() - _td(seconds=age_seconds)
        acct.save()
        return acct

    def _ibkr_client(self):
        """A stand-in whose TYPE NAME is the routing truth the equity
        guard keys on — and which is not a PaperTrader."""
        return type("IBKRTrader", (), {})()

    def test_a_broker_backed_route_with_no_reading_refuses(self):
        self._ibkr_backed(equity=None)
        with patch(ROUTER, return_value=self._ibkr_client()):
            out = self._arm()
        self.assertIn("broker_account_sync", out["error"])

    def test_a_pool_larger_than_the_account_cannot_be_armed(self):
        """The default pool is a seeded 10,000 against a real 500 — a
        pool larger than the money makes every limit looser than it
        reads, on real funds."""
        self._ibkr_backed(equity="500.00")
        with patch(ROUTER, return_value=self._ibkr_client()):
            out = self._arm()
        self.assertIn("error", out)
        self.assertIn("larger than the money", out["error"])

    def test_a_pool_inside_the_account_arms_with_the_typed_capital(self):
        self._ibkr_backed(equity="500.00")
        with patch(ROUTER, return_value=self._ibkr_client()):
            out = self._arm(capital=450)
        self.assertTrue(out.get("ok"), out)
        self.assertEqual(out["capital"], 450.0)

    def test_a_stale_reading_refuses_to_arm(self):
        """Arming against a memory is not arming against an account."""
        self._ibkr_backed(equity="500.00", age_seconds=48 * 3600)
        with patch(ROUTER, return_value=self._ibkr_client()):
            out = self._arm(capital=450)
        self.assertIn("old", out["error"])


class FundsTrackingTests(TestCase):
    """Phase B, operator-requested: pools that FOLLOW the broker's own
    reading — trade the funds actually available, not a typed number.
    The sync beat is the only writer; stale readings freeze new entries;
    at most one pool follows the account at a time."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("lv_t", password="x")

    def setUp(self):
        cache.clear()
        _quote("BTCUSD", 60000)
        _components_on()

    def _ibkr_backed(self, equity="500.00", age_seconds=0):
        from datetime import timedelta as _td
        from django.utils import timezone as _tz
        from bot_program.models import IBKRAccount
        acct = IBKRAccount.objects.create(
            user=self.user, label="ISA", host="ibgateway", port=4003,
            client_id=1)
        acct.set_credentials("U28134395")
        if equity is not None:
            acct.last_equity = Decimal(equity)
            acct.last_equity_currency = "EUR"
            acct.last_equity_at = _tz.now() - _td(seconds=age_seconds)
        acct.save()
        return acct

    def _ibkr_client(self):
        return type("IBKRTrader", (), {})()

    def _arm_tracking(self, **kw):
        from bot_program.manual_trade import arm_manual_lane
        args = dict(asset_class="crypto", mode="live", pin_ok=True,
                    track=True)
        args.update(kw)
        return arm_manual_lane(self.user, **args)

    def test_tracking_starts_by_becoming_the_account(self):
        self._ibkr_backed(equity="500.00")
        with patch(ROUTER, return_value=self._ibkr_client()):
            out = self._arm_tracking()
        self.assertTrue(out.get("ok"), out)
        self.assertTrue(out["tracks_broker"])
        self.assertEqual(out["capital"], 500.0)

    def test_tracking_refuses_a_venue_that_is_not_the_account(self):
        """The reading IS the IBKR account — a Binance-routed pool
        following it would size one venue's orders by another's money."""
        self._ibkr_backed(equity="500.00")
        with patch(ROUTER, return_value=_fake_live_client()):
            out = self._arm_tracking()
        self.assertIn("error", out)
        self.assertIn("route", out["error"])

    def test_only_one_pool_may_follow_the_account(self):
        """Two followers would each claim the same money in full."""
        _instrument("EURUSD", "forex")
        self._ibkr_backed(equity="500.00")
        with patch(ROUTER, return_value=self._ibkr_client()):
            first = self._arm_tracking()
            self.assertTrue(first.get("ok"), first)
            second = self._arm_tracking(asset_class="forex")
        self.assertIn("error", second)
        self.assertIn("already follows", second["error"])

    def test_disarming_clears_the_tracking_flag(self):
        self._ibkr_backed(equity="500.00")
        from bot_program.manual_trade import (arm_manual_lane,
                                              manual_config_for)
        with patch(ROUTER, return_value=self._ibkr_client()):
            self._arm_tracking()
        out = arm_manual_lane(self.user, asset_class="crypto", mode="paper")
        self.assertTrue(out.get("ok"), out)
        cfg = manual_config_for(self.user, "crypto")
        self.assertNotIn("capital_tracks_broker", cfg.extras or {})

    def test_the_sync_retunes_a_tracking_pool(self):
        self._ibkr_backed(equity="500.00")
        with patch(ROUTER, return_value=self._ibkr_client()):
            self._arm_tracking()
        from bot_program.tasks import _follow_the_account
        _follow_the_account(self.user, 612.34, "EUR")
        from bot_program.manual_trade import manual_config_for
        self.assertEqual(
            float(manual_config_for(self.user, "crypto").capital), 612.34)

    def test_the_sync_leaves_untracked_pools_alone(self):
        self._ibkr_backed(equity="500.00")
        from bot_program.manual_trade import arm_manual_lane
        with patch(ROUTER, return_value=self._ibkr_client()):
            out = arm_manual_lane(self.user, asset_class="crypto",
                                  mode="live", pin_ok=True, capital=450,
                                  track=False)
            self.assertTrue(out.get("ok"), out)
        from bot_program.tasks import _follow_the_account
        _follow_the_account(self.user, 612.34, "EUR")
        from bot_program.manual_trade import manual_config_for
        self.assertEqual(
            float(manual_config_for(self.user, "crypto").capital), 450.0)

    def test_a_stale_reading_freezes_live_manual_entries(self):
        self._ibkr_backed(equity="500.00")
        with patch(ROUTER, return_value=self._ibkr_client()):
            self._arm_tracking()
        from datetime import timedelta as _td
        from django.utils import timezone as _tz
        acct = self.user.ibkr_account
        acct.last_equity_at = _tz.now() - _td(hours=3)
        acct.save(update_fields=["last_equity_at"])
        from bot_program.manual_trade import execute_take_trade
        with patch(ROUTER, return_value=_fake_live_client()):
            out = execute_take_trade(
                self.user, _signal(_instrument("BTCUSD")), pin_ok=True)
        self.assertIn("error", out)
        self.assertIn("frozen", out["error"])

    def test_a_fresh_reading_does_not_freeze(self):
        self._ibkr_backed(equity="500.00")
        with patch(ROUTER, return_value=self._ibkr_client()):
            self._arm_tracking()
        from bot_program.capital_truth import tracking_freeze_reason
        from bot_program.manual_trade import manual_config_for
        self.assertIsNone(tracking_freeze_reason(
            self.user, manual_config_for(self.user, "crypto")))

    def test_bots_on_a_tracking_pool_freeze_on_a_stale_reading_too(self):
        """The freeze is generic: any live config that follows the
        account waits out a stale reading, bot or hand."""
        self._ibkr_backed(equity="500.00", age_seconds=3 * 3600)
        from bot_program.manual_trade import manual_config_for
        cfg = manual_config_for(self.user, "crypto")
        cfg.mode = "live"
        cfg.enabled = True
        ex = dict(cfg.extras or {})
        ex["capital_tracks_broker"] = True
        cfg.extras = ex
        cfg.save()
        from bot_program.asset_engine.base import make_bot
        ok, why = make_bot(cfg).can_open_new()
        self.assertFalse(ok)
        self.assertIn("reading", why)
