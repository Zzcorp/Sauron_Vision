"""The seven decisions that were held back, and what each one settled.

An adversarial sweep produced 34 fixes. Twenty-seven were unambiguous and
landed. Seven were not: each one contained a real bug wrapped in a change
nobody asked for, or a fix whose escalation told the operator the opposite
of the truth, or a correction whose historical rows needed a decision of
their own. Parking them was right; leaving them parked was not.

These tests hold the RESOLUTIONS, and in several cases the resolution is
a refusal — the session filter keeps its widths, the risk gate keeps its
book scope. Those are the assertions most worth having: a later sweep will
propose the same widening again, and it should have to argue with a test.

Run with:  python manage.py test tests.test_parked_decisions
"""
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.utils import timezone


# ═══ 1. Price alerts: 'cross' was true of every finite number ═══════════

class ACrossNeedsASideToCrossFromTests(TestCase):
    """`price >= target or price <= target` is a tautology. Every 'cross'
    alert fired on the first beat whatever the market was doing, sent its
    notification, and — being consumed — could never fire when the level
    was actually crossed."""

    def _alert(self, target="100", condition="cross"):
        from alerts.models import PriceAlert
        from market_data.models import Instrument
        user = User.objects.create_user(f"px_{condition}_{target}",
                                        password="x")
        inst, _ = Instrument.objects.get_or_create(
            symbol="XCROSS", defaults={"name": "X", "asset_class": "stock"})
        return PriceAlert.objects.create(
            user=user, instrument=inst, condition=condition,
            target_price=Decimal(target))

    def test_the_first_sighting_arms_and_does_not_fire(self):
        from alerts.models import _cross_triggered
        a = self._alert()
        self.assertFalse(_cross_triggered(a, Decimal("95")))
        a.refresh_from_db()
        self.assertEqual(a.baseline_price, Decimal("95"))

    def test_it_fires_when_the_price_reaches_the_other_side(self):
        from alerts.models import _cross_triggered
        a = self._alert()
        _cross_triggered(a, Decimal("95"))          # arm below
        self.assertTrue(_cross_triggered(a, Decimal("101")))

    def test_movement_on_the_same_side_is_not_a_crossing(self):
        from alerts.models import _cross_triggered
        a = self._alert()
        _cross_triggered(a, Decimal("95"))
        self.assertFalse(_cross_triggered(a, Decimal("99.99")))

    def test_a_second_worker_cannot_overwrite_the_baseline(self):
        """A rewritten baseline is a crossing erased."""
        from alerts.models import PriceAlert, _cross_triggered
        a = self._alert()
        _cross_triggered(a, Decimal("95"))
        again = PriceAlert.objects.get(pk=a.pk)
        again.baseline_price = None                 # a stale in-memory copy
        _cross_triggered(again, Decimal("105"))
        a.refresh_from_db()
        self.assertEqual(a.baseline_price, Decimal("95"))

    def test_a_fossil_quote_fires_nothing(self):
        """An alert fired against a stale quote says a level broke "now"
        when it broke, or did not break, at some unknown time before the
        feed stopped."""
        from alerts.models import PriceAlert, check_price_alerts
        from market_data.models import LiveQuote
        a = self._alert(condition="above", target="10")
        q = LiveQuote.objects.create(instrument=a.instrument,
                                     last=Decimal("500"))
        LiveQuote.objects.filter(pk=q.pk).update(
            updated_at=timezone.now() - timedelta(hours=6))
        check_price_alerts()
        self.assertFalse(PriceAlert.objects.get(pk=a.pk).triggered)

    def test_a_fresh_quote_still_fires(self):
        from alerts.models import PriceAlert, check_price_alerts
        from market_data.models import LiveQuote
        a = self._alert(condition="above", target="10")
        LiveQuote.objects.create(instrument=a.instrument, last=Decimal("500"))
        check_price_alerts()
        self.assertTrue(PriceAlert.objects.get(pk=a.pk).triggered)


# ═══ 2. Circuit breakers: what a breaker that cannot run means ══════════

class ABreakerThatCannotRunSaysSoTests(TestCase):
    """The parked objection was that failing CLOSED here contradicts
    `preflight`, which fails open loudly and documents why. It does — and
    both breakers query the same shared database preflight does, so the
    blast radius is the same fleet. The resolution keeps the house posture
    and fixes what was actually wrong: the SILENCE."""

    def _cfg(self, **extras):
        from bot_program.models import AssetBotConfig
        user = User.objects.create_user(f"brk_{len(extras)}_{id(extras)}",
                                        password="x")
        return AssetBotConfig.objects.create(
            user=user, asset_class="stock", name="BRK", mode="paper",
            symbols=["AAPL"], capital=Decimal("10000"), enabled=True,
            extras=extras)

    def test_a_typo_in_a_threshold_leaves_the_breaker_armed(self):
        """`float("10%")` used to raise straight past the breaker. A config
        error is not the transient kind that argues for standing aside."""
        from bot_program.asset_engine.safety import (
            DEFAULT_MAX_DRAWDOWN_PCT, _knob,
        )
        cfg = self._cfg(max_drawdown_pct="10%")
        self.assertEqual(
            _knob(cfg, cfg.extras, "max_drawdown_pct",
                  DEFAULT_MAX_DRAWDOWN_PCT),
            float(DEFAULT_MAX_DRAWDOWN_PCT))

    def test_a_good_value_is_still_honoured(self):
        from bot_program.asset_engine.safety import _knob
        cfg = self._cfg(max_drawdown_pct=4.5)
        self.assertEqual(_knob(cfg, cfg.extras, "max_drawdown_pct", 10.0), 4.5)

    def test_a_breaker_that_raises_does_not_halt_the_fleet(self):
        from unittest.mock import patch

        from bot_program.asset_engine.safety import CircuitBreakers
        cb = CircuitBreakers(self._cfg())
        with patch.object(CircuitBreakers, "check_drawdown_from_peak",
                          side_effect=RuntimeError("db gone")):
            ok, reasons = cb.check_all()
        self.assertTrue(ok, "a transient database fault must not stop "
                            "every config on the platform")
        self.assertEqual(reasons, [])

    def test_but_it_is_never_silent_about_it(self):
        """(True, []) was byte-identical to both breakers passing. That is
        the bug: the bot kept opening with nothing watching its drawdown
        while every screen showed it as fine."""
        from unittest.mock import patch

        from bot_program.asset_engine.safety import CircuitBreakers
        cb = CircuitBreakers(self._cfg())
        with patch.object(CircuitBreakers, "check_drawdown_from_peak",
                          side_effect=RuntimeError("db gone")):
            cb.check_all()
        self.assertEqual(len(cb.blind), 1)
        self.assertIn("could not be evaluated", cb.blind[0])

    def test_a_clean_pass_leaves_nothing_blind(self):
        from bot_program.asset_engine.safety import CircuitBreakers
        cb = CircuitBreakers(self._cfg())
        ok, reasons = cb.check_all()
        self.assertTrue(ok)
        self.assertEqual(cb.blind, [])


class ExtrasSurviveAConcurrentEditTests(TestCase):
    """The runner loads a config ONCE and holds it for a whole tick, then
    the heartbeat wrote the entire JSON column back from that snapshot. An
    operator who tightened risk mid-tick had it silently reverted."""

    def test_a_heartbeat_does_not_revert_the_operators_edit(self):
        from bot_program.asset_engine.safety import _save_extras
        from bot_program.models import AssetBotConfig
        user = User.objects.create_user("extras_u", password="x")
        cfg = AssetBotConfig.objects.create(
            user=user, asset_class="stock", name="X", mode="paper",
            symbols=["AAPL"], capital=Decimal("10000"), enabled=True,
            extras={"risk_per_trade_pct": 2.0})
        held = AssetBotConfig.objects.get(pk=cfg.pk)   # the tick's snapshot

        # The operator tightens risk on the HQ form, mid-tick.
        AssetBotConfig.objects.filter(pk=cfg.pk).update(
            extras={"risk_per_trade_pct": 0.5})

        # ...and the heartbeat fires from the stale snapshot.
        _save_extras(held, last_tick_at="now")

        fresh = AssetBotConfig.objects.get(pk=cfg.pk)
        self.assertEqual(fresh.extras["risk_per_trade_pct"], 0.5,
                         "the heartbeat wrote back a risk the operator had "
                         "already removed")
        self.assertEqual(fresh.extras["last_tick_at"], "now")


# ═══ 3. Forex sessions: DST, yes. A wider filter, no. ═══════════════════

class SessionsRideTheCentresOwnClocksTests(SimpleTestCase):
    """The fixed UTC table is the liquid windows read in each centre's
    SUMMER time, so for four months a year it refused the 16:00 London fix
    and cut New York off at 15:00 local — mid-session."""

    def _at(self, zone, y, m, d, h, minute=0):
        return datetime(y, m, d, h, minute,
                        tzinfo=ZoneInfo(zone)).astimezone(ZoneInfo("UTC"))

    def test_london_still_trades_at_16_00_in_january(self):
        from bot_program.asset_engine.forex_bot import _active_forex_sessions
        # A January Wednesday, 16:00 London (GMT) = 16:00 UTC — outside the
        # old [7, 15.5) UTC window entirely.
        moment = self._at("Europe/London", 2026, 1, 14, 16, 0)
        self.assertIn("london", _active_forex_sessions(moment))

    def test_new_york_still_trades_at_15_30_in_january(self):
        from bot_program.asset_engine.forex_bot import _active_forex_sessions
        moment = self._at("America/New_York", 2026, 1, 14, 15, 30)
        self.assertIn("new_york", _active_forex_sessions(moment))

    def test_the_windows_keep_their_widths(self):
        """The correction is to WHEN each window falls, not to how wide it
        is. A session filter that admits more hours is a different risk
        posture than the operator configured, and nothing asked for that."""
        from bot_program.asset_engine.forex_bot import SESSION_WINDOWS_LOCAL
        widths = {name: round(end - start, 2)
                  for name, (_z, start, end) in SESSION_WINDOWS_LOCAL.items()}
        self.assertEqual(widths, {"tokyo": 6.0, "london": 8.5,
                                  "new_york": 6.5, "sydney": 8.0})

    def test_the_filter_does_not_cover_the_whole_day(self):
        """The union of the four windows must still leave the quiet hours
        out — a filter that is always on is not a filter."""
        from bot_program.asset_engine.forex_bot import _active_forex_sessions
        quiet = 0
        base = datetime(2026, 7, 15, 0, 0, tzinfo=ZoneInfo("UTC"))  # a Wed
        for hour in range(24):
            if not _active_forex_sessions(base + timedelta(hours=hour)):
                quiet += 1
        self.assertGreater(quiet, 0, "every hour of the day is in session — "
                                     "the liquidity filter admits everything")

    def test_the_week_opens_sunday_evening_new_york(self):
        from bot_program.asset_engine.forex_bot import forex_market_open
        self.assertFalse(forex_market_open(
            self._at("America/New_York", 2026, 7, 12, 16, 0)))   # Sun 16:00
        self.assertTrue(forex_market_open(
            self._at("America/New_York", 2026, 7, 12, 18, 0)))   # Sun 18:00

    def test_the_week_closes_friday_evening_new_york(self):
        from bot_program.asset_engine.forex_bot import forex_market_open
        self.assertTrue(forex_market_open(
            self._at("America/New_York", 2026, 7, 17, 16, 0)))
        self.assertFalse(forex_market_open(
            self._at("America/New_York", 2026, 7, 17, 18, 0)))

    def test_saturday_is_closed(self):
        from bot_program.asset_engine.forex_bot import forex_market_open
        self.assertFalse(forex_market_open(
            self._at("America/New_York", 2026, 7, 18, 12, 0)))


class AQuietHourIsNotTheWeekendTests(TestCase):
    """`decide()` read an empty session set as the weekend, so on every
    weekday the fleet declined ticks with "forex market closed (weekend)"
    while the market was open. The operator then goes looking at weekend
    logic to explain a refusal that has nothing to do with it."""

    def test_the_two_questions_have_different_answers(self):
        from bot_program.asset_engine.forex_bot import (
            _active_forex_sessions, forex_market_open,
        )
        base = datetime(2026, 7, 15, 0, 0, tzinfo=ZoneInfo("UTC"))
        found = False
        for hour in range(24):
            moment = base + timedelta(hours=hour)
            if forex_market_open(moment) and not _active_forex_sessions(moment):
                found = True
                break
        self.assertTrue(found, "no weekday hour distinguishes them — the "
                               "split has nothing to describe")

    def test_the_refusal_names_the_real_reason(self):
        from unittest.mock import patch

        from bot_program.asset_engine.forex_bot import ForexBot
        from bot_program.models import AssetBotConfig
        user = User.objects.create_user("fx_quiet_u", password="x")
        cfg = AssetBotConfig.objects.create(
            user=user, asset_class="forex", name="FX", mode="paper",
            symbols=["EURUSD"], capital=Decimal("10000"), enabled=True)
        with patch("bot_program.asset_engine.forex_bot.forex_market_open",
                   return_value=True), \
             patch("bot_program.asset_engine.forex_bot."
                   "_active_forex_sessions", return_value=set()):
            decision = ForexBot(cfg).decide("EURUSD")
        self.assertEqual(decision.direction, "HOLD")
        joined = " ".join(decision.reasons).lower()
        self.assertIn("no major forex session", joined)
        self.assertNotIn("weekend", joined)


# ═══ 4. The composite news leg: awake, but not at full volume ═══════════

class TheNewsLegReadsTheModelThatExistsTests(TestCase):
    """It asked for `scraping.models.NewsItem`, which has never existed.
    The ImportError went into a bare except and the leg returned a flat 0
    for every symbol on every bar — so a config that authored 0.3 of its
    weight to news was damping its own composite by that whole 0.3."""

    def _article(self, title, sentiment, hours_ago=1):
        from scraping.models import NewsArticle
        a = NewsArticle.objects.create(
            title=title, url=f"http://x/{title}{sentiment}",
            published_at=timezone.now() - timedelta(hours=hours_ago),
            ai_sentiment_score=sentiment)
        return a

    def test_it_finds_graded_articles_now(self):
        from bot_program.engine.strategy import _score_news
        for i in range(3):
            self._article(f"BTC rallies {i}", 0.8)
        score, notes = _score_news("BTCUSDT")
        self.assertGreater(score, 0)
        self.assertTrue(notes)

    def test_one_article_does_not_arrive_at_full_conviction(self):
        """The raw balance reaches ±1.00 on a single article. That was
        harmless while the leg was dead; waking it up made it live."""
        from bot_program.engine.strategy import _score_news
        self._article("BTC rallies", 0.9)
        score, _ = _score_news("BTCUSDT")
        self.assertLess(abs(score), 1.0)
        self.assertGreater(abs(score), 0.0)

    def test_enough_articles_do(self):
        from bot_program.engine.strategy import (
            NEWS_FULL_WEIGHT_ARTICLES, _score_news,
        )
        for i in range(NEWS_FULL_WEIGHT_ARTICLES):
            self._article(f"BTC rallies {i}", 0.9)
        score, _ = _score_news("BTCUSDT")
        self.assertAlmostEqual(score, 1.0, places=6)

    def test_an_ungraded_article_contributes_nothing(self):
        """None is not neutral — it means the analyst has not read it."""
        from bot_program.engine.strategy import _score_news
        self._article("BTC something", None)
        self.assertEqual(_score_news("BTCUSDT"), (0, []))

    def test_articles_naming_another_asset_are_not_counted(self):
        from bot_program.engine.strategy import _score_news
        for i in range(3):
            self._article(f"ETH rallies {i}", 0.9)
        self.assertEqual(_score_news("BTCUSDT"), (0, []))


# ═══ 5. Tax lots: a yen gain filed in a dollar column ═══════════════════

class TaxLotsBookInAccountCurrencyTests(TestCase):
    """(sale - cost) x qty on a USDJPY row is a yen figure, and it went
    straight into a column every tax report reads as dollars: a 33-dollar
    gain filed as 5,000. Right sign, right symbol, 150x wrong."""

    def _forex_trade(self, rate):
        from bot_program.models import AssetBotConfig, AssetBotTrade
        user = User.objects.create_user(f"tl_{rate}", password="x")
        cfg = AssetBotConfig.objects.create(
            user=user, asset_class="forex", name="FX", mode="paper",
            symbols=["USDJPY"], capital=Decimal("10000"), enabled=True)
        return AssetBotTrade(
            config=cfg, asset_class="forex", symbol="USDJPY", side="SELL",
            qty=Decimal("1000"), entry_price=Decimal("150"),
            exit_price=Decimal("155"), status="CLOSED",
            metadata={"value_per_unit": rate})

    def test_a_forex_gain_is_converted_at_the_entry_rate(self):
        from bot_program.tax_lots import _account_ccy_rate
        trade = self._forex_trade(0.0066)
        self.assertAlmostEqual(float(_account_ccy_rate(trade)), 0.0066,
                               places=6)

    def test_a_share_is_left_alone(self):
        from bot_program.models import AssetBotConfig, AssetBotTrade
        from bot_program.tax_lots import _account_ccy_rate
        user = User.objects.create_user("tl_stock", password="x")
        cfg = AssetBotConfig.objects.create(
            user=user, asset_class="stock", name="S", mode="paper",
            symbols=["AAPL"], capital=Decimal("10000"), enabled=True)
        trade = AssetBotTrade(config=cfg, asset_class="stock", symbol="AAPL",
                              side="SELL", qty=Decimal("10"),
                              entry_price=Decimal("100"))
        self.assertEqual(_account_ccy_rate(trade), Decimal("1"))

    def test_the_backfill_refuses_to_invent_a_rate(self):
        """The historical rows are wrong and need correcting — but a made-up
        rate on a tax record is the same class of error the correction
        exists to remove. A row with no entry rate on file is reported and
        skipped, never converted at today's price."""
        from pathlib import Path

        from django.conf import settings
        src = (Path(settings.BASE_DIR) / "bot_program" / "management"
               / "commands" / "backfill_taxlot_currency.py"
               ).read_text(encoding="utf-8")
        self.assertIn("value_per_unit", src)
        self.assertIn("REPORTED", src)

    def test_the_backfill_is_a_dry_run_until_told_otherwise(self):
        from io import StringIO

        from django.core.management import call_command
        out = StringIO()
        call_command("backfill_taxlot_currency", stdout=out)
        self.assertIn("nothing was saved", out.getvalue())


# ═══ 6. A flat position is not a stranded one ══════════════════════════

class NoScratchExitsTests(TestCase):
    """`_mark_price` fell back to the entry price, and two callers book the
    mark AS the exit: a stop-out that cost 450 dollars was recorded as
    exit == entry, pnl 0.00, realized_r 0.0 — invisible to the daily-loss
    gate and a break-even trade in the promotion record."""

    def _trade(self):
        from bot_program.models import AssetBotConfig, AssetBotTrade
        user = User.objects.create_user("flat_u", password="x")
        cfg = AssetBotConfig.objects.create(
            user=user, asset_class="stock", name="F", mode="live",
            symbols=["AAPL"], capital=Decimal("10000"), enabled=True)
        return AssetBotTrade.objects.create(
            config=cfg, asset_class="stock", symbol="AAPL", side="BUY",
            qty=Decimal("10"), entry_price=Decimal("100"),
            status="CLOSE_PENDING", paper=False, opened_at=timezone.now())

    def test_no_price_means_none_not_the_entry_price(self):
        from unittest.mock import MagicMock

        from bot_program.pending_closes import _mark_price
        client = MagicMock()
        client.ticker.return_value = {}
        self.assertIsNone(_mark_price(self._trade(), client))

    def test_a_real_price_still_comes_back(self):
        from unittest.mock import MagicMock

        from bot_program.pending_closes import _mark_price
        client = MagicMock()
        client.ticker.return_value = {"lastPrice": "95.5"}
        self.assertEqual(_mark_price(self._trade(), client),
                         Decimal("95.5"))

    def test_an_unpriced_flat_row_waits_rather_than_booking_a_scratch(self):
        from unittest.mock import MagicMock

        from bot_program.models import AssetBotTrade
        from bot_program.pending_closes import _finalise_flat
        trade = self._trade()
        client = MagicMock()
        client.ticker.return_value = {}
        self.assertFalse(_finalise_flat(trade, client, reason="X"))
        row = AssetBotTrade.objects.get(pk=trade.pk)
        self.assertEqual(row.status, "CLOSE_PENDING")
        self.assertIsNone(row.exit_price)

    def test_it_is_not_escalated_as_a_stranded_position(self):
        """`_after_failed_attempt` ends at `_give_up`, whose whole
        vocabulary — "stranded", "STILL OPEN at the broker", "close it
        manually" — is the opposite of what is true here. The broker is
        FLAT. Sending the operator to chase a position that does not exist
        is worse than the wait."""
        from unittest.mock import MagicMock

        from bot_program.models import AssetBotTrade
        from bot_program.pending_closes import _attempts, _finalise_flat
        trade = self._trade()
        client = MagicMock()
        client.ticker.return_value = {}
        before = _attempts(trade)
        _finalise_flat(trade, client, reason="X")
        row = AssetBotTrade.objects.get(pk=trade.pk)
        self.assertEqual(_attempts(row), before,
                         "a missing quote counted toward abandonment")

    def test_but_the_operator_is_told(self):
        """It waits with a voice, not in silence."""
        from unittest.mock import MagicMock

        from alerts.models import Notification
        from bot_program.pending_closes import _finalise_flat
        trade = self._trade()
        client = MagicMock()
        client.ticker.return_value = {}
        _finalise_flat(trade, client, reason="X")
        note = Notification.objects.filter(user=trade.config.user).first()
        self.assertIsNotNone(note)
        self.assertIn("flat", note.body.lower())

    def test_a_priced_flat_row_closes_normally(self):
        from unittest.mock import MagicMock

        from bot_program.models import AssetBotTrade
        from bot_program.pending_closes import _finalise_flat
        trade = self._trade()
        client = MagicMock()
        client.ticker.return_value = {"lastPrice": "95.5"}
        self.assertTrue(_finalise_flat(trade, client, reason="X"))
        row = AssetBotTrade.objects.get(pk=trade.pk)
        self.assertEqual(row.status, "CLOSED")
        self.assertEqual(row.exit_price, Decimal("95.5"))


class OneCloseAtATimeTests(TestCase):
    """The sweep iterated a plain queryset with no row lock and no look at
    the claim the CLOSE button takes. Two live closes on one position makes
    a flatten into a naked reverse."""

    def _pending(self):
        from bot_program.models import AssetBotConfig, AssetBotTrade
        user = User.objects.create_user("claim_u", password="x")
        cfg = AssetBotConfig.objects.create(
            user=user, asset_class="stock", name="C", mode="live",
            symbols=["AAPL"], capital=Decimal("10000"), enabled=True)
        return AssetBotTrade.objects.create(
            config=cfg, asset_class="stock", symbol="AAPL", side="BUY",
            qty=Decimal("10"), entry_price=Decimal("100"),
            status="CLOSE_PENDING", paper=False, opened_at=timezone.now())

    def test_a_row_can_be_claimed_once(self):
        from bot_program.pending_closes import _claim_for_retry
        trade = self._pending()
        self.assertIsNotNone(_claim_for_retry(trade.pk))
        self.assertIsNone(_claim_for_retry(trade.pk),
                          "a second worker took the same row")

    def test_it_is_the_same_claim_the_close_button_takes(self):
        """Not a second private one — the beat and the button have to
        exclude each other, not just their own kind."""
        from bot_program.manual_close import CLAIM_KEY
        from bot_program.models import AssetBotTrade
        from bot_program.pending_closes import _claim_for_retry
        trade = self._pending()
        _claim_for_retry(trade.pk)
        self.assertIn(CLAIM_KEY,
                      AssetBotTrade.objects.get(pk=trade.pk).metadata)

    def test_a_row_that_closed_meanwhile_is_not_claimed(self):
        from bot_program.models import AssetBotTrade
        from bot_program.pending_closes import _claim_for_retry
        trade = self._pending()
        AssetBotTrade.objects.filter(pk=trade.pk).update(status="CLOSED")
        self.assertIsNone(_claim_for_retry(trade.pk))


# ═══ 7. Simulated money cannot pay for a real loss ═════════════════════

class LiveAndPaperAreJudgedApartTests(TestCase):
    """`paper` is not a property of a config an operator can reason about
    from outside: a LIVE config runs its paper-stage rules on the paper
    venue at full size, and every hand-taken TAKE TRADE is paper today. So
    one book routinely carries both — and netting them let a book that lost
    2,400 of real money report +200 and keep trading."""

    def setUp(self):
        self.user = User.objects.create_user("venue_u", password="x")
        from bot_program.models import AssetBotConfig
        self.cfg = AssetBotConfig.objects.create(
            user=self.user, asset_class="stock", name="V", mode="live",
            symbols=["AAPL"], capital=Decimal("10000"), enabled=True)

    def _closed(self, pnl, paper):
        from bot_program.models import AssetBotTrade
        return AssetBotTrade.objects.create(
            config=self.cfg, asset_class="stock", symbol="AAPL", side="BUY",
            qty=Decimal("1"), entry_price=Decimal("100"),
            exit_price=Decimal("100"), pnl=Decimal(str(pnl)),
            status="CLOSED", paper=paper,
            opened_at=timezone.now() - timedelta(hours=2),
            closed_at=timezone.now() - timedelta(hours=1))

    def _open(self, notional, paper):
        from bot_program.models import AssetBotTrade
        return AssetBotTrade.objects.create(
            config=self.cfg, asset_class="stock", symbol="AAPL", side="BUY",
            qty=Decimal("1"), entry_price=Decimal(str(notional)),
            status="OPEN", paper=paper, opened_at=timezone.now())

    def test_a_simulated_profit_cannot_hide_a_real_loss(self):
        from portfolio.risk_gate import limits_book, realized_since
        self._closed(-2400, paper=False)
        self._closed(2600, paper=True)
        window = realized_since(self.user, limits_book())
        self.assertEqual(window["realized"], -2400.0)
        self.assertEqual(window["live_realized"], -2400.0)
        self.assertEqual(window["paper_realized"], 2600.0)

    def test_two_venues_down_are_not_one_book_down_twice(self):
        """The reverse arithmetic is a bug too: two venues each 200 down is
        not a 400-down day on a book that only lost the live 200."""
        from portfolio.risk_gate import limits_book, realized_since
        self._closed(-200, paper=False)
        self._closed(-200, paper=True)
        self.assertEqual(realized_since(self.user, limits_book())["realized"],
                         -200.0)

    def test_an_empty_venue_is_not_a_zero_to_compare_against(self):
        """On a book that only trades live, min(live, paper) with an empty
        paper side would report a +500 day as a flat one."""
        from portfolio.risk_gate import limits_book, realized_since
        self._closed(500, paper=False)
        self.assertEqual(realized_since(self.user, limits_book())["realized"],
                         500.0)

    def test_simulated_positions_do_not_hold_the_live_ceiling(self):
        from portfolio.risk_gate import limits_book, open_capital_at_work
        self._open(1000, paper=False)
        for _ in range(5):
            self._open(1000, paper=True)
        book = open_capital_at_work(self.user, limits_book())
        self.assertEqual(book["live_total"], 1000.0)
        self.assertEqual(book["paper_total"], 5000.0)
        # The larger binds — but the two are never added into 6000.
        self.assertEqual(book["total"], 5000.0)

    def test_the_refusal_names_which_venue_filled_the_ceiling(self):
        """"You are fully invested" and "your paper experiment is holding
        your live ceiling" are different sentences and the operator acts on
        them differently."""
        from portfolio.risk_gate import exposure_state, limits_book
        book = limits_book()
        book.current_value = Decimal("10000")
        book.max_total_exposure_pct = 10
        book.save()
        # OVER the 1,000 ceiling, so the refusal branch is the one that runs.
        # At 900 the gate returned ok=True and this assertion passed against
        # the NON-refusal sentence — so deleting the venue split from the
        # halt message, which is the sentence an operator reads in an
        # emergency, would have left the test green.
        self._open(700, paper=True)
        self._open(700, paper=True)
        state = exposure_state(self.user, portfolio=book)
        self.assertFalse(state["ok"], state["reason"])
        self.assertIn("paper", state["reason"].lower())

    def test_a_live_entry_is_not_refused_by_a_big_paper_book(self):
        """The other half of the same rule. `committed` defaults to the
        LARGER venue, which is the right summary for a card and the wrong
        judge for a live ticket: five simulated positions must not refuse a
        real one, which is the netting defect this split removed, pointed
        the other way."""
        from portfolio.risk_gate import exposure_state, limits_book
        book = limits_book()
        book.current_value = Decimal("10000")
        book.max_total_exposure_pct = 10
        book.save()
        for _ in range(5):
            self._open(900, paper=True)
        self._open(100, paper=False)
        live = exposure_state(self.user, portfolio=book, venue="live")
        self.assertTrue(live["ok"], live["reason"])
        paper = exposure_state(self.user, portfolio=book, venue="paper")
        self.assertFalse(paper["ok"])

    def test_the_ceiling_refuses_the_ticket_that_would_breach_it(self):
        """Not the one after. Without `adding` the gate can only answer "am
        I already over?", so a book at 950 of a 1,000 ceiling clears, the
        scan opens at the single-position cap, and the book ends the pass
        over a limit nothing refused."""
        from portfolio.risk_gate import exposure_state, limits_book
        book = limits_book()
        book.current_value = Decimal("10000")
        book.max_total_exposure_pct = 10
        book.save()
        self._open(950, paper=False)
        self.assertTrue(
            exposure_state(self.user, portfolio=book, venue="live")["ok"])
        tight = exposure_state(self.user, portfolio=book, venue="live",
                               adding=100.0)
        self.assertFalse(tight["ok"])
        self.assertIn("would take total exposure past", tight["reason"])

    def test_the_book_scope_of_the_money_gates_is_unchanged(self):
        """The parked objection was that this change arrived entangled with
        a widening of WHICH BOOKS the money gates measure. That is a live
        question about the risk denominator and it is not settled here —
        the venue split must not smuggle it in."""
        import inspect

        from portfolio import risk_gate
        src = inspect.getsource(risk_gate.open_capital_at_work)
        self.assertIn("portfolio=portfolio", src)
        self.assertNotIn("_gate_books", src)
