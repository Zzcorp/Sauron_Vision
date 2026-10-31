"""THE HORDE: a seat for every open position, in a band beside the strip.

The operator, 2026-10-08: "un nouveau bandeau inférieur qui se place au même
niveau que celui actuel ... que l'on peut agrandir ou rétrécir ... la
mission, activité et déploiement des orcs selon le portfolio ... Appelez ça
la Horde." The Orcs (one trader agent per open position) are not built yet;
the Horde is their house. Every open position is a seat; today a seat is
held by the mechanical care, by the engine alone, or by nothing, and the
Horde says which — it never says an Orc decided anything.

One JSON door, /api/horde/ (dashboard.views_horde over dashboard.horde),
one partial (templates/_partials/the_horde.html, authenticated only), one
sheet (static/css/sv-horde.css) and one script (static/js/sv-horde.js).

What is pinned here:
  1. the door: login, the idle lock's 423, the investor cage, GET only,
     a 400 on anything it does not know, a 404 that names nobody;
  2. the scope: a viewer reads only their own book, `pf:` reviews reach
     their legacy seats, no AI-spend key ever travels;
  3. the truth: a real row is valued by the venue mark (a stand-in quote
     is never a price), the digits are the positions page's, demo is
     never "real money", the stragglers and the working orders say what
     they are, the holder and the light tables, the gate's words verbatim;
  4. the Orc rule: no Orc and no Captain is seated, no Orc verb anywhere;
  5. the ceiling: a board's query count does not grow with the seats,
     the tab is cached, the forbidden readers are never called;
  6. the markup, the sheet and the script: no live region, a real tab
     button, a window splitter, the offsets, the ladder, reduced motion,
     the phone tier, the polling guard, rule 1 in the source;
  7. the openers: the level editor loads once and says when it saved, the
     Ask panel takes the seat's facts;
  8. the chrome: the TALL chart, the motion layer, Gollum and the tour;
  9. the stored reasons: the debate's `why`, a venue's refusal, an unread
     thesis and a gate that failed are said by cause, and a voice's words
     never carry an exception name or an amount it wrote.

Run with:  python manage.py test tests.test_the_horde
"""
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.contrib.auth.models import User
from django.core.cache import cache
from django.db import connection
from django.test import SimpleTestCase, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

URL = "/api/horde/"
BASE = Path(settings.BASE_DIR)
JS = BASE / "static" / "js" / "sv-horde.js"
SHEET = BASE / "static" / "css" / "sv-horde.css"
PARTIAL = BASE / "templates" / "_partials" / "the_horde.html"
HORDE_PY = BASE / "dashboard" / "horde.py"
LOCMEM = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
NODE = shutil.which("node")


def _read(*parts):
    return BASE.joinpath(*parts).read_text(encoding="utf-8")


def _strip_js(src):
    code = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"(?m)^\s*//.*$", "", code)


def _strip_css(src):
    return re.sub(r"/\*.*?\*/", "", src, flags=re.S)


# ── fixtures ─────────────────────────────────────────────────────────────

def _user(name="horde_u", staff=False):
    return User.objects.create_user(username=name, password="x", is_staff=staff)


def _cfg(user, cls="commodity", name="bot", mode="live", enabled=True,
         symbols=None, ccy="USD", extras=None, capital="10000"):
    from bot_program.models import AssetBotConfig
    return AssetBotConfig.objects.create(
        user=user, asset_class=cls, name=name, enabled=enabled, mode=mode,
        symbols=["XAUUSD"] if symbols is None else symbols,
        capital=Decimal(capital), base_currency=ccy, extras=extras or {})


def _manual(user, cls="commodity"):
    return _cfg(user, cls=cls, name="manual", symbols=[])


def _trade(cfg, symbol="XAUUSD", *, side="BUY", qty="1", entry="100",
           stop="98", target="110", paper=True, status="OPEN", meta=None,
           rule="golden_cross", cls=None, opened=None):
    from bot_program.models import AssetBotTrade
    md = {"initial_stop_loss": float(stop)} if stop else {}
    md.update(meta or {})
    t = AssetBotTrade.objects.create(
        config=cfg, asset_class=cls or cfg.asset_class, symbol=symbol,
        side=side, qty=Decimal(qty), entry_price=Decimal(entry),
        stop_loss=Decimal(stop) if stop else None,
        take_profit=Decimal(target) if target else None,
        status=status, paper=paper, rule_name=rule, metadata=md)
    if opened is not None:
        type(t).objects.filter(pk=t.pk).update(opened_at=opened)
        t.refresh_from_db()
    return t


def _real(cfg, symbol="XAUUSD", demo=False, **kw):
    meta = {"broker": "etoro"}
    if demo:
        meta["broker_env"] = "paper"
    meta.update(kw.pop("meta", {}) or {})
    return _trade(cfg, symbol, paper=False, meta=meta, **kw)


def _instrument(symbol, cls="commodity", active=True):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": cls,
                                 "is_active": active})
    return inst


def _quote(symbol, last, cls="commodity", source="yahoo", change="0.5"):
    from market_data.models import LiveQuote
    inst = _instrument(symbol, cls)
    LiveQuote.objects.update_or_create(
        instrument=inst, defaults={"last": Decimal(str(last)), "source": source,
                                   "change_pct": Decimal(str(change))})
    return inst


def _legacy(user, symbol="AAPL", cls="stock", direction="long", qty="10",
            entry="100", stop=None, book=None):
    from portfolio.models import Position
    from portfolio.services import get_or_create_default_portfolio
    pf = book or get_or_create_default_portfolio(user=user)
    return Position.objects.create(
        portfolio=pf, instrument=_instrument(symbol, cls), direction=direction,
        quantity=Decimal(qty), entry_price=Decimal(entry),
        current_price=Decimal(entry),
        stop_loss=Decimal(stop) if stop else None, opened_at=timezone.now())


def _switches(**on):
    from core.platform_control import PlatformComponent
    for key, enabled in on.items():
        PlatformComponent.objects.update_or_create(
            key=key, defaults={"name": key, "category": "system",
                               "is_enabled": enabled})


def _all_on():
    _switches(platform_master=True, pipeline_asset_bots=True, aragorn=True,
              agent_position_review=True)


def _review(key, verdict="hold", user=None, symbol="XAUUSD", **kw):
    from brain.position_review_models import PositionReview
    book, pid = key.split(":")
    return PositionReview.objects.create(
        book=book, position_id=int(pid), symbol=symbol, user=user,
        verdict=verdict, triggers=[{"code": "r", "severity": 0.5,
                                    "text": "Price near the stop"}], **kw)


def _seats(board):
    return [s for g in board["groups"] for s in g["seats"]]


def _seat(board, key):
    for s in _seats(board):
        if s["key"] == key:
            return s
    raise AssertionError(f"no seat {key} in {[s['key'] for s in _seats(board)]}")


def _keys(obj, out=None):
    out = set() if out is None else out
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.add(k)
            _keys(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _keys(v, out)
    return out


def _strings(obj, out=None):
    out = [] if out is None else out
    if isinstance(obj, dict):
        for v in obj.values():
            _strings(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _strings(v, out)
    elif isinstance(obj, str):
        out.append(obj)
    return out


class _Base(TestCase):
    """A logged-in owner with every switch on and a clean cache."""

    def setUp(self):
        cache.clear()
        self.user = _user()
        self.client.force_login(self.user)
        _all_on()

    def board(self):
        r = self.client.get(URL)
        self.assertEqual(r.status_code, 200, r.content[:400])
        return r.json()

    def tab(self):
        r = self.client.get(URL, {"part": "tab"})
        self.assertEqual(r.status_code, 200, r.content[:400])
        return r.json()

    def seat(self, key):
        r = self.client.get(URL, {"seat": key})
        self.assertEqual(r.status_code, 200, r.content[:400])
        return r.json()


# ── 13.1 the door ────────────────────────────────────────────────────────

@override_settings(CACHES=LOCMEM)
class TheDoorTests(TestCase):

    def setUp(self):
        cache.clear()

    def test_an_anonymous_reader_is_sent_to_sign_in(self):
        from django.shortcuts import resolve_url
        r = self.client.get(URL)
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r["Location"].startswith(resolve_url(settings.LOGIN_URL)),
                        r["Location"])
        self.assertIn("next=/api/horde/", r["Location"])

    def test_a_locked_session_gets_the_423(self):
        from django.urls import reverse
        self.client.force_login(_user("horde_lock"))
        session = self.client.session
        session["pin_locked"] = True
        session.save()
        r = self.client.get(reverse("horde_feed"))
        self.assertEqual(r.status_code, 423)
        self.assertEqual(r.json(), {"pin_locked": True})
        session = self.client.session
        session["pin_locked"] = False
        session.save()
        r = self.client.get(reverse("horde_feed"), {"part": "tab"})
        self.assertEqual((r.status_code, r.json()["part"]), (200, "tab"))

    def test_an_investor_is_sent_to_the_panel(self):
        from portfolio.investor_models import InvestorAccess
        owner = _user("horde_owner")
        investor = _user("horde_lp")
        InvestorAccess.objects.create(investor=investor, owner=owner, label="Fund")
        self.client.force_login(investor)
        from django.urls import reverse
        r = self.client.get(reverse("horde_feed"))
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r["Location"].startswith("/investor/"), r["Location"])

    def test_only_get(self):
        self.client.force_login(_user("horde_post"))
        self.assertEqual(self.client.post(URL).status_code, 405)

    def test_what_it_does_not_know_is_a_400(self):
        self.client.force_login(_user("horde_bad"))
        for q in ({"part": "nope"}, {"seat": "bot:x"}, {"seat": "foo:1"},
                  {"seat": "bot:1", "part": "tab"}):
            r = self.client.get(URL, q)
            self.assertEqual(r.status_code, 400, q)
            self.assertEqual(r.json(), {"ok": False, "error": "bad_request",
                                        "t": "Unknown part or seat key."})

    def test_the_route_is_named_and_never_cached(self):
        from django.urls import reverse
        self.assertEqual(reverse("horde_feed"), URL)
        self.client.force_login(_user("horde_route"))
        r = self.client.get(URL)
        self.assertEqual(r.status_code, 200)
        self.assertIn("no-cache", r.get("Cache-Control", ""))
        body = r.json()
        self.assertEqual((body["ok"], body["v"], body["part"]), (True, 1, "board"))
        self.assertEqual(body["empty"]["code"], "no_book")


# ── 13.2 the scope (rule 4) ──────────────────────────────────────────────

@override_settings(CACHES=LOCMEM)
class TheScopeTests(_Base):

    def setUp(self):
        super().setUp()
        self.other = _user("horde_b")
        self.cfg = _cfg(self.user)
        self.mine = _trade(self.cfg, "XAUUSD")
        bcfg = _cfg(self.other, name="theirs")
        self.theirs = _trade(bcfg, "XAGUSD", entry="30", stop="29", target="33")
        self.their_pos = _legacy(self.other, "MSFT")

    def test_another_book_never_appears(self):
        board = self.board()
        keys = {s["key"] for s in _seats(board)}
        self.assertEqual(keys, {f"bot:{self.mine.id}"})
        text = json.dumps(board) + json.dumps(self.tab())
        self.assertNotIn("XAGUSD\"", text.replace("XAGUSD\", \"relation", ""))
        self.assertNotIn("MSFT", text)
        self.assertNotIn("horde_b", text)
        self.assertEqual(self.tab()["seats"], 1)

    def test_a_seat_of_another_book_is_a_404_that_names_nobody(self):
        for key in (f"bot:{self.theirs.id}", f"pf:{self.their_pos.id}",
                    "bot:999999"):
            r = self.client.get(URL, {"seat": key})
            self.assertEqual(r.status_code, 404, key)
            self.assertEqual(r.json(), {"ok": False, "error": "not_found",
                                        "t": "This position is not open in your book."})
            self.assertNotIn(b"horde_b", r.content)

    def test_the_shared_main_book_is_not_a_seat_but_the_gate_counts_it(self):
        from portfolio.risk_gate import limits_book
        from portfolio.services import get_or_create_default_portfolio
        main = limits_book()
        main.max_open_risk_pct = 15
        main.save()
        own = get_or_create_default_portfolio(user=self.user)
        own.current_value = Decimal("10000")
        own.save()
        _real(self.cfg, "XAUUSD")
        _legacy(self.user, "IBM", book=main)
        board = self.board()
        self.assertNotIn("IBM", json.dumps(_seats(board)))
        live = board["head"]["sides"]["live"]
        self.assertEqual(live["gate_extra_rows"], 1)
        self.assertIn("The gate counts 1 more row(s): open rows of the shared "
                      "Main book, which are not seats here.", live["extra_t"])

    def test_pf_reviews_reach_the_legacy_seat_and_never_anothers(self):
        pos = _legacy(self.user, "AAPL")
        _review(f"pf:{pos.id}", verdict="exit", user=None, symbol="AAPL")
        _review(f"bot:{self.theirs.id}", verdict="exit", user=self.other,
                symbol="XAGUSD")
        board = self.board()
        seat = _seat(board, f"pf:{pos.id}")
        self.assertEqual(seat["voice"]["reviewer"]["word"], "EXIT")
        self.assertIn("reviewer_exit", [w["code"] for w in seat["light"]["why"]])
        mine = _seat(board, f"bot:{self.mine.id}")
        self.assertIsNone(mine["voice"]["reviewer"])

    def test_no_seat_no_review_read(self):
        from bot_program.models import AssetBotTrade
        AssetBotTrade.objects.filter(config__user=self.user).delete()
        with mock.patch("brain.position_review.latest_verdicts",
                        side_effect=AssertionError("read with no keys")):
            body = self.board()
            self.tab()
        self.assertEqual(body["empty"]["code"], "no_seats")

    def test_another_users_orc_never_appears(self):
        from tests.orcs.helpers import born
        born(self, self.mine)
        born(self, self.theirs)
        _switches(orcs=True)
        board = self.board()
        labels = {s["orc"]["label"] for s in _seats(board) if s["orc"]}
        self.assertEqual(labels, {f"Orc #{self.mine.id}"})
        self.assertNotIn(f"Orc #{self.theirs.id}", json.dumps(board))
        r = self.client.get(URL, {"seat": f"bot:{self.theirs.id}"})
        self.assertEqual(r.status_code, 404)
        from dashboard.horde import _orc_slots
        self.assertEqual(_orc_slots([self.theirs.id], on=True,
                                    user=self.user), {})

    def test_no_ai_spend_key_travels_with_orcs(self):
        from decimal import Decimal as D

        from bot_program.orcs.models import Orc
        from tests.orcs.helpers import _wake_card, born
        orc = born(self, self.mine)
        _wake_card(orc)
        Orc.objects.filter(pk=orc.pk).update(spend_today_usd=D("1.25"),
                                             r_money=D("99.5"))
        _switches(orcs=True)
        board, seat = self.board(), self.seat(f"bot:{self.mine.id}")
        # the walk below reads real Orc slots, not an empty board
        self.assertTrue(any(s["orc"] for s in _seats(board)))
        self.assertIsNotNone(seat["voice"]["orc"])
        for payload in (board, seat):
            keys = _keys(payload)
            for banned in ("cost_usd", "tokens_in", "tokens_out",
                           "model_used", "r_money", "spend_today_usd",
                           "ai_cost_usd", "spend"):
                self.assertNotIn(banned, keys)

    def test_no_ai_spend_key_travels_staff_or_not(self):
        _review(f"bot:{self.mine.id}", verdict="tighten", user=self.user,
                cost_usd=Decimal("0.02"), tokens_in=900, tokens_out=200,
                model_used="m-1", reasoning_md="Tighten.")
        plain = self.board()
        seat = self.seat(f"bot:{self.mine.id}")
        staff = _user("horde_staff", staff=True)
        cfg = _cfg(staff, name="s")
        st = _trade(cfg, "XAUUSD")
        _review(f"bot:{st.id}", verdict="tighten", user=staff,
                cost_usd=Decimal("0.02"), tokens_in=900, tokens_out=200,
                model_used="m-1", reasoning_md="Tighten.")
        self.client.force_login(staff)
        cache.clear()
        staff_board = self.board()
        staff_seat = self.seat(f"bot:{st.id}")
        for payload in (plain, seat, staff_board, staff_seat):
            keys = _keys(payload)
            for banned in ("cost_usd", "tokens_in", "tokens_out", "model_used"):
                self.assertNotIn(banned, keys)
        self.assertEqual(_keys(plain), _keys(staff_board))


# ── 13.3 the truth ───────────────────────────────────────────────────────

@override_settings(CACHES=LOCMEM)
class TheTruthTests(_Base):

    def setUp(self):
        super().setUp()
        self.cfg = _cfg(self.user)

    def test_a_stand_in_quote_is_never_a_real_rows_price(self):
        _quote("XAUUSD", "2650")                      # GC=F: a future
        t = _real(self.cfg, "XAUUSD", entry="2600", stop="2580", target="2700")
        seat = _seat(self.board(), f"bot:{t.id}")
        self.assertIsNone(seat["mark"]["v"])
        self.assertEqual(seat["mark"]["t"], "—")
        self.assertEqual(seat["mark"]["wait"], "waiting for the venue's price")
        self.assertIsNone(seat["money"]["pnl_v"])
        self.assertIsNone(seat["money"]["r_v"])
        self.assertEqual(seat["money"]["r_t"], "—")
        self.assertNotIn("2650", json.dumps(seat))
        self.assertIn("mark_waiting", [w["code"] for w in seat["light"]["why"]])

    def test_the_digits_are_the_positions_pages(self):
        """The money (P&L, R, percentages) is the positions page's to the
        digit; the PRICE is the instrument's one precision (core/
        price_format), its levels', its plan's and its correlated row's
        (2026-10-16 review: "4,182.1000" beside "4160.00")."""
        from core.price_format import format_price
        from dashboard.views import _live_open_book
        from portfolio.services import get_or_create_default_portfolio
        _quote("BTCUSD", "101.5", cls="crypto", source="binance_public")
        _quote("ETHUSD", "48", cls="crypto", source="binance_public")
        _quote("AAPL", "110", cls="stock")
        crypto = _cfg(self.user, cls="crypto", name="c", mode="paper",
                      symbols=["BTCUSD"])
        _trade(crypto, "BTCUSD", entry="100", stop="98")
        _trade(crypto, "ETHUSD", side="SELL", entry="50", stop="52", target="40")
        _trade(crypto, "BTCUSD", stop=None, entry="99")
        _legacy(self.user, "AAPL", stop="95")
        pf = get_or_create_default_portfolio(user=self.user)
        rows = {r["key"]: r for r in _live_open_book(self.user, pf)[1]}
        board = self.board()
        self.assertEqual(len(_seats(board)), len(rows))
        for seat in _seats(board):
            kind, ident = seat["key"].split(":")
            row = rows[("bot-" if kind == "bot" else "pos-") + ident]
            self.assertEqual(seat["money"]["r_t"], row["r_text"])
            self.assertEqual(seat["money"]["pnl_t"], row["pnl_text"])
            self.assertEqual(seat["money"]["pct_t"], row["pct_text"])
            self.assertEqual(seat["mark"]["t"],
                             format_price(row["current_price"], seat["instrument_class"],
                                          seat["symbol"]))
            self.assertEqual(seat["mark"]["word"], row["mark_word"])
            self.assertEqual(seat["mark"]["wait"], row["mark_wait"])

    def test_the_seat_count_is_the_strips(self):
        _trade(self.cfg, "XAUUSD")
        _trade(self.cfg, "XAGUSD", status="CLOSE_PENDING")
        _legacy(self.user, "AAPL")
        _trade(self.cfg, "WTIUSD", status="ERROR")            # a straggler
        page = self.client.get("/getting-started/").content.decode()
        m = re.search(r'id="ipPositionsCount"[^>]*>(\d+)<', page)
        self.assertIsNotNone(m)
        self.assertEqual(self.tab()["seats"], int(m.group(1)))
        self.assertEqual(len(_seats(self.board())), int(m.group(1)))
        self.assertIn(f'id="svHordeSeats">{m.group(1)} seats<', page)

    def test_demo_is_never_real_money(self):
        t = _real(self.cfg, "XAUUSD", demo=True)
        board = self.board()
        seat = _seat(board, f"bot:{t.id}")
        self.assertEqual((seat["world"], seat["world_word"]), ("demo", "DEMO"))
        self.assertNotIn("REAL MONEY", json.dumps(seat))
        self.assertTrue(board["head"]["sides"]["live"]["demo_note"])
        self.assertEqual(board["groups"][0]["lines"][0]["world_word"], "DEMO")

    def test_close_pending_is_a_seat_in_alarm(self):
        t = _trade(self.cfg, "XAUUSD", status="CLOSE_PENDING")
        seat = _seat(self.board(), f"bot:{t.id}")
        self.assertEqual(seat["light"]["tone"], "alarm")
        self.assertIn("close_pending", [w["code"] for w in seat["light"]["why"]])
        self.assertEqual(seat["commands"]["close_label"], "Retry close…")
        self.assertIsNone(seat["commands"]["levels"])

    def test_a_close_sauron_gave_up_on_is_a_straggler(self):
        t = _trade(self.cfg, "WTIUSD", status="ERROR", entry="70", stop="68",
                   target="75")
        board = self.board()
        self.assertNotIn(f"bot:{t.id}", {s["key"] for s in _seats(board)})
        row = board["stragglers"][0]
        self.assertEqual(row["key"], f"bot:{t.id}")
        self.assertEqual(row["story"], f"/forensics/{t.id}/")
        self.assertIn("It may still be open at the broker", row["t"])
        self.assertNotIn("commands", row)
        self.assertEqual(self.tab()["stragglers"], 1)
        self.assertGreaterEqual(self.tab()["alarms"], 1)

    def test_a_working_order_is_an_order(self):
        _quote("XAGUSD", "29.1")          # 0.1R from the stop: not a position
        t = _trade(self.cfg, "XAGUSD", entry="30", stop="29", target="33",
                   meta={"entry_working": True})
        seat = _seat(self.board(), f"bot:{t.id}")
        self.assertEqual(seat["light"]["tone"], "order")
        self.assertNotIn("near_stop", [w["code"] for w in seat["light"]["why"]])
        self.assertTrue(seat["working"])
        self.assertIsNone(seat["money"]["pnl_v"])
        self.assertEqual(seat["money"]["note"], "no P&L: not filled")
        self.assertTrue(seat["mission"].startswith("Working order at the broker"))

    def test_a_legacy_row_has_no_venue_no_keeper_no_command(self):
        pos = _legacy(self.user, "AAPL")
        seat = _seat(self.board(), f"pf:{pos.id}")
        self.assertEqual((seat["world"], seat["world_word"]), ("", "NO VENUE"))
        self.assertEqual(seat["holder"]["by"], "nothing")
        self.assertIsNone(seat["links"]["story"])
        self.assertFalse(seat["commands"]["close"])
        self.assertFalse(seat["commands"]["advice"])
        self.assertIsNone(seat["commands"]["levels"])
        self.assertEqual(seat["mission"], "Recorded by hand · no keeper")
        self.assertEqual(seat["light"]["tone"], "unheld")

    def test_the_holder_table(self):
        from dashboard.horde import holder
        on = {"platform_master": True, "pipeline_asset_bots": True,
              "aragorn": True}
        bot = {"legacy": False, "config_enabled": True, "keeps_managing": False,
               "record_short": "", "manual_lane": False, "protected": False,
               "world": "paper"}
        self.assertEqual(holder({**bot, "legacy": True}, on)["by"], "nothing")
        tick_off = holder(bot, {**on, "pipeline_asset_bots": False})
        self.assertEqual(tick_off["by"], "nothing")
        self.assertIn("the 5-minute tick is switched off", tick_off["words"])
        self.assertEqual(holder(bot, {"aragorn": True})["by"], "nothing",
                         "a missing switch row reads as off")
        off = holder({**bot, "config_enabled": False,
                      "record_short": "stopped by `bot off` on the server"}, on)
        self.assertEqual(off["by"], "nothing")
        self.assertIn("Its bot is off (stopped by `bot off` on the server)",
                      off["words"])
        self.assertEqual(holder(bot, {**on, "aragorn": False})["by"], "engine")
        manual = holder({**bot, "manual_lane": True}, on)
        self.assertEqual((manual["by"], manual["short"]),
                         ("care_locks", "Care · profit locks"))
        braked = holder({**bot, "config_enabled": False, "keeps_managing": True,
                         "record_short": "stopped by `bot brake` on the server"},
                        on)
        self.assertEqual((braked["by"], braked["short"]),
                         ("care_braked", "Care · braked bot"))
        full = holder(bot, on)
        self.assertEqual((full["by"], full["short"]), ("care", "Full care"))
        self.assertEqual(full["suffix"],
                         "A paper row: only the platform's simulator acts on it.")
        self.assertIn("so they work even when Sauron is offline",
                      holder({**bot, "world": "live", "protected": True}, on)["suffix"])
        self.assertIn("as long as Sauron itself is running",
                      holder({**bot, "world": "demo"}, on)["suffix"])

    def test_the_holder_reads_the_disarm_record(self):
        from bot_program.asset_engine import disarm
        from dashboard.horde import _holder_facts, holder
        on = {"platform_master": True, "pipeline_asset_bots": True,
              "aragorn": True}
        off_cfg = _cfg(self.user, name="off")
        disarm.disable_config(off_cfg, by=disarm.BY_BOT_OFF, why="t", who="u")
        brake_cfg = _cfg(self.user, name="brk")
        disarm.disable_config(brake_cfg, by=disarm.BY_BOT_BRAKE, why="t", who="u")
        off_cfg.refresh_from_db()
        brake_cfg.refresh_from_db()
        a = _trade(off_cfg, "XAUUSD")
        b = _trade(brake_cfg, "XAUUSD")
        self.assertEqual(holder(_holder_facts(a, "paper"), on)["by"], "nothing")
        self.assertEqual(holder(_holder_facts(b, "paper"), on)["by"], "care_braked")
        m = _trade(_manual(self.user), "XAUUSD", rule="manual_take")
        self.assertEqual(holder(_holder_facts(m, "paper"), on)["by"], "care_locks")

    def _calm(self, **over):
        facts = {
            "status": "OPEN", "close_in_doubt": False,
            "protection_vanished": False, "legs_unconfirmed": False,
            "venue_stop_unread": False, "stop_rules_inert": "",
            "stop_rules_inert_detail": "", "through_stop": False,
            "stop_t": "98.00", "world": "paper", "has_stop": True,
            "held_stop": None, "thesis_verdict": "", "thesis_fresh": False,
            "reviewer_verdict": "", "holder_by": "care", "protected": False,
            "working": False, "mark_source": "quote", "mark_age_t": "",
            "priced": True, "near_stop_r": 2.0, "event": None,
            "care_present": True, "refusal": "", "time_stop_left_s": None,
            "asset_class": "crypto", "vpu_stamped": True,
            "tick_overdue": False, "tick_age_t": "", "legacy": False,
        }
        facts.update(over)
        return facts

    def test_the_light_table(self):
        from dashboard.horde import light
        self.assertEqual(light(self._calm()),
                         {"tone": "calm", "word": "CALM",
                          "why": [{"code": "calm", "tone": "calm",
                                   "t": "Held; nothing flagged."}]})
        real = {"world": "live"}
        cases = [
            ("close_pending", "alarm", {"status": "CLOSE_PENDING"}),
            ("close_in_doubt", "alarm", {"close_in_doubt": True}),
            ("protection_vanished", "alarm", {"protection_vanished": True}),
            ("legs_unconfirmed", "alarm", {"legs_unconfirmed": True}),
            ("venue_stop_unread", "alarm", {"venue_stop_unread": True}),
            ("stop_rules_inert", "alarm", {"stop_rules_inert": "legs_unmovable"}),
            ("through_stop", "alarm", {"through_stop": True}),
            ("no_stop_real", "alarm", {**real, "has_stop": False}),
            ("no_stop_at_venue", "alarm", {**real, "held_stop": 0.0}),
            ("thesis_exit", "alarm", {"thesis_verdict": "exit", "thesis_fresh": True}),
            ("reviewer_exit", "alarm", {"reviewer_verdict": "exit"}),
            ("unheld_real", "alarm", {**real, "holder_by": "nothing"}),
            ("working", "order", {"working": True}),
            ("mark_stale", "watch", {**real, "mark_source": "venue_stale",
                                     "mark_age_t": "2 h"}),
            ("mark_waiting", "watch", {**real, "priced": False,
                                       "mark_source": "awaiting_venue"}),
            ("near_stop", "watch", {"near_stop_r": 0.2}),
            ("thesis_adjust", "watch", {"thesis_verdict": "adjust", "thesis_fresh": True}),
            ("thesis_watch", "watch", {"thesis_verdict": "watch", "thesis_fresh": True}),
            ("reviewer_tighten", "watch", {"reviewer_verdict": "tighten"}),
            ("reviewer_take_part", "watch", {"reviewer_verdict": "take_part"}),
            ("event_near", "watch", {"event": {"title": "CPI", "at_t": "12:30"}}),
            ("no_care_record", "watch", {"care_present": False}),
            ("mirror_refused", "watch", {"refusal": "refused"}),
            ("time_stop_soon", "watch", {"time_stop_left_s": 3600}),
            ("no_usd_stamp", "watch", {"asset_class": "forex", "vpu_stamped": False}),
            ("no_stop_paper", "watch", {"has_stop": False}),
            ("tick_stale", "watch", {"tick_overdue": True, "tick_age_t": "20 min"}),
            ("unheld", "unheld", {"holder_by": "nothing"}),
        ]
        for code, tone, over in cases:
            got = light(self._calm(**over))
            self.assertIn(code, [w["code"] for w in got["why"]], code)
            self.assertEqual(got["tone"], tone, code)
            self.assertEqual(got["word"], tone.upper(), code)
            for w in got["why"]:
                self.assertTrue(w["t"].endswith("."), (code, w["t"]))
        both = light(self._calm(close_in_doubt=True, near_stop_r=0.1))
        self.assertEqual(both["tone"], "alarm")
        self.assertEqual([w["code"] for w in both["why"]],
                         ["close_in_doubt", "near_stop"])
        stale_paper = light(self._calm(mark_source="venue_stale"))
        self.assertEqual(stale_paper["tone"], "calm", "staleness is a real-row watch")
        # Nothing ticks it, but the broker holds its levels: not unheld.
        guarded = light(self._calm(world="live", holder_by="nothing", protected=True))
        self.assertNotIn("unheld_real", [w["code"] for w in guarded["why"]])
        self.assertEqual(guarded["tone"], "calm")

    def test_the_held_stop(self):
        t = _real(self.cfg, "XAUUSD", meta={
            "stop_rewritten_by_venue": {"sent": 98.0, "held": 0.0}})
        seat = _seat(self.board(), f"bot:{t.id}")
        self.assertIn("no_stop_at_venue", [w["code"] for w in seat["light"]["why"]])
        u = _real(self.cfg, "XAGUSD", entry="2", stop="1.2", target="3", meta={
            "stop_rewritten_by_venue": {"sent": 1.2, "held": 1.23}})
        stops = self.seat(f"bot:{u.id}")["stops"]
        self.assertIn({"label": "stop held at eToro since the fill", "t": "1.23"},
                      stops)

    def test_a_later_move_supersedes_the_fills_no_stop(self):
        """eToro's "no stop" at the fill is the level resting there only
        until something moves it: a broker stop move, a level edit, the
        post-fill re-anchor or a care mirror replaces it (bot_program/
        venue_exit.py venue_levels). The alarm and the Ask facts say no
        stop rests at eToro only while that is still true."""
        none = {"stop_rewritten_by_venue": {"sent": 98.0, "held": 0.0}}
        later = (
            {"stop_moves": [{"to": "99", "asked": "99", "at": "100",
                             "why": "trail:broker"}]},
            {"level_edits": [{"at": timezone.now().isoformat(), "stop": "99",
                              "target": None, "widened": False,
                              "broker": "in-place"}]},
            {"stop_reanchored_to_fill": True},
            {"care": {"venue_stop": 99.0, "since": timezone.now().isoformat()}},
        )
        bare = _real(self.cfg, "XAUUSD", meta=dict(none))
        moved = [_real(self.cfg, "XAUUSD", meta={**none, **m}) for m in later]
        board = self.board()
        seat = _seat(board, f"bot:{bare.id}")
        self.assertIn("no_stop_at_venue", [w["code"] for w in seat["light"]["why"]])
        self.assertIn("held at eToro none", seat["commands"]["ask"]["facts"])
        for t in moved:
            seat = _seat(board, f"bot:{t.id}")
            self.assertNotIn("no_stop_at_venue",
                             [w["code"] for w in seat["light"]["why"]], t.metadata)
            self.assertNotIn("held at eToro", seat["commands"]["ask"]["facts"])

    def test_an_unmeasured_correlation_is_a_dash(self):
        _quote("XAGUSD", "31", change="0")
        _instrument("XAUUSD")
        t = _trade(self.cfg, "XAUUSD")
        peers = self.seat(f"bot:{t.id}")["instruments"]["peers"]
        silver = [p for p in peers if p["symbol"] == "XAGUSD"]
        self.assertEqual(len(silver), 1)
        self.assertFalse(silver[0]["measured"])
        self.assertIsNone(silver[0]["rho_t"])
        self.assertIsNone(silver[0]["change_t"])
        self.assertEqual(silver[0]["last_t"], "31.00")

    def test_worlds_and_currencies_are_never_summed(self):
        _quote("XAUUSD", "101", source="etoro")
        live_eur = _cfg(self.user, name="eur", ccy="EUR")
        for cfg, real in ((self.cfg, True), (self.cfg, False), (live_eur, True)):
            meta = {"broker": "etoro", "venue_mark": {
                "price": 101.0, "at": timezone.now().isoformat(),
                "source": "etoro", "via": "tick"}} if real else {}
            _trade(cfg, "XAUUSD", paper=not real, meta=meta)
        group = self.board()["groups"][0]
        by_world = {line["world"]: line for line in group["lines"]}
        self.assertEqual(set(by_world), {"live", "paper"})
        self.assertEqual(sorted(p["ccy"] for p in by_world["live"]["pnl"]),
                         ["EUR", "USD"])
        self.assertEqual([p["ccy"] for p in by_world["paper"]["pnl"]], ["USD"])
        self.assertEqual(sum(len(ln["pnl"]) for ln in group["lines"]), 3)

    def test_the_gate_is_quoted_verbatim(self):
        from portfolio.risk_gate import limits_book, preflight
        from portfolio.services import get_or_create_default_portfolio
        main = limits_book()
        main.max_open_risk_pct = 15
        main.max_daily_loss_pct = 8
        main.current_value = Decimal("0")
        main.save()
        own = get_or_create_default_portfolio(user=self.user)
        own.current_value = Decimal("0")
        own.save()
        _real(self.cfg, "XAUUSD")
        live = self.board()["head"]["sides"]["live"]
        gate = preflight(self.user, venue="live")["checks"]
        self.assertEqual(live["open_risk"]["reason"], gate["open_risk"]["reason"])
        self.assertEqual(live["daily"]["reason"], gate["daily_loss"]["reason"])
        self.assertEqual(live["open_risk"]["tone"], "unmeasured")
        self.assertIsNone(live["open_risk"]["pct_t"])
        self.assertIn("never been set", live["open_risk"]["t"])
        # No book value, no book words: a dash, and the allocation says why.
        self.assertEqual(live["book_t"], "—")
        self.assertEqual(live["alloc_t"],
                         "Book size unknown: allocation cannot be measured.")

    def test_limits_that_could_not_be_read_say_so(self):
        _trade(self.cfg, "XAUUSD")
        broken = {"ok": True, "failed_open": True, "checks": {},
                  "reason": "book risk limits could not be read (boom) — "
                            "entries are not gated by them right now"}
        with mock.patch("portfolio.risk_gate.preflight", return_value=broken):
            head = self.board()["head"]
            flag = self.tab()["flag"]
        self.assertTrue(head["sides"]["live"]["failed_open"])
        # Said in the Horde's words: the gate's reason carries the
        # exception's text (portfolio/risk_gate.py preflight), never shown.
        from dashboard.horde import FAILED_OPEN, FAILED_REASON
        self.assertEqual(head["sides"]["live"]["failed_reason"], FAILED_REASON)
        # The gate said nothing about exposure or notional: a dash, never OK.
        self.assertIsNone(head["sides"]["live"]["exposure"]["ok"])
        self.assertIsNone(head["sides"]["live"]["notional"]["ok"])
        self.assertEqual(head["sides"]["live"]["failed_t"], FAILED_OPEN)
        self.assertNotIn("boom", json.dumps(head))
        self.assertEqual(flag, "unreadable")

    def test_a_day_whose_closes_carry_no_price_is_unmeasured(self):
        """risk_gate.daily_loss_state sets the floor and leaves realized
        None when no close of the window carries a price: the stop cannot
        be applied, so the band dashes it and quotes the gate, never
        "OPEN"."""
        from dashboard.horde import _daily
        reason = ("2 position(s) closed in the last 24h and none of them "
                  "carries a price to measure")
        out = _daily({"limit_money": -800.0, "limit_pct": 8, "hard_pct": 12,
                      "realized": None, "mode": "open", "reason": reason}, 0)
        self.assertEqual(out["mode"], "unmeasured")
        self.assertEqual(out["t"], reason)

    def test_a_review_without_a_verdict_colours_nothing(self):
        """The reviewer's "none" (no model pass) and "no_quote" are not
        verdicts: no chip, no light, and the dossier says NO VERDICT."""
        t = _trade(self.cfg, "XAUUSD")
        _review(f"bot:{t.id}", verdict="none", user=self.user)
        seat = _seat(self.board(), f"bot:{t.id}")
        self.assertIsNone(seat["voice"]["reviewer"])
        self.assertFalse([w for w in seat["light"]["why"]
                          if w["code"].startswith("reviewer_")])
        voice = self.seat(f"bot:{t.id}")["voice"]["reviewer"]
        self.assertEqual(voice["word"], "NO VERDICT")

    def test_an_unstamped_forex_row_puts_no_money_in_the_totals(self):
        """No USD conversion stamp: its risk is in the quote currency, so it
        is a dash on the seat and left out of the band's sum (§6.3)."""
        fx = _cfg(self.user, cls="forex", name="fx", symbols=["USDJPY"])
        t = _trade(fx, "USDJPY", entry="150", stop="149", target="152")
        _trade(fx, "EURUSD", entry="1.1", stop="1.09", target="1.12",
               meta={"value_per_unit": 1.0})
        board = self.board()
        seat = _seat(board, f"bot:{t.id}")
        self.assertIn("no_usd_stamp", [w["code"] for w in seat["light"]["why"]])
        self.assertIsNone(seat["risk"]["t"])
        self.assertIsNone(seat["risk"]["v"])
        line = [g for g in board["groups"] if g["key"] == "forex"][0]["lines"][0]
        self.assertEqual((line["seats"], line["risk_n"]), (2, 1))
        self.assertEqual(line["risk_t"], "0.01")
        dossier = self.seat(f"bot:{t.id}")
        risk = [r for r in dossier["deployment"] if r["label"] == "Risk at the stop"][0]
        self.assertEqual(risk["t"], "—")

    def test_a_target_only_edit_says_the_target(self):
        t = _trade(self.cfg, "XAUUSD", meta={"level_edits": [
            {"at": timezone.now().isoformat(), "by": "u", "stop": None,
             "target": "112", "widened": False, "broker": "bot"}]})
        lines = [e["t"] for e in self.seat(f"bot:{t.id}")["timeline"]
                 if e["author"] == "YOU"]
        self.assertTrue(any(x.startswith("You set the target to") for x in lines), lines)
        self.assertFalse(any(x.startswith("You set the stop to") for x in lines), lines)

    def test_the_phone_stop_line_is_true_for_a_working_order(self):
        """The Eye's /stop withdraws the braked config's working entries
        (telegram_eye.apply_brake, withdraw=True): a working order's seat
        never reads "it never closes this position"."""
        w = _trade(self.cfg, "XAGUSD", entry="30", stop="29", target="33",
                   meta={"entry_working": True})
        o = _trade(self.cfg, "XAUUSD")
        stop_w = [p for p in self.seat(f"bot:{w.id}")["phone"]
                  if p["cmd"].startswith("/stop")][0]
        stop_o = [p for p in self.seat(f"bot:{o.id}")["phone"]
                  if p["cmd"].startswith("/stop")][0]
        self.assertIn("working orders are withdrawn, this one included", stop_w["t"])
        self.assertIn("It never closes this position.", stop_o["t"])

    def test_a_zero_stop_is_no_stop(self):
        """eToro spells "no stop" 0: never a level 100% away."""
        _quote("XAUUSD", "101")
        t = _trade(self.cfg, "XAUUSD", stop="0")
        seat = _seat(self.board(), f"bot:{t.id}")
        self.assertIsNone(seat["levels"]["stop_t"])
        self.assertIsNone(seat["levels"]["stop_pct_t"])
        self.assertIn("no_stop_paper", [w["code"] for w in seat["light"]["why"]])

    def test_a_legacy_seat_has_its_peers_too(self):
        _instrument("AAPL", "stock")
        t = _trade(self.cfg, "XAUUSD")
        pos = _legacy(self.user, "AAPL")
        peers = self.seat(f"pf:{pos.id}")["instruments"]["peers"]
        mine = [p for p in peers if p["symbol"] == "XAUUSD"]
        self.assertEqual(len(mine), 1)
        self.assertEqual(mine[0]["relation"], f"YOUR PAPER SEAT #{t.id}")
        self.assertEqual(mine[0]["seat_world"], "paper")
        self.assertTrue(mine[0]["is_seat"])
        self.assertFalse(mine[0]["ticket"])

    def test_a_broker_row_no_seat_claims(self):
        _real(self.cfg, "XAUUSD")
        view = {"name": "eToro", "env": "LIVE", "kind": "etoro", "label": "x",
                "equity": None,
                "positions": {"rows": [
                    {"symbol": "AAPL", "qty": 3, "market_value": 512.5},
                    {"symbol": "XAUUSD", "qty": 1, "market_value": 2600}],
                    "at": timezone.now(), "age_seconds": 720}}
        with mock.patch("bot_program.capital_truth.broker_view", return_value=view):
            un = self.board()["unseated"]
        self.assertEqual([r["symbol"] for r in un["rows"]], ["AAPL"])
        self.assertEqual((un["broker"], un["env"], un["world"]),
                         ("eToro", "LIVE", "live"))
        self.assertEqual(un["age_t"], "12 min")
        self.assertEqual(un["rows"][0]["value_t"], "512.50")

    def test_an_unmarked_broker_row_is_a_dash(self):
        """eToro's /portfolio row carries no mark: its adapter writes
        market_value 0.0 rather than inventing one (bot_program/engine/
        etoro_client.py broker_portfolio). Unmeasured, never 0.00."""
        view = {"name": "eToro", "env": "DEMO", "kind": "etoro", "label": "x",
                "equity": None,
                "positions": {"rows": [
                    {"symbol": "GLDM", "qty": 2.0, "market_value": 0.0,
                     "market_price": 0.0}],
                    "at": timezone.now(), "age_seconds": 30}}
        with mock.patch("bot_program.capital_truth.broker_view", return_value=view):
            un = self.board()["unseated"]
        self.assertEqual(un["rows"][0]["value_t"], "—")
        self.assertEqual((un["world"], un["world_word"]), ("demo", "DEMO"))


# ── 13.4 the Orc rule ────────────────────────────────────────────────────

RESERVED = {
    "No Orc", "No Orc seated.",
    "Nothing on this seat was decided by an Orc.",
    "When the Orcs arrive, this seat's Orc writes its thesis, plan and notes here.",
    "No Captain seated yet.",
    "Captains are not built yet. Today this class answers to the book limits: "
    "open risk at the stops, theme legs and the correlation taper.",
    "No Orc has written a thesis for this seat yet.",
}
ORC_WORD = re.compile(r"\b(Orc|Orcs|Captain|Captains)\b")


def _sentences(text):
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n", text) if s.strip()]


@override_settings(CACHES=LOCMEM)
class TheOrcTests(_Base):

    def _full_book(self):
        cfg = _cfg(self.user)
        self.t = _trade(cfg, "XAUUSD")
        _real(cfg, "XAGUSD", entry="30", stop="29", target="33")
        _trade(cfg, "WTIUSD", status="CLOSE_PENDING", entry="70", stop="68",
               target="75")
        _trade(cfg, "NGUSD", status="ERROR", entry="3", stop="2.5", target="4")
        _trade(_manual(self.user), "HGUSD", rule="manual_take",
               meta={"manual": True}, entry="4", stop="3.8", target="4.5")
        _legacy(self.user, "AAPL")

    def test_no_orc_and_no_captain_is_seated(self):
        self._full_book()
        board = self.board()
        self.assertTrue(_seats(board))
        for seat in _seats(board):
            self.assertIsNone(seat["orc"])
        for group in board["groups"]:
            self.assertIsNone(group["captain"])
        self.assertIsNone(self.seat(f"bot:{self.t.id}")["voice"]["orc"])

    def test_the_seams_are_empty(self):
        from dashboard.horde import _captain_slots, _orc_slots
        self.assertEqual(_orc_slots([1, 2]), {})
        self.assertEqual(_captain_slots(self.user, ["forex"]), {})

    def test_every_orc_word_in_a_payload_is_reserved(self):
        self._full_book()
        texts = _strings(self.board()) + _strings(self.seat(f"bot:{self.t.id}"))
        for text in texts:
            for sentence in _sentences(text):
                if ORC_WORD.search(sentence):
                    self.assertTrue(
                        any(sentence.startswith(r) or r.startswith(sentence)
                            or sentence in r or r in sentence
                            for r in RESERVED | {"Today:"}),
                        sentence)

    def test_every_orc_word_in_the_files_is_reserved(self):
        from dashboard import horde
        for r in RESERVED:
            self.assertIn(r, horde.RESERVED_ORC_SENTENCES)
        for path in (PARTIAL, JS, HORDE_PY):
            if not path.exists():
                self.fail(f"{path} does not exist")
            src = path.read_text(encoding="utf-8")
            if path.suffix == ".js":
                src = _strip_js(src)
            if path.suffix == ".py":
                src = "\n".join(re.findall(r'"([^"\n]*)"', src))
            for line in src.splitlines():
                for m in re.finditer(r"[A-Z][^.<>\"]*\b(?:Orc|Orcs|Captain|Captains)\b[^.<>\"]*\.?",
                                     line):
                    frag = m.group(0).strip()
                    self.assertTrue(any(frag in r or r in frag for r in RESERVED)
                                    or frag in ("Orc", "Orcs"),
                                    f"{path.name}: {frag!r}")

    def test_no_orc_verb_anywhere(self):
        verb = re.compile(r"Orc\w*\s+(decided|closed|trimmed|tightened|added|moved|exited)")
        by = re.compile(r"(closed|trimmed|tightened|held|decided) by (the|an) Orc")
        for path in (PARTIAL, JS, HORDE_PY):
            src = path.read_text(encoding="utf-8")
            self.assertIsNone(verb.search(src), path.name)
            for m in by.finditer(src):
                around = src[max(0, m.start() - 40):m.end() + 2]
                self.assertIn("Nothing on this seat was decided by an Orc.", around,
                              path.name)
        self.assertNotRegex(HORDE_PY.read_text(encoding="utf-8"),
                            r'"seat"\s*:\s*\{[^}]*"level"')

    # ── O1d (Orcs spec §9.5): the seams filled, only while orcs is ON ──

    def _orcs_on(self):
        """The book above, an Orc on each bot seat, the switch ON, a wake,
        a drum and the day's weather written as O1c writes them."""
        from bot_program.orcs.models import OrcDayBaseline
        from bot_program.orcs.sessions import trading_day
        from tests.orcs.helpers import (_drum_heard, _paper_cap, _wake_card,
                                        born)
        self._full_book()
        _paper_cap()
        from bot_program.models import AssetBotTrade
        self.orcs = [born(self, t) for t in AssetBotTrade.objects.filter(
            config__user=self.user, status="OPEN")]
        for o in self.orcs:
            _wake_card(o)
            _drum_heard(o)
        OrcDayBaseline.objects.create(
            user=self.user, asset_class="commodity",
            trading_day=trading_day(timezone.now()), day_class="eventful",
            score=44)
        _switches(orcs=True)

    def test_the_seams_fill_when_on(self):
        self._orcs_on()
        board = self.board()
        self.assertEqual(board["v"], 2)
        orcs = {s["key"]: s["orc"] for s in _seats(board) if s["orc"]}
        self.assertIn(f"bot:{self.t.id}", orcs)
        slot = orcs[f"bot:{self.t.id}"]
        self.assertEqual(slot["label"], f"Orc #{self.t.id}")
        self.assertEqual(slot["authority"]["level_t"], "L0 · Snaga")
        self.assertEqual(slot["mode"], "shadow")
        group = next(g for g in board["groups"] if g["key"] == "commodity")
        self.assertEqual(group["captain"], {"day": {
            "class": "eventful", "score_t": "score 44",
            "t": "eventful · score 44"}})
        # a legacy seat is no idea of the Orcs
        self.assertTrue(all(s["orc"] is None for s in _seats(board)
                            if s["key"].startswith("pf:")))
        seat = self.seat(f"bot:{self.t.id}")
        self.assertEqual(seat["v"], 2)
        self.assertEqual(seat["voice"]["orc"]["label"], f"Orc #{self.t.id}")
        self.assertEqual(seat["voice"]["orc_block"],
                         {"present": True, "t": []})
        self.assertEqual(seat["mission"]["thesis"],
                         slot["thesis"]["t"])

    def test_an_unimportable_orcs_package_leaves_the_seams_empty(self):
        from dashboard.horde import _captain_slots, _orc_slots
        self._orcs_on()
        with mock.patch.dict("sys.modules", {"bot_program.orcs.notes": None}):
            self.assertEqual(_orc_slots([self.t.id], on=True), {})
            self.assertEqual(_captain_slots(self.user, ["commodity"],
                                            on=True), {})
            board = self.board()
        for seat in _seats(board):
            self.assertIsNone(seat["orc"])
        for group in board["groups"]:
            self.assertIsNone(group["captain"])

    def test_a_failing_notes_read_never_blanks_the_band(self):
        self._orcs_on()
        with mock.patch("bot_program.orcs.notes.for_rows",
                        side_effect=RuntimeError("boom")), \
                mock.patch("bot_program.orcs.notes.for_classes",
                           side_effect=RuntimeError("boom")), \
                self.assertLogs("dashboard.horde", level="WARNING"):
            board = self.board()
            seat = self.seat(f"bot:{self.t.id}")
        self.assertEqual(len(_seats(board)), 5)
        self.assertTrue(all(s["orc"] is None for s in _seats(board)))
        self.assertIsNone(seat["voice"]["orc"])
        self.assertFalse(seat["voice"]["orc_block"]["present"])

    def test_every_orc_word_in_an_on_payload_is_reserved(self):
        from bot_program.orcs import notes
        self._orcs_on()
        board = self.board()
        seat = self.seat(f"bot:{self.t.id}")
        journal = {j["t"] for s in _seats(board) if s["orc"]
                   for j in s["orc"]["journal"]}
        journal |= {j["t"] for j in seat["voice"]["orc"]["journal"]}
        verb = re.compile(r"Orc\w*\s+(decided|closed|trimmed|tightened|"
                          r"added|moved|exited)")
        for text in _strings(board) + _strings(seat):
            if text in journal:
                self.assertIsNone(verb.search(text), text)
                continue
            for sentence in _sentences(text):
                if ORC_WORD.search(sentence):
                    self.assertTrue(
                        notes.is_reserved(sentence)
                        or any(sentence.startswith(r) or r.startswith(sentence)
                               or sentence in r or r in sentence
                               for r in RESERVED | {"Today:"}),
                        sentence)

    def test_the_lineage_key_is_never_seat(self):
        self._orcs_on()
        for payload in (self.board(), self.seat(f"bot:{self.t.id}")):
            for s in ([x["orc"] for x in _seats(payload) if x["orc"]]
                      if "groups" in payload else [payload["voice"]["orc"]]):
                self.assertIn("lineage", s)
                self.assertNotIn("seat", _keys(s))

    def test_the_contract_is_v2_only_while_on(self):
        self._orcs_on()
        self.assertEqual(self.board()["v"], 2)
        _switches(orcs=False)
        cache.clear()
        board = self.board()
        self.assertEqual(board["v"], 1)
        self.assertEqual(self.seat(f"bot:{self.t.id}")["v"], 1)
        for seat in _seats(board):
            self.assertIsNone(seat["orc"])

    def test_the_ask_facts_are_the_same_on_and_off(self):
        self._orcs_on()
        on = self.seat(f"bot:{self.t.id}")["seat"]["commands"]["ask"]
        _switches(orcs=False)
        cache.clear()
        off = self.seat(f"bot:{self.t.id}")["seat"]["commands"]["ask"]
        self.assertEqual(on, off)

    # ── the plain words (PR68) on an Orc's slot ──────────────────────────

    def _orc_of_t(self):
        return next(o for o in self.orcs if o.root_trade_id == self.t.id)

    def _operator_thesis(self, orc, text):
        from bot_program.orcs import journal
        journal.append(orc, "thesis", "Your thesis: " + text,
                       author="operator",
                       body={"thesis": {"source": "operator", "text": text}})

    def _slot_and_seat(self):
        cache.clear()
        board = self.board()
        slot = next(s["orc"] for s in _seats(board)
                    if s["key"] == f"bot:{self.t.id}")
        return board, slot, self.seat(f"bot:{self.t.id}")

    def test_the_operators_thesis_that_may_name_money_is_withheld_whole(self):
        from dashboard.plain_words import WITHHELD
        self._orcs_on()
        self._operator_thesis(self._orc_of_t(),
                              "risk at the stop 1,234.56 and it still holds")
        board, slot, seat = self._slot_and_seat()
        self.assertEqual(slot["thesis"]["source"], "operator")
        self.assertEqual(slot["thesis"]["t"], WITHHELD)
        self.assertEqual(seat["voice"]["orc"]["thesis"]["t"], WITHHELD)
        self.assertEqual(seat["mission"]["thesis"], WITHHELD)
        mine = [j for j in slot["journal"] if j["author"] == "operator"]
        self.assertTrue(mine)
        self.assertTrue(all(j["t"] == WITHHELD for j in mine))
        for payload in (board, seat):
            self.assertNotIn("1,234.56", json.dumps(payload))

    def test_the_rows_own_amount_is_read_by_value_in_the_thesis(self):
        """The row's amount at its stop (125 × |100 − 98| = 250), said bare,
        with no money word: withheld all the same. A level and an R stay."""
        from bot_program.models import AssetBotTrade
        from dashboard.plain_words import WITHHELD
        self._orcs_on()
        AssetBotTrade.objects.filter(pk=self.t.pk).update(qty=Decimal("125"))
        self._operator_thesis(self._orc_of_t(), "worst case 250 if wrong")
        _board, slot, _seat = self._slot_and_seat()
        self.assertEqual(slot["thesis"]["t"], WITHHELD)
        self._operator_thesis(self._orc_of_t(),
                              "holds above 98.00 for +2R by Friday")
        _board, slot, seat = self._slot_and_seat()
        self.assertEqual(slot["thesis"]["t"],
                         "holds above 98.00 for +2R by Friday")
        self.assertEqual(seat["mission"]["thesis"],
                         "holds above 98.00 for +2R by Friday")

    def test_a_line_that_names_an_exception_is_withheld_whole(self):
        from bot_program.orcs import journal
        from bot_program.orcs.models import Orc
        from dashboard.plain_words import WITHHELD_ERROR
        self._orcs_on()
        orc = self._orc_of_t()
        journal.append(orc, "fact", "The venue now holds the stop at "
                       "1,950.00 (-1.00R).", fact=True)
        journal.append(orc, "fact", "The read failed (OperationalError: "
                       "database is locked).", fact=True)
        self._operator_thesis(orc, "KeyError: 'bias' says the trend is gone")
        Orc.objects.filter(pk=orc.pk).update(
            latest_note="requests.exceptions.ConnectionError at the venue")
        board, slot, seat = self._slot_and_seat()
        for sl in (slot, seat["voice"]["orc"]):
            self.assertEqual(sl["thesis"]["t"], WITHHELD_ERROR)
            self.assertEqual(sl["latest_note"], WITHHELD_ERROR)
            lines = [j["t"] for j in sl["journal"]]
            # a code line in prices and R is kept as written
            self.assertIn("The venue now holds the stop at 1,950.00 "
                          "(-1.00R).", lines)
            self.assertEqual(lines[-2:], [WITHHELD_ERROR, WITHHELD_ERROR])
        for payload in (board, seat):
            text = json.dumps(payload)
            for leak in ("OperationalError", "database is locked",
                         "KeyError", "ConnectionError"):
                self.assertNotIn(leak, text)

    def test_a_fact_code_writes_under_the_operators_name_is_codes(self):
        """A hand edit's fact (bot_program/orcs/facts.py) is written by
        code with author "operator": a price and an R, never his words. A
        price that sits near the row's amount at its stop (50 x |100 - 98|
        = 100) is no amount: the line shows as written, as the same
        sentence by code does. Only his thesis entries are a voice's."""
        from bot_program.models import AssetBotTrade
        from bot_program.orcs import journal
        from dashboard.plain_words import WITHHELD
        self._orcs_on()
        AssetBotTrade.objects.filter(pk=self.t.pk).update(qty=Decimal("50"))
        orc = self._orc_of_t()
        hand = ("A hand edit set the venue's stop at 99.00 (-0.50R). The "
                "grade counts it as a hand act.")
        journal.append(orc, "fact", "The venue now holds the stop at 99.00 "
                       "(-0.50R).", fact=True)
        journal.append(orc, "fact", hand, author="operator", fact=True)
        self._operator_thesis(orc, "worst case 100 if it fails")
        board, slot, seat = self._slot_and_seat()
        for sl in (slot, seat["voice"]["orc"]):
            lines = {(j["author"], j["kind"]): j["t"] for j in sl["journal"]}
            self.assertEqual(lines[("operator", "fact")], hand)
            self.assertEqual(lines[("code", "fact")],
                             "The venue now holds the stop at 99.00 "
                             "(-0.50R).")
            # his own thesis entry naming the row's amount bare is withheld
            self.assertEqual(lines[("operator", "thesis")], WITHHELD)
            self.assertEqual(sl["thesis"]["t"], WITHHELD)

    def test_the_plain_words_never_change_the_slot_they_read(self):
        """The entry's own reason is a voice on the seat (the operator's
        thesis already passes the plain words in notes.slot): the Horde
        withholds it on a copy and leaves the slot it read as it was."""
        from bot_program.orcs.models import Orc
        from bot_program.orcs.notes import for_rows
        from dashboard.horde import _orc_slots
        self._orcs_on()
        orc = self._orc_of_t()
        Orc.objects.filter(pk=orc.pk).update(
            thesis={**orc.thesis, "reason": "KeyError says so"})
        raw = for_rows([self.t.id], user=self.user)
        before = json.dumps(raw, sort_keys=True, default=str)
        with mock.patch("bot_program.orcs.notes.for_rows", return_value=raw):
            shown = _orc_slots([self.t.id], on=True, user=self.user,
                               trades=[self.t])
        self.assertEqual(json.dumps(raw, sort_keys=True, default=str), before)
        self.assertEqual(raw[f"bot:{self.t.id}"]["thesis"]["t"],
                         "KeyError says so")
        self.assertNotEqual(shown[f"bot:{self.t.id}"]["thesis"]["t"],
                            "KeyError says so")


# ── 13.5 the ceiling (rule 5) ────────────────────────────────────────────

@override_settings(CACHES=LOCMEM)
class TheCeilingTests(_Base):

    def setUp(self):
        super().setUp()
        self.cfg = _cfg(self.user, cls="crypto", symbols=["BTCUSD"], mode="paper")
        _quote("BTCUSD", "101", cls="crypto", source="binance_public")
        _quote("ETHUSD", "50", cls="crypto", source="binance_public")
        from portfolio.services import get_or_create_default_portfolio
        get_or_create_default_portfolio(user=self.user)

    def _bots(self, n):
        """n seats over a growing set of configs (a bot, the manual lane, a
        braked bot, then one more bot per ten seats), so a read per CONFIG
        shows in the count as surely as a read per row."""
        if not hasattr(self, "_cfgs"):
            from bot_program.asset_engine import disarm
            braked = _cfg(self.user, cls="crypto", name="braked", mode="paper",
                          symbols=["ETHUSD"])
            disarm.disable_config(braked, by=disarm.BY_BOT_BRAKE, why="t", who="u")
            braked.refresh_from_db()
            self._cfgs = [self.cfg, _manual(self.user, cls="crypto"), braked]
        for i in range(n):
            k = len(getattr(self, "_made", []))
            if k and k % 10 == 0:
                self._cfgs.append(_cfg(self.user, cls="crypto", name=f"more{k}",
                                       mode="paper", symbols=["BTCUSD"]))
            cfg = self._cfgs[k % len(self._cfgs)]
            self._made = getattr(self, "_made", []) + [
                _trade(cfg, "BTCUSD" if i % 2 else "ETHUSD",
                       rule="manual_take" if cfg.name == "manual" else "golden_cross",
                       meta={"stop_moves": [{"to": "99", "why": "trail"}],
                             "care": {"soft_stop": 99.0, "soft_why": "breakeven",
                                      "since": timezone.now().isoformat()}})]
        return self._made

    def _count(self, fn):
        with CaptureQueriesContext(connection) as ctx:
            fn()
        return len(ctx.captured_queries)

    def _board_warm(self):
        from dashboard import horde
        horde.board(self.user)                   # warms Block B
        return self._count(lambda: horde.board(self.user))

    def test_a_warm_board_costs_the_same_for_3_and_30_seats(self):
        self._bots(3)
        small = self._board_warm()
        self._bots(27)
        cache.clear()
        big = self._board_warm()
        self.assertEqual(small, big)
        self.assertEqual(big, 10)

    def _with_orcs(self):
        from bot_program.models import AssetBotTrade
        from tests.orcs.helpers import _drum_heard, _paper_cap, born
        _paper_cap()
        for t in AssetBotTrade.objects.filter(config__user=self.user,
                                              status="OPEN"):
            orc = born(self, t)
            if orc is not None:
                _drum_heard(orc)
        _switches(orcs=True)

    def test_a_warm_board_with_orcs_costs_the_same_for_3_and_30_seats(self):
        """O1d: ON, the seats' notes are two reads (the legs with their
        Orc, seat and row; the arms) and the bands' one (the day), whatever
        the seat count; the switch rides the batch."""
        self._bots(3)
        self._with_orcs()
        small = self._board_warm()
        self._bots(27)
        self._with_orcs()
        cache.clear()
        big = self._board_warm()
        self.assertEqual(small, big)
        self.assertEqual(big, 13)

    def test_the_seat_detail_with_an_orc_stays_within_16(self):
        from dashboard import horde
        t = self._bots(2)[0]
        self._with_orcs()
        horde.seat_detail(self.user, f"bot:{t.id}")
        n = self._count(lambda: horde.seat_detail(self.user, f"bot:{t.id}"))
        self.assertLessEqual(n, 16)
        self.assertEqual(n, 15)

    def test_legacy_rows_cost_one_more_whatever_their_number(self):
        self._bots(2)
        _legacy(self.user, "AAPL")
        one = self._board_warm()
        for s in ("MSFT", "IBM", "ORCL", "NVDA"):
            _legacy(self.user, s)
        cache.clear()
        five = self._board_warm()
        self.assertEqual(one, five)
        self.assertEqual(five, 11)

    def test_a_cold_board_costs_the_same_for_3_and_30_seats(self):
        """Block B cold. The first read ever also creates the shared Main
        book (risk_gate.limits_book), so it is taken once before counting."""
        from dashboard import horde
        horde.board(self.user)
        self._bots(3)
        cache.clear()
        small = self._count(lambda: horde.board(self.user))
        self._bots(27)
        cache.clear()
        big = self._count(lambda: horde.board(self.user))
        self.assertEqual(small, big)

    def test_the_tab_is_cached_on_the_fingerprint(self):
        from dashboard import horde
        self._bots(3)
        first = horde.tab(self.user)
        n = self._count(lambda: horde.tab(self.user))
        self.assertEqual(n, 4)
        self.assertEqual(horde.tab(self.user)["seats"], first["seats"])
        _trade(self.cfg, "BTCUSD")
        self.assertEqual(horde.tab(self.user)["seats"], first["seats"] + 1)
        # A row of the hand-kept book is in the fingerprint too: opening
        # one moves the cached tab at once.
        _legacy(self.user, "AAPL")
        moved = horde.tab(self.user)
        self.assertEqual(moved["seats"], first["seats"] + 2)
        self.assertEqual(moved["by_world"]["none"], 1)

    def test_the_seat_detail_does_not_grow_with_its_history(self):
        from alerts.models import Notification
        from bot_program.aragorn_models import AragornAction
        from dashboard import horde

        def make(moves, notes, reviews, actions, sym):
            t = _trade(self.cfg, sym, meta={"stop_moves": [
                {"to": "99", "asked": "99", "at": "100", "why": "trail:broker",
                 "when": timezone.now().isoformat()}] * moves})
            for _ in range(notes):
                Notification.objects.create(user=self.user, notification_type="bot",
                                            title="Filled", url=f"/forensics/{t.id}/")
            for _ in range(reviews):
                _review(f"bot:{t.id}", verdict="hold", user=self.user, symbol=sym)
            for _ in range(actions):
                AragornAction.objects.create(kind="care_mirror", trade_id=t.id,
                                             detail="REAL MONEY: moved")
            return t
        a = make(2, 1, 1, 1, "BTCUSD")
        b = make(20, 10, 10, 10, "ETHUSD")
        horde.seat_detail(self.user, f"bot:{a.id}")
        horde.seat_detail(self.user, f"bot:{b.id}")
        small = self._count(lambda: horde.seat_detail(self.user, f"bot:{a.id}"))
        big = self._count(lambda: horde.seat_detail(self.user, f"bot:{b.id}"))
        self.assertEqual(small, big)
        # §9.4: at most 16. Here 13: the seat and the viewer's other open
        # rows (one read), its Instrument and LiveQuote, the rule's stage,
        # the care's actions, the notices, the reviews, the switches, the
        # peers' Instruments, the matrix on its cache hit (3) and the peers'
        # quotes.
        self.assertLessEqual(big, 16)
        self.assertEqual(big, 13)

    def test_the_forbidden_readers_are_never_called(self):
        """Patched to raise, AND asserted never called: the head's reads
        (Block B) and a legacy seat's shaping swallow their errors (the
        seats are still served), so a 200 alone proves nothing. Nothing
        may degrade either: the head stays readable and every seat is
        there, the legacy one and its dossier included."""
        self._bots(2)
        t = _trade(self.cfg, "BTCUSD")
        pos = _legacy(self.user, "AAPL")
        boom = mock.Mock(side_effect=AssertionError("forbidden reader"))
        with mock.patch("dashboard.position_summary.build_summary", boom), \
                mock.patch("bot_program.manual_close.preview_close", boom), \
                mock.patch("portfolio.correlation.compute_correlation", boom), \
                mock.patch("portfolio.risk_gate.correlation_state", boom), \
                mock.patch("brain.close_advice.advise", boom), \
                mock.patch("bot_program.manual_close._risk_dollars", boom), \
                mock.patch("core.platform_control.is_component_enabled", boom):
            r = self.client.get(URL)
            self.assertEqual(r.status_code, 200)
            board = r.json()
            r = self.client.get(URL, {"part": "tab"})
            self.assertEqual(r.status_code, 200)
            tab = r.json()
            self.assertEqual(self.client.get(URL, {"seat": f"bot:{t.id}"}).status_code, 200)
            self.assertEqual(self.client.get(URL, {"seat": f"pf:{pos.id}"}).status_code, 200)
        boom.assert_not_called()
        self.assertTrue(board["head"]["readable"], board["head"].get("t"))
        self.assertEqual(len(_seats(board)), 4)
        self.assertIn(f"pf:{pos.id}", {s["key"] for s in _seats(board)})
        self.assertIsNone(tab["flag"])

    def test_the_forbidden_guard_sees_the_head(self):
        """The guard above is not blind to Block B: a forbidden reader
        called from the head fails it (the review planted close_advice in
        _head_raw and 99 tests stayed green)."""
        from brain import close_advice
        from dashboard import horde
        self._bots(1)
        boom = mock.Mock(side_effect=AssertionError("forbidden reader"))
        real = horde._head_raw

        def planted(user, fp, now):
            close_advice.advise(user, [])
            return real(user, fp, now)
        with mock.patch("brain.close_advice.advise", boom), \
                mock.patch.object(horde, "_head_raw", planted), \
                self.assertLogs("dashboard.horde", level="WARNING"):
            board = self.client.get(URL).json()
        self.assertTrue(boom.called)
        self.assertFalse(board["head"]["readable"])

    def test_a_legacy_forex_row_reads_its_rate_once_per_currency(self):
        """usd_per_unit reads the quote currency's USD rate (portfolio/
        services.py quote_ccy_usd_rate: two reads for a yen row). Once per
        CURRENCY for the pass, never per row: three more yen rows (USDJPY
        twice, GBPJPY) cost nothing more on the poll."""
        _quote("USDJPY", "150", cls="forex")
        _quote("GBPJPY", "190", cls="forex")
        _legacy(self.user, "USDJPY", cls="forex", qty="1000", entry="149")
        one = self._board_warm()
        _legacy(self.user, "USDJPY", cls="forex", qty="1000", entry="148")
        _legacy(self.user, "USDJPY", cls="forex", qty="500", entry="151")
        _legacy(self.user, "GBPJPY", cls="forex", qty="1000", entry="189")
        cache.clear()
        four = self._board_warm()
        self.assertEqual(one, four)
        # And the rate is read at all: without a legacy forex row the same
        # book costs less (the yen's two reads are the difference).
        from portfolio.models import Position
        Position.objects.filter(instrument__asset_class="forex").delete()
        _legacy(self.user, "AAPL")
        cache.clear()
        self.assertLess(self._board_warm(), one)

    def test_the_rate_memo_never_crosses_currencies(self):
        from types import SimpleNamespace

        from portfolio.services import usd_per_unit
        rates = {}
        seen = []

        def rate(ccy):
            seen.append(ccy)
            return {"JPY": 0.0067, "CHF": 1.1}.get(ccy)
        row = lambda s: SimpleNamespace(value_per_unit=None, asset_class="forex",  # noqa: E731
                                         instrument=SimpleNamespace(symbol=s,
                                                                    asset_class="forex"))
        with mock.patch("bot_program.asset_engine.forex_bot.quote_ccy_usd_rate", rate):
            got = [usd_per_unit(row(s), rates)
                   for s in ("USDJPY", "GBPJPY", "EURCHF", "USDJPY", "EURSEK", "EURSEK")]
        self.assertEqual(got, [0.0067, 0.0067, 1.1, 0.0067, None, None])
        self.assertEqual(seen, ["JPY", "CHF", "SEK"])


# ── 13.6 the markup ──────────────────────────────────────────────────────

@override_settings(CACHES=LOCMEM)
class TheMarkupTests(TestCase):

    def setUp(self):
        cache.clear()

    def test_the_partial_has_no_script_no_style_no_live_region(self):
        src = PARTIAL.read_text(encoding="utf-8")
        for word in ("<script", "<style", "data-sv-live", "data-sv-live-key"):
            self.assertNotIn(word, src, word)
        self.assertIn("{% url 'horde_feed' %}", src)

    def test_the_tab_is_a_real_button(self):
        src = PARTIAL.read_text(encoding="utf-8")
        m = re.search(r'<button[^>]*id="svHordeTab"[^>]*>', src, re.S)
        self.assertIsNotNone(m)
        self.assertIn('aria-expanded="false"', m.group(0))
        self.assertIn('aria-controls="svHordePanel"', m.group(0))

    def test_the_grip_is_a_window_splitter(self):
        src = PARTIAL.read_text(encoding="utf-8")
        m = re.search(r'<div[^>]*id="svHordeGrip"[^>]*>', src, re.S)
        self.assertIsNotNone(m)
        for attr in ('role="separator"', "aria-orientation=", "aria-valuemin=",
                     "aria-valuemax=", "aria-valuenow=", 'tabindex="0"'):
            self.assertIn(attr, m.group(0), attr)

    def test_the_open_sheet_counts_its_own_seats(self):
        """A phone hides the pill while the sheet is open; the head carries
        the seat count and the alarm chip instead (§3.8)."""
        src = PARTIAL.read_text(encoding="utf-8")
        head = src[src.index('id="svHordeHead"'):src.index("</header>")]
        self.assertIn('id="svHordeCount"', head)
        self.assertIn("getElementById('svHordeCount')", _strip_js(JS.read_text(encoding="utf-8")))

    def test_the_announcer_sits_outside_the_inert_panel(self):
        src = PARTIAL.read_text(encoding="utf-8")
        say = src.index('id="svHordeSay"')
        panel = src.index('id="svHordePanel"')
        self.assertLess(say, panel)
        self.assertIn('aria-live="polite"', src[say - 80:say + 80])

    def test_it_renders_once_for_a_member_and_never_for_a_visitor(self):
        user = _user("horde_page")
        self.client.force_login(user)
        body = self.client.get("/getting-started/").content.decode()
        self.assertEqual(body.count('id="svHorde"'), 1)
        self.assertIn('data-horde-url="/api/horde/"', body)
        # Signed in, the public pages still carry no Horde: they are their
        # own documents, not base.html.
        for path in ("/wall/", "/book/"):
            r = self.client.get(path)
            self.assertNotIn("svHorde", r.content.decode(), path)
        self.client.logout()
        for path in ("/login/", "/wall/", "/book/", "/", "/positions/"):
            r = self.client.get(path, follow=True)
            self.assertEqual(r.status_code, 200, path)
            self.assertNotIn("svHorde", r.content.decode(), path)

    def test_the_shell_pages_render_for_staff_and_members_with_seats(self):
        """A staff reader and a member, each with a book of every kind, get
        the shell pages with the Horde once and its door answers all three
        parts; the member never reads the staff reader's seats."""
        _all_on()
        pages = ("/getting-started/", "/positions/", "/portfolio/", "/signals/")
        keys = {}
        for name, staff in (("horde_staff_page", True), ("horde_member_page", False)):
            user = _user(name, staff=staff)
            cfg = _cfg(user, name=f"{name}-bot")
            open_row = _real(cfg, "XAUUSD")
            _trade(cfg, "XAGUSD", entry="30", stop="29", target="33",
                   status="CLOSE_PENDING")
            _trade(cfg, "WTIUSD", status="ERROR", entry="70", stop="68", target="75")
            _legacy(user, "AAPL")
            self.client.force_login(user)
            cache.clear()
            for path in pages:
                r = self.client.get(path)
                self.assertEqual(r.status_code, 200, (name, path))
                body = r.content.decode()
                self.assertEqual(body.count('id="svHorde"'), 1, (name, path))
                self.assertIn('id="svHordeSeats">3 seats<', body, (name, path))
            board = self.client.get(URL).json()
            keys[name] = {s["key"] for g in board["groups"] for s in g["seats"]}
            self.assertEqual(len(keys[name]), 3, name)
            self.assertEqual(self.client.get(URL, {"part": "tab"}).json()["seats"], 3)
            self.assertEqual(self.client.get(URL, {"seat": f"bot:{open_row.id}"})
                             .status_code, 200)
            self.client.logout()
        self.assertFalse(keys["horde_staff_page"] & keys["horde_member_page"])

    def test_it_sits_outside_the_band_and_adds_no_refresher(self):
        from tests.test_headband_truth import _headband_source
        self.assertNotIn("the_horde.html", _headband_source())
        user = _user("horde_shell")
        self.client.force_login(user)
        body = self.client.get("/signals/").content.decode()
        self.assertIn('id="svHorde"', body)
        self.assertEqual(body.count("var LIVE_URL ="), 1)
        base = _read("templates", "base.html")
        inc = ('{% if request.user.is_authenticated %}{% include '
               '"_partials/the_horde.html" %}{% endif %}')
        self.assertEqual(base.count("the_horde.html"), 1)
        self.assertIn(inc, base)
        self.assertGreater(base.index(inc), base.index("activity_drawer.html"))
        self.assertGreater(base.index(inc), base.index('<div class="page-content'))
        self.assertGreater(base.index(inc), base.index("</main>"))

    def test_the_sheet_and_script_are_linked_once_in_order(self):
        base = _read("templates", "base.html")
        self.assertEqual(base.count("'css/sv-horde.css'"), 1)
        at = base.index("'css/sv-horde.css'")
        self.assertGreater(at, base.index("'css/sv-activity.css'"))
        self.assertLess(at, base.index("'css/sv-responsive.css'"))
        self.assertEqual(base.count("'js/sv-horde.js'"), 1)
        self.assertIn('<script src="{% static \'js/sv-horde.js\' %}" defer></script>',
                      base)
        self.assertGreater(base.index("'js/sv-horde.js'"),
                           base.index("'js/sv-activity.js'"))
        self.assertLess(base.index("'js/sv-horde.js'"), base.index("</head>"))

    def test_h_toggles_the_horde_and_the_shortcut_is_listed(self):
        base = _read("templates", "base.html")
        self.assertIn('<span class="kbd-label">Toggle the Horde</span>'
                      '<span class="kbd-keys"><kbd>h</kbd></span>', base)
        g = base.index("if (gPressed)")
        h = base.index("key === 'h'")
        self.assertGreater(h, g)
        self.assertIn("window.SVHorde.toggle('key')", base[h:h + 200])

    def test_no_horde_node_is_a_position_row(self):
        for path in (PARTIAL, JS):
            self.assertNotIn("data-sv-position-row", path.read_text(encoding="utf-8"))

    def test_every_word_the_script_asks_for_is_in_the_template(self):
        src = PARTIAL.read_text(encoding="utf-8")
        have = set(re.findall(r'data-w="([a-z0-9_]+)"', src))
        want = set(re.findall(r"\bW\('([a-z0-9_]+)'", _strip_js(JS.read_text(encoding="utf-8"))))
        self.assertTrue(want)
        self.assertEqual(want - have, set())
        for line in ("Mustering the Horde", "THE HORDE", "Toggle the Horde",
                     "Locked. Unlock Sauron to see the Horde.",
                     "Signed out. Sign in again to see the Horde.",
                     "Resize the Horde", "Back to the Horde",
                     "Should I close?", "Stop / target…", "opens a confirmation",
                     "No Orc seated.", "Nothing on this seat was decided by an Orc."):
            self.assertIn(line, src + _read("templates", "base.html"), line)


# ── 13.7 the sheet ───────────────────────────────────────────────────────

class TheSheetTests(SimpleTestCase):

    def setUp(self):
        self.css = _strip_css(SHEET.read_text(encoding="utf-8"))
        self.ladder = _read("static", "css", "sv-overlay.css")

    def _rule(self, selector, text=None):
        m = re.search(r"(?:^|\})\s*" + re.escape(selector) + r"\s*\{([^}]*)\}",
                      text or self.css)
        self.assertIsNotNone(m, selector)
        return " ".join(m.group(1).split())

    def test_tokens_and_rungs_only(self):
        zs = re.findall(r"z-index\s*:\s*([^;]+);", self.css)
        self.assertTrue(zs)
        for z in zs:
            self.assertRegex(z.strip(), r"^(calc\()?var\(--z-", z)
        self.assertEqual(re.findall(r"#[0-9a-fA-F]{3,8}\b", self.css), [])
        self.assertNotRegex(self.css, r"rgba?\(")
        self.assertNotRegex(self.css, r"animation[^;{}]*\b(forwards|both)\b")

    def test_the_offsets_follow_the_strip(self):
        self.assertIn("--ip-h: 60px;", self._rule("body:has(.info-panel-wrap)"))
        self.assertRegex(self.css, r"body:has\(\.info-panel-wrap\.minimized\),\s*"
                                   r"body\.page-dashboard\s*\{\s*--ip-h: 0px;")
        self.assertIn("left: 68px;", self._rule("body:has(.sidebar.mini) .sv-horde"))
        self.assertIn("right: 44px;", self._rule("body:has(.signals-rail) .sv-horde"))
        m = re.search(r"@media \(min-width: 769px\) \{(.*?)\n\}", self.css, re.S)
        self.assertIsNotNone(m)
        block = m.group(1)
        self.assertRegex(block, r"body:has\(\.signals-rail\.open\) \.sv-horde \{ right: 280px;")
        self.assertRegex(block, r"body:has\(\.sv-activity\.open\) \.sv-horde \{ right: 404px;")
        self.assertRegex(block, r"body:has\(\.signals-rail\.open\):has\(\.sv-activity\.open\) "
                                r"\.sv-horde \{ right: 640px;")
        root = self._rule(".sv-horde")
        for decl in ("position: fixed;", "bottom: var(--ip-h, 0px);",
                     "height: var(--horde-h, 360px);", "z-index: var(--z-horde);",
                     "transform: translateY(100%);"):
            self.assertIn(decl, root, decl)
        self.assertIn("transform: none;", self._rule(".sv-horde.open"))

    def test_a_minimized_strip_moves_the_tab_clear_of_its_pill(self):
        """The strip's SHOW PANEL pill is centred on the VIEWPORT
        (sauron.css .ip-restore-pill, left: 50%), the root on the space
        between the sidebar and the rail: with the full sidebar the closed
        tab sat under the pill (measured at 1440x900: tab 336-744, pill
        651-789). Minimized, the tab starts right of the pill and of the
        strip's minimize tab, from the edges the root's own rules declare,
        on a wide screen only (a phone marks the strip minimized too)."""
        for sel, decl in ((".sv-horde", "--hd-l: var(--sidebar-width);"),
                          (".sv-horde", "--hd-r: 0px;"),
                          ("body:has(.sidebar.mini) .sv-horde", "--hd-l: 68px;"),
                          ("body:has(.signals-rail) .sv-horde", "--hd-r: 44px;")):
            self.assertIn(decl, self._rule(sel), (sel, decl))
        blocks = re.findall(r"@media \(min-width: 769px\) \{(.*?)\n\}", self.css, re.S)
        moved = [b for b in blocks
                 if "body:has(.info-panel-wrap.minimized) .sv-horde-tab" in b]
        self.assertEqual(len(moved), 1)
        # Round 2: LEFT of the pill (viewport centre - 84) and of the
        # strip's own minimize tab, as in every other state.
        rule = self._rule("body:has(.info-panel-wrap.minimized) .sv-horde-tab", moved[0])
        self.assertIn("right: max(calc(50% + 40px), "
                      "calc(50% + (var(--hd-l) - var(--hd-r)) / 2 + 84px));", rule)
        # Where even the narrowest tier has no room there, right of the
        # pill (viewport centre + 84) and of the strip's own minimize tab.
        alt = self._rule("body:has(.info-panel-wrap.minimized) .sv-horde.hd-tab-alt .sv-horde-tab",
                         moved[0])
        self.assertIn("right: auto;", alt)
        self.assertIn("left: max(calc(50% + (var(--hd-r) - var(--hd-l)) / 2 + 84px), "
                      "calc(50% + (var(--hd-r) - var(--hd-sr)) / 2 + 40px));", alt)
        for b in blocks:
            for w in ("280px", "404px", "640px"):
                if f"right: {w};" in b:
                    self.assertIn(f"--hd-r: {w};", b, w)
        # The strip learns the rail, never the activity drawer.
        self.assertIn("--hd-sr: 0px;", self._rule(".sv-horde"))
        self.assertIn("--hd-sr: 44px;", self._rule("body:has(.signals-rail) .sv-horde"))
        wide = [b for b in blocks if "body:has(.signals-rail.open) .sv-horde {" in b][0]
        self.assertIn("--hd-sr: 280px;", self._rule("body:has(.signals-rail.open) .sv-horde", wide))
        for sel in ("body:has(.sv-activity.open) .sv-horde",
                    "body:has(.signals-rail.open):has(.sv-activity.open) .sv-horde"):
            self.assertNotIn("--hd-sr", self._rule(sel, wide), sel)

    def _css_px(self, expr, root_w, **var):
        """A calc()/max() of the tab rule, evaluated for one layout."""
        e = expr
        for k, v in var.items():
            e = e.replace(f"var(--{k.replace('_', '-')})", f"({v})")
        e = e.replace("100%", f"({root_w})").replace("50%", f"({root_w / 2})")
        e = re.sub(r"(\d)px", r"\1", e).replace("calc(", "(")
        self.assertRegex(e, r"^[\d\s().+\-*/,maxin]+$", e)
        return eval(e, {"__builtins__": {}}, {"max": max, "min": min})  # noqa: S307

    def test_the_minimized_tab_clears_the_strips_own_tab(self):
        """Measured layouts (2026-10-15 review): the drawer open moves the
        root's edge, not the strip's, and the tab had slid under the
        strip's minimize tab. The rule's own arithmetic, per layout: the
        tab starts right of the pill and of the minimize tab and ends
        inside the root."""
        blocks = re.findall(r"@media \(min-width: 769px\) \{(.*?)\n\}", self.css, re.S)
        moved = [b for b in blocks
                 if "body:has(.info-panel-wrap.minimized) .sv-horde-tab" in b][0]
        rule = self._rule("body:has(.info-panel-wrap.minimized) .sv-horde.hd-tab-alt .sv-horde-tab",
                          moved)
        left = re.search(r"left: (max\(.*?\));", rule).group(1)
        width = re.search(r"max-width: (calc\(.*\));", rule).group(1)
        # (viewport, sidebar, root's right edge, strip's right edge): the
        # drawer open with the full sidebar (the measured overlap), the
        # rail closed, the mini sidebar with the drawer, the rail open.
        for vw, l, r, sr in ((1380, 260, 404, 44), (1380, 260, 44, 44), (1380, 68, 404, 44),
                             (1100, 68, 280, 280), (1380, 260, 0, 0)):
            root_w = vw - l - r
            x = l + self._css_px(left, root_w, hd_l=l, hd_r=r, hd_sr=sr, se_fab_size=56)
            w = self._css_px(width, root_w, hd_l=l, hd_r=r, hd_sr=sr, se_fab_size=56)
            strip_mid = l + (vw - l - sr) / 2
            self.assertGreaterEqual(x, strip_mid + 32, (vw, l, r, sr))       # the minimize tab
            self.assertGreaterEqual(x, vw / 2 + 70, (vw, l, r, sr))         # the pill
            self.assertLessEqual(x + max(w, 0), vw - r, (vw, l, r, sr))     # inside the root
        # Round 2, the usual place: LEFT of the pill and of the minimize
        # tab, clear of Gollum (74px inside the root's left edge).
        rule = self._rule("body:has(.info-panel-wrap.minimized) .sv-horde-tab", moved)
        right = re.search(r"right: (max\(.*?\));", rule).group(1)
        width = re.search(r"max-width: (calc\(.*\));", rule).group(1)
        for vw, l, r, sr in ((1380, 260, 404, 44), (1380, 260, 44, 44), (1380, 68, 404, 44),
                             (1100, 68, 280, 280), (1380, 260, 0, 0), (1440, 260, 44, 44)):
            root_w = vw - l - r
            x_r = vw - r - self._css_px(right, root_w, hd_l=l, hd_r=r, hd_sr=sr)
            w = self._css_px(width, root_w, hd_l=l, hd_r=r, hd_sr=sr)
            strip_mid = l + (vw - l - sr) / 2
            self.assertLessEqual(x_r, strip_mid - 32, (vw, l, r, sr))       # the minimize tab
            self.assertLessEqual(x_r, vw / 2 - 70, (vw, l, r, sr))          # the pill
            self.assertGreaterEqual(x_r - w, l + 74, (vw, l, r, sr))        # Gollum
            self.assertGreater(w, 200, (vw, l, r, sr))                      # room for a tier

    def test_the_alarms_and_the_real_pill_never_clip(self):
        """Spec §4.1 and rule 3: the alarm segment never hides and the REAL
        pill is on the tab. No segment is ever cut (2026-10-16: at 1380
        every one ended in an ellipsis, numbers included): each keeps its
        whole width and a tier drops whole segments, chosen by the
        script from the measured content (TheScreenshotReviewScriptTests)."""
        self.assertIn("flex-shrink: 0;", self._rule(".sv-horde-tab > *"))
        self.assertNotIn("text-overflow", self.css[self.css.index(".sv-horde-tab {"):
                                                   self.css.index(".sv-horde-panel {")])
        hides = re.findall(r"([^{}]+)\{\s*display: none;\s*\}", self.css)
        for sel in hides:
            self.assertNotIn(".hd-tab-real", sel, sel)
            self.assertNotIn(".hd-tab-alarms", sel, sel)
            for line in sel.split(","):
                if ".hd-tab-" in line:
                    self.assertRegex(line.strip(), r"^\.sv-horde\.hd-t-[ms] \.hd-tab-", line)
        phone = re.search(r"@media \(max-width: 768px\) \{(.*?)\n\}", self.css, re.S).group(1)
        self.assertNotIn("info-panel-wrap.minimized", phone)

    def test_the_tab_and_the_body(self):
        """The tab ends 40px left of the root's centre (clear of the strip's
        32px-wide-each-side minimize tab, whose centre is at or right of the
        root's) and starts clear of Gollum (18-74px inside the root): its
        room is half the root less 122px. The body keeps the floating
        controls in its side gutters, never over its content."""
        tab = self._rule(".sv-horde-tab")
        self.assertIn("top: -28px;", tab)
        self.assertIn("right: calc(50% + 40px);", tab)
        self.assertIn("max-width: calc(50% - 122px);", tab)
        body = self._rule(".hd-body")
        self.assertIn("padding: 0 var(--hd-gut-r) 0 var(--hd-gut-l);", body)

    def test_reduced_motion(self):
        m = re.search(r"@media \(prefers-reduced-motion: reduce\) \{(.*?)\n\}",
                      self.css, re.S)
        self.assertIsNotNone(m)
        block = m.group(1)
        for sel in (".sv-horde", ".sv-horde-panel", ".sv-horde-tab", ".hd-dossier",
                    ".hd-light--alarm", "#svHordeTab.gl-pointed"):
            self.assertIn(sel, block, sel)
        self.assertIn("transition: none", block)
        self.assertIn("animation: none", block)

    def test_reduced_motion_outweighs_the_phone_sheet(self):
        """The phone tier's .sv-horde.open .sv-horde-panel (0,3,0) slides the
        sheet; a reduced-motion rule at .sv-horde-panel (0,1,0) lost to it."""
        m = re.search(r"@media \(prefers-reduced-motion: reduce\) \{(.*?)\n\}",
                      self.css, re.S)
        self.assertIn(".sv-horde.open .sv-horde-panel", m.group(1))
        self.assertIn(".sv-horde .sv-horde-panel", m.group(1))

    def test_the_command_bar_sticks_on_every_width(self):
        """C5: the money buttons sit in the dossier's sticky bar. Its inset
        is 0 on every width: a sticky inset is measured inside the
        scroller's padding, and .hd-body's bottom padding already clears
        the floating buttons, so lifting it by them again floated it into
        the sticky head (2026-10-15: -13px at 1024x768, -32px at
        1100x700). Below the dossier column only the bar sticks, and a
        phone folds the war table while a seat is open."""
        phone = re.search(r"@media \(max-width: 768px\) \{(.*?)\n\}", self.css, re.S)
        wide = self.css.replace(phone.group(0), "")
        bar = self._rule(".hd-dos-cmdbar", wide)
        self.assertIn("position: sticky;", bar)
        self.assertIn("bottom: 0;", bar)
        self.assertNotIn("se-fab", bar)
        # The scrollers that hold the bar have no bottom padding: a sticky
        # inset is measured inside it (2026-10-16: text bled under the bar
        # through the dossier's 10px, and the phone's bar floated 82px up).
        self.assertIn("padding: 0 var(--hd-gut-r) 0 var(--hd-gut-l);", self._rule(".hd-body"))
        self.assertRegex(self._rule(".hd-dossier"), r"padding: 0 10px;")
        self.assertIn("position: static;", self._rule(".sv-horde:not(.hd-w-l) .hd-dos-head"))
        self.assertIn("position: sticky;", self._rule(".hd-dos-head"))
        self.assertIn("bottom: 0;", self._rule(".hd-dos-cmdbar", phone.group(1)))
        self.assertIn("display: none;", self._rule(".sv-horde.hd-has-seat #svHordeTable",
                                                   phone.group(1)))
        js = _strip_js(JS.read_text(encoding="utf-8"))
        self.assertIn("add(seatBox, el('div', 'hd-cmds hd-dos-cmdbar'))", js)

    def test_the_headband_restore_tabs_stand_on_the_chrome_rung(self):
        """A collapsed headband gives its height to a FULL sheet; its
        restore tab (sauron.css z-index 80) was then under the sheet, the
        only way back covered."""
        self.assertIn(".hb-restore-tab { z-index: var(--z-chrome) !important; }", self.ladder)
        z = {k: int(v) for k, v in re.findall(r"--z-([a-z-]+):\s*(\d+)", self.ladder)}
        self.assertGreater(z["chrome"], z["horde"])

    def test_the_warnings_have_their_own_box(self):
        """The head pins the summary line and the warnings; the war table's
        cells stand in the body, at its top, and scroll with the bands as
        one unit (2026-10-16)."""
        partial = PARTIAL.read_text(encoding="utf-8")
        head = partial[partial.index('id="svHordeHead"'):partial.index("</header>")]
        self.assertLess(head.index('id="svHordeSum"'), head.index('id="svHordeNotes"'))
        self.assertNotIn('id="svHordeTable"', head)
        body = partial[partial.index('id="svHordeBody"'):]
        self.assertLess(body.index('id="svHordeTable"'), body.index('id="svHordeBands"'))
        notes = self._rule(".hd-notes")
        self.assertIn("flex-direction: column;", notes)
        self.assertNotIn("max-height", notes)

    def test_the_phone_tier(self):
        m = re.search(r"@media \(max-width: 768px\) \{(.*?)\n\}", self.css, re.S)
        self.assertIsNotNone(m)
        block = m.group(1)
        root = re.search(r"\.sv-horde\s*\{([^}]*)\}", block)
        self.assertIsNotNone(root)
        for decl in ("position: fixed", "width: 0", "height: 0", "transform: none"):
            self.assertIn(decl, root.group(1), decl)
        self.assertRegex(block, r"\.sv-horde-tab\s*\{[^}]*bottom: var\(--se-bottom-edge\)")
        self.assertRegex(block, r"\.sv-horde-panel\s*\{[^}]*bottom: var\(--sv-bottom-chrome\)")
        self.assertIn("body:has(#pdCloseBtn) .sv-horde { display: none !important; }",
                      block)

    def test_the_ladder_gains_one_rung_and_two_retrofits(self):
        z = {k: int(v) for k, v in re.findall(r"--z-([a-z-]+):\s*(\d+)", self.ladder)}
        self.assertEqual(z["horde"], 499)
        self.assertLess(z["horde"], z["chrome"])
        self.assertEqual(self.ladder.count("--z-horde:"), 1)
        order = [k for k, _v in re.findall(r"--z-([a-z-]+):\s*(\d+)", self.ladder)]
        self.assertEqual(order.index("horde"), order.index("chrome") + 1)
        self.assertEqual(order.index("drawer"), order.index("horde") + 1)
        self.assertIn("#ipRestorePill { z-index: var(--z-chrome) !important; }",
                      self.ladder)
        self.assertIn(".rail-toggle-btn, .sidebar-toggle-btn "
                      "{ z-index: var(--z-chrome) !important; }", self.ladder)

    def test_the_phone_sheet_is_untouched(self):
        phone = _read("static", "css", "sv-responsive.css")
        self.assertNotIn("horde", phone.lower())


# ── 13.8 the script ──────────────────────────────────────────────────────

class TheScriptTests(SimpleTestCase):

    def setUp(self):
        self.js = JS.read_text(encoding="utf-8")
        self.code = _strip_js(self.js)

    def _fn(self, name):
        start = self.code.index("function " + name + "(")
        depth, i = 0, self.code.index("{", start)
        while True:
            ch = self.code[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return self.code[start:i + 1]
            i += 1

    def test_text_only(self):
        self.assertNotRegex(self.code, r"innerHTML\s*=")
        self.assertNotIn("insertAdjacentHTML", self.code)
        self.assertNotIn("outerHTML", self.code)
        self.assertIn("textContent", self.code)
        for word in ("new WebSocket", "{%", "{{", "var LIVE_URL"):
            self.assertNotIn(word, self.js)

    def test_storage_is_fenced_and_named(self):
        lines = [ln for ln in self.code.splitlines() if "localStorage" in ln]
        self.assertTrue(lines)
        for ln in lines:
            self.assertIn("try {", ln, ln)
        for key in ("'sauron_horde_open'", "'sauron_horde_h'", "'sauron_horde_lens'",
                    "'sauron_horde_shut'", "'sauron_horde_snap_phone'"):
            self.assertIn(key, self.code, key)

    def test_a_phone_never_saves_the_desktop_keys(self):
        for key in ("OPEN_KEY", "H_KEY"):
            for m in re.finditer(r"store\(" + key, self.code):
                before = self.code[max(0, m.start() - 160):m.start()]
                self.assertIn("!state.phone", before, key)
        self.assertIn("OPEN_KEY = 'sauron_horde_open'", self.code)
        self.assertIn("H_KEY = 'sauron_horde_h'", self.code)

    def test_the_polling_guard(self):
        self.assertEqual(self.code.count("setInterval("), 1)
        self.assertIn("setInterval(", self._fn("startPoll"))
        stop = self._fn("stopPoll")
        self.assertIn("clearInterval(", stop)
        self.assertIn("state.ctl.abort()", stop)
        tick = self._fn("tick")
        self.assertRegex(tick, r"^function tick\(\) \{\s*if \(!state\.open \|\| "
                               r"document\.hidden\) return;")
        self.assertEqual(self.code.count("startPoll()"), 1)
        set_open = self._fn("setOpen")
        self.assertIn("startPoll()", set_open)
        self.assertIn("stopPoll()", set_open)
        rt = self._fn("readTab")
        self.assertRegex(rt, r"^function readTab\(reason\) \{\s*if \(document\.hidden\) return;")
        self.assertIn("TAB_MIN_GAP_MS", rt)
        allowed = self._fn("tick") + self._fn("setOpen")
        for line in self.code.splitlines():
            if "readBoard(" in line and "function readBoard" not in line \
                    and line.strip() not in allowed:
                self.assertIn("state.open &&", line, line)

    def test_the_house_signals_are_named(self):
        for word in ("data-horde-url", "sv:eye-event", "sv:pin-unlocked",
                     "visibilitychange", "r.status === 423", "r.redirected",
                     "TICK_MS = 20000", "UP_EVERY = 3", "TAB_MIN_GAP_MS = 10000",
                     "sv:levels-saved", "sv:chrome-moved", "requestIdleCallback",
                     "MutationObserver", "ipPositionsCount",
                     "EVENT_DEBOUNCE_MS = 800", "TAB_STALE_MS = 300000",
                     "SEAT_LOAD_TIMEOUT_MS = 5000", "prefers-reduced-motion"):
            self.assertIn(word, self.code, word)

    def test_rule_one_in_the_source(self):
        for word in ("method:", '"POST"', "'POST'", "/close/", "/levels/",
                     "take-trade", "close-advice"):
            self.assertNotIn(word, self.code, word)
        for word in ("data-sv-close-trade", "lvl-edit", "data-sv-advice-ids",
                     "data-sv-advice-no-close", "svTakeTradeAsset",
                     "askSauronAbout"):
            self.assertIn(word, self.code, word)
        self.assertEqual(len(re.findall(r"\bfetch\(", self.code)), 1)

    def test_escape_is_polite(self):
        self.assertIn("e.defaultPrevented", self.code)
        self.assertIn("contains(document.activeElement)", self.code)

    def test_the_phone_is_the_768px_query(self):
        self.assertIn("matchMedia('(max-width: 768px)')", self.code)

    def test_a_phone_never_filters_by_a_lens_it_cannot_see(self):
        """The phone head hides the lens buttons; a lens kept from a wide
        screen must not hide seats there with nothing to bring them back."""
        self.assertIn("function lens() { return state.phone ? 'all' : state.lens; }",
                      self.code)
        self.assertIn("if (lens() === 'all') return true;", self._fn("lensMatches"))

    def test_the_phone_room_is_measured_from_the_resolved_nav(self):
        """--sv-bottom-chrome is calc(56px + env(...)) on a phone: a custom
        property reads back unresolved, parseFloat makes it 0 and the FULL
        sheet ran 56px up over the top chrome. The sheet's own resolved
        `bottom` (which IS that variable) is read instead."""
        fn = self._fn("measure")
        self.assertIn("getComputedStyle(panel).bottom", fn)
        self.assertNotIn("getPropertyValue('--sv-bottom-chrome')", self.code)

    def test_a_phone_card_keeps_its_money_on_one_row(self):
        """§3.8, round 2: light, symbol, side, world; the mission; then R,
        P&L and the mark on one row of their own (driven in
        TheScreenshotReviewScriptTests.test_a_card_says_its_money_as_one_
        unit). The rail, the voice and the holder fold away."""
        card = self._fn("seatCard")
        self.assertNotIn("if (rr) add(r1, rr);", card)
        self.assertIn("'hd-seat-row hd-money-row'", card)
        self.assertEqual(card.count("'hd-seat-row hd-phone-hide'"), 2)

    def test_an_unmeasured_daily_stop_is_never_open_on_the_phone(self):
        """The summary line says OPEN only for an open stop (driven:
        TheScreenshotReviewScriptTests.test_an_unmeasured_stop_is_a_dash_
        on_the_summary)."""
        table = self._fn("sideSummary")
        self.assertIn("dl.mode === 'open' ? W('mode_open') : DASH", table)

    def test_a_refreshed_dossier_keeps_the_readers_place(self):
        """Only the first paint after opening takes the focus to the
        heading; a refresh (rev moved, levels saved, the button) keeps the
        focus and the scroll where the reader left them."""
        self.assertIn("state.seatFocus = true;", self._fn("openSeat"))
        dossier = self._fn("paintDossier")
        self.assertIn("var first = state.seatFocus;", dossier)
        self.assertIn("if (first) { try { h3.focus(); }", dossier)
        self.assertIn("else seatBox.scrollTop = keep;", dossier)

    def test_a_keyed_height_is_the_readers_at_once(self):
        """A re-measure (any transitionend outside the Horde) re-applies
        the kept fraction: a key step updates it at once, and only the
        storage waits 300 ms. On a phone an arrow is a snap."""
        src = self.code[self.code.index("grip.addEventListener('keydown'"):]
        src = src[:src.index("});") + 3]
        self.assertIn("else if (state.maxH) state.frac = state.h / state.maxH;", src)
        self.assertIn("h = state.phone ? nextSnap(1) : h + step;", src)
        self.assertIn("setTimeout(persistHeight, 300)", src)

    def test_a_dossier_makes_room_and_gives_it_back(self):
        """A dossier opened on a short sheet grows it (FULL on a phone,
        where its sticky head and command bar otherwise meet); closing it
        gives the height back unless the reader sized the sheet meanwhile,
        and a re-measure never undoes the reader's own height."""
        room = self._fn("makeRoom")
        self.assertIn("if (state.phone) {", room)
        self.assertIn("applyHeight(snaps()[2]);", room)
        self.assertIn("applyHeight(state.phone ? snaps()[state.snapPhone - 1] : state.grownFrom);",
                      self._fn("giveRoomBack"))
        self.assertIn("userSized();", self._fn("dragEnd"))
        keys = self.code[self.code.index("grip.addEventListener('keydown'"):]
        self.assertIn("userSized();", keys[:keys.index("});")])
        self.assertIn("function userSized() { state.grownFrom = state.grownTo = null; }",
                      self.code)

    def test_the_lens_filters_the_same_bet_lines(self):
        self.assertIn("'.hd-line[data-world], .hd-bet[data-world]'", self._fn("applyFilters"))

    def test_it_parses(self):
        from tests.test_inline_js_parses import NODE as node, _parse_all
        if node is None:
            self.skipTest("node is not installed on this machine")
        self.assertEqual(_parse_all([{"label": JS.name, "source": self.js}]), [])


# ── 13.9 the openers ─────────────────────────────────────────────────────

LEVEL_HARNESS = r"""
const fs = require('fs'), vm = require('vm');
const src = fs.readFileSync(process.argv[2], 'utf8');
let clicks = 0;
const doc = { addEventListener(t) { if (t === 'click') clicks++; },
              removeEventListener() {}, querySelector() { return null; },
              createElement() { return {}; }, dispatchEvent() {} };
const win = { innerWidth: 1000, innerHeight: 800 };
vm.runInNewContext(src, { window: win, document: doc, CustomEvent: function () {} });
vm.runInNewContext(src, { window: win, document: doc, CustomEvent: function () {} });
process.stdout.write(JSON.stringify({ clicks: clicks,
                                      api: typeof win.SVLevelEdit.open }));
"""


@override_settings(CACHES=LOCMEM)
class TheOpenerTests(_Base):

    def test_the_level_editor_loads_once_and_says_it_saved(self):
        src = _read("static", "js", "sv-level-edit.js")
        self.assertIn("if (w.SVLevelEdit) return;", src)
        self.assertIn("w.SVLevelEdit.open = open;", src)
        self.assertIn('"sv:levels-saved"', src)
        self.assertLess(src.index('"sv:levels-saved"'), src.index("if (w.svLiveRefresh)"))

    @unittest.skipUnless(NODE, "node is not installed")
    def test_twice_loaded_it_binds_once(self):
        tmp = Path(tempfile.mkdtemp(prefix="sv-horde-"))
        try:
            (tmp / "lvl.js").write_text(_read("static", "js", "sv-level-edit.js"),
                                        encoding="utf-8")
            (tmp / "run.js").write_text(LEVEL_HARNESS, encoding="utf-8")
            proc = subprocess.run([NODE, str(tmp / "run.js"), str(tmp / "lvl.js")],
                                  capture_output=True, text=True, timeout=60)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            got = json.loads(proc.stdout)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertEqual(got, {"clicks": 1, "api": "function"})

    def test_the_ask_panel_takes_a_position_and_its_facts(self):
        base = _read("templates", "base.html")
        kinds = base[base.index("var ASK_KINDS = {"):base.index("function setContext")]
        self.assertIn("position: {", kinds)
        self.assertIn("'How is my '", kinds)
        self.assertIn("function (subject, kind, facts)", base)
        self.assertIn("data-ask-facts", base)
        self.assertIn("(Facts shown on screen: '", base)

    def test_the_commands_each_seat_offers(self):
        cfg = _cfg(self.user)
        open_bot = _trade(cfg, "XAUUSD")
        pending = _trade(cfg, "XAGUSD", status="CLOSE_PENDING", entry="30",
                         stop="29", target="33")
        pos = _legacy(self.user, "AAPL")
        board = self.board()
        a = _seat(board, f"bot:{open_bot.id}")["commands"]
        self.assertIsNotNone(a["levels"])
        self.assertEqual(a["levels"]["trade"], str(open_bot.id))
        self.assertEqual(a["levels"]["live"], "0")
        self.assertTrue(a["close"])
        self.assertEqual(a["close_label"], "Close…")
        b = _seat(board, f"bot:{pending.id}")["commands"]
        self.assertIsNone(b["levels"])
        self.assertTrue(b["close"])
        c = _seat(board, f"pf:{pos.id}")["commands"]
        self.assertFalse(c["close"])
        self.assertIsNone(c["levels"])
        for seat in _seats(board):
            facts = seat["commands"]["ask"]["facts"]
            self.assertLessEqual(len(facts), 900)
            self.assertNotIn("mark 0 ", facts + " ")
        self.assertIn("mark unknown", a["ask"]["facts"])
        self.assertEqual(a["ask"]["subject"], f"XAUUSD long #{open_bot.id}")

    def test_the_positions_page_keeps_its_own_tags(self):
        """No page template is edited (C9): /positions/ keeps its own two
        tags, and the Horde loads the very same files lazily, which the
        level editor's own once-guard makes safe."""
        page = _read("templates", "dashboard", "positions_list.html")
        self.assertEqual(len(re.findall(r"<script[^>]*js/sv-level-edit\.js", page)), 1)
        self.assertEqual(len(re.findall(r"<script[^>]*js/sv-close-advice\.js", page)), 1)
        partial = PARTIAL.read_text(encoding="utf-8")
        self.assertIn('data-level-edit-src="{% static \'js/sv-level-edit.js\' %}"', partial)
        self.assertIn('data-advice-src="{% static \'js/sv-close-advice.js\' %}"', partial)


# ── 13.10 the chrome ─────────────────────────────────────────────────────

class TheChromeTests(SimpleTestCase):

    def test_the_tall_chart_measures_the_open_horde(self):
        chart = _read("templates", "_partials", "chart_widget.html")
        guard = chart.index("panel.top > vh * 0.5")
        horde = chart.index("visibleRect('#svHordePanel')")
        self.assertGreater(horde, guard)
        self.assertIn("horde.bottom > vh * 0.5", chart)
        self.assertIn("'sv:chrome-moved'", chart)

    def test_the_motion_layer_leaves_it_alone(self):
        js = _read("static", "js", "sv-motion.js")
        outside = js[js.index("var OUTSIDE"):js.index(";", js.index("var OUTSIDE"))]
        self.assertIn("#svHorde", outside)

    def test_gollum_points_and_never_opens(self):
        js = _read("static", "js", "sv-gollum.js")
        self.assertIn('e.href === "#horde"', js)
        self.assertIn("svHordeTab", js)
        start = js.index('e.href === "#horde"')
        branch = js[start:js.index("return;", start)]
        self.assertNotIn(".click(", branch)
        self.assertNotIn("setOpen", branch)
        self.assertNotIn("toggle(", branch)

    def test_the_tour_names_the_horde_truthfully(self):
        tour = _read("templates", "_tour.html")
        self.assertIn('sel: "#svHordeTab", title: "The Horde"', tour)
        self.assertIn("no Orc is seated yet", tour)
        self.assertLess(tour.index('sel: "#infoPanelWrap"'), tour.index('sel: "#svHordeTab"'))

    def test_the_forensics_close_bar_is_untouched(self):
        """The position page owns its bottom edge: its close-bar offsets are
        not touched, and on a phone the Horde stands aside there (§3.8)."""
        pd = _read("templates", "dashboard", "forensics_detail.html")
        self.assertEqual(pd.count(".info-panel-wrap:not(.minimized)"), 3)
        # The three rules as they read at 74e6bc1.
        self.assertIn("body:has(.info-panel-wrap:not(.minimized)) .pd-closebar "
                      "{ bottom: 60px; }", pd)
        self.assertIn("body:has(.info-panel-wrap:not(.minimized)) .pd-closebar-space "
                      "{ height: 156px; }", pd)
        self.assertRegex(pd, r"html\.pd-js body:has\(#pdCloseBtn\):has\(\.info-panel-wrap"
                             r":not\(\.minimized\)\) \{\s*--se-bottom-edge: calc\(149px \+ "
                             r"env\(safe-area-inset-bottom, 0px\)\);\s*\}")
        self.assertNotIn("horde", pd.lower())
        sheet = _strip_css(SHEET.read_text(encoding="utf-8"))
        self.assertIn("body:has(#pdCloseBtn) .sv-horde { display: none !important; }", sheet)


# ── 13.11 the review of 2026-10-15: what a seat says about real money ───

def _vm(price):
    """A fresh venue stamp (bot_program.venue_mark: the tick's own print)."""
    return {"venue_mark": {"price": float(price), "at": timezone.now().isoformat(),
                           "source": "etoro", "via": "tick"}}


def _view(rows, env="LIVE", at=None, age=600):
    return {"name": "eToro", "env": env, "kind": "etoro", "label": "x",
            "equity": None,
            "positions": {"rows": rows, "at": at or timezone.now(),
                          "age_seconds": age}}


@override_settings(CACHES=LOCMEM)
class TheBrokerBandTests(_Base):
    """AT ETORO, NO SEAT: one broker row per seat by (symbol, side) and
    count; the stragglers and the seats closed since the snapshot claim
    theirs; nothing guesses where a row came from."""

    def setUp(self):
        super().setUp()
        self.cfg = _cfg(self.user)

    def unseated(self, view):
        with mock.patch("bot_program.capital_truth.broker_view", return_value=view):
            return self.board()["unseated"]

    def test_a_straggler_claims_its_row(self):
        t = _real(self.cfg, "XAUUSD", status="ERROR")
        un = self.unseated(_view([{"symbol": "XAUUSD", "side": "BUY", "qty": 1}]))
        self.assertIsNone(un)
        self.assertEqual([s["key"] for s in self.board()["stragglers"]], [f"bot:{t.id}"])

    def test_a_seat_closed_since_the_snapshot_claims_its_row(self):
        from datetime import timedelta

        from bot_program.models import AssetBotTrade
        snap = timezone.now() - timedelta(minutes=10)
        just = _real(self.cfg, "XAUUSD", status="CLOSED")
        AssetBotTrade.objects.filter(pk=just.pk).update(closed_at=timezone.now())
        rows = [{"symbol": "XAUUSD", "side": "BUY", "qty": 1}]
        self.assertIsNone(self.unseated(_view(rows, at=snap)))
        # Closed BEFORE the snapshot: eToro no longer held it then, so a
        # row it still lists is another position.
        AssetBotTrade.objects.filter(pk=just.pk).update(
            closed_at=snap - timedelta(hours=1))
        cache.clear()
        un = self.unseated(_view(rows, at=snap))
        self.assertEqual([r["symbol"] for r in un["rows"]], ["XAUUSD"])

    def test_a_second_position_on_a_seated_symbol_is_listed(self):
        _real(self.cfg, "XAUUSD")
        un = self.unseated(_view([{"symbol": "XAUUSD", "side": "BUY", "qty": 1},
                                  {"symbol": "XAUUSD", "side": "BUY", "qty": 2},
                                  {"symbol": "XAUUSD", "side": "SELL", "qty": 1}]))
        self.assertEqual([(r["symbol"], r["side_word"], r["units_t"]) for r in un["rows"]],
                         [("XAUUSD", "LONG", "2"), ("XAUUSD", "SHORT", "1")])

    def test_what_is_not_held_there_claims_nothing(self):
        """A working order is not a position yet; a demo seat is not at the
        real account; a paper seat is nowhere."""
        _real(self.cfg, "XAUUSD", meta={"entry_working": True})
        _real(self.cfg, "XAGUSD", demo=True, entry="30", stop="29", target="33")
        _trade(self.cfg, "WTIUSD", entry="70", stop="68", target="75")
        un = self.unseated(_view([{"symbol": "XAUUSD", "side": "BUY", "qty": 1},
                                  {"symbol": "XAGUSD", "side": "BUY", "qty": 1},
                                  {"symbol": "WTIUSD", "side": "BUY", "qty": 1}]))
        self.assertEqual([r["symbol"] for r in un["rows"]], ["XAUUSD", "XAGUSD", "WTIUSD"])

    def test_the_words_never_guess(self):
        _real(self.cfg, "EURUSD", cls="forex", entry="1.1", stop="1.09", target="1.12")
        un = self.unseated(_view([{"symbol": "ETORO:1", "side": "BUY", "qty": 1000},
                                  {"symbol": "AAPL", "side": "BUY", "qty": 3}], age=720))
        by = {r["symbol"]: r["t"] for r in un["rows"]}
        self.assertEqual(by["ETORO:1"], "eToro could not name this instrument; it may "
                                        "be one of your seats.")
        self.assertEqual(by["AAPL"], "Not matched to an open seat as of this read "
                                     "(12 min ago).")
        text = json.dumps(un)
        for wrong in ("Opened at eToro directly", "orphan", "Nothing on the platform manages"):
            self.assertNotIn(wrong, text)

    def test_the_closed_read_is_paid_only_for_a_row_left_over(self):
        from dashboard import horde
        from portfolio.services import get_or_create_default_portfolio
        # The book row first: the first head read creates it, which moves
        # the fingerprint (TheCeilingTests does the same).
        get_or_create_default_portfolio(user=self.user)
        _real(self.cfg, "XAUUSD")
        matched = _view([{"symbol": "XAUUSD", "side": "BUY", "qty": 1}])
        extra = _view([{"symbol": "XAUUSD", "side": "BUY", "qty": 1},
                       {"symbol": "AAPL", "side": "BUY", "qty": 1}])

        def count(view):
            with mock.patch("bot_program.capital_truth.broker_view", return_value=view):
                cache.clear()
                horde.board(self.user)
                with CaptureQueriesContext(connection) as ctx:
                    horde.board(self.user)
            return len(ctx.captured_queries)
        self.assertEqual(count(extra), count(matched) + 1)


@override_settings(CACHES=LOCMEM)
class TheVenueStopTests(_Base):
    """A real row the venue protects can only be stopped at the stop the
    venue holds (venue_exit.venue_levels): the seat's stop, distance,
    THROUGH and near-stop read it; the risk stays the gate's, with a note
    of what rests at the venue; the dossier says the fill's stop as
    history once something has replaced it."""

    def setUp(self):
        super().setUp()
        self.cfg = _cfg(self.user)
        _instrument("XAUUSD")

    def _protected(self, held, mark, **meta):
        md = {"protected": True, "protective_trade_id": "p1",
              "stop_rewritten_by_venue": {"sent": 98.0, "held": held}}
        md.update(_vm(mark))
        md.update(meta)
        return _real(self.cfg, "XAUUSD", meta=md)

    def test_a_wider_venue_stop_is_the_one_that_can_be_hit(self):
        t = self._protected(95.0, 97.5)
        seat = _seat(self.board(), f"bot:{t.id}")
        codes = [w["code"] for w in seat["light"]["why"]]
        self.assertNotIn("through_stop", codes)
        self.assertFalse(seat["levels"]["stop_through"])
        self.assertEqual(seat["levels"]["stop_t"], "95.00")
        self.assertEqual(seat["levels"]["sent_stop_t"], "98.00")
        # The gate's own figure, at the stop sent; the venue's beside it.
        self.assertEqual(seat["risk"]["t"], "2.00")
        self.assertEqual(seat["risk"]["venue_note"], "eToro holds a wider stop: 5.00 at it.")
        self.assertIn("stop 95.00 · stop sent 98.00", seat["commands"]["ask"]["facts"])
        line = [r for r in self.seat(f"bot:{t.id}")["deployment"]
                if r["label"] == "Risk at the stop"][0]
        self.assertEqual(line["t"], "eToro holds a wider stop: 5.00 at it.")
        self.assertTrue(line["sub"].startswith("The book limits count 2.00"), line)

    def test_through_the_venues_stop_is_an_alarm(self):
        t = self._protected(95.0, 94.0)
        seat = _seat(self.board(), f"bot:{t.id}")
        through = [w for w in seat["light"]["why"] if w["code"] == "through_stop"]
        self.assertEqual(through[0]["t"], "The price is through the stop (95.00).")

    def test_no_stop_at_the_venue_is_said_everywhere_alike(self):
        t = self._protected(0.0, 99.0)
        seat = _seat(self.board(), f"bot:{t.id}")
        self.assertIn("no_stop_at_venue", [w["code"] for w in seat["light"]["why"]])
        self.assertIsNone(seat["levels"]["stop_t"])
        self.assertIsNone(seat["levels"]["stop_pct_t"])
        self.assertEqual(seat["levels"]["sent_stop_t"], "98.00")
        self.assertEqual(seat["risk"]["venue_note"],
                         "eToro holds no stop: the whole notional is at risk.")
        self.assertEqual(seat["holder"]["suffix"],
                         "The broker holds the target only; no stop rests there.")
        dossier = self.seat(f"bot:{t.id}")
        lines = {r["label"]: r for r in dossier["deployment"]}
        self.assertEqual(lines["Risk at the stop"]["t"],
                         "eToro holds no stop: the whole notional is at risk.")
        self.assertNotIn("work even when Sauron is offline",
                         lines["Who holds the levels"]["t"])
        self.assertIn("stop now none (sent 98.00)", dossier["mission"]["plan"]["t"])

    def test_the_holder_suffix_follows_what_rests_at_the_venue(self):
        from dashboard.horde import holder
        on = {"platform_master": True, "pipeline_asset_bots": True, "aragorn": True}
        bot = {"legacy": False, "config_enabled": True, "keeps_managing": False,
               "record_short": "", "manual_lane": False, "protected": True,
               "world": "live"}
        self.assertIn("work even when Sauron is offline",
                      holder({**bot, "venue_stop": "held"}, on)["suffix"])
        self.assertEqual(holder({**bot, "venue_stop": "none", "venue_target": False}, on)
                         ["suffix"], "The broker holds neither a stop nor a target for it.")
        self.assertIn("could not be read",
                      holder({**bot, "venue_stop": "unread"}, on)["suffix"])

    def test_the_fills_stop_is_history_once_replaced(self):
        """eToro held no stop at the fill; a level edit then moved the stop
        to 99 at the broker. Nothing may say no stop rests there now."""
        t = self._protected(0.0, 100.5, level_edits=[
            {"at": timezone.now().isoformat(), "stop": "99", "target": None,
             "widened": False, "broker": "in-place"}], initial_stop_loss=98.0)
        type(t).objects.filter(pk=t.pk).update(stop_loss=Decimal("99"))
        board = self.board()
        seat = _seat(board, f"bot:{t.id}")
        self.assertNotIn("no_stop_at_venue", [w["code"] for w in seat["light"]["why"]])
        self.assertEqual(seat["levels"]["stop_t"], "99.00")
        self.assertIsNone(seat["levels"]["sent_stop_t"])
        dossier = self.seat(f"bot:{t.id}")
        stops = {s["label"]: s["t"] for s in dossier["stops"]}
        self.assertNotIn("stop held at eToro since the fill", stops)
        self.assertEqual(stops["eToro's stop at the fill (since replaced)"], "none")
        venue = [e["t"] for e in dossier["timeline"] if e["author"] == "VENUE"]
        self.assertIn("eToro held no stop at the fill: 98.00 was sent.", venue)
        self.assertFalse(any(x.startswith("eToro holds no stop") for x in venue), venue)


@override_settings(CACHES=LOCMEM)
class TheHolderSuffixTests(_Base):
    """The suffix is said only of what is true: nothing closes a real row
    whose tick or bot is off (runner.run_asset_bot_tick skips it)."""

    BOT = {"legacy": False, "config_enabled": True, "keeps_managing": False,
           "record_short": "", "manual_lane": False, "protected": False}
    ON = {"platform_master": True, "pipeline_asset_bots": True, "aragorn": True}

    def test_nothing_holds_it_so_nothing_closes_it(self):
        from dashboard.horde import holder
        tick_off = {**self.ON, "pipeline_asset_bots": False}
        bot_off = {**self.BOT, "config_enabled": False, "record_short": "off"}
        for world in ("live", "demo"):
            for facts, sw in (({**self.BOT, "world": world}, tick_off),
                              ({**bot_off, "world": world}, self.ON)):
                got = holder(facts, sw)
                self.assertEqual(got["by"], "nothing")
                self.assertNotIn("Sauron closes it", got["suffix"])
                self.assertEqual(got["suffix"], "Nothing on the platform closes it, and "
                                                "the broker holds no levels for it.")
        paper = holder({**self.BOT, "world": "paper"}, tick_off)
        self.assertNotIn("only the platform's simulator acts", paper["suffix"])
        for sw in (self.ON, {**self.ON, "aragorn": False}):
            self.assertIn("Sauron closes it", holder({**self.BOT, "world": "live"}, sw)["suffix"])

    def test_the_seat_and_the_dossier_say_it(self):
        _switches(pipeline_asset_bots=False)
        t = _real(_cfg(self.user), "XAUUSD")
        seat = _seat(self.board(), f"bot:{t.id}")
        self.assertNotIn("Sauron closes it", seat["holder"]["suffix"])
        self.assertIn("unheld_real", [w["code"] for w in seat["light"]["why"]])
        dossier = self.seat(f"bot:{t.id}")
        who = [r for r in dossier["deployment"] if r["label"] == "Who holds the levels"][0]
        self.assertNotIn("Sauron closes it", who["t"])
        self.assertNotIn("Sauron closes it", json.dumps(dossier["voice"]["care"]))


@override_settings(CACHES=LOCMEM)
class TheZeroStopTests(_Base):
    """An opening stop of 0 is eToro's "no stop": no R, no rail, no 1R, on
    the seat, in the dossier, in the Ask facts and on /positions/."""

    def test_no_stop_no_r(self):
        from dashboard.views import _live_open_book
        from portfolio.services import get_or_create_default_portfolio
        _instrument("XAUUSD")
        t = _real(_cfg(self.user), "XAUUSD", stop="0", meta=_vm(105))
        seat = _seat(self.board(), f"bot:{t.id}")
        self.assertIsNone(seat["money"]["r_v"])
        self.assertEqual(seat["money"]["r_t"], "—")
        self.assertIsNone(seat["levels"]["progress_v"])
        self.assertIsNone(seat["levels"]["istop_t"])
        self.assertIsNone(seat["levels"]["stop_t"])
        facts = seat["commands"]["ask"]["facts"]
        self.assertIn("R now unknown", facts)
        self.assertIn("opening stop none", facts)
        self.assertNotIn("0.00000000", json.dumps(seat["levels"]) + facts)
        # The level editor opens with no stop, as /positions/ hands it.
        self.assertEqual(seat["commands"]["levels"]["stop"], "")
        self.assertEqual(seat["commands"]["levels"]["decimals"], 2)
        plan = self.seat(f"bot:{t.id}")["mission"]["plan"]["t"]
        self.assertIn("opening stop none (1R = —)", plan)
        self.assertNotIn("R from entry", plan)
        pf = get_or_create_default_portfolio(user=self.user)
        row = {r["key"]: r for r in _live_open_book(self.user, pf)[1]}[f"bot-{t.id}"]
        self.assertEqual(row["r_text"], "—")

    def test_the_reader_of_a_stop_level(self):
        """Every opening stop the Horde reads goes through _a_stop: 0 and
        under are "none", never a level, whatever else guards the path."""
        from dashboard.horde import _a_stop
        for none in (0, 0.0, "0", "0.00000000", -1, None, ""):
            self.assertIsNone(_a_stop(none), none)
        self.assertEqual(_a_stop("98"), 98.0)

    def test_a_legacy_zero_stop_is_no_stop(self):
        _quote("AAPL", "105", cls="stock")
        pos = _legacy(self.user, "AAPL", stop="0")
        seat = _seat(self.board(), f"pf:{pos.id}")
        self.assertIsNone(seat["levels"]["istop_t"])
        self.assertIsNone(seat["levels"]["progress_v"])
        self.assertEqual(seat["money"]["r_t"], "—")


@override_settings(CACHES=LOCMEM)
class TheHeadAndTabTests(_Base):
    """The tab, the head, the allocation and the group lines, read off one
    book: a live seat, a demo seat, two paper seats (one an alarm), a
    straggler, and a book of 10,000."""

    def setUp(self):
        super().setUp()
        from portfolio.risk_gate import limits_book
        from portfolio.services import get_or_create_default_portfolio
        main = limits_book()
        main.max_open_risk_pct = 15
        main.save()
        own = get_or_create_default_portfolio(user=self.user)
        own.current_value = Decimal("10000")
        own.save()
        _instrument("XAUUSD")
        _instrument("XAGUSD")
        _quote("BTCUSD", "101", cls="crypto", source="binance_public")
        live = _cfg(self.user, name="live")
        paper = _cfg(self.user, cls="crypto", name="pc", mode="paper", symbols=["BTCUSD"])
        self.live = _real(live, "XAUUSD", qty="50", meta=_vm(101))           # +0.50R
        self.demo = _real(live, "XAGUSD", demo=True, entry="30", stop="29",
                          target="33", qty="10", meta=_vm(31))                # +1.00R
        self.paper = _trade(paper, "BTCUSD", entry="100", stop="98")          # +0.50R
        self.pending = _trade(paper, "BTCUSD", status="CLOSE_PENDING")       # alarm
        self.straggler = _trade(paper, "ETHUSD", status="ERROR")

    def test_the_tab_leads_with_real_money_and_never_mixes_worlds(self):
        tab = self.tab()
        self.assertEqual(tab["lead"], "live")
        self.assertEqual(tab["sides"]["live"]["r_t"], "+0.50R")
        self.assertEqual(tab["sides"]["live"]["r_v"], 0.5)
        self.assertEqual(tab["sides"]["demo"]["r_t"], "+1.00R")
        self.assertIn("Real money: 1 seat, open R +0.50R", tab["title_t"])
        self.assertIn("Demo: 1 seat, open R +1.00R", tab["title_t"])
        self.assertEqual(tab["by_world"], {"live": 1, "demo": 1, "paper": 2, "none": 0})
        self.assertIn("1 real money, open R +0.50R", tab["aria_t"])

    def test_the_allocation_is_a_share_of_the_book(self):
        board = self.board()
        live = board["head"]["sides"]["live"]
        seats = {s["key"]: s for s in _seats(board)}
        work = {k: seats[k]["at_work"]["v"] for k in (f"bot:{self.live.id}",
                                                      f"bot:{self.demo.id}")}
        self.assertTrue(all(v for v in work.values()), work)
        by = {(a["class"], a["demo"]): a for a in live["alloc"]}
        real = by[("commodity", False)]
        self.assertEqual(real["pct_v"], round(work[f"bot:{self.live.id}"] / 10000 * 100, 2))
        self.assertEqual(by[("commodity", True)]["pct_v"],
                         round(work[f"bot:{self.demo.id}"] / 10000 * 100, 2))
        used = sum(work.values()) / 10000 * 100
        self.assertEqual(live["alloc_free"]["pct_v"], round(100 - used, 2))

    def test_each_line_measures_its_risk_against_the_book(self):
        # A paper commodity seat too: 10 x (70 - 68) = 20 at its stop,
        # which is the paper book's, never the real account's share.
        _trade(_cfg(self.user, name="pp", mode="paper"), "WTIUSD", qty="10",
               entry="70", stop="68", target="75")
        board = self.board()
        group = [g for g in board["groups"] if g["key"] == "commodity"][0]
        line = [ln for ln in group["lines"] if ln["world"] == "live"][0]
        # 50 x (100 - 98) = 100 at the stop, 1.0% of 10,000.
        self.assertEqual(line["risk_t"], "100.00")
        self.assertEqual(line["risk_pct_t"], "1.0%")
        # The class's share counts the real account's rows only.
        self.assertTrue(group["today"]["share_t"].startswith("This class: 110.00 of the"),
                        group["today"]["share_t"])

    def test_the_head_counts_the_straggler_and_the_alarm_band_leads(self):
        board = self.board()
        self.assertEqual(board["head"]["tones"]["alarm"], 2)
        self.assertEqual(self.tab()["alarms"], 2)
        # Real money in alarm is the live world's only: a paper alarm, a
        # straggler and a demo alarm are not it.
        self.assertFalse(board["tab"]["alarm_real"])
        _real(_cfg(self.user, name="dm"), "XPTUSD", demo=True, status="CLOSE_PENDING",
              entry="990", stop="980", target="1020")
        self.assertFalse(self.tab()["alarm_real"])
        _real(_cfg(self.user, name="lv"), "XPDUSD", status="CLOSE_PENDING",
              entry="990", stop="980", target="1020")
        self.assertTrue(self.tab()["alarm_real"])
        # The crypto band holds the alarm: it leads the real commodity one.
        self.assertEqual([g["key"] for g in board["groups"]], ["crypto", "commodity"])
        crypto = board["groups"][0]
        self.assertEqual(crypto["seats"][0]["key"], f"bot:{self.pending.id}")

    def test_seats_are_ordered_by_tone_before_world(self):
        working = _real(_cfg(self.user, name="w2"), "XAUUSD", demo=False,
                        meta={"entry_working": True, **_vm(101)})
        _trade(_cfg(self.user, name="p2", mode="paper"), "XAUUSD",
               meta={"entry_working": True})
        group = [g for g in self.board()["groups"] if g["key"] == "commodity"][0]
        tones = [s["light"]["tone"] for s in group["seats"]]
        self.assertEqual(tones, sorted(tones, key=["alarm", "order", "watch", "unheld",
                                                   "calm"].index), tones)
        self.assertEqual(group["seats"][0]["key"], f"bot:{working.id}")

    def test_progress_is_measured_from_the_opening_stop(self):
        seat = _seat(self.board(), f"bot:{self.live.id}")
        # entry 100, opening stop 98, target 110, venue mark 101.
        self.assertEqual(seat["levels"]["progress_v"], 0.25)

    def test_with_the_tick_off_the_head_says_so_and_counts_the_wait(self):
        _quote("XPTUSD", "1000")                     # PL=F: a stand-in
        _real(_cfg(self.user, name="pt"), "XPTUSD", entry="990", stop="980",
              target="1020")
        _switches(pipeline_asset_bots=False)
        head = self.board()["head"]
        self.assertIn("The 5-minute tick is off: the platform enforces no stop or target.",
                      head["switch_lines"])
        self.assertEqual(head["marks"]["waiting"], 1)
        self.assertEqual(head["marks"]["venue"], 2)

    def test_a_same_bet_needs_two_seats_of_one_world(self):
        board = self.board()
        group = [g for g in board["groups"] if g["key"] == "commodity"][0]
        self.assertEqual(group["same_bet"], [])          # one live, one demo
        _real(_cfg(self.user, name="ag"), "XAGUSD", entry="30", stop="29",
              target="33", meta=_vm(31))
        group = [g for g in self.board()["groups"] if g["key"] == "commodity"][0]
        self.assertEqual([b["world"] for b in group["same_bet"]], ["live"])
        # round 2: the count names its book
        self.assertIn("Long precious through 2 real-money seats", group["same_bet"][0]["t"])


# ── 13.12 the script, driven: behaviour, not source text ────────────────

HARNESS = BASE / "tests" / "horde_dom_harness.js"
_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
         "meta", "source", "track", "wbr"}


def _partial_tree(**ctx):
    """The rendered partial as a JSON tree (html.parser), for the harness."""
    from html.parser import HTMLParser

    from django.template.loader import render_to_string

    class Tree(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.root = {"tag": "root", "attrs": {}, "children": []}
            self.stack = [self.root]

        def handle_starttag(self, tag, attrs):
            node = {"tag": tag, "attrs": {k: (v if v is not None else "") for k, v in attrs},
                    "children": []}
            self.stack[-1]["children"].append(node)
            if tag not in _VOID:
                self.stack.append(node)

        def handle_endtag(self, tag):
            for i in range(len(self.stack) - 1, 0, -1):
                if self.stack[i]["tag"] == tag:
                    del self.stack[i:]
                    break

        def handle_data(self, data):
            if data:
                self.stack[-1]["children"].append(data)

    t = Tree()
    t.feed(render_to_string("_partials/the_horde.html", {"panel_positions": 3, **ctx}))
    return t.root["children"]


def _drive(scenario, payloads, js=None):
    """Run sv-horde.js (or `js`, its source) in the harness under a
    scenario; the scenario's return value comes back."""
    tmp = Path(tempfile.mkdtemp(prefix="sv-horde-dom-"))
    try:
        (tmp / "tree.json").write_text(json.dumps(_partial_tree()), encoding="utf-8")
        (tmp / "horde.js").write_text(js if js is not None else JS.read_text(encoding="utf-8"),
                                      encoding="utf-8")
        (tmp / "scenario.js").write_text(scenario, encoding="utf-8")
        (tmp / "payloads.json").write_text(json.dumps(payloads), encoding="utf-8")
        proc = subprocess.run([NODE, str(HARNESS), str(tmp / "tree.json"), str(tmp / "horde.js"),
                               str(tmp / "scenario.js"), str(tmp / "payloads.json")],
                              capture_output=True, text=True, timeout=120)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if proc.returncode != 0:
        raise AssertionError(proc.stderr[-3000:])
    return json.loads(proc.stdout)


OPEN = """
env.load();
await env.settle();
env.click(env.$('svHordeTab'));
await env.settle();
"""


@unittest.skipUnless(NODE, "node is not installed")
@override_settings(CACHES=LOCMEM)
class TheScriptBehaviourTests(_Base):
    """sv-horde.js run against the rendered partial in a small DOM (tests/
    horde_dom_harness.js): focus falls to <body> where a browser's would
    (removed, hidden, inert), timers and frames are the test's, and the
    answers are the endpoint's own."""

    def setUp(self):
        super().setUp()
        self.cfg = _cfg(self.user)
        _instrument("XAUUSD")
        _instrument("XAGUSD")
        self.live = _real(self.cfg, "XAUUSD", meta=_vm(101))
        self.demo = _real(self.cfg, "XAGUSD", demo=True, entry="30", stop="29",
                          target="33", meta=_vm(31))
        self.paper = _trade(self.cfg, "WTIUSD", entry="70", stop="68", target="75",
                            status="CLOSE_PENDING")

    def payloads(self, seat=None):
        out = {"board": self.board(), "tab": self.tab()}
        out["seat"] = self.seat(seat or f"bot:{self.live.id}")
        return out

    def test_an_orc_seat_paints_label_level_and_the_day_and_text_stays_text(self):
        from bot_program.orcs import journal
        from bot_program.orcs.models import OrcDayBaseline
        from bot_program.orcs.sessions import trading_day
        from tests.orcs.helpers import _paper_cap, _wake_card, born
        _paper_cap()
        orc = born(self, self.live)
        _wake_card(orc)
        journal.append(orc, "thesis", "Your thesis: <script>alert(1)</script>",
                       author="operator", body={"thesis": {
                           "source": "operator",
                           "text": "<script>alert(1)</script> holds"}})
        OrcDayBaseline.objects.create(
            user=self.user, asset_class="commodity",
            trading_day=trading_day(timezone.now()), day_class="stormy",
            score=63)
        _switches(orcs=True)
        got = _drive(OPEN + """
            const bands = env.$('svHordeBands'), box = env.$('svHordeSeat');
            const key = env.payloads.seat.seat.key;
            const card = bands.querySelector('[data-open-seat="' + key + '"]').closest('.hd-seat');
            const foot = card.textContent;
            const head = bands.querySelector('.hd-band[data-band="commodity"] .hd-band-head').textContent;
            env.click(bands.querySelector('[data-open-seat="' + key + '"]'));
            await env.settle();
            const orcBox = box.querySelector('.hd-orc');
            const scripts = box.querySelectorAll('script').length;
            const links = Array.prototype.map.call(orcBox.querySelectorAll('a'),
                                                   (a) => a.getAttribute('href'));
            return {foot, head, orc: orcBox.textContent, scripts, links};
        """, self.payloads())
        got = {k: (v.replace("\xa0", " ") if isinstance(v, str) else v)
               for k, v in got.items()}
        self.assertIn(f"Orc #{self.live.id} · L0 · Snaga", got["foot"])
        self.assertIn("Day: stormy · score 63", got["head"])
        self.assertIn("No Captain seated yet.", got["head"])
        self.assertIn("Rank: L0 · Snaga", got["orc"])
        self.assertIn("<script>alert(1)</script> holds", got["orc"])
        self.assertIn("Complexity: score 58 · complex · No model (code only)",
                      got["orc"])
        self.assertIn(f"Open Orc #{self.live.id} ›", got["orc"])
        self.assertEqual(got["scripts"], 0)
        self.assertEqual(got["links"], [f"/orcs/{self.live.id}/"])

    def test_the_switch_lines_stand_outside_the_capped_table(self):
        _switches(aragorn=False)
        got = _drive(OPEN + """
            return {notes: env.$('svHordeNotes').textContent,
                    table: env.$('svHordeTable').textContent};
        """, self.payloads())
        line = "The care is switched off: no soft stops, trails or locks run."
        self.assertIn(line, got["notes"])
        self.assertNotIn(line, got["table"])
        self.assertIn("MARKS", got["notes"].upper())

    def test_a_poll_keeps_the_expanders_and_the_readers_place(self):
        got = _drive(OPEN + """
            const bands = env.$('svHordeBands');
            env.click(bands.querySelector('[data-hd-focus="exp:commodity"]'));
            bands.querySelector('[data-hd-focus="band:commodity"]').focus();
            const before = env.focusKey();
            const reads = env.fetched.length;
            await env.advance(20000);              // one scheduled read
            const exp = bands.querySelector('[data-hd-focus="exp:commodity"]');
            const band = exp.closest('.hd-band');
            const out = {before, after: env.focusKey(), read: env.fetched.length - reads,
                         expanded: exp.getAttribute('aria-expanded'),
                         todayHidden: band.querySelector('.hd-today').hidden};
            const chip = env.$('svHordeSum').querySelector('[data-hd-focus="chip:alarm"]');
            chip.focus();
            await env.advance(20000);
            out.chip = env.focusKey();
            return out;
        """, self.payloads())
        self.assertEqual(got["read"], 1)
        self.assertEqual(got["before"], "band:commodity")
        self.assertEqual(got["after"], "band:commodity")
        self.assertEqual(got["expanded"], "true")
        self.assertFalse(got["todayHidden"])
        self.assertEqual(got["chip"], "chip:alarm")

    def test_a_lens_leaves_every_band_a_way_in(self):
        got = _drive(OPEN + """
            const root = env.$('svHorde');
            env.click(root.querySelector('.hd-lens-btn[data-lens="demo"]'));
            const band = env.$('svHordeBands').querySelector('.hd-band[data-band="commodity"]');
            return Array.prototype.map.call(band.querySelectorAll('.hd-seat'), (c) => ({
                world: c.getAttribute('data-world'), hidden: c.hidden,
                ti: c.querySelector('.hd-seat-open').tabIndex}));
        """, self.payloads())
        self.assertEqual(sorted((c["world"], c["hidden"], c["ti"]) for c in got),
                         [("demo", False, 0), ("live", True, -1), ("paper", True, -1)])

    def test_a_press_that_does_not_move_is_not_a_resize(self):
        got = _drive(OPEN + """
            const grip = env.$('svHordeGrip'), root = env.$('svHorde');
            env.key(grip, 'ArrowUp');
            await env.advance(400);
            const h = root.style.getPropertyValue('--horde-h'), kept = env.store['sauron_horde_h'];
            env.pointer(grip, 'pointerdown', 500);
            env.pointer(grip, 'pointerup', 500);
            await env.advance(400);
            return {h, kept, after: root.style.getPropertyValue('--horde-h'),
                    keptAfter: env.store['sauron_horde_h'], open: root.classList.contains('open')};
        """, self.payloads())
        self.assertEqual(got["h"], "474px")        # HALF 450 + one 24px step
        self.assertEqual(got["after"], "474px")    # not snapped back to HALF
        self.assertEqual(got["keptAfter"], got["kept"])
        self.assertTrue(got["open"])

    def test_a_tap_on_the_phone_head_never_pins_full(self):
        got = _drive("""
            env.media.matches = true;
            env.win.SVLevelEdit = {}; env.win.SVCloseAdvice = {};
            env.load();
            await env.settle();
            env.click(env.$('svHordeTab'));
            await env.settle();
            const root = env.$('svHorde');
            const before = root.style.getPropertyValue('--horde-h');
            env.click(env.$('svHordeBands').querySelector(
                '[data-open-seat="' + env.payloads.seat.seat.key + '"]'));
            await env.settle();
            const grown = root.style.getPropertyValue('--horde-h');
            const head = env.$('svHordeHead');
            env.pointer(head, 'pointerdown', 300);
            env.pointer(head, 'pointerup', 300);
            await env.settle();
            const back = env.$('svHordeSeat').querySelectorAll('button')
                .filter((b) => b.textContent.indexOf('Back') !== -1)[0];
            env.click(back);
            await env.settle();
            return {before, grown, after: root.style.getPropertyValue('--horde-h'),
                    snap: env.store['sauron_horde_snap_phone'] || null};
        """, self.payloads())
        # The phone's room: 900 less 8 (no chrome measured here) = 892.
        self.assertEqual(got["before"], "595px")   # two thirds
        self.assertEqual(got["grown"], "892px")    # FULL while the dossier is open
        self.assertIsNone(got["snap"])
        self.assertEqual(got["after"], "595px")    # given back

    def test_collapsing_from_inside_hands_the_focus_to_the_tab(self):
        got = _drive(OPEN + """
            const root = env.$('svHorde'), grip = env.$('svHordeGrip'), tab = env.$('svHordeTab');
            const h = root.style.getPropertyValue('--horde-h');
            grip.focus();
            env.key(grip, 'Enter');
            await env.settle();
            const out = {closed: !root.classList.contains('open'),
                         focus: env.doc.activeElement === tab};
            env.click(tab, 0);                     // Enter on the tab
            await env.settle();
            out.reopened = root.classList.contains('open');
            out.sameHeight = root.style.getPropertyValue('--horde-h') === h;
            env.$('svHordeBands').querySelector('[data-open-seat]').focus();
            env.win.SVHorde.toggle('key');         // base.html's h key
            await env.settle();
            out.hFocus = env.doc.activeElement === tab;
            return out;
        """, self.payloads())
        self.assertEqual(got, {"closed": True, "focus": True, "reopened": True,
                               "sameHeight": True, "hFocus": True})

    def test_a_refreshed_dossier_never_steals_the_focus(self):
        got = _drive(OPEN.replace("env.load();", "env.win.SVLevelEdit = {}; "
                                                 "env.win.SVCloseAdvice = {}; env.load();") + """
            const bands = env.$('svHordeBands'), box = env.$('svHordeSeat');
            const open = bands.querySelector('[data-open-seat="' + env.payloads.seat.seat.key + '"]');
            env.click(open);
            await env.settle();
            const first = env.doc.activeElement.localName;
            open.focus();
            box.scrollTop = 120;
            env.fire('sv:levels-saved', {trade: open.getAttribute('data-open-seat').split(':')[1]});
            await env.advance(1000);
            return {first, second: env.focusKey(), scroll: box.scrollTop,
                    painted: box.querySelectorAll('h3').length,
                    seatReads: env.fetched.filter((u) => u.indexOf('seat=') !== -1).length};
        """, self.payloads())
        self.assertEqual(got["first"], "h3")
        self.assertEqual(got["seatReads"], 2)
        self.assertEqual(got["painted"], 1)
        self.assertTrue(got["second"].startswith("seat:bot:"), got)
        self.assertEqual(got["scroll"], 120)

    def test_the_tab_tier_follows_the_tabs_measured_content(self):
        """The tier is the widest whose content fits the tab's room, both
        MEASURED (the tab's scrollWidth against its clientWidth), never a
        guess from the root's width: at 1380 the full tier needed ~470px
        in a 368px room and every segment ended in an ellipsis
        (2026-10-16). The harness measures a segment at 7px a character,
        hides what sv-horde.css hides per tier, and gives the tab a room."""
        got = _drive(OPEN + """
            env.click(env.$('svHordeClose'));
            await env.settle();
            const root = env.$('svHorde'), tab = env.$('svHordeTab');
            const hiddenBy = {'hd-t-m': ['hd-tab-name'],
                              'hd-t-s': ['hd-tab-name', 'hd-tab-r', 'hd-tab-risk', 'hd-tab-flag']};
            const need = (t) => {
                const off = [].concat(...Object.keys(hiddenBy).filter((c) => root.classList.contains(c))
                                                              .map((c) => hiddenBy[c]));
                const segs = t.children.filter((s) => !s.hidden && !off.some((c) => s.classList.contains(c)));
                return 20 + segs.reduce((w, s) => w + 7 * s.textContent.length, 0) + 8 * (segs.length - 1);
            };
            tab._scrollWidth = need;
            const at = (room) => {
                tab._clientWidth = room; env.resize();
                const tier = ['hd-t-l', 'hd-t-m', 'hd-t-s'].filter((c) => root.classList.contains(c));
                return {tier, seats: env.$('svHordeSeats').textContent, need: need(tab), room};
            };
            const full = (() => { tab._clientWidth = 2000; env.resize(); return need(tab); })();
            return {text: tab.textContent, roomy: at(full), short: at(full - 2), tight: at(160)};
        """, self.payloads())
        self.assertEqual(got["roomy"]["tier"], ["hd-t-l"])
        self.assertTrue(got["roomy"]["seats"].endswith("seats"), got)
        # Two pixels short of the full tier (one is rounding's): the next
        # tier, whose content fits.
        self.assertEqual(got["short"]["tier"], ["hd-t-m"])
        self.assertTrue(got["short"]["seats"].startswith("HORDE"), got)
        self.assertLessEqual(got["short"]["need"], got["short"]["room"])
        self.assertEqual(got["tight"]["tier"], ["hd-t-s"])
        self.assertIn("REAL", got["text"])


@unittest.skipUnless(NODE, "node is not installed")
class TheTallChartTests(SimpleTestCase):
    """tallBox() (chart_widget.html) run under node with the furniture
    measured: the Horde's inset is taken only while it leaves the chart
    its MIN_TALL_H floor; past that the chart pins over the sheet with the
    strip-only inset, never over the whole screen."""

    RUN = r"""
const fs = require('fs'), vm = require('vm');
const src = fs.readFileSync(process.argv[2], 'utf8');
function grab(name) {
  const start = src.indexOf('function ' + name + '(');
  let depth = 0, i = src.indexOf('{', start);
  for (; i < src.length; i++) {
    if (src[i] === '{') depth++;
    else if (src[i] === '}') { depth--; if (!depth) break; }
  }
  return src.slice(start, i + 1);
}
const floor = (n) => Number(new RegExp('var ' + n + ' = (\\d+);').exec(src)[1]);
const cases = JSON.parse(process.argv[3]);
const out = cases.map((c) => {
  const ctx = { window: { innerHeight: c.vh, innerWidth: c.vw },
                MIN_TALL_H: floor('MIN_TALL_H'), MIN_TALL_W: floor('MIN_TALL_W'),
                visibleRect: (sel) => c.rects[sel] || null };
  vm.createContext(ctx);
  vm.runInContext(grab('tallBox') + '; out = tallBox();', ctx);
  return ctx.out;
});
process.stdout.write(JSON.stringify(out));
"""

    def _boxes(self, cases):
        tmp = Path(tempfile.mkdtemp(prefix="sv-tall-"))
        try:
            (tmp / "run.js").write_text(self.RUN, encoding="utf-8")
            (tmp / "chart.html").write_text(_read("templates", "_partials", "chart_widget.html"),
                                            encoding="utf-8")
            proc = subprocess.run([NODE, str(tmp / "run.js"), str(tmp / "chart.html"),
                                   json.dumps(cases)], capture_output=True, text=True,
                                  timeout=60)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    def test_a_tall_horde_never_lays_the_chart_over_the_screen(self):
        rect = lambda t, b, l=0, r=1380: {"top": t, "bottom": b, "left": l, "right": r}  # noqa: E731
        base = {".topbar": rect(0, 106), ".info-panel-wrap": rect(840, 900, 240, 1336),
                ".sidebar": rect(0, 900, 0, 240), ".signals-rail": rect(0, 900, 1336, 1380)}
        full, half = self._boxes([
            {"vh": 900, "vw": 1380, "rects": {**base, "#svHordePanel": rect(150, 840, 240, 1336)}},
            {"vh": 900, "vw": 1380, "rects": {**base, "#svHordePanel": rect(497, 840, 240, 1336)}},
        ])
        # FULL: the strip's inset only, never {8, 8, 8, 8} over everything.
        self.assertEqual(full, {"top": 114, "right": 52, "bottom": 68, "left": 248})
        # HALF: pinned above the sheet.
        self.assertEqual(half, {"top": 114, "right": 52, "bottom": 411, "left": 248})


# ── 13.14 the screenshot review of 2026-10-16 ────────────────────────────
#
# The committed Horde was screenshot at 1100, 1380, 1440 and 390 and the
# review listed what was untrue and what was ugly, clipped or overlapping
# (shots_report.md). Each test here fails on the code the review saw.

def _thesis(verdict="hold", stop=98):
    return {"thesis": {"verdict": verdict, "words": "the structure still holds",
                       "at": timezone.now().isoformat(), "stop": stop}}


@override_settings(CACHES=LOCMEM)
class TheScreenshotReviewTests(_Base):
    """The untrue list, through the endpoint."""

    def setUp(self):
        super().setUp()
        self.cfg = _cfg(self.user)

    # untrue 1
    def test_the_orc_thesis_slot_is_the_orcs_and_names_the_thesis_check(self):
        """MISSION's slot said "No thesis is written for this seat yet."
        above a thesis check that read HOLD."""
        from dashboard import horde
        t = _trade(self.cfg, "XAUUSD", meta=_thesis("hold"))
        mission = self.seat(f"bot:{t.id}")["mission"]
        self.assertEqual(mission["thesis"], "No Orc has written a thesis for this seat yet.")
        self.assertEqual(mission["thesis"], horde.NO_THESIS_YET)
        self.assertIn("The thesis check", mission["thesis_note"])
        self.assertIn("HOLD", mission["thesis_note"])
        bare = _trade(self.cfg, "XAGUSD", entry="30", stop="29", target="33")
        self.assertEqual(self.seat(f"bot:{bare.id}")["mission"]["thesis_note"], "")

    # untrue 2
    def test_marks_says_which_book_each_count_covers(self):
        _real(self.cfg, "XAUUSD", meta=_vm(101))
        _trade(self.cfg, "WTIUSD", entry="70", stop="68", target="75")
        _quote("WTIUSD", "71")
        marks = self.board()["head"]["marks"]
        self.assertTrue(marks["t"].startswith("MARKS · REAL (1): 1 venue"), marks["t"])
        self.assertIn("PAPER (1): 1 feed · 0 waiting", marks["t"])
        self.assertEqual((marks["real_n"], marks["paper_n"]), (1, 1))

    def test_marks_names_demo_when_the_real_side_holds_demo(self):
        _real(self.cfg, "XAUUSD", demo=True, meta=_vm(101))
        self.assertIn("REAL AND DEMO (1)", self.board()["head"]["marks"]["t"])

    # untrue 4
    def test_an_index_cfd_in_a_stock_bot_says_why_it_is_banded_there(self):
        _instrument("NSDQ100", "index")
        stock = _cfg(self.user, cls="stock", name="s", symbols=["NSDQ100"])
        _real(stock, "NSDQ100", entry="24000", stop="23800", target="24500",
              meta=_vm(24100))
        board = self.board()
        band = [g for g in board["groups"] if g["key"] == "stock"][0]
        self.assertIn("NSDQ100 (an index) is banded under STOCK", band["class_note_t"])
        alloc = board["head"]["sides"]["live"]["alloc"]
        self.assertIn("(with NSDQ100, an index)", alloc[0]["t"])
        plain = [g for g in board["groups"] if g["key"] != "stock"]
        self.assertTrue(all(g["class_note_t"] == "" for g in plain))

    # untrue 5 and 6
    def _peer_rows(self, rho_by_symbol, n_seats=0):
        """_peers over a mocked matrix: XAUUSD against its SMT partner and
        complex and `n_seats` other seats."""
        from bot_program import capital_desk
        from dashboard.horde import _peer_seat, _peers
        for s in ("XAGUSD", "XPTUSD", "XPDUSD"):
            _instrument(s)
        fx = _cfg(self.user, cls="forex", name="fx", symbols=[])
        others = []
        for i in range(n_seats):
            sym = f"S{i:02d}USD"
            _instrument(sym, "forex")
            others.append(_peer_seat(_trade(fx, sym, entry="1.1", stop="1.09", target="1.2")))
        rho, measured = {}, set()
        for s, r in rho_by_symbol.items():
            pair = tuple(sorted(("XAUUSD", s)))
            rho[pair] = r
            measured.add(pair)
        matrix = {"rho": rho, "measured": measured,
                  "n_bars": {p: 180 for p in measured}, "symbols": [], "pairs_total": 0}
        with mock.patch.object(capital_desk, "correlation_matrix", return_value=matrix):
            rows, _chips = _peers(self.user, "XAUUSD", "BUY", "commodity", "paper",
                                  others, timezone.now())
        return rows

    # round 2: "(1R = 25.98)" read like a price distance
    def test_one_r_is_said_with_its_currency(self):
        t = _trade(self.cfg, "XAUUSD", qty="0.6", entry="4141.3", stop="4098", target="4260")
        d = self.seat(f"bot:{t.id}")
        self.assertIn("(1R = 25.98 USD)", d["mission"]["plan"]["t"])
        one = [m for m in d["deployment"] if m["label"] == "1R"][0]
        self.assertEqual(one["t"], "25.98 USD")

    # round 2: "YOUR SEAT #31" on a paper seat read like the real ones
    def test_a_correlated_seat_names_its_book(self):
        from bot_program import capital_desk
        from dashboard.horde import _peer_seat, _peers
        fx = _cfg(self.user, cls="forex", name="fx", symbols=[])
        for s in ("EURUSD", "GBPUSD", "USDCNH"):
            _instrument(s, "forex")
        real = _real(fx, "EURUSD", entry="1.1", stop="1.09", target="1.2", meta=_vm(1.1))
        demo = _real(fx, "USDCNH", demo=True, entry="7.1", stop="7.2", target="7.0",
                     side="SELL", meta=_vm(7.1))
        paper = _trade(fx, "GBPUSD", entry="1.3", stop="1.29", target="1.4")
        others = [_peer_seat(t) for t in (real, demo, paper)]
        with mock.patch.object(capital_desk, "correlation_matrix", return_value={}):
            rows, _ = _peers(self.user, "XAUUSD", "BUY", "commodity", "live",
                             others, timezone.now())
        by = {r["symbol"]: r for r in rows}
        self.assertEqual(by["EURUSD"]["relation"], f"YOUR REAL SEAT #{real.id}")
        self.assertEqual(by["USDCNH"]["relation"], f"YOUR DEMO SEAT #{demo.id}")
        self.assertEqual(by["GBPUSD"]["relation"], f"YOUR PAPER SEAT #{paper.id}")
        self.assertEqual([by[s]["seat_world"] for s in ("EURUSD", "USDCNH", "GBPUSD")],
                         ["live", "demo", "paper"])
        self.assertEqual(by["EURUSD"]["seat_world_word"], "REAL MONEY")

    def test_the_strength_word_follows_the_printed_number(self):
        """"+0.40 weak" beside "+0.46 moderate": 0.398 was judged against
        0.4 and printed as 0.40."""
        rows = {r["symbol"]: r for r in self._peer_rows(
            {"XAGUSD": 0.398, "XPTUSD": 0.6951, "XPDUSD": 0.394})}
        self.assertEqual((rows["XAGUSD"]["rho_t"], rows["XAGUSD"]["strength"]), ("+0.40", "moderate"))
        self.assertEqual((rows["XPTUSD"]["rho_t"], rows["XPTUSD"]["strength"]), ("+0.70", "strong"))
        self.assertEqual((rows["XPDUSD"]["rho_t"], rows["XPDUSD"]["strength"]), ("+0.39", "weak"))

    def test_the_strongest_comes_first_and_the_family_survives_the_cap(self):
        """XAGUSD at +0.84 came 8th under seats at -0.08; with twelve or
        more seats the partner and the complex were cut entirely."""
        rhos = {f"S{i:02d}USD": (0.05 + i / 100) * (-1 if i % 2 else 1) for i in range(14)}
        rhos.update({"XAGUSD": 0.84, "XPTUSD": 0.02, "XPDUSD": -0.01})
        rows = self._peer_rows(rhos, n_seats=14)
        from dashboard.horde import PEERS_MAX
        syms = [r["symbol"] for r in rows]
        self.assertEqual(len(rows), PEERS_MAX)
        self.assertEqual(syms[0], "XAGUSD")
        for fam in ("XAGUSD", "XPTUSD", "XPDUSD"):
            self.assertIn(fam, syms)
        strengths = [abs(r["rho_v"]) for r in rows]
        self.assertEqual(strengths, sorted(strengths, reverse=True))
        seats = [r for r in rows if r["is_seat"]]
        self.assertTrue(seats)
        self.assertTrue(all(r["relation"].startswith("YOUR PAPER SEAT #") for r in seats))
        # the strongest seats are the ones kept
        kept = {r["symbol"] for r in seats}
        dropped = set(rhos) - set(syms)
        self.assertTrue(dropped)
        self.assertLessEqual(max(abs(rhos[s]) for s in dropped),
                             min(abs(rhos[s]) for s in kept))

    # untrue 7
    def test_the_market_line_names_the_venue_that_holds_the_row(self):
        """"CME Futures open" on a gold CFD held at eToro."""
        gold = _real(self.cfg, "XAUUSD", meta=_vm(101))
        line = [m for m in self.seat(f"bot:{gold.id}")["metrics"] if m["label"] == "Market"][0]
        self.assertTrue(line["t"].startswith("eToro:"), line["t"])
        self.assertIn("eToro's own hours are not modelled here", line["t"])
        self.assertFalse(line["t"].startswith("CME"), line["t"])
        _instrument("NSDQ100", "index")
        stock = _cfg(self.user, cls="stock", name="s", symbols=["NSDQ100"])
        ndx = _real(stock, "NSDQ100", entry="24000", stop="23800", target="24500",
                    meta=_vm(24100))
        line = [m for m in self.seat(f"bot:{ndx.id}")["metrics"] if m["label"] == "Market"][0]
        self.assertTrue(line["t"].startswith("eToro: an index CFD keeps the FX week."), line["t"])
        paper = _trade(self.cfg, "XAGUSD", entry="30", stop="29", target="33")
        line = [m for m in self.seat(f"bot:{paper.id}")["metrics"] if m["label"] == "Market"][0]
        self.assertTrue(line["t"].startswith("Paper venue, on the "), line["t"])

    # untrue 8
    def test_a_hand_trade_is_never_the_bots(self):
        from bot_program.asset_engine import safety
        manual = _manual(self.user)
        hand = _real(manual, "XAUUSD", meta={**_vm(101), "manual": True})
        bot = _trade(self.cfg, "XAGUSD", entry="30", stop="29", target="33")
        with mock.patch.object(safety, "heartbeat_age_seconds", return_value=180):
            h = [m for m in self.seat(f"bot:{hand.id}")["metrics"] if m["label"] == "Last tick"][0]
            b = [m for m in self.seat(f"bot:{bot.id}")["metrics"] if m["label"] == "Last tick"][0]
        self.assertNotIn("bot", h["t"].lower())
        self.assertIn("the lane that holds your ticket", h["t"])
        self.assertTrue(b["t"].startswith(f"The bot {self.cfg.name} #{self.cfg.id} last ticked"), b["t"])

    # round 2: the light said "Its bot last ticked" of a hand ticket
    def test_a_hand_tickets_light_never_says_its_bot(self):
        from bot_program.asset_engine import safety
        _all_on()
        manual = _manual(self.user)
        hand = _real(manual, "XAUUSD", meta={**_vm(101), "manual": True})
        bot = _trade(self.cfg, "XAGUSD", entry="30", stop="29", target="33")
        with mock.patch.object(safety, "heartbeat_age_seconds", return_value=10 ** 6):
            board = self.board()
        hw = [w for w in _seat(board, f"bot:{hand.id}")["light"]["why"]
              if w["code"] == "tick_stale"]
        bw = [w for w in _seat(board, f"bot:{bot.id}")["light"]["why"]
              if w["code"] == "tick_stale"]
        self.assertEqual(len(hw), 1, _seat(board, f"bot:{hand.id}")["light"])
        self.assertNotIn("bot", hw[0]["t"].lower())
        self.assertIn("the lane that holds your ticket", hw[0]["t"])
        self.assertEqual(len(bw), 1)
        self.assertTrue(bw[0]["t"].startswith("Its bot last ticked"), bw[0]["t"])

    # untrue 9
    def test_the_phone_commands_are_real_commands(self):
        t = _trade(self.cfg, "XAUUSD")
        phone = self.seat(f"bot:{t.id}")["phone"]
        for p in phone:
            self.assertNotIn("{", p["cmd"])
            self.assertNotIn("}", p["cmd"])
        q = [p for p in phone if p["cmd"].startswith("/q ")][0]
        self.assertEqual(q["cmd"], "/q Is the reason for my XAUUSD long still alive?")

    # untrue 10
    def test_one_price_format_per_instrument_across_the_dossier(self):
        """The mark "4,182.1000" and "24,856.0000", the levels "4160.00",
        the reviewer's "Suggested stop 4168" beside "structure stop
        4128.00": one precision per instrument, core/price_format's."""
        from core.price_format import format_price
        _instrument("NSDQ100", "index")
        stock = _cfg(self.user, cls="stock", name="s", symbols=["NSDQ100"])
        ndx = _real(stock, "NSDQ100", entry="24000", stop="23800", target="24500",
                    meta=_vm(24856))
        gold = _real(self.cfg, "XAUUSD", entry="4141.3", stop="4098", target="4260",
                     meta={**_vm(4182.1), **_thesis("hold", 4128)})
        _review(f"bot:{gold.id}", verdict="tighten", user=self.user, suggested_stop=4168)
        board = self.board()
        self.assertEqual(_seat(board, f"bot:{ndx.id}")["mark"]["t"], "24856.00")
        g = _seat(board, f"bot:{gold.id}")
        self.assertEqual(g["mark"]["t"], "4182.10")
        self.assertNotIn(".1000", json.dumps(g["money"]["r_title"]))
        d = self.seat(f"bot:{gold.id}")
        self.assertEqual(d["voice"]["reviewer"]["suggested_stop_t"], "4168.00")
        self.assertEqual(d["voice"]["thesis"]["stop_t"], "4128.00")
        peer = [p for p in d["instruments"]["peers"] if p["symbol"] == "NSDQ100"][0]
        self.assertEqual(peer["last_t"], format_price(24856, "index", "NSDQ100"))


@unittest.skipUnless(NODE, "node is not installed")
@override_settings(CACHES=LOCMEM)
class TheScreenshotReviewScriptTests(_Base):
    """The ugly, clipped and overlapping list, and the untrue words the
    script paints, driven in tests/horde_dom_harness.js."""

    def setUp(self):
        super().setUp()
        self.cfg = _cfg(self.user)
        _instrument("XAUUSD")
        _instrument("XAGUSD")
        self.live = _real(self.cfg, "XAUUSD", meta={**_vm(101), **_thesis("hold")})
        _review(f"bot:{self.live.id}", verdict="exit", user=self.user)
        self.demo = _real(self.cfg, "XAGUSD", demo=True, entry="30", stop="29",
                          target="33", meta=_vm(31))
        self.paper = _trade(self.cfg, "WTIUSD", entry="70", stop="68", target="75")

    def payloads(self):
        return {"board": self.board(), "tab": self.tab(), "seat": self.seat(f"bot:{self.live.id}")}

    OPEN_SEAT = OPEN.replace("env.load();", "env.win.SVLevelEdit = {}; env.win.SVCloseAdvice = {}; env.load();") + """
        env.click(env.$('svHordeBands').querySelector('[data-open-seat="' + env.payloads.seat.seat.key + '"]'));
        await env.settle();
        const box = env.$('svHordeSeat');
    """

    # untrue 1 and 3, on screen
    def test_the_verdict_chip_and_the_thesis_slot_say_whose_they_are(self):
        got = _drive(self.OPEN_SEAT + """
            const card = env.$('svHordeBands').querySelector('[data-seat="' + env.payloads.seat.seat.key + '"]');
            const kv = box.querySelector('#svHordeSec-mission dl');
            const dts = kv.querySelectorAll('dt'), dds = kv.querySelectorAll('dd');
            const i = dts.findIndex((d) => d.textContent === "Orc's thesis");
            return {chip: card.querySelector('.hd-voice-chip').textContent,
                    chipTitle: card.querySelector('.hd-voice-chip').title,
                    slot: i >= 0 ? dds[i].textContent : null};
        """, self.payloads())
        self.assertEqual(got["chip"], "Reviewer: EXIT")
        self.assertIn("position reviewer", got["chipTitle"])
        self.assertTrue(got["slot"].startswith("No Orc has written a thesis for this seat yet."), got)
        self.assertIn("The thesis check (VOICE)", got["slot"])

    # untrue 2, on screen
    def test_the_marks_line_on_screen_is_the_servers_sentence(self):
        got = _drive(OPEN + "return env.$('svHordeNotes').textContent;", self.payloads())
        self.assertIn("REAL AND DEMO (2)", got)
        self.assertIn("PAPER (1)", got)

    # untrue 9, on screen
    def test_each_phone_command_has_its_own_copy(self):
        got = _drive(self.OPEN_SEAT + """
            const copied = [];
            env.win.navigator = undefined;
            const lis = box.querySelectorAll('.hd-phone-cmds li');
            return lis.map((li) => ({cmd: li.querySelector('.hd-cmd-text').textContent,
                                     copy: li.querySelector('.hd-copy').getAttribute('data-copy'),
                                     aria: li.querySelector('.hd-copy').getAttribute('aria-label')}));
        """, self.payloads())
        self.assertGreaterEqual(len(got), 3)
        for row in got:
            self.assertEqual(row["copy"], row["cmd"])
            self.assertEqual(row["aria"], "Copy " + row["cmd"])
            self.assertNotIn("{", row["cmd"])

    # ugly 1 is TheScriptBehaviourTests.test_the_tab_tier_follows_the_tabs_measured_content

    # ugly 2
    def test_full_tucks_the_tab_under_nothing_and_meets_the_header(self):
        """FULL left 12px of page between the header and the sheet, with
        the tab half under the header."""
        got = _drive(OPEN + """
            const root = env.$('svHorde'), tab = env.$('svHordeTab');
            tab.focus();
            env.click(root.querySelector('[data-snap="full"]'));
            await env.settle();
            const full = {h: root.style.getPropertyValue('--horde-h'),
                          tucked: root.classList.contains('hd-tab-tucked'),
                          focus: env.focusKey(),
                          count: env.$('svHordeCount').textContent};
            env.click(root.querySelector('[data-snap="half"]'));
            await env.settle();
            return {full, half: root.classList.contains('hd-tab-tucked')};
        """, self.payloads())
        self.assertEqual(got["full"]["h"], "900px")         # the harness: no header, no strip box
        self.assertTrue(got["full"]["tucked"])
        self.assertEqual(got["full"]["focus"], "svHordeTitle")
        self.assertIn("1 ALARM", got["full"]["count"])
        self.assertIn("REAL 1", got["full"]["count"])
        # Round 2: open at any height, the tab tucks (riding the sheet's
        # top it cut through the page's own lines).
        self.assertTrue(got["half"])

    # ugly 4, 5, 16
    def test_the_war_table_is_one_line_that_opens_whole(self):
        """The head's capped scroller cut the cards mid-content and left no
        seat card at HALF; its alarm chips were grey."""
        got = _drive(OPEN + """
            const sum = env.$('svHordeSum'), table = env.$('svHordeTable');
            const btn = sum.querySelector('.hd-sum-btn');
            const out = {sum: sum.textContent, hidden: table.hidden, cells: table.querySelectorAll('.hd-cell').length,
                         inBody: env.$('svHordeBody').contains(table),
                         chips: sum.querySelectorAll('.hd-chip-btn').map((c) => c.className)};
            env.click(btn);
            out.opened = {hidden: table.hidden, expanded: btn.getAttribute('aria-expanded'),
                          kept: env.store['sauron_horde_limits']};
            await env.advance(20000);                   // a poll repaints: still open
            out.afterPoll = env.$('svHordeTable').hidden;
            return out;
        """, self.payloads())
        self.assertIn("REAL risk", got["sum"])
        self.assertIn("PAPER risk", got["sum"])
        self.assertTrue(got["hidden"])
        self.assertTrue(got["inBody"])
        self.assertGreaterEqual(got["cells"], 2)
        self.assertEqual(got["opened"], {"hidden": False, "expanded": "true", "kept": "1"})
        self.assertFalse(got["afterPoll"])
        self.assertTrue(any("hd-chip-btn--alarm" in c for c in got["chips"]), got["chips"])

    def test_an_unmeasured_stop_is_a_dash_on_the_summary(self):
        from django.core.cache import cache as c
        board = self.board()
        board["head"]["sides"]["live"]["daily"]["mode"] = "unmeasured"
        got = _drive(OPEN + "return env.$('svHordeSum').textContent;",
                     {"board": board, "tab": self.tab(), "seat": self.seat(f"bot:{self.live.id}")})
        c.clear()
        self.assertIn("REAL risk", got)
        self.assertRegex(got, r"REAL risk [^·]+· daily stop —")

    def test_half_shows_the_first_row_of_cards_whole(self):
        """At 1100x800 HALF showed no seat card: HALF is the larger of half
        the room and the height the first row of cards needs, measured."""
        got = _drive(OPEN + """
            const root = env.$('svHorde'), body = env.$('svHordeBody');
            body._clientHeight = 200;                      // what the body has at half (450)
            body._rect = {top: 300, bottom: 500, height: 200};
            const card = env.$('svHordeBands').querySelector('.hd-seat');
            card._rect = {top: 560, bottom: 650, height: 90};   // its bottom 350px into the body
            env.click(root.querySelector('[data-snap="half"]'));
            await env.settle();
            return root.style.getPropertyValue('--horde-h');
        """, self.payloads())
        # chrome (450 - 200) + the card's bottom in the body (350) + 8 of air
        self.assertEqual(got, "608px")

    # ugly 7, 10
    def test_a_chip_lands_its_heading_under_the_pinned_head(self):
        got = _drive(self.OPEN_SEAT + """
            const head = box.querySelector('.hd-dos-head');
            head._rect = {top: 0, bottom: 123, height: 123};
            const chips = box.querySelector('.hd-dos-chips');
            env.doc.scrolledIntoView = [];
            env.click(chips.querySelectorAll('.hd-chip-btn')[3]);     // Activity
            return {var: box.style.getPropertyValue('--hd-dos-head-h'),
                    went: env.doc.scrolledIntoView};
        """, self.payloads())
        self.assertEqual(got["var"], "123px")
        self.assertEqual(got["went"][-1]["id"], "svHordeSec-activity")
        self.assertEqual(got["went"][-1]["opts"]["block"], "start")

    # ugly 12
    def test_the_correlated_rows_wrap_and_their_buttons_stand_apart(self):
        got = _drive(self.OPEN_SEAT + """
            const sec = env.$('svHordeSec-instruments');
            return {table: sec.querySelectorAll('table').length,
                    rows: sec.querySelectorAll('.hd-peer').map((li) => ({
                        top: li.querySelector('.hd-peer-row').textContent,
                        acts: li.querySelector('.hd-peer-acts').querySelectorAll('button, a').map((b) => b.textContent)}))};
        """, self.payloads())
        self.assertEqual(got["table"], 0)
        self.assertTrue(got["rows"])
        for row in got["rows"]:
            self.assertTrue(row["acts"], row)

    # ugly 14
    def test_no_line_opens_with_a_middle_dot(self):
        """"· 25,840.55, the broker account", "· at the stops 27.60": the
        dot ends the piece before it (a no-break space binds it there),
        and no box of a wrapping row starts with one."""
        got = _drive(self.OPEN_SEAT + """
            env.click(env.$('svHordeSum').querySelector('.hd-sum-btn'));
            await env.settle();
            const bad = [];
            const walk = (n) => n.childNodes.forEach((c) => {
                if (c.nodeType === 3) { if (/ \\u00b7/.test(c.data)) bad.push('space-dot: ' + c.data); return; }
                const t = c.textContent;
                if (/^\\s*\\u00b7/.test(t) && !(c.classList.contains('hd-muted') || c.classList.contains('hd-sep')))
                    bad.push('starts: ' + c.className + ' ' + t.slice(0, 40));
                walk(c);
            });
            ['svHordeSum', 'svHordeTable', 'svHordeNotes', 'svHordeBands'].forEach((id) => walk(env.$(id)));
            return {bad, units: env.$('svHordeBands').querySelectorAll('.hd-line .hd-unit').length};
        """, self.payloads())
        self.assertEqual(got["bad"], [])
        self.assertGreater(got["units"], 0)

    # ugly 15
    CARD = """
            const card = env.$('svHordeBands').querySelector('[data-seat="' + env.payloads.seat.seat.key + '"]');
            const rows = card.querySelectorAll('.hd-seat-row').map((r) => ({
                cls: r.className + (r.parentNode.className === 'hd-seat-foot hd-phone-hide' ? ' IN-FOOT' : ''),
                kids: r.children.map((k) => k.className), t: r.textContent}));
            return rows;
    """

    # round 2: the phone split "-0.50R", "-57.24 USD" and "7.12860 venue"
    # over three places; the desktop card ran "held" into the holder and
    # "% to the stop" into the target, and "No Orc" moved up and down.
    def test_a_card_says_its_money_as_one_unit(self):
        for phone in (True, False):
            got = _drive(("env.media.matches = true;" if phone else "") + OPEN + self.CARD,
                         self.payloads())
            head, mission, money = got[0], got[1], got[2]
            self.assertFalse(any("hd-r" in k.split() for k in head["kids"]), (phone, head))
            self.assertIn("hd-mission", mission["kids"])
            self.assertEqual(money["cls"], "hd-seat-row hd-money-row", (phone, money))
            self.assertEqual([k.split()[0] for k in money["kids"]][:3], ["hd-r", "hd-pnl", "hd-mark"],
                             (phone, money))
            if phone:
                continue
            dist = [r for r in got if "hd-stop-dist" in r["cls"]]
            self.assertEqual(len(dist), 1)
            self.assertIn("% to the stop", dist[0]["t"])
            self.assertNotIn("to the stop", "".join(r["t"] for r in got if "hd-stop-dist" not in r["cls"]))
            age, holder = got[-2], got[-1]
            self.assertIn("IN-FOOT", age["cls"])
            self.assertIn("IN-FOOT", holder["cls"])
            self.assertTrue(age["t"].startswith("position open "), age["t"])   # its own subject
            self.assertNotIn("position open", holder["t"])
            self.assertTrue(holder["t"].rstrip().endswith("No Orc"), holder["t"])
            voice = [r for r in got if any("hd-voice-chip" in k for k in r["kids"])]
            self.assertEqual(len(voice), 1)
            self.assertEqual(len(voice[0]["kids"]), 1)                      # a row of its own

    # round 2: placed after the Commands heading, the bar scrolled away
    # once Instruments was read
    def test_the_command_bar_is_the_dossiers_last_child(self):
        got = _drive(self.OPEN_SEAT + """
            const kids = box.children;
            const last = kids[kids.length - 1];
            const ids = kids.map((k) => k.id);
            return {last: last.id, cls: last.className, btns: last.querySelectorAll('button').length,
                    afterInstruments: ids.indexOf('svHordeCmds') > ids.indexOf('svHordeSec-instruments')};
        """, self.payloads())
        self.assertEqual(got["last"], "svHordeCmds")
        self.assertIn("hd-dos-cmdbar", got["cls"])
        self.assertGreater(got["btns"], 0)
        self.assertTrue(got["afterInstruments"])

    # round 2: the page's side-panel toggles stood on the open sheet's head
    def test_the_side_toggles_leave_the_sheets_head(self):
        got = _drive(OPEN + """
            const root = env.$('svHorde');
            env.click(root.querySelector('[data-snap="half"]'));
            await env.settle();
            const half = env.doc.body.style.getPropertyValue('--hd-toggle-y');
            const h = parseFloat(root.style.getPropertyValue('--horde-h'));
            env.click(env.$('svHordeClose'));
            await env.settle();
            return {half, h, vh: env.win.innerHeight,
                    closed: env.doc.body.style.getPropertyValue('--hd-toggle-y')};
        """, self.payloads())
        sheet_top = got["vh"] - got["h"]                       # the harness: no strip, no header
        y = float(got["half"].replace("px", ""))
        self.assertLessEqual(y + 28 + 8, sheet_top + 1, got)   # the 56px toggle ends 8px above it
        self.assertEqual(got["closed"], "")

    def test_the_dossier_head_is_one_row_of_compact_buttons(self):
        got = _drive("""
            env.media.matches = true;
            env.win.SVLevelEdit = {}; env.win.SVCloseAdvice = {};
            env.load();
            await env.settle();
            env.click(env.$('svHordeTab'));
            await env.settle();
            env.click(env.$('svHordeBands').querySelector('[data-open-seat="' + env.payloads.seat.seat.key + '"]'));
            await env.settle();
            const tools = env.$('svHordeSeat').querySelector('.hd-dos-title .hd-dos-tools');
            return tools.querySelectorAll('button').map((b) => [b.textContent, b.getAttribute('aria-label')]);
        """, self.payloads())
        self.assertEqual(got, [["‹ Back", "Back to the Horde"], ["\u21bb", "Refresh this seat"],
                               ["×", "Close this dossier"]])


class TheScreenshotReviewSheetTests(SimpleTestCase):
    """What only a layout engine can show is pinned in the sheet's own
    words here, and was measured in Chromium at 1100, 1380, 1440 and 390
    (polish/shoot.js: no floating control over a pill or a money line,
    the tab whole, HALF with a whole row of cards, the dossier's room)."""

    def setUp(self):
        self.css = _strip_css(SHEET.read_text(encoding="utf-8"))
        self.phone = re.search(r"@media \(max-width: 768px\) \{(.*?)\n\}", self.css, re.S).group(1)

    def _rule(self, selector, text=None):
        m = re.search(r"(?:^|\})\s*" + re.escape(selector) + r"\s*\{([^}]*)\}", text or self.css)
        self.assertIsNotNone(m, selector)
        return " ".join(m.group(1).split())

    # ugly 3
    def test_the_floating_controls_never_stand_over_the_content(self):
        root = self._rule(".sv-horde")
        # Gollum: 18px inside the left chrome, a fab wide; the Eye: the
        # right edge's own distance, a fab wide; 8px of air each.
        self.assertIn("--hd-gut-l: max(32px, calc(var(--se-left-chrome, 0px) + 18px + "
                      "var(--se-fab-size, 56px) + 8px - var(--hd-l)));", root)
        self.assertIn("--hd-gut-r: max(32px, calc(var(--se-right-edge, 0px) + "
                      "var(--se-fab-size, 56px) + 8px - var(--hd-r)));", root)
        self.assertIn("--hd-foot: 28px;", root)                 # the strip's minimize tab
        self.assertIn("padding-bottom: var(--hd-foot);", self._rule(".sv-horde-panel"))
        self.assertIn("--hd-foot: 44px;", self._rule("body:has(.info-panel-wrap.minimized) .sv-horde"))
        self.assertIn("z-index: calc(var(--z-horde) - 1) !important;",
                      self._rule("body:has(.sv-horde.open) .gollum-bubble"))
        self.assertIn("z-index: calc(var(--z-horde) - 1) !important;",
                      self._rule("body:has(.sv-horde.open) .se-eye-fab", self.phone))
        self.assertRegex(self.phone, r"\.sv-horde \{ --hd-foot: 0px; \}")
        self.assertNotIn("info-panel-wrap", self.phone)

    # ugly 6, 8, 9
    def test_the_dossier_has_the_room_and_the_pinned_boxes_do_not_meet(self):
        col = self._rule(".sv-horde.hd-w-l .hd-dossier")
        self.assertIn("max-height: calc(var(--hd-body-h, 300px) - 10px);", col)
        self.assertNotIn("se-fab", col)
        self.assertIn("z-index: calc(var(--z-sticky) + 1);", self._rule(".hd-dos-head"))
        self.assertIn("z-index: var(--z-sticky);", self._rule(".hd-dos-cmdbar"))
        self.assertIn("scroll-margin-top: calc(var(--hd-dos-head-h, 0px) + 8px);",
                      self._rule(".hd-dos-sec"))
        self.assertNotRegex(self.css, r"#svHordeTable\s*\{[^}]*max-height")

    # ugly 10
    def test_the_chip_row_wraps_and_shows_every_chip(self):
        """Round 2: a sideways scroller hid Instruments behind a fade
        ("Comm..."): the row wraps, all seven chips on screen."""
        chips = self._rule(".hd-dos-chips")
        self.assertIn("flex-wrap: wrap;", chips)
        self.assertNotIn("overflow-x", chips)
        self.assertNotIn("hd-more-r", self.css)

    # ugly 11
    # round 2
    def test_the_side_toggles_follow_the_open_sheet(self):
        self.assertIn("body:has(.sv-horde.open) .rail-toggle-btn { top: var(--hd-toggle-y, 50%); }",
                      " ".join(self.css.split()))

    def test_the_alarms_are_said_once_in_the_open_head(self):
        flat = " ".join(self.css.split())
        self.assertIn(".sv-horde.open:not(.hd-phone) .hd-head:has(.hd-sum-chips .hd-chip-btn--alarm) "
                      ".hd-count-alarms { display: none; }", flat)
        self.assertIn(".sv-horde.hd-limits-open .hd-head:has(.hd-sum-chips .hd-chip-btn--alarm) "
                      ".hd-count-alarms { display: none; }", " ".join(self.phone.split()))
        self.assertIn("'hd-tab-alarms hd-count-alarms'", JS.read_text(encoding="utf-8"))

    def test_the_phone_expander_rides_the_captains_line(self):
        rule = self._rule(".hd-band-head .hd-expander", self.phone)
        self.assertNotIn("flex-basis: 100%", rule)
        self.assertIn("padding: 14px 0; margin: -14px 0;", rule)       # a 44px hit area, no gap

    def test_no_real_glow_bleeds_over_the_scroll_edge(self):
        self.assertEqual(self._rule(".hd-body .sv-world--live"), "box-shadow: none;")

    def test_no_orc_stands_at_the_cards_foot(self):
        self.assertIn("display: flex; flex-direction: column;", self._rule(".hd-seat"))
        self.assertIn("margin-top: auto;", self._rule(".hd-seat-foot"))

    def test_stop_target_reads_as_a_button(self):
        lvl = self._rule(".hd-cmds .hd-btn.lvl-edit")
        for decl in ("display: inline-block;", "width: auto;", "text-align: center;",
                     "border: 1px solid var(--border);"):
            self.assertIn(decl, lvl)

    # ugly 13
    def test_the_phone_bar_sits_on_the_sheets_bottom(self):
        self.assertIn("padding: 0 12px;", self._rule(".hd-body", self.phone))
        self.assertIn("padding: 6px 0;", self._rule(".hd-dos-cmdbar", self.phone))

    # ugly 16
    def test_the_alarm_chips_wear_the_tabs_colours(self):
        self.assertIn("var(--danger)", self._rule(".hd-chip-btn--alarm"))
        self.assertIn("var(--warning)", self._rule(".hd-chip-btn--watch"))


# ── the final review (2026-10-16): the minor items left after round 2 ───

@override_settings(CACHES=LOCMEM)
class TheFinalReviewTests(_Base):
    """The words the server sends, after the last screenshot review."""

    def setUp(self):
        super().setUp()
        self.cfg = _cfg(self.user)
        _instrument("XAUUSD")

    def test_the_phone_hint_reads_the_eyes_own_daily_cap(self):
        from bot_program.telegram_eye import QUESTIONS_PER_DAY
        t = _real(self.cfg, "XAUUSD", meta=_vm(101))
        lines = [p["t"] for p in self.seat(f"bot:{t.id}")["phone"]]
        ask = [x for x in lines if x.startswith("Ask Sauron anything")]
        self.assertEqual(len(ask), 1, lines)
        self.assertIn(f"({QUESTIONS_PER_DAY} a day)", ask[0])
        self.assertNotIn("{", ask[0])
        with mock.patch("bot_program.telegram_eye.QUESTIONS_PER_DAY", 7):
            cache.clear()
            again = [p["t"] for p in self.seat(f"bot:{t.id}")["phone"]
                     if p["t"].startswith("Ask Sauron anything")]
        self.assertIn("(7 a day)", again[0])

    def test_the_time_stop_says_where_its_hours_come_from_in_words(self):
        t = _real(self.cfg, "XAUUSD", meta=_vm(101))
        line = [m for m in self.seat(f"bot:{t.id}")["metrics"] if m["label"] == "Time stop"][0]
        self.assertTrue(line["t"].endswith("h after entry (the class default)"), line)
        self.assertNotIn("class-default", line["t"])
        self.cfg.max_hold_hours = 48
        self.cfg.save(update_fields=["max_hold_hours"])
        cache.clear()
        line = [m for m in self.seat(f"bot:{t.id}")["metrics"] if m["label"] == "Time stop"][0]
        self.assertEqual(line["t"], "Time stop: 48 h after entry (set on the bot)")

    def test_a_care_mirror_row_prints_its_stop_like_the_engine_rows(self):
        from bot_program.aragorn_models import AragornAction
        from core.price_format import format_price
        t = _real(self.cfg, "XAUUSD", entry="4141.3", stop="4098", target="4260",
                  meta={**_vm(4182.1), "stop_moves": [
                      {"to": 4160.0, "asked": 4160.0, "why": "trail:broker",
                       "when": timezone.now().isoformat()}]})
        # The production sentence (bot_program/position_care.py, :g).
        AragornAction.objects.create(
            kind="care_mirror", trade_id=t.id, symbol="XAUUSD",
            detail="REAL MONEY: the venue stop follows the trail to 4160 — the lock "
                   "outlives the platform",
            stats={"soft_stop": 4160.0, "venue_stop": 4160.0})
        # A row with no stat keeps its words.
        AragornAction.objects.create(kind="care_mirror", trade_id=t.id, symbol="XAUUSD",
                                     detail="REAL MONEY: moved")
        rows = self.seat(f"bot:{t.id}")["timeline"]
        want = format_price(4160.0, "commodity", "XAUUSD")
        engine = [e["t"] for e in rows if e["author"] == "ENGINE"]
        care = [e["t"] for e in rows if e["author"] == "CARE"]
        self.assertTrue(any(want in x for x in engine), engine)
        self.assertIn(f"REAL MONEY: the venue stop follows the trail to {want} — the lock "
                      "outlives the platform", care)
        self.assertIn("REAL MONEY: moved", care)
        self.assertFalse(any(" to 4160 " in x for x in care), care)

    def test_a_price_without_a_day_change_says_why_with_a_dash(self):
        _instrument("NSDQ100", "index")
        stock = _cfg(self.user, cls="stock", name="s", symbols=["NSDQ100"])
        _real(stock, "NSDQ100", entry="24000", stop="23800", target="24500", meta=_vm(24856))
        gold = _real(self.cfg, "XAUUSD", entry="4141.3", stop="4098", target="4260",
                     meta=_vm(4182.1))
        peer = [p for p in self.seat(f"bot:{gold.id}")["instruments"]["peers"]
                if p["symbol"] == "NSDQ100"][0]
        self.assertIsNotNone(peer["last_t"])
        self.assertIsNone(peer["change_t"])
        self.assertEqual(peer["change_why"], horde_mod().CHANGE_NONE_VENUE)

    def test_the_strip_says_which_books_its_open_pnl_adds(self):
        from django.template.loader import get_template
        src = get_template("base.html").template.source
        sub = re.search(r'data-sv-live="hb-pnl-sub"[^>]*>(.*?)</span>', src, re.S).group(1)
        self.assertIn("real + paper across {{ panel_positions_priced }} of", sub)
        self.assertIn("real + paper across {{ panel_positions }} position", sub)


def horde_mod():
    from dashboard import horde
    return horde


@unittest.skipUnless(NODE, "node is not installed")
@override_settings(CACHES=LOCMEM)
class TheFinalReviewScriptTests(_Base):
    """The phone card and the dossier, driven in tests/horde_dom_harness.js."""

    def setUp(self):
        super().setUp()
        self.cfg = _cfg(self.user)
        _instrument("XAUUSD")
        _instrument("XAGUSD")
        self.live = _real(self.cfg, "XAUUSD", meta={**_vm(101), **_thesis("hold")})
        self.paper = _trade(self.cfg, "XAGUSD", entry="30", stop="29", target="33")

    def payloads(self, key=None):
        return {"board": self.board(), "tab": self.tab(),
                "seat": self.seat(key or f"bot:{self.live.id}")}

    ROWS = OPEN + """
        const card = env.$('svHordeBands').querySelector('[data-seat="' + env.payloads.seat.seat.key + '"]');
        return {tone: card.getAttribute('data-tone'),
                rows: card.querySelectorAll('.hd-seat-row').map((r) => ({cls: r.className, t: r.textContent}))};
    """

    def test_a_phone_alarm_names_the_voice_that_raised_it(self):
        _review(f"bot:{self.live.id}", verdict="exit", user=self.user)
        got = _drive("env.media.matches = true;" + self.ROWS, self.payloads())
        self.assertEqual(got["tone"], "alarm")
        voice = [r for r in got["rows"] if "Reviewer: EXIT" in r["t"]]
        self.assertEqual(len(voice), 1, got)
        self.assertNotIn("hd-phone-hide", voice[0]["cls"])
        self.assertFalse(any("hd-light-why" in r["cls"] for r in got["rows"]), got)

    def test_a_calm_voice_is_never_shown_as_the_cause(self):
        """The reviewer says HOLD; the alarm is the price through the
        stop: the phone card says that reason, and the HOLD chip stays
        folded."""
        _review(f"bot:{self.live.id}", verdict="hold", user=self.user)
        self.live.metadata = {**self.live.metadata, **_vm(90)}
        self.live.save(update_fields=["metadata"])
        got = _drive("env.media.matches = true;" + self.ROWS, self.payloads())
        self.assertEqual(got["tone"], "alarm")
        voice = [r for r in got["rows"] if "Reviewer:" in r["t"]]
        self.assertTrue(all("hd-phone-hide" in r["cls"] for r in voice), got)
        why = [r for r in got["rows"] if "hd-light-why" in r["cls"]]
        self.assertEqual(len(why), 1, got)
        self.assertIn("through the stop", why[0]["t"])

    def test_a_phone_watch_says_its_first_reason(self):
        got = _drive("env.media.matches = true;" + self.ROWS,
                     self.payloads(f"bot:{self.paper.id}"))
        self.assertEqual(got["tone"], "watch")
        why = [r for r in got["rows"] if "hd-light-why" in r["cls"]]
        self.assertEqual(len(why), 1, got)
        self.assertEqual(why[0]["t"], "The care has no record of this row yet.")

    def test_the_phone_bar_asks_in_two_words_and_keeps_the_full_title(self):
        open_seat = (OPEN.replace("env.load();", "env.win.SVLevelEdit = {}; env.win.SVCloseAdvice = {}; env.load();")
                     + """
            env.click(env.$('svHordeBands').querySelector('[data-open-seat="' + env.payloads.seat.seat.key + '"]'));
            await env.settle();
            const b = env.$('svHordeCmds').querySelectorAll('button')[0];
            return {t: b.textContent, title: b.title};
        """)
        phone = _drive("env.media.matches = true;" + open_seat, self.payloads())
        wide = _drive(open_seat, self.payloads())
        self.assertEqual(phone, {"t": "Ask Sauron", "title": "Ask Sauron about this seat"})
        self.assertEqual(wide["t"], "Ask Sauron about this seat")

    def test_a_band_line_wraps_its_words_beside_the_pill(self):
        got = _drive(OPEN + """
            const line = env.$('svHordeBands').querySelector('.hd-line');
            return {kids: line.children.map((k) => k.className),
                    units: line.children[1].querySelectorAll('.hd-unit').length};
        """, self.payloads())
        self.assertEqual(len(got["kids"]), 2, got)
        self.assertIn("sv-world", got["kids"][0])
        self.assertEqual(got["kids"][1], "hd-line-words")
        self.assertGreater(got["units"], 0)

    def test_the_marks_note_breaks_between_whole_segments(self):
        got = _drive(OPEN + """
            const note = env.$('svHordeNotes').querySelector('.hd-note-units');
            return {units: note.querySelectorAll('.hd-unit').map((u) => u.textContent),
                    t: note.textContent};
        """, self.payloads())
        self.assertTrue(got["units"], got)
        self.assertEqual(got["units"][0], "MARKS\u00a0\u00b7")
        self.assertIn("PAPER (1)", got["t"])
        self.assertNotIn(" \u00b7", got["t"])

    def test_a_peer_price_without_a_change_shows_a_titled_dash(self):
        _instrument("NSDQ100", "index")
        stock = _cfg(self.user, cls="stock", name="s", symbols=["NSDQ100"])
        _real(stock, "NSDQ100", entry="24000", stop="23800", target="24500", meta=_vm(24856))
        got = _drive(OPEN.replace("env.load();", "env.win.SVLevelEdit = {}; env.win.SVCloseAdvice = {}; env.load();") + """
            env.click(env.$('svHordeBands').querySelector('[data-open-seat="' + env.payloads.seat.seat.key + '"]'));
            await env.settle();
            const px = env.$('svHordeSeat').querySelector('[data-peer-last="NSDQ100"]');
            const d = px.querySelector('.sv-unknown');
            return {t: px.textContent, dash: d ? d.textContent : null, title: d ? d.title : null};
        """, self.payloads())
        self.assertTrue(got["t"].endswith(" —"), got)
        self.assertEqual(got["dash"], "—")
        self.assertIn("No day change", got["title"])


class TheFinalReviewSheetTests(SimpleTestCase):
    """The final review's layout, pinned in the sheet's own words (measured
    in Chromium at 1100, 1380, 1440 and 390: polish/shots_r3)."""

    def setUp(self):
        self.css = _strip_css(SHEET.read_text(encoding="utf-8"))
        self.phone = re.search(r"@media \(max-width: 768px\) \{(.*?)\n\}", self.css, re.S).group(1)
        self.code = _strip_js(JS.read_text(encoding="utf-8"))

    def _rule(self, selector, text=None):
        m = re.search(r"(?:^|\})\s*" + re.escape(selector) + r"\s*\{([^}]*)\}", text or self.css)
        self.assertIsNotNone(m, selector)
        return " ".join(m.group(1).split())

    def test_a_band_line_keeps_its_pill_in_a_column_of_its_own(self):
        self.assertIn("flex-wrap: nowrap;", self._rule(".hd-line"))
        self.assertIn("flex: none;", self._rule(".hd-line > .sv-world, .hd-line > .hd-no-venue"))
        words = self._rule(".hd-line-words")
        self.assertIn("flex-wrap: wrap;", words)
        self.assertIn("row-gap: 0;", words)
        self.assertIn("min-width: 0;", words)

    def test_a_line_never_ends_on_a_dangling_dot(self):
        self.assertEqual(self._rule(".hd-unit.hd-eol > .hd-sep"), "visibility: hidden;")
        self.assertIn("u.classList.toggle('hd-eol', eol);", self.code)
        self.assertIn("lineEndsSoon();", self.code[self.code.index("function paintBoard("):])

    def test_the_phone_card_head_has_no_44px_box_of_its_own(self):
        self.assertIn("min-height: 0;", self._rule(".hd-seat-open", self.phone))
        tap = [r for r in re.findall(r"([^{}]+)\{\s*min-height: 44px;", self.phone)]
        self.assertTrue(tap)
        self.assertFalse(any(".hd-seat-open" in r for r in tap), tap)
        # The card stays one tap target: the button's ::after covers it.
        self.assertIn("inset: 0;", self._rule(".hd-seat-open::after"))
        self.assertEqual(self._rule(".hd-light-why"), "display: none;")
        self.assertEqual(self._rule(".hd-light-why", self.phone), "display: flex;")

    def test_an_open_seat_folds_the_book_limits_and_marks_on_the_phone(self):
        flat = " ".join(self.phone.split())
        self.assertIn(".sv-horde.hd-has-seat .hd-sum, .sv-horde.hd-has-seat .hd-notes > .hd-note "
                      "{ display: none; }", flat)
        # A failed read is still said.
        self.assertIn(".sv-horde.hd-has-seat .hd-notes:not(:has(.hd-failed)) { display: none; }", flat)

    def test_the_phone_pill_is_the_eyes_size_so_the_pages_padding_clears_it(self):
        tab = self._rule(".sv-horde-tab", self.phone)
        self.assertIn("height: var(--se-fab-size, 48px);", tab)
        self.assertIn("bottom: var(--se-bottom-edge);", tab)
        resp = " ".join(_read("static", "css", "sv-responsive.css").split())
        self.assertIn("padding-bottom: calc(var(--sv-bottom-chrome) + var(--se-fab-size) + 28px) !important;",
                      resp)
        self.assertIn("html body:has(.sv-phone-nav .sv-pn-item) { --se-bottom-edge: "
                      "calc(var(--sv-bottom-chrome) + 12px); }", resp)


# ── 13.13 a stored reason is said, never forwarded ───────────────────────
#
# The council band's review (2026-10-23): the dossier printed the trade
# debate's raw `why`, which can carry an exception's text (ai_agents/agents/
# trade_debate.py debate_candidate) and an amount of money (the AI budget's
# refusal is in dollars, and a side may echo the brief's "risk at the stop
# N"). Every free text the Horde forwards is fed here through its real
# producer (or a faithful fake of the last write) with an exception-like and
# an amount-like piece: the payload and the painted page never carry them,
# and the cause is still said in words (dashboard/plain_words.py).

#: An exception's text with an amount inside it, as a transport error
#: prints itself (str(e) of a requests ConnectionError).
EXC_TEXT = ("HTTPSConnectionPool(host='api.etoro.com'): Max retries exceeded "
            "(Caused by NewConnectionError: margin 1,234.56 USD)")
EXC_FRAGS = ("HTTPSConnectionPool", "NewConnectionError", "api.etoro.com",
             "Max retries", "Caused by", "1,234.56")

#: The band and the open dossier as the script paints them: every text and
#: every attribute of the document, the "more" of a long answer unfolded.
_WALK = """
    const out = [];
    const walk = (n) => {
      if (n.nodeType === 3) { out.push(n.data); return; }
      Object.keys(n.attrs || {}).forEach((k) => out.push(String(n.attrs[k])));
      (n.childNodes || []).forEach(walk);
    };
    walk(env.doc.documentElement);
    return out.join('\\n');
"""
BAND_DOM = OPEN + _WALK
SEAT_DOM = (OPEN.replace("env.load();", "env.win.SVLevelEdit = {}; "
                         "env.win.SVCloseAdvice = {}; env.load();") + """
    env.click(env.$('svHordeBands').querySelector('[data-open-seat="' + env.payloads.seat.seat.key + '"]'));
    await env.settle();
    env.$('svHordeSeat').querySelectorAll('.hd-expander').forEach((b) => env.click(b));
    await env.settle();
""" + _WALK)


def _debate_cand(price=2000.0, stop=1950.0, target=2150.0):
    """A live candidate as the engine hands it to the debate (bot_program/
    asset_engine/base.py EntryCandidate: the fields candidate_brief reads)."""
    from types import SimpleNamespace
    return SimpleNamespace(
        symbol="XAUUSD", asset_class="commodity", price=price, stop=stop,
        target=target, cost={"fraction": 0.001}, value_per_unit=1.0, elite=None,
        decision=SimpleNamespace(direction="BUY", rule_name="golden_cross",
                                 score=0.7,
                                 reasons=["bull evidence +1.20 clears 0.50"]))


def _debate_bot(cfg):
    from types import SimpleNamespace
    return SimpleNamespace(cfg=cfg, _instrument_class=lambda symbol: "commodity")


def _recorded(debate):
    """What the engine keeps of a debate on the row it opens (bot_program/
    asset_engine/base.py, the trade debate: only while the debate is on)."""
    assert debate.get("on"), debate
    return {k: debate.get(k) for k in (
        "ran", "binding", "graded", "why", "executioner", "champion",
        "champion_wins", "council_id")}


@override_settings(CACHES=LOCMEM)
class TheStoredReasonTests(_Base):
    """The debate's `why`, the voices' words, the venue's refusals, the
    thesis check's unread words and the gate's failure: said by cause."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # The council subclasses the debate's agents when it is imported
        # (ai_agents/agents/council.py CouncilExecutioner, CouncilChampion).
        # The tests below stand the agents in for the debate and patch the
        # council's open_debate_session, which imports the council: done
        # here first, a worker never builds the council's voices on a
        # stand-in, and the council's own suites never meet one.
        import ai_agents.agents.council  # noqa: F401

    def setUp(self):
        super().setUp()
        self.cfg = _cfg(self.user)
        _instrument("XAUUSD")

    def _all(self, key):
        """(the payloads as one text, the payloads, the painted page)."""
        payloads = {"board": self.board(), "tab": self.tab(), "seat": self.seat(key)}
        page = _drive(SEAT_DOM, payloads) if NODE else ""
        return json.dumps(payloads, ensure_ascii=False), payloads, page

    def _never(self, frags, *texts):
        for text in texts:
            for frag in frags:
                self.assertNotIn(frag, text)

    def _debated(self, debate, meta=None, **kw):
        kw.setdefault("entry", "2000")
        kw.setdefault("stop", "1950")
        kw.setdefault("target", "2150")
        kw.setdefault("qty", "5")
        return _real(self.cfg, "XAUUSD",
                     meta={**_vm(2010), "debate": _recorded(debate), **(meta or {})},
                     **kw)

    def _argued(self, killer, edge, record=False):
        """A debate argued through debate_candidate (price 2000, stop 1950,
        size 5: "risk at the stop 250.00") whose sides answer from the
        brief they were shown: `killer` and `edge` are formatted with its
        amount and its net reward:risk. `record` lets the council keep its
        record of the debate (the brief and its candidate)."""
        from ai_agents.agents import trade_debate
        _switches(trade_debate=True)
        real_ex, real_ch = trade_debate.ExecutionerAgent, trade_debate.ChampionAgent

        def read(brief):
            return {"amount": re.search(r"risk at the stop ([\d,.]+)", brief).group(1),
                    "rr": re.search(r"net reward:risk ([\d.]+)", brief).group(1)}

        class Ex:
            def run(self, brief="", **kw):
                return real_ex.parse_response(None, json.dumps({
                    "verdict": "cut", "conviction": 0.6, "size_scale": 0.5,
                    "killer": killer.format(**read(brief)), "reasons": []}))

        class Ch:
            def run(self, brief="", **kw):
                return real_ch.parse_response(None, json.dumps({
                    "verdict": "back", "conviction": 0.7,
                    "edge": edge.format(**read(brief)), "reasons": []}))

        with mock.patch.object(trade_debate, "ExecutionerAgent", Ex), \
                mock.patch.object(trade_debate, "ChampionAgent", Ch):
            if record:
                return trade_debate.debate_candidate(_debate_bot(self.cfg),
                                                     _debate_cand(), 5.0)
            with mock.patch("ai_agents.agents.council.open_debate_session",
                            return_value=None):
                return trade_debate.debate_candidate(_debate_bot(self.cfg),
                                                     _debate_cand(), 5.0)

    # the debate's `why`

    def test_a_budget_refusal_says_the_budget_and_never_its_dollars(self):
        from ai_agents.agents.trade_debate import debate_candidate
        from ai_agents.models import AgentTask
        _switches(trade_debate=True)
        AgentTask.objects.create(agent="news_analyst", provider="anthropic",
                                 model="m-1", prompt_summary="x",
                                 cost_usd=Decimal("5.03"))
        ai = {**getattr(settings, "AI_CONFIG", {}), "daily_budget_usd": 5.0,
              "orc_daily_budget_usd": 0}
        with self.settings(AI_CONFIG=ai):
            debate = debate_candidate(_debate_bot(self.cfg), _debate_cand(), 5.0)
        # The producer's own words carry the dollars (ai_agents/spend.py).
        self.assertFalse(debate["ran"])
        self.assertIn("$5.03", debate["why"])
        t = self._debated(debate)
        text, p, page = self._all(f"bot:{t.id}")
        said = p["seat"]["mission"]["debate"]["t"]
        self.assertTrue(said.endswith(" · Not argued: today's AI budget refused it"), said)
        self.assertIn("Not argued: today's AI budget refused it", page)
        self._never(("$5.03", "5.03", "AI budget:", "daily AI budget spent"), text, page)

    def test_a_debate_that_failed_says_so_and_never_the_exception(self):
        from django.db.utils import OperationalError

        from ai_agents.agents import trade_debate
        _switches(trade_debate=True)
        boom = OperationalError("could not read the ledger: equity 1,234.56 USD")
        with mock.patch.object(trade_debate, "candidate_brief", side_effect=boom):
            debate = trade_debate.debate_candidate(_debate_bot(self.cfg),
                                                   _debate_cand(), 5.0)
        self.assertTrue(debate["why"].startswith("debate unavailable (OperationalError: "),
                        debate["why"])
        t = self._debated(debate)
        text, p, page = self._all(f"bot:{t.id}")
        said = p["seat"]["mission"]["debate"]["t"]
        self.assertTrue(said.endswith(
            " · Not argued: the debate failed before either side was asked"), said)
        self.assertIn("the debate failed before either side was asked", page)
        self._never(("OperationalError", "could not read the ledger", "1,234.56",
                     "debate unavailable"), text, page)

    def test_a_silent_side_is_named_in_words_never_its_exception(self):
        import threading

        from ai_agents.agents import trade_debate
        _switches(trade_debate=True)
        gate = threading.Event()

        class Broken:
            def run(self, **kw):
                raise ValueError("no JSON object with a verdict in the answer: "
                                 "risk at the stop 250.00")

        class Slow:
            def run(self, **kw):
                gate.wait(10)

        try:
            with mock.patch.object(trade_debate, "ExecutionerAgent", Broken), \
                    mock.patch.object(trade_debate, "ChampionAgent", Slow), \
                    mock.patch.object(trade_debate, "DEBATE_TIMEOUT_S", 0.3), \
                    mock.patch("ai_agents.agents.council.open_debate_session",
                               return_value=None):
                debate = trade_debate.debate_candidate(_debate_bot(self.cfg),
                                                       _debate_cand(), 5.0)
        finally:
            gate.set()
        self.assertEqual(debate["why"], "executioner unavailable (ValueError); "
                                        "champion unavailable (timeout)")
        t = self._debated(debate)
        text, p, page = self._all(f"bot:{t.id}")
        said = p["seat"]["mission"]["debate"]["t"]
        want = ("Not argued in full: the Executioner's call failed; the Champion "
                "did not answer in time")
        self.assertTrue(said.endswith(" · " + want), said)
        self.assertIn(want, page)
        self._never(("ValueError", "unavailable", "no JSON object"), text, page)

    def test_a_side_that_echoes_the_briefs_amount_is_withheld_whole(self):
        """The brief puts the risk at the stop before both sides
        (trade_debate.candidate_brief); a side that repeats it, even bare,
        is withheld whole. A side that names an exception is withheld
        whole too: nothing is cut out of a voice's line."""
        from ai_agents.agents import trade_debate
        _switches(trade_debate=True)
        real_ex, real_ch = trade_debate.ExecutionerAgent, trade_debate.ChampionAgent

        class Echo:
            def run(self, brief="", **kw):
                amount = re.search(r"risk at the stop ([\d,.]+)", brief).group(1)
                return real_ex.parse_response(None, json.dumps({
                    "verdict": "cut", "conviction": 0.6, "size_scale": 0.5,
                    "killer": f"one touch of the stop costs {amount} and the "
                              f"day cannot carry it", "reasons": []}))

        class Plain:
            def run(self, brief="", **kw):
                return real_ch.parse_response(None, json.dumps({
                    "verdict": "back", "conviction": 0.7,
                    "edge": "the lows were swept at 1948.5 and reclaimed (the "
                            "record could not be read: KeyError)",
                    "reasons": []}))

        with mock.patch.object(trade_debate, "ExecutionerAgent", Echo), \
                mock.patch.object(trade_debate, "ChampionAgent", Plain), \
                mock.patch("ai_agents.agents.council.open_debate_session",
                           return_value=None):
            debate = trade_debate.debate_candidate(_debate_bot(self.cfg),
                                                   _debate_cand(), 5.0)
        self.assertTrue(debate["ran"])
        self.assertIn("costs 250.00", debate["executioner"]["killer"])
        t = self._debated(debate)
        text, p, page = self._all(f"bot:{t.id}")
        said = p["seat"]["mission"]["debate"]["t"]
        self.assertEqual(said, (
            "Executioner: CUT: its words are withheld: they may name an amount "
            "of money · Champion: BACK: its words are withheld: they quote an "
            "error · shadow"))
        # The script binds each dot to the word before it (a no-break space).
        self.assertIn(said, page.replace(" ", " "))
        self._never(("one touch of the stop", "KeyError", "the lows were swept"),
                    text, page)

    ECHO = "one touch of the stop and {amount} is gone for the day"
    EDGE = "net reward:risk {rr} after costs; the sweep at 1948.5 was reclaimed"

    def test_a_bare_echo_is_withheld_when_the_fill_or_the_cut_moved_the_size(self):
        """A real row keeps the broker's fill, not the proposal the brief was
        priced at, and the cut's rounded size, not the size the brief was
        shown (review: "risk at the stop 250.00" echoed bare printed). The
        row's proposal, its cut and its size are read and the figure is
        matched by value. The Champion's own reward:risk is a ratio, not
        money, and prints."""
        debate = self._argued(self.ECHO, self.EDGE)
        self.assertIn("and 250.00 is gone", debate["executioner"]["killer"])
        rr = re.search(r"reward:risk ([\d.]+)", debate["champion"]["edge"]).group(1)
        rows = {
            "a favourable slip, nothing re-anchored": dict(
                entry="1990", meta={"slippage": {"proposal": 2000.0, "fill": 1990.0,
                                                 "points": -10.0, "r_fraction": -0.2}}),
            "a refused re-anchor": dict(
                entry="2010", meta={"slippage": {"proposal": 2000.0, "fill": 2010.0,
                                                 "points": 10.0, "r_fraction": 0.2},
                                    "stop_reanchor_refused": "refused"}),
            "a cut rounded to 1.6 at 0.33x": dict(
                qty="1.6", meta={"debate_cut": {"scale": 0.33, "qty": 1.6,
                                                "leverage": 1}}),
            "a whole-unit cut: 2 at 0.5x": dict(
                qty="2", meta={"debate_cut": {"scale": 0.5, "qty": 2.0,
                                              "leverage": 1}}),
            "a fill smaller than the size": dict(qty="4.9"),
        }
        for name, kw in rows.items():
            with self.subTest(name):
                cache.clear()
                t = self._debated(debate, **kw)
                text, p, page = self._all(f"bot:{t.id}")
                said = p["seat"]["mission"]["debate"]["t"]
                self.assertTrue(said.startswith(
                    "Executioner: CUT: its words are withheld: they may name an "
                    "amount of money · Champion: BACK: net reward:risk "
                    f"{rr} after costs; the sweep at 1948.5 was reclaimed · "), said)
                self._never(("is gone for the day",), text, page)

    def test_the_councils_record_gives_the_briefs_own_amount(self):
        """The council keeps the brief and the candidate it was priced on
        (ai_agents/agents/council.py open_debate_session): a row whose own
        levels no longer say the brief's amount (an older row: no proposal
        recorded, the stop since moved) still withholds the echo."""
        debate = self._argued(self.ECHO, self.EDGE, record=True)
        self.assertTrue(debate["council_id"])
        t = self._debated(debate, entry="1990", stop="1985",
                          meta={"initial_stop_loss": 1985.0})
        text, p, page = self._all(f"bot:{t.id}")
        said = p["seat"]["mission"]["debate"]["t"]
        self.assertTrue(said.startswith(
            "Executioner: CUT: its words are withheld: they may name an amount "
            "of money · Champion: BACK: net reward:risk"), said)
        self._never(("is gone for the day",), text, page)
        # The same row without the record: nothing of the row says 250.00.
        from dashboard import horde
        meta = {**t.metadata, "debate": {**t.metadata["debate"], "council_id": None}}
        self.assertIsNone(horde._debate_marks(t, meta).search("and 250.00 is gone"))

    # the venue's refusals: the care's mirror and the inert stamp

    def test_a_stop_move_the_venue_did_not_take_is_said_by_cause(self):
        from bot_program.asset_engine.base import make_bot
        from bot_program.position_care import care
        cfg = _cfg(self.user, cls="crypto", name="c", symbols=["BTCUSD"],
                   extras={"breakeven_at_r": 1.0})
        _instrument("BTCUSD", "crypto")
        t = _real(cfg, "BTCUSD", meta={"protected": True,
                                       "protective_trade_id": "P1", **_vm(102.2)})
        client = mock.MagicMock(spec=["modify_protective", "ticker"])
        client.modify_protective.side_effect = ConnectionError(EXC_TEXT)
        bot = make_bot(cfg)
        care(bot, t, 102.2, client)               # the mirror: one refusal
        for _ in range(2):                        # three in all: the stamp
            bot._move_broker_stop(t, 102.2, client, Decimal("100.2"),
                                  "care breakeven")
        t.refresh_from_db()
        self.assertIn("NewConnectionError", t.metadata["care"]["venue_stop_refusal"])
        self.assertIn("1,234.56", t.metadata["stop_rules_inert_detail"])
        text, p, page = self._all(f"bot:{t.id}")
        why = {w["code"]: w["t"] for w in _seat(p["board"], f"bot:{t.id}")["light"]["why"]}
        self.assertEqual(why["mirror_refused"],
                         "The care's stop did not reach eToro: the venue could not "
                         "be reached.")
        self.assertEqual(why["stop_rules_inert"],
                         "Stop moves keep failing at the broker: every recorded leg "
                         "handle was refused (the venue could not be reached).")
        self.assertEqual(p["seat"]["voice"]["care"]["refusal"],
                         "The care's stop did not reach eToro: the venue could not "
                         "be reached")
        self.assertIn("the venue could not be reached", page)
        self._never(EXC_FRAGS, text, page)

    # the thesis check's unread words

    def test_an_unread_thesis_says_which_read_failed_never_the_exception(self):
        from brain import thesis_check
        t = _real(self.cfg, "XAUUSD", meta=_vm(101))
        pos = {"symbol": "XAUUSD", "side": "BUY", "position_id": t.id}
        facts = {"mark": 101.0, "symbol": "XAUUSD", "side": "BUY",
                 "unrealized_r": 0.5, "mae_r": -0.2}
        boom = ValueError("bars unreadable: equity 1,234.56 USD")
        with mock.patch.object(thesis_check, "structure_read", side_effect=boom):
            th = thesis_check.thesis_check(pos, facts)
        self.assertIn("1,234.56", th["words"])
        self.assertTrue(thesis_check.write_on_row(t.id, th))
        text, p, page = self._all(f"bot:{t.id}")
        voice = p["seat"]["voice"]["thesis"]
        self.assertEqual((voice["word"], voice["words"]),
                         ("UNREAD", "Thesis unread: the structure could not be read."))
        line = [e["t"] for e in p["seat"]["timeline"] if e["author"] == "THESIS CHECK"]
        self.assertEqual(line, ["UNREAD: Thesis unread: the structure could not be read."])
        self.assertIn("Thesis unread: the structure could not be read.", page)
        self._never(("bars unreadable", "1,234.56", "ValueError", "structure unread:"),
                    text, page)

    # the reviewer's reasoning

    def test_the_reviewers_reasoning_never_carries_an_amount_or_an_exception_name(self):
        """What review_one stores (brain/position_review_agent.py: the
        model's reasoning_md, cut at 4000): an answer that may name an
        amount, or names an exception, is withheld whole."""
        from dashboard import horde
        t = _real(self.cfg, "XAUUSD", meta=_vm(101))
        _review(f"bot:{t.id}", verdict="tighten", user=self.user, model_used="m-1",
                reasoning_md="Risking 1,234.56 USD on a stale thesis is too much.\n"
                             "Tighten to 99.")
        text, p, page = self._all(f"bot:{t.id}")
        rv = p["seat"]["voice"]["reviewer"]
        self.assertEqual((rv["word"], rv["reasoning"], rv["reasoning_cut"]),
                         ("TIGHTEN", horde.REASONING_WITHHELD, None))
        self.assertIn(horde.REASONING_WITHHELD, page)
        self._never(("1,234.56", "Risking", "stale thesis"), text, page)
        g = _real(self.cfg, "XAGUSD", entry="30", stop="29", target="33", meta=_vm(31))
        _review(f"bot:{g.id}", verdict="hold", user=self.user, model_used="m-1",
                symbol="XAGUSD",
                reasoning_md="The structure holds; the positioning read failed "
                             "(KeyError: 'pools').\nHold.")
        cache.clear()
        text, p, page = self._all(f"bot:{g.id}")
        self.assertEqual(p["seat"]["voice"]["reviewer"]["reasoning"],
                         horde.REASONING_ERROR)
        self.assertIn(horde.REASONING_ERROR, page)
        self._never(("KeyError", "'pools'", "The structure holds"), text, page)

    def test_the_reviewer_never_repeats_a_failed_read_or_the_trades_own_amount(self):
        """The reviewer is shown the positioning read's failure text
        (brain/position_review.py _positioning: "positioning unread: <the
        exception's text>") and the trade's own qty and levels; reasoning
        that repeats the one, or names an amount worked from the other
        (matched by value), is withheld whole. Reasoning that quotes the
        exposure trigger in units and the stop loss level prints as
        written."""
        from brain import position_review
        from dashboard import horde
        t = _real(self.cfg, "XAUUSD", qty="5", entry="2000", stop="1950",
                  target="2150", meta=_vm(2010))
        with mock.patch("bot_program.positioning.positioning_map",
                        side_effect=ConnectionError(EXC_TEXT)):
            pos = position_review._positioning({"symbol": "XAUUSD"},
                                               {"symbol": "XAUUSD", "side": "BUY",
                                                "mark": 2010.0})
        self.assertIn("Max retries exceeded", pos["why"])
        facts = {"qty": 5.0, "entry": 2000.0, "initial_stop": 1950.0,
                 "stop": 1950.0, "target": 2150.0, "mark": 2010.0,
                 "positioning": pos}
        r = _review(f"bot:{t.id}", verdict="hold", user=self.user, model_used="m-1",
                    facts=facts, mark=Decimal("2010"), reasoning_md="x")
        cases = (
            ("The map is blind: Max retries exceeded on its read.\nHold.",
             horde.REASONING_ERROR, "Max retries"),
            ("Hold: the stop still caps this trade at 250.00, inside the plan.",
             horde.REASONING_WITHHELD, "caps this trade"),
            ("Hold: a stop-out now takes back 300 of the open move.",
             horde.REASONING_WITHHELD, "takes back"),
        )
        for reasoning, shown, frag in cases:
            with self.subTest(reasoning):
                type(r).objects.filter(pk=r.pk).update(reasoning_md=reasoning)
                cache.clear()
                text, p, page = self._all(f"bot:{t.id}")
                self.assertEqual(p["seat"]["voice"]["reviewer"]["reasoning"], shown)
                self._never((frag, "HTTPSConnectionPool", "1,234.56"), text, page)
        kept = ("The concentration trigger is real: net USD exposure +1.2 is at "
                "the gate.\nHold; the stop loss at 1950 already sits below the "
                "swept low, a reward:risk of 2.85 remains.")
        type(r).objects.filter(pk=r.pk).update(reasoning_md=kept)
        cache.clear()
        text, p, page = self._all(f"bot:{t.id}")
        self.assertEqual(p["seat"]["voice"]["reviewer"]["reasoning"], kept)

    # the gate that could not be read

    def test_limits_that_could_not_be_read_never_print_the_exception(self):
        from dashboard import horde
        _real(self.cfg, "XAUUSD", meta=_vm(101))
        boom = RuntimeError("ledger unreadable: equity 1,234.56 USD")
        with mock.patch("portfolio.risk_gate.daily_loss_state", side_effect=boom):
            board, tab = self.board(), self.tab()
        live = board["head"]["sides"]["live"]
        self.assertTrue(live["failed_open"])
        self.assertEqual((live["failed_t"], live["failed_reason"]),
                         (horde.FAILED_OPEN, horde.FAILED_REASON))
        page = _drive(BAND_DOM, {"board": board, "tab": tab, "seat": {}}) if NODE else ""
        if NODE:
            self.assertIn("THE BOOK LIMITS COULD NOT BE READ", page)
        self._never(("ledger unreadable", "1,234.56", "RuntimeError"),
                    json.dumps([board, tab]), page)


class ThePlainWordsTests(TestCase):
    """dashboard/plain_words.py over what the real producers write."""

    def test_every_debate_why_the_producers_write_is_said_in_words(self):
        from ai_agents.agents.trade_debate import debate_candidate
        from dashboard import plain_words as pw
        cfg = _cfg(_user("pw_u"))
        off = debate_candidate(_debate_bot(cfg), _debate_cand(), 5.0)
        self.assertEqual(off["why"], "trade_debate is OFF")
        # The demo branch's own words, read from the engine's source.
        demo = re.search(r'\{"why": "([^"]*demo world[^"]*)"\}',
                         _read("bot_program", "asset_engine", "base.py")).group(1)
        cases = {
            off["why"]: "Not argued: the debate's switch was off",
            demo: ("Not argued: the venue's demo world is a rehearsal and is "
                   "never argued"),
            ("refused at 2026-10-23T10:00: the Executioner vetoed it (0.80): "
             "risk at the stop 1,234.56"):
                "Not argued: an earlier binding refusal still held",
            "AI budget: daily AI budget spent ($5.03 of $5.00)":
                "Not argued: today's AI budget refused it",
            "debate unavailable (KeyError: 'price')":
                "Not argued: the debate failed before either side was asked",
            "executioner unavailable (BudgetRefused)":
                "Not argued in full: today's AI budget refused the Executioner",
            "champion unavailable (timeout)":
                "Not argued in full: the Champion did not answer in time",
            "something nobody wrote 1,234.56 (ValueError)": "Not argued in full",
            "": "",
        }
        for why, words in cases.items():
            self.assertEqual(pw.debate_why_words(why), words, why)

    def test_a_refusal_note_is_said_by_cause(self):
        from dashboard import plain_words as pw
        # The care's own sentence, read from its source (adjacent literals
        # joined): bot_program/position_care.py _mirror_to_venue.
        own = "not sent: the level is not on the right side of the mark"
        self.assertIn(own, re.sub(r'"\s*"', "", _read("bot_program", "position_care.py")))
        cases = {
            own: "not sent, the level is not on the right side of the mark",
            "P1: " + EXC_TEXT: "the venue could not be reached",
            "P1: ReadTimeout(read timed out)": "the venue did not answer in time",
            "P1: x; remaining handles not asked: the venue did not answer within "
            "the walk budget": "the venue did not answer in time",
            "P1: no leg matched; P2: no leg matched":
                "no order the row records was found at the venue",
            "eToro refused (400): stop too close; margin 1,234.56 USD":
                "the move failed; the venue's answer is kept in the log, not shown here",
            "refused": "the move failed; the venue's answer is kept in the log, "
                       "not shown here",
            "": "",
        }
        for note, words in cases.items():
            self.assertEqual(pw.venue_words(note), words, note)

    def test_a_voices_line_is_withheld_whole_when_it_may_name_an_amount(self):
        from dashboard import plain_words as pw
        marks = pw.money_marks([250.0])
        for line in ("risk at the stop 1,234.56", "a $500 cushion", "500 dollars",
                     "equity: 1234", "it costs 250.00", "it costs 250 to be wrong"):
            self.assertEqual(pw.scrub(line, marks=marks), pw.WITHHELD, line)
        for line in ("a loss of 1R is the plan", "drawdown 4% today",
                     "the stop at 1948.5 holds", "2.50R left to the target"):
            self.assertEqual(pw.scrub(line, marks=marks), line, line)
        self.assertEqual(pw.scrub("the read failed (KeyError: 'x') twice"),
                         pw.WITHHELD_ERROR)
        self.assertIsNone(pw.money_marks([None, 0, "x"]))

    def test_a_currency_with_a_sign_or_a_magnitude_is_money(self):
        """A sign or a k/m suffix between the currency and the figure, and
        the stablecoin codes (review: each of these passed unchanged)."""
        from dashboard import plain_words as pw
        for line in ("Risk at the stop USD -850.00 if it fails", "P&L: $-412.50 now",
                     "1.2k USD at risk", "about 12k USD", "1250 USDC",
                     "US$1,250 on it", "EUR +85.20 since the open", "a 3m GBP book"):
            self.assertEqual(pw.scrub(line), pw.WITHHELD, line)

    def test_a_money_word_or_verb_with_fillers_or_a_trailing_ratio_is_money(self):
        """The R and percent exemption ends with the figure's own digits
        ("850.00, R:R 1.8" is money); a run of fillers may stand between
        the word and the figure; the verbs a voice uses for an amount; a
        figure before "at risk". Below 1,000 and ungrouped, so only these
        patterns catch them."""
        from dashboard import plain_words as pw
        for line in ("risk at the stop 850.00, R:R 1.8", "risk at the stop 850.00 R:R 1.8",
                     "a loss of about 850.00", "risk ≈ 850.00", "risk of roughly 1,250",
                     "a stop-out costs 850.00", "would lose 1250.00 on the stop",
                     "gives back 412.50 of open profit", "it lost 120 on the gap",
                     "850.00 at risk on a thin edge", "1250 on the line"):
            self.assertEqual(pw.scrub(line), pw.WITHHELD, line)

    def test_ratios_levels_counts_and_names_are_kept_as_written(self):
        """The ratio and the level that share a money word, a count after a
        verb, a theme's exposure in units, and a CamelCase name that is
        not an exception: the voice's line shows as it wrote it."""
        from dashboard import plain_words as pw
        for line in ("net reward:risk 2.85 after costs", "reward-to-risk of 2.85",
                     "the stop loss at 1950 sits under a swept low",
                     "stop-loss at 1950 is inside the ATR",
                     "take profit at 2150 is 7.5% away",
                     "net USD exposure +1.2 is at the gate level",
                     "the rule lost 3 of its last 5 trades", "risk 2 ATR away",
                     "the signal came from: TradingView",
                     "Edge: PowerOfThree sweep (GoldenCross)",
                     "catalyst: PayPal earnings tonight",
                     "flows: BlackRock bought the ETF two days running",
                     "the big holder (MicroStrategy) has not sold",
                     "an exception to the rule: the trend is up"):
            self.assertEqual(pw.scrub(line), line, line)
        many = ("The concentration trigger is real: net USD exposure +1.2 is at "
                "the gate.\nHold; the stop loss at 2318.4 already sits below the "
                "swept low.")
        self.assertEqual(pw.scrub(many, 6000, keep_lines=True), many)

    def test_a_line_that_names_an_exception_is_withheld_whole(self):
        """Keyed on the class name's suffix: acronym-led, dotted and
        nested-bracket names, and a name after a colon with its message
        (review: each passed, or kept its message)."""
        from dashboard import plain_words as pw
        for line in ("the rule's record could not be read (OSError), so no edge is proven",
                     "positioning unread: OSError: [Errno 111] Connection refused",
                     "debate unavailable (HTTPError: 500 Server Error)",
                     "(OperationalError: could not connect (timeout))",
                     "read failed (requests.exceptions.ConnectionError: "
                     "HTTPSConnectionPool(host='x', port=443))",
                     "thesis check failed: KeyError: 'level'",
                     "posture unreadable: JSONDecodeError", "EOFError at the read",
                     "socket.timeout: timed out", "the read: Exception"):
            self.assertEqual(pw.scrub(line), pw.WITHHELD_ERROR, line)
        failures = pw.failure_texts(
            'positioning unread: connection to server at "db" (172.18.0.3), '
            'port 5432 failed: FATAL: too many connections', "no usable mark")
        self.assertEqual(len(failures), 1)
        self.assertEqual(pw.scrub("Hold: port 5432 failed: FATAL: too many "
                                  "connections, so the map is blind.",
                                  failures=failures), pw.WITHHELD_ERROR)
        self.assertEqual(pw.scrub("Hold: the map is blind.", failures=failures),
                         "Hold: the map is blind.")

    def test_the_marks_match_by_value_not_by_spelling(self):
        """A fill or a rounded cut moves the brief's amount a little: every
        figure in the line is read and matched within the tolerance; a
        short whole figure, and a figure in R or percent, never count."""
        from dashboard import plain_words as pw
        marks = pw.money_marks([849.0])
        for line in ("and 850.00 goes with it", "850 is gone", "a touch takes 849.5",
                     "-850.00 at the stop"):
            self.assertTrue(marks.search(line), line)
        for line in ("the sweep at 1948.5", "850R is not a plan", "a 850% move",
                     "3 of 5", "the stop at 15.00"):
            self.assertFalse(marks.search(line), line)
        small = pw.money_marks([2.5])
        self.assertTrue(small.search("2.50 goes with it"))
        self.assertFalse(small.search("2 sweeps, 3 breaks"))


@override_settings(CACHES=LOCMEM)
class TheShortReadBackTests(_Base):
    """THE SHORT READ-BACK (2026-10-31, bot_program/short_readback.py): a
    hand-taken short on a class nobody has measured at eToro is read back
    from eToro at the fill. A read that found something else flags the
    row (metadata["short_readback"] ok False): the seat's light says it as
    an ALARM, and the care's box in the dossier says it too."""

    FLAG = {"ok": False, "state": "mismatch",
            "facts": ["eToro holds it as a long, not a short"]}

    def _short(self, flag):
        _quote("BTCUSD", 60000, cls="crypto")
        cfg = _manual(self.user, cls="crypto")
        return _real(cfg, "BTCUSD", side="SELL", entry="60000",
                     stop="60900", target="58200", rule="manual_take",
                     meta={"manual": True, "short_readback": flag})

    def test_the_light_table_entry(self):
        from dashboard.horde import light
        facts = TheTruthTests._calm(None, short_readback=self.FLAG)
        got = light(facts)
        (why,) = [w for w in got["why"] if w["code"] == "short_readback"]
        self.assertEqual(got["tone"], "alarm")
        self.assertEqual(why["t"], "Read back from eToro after the fill: "
                                   "eToro holds it as a long, not a short.")
        clean = {"ok": True, "state": "clean", "facts": []}
        self.assertNotIn("short_readback",
                         [w["code"] for w in light(TheTruthTests._calm(
                             None, short_readback=clean))["why"]])

    def test_the_seat_and_the_care_say_it(self):
        t = self._short(self.FLAG)
        seat = _seat(self.board(), f"bot:{t.id}")
        self.assertIn("short_readback", [w["code"] for w in seat["light"]["why"]])
        self.assertEqual(seat["light"]["tone"], "alarm")
        care = self.seat(f"bot:{t.id}")["voice"]["care"]
        self.assertEqual(care["readback"],
                         "Read back from eToro after the fill: eToro holds "
                         "it as a long, not a short.")

    def test_a_clean_read_back_says_nothing(self):
        t = self._short({"ok": True, "state": "clean", "facts": []})
        seat = _seat(self.board(), f"bot:{t.id}")
        self.assertNotIn("short_readback",
                         [w["code"] for w in seat["light"]["why"]])
        self.assertIsNone(self.seat(f"bot:{t.id}")["voice"]["care"]["readback"])

    def test_the_script_paints_it_in_the_care_box(self):
        src = _read("static", "js", "sv-horde.js")
        self.assertIn("c.readback", src)
