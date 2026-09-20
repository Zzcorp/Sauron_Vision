"""THE VENUE'S OWN FLOOR, AND THE FOLLOW LEAK.

TWO REFUSALS, neither of which can raise a number.

ONE. `_round_qty` knows the ASSET CLASS and nothing about the venue —
forex_bot.py:27 says out loud that its 100-unit boundary is for "tidier paper
trades". Saxo publishes LotSize/LotSizeType and MinimumTradeSize, and
`SaxoTrader._amount` already refuses a size below the minimum rather than
raising it (upsizing would silently override the operator's risk). But it
refuses inside `market_order`, recorded as ORDER_ERROR, whose standing advice
is "check the gateway" — so a pool sizing 400 units against a 1,000 minimum
produced a line that read as a broken connection, on every tick, for ever.

Asked before the order now, in three states, and a floor of 0 would be a
fourth this must never give. An UNMEASURED floor refuses nothing: the adapter
stays the enforcer, so a failed reference read cannot stop a venue trading.
And nothing is resized in either direction — both numbers and the multiple go
to the operator, under a skip code of its own.

TWO. `manual_trade.py:2051` refuses to arm a following pool whose orders
route somewhere other than the book. The `/asset-bots/` Follow button, where
the operator actually ticks it, had no venue test at all: it wrote
cfg.capital from the book's reading and the sync then refused to retune that
row for ever. And the sync's own test read `symbols[0]` while routing is per
symbol, so a pool spanning two venues was refused or retuned according to
which symbol the operator typed FIRST.

THE ADVICE USED TO POINT THE WRONG WAY, and it is pinned here. Units = risk
budget / stop distance, so a WIDER stop buys FEWER units. The first draft of
both operator-facing strings said "widen the stop" — which drives the size
further below the floor it is meant to clear.
"""
from decimal import Decimal
from unittest import mock

from django.test import TestCase
from django.urls import reverse

from tests.test_execution_trust import _cfg as _live_cfg
from tests.test_execution_trust import _instrument, _signal
from tests.test_saxo_wiring import _instrument as _inst_of
from tests.test_saxo_wiring import etoro, saxo


def _floor(details):
    from bot_program.engine.saxo_client import SaxoTrader
    return SaxoTrader._size_floor(details)


def _amount(details, qty):
    from bot_program.engine.saxo_client import SaxoTrader
    return SaxoTrader._amount(details, qty)


class _Venue(mock.MagicMock):
    """A client whose CLASS defines `min_tradable`.

    `capabilities.missing_methods` resolves `type(instance)` and asks the
    CLASS for the method, so a bare MagicMock declares NO capability at all —
    which is why the gate reads unmeasured in every pre-existing test and why
    none of them changed behaviour. A subclass is the only way to hand the
    engine a client that can really be asked.
    """

    def min_tradable(self, symbol):
        return self.floor_value


def _venue(floor, *, price="100"):
    c = _Venue()
    c.floor_value = floor
    c.ticker = mock.MagicMock(return_value={"lastPrice": price})
    c.market_order = mock.MagicMock(return_value={
        "orderId": "o1", "status": "FILLED",
        "avgPrice": price, "executedQty": "10"})
    c.get_positions = mock.MagicMock(return_value=[])
    return c


class TheFloorComesOffThePayload(TestCase):
    """No Saxo number is written anywhere — every floor is read at runtime."""

    def test_the_minimum_alone_is_the_floor(self):
        self.assertEqual(_floor({"MinimumTradeSize": 1000}), 1000.0)

    def test_a_lot_grid_floors_to_the_first_lot_at_or_above_the_minimum(self):
        """_amount floors to the grid BEFORE checking the minimum, so on a
        400 grid with a 1,000 minimum the smallest ACCEPTABLE size is 1,200.
        Reporting 1,000 would report a size Saxo refuses."""
        self.assertEqual(
            _floor({"LotSize": 400, "LotSizeType": "OddLotAllowed",
                    "MinimumTradeSize": 1000}), 1200.0)

    def test_an_enforced_lot_is_a_floor_on_its_own(self):
        self.assertEqual(
            _floor({"LotSize": 500, "LotSizeType": "OddLotAllowed"}), 500.0)

    def test_neither_field_is_unmeasured_not_zero(self):
        """`_details` returns {} when the reference read failed. A caller
        reading 0 would announce that a one-unit order is safe here."""
        self.assertIsNone(_floor({}))

    def test_a_lot_size_that_is_not_used_is_unmeasured(self):
        self.assertIsNone(_floor({"LotSize": 400, "LotSizeType": "NotUsed"}))

    def test_an_unparseable_field_is_unmeasured(self):
        self.assertIsNone(_floor({"MinimumTradeSize": "bad"}))

    def test_the_floor_is_exactly_the_smallest_size_amount_accepts(self):
        """The anti-drift guard. Two readers of LotSize/MinimumTradeSize
        cannot diverge without this going red."""
        for details in ({"MinimumTradeSize": 1000},
                        {"LotSize": 400, "LotSizeType": "OddLotAllowed",
                         "MinimumTradeSize": 1000},
                        {"LotSize": 500, "LotSizeType": "OddLotAllowed"}):
            f = _floor(details)
            self.assertIsNotNone(f, details)
            self.assertEqual(_amount(details, f), f, details)
            with self.assertRaises(ValueError, msg=str(details)):
                _amount(details, f * 0.99)

    def test_min_tradable_is_unmeasured_when_saxo_cannot_be_asked(self):
        from bot_program.engine.saxo_client import SaxoTrader
        t = SaxoTrader.__new__(SaxoTrader)
        with mock.patch.object(SaxoTrader, "resolve",
                               side_effect=LookupError("no such spelling")):
            self.assertIsNone(t.min_tradable("NOPE"))


class TheEngineReadsThreeStates(TestCase):

    def _ask(self, client, symbol="AAPL"):
        from bot_program.asset_engine.base import AssetBot
        return AssetBot._venue_size_floor(client, symbol)

    def test_an_adapter_that_cannot_be_asked_reads_unmeasured(self):
        class _NoFloor:
            pass
        floor, why = self._ask(_NoFloor())
        self.assertIsNone(floor)
        self.assertIn("size_floor", why)

    def test_a_bare_mock_client_declares_nothing(self):
        """The property that kept every existing test green: capabilities are
        read off the CLASS, and MagicMock the class has no min_tradable."""
        floor, why = self._ask(mock.MagicMock())
        self.assertIsNone(floor)
        self.assertIn("declares no size_floor", why)

    def test_a_measured_floor_comes_back_as_a_number(self):
        self.assertEqual(self._ask(_venue(1000)), (1000.0, ""))

    def test_a_floor_of_zero_is_not_a_measurement(self):
        """A vacuous gate that looks measured is worse than no gate."""
        floor, why = self._ask(_venue(0))
        self.assertIsNone(floor)
        self.assertIn("not a measurement", why)

    def test_a_none_answer_is_unmeasured(self):
        floor, why = self._ask(_venue(None))
        self.assertIsNone(floor)
        self.assertIn("could not state", why)

    def test_a_raise_is_unmeasured_and_names_the_raise(self):
        class _Angry(_Venue):
            def min_tradable(self, symbol):
                raise TimeoutError("gone")
        floor, why = self._ask(_Angry())
        self.assertIsNone(floor)
        self.assertIn("TimeoutError", why)

    def test_a_non_number_is_unmeasured(self):
        class _Words(_Venue):
            def min_tradable(self, symbol):
                return "one thousand"
        floor, why = self._ask(_Words())
        self.assertIsNone(floor)
        self.assertIn("not a number", why)

    def test_a_mock_answer_measures_one_and_therefore_refuses_nothing(self):
        """Pinned because it surprised the author: float(MagicMock()) is 1.0,
        not a TypeError. So a test client that never set a floor reads a
        MEASURED floor of 1.0 — below every real size, so it refuses nothing
        and no existing test changes. It is not the unmeasured branch."""
        self.assertEqual(self._ask(_Venue()), (1.0, ""))


class TheVocabularyAndTheTable(TestCase):

    def test_only_saxo_can_be_asked_its_minimum(self):
        from bot_program.engine.capabilities import (ADAPTER_CAPABILITIES,
                                                     CAPABILITIES)
        self.assertEqual(CAPABILITIES["size_floor"], ("min_tradable",))
        can = {k for k, v in ADAPTER_CAPABILITIES.items()
               if "size_floor" in v}
        self.assertEqual(can, {"saxo"},
                         "no eToro or IBKR minimum may be invented")

    def test_the_declared_table_matches_the_class(self):
        from bot_program.engine.capabilities import (capabilities_of,
                                                     declared)
        from bot_program.engine.saxo_client import SaxoTrader
        self.assertEqual(set(capabilities_of(SaxoTrader)),
                         set(declared("saxo")))

    def _advice(self):
        """diagnose() reads a CONFIG and reports its top code, so the advice
        is reached the way the operator reaches it: through a recorded skip."""
        from bot_program.asset_engine import skips
        from tests.test_execution_trust import _user
        cfg = _live_cfg(_user("advice_u"), name="ADV")
        skips.record(cfg, "AAPL", skips.VENUE_MIN_SIZE, "sized 400, min 1000")
        cfg.refresh_from_db()
        return skips.diagnose(cfg)

    def test_the_refusal_is_its_own_code_with_advice(self):
        from bot_program.asset_engine import skips
        self.assertEqual(skips.VENUE_MIN_SIZE, "venue_min_size")
        self.assertNotIn(skips.VENUE_MIN_SIZE,
                         (skips.SIZED_TO_ZERO, skips.ORDER_ERROR))
        advice = self._advice()
        self.assertIn("nothing was resized", advice, advice)

    def test_the_advice_does_not_tell_the_operator_to_widen_the_stop(self):
        """units = risk / stop distance: a wider stop buys FEWER units and
        makes this worse. The first draft said to widen it."""
        advice = self._advice().lower()
        self.assertNotIn("widen the stop", advice)
        self.assertIn("tighten the stop", advice, advice)


class TheEntryRefusesAndNeverResizes(TestCase):

    def setUp(self):
        from tests.test_execution_trust import _user
        self.user = _user("floor_u")
        self.cfg = _live_cfg(self.user, name="FLOOR")
        self.inst = _instrument()
        _signal(self.inst)

    def _scan(self, floor):
        from bot_program.asset_engine.stock_bot import StockBot
        client = _venue(floor)
        with mock.patch("bot_program.engine.broker_router.client_for_symbol",
                        return_value=client):
            StockBot(self.cfg).scan_symbol("AAPL")
        self.cfg.refresh_from_db()
        return client

    def test_a_floor_above_the_size_refuses_and_sends_nothing(self):
        from bot_program.asset_engine import skips
        from bot_program.models import AssetBotTrade
        client = self._scan(1_000_000.0)
        client.market_order.assert_not_called()
        self.assertFalse(AssetBotTrade.objects.filter(config=self.cfg)
                         .exists())
        self.assertEqual(
            (self.cfg.extras.get("skips") or {}).get("AAPL", {}).get("code"),
            skips.VENUE_MIN_SIZE)
        self.assertEqual(
            (self.cfg.extras.get("skip_counts") or {})
            .get(skips.VENUE_MIN_SIZE), 1)

    def test_the_refusal_names_both_numbers(self):
        self._scan(1_000_000.0)
        detail = self.cfg.extras["skips"]["AAPL"]["detail"]
        self.assertIn("1e+06", detail, detail)
        self.assertIn("minimum", detail, detail)
        self.assertIn("units from the stop distance", detail, detail)

    def test_nothing_is_resized_to_the_floor(self):
        """House rule 3, read out of the order the adapter was asked for."""
        client = self._scan(1_000_000.0)
        client.market_order.assert_not_called()

    def test_an_unmeasured_floor_refuses_nothing(self):
        from bot_program.models import AssetBotTrade
        client = self._scan(None)
        client.market_order.assert_called_once()
        self.assertTrue(AssetBotTrade.objects.filter(config=self.cfg)
                        .exists())

    def test_a_floor_below_the_size_refuses_nothing(self):
        client = self._scan(1.0)
        client.market_order.assert_called_once()

    def test_the_alert_names_the_pool_not_only_the_symbol(self):
        """Deduped per CONFIG per symbol: a title carrying only the symbol
        would silence a second pool for a day and the operator would fund
        the wrong one."""
        from alerts.models import Notification
        self._scan(1_000_000.0)
        titles = list(Notification.objects.filter(user=self.user)
                      .values_list("title", flat=True))
        self.assertTrue(any("FLOOR" in t and "AAPL" in t for t in titles),
                        titles)

    def test_the_alert_body_does_not_say_to_widen_the_stop(self):
        from alerts.models import Notification
        self._scan(1_000_000.0)
        body = " ".join(Notification.objects.filter(user=self.user)
                        .values_list("body", flat=True)).lower()
        self.assertNotIn("widen the stop", body)
        self.assertIn("tighter stop", body)


class TheFollowButtonRefusesAnOffBookPool(TestCase):

    def setUp(self):
        from django.contrib.auth.hashers import make_password
        from django.contrib.auth.models import User
        from portfolio.trader_profile import TraderProfile
        self.user = User.objects.create_superuser("follow_u", "f@x", "x")
        prof, _ = TraderProfile.objects.get_or_create(user=self.user)
        prof.access_pin_hash = make_password("1234")
        prof.save()
        self.client.force_login(self.user)
        # Saxo carries stocks and is the book; eToro carries forex.
        acct = saxo(self.user, flags=("stock",), sim=True)
        acct.last_equity = Decimal("100000")
        acct.last_equity_currency = "EUR"
        from django.utils import timezone
        acct.last_equity_at = timezone.now()
        acct.save()
        etoro(self.user, flags=("forex",))
        _inst_of("AAPL", "stock")
        _inst_of("EURUSD", "forex")

    def _post(self, cfg):
        return self.client.post(reverse("hq_follow_asset_bot"),
                                {"config_id": cfg.id, "follow": "1",
                                 "pin": "1234"})

    def test_a_pool_that_trades_elsewhere_cannot_follow(self):
        from bot_program.models import AssetBotConfig
        cfg = AssetBotConfig.objects.create(
            user=self.user, name="FX", asset_class="forex", mode="live",
            enabled=True, symbols=["EURUSD"], capital=Decimal("500"))
        self._post(cfg)
        cfg.refresh_from_db()
        self.assertEqual(cfg.capital, Decimal("500"),
                         "the button must not size it from another account")
        self.assertFalse((cfg.extras or {}).get("capital_tracks_broker"))

    def test_a_pool_on_the_book_still_follows(self):
        from bot_program.models import AssetBotConfig
        cfg = AssetBotConfig.objects.create(
            user=self.user, name="EQ", asset_class="stock", mode="live",
            enabled=True, symbols=["AAPL"], capital=Decimal("500"))
        self._post(cfg)
        cfg.refresh_from_db()
        self.assertTrue((cfg.extras or {}).get("capital_tracks_broker"))
        self.assertEqual(cfg.capital, Decimal("100000.00"))


class TheSyncAsksEverySymbol(TestCase):

    def setUp(self):
        from django.contrib.auth.models import User
        self.user = User.objects.create_user("sync_sym_u", password="x")
        acct = saxo(self.user, flags=("stock",), sim=True)
        acct.save()
        etoro(self.user, flags=("forex",))
        _inst_of("AAPL", "stock")
        _inst_of("EURUSD", "forex")

    def _pool(self, symbols):
        from bot_program.models import AssetBotConfig
        return AssetBotConfig.objects.create(
            user=self.user, name="P" + symbols[0], asset_class="stock",
            mode="live", enabled=True, symbols=list(symbols),
            capital=Decimal("500"),
            extras={"capital_tracks_broker": True})

    def _run(self):
        from bot_program.tasks import _follow_the_account
        from tests.test_saxo_wiring import _fresh
        _follow_the_account(_fresh(self.user), 100000.0, "EUR")

    def test_a_foreign_second_symbol_refuses_the_retune(self):
        """The order-dependence. symbols[0] routed to the book, so the old
        test retuned this pool off an account its other symbol does not
        trade — and flipping the two strings flipped the decision."""
        pool = self._pool(["AAPL", "EURUSD"])
        self._run()
        pool.refresh_from_db()
        self.assertEqual(pool.capital, Decimal("500"))

    def test_a_foreign_first_symbol_still_refuses(self):
        pool = self._pool(["EURUSD", "AAPL"])
        self._run()
        pool.refresh_from_db()
        self.assertEqual(pool.capital, Decimal("500"))

    def test_a_pool_wholly_on_the_book_is_still_retuned(self):
        """The regression guard: following must not go inert."""
        pool = self._pool(["AAPL"])
        self._run()
        pool.refresh_from_db()
        self.assertEqual(pool.capital, Decimal("100000.00"))
