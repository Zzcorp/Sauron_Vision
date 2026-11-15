"""ONE PRICE EVERYWHERE IS DISPLAY ONLY (2026-11-12): money direction none.

The rule every screen prints a price by (market_data.one_quote) may pick a
newer eToro reading than the one a row is valued at, and the relay pushes
it to the browsers. Neither may ever reach a money path: entries, sizing,
the manage tick, the marks stops are measured on, closes, the kill switch,
bookings, valuation and P&L read exactly what they read before. Source
scans in the style of tests/feed/test_feed_pins.py (its I7 pin: money
modules may not name the display wrappers), over the same money modules:

  * no money module imports market_data.one_quote, by any spelling;
  * no money module names its entry points (shown, shown_many,
    for_request, push_shown, relay_held_quotes) as a name, an attribute
    or a string;
  * the rule itself writes nothing, opens no network and imports no order
    path.

Run with:  python manage.py test tests.test_one_quote_pins
"""
import ast
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from tests.feed.test_feed_pins import (_imports, _money_files, _names, _rel,
                                       _scoped, _strings, _tree)

BASE = Path(settings.BASE_DIR)
MODULE = "market_data.one_quote"
FORBIDDEN = {"shown_many", "push_shown", "relay_held_quotes", "one_quote"}
#: "shown" and "for_request" are ordinary words; they are forbidden as an
#: attribute of the rule's module or an import from it.
FORBIDDEN_FROM_MODULE = {"shown", "for_request", "Registry", "Shown"}


def _hits(node):
    hit = (_names(node) & FORBIDDEN) | (set(_strings(node)) & (
        FORBIDDEN | {MODULE}))
    for n in ast.walk(node):
        if isinstance(n, ast.ImportFrom) and n.module and \
                n.module.startswith(MODULE):
            hit.add(n.module)
        elif isinstance(n, ast.ImportFrom) and n.module == "market_data":
            hit |= {a.name for a in n.names if a.name == "one_quote"}
        elif isinstance(n, ast.Import):
            hit |= {a.name for a in n.names if a.name.startswith(MODULE)}
        elif isinstance(n, ast.Attribute) and \
                n.attr in FORBIDDEN_FROM_MODULE and \
                isinstance(n.value, (ast.Name, ast.Attribute)) and \
                getattr(n.value, "id", getattr(n.value, "attr", "")) == \
                "one_quote":
            hit.add(n.attr)
    return hit


class NoMoneyPathReadsTheRuleTests(SimpleTestCase):

    def test_no_money_module_reaches_the_rule(self):
        seen = 0
        for path, funcs in _money_files():
            for node in _scoped(_tree(path), funcs):
                hit = _hits(node)
                self.assertFalse(hit, f"{_rel(path)} names {sorted(hit)}")
            seen += 1
        self.assertGreater(seen, 100, "the scan found the money modules")

    def test_the_scan_catches_every_spelling(self):
        for src in ("from market_data.one_quote import shown\n",
                    "from market_data import one_quote\none_quote.shown('X')\n",
                    "import market_data.one_quote\n",
                    "from market_data.one_quote import shown_many as s\n",
                    "import importlib\n"
                    "importlib.import_module('market_data.one_quote')\n",
                    "from dashboard.consumers import push_shown\n",
                    "x = getattr(tasks, 'relay_held_quotes')\n"):
            with self.subTest(src=src):
                self.assertTrue(_hits(ast.parse(src)), src)


class TheRuleOnlyReadsTests(SimpleTestCase):

    def setUp(self):
        self.path = BASE / "market_data" / "one_quote.py"
        self.tree = ast.parse(self.path.read_text(encoding="utf-8"))

    def test_it_imports_no_order_path_no_network_and_no_writer(self):
        imports = _imports(self.tree)
        for bad in ("requests", "httpx", "urllib.request", "socket",
                    "bot_program.engine", "bot_program.manual_trade",
                    "bot_program.manual_close", "market_data.quotes",
                    "market_data.venue_store", "yfinance", "anthropic"):
            self.assertFalse(
                any(i == bad or i.startswith(bad + ".") for i in imports),
                bad)

    def test_it_writes_nothing(self):
        writes = {"save", "create", "update", "update_or_create",
                  "get_or_create", "bulk_create", "bulk_update", "delete",
                  "set", "set_many", "incr", "write_quote", "stamp",
                  "stamp_rows"}
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Call) and \
                    isinstance(node.func, ast.Attribute):
                self.assertNotIn(node.func.attr, writes,
                                 ast.dump(node.func)[:120])
