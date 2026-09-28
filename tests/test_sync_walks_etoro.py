"""The broker sync walks eToro, and the book can be an eToro row (2026-09-17).

Until this change `BrokerEquityReading.account` was a foreign key to
IBKRAccount and nothing else could land a reading, `broker_backed()` returned
IBKRAccount by construction, and `sync_broker_account` walked IBKR rows and
no others. An eToro account could be keyed, flagged, routed to, and TRADED
ON — and its equity would never reach a page, the drawdown governor, or the
arming preflight. The router would have moved money to a venue the book
could not see.

WHAT THESE TESTS CONFRONT

  * The sync stores the same five cells and the same history-row shape for
    eToro as for IBKR, keyed (broker, account_pk), from ONE broker call.
  * broker_backed() answers eToro only under the router's own rule — keyed
    AND flagged primary for at least one class — so "the broker that
    carries something" and "the broker whose equity is the book" are one
    answer. A user with no eToro flag sees IBKR exactly as before.
  * The two readers filter on the pair, so an eToro book's high-water mark
    is computed from eToro rows in eToro's currency and never from IBKR's.
  * A miss on eToro is COUNTED and LOGGED, not raised inside the miss
    handler (EtoroAccount has no host/port) — the silent-miss defect of
    2026-09-15 must not return through a new door.
  * The miss keys carry the broker kind: an IBKR row and an eToro row that
    share a pk must not share an outage counter.
"""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from bot_program.equity_models import BrokerEquityReading
from bot_program.models import EtoroAccount, IBKRAccount


def _etoro(user, *, keyed=True, demo=True, **flags):
    acct = EtoroAccount.objects.create(user=user, demo=demo, label="Main",
                                       **flags)
    if keyed:
        acct.set_credentials("k", "u")
    acct.save()
    return acct


def _client(reading=(2012.02, "EUR"), rows=None):
    c = MagicMock()
    c.net_liquidation.return_value = reading
    c.broker_portfolio.return_value = ([] if rows is None else rows)
    return c


def _sync_etoro(client):
    from bot_program.tasks import sync_etoro_accounts
    with patch("bot_program.engine.etoro_client.EtoroTrader",
               return_value=client):
        return sync_etoro_accounts.__wrapped__.__wrapped__()


class TheSyncStoresAnEtoroReadingTests(TestCase):

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user("es_u", password="x")
        self.acct = _etoro(self.user)

    def test_the_five_cells_and_one_history_row_land(self):
        rows = [{"symbol": "AAPL", "qty": 10.0, "side": "BUY",
                 "avg_cost": 190.5, "market_price": 0.0, "market_value": 0.0,
                 "unrealized_pnl": 0.0, "currency": "", "sec_type": "CFD"}]
        out = _sync_etoro(_client(rows=rows))
        self.assertEqual(out["attempted"], 1)
        self.assertEqual(out["stored"], 1)
        self.assertEqual(out["unreachable"], 0)
        acct = EtoroAccount.objects.get(pk=self.acct.pk)
        self.assertEqual(acct.last_equity, Decimal("2012.02"))
        self.assertEqual(acct.last_equity_currency, "EUR")
        self.assertIsNotNone(acct.last_equity_at)
        self.assertEqual(acct.broker_positions, rows)
        self.assertIsNotNone(acct.broker_positions_at)
        self.assertTrue(acct.connected)
        row = BrokerEquityReading.objects.get(broker="etoro",
                                              account_pk=acct.pk)
        self.assertEqual(row.value, Decimal("2012.02"))
        self.assertEqual(row.currency, "EUR")
        self.assertEqual(row.env, "paper")
        self.assertIsNone(row.account, "an eToro row must not borrow the "
                                       "IBKR foreign key")

    def test_live_keys_file_the_row_as_live(self):
        EtoroAccount.objects.filter(pk=self.acct.pk).update(demo=False)
        _sync_etoro(_client())
        self.assertEqual(BrokerEquityReading.objects.get(
            broker="etoro", account_pk=self.acct.pk).env, "live")

    def test_an_unkeyed_row_is_skipped_not_counted(self):
        EtoroAccount.objects.filter(pk=self.acct.pk).update(
            api_key_enc="", user_key_enc="")
        out = _sync_etoro(_client())
        self.assertEqual(out["attempted"], 0)
        self.assertFalse(BrokerEquityReading.objects.filter(
            broker="etoro").exists())

    def test_the_same_instant_stores_one_row(self):
        """A retried sync in the same second must not double a reading —
        the (broker, account_pk, at) uniqueness the IBKR path relies on."""
        fixed = timezone.now().replace(microsecond=0)
        with patch("django.utils.timezone.now", return_value=fixed):
            _sync_etoro(_client())
            _sync_etoro(_client())
        self.assertEqual(BrokerEquityReading.objects.filter(
            broker="etoro", account_pk=self.acct.pk).count(), 1)


class AMissOnEtoroIsCountedNotRaisedTests(TestCase):

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user("em_u", password="x")
        self.acct = _etoro(self.user)

    def test_both_reads_none_is_a_logged_miss(self):
        """EtoroAccount has no host or port. The miss handler used to format
        both into its warning; on an eToro row that raise would have swallowed
        the miss — the silent-miss defect returning through a new door."""
        c = _client(reading=None)
        c.broker_portfolio.return_value = None
        with self.assertLogs("bot_program.tasks", level="WARNING") as got:
            out = _sync_etoro(c)
        self.assertEqual(out["unreachable"], 1)
        self.assertEqual(out["stored"], 0)
        joined = "\n".join(got.output)
        self.assertIn("consecutive miss 1", joined)
        self.assertIn("Main", joined)
        self.assertFalse(BrokerEquityReading.objects.filter(
            broker="etoro").exists())
        self.assertEqual(cache.get(f"broker_sync:miss:etoro:{self.acct.pk}"),
                         1)

    def test_a_raise_inside_the_client_is_a_miss_too(self):
        c = MagicMock()
        c.net_liquidation.side_effect = RuntimeError("wire down")
        with self.assertLogs("bot_program.tasks", level="WARNING"):
            out = _sync_etoro(c)
        self.assertEqual(out["unreachable"], 1)

    def test_miss_keys_do_not_collide_across_brokers(self):
        """An IBKR row and an eToro row can share a pk. One broker's outage
        must not count against the other's alert."""
        from bot_program.tasks import _clear_broker_miss, _note_broker_miss
        ib = IBKRAccount.objects.create(user=self.user, port=4003,
                                        label="IB")
        ib.set_credentials("U1")
        ib.save()
        with patch("bot_program.notifications.notify_broker_unreachable"), \
             self.assertLogs("bot_program.tasks", level="WARNING"):
            _note_broker_miss(ib, self.user)
            _note_broker_miss(ib, self.user)
            _note_broker_miss(self.acct, self.user)
        self.assertEqual(cache.get(f"broker_sync:miss:ibkr:{ib.pk}"), 2)
        self.assertEqual(cache.get(f"broker_sync:miss:etoro:{self.acct.pk}"),
                         1)
        _clear_broker_miss(self.acct)
        self.assertIsNone(cache.get(f"broker_sync:miss:etoro:{self.acct.pk}"))
        self.assertEqual(cache.get(f"broker_sync:miss:ibkr:{ib.pk}"), 2,
                         "clearing eToro's counter cleared IBKR's")


class TheBookCanBeAnEtoroRowTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("bk_u", password="x")
        ib = IBKRAccount.objects.create(user=self.user, port=4003)
        ib.set_credentials("U1")
        ib.save()
        self.ib = ib

    def _fresh(self):
        return User.objects.get(pk=self.user.pk)

    def test_no_etoro_flag_means_ibkr_exactly_as_before(self):
        from bot_program.capital_truth import broker_backed
        _etoro(self.user)                           # keyed, no flags
        self.assertEqual(broker_backed(self._fresh()).pk, self.ib.pk)
        self.assertEqual(type(broker_backed(self._fresh())).__name__,
                         "IBKRAccount")

    def test_keyed_and_flagged_etoro_is_the_book(self):
        from bot_program.capital_truth import broker_backed
        et = _etoro(self.user, is_primary_for_stocks=True)
        found = broker_backed(self._fresh())
        self.assertEqual(type(found).__name__, "EtoroAccount")
        self.assertEqual(found.pk, et.pk)

    def test_flagged_but_unkeyed_etoro_is_not_the_book(self):
        """The router's rule, exactly: a flag with no keys routes to paper
        and the engine refuses to trade. It must not become the book either,
        or the preflight would read a blank equity as the account."""
        from bot_program.capital_truth import broker_backed
        _etoro(self.user, keyed=False, is_primary_for_stocks=True)
        self.assertEqual(type(broker_backed(self._fresh())).__name__,
                         "IBKRAccount")

    def test_the_high_water_mark_reads_etoro_rows_in_etoro_s_currency(self):
        from bot_program.capital_truth import equity_high_water
        et = _etoro(self.user, is_primary_for_stocks=True)
        now = timezone.now()
        EtoroAccount.objects.filter(pk=et.pk).update(
            last_equity=Decimal("1900"), last_equity_currency="EUR",
            last_equity_at=now)
        for days, value in ((5, "2100"), (3, "1950")):
            BrokerEquityReading.objects.create(
                broker="etoro", account_pk=et.pk, value=Decimal(value),
                currency="EUR", env="paper", at=now - timedelta(days=days))
        # IBKR history in the same currency must NOT leak into eToro's hwm.
        BrokerEquityReading.objects.create(
            broker="ibkr", account_pk=self.ib.pk, account=self.ib,
            value=Decimal("9999"), currency="EUR", env="live",
            at=now - timedelta(days=1))
        hwm = equity_high_water(self._fresh())
        self.assertIsNotNone(hwm)
        self.assertEqual(hwm["hwm"], 2100.0)
        self.assertEqual(hwm["currency"], "EUR")
        self.assertEqual(hwm["n"], 2)

    def test_the_governor_reads_the_pair_too(self):
        from bot_program.share_allocator import drop_24h
        et = _etoro(self.user, is_primary_for_stocks=True)
        now = timezone.now()
        EtoroAccount.objects.filter(pk=et.pk).update(
            last_equity=Decimal("1900"), last_equity_currency="EUR",
            last_equity_at=now)
        BrokerEquityReading.objects.create(
            broker="etoro", account_pk=et.pk, value=Decimal("2000"),
            currency="EUR", env="paper", at=now - timedelta(hours=2))
        dd = drop_24h(self._fresh(), now=now)
        self.assertIsNotNone(dd)
        self.assertAlmostEqual(dd, 0.05, places=4)


class TheTwinIsWiredTests(TestCase):

    def test_it_is_on_the_beat_schedule_under_the_same_switch(self):
        from pathlib import Path

        from django.conf import settings
        celery = (Path(settings.BASE_DIR) / "config"
                  / "celery.py").read_text(encoding="utf-8")
        tasks = (Path(settings.BASE_DIR) / "bot_program"
                 / "tasks.py").read_text(encoding="utf-8")
        self.assertIn("bot_program.tasks.sync_etoro_accounts", celery)
        block = tasks[tasks.index("def sync_etoro_accounts"):]
        head = tasks[:tasks.index("def sync_etoro_accounts")]
        self.assertIn('@guarded_task("broker_account_sync")',
                      head[-200:], "the twin is not under the same switch "
                                   "as its sibling")

    def test_a_row_written_through_the_fk_alone_gets_its_pair(self):
        """Found by the readers' own tests the moment they filtered on the
        pair: every fixture seeded `account=acct` and nothing else, and the
        readers saw no history at all — a drawdown of zero, forever, for any
        row created the old way. The FK is a convenience that fills the key;
        it must never be a second key the readers cannot see."""
        user = User.objects.create_user("lg_u", password="x")
        ib = IBKRAccount.objects.create(user=user, port=4003)
        ib.set_credentials("U1")
        ib.save()
        row = BrokerEquityReading.objects.create(
            account=ib, value=Decimal("1"), currency="EUR", env="live",
            at=timezone.now())                      # no pair given
        row.refresh_from_db()
        self.assertEqual((row.broker, row.account_pk), ("ibkr", ib.pk))
        self.assertTrue(BrokerEquityReading.objects.filter(
            broker="ibkr", account_pk=ib.pk).exists())

    def test_an_etoro_row_never_borrows_the_fk_derivation(self):
        """The derivation fires only when the FK is set and the pair is not.
        An eToro row has no FK; its pair is written explicitly and must
        survive save() untouched."""
        user = User.objects.create_user("lg_e", password="x")
        et = _etoro(user)
        row = BrokerEquityReading.objects.create(
            broker="etoro", account_pk=et.pk, value=Decimal("2"),
            currency="EUR", env="paper", at=timezone.now())
        row.refresh_from_db()
        self.assertEqual((row.broker, row.account_pk, row.account_id),
                         ("etoro", et.pk, None))
