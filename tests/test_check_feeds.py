"""A command that answers "why is this feed quiet?".

The health panel says WHAT the state is — `never`, `idle`, `red`. It cannot
say WHY, because it only reads the quote table and a feed that has never
written leaves nothing there to read.

That gap had a cost. On 2026-08-28 the operator supplied OANDA credentials,
redeployed, and the panel still said `never` — with no way to tell from the
platform whether the container was down, the token was for the wrong
environment, the market was shut, or ticks were arriving and being dropped.
Four very different next moves, one word on screen.

Run with:  python manage.py test tests.test_check_feeds
"""
import os
from contextlib import contextmanager
from io import StringIO
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.test import TestCase


@contextmanager
def _env(**pairs):
    saved = {k: os.environ.get(k) for k in pairs}
    try:
        for k, v in pairs.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _run(feed):
    out = StringIO()
    call_command("check_feeds", f"--feed={feed}", stdout=out, stderr=out)
    return out.getvalue()


class ItStopsAtTheFirstThingThatIsWrongTests(TestCase):

    def test_no_credentials_reports_off_and_probes_nothing(self):
        """Not switched on is not broken, and there is nothing to ask the
        vendor about."""
        with _env(OANDA_API_KEY=None, OANDA_ACCOUNT_ID=None), \
                patch("requests.get") as g:
            body = _run("oanda_stream")
        g.assert_not_called()
        self.assertIn("not configured", body)
        self.assertIn("OFF", body)

    def test_a_refused_key_stops_before_the_market_and_delivery_checks(self):
        """No point reporting an empty quote table when the vendor is
        rejecting the credentials."""
        r = MagicMock(status_code=401)
        with _env(OANDA_API_KEY="k", OANDA_ACCOUNT_ID="1"), \
                patch("requests.get", return_value=r):
            body = _run("oanda_stream")
        self.assertIn("refused", body)
        self.assertNotIn("delivery", body)

    def test_a_wrong_environment_token_is_named_as_the_likely_cause(self):
        """The commonest real cause and invisible from the panel: a
        practice token against the live host, or the reverse. OANDA answers
        401 either way."""
        r = MagicMock(status_code=401)
        with _env(OANDA_API_KEY="k", OANDA_ACCOUNT_ID="1",
                  OANDA_ENV="practice"), \
                patch("requests.get", return_value=r):
            body = _run("oanda_stream")
        self.assertIn("OANDA_ENV=live", body)

    def test_a_good_key_with_no_ticks_names_the_profile_flag(self):
        """The actual answer for this deployment: `up -d` does not start a
        profiled service, so the streamer was never launched."""
        r = MagicMock(status_code=200)
        r.json.return_value = {"account": {}}
        with _env(OANDA_API_KEY="k", OANDA_ACCOUNT_ID="1"), \
                patch("requests.get", return_value=r):
            body = _run("oanda_stream")
        self.assertIn("NEVER written", body)
        self.assertIn("--profile streamers", body)
        self.assertIn("stream-oanda", body)


class ItKnowsWhenSilenceIsCorrectTests(TestCase):

    def test_a_closed_market_is_reported_as_such(self):
        """A silent Finnhub at 05:00 ET is the system working."""
        from datetime import datetime
        from zoneinfo import ZoneInfo
        r = MagicMock(status_code=200)
        r.json.return_value = {"c": 100.0}
        night = datetime(2026, 8, 28, 5, 0, tzinfo=ZoneInfo("America/New_York"))
        with _env(FINNHUB_API_KEY="k"), \
                patch("requests.get", return_value=r), \
                patch("django.utils.timezone.now", return_value=night):
            body = _run("finnhub_ws")
        self.assertIn("CLOSED", body)
        self.assertIn("idle", body)

    def test_it_changes_nothing(self):
        """A diagnostic that writes is a diagnostic nobody dares run on
        production."""
        from market_data.models import LiveQuote
        before = LiveQuote.objects.count()
        with _env(OANDA_API_KEY=None, OANDA_ACCOUNT_ID=None):
            _run("oanda_stream")
        self.assertEqual(LiveQuote.objects.count(), before)

    def test_an_unknown_feed_name_lists_the_real_ones(self):
        out = StringIO()
        call_command("check_feeds", "--feed=nonsense", stdout=out, stderr=out)
        body = out.getvalue()
        self.assertIn("Declared:", body)
        self.assertIn("oanda_stream", body)

    def test_a_probe_that_raises_does_not_crash_the_command(self):
        with _env(OANDA_API_KEY="k", OANDA_ACCOUNT_ID="1"), \
                patch("requests.get", side_effect=RuntimeError("no dns")):
            body = _run("oanda_stream")
        self.assertIn("probe failed", body)
