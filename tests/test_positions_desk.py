"""The desk on /positions/ (UI batch B7, S2.2, 2026-11-13).

The operator approved the desk v2 board, the Bloomberg-discipline and
TradingView-calm desk in Sauron's identity ("amazing work, bravo, I need it
fast!!"; scratchpad canvas_v2/project/Desk2.dc.html). This module holds the
page to that board:

  * THE FIGURES (dashboard/positions_desk.py): open P&L by world, never
    summed; the REAL book at eToro (equity, exposure, at the stops against
    the limit, margin used); closed in 24 h with each world's sum apart;
    the REAL exposure by class and by side; closed in 30 days by world,
    judged from 10 graded closes.
  * THE MARKUP: the KPI strip by world (REAL a solid chip, DEMO a gold
    outline, PAPER a grey one), THE BOOK AT ETORO, OPEN POSITIONS with its
    world tabs, the keys (J K move, Enter the Orc line, Tab to Close) and
    CLOSE ALL with the square; the one-line table in the board's columns,
    the Orc line in a disclosure row, the lower row.
  * THE MONEY CONTROLS (UI plan §10): CLOSE, RETRY CLOSE, CLOSE ALL, the
    close dialog, the level editor and the selection's close keep their
    words, steps, PIN and focus order: their scripts are main's, byte for
    byte, and the page's one form is main's.
  * MEASURED (headless Chromium, the page as a file, offline, 1440 x 900,
    dark, Magic): the board's geometry, one-line rows, the table inside
    its card with CLOSE in view, no colour outside the tokens, no text
    under 11 px, every text at 4.5:1 on its ground, no glow, REAL the only
    solid red fill; the REAL edge kept under hover and focus; the keys;
    the disclosure kept across a live swap; the close dialog (live and
    paper) and the level editor on the same census.

Display only: nothing here posts, trades or calls a broker or a model.
Every row is synthetic.

Run with:  python manage.py test tests.test_positions_desk
"""
import hashlib
import json
from html.parser import HTMLParser
import pathlib
import re
import unittest
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client, SimpleTestCase, TestCase
from django.utils import timezone

from tests.test_close_advice import CHROME, HOST

ROOT = pathlib.Path(settings.BASE_DIR)
PAGE = "templates/dashboard/positions_list.html"
SHEET = "static/css/sv-positions.css"
SCRIPT = "static/js/sv-positions.js"

LIVE = {"broker": "etoro", "broker_env": "live"}
DEMO = {"broker": "etoro", "broker_env": "paper"}


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


# ── The synthetic book ─────────────────────────────────────────────────────

def _instrument(symbol, asset_class):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class,
                                 "is_active": True})
    return inst


def _quote(symbol, asset_class, last, *, source="etoro", age_s=None,
           bid=None, ask=None):
    from market_data.models import LiveQuote
    inst = _instrument(symbol, asset_class)
    q, _ = LiveQuote.objects.update_or_create(
        instrument=inst, defaults={
            "last": Decimal(str(last)), "source": source,
            "bid": None if bid is None else Decimal(str(bid)),
            "ask": None if ask is None else Decimal(str(ask))})
    if age_s is not None:
        LiveQuote.objects.filter(pk=q.pk).update(
            updated_at=timezone.now() - timedelta(seconds=age_s))
    return q


def _config(user, asset_class, mode):
    from bot_program.models import AssetBotConfig
    cfg, _ = AssetBotConfig.objects.get_or_create(
        user=user, asset_class=asset_class, name="desk_%s_%s" % (asset_class, mode),
        defaults=dict(enabled=True, mode=mode, symbols=[],
                      capital=Decimal("10000"), base_currency="USD"))
    return cfg


def _open(user, symbol, cls, side, qty, entry, stop, target, *, world,
          pid=None, hours=2):
    from bot_program.models import AssetBotTrade
    meta = {"value_per_unit": 1.0, "initial_stop_loss": float(stop),
            "leverage": 1}
    if world == "live":
        meta.update(LIVE)
    elif world == "demo":
        meta.update(DEMO)
    if pid:
        meta["broker_position_id"] = pid
    t = AssetBotTrade.objects.create(
        config=_config(user, cls, "paper" if world == "paper" else "live"),
        asset_class=cls, symbol=symbol, side=side, qty=Decimal(qty),
        entry_price=Decimal(entry), stop_loss=Decimal(stop),
        take_profit=Decimal(target), status="OPEN",
        paper=world == "paper", rule_name="breakout_4h",
        reason="a synthetic entry", metadata=meta)
    AssetBotTrade.objects.filter(pk=t.pk).update(
        opened_at=timezone.now() - timedelta(hours=hours))
    t.refresh_from_db()
    return t


def _closed(user, symbol, cls, side, entry, exit_, pnl, r, outcome, *, world,
            hours):
    from bot_program.models import AssetBotTrade
    meta = {"value_per_unit": 1.0, "initial_stop_loss": float(entry) * 0.99}
    if world == "live":
        meta.update(LIVE)
    elif world == "demo":
        meta.update(DEMO)
    t = AssetBotTrade.objects.create(
        config=_config(user, cls, "paper" if world == "paper" else "live"),
        asset_class=cls, symbol=symbol, side=side, qty=Decimal("1"),
        entry_price=Decimal(entry), exit_price=Decimal(exit_),
        status="CLOSED", paper=world == "paper", rule_name="breakout_4h",
        metadata=meta, pnl=Decimal(str(pnl)), realized_r=r, outcome=outcome)
    now = timezone.now()
    AssetBotTrade.objects.filter(pk=t.pk).update(
        opened_at=now - timedelta(hours=hours + 3),
        closed_at=now - timedelta(hours=hours))
    return t


#: The book's eToro position ids and eToro's own net profit for each.
HOLDINGS = (("EURUSD", "5101", 20000, 65.00, "BUY"),
            ("XAUUSD", "5102", 1.5, 15.42, "SELL"),
            ("AAPL", "5103", 4, -4.16, "BUY"))


def desk_book(user, *, orc=True):
    """The board's book, synthetic: three REAL rows at eToro (eToro's own
    P&L for each), two DEMO, one PAPER on a stale outside quote; closes in
    the last day and the last month in every world; the eToro account's
    own cells; the open-risk limit on the limits book. An Orc follows the
    EURUSD row when `orc`."""
    from bot_program.models import EtoroAccount
    from portfolio.models import Portfolio
    from portfolio.services import get_or_create_default_portfolio
    _quote("EURUSD", "forex", "1.08745", bid="1.08745", ask="1.08752")
    _quote("XAUUSD", "commodity", "2648.12", bid="2647.72", ask="2648.12")
    _quote("AAPL", "stock", "227.06", age_s=600)
    _quote("BTCUSD", "crypto", "91230.5")
    _quote("NAS100", "index", "20872.0")
    _quote("GBPUSD", "forex", "1.29044", source="yfinance", age_s=180)
    eur = _open(user, "EURUSD", "forex", "BUY", "20000", "1.08420", "1.08160",
                "1.09040", world="live", pid="5101", hours=2)
    _open(user, "XAUUSD", "commodity", "SELL", "1.5", "2658.40", "2682.00",
          "2610.00", world="live", pid="5102", hours=5)
    _open(user, "AAPL", "stock", "BUY", "4", "228.10", "223.20", "238.00",
          world="live", pid="5103", hours=9)
    _open(user, "BTCUSD", "crypto", "BUY", "0.05", "92410.0", "88900.0",
          "99000.0", world="demo", hours=12)
    _open(user, "NAS100", "index", "BUY", "1", "20810.5", "20700.0",
          "21050.0", world="demo", hours=20)
    _open(user, "GBPUSD", "forex", "SELL", "10000", "1.29110", "1.29480",
          "1.28400", world="paper", hours=30)
    # Closed in the last day: two REAL, five PAPER (the board's lower left).
    _closed(user, "USDCAD", "forex", "BUY", "1.39820", "1.40010", 13.57, 0.95,
            "hit_target", world="live", hours=3)
    _closed(user, "XBRUSD", "commodity", "SELL", "71.95", "72.31", -0.72,
            -0.80, "manual_close", world="live", hours=5)
    _closed(user, "EURJPY", "forex", "SELL", "163.420", "163.180", 15.66, 0.60,
            "hit_target", world="paper", hours=6)
    _closed(user, "NZDUSD", "forex", "BUY", "0.58910", "0.58790", -24.00,
            -1.00, "stopped_out", world="paper", hours=8)
    _closed(user, "US500", "index", "BUY", "5904.0", "5911.5", 15.00, 0.50,
            "time_stop", world="paper", hours=10)
    _closed(user, "XAGUSD", "commodity", "SELL", "31.240", "31.420", -9.00,
            -0.60, "manual_close", world="paper", hours=12)
    _closed(user, "GBPJPY", "forex", "BUY", "198.410", "198.120", -9.47,
            -0.30, "stopped_out", world="paper", hours=14)
    # Older closes inside the month: REAL reaches 12 graded, PAPER 12,
    # DEMO stays at 3 (under the 10 the board judges a world from).
    for i in range(10):
        win = i % 2 == 0
        _closed(user, "EURGBP", "forex", "BUY", "0.86000",
                "0.86200" if win else "0.85900", 20.0 if win else -10.0,
                1.0 if win else -0.5, "hit_target" if win else "stopped_out",
                world="live", hours=48 + i * 24)
    for i in range(3):
        _closed(user, "ETHUSD", "crypto", "BUY", "3000", "3030", 15.0, 0.5,
                "hit_target", world="demo", hours=60 + i * 24)
    for i in range(7):
        win = i < 5
        _closed(user, "USDJPY", "forex", "SELL", "150.000",
                "149.800" if win else "150.100", 12.0 if win else -8.0,
                0.6 if win else -0.4, "hit_target" if win else "stopped_out",
                world="paper", hours=72 + i * 24)
    # eToro's own cells (40 s old) and its holdings with each position's
    # own net profit (8 s old): what the sync writes, no eToro call.
    acct = EtoroAccount.objects.create(user=user, demo=False, label="Main",
                                       is_primary_for_stocks=True)
    acct.set_credentials("synthetic-key", "synthetic-user")
    at = timezone.now() - timedelta(seconds=40)
    acct.last_used_margin = Decimal("4402.10")
    acct.last_available_cash = Decimal("6051.51")
    acct.last_pnl = Decimal("76.26")
    acct.last_frozen_cash = Decimal("0")
    acct.last_balance = Decimal("10377.35")
    acct.last_margin_at = at
    acct.last_margin_world = "live"
    acct.last_equity = Decimal("10453.61")
    acct.last_equity_currency = "USD"
    acct.last_equity_at = at
    acct.broker_positions = [
        {"symbol": s, "sec_type": "CFD", "qty": float(q), "side": side,
         "avg_cost": 1.0, "market_price": 0.0, "market_value": 0.0,
         "unrealized_pnl": 0.0, "currency": "", "leverage": 1,
         "position_id": pid, "amount": 1000.0, "net_profit": net}
        for s, pid, q, net, side in HOLDINGS]
    acct.broker_positions_at = timezone.now() - timedelta(seconds=8)
    acct.save()
    # The limits book's open-risk limit (the gates' own field).
    get_or_create_default_portfolio()
    Portfolio.objects.filter(name="Main").update(max_open_risk_pct=Decimal("2.5"))
    if orc:
        try:
            from tests.orcs.helpers import _on
            from bot_program.orcs.birth import ensure
            _on()
            with TestCase.captureOnCommitCallbacks(execute=True):
                ensure(eur)
        except Exception:  # noqa: BLE001 — the book stands without its Orc
            pass
    return eur


def desk_client(name="desk_op"):
    user = get_user_model().objects.create_user(
        name, password="x", is_staff=True, is_superuser=True)
    desk_book(user)
    client = Client()
    client.force_login(user)
    return user, client


def _get(client, url):
    resp = client.get(url, HTTP_HOST=HOST)
    if resp.status_code != 200:
        raise AssertionError("%s answered %s" % (url, resp.status_code))
    return resp.content.decode("utf-8")


def _rows(html):
    """[(the row's <tr ...> tag, its markup)] for every open position row."""
    out = []
    for m in re.finditer(r"(<tr data-sv-position-row[^>]*>)(.*?)</tr>", html, re.S):
        out.append((m.group(1), m.group(2)))
    return out


# ══════════════════════════════════════════════════════════════════════════
# 1. The figures
# ══════════════════════════════════════════════════════════════════════════

class DeskFiguresTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user, cls.client_ = desk_client("desk_figures")

    def desk(self):
        from dashboard import views
        from django.test import RequestFactory
        request = RequestFactory().get("/positions/", HTTP_HOST=HOST)
        request.user = self.user
        captured = {}
        real = views._live_page

        def grab(req, template, context, live_only):
            captured.update(context)
            return real(req, template, context, live_only)
        from unittest import mock
        with mock.patch.object(views, "_live_page", grab):
            views.positions_list(request)
        return captured

    def test_the_worlds_are_never_summed(self):
        ctx = self.desk()
        worlds = {w["world"]: w for w in ctx["desk"]["worlds"]}
        self.assertEqual(list(worlds), ["live", "demo", "paper"])
        self.assertEqual([worlds[w]["n"] for w in worlds], [3, 2, 1])
        # REAL is the sum of what its rows PRINT: eToro's own net profit.
        self.assertEqual(worlds["live"]["pnl"]["text"], "+76.26")
        self.assertEqual(worlds["live"]["pnl"]["arrow"], "▲")
        self.assertFalse(worlds["live"]["pnl"]["est"])
        self.assertRegex(worlds["live"]["sub"], r"^3 positions · read \d+ s ago$")
        rows = {r["world"]: [] for r in ctx["positions"]}
        for r in ctx["positions"]:
            rows[r["world"]].append(r["unrealized_pnl"])
        for w in ("live", "demo", "paper"):
            self.assertAlmostEqual(worlds[w]["pnl"]["value"], round(sum(rows[w]), 2))
        # Nothing on the desk prints the three added together.
        total = sum(worlds[w]["pnl"]["value"] for w in worlds)
        page = _get(self.client_, "/positions/")
        desk = page[page.index('class="pd-desk"'):page.index('class="sv-metrics-wrapper"')]
        self.assertNotIn("{:+,.2f}".format(total), desk)

    def test_the_book_at_etoro(self):
        book = self.desk()["desk"]["book"]
        self.assertEqual(book["equity"], "$10,453.61")
        self.assertEqual(book["exposure"], "$26,629.42")
        self.assertEqual(book["margin"], "42.1%")
        self.assertEqual((book["margin_used"], book["margin_free"]),
                         ("$4,402.10", "$6,051.51"))
        # Every REAL stop filled: 20,000 x 0.0026 + 1.5 x 23.60 + 4 x 4.90.
        self.assertEqual(book["stops_money"], "-107.00")
        self.assertEqual(book["stops"], "1.02%")
        self.assertEqual(book["stops_limit"], "2.50%")
        self.assertFalse(book["stops_over"])

    def test_the_stops_are_the_orcs_reading_of_the_live_book_made_without_them(self):
        """CI round 1 (2026-11-14): the desk imported the Orcs' own reader
        (bot_program.orcs.sources._live_book), a new importer of the Orcs,
        which their pin refuses (tests/orcs/test_orc_o2a_shadow_pins.py). It
        reads the live book itself now, row for row as the Orcs and the
        open-risk gate price it: the same money on the same book, the DEMO
        and PAPER rows left out."""
        from bot_program.orcs.sources import _live_book
        from dashboard import positions_desk
        from portfolio.models import Portfolio
        pf = Portfolio.objects.get(name="Main")
        risk, share, limit = positions_desk._at_the_stops(self.user)
        _mode, orcs_risk, _limit_money = _live_book(self.user, pf)
        self.assertIsNotNone(orcs_risk)
        self.assertAlmostEqual(risk, orcs_risk, places=9)
        # 20,000 x 0.0026 + 1.5 x 23.60 + 4 x 4.90: the three REAL rows only.
        self.assertAlmostEqual(risk, 107.0, places=6)
        self.assertEqual(limit, 2.5)

    def test_the_real_exposure_by_class_and_side(self):
        ex = self.desk()["desk"]["exposure"]
        self.assertEqual([(c["name"], c["text"], c["share_text"]) for c in ex["classes"]],
                         [("forex", "$21,749.00", "81.7%"),
                          ("commodity", "$3,972.18", "14.9%"),
                          ("stock", "$908.24", "3.4%")])
        self.assertEqual((ex["long_text"], ex["short_text"]), ("85.1%", "14.9%"))
        self.assertEqual(ex["top"], {"symbol": "EURUSD", "text": "81.7%"})

    def test_closed_in_24_hours_each_world_apart(self):
        c = self.desk()["desk"]["closed_24h"]
        self.assertEqual([r["symbol"] for r in c["rows"]],
                         ["USDCAD", "XBRUSD", "EURJPY", "NZDUSD", "US500",
                          "XAGUSD", "GBPJPY"])
        self.assertEqual([r["by"] for r in c["rows"]],
                         ["target", "you", "target", "stop", "time", "you", "stop"])
        self.assertEqual(c["rows"][0]["entry"], "1.39820")
        self.assertEqual(c["rows"][0]["r"], "+0.95R")
        sums = {w["world"]: w["pnl"]["text"] for w in c["worlds"]}
        self.assertEqual(sums, {"live": "+12.85", "demo": "—", "paper": "-11.81"})

    def test_closed_in_30_days_by_world(self):
        rows = {r["world"]: r for r in self.desk()["desk"]["closed_30d"]}
        # REAL: 6 of 12 won; 113.57 won against 50.72 lost; R averages
        # (0.95 - 0.80 + 5 x 1.0 - 5 x 0.5) / 12.
        self.assertEqual((rows["live"]["n"], rows["live"]["won"], rows["live"]["pf"],
                          rows["live"]["r"]), (12, "50%", "2.24", "+0.22R"))
        # Three demo closes: counted, never graded into a rate.
        self.assertEqual((rows["demo"]["n"], rows["demo"]["won"], rows["demo"]["r"],
                          rows["demo"]["pf"]), (3, "—", "—", "—"))
        self.assertEqual(rows["paper"]["n"], 12)
        self.assertEqual(rows["paper"]["won"], "58%")

    def test_the_world_tabs_count_the_book(self):
        tabs = self.desk()["open_view"]["world_tabs"]
        self.assertEqual([(t["label"], t["n"], t["current"]) for t in tabs],
                         [("All", 6, True), ("Real", 3, False), ("Demo", 2, False),
                          ("Paper", 1, False)])
        self.assertEqual(tabs[1]["href"], "/positions/?tab=open&world=live")
        page = _get(self.client_, "/positions/?world=demo")
        rows = _rows(page)
        self.assertEqual(len(rows), 2)
        self.assertTrue(all('data-pos-world="demo"' in tag for tag, _r in rows))
        # A filter narrows the table, never CLOSE ALL: it says so.
        self.assertIn("Close all (whole book)", page)

    def test_an_empty_book_prints_dashes_never_zeros(self):
        from dashboard.positions_desk import desk
        out = desk(self.user, [], [], [], None)
        self.assertEqual([w["pnl"]["text"] for w in out["worlds"]], ["—", "—", "—"])
        self.assertEqual(out["book"]["exposure"], "—")
        self.assertEqual(out["book"]["margin"], "—")
        self.assertIsNone(out["exposure"])


# ══════════════════════════════════════════════════════════════════════════
# 2. The markup
# ══════════════════════════════════════════════════════════════════════════

#: The board's columns, in its order (the select box first, the chevron
#: of the disclosure leading the symbol's cell, CLOSE last).
COLUMNS = ["Symbol", "Side", "World", "Qty", "Entry", "Mark", "P&amp;L", "R",
           "Stop", "Target", "Priced by"]


class DeskMarkupTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user, cls.client_ = desk_client("desk_markup")
        cls.page = _get(cls.client_, "/positions/")
        cls.live = _get(cls.client_, "/positions/live/")

    def test_the_kpi_strip_by_world_and_the_book(self):
        strip = self.page[self.page.index('data-sv-live="pos-strip"'):]
        strip = strip[:strip.index('data-sv-live="pos-count"')]
        self.assertRegex(strip, r'class="pd-card pd-kgrp"[^>]*aria-label="Open P&amp;L by world, never summed"')
        self.assertIn("by world · never summed", strip)
        cells = re.findall(r'data-pd-world="(\w+)"', strip)
        self.assertEqual(cells, ["live", "demo", "paper"])
        self.assertIn('<span class="sv-world sv-world--live" title="Real money: this is an order at the broker">REAL</span>', strip)
        self.assertIn('sv-world--demo', strip)
        self.assertIn('sv-world--paper', strip)
        self.assertIn("The book at eToro", strip)
        for label in ("Exposure", "At the stops", "Margin used"):
            self.assertIn(">%s<" % label, strip)
        self.assertIn("if all stops fill", strip)
        # eToro's own used figure stays said with its words and its split.
        self.assertIn("ETORO USED", strip)

    def test_open_positions_head(self):
        head = self.page[self.page.index('class="pd-card pd-pos"'):]
        head = head[:head.index("<table")]
        self.assertIn(">Open positions<", head)
        self.assertRegex(head, r'<nav class="pd-seg"[^>]*aria-label="Show one world"')
        self.assertEqual(re.findall(r'class="pd-seg-btn[^"]*"[^>]*>([A-Za-z]+) <span', head),
                         ["All", "Real", "Demo", "Paper"])
        self.assertIn('aria-current="page"', head)
        for key in ("J", "K", "Enter", "Tab"):
            self.assertIn('<kbd class="pd-kbd">%s</kbd>' % key, head)
        # "stop · target · Close": from the keys' row Tab walks the symbol,
        # the stop, the target, then CLOSE (the review of 2026-11-13, F8).
        for words in ("move", "the Orc line", "stop · target · Close"):
            self.assertIn(words, head)
        self.assertRegex(head, r'<button type="button" class="btn btn-sm btn-stop" id="svCloseAll"[^>]*>Close all</button>')

    def test_the_table_takes_the_board_s_columns(self):
        table = self.page[re.search(r'<table class="[^"]*\bpd-table\b', self.page).start():]
        thead = table[:table.index("</thead>")]
        got = re.findall(r"<th[^>]*>([^<]*)</th>", thead)
        names = [g for g in got if g.strip()]
        self.assertEqual(names, COLUMNS)

    def test_each_row_is_one_line_with_a_disclosure(self):
        rows = _rows(self.page)
        self.assertEqual(len(rows), 6)
        for tag, row in rows:
            with self.subTest(row=tag[:80]):
                self.assertRegex(row, r'<button type="button" class="pd-disc" aria-expanded="false" aria-controls="pd-det-[\w-]+"')
                # No figure printed at eight decimals (the level editor's
                # data keeps the stored value, which it pre-fills, unchanged).
                printed = re.sub(r"<[^>]*>", " ", row)
                self.assertNotRegex(printed, r"\d+\.\d{8}")
                self.assertIn('class="btn btn-sm btn-danger" data-sv-close-trade=', row)
        # the detail rows follow, closed, and hold the Orc line on EURUSD
        dets = re.findall(r'<tr class="pd-det[^"]*" id="pd-det-[\w-]+"[^>]*hidden>(.*?)</tr>', self.page, re.S)
        self.assertEqual(len(dets), 6)
        self.assertTrue(any('class="pos-orc-line"' in d for d in dets), "no Orc line")
        # quantities in the instrument's digits, never eight decimals
        self.assertIn(">20,000<", self.page)
        self.assertIn(">0.05<", self.page)
        self.assertIn(">1.5<", self.page)

    def test_side_and_pnl_carry_words_and_arrows(self):
        rows = dict((re.search(r'data-pos-symbol="(\w+)"', t).group(1), r) for t, r in _rows(self.page))
        self.assertIn("▲ Long", rows["EURUSD"])
        self.assertIn("▼ Short", rows["XAUUSD"])
        self.assertRegex(rows["EURUSD"], r'class="pd-pv up"[^>]*>\+65\.00<span class="pd-dg"[^>]*>▲</span>')
        self.assertRegex(rows["AAPL"], r'class="pd-pv down"[^>]*>-4\.16<span class="pd-dg"[^>]*>▼</span>')
        # the price's source and age, live where the painter keeps it
        self.assertRegex(rows["GBPUSD"], r'class="pd-src[^"]*"[^>]*data-q="GBPUSD" data-q-f="words"')

    def test_the_lower_row(self):
        for label in ('aria-label="Closed in the last 24 hours"', 'aria-label="Real exposure"',
                      'aria-label="Closed in thirty days, by world"'):
            self.assertIn(label, self.page)
        self.assertIn("History ›", self.page)
        self.assertIn("By side", self.page)
        self.assertIn("A world is judged from 10 graded closes", self.page)

    def test_the_live_refresh_carries_the_desk(self):
        for region in ("pos-strip", "pos-count", "pos-worlds", "pos-open", "pos-lower"):
            with self.subTest(region=region):
                self.assertIn('data-sv-live="%s"' % region, self.live)
        self.assertIn('class="pos-orc-line"', self.live)

    def test_history_keeps_its_tab(self):
        page = _get(self.client_, "/positions/?tab=history")
        self.assertIn("Trade History", page)
        # The closed book's strip stands on the history tab, refreshed with
        # it; the open book's figures (by world) are the open tab's alone.
        strip = page[page.index('data-sv-live="pos-strip"'):]
        strip = strip[:strip.index("</section>")]
        for key in ("pos.closed", "pos.win_rate", "pos.realized",
                    "pos.profit_factor", "pos.avg_wl"):
            self.assertIn('data-sv-live-key="%s"' % key, strip)
        self.assertNotIn("data-pd-world", strip)
        live = _get(self.client_, "/positions/live/?tab=history")
        self.assertIn('data-sv-live="pos-strip"', live)
        self.assertNotIn('data-sv-live="pos-open"', live)

    def test_the_30_day_cells_are_named_for_the_refresh(self):
        for world in ("live", "demo", "paper"):
            for cell in ("won", "r", "n", "pf"):
                self.assertIn('data-sv-live-key="pos.c30.%s.%s"' % (world, cell),
                              self.page)

    def test_the_sheet_and_the_script_load_on_this_page(self):
        self.assertIn("css/sv-positions.css", self.page)
        self.assertIn("js/sv-positions.js", self.page)


# ══════════════════════════════════════════════════════════════════════════
# 3. The money controls keep their words, steps and PIN (§10)
# ══════════════════════════════════════════════════════════════════════════

def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _close_all_script(page_src):
    start = page_src.index("/* CLOSE ALL.")
    end = page_src.index("})();", start) + len("})();")
    return page_src[start:end]


def _close_flow(base_src):
    start = base_src.index("  function closeFlow(btn) {")
    end = base_src.index("  window.svCloseTrade = function (id) {", start)
    return base_src[start:end]


#: main 1b94a50, read on 2026-11-13: the money controls' scripts as they
#: are. A change to one of them changes words, steps or the PIN, and must
#: be made on purpose, with this record.
MAIN_SHA = {
    "close_all": "f1ea1419dfc32052ef6712f8a422bc87f19e4c07fa92e771bfd11615795be242",
    "close_flow": "b067da0814e42412f64c2e61e6211d5fb194969e16610d597723b1bf68d0249a",
    "static/js/sv-level-edit.js": "c1a955853ae5210614ea3cbf187931849b477de120f218b737f81f89d0f30cb1",
    "static/js/sv-close-advice.js": "7b3d67cbe40a14727cd670f2ae56958fe514a13e29f3a957c6c36009a4acb378",
    "static/js/sv-overlay.js": "97d23e286810a63fc674d7ff92c9b1f6c5f744fb764077e90c4c7263ee52a756",
}
#: The page's forms on main 1b94a50 with this book: the shell's three
#: POST forms around the page, and the page's one, the order-and-filter bar
#: (GET), its fields (the venue select shows: the book holds live and
#: paper rows).
MAIN_FORMS = [("post", ["csrfmiddlewaretoken"]), ("post", ["csrfmiddlewaretoken"]),
              ("get", ["class", "group", "side", "sort", "symbol", "tab", "venue"]),
              ("post", ["csrfmiddlewaretoken"])]


class MoneyControlsUnchangedTests(SimpleTestCase):

    def test_close_all_s_script_is_main_s(self):
        self.assertEqual(_sha(_close_all_script(read(PAGE))), MAIN_SHA["close_all"])

    def test_the_close_dialog_s_flow_is_main_s(self):
        self.assertEqual(_sha(_close_flow(read("templates/base.html"))), MAIN_SHA["close_flow"])

    def test_the_level_editor_the_selection_and_the_dialogs_are_main_s(self):
        for rel in ("static/js/sv-level-edit.js", "static/js/sv-close-advice.js",
                    "static/js/sv-overlay.js"):
            with self.subTest(file=rel):
                self.assertEqual(_sha(read(rel)), MAIN_SHA[rel])

    def test_close_and_retry_close_keep_their_words(self):
        src = read(PAGE)
        self.assertIn('class="btn btn-sm btn-danger" data-sv-close-trade="{{ p.trade_id }}">'
                      "{% if p.status == 'CLOSE_PENDING' %}RETRY CLOSE{% else %}CLOSE{% endif %}", src)
        self.assertIn(">Close all{% if open_view.filtered %} (whole book){% endif %}</button>", src)

    def test_the_level_buttons_keep_their_data(self):
        src = read(PAGE)
        for attr in ("data-lvl-trade", "data-lvl-symbol", "data-lvl-side", "data-lvl-stop",
                     "data-lvl-target", "data-lvl-decimals", "data-lvl-live", "data-lvl-protected"):
            self.assertEqual(src.count(attr + "="), 2, attr)


class PageFormsTests(TestCase):

    def test_the_page_s_forms_are_main_s(self):
        _user, client = desk_client("desk_forms")
        page = _get(client, "/positions/")
        forms = []
        for m in re.finditer(r"<form\b([^>]*)>(.*?)</form>", page, re.S):
            method = (re.search(r'method="([^"]*)"', m.group(1)) or [None, "get"])[1]
            names = sorted(set(re.findall(r'name="([^"]+)"', m.group(2))))
            forms.append((method.lower(), names))
        self.assertEqual(forms, MAIN_FORMS)


# ══════════════════════════════════════════════════════════════════════════
# 4. Measured: the page as the browser lays it out
# ══════════════════════════════════════════════════════════════════════════

def _token_names():
    css = read("static/css/sv-tokens.css")
    root = css[css.index(":root {"):css.index("}", css.index(":root {"))]
    return sorted(set(re.findall(r"(--sv-[\w-]+)\s*:", root)))


#: The probes, in the page: colours as numbers, the token set, the census.
PROBE = r"""
window.__pd = (function () {
  function rgba(c) {
    var m = /rgba?\(([^)]+)\)/.exec(c || '');
    if (m) { var p = m[1].split(/[ ,\/]+/).filter(Boolean).map(Number); return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 }; }
    m = /color\(srgb ([\d.e-]+) ([\d.e-]+) ([\d.e-]+)(?: \/ ([\d.]+))?\)/.exec(c || '');
    if (m) return { r: Math.round(m[1] * 255), g: Math.round(m[2] * 255), b: Math.round(m[3] * 255), a: m[4] === undefined ? 1 : Number(m[4]) };
    return null;
  }
  function name(n) {
    return n.tagName.toLowerCase() + (typeof n.className === 'string' && n.className.trim()
      ? '.' + n.className.trim().split(/\s+/).slice(0, 3).join('.') : '') + (n.id ? '#' + n.id : '');
  }
  var TOKENS = null;
  function tokens(names) {
    if (TOKENS) return TOKENS;
    var host = document.createElement('div'); host.style.color = 'rgb(1, 2, 3)';
    var s = document.createElement('span'); host.appendChild(s); document.body.appendChild(host);
    var out = [{ r: 0, g: 0, b: 0, a: 0 }];
    names.forEach(function (n) {
      s.style.color = ''; s.style.color = 'var(' + n + ')';
      var c = rgba(getComputedStyle(s).color);
      if (c && !(c.r === 1 && c.g === 2 && c.b === 3)) out.push(c);
    });
    host.remove(); TOKENS = out; return out;
  }
  function near(a, b) { return Math.abs(a.r - b.r) <= 1 && Math.abs(a.g - b.g) <= 1 && Math.abs(a.b - b.b) <= 1 && Math.abs(a.a - b.a) <= 0.02; }
  function isToken(c, set) {
    if (!c) return true;
    if (c.a === 0) return true;
    return set.some(function (t) { return near(c, t); });
  }
  function lum(c) {
    function ch(v) { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }
    return 0.2126 * ch(c.r) + 0.7152 * ch(c.g) + 0.0722 * ch(c.b);
  }
  function over(top, under) {
    var a = top.a + under.a * (1 - top.a);
    if (a <= 0) return { r: 0, g: 0, b: 0, a: 0 };
    return { r: (top.r * top.a + under.r * under.a * (1 - top.a)) / a,
             g: (top.g * top.a + under.g * under.a * (1 - top.a)) / a,
             b: (top.b * top.a + under.b * under.a * (1 - top.a)) / a, a: a };
  }
  /* The ground a text sits on: the backgrounds from the element up to the
     first opaque one, composited; the void (bg-0) under them all. */
  function ground(el) {
    var layers = [];
    for (var n = el; n && n.nodeType === 1; n = n.parentElement) {
      var c = rgba(getComputedStyle(n).backgroundColor);
      if (c && c.a > 0) { layers.push(c); if (c.a >= 0.999) break; }
    }
    var g = rgba(getComputedStyle(document.documentElement).getPropertyValue('--sv-bg-0').trim() ? 'rgb(4, 11, 7)' : 'rgb(0,0,0)');
    for (var i = layers.length - 1; i >= 0; i--) g = over(layers[i], g);
    return g;
  }
  function contrast(fg, bg) {
    var c = over(fg, bg), a = lum(c) + 0.05, b = lum(bg) + 0.05;
    return a > b ? a / b : b / a;
  }
  function visible(el) {
    return el.checkVisibility && el.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true });
  }
  function ownText(el) {
    var t = '';
    for (var i = 0; i < el.childNodes.length; i++) if (el.childNodes[i].nodeType === 3) t += el.childNodes[i].nodeValue;
    return t.trim();
  }
  function red(c) { return c && c.a >= 0.5 && c.r >= 150 && c.r - Math.max(c.g, c.b) >= 80; }
  var REAL = '.sv-world--live, .sv-venue--live, .sv-armed-pill, .tk-venue--live';
  /* Every visible element under `root` (and its painted pseudo-elements):
     colours off the tokens, text under 11 px, contrast under 4.5, glows,
     red fills outside REAL. */
  /* The popover's and the dialog's own shadows (the tokens), layer by
     layer as the browser computes them: the only outer shadows allowed. */
  var SHADOWS = null;
  function shadows() {
    if (SHADOWS) return SHADOWS;
    var s = document.createElement('div'); document.body.appendChild(s); SHADOWS = [];
    ['--sv-shadow-pop', '--sv-shadow-dialog'].forEach(function (n) {
      s.style.boxShadow = 'var(' + n + ')';
      getComputedStyle(s).boxShadow.split(/,(?![^(]*\))/).forEach(function (l) { SHADOWS.push(l.trim()); });
    });
    s.remove(); return SHADOWS;
  }
  function census(root, names) {
    var set = tokens(names), allowed = shadows(), out = { n: 0, texts: 0, colour: [], small: [], low: [], glow: [], red: [], radius: [] };
    var all = [root].concat(Array.prototype.slice.call(root.querySelectorAll('*')));
    all.forEach(function (el) {
      if (!visible(el)) return;
      if (el.closest('svg') && el.tagName.toLowerCase() !== 'svg') { /* the shapes: fill and stroke only */
        if (!/^(path|rect|circle|ellipse|line|polyline|polygon|text|tspan)$/i.test(el.tagName)) return;
        var s0 = getComputedStyle(el);
        ['fill', 'stroke'].forEach(function (p) { var c = rgba(s0[p]); if (c && !isToken(c, set)) out.colour.push(name(el) + ' ' + p + ' ' + s0[p]); });
        return;
      }
      out.n++;
      ['', '::before', '::after'].forEach(function (pseudo) {
        var s = getComputedStyle(el, pseudo || null);
        if (pseudo && (s.content === 'none' || s.content === 'normal' || s.display === 'none')) return;
        var label = name(el) + pseudo;
        var props = [['color', s.color], ['background-color', s.backgroundColor]];
        ['Top', 'Right', 'Bottom', 'Left'].forEach(function (k) {
          if (parseFloat(s['border' + k + 'Width']) > 0 && s['border' + k + 'Style'] !== 'none') props.push(['border-' + k.toLowerCase() + '-color', s['border' + k + 'Color']]);
        });
        if (s.outlineStyle !== 'none' && parseFloat(s.outlineWidth) > 0) props.push(['outline-color', s.outlineColor]);
        props.forEach(function (p) { var c = rgba(p[1]); if (!isToken(c, set)) out.colour.push(label + ' ' + p[0] + ' ' + p[1]); });
        if (s.textShadow !== 'none') out.glow.push(label + ' text-shadow ' + s.textShadow);
        if (s.filter !== 'none') out.glow.push(label + ' filter ' + s.filter);
        if (s.boxShadow !== 'none' && !el.matches(':focus')) {   /* a focus ring is the Eye's, allowed */
          s.boxShadow.split(/,(?![^(]*\))/).forEach(function (layer) {
            layer = layer.trim();
            if (allowed.indexOf(layer) >= 0) return;
            var px = (layer.replace(/rgba?\([^)]+\)/, '').match(/-?[\d.]+px/g) || []).map(parseFloat);
            var c = rgba(layer);
            if (!isToken(c, set)) out.colour.push(label + ' box-shadow ' + layer);
            if (px[2] && !/inset/.test(layer) && !el.closest('.sv-dialog, .lvl-dlg')) out.glow.push(label + ' box-shadow ' + layer);
            if (px[2] && /inset/.test(layer)) out.glow.push(label + ' box-shadow ' + layer);
            if (red(c) && !(/inset/.test(layer) && !px[2] && el.closest('.sv-row--live'))) out.red.push(label + ' box-shadow ' + layer);
          });
        }
        var bg = rgba(s.backgroundColor);
        if (red(bg) && !el.matches(REAL)) out.red.push(label + ' background ' + s.backgroundColor);
        var rad = parseFloat(s.borderTopLeftRadius);
        if ([0, 2, 4, 6].indexOf(rad) < 0 && rad < 999 && !(rad >= el.getBoundingClientRect().height / 2 - 0.5)) out.radius.push(label + ' ' + s.borderTopLeftRadius);
        var text = pseudo ? s.content.replace(/^["']|["']$/g, '') : ownText(el);
        if (text && text !== 'none') {
          out.texts++;
          if (parseFloat(s.fontSize) < 11) out.small.push(label + ' ' + s.fontSize + ' "' + text.slice(0, 20) + '"');
          var fg = rgba(s.color);
          if (fg && fg.a > 0) {
            var k = contrast(fg, ground(el));
            if (k < 4.5) out.low.push(label + ' ' + k.toFixed(2) + ' "' + text.slice(0, 20) + '"');
          }
        }
      });
    });
    return out;
  }
  function box(sel) { var e = document.querySelector(sel); if (!e) return null; var r = e.getBoundingClientRect(); return { x: r.left, y: r.top, w: r.width, h: r.height }; }
  function boxes(sel) { return Array.prototype.map.call(document.querySelectorAll(sel), function (e) { var r = e.getBoundingClientRect(); return { x: r.left, y: r.top, w: r.width, h: r.height }; }); }
  function frame() { return new Promise(function (r) { requestAnimationFrame(function () { requestAnimationFrame(r); }); }); }
  /* A still page: what plays once (the page's entrance) at its end, what
     loops held at its start, then laid out afresh. */
  function settle(round) {
    var moving = 0;
    document.getAnimations().forEach(function (a) {
      var t = a.effect && a.effect.getComputedTiming();
      if (t && t.iterations === Infinity) { a.pause(); a.currentTime = 0; }
      else if (a.playState !== 'finished') { moving++; try { a.finish(); } catch (e) {} }
    });
    return frame().then(function () { return moving && (round || 0) < 6 ? settle((round || 0) + 1) : 0; });
  }
  return { rgba: rgba, census: census, box: box, boxes: boxes, frame: frame, settle: settle, name: name };
})();
"""


def _file(markup, scripts=(), before=""):
    """The rendered page as a file Chromium opens on its own (the magic
    layer's _file_page: scripts dropped, no network), with the named
    static scripts put back as they ship; `before` runs ahead of them."""
    from tests.test_magic_layer import _file_page
    return _file_page(markup, scripts=scripts, before=before)


def _loaded(client, url="/positions/"):
    """/positions/ as the operator has it once loaded: the htmx analytics
    panel swapped in where the page asks for it."""
    page = _get(client, url)
    body = _get(client, "/htmx/metrics/positions/")
    return re.sub(r'(<div class="sv-metrics-wrapper"[^>]*>)(</div>)',
                  lambda m: m.group(1) + body + m.group(2), page, count=1)


def _donut_script(client):
    """The donut partial's own script, as the htmx panel ships it: the file
    page drops inline scripts, and without this one the analytics' donuts
    and their legend swatches are never painted (the review's hole: a red
    swatch the census could not see)."""
    body = _get(client, "/htmx/metrics/positions/")
    m = re.search(r"<script>\s*(\(function \(\) \{\s*if \(!window\.svRenderDonuts\).*?)</script>",
                  body, re.S)
    return m.group(1) if m else ""


#: The desk's measured scripts, as the page ships them.
DESK_SCRIPTS = ("sv-overlay.js", "sv-level-edit.js", "sv-close-advice.js",
                "sv-positions.js")

#: The review's checks at rest (2026-11-13), as one probe: `% names`.
REVIEW_PROBE = r"""(async function () {
  var N = %s, out = {};
  function tok(n) { var s = document.createElement('span'); s.style.color = 'var(' + n + ')';
    document.body.appendChild(s); var c = getComputedStyle(s).color; s.remove(); return c; }
  out.ink = { ink1: tok('--sv-ink-1'), ink2: tok('--sv-ink-2'), ink3: tok('--sv-ink-3'), up: tok('--sv-up'),
              down: tok('--sv-down'), eye: tok('--sv-eye'), demo: tok('--sv-demo') };
  function dg(pv) { var d = pv && pv.querySelector('.pd-dg'); return d ? d.textContent : null; }
  /* the open rows: P&L and R in their tones; an estimate in ink, no arrow */
  out.rows = Array.prototype.map.call(document.querySelectorAll('.pd-table tbody tr[data-sv-position-row]'), function (tr) {
    var pv = tr.querySelector('td[data-label="P&L"] .pd-pv'), r = tr.querySelector('td[data-label="R"]');
    return { sym: tr.getAttribute('data-pos-symbol'), est: !!(pv && pv.querySelector('.pd-est')),
             pnl: pv ? getComputedStyle(pv).color : '', arrow: dg(pv),
             r: r ? getComputedStyle(r).color : '', rText: r ? r.textContent.trim() : '' };
  });
  out.kpi = Array.prototype.map.call(document.querySelectorAll('.pd-kc[data-pd-world]'), function (kc) {
    var pv = kc.querySelector('.pd-pv');
    return { world: kc.getAttribute('data-pd-world'), est: !!(pv && pv.querySelector('.pd-est')),
             color: pv ? getComputedStyle(pv).color : '', arrow: dg(pv) };
  });
  out.c24 = Array.prototype.map.call(document.querySelectorAll('.pd-tc tbody tr'), function (tr) {
    var pv = tr.querySelector('.pd-pv'), r = tr.querySelectorAll('td')[7];
    return { pnl: pv ? getComputedStyle(pv).color : '', r: r ? getComputedStyle(r).color : '', rText: r ? r.textContent.trim() : '' };
  });
  out.c30 = Array.prototype.map.call(document.querySelectorAll('.pd-t30:not(.pd-hb) tbody tr'), function (tr) {
    var r = tr.querySelectorAll('td')[2]; return { r: getComputedStyle(r).color, rText: r.textContent.trim() };
  });
  /* at the broker: the sides and the P&L in their colours, quantities as read */
  out.broker = Array.prototype.map.call(document.querySelectorAll('.bkp-table tbody tr'), function (tr) {
    var side = tr.querySelector('[data-label="Side"]'), pnl = tr.querySelector('[data-label="Unreal P&L"]'),
        qty = tr.querySelector('[data-label="Qty"]');
    return { side: side.textContent.trim(), sideColor: getComputedStyle(side).color,
             pnl: pnl.textContent.trim(), pnlColor: getComputedStyle(pnl).color, qty: qty.textContent.trim() };
  });
  /* no text on the void: every visible word of the desk on an opaque ground */
  var desk = document.querySelector('.pd-desk');
  out.voidText = [];
  var tw = document.createTreeWalker(desk, NodeFilter.SHOW_TEXT), n;
  while ((n = tw.nextNode())) {
    if (!n.nodeValue.trim()) continue;
    var el = n.parentElement;
    if (!el || !el.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })) continue;
    var opaque = false;
    for (var a = el; a; a = a.parentElement) {
      var c = __pd.rgba(getComputedStyle(a).backgroundColor);
      if (c && c.a >= 0.99) { opaque = true; break; }
      if (a === desk) break;
    }
    if (!opaque) out.voidText.push(n.nodeValue.trim().slice(0, 48));
  }
  /* the eToro line: inside the book card, opened on its own opaque ground */
  var pop = document.getElementById('pdEtoro'), btn = document.querySelector('.pd-acct-btn');
  out.etoro = { inCard: !!(pop && pop.closest('.pd-kgrp')), btn: !!btn };
  if (pop && btn) {
    btn.click(); await __pd.frame();
    out.etoro.open = pop.matches(':popover-open');
    out.etoro.bg = __pd.rgba(getComputedStyle(pop).backgroundColor);
    out.etoro.text = pop.textContent.replace(/\s+/g, ' ').trim();
    out.etoro.census = __pd.census(pop, N);
    try { pop.hidePopover(); } catch (e) {}
  }
  /* the SYMBOL label over the symbols; the symbol plain mono ink-1 */
  function textLeft(el) {
    var w = document.createTreeWalker(el, NodeFilter.SHOW_TEXT), t;
    while ((t = w.nextNode())) { if (t.nodeValue.trim()) { var r = document.createRange(); r.selectNodeContents(t); return r.getBoundingClientRect().left; } }
    return null;
  }
  var symTh = Array.prototype.find.call(document.querySelectorAll('.pd-table thead th'), function (th) { return th.textContent.trim() === 'Symbol'; });
  var sym = document.querySelector('.pd-table tbody .pos-sym-link, .pd-table tbody .pos-sym-plain');
  out.symAlign = symTh && sym ? textLeft(symTh) - textLeft(sym) : null;
  /* the detail row of EURUSD, opened: no chip again, nothing pinned, the Orc line and one line */
  var eur = document.querySelector('.pd-table tr[data-pos-symbol="EURUSD"]'), disc = eur.querySelector('.pd-disc');
  disc.click(); await __pd.frame();
  var det = document.getElementById(disc.getAttribute('aria-controls'));
  var cells = det.querySelectorAll(':scope > td');
  out.det = { chips: det.querySelectorAll('.sv-world').length, lastSpan: cells[cells.length - 1].getAttribute('colspan'),
              sticky: Array.prototype.filter.call(cells, function (td) { return getComputedStyle(td).position === 'sticky'; }).length,
              line2: det.querySelector('.pd-det2').getBoundingClientRect().height,
              lh: parseFloat(getComputedStyle(det.querySelector('.pd-det2')).lineHeight) || 16 };
  disc.click(); await __pd.frame();
  document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  if (document.activeElement && document.activeElement.blur) document.activeElement.blur();
  /* the analytics: no Eye green and no DEMO gold on a data shape, the donuts drawn */
  var bad = [__pd.rgba(out.ink.eye), __pd.rgba(out.ink.demo)];
  out.shapes = [];
  Array.prototype.forEach.call(document.querySelectorAll('.pd-analytics svg rect, .pd-analytics svg circle, .pd-analytics svg path, .pd-analytics svg line, .pd-analytics .oc-donut-legend-swatch'), function (el) {
    var cs = getComputedStyle(el);
    /* what paints: a shape's fill and stroke, a swatch's ground */
    var paints = el.closest('svg') ? [['fill', cs.fill], ['stroke', cs.stroke]] : [['background', cs.backgroundColor]];
    paints.forEach(function (p) {
      var c = __pd.rgba(p[1]); if (!c || c.a === 0) return;
      bad.forEach(function (b) { if (Math.abs(c.r - b.r) <= 2 && Math.abs(c.g - b.g) <= 2 && Math.abs(c.b - b.b) <= 2) out.shapes.push(__pd.name(el) + ' ' + p[0] + ' ' + p[1]); });
    });
  });
  out.donuts = document.querySelectorAll('.pd-analytics .oc-donut-seg').length;
  out.swatches = Array.prototype.map.call(document.querySelectorAll('.pd-analytics .oc-donut-legend-swatch'), function (s) { return getComputedStyle(s).backgroundColor; });
  out.sides = Array.prototype.map.call(document.querySelectorAll('.pd-analytics .oc-mini-side'), function (s) { return [s.textContent.trim(), getComputedStyle(s).color]; });
  /* TAKE TRADE (B6's money control) opens on this page too: the page's sheet changes nothing inside it */
  var host = document.createElement('div');
  host.className = 'sv-dialog sz-dialog is-open';
  host.innerHTML = '<div class="sv-dialog-head"><span class="sv-dialog-title">TAKE TRADE</span><button class="sv-dialog-x">x</button></div>'
    + '<div class="sv-dialog-msg">m</div><div class="sv-dialog-detail">d</div>'
    + '<div class="sv-dialog-facts"><div class="sv-dialog-fact"><span class="lbl">Size</span><span>1</span></div></div>'
    + '<div class="sz-warn sz-warn--book"><b>BOOK</b> text</div>'
    + '<label class="sv-dialog-confirm-text">PIN <input type="password"></label>'
    + '<div class="sv-dialog-foot"><button class="sv-dialog-btn">Cancel</button><button class="sv-dialog-btn sv-dialog-btn--go" disabled>TAKE TRADE</button></div>';
  document.body.appendChild(host);
  function look() { return Array.prototype.map.call(host.querySelectorAll('*'), function (e) { var c = getComputedStyle(e);
    return [e.className, c.fontSize, c.fontFamily, c.color, c.backgroundColor, c.boxShadow, c.textTransform, c.opacity,
            c.borderTopColor, c.letterSpacing, c.padding].join('|'); }); }
  var withSheet = look();
  var sheet = Array.prototype.find.call(document.styleSheets, function (s) { return s.href && /sv-positions\.css$/.test(s.href); });
  sheet.disabled = true; var without = look(); sheet.disabled = false; host.remove();
  out.takeTrade = withSheet.filter(function (v, i) { return v !== without[i]; });
  return out;
})()"""

#: The controls whose focus ring the review read (F8): the desk's own and
#: the money controls on it.
RING_SELECTORS = (".pd-table .pd-disc", ".pd-table .pos-sym-link", ".pd-table .lvl-edit",
                  ".pd-table [data-sv-close-trade]", "#svCloseAll", ".pd-seg-btn",
                  ".pd-filter-btn", ".pd-acct-btn", ".pd-lk")


#: The board's lower row at its 1136 px desk (Desk2.dc.html): the 24 hours,
#: the REAL exposure, the 30 days, and the desk width from which the three
#: share one line.
BOARD_LOWER = (590, 248, 274)
LOWER_ONE_LINE = 1100


def _lower_row_checks(test, low, desk, gap):
    """The lower row against the board, whatever the frame around it."""
    test.assertEqual(len(low), 3)
    c24, ex, c30 = low
    for c in low:
        test.assertGreaterEqual(c["h"], 298 - 0.5, c)
    if desk["w"] >= LOWER_ONE_LINE:
        test.assertTrue(all(abs(c["y"] - c24["y"]) < 0.5 for c in low), low)
        test.assertGreaterEqual(ex["w"], BOARD_LOWER[1] - 0.5)
        test.assertGreaterEqual(c30["w"], BOARD_LOWER[2] - 0.5)
        test.assertGreater(c24["w"], c30["w"])
        test.assertAlmostEqual(c24["w"] + ex["w"] + c30["w"] + 2 * gap, desk["w"], delta=1)
        if desk["w"] >= sum(BOARD_LOWER) + 2 * gap:
            # the board's proportions, at its desk and wider
            test.assertAlmostEqual(ex["w"] / c30["w"], BOARD_LOWER[1] / BOARD_LOWER[2], delta=0.01)
            test.assertAlmostEqual(c24["w"] / ex["w"], BOARD_LOWER[0] / BOARD_LOWER[1], delta=0.03)
    elif desk["w"] >= 640:
        test.assertAlmostEqual(c24["w"], desk["w"], delta=0.5)
        test.assertAlmostEqual(ex["y"], c30["y"], delta=0.5)
        test.assertAlmostEqual(ex["y"], c24["y"] + c24["h"] + gap, delta=0.5)
        test.assertAlmostEqual(ex["w"], c30["w"], delta=0.5)
        test.assertAlmostEqual(ex["h"], c30["h"], delta=0.5)
        test.assertAlmostEqual(c30["x"] - (ex["x"] + ex["w"]), gap, delta=0.5)


@unittest.skipUnless(CHROME, "no headless Chromium on this machine")
class DeskMeasuredTests(TestCase):
    """/positions/ at 1440 x 900, dark, Magic, the rail closed: the board's
    structure and geometry, and the census of every visible element."""

    maxDiff = None

    @classmethod
    def setUpTestData(cls):
        from tests.test_magic_layer import _Browser
        _user, client = desk_client("desk_measured")
        page = _file(_loaded(client), scripts=DESK_SCRIPTS, before=_donut_script(client))
        names = json.dumps(_token_names())
        b = _Browser({"desk": page}, "sv-desk-")
        try:
            sid = b.tab(1440, 900)
            b.open(sid, "desk", PROBE)
            cls.got = b.js(sid, "(async function () {"
                           " document.body.setAttribute('data-sv-ambience', 'magic'); await __pd.settle();"
                           " var N = %s, out = {};"
                           " var desk = document.querySelector('.pd-desk');"
                           " out.desk = __pd.box('.pd-desk');"
                           " out.kpis = __pd.boxes('.pd-kpis > .pd-card');"
                           " out.khead = __pd.boxes('.pd-khead');"
                           " out.chead = __pd.box('.pd-pos .pd-chead');"
                           " out.pos = __pd.box('.pd-pos');"
                           " out.lower = __pd.boxes('.pd-lower > .pd-card');"
                           " out.lowerGap = parseFloat(getComputedStyle(document.querySelector('.pd-lower')).columnGap);"
                           " var wrap = document.querySelector('.pd-pos .table-wrapper');"
                           " out.fit = wrap ? [wrap.scrollWidth, wrap.clientWidth] : null;"
                           " out.th = __pd.boxes('.pd-table thead th').map(function (b) { return b.h; });"
                           " out.rows = Array.prototype.map.call(document.querySelectorAll('.pd-table tbody tr[data-sv-position-row]'), function (r) { return r.getBoundingClientRect().height; });"
                           " out.close = __pd.boxes('.pd-table [data-sv-close-trade]');"
                           " out.syms = Array.prototype.map.call(document.querySelectorAll('.pd-table .pos-sym-link, .pd-table .pos-sym-plain'), function (s) { var r = s.getClientRects(); return [s.textContent, r.length]; });"
                           " out.closeAll = (function () { var b = document.getElementById('svCloseAll'); return b ? [getComputedStyle(b, '::before').content, b.className] : null; })();"
                           " out.overflowX = document.documentElement.scrollWidth - document.documentElement.clientWidth;"
                           " out.titles = Array.prototype.map.call(document.querySelectorAll('.pd-desk .pd-title'), function (t) { return getComputedStyle(t).fontFamily.split(',')[0].replace(/\"/g, ''); });"
                           " out.figures = Array.prototype.filter.call(document.querySelectorAll('.pd-desk .pd-kv, .pd-desk td.num, .pd-desk .pd-pv'), function (e) { return /\\d/.test(e.textContent); }).map(function (e) { return getComputedStyle(e).fontFamily.split(',')[0].replace(/\"/g, ''); });"
                           " out.rest = __pd.census(desk, N);"
                           " return out; })()" % names)
            # the review's checks at rest (2026-11-13): tones, the void, the
            # eToro line, the symbol's label, the open detail, the analytics'
            # data shapes, TAKE TRADE left alone
            cls.review = b.js(sid, REVIEW_PROBE % names)
            # every focus ring on the desk: ink, never the Eye's light
            cls.rings = {}
            for sel in RING_SELECTORS:
                n = b.force(sid, sel, ["focus-visible"])
                cls.rings[sel] = [n, b.js(sid, "(function () { var e = document.querySelector(%s);"
                                                " if (!e) return null; var c = getComputedStyle(e);"
                                                " return [c.outlineStyle, c.outlineColor]; })()" % json.dumps(sel))]
                b.force(sid, sel, [])
            # the REAL edge, hovered and focused
            n = b.force(sid, ".pd-table tr[data-sv-position-row].sv-row--live", ["hover", "focus-within"])
            cls.edge = [n, b.js(sid, "Array.prototype.map.call(document.querySelectorAll('.pd-table tr[data-sv-position-row].sv-row--live > td:first-child'), function (td) { return getComputedStyle(td).boxShadow; })")]
            b.force(sid, ".pd-table tr[data-sv-position-row].sv-row--live", [])
            # the keys: J J moves down twice, K up once, Enter opens the
            # focused row's Orc line; nothing is clicked, nothing closes
            cls.keys = b.js(sid, "(async function () {"
                            " function key(k) { document.dispatchEvent(new KeyboardEvent('keydown', { key: k, bubbles: true })); }"
                            " var rows = document.querySelectorAll('.pd-table tbody tr[data-sv-position-row]');"
                            " key('j'); key('j'); var a = Array.prototype.indexOf.call(rows, document.querySelector('.pd-table tr.is-focus'));"
                            " key('k'); var b2 = Array.prototype.indexOf.call(rows, document.querySelector('.pd-table tr.is-focus'));"
                            " key('Enter'); await __pd.frame();"
                            " var row = rows[b2], disc = row.querySelector('.pd-disc'), det = document.getElementById(disc.getAttribute('aria-controls'));"
                            " var opened = [disc.getAttribute('aria-expanded'), det.hidden];"
                            " var inp = document.createElement('input'); document.body.appendChild(inp); inp.focus();"
                            " inp.dispatchEvent(new KeyboardEvent('keydown', { key: 'j', bubbles: true }));"
                            " var stayed = Array.prototype.indexOf.call(rows, document.querySelector('.pd-table tr.is-focus'));"
                            " inp.remove();"
                            " var closing = document.querySelectorAll('.sv-dialog').length;"
                            " return { a: a, b: b2, opened: opened, stayed: stayed, dialogs: closing }; })()")
            # the open disclosure, measured, and kept across a live swap
            cls.disc = b.js(sid, "(async function () {"
                            " var N = %s;"
                            " var det = document.querySelector('.pd-det:not([hidden])');"
                            " var census = __pd.census(det, N);"
                            " var region = document.querySelector('[data-sv-live=\"pos-open\"]');"
                            " var key = det.getAttribute('data-pd-key');"
                            " region.innerHTML = region.innerHTML.replace(/(<tr class=\"pd-det[^\"]*\"[^>]*?)(?: hidden=\"\")?>/g, function (m, a) { return /hidden/.test(m) ? m : m; });"
                            " var fresh = region.innerHTML; region.innerHTML = fresh;"
                            " document.querySelectorAll('.pd-det').forEach(function (d) { d.hidden = true; });"
                            " document.dispatchEvent(new CustomEvent('sv:live-swapped', { detail: { region: 'pos-open', node: region } }));"
                            " await __pd.frame();"
                            " var again = document.querySelector('.pd-det[data-pd-key=\"' + key + '\"]');"
                            " return { census: census, kept: !!again && !again.hidden, h: det.getBoundingClientRect().height }; })()" % names)
            # the selection bar: one box ticked
            cls.sel = b.js(sid, "(async function () {"
                           " var N = %s; var box = document.querySelector('.pd-table input[data-sv-select-trade]');"
                           " box.click(); await __pd.frame();"
                           " var bar = document.querySelector('[data-sv-select-bar]');"
                           " var out = { shown: !bar.hidden, census: __pd.census(bar, N) };"
                           " box.click(); await __pd.frame(); return out; })()" % names)
            # the close dialog, live (PIN) and paper, as closeFlow asks SV.overlay
            cls.dialogs = {}
            for kind, live in (("live", True), ("paper", False)):
                cls.dialogs[kind] = b.js(sid, "(async function () {"
                                         " var N = %s;"
                                         " SV.overlay.confirm({ title: 'Close this position?',"
                                         "   message: %s,"
                                         "   facts: [['Closing', 'BUY 20000 EURUSD'], ['Entry', '1.08420'], ['Mark now', '1.08745'],"
                                         "           ['Books at', '1.08745'], ['Realises', '+65.00  ·  +1.25R'], ['Venue', %s]],"
                                         "   danger: true, secretLabel: %s, confirmLabel: %s });"
                                         " await __pd.frame(); await new Promise(function (r) { setTimeout(r, 300); });"
                                         " var d = document.querySelector('.sv-dialog.is-open');"
                                         " var out = { census: __pd.census(d, N), pin: !!d.querySelector('input[type=password][inputmode=numeric]'),"
                                         "   focus: document.activeElement && document.activeElement.getAttribute('data-role'),"
                                         "   order: Array.prototype.map.call(d.querySelectorAll('button, input'), function (e) { return e.getAttribute('data-role') || e.className; }),"
                                         "   ok: d.querySelector('[data-role=ok]').textContent,"
                                         "   ring: document.activeElement ? getComputedStyle(document.activeElement).boxShadow : '' };"
                                         " SV.overlay.close(d); await new Promise(function (r) { setTimeout(r, 300); });"
                                         " return out; })()"
                                         % (names,
                                            json.dumps("This flattens a LIVE position at the broker. It cannot be undone, and re-entering costs the round trip again." if live else "This books the exit on the paper venue and grades the trade."),
                                            json.dumps("LIVE" if live else "PAPER"),
                                            "'Trading PIN'" if live else "undefined",
                                            json.dumps("CLOSE LIVE POSITION" if live else "CLOSE POSITION")))
            # the level editor on a REAL row (its PIN field) at rest
            cls.level = b.js(sid, "(async function () {"
                             " var N = %s; var btn = document.querySelector('.pd-table tr.sv-row--live .lvl-edit');"
                             " btn.click(); await __pd.frame();"
                             " var d = document.querySelector('.lvl-dlg');"
                             " var out = { census: __pd.census(d, N), labels: Array.prototype.map.call(d.querySelectorAll('label'), function (l) { return l.textContent; }),"
                             "   buttons: Array.prototype.map.call(d.querySelectorAll('button'), function (x) { return x.textContent; }),"
                             "   ring: document.activeElement ? getComputedStyle(document.activeElement).boxShadow : '',"
                             "   selection: document.activeElement ? getComputedStyle(document.activeElement, '::selection').backgroundColor : '' };"
                             " return out; })()" % names)
        finally:
            b.close()

    def _clean(self, census, where):
        for key in ("colour", "small", "low", "glow", "red", "radius"):
            with self.subTest(where=where, check=key):
                self.assertEqual(census[key], [])

    def test_the_kpi_strip_is_two_cards_of_the_board_s_height(self):
        k = self.got["kpis"]
        self.assertEqual(len(k), 2)
        self.assertAlmostEqual(k[0]["y"], k[1]["y"], delta=0.5)
        self.assertAlmostEqual(k[0]["w"], k[1]["w"], delta=1)
        self.assertAlmostEqual(k[1]["x"] - (k[0]["x"] + k[0]["w"]), 12, delta=0.5)
        for card in k:
            self.assertAlmostEqual(card["h"], 104, delta=1)
        for h in self.got["khead"]:
            self.assertAlmostEqual(h["h"], 28, delta=0.5)

    def test_the_open_book_card_and_its_rows(self):
        self.assertAlmostEqual(self.got["chead"]["h"], 40, delta=0.5)
        self.assertTrue(all(abs(h - 28) <= 0.5 for h in self.got["th"]), self.got["th"])
        self.assertEqual(len(self.got["rows"]), 6)
        for h in self.got["rows"]:
            self.assertAlmostEqual(h, 36, delta=0.5)
        scroll, client = self.got["fit"]
        self.assertLessEqual(scroll, client)
        self.assertEqual(self.got["overflowX"], 0)
        pos = self.got["pos"]
        for b in self.got["close"]:
            self.assertLessEqual(b["x"] + b["w"], pos["x"] + pos["w"])
            self.assertLessEqual(b["x"] + b["w"], 1440)
        for sym, lines in self.got["syms"]:
            self.assertEqual(lines, 1, sym)

    def test_close_all_carries_the_square_and_the_stop_look(self):
        content, cls_ = self.got["closeAll"]
        self.assertEqual(content, '"■"')
        self.assertIn("btn-stop", cls_)

    def test_the_lower_row_is_three_cards_in_the_board_s_proportions(self):
        """The board's row, 590 : 248 : 274 in its 1136 px desk (updated
        deliberately after the review of 2026-11-13: S0's 300 px floor came
        from the old asset-class card, and the board the operator approved,
        "amazing work, bravo, I need it fast!!", holds its tables whole at
        248 and 274): a desk 1100 px wide or more holds the three on one
        line in those proportions; narrower, the 24 hours runs the full
        width above the exposure and the 30 days, side by side."""
        _lower_row_checks(self, self.got["lower"], self.got["desk"], self.got["lowerGap"])

    def test_titles_in_the_display_face_and_figures_in_the_number_face(self):
        self.assertTrue(self.got["titles"])
        self.assertEqual(set(self.got["titles"]), {"Orbitron"})
        self.assertTrue(self.got["figures"])
        self.assertEqual(set(self.got["figures"]), {"JetBrains Mono"})

    def test_nothing_on_the_page_is_old(self):
        self.assertGreater(self.got["rest"]["texts"], 150)
        self._clean(self.got["rest"], "page")

    def test_the_real_edge_holds_under_hover_and_focus(self):
        n, shadows = self.edge
        self.assertEqual(n, 3)
        for s in shadows:
            self.assertRegex(s, r"rgb\(204, 58, 64\) 3px 0px 0px 0px inset")

    def test_the_keys_move_and_open_and_never_close(self):
        k = self.keys
        self.assertEqual((k["a"], k["b"]), (1, 0))
        self.assertEqual(k["opened"], ["true", False])
        self.assertEqual(k["stayed"], 0)
        self.assertEqual(k["dialogs"], 0)

    def test_the_open_line_is_on_the_tokens_and_survives_a_swap(self):
        self.assertGreater(self.disc["census"]["texts"], 8)
        self._clean(self.disc["census"], "disclosure")
        self.assertTrue(self.disc["kept"])

    def test_the_selection_bar(self):
        self.assertTrue(self.sel["shown"])
        self.assertGreater(self.sel["census"]["texts"], 3)
        self._clean(self.sel["census"], "selection bar")

    def test_the_close_dialog_live_and_paper(self):
        live, paper = self.dialogs["live"], self.dialogs["paper"]
        self.assertTrue(live["pin"])
        self.assertFalse(paper["pin"])
        self.assertEqual(live["focus"], "secret")
        self.assertEqual(live["ok"], "CLOSE LIVE POSITION")
        self.assertEqual(paper["ok"], "CLOSE POSITION")
        self.assertEqual(live["order"][-2:], ["cancel", "ok"])
        for kind, got in self.dialogs.items():
            self.assertGreater(got["census"]["texts"], 6, kind)
            self._clean(got["census"], "close dialog " + kind)

    def test_the_level_editor(self):
        self.assertEqual(self.level["labels"], ["STOP", "TARGET", "TRADING PIN"])
        self.assertEqual(self.level["buttons"], ["CANCEL", "SAVE"])
        self.assertGreater(self.level["census"]["texts"], 4)
        self._clean(self.level["census"], "level editor")

    # ── The review (2026-11-13): each fix held, measured ─────────────────

    def test_r_takes_the_tone_of_its_row_s_pnl(self):
        """F3: R was ink-1 on every row, the more specific cell rule beating
        the tone; the board draws R in up and down."""
        ink = self.review["ink"]
        rows = [r for r in self.review["rows"] if not r["est"] and r["rText"] not in ("", "—")]
        self.assertTrue(rows)
        for r in rows:
            with self.subTest(row=r["sym"]):
                self.assertIn(r["r"], (ink["up"], ink["down"]), r)
                self.assertEqual(r["r"], r["pnl"], r)
        for r in self.review["c24"]:
            with self.subTest(closed=r["rText"]):
                self.assertEqual(r["r"], r["pnl"], r)
        for r in self.review["c30"]:
            if r["rText"].startswith("+"):
                self.assertEqual(r["r"], ink["up"], r)
            elif r["rText"].startswith("-"):
                self.assertEqual(r["r"], ink["down"], r)

    def test_an_estimate_is_drawn_in_ink_with_no_arrow(self):
        """F12: the board draws an estimate as "≈ +6.60" in ink-1 with an
        empty arrow slot, so it never reads as a measured gain; its R one
        step down (ink-2)."""
        ink = self.review["ink"]
        est = [r for r in self.review["rows"] if r["est"]]
        # The two DEMO rows eToro's own list does not carry in this book.
        self.assertEqual(sorted(r["sym"] for r in est), ["BTCUSD", "NAS100"])
        for r in est:
            with self.subTest(row=r["sym"]):
                self.assertEqual(r["pnl"], ink["ink1"])
                self.assertEqual(r["arrow"], "")
                self.assertEqual(r["r"], ink["ink2"])
        kpi = {k["world"]: k for k in self.review["kpi"]}
        self.assertTrue(kpi["demo"]["est"])
        self.assertEqual((kpi["demo"]["color"], kpi["demo"]["arrow"]), (ink["ink1"], ""))
        self.assertFalse(kpi["live"]["est"])
        self.assertEqual((kpi["live"]["color"], kpi["live"]["arrow"]), (ink["up"], "▲"))

    def test_at_the_broker_sides_and_pnl_in_their_colours(self):
        """F19: SIDE and UNREAL P&L were ink-1 (the cell rule again); the
        quantity read "1.5000"."""
        ink = self.review["ink"]
        rows = {r["side"] + r["qty"]: r for r in self.review["broker"]}
        self.assertEqual(sorted(rows), ["BUY20,000", "BUY4", "SELL1.5"])
        for r in self.review["broker"]:
            with self.subTest(row=r):
                self.assertEqual(r["sideColor"], ink["up"] if r["side"] == "BUY" else ink["down"])
                self.assertEqual(r["pnlColor"], ink["down"] if r["pnl"].startswith("-") else ink["up"])

    def test_no_word_or_figure_stands_on_the_void(self):
        """F4: the eToro used line sat between the cards with no ground of
        its own, where the Eye's light and the embers pass."""
        self.assertEqual(self.review["voidText"], [])

    def test_the_etoro_line_opens_in_the_book_card_on_its_own_ground(self):
        e = self.review["etoro"]
        self.assertTrue(e["inCard"], e)
        self.assertTrue(e["btn"], e)
        self.assertTrue(e.get("open"), e)
        self.assertGreaterEqual(e["bg"]["a"], 0.99)
        self.assertIn("ETORO USED", e["text"])
        self.assertIn("6,051.51 available", e["text"])
        self.assertIn("At that read", e["text"])
        self._clean(e["census"], "eToro line")

    def test_the_symbol_label_stands_over_the_symbols(self):
        """F10: SYMBOL sat 32 px left of the symbols, over the chevrons."""
        self.assertIsNotNone(self.review["symAlign"])
        self.assertLessEqual(abs(self.review["symAlign"]), 1.0)

    def test_the_open_detail_row_is_the_orc_line_and_one_line(self):
        """F9: the detail row repeated the REAL MONEY chip, wrapped to three
        lines and let the pinned CLOSE column's edge run through it."""
        d = self.review["det"]
        self.assertEqual(d["chips"], 0)
        self.assertIsNotNone(d["lastSpan"])
        self.assertEqual(d["sticky"], 0)
        self.assertLessEqual(d["line2"], d["lh"] * 1.5)

    def test_the_analytics_draw_data_never_in_the_eye_s_green_or_demo_s_gold(self):
        """F6 and contract F3: gains were the Eye's green, the donuts took
        the old order (gold among them) and two legend swatches were solid
        coral; the census now sees the donuts painted."""
        self.assertGreater(self.review["donuts"], 0)
        self.assertEqual(self.review["shapes"], [])
        for side, colour in self.review["sides"]:
            with self.subTest(side=side):
                self.assertRegex(side, r"^[▲▼] (LONG|SHORT)$")
                self.assertEqual(colour, self.review["ink"]["ink2"])

    def test_take_trade_is_left_to_its_own_look(self):
        """Contract F2: the close dialog's restyle had no page scope and
        restyled TAKE TRADE (B6's money control) when it opened here."""
        self.assertEqual(self.review["takeTrade"], [])

    def test_every_focus_ring_on_the_desk_is_ink(self):
        """F8: every focused control drew the Eye's 2 px ring, CLOSE and the
        PIN field among them; the board draws the keys' frame in ink, and
        money controls never take the Eye's green."""
        eye = self.review["ink"]["eye"]
        for sel, (n, ring) in self.rings.items():
            if not n:
                continue
            with self.subTest(control=sel):
                self.assertEqual(ring[0], "solid", ring)
                self.assertIn(ring[1], (self.review["ink"]["ink1"], self.review["ink"]["ink2"]), ring)
        self.assertNotIn(eye.replace("rgb(", "").rstrip(")"), self.dialogs["live"]["ring"])
        self.assertTrue(self.dialogs["live"]["ring"] and self.dialogs["live"]["ring"] != "none")
        self.assertNotIn(eye.replace("rgb(", "").rstrip(")"), self.level["ring"])
        self.assertTrue(self.level["ring"] and self.level["ring"] != "none")

    def test_the_level_editor_selects_in_the_tokens(self):
        """F16: the pre-selected stop showed the browser's own blue."""
        self.assertEqual(self.level["selection"], "rgb(27, 44, 35)")   # --sv-bg-4


#: The widths the review measured (F1): the frame's tiers raise the cell
#: text to 14 px at 1680 and 15 px at 2200.
WIDTHS = ((1280, 800), (1440, 900), (1680, 1050), (1920, 1080), (2560, 1440))

WIDTHS_PROBE = r"""(async function () {
  document.body.setAttribute('data-sv-ambience', 'magic'); await __pd.settle();
  if (document.fonts && document.fonts.ready) await document.fonts.ready;
  var out = { vw: window.innerWidth, desk: __pd.box('.pd-desk') };
  var wrap = document.querySelector('.pd-pos .table-wrapper');
  out.fit = wrap ? [wrap.scrollWidth, wrap.clientWidth] : null;
  function texts(el) {
    var rects = [], w = document.createTreeWalker(el, NodeFilter.SHOW_TEXT), t;
    while ((t = w.nextNode())) {
      if (!t.nodeValue.trim()) continue;
      var p = t.parentElement;
      if (!p || p.closest('.pd-sr, [hidden]') || !p.checkVisibility()) continue;
      var r = document.createRange(); r.selectNodeContents(t);
      Array.prototype.forEach.call(r.getClientRects(), function (q) { if (q.width > 0) rects.push(q); });
    }
    return rects;
  }
  /* every cell's words inside the cell; PRICED BY may shorten its source,
     never its end (the age) */
  out.over = [];
  Array.prototype.forEach.call(document.querySelectorAll('.pd-desk table td, .pd-desk table th'), function (td) {
    if (td.closest('tr[hidden], .pd-det') || !td.checkVisibility()) return;
    var rects = texts(td); if (!rects.length) return;
    var cs = getComputedStyle(td), b = td.getBoundingClientRect();
    var left = b.left + parseFloat(cs.borderLeftWidth) + parseFloat(cs.paddingLeft) - 0.5;
    var right = b.right - parseFloat(cs.borderRightWidth) - parseFloat(cs.paddingRight) + 0.5;
    var lo = Math.min.apply(null, rects.map(function (q) { return q.left; }));
    var hi = Math.max.apply(null, rects.map(function (q) { return q.right; }));
    var t = td.closest('table');
    var name = (t.getAttribute('aria-label') || t.className.split(' ').pop()) + ' / ' + (td.getAttribute('data-label') || td.tagName);
    var cut = td.classList.contains('pd-srcc') ? hi > right : (lo < left || hi > right);
    if (cut) out.over.push([name, td.textContent.replace(/\s+/g, ' ').trim().slice(0, 30), Math.round(lo - left), Math.round(hi - right)]);
  });
  /* the KPI figures and their lines whole; the heads never overflow */
  Array.prototype.forEach.call(document.querySelectorAll('.pd-kc .pd-kv, .pd-kc .pd-ks, .pd-desk .pd-khead, .pd-desk .pd-chead'), function (el) {
    if (!el.checkVisibility()) return;
    if (el.scrollWidth > el.clientWidth + 0.5) out.over.push(['kpi', el.textContent.replace(/\s+/g, ' ').trim().slice(0, 40), el.clientWidth, el.scrollWidth]);
  });
  /* the open book's head: no two items overlap; the keys show whole pairs */
  var head = document.querySelector('.pd-pos .pd-chead');
  var items = Array.prototype.filter.call(head.children, function (c) { return c.checkVisibility() && c.getBoundingClientRect().width > 0; })
    .map(function (c) { return [c.className || c.tagName, c.getBoundingClientRect()]; });
  for (var i = 1; i < items.length; i++) {
    if (items[i][1].left < items[i - 1][1].right - 0.5) out.over.push(['head', items[i - 1][0] + ' / ' + items[i][0], 0, 0]);
  }
  var keys = document.querySelector('.pd-keys');
  out.keysShown = [];
  if (keys && keys.checkVisibility()) {
    var kb = keys.getBoundingClientRect();
    Array.prototype.forEach.call(keys.querySelectorAll('.pd-key'), function (k) {
      var r = k.getBoundingClientRect();
      if (r.top >= kb.bottom - 0.5) return;
      out.keysShown.push(k.textContent);
      if (r.left < kb.left - 0.5 || r.right > kb.right + 0.5) out.over.push(['keys', k.textContent, 0, 0]);
    });
  }
  function dotX(el) {
    var w = document.createTreeWalker(el, NodeFilter.SHOW_TEXT), n;
    while ((n = w.nextNode())) { var i = n.nodeValue.indexOf('.'); if (i >= 0) { var r = document.createRange(); r.setStart(n, i); r.setEnd(n, i + 1); return r.getBoundingClientRect().left; } }
    return null;
  }
  function dots(sel) { return Array.prototype.map.call(document.querySelectorAll(sel), dotX).filter(function (x) { return x !== null; }); }
  out.dots = dots('.pd-table tbody tr[data-sv-position-row] > td[data-label="P&L"] .pd-pv');
  out.dots24 = dots('.pd-tc tbody td .pd-pv');
  out.lower = __pd.boxes('.pd-lower > .pd-card');
  out.lowerGap = parseFloat(getComputedStyle(document.querySelector('.pd-lower')).columnGap);
  out.fs = getComputedStyle(document.querySelector('.pd-table tbody td.num')).fontSize;
  return out;
})()"""


@unittest.skipUnless(CHROME, "no headless Chromium on this machine")
class DeskWidthsMeasuredTests(TestCase):
    """The review's blocker (F1): from 1680 the size tiers raised the cells
    to 14 and 15 px while the figure columns kept their pixel widths, so
    quantities, prices and P&L were cut mid-figure and their decimal
    points drifted; at 1280 PRICED BY was 19 px wide. Measured at every
    width the frame has a tier for, in this frame."""

    maxDiff = None

    @classmethod
    def setUpTestData(cls):
        from tests.test_magic_layer import _Browser
        _user, client = desk_client("desk_widths")
        page = _file(_loaded(client), scripts=DESK_SCRIPTS)
        b = _Browser({"desk": page}, "sv-desk-w-")
        cls.got = {}
        try:
            for w, h in WIDTHS:
                sid = b.tab(w, h)
                b.open(sid, "desk", PROBE)
                cls.got[w] = b.js(sid, WIDTHS_PROBE)
        finally:
            b.close()

    def test_no_figure_and_no_word_is_cut_at_any_width(self):
        for w, got in sorted(self.got.items()):
            with self.subTest(width=w, cells=got["fs"]):
                self.assertEqual(got["over"], [])

    def test_the_pnl_decimal_points_stand_at_one_x_at_every_width(self):
        for w, got in sorted(self.got.items()):
            for key in ("dots", "dots24"):
                with self.subTest(width=w, table=key):
                    self.assertGreaterEqual(len(got[key]), 6)
                    self.assertLess(max(got[key]) - min(got[key]), 0.5, got[key])

    def test_the_keys_hint_is_whole_where_the_desk_is_the_board_s(self):
        """F8: the longer, truthful hint never overlaps nor cuts a word: at
        1440 and wider it is whole; narrower it drops whole pairs."""
        for w, got in sorted(self.got.items()):
            if w < 1440:
                continue
            with self.subTest(width=w):
                self.assertEqual(got["keysShown"], ["JKmove", "Enterthe Orc line", "Tabstop · target · Close"])

    def test_the_book_fits_its_card_from_1440(self):
        for w, got in sorted(self.got.items()):
            if w < 1440:
                continue
            with self.subTest(width=w):
                scroll, client = got["fit"]
                self.assertLessEqual(scroll, client)

    def test_the_lower_row_at_every_width(self):
        for w, got in sorted(self.got.items()):
            with self.subTest(width=w, desk=got["desk"]["w"]):
                _lower_row_checks(self, got["lower"], got["desk"], got["lowerGap"])


#: The phone pass: every closed detail row, then one opened and closed again
#: by its disclosure.
PHONE_PROBE = r"""(async function () {
  await __pd.settle();
  function shown(tr) { return getComputedStyle(tr).display !== 'none' && tr.checkVisibility(); }
  var dets = Array.prototype.slice.call(document.querySelectorAll('.pd-table > tbody > tr.pd-det'));
  var out = { vw: window.innerWidth, n: dets.length,
              closedShown: dets.filter(function (tr) { return tr.hidden && shown(tr); }).map(function (tr) { return tr.id; }) };
  var btn = document.querySelector('.pd-table .pd-disc');
  var det = btn && document.getElementById(btn.getAttribute('aria-controls'));
  out.before = det ? shown(det) : null;
  if (btn) btn.click();
  await __pd.settle();
  out.opened = det ? [det.hidden, shown(det)] : null;
  if (btn) btn.click();
  await __pd.settle();
  out.closedAgain = det ? [det.hidden, shown(det)] : null;
  return out;
})()"""


#: The open book's live chip, as the faces test reads it.
LIVE_CHIP = ".pd-pos .pd-chead > .sv-live-chip"

#: The kit's two faces stood in (CI round 1, 2026-11-14). This page, opened
#: as a file, fetches no face (_offline drops Google's links), so the faces
#: that drew the chip were the machine's: Inter and JetBrains Mono where they
#: are installed (the old-design guard's job installs both), the machine's
#: own sans everywhere else (the suite's runner, which installs neither,
#: drew all six glyphs in DejaVu Sans). As FacesMeasuredTests does for
#: Orbitron, a face every DejaVu install has stands in for each kit face,
#: over the characters that face carries in the chip, as the faces the guard
#: installs carry them (fc-list: JetBrains Mono has U+25C9, Inter has not):
#: (the kit's family, the faces that stand in for it, its characters).
CHIP_STANDINS = (
    ("Inter", ("DejaVu Serif",), "U+0000-00FF", "L"),
    ("JetBrains Mono", ("DejaVu Sans Mono", "DejaVu Serif"), "U+0000-00FF, U+25C9", "◉"),
)
STANDIN_FACES = {face for _family, faces, _range, _char in CHIP_STANDINS for face in faces}

#: The stand-ins declared and loaded (the count of faces each load found),
#: then the machine's own face for the mark: a span beside the chip in the
#: chip's chain without the kit's two families, which the measure must be
#: able to tell from the stand-ins.
CHIP_FACES_PROBE = r"""(async function () {
  await __pd.settle();
  var st = document.createElement('style');
  st.textContent = %(rules)s;
  document.head.appendChild(st);
  var loaded = [];
  var each = %(loads)s;
  for (var i = 0; i < each.length; i++) loaded.push((await document.fonts.load(each[i][0], each[i][1])).length);
  await document.fonts.ready;
  var chip = document.querySelector(%(chip)s);
  var kit = each.map(function (e) { return e[2]; });
  var tail = getComputedStyle(chip).fontFamily.split(',').filter(function (f) {
    return kit.indexOf(f.trim().replace(/"/g, '')) < 0; }).join(',');
  var mark = document.createElement('span');
  mark.setAttribute('data-pd-own-face', '');
  mark.style.cssText = 'font-family:' + tail + ';font-weight:600;font-size:11px';
  mark.textContent = '◉';
  chip.parentNode.appendChild(mark);
  return { text: chip.textContent, family: getComputedStyle(chip).fontFamily, loaded: loaded };
})()""" % {
    "rules": json.dumps(" ".join(
        '@font-face { font-family: "%s"; font-weight: 100 900; src: %s; unicode-range: %s; }'
        % (family, ", ".join('local("%s")' % f for f in faces), ranges)
        for family, faces, ranges, _char in CHIP_STANDINS)),
    "loads": json.dumps([['600 11px "%s"' % family, char, family]
                         for family, _faces, _ranges, char in CHIP_STANDINS]),
    "chip": json.dumps(LIVE_CHIP),
}


@unittest.skipUnless(CHROME, "no headless Chromium on this machine")
class DeskPhoneAndFacesMeasuredTests(TestCase):
    """The old-design guard's measured half, on main merged (B0, 2026-11-14),
    read two things on this page the board never draws. On the phone every
    row's detail stood open as a see-through card of its own: sauron.css's
    stacked tables give every row display: block, which outranks the hidden
    attribute. And the open book's live chip drew its ◉ in a fallback face,
    as Inter has none: the desk's words chain the number face after Inter for
    their glyphs, as the board's chips do. The chip is read with the kit's
    faces stood in (CHIP_STANDINS), the same on every machine."""

    @classmethod
    def setUpTestData(cls):
        from tests.test_magic_layer import _Browser
        _user, client = desk_client("desk_phone")
        page = _file(_loaded(client), scripts=DESK_SCRIPTS)
        b = _Browser({"desk": page}, "sv-desk-p-")
        try:
            sid = b.tab(390, 844)
            b.open(sid, "desk", PROBE)
            cls.phone = b.js(sid, PHONE_PROBE)
            sid = b.tab(1440, 900)
            b.open(sid, "desk", PROBE)
            cls.chip = b.js(sid, CHIP_FACES_PROBE)
            cls.chip_faces = b.fonts(sid, LIVE_CHIP)
            cls.own_faces = b.fonts(sid, "[data-pd-own-face]")
        finally:
            b.close()

    def test_a_closed_detail_row_stays_closed_on_the_phone(self):
        got = self.phone
        self.assertEqual(got["vw"], 390)
        self.assertGreater(got["n"], 0)
        self.assertEqual(got["closedShown"], [])
        self.assertIs(got["before"], False)
        # its disclosure still opens it, and closes it again
        self.assertEqual(got["opened"], [False, True])
        self.assertEqual(got["closedAgain"], [True, False])

    def test_the_live_chip_s_glyph_is_drawn_in_the_kit_s_faces(self):
        self.assertIn("◉", self.chip["text"])
        # each kit face is stood in on this machine
        self.assertEqual([n >= 1 for n in self.chip["loaded"]], [True] * len(CHIP_STANDINS), self.chip)
        # the machine's own face for the mark is none of the stand-ins: the measure tells them apart
        own = [f["family"] for node in self.own_faces for f in node]
        self.assertTrue(own, self.own_faces)
        self.assertEqual([f for f in own if f in STANDIN_FACES], [], self.own_faces)
        # every glyph of the chip in a kit face, the ◉ (no glyph of Inter's) in the number face's
        faces = [f["family"] for node in self.chip_faces for f in node]
        self.assertTrue(faces, self.chip_faces)
        self.assertEqual([f for f in faces if f not in STANDIN_FACES], [], (self.chip_faces, self.chip["family"]))


# ══════════════════════════════════════════════════════════════════════════
# 5. The review (2026-11-13), held by the page as rendered
# ══════════════════════════════════════════════════════════════════════════

_VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
              "meta", "param", "source", "track", "wbr"}


class _Regions(HTMLParser):
    """{region name: its inner markup} for every data-sv-live region."""

    def __init__(self, src):
        super().__init__(convert_charrefs=False)
        self.src = src
        self.offsets = [0]
        for line in src.splitlines(keepends=True):
            self.offsets.append(self.offsets[-1] + len(line))
        self.stack = []
        self.out = {}

    def _pos(self):
        line, col = self.getpos()
        return self.offsets[line - 1] + col

    def handle_starttag(self, tag, attrs):
        if tag in _VOID_TAGS:
            return
        region = dict(attrs).get("data-sv-live")
        self.stack.append([tag, region, self._pos() + len(self.get_starttag_text())])

    def handle_endtag(self, tag):
        while self.stack:
            t, region, start = self.stack.pop()
            if t == tag:
                if region:
                    self.out[region] = self.src[start:self._pos()]
                return


def _regions(html):
    p = _Regions(html)
    p.feed(html)
    return p.out


def _canon(markup):
    """A region's markup with what a second moves set aside: the live
    chip's painted word, ages in words."""
    s = re.sub(r"\s+", " ", markup)
    s = re.sub(r"(data-sv-live-status[^>]*>)[^<]*", r"\1", s)
    s = re.sub(r"\b\d+(?:\.\d+)?\s?(?:s|sec|min|minutes?|h|hours?|days?)\b", "#", s)
    return s.strip()


class DeskReviewTests(TestCase):
    """The review of 2026-11-13 (the fidelity and contract lenses): each
    fix that the rendered page can hold, held."""

    @classmethod
    def setUpTestData(cls):
        cls.user, cls.client_ = desk_client("desk_review")
        cls.page = _get(cls.client_, "/positions/")
        cls.live = _get(cls.client_, "/positions/live/")
        cls.hist = _get(cls.client_, "/positions/?tab=history")
        cls.hist_live = _get(cls.client_, "/positions/live/?tab=history")

    def _desk_regions(self, html):
        return {k: v for k, v in _regions(html).items()
                if k.startswith("pos-") or k == "cap-card"}

    def test_every_region_renders_alike_on_the_page_and_its_refresh(self):
        """Contract F1: a region whose two renders differ is swapped by the
        first sweep; the History link only the full page carried vanished
        20 to 60 s after load, and nothing linked to the history again."""
        for full, live in ((self.page, self.live), (self.hist, self.hist_live)):
            a, b = self._desk_regions(full), self._desk_regions(live)
            self.assertTrue(a)
            for name in sorted(a):
                with self.subTest(region=name):
                    self.assertIn(name, b)
                    self.assertEqual(_canon(a[name]), _canon(b[name]))
        self.assertIn('href="?tab=history"', _regions(self.live)["pos-lower"])

    def test_a_desk_that_cannot_be_read_prints_dashes_never_an_error(self):
        """Contract F4: the desk's figures ran unguarded on the page the
        operator closes from; a failure there must cost the figures, never
        the page and its CLOSE buttons."""
        from unittest import mock
        with mock.patch("dashboard.positions_desk.desk", side_effect=RuntimeError("synthetic")):
            page = _get(self.client_, "/positions/")
        self.assertEqual(len(_rows(page)), 6)
        self.assertEqual(page.count('class="btn btn-sm btn-danger" data-sv-close-trade="'), 6)
        self.assertIn('id="svCloseAll"', page)
        strip = page[page.index('data-sv-live="pos-strip"'):page.index('data-sv-live="pos-count"')]
        self.assertEqual(re.findall(r'data-pd-world="(\w+)"', strip), ["live", "demo", "paper"])
        self.assertIn("—", strip)

    def test_the_closed_book_is_by_world_never_summed(self):
        """F5: the history strip added REAL, DEMO and PAPER (+140.04, read as
        real money); each world now stands apart, REAL keeping the keys."""
        strip = self.hist[self.hist.index('data-sv-live="pos-strip"'):]
        strip = strip[:strip.index("</section>")]
        self.assertIn("by world · never summed", strip)
        self.assertEqual(re.findall(r'data-pd-closed-world="(\w+)"', strip), ["live", "demo", "paper"])
        keys = dict(re.findall(r'data-sv-live-key="([\w.]+)">([^<]*)<', strip))
        self.assertEqual(keys["pos.realized"], "+62.85")
        self.assertEqual(keys["pos.realized.demo"], "+45.00")
        self.assertEqual(keys["pos.realized.paper"], "+32.19")
        self.assertEqual((keys["pos.closed"], keys["pos.closed.demo"], keys["pos.closed.paper"]),
                         ("12", "3", "12"))
        self.assertEqual(keys["pos.win_rate"], "50%")
        # Three demo closes are counted, never graded into a rate.
        self.assertEqual((keys["pos.win_rate.demo"], keys["pos.profit_factor.demo"]), ("—", "—"))
        for summed in ("+140.04", "27"):
            self.assertNotIn(">%s<" % summed, strip)

    def test_best_and_worst_name_their_world_in_the_instrument_s_digits(self):
        """F5 and F18: best and worst picked across worlds with no chip, and
        a winning EURGBP read "0.86 → 0.86"."""
        best = self.hist[self.hist.index(">Best Trade<"):self.hist.index(">Worst Trade<")]
        worst = self.hist[self.hist.index(">Worst Trade<"):self.hist.index('class="pd-card pd-hist"')]
        self.assertIn('sv-world sv-world--live', best)
        self.assertIn("0.86000 → 0.86200", best)
        self.assertIn('sv-world sv-world--paper', worst)
        self.assertIn("0.58910 → 0.58790", worst)

    def test_the_history_list_uses_the_short_chips_and_the_side_markers(self):
        """F18: rows wore the long REAL MONEY chip; the bar's markers were
        ◀ ▶ on the fills at 2.8:1."""
        hist = self.hist[self.hist.index('class="pd-card pd-hist"'):self.hist.index('aria-label="At the broker"')]
        self.assertIn("ph-chart-marker", hist)
        self.assertNotIn(">REAL MONEY<", hist)
        self.assertNotIn("&#9654;", hist)
        self.assertNotIn("&#9664;", hist)

    def test_the_30_day_note_keeps_the_fees_caveat(self):
        """F21: the board's note says fees are not counted yet; for real
        money that caveat stays."""
        note = self.page[self.page.index('class="pd-foot pd-foot--c30"'):]
        note = note[:note.index("</p>")]
        self.assertIn("Fees are not counted yet", note)

    def test_margin_used_says_its_currency_and_the_stops_their_rule(self):
        """F14: MARGIN USED's line dropped the $; AT THE STOPS now says how
        it is measured."""
        strip = self.page[self.page.index('data-sv-live="pos-strip"'):self.page.index('data-sv-live="pos-count"')]
        self.assertRegex(strip, r'data-sv-live-key="pos\.margin\.sub"[^>]*>.*?\$4,402\.10.*?\$6,051\.51.*? free', )
        self.assertRegex(strip, r'title="[^"]*if every stop fills[^"]*entry[^"]*"')

    def test_a_world_tab_says_its_world_and_leaves_the_filter_button_dark(self):
        """F20: the Real tab's note said "world live" and lit Order · filter."""
        page = _get(self.client_, "/positions/?world=live")
        note = re.search(r'<p class="pos-view-note"[^>]*>(.*?)</p>', page, re.S).group(1)
        self.assertIn("world <b>Real</b>", note)
        self.assertRegex(page, r'class="pd-filter-btn"\s')
        page = _get(self.client_, "/positions/?world=live&side=long")
        self.assertRegex(page, r'class="pd-filter-btn is-on"')

    def test_at_the_broker_reads_as_a_trader_reads(self):
        """F19: quantities at four decimals and LIVE as an Orbitron word."""
        panel = self.page[self.page.index('aria-label="At the broker"'):]
        panel = panel[:panel.index("</section>")]
        head = panel[:panel.index("</div>")]
        self.assertNotRegex(head, r"<h2[^>]*>[^<]*·\s*LIVE\s*</h2>")
        self.assertIn('sv-world sv-world--live', head)
        self.assertIn('data-label="Qty">1.5<', panel)
        self.assertNotIn("1.5000", panel)

    def test_the_history_tab_keeps_the_broker_and_the_capital(self):
        """Contract F5: main showed both on both tabs."""
        self.assertIn('aria-label="At the broker"', self.hist)
        self.assertIn('data-sv-live="cap-card"', self.hist)

    def test_the_etoro_line_sits_in_the_book_card(self):
        """F4: one paragraph between the cards, on the void."""
        strip = self.page[self.page.index('data-sv-live="pos-strip"'):self.page.index('data-sv-live="pos-count"')]
        book = strip[strip.index('aria-label="The real book at eToro"'):]
        book = book[:book.index("</section>")]
        for key in ("pos.etoro", "pos.etoro.sub", "pos.etoro.split"):
            self.assertIn('data-sv-live-key="%s"' % key, book)
        self.assertIn("ETORO USED", book)
        self.assertIn('popovertarget="pdEtoro"', book)
        self.assertNotIn('<p class="pd-etoro"', strip)

    def test_an_estimate_is_marked_and_never_drawn_as_a_measured_gain(self):
        """F12, in the markup: the ≈, ink, an empty arrow slot."""
        rows = dict((re.search(r'data-pos-symbol="(\w+)"', t).group(1), r) for t, r in _rows(self.page))
        self.assertRegex(rows["NAS100"], r'class="pd-pv pd-pv--est"><span class="pd-est" aria-label="estimate">≈</span>'
                                         r'\+61\.50<span class="pd-dg" aria-hidden="true"></span>')
        self.assertIn('class="num pd-r--est"', rows["NAS100"])
        self.assertRegex(rows["EURUSD"], r'class="pd-pv up">\+65\.00<span class="pd-dg" aria-hidden="true">▲</span>')

    def test_the_keys_say_where_tab_goes(self):
        """F8: from the keys' row CLOSE is the fourth Tab stop (the symbol,
        the stop, the target); the hint says so."""
        head = self.page[self.page.index('class="pd-card pd-pos"'):]
        head = head[:head.index("<table")]
        self.assertIn('<kbd class="pd-kbd">Tab</kbd><span>stop · target · Close</span>', head)

    def test_the_detail_row_repeats_no_chip_and_spans_to_the_end(self):
        """F9: a second REAL MONEY chip under the row's own, and a last cell
        the pinned CLOSE column took."""
        dets = re.findall(r'<tr class="pd-det[^"]*" id="pd-det-[\w-]+"[^>]*hidden>(.*?)</tr>', self.page, re.S)
        self.assertEqual(len(dets), 6)
        for det in dets:
            self.assertNotIn("sv-world", det)
            tds = re.findall(r"<td\b([^>]*)>", det)
            self.assertIn("colspan=", tds[-1])
            spans = sum(int(re.search(r'colspan="(\d+)"', t).group(1)) if "colspan" in t else 1 for t in tds)
            self.assertEqual(spans, 13)

    def test_the_figure_columns_are_sized_from_their_figures(self):
        """F1: each figure column as wide as its widest figure in the number
        face (the instrument's digits, the ≈ and the arrow's slot), never a
        fixed pixel width the size tiers outgrow."""
        cols = re.search(r'<colgroup>(<col class="pd-c-sel">.*?)</colgroup>', self.page).group(1)
        for want in ('class="pd-c-sym pd-ch6"', 'class="pd-c-qty pd-ch6"', 'class="pd-c-px pd-ch8"',
                     'class="pd-c-pnl pd-ch10"', 'class="pd-c-r pd-ch6"', 'class="pd-c-lvl pd-ch8"'):
            self.assertIn(want, cols)


class DeskSourceReviewTests(SimpleTestCase):
    """The review's fixes that live in the sources."""

    def _rules(self):
        css = re.sub(r"/\*.*?\*/", "", read(SHEET), flags=re.S)
        for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
            yield m.group(1).strip(), m.group(2)

    def test_the_close_dialog_rules_leave_take_trade_alone(self):
        """Contract F2: every dialog rule of this sheet is scoped to the
        close flows (a danger confirm that is not TAKE TRADE)."""
        n = 0
        for selector, _body in self._rules():
            for sel in selector.split(","):
                if re.search(r"\.sv-dialog|\.sz-warn", sel):
                    n += 1
                    self.assertIn(".sv-dialog--danger:not(.sz-dialog)", sel, sel)
        self.assertGreater(n, 5)

    def test_the_analytics_fragment_carries_no_page_style(self):
        """F6: its own <style> block and inline styles moved to the sheet; the
        sides are words with their arrows; no caption points at a table the
        page no longer has."""
        frag = read("templates/dashboard/_positions_metrics.html")
        self.assertNotIn("<style", frag)
        self.assertNotRegex(frag, r'\sstyle="')
        self.assertIn("▲ LONG", frag)
        self.assertIn("▼ SHORT", frag)
        self.assertNotIn("the asset-class table at the top of this page", frag)
