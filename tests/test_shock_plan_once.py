"""One shock plan per shock (2026-10-03).

The operator's Telegram, on the night of 2026-10-02: "⚠ Shock plan
proposed — equity −3.1% in 24h; shock hold until 10-04 00:05 (plan #41);
25 pool(s) to de-risk" — "this message keeps popping up". The sync's
shock trigger (bot_program.tasks._shock_trigger) read the 24 h drop as a
shock for the whole day it stayed in the window, and its hourly cooldown
let it propose a NEW plan, and say so again, every hour while the first
sat unanswered on /shares/.

A shock plan still PROPOSED inside the hold is the answer already given:
nothing new is proposed and nothing is said again. A plan the admin
applied, rejected or that expired no longer holds the door.

Run with:  python manage.py test tests.test_shock_plan_once
"""
from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from bot_program import share_allocator, tasks
from bot_program.share_models import SharePlan


def _plan(user, state=SharePlan.STATE_PROPOSED, hours_ago=2,
          mode=SharePlan.MODE_SHOCK):
    plan = SharePlan.objects.create(
        user=user, mode=mode, state=state,
        mode_reasons=["equity −3.1% in 24h"], targets={"a": 0.1},
        current_shares={"a": 0.2})
    SharePlan.objects.filter(pk=plan.pk).update(
        proposed_at=timezone.now() - timedelta(hours=hours_ago))
    return plan


class OneShockPlanTests(TestCase):

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.user = get_user_model().objects.create_user("shock_u",
                                                          password="x")
        self.now = timezone.now()

    def _fire(self):
        proposed = mock.MagicMock(pk=42, current_shares={"a": 0.2},
                                  targets={"a": 0.1},
                                  mode_reasons=["equity −3.1% in 24h"])
        with mock.patch("core.platform_control.is_component_enabled",
                        return_value=True), \
                mock.patch.object(share_allocator, "shock_detected",
                                  return_value=True), \
                mock.patch.object(share_allocator,
                                  "propose_share_plan_with_reason",
                                  return_value=(proposed, "")) as propose, \
                mock.patch("bot_program.notifications.notify_staff") as say:
            tasks._shock_trigger(self.user, self.now)
        return propose, say

    def test_a_pending_shock_plan_holds_the_door(self):
        _plan(self.user)
        propose, say = self._fire()
        propose.assert_not_called()
        say.assert_not_called()

    def test_an_answered_plan_does_not(self):
        _plan(self.user, state=SharePlan.STATE_APPLIED)
        propose, say = self._fire()
        propose.assert_called_once()
        say.assert_called_once()
        self.assertIn("1 pool(s) to de-risk", say.call_args.kwargs["body"])

    def test_a_plan_past_the_hold_does_not(self):
        _plan(self.user, hours_ago=share_allocator.SHOCK_HOLD_HOURS + 1)
        propose, _say = self._fire()
        propose.assert_called_once()

    def test_a_normal_plan_or_another_user_s_does_not(self):
        _plan(self.user, mode=SharePlan.MODE_NORMAL)
        other = get_user_model().objects.create_user("shock_o", password="x")
        _plan(other)
        propose, _say = self._fire()
        propose.assert_called_once()
