"""Six numbers the dashboard printed that nobody had measured.

Every case here is a figure an operator acts on, computed from the wrong
population or the wrong calendar:

  * the gate accept/reject rate, divided a complete reject count by a
    ~10%-sampled allow count and told the operator their risk gate was
    blocking three quarters of their entries;
  * the News & Sentiment panel, which imported a model that has never
    existed and so reported a dead news pipeline on every request;
  * the backtest averages, which read a run's NULL metric as a measured
    zero and dragged AVG WIN RATE down by the runs that took no trades;
  * the 12-month realized-P&L chart, which stepped back in 30-day blocks
    and therefore drew one month twice and dropped a neighbouring month;
  * the System Map legend, which had no counter slot for a node whose
    probe failed and 500'd the whole operations page when one did;
  * the hypothesis tile, which counted every overdue hypothesis a second
    time in the "due 24h" figure printed beside it.

Run with:  python manage.py test tests.test_dashboard_arithmetic
"""
from datetime import date, datetime, timedelta, timezone as dt_timezone
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone


def _user(name="dash_a", staff=False):
    return User.objects.create_user(username=name, password="x",
                                    is_staff=staff)


def _master_on():
    from core.platform_control import PlatformComponent
    return PlatformComponent.objects.create(
        key="platform_master", name="Master switch", category="system",
        is_enabled=True)


def _gate_events(user, allows, rejects):
    from bot_program.orchestrator_models import OrchestratorEvent
    for i in range(allows):
        OrchestratorEvent.objects.create(
            user=user, asset_class="stock", symbol="AAPL", side="BUY",
            decision="allow", reason=f"ok {i}")
    for i in range(rejects):
        OrchestratorEvent.objects.create(
            user=user, asset_class="stock", symbol="AAPL", side="BUY",
            decision="reject", reason=f"theme cap {i}")


# ── The gate rate that never was one ─────────────────────────────────────

class GateRateIsNotComputedFromASampleTests(TestCase):
    """The orchestrator keeps every reject and one allow in ten. Any ratio
    of the two rows is a complete numerator over a sampled denominator."""

    def setUp(self):
        self.user = _user("dash_gate")
        self.client.force_login(self.user)
        _master_on()

    def test_a_gate_refusing_seven_in_ten_is_not_reported_as_refusing_all(self):
        # 100 consultations at a true 70% reject rate: 30 allows, of which
        # ~3 survive sampling, against all 70 rejects. That reads as 96%
        # rejected, and the node used to flip to STALE / "almost everything
        # is blocked" — which sends the operator off to loosen the exposure
        # caps that were doing their job.
        _gate_events(self.user, allows=3, rejects=70)
        from dashboard.views_topology import build_topology
        node = next(n for n in build_topology(self.user)["nodes"]
                    if n["key"] == "gate_orchestrator")
        self.assertEqual(node["state"], "live")
        self.assertNotIn("almost everything", node["why"].lower())
        self.assertNotIn("%", node["why"])

    def test_the_gate_node_leads_with_the_count_the_table_can_answer(self):
        _gate_events(self.user, allows=1, rejects=19)
        from dashboard.views_topology import build_topology
        node = next(n for n in build_topology(self.user)["nodes"]
                    if n["key"] == "gate_orchestrator")
        self.assertEqual(node["metric"], 19)
        self.assertIn("reject", node["metric_label"])
        self.assertIn("sample", node["why"])

    def test_the_system_map_gate_node_does_not_print_a_reject_percentage(self):
        _gate_events(self.user, allows=1, rejects=19)
        from dashboard.views_system_map import collect_system_map
        nodes = [n for stage in collect_system_map(self.user)["stages"]
                 for n in stage["nodes"]]
        gate = next(n for n in nodes if n["key"] == "gate")
        self.assertEqual(gate["state"], "live")
        self.assertNotIn("%", gate["why"])
        self.assertNotIn("almost everything", gate["why"].lower())
        self.assertEqual(gate["metric"], 19)

    def test_the_operations_strip_shows_refusals_not_an_accept_rate(self):
        _gate_events(self.user, allows=4, rejects=10)
        r = self.client.get("/command/tab/live/")
        self.assertEqual(r.context["gate_n_reject"], 10)
        self.assertNotIn("gate_accept_rate", r.context)
        body = r.content.decode()
        self.assertIn("allow logged (sampled)", body)
        self.assertNotIn("28.6%", body)


# ── News & sentiment ─────────────────────────────────────────────────────

class NewsMetricsReadTheRealTableTests(TestCase):
    def setUp(self):
        self.user = _user("dash_news")
        self.client.force_login(self.user)

    def _article(self, i, sentiment=None, days_ago=1):
        from scraping.models import NewsArticle
        return NewsArticle.objects.create(
            title=f"Headline {i}", source="unit-test",
            url=f"https://example.invalid/news/{i}",
            published_at=timezone.now() - timedelta(days=days_ago),
            ai_sentiment_score=sentiment)

    def test_a_populated_news_table_is_not_reported_as_a_dead_pipeline(self):
        for i in range(3):
            self._article(i)
        r = self.client.get("/htmx/metrics/news/")
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("error", r.context)
        self.assertEqual(r.context["totals"]["count_14d"], 3)

    def test_sentiment_comes_through_instead_of_an_import_error(self):
        self._article(10, sentiment=0.8)
        self._article(11, sentiment=0.6)
        r = self.client.get("/htmx/metrics/news/")
        self.assertIsNotNone(r.context["current_sentiment"])
        self.assertEqual(r.context["totals"]["sentiment_label"], "BULLISH")

    def test_articles_outside_the_window_are_not_counted(self):
        self._article(20, days_ago=1)
        self._article(21, days_ago=30)
        r = self.client.get("/htmx/metrics/news/")
        self.assertEqual(r.context["totals"]["count_14d"], 1)


# ── Backtest averages ────────────────────────────────────────────────────

class BacktestAveragesSkipUnmeasuredRunsTests(TestCase):
    def setUp(self):
        self.user = _user("dash_bt")
        self.client.force_login(self.user)

    def _run(self, name, **kw):
        from backtester.models import BacktestRun
        defaults = dict(
            user=self.user, name=name, strategy_type="rsi_oversold",
            parameters={}, symbols=["AAPL"],
            start_date=date(2025, 1, 1), end_date=date(2025, 6, 1),
            status="completed")
        defaults.update(kw)
        return BacktestRun.objects.create(**defaults)

    def test_a_run_that_took_no_trades_does_not_drag_the_average_down(self):
        # Three runs won 60% of their trades; the fourth never triggered, so
        # the engine left win_rate NULL. The strip used to print 45.0%.
        for i in range(3):
            self._run(f"traded {i}", win_rate=60.0, total_return_pct=10.0,
                      sharpe_ratio=1.0, max_drawdown_pct=-5.0)
        self._run("no trades")
        r = self.client.get("/backtest/")
        self.assertEqual(r.context["avg_win_rate"], 60.0)
        self.assertEqual(r.context["avg_sharpe"], 1.0)
        self.assertEqual(r.context["avg_return"], 10.0)
        self.assertEqual(r.context["avg_dd"], -5.0)

    def test_when_no_completed_run_measured_a_metric_it_stays_unknown(self):
        self._run("silent one")
        self._run("silent two")
        r = self.client.get("/backtest/")
        self.assertIsNone(r.context["avg_win_rate"])
        self.assertIsNone(r.context["avg_sharpe"])
        self.assertIsNone(r.context["avg_return"])

    def test_best_and_worst_do_not_invent_a_flat_run(self):
        # Every measured run lost; a NULL-return run used to be read as 0%
        # and crowned the best result on the page.
        self._run("loser", total_return_pct=-8.0, win_rate=20.0)
        self._run("never ran")
        r = self.client.get("/backtest/")
        self.assertEqual(r.context["best_return"], -8.0)
        self.assertEqual(r.context["worst_return"], -8.0)


# ── The 12-month P&L bars ────────────────────────────────────────────────

class MonthlyPnlBarsWalkCalendarMonthsTests(TestCase):
    def setUp(self):
        self.user = _user("dash_months")

    def _labels(self, at):
        # The login rides inside the patch too: a session stamped at the real
        # clock and read at a patched one is simply an expired session, and
        # the page would answer with a redirect instead of a chart.
        with patch("django.utils.timezone.now", return_value=at):
            self.client.force_login(self.user)
            r = self.client.get("/positions/?tab=history")
        self.assertEqual(r.status_code, 200, at)
        return [row["month"] for row in r.context["monthly_rows"]]

    def test_no_month_is_drawn_twice_and_none_is_dropped(self):
        # 25 Jan 2026: the 330-day and 300-day offsets both landed in March
        # 2025, so March got two identical bars and February 2025 — whose
        # closes ARE summed into monthly_pnl — never appeared at all.
        labels = self._labels(datetime(2026, 1, 25, 12, 0,
                                       tzinfo=dt_timezone.utc))
        self.assertEqual(len(labels), 12)
        self.assertEqual(len(set(labels)), 12)
        self.assertEqual(labels[-1], "Jan")
        self.assertEqual(labels[0], "Feb")

    def test_the_window_always_ends_on_the_current_month(self):
        for at in (datetime(2026, 3, 31, 9, 0, tzinfo=dt_timezone.utc),
                   datetime(2026, 8, 1, 0, 5, tzinfo=dt_timezone.utc),
                   datetime(2026, 12, 31, 23, 0, tzinfo=dt_timezone.utc)):
            labels = self._labels(at)
            self.assertEqual(len(set(labels)), 12, at)
            self.assertEqual(labels[-1], at.strftime("%b"), at)


# ── The map must not be the second thing that breaks ─────────────────────

class SystemMapSurvivesAFailedProbeTests(TestCase):
    def setUp(self):
        self.user = _user("dash_map", staff=True)
        self.client.force_login(self.user)
        _master_on()

    def _bars_probe_raises(self):
        """A half-applied migration or a DB blip, exactly where the map reads
        the bar table."""
        from market_data.models import PriceData
        return patch.object(PriceData.objects, "count",
                            side_effect=RuntimeError("relation does not exist"))

    def test_a_synthetic_node_whose_probe_raises_does_not_500_the_page(self):
        with self._bars_probe_raises():
            r = self.client.get("/admin-dashboard/system-map/")
            self.assertEqual(r.status_code, 200)
            state = self.client.get("/admin-dashboard/system-map/state/")
            self.assertEqual(state.status_code, 200)
            self.assertEqual(state.json()["counts"]["unknown"], 1)

    def test_the_unmeasurable_node_is_counted_and_named(self):
        from dashboard.views_topology import build_topology
        with self._bars_probe_raises():
            topo = build_topology(self.user)
        self.assertEqual(topo["counts"]["unknown"], 1)
        self.assertIn("unknown", [row["key"] for row in topo["legend"]])
        node = next(n for n in topo["nodes"] if n["key"] == "feed_bot_bars")
        self.assertEqual(node["state"], "unknown")
        self.assertEqual(node["meta"]["label"], "UNKNOWN")

    def test_a_healthy_map_does_not_carry_a_permanent_unknown_chip(self):
        from dashboard.views_topology import build_topology
        topo = build_topology(self.user)
        self.assertEqual(topo["counts"]["unknown"], 0)
        self.assertNotIn("unknown", [row["key"] for row in topo["legend"]])


# ── Hypotheses due vs overdue ────────────────────────────────────────────

class HypothesisDueCountExcludesTheOverdueTests(TestCase):
    def setUp(self):
        self.user = _user("dash_hyp")
        self.client.force_login(self.user)

    def _hyp(self, deadline):
        from brain.knowledge_models import Hypothesis
        return Hypothesis.objects.create(
            claim_text="EURUSD closes above 1.10 this week",
            source_agent="unit-test", resolution_deadline=deadline)

    def test_overdue_and_due_24h_can_be_added_without_double_counting(self):
        now = timezone.now()
        for _ in range(3):
            self._hyp(now - timedelta(hours=6))
        for _ in range(2):
            self._hyp(now + timedelta(hours=12))
        # Well outside the window — neither figure may claim it.
        self._hyp(now + timedelta(days=9))
        r = self.client.get("/hypotheses/")
        self.assertEqual(r.context["overdue"], 3)
        self.assertEqual(r.context["due_soon"], 2)

    def test_nothing_falling_due_reads_as_zero_not_as_the_overdue_backlog(self):
        now = timezone.now()
        for _ in range(3):
            self._hyp(now - timedelta(days=2))
        r = self.client.get("/hypotheses/")
        self.assertEqual(r.context["overdue"], 3)
        self.assertEqual(r.context["due_soon"], 0)

    def test_a_hypothesis_with_no_deadline_is_in_neither_figure(self):
        self._hyp(None)
        r = self.client.get("/hypotheses/")
        self.assertEqual(r.context["overdue"], 0)
        self.assertEqual(r.context["due_soon"], 0)
