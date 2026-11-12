"""MAX BOT FLOOR RISK (%) on /setup/ (2026-11-12): the most a bot's entry
raised to the venue's smallest size may risk at its stop, in percent of the
bot's pool.

The venue floor for bots (bot_program/asset_engine/base.py, behind the
live-money switch bots_venue_floor_live) opens an order that is under the
venue's minimum AT that minimum. That is more risk than the bot's own
setting buys, so the operator sets the ceiling: Portfolio
.max_bot_floor_risk_pct on the limits book, 2.0 by default, from 0.1 to the
platform's hard per-trade cap (sizing.MAX_RISK_FRACTION, 7%), never above.

Pinned here:
  * the field, its default and the migration that adds it (2.0: with the
    switch OFF nothing reads it, so nothing changes on deploy);
  * the reader bot_floor_risk_pct(): the book at call time; a value that
    cannot be read, is not a number or sits outside the bounds answers
    None, which is NO floor entry at all (it fails closed), and says so;
  * the card: saved with the other limits, all or none; a blank is
    refused like every other percentage (blank is not the default); a
    card rendered before the field existed keeps the stored value; never
    above 7.

Run with:  python manage.py test tests.test_bot_venue_floor_setting
"""
import re
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase

BASE_LOG = "bot_program.asset_engine.base"


def _ceiling(value):
    from portfolio.risk_gate import limits_book
    book = limits_book()
    book.max_bot_floor_risk_pct = value
    book.save(update_fields=["max_bot_floor_risk_pct", "updated_at"])
    return book


class TheSettingTests(TestCase):

    def test_two_percent_by_default_bounded_like_the_card(self):
        from bot_program.asset_engine import base
        from bot_program.asset_engine.sizing import MAX_RISK_FRACTION
        from dashboard.views import (RISK_LIMIT_BLANK_IS_NONE,
                                     RISK_LIMIT_BOUNDS, RISK_LIMIT_FIELDS,
                                     RISK_LIMIT_OPTIONAL, RISK_LIMIT_WHOLE)
        from portfolio.models import Portfolio
        from portfolio.risk_gate import limits_book
        field = Portfolio._meta.get_field("max_bot_floor_risk_pct")
        self.assertEqual(field.default, 2.0)
        self.assertFalse(field.null)
        self.assertEqual(limits_book().max_bot_floor_risk_pct, 2.0)
        self.assertEqual(base.BOT_FLOOR_RISK_DEFAULT_PCT, 2.0)
        low, high, label = RISK_LIMIT_BOUNDS["max_bot_floor_risk_pct"]
        self.assertEqual((low, high), base.BOT_FLOOR_RISK_BOUNDS)
        self.assertEqual((low, high), (0.1, 7.0))
        self.assertEqual(label, "Max bot floor risk")
        # never above the platform's hard per-trade cap
        self.assertAlmostEqual(high, MAX_RISK_FRACTION * 100, places=9)
        self.assertEqual(RISK_LIMIT_FIELDS["max_bot_floor_risk"],
                         "max_bot_floor_risk_pct")
        self.assertIn("max_bot_floor_risk", RISK_LIMIT_OPTIONAL)
        # a percentage: a blank is refused, a fraction is allowed
        self.assertNotIn("max_bot_floor_risk_pct", RISK_LIMIT_BLANK_IS_NONE)
        self.assertNotIn("max_bot_floor_risk_pct", RISK_LIMIT_WHOLE)

    def test_the_migration_adds_it_at_two_after_the_newest(self):
        from django.db.migrations.loader import MigrationLoader
        loader = MigrationLoader(None, ignore_no_migrations=True)
        mig = loader.disk_migrations[
            ("portfolio", "0020_portfolio_max_bot_floor_risk_pct")]
        self.assertEqual(mig.dependencies,
                         [("portfolio", "0019_traderprofile_rail_prefs")])
        (op,) = mig.operations
        self.assertEqual(type(op).__name__, "AddField")
        self.assertEqual((op.model_name, op.name),
                         ("portfolio", "max_bot_floor_risk_pct"))
        self.assertEqual(op.field.default, 2.0)
        self.assertFalse(op.field.null)

    def test_the_reader_reads_the_book_at_call_time(self):
        from bot_program.asset_engine.base import bot_floor_risk_pct
        self.assertEqual(bot_floor_risk_pct(), 2.0)
        for value in (0.1, 0.5, 1.25, 7.0, 7):
            _ceiling(value)
            self.assertEqual(bot_floor_risk_pct(), float(value))

    def test_out_of_bounds_reads_no_ceiling_and_says_so(self):
        """Only a write past the card can put one there. None is no floor
        entry at all: never the default, never a clamp."""
        from bot_program.asset_engine.base import bot_floor_risk_pct
        for value in (0, 0.05, -1, 7.01, 25, 100):
            _ceiling(value)
            with self.assertLogs(BASE_LOG, level="WARNING") as logs:
                self.assertIsNone(bot_floor_risk_pct(), value)
            self.assertIn("MAX BOT FLOOR RISK", logs.output[0])
            self.assertIn("no entry is raised", logs.output[0])

    def test_a_value_that_is_not_a_number_reads_no_ceiling(self):
        from bot_program.asset_engine.base import bot_floor_risk_pct
        for raw in ("2", True, None, float("nan"), float("inf"), object()):
            with mock.patch("portfolio.risk_gate.limits_book",
                            return_value=SimpleNamespace(
                                max_bot_floor_risk_pct=raw)):
                with self.assertLogs(BASE_LOG, level="WARNING"):
                    self.assertIsNone(bot_floor_risk_pct(), repr(raw))

    def test_an_unreadable_book_reads_no_ceiling_and_says_so(self):
        from bot_program.asset_engine.base import bot_floor_risk_pct
        with mock.patch("portfolio.risk_gate.limits_book",
                        side_effect=RuntimeError("no book")):
            with self.assertLogs(BASE_LOG, level="WARNING") as logs:
                self.assertIsNone(bot_floor_risk_pct())
        self.assertIn("unreadable", logs.output[0])

    def test_never_above_the_hard_cap_even_if_the_cap_is_lowered(self):
        """The reader reads sizing.MAX_RISK_FRACTION at call time: a stored
        6 under a hard cap of 5% is no ceiling."""
        from bot_program.asset_engine.base import bot_floor_risk_pct
        _ceiling(6.0)
        self.assertEqual(bot_floor_risk_pct(), 6.0)
        with mock.patch("bot_program.asset_engine.sizing.MAX_RISK_FRACTION",
                        0.05):
            with self.assertLogs(BASE_LOG, level="WARNING"):
                self.assertIsNone(bot_floor_risk_pct())


class TheCardTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("floor_ui",
                                                        password="x")

    def setUp(self):
        self.client.force_login(self.user)

    def _post(self, **overrides):
        data = {"action": "update_risk", "max_exposure": "100",
                "max_position": "20", "max_daily_loss": "8",
                "max_correlation": "0.7", "max_theme_legs": "3"}
        data.update(overrides)
        return self.client.post("/setup/", data, follow=True)

    def test_the_card_saves_it_with_the_others(self):
        from portfolio.risk_gate import limits_book
        r = self._post(max_bot_floor_risk="1.5", max_daily_loss="6")
        self.assertContains(r, "Risk limits updated")
        book = limits_book()
        self.assertAlmostEqual(book.max_bot_floor_risk_pct, 1.5)
        self.assertAlmostEqual(book.max_daily_loss_pct, 6.0)

    def test_a_blank_is_refused_and_nothing_is_saved(self):
        """Blank is not the default: a ceiling nobody typed is not saved,
        and the stored number stays."""
        from portfolio.risk_gate import limits_book
        _ceiling(1.5)
        for blank in ("", "   "):
            r = self._post(max_bot_floor_risk=blank, max_daily_loss="4")
            self.assertContains(r, "NOT saved")
            self.assertContains(r, "Max bot floor risk was left blank")
            book = limits_book()
            self.assertAlmostEqual(book.max_bot_floor_risk_pct, 1.5)
            self.assertNotAlmostEqual(book.max_daily_loss_pct, 4.0)

    def test_out_of_bounds_is_refused_and_nothing_is_saved(self):
        from portfolio.risk_gate import limits_book
        _ceiling(1.5)
        for raw in ("0", "0.05", "-1", "7.01", "8", "25", "abc"):
            r = self._post(max_bot_floor_risk=raw, max_daily_loss="4")
            self.assertContains(r, "NOT saved")
            self.assertContains(r, "Max bot floor risk")
            book = limits_book()
            self.assertAlmostEqual(book.max_bot_floor_risk_pct, 1.5,
                                   msg=raw)
            self.assertNotAlmostEqual(book.max_daily_loss_pct, 4.0, msg=raw)

    def test_the_refusal_names_the_hard_cap(self):
        r = self._post(max_bot_floor_risk="8")
        self.assertContains(
            r, "Max bot floor risk must be between 0.1 and 7 — the most a "
               "bot&#x27;s entry raised to the venue&#x27;s smallest size "
               "may risk, in percent of its pool; 7% is the hard cap of "
               "every trade")
        self.assertNotContains(r, "8 would gate every trade")

    def test_the_bounds_themselves_are_saved(self):
        from portfolio.risk_gate import limits_book
        for raw, want in (("0.1", 0.1), ("7", 7.0)):
            r = self._post(max_bot_floor_risk=raw)
            self.assertContains(r, "Risk limits updated")
            self.assertAlmostEqual(limits_book().max_bot_floor_risk_pct,
                                   want)

    def test_a_sibling_refused_saves_no_ceiling_either(self):
        from portfolio.risk_gate import limits_book
        r = self._post(max_bot_floor_risk="1.5", max_daily_loss="")
        self.assertContains(r, "NOT saved")
        self.assertAlmostEqual(limits_book().max_bot_floor_risk_pct, 2.0)

    def test_a_form_without_the_field_still_saves_and_keeps_it(self):
        """A card rendered before the field existed: the others save and
        the stored ceiling is kept (absent is not blank)."""
        from portfolio.risk_gate import limits_book
        r = self._post(max_daily_loss="6")
        self.assertContains(r, "Risk limits updated")
        self.assertAlmostEqual(limits_book().max_bot_floor_risk_pct, 2.0)
        _ceiling(1.25)
        self._post(max_daily_loss="7")
        book = limits_book()
        self.assertAlmostEqual(book.max_daily_loss_pct, 7.0)
        self.assertAlmostEqual(book.max_bot_floor_risk_pct, 1.25)

    def test_the_card_renders_it_with_its_help(self):
        r = self.client.get("/setup/")
        self.assertContains(r, "MAX BOT FLOOR RISK (%)")
        self.assertContains(r, 'name="max_bot_floor_risk" value="2.0"')
        self.assertContains(r, "Bots: Venue Floor")
        self.assertContains(r, "never above 7")
        _ceiling(1.5)
        r = self.client.get("/setup/")
        self.assertContains(r, 'name="max_bot_floor_risk" value="1.5"')

    def test_it_sits_beside_max_bot_leverage(self):
        body = self.client.get("/setup/").content.decode()
        lev = body.index("MAX BOT LEVERAGE (x)")
        floor = body.index("MAX BOT FLOOR RISK (%)")
        risk = body.index("MAX OPEN RISK (%)")
        self.assertLess(lev, floor)
        self.assertLess(floor, risk)

    def test_the_input_takes_a_percentage_from_a_tenth_to_seven(self):
        for d in settings.TEMPLATES[0]["DIRS"]:
            path = Path(d) / "dashboard/setup.html"
            if path.exists():
                body = path.read_text(encoding="utf-8")
                break
        tags = [t for t in re.findall(r"<input[^>]*>", body)
                if 'name="max_bot_floor_risk"' in t]
        self.assertEqual(len(tags), 1)
        tag = tags[0]
        self.assertIn('type="number"', tag)
        self.assertIn('step="any"', tag)
        self.assertIn('min="0.1"', tag)
        self.assertIn('max="7"', tag)
        self.assertIn("required", tag)
