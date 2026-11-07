"""THE FEED'S PINS (the eToro feed spec, F1, §6.2 Pins, I2, I7, I15;
2026-11-07). Source scans, in the style of tests/test_venue_pnl.py's
decision-module scan: they read the code, never run it.

  1. Money modules may not name display_quote or reference_quote (I7):
     money has one door, money_price.
  2. A ratchet of today's LiveQuote reads in money modules, by module and
     function: a new read fails, and a read that goes away asks for the
     ratchet to be lowered. Each later phase moves a read behind the door
     and lowers its line; none may add one.
  3. Feed modules may not import an order path, call /search or name
     instrument_id() (I15): the feed observes and never trades.
  4. Only the feed's modules name a vq:* key (I2).
  5. The feed never writes LiveQuote (I2), never writes the engine's rates
     cache before F9, and its pure core opens no network.
  6. F1 adds no switch: no money door is open, and none of the switches
     the later phases bring exists yet.

Run with:  python manage.py test tests.feed.test_feed_pins
"""
import ast
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

BASE = Path(settings.BASE_DIR)

#: Every module that decides money (tests/test_venue_pnl.py's decision
#: scan, plus the book's own readers in portfolio/services.py).
MONEY_TREES = ("bot_program", "brain", "ai_agents")
MONEY_FILES = ("portfolio/risk_gate.py", "portfolio/tasks.py",
               "portfolio/position_sizing.py", "portfolio/services.py",
               "market_data/bot_bars.py")

#: The feed's modules (§4.3). F1's three exist; the later ones are
#: scanned from the day they do.
FEED_CORE = ("market_data/venue_quotes.py", "market_data/venue_store.py",
             "market_data/venue_session.py")
FEED_LATER = ("market_data/feed_wants.py",
              "market_data/management/commands/stream_etoro.py",
              "bot_program/engine/etoro_stream.py",
              "portfolio/pnl_venue.py", "bot_program/etoro_pnl.py",
              "bot_program/feed_shadow.py")

#: TODAY'S LiveQuote READS IN MONEY MODULES (2026-11-07, main at F1), by
#: module and enclosing definition: the count of `LiveQuote` and
#: `.live_quote` names there. A new read fails; a read that goes away
#: lowers its line here, in the same change.
LIVEQUOTE_RATCHET = {
    "ai_agents/calibration.py": {"mark_for_symbol": 1},
    "ai_agents/tasks.py": {"generate_daily_commentary": 2,
                           "optimize_strategies": 1,
                           "run_anomaly_detection": 1},
    "bot_program/asset_engine/forex_bot.py": {"quote_ccy_usd_rate._live": 1},
    "bot_program/engine/kill_switch.py": {"_market_exit_price": 1},
    "bot_program/engine/paper_trader.py": {"PaperTrader.market_order": 1,
                                           "PaperTrader.order_book": 1,
                                           "PaperTrader.ticker": 1},
    "bot_program/etoro_quotes.py": {"_holder": 1},
    "bot_program/management/commands/open_trades.py": {"_open_mark": 1},
    "bot_program/mark_sanity.py": {"second_opinion": 1},
    "bot_program/market_stress.py": {"_daily_closes": 1},
    "bot_program/morgul.py": {"check_heartbeat": 1},
    "bot_program/nl_trader.py": {"NLTradeParser.execute": 4},
    "bot_program/orcs/dossier.py": {"_mark": 1},
    "bot_program/orcs/drum_bus.py": {"_last": 1},
    "bot_program/orcs/grading.py": {"_usd_per.quote": 1},
    "bot_program/orcs/situation.py": {"_spread": 1},
    "bot_program/orcs/sources.py": {"quote": 1, "quotes": 1},
    "bot_program/reconcile_asset.py": {"_close_as_orphan": 1},
    "bot_program/tasks.py": {"refresh_option_chains_for_user": 1},
    "brain/position_review.py": {"_venue_mark_for": 1},
    "portfolio/services.py": {"_normalize_trades": 1, "_venue_answers": 1},
    "portfolio/tasks.py": {"_mark_for": 1},
}
LIVEQUOTE_NAMES = {"LiveQuote", "live_quote"}

#: The order paths (I15): every package and module that can send, change
#: or cancel an order, close a position or move a stop.
ORDER_PATH_PACKAGES = ("bot_program.engine", "bot_program.asset_engine")
ORDER_PATH_MODULES = ("bot_program.manual_trade", "bot_program.manual_close",
                      "bot_program.pending_closes",
                      "bot_program.reconcile_asset",
                      "bot_program.position_care", "bot_program.venue_exit",
                      "bot_program.adjust_levels", "bot_program.nl_trader",
                      "bot_program.orchestrator", "bot_program.tasks",
                      "bot_program.short_proofs", "bot_program.withdrawals")
#: The names that send, change or cancel at a venue, or look an id up.
ORDER_NAMES = {"instrument_id", "market_order", "close_position",
               "open_position", "place_order", "limit_order", "stop_order",
               "cancel_order", "modify_position", "update_stop_loss",
               "submit_option_close", "close_or_refuse", "execute_close",
               "execute_take_trade", "execute_kill_switch", "search_no"}
#: The pure core opens no network (§4.3: "Never: keys, network").
NETWORK_MODULES = ("requests", "socket", "websockets", "urllib", "http",
                   "aiohttp", "httpx", "redis", "asyncio", "ssl",
                   "curl_cffi", "websocket")
#: What the feed may ask of a cache (Django's, the engine's rates cache
#: behind it) and of the redis client it is handed: reads, and the one
#: script that writes vq:* keys. Nothing that writes anything else.
CACHE_RECEIVERS = {"cache", "_cache"}
CACHE_ALLOWED = {"get"}
CLIENT_RECEIVERS = {"client", "_client"}
CLIENT_ALLOWED = {"register_script", "hgetall"}
#: The only Redis commands the compare-and-set script runs.
LUA_COMMANDS = {"HMGET", "HSET", "PEXPIRE"}
#: The switches the later phases bring (§6.3): none exists in F1.
LATER_SWITCHES = ("protective_unblock_live", "close_without_price_live",
                  "reference_truth_live", "venue_exit_booking_live",
                  "venue_marks_live", "venue_entries_live",
                  "venue_conversion_live", "posture_venue_series_live",
                  "venue_bars_live", "paper_venue_prices_live",
                  "venue_book_value_live", "morgul_venue_guard_live",
                  "orcs_venue_prices", "alerts_venue_prices",
                  "private_stream_hints_live", "venue_wake_live",
                  "etoro_pnl_display", "etoro_feed", "venue_feed_display",
                  "venue_pnl_delta_display")


def _money_files():
    for tree in MONEY_TREES:
        for path in sorted((BASE / tree).rglob("*.py")):
            if "migrations" in path.parts or "__pycache__" in path.parts:
                continue
            yield path
    for rel in MONEY_FILES:
        yield BASE / rel


def _feed_files():
    for rel in FEED_CORE + FEED_LATER:
        path = BASE / rel
        if path.exists():
            yield path


def _tree(path):
    return ast.parse(path.read_text(encoding="utf-8"))


def _names(tree):
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            out.add(node.id)
        elif isinstance(node, ast.Attribute):
            out.add(node.attr)
        elif isinstance(node, ast.alias):
            out.add(node.name.rsplit(".", 1)[-1])
            if node.asname:
                out.add(node.asname)
    return out


def _imports(tree):
    """Every module a file imports, top level or inside a function."""
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module)
            out.update(f"{node.module}.{a.name}" for a in node.names)
    return out


def _livequote_reads(tree) -> dict:
    """{enclosing definition: count of LiveQuote / .live_quote names}."""
    out = {}

    def walk(node, where):
        for child in ast.iter_child_nodes(node):
            w = where
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef,
                                  ast.ClassDef)):
                w = f"{where}.{child.name}" if where else child.name
            hit = ((isinstance(child, ast.Name)
                    and child.id in LIVEQUOTE_NAMES)
                   or (isinstance(child, ast.Attribute)
                       and child.attr in LIVEQUOTE_NAMES))
            if hit:
                key = where or "<module>"
                out[key] = out.get(key, 0) + 1
            walk(child, w)
    walk(tree, "")
    return out


def _strings(tree):
    """Every string constant, f-strings' literal parts included."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.value


def _receiver_calls(tree, receivers):
    """(receiver, method) of every call `<receiver>.<method>(...)` whose
    receiver is one of `receivers` (a name, or an attribute's last part)."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func,
                                                     ast.Attribute):
            r = node.func.value
            name = (r.id if isinstance(r, ast.Name)
                    else r.attr if isinstance(r, ast.Attribute) else None)
            if name in receivers:
                yield name, node.func.attr


class TheMoneyDoorPinTests(SimpleTestCase):
    """1. Money reads a price through money_price, never through the
    display or the reference wrappers."""

    FORBIDDEN = {"display_quote", "reference_quote"}

    def test_no_money_module_names_the_display_or_reference_wrappers(self):
        seen = 0
        for path in _money_files():
            hit = _names(_tree(path)) & self.FORBIDDEN
            self.assertFalse(hit, f"{path.relative_to(BASE)} names "
                                  f"{sorted(hit)}")
            seen += 1
        self.assertGreater(seen, 100, "the scan found the money modules")

    def test_the_scan_catches_every_spelling(self):
        for src in ("from market_data.venue_quotes import display_quote\n",
                    "from market_data import venue_quotes as v\n"
                    "v.reference_quote(None, symbol='EURUSD')\n",
                    "import market_data.venue_quotes\n"
                    "market_data.venue_quotes.display_quote(None)\n",
                    "from market_data.venue_quotes import reference_quote "
                    "as r\n"):
            self.assertTrue(_names(ast.parse(src)) & self.FORBIDDEN, src)

    def test_the_wrappers_exist_where_the_pin_looks(self):
        from market_data import venue_quotes
        for name in self.FORBIDDEN | {"money_price"}:
            self.assertTrue(callable(getattr(venue_quotes, name)), name)


class TheLiveQuoteRatchetTests(SimpleTestCase):
    """2. Today's LiveQuote reads in money modules, and not one more."""

    def test_no_new_read_and_no_stale_line(self):
        found = {}
        for path in _money_files():
            reads = _livequote_reads(_tree(path))
            if reads:
                found[path.relative_to(BASE).as_posix()] = reads
        for rel, reads in sorted(found.items()):
            allowed = LIVEQUOTE_RATCHET.get(rel, {})
            for where, n in sorted(reads.items()):
                self.assertLessEqual(
                    n, allowed.get(where, 0),
                    f"a new LiveQuote read in a money module: {rel} "
                    f"{where} reads it {n} time(s), the ratchet allows "
                    f"{allowed.get(where, 0)} — read eToro's price through "
                    f"market_data.venue_quotes.money_price instead")
        for rel, allowed in sorted(LIVEQUOTE_RATCHET.items()):
            for where, n in sorted(allowed.items()):
                got = found.get(rel, {}).get(where, 0)
                self.assertEqual(
                    got, n, f"{rel} {where} now reads LiveQuote {got} "
                            f"time(s), the ratchet says {n}: lower the line "
                            f"in LIVEQUOTE_RATCHET")

    def test_the_counter_counts_names_and_related_reads_not_imports(self):
        src = ("from market_data.models import LiveQuote\n"
               "def a(inst):\n"
               "    q = LiveQuote.objects.filter(instrument=inst).first()\n"
               "    return inst.live_quote.last if q else None\n"
               "class B:\n"
               "    def c(self):\n"
               "        from market_data import models\n"
               "        return models.LiveQuote.objects.all()\n")
        self.assertEqual(_livequote_reads(ast.parse(src)),
                         {"a": 2, "B.c": 1})


class TheFeedTradesNothingTests(SimpleTestCase):
    """3. The feed observes; it never trades (I15)."""

    def test_the_core_exists_and_is_scanned(self):
        scanned = {p.relative_to(BASE).as_posix() for p in _feed_files()}
        self.assertTrue(set(FEED_CORE) <= scanned, scanned)

    def test_no_feed_module_imports_an_order_path(self):
        for path in _feed_files():
            for mod in _imports(_tree(path)):
                with self.subTest(path=path.name, mod=mod):
                    self.assertFalse(
                        mod.startswith(tuple(p + "." for p in
                                             ORDER_PATH_PACKAGES))
                        or mod in ORDER_PATH_PACKAGES
                        or any(mod == m or mod.startswith(m + ".")
                               for m in ORDER_PATH_MODULES),
                        f"{path.relative_to(BASE)} imports {mod}")

    def test_no_feed_module_names_an_order_or_a_lookup(self):
        for path in _feed_files():
            tree = _tree(path)
            hit = _names(tree) & ORDER_NAMES
            self.assertFalse(hit, f"{path.relative_to(BASE)} names "
                                  f"{sorted(hit)}")
            for s in _strings(tree):
                self.assertNotIn("/search", s, path.name)
                self.assertNotIn("market-data/search", s, path.name)

    def test_the_scan_catches_an_order_path(self):
        tree = ast.parse("def f(c):\n"
                         "    from bot_program.engine.etoro_client import "
                         "EtoroTrader\n"
                         "    return c.instrument_id('EURUSD')\n")
        self.assertIn("bot_program.engine.etoro_client", _imports(tree))
        self.assertIn("instrument_id", _names(tree) & ORDER_NAMES)


class TheStoresAreTheFeedsTests(SimpleTestCase):
    """4 and 5. Only the feed names vq:*; the feed never writes LiveQuote or
    the engine's rates cache, and its core opens no network."""

    def _all_python(self):
        skip = {"tests", "venv", "node_modules", "static", "staticfiles",
                ".git", "media", "frontend"}
        for path in sorted(BASE.rglob("*.py")):
            rel = path.relative_to(BASE)
            if rel.parts[0] in skip or "migrations" in rel.parts \
                    or "__pycache__" in rel.parts or ".claude" in rel.parts:
                continue
            yield path

    def test_only_the_feed_names_a_vq_key(self):
        feed = {p.resolve() for p in _feed_files()}
        seen = 0
        for path in self._all_python():
            if path.resolve() in feed:
                continue
            seen += 1
            for s in _strings(_tree(path)):
                self.assertFalse(s.startswith("vq:"),
                                 f"{path.relative_to(BASE)} names {s!r}: "
                                 f"only the feed writes vq:*")
        self.assertGreater(seen, 500)

    def test_the_feed_never_writes_livequote(self):
        for path in _feed_files():
            tree = _tree(path)
            hit = _names(tree) & (LIVEQUOTE_NAMES | {"write_quote"})
            self.assertFalse(hit, f"{path.relative_to(BASE)} names "
                                  f"{sorted(hit)}")
            for mod in _imports(tree):
                self.assertFalse(mod.startswith("market_data.quotes"),
                                 f"{path.name} imports {mod}")
                self.assertNotEqual(mod, "market_data.models.LiveQuote")

    def test_the_feed_writes_no_cache_and_no_rates_before_f9(self):
        """The engine's rates cache (etoro_rates:r:*) is read, never
        written, before F9: the feed asks a cache for `get` only, imports
        none of the cache's writers, and its redis client only loads the
        script and reads a record back."""
        for path in _feed_files():
            tree = _tree(path)
            for receivers, allowed in ((CACHE_RECEIVERS, CACHE_ALLOWED),
                                       (CLIENT_RECEIVERS, CLIENT_ALLOWED)):
                for who, method in _receiver_calls(tree, receivers):
                    self.assertIn(method, allowed,
                                  f"{path.relative_to(BASE)} calls "
                                  f"{who}.{method}")
            for mod in _imports(tree):
                self.assertFalse(mod.startswith(
                    "bot_program.engine.etoro_rates"), f"{path.name} {mod}")

    def test_the_scan_catches_a_cache_write(self):
        tree = ast.parse("from django.core.cache import cache\n"
                         "def f(v):\n    cache.set('etoro_rates:r:live:1', v)\n")
        self.assertIn(("cache", "set"),
                      set(_receiver_calls(tree, CACHE_RECEIVERS)))

    def test_the_core_opens_no_network(self):
        for rel in FEED_CORE:
            for mod in _imports(_tree(BASE / rel)):
                root = mod.split(".", 1)[0]
                self.assertNotIn(root, NETWORK_MODULES, f"{rel} {mod}")

    def test_the_lua_script_writes_vq_keys_only(self):
        import re
        from market_data import venue_store
        self.assertIn("string.sub(key, 1, 3) ~= 'vq:'", venue_store.CAS_LUA)
        commands = set(re.findall(r"redis\.call\('([A-Z]+)'",
                                  venue_store.CAS_LUA))
        self.assertEqual(commands, LUA_COMMANDS)
        self.assertEqual(venue_store.VQ_PREFIX, "vq:")
        for fn in (venue_store.ws_key, venue_store.rest_key,
                   venue_store.ring_key):
            self.assertTrue(fn(1).startswith("vq:"))


class NoSwitchTests(SimpleTestCase):
    """6. F1 has no effect on money and adds no switch (/ops/ shows none)."""

    def test_no_money_door_is_open(self):
        from market_data import venue_quotes
        self.assertEqual(dict(venue_quotes.FEED_MONEY_SWITCHES), {})

    def test_none_of_the_later_switches_exists_yet(self):
        from core import platform_control
        src = (BASE / "core" / "platform_control.py").read_text(
            encoding="utf-8")
        for key in LATER_SWITCHES:
            self.assertNotIn(key, platform_control.LIVE_MONEY_SWITCHES)
            self.assertNotIn(f'"{key}"', src, key)
