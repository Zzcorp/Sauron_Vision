"""One unavailable pair killed the whole forex feed.

The production log, 2026-08-28, once per minute for hours:

    oanda disconnected: 400, message='Bad Request',
    url='.../pricing/stream?instruments=AUD_CAD,AUD_CHF,...,CHF_HUF,...,
    USD_CNH,USD_CZK,USD_RON,USD_TRY,USD_ZAR,ZAR_JPY'

The credentials were perfect — a direct call to the account summary
returned 200. The streamer was running, reconnecting on schedule, and
subscribing to all 47 forex pairs in the catalogue. OANDA rejects the
ENTIRE subscription if any single instrument is unavailable to the
account, and answers with a bare 400 that names no culprit. A demo
account — a US one especially, where CFTC rules cut the list hard — does
not carry CHF_HUF or USD_RON.

So: nothing ever arrived, the health panel said `never`, and the three
things an operator would check first (key, account id, container) were all
fine.

The fix asks the account what it carries before subscribing, and — for the
case where that lookup itself fails — makes the 400 say what was asked for.

Run with:  python manage.py test tests.test_oanda_subscription
"""
from unittest.mock import AsyncMock, MagicMock

from django.test import SimpleTestCase, TestCase


class _Resp:
    def __init__(self, status=200, payload=None):
        self.status = status
        self._payload = payload

    async def json(self):
        return self._payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _Session:
    """Just enough aiohttp to exercise the lookup."""

    def __init__(self, resp):
        self._resp = resp
        self.calls = []

    def get(self, url, **kw):
        self.calls.append(url)
        return self._resp


class TheAccountIsAskedWhatItCarriesTests(SimpleTestCase):

    def _run(self, coro):
        import asyncio
        return asyncio.run(coro)

    def test_it_returns_the_names_the_account_may_stream(self):
        from market_data.management.commands.stream_oanda import (
            account_instruments,
        )
        payload = {"instruments": [{"name": "EUR_USD"}, {"name": "USD_JPY"}]}
        sess = _Session(_Resp(200, payload))
        got = self._run(account_instruments(sess, "https://api", "101-1"))
        self.assertEqual(got, {"EUR_USD", "USD_JPY"})
        self.assertIn("/v3/accounts/101-1/instruments", sess.calls[0])

    def test_a_failed_lookup_answers_None_not_an_empty_set(self):
        """None means "could not ask", and the caller then subscribes to
        the catalogue as before. An empty set would read as "this account
        carries nothing" and turn a working feed off."""
        from market_data.management.commands.stream_oanda import (
            account_instruments,
        )
        sess = _Session(_Resp(403, None))
        self.assertIsNone(
            self._run(account_instruments(sess, "https://api", "101-1")))

    def test_an_empty_instrument_list_is_also_None(self):
        from market_data.management.commands.stream_oanda import (
            account_instruments,
        )
        sess = _Session(_Resp(200, {"instruments": []}))
        self.assertIsNone(
            self._run(account_instruments(sess, "https://api", "101-1")))

    def test_it_never_raises_into_the_stream_loop(self):
        from market_data.management.commands.stream_oanda import (
            account_instruments,
        )
        sess = MagicMock()
        sess.get.side_effect = RuntimeError("dns")
        self.assertIsNone(
            self._run(account_instruments(sess, "https://api", "101-1")))


class TheSubscriptionIsBoundedTests(SimpleTestCase):
    """OANDA caps a single pricing stream, and the catalogue is 47 pairs."""

    def test_the_cap_is_declared_and_below_the_catalogue_size(self):
        from market_data.management.commands.stream_oanda import STREAM_CHUNK
        self.assertGreater(STREAM_CHUNK, 0)
        self.assertLess(STREAM_CHUNK, 47)


class TheRefusalNamesWhatItAskedForTests(SimpleTestCase):
    """OANDA's 400 names no culprit. If the platform does not say what it
    asked for, the operator has a dead feed and no thread to pull."""

    def _source(self):
        from pathlib import Path

        from django.conf import settings
        return (Path(settings.BASE_DIR) / "market_data" / "management"
                / "commands" / "stream_oanda.py").read_text(encoding="utf-8")

    def test_a_400_logs_the_instruments_and_the_body(self):
        src = self._source()
        self.assertIn("REFUSED the subscription (400)", src)
        self.assertIn('", ".join(instruments)', src)

    def test_dropped_pairs_are_named_not_counted(self):
        """"38 of 47" tells an operator nothing they can act on; the list
        tells them whether the catalogue or the account is wrong."""
        src = self._source()
        self.assertIn("were dropped", src)
        self.assertIn('", ".join(sorted(dropped))', src)

    def test_a_400_forces_the_instrument_list_to_be_re_read(self):
        """Otherwise a stale `allowed` set would keep proposing the same
        rejected subscription on every reconnect, forever."""
        src = self._source()
        i = src.find("REFUSED the subscription (400)")
        self.assertGreater(i, 0)
        self.assertIn("allowed = None", src[i:i + 400])

    def test_an_account_carrying_nothing_says_so_rather_than_looping(self):
        src = self._source()
        self.assertIn("can stream NONE of the", src)


class TheStreamSpendsItsSlotsOnWhatTheBotsTradeTests(TestCase):
    """Order is load-bearing, not cosmetic: a single OANDA pricing stream
    is capped, so whatever the ordering leaves last is what gets dropped."""

    def setUp(self):
        from decimal import Decimal

        from django.contrib.auth.models import User
        from bot_program.models import AssetBotConfig
        from instruments.models import Instrument

        for sym in ("EURUSD", "GBPUSD", "USDJPY", "AUDCAD", "CHFHUF",
                    "EURPLN", "USDTRY"):
            Instrument.objects.get_or_create(
                symbol=sym, defaults={"name": sym, "asset_class": "forex",
                                      "is_active": True})
        user = User.objects.create_user("oanda_order_u", password="x")
        AssetBotConfig.objects.create(
            user=user, asset_class="forex", name="FX", mode="paper",
            symbols=["EURUSD", "GBPUSD", "USDJPY"],
            capital=Decimal("10000"), enabled=True)

    def _discover(self, override=None):
        """Calls the wrapped SYNC function, not the async wrapper.

        `sync_to_async` runs its target in a thread-pool executor, and that
        thread gets its OWN database connection — which cannot see the
        uncommitted transaction a Django TestCase wraps each test in. Going
        through the wrapper made every query return nothing, the try block
        fall through to the hardcoded fallback list, and the test assert
        against four pairs that came from an except branch.
        """
        from market_data.management.commands.stream_oanda import (
            discover_instruments,
        )
        return discover_instruments.func(override)

    def test_the_fleets_pairs_come_first(self):
        got = self._discover()
        self.assertEqual(set(got[:3]), {"EUR_USD", "GBP_USD", "USD_JPY"})

    def test_the_exotics_come_last_and_are_the_first_to_be_cut(self):
        """Alphabetically AUD_CAD and CHF_HUF beat GBP_USD and USD_JPY, so
        an alphabetical cap streamed the pairs nobody trades."""
        got = self._discover()
        self.assertLess(got.index("USD_JPY"), got.index("CHF_HUF"))
        self.assertLess(got.index("GBP_USD"), got.index("AUD_CAD"))

    def test_a_pair_no_config_watches_is_still_included(self):
        """It is the first thing to lose, not excluded outright."""
        self.assertIn("USD_TRY", self._discover())

    def test_the_catalogue_symbols_are_converted_to_oanda_form(self):
        for pair in self._discover():
            self.assertIn("_", pair)

    def test_an_override_still_wins_outright(self):
        self.assertEqual(self._discover(["eur_usd"]), ["EUR_USD"])

    def test_it_is_not_silently_falling_back(self):
        """The fallback list is exactly four majors, so a test asserting
        "EUR_USD comes first" passes just as well when every query failed.
        This is the guard that tells the two apart."""
        got = self._discover()
        self.assertGreater(len(got), 4, "this is the hardcoded fallback")
        self.assertIn("CHF_HUF", got)
