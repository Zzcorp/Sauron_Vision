"""SOURCE PINS FOR O1d (spec §11, hard rules 1 and 2): the read API, the
Telegram replies and the ranks reach no order path, no stop mover, no row
writer, no notifier and no model; the pages write only the operator's
thesis, through journal.append; the row's stamp is still read inside the
Orc package (and Morgul's G8) only.

Run with:  python manage.py test tests.orcs.test_orc_source_pins_o1d
"""
import ast
import importlib
import inspect

from django.test import SimpleTestCase

from tests.orcs import test_orc_source_pins_o1b as o1b
from tests.orcs.test_orc_switch_off import TheSourcePinTests

MODULES = ("bot_program.orcs.notes", "bot_program.orcs.surfaces",
           "bot_program.orcs.ranks")
FORBIDDEN = (TheSourcePinTests.FORBIDDEN | o1b.FORBIDDEN
             | {"_send_telegram", "send_alarm", "begin_ask",
                "answer_question", "ClaudeProvider", "complete"})
WRITES = o1b.WRITES | {"append", "remember", "merge_seen", "refresh_from_db"}


def _tree(name):
    return ast.parse(inspect.getsource(importlib.import_module(name)))


def _calls(tree):
    """The dotted chain of every call, outermost last."""
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            out.append(o1b._chain(node.func))
    return out


class TheO1dPinsTests(SimpleTestCase):

    def test_notes_surfaces_ranks_reach_no_order_path_and_no_model(self):
        for name in MODULES:
            ids = o1b._identifiers(_tree(name))
            with self.subTest(module=name):
                self.assertFalse(ids & FORBIDDEN, ids & FORBIDDEN)
                self.assertFalse([i for i in ids if i.startswith("ai_agents")])
                self.assertFalse([i for i in ids if "anthropic" in i])
                self.assertFalse([i for i in ids if "broker_router" in i])

    def test_notes_writes_nothing_but_the_card_in_memory(self):
        """notes.refresh sets orc.card in memory; journal.append saves it
        under the Orc's lock. Nothing in the read API, the replies or the
        ranks calls a writer."""
        for name in MODULES:
            with self.subTest(module=name):
                for chain in _calls(_tree(name)):
                    tail = chain[-1] if chain else ""
                    if tail in ("append",) and chain[:1] != ["journal"]:
                        continue                  # a list's append
                    if chain == ["card", "update"]:
                        continue                  # the card, in memory
                    self.assertNotIn(tail, WRITES, chain)
        src = inspect.getsource(importlib.import_module(MODULES[0]))
        self.assertIn("orc.card = card", src)

    def test_views_orcs_writes_only_through_journal_append(self):
        from dashboard import views_orcs
        tree = ast.parse(inspect.getsource(views_orcs))
        writes = [c for c in _calls(tree)
                  if c and c[-1] in (o1b.WRITES - {"update"})]
        self.assertEqual(writes, [], writes)
        appends = [c for c in _calls(tree) if c[-2:] == ["journal", "append"]]
        self.assertEqual(len(appends), 1)
        thesis = inspect.getsource(views_orcs.orc_thesis)
        self.assertIn('author="operator"', thesis)
        self.assertNotIn("fact=True", thesis)
        self.assertNotIn(".thesis =", thesis)
        self.assertIn("orcs_on()", thesis)
        # the other views only read
        for fn in (views_orcs.orcs_list, views_orcs.orc_detail,
                   views_orcs.orcs_seats):
            src = inspect.getsource(fn)
            self.assertNotIn("journal.append", src, fn.__name__)
            self.assertNotIn("from bot_program.orcs import journal", src)

    def test_the_stamp_is_read_only_inside_the_package(self):
        TheSourcePinTests(
            "test_nothing_outside_the_orcs_reads_the_stamp"
        ).test_nothing_outside_the_orcs_reads_the_stamp()
        from bot_program.orcs import notes
        self.assertIn('meta.get("orc")', inspect.getsource(notes.stamped))

    def test_the_seams_read_the_switch_from_the_batch(self):
        from dashboard import horde
        self.assertIn("orcs", horde.SWITCH_KEYS)
        src = inspect.getsource(horde)
        self.assertNotRegex(src, r"(?<![\w.])orcs_on\(")
        self.assertNotIn("switches import orcs_on", src)
        self.assertNotIn("is_component_enabled(", src)
        for fn in (horde._orc_slots, horde._captain_slots):
            body = inspect.getsource(fn)
            self.assertIn("except ImportError", body)
            self.assertIn("if not on", body)
