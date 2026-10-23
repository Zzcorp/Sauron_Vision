"""SOURCE PINS FOR O1c (spec §11, hard rules 1 and 2): the dossier, the
fence, the score, the weather, the wakes and the drums reach no order
path, no stop mover, no row writer, no model and no token counter (a
network call), never read a news body or `ai_summary`, and never write a
`pending` wake (dispatch is O2's).

Run with:  python manage.py test tests.orcs.test_orc_source_pins_o1c
"""
import ast
import importlib
import inspect

from django.test import SimpleTestCase

from tests.orcs.test_orc_source_pins_o1b import (FORBIDDEN, WRITES, _chain,
                                                 _identifiers)

MODULES = ("sessions", "fence", "complexity", "integrity", "weather",
           "sources", "dossier", "dossier_market", "dossier_instrument",
           "dossier_position", "wake", "drums", "drum_bus", "observe",
           "census", "tasks", "journal", "notes")
BODIES = {"ai_summary", "raw_content", "content_summary"}


def _tree(name):
    mod = importlib.import_module(f"bot_program.orcs.{name}")
    return ast.parse(inspect.getsource(mod))


class ThePinsTests(SimpleTestCase):

    def test_no_order_path_no_model_no_token_counter(self):
        for name in MODULES:
            ids = _identifiers(_tree(name))
            with self.subTest(module=name):
                self.assertFalse(ids & FORBIDDEN, ids & FORBIDDEN)
                self.assertFalse([i for i in ids if i.startswith("ai_agents")])
                self.assertFalse([i for i in ids if "anthropic" in i])
                self.assertNotIn("count_tokens", ids)

    def test_never_writes_a_trade_row(self):
        # the census's O1a restamp writes the leg stamp under the row's
        # lock by design (tests/orcs/test_orc_census.py pins it); every
        # module O1c adds or changes beside it writes no trade row
        for name in (m for m in MODULES if m != "census"):
            tree = _tree(name)
            with self.subTest(module=name):
                for node in ast.walk(tree):
                    if isinstance(node, ast.Call):
                        chain = _chain(node.func)
                        if "AssetBotTrade" in chain:
                            self.assertFalse(set(chain) & WRITES, chain)

    def test_never_reads_a_news_body_or_the_analysts_summary(self):
        for name in MODULES:
            tree = _tree(name)
            with self.subTest(module=name):
                for node in ast.walk(tree):
                    if isinstance(node, ast.Attribute):
                        self.assertNotIn(node.attr, BODIES)
                    if isinstance(node, ast.Constant):
                        self.assertNotIn(node.value, BODIES)
                    if isinstance(node, ast.keyword) and node.arg in BODIES:
                        # the one allowed use: a filter on the parser's
                        # failure sentinel, which loads no text
                        self.assertEqual(ast.unparse(node.value),
                                         "FAILED_PARSE_SUMMARY")

    def test_no_pending_wake_is_ever_written(self):
        src = inspect.getsource(importlib.import_module(
            "bot_program.orcs.wake"))
        self.assertNotIn('status="pending"', src)
        self.assertNotIn("status='pending'", src)
        self.assertIn("# O2:", src, "the dispatch seam is marked")

    def test_the_o2_seams_are_marked(self):
        for name, needle in (("integrity", "# O2:"), ("dossier_market", "# O2:"),
                             ("dossier_position", "# O2:"),
                             ("drum_bus", "# O2:"), ("fence", "# O2:")):
            src = inspect.getsource(importlib.import_module(
                f"bot_program.orcs.{name}"))
            with self.subTest(module=name):
                self.assertIn(needle, src)

    def test_the_bar_refresh_imports_no_order_path(self):
        from market_data import bot_bars, candle_headroom
        for mod in (bot_bars, candle_headroom):
            ids = _identifiers(ast.parse(inspect.getsource(mod)))
            for bad in ("_close_trade", "execute_entry", "market_order",
                        "close_position", "_move_broker_stop",
                        "modify_protective"):
                self.assertNotIn(bad, ids, (mod.__name__, bad))
