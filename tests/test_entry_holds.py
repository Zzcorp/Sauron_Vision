"""THE ENTRY SIDE HOLDS ON A SICK VENUE, A 429 PAUSE AND A KEPT "NO"
(2026-10-07, PR50; bot_program/asset_engine/base.py).

On 2026-10-06 eToro's live world went SICK at 23:38:34 UTC on seven /search
429s in one second. The sick check sat in execute_entry alone, so every
candidate of the quiet still asked eToro for its rate (and the /search a
cold id costs) in propose_entry, only to be held at execute — and each 429
among those asks pushed the quiet further. Now, keyed on the adapter
(venue_health), so a MagicMock, a PaperTrader and a paper config propose
as before:
  * propose_entry asks nothing while the venue is sick, while THIS
    PROCESS's 429 pause for that world runs (venue_health.pause_s), or for
    a symbol eToro said twice it does not know (venue_health.kept_no);
  * execute_entry holds before the eligibility read inside the pause
    (NO_PRICE, "nothing sent"; the venue is not sick);
  * the last look that met eToro's 429, or failed inside the pause, sends
    nothing; every other unreadable last look still sends, as before —
    another carrier's 429 (OANDA, Alpaca) among them;
  * the venue's health is read again at the send.
The manage tick, closes, the reconcile, the kill switch, the manual lanes
and TAKE TRADE never read the pause or the "no".

The adapter's side (the pause, the "no", the background reads) is pinned
in tests/test_etoro_rate_pause.py, whose fixtures these borrow; the
execute fixture is tests.test_entry_quote.TheLastLookTests'.

Run with:  python manage.py test tests.test_entry_holds
"""
import inspect
from unittest import mock

import requests
from django.test import SimpleTestCase, TestCase

from bot_program import venue_health as vh
from bot_program.engine import etoro_client as ec
from tests.test_entry_quote import (POSTED, ROUTER, _account, _book, _etoro,
                                    _instrument, _live_cfg, _mock_client,
                                    _order_posts, _signal, _user)
from tests.test_etoro_client import SEARCH_AAPL, _client, _Resp
from tests.test_etoro_rate_pause import (RATES_429, RATES_OK, _hclient,
                                         _PauseOn)

STAFF = "bot_program.notifications.notify_staff"


class TheEntrySideTests(_PauseOn, TestCase):
    """A LIVE stock config, the REAL EtoroTrader over a fake wire
    (tests.test_entry_quote.TheLastLookTests' fixture). The demo key's
    world is "demo"."""

    def setUp(self):
        super().setUp()
        self.user = _user("rp_entry")
        self.cfg = _live_cfg(self.user, name="RP")
        self.cfg.base_currency = "USD"
        self.cfg.extras = {}
        self.cfg.save(update_fields=["base_currency", "extras"])
        _signal(_instrument(), rule="rp_rule")
        _book(self.user)
        _account(self.user, cash=100000)
        p = mock.patch("bot_program.asset_engine.base.ETORO_PROVEN",
                       frozenset({"stock"}))
        p.start()
        self.addCleanup(p.stop)

    def _bot(self):
        from bot_program.asset_engine.stock_bot import StockBot
        self.bot = StockBot(self.cfg)
        return self.bot

    def _cand(self):
        with mock.patch(ROUTER, return_value=_mock_client("100.00")):
            cand = self._bot().propose_entry("AAPL")
        self.assertIsNotNone(cand)
        return cand

    def _note(self):
        from bot_program.asset_engine import skips
        self.cfg.refresh_from_db()
        return skips.last_by_symbol(self.cfg)["AAPL"]

    def _execute(self, cand, t):
        with mock.patch(ROUTER, return_value=t), mock.patch("time.sleep"):
            return self.bot.execute_entry(cand)

    # ── the proposal ────────────────────────────────────────────────────

    def test_a_sick_venue_proposes_nothing_and_asks_no_rate(self):
        from bot_program.asset_engine import skips
        t, fake = _client([SEARCH_AAPL, RATES_OK])
        with mock.patch(STAFF):
            vh.note("etoro", "demo", "order", detail="in doubt: ReadTimeout")
        with mock.patch(ROUTER, return_value=t):
            self.assertIsNone(self._bot().propose_entry("AAPL"))
        self.assertEqual(fake.calls, [])
        note = self._note()
        self.assertEqual(note["code"], skips.VENUE_SICK)
        self.assertTrue(note["detail"].startswith(
            "AAPL: eToro (demo) is sick since "), note)
        self.assertTrue(note["detail"].endswith(" — nothing sent"), note)

    def test_a_mock_client_still_proposes_while_etoro_is_sick(self):
        with mock.patch(STAFF):
            vh.note("etoro", "demo", "order", code=503)
            vh.note("etoro", "live", "order", code=503)
        ec._RATE_PAUSE["demo"] = self.clock.t + 25
        ec._RATE_PAUSE["live"] = self.clock.t + 25
        self._cand()

    def test_a_paused_world_proposes_nothing_and_asks_nothing(self):
        from bot_program.asset_engine import skips
        t, fake = _client([SEARCH_AAPL, RATES_OK])
        ec._RATE_PAUSE["demo"] = self.clock.t + 25
        with mock.patch(ROUTER, return_value=t):
            self.assertIsNone(self._bot().propose_entry("AAPL"))
        self.assertEqual(fake.calls, [])
        note = self._note()
        self.assertEqual(note["code"], skips.NO_PRICE)
        self.assertEqual(note["detail"],
                         "eToro rate pause after a 429, 25s left — not asked")
        # the other world's pause holds nothing here (worlds never share)
        ec._RATE_PAUSE.clear()
        ec._RATE_PAUSE["live"] = self.clock.t + 25
        with mock.patch(ROUTER, return_value=t):
            self.assertIsNotNone(self._bot().propose_entry("AAPL"))
        self.assertTrue([c for c in fake.calls if "/rates" in c[1]])

    def test_a_kept_no_skips_the_proposal_without_a_wire_call(self):
        from bot_program.asset_engine import skips
        ec._SEARCH_NO[("demo", "AAPL")] = {
            "first": self.clock.t - 120, "kept": self.clock.t - 60,
            "words": "eToro knows no instrument spelled 'AAPL'",
            "lone_id": None, "lone_spelling": None}
        t, fake = _client([SEARCH_AAPL, RATES_OK])
        with mock.patch(ROUTER, return_value=t):
            self.assertIsNone(self._bot().propose_entry("AAPL"))
        self.assertEqual(fake.calls, [])
        note = self._note()
        self.assertEqual(note["code"], skips.NO_PRICE)
        self.assertTrue(note["detail"].startswith(
            "AAPL: eToro knows no instrument spelled 'AAPL' — eToro's "
            "answer twice; not asked again for "), note)

    # ── the order ───────────────────────────────────────────────────────

    def test_a_paused_world_holds_a_real_entry_before_the_eligibility_read(self):
        from bot_program.asset_engine import skips
        cand = self._cand()
        t, fake = _etoro()
        ec._RATE_PAUSE["demo"] = self.clock.t + 25
        self.assertIsNone(self._execute(cand, t))
        self.assertEqual(fake.calls, [])
        note = self._note()
        self.assertEqual(note["code"], skips.NO_PRICE)
        self.assertEqual(note["detail"], "AAPL: eToro rate pause after a "
                                         "429, 25s left — nothing sent")

    def test_a_last_look_500_inside_a_pause_is_not_called_a_429(self):
        from bot_program.asset_engine import skips
        cand = self._cand()
        t, fake = _etoro([SEARCH_AAPL, POSTED])
        err = requests.HTTPError("500 Server Error", response=_Resp(500))

        def _pause_then_500(*a, **k):
            ec._RATE_PAUSE["demo"] = self.clock.t + 20
            raise err
        with mock.patch.object(type(t), "ticker",
                               side_effect=_pause_then_500):
            self.assertIsNone(self._execute(cand, t))
        self.assertEqual(_order_posts(fake), [])
        note = self._note()
        self.assertEqual(note["code"], skips.NO_PRICE)
        self.assertEqual(note["detail"], "AAPL: the last look could not "
                                         "read the quote inside eToro's 429 "
                                         "pause (20s left) — nothing sent "
                                         "on the proposal's price")

    def test_a_last_look_that_meets_a_429_sends_nothing(self):
        from bot_program.asset_engine import skips
        cand = self._cand()
        t, fake = _etoro([SEARCH_AAPL, RATES_429, POSTED])
        self.assertIsNone(self._execute(cand, t))
        self.assertEqual(_order_posts(fake), [])
        note = self._note()
        self.assertEqual(note["code"], skips.NO_PRICE)
        # the fixture's _Resp raises without .response, so the 429 is read
        # off the pause this very read granted
        self.assertEqual(note["detail"], "AAPL: the last look could not "
                                         "read the quote inside eToro's 429 "
                                         "pause (30s left) — nothing sent "
                                         "on the proposal's price")

    def test_a_429_carried_on_the_raise_holds_even_with_the_pause_off(self):
        from bot_program.asset_engine import skips
        words = ("AAPL: the last look met eToro's 429 — nothing sent on the "
                 "proposal's price")
        cand = self._cand()
        t, fake = _etoro()
        err = requests.HTTPError("429 Client Error", response=_Resp(429))
        with mock.patch.object(ec, "RATE_PAUSE", False), \
                mock.patch.object(type(t), "ticker", side_effect=err):
            self.assertIsNone(self._execute(cand, t))
        self.assertEqual([c for c in fake.calls if "/orders" in c[1]], [])
        self.assertEqual(self._note()["code"], skips.NO_PRICE)
        self.assertEqual(self._note()["detail"], words)
        # the same over the wire: requests' own raise carries the 429
        # (tests.test_etoro_rate_pause._hclient), no pause is granted, and
        # the one refusal is noted, not yet a sick venue
        _, plain = _etoro([SEARCH_AAPL, RATES_429, POSTED])
        t, fake = _hclient(plain.routes, env="demo")
        with mock.patch.object(ec, "RATE_PAUSE", False):
            self.assertIsNone(self._execute(self._cand(), t))
        self.assertEqual(_order_posts(fake), [])
        self.assertEqual(len([c for c in fake.calls if "/rates" in c[1]]), 1)
        self.assertEqual(ec._RATE_PAUSE, {})
        self.assertEqual(self._note()["detail"], words)

    def test_a_sick_venue_after_an_unreadable_last_look_sends_nothing(self):
        from bot_program.asset_engine import skips
        cand = self._cand()
        t, fake = _etoro([SEARCH_AAPL, ("GET", "/rates", 500, {}), POSTED])

        def _sick_now(*a, **k):
            with mock.patch(STAFF):
                vh.note("etoro", "demo", "order", code=503)
            raise RuntimeError("HTTP 500")
        with mock.patch.object(type(t), "ticker", side_effect=_sick_now):
            self.assertIsNone(self._execute(cand, t))
        self.assertEqual(_order_posts(fake), [])
        self.assertEqual(self._note()["code"], skips.VENUE_SICK)

    def test_a_venue_turned_sick_before_the_send_holds_a_readable_order(self):
        from bot_program.asset_engine import skips
        cand = self._cand()
        t, fake = _etoro([SEARCH_AAPL, RATES_OK, POSTED])
        real = type(t).ticker

        def _sick_elsewhere(self_, symbol):
            with mock.patch(STAFF):
                vh.note("etoro", "demo", "order", detail="in doubt: x")
            return real(self_, symbol)
        with mock.patch.object(type(t), "ticker", _sick_elsewhere):
            self.assertIsNone(self._execute(cand, t))
        self.assertEqual(_order_posts(fake), [])
        note = self._note()
        self.assertEqual(note["code"], skips.VENUE_SICK)
        self.assertTrue(note["detail"].startswith(
            "AAPL: eToro (demo) is sick since "), note)

    def test_any_other_unreadable_last_look_still_sends(self):
        cand = self._cand()
        t, fake = _etoro([SEARCH_AAPL, ("GET", "/rates", 500, {}), POSTED])
        with mock.patch.object(type(t), "ticker",
                               side_effect=RuntimeError("x")):
            self.assertIsNotNone(self._execute(cand, t))
        self.assertEqual(len(_order_posts(fake)), 1)

    def test_another_carriers_429_at_the_last_look_still_sends(self):
        # (2026-10-07, review) the 429 hold is eToro's, keyed on the
        # adapter like the pause: a stock carried by Alpaca whose last look
        # met a 429 is sent on the proposal's price, as before PR50 — and
        # no row says eToro for it
        cand = self._cand()
        client = _named_mock("AlpacaTrader")
        client.ticker.side_effect = requests.HTTPError(
            "429 Client Error", response=_Resp(429))
        client.market_order.return_value = {
            "orderId": "ALP-1", "status": "FILLED", "executedQty": "1",
            "price": "100.00"}
        self.assertIsNotNone(self._execute(cand, client))
        self.assertTrue(client.ticker.called)
        self.assertEqual(client.market_order.call_count, 1)
        self.assertNotIn("AAPL", _skips(self.cfg))


def _named_mock(name):
    """A MagicMock whose CLASS is named `name`, so capabilities.adapter_key
    reads it as that carrier."""
    from tests.test_desk_seam import _client as _plain
    cls = type(name, (mock.MagicMock,), {})
    client = cls()
    client.ticker.return_value = _plain().ticker.return_value
    client.get_positions.return_value = []
    return client


def _skips(cfg):
    from bot_program.asset_engine import skips
    cfg.refresh_from_db()
    return skips.last_by_symbol(cfg)


class TheLastLook429IsEtorosTests(SimpleTestCase):
    """(2026-10-07, review) _last_look's 429 hold is keyed on the adapter:
    only eToro's 429 refuses (its pause and health memory are eToro's).
    OANDA and Alpaca call raise_for_status(), so their 429 also carries
    .response.status_code — it is any other unreadable look on a healthy
    venue, and the order goes, as before PR50."""

    def _look(self, client, symbol):
        from bot_program.asset_engine.base import AssetBot
        bot = mock.Mock(asset_class="forex")
        return AssetBot._last_look(bot, client, symbol, "BUY", 1.1, 1.09,
                                   1.12)

    def _429(self):
        return requests.HTTPError("429 Client Error", response=_Resp(429))

    def test_oanda_and_alpaca_429s_refuse_nothing(self):
        from bot_program.engine.alpaca_client import AlpacaTrader
        from bot_program.engine.oanda_client import OANDATrader
        for cls, client, symbol in (
                (OANDATrader, OANDATrader("k", "a", env="live"), "EURUSD"),
                (AlpacaTrader, AlpacaTrader("k", "s", env="live"), "AAPL")):
            with mock.patch.object(cls, "ticker", side_effect=self._429()):
                out = self._look(client, symbol)
            self.assertNotIn("refused", out, (cls.__name__, out))
            self.assertEqual(out, {"skip": "", "why": "", "quote": None})

    def test_an_unknown_carriers_429_refuses_nothing(self):
        client = mock.MagicMock()
        client.ticker.side_effect = self._429()
        self.assertNotIn("refused", self._look(client, "AAPL"))

    def test_etoros_429_still_refuses_in_etoros_words(self):
        client = _named_mock("EtoroTrader")
        client.rate_pause_s.return_value = 0
        client.ticker.side_effect = self._429()
        self.assertEqual(self._look(client, "AAPL")["refused"],
                         "AAPL: the last look met eToro's 429 — nothing sent "
                         "on the proposal's price")


class TheEngineReadsItTests(SimpleTestCase):

    def test_the_sites_that_must_never_read_it(self):
        from bot_program import (manual_close, manual_trade, pending_closes,
                                 reconcile_asset)
        from bot_program.asset_engine.base import AssetBot
        from bot_program.engine import kill_switch
        for word in ("pause_s", "kept_no", "trust_no"):
            for fn in (AssetBot.manage_positions, AssetBot._mark_price):
                self.assertNotIn(word, inspect.getsource(fn))
            for mod in (manual_close, manual_trade, pending_closes,
                        reconcile_asset, kill_switch):
                self.assertNotIn(word, inspect.getsource(mod),
                                 (word, mod.__name__))

    def test_the_gates_sit_where_they_must(self):
        from bot_program.asset_engine.base import AssetBot
        src = inspect.getsource(AssetBot.propose_entry)
        self.assertLess(src.index("venue_health.refusal(client, symbol)"),
                        src.index("venue_health.pause_s(client)"))
        self.assertLess(src.index("venue_health.pause_s(client)"),
                        src.index("venue_health.kept_no(client, symbol)"))
        self.assertLess(src.index("venue_health.kept_no(client, symbol)"),
                        src.index("tk = client.ticker(symbol)"))
        src = inspect.getsource(AssetBot.execute_entry)
        sick = src.index("venue_health.refusal(client, symbol)")
        pause = src.index("venue_health.pause_s(client)")
        self.assertLess(sick, pause)
        self.assertLess(pause, src.index("self._etoro_entry_refusal("))
        look = src.index("self._last_look(client, symbol")
        refused = src.index('_look.get("refused")')
        again = src.index("venue_health.refusal(client, symbol)", refused)
        self.assertLess(look, refused)
        self.assertLess(refused, again)
        self.assertLess(again, src.index("order_kwargs = {"))
        # the last look reads the 429 before the pause, both in its except
        src = inspect.getsource(AssetBot._last_look)
        fail = src.index("except Exception as e:")
        self.assertLess(fail, src.index("code == 429"))
        self.assertLess(src.index("code == 429"),
                        src.index("venue_health.pause_s(client)"))
