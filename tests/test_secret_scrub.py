"""An upstream 403 must not publish the key that made the call.

`requests.Response.raise_for_status()` builds its message from the FULL
url, query string included. So a forbidden response on a call
authenticated by `?apikey=...` raises an exception whose text carries a
live credential — and that text is stored on the component row, rendered
on the health page, and echoed into every log line that touches it. One
403 put a working API key on a dashboard.

Scrubbing happens in `PlatformComponent.mark_run` rather than at each
call site because that is the one place every ingest outcome passes
through. A hundred callers cannot each be trusted to remember.

Run with:  python manage.py test tests.test_secret_scrub
"""
from django.test import SimpleTestCase, TestCase


class TheKeyNeverReachesTheMessageTests(SimpleTestCase):
    def test_the_real_leak_is_redacted(self):
        """The shape of the message that appeared on the health page.

        The key here is SYNTHETIC. This test was first written with the
        real one pasted in verbatim — "the exact message" — which put a
        live credential into a public repository, in the very commit
        that fixed the leak it came from. A fixture only has to have the
        right SHAPE; it never has to be real, and a test that needs a
        working secret to be meaningful is a test to rewrite.
        """
        from core.secret_scrub import scrub
        msg = ("403 Client Error: Forbidden for url: "
               "https://financialmodelingprep.com/api/v3/earning_calendar"
               "?from=2026-08-27&to=2026-09-10&apikey=SYNTHETIC0KEY0FOR0THIS0TEST0")
        out = scrub(msg)
        self.assertNotIn("SYNTHETIC0KEY0FOR0THIS0TEST0", out)
        self.assertIn("apikey=***", out)

    def test_the_rest_of_the_message_survives(self):
        """A redacted message that says nothing is a lost failure."""
        from core.secret_scrub import scrub
        out = scrub("403 Client Error: Forbidden for url: "
                    "https://x.com/v3/earning_calendar?apikey=abcd1234efgh")
        self.assertIn("403", out)
        self.assertIn("Forbidden", out)
        self.assertIn("earning_calendar", out)

    def test_every_common_credential_param_name(self):
        from core.secret_scrub import scrub
        for name in ("apikey", "api_key", "api-key", "token", "access_token",
                     "secret", "client_secret", "password", "signature"):
            out = scrub(f"https://x.com/a?{name}=SUPERSECRETVALUE1")
            self.assertNotIn("SUPERSECRETVALUE1", out, name)

    def test_a_bearer_header_is_redacted(self):
        from core.secret_scrub import scrub
        out = scrub("Authorization: Bearer 10d2e6056c609a3003a475f56854")
        self.assertNotIn("10d2e6056c609a3003a475f56854", out)
        self.assertIn("Bearer ***", out)

    def test_innocent_text_is_untouched(self):
        """Over-redaction loses the diagnosis, which is the other way to
        fail here."""
        from core.secret_scrub import scrub
        msg = "no secrets here, just a 403 for /api/v3/earning_calendar"
        self.assertEqual(scrub(msg), msg)

    def test_a_keyword_parameter_is_not_a_key(self):
        from core.secret_scrub import scrub
        self.assertIn("keyword=bitcoin", scrub("https://x.com/a?keyword=bitcoin"))

    def test_it_never_raises(self):
        """This runs on the error path — a scrubber that throws while
        recording a failure loses the failure as well as leaking it."""
        from core.secret_scrub import scrub
        for bad in (None, 12345, object(), b"bytes"):
            self.assertIsInstance(scrub(bad), str)

    def test_a_declared_secret_is_removed_anywhere(self):
        import os
        from core.secret_scrub import scrub
        os.environ["TESTVENDOR_API_KEY"] = "zzTOPSECRETzz9999"
        try:
            out = scrub("upstream said: zzTOPSECRETzz9999 is invalid")
            self.assertNotIn("zzTOPSECRETzz9999", out)
        finally:
            os.environ.pop("TESTVENDOR_API_KEY", None)


class TheComponentRowNeverStoresOneTests(TestCase):
    def test_mark_run_scrubs_before_storing(self):
        from core.platform_control import PlatformComponent
        c = PlatformComponent.objects.create(
            key="test_scrub", name="Test", category="ingest")
        c.mark_run(success=False,
                   message="403 for url: https://x.com/a?apikey=LIVEKEY12345")
        c.refresh_from_db()
        self.assertNotIn("LIVEKEY12345", c.last_message)
        self.assertIn("403", c.last_message)

    def test_a_healthy_message_is_unchanged(self):
        from core.platform_control import PlatformComponent
        c = PlatformComponent.objects.create(
            key="test_ok", name="Test", category="ingest")
        c.mark_run(success=True, message="stored 42 rows")
        c.refresh_from_db()
        self.assertEqual(c.last_message, "stored 42 rows")
