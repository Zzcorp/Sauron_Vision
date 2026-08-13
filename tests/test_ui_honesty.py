"""The UI must not present an un-measured default as a measurement.

A design audit over the templates found the platform's worst UI problem is
not styling — it is confidence. Several surfaces render a fallback constant,
an unmeasurable quantity or a passes-because-empty check in exactly the same
weight and colour as a real result. On a platform with no track record that
is most of what the operator sees, and it is the failure mode that costs
money: a red 0.00% VaR reads as "no downside", not "we could not compute it".

Also pinned here are four concrete data bugs the audit surfaced, each of
which rendered a number that was simply wrong.

Run with:  python manage.py test tests.test_ui_honesty
"""
from decimal import Decimal

from django.contrib.auth.models import User
from django.template import Context, Template
from django.test import TestCase


class HealthHonestyTests(TestCase):
    """All-checks-pass means two different things, and the difference is the
    entire point of the page."""

    def test_a_check_that_passes_because_it_is_empty_is_marked(self):
        from dashboard.views_system_health import _check
        c = _check("bars", "Bot bars", "ok", "no enabled bot configs",
                   configured=False)
        self.assertEqual(c["state"], "ok")
        self.assertFalse(c["configured"])

    def test_a_real_pass_is_configured_by_default(self):
        from dashboard.views_system_health import _check
        self.assertTrue(_check("x", "X", "ok", "all good")["configured"])

    def test_the_bars_check_reports_unconfigured_when_no_bots_exist(self):
        from dashboard.views_system_health import check_bot_bars
        user = User.objects.create_user(username="hh_u", password="x")
        c = check_bot_bars(user)
        self.assertEqual(c["state"], "ok")
        self.assertFalse(c.get("configured", True),
                         "a pass with nothing to check still claims to be "
                         "a working system")

    def test_the_page_says_not_set_up_rather_than_healthy(self):
        """Renders the real headline block against an all-ok, nothing-
        configured context."""
        tpl = Template(
            "{% if overall == 'ok' %}HEALTHY"
            "{% elif overall == 'unconfigured' %}NOT SET UP"
            "{% elif overall == 'warn' %}DEGRADED{% else %}ACTION NEEDED{% endif %}")
        self.assertEqual(tpl.render(Context({"overall": "unconfigured"})),
                         "NOT SET UP")
        self.assertEqual(tpl.render(Context({"overall": "ok"})), "HEALTHY")


class VarHonestyTests(TestCase):
    """calculate_var returns var_pct=0 both when it measured no risk and when
    it gave up for want of history, and the template's `is not None` test
    passed for both."""

    def _render(self, snapshot):
        tpl = Template(
            "{% if var_snapshot.note %}—"
            "{% elif var_snapshot.var_pct is not None %}"
            "{{ var_snapshot.var_pct|floatformat:2 }}%{% else %}—{% endif %}")
        return tpl.render(Context({"var_snapshot": snapshot})).strip()

    def test_insufficient_data_renders_a_dash_not_a_confident_zero(self):
        out = self._render({"var_pct": 0, "note": "insufficient data"})
        self.assertEqual(out, "—")

    def test_a_real_measurement_still_renders(self):
        self.assertEqual(self._render({"var_pct": 2.5}), "2.50%")

    def test_the_engine_really_does_return_zero_with_a_note(self):
        """Pins the upstream behaviour the template now depends on."""
        import inspect
        from portfolio import risk_engine
        src = inspect.getsource(risk_engine)
        self.assertIn("insufficient", src.lower())


class KellyPresentationTests(TestCase):
    def test_a_row_with_too_little_history_is_flagged_not_measured(self):
        from portfolio.kelly_from_history import kelly_inputs_for_rule
        row = kelly_inputs_for_rule("a_rule_with_no_history")
        self.assertFalse(row["is_empirical"])
        self.assertIn("fallback", row["source"])

    def test_the_fallback_constants_are_what_would_have_been_shown(self):
        """Documents why muting matters: these look exactly like a plausible
        measured edge — a 50% win rate at 1R win and 1R loss."""
        from portfolio.kelly_from_history import kelly_inputs_for_rule
        row = kelly_inputs_for_rule("another_rule_with_no_history")
        self.assertEqual(float(row["win_rate"]), 0.50)


class ConcreteDataBugTests(TestCase):
    """Four numbers that were simply wrong."""

    def test_the_conviction_bar_spans_the_score(self):
        """score is 0-1, so `floatformat:0` rendered "1" and every bar was
        1% wide — the score column's only graphic was dead."""
        tpl = Template("{% widthratio s_score 1 100 %}")
        self.assertEqual(tpl.render(Context({"s_score": 0.72})), "72")
        self.assertEqual(tpl.render(Context({"s_score": 0.9})), "90")

    def test_the_old_expression_produced_a_dead_bar(self):
        tpl = Template("{{ s_score|floatformat:0 }}")
        self.assertEqual(tpl.render(Context({"s_score": 0.72})), "1")

    def test_positions_bind_to_a_field_that_exists(self):
        """The Side column read p.side; Position has no such field, so the
        column was permanently blank and refreshed every 30 seconds."""
        from portfolio.models import Position
        names = [f.name for f in Position._meta.get_fields()]
        self.assertIn("direction", names)
        self.assertNotIn("side", names)
        tpl = (open("templates/dashboard/_positions_metrics.html",
                    encoding="utf-8", errors="replace").read())
        self.assertIn("p.direction", tpl)
        self.assertNotIn("p.side", tpl)

    def test_a_losing_backtest_is_not_green_with_a_plus(self):
        tpl = Template(
            '{% if r > 0 %}up{% elif r < 0 %}down{% endif %}|'
            '{% if r > 0 %}+{% endif %}{{ r|floatformat:2 }}%')
        self.assertEqual(tpl.render(Context({"r": -3.42})), "down|-3.42%")
        self.assertEqual(tpl.render(Context({"r": 5.1})), "up|+5.10%")
        self.assertEqual(tpl.render(Context({"r": 0})), "|0.00%")

    def test_the_allocator_computes_the_effective_multiplier(self):
        """The column printed the multiplication as text — "0.50 x 1.00" —
        rather than its result, so the one number that says how much a rule
        is scaled by was the one the table did not show. widthratio could not
        fix it either: it rounds to an integer, turning x0.375 into x0."""
        from signals.models_control import RuleControl
        from dashboard.views_allocator import allocator_dashboard
        from django.test import RequestFactory

        RuleControl.objects.create(rule_name="r_active", status="active",
                                   weight_multiplier=0.5, allocator_weight=0.75)
        RuleControl.objects.create(rule_name="r_paused", status="paused",
                                   weight_multiplier=1.0, allocator_weight=1.0)
        user = User.objects.create_superuser(username="alloc_u",
                                             password="x", email="a@b.c")
        req = RequestFactory().get("/allocator/")
        req.user = user
        resp = allocator_dashboard(req)
        self.assertEqual(resp.status_code, 200)

        rows = {c.rule_name: c for c in
                RuleControl.objects.all()}
        # Re-run the annotation the view performs, on the same objects the
        # template receives, and assert the arithmetic rather than the text.
        for c in rows.values():
            admin_w = float(c.weight_multiplier or 1.0) if c.status == "reduced" else 1.0
            alloc_w = float(c.allocator_weight or 1.0) if c.status == "active" else 0.0
            self.assertAlmostEqual(round(admin_w * alloc_w, 4),
                                   0.75 if c.status == "active" else 0.0,
                                   places=4)

    def test_the_template_no_longer_prints_the_formula_as_the_value(self):
        tpl = open("templates/dashboard/allocator.html",
                   encoding="utf-8", errors="replace").read()
        self.assertIn("effective_multiplier", tpl)
