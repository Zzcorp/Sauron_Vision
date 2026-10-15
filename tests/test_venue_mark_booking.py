"""BOOKING IS STRICTER THAN SHOWING, re-checked (2026-10-15).

Two adversarial re-checks of PR53 (the venue mark: a real Gold Spot row was
valued at the gold future) confirmed that its hand-written fixes left a
real-money defect and several smaller ones. What is pinned here:

  * THE VERDICT STAYS OUT OF THE ROW UNTIL THE CLOSED BOOKING (C1). The
    kill switch wrote `exit_price_unavailable` into the row's metadata in
    memory before any order was sent; every later save persisted it,
    including the CLOSE_PENDING save eToro's unproven close (PENDING,
    executedQty 0.0) lands on, and nothing that later PRICED the row
    cleared it. The drain then booked a real loss WITH the flag, and the
    book's daily stop (portfolio.risk_gate.realized_since) skipped it as
    unmeasured. Now the kill switch's mark read returns its verdict, the
    CLOSED booking decides per fill, every priced booking pops a leftover
    flag and age, and the flag never reaches a CLOSE_PENDING save.
  * THE SHUT MARKET IS THE VENUE'S OWN CLOCK (C2): a stale print books
    over a shut market only when it was taken within BOOK_BEFORE_SHUT_S of
    the close (the venue's price AT the close), never in the settle window
    after an open, and an index CFD timed by its cash index is never
    "shut" for this purpose.
  * A QUOTE books only while fresh (C3), and a stale quote never hides a
    bookable venue print.
  * A VENUE_STALE mark decides nothing in an open market (C4): the
    position review (the thesis stop Aragorn applies) and the level editor
    use it only while the market is shut; the pages keep showing it.
  * A sideless print carries the last measured half-spread forward (C5);
    the bot entry, the working fill and the close dialog stamp their
    sides; TAKE TRADE's spread is anchored at the fill.
  * exit_mark_age_s rides only a booking a STALE print priced (C6); a real
    options row with no premium is flagged unpriced (C7); eToro's "0" for a
    shut market falls into the booking rule (C8); the instrument page's
    panel shows the mark word with its age (C9).
  * The tests dimension (T): the source-text pins became behaviour tests.

A SECOND RE-CHECK of those fixes (2026-10-15) found what they left:
  * the entry standing in for a real row's exit is marked where it is
    chosen — the units the kill switch finds already filled at the venue
    (priced at the switch's own mark, never by asking the ticker that just
    failed), the drain's resend with no mark — and every CLOSED booking
    (the kill switch, the drain's finaliser, the reconcile's orphan close,
    which now blends the residual with the ledger) asks one per-fill rule,
    pending_closes.booking_unpriced;
  * the kill switch's CLOSE_PENDING save is written under the row lock with
    a status check, onto the row's current metadata, and a row another
    close holds (its claim) is left to it;
  * a shut market books no older print than the open market would
    (BOOK_BEFORE_SHUT_S = BOOK_STALE_MAX_S), the deciding readers take only
    the print at the close (venue_mark.at_the_close), an index CFD keeps
    its venue's week, the level editor judges a quote only while live, and
    an exit at a stale quote records its age;
  * a working fill dates the order-time spread from its read, TAKE TRADE's
    working order keeps the ticket's sides, and every fill lane's SHORT
    side is pinned.

Run with:  python manage.py test tests.test_venue_mark_booking
"""
from datetime import datetime, timedelta, timezone as dt_tz
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from tests.test_venue_mark_birth import (FUTURE, ROUTER, SPOT_FILL, _cfg,
                                         _gold, _instrument, _quote, _stamp)

SHUT = "bot_program.venue_mark.market_shut"


def _utc(*parts):
    return datetime(*parts, tzinfo=dt_tz.utc)


def _open_market():
    """The row's market reads OPEN by the venue's own clock."""
    return mock.patch(SHUT, return_value=None)


def _shut_market(closed=None):
    """The row's market reads SHUT; `closed` is when the shut began
    (default: two and a half hours before now, so a three-hour print was
    taken half an hour before the close — inside BOOK_BEFORE_SHUT_S)."""
    closed = closed or (timezone.now() - timedelta(hours=2, minutes=30))
    return mock.patch(SHUT, return_value={"closed": closed, "reopens": None})


class _EtoroDown:
    """eToro while its rates fail: the ticker raises; a close is ACCEPTED
    and unproven — status PENDING, executedQty "0.0", the measured shape
    (etoro_client.close_position) — so the row lands CLOSE_PENDING."""
    PORTFOLIO_LAG_S = 0

    def __init__(self, answer=None):
        self.answer = answer or {"orderId": "c1", "status": "PENDING",
                                 "executedQty": "0.0"}
        self.sent = []

    def ticker(self, symbol):
        raise RuntimeError("eToro: rates unavailable")

    def market_order(self, *a, **k):
        self.sent.append((a, k))
        return self.answer

    def cancel_order(self, oid):
        return True


class _EtoroPriced(_EtoroDown):
    """eToro answering its rate; the close FILLED for the units asked and,
    as measured, with no avgPrice — the exit books at the engine's mark.
    `held` (a list) makes the client list its positions; without it the
    book cannot be read, so the kill switch sends its close."""

    def __init__(self, last="2600", answer=None, held=None):
        super().__init__(answer or {"orderId": "c2", "status": "FILLED",
                                    "executedQty": "1"})
        self.last = last
        if held is not None:
            self.get_positions = lambda: list(held)

    def ticker(self, symbol):
        return {"lastPrice": self.last, "bid": str(float(self.last) - 0.1),
                "ask": str(float(self.last) + 0.1)}


def _realized(user):
    from portfolio.risk_gate import realized_since
    from portfolio.services import get_or_create_default_portfolio
    return realized_since(user, get_or_create_default_portfolio(user=user))


class TheVerdictStaysOutOfTheRowTests(TestCase):
    """C1. The realistic eToro path, reproduced first and kept."""

    def setUp(self):
        self.user = get_user_model().objects.create_user("vmk_c1",
                                                         password="x")
        self.cfg = _cfg(self.user)
        _instrument("XAUUSD", "commodity", "Gold Spot")
        _quote("XAUUSD", FUTURE, asset_class="commodity")

    def _kill(self, trade, client):
        from bot_program.engine.kill_switch import _close_asset_trade
        with mock.patch(ROUTER, return_value=client), _open_market():
            return _close_asset_trade(trade, timezone.now())

    def _drain(self, trade, client):
        from bot_program.pending_closes import retry_trade_close
        with mock.patch(ROUTER, return_value=client):
            return retry_trade_close(trade)

    def test_pending_then_drain_books_the_loss_the_daily_stop_can_see(self):
        """A kill switch while eToro's rates fail (the three-hour print is
        not bookable in an open market), eToro answers PENDING/0.0: the
        row goes CLOSE_PENDING with NO flag. The drain proves the close at
        the ticker's price: CLOSED, pnl -50, no flag, and realized_since
        counts it among the live closes."""
        from bot_program.models import AssetBotTrade
        from bot_program.reconcile_asset import UNPRICED_EXIT_KEY
        t = _gold(self.cfg, meta=_stamp("2649.75", age_s=3 * 3600))
        with self.assertRaises(RuntimeError):
            self._kill(t, _EtoroDown())
        t = AssetBotTrade.objects.get(pk=t.pk)
        self.assertEqual(t.status, "CLOSE_PENDING")
        self.assertNotIn(UNPRICED_EXIT_KEY, t.metadata,
                         "the flag never reaches a CLOSE_PENDING save")
        self.assertNotIn("exit_mark_age_s", t.metadata)
        self.assertTrue(self._drain(t, _EtoroPriced("2600", held=[])))
        t = AssetBotTrade.objects.get(pk=t.pk)
        self.assertEqual(t.status, "CLOSED")
        self.assertEqual(t.exit_price, Decimal("2600"))
        self.assertEqual(t.pnl, Decimal("-50"))
        self.assertNotIn(UNPRICED_EXIT_KEY, t.metadata)
        r = _realized(self.user)
        self.assertEqual((r["live_n"], r["unmeasured"]), (1, 0))
        self.assertAlmostEqual(r["live_realized"], -50.0, places=2)

    def test_a_second_kill_switch_prices_a_row_the_first_one_flagged(self):
        """A CLOSE_PENDING row carrying the flag main's code wrote; the
        second press reads a live ticker and eToro fills without a price:
        CLOSED at 2600 with pnl -50, the leftover flag gone."""
        from bot_program.models import AssetBotTrade
        from bot_program.reconcile_asset import UNPRICED_EXIT_KEY
        t = _gold(self.cfg, status="CLOSE_PENDING",
                  meta={UNPRICED_EXIT_KEY: True, "exit_mark_age_s": 7200})
        self._kill(t, _EtoroPriced("2600"))
        t = AssetBotTrade.objects.get(pk=t.pk)
        self.assertEqual(t.status, "CLOSED")
        self.assertEqual(float(t.exit_price), 2600.0)
        self.assertEqual(t.pnl, Decimal("-50"))
        self.assertNotIn(UNPRICED_EXIT_KEY, t.metadata)
        self.assertNotIn("exit_mark_age_s", t.metadata)

    def test_partial_then_retry_books_a_measured_blend_with_no_flag(self):
        """Nothing priced the mark, but the broker's own fill priced the six
        it filled: CLOSE_PENDING without the flag; the retry fills the four
        at 2590 and the blend is a measured exit."""
        from bot_program.models import AssetBotTrade
        from bot_program.reconcile_asset import UNPRICED_EXIT_KEY
        t = _gold(self.cfg, qty="10")
        first = _EtoroDown({"orderId": "c1", "status": "FILLED",
                            "executedQty": "6", "avgPrice": "2600"})
        with self.assertRaises(RuntimeError):
            self._kill(t, first)
        t = AssetBotTrade.objects.get(pk=t.pk)
        self.assertEqual(t.status, "CLOSE_PENDING")
        self.assertNotIn(UNPRICED_EXIT_KEY, t.metadata)
        second = _EtoroPriced(
            "2590", answer={"orderId": "c2", "status": "FILLED",
                            "executedQty": "4", "avgPrice": "2590"},
            held=[{"symbol": "XAUUSD", "qty": 4.0, "side": "BUY"}])
        self.assertTrue(self._drain(t, second))
        t = AssetBotTrade.objects.get(pk=t.pk)
        self.assertEqual(t.status, "CLOSED")
        self.assertEqual(t.exit_price, Decimal("2596"))
        self.assertEqual(t.pnl, Decimal("-540"))
        self.assertNotIn(UNPRICED_EXIT_KEY, t.metadata)
        self.assertEqual(t.metadata["exit_fill_source"], "broker")

    def test_the_booking_rule_per_fill(self):
        """Nothing priced the mark and eToro filled WITHOUT a price: CLOSED,
        flagged, pnl None, the exit the entry's stand-in. The broker's own
        avgPrice on the same unpriced mark: a measured exit, no flag."""
        from bot_program.models import AssetBotTrade
        from bot_program.reconcile_asset import UNPRICED_EXIT_KEY
        bare = _gold(self.cfg)
        self._kill(bare, _EtoroDown({"orderId": "c1", "status": "FILLED",
                                     "executedQty": "1"}))
        bare = AssetBotTrade.objects.get(pk=bare.pk)
        self.assertEqual(bare.status, "CLOSED")
        self.assertTrue(bare.metadata.get(UNPRICED_EXIT_KEY))
        self.assertIsNone(bare.pnl)
        self.assertEqual(bare.exit_price, SPOT_FILL)
        self.assertNotIn("exit_mark_age_s", bare.metadata)
        self.assertTrue(bare.metadata["close_fills"][-1].get("unpriced"))
        priced = _gold(self.cfg)
        self._kill(priced, _EtoroDown({"orderId": "c1", "status": "FILLED",
                                       "executedQty": "1",
                                       "avgPrice": "2600"}))
        priced = AssetBotTrade.objects.get(pk=priced.pk)
        self.assertEqual(priced.pnl, Decimal("-50"))
        self.assertNotIn(UNPRICED_EXIT_KEY, priced.metadata)
        self.assertEqual(priced.metadata["exit_fill_source"], "broker")
        r = _realized(self.user)
        self.assertEqual((r["live_n"], r["unmeasured"]), (1, 1))

    def test_the_mark_read_writes_nothing_on_the_row(self):
        from bot_program.engine.kill_switch import _market_exit_price
        t = _gold(self.cfg, meta=_stamp("2610", age_s=16 * 60))
        bare = _gold(self.cfg)
        before, bare_before = dict(t.metadata), dict(bare.metadata)
        with _open_market():
            self.assertEqual(_market_exit_price("XAUUSD", t.entry_price,
                                                client=_EtoroDown(),
                                                trade=t),
                             (2610.0, False, 960))
            price, unpriced, age = _market_exit_price(
                "XAUUSD", bare.entry_price, client=_EtoroDown(), trade=bare)
        self.assertEqual((price, unpriced, age), (float(SPOT_FILL), True,
                                                  None))
        self.assertEqual(t.metadata, before)
        self.assertEqual(bare.metadata, bare_before)
        # a paper row and a call with no trade: a price, never a verdict
        paper = _gold(_cfg(self.user, name="p", mode="paper"), paper=True)
        self.assertEqual(_market_exit_price("XAUUSD", paper.entry_price,
                                            client=_EtoroDown(),
                                            trade=paper),
                         (float(FUTURE), False, None))
        self.assertEqual(_market_exit_price("XAUUSD", SPOT_FILL,
                                            client=_EtoroDown()),
                         (float(FUTURE), False, None))

    def test_the_closed_booking_is_written_under_the_row_lock(self):
        """A close that landed elsewhere while the switch was at the broker
        keeps its own words: the switch does not overwrite a CLOSED row."""
        from bot_program.models import AssetBotTrade
        t = _gold(self.cfg)

        class _ClosesMeanwhile(_EtoroPriced):
            def market_order(self_, *a, **k):
                AssetBotTrade.objects.filter(pk=t.pk).update(
                    status="CLOSED", exit_price=Decimal("2620"),
                    pnl=Decimal("-30"), closed_at=timezone.now())
                return super().market_order(*a, **k)

        self._kill(t, _ClosesMeanwhile("2600"))
        t = AssetBotTrade.objects.get(pk=t.pk)
        self.assertEqual((t.exit_price, t.pnl), (Decimal("2620"),
                                                 Decimal("-30")))


class EveryPricedBookingPopsALeftoverTests(TestCase):
    """C1's other writers: the drain's finaliser and the reconcile's orphan
    close drop a flag an earlier attempt left behind once they price."""

    def setUp(self):
        self.user = get_user_model().objects.create_user("vmk_pop",
                                                         password="x")
        self.cfg = _cfg(self.user)
        _instrument("XAUUSD", "commodity", "Gold Spot")
        _quote("XAUUSD", FUTURE, asset_class="commodity")

    def test_the_drains_finaliser(self):
        from bot_program.models import AssetBotTrade
        from bot_program.pending_closes import (_finalise_closed,
                                                resolve_exit_fill)
        from bot_program.reconcile_asset import UNPRICED_EXIT_KEY
        t = _gold(self.cfg, status="CLOSE_PENDING",
                  meta={UNPRICED_EXIT_KEY: True, "exit_mark_age_s": 7200})
        fill = resolve_exit_fill(t, None, mark=Decimal("2600"))
        _finalise_closed(t, fill=fill, reason="RETRY_VENUE_PROVED_CLOSED")
        t = AssetBotTrade.objects.get(pk=t.pk)
        self.assertEqual(t.pnl, Decimal("-50"))
        self.assertNotIn(UNPRICED_EXIT_KEY, t.metadata)
        self.assertNotIn("exit_mark_age_s", t.metadata)
        self.assertEqual(_realized(self.user)["live_n"], 1)

    def test_the_orphan_close_priced_by_the_brokers_fill(self):
        from bot_program.models import AssetBotTrade
        from bot_program.reconcile_asset import (UNPRICED_EXIT_KEY,
                                                 _close_as_orphan)
        t = _gold(self.cfg, status="CLOSE_PENDING",
                  meta={UNPRICED_EXIT_KEY: True, "exit_mark_age_s": 7200})
        c = mock.MagicMock(spec=["ticker", "closing_fill"])
        c.ticker.side_effect = RuntimeError("down")
        c.closing_fill.return_value = {"price": 2600.0, "qty": 1.0,
                                       "source": "alpaca:order:1"}
        with mock.patch(ROUTER, return_value=c):
            self.assertTrue(_close_as_orphan(t))
        t = AssetBotTrade.objects.get(pk=t.pk)
        self.assertEqual(t.pnl, Decimal("-50"))
        self.assertEqual(t.metadata["exit_fill_source"], "broker")
        self.assertNotIn(UNPRICED_EXIT_KEY, t.metadata)
        self.assertNotIn("exit_mark_age_s", t.metadata)

    def test_the_orphan_close_priced_by_the_ticker(self):
        from bot_program.models import AssetBotTrade
        from bot_program.reconcile_asset import (UNPRICED_EXIT_KEY,
                                                 _close_as_orphan)
        t = _gold(self.cfg, status="CLOSE_PENDING",
                  meta={UNPRICED_EXIT_KEY: True})
        c = mock.MagicMock(spec=["ticker"])
        c.ticker.return_value = {"lastPrice": "2600"}
        with mock.patch(ROUTER, return_value=c):
            self.assertTrue(_close_as_orphan(t))
        t = AssetBotTrade.objects.get(pk=t.pk)
        self.assertEqual(t.pnl, Decimal("-50"))
        self.assertNotIn(UNPRICED_EXIT_KEY, t.metadata)
        self.assertNotIn("exit_mark_age_s", t.metadata,
                         "a fresh ticker print carries no age")


def _stamp_at(price, at, **sides):
    out = {"price": float(price), "at": at.isoformat(), "source": "etoro",
           "via": "tick"}
    out.update(sides)
    return {"venue_mark": out}


class TheShutMarketIsTheVenuesClockTests(TestCase):
    """C2. `market_shut` reads the venue's own clock; a stale print books
    over a shut market only when it was taken at the close."""

    def setUp(self):
        self.user = get_user_model().objects.create_user("vmk_c2",
                                                         password="x")
        self.cfg = _cfg(self.user)
        _instrument("XAUUSD", "commodity", "Gold Spot")
        _instrument("EURUSD", "forex")
        _instrument("SPX500", "index")

    def _real(self, symbol, cls, meta):
        from bot_program.models import AssetBotTrade
        m = {"broker": "etoro", "initial_stop_loss": 1.0}
        m.update(meta)
        return AssetBotTrade.objects.create(
            config=self.cfg, asset_class=cls, symbol=symbol, side="BUY",
            qty=Decimal("1"), entry_price=Decimal("1"),
            stop_loss=Decimal("0.5"), status="OPEN", paper=False,
            rule_name="manual_take", metadata=m)

    def _bookable(self, trade, now):
        from bot_program import venue_mark
        mk = venue_mark.resolve(trade, None, now=now)
        self.assertEqual(mk.source, venue_mark.VENUE_STALE)
        return venue_mark.bookable(mk, trade, now=now)

    def test_the_clock_says_when_the_shut_began(self):
        from core.exchange_status import market_clock
        sat = _utc(2026, 10, 10, 12, 0)
        self.assertEqual(market_clock("forex", now_utc=sat)["closed"],
                         _utc(2026, 10, 9, 21, 0))
        self.assertEqual(market_clock("commodity", now_utc=sat)["closed"],
                         _utc(2026, 10, 9, 21, 0), "Globex: Friday 16:00 CT")
        self.assertEqual(market_clock("stock", now_utc=sat)["closed"],
                         _utc(2026, 10, 9, 20, 0), "NYSE: Friday 16:00 ET")
        brk = market_clock("commodity", now_utc=_utc(2026, 10, 13, 21, 30))
        self.assertFalse(brk["is_open"])
        self.assertEqual(brk["closed"], _utc(2026, 10, 13, 21, 0),
                         "the daily break began at 16:00 CT")
        tue = market_clock("forex", now_utc=_utc(2026, 10, 13, 12, 0))
        self.assertTrue(tue["is_open"])
        self.assertIsNone(tue["closed"])
        self.assertIsNone(market_clock("crypto", now_utc=sat)["closed"])
        self.assertIsNone(market_clock("cfd", now_utc=sat)["closed"])
        # Sunday 21:05 UTC: the week is OPEN (its settle window)
        sun = market_clock("forex", now_utc=_utc(2026, 10, 11, 21, 5))
        self.assertTrue(sun["is_open"])

    def test_market_shut_is_the_venues_clock_never_the_settle_window(self):
        from bot_program import venue_mark
        gold = self._real("XAUUSD", "commodity", {})
        eur = self._real("EURUSD", "forex", {})
        sat = _utc(2026, 10, 10, 12, 0)
        shut = venue_mark.market_shut(gold, now=sat)
        self.assertEqual(shut["closed"], _utc(2026, 10, 9, 21, 0))
        self.assertEqual(venue_mark.market_shut(eur, now=sat)["closed"],
                         _utc(2026, 10, 9, 21, 0))
        # Sunday 21:05 UTC: forex reopened five minutes ago — OPEN, however
        # the paper venue's settle window words it
        self.assertIsNone(venue_mark.market_shut(
            eur, now=_utc(2026, 10, 11, 21, 5)))
        # Tuesday noon: open
        self.assertIsNone(venue_mark.market_shut(
            gold, now=_utc(2026, 10, 13, 12, 0)))

    def test_a_weekend_books_only_the_fridays_close(self):
        sat = _utc(2026, 10, 10, 12, 0)
        at_close = self._real("XAUUSD", "commodity",
                              _stamp_at("2649.75", _utc(2026, 10, 9, 20, 30)))
        self.assertTrue(self._bookable(at_close, sat),
                        "the print half an hour before Friday's close")
        noon = self._real("XAUUSD", "commodity",
                          _stamp_at("2649.75", _utc(2026, 10, 9, 18, 0)))
        self.assertFalse(self._bookable(noon, sat),
                         "three hours before the close is not the close")
        thursday = self._real("XAUUSD", "commodity",
                              _stamp_at("2649.75", _utc(2026, 10, 8, 20, 50)))
        self.assertFalse(self._bookable(thursday, sat),
                         "a day-older print is not Friday's close")

    def test_the_daily_break_books_only_the_print_at_the_close(self):
        brk = _utc(2026, 10, 13, 21, 30)      # Globex 16:00-17:00 CT
        near = self._real("XAUUSD", "commodity",
                          _stamp_at("2649.75", _utc(2026, 10, 13, 20, 0)))
        self.assertTrue(self._bookable(near, brk))
        seven_h = self._real("XAUUSD", "commodity",
                             _stamp_at("2649.75", _utc(2026, 10, 13, 14, 30)))
        self.assertFalse(self._bookable(seven_h, brk),
                         "a seven-hour print over a shut market")

    def test_the_settle_window_is_an_open_market(self):
        """Sunday 21:05 UTC: forex reopened at 21:00; Friday's print is not
        bookable — the paper venue's settle window counted as 'shut' here
        before, and a print up to four days old booked after the gap."""
        friday = self._real("EURUSD", "forex",
                            _stamp_at("1.1", _utc(2026, 10, 9, 20, 30)))
        self.assertFalse(self._bookable(friday, _utc(2026, 10, 11, 21, 5)))
        self.assertTrue(self._bookable(friday, _utc(2026, 10, 10, 12, 0)),
                        "...while on Saturday it IS the venue's price")

    def test_an_index_cfd_keeps_its_venues_week_not_its_cash_index(self):
        """Tuesday 02:00 UTC NYSE is shut and the CFD trades: open. On
        Saturday the CFD's own week is shut, from Friday's close."""
        from bot_program import venue_mark
        tue_night = _utc(2026, 10, 13, 2, 0)   # NYSE shut, the CFD trades
        row = self._real("SPX500", "index",
                         _stamp_at("6500", _utc(2026, 10, 12, 23, 0)))
        self.assertIsNone(venue_mark.market_shut(row, now=tue_night))
        self.assertFalse(self._bookable(row, tue_night),
                         "a three-hour print on a market that trades")
        recent = self._real("SPX500", "index",
                            _stamp_at("6500", _utc(2026, 10, 13, 1, 20)))
        self.assertTrue(self._bookable(recent, tue_night),
                        "...within the hour it books as anywhere")
        sat = _utc(2026, 10, 10, 12, 0)
        self.assertEqual(venue_mark.market_shut(row, now=sat)["closed"],
                         _utc(2026, 10, 9, 21, 0))
        self.assertIsNone(venue_mark.market_shut(
            row, now=_utc(2026, 10, 14, 12, 0)), "Wednesday: open")
        friday = self._real("SPX500", "index",
                            _stamp_at("5810", _utc(2026, 10, 9, 20, 59)))
        self.assertTrue(self._bookable(friday, sat),
                        "Friday's close books over the weekend")

    def test_an_unreadable_clock_is_not_shut(self):
        from bot_program import venue_mark
        gold = self._real("XAUUSD", "commodity", {})
        with mock.patch("core.exchange_status.market_clock",
                        side_effect=RuntimeError("no clock")):
            self.assertIsNone(venue_mark.market_shut(gold))


class AQuoteBooksOnlyWhileFreshTests(TestCase):
    """C3. A QUOTE is bookable within MAX_AGE_S (or at the close of a shut
    market); a stale quote never hides a bookable venue print."""

    def setUp(self):
        self.user = get_user_model().objects.create_user("vmk_c3",
                                                         password="x")
        self.cfg = _cfg(self.user, asset_class="forex")
        _instrument("EURUSD", "forex")

    def _eur(self, meta=None, paper=False):
        from bot_program.models import AssetBotTrade
        m = {"initial_stop_loss": 1.09}
        if not paper:
            m["broker"] = "etoro"
        m.update(meta or {})
        return AssetBotTrade.objects.create(
            config=self.cfg, asset_class="forex", symbol="EURUSD", side="BUY",
            qty=Decimal("10000"), entry_price=Decimal("1.1000"),
            stop_loss=Decimal("1.09"), status="OPEN", paper=paper,
            rule_name="manual_take", metadata=m)

    def _dead(self):
        c = mock.MagicMock(spec=["ticker"])
        c.ticker.side_effect = RuntimeError("down")
        return c

    def test_a_dead_feeds_days_old_quote_does_not_book(self):
        from bot_program import venue_mark
        from bot_program.engine.kill_switch import _market_exit_price
        from market_data.models import LiveQuote
        _quote("EURUSD", "1.1010", asset_class="forex", source="oanda_stream",
               age_s=3 * 86400)
        t = self._eur()
        q = LiveQuote.objects.get(instrument__symbol="EURUSD")
        mk = venue_mark.resolve(t, q)
        self.assertEqual(mk.source, venue_mark.QUOTE)
        with _open_market():
            self.assertFalse(venue_mark.bookable(mk, t))
            self.assertIsNone(venue_mark.for_booking(t, q))
            self.assertEqual(_market_exit_price("EURUSD", t.entry_price,
                                                client=self._dead(), trade=t),
                             (1.1, True, None))
        _quote("EURUSD", "1.1010", asset_class="forex", source="oanda_stream",
               age_s=60)
        q = LiveQuote.objects.get(instrument__symbol="EURUSD")
        self.assertTrue(venue_mark.bookable(venue_mark.resolve(t, q), t))
        self.assertEqual(_market_exit_price("EURUSD", t.entry_price,
                                            client=self._dead(), trade=t),
                         (1.101, False, None))

    def test_a_stale_quote_never_hides_a_bookable_venue_print(self):
        """The quote is 20 minutes old (newer than the print, so resolve
        answers QUOTE) and past the fresh bound; the 40-minute venue print
        books within the hour — the kill switch takes it."""
        from bot_program import venue_mark
        from bot_program.engine.kill_switch import _market_exit_price
        from market_data.models import LiveQuote
        _quote("EURUSD", "1.1010", asset_class="forex", source="oanda_stream",
               age_s=20 * 60)
        t = self._eur(_stamp("1.1050", age_s=40 * 60))
        q = LiveQuote.objects.get(instrument__symbol="EURUSD")
        self.assertEqual(venue_mark.resolve(t, q).source, venue_mark.QUOTE)
        with _open_market():
            mk = venue_mark.for_booking(t, q)
            self.assertEqual((mk.source, mk.price), (venue_mark.VENUE_STALE,
                                                     1.105))
            price, unpriced, age = _market_exit_price(
                "EURUSD", t.entry_price, client=self._dead(), trade=t)
        self.assertEqual((price, unpriced), (1.105, False))
        self.assertAlmostEqual(age, 2400, delta=30)

    def test_a_shut_markets_quote_books_at_the_close_like_a_print(self):
        from bot_program import venue_mark
        from market_data.models import LiveQuote
        _quote("EURUSD", "1.1010", asset_class="forex", source="oanda_stream",
               age_s=3 * 3600)
        t = self._eur()
        q = LiveQuote.objects.get(instrument__symbol="EURUSD")
        mk = venue_mark.resolve(t, q)
        with _shut_market(closed=timezone.now() - timedelta(hours=2,
                                                            minutes=30)):
            self.assertTrue(venue_mark.bookable(mk, t),
                            "taken half an hour before the close")
        with _shut_market(closed=timezone.now() - timedelta(hours=1,
                                                            minutes=30)):
            self.assertFalse(venue_mark.bookable(mk, t),
                             "taken an hour and a half before the close")
        paper = self._eur(paper=True)
        with _open_market():
            self.assertFalse(venue_mark.bookable(venue_mark.resolve(paper, q),
                                                 paper),
                             "a paper row's three-hour quote in an open market")


class AStalePrintDecidesNothingInAnOpenMarketTests(TestCase):
    """C4. The position review (the thesis stop Aragorn applies) and the
    level editor take a VENUE_STALE print only while the market is shut;
    the pages keep showing it with its age."""

    def setUp(self):
        self.user = get_user_model().objects.create_user("vmk_c4",
                                                         password="x")
        self.cfg = _cfg(self.user)
        _instrument("XAUUSD", "commodity", "Gold Spot")
        _quote("XAUUSD", FUTURE, asset_class="commodity")

    def test_the_review_takes_a_stale_print_only_while_shut(self):
        from brain import position_review as pr
        t = _gold(self.cfg, meta=_stamp("2700", age_s=3 * 3600))
        pos = pr.bot_position(t)
        with _open_market():
            got = pr._venue_mark_for(pos)
        self.assertIsNone(got[0], "a three-hour print is not a live mark")
        self.assertIn("3 h old", got[1])
        self.assertIn("is not live", got[1])
        self.assertNotIn("market is open", got[1],
                         "the clock may not be modelled: never said open")
        with _open_market():
            facts = pr.measure(pos)
        self.assertIsNone(facts["mark"])
        self.assertIn("no_verdict_reason", facts)
        self.assertIsNone(facts["unrealized_r"],
                          "no R, no thesis stop, on a stale print")
        with _shut_market():
            got = pr._venue_mark_for(pos)
        self.assertEqual(got, (2700.0, "venue (3 h old, market shut)"))
        fresh = _gold(self.cfg, meta=_stamp("2700", age_s=30))
        self.assertEqual(pr._venue_mark_for(pr.bot_position(fresh)),
                         (2700.0, "venue"))

    def test_the_review_falls_back_to_the_fresh_quote_rule_where_it_may(self):
        """EURUSD's quote IS the venue's instrument: with a stale print and
        no quote the review keeps usable_mark's own answer (None here)."""
        from brain import position_review as pr
        from bot_program.models import AssetBotTrade
        _instrument("EURUSD", "forex")
        t = AssetBotTrade.objects.create(
            config=_cfg(self.user, asset_class="forex", name="fx"),
            asset_class="forex", symbol="EURUSD", side="BUY",
            qty=Decimal("1000"), entry_price=Decimal("1.1"),
            stop_loss=Decimal("1.09"), status="OPEN", paper=False,
            rule_name="r", metadata={"broker": "etoro",
                                     **_stamp("1.105", age_s=3 * 3600)})
        with _open_market():
            self.assertIsNone(pr._venue_mark_for(pr.bot_position(t)))

    def test_the_review_values_a_short_at_the_ask(self):
        from brain import position_review as pr
        from bot_program import venue_mark
        from bot_program.models import AssetBotTrade
        short = _gold(self.cfg, entry="2649.75", meta={
            "venue_mark": venue_mark.at_fill(2649.75, source="etoro",
                                             bid=2649.75, ask=2650.00)})
        AssetBotTrade.objects.filter(pk=short.pk).update(side="SELL")
        short.refresh_from_db()
        self.assertEqual(pr._venue_mark_for(pr.bot_position(short)),
                         (2650.0, "venue"))

    def test_the_level_editor_judges_a_stale_print_only_while_shut(self):
        from bot_program.adjust_levels import _mark_for, validate_levels
        long_ = _gold(self.cfg, meta=_stamp("2650.00", age_s=3 * 3600))
        with _open_market():
            self.assertIsNone(_mark_for(long_))
            self.assertEqual(validate_levels(long_, Decimal("2655"), None),
                             [], "no mark, no side check, never the basis")
        with _shut_market():
            self.assertEqual(_mark_for(long_), Decimal("2650.0"))
            self.assertTrue(validate_levels(long_, Decimal("2655"), None))

    def test_the_pages_keep_showing_the_stale_print_with_its_age(self):
        from dashboard.views import _chart_positions
        from instruments.models import Instrument
        from portfolio.services import unified_open_positions
        t = _gold(self.cfg, meta=_stamp("2649.75", age_s=2 * 3600))
        with _open_market():
            row = [r for r in unified_open_positions(self.user)
                   if r.trade_id == t.id][0]
            self.assertEqual(row.mark_source, "venue_stale")
            self.assertAlmostEqual(row.unrealized_pnl, -0.25, places=6)
            inst = Instrument.objects.get(symbol="XAUUSD")
            panel = {r["id"]: r for r in _chart_positions(self.user, inst)}
        self.assertEqual(panel[f"bot-{t.pk}"]["mark_word"], "venue · 2 h old")


class TheSidesSurviveTests(TestCase):
    """C5. A sideless newer print carries the measured half-spread; the
    three lanes that book a fill stamp its sides; the dialog stamps the
    sides it read."""

    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user("vmk_c5",
                                                         password="x")
        self.cfg = _cfg(self.user)
        _instrument("XAUUSD", "commodity", "Gold Spot")
        _quote("XAUUSD", FUTURE, asset_class="commodity")

    def _pnl(self, t):
        from portfolio.services import unified_open_positions
        return [r for r in unified_open_positions(self.user)
                if r.trade_id == t.id][0].unrealized_pnl

    def test_a_candle_carries_the_fills_half_spread_forward(self):
        from bot_program import venue_mark
        long_ = _gold(self.cfg, entry="2650.00", meta={
            "venue_mark": venue_mark.at_fill(2650.00, source="etoro",
                                             bid=2649.50, ask=2650.00)})
        short = _gold(self.cfg, entry="2649.50", meta={
            "venue_mark": venue_mark.at_fill(2649.50, source="etoro",
                                             bid=2649.50, ask=2650.00)})
        from bot_program.models import AssetBotTrade
        AssetBotTrade.objects.filter(pk=short.pk).update(side="SELL")
        short.refresh_from_db()
        self.assertAlmostEqual(self._pnl(long_), -0.5, places=6)
        self.assertAlmostEqual(self._pnl(short), -0.5, places=6)
        # the bar refresh, minutes later: the same market, a close at the
        # mid, no sides — the valuation must not snap to zero
        self.assertEqual(venue_mark.stamp_rows("XAUUSD", 2649.75,
                                               carrier="etoro"), 2)
        long_.refresh_from_db()
        short.refresh_from_db()
        vm = long_.metadata["venue_mark"]
        self.assertEqual((vm["bid"], vm["ask"]), (2649.5, 2650.0))
        self.assertIn("spread_from", vm)
        self.assertLess(vm["spread_age_s"], 60)
        self.assertAlmostEqual(self._pnl(long_), -0.5, places=6)
        self.assertAlmostEqual(self._pnl(short), -0.5, places=6)
        got = venue_mark.last(long_)
        self.assertIsNotNone(got["spread_from"])
        # a chain: the next candle still names the ORIGINAL measurement
        venue_mark.stamp(long_, 2651.0, source="etoro", via="candle",
                         now=timezone.now() + timedelta(seconds=600))
        long_.refresh_from_db()
        self.assertEqual(long_.metadata["venue_mark"]["spread_from"],
                         vm["spread_from"])
        self.assertEqual(long_.metadata["venue_mark"]["bid"], 2650.75)

    def test_a_measurement_past_the_bound_is_not_carried(self):
        from bot_program import venue_mark
        old = timezone.now() - timedelta(seconds=venue_mark.SPREAD_CARRY_MAX_S
                                         + 60)
        t = _gold(self.cfg, meta=_stamp_at("2650", old, bid=2649.5,
                                            ask=2650.0))
        self.assertTrue(venue_mark.stamp(t, 2649.75, source="etoro",
                                         via="candle"))
        t.refresh_from_db()
        self.assertNotIn("bid", t.metadata["venue_mark"])
        self.assertNotIn("spread_from", t.metadata["venue_mark"])
        self.assertAlmostEqual(self._pnl(t), -0.25, places=6)

    def test_a_measured_pair_is_never_overwritten_by_a_carried_one(self):
        from bot_program import venue_mark
        t = _gold(self.cfg, meta={"venue_mark": venue_mark.at_fill(
            2650.00, source="etoro", bid=2649.50, ask=2650.00)})
        self.assertTrue(venue_mark.stamp(t, 2649.75, source="etoro",
                                         via="tick", bid=2649.6, ask=2649.9))
        t.refresh_from_db()
        vm = t.metadata["venue_mark"]
        self.assertEqual((vm["bid"], vm["ask"]), (2649.6, 2649.9))
        self.assertNotIn("spread_from", vm)

    def test_fill_sides_anchors_the_spread_at_the_fill(self):
        from bot_program.venue_mark import fill_sides
        self.assertEqual(fill_sides(100.0, "BUY", bid=99.9, ask=100.1),
                         {"bid": 99.8, "ask": 100.0})
        self.assertEqual(fill_sides(100.0, "SELL", bid=99.9, ask=100.1),
                         {"bid": 100.0, "ask": 100.2})
        self.assertEqual(fill_sides(100.0, "BUY", bid=None, ask=100.1), {})
        self.assertEqual(fill_sides(100.0, "BUY", bid=100.2, ask=100.1), {},
                         "a crossed pair anchors nothing")
        self.assertEqual(fill_sides(0, "BUY", bid=99.9, ask=100.1), {})

    def test_take_trade_anchors_the_tickets_spread_at_the_fill(self):
        """The ticket's quote read bid 59990 / ask 60010; the fill 60012.5
        is the ask: the row is born bid 59992.5 / ask 60012.5. Swapping the
        sides, dropping or doubling the spread each fails here."""
        from bot_program.models import AssetBotTrade
        from tests.test_take_trade_live import (_arm_live, _components_on,
                                                _fake_live_client, _quote as q,
                                                _signal)
        inst = q("BTCUSD", 60000)
        _components_on()
        _arm_live(self.user)
        client = _fake_live_client()
        client.ticker.return_value = {"lastPrice": "60000", "bid": "59990",
                                      "ask": "60010"}
        from bot_program.manual_trade import execute_take_trade
        with mock.patch(ROUTER, return_value=client):
            out = execute_take_trade(self.user, _signal(inst), pin_ok=True)
        self.assertTrue(out.get("ok"), out)
        vm = AssetBotTrade.objects.get(pk=out["trade_id"]).metadata["venue_mark"]
        self.assertEqual((vm["price"], vm["bid"], vm["ask"]),
                         (60012.5, 59992.5, 60012.5))

    def test_a_working_fill_stamps_the_last_looks_sides_at_the_fill(self):
        from instruments.models import Instrument
        from tests.test_working_entries import (_cfg as wcfg,
                                                _client as wclient,
                                                _working_trade)
        Instrument.objects.get_or_create(
            symbol="NVDA", defaults={"name": "NVDA", "asset_class": "stock"})
        cfg = wcfg(self.user)
        sent = timezone.now() - timedelta(hours=2)
        trade = _working_trade(cfg, entry_quote={"bid": 99.5, "ask": 100.0,
                                                 "mid": 99.75},
                               entry_working_since=sent.isoformat())
        from bot_program.asset_engine.stock_bot import StockBot
        with mock.patch(ROUTER, return_value=wclient(
                {"state": "filled", "filled": 10.0, "avgPrice": 99.75,
                 "status": "Filled"})):
            StockBot(cfg).manage_positions()
        trade.refresh_from_db()
        vm = trade.metadata["venue_mark"]
        self.assertEqual((vm["price"], vm["bid"], vm["ask"]),
                         (99.75, 99.25, 99.75))
        # the spread is dated from its READ at order time, never the fill
        self.assertEqual(vm["spread_from"], sent.isoformat())
        self.assertAlmostEqual(vm["spread_age_s"], 7200, delta=60)

    def test_the_close_dialog_stamps_the_sides_it_read(self):
        from bot_program.manual_close import preview_close
        from bot_program.models import AssetBotTrade
        from tests.test_manual_close import _live_trade, _quote as mq
        inst = mq("BTCUSD", 60000)
        t = _live_trade(self.user, inst)
        live = mock.MagicMock(name="live_client")
        live.ticker.return_value = {"lastPrice": "60100", "bid": "60090",
                                    "ask": "60110"}
        with mock.patch(ROUTER, return_value=live):
            p = preview_close(self.user, t)
        self.assertNotIn("error", p)
        vm = AssetBotTrade.objects.get(pk=t.pk).metadata["venue_mark"]
        self.assertEqual((vm["price"], vm["bid"], vm["ask"], vm["via"]),
                         (60100.0, 60090.0, 60110.0, "close dialog"))


class TheSmallerVerdictsTests(TestCase):
    """C6 the age's provenance in the reconcile; C7 a real options row with
    no premium; C8 eToro's "0" for a shut market; C9 the panel's words."""

    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user("vmk_sm",
                                                         password="x")
        self.cfg = _cfg(self.user)
        _instrument("XAUUSD", "commodity", "Gold Spot")
        _quote("XAUUSD", FUTURE, asset_class="commodity")

    def test_the_reconcile_writes_the_age_only_for_a_stale_print(self):
        from bot_program.models import AssetBotTrade
        from bot_program.reconcile_asset import _close_as_orphan
        dead = mock.MagicMock(spec=["ticker"])
        dead.ticker.side_effect = RuntimeError("down")
        fresh = _gold(self.cfg, meta=_stamp("2649.75", age_s=60))
        with mock.patch(ROUTER, return_value=dead), _open_market():
            self.assertTrue(_close_as_orphan(fresh))
        fresh = AssetBotTrade.objects.get(pk=fresh.pk)
        self.assertEqual(fresh.exit_price, Decimal("2649.75"))
        self.assertNotIn("exit_mark_age_s", fresh.metadata,
                         "a fresh print is not a stale one")
        stale = _gold(self.cfg, meta=_stamp("2649.75", age_s=3 * 3600))
        with mock.patch(ROUTER, return_value=dead), _shut_market():
            self.assertTrue(_close_as_orphan(stale))
        stale = AssetBotTrade.objects.get(pk=stale.pk)
        self.assertAlmostEqual(stale.metadata["exit_mark_age_s"], 3 * 3600,
                               delta=60)
        # the level the venue held priced it: no print's age beside it
        level = _gold(self.cfg, meta=_stamp("2649.75", age_s=3 * 3600))
        with mock.patch(ROUTER, return_value=dead), _shut_market(), \
                mock.patch("bot_program.venue_exit.estimate", return_value={
                    "level": "stop", "price": 2630.0, "evidence": "crossed",
                    "seen": None, "source": "venue_stop", "since": None}):
            self.assertTrue(_close_as_orphan(level, venue_said="closed"))
        level = AssetBotTrade.objects.get(pk=level.pk)
        self.assertEqual(level.exit_price, Decimal("2630"))
        self.assertNotIn("exit_mark_age_s", level.metadata)

    def test_a_real_options_row_with_no_premium_is_unpriced(self):
        from bot_program.engine.kill_switch import _close_asset_trade
        from bot_program.models import AssetBotTrade
        from bot_program.reconcile_asset import UNPRICED_EXIT_KEY
        cfg = _cfg(self.user, asset_class="options", name="opt")
        t = AssetBotTrade.objects.create(
            config=cfg, asset_class="options", symbol="AAPL", side="BUY",
            qty=Decimal("1"), entry_price=Decimal("5.00"),
            stop_loss=Decimal("3"), status="OPEN", paper=False,
            rule_name="x", metadata={"broker": "alpaca", "occ_symbol": "AAPL1"})
        c = mock.MagicMock(spec=["ticker", "market_order", "cancel_order"])
        c.ticker.side_effect = RuntimeError("down")
        with mock.patch(ROUTER, return_value=c), \
                mock.patch("bot_program.asset_engine.options_bot."
                           "current_premium_for_trade", return_value=None), \
                mock.patch("bot_program.asset_engine.options_bot."
                           "submit_option_close",
                           return_value={"status": "FILLED",
                                         "executedQty": "1"}):
            _close_asset_trade(t, timezone.now())
        t = AssetBotTrade.objects.get(pk=t.pk)
        self.assertEqual(t.status, "CLOSED")
        self.assertEqual(t.exit_price, Decimal("5"))
        self.assertIsNone(t.pnl, "the entry premium is not a scratch")
        self.assertTrue(t.metadata.get(UNPRICED_EXIT_KEY))
        # a premium read: priced as before
        t2 = AssetBotTrade.objects.create(
            config=cfg, asset_class="options", symbol="AAPL", side="BUY",
            qty=Decimal("1"), entry_price=Decimal("5.00"),
            stop_loss=Decimal("3"), status="OPEN", paper=False,
            rule_name="x", metadata={"broker": "alpaca", "occ_symbol": "AAPL1",
                                     "contract_multiplier": 100})
        with mock.patch(ROUTER, return_value=c), \
                mock.patch("bot_program.asset_engine.options_bot."
                           "current_premium_for_trade",
                           return_value=Decimal("4.50")), \
                mock.patch("bot_program.asset_engine.options_bot."
                           "submit_option_close",
                           return_value={"status": "FILLED",
                                         "executedQty": "1"}):
            _close_asset_trade(t2, timezone.now())
        t2 = AssetBotTrade.objects.get(pk=t2.pk)
        self.assertIsNotNone(t2.pnl)
        self.assertNotIn(UNPRICED_EXIT_KEY, t2.metadata)

    def test_etoros_zero_for_a_shut_market_falls_into_the_rule(self):
        from bot_program.models import AssetBotTrade
        from bot_program.reconcile_asset import (UNPRICED_EXIT_KEY,
                                                 _close_as_orphan)
        zero = mock.MagicMock(spec=["ticker"])
        zero.ticker.return_value = {"lastPrice": "0", "market_shut": True}
        t = _gold(self.cfg, meta=_stamp("2649.75", age_s=3 * 3600))
        with mock.patch(ROUTER, return_value=zero), _shut_market():
            self.assertTrue(_close_as_orphan(t))
        t = AssetBotTrade.objects.get(pk=t.pk)
        self.assertEqual(t.exit_price, Decimal("2649.75"))
        self.assertAlmostEqual(float(t.pnl), -0.25, places=6)
        self.assertNotIn(UNPRICED_EXIT_KEY, t.metadata)
        bare = _gold(self.cfg)
        with mock.patch(ROUTER, return_value=zero), _shut_market():
            self.assertTrue(_close_as_orphan(bare))
        bare = AssetBotTrade.objects.get(pk=bare.pk)
        self.assertIsNone(bare.pnl)
        self.assertTrue(bare.metadata.get(UNPRICED_EXIT_KEY))

    def test_the_instrument_page_panel_says_the_mark_with_its_age(self):
        self.client.force_login(self.user)
        _gold(self.cfg, meta=_stamp("2649.75", age_s=2 * 3600))
        with _open_market():
            body = self.client.get("/instruments/XAUUSD/",
                                   HTTP_HOST="127.0.0.1").content.decode()
        self.assertIn('data-mark-source="venue_stale"', body)
        self.assertIn("venue · 2 h old", body)
        self.assertIn("-0.25", body)
        self.assertNotIn("+18.00", body)


class TheTestsDimensionTests(TestCase):
    """T. Behaviour where a source grep stood: the manage tick's bid/ask
    pass-through, the candle stamp's time and the public-feed guard, the
    open_trades command's stale branch, the stamp's changed-sides rewrite."""

    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user("vmk_t",
                                                         password="x")
        self.cfg = _cfg(self.user)
        _instrument("XAUUSD", "commodity", "Gold Spot")
        _quote("XAUUSD", FUTURE, asset_class="commodity")

    def test_the_manage_tick_stamps_the_tickers_two_sides(self):
        from tests.test_risk_limits_bind import _config, _quote as cq
        from tests.test_scale_out import _trade
        cfg = _config(self.user, symbols=["BTCUSD"])
        cq("BTCUSD", "100.9")
        t = _trade(cfg, paper=False)
        from bot_program.asset_engine.base import make_bot
        client = mock.MagicMock(spec=["ticker"])
        client.ticker.return_value = {"lastPrice": "100.4", "symbol": "BTCUSD",
                                      "bid": "100.3", "ask": "100.5"}
        with mock.patch(ROUTER, return_value=client):
            make_bot(cfg).manage_positions()
        t.refresh_from_db()
        vm = t.metadata["venue_mark"]
        self.assertEqual((vm["price"], vm["bid"], vm["ask"], vm["via"]),
                         (100.4, 100.3, 100.5, "tick"))

    def test_a_closed_candle_is_stamped_at_its_end_not_now(self):
        from bot_program import venue_mark
        from bot_program.engine.etoro_client import EtoroTrader
        from market_data import bot_bars
        cfg = _cfg(self.user, name="off", enabled=False)
        t = _gold(cfg)
        opened = timezone.now() - timedelta(hours=5)
        rows = [[int(opened.timestamp() * 1000), "2648", "2651", "2647",
                 "2649.5", "10"]]
        self.assertEqual(bot_bars._stamp_venue_rows(
            EtoroTrader("k", "u", env="live"), "XAUUSD", "1h", rows), 1)
        t.refresh_from_db()
        got = venue_mark.last(t)
        self.assertEqual(got["price"], 2649.5)
        self.assertAlmostEqual(got["age_s"], 4 * 3600, delta=30,
                               msg="stamped at the candle's END, four hours "
                                   "ago")
        self.assertEqual(venue_mark.resolve(t, None).source,
                         venue_mark.VENUE_STALE)

    def test_the_public_feed_never_stamps_even_with_a_carrier_key(self):
        from bot_program.engine.binance_client import BinanceClient
        from bot_program.models import AssetBotTrade
        from market_data import bot_bars
        _instrument("BTCUSD", "crypto")
        cfg = _cfg(self.user, asset_class="crypto", name="c", enabled=False)
        t = AssetBotTrade.objects.create(
            config=cfg, asset_class="crypto", symbol="BTCUSD", side="BUY",
            qty=Decimal("1"), entry_price=Decimal("60000"),
            stop_loss=Decimal("59000"), status="OPEN", paper=False,
            rule_name="r", metadata={"broker": "binance"})
        rows = [[int(timezone.now().timestamp() * 1000) - 60000, "1", "1",
                 "1", "60100", "1"]]
        public = BinanceClient("", "", testnet=False)
        public._sv_public_feed = True
        self.assertEqual(bot_bars._stamp_venue_rows(public, "BTCUSD", "1h",
                                                    rows), 0)
        t.refresh_from_db()
        self.assertNotIn("venue_mark", t.metadata)
        venue = BinanceClient("k", "s", testnet=False)
        self.assertEqual(bot_bars._stamp_venue_rows(venue, "BTCUSD", "1h",
                                                    rows), 1,
                         "the same client as the VENUE stamps")

    def test_the_open_trades_command_reads_a_stale_print(self):
        from bot_program.management.commands.open_trades import _open_mark
        stale = _gold(self.cfg, meta=_stamp("2649.75", age_s=3 * 3600))
        self.assertEqual(_open_mark(stale, False), 2649.75)

    def test_the_stamp_rewrites_the_same_price_with_changed_sides(self):
        from bot_program import venue_mark
        t = _gold(self.cfg)
        self.assertTrue(venue_mark.stamp(t, 2650, source="etoro", via="tick",
                                         bid=2649.9, ask=2650.1))
        self.assertFalse(venue_mark.stamp(t, 2650, source="etoro", via="tick",
                                          bid=2649.9, ask=2650.1),
                         "the same print, just written")
        self.assertTrue(venue_mark.stamp(t, 2650, source="etoro", via="tick",
                                         bid=2649.8, ask=2650.2),
                        "the same price with a wider spread is a new print")
        t.refresh_from_db()
        self.assertEqual(t.metadata["venue_mark"]["bid"], 2649.8)


# ── the second re-check (2026-10-15): what the first fixes left ─────────


class _Flat(_EtoroDown):
    """eToro's rates down and the position ALREADY GONE from its book (a
    stop eToro filled): the ticker raises and get_positions lists
    nothing, so the switch finds nothing left to send."""

    def __init__(self, answer=None, held=()):
        super().__init__(answer)
        self.get_positions = lambda: list(held)


def _fresh(trade):
    from bot_program.models import AssetBotTrade
    return AssetBotTrade.objects.select_related("config__user").get(
        pk=trade.pk)


class TheStandInIsNeverAScratchTests(TestCase):
    """The entry standing in for a real row's exit is marked where it is
    chosen — the units the switch finds already filled at the venue, the
    drain's resend without a mark — and every booking asks one per-fill
    rule (pending_closes.booking_unpriced)."""

    def setUp(self):
        self.user = get_user_model().objects.create_user("vmk_r2",
                                                         password="x")
        self.cfg = _cfg(self.user)
        _instrument("XAUUSD", "commodity", "Gold Spot")
        _quote("XAUUSD", FUTURE, asset_class="commodity")

    def _kill(self, trade, client):
        from bot_program.engine.kill_switch import _close_asset_trade
        with mock.patch(ROUTER, return_value=client), _open_market():
            return _close_asset_trade(trade, timezone.now())

    def _drain(self, trade, client):
        from bot_program.pending_closes import retry_trade_close
        with mock.patch(ROUTER, return_value=client), _open_market():
            return retry_trade_close(trade)

    def test_a_row_already_flat_while_the_rates_fail_is_unpriced(self):
        """A1: eToro's stop already filled (its book is flat), its rates are
        down and the only print is three hours old in an open market. The
        switch sends nothing and books CLOSED — UNPRICED, never the
        entry's confident zero, and the daily stop counts it unmeasured."""
        from bot_program.reconcile_asset import UNPRICED_EXIT_KEY
        t = _gold(self.cfg, meta=_stamp("2649.75", age_s=3 * 3600))
        client = _Flat()
        self._kill(t, client)
        self.assertEqual(client.sent, [], "nothing left to send")
        t = _fresh(t)
        self.assertEqual(t.status, "CLOSED")
        self.assertTrue(t.metadata.get(UNPRICED_EXIT_KEY))
        self.assertIsNone(t.pnl)
        self.assertTrue(t.metadata["close_fills"][-1].get("unpriced"))
        r = _realized(self.user)
        self.assertEqual((r["live_n"], r["unmeasured"]), (0, 1))

    def test_a_row_already_flat_books_a_bookable_print_with_its_age(self):
        """A3: the same, with a forty-minute print at 2631 the switch may
        book: the units found filled are priced at it, and its age rides
        the row because that print priced the exit."""
        from bot_program.reconcile_asset import UNPRICED_EXIT_KEY
        t = _gold(self.cfg, meta=_stamp("2631", age_s=40 * 60))
        self._kill(t, _Flat())
        t = _fresh(t)
        self.assertEqual(t.status, "CLOSED")
        self.assertEqual(t.exit_price, Decimal("2631"))
        self.assertEqual(t.pnl, Decimal("-19"))
        self.assertNotIn(UNPRICED_EXIT_KEY, t.metadata)
        self.assertAlmostEqual(t.metadata["exit_mark_age_s"], 2400, delta=60)

    def test_the_drains_resend_with_no_mark_is_unpriced(self):
        """A5: a CLOSE_PENDING real row with nothing working; the drain
        resends, the venue proves the close FILLED with no price, and the
        rates are still down. The entry stood in: UNPRICED, pnl NULL."""
        from bot_program.reconcile_asset import UNPRICED_EXIT_KEY
        t = _gold(self.cfg, status="CLOSE_PENDING")
        d = _EtoroDown({"orderId": "c2", "status": "FILLED",
                        "executedQty": "1"})
        d.get_positions = lambda: [{"symbol": "XAUUSD", "qty": 1.0,
                                    "side": "BUY"}]
        with mock.patch("dashboard.consumers.push_eye_event") as eye, \
                mock.patch("bot_program.audit.record_event") as audit:
            self.assertTrue(self._drain(t, d))
        t = _fresh(t)
        self.assertEqual(t.status, "CLOSED")
        self.assertTrue(t.metadata.get(UNPRICED_EXIT_KEY))
        self.assertIsNone(t.pnl)
        self.assertEqual(_realized(self.user)["unmeasured"], 1)
        # a dash, never a zero, wherever the close is told
        closes = [c[0][2] for c in eye.call_args_list
                  if c[0][1] == "fill_close"]
        self.assertEqual([c["pnl"] for c in closes], [""])
        trade_closes = [c[0][1] for c in audit.call_args_list
                        if c[0][0] == "trade_close"]
        self.assertEqual([c["pnl"] for c in trade_closes], [None])

    def test_a_partial_unpriced_then_an_unpriced_resend_stays_unpriced(self):
        """A4b: the switch on 10 units, FILLED 6 with no price while the
        rates are down (CLOSE_PENDING, its slice marked, no row flag); the
        drain resends the 4, still no price and no rates: UNPRICED. A
        priced resend books the measured blend (the next test)."""
        from bot_program.reconcile_asset import UNPRICED_EXIT_KEY
        t = _gold(self.cfg, qty="10")
        with self.assertRaises(RuntimeError):
            self._kill(t, _EtoroDown({"orderId": "c1", "status": "FILLED",
                                      "executedQty": "6"}))
        t = _fresh(t)
        self.assertEqual(t.status, "CLOSE_PENDING")
        self.assertNotIn(UNPRICED_EXIT_KEY, t.metadata)
        d = _EtoroDown({"orderId": "c2", "status": "FILLED",
                        "executedQty": "4"})
        d.get_positions = lambda: [{"symbol": "XAUUSD", "qty": 4.0,
                                    "side": "BUY"}]
        self.assertTrue(self._drain(t, d))
        t = _fresh(t)
        self.assertEqual(t.status, "CLOSED")
        self.assertTrue(t.metadata.get(UNPRICED_EXIT_KEY))
        self.assertIsNone(t.pnl)

    def test_a_mixed_ledger_books_the_measured_blend(self):
        """K1/K2: the broker priced 6 of 10 (avgPrice 2600) on the first
        press; the second press filled 4 with no price while the rates are
        still down. One slice was priced: the booking is the measured
        blend, never the flag with pnl NULL."""
        from bot_program.reconcile_asset import UNPRICED_EXIT_KEY
        t = _gold(self.cfg, qty="10")
        with self.assertRaises(RuntimeError):
            self._kill(t, _EtoroDown({"orderId": "c1", "status": "FILLED",
                                      "executedQty": "6",
                                      "avgPrice": "2600"}))
        t = _fresh(t)
        self._kill(t, _EtoroDown({"orderId": "c2", "status": "FILLED",
                                  "executedQty": "4"}))
        t = _fresh(t)
        self.assertEqual(t.status, "CLOSED")
        self.assertNotIn(UNPRICED_EXIT_KEY, t.metadata)
        self.assertEqual(t.exit_price, Decimal("2620"))
        self.assertEqual(t.pnl, Decimal("-300"))

    def test_the_brokers_fill_carries_no_print_age(self):
        """K3: a sixteen-minute print priced the mark but the broker's own
        avgPrice priced the exit: no exit_mark_age_s beside it. Without the
        broker's price the print priced it, and its age rides the row."""
        t = _gold(self.cfg, meta=_stamp("2610", age_s=16 * 60))
        self._kill(t, _EtoroDown({"orderId": "c1", "status": "FILLED",
                                  "executedQty": "1", "avgPrice": "2600"}))
        t = _fresh(t)
        self.assertEqual(t.metadata["exit_fill_source"], "broker")
        self.assertNotIn("exit_mark_age_s", t.metadata)
        stale = _gold(self.cfg, meta=_stamp("2610", age_s=16 * 60))
        self._kill(stale, _EtoroDown({"orderId": "c1", "status": "FILLED",
                                      "executedQty": "1"}))
        stale = _fresh(stale)
        self.assertAlmostEqual(stale.metadata["exit_mark_age_s"], 960,
                               delta=30)

    def test_a_mark_read_that_raises_is_unpriced_for_a_real_row(self):
        """K4: anything raising on the way to the one answer leaves a REAL
        row's exit unpriced, never the entry's zero."""
        from bot_program.engine.kill_switch import _market_exit_price
        t = _gold(self.cfg)
        with mock.patch("bot_program.venue_mark.for_booking",
                        side_effect=RuntimeError("db")):
            self.assertEqual(_market_exit_price("XAUUSD", t.entry_price,
                                                client=_EtoroDown(), trade=t),
                             (float(SPOT_FILL), True, None))

    def test_the_drains_own_reconcile_marks_a_stand_in(self):
        """The drain's call of the cancel-window reconcile reads its own
        mark; with none on a real row the entry stands in, marked."""
        from bot_program.pending_closes import _reconcile_filled_against_broker
        t = _gold(self.cfg, qty="10")
        c = _Flat(held=[{"symbol": "XAUUSD", "qty": 4.0, "side": "BUY"}])
        _reconcile_filled_against_broker(t, c)
        t = _fresh(t)
        self.assertEqual(t.metadata["close_fills"],
                         [{"qty": "6", "price": "2650.00", "source": "mark",
                           "reconciled": True, "unpriced": True}])
        type(t).objects.filter(pk=t.pk).update(status="CLOSED")
        priced = _gold(self.cfg, qty="10")
        _reconcile_filled_against_broker(
            priced, _EtoroPriced("2600", held=[{"symbol": "XAUUSD",
                                                "qty": 4.0, "side": "BUY"}]))
        priced = _fresh(priced)
        self.assertNotIn("unpriced", priced.metadata["close_fills"][-1])


class TheSwitchHonoursTheRowLockTests(TestCase):
    """A7 and the claim: the switch's CLOSE_PENDING save is written under
    the row lock with a status check like its CLOSED booking, onto the
    row's current metadata, and a row another close holds is left to it."""

    def setUp(self):
        self.user = get_user_model().objects.create_user("vmk_lock",
                                                         password="x")
        self.cfg = _cfg(self.user)
        _instrument("XAUUSD", "commodity", "Gold Spot")
        _quote("XAUUSD", FUTURE, asset_class="commodity")

    def _kill(self, trade, client):
        from bot_program.engine.kill_switch import _close_asset_trade
        with mock.patch(ROUTER, return_value=client), _open_market():
            return _close_asset_trade(trade, timezone.now())

    def test_a_row_the_reconcile_closed_meanwhile_stays_closed(self):
        """A7: while eToro answers the switch's close PENDING, the real
        reconcile books the row CLOSED at 2620 (pnl -30). The switch's
        CLOSE_PENDING save never turns it back: the measured loss stays in
        the daily stop and the row is booked once."""
        from bot_program.manual_close import _release
        from bot_program.reconcile_asset import _claim_orphan, _close_as_orphan
        t = _gold(self.cfg)
        booked = []

        class _ReconcileMeanwhile(_EtoroDown):
            def market_order(self_, *a, **k):
                fresh, why = _claim_orphan(t.pk)
                assert fresh is not None, why
                try:
                    priced = mock.MagicMock(spec=["ticker"])
                    priced.ticker.return_value = {"lastPrice": "2620"}
                    with mock.patch(ROUTER, return_value=priced):
                        booked.append(_close_as_orphan(fresh))
                finally:
                    _release(fresh.pk)
                return super().market_order(*a, **k)

        with self.assertRaises(RuntimeError) as err:
            self._kill(t, _ReconcileMeanwhile())
        self.assertIn("closed elsewhere", str(err.exception))
        self.assertEqual(booked, [True])
        t = _fresh(t)
        self.assertEqual(t.status, "CLOSED")
        self.assertEqual((t.exit_price, t.pnl), (Decimal("2620"),
                                                 Decimal("-30")))
        self.assertEqual(t.metadata["exit_fill_source"], "mark")
        r = _realized(self.user)
        self.assertEqual(r["live_n"], 1)
        self.assertAlmostEqual(r["live_realized"], -30.0, places=2)

    def test_the_pending_save_keeps_a_key_written_meanwhile(self):
        """The CLOSE_PENDING save lays the switch's keys over the row as the
        database holds it, never over the sweep's snapshot."""
        from bot_program.models import AssetBotTrade
        t = _gold(self.cfg)

        class _WritesMeanwhile(_EtoroDown):
            def market_order(self_, *a, **k):
                row = AssetBotTrade.objects.get(pk=t.pk)
                row.metadata = {**row.metadata, "thesis_stop": 2640.0}
                row.save(update_fields=["metadata"])
                return super().market_order(*a, **k)

        with self.assertRaises(RuntimeError):
            self._kill(t, _WritesMeanwhile())
        t = _fresh(t)
        self.assertEqual(t.status, "CLOSE_PENDING")
        self.assertEqual(t.metadata["thesis_stop"], 2640.0)
        self.assertIn("close_fills", t.metadata)

    def test_a_row_another_close_holds_is_left_to_it(self):
        """A fresh claim (the CLOSE button, the drain, the reconcile): the
        switch sends nothing and names the row in its errors. A stale
        claim — its worker died — does not hold the row."""
        from bot_program.manual_close import CLAIM_KEY
        held = _gold(self.cfg, meta={CLAIM_KEY: timezone.now().isoformat()})
        client = _EtoroPriced("2600")
        with self.assertRaises(RuntimeError) as err:
            self._kill(held, client)
        self.assertIn("being closed elsewhere", str(err.exception))
        self.assertEqual(client.sent, [])
        self.assertEqual(_fresh(held).status, "OPEN")
        stale = _gold(self.cfg, meta={
            CLAIM_KEY: (timezone.now() - timedelta(hours=1)).isoformat()})
        self._kill(stale, _EtoroPriced("2600"))
        self.assertEqual(_fresh(stale).status, "CLOSED")


def _partial_row(cfg):
    """A CLOSE_PENDING row of 10 units, 6 already filled by the broker at
    2620 (-180 measured), 4 still to close."""
    from bot_program.models import AssetBotTrade
    return AssetBotTrade.objects.create(
        config=cfg, asset_class="commodity", symbol="XAUUSD", side="BUY",
        qty=Decimal("10"), entry_price=Decimal("2650"),
        stop_loss=Decimal("2630"), take_profit=Decimal("2700"),
        status="CLOSE_PENDING", paper=False, rule_name="manual_take",
        metadata={"initial_stop_loss": 2630.0, "broker": "etoro",
                  "close_fills": [{"qty": "6", "price": "2620",
                                   "source": "broker"}],
                  "close_filled_qty": "6", "close_residual_qty": "4",
                  "exit_fill_source": "broker"})


class TheOrphanCloseReadsTheLedgerTests(TestCase):
    """A10/A11: the reconcile prices the RESIDUAL of a CLOSE_PENDING row
    and blends it with the slices already filled."""

    def setUp(self):
        self.user = get_user_model().objects.create_user("vmk_led",
                                                         password="x")
        self.cfg = _cfg(self.user)
        _instrument("XAUUSD", "commodity", "Gold Spot")

    def _orphan(self, t, client):
        from bot_program.reconcile_asset import _close_as_orphan
        with mock.patch(ROUTER, return_value=client), _open_market():
            self.assertTrue(_close_as_orphan(t))
        return _fresh(t)

    def test_a_residual_nothing_priced_keeps_the_measured_slices(self):
        """A10: rates down. The six the broker priced stay measured (-180);
        the four at the entry's stand-in are marked unpriced; the row is not
        flagged, so the daily stop sees the measured loss."""
        from bot_program.reconcile_asset import UNPRICED_EXIT_KEY
        dead = mock.MagicMock(spec=["ticker"])
        dead.ticker.side_effect = RuntimeError("rates down")
        t = self._orphan(_partial_row(self.cfg), dead)
        self.assertEqual(t.pnl, Decimal("-180"))
        self.assertNotIn(UNPRICED_EXIT_KEY, t.metadata)
        self.assertEqual(len(t.metadata["close_fills"]), 2)
        self.assertTrue(t.metadata["close_fills"][-1].get("unpriced"))
        self.assertEqual(t.metadata["exit_fill_source"], "mark")
        self.assertEqual(_realized(self.user)["unmeasured"], 0)

    def test_a_priced_residual_blends_with_the_ledger(self):
        """A11: the ticker answers 2600. Six at 2620 and four at 2600: exit
        2612, pnl -380 — not ten at 2600 (-500)."""
        c = mock.MagicMock(spec=["ticker"])
        c.ticker.return_value = {"lastPrice": "2600"}
        t = self._orphan(_partial_row(self.cfg), c)
        self.assertEqual(t.exit_price, Decimal("2612"))
        self.assertEqual(t.pnl, Decimal("-380"))
        self.assertEqual(t.metadata["close_filled_qty"], "10")
        self.assertTrue(t.metadata["exit_price_inferred"])

    def test_a_ledger_of_stand_ins_only_is_unpriced(self):
        """Every slice at the entry's stand-in and nothing pricing the
        residual: UNPRICED, as before."""
        from bot_program.reconcile_asset import UNPRICED_EXIT_KEY
        t = _partial_row(self.cfg)
        t.metadata["close_fills"] = [{"qty": "6", "price": "2650",
                                      "source": "mark", "unpriced": True}]
        t.metadata["exit_fill_source"] = "mark"
        t.save(update_fields=["metadata"])
        dead = mock.MagicMock(spec=["ticker"])
        dead.ticker.side_effect = RuntimeError("rates down")
        t = self._orphan(t, dead)
        self.assertIsNone(t.pnl)
        self.assertTrue(t.metadata.get(UNPRICED_EXIT_KEY))

    def test_the_reconcile_books_the_print_a_stale_quote_would_hide(self):
        """R1 (by behaviour, where a source grep stood): a 20-minute quote
        (resolve answers QUOTE, too old to book) never hides the bookable
        40-minute venue print."""
        from bot_program.models import AssetBotTrade
        from bot_program.reconcile_asset import UNPRICED_EXIT_KEY
        _instrument("EURUSD", "forex")
        _quote("EURUSD", "1.1010", asset_class="forex", source="oanda_stream",
               age_s=20 * 60)
        t = AssetBotTrade.objects.create(
            config=_cfg(self.user, asset_class="forex", name="fx"),
            asset_class="forex", symbol="EURUSD", side="BUY",
            qty=Decimal("10000"), entry_price=Decimal("1.1000"),
            stop_loss=Decimal("1.09"), status="OPEN", paper=False,
            rule_name="manual_take",
            metadata={"broker": "etoro", "initial_stop_loss": 1.09,
                      **_stamp("1.1050", age_s=40 * 60)})
        dead = mock.MagicMock(spec=["ticker"])
        dead.ticker.side_effect = RuntimeError("down")
        t = self._orphan(t, dead)
        self.assertEqual(t.exit_price, Decimal("1.105"))
        self.assertNotIn(UNPRICED_EXIT_KEY, t.metadata)
        self.assertAlmostEqual(t.metadata["exit_mark_age_s"], 2400, delta=60)


def _at(when):
    """The platform's clock at a fixed instant (the venue mark, the review
    and the booking all read django.utils.timezone.now)."""
    return mock.patch("django.utils.timezone.now", return_value=when)


class TheCloseIsTheVenuesPriceAtTheCloseTests(TestCase):
    """A12, P1-P4, Q1 and the shut-start clock, at fixed instants and on
    the real clock (nothing mocked but the time)."""

    def setUp(self):
        self.user = get_user_model().objects.create_user("vmk_close",
                                                         password="x")
        self.cfg = _cfg(self.user)
        _instrument("XAUUSD", "commodity", "Gold Spot")
        _quote("XAUUSD", FUTURE, asset_class="commodity")

    def _real(self, symbol, cls, meta, side="BUY", entry="1"):
        from bot_program.models import AssetBotTrade
        m = {"broker": "etoro", "initial_stop_loss": 1.0}
        m.update(meta)
        return AssetBotTrade.objects.create(
            config=self.cfg, asset_class=cls, symbol=symbol, side=side,
            qty=Decimal("1"), entry_price=Decimal(entry),
            stop_loss=Decimal("0.5"), status="OPEN", paper=False,
            rule_name="manual_take", metadata=m)

    def test_a_shut_market_books_no_older_print_than_the_open_one(self):
        """A12, Tuesday 2026-10-13: at 20:59 UTC (open) a 19:29 print is
        refused; at 21:01 (Globex's daily break) it is refused too — a
        shut market books only what the open market accepted a moment
        before it shut. A 20:15 print books on both sides of 21:00."""
        from bot_program import venue_mark
        self.assertEqual(venue_mark.BOOK_BEFORE_SHUT_S,
                         venue_mark.BOOK_STALE_MAX_S)
        old = _gold(self.cfg, meta=_stamp_at("2649.75",
                                             _utc(2026, 10, 13, 19, 29)))
        near = _gold(self.cfg, meta=_stamp_at("2649.75",
                                              _utc(2026, 10, 13, 20, 15)))
        far = _gold(self.cfg, meta=_stamp_at("2649.75",
                                             _utc(2026, 10, 13, 19, 5)))
        for when in (_utc(2026, 10, 13, 20, 59), _utc(2026, 10, 13, 21, 1)):
            with _at(when):
                self.assertIsNone(venue_mark.for_booking(old, None), when)
                self.assertIsNone(venue_mark.for_booking(far, None), when)
                mk = venue_mark.for_booking(near, None)
                self.assertEqual(mk.source, venue_mark.VENUE_STALE, when)

    def test_a_print_days_before_the_close_decides_nothing(self):
        """P1: Saturday 2026-10-10 12:00 UTC; the real long's last print
        was Thursday 15:00 at 2700, the platform's quote the future. The
        booking refuses it, and so do the review and the level editor —
        no thesis stop, no R, no side check on a 45-hour print."""
        from bot_program import venue_mark
        from bot_program.adjust_levels import _mark_for
        from brain import position_review as pr
        t = _gold(self.cfg, meta=_stamp_at("2700", _utc(2026, 10, 8, 15, 0)))
        with _at(_utc(2026, 10, 10, 12, 0)):
            mk = venue_mark.resolve(t, None)
            self.assertEqual(mk.source, venue_mark.VENUE_STALE)
            self.assertFalse(venue_mark.bookable(mk, t))
            got = pr._venue_mark_for(pr.bot_position(t))
            self.assertIsNone(_mark_for(t))
        self.assertIsNone(got[0])
        self.assertIn("was not taken at its market's close", got[1])

    def test_the_daily_breaks_older_print_decides_nothing(self):
        """P2: Tuesday 21:30 UTC, inside Globex's daily break, a print from
        09:00 UTC (12.5 h): refused by the booking and the review alike;
        the print at 20:30 decides."""
        from bot_program import venue_mark
        from brain import position_review as pr
        old = _gold(self.cfg, meta=_stamp_at("2700",
                                             _utc(2026, 10, 13, 9, 0)))
        near = _gold(self.cfg, meta=_stamp_at("2700",
                                              _utc(2026, 10, 13, 20, 30)))
        with _at(_utc(2026, 10, 13, 21, 30)):
            self.assertFalse(venue_mark.bookable(venue_mark.resolve(old, None),
                                                 old))
            self.assertIsNone(pr._venue_mark_for(pr.bot_position(old))[0])
            self.assertEqual(pr._venue_mark_for(pr.bot_position(near)),
                             (2700.0, "venue (60 min old, market shut)"))

    def test_an_index_cfd_is_shut_for_the_weekend(self):
        """P3: SPX500 (an index CFD, its quote the cash index) on Saturday
        2026-10-10 12:00 UTC, its last print Friday 20:59 at 5810: the
        venue's price at the close — the review measures at it and the
        editor refuses a long stop above it. On Wednesday it is open."""
        from bot_program import venue_mark
        from bot_program.adjust_levels import _mark_for, validate_levels
        from brain import position_review as pr
        _instrument("SPX500", "index")
        t = self._real("SPX500", "index",
                       _stamp_at("5810", _utc(2026, 10, 9, 20, 59)),
                       entry="5800")
        sat = _utc(2026, 10, 10, 12, 0)
        shut = venue_mark.market_shut(t, now=sat)
        self.assertEqual(shut["closed"], _utc(2026, 10, 9, 21, 0))
        self.assertEqual(shut["reopens"], _utc(2026, 10, 11, 21, 0))
        self.assertIsNone(venue_mark.market_shut(
            t, now=_utc(2026, 10, 14, 12, 0)))
        with _at(sat):
            self.assertEqual(pr._venue_mark_for(pr.bot_position(t)),
                             (5810.0, "venue (15 h old, market shut)"))
            self.assertEqual(_mark_for(t), Decimal("5810.0"))
            self.assertTrue(validate_levels(t, Decimal("5815"), None),
                            "a long stop above Friday's close is refused")

    def test_an_index_cfd_is_never_timed_by_its_cash_market(self):
        """V1: GER40 (an index class with no cash-index stand-in) at
        Wednesday 20:30 UTC — the platform's index clock (NYSE) is shut,
        the CFD's week is open."""
        from bot_program import venue_mark
        from core.exchange_status import market_clock
        _instrument("GER40", "index")
        t = self._real("GER40", "index", {})
        wed = _utc(2026, 10, 14, 20, 30)
        self.assertFalse(market_clock("index", now_utc=wed)["is_open"])
        self.assertIsNone(venue_mark.market_shut(t, now=wed))

    def test_the_level_editor_judges_only_a_live_quote(self):
        """P4: a real EURUSD long in an open market, its last print 30 h
        old and the platform's quote (the venue's own instrument) 20 h
        old: resolve answers the quote, and the editor judges nothing on
        it. A five-minute quote judges."""
        from bot_program import venue_mark
        from bot_program.adjust_levels import _mark_for
        from bot_program.models import AssetBotTrade
        _instrument("EURUSD", "forex")
        _quote("EURUSD", "1.105", asset_class="forex", source="oanda_stream",
               age_s=20 * 3600)
        t = AssetBotTrade.objects.create(
            config=self.cfg, asset_class="forex", symbol="EURUSD",
            side="BUY", qty=Decimal("1000"), entry_price=Decimal("1.1"),
            stop_loss=Decimal("1.09"), status="OPEN", paper=False,
            rule_name="r", metadata={"broker": "etoro",
                                     **_stamp("1.1", age_s=30 * 3600)})
        from market_data.models import LiveQuote
        with _open_market():
            mk = venue_mark.resolve(
                t, LiveQuote.objects.get(instrument__symbol="EURUSD"))
            self.assertEqual(mk.source, venue_mark.QUOTE)
            self.assertIsNone(_mark_for(t))
            _quote("EURUSD", "1.105", asset_class="forex",
                   source="oanda_stream", age_s=300)
            self.assertEqual(_mark_for(t), Decimal("1.105"))

    def test_an_exit_at_a_stale_quote_carries_its_age(self):
        """Q1: Saturday 12:00 UTC, a real EURUSD long with no print, the
        quote taken Friday 20:30 (the venue's own instrument, at the
        close), eToro's ticker down: the exit books at it WITH its age; a
        five-minute quote books none."""
        from bot_program.engine.kill_switch import _market_exit_price
        from bot_program.models import AssetBotTrade
        from market_data.models import LiveQuote
        _instrument("EURUSD", "forex")
        q = _quote("EURUSD", "1.105", asset_class="forex",
                   source="oanda_stream")
        LiveQuote.objects.filter(pk=q.pk).update(
            updated_at=_utc(2026, 10, 9, 20, 30))
        t = AssetBotTrade.objects.create(
            config=self.cfg, asset_class="forex", symbol="EURUSD",
            side="BUY", qty=Decimal("1000"), entry_price=Decimal("1.1"),
            stop_loss=Decimal("1.09"), status="OPEN", paper=False,
            rule_name="r", metadata={"broker": "etoro"})
        dead = mock.MagicMock(spec=["ticker"])
        dead.ticker.side_effect = RuntimeError("down")
        with _at(_utc(2026, 10, 10, 12, 0)):
            price, unpriced, age = _market_exit_price(
                "EURUSD", t.entry_price, client=dead, trade=t)
        self.assertEqual((price, unpriced), (1.105, False))
        self.assertEqual(age, 55800)
        # the reconcile's orphan close writes the same provenance
        from bot_program.reconcile_asset import _close_as_orphan
        orphan = AssetBotTrade.objects.create(
            config=self.cfg, asset_class="forex", symbol="EURUSD",
            side="BUY", qty=Decimal("1000"), entry_price=Decimal("1.1"),
            stop_loss=Decimal("1.09"), status="OPEN", paper=False,
            rule_name="r", metadata={"broker": "etoro"})
        with _at(_utc(2026, 10, 10, 12, 0)), \
                mock.patch(ROUTER, return_value=dead):
            self.assertTrue(_close_as_orphan(orphan))
        orphan = _fresh(orphan)
        self.assertEqual(orphan.exit_price, Decimal("1.105"))
        self.assertEqual(orphan.metadata["exit_mark_age_s"], 55800)
        _quote("EURUSD", "1.105", asset_class="forex", source="oanda_stream",
               age_s=300)
        with _open_market():
            self.assertEqual(_market_exit_price("EURUSD", t.entry_price,
                                                client=dead, trade=t),
                             (1.105, False, None))

    def test_the_shut_began_at_the_venues_real_close(self):
        """E1-E4: the clock's own answer for when the running shut began —
        NYSE's early close and its holiday, the forex weekend before
        Sunday's open, a product's daily gap."""
        from core.exchange_status import market_clock
        self.assertEqual(
            market_clock("stock", now_utc=_utc(2026, 11, 28, 12))["closed"],
            _utc(2026, 11, 27, 18, 0), "the day after Thanksgiving: 13:00 ET")
        self.assertEqual(
            market_clock("stock", now_utc=_utc(2026, 11, 27, 13))["closed"],
            _utc(2026, 11, 25, 21, 0), "Thanksgiving is no session")
        self.assertEqual(
            market_clock("forex", now_utc=_utc(2026, 10, 11, 12))["closed"],
            _utc(2026, 10, 9, 21, 0), "Sunday before the open: Friday")
        self.assertEqual(
            market_clock("commodity", symbol="WHEATUSD",
                         now_utc=_utc(2026, 10, 13, 20, 0))["closed"],
            _utc(2026, 10, 13, 18, 20), "CBOT grains: the 13:20 CT gap")

    def test_a_print_taken_after_the_close_is_the_closes(self):
        """V3: the last candle ends AT the close; a print stamped just
        after the shut began is the close's price too."""
        from bot_program import venue_mark
        t = _gold(self.cfg, meta=_stamp_at("2649.75",
                                           _utc(2026, 10, 9, 21, 0, 30)))
        sat = _utc(2026, 10, 10, 12, 0)
        self.assertTrue(venue_mark.bookable(venue_mark.resolve(t, None,
                                                               now=sat),
                                            t, now=sat))


class TheSpreadIsDatedFromItsReadTests(TestCase):
    """A working fill anchors the spread read at ORDER time only while that
    read is young, dated from the read; TAKE TRADE's working order keeps
    the ticket's sides for its fill; the short side of every fill lane."""

    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user("vmk_sp",
                                                         password="x")

    def _fill_working(self, cfg, trade, avg):
        from bot_program.asset_engine.base import make_bot
        from tests.test_working_entries import _client as wclient
        with mock.patch(ROUTER, return_value=wclient(
                {"state": "filled", "filled": float(trade.metadata.get(
                    "qty_requested") or trade.qty), "avgPrice": avg,
                 "status": "Filled"})):
            make_bot(cfg).manage_positions()
        trade.refresh_from_db()
        return trade.metadata["venue_mark"]

    def test_an_order_time_spread_past_the_bound_anchors_nothing(self):
        """C2: the last look read a 0.8 spread twenty hours before the
        fill: the row is stamped sideless (the next tick measures), and a
        candle after it carries nothing."""
        from bot_program import venue_mark
        from instruments.models import Instrument
        from tests.test_working_entries import _cfg as wcfg, _working_trade
        Instrument.objects.get_or_create(
            symbol="NVDA", defaults={"name": "NVDA", "asset_class": "stock"})
        cfg = wcfg(self.user)
        sent = timezone.now() - timedelta(hours=20)
        t = _working_trade(cfg, entry_quote={"bid": 99.2, "ask": 100.0},
                           entry_working_since=sent.isoformat())
        vm = self._fill_working(cfg, t, 99.75)
        self.assertEqual(vm["price"], 99.75)
        self.assertNotIn("bid", vm)
        self.assertTrue(venue_mark.stamp(t, 99.9, source="ibkr",
                                         via="candle"))
        t.refresh_from_db()
        self.assertNotIn("bid", t.metadata["venue_mark"])

    def test_a_short_working_fill_is_born_at_the_bid(self):
        """S3: a SELL fills at the bid: bid = fill, ask = fill + spread."""
        from instruments.models import Instrument
        from bot_program.models import AssetBotTrade
        from tests.test_working_entries import _cfg as wcfg, _working_trade
        Instrument.objects.get_or_create(
            symbol="NVDA", defaults={"name": "NVDA", "asset_class": "stock"})
        cfg = wcfg(self.user)
        t = _working_trade(cfg, entry_quote={"bid": 99.5, "ask": 100.0},
                           entry_working_since=timezone.now().isoformat())
        AssetBotTrade.objects.filter(pk=t.pk).update(
            side="SELL", stop_loss=Decimal("102"), take_profit=Decimal("96"))
        t.refresh_from_db()
        vm = self._fill_working(cfg, t, 99.5)
        self.assertEqual((vm["price"], vm["bid"], vm["ask"]),
                         (99.5, 99.5, 100.0))

    def test_a_working_take_trade_keeps_the_tickets_sides_for_its_fill(self):
        """TAKE TRADE's working branch: the ticket's bid/ask ride the row
        with the time they were read (entry_quote), and the fill anchors
        them — a manual order eToro held no longer reads exactly zero."""
        from bot_program.models import AssetBotTrade
        from tests.test_take_trade_live import (_arm_live, _components_on,
                                                _fake_live_client, _quote as q,
                                                _signal)
        inst = q("BTCUSD", 60000)
        _components_on()
        cfg = _arm_live(self.user)
        held = {"orderId": "7", "symbol": "BTCUSD", "side": "BUY",
                "executedQty": "0.0", "avgPrice": "0.0",
                "status": "PENDING", "working": True, "raw": {}}
        client = _fake_live_client(held)
        client.ticker.return_value = {"lastPrice": "60000", "bid": "59990",
                                      "ask": "60010"}
        from bot_program.manual_trade import execute_take_trade
        with mock.patch(ROUTER, return_value=client):
            out = execute_take_trade(self.user, _signal(inst), pin_ok=True)
        self.assertTrue(out.get("working"), out)
        t = AssetBotTrade.objects.get(pk=out["trade_id"])
        eq = t.metadata["entry_quote"]
        self.assertEqual((float(eq["bid"]), float(eq["ask"])),
                         (59990.0, 60010.0))
        self.assertEqual(eq["read_at"], t.metadata["entry_working_since"])
        self.assertNotIn("venue_mark", t.metadata)
        vm = self._fill_working(cfg, t, 60012.5)
        self.assertEqual((vm["price"], vm["bid"], vm["ask"]),
                         (60012.5, 59992.5, 60012.5))
        self.assertEqual(vm["spread_from"], eq["read_at"])

    def test_a_short_take_trade_is_born_at_the_bid(self):
        """S1: a bearish ticket read bid 59990 / ask 60010 and filled at
        60012.5: the short is born bid = fill, ask = fill + 20."""
        from bot_program.models import AssetBotTrade
        from tests.test_take_trade_live import (_arm_live, _components_on,
                                                _fake_live_client, _quote as q,
                                                _signal)
        inst = q("BTCUSD", 60000)
        _components_on()
        _arm_live(self.user)
        client = _fake_live_client()
        client.ticker.return_value = {"lastPrice": "60000", "bid": "59990",
                                      "ask": "60010"}
        from bot_program.manual_trade import execute_take_trade
        with mock.patch(ROUTER, return_value=client):
            out = execute_take_trade(
                self.user, _signal(inst, direction="bearish", entry=60000,
                                   stop=60900, target=58200), pin_ok=True)
        self.assertTrue(out.get("ok"), out)
        vm = AssetBotTrade.objects.get(pk=out["trade_id"]).metadata[
            "venue_mark"]
        self.assertEqual((vm["price"], vm["bid"], vm["ask"]),
                         (60012.5, 60012.5, 60032.5))


class AShortBotEntryIsBornAtTheBidTests(TestCase):
    """S2: execute_entry on a LIVE stock config carried by the real
    EtoroTrader over a fake wire (the birth test's fixture), a BEARISH
    signal: the last look read bid 99.9 / ask 100.1, a SELL fills at the
    bid — the new short reads bid = fill, ask = fill + 0.2."""

    def setUp(self):
        from tests.test_entry_quote import (_account, _book,
                                            _clear_eligibility, _instrument,
                                            _live_cfg, _signal, _user)
        self.user = _user("vmk_short")
        self.cfg = _live_cfg(self.user, name="VMS")
        self.cfg.base_currency = "USD"
        self.cfg.extras = {}
        self.cfg.save(update_fields=["base_currency", "extras"])
        _signal(_instrument(), rule="vms_rule", direction="bearish")
        _book(self.user)
        _account(self.user, cash=100000)
        p = mock.patch("bot_program.asset_engine.base.ETORO_PROVEN",
                       frozenset({"stock"}))
        p.start()
        self.addCleanup(p.stop)
        _clear_eligibility()
        self.addCleanup(_clear_eligibility)

    def test_a_short_bot_entry_reads_at_the_ask(self):
        from bot_program.asset_engine.stock_bot import StockBot
        from bot_program.models import AssetBotTrade
        from tests.test_entry_quote import _etoro, _mock_client
        bot = StockBot(self.cfg)
        with mock.patch(ROUTER, return_value=_mock_client("100.00")):
            cand = bot.propose_entry("AAPL")
        self.assertIsNotNone(cand)
        t, _fake = _etoro()
        with mock.patch(ROUTER, return_value=t), mock.patch("time.sleep"):
            res = bot.execute_entry(cand)
        self.assertIsNotNone(res)
        trade = AssetBotTrade.objects.get(id=res["trade_id"])
        self.assertEqual(trade.side, "SELL")
        vm = trade.metadata["venue_mark"]
        price = float(trade.entry_price)
        self.assertEqual((vm["price"], vm["bid"]), (price, price))
        self.assertAlmostEqual(vm["ask"], price + 0.2, places=6)
