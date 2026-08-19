"""The Eye's rule-control pills: reduced, paused, actions/24h.

Two of the three were stuck at 0 on every install ever deployed, and the way
they got there is the reason this file exists:

  `RuleControl.objects.filter(status="active", size_multiplier__lt=1.0)`

`size_multiplier` is not a field `RuleControl` declares. Django resolves lookup
names inside `filter()`, so the FieldError was raised before `.count()` — and
the three counters shared ONE `try/except Exception: pass`. The exception took
the assignment it belonged to AND the `live_actions_24h` statement below it,
which was correct code that never ran. Two dead pills sat beside a working
`paused` pill, on a live dashboard, looking authoritative.

The predicate was wrong on both sides too: `rule_actuator.apply_action` writes
STATUS_REDUCED when it reduces a rule, and `rule_size_multiplier` honours
`weight_multiplier` only in that status — so a reduced rule is never
status="active", and renaming the field alone would still have counted zero.

Run with:  python manage.py test tests.test_eye_rule_control
"""
import logging
import pathlib
from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.core.exceptions import FieldError
from django.test import TestCase
from django.utils import timezone


def _ctrl(name, **kw):
    from signals.models_control import RuleControl
    return RuleControl.objects.create(rule_name=name, **kw)


def _action(name, *, applied_ago_hours=1):
    from signals.models_control import RuleAction
    return RuleAction.objects.create(
        rule_name=name, action=RuleAction.ACTION_REDUCE,
        state=RuleAction.STATE_APPLIED,
        applied_at=timezone.now() - timedelta(hours=applied_ago_hours))


class ReducedCounterTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("eye_rc", password="x")

    def _summary(self):
        from dashboard.views_eye import _rule_control_summary
        return _rule_control_summary(self.user)

    def test_the_model_has_no_field_called_size_multiplier(self):
        """The pin: this is what made the old filter a FieldError, not a
        query that merely matched nothing."""
        from signals.models_control import RuleControl
        names = {f.name for f in RuleControl._meta.get_fields()}
        self.assertNotIn("size_multiplier", names)
        self.assertIn("weight_multiplier", names)
        # Pin the USE, not the word: the comment that explains this fix has
        # to be able to name the field it removed.
        src = pathlib.Path("dashboard/views_eye.py").read_text(encoding="utf-8")
        for use in ("size_multiplier=", "size_multiplier__", '"size_multiplier"',
                    "'size_multiplier'"):
            with self.subTest(use=use):
                self.assertNotIn(use, src)

    def test_a_reduced_rule_is_counted(self):
        _ctrl("reduced_one", status="reduced", weight_multiplier=0.5)
        _ctrl("reduced_two", status="reduced", weight_multiplier=0.25)
        _ctrl("full_size", status="active")
        self.assertEqual(self._summary()["reduced_rules"], 2)

    def test_the_status_is_the_predicate_not_the_multiplier(self):
        """A rule left at weight_multiplier < 1.0 while status is active is
        NOT reduced: `rule_size_multiplier` ignores that column outside the
        reduced status, so the rule trades at full size."""
        _ctrl("stale_multiplier", status="active", weight_multiplier=0.5)
        self.assertEqual(self._summary()["reduced_rules"], 0)

    def test_nothing_reduced_is_a_measured_zero(self):
        _ctrl("plain", status="active")
        self.assertEqual(self._summary()["reduced_rules"], 0)


class PausedCounterTests(TestCase):
    """`status == "paused"` is not the paused population: nothing writes the
    column back when `paused_until` elapses, so the raw status keeps reporting
    a rule that has been signalling again for weeks as stopped. The counter
    reads the model's own `running_q()`, the ORM statement of
    `is_effectively_active()`."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("eye_paused", password="x")

    def _summary(self):
        from dashboard.views_eye import _rule_control_summary
        return _rule_control_summary(self.user)

    def test_a_live_pause_counts(self):
        _ctrl("still_paused", status="paused",
              paused_until=timezone.now() + timedelta(days=3))
        self.assertEqual(self._summary()["paused_rules"], 1)

    def test_an_indefinite_pause_counts(self):
        _ctrl("paused_forever", status="paused", paused_until=None)
        self.assertEqual(self._summary()["paused_rules"], 1)

    def test_an_expired_pause_does_not(self):
        """The rule is signalling again — `is_effectively_active` says so."""
        from signals.models_control import RuleControl
        ctrl = _ctrl("pause_elapsed", status="paused",
                     paused_until=timezone.now() - timedelta(days=1))
        self.assertTrue(ctrl.is_effectively_active())
        self.assertEqual(self._summary()["paused_rules"], 0)
        # The column still says "paused"; only the reading changed.
        self.assertEqual(
            RuleControl.objects.get(rule_name="pause_elapsed").status, "paused")

    def test_a_reduced_rule_is_not_paused(self):
        _ctrl("reduced_and_running", status="reduced", weight_multiplier=0.5)
        self.assertEqual(self._summary()["paused_rules"], 0)


class OneBrokenCounterTests(TestCase):
    """The blast radius, asserted directly: a failure in one counter must not
    take an unrelated one down with it, and must not be silent."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("eye_blast", password="x")

    def _summary(self):
        from dashboard.views_eye import _rule_control_summary
        return _rule_control_summary(self.user)

    def _broken_rule_control(self):
        broken = MagicMock()
        broken.objects.filter.side_effect = FieldError("no such field")
        broken.objects.exclude.side_effect = FieldError("no such field")
        return broken

    def test_a_healthy_counter_survives_a_broken_one(self):
        _action("some_rule")
        _action("some_rule")
        _action("another_rule")
        with self.assertLogs("dashboard.views_eye", level=logging.ERROR):
            with patch("signals.models.RuleControl",
                       self._broken_rule_control()):
                out = self._summary()
        self.assertEqual(out["paused_rules"], 0)
        self.assertEqual(out["reduced_rules"], 0)
        self.assertEqual(out["live_actions_24h"], 3,
                         "a RuleControl failure used to zero this too")

    def test_the_failure_is_logged_rather_than_absorbed(self):
        with self.assertLogs("dashboard.views_eye", level=logging.ERROR) as cm:
            with patch("signals.models.RuleControl",
                       self._broken_rule_control()):
                self._summary()
        joined = "\n".join(cm.output)
        self.assertIn("reduced_rules", joined)
        self.assertIn("paused_rules", joined)

    def test_a_missing_phase5_module_is_still_a_quiet_skip(self):
        """The one failure here that is expected rather than a bug: the
        docstring's stripped-down deployment. It keeps its own guard, and it
        does not shout.

        `None` in sys.modules is what an absent module looks like to an
        `import` statement — ImportError, raised at the import itself.
        """
        with patch.dict("sys.modules", {"signals.models": None}):
            out = self._summary()
        self.assertEqual(out, {"paused_rules": 0, "reduced_rules": 0,
                               "live_actions_24h": 0})


class ActionsCounterTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("eye_actions", password="x")

    def _summary(self):
        from dashboard.views_eye import _rule_control_summary
        return _rule_control_summary(self.user)

    def test_only_applied_actions_inside_the_window_count(self):
        from signals.models_control import RuleAction
        _action("recent", applied_ago_hours=2)
        _action("older", applied_ago_hours=48)
        RuleAction.objects.create(rule_name="never_applied",
                                  action=RuleAction.ACTION_PAUSE)
        self.assertEqual(self._summary()["live_actions_24h"], 1)


class EyePagePillsTests(TestCase):
    """End to end: the numbers reach the panel that shows them."""

    def setUp(self):
        self.user = User.objects.create_user("eye_page", password="x")
        self.client.force_login(self.user)

    def test_the_panel_prints_the_counted_values(self):
        _ctrl("p_rule", status="paused",
              paused_until=timezone.now() + timedelta(days=1))
        _ctrl("r_rule", status="reduced", weight_multiplier=0.5)
        _action("r_rule")
        resp = self.client.get("/eye/partial/", HTTP_HOST="127.0.0.1")
        self.assertEqual(resp.status_code, 200)
        body = " ".join(resp.content.decode("utf-8", "replace").split())
        self.assertEqual(resp.context["rule_control"],
                         {"paused_rules": 1, "reduced_rules": 1,
                          "live_actions_24h": 1})
        self.assertIn("reduced: 1", body)
        self.assertIn("paused: 1", body)
        self.assertIn("actions/24h: 1", body)
