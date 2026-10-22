"""SOURCE PINS FOR O1b (spec §11, hard rules 1 and 2): the arms, the menu,
the gaps, the playbook, the predicates, the grade and the tribunal reach
no order path, no stop mover, no row writer and no model.

Run with:  python manage.py test tests.orcs.test_orc_source_pins_o1b
"""
import ast
import importlib
import inspect

from django.test import SimpleTestCase

MODULES = ("pricing", "bars", "menu", "gaps", "playbook", "predicates",
           "ghost", "grading", "tribunal", "tasks")
FORBIDDEN = {"_close_trade", "execute_entry", "client_for_symbol",
             "modify_protective", "_move_broker_stop", "apply_breakeven",
             "update_trailing_stop", "_write_stamp", "_commit",
             "_save_care", "_scale_out_paper", "dispatch_notification",
             "notify_staff"}
WRITES = {"save", "update", "create", "delete", "bulk_update",
          "bulk_create", "update_or_create", "get_or_create",
          "select_for_update"}


def _tree(name):
    mod = importlib.import_module(f"bot_program.orcs.{name}")
    return ast.parse(inspect.getsource(mod))


def _identifiers(tree):
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            out.add(node.id)
        elif isinstance(node, ast.Attribute):
            out.add(node.attr)
        elif isinstance(node, ast.ImportFrom):
            out.add(node.module or "")
            out.update(a.name for a in node.names)
        elif isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
    return out


def _chain(node):
    """The dotted names of an attribute chain, outermost last."""
    parts = []
    while isinstance(node, (ast.Attribute, ast.Call)):
        if isinstance(node, ast.Call):
            node = node.func
            continue
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return list(reversed(parts))


class ThePinsTests(SimpleTestCase):

    def test_no_order_path_no_stop_mover_no_model(self):
        for name in MODULES:
            ids = _identifiers(_tree(name))
            with self.subTest(module=name):
                self.assertFalse(ids & FORBIDDEN, ids & FORBIDDEN)
                self.assertFalse([i for i in ids
                                  if i.startswith("ai_agents")])
                self.assertFalse([i for i in ids if "anthropic" in i])

    def test_never_writes_a_trade_row(self):
        for name in MODULES:
            tree = _tree(name)
            with self.subTest(module=name):
                for node in ast.walk(tree):
                    if not isinstance(node, ast.Call):
                        continue
                    chain = _chain(node.func)
                    if "AssetBotTrade" in chain:
                        self.assertFalse(set(chain) & WRITES, chain)
                # a shadow is a dataclass, never a model copy
                self.assertNotIn("refresh_from_db", _identifiers(tree))

    def test_the_care_ghost_reads_plan_and_the_trailing_arithmetic_only(self):
        ids = _identifiers(_tree("ghost"))
        self.assertIn("plan", ids)
        self.assertIn("breakeven_candidate", ids)
        self.assertIn("trail_candidate", ids)
        self.assertIn("stamp_value", ids)
        self.assertNotIn("stamp", ids & {"stamp"},
                         "the replay's stamp writer is never called")

    def test_a_bar_is_final_after_the_bar_refreshs_own_interval(self):
        """BAR_REFRESH_S is the bar refresh's beat (config/celery.py): a bar
        that just ended is a snapshot until that beat's next pass."""
        from bot_program.orcs.constants import BAR_REFRESH_S
        from config.celery import app
        self.assertEqual(
            app.conf.beat_schedule["refresh-bot-bars"]["schedule"],
            float(BAR_REFRESH_S))
