"""THE RECONCILE AROUND THE CLOCK (2026-10-06).

GBPNZD #135 was stopped out by eToro in the night and stayed OPEN here until
the 13:00 UTC reconcile: the pass ran 13:00-21:45 only. It now runs every
15 minutes all day, and the review of that change found what an all-day
cadence exposes:

  * the orphan close acted on the row snapshot the pass loaded before any
    broker read: a row the five-minute tick (or the CLOSE button) closed in
    between was overwritten with " | reconciled-orphan", its stale metadata,
    a second grade and a second close alert. The row is now re-read under
    the close claim (manual_close.CLAIM_KEY) and written only while it is
    still open;
  * eToro holds ONE book, and the pass read it once per asset class (four
    GET /portfolio where one answers), in each of its two sweeps;
  * the warm kept asking after the venue refused: one venue-health note per
    symbol, and three inside 180 s mark the venue SICK;
  * the unclaimed-position alert had no memory: one position opened by hand
    in the eToro app rang the phone four times an hour all night.

Run with:  python manage.py test tests.test_reconcile_all_day
"""
from datetime import timedelta
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from tests.test_exit_truth import _cfg, _trade, _user


class EtoroTrader:
    """A one-book venue. The CLASS NAME is what the reconcile keys on, so it
    is named like the adapter and never subclassed."""

    def __init__(self, held=(), world="live", refuse=None):
        self.held = list(held)
        self.world = world
        self.refuse = refuse
        self.reads = 0
        self.named = []

    def _world(self):
        return self.world

    def instrument_id(self, symbol):
        self.named.append(symbol)
        if self.refuse is not None:
            raise self.refuse
        return 1000 + len(self.named)

    def get_positions(self):
        self.reads += 1
        return [{"symbol": s} for s in self.held]

    def ticker(self, symbol):
        return {"lastPrice": "101"}


class IBKRTrader(EtoroTrader):
    """Class-keyed like every venue but eToro (a subclass only for its
    name: _state_key reads type(client).__name__)."""


def _reconcile(user, client):
    from bot_program.reconcile_asset import reconcile_user
    with mock.patch("bot_program.engine.broker_router.client_for_symbol",
                    return_value=client):
        return reconcile_user(user)


class TheRowIsReadAgainBeforeItIsClosedTests(TestCase):

    def setUp(self):
        self.user = _user("allday_u")
        self.cfg = _cfg(self.user)

    def test_a_row_closed_after_the_snapshot_keeps_its_own_close(self):
        """The tick closes the row between the pass's snapshot and its
        /portfolio read, and eToro has already dropped the position."""
        from bot_program.models import AssetBotTrade
        from bot_program import reconcile_asset as ra
        trade = _trade(self.cfg)
        real = ra._broker_open_symbols

        def tick_closes_it_meanwhile(client, **kw):
            AssetBotTrade.objects.filter(pk=trade.pk).update(
                status="CLOSED", reason="closed:SL",
                closed_at=timezone.now(),
                metadata={"initial_stop_loss": 98.0,
                          "close_sent_at": "2026-10-06T02:00:00+00:00"})
            return real(client, **kw)

        with mock.patch.object(ra, "_broker_open_symbols",
                               side_effect=tick_closes_it_meanwhile), \
                mock.patch("bot_program.bot_grading.grade_bot_trade") as graded:
            out = _reconcile(self.user, EtoroTrader())
        trade.refresh_from_db()
        self.assertEqual(trade.reason, "closed:SL")
        self.assertIn("close_sent_at", trade.metadata)
        self.assertEqual(out["closed_as_orphan"], 0)
        self.assertEqual(out["closed_elsewhere"], 1)
        graded.assert_not_called()

    def test_a_row_another_path_is_closing_is_left_to_it(self):
        from bot_program.manual_close import CLAIM_KEY
        trade = _trade(self.cfg, metadata={
            "initial_stop_loss": 98.0,
            CLAIM_KEY: timezone.now().isoformat()})
        out = _reconcile(self.user, EtoroTrader())
        trade.refresh_from_db()
        self.assertEqual(trade.status, "OPEN")
        self.assertEqual(out["closed_as_orphan"], 0)
        self.assertEqual(out["closed_elsewhere"], 1)

    def test_a_stale_claim_does_not_keep_an_orphan_open(self):
        from bot_program.manual_close import CLAIM_KEY, CLAIM_TTL_SECONDS
        old = timezone.now() - timedelta(seconds=CLAIM_TTL_SECONDS + 5)
        trade = _trade(self.cfg, metadata={"initial_stop_loss": 98.0,
                                           CLAIM_KEY: old.isoformat()})
        out = _reconcile(self.user, EtoroTrader())
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSED")
        self.assertEqual(out["closed_as_orphan"], 1)

    def test_the_claim_is_released_after_the_orphan_close(self):
        from bot_program.manual_close import CLAIM_KEY
        trade = _trade(self.cfg)
        out = _reconcile(self.user, EtoroTrader())
        trade.refresh_from_db()
        self.assertEqual(out["closed_as_orphan"], 1)
        self.assertEqual(trade.status, "CLOSED")
        self.assertIn("reconciled-orphan", trade.reason)
        self.assertNotIn(CLAIM_KEY, trade.metadata)

    def test_the_write_itself_refuses_a_row_closed_while_it_was_priced(self):
        """The broker reads in _close_as_orphan take seconds; a close that
        lands in them keeps its words."""
        from bot_program.models import AssetBotTrade
        from bot_program.reconcile_asset import _close_as_orphan
        trade = _trade(self.cfg)
        snapshot = AssetBotTrade.objects.get(pk=trade.pk)
        AssetBotTrade.objects.filter(pk=trade.pk).update(
            status="CLOSED", reason="closed:TP", closed_at=timezone.now())
        with mock.patch("bot_program.engine.broker_router.client_for_symbol",
                        return_value=EtoroTrader()), \
                mock.patch("bot_program.notifications."
                           "notify_bot_fill_close") as told:
            self.assertFalse(_close_as_orphan(snapshot))
        trade.refresh_from_db()
        self.assertEqual(trade.reason, "closed:TP")
        told.assert_not_called()


class OneEtoroBookIsReadOncePerPassTests(TestCase):

    def setUp(self):
        self.user = _user("onebook_u")
        self.stock = _cfg(self.user, name="ST")
        self.fx = _cfg(self.user, name="FX", asset_class="forex")
        self.fx.symbols = ["EURUSD"]
        self.fx.save(update_fields=["symbols"])

    def test_the_row_pass_reads_the_book_once_for_every_class(self):
        _trade(self.stock)
        _trade(self.fx, symbol="EURUSD")
        venue = EtoroTrader(held=["AAPL", "EURUSD"])
        out = _reconcile(self.user, venue)
        self.assertEqual(venue.reads, 1)
        self.assertEqual(out["checked"], 2)
        self.assertEqual(out["closed_as_orphan"], 0)

    def test_the_two_worlds_are_two_books(self):
        from bot_program.reconcile_asset import _state_key
        self.assertNotEqual(_state_key(EtoroTrader(world="live"), "stock"),
                            _state_key(EtoroTrader(world="demo"), "stock"))
        self.assertEqual(_state_key(EtoroTrader(), "stock"),
                         _state_key(EtoroTrader(), "forex"))

    def test_another_venue_is_still_read_per_class(self):
        _trade(self.stock)
        _trade(self.fx, symbol="EURUSD")
        venue = IBKRTrader(held=["AAPL", "EURUSD"])
        _reconcile(self.user, venue)
        self.assertEqual(venue.reads, 2)

    def test_the_sweep_reads_the_book_once_warmed_with_every_class(self):
        from bot_program.reconcile_asset import reconcile_unknown_positions
        venue = EtoroTrader(held=["AAPL", "EURUSD"])
        with mock.patch("bot_program.engine.broker_router.client_for_symbol",
                        return_value=venue), \
                mock.patch("bot_program.notifications."
                           "notify_unclaimed_position") as paged:
            out = reconcile_unknown_positions(self.user)
        self.assertEqual(venue.reads, 1)
        self.assertEqual(sorted(venue.named), ["AAPL", "EURUSD"])
        self.assertEqual(out["checked"], 1)
        self.assertEqual(out["unclaimed"], 2)
        paged.assert_called_once()


class TheWarmStopsAtTheFirstRefusalTests(TestCase):

    def _warm(self, refuse):
        from bot_program.reconcile_asset import _broker_open_symbols
        venue = EtoroTrader(refuse=refuse)
        state = _broker_open_symbols(venue, asset_class="stock",
                                     warm=["AAPL", "MSFT", "NVDA"])
        return venue, state

    def test_a_refused_ask_ends_the_warm(self):
        """Each further ask is another venue-health note; three inside
        180 s mark eToro SICK and refuse every new real entry."""
        venue, state = self._warm(RuntimeError("429 Too Many Requests"))
        self.assertEqual(venue.named, ["AAPL"])
        self.assertIsNotNone(state, "the book is still read")

    def test_an_unknown_spelling_does_not(self):
        venue, _state = self._warm(LookupError("no such symbol"))
        self.assertEqual(venue.named, ["AAPL", "MSFT", "NVDA"])


class TheUnclaimedAlertIsSaidOnceTests(TestCase):

    def setUp(self):
        self.user = _user("unclaimed_once_u")

    def _say(self, symbols, venue="eToro"):
        from bot_program.notifications import notify_unclaimed_position
        with mock.patch("requests.post"):
            return notify_unclaimed_position(self.user, symbols=symbols,
                                             venue=venue)

    def _bells(self):
        from alerts.models import Notification
        return Notification.objects.filter(user=self.user,
                                           title__contains="no row claims")

    def test_a_standing_set_is_said_once_a_window(self):
        self._say(["XAUUSD"])
        self.assertFalse(self._say(["XAUUSD"]))
        self.assertEqual(self._bells().count(), 1)

    def test_a_changed_set_is_said_at_once(self):
        self._say(["XAUUSD"])
        self._say(["NVDA"])
        self._say(["NVDA", "XAUUSD"])
        self.assertEqual(self._bells().count(), 3)

    def test_another_venue_is_its_own_condition(self):
        self._say(["XAUUSD"])
        self._say(["XAUUSD"], venue="Saxo")
        self.assertEqual(self._bells().count(), 2)

    def test_it_is_said_again_once_the_window_has_passed(self):
        from bot_program.notifications import UNCLAIMED_REMIND_S
        self._say(["XAUUSD"])
        self._bells().update(created_at=timezone.now() - timedelta(
            seconds=UNCLAIMED_REMIND_S + 1))
        self._say(["XAUUSD"])
        self.assertEqual(self._bells().count(), 2)

    def test_the_window_is_morguls_reminder(self):
        from bot_program import morgul
        from bot_program.notifications import UNCLAIMED_REMIND_S
        self.assertEqual(UNCLAIMED_REMIND_S, morgul.REMIND_S)
