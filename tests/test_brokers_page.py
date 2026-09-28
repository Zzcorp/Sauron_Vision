"""Les courtiers: somewhere to put the keys, before the adapters (2026-09-17).

The operator is obtaining eToro and Saxo credentials today. Until this page
there was nowhere to put them: the four existing brokers are configured on
the admin HQ page (three of them) and Django admin (the fourth), and nothing
anywhere lists what each one can be asked to hold.

WHAT THESE TESTS HOLD

  * A raw secret never reaches the database column, never reaches the
    rendered page, and an empty row answers (None, None) — the same contract
    the four existing rows keep.
  * "recorded" and "connected" are different words for different states,
    and a broker with no adapter is never shown as connected however good
    its keys are.
  * The eToro probe reports THREE outcomes. The probe URL was taken from
    public documentation; if it 404s, that is the probe's fault and the
    operator must not read "your keys are refused".
  * Saving is superuser-and-POST, reusing `_admin_only` rather than a copy.
  * The capabilities column is the table the conformance test enforces, not
    a second list typed into a template.
  * The Demo untick is the switch to real money (measured 2026-09-23: one
    pair opens both worlds), and the save that unticks it is refused without
    the trading PIN, with a class ticked on the same save, or while a live
    config is enabled — nothing written on a refusal.
"""
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from bot_program.models import EtoroAccount, SaxoAccount

RAW_KEY = "etoro-key-9f3a7c2d"
RAW_USER = "etoro-user-b81e44"
RAW_APP = "saxo-app-0c1d2e"
RAW_SECRET = "saxo-secret-3f4a5b"


class TheRowsKeepTheSecretTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("row_u", password="x")

    def test_etoro_round_trips_and_stores_nothing_readable(self):
        acct = EtoroAccount.objects.create(user=self.user)
        acct.set_credentials(RAW_KEY, RAW_USER)
        acct.save()
        stored = EtoroAccount.objects.get(pk=acct.pk)
        self.assertEqual(stored.get_credentials(), (RAW_KEY, RAW_USER))
        self.assertNotIn(RAW_KEY, stored.api_key_enc)
        self.assertNotIn(RAW_USER, stored.user_key_enc)

    def test_saxo_round_trips_and_stores_nothing_readable(self):
        acct = SaxoAccount.objects.create(user=self.user)
        acct.set_credentials(RAW_APP, RAW_SECRET)
        acct.save()
        stored = SaxoAccount.objects.get(pk=acct.pk)
        self.assertEqual(stored.get_credentials(), (RAW_APP, RAW_SECRET))
        self.assertNotIn(RAW_APP, stored.app_key_enc)
        self.assertNotIn(RAW_SECRET, stored.app_secret_enc)

    def test_an_empty_row_answers_none_pair(self):
        """The contract the other four rows keep: the router reads
        (None, None) and falls back to paper, never a half-key."""
        self.assertEqual(EtoroAccount(user=self.user).get_credentials(),
                         (None, None))
        self.assertEqual(SaxoAccount(user=self.user).get_credentials(),
                         (None, None))

    def test_registered_is_not_a_session(self):
        """An app key identifies Sauron to Saxo. Only a refresh token means
        the OAuth sign-in happened and the server can renew alone."""
        acct = SaxoAccount.objects.create(user=self.user)
        acct.set_credentials(RAW_APP, RAW_SECRET)
        self.assertFalse(acct.has_session)
        from django.utils import timezone
        acct.set_tokens("acc", "ref", timezone.now())
        self.assertTrue(acct.has_session)
        self.assertEqual(acct.get_refresh_token(), "ref")
        self.assertNotIn("ref", acct.refresh_token_enc)


class ThePageTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("page_u", password="x")
        self.admin = User.objects.create_superuser("page_admin", "a@x", "x")

    def test_it_needs_a_login(self):
        r = self.client.get(reverse("brokers_page"))
        self.assertNotEqual(r.status_code, 200)

    def test_it_lists_every_broker_with_a_three_state_status(self):
        self.client.force_login(self.user)
        body = self.client.get(reverse("brokers_page")).content.decode()
        for name in ("Interactive Brokers", "Alpaca", "OANDA", "Binance",
                     "eToro", "Saxo Bank"):
            self.assertIn(name, body)
        self.assertIn("no row", body)

    def test_a_broker_without_an_adapter_is_never_connected(self):
        """However good the keys, nothing can be asked of a broker the engine
        has no client for. Showing it green would send an operator to arm a
        live config against it.

        Tested on the rule rather than through a row, because since
        2026-09-19 every broker on the page HAS an adapter — eToro grew one
        on 09-17 and Saxo on 09-19. The rule is for the next one keyed
        before its client exists, and the page's own green is pinned below
        by test_a_keyed_saxo_row_with_a_session_is_green."""
        from dashboard.views_brokers import _status

        acct = SaxoAccount.objects.create(user=self.user, connected=True)
        acct.set_credentials(RAW_APP, RAW_SECRET)
        acct.save()
        self.assertEqual(_status(acct, has_adapter=False),
                         "session open — adapter pending")
        acct.connected = False
        self.assertEqual(_status(acct, has_adapter=False),
                         "recorded — adapter pending")
        self.assertEqual(_status(None, has_adapter=True), "no row")

    def test_a_keyed_saxo_row_with_a_session_is_green(self):
        """The other half of the same rule: a broker that CAN be asked, and
        has a session, is green. It painted "adapter pending" for three days
        after the adapter shipped."""
        acct = SaxoAccount.objects.create(user=self.user, connected=True)
        acct.set_credentials(RAW_APP, RAW_SECRET)
        acct.save()
        self.client.force_login(self.user)
        body = self.client.get(reverse("brokers_page")).content.decode()
        self.assertNotIn("adapter pending", body)

    def test_the_capabilities_column_is_the_enforced_table(self):
        from bot_program.engine.capabilities import declared
        from bot_program.models import IBKRAccount
        acct = IBKRAccount.objects.create(user=self.user, port=4004)
        acct.set_credentials("DU1")
        acct.save()
        self.client.force_login(self.user)
        body = self.client.get(reverse("brokers_page")).content.decode()
        for cap in declared("ibkr"):
            self.assertIn(cap, body)

    def test_only_a_superuser_sees_the_forms(self):
        self.client.force_login(self.user)
        self.assertNotIn(b'name="etoro_api_key"',
                         self.client.get(reverse("brokers_page")).content)
        self.client.force_login(self.admin)
        body = self.client.get(reverse("brokers_page")).content
        self.assertIn(b'name="etoro_api_key"', body)
        self.assertIn(b'name="saxo_app_key"', body)

    def test_the_time_stop_caveat_is_on_the_page(self):
        """No broker holds it. Written where the brokers are listed, so it
        is read at the moment someone is deciding what to delegate."""
        self.client.force_login(self.user)
        body = self.client.get(reverse("brokers_page")).content.decode()
        self.assertIn("time stop", body)


class SavingEtoroTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("et_u", password="x")
        self.admin = User.objects.create_superuser("et_admin", "a@x", "x")
        self.post = {"target_username": "et_u", "etoro_api_key": RAW_KEY,
                     "etoro_user_key": RAW_USER, "demo": "on"}

    def _save(self, verdict=("ok", "200")):
        self.client.force_login(self.admin)
        with mock.patch("dashboard.views_brokers.etoro_probe",
                        return_value=verdict) as probe:
            r = self.client.post(reverse("hq_save_etoro"), self.post)
        return r, probe

    def test_a_non_superuser_is_refused(self):
        self.client.force_login(self.user)
        r = self.client.post(reverse("hq_save_etoro"), self.post)
        self.assertEqual(r.status_code, 403)
        self.assertFalse(EtoroAccount.objects.exists())

    def test_get_is_not_a_save(self):
        self.client.force_login(self.admin)
        r = self.client.get(reverse("hq_save_etoro"))
        self.assertEqual(r.status_code, 405)

    def test_verified_keys_are_stored_encrypted_and_connected(self):
        r, probe = self._save(("ok", "200"))
        self.assertEqual(r.status_code, 302)
        probe.assert_called_once_with(RAW_KEY, RAW_USER, demo=True)
        acct = EtoroAccount.objects.get(user=self.user)
        self.assertTrue(acct.connected)
        self.assertTrue(acct.demo)
        self.assertIsNotNone(acct.last_sync)
        self.assertEqual(acct.get_credentials(), (RAW_KEY, RAW_USER))
        self.assertNotIn(RAW_KEY, acct.api_key_enc)

    def test_refused_keys_are_kept_but_not_connected(self):
        self._save(("refused", "401"))
        acct = EtoroAccount.objects.get(user=self.user)
        self.assertFalse(acct.connected)
        self.assertIsNone(acct.last_sync)

    def test_a_probe_that_cannot_decide_does_not_blame_the_keys(self):
        """A 404 on the probe path is this codebase's error. The message
        must say 'could not verify', never 'refused'."""
        r, _ = self._save(("unknown", "404"))
        acct = EtoroAccount.objects.get(user=self.user)
        self.assertFalse(acct.connected)
        page = self.client.get(reverse("brokers_page")).content.decode()
        self.assertIn("could not be verified", page)
        self.assertNotIn("REFUSED", page)

    def test_the_secret_never_reaches_the_rendered_page(self):
        self._save(("ok", "200"))
        page = self.client.get(reverse("brokers_page")).content.decode()
        self.assertNotIn(RAW_KEY, page)
        self.assertNotIn(RAW_USER, page)

    def test_the_probe_maps_status_codes_to_three_answers(self):
        from dashboard.views_brokers import etoro_probe

        def fake(status):
            resp = mock.Mock()
            resp.status_code = status
            return mock.patch("requests.get", return_value=resp)

        with fake(200):
            self.assertEqual(etoro_probe("k", "u")[0], "ok")
        with fake(401):
            self.assertEqual(etoro_probe("k", "u")[0], "refused")
        with fake(404):
            self.assertEqual(etoro_probe("k", "u")[0], "unknown")
        with mock.patch("requests.get", side_effect=OSError("down")):
            self.assertEqual(etoro_probe("k", "u")[0], "unknown")


class TheDemoUntickIsGuardedTests(TestCase):
    """The untick is the switch to real money. Measured 2026-09-23: the pair
    eToro's portal calls "virtual", saved with Demo ticked, answered 200 on
    the demo AND the live aggregate-portfolio — one pair opens both worlds,
    and the Demo tick alone picks the URL segment. So a demo -> live flip is
    refused, nothing written, without the acting superuser's trading PIN,
    with a class box ticked on the same save, or while any live config of
    the target user is enabled. The way back (live -> demo) has its own,
    different guard since 2026-09-28: TheDemoTickIsGuardedTests."""

    PIN = "4321"

    def setUp(self):
        self.user = User.objects.create_user("gd_u", password="x")
        self.admin = User.objects.create_superuser("gd_admin", "a@x", "x")
        acct = EtoroAccount.objects.create(user=self.user, demo=True,
                                           connected=True,
                                           is_primary_for_forex=True)
        acct.set_credentials(RAW_KEY, RAW_USER)
        acct.save()
        self.client.force_login(self.admin)

    def _give_the_admin_a_pin(self):
        from portfolio.trader_profile import get_or_create_profile
        prof = get_or_create_profile(self.admin)
        prof.set_pin(self.PIN)
        prof.save()

    def _cfg(self, *, enabled, mode="live", name="megacaps"):
        from bot_program.models import AssetBotConfig
        return AssetBotConfig.objects.create(
            user=self.user, asset_class="stock", name=name, mode=mode,
            enabled=enabled, symbols=["AAPL"])

    def _post(self, **extra):
        """A save of NEW keys, Demo absent (= live) unless given; the probe
        is patched so a refusal can be told from a send."""
        data = {"target_username": "gd_u", "etoro_api_key": "k2",
                "etoro_user_key": "u2"}
        data.update(extra)
        with mock.patch("dashboard.views_brokers.etoro_probe",
                        return_value=("ok", "200")) as probe:
            r = self.client.post(reverse("hq_save_etoro"), data, follow=True)
        return r.content.decode(), probe

    def _row(self):
        return EtoroAccount.objects.get(user=self.user)

    def assertNothingWasSaved(self, probe):
        """Still demo, the flags not read, the keys not re-encrypted, and
        nothing sent to eToro."""
        acct = self._row()
        self.assertTrue(acct.demo)
        self.assertTrue(acct.is_primary_for_forex)
        self.assertEqual(acct.get_credentials(), (RAW_KEY, RAW_USER))
        probe.assert_not_called()

    def test_the_flip_is_refused_without_the_pin(self):
        body, probe = self._post()
        self.assertNothingWasSaved(probe)
        self.assertIn("REFUSED to untick Demo for gd_u", body)
        self.assertIn("nothing was saved", body)
        self.assertIn("measured 2026-09-23: the same eToro pair answered 200 "
                      "on the demo AND the live aggregate-portfolio", body)
        self.assertIn("the trading PIN was not supplied or is wrong", body)

    def test_a_wrong_pin_is_no_pin(self):
        self._give_the_admin_a_pin()
        body, probe = self._post(pin="0000")
        self.assertNothingWasSaved(probe)
        self.assertIn("the trading PIN was not supplied or is wrong", body)

    def test_the_flip_is_refused_while_a_live_config_is_enabled(self):
        self._give_the_admin_a_pin()
        cfg = self._cfg(enabled=True)
        body, probe = self._post(pin=self.PIN)
        self.assertNothingWasSaved(probe)
        self.assertIn(f"live config(s) ENABLED for gd_u: [{cfg.id}] megacaps",
                      body)
        self.assertIn("bot off &lt;id&gt;", body)     # the page escapes it
        # the PIN was right: that reason must not be on the list
        self.assertNotIn("trading PIN was not supplied", body)

    def test_the_flip_is_refused_with_a_class_ticked_on_the_same_save(self):
        self._give_the_admin_a_pin()
        body, probe = self._post(pin=self.PIN, primary_stocks="on")
        self.assertNothingWasSaved(probe)
        self.assertIn("class box(es) ticked on the same save (stocks)", body)
        self.assertIn("second save", body)

    def test_every_reason_that_applies_is_printed_at_once(self):
        """One flash, the whole list — an operator who fixes one reason and
        meets the next on the following click learns to distrust the page."""
        self._cfg(enabled=True)
        body, probe = self._post(primary_stocks="on", primary_crypto="on")
        self.assertNothingWasSaved(probe)
        self.assertIn("(1) live config(s) ENABLED", body)
        self.assertIn("(2) class box(es) ticked on the same save "
                      "(stocks, crypto)", body)
        self.assertIn("(3) the trading PIN was not supplied", body)

    def test_the_flip_is_allowed_with_the_pin_and_nothing_enabled(self):
        """A DISABLED live config and an ENABLED paper config count for
        nothing: neither can place a real order."""
        self._give_the_admin_a_pin()
        self._cfg(enabled=False, name="disabled_live")
        self._cfg(enabled=True, mode="paper", name="enabled_paper")
        body, probe = self._post(pin=self.PIN)
        acct = self._row()
        self.assertFalse(acct.demo)
        self.assertFalse(acct.is_primary_for_forex)    # unticked = OFF
        self.assertEqual(acct.get_credentials(), ("k2", "u2"))
        probe.assert_called_once_with("k2", "u2", demo=False)
        self.assertNotIn("REFUSED to untick", body)
        self.assertIn("(live)", body)
        self.assertIn("Demo UNTICKED: from this save the same pair places "
                      "REAL orders", body)

    def test_a_demo_to_demo_re_save_needs_no_pin(self):
        """The guard is one-directional. A re-save that keeps Demo ticked —
        with a live config enabled AND a class ticked — goes through as it
        always did, and the flags are read."""
        self._cfg(enabled=True)
        body, probe = self._post(demo="on", primary_stocks="on")
        acct = self._row()
        self.assertTrue(acct.demo)
        self.assertTrue(acct.is_primary_for_stocks)
        self.assertFalse(acct.is_primary_for_forex)
        self.assertEqual(acct.get_credentials(), ("k2", "u2"))
        probe.assert_called_once_with("k2", "u2", demo=True)
        self.assertNotIn("REFUSED to untick", body)

    def test_a_live_to_demo_re_save_needs_no_pin(self):
        """Toward the virtual world there is no PIN: the flip places no real
        order, so an enabled live config does not stop it either. It does
        need the Switch world tick since 2026-09-28 — it points every later
        close at the virtual portfolio (TheDemoTickIsGuardedTests)."""
        EtoroAccount.objects.filter(user=self.user).update(demo=False)
        self._cfg(enabled=True)
        body, probe = self._post(demo="on", confirm_world_change="on")
        self.assertTrue(self._row().demo)
        probe.assert_called_once_with("k2", "u2", demo=True)
        self.assertNotIn("REFUSED to untick", body)
        self.assertNotIn("REFUSED to tick", body)

    def test_a_fresh_row_saved_live_is_not_a_flip(self):
        """No row yet: nothing to flip from. The first save of a pair with
        Demo unticked is the operator's declared choice, as it was before
        the guard — the guard is on the CHANGE of world, where a virtual
        habit meets a real order."""
        EtoroAccount.objects.filter(user=self.user).delete()
        body, probe = self._post()
        self.assertFalse(self._row().demo)
        probe.assert_called_once_with("k2", "u2", demo=False)
        self.assertNotIn("REFUSED to untick", body)

    def test_the_pin_gate_is_the_platforms_not_a_copy(self):
        from dashboard import views_brokers
        from dashboard.views_admin_hq import _pin_ok
        self.assertIs(views_brokers._pin_ok, _pin_ok)

    def test_the_form_carries_the_pin_field_and_names_the_measurement(self):
        body = self.client.get(reverse("brokers_page")).content.decode()
        form = body[body.index("Add / Update eToro Keys"):
                    body.index("Register Saxo Application")]
        self.assertIn('name="pin"', form)
        self.assertIn("same pair opens both worlds", form)
        self.assertIn("Unticking it sends real orders", form)
        self.assertNotIn("portfolio keys", form)


class TheDemoTickIsGuardedTests(TestCase):
    """The way back is guarded too, on different terms (2026-09-28).

    live -> demo places no real order, so no PIN. What it does is point
    every later CLOSE at the virtual portfolio — the router builds the
    client from the Demo flag at call time — so a real position still open
    at eToro can no longer be closed through the platform. And the form
    made it the default: Demo shipped ticked whatever the row said. So the
    flip needs the Switch world tick, and is refused — tick or no tick —
    while any real eToro position is OPEN or CLOSE_PENDING. Nothing is
    written on a refusal, and the probe is not sent."""

    def setUp(self):
        self.user = User.objects.create_user("dt_u", password="x")
        self.admin = User.objects.create_superuser("dt_admin", "a@x", "x")
        acct = EtoroAccount.objects.create(user=self.user, demo=False,
                                           connected=True,
                                           is_primary_for_stocks=True)
        acct.set_credentials(RAW_KEY, RAW_USER)
        acct.save()
        self.client.force_login(self.admin)

    def _post(self, **extra):
        data = {"target_username": "dt_u", "etoro_api_key": "k2",
                "etoro_user_key": "u2", "demo": "on",
                "primary_stocks": "on"}
        data.update(extra)
        with mock.patch("dashboard.views_brokers.etoro_probe",
                        return_value=("ok", "200")) as probe:
            r = self.client.post(reverse("hq_save_etoro"), data, follow=True)
        return r.content.decode(), probe

    def _row(self):
        return EtoroAccount.objects.get(user=self.user)

    def _trade(self, *, symbol="AAPL", status="OPEN", paper=False,
               broker="etoro", world="live", asset_class="stock"):
        from bot_program.models import AssetBotConfig, AssetBotTrade
        cfg, _ = AssetBotConfig.objects.get_or_create(
            user=self.user, name="megacaps",
            defaults={"asset_class": "stock", "mode": "live",
                      "enabled": False, "symbols": ["AAPL"]})
        meta = {}
        if broker:
            meta["broker"] = broker
        if world:
            meta["broker_env"] = world
        return AssetBotTrade.objects.create(
            config=cfg, asset_class=asset_class, symbol=symbol, side="BUY",
            qty=1, entry_price=100, status=status, paper=paper,
            metadata=meta)

    def assertStillLive(self, probe):
        acct = self._row()
        self.assertFalse(acct.demo)
        self.assertTrue(acct.is_primary_for_stocks)
        self.assertEqual(acct.get_credentials(), (RAW_KEY, RAW_USER))
        probe.assert_not_called()

    def test_the_flip_is_refused_without_the_switch_world_tick(self):
        body, probe = self._post()
        self.assertStillLive(probe)
        self.assertIn("REFUSED to tick Demo for dt_u", body)
        self.assertIn("nothing was saved", body)
        self.assertIn("the &#x27;Switch world&#x27; box was not ticked", body)
        self.assertIn("every close", body)

    def test_the_flip_is_refused_with_real_positions_open_even_ticked(self):
        """Tick or no tick: no box makes stranding a real position safe."""
        a = self._trade(symbol="AAPL")
        b = self._trade(symbol="MSFT", status="CLOSE_PENDING")
        body, probe = self._post(confirm_world_change="on")
        self.assertStillLive(probe)
        self.assertIn("2 real positions are still open at eToro; switching "
                      "to demo would cut the platform off from closing them",
                      body)
        self.assertIn(f"[{a.pk}] AAPL, [{b.pk}] MSFT", body)
        self.assertNotIn("Switch world&#x27; box was not ticked", body)

    def test_both_reasons_are_printed_at_once(self):
        self._trade()
        body, probe = self._post()
        self.assertStillLive(probe)
        self.assertIn("(1) the &#x27;Switch world&#x27; box", body)
        self.assertIn("(2) 1 real position is still open at eToro; "
                      "switching to demo would cut the platform off from "
                      "closing it", body)

    def test_a_row_with_no_world_stamp_counts_as_real(self):
        """The row is LIVE today and an unknown world may be the real one:
        a refusal the operator can read beats a position nothing can
        close."""
        self._trade(world="")
        body, probe = self._post(confirm_world_change="on")
        self.assertStillLive(probe)
        self.assertIn("1 real position is still open at eToro", body)

    def test_what_is_not_a_real_etoro_position_does_not_count(self):
        """Closed, paper, filled in the virtual world, stamped as carried by
        another broker, or unstamped in a class this row does not carry:
        none of them is stranded by the flip. (EURUSD is booked forex and
        its Instrument says forex; ZZZ has no Instrument, so the router
        reads it as crypto — neither is a class this row is primary for.)"""
        from instruments.models import Instrument
        Instrument.objects.create(symbol="EURUSD", name="EUR/USD",
                                  asset_class="forex")
        self._trade(status="CLOSED")
        self._trade(paper=True)
        self._trade(world="paper")
        self._trade(broker="ibkr")
        self._trade(broker="", symbol="EURUSD", asset_class="forex")
        self._trade(broker="", symbol="ZZZ", asset_class="forex")
        body, probe = self._post(confirm_world_change="on")
        acct = self._row()
        self.assertTrue(acct.demo)
        self.assertTrue(acct.is_primary_for_stocks)
        self.assertEqual(acct.get_credentials(), ("k2", "u2"))
        probe.assert_called_once_with("k2", "u2", demo=True)
        self.assertNotIn("REFUSED", body)
        self.assertIn("Demo TICKED: from this save every order and every "
                      "close goes to the virtual portfolio", body)

    def test_a_row_with_no_carrier_counts_when_this_row_carries_its_class(
            self):
        """A TAKE TRADE booked before 2026-09-24 has no metadata["broker"].
        venue_close refuses nothing for it, so its close goes wherever the
        router answers — here, this row, primary for stocks — and after the
        flip, to the virtual portfolio. Unknown carrier, like unknown world,
        counts."""
        t = self._trade(broker="")
        body, probe = self._post(confirm_world_change="on")
        self.assertStillLive(probe)
        self.assertIn(f"1 real position is still open at eToro; switching "
                      f"to demo would cut the platform off from closing it "
                      f"([{t.pk}] AAPL)", body)

    def test_a_row_with_no_carrier_counts_by_the_instrument_class_too(self):
        """The router asks the INSTRUMENT's class, not the class the trade
        was booked under: a forex instrument in a stock config goes to the
        row primary for forex."""
        from instruments.models import Instrument
        Instrument.objects.create(symbol="EURUSD", name="EUR/USD",
                                  asset_class="forex")
        EtoroAccount.objects.filter(user=self.user).update(
            is_primary_for_stocks=False, is_primary_for_forex=True)
        self._trade(broker="", world="", symbol="EURUSD")
        body, probe = self._post(confirm_world_change="on",
                                 primary_stocks="", primary_forex="on")
        acct = self._row()
        self.assertFalse(acct.demo)
        self.assertTrue(acct.is_primary_for_forex)
        probe.assert_not_called()
        self.assertIn("1 real position is still open at eToro", body)

    def test_a_routing_save_that_keeps_the_row_live_needs_nothing(self):
        """The save the trap used to catch: Demo left as it is on file
        (unticked), one class box changed, the pair on file retyped."""
        body, probe = self._post(demo="", primary_stocks="",
                                 primary_forex="on",
                                 etoro_api_key=RAW_KEY,
                                 etoro_user_key=RAW_USER)
        acct = self._row()
        self.assertFalse(acct.demo)
        self.assertTrue(acct.is_primary_for_forex)
        self.assertFalse(acct.is_primary_for_stocks)
        probe.assert_called_once_with(RAW_KEY, RAW_USER, demo=False)
        self.assertNotIn("REFUSED", body)
        self.assertNotIn("environment changed", body)

    def test_the_demo_to_live_guard_is_unchanged(self):
        """The untick keeps its own guard, PIN and all — the Switch world
        tick is not a way around it."""
        EtoroAccount.objects.filter(user=self.user).update(demo=True)
        body, probe = self._post(demo="", primary_stocks="",
                                 confirm_world_change="on")
        self.assertTrue(self._row().demo)
        probe.assert_not_called()
        self.assertIn("REFUSED to untick Demo for dt_u", body)
        self.assertIn("the trading PIN was not supplied", body)


class TheKeySwapIsGuardedTests(TestCase):
    """A different pair on a LIVE row is a different account (2026-09-28).

    The eToro form opens on the logged-in account now, not on an empty
    "pick an account" the browser refused to submit. The failure that
    makes possible: a superuser with a LIVE row types a teammate's pair and
    forgets the dropdown; live -> live had no guard, the probe passes (the
    pair is good), and from then on the superuser's live configs place real
    orders in the teammate's account while every close of the superuser's
    open positions goes where their positionId does not exist. So a pair
    that differs from the one on file, on a LIVE row that stays live, needs
    the "Replace keys" tick, and is refused — tick or no tick — while a
    real eToro position is open. Nothing is written on a refusal, and the
    probe is not sent. The rows here are the superuser's OWN, posted with
    the preselected target, because that is the scenario."""

    def setUp(self):
        self.admin = User.objects.create_superuser("ks_admin", "a@x", "x")
        acct = EtoroAccount.objects.create(user=self.admin, demo=False,
                                           connected=True,
                                           is_primary_for_stocks=True)
        acct.set_credentials(RAW_KEY, RAW_USER)
        acct.save()
        self.client.force_login(self.admin)

    def _post(self, **extra):
        """A save of a TEAMMATE's pair onto the preselected (own) account,
        the row's boxes as they are on file."""
        data = {"target_username": "ks_admin",
                "etoro_api_key": "teammate-k", "etoro_user_key": "teammate-u",
                "primary_stocks": "on"}
        data.update(extra)
        with mock.patch("dashboard.views_brokers.etoro_probe",
                        return_value=("ok", "200")) as probe:
            r = self.client.post(reverse("hq_save_etoro"), data, follow=True)
        return r.content.decode(), probe

    def _row(self):
        return EtoroAccount.objects.get(user=self.admin)

    def _trade(self, *, broker="etoro"):
        from bot_program.models import AssetBotConfig, AssetBotTrade
        cfg, _ = AssetBotConfig.objects.get_or_create(
            user=self.admin, name="megacaps",
            defaults={"asset_class": "stock", "mode": "live",
                      "enabled": False, "symbols": ["AAPL"]})
        meta = {"broker_env": "live"}
        if broker:
            meta["broker"] = broker
        return AssetBotTrade.objects.create(
            config=cfg, asset_class="stock", symbol="AAPL", side="BUY",
            qty=1, entry_price=100, status="OPEN", paper=False,
            metadata=meta)

    def assertKeptTheOwnPair(self, probe):
        acct = self._row()
        self.assertFalse(acct.demo)
        self.assertTrue(acct.is_primary_for_stocks)
        self.assertEqual(acct.get_credentials(), (RAW_KEY, RAW_USER))
        probe.assert_not_called()

    def test_a_teammates_pair_on_the_preselected_row_is_refused(self):
        body, probe = self._post()
        self.assertKeptTheOwnPair(probe)
        self.assertIn("REFUSED to replace the key pair on "
                      "ks_admin&#x27;s LIVE row — nothing was saved", body)
        self.assertIn("the &#x27;Replace keys&#x27; box was not ticked", body)
        self.assertIn("pick it in the dropdown", body)

    def test_refused_with_a_real_position_open_even_ticked(self):
        """Nothing here can prove two pairs open one account, so a
        rotation waits for the open positions too."""
        t = self._trade()
        body, probe = self._post(confirm_key_change="on")
        self.assertKeptTheOwnPair(probe)
        self.assertIn(f"1 real position is still open at eToro under the "
                      f"pair on file; a different pair would send its close "
                      f"to the account that pair opens, where it does not "
                      f"exist ([{t.pk}] AAPL)", body)
        self.assertNotIn("Replace keys&#x27; box was not ticked", body)

    def test_an_unstamped_position_counts_here_too(self):
        self._trade(broker="")
        body, probe = self._post(confirm_key_change="on")
        self.assertKeptTheOwnPair(probe)
        self.assertIn("1 real position is still open at eToro under the "
                      "pair on file", body)

    def test_both_reasons_are_printed_at_once(self):
        self._trade()
        body, probe = self._post()
        self.assertKeptTheOwnPair(probe)
        self.assertIn("(1) the &#x27;Replace keys&#x27; box", body)
        self.assertIn("(2) 1 real position is still open at eToro", body)

    def test_a_ticked_replacement_with_nothing_open_goes_through(self):
        """A rotation meant on purpose: the box ticked, and the only open
        row is stamped as another broker's — that stamp is a fact, and the
        pair on this row cannot close it anyway."""
        self._trade(broker="ibkr")
        body, probe = self._post(confirm_key_change="on")
        acct = self._row()
        self.assertFalse(acct.demo)
        self.assertEqual(acct.get_credentials(),
                         ("teammate-k", "teammate-u"))
        probe.assert_called_once_with("teammate-k", "teammate-u", demo=False)
        self.assertNotIn("REFUSED", body)

    def test_retyping_the_pair_on_file_is_not_asked(self):
        """The routing-only save: same pair, a class box moved."""
        self._trade()
        body, probe = self._post(etoro_api_key=RAW_KEY,
                                 etoro_user_key=RAW_USER,
                                 primary_stocks="", primary_forex="on")
        acct = self._row()
        self.assertTrue(acct.is_primary_for_forex)
        self.assertFalse(acct.is_primary_for_stocks)
        probe.assert_called_once_with(RAW_KEY, RAW_USER, demo=False)
        self.assertNotIn("REFUSED", body)

    def test_a_live_row_with_no_pair_on_file_is_not_asked(self):
        """Nothing to swap from — "Forget eToro keys" leaves a live row with
        no pair, the router answers paper for it, and re-entering a pair is
        how its open positions become reachable again."""
        self._trade()
        EtoroAccount.objects.filter(user=self.admin).update(
            api_key_enc="", user_key_enc="")
        body, probe = self._post()
        self.assertEqual(self._row().get_credentials(),
                         ("teammate-k", "teammate-u"))
        probe.assert_called_once_with("teammate-k", "teammate-u", demo=False)
        self.assertNotIn("REFUSED", body)

    def test_a_demo_row_is_not_asked(self):
        """A demo row's positions are virtual; a new pair there moves no
        real money and strands nothing real."""
        EtoroAccount.objects.filter(user=self.admin).update(demo=True)
        body, probe = self._post(demo="on")
        acct = self._row()
        self.assertTrue(acct.demo)
        self.assertEqual(acct.get_credentials(),
                         ("teammate-k", "teammate-u"))
        self.assertNotIn("REFUSED", body)


class TheFormShowsTheRowOnFileTests(TestCase):
    """The two forms post every box at once, so a box that starts at a
    default instead of the row is a change nobody chose. Demo and SIM
    shipped ticked and every class box unticked, whatever the row said
    (2026-09-28). Now the picked account's row is rendered, the logged-in
    account is preselected, and every option carries its own row for the
    script to move the boxes when the dropdown moves."""

    def setUp(self):
        self.admin = User.objects.create_superuser("fo_admin", "a@x", "x")
        self.other = User.objects.create_user("fo_other", password="x")
        self.client.force_login(self.admin)

    def _page(self):
        return self.client.get(reverse("brokers_page")).content.decode()

    @staticmethod
    def _forms(body):
        etoro = body[body.index("Add / Update eToro Keys"):
                     body.index("Register Saxo Application")]
        saxo = body[body.index("Register Saxo Application"):]
        saxo = saxo[:saxo.index("</form>")]
        return etoro, saxo

    @staticmethod
    def _box(form, name):
        start = form.index(f'name="{name}"')
        return form[start:form.index(">", start)]

    def test_a_live_etoro_row_renders_demo_unticked_and_its_classes(self):
        EtoroAccount.objects.create(user=self.admin, demo=False,
                                    is_primary_for_stocks=True,
                                    is_primary_for_crypto=True)
        etoro, _ = self._forms(self._page())
        self.assertNotIn("checked", self._box(etoro, "demo"))
        self.assertIn("checked", self._box(etoro, "primary_stocks"))
        self.assertIn("checked", self._box(etoro, "primary_crypto"))
        self.assertNotIn("checked", self._box(etoro, "primary_forex"))
        self.assertIn("On file for fo_admin: LIVE · primary for stocks, "
                      "crypto.", etoro)

    def test_a_live_saxo_row_renders_sim_unticked_and_its_uri(self):
        from tests.test_saxo_wiring import saxo
        saxo(self.admin, flags=("forex",), sim=False)
        _, form = self._forms(self._page())
        self.assertNotIn("checked", self._box(form, "sim"))
        self.assertIn("checked", self._box(form, "primary_forex"))
        self.assertNotIn("checked", self._box(form, "primary_stocks"))
        self.assertIn('value="https://h.example.net/brokers/saxo/callback/"',
                      self._box(form, "saxo_redirect_uri"))
        self.assertIn("On file for fo_admin: LIVE · session open · primary "
                      "for forex.", form)

    def test_no_row_renders_a_new_row_s_defaults(self):
        etoro, saxo = self._forms(self._page())
        self.assertIn("checked", self._box(etoro, "demo"))
        self.assertIn("checked", self._box(saxo, "sim"))
        for name in ("primary_stocks", "primary_forex", "primary_commodity",
                     "primary_crypto"):
            self.assertNotIn("checked", self._box(etoro, name), name)
            self.assertNotIn("checked", self._box(saxo, name), name)
        self.assertIn("no eToro row yet", etoro)
        self.assertIn("no Saxo application yet", saxo)

    def test_the_logged_in_account_is_preselected(self):
        etoro, saxo = self._forms(self._page())
        for form in (etoro, saxo):
            self.assertIn('<option value="fo_admin" selected', form)
            self.assertNotIn('<option value="fo_other" selected', form)

    def test_every_option_carries_its_own_row_for_the_script(self):
        EtoroAccount.objects.create(user=self.other, demo=False,
                                    is_primary_for_forex=True)
        from tests.test_saxo_wiring import saxo
        saxo(self.other, flags=("stock", "crypto"), sim=True, session=False)
        etoro, form = self._forms(self._page())
        self.assertIn('<option value="fo_other" data-ticked="primary_forex"',
                      etoro)
        self.assertIn('<option value="fo_other" data-ticked="sim '
                      'primary_stocks primary_crypto"', form)
        self.assertIn('data-redirect-uri="https://h.example.net/brokers/'
                      'saxo/callback/"', form)
        body = self._page()
        self.assertIn("form[data-reflects-row]", body)

    def test_the_switch_world_box_is_there_and_never_prefilled(self):
        etoro, saxo = self._forms(self._page())
        for form in (etoro, saxo):
            self.assertIn('name="confirm_world_change"', form)
            self.assertNotIn("checked", self._box(form,
                                                  "confirm_world_change"))

    def test_the_replace_keys_box_is_there_never_prefilled_or_carried(self):
        """eToro only: a new Saxo key closes the session, so nothing trades
        on it until the next sign-in. The script unticks it with Switch
        world whenever the dropdown moves."""
        body = self._page()
        etoro, saxo = self._forms(body)
        self.assertIn('name="confirm_key_change"', etoro)
        self.assertNotIn("checked", self._box(etoro, "confirm_key_change"))
        self.assertNotIn('name="confirm_key_change"', saxo)
        script = body[body.index("form[data-reflects-row]") - 2000:]
        self.assertIn('"confirm_world_change", "confirm_key_change"', script)

    def test_the_stale_session_sentence_is_gone(self):
        """It said "Re-saving closes any open session" two lines above the
        form's own "Re-saving the same application no longer closes the
        session". The reworded note says which saves close it."""
        _, saxo = self._forms(self._page())
        self.assertNotIn("Re-saving closes any open session", saxo)
        self.assertIn("Changing the key, the secret, the redirect URI or SIM "
                      "closes any open session; a save that only changes the "
                      "class boxes keeps it.", saxo)


class SavingSaxoTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("sx_u", password="x")
        self.admin = User.objects.create_superuser("sx_admin", "a@x", "x")

    def test_the_application_is_recorded_and_honestly_not_connected(self):
        self.client.force_login(self.admin)
        r = self.client.post(reverse("hq_save_saxo"), {
            "target_username": "sx_u", "saxo_app_key": RAW_APP,
            "saxo_app_secret": RAW_SECRET,
            "saxo_redirect_uri": "https://host/brokers/saxo/callback/",
            "sim": "on"})
        self.assertEqual(r.status_code, 302)
        acct = SaxoAccount.objects.get(user=self.user)
        self.assertEqual(acct.get_credentials(), (RAW_APP, RAW_SECRET))
        self.assertEqual(acct.redirect_uri,
                         "https://host/brokers/saxo/callback/")
        self.assertTrue(acct.sim)
        self.assertFalse(acct.connected)
        self.assertFalse(acct.has_session)
        page = self.client.get(reverse("brokers_page")).content.decode()
        self.assertIn("Not yet", page)
        self.assertNotIn(RAW_SECRET, page)

    def test_a_missing_redirect_uri_is_refused(self):
        """A mismatch there is the classic OAuth failure, and it is caught
        at the portal, not here — but an EMPTY one can be caught here."""
        self.client.force_login(self.admin)
        self.client.post(reverse("hq_save_saxo"), {
            "target_username": "sx_u", "saxo_app_key": RAW_APP,
            "saxo_app_secret": RAW_SECRET, "saxo_redirect_uri": ""})
        self.assertFalse(SaxoAccount.objects.exists())


class TheSaxoWorldFlipIsGuardedTests(TestCase):
    """The Saxo twin of TheDemoTickIsGuardedTests (2026-09-28).

    Saxo serves SIM and live from ONE row, and broker_router builds
    SaxoTrader from the row's SIM box at call time, so a flip made with a
    real position open sends every later close — the time stop, a bot
    exit, the operator's close, EMERGENCY FLATTEN — to the other gateway,
    where the position does not exist. The guard on the flip asked only
    about the SESSION: alive, the Switch world tick let it through; dead
    (the ordinary state after a long pause), it asked for nothing at all.
    Now the flip is refused, nothing written and the session untouched,
    while any real Saxo position is OPEN or CLOSE_PENDING — tick or no
    tick, session alive or not. A row with nothing open keeps the session
    rule exactly as it was."""

    URI = "https://host/brokers/saxo/callback/"

    def setUp(self):
        self.user = User.objects.create_user("sw_u", password="x")
        self.admin = User.objects.create_superuser("sw_admin", "a@x", "x")
        acct = SaxoAccount.objects.create(user=self.user, sim=False,
                                          redirect_uri=self.URI,
                                          is_primary_for_stocks=True)
        acct.set_credentials(RAW_APP, RAW_SECRET)
        acct.save()
        self.client.force_login(self.admin)

    def _post(self, **extra):
        """SIM ticked on a LIVE row, a new pair typed and the class box
        moved: a save that goes through leaves every one of those on the
        row, so a refusal is checked on all of them."""
        data = {"target_username": "sw_u", "saxo_app_key": "k2",
                "saxo_app_secret": "s2", "saxo_redirect_uri": self.URI,
                "sim": "on", "primary_forex": "on"}
        data.update(extra)
        r = self.client.post(reverse("hq_save_saxo"), data, follow=True)
        return r.content.decode()

    def _row(self):
        return SaxoAccount.objects.get(user=self.user)

    def _sign_in(self):
        from datetime import timedelta

        from django.utils import timezone
        acct = self._row()
        acct.set_tokens("acc", "ref", timezone.now() + timedelta(seconds=1200),
                        refresh_expires_at=timezone.now()
                        + timedelta(seconds=2400))
        acct.connected = True
        acct.save()

    def _trade(self, *, symbol="AAPL", status="OPEN", paper=False,
               broker="saxo", world="live", asset_class="stock"):
        from bot_program.models import AssetBotConfig, AssetBotTrade
        cfg, _ = AssetBotConfig.objects.get_or_create(
            user=self.user, name="megacaps",
            defaults={"asset_class": "stock", "mode": "live",
                      "enabled": False, "symbols": ["AAPL"]})
        meta = {}
        if broker:
            meta["broker"] = broker
        if world:
            meta["broker_env"] = world
        return AssetBotTrade.objects.create(
            config=cfg, asset_class=asset_class, symbol=symbol, side="BUY",
            qty=1, entry_price=100, status=status, paper=paper,
            metadata=meta)

    def assertNothingWritten(self, body):
        acct = self._row()
        self.assertFalse(acct.sim)
        self.assertTrue(acct.is_primary_for_stocks)
        self.assertFalse(acct.is_primary_for_forex)
        self.assertEqual(acct.get_credentials(), (RAW_APP, RAW_SECRET))
        self.assertIn("REFUSED to switch sw_u from LIVE to SIM", body)
        self.assertIn("nothing was saved", body)

    def test_the_flip_is_refused_with_real_positions_open_even_ticked(self):
        """The finding's own scenario: the refresh token has lapsed, so the
        session rule asks for nothing — and the tick is given anyway."""
        a = self._trade(symbol="AAPL")
        b = self._trade(symbol="MSFT", status="CLOSE_PENDING")
        body = self._post(confirm_world_change="on")
        self.assertNothingWritten(body)
        self.assertIn("2 real positions are still open at Saxo; switching "
                      "world would cut the platform off from closing them",
                      body)
        self.assertIn(f"[{a.pk}] AAPL, [{b.pk}] MSFT", body)

    def test_the_flip_is_refused_with_the_session_alive_and_no_tick_too(self):
        """Refused on the positions, and the session and the readings the
        flip would have closed and dropped are left exactly as they were."""
        from decimal import Decimal
        self._sign_in()
        SaxoAccount.objects.filter(user=self.user).update(
            last_equity=Decimal("2500"))
        t = self._trade()
        body = self._post()
        self.assertNothingWritten(body)
        self.assertIn(f"1 real position is still open at Saxo; switching "
                      f"world would cut the platform off from closing it "
                      f"([{t.pk}] AAPL)", body)
        acct = self._row()
        self.assertTrue(acct.session_alive())
        self.assertEqual(acct.get_refresh_token(), "ref")
        self.assertEqual(acct.last_equity, Decimal("2500"))

    def test_the_other_direction_is_refused_the_same_way(self):
        """SIM -> live strands a real position just as well: the row is
        SIM today, and an unstamped world may be the real one."""
        SaxoAccount.objects.filter(user=self.user).update(sim=True)
        t = self._trade(world="")
        body = self._post(sim="", confirm_world_change="on")
        acct = self._row()
        self.assertTrue(acct.sim)
        self.assertFalse(acct.is_primary_for_forex)
        self.assertEqual(acct.get_credentials(), (RAW_APP, RAW_SECRET))
        self.assertIn("REFUSED to switch sw_u from SIM to LIVE", body)
        self.assertIn(f"1 real position is still open at Saxo; switching "
                      f"world would cut the platform off from closing it "
                      f"([{t.pk}] AAPL)", body)

    def test_a_row_with_no_world_stamp_counts_as_real(self):
        self._trade(world="")
        body = self._post(confirm_world_change="on")
        self.assertNothingWritten(body)
        self.assertIn("1 real position is still open at Saxo", body)

    def test_what_is_not_a_real_saxo_position_does_not_count(self):
        """Closed, paper, filled on the simulator, stamped as carried by
        another broker, or unstamped in a class this row does not carry:
        none of them is stranded by the flip. (EURUSD is booked forex and
        its Instrument says forex; ZZZ has no Instrument, so the router
        reads it as crypto — neither is a class this row is primary for.)
        No session, so no tick is needed either — the rule as it was."""
        from instruments.models import Instrument
        Instrument.objects.create(symbol="EURUSD", name="EUR/USD",
                                  asset_class="forex")
        self._trade(status="CLOSED")
        self._trade(paper=True)
        self._trade(world="paper")
        self._trade(broker="etoro")
        self._trade(broker="", symbol="EURUSD", asset_class="forex")
        self._trade(broker="", symbol="ZZZ", asset_class="forex")
        body = self._post()
        acct = self._row()
        self.assertTrue(acct.sim)
        self.assertTrue(acct.is_primary_for_forex)
        self.assertFalse(acct.is_primary_for_stocks)
        self.assertEqual(acct.get_credentials(), ("k2", "s2"))
        self.assertNotIn("REFUSED", body)
        self.assertIn("Saxo application saved for sw_u (sim)", body)

    def test_a_row_with_no_carrier_counts_when_this_row_carries_its_class(
            self):
        """A TAKE TRADE booked before 2026-09-24 has no metadata["broker"];
        its close goes wherever the router answers — this row, primary for
        stocks — and after the flip, to the other gateway."""
        t = self._trade(broker="")
        body = self._post(confirm_world_change="on")
        self.assertNothingWritten(body)
        self.assertIn(f"1 real position is still open at Saxo; switching "
                      f"world would cut the platform off from closing it "
                      f"([{t.pk}] AAPL)", body)

    def test_a_row_with_no_carrier_counts_by_the_instrument_class_too(self):
        from instruments.models import Instrument
        Instrument.objects.create(symbol="EURUSD", name="EUR/USD",
                                  asset_class="forex")
        SaxoAccount.objects.filter(user=self.user).update(
            is_primary_for_stocks=False, is_primary_for_forex=True)
        self._trade(broker="", world="", symbol="EURUSD")
        body = self._post(confirm_world_change="on")
        acct = self._row()
        self.assertFalse(acct.sim)
        self.assertTrue(acct.is_primary_for_forex)
        self.assertEqual(acct.get_credentials(), (RAW_APP, RAW_SECRET))
        self.assertIn("1 real position is still open at Saxo", body)

    def test_a_save_that_keeps_the_world_is_not_asked(self):
        """Positions open, SIM left as it is on file, one class box moved:
        the routing save the trap used to catch goes through."""
        self._trade()
        body = self._post(sim="", saxo_app_key=RAW_APP,
                          saxo_app_secret=RAW_SECRET)
        acct = self._row()
        self.assertFalse(acct.sim)
        self.assertTrue(acct.is_primary_for_forex)
        self.assertFalse(acct.is_primary_for_stocks)
        self.assertNotIn("REFUSED", body)
        self.assertIn("Saxo routing saved for sw_u", body)

    def test_a_row_with_nothing_open_keeps_the_session_rule(self):
        """No positions: a dead session flips with no tick, an alive one
        is refused on the session and says nothing about positions."""
        self._sign_in()
        body = self._post()
        self.assertTrue(self._row().session_alive())
        self.assertIn("REFUSED to switch sw_u from LIVE to SIM", body)
        self.assertIn("has an open session", body)
        self.assertNotIn("still open at Saxo", body)
        acct = self._row()
        acct.clear_session()
        acct.save()
        body = self._post()
        self.assertTrue(self._row().sim)
        self.assertNotIn("REFUSED", body)


class TheRailReachesItTests(TestCase):

    def test_the_page_is_on_the_rail_under_the_money(self):
        from pathlib import Path

        from django.conf import settings
        rail = (Path(settings.BASE_DIR) / "templates"
                / "base.html").read_text(encoding="utf-8")
        self.assertIn("{% url 'brokers_page' %}", rail)
        self.assertIn("page_id == 'brokers'", rail)


class TheEtoroBoxesSayWhatIsMeasuredAndProvenTests(TestCase):
    """E3.5 + GAP 4 (2026-09-26). Each eToro class box carries, in English
    on one line, what eToro answered on 2026-09-23 (stocks real at 1x from
    10 USD; ETFs CFD only; forex, indices and commodities a 1,000 USD
    minimum; crypto real at 1x from 10 USD) and the class's proof state.
    ETORO_PROVEN carries crypto alone since 2026-09-26, so every other box
    reads "no proof pinned — entries refused"; a save that ticks a box
    names what the gate will
    refuse — on the verified branch too, which said nothing before. The
    gate keys on the INSTRUMENT's class, so the stocks box needs three
    tokens: stock, etf, index."""

    PROVEN = "bot_program.asset_engine.base.ETORO_PROVEN"
    ALL_STOCKS = frozenset({"stock", "etf", "index", "short"})

    def setUp(self):
        self.user = User.objects.create_user("pf_u", password="x")
        self.admin = User.objects.create_superuser("pf_admin", "a@x", "x")
        self.client.force_login(self.admin)

    def _form(self):
        body = self.client.get(reverse("brokers_page")).content.decode()
        return body[body.index("Add / Update eToro Keys"):
                    body.index("Register Saxo Application")]

    @staticmethod
    def _label(form, name):
        start = form.index(f'name="{name}"')
        return form[start:form.index("</label>", start)]

    def _save(self, verdict=("ok", "200"), **boxes):
        data = {"target_username": "pf_u", "etoro_api_key": RAW_KEY,
                "etoro_user_key": RAW_USER, "demo": "on"}
        data.update(boxes)
        with mock.patch("dashboard.views_brokers.etoro_probe",
                        return_value=verdict):
            r = self.client.post(reverse("hq_save_etoro"), data, follow=True)
        return r.content.decode()

    def test_the_four_labels_carry_the_measured_facts(self):
        form = self._form()
        self.assertIn("what eToro answered when measured on 2026-09-23", form)
        stocks = self._label(form, "primary_stocks")
        for fact in ("stocks · ETFs · indices",
                     "real shares at 1x from 10 USD (W-8BEN)",
                     "CFD at 2–5x or short",
                     "ETFs CFD only, overnight fee even at 1x",
                     "indices CFD, 1,000 USD minimum"):
            self.assertIn(fact, stocks)
        forex = self._label(form, "primary_forex")
        for fact in ("CFD only", "1,000 USD minimum", "up to 30x live",
                     "this platform caps lower"):
            self.assertIn(fact, forex)
        commodity = self._label(form, "primary_commodity")
        for fact in ("CFD only", "WHEAT.FUT and PLATINUM found",
                     "gold, silver and oil spellings unknown",
                     "1,000 USD minimum"):
            self.assertIn(fact, commodity)
        crypto = self._label(form, "primary_crypto")
        for fact in ("real coins at 1x from 10 USD (BTC, ETH, XRP, SOL)",
                     "CFD at 2x or short",
                     "unticked, crypto routes to Binance"):
            self.assertIn(fact, crypto)

    def test_every_box_but_crypto_says_no_proof_is_pinned(self):
        """As the tree ships since 2026-09-28: crypto's proof is pinned
        (the real BTC round trip, test_proof_crypto) and the stocks box
        carries the ETF proof alone (the demo GLDM round trip,
        test_proof_etf) with stock and index still refused; forex and
        commodity read "no proof pinned — entries refused"."""
        form = self._form()
        for name in ("primary_forex", "primary_commodity"):
            self.assertIn("no proof pinned — entries refused",
                          self._label(form, name), name)
        crypto = self._label(form, "primary_crypto")
        self.assertIn("proof pinned", crypto)
        self.assertNotIn("no proof pinned", crypto)
        stocks = self._label(form, "primary_stocks")
        self.assertIn("proof pinned for etf only — stock, index entries "
                      "refused", stocks)
        self.assertEqual(form.count("no proof pinned — entries refused"), 2)
        self.assertIn("no short proven", stocks)

    def test_a_pinned_proof_reads_beside_its_box_only(self):
        with mock.patch(self.PROVEN, self.ALL_STOCKS):
            form = self._form()
        stocks = self._label(form, "primary_stocks")
        self.assertIn("proof pinned", stocks)
        self.assertNotIn("no proof pinned", stocks)
        self.assertIn("shorts proven", stocks)
        self.assertEqual(form.count("no proof pinned — entries refused"), 3)

    def test_a_partial_stocks_proof_names_what_is_still_refused(self):
        """An ETF proof (GLDM, the first sitting) lifts ETF entries and
        nothing else on the box."""
        with mock.patch(self.PROVEN, frozenset({"etf"})):
            stocks = self._label(self._form(), "primary_stocks")
        self.assertIn("proof pinned for etf only — stock, index entries "
                      "refused", stocks)

    def test_a_verified_save_names_the_unproven_class_and_the_refusal(self):
        body = self._save(primary_stocks="on")
        self.assertIn("eToro keys saved and verified for pf_u (demo).", body)
        # etf's proof is pinned since 2026-09-28; stock and index are not.
        self.assertIn("No demo fill-and-close proof is pinned for stock, "
                      "index", body)
        self.assertIn("gate_blocked", body)
        self.assertIn("Every short is refused as well", body)
        self.assertNotIn("now the book", body)
        self.assertTrue(EtoroAccount.objects.get(user=self.user)
                        .is_primary_for_stocks)

    def test_a_proven_class_saves_without_the_note(self):
        with mock.patch(self.PROVEN, self.ALL_STOCKS):
            body = self._save(primary_stocks="on")
        self.assertIn("saved and verified", body)
        self.assertNotIn("No demo fill-and-close proof", body)
        self.assertNotIn("Every short is refused", body)

    def test_a_stock_proof_alone_still_names_etf_and_index(self):
        with mock.patch(self.PROVEN, frozenset({"stock"})):
            body = self._save(primary_stocks="on", primary_crypto="on")
        self.assertIn("No demo fill-and-close proof is pinned for etf, "
                      "index, crypto", body)
        self.assertIn("every eToro entry of those classes is refused "
                      "(gate_blocked), by the bots and by TAKE TRADE, each "
                      "until its own proof lands; nothing is sent in the "
                      "meantime.", body)

    def test_a_proven_class_with_shorts_unproven_names_only_the_short(self):
        """Every ticked class proven, "short" not: the note names the short
        alone, with no "as well" leaning on a sentence that is not there."""
        with mock.patch(self.PROVEN, frozenset({"crypto"})):
            body = self._save(primary_crypto="on")
        self.assertNotIn("No demo fill-and-close proof", body)
        self.assertIn("Every short is refused until the short proof is "
                      "pinned.", body)
        self.assertNotIn("refused as well", body)

    def test_a_save_that_ticks_nothing_says_nothing_about_proofs(self):
        body = self._save()
        self.assertIn("saved and verified", body)
        self.assertNotIn("No demo fill-and-close proof", body)
        self.assertNotIn("Every short is refused", body)

    def test_a_refused_save_carries_both_notes(self):
        body = self._save(("refused", "401"), primary_forex="on")
        self.assertIn("now the book", body)
        self.assertIn("No demo fill-and-close proof is pinned for forex "
                      "(ETORO_PROVEN", body)
        self.assertIn("every eToro entry of that class is refused "
                      "(gate_blocked), by the bots and by TAKE TRADE, until "
                      "its proof lands; nothing is sent in the meantime. "
                      "Every short is refused as well until the short proof "
                      "is pinned.", body)
