"""A retired IBKR row raises nothing (2026-09-30).

The operator: "remove any IBKR problems please, it's no more a concern
for us". The book is eToro; the IBKR row ("Main") routes no class and its
Gateway is down. Yet the sync attempted it every 15 minutes, graded the
shared sync row a warning, and from the third miss told the Eye "broker
unreachable"; the alarm chat, the operator's father's, would have heard
"IBKR account has not answered" every three hours and "IBKR is not
delivering quotes" every day; /health/ read the IBKR feed as NEVER; the
sweep logged it unreadable; /treasury/ noted its aging reading.

One predicate decides, capital_truth.ibkr_in_use: a row is in use while
it is the book, routes a class, has an enabled live options/CFD config
behind it, or holds an open real-money row stamped ibkr. Pinned here: the
predicate, and each reader that now leaves a retired row alone — the
sync (and its miss count), the alarm, the feed, the sweep's venue count,
/treasury/, the preflight — while a row in use is treated exactly as
before.

Run with:  python manage.py test tests.test_ibkr_retired
"""
from decimal import Decimal
from io import StringIO
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from tests.test_component_digest import _component

FLAGS = ("is_primary_for_stocks", "is_primary_for_forex",
         "is_primary_for_options", "is_primary_for_commodity",
         "is_primary_for_cfd")


def _ibkr(user, **flags):
    """The live box's row: keyed, every class unticked unless named."""
    from bot_program.models import IBKRAccount
    fields = {f: False for f in FLAGS}
    fields.update(flags)
    acct = IBKRAccount.objects.create(user=user, label="Main",
                                      host="ibgateway", port=4003,
                                      client_id=1, **fields)
    acct.set_credentials("U1234567")
    acct.save(update_fields=["account_id_enc"])
    return acct


def _etoro_book(user):
    from bot_program.models import EtoroAccount
    acct = EtoroAccount.objects.create(user=user, is_primary_for_forex=True,
                                       is_primary_for_crypto=True)
    acct.set_credentials("the-api-key", "the-user-key")
    acct.save()
    return acct


class _Base(TestCase):

    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user("ibkr_ret",
                                                         password="x")
        self.etoro = _etoro_book(self.user)
        self.ibkr = _ibkr(self.user)


class ThePredicateTests(_Base):

    def test_the_live_box_row_is_retired(self):
        from bot_program.capital_truth import ibkr_in_use
        self.assertFalse(ibkr_in_use(self.ibkr))

    def test_any_class_brings_it_back(self):
        from bot_program.capital_truth import ibkr_in_use
        for flag in FLAGS:
            setattr(self.ibkr, flag, True)
            self.assertTrue(ibkr_in_use(self.ibkr), flag)
            setattr(self.ibkr, flag, False)

    def test_the_book_is_in_use(self):
        from bot_program.capital_truth import ibkr_in_use
        self.etoro.delete()
        self.ibkr.refresh_from_db()
        self.assertTrue(ibkr_in_use(self.ibkr))

    def test_an_open_real_money_row_there_is_in_use(self):
        from bot_program.capital_truth import ibkr_in_use
        from bot_program.models import AssetBotConfig, AssetBotTrade
        cfg = AssetBotConfig.objects.create(
            user=self.user, asset_class="stock", name="old", mode="live",
            enabled=False, symbols=[], capital=Decimal("100"))
        AssetBotTrade.objects.create(
            config=cfg, asset_class="stock", symbol="AAPL", side="BUY",
            qty=Decimal("1"), entry_price=Decimal("100"), status="OPEN",
            paper=False, metadata={"broker": "ibkr"})
        self.assertTrue(ibkr_in_use(self.ibkr))

    def test_an_enabled_live_options_config_is_in_use(self):
        """The router's forced IBKR route for options and CFD."""
        from bot_program.capital_truth import ibkr_in_use
        from bot_program.models import AssetBotConfig
        AssetBotConfig.objects.create(
            user=self.user, asset_class="options", name="opt", mode="live",
            enabled=True, symbols=[], capital=Decimal("100"))
        self.assertTrue(ibkr_in_use(self.ibkr))

    def test_an_unreadable_row_is_in_use(self):
        from bot_program import capital_truth
        with patch.object(capital_truth, "broker_backed",
                          side_effect=RuntimeError("db gone")), \
                self.assertLogs("bot_program.capital_truth", "WARNING"):
            self.assertTrue(capital_truth.ibkr_in_use(self.ibkr))


class TheSyncTests(_Base):

    def setUp(self):
        super().setUp()
        _component("platform_master", category="system")
        _component("broker_account_sync", category="pipeline",
                   last_run_at=None, last_status="")

    def _pass(self):
        from bot_program.tasks import sync_broker_account
        with patch("bot_program.engine.ibkr_client.is_ibkr_available",
                   return_value=True), \
                patch("bot_program.engine.ibkr_sessions.acquire_trader",
                      return_value=None) as acquire:
            out = sync_broker_account.__wrapped__()
        return out, acquire

    def test_a_retired_row_is_not_read_and_the_pass_is_idle(self):
        out, acquire = self._pass()
        acquire.assert_not_called()
        self.assertEqual(out["attempted"], 0)
        self.assertEqual(out["idle"], "no IBKR account to read")

    def test_its_standing_miss_count_is_cleared(self):
        key = f"broker_sync:miss:ibkr:{self.ibkr.pk}"
        cache.set(key, 7, 3600)
        cache.set(f"broker_sync:alerted:ibkr:{self.ibkr.pk}", 1, 3600)
        self._pass()
        self.assertIsNone(cache.get(key))

    def test_a_row_in_use_is_still_attempted(self):
        self.ibkr.is_primary_for_options = True
        self.ibkr.save(update_fields=["is_primary_for_options"])
        with patch("bot_program.tasks._note_broker_miss") as miss:
            out, acquire = self._pass()
        acquire.assert_called_once()
        self.assertEqual(out["attempted"], 1)
        miss.assert_called_once()

    def test_without_the_library_a_retired_row_is_still_idle(self):
        from bot_program.tasks import sync_broker_account
        with patch("bot_program.engine.ibkr_client.is_ibkr_available",
                   return_value=False):
            out = sync_broker_account.__wrapped__()
        self.assertEqual(out.get("idle"), "no keyed IBKR account")


class TheAlarmTests(_Base):

    def setUp(self):
        super().setUp()
        _component("broker_account_sync", category="pipeline")

    def test_a_retired_row_never_rings_whatever_the_cache_holds(self):
        from bot_program.alarm import read_brokers
        cache.set(f"broker_sync:miss:ibkr:{self.ibkr.pk}", 40, 3600)
        self.assertEqual(read_brokers(timezone.now()), [])

    def test_a_row_in_use_still_rings(self):
        from bot_program.alarm import read_brokers
        self.ibkr.is_primary_for_stocks = True
        self.ibkr.save(update_fields=["is_primary_for_stocks"])
        cache.set(f"broker_sync:miss:ibkr:{self.ibkr.pk}", 40, 3600)
        alarms = read_brokers(timezone.now())
        self.assertEqual(len(alarms), 1)
        self.assertIn("has not answered 40 syncs", alarms[0].words)


class TheFeedTests(_Base):

    def _ibkr_feed(self):
        from market_data.feeds import FEEDS
        return next(f for f in FEEDS if f["key"] == "ibkr")

    def test_a_row_with_no_class_does_not_switch_the_feed_on(self):
        from market_data.feeds import _missing_row, is_configured
        feed = self._ibkr_feed()
        self.assertEqual(_missing_row(feed), "IBKRAccount")
        self.assertFalse(is_configured(feed))

    def test_a_row_that_routes_a_class_does(self):
        from market_data.feeds import _missing_row
        self.ibkr.is_primary_for_forex = True
        self.ibkr.save(update_fields=["is_primary_for_forex"])
        self.assertEqual(_missing_row(self._ibkr_feed()), "")


class TheSweepTests(_Base):

    def test_a_retired_row_is_not_a_second_venue(self):
        from bot_program.reconcile_asset import keyed_venue_count
        self.assertEqual(keyed_venue_count(self.user), 1)
        self.ibkr.is_primary_for_stocks = True
        self.ibkr.save(update_fields=["is_primary_for_stocks"])
        self.assertEqual(keyed_venue_count(self.user), 2)

    def test_the_sweep_leaves_a_retired_row_alone(self):
        import inspect

        from bot_program import reconcile_asset
        src = inspect.getsource(reconcile_asset)
        self.assertIn('if broker_kind(r) != "ibkr" or ibkr_in_use(r)]', src)


class TheTreasuryTests(_Base):

    def test_a_retired_row_is_marked_and_its_aging_reading_is_not_news(self):
        from bot_program import broker_vision
        from datetime import timedelta
        self.ibkr.last_equity = Decimal("100")
        self.ibkr.last_equity_currency = "USD"
        self.ibkr.last_equity_at = timezone.now() - timedelta(days=5)
        self.ibkr.save()
        rows = broker_vision.brokers(self.user)
        ibkr = next(r for r in rows if r["kind"] == "ibkr")
        self.assertTrue(ibkr["retired"])
        etoro = next(r for r in rows if r["kind"] == "etoro")
        self.assertFalse(etoro["retired"])


class ThePreflightTests(_Base):

    def test_a_retired_row_is_one_line_and_no_finding(self):
        from django.core.management import call_command
        self.ibkr.username_enc = ""
        self.ibkr.save(update_fields=["username_enc"])
        out = StringIO()
        call_command("preflight_live", f"--user={self.user.username}",
                     stdout=out)
        text = out.getvalue()
        self.assertIn("ibkr   retired — not the book, routes nothing", text)
        self.assertNotIn("no Gateway login stored", text)
        self.assertNotIn("socket       ibgateway", text)
