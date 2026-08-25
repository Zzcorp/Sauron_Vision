"""The brain's concerns become actions — one press each, none of them a trade.

The operator read the latest synthesis (five EUR-bloc legs wearing six
tickets, a squeeze rule breaking out into a random walk, a golden cross
live with no closed trades, manual takes wandering out of commodities) and
said "act on its concerns". The platform cannot move the live account
from code, so acting means: the overlay's `pause_recommended` becomes a
"Propose pause" press, `watch` a "Propose size cut", both landing in the
HQ actuator queue an admin still has to apply; a theme concern links to
the pages where exposure is actually managed; discretionary drift offers
the manual-config kill switch, superuser only. Every press is idempotent
per (report, rule, action) so a nervous double-click queues one row, and
the page swaps the button for a state chip once a proposal stands.

Run with:  python manage.py test tests.test_brain_actions
"""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse


SYNTHESIS_CONCERNS = [
    {"kind": "theme_saturation", "severity": 0.82, "ref": "eur_bloc",
     "text": "Five long EUR-bloc legs — one bet wearing six tickets; trim to two."},
    {"kind": "rule_regime_mismatch", "severity": 0.70,
     "ref": "bollinger_squeeze_breakout",
     "text": "bollinger_squeeze_breakout is breaking out into a random walk; pause the forex leg."},
    {"kind": "unvalidated_exposure", "severity": 0.60, "ref": "golden_cross",
     "text": "golden_cross is live with no closed trades; watch, do not add."},
    {"kind": "discretionary_drift", "severity": 0.45, "ref": "manual_take",
     "text": "manual_take used outside commodities; restrict it there."},
]
SYNTHESIS_OVERLAY = {
    "manual_take": "watch",
    "golden_cross": "watch",
    "rsi_bull_divergence": "active",
    "bollinger_squeeze_breakout": "pause_recommended",
}


def _report(**over):
    from brain.models import BrainReport
    fields = dict(regime_label="mean_reverting", regime_confidence=0.6,
                  portfolio_health_score=0.4,
                  top_concerns=SYNTHESIS_CONCERNS,
                  rule_status_overlay=SYNTHESIS_OVERLAY,
                  narrative_md="One bet wearing six tickets.")
    fields.update(over)
    return BrainReport.objects.create(**fields)


def _staff(name="brain_staff"):
    return User.objects.create_user(username=name, password="x", is_staff=True)


def _superuser(name="brain_super"):
    return User.objects.create_superuser(username=name, password="x", email="")


def _plain(name="brain_plain"):
    return User.objects.create_user(username=name, password="x")


def _manual_config(user, asset_class, enabled=True):
    from bot_program.manual_trade import MANUAL_CONFIG_NAME
    from bot_program.models import AssetBotConfig
    return AssetBotConfig.objects.create(
        user=user, asset_class=asset_class, name=MANUAL_CONFIG_NAME,
        enabled=enabled, mode="paper", symbols=[])


class ProposeFromBrainTests(TestCase):
    def test_the_first_press_creates_one_proposal_and_the_second_returns_it(self):
        from signals.models import RuleAction
        from signals.rule_actuator import propose_from_brain
        report = _report()
        user = _staff()
        first = propose_from_brain(report, "bollinger_squeeze_breakout", "pause_rule", user)
        second = propose_from_brain(report, "bollinger_squeeze_breakout", "pause_rule", user)
        self.assertEqual(first.id, second.id)
        self.assertEqual(RuleAction.objects.filter(source_brain_report=report).count(), 1)
        self.assertEqual(first.state, RuleAction.STATE_PROPOSED)
        self.assertEqual(first.action, RuleAction.ACTION_PAUSE)
        self.assertIsNone(first.source_investigation)

    def test_the_rationale_names_the_report_the_overlay_and_the_concern(self):
        from signals.rule_actuator import propose_from_brain
        report = _report()
        ra = propose_from_brain(report, "golden_cross", "reduce_size", _staff())
        self.assertIn(f"brain synthesis #{report.id}", ra.rationale)
        self.assertIn("overlay watch", ra.rationale)
        self.assertIn("no closed trades", ra.rationale)

    def test_informational_actions_are_refused(self):
        from signals.models import RuleAction
        from signals.rule_actuator import propose_from_brain, ActuatorError
        report = _report()
        for bad in ("monitor", "investigate_data", "retune_params", ""):
            with self.assertRaises(ActuatorError):
                propose_from_brain(report, "golden_cross", bad, _staff(f"s_{bad or 'blank'}"))
        self.assertFalse(RuleAction.objects.exists())

    def test_the_migration_gives_ruleaction_its_brain_source(self):
        """The test database is built from the migration chain, so a row
        saved through the FK proves 0018 applied and reverse-relates."""
        from signals.models import RuleAction
        report = _report()
        ra = RuleAction.objects.create(rule_name="x", action="pause_rule",
                                       source_brain_report=report)
        self.assertEqual(list(report.rule_actions.all()), [ra])


class ProposeEndpointTests(TestCase):
    def test_a_non_staff_press_is_forbidden(self):
        from signals.models import RuleAction
        report = _report()
        self.client.force_login(_plain())
        resp = self.client.post(reverse("brain_propose"), {
            "report_id": report.id, "rule_name": "bollinger_squeeze_breakout",
            "action": "pause_rule"})
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(RuleAction.objects.exists())

    def test_a_staff_press_creates_once_and_redirects_to_the_brain_page(self):
        from signals.models import RuleAction
        report = _report()
        self.client.force_login(_staff())
        payload = {"report_id": report.id, "rule_name": "bollinger_squeeze_breakout",
                   "action": "pause_rule"}
        resp = self.client.post(reverse("brain_propose"), payload)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], reverse("brain_dashboard"))
        resp = self.client.post(reverse("brain_propose"), payload)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(RuleAction.objects.filter(source_brain_report=report).count(), 1)

    def test_an_xhr_press_answers_json_with_the_row_it_made(self):
        report = _report()
        self.client.force_login(_staff())
        resp = self.client.post(reverse("brain_propose"), {
            "report_id": report.id, "rule_name": "golden_cross",
            "action": "reduce_size"}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["state"], "proposed")
        self.assertEqual(body["rule_name"], "golden_cross")


class BrainPageLeversTests(TestCase):
    def test_pause_recommended_shows_the_propose_pause_button(self):
        _report()
        self.client.force_login(_staff())
        html = self.client.get(reverse("brain_dashboard")).content.decode()
        self.assertIn("Propose pause · bollinger_squeeze_breakout", html)
        self.assertIn("Propose size cut · golden_cross", html)
        self.assertIn("Propose size cut · manual_take", html)
        self.assertNotIn("· rsi_bull_divergence", html)
        self.assertIn("Proposals wait for an admin at HQ; nothing here trades.", html)

    def test_a_standing_proposal_replaces_the_button_with_its_state_chip(self):
        from signals.rule_actuator import propose_from_brain
        report = _report()
        user = _staff()
        propose_from_brain(report, "bollinger_squeeze_breakout", "pause_rule", user)
        self.client.force_login(user)
        html = self.client.get(reverse("brain_dashboard")).content.decode()
        self.assertNotIn("Propose pause · bollinger_squeeze_breakout", html)
        self.assertIn('data-lever-state="proposed"', html)
        self.assertIn("proposed &middot; pause_rule", html)
        self.assertIn(reverse("admin_dashboard"), html)

    def test_theme_saturation_links_to_positions_and_books_for_a_superuser(self):
        _report()
        self.client.force_login(_superuser())
        html = self.client.get(reverse("brain_dashboard")).content.decode()
        self.assertIn("Open cross-book concentration", html)
        self.assertIn(reverse("hq_books"), html)
        self.assertIn("Open positions", html)
        self.assertIn(reverse("positions_list"), html)

    def test_theme_saturation_keeps_the_books_link_from_non_superusers(self):
        _report()
        self.client.force_login(_staff())
        html = self.client.get(reverse("brain_dashboard")).content.decode()
        self.assertNotIn("Open cross-book concentration", html)
        self.assertIn("Open positions", html)

    def test_disable_manual_forms_appear_only_for_non_commodity_configs(self):
        _report()
        su = _superuser()
        forex = _manual_config(su, "forex")
        _manual_config(su, "commodity")
        _manual_config(su, "crypto", enabled=False)
        self.client.force_login(su)
        html = self.client.get(reverse("brain_dashboard")).content.decode()
        self.assertIn("Disable manual &middot; forex", html)
        self.assertIn(f'name="config_id" value="{forex.id}"', html)
        self.assertNotIn("Disable manual &middot; commodity", html)
        self.assertNotIn("Disable manual &middot; crypto", html)
        self.assertIn(reverse("brain_disable_manual"), html)

    def test_disable_manual_forms_are_a_note_for_staff_who_are_not_superusers(self):
        _report()
        staff = _staff()
        _manual_config(staff, "forex")
        self.client.force_login(staff)
        html = self.client.get(reverse("brain_dashboard")).content.decode()
        self.assertNotIn("Disable manual &middot; forex", html)
        self.assertIn("superuser press at HQ", html)
        self.assertNotIn(reverse("brain_disable_manual"), html)

    def test_an_unknown_concern_kind_gets_no_fabricated_lever(self):
        _report(top_concerns=[{"kind": "weather", "severity": 0.5,
                               "text": "It is raining on the exchange."}],
                rule_status_overlay={})
        self.client.force_login(_superuser())
        html = self.client.get(reverse("brain_dashboard")).content.decode()
        self.assertIn("It is raining on the exchange.", html)
        self.assertIn("No platform lever for this concern", html)
        self.assertNotIn(reverse("brain_propose"), html)
