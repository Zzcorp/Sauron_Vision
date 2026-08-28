"""The credential forms answer the questions they kept provoking.

Three real operator questions, all caused by a field label:

  "should I also input the oanda and alpaca credential in admin too? if yes
   what to put for username?"   — the field said only "Username", and the
   same broker's key also lives in .env for a completely different job, so
   an operator who had set one reasonably assumed the other was done.

  "WHAT HOST to put when inputing IBKR CREDENTIALS again please?"  — asked
   twice. The field pre-filled `127.0.0.1`, which is wrong for every
   containerised deployment and right for none of them: inside the web
   container 127.0.0.1 IS the web container, so the socket times out and
   the failure is indistinguishable from a bad password.

A default that is wrong everywhere is worse than an empty field, because it
looks like advice.

Run with:  python manage.py test tests.test_broker_form_clarity
"""
from django.contrib.auth.models import User
from django.test import TestCase


class TheUsernameFieldSaysWhichUsernameTests(TestCase):

    def setUp(self):
        self.admin = User.objects.create_superuser(
            "bf_admin", "bf@example.com", "x")
        self.client.force_login(self.admin)

    def _page(self):
        return self.client.get("/admin-dashboard/",
                               HTTP_HOST="127.0.0.1").content.decode()

    def test_it_does_not_ask_for_a_typed_username_at_all(self):
        """Superseded, and by the better fix.

        The first pass relabelled the text box "Sauron login username (not
        your broker login)" — an answer to the question. A dropdown of the
        real accounts REMOVES the question, and takes the typo class with
        it: a trailing space in a typed name redirects with "no user named
        'sauron '" and reads as the account being missing.

        The label lives on the select now, so this asserts the mechanism
        rather than the sentence."""
        body = self._page()
        self.assertIn("Account these credentials belong to", body)
        self.assertIn('<select name="target_username"', body)
        self.assertIn("— pick an account —", body)

    def test_the_list_is_the_real_accounts(self):
        User.objects.create_user("bf_trader", password="x")
        self.assertIn('<option value="bf_trader">', self._page())

    def test_the_bare_username_placeholder_is_gone(self):
        body = self._page()
        self.assertNotIn('placeholder="Username"', body)

    def test_the_forms_say_these_credentials_place_orders(self):
        """The .env keys feed the price stream; these place orders. Setting
        one does not set the other, and nothing said so."""
        body = self._page()
        self.assertIn("PLACE ORDERS", body)
        self.assertIn("price stream", body)


class TheIbkrHostFieldSaysWhichHostTests(TestCase):

    def setUp(self):
        self.admin = User.objects.create_superuser(
            "bf_admin2", "bf2@example.com", "x")
        self.client.force_login(self.admin)

    def _page(self):
        return self.client.get("/admin-dashboard/",
                               HTTP_HOST="127.0.0.1").content.decode()

    def test_it_no_longer_defaults_to_the_one_wrong_answer(self):
        """127.0.0.1 inside the web container is the web container."""
        body = self._page()
        self.assertNotIn('name="ibkr_host" value="127.0.0.1"', body)

    def test_it_names_both_supported_setups(self):
        body = self._page()
        self.assertIn("ibgateway", body)
        self.assertIn("host.docker.internal", body)

    def test_it_warns_about_the_failure_that_looks_like_a_bad_password(self):
        """The socket refusing an untrusted IP and a wrong credential are
        the same error from the operator's side."""
        body = self._page()
        self.assertIn("Trusted IPs", body)

    def test_the_default_matches_the_bundled_container(self):
        """`ibgateway` is the compose service name, which Docker's internal
        DNS resolves on the shared network — so the pre-filled value is
        correct for the setup this repo actually ships."""
        from pathlib import Path

        from django.conf import settings
        compose = (Path(settings.BASE_DIR) / "deploy" / "docker-compose.yml"
                   ).read_text(encoding="utf-8")
        self.assertIn("\n  ibgateway:", compose)
        self.assertIn('name="ibkr_host" value="ibgateway"', self._page())

    def test_host_docker_internal_actually_resolves(self):
        """It only works because the django anchor declares it. If that
        extra_hosts entry is ever dropped, the advice above becomes a lie."""
        from pathlib import Path

        from django.conf import settings
        compose = (Path(settings.BASE_DIR) / "deploy" / "docker-compose.yml"
                   ).read_text(encoding="utf-8")
        self.assertIn("host.docker.internal:host-gateway", compose)
