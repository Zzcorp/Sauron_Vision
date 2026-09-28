"""The position tables in purchase order, filtered and grouped (2026-09-26).

The operator's ask, 2026-09-26: the book in the order it was bought, with
filters (same asset, same type) and groups. Pinned here:
  - dashboard/position_views, pure: junk params fall back to the defaults
    and never raise; `opened` IS purchase order; each filter narrows; a
    group nothing in it could price sums to None, never 0; the (row,
    detail) pairs never come apart; /portfolio/'s cap cuts after the sort.
  - the pages: ?group=class renders one group row per type present, with
    its count; ?symbol=X shows X alone and says "showing 1 of N"; the strip
    and Close all still count the whole book; /positions/live/ with the
    same params renders the same order; the history tab sorts by the
    close; /portfolio/?sort=opened orders its table by opened_at; a junk
    param still renders 200; an asset the book no longer holds turns its
    filter off and the table says so, repeating the value only when it
    looks like a ticker; Close all says "whole book" and carries no count
    that a fill could make stale; a group the eight-row cap cuts still
    sums all of its rows; each group row spans the thead's columns; the
    bar stays out of the live fragments and has a no-JS submit.

Run with:  python manage.py test tests.test_position_views
"""
import html
import re
from datetime import datetime, timedelta, timezone as dt_tz
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from dashboard import position_views as pv

HOST = "127.0.0.1"
DASH = "—"
T0 = datetime(2026, 9, 1, 12, 0, tzinfo=dt_tz.utc)


# ── Fixtures: rows shaped the way the views build them ─────────────────────

def _row(symbol, asset_class, days, *, side="long", pnl=None, qty=1.0,
         entry=100.0, mark=None, paper=True, source="bot"):
    """A live row as dashboard.views._live_row shapes one — the keys the
    module reads. `days` is the purchase day after T0; None is no stamp."""
    return {"key": "bot-%s-%s" % (symbol, days), "symbol": symbol,
            "asset_class": asset_class, "direction": side, "quantity": qty,
            "entry_price": entry, "current_price": mark,
            "unrealized_pnl": pnl, "paper": paper, "source": source,
            "opened_at": (T0 + timedelta(days=days)
                          if days is not None else None)}


def _pairs(*rows):
    """(row, detail) as _render_positions zips them: the detail names its
    own row's symbol, so a misaligned pair is visible."""
    return [(r, {"symbol": r["symbol"],
                 "venue": (("PAPER" if r["paper"] else "LIVE")
                           if r["source"] == "bot" else "")})
            for r in rows]


def _symbols(pairs):
    return [row["symbol"] for row, _detail in pairs]


# ── 1. Parsing: a closed vocabulary with safe defaults ─────────────────────

class ParseTests(SimpleTestCase):
    def setUp(self):
        self.pairs = _pairs(_row("EURUSD", "forex", 1),
                            _row("BTCUSD", "crypto", 2, side="short"))

    def test_junk_falls_back_to_the_defaults(self):
        view = pv.parse_view({"sort": "DROP TABLE", "class": "bonds",
                              "symbol": "<script>", "side": "sideways",
                              "venue": "moon", "group": "x" * 500},
                             self.pairs)
        self.assertEqual(
            (view["sort"], view["asset_class"], view["symbol"],
             view["side"], view["venue"], view["group"]),
            ("opened", "", "", "", "", ""))

    def test_the_history_default_is_the_newest_close(self):
        self.assertEqual(pv.parse_view({}, self.pairs, history=True)["sort"],
                         "-closed")
        # The open book has no close to sort by.
        self.assertEqual(pv.parse_view({"sort": "closed"}, self.pairs)["sort"],
                         "opened")
        self.assertEqual(pv.parse_view({"sort": "closed"}, self.pairs,
                                       history=True)["sort"], "closed")

    def test_an_unreadable_params_object_is_no_params(self):
        for params in (None, object(), {"sort": 7}, {"sort": []}):
            view = pv.build_view(params, self.pairs)
            self.assertEqual(view["sort"], "opened", params)
            self.assertEqual(view["n_shown"], 2, params)
        # The last value wins, as QueryDict.get reads it.
        self.assertEqual(pv.parse_view({"sort": ["junk", "-pnl"]},
                                       self.pairs)["sort"], "-pnl")

    def test_type_and_asset_must_be_in_the_book(self):
        view = pv.parse_view({"class": "FOREX", "symbol": "btcusd"},
                             self.pairs)
        self.assertEqual(view["asset_class"], "forex")
        self.assertEqual(view["symbol"], "BTCUSD")
        view = pv.parse_view({"class": "bonds", "symbol": "AAPL"}, self.pairs)
        self.assertEqual((view["asset_class"], view["symbol"]), ("", ""))

    def test_a_filter_the_book_does_not_hold_is_dropped_and_named(self):
        """The last BTCUSD closing under ?symbol=BTCUSD: the next sweep
        shows the whole book, and has to say the filter went off."""
        view = pv.build_view({"class": "bonds", "symbol": "AAPL"}, self.pairs)
        self.assertEqual(view["dropped"], [("type", "bonds"), ("asset", "AAPL")])
        self.assertEqual(view["n_shown"], 2)
        self.assertTrue(view["changed"])
        self.assertFalse(view["filtered"])
        # A control character is junk, not a name: dropped without a word.
        self.assertEqual(pv.build_view({"symbol": "\x00"}, self.pairs)["dropped"],
                         [])
        self.assertEqual(pv.build_view({"symbol": "EURUSD"},
                                       self.pairs)["dropped"], [])

    def test_only_a_ticker_shaped_value_is_echoed_back(self):
        """A crafted link must not put its own sentence on the page that
        holds Close all: a value with a space is dropped under a neutral
        sentence that repeats nothing of it."""
        view = pv.build_view(
            {"symbol": "MARGIN CALL - close everything now",
             "class": "<script>"}, self.pairs)
        self.assertEqual(view["dropped"], [("type", ""), ("asset", "")])
        self.assertTrue(view["changed"])
        for token in ("BRK.B", "EUR/USD", "ES=F", "^VIX", "btc-usd"):
            self.assertEqual(pv.build_view({"symbol": token},
                                           self.pairs)["dropped"],
                             [("asset", token)], token)

    def test_the_options_carry_counts(self):
        view = pv.parse_view({}, self.pairs + _pairs(_row("GBPUSD", "forex", 3)))
        self.assertEqual([o["label"] for o in view["class_options"]],
                         ["crypto (1)", "forex (2)"])
        self.assertEqual([o["label"] for o in view["side_options"]],
                         ["long (2)", "short (1)"])
        self.assertEqual([o["label"] for o in view["venue_options"]],
                         ["paper (3)"])


# ── 2. Order: purchase order is the floor every order stands on ────────────

class OrderTests(SimpleTestCase):
    def test_opened_ascending_is_purchase_order(self):
        pairs = _pairs(_row("C", "crypto", 3), _row("A", "crypto", 1),
                       _row("X", "crypto", None), _row("B", "crypto", 2))
        self.assertEqual(_symbols(pv.sort_pairs(pairs, "opened")),
                         ["A", "B", "C", "X"])
        # A row with no stamp is last both ways: it was not bought first.
        self.assertEqual(_symbols(pv.sort_pairs(pairs, "-opened")),
                         ["C", "B", "A", "X"])

    def test_an_unmeasured_pnl_sorts_last_both_ways(self):
        pairs = _pairs(_row("UP", "crypto", 1, pnl=5.0),
                       _row("NONE", "crypto", 2),
                       _row("DOWN", "crypto", 3, pnl=-5.0))
        self.assertEqual(_symbols(pv.sort_pairs(pairs, "pnl")),
                         ["DOWN", "UP", "NONE"])
        self.assertEqual(_symbols(pv.sort_pairs(pairs, "-pnl")),
                         ["UP", "DOWN", "NONE"])

    def test_ties_keep_purchase_order(self):
        pairs = _pairs(_row("BTCUSD", "crypto", 3), _row("EURUSD", "forex", 2),
                       _row("ETHUSD", "crypto", 1))
        self.assertEqual(_symbols(pv.sort_pairs(pairs, "class")),
                         ["ETHUSD", "BTCUSD", "EURUSD"])

    def test_a_naive_stamp_beside_an_aware_one_does_not_raise(self):
        naive = _row("B", "crypto", None)
        naive["opened_at"] = datetime(2026, 9, 5, 12, 0)
        got = _symbols(pv.sort_pairs(_pairs(_row("A", "crypto", 1), naive),
                                     "opened"))
        self.assertEqual(sorted(got), ["A", "B"])


# ── 3. Filters narrow the table; the counts say by how much ────────────────

class FilterTests(SimpleTestCase):
    def setUp(self):
        self.pairs = _pairs(
            _row("EURUSD", "forex", 1, paper=False),
            _row("GBPUSD", "forex", 2, side="short"),
            _row("BTCUSD", "crypto", 3),
            _row("PVSTK", "stock", 4, source="position"))

    def _shown(self, **params):
        return _symbols(pv.build_view(params, self.pairs)["pairs"])

    def test_each_filter_narrows(self):
        self.assertEqual(self._shown(**{"class": "forex"}),
                         ["EURUSD", "GBPUSD"])
        self.assertEqual(self._shown(symbol="BTCUSD"), ["BTCUSD"])
        self.assertEqual(self._shown(side="short"), ["GBPUSD"])
        self.assertEqual(self._shown(venue="live"), ["EURUSD"])
        # A legacy row has no venue: it is neither live nor paper.
        self.assertEqual(self._shown(venue="paper"), ["GBPUSD", "BTCUSD"])
        self.assertEqual(self._shown(**{"class": "forex", "side": "long"}),
                         ["EURUSD"])

    def test_the_view_says_how_much_of_the_book_it_shows(self):
        view = pv.build_view({"symbol": "BTCUSD"}, self.pairs)
        self.assertEqual((view["n_shown"], view["n_total"]), (1, 4))
        self.assertTrue(view["filtered"])
        self.assertTrue(view["partial"])
        self.assertEqual(view["filters"], [("asset", "BTCUSD")])
        grouped = pv.build_view({"group": "class"}, self.pairs)
        self.assertFalse(grouped["filtered"])
        self.assertFalse(grouped["partial"])

    def test_the_venue_reads_the_row_when_there_is_no_detail(self):
        """/portfolio/ hands (row, None)."""
        pairs = [(row, None) for row, _detail in self.pairs]
        self.assertEqual(
            _symbols(pv.build_view({"venue": "live"}, pairs)["pairs"]),
            ["EURUSD"])

    def test_the_cap_cuts_after_the_sort_and_the_filter(self):
        view = pv.build_view({"sort": "-opened"}, self.pairs, limit=2)
        self.assertEqual(_symbols(view["pairs"]), ["PVSTK", "BTCUSD"])
        self.assertEqual((view["n_shown"], view["n_matched"], view["n_total"]),
                         (2, 4, 4))
        self.assertTrue(view["partial"])
        self.assertFalse(view["filtered"])

    def test_the_clear_link_keeps_the_tab(self):
        view = pv.build_view({"class": "forex"}, self.pairs,
                             keep={"tab": "open"}, base_url="/positions/")
        self.assertEqual(view["clear_href"], "/positions/?tab=open")
        self.assertEqual(view["keep"], [("tab", "open")])
        self.assertTrue(view["changed"])
        self.assertFalse(pv.build_view({}, self.pairs)["changed"])


# ── 4. Groups: subtotals, and unmeasured is never 0 ────────────────────────

class GroupTests(SimpleTestCase):
    def test_subtotals_and_an_unpriced_group_sums_to_none(self):
        pairs = _pairs(
            _row("EURUSD", "forex", 1, pnl=10.0, qty=1000, entry=1.08,
                 mark=1.10),
            _row("GBPUSD", "forex", 2, pnl=-4.0, qty=1000, entry=1.25),
            _row("BTCUSD", "crypto", 3, qty=1, entry=100))
        groups = pv.build_view({"group": "class"}, pairs)["groups"]
        self.assertEqual([(g["key"], g["n"]) for g in groups],
                         [("forex", 2), ("crypto", 1)])
        forex, crypto = groups
        self.assertEqual(forex["pnl"], 6.0)
        self.assertEqual(forex["pnl_text"], "+6.00")
        self.assertEqual(forex["pnl_tone"], "up")
        # The mark where there is one, entry cost where there is not.
        self.assertAlmostEqual(forex["exposure"], 1100.0 + 1250.0)
        self.assertIsNone(crypto["pnl"])
        self.assertEqual(crypto["pnl_text"], DASH)
        self.assertEqual(crypto["pnl_tone"], "")
        self.assertEqual(crypto["exposure"], 100.0)
        self.assertIn("not zero", crypto["pnl_title"])

    def test_a_group_the_cap_cuts_still_sums_all_of_it(self):
        """/portfolio/'s cap thins the table, never a group's count or its
        sums: a subtotal over the listed rows alone would read as the
        type's total and contradict the donut."""
        pairs = _pairs(_row("EURUSD", "forex", 1, pnl=1.0),
                       _row("BTCUSD", "crypto", 2, pnl=2.0),
                       _row("GBPUSD", "forex", 3, pnl=4.0),
                       _row("ETHUSD", "crypto", 4, pnl=8.0))
        view = pv.build_view({"group": "class"}, pairs, limit=2)
        forex, crypto = view["groups"]
        self.assertEqual((forex["n"], forex["n_shown"], forex["pnl"],
                          forex["cut"]), (2, 1, 5.0, True))
        self.assertEqual((crypto["n"], crypto["n_shown"], crypto["pnl"],
                          crypto["cut"]), (2, 1, 10.0, True))
        self.assertIn("cover all 2", forex["cut_title"])
        self.assertEqual(_symbols(view["pairs"]), ["EURUSD", "BTCUSD"])
        self.assertEqual((view["n_shown"], view["n_matched"]), (2, 4))
        # A group the cap cut entirely keeps its header and its sums.
        forex, crypto = pv.build_view({"group": "class"}, pairs,
                                      limit=1)["groups"]
        self.assertEqual((crypto["n"], crypto["n_shown"], crypto["pnl"],
                          crypto["rows"]), (2, 0, 10.0, []))
        # No cap: nothing is cut.
        self.assertFalse(any(g["cut"] for g in
                             pv.build_view({"group": "class"},
                                           pairs)["groups"]))

    def test_no_grouping_is_one_headless_group(self):
        groups = pv.build_view({}, _pairs(_row("A", "crypto", 1)))["groups"]
        self.assertEqual(len(groups), 1)
        self.assertFalse(groups[0]["header"])

    def test_the_groups_follow_the_sort(self):
        pairs = _pairs(_row("BTCUSD", "crypto", 1), _row("EURUSD", "forex", 2),
                       _row("ETHUSD", "crypto", 3))
        view = pv.build_view({"group": "class", "sort": "-opened"}, pairs)
        self.assertEqual([g["key"] for g in view["groups"]],
                         ["crypto", "forex"])
        self.assertEqual([r["symbol"] for r in view["groups"][0]["rows"]],
                         ["ETHUSD", "BTCUSD"])
        # The flat list is the rendered order: grouped rows together.
        self.assertEqual(_symbols(view["pairs"]),
                         ["ETHUSD", "BTCUSD", "EURUSD"])

    def test_the_pairs_never_come_apart(self):
        pairs = _pairs(*[_row(s, c, d, pnl=p) for s, c, d, p in (
            ("EURUSD", "forex", 4, 1.0), ("BTCUSD", "crypto", 1, None),
            ("ETHUSD", "crypto", 3, -2.0), ("PVSTK", "stock", 2, 3.0))])
        for params in ({}, {"sort": "-pnl"}, {"sort": "symbol", "group": "class"},
                       {"group": "symbol", "side": "long"},
                       {"class": "crypto", "sort": "pnl"}):
            view = pv.build_view(params, pairs)
            flat = []
            for group in view["groups"]:
                for row, detail in group["pairs"]:
                    self.assertEqual(detail["symbol"], row["symbol"], params)
                    flat.append((row, detail))
            self.assertEqual(flat, view["pairs"], params)

    def test_a_closed_trade_groups_on_its_booked_pnl(self):
        pairs = _pairs(_row("A", "crypto", 1, pnl=5.0),
                       _row("B", "crypto", 2, pnl=-2.0))
        group = pv.build_view({"group": "class"}, pairs,
                              history=True)["groups"][0]
        self.assertEqual((group["pnl"], group["pnl_label"], group["noun"]),
                         (3.0, "realized", "trade"))
        self.assertEqual(group["exposure_label"], "exposure at entry")


# ── Page fixtures ──────────────────────────────────────────────────────────

def _user(name):
    return User.objects.create_user(username=name, password="x")


def _instrument(symbol, asset_class):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class,
                                 "is_active": True})
    return inst


def _quote(symbol, last, asset_class):
    from market_data.models import LiveQuote
    LiveQuote.objects.update_or_create(
        instrument=_instrument(symbol, asset_class),
        defaults={"last": Decimal(str(last)), "source": "test"})


def _trade(user, symbol, asset_class, days_ago, *, side="BUY", qty="1",
           entry="100", paper=True, **kw):
    from bot_program.models import AssetBotConfig, AssetBotTrade
    _instrument(symbol, asset_class)
    cfg, _ = AssetBotConfig.objects.get_or_create(
        user=user, asset_class=asset_class, name="pv-%s" % asset_class,
        defaults=dict(enabled=True, mode="paper", symbols=[],
                      capital=Decimal("10000"), base_currency="USD"))
    trade = AssetBotTrade.objects.create(
        config=cfg, asset_class=asset_class, symbol=symbol, side=side,
        qty=Decimal(qty), entry_price=Decimal(entry), paper=paper, **kw)
    # opened_at is auto_now_add: the purchase time is written after the row
    # exists, or every fixture would be bought in the same instant.
    AssetBotTrade.objects.filter(pk=trade.pk).update(
        opened_at=timezone.now() - timedelta(days=days_ago))
    return trade


def _region(body, name):
    """One live region's markup, up to the next region marker."""
    start = body.index('data-sv-live="%s"' % name)
    end = body.find('data-sv-live="', start + 12)
    return body[start:end if end != -1 else len(body)]


def _keys(body, name):
    """The row keys of a live region, in the order the page renders them."""
    return re.findall(r'data-sv-live-key="(bot-\d+)\.last"', _region(body, name))


def cells(body):
    """{live key: the text in that cell} — tests/test_portfolio_live.cells."""
    out = {}
    for m in re.finditer(r'data-sv-live-key="([^"]+)"[^>]*>', body):
        window = body[m.end():m.end() + 400]
        window = window.split("</td>")[0].split("</span>")[0]
        out[m.group(1)] = html.unescape(re.sub(r"<[^>]+>", "", window)).strip()
    return out


class _PageCase(TestCase):
    def _get(self, url):
        resp = self.client.get(url, HTTP_HOST=HOST)
        self.assertEqual(resp.status_code, 200, url)
        return resp.content.decode("utf-8", "replace")


# ── 5. /positions/, the open tab ───────────────────────────────────────────

class PositionsOpenTabTests(_PageCase):
    def setUp(self):
        self.user = _user("pv_open")
        self.client.force_login(self.user)
        _quote("EURUSD", "1.10", "forex")
        _quote("GBPUSD", "1.30", "forex")
        _quote("BTCUSD", "110", "crypto")
        # Created out of purchase order on purpose.
        self.btc = _trade(self.user, "BTCUSD", "crypto", 3)
        self.eur = _trade(self.user, "EURUSD", "forex", 5, qty="1000",
                          entry="1.08")
        self.eth = _trade(self.user, "ETHUSD", "crypto", 1, side="SELL")
        self.stk = _trade(self.user, "PVSTK", "stock", 2)
        self.gbp = _trade(self.user, "GBPUSD", "forex", 4, qty="1000",
                          entry="1.25", paper=False)
        self.bought = ["bot-%d" % t.id for t in
                       (self.eur, self.gbp, self.btc, self.stk, self.eth)]

    def test_the_open_tab_is_in_purchase_order_by_default(self):
        self.assertEqual(_keys(self._get("/positions/"), "pos-open"),
                         self.bought)

    def test_newest_first_is_one_param_away(self):
        self.assertEqual(_keys(self._get("/positions/?sort=-opened"),
                               "pos-open"), self.bought[::-1])

    def test_group_by_type_renders_one_group_row_per_type(self):
        body = self._get("/positions/?group=class")
        region = _region(body, "pos-open")
        self.assertEqual(region.count('class="pos-group-row"'), 3)
        for name, n in (("forex", 2), ("crypto", 2), ("stock", 1)):
            self.assertRegex(
                region, r'pos-group-name">%s</span><span class="pos-group-n">'
                        r'%d position%s<' % (name, n, "s" if n > 1 else ""))
        # Groups in the order of their first purchase, rows bought-first.
        self.assertEqual(_keys(body, "pos-open"),
                         ["bot-%d" % t.id for t in
                          (self.eur, self.gbp, self.btc, self.eth, self.stk)])
        # One tbody per group, so each header's scope="rowgroup" names its
        # own rows only; ungrouped, the one tbody the table always had.
        self.assertEqual(region.count("<tbody>"), 3)
        self.assertEqual(
            _region(self._get("/positions/"), "pos-open").count("<tbody>"), 1)

    def test_a_group_nothing_could_price_prints_a_dash_not_zero(self):
        got = cells(self._get("/positions/?group=class"))
        self.assertEqual(got["pos.group.class.stock.pnl"], DASH)
        # ETHUSD has no quote: crypto sums BTCUSD alone, never a 0 for ETH.
        self.assertEqual(got["pos.group.class.crypto.pnl"], "+10.00")

    def test_a_symbol_filter_shows_that_asset_alone_and_says_so(self):
        body = self._get("/positions/?symbol=BTCUSD")
        self.assertEqual(_keys(body, "pos-open"), ["bot-%d" % self.btc.id])
        self.assertIn("Showing <b>1</b> of <b>5</b> open positions",
                      _region(body, "pos-open"))

    def test_the_strip_and_the_breakdown_still_count_the_whole_book(self):
        resp = self.client.get("/positions/?symbol=BTCUSD", HTTP_HOST=HOST)
        body = resp.content.decode()
        self.assertEqual(cells(body)["pos.open"], "5")
        self.assertEqual(len(resp.context["positions"]), 5)
        self.assertEqual({a["asset_class"] for a in
                          resp.context["asset_breakdown"]},
                         {"forex", "crypto", "stock"})

    def test_close_all_names_the_whole_book_under_a_filter(self):
        body = self._get("/positions/?symbol=BTCUSD")
        button = re.search(r'<button[^>]*id="svCloseAll"[^>]*>([^<]*)</button>',
                           body)
        self.assertEqual(button.group(1).strip(), "Close all (whole book)")
        self.assertIn("not only the rows this filter shows", button.group(0))
        # No count on the button: it sits outside every live region, so a
        # number there would go stale after a fill. The count is in the
        # note, inside pos-open, which every sweep re-renders.
        self.assertNotRegex(button.group(0), r"\b[15]\b")
        self.assertIn("The totals above count all 5; Close all acts on the whole book.",
                      _region(body, "pos-open"))
        plain = re.search(r'<button[^>]*id="svCloseAll"[^>]*>([^<]*)</button>',
                          self._get("/positions/"))
        self.assertEqual(plain.group(1).strip(), "Close all")
        self.assertNotIn("title=", plain.group(0))

    def test_the_live_fragment_renders_the_same_table(self):
        query = "?sort=-opened&group=class&side=long"
        page = self._get("/positions/" + query)
        frag = self._get("/positions/live/" + query)
        self.assertEqual(_keys(frag, "pos-open"), _keys(page, "pos-open"))
        self.assertEqual(len(_keys(frag, "pos-open")), 4)
        self.assertEqual(_region(frag, "pos-open").count("pos-group-row"),
                         _region(page, "pos-open").count("pos-group-row"))
        self.assertIn("Showing <b>4</b> of <b>5</b>", _region(frag, "pos-open"))
        page_cells, frag_cells = cells(page), cells(frag)
        for key, value in frag_cells.items():
            self.assertEqual(page_cells[key], value, key)
        # The bar stays out of the fragment: a sweep never swaps a select
        # out from under the operator.
        self.assertIn("data-pos-filter", page)
        self.assertNotIn("data-pos-filter", frag)

    def test_an_asset_no_longer_held_turns_the_filter_off_and_says_so(self):
        body = self._get("/positions/?symbol=PVGONE")
        region = _region(body, "pos-open")
        self.assertIn("No open positions match asset <b>PVGONE</b>, so that "
                      "filter is off.", region)
        self.assertEqual(_keys(body, "pos-open"), self.bought)
        self.assertNotIn("Showing <b>", region)
        # The live fragment says the same thing on the next sweep.
        self.assertIn("so that filter is off",
                      _region(self._get("/positions/live/?symbol=PVGONE"),
                              "pos-open"))

    def test_a_crafted_value_is_not_repeated_on_the_page(self):
        body = self._get("/positions/?symbol=MARGIN%20CALL%20-%20close%20"
                         "everything%20now")
        self.assertIn("The asset asked for is not among the open positions, "
                      "so that filter is off.", _region(body, "pos-open"))
        self.assertNotIn("MARGIN CALL", body)
        self.assertNotIn("close everything", body)
        self.assertEqual(_keys(body, "pos-open"), self.bought)

    def test_each_group_row_spans_every_column_of_the_table(self):
        """cols=14 is written in the include: a column added to the table
        later must fail here, not leave the group headers short."""
        region = _region(self._get("/positions/?group=class"), "pos-open")
        thead = re.search(r"<thead>(.*?)</thead>", region, re.S).group(1)
        spans = re.findall(r'<tr class="pos-group-row"><th scope="rowgroup" '
                           r'colspan="(\d+)"', region)
        self.assertEqual(len(spans), 3)
        self.assertEqual(set(spans), {str(len(re.findall(r"<th[\s>]",
                                                         thead)))})

    def test_a_filter_that_matches_nothing_does_not_call_the_book_empty(self):
        body = self._get("/positions/?class=stock&side=short")
        region = _region(body, "pos-open")
        self.assertIn("NO OPEN POSITION MATCHES THIS FILTER", region)
        self.assertNotIn("NO OPEN POSITIONS", region)
        self.assertEqual(cells(body)["pos.open"], "5")

    def test_the_filter_bar_lists_what_the_book_holds(self):
        form = self._get("/positions/").split("data-pos-filter", 1)[1]
        form = form.split("</form>", 1)[0]
        self.assertIn('name="tab" value="open"', form)
        # Without script the Apply button is the whole mechanism.
        self.assertIn('<button type="submit"', form)
        for label in ("forex (2)", "crypto (2)", "stock (1)", "short (1)",
                      "long (4)", "live (1)", "paper (4)", "BTCUSD (1)"):
            self.assertIn(">%s<" % label, form)
        self.assertNotIn("pos-filter-clear", form)
        filtered = self._get("/positions/?class=forex").split(
            "data-pos-filter", 1)[1].split("</form>", 1)[0]
        self.assertIn('href="/positions/?tab=open"', filtered)
        self.assertIn('<option value="forex" selected>', filtered)

    def test_junk_params_render_200_in_purchase_order(self):
        for url in ("/positions/?sort=%27%3B--&class=%00&symbol=" + "X" * 300
                    + "&side=up&venue=moon&group=%3Cx%3E",
                    "/positions/live/?sort=zz&group=zz&class=zz",
                    "/positions/?tab=history&sort=pnl&group=nope&class=nope",
                    "/portfolio/?sort=closed&group=zz&side=zz",
                    "/portfolio/live/?venue=zz&symbol=%E2%80%94"):
            self._get(url)
        self.assertEqual(_keys(self._get("/positions/?sort=nonsense"),
                               "pos-open"), self.bought)


# ── 6. /positions/?tab=history ─────────────────────────────────────────────

class PositionsHistoryTabTests(_PageCase):
    def setUp(self):
        self.user = _user("pv_hist")
        self.client.force_login(self.user)
        now = timezone.now()
        for symbol, cls, bought, closed, pnl in (
                ("PVAAA", "crypto", 10, 3, "10"),
                ("PVBBB", "crypto", 9, 1, "-10"),
                ("PVCCC", "forex", 8, 2, "5")):
            _trade(self.user, symbol, cls, bought, status="CLOSED",
                   exit_price=Decimal("100"), pnl=Decimal(pnl),
                   closed_at=now - timedelta(days=closed))

    def _order(self, query=""):
        body = self._get("/positions/?tab=history" + query)
        listing = body.split('class="ph-list"', 1)[1]
        return re.findall(r'class="ph-sym">([^<]+)<', listing)

    def test_the_newest_close_leads_by_default(self):
        self.assertEqual(self._order(), ["PVBBB", "PVCCC", "PVAAA"])

    def test_sort_closed_is_the_oldest_close_first(self):
        self.assertEqual(self._order("&sort=closed"),
                         ["PVAAA", "PVCCC", "PVBBB"])

    def test_purchase_order_on_the_history_too(self):
        self.assertEqual(self._order("&sort=opened"),
                         ["PVAAA", "PVBBB", "PVCCC"])

    def test_groups_on_the_history(self):
        body = self._get("/positions/?tab=history&group=class&sort=closed")
        self.assertEqual(body.count('class="ph-group-row"'), 2)
        got = cells(body)
        self.assertEqual(got["ph.group.class.crypto.pnl"], "+0.00")
        self.assertEqual(got["ph.group.class.forex.pnl"], "+5.00")
        self.assertEqual(self._order("&group=class&sort=closed"),
                         ["PVAAA", "PVBBB", "PVCCC"])

    def test_the_form_keeps_the_history_tab(self):
        body = self._get("/positions/?tab=history&class=forex")
        self.assertIn('name="tab" value="history"', body)
        self.assertIn("Showing <b>1</b> of <b>3</b> closed trades", body)
        self.assertEqual(self._order("&class=forex"), ["PVCCC"])


# ── 7. /portfolio/'s open table ────────────────────────────────────────────

class PortfolioTableTests(_PageCase):
    def setUp(self):
        self.user = _user("pv_pf")
        self.client.force_login(self.user)
        _quote("BTCUSD", "110", "crypto")
        self.mid = _trade(self.user, "BTCUSD", "crypto", 2)
        self.old = _trade(self.user, "EURUSD", "forex", 3)
        self.new = _trade(self.user, "ETHUSD", "crypto", 1)
        self.bought = ["bot-%d" % t.id for t in (self.old, self.mid, self.new)]

    def test_sort_opened_orders_the_table_by_opened_at(self):
        self.assertEqual(_keys(self._get("/portfolio/?sort=opened"), "pf-open"),
                         self.bought)
        self.assertEqual(_keys(self._get("/portfolio/?sort=-opened"),
                               "pf-open"), self.bought[::-1])

    def test_purchase_order_is_the_default(self):
        self.assertEqual(_keys(self._get("/portfolio/"), "pf-open"),
                         self.bought)

    def test_the_live_fragment_renders_the_same_table(self):
        query = "?sort=-opened&group=class"
        page = self._get("/portfolio/" + query)
        frag = self._get("/portfolio/live/" + query)
        self.assertEqual(_keys(frag, "pf-open"), _keys(page, "pf-open"))
        self.assertEqual(_region(frag, "pf-open").count('class="pos-group-row"'),
                         2)
        self.assertIn("data-pos-filter", page)
        self.assertNotIn("data-pos-filter", frag)

    def test_each_group_row_spans_every_column_of_the_table(self):
        region = _region(self._get("/portfolio/?group=class"), "pf-open")
        thead = re.search(r"<thead>(.*?)</thead>", region, re.S).group(1)
        spans = re.findall(r'<tr class="pos-group-row"><th scope="rowgroup" '
                           r'colspan="(\d+)"', region)
        self.assertEqual(len(spans), 2)
        self.assertEqual(set(spans), {str(len(re.findall(r"<th[\s>]",
                                                         thead)))})

    def test_a_filter_matching_the_whole_book_still_says_it_is_on(self):
        """Every row here is long: ?side=long narrows nothing, and the
        table still says a filter is on and what it counts."""
        region = _region(self._get("/portfolio/?side=long"), "pf-open")
        self.assertIn("Showing <b>3</b> of <b>3</b> open positions · side "
                      "<b>long</b>", region)

    def test_a_group_the_cap_cuts_still_reads_its_whole_total(self):
        """10 open, eight rows listed: a group's count and sums cover all
        of its rows, the ones past the cap included, and it says how many
        the table lists. The donut above sizes the same totals."""
        for i in range(7):
            _trade(self.user, "PVX%d" % i, "stock", 10 + i)
        # Newest first: ETHUSD, BTCUSD, EURUSD, then five of the seven
        # PVX — stock is split by the cap.
        body = self._get("/portfolio/?group=class&sort=-opened")
        region = _region(body, "pf-open")
        self.assertEqual(region.count('class="pos-group-row"'), 3)
        stock = re.search(r'pos-group-name">stock</span>(.*?)</tr>', region,
                          re.S).group(1)
        self.assertIn('<span class="pos-group-n">7 positions</span>'
                      '<span class="pos-group-cut"', stock)
        self.assertIn(">5 of 7 shown<", stock)
        # 7 x 1 x 100 at entry cost (no quote): all seven, not the five.
        self.assertIn("exposure <b>700.00</b>", stock)
        crypto = re.search(r'pos-group-name">crypto</span>(.*?)</tr>', region,
                           re.S).group(1)
        self.assertNotIn("pos-group-cut", crypto)
        self.assertEqual(len(_keys(body, "pf-open")), 8)
        # Purchase order: crypto (BTCUSD, ETHUSD) is bought last and the
        # cap keeps both off the table; its header stays, summing both.
        body = self._get("/portfolio/?group=class")
        region = _region(body, "pf-open")
        crypto = re.search(r'pos-group-name">crypto</span>(.*?)</tr>', region,
                           re.S).group(1)
        self.assertIn(">0 of 2 shown<", crypto)
        self.assertEqual(cells(body)["pf.group.class.crypto.pnl"], "+10.00")
        self.assertEqual(cells(body)["pf.open"], "10")

    def test_the_eight_row_cap_comes_after_the_sort_and_says_so(self):
        extra = [_trade(self.user, "PVX%d" % i, "stock", 10 + i)
                 for i in range(7)]
        body = self._get("/portfolio/")
        # The eight bought first: the seven PVX (10..16 days ago), then
        # EURUSD (3 days ago); BTCUSD and ETHUSD fall past the cap.
        oldest = ["bot-%d" % t.id for t in reversed(extra)] + [self.bought[0]]
        self.assertEqual(_keys(body, "pf-open"), oldest)
        self.assertIn("Showing <b>8</b> of <b>10</b> open positions",
                      _region(body, "pf-open"))
        self.assertEqual(cells(body)["pf.open"], "10")

    def test_a_filter_narrows_the_table_and_not_the_strip(self):
        resp = self.client.get("/portfolio/?class=crypto", HTTP_HOST=HOST)
        body = resp.content.decode()
        self.assertEqual(_keys(body, "pf-open"),
                         ["bot-%d" % self.mid.id, "bot-%d" % self.new.id])
        self.assertEqual(resp.context["open_positions_count"], 3)
        self.assertEqual(cells(body)["pf.open"], "3")
        self.assertIn("Showing <b>2</b> of <b>3</b>", body)
