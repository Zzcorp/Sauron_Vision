"""eToro's OWN P&L ON EVERY OPEN eTORO ROW (2026-11-06).

The operator's report, 2026-11-06: an open eToro forex row read a gain on
Sauron and a small loss in the eToro app. Sauron valued the open long at a
quote's LAST price (a public feed, minutes old) while eToro values a long
at its BID and a short at its ASK, in the account's currency, and prints each
position's own net profit on its /portfolio row. The sync already keeps
that figure (EtoroAccount.broker_positions, "net_profit", with the
position id), so every surface that shows an open eToro row's P&L now
asks one helper, portfolio.services.venue_pnl:

  1. eToro's own figure, when the stored holdings of the row's world list
     the row's position id with a number, read less than
     ETORO_PNL_MAX_AGE_S ago (source "etoro");
  2. else an eToro-written quote's CLOSING side (bid for a long, ask for a
     short), fresh, converted to USD (source "etoro_quote");
  3. else the platform's own mark-based figure (source "estimate").

Where the figure is not eToro's own the page says so ("estimate: <feed>
quote, <age>"). Never a figure eToro did not send: None stays None.

DISPLAY ONLY. Nothing that decides money reads the helper: the exits, the
stops, the care, the gates, the daily loss, Morgul, the Orcs, grading, the
treasury's used figures and every close's booking keep their own numbers
(the last class below scans them). No test here talks to eToro: the
holdings are written straight into the account row, and a constructed
EtoroTrader fails the test.

Run with:  python manage.py test tests.test_venue_pnl
"""
import ast
import html
import json
import re
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

HOST = "127.0.0.1"
SYMBOL = "EURCAD"
ENTRY, LAST, QTY, VPU = "1.50000", "1.50900", "2000", 0.72
STOP_LONG, STOP_SHORT = "1.49000", "1.51000"
PID = "3001"
#: The figure Sauron's mark gives the row: (1.509 - 1.5) x 2000 x 0.72.
ESTIMATE = 12.96
#: The figure eToro's holdings carry for the same position.
ETORO_NET = -1.15


# ── fixtures ─────────────────────────────────────────────────────────────

def _user(name="pnl_u"):
    return get_user_model().objects.create_user(name, password="x")


def _instrument(symbol=SYMBOL, asset_class="forex"):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class,
                                 "is_active": True})
    return inst


def _quote(last=LAST, *, symbol=SYMBOL, source="yfinance", bid=None,
           ask=None, age_s=None):
    """The platform's one quote row for `symbol`: `age_s` ages it (auto_now
    can only be moved by a queryset update)."""
    from market_data.models import LiveQuote
    inst = _instrument(symbol)
    q, _ = LiveQuote.objects.update_or_create(
        instrument=inst, defaults={
            "last": Decimal(str(last)), "source": source,
            "bid": None if bid is None else Decimal(str(bid)),
            "ask": None if ask is None else Decimal(str(ask))})
    if age_s is not None:
        LiveQuote.objects.filter(pk=q.pk).update(
            updated_at=timezone.now() - timedelta(seconds=age_s))
    return q


def _config(user, *, name="manual", mode="live"):
    from bot_program.models import AssetBotConfig
    return AssetBotConfig.objects.create(
        user=user, asset_class="forex", name=name, enabled=True, mode=mode,
        symbols=[], capital=Decimal("10000"), base_currency="USD")


def _row(cfg, *, side="BUY", pid=PID, env="live", broker="etoro",
         status="OPEN", paper=False, symbol=SYMBOL, stop=None, **extra):
    """An eToro row as both lanes book it: the venue stamps (broker,
    broker_env, broker_position_id), the sizing stamp (value_per_unit) and
    the stop it opened with."""
    from bot_program.models import AssetBotTrade
    stop = stop or (STOP_LONG if side == "BUY" else STOP_SHORT)
    meta = {"value_per_unit": VPU, "initial_stop_loss": float(stop),
            "leverage": 1}
    if broker:
        meta["broker"] = broker
    if env:
        meta["broker_env"] = env
    if pid:
        meta["broker_position_id"] = pid
    return AssetBotTrade.objects.create(
        config=cfg, asset_class="forex", symbol=symbol, side=side,
        qty=Decimal(QTY), entry_price=Decimal(ENTRY),
        stop_loss=Decimal(stop), status=status, paper=paper, metadata=meta,
        rule_name="manual_take", **extra)


def _holding(pid=PID, net=ETORO_NET, side="BUY", symbol=SYMBOL):
    """One /portfolio row as EtoroTrader.broker_portfolio stores it: the
    constants eToro's list does not carry, and the position's own id and
    net profit."""
    return {"symbol": symbol, "sec_type": "CFD", "qty": float(QTY),
            "side": side, "avg_cost": 1.5, "market_price": 0.0,
            "market_value": 0.0, "unrealized_pnl": 0.0, "currency": "",
            "leverage": 1, "position_id": pid, "amount": 3000.0,
            "net_profit": net}


def _held(user, rows, *, age_s=60, demo=False, keys=False, primary=False,
          currency="USD"):
    """The sync's snapshot, written as the sync writes it — no eToro call."""
    from bot_program.models import EtoroAccount
    acct, _ = EtoroAccount.objects.get_or_create(user=user)
    acct.demo = demo
    acct.broker_positions = rows
    acct.broker_positions_at = timezone.now() - timedelta(seconds=age_s)
    acct.last_equity_currency = currency
    acct.is_primary_for_forex = primary
    if keys:
        acct.set_credentials("fake-api-key", "fake-user-key")
    acct.save()
    return acct


def _no_venue_calls(case):
    """A tripwire: building an eToro client, or the Eye's live read, fails
    the test. The pages read the stored snapshot only."""
    for target in ("bot_program.engine.etoro_client.EtoroTrader.__init__",
                   "bot_program.telegram_eye.read_live_account"):
        patcher = mock.patch(target, side_effect=AssertionError(
            f"{target} was called: no test here talks to eToro"))
        patcher.start()
        case.addCleanup(patcher.stop)


def _text(fragment):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment or ""))
                    .split())


def _td(body, key):
    """The text of the table cell carrying data-sv-live-key=`key`."""
    m = re.search(r'data-sv-live-key="%s"[^>]*>(.*?)</td>' % re.escape(key),
                  body, re.S)
    return None if m is None else _text(m.group(1))


def _span(body, key):
    m = re.search(r'data-sv-live-key="%s"[^>]*>([^<]*)<' % re.escape(key),
                  body)
    return None if m is None else html.unescape(m.group(1)).strip()


class _Case(TestCase):

    def setUp(self):
        cache.clear()
        _no_venue_calls(self)
        self.user = _user()
        self.cfg = _config(self.user)
        _quote()


# ── 1. the helper ────────────────────────────────────────────────────────

class TheHelperTests(_Case):

    def test_the_report_shape_shows_etoros_own_figure(self):
        """A long whose public LAST is above eToro's bid, and whose stored
        netProfit is negative: eToro's figure, not the quote's gain."""
        from portfolio.services import (PNL_ETORO, unified_open_positions,
                                        venue_pnl)
        t = _row(self.cfg)
        acct = _held(self.user, [_holding()])
        up = unified_open_positions(self.user)[0]
        self.assertAlmostEqual(float(up.unrealized_pnl), ESTIMATE, places=2,
                               msg="the mark's figure Sauron printed")
        v = venue_pnl(t)
        self.assertEqual(v["source"], PNL_ETORO)
        self.assertAlmostEqual(v["pnl_usd"], ETORO_NET, places=6)
        self.assertEqual(v["at"], acct.broker_positions_at)
        self.assertEqual(v["words"], "", "eToro's own figure needs no excuse")
        # the percentage divides eToro's dollars by the entry's dollars
        self.assertAlmostEqual(v["pnl_pct"], -0.05, places=2)
        # R is eToro's P&L over the risk the row opened with (14.40 USD):
        # a mark R (+0.90R) beside -1.15 would contradict its own sign
        self.assertAlmostEqual(v["r"], ETORO_NET / 14.4, places=4)

    def test_a_stale_read_falls_back_with_the_words(self):
        from portfolio.services import (ETORO_PNL_MAX_AGE_S, PNL_ESTIMATE,
                                        venue_pnl)
        self.assertEqual(ETORO_PNL_MAX_AGE_S, 900)
        t = _row(self.cfg)
        _held(self.user, [_holding()], age_s=ETORO_PNL_MAX_AGE_S + 120)
        v = venue_pnl(t)
        self.assertEqual(v["source"], PNL_ESTIMATE)
        self.assertAlmostEqual(v["pnl_usd"], ESTIMATE, places=2)
        self.assertTrue(v["words"].startswith(
            "estimate: Yahoo Finance quote, "), v["words"])
        self.assertIn("read 17 min ago", v["title"])

    def test_a_short_is_valued_at_an_etoro_quotes_ask(self):
        from portfolio.services import PNL_ETORO_QUOTE, venue_pnl
        _quote(source="etoro", bid="1.50850", ask="1.50930")
        t = _row(self.cfg, side="SELL")
        v = venue_pnl(t)                       # no holdings stored at all
        self.assertEqual(v["source"], PNL_ETORO_QUOTE)
        # (1.5093 - 1.5) x 2000 x 0.72, a short: -13.39 — the ask, never the
        # last (-12.96) and never the bid (-12.24)
        self.assertAlmostEqual(v["pnl_usd"], -13.39, places=2)
        self.assertTrue(v["words"].startswith("estimate: eToro quote, "),
                        v["words"])

    def test_a_long_is_valued_at_an_etoro_quotes_bid(self):
        from portfolio.services import PNL_ETORO_QUOTE, venue_pnl
        _quote(source="etoro", bid="1.50850", ask="1.50930")
        t = _row(self.cfg)
        _held(self.user, [_holding()], age_s=3600)          # too old
        v = venue_pnl(t)
        self.assertEqual(v["source"], PNL_ETORO_QUOTE)
        self.assertAlmostEqual(v["pnl_usd"], 12.24, places=2)

    def test_another_feeds_sides_and_a_stale_etoro_quote_are_estimates(self):
        from portfolio.services import PNL_ESTIMATE, venue_pnl
        t = _row(self.cfg)
        _quote(source="oanda_stream", bid="1.50850", ask="1.50930")
        v = venue_pnl(t)
        self.assertEqual(v["source"], PNL_ESTIMATE)
        self.assertAlmostEqual(v["pnl_usd"], ESTIMATE, places=2)
        _quote(source="etoro", bid="1.50850", ask="1.50930", age_s=3600)
        v = venue_pnl(t)
        self.assertEqual(v["source"], PNL_ESTIMATE)

    def test_a_row_of_the_other_world_is_untouched(self):
        """The stored holdings are the demo account's: a live row's id in
        them is never its figure."""
        from portfolio.services import PNL_ESTIMATE, venue_pnl
        t = _row(self.cfg)
        _held(self.user, [_holding()], demo=True)
        v = venue_pnl(t)
        self.assertEqual(v["source"], PNL_ESTIMATE)
        self.assertAlmostEqual(v["pnl_usd"], ESTIMATE, places=2)
        self.assertIn("demo", v["title"])

    def test_a_row_with_no_position_id_is_untouched(self):
        from portfolio.services import PNL_ESTIMATE, venue_pnl
        t = _row(self.cfg, pid=None)
        _held(self.user, [_holding()])
        v = venue_pnl(t)
        self.assertEqual(v["source"], PNL_ESTIMATE)
        self.assertAlmostEqual(v["pnl_usd"], ESTIMATE, places=2)
        self.assertIn("no eToro position id", v["title"])

    def test_a_figure_etoro_did_not_send_is_never_invented(self):
        from market_data.models import LiveQuote
        from portfolio.services import PNL_ESTIMATE, venue_pnl
        t = _row(self.cfg)
        _held(self.user, [_holding(net=None)])
        v = venue_pnl(t)
        self.assertEqual(v["source"], PNL_ESTIMATE)
        self.assertAlmostEqual(v["pnl_usd"], ESTIMATE, places=2)
        # nothing marks the row at all: None stays None, never 0
        LiveQuote.objects.all().delete()
        v = venue_pnl(t)
        self.assertEqual(v["source"], PNL_ESTIMATE)
        self.assertIsNone(v["pnl_usd"])
        self.assertIsNone(v["pnl_pct"])

    def test_rows_etoro_does_not_carry_get_nothing(self):
        from portfolio.services import venue_pnl, venue_pnls
        paper = _row(_config(self.user, name="paper", mode="paper"),
                     paper=True)
        saxo = _row(self.cfg, broker="saxo")
        _held(self.user, [_holding()])
        self.assertIsNone(venue_pnl(paper))
        self.assertIsNone(venue_pnl(saxo))
        self.assertEqual(venue_pnls(self.user, [paper, saxo]), {})

    def test_a_closed_rows_booking_is_untouched(self):
        """A close keeps the P&L it booked, whatever eToro's list says."""
        from portfolio.services import (unified_closed_positions, venue_pnl,
                                        venue_pnls)
        t = _row(self.cfg, status="CLOSED", pnl=Decimal("-5.04"),
                 exit_price=Decimal("1.49650"), closed_at=timezone.now())
        _held(self.user, [_holding()])
        self.assertIsNone(venue_pnl(t))
        self.assertEqual(venue_pnls(self.user, [t]), {})
        closed = unified_closed_positions(self.user)
        self.assertEqual(len(closed), 1)
        self.assertAlmostEqual(float(closed[0].unrealized_pnl), -5.04,
                               places=6)
        self.client.force_login(self.user)
        body = self.client.get("/positions/?tab=history",
                               HTTP_HOST=HOST).content.decode()
        self.assertIn("-5.04", body)
        self.assertNotIn("-1.15", body)

    def test_the_book_value_is_not_moved(self):
        """live_book_value — the gate denominator's writer — keeps its own
        sum: its rows and its open P&L are the marks', unchanged."""
        from portfolio.services import live_book_value
        _row(self.cfg)
        _held(self.user, [_holding()])
        book = live_book_value(self.user)
        self.assertAlmostEqual(book.unrealized, ESTIMATE, places=2)
        self.assertAlmostEqual(float(book.rows[0].unrealized_pnl), ESTIMATE,
                               places=2)
        self.assertAlmostEqual(book.funded_marked,
                               round(1.509 * 2000 * VPU, 2), places=2)


# ── 2. every surface that shows it ───────────────────────────────────────

class TheSurfacesTests(_Case):

    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)
        self.t = _row(self.cfg)
        self.acct = _held(self.user, [_holding()])

    def _get(self, url):
        r = self.client.get(url, HTTP_HOST=HOST)
        self.assertEqual(r.status_code, 200, url)
        return r.content.decode()

    def test_the_positions_page_row_strip_card_and_live_region(self):
        for url in ("/positions/", "/positions/live/"):
            body = self._get(url)
            key = f"bot-{self.t.id}"
            self.assertEqual(_td(body, f"{key}.pnl"), "-1.15", url)
            self.assertEqual(_td(body, f"{key}.pct"), "-0.05%", url)
            self.assertEqual(_td(body, f"{key}.r"), "-0.08R", url)
            self.assertEqual(_span(body, "pos.unrealized"), "-1.15", url)
            self.assertIn('data-pos-pnl="-1.15"', body, url)
            self.assertIn('data-pos-net-now="-1.15"', body, url)
            self.assertIn('data-pos-value-now="2,158.85"', body, url)
            self.assertNotIn("estimate:", body, url)

    def test_an_estimate_says_so_on_the_positions_page(self):
        _held(self.user, [_holding()], age_s=3600)
        body = self._get("/positions/")
        cell = _td(body, f"bot-{self.t.id}.pnl")
        self.assertTrue(cell.startswith("+12.96 estimate: Yahoo Finance "
                                        "quote, "), cell)
        self.assertEqual(_span(body, "pos.unrealized"), "+12.96")

    def test_the_at_the_broker_panel_prints_etoros_net_profit(self):
        _held(self.user, [_holding()], keys=True, primary=True)
        body = self._get("/positions/")
        panel = body.split("At the broker", 1)[1].split("</table>", 1)[0]
        row = panel.split(f">{SYMBOL}<", 1)[1][:600]
        self.assertRegex(row, r'data-label="Mark">(?:&mdash;|—)<')
        self.assertRegex(row, r'data-label="Value">(?:&mdash;|—)<')
        self.assertRegex(row, r'data-label="Unreal P&amp;L" '
                              r'class="bkp-down">-1\.15<')
        self.assertIn("CLAIMED", row)

    def test_the_portfolio_page(self):
        for url in ("/portfolio/", "/portfolio/live/"):
            body = self._get(url)
            self.assertEqual(_td(body, f"bot-{self.t.id}.pnl"), "-1.15", url)
            self.assertEqual(_span(body, "pf.unrealized"), "-1.15", url)
            self.assertEqual(_span(body, "pf.unrealized_live"), "-1.15", url)

    def test_the_headband(self):
        from tests.test_headband_truth import _ctx
        ctx = _ctx(self.user)
        self.assertAlmostEqual(ctx["panel_open_pnl"], ETORO_NET, places=6)
        self.assertAlmostEqual(ctx["panel_open_pnl_live"], ETORO_NET,
                               places=6)
        row = ctx["panel_open_rows"][0]
        self.assertAlmostEqual(row["pnl"], ETORO_NET, places=6)
        self.assertAlmostEqual(row["pct"], -0.05, places=2)
        self.assertAlmostEqual(row["r"], -0.08, places=2)
        self.assertEqual(ctx["panel_open_r_live_display"], "-0.08R")

    def test_the_ops_center_head_and_portfolio_tab(self):
        from dashboard.views_command import _tab_bar_metrics
        # Updated deliberately 2026-11-07 (Operations Center OC0): every
        # money cell carries its currency, and the LIVE head prints REAL's
        # own open P&L (spec §5.2, OC0). The meaning is kept: the head is
        # eToro's own figure for the row, never the marks' (no "≈").
        self.assertEqual(_tab_bar_metrics(self.user)["live"]["secondary"],
                         "-1.15 USD")
        body = self._get("/command/tab/portfolio/")
        table = body.split("Open positions", 1)[1]
        self.assertIn("-1.15", table)
        self.assertNotIn("12.96", table)
        strip = body.split("UNREALIZED P&amp;L", 1)[1][:300]
        self.assertIn("-1.15", strip)

    def test_the_digest_line(self):
        from alerts.digest_book import book_sections
        real = book_sections(self.user)["real_money"]["positions"]
        self.assertEqual(len(real), 1)
        self.assertAlmostEqual(real[0]["pnl"], ETORO_NET, places=6)
        self.assertIn("-0.05% · -1.15 USD", real[0]["line"])

    def test_the_digest_line_says_an_estimate(self):
        from alerts.digest_book import book_sections
        _held(self.user, [_holding()], age_s=3600)
        line = book_sections(self.user)["real_money"]["positions"][0]["line"]
        self.assertIn("+12.96 USD · estimate: Yahoo Finance quote, ", line)

    def test_the_position_page(self):
        from dashboard.position_summary import build_summary
        summary = build_summary(self.t)
        self.assertEqual(summary["big_value"], "-1.15 USD")
        self.assertIn("eToro's own figure", summary["big_sub"])
        _held(self.user, [_holding()], age_s=3600)
        summary = build_summary(self.t)
        self.assertEqual(summary["big_value"], "+12.96 USD")
        self.assertIn("estimate: Yahoo Finance quote, ", summary["big_sub"])

    def test_the_horde_seat(self):
        from dashboard import horde
        board = horde.board(self.user)
        seats = [s for g in board["groups"] for s in g["seats"]]
        seat = next(s for s in seats if s["key"] == f"bot:{self.t.id}")
        self.assertAlmostEqual(seat["money"]["pnl_v"], ETORO_NET, places=6)
        self.assertEqual(seat["money"]["pnl_t"], "-1.15")
        self.assertEqual(seat["money"]["ccy"], "USD")
        self.assertEqual(seat["money"]["r_t"], "-0.08R")
        detail = horde.seat_detail(self.user, f"bot:{self.t.id}")
        self.assertEqual(detail["seat"]["money"]["pnl_t"], "-1.15")


# ── 3. no decision path reads it ─────────────────────────────────────────

#: Every module that decides money: the exits, the stops, the care, the
#: gates, the daily loss, Morgul, the Orcs (and their dossiers), grading,
#: the treasury's used figures, the closes and their booking, the reviewer
#: — and the agents that hand the open positions to a model (ai_agents,
#: the review of 2026-11-06).
DECISION_TREES = ("bot_program", "brain", "ai_agents")
DECISION_FILES = ("portfolio/risk_gate.py", "portfolio/tasks.py",
                  "portfolio/position_sizing.py", "market_data/bot_bars.py")
#: Functions shared by a page and a decision: their bodies stay the marks'.
SHARED = {
    "portfolio/services.py": (
        "live_book_value", "_trade_to_position", "_normalize_trades",
        "unified_open_positions", "unified_closed_positions",
        "capital_summary", "usd_per_unit", "notional_usd",
        "pnl_on_capital_pct", "_capital_at_work"),
    "dashboard/views_command.py": ("_open_book", "_reprice_legacy"),
}
#: Every public name of the section, each of which carries eToro's
#: figure: the helper and every wrapper that hands it on (the review of
#: 2026-11-06: ShownRow writes it into unrealized_pnl on a row shaped like
#: the book's, so a decision reading "the open book" through
#: shown_open_rows would take it for the marks). The guard below keeps
#: this set whole as the section grows.
HELPER_NAMES = {"venue_pnl", "venue_pnls", "venue_pnls_for_rows",
                "shown_open_rows", "shown_unrealized", "ShownRow",
                "etoro_carried", "shown_book"}
#: The section head the guard reads the section's names from.
SECTION_HEAD = "# ── THE VENUE'S OWN P&L"


def _names(tree):
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            out.add(node.id)
        elif isinstance(node, ast.Attribute):
            out.add(node.attr)
        elif isinstance(node, ast.alias):
            out.add(node.name.rsplit(".", 1)[-1])
    return out


class NoDecisionPathTests(SimpleTestCase):

    def _files(self):
        base = Path(settings.BASE_DIR)
        for tree in DECISION_TREES:
            for path in sorted((base / tree).rglob("*.py")):
                if "migrations" in path.parts or "__pycache__" in path.parts:
                    continue
                yield path
        for rel in DECISION_FILES:
            yield base / rel

    def test_no_decision_path_imports_the_helper(self):
        seen = 0
        for path in self._files():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            hit = _names(tree) & HELPER_NAMES
            self.assertFalse(hit, f"{path} reads {sorted(hit)}")
            seen += 1
        self.assertGreater(seen, 100, "the scan found the decision modules")

    def test_the_shared_readers_keep_the_marks(self):
        base = Path(settings.BASE_DIR)
        for rel, funcs in SHARED.items():
            tree = ast.parse((base / rel).read_text(encoding="utf-8"))
            found = {n.name: n for n in ast.walk(tree)
                     if isinstance(n, ast.FunctionDef) and n.name in funcs}
            self.assertEqual(set(found), set(funcs), rel)
            for name, node in found.items():
                hit = _names(node) & HELPER_NAMES
                self.assertFalse(hit, f"{rel}:{name} reads {sorted(hit)}")

    # The review (2026-11-06): the guard named two of the section's public
    # names, so a decision reading the book through a wrapper passed it.

    def test_the_guard_names_every_public_name_of_the_section(self):
        """Every public function and class of the section hands eToro's
        figure on (the helper, its wrappers, the display copies): a
        decision module reading ANY of them is caught, the next wrapper
        included."""
        src = (Path(settings.BASE_DIR) / "portfolio" / "services.py"
               ).read_text(encoding="utf-8")
        head = src[:src.index(SECTION_HEAD)].count("\n") + 1
        public = {n.name for n in ast.parse(src).body
                  if isinstance(n, (ast.FunctionDef, ast.ClassDef))
                  and n.lineno > head and not n.name.startswith("_")}
        self.assertGreaterEqual(public, {
            "venue_pnl", "venue_pnls", "venue_pnls_for_rows",
            "shown_open_rows", "shown_unrealized", "ShownRow",
            "etoro_carried"})
        self.assertFalse(public - HELPER_NAMES,
                         f"the guard misses {sorted(public - HELPER_NAMES)}")

    def test_a_decision_module_reading_a_wrapper_is_caught(self):
        """The reviewer's probe, as source: a gate summing
        shown_open_rows' unrealized_pnl would take eToro's figure for the
        marks."""
        for src in (
                "from portfolio.services import shown_open_rows, "
                "unified_open_positions\n"
                "def open_loss(user):\n"
                "    rows, _v = shown_open_rows(\n"
                "        user, unified_open_positions(user))\n"
                "    return sum(r.unrealized_pnl or 0 for r in rows)\n",
                "from portfolio.services import ShownRow\n",
                "import portfolio.services as s\ns.shown_unrealized([])\n",
                "from portfolio import services\n"
                "services.venue_pnls_for_rows(None, [])\n",
                "from portfolio.services import etoro_carried\n"):
            self.assertTrue(_names(ast.parse(src)) & HELPER_NAMES, src)

    def test_the_scan_covers_the_agents_that_read_positions(self):
        """ai_agents hands the open positions' P&L to the models
        (ai_agents/tasks.py): it is scanned with the decisions."""
        base = Path(settings.BASE_DIR)
        files = {p.relative_to(base).as_posix() for p in self._files()}
        self.assertIn("ai_agents/tasks.py", files)
        self.assertIn("brain/close_advice.py", files)
        self.assertIn("bot_program/morgul.py", files)


# ── 4. the review (2026-11-06): what still printed the marks ─────────────
#
# The review of this change found surfaces beside the rows that still
# printed the mark's figure, or an estimate without saying so: "Should I
# close?", the book's VALUE, the position page's notes, the headband's
# dropdown rows, the investor panel, the PDF and the chart's hover card.

def _advice(case, ids):
    r = case.client.post("/positions/close-advice/",
                         data=json.dumps({"ids": ids}),
                         content_type="application/json", HTTP_HOST=HOST)
    case.assertEqual(r.status_code, 200)
    return r.json()


def _pdf_tables(case):
    """The PDF report's tables (their rows) and its paragraphs (their
    text), as the report hands them to reportlab."""
    from reportlab import platypus
    tables, paras = [], []
    real_table, real_para = platypus.Table, platypus.Paragraph

    def table(data, *a, **kw):
        tables.append(data)
        return real_table(data, *a, **kw)

    def para(text, *a, **kw):
        paras.append(text)
        return real_para(text, *a, **kw)

    with mock.patch("reportlab.platypus.Table", side_effect=table), \
            mock.patch("reportlab.platypus.Paragraph", side_effect=para):
        r = case.client.get("/reports/portfolio/", HTTP_HOST=HOST)
    case.assertEqual(r.status_code, 200)
    return tables, paras


class TheCloseAdviceTests(_Case):
    """"Should I close?" (/positions/, /portfolio/, the Horde, the position
    page): the card and the selection print the figure the row prints.
    Sauron's read — the verdict, the reasons, what the AI is sent — stays
    the brain's, at the price shown, and the card says so."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)
        self.t = _row(self.cfg)
        _held(self.user, [_holding()])

    def test_the_card_and_the_selection_print_etoros_figure(self):
        from brain.close_advice import advise
        brain = advise(self.user, [self.t.id])["positions"][0]
        a = _advice(self, [self.t.id])
        card = a["positions"][0]
        n = card["numbers"]
        self.assertAlmostEqual(n["pnl"], ETORO_NET, places=6)
        self.assertEqual(n["pnl_text"], "-1.15 USD")
        self.assertTrue(n["pnl_said"].startswith("eToro's own figure, read "),
                        n["pnl_said"])
        self.assertEqual(n["r_now_text"], "-0.08R")
        # Sauron's read is the brain's, at the price shown: said under R
        self.assertEqual(brain["numbers"]["pnl_text"], "+12.96 USD")
        self.assertEqual(brain["numbers"]["r_now_text"], "+0.90R")
        self.assertIn("+0.90R", n["r_now_said"])
        self.assertEqual(card["verdict"], brain["verdict"])
        self.assertEqual(card["reasons"], brain["reasons"])
        self.assertEqual(n["mark_text"], brain["numbers"]["mark_text"])
        s = a["summary"]
        self.assertAlmostEqual(s["pnl"], ETORO_NET, places=6)
        self.assertEqual(s["pnl_text"], "-1.15 USD")
        self.assertNotIn("estimate", s["pnl_note"])

    def test_an_estimate_says_so_on_the_card_and_the_selection(self):
        _held(self.user, [_holding()], age_s=3600)
        a = _advice(self, [self.t.id])
        n = a["positions"][0]["numbers"]
        self.assertEqual(n["pnl_text"], "+12.96 USD")
        self.assertTrue(n["pnl_said"].startswith(
            "estimate: Yahoo Finance quote, "), n["pnl_said"])
        self.assertEqual(n["r_now_text"], "+0.90R")
        self.assertEqual(n.get("r_now_said", ""), "")
        s = a["summary"]
        self.assertEqual(s["pnl_text"], "+12.96 USD")
        self.assertIn("estimate", s["pnl_note"])
        self.assertIn(SYMBOL, s["pnl_note"])

    def test_a_row_etoro_does_not_carry_is_the_brains_own(self):
        from brain.close_advice import advise
        paper = _row(_config(self.user, name="paper", mode="paper"),
                     paper=True, pid=None, broker=None, env=None)
        brain = advise(self.user, [paper.id])
        a = _advice(self, [paper.id])
        self.assertEqual(a["positions"][0]["numbers"]["pnl_text"],
                         brain["positions"][0]["numbers"]["pnl_text"])
        self.assertEqual(a["positions"][0]["numbers"]["r_now_text"],
                         brain["positions"][0]["numbers"]["r_now_text"])
        self.assertEqual(a["positions"][0]["numbers"].get("pnl_said", ""),
                         "")
        self.assertEqual(a["summary"]["pnl_text"],
                         brain["summary"]["pnl_text"])

    def test_the_dialog_prints_the_words(self):
        js = (Path(settings.BASE_DIR) / "static" / "js"
              / "sv-close-advice.js").read_text(encoding="utf-8")
        card = js.split("function card(", 1)[1]
        self.assertIn("n.pnl_said", card)
        self.assertIn("n.r_now_said", card)


class TheBookValueShownTests(_Case):
    """The book's VALUE on the pages: cash plus everything open, with the
    open P&L inside it at eToro's own figure for an eToro position its
    holdings list — the marks' 1,000 + 2,172.96 = 3,172.96 prints as
    1,000 + 2,160.00 - 1.15 = 3,158.85. live_book_value (the gates'
    denominator) keeps the marks."""

    SHOWN, MARKED = 3158.85, 3172.96

    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)
        from portfolio.services import get_or_create_default_portfolio
        self.pf = get_or_create_default_portfolio(user=self.user)
        self.pf.cash_available = Decimal("1000")
        self.pf.save()
        self.t = _row(self.cfg)
        _held(self.user, [_holding()])

    def _book(self):
        from portfolio.services import live_book_value
        return live_book_value(self.user, self.pf)

    def test_the_shown_value_moves_and_the_book_does_not(self):
        from portfolio.services import shown_book
        book = self._book()
        self.assertAlmostEqual(book.value, self.MARKED, places=2)
        shown = shown_book(self.user, book)
        self.assertAlmostEqual(shown.value, self.SHOWN, places=2)
        self.assertAlmostEqual(shown.free,
                               round(self.SHOWN - book.allocated, 2), places=2)
        self.assertEqual(shown.allocated, book.allocated)
        self.assertEqual(shown.marked, book.marked)
        self.assertEqual(shown.unrealized, book.unrealized)
        self.assertAlmostEqual(book.value, self.MARKED, places=2)
        self.assertAlmostEqual(self._book().value, self.MARKED, places=2)

    def test_a_stale_read_keeps_the_marks_value(self):
        from portfolio.services import shown_book
        _held(self.user, [_holding()], age_s=3600)
        book = self._book()
        self.assertAlmostEqual(shown_book(self.user, book).value,
                               self.MARKED, places=2)

    def test_a_short_moves_with_its_own_figure(self):
        """The P&L inside the value is eToro's in place of the mark's,
        whichever the side: a short eToro marks at -13.39 (its ask) where
        the mark says -12.96 takes 0.43 off."""
        from portfolio.services import shown_book
        self.t.delete()
        _row(self.cfg, side="SELL")
        _held(self.user, [_holding(net=-13.39, side="SELL")])
        book = self._book()
        self.assertAlmostEqual(shown_book(self.user, book).value,
                               round(book.value - 0.43, 2), places=2)

    def test_the_headband(self):
        from tests.test_headband_truth import _ctx
        self.assertEqual(_ctx(self.user)["panel_portfolio_value"], "3,159")

    def test_the_portfolio_strip(self):
        free = round(self.SHOWN - self._book().allocated, 2)
        for url in ("/portfolio/", "/portfolio/live/"):
            body = self.client.get(url, HTTP_HOST=HOST).content.decode()
            self.assertEqual(_span(body, "pf.value"), "3,158.85", url)
            self.assertEqual(_span(body, "pf.free"), f"{free:,.2f}", url)

    def test_the_ops_center_heads_and_tab(self):
        from dashboard.views_command import _hero_metrics, _tab_bar_metrics
        sym = self._book().currency_symbol
        # Updated deliberately 2026-11-07 (Operations Center OC0): the
        # platform book is in mixed currencies, never converted, so it
        # wears no currency sign, and the head prints its two decimals like
        # the hero and the tab (spec §5.2, OC0). The meaning is kept: the
        # head, the hero and the tab show the same shown book, never the
        # marks' 3,172.96.
        self.assertEqual(_tab_bar_metrics(self.user)["portfolio"]["primary"],
                         "3,158.85")
        self.assertEqual(_hero_metrics(self.user)["value"], "3,158.85")
        body = self.client.get("/command/tab/portfolio/",
                               HTTP_HOST=HOST).content.decode()
        self.assertIn("3,158.85", body)
        self.assertNotIn(f"{sym}3,158.85", body)
        self.assertNotIn("3,172.96", body)

    def test_the_pdf(self):
        tables, _paras = _pdf_tables(self)
        summary = {row[0]: row[1] for row in tables[0][1:]
                   if isinstance(row[1], str)}
        self.assertEqual(summary["Portfolio Value"],
                         f"{self.pf.currency} 3,158.85")

    def test_the_digest(self):
        from alerts.digest_book import book_sections
        cur = (self.pf.currency or "").upper()
        lines = book_sections(self.user)["simulated"]["lines"]
        self.assertIn(f"Book value: 3,158.85 {cur} · cash 1,000.00 {cur}",
                      lines)


class ThePositionPageNotesTests(_Case):
    """The notes under the position page's figure speak of the figure it
    prints: eToro's own does not go stale with the mark, and it is in
    dollars whatever the row's own marks are in."""

    def setUp(self):
        super().setUp()
        self.t = _row(self.cfg)
        _held(self.user, [_holding()])
        # THE MARKET IS PINNED OPEN (2026-11-07): these notes are about a
        # stale price beside eToro's own figure, not about the market's
        # hours. Unpinned, a run on a weekend found the forex market shut
        # and read the shut-market note in their place, so the suite went
        # red every Saturday and Sunday. tests/test_position_page.py covers
        # the shut-market note itself.
        pin = mock.patch("core.exchange_status.market_status_for",
                         return_value={"is_open": True})
        pin.start()
        self.addCleanup(pin.stop)

    def _notes(self, trade=None):
        from dashboard.position_summary import build_summary
        s = build_summary(trade or self.t)
        return s, " ".join(n["text"] for n in s["notes"])

    def test_a_stale_price_beside_etoros_own_figure(self):
        _quote(age_s=1800)
        s, notes = self._notes()
        self.assertEqual(s["big_value"], "-1.15 USD")
        self.assertIn("The price is stale", notes)
        self.assertNotIn("profit or loss may be out of date", notes)

    def test_a_stale_price_under_an_estimate_still_says_so(self):
        _quote(age_s=1800)
        _held(self.user, [_holding()], age_s=3600)
        s, notes = self._notes()
        self.assertEqual(s["big_value"], "+12.96 USD")
        self.assertIn("so the profit or loss may be out of date", notes)

    def test_an_unconverted_row_says_only_its_size_is_in_its_quote(self):
        meta = dict(self.t.metadata)
        meta.pop("value_per_unit")
        self.t.metadata = meta
        self.t.save()
        s, notes = self._notes()
        self.assertEqual(s["big_value"], "-1.15 USD")
        self.assertIn("its size is shown in CAD, not USD", notes)
        self.assertNotIn("its profit or loss and its size", notes)

    def test_a_row_waiting_for_the_venue_price_with_etoros_figure(self):
        """A CFD whose platform quote is the future (XPTUSD against PL=F):
        no price until the venue's arrives, but eToro's figure is there."""
        _quote(last="950.00", symbol="XPTUSD")
        t = _row(self.cfg, symbol="XPTUSD", pid="4001")
        _held(self.user, [_holding(),
                          _holding(pid="4001", symbol="XPTUSD", net=-2.65)])
        s, notes = self._notes(t)
        self.assertEqual(s["big_value"], "-2.65 USD")
        self.assertNotIn("nothing is shown", notes)
        self.assertNotIn("cannot be shown", notes)


class TheWordsOnEverySurfaceTests(_Case):
    """Where an open eToro row's figure is an estimate, every surface that
    prints it says so; where it is eToro's own, the PDF says whose."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)
        self.t = _row(self.cfg)
        _held(self.user, [_holding()], age_s=3600)          # an estimate

    def _get(self, url):
        r = self.client.get(url, HTTP_HOST=HOST)
        self.assertEqual(r.status_code, 200, url)
        return r.content.decode()

    def test_the_headband_dropdown_rows(self):
        from tests.test_headband_truth import _ctx
        row = _ctx(self.user)["panel_open_rows"][0]
        self.assertTrue(row["pnl_words"].startswith(
            "estimate: Yahoo Finance quote, "), row)
        body = self._get("/positions/")
        m = re.search(r'<span class="[^"]*\bipr-est\b[^"]*" title="([^"]*)"'
                      r'>([^<]*)<', body)
        self.assertIsNotNone(m, "the dropdown row says it is an estimate")
        self.assertEqual(m.group(2).strip(), "estimate")
        self.assertIn("estimate: Yahoo Finance quote, ",
                      html.unescape(m.group(1)))

    def test_the_headband_rows_say_nothing_on_etoros_own(self):
        from tests.test_headband_truth import _ctx
        _held(self.user, [_holding()])
        row = _ctx(self.user)["panel_open_rows"][0]
        self.assertEqual(row["pnl_words"], "")
        self.assertNotIn('ipr-est', self._get("/positions/"))

    def test_the_investor_panel(self):
        from portfolio.investor_models import InvestorAccess
        investor = get_user_model().objects.create_user("lp_pnl",
                                                        password="x")
        InvestorAccess.objects.create(
            investor=investor, owner=self.user, label="Fund",
            show_positions=True, percents_only=False)
        self.client.force_login(investor)
        body = self._get("/investor/")
        self.assertIn("estimate: Yahoo Finance quote, ", body)

    def test_the_pdf_says_whose_figure(self):
        tables, paras = _pdf_tables(self)
        pos = next(t for t in tables if t and t[0][0] == "Symbol")
        head, row = pos[0], pos[1]
        self.assertEqual(row[0], SYMBOL)
        self.assertEqual(row[head.index("Basis")], "estimate")
        note = " ".join(str(p) for p in paras)
        self.assertIn(f"{SYMBOL}: estimate: Yahoo Finance quote, ", note)
        # eToro's own figure is said too: the Current beside it is the
        # mark, which eToro's figure does not read
        _held(self.user, [_holding()])
        tables, paras = _pdf_tables(self)
        pos = next(t for t in tables if t and t[0][0] == "Symbol")
        self.assertEqual(pos[1][pos[0].index("Basis")], "eToro")
        self.assertEqual(pos[1][pos[0].index("P&L %")], "-0.05%")
        self.assertIn("eToro's own", " ".join(str(p) for p in paras))

    def test_the_chart_hover_card(self):
        from dashboard.views import _chart_positions
        rows = _chart_positions(self.user, _instrument())
        bot = next(r for r in rows if r.get("id") == f"bot-{self.t.id}")
        self.assertTrue(bot["pnl_words"].startswith("estimate: "), bot)
        src = (Path(settings.BASE_DIR) / "templates" / "_partials"
               / "chart_widget.html").read_text(encoding="utf-8")
        card = src.split("function positionCard(", 1)[1].split(
            "\n    function ", 1)[0]
        self.assertIn("p.pnl_words", card)


# ── 5. the band's words beside eToro's figure (2026-11-06) ───────────────
#
# The review's probe J: an eToro row the book cannot price (its platform
# quote is a stand-in and the venue's own price is not in yet) whose
# holdings list it with eToro's own figure. The band printed that figure as
# its open P&L and, beside it, the book's sentence "value, exposure and P&L
# cannot be measured" — and "across 0 of 1 positions" under it.

def _band(body):
    """The headband's PORTFOLIO, POSITIONS and OPEN P&L cells as the page
    renders them: from the panel's scroll strip to the end of OPEN P&L."""
    start = body.index('id="ipScroll"')
    detail = body.index('data-sv-live="hb-pnl-detail"', start)
    return body[start:body.index("</a>", detail)]


def _sub(body):
    """The line under the band's OPEN P&L figure."""
    m = re.search(r'data-sv-live="hb-pnl-sub"[^>]*>(.*?)</span>', body, re.S)
    return None if m is None else _text(m.group(1))


class TheBandsWordsTests(_Case):
    """The words beside the band's open P&L say what that figure holds: a
    row the book could not price is out of the value and the exposure, and
    in the open P&L at eToro's own figure."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)
        # XPTUSD's platform quote is the future (PL=F): the row awaits the
        # venue's own price, so the book cannot price it.
        _quote(last="950.00", symbol="XPTUSD")
        self.t = _row(self.cfg, symbol="XPTUSD", pid="4001")
        self.held = _holding(pid="4001", symbol="XPTUSD", net=-2.65)
        _held(self.user, [self.held])

    def _body(self):
        r = self.client.get("/positions/", HTTP_HOST=HOST)
        self.assertEqual(r.status_code, 200)
        return r.content.decode()

    def test_the_band_never_says_its_pnl_cannot_be_measured(self):
        from tests.test_headband_truth import _ctx
        ctx = _ctx(self.user)
        self.assertEqual(ctx["panel_positions_priced"], 0)
        self.assertEqual(ctx["panel_open_pnl_display"], "-2.65")
        words = ctx["panel_book_coverage"]
        self.assertNotIn("P&L cannot be measured", words)
        self.assertIn("value and exposure cannot be measured", words)
        self.assertIn("1 at eToro's own figure", words)
        body = self._body()
        band = html.unescape(_band(body))
        self.assertIn("-2.65", band)
        self.assertNotIn("P&L cannot be measured", band)
        # the line under the figure counts the position the figure holds
        self.assertEqual(_sub(body), "real + paper across 1 position")

    def test_beside_a_priced_row_the_other_is_in_the_pnl(self):
        """A priced row beside it: the sentence no longer says the other is
        "not in these figures" while the open P&L holds it."""
        from tests.test_headband_truth import _ctx
        _row(self.cfg)
        _held(self.user, [_holding(), self.held])
        ctx = _ctx(self.user)
        self.assertEqual(ctx["panel_positions_priced"], 1)
        self.assertAlmostEqual(ctx["panel_open_pnl"], ETORO_NET - 2.65,
                               places=6)
        words = ctx["panel_book_coverage"]
        self.assertIn("1 of 2", words)
        self.assertNotIn("not in these figures", words)
        self.assertIn("not in the value or the exposure", words)
        self.assertIn("1 at eToro's own figure", words)
        self.assertEqual(_sub(self._body()),
                         "real + paper across 2 positions")

    def test_with_no_figure_from_etoro_the_books_words_stand(self):
        """eToro's holdings do not list it: no figure is printed, and the
        book's sentence stands to the letter — that P&L is unmeasured."""
        from tests.test_headband_truth import _ctx
        _held(self.user, [])
        ctx = _ctx(self.user)
        self.assertIsNone(ctx["panel_open_pnl_display"])
        self.assertIn("value, exposure and P&L cannot be measured",
                      ctx["panel_book_coverage"])
        self.assertEqual(_sub(self._body()),
                         "real + paper across 0 of 1 positions")
