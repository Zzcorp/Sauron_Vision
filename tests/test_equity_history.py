"""The account's equity history — the drawdown governor's memory.

`IBKRAccount.last_equity` is one cell the sync overwrites; the share
allocator's drawdown governor needs the road, not the position. So the
sync writes one BrokerEquityReading per STORED reading — in the same
block, from the same broker call — and nothing else writes that table.
These tests pin what makes the history believable:

  * A stored reading is a row; an unreachable gateway is a GAP, never a
    zero row (a zero would read as a 100% drawdown for 90 days).
  * The high-water mark includes the current reading, so a fresh account
    has hwm == reading, dd 0, n == 0 — never "no hwm".
  * Only rows in the current reading's currency count: a GBP history
    behind a EUR reading is an exchange rate, not a drawdown.
  * Rows older than 400 days are pruned, and only for that account.
  * The entry-path cache in capital_truth.broker_equity merges into the
    row instead of writing the runner's whole copy back — a share the
    allocator wrote between the config load and the cache stamp survives.

Run with:  python manage.py test tests.test_equity_history
"""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone


def _user(name="eq_u"):
    return User.objects.create_user(name, password="x")


def _acct(user, account_id="U1234567", port=4001, **fields):
    from bot_program.models import IBKRAccount
    acct = IBKRAccount.objects.create(user=user, label="ISA_CAPITAL",
                                      host="ibgateway", port=port,
                                      client_id=1, **fields)
    if account_id:
        acct.set_credentials(account_id)
        acct.save(update_fields=["account_id_enc"])
    return acct


def _reading(acct, value, *, days_ago=0.0, currency="GBP", env="live"):
    from bot_program.models import BrokerEquityReading
    return BrokerEquityReading.objects.create(
        account=acct, value=Decimal(str(value)), currency=currency, env=env,
        at=timezone.now() - timedelta(days=days_ago))


def _stamp(acct, value, currency="GBP", *, age_seconds=0):
    acct.last_equity = Decimal(str(value))
    acct.last_equity_currency = currency
    acct.last_equity_at = timezone.now() - timedelta(seconds=age_seconds)
    acct.save()


def _run_sync(reading=(52340.12, "GBP"), rows=None):
    """The sync task with the socket layer stubbed, as test_broker_truth
    runs it: __wrapped__ twice to step past @shared_task and @guarded_task."""
    from bot_program.tasks import sync_broker_account
    trader = MagicMock()
    trader.net_liquidation.return_value = reading
    trader.broker_portfolio.return_value = rows
    with patch("bot_program.engine.ibkr_client.is_ibkr_available",
               return_value=True), \
         patch("bot_program.engine.ibkr_client.IBKRTrader",
               return_value=trader):
        return sync_broker_account.__wrapped__.__wrapped__()


class TheSyncWritesTheHistoryTests(TestCase):

    def test_a_stored_reading_is_one_history_row(self):
        from bot_program.models import BrokerEquityReading
        u = _user("eq_sync")
        acct = _acct(u)
        out = _run_sync(rows=[{"symbol": "AZN"}])
        self.assertEqual(out["stored"], 1)
        rows = list(BrokerEquityReading.objects.filter(account=acct))
        self.assertEqual(len(rows), 1)
        self.assertEqual(float(rows[0].value), 52340.12)
        self.assertEqual(rows[0].currency, "GBP")
        self.assertEqual(rows[0].env, "live")
        acct.refresh_from_db()
        # Same instant as the cell: the road and the position quote one sync.
        self.assertEqual(rows[0].at, acct.last_equity_at)

    def test_two_syncs_are_two_rows(self):
        from bot_program.models import BrokerEquityReading
        u = _user("eq_two")
        acct = _acct(u)
        _run_sync(reading=(100.0, "GBP"))
        _run_sync(reading=(110.0, "GBP"))
        values = sorted(float(r.value) for r in
                        BrokerEquityReading.objects.filter(account=acct))
        self.assertEqual(values, [100.0, 110.0])

    def test_an_unreachable_gateway_writes_no_row_ever(self):
        """A gap, not a zero. A zero row would be a 100% drawdown."""
        from bot_program.models import BrokerEquityReading
        u = _user("eq_gap")
        acct = _acct(u)
        _stamp(acct, "50000")
        out = _run_sync(reading=None, rows=None)
        self.assertEqual(out["unreachable"], 1)
        self.assertEqual(BrokerEquityReading.objects.filter(account=acct)
                         .count(), 0)

    def test_holdings_only_syncs_write_no_equity_row(self):
        from bot_program.models import BrokerEquityReading
        u = _user("eq_rows_only")
        acct = _acct(u)
        _run_sync(reading=None, rows=[{"symbol": "AZN"}])
        self.assertEqual(BrokerEquityReading.objects.filter(account=acct)
                         .count(), 0)

    def test_a_failed_history_insert_does_not_fail_the_sync(self):
        u = _user("eq_fail")
        acct = _acct(u)
        with patch("bot_program.equity_models.BrokerEquityReading.objects"
                   ".create", side_effect=RuntimeError("disk full")):
            out = _run_sync()
        self.assertEqual(out["stored"], 1)
        acct.refresh_from_db()
        self.assertEqual(float(acct.last_equity), 52340.12)

    def test_rows_older_than_400_days_are_pruned_for_that_account_only(self):
        from bot_program.models import BrokerEquityReading
        u = _user("eq_prune")
        acct = _acct(u)
        # Not interfaced, so the sync skips it: the prune must be scoped
        # to the account that was just read, not run fleet-wide.
        other = _acct(_user("eq_other"), account_id="")
        _reading(acct, 100, days_ago=401)
        keep = _reading(acct, 100, days_ago=399)
        foreign = _reading(other, 100, days_ago=401)
        _run_sync()
        left = set(BrokerEquityReading.objects.filter(account=acct)
                   .values_list("pk", flat=True))
        self.assertIn(keep.pk, left)
        self.assertEqual(len(left), 2)           # the kept row + the new one
        self.assertTrue(BrokerEquityReading.objects.filter(
            pk=foreign.pk).exists())


class TheHighWaterMarkTests(TestCase):

    def setUp(self):
        self.user = _user("eq_hwm")
        self.acct = _acct(self.user)

    def test_no_reading_means_none(self):
        from bot_program.capital_truth import equity_drawdown, equity_high_water
        self.assertIsNone(equity_high_water(self.user))
        self.assertIsNone(equity_drawdown(self.user))

    def test_no_history_means_hwm_from_the_reading_itself(self):
        from bot_program.capital_truth import equity_drawdown, equity_high_water
        _stamp(self.acct, "500")
        hw = equity_high_water(self.user)
        self.assertEqual(hw["hwm"], 500.0)
        self.assertEqual(hw["n"], 0)
        dd = equity_drawdown(self.user)
        self.assertEqual(dd["drawdown_pct"], 0.0)
        self.assertEqual(dd["hwm"], 500.0)
        self.assertEqual(dd["n"], 0)
        self.assertFalse(dd["stale"])

    def test_the_drawdown_is_measured_against_the_window_high(self):
        from bot_program.capital_truth import equity_drawdown
        _reading(self.acct, 1000, days_ago=10)
        _reading(self.acct, 900, days_ago=5)
        _stamp(self.acct, "800")
        dd = equity_drawdown(self.user)
        self.assertEqual(dd["hwm"], 1000.0)
        self.assertAlmostEqual(dd["drawdown_pct"], 0.2)
        self.assertEqual(dd["n"], 2)

    def test_a_new_high_is_a_zero_drawdown_never_negative(self):
        from bot_program.capital_truth import equity_drawdown
        _reading(self.acct, 900, days_ago=3)
        _stamp(self.acct, "1000")
        dd = equity_drawdown(self.user)
        self.assertEqual(dd["hwm"], 1000.0)
        self.assertEqual(dd["drawdown_pct"], 0.0)

    def test_rows_outside_the_window_do_not_count(self):
        from bot_program.capital_truth import equity_drawdown
        _reading(self.acct, 5000, days_ago=91)
        _reading(self.acct, 1000, days_ago=30)
        _stamp(self.acct, "900")
        dd = equity_drawdown(self.user, window_days=90)
        self.assertEqual(dd["hwm"], 1000.0)
        self.assertAlmostEqual(dd["drawdown_pct"], 0.1)

    def test_a_currency_change_resets_the_history(self):
        """A GBP history behind a EUR reading is an exchange rate, not a
        drawdown."""
        from bot_program.capital_truth import equity_drawdown
        _reading(self.acct, 1000, days_ago=3, currency="GBP")
        _stamp(self.acct, "800", currency="EUR")
        dd = equity_drawdown(self.user)
        self.assertEqual(dd["hwm"], 800.0)
        self.assertEqual(dd["drawdown_pct"], 0.0)
        self.assertEqual(dd["n"], 0)
        self.assertEqual(dd["currency"], "EUR")

    def test_a_stale_reading_says_so(self):
        from bot_program.capital_truth import TRACKING_FRESH_SECONDS, equity_drawdown
        _stamp(self.acct, "800", age_seconds=TRACKING_FRESH_SECONDS + 60)
        self.assertTrue(equity_drawdown(self.user)["stale"])


class TheEntryPathCacheMergesTests(TestCase):
    """capital_truth.broker_equity stamps a cache into extras from the
    entry path, off a `cfg` the tick loaded once. It used to write that
    copy's WHOLE extras back — reverting a share the allocator wrote in
    between. It merges into the row now."""

    def _cfg(self, user):
        from bot_program.models import AssetBotConfig
        return AssetBotConfig.objects.create(
            user=user, asset_class="stock", name="live_stock", mode="live",
            enabled=True, symbols=["AAPL"], capital=Decimal("1000"),
            extras={"capital_tracks_broker": True})

    def test_a_share_written_mid_tick_survives_the_cache_stamp(self):
        from bot_program.capital_truth import broker_equity
        from bot_program.models import AssetBotConfig
        user = _user("eq_merge")
        cfg = self._cfg(user)                      # the runner's copy
        # The allocator applies a plan while the tick is running.
        row = AssetBotConfig.objects.get(pk=cfg.pk)
        row.extras = {**row.extras, "account_share_pct": 37.5}
        row.save(update_fields=["extras"])
        client = MagicMock()
        client.balance_usdt.return_value = 2500.0
        with patch("bot_program.engine.broker_router.client_for_symbol",
                   return_value=client):
            self.assertEqual(broker_equity(user, cfg), 2500.0)
        row.refresh_from_db()
        self.assertEqual(row.extras["account_share_pct"], 37.5)
        self.assertEqual(row.extras["broker_equity"], 2500.0)
        self.assertIn("broker_equity_at", row.extras)
        self.assertTrue(row.extras["capital_tracks_broker"])
        # The in-memory copy reads the merged row too, so the rest of the
        # tick sees the share the admin just confirmed.
        self.assertEqual(cfg.extras["account_share_pct"], 37.5)

    def test_the_cache_is_read_back_without_a_broker_call(self):
        from bot_program.capital_truth import broker_equity
        user = _user("eq_cached")
        cfg = self._cfg(user)
        cfg.extras = {**cfg.extras, "broker_equity": 1234.0,
                      "broker_equity_at": timezone.now().isoformat()}
        cfg.save(update_fields=["extras"])
        with patch("bot_program.engine.broker_router.client_for_symbol") \
                as client_for_symbol:
            self.assertEqual(broker_equity(user, cfg), 1234.0)
        client_for_symbol.assert_not_called()
