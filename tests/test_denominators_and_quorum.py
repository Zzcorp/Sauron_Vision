"""Three numbers the platform reported without checking.

  the pool          `AssetBotConfig.capital` is the denominator of the whole
                    per-config risk stack — the risk budget, the daily-loss
                    floor, the drawdown curve's opening equity, the base
                    both single-position checks measure against. It is a
                    number typed into a form, and nothing ever compared it
                    to the broker's balance. Declared LARGER than the
                    account, every limit derived from it is looser than it
                    reads: a "2% daily loss" on a declared 100,000 against
                    a real 20,000 is a 10% daily loss.

  the heartbeat     The health page had eight checks and not one read
                    whether the schedule was still turning. The only thing
                    that reports a stopped component is the digest, which
                    returns nothing when all is well — so a wedged beat, a
                    dead worker and a failed send all look like a good day.
                    The failure correlates: a stopped worker both generates
                    faults and suppresses the report about them.

  the quorum        `min_signals_for_entry = 2` buys INDEPENDENT
                    confirmation. It counted rule NAMES, so two readings of
                    one dataset satisfied it between them — and the reason
                    string on the trade reported the headcount as evidence
                    count. The platform already measures which rules trade
                    the same factor and routed that only to a narrator.

Run with:  python manage.py test tests.test_denominators_and_quorum
"""
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.utils import timezone


def _cfg(user, **kw):
    from bot_program.models import AssetBotConfig
    opts = dict(user=user, asset_class="stock", name="D", mode="live",
                symbols=["AAPL"], capital=Decimal("100000"), enabled=True)
    opts.update(kw)
    return AssetBotConfig.objects.create(**opts)


def _client(balance):
    c = MagicMock()
    c.balance_usdt.return_value = balance
    return c


class ThePoolIsComparedToTheAccountTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("cap_u", password="x")

    def _mismatches(self, cfg, client):
        from bot_program.capital_truth import capital_mismatches
        with patch("bot_program.engine.broker_router.client_for_symbol",
                   return_value=client):
            return capital_mismatches(self.user)

    def test_a_pool_larger_than_the_account_is_reported(self):
        """The dangerous direction: every limit is a percentage of the
        declared pool, so all of them are looser than they read."""
        cfg = _cfg(self.user, capital=Decimal("100000"))
        rows = self._mismatches(cfg, _client(20000.0))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["direction"], "over")
        self.assertEqual(rows[0]["ratio"], 5.0)

    def test_a_pool_that_matches_is_silent(self):
        cfg = _cfg(self.user, capital=Decimal("20000"))
        self.assertEqual(self._mismatches(cfg, _client(20000.0)), [])

    def test_a_small_drift_is_not_worth_an_alarm(self):
        """A false alarm trains an operator to ignore the real one."""
        cfg = _cfg(self.user, capital=Decimal("20500"))
        self.assertEqual(self._mismatches(cfg, _client(20000.0)), [])

    def test_an_unreadable_balance_is_unmeasured_not_zero(self):
        """Booking a failed call as 0.0 would report the account as empty
        — alarming, and false."""
        from bot_program.capital_truth import broker_equity
        cfg = _cfg(self.user)
        c = MagicMock()
        c.balance_usdt.side_effect = RuntimeError("no route")
        with patch("bot_program.engine.broker_router.client_for_symbol",
                   return_value=c):
            self.assertIsNone(broker_equity(self.user, cfg))

    def test_a_paper_config_has_no_account_to_ask(self):
        from bot_program.capital_truth import broker_equity
        cfg = _cfg(self.user, mode="paper")
        self.assertIsNone(broker_equity(self.user, cfg))

    def test_a_client_without_a_balance_api_is_unmeasured(self):
        from bot_program.capital_truth import broker_equity
        cfg = _cfg(self.user)
        with patch("bot_program.engine.broker_router.client_for_symbol",
                   return_value=MagicMock(spec=["ticker"])):
            self.assertIsNone(broker_equity(self.user, cfg))

    def test_a_zero_balance_is_unmeasured_rather_than_an_empty_account(self):
        """This module cannot tell an empty account from an API answering
        badly, and guessing either way is a claim it has not earned."""
        from bot_program.capital_truth import broker_equity
        cfg = _cfg(self.user)
        with patch("bot_program.engine.broker_router.client_for_symbol",
                   return_value=_client(0.0)):
            self.assertIsNone(broker_equity(self.user, cfg))

    def test_the_health_check_fails_on_an_oversized_pool(self):
        from dashboard.views_system_health import check_capital_truth
        _cfg(self.user, capital=Decimal("100000"))
        with patch("bot_program.engine.broker_router.client_for_symbol",
                   return_value=_client(20000.0)):
            c = check_capital_truth(self.user)
        self.assertEqual(c["state"], "fail")
        self.assertIn("looser", c["hint"])


class TheBeatCanBeReportedDeadTests(TestCase):

    def _comp(self, key, **kw):
        from core.platform_control import PlatformComponent
        opts = dict(key=key, name=key, is_enabled=True)
        opts.update(kw)
        obj, _ = PlatformComponent.objects.update_or_create(
            key=key, defaults=opts)
        return obj

    def test_a_failing_component_turns_the_page_red(self):
        from dashboard.views_system_health import check_component_staleness
        self._comp("scraper_news", last_status="error",
                   last_message="boom", last_run_at=timezone.now())
        c = check_component_staleness()
        self.assertEqual(c["state"], "fail")
        self.assertIn("scraper_news", c["detail"])

    def test_a_platform_that_never_started_is_not_a_stall(self):
        from dashboard.views_system_health import check_component_staleness
        self._comp("scraper_news", last_run_at=None)
        c = check_component_staleness()
        self.assertEqual(c["state"], "warn")
        self.assertFalse(c["configured"])

    def test_a_healthy_schedule_reads_ok(self):
        from dashboard.views_system_health import check_component_staleness
        self._comp("scraper_news", last_status="success",
                   last_run_at=timezone.now())
        self.assertEqual(check_component_staleness()["state"], "ok")

    def test_no_components_is_an_absence_not_a_pass(self):
        from dashboard.views_system_health import check_component_staleness
        from core.platform_control import PlatformComponent
        PlatformComponent.objects.all().delete()
        c = check_component_staleness()
        self.assertFalse(c["configured"])


class TheQuorumCountsSourcesNotNamesTests(SimpleTestCase):

    def test_two_readings_of_one_dataset_are_one_source(self):
        from bot_program.asset_engine.rule_clusters import independent_sources
        mapping = {"funding_a": "c1", "funding_b": "c1"}
        self.assertEqual(
            independent_sources(["funding_a", "funding_b"],
                                mapping=mapping, stale=False), 1)

    def test_genuinely_different_rules_still_count_separately(self):
        from bot_program.asset_engine.rule_clusters import independent_sources
        mapping = {"funding_a": "c1", "funding_b": "c1"}
        self.assertEqual(
            independent_sources(["funding_a", "momentum_x"],
                                mapping=mapping, stale=False), 2)

    def test_an_unpaired_rule_is_its_own_source(self):
        """The audit only reports rules it found a partner for; absence
        from the map means independent, not unknown."""
        from bot_program.asset_engine.rule_clusters import independent_sources
        self.assertEqual(
            independent_sources(["solo"], mapping={}, stale=False), 1)

    def test_an_unmeasured_correlation_does_not_tighten_the_gate(self):
        """Failing the other way would make an unreadable audit silently
        stricter than the operator set."""
        from bot_program.asset_engine.rule_clusters import independent_sources
        self.assertEqual(
            independent_sources(["a", "b"], mapping={}, stale=True), 2)

    def test_an_unreadable_audit_is_stale_not_empty(self):
        from bot_program.asset_engine import rule_clusters
        rule_clusters._CACHE.update({"at": None, "map": {}, "stale": True})
        with patch("brain.correlation_audit."
                   "detect_realized_return_correlation",
                   side_effect=RuntimeError("no data")):
            mapping, stale = rule_clusters.cluster_map(force=True)
        self.assertTrue(stale)
        self.assertEqual(mapping, {})

    def test_correlated_pairs_become_one_cluster(self):
        from bot_program.asset_engine import rule_clusters
        rule_clusters._CACHE.update({"at": None, "map": {}, "stale": True})
        with patch("brain.correlation_audit."
                   "detect_realized_return_correlation",
                   return_value=[{"rule_a": "x", "rule_b": "y"},
                                 {"rule_a": "y", "rule_b": "z"}]):
            mapping, stale = rule_clusters.cluster_map(force=True)
        self.assertFalse(stale)
        self.assertEqual(len({mapping["x"], mapping["y"], mapping["z"]}), 1)
