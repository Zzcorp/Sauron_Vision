"""Saxo is a venue the platform routes to, reads, and can call the book.

Wired on 2026-09-19, the way eToro was wired on 09-17, and held here at
the three places that must agree about WHICH broker carries an asset
class: the router (both of its public functions), capital_truth's idea of
the book, and the page that lets an operator claim a class.

PRECEDENCE: saxo, then etoro, then ibkr. One tuple
(broker_router.VENUE_PRECEDENCE), three readers, and a test that the
three cannot drift — because "which broker carries stocks" having two
answers is how an operator's orders move venue without anyone deciding.

WHAT THESE TESTS CONFRONT

  * The flags against the router: a keyed row with NO flag carries
    nothing and is routed to by nothing. That is the brake, and it is
    off by default.
  * The router against the book: broker_backed() applies the router's own
    rule (keyed AND flagged), so "the broker that carries something" and
    "the broker whose equity is the book" are one answer.
  * A dead session against a live config: the router hands back a
    PaperTrader, which asset_engine refuses to trade — loudly — rather
    than trading somewhere the operator did not choose.
  * The sync against the keeper: a row with no live session is SKIPPED,
    not attempted, so a known sign-in is not also counted as an
    unreachable broker and alerted twice.
  * The history row against the readers: keyed (broker="saxo",
    account_pk), which is what equity_high_water and drop_24h filter on.
"""
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from bot_program.capital_truth import broker_backed, broker_kind
from bot_program.engine import broker_router as router
from bot_program.models import EtoroAccount, IBKRAccount, SaxoAccount

CLASSES = ("stock", "forex", "commodity", "crypto")


def saxo(user, *, flags=(), session=True, sim=True, keyed=True):
    acct = SaxoAccount.objects.create(
        user=user, sim=sim,
        redirect_uri="https://h.example.net/brokers/saxo/callback/")
    if keyed:
        acct.set_credentials("app-key", "app-secret")
    for cls in flags:
        setattr(acct, {"stock": "is_primary_for_stocks",
                       "forex": "is_primary_for_forex",
                       "commodity": "is_primary_for_commodity",
                       "crypto": "is_primary_for_crypto"}[cls], True)
    if session:
        now = timezone.now()
        acct.set_tokens("acc", "ref", now + timedelta(seconds=1200),
                        refresh_expires_at=now + timedelta(seconds=2400))
        acct.connected = True
    acct.save()
    return acct


def etoro(user, *, flags=("stock",)):
    acct = EtoroAccount.objects.create(user=user)
    acct.set_credentials("k", "u")
    for cls in flags:
        setattr(acct, {"stock": "is_primary_for_stocks",
                       "forex": "is_primary_for_forex",
                       "commodity": "is_primary_for_commodity",
                       "crypto": "is_primary_for_crypto"}[cls], True)
    acct.save()
    return acct


def ibkr(user, *, flags=("stock",)):
    acct = IBKRAccount.objects.create(user=user, port=4004)
    acct.set_credentials("DU1234567")
    acct.username_enc, acct.password_enc = "x", "y"
    for cls in flags:
        attr = f"is_primary_for_{'stocks' if cls == 'stock' else cls}"
        if hasattr(acct, attr):
            setattr(acct, attr, True)
    acct.save()
    return acct


def _fresh(user):
    return User.objects.get(pk=user.pk)


def _instrument(symbol, asset_class):
    """The router reads the instrument to learn an asset class; without one
    every symbol falls through to paper."""
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class})
    return inst


def _sync(client=None, side_effect=None):
    """The task's BODY, past @shared_task and @guarded_task — the house
    pattern (tests/test_sync_walks_etoro.py). The decorator itself is
    pinned by TheGateTests below, read off the source."""
    from bot_program.tasks import sync_saxo_accounts
    kw = ({"side_effect": side_effect} if side_effect
          else {"return_value": client})
    with mock.patch("bot_program.engine.saxo_client.SaxoTrader", **kw) as T:
        return sync_saxo_accounts.__wrapped__.__wrapped__(), T


class TheFlagsAreTheBrakeTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("wire_flags", password="x")

    def test_a_keyed_row_with_no_flag_carries_nothing(self):
        saxo(self.user, flags=())
        u = _fresh(self.user)
        for cls in CLASSES:
            with self.subTest(cls):
                self.assertFalse(router._saxo_overrides(u, cls))
        self.assertIsNone(broker_backed(u))

    def test_a_flag_claims_exactly_its_class(self):
        saxo(self.user, flags=("forex",))
        u = _fresh(self.user)
        self.assertTrue(router._saxo_overrides(u, "forex"))
        for cls in ("stock", "commodity", "crypto"):
            self.assertFalse(router._saxo_overrides(u, cls))

    def test_the_stock_flag_carries_etfs_too(self):
        acct = saxo(self.user, flags=("stock",))
        self.assertTrue(acct.is_primary_for("stock"))
        self.assertTrue(acct.is_primary_for("etf"))
        self.assertFalse(acct.is_primary_for("options"))
        self.assertFalse(acct.is_primary_for("nonsense"))

    def test_no_row_at_all_claims_nothing(self):
        for cls in CLASSES:
            self.assertFalse(router._saxo_overrides(self.user, cls))


class ThePrecedenceTests(TestCase):
    """saxo, then etoro, then ibkr — in all three places that decide."""

    def setUp(self):
        self.user = User.objects.create_user("wire_prec", password="x")

    def test_the_tuple_is_the_order(self):
        self.assertEqual(router.VENUE_PRECEDENCE, ("saxo", "etoro", "ibkr"))

    def test_saxo_wins_the_class_all_three_claim(self):
        saxo(self.user, flags=("stock",))
        etoro(self.user, flags=("stock",))
        ibkr(self.user, flags=("stock",))
        _instrument("AAPL", "stock")
        u = _fresh(self.user)
        self.assertEqual(router.broker_name_for_symbol(u, "AAPL"), "saxo")
        client = router.client_for_symbol(u, "AAPL")
        self.assertEqual(type(client).__name__, "SaxoTrader")

    def test_etoro_still_wins_a_class_saxo_does_not_claim(self):
        saxo(self.user, flags=("forex",))
        etoro(self.user, flags=("stock",))
        _instrument("AAPL", "stock")
        _instrument("EURUSD", "forex")
        u = _fresh(self.user)
        self.assertEqual(router.broker_name_for_symbol(u, "AAPL"), "etoro")
        self.assertEqual(router.broker_name_for_symbol(u, "EURUSD"), "saxo")
        self.assertEqual(type(router.client_for_symbol(u, "AAPL")).__name__,
                         "EtoroTrader")
        self.assertEqual(type(router.client_for_symbol(u, "EURUSD")).__name__,
                         "SaxoTrader")

    def test_options_and_cfd_are_still_forced_to_ibkr(self):
        """No account row has a flag for either, so the override can never
        take them — the forced rule holds."""
        saxo(self.user, flags=("stock", "forex", "commodity", "crypto"))
        u = _fresh(self.user)
        for cls in ("options", "cfd"):
            with self.subTest(cls):
                self.assertFalse(router._saxo_overrides(u, cls))
                _instrument(f"FORCED_{cls}", cls)
                self.assertEqual(
                    router.broker_name_for_symbol(u, f"FORCED_{cls}"), "ibkr")


class TheClientTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("wire_client", password="x")

    def test_a_live_session_gives_a_saxo_trader_on_the_rows_environment(self):
        _instrument("AAPL", "stock")
        saxo(self.user, flags=("stock",), sim=True)
        client = router.client_for_symbol(_fresh(self.user), "AAPL")
        self.assertEqual(type(client).__name__, "SaxoTrader")
        # The ROW decides the world: a SIM application serves a live config
        # with SIM, because the keys are what Saxo authenticates.
        self.assertEqual(client.env, "sim")
        saxo2 = SaxoAccount.objects.get(user=self.user)
        saxo2.sim = False
        saxo2.save()
        self.assertEqual(
            router.client_for_symbol(_fresh(self.user), "AAPL").env, "live")

    def test_a_dead_session_gives_paper_not_saxo(self):
        _instrument("AAPL", "stock")
        """asset_engine refuses to trade a live config against a
        PaperTrader, loudly. That refusal is the point: better a loud stop
        than an order somewhere the operator did not choose."""
        saxo(self.user, flags=("stock",), session=False)
        with self.assertLogs("bot_program.engine.broker_router",
                             level="WARNING"):
            client = router.client_for_symbol(_fresh(self.user), "AAPL")
        self.assertEqual(type(client).__name__, "PaperTrader")

    def test_an_expired_session_gives_paper(self):
        _instrument("AAPL", "stock")
        acct = saxo(self.user, flags=("stock",))
        acct.set_tokens("a", "r", timezone.now(),
                        refresh_expires_at=timezone.now() - timedelta(seconds=1))
        acct.save()
        with self.assertLogs("bot_program.engine.broker_router",
                             level="WARNING"):
            self.assertEqual(
                type(router.client_for_symbol(_fresh(self.user), "AAPL")).__name__,
                "PaperTrader")

    def test_an_unkeyed_row_gives_paper(self):
        _instrument("AAPL", "stock")
        saxo(self.user, flags=("stock",), keyed=False)
        self.assertEqual(
            type(router.client_for_symbol(_fresh(self.user), "AAPL")).__name__,
            "PaperTrader")


class TheBookTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("wire_book", password="x")

    def test_a_keyed_and_flagged_saxo_row_is_the_book_over_the_others(self):
        saxo(self.user, flags=("stock",))
        etoro(self.user, flags=("stock",))
        ibkr(self.user, flags=("stock",))
        book = broker_backed(_fresh(self.user))
        self.assertEqual(type(book).__name__, "SaxoAccount")
        self.assertEqual(broker_kind(book), "saxo")

    def test_a_keyed_but_unflagged_saxo_row_is_not_the_book(self):
        saxo(self.user, flags=())
        etoro(self.user, flags=("stock",))
        self.assertEqual(type(broker_backed(_fresh(self.user))).__name__,
                         "EtoroAccount")

    def test_a_registered_row_that_never_connected_can_still_be_the_book(self):
        """Carriage is a CONFIGURATION fact; reachability is answered by the
        age of the reading. A book with no reading shows an em dash and the
        preflight refuses to arm against it — which is the honest state,
        not a reason to pretend another broker is the book."""
        saxo(self.user, flags=("stock",), session=False)
        book = broker_backed(_fresh(self.user))
        self.assertEqual(type(book).__name__, "SaxoAccount")
        self.assertIsNone(book.last_equity)

    def test_both_broker_kind_helpers_know_saxo(self):
        from bot_program.tasks import _broker_kind
        acct = saxo(self.user, flags=("stock",))
        self.assertEqual(broker_kind(acct), "saxo")
        self.assertEqual(_broker_kind(acct), "saxo")
        # and a row neither helper knows still files under ibkr, as before
        self.assertEqual(broker_kind(ibkr(self.user)), "ibkr")


class TheSyncTests(TestCase):

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.user = User.objects.create_user("wire_sync", password="x")

    def _client(self, equity=(12345.67, "EUR"), rows=None):
        return mock.Mock(net_liquidation=mock.Mock(return_value=equity),
                         broker_portfolio=mock.Mock(
                             return_value=rows if rows is not None else []))

    def test_a_row_with_no_session_is_skipped_not_attempted(self):
        """The keeper owns the session's health and the page already says
        "sign in again"; attempting it here would alert twice for one fact."""
        saxo(self.user, flags=("stock",), session=False)
        out, T = _sync(self._client())
        T.assert_not_called()
        self.assertEqual(out["no_session"], 1)
        self.assertEqual(out["attempted"], 0)

    def test_an_unregistered_row_is_not_walked_at_all(self):
        saxo(self.user, flags=("stock",), keyed=False)
        out, _T = _sync(self._client())
        self.assertEqual((out["attempted"], out["no_session"]), (0, 0))

    def test_a_reading_lands_on_the_row_and_in_the_history(self):
        acct = saxo(self.user, flags=("stock",))
        rows = [{"symbol": "AAPL", "qty": 10, "side": "BUY",
                 "avg_cost": 200.0, "market_price": 210.0}]
        out, _T = _sync(self._client(rows=rows))
        acct.refresh_from_db()
        self.assertEqual(out, {"attempted": 1, "stored": 1, "unreachable": 0,
                               "no_session": 0})
        self.assertEqual(float(acct.last_equity), 12345.67)
        self.assertEqual(acct.last_equity_currency, "EUR")
        self.assertIsNotNone(acct.last_equity_at)
        self.assertEqual(acct.broker_positions, rows)
        self.assertIsNotNone(acct.broker_positions_at)
        self.assertTrue(acct.connected)

        from bot_program.equity_models import BrokerEquityReading
        # Keyed on the pair every reader filters by — equity_high_water and
        # the share allocator's drop_24h both do.
        reading = BrokerEquityReading.objects.get(broker="saxo",
                                                  account_pk=acct.pk)
        self.assertEqual(float(reading.value), 12345.67)
        self.assertEqual(reading.currency, "EUR")

    def test_an_unreachable_broker_counts_and_notes_the_miss(self):
        saxo(self.user, flags=("stock",))
        dead = mock.Mock(net_liquidation=mock.Mock(return_value=None),
                         broker_portfolio=mock.Mock(return_value=None))
        with mock.patch("bot_program.tasks._note_broker_miss") as miss:
            out, _T = _sync(dead)
        self.assertEqual(out["unreachable"], 1)
        self.assertEqual(out["stored"], 0)
        miss.assert_called_once()

    def test_a_raising_client_does_not_stop_the_walk(self):
        saxo(self.user, flags=("stock",))
        other = User.objects.create_user("wire_sync2", password="x")
        saxo(other, flags=("stock",))
        calls = {"n": 0}

        def flaky(acct):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("socket died")
            return self._client()

        with mock.patch("bot_program.tasks._note_broker_miss"):
            with self.assertLogs("bot_program.tasks", level="WARNING"):
                out, _T = _sync(side_effect=flaky)
        self.assertEqual(out["attempted"], 2)
        self.assertEqual(out["unreachable"], 1)
        self.assertEqual(out["stored"], 1)

    def test_the_switch_governs_it(self):
        """Read off the source, the way the eToro twin is held: one switch
        governs "does the platform read its brokers", and it is the SAME
        switch, not a second one an operator would have to find."""
        from pathlib import Path

        from django.conf import settings
        src = (Path(settings.BASE_DIR) / "bot_program" / "tasks.py").read_text(
            encoding="utf-8")
        block = src[src.index("def sync_saxo_accounts"):]
        head = src[:src.index("def sync_saxo_accounts")]
        self.assertIn('@guarded_task("broker_account_sync")', head[-120:],
                      "sync_saxo_accounts is not gated by the broker switch")
        self.assertIn("SaxoAccount.objects.exclude(app_key_enc=\"\")",
                      block[:2000])

    def test_the_beat_schedules_it_at_the_etoro_cadence(self):
        from config.celery import app
        entry = app.conf.beat_schedule.get("sync-saxo-accounts")
        self.assertIsNotNone(entry)
        self.assertEqual(entry["task"], "bot_program.tasks.sync_saxo_accounts")
        self.assertEqual(entry["schedule"],
                         app.conf.beat_schedule["sync-etoro-accounts"]["schedule"])


class ThePageClaimsClassesTests(TestCase):

    def setUp(self):
        self.admin = User.objects.create_superuser("wire_admin", "a@x", "x")
        self.client.login(username="wire_admin", password="x")

    def _save(self, **over):
        data = {"target_username": self.admin.username,
                "saxo_app_key": "k", "saxo_app_secret": "s",
                "saxo_redirect_uri": "https://h.example.net/brokers/saxo/callback/",
                "sim": "on"}
        data.update(over)
        return self.client.post(reverse("hq_save_saxo"), data, follow=True)

    def test_the_boxes_set_the_flags_and_unchecked_means_off(self):
        self._save(primary_stocks="on", primary_forex="on")
        acct = SaxoAccount.objects.get(user=self.admin)
        self.assertTrue(acct.is_primary_for_stocks)
        self.assertTrue(acct.is_primary_for_forex)
        self.assertFalse(acct.is_primary_for_commodity)
        self.assertFalse(acct.is_primary_for_crypto)
        self._save()
        acct.refresh_from_db()
        self.assertFalse(acct.is_primary_for_stocks)

    def test_a_contested_class_is_named_on_the_losing_row(self):
        """The router resolves it deterministically; silence about it is how
        an operator's stock orders move venue without anyone deciding."""
        etoro(self.admin, flags=("stock",))
        self._save(primary_stocks="on")
        page = self.client.get(reverse("brokers_page"))
        self.assertContains(page, "claimed by two brokers")
        self.assertContains(page, "stock → saxo")

    def test_one_claimant_says_nothing_about_conflicts(self):
        self._save(primary_stocks="on")
        page = self.client.get(reverse("brokers_page"))
        self.assertNotContains(page, "claimed by two brokers")


class EveryBookableRowAnswersTheHelpersTests(TestCase):
    """The test whose absence let a defect ship on 2026-09-17.

    capital_truth.broker_view() reads `acct.env_label` with NO guard, and
    that property existed on IBKRAccount alone. broker_backed() had
    returned an EtoroAccount since 09-17, so ticking one primary-for box
    would have raised AttributeError on /portfolio/, /positions/, /setup/,
    /command/ and in `preflight_live`. That commit said a survey of the
    nine broker_backed() call sites found nothing IBKR-specific — and it
    was wrong, because the property is reached one level down, through a
    helper.

    So this walks EVERY row that can be the book through EVERY helper that
    takes one. A new bookable row fails here rather than on a page.
    """

    def setUp(self):
        self.user = User.objects.create_user("wire_helpers", password="x")

    def _each_book(self):
        """[(kind, a user whose book is that kind)]."""
        out = []
        for kind, make in (("saxo", saxo), ("etoro", etoro), ("ibkr", ibkr)):
            u = User.objects.create_user(f"book_{kind}", password="x")
            make(u, flags=("stock",))
            out.append((kind, _fresh(u)))
        return out

    def test_every_row_has_an_env_label_that_is_a_string(self):
        for kind, u in self._each_book():
            with self.subTest(kind):
                acct = broker_backed(u)
                self.assertIsNotNone(acct, kind)
                label = acct.env_label
                self.assertIsInstance(label, str)
                self.assertTrue(label.strip(), f"{kind}: empty env_label")

    def test_broker_view_answers_for_every_book_and_names_it(self):
        from bot_program.capital_truth import broker_view
        expected = {"saxo": "Saxo Bank", "etoro": "eToro", "ibkr": "IBKR"}
        for kind, u in self._each_book():
            with self.subTest(kind):
                view = broker_view(u)
                self.assertIsNotNone(view, kind)
                self.assertEqual(view["kind"], kind)
                self.assertEqual(view["name"], expected[kind])
                self.assertIsInstance(view["env"], str)

    def test_the_templates_print_the_broker_they_were_given(self):
        """Three pages hardcoded IBKR over whatever book they held."""
        from pathlib import Path

        from django.conf import settings
        root = Path(settings.BASE_DIR)
        for rel in ("templates/_partials/broker_account.html",
                    "templates/dashboard/positions_list.html"):
            body = (root / rel).read_text(encoding="utf-8")
            with self.subTest(rel):
                self.assertIn("broker.name", body)
                self.assertNotIn("IBKR {{ broker.label }}", body)

    def test_every_adapter_capital_truth_probes_has_balance_usdt(self):
        """capital_truth.broker_equity() probes that exact name; an adapter
        without it leaves capital_mismatches, pool_oversubscription and
        the health page's capital check silently blind on every config it
        carries."""
        import importlib

        from tests.test_broker_contract import ADAPTERS
        for name, (module, cls) in ADAPTERS.items():
            # PaperTrader is deliberately exempt: broker_equity() returns
            # None for a paper config before it probes anything, and a live
            # config handed a PaperTrader is REFUSED rather than sized — so
            # a balance on it would be a number with no account behind it.
            if name == "paper":
                continue
            with self.subTest(name):
                klass = getattr(importlib.import_module(module), cls)
                self.assertTrue(callable(getattr(klass, "balance_usdt", None)),
                                f"{name} has no balance_usdt()")


class TheSyncFeedsTheAllocatorTests(TestCase):
    """A pool that tracks the account is re-sized by the sync and by
    nothing else, and an hour-old reading freezes every entry. Neither new
    walk called the two functions that do it."""

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.user = User.objects.create_user("wire_alloc", password="x")

    def _reading_client(self, value=1000.0, currency="EUR", rows=None):
        return mock.Mock(
            net_liquidation=mock.Mock(return_value=(value, currency)),
            broker_portfolio=mock.Mock(return_value=rows or []))

    def test_the_book_retunes_its_followers_and_can_trigger_a_shock(self):
        saxo(self.user, flags=("stock",))
        with mock.patch("bot_program.tasks._follow_the_account") as follow, \
             mock.patch("bot_program.tasks._shock_trigger") as shock:
            out, _T = _sync(self._reading_client())
        self.assertEqual(out["stored"], 1)
        follow.assert_called_once()
        self.assertEqual(follow.call_args.args[1:], (1000.0, "EUR"))
        shock.assert_called_once()

    def test_a_row_that_is_not_the_book_does_not_retune_anything(self):
        """Two brokers retuning the same pools would fight over them."""
        saxo(self.user, flags=())
        with mock.patch("bot_program.tasks._follow_the_account") as follow, \
             mock.patch("bot_program.tasks._shock_trigger") as shock:
            out, _T = _sync(self._reading_client())
        self.assertEqual(out["stored"], 1)
        follow.assert_not_called()
        shock.assert_not_called()

    def test_the_history_row_records_which_environment_it_came_from(self):
        """Saxo's SIM and LIVE are two worlds on ONE row: without this a
        simulated balance and a real one are indistinguishable."""
        acct = saxo(self.user, flags=("stock",), sim=True)
        with mock.patch("bot_program.tasks._follow_the_account"), \
             mock.patch("bot_program.tasks._shock_trigger"):
            _sync(self._reading_client(value=1.0))
        from bot_program.equity_models import BrokerEquityReading
        self.assertEqual(
            BrokerEquityReading.objects.get(broker="saxo",
                                            account_pk=acct.pk).env, "paper")

    def test_a_pass_that_stored_no_equity_still_counts_as_done(self):
        """The gate's DONE counter belongs to the pass: counting it inside
        the history try graded the component 'handled N rows and stored
        none'."""
        saxo(self.user, flags=("stock",))
        out, _T = _sync(mock.Mock(
            net_liquidation=mock.Mock(return_value=None),
            broker_portfolio=mock.Mock(return_value=[{"symbol": "AAPL"}])))
        self.assertEqual((out["attempted"], out["stored"]), (1, 1))

    def test_every_interfaced_book_is_selected_for_the_allocator(self):
        """Three callers had written "walk IBKRAccount" and each silently
        skipped a Saxo or an eToro book."""
        from bot_program.tasks import _users_with_a_broker_row
        saxo(self.user, flags=("stock",))
        u2 = User.objects.create_user("wire_alloc2", password="x")
        etoro(u2)
        u3 = User.objects.create_user("wire_alloc3", password="x")
        ibkr(u3)
        User.objects.create_user("wire_alloc4", password="x")
        names = set(_users_with_a_broker_row().values_list("username",
                                                           flat=True))
        self.assertEqual(names, {"wire_alloc", "wire_alloc2", "wire_alloc3"})


class TheSweepReadsAnyBookTests(TestCase):
    """The sweep that exists to find a position no row claims was blind on
    the two newest venues: it read acct.host / .port / .client_id and
    called acquire_trader, which on a Saxo row is an AttributeError,
    swallowed and counted as "broker unavailable"."""

    def setUp(self):
        self.user = User.objects.create_user("wire_sweep", password="x")

    def _sweep(self):
        from bot_program.reconcile_asset import reconcile_unknown_positions
        return reconcile_unknown_positions(self.user)

    def test_a_saxo_book_is_read_through_its_own_adapter(self):
        saxo(self.user, flags=("stock",))
        with mock.patch("bot_program.engine.saxo_client.SaxoTrader") as T:
            with mock.patch("bot_program.reconcile_asset._broker_open_symbols",
                            return_value={"symbols": {"AAPL"}}) as probe:
                out = self._sweep()
        T.assert_called_once()
        probe.assert_called_once()
        self.assertEqual(out["checked"], 1)
        self.assertEqual(out["errors"], 0)
        self.assertIn("AAPL", out["symbols"])

    def test_a_saxo_book_with_no_session_is_an_error_not_a_clean_sweep(self):
        saxo(self.user, flags=("stock",), session=False)
        with self.assertLogs("bot_program.reconcile_asset", level="WARNING"):
            out = self._sweep()
        self.assertEqual(out["errors"], 1)
        self.assertEqual(out["broker_unavailable"], 1)
        self.assertEqual(out["unclaimed"], 0)

    def test_an_etoro_book_is_read_through_its_own_adapter(self):
        etoro(self.user, flags=("stock",))
        with mock.patch("bot_program.engine.etoro_client.EtoroTrader") as T:
            with mock.patch("bot_program.reconcile_asset._broker_open_symbols",
                            return_value={"symbols": set()}):
                out = self._sweep()
        T.assert_called_once()
        self.assertEqual(out["checked"], 1)
        self.assertEqual(out["errors"], 0)


class TheDrawdownGovernorIgnoresTheOtherWorldTests(TestCase):
    """A simulated balance must never sit in a real account's high-water
    mark. Saxo and eToro carry two environments on ONE row, so without a
    filter the governor that de-risks real money reads readings taken in
    a simulator — and the number it de-risks against is the highest of
    both.

    A row that never recorded an `env` is KEPT: excluding it would drop
    every reading written before the column was filled, and "unknown
    provenance" is not "the wrong world".
    """

    def setUp(self):
        self.user = User.objects.create_user("wire_env", password="x")

    def _reading(self, acct, value, *, env, minutes_ago=10, currency="EUR"):
        from bot_program.capital_truth import broker_kind
        from bot_program.equity_models import BrokerEquityReading
        return BrokerEquityReading.objects.create(
            broker=broker_kind(acct), account_pk=acct.pk, env=env,
            value=Decimal(str(value)), currency=currency,
            at=timezone.now() - timedelta(minutes=minutes_ago))

    def _live_row(self, value=1000.0, currency="EUR"):
        """A LIVE Saxo row carrying a current reading."""
        acct = saxo(self.user, flags=("stock",), sim=False)
        acct.last_equity = Decimal(str(value))
        acct.last_equity_currency = currency
        acct.last_equity_at = timezone.now()
        acct.save()
        return acct

    def test_broker_env_reads_each_rows_own_flag(self):
        from bot_program.capital_truth import broker_env
        self.assertEqual(broker_env(saxo(self.user, sim=True)), "paper")
        SaxoAccount.objects.all().delete()
        self.assertEqual(broker_env(saxo(self.user, sim=False)), "live")
        u2 = User.objects.create_user("wire_env2", password="x")
        self.assertEqual(broker_env(etoro(u2)), "paper")     # demo default
        u3 = User.objects.create_user("wire_env3", password="x")
        self.assertEqual(broker_env(ibkr(u3)),
                         IBKRAccount.objects.get(user=u3).env or "")

    def test_a_simulated_high_water_mark_is_not_a_live_one(self):
        from bot_program.capital_truth import equity_high_water
        acct = self._live_row(value=1000.0)
        self._reading(acct, 9000.0, env="paper")     # a SIM fortune
        self._reading(acct, 1100.0, env="live")
        hw = equity_high_water(_fresh(self.user))
        self.assertEqual(hw["hwm"], 1100.0)
        self.assertEqual(hw["n"], 1)

    def test_a_reading_with_no_recorded_environment_still_counts(self):
        from bot_program.capital_truth import equity_high_water
        acct = self._live_row(value=1000.0)
        self._reading(acct, 1200.0, env="")
        self.assertEqual(equity_high_water(_fresh(self.user))["hwm"], 1200.0)

    def test_the_24h_drop_ignores_the_other_world_too(self):
        from bot_program.share_allocator import drop_24h
        acct = self._live_row(value=900.0)
        self._reading(acct, 9000.0, env="paper", minutes_ago=30)
        self._reading(acct, 1000.0, env="live", minutes_ago=30)
        drop = drop_24h(_fresh(self.user))
        # Against the live top of 1000, not the simulator's 9000.
        self.assertAlmostEqual(drop, (1000.0 - 900.0) / 1000.0, places=6)

    def test_with_no_live_history_the_drop_is_unmeasured_not_zero(self):
        from bot_program.share_allocator import drop_24h
        acct = self._live_row(value=900.0)
        self._reading(acct, 9000.0, env="paper", minutes_ago=30)
        self.assertIsNone(drop_24h(_fresh(self.user)))


class TheCloseAsksTheVenueTests(TestCase):
    """An opposite market order does not flatten a Saxo position under the
    FifoEndOfDay netting profile: both lots stay open until the evening
    netting, so the platform would book the row CLOSED against a position
    the broker still holds."""

    def setUp(self):
        self.user = User.objects.create_user("wire_close", password="x")

    def _trade(self, **meta):
        from bot_program.asset_models import AssetBotConfig, AssetBotTrade
        cfg, _ = AssetBotConfig.objects.get_or_create(
            user=self.user, name="close_pool",
            defaults={"asset_class": "stock", "mode": "live",
                      "symbols": ["AAPL"], "capital": Decimal("1000"),
                      "base_currency": "EUR", "enabled": True})
        return AssetBotTrade.objects.create(
            config=cfg, asset_class="stock", symbol="AAPL", side="BUY",
            qty=Decimal("10"), entry_price=Decimal("200"), status="OPEN",
            paper=False, metadata=dict(meta))

    def _close(self, trade, client):
        from bot_program.asset_engine.base import AssetBot
        return AssetBot._submit_close_order(
            mock.Mock(asset_class="stock"), trade, client, "cid")

    def test_a_client_that_does_not_answer_is_closed_exactly_as_before(self):
        """Every adapter but Saxo. The old path, untouched."""
        client = mock.Mock(spec=["market_order"])
        client.market_order.return_value = {"status": "FILLED"}
        self._close(self._trade(protective_trade_id="P1"), client)
        client.market_order.assert_called_once()
        self.assertEqual(client.market_order.call_args.args[1], "SELL")

    def test_a_venue_that_needs_a_position_id_gets_one(self):
        client = mock.Mock(spec=["market_order", "close_position",
                                 "close_needs_position_id"])
        client.close_needs_position_id.return_value = True
        client.close_position.return_value = {"status": "FILLED"}
        self._close(self._trade(protective_trade_id="P9"), client)
        client.close_position.assert_called_once_with("P9", "AAPL", 10.0)
        client.market_order.assert_not_called()

    def test_a_venue_that_nets_immediately_uses_the_ordinary_close(self):
        client = mock.Mock(spec=["market_order", "close_position",
                                 "close_needs_position_id"])
        client.close_needs_position_id.return_value = False
        client.market_order.return_value = {"status": "FILLED"}
        self._close(self._trade(protective_trade_id="P9"), client)
        client.market_order.assert_called_once()
        client.close_position.assert_not_called()

    def test_a_broker_that_cannot_say_keeps_the_old_path(self):
        client = mock.Mock(spec=["market_order", "close_position",
                                 "close_needs_position_id"])
        client.close_needs_position_id.side_effect = RuntimeError("no session")
        client.market_order.return_value = {"status": "FILLED"}
        with self.assertLogs("bot_program.asset_engine.base", level="WARNING"):
            self._close(self._trade(protective_trade_id="P9"), client)
        client.market_order.assert_called_once()

    def test_no_position_id_says_out_loud_what_the_close_will_leave(self):
        client = mock.Mock(spec=["market_order", "close_position",
                                 "close_needs_position_id"])
        client.close_needs_position_id.return_value = True
        client.market_order.return_value = {"status": "FILLED"}
        with self.assertLogs("bot_program.asset_engine.base",
                             level="ERROR") as cm:
            self._close(self._trade(), client)
        self.assertTrue(any("BOTH lots open" in m for m in cm.output))
        client.market_order.assert_called_once()
        client.close_position.assert_not_called()

    # ── the two ways the chooser used to be fooled ──────────────────────

    def test_an_answer_that_is_neither_yes_nor_no_keeps_the_old_path(self):
        """The first version asked `bool(answer)`, so ANY truthy object sent
        the close down the position-id path. A mock, a Sentinel, a stray
        dict — none of them answered the question, and the reading of no
        answer is the one the exception branch already made."""
        client = mock.Mock(spec=["market_order", "close_position",
                                 "close_needs_position_id"])
        client.close_needs_position_id.return_value = object()
        client.market_order.return_value = {"status": "FILLED"}
        with self.assertLogs("bot_program.asset_engine.base",
                             level="WARNING") as cm:
            self._close(self._trade(protective_trade_id="P9"), client)
        self.assertTrue(any("neither" in m for m in cm.output))
        client.market_order.assert_called_once()
        client.close_position.assert_not_called()

    def test_a_position_id_is_never_invented_out_of_a_non_string(self):
        """metadata is a JSONField: it can hold a dict, a list, anything.
        str() of all of them is a long non-empty string that reads like a
        venue id, and closing BY an invented id closes some other position
        or nothing while the row still books CLOSED."""
        client = mock.Mock(spec=["market_order", "close_position",
                                 "close_needs_position_id"])
        client.close_needs_position_id.return_value = True
        client.market_order.return_value = {"status": "FILLED"}
        trade = self._trade(protective_trade_id={"id": 7})
        with self.assertLogs("bot_program.asset_engine.base",
                             level="ERROR") as cm:
            self._close(trade, client)
        self.assertTrue(any("BOTH lots open" in m for m in cm.output))
        client.close_position.assert_not_called()
        client.market_order.assert_called_once()

    def test_a_numeric_position_id_is_still_a_position_id(self):
        """Saxo PositionIds are decimal, and a JSON round-trip can leave one
        as an int. Rejecting it would flatten nothing on the venue that
        needs it most."""
        client = mock.Mock(spec=["market_order", "close_position",
                                 "close_needs_position_id"])
        client.close_needs_position_id.return_value = True
        client.close_position.return_value = {"status": "FILLED"}
        self._close(self._trade(broker_position_id=4001234567), client)
        client.close_position.assert_called_once_with("4001234567", "AAPL",
                                                      10.0)
        client.market_order.assert_not_called()

    def test_an_adapter_that_needs_an_id_and_cannot_close_by_one_says_so(self):
        """It would otherwise fall through to the opposite order in
        silence — the same double-lot outcome as a missing id, so it earns
        the same ERROR."""
        client = mock.Mock(spec=["market_order", "close_needs_position_id"])
        client.close_needs_position_id.return_value = True
        client.market_order.return_value = {"status": "FILLED"}
        with self.assertLogs("bot_program.asset_engine.base",
                             level="ERROR") as cm:
            self._close(self._trade(protective_trade_id="P9"), client)
        self.assertTrue(any("no close_position" in m for m in cm.output))
        client.market_order.assert_called_once()
