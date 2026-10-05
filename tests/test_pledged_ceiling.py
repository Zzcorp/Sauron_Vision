"""MAX ACCOUNT PLEDGED is the operator's number (2026-10-01).

The operator's son took a manual EURUSD ticket at 1x (~1,016 USD of a
2,240 USD eToro account, 45%) and every stock ticket after it was refused:
"the account would be 60% pledged after UNG ... the ceiling is 50%". The
50% was a constant (asset_engine.base.MAX_PLEDGED_FRACTION). He chose 80.

The percentage now lives on the limits book (Portfolio.max_pledged_pct,
the /setup/ Risk Limits card) and base.pledged_ceiling() reads it, for
the order gate and for Morgul's G6 alike: a gate at 80 with a watchdog
still braking at 55 would stop every live bot the moment an order the
gate allowed filled. Pinned here: the reader (the operator's number,
the old constant when unreadable or out of bounds), Morgul following it,
and the card (saves it, refuses it blank or out of bounds, keeps it when
an older form leaves it out). The gate's own refusal is pinned in
tests/test_etoro_leverage.py next to the 50% one.

Run with:  python manage.py test tests.test_pledged_ceiling
"""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from tests.test_morgul import _Case, _by_subject, _cfg, _check, _etoro


def _set(pct):
    from portfolio.risk_gate import limits_book
    book = limits_book()
    book.max_pledged_pct = pct
    book.save(update_fields=["max_pledged_pct", "updated_at"])
    return book


class TheReaderTests(TestCase):

    def test_the_default_is_the_old_constant(self):
        from bot_program.asset_engine.base import (MAX_PLEDGED_FRACTION,
                                                   pledged_ceiling)
        self.assertEqual(MAX_PLEDGED_FRACTION, 0.5)
        self.assertEqual(pledged_ceiling(), 0.5)

    def test_the_operators_number_is_read(self):
        from bot_program.asset_engine.base import pledged_ceiling
        _set(80)
        self.assertAlmostEqual(pledged_ceiling(), 0.8)

    def test_out_of_bounds_falls_back_to_the_default(self):
        from bot_program.asset_engine.base import pledged_ceiling
        for pct in (0, 5, 9.9, 100.1, 150, -10):
            _set(pct)
            with self.assertLogs("bot_program.asset_engine.base", "WARNING"):
                self.assertEqual(pledged_ceiling(), 0.5, pct)

    def test_the_whole_account_may_be_pledged_since_the_operator_asked(self):
        """2026-10-05: "même 100% de cap". 95 was the ceiling of the card
        and of the reader; 100 now reads as the whole account, and Morgul's
        alarm, the ceiling plus its slack, is clamped at the whole account
        so it still sounds — the moment the margin used exceeds the equity."""
        from bot_program.asset_engine.base import (PLEDGED_PCT_BOUNDS,
                                                   pledged_ceiling)
        from bot_program.morgul import MARGIN_SLACK, margin_alarm_fraction
        self.assertEqual(PLEDGED_PCT_BOUNDS, (10.0, 100.0))
        _set(100)
        self.assertEqual(pledged_ceiling(), 1.0)
        _set(95.1)
        self.assertAlmostEqual(pledged_ceiling(), 0.951)
        self.assertAlmostEqual(margin_alarm_fraction(0.8), 0.8 + MARGIN_SLACK)
        self.assertEqual(margin_alarm_fraction(1.0), 1.0)
        self.assertEqual(margin_alarm_fraction(0.97), 1.0)
        self.assertEqual(margin_alarm_fraction("x"), 1.0)

    def test_an_unreadable_book_falls_back_to_the_default(self):
        from bot_program.asset_engine.base import pledged_ceiling
        with patch("portfolio.risk_gate.limits_book",
                   side_effect=RuntimeError("db gone")), \
                self.assertLogs("bot_program.asset_engine.base", "WARNING"):
            self.assertEqual(pledged_ceiling(), 0.5)


class MorgulFollowsTheCeilingTests(_Case):
    """G6 brakes at the ceiling + MARGIN_SLACK. It must read the same
    ceiling the gate does, or an order the gate allows trips the brake."""

    def setUp(self):
        super().setUp()
        self.now = timezone.now()
        self.cfg = _cfg(self.user, "Stocks live", "stock", mode="live")

    def _acct(self, used):
        return _etoro(self.user, demo=False, is_primary_for_stocks=True,
                      last_equity=Decimal("100"), last_equity_currency="USD",
                      last_used_margin=Decimal(str(used)),
                      last_margin_at=self.now - timedelta(minutes=5),
                      last_margin_world="live")

    def test_sixty_percent_is_quiet_under_an_eighty_ceiling(self):
        _set(80)
        self._acct(60)
        self.assertEqual(_check("margin", self.now)[1], [])

    def test_past_the_raised_ceiling_and_five_points_is_critical(self):
        _set(80)
        acct = self._acct(90)
        f = _by_subject(_check("margin", self.now)[1])[
            f"account:{acct.pk}:pledged"]
        self.assertEqual(f.severity, "critical")
        self.assertIn("Pledged: 90.0% of equity; the limit is 80.0%, the "
                      "alarm 85.0%", f.facts)

    def test_at_the_whole_account_the_alarm_sounds_past_the_equity_not_never(self):
        """A ceiling of 100 plus five points would put the alarm at 105%
        of equity, which never comes: the alarm is clamped at the whole
        account, quiet at 99%, critical the moment the margin exceeds it."""
        _set(100)
        acct = self._acct(99)
        self.assertEqual(_check("margin", self.now)[1], [])
        acct.last_used_margin = Decimal("101")
        acct.save(update_fields=["last_used_margin"])
        f = _by_subject(_check("margin", self.now)[1])[
            f"account:{acct.pk}:pledged"]
        self.assertEqual(f.severity, "critical")
        self.assertIn("Pledged: 101.0% of equity; the limit is 100.0%, the "
                      "alarm 100.0%", f.facts)


class TheCardTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("pledge_ui",
                                                        password="x")

    def setUp(self):
        self.client.force_login(self.user)

    def _post(self, **overrides):
        data = {"action": "update_risk", "max_exposure": "100",
                "max_position": "20", "max_daily_loss": "8",
                "max_correlation": "0.7", "max_theme_legs": "3"}
        data.update(overrides)
        return self.client.post("/setup/", data, follow=True)

    def test_the_card_saves_it(self):
        from portfolio.risk_gate import limits_book
        self._post(max_pledged="80")
        self.assertAlmostEqual(limits_book().max_pledged_pct, 80.0)

    def test_the_card_renders_it(self):
        _set(80)
        r = self.client.get("/setup/")
        self.assertContains(r, 'name="max_pledged"')
        self.assertContains(r, "MAX ACCOUNT PLEDGED")

    def test_blank_or_out_of_bounds_is_refused_and_nothing_is_saved(self):
        from portfolio.risk_gate import limits_book
        _set(70)
        for raw in ("", "5", "101", "abc"):
            r = self._post(max_pledged=raw, max_daily_loss="4")
            self.assertContains(r, "NOT saved")
            book = limits_book()
            self.assertAlmostEqual(book.max_pledged_pct, 70.0, msg=raw)
            self.assertNotAlmostEqual(book.max_daily_loss_pct, 4.0, msg=raw)

    def test_the_card_takes_the_whole_account_since_the_operator_asked(self):
        """2026-10-05, "même 100% de cap": 100 saves (95 was the card's
        ceiling), 100.1 does not, and the card says what 100 means."""
        from portfolio.risk_gate import limits_book
        self._post(max_pledged="100")
        self.assertAlmostEqual(limits_book().max_pledged_pct, 100.0)
        r = self.client.get("/setup/")
        self.assertContains(r, 'max="100"')
        self.assertContains(r, "one gap can take the whole account")
        r = self._post(max_pledged="100.1")
        self.assertContains(r, "NOT saved")
        self.assertAlmostEqual(limits_book().max_pledged_pct, 100.0)

    def test_a_form_without_the_field_keeps_it_and_saves_the_rest(self):
        """A card rendered before the field existed still saves."""
        from portfolio.risk_gate import limits_book
        _set(80)
        self._post(max_daily_loss="6")
        book = limits_book()
        self.assertAlmostEqual(book.max_pledged_pct, 80.0)
        self.assertAlmostEqual(book.max_daily_loss_pct, 6.0)
