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
    the target user is enabled. Every other direction is untouched."""

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
        """Toward the virtual world there is no gate: the flip that STOPS
        real orders stays frictionless, like disabling a bot."""
        EtoroAccount.objects.filter(user=self.user).update(demo=False)
        self._cfg(enabled=True)
        body, probe = self._post(demo="on")
        self.assertTrue(self._row().demo)
        probe.assert_called_once_with("k2", "u2", demo=True)
        self.assertNotIn("REFUSED to untick", body)

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


class TheRailReachesItTests(TestCase):

    def test_the_page_is_on_the_rail_under_the_money(self):
        from pathlib import Path

        from django.conf import settings
        rail = (Path(settings.BASE_DIR) / "templates"
                / "base.html").read_text(encoding="utf-8")
        self.assertIn("{% url 'brokers_page' %}", rail)
        self.assertIn("page_id == 'brokers'", rail)
