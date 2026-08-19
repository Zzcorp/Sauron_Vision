"""The portfolio and positions pages: true, and moving.

Both pages computed everything once, at render, and nothing recomputed it — so
the two screens that hold the operator's money sat frozen at whatever they said
when they were opened. Worse, what they said was partly fiction: the open P&L
was summed off Position.unrealized_pnl, a column NOTHING in this codebase ever
writes on the book these pages read, so it renders +0.00 forever.

What is asserted here:
  - open P&L and exposure are derived from live marks, never from that column
  - both position books are counted (portfolio.Position AND AssetBotTrade)
  - R is measured against the stop the trade OPENED with, not the trailed one,
    and is an em-dash when there is no stop or no mark — never 0.0R
  - the refresh endpoint renders the SAME regions the page rendered, with the
    same values and the same em-dashes
  - the page rides the shell's /ws/eye/ events and never opens its own socket,
    never polls unconditionally, and never polls at all on the fast cadence
    while the socket is up
  - an unpriced position renders a dash on the first render AND on a refresh

Run with:  python manage.py test tests.test_portfolio_live
"""
import html
import re
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone


# ── Fixtures ─────────────────────────────────────────────────────────────

def _user(name="pfl_u"):
    return User.objects.create_user(username=name, password="x")


def _instrument(symbol, asset_class="crypto"):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class})
    return inst


def _quote(symbol, last, asset_class="crypto"):
    from market_data.models import LiveQuote
    inst = _instrument(symbol, asset_class)
    quote, _ = LiveQuote.objects.update_or_create(
        instrument=inst, defaults={"last": Decimal(str(last)),
                                   "source": "test"})
    return quote


def _book():
    """The SHARED "Main" portfolio — the book both pages read."""
    from portfolio.services import get_or_create_default_portfolio
    return get_or_create_default_portfolio()


def _position(symbol="AAPL", qty="1", entry="100", current="100",
              direction="long", stored_pnl="0", asset_class="stock",
              stop=None, closed=False):
    """A legacy portfolio.Position. `stored_pnl` writes the dead column on
    purpose, so a test can prove the page ignores it."""
    from portfolio.models import Position
    now = timezone.now()
    return Position.objects.create(
        portfolio=_book(), instrument=_instrument(symbol, asset_class),
        direction=direction, quantity=Decimal(qty),
        entry_price=Decimal(entry), current_price=Decimal(current),
        stop_loss=Decimal(stop) if stop is not None else None,
        unrealized_pnl=Decimal(stored_pnl),
        opened_at=now - timedelta(days=1),
        closed_at=now if closed else None)


def _config(user, name="B1", asset_class="crypto", **kw):
    from bot_program.models import AssetBotConfig
    defaults = dict(enabled=True, mode="paper", symbols=[],
                    capital=Decimal("10000"), base_currency="USD")
    defaults.update(kw)
    return AssetBotConfig.objects.create(
        user=user, asset_class=asset_class, name=name, **defaults)


def _trade(user, symbol="BTCUSD", status="OPEN", side="BUY", qty="1",
           entry="100", config=None, **kw):
    from bot_program.models import AssetBotTrade
    cfg = config or _config(user, name=f"cfg-{symbol}-{status}-{id(user)}")
    return AssetBotTrade.objects.create(
        config=cfg, asset_class=cfg.asset_class, symbol=symbol, side=side,
        qty=Decimal(qty), entry_price=Decimal(entry), status=status, **kw)


DASH = "—"


def cells(body):
    """{live key: the text an operator reads in that cell}.

    The refresh works by matching data-sv-live-key, so reading the page the
    same way the browser does is what makes "the endpoint returns what the
    page rendered" a real assertion rather than a substring check.
    """
    out = {}
    for m in re.finditer(r'data-sv-live-key="([^"]+)"[^>]*>', body):
        window = body[m.end():m.end() + 400]
        window = window.split("</td>")[0].split("</span>")[0]
        out[m.group(1)] = html.unescape(re.sub(r"<[^>]+>", "", window)).strip()
    return out


def regions(body):
    return set(re.findall(r'data-sv-live="([^"]+)"', body))


# ── 1. P&L comes from marks, not from the dead column ────────────────────

class MarkedNotStoredTests(TestCase):
    """Position.unrealized_pnl defaults to 0 and its only writer is an hourly
    task; on the book these pages read it is a permanent, confident +0.00."""

    def setUp(self):
        self.user = _user("pfl_marks")

    def _book_now(self):
        from dashboard.views import _live_open_book
        return _live_open_book(self.user, _book())

    def test_legacy_row_is_repriced_and_the_stored_column_ignored(self):
        _quote("AAPL", "105", asset_class="stock")
        _position("AAPL", qty="1", entry="100", stored_pnl="999")
        _objs, rows, n_priced, unrealized, _dep = self._book_now()
        self.assertEqual(n_priced, 1)
        self.assertEqual(unrealized, 5.0)
        self.assertEqual(rows[0]["unrealized_pnl"], 5.0)

    def test_bot_row_is_marked_to_the_live_quote(self):
        _quote("BTCUSD", "110")
        _trade(self.user, "BTCUSD", qty="2", entry="100")
        _objs, _rows, _n, unrealized, _dep = self._book_now()
        self.assertEqual(unrealized, 20.0)

    def test_short_side_flips_the_sign(self):
        _quote("BTCUSD", "110")
        _trade(self.user, "BTCUSD", side="SELL", qty="2", entry="100")
        _objs, _rows, _n, unrealized, _dep = self._book_now()
        self.assertEqual(unrealized, -20.0)

    def test_an_unpriced_book_is_unknown_not_flat(self):
        """Reporting +0.00 for a position nothing could price is a claim that
        the position is break-even."""
        _position("NOQUOTE", qty="1", entry="100", stored_pnl="999")
        _objs, rows, n_priced, unrealized, deployed = self._book_now()
        self.assertEqual(len(rows), 1)
        self.assertEqual(n_priced, 0)
        self.assertIsNone(unrealized)
        self.assertIsNone(deployed)
        self.assertIsNone(rows[0]["unrealized_pnl"])
        self.assertEqual(rows[0]["pnl_text"], DASH)


# ── 2. Both books ────────────────────────────────────────────────────────

class BothBooksTests(TestCase):
    """Exposure lives in portfolio.Position AND bot_program.AssetBotTrade.
    Reading one of them showed an empty book to an operator holding trades."""

    def setUp(self):
        self.user = _user("pfl_union")
        self.client.force_login(self.user)

    def test_the_open_book_unions_both(self):
        from dashboard.views import _live_open_book
        _position("AAPL")
        _trade(self.user, "BTCUSD")
        _objs, rows, _n, _u, _d = _live_open_book(self.user, _book())
        self.assertEqual(len(rows), 2)
        self.assertEqual({r["symbol"] for r in rows}, {"AAPL", "BTCUSD"})

    def test_close_pending_still_counts_as_exposure(self):
        from dashboard.views import _live_open_book
        _trade(self.user, "BTCUSD", status="CLOSE_PENDING")
        _objs, rows, _n, _u, _d = _live_open_book(self.user, _book())
        self.assertEqual(len(rows), 1)

    def test_both_pages_count_the_union(self):
        _position("AAPL")
        _trade(self.user, "BTCUSD")
        pf = self.client.get("/portfolio/", HTTP_HOST="127.0.0.1")
        pos = self.client.get("/positions/", HTTP_HOST="127.0.0.1")
        self.assertEqual(pf.context["open_positions_count"], 2)
        self.assertEqual(len(pos.context["positions"]), 2)
        self.assertEqual(cells(pf.content.decode())["pf.open"], "2")
        self.assertEqual(cells(pos.content.decode())["pos.open"], "2")

    def test_the_two_pages_agree_on_open_pnl(self):
        """One union-and-mark feeds both, so they cannot quote two P&Ls."""
        _quote("BTCUSD", "110")
        _trade(self.user, "BTCUSD", qty="1", entry="100")
        pf = cells(self.client.get(
            "/portfolio/", HTTP_HOST="127.0.0.1").content.decode())
        pos = cells(self.client.get(
            "/positions/", HTTP_HOST="127.0.0.1").content.decode())
        self.assertEqual(pf["pf.unrealized"], "+10.00")
        self.assertEqual(pos["pos.unrealized"], "+10.00")


# ── 3. R against the risk the trade was taken with ───────────────────────

class RMultipleTests(TestCase):
    def setUp(self):
        self.user = _user("pfl_r")
        self.client.force_login(self.user)

    def _row(self):
        from dashboard.views import _live_open_book
        _objs, rows, _n, _u, _d = _live_open_book(self.user, _book())
        return rows[0]

    def test_r_uses_the_entry_stop_not_the_trailed_one(self):
        """A trailing stop rewrites stop_loss. Grading against it makes risk
        and P&L the same quantity, and every trailed winner scores ~1.0R."""
        _quote("BTCUSD", "110")
        _trade(self.user, "BTCUSD", qty="1", entry="100",
               stop_loss=Decimal("105"),
               metadata={"initial_stop_loss": 90.0})
        row = self._row()
        # (110 - 100) / |100 - 90| = 1.0. Against the trailed stop it would
        # have read 2.0.
        self.assertEqual(row["r_multiple"], 1.0)
        self.assertEqual(row["r_text"], "+1.00R")

    def test_a_short_running_against_it_reads_negative(self):
        _quote("BTCUSD", "110")
        _trade(self.user, "BTCUSD", side="SELL", qty="1", entry="100",
               metadata={"initial_stop_loss": 105.0})
        self.assertEqual(self._row()["r_multiple"], -2.0)

    def test_no_stop_means_no_r_not_zero_r(self):
        """0.0R reads as a scratch trade sitting exactly at entry."""
        _quote("BTCUSD", "110")
        _trade(self.user, "BTCUSD", qty="1", entry="100")
        row = self._row()
        self.assertIsNone(row["r_multiple"])
        self.assertEqual(row["r_text"], DASH)

    def test_no_mark_means_no_r(self):
        _trade(self.user, "NOQUOTE", qty="1", entry="100",
               metadata={"initial_stop_loss": 90.0})
        self.assertIsNone(self._row()["r_multiple"])

    def test_a_legacy_row_grades_against_its_own_stop(self):
        _quote("AAPL", "110", asset_class="stock")
        _position("AAPL", qty="1", entry="100", stop="90")
        self.assertEqual(self._row()["r_multiple"], 1.0)

    def test_a_failing_stop_lookup_is_logged_and_dashes_the_column(self):
        """Swallowing this silently would leave a column of em-dashes with no
        explanation anywhere — not on the page, not in the log."""
        from unittest.mock import patch
        from dashboard.views import _live_open_book
        _quote("BTCUSD", "110")
        _trade(self.user, "BTCUSD", qty="1", entry="100",
               metadata={"initial_stop_loss": 90.0})
        with patch("bot_program.manual_close._initial_stop",
                   side_effect=RuntimeError("stop store down")):
            with self.assertLogs("dashboard.views", level="WARNING") as log:
                _objs, rows, _n, unrealized, _d = _live_open_book(
                    self.user, _book())
        self.assertTrue(any("stop store down" in line for line in log.output))
        self.assertIsNone(rows[0]["r_multiple"])
        self.assertEqual(rows[0]["r_text"], DASH)
        # The P&L does not depend on the stop and must survive intact.
        self.assertEqual(unrealized, 10.0)

    def test_both_pages_print_the_r_column(self):
        _quote("BTCUSD", "110")
        _trade(self.user, "BTCUSD", qty="1", entry="100",
               metadata={"initial_stop_loss": 90.0})
        for url in ("/positions/", "/portfolio/"):
            body = self.client.get(url, HTTP_HOST="127.0.0.1").content.decode()
            self.assertIn('<th class="num">R</th>', body, url)
            self.assertIn("+1.00R", body, url)


# ── 4. Unknown renders as an em-dash, never a zero ───────────────────────

class EmDashNotZeroTests(TestCase):
    def setUp(self):
        self.user = _user("pfl_dash")
        self.client.force_login(self.user)

    def test_no_positions_means_no_open_pnl_measurement(self):
        body = self.client.get("/portfolio/", HTTP_HOST="127.0.0.1").content.decode()
        self.assertEqual(cells(body)["pf.unrealized"], DASH)

    def test_win_rate_and_profit_factor_start_unmeasured(self):
        """0.0% over zero closed trades claims every trade lost."""
        for url, prefix in (("/portfolio/", "pf"), ("/positions/", "pos")):
            got = cells(self.client.get(
                url, HTTP_HOST="127.0.0.1").content.decode())
            self.assertEqual(got[f"{prefix}.win_rate"], DASH, url)
            self.assertEqual(got[f"{prefix}.profit_factor"], DASH, url)

    def test_drawdown_without_a_snapshot_is_not_zero(self):
        body = self.client.get("/portfolio/", HTTP_HOST="127.0.0.1").content.decode()
        self.assertEqual(cells(body)["pf.max_dd"], DASH)

    def test_an_unpriced_position_dashes_its_row(self):
        _trade(self.user, "NOQUOTE", qty="1", entry="100")
        got = cells(self.client.get(
            "/positions/", HTTP_HOST="127.0.0.1").content.decode())
        row = [k for k in got if k.endswith(".pnl")][0].split(".")[0]
        self.assertEqual(got[f"{row}.pnl"], DASH)
        self.assertEqual(got[f"{row}.pct"], DASH)
        self.assertEqual(got[f"{row}.last"], DASH)
        self.assertEqual(got[f"{row}.r"], DASH)

    def test_an_unpriced_book_does_not_claim_to_be_all_cash(self):
        """100% cash is a claim of no exposure, on a book carrying some."""
        _trade(self.user, "NOQUOTE", qty="1", entry="100")
        got = cells(self.client.get(
            "/portfolio/", HTTP_HOST="127.0.0.1").content.decode())
        self.assertEqual(got["pf.exposure"], DASH)
        self.assertIn("unknown", got["pf.cash.sub"])

    def test_every_live_cell_carries_a_tooltip(self):
        """A four-character number cannot say which book it counted, or how
        many of its rows it could actually price."""
        for url in ("/portfolio/", "/positions/"):
            response = self.client.get(url, HTTP_HOST="127.0.0.1")
            for key, cell in response.context["strip"].items():
                self.assertTrue(cell["title"].strip(),
                                f"{url}{key} has no tooltip")


# ── 5. The refresh endpoint renders what the page rendered ───────────────

class RefreshShapeTests(TestCase):
    def setUp(self):
        self.user = _user("pfl_shape")
        self.client.force_login(self.user)
        _quote("BTCUSD", "110")
        _trade(self.user, "BTCUSD", qty="1", entry="100",
               metadata={"initial_stop_loss": 90.0})

    def _both(self, page, live):
        a = self.client.get(page, HTTP_HOST="127.0.0.1")
        b = self.client.get(live, HTTP_HOST="127.0.0.1")
        self.assertEqual(a.status_code, 200)
        self.assertEqual(b.status_code, 200)
        return a.content.decode(), b.content.decode()

    def test_portfolio_fragment_matches_the_page(self):
        page, frag = self._both("/portfolio/", "/portfolio/live/")
        self.assertTrue(regions(frag))
        self.assertTrue(regions(frag) <= regions(page))
        page_cells, frag_cells = cells(page), cells(frag)
        for key, value in frag_cells.items():
            self.assertEqual(page_cells[key], value, key)

    def test_positions_fragment_matches_the_page(self):
        page, frag = self._both("/positions/", "/positions/live/")
        self.assertTrue(regions(frag) <= regions(page))
        page_cells, frag_cells = cells(page), cells(frag)
        for key, value in frag_cells.items():
            self.assertEqual(page_cells[key], value, key)

    def test_an_unpriced_row_dashes_on_the_refresh_too(self):
        """The failure this whole shape exists to prevent: a second template
        with its own idea of what an unknown looks like."""
        _trade(self.user, "NOQUOTE", qty="1", entry="100")
        for page, live in (("/portfolio/", "/portfolio/live/"),
                           ("/positions/", "/positions/live/")):
            page_body, frag = self._both(page, live)
            frag_cells = cells(frag)
            dashed = [k for k, v in cells(page_body).items()
                      if v == DASH and k in frag_cells]
            self.assertTrue(dashed, page)
            for key in dashed:
                self.assertEqual(frag_cells[key], DASH, f"{page} {key}")

    def test_the_fragment_is_not_a_whole_page(self):
        """It must not drag the shell, the ticker or a second socket with it."""
        for live in ("/portfolio/live/", "/positions/live/"):
            body = self.client.get(live, HTTP_HOST="127.0.0.1").content.decode()
            self.assertNotIn("<html", body.lower(), live)
            self.assertNotIn("new WebSocket", body, live)
            self.assertNotIn("sv-metrics-wrapper", body, live)

    def test_the_numbers_move_between_two_calls(self):
        """The point of the endpoint: the mark moves, the next sweep differs."""
        before = cells(self.client.get(
            "/portfolio/live/", HTTP_HOST="127.0.0.1").content.decode())
        _quote("BTCUSD", "120")
        after = cells(self.client.get(
            "/portfolio/live/", HTTP_HOST="127.0.0.1").content.decode())
        self.assertEqual(before["pf.unrealized"], "+10.00")
        self.assertEqual(after["pf.unrealized"], "+20.00")

    def test_a_new_fill_appears_without_a_page_reload(self):
        body = self.client.get(
            "/positions/live/", HTTP_HOST="127.0.0.1").content.decode()
        self.assertNotIn("ETHUSD", body)
        _quote("ETHUSD", "50")
        _trade(self.user, "ETHUSD", qty="1", entry="49")
        body = self.client.get(
            "/positions/live/", HTTP_HOST="127.0.0.1").content.decode()
        self.assertIn("ETHUSD", body)

    def test_the_region_exists_before_the_first_position(self):
        """With the card hidden on an empty book there was nowhere for the
        first fill to land, so the page went on showing nothing."""
        other = _user("pfl_empty")
        self.client.force_login(other)
        body = self.client.get("/portfolio/", HTTP_HOST="127.0.0.1").content.decode()
        self.assertIn('data-sv-live="pf-open"', body)
        self.assertIn("NO OPEN POSITIONS", body)

    def test_the_history_tab_still_refreshes_its_strip(self):
        frag = self.client.get(
            "/positions/live/?tab=history", HTTP_HOST="127.0.0.1"
        ).content.decode()
        self.assertIn('data-sv-live="pos-strip"', frag)
        self.assertNotIn('data-sv-live="pos-open"', frag)

    def test_the_history_tab_page_still_renders_whole(self):
        """The live branch must not have eaten the tab it does not refresh."""
        _trade(self.user, "ETHUSD", status="CLOSED", qty="1", entry="100",
               exit_price=Decimal("110"), pnl=Decimal("10"),
               closed_at=timezone.now())
        response = self.client.get("/positions/?tab=history",
                                   HTTP_HOST="127.0.0.1")
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn("Trade History", body)
        self.assertIn("ETHUSD", body)
        self.assertIn('data-sv-live="pos-strip"', body)

    def test_the_endpoints_require_login(self):
        self.client.logout()
        for live in ("/portfolio/live/", "/positions/live/"):
            self.assertIn(self.client.get(live, HTTP_HOST="127.0.0.1")
                          .status_code, (302, 403), live)

    def test_the_endpoints_are_per_user(self):
        other = _user("pfl_other")
        _quote("ETHUSD", "50")
        _trade(other, "ETHUSD", qty="1", entry="49")
        body = self.client.get(
            "/positions/live/", HTTP_HOST="127.0.0.1").content.decode()
        self.assertNotIn("ETHUSD", body)


# ── 6. How it refreshes: events, not a poll ──────────────────────────────

class RefreshDisciplineTests(TestCase):
    def setUp(self):
        self.user = _user("pfl_disc")
        self.client.force_login(self.user)

    def _page(self, url="/positions/"):
        return self.client.get(url, HTTP_HOST="127.0.0.1").content.decode()

    def _script(self, body):
        self.assertIn("var LIVE_URL", body)
        return body.split("var LIVE_URL", 1)[1].split("</script>", 1)[0]

    def test_it_listens_on_the_shell_event_for_the_three_fill_kinds(self):
        for url in ("/portfolio/", "/positions/"):
            script = self._script(self._page(url))
            self.assertIn("sv:eye-event", script, url)
            for kind in ("fill_open", "fill_close", "close_pending"):
                self.assertIn(kind, script, f"{url} {kind}")

    def test_it_does_not_open_a_second_socket(self):
        """base.html owns the one /ws/eye/ connection. Counted against another
        page on the same base template, because base.html legitimately opens
        the sockets all of them share."""
        eye = self._page("/eye/")
        for url in ("/portfolio/", "/positions/"):
            self.assertEqual(self._page(url).count("new WebSocket"),
                             eye.count("new WebSocket"), url)

    def test_nothing_polls_on_the_fast_cadence_while_the_socket_is_up(self):
        """The sweep is gated on svLive.isUp() — with the socket up the fills
        announce themselves and only the drifting marks need a sweep."""
        for url in ("/portfolio/", "/positions/"):
            script = self._script(self._page(url))
            timer = script.split("setInterval(", 1)[1]
            self.assertIn("svLive", timer, url)
            self.assertIn("isUp()", timer, url)
            self.assertIn("UP_EVERY", timer, url)
            self.assertIn("document.hidden", timer, url)

    def test_no_region_is_left_on_an_unconditional_htmx_poll(self):
        """`hx-trigger="load, every 30s"` was exactly the fast unconditional
        poll this page is not allowed to run."""
        for url in ("/portfolio/", "/positions/"):
            self.assertNotRegex(self._page(url), r'hx-trigger="[^"]*every ',
                                url)

    def test_the_page_says_which_way_the_numbers_are_arriving(self):
        for url in ("/portfolio/", "/positions/"):
            body = self._page(url)
            self.assertIn("data-sv-live-status", body, url)
            self.assertIn("sv-live-offline", body, url)

    def test_movement_honours_reduced_motion(self):
        for url in ("/portfolio/", "/positions/"):
            self.assertIn("prefers-reduced-motion", self._script(self._page(url)))

    def test_a_changed_value_is_flashed_with_the_house_pulse(self):
        for url in ("/portfolio/", "/positions/"):
            self.assertIn("sc-changed", self._script(self._page(url)), url)


# ── 7. House rules on the two templates ──────────────────────────────────

class TemplateHygieneTests(TestCase):
    def test_no_multiline_hash_comment(self):
        """{# #} is single-line; spanning it renders the text verbatim."""
        from pathlib import Path
        from django.conf import settings
        base = Path(settings.BASE_DIR)
        for rel in (("templates", "dashboard", "positions_list.html"),
                    ("templates", "dashboard", "portfolio_overview.html"),
                    ("templates", "dashboard", "_live_shell.html"),
                    ("templates", "_partials", "live_region.html")):
            text = base.joinpath(*rel).read_text(encoding="utf-8")
            for m in re.finditer(r"\{#(.*?)#\}", text, re.S):
                self.assertNotIn("\n", m.group(1),
                                 f"{rel[-1]}: {m.group(1).strip()[:60]}")

    def test_no_comment_markup_reaches_the_browser(self):
        user = _user("pfl_hygiene")
        self.client.force_login(user)
        for url in ("/portfolio/", "/positions/", "/portfolio/live/",
                    "/positions/live/"):
            body = self.client.get(url, HTTP_HOST="127.0.0.1").content.decode()
            self.assertNotIn("{#", body, url)
            self.assertNotIn("{% comment", body, url)

    def test_the_wide_tables_still_scroll_inside_their_own_wrapper(self):
        """A card may not push the body sideways at 360px."""
        from pathlib import Path
        from django.conf import settings
        base = Path(settings.BASE_DIR) / "templates" / "dashboard"
        for name in ("positions_list.html", "portfolio_overview.html"):
            text = (base / name).read_text(encoding="utf-8")
            tables = text.count("<table")
            wrappers = text.count('<div class="table-wrapper">')
            self.assertGreaterEqual(wrappers, tables, name)
