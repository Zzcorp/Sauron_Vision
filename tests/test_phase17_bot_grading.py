"""Phase-17 reinforcement-loop tests:
  - grade_bot_trade computes outcome/realized_r/duration on close
  - bot_performance_summary aggregates per (rule, asset_class)
  - bot_trade_track_record returns confidence multiplier in [0.5, 1.5]
  - AssetBot.decide() applies multiplier when extras['use_bot_track_record']=True
  - /bot-performance/ dashboard renders

Run with:  python manage.py test tests.test_phase17_bot_grading
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase, Client
from django.utils import timezone


def _user(name="grade_u"):
    return User.objects.create_user(username=name, password="x")


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


def _closed_trade(cfg, *, symbol, side, entry, exit, sl, tp, qty=1,
                  pnl=None, rule_name="r1", reason="", asset_class=None,
                  hours_open=2):
    """Helper to create a CLOSED trade with the right shape for grading."""
    from bot_program.models import AssetBotTrade
    if pnl is None:
        if side == "BUY":
            pnl = Decimal(str((exit - entry) * qty))
        else:
            pnl = Decimal(str((entry - exit) * qty))
    opened_at = timezone.now() - timedelta(hours=hours_open)
    closed_at = timezone.now()
    t = AssetBotTrade.objects.create(
        config=cfg, asset_class=asset_class or cfg.asset_class,
        symbol=symbol, side=side, qty=Decimal(str(qty)),
        entry_price=Decimal(str(entry)),
        exit_price=Decimal(str(exit)),
        stop_loss=Decimal(str(sl)),
        take_profit=Decimal(str(tp)),
        status="CLOSED", pnl=pnl,
        rule_name=rule_name, reason=reason,
    )
    # opened_at has auto_now_add=True, so override after create.
    AssetBotTrade.objects.filter(pk=t.pk).update(
        opened_at=opened_at, closed_at=closed_at)
    t.refresh_from_db()
    return t


# ── grade_bot_trade ──────────────────────────────────────────────────────

class GradeBotTradeTests(TestCase):
    def setUp(self):
        self.user = _user()
        self.cfg = _abc(self.user, "stock", name="ST")

    def test_buy_hit_target(self):
        from bot_program.bot_grading import grade_bot_trade
        t = _closed_trade(self.cfg, symbol="AAPL", side="BUY",
                          entry=100, exit=110, sl=95, tp=110, qty=10)
        ok = grade_bot_trade(t)
        self.assertTrue(ok)
        t.refresh_from_db()
        self.assertEqual(t.outcome, "hit_target")
        # Initial risk: |100 - 95| × 10 = 50. Pnl: 100. realized_r = 100/50 = 2.0
        self.assertEqual(t.realized_r, 2.0)
        self.assertGreater(t.duration_minutes, 0)

    def test_buy_stopped_out(self):
        from bot_program.bot_grading import grade_bot_trade
        t = _closed_trade(self.cfg, symbol="AAPL", side="BUY",
                          entry=100, exit=95, sl=95, tp=110, qty=10)
        grade_bot_trade(t)
        t.refresh_from_db()
        self.assertEqual(t.outcome, "stopped_out")
        # Pnl: -50 / risk: 50 = -1.0R
        self.assertEqual(t.realized_r, -1.0)

    def test_sell_hit_target(self):
        from bot_program.bot_grading import grade_bot_trade
        t = _closed_trade(self.cfg, symbol="AAPL", side="SELL",
                          entry=100, exit=90, sl=105, tp=90, qty=10)
        grade_bot_trade(t)
        t.refresh_from_db()
        self.assertEqual(t.outcome, "hit_target")
        # Pnl on SELL: (100-90)*10=100. Risk: |100-105|*10=50. R=2.0
        self.assertEqual(t.realized_r, 2.0)

    def test_sell_stopped_out(self):
        from bot_program.bot_grading import grade_bot_trade
        t = _closed_trade(self.cfg, symbol="AAPL", side="SELL",
                          entry=100, exit=105, sl=105, tp=90, qty=10)
        grade_bot_trade(t)
        t.refresh_from_db()
        self.assertEqual(t.outcome, "stopped_out")
        self.assertEqual(t.realized_r, -1.0)

    def test_expiry_close_outcome(self):
        from bot_program.bot_grading import grade_bot_trade
        t = _closed_trade(self.cfg, symbol="AAPL", side="BUY",
                          entry=100, exit=102, sl=95, tp=110, qty=10,
                          reason="EXPIRY_CLOSE: theta cliff")
        grade_bot_trade(t)
        t.refresh_from_db()
        self.assertEqual(t.outcome, "expired")

    def test_manual_close_when_neither_sl_nor_tp_hit(self):
        from bot_program.bot_grading import grade_bot_trade
        t = _closed_trade(self.cfg, symbol="AAPL", side="BUY",
                          entry=100, exit=105, sl=95, tp=110, qty=10)
        grade_bot_trade(t)
        t.refresh_from_db()
        self.assertEqual(t.outcome, "manual_close")

    def test_open_trade_returns_false(self):
        from bot_program.bot_grading import grade_bot_trade
        from bot_program.models import AssetBotTrade
        t = AssetBotTrade.objects.create(
            config=self.cfg, asset_class="stock", symbol="X",
            side="BUY", qty=Decimal("1"),
            entry_price=Decimal("100"), status="OPEN",
        )
        self.assertFalse(grade_bot_trade(t))


# ── bot_performance_summary ──────────────────────────────────────────────

class BotPerformanceSummaryTests(TestCase):
    def setUp(self):
        self.user = _user("perf_u")
        self.cfg = _abc(self.user, "stock", name="ST")

    def _seed_pair(self, rule, n_wins=2, n_losses=2):
        from bot_program.bot_grading import grade_bot_trade
        for i in range(n_wins):
            t = _closed_trade(self.cfg, symbol=f"W{i}", side="BUY",
                              entry=100, exit=110, sl=95, tp=110, qty=10,
                              rule_name=rule)
            grade_bot_trade(t)
        for i in range(n_losses):
            t = _closed_trade(self.cfg, symbol=f"L{i}", side="BUY",
                              entry=100, exit=95, sl=95, tp=110, qty=10,
                              rule_name=rule)
            grade_bot_trade(t)

    def test_aggregates_per_rule_and_class(self):
        from bot_program.bot_grading import bot_performance_summary
        self._seed_pair("alpha", n_wins=3, n_losses=1)
        rows = bot_performance_summary(rule_name="alpha", days=30)
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r["rule_name"], "alpha")
        self.assertEqual(r["asset_class"], "stock")
        self.assertEqual(r["n"], 4)
        self.assertEqual(r["n_wins"], 3)
        self.assertEqual(r["n_losses"], 1)
        self.assertAlmostEqual(r["win_rate"], 0.75)

    def test_filters_by_asset_class(self):
        from bot_program.bot_grading import bot_performance_summary, grade_bot_trade
        self._seed_pair("alpha")
        # Add a forex trade with the same rule.
        fx = _abc(self.user, "forex", name="FX")
        t = _closed_trade(fx, symbol="EURUSD", side="BUY",
                          entry=1.10, exit=1.12, sl=1.09, tp=1.12, qty=1000,
                          rule_name="alpha")
        grade_bot_trade(t)
        rows = bot_performance_summary(asset_class="forex", days=30)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["asset_class"], "forex")

    def test_excludes_old_trades(self):
        """Trades closed > days ago aren't counted."""
        from bot_program.bot_grading import bot_performance_summary, grade_bot_trade
        from bot_program.models import AssetBotTrade
        # Create trade that closed 60 days ago.
        t = _closed_trade(self.cfg, symbol="OLD", side="BUY",
                          entry=100, exit=110, sl=95, tp=110, qty=10,
                          rule_name="ancient")
        grade_bot_trade(t)
        # Backdate.
        t.closed_at = timezone.now() - timedelta(days=60)
        t.save(update_fields=["closed_at"])
        rows = bot_performance_summary(rule_name="ancient", days=30)
        self.assertEqual(len(rows), 0)

    def test_ignores_blank_rule_name(self):
        from bot_program.bot_grading import bot_performance_summary, grade_bot_trade
        t = _closed_trade(self.cfg, symbol="X", side="BUY",
                          entry=100, exit=110, sl=95, tp=110, qty=10,
                          rule_name="")
        grade_bot_trade(t)
        rows = bot_performance_summary(days=30)
        self.assertEqual(len(rows), 0)


# ── bot_trade_track_record ───────────────────────────────────────────────

class BotTradeTrackRecordTests(TestCase):
    def setUp(self):
        self.user = _user("trk_u")
        self.cfg = _abc(self.user, "stock", name="ST")

    def _seed(self, rule, n_wins, n_losses):
        from bot_program.bot_grading import grade_bot_trade
        for i in range(n_wins):
            t = _closed_trade(self.cfg, symbol=f"W{i}", side="BUY",
                              entry=100, exit=110, sl=95, tp=110, qty=10,
                              rule_name=rule)
            grade_bot_trade(t)
        for i in range(n_losses):
            t = _closed_trade(self.cfg, symbol=f"L{i}", side="BUY",
                              entry=100, exit=95, sl=95, tp=110, qty=10,
                              rule_name=rule)
            grade_bot_trade(t)

    def test_returns_one_when_below_min_n(self):
        from bot_program.bot_grading import bot_trade_track_record
        self._seed("low_n", n_wins=2, n_losses=1)  # n=3 < min_n=10
        self.assertEqual(bot_trade_track_record("low_n", "stock"), 1.0)

    def test_winning_rule_boosts_score(self):
        from bot_program.bot_grading import bot_trade_track_record
        # 8 wins (2R each), 2 losses (-1R each) → win_rate=0.8, avg_r=1.4
        self._seed("winner", n_wins=8, n_losses=2)
        m = bot_trade_track_record("winner", "stock", min_n=5)
        self.assertGreater(m, 1.0)
        self.assertLessEqual(m, 1.5)

    def test_losing_rule_penalises(self):
        from bot_program.bot_grading import bot_trade_track_record
        self._seed("loser", n_wins=2, n_losses=8)
        m = bot_trade_track_record("loser", "stock", min_n=5)
        self.assertLess(m, 1.0)
        self.assertGreaterEqual(m, 0.5)

    def test_unknown_rule_returns_one(self):
        from bot_program.bot_grading import bot_trade_track_record
        self.assertEqual(bot_trade_track_record("nonexistent", "stock"), 1.0)


# ── AssetBot decide() integration ────────────────────────────────────────

class DecideTrackRecordTests(TestCase):
    def setUp(self):
        self.user = _user("dec_u")

    def _seed_signal(self, symbol, asset_class, rule, score=0.85):
        from instruments.models import Instrument
        from signals.models import Signal
        inst, _ = Instrument.objects.get_or_create(
            symbol=symbol, defaults={"name": symbol, "asset_class": asset_class},
        )
        return Signal.objects.create(
            instrument=inst, signal_type="composite", direction="bullish",
            urgency="medium", title="t", description="t", rule_name=rule,
            score=score, sub_scores={},
            price_at_signal=Decimal("100"), suggested_entry=Decimal("100"),
        )

    def test_decide_unchanged_when_extras_off(self):
        from bot_program.asset_engine import StockBot
        cfg = _abc(self.user, "stock", name="ST", symbols=["AAA"])
        self._seed_signal("AAA", "stock", "rule_x", score=0.80)
        d = StockBot(cfg).decide("AAA")
        self.assertEqual(d.direction, "BUY")
        self.assertAlmostEqual(d.score, 0.80, places=3)

    def test_decide_boosts_when_extras_on_and_rule_winning(self):
        from bot_program.asset_engine import StockBot
        from bot_program.bot_grading import grade_bot_trade
        cfg = _abc(self.user, "stock", name="ST", symbols=["AAA"],
                   extras={"use_bot_track_record": True})
        # Seed a strong winner track record for rule_w.
        for i in range(8):
            t = _closed_trade(cfg, symbol=f"W{i}", side="BUY",
                              entry=100, exit=110, sl=95, tp=110, qty=10,
                              rule_name="rule_w")
            grade_bot_trade(t)
        for i in range(2):
            t = _closed_trade(cfg, symbol=f"L{i}", side="BUY",
                              entry=100, exit=95, sl=95, tp=110, qty=10,
                              rule_name="rule_w")
            grade_bot_trade(t)
        # Now a fresh signal under that rule.
        self._seed_signal("AAA", "stock", "rule_w", score=0.60)
        d = StockBot(cfg).decide("AAA")
        # Score should have been multiplied up by ~1.4 (capped at 1.0).
        self.assertEqual(d.direction, "BUY")
        self.assertGreater(d.score, 0.60)

    def test_decide_penalises_when_extras_on_and_rule_losing(self):
        from bot_program.asset_engine import StockBot
        from bot_program.bot_grading import grade_bot_trade
        cfg = _abc(self.user, "stock", name="ST", symbols=["AAA"],
                   extras={"use_bot_track_record": True})
        for i in range(8):
            t = _closed_trade(cfg, symbol=f"L{i}", side="BUY",
                              entry=100, exit=95, sl=95, tp=110, qty=10,
                              rule_name="rule_l")
            grade_bot_trade(t)
        for i in range(2):
            t = _closed_trade(cfg, symbol=f"W{i}", side="BUY",
                              entry=100, exit=110, sl=95, tp=110, qty=10,
                              rule_name="rule_l")
            grade_bot_trade(t)
        self._seed_signal("AAA", "stock", "rule_l", score=0.80)
        d = StockBot(cfg).decide("AAA")
        # Score should be penalised below the raw 0.80.
        self.assertEqual(d.direction, "BUY")
        self.assertLess(d.score, 0.80)


# ── Dashboard rendering ──────────────────────────────────────────────────

class BotPerformanceDashboardTests(TestCase):
    def test_renders_empty(self):
        u = _user("perf_dash_u")
        c = Client()
        c.force_login(u)
        r = c.get("/bot-performance/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "REINFORCEMENT LOOP")

    def test_renders_with_data(self):
        from bot_program.bot_grading import grade_bot_trade
        u = _user("perf_dash_u2")
        cfg = _abc(u, "stock", name="ST")
        for i in range(3):
            t = _closed_trade(cfg, symbol=f"X{i}", side="BUY",
                              entry=100, exit=110, sl=95, tp=110, qty=10,
                              rule_name="rule_seen")
            grade_bot_trade(t)
        c = Client()
        c.force_login(u)
        r = c.get("/bot-performance/?days=30")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "rule_seen")

    def test_days_query_param_clamped(self):
        u = _user("perf_dash_u3")
        c = Client()
        c.force_login(u)
        # Out-of-range days: clamped to [7, 365].
        r = c.get("/bot-performance/?days=99999")
        self.assertEqual(r.status_code, 200)
        # No exception thrown is the assertion; HTML contains DAYS label.
        self.assertContains(r, "DAYS")
