"""eToro's ALL-WEEK WORDS ARE DISPLAY ONLY (2026-11-19): money direction
none.

The screens now say "open · eToro 24/7" at the weekend for eToro's
all-week instruments (market_data/all_week_display.py). The operator
decided on 2026-11-19 that the bots keep no new entry at the weekend, for
now, and nothing that moves money was to change. With every clock and
every new word switched ON, these tests pin that:

  * a Saturday XAUUSD, XAGUSD, NGUSD or OIL (eToro id 17) bot entry is
    still refused on the entry clock (asset_engine/base.py
    _entry_timing_gate, entry_timing.SHUT), and recorded as MARKET_SHUT;
  * a paper XAUUSD row still waits for CME's open: the manage tick marks,
    moves and books nothing (base.py's paper wait), and the paper venue
    still refuses a fill;
  * the care's weekend window, mark_sanity's market read, the Orcs'
    metronome (W11's next_shut), the bar writer's rule and the booking
    rule (venue_mark.market_shut) read the very clocks they read before;
  * the guards' clocks answer as before for XAUUSD, XAGUSD, NGUSD,
    SPX500, NSDQ100, EURUSD, GBPUSD, HGUSD and BTCUSD on Saturday 15:00
    UTC (the build map's probe);
  * no money module imports the new display reader, except the display
    functions named below, each of which returns words only.

SPX500 and NSDQ100 are not refused by the bots' clock at the weekend
today (an index is no SHUT class): pinned here as it is, and said to the
operator; no screen says "bots: no weekend entries" for them
(tests/test_all_week_display.py).

Fakes only (the feed harness's fake eToro), no network; every price is
invented. Run with:  python manage.py test tests.test_all_week_money_pins
"""
import ast
from datetime import datetime, timedelta
from datetime import timezone as dt_tz
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from django.conf import settings
from django.test import SimpleTestCase, TestCase

from tests.feed import harness as H
from tests.feed.test_feed_pins import _money_files, _rel, _tree

UTC = dt_tz.utc
BASE = Path(settings.BASE_DIR)
SAT_1500 = datetime(2026, 11, 21, 15, 0, tzinfo=UTC)
FRI_2100 = datetime(2026, 11, 20, 21, 0, tzinfo=UTC)
SUN_2300 = datetime(2026, 11, 22, 23, 0, tzinfo=UTC)

ROWS = {"XAUUSD": ("commodity", "COMEX"), "XAGUSD": ("commodity", "COMEX"),
        "NGUSD": ("commodity", "NYMEX"), "SPX500": ("index", "CME"),
        "NSDQ100": ("index", "CME"), "EURUSD": ("forex", "FOREX"),
        "GBPUSD": ("forex", "FOREX"), "HGUSD": ("commodity", "COMEX"),
        "BTCUSD": ("crypto", "CRYPTO")}


def oil():
    from bot_program.engine.etoro_client import PINNED_SYMBOL
    return PINNED_SYMBOL[17]


def row(symbol):
    cls, exch = ROWS.get(symbol, ("commodity", "NYMEX"))
    return cls, exch


def all_on(test):
    """Every clock and every new word ON, for one test. Before the words
    existed (the branch's base) there is nothing to switch on, and these
    pins read the very same answers: they hold on both sides."""
    targets = ["signals.market_hold.GATE", "bot_program.entry_timing.GATE",
               "bot_program.engine.paper_trader.MARKET_HOURS_GATE"]
    try:
        import market_data.all_week_display  # noqa: F401
        targets.append("market_data.all_week_display.GATE")
    except ImportError:
        pass
    for target in targets:
        p = mock.patch(target, True)
        p.start()
        test.addCleanup(p.stop)


def instrument(symbol):
    from instruments.models import Instrument
    cls, exch = row(symbol)
    inst, _ = Instrument.objects.update_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": cls,
                                 "exchange": exch, "is_active": True})
    return inst


class TheBotsStillRefuseAWeekendEntryTests(TestCase):
    """base.py's entry clock (the proposal's first gate, 5414-5434)."""

    def setUp(self):
        all_on(self)
        from django.contrib.auth.models import User
        self.user = User.objects.create_user("pins_owner")

    def gate(self, symbol):
        """The gate a live commodity bot asks for `symbol`: it reads the
        INSTRUMENT row's own class and venue (entry_timing.instrument_key),
        an index's included."""
        from bot_program.asset_engine.base import make_bot
        from bot_program.models import AssetBotConfig
        instrument(symbol)
        cfg = AssetBotConfig.objects.create(
            user=self.user, asset_class="commodity", name=f"pins-{symbol}",
            enabled=True, mode="live", symbols=[symbol],
            capital=Decimal("10000"))
        return make_bot(cfg)._entry_timing_gate(symbol, now=SAT_1500)

    def test_a_saturday_entry_on_the_four_commodities_is_refused(self):
        from bot_program import entry_timing
        from bot_program.asset_engine import skips
        for sym in ("XAUUSD", "XAGUSD", "NGUSD", oil()):
            with self.subTest(sym if sym != oil() else "eToro id 17"):
                v = self.gate(sym)
                self.assertFalse(v["ok"])
                self.assertEqual(v["code"], entry_timing.SHUT)
                self.assertEqual(entry_timing.skip_code(v), skips.MARKET_SHUT)
                self.assertIn("the commodity market is shut until Sunday "
                              "23:00 UTC", v["why"])

    def test_the_indices_are_as_before_not_a_shut_class(self):
        """Pinned as it stands (the build map's W1, said to the
        operator): the display change neither adds nor removes a refusal."""
        for sym in ("SPX500", "NSDQ100"):
            with self.subTest(sym):
                self.assertTrue(self.gate(sym)["ok"])


class ThePaperRowStillWaitsTests(TestCase):
    """base.py's paper wait (1468-1499): a paper row on a shut market is
    marked, moved and booked by nothing until it reopens."""

    def setUp(self):
        all_on(self)
        self.clock = H.FakeClock(start=SAT_1500)
        self.clock.__enter__()
        self.addCleanup(self.clock.__exit__, None, None, None)
        self.owner = H.user("pins_paper")

    def test_a_paper_xauusd_row_with_its_stop_crossed_stays_open(self):
        from bot_program.asset_engine.base import make_bot
        from bot_program.models import AssetBotConfig
        instrument("XAUUSD")
        cfg = AssetBotConfig.objects.create(
            user=self.owner, asset_class="commodity", name="pins-paper",
            enabled=True, mode="paper", symbols=[],
            capital=Decimal("10000"))
        t = H.real_row(cfg, "XAUUSD", entry=Decimal("2000.00"),
                       stop=Decimal("1980.00"), target=Decimal("2060.00"),
                       position_id="p-XAUUSD")
        t.paper = True
        t.metadata = {}
        t.save(update_fields=["paper", "metadata"])
        e = H.EtoroTrader({"XAUUSD": H.tick(Decimal("1950.00"))})
        with H.route_to(e):
            make_bot(cfg).manage_positions()
        t.refresh_from_db()
        self.assertEqual(t.status, "OPEN", "the paper row waits for CME")
        self.assertEqual(e.writes_sent, [])

    def test_the_paper_venue_still_refuses_a_saturday_fill(self):
        from bot_program.engine.paper_trader import paper_market_shut
        instrument("XAUUSD")
        said = paper_market_shut("XAUUSD", "commodity", now=SAT_1500)
        self.assertTrue(said)
        self.assertIn("commodity market is shut", said)
        self.assertIn("Sunday 23:00 UTC", said)


class TheGuardsReadTheirOwnClocksTests(SimpleTestCase):
    """The build map's probe, Saturday 15:00 UTC, every switch ON."""

    def setUp(self):
        all_on(self)

    def test_the_clocks_answer_as_before(self):
        from bot_program import entry_timing
        from core.exchange_status import market_clock, market_status_for
        from signals.market_hold import market_state
        want = {
            "XAUUSD": ("CME", False, "CME Futures", "shut", "SHUT"),
            "XAGUSD": ("CME", False, "CME Futures", "shut", "SHUT"),
            "NGUSD": ("CME", False, "CME Futures", "shut", "SHUT"),
            oil(): ("CME", False, "CME Futures", "shut", "SHUT"),
            "SPX500": ("NYSE", False, "New York Stock Exchange", "shut", ""),
            "NSDQ100": ("NYSE", False, "New York Stock Exchange", "shut",
                        ""),
            "EURUSD": ("FOREX", False, "Forex Market", "shut", "SHUT"),
            "GBPUSD": ("FOREX", False, "Forex Market", "shut", "SHUT"),
            "HGUSD": ("CME", False, "CME Futures", "shut", "SHUT"),
            "BTCUSD": ("CRYPTO", True, "Crypto", "always", ""),
        }
        for sym, (session, is_open, badge, state, code) in want.items():
            cls, exch = row(sym)
            with self.subTest(sym if sym != oil() else "eToro id 17"):
                clock = market_clock(cls, exch, symbol=sym, now_utc=SAT_1500)
                self.assertEqual((clock["session"], clock["is_open"]),
                                 (session, is_open))
                ms = market_status_for(cls, exch, now_utc=SAT_1500,
                                       symbol=sym)
                self.assertEqual((ms["name"], ms["is_open"]),
                                 (badge, is_open))
                st = market_state(SimpleNamespace(
                    symbol=sym, asset_class=cls, exchange=exch),
                    now=SAT_1500)
                self.assertEqual(st["state"], state)
                v = entry_timing.clock_verdict(sym, cls, exchange=exch,
                                               now=SAT_1500)
                self.assertEqual((v or {}).get("code") or "", code)

    def test_the_strip_and_its_count_are_the_exchanges_own(self):
        from core.exchange_status import get_exchange_status
        st = get_exchange_status(SAT_1500)
        cme = [r for r in st["exchanges"] if r["code"] == "CME"][0]
        self.assertFalse(cme["is_open"])
        self.assertEqual(st["open_count"], sum(
            1 for r in st["exchanges"] if r["is_open"]))

    def test_the_booking_rule_still_reads_a_saturday_gold_row_shut(self):
        from bot_program.venue_mark import market_shut
        trade = SimpleNamespace(symbol="XAUUSD", asset_class="commodity")
        with mock.patch("bot_program.engine.paper_trader._instrument_key",
                        return_value=("commodity", "COMEX")):
            shut = market_shut(trade, now=SAT_1500)
        self.assertIsNotNone(shut)
        self.assertEqual(shut["reopens"], SUN_2300)

    def test_mark_sanity_and_the_paper_venue_read_the_same_shut(self):
        from bot_program.engine.paper_trader import paper_market_shut
        with mock.patch("bot_program.engine.paper_trader._instrument_key",
                        return_value=("commodity", "COMEX")):
            self.assertTrue(paper_market_shut("XAUUSD", "commodity",
                                              now=SAT_1500))

    def test_the_orcs_metronome_rests_on_saurons_clock(self):
        from bot_program.orcs.sessions import next_shut
        s = next_shut("commodity", "XAUUSD", SAT_1500, exchange="COMEX")
        self.assertTrue(s["now_shut"])
        self.assertEqual(s["reopens"], SUN_2300)

    def test_the_care_window_and_the_bar_rule_are_unchanged(self):
        from bot_program.position_care import is_weekend_window
        from market_data.shut_bars import (holds_no_open_time,
                                           shut_for_a_day_now)
        self.assertTrue(is_weekend_window(FRI_2100, "commodity"))
        gold = SimpleNamespace(symbol="XAUUSD", asset_class="commodity",
                               exchange="COMEX")
        copper = SimpleNamespace(symbol="HGUSD", asset_class="commodity",
                                 exchange="COMEX")
        self.assertFalse(holds_no_open_time(gold, "4h", SAT_1500))
        self.assertTrue(holds_no_open_time(copper, "4h", SAT_1500))
        self.assertIsNone(shut_for_a_day_now(gold, SAT_1500))
        self.assertIsNotNone(shut_for_a_day_now(copper, SAT_1500))


# ── the display reader stays on the screens ──────────────────────────────

MODULE = "market_data.all_week_display"
#: The clock helper's own names: read by the display reader only.
HELPER_NAMES = {"all_week_state", "ALL_WEEK_BREAKS_UTC"}
#: The display functions inside the money trees allowed to read the
#: display reader: each returns words for a screen, never a decision.
DISPLAY_FUNCTIONS = {
    "brain/close_advice.py": {"_market_reason"},
    "bot_program/orcs/notes.py": {"slot"},
    "bot_program/telegram_eye.py": {"_skip_line"},
}


def _hits(node):
    hit = set()
    for n in ast.walk(node):
        if isinstance(n, ast.ImportFrom) and n.module:
            if n.module == MODULE or n.module.startswith(MODULE + "."):
                hit.add(n.module)
            elif n.module == "market_data":
                hit |= {a.name for a in n.names
                        if a.name == "all_week_display"}
        elif isinstance(n, ast.Import):
            hit |= {a.name for a in n.names if a.name.startswith(MODULE)}
        elif isinstance(n, ast.Constant) and isinstance(n.value, str) and \
                n.value in (MODULE, "all_week_display"):
            hit.add(n.value)
        elif isinstance(n, ast.Attribute) and n.attr == "all_week_display":
            hit.add(n.attr)
    return hit


def _helper_hits(node):
    hit = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Name) and n.id in HELPER_NAMES:
            hit.add(n.id)
        elif isinstance(n, ast.Attribute) and n.attr in HELPER_NAMES:
            hit.add(n.attr)
        elif isinstance(n, ast.alias) and n.name in HELPER_NAMES:
            hit.add(n.name)
    return hit


def _outside_display_functions(tree, allowed):
    """The top-level nodes of `tree` that are not one of `allowed`'s
    definitions (a class's methods by their own name too)."""
    out = []
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and \
                n.name in allowed:
            continue
        out.append(n)
    return out


class NoMoneyPathReadsTheDisplayReaderTests(SimpleTestCase):

    def test_no_money_module_reaches_it_outside_its_display_functions(self):
        seen = 0
        for path, funcs in _money_files():
            rel = _rel(path)
            tree = _tree(path)
            allowed = DISPLAY_FUNCTIONS.get(rel, set())
            nodes = (_outside_display_functions(tree, allowed)
                     if funcs is None else
                     [n for n in tree.body
                      if getattr(n, "name", None) in funcs])
            for node in nodes:
                hit = _hits(node)
                self.assertFalse(hit, f"{rel} names {sorted(hit)} outside "
                                      f"its display functions")
                if rel != "market_data/shut_bars.py":
                    helper = _helper_hits(node)
                    self.assertFalse(helper, f"{rel} names {sorted(helper)}")
            seen += 1
        self.assertGreater(seen, 100, "the scan found the money modules")

    def test_each_allowed_function_exists_and_reads_it(self):
        for rel, names in DISPLAY_FUNCTIONS.items():
            tree = _tree(BASE / rel)
            found = {n.name: n for n in tree.body
                     if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
            for name in names:
                with self.subTest(f"{rel}:{name}"):
                    self.assertIn(name, found)
                    self.assertTrue(_hits(found[name]),
                                    "an allowed function that no longer "
                                    "reads it leaves this list")

    def test_the_guards_never_name_it(self):
        for rel in ("bot_program/asset_engine/base.py",
                    "bot_program/engine/paper_trader.py",
                    "bot_program/entry_timing.py", "bot_program/morgul.py",
                    "bot_program/venue_mark.py",
                    "bot_program/engine/etoro_rates.py",
                    "bot_program/mark_sanity.py",
                    "bot_program/position_care.py",
                    "bot_program/orcs/wake.py",
                    "bot_program/orcs/sessions.py",
                    "bot_program/shut_guard.py",
                    "bot_program/pending_closes.py",
                    "bot_program/manual_trade.py",
                    "bot_program/manual_close.py",
                    "bot_program/engine/kill_switch.py",
                    "market_data/bot_bars.py", "core/exchange_status.py",
                    "signals/market_hold.py"):
            with self.subTest(rel):
                src = (BASE / rel).read_text(encoding="utf-8")
                self.assertNotIn("all_week_display", src)
                self.assertNotIn("all_week_state", src)

    def test_the_scan_catches_every_spelling(self):
        for src in ("from market_data.all_week_display import week\n",
                    "from market_data import all_week_display\n",
                    "import market_data.all_week_display\n",
                    "import importlib\n"
                    "importlib.import_module('market_data.all_week_display')\n",
                    "x = market_data.all_week_display\n"):
            with self.subTest(src=src):
                self.assertTrue(_hits(ast.parse(src)), src)
        self.assertTrue(_helper_hits(ast.parse(
            "from market_data.shut_bars import all_week_state\n")))

    def test_the_reader_writes_nothing_and_asks_no_one(self):
        tree = ast.parse((BASE / "market_data" / "all_week_display.py")
                         .read_text(encoding="utf-8"))
        from tests.feed.test_feed_pins import _imports
        imports = _imports(tree)
        for bad in ("requests", "httpx", "urllib.request", "socket",
                    "bot_program.engine", "bot_program.manual_trade",
                    "bot_program.manual_close", "market_data.quotes",
                    "yfinance", "anthropic", "django.db"):
            self.assertFalse(
                any(i == bad or i.startswith(bad + ".") for i in imports),
                bad)
        writes = {"save", "create", "update_or_create", "get_or_create",
                  "bulk_create", "bulk_update", "delete", "set_many",
                  "incr"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and \
                    isinstance(node.func, ast.Attribute):
                self.assertNotIn(node.func.attr, writes)
            if isinstance(node, ast.Attribute):
                self.assertNotIn(node.attr, ("objects", "cache"),
                                 "no table and no cache: clock only")

    def test_a_week_of_words_moves_no_clock(self):
        """With every word ON, every guard clock reads as with every word
        OFF, at every half hour of a week."""
        from bot_program import entry_timing
        from core.exchange_status import market_clock
        from signals.market_hold import market_state
        all_on(self)
        t = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
        syms = ("XAUUSD", "NGUSD", "SPX500", "EURUSD", "HGUSD")

        def read():
            out = []
            for i in range(0, 7 * 48):
                now = t + timedelta(minutes=30 * i)
                for sym in syms:
                    cls, exch = row(sym)
                    inst = SimpleNamespace(symbol=sym, asset_class=cls,
                                           exchange=exch)
                    out.append((
                        market_clock(cls, exch, symbol=sym,
                                     now_utc=now)["is_open"],
                        market_state(inst, now=now)["state"],
                        (entry_timing.clock_verdict(
                            sym, cls, exchange=exch, now=now) or {}).get(
                                "code")))
            return out
        on = read()
        with mock.patch("market_data.all_week_display.GATE", False):
            off = read()
        self.assertEqual(on, off)
