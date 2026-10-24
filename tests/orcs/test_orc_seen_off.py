"""OFF IS TODAY (spec §11 O1, hard rule 1; O1d). With the `orcs` switch OFF
every surface O1d touches answers exactly what it answered before: the
Horde's board, tab and seat detail (bytes and queries), the positions page,
the close preview and close-all, the Eye's parse and help. ON or OFF, no
surface makes an outbound request, and no O1d code reaches the tick.

"Byte-identical" is measured against the same surface with the Orc
package's read API made unimportable (sys.modules entry None): what the
seams return when the package does not exist, which is the answer before
O1d.

Run with:  python manage.py test tests.orcs.test_orc_seen_off
"""
import inspect
import json
import re
from datetime import datetime, timezone as dt_tz
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from tests.orcs.helpers import (_drum_heard, _paper_cap, _switch, _wake_card,
                                born)
from tests.test_the_horde import (LOCMEM, _all_on, _cfg, _legacy, _manual,
                                  _quote, _trade, _user)

NOW = datetime(2026, 10, 21, 14, 5, tzinfo=dt_tz.utc)
NO_NOTES = {"bot_program.orcs.notes": None}
NO_SURFACES = {"bot_program.orcs.surfaces": None}


def _orcs(on):
    _switch("orcs", on)


def _count(fn):
    with CaptureQueriesContext(connection) as ctx:
        fn()
    return len(ctx.captured_queries)


def _strip(html):
    html = re.sub(r'name="csrfmiddlewaretoken" value="[^"]+"', "", html)
    html = re.sub(r'csrf[_-]?token["\']?\s*[:=]\s*["\'][^"\']+["\']', "",
                  html, flags=re.I)
    return re.sub(r'nonce="[^"]+"', "", html)


@override_settings(CACHES=LOCMEM)
class TheHordeOffTests(TestCase):

    def setUp(self):
        cache.clear()
        _all_on()
        _paper_cap()
        self.user = _user("orc_off")
        self.client.force_login(self.user)
        self.cfg = _cfg(self.user, cls="crypto", symbols=["BTCUSD"],
                        mode="paper")
        _quote("BTCUSD", "101", cls="crypto", source="binance_public")
        _quote("ETHUSD", "50", cls="crypto", source="binance_public")
        from portfolio.services import get_or_create_default_portfolio
        get_or_create_default_portfolio(user=self.user)
        from bot_program.asset_engine import disarm
        braked = _cfg(self.user, cls="crypto", name="braked", mode="paper",
                      symbols=["ETHUSD"])
        disarm.disable_config(braked, by=disarm.BY_BOT_BRAKE, why="t",
                              who="u")
        braked.refresh_from_db()
        self.cfgs = [self.cfg, _manual(self.user, cls="crypto"), braked]
        self.made = []

    def bots(self, n, orcs=True):
        for i in range(n):
            k = len(self.made)
            if k and k % 10 == 0:
                self.cfgs.append(_cfg(self.user, cls="crypto",
                                      name=f"more{k}", mode="paper",
                                      symbols=["BTCUSD"]))
            cfg = self.cfgs[k % len(self.cfgs)]
            t = _trade(cfg, "BTCUSD" if i % 2 else "ETHUSD",
                       rule="manual_take" if cfg.name == "manual"
                       else "golden_cross",
                       meta={"stop_moves": [{"to": "99", "why": "trail"}],
                             "care": {"soft_stop": 99.0,
                                      "soft_why": "breakeven",
                                      "since": timezone.now().isoformat()}})
            self.made.append(t)
            if orcs:
                orc = born(self, t)
                if orc is not None:
                    _wake_card(orc)
                    _drum_heard(orc)
        return self.made

    def board(self):
        from dashboard import horde
        cache.clear()
        with patch("django.utils.timezone.now", return_value=NOW):
            horde.board(self.user, now=NOW)
            return json.dumps(horde.board(self.user, now=NOW),
                              sort_keys=True, default=str)

    def warm(self):
        from dashboard import horde
        cache.clear()
        horde.board(self.user)
        return _count(lambda: horde.board(self.user))

    def test_horde_board_off_is_byte_identical_with_orcs_in_the_tables(self):
        from bot_program.orcs.models import Orc
        self.bots(3)
        self.assertEqual(Orc.objects.count(), 3)
        _orcs(False)
        off = self.board()
        with patch.dict("sys.modules", NO_NOTES):
            bare = self.board()
        self.assertEqual(off, bare)
        data = json.loads(off)
        self.assertEqual(data["v"], 1)
        for g in data["groups"]:
            self.assertIsNone(g["captain"])
            for s in g["seats"]:
                self.assertIsNone(s["orc"])
        _orcs(True)
        on = json.loads(self.board())
        self.assertEqual(on["v"], 2)
        self.assertTrue(all(s["orc"] for g in on["groups"]
                            for s in g["seats"]))

    def test_horde_board_off_costs_today(self):
        self.bots(3)
        _orcs(False)
        self.assertEqual(self.warm(), 10)
        _legacy(self.user, "AAPL")
        self.assertEqual(self.warm(), 11)

    def test_horde_seat_detail_off_is_byte_identical(self):
        from dashboard import horde
        t = self.bots(2)[0]
        _orcs(False)
        key = f"bot:{t.id}"
        horde.seat_detail(self.user, key, now=NOW)

        def detail():
            with patch("django.utils.timezone.now", return_value=NOW):
                return json.dumps(horde.seat_detail(self.user, key, now=NOW),
                                  sort_keys=True, default=str)
        self.assertEqual(_count(lambda: horde.seat_detail(self.user, key)),
                         13)
        off = detail()
        with patch.dict("sys.modules", NO_NOTES):
            bare = detail()
        self.assertEqual(off, bare)
        d = json.loads(off)
        self.assertEqual(d["v"], 1)
        self.assertIsNone(d["voice"]["orc"])
        self.assertIsNone(d["seat"]["orc"])
        self.assertFalse(d["voice"]["orc_block"]["present"])
        self.assertEqual(d["mission"]["thesis"],
                         "No Orc has written a thesis for this seat yet.")

    def test_horde_tab_never_reads_an_orc(self):
        from dashboard import horde
        self.bots(3)
        for on in (False, True):
            _orcs(on)
            cache.clear()
            with patch("bot_program.orcs.notes.for_rows",
                       side_effect=AssertionError("read")) as rows, \
                    patch("bot_program.orcs.notes.for_classes",
                          side_effect=AssertionError("read")) as classes:
                horde.tab(self.user)
                self.assertEqual(_count(lambda: horde.tab(self.user)), 4)
            rows.assert_not_called()
            classes.assert_not_called()


class _Row(TestCase):

    def setUp(self):
        from instruments.models import Instrument
        from market_data.models import LiveQuote
        cache.clear()
        _switch("platform_master", True)
        _orcs(True)
        self.user = _user("orc_off_pos")
        self.client.force_login(self.user)
        inst, _ = Instrument.objects.get_or_create(
            symbol="BTCUSD", defaults={"name": "BTCUSD",
                                       "asset_class": "crypto"})
        LiveQuote.objects.update_or_create(
            instrument=inst, defaults={"last": Decimal("101"),
                                       "source": "binance_public"})
        self.cfg = _cfg(self.user, cls="crypto", symbols=["BTCUSD"],
                        mode="paper")
        self.row = _trade(self.cfg, "BTCUSD")

    def html(self, url="/positions/"):
        r = self.client.get(url)
        self.assertEqual(r.status_code, 200)
        return _strip(r.content.decode())

    def preview(self, url=None):
        r = self.client.post(url or f"/positions/{self.row.pk}/close/preview/",
                             data="{}", content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content[:200])
        return json.dumps(r.json(), sort_keys=True)


class TheBooksOffTests(_Row):

    def test_positions_page_off_is_byte_identical(self):
        born(self, self.row)
        _orcs(False)
        with patch("django.utils.timezone.now", return_value=NOW):
            off = self.html()
            with patch.dict("sys.modules", NO_NOTES):
                bare = self.html()
        self.assertEqual(off, bare)
        self.assertNotIn("data-pos-orc", off)
        self.assertNotIn('class="pos-orc-line"', off)

    def test_positions_page_adds_no_query_without_a_stamp(self):
        def page():
            return self.client.get("/positions/")
        page()
        for on in (True, False):
            _orcs(on)
            n = _count(page)
            with patch.dict("sys.modules", NO_NOTES):
                bare = _count(page)
            self.assertEqual(n, bare, on)

    def test_close_preview_off_is_byte_identical(self):
        born(self, self.row)
        _orcs(False)
        off = self.preview()
        with patch.dict("sys.modules", NO_NOTES):
            bare = self.preview()
        self.assertEqual(off, bare)
        self.assertNotIn('"orc"', off)

    def test_close_all_preview_never_reads_an_orc(self):
        born(self, self.row)
        url = "/positions/close-all/preview/"
        for on in (True, False):
            _orcs(on)
            plain = self.preview(url)
            boom = MagicMock(side_effect=AssertionError("read"))
            with patch("bot_program.orcs.notes.close_note_for", boom), \
                    patch("bot_program.orcs.notes.for_trades", boom), \
                    patch("bot_program.orcs.notes.for_rows", boom):
                patched = self.preview(url)
            boom.assert_not_called()
            self.assertEqual(plain, patched)
            self.assertNotIn('"orc"', plain)


class TheEyeOffTests(TestCase):

    def setUp(self):
        from tests.test_telegram_eye import _staff
        cache.clear()
        self.addCleanup(cache.clear)
        _switch("platform_master", True)
        _orcs(False)
        self.user = _staff()

    def test_slash_orc_off_is_chatter_and_sends_nothing(self):
        from bot_program import telegram_eye as eye
        from tests.test_telegram_eye import SEND, _update
        with patch(SEND, return_value=True) as send:
            with self.captureOnCommitCallbacks(execute=True):
                verdicts = [eye.handle(_update(i, text)) for i, text in
                            enumerate(("/orc 12", "/orcs", "/orc", "/orcs off"),
                                      start=1)]
        self.assertEqual(verdicts, ["chatter"] * 4)
        send.assert_not_called()

    def test_quoted_orc_off_still_asks_sauron(self):
        from bot_program import telegram_eye as eye
        from tests.test_telegram_eye import SEND, _update
        asked = []

        def begin_ask(conv, question, **kw):
            asked.append(question)
            raise RuntimeError("stop here")
        with patch("brain.research_agent.begin_ask", begin_ask), \
                patch(SEND, return_value=True):
            with self.captureOnCommitCallbacks(execute=True):
                verdict = eye.handle(_update(1, '"orc 12"'))
        self.assertEqual(verdict, "answered:ask")
        self.assertEqual(len(asked), 1)
        self.assertTrue(asked[0].startswith("orc 12"), asked[0])

    def test_help_off_is_unchanged(self):
        from bot_program import telegram_eye as eye
        today = (
            "Commands",
            "  • /status — the status report (also /etat)",
            "  • /positions — the open positions",
            "  • /why SYMBOL — why a symbol did not trade (also /pourquoi)",
            "  • /q QUESTION — ask Sauron (also /ask, or the question in "
            "quotes)",
            "  • /stop ID — stop one bot (numbers are in /status)",
            "  • /stopall — stop every running bot",
            "  • /help — this list (also /aide)",
            "Good to know",
            "Replies are always in English.",
            "The brake never closes a position; a stopped bot keeps managing "
            "what is open.",
            "A stopped bot is re-armed on the server, never here.",
            "A quoted question sent as a reply to a Sauron message works too.",
            eye.PRIVACY_LINE,
        )
        self.assertEqual(tuple(str(x) for x in eye.build_help().lines), today)
        with patch.dict("sys.modules", NO_SURFACES):
            _orcs(True)
            self.assertEqual(tuple(str(x) for x in eye.build_help().lines),
                             today)


class TheNoNetworkTests(_Row):

    def test_no_outbound_request_from_any_surface(self):
        import requests

        from bot_program import telegram_eye as eye
        from dashboard import horde
        from tests.test_telegram_eye import SEND, _staff, _update
        orc = born(self, self.row)
        _wake_card(orc)
        _drum_heard(orc)
        calls = []

        def record(name):
            def fn(*a, **kw):
                calls.append(name)
                raise AssertionError(f"outbound: {name}")
            return fn
        with patch.object(requests.Session, "request",
                          side_effect=record("session")), \
                patch("requests.get", side_effect=record("get")), \
                patch("requests.post", side_effect=record("post")), \
                patch("ai_agents.providers.claude_provider.ClaudeProvider."
                      "complete", side_effect=record("claude")), \
                patch("bot_program.engine.broker_router.client_for_symbol",
                      side_effect=record("broker")):
            board = horde.board(self.user)
            seat = horde.seat_detail(self.user, f"bot:{self.row.pk}")
            pages = [self.client.get(url).status_code for url in (
                "/positions/", "/orcs/", f"/orcs/{self.row.pk}/")]
            staff = _staff()
            cfg = _cfg(staff, cls="crypto", symbols=["BTCUSD"], mode="paper")
            st = _trade(cfg, "BTCUSD")
            born(self, st)
            with patch(SEND, return_value=True) as send:
                with self.captureOnCommitCallbacks(execute=True):
                    verdict = eye.handle(_update(1, f"/orc {st.pk}"))
        self.assertEqual(calls, [])
        # every surface above did answer, with its Orc
        self.assertEqual(pages, [200, 200, 200])
        self.assertTrue(any(s["orc"] for g in board["groups"]
                            for s in g["seats"]))
        self.assertIsNotNone(seat["voice"]["orc"])
        self.assertEqual(verdict, "answered:orc")
        self.assertTrue(send.called)
        # the close preview's own broker reads are the same ON and OFF
        seen = {}
        for on in (True, False):
            _orcs(on)
            router = MagicMock()
            with patch("bot_program.engine.broker_router.client_for_symbol",
                       router):
                self.preview()
            seen[on] = router.call_count
        self.assertEqual(seen[True], seen[False])


class TheTickTests(TestCase):

    def test_o1d_reaches_no_tick_file(self):
        from bot_program import manual_close, position_care
        from bot_program.asset_engine import base
        self.assertIsNone(re.search(r"\borcs?\b", inspect.getsource(
            manual_close.preview_close), re.I))
        for mod in (base, position_care):
            src = inspect.getsource(mod)
            for name in ("notes", "surfaces", "views_orcs", "ranks"):
                self.assertNotRegex(
                    src, rf"(from bot_program\.orcs(\.| import ){name}\b"
                         rf"|orcs\.{name}\b)", (mod.__name__, name))
