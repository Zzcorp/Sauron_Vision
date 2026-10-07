"""THE SWEEP (2026-10-07): a name that does not exist is a branch that never
runs, and every one found so far failed quietly.

  the clock      django.utils.timezone.utc left Django in 5.0 (this install
                 runs 5.2). venue_health printed "?" for every time in the
                 eToro sick alert, and thesis_check.care_stop raised into
                 position_care.care()'s except, which skips the row's whole
                 care plan. No project file may read it again.
  the rules      sentiment_velocity_spike and earnings_surprise imported
                 scraping.models.SocialPost and .EarningsEvent, models that
                 never existed, inside `except: return None`: every signal
                 pass "scanned" them and /evolution/ listed them as families
                 the engine runs. Both are gone from the engine, and every
                 import in a rule module must name something real.
  the VaR        RiskEngine._parametric_var imported scipy, which is not in
                 requirements.txt: /api/risk/?action=var&method=parametric
                 answered a 500 once the book had positions and 30 returns.

Run with:  python manage.py test tests.test_dead_names
"""
import ast
import importlib
import importlib.util
import os
import sys
from pathlib import Path
from unittest.mock import patch

import numpy as np
from django.conf import settings
from django.test import SimpleTestCase, TestCase

REMOVED_RULES = ("sentiment_velocity_spike", "earnings_surprise")
# Copies of the tree that are not the tree, and trees with no project code.
# SV_V is skipped for the same reason by tests/test_calendar_truth.py and
# tests/test_tier345_truth.py.
SKIP_DIRS = {"venv", ".venv", ".claude", "node_modules", ".git", "staticfiles",
             "static", "frontend", "test_backups", "SV_V", "__pycache__",
             "media", "logs"}


def _project_files():
    """Every .py under BASE_DIR, pruning the skipped trees before they are
    walked (a checkout's venv/ and .claude/worktrees/ hold tens of
    thousands of files that are not ours)."""
    root = Path(settings.BASE_DIR)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            if name.endswith(".py"):
                yield root, Path(dirpath) / name


def _django_utc_reads(source: str):
    """(line, spelling) for every read of django.utils.timezone.utc, under
    whatever name the file binds the module to. Scope-blind on purpose: a
    file that binds `timezone` to Django's module anywhere is flagged for
    every `timezone.utc` in it, so a file that needs both spells the
    stdlib one `dt_timezone` (bot_program/withdrawals.py:68)."""
    tree = ast.parse(source)
    bound = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "django.utils":
            bound |= {a.asname or "timezone" for a in node.names
                      if a.name == "timezone"}
        elif isinstance(node, ast.ImportFrom) and node.module == "django.utils.timezone":
            for a in node.names:
                if a.name == "utc":
                    yield node.lineno, "from django.utils.timezone import utc"
        elif isinstance(node, ast.Import):
            bound |= {a.asname for a in node.names
                      if a.name == "django.utils.timezone" and a.asname}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Attribute) and node.attr == "utc"):
            continue
        v = node.value
        if isinstance(v, ast.Name) and v.id in bound:
            yield node.lineno, f"{v.id}.utc"
        elif ast.unparse(v) == "django.utils.timezone":
            yield node.lineno, "django.utils.timezone.utc"


def _is_submodule(module: str, name: str) -> bool:
    try:
        return importlib.util.find_spec(f"{module}.{name}") is not None
    except (ImportError, ValueError):      # `module` is not a package
        return False


def _missing_imports(path: Path) -> list:
    """Every `import X` and absolute `from X import Y` in one file, at any
    depth, that names nothing real."""
    missing = []
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                try:
                    found = importlib.util.find_spec(alias.name) is not None
                except (ImportError, ValueError):
                    found = False
                if not found:
                    missing.append(f"{path.name}:{node.lineno} import {alias.name}")
            continue
        if not isinstance(node, ast.ImportFrom) or node.level:
            continue
        try:
            module = importlib.import_module(node.module)
        except ImportError:
            missing.append(f"{path.name}:{node.lineno} from {node.module} "
                           f"(no such module)")
            continue
        for alias in node.names:
            if alias.name == "*" or hasattr(module, alias.name):
                continue
            if _is_submodule(node.module, alias.name):
                continue
            missing.append(f"{path.name}:{node.lineno} from "
                           f"{node.module} import {alias.name}")
    return missing


class TheClockTests(SimpleTestCase):

    def test_no_project_file_reads_django_timezone_utc(self):
        hits = []
        for root, path in _project_files():
            text = path.read_text(encoding="utf-8", errors="replace")
            if "utc" not in text or "django" not in text:
                continue
            for line, spelling in _django_utc_reads(text):
                hits.append(f"{path.relative_to(root)}:{line} {spelling}")
        self.assertEqual(hits, [], "use datetime.timezone.utc")

    def test_the_guard_sees_every_spelling(self):
        src = ("from django.utils import timezone\n"
               "from django.utils import timezone as dj\n"
               "import django.utils.timezone as djtz\n"
               "from django.utils.timezone import utc\n"
               "from datetime import timezone as dt_timezone\n"
               "a = timezone.utc\nb = dj.utc\nc = djtz.utc\n"
               "d = django.utils.timezone.utc\ne = dt_timezone.utc\n")
        self.assertEqual([s for _l, s in _django_utc_reads(src)],
                         ["from django.utils.timezone import utc",
                          "timezone.utc", "dj.utc", "djtz.utc",
                          "django.utils.timezone.utc"])


class TheRuleSourceTests(TestCase):

    def test_every_import_in_a_rule_module_names_something_real(self):
        rules_dir = Path(settings.BASE_DIR) / "signals" / "rules"
        missing = []
        for path in sorted(rules_dir.glob("*.py")):
            missing += _missing_imports(path)
        self.assertEqual(missing, [])

    def test_the_import_check_sees_a_missing_name_and_a_missing_module(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "probe_rules.py"
            p.write_text("def f():\n"
                         "    from scraping.models import NoSuchModel\n"
                         "    from scraping.no_such_module import X\n"
                         "    import no_such_top_level_module\n"
                         "    from scraping.models import SentimentSnapshot\n",
                         encoding="utf-8")
            self.assertEqual(_missing_imports(p), [
                "probe_rules.py:2 from scraping.models import NoSuchModel",
                "probe_rules.py:3 from scraping.no_such_module (no such module)",
                "probe_rules.py:4 import no_such_top_level_module"])

    def test_the_engine_loads_no_rule_without_a_source(self):
        from signals.engine import SignalEngine
        names = {r.name for r in SignalEngine().rules}
        for name in REMOVED_RULES:
            self.assertNotIn(name, names)
        for module in ("signals.rules.sentiment_rules",
                       "signals.rules.fundamental_rules"):
            self.assertIsNone(importlib.util.find_spec(module))

    def test_the_evolution_registry_lists_only_what_the_engine_runs(self):
        """/evolution/ calls its list 'every rule family the engine actually
        runs' (dashboard/views_evolution.py _registry_rows). The anchors are
        names only the engine supplies (no schema, no RuleControl row here),
        so a SignalEngine that failed to build, which the view swallows,
        fails this test instead of passing it."""
        from dashboard.views_evolution import _registry_rows
        from signals.evolution import SCHEMA_REGISTRY, _ensure_rules_registered
        from signals.models import RuleControl
        _ensure_rules_registered()
        self.assertFalse(RuleControl.objects.exists())
        names = {r["rule_name"] for r in _registry_rows(SCHEMA_REGISTRY)}
        for name in REMOVED_RULES:
            self.assertNotIn(name, names)
        for engine_only in ("macd_bullish_crossover", "smc_composite"):
            self.assertNotIn(engine_only, SCHEMA_REGISTRY)
            self.assertIn(engine_only, names)


class TheParametricVarTests(SimpleTestCase):

    def test_the_parametric_var_needs_no_scipy(self):
        from portfolio.risk_engine import RiskEngine
        returns = [0.01, -0.02, 0.015, -0.005, 0.0] * 10
        mean, std = float(np.mean(returns)), float(np.std(returns))
        z95 = -1.6448536269514722          # scipy.stats.norm.ppf(1 - 0.95)
        with patch.dict(sys.modules, {"scipy": None, "scipy.stats": None}):
            one = RiskEngine(None)._parametric_var(returns, 0.95, 1)
            four = RiskEngine(None)._parametric_var(returns, 0.95, 4)
        self.assertAlmostEqual(one, mean + z95 * std, places=12)
        self.assertAlmostEqual(four, 2 * (mean + z95 * std), places=12)
