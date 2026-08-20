"""The platform's own defaults must not refuse the platform's own trade.

Wiring the /setup/ Risk Limits into a real gate exposed a contradiction that
had been invisible for as long as the fields enforced nothing: a fresh book
and a fresh bot pool are both seeded at 10,000, the portfolio allowed 10% in
one position (1,000) and the sizing engine allowed 20% of the pool (2,000).
The operator's first default-sized ticket was refused by arithmetic between
two of our own numbers.

Only reachable once the limits bind, which is exactly why it needs a test
rather than a comment: nothing else in the suite compares the two pools.

Run with:  python manage.py test tests.test_shipped_defaults_agree
"""
from decimal import Decimal

from django.test import SimpleTestCase, TestCase


def _field_default(model, name):
    return model._meta.get_field(name).default


class SinglePositionCeilingTests(SimpleTestCase):
    def test_the_portfolio_ceiling_is_not_tighter_than_the_sizing_engine(self):
        """Two pools, seeded identically, that must not contradict.

        The sizing fraction is the tuned number — it carries per-class
        overrides and every position has been sized by it. The portfolio
        percentage is the one that moves.
        """
        from bot_program.asset_engine.sizing import DEFAULT_MAX_NOTIONAL_FRACTION
        from portfolio.models import Portfolio

        portfolio_pct = float(_field_default(Portfolio,
                                             "max_single_position_pct"))
        sizing_pct = DEFAULT_MAX_NOTIONAL_FRACTION * 100.0
        self.assertGreaterEqual(
            portfolio_pct, sizing_pct,
            f"a fresh book allows {portfolio_pct:g}% in one position while "
            f"sizing allows {sizing_pct:g}% of an identically-seeded pool — "
            f"the default trade is refused by our own arithmetic")

    def test_the_default_pools_really_are_seeded_the_same(self):
        """The premise of the test above. If these ever diverge, comparing
        the two percentages stops meaning anything and this file needs
        rewriting rather than quietly passing."""
        from bot_program.models import AssetBotConfig
        self.assertEqual(Decimal(str(_field_default(AssetBotConfig, "capital"))),
                         Decimal("10000"))

    def test_a_total_exposure_ceiling_of_100_does_not_pre_refuse_anything(self):
        from portfolio.models import Portfolio
        self.assertGreaterEqual(
            float(_field_default(Portfolio, "max_total_exposure_pct")), 100.0)


class GateAcceptsTheDefaultTicketTests(TestCase):
    """End to end: a default-sized position on a default book clears the gate.

    The unit test above compares two constants; this one asks the gate
    itself, so a future change to how capital-at-work is measured cannot
    quietly reintroduce the refusal while the percentages still look fine.
    """

    def test_a_default_equity_ticket_clears_the_single_position_ceiling(self):
        from portfolio.models import Portfolio
        from portfolio.risk_gate import single_position_state

        book = Portfolio.objects.create(
            name="defaults", initial_capital=Decimal("10000"),
            current_value=Decimal("10000"), cash_available=Decimal("10000"))
        # 20% of a 10,000 bot pool — the largest position sizing will build
        # for an equity at the shipped fraction.
        state = single_position_state(book, asset_class="stock",
                                      notional=2000.0)
        self.assertTrue(state["ok"], state.get("reason"))

    def test_a_position_past_the_ceiling_is_still_refused(self):
        """The ceiling moved; it did not stop existing."""
        from portfolio.models import Portfolio
        from portfolio.risk_gate import single_position_state

        book = Portfolio.objects.create(
            name="defaults2", initial_capital=Decimal("10000"),
            current_value=Decimal("10000"), cash_available=Decimal("10000"))
        state = single_position_state(book, asset_class="stock",
                                      notional=5000.0)
        self.assertFalse(state["ok"])
        self.assertIn("2,000", state["reason"].replace(" ", " "))
