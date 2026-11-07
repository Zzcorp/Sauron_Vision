"""THE FEED'S PINS (the eToro feed spec, F1, §6.2 Pins, I2, I7, I15;
2026-11-07). Source scans, in the style of tests/test_venue_pnl.py's
decision-module scan: they read the code, never run it.

  1. Money modules may not name display_quote or reference_quote (I7),
     as a name, an attribute or a string (getattr(module, "...")): money
     has one door, money_price. portfolio/services.py is scanned by the
     functions a decision shares with a page (tests/test_venue_pnl.py's
     SHARED), so its display section may grow eToro's screen.
  2. A ratchet of today's LiveQuote reads in money modules, by module and
     function, whatever the spelling: the model's name and its aliases,
     the `.live_quote` relation, the strings "live_quote"/"LiveQuote"
     (getattr, hasattr, apps.get_model) and every live_quote__ lookup. A
     new read fails; a read that goes away asks for the ratchet to be
     lowered. Each later phase moves a read behind the door and lowers its
     line; none may add one. Every line names the §5.10 adapter whose
     replay covers it (tests/feed/test_decision_replay.ADAPTERS).
  3. Feed modules may not import an order path, call /search or name
     instrument_id() (I15): the feed observes and never trades. A feed
     module is one the spec names (§4.3) or ANY module that imports the
     feed's store (market_data.venue_store) — not a closed list of file
     names — and each keeps its own rule (FEED_RULES).
  4. Only the feed's writers name a vq:* key or the store's write door
     (RedisVenueStore, the key builders, the script); only the client's
     rates parser writes the engine's rates cache (etoro_rates:r:*).
  5. The feed never writes LiveQuote — it imports no module that does
     (found by scanning every writer) — never writes any cache or redis
     key except through the store's one script, and its pure core opens
     no network.
  6. F1 adds no switch: no money door is open, and none of the switches
     the later phases bring exists yet.

Run with:  python manage.py test tests.feed.test_feed_pins
"""
import ast
import functools
import sys
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

BASE = Path(settings.BASE_DIR)

#: Every module that decides money (tests/test_venue_pnl.py's decision
#: scan) and signals/performance.py, whose outcome grading feeds sizing
#: (bot_program/asset_engine/aggregation.py).
MONEY_TREES = ("bot_program", "brain", "ai_agents")
MONEY_FILES = ("portfolio/risk_gate.py", "portfolio/tasks.py",
               "portfolio/position_sizing.py", "market_data/bot_bars.py",
               "signals/performance.py")
#: Files a page and a decision share: scanned by these functions only,
#: the ones a decision reads (tests/test_venue_pnl.py SHARED).
MONEY_FUNCTIONS = {
    "portfolio/services.py": (
        "live_book_value", "_trade_to_position", "_normalize_trades",
        "unified_open_positions", "unified_closed_positions",
        "capital_summary", "usd_per_unit", "notional_usd",
        "pnl_on_capital_pct", "_capital_at_work"),
}

#: The feed's modules the spec names (§4.3). F1's three exist; the later
#: ones are scanned from the day they do. Any other module that imports
#: the feed's store is a feed module too (_feed_files).
FEED_CORE = ("market_data/venue_quotes.py", "market_data/venue_store.py",
             "market_data/venue_session.py")
FEED_LATER = ("market_data/feed_wants.py",
              "market_data/management/commands/stream_etoro.py",
              "bot_program/engine/etoro_stream.py",
              "portfolio/pnl_venue.py", "bot_program/etoro_pnl.py",
              "bot_program/feed_shadow.py")
#: Each feed module's own rule (§4.3): the order-path packages it may
#: still import from — the core none at all (no bot_program.engine), the
#: stream client its own package's non-order modules, the /pnl reader the
#: client it reads /pnl through. Every feed module, whatever its rule,
#: names no order method and no lookup, and imports no order module.
FEED_RULES = {
    "market_data/venue_quotes.py": (),
    "market_data/venue_store.py": (),
    "market_data/venue_session.py": (),
    "bot_program/engine/etoro_stream.py": (
        "bot_program.engine.etoro_budget",),
    "bot_program/etoro_pnl.py": ("bot_program.engine.etoro_client",
                                 "bot_program.engine.etoro_budget"),
}
#: (A feed module not listed keeps the strictest rule, the core's; a later
#: module's rule widens here, by name, in its own pull request.)
#: The feed's writers: the only modules that may name the store's write
#: door or a vq:* key. The store itself and the stream service (F6); the
#: REST fallback's module joins by name in its own pull request.
FEED_WRITERS = ("market_data/venue_store.py",
                "market_data/management/commands/stream_etoro.py")
#: The store's write door: whoever takes one of these from the store can
#: write vq:*. STORE_DISTINCT are names no other module uses, caught
#: however they are reached; record_key is a common name (the Orcs'
#: scheduler has its own), caught when taken from the store.
STORE_WRITE_DOOR = {"RedisVenueStore", "MemoryVenueStore", "ws_key",
                    "rest_key", "ring_key", "record_key", "VQ_PREFIX",
                    "CAS_LUA"}
STORE_DISTINCT = STORE_WRITE_DOOR - {"record_key"}
#: Who may write the engine's rates cache: the client's rates parser
#: (etoro_rates.put / put_many), and the cache module itself.
RATES_WRITERS = ("bot_program/engine/etoro_client.py",
                 "bot_program/engine/etoro_rates.py")
RATES_WRITE_NAMES = {"put", "put_many", "_put_many_now"}
#: Who may name the rates cache's key text: the cache itself, and the
#: feed's read-only view of it.
RATES_KEY_NAMERS = ("bot_program/engine/etoro_rates.py",
                    "market_data/venue_store.py")

#: TODAY'S LiveQuote READS IN MONEY MODULES (2026-11-07, main at F1), by
#: module and enclosing definition, whatever the spelling (see
#: _livequote_reads), each with the §5.10 adapter whose replay covers it.
#: A new read fails; a read that goes away lowers its line here, in the
#: same change.
LIVEQUOTE_RATCHET = {
    "ai_agents/calibration.py": {"mark_for_symbol": (1, "M11")},
    "ai_agents/tasks.py": {"generate_daily_commentary": (2, "M11"),
                           "optimize_strategies": (1, "M11"),
                           "run_anomaly_detection": (1, "M11")},
    "bot_program/adjust_levels.py": {"_mark_for": (1, "M10")},
    "bot_program/asset_engine/forex_bot.py": {
        "quote_ccy_usd_rate._live": (1, "M12")},
    "bot_program/engine/kill_switch.py": {"_market_exit_price": (1, "M6")},
    "bot_program/engine/paper_trader.py": {
        "PaperTrader.market_order": (1, "M16"),
        "PaperTrader.order_book": (1, "M16"),
        "PaperTrader.ticker": (1, "M16")},
    "bot_program/etoro_quotes.py": {"_holder": (1, "M9")},
    "bot_program/management/commands/open_trades.py": {
        "_open_mark": (1, "display")},
    "bot_program/mark_sanity.py": {"second_opinion": (1, "M2")},
    "bot_program/market_stress.py": {"_daily_closes": (1, "M13")},
    "bot_program/morgul.py": {"check_heartbeat": (1, "M14")},
    "bot_program/nl_trader.py": {"NLTradeParser.execute": (4, "M18")},
    "bot_program/orcs/dossier.py": {"_mark": (1, "M19")},
    "bot_program/orcs/drum_bus.py": {"_last": (1, "M19")},
    "bot_program/orcs/grading.py": {"_usd_per.quote": (1, "M19")},
    "bot_program/orcs/situation.py": {"_spread": (1, "M19")},
    "bot_program/orcs/sources.py": {"quote": (1, "M19"),
                                    "quotes": (1, "M19")},
    "bot_program/reconcile_asset.py": {"_close_as_orphan": (1, "M8")},
    "bot_program/tasks.py": {"refresh_option_chains_for_user": (1, "M1")},
    "brain/position_review.py": {"_venue_mark_for": (1, "M11")},
    "portfolio/services.py": {"_normalize_trades": (1, "M17")},
    "portfolio/tasks.py": {"_mark_for": (1, "M17")},
    "signals/performance.py": {"evaluate_signal_outcome": (1, "M3")},
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
#: The names that send, change or cancel at a venue, or look an id up —
#: the real eToro client's writes included.
ORDER_NAMES = {"instrument_id", "market_order", "close_position",
               "open_position", "place_order", "limit_order", "stop_order",
               "cancel_order", "modify_position", "update_stop_loss",
               "modify_protective", "modify_target", "submit_option_close",
               "close_or_refuse", "execute_close", "execute_take_trade",
               "execute_kill_switch", "search_no"}
#: The pure core opens no network (§4.3: "Never: keys, network").
NETWORK_MODULES = ("requests", "socket", "websockets", "urllib", "http",
                   "aiohttp", "httpx", "redis", "asyncio", "ssl",
                   "curl_cffi", "websocket")
#: What the feed may ask of a redis client it is handed: load the one
#: script, and read a record back.
CLIENT_RECEIVERS = {"client", "_client"}
CLIENT_ALLOWED = {"register_script", "hgetall"}
#: Methods that write a cache, a redis key or a channel, on ANY receiver.
#: A feed module calls none of them except the ones listed in
#: FEED_WRITE_CALLS (a Python set's add, a Counter's update...).
WRITE_METHODS = {"set", "set_many", "add", "incr", "decr", "delete",
                 "delete_many", "touch", "clear", "hset", "hmset", "hsetnx",
                 "hdel", "expire", "pexpire", "persist", "eval", "evalsha",
                 "execute_command", "setex", "psetex", "getset", "setnx",
                 "lpush", "rpush", "sadd", "zadd", "xadd", "publish",
                 "group_send", "send"}
#: (feed module, enclosing definition, receiver, method): the only write-
#: shaped calls the feed makes, none of them a cache's.
FEED_WRITE_CALLS = {
    ("market_data/venue_quotes.py", "grade", "flags", "add"),
}
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

_SKIP_TOP = {"tests", "venv", "node_modules", "static", "staticfiles",
             ".git", "media", "frontend"}


def _rel(path) -> str:
    return path.relative_to(BASE).as_posix()


def _all_python():
    """Every non-test, non-migration module of the code base."""
    for path in sorted(BASE.rglob("*.py")):
        rel = path.relative_to(BASE)
        if rel.parts[0] in _SKIP_TOP or "migrations" in rel.parts \
                or "__pycache__" in rel.parts or ".claude" in rel.parts:
            continue
        yield path


def _money_files():
    """(path, the definitions scanned or None for the whole file)."""
    for tree in MONEY_TREES:
        for path in sorted((BASE / tree).rglob("*.py")):
            if "migrations" in path.parts or "__pycache__" in path.parts:
                continue
            yield path, None
    for rel in MONEY_FILES:
        yield BASE / rel, None
    for rel, funcs in MONEY_FUNCTIONS.items():
        yield BASE / rel, funcs


@functools.lru_cache(maxsize=None)
def _tree(path):
    return ast.parse(path.read_text(encoding="utf-8"))


def _scoped(tree, funcs):
    """The nodes a scan reads: the whole tree, or the named top-level
    definitions only."""
    if funcs is None:
        return [tree]
    found = [n for n in tree.body
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef,
                               ast.ClassDef)) and n.name in funcs]
    return found


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


def _strings(tree):
    """Every string constant, f-strings' literal parts included."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.value


def _code_strings(tree):
    """Every string constant but docstrings and other bare string
    statements: what the code can hand to a cache or a client."""
    prose = {id(n.value) for n in ast.walk(tree)
             if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)}
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                and id(node) not in prose:
            yield node.value


def _imports(tree):
    """Every module a file imports, top level or inside a function, and
    each imported name as module.name; relative imports resolved."""
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module)
            out.update(f"{node.module}.{a.name}" for a in node.names)
    return out


def _module_of(path) -> str:
    return _rel(path)[:-3].replace("/", ".").removesuffix(".__init__")


def _aliases(tree, names):
    """Local names bound to one of `names` by an import (`import ... as`)."""
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for a in node.names:
                if a.name in names and a.asname:
                    out.add(a.asname)
    return out


def _is_livequote_string(s) -> bool:
    return s in LIVEQUOTE_NAMES or s.startswith("live_quote__")


def _livequote_reads(tree) -> dict:
    """{enclosing definition: count of LiveQuote reads}, whatever the
    spelling: the model's name or an import alias of it, the
    `.live_quote` relation, a "live_quote"/"LiveQuote" string handed to a
    call (getattr, hasattr, apps.get_model, select_related, values_list)
    or a live_quote__ lookup (a call's string or keyword). The import line
    itself is not a read, nor a docstring, nor a string that is no call's
    argument (a label such as `return spread, "live_quote"`)."""
    alias = _aliases(tree, {"LiveQuote"})
    out = {}

    def hits(node) -> int:
        if isinstance(node, ast.Name):
            return int(node.id in LIVEQUOTE_NAMES or node.id in alias)
        if isinstance(node, ast.Attribute):
            return int(node.attr in LIVEQUOTE_NAMES)
        if isinstance(node, ast.keyword) and node.arg:
            return int(node.arg == "live_quote"
                       or node.arg.startswith("live_quote__"))
        if isinstance(node, ast.Call):
            return sum(1 for a in node.args
                       if isinstance(a, ast.Constant)
                       and isinstance(a.value, str)
                       and _is_livequote_string(a.value))
        return 0

    def walk(node, where):
        for child in ast.iter_child_nodes(node):
            w = where
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef,
                                  ast.ClassDef)):
                w = f"{where}.{child.name}" if where else child.name
            if isinstance(child, (ast.Import, ast.ImportFrom)):
                continue
            n = hits(child)
            if n:
                key = where or "<module>"
                out[key] = out.get(key, 0) + n
            walk(child, w)
    walk(tree, "")
    return out


def _store_aliases(tree) -> set:
    """Local names bound to the store's module (market_data.venue_store),
    by any import spelling."""
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "market_data":
            for a in node.names:
                if a.name == "venue_store":
                    out.add(a.asname or a.name)
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.name == "market_data.venue_store":
                    out.add(a.asname or "market_data")
    return out


def _store_door_uses(tree) -> set:
    """The store's write-door names a module takes: imported from the
    store, read off the store's module, or — for the names no other module
    uses — named at all."""
    door = set()
    aliases = _store_aliases(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and \
                node.module == "market_data.venue_store":
            door |= {a.name for a in node.names} & STORE_WRITE_DOOR
        elif isinstance(node, ast.Attribute) and \
                node.attr in STORE_WRITE_DOOR:
            base = node.value
            while isinstance(base, ast.Attribute):
                base = base.value
            if isinstance(base, ast.Name) and base.id in aliases:
                door.add(node.attr)
            elif node.attr in STORE_DISTINCT:
                door.add(node.attr)
        elif isinstance(node, ast.Name) and node.id in STORE_DISTINCT:
            door.add(node.id)
    door |= set(_code_strings(tree)) & STORE_DISTINCT
    return door


def _receiver_calls(tree, receivers=None):
    """(receiver name, method, enclosing definition) of every call
    `<receiver>.<method>(...)`; `receivers` narrows to those names (a
    name, or an attribute's last part)."""
    out = []

    def walk(node, where):
        for child in ast.iter_child_nodes(node):
            w = where
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef,
                                  ast.ClassDef)):
                w = f"{where}.{child.name}" if where else child.name
            if isinstance(child, ast.Call) and isinstance(child.func,
                                                          ast.Attribute):
                r = child.func.value
                name = (r.id if isinstance(r, ast.Name)
                        else r.attr if isinstance(r, ast.Attribute)
                        else type(r).__name__)
                if receivers is None or name in receivers:
                    out.append((name, child.func.attr, where))
            walk(child, w)
    walk(tree, "")
    return out


@functools.lru_cache(maxsize=None)
def _livequote_writers() -> frozenset:
    """Every module that writes LiveQuote: it calls write_quote, or a
    LiveQuote manager's create/update/delete."""
    writes = {"create", "update_or_create", "get_or_create", "bulk_create",
              "bulk_update", "update", "delete"}
    out = set()
    for path in _all_python():
        text = path.read_text(encoding="utf-8")
        if "write_quote" not in text and "LiveQuote" not in text:
            continue
        for node in ast.walk(ast.parse(text)):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            name = f.id if isinstance(f, ast.Name) else \
                f.attr if isinstance(f, ast.Attribute) else ""
            if name == "write_quote":
                out.add(_module_of(path))
                break
            if name in writes and "LiveQuote" in ast.dump(f):
                out.add(_module_of(path))
                break
    return frozenset(out)


def _feed_files():
    """The spec's feed modules that exist, and every other non-test module
    that imports the feed's store (any spelling: _imports names
    `from market_data import venue_store` as market_data.venue_store)."""
    seen = set()
    for rel in FEED_CORE + FEED_LATER:
        path = BASE / rel
        if path.exists():
            seen.add(path)
            yield path
    for path in _all_python():
        if path not in seen and \
                "market_data.venue_store" in _imports(_tree(path)):
            yield path


# ── 1. the money door ────────────────────────────────────────────────────

class TheMoneyDoorPinTests(SimpleTestCase):
    """1. Money reads a price through money_price, never through the
    display or the reference wrappers, by any spelling."""

    FORBIDDEN = {"display_quote", "reference_quote"}

    def _hits(self, node):
        return (_names(node) & self.FORBIDDEN) | \
            (set(_strings(node)) & self.FORBIDDEN)

    def test_no_money_module_names_the_display_or_reference_wrappers(self):
        seen = 0
        for path, funcs in _money_files():
            for node in _scoped(_tree(path), funcs):
                hit = self._hits(node)
                self.assertFalse(hit, f"{_rel(path)} names {sorted(hit)}")
            seen += 1
        self.assertGreater(seen, 100, "the scan found the money modules")

    def test_the_scan_catches_every_spelling(self):
        for src in ("from market_data.venue_quotes import display_quote\n",
                    "from market_data import venue_quotes as v\n"
                    "v.reference_quote(None, symbol='EURUSD')\n",
                    "import market_data.venue_quotes\n"
                    "market_data.venue_quotes.display_quote(None)\n",
                    "from market_data.venue_quotes import reference_quote "
                    "as r\n",
                    "from market_data import venue_quotes\n"
                    "getattr(venue_quotes, 'display_quote')(None, None)\n",
                    "import importlib\n"
                    "importlib.import_module('market_data.venue_quotes')"
                    ".__dict__['reference_quote']\n"):
            with self.subTest(src=src):
                self.assertTrue(self._hits(ast.parse(src)), src)

    def test_services_is_scanned_by_the_functions_a_decision_shares(self):
        """The display section of portfolio/services.py ("THE VENUE'S OWN
        P&L") may call display_quote (F4, F7); the functions a decision
        reads may not. The list is tests/test_venue_pnl.py's SHARED."""
        from tests.test_venue_pnl import SHARED
        self.assertEqual(MONEY_FUNCTIONS["portfolio/services.py"],
                         SHARED["portfolio/services.py"])
        tree = _tree(BASE / "portfolio" / "services.py")
        found = {n.name for n in _scoped(tree, MONEY_FUNCTIONS[
            "portfolio/services.py"])}
        self.assertEqual(found, set(MONEY_FUNCTIONS["portfolio/services.py"]))
        page = ast.parse("def venue_pnls():\n"
                         "    from market_data.venue_quotes import "
                         "display_quote\n")
        self.assertEqual(_scoped(page, MONEY_FUNCTIONS[
            "portfolio/services.py"]), [], "a page's function is not scanned")

    def test_the_wrappers_exist_where_the_pin_looks(self):
        from market_data import venue_quotes
        for name in self.FORBIDDEN | {"money_price"}:
            self.assertTrue(callable(getattr(venue_quotes, name)), name)


# ── 2. the LiveQuote ratchet ─────────────────────────────────────────────

class TheLiveQuoteRatchetTests(SimpleTestCase):
    """2. Today's LiveQuote reads in money modules, and not one more."""

    def _found(self):
        found = {}
        for path, funcs in _money_files():
            reads = {}
            for node in _scoped(_tree(path), funcs):
                part = _livequote_reads(node) if funcs is None else {
                    f"{node.name}{'.' + k if k != '<module>' else ''}": v
                    for k, v in _livequote_reads(node).items()}
                for k, v in part.items():
                    reads[k] = reads.get(k, 0) + v
            if reads:
                found[_rel(path)] = reads
        return found

    def test_no_new_read_and_no_stale_line(self):
        found = self._found()
        for rel, reads in sorted(found.items()):
            allowed = LIVEQUOTE_RATCHET.get(rel, {})
            for where, n in sorted(reads.items()):
                cap = allowed.get(where, (0, ""))[0]
                self.assertLessEqual(
                    n, cap,
                    f"a new LiveQuote read in a money module: {rel} "
                    f"{where} reads it {n} time(s), the ratchet allows "
                    f"{cap} — read eToro's price through "
                    f"market_data.venue_quotes.money_price instead")
        for rel, allowed in sorted(LIVEQUOTE_RATCHET.items()):
            for where, (n, _adapter) in sorted(allowed.items()):
                got = found.get(rel, {}).get(where, 0)
                self.assertEqual(
                    got, n, f"{rel} {where} now reads LiveQuote {got} "
                            f"time(s), the ratchet says {n}: lower the line "
                            f"in LIVEQUOTE_RATCHET")

    def test_every_line_names_a_registered_adapter(self):
        """§5.10's completeness pin: a money module's LiveQuote read is
        registered to the replay adapter that covers it."""
        from tests.feed.test_decision_replay import ADAPTERS
        for rel, allowed in LIVEQUOTE_RATCHET.items():
            for where, (_n, adapter) in allowed.items():
                self.assertIn(adapter, ADAPTERS, f"{rel} {where}")

    def test_the_counter_counts_every_spelling_and_not_imports(self):
        src = ("from market_data.models import LiveQuote\n"
               "from market_data.models import LiveQuote as LQ\n"
               "def a(inst):\n"
               "    label = 'live_quote'\n"
               "    '''LiveQuote in a docstring is no read'''\n"
               "    q = LiveQuote.objects.filter(instrument=inst).first()\n"
               "    return inst.live_quote.last if q else None\n"
               "class B:\n"
               "    def c(self):\n"
               "        from market_data import models\n"
               "        return models.LiveQuote.objects.all()\n"
               "def d(inst, apps, qs):\n"
               "    getattr(inst, 'live_quote', None)\n"
               "    hasattr(inst, 'live_quote')\n"
               "    apps.get_model('market_data', 'LiveQuote')\n"
               "    qs.values_list('live_quote__last', flat=True)\n"
               "    qs.filter(live_quote__last__gt=0)\n"
               "    LQ.objects.first()\n")
        self.assertEqual(_livequote_reads(ast.parse(src)),
                         {"a": 2, "B.c": 1, "d": 6})

    def test_the_review_spellings_are_caught(self):
        """2026-11-07, review: four new reads passed the old counter."""
        for src in ("def f(inst):\n    return getattr(inst, 'live_quote',"
                    " None)\n",
                    "from market_data.models import LiveQuote as LQ\n"
                    "def f():\n    return LQ.objects.first()\n",
                    "def f(qs):\n    return qs.values_list("
                    "'live_quote__last')\n",
                    "def f(apps):\n    return apps.get_model('market_data',"
                    " 'LiveQuote')\n"):
            with self.subTest(src=src):
                self.assertEqual(_livequote_reads(ast.parse(src)), {"f": 1})


# ── 3. the feed trades nothing ───────────────────────────────────────────

class TheFeedTradesNothingTests(SimpleTestCase):
    """3. The feed observes; it never trades (I15)."""

    def test_the_core_exists_and_is_scanned(self):
        scanned = {_rel(p) for p in _feed_files()}
        self.assertTrue(set(FEED_CORE) <= scanned, scanned)

    def test_a_module_that_imports_the_store_is_a_feed_module(self):
        """2026-11-07, review: a feed module named otherwise than the list
        escaped every rule (market_data/venue_rest_fallback.py). Whoever
        imports the store, by any spelling, is scanned as the feed."""
        for src in ("from market_data.venue_store import frame\n",
                    "from market_data import venue_store\n",
                    "import market_data.venue_store as vs\n"):
            with self.subTest(src=src):
                self.assertIn("market_data.venue_store",
                              _imports(ast.parse(src)))
        found = {_rel(p) for p in _feed_files()}
        importers = {_rel(p) for p in _all_python()
                     if "market_data.venue_store" in _imports(_tree(p))}
        self.assertTrue(importers <= found, importers - found)

    def _order_imports(self, rel, mods):
        allowed = FEED_RULES.get(rel, ())
        bad = []
        for mod in mods:
            if any(mod == a or mod.startswith(a + ".") for a in allowed):
                continue
            if mod in ORDER_PATH_PACKAGES or mod.startswith(tuple(
                    p + "." for p in ORDER_PATH_PACKAGES)) or any(
                    mod == m or mod.startswith(m + ".")
                    for m in ORDER_PATH_MODULES):
                bad.append(mod)
        return bad

    def test_no_feed_module_imports_an_order_path(self):
        for path in _feed_files():
            rel = _rel(path)
            mods = _imports(_tree(path))
            with self.subTest(path=rel):
                self.assertEqual(self._order_imports(rel, mods), [])
                for mod in mods:
                    self.assertFalse(any(
                        mod == m or mod.startswith(m + ".")
                        for m in ORDER_PATH_MODULES), f"{rel} imports {mod}")

    def test_each_feed_module_keeps_its_own_rule(self):
        """The core imports nothing of the engine; the stream client may
        use its package's budget; the /pnl reader may use the client it
        reads /pnl through — and none of them an order module."""
        self.assertEqual(self._order_imports(
            "market_data/venue_quotes.py",
            {"bot_program.engine.etoro_rates"}),
            ["bot_program.engine.etoro_rates"])
        self.assertEqual(self._order_imports(
            "bot_program/etoro_pnl.py",
            {"bot_program.engine.etoro_client",
             "bot_program.engine.kill_switch"}),
            ["bot_program.engine.kill_switch"])
        self.assertEqual(self._order_imports(
            "bot_program/engine/etoro_stream.py",
            {"bot_program.engine.etoro_budget",
             "bot_program.engine.etoro_client"}),
            ["bot_program.engine.etoro_client"])

    def test_no_feed_module_names_an_order_or_a_lookup(self):
        for path in _feed_files():
            tree = _tree(path)
            hit = (_names(tree) | set(_strings(tree))) & ORDER_NAMES
            self.assertFalse(hit, f"{_rel(path)} names {sorted(hit)}")
            for s in _strings(tree):
                self.assertNotIn("/search", s, path.name)
                self.assertNotIn("market-data/search", s, path.name)

    def test_the_scan_catches_an_order_path(self):
        tree = ast.parse("def f(c):\n"
                         "    from bot_program.engine.etoro_client import "
                         "EtoroTrader\n"
                         "    getattr(c, 'modify_protective')\n"
                         "    return c.instrument_id('EURUSD')\n")
        self.assertIn("bot_program.engine.etoro_client", _imports(tree))
        self.assertEqual((_names(tree) | set(_strings(tree))) & ORDER_NAMES,
                         {"instrument_id", "modify_protective"})


# ── 4 and 5. the stores are the feed's ───────────────────────────────────

class TheStoresAreTheFeedsTests(SimpleTestCase):
    """4 and 5. Only the feed's writers name vq:* or the store's write
    door; only the client's rates parser writes the engine's rates cache;
    the feed never writes LiveQuote or any cache, and its core opens no
    network."""

    def test_only_the_feeds_writers_name_a_vq_key(self):
        writers = {BASE / rel for rel in FEED_WRITERS}
        seen = 0
        for path in _all_python():
            if path in writers:
                continue
            seen += 1
            for s in _code_strings(_tree(path)):
                self.assertFalse(s.startswith("vq:"),
                                 f"{_rel(path)} names {s!r}: only the "
                                 f"feed's writers write vq:*")
        self.assertGreater(seen, 500)

    def test_only_the_feeds_writers_name_the_stores_write_door(self):
        """2026-11-07, review: RedisVenueStore(client).write(...) and
        cache.set(ws_key(1), ...) wrote vq:* from a page and a poller with
        no "vq:" literal in sight. The door's names are the writers'."""
        writers = {BASE / rel for rel in FEED_WRITERS}
        for path in _all_python():
            if path in writers:
                continue
            hit = _store_door_uses(_tree(path))
            self.assertFalse(hit, f"{_rel(path)} names {sorted(hit)}: "
                                  f"only the feed's writers write vq:*")

    def test_the_door_scan_catches_the_reviews_writes(self):
        for src in ("from market_data.venue_store import RedisVenueStore\n"
                    "def f(c, fr):\n    RedisVenueStore(c).write(1, 'ws', "
                    "fr)\n",
                    "from django.core.cache import cache\n"
                    "from market_data import venue_store as vs\n"
                    "def f(v):\n    cache.set(vs.ws_key(1), v)\n",
                    "import market_data.venue_store\n"
                    "def f(v):\n    return market_data.venue_store"
                    ".record_key('ws', 1)\n",
                    "from market_data.venue_store import record_key\n"):
            with self.subTest(src=src):
                self.assertTrue(_store_door_uses(ast.parse(src)), src)
        self.assertFalse(_store_door_uses(ast.parse(
            "def record_key(x):\n    return x\nrecord_key(1)\n")),
            "another module's own record_key is not the store's")

    def test_only_the_rates_parser_writes_the_engines_rates_cache(self):
        """I2's other half: etoro_rates:r:* is written by the client's
        rates reads (etoro_rates.put / put_many) and nothing else; its key
        text is named by the cache and the feed's read-only view only."""
        for path in _all_python():
            rel = _rel(path)
            tree = _tree(path)
            if rel not in RATES_KEY_NAMERS:
                for s in _code_strings(tree):
                    self.assertNotIn("etoro_rates:r:", s, rel)
            if rel in RATES_WRITERS:
                continue
            calls = {(r, m) for r, m, _w in _receiver_calls(tree)}
            for r, m in calls:
                self.assertFalse(r == "etoro_rates" and m in
                                 RATES_WRITE_NAMES,
                                 f"{rel} calls etoro_rates.{m}")
            for mod in _imports(tree):
                self.assertFalse(
                    mod.startswith("bot_program.engine.etoro_rates.")
                    and mod.rsplit(".", 1)[-1] in RATES_WRITE_NAMES,
                    f"{rel} imports {mod}")

    def test_the_feed_never_writes_livequote(self):
        """2026-11-07, review: importing the interim beat's refresh or the
        Yahoo adapter's save_quote_to_db passed. The feed imports no module
        that writes LiveQuote — the writers found by scanning them."""
        writers = _livequote_writers()
        self.assertTrue({"market_data.quotes", "bot_program.etoro_quotes",
                         "market_data.adapters.yfinance_adapter"} <= writers,
                        writers)
        for path in _feed_files():
            tree = _tree(path)
            hit = _names(tree) & (LIVEQUOTE_NAMES | {"write_quote"})
            self.assertFalse(hit, f"{_rel(path)} names {sorted(hit)}")
            for mod in _imports(tree):
                self.assertFalse(
                    mod in writers or mod.rsplit(".", 1)[0] in writers,
                    f"{_rel(path)} imports {mod}, a LiveQuote writer")
                self.assertNotEqual(mod, "market_data.models.LiveQuote")

    def test_the_feed_writes_no_cache_and_no_rates_before_f9(self):
        """The engine's rates cache (etoro_rates:r:*) is read, never
        written, before F9: no feed module makes a write-shaped call on
        ANY receiver (a cache, a client, a channel layer — however it is
        named) beyond FEED_WRITE_CALLS, its redis client only loads the
        script and reads a record back, and none imports the rates
        cache's module."""
        for path in _feed_files():
            rel = _rel(path)
            tree = _tree(path)
            for who, method, where in _receiver_calls(tree):
                if method in WRITE_METHODS:
                    self.assertIn((rel, where, who, method),
                                  FEED_WRITE_CALLS,
                                  f"{rel} {where} calls {who}.{method}")
            for who, method, _w in _receiver_calls(tree, CLIENT_RECEIVERS):
                self.assertIn(method, CLIENT_ALLOWED,
                              f"{rel} calls {who}.{method}")
            for mod in _imports(tree):
                self.assertFalse(mod.startswith(
                    "bot_program.engine.etoro_rates"), f"{path.name} {mod}")

    def test_the_scan_catches_a_write_on_any_receiver(self):
        """2026-11-07, review: caches["default"].set, a renamed cache and
        self._r.hset passed a scan keyed on the receiver's name."""
        for src in ("from django.core.cache import caches\n"
                    "def f(v):\n    caches['default'].set('k', v)\n",
                    "from django.core.cache import cache as c\n"
                    "def f(v):\n    c.set('k', v)\n",
                    "class S:\n    def f(self, v):\n"
                    "        self._r.hset('k', 'f', v)\n"):
            with self.subTest(src=src):
                methods = {m for _r, m, _w in _receiver_calls(
                    ast.parse(src))}
                self.assertTrue(methods & WRITE_METHODS, src)

    def test_the_core_opens_no_network(self):
        for rel in FEED_CORE:
            for mod in _imports(_tree(BASE / rel)):
                root = mod.split(".", 1)[0]
                self.assertNotIn(root, NETWORK_MODULES, f"{rel} {mod}")

    def test_the_venue_source_rule_imports_the_standard_library_only(self):
        """Its callers import it at module level inside code that fails
        open; it must load wherever they do."""
        tree = _tree(BASE / "market_data" / "venue_source.py")
        roots = {m.split(".", 1)[0] for m in _imports(tree)}
        self.assertTrue(roots <= set(sys.stdlib_module_names) | {
            "__future__"}, roots)

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


# ── 6. no switch ─────────────────────────────────────────────────────────

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
