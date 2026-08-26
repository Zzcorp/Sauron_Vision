"""The safety layer the operator trusts, and the signal evidence beneath it.

Seven things that were quietly false at once, all of them invisible from the
product:

  * A live OPTIONS config in shadow mode kept buying real premium. The chip
    on the headband said "decides, submits nothing"; `OptionsBot.scan_symbol`
    overrides the base method wholesale and simply never had the gate.
  * Every heartbeat rewrote the whole `extras` JSON from the snapshot the tick
    started with, so an operator who cut `risk_per_trade_pct` mid-tick had it
    reverted within seconds, with no error and no log line.
  * A typo in one `extras` field (`"10%"`) turned a circuit breaker off, and
    `check_all` returned the same `(True, [])` a passing breaker returns.
  * The opportunity scanner wrote a second identical Signal every time a setup
    re-matched, and the bot's consensus sums evidence per ROW — one rule voting
    twice with its own conviction.
  * `evaluate_signal_outcome` put the 7-day TTL behind a price gate, so the
    signals on instruments nothing quotes any more were the only ones that
    could never expire, and they kept voting.
  * SmcSignal grading bounded its quote lookup at 900s and then fell through
    to a PriceData bar of ANY age — a dead feed became measured evidence that
    a setup loses.
  * The forex session table was fixed UTC with two one-hour holes, and an
    empty session set was reported as the weekend — on a Tuesday.

Run with:  python manage.py test tests.test_signal_and_safety_truth
"""
from datetime import datetime, timedelta, timezone as dt_tz
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.utils import timezone


# ── shared builders ─────────────────────────────────────────────────────

def _user(name):
    return User.objects.create_user(username=name, password="x")


def _instrument(symbol, asset_class="stock"):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class})
    return inst


def _cfg(user, **kw):
    from bot_program.models import AssetBotConfig
    defaults = dict(user=user, asset_class="stock", name="T", mode="paper",
                    symbols=["AAPL"], capital=Decimal("100000"), enabled=True,
                    base_currency="USD", position_size_pct=2.0,
                    max_concurrent_positions=5, max_daily_loss_pct=2.0,
                    stop_loss_pct=20.0, take_profit_pct=50.0,
                    entry_score_min=0.6, min_signals_for_entry=1)
    defaults.update(kw)
    return AssetBotConfig.objects.create(**defaults)


# ── shadow mode reaches the options lane ────────────────────────────────

class OptionsShadowModeTests(TestCase):
    """Shadow mode is the one control an operator uses to say "compute, do not
    spend". The options lane honoured it nowhere: it submitted live orders and
    booked paper=False rows while every surface reported it as submitting
    nothing."""

    def setUp(self):
        from bot_program.options_models import OptionContract
        self.user = _user("shadow_opt_u")
        self.inst = _instrument("AAPL", "stock")
        self.cfg = _cfg(self.user, asset_class="options", name="Opt",
                        mode="live", symbols=["AAPL"],
                        capital=Decimal("1000000"))
        self.contract = OptionContract.objects.create(
            underlying=self.inst, strike=Decimal("180"),
            expiry=timezone.now().date() + timedelta(days=30), right="C",
            multiplier=100, bid=Decimal("1.00"), ask=Decimal("1.02"),
            last_price=Decimal("1.01"), iv=0.30, delta=0.41)

    def _scan(self, client):
        from bot_program.asset_engine.base import BotDecision
        from bot_program.asset_engine.options_bot import OptionsBot
        bot = OptionsBot(self.cfg)
        corr = {"scale": 1.0, "max_corr": 0.1, "peer": "", "threshold": 0.7,
                "measured": True, "reason": ""}
        with patch.object(bot, "decide",
                          return_value=BotDecision("BUY", 0.9, ["signal"])), \
                patch("bot_program.engine.broker_router.client_for_symbol",
                      return_value=client), \
                patch("portfolio.risk_gate.correlation_state",
                      return_value=corr):
            return bot.scan_symbol("AAPL")

    def _client(self):
        client = MagicMock()
        client.market_order_option.return_value = {
            "orderId": "1", "status": "FILLED"}
        return client

    def test_the_same_pass_does_submit_when_shadow_is_off(self):
        """Control: without shadow_until this harness reaches the broker, so
        the assertions below are about the gate and not about a pass that
        never got there."""
        from bot_program.models import AssetBotTrade
        client = self._client()
        res = self._scan(client)
        self.assertIsNotNone(res)
        client.market_order_option.assert_called_once()
        self.assertTrue(
            AssetBotTrade.objects.filter(config=self.cfg,
                                         paper=False).exists())

    def test_a_shadow_options_config_submits_no_order_and_books_no_row(self):
        from bot_program.models import AssetBotTrade
        from bot_program.asset_engine.safety import enable_shadow
        enable_shadow(self.cfg, hours=24)
        client = self._client()

        res = self._scan(client)

        self.assertIsNone(res)
        client.market_order_option.assert_not_called()
        client.market_order.assert_not_called()
        self.assertFalse(AssetBotTrade.objects.filter(config=self.cfg).exists())

    def test_the_shadow_skip_is_recorded_so_the_bot_can_explain_itself(self):
        from bot_program.asset_engine import skips
        from bot_program.asset_engine.safety import enable_shadow
        enable_shadow(self.cfg, hours=24)

        self._scan(self._client())

        self.cfg.refresh_from_db()
        recorded = (self.cfg.extras or {}).get("skips", {}).get("AAPL", {})
        self.assertEqual(recorded.get("code"), skips.SHADOW)


# ── extras is the operator's, not the tick's ────────────────────────────

class ExtrasPersistenceTests(TestCase):
    """A tick holds one config instance for ~40 seconds and writes extras at
    least three times inside it. Merging onto that stale snapshot meant the
    heartbeat reverted whatever the operator changed in the meantime."""

    def setUp(self):
        self.user = _user("extras_u")
        self.cfg = _cfg(self.user, extras={"risk_per_trade_pct": 1.0})

    def test_an_operator_risk_edit_mid_tick_survives_the_next_heartbeat(self):
        from bot_program.models import AssetBotConfig
        from bot_program.asset_engine.safety import write_heartbeat

        # The tick is holding `self.cfg`, loaded before the edit.
        AssetBotConfig.objects.filter(pk=self.cfg.pk).update(
            extras={"risk_per_trade_pct": 0.25})

        write_heartbeat(self.cfg, status="OK", note="ok")

        self.cfg.refresh_from_db()
        self.assertEqual(self.cfg.extras["risk_per_trade_pct"], 0.25)

    def test_the_rest_of_the_tick_reads_the_operators_new_value(self):
        from bot_program.models import AssetBotConfig
        from bot_program.asset_engine.safety import write_heartbeat

        AssetBotConfig.objects.filter(pk=self.cfg.pk).update(
            extras={"risk_per_trade_pct": 0.25})
        write_heartbeat(self.cfg, status="OK", note="ok")

        # Not just on disk: the in-memory instance the tick keeps using.
        self.assertEqual(self.cfg.extras["risk_per_trade_pct"], 0.25)

    def test_a_shadow_window_set_mid_tick_is_not_erased_by_a_skip(self):
        from bot_program.models import AssetBotConfig
        from bot_program.asset_engine import skips
        from bot_program.asset_engine.safety import is_shadow

        until = (timezone.now() + timedelta(hours=24)).isoformat()
        AssetBotConfig.objects.filter(pk=self.cfg.pk).update(
            extras={"risk_per_trade_pct": 1.0, "shadow_until": until})

        skips.record(self.cfg, "AAPL", skips.NO_SIGNALS, "nothing to trade")

        self.cfg.refresh_from_db()
        self.assertTrue(is_shadow(self.cfg))

    def test_the_key_the_write_owns_still_lands(self):
        from bot_program.asset_engine.safety import write_heartbeat
        write_heartbeat(self.cfg, status="OK", note="all good")
        self.cfg.refresh_from_db()
        self.assertEqual(self.cfg.extras["last_tick_status"], "OK")
        self.assertIn("last_tick_at", self.cfg.extras)


# ── a breaker that cannot answer is not a breaker that cleared ──────────

class CircuitBreakerHonestyTests(TestCase):
    def setUp(self):
        self.user = _user("breaker_u")

    def _losing_history(self, cfg, n=8):
        from bot_program.models import AssetBotTrade
        for i in range(n):
            AssetBotTrade.objects.create(
                config=cfg, asset_class="stock", symbol="AAPL", side="BUY",
                qty=Decimal("1"), entry_price=Decimal("100"),
                exit_price=Decimal("50"), pnl=Decimal("-5000"),
                status="CLOSED", paper=True,
                closed_at=timezone.now() - timedelta(minutes=n - i))

    def test_a_non_numeric_drawdown_knob_leaves_the_breaker_armed(self):
        """`float("10%")` raised, check_all continued past it, and can_open_new
        read the silence as "cleared" — so the bot traded through a drawdown
        the operator believed was capped."""
        from bot_program.asset_engine.safety import CircuitBreakers
        cfg = _cfg(self.user, capital=Decimal("10000"),
                   extras={"max_drawdown_pct": "10%", "max_loss_streak": 0})
        self._losing_history(cfg)

        allowed, reasons = CircuitBreakers(cfg).check_all()

        self.assertFalse(allowed)
        self.assertTrue(any("drawdown" in r for r in reasons))

    def test_a_null_knob_falls_back_to_the_shipped_default(self):
        from bot_program.asset_engine.safety import CircuitBreakers
        cfg = _cfg(self.user, capital=Decimal("10000"),
                   extras={"max_drawdown_pct": None, "max_loss_streak": 0})
        self._losing_history(cfg)

        allowed, reasons = CircuitBreakers(cfg).check_all()

        self.assertFalse(allowed)

    def test_a_breaker_that_raises_halts_instead_of_reporting_clear(self):
        from bot_program.asset_engine.safety import CircuitBreakers
        cfg = _cfg(self.user, extras={})
        breakers = CircuitBreakers(cfg)
        with patch.object(CircuitBreakers, "check_drawdown_from_peak",
                          side_effect=RuntimeError("db gone")):
            allowed, reasons = breakers.check_all()

        self.assertFalse(allowed)
        self.assertTrue(any("could not be evaluated" in r for r in reasons))

    def test_a_clean_config_still_clears_both_breakers(self):
        from bot_program.asset_engine.safety import CircuitBreakers
        cfg = _cfg(self.user, extras={})
        allowed, reasons = CircuitBreakers(cfg).check_all()
        self.assertTrue(allowed)
        self.assertEqual(reasons, [])


# ── one rule, one vote ──────────────────────────────────────────────────

class OpportunityScannerDedupeTests(TestCase):
    """The bot's consensus sums evidence per Signal ROW. A setup that still
    matched on a later pass wrote a second identical row and voted twice with
    one rule's conviction, which is enough to carry a direction on its own."""

    def setUp(self):
        from signals.models import OpportunitySetup
        from market_data.models import PriceData
        self.inst = _instrument("DUPE1", "stock")
        PriceData.objects.create(
            instrument=self.inst, timeframe="1d",
            timestamp=timezone.now() - timedelta(hours=1),
            open=Decimal("100"), high=Decimal("100"), low=Decimal("100"),
            close=Decimal("100"), volume=0, source="test")
        self.setup = OpportunitySetup.objects.create(
            name="dupe_setup", direction="bullish", conditions=[],
            min_match_score=0.0, suggested_horizon_days=5, asset_classes=[],
            sizing={"stop_pct": 2.0, "target_rr": 2.0}, is_active=True)

    def _scan(self):
        from signals.opportunity_scanner import scan_setup
        return scan_setup(self.setup, self.inst, as_of=False)

    def test_a_setup_that_matches_twice_leaves_one_active_signal(self):
        from signals.models import Signal
        first = self._scan()
        second = self._scan()

        self.assertTrue(first["matched"])
        self.assertTrue(second["matched"])
        self.assertEqual(
            Signal.objects.filter(instrument=self.inst,
                                  rule_name="dupe_setup",
                                  is_active=True).count(), 1)
        self.assertEqual(first["signal_id"], second["signal_id"])

    def test_the_second_match_still_records_its_own_flag(self):
        """Deduping the vote must not cost the scanner its own history — the
        flag is what /opportunities/ and the resolver read."""
        from signals.models import OpportunityFlag
        self._scan()
        self._scan()
        self.assertEqual(
            OpportunityFlag.objects.filter(setup=self.setup,
                                           instrument=self.inst).count(), 2)

    def test_a_closed_signal_does_not_block_the_next_one(self):
        from signals.models import Signal
        self._scan()
        Signal.objects.filter(instrument=self.inst).update(
            is_active=False, outcome="expired", expired_at=timezone.now())

        self._scan()

        self.assertEqual(
            Signal.objects.filter(instrument=self.inst,
                                  rule_name="dupe_setup").count(), 2)


# ── age is answerable without a price ───────────────────────────────────

class SignalExpiryWithoutPriceTests(TestCase):
    """The TTL sat behind the price gate, so the signals that most needed
    expiring — the ones on an instrument nothing quotes any more — were the
    only ones that could never expire. They stayed is_active and kept voting
    in AssetBot.decide() forever."""

    def setUp(self):
        self.inst = _instrument("NOQUOTE", "stock")

    def _signal(self, age_days):
        from signals.models import Signal
        sig = Signal.objects.create(
            instrument=self.inst, signal_type="composite",
            direction="bullish", urgency="medium", title="t",
            description="d", rule_name="r_old", score=0.8, sub_scores={},
            price_at_signal=Decimal("100"), suggested_entry=Decimal("100"),
            suggested_stop=Decimal("95"), suggested_target=Decimal("110"),
            is_active=True)
        Signal.objects.filter(pk=sig.pk).update(
            created_at=timezone.now() - timedelta(days=age_days))
        sig.refresh_from_db()
        return sig

    def test_a_signal_past_its_ttl_expires_with_no_price_available(self):
        from signals.performance import evaluate_signal_outcome
        sig = self._signal(age_days=10)

        outcome = evaluate_signal_outcome(sig)

        self.assertEqual(outcome, "expired")
        sig.refresh_from_db()
        self.assertFalse(sig.is_active)
        self.assertIsNotNone(sig.expired_at)

    def test_an_expiry_with_no_price_records_no_r_rather_than_a_flat_one(self):
        """A fabricated 0.0 would enter the decay tracker and the allocator as
        a measurement nobody made."""
        from signals.performance import evaluate_signal_outcome
        sig = self._signal(age_days=10)
        evaluate_signal_outcome(sig)
        sig.refresh_from_db()
        self.assertIsNone(sig.realized_r)

    def test_a_signal_inside_its_ttl_is_left_alone_when_there_is_no_price(self):
        from signals.performance import evaluate_signal_outcome
        sig = self._signal(age_days=1)

        outcome = evaluate_signal_outcome(sig)

        self.assertIsNone(outcome)
        sig.refresh_from_db()
        self.assertTrue(sig.is_active)

    def test_a_priced_expiry_still_marks_to_market(self):
        from signals.performance import evaluate_signal_outcome
        sig = self._signal(age_days=10)
        evaluate_signal_outcome(sig, current_price=Decimal("102"))
        sig.refresh_from_db()
        self.assertEqual(sig.outcome, "expired")
        self.assertIsNotNone(sig.realized_r)


# ── a dead feed is not evidence ─────────────────────────────────────────

class SmcFossilPriceTests(TestCase):
    """`_latest_price` bounded the LiveQuote branch at 900s and then fell
    through to the newest PriceData bar of ANY age. Every ACTIVE card on a
    symbol whose ingestion had stopped was stamped INVALIDATED at -1.0R on
    every pass — losses that never happened, handed to get_hit_rate as a
    measurement and from there into the composite that sizes live entries."""

    def setUp(self):
        self.inst = _instrument("DEADFEED", "stock")

    def _bar(self, close, age_hours):
        from market_data.models import PriceData
        PriceData.objects.create(
            instrument=self.inst, timeframe="1h",
            timestamp=timezone.now() - timedelta(hours=age_hours),
            open=Decimal(str(close)), high=Decimal(str(close)),
            low=Decimal(str(close)), close=Decimal(str(close)),
            volume=0, source="test")

    def test_a_three_day_old_bar_is_not_a_price(self):
        from signals.lifecycle import _latest_price
        self._bar(94.0, age_hours=72)
        self.assertIsNone(_latest_price("DEADFEED", "1h"))

    def test_a_recent_bar_still_is(self):
        from signals.lifecycle import _latest_price
        self._bar(94.0, age_hours=1)
        self.assertAlmostEqual(_latest_price("DEADFEED", "1h"), 94.0, places=4)

    def test_a_daily_card_tolerates_a_day_old_bar(self):
        """The bound is scaled by timeframe: a 1d card's newest bar is
        legitimately a day old, and bounding it at the 1h figure would stop
        every daily card grading."""
        from signals.lifecycle import _latest_price
        self._bar(94.0, age_hours=20)
        self.assertAlmostEqual(_latest_price("DEADFEED", "1d"), 94.0, places=4)

    def test_a_fossil_does_not_invalidate_a_live_card(self):
        from signals.models_smc import SmcSignal
        from signals.lifecycle import transition_signal
        self._bar(94.0, age_hours=72)  # below the stop, but three days dead
        sig = SmcSignal.objects.create(
            symbol="DEADFEED", timeframe="1h", setup="FVG_TAP",
            direction="LONG", headline="h", thesis="t", invalidation="i",
            entry=100.0, stop=95.0, target=110.0, r_multiple=2.0)

        self.assertEqual(transition_signal(sig), "ACTIVE")
        sig.refresh_from_db()
        self.assertIsNone(sig.realized_r)

    def test_a_card_on_a_dead_feed_still_expires_at_its_ttl(self):
        """Bounding the price must not simply move the damage: a card nobody
        can grade has to leave the rail rather than sit ACTIVE forever."""
        from signals.models_smc import SmcSignal
        from signals.lifecycle import transition_signal
        self._bar(94.0, age_hours=72)
        sig = SmcSignal.objects.create(
            symbol="DEADFEED", timeframe="1h", setup="FVG_TAP",
            direction="LONG", headline="h", thesis="t", invalidation="i",
            entry=100.0, stop=95.0, target=110.0, r_multiple=2.0)
        SmcSignal.objects.filter(pk=sig.pk).update(
            created_at=timezone.now() - timedelta(days=30))
        sig.refresh_from_db()

        self.assertEqual(transition_signal(sig), "EXPIRED")
        sig.refresh_from_db()
        self.assertIsNone(sig.realized_r)


# ── forex sessions in the centres' own clocks ───────────────────────────

class ForexSessionCoverageTests(SimpleTestCase):
    """The UTC table left holes at 06:00-07:00 and 20:00-21:00, and decide()
    reads an empty session set as the weekend — so the fleet declined ~24 FX
    ticks every weekday with a reason that sent the operator into the weekend
    logic. Fixed UTC hours also cannot follow DST: New York was cut off at
    15:00 local through the winter, mid-session."""

    def _at(self, iso):
        return datetime.fromisoformat(iso).replace(tzinfo=dt_tz.utc)

    def test_a_weekday_hour_is_never_reported_as_the_weekend(self):
        from bot_program.asset_engine.forex_bot import forex_market_open
        # Tuesday 20:30 UTC and Monday 06:30 UTC — both used to come back
        # empty, and both are plainly inside the trading week.
        self.assertTrue(forex_market_open(self._at("2026-12-08T20:30")))
        self.assertTrue(forex_market_open(self._at("2026-05-04T06:30")))

    def test_the_two_old_holes_are_covered_by_a_real_session(self):
        from bot_program.asset_engine.forex_bot import _active_forex_sessions
        self.assertTrue(_active_forex_sessions(self._at("2026-12-08T20:30")))
        self.assertTrue(_active_forex_sessions(self._at("2026-05-04T06:30")))

    def test_new_york_is_in_session_at_1530_local_in_december(self):
        from bot_program.asset_engine.forex_bot import _active_forex_sessions
        active = _active_forex_sessions(self._at("2026-12-08T20:30"))
        self.assertIn("new_york", active)

    def test_the_london_fix_hour_is_inside_the_london_session_in_winter(self):
        """15:30-16:30 UTC in December is 15:30-16:30 London and contains the
        16:00 fix. The old table closed London at 15:30 UTC year-round."""
        from bot_program.asset_engine.forex_bot import _active_forex_sessions
        self.assertIn("london",
                      _active_forex_sessions(self._at("2026-12-08T16:00")))

    def test_the_pre_london_hour_is_not_london_in_winter(self):
        from bot_program.asset_engine.forex_bot import _active_forex_sessions
        self.assertNotIn("london",
                         _active_forex_sessions(self._at("2026-12-08T07:30")))

    def test_the_weekly_close_and_open_still_hold(self):
        from bot_program.asset_engine.forex_bot import (
            _active_forex_sessions, forex_market_open,
        )
        # Saturday, and Friday after the 17:00 New York close.
        self.assertFalse(forex_market_open(self._at("2026-05-02T12:00")))
        self.assertFalse(forex_market_open(self._at("2026-05-01T22:00")))
        self.assertEqual(_active_forex_sessions(self._at("2026-05-02T12:00")),
                         set())
        # Sunday after the 17:00 New York open.
        self.assertTrue(forex_market_open(self._at("2026-05-03T22:00")))


class ForexSessionReasonTests(TestCase):
    def setUp(self):
        self.user = _user("fx_reason_u")

    def test_a_quiet_hour_is_not_explained_as_the_weekend(self):
        """21:00-22:00 UTC in northern summer really is between the New York
        close and the Sydney open. The refusal is right; calling it the
        weekend on a Tuesday is what sent the operator hunting."""
        from bot_program.asset_engine.forex_bot import ForexBot
        cfg = _cfg(self.user, asset_class="forex", name="FX",
                   symbols=["EURUSD"])
        tuesday_quiet = datetime(2026, 7, 7, 21, 30, tzinfo=dt_tz.utc)
        with patch("bot_program.asset_engine.forex_bot.timezone.now",
                   return_value=tuesday_quiet):
            decision = ForexBot(cfg).decide("EURUSD")

        self.assertEqual(decision.direction, "HOLD")
        self.assertNotIn("weekend", decision.reasons[0].lower())
        self.assertIn("no major forex session", decision.reasons[0])

    def test_the_weekend_is_still_explained_as_the_weekend(self):
        from bot_program.asset_engine.forex_bot import ForexBot
        cfg = _cfg(self.user, asset_class="forex", name="FX",
                   symbols=["EURUSD"])
        saturday = datetime(2026, 5, 2, 12, 0, tzinfo=dt_tz.utc)
        with patch("bot_program.asset_engine.forex_bot.timezone.now",
                   return_value=saturday):
            decision = ForexBot(cfg).decide("EURUSD")

        self.assertEqual(decision.direction, "HOLD")
        self.assertIn("weekend", decision.reasons[0].lower())
