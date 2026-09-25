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


ROUTER = "bot_program.engine.broker_router.client_for_symbol"
PROVEN = "bot_program.asset_engine.base.ETORO_PROVEN"


def _etoro_like(**answers):
    """A client whose CLASS is NAMED EtoroTrader, carrying the three
    eligibility tiers (money_floor, order_caps, leverage_values) and the
    fractional tier with the answers a test states. capabilities.
    adapter_key reads the class NAME and has_capability reads the CLASS's
    callables, so a bare MagicMock (which declares nothing) never meets
    either; a MagicMock base keeps every other attribute mocked, as
    _Venue does. The WIRE's own three states are pinned on the real
    adapter in tests/test_etoro_client.py; here the ENGINE's reading of
    them is. An answer that is an exception is raised, as the real
    adapter raises on an unknown spelling. eligibility_state defaults to
    "read"; a cap left unstated answers None (unmeasured passes)."""
    answers.setdefault("eligibility_state", "read")

    def _answer(key):
        def method(self, symbol, *a, **kw):
            v = answers.get(key)
            if isinstance(v, BaseException):
                raise v
            return v
        return method

    ns = {name: _answer(name) for name in (
        "min_notional", "max_units_per_order", "allow_open_position",
        "eligibility_state", "leverage_values", "max_stop_loss_pct",
        "settlement_for", "takes_fractional_units")}
    ns["ticker"] = lambda self, symbol: {
        "lastPrice": str(answers.get("price", "100"))}
    client = type("EtoroTrader", (mock.MagicMock,), ns)()
    client.get_positions = mock.MagicMock(return_value=[])
    return client


class TheMeasuredMoneyFloorTests(TestCase):
    """E1.3 (2026-09-25): eToro's minPositionExposure — a MONEY floor the
    VENUE states (MEASURED 2026-09-23: 10 USD on stocks, ETFs and crypto;
    1,000 USD on forex, indices and commodities) — read through the
    `money_floor` tier FIRST, turned into units with the entry price and
    value_per_unit, with an EMPTY note so the refusal reads as any
    measured floor. None (no row today) falls to the operator's declared
    floor, then unmeasured, carrying the row's own reason."""

    def setUp(self):
        from tests.test_execution_trust import _user
        self.user = _user("mfloor_u")
        self.cfg = _live_cfg(self.user, name="MFLOOR")
        self.inst = _instrument()
        _signal(self.inst)

    def _ask(self, client, symbol="AAPL", **kw):
        from bot_program.asset_engine.base import AssetBot
        return AssetBot._venue_size_floor(client, symbol, **kw)

    def test_a_measured_money_floor_is_units_at_the_price_with_an_empty_note(self):
        floor, why = self._ask(_etoro_like(min_notional=1000), "EURUSD",
                               price=1.08)
        self.assertAlmostEqual(floor, 925.9259, places=3)
        self.assertEqual(why, "")

    def test_value_per_unit_turns_a_usd_floor_into_quote_units(self):
        """USDJPY at 150: one unit moves 1/150 USD per point, so a 1,000
        USD floor is 1,000 units — not 6.7. Without value_per_unit the
        floor typed in USD is 150x wrong."""
        floor, why = self._ask(_etoro_like(min_notional=1000), "USDJPY",
                               price=150.0, value_per_unit=1 / 150)
        self.assertAlmostEqual(floor, 1000.0, places=6)
        self.assertEqual(why, "")
        floor, _ = self._ask(_etoro_like(min_notional=1000), "USDJPY",
                             price=150.0)
        self.assertAlmostEqual(floor, 1000.0 / 150.0, places=6)

    def test_a_measured_floor_and_no_price_is_unmeasured_and_says_so(self):
        floor, why = self._ask(_etoro_like(min_notional=1000), "EURUSD")
        self.assertIsNone(floor)
        self.assertIn("no price", why)
        self.assertIn("1000", why)

    def test_no_row_falls_to_the_declared_floor_then_unmeasured(self):
        floor, why = self._ask(_etoro_like(min_notional=None), "AAPL",
                               price=200.0, min_notional=10.0)
        self.assertAlmostEqual(floor, 0.05)
        self.assertIn("operator-declared", why)
        floor, why = self._ask(_etoro_like(min_notional=None), "AAPL",
                               price=200.0)
        self.assertIsNone(floor)
        self.assertIn("no eligibility row", why)
        floor, why = self._ask(_etoro_like(min_notional=LookupError(
            "eToro knows no instrument spelled 'NOPE'")), "NOPE", price=1.0)
        self.assertIsNone(floor)
        self.assertIn("LookupError", why)

    def test_the_measured_floor_is_asked_before_the_declared_one(self):
        floor, why = self._ask(_etoro_like(min_notional=1000), "EURUSD",
                               price=1.08, min_notional=5.0)
        self.assertAlmostEqual(floor, 925.9259, places=3)
        self.assertEqual(why, "")

    def test_a_zero_floor_is_not_a_measurement(self):
        floor, why = self._ask(_etoro_like(min_notional=0), "AAPL",
                               price=100.0)
        self.assertIsNone(floor)
        self.assertIn("not a measurement", why)

    def test_a_non_numeric_floor_is_named_for_what_it_answered(self):
        """Only a fake reaches this (the real client answers float | None):
        the reason names the answer itself, never "answered 0"."""
        floor, why = self._ask(_etoro_like(min_notional="ten"), "AAPL",
                               price=100.0)
        self.assertIsNone(floor)
        self.assertIn("'ten'", why)
        self.assertIn("not a number", why)
        self.assertNotIn("answered 0", why)

    def test_the_declared_floor_reads_value_per_unit_too(self):
        from bot_program.asset_engine.base import AssetBot
        units, why = AssetBot._declared_money_floor(object(), "USDJPY",
                                                    150.0, 1000.0, 1 / 150)
        self.assertAlmostEqual(units, 1000.0, places=6)
        self.assertIn("operator-declared", why)
        units, _ = AssetBot._declared_money_floor(object(), "USDJPY",
                                                  150.0, 1000.0)
        self.assertAlmostEqual(units, 1000.0 / 150.0, places=6)

    def test_saxo_alone_still_declares_size_floor(self):
        from bot_program.engine.capabilities import (ADAPTER_CAPABILITIES,
                                                     CAPABILITIES)
        self.assertEqual(CAPABILITIES["money_floor"], ("min_notional",))
        self.assertEqual({k for k, v in ADAPTER_CAPABILITIES.items()
                          if "money_floor" in v}, {"etoro"})
        self.assertEqual({k for k, v in ADAPTER_CAPABILITIES.items()
                          if "size_floor" in v}, {"saxo"})

    def test_the_entry_refuses_under_a_measured_floor_with_the_venue_wording(self):
        """Through the stock lane: the class states a 1,000,000 USD floor
        on AAPL at 100 (10,000 units) against a size well under it. The
        skip is VENUE_MIN_SIZE with the MEASURED wording — no
        operator-declared label — the alert fires, nothing is sent."""
        from alerts.models import Notification
        from bot_program.asset_engine import skips
        from bot_program.asset_engine.stock_bot import StockBot
        from bot_program.models import AssetBotTrade
        client = _etoro_like(min_notional=1_000_000, allow_open_position=True)
        with mock.patch(PROVEN, frozenset({"stock"})), \
                mock.patch(ROUTER, return_value=client):
            StockBot(self.cfg).scan_symbol("AAPL")
        client.market_order.assert_not_called()
        self.assertFalse(AssetBotTrade.objects.filter(config=self.cfg)
                         .exists())
        self.cfg.refresh_from_db()
        note = self.cfg.extras["skips"]["AAPL"]
        self.assertEqual(note["code"], skips.VENUE_MIN_SIZE)
        self.assertNotIn("operator-declared", note["detail"])
        self.assertIn("this venue's minimum is 10000", note["detail"])
        self.assertTrue(Notification.objects.filter(
            user=self.user, title__contains="AAPL").exists())


class TheEligibilityGateTests(TestCase):
    """Step 2 of AssetBot._etoro_entry_refusal (E1.4, 2026-09-25) on the
    `order_caps` tier: the read's own THREE-STATE first — "absent" (the
    venue holds no row: refused), "error" (could not ask: refused for a
    levered hint or a 1,000-USD-floor class, a 1x stock/etf/crypto
    proceeds for a hold under 24 h with the log line), "read" (then
    allowOpenPosition and maxUnitsPerOrder). Nothing is clamped."""

    def _gate(self, client, symbol="AAPL", icls="stock", qty=1.0,
              hint=None, side="BUY"):
        from bot_program.asset_engine.base import AssetBot
        with mock.patch(PROVEN, frozenset({"stock", "etf", "crypto", "forex",
                                           "index", "commodity", "short"})):
            return AssetBot._etoro_entry_refusal(
                client, symbol, side, qty, 100.0, icls, leverage_hint=hint)

    def test_allow_open_position_false_is_refused(self):
        from bot_program.asset_engine import skips
        code, why = self._gate(_etoro_like(allow_open_position=False,
                                           max_units_per_order=6151))
        self.assertEqual(code, skips.ELIGIBILITY_REFUSED)
        self.assertIn("allowOpenPosition false", why)
        self.assertIn("AAPL", why)

    def test_a_size_past_max_units_per_order_is_refused_naming_both(self):
        from bot_program.asset_engine import skips
        client = _etoro_like(allow_open_position=True, max_units_per_order=41)
        code, why = self._gate(client, symbol="BTCUSD", icls="crypto",
                               qty=42)
        self.assertEqual(code, skips.ELIGIBILITY_REFUSED)
        self.assertIn("42", why)
        self.assertIn("41", why)
        self.assertIn("not clamped", why)
        self.assertEqual(self._gate(client, symbol="BTCUSD", icls="crypto",
                                    qty=41), ("", ""))
        self.assertEqual(self._gate(client, symbol="BTCUSD", icls="crypto",
                                    qty=0.0004), ("", ""))

    def test_an_absent_row_is_refused(self):
        from bot_program.asset_engine import skips
        code, why = self._gate(_etoro_like(eligibility_state="absent"))
        self.assertEqual(code, skips.ELIGIBILITY_REFUSED)
        self.assertIn("no eligibility row", why)
        self.assertIn("AAPL", why)

    def test_an_unread_row_refuses_the_thousand_floor_classes_at_1x(self):
        from bot_program.asset_engine import skips
        for icls, sym in (("forex", "EURUSD"), ("index", "SPX500"),
                          ("commodity", "WHEAT")):
            with self.subTest(icls=icls):
                code, why = self._gate(_etoro_like(eligibility_state="error"),
                                       symbol=sym, icls=icls)
                self.assertEqual(code, skips.ELIGIBILITY_REFUSED)
                self.assertIn("1,000 USD floor", why)
                self.assertIn("unread", why)
                self.assertIn(sym, why)

    def test_an_unread_row_lets_a_1x_stock_etf_or_crypto_through_with_the_log_line(self):
        with self.assertLogs("bot_program.asset_engine.base",
                             level="INFO") as cm:
            for icls, sym in (("stock", "AAPL"), ("etf", "GLDM"),
                              ("crypto", "BTCUSD")):
                self.assertEqual(
                    self._gate(_etoro_like(eligibility_state="error"),
                               symbol=sym, icls=icls), ("", ""), icls)
        said = [ln for ln in cm.output if "settlement unknown" in ln]
        self.assertEqual(len(said), 3, cm.output)
        self.assertTrue(all("24 h" in ln for ln in said), said)

    def test_an_unread_row_refuses_any_hint_above_one(self):
        from bot_program.asset_engine import skips
        code, why = self._gate(_etoro_like(eligibility_state="error"), hint=5)
        self.assertEqual(code, skips.ELIGIBILITY_REFUSED)
        self.assertIn("5x", why)
        self.assertIn("LIVE leverage list", why)
        code, why = self._gate(_etoro_like(eligibility_state="error"),
                               symbol="BTCUSD", icls="crypto", hint=2)
        self.assertEqual(code, skips.ELIGIBILITY_REFUSED)
        self.assertIn("2x", why)
        code, why = self._gate(_etoro_like(eligibility_state="error"),
                               symbol="EURUSD", icls="forex", hint=10)
        self.assertEqual(code, skips.ELIGIBILITY_REFUSED)
        self.assertIn("10x", why)
        self.assertIn("1,000 USD floor", why)

    def test_a_raise_from_the_state_reads_as_error(self):
        from bot_program.asset_engine import skips
        client = _etoro_like(eligibility_state=LookupError(
            "eToro knows no instrument spelled 'NOPE'"))
        code, why = self._gate(client, symbol="NOPE", icls="forex")
        self.assertEqual(code, skips.ELIGIBILITY_REFUSED)
        with self.assertLogs("bot_program.asset_engine.base",
                             level="INFO") as cm:
            self.assertEqual(self._gate(client, symbol="NOPE", icls="stock"),
                             ("", ""))
        self.assertTrue(any("eligibility_state raised LookupError" in ln
                            for ln in cm.output), cm.output)

    def test_a_read_row_that_allows_and_fits_passes(self):
        self.assertEqual(self._gate(_etoro_like(
            allow_open_position=True, max_units_per_order=6151,
            min_notional=10)), ("", ""))
        self.assertEqual(self._gate(_etoro_like()), ("", ""),
                         "caps unstated: unmeasured refuses nothing here")

    def test_a_raise_from_the_caps_reads_as_unmeasured(self):
        client = _etoro_like(allow_open_position=TimeoutError("gone"))
        with self.assertLogs("bot_program.asset_engine.base",
                             level="INFO") as cm:
            self.assertEqual(self._gate(client), ("", ""))
        self.assertTrue(any("order caps unmeasured" in ln
                            for ln in cm.output), cm.output)

    def test_the_words_fit_the_skip_record_and_start_with_the_verdict(self):
        for client, kw in (
                (_etoro_like(eligibility_state="absent"), {}),
                (_etoro_like(eligibility_state="error"),
                 dict(symbol="RUSSELL2000", icls="commodity", hint=5)),
                (_etoro_like(allow_open_position=False), {}),
                (_etoro_like(max_units_per_order=41), dict(qty=42))):
            _code, why = self._gate(client, **kw)
            self.assertLessEqual(len(why), 200, why)
            self.assertTrue(why.startswith(("eToro", "sized")), why)

    def test_the_code_and_its_advice(self):
        from bot_program.asset_engine import skips
        from tests.test_execution_trust import _user
        self.assertEqual(skips.ELIGIBILITY_REFUSED, "eligibility_refused")
        self.assertNotIn(skips.ELIGIBILITY_REFUSED,
                         (skips.LEVERAGE_REFUSED, skips.GATE_BLOCKED,
                          skips.VENUE_MIN_SIZE, skips.ORDER_ERROR))
        cfg = _live_cfg(_user("elig_adv"), name="EADV")
        skips.record(cfg, "EURUSD", skips.ELIGIBILITY_REFUSED,
                     "eToro EURUSD (forex, 1x): eligibility row unread")
        cfg.refresh_from_db()
        advice = skips.diagnose(cfg)
        self.assertIn("eligibility row", advice, advice)
        self.assertIn("nothing was clamped", advice, advice)
        self.assertIn("1,000 USD", advice, advice)


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
