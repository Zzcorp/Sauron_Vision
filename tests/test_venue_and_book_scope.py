"""What the book-level risk gates measure: whose money, and which book.

Three ways the /setup/ Risk Limits card was reading the wrong quantity while
looking entirely healthy.

  * VENUE. `paper` is not a property of a config an operator can reason about
    from the outside — a LIVE config runs its paper-stage rules on the paper
    venue at full nominal size, and every hand-taken TAKE TRADE is paper
    today — so one book carries both at once. The gates added them. A day
    that lost 2,400 of real money while simulated rules booked +2,600
    reported +200 realized, the card read green, and every bot kept opening
    while the real account fell. Simulated open positions ate the real
    MAX TOTAL EXPOSURE ceiling the same way, from the other side.

  * BOOK. The money gates scanned the shared "Main" row alone. /setup/ now
    creates hand-added positions on `<username>_main` (they belong to the
    operator), so the four positions someone records on that form — the
    form's stated purpose — were charged against nothing. "0.00 committed
    across 0 position(s)" to an operator who had just entered 85,000 of
    holdings, and then clearance for a bookful more on top.

  * CANDIDATE. `exposure_state` asked "am I already over?" and never "would
    this put me over?", so the ceiling could only refuse the entry AFTER the
    one that breached it — committed 99,500 of a 100,000 ceiling reads as
    headroom, and the next position takes the book to 119.5% with nothing
    having refused anything.

Plus the chat trader, which read `max_single_position_pct` off the per-user
book — a field nothing on this platform ever writes, so it enforced the
model's factory 20% however the operator had set the card.

Run with:  python manage.py test tests.test_venue_and_book_scope
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone


def _instrument(symbol="AAPL", asset_class="stock"):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class,
                                 "is_active": True})
    return inst


def _quote(symbol, last, asset_class="stock"):
    from market_data.models import LiveQuote
    inst = _instrument(symbol, asset_class)
    LiveQuote.objects.update_or_create(
        instrument=inst, defaults={"last": Decimal(str(last)),
                                   "source": "test"})
    return inst


def _book(**limits):
    """The shared row the /setup/ Risk Limits card writes to."""
    from portfolio.risk_gate import limits_book
    pf = limits_book()
    for field, value in limits.items():
        setattr(pf, field, value)
    pf.save()
    return pf


def _own_book(user, **fields):
    """`<username>_main` — where /setup/ puts a hand-added position and where
    the chat trader books."""
    from portfolio.services import get_or_create_default_portfolio
    pf = get_or_create_default_portfolio(user=user)
    for field, value in fields.items():
        setattr(pf, field, value)
    if fields:
        pf.save()
    return pf


def _config(user, asset_class="crypto", name="t", mode="paper"):
    from bot_program.models import AssetBotConfig
    return AssetBotConfig.objects.create(
        user=user, asset_class=asset_class, name=name, enabled=True,
        mode=mode, symbols=[], capital=Decimal("10000"))


def _closed(cfg, pnl, *, paper, hours_ago=1, symbol="BTCUSD"):
    from bot_program.models import AssetBotTrade
    t = AssetBotTrade.objects.create(
        config=cfg, asset_class=cfg.asset_class, symbol=symbol, side="BUY",
        qty=Decimal("1"), entry_price=Decimal("100"), exit_price=Decimal("90"),
        status="CLOSED", pnl=Decimal(str(pnl)), paper=paper)
    t.closed_at = timezone.now() - timedelta(hours=hours_ago)
    t.save(update_fields=["closed_at"])
    return t


def _open(cfg, *, paper, entry="100", qty="1", symbol="BTCUSD"):
    from bot_program.models import AssetBotTrade
    return AssetBotTrade.objects.create(
        config=cfg, asset_class=cfg.asset_class, symbol=symbol, side="BUY",
        qty=Decimal(qty), entry_price=Decimal(entry), status="OPEN",
        paper=paper, metadata={})


def _position(portfolio, symbol, *, qty, entry, asset_class="stock",
              direction="long", closed_hours_ago=None, exit_price=None):
    from portfolio.models import Position
    pos = Position.objects.create(
        portfolio=portfolio, instrument=_instrument(symbol, asset_class),
        direction=direction, quantity=Decimal(str(qty)),
        entry_price=Decimal(str(entry)),
        current_price=Decimal(str(exit_price if exit_price is not None
                                  else entry)),
        opened_at=timezone.now() - timedelta(days=3))
    if closed_hours_ago is not None:
        pos.closed_at = timezone.now() - timedelta(hours=closed_hours_ago)
        pos.save(update_fields=["closed_at"])
    return pos


class DailyLossVenueTests(TestCase):
    """MAX DAILY LOSS across a book that carries both venues at once."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("venue_dl",
                                                        password="x")

    def setUp(self):
        _book(current_value=Decimal("100000"), max_daily_loss_pct=3.0)
        self.cfg = _config(self.user)

    def test_a_simulated_profit_cannot_pay_for_a_real_loss(self):
        """The failure exactly as it read: -2,400 of real money, +2,600 of
        simulated, and a card reporting +200 against a -3,000 floor while the
        real account fell."""
        from portfolio.risk_gate import daily_loss_state
        _closed(self.cfg, -2400, paper=False)
        _closed(self.cfg, 2600, paper=True)
        state = daily_loss_state(self.user)
        self.assertEqual(state["realized"], -2400.0)
        self.assertEqual(state["live_realized"], -2400.0)
        self.assertEqual(state["paper_realized"], 2600.0)
        # And the operator can see both, so "my money is gone" and "my
        # simulation is" are not the same sentence.
        self.assertIn("live -2,400.00", state["reason"])
        self.assertIn("paper 2,600.00", state["reason"])

    def test_the_floor_then_fires_on_the_real_loss_alone(self):
        """The consequence of the netting was not a wrong number on a card:
        it was a gate that never fired."""
        from portfolio.risk_gate import daily_loss_state, preflight
        _closed(self.cfg, -3100, paper=False)
        _closed(self.cfg, 5000, paper=True)
        state = daily_loss_state(self.user)
        self.assertFalse(state["ok"])
        self.assertIn("daily loss limit hit", state["reason"])
        self.assertFalse(preflight(self.user)["ok"])

    def test_a_paper_venue_loss_still_stops_the_paper_venue(self):
        """TAKE TRADE writes paper rows today, so a gate that simply ignored
        the paper venue would hand the manual lane back the unlimited losing
        day this card was built to end."""
        from portfolio.risk_gate import daily_loss_state
        _closed(self.cfg, -3500, paper=True)
        state = daily_loss_state(self.user)
        self.assertFalse(state["ok"])
        self.assertEqual(state["realized"], -3500.0)

    def test_two_venues_inside_the_floor_are_not_added_into_a_breach(self):
        """-2,000 live and -2,000 paper is not a -4,000 day: the book only
        lost the live 2,000, and charging it twice would halt a fleet that is
        inside its limit."""
        from portfolio.risk_gate import daily_loss_state
        _closed(self.cfg, -2000, paper=False)
        _closed(self.cfg, -2000, paper=True)
        state = daily_loss_state(self.user)
        self.assertTrue(state["ok"], state["reason"])
        self.assertEqual(state["realized"], -2000.0)

    def test_a_profitable_live_day_is_not_reported_as_flat(self):
        """A venue with nothing closed in it is not a 0.00 the other has to be
        compared against — otherwise a +500 day reads as a scratch."""
        from portfolio.risk_gate import realized_since
        _closed(self.cfg, 500, paper=False)
        self.assertEqual(realized_since(self.user)["realized"], 500.0)


class ExposureVenueTests(TestCase):
    """MAX TOTAL EXPOSURE — the same split, from the other side."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("venue_ex",
                                                        password="x")

    def setUp(self):
        _book(current_value=Decimal("10000"), max_total_exposure_pct=50.0)
        self.cfg = _config(self.user)

    def test_simulated_positions_do_not_consume_the_live_ceiling(self):
        """Four simulated positions plus two real ones summed past a ceiling
        that exists to bound real money, and the live entry behind them was
        refused by capital nobody had committed."""
        from portfolio.risk_gate import exposure_state
        _open(self.cfg, paper=True, entry="1000", qty="4")   # 4,000 simulated
        _open(self.cfg, paper=False, entry="1000", qty="2")  # 2,000 real
        state = exposure_state(self.user)
        self.assertTrue(state["ok"], state["reason"])
        self.assertEqual(state["live_committed"], 2000.0)
        self.assertEqual(state["paper_committed"], 4000.0)

    def test_a_full_paper_book_still_refuses_and_says_which_book(self):
        from portfolio.risk_gate import exposure_state
        _open(self.cfg, paper=True, entry="1000", qty="6")
        state = exposure_state(self.user)
        self.assertFalse(state["ok"])
        self.assertIn("paper 6,000.00", state["reason"])


class CandidateExposureTests(TestCase):
    """"Would this put me over?" — the question the ceiling never asked."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("venue_cand",
                                                        password="x")

    def setUp(self):
        _book(current_value=Decimal("100000"), max_total_exposure_pct=100.0)
        self.cfg = _config(self.user)
        _open(self.cfg, paper=False, entry="1000", qty="99.5")  # 99,500

    def test_a_ticket_that_would_breach_the_ceiling_is_refused(self):
        """99,500 committed of a 100,000 ceiling reads as headroom, and the
        20%-of-pool position that followed took the book to 119.5% of a limit
        the operator set to 100%."""
        from portfolio.risk_gate import exposure_state
        self.assertTrue(exposure_state(self.user)["ok"])
        state = exposure_state(self.user, adding=20000.0)
        self.assertFalse(state["ok"])
        self.assertIn("this one adds 20,000.00", state["reason"])

    def test_a_ticket_that_fits_inside_the_headroom_is_not(self):
        """The candidate check must not become a second, tighter ceiling."""
        from portfolio.risk_gate import exposure_state
        self.assertTrue(exposure_state(self.user, adding=400.0)["ok"])

    def test_preflight_carries_the_candidate_through(self):
        """So the caller that knows the size has one call to make, not two."""
        from portfolio.risk_gate import preflight
        self.assertTrue(preflight(self.user)["ok"])
        self.assertFalse(preflight(self.user, adding=20000.0)["ok"])


class BookScopeTests(TestCase):
    """A position the operator entered on /setup/ lands on their OWN book."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("venue_bk",
                                                        password="x")

    def setUp(self):
        _book(current_value=Decimal("100000"), max_total_exposure_pct=100.0,
              max_single_position_pct=20.0, max_daily_loss_pct=3.0)
        self.own = _own_book(self.user, current_value=Decimal("100000"))

    def test_positions_recorded_on_setup_are_charged_against_the_ceiling(self):
        """Four holdings totalling 85,000 entered on the form whose stated
        purpose is recording them — and a gate that answered "0.00 committed
        across 0 position(s)" and cleared a further bookful on top."""
        from portfolio.risk_gate import exposure_state
        for i, symbol in enumerate(("AAPL", "MSFT", "NVDA", "TSLA")):
            _position(self.own, symbol, qty=1000, entry=21.25)
        state = exposure_state(self.user)
        self.assertEqual(state["committed"], 85000.0)
        self.assertEqual(state["n_open"], 4)

    def test_they_reach_the_concentration_peer_set_too(self):
        """The same rows were invisible to the ceiling on one bet, so the
        operator's own 85,000 in one name counted as nothing held."""
        from portfolio.risk_gate import symbol_side_exposure
        _position(self.own, "AAPL", qty=100, entry=200)
        held = symbol_side_exposure(self.user, "AAPL", "BUY")
        self.assertEqual(held["n"], 1)
        self.assertEqual(held["committed"], 20000.0)

    def test_a_close_on_the_users_own_book_reaches_the_daily_loss_window(self):
        """Both paths that close a Position work on this book. While the gate
        read the shared row alone, their closes landed nowhere it looked."""
        from portfolio.risk_gate import realized_since
        _position(self.own, "MSFT", qty=100, entry=200, exit_price=185,
                  closed_hours_ago=2)
        window = realized_since(self.user)
        self.assertEqual(window["realized"], -1500.0)

    def test_the_shared_book_is_still_counted(self):
        """Widening the scan must not swap one blind spot for another — the
        eToro sync still writes to the shared row."""
        from portfolio.risk_gate import exposure_state, limits_book
        _position(limits_book(), "NVDA", qty=100, entry=300)
        self.assertEqual(exposure_state(self.user)["committed"], 30000.0)


class ChatTraderLimitTests(TestCase):
    """The chat lane checked a percentage nobody had ever set."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("venue_nl",
                                                        password="x")

    def setUp(self):
        self.inst = _quote("AAPL", 200)
        _own_book(self.user, current_value=Decimal("100000"))

    def _buy(self, quantity=300):
        from bot_program.nl_trader import NLTradeParser
        return NLTradeParser().execute(
            {"action": "buy", "symbol": "AAPL", "quantity": quantity,
             "confidence": 0.9}, self.user)

    def test_tightening_the_card_reaches_the_chat_trader(self):
        """5% of a 100,000 book is 5,000. The order is 60,000 — and it used to
        be waved through against the model's untouched 20% default."""
        from portfolio.models import Position
        _book(current_value=Decimal("100000"), max_single_position_pct=5.0)
        out = self._buy()
        self.assertEqual(out["status"], "error")
        self.assertIn("single position may hold", out["message"])
        self.assertFalse(Position.objects.filter(
            instrument=self.inst, closed_at__isnull=True).exists())

    def test_loosening_it_reaches_the_chat_trader_as_well(self):
        """Not a gate that only ever says no: the card moves this path in both
        directions, which is what it never did before."""
        _book(current_value=Decimal("100000"), max_single_position_pct=100.0)
        self.assertEqual(self._buy()["status"], "executed")

    def test_the_refusal_carries_the_arithmetic(self):
        """Same as every other refusal on this platform — the operator cannot
        tell whether to size down or move the limit without both numbers."""
        _book(current_value=Decimal("100000"), max_single_position_pct=5.0)
        message = self._buy()["message"]
        self.assertIn("60,000.00", message)
        self.assertIn("5,000.00", message)
