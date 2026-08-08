"""Phase-31 strategy starter-pack tests:
  - seed_setups creates 6 OpportunitySetup rows + 6 RuleControl rows
  - re-running is idempotent (no duplicates, counts as update)
  - --activate flag flips is_active to True
  - --reset cleans up only seeded rows
  - all conditions reference registered evaluator kinds
  - all referenced evaluator kinds are present in EVALUATOR_REGISTRY
  - command CLI invokes the right path

Run with:  python manage.py test tests.test_phase31_strategy_seed
"""
from io import StringIO

from django.core.management import call_command
from django.test import TestCase


class SeedSetupsTests(TestCase):
    def test_seeds_six_starter_strategies(self):
        from signals.management.commands.seed_strategies import seed_setups
        from signals.models_opportunity import OpportunitySetup
        from signals.models_control import RuleControl

        r = seed_setups()
        self.assertEqual(r["created"], 6)
        self.assertEqual(r["updated"], 0)
        self.assertEqual(r["rules_created"], 6)
        self.assertEqual(r["total"], 6)
        self.assertEqual(OpportunitySetup.objects.filter(
            name__startswith="starter_").count(), 6)
        self.assertEqual(RuleControl.objects.filter(
            rule_name__startswith="starter_").count(), 6)

    def test_idempotent_reseed(self):
        from signals.management.commands.seed_strategies import seed_setups
        from signals.models_opportunity import OpportunitySetup

        seed_setups()
        r = seed_setups()
        # Second pass: zero created, all updated.
        self.assertEqual(r["created"], 0)
        self.assertEqual(r["updated"], 6)
        # Still six rows total.
        self.assertEqual(OpportunitySetup.objects.filter(
            name__startswith="starter_").count(), 6)

    def test_activate_flag_sets_is_active_true(self):
        from signals.management.commands.seed_strategies import seed_setups
        from signals.models_opportunity import OpportunitySetup

        seed_setups(activate=False)
        self.assertFalse(OpportunitySetup.objects
                          .filter(name="starter_stock_momentum").first().is_active)
        seed_setups(activate=True)
        self.assertTrue(OpportunitySetup.objects
                         .filter(name="starter_stock_momentum").first().is_active)

    def test_reset_removes_only_seeded_setups(self):
        from signals.management.commands.seed_strategies import (
            seed_setups, reset_setups,
        )
        from signals.models_opportunity import OpportunitySetup
        from signals.models_control import RuleControl

        # Pre-existing user-created setup that must NOT be touched.
        OpportunitySetup.objects.create(
            name="my_custom_strategy", description="user setup",
            direction="bullish", asset_classes=["stock"],
            conditions=[], min_match_score=0.5,
        )
        RuleControl.objects.create(rule_name="my_custom_strategy")
        seed_setups()
        r = reset_setups()
        self.assertEqual(r["setups_deleted"], 6)
        self.assertEqual(r["rules_deleted"], 6)
        # User setup survives.
        self.assertTrue(OpportunitySetup.objects.filter(
            name="my_custom_strategy").exists())
        self.assertTrue(RuleControl.objects.filter(
            rule_name="my_custom_strategy").exists())


class SeedConditionValidityTests(TestCase):
    """Every condition in every starter setup must reference a registered
    evaluator kind. Otherwise the scanner would silently skip the condition."""

    def test_all_evaluator_kinds_registered(self):
        from signals.management.commands.seed_strategies import _setup_definitions
        from signals.opportunity_scanner import EVALUATOR_REGISTRY

        for spec in _setup_definitions():
            for cond in spec["conditions"]:
                kind = cond.get("kind")
                self.assertIn(
                    kind, EVALUATOR_REGISTRY,
                    msg=(f"Setup {spec['name']!r} references unknown "
                         f"evaluator {kind!r}"),
                )

    def test_all_setups_have_conditions(self):
        from signals.management.commands.seed_strategies import _setup_definitions
        for spec in _setup_definitions():
            self.assertGreater(
                len(spec["conditions"]), 0,
                msg=f"Setup {spec['name']!r} has no conditions",
            )

    def test_all_setups_have_distinct_names(self):
        from signals.management.commands.seed_strategies import _setup_definitions
        names = [s["name"] for s in _setup_definitions()]
        self.assertEqual(len(names), len(set(names)))

    def test_all_setup_names_use_seed_prefix(self):
        from signals.management.commands.seed_strategies import (
            _setup_definitions, SEED_PREFIX,
        )
        for spec in _setup_definitions():
            self.assertTrue(spec["name"].startswith(SEED_PREFIX))


class CommandLineTests(TestCase):
    def test_command_runs_default(self):
        from signals.models_opportunity import OpportunitySetup
        out = StringIO()
        call_command("seed_strategies", stdout=out)
        self.assertEqual(OpportunitySetup.objects.filter(
            name__startswith="starter_").count(), 6)
        self.assertIn("Seeded 6 starter strategies", out.getvalue())

    def test_command_activate_flag(self):
        from signals.models_opportunity import OpportunitySetup
        out = StringIO()
        call_command("seed_strategies", "--activate", stdout=out)
        active_count = OpportunitySetup.objects.filter(
            name__startswith="starter_", is_active=True).count()
        self.assertEqual(active_count, 6)

    def test_command_reset_flag(self):
        from signals.models_opportunity import OpportunitySetup
        call_command("seed_strategies")  # seed first
        out = StringIO()
        call_command("seed_strategies", "--reset", stdout=out)
        self.assertEqual(OpportunitySetup.objects.filter(
            name__startswith="starter_").count(), 0)
        self.assertIn("Reset done", out.getvalue())
