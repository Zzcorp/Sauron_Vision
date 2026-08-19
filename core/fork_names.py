"""The `{parent}_evolved_v{N}` fork-name scheme — one parser, one format.

`signals.evolution.apply_evolution` mints a fork by appending `_evolved_v{N}`
to its parent's rule name, and forks the `RuleControl` row ONLY: the schema,
the evaluator and the `OpportunitySetup` holding the conditions all still
belong to the parent. So every reader that wants a fork's schema, evaluator or
definition has to take the name apart again, and three of them did it with a
private copy of the same regex:

  - `signals.promotion_evidence._evaluator_name` — resolves a fork to the
    parent's evaluator before the walk-forward gate will backtest it,
  - `dashboard.views._promotion_ladder` — walks a fork up to the parent whose
    `OpportunitySetup` defines it,
  - `dashboard.views_evolution._registry_rows` — groups a fork under its
    parent family instead of listing it as its own un-evolvable one.

All three agreed, so nothing rendered wrongly; the cost is that renaming the
scheme means finding call sites that do not reference each other, while two of
those docstrings assert an agreement that nothing enforced. This module is the
enforcement.

It lives in `core` and imports nothing but `re` on purpose. `signals` owns the
format, but `dashboard` must not import a `signals` private for a string
operation, and `core` is the one layer both already sit above — importing it
costs no model, no app registry and no query.

NOT YET ADOPTED BY: `signals.promotion_evidence._evaluator_name`, which still
carries a byte-identical private copy (`signals/` is owned by another hand in
this wave). Its body becomes `return base_family(rule_name)` — the semantics
here are that copy's, character for character, including the one-level peel.
"""
import re

# The infix `signals.evolution.apply_evolution` writes, exported so that a
# cheap DB prefilter (`rule_name__contains=FORK_INFIX`, dashboard/views.py's
# live-fork counter) and the parser below cannot drift apart.
FORK_INFIX = "_evolved_v"

# Anchored at the end, so it peels exactly ONE level per call: a fork of a fork
# (`a_evolved_v1_evolved_v2`) resolves to `a_evolved_v1`, its immediate parent,
# not to `a`. Callers that want the root walk it in a bounded loop.
_FORK_SUFFIX_RE = re.compile(re.escape(FORK_INFIX) + r"\d+$")


def fork_name(parent_rule: str, n: int) -> str:
    """The name the Nth fork of `parent_rule` gets."""
    return "{}{}{}".format(parent_rule, FORK_INFIX, n)


def base_family(rule_name: str) -> str:
    """`golden_cross_evolved_v3` → `golden_cross`; anything else unchanged.

    Returns the name itself for an original, which is what a caller looking up
    a schema or an evaluator wants: one lookup key either way.
    """
    return _FORK_SUFFIX_RE.sub("", rule_name or "")


def fork_parent(rule_name: str) -> str:
    """The rule this one was forked from, or "" when it is an original.

    The `""` is the distinction `base_family` deliberately does not draw: a
    card that says "FORK OF x" must not say it about every rule on the page.
    """
    name = rule_name or ""
    parent = base_family(name)
    return parent if parent != name else ""


def is_fork(rule_name: str) -> bool:
    """True for a name evolution minted, False for one a human or seeder did."""
    return bool(fork_parent(rule_name))
