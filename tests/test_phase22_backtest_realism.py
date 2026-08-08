"""Phase-22 backtest enhancements:
  - Transaction cost subtracted from realized_r
  - Slippage applied at entry + exit
  - Walk-forward train/test split with separate stats

Run with:  python manage.py test tests.test_phase22_backtest_realism
"""
from datetime import datetime, timedelta, timezone as dt_tz
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase


def _user(name="bt22_u"):
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
        enabled=True, mode="paper", symbols=["AAPL"],
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


def _signal(instrument, *, ts, direction="bullish", price=100,
            rule="r1", score=0.85):
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


# ── Transaction cost ─────────────────────────────────────────────────────

class TransactionCostTests(TestCase):
    def setUp(self):
        self.user = _user("tc_u")
        # SL = 2%, TP = 4%
        self.cfg = _abc(self.user, "stock", name="ST", symbols=["AAPL"])
        self.inst = _instrument("AAPL")
        self.start = datetime(2026, 4, 1, 9, 0, tzinfo=dt_tz.utc)
        self.end = datetime(2026, 4, 30, 23, 0, tzinfo=dt_tz.utc)

    def _seed_winning_trade(self):
        sig_time = self.start + timedelta(hours=1)
        _signal(self.inst, ts=sig_time, direction="bullish", price=100, rule="r1")
        _bar(self.inst, ts=sig_time + timedelta(hours=1),
             o=100, h=104.5, low=99.5, c=104)

    def test_zero_cost_unchanged(self):
        from bot_program.backtest_asset import BacktestParams, run_backtest
        self._seed_winning_trade()
        result = run_backtest(BacktestParams(
            config_id=self.cfg.id, start=self.start, end=self.end))
        self.assertEqual(result.trades[0].realized_r, 2.0)

    def test_cost_subtracted(self):
        """SL=2%, tx_cost=0.10% (round-trip). 0.10/2.0 = 0.05R subtracted."""
        from bot_program.backtest_asset import BacktestParams, run_backtest
        self._seed_winning_trade()
        result = run_backtest(BacktestParams(
            config_id=self.cfg.id, start=self.start, end=self.end,
            transaction_cost_pct=0.10))
        self.assertAlmostEqual(result.trades[0].realized_r, 2.0 - 0.05, places=4)

    def test_high_cost_can_flip_sign(self):
        """A barely-winning trade can become a loss after costs."""
        from bot_program.backtest_asset import BacktestParams, run_backtest
        self._seed_winning_trade()
        # 5% round-trip is huge — 5/2 = 2.5R; 2.0R win becomes -0.5R.
        result = run_backtest(BacktestParams(
            config_id=self.cfg.id, start=self.start, end=self.end,
            transaction_cost_pct=5.0))
        self.assertLess(result.trades[0].realized_r, 0)


# ── Slippage ─────────────────────────────────────────────────────────────

class SlippageTests(TestCase):
    def setUp(self):
        self.user = _user("sl_u")
        self.cfg = _abc(self.user, "stock", name="ST", symbols=["AAPL"])
        self.inst = _instrument("AAPL")
        self.start = datetime(2026, 4, 1, 9, 0, tzinfo=dt_tz.utc)
        self.end = datetime(2026, 4, 30, 23, 0, tzinfo=dt_tz.utc)

    def _seed_tp_hit(self):
        sig_time = self.start + timedelta(hours=1)
        _signal(self.inst, ts=sig_time, direction="bullish", price=100)
        _bar(self.inst, ts=sig_time + timedelta(hours=1),
             o=100, h=104.5, low=99.5, c=104)

    def test_slippage_reduces_winning_r(self):
        from bot_program.backtest_asset import BacktestParams, run_backtest
        self._seed_tp_hit()
        # 0.5% one-way slippage: entry slipped up to 100.5, TP slipped down to ~103.48
        # PnL_per_unit ≈ 102.98; risk = |100 - 98| = 2 → R ≈ 1.49.
        # (vs. 2.0R with no slippage)
        result = run_backtest(BacktestParams(
            config_id=self.cfg.id, start=self.start, end=self.end,
            slippage_pct=0.5))
        self.assertLess(result.trades[0].realized_r, 2.0)
        # Entry price field should reflect the slipped entry.
        self.assertAlmostEqual(result.trades[0].entry_price, 100.5, places=2)

    def test_slippage_makes_stop_worse(self):
        """Slippage past the SL means a worse loss — R goes from -1 to < -1."""
        from bot_program.backtest_asset import BacktestParams, run_backtest
        sig_time = self.start + timedelta(hours=1)
        _signal(self.inst, ts=sig_time, direction="bullish", price=100)
        # Bar that hits SL at 98
        _bar(self.inst, ts=sig_time + timedelta(hours=1),
             o=100, h=100.5, low=97, c=98)
        result = run_backtest(BacktestParams(
            config_id=self.cfg.id, start=self.start, end=self.end,
            slippage_pct=0.5))
        # entry slips to 100.5, exit slips below 98 → loss > 1R.
        self.assertLess(result.trades[0].realized_r, -1.0)


# ── Walk-forward ─────────────────────────────────────────────────────────

class WalkForwardTests(TestCase):
    def setUp(self):
        self.user = _user("wf_u")
        self.cfg = _abc(self.user, "stock", name="ST", symbols=["AAPL"],
                         cool_down_minutes=0)
        self.inst = _instrument("AAPL")
        # 100-hour window so we can place trades cleanly in train vs test.
        self.start = datetime(2026, 4, 1, 0, 0, tzinfo=dt_tz.utc)
        self.end = datetime(2026, 4, 5, 4, 0, tzinfo=dt_tz.utc)  # +100h

    def test_walk_forward_partitions_trades(self):
        from bot_program.backtest_asset import BacktestParams, run_backtest
        # 4 winning trades evenly spread across the 100h window.
        # train_pct=0.5 → split at +50h; trades at 10h, 30h, 70h, 90h
        # → 2 in train, 2 in test.
        for hours_offset in (10, 30, 70, 90):
            sig_time = self.start + timedelta(hours=hours_offset)
            _signal(self.inst, ts=sig_time, direction="bullish",
                    price=100, rule=f"r{hours_offset}")
            _bar(self.inst, ts=sig_time + timedelta(hours=1),
                 o=100, h=104.5, low=99.5, c=104)
            _bar(self.inst, ts=sig_time + timedelta(hours=2),
                 o=100, h=100, low=100, c=100)
        result = run_backtest(BacktestParams(
            config_id=self.cfg.id, start=self.start, end=self.end,
            walk_forward=True, train_pct=0.5))

        self.assertEqual(len(result.trades), 4)
        self.assertIsNotNone(result.train_stats)
        self.assertIsNotNone(result.test_stats)
        self.assertEqual(result.train_stats["n"], 2)
        self.assertEqual(result.test_stats["n"], 2)
        self.assertIsNotNone(result.walk_forward_split_at)

    def test_walk_forward_off_returns_none_partitions(self):
        from bot_program.backtest_asset import BacktestParams, run_backtest
        sig_time = self.start + timedelta(hours=10)
        _signal(self.inst, ts=sig_time, direction="bullish", price=100)
        _bar(self.inst, ts=sig_time + timedelta(hours=1),
             o=100, h=104.5, low=99.5, c=104)
        result = run_backtest(BacktestParams(
            config_id=self.cfg.id, start=self.start, end=self.end,
            walk_forward=False))
        self.assertIsNone(result.train_stats)
        self.assertIsNone(result.test_stats)

    def test_walk_forward_no_trades_skips(self):
        """No qualifying signals → walk-forward stats stay None, no error."""
        from bot_program.backtest_asset import BacktestParams, run_backtest
        result = run_backtest(BacktestParams(
            config_id=self.cfg.id, start=self.start, end=self.end,
            walk_forward=True, train_pct=0.7))
        self.assertEqual(len(result.trades), 0)
        # No trades → no partitioning attempted, both stats remain None.
        self.assertIsNone(result.train_stats)


# ── Persistence + view round-trip with realism knobs ─────────────────────

class ViewRealismRoundtripTests(TestCase):
    def test_view_passes_realism_params_to_engine(self):
        from bot_program.models import BotBacktestRun
        from django.test import Client
        u = _user("vr_u")
        cfg = _abc(u, "stock", name="ST", symbols=["AAPL"])
        inst = _instrument("AAPL")
        sig_time = datetime(2026, 4, 5, 10, 0, tzinfo=dt_tz.utc)
        _signal(inst, ts=sig_time, direction="bullish", price=100)
        _bar(inst, ts=sig_time + timedelta(hours=1),
             o=100, h=104.5, low=99.5, c=104)

        c = Client()
        c.force_login(u)
        r = c.post("/bot-backtest/run/", {
            "config_id": cfg.id,
            "start": "2026-04-01",
            "end": "2026-04-30",
            "transaction_cost_pct": "0.10",
            "slippage_pct": "0.5",
            "walk_forward": "on",
            "train_pct": "0.6",
        }, follow=True)
        self.assertEqual(r.status_code, 200)

        run = BotBacktestRun.objects.filter(user=u).first()
        self.assertIsNotNone(run)
        self.assertEqual(run.params["transaction_cost_pct"], 0.10)
        self.assertEqual(run.params["slippage_pct"], 0.5)
        self.assertTrue(run.params["walk_forward"])
        self.assertEqual(run.params["train_pct"], 0.6)
        # walk_forward block populated in stats
        self.assertIn("walk_forward", run.stats)
