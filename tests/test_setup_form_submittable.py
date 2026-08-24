"""A settings form must accept the values it renders.

The Risk Limits card could not be submitted from a browser at all. HTML5
measures `step` from the STEP BASE, and the step base is `min` when one is
present — so `min="0.1" step="1"` admits 0.1, 1.1, 2.1 and nothing else.
Three of the four fields rendered their own shipped default as an invalid
value, and the browser refused the whole form silently, on the one page
whose purpose is setting those numbers.

Nothing server-side could catch it: the request never arrives. So the check
has to be on the markup, and it has to be the browser's own arithmetic.

Run with:  python manage.py test tests.test_setup_form_submittable
"""
import re
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

INPUT_RE = re.compile(r"<input[^>]*type=\"number\"[^>]*>")
ATTR_RE = re.compile(r'(\w[\w-]*)="([^"]*)"')


def _inputs(rel):
    for d in settings.TEMPLATES[0]["DIRS"]:
        path = Path(d) / rel
        if path.exists():
            body = path.read_text(encoding="utf-8")
            break
    else:
        raise AssertionError(f"template not found: {rel}")
    out = []
    for tag in INPUT_RE.findall(body):
        attrs = dict(ATTR_RE.findall(tag))
        if attrs.get("name"):
            out.append(attrs)
    return out


def _step_valid(value: Decimal, minimum, step) -> bool:
    """The browser's own rule: (value - base) must be a whole multiple of step.

    `step="any"` disables the check entirely, which is the point of using it.
    """
    if step is None or step == "any":
        return True
    base = Decimal(minimum) if minimum is not None else Decimal(0)
    quantum = Decimal(step)
    if quantum <= 0:
        return True
    return ((value - base) % quantum) == 0


class RiskLimitFormTests(SimpleTestCase):
    """Every numeric input on /setup/ must accept the model's own default."""

    FIELD_DEFAULTS = {
        "max_exposure": "max_total_exposure_pct",
        "max_position": "max_single_position_pct",
        "max_daily_loss": "max_daily_loss_pct",
        "max_correlation": "max_correlation_threshold",
        "max_theme_legs": "max_theme_legs",
    }

    def setUp(self):
        self.inputs = {a["name"]: a for a in _inputs("dashboard/setup.html")}

    def test_every_risk_input_is_present(self):
        for name in self.FIELD_DEFAULTS:
            self.assertIn(name, self.inputs)

    def test_every_shipped_default_is_a_submittable_value(self):
        from portfolio.models import Portfolio
        for name, field in self.FIELD_DEFAULTS.items():
            attrs = self.inputs[name]
            default = Decimal(str(Portfolio._meta.get_field(field).default))
            self.assertTrue(
                _step_valid(default, attrs.get("min"), attrs.get("step")),
                f"{name}: the form renders {default} but step="
                f"{attrs.get('step')!r} from a base of {attrs.get('min')!r} "
                f"does not admit it — the browser will refuse to submit")

    def test_every_shipped_default_is_inside_the_declared_range(self):
        from portfolio.models import Portfolio
        for name, field in self.FIELD_DEFAULTS.items():
            attrs = self.inputs[name]
            default = Decimal(str(Portfolio._meta.get_field(field).default))
            if attrs.get("min") is not None:
                self.assertGreaterEqual(default, Decimal(attrs["min"]), name)
            if attrs.get("max") is not None:
                self.assertLessEqual(default, Decimal(attrs["max"]), name)

    def test_a_mid_range_value_an_operator_would_type_is_submittable(self):
        """Defaults are not the only values that have to work — the field
        exists to be changed."""
        typed = {"max_exposure": Decimal("85"), "max_position": Decimal("12.5"),
                 "max_daily_loss": Decimal("2.5"),
                 "max_correlation": Decimal("0.65"),
                 "max_theme_legs": Decimal("4")}
        for name, value in typed.items():
            attrs = self.inputs[name]
            self.assertTrue(
                _step_valid(value, attrs.get("min"), attrs.get("step")),
                f"{name}: an operator cannot type {value}")


class TheRuleItselfTests(SimpleTestCase):
    """Pin the browser arithmetic, so the helper above cannot drift into
    agreeing with whatever the markup happens to say."""

    def test_a_min_offset_step_rejects_a_round_number(self):
        # The exact shape of the bug: base 0.1, step 1, value 100.
        self.assertFalse(_step_valid(Decimal("100"), "0.1", "1"))

    def test_the_same_step_from_a_zero_base_accepts_it(self):
        self.assertTrue(_step_valid(Decimal("100"), "0", "1"))

    def test_step_any_accepts_anything(self):
        self.assertTrue(_step_valid(Decimal("0.7"), "0.01", "any"))
        self.assertTrue(_step_valid(Decimal("100"), "0.1", "any"))
