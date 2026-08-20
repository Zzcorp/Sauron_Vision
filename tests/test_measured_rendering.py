"""A price nobody booked must LOOK like a price nobody booked.

`{{ value|floatformat:2 }}` renders None as the EMPTY STRING. Not a zero,
not a dash — nothing at all. So a closed position whose exit price was
never booked drew a detail grid of labels with blank space underneath
them, and the operator reported it as the panel having no prices, which is
exactly what it looked like.

The platform already has a rule for this — None means NOT MEASURED and
renders an em-dash — written in longhand at dozens of sites. These filters
are that rule, available where floatformat was silently swallowing it.

Run with:  python manage.py test tests.test_measured_rendering
"""
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.template import Context, Template
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

DASH = "—"


def _render(src, **ctx):
    return Template("{% load sauron_tags %}" + src).render(Context(ctx))


class MeasuredFilterTests(SimpleTestCase):
    def test_a_number_still_renders_as_a_number(self):
        self.assertEqual(_render("{{ v|measured:2 }}", v=Decimal("2400.5")),
                         "2400.50")

    def test_none_is_a_dash_and_never_a_blank(self):
        """The bug, in one assertion."""
        self.assertEqual(_render("{{ v|measured:2 }}", v=None), DASH)

    def test_none_is_not_quietly_turned_into_a_zero(self):
        """The other way this gets 'fixed' wrong. A zero is a reading."""
        self.assertNotIn("0", _render("{{ v|measured:2 }}", v=None))

    def test_a_missing_context_variable_is_a_dash(self):
        self.assertEqual(_render("{{ nope|measured:2 }}"), DASH)

    def test_something_unnumeric_is_a_dash_rather_than_a_blank(self):
        self.assertEqual(_render("{{ v|measured:2 }}", v="n/a"), DASH)

    def test_a_percentage_keeps_its_sign_when_measured(self):
        self.assertEqual(_render("{{ v|measured_pct:2 }}", v=-3.5), "-3.50%")

    def test_an_unmeasured_percentage_drops_the_percent_sign(self):
        """A bare '%' is not a reading — it is a unit with nothing in it."""
        self.assertEqual(_render("{{ v|measured_pct:2 }}", v=None), DASH)


class SignClassTests(SimpleTestCase):
    """`{% if pnl >= 0 %}` is a trap: Django's smart-if swallows the
    TypeError from comparing None with 0 and evaluates it False, so every
    unmeasured number was painted in the LOSS colour — the platform stating
    a loss it had never measured."""

    def test_a_gain_is_up(self):
        self.assertEqual(_render("{{ v|sign_class }}", v=12), "up")

    def test_a_loss_is_down(self):
        self.assertEqual(_render("{{ v|sign_class }}", v=-12), "down")

    def test_a_measured_zero_is_up_not_a_loss(self):
        self.assertEqual(_render("{{ v|sign_class }}", v=0), "up")

    def test_an_unmeasured_value_is_neither(self):
        self.assertEqual(_render("{{ v|sign_class }}", v=None), "flat")

    def test_the_dash_colour_is_neutral_in_the_stylesheet(self):
        css = (Path(settings.BASE_DIR) / "static" / "css" / "sauron.css") \
            .read_text(encoding="utf-8")
        self.assertIn(".sign-flat", css)


class ClosedPositionDetailTests(TestCase):
    """End to end, on the surface the operator opened: expanding a closed
    trade in Trade History."""

    def setUp(self):
        self.user = get_user_model().objects.create_user("meas_u", password="x")
        self.client.force_login(self.user)

    def _closed(self, **over):
        from bot_program.models import AssetBotConfig, AssetBotTrade
        from instruments.models import Instrument
        Instrument.objects.get_or_create(
            symbol="XAUUSD",
            defaults={"name": "Gold", "asset_class": "commodity"})
        cfg, _ = AssetBotConfig.objects.get_or_create(
            user=self.user, asset_class="commodity", name="meas",
            defaults={"capital": Decimal("10000")})
        fields = dict(
            config=cfg, asset_class="commodity", symbol="XAUUSD", side="BUY",
            qty=Decimal("1"), entry_price=Decimal("2400"),
            exit_price=None, stop_loss=None, take_profit=None,
            status="CLOSED", pnl=Decimal("0"), paper=True)
        fields.update(over)
        trade = AssetBotTrade.objects.create(**fields)
        AssetBotTrade.objects.filter(pk=trade.pk).update(
            closed_at=timezone.now())
        return trade

    def _history(self):
        resp = self.client.get("/positions/?tab=history", HTTP_HOST="127.0.0.1")
        self.assertEqual(resp.status_code, 200)
        return resp.content.decode("utf-8", "replace")

    def test_an_unbooked_exit_price_leaves_no_empty_cell(self):
        """What the operator actually saw: a labelled blank."""
        import re
        self._closed()
        body = self._history()
        detail = body[body.find("ph-trade-detail"):][:3000]
        blanks = re.findall(r'ph-detail-value[^>]*>\s*</div>', detail)
        self.assertEqual(blanks, [], "a detail cell rendered with nothing in it")

    def test_the_unbooked_price_says_so(self):
        self._closed()
        detail = self._history()
        detail = detail[detail.find("ph-trade-detail"):][:3000]
        self.assertIn("Exit Price", detail)
        self.assertIn(DASH, detail)

    def test_a_booked_price_is_still_shown(self):
        """The fix must not dash a price that IS known."""
        self._closed(exit_price=Decimal("2450"))
        detail = self._history()
        self.assertIn("2450", detail)

    def test_the_chart_label_dashes_an_unbooked_exit(self):
        self._closed()
        body = self._history()
        seg = body[body.find("ph-chart-bar"):][:600]
        self.assertIn("Exit:", seg)
        self.assertNotIn("Exit: <", seg.replace("Exit: " + DASH, "ok"))
