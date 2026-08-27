"""The feed panel reports the feeds, not the rows.

The operator's report: "finnhub is in red and oanda is not shown in the live
popup with yfinance in green and binance too". Two different bugs wearing one
symptom.

`/api/live/health/` built its list by grouping `LiveQuote.source` over the
rows that happened to exist. `LiveQuote` is ONE row per instrument with a
single `source` column the winning writer overwrites, so that list was really
"which feed last won a write somewhere" — and it could not express any of the
three states that actually matter:

  * OANDA has no credentials on this deployment, so its streamer returns
    before its first network call, so no row ever bears `oanda_stream`, so
    the panel showed NOTHING. A feed that has never run rendered as silence
    while a merely stale one at least showed red.
  * Finnhub writes on US equity trade prints and nothing else. It is red
    every night, all weekend and every holiday, by design. A panel that
    cries wolf nightly is one nobody reads on the morning it means it.
  * A feed streaming perfectly but outranked on every instrument it covers
    holds no rows at all — `binance_public` vanishes the moment
    `binance_ws` connects, while doing exactly its job.

Run with:  python manage.py test tests.test_feed_registry
"""
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.utils import timezone


class TheRegistryIsDeclaredNotDerivedTests(SimpleTestCase):

    def test_every_writer_in_the_codebase_is_declared(self):
        """Every source string a WRITER actually stamps must be declared.

        The list is the writers, not `SOURCE_PRIORITY`. The first version of
        this test also asserted `fmp`, `oanda`, `alpaca` and `twelve_data` —
        which sit in the priority table and which NO code path writes — and
        declaring them was a blocker, not untidiness: `binance` needs no
        credentials, so it read as configured on every install, sat
        permanently in `never`, and made the top-bar pill unable to reach
        green on any deployment at all.
        """
        from market_data.feeds import BY_KEY
        for key in ("binance_ws", "oanda_stream", "finnhub_ws", "ibkr",
                    "yfinance", "binance_public", "alpha_vantage",
                    "coingecko", "etoro"):
            self.assertIn(key, BY_KEY, f"{key} is written but not declared")

    def test_nothing_is_declared_that_no_writer_stamps(self):
        """The other direction, and the one that was the blocker."""
        from market_data.feeds import BY_KEY
        for ghost in ("binance", "oanda", "alpaca", "twelve_data", "fmp"):
            self.assertNotIn(
                ghost, BY_KEY,
                f"{ghost} is declared but nothing writes it — it would sit "
                f"in `never` forever and hold the pill off green")

    def test_each_feed_carries_an_operator_facing_label(self):
        """The panel used to print the raw column value, so an operator read
        `finnhub_ws` and `oanda_stream` — internal identifiers."""
        from market_data.feeds import FEEDS
        for f in FEEDS:
            self.assertTrue(f["label"])
            self.assertNotIn("_ws", f["label"])
            self.assertNotIn("_stream", f["label"])

    def test_freshness_tolerances_are_per_feed(self):
        """One global 60s/600s pair was calibrated for a websocket and
        applied to a ten-minute poller."""
        from market_data.feeds import BY_KEY
        stream = BY_KEY["binance_ws"]["ages"]
        poller = BY_KEY["yfinance"]["ages"]
        self.assertLess(stream[0], poller[0])


class NotSwitchedOnIsNotBrokenTests(SimpleTestCase):

    def _feed(self, key):
        from market_data.feeds import BY_KEY
        return BY_KEY[key]

    def test_a_feed_without_credentials_reports_off_not_red(self):
        """A panel that shouts about a feed nobody wants trains its reader
        to ignore it."""
        from market_data.feeds import state_for
        with self.settings():
            import os
            saved = {k: os.environ.pop(k, None)
                     for k in ("OANDA_API_KEY", "OANDA_ACCOUNT_ID")}
            try:
                state, note = state_for(self._feed("oanda_stream"),
                                        latest=None, age_seconds=None,
                                        superseder_ok=False)
            finally:
                for k, v in saved.items():
                    if v is not None:
                        os.environ[k] = v
        self.assertEqual(state, "off")
        self.assertIn("OANDA_API_KEY", note)

    def test_an_empty_env_var_is_not_a_credential(self):
        """`FINNHUB_API_KEY=` with nothing after it sets the variable. A
        bare presence check would call the feed configured and then report
        it red forever for failing on a key it never had."""
        import os

        from market_data.feeds import is_configured
        saved = os.environ.get("FINNHUB_API_KEY")
        os.environ["FINNHUB_API_KEY"] = "   "
        try:
            self.assertFalse(is_configured(self._feed("finnhub_ws")))
        finally:
            if saved is None:
                os.environ.pop("FINNHUB_API_KEY", None)
            else:
                os.environ["FINNHUB_API_KEY"] = saved

    def test_off_and_idle_do_not_colour_the_pill(self):
        from market_data.feeds import BENIGN_STATES
        self.assertIn("off", BENIGN_STATES)
        self.assertIn("idle", BENIGN_STATES)
        self.assertIn("yielding", BENIGN_STATES)


class AClosedMarketIsNotAFaultTests(SimpleTestCase):
    """Finnhub goes red every single night by design — it writes on US
    equity trade prints and nothing else."""

    def _at_et(self, y, m, d, h, minute=0):
        return datetime(y, m, d, h, minute,
                        tzinfo=ZoneInfo("America/New_York"))

    def test_the_us_session_window_is_open_midday(self):
        from market_data.feeds import Window, window_is_open
        self.assertTrue(window_is_open(Window.US_EQUITY,
                                       self._at_et(2026, 8, 26, 11, 0)))

    def test_it_is_closed_in_the_evening(self):
        from market_data.feeds import Window, window_is_open
        self.assertFalse(window_is_open(Window.US_EQUITY,
                                        self._at_et(2026, 8, 26, 20, 0)))

    def test_it_is_closed_at_the_weekend(self):
        from market_data.feeds import Window, window_is_open
        self.assertFalse(window_is_open(Window.US_EQUITY,
                                        self._at_et(2026, 8, 29, 11, 0)))

    def test_crypto_is_always_open(self):
        from market_data.feeds import Window, window_is_open
        self.assertTrue(window_is_open(Window.ALWAYS,
                                       self._at_et(2026, 8, 29, 3, 0)))

    def test_a_stale_finnhub_at_night_is_idle_not_red(self):
        """The whole point of the report. A healthy Finnhub is four hours
        stale at 20:00 ET and must not be indistinguishable from a dead
        one."""
        import os

        from market_data.feeds import BY_KEY, state_for
        saved = os.environ.get("FINNHUB_API_KEY")
        os.environ["FINNHUB_API_KEY"] = "present"
        try:
            night = self._at_et(2026, 8, 26, 20, 0)
            state, note = state_for(
                BY_KEY["finnhub_ws"], latest=night - timedelta(hours=4),
                age_seconds=14400, superseder_ok=False, now=night)
        finally:
            if saved is None:
                os.environ.pop("FINNHUB_API_KEY", None)
            else:
                os.environ["FINNHUB_API_KEY"] = saved
        self.assertEqual(state, "idle")
        self.assertIn("closed", note)

    def test_a_finnhub_that_died_during_the_session_is_red_that_night(self):
        """`idle` forgives silence, so it must not become the second place a
        dead feed can hide. A stream that dropped at 09:40 is not made
        healthy by the 16:00 close — and no DURATION bound can say so, since
        an ordinary overnight gap is seventeen hours and a weekend sixty-five.
        """
        import os

        from market_data.feeds import BY_KEY, state_for
        saved = os.environ.get("FINNHUB_API_KEY")
        os.environ["FINNHUB_API_KEY"] = "present"
        try:
            night = self._at_et(2026, 8, 26, 20, 0)
            state, note = state_for(
                BY_KEY["finnhub_ws"],
                latest=self._at_et(2026, 8, 26, 9, 40),
                age_seconds=37200, superseder_ok=False, now=night)
        finally:
            if saved is None:
                os.environ.pop("FINNHUB_API_KEY", None)
            else:
                os.environ["FINNHUB_API_KEY"] = saved
        self.assertEqual(state, "red")
        self.assertIn("during the session", note)

    def test_the_idle_bound_is_the_markets_own_clock(self):
        from market_data.feeds import Window, window_last_closed
        closed = window_last_closed(Window.US_EQUITY,
                                    self._at_et(2026, 8, 26, 20, 0))
        self.assertEqual((closed.hour, closed.day), (16, 26))
        # Sunday looks back to Friday, never to Saturday.
        sun = window_last_closed(Window.US_EQUITY,
                                 self._at_et(2026, 8, 30, 12, 0))
        self.assertEqual(sun.weekday(), 4)
        # A market that never shuts has no last close to measure against.
        self.assertIsNone(window_last_closed(Window.ALWAYS,
                                             self._at_et(2026, 8, 30, 12, 0)))

    def test_but_a_stale_finnhub_during_the_session_is_red(self):
        """Idle must not become an excuse that hides a genuinely dead feed."""
        import os

        from market_data.feeds import BY_KEY, state_for
        saved = os.environ.get("FINNHUB_API_KEY")
        os.environ["FINNHUB_API_KEY"] = "present"
        try:
            midday = self._at_et(2026, 8, 26, 11, 0)
            state, _ = state_for(
                BY_KEY["finnhub_ws"], latest=midday - timedelta(hours=3),
                age_seconds=10800, superseder_ok=False, now=midday)
        finally:
            if saved is None:
                os.environ.pop("FINNHUB_API_KEY", None)
            else:
                os.environ["FINNHUB_API_KEY"] = saved
        self.assertEqual(state, "red")


class TheThreeSilencesAreNowDistinctTests(SimpleTestCase):

    def test_configured_but_never_delivered_is_its_own_state(self):
        """The loudest state on the panel: a thing the operator switched on
        that has never once worked."""
        from market_data.feeds import BY_KEY, state_for
        state, note = state_for(BY_KEY["binance_ws"], latest=None,
                                age_seconds=None, superseder_ok=False)
        self.assertEqual(state, "never")
        self.assertIn("never", note)

    def test_running_but_outranked_is_yielding_not_missing(self):
        """`binance_public` vanished the moment `binance_ws` connected,
        while doing exactly its job.

        It has never written a row of its OWN — SOURCE_PRIORITY refuses
        every write while the stream holds the instrument — so `latest` is
        None, and the first version of this could not tell it from a dead
        feed: its `holds_rows` flag and `latest` were derived from the same
        GROUP BY by the only caller, so they were one condition and the
        `yielding` branch was unreachable. What settles it is whether the
        SUPERSEDER is fresh, which is a question the data can answer.
        """
        from market_data.feeds import BY_KEY, state_for
        now = timezone.now()
        state, note = state_for(
            BY_KEY["binance_public"], latest=None, age_seconds=None,
            superseder_ok=True, now=now)
        self.assertEqual(state, "yielding")
        self.assertIn("binance_ws", note)

    def test_but_with_the_stream_down_it_is_not_forgiven(self):
        """`yielding` must not become a second place for a dead feed to
        hide. With nothing outranking it, silence is silence."""
        from market_data.feeds import BY_KEY, state_for
        state, _ = state_for(BY_KEY["binance_public"], latest=None,
                             age_seconds=None, superseder_ok=False)
        self.assertEqual(state, "never")

    def test_a_fresh_feed_is_green(self):
        from market_data.feeds import BY_KEY, state_for
        now = timezone.now()
        state, _ = state_for(BY_KEY["binance_ws"], latest=now,
                             age_seconds=5, superseder_ok=False, now=now)
        self.assertEqual(state, "green")


class TheEndpointAnswersForEveryDeclaredFeedTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("feed_u", password="x")
        self.client.force_login(self.user)

    def test_oanda_appears_even_having_never_written(self):
        """The operator's actual complaint: it was not shown at all."""
        res = self.client.get("/api/live/health/")
        keys = [s["source"] for s in res.json()["sources"]]
        self.assertIn("oanda_stream", keys)

    def test_every_declared_feed_gets_a_row(self):
        from market_data.feeds import FEEDS
        res = self.client.get("/api/live/health/")
        keys = {s["source"] for s in res.json()["sources"]}
        for f in FEEDS:
            self.assertIn(f["key"], keys)

    def test_a_source_the_registry_does_not_know_is_shown_not_dropped(self):
        """It means the registry has fallen behind the writers, and hiding
        it is how it stays behind."""
        from instruments.models import Instrument
        from market_data.models import LiveQuote
        inst, _ = Instrument.objects.get_or_create(
            symbol="ZZTEST", defaults={"name": "Z", "asset_class": "stock"})
        LiveQuote.objects.create(instrument=inst, last=Decimal("1"),
                                 source="some_new_feed")
        rows = {s["source"]: s for s in
                self.client.get("/api/live/health/").json()["sources"]}
        self.assertIn("some_new_feed", rows)
        self.assertEqual(rows["some_new_feed"]["state"], "unregistered")

    def test_the_server_decides_the_pill(self):
        """The client used to derive it with a pessimistic dot and an
        optimistic label, so one green feed among five red ones painted a
        red dot beside the word LIVE."""
        body = self.client.get("/api/live/health/").json()
        self.assertIn("pill", body)
        self.assertIn("pill_state", body)

    def test_every_row_carries_a_label_and_a_reason(self):
        for s in self.client.get("/api/live/health/").json()["sources"]:
            self.assertTrue(s["label"], s)
            self.assertIn("configured", s)
            self.assertIn("state", s)

    def test_the_popup_no_longer_derives_the_pill_itself(self):
        from pathlib import Path

        from django.conf import settings
        src = (Path(settings.BASE_DIR) / "templates" / "base.html"
               ).read_text(encoding="utf-8")
        self.assertNotIn("var hasGreen=srcs.some", src)
        self.assertIn("d.pill_state", src)

    def test_the_popup_escapes_what_it_prints(self):
        """`source` is a free-form CharField with no choices, concatenated
        into innerHTML."""
        from pathlib import Path

        from django.conf import settings
        src = (Path(settings.BASE_DIR) / "templates" / "base.html"
               ).read_text(encoding="utf-8")
        self.assertIn("esc(s.label||s.source)", src)

    def test_every_state_has_a_colour(self):
        """Any state outside green/yellow/red used to yield an undefined
        class — an 8px transparent dot, an invisible status."""
        from pathlib import Path

        from django.conf import settings
        css = (Path(settings.BASE_DIR) / "static" / "css" / "sauron.css"
               ).read_text(encoding="utf-8")
        for state in ("off", "idle", "yielding", "never", "unregistered"):
            self.assertIn(f".lsp-{state}", css, state)
