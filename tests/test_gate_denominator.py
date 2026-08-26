"""The limits are percentages of the operator's book, not of a seed.

Every risk limit on this platform is a percentage of a book value, and
the gates read that value from the SHARED limits book — the same row
that correctly holds the four percentages themselves.

Nothing puts the operator's money on that row. `/setup/`'s capital form
resolves `get_or_create_default_portfolio(user=request.user)` and saves
`current_value` there, on the operator's OWN row. And
`recalculate_exposure` re-values every book from its own positions, so
the shared row tracks a book whose bot half is empty by construction and
settles back to the seeded `PORTFOLIO_INITIAL_CAPITAL` — 10,000 by
default — and stays there.

Meanwhile the numerator was always per-operator: `realized_since` and
`open_capital_at_work` both filter `config__user=user`. So a real 50,000
book was measured against a 10,000 denominator, and a 3% daily-loss
floor halted the fleet at -300 instead of -1,500 with a reason that
never named the book it used. For a book UNDER the seed it errs the
other way, which is the direction that costs money.

Run with:  python manage.py test tests.test_gate_denominator
"""
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase


def _own_book(user, value):
    from portfolio.services import get_or_create_default_portfolio
    pf = get_or_create_default_portfolio(user=user)
    pf.current_value = Decimal(str(value))
    pf.save(update_fields=["current_value"])
    return pf


def _limits(**pct):
    from portfolio.risk_gate import limits_book
    book = limits_book()
    book.current_value = Decimal("10000")        # the seed nobody sets
    for k, v in pct.items():
        setattr(book, k, v)
    book.save()
    return book


class TheDenominatorIsTheOperatorsBookTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("gate_u", password="x")

    def test_the_size_comes_from_the_operators_row(self):
        from portfolio.risk_gate import gate_book_value, limits_book
        _limits()
        _own_book(self.user, 50000)
        self.assertEqual(gate_book_value(self.user, limits_book()), 50000.0)

    def test_without_a_user_the_passed_book_still_answers(self):
        """Every caller that hands in a book and no user keeps its old
        meaning — this must not change what a shared-book call means."""
        from portfolio.risk_gate import gate_book_value, limits_book
        _limits()
        self.assertEqual(gate_book_value(None, limits_book()), 10000.0)

    def test_an_operator_with_no_book_falls_back(self):
        from portfolio.risk_gate import gate_book_value, limits_book
        _limits()
        fresh = User.objects.create_user("no_book_u", password="x")
        self.assertIsNotNone(gate_book_value(fresh, limits_book()))


class ThePercentagesStillLiveOnTheSharedBookTests(TestCase):
    """The split is deliberate and must survive: the limits are shared,
    the book they scale is the operator's."""

    def setUp(self):
        self.user = User.objects.create_user("pct_u", password="x")

    def test_the_floor_is_a_percentage_of_the_operators_book(self):
        from portfolio.risk_gate import daily_loss_state
        _limits(max_daily_loss_pct=Decimal("3"))
        _own_book(self.user, 50000)
        state = daily_loss_state(self.user)
        self.assertAlmostEqual(abs(float(state["limit_money"])), 1500.0,
                               places=2)
        self.assertEqual(float(state["book_value"]), 50000.0)

    def test_the_old_behaviour_would_have_used_the_seed(self):
        """Names the bug: 3% of the seed is -300, not -1,500."""
        from portfolio.risk_gate import book_value, limits_book
        _limits(max_daily_loss_pct=Decimal("3"))
        _own_book(self.user, 50000)
        self.assertEqual(book_value(limits_book()), 10000.0)
        self.assertNotEqual(book_value(limits_book()), 50000.0)

    def test_the_ceiling_is_a_percentage_of_the_operators_book(self):
        from portfolio.risk_gate import exposure_state
        _limits(max_total_exposure_pct=Decimal("100"))
        _own_book(self.user, 50000)
        state = exposure_state(self.user)
        self.assertAlmostEqual(float(state["cap_money"]), 50000.0, places=2)
        self.assertEqual(float(state["book_value"]), 50000.0)

    def test_a_book_smaller_than_the_seed_tightens_rather_than_loosens(self):
        """The dangerous direction: an operator with 2,000 was being
        allowed the room of a 10,000 book."""
        from portfolio.risk_gate import exposure_state
        _limits(max_total_exposure_pct=Decimal("100"))
        _own_book(self.user, 2000)
        self.assertAlmostEqual(
            float(exposure_state(self.user)["cap_money"]), 2000.0, places=2)


class AnExplicitCapitalBaseStillWinsTests(TestCase):
    """The bot and manual pools size against their OWN capital and pass
    it in. That must keep overriding the book."""

    def setUp(self):
        self.user = User.objects.create_user("pool_u", password="x")

    def test_a_passed_capital_base_is_not_overridden(self):
        from portfolio.risk_gate import limits_book, single_position_state
        _limits(max_single_position_pct=Decimal("10"))
        _own_book(self.user, 50000)
        state = single_position_state(
            limits_book(), asset_class="stock", user=self.user,
            notional=500.0, capital_base=1000.0, base_label="bot pool")
        self.assertAlmostEqual(float(state["cap_money"]), 100.0, places=2)

    def test_without_one_it_uses_the_operators_book(self):
        from portfolio.risk_gate import limits_book, single_position_state
        _limits(max_single_position_pct=Decimal("10"))
        _own_book(self.user, 50000)
        state = single_position_state(
            limits_book(), asset_class="stock", user=self.user, notional=0.0)
        self.assertAlmostEqual(float(state["cap_money"]), 5000.0, places=2)


class TheSetupCardQuotesTheGateTests(TestCase):
    """A card describing a limit nobody applies is worse than no card."""

    def setUp(self):
        self.user = User.objects.create_superuser("card_u", "c@x.x", "x")
        self.client.force_login(self.user)

    def test_the_card_reads_the_same_book_the_gate_enforces(self):
        _limits(max_total_exposure_pct=Decimal("100"))
        _own_book(self.user, 50000)
        resp = self.client.get("/setup/")
        self.assertEqual(resp.status_code, 200)
        cap = float(resp.context["risk_exposure"]["cap_money"])
        self.assertAlmostEqual(cap, 50000.0, places=2)


class AnUnknownBookStaysUnknownTests(TestCase):
    """The trap this fix walked into on its first attempt.

    `book_value` answers None for a book whose size was never set, so a
    gate abstains rather than enforcing a number nobody entered. Reaching
    for the operator's row via `get_or_create_default_portfolio` SEEDS a
    new one at PORTFOLIO_INITIAL_CAPITAL — which turns "unknown" into a
    confident 10,000, the same fabrication this whole change removes.
    The lookup must never create.
    """

    def setUp(self):
        self.user = User.objects.create_user("unset_u", password="x")

    def test_an_operator_with_no_row_does_not_get_one_invented(self):
        from portfolio.models import Portfolio
        from portfolio.risk_gate import gate_book_value, limits_book

        book = limits_book()
        book.current_value = Decimal("0")          # never set
        book.save(update_fields=["current_value"])

        self.assertIsNone(gate_book_value(self.user, book))
        self.assertFalse(
            Portfolio.objects.filter(name="unset_u_main").exists(),
            "reading a gate must not create a book")

    def test_the_gate_abstains_rather_than_halting(self):
        """A 3% limit on a book of unknown size is not 'stop at zero'."""
        from portfolio.risk_gate import daily_loss_state, limits_book

        book = limits_book()
        book.current_value = Decimal("0")
        book.max_daily_loss_pct = Decimal("3")
        book.save()

        state = daily_loss_state(self.user)
        self.assertTrue(state["ok"])
        self.assertIsNone(state["book_value"])
        self.assertIn("never been set", state["reason"])
