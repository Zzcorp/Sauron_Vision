"""One parser for `{parent}_evolved_v{N}`, and the sites that must use it.

`signals.evolution.apply_evolution` mints a fork by appending `_evolved_v{N}`
to its parent's name and forks the RuleControl row ONLY — schema, evaluator
and OpportunitySetup all stay with the parent. Three readers therefore take
the name apart again, and each carried its own copy of the same regex:

  - `signals.promotion_evidence._evaluator_name` (the walk-forward gate: a
    fork that fails to resolve is not backtested at all, and reaches a LIVE
    stage through the fail-open path),
  - `dashboard.views._promotion_ladder` (which setup defines this fork),
  - `dashboard.views_evolution._registry_rows` (which family it belongs to).

They agreed, so nothing rendered wrongly — the cost was that two of those
docstrings ASSERTED the agreement while nothing enforced it. `core.fork_names`
is the enforcement, and these tests are what makes a fourth copy fail.

Run with:  python manage.py test tests.test_fork_names
"""
import pathlib

from django.test import SimpleTestCase


class ParserTests(SimpleTestCase):
    def test_a_fork_resolves_to_its_parent(self):
        from core.fork_names import base_family, fork_parent, is_fork
        self.assertEqual(base_family("golden_cross_evolved_v3"), "golden_cross")
        self.assertEqual(fork_parent("golden_cross_evolved_v3"), "golden_cross")
        self.assertTrue(is_fork("golden_cross_evolved_v3"))

    def test_an_original_is_left_alone(self):
        """`base_family` returns the name (one lookup key either way);
        `fork_parent` returns "" (a card must not claim every rule is a fork).
        That difference is the whole reason both exist."""
        from core.fork_names import base_family, fork_parent, is_fork
        self.assertEqual(base_family("golden_cross"), "golden_cross")
        self.assertEqual(fork_parent("golden_cross"), "")
        self.assertFalse(is_fork("golden_cross"))

    def test_the_peel_is_one_level_deep(self):
        """A fork of a fork resolves to its IMMEDIATE parent. Callers that
        want the root walk it in a bounded loop (`_promotion_ladder` does),
        and the evidence gate deliberately does not — matching the copy it
        replaces, character for character."""
        from core.fork_names import base_family
        self.assertEqual(base_family("a_evolved_v1_evolved_v2"), "a_evolved_v1")

    def test_a_name_that_only_looks_like_a_fork_is_not_one(self):
        from core.fork_names import fork_parent
        for name in ("x_evolved_v", "evolved_v2", "x_evolved_v2_tail"):
            with self.subTest(name=name):
                self.assertEqual(fork_parent(name), "")

    def test_empty_and_none_are_not_forks(self):
        """Every call site passes a CharField that may be blank."""
        from core.fork_names import base_family, fork_parent
        for name in ("", None):
            with self.subTest(name=name):
                self.assertEqual(base_family(name), "")
                self.assertEqual(fork_parent(name), "")

    def test_the_name_it_mints_is_the_name_it_parses(self):
        from core.fork_names import fork_name, fork_parent
        minted = fork_name("golden_cross", 3)
        self.assertEqual(minted, "golden_cross_evolved_v3")
        self.assertEqual(fork_parent(minted), "golden_cross")


class OneParserTests(SimpleTestCase):
    """The duplication itself, asserted away."""

    def test_the_dashboard_pages_hold_no_private_copy_of_the_regex(self):
        for path in ("dashboard/views.py", "dashboard/views_evolution.py"):
            with self.subTest(module=path):
                src = pathlib.Path(path).read_text(encoding="utf-8")
                self.assertNotIn(r"_evolved_v\d+", src,
                                 "this module parses fork names again itself "
                                 "— import core.fork_names instead")

    def test_both_pages_use_the_shared_functions_themselves(self):
        """Not a lookalike with the same name: the identical object."""
        from core import fork_names
        from dashboard import views, views_evolution
        self.assertIs(views.fork_parent, fork_names.fork_parent)
        self.assertIs(views_evolution.base_family, fork_names.base_family)

    def test_the_live_fork_counter_reads_the_shared_infix(self):
        """dashboard/views.py counts forks with a LIKE. It is the loose form
        of the parser on purpose, but it must not be a second hard-coded copy
        of the naming scheme."""
        from core.fork_names import FORK_INFIX
        src = pathlib.Path("dashboard/views.py").read_text(encoding="utf-8")
        self.assertIn("rule_name__contains=FORK_INFIX", src)
        self.assertEqual(FORK_INFIX, "_evolved_v")

    def test_the_evidence_gate_resolves_a_fork_the_same_way(self):
        """`signals.promotion_evidence._evaluator_name` still carries its own
        copy (signals/ is owned elsewhere in this wave — its body becomes
        `return base_family(rule_name)`). Until it adopts the module, this is
        what keeps the two from drifting: they must agree on every shape.

        The stake is not cosmetic. If the gate resolved a fork differently
        from the pages, a fork would be backtested against one evaluator and
        described on screen as a child of another.
        """
        from core.fork_names import base_family
        from signals.promotion_evidence import _evaluator_name
        for name in ("golden_cross", "golden_cross_evolved_v3",
                     "a_evolved_v1_evolved_v2", "x_evolved_v", "", None,
                     "rsi_divergence_evolved_v10"):
            with self.subTest(name=name):
                self.assertEqual(_evaluator_name(name), base_family(name))

    def test_the_constructor_still_writes_what_this_parses(self):
        """`signals.evolution.apply_evolution` owns the format. If that line
        changes, the parser has to change with it — and this is where the two
        are read in the same breath."""
        from core.fork_names import fork_name
        src = pathlib.Path("signals/evolution.py").read_text(encoding="utf-8")
        self.assertIn('_evolved_v{n}', src,
                      "the fork constructor moved — point it at "
                      "core.fork_names.fork_name")
        self.assertEqual(fork_name("p", 1), "p_evolved_v1")
