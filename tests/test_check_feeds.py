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
        self.assertIn("never written", body.lower())
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
        # No quotes at all AND the market shut: `never` is still the
        # right answer — a feed that has never delivered has not been
        # excused by the closing bell.
        self.assertIn("NEVER", body)

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


class OneVerdictNotTwoTests(TestCase):
    """The command reimplemented the panel's judgement and the copy was
    wrong within a day. From the operator's real output:

        [ skip ] market   CLOSED right now — silence here is correct
        [ FAIL ] verdict  ...but the market is open, and the ticks stopped.

    Two lines, one screen, flatly contradicting each other. It also called
    alpha_vantage and coingecko "has NEVER written" while both were
    legitimately yielding to a stream that was delivering at 0s old, and
    told the operator to go read the logs of containers behaving perfectly.
    """

    def _quote(self, source, symbol, ago_seconds=0):
        from datetime import timedelta
        from decimal import Decimal

        from django.utils import timezone
        from instruments.models import Instrument
        from market_data.models import LiveQuote
        inst, _ = Instrument.objects.get_or_create(
            symbol=symbol, defaults={"name": symbol,
                                     "asset_class": "crypto"})
        q = LiveQuote.objects.create(instrument=inst, last=Decimal("1"),
                                     source=source)
        if ago_seconds:
            LiveQuote.objects.filter(pk=q.pk).update(
                updated_at=timezone.now() - timedelta(seconds=ago_seconds))
        return q

    def test_a_superseded_feed_reports_yielding_not_never(self):
        """CoinGecko writing nothing while the Binance stream is fresh is
        the fallback being correctly unused, not a fault."""
        self._quote("binance_ws", "BTCUSD")
        body = _run("coingecko")
        self.assertIn("YIELDING", body)
        self.assertNotIn("NEVER", body)

    def test_but_with_the_superseder_dead_it_is_never_again(self):
        """`yielding` must not become a second place for a dead feed to
        hide."""
        self._quote("binance_ws", "BTCUSD", ago_seconds=9999)
        body = _run("coingecko")
        self.assertIn("NEVER", body)

    def test_a_closed_market_never_prints_a_contradiction(self):
        """The exact defect: a verdict claiming the market is open under a
        line saying it is closed."""
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo
        night = datetime(2026, 8, 28, 5, 0,
                         tzinfo=ZoneInfo("America/New_York"))
        r = MagicMock(status_code=200)
        r.json.return_value = {"c": 100.0}
        with _env(FINNHUB_API_KEY="k"), \
                patch("requests.get", return_value=r), \
                patch("django.utils.timezone.now", return_value=night):
            # AFTER the 16:00 ET close, so the feed was alive when the
            # market shut. Fourteen hours would be 15:00 ET — mid-session —
            # and `idle` deliberately refuses to excuse that: a stream that
            # died during the session is red, closing bell or not.
            self._quote("finnhub_ws", "AAPL",
                        ago_seconds=int(timedelta(hours=12).total_seconds()))
            body = _run("finnhub_ws")
        self.assertIn("IDLE", body)
        self.assertNotIn("market is open", body)

    def test_the_verdict_is_the_panels_own_state_vocabulary(self):
        """Not a second set of words that can drift from the first."""
        from market_data.feeds import BENIGN_STATES
        self._quote("binance_ws", "BTCUSD")
        body = _run("binance_ws")
        self.assertIn("GREEN", body)
        self.assertTrue(any(s in ("off", "idle", "yielding")
                            for s in BENIGN_STATES))


class IbkrIsConfiguredByARowNotAnEnvVarTests(TestCase):
    """IBKR has no API key — it needs a host, a port and a logged-in
    Gateway, which live in an IBKRAccount row. Declared with no `requires`,
    `is_configured` was unconditionally true, so every deployment that has
    never set IBKR up saw the loudest state on the panel for a thing nobody
    asked for."""

    def test_with_no_account_row_it_is_off(self):
        body = _run("ibkr")
        self.assertIn("no IBKRAccount configured", body)
        self.assertIn("OFF", body)

    def test_with_a_row_it_is_judged_like_any_other_feed(self):
        from django.contrib.auth.models import User
        from bot_program.models import IBKRAccount
        user = User.objects.create_user("ibkr_cfg_u", password="x")
        IBKRAccount.objects.create(user=user, host="ibgateway", port=4002)
        body = _run("ibkr")
        self.assertNotIn("OFF", body)
        self.assertIn("NEVER", body)

    def test_the_advice_names_the_admin_page_not_a_profile_flag(self):
        """A feed configured by a row cannot be fixed with --profile."""
        from django.contrib.auth.models import User
        from bot_program.models import IBKRAccount
        user = User.objects.create_user("ibkr_cfg_u2", password="x")
        IBKRAccount.objects.create(user=user, host="ibgateway", port=4002)
        body = _run("ibkr")
        self.assertIn("admin-dashboard", body)
