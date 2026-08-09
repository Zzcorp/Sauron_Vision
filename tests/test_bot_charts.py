"""Per-bot equity curve and R distribution.

Run with:  python manage.py test tests.test_bot_charts
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone


def _user(name="bc_u"):
    return User.objects.create_user(username=name, password="x")


def _cfg(user, name="BC", capital="10000"):
    from bot_program.models import AssetBotConfig
    return AssetBotConfig.objects.create(
        user=user, asset_class="stock", name=name, mode="paper",
        symbols=["AAPL"], capital=Decimal(capital), enabled=True)


def _closed(cfg, pnl, r, days_ago=1):
    from bot_program.models import AssetBotTrade
    return AssetBotTrade.objects.create(
        config=cfg, asset_class="stock", symbol="AAPL", side="BUY",
        qty=Decimal("1"), entry_price=Decimal("100"),
        exit_price=Decimal("101"), pnl=Decimal(str(pnl)),
        realized_r=r, status="CLOSED", paper=True,
        closed_at=timezone.now() - timedelta(days=days_ago))


class ChartMathTests(TestCase):
    def setUp(self):
        self.user = _user()
        self.cfg = _cfg(self.user)

    def test_equity_curve_compounds_pnl_in_time_order(self):
        from dashboard.views_bot_charts import _equity_series
        trades = [_closed(self.cfg, 100, 1.0, days_ago=3),
                  _closed(self.cfg, -50, -0.5, days_ago=2),
                  _closed(self.cfg, 200, 2.0, days_ago=1)]
        points = _equity_series(trades, 1000.0)
        self.assertEqual([p["equity"] for p in points],
                         [1000.0, 1100.0, 1050.0, 1250.0])

    def test_max_drawdown_is_measured_from_the_running_peak(self):
        from dashboard.views_bot_charts import _equity_series, _stats
        trades = [_closed(self.cfg, 100, 1.0, days_ago=3),
                  _closed(self.cfg, -200, -2.0, days_ago=2)]
        points = _equity_series(trades, 1000.0)
        stats = _stats(trades, points)
        # peak 1100 -> trough 900 = 18.18%
        self.assertAlmostEqual(stats["max_drawdown_pct"], 18.18, places=1)

    def test_profit_factor_and_expectancy(self):
        from dashboard.views_bot_charts import _equity_series, _stats
        trades = [_closed(self.cfg, 100, 2.0, days_ago=3),
                  _closed(self.cfg, -50, -1.0, days_ago=2)]
        stats = _stats(trades, _equity_series(trades, 1000.0))
        self.assertEqual(stats["profit_factor"], 2.0)
        self.assertEqual(stats["expectancy"], 0.5)
        self.assertEqual(stats["win_rate"], 0.5)

    def test_outlier_share_flags_a_one_trade_edge(self):
        """If the best trade carries most of the total R, the 'edge' is one
        lucky outlier rather than a repeatable process."""
        from dashboard.views_bot_charts import _equity_series, _stats
        trades = [_closed(self.cfg, 1000, 10.0, days_ago=3),
                  _closed(self.cfg, 10, 0.1, days_ago=2),
                  _closed(self.cfg, 10, 0.1, days_ago=1)]
        stats = _stats(trades, _equity_series(trades, 1000.0))
        self.assertGreater(stats["top_trade_share"], 0.9)

    def test_histogram_separates_wins_from_losses(self):
        from dashboard.views_bot_charts import _r_histogram
        trades = [_closed(self.cfg, 10, 1.5, days_ago=2),
                  _closed(self.cfg, -10, -1.5, days_ago=1)]
        buckets = _r_histogram(trades)
        wins = sum(b["n"] for b in buckets if b["win"])
        losses = sum(b["n"] for b in buckets if not b["win"])
        self.assertEqual((wins, losses), (1, 1))

    def test_no_trades_degrades_gracefully(self):
        from dashboard.views_bot_charts import _equity_series, _r_histogram, _stats
        points = _equity_series([], 1000.0)
        self.assertEqual(_r_histogram([]), [])
        self.assertIsNone(_stats([], points)["expectancy"])


class ChartPageTests(TestCase):
    def setUp(self):
        self.user = _user("bc_page")
        self.cfg = _cfg(self.user)
        self.client.force_login(self.user)

    def test_page_renders_with_data(self):
        _closed(self.cfg, 100, 1.0)
        r = self.client.get("/bot-charts/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "BOT PERFORMANCE")

    def test_page_renders_with_no_trades(self):
        r = self.client.get("/bot-charts/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Not enough closed trades")

    def test_filtering_by_bot(self):
        """Assert on the computed stats, not on page text: a raw number can
        collide with unrelated markup (a z-index, an SVG coordinate)."""
        other = _cfg(self.user, name="OTHER")
        _closed(self.cfg, 100, 1.0)
        _closed(other, 999, 9.0)
        r = self.client.get(f"/bot-charts/?config={self.cfg.id}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context["stats"]["n"], 1)
        self.assertEqual(r.context["stats"]["total_pnl"], 100.0)

    def test_other_users_trades_are_excluded(self):
        stranger = _user("bc_stranger")
        _closed(_cfg(stranger, name="THEIRS"), 777, 7.0)
        _closed(self.cfg, 10, 0.5)
        r = self.client.get("/bot-charts/")
        self.assertEqual(r.context["stats"]["n"], 1)
        self.assertEqual(r.context["stats"]["total_pnl"], 10.0)
