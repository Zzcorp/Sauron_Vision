"""Daily LLM spend ceiling.

The brain's scheduled agents are the largest recurring variable cost in
the platform and the least validated component. These assert the ceiling
is real and that guarding the tasks did not unregister them from Celery.

Run with:  python manage.py test tests.test_ai_spend
"""
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone


def _task(cost, agent="news_analyst"):
    from ai_agents.models import AgentTask
    return AgentTask.objects.create(
        agent=agent, provider="claude", model="claude-opus-5",
        prompt_summary="p", cost_usd=Decimal(str(cost)), success=True)


class BudgetTests(TestCase):
    def test_spend_is_read_from_the_real_ledger(self):
        from ai_agents.spend import spent_today
        _task(0.25)
        _task(0.75)
        self.assertAlmostEqual(spent_today(), 1.0, places=4)

    def test_yesterdays_spend_does_not_count(self):
        from datetime import timedelta
        from ai_agents.models import AgentTask
        from ai_agents.spend import spent_today
        t = _task(5.0)
        AgentTask.objects.filter(pk=t.pk).update(
            created_at=timezone.now() - timedelta(days=1))
        self.assertAlmostEqual(spent_today(), 0.0, places=4)

    @override_settings(AI_CONFIG={"daily_budget_usd": 1.0, "models": {},
                                   "default_provider": "claude"})
    def test_calls_are_blocked_once_the_budget_is_spent(self):
        from ai_agents.spend import can_spend
        _task(1.10)
        allowed, reason = can_spend(tier="balanced")
        self.assertFalse(allowed)
        self.assertIn("daily AI budget spent", reason)

    @override_settings(AI_CONFIG={"daily_budget_usd": 1.0, "models": {},
                                   "default_provider": "claude"})
    def test_deep_tier_is_capped_below_the_full_budget(self):
        """Cheap operational agents must still run late in the day."""
        from ai_agents.spend import can_spend
        _task(0.80)  # past the 70% deep-tier reserve, under the full budget
        deep_allowed, _ = can_spend(tier="deep")
        fast_allowed, _ = can_spend(tier="fast", estimated_usd=0.01)
        self.assertFalse(deep_allowed)
        self.assertTrue(fast_allowed)

    @override_settings(AI_CONFIG={"daily_budget_usd": 0, "models": {},
                                   "default_provider": "claude"})
    def test_zero_budget_disables_the_ceiling(self):
        from ai_agents.spend import can_spend
        _task(999)
        allowed, _ = can_spend(tier="deep")
        self.assertTrue(allowed)


class GuardedTaskTests(TestCase):
    @override_settings(AI_CONFIG={"daily_budget_usd": 1.0, "models": {},
                                   "default_provider": "claude"})
    def test_guarded_brain_task_skips_cleanly_when_broke(self):
        from brain.tasks import run_sauron_mind
        _task(2.0)
        result = run_sauron_mind()
        self.assertEqual(result["status"], "skipped")
        self.assertIn("budget", result["reason"])

    def test_guarding_did_not_unregister_the_tasks(self):
        """@spend_guard above @shared_task would leave a plain function and
        beat would enqueue a task no worker knows."""
        from config.celery import app
        app.loader.import_default_modules()
        app.finalize()
        registered = set(app.tasks)
        for name in ("brain.tasks.run_sauron_mind",
                     "brain.tasks.run_critic_pass",
                     "brain.tasks.run_strategist",
                     "brain.tasks.run_strategy_generator",
                     "brain.tasks.run_earnings_reviewer"):
            self.assertIn(name, registered)

    def test_brain_cadences_were_reduced(self):
        from config.celery import app
        schedule = app.conf.beat_schedule
        self.assertGreaterEqual(schedule["sauron-mind-synthesize"]["schedule"], 3600)
        self.assertGreaterEqual(schedule["sauron-critic-pass"]["schedule"], 7200)
