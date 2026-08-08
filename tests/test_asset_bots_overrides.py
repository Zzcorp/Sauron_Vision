"""Phase 13.4/13.5 tests:
  - ForexBot session-aware decide()
  - StockBot earnings-blackout decide()
  - tick-asset-bots beat schedule entry registered

Run with:  python manage.py test tests.test_asset_bots_overrides
"""
from datetime import datetime, timedelta, timezone as dt_tz
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone


def _instrument(symbol, asset_class="forex"):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class},
    )
    return inst


def _user(name="ovr_user"):
    return User.objects.create_user(username=name, password="x")


def _config(user, asset_class, **overrides):
    from bot_program.models import AssetBotConfig
    defaults = dict(
        user=user, asset_class=asset_class, name="Test",
        enabled=True, mode="paper",
        symbols=[], capital=Decimal("10000"), base_currency="USD",
        position_size_pct=2.0, max_concurrent_positions=5,
        max_daily_loss_pct=2.0, stop_loss_pct=1.5, take_profit_pct=3.0,
        entry_score_min=0.6, min_signals_for_entry=1,
    )
    defaults.update(overrides)
    return AssetBotConfig.objects.create(**defaults)


def _bullish_signal(symbol, asset_class, score=0.85, rule="rule_a"):
    """Helper to seed an active bullish signal so super().decide() returns BUY."""
    from signals.models import Signal
    inst = _instrument(symbol, asset_class)
    return Signal.objects.create(
        instrument=inst, signal_type="composite", direction="bullish",
        urgency="medium", title="t", description="t", rule_name=rule,
        score=score, sub_scores={},
        price_at_signal=Decimal("100"), suggested_entry=Decimal("100"),
    )


# ── Active forex session helper ─────────────────────────────────────────────

class ActiveForexSessionsTests(TestCase):
    def test_weekend_returns_empty(self):
        from bot_program.asset_engine.forex_bot import _active_forex_sessions
        # Saturday 12:00 UTC (2026-05-02 is a Saturday)
        sat_noon = datetime(2026, 5, 2, 12, 0, tzinfo=dt_tz.utc)
        self.assertEqual(_active_forex_sessions(sat_noon), set())

    def test_friday_evening_after_close_returns_empty(self):
        from bot_program.asset_engine.forex_bot import _active_forex_sessions
        # Friday 22:00 UTC (after weekly close)
        fri_late = datetime(2026, 5, 1, 22, 0, tzinfo=dt_tz.utc)
        self.assertEqual(_active_forex_sessions(fri_late), set())

    def test_sunday_after_2100_active(self):
        from bot_program.asset_engine.forex_bot import _active_forex_sessions
        # Sunday 22:00 UTC = Sydney session opens
        sun_late = datetime(2026, 5, 3, 22, 0, tzinfo=dt_tz.utc)
        active = _active_forex_sessions(sun_late)
        self.assertIn("sydney", active)

    def test_monday_london_ny_overlap(self):
        from bot_program.asset_engine.forex_bot import _active_forex_sessions
        # Monday 14:00 UTC = London (07:00-15:30) AND NY (13:30-20:00)
        mon = datetime(2026, 5, 4, 14, 0, tzinfo=dt_tz.utc)
        active = _active_forex_sessions(mon)
        self.assertIn("london", active)
        self.assertIn("new_york", active)

    def test_monday_morning_tokyo_and_sydney_overlap(self):
        from bot_program.asset_engine.forex_bot import _active_forex_sessions
        # Monday 03:00 UTC = Tokyo (00-06) AND Sydney (21-05 wrap) both active.
        mon = datetime(2026, 5, 4, 3, 0, tzinfo=dt_tz.utc)
        active = _active_forex_sessions(mon)
        self.assertEqual(active, {"tokyo", "sydney"})

    def test_monday_pre_london_tokyo_only(self):
        from bot_program.asset_engine.forex_bot import _active_forex_sessions
        # Monday 06:30 UTC = Tokyo closed (06:00), Sydney closed (05:00),
        # London not yet open (07:00). So no session active.
        mon = datetime(2026, 5, 4, 6, 30, tzinfo=dt_tz.utc)
        active = _active_forex_sessions(mon)
        self.assertEqual(active, set())


# ── ForexBot session-aware decide ──────────────────────────────────────────

class ForexBotDecideTests(TestCase):
    def setUp(self):
        self.user = _user()

    def _patched_now(self, dt):
        """Patch the imports `forex_bot` uses for `now`."""
        from unittest.mock import patch
        return patch("bot_program.asset_engine.forex_bot.timezone.now", return_value=dt)

    def test_holds_on_weekend(self):
        from bot_program.asset_engine import ForexBot
        cfg = _config(self.user, "forex", symbols=["EURUSD"])
        _bullish_signal("EURUSD", "forex")
        sat = datetime(2026, 5, 2, 12, 0, tzinfo=dt_tz.utc)
        with self._patched_now(sat):
            decision = ForexBot(cfg).decide("EURUSD")
        self.assertEqual(decision.direction, "HOLD")
        self.assertIn("weekend", decision.reasons[0].lower())

    def test_holds_outside_preferred_session(self):
        """EURUSD prefers london+new_york. At 03:00 UTC Monday only Tokyo is active."""
        from bot_program.asset_engine import ForexBot
        cfg = _config(self.user, "forex", symbols=["EURUSD"])
        _bullish_signal("EURUSD", "forex")
        mon_tokyo = datetime(2026, 5, 4, 3, 0, tzinfo=dt_tz.utc)
        with self._patched_now(mon_tokyo):
            decision = ForexBot(cfg).decide("EURUSD")
        self.assertEqual(decision.direction, "HOLD")
        self.assertIn("outside preferred sessions", decision.reasons[0])

    def test_buys_inside_preferred_session(self):
        """EURUSD at 14:00 UTC Monday — London/NY overlap; default decide() should fire."""
        from bot_program.asset_engine import ForexBot
        cfg = _config(self.user, "forex", symbols=["EURUSD"])
        _bullish_signal("EURUSD", "forex", score=0.9)
        mon_overlap = datetime(2026, 5, 4, 14, 0, tzinfo=dt_tz.utc)
        with self._patched_now(mon_overlap):
            decision = ForexBot(cfg).decide("EURUSD")
        self.assertEqual(decision.direction, "BUY")

    def test_pair_specific_jpy_active_in_tokyo(self):
        """USDJPY prefers tokyo+new_york. At 03:00 UTC Monday Tokyo is active → BUY."""
        from bot_program.asset_engine import ForexBot
        cfg = _config(self.user, "forex", symbols=["USDJPY"])
        _bullish_signal("USDJPY", "forex", score=0.9)
        mon_tokyo = datetime(2026, 5, 4, 3, 0, tzinfo=dt_tz.utc)
        with self._patched_now(mon_tokyo):
            decision = ForexBot(cfg).decide("USDJPY")
        self.assertEqual(decision.direction, "BUY")

    def test_extras_override_preferred_sessions(self):
        """Admin override via extras["preferred_sessions"]."""
        from bot_program.asset_engine import ForexBot
        cfg = _config(self.user, "forex", symbols=["EURUSD"],
                      extras={"preferred_sessions": {"EURUSD": ["tokyo"]}})
        _bullish_signal("EURUSD", "forex", score=0.9)
        mon_tokyo = datetime(2026, 5, 4, 3, 0, tzinfo=dt_tz.utc)
        with self._patched_now(mon_tokyo):
            decision = ForexBot(cfg).decide("EURUSD")
        self.assertEqual(decision.direction, "BUY")  # admin allowed Tokyo

    def test_extras_disable_session_filter(self):
        """extras['session_filter_disabled']=True bypasses session timing entirely."""
        from bot_program.asset_engine import ForexBot
        cfg = _config(self.user, "forex", symbols=["EURUSD"],
                      extras={"session_filter_disabled": True})
        _bullish_signal("EURUSD", "forex", score=0.9)
        # Even on Saturday, with the filter off, it should fall through to default decide.
        sat = datetime(2026, 5, 2, 12, 0, tzinfo=dt_tz.utc)
        with self._patched_now(sat):
            decision = ForexBot(cfg).decide("EURUSD")
        self.assertEqual(decision.direction, "BUY")


# ── StockBot earnings-blackout decide ──────────────────────────────────────

class StockBotEarningsBlackoutTests(TestCase):
    def setUp(self):
        self.user = _user()

    def _add_earnings_event(self, symbol, days_ahead, title=None):
        """Seed an EconomicEvent that the blackout helper will detect."""
        from market_data.models import EconomicEvent
        title = title or f"{symbol} Q1 Earnings"
        return EconomicEvent.objects.create(
            title=title, country="US", impact="high",
            datetime=timezone.now() + timedelta(days=days_ahead),
            source="test",
        )

    def test_blackout_triggers_when_earnings_within_window(self):
        from bot_program.asset_engine import StockBot
        cfg = _config(self.user, "stock", symbols=["AAPL"])
        _bullish_signal("AAPL", "stock", score=0.9)
        self._add_earnings_event("AAPL", days_ahead=2)  # within default 3-day window
        decision = StockBot(cfg).decide("AAPL")
        self.assertEqual(decision.direction, "HOLD")
        self.assertIn("earnings blackout", decision.reasons[0])

    def test_no_blackout_when_earnings_far_away(self):
        from bot_program.asset_engine import StockBot
        cfg = _config(self.user, "stock", symbols=["AAPL"])
        _bullish_signal("AAPL", "stock", score=0.9)
        self._add_earnings_event("AAPL", days_ahead=30)  # outside window
        decision = StockBot(cfg).decide("AAPL")
        self.assertEqual(decision.direction, "BUY")

    def test_no_blackout_when_no_earnings_event(self):
        from bot_program.asset_engine import StockBot
        cfg = _config(self.user, "stock", symbols=["AAPL"])
        _bullish_signal("AAPL", "stock", score=0.9)
        decision = StockBot(cfg).decide("AAPL")
        self.assertEqual(decision.direction, "BUY")

    def test_extras_disable_earnings_filter(self):
        from bot_program.asset_engine import StockBot
        cfg = _config(self.user, "stock", symbols=["AAPL"],
                      extras={"earnings_blackout_disabled": True})
        _bullish_signal("AAPL", "stock", score=0.9)
        self._add_earnings_event("AAPL", days_ahead=1)  # would normally HOLD
        decision = StockBot(cfg).decide("AAPL")
        self.assertEqual(decision.direction, "BUY")  # filter disabled

    def test_extras_custom_blackout_days(self):
        """With a 7-day blackout, earnings 5 days ahead should now trigger HOLD."""
        from bot_program.asset_engine import StockBot
        cfg = _config(self.user, "stock", symbols=["AAPL"],
                      extras={"earnings_blackout_days": 7})
        _bullish_signal("AAPL", "stock", score=0.9)
        self._add_earnings_event("AAPL", days_ahead=5)
        decision = StockBot(cfg).decide("AAPL")
        self.assertEqual(decision.direction, "HOLD")

    def test_unrelated_earnings_event_does_not_block(self):
        """Earnings event for a different symbol must not block this one."""
        from bot_program.asset_engine import StockBot
        cfg = _config(self.user, "stock", symbols=["AAPL"])
        _bullish_signal("AAPL", "stock", score=0.9)
        # MSFT earnings — title doesn't contain "AAPL"
        self._add_earnings_event("MSFT", days_ahead=2)
        decision = StockBot(cfg).decide("AAPL")
        self.assertEqual(decision.direction, "BUY")


# ── Phase 13.5: beat schedule entry registered ─────────────────────────────

class BeatScheduleTests(TestCase):
    def test_tick_asset_bots_in_beat_schedule(self):
        from config.celery import app
        schedule = app.conf.beat_schedule
        self.assertIn("tick-asset-bots", schedule)
        entry = schedule["tick-asset-bots"]
        self.assertEqual(entry["task"], "bot_program.tasks.tick_all_asset_bots")
        # 5-minute interval (300s) — could be a number or crontab; we accept either.
        sched = entry["schedule"]
        if isinstance(sched, (int, float)):
            self.assertEqual(sched, 300.0)
