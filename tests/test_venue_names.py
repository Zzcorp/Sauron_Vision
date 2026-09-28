"""A POSITION THE PLATFORM CANNOT NAME IS NOT A POSITION THAT IS GONE.

Found by a completeness critic asked "what does none of these look at?" —
the same seat that found eToro closing by opening. Every test here is a
failure that was reachable at HEAD aa53b4d on the venue being keyed tonight,
and three of them would have booked a live position CLOSED in the database
while the money was still at the broker.

THE DEFECT. EtoroTrader answers a position read with instrumentIds and puts
a platform name on one only from the reverse map that same client instance
filled — `self._symbols`, written solely inside `instrument_id()` and read
with the sentinel fallback `ETORO:{iid}`. The router builds a FRESH client
on every call. So any reader that did not itself place an order sees a book
spelled ETORO:1001, and every question of the form "is this still there?"
answers no:

  * reconcile_asset orphan-closed the row, labelled manual_close, every 15
    minutes;
  * the CLOSE_PENDING drain read FLAT and booked the row closed at a mark
    nobody filled at, every 300 s, on a beat that is deliberately ungated
    so neither the kill switch nor any component row can stop it;
  * the engine's in-doubt branch read False as "the broker is flat and
    nothing is sent", so a close that may never have landed was never
    re-sent;
  * and the unclaimed sweep reported every eToro position as unclaimed
    under a name no human can look up.

THE SHAPE OF THE FIX is the one this repo uses everywhere: three states, and
the third one travels WITH the reading. `symbol_unresolved` beside the name,
and then "could not name it" is never "not there". The warm — the adapter's
own `instrument_id()`, called for the symbols a reader is about to ask about
— is what keeps the honest answer from being "unreadable" for ever.

AND THE SNAPSHOT KEY. `_broker_snapshot` cached one venue's position list
under `id(client)` while `client` is rebound per row in the same pass and
nothing holds the old one. A freed address can be reused, and the hit would
answer one venue's row out of another venue's book. The invariant is tested
here as what it is: the key holds the venue, not the object.
"""
from decimal import Decimal
from unittest import mock

from django.test import TestCase

from tests.test_exit_truth import _cfg, _trade, _user


def _etoro():
    from bot_program.engine.etoro_client import EtoroTrader
    return EtoroTrader("key", "user", env="demo")


def _positions_client(rows, *, instrument_id=None):
    """A duck-typed client whose book is `rows`."""
    c = mock.MagicMock()
    c.get_positions = mock.MagicMock(return_value=list(rows))
    if instrument_id is None:
        del c.instrument_id
    else:
        c.instrument_id = instrument_id
    return c


class AdapterNamesItsOwnBook(TestCase):
    """The two live venues report whether they could name what they found."""

    def test_a_cold_etoro_client_flags_the_position_it_cannot_name(self):
        t = _etoro()
        with mock.patch.object(
                t, "_open_positions",
                return_value=[{"instrumentID": 1001, "units": 3,
                               "isBuy": True, "positionID": "p1"}]):
            rows = t.get_positions()
        self.assertEqual(rows[0]["symbol"], "ETORO:1001")
        self.assertIs(rows[0]["symbol_unresolved"], True)

    def test_a_warm_etoro_client_does_not_flag_it(self):
        t = _etoro()
        t._symbols[1001] = "EURUSD"
        with mock.patch.object(
                t, "_open_positions",
                return_value=[{"instrumentID": 1001, "units": 3,
                               "isBuy": True, "positionID": "p1"}]):
            rows = t.get_positions()
        self.assertEqual(rows[0]["symbol"], "EURUSD")
        self.assertNotIn("symbol_unresolved", rows[0])

    def test_saxo_flags_only_the_position_nothing_named(self):
        from bot_program.engine import saxo_client as sx
        t = sx.SaxoTrader.__new__(sx.SaxoTrader)
        lots = [
            {"PositionBase": {"Uic": 21, "AssetType": "FxSpot", "Amount": 5,
                              "OpenPrice": 1.1},
             "PositionView": {}, "PositionId": "a",
             "DisplayAndFormat": {"Symbol": "EURUSD:xcfd"}},
            {"PositionBase": {"Uic": 99, "AssetType": "FxSpot", "Amount": 5,
                              "OpenPrice": 1.1},
             "PositionView": {}, "PositionId": "b"},
        ]
        with mock.patch.dict(sx._SYMBOL_BY_UIC, {}, clear=True), \
                mock.patch.object(sx.SaxoTrader, "_positions",
                                  return_value=lots):
            rows = t.get_positions()
        self.assertEqual(rows[0]["symbol"], "EURUSD")
        self.assertNotIn("symbol_unresolved", rows[0])
        self.assertEqual(rows[1]["symbol"], "UIC99")
        self.assertIs(rows[1]["symbol_unresolved"], True)


class TheReaderCountsWhatItCouldNotName(TestCase):

    def test_an_unnamed_position_is_counted_and_left_out_of_symbols(self):
        from bot_program.reconcile_asset import _broker_open_symbols
        client = _positions_client([
            {"symbol": "AAPL"},
            {"symbol": "ETORO:1001", "symbol_unresolved": True},
        ])
        state = _broker_open_symbols(client, asset_class="stock")
        self.assertEqual(state["symbols"], {"AAPL"})
        self.assertEqual(state["unnamed"], 1)

    def test_a_magic_mock_row_is_not_read_as_unnameable(self):
        """`is True`, not a truth test: a Mock answers every attribute."""
        from bot_program.reconcile_asset import _broker_open_symbols
        row = mock.MagicMock()
        row.symbol = "AAPL"
        row.sec_type = None
        client = _positions_client([row])
        state = _broker_open_symbols(client, asset_class="stock")
        self.assertEqual(state["unnamed"], 0)
        self.assertEqual(state["symbols"], {"AAPL"})

    def test_the_reader_warms_the_names_it_was_given(self):
        from bot_program.reconcile_asset import _broker_open_symbols
        warm = mock.MagicMock(return_value=7)
        client = _positions_client([{"symbol": "AAPL"}], instrument_id=warm)
        _broker_open_symbols(client, asset_class="stock",
                             warm=("AAPL", "MSFT"))
        self.assertEqual(sorted(c.args[0] for c in warm.call_args_list),
                         ["AAPL", "MSFT"])

    def test_a_warm_that_raises_is_not_fatal(self):
        from bot_program.reconcile_asset import _broker_open_symbols
        warm = mock.MagicMock(side_effect=LookupError("eToro knows no AAPL"))
        client = _positions_client([{"symbol": "AAPL"}], instrument_id=warm)
        state = _broker_open_symbols(client, asset_class="stock",
                                     warm=("AAPL",))
        self.assertEqual(state["symbols"], {"AAPL"})


class ReconcileDoesNotCloseWhatItCannotSee(TestCase):

    def setUp(self):
        self.user = _user("names_u")
        self.cfg = _cfg(self.user)
        self.trade = _trade(self.cfg)

    def _run(self, rows):
        from bot_program.reconcile_asset import reconcile_user
        client = _positions_client(rows)
        with mock.patch("bot_program.engine.broker_router.client_for_symbol",
                        return_value=client):
            return reconcile_user(self.user)

    def test_an_unnameable_book_closes_nothing(self):
        out = self._run([{"symbol": "ETORO:1001",
                          "symbol_unresolved": True}])
        self.trade.refresh_from_db()
        self.assertEqual(self.trade.status, "OPEN")
        self.assertEqual(out["closed_as_orphan"], 0)
        self.assertEqual(out["broker_unavailable"], 1)

    def test_a_readable_book_still_closes_the_orphan(self):
        """The regression guard: reconciliation must not go inert."""
        out = self._run([{"symbol": "MSFT"}])
        self.trade.refresh_from_db()
        self.assertEqual(self.trade.status, "CLOSED")
        self.assertEqual(out["closed_as_orphan"], 1)

    def test_a_named_match_is_still_left_open(self):
        out = self._run([{"symbol": "AAPL"}])
        self.trade.refresh_from_db()
        self.assertEqual(self.trade.status, "OPEN")
        self.assertEqual(out["closed_as_orphan"], 0)


class TheSweepNamesNothingItInvented(TestCase):

    def test_an_unnameable_position_is_an_unreadable_book_not_an_alarm(self):
        from bot_program.reconcile_asset import reconcile_unknown_positions
        user = _user("sweep_u")
        _cfg(user)
        client = _positions_client([{"symbol": "ETORO:1001",
                                     "symbol_unresolved": True}])
        with mock.patch("bot_program.engine.broker_router.client_for_symbol",
                        return_value=client):
            out = reconcile_unknown_positions(user)
        self.assertEqual(out["symbols"], [])
        self.assertEqual(out["unclaimed"], 0)
        self.assertEqual(out["broker_unavailable"], 1)

    def test_the_named_half_of_a_part_read_book_is_still_reported(self):
        from bot_program.reconcile_asset import reconcile_unknown_positions
        user = _user("sweep_u2")
        _cfg(user)
        client = _positions_client([
            {"symbol": "ETORO:1001", "symbol_unresolved": True},
            {"symbol": "TSLA"},
        ])
        with mock.patch("bot_program.engine.broker_router.client_for_symbol",
                        return_value=client):
            out = reconcile_unknown_positions(user)
        self.assertEqual(out["symbols"], ["TSLA"])
        self.assertEqual(out["broker_unavailable"], 1)


class TheDrainReadsUnknownNotFlat(TestCase):

    def setUp(self):
        self.user = _user("drain_u")
        self.cfg = _cfg(self.user)
        self.trade = _trade(self.cfg, status="CLOSE_PENDING")

    def test_an_unnameable_book_is_unknown(self):
        from bot_program.pending_closes import POS_UNKNOWN, broker_exposure
        client = _positions_client([{"symbol": "ETORO:1001", "qty": 10,
                                     "side": "BUY",
                                     "symbol_unresolved": True}])
        state = broker_exposure(self.trade, client)
        self.assertEqual(state["state"], POS_UNKNOWN)
        self.assertIn("could not be named", state["why"])

    def test_a_readable_empty_book_is_still_flat(self):
        """The regression guard: the drain must still be able to conclude."""
        from bot_program.pending_closes import POS_FLAT, broker_exposure
        client = _positions_client([{"symbol": "MSFT", "qty": 4,
                                     "side": "BUY"}])
        self.assertEqual(broker_exposure(self.trade, client)["state"],
                         POS_FLAT)

    def test_a_named_lot_outranks_an_unnamed_one(self):
        from bot_program.pending_closes import POS_HELD, broker_exposure
        client = _positions_client([
            {"symbol": "AAPL", "qty": 10, "side": "BUY"},
            {"symbol": "ETORO:1001", "qty": 5, "side": "BUY",
             "symbol_unresolved": True},
        ])
        state = broker_exposure(self.trade, client)
        self.assertEqual(state["state"], POS_HELD)
        self.assertEqual(state["qty"], Decimal("10"))

    def test_the_drain_warms_the_name_before_asking(self):
        from bot_program.pending_closes import broker_exposure
        warm = mock.MagicMock(return_value=1)
        client = _positions_client([{"symbol": "AAPL", "qty": 10,
                                     "side": "BUY"}], instrument_id=warm)
        broker_exposure(self.trade, client)
        warm.assert_called_once_with("AAPL")


class TheEngineSaysCannotSay(TestCase):

    def setUp(self):
        self.user = _user("engine_u")
        self.cfg = _cfg(self.user)
        self.trade = _trade(self.cfg)

    def _bot(self):
        from bot_program.asset_engine.stock_bot import StockBot
        return StockBot(self.cfg)

    def test_an_unnamed_row_makes_the_answer_none(self):
        self.assertIsNone(self._bot()._broker_still_holds(
            self.trade, [{"symbol": "ETORO:1001", "qty": 10, "side": "BUY",
                          "symbol_unresolved": True}]))

    def test_a_named_book_with_no_match_is_still_false(self):
        self.assertIs(self._bot()._broker_still_holds(
            self.trade, [{"symbol": "MSFT", "qty": 10, "side": "BUY"}]),
            False)


class TheSnapshotIsKeyedOnTheVenue(TestCase):
    """Never on the object's address — a freed id() is handed out again."""

    class _VenueA:
        def __init__(self):
            self.calls = 0

        def get_positions(self):
            self.calls += 1
            return [{"symbol": "AAPL"}]

    class _VenueB(_VenueA):
        pass

    def setUp(self):
        self.user = _user("snap_u")
        self.cfg = _cfg(self.user)

    def _bot(self):
        from bot_program.asset_engine.stock_bot import StockBot
        bot = StockBot(self.cfg)
        bot._tick_broker_cache = {}
        return bot

    def test_two_clients_of_one_venue_share_one_read(self):
        bot = self._bot()
        a, b = self._VenueA(), self._VenueA()
        bot._broker_snapshot(a, "positions")
        bot._broker_snapshot(b, "positions")
        self.assertEqual((a.calls, b.calls), (1, 0))

    def test_two_venues_do_not_share_a_read(self):
        bot = self._bot()
        a, b = self._VenueA(), self._VenueB()
        bot._broker_snapshot(a, "positions")
        bot._broker_snapshot(b, "positions")
        self.assertEqual((a.calls, b.calls), (1, 1))
