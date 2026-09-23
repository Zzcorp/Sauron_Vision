"""THE ROW KNOWS WHO CARRIED IT. NOTHING THAT CLOSES IT ASKED.

`execute_entry` stamps `entry_meta["broker"]` with the adapter that actually
carried the entry, and until this change the ONLY reader of that field was the
/treasury/ display. Every path that can BOOK a close rebuilds the client from
today's primary-for flag instead — the manage loop, reconcile, and the kill
switch. So moving one checkbox makes reconciliation ask the WRONG venue about
a live position, get an honest "I do not hold that", and orphan-close a row
whose leg is still open somewhere else.

The `unnamed` valve from 2431d96 cannot catch this: the wrong venue can name
everything IT holds, so `unnamed` is 0 and the miss looks like an absence.

IT IS NOT HYPOTHETICAL. On 2026-09-22 the operator was about to key eToro with
three stale IBKR rows still OPEN. Ticking "stocks" would have routed all three
to eToro, eToro would have said it holds no GLDM, and all three would have been
booked CLOSED at an estimated mark inside fifteen minutes — by the wrong venue,
at invented prices.

AND THE ONE CLASS SAXO COULD NOT CLAIM. IBKR and eToro both map "index" onto
their stocks boolean; Saxo did not. The divergence that closes was found by a
refuter, not by the suite: `broker_vision` attributes a row by the CONFIG's
class while the router asks the INSTRUMENT's, so a Saxo row flagged for stocks
would have had /treasury/ print "saxo" for a row holding SPX500 while the close
went to IBKR. The label ships with it, because on Saxo an index is a leveraged
CFD and the box said "stocks · ETFs".
"""
from decimal import Decimal
from unittest import mock

from django.test import TestCase

from tests.test_exit_truth import _cfg, _trade, _user


class _Book:
    """A client whose CLASS NAME decides its adapter key, as the map does."""

    def __init__(self, symbols=()):
        self._symbols = list(symbols)

    def get_positions(self):
        """A bare symbol becomes {"symbol": s}; a dict passes through, so a
        caller can give qty and side. The CLASS NAME is what adapter_key
        reads, so these must not be subclassed in a test — a subclass is a
        name the map has never heard of, and the guard would correctly refuse
        to compare against it."""
        return [r if isinstance(r, dict) else {"symbol": r}
                for r in self._symbols]

    def ticker(self, symbol):
        return {"lastPrice": "101"}


class IBKRTrader(_Book):
    pass


class EtoroTrader(_Book):
    pass


class _Stranger(_Book):
    """A class the adapter map has never heard of — adapter_key answers ""."""


class AMissAtTheWrongVenueIsNotAnAbsence(TestCase):

    def setUp(self):
        self.user = _user("drift_u")
        self.cfg = _cfg(self.user)

    def _row(self, **meta):
        base = {"initial_stop_loss": 98.0}
        base.update(meta)
        return _trade(self.cfg, metadata=base)

    def _run(self, client):
        from bot_program.reconcile_asset import reconcile_user
        with mock.patch("bot_program.engine.broker_router.client_for_symbol",
                        return_value=client):
            return reconcile_user(self.user)

    def test_a_row_carried_elsewhere_is_not_orphan_closed(self):
        """The whole finding, in one assertion."""
        trade = self._row(broker="ibkr")
        out = self._run(EtoroTrader())
        trade.refresh_from_db()
        self.assertEqual(trade.status, "OPEN")
        self.assertIsNone(trade.exit_price)
        self.assertEqual(out["closed_as_orphan"], 0)
        self.assertEqual(out["broker_unavailable"], 1)

    def test_the_same_venue_still_orphan_closes(self):
        """The regression guard: reconciliation must not go inert."""
        trade = self._row(broker="ibkr")
        out = self._run(IBKRTrader())
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSED")
        self.assertEqual(out["closed_as_orphan"], 1)

    def test_a_row_with_no_recorded_carrier_keeps_the_old_behaviour(self):
        """Anything opened before 2026-09-19 carries no `broker` key. Cannot
        tell is not a refusal — it is exactly what it was."""
        trade = self._row()
        out = self._run(EtoroTrader())
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSED")
        self.assertEqual(out["closed_as_orphan"], 1)

    def test_an_unrecognised_client_is_cannot_tell_not_drift(self):
        """adapter_key answers "" for a class it does not know, and "" is not
        a venue name to compare against."""
        trade = self._row(broker="ibkr")
        out = self._run(_Stranger())
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSED")
        self.assertEqual(out["closed_as_orphan"], 1)

    def test_a_row_the_wrong_venue_happens_to_name_is_still_left_open(self):
        """Belt and braces: even a symbol match must not close it, and it
        must not be counted as a drift refusal either."""
        trade = self._row(broker="ibkr")
        out = self._run(EtoroTrader(["AAPL"]))
        trade.refresh_from_db()
        self.assertEqual(trade.status, "OPEN")
        self.assertEqual(out["closed_as_orphan"], 0)


class SaxoCanCarryAnIndex(TestCase):

    def setUp(self):
        from tests.test_saxo_wiring import saxo
        self.user = _user("idx_u")
        self.acct = saxo(self.user, flags=("stock",), sim=True)

    def test_index_rides_on_the_stocks_box(self):
        self.assertTrue(self.acct.is_primary_for("index"))
        self.assertTrue(self.acct.is_primary_for("etf"))

    def test_index_is_not_claimed_when_stocks_is_not(self):
        self.acct.is_primary_for_stocks = False
        self.acct.save(update_fields=["is_primary_for_stocks"])
        self.assertFalse(self.acct.is_primary_for("index"))

    def test_all_three_rows_agree_on_every_catalogue_class(self):
        """The only thing that stops the next omission: one shared list,
        walked against all three rows. Saxo was the odd one out on `index`
        for days and nothing in 7,445 tests noticed."""
        from bot_program.models import EtoroAccount, IBKRAccount, SaxoAccount
        shared = ("stock", "etf", "index", "forex", "commodity")
        rows = (SaxoAccount(is_primary_for_stocks=True),
                EtoroAccount(is_primary_for_stocks=True),
                IBKRAccount(is_primary_for_stocks=True))
        for cls in shared:
            answers = {type(r).__name__: r.is_primary_for(cls) for r in rows}
            self.assertEqual(
                len(set(answers.values())), 1,
                f"the three rows disagree on {cls!r}: {answers}")

    def test_an_index_symbol_routes_to_saxo_when_saxo_carries_stocks(self):
        from bot_program.engine.broker_router import broker_name_for_symbol
        from tests.test_saxo_wiring import _fresh, _instrument
        _instrument("SPX500", "index")
        cfg = _cfg(self.user, name="IDX")
        self.assertEqual(
            broker_name_for_symbol(_fresh(self.user), "SPX500", cfg), "saxo")

    def test_an_index_symbol_does_not_route_to_saxo_without_the_box(self):
        from bot_program.engine.broker_router import broker_name_for_symbol
        from tests.test_saxo_wiring import _fresh, _instrument
        _instrument("SPX500", "index")
        self.acct.is_primary_for_stocks = False
        self.acct.save(update_fields=["is_primary_for_stocks"])
        cfg = _cfg(self.user, name="IDX2")
        self.assertNotEqual(
            broker_name_for_symbol(_fresh(self.user), "SPX500", cfg), "saxo")


class TheLabelSaysWhatTheBoxDoes(TestCase):
    """House rule 3 applied to the checkbox: on Saxo an index is a leveraged
    CFD, and one box routes it. eToro's label already named indices and
    Saxo's own commodity box already said CFD."""

    def test_the_field_names_indices_and_the_cfd(self):
        from bot_program.models import SaxoAccount
        text = SaxoAccount._meta.get_field("is_primary_for_stocks").help_text
        self.assertIn("index", text.lower())
        self.assertIn("CfdOnIndex", text)

    def test_the_checkbox_names_indices_and_the_cfd(self):
        import io
        from django.conf import settings
        page = io.open(settings.BASE_DIR / "templates" / "dashboard"
                       / "brokers.html", encoding="utf-8").read()
        line = [ln for ln in page.splitlines()
                if 'name="primary_stocks"' in ln and "Saxo" not in ln]
        self.assertTrue(line, "the primary_stocks boxes vanished")
        saxo_box = line[-1]
        self.assertIn("indices", saxo_box)
        self.assertIn("(CFD)", saxo_box)


class TheClaimsColumnIsNotDuplicated(TestCase):
    """`index` is deliberately NOT added to broker_vision.ROUTABLE_CLASSES:
    `_claims` skips "etf" because it rides on the stocks boolean, and index
    rides on the same one, so listing it would print one column twice in the
    treasury claims line."""

    def test_index_is_absent_from_the_claims_vocabulary(self):
        from bot_program.broker_vision import ROUTABLE_CLASSES
        self.assertNotIn("index", ROUTABLE_CLASSES)

    def test_the_claims_column_does_not_repeat_the_stocks_column(self):
        from tests.test_saxo_wiring import saxo
        from bot_program.broker_vision import _claims
        acct = saxo(_user("claims_u"), flags=("stock", "forex"), sim=True)
        self.assertEqual(_claims(acct), ["stock", "forex"])


class ARowNobodyStampedIsUnattributable(TestCase):
    """The hole a refuter found in the guard above, before the eToro path fix
    could walk into it.

    `execute_entry` only began stamping metadata["broker"] on 2026-09-22, so
    every older row carries nothing and the drift check waived. That was
    harmless only while the eToro paths were broken — a real key made
    get_positions RAISE, and a raise is "could not ask". Fix the paths and the
    same call returns an empty book, `unnamed` reads 0 because eToro names its
    own book perfectly well, and every carrier-less row is orphan-closed at
    entry price with P&L zero.

    The rule is deliberately narrow: ambiguous only when MORE THAN ONE venue
    is keyed. One keyed broker has nothing to be confused with.
    """

    def setUp(self):
        from tests.test_saxo_wiring import etoro, saxo
        self.user = _user("amb_u")
        self.cfg = _cfg(self.user)
        self.saxo, self.etoro = saxo, etoro

    def _row(self, **meta):
        base = {"initial_stop_loss": 98.0}
        base.update(meta)
        return _trade(self.cfg, metadata=base)

    def _run(self, client):
        from bot_program.reconcile_asset import reconcile_user
        from tests.test_saxo_wiring import _fresh
        with mock.patch("bot_program.engine.broker_router.client_for_symbol",
                        return_value=client):
            return reconcile_user(_fresh(self.user))

    def test_two_keyed_venues_make_a_carrier_less_row_unclosable(self):
        self.saxo(self.user, flags=("stock",), sim=True)
        self.etoro(self.user, flags=("forex",))
        trade = self._row()
        out = self._run(EtoroTrader())
        trade.refresh_from_db()
        self.assertEqual(trade.status, "OPEN")
        self.assertEqual(out["closed_as_orphan"], 0)
        self.assertEqual(out["broker_unavailable"], 1)

    def test_one_keyed_venue_keeps_todays_behaviour(self):
        """Not "never close old rows" — "do not close a row two venues could
        explain". With one broker there is nothing to be confused with."""
        self.etoro(self.user, flags=("stock",))
        trade = self._row()
        out = self._run(EtoroTrader())
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSED")
        self.assertEqual(out["closed_as_orphan"], 1)

    def test_a_stamped_row_at_its_own_venue_still_closes(self):
        self.saxo(self.user, flags=("stock",), sim=True)
        self.etoro(self.user, flags=("forex",))
        trade = self._row(broker="etoro")
        out = self._run(EtoroTrader())
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSED")
        self.assertEqual(out["closed_as_orphan"], 1)

    def test_a_row_filled_live_is_not_compared_against_the_demo_book(self):
        """broker_router builds the eToro client from the account's Demo
        flag at call time; a rehearsal week with live rows open must not
        orphan-close them against the demo portfolio. `env` is set on the
        INSTANCE: the class name, which adapter_key reads, is unchanged."""
        from bot_program.reconcile_asset import unattributable
        self.saxo(self.user, flags=("stock",), sim=True)
        self.etoro(self.user, flags=("forex",))
        trade = self._row(broker="etoro", broker_env="live")
        book = EtoroTrader()
        book.env = "demo"
        self.assertIn("filled in the live world",
                      unattributable(trade, book, keyed=2))
        out = self._run(book)
        trade.refresh_from_db()
        self.assertEqual(trade.status, "OPEN")
        self.assertEqual(out["closed_as_orphan"], 0)
        self.assertEqual(out["broker_unavailable"], 1)

    def test_the_same_world_or_no_world_refuses_nothing(self):
        """Three states, both sides."""
        from bot_program.reconcile_asset import unattributable
        trade = self._row(broker="etoro", broker_env="live")
        same = EtoroTrader()
        same.env = "live"
        self.assertEqual(unattributable(trade, same, keyed=2), "")
        self.assertEqual(unattributable(trade, EtoroTrader(), keyed=2), "")
        unstamped = self._row(broker="etoro")
        demo = EtoroTrader()
        demo.env = "demo"
        self.assertEqual(unattributable(unstamped, demo, keyed=2), "")

    def test_the_count_reads_keys_not_rows(self):
        from bot_program.reconcile_asset import keyed_venue_count
        from tests.test_saxo_wiring import _fresh
        self.assertEqual(keyed_venue_count(_fresh(self.user)), 0)
        self.saxo(self.user, flags=("stock",), sim=True)
        self.assertEqual(keyed_venue_count(_fresh(self.user)), 1)
        self.etoro(self.user, flags=("forex",))
        self.assertEqual(keyed_venue_count(_fresh(self.user)), 2)

    def test_an_unkeyed_row_does_not_count(self):
        from bot_program.models import EtoroAccount
        from bot_program.reconcile_asset import keyed_venue_count
        from tests.test_saxo_wiring import _fresh
        self.saxo(self.user, flags=("stock",), sim=True)
        EtoroAccount.objects.create(user=self.user)   # exists, no credentials
        self.assertEqual(keyed_venue_count(_fresh(self.user)), 1)


class TheDrainRefusesAnUnattributableBook(TestCase):
    """pending_closes had NO drift guard at all — 5078365 claimed every
    booking path was covered and never touched the file. `_finalise_flat`
    books a close on POS_FLAT, so the same wrong-venue miss lands there."""

    def setUp(self):
        from tests.test_saxo_wiring import etoro, saxo
        self.user = _user("drain_amb_u")
        self.cfg = _cfg(self.user)
        saxo(self.user, flags=("stock",), sim=True)
        etoro(self.user, flags=("forex",))
        self.trade = _trade(self.cfg, status="CLOSE_PENDING",
                            metadata={"initial_stop_loss": 98.0,
                                      "broker": "ibkr"})

    def _client(self, rows=()):
        """EtoroTrader itself, never a subclass: adapter_key reads the class
        NAME, so a subclass answers "" and the guard would refuse to compare
        against a venue it cannot name. A MagicMock fails the same way."""
        return EtoroTrader(rows)

    def test_a_wrong_venue_miss_is_unknown_not_flat(self):
        from bot_program.pending_closes import POS_UNKNOWN, broker_exposure
        state = broker_exposure(self.trade, self._client())
        self.assertEqual(state["state"], POS_UNKNOWN)
        self.assertIn("carried by ibkr", state["why"])

    def test_a_positive_identification_still_counts(self):
        """The guard bites on the ABSENCE only. If the venue answering says it
        holds the symbol, side and size, that is evidence whoever carried the
        row — and suppressing it would block a legitimate close."""
        from bot_program.pending_closes import POS_HELD, broker_exposure
        state = broker_exposure(self.trade, self._client(
            [{"symbol": "AAPL", "qty": 10, "side": "BUY"}]))
        self.assertEqual(state["state"], POS_HELD)
        self.assertEqual(state["qty"], Decimal("10"))

    def test_an_empty_real_account_does_not_book_a_carrier_less_row(self):
        """The case the money lens named: a freshly keyed real account holds
        nothing, so `symbols` is empty AND `unnamed` is 0 — both valves read
        0, which is the strongest possible false "the broker is flat"."""
        from bot_program.pending_closes import POS_UNKNOWN, broker_exposure
        bare = _trade(self.cfg, status="CLOSE_PENDING", symbol="MSFT",
                      metadata={"initial_stop_loss": 98.0})
        state = broker_exposure(bare, self._client([]))
        self.assertEqual(state["state"], POS_UNKNOWN)
        self.assertIn("no carrier", state["why"])
