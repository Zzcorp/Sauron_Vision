"""What happens the moment real eToro and Saxo keys go in — held here.

The platform was traced step by step from "the operator pastes the keys" to
"the fleet trades", by readers whose only job was to name what would fail.
These are the failures that survived refutation and were fixed, each held at
the seam it broke, so the next venue cannot quietly reintroduce it.

THE OPERATOR'S OWN SEQUENCE

  connect Saxo, sign in, tick the routing boxes, run saxo_smoke. Step three
  used to destroy step two: save_saxo_credentials is the ONLY writer of the
  primary-for flags anywhere in the platform, the form posts every field at
  once, and the view closed the session unconditionally. The flags saved, so
  broker_backed promoted the row to the book (keyed AND carries, never a
  session), the keeper could not recover it (it skips rows with no refresh
  token), and saxo_smoke stopped at "no live Saxo session". The sequence, run
  exactly as written, ended on a dead platform.

WHAT ELSE THE TRACE FOUND, AND WHAT EACH TEST BELOW PINS

  * a reading from the OTHER world surviving an environment flip. Saxo's
    save dropped the cells; eToro's did not, and its demo box ships checked.
  * a REFUSED probe still becoming the book, silently.
  * the Saxo row still built has_adapter=False three days after the adapter
    shipped, so a perfect sign-in painted the row as unusable.
  * the IBKR walk retuning every follower pool from IBKR's equity while the
    entries were gated on Saxo's reading — the guard existed in the two
    newer walks and said why, and the oldest one never got it.
  * EMERGENCY FLATTEN discarding cancel_order's False, flattening over a
    stop that was never cancelled.
  * a rehearsal fill indistinguishable from a real one.
  * the unknown-position sweep, written because a funded account with no bot
    got zero sweeps, going blind on IBKR the moment Saxo became the book.
  * preflight_live answering the arming question about IBKR only.
"""
from datetime import timedelta
from decimal import Decimal
from io import StringIO
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from bot_program.models import (AssetBotConfig, EtoroAccount, IBKRAccount,
                                SaxoAccount)
from tests.test_saxo_wiring import _fresh, etoro, ibkr, saxo

APP, SECRET = "app-key", "app-secret"
URI = "https://host/brokers/saxo/callback/"
BOXES = {"stock": "primary_stocks", "forex": "primary_forex",
         "commodity": "primary_commodity", "crypto": "primary_crypto"}


def _post_saxo(client, username, *, key=APP, secret=SECRET, uri=URI,
               sim=True, flags=("stock",)):
    data = {"target_username": username, "saxo_app_key": key,
            "saxo_app_secret": secret, "saxo_redirect_uri": uri}
    if sim:
        data["sim"] = "on"
    for f in flags:
        data[BOXES[f]] = "on"
    return client.post(reverse("hq_save_saxo"), data)


def _cfg(user, *, asset_class="stock", mode="live", enabled=True,
         capital="1000", currency="EUR", symbols=("AAPL",)):
    return AssetBotConfig.objects.create(
        user=user, name=f"{asset_class}_{mode}", asset_class=asset_class,
        mode=mode, enabled=enabled, symbols=list(symbols),
        capital=Decimal(capital), base_currency=currency)


# ── the sequence ────────────────────────────────────────────────────────

class TheRoutingSaveKeepsTheSessionTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("me_u", password="x")
        self.admin = User.objects.create_superuser("me_admin", "a@x", "x")
        self.client.force_login(self.admin)
        # The row exactly as Connect Saxo leaves it: keyed, signed in, and
        # carrying nothing, because every box defaults off.
        acct = saxo(self.user, flags=(), sim=True)
        acct.set_credentials(APP, SECRET)
        acct.redirect_uri = URI
        acct.save()
        self.acct = acct

    def _row(self):
        return SaxoAccount.objects.get(user=self.user)

    def test_ticking_a_routing_box_leaves_the_session_alone(self):
        """The whole finding, in one assertion: the flags are what changed,
        so the session is not what pays."""
        _post_saxo(self.client, "me_u", flags=("stock", "forex"))
        acct = self._row()
        self.assertTrue(acct.is_primary_for("stock"))
        self.assertTrue(acct.is_primary_for("forex"))
        self.assertTrue(acct.has_session)
        self.assertTrue(acct.session_alive())

    def test_a_different_secret_still_closes_the_session(self):
        """A session belongs to ONE application: the original rule stands
        wherever the application actually changed."""
        _post_saxo(self.client, "me_u", secret="a-different-secret")
        self.assertFalse(self._row().has_session)

    def test_a_different_redirect_uri_still_closes_the_session(self):
        _post_saxo(self.client, "me_u",
                   uri="https://other.example.net/brokers/saxo/callback/")
        self.assertFalse(self._row().has_session)

    def test_flipping_the_environment_closes_it_and_drops_the_readings(self):
        acct = self.acct
        acct.last_equity = Decimal("1000")
        acct.last_equity_currency = "USD"
        acct.last_equity_at = timezone.now()
        acct.save()
        _post_saxo(self.client, "me_u", sim=False)
        acct = self._row()
        self.assertFalse(acct.sim)
        self.assertFalse(acct.has_session)
        self.assertIsNone(acct.last_equity)
        self.assertIsNone(acct.last_equity_at)

    def test_the_message_says_which_of_the_two_happened(self):
        """An operator who reads "any session that was open is closed" after a
        save that closed nothing learns to disbelieve the message."""
        r = self.client.post(
            reverse("hq_save_saxo"),
            {"target_username": "me_u", "saxo_app_key": APP,
             "saxo_app_secret": SECRET, "saxo_redirect_uri": URI,
             "sim": "on", "primary_stocks": "on"}, follow=True)
        self.assertIn("left alone", r.content.decode())

    def test_a_real_application_change_still_says_the_session_is_closed(self):
        r = self.client.post(
            reverse("hq_save_saxo"),
            {"target_username": "me_u", "saxo_app_key": "another-app-key",
             "saxo_app_secret": SECRET, "saxo_redirect_uri": URI,
             "sim": "on", "primary_stocks": "on"}, follow=True)
        self.assertIn("is closed", r.content.decode())


class TheEtoroSaveTellsTheTruthTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("et_u", password="x")
        self.admin = User.objects.create_superuser("et_admin", "a@x", "x")
        self.client.force_login(self.admin)

    def _post(self, **extra):
        data = {"target_username": "et_u", "etoro_api_key": "k2",
                "etoro_user_key": "u2"}
        data.update(extra)
        return self.client.post(reverse("hq_save_etoro"), data, follow=True)

    def test_flipping_demo_to_live_drops_the_virtual_reading(self):
        """A virtual balance on a row now flagged LIVE, minutes old, is fresh
        enough for every governor to size a real order against."""
        acct = etoro(self.user, flags=("stock",))
        acct.demo = True
        acct.last_equity = Decimal("100000")
        acct.last_equity_currency = "USD"
        acct.last_equity_at = timezone.now()
        acct.broker_positions = [{"symbol": "AAPL"}]
        acct.broker_positions_at = timezone.now()
        acct.save()
        with mock.patch("dashboard.views_brokers.etoro_probe",
                        return_value=("ok", "")):
            self._post(primary_stocks="on")          # demo absent = live
        acct = EtoroAccount.objects.get(user=self.user)
        self.assertFalse(acct.demo)
        self.assertIsNone(acct.last_equity)
        self.assertIsNone(acct.last_equity_at)
        self.assertEqual(acct.last_equity_currency, "")
        self.assertEqual(acct.broker_positions, [])
        self.assertIsNone(acct.broker_positions_at)

    def test_a_save_that_does_not_change_the_environment_keeps_them(self):
        acct = etoro(self.user, flags=("stock",))
        acct.demo = True
        acct.last_equity = Decimal("4242")
        acct.last_equity_at = timezone.now()
        acct.save()
        with mock.patch("dashboard.views_brokers.etoro_probe",
                        return_value=("ok", "")):
            self._post(primary_stocks="on", demo="on")
        acct = EtoroAccount.objects.get(user=self.user)
        self.assertEqual(acct.last_equity, Decimal("4242"))

    def test_a_refused_probe_that_carries_a_class_says_it_is_the_book(self):
        """broker_backed asks "keyed AND carries", never "connected" — so a
        row eToro has just refused becomes the account every pool is measured
        against. "Saved but REFUSED" never said that."""
        with mock.patch("dashboard.views_brokers.etoro_probe",
                        return_value=("refused", "401 unauthorized")):
            r = self._post(primary_stocks="on")
        self.assertIn("now the book", r.content.decode())

    def test_a_refused_probe_that_carries_nothing_says_no_such_thing(self):
        with mock.patch("dashboard.views_brokers.etoro_probe",
                        return_value=("refused", "401 unauthorized")):
            r = self._post()
        self.assertNotIn("now the book", r.content.decode())


class TheSaxoRowHasAnAdapterTests(TestCase):

    def test_the_page_stops_saying_saxo_cannot_be_asked_anything(self):
        """has_adapter=False survived three days past the adapter, on the
        page the OAuth callback returns to."""
        from dashboard.views_brokers import _rows
        user = User.objects.create_user("ad_u", password="x")
        saxo(user, flags=("stock",))
        row = next(r for r in _rows(_fresh(user)) if r["key"] == "saxo")
        self.assertTrue(row["has_adapter"])
        self.assertTrue(row["capabilities"])


# ── the money paths ─────────────────────────────────────────────────────

class EveryWalkRetunesOnlyItsOwnBookTests(SimpleTestCase):
    """Read off the source: the IBKR walk cannot be driven without the IBKR
    library, and the invariant is precisely that all three walks agree."""

    def test_all_three_broker_walks_carry_the_is_the_book_guard(self):
        src = (Path(settings.BASE_DIR) / "bot_program" / "tasks.py").read_text(
            encoding="utf-8")
        for name in ("sync_broker_account", "sync_saxo_accounts",
                     "sync_etoro_accounts"):
            body = src.split("def %s(" % name)[1].split("\ndef ")[0]
            self.assertIn("_follow_the_account", body, name)
            self.assertIn("book.pk == acct.pk", body,
                          "%s retunes the pools without asking whether this "
                          "row is the book" % name)


class TheKillSwitchReadsTheCancelTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("ks_u", password="x")
        self.cfg = _cfg(self.user)

    def _trade(self):
        from bot_program.asset_models import AssetBotTrade
        return AssetBotTrade.objects.create(
            config=self.cfg, asset_class="stock", symbol="AAPL", side="BUY",
            qty=Decimal("10"), entry_price=Decimal("200"), status="OPEN",
            paper=False, metadata={"protective_order_ids": ["S1"],
                                   "initial_stop_loss": 190.0})

    def _client(self, *, cancel):
        c = mock.MagicMock(spec=["cancel_order", "market_order", "ticker",
                                 "order_status"])
        c.cancel_order.return_value = cancel
        c.ticker.return_value = {"lastPrice": "205"}
        c.market_order.return_value = {"status": "FILLED", "avgPrice": "205",
                                       "executedQty": "10"}
        return c

    def _flatten(self, client):
        from bot_program.engine.kill_switch import _close_asset_trade
        trade = self._trade()
        with mock.patch("bot_program.engine.broker_router.client_for_symbol",
                        return_value=client):
            _close_asset_trade(trade, timezone.now())
        trade.refresh_from_db()
        return trade

    def test_a_refused_cancel_is_named_on_the_row_and_in_the_log(self):
        """False is a refusal. SaxoTrader returns a bool there precisely
        because a dict is always truthy, and the switch used to throw the
        answer away — booking the row CLOSED over a full-size GTC stop that
        fires against a flat book and OPENS a reverse position."""
        client = self._client(cancel=False)
        with self.assertLogs("bot_program.engine.kill_switch",
                             level="ERROR") as cm:
            trade = self._flatten(client)
        self.assertTrue(any("still resting" in m for m in cm.output))
        self.assertEqual(trade.metadata.get("kill_left_resting_orders"), ["S1"])
        # The flatten still happens: a live position during a kill is the
        # larger risk of the two.
        client.market_order.assert_called_once()

    def test_a_confirmed_cancel_leaves_no_flag(self):
        trade = self._flatten(self._client(cancel=True))
        self.assertNotIn("kill_left_resting_orders", trade.metadata)

    def test_an_adapter_that_says_nothing_is_still_trusted(self):
        """None is not a refusal — it is the old contract, and IBKR's
        cancel_order has always returned it."""
        trade = self._flatten(self._client(cancel=None))
        self.assertNotIn("kill_left_resting_orders", trade.metadata)


class TheEntryRecordsWhichWorldItTradedTests(SimpleTestCase):

    def test_every_adapter_env_word_is_in_the_map(self):
        """A new adapter whose env word is missing records NO world rather
        than a wrong one — but it should be added, so this names the three
        that exist."""
        from bot_program.asset_engine.base import AssetBot
        for word in ("sim", "demo", "live", "paper", "practice", "testnet"):
            self.assertIn(word, AssetBot.VENUE_WORLDS)
        self.assertEqual(AssetBot.VENUE_WORLDS["sim"], "paper")
        self.assertEqual(AssetBot.VENUE_WORLDS["demo"], "paper")
        self.assertEqual(AssetBot.VENUE_WORLDS["live"], "live")

    def test_the_two_two_world_adapters_report_a_word_the_map_knows(self):
        from bot_program.asset_engine.base import AssetBot
        from bot_program.engine.etoro_client import EtoroTrader
        from bot_program.engine.saxo_client import SaxoTrader
        for client in (SaxoTrader(env="sim", token="t", session=object()),
                       SaxoTrader(env="live", token="t", session=object()),
                       EtoroTrader("k", "u", env="demo"),
                       EtoroTrader("k", "u", env="live")):
            self.assertIn(client.env, AssetBot.VENUE_WORLDS,
                          "%s reports env=%r, which the entry cannot file"
                          % (type(client).__name__, client.env))

    def test_the_entry_stamps_the_world_beside_the_broker(self):
        import ast
        import inspect
        import textwrap

        from bot_program.asset_engine.base import AssetBot
        src = textwrap.dedent(inspect.getsource(AssetBot.execute_entry))
        keys = {n.slice.value for n in ast.walk(ast.parse(src))
                if isinstance(n, ast.Subscript)
                and isinstance(getattr(n, "slice", None), ast.Constant)
                and isinstance(n.value, ast.Name)
                and n.value.id == "entry_meta"
                and isinstance(n.slice.value, str)}
        self.assertIn("broker", keys)
        self.assertIn("broker_env", keys)


class TheSweepWalksEveryKeyedRowTests(TestCase):
    """The half written because a funded account with no bot got ZERO
    sweeps. The book is where the money is measured; it is not where the
    positions are."""

    def setUp(self):
        self.user = User.objects.create_user("sw_u", password="x")

    def test_ibkr_is_still_swept_when_saxo_is_the_book(self):
        from bot_program import reconcile_asset
        saxo(self.user, flags=("stock", "forex"))
        ibkr(self.user, flags=())
        asked = []

        def _open_symbols(client, asset_class="stock"):
            asked.append(type(client).__name__)
            return {"symbols": set()}

        with mock.patch.object(reconcile_asset, "_broker_open_symbols",
                               side_effect=_open_symbols), \
                mock.patch("bot_program.engine.saxo_client.SaxoTrader") as S, \
                mock.patch("bot_program.engine.ibkr_client.is_ibkr_available",
                           return_value=True), \
                mock.patch("bot_program.engine.ibkr_sessions.acquire_trader") \
                as A:
            S.return_value = mock.MagicMock(name="SaxoTrader")
            A.return_value = mock.MagicMock(name="IBKRTrader")
            reconcile_asset.reconcile_unknown_positions(_fresh(self.user))
        self.assertEqual(len(asked), 2,
                         "one client per keyed row, not one for the book")

    def test_an_unkeyed_row_is_not_walked(self):
        from bot_program import reconcile_asset
        saxo(self.user, flags=("stock",))
        IBKRAccount.objects.create(user=self.user, port=4004)   # no account id
        asked = []
        with mock.patch.object(reconcile_asset, "_broker_open_symbols",
                               side_effect=lambda c, asset_class="stock":
                               asked.append(1) or {"symbols": set()}), \
                mock.patch("bot_program.engine.saxo_client.SaxoTrader"):
            reconcile_asset.reconcile_unknown_positions(_fresh(self.user))
        self.assertEqual(len(asked), 1)


# ── the arming gate ─────────────────────────────────────────────────────

def _preflight(user=""):
    out = StringIO()
    kw = {"user": user} if user else {}
    call_command("preflight_live", stdout=out, **kw)
    return out.getvalue()


class ThePreflightKnowsTheVenueTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("pv_u", password="x")

    def test_a_box_with_no_ibkr_row_is_not_a_blocker(self):
        """It reported "no IBKRAccount row exists" on a box keyed to Saxo and
        eToro — refusing to arm for the absence of a broker nobody intends to
        use, while checking nothing about the one that would trade."""
        saxo(self.user, flags=("stock",))
        body = _preflight("pv_u")
        self.assertNotIn("no IBKRAccount", body)
        self.assertIn("THE BROKERS", body)

    def test_it_names_the_book_and_its_world(self):
        saxo(self.user, flags=("stock",), sim=True)
        body = _preflight("pv_u")
        self.assertIn("saxo", body)
        self.assertIn("paper", body)

    def test_a_live_config_with_no_primary_venue_blocks(self):
        """broker_router always returns SOME client and falls back to the
        PaperTrader, so the pool books simulated fills while calling itself
        live."""
        saxo(self.user, flags=())          # keyed, carries nothing
        _cfg(self.user, asset_class="stock")
        body = _preflight("pv_u")
        self.assertIn("PaperTrader", body)
        self.assertIn("BLOCKERS", body)

    def test_a_live_config_on_a_sim_venue_blocks(self):
        saxo(self.user, flags=("stock",), sim=True)
        _cfg(self.user, asset_class="stock")
        body = _preflight("pv_u")
        self.assertIn("DEMO account", body)
        self.assertIn("BLOCKERS", body)

    def test_a_live_config_on_a_live_venue_does_not_block_for_the_venue(self):
        saxo(self.user, flags=("stock",), sim=False)
        _cfg(self.user, asset_class="stock")
        body = _preflight("pv_u")
        self.assertNotIn("DEMO account", body)

    def test_a_dead_saxo_session_blocks_a_live_config(self):
        saxo(self.user, flags=("stock",), sim=False, session=False)
        _cfg(self.user, asset_class="stock")
        body = _preflight("pv_u")
        self.assertIn("session is not alive", body)

    def test_the_ibkr_margin_floor_is_not_printed_for_a_saxo_book(self):
        """It is IBKR's rule (Error 201), not a property of money."""
        acct = saxo(self.user, flags=("stock",), sim=False)
        acct.last_equity = Decimal("500")
        acct.last_equity_currency = "USD"
        acct.last_equity_at = timezone.now()
        acct.save()
        self.assertNotIn("IBKR floor", _preflight("pv_u"))


class TheVenueResolverCannotDriftTests(TestCase):
    """The preflight's resolver against the router's own predicates, class by
    class and flag by flag — a second copy of "which broker carries this"
    that drifted would make the preflight confidently name the wrong one."""

    def test_it_agrees_with_the_router_for_every_class(self):
        from bot_program.engine import broker_router as router
        from bot_program.management.commands.preflight_live import _venue_for

        user = User.objects.create_user("vr_u", password="x")
        saxo(user, flags=("stock",))
        etoro(user, flags=("stock", "forex"))
        ibkr(user, flags=("commodity",))
        u = _fresh(user)
        for cls in ("stock", "forex", "commodity", "crypto", "options"):
            row, kind = _venue_for(u, cls)
            if router._saxo_overrides(u, cls):
                self.assertEqual(kind, "saxo", cls)
            elif router._etoro_overrides(u, cls):
                self.assertEqual(kind, "etoro", cls)
            elif cls in ("options", "cfd") or router._ibkr_overrides(u, cls):
                self.assertEqual(kind, "ibkr", cls)
            else:
                self.assertIsNone(row, cls)

    def test_nothing_keyed_and_flagged_means_nothing_carries_it(self):
        from bot_program.management.commands.preflight_live import _venue_for
        user = User.objects.create_user("vr_none", password="x")
        saxo(user, flags=())
        row, kind = _venue_for(_fresh(user), "stock")
        self.assertIsNone(row)
        self.assertEqual(kind, "")


class TheMoneyPageSaysWhichWorldTests(TestCase):
    """/treasury/ painted every row in the simulator's colour, including a
    live one, because `env_label` is uppercase and venue-shaped and the badge
    compared it to 'live'. The comparison is now against a word the platform
    controls; the label stays the one a human reads."""

    def setUp(self):
        self.user = User.objects.create_user("tw_u", password="x")

    def _row(self):
        from bot_program.broker_vision import brokers
        return next(r for r in brokers(_fresh(self.user)) if r["kind"] == "saxo")

    def test_a_live_row_says_live(self):
        saxo(self.user, flags=("stock",), sim=False)
        row = self._row()
        self.assertEqual(row["world"], "live")
        self.assertIn("LIVE", row["env"])

    def test_a_sim_row_says_paper(self):
        saxo(self.user, flags=("stock",), sim=True)
        row = self._row()
        self.assertEqual(row["world"], "paper")

    def test_the_page_compares_the_word_and_not_the_label(self):
        html = (Path(settings.BASE_DIR) / "templates" / "dashboard"
                / "treasury.html").read_text(encoding="utf-8")
        self.assertNotIn("r.env == 'live'", html)
        self.assertNotIn("v.book.env == 'live'", html)
        self.assertIn("r.world == 'live'", html)

    def test_ages_read_like_a_clock_on_the_page_too(self):
        from bot_program.broker_vision import _age_text
        self.assertEqual(_age_text(None), "—")
        self.assertEqual(_age_text(45), "45s")
        self.assertEqual(_age_text(600), "10m")
        self.assertEqual(_age_text(28800), "8.0h")
        html = (Path(settings.BASE_DIR) / "templates" / "dashboard"
                / "treasury.html").read_text(encoding="utf-8")
        self.assertNotIn("age_seconds }} s", html)
