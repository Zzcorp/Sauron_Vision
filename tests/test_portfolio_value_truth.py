"""Portfolio value: one definition, measured on the read, honest when partial.

The operator's report was "my portfolio cell is stuck at 10k capital, it does
not move whatever I have open" — on the bottom headband, on the Operations
Center and on the portfolio page. All three were reading `current_value`, a
STORED column whose only maintainers were two tasks that valued the LEGACY
book (portfolio.Position) on the SHARED "Main" portfolio. Every bot entry and
every TAKE TRADE writes bot_program.AssetBotTrade on a PER-USER book, so on
the operator's account the column was written once at creation and never
again.

What is asserted here:
  - `portfolio.services.live_book_value` is the one answer: cash plus BOTH
    books at live marks, with its components beside it so the total is
    checkable
  - a position with NO QUOTE is left OUT of the total and never valued at its
    entry price; the total is then flagged partial and says how many it missed
  - nothing priced at all means None, never 0 and never cash-only — while an
    EMPTY book is a measurement of exactly cash
  - `recalculate_exposure` moves the stored column on a book whose positions
    are bot trades, and refuses to overwrite it with a figure that measured
    nothing
  - the shared book is not fed other people's bot trades
  - every surface that renders a portfolio value renders that one number

Run with:  python manage.py test tests.test_portfolio_value_truth
    (NOT RUN by the slice that wrote it — another slice owns the runner.)
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone


DASH = "—"
HOST = "127.0.0.1"


# ── Fixtures ─────────────────────────────────────────────────────────────

def _user(name="pv_u"):
    return User.objects.create_user(username=name, password="x")


def _book(user=None):
    from portfolio.services import get_or_create_default_portfolio
    return get_or_create_default_portfolio(user=user)


def _instrument(symbol, asset_class="crypto", sector="", currency=""):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol,
        defaults={"name": symbol, "asset_class": asset_class,
                  "sector": sector, "currency": currency or "USD"})
    return inst


def _quote(symbol, last, asset_class="crypto"):
    from market_data.models import LiveQuote
    inst = _instrument(symbol, asset_class)
    quote, _ = LiveQuote.objects.update_or_create(
        instrument=inst, defaults={"last": Decimal(str(last)),
                                   "source": "test"})
    return quote


def _position(portfolio, symbol="AAPL", qty="2", entry="100", current="100",
              direction="long", asset_class="stock"):
    """A legacy portfolio.Position on the given book."""
    from portfolio.models import Position
    return Position.objects.create(
        portfolio=portfolio, instrument=_instrument(symbol, asset_class),
        direction=direction, quantity=Decimal(qty),
        entry_price=Decimal(entry), current_price=Decimal(current),
        opened_at=timezone.now() - timedelta(days=1))


def _config(user, name="B1", asset_class="crypto", **kw):
    from bot_program.models import AssetBotConfig
    defaults = dict(enabled=True, mode="paper", symbols=[],
                    capital=Decimal("10000"), base_currency="USD")
    defaults.update(kw)
    return AssetBotConfig.objects.create(
        user=user, asset_class=asset_class, name=name, **defaults)


def _trade(user, symbol="BTCUSD", status="OPEN", side="BUY", qty="1",
           entry="100", config=None, **kw):
    from bot_program.models import AssetBotTrade
    cfg = config or _config(user, name=f"cfg-{symbol}-{status}")
    return AssetBotTrade.objects.create(
        config=cfg, asset_class=cfg.asset_class, symbol=symbol, side=side,
        qty=Decimal(qty), entry_price=Decimal(entry), status=status, **kw)


def _value(user, portfolio=None):
    from portfolio.services import live_book_value
    return live_book_value(user, portfolio or _book(user))


def _run_exposure():
    """The gated task, called past both decorators as the suite does."""
    from portfolio.tasks import recalculate_exposure
    return recalculate_exposure.__wrapped__.__wrapped__()


def _run_snapshot():
    from portfolio.tasks import create_daily_snapshot
    return create_daily_snapshot.__wrapped__.__wrapped__()


# ── 1. One function, both books, components beside the total ─────────────

class LiveBookValueTests(TestCase):
    def setUp(self):
        self.user = _user("pv_value")
        self.pf = _book(self.user)
        self.cash = float(self.pf.cash_available)

    def test_it_counts_both_books_at_live_marks(self):
        """A legacy Position AND an AssetBotTrade, each at its own quote."""
        _quote("AAPL", "120", asset_class="stock")
        _position(self.pf, "AAPL", qty="2", entry="100")
        _quote("BTCUSD", "110")
        _trade(self.user, "BTCUSD", qty="3", entry="100")

        book = _value(self.user, self.pf)
        # EXPOSURE is the full deployed notional of both halves, whoever's
        # money it is: 2 x 120 legacy + 3 x 110 bot.
        self.assertAlmostEqual(book.marked, 570.0, places=2)
        # VALUE is what those positions actually ADDED. The legacy row is
        # funded from the cash column, so it contributes its 240 marked. The
        # bot row is paper — nothing debited cash when it opened — so it
        # contributes only its P&L, (110 - 100) x 3 = 30.
        self.assertAlmostEqual(book.value, self.cash + 240.0 + 30.0, places=2)
        self.assertAlmostEqual(book.funded_marked, 240.0, places=2)
        self.assertAlmostEqual(book.simulated_pnl, 30.0, places=2)
        self.assertEqual(book.n_open, 2)
        self.assertEqual(book.n_priced, 2)
        self.assertFalse(book.partial)

    def test_the_total_is_its_components(self):
        """A total whose parts are invisible is a number nobody can check."""
        _quote("BTCUSD", "110")
        _trade(self.user, "BTCUSD", qty="4", entry="100")
        book = _value(self.user, self.pf)
        self.assertAlmostEqual(
            book.value, book.cash + book.funded_marked + book.simulated_pnl,
            places=6)
        self.assertEqual(book.n_open, book.n_priced + book.n_unpriced)

    def test_a_flat_position_does_not_change_what_the_book_is_worth(self):
        """The bug this split exists for. Nothing debits `cash_available`
        when a paper position opens, so adding its notional on top of cash
        that still held it booked a gain for placing a trade: a flat 2-lot
        of gold on a 10,000 book read as 14,800."""
        before = _value(self.user, self.pf).value
        _quote("BTCUSD", "100")
        _trade(self.user, "BTCUSD", qty="20", entry="100")   # 2,000 deployed
        book = _value(self.user, self.pf)
        self.assertAlmostEqual(book.value, before, places=2)
        self.assertAlmostEqual(book.unrealized, 0.0, places=2)
        # ...and it is still exposure, so the gate still sees it.
        self.assertAlmostEqual(book.marked, 2000.0, places=2)

    def test_a_bot_trade_moves_the_value(self):
        """The regression this slice exists for. The stored column could not
        move on a book whose positions are AssetBotTrade rows."""
        before = _value(self.user, self.pf).value
        _quote("BTCUSD", "110")
        _trade(self.user, "BTCUSD", qty="4", entry="100")
        after = _value(self.user, self.pf).value
        # By its P&L — (110 - 100) x 4 — and not by its 440 of notional,
        # which was never taken out of the cash column to begin with.
        self.assertAlmostEqual(after - before, 40.0, places=2)

    def test_a_mark_moving_moves_the_value(self):
        _quote("BTCUSD", "110")
        _trade(self.user, "BTCUSD", qty="2", entry="100")
        before = _value(self.user, self.pf).value
        _quote("BTCUSD", "130")
        self.assertAlmostEqual(
            _value(self.user, self.pf).value - before, 40.0, places=2)

    def test_a_short_is_exposure_of_the_same_size_as_a_long(self):
        """Deployed capital, not signed delta: a short is not negative
        exposure, and netting the two would report a hedged book as flat."""
        _quote("BTCUSD", "110")
        _trade(self.user, "BTCUSD", side="SELL", qty="3", entry="100")
        self.assertAlmostEqual(_value(self.user, self.pf).marked, 330.0,
                               places=2)

    def test_a_closed_trade_leaves_the_book(self):
        _quote("BTCUSD", "110")
        trade = _trade(self.user, "BTCUSD", qty="2")
        self.assertEqual(_value(self.user, self.pf).n_open, 1)
        trade.status = "CLOSED"
        trade.closed_at = timezone.now()
        trade.save(update_fields=["status", "closed_at"])
        book = _value(self.user, self.pf)
        self.assertEqual(book.n_open, 0)
        self.assertAlmostEqual(book.value, self.cash, places=2)

    def test_close_pending_still_counts_as_exposure(self):
        """The broker refused the close, so it is still open there — every
        other surface in the platform counts CLOSE_PENDING as exposure."""
        _quote("BTCUSD", "110")
        _trade(self.user, "BTCUSD", status="CLOSE_PENDING", qty="2")
        self.assertEqual(_value(self.user, self.pf).n_open, 1)
        self.assertAlmostEqual(_value(self.user, self.pf).marked, 220.0,
                               places=2)

    def test_it_reuses_the_platforms_one_union(self):
        """Not a third walk over the two books: the numbers this returns are
        the numbers the Operations Center and the headband already read."""
        from dashboard.views_command import _open_book
        _quote("BTCUSD", "110")
        _trade(self.user, "BTCUSD", qty="2")
        _quote("AAPL", "120", asset_class="stock")
        _position(self.pf, "AAPL")
        rows, n_priced, unrealized, deployed = _open_book(self.user, self.pf)
        book = _value(self.user, self.pf)
        self.assertEqual(book.n_open, len(rows))
        self.assertEqual(book.n_priced, n_priced)
        self.assertEqual(book.unrealized, unrealized)
        self.assertAlmostEqual(book.marked, deployed, places=6)

    def test_a_precomputed_union_is_accepted_rather_than_redone(self):
        """A page that renders the rows AND the total pays for one union."""
        from dashboard.views_command import _open_book
        _quote("BTCUSD", "110")
        _trade(self.user, "BTCUSD", qty="2")
        union = _open_book(self.user, self.pf)
        from portfolio.services import live_book_value
        self.assertEqual(live_book_value(self.user, self.pf, book=union).value,
                         _value(self.user, self.pf).value)


# ── 2. Unmeasurable stays unmeasurable ───────────────────────────────────

class PartialAndUnknownTests(TestCase):
    def setUp(self):
        self.user = _user("pv_partial")
        self.pf = _book(self.user)
        self.cash = float(self.pf.cash_available)

    def test_nothing_priced_is_none_and_never_cash_only(self):
        """An unpriced book is unknown, not flat. Printing cash alone would
        claim the exposure had gone away."""
        _trade(self.user, "NOQUOTE", qty="5", entry="100")
        book = _value(self.user, self.pf)
        self.assertIsNone(book.value)
        self.assertIsNone(book.marked)
        self.assertIsNone(book.unrealized)
        self.assertNotEqual(book.value, self.cash)
        self.assertEqual(book.n_open, 1)
        self.assertEqual(book.n_unpriced, 1)
        self.assertIn("none with a live quote", book.coverage)

    def test_an_unpriced_row_is_left_out_and_not_valued_at_entry(self):
        """Entry cost inside a figure labelled "current value" is a price
        claim nobody made. The row is dropped and the total says so."""
        _quote("BTCUSD", "110")
        _trade(self.user, "BTCUSD", qty="2", entry="100")
        _trade(self.user, "NOQUOTE", qty="9", entry="1000")  # 9,000 at entry

        book = _value(self.user, self.pf)
        self.assertAlmostEqual(book.marked, 220.0, places=2)
        # The priced row is paper, so it adds its P&L of 20 and not its 220
        # of notional. The unpriced row adds nothing either way — which is
        # the point: 9,000 of entry cost stays out of a "current value".
        self.assertAlmostEqual(book.value, self.cash + 20.0, places=2)
        self.assertTrue(book.partial)
        self.assertEqual(book.n_open, 2)
        self.assertEqual(book.n_priced, 1)
        self.assertEqual(book.n_unpriced, 1)
        self.assertIn("1 of 2", book.coverage)

    def test_an_empty_book_is_measured_and_not_unknown(self):
        """Nothing open is a measurement of zero deployed."""
        book = _value(self.user, self.pf)
        self.assertAlmostEqual(book.value, self.cash, places=2)
        self.assertEqual(book.marked, 0.0)
        self.assertFalse(book.partial)
        self.assertEqual(book.n_unpriced, 0)
        self.assertEqual(book.coverage, "Nothing open in either book.")

    def test_an_option_row_has_no_premium_feed_and_stays_out(self):
        """Options store the UNDERLYING in symbol and the PREMIUM in entry
        price. Joining the underlying's quote books fictitious value."""
        _quote("AAPL", "220", asset_class="stock")
        _trade(self.user, "AAPL", qty="1", entry="3.20",
               config=_config(self.user, name="opt", asset_class="options"),
               metadata={"multiplier": 100})
        book = _value(self.user, self.pf)
        self.assertEqual(book.n_priced, 0)
        self.assertIsNone(book.value)

    def test_exposure_and_cash_shares_are_none_when_nothing_is_priced(self):
        """"100% cash" over an unpriced book is a claim of no exposure at
        all — the opposite of what an unpriced book means."""
        _trade(self.user, "NOQUOTE", qty="5")
        book = _value(self.user, self.pf)
        self.assertIsNone(book.exposure_pct)
        self.assertIsNone(book.cash_pct)

    def test_shares_are_measured_on_a_priced_book(self):
        """On a FUNDED book the two shares complement: the money is either
        sitting in cash or committed to a position, and cash + marked is
        the whole book."""
        _quote("AAPL", "100", asset_class="stock")
        _position(self.pf, "AAPL", qty="100", entry="100", current="100")
        book = _value(self.user, self.pf)
        self.assertAlmostEqual(book.exposure_pct + book.cash_pct, 100.0,
                               places=6)
        self.assertGreater(book.exposure_pct, 0)

    def test_a_paper_book_does_not_pretend_its_cash_was_spent(self):
        """And on a PAPER book they deliberately do not complement. Nothing
        was taken out of the cash column to open the position, so the cash
        really is untouched AND the notional really is at risk. Forcing the
        two to add to 100 would mean inventing one of them — either a cash
        debit that never happened, or exposure the operator does not have."""
        _quote("BTCUSD", "100")
        _trade(self.user, "BTCUSD", qty="100", entry="100")   # 10,000 deployed
        book = _value(self.user, self.pf)
        self.assertAlmostEqual(book.cash_pct, 100.0, places=6)
        self.assertAlmostEqual(book.exposure_pct, 100.0, places=6)
        self.assertAlmostEqual(book.value, self.cash, places=2)


# ── 3. The stored column stops being a lie ───────────────────────────────

class StoredColumnTests(TestCase):
    """`Portfolio.current_value` is KEPT and made true rather than retired:
    portfolio.risk_gate scales max daily loss, max total exposure and max
    single position as percentages OF it, and unlike a dashboard cell a
    mis-scaled gate shows nobody anything."""

    def setUp(self):
        self.user = _user("pv_stored")
        self.pf = _book(self.user)
        self.cash = float(self.pf.cash_available)

    def test_a_bot_only_book_is_revalued(self):
        """The operator's exact report: a per-user book holding nothing but
        bot trades, whose stored value was written once at creation."""
        _quote("BTCUSD", "110")
        _trade(self.user, "BTCUSD", qty="4", entry="100")
        _run_exposure()
        self.pf.refresh_from_db()
        # +40 of P&L on a paper trade, not its 440 of notional: the cash
        # column it would have been funded from was never debited.
        self.assertAlmostEqual(float(self.pf.current_value),
                               self.cash + 40.0, places=2)

    def test_the_legacy_book_is_valued_exactly_as_before(self):
        main = _book()
        _quote("AAPL", "110", asset_class="stock")
        _position(main, "AAPL", qty="5", entry="100")
        out = _run_exposure()
        main.refresh_from_db()
        self.assertEqual(out["marked"], 1)
        self.assertAlmostEqual(out["exposure_by_asset_class"]["stock"], 550.0,
                               places=1)
        self.assertAlmostEqual(float(main.current_value),
                               float(main.cash_available) + 550.0, places=2)

    def test_the_shared_book_is_not_fed_someone_elses_bot_trades(self):
        """"Main" has no owner, so no user's trades belong to it. Folding
        them in would inflate the denominator every risk limit is a
        percentage of."""
        _quote("BTCUSD", "110")
        _trade(self.user, "BTCUSD", qty="4", entry="100")
        _run_exposure()
        main = _book()
        main.refresh_from_db()
        self.assertAlmostEqual(float(main.current_value),
                               float(main.cash_available), places=2)

    def test_it_refuses_to_overwrite_a_book_it_could_not_price(self):
        """Writing cash-only would tell risk_gate the exposure went away, and
        a risk denominator must never shrink by accident."""
        self.pf.current_value = Decimal("7777.00")
        self.pf.save(update_fields=["current_value"])
        _trade(self.user, "NOQUOTE", qty="5", entry="100")

        _run_exposure()
        self.pf.refresh_from_db()
        self.assertEqual(self.pf.current_value, Decimal("7777.00"))

    def test_the_run_reports_which_books_it_could_not_write(self):
        _trade(self.user, "NOQUOTE", qty="5", entry="100")
        out = _run_exposure()
        mine = [b for b in out["books"] if b["portfolio_id"] == self.pf.pk]
        self.assertEqual(len(mine), 1)
        self.assertFalse(mine[0]["value_written"])
        self.assertEqual(mine[0]["unpriced"], 1)

    def test_the_first_run_ever_still_survives_creating_the_portfolio(self):
        """Settings hand initial_capital over as a float, and a fresh instance
        keeps its given types until reloaded — float + Decimal is how the very
        first exposure run on a fresh deploy died once already."""
        from portfolio.models import Portfolio
        Portfolio.objects.all().delete()
        self.assertFalse(Portfolio.objects.exists())
        self.assertEqual(_run_exposure()["status"], "ok")

    def test_the_breakdowns_add_up_to_the_total_beside_them(self):
        _quote("BTCUSD", "110")
        _trade(self.user, "BTCUSD", qty="4", entry="100")
        _quote("AAPL", "120", asset_class="stock")
        _position(self.pf, "AAPL", qty="2", entry="100")

        from portfolio.tasks import value_and_exposure
        book, by_class, _by_sector, _by_currency = value_and_exposure(self.pf)
        self.assertAlmostEqual(sum(by_class.values()), book.marked, places=2)


# ── 4. Snapshots follow the same book ────────────────────────────────────

class SnapshotTests(TestCase):
    def setUp(self):
        self.user = _user("pv_snap")
        self.pf = _book(self.user)
        self.cash = float(self.pf.cash_available)

    def test_the_per_user_book_gets_a_snapshot_at_all(self):
        """It only ever snapshotted the shared book, so the equity curve, the
        day change and the drawdown watermark on the operator's own account
        had no series to be computed from."""
        from portfolio.models import PortfolioSnapshot
        _quote("BTCUSD", "110")
        _trade(self.user, "BTCUSD", qty="4", entry="100")
        _run_snapshot()
        snap = PortfolioSnapshot.objects.get(portfolio=self.pf,
                                             date=timezone.now().date())
        self.assertAlmostEqual(float(snap.total_value), self.cash + 40.0,
                               places=2)

    def test_no_snapshot_is_written_for_a_book_nothing_could_price(self):
        """total_value is a non-null column, so the only way to record
        "unknown" is to record nothing — a cash-only point would book a
        fictitious daily loss the size of the whole open book."""
        from portfolio.models import PortfolioSnapshot
        _trade(self.user, "NOQUOTE", qty="5", entry="100")
        out = _run_snapshot()
        self.assertFalse(
            PortfolioSnapshot.objects.filter(portfolio=self.pf).exists())
        self.assertIn(self.pf.name, out["skipped"])


# ── 5. Ownership: the only link between a book and a person ──────────────

class PortfolioOwnerTests(TestCase):
    def test_a_per_user_book_resolves_to_its_user(self):
        from portfolio.services import portfolio_owner
        user = _user("pv_owner")
        self.assertEqual(portfolio_owner(_book(user)), user)

    def test_the_shared_book_has_no_owner(self):
        from portfolio.services import portfolio_owner
        self.assertIsNone(portfolio_owner(_book()))

    def test_a_username_containing_the_suffix_still_round_trips(self):
        """"alice_main" gets the book "alice_main_main", so stripping one
        suffix lands back on the username and not on "alice"."""
        from portfolio.services import portfolio_owner
        user = _user("alice_main")
        self.assertEqual(portfolio_owner(_book(user)), user)

    def test_an_unowned_book_is_valued_from_the_legacy_half_alone(self):
        from portfolio.services import unified_open_positions
        user = _user("pv_unowned")
        _quote("BTCUSD", "110")
        _trade(user, "BTCUSD", qty="4")
        main = _book()
        _position(main, "AAPL", qty="2")
        rows = unified_open_positions(None, main)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].instrument.symbol, "AAPL")


# ── 6. Every surface renders that one number ─────────────────────────────

class SurfacesAgreeTests(TestCase):
    def setUp(self):
        self.user = _user("pv_surface")
        self.pf = _book(self.user)
        self.cash = float(self.pf.cash_available)
        _quote("BTCUSD", "110")
        _trade(self.user, "BTCUSD", qty="4", entry="100")
        self.expected = self.cash + 40.0
        self.client.force_login(self.user)

    def test_the_headband_cell(self):
        from core.context_processors import _book_truth
        out = _book_truth(self.user, self.pf)
        self.assertEqual(out["panel_portfolio_value"], f"{self.expected:,.0f}")
        self.assertEqual(out["panel_deployed"], "440")

    def test_the_headband_cell_is_not_the_stored_column(self):
        """The column is what froze. If the cell ever reads it again this
        fails, because the task that writes it has not run in this test."""
        from core.context_processors import _book_truth
        out = _book_truth(self.user, self.pf)
        self.assertNotEqual(
            out["panel_portfolio_value"],
            f"{float(self.pf.current_value):,.0f}")

    def test_the_op_center_tab_head(self):
        from dashboard.views_command import _tab_bar_metrics
        metric = _tab_bar_metrics(self.user)["portfolio"]
        self.assertIn(f"{self.expected:,.0f}", metric["primary"])
        self.assertNotEqual(metric["primary"], DASH)

    def test_the_op_center_hero(self):
        from dashboard.views_command import _hero_metrics
        self.assertEqual(_hero_metrics(self.user)["value"],
                         f"{self.expected:,.2f}")

    def test_the_portfolio_page_strip(self):
        body = self.client.get("/portfolio/", HTTP_HOST=HOST).content.decode()
        self.assertIn(f"{self.expected:,.2f}", body)

    def test_the_headband_and_the_op_center_quote_one_number(self):
        from core.context_processors import _book_truth
        from dashboard.views_command import _hero_metrics
        band = _book_truth(self.user, self.pf)["panel_portfolio_value"]
        hero = _hero_metrics(self.user)["value"]
        self.assertEqual(float(band.replace(",", "")),
                         round(float(hero.replace(",", "")), 0))

    def test_an_unpriced_row_makes_the_surfaces_say_partial(self):
        from core.context_processors import _book_truth
        _trade(self.user, "NOQUOTE", qty="9", entry="1000")
        out = _book_truth(self.user, self.pf)
        self.assertTrue(out["panel_value_partial"])
        self.assertEqual(out["panel_positions_unpriced"], 1)
        self.assertIn("1 of 2", out["panel_book_coverage"])
        body = self.client.get("/portfolio/", HTTP_HOST=HOST).content.decode()
        self.assertIn("are not in these", body)

    def test_the_pdf_report_prints_the_measured_book(self):
        try:
            import reportlab  # noqa: F401
        except ImportError:
            self.skipTest("reportlab is not installed in this environment")
        r = self.client.get("/reports/portfolio/", HTTP_HOST=HOST)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "application/pdf")
