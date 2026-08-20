"""A money gain without a percentage does not say how good it was.

+250 is a different trade on a 1,000 position than on a 100,000 one, and the
currency figure alone cannot tell them apart. Wherever this platform prints
what a position or a day MADE, it prints what that was as a share of what
was put in.

The percentage is None — never 0 — when there is no base to divide by. A
percentage of an unknown book is not a small percentage, it is not a
percentage, and it renders as an em-dash for the same reason every other
unmeasured value on this platform does.

Run with:  python manage.py test tests.test_gain_shows_percent
"""
import re
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

#: Templates that print a money gain, and the loop variable each uses.
GAIN_SURFACES = (
    ("dashboard/_command_portfolio.html", "p.unrealized_pnl"),
    ("dashboard/portfolio_overview.html", "p.unrealized_pnl"),
)


def _template(rel):
    for d in settings.TEMPLATES[0]["DIRS"]:
        path = Path(d) / rel
        if path.exists():
            return path.read_text(encoding="utf-8")
    raise AssertionError(f"template not found: {rel}")


class EveryGainCarriesItsPercentTests(SimpleTestCase):
    def test_each_money_figure_has_a_percentage_beside_it(self):
        for rel, var in GAIN_SURFACES:
            body = _template(rel)
            for line in body.splitlines():
                if f"{{{{ {var}|floatformat" in line:
                    self.assertIn(
                        "pnl-pct", line,
                        f"{rel}: prints money with no percentage beside it: "
                        f"{line.strip()[:90]}")

    def test_an_unmeasured_percentage_is_a_dash_not_a_zero(self):
        for rel, _var in GAIN_SURFACES:
            body = _template(rel)
            self.assertIn("unrealized_pnl_pct is not None", body, rel)
            self.assertIn("&mdash;", body, rel)

    def test_the_percentage_is_styled_and_not_a_raw_span(self):
        css = (Path(settings.BASE_DIR) / "static" / "css" / "sauron.css") \
            .read_text(encoding="utf-8")
        self.assertIn(".pnl-pct", css)


class TwentyFourHourPercentTests(TestCase):
    """The aggregate case, where the denominator is the book rather than the
    position, and the view has to supply it."""

    def setUp(self):
        self.user = get_user_model().objects.create_user("pct_u", password="x")

    def _book(self, value):
        from portfolio.risk_gate import limits_book
        book = limits_book()
        book.current_value = Decimal(str(value))
        book.save(update_fields=["current_value"])
        return book

    def _closed(self, pnl):
        from bot_program.models import AssetBotConfig, AssetBotTrade
        from django.utils import timezone
        cfg, _ = AssetBotConfig.objects.get_or_create(
            user=self.user, asset_class="crypto", name="pct bot",
            defaults={"capital": Decimal("10000")})
        t = AssetBotTrade.objects.create(
            config=cfg, asset_class="crypto", symbol="BTCUSD", side="BUY",
            qty=Decimal("1"), entry_price=Decimal("100"),
            exit_price=Decimal("110"), status="CLOSED",
            pnl=Decimal(str(pnl)), paper=True)
        t.closed_at = timezone.now()
        t.save(update_fields=["closed_at"])
        return t

    def test_a_gain_is_reported_as_a_share_of_the_book(self):
        from dashboard.views_eye import _pnl_24h
        self._book(10000)
        self._closed(250)
        out = _pnl_24h(self.user)
        self.assertEqual(float(out["total"]), 250.0)
        self.assertEqual(out["pct"], 2.5)

    def test_a_loss_keeps_its_sign(self):
        from dashboard.views_eye import _pnl_24h
        self._book(10000)
        self._closed(-500)
        self.assertEqual(_pnl_24h(self.user)["pct"], -5.0)

    def test_each_asset_class_carries_its_own_share(self):
        from dashboard.views_eye import _pnl_24h
        self._book(10000)
        self._closed(250)
        by_class = _pnl_24h(self.user)["by_class"]
        self.assertEqual(by_class["crypto"]["pct"], 2.5)

    def test_an_unset_book_gives_none_and_not_zero(self):
        """The distinction the whole platform runs on: a percentage nobody
        could compute is not a percentage of nothing."""
        from dashboard.views_eye import _pnl_24h
        self._book(0)
        self._closed(250)
        out = _pnl_24h(self.user)
        self.assertEqual(float(out["total"]), 250.0)
        self.assertIsNone(out["pct"])

    def test_a_quiet_day_is_a_measured_zero(self):
        from dashboard.views_eye import _pnl_24h
        self._book(10000)
        out = _pnl_24h(self.user)
        self.assertEqual(out["pct"], 0.0)

    def test_the_panel_renders_the_percentage(self):
        self.assertIn("pnl_24h.pct", _template("dashboard/_eye_body.html"))

    def test_the_panel_dashes_an_unmeasured_one(self):
        body = _template("dashboard/_eye_body.html")
        self.assertIn("pnl_24h.pct is not None", body)
