"""Live and paper, told apart at a glance (2026-09-13).

The bottom strip's money cells were all cross-venue, and honest about it:
its heads read "PORTFOLIO · BOTH BOOKS" and "OPEN POSITIONS · BOTH BOOKS".
Honest, but the wrong grain for the question an operator asks fastest —
*how much real money is engaged right now*. A simulated pool inflates the
pooled `used_total`, and no live entry can draw a cent of the pooled
`free_total`.

`portfolio.services.capital_summary` has kept the split since it was
written, and says why at the dict that produces it: "a paper pool and a
live pool are not one bucket of deployable money — summing them
advertised 'free' capital that no live entry could actually draw on".
Nothing rendered it. This adds `used_live`/`used_paper` to complete the
set, publishes the six figures to the strip, and pins the one rule the
whole platform already obeys: THE TWO ARE NEVER SUMMED.

THE COLOUR. A survey of the codebase on the same day found THREE
conventions running against each other — red=live on the position hover
card and the HQ account grid, gold=live in the capital card's MODE
column, and /desk/ borrowing the `bearish` badge for live. Three answers
to one question teach the operator none of them. Red wins because it is
the one that already carries a written reason (sauron.css:2284): "LIVE is
real money and has to be legible as such before the operator reaches the
close button. PAPER stays deliberately unremarkable — a paper position
dressed as an alert trains the operator to ignore the colour."

Run with:  python manage.py test tests.test_venue_split
"""
import html
import re
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.test import RequestFactory, SimpleTestCase, TestCase


def _user(name="vs_u"):
    return User.objects.create_user(username=name, password="x")


def _config(user, name, mode, capital):
    from bot_program.models import AssetBotConfig
    return AssetBotConfig.objects.create(
        user=user, asset_class="crypto", name=name, enabled=True,
        mode=mode, symbols=[], capital=Decimal(capital), base_currency="USD")


def _ctx(user):
    from core.context_processors import sauron_context
    request = RequestFactory().get("/")
    request.user = user
    return sauron_context(request)


class CapitalSummarySplitsByVenueTests(TestCase):

    def setUp(self):
        self.user = _user()
        _config(self.user, "live-pool", "live", "1000")
        _config(self.user, "paper-pool", "paper", "4000")

    def test_the_split_carries_pool_used_and_free_for_each_venue(self):
        from portfolio.services import capital_summary
        cap = capital_summary(self.user)
        for key in ("pool_live", "pool_paper", "used_live", "used_paper",
                    "free_live", "free_paper"):
            self.assertIn(key, cap, f"{key} missing — the split is incomplete "
                                    f"and a caller will re-derive it wrongly")

    def test_a_live_pool_is_never_inflated_by_a_paper_one(self):
        """The whole point. 1,000 live beside 4,000 paper is not 5,000 of
        anything an operator can deploy."""
        from portfolio.services import capital_summary
        cap = capital_summary(self.user)
        self.assertEqual(cap["pool_live"], 1000.0)
        self.assertEqual(cap["pool_paper"], 4000.0)
        self.assertEqual(cap["pool_total"], 5000.0)
        self.assertNotEqual(cap["pool_live"], cap["pool_total"])

    def test_free_is_shown_negative_rather_than_clamped(self):
        """An oversubscribed pool is exactly the state these cells exist to
        surface, per capital_summary's own comment."""
        from portfolio.services import capital_summary
        cap = capital_summary(self.user)
        self.assertIsInstance(cap["free_live"], float)
        self.assertIsInstance(cap["free_paper"], float)


class TheStripPublishesBothVenuesTests(TestCase):

    def setUp(self):
        self.user = _user("vs_ctx")
        _config(self.user, "live-pool", "live", "1000")
        _config(self.user, "paper-pool", "paper", "4000")

    def test_the_context_carries_six_venue_figures(self):
        ctx = _ctx(self.user)
        for key in ("panel_pool_live", "panel_pool_paper",
                    "panel_used_live", "panel_used_paper",
                    "panel_free_live", "panel_free_paper"):
            self.assertIn(key, ctx, f"{key} is not published to the strip")

    def test_the_live_figure_is_the_live_one(self):
        ctx = _ctx(self.user)
        self.assertEqual(ctx["panel_pool_live"], "1,000")
        self.assertEqual(ctx["panel_pool_paper"], "4,000")

    def test_the_pooled_cells_are_still_there(self):
        """The split is an addition, not a replacement: the head still says
        BOTH BOOKS and the pooled figure is still the answer to a different,
        legitimate question."""
        ctx = _ctx(self.user)
        self.assertEqual(ctx["panel_pool"], "5,000")


class TheTemplateRendersTheSplitTests(SimpleTestCase):

    def _base(self):
        return (Path(settings.BASE_DIR) / "templates" / "base.html").read_text(
            encoding="utf-8")

    def test_the_strip_shows_engaged_and_free_per_venue(self):
        base = self._base()
        for needle in ("panel_used_live", "panel_used_paper",
                       "panel_free_live", "panel_free_paper"):
            self.assertIn(needle, base, f"{needle} is computed and published "
                                        f"and still not rendered anywhere")

    def test_every_venue_figure_dashes_rather_than_zeroes(self):
        """An unreadable pool is unknown, not empty. The strip's oldest rule
        and the Oculus's: 0 is a measurement, the em dash is not."""
        base = self._base()
        for needle in ("panel_used_live", "panel_used_paper",
                       "panel_free_live", "panel_free_paper"):
            start = base.index(needle)
            cell = base[start:start + 400]
            self.assertIn("sv-unknown", cell,
                          f"the cell for {needle} renders no em-dash branch — "
                          f"an unreadable figure would print as blank or 0")

    def test_the_label_carries_the_venue_not_the_value(self):
        """A live FIGURE painted red is indistinguishable from a loss, and
        the value column already uses red for a negative free pool."""
        base = self._base()
        self.assertIn('<span class="sv-venue sv-venue--live">LIVE</span>', base)
        self.assertIn('<span class="sv-venue sv-venue--paper">PAPER</span>',
                      base)
        # The marker belongs inside the key, never the value.
        for m in re.finditer(r'class="dv[^"]*"[^>]*>([^<]*)<span class="sv-venue',
                             base):
            self.fail(f"a venue marker leaked into a value cell: {m.group(0)}")


class TheVenueColourIsSaidOnceTests(SimpleTestCase):

    def _css(self):
        return (Path(settings.BASE_DIR) / "static" / "css" / "sauron.css"
                ).read_text(encoding="utf-8")

    def test_red_is_live_and_paper_is_muted(self):
        css = self._css()
        self.assertIn(".sv-venue--live { color: var(--accent-red); }", css)
        self.assertIn(".sv-venue--paper { color: var(--text-muted); }", css)

    def test_the_marker_does_not_fill_a_background(self):
        """It sits in dense grids where a fill fights the cell borders — and
        a row tinted by venue shouts across the whole card, which is the
        'paper position dressed as an alert' the original comment warns
        against."""
        css = self._css()
        block = css[css.index(".sv-venue {"):css.index(".sv-venue--paper") + 120]
        self.assertNotIn("background", block)

    def test_the_convention_it_extends_is_still_there(self):
        """If the rule this was promoted FROM is ever deleted, the promotion
        needs revisiting rather than silently becoming the only source."""
        css = self._css()
        self.assertIn(".pos-pop-venue.is-live", css)
        self.assertIn(".hq-acct--live", css)
        self.assertIn("real money", css)
