"""Phase-18 bot-trade backtester tests:
  - Exit simulation (TP, SL, expired, conservative SL-first when bar covers both)
  - End-to-end run_backtest with seeded signals + price bars
  - Stats computation (win rate, R, drawdown, profit factor, sharpe)
  - One-position-per-symbol + cooldown gating
  - View / persistence round-trip

Run with:  python manage.py test tests.test_phase18_backtest
"""
from datetime import datetime, timedelta, timezone as dt_tz
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase, Client
from django.utils import timezone


def _user(name="bt_u"):
    return User.objects.create_user(username=name, password="x")


def _instrument(symbol, asset_class="stock"):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class},
    )
    return inst


def _abc(user, asset_class, **kw):
    from bot_program.models import AssetBotConfig
    defaults = dict(
        enabled=True, mode="paper", symbols=[],
        capital=Decimal("10000"), base_currency="USD",
        position_size_pct=2.0, max_concurrent_positions=5,
        max_daily_loss_pct=2.0, stop_loss_pct=2.0, take_profit_pct=4.0,
        entry_score_min=0.6, min_signals_for_entry=1,
        timeframe="1h", cool_down_minutes=0,
    )
    defaults.update(kw)
    return AssetBotConfig.objects.create(
        user=user, asset_class=asset_class, name=defaults.pop("name", "T"),
        **defaults,
    )


def _bar(instrument, *, ts, o, h, low, c, timeframe="1h"):
    from market_data.models import PriceData
    return PriceData.objects.create(
        instrument=instrument, timeframe=timeframe, timestamp=ts,
        open=Decimal(str(o)), high=Decimal(str(h)),
        low=Decimal(str(low)), close=Decimal(str(c)),
        volume=0, source="test",
    )


def _signal(instrument, *, ts, direction, price, rule="r1", score=0.85):
    from signals.models import Signal
    s = Signal.objects.create(
        instrument=instrument, signal_type="composite", direction=direction,
        urgency="medium", title="t", description="t", rule_name=rule,
        score=score, sub_scores={},
        price_at_signal=Decimal(str(price)),
        suggested_entry=Decimal(str(price)),
    )
    Signal.objects.filter(pk=s.pk).update(created_at=ts)
    s.refresh_from_db()
    return s


# ── Exit simulation ──────────────────────────────────────────────────────

class ExitSimulationTests(TestCase):
    def setUp(self):
        self.inst = _instrument("AAPL")
        self.t0 = datetime(2026, 4, 1, 10, 0, tzinfo=dt_tz.utc)

    def test_buy_hits_target(self):
        from bot_program.backtest_asset import _simulate_exit
        # entry 100, sl 98, tp 104
        _bar(self.inst, ts=self.t0 + timedelta(hours=1), o=100, h=102, low=99.5, c=101)
        _bar(self.inst, ts=self.t0 + timedelta(hours=2), o=101, h=104.5, low=100, c=104)
        et, px, outcome = _simulate_exit(
            self.inst, "1h", self.t0, side="BUY", sl=98, tp=104, max_bars=10)
        self.assertEqual(outcome, "hit_target")
        self.assertEqual(px, 104)

    def test_buy_stopped_out(self):
        from bot_program.backtest_asset import _simulate_exit
        _bar(self.inst, ts=self.t0 + timedelta(hours=1), o=100, h=101, low=97.5, c=98)
        et, px, outcome = _simulate_exit(
            self.inst, "1h", self.t0, side="BUY", sl=98, tp=104, max_bars=10)
        self.assertEqual(outcome, "stopped_out")
        self.assertEqual(px, 98)

    def test_buy_sl_first_when_both_in_same_bar(self):
        """Conservative: when a bar covers both SL and TP, SL is assumed first."""
        from bot_program.backtest_asset import _simulate_exit
        _bar(self.inst, ts=self.t0 + timedelta(hours=1), o=100, h=105, low=97, c=103)
        et, px, outcome = _simulate_exit(
            self.inst, "1h", self.t0, side="BUY", sl=98, tp=104, max_bars=10)
        self.assertEqual(outcome, "stopped_out")
        self.assertEqual(px, 98)

    def test_sell_hits_target(self):
        from bot_program.backtest_asset import _simulate_exit
        # entry 100, sl 102 (above), tp 96 (below)
        _bar(self.inst, ts=self.t0 + timedelta(hours=1), o=100, h=101, low=98, c=99)
        _bar(self.inst, ts=self.t0 + timedelta(hours=2), o=99, h=99.5, low=95.5, c=96)
        et, px, outcome = _simulate_exit(
            self.inst, "1h", self.t0, side="SELL", sl=102, tp=96, max_bars=10)
        self.assertEqual(outcome, "hit_target")
        self.assertEqual(px, 96)

    def test_expired_when_neither_hit(self):
        from bot_program.backtest_asset import _simulate_exit
        # tight range, neither SL nor TP triggered
        _bar(self.inst, ts=self.t0 + timedelta(hours=1), o=100, h=100.5, low=99.5, c=100)
        _bar(self.inst, ts=self.t0 + timedelta(hours=2), o=100, h=100.4, low=99.6, c=100)
        et, px, outcome = _simulate_exit(
            self.inst, "1h", self.t0, side="BUY", sl=98, tp=104, max_bars=10)
        self.assertEqual(outcome, "expired")
        self.assertEqual(px, 100)

    def test_no_bars_returns_expired(self):
        from bot_program.backtest_asset import _simulate_exit
        et, px, outcome = _simulate_exit(
            self.inst, "1h", self.t0, side="BUY", sl=98, tp=104, max_bars=10)
        self.assertEqual(outcome, "expired")
        self.assertIsNone(et)


# ── End-to-end run_backtest ──────────────────────────────────────────────

class RunBacktestTests(TestCase):
    def setUp(self):
        self.user = _user()
        self.cfg = _abc(self.user, "stock", name="ST", symbols=["AAPL"],
                         stop_loss_pct=2.0, take_profit_pct=4.0)
        self.inst = _instrument("AAPL")
        self.start = datetime(2026, 4, 1, 9, 0, tzinfo=dt_tz.utc)
        self.end = datetime(2026, 4, 30, 23, 0, tzinfo=dt_tz.utc)

    def _seed_signal_and_bars(self, ts_offset_hours, direction="bullish",
                               *, sl_hit=False, tp_hit=True):
        sig_time = self.start + timedelta(hours=ts_offset_hours)
        _signal(self.inst, ts=sig_time, direction=direction, price=100,
                rule="r1")
        # entry=100, SL=98 (sl_pct=2%), TP=104 (tp_pct=4%)
        if direction == "bullish":
            if sl_hit:
                _bar(self.inst, ts=sig_time + timedelta(hours=1),
                     o=100, h=100.5, low=97, c=98)
            elif tp_hit:
                _bar(self.inst, ts=sig_time + timedelta(hours=1),
                     o=100, h=104.5, low=99.5, c=104)
            else:
                _bar(self.inst, ts=sig_time + timedelta(hours=1),
                     o=100, h=100.5, low=99.5, c=100)
        else:  # bearish: entry 100, SL 102, TP 96
            if sl_hit:
                _bar(self.inst, ts=sig_time + timedelta(hours=1),
                     o=100, h=102.5, low=99.5, c=102)
            elif tp_hit:
                _bar(self.inst, ts=sig_time + timedelta(hours=1),
                     o=100, h=100.5, low=95.5, c=96)
        # Cooldown clear: add a far-future bar so subsequent walks find data.
        _bar(self.inst, ts=sig_time + timedelta(hours=2),
             o=100, h=100, low=100, c=100)

    def test_winning_trade_produces_positive_r(self):
        from bot_program.backtest_asset import BacktestParams, run_backtest
        self._seed_signal_and_bars(1, direction="bullish", tp_hit=True)
        result = run_backtest(BacktestParams(
            config_id=self.cfg.id, start=self.start, end=self.end))
        self.assertEqual(len(result.trades), 1)
        t = result.trades[0]
        self.assertEqual(t.outcome, "hit_target")
        # R = (104-100)/(100-98) = 2.0
        self.assertEqual(t.realized_r, 2.0)

    def test_losing_trade_produces_minus_one_r(self):
        from bot_program.backtest_asset import BacktestParams, run_backtest
        self._seed_signal_and_bars(1, direction="bullish", sl_hit=True, tp_hit=False)
        result = run_backtest(BacktestParams(
            config_id=self.cfg.id, start=self.start, end=self.end))
        self.assertEqual(len(result.trades), 1)
        self.assertEqual(result.trades[0].outcome, "stopped_out")
        self.assertEqual(result.trades[0].realized_r, -1.0)

    def test_one_position_per_symbol(self):
        """A second signal during an open position is skipped."""
        from bot_program.backtest_asset import BacktestParams, run_backtest
        # Signal at h=1 stops out at h=2; cooldown=0 by default, so signal at h=3 should be picked up.
        # But signal at h=1.5 (mid-position) should be skipped.
        sig_time_1 = self.start + timedelta(hours=1)
        _signal(self.inst, ts=sig_time_1, direction="bullish", price=100, rule="r1")
        # Both SL hit at h=2 (i.e., position lasts 1 hour).
        _bar(self.inst, ts=self.start + timedelta(hours=2),
             o=100, h=100.5, low=97, c=98)
        # Mid-position signal: should be skipped.
        sig_mid = self.start + timedelta(hours=1, minutes=30)
        _signal(self.inst, ts=sig_mid, direction="bullish", price=100, rule="r1")

        result = run_backtest(BacktestParams(
            config_id=self.cfg.id, start=self.start, end=self.end))
        self.assertEqual(len(result.trades), 1)

    def test_no_symbols_returns_skipped(self):
        from bot_program.backtest_asset import BacktestParams, run_backtest
        cfg = _abc(self.user, "stock", name="empty", symbols=[])
        result = run_backtest(BacktestParams(
            config_id=cfg.id, start=self.start, end=self.end))
        self.assertEqual(result.skipped.get("reason"), "no_symbols")
        self.assertEqual(len(result.trades), 0)

    def test_signals_below_score_min_excluded(self):
        from bot_program.backtest_asset import BacktestParams, run_backtest
        # entry_score_min defaults to 0.6
        sig_time = self.start + timedelta(hours=1)
        _signal(self.inst, ts=sig_time, direction="bullish",
                price=100, rule="r1", score=0.50)  # below threshold
        result = run_backtest(BacktestParams(
            config_id=self.cfg.id, start=self.start, end=self.end))
        self.assertEqual(len(result.trades), 0)


# ── Stats computation ────────────────────────────────────────────────────

class StatsTests(TestCase):
    def _trade(self, **kw):
        from bot_program.backtest_asset import BacktestTrade
        defaults = dict(
            symbol="X", side="BUY", rule_name="r",
            entry_time=None, entry_price=100,
            stop_loss=98, take_profit=104,
            exit_time=None, exit_price=104,
            outcome="hit_target", realized_r=2.0,
            duration_minutes=60,
        )
        defaults.update(kw)
        return BacktestTrade(**defaults)

    def test_empty_returns_zeros(self):
        from bot_program.backtest_asset import compute_stats
        s = compute_stats([])
        self.assertEqual(s["n"], 0)
        self.assertEqual(s["total_r"], 0)

    def test_basic_stats(self):
        from bot_program.backtest_asset import compute_stats
        trades = [
            self._trade(realized_r=2.0, outcome="hit_target"),
            self._trade(realized_r=-1.0, outcome="stopped_out"),
            self._trade(realized_r=2.0, outcome="hit_target"),
        ]
        s = compute_stats(trades)
        self.assertEqual(s["n"], 3)
        self.assertEqual(s["n_wins"], 2)
        self.assertEqual(s["n_losses"], 1)
        self.assertAlmostEqual(s["win_rate"], 2/3, places=3)
        self.assertEqual(s["total_r"], 3.0)
        # gross_wins=4, gross_losses=1 → PF=4
        self.assertEqual(s["profit_factor"], 4.0)

    def test_max_drawdown_in_r(self):
        from bot_program.backtest_asset import compute_stats
        # equity curve: +2, +1 (-1), -1 (-2), +1 (+2). Peak 2 at trade-1, then drops to -1.
        trades = [
            self._trade(realized_r=2.0),
            self._trade(realized_r=-1.0),
            self._trade(realized_r=-2.0),
            self._trade(realized_r=2.0),
        ]
        s = compute_stats(trades)
        # Equity: 2, 1, -1, 1. Peak 2, lowest after peak = -1 → DD = 3.
        self.assertEqual(s["max_drawdown_r"], 3.0)

    def test_max_consecutive_losses(self):
        from bot_program.backtest_asset import compute_stats
        trades = [self._trade(realized_r=r) for r in [1, -1, -1, -1, 1, -1, -1]]
        s = compute_stats(trades)
        self.assertEqual(s["max_consecutive_losses"], 3)


# ── Persistence + view round-trip ────────────────────────────────────────

class BacktestViewTests(TestCase):
    def setUp(self):
        self.user = _user("bt_view_u")
        self.client = Client()
        self.client.force_login(self.user)

    def test_list_renders_empty(self):
        r = self.client.get("/bot-backtest/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "BOT BACKTEST")

    def test_run_persists_to_botbacktestrun(self):
        from bot_program.models import BotBacktestRun
        cfg = _abc(self.user, "stock", name="ST", symbols=["AAPL"])
        inst = _instrument("AAPL")
        # Seed a winning trade.
        sig_time = datetime(2026, 4, 5, 10, 0, tzinfo=dt_tz.utc)
        _signal(inst, ts=sig_time, direction="bullish", price=100, rule="r1")
        _bar(inst, ts=sig_time + timedelta(hours=1),
             o=100, h=104.5, low=99.5, c=104)

        r = self.client.post("/bot-backtest/run/", {
            "config_id": cfg.id,
            "start": "2026-04-01",
            "end": "2026-04-30",
        }, follow=True)
        self.assertEqual(r.status_code, 200)
        run = BotBacktestRun.objects.filter(user=self.user).first()
        self.assertIsNotNone(run)
        self.assertEqual(run.status, "complete")
        self.assertEqual(run.stats.get("n"), 1)
        self.assertEqual(len(run.trades_json), 1)

    def test_detail_view_renders(self):
        from bot_program.models import BotBacktestRun
        run = BotBacktestRun.objects.create(
            user=self.user, config_name_snapshot="X",
            asset_class_snapshot="stock",
            stats={"n": 0}, trades_json=[], status="complete",
        )
        r = self.client.get(f"/bot-backtest/{run.id}/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, f"BACKTEST #{run.id}")

    def test_invalid_dates_show_error(self):
        cfg = _abc(self.user, "stock", name="ST", symbols=["AAPL"])
        r = self.client.post("/bot-backtest/run/", {
            "config_id": cfg.id,
            "start": "not-a-date",
            "end": "2026-04-30",
        }, follow=True)
        self.assertEqual(r.status_code, 200)
        # Form-level error should bring us back to the list.
        self.assertContains(r, "BOT BACKTEST")
