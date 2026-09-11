"""The rule actuator's buttons as a command, plus the one the page lacks.

`actuator apply|reject|rollback ID` goes through the same functions the
admin page's buttons call: live mode required to apply, daily caps,
snapshot for rollback. `actuator reject --stale` is the button the page
does not have: the decay investigation re-proposes the same enforcement
every day it still holds, so one finding shows up as six "pause" rows;
--stale rejects every proposal a newer one on the same rule and action
supersedes.

Run with:  python manage.py test tests.test_actuator_command
"""
from datetime import timedelta
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command
from django.test import TestCase
from django.utils import timezone

User = get_user_model()


def _run(*args, **kw):
    out = StringIO()
    call_command(*args, stdout=out, **kw)
    return out.getvalue()


def _live(enabled):
    from core.platform_control import PlatformComponent, seed_components
    seed_components()
    c = PlatformComponent.objects.get(key="actuator_mode_live")
    c.is_enabled = enabled
    c.save()


def _proposal(rule, action, *, days_ago=0, rationale="decay"):
    from signals.models import RuleAction
    row = RuleAction.objects.create(rule_name=rule, action=action,
                                    rationale=rationale)
    if days_ago:
        RuleAction.objects.filter(pk=row.pk).update(
            proposed_at=timezone.now() - timedelta(days=days_ago))
        row.refresh_from_db()
    return row


class ActuatorCommandTests(TestCase):

    def setUp(self):
        _live(True)
        self.old = _proposal("macd_bullish_crossover", "pause_rule", days_ago=5)
        self.mid = _proposal("macd_bullish_crossover", "pause_rule", days_ago=2)
        self.new = _proposal("macd_bullish_crossover", "pause_rule",
                             rationale="recent expectancy -0.0269 vs 0.2581")
        self.red_old = _proposal("bollinger_squeeze_breakout", "reduce_size",
                                 days_ago=3)
        self.red_new = _proposal("bollinger_squeeze_breakout", "reduce_size")

    def test_list_marks_the_stale_duplicates(self):
        out = _run("actuator", "list")
        self.assertIn("LIVE (apply allowed)", out)
        self.assertIn("PROPOSED (5)", out)
        self.assertIn("recent expectancy -0.0269", out)
        stale_lines = [l for l in out.splitlines() if "stale" in l]
        self.assertEqual(len(stale_lines), 3)
        self.assertTrue(any(f"#{self.old.id} " in l for l in stale_lines))
        self.assertFalse(any(f"#{self.new.id} " in l for l in stale_lines))

    def test_apply_is_the_pages_apply(self):
        from signals.models import RuleAction, RuleControl
        from signals.rule_actuator import is_rule_active, rule_size_multiplier
        out = _run("actuator", "apply", str(self.new.id), str(self.red_new.id))
        self.assertIn(f"#{self.new.id} pause_rule macd_bullish_crossover: APPLIED", out)
        self.assertIn("weight 0 for 30 days", out)
        self.assertIn("weight ×0.5", out)
        self.assertFalse(is_rule_active("macd_bullish_crossover"))
        self.assertEqual(rule_size_multiplier("bollinger_squeeze_breakout"), 0.5)
        self.new.refresh_from_db()
        self.assertEqual(self.new.state, RuleAction.STATE_APPLIED)
        self.assertEqual(RuleControl.objects.get(
            rule_name="macd_bullish_crossover").status, "paused")

    def test_shadow_mode_refuses_with_the_reason(self):
        _live(False)
        out = _run("actuator", "apply", str(self.new.id))
        self.assertIn("shadow mode", out)
        self.new.refresh_from_db()
        self.assertEqual(self.new.state, "proposed")
        self.assertIn("SHADOW (apply disabled)", _run("actuator", "list"))

    def test_reject_stale_keeps_the_newest_per_rule_and_action(self):
        from signals.models import RuleAction
        out = _run("actuator", "reject", stale=True)
        for row in (self.old, self.mid, self.red_old):
            self.assertIn(f"#{row.id} ", out)
            row.refresh_from_db()
            self.assertEqual(row.state, RuleAction.STATE_REJECTED)
        for row in (self.new, self.red_new):
            row.refresh_from_db()
            self.assertEqual(row.state, RuleAction.STATE_PROPOSED)
        self.assertIn("no stale proposals", _run("actuator", "reject", stale=True))

    def test_a_pause_the_page_applied_makes_the_older_proposal_stale(self):
        """2026-09-11: the page applied #11 (pause macd); `actuator apply
        9` then paused the same rule again. Now: #9 is stale, and apply
        refuses it with the reason."""
        from signals.models import RuleAction
        from signals.rule_actuator import apply_action
        apply_action(self.new.id, None)            # the page's click
        out = _run("actuator", "list")
        self.assertIn(f"#{self.mid.id}", out)
        self.assertIn("rule already paused", out)
        out = _run("actuator", "apply", str(self.mid.id))
        self.assertIn("already paused", out)
        self.assertIn("nothing to apply", out)
        self.mid.refresh_from_db()
        self.assertEqual(self.mid.state, RuleAction.STATE_PROPOSED)
        # And a reduction on a paused rule is moot too.
        moot = _proposal("macd_bullish_crossover", "reduce_size")
        out = _run("actuator", "reject", stale=True)
        for row in (self.old, self.mid, moot):
            self.assertIn(f"#{row.id} ", out)
            row.refresh_from_db()
            self.assertEqual(row.state, RuleAction.STATE_REJECTED)

    def test_an_expired_pause_is_not_in_effect(self):
        from signals.models import RuleControl
        RuleControl.objects.create(
            rule_name="macd_bullish_crossover", status="paused",
            weight_multiplier=0.0,
            paused_until=timezone.now() - timedelta(days=1))
        out = _run("actuator", "apply", str(self.new.id))
        self.assertIn("APPLIED", out)

    def test_rollback_restores_the_rule(self):
        from signals.rule_actuator import is_rule_active
        _run("actuator", "apply", str(self.new.id))
        self.assertFalse(is_rule_active("macd_bullish_crossover"))
        out = _run("actuator", "rollback", str(self.new.id))
        self.assertIn("ROLLED BACK", out)
        self.assertTrue(is_rule_active("macd_bullish_crossover"))

    def test_by_records_the_admin_and_errors_are_plain(self):
        User.objects.create_user("ops", password="x", is_superuser=True)
        _run("actuator", "reject", str(self.old.id), by="ops")
        self.old.refresh_from_db()
        self.assertEqual(self.old.confirmed_by.username, "ops")
        out = _run("actuator", "apply", str(self.old.id))
        self.assertIn("cannot apply", out)
        self.assertIn("not found", _run("actuator", "apply", "999999"))
        with self.assertRaises(CommandError):
            _run("actuator", "apply")
        with self.assertRaises(CommandError):
            _run("actuator", "reject", str(self.mid.id), by="nobody")
