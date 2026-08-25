"""The operator sees every book at once — and where the bets pile up.

The risk gates judge each book alone; the All-Books page is the view
they cannot have. Its discipline is capital_summary's, all the way
down: paper and live pools are separate rows, currencies are never
summed into one figure, an unpriced leg is counted rather than valued
at a stale entry, option premium is its own fact — and only REAL money
trips the crowded flag.

Run with:  python manage.py test tests.test_all_books
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone


def _instrument(symbol, asset_class="stock"):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol,
                                 "asset_class": asset_class})
    return inst


def _position(user, symbol, qty="1", price="100", priced=True):
    from portfolio.models import Position
    from portfolio.services import get_or_create_default_portfolio
    return Position.objects.create(
        portfolio=get_or_create_default_portfolio(user=user),
        instrument=_instrument(symbol), direction="long",
        quantity=Decimal(qty), entry_price=Decimal(price),
        current_price=Decimal(price) if priced else Decimal("0"),
        opened_at=timezone.now() - timedelta(days=1))


def _bot_trade(user, symbol, qty="1", entry="100", capital="1000",
               mode="paper", name="ab_books", currency="USD"):
    from bot_program.models import AssetBotConfig, AssetBotTrade
    cfg, _ = AssetBotConfig.objects.get_or_create(
        user=user, asset_class="crypto", name=name,
        defaults=dict(enabled=True, mode=mode, symbols=[],
                      capital=Decimal(capital), base_currency=currency))
    return AssetBotTrade.objects.create(
        config=cfg, asset_class="crypto", symbol=symbol, side="BUY",
        qty=Decimal(qty), entry_price=Decimal(entry), status="OPEN")


class AllBooksTests(TestCase):
    def setUp(self):
        self.operator = get_user_model().objects.create_superuser(
            "books_op", "op@x.x", "x")
        self.client.force_login(self.operator)

    def _body(self):
        return self.client.get("/admin-dashboard/books/").content.decode()

    def test_the_page_is_for_the_operator_alone(self):
        outsider = get_user_model().objects.create_user("books_out",
                                                        password="x")
        self.client.force_login(outsider)
        self.assertEqual(
            self.client.get("/admin-dashboard/books/").status_code, 403)
        self.client.force_login(self.operator)
        self.assertEqual(
            self.client.get("/admin-dashboard/books/").status_code, 200)

    def test_every_book_appears(self):
        from portfolio.services import get_or_create_default_portfolio
        a = get_user_model().objects.create_user("books_a", password="x")
        b = get_user_model().objects.create_user("books_b", password="x")
        get_or_create_default_portfolio(user=a)
        get_or_create_default_portfolio(user=b)
        body = self._body()
        self.assertIn("books_a_main", body)
        self.assertIn("books_b_main", body)

    def test_the_bot_books_appear_with_their_pools(self):
        u = get_user_model().objects.create_user("books_bot", password="x")
        _bot_trade(u, "BTCUSD", capital="2500")
        body = self._body()
        self.assertIn("books_bot", body)
        self.assertIn("USD 2500.00", body)

    def test_paper_and_live_pools_are_never_one_number(self):
        """A live 5,000 pool and a paper 10,000 pool are two rows — the
        capital_summary rule: simulated money is not deployable money,
        and their sum is a figure no entry could draw on."""
        u = get_user_model().objects.create_user("books_pl", password="x")
        _bot_trade(u, "BTCUSD", capital="5000", mode="live", name="lv")
        _bot_trade(u, "ETHUSD", capital="10000", mode="paper", name="pp")
        body = self._body()
        self.assertIn("USD 5000.00", body)
        self.assertIn("USD 10000.00", body)
        self.assertNotIn("15000.00", body)
        self.assertIn("LIVE", body)
        self.assertIn("PAPER", body)

    def test_real_money_in_two_books_is_flagged_crowded(self):
        """A legacy book position plus a LIVE bot trade on one symbol —
        the per-book gates each saw half of it; this page sees both."""
        a = get_user_model().objects.create_user("books_c", password="x")
        b = get_user_model().objects.create_user("books_d", password="x")
        _position(a, "AAPL")
        _bot_trade(b, "AAPL", mode="live")
        body = self._body()
        self.assertIn("book · books_c_main", body)
        self.assertIn("bot · books_d [live]", body)
        self.assertIn("1 CROWDED", body)
        self.assertIn("Held in 2 books at once", body)

    def test_a_paper_overlap_is_listed_but_never_trips_the_flag(self):
        """Simulated exposure is shown — marked [paper] — but must not
        push the operator to trim REAL positions over fictional
        crowding."""
        a = get_user_model().objects.create_user("books_e", password="x")
        b = get_user_model().objects.create_user("books_f", password="x")
        _position(a, "TSLA")
        _bot_trade(b, "TSLA", mode="paper")
        body = self._body()
        self.assertIn("bot · books_f [paper]", body)
        self.assertIn("0 CROWDED", body)
        self.assertNotIn("books at once", body)

    def test_a_lonely_symbol_is_not_flagged(self):
        a = get_user_model().objects.create_user("books_g", password="x")
        _position(a, "MSFT")
        body = self._body()
        self.assertIn("MSFT", body)
        self.assertIn("0 CROWDED", body)
        self.assertNotIn("books at once", body)

    def test_currencies_never_merge_into_one_figure(self):
        """A EUR book leg and a USD bot leg on the same symbol are two
        labeled parts — never 'Long $ 20000.00', a number in no
        currency that exists."""
        from portfolio.services import get_or_create_default_portfolio
        a = get_user_model().objects.create_user("books_h", password="x")
        b = get_user_model().objects.create_user("books_i", password="x")
        book = get_or_create_default_portfolio(user=a)
        book.currency = "EUR"
        book.save(update_fields=["currency"])
        _position(a, "NVDA", qty="100", price="100")
        _bot_trade(b, "NVDA", qty="100", entry="100", mode="live")
        body = self._body()
        self.assertIn("EUR 10,000.00", body)
        self.assertIn("USD 10,000.00", body)
        self.assertNotIn("20,000.00", body)

    def test_an_unpriced_leg_is_counted_never_valued_at_entry(self):
        """The books table refuses to mark it; the concentration table
        must not quietly book it at a stale entry price either."""
        a = get_user_model().objects.create_user("books_j", password="x")
        _position(a, "RICE", qty="7", price="123.45", priced=False)
        body = self._body()
        self.assertIn("+1 unpriced", body)
        self.assertNotIn("864.15", body)  # 7 × 123.45 never appears

    def test_an_all_unpriced_book_says_dash_not_zero(self):
        """n_open > 0 with every leg unmarked used to print a confident
        '0.00 +1 unpriced' — the exact render the em-dash rule exists
        to forbid."""
        a = get_user_model().objects.create_user("books_k", password="x")
        _position(a, "COCOA", priced=False)
        body = self._body()
        row = body.split("books_k_main")[1].split("</tr>")[0]
        cell = row.rsplit("<td", 1)[1]  # the marked-exposure cell
        self.assertIn("&mdash;", cell)
        self.assertIn("+1 unpriced", cell)
        self.assertNotIn("0.00", cell)
