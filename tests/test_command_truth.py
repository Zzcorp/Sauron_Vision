"""THE OPERATIONS CENTER, OC0: truth and cost in today's look (2026-11-07).

/command/ is the operator's home. Its map found it adding REAL, DEMO and
PAPER money together, printing a DEMO row as REAL MONEY, counting bots on
a DEMO account as armed with real funds, calling the average win over the
average loss a profit factor, printing money with no currency and quantities
with eight decimals, leaving most of its dashes unexplained, holding the
session open with its own poll, and paying for the shell on every tab. OC0
fixes what is false or wasteful, in today's styles (the Operations Center
spec, section 8, OC0; sections 5, 6 and 7 bind it).

What is pinned here, on synthetic rows only (EURUSD, AAPL, BTCUSD, round
amounts):
  - worlds: the DEMO row reads DEMO; no money cell anywhere on the page or
    its fragments prints a sum or an average across worlds; the averages,
    the profit factor and the P&L by class are per world; the hero's three
    lines equal the band's own split; ACT splits real and demo; the armed
    pill counts bots on a REAL account only, and a config whose route
    cannot be read stays in it;
  - money paths: live_book_value and what store_book_value writes are the
    same before and after the page is read; the home holds no bot form for
    anyone (proposal P1, 2026-11-12), and the bots page keeps both, with
    their CSRF token and their PIN field;
  - words, numbers, windows, ages and dashes;
  - the bots tab: the world from the account, health from the heartbeat;
  - cost: query budgets cold, fragments without the shell, database
    aggregates equal to the loops they replace;
  - no broker or model call to draw the page;
  - the page's own poll, under node (tests/js/command_metrics.test.js),
    and what the server makes of it (no session stamp, 423 when locked).

Display only: nothing here places, closes or changes an order.

Run with:  python manage.py test tests.test_command_truth
"""
import copy
import json
import re
import shutil
import subprocess
import sys
import time
from datetime import timedelta
from decimal import Decimal
from html.parser import HTMLParser
from pathlib import Path
from unittest import mock, skipIf

from django.conf import settings
from django.contrib.auth.models import User
from django.core.cache import cache
from django.db import connection
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

DASH = "—"
BASE = Path(settings.BASE_DIR)
FRAGMENTS = ("/command/tab/live/", "/command/tab/portfolio/",
             "/command/tab/history/", "/command/tab/bots/")
NODE = shutil.which("node")


# ── fixtures: synthetic rows only ────────────────────────────────────────

def _user(name, *, staff=True, superuser=False):
    return User.objects.create_user(name, password="x", is_staff=staff,
                                    is_superuser=superuser)


def _instrument(symbol, cls, currency="USD"):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": cls,
                                 "currency": currency})
    return inst


def _quote(symbol, last, cls, *, age_s=30):
    from market_data.models import LiveQuote
    inst = _instrument(symbol, cls)
    LiveQuote.objects.update_or_create(
        instrument=inst, defaults={"last": Decimal(str(last)),
                                   "source": "test"})
    LiveQuote.objects.filter(instrument=inst).update(
        updated_at=timezone.now() - timedelta(seconds=age_s))


def _config(user, name, cls, *, mode="paper", enabled=True, symbols=None,
            extras=None):
    from bot_program.models import AssetBotConfig
    return AssetBotConfig.objects.create(
        user=user, asset_class=cls, name=name, mode=mode, enabled=enabled,
        symbols=list(symbols or []), capital=Decimal("10000"),
        base_currency="USD", extras=extras or {})


#: The stamps a row of each world carries (dashboard.position_summary
#: .world_of reads them): REAL and DEMO are eToro rows, paper=False; DEMO
#: is the eToro demo world (broker_env "paper"); PAPER is the simulator.
STAMPS = {
    "live": (False, {"broker": "etoro", "broker_env": "live",
                     "value_per_unit": 1}),
    "demo": (False, {"broker": "etoro", "broker_env": "paper",
                     "value_per_unit": 1}),
    "paper": (True, {"broker": "paper"}),
}


def _trade(cfg, symbol, qty, entry, *, world, status="OPEN", side="BUY",
           pnl=None, r=None, opened_ago_s=600, closed_ago_s=None,
           rule="oc_rule"):
    from bot_program.models import AssetBotTrade
    paper, meta = STAMPS[world]
    t = AssetBotTrade.objects.create(
        config=cfg, asset_class=cfg.asset_class, symbol=symbol, side=side,
        qty=Decimal(str(qty)), entry_price=Decimal(str(entry)),
        status=status, paper=paper, metadata=dict(meta), rule_name=rule,
        pnl=None if pnl is None else Decimal(str(pnl)), realized_r=r)
    upd = {"opened_at": timezone.now() - timedelta(seconds=opened_ago_s)}
    if closed_ago_s is not None:
        upd["closed_at"] = timezone.now() - timedelta(seconds=closed_ago_s)
    AssetBotTrade.objects.filter(pk=t.pk).update(**upd)
    t.refresh_from_db()
    return t


def _etoro(user, *, demo=False, forex=False, stocks=True, equity="10000.00"):
    from bot_program.models import EtoroAccount
    acct = EtoroAccount.objects.create(
        user=user, demo=demo, label="Main", is_primary_for_stocks=stocks,
        is_primary_for_forex=forex)
    acct.set_credentials("k", "u")
    at = timezone.now() - timedelta(seconds=40)
    acct.last_used_margin = Decimal("600.00")
    acct.last_available_cash = Decimal("9000.00")
    acct.last_pnl = Decimal("12.00")
    acct.last_frozen_cash = Decimal("0.00")
    acct.last_balance = Decimal("9988.00")
    acct.last_margin_at = at
    acct.last_margin_world = "demo" if demo else "live"
    acct.last_equity = Decimal(equity)
    acct.last_equity_currency = "USD"
    acct.last_equity_at = at
    acct.save()
    return acct


def _portfolio(user, cash="10000"):
    from portfolio.services import get_or_create_default_portfolio
    pf = get_or_create_default_portfolio(user=user)
    pf.cash_available = Decimal(cash)
    pf.save()
    return pf


#: The three worlds' open P&L and realized P&L on the fixture below:
#: REAL +10.00, DEMO +1.00, PAPER +100.00, open and closed.
REAL_PNL, DEMO_PNL, PAPER_PNL = 10.0, 1.0, 100.0

#: Any sum or average of two or three of them is a number this page must
#: never print as money (the spec's own list).
SUMS = ("11.00", "101.00", "110.00", "111.00")
AVERAGES = ("5.50", "50.50", "55.00", "37.00")


def _three_worlds(user, *, with_etoro=True):
    """One REAL (+10.00), one DEMO (+1.00) and one PAPER (+100.00) row,
    open and closed in the last hour; a portfolio with 10,000 typed cash;
    an eToro REAL account read 40 s ago."""
    _portfolio(user)
    if with_etoro:
        _etoro(user)
    _quote("AAPL", "210", "stock")
    _quote("EURUSD", "1.09412", "forex")
    _quote("BTCUSD", "20100", "crypto")
    real = _config(user, "oc real", "stock", mode="live", symbols=["AAPL"])
    demo = _config(user, "oc demo", "forex", mode="paper", symbols=["EURUSD"])
    paper = _config(user, "oc paper", "crypto", symbols=["BTCUSD"])
    rows = {
        "live": _trade(real, "AAPL", 1, 200, world="live"),
        "demo": _trade(demo, "EURUSD", 100, "1.08412", world="demo"),
        "paper": _trade(paper, "BTCUSD", 1, 20000, world="paper"),
    }
    _trade(real, "AAPL", 1, 200, world="live", status="CLOSED",
           pnl=REAL_PNL, r=1.0, closed_ago_s=900)
    _trade(demo, "EURUSD", 100, "1.08412", world="demo", status="CLOSED",
           pnl=DEMO_PNL, r=0.5, closed_ago_s=1200)
    _trade(paper, "BTCUSD", 1, 20000, world="paper", status="CLOSED",
           pnl=PAPER_PNL, r=2.0, closed_ago_s=1500)
    return rows


def _page_part(body):
    """The page's own content: from the hero to the end of the content
    block — never the shell around it (the band, the rail, the Horde),
    which S1b owns."""
    start = body.index('<div class="oc-hero"')
    end = body.index("</main>", start)
    return body[start:end]


def _texts(html):
    """Visible text, scripts, styles and SVG drawings left out."""
    parser = _Walker()
    parser.feed(html)
    return parser.texts


class _Walker(HTMLParser):
    """Text nodes with their parent element's attributes; elements by
    attribute; nothing inside script, style or svg."""

    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input",
            "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.texts = []          # [(text, parent attrs dict, parent tag)]
        self.elements = []       # [(tag, attrs dict, [text...])]
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.VOID:
            self.elements.append((tag, dict(attrs), []))
            return
        if tag in ("script", "style", "svg"):
            self._skip += 1
        el = (tag, dict(attrs), [])
        self.elements.append(el)
        self.stack.append(el)

    def handle_startendtag(self, tag, attrs):
        self.elements.append((tag, dict(attrs), []))

    def handle_endtag(self, tag):
        if tag in self.VOID:
            return
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                if tag in ("script", "style", "svg"):
                    self._skip = max(0, self._skip - 1)
                del self.stack[i:]
                break

    def handle_data(self, data):
        if self._skip or not data.strip():
            return
        parent = self.stack[-1] if self.stack else ("", {}, [])
        self.texts.append((data, parent[1], parent[0]))
        for el in self.stack:
            el[2].append(data)


def _walk(html):
    w = _Walker()
    w.feed(html)
    return w


def _money_hits(text, numbers):
    """Each of `numbers` printed as a figure in `text` (not inside a larger
    number: 111.00 is not 11.00)."""
    hits = []
    for num in numbers:
        pat = r"(?<![\d.,])" + re.escape(num) + r"(?![\d])"
        if re.search(pat, text):
            hits.append(num)
    return hits


def _json_strings(value):
    if isinstance(value, dict):
        for v in value.values():
            yield from _json_strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _json_strings(v)
    elif isinstance(value, str):
        yield value


# ── 1. Worlds ────────────────────────────────────────────────────────────

class WorldsTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = _user("oc_worlds")
        self.client.force_login(self.user)
        self.rows = _three_worlds(self.user)

    def test_a_demo_row_reads_demo_and_a_real_row_reads_real(self):
        body = self.client.get("/command/tab/live/").content.decode()
        rows = re.findall(r"<tr data-sv-position-row.*?</tr>", body, re.S)
        demo = [r for r in rows if ">EURUSD<" in r]
        real = [r for r in rows if ">AAPL<" in r]
        self.assertEqual(len(demo), 1, rows)
        self.assertEqual(len(real), 1, rows)
        self.assertIn("sv-world--demo", demo[0])
        self.assertNotIn("sv-world--live", demo[0])
        self.assertIn("sv-world--live", real[0])

    def test_no_money_cell_prints_a_sum_or_an_average_across_worlds(self):
        notional = {"live": 210.0, "demo": 109.412, "paper": 20100.0}
        sums = set(SUMS) | set(AVERAGES)
        for a, b in (("live", "demo"), ("live", "paper"), ("demo", "paper")):
            sums.add(f"{notional[a] + notional[b]:,.2f}")
        sums.add(f"{sum(notional.values()):,.2f}")
        # floatformat:0 printed the deployed sum with no separator
        sums.add(f"{round(sum(notional.values()))}")
        sums.add(f"{round(sum(notional.values())):,}")
        seen = {"page": " ".join(t for t, _a, _g in _texts(
            _page_part(self.client.get("/command/").content.decode())))}
        for path in FRAGMENTS:
            seen[path] = " ".join(t for t, _a, _g in _texts(
                self.client.get(path).content.decode()))
        payload = self.client.get("/command/tab/metrics/").json()
        seen["metrics"] = " ".join(_json_strings(payload))
        for where, text in seen.items():
            self.assertEqual(_money_hits(text, sorted(sums)), [], where)

    def test_averages_profit_factor_and_class_pnl_are_per_world(self):
        r = self.client.get("/command/tab/portfolio/")
        stats = r.context["stats_by_world"]
        self.assertEqual(stats["live"]["avg_win"], REAL_PNL)
        self.assertEqual(stats["demo"]["avg_win"], DEMO_PNL)
        self.assertEqual(stats["paper"]["avg_win"], PAPER_PNL)
        for world in ("live", "demo", "paper"):
            self.assertIsNone(stats[world]["avg_loss"], world)
            self.assertIsNone(stats[world]["profit_factor"], world)
        live = self.client.get("/command/tab/live/")
        rows = live.context["pnl_24h"]["by_world_class"]
        got = {(row["world"], row["asset_class"]): row["pnl"] for row in rows}
        self.assertEqual(got, {("live", "stock"): REAL_PNL,
                               ("demo", "forex"): DEMO_PNL,
                               ("paper", "crypto"): PAPER_PNL})
        self.assertNotIn("pnl-pct", live.content.decode().split(
            "P&amp;L by asset class")[1].split("Rule control")[0])

    def test_the_heros_three_lines_equal_the_bands_split(self):
        from core.context_processors import _panel_detail
        from dashboard.views_command import _hero_metrics
        cache.clear()
        band = _panel_detail(self.user)
        hero = _hero_metrics(self.user)
        self.assertEqual(hero["worlds"]["live"]["pnl"],
                         band["panel_open_pnl_live"])
        self.assertEqual(hero["worlds"]["demo"]["pnl"],
                         band["panel_open_pnl_demo"])
        self.assertEqual(hero["worlds"]["paper"]["pnl"],
                         band["panel_open_pnl_paper"])
        self.assertEqual(hero["worlds"]["live"]["pnl"], REAL_PNL)
        body = _page_part(self.client.get("/command/").content.decode())
        for key in ("world_live", "world_demo", "world_paper"):
            self.assertIn(f'data-oc-hero="{key}"', body)
        self.assertIn("never added", body)

    def test_act_splits_real_and_demo(self):
        from dashboard.views_day import day_live_payload
        act = {w: n for n, w in
               day_live_payload(self.user)["stages"]["act"]["metrics"]}
        self.assertEqual(act["open now, real money"], 1)
        self.assertEqual(act["open now, demo"], 1)
        self.assertEqual(act["open now, paper"], 1)
        self.assertNotIn("open now, live money", act)

    def test_the_tab_heads_lead_with_real_and_keep_a_count_beside_it(self):
        from dashboard.views_command import _tab_bar_metrics
        tabs = _tab_bar_metrics(self.user)
        self.assertEqual(tabs["live"]["primary"], "1 REAL OPEN")
        self.assertIn("10.00 USD", tabs["live"]["secondary"])
        self.assertIn("3 open, all worlds", tabs["live"]["title"])
        self.assertEqual(tabs["live"]["n_open"], 3)
        self.assertIn("REAL", tabs["bots"]["secondary"])
        self.assertIn("10.00 USD", tabs["bots"]["secondary"])


class ThePillTests(TestCase):
    """The topbar's red pill is the one REAL marker: it counts bots armed
    on a REAL account. A config's world is the world of the account its
    symbols route to; one whose route cannot be read stays in the count,
    so the pill never under-counts real money (spec §6.3, 3)."""

    def _truth(self, user):
        from core.context_processors import _bot_truth
        return _bot_truth(User.objects.get(pk=user.pk), {})["panel_bot"]

    def _live_fx(self, user):
        _instrument("EURUSD", "forex")
        return _config(user, "fx live", "forex", mode="live",
                       symbols=["EURUSD"])

    def test_a_live_mode_config_routed_to_a_demo_account_is_not_counted(self):
        user = _user("oc_pill_demo")
        _etoro(user, demo=True, forex=True)
        self._live_fx(user)
        bot = self._truth(user)
        self.assertEqual(bot["live"], 0)
        self.assertEqual(bot["live_demo"], 1)
        self.assertIn("1 on a DEMO account", bot["reason"])

    def test_one_on_a_real_account_is_counted(self):
        user = _user("oc_pill_real")
        _etoro(user, demo=False, forex=True)
        self._live_fx(user)
        bot = self._truth(user)
        self.assertEqual(bot["live"], 1)
        self.assertEqual(bot["live_demo"], 0)

    def test_one_whose_route_cannot_be_read_is_counted(self):
        user = _user("oc_pill_unread")
        _etoro(user, demo=True, forex=True)
        self._live_fx(user)
        with mock.patch(
                "bot_program.engine.broker_router.broker_name_for_symbol",
                side_effect=RuntimeError("router unreadable")):
            bot = self._truth(user)
        self.assertEqual(bot["live"], 1)
        self.assertEqual(bot["live_demo"], 0)

    def test_the_pill_prints_the_real_account_count(self):
        user = _user("oc_pill_page")
        _etoro(user, demo=True, forex=True)
        self._live_fx(user)
        self.client.force_login(user)
        body = self.client.get("/command/").content.decode()
        self.assertNotIn("sv-armed-pill", body)


# ── 2. Money paths ───────────────────────────────────────────────────────

class MoneyPathsTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = _user("oc_money", superuser=True)
        self.client.force_login(self.user)
        _three_worlds(self.user)

    def test_the_book_value_and_its_stored_copy_are_unchanged(self):
        """live_book_value is not edited; the page only reads it. Cash
        10,000 + the REAL and DEMO notional (210.00 + 109.41) + paper's open
        and realized P&L (100.00 + 100.00), on the fixture."""
        from portfolio.services import (get_or_create_default_portfolio,
                                        live_book_value)
        from portfolio.tasks import store_book_value
        before = live_book_value(self.user).value
        self.assertEqual(before, 10519.41)
        pf = get_or_create_default_portfolio(user=self.user)
        stored = pf.current_value
        for path in ("/command/", "/command/tab/metrics/") + FRAGMENTS:
            self.assertEqual(self.client.get(path).status_code, 200, path)
        self.assertEqual(live_book_value(self.user).value, before)
        pf.refresh_from_db()
        self.assertEqual(pf.current_value, stored)
        self.assertTrue(store_book_value(pf, live_book_value(self.user)))
        pf.refresh_from_db()
        self.assertEqual(pf.current_value, Decimal("10519.41"))

    # ── the bots' Toggle and Tick (proposal P1) ──────────────────────────
    #
    # Updated deliberately 2026-11-12. OC0 pinned here that a superuser's
    # BOTS tab on the home drew the Toggle form with its CSRF token
    # (test_a_superusers_toggle_form_passes_csrf). The operator approved
    # proposal P1 on 2026-11-07: the two forms leave the home for everyone
    # ("Toggle" does not say on or off, and "▶ Tick" starts a bot pass from
    # the home with no PIN and no confirmation) and stay on the bots page.
    # The meaning is kept and moved with the forms: the home holds neither
    # form for any user, the bots page holds both, and the Toggle form as
    # the bots page renders it still passes CSRF. The endpoints, their PIN
    # and their words are not edited.

    BOT_ENDPOINTS = ("/admin-dashboard/asset-bots/toggle/",
                     "/admin-dashboard/asset-bots/tick/")

    def _bot_forms(self, html):
        """[(action, the form's html)] for every form that posts to the
        Toggle or the Tick endpoint."""
        return [(m.group(1), m.group(0)) for m in re.finditer(
            r'<form\b[^>]*\baction="([^"]*)"[^>]*>.*?</form>', html, re.S)
            if m.group(1) in self.BOT_ENDPOINTS]

    def test_the_home_holds_no_bot_form_for_any_user(self):
        from bot_program.models import AssetBotConfig
        # A disabled live-mode config: the row whose Toggle form carried
        # the PIN field.
        _config(self.user, "oc live off", "stock", mode="live",
                enabled=False, symbols=["AAPL"])
        staff = _user("oc_money_staff", staff=True)
        viewer = _user("oc_money_viewer2", staff=False)
        for user in (staff, viewer):
            _config(user, f"{user.username} bot", "crypto")
        for user in (self.user, staff, viewer):
            self.client.force_login(user)
            names = list(AssetBotConfig.objects.filter(user=user)
                         .values_list("name", flat=True))
            self.assertTrue(names, user.username)
            for path in ("/command/tab/bots/", "/command/?tab=bots"):
                body = self.client.get(path).content.decode()
                where = f"{user.username} {path}"
                if path.startswith("/command/tab/"):
                    for name in names:
                        self.assertIn(name, body, where)
                    # The fragment holds no form at all, so no token and
                    # no PIN field either.
                    self.assertNotIn("<form", body, where)
                    self.assertNotIn("csrfmiddlewaretoken", body, where)
                    self.assertNotIn('name="pin"', body, where)
                    self.assertNotIn("▶ Tick", body, where)
                    self.assertNotIn(">Toggle<", body, where)
                else:
                    body = _page_part(body)
                self.assertEqual(self._bot_forms(body), [], where)
                for action in self.BOT_ENDPOINTS:
                    self.assertNotIn(action, body, where)

    def test_a_superuser_gets_one_link_to_the_bots_page_instead(self):
        """In the forms' place, for the users the endpoints accept: one
        plain link to the bots page, where both remain. Nobody else is
        told of controls the endpoint would refuse them."""
        staff = _user("oc_money_staff2", staff=True)
        _config(staff, "staff bot", "crypto")
        link = re.compile(r'<p\b[^>]*data-oc-bot-controls[^>]*>(.*?)</p>',
                          re.S)
        body = self.client.get("/command/tab/bots/").content.decode()
        found = link.findall(body)
        self.assertEqual(len(found), 1, found)
        anchors = re.findall(r'<a\b[^>]*href="([^"]*)"[^>]*>(.*?)</a>',
                             found[0], re.S)
        self.assertEqual([(href, " ".join(text.split()))
                          for href, text in anchors],
                         [("/asset-bots/", "Bots page ›")])
        words = " ".join(t for t, _a, _g in _texts(found[0]))
        self.assertIn("on or off", words)
        self.assertIn("tick", words.lower())
        self.assertNotIn("System map", words)
        self.client.force_login(staff)
        body = self.client.get("/command/tab/bots/").content.decode()
        self.assertIn("staff bot", body)
        self.assertEqual(link.findall(body), [])

    def test_a_hand_taken_lane_is_said_not_to_be_on_the_bots_page(self):
        """This tab lists every config, the TAKE TRADE lane ("manual", no
        symbols) among them; the bots page lists the fleet without it
        (views_asset_bots). The home's Toggle was the one page form for
        that row: the line that replaces it says where its switch is, so a
        superuser is not sent to a page that does not hold it."""
        from bot_program.manual_trade import manual_config_for
        lane = manual_config_for(self.user, "forex")
        self.assertEqual((lane.name, lane.symbols), ("manual", []))
        body = self.client.get("/command/tab/bots/").content.decode()
        found = re.findall(r'<p\b[^>]*data-oc-bot-controls[^>]*>(.*?)</p>',
                           body, re.S)
        self.assertEqual(len(found), 1, found)
        # Still one link, to the bots page; the System map is named.
        self.assertEqual(re.findall(r'<a\b[^>]*href="([^"]*)"', found[0]),
                         ["/asset-bots/"])
        words = " ".join(t for t, _a, _g in _texts(found[0]))
        self.assertIn("hand-taken lane", words)
        self.assertIn("System map", words)
        # The bots page, as it always was, lists no row for the lane.
        page = self.client.get("/asset-bots/").content.decode()
        self.assertFalse([f for _a, f in self._bot_forms(page)
                          if f'name="config_id" value="{lane.id}"' in f])

    def test_the_bots_page_keeps_both_forms_and_they_post_as_before(self):
        from bot_program.models import AssetBotConfig
        _instrument("AAPL", "stock")
        off = _config(self.user, "oc live off", "stock", mode="live",
                      enabled=False, symbols=["AAPL"])
        paper = AssetBotConfig.objects.get(user=self.user, name="oc paper")
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        r = client.get("/asset-bots/")
        self.assertEqual(r.status_code, 200)
        forms = self._bot_forms(r.content.decode())
        toggle_url, tick_url = self.BOT_ENDPOINTS

        def form_for(action, cfg):
            hits = [f for a, f in forms if a == action
                    and f'name="config_id" value="{cfg.id}"' in f]
            self.assertEqual(len(hits), 1, (action, cfg.name))
            self.assertIn('method="post"', hits[0])
            token = re.search(
                r'name="csrfmiddlewaretoken" value="([^"]+)"', hits[0])
            self.assertIsNotNone(token, (action, cfg.name))
            return hits[0], token.group(1)

        # Both forms for every bot row, the PIN field where it always was:
        # on the Toggle of a live-mode bot that is off (arming it).
        for cfg in (paper, off):
            toggle, _tok = form_for(toggle_url, cfg)
            tick, _tok = form_for(tick_url, cfg)
            self.assertIn(">Toggle</button>", toggle)
            self.assertIn(">▶ Tick</button>", tick)
            self.assertNotIn('name="pin"', tick)
        self.assertIn('type="password" name="pin"', form_for(toggle_url, off)[0])
        self.assertNotIn('name="pin"', form_for(toggle_url, paper)[0])

        # The Toggle form as rendered, posted as a browser would: its own
        # token against the cookie the page's response set.
        _form, token = form_for(toggle_url, paper)
        r = client.post(toggle_url, {"csrfmiddlewaretoken": token,
                                     "config_id": paper.id})
        self.assertNotEqual(r.status_code, 403, r.content[:300])
        paper.refresh_from_db()
        self.assertFalse(paper.enabled)
        # Arming a live-mode bot still asks for the PIN: with none, it
        # stays off.
        r = client.post(toggle_url, {"csrfmiddlewaretoken": token,
                                     "config_id": off.id})
        self.assertNotEqual(r.status_code, 403, r.content[:300])
        off.refresh_from_db()
        self.assertFalse(off.enabled)
        # The Tick form reaches the runner, as before (the runner itself is
        # not run here).
        _form, token = form_for(tick_url, paper)
        with mock.patch("bot_program.asset_engine.runner.run_asset_bot_tick",
                        return_value={"status": "skipped",
                                      "reason": "test"}) as tick:
            r = client.post(tick_url, {"csrfmiddlewaretoken": token,
                                       "config_id": paper.id})
        self.assertNotEqual(r.status_code, 403, r.content[:300])
        tick.assert_called_once_with(paper.id)

    def test_a_user_the_endpoint_refuses_gets_no_bot_form(self):
        viewer = _user("oc_money_viewer", staff=True, superuser=False)
        _config(viewer, "viewer bot", "crypto")
        self.client.force_login(viewer)
        body = self.client.get("/command/tab/bots/").content.decode()
        self.assertIn("viewer bot", body)
        self.assertNotIn('action="/admin-dashboard/asset-bots/', body)
        self.assertNotIn("▶ Tick", body)
        # And the endpoints refuse that user, as they always did.
        for url in self.BOT_ENDPOINTS:
            self.assertEqual(self.client.post(url, {"config_id": 1}).status_code,
                             403, url)


# ── 3. Words ─────────────────────────────────────────────────────────────

class WordsTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = _user("oc_words")
        self.client.force_login(self.user)

    def test_the_platform_book_carries_its_words_and_no_currency_sign(self):
        _three_worlds(self.user)
        part = _page_part(self.client.get("/command/").content.decode())
        self.assertIn("PLATFORM BOOK", part)
        self.assertIn("10,519.41", part)
        self.assertNotRegex(part, r"[€$£]\s?10,519\.41")
        self.assertIn("(EUR + USD, not converted)", part)
        for words in ("cash typed on /setup/", "not a balance",
                      "hand-recorded rows too", "not converted"):
            self.assertIn(words, part)
        self.assertIn("bk-card", part)

    def test_the_profit_factor_is_gross_wins_over_gross_losses(self):
        _portfolio(self.user)
        cfg = _config(self.user, "oc pf", "stock", mode="live")
        for i, pnl in enumerate((30, 10, -10, -5, -5)):
            _trade(cfg, "AAPL", 1, 200, world="live", status="CLOSED",
                   pnl=pnl, r=pnl / 10, closed_ago_s=3600 * (i + 1))
        r = self.client.get("/command/tab/portfolio/")
        real = r.context["stats_by_world"]["live"]
        self.assertEqual(real["profit_factor"], 2.0)   # 40 / 20
        self.assertEqual(real["payoff"], 3.0)          # 20 / 6.67
        self.assertEqual(r.context["profit_factor"], 2.0)
        body = r.content.decode()
        self.assertIn("payoff", body)
        self.assertIn("gross wins over gross losses", body)

    def test_the_24h_dash_names_the_2330_snapshot(self):
        from dashboard.views_command import _hero_metrics
        from portfolio.models import PortfolioSnapshot
        pf = _portfolio(self.user)
        hero = _hero_metrics(self.user)
        self.assertEqual(hero["delta"], DASH)
        self.assertIn("23:30 UTC", hero["delta_title"])
        yesterday = timezone.localdate() - timedelta(days=1)
        PortfolioSnapshot.objects.create(
            portfolio=pf, date=yesterday, total_value=Decimal("10000"),
            cash=Decimal("9000"), daily_pnl=Decimal("42"),
            daily_pnl_pct=0.42, cumulative_pnl_pct=1.0, max_drawdown=-2.0)
        hero = _hero_metrics(self.user)
        self.assertEqual(hero["prev_delta"], "+0.42%")
        self.assertIn(yesterday.isoformat(), hero["prev_title"])


# ── 4. Numbers ───────────────────────────────────────────────────────────

class NumbersTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = _user("oc_numbers")
        self.client.force_login(self.user)

    def test_no_eight_decimals_and_prices_in_the_instruments_own(self):
        _three_worlds(self.user)
        for path in ("/command/tab/live/", "/command/tab/portfolio/"):
            text = " ".join(t for t, _a, _g in _texts(
                self.client.get(path).content.decode()))
            self.assertNotRegex(text, r"\d\.\d{8}\b", path)
            self.assertIn("1.08412", text, path)
            self.assertNotRegex(text, r"(?<![\d.])1\.0841(?!\d)", path)

    def test_every_money_cell_has_two_decimals_and_a_currency(self):
        _portfolio(self.user)
        _quote("BTCUSD", "34481.4", "crypto")
        cfg = _config(self.user, "oc big", "crypto")
        _trade(cfg, "BTCUSD", 1, 34000, world="paper")
        _trade(cfg, "BTCUSD", 1, 34000, world="paper", status="CLOSED",
               pnl="481.4", r=1.0, closed_ago_s=600)
        live = self.client.get("/command/tab/live/").content.decode()
        self.assertIn("34,481.40 USD", live)
        money = re.compile(r"^(?:≈ )?[+\-−]?\d{1,3}(?:,\d{3})*\.\d{2} [A-Z]{3}$")
        n = 0
        for path in FRAGMENTS + ("/command/",):
            html = self.client.get(path).content.decode()
            if path == "/command/":
                html = _page_part(html)
            for tag, attrs, texts in _walk(html).elements:
                if "data-oc-money" not in attrs:
                    continue
                value = " ".join("".join(texts).split())
                n += 1
                self.assertTrue(value == DASH or money.match(value),
                                f"{path}: {value!r}")
        self.assertGreaterEqual(n, 12)

    def test_etoros_used_figure_carries_the_accounts_currency(self):
        """ETORO USED printed 600.00 with no currency (the map, 5.7): the
        figure is eToro's, in the account's own currency
        (etoro_used.account_used's `currency`), and the cell says it."""
        _three_worlds(self.user)
        live = self.client.get("/command/tab/live/").content.decode()
        cell = live[live.index("ETORO USED"):]
        cell = cell[:cell.index("</div>")]
        self.assertRegex(cell, r"data-oc-money[^>]*>600\.00 USD<")

    def test_the_equity_curves_low_and_high_are_grouped(self):
        """The platform book is 25,000.50 everywhere on the page; the
        curve's low and high printed 25000.50 (spec §5.2: money is
        grouped, with two decimals)."""
        from portfolio.models import PortfolioSnapshot
        pf = _portfolio(self.user)
        day = timezone.localdate() - timedelta(days=1)
        for i, value in enumerate(("25000.5", "10000")):
            PortfolioSnapshot.objects.create(
                portfolio=pf, date=day - timedelta(days=i),
                total_value=Decimal(value), cash=Decimal("9000"),
                daily_pnl=Decimal("10"), daily_pnl_pct=0.1,
                cumulative_pnl_pct=1.0, max_drawdown=-2.0)
        # The visible text: the chart's data attributes keep the plain
        # numbers its script parses.
        text = " ".join(t for t, _a, _g in _texts(
            self.client.get("/command/tab/portfolio/").content.decode()))
        self.assertIn("low 10,000.00 · high 25,000.50", text)
        self.assertNotIn("25000.50", text)


# ── 5. Windows and ages ──────────────────────────────────────────────────

class WindowsAndAgesTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = _user("oc_windows")
        self.client.force_login(self.user)
        _three_worlds(self.user)

    def test_each_statistic_says_its_window(self):
        portfolio = self.client.get("/command/tab/portfolio/").content.decode()
        self.assertIn("lifetime", portfolio)
        live = self.client.get("/command/tab/live/").content.decode()
        self.assertIn("all worlds · R only", live)
        self.assertIn("Gate events · the last 30, any age", live)
        self.assertIn("24 h", live)
        history = self.client.get("/command/tab/history/").content.decode()
        self.assertIn("90 d", history)
        bots = self.client.get("/command/tab/bots/").content.decode()
        self.assertIn("24 h", bots)

    def test_no_strip_line_is_cut_by_an_ellipsis(self):
        """The line under a strip figure is where its window, its worlds
        and its age are said ("· all worlds · R only", "· report 2 h ago",
        "· platform-wide"). On one line with an ellipsis, a six-cell strip
        at 1440 px showed "0 closed · win rate — …" and "conf 0.62 · trust
        MEDI…": the label was in the page and not on the screen. Every
        such line on the four tabs wraps (sauron.css's
        .oc-strip-sub--wrap, as PORTFOLIO's and eToro's cells already
        did)."""
        from brain.models import BrainReport
        BrainReport.objects.create(regime_label="trending",
                                   regime_confidence=0.62)
        for path in FRAGMENTS:
            body = self.client.get(path).content.decode()
            lines = re.findall(r'class="(oc-strip-sub\b[^"]*)"', body)
            self.assertGreaterEqual(len(lines), 4, path)
            cut = [c for c in lines if "oc-strip-sub--wrap" not in c.split()]
            self.assertEqual(cut, [], path)
        css = (BASE / "static" / "css" / "sauron.css").read_text(
            encoding="utf-8")
        self.assertRegex(css, r"\.oc-strip-sub\.oc-strip-sub--wrap\s*\{[^}]*"
                              r"white-space:\s*normal")

    def test_the_regime_snapshots_and_gate_times_carry_their_age(self):
        from brain.models import BrainReport
        from bot_program.orchestrator_models import OrchestratorEvent
        from dashboard.views_command import _hero_metrics
        from portfolio.models import PortfolioSnapshot
        from portfolio.services import get_or_create_default_portfolio
        rep = BrainReport.objects.create(regime_label="trending",
                                         regime_confidence=0.62)
        BrainReport.objects.filter(pk=rep.pk).update(
            created_at=timezone.now() - timedelta(hours=2, minutes=5))
        hero = _hero_metrics(self.user)
        self.assertEqual(hero["regime_age"], "2 h ago")
        pf = get_or_create_default_portfolio(user=self.user)
        day = timezone.localdate() - timedelta(days=1)
        for i in range(6):
            PortfolioSnapshot.objects.create(
                portfolio=pf, date=day - timedelta(days=i),
                total_value=Decimal("10000"), cash=Decimal("9000"),
                daily_pnl=Decimal("10"), daily_pnl_pct=0.1 * (i % 3 - 1),
                cumulative_pnl_pct=1.0, max_drawdown=-2.0)
        body = self.client.get("/command/tab/portfolio/").content.decode()
        self.assertIn(f"snapshot {day.isoformat()}", body)
        old = OrchestratorEvent.objects.create(
            user=self.user, asset_class="forex", symbol="EURUSD", side="BUY",
            decision="reject", reason="orchestrator: usd theme cap")
        when = timezone.now() - timedelta(days=3)
        OrchestratorEvent.objects.filter(pk=old.pk).update(created_at=when)
        live = self.client.get("/command/tab/live/").content.decode()
        self.assertIn(when.strftime("%Y-%m-%d %H:%M"), live)


# ── 6. Dashes ────────────────────────────────────────────────────────────

def _check_dashes(case, html, where):
    """Every dash in `html` has a title, and the legend lists it; a dash
    never sits untitled inside a sentence either. Returns how many."""
    walker = _walk(html)
    legend = set()
    for tag, attrs, texts in walker.elements:
        if "data-oc-why" in attrs:
            legend.add(" ".join("".join(texts).split()))
    dashes = 0
    for text, attrs, tag in walker.texts:
        if text.strip() != DASH:
            # A dash that stands for a figure, inside a longer text node:
            # "— configs · — enabled" (a separator dash has a word on
            # both sides).
            case.assertNotRegex(
                " ".join(text.split()), r"(?:^|· |: )— (?!$)|(?<=[a-z] )—$",
                f"{where}: an untitled dash inside {text.strip()!r}")
            continue
        dashes += 1
        title = (attrs.get("title") or "").strip()
        case.assertTrue(title, f"{where}: a dash in <{tag}> has no title")
        case.assertIn(" ".join(title.split()), legend,
                      f"{where}: {title!r} is not in the legend")
    return dashes


class DashesTests(TestCase):
    """A dash means no figure here, and its line says why; 0 is a
    measured zero (spec §5.7)."""

    def _check(self, html, where):
        return _check_dashes(self, html, where)

    def test_every_dash_has_a_title_and_the_footer_lists_it(self):
        for name, build in (("empty", lambda u: None),
                            ("three worlds", _three_worlds)):
            user = _user(f"oc_dash_{name.replace(' ', '_')}")
            build(user)
            self.client.force_login(user)
            n = self._check(_page_part(
                self.client.get("/command/").content.decode()), name + " page")
            self.assertGreater(n, 0, name)
            for path in FRAGMENTS:
                self._check(self.client.get(path).content.decode(),
                            f"{name} {path}")

    def test_the_payloads_dashes_are_strings_with_words(self):
        from dashboard.views_day import day_live_payload
        user = _user("oc_dash_payload")
        cache.delete("morgul:summary")
        live = day_live_payload(user)
        flat = [m for st in live["stages"].values() for m in st["metrics"]]
        self.assertTrue(all(m[0] is not None for m in flat), flat)
        dashed = {m[1]: m[0] for m in flat if m[0] == DASH}
        for words in ("min since the newest live quote — none stored yet",
                      "min since the freshest bot tick — no heartbeat yet",
                      "Morgul guards ran — no run recorded",
                      "min since the broker's reading — none landed yet"):
            self.assertIn(words, dashed, dashed)

    def test_a_dash_the_poll_paints_carries_its_reason(self):
        """The page's poll writes each hero key's text and, when the
        payload has it, `<key>_title` over the cell's title. A key that
        comes back as the dash with no title, or an empty one, left the
        dash with the title of the figure it replaced, or with none: every
        hero key the page patches carries its reason whenever it is the
        dash, with the book walk failing too."""
        from dashboard.views_command import _hero_metrics, _tab_bar_metrics
        page = (BASE / "templates" / "dashboard" / "command.html").read_text(
            encoding="utf-8")
        keys = sorted(set(re.findall(r'data-oc-hero="(\w+)"', page)))
        self.assertIn("prev_delta", keys)
        user = _user("oc_dash_poll")
        states = {"empty": lambda: (_hero_metrics(user),
                                    _tab_bar_metrics(user))}

        def failed():
            with mock.patch("dashboard.views_command._open_book",
                            side_effect=RuntimeError("quote feed down")):
                with self.assertLogs("dashboard.views_command",
                                     level="WARNING"):
                    return _hero_metrics(user), _tab_bar_metrics(user)
        states["the walk failed"] = failed
        for name, read in states.items():
            hero, tabs = read()
            dashed = [k for k in keys if hero.get(k) == DASH]
            self.assertIn("delta", dashed, name)
            for key in dashed:
                self.assertTrue(str(hero.get(key + "_title") or "").strip(),
                                f"{name}: hero {key} is a dash with no reason")
            for tab, head in tabs.items():
                for part in ("primary", "secondary"):
                    if head[part] == DASH:
                        self.assertTrue(head[part + "_title"].strip(),
                                        f"{name}: {tab} {part}")
        hero, _tabs = states["the walk failed"]()
        self.assertEqual(hero["value"], DASH)

    @skipIf(NODE is None, "node is not installed")
    def test_both_painters_print_the_dash_and_never_null(self):
        """The tiles (sv-day-live.js) and the panel (sv-day-scheme.js)
        print a metric through their own fmt(), which is String(n): a null
        in the payload would print "null". Each fmt, as shipped, is handed
        the payload's own values under node: the dash comes out as the
        dash, and nothing comes out as "null" (spec §5.7)."""
        from dashboard.views_day import day_live_payload
        user = _user("oc_dash_painters")
        cache.delete("morgul:summary")
        live = day_live_payload(user)
        values = [m[0] for st in live["stages"].values()
                  for m in st["metrics"]]
        self.assertIn(DASH, values)
        for rel in ("static/js/sv-day-live.js", "static/js/sv-day-scheme.js"):
            src = (BASE / rel).read_text(encoding="utf-8")
            fmt = re.search(r"function fmt\(n\) \{.*?\n  \}", src, re.S)
            self.assertIsNotNone(fmt, f"{rel}: fmt() not found")
            proc = subprocess.run(
                [NODE, "-e", fmt.group(0) + ";process.stdout.write(JSON."
                 "stringify(JSON.parse(process.argv[1]).map(fmt)))",
                 json.dumps(values)],
                capture_output=True, text=True, timeout=60)
            self.assertEqual(proc.returncode, 0, proc.stderr[-800:])
            printed = json.loads(proc.stdout)
            self.assertEqual(len(printed), len(values), rel)
            self.assertNotIn("null", printed, rel)
            for value, text in zip(values, printed):
                if value == DASH:
                    self.assertEqual(text, DASH, rel)


class WhenAReadFailsTests(TestCase):
    """A read that fails is "not measured", never "none". Each block of
    the LIVE tab is fenced and prints dashes when its read raises; the
    dashes then said what an empty day says ("the gate was not asked in
    24 h", "closed with no R", "No graded loser: a clean session", a
    brain with "0" concerns), or stood untitled inside a sentence. A
    failed read now says so, in the spec's words for it (§5.7), and
    every failure is logged."""

    NOT_MEASURED = "not measured: a source could not be read"

    def setUp(self):
        cache.clear()
        self.user = _user("oc_fail")
        self.client.force_login(self.user)
        _three_worlds(self.user)

    def _live(self, patcher):
        with patcher:
            with self.assertLogs("dashboard.views_command", level="WARNING"):
                body = self.client.get("/command/tab/live/").content.decode()
        _check_dashes(self, body, "a failed read")
        return body, " ".join(t for t, _a, _g in _texts(body))

    def _cell(self, body, label):
        """The strip cell whose label is `label`: (its html, its text)."""
        for cell in re.findall(r'<div class="oc-strip-cell".*?</div>', body,
                               re.S):
            if f'<span class="oc-strip-label">{label}</span>' in cell:
                return cell, " ".join(
                    "".join(t for t, _a, _g in _texts(cell)).split())
        self.fail(f"no strip cell {label!r}")

    def test_the_closes_of_24h(self):
        body, text = self._live(mock.patch(
            "dashboard.views_command._fill_card",
            side_effect=RuntimeError("closes unreadable")))
        for false_none in ("No graded loser: a clean session",
                           "No graded winner yet", "No fills in the last 24h",
                           "No graded closes in last 24h",
                           "closed with no R", "nothing closed in 24 h"):
            self.assertNotIn(false_none, text)
        for label in ("24H R", "W / L 24H"):
            cell, _text = self._cell(body, label)
            self.assertIn(f'title="{self.NOT_MEASURED}"', cell, label)
        self.assertGreaterEqual(text.count("the closes could not be read"), 4)
        # The configs are the Eye's own read: they do not die with the
        # closes.
        _cell, opens = self._cell(body, "OPEN POS")
        self.assertIn("3 configs · 3 enabled", opens)

    def test_the_gate(self):
        from bot_program.orchestrator_models import OrchestratorEvent
        body, text = self._live(mock.patch.object(
            OrchestratorEvent.objects, "filter",
            side_effect=RuntimeError("gate unreadable")))
        cell, cell_text = self._cell(body, "GATE 24H")
        self.assertIn(f'title="{self.NOT_MEASURED}"', cell)
        self.assertNotIn("the gate was not asked", body)
        self.assertNotIn("allow logged", cell_text)

    def test_the_rules(self):
        from signals.models_control import RuleControl
        body, _text = self._live(mock.patch.object(
            RuleControl, "running_q",
            side_effect=RuntimeError("rules unreadable")))
        cell, cell_text = self._cell(body, "RULES")
        self.assertIn(f'title="{self.NOT_MEASURED}"', cell)
        self.assertNotIn("paused ·", cell_text)

    def test_the_brain(self):
        body, text = self._live(mock.patch(
            "dashboard.views_command._brain_reading",
            side_effect=RuntimeError("brain unreadable")))
        for label in ("REGIME", "CONCERNS"):
            cell, _text = self._cell(body, label)
            self.assertIn(f'title="{self.NOT_MEASURED}"', cell, label)
        self.assertNotIn("the brain has written no report", body)
        self.assertNotIn("No active concerns from the brain", text)
        _cell, concerns = self._cell(body, "CONCERNS")
        self.assertNotRegex(concerns, r"CONCERNS 0\b")


# ── 7. The bots tab ──────────────────────────────────────────────────────

class BotsTabTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = _user("oc_bots")
        self.client.force_login(self.user)

    def test_a_live_mode_config_on_a_demo_account_reads_demo(self):
        _etoro(self.user, demo=True, forex=True)
        _instrument("EURUSD", "forex")
        _config(self.user, "fx on demo", "forex", mode="live",
                symbols=["EURUSD"])
        r = self.client.get("/command/tab/bots/")
        body = r.content.decode()
        row = re.search(r"<tr[^>]*>(?:(?!</tr>).)*fx on demo.*?</tr>", body,
                        re.S).group(0)
        self.assertIn("sv-world--demo", row)
        self.assertNotIn("sv-world--live", row)
        self.assertIn("REAL-MONEY BOTS", body)
        self.assertEqual(r.context["n_live"], 0)
        self.assertEqual(r.context["n_live_demo"], 1)

    def test_health_comes_from_the_heartbeat_not_from_trades(self):
        now = timezone.now()
        fresh = _config(self.user, "ticks on time", "crypto", extras={
            "last_tick_at": (now - timedelta(minutes=2)).isoformat()})
        late = _config(self.user, "traded but silent", "crypto", extras={
            "last_tick_at": (now - timedelta(hours=5)).isoformat()})
        _trade(late, "BTCUSD", 1, 20000, world="paper", opened_ago_s=600)
        _config(self.user, "switched off", "crypto", enabled=False, extras={
            "last_tick_at": (now - timedelta(minutes=1)).isoformat()})
        r = self.client.get("/command/tab/bots/")
        health = {row["config"].name: row["health"] for row in r.context["rows"]}
        self.assertEqual(health, {"ticks on time": "ALIVE",
                                  "traded but silent": "IDLE",
                                  "switched off": "OFF"})
        self.assertEqual(r.context["n_alive"], 1)
        self.assertNotIn("ALIVE 6H", r.content.decode())
        self.assertIsNotNone(fresh)

    def _pnl_cell(self, body, name):
        row = re.search(r"<tr[^>]*>(?:(?!</tr>).)*%s.*?</tr>" % re.escape(name),
                        body, re.S).group(0)
        cell = re.findall(r"<td[^>]*>.*?</td>", row, re.S)[7]
        return row, " ".join("".join(t for t, _a, _g in _texts(cell)).split())

    def test_a_close_from_another_world_names_its_world(self):
        """The P&L cell prints each world's money apart, but one world's
        alone went unnamed and read as the row chip's. A config switched to
        paper mode while a REAL row was still open closes real money under
        a PAPER chip: the cell names the world of its money whenever it is
        not the chip's (spec §5.2: the world is world_of on the trade)."""
        was_live = _config(self.user, "was live", "stock", mode="paper")
        _trade(was_live, "AAPL", 1, 200, world="live", status="CLOSED",
               pnl=-10, r=-1.0, closed_ago_s=600)
        own = _config(self.user, "paper own", "crypto")
        _trade(own, "BTCUSD", 1, 20000, world="paper", status="CLOSED",
               pnl=100, r=2.0, closed_ago_s=600)
        body = self.client.get("/command/tab/bots/").content.decode()
        row, cell = self._pnl_cell(body, "was live")
        self.assertIn("sv-world--paper", row)
        self.assertEqual(cell, "-10.00 USD REAL")
        row, cell = self._pnl_cell(body, "paper own")
        self.assertIn("sv-world--paper", row)
        self.assertEqual(cell, "+100.00 USD")


# ── 8. Cost ──────────────────────────────────────────────────────────────

class CostTests(TestCase):
    """Budgets cold, after cache.clear() (spec §7.3), on the three worlds,
    a hand-recorded row and a few configs.

    Two kinds of read are the shell's, not the page's, and the spec's
    baselines (§7.1: each the last of several GETs) were taken without them:
      - the presence stamp (core/presence.py): the middleware writes one
        row per user at most once a minute, whatever the page. A clear
        cache would make every GET here pay it (4 statements under the test
        runner, two of them savepoints), so its throttle is set again after
        each clear;
      - on the page GET, the shell's context processors and the ring's
        counts. The shell is 118 queries cold under the test runner, where
        `_panel_detail` and two other shell readers never read their cache
        (their keys hold ids the runner rolls back), so the 105 of §7.3 is
        asserted as §7.1 measured it: a second GET, with the shell's caches
        read as in production (the cache is cleared after). The page's OWN
        reads (rendered without the shell) are asserted cold, ≤ 30, with
        the ring's counts as the public Wall caches them (wall_facts: 300 s,
        site-wide, 21 queries once per five minutes).
    Measured the same way on origin/main: the page 125 warm (54 own), LIVE
    156 cold, PORTFOLIO 134, HISTORY 124, BOTS 134, metrics 50."""

    BUDGETS = {"/command/tab/live/": 50,
               "/command/tab/portfolio/": 22, "/command/tab/history/": 14,
               "/command/tab/bots/": 14, "/command/tab/metrics/": 25}
    PAGE, PAGE_OWN = 105, 30

    def setUp(self):
        self.user = _user("oc_cost", superuser=True)
        _three_worlds(self.user)
        from portfolio.models import Position
        from portfolio.services import get_or_create_default_portfolio
        _quote("USDJPY", "150.120", "forex")
        Position.objects.create(
            portfolio=get_or_create_default_portfolio(user=self.user),
            instrument=_instrument("USDJPY", "forex", "JPY"),
            direction="long", quantity=Decimal("1000"),
            entry_price=Decimal("150.000"), current_price=Decimal("150.000"),
            opened_at=timezone.now() - timedelta(days=1))
        self.client.force_login(self.user)
        self.client.get("/command/tab/metrics/")   # the session's first sighting

    def _clear(self):
        """cache.clear(), the presence stamp's once-a-minute throttle set
        again (the shell's write, not the page's read)."""
        from core.presence import PRESENCE_WRITE_INTERVAL
        cache.clear()
        cache.set(f"presence:{self.user.pk}", 1, PRESENCE_WRITE_INTERVAL)

    def _count(self, path):
        with CaptureQueriesContext(connection) as ctx:
            r = self.client.get(path)
        self.assertEqual(r.status_code, 200, path)
        return len(ctx.captured_queries)

    def test_the_query_budgets_hold_cold(self):
        over = {}
        for path, budget in self.BUDGETS.items():
            self._clear()
            n = self._count(path)
            if n > budget:
                over[path] = (n, budget)
        self.assertEqual(over, {})

    def test_the_pages_own_reads_hold_cold_and_the_page_holds_warm(self):
        from core.wall_facts import wall_facts
        templates = copy.deepcopy(settings.TEMPLATES)
        templates[0]["OPTIONS"]["context_processors"] = [
            p for p in templates[0]["OPTIONS"]["context_processors"]
            if not p.startswith(("core.context_processors", "core.context_ui"))]
        self._clear()
        wall_facts()                       # the public Wall's own cache
        with override_settings(TEMPLATES=templates):
            own = self._count("/command/")
        self.assertLessEqual(own, self.PAGE_OWN)
        self.addCleanup(cache.clear)
        self._clear()
        with mock.patch.object(sys, "argv", ["manage.py", "runserver"]):
            self.client.get("/command/")
            warm = self._count("/command/")
        self.assertLessEqual(warm, self.PAGE)

    def test_each_fragment_is_the_same_without_the_shell(self):
        templates = copy.deepcopy(settings.TEMPLATES)
        templates[0]["OPTIONS"]["context_processors"] = [
            p for p in templates[0]["OPTIONS"]["context_processors"]
            if not p.startswith(("core.context_processors", "core.context_ui"))]
        token = re.compile(r'(name="csrfmiddlewaretoken" value=")[^"]+')
        stamp = re.compile(r"\d\d:\d\d:\d\d UTC")
        for path in FRAGMENTS:
            with mock.patch("django.utils.timezone.now",
                            return_value=timezone.now()):
                full = self.client.get(path).content.decode()
                with override_settings(TEMPLATES=templates):
                    bare = self.client.get(path).content.decode()
            clean = lambda s: stamp.sub("", token.sub(r"\1", s))  # noqa: E731
            self.assertEqual(clean(full), clean(bare), path)


class AggregatesEqualTheLoopsTests(TestCase):
    """The database aggregates replace Python loops over every close; on a
    fixture with an unknown, a zero and a hand-recorded close, they answer
    what the loops answered, world by world."""

    def setUp(self):
        self.user = _user("oc_agg")
        self.client.force_login(self.user)
        pf = _portfolio(self.user)
        real = _config(self.user, "agg real", "stock", mode="live")
        demo = _config(self.user, "agg demo", "forex")
        paper = _config(self.user, "agg paper", "crypto")
        days = 0
        for cfg, world, pnls in ((real, "live", (30, 10, -10, -5, None, 0)),
                                 (demo, "demo", (2, -1, 0)),
                                 (paper, "paper", (50, -20, -30, None))):
            for pnl in pnls:
                days += 1
                _trade(cfg, "AAPL" if world == "live" else
                       "EURUSD" if world == "demo" else "BTCUSD",
                       1, 100, world=world, status="CLOSED", pnl=pnl,
                       r=None if pnl is None else pnl / 10,
                       opened_ago_s=86400 * days + 60,
                       closed_ago_s=86400 * days)
        from portfolio.models import Position
        for i, pnl in enumerate(("7.00", "-3.00", "0.00")):
            Position.objects.create(
                portfolio=pf, instrument=_instrument("EURUSD", "forex"),
                direction="long", quantity=Decimal("1"),
                entry_price=Decimal("1"), current_price=Decimal("1"),
                unrealized_pnl=Decimal(pnl),
                opened_at=timezone.now() - timedelta(days=30 + i),
                closed_at=timezone.now() - timedelta(days=20 + i))

    def _old_loop(self):
        """The old tab's loop over unified_closed_positions, kept here, with
        each close's world read by world_of off its trade."""
        from bot_program.models import AssetBotTrade
        from dashboard.position_summary import world_of
        from portfolio.services import (get_or_create_default_portfolio,
                                        unified_closed_positions)
        pf = get_or_create_default_portfolio(user=self.user)
        worlds = {t.id: world_of(t) for t in AssetBotTrade.objects.filter(
            config__user=self.user, status="CLOSED")}
        out = {}
        for p in unified_closed_positions(self.user, pf):
            w = worlds.get(getattr(p, "trade_id", None), "") \
                if getattr(p, "source", "") == "bot" else ""
            out.setdefault(w, []).append(p.unrealized_pnl)
        stats = {}
        for w, pnls in out.items():
            graded = [float(x) for x in pnls if x is not None]
            wins = [x for x in graded if x > 0]
            losses = [x for x in graded if x < 0]
            stats[w] = {
                "n": len(pnls), "n_graded": len(graded),
                "n_unknown": len(pnls) - len(graded),
                "wins": len(wins), "losses": len(losses),
                "avg_win": round(sum(wins) / len(wins), 2) if wins else None,
                "avg_loss": (round(sum(losses) / len(losses), 2)
                             if losses else None),
                "profit_factor": (round(sum(wins) / abs(sum(losses)), 2)
                                  if losses else None)}
        return stats

    def test_portfolio_aggregates_equal_the_old_loop(self):
        stats = self.client.get("/command/tab/portfolio/").context[
            "stats_by_world"]
        for world, old in self._old_loop().items():
            for key, value in old.items():
                self.assertEqual(stats[world][key], value, (world, key))

    def test_historys_per_day_cumulative_r_equals_the_per_close_line(self):
        from bot_program.models import AssetBotTrade
        r = self.client.get("/command/tab/history/")
        closes = list(AssetBotTrade.objects.filter(
            config__user=self.user, status="CLOSED",
            closed_at__gte=timezone.now() - timedelta(days=90),
            realized_r__isnull=False).order_by("closed_at")
            .values_list("closed_at", "realized_r"))
        running, at_day_end = 0.0, {}
        for at, rr in closes:
            running += float(rr)
            at_day_end[at.date()] = round(running, 4)
        self.assertEqual(r.context["cum_r_days"],
                         [d.isoformat() for d in sorted(at_day_end)])
        self.assertEqual(r.context["cum_r_points"],
                         [at_day_end[d] for d in sorted(at_day_end)])

    def test_the_best_and_worst_equal_a_sort_of_every_close(self):
        """Two ranked reads (one per book) answer what sorting every close
        answered: the five largest gains and the five largest losses, bot
        and hand-recorded together, each in its own world."""
        from bot_program.models import AssetBotTrade
        from dashboard.position_summary import world_of
        from portfolio.services import (get_or_create_default_portfolio,
                                        unified_closed_positions)
        pf = get_or_create_default_portfolio(user=self.user)
        worlds = {t.id: world_of(t) for t in AssetBotTrade.objects.filter(
            config__user=self.user, status="CLOSED")}
        closes = [(float(p.unrealized_pnl), p.instrument.symbol,
                   worlds.get(getattr(p, "trade_id", None), "")
                   if getattr(p, "source", "") == "bot" else "")
                  for p in unified_closed_positions(self.user, pf)
                  if p.unrealized_pnl is not None]
        best = sorted((c for c in closes if c[0] > 0), reverse=True)[:5]
        worst = sorted(c for c in closes if c[0] < 0)[:5]
        ctx = self.client.get("/command/tab/portfolio/").context
        got = lambda rows: [(r["pnl"], r["symbol"], r["world"])  # noqa: E731
                            for r in rows]
        self.assertEqual(got(ctx["best_trades"]),
                         [(p, s, w) for p, s, w in best])
        self.assertEqual(got(ctx["worst_trades"]),
                         [(p, s, w) for p, s, w in worst])
        self.assertEqual([p for p, _s, _w in best], [50, 30, 10, 7, 2])
        self.assertEqual([p for p, _s, _w in worst], [-30, -20, -10, -5, -3])

    def test_the_bots_aggregates_equal_the_per_config_loop(self):
        from bot_program.models import AssetBotConfig, AssetBotTrade
        cfg = AssetBotConfig.objects.get(user=self.user, name="agg paper")
        _trade(cfg, "BTCUSD", 1, 100, world="paper", opened_ago_s=300)
        _trade(cfg, "BTCUSD", 1, 100, world="paper", status="CLOSED",
               pnl=12, r=1.2, opened_ago_s=900, closed_ago_s=600)
        rows = {row["config"].id: row for row in
                self.client.get("/command/tab/bots/").context["rows"]}
        since = timezone.now() - timedelta(hours=24)
        for c in AssetBotConfig.objects.filter(user=self.user):
            trades = AssetBotTrade.objects.filter(config=c)
            closed = trades.filter(status="CLOSED", closed_at__gte=since)
            pnl = sum((t.pnl for t in closed if t.pnl is not None),
                      Decimal("0")) if closed.exists() else None
            row = rows[c.id]
            self.assertEqual(row["open_count"], trades.filter(
                status__in=("OPEN", "CLOSE_PENDING")).count(), c.name)
            self.assertEqual(row["opens_24h"],
                             trades.filter(opened_at__gte=since).count())
            self.assertEqual(row["closed_24h"], closed.count())
            self.assertEqual(row["pnl_24h"],
                             None if pnl is None else float(pnl), c.name)


# ── 9. No broker or model call ───────────────────────────────────────────

class NoBrokerOrModelCallTests(TestCase):
    SOURCES = ("dashboard/views_command.py",)
    FORBIDDEN = ("client_for_symbol", "EtoroTrader", "etoro_client",
                 "ai_agents.providers", "BaseAgent", "anthropic", "openai",
                 "import requests", "urllib")

    def test_the_source_imports_no_adapter_and_no_model(self):
        for rel in self.SOURCES:
            src = (BASE / rel).read_text(encoding="utf-8")
            for word in self.FORBIDDEN:
                self.assertNotIn(word, src, f"{rel}: {word}")

    def test_the_page_and_its_fragments_render_with_every_door_shut(self):
        user = _user("oc_nocall", superuser=True)
        _three_worlds(user)
        self.client.force_login(user)
        calls = []

        def refuse(name):
            def _raise(*a, **k):
                calls.append(name)
                raise AssertionError(f"{name} was called")
            return _raise
        patches = [
            mock.patch("bot_program.engine.etoro_client.EtoroTrader.__init__",
                       refuse("EtoroTrader")),
            mock.patch("bot_program.engine.broker_router.client_for_symbol",
                       refuse("client_for_symbol")),
            mock.patch("http.client.HTTPConnection.connect",
                       refuse("HTTPConnection.connect")),
            mock.patch("urllib3.connectionpool.HTTPConnectionPool.urlopen",
                       refuse("urlopen")),
            mock.patch("ai_agents.providers.claude_provider.ClaudeProvider"
                       ".complete", refuse("model")),
            mock.patch("ai_agents.base_agent.BaseAgent.run", refuse("agent")),
        ]
        for p in patches:
            p.start()
        try:
            for path in ("/command/", "/command/tab/metrics/") + FRAGMENTS:
                self.assertEqual(self.client.get(path).status_code, 200, path)
        finally:
            for p in patches:
                p.stop()
        self.assertEqual(calls, [])


# ── 10. The page's own poll ──────────────────────────────────────────────

@skipIf(NODE is None, "node is not installed")
class ThePollUnderNodeTests(SimpleTestCase):
    """tests/js/command_metrics.test.js drives the metrics poll exactly as
    command.html ships it, under node with the browser stubbed."""

    def test_the_poll_stops_on_lock_redirect_and_hidden_and_resumes(self):
        proc = subprocess.run(
            [NODE, str(BASE / "tests" / "js" / "command_metrics.test.js"),
             str(BASE / "templates" / "dashboard" / "command.html")],
            capture_output=True, text=True, timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        out = json.loads(proc.stdout)
        self.assertEqual(out["failed"], [], out)
        for case in ("sends_x_requested_with", "stops_on_423",
                     "stops_on_redirect", "nothing_while_hidden",
                     "resumes_on_pin_unlocked", "resumes_when_visible",
                     "eye_event_refetches"):
            self.assertIn(case, out["passed"], out)


class ThePollOnTheServerTests(TestCase):
    """What the server makes of the page's own poll, asked as the page
    asks it (X-Requested-With, the header the node test above sees the
    shipped script send): the idle lock never counts it as a human, so it
    never stamps the session, and a locked session gets 423. Asked without
    the header, as the page did before OC0, the same poll stamped the
    session every 45 s and the server's idle backstop never fired while
    /command/ was open (core/idle_lock.py)."""

    AS_THE_PAGE = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest",
                   "HTTP_ACCEPT": "application/json"}

    def setUp(self):
        cache.clear()
        self.user = _user("oc_poll")
        self.client.force_login(self.user)

    def test_the_poll_never_stamps_the_session(self):
        stale = int(time.time()) - 120   # old enough to stamp, too young to lock
        session = self.client.session
        session["sv_last_seen"] = stale
        session.save()
        r = self.client.get("/command/tab/metrics/", **self.AS_THE_PAGE)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.client.session["sv_last_seen"], stale)
        # The same poll with no header is a human to the lock: it stamps.
        self.client.get("/command/tab/metrics/")
        self.assertGreater(self.client.session["sv_last_seen"], stale)

    def test_a_locked_session_gets_423_and_no_figure(self):
        session = self.client.session
        session["pin_locked"] = True
        session.save()
        r = self.client.get("/command/tab/metrics/", **self.AS_THE_PAGE)
        self.assertEqual(r.status_code, 423)
        self.assertEqual(r.json(), {"pin_locked": True})


class ThePageScriptTests(SimpleTestCase):
    def setUp(self):
        self.page = (BASE / "templates" / "dashboard" / "command.html"
                     ).read_text(encoding="utf-8")

    def test_the_css_is_rendered_once(self):
        """{% block extra_css %} sat inside {% block content %}: the page's
        style block and its sheet were rendered twice (once by base.html's
        own extra_css slot, once inside the content)."""
        parents, stack = {}, []
        for m in re.finditer(r"\{%\s*(block|endblock)\b\s*(\w*)\s*%\}",
                             self.page):
            if m.group(1) == "block":
                parents[m.group(2)] = stack[-1] if stack else None
                stack.append(m.group(2))
            else:
                stack.pop()
        self.assertIn("extra_css", parents)
        self.assertIsNone(parents["extra_css"])
        self.assertEqual(self.page.count("{% block extra_css %}"), 1)

    def test_the_heads_never_flash_eye_green(self):
        m = re.search(r"@keyframes oc-changed\s*\{((?:[^{}]*\{[^{}]*\})*)"
                      r"[^{}]*\}", self.page)
        self.assertIsNotNone(m)
        self.assertNotIn("0,232,104", m.group(1).replace(" ", ""))
        self.assertNotIn("--accent", m.group(1))
