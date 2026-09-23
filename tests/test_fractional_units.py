"""Fractional units on a venue that takes them (2026-09-23).

The stock bot floors every live size to WHOLE shares by its own rule. eToro
takes float units — a BELIEF from the public reference, unmeasured — declared
as a `fractional_units` capability tier on EtoroTrader alone, read off the
CLIENT the router hands the entry, and honoured only while the
`fractional_units_live` component is ON (it arrives OFF; the demo proof
D2c flips it). Units still come from risk_per_trade_pct and the stop; the
rounding brings the sent size closer to that number and never above it.

Three states everywhere: True fractions, False whole, None unmeasured —
which is whole shares, as before. A venue's refusal of a fraction carries
its own words, is remembered per symbol for 24 h, and is alerted once; an
over-fill is stamped and alerted; the money floor is the OPERATOR's explicit
extras['venue_min_notional'], never an adapter's belief.

The eToro client is the REAL class with its transport replaced — never a
subclass, because capabilities.adapter_key reads the class name; the
whole-share venue is tests.test_venue_min_size's stub.
"""
from decimal import Decimal
from unittest import mock

from django.test import SimpleTestCase, TestCase

from tests.test_etoro_client import SEARCH_AAPL, _client
from tests.test_execution_trust import _cfg as _live_cfg
from tests.test_execution_trust import _instrument, _signal, _user
from tests.test_venue_min_size import _venue

ROUTER = "bot_program.engine.broker_router.client_for_symbol"
SWITCH = "fractional_units_live"


class _NoTier:
    """A client class with no capability method at all."""


class _Fractional(mock.MagicMock):
    """A client whose CLASS defines `takes_fractional_units` — the only
    way to hand the engine a client the tier can be read from (a bare
    MagicMock declares nothing)."""
    answer = True

    def takes_fractional_units(self, symbol):
        if isinstance(self.answer, BaseException):
            raise self.answer
        return self.answer


class _Both(mock.MagicMock):
    """Declares both a measured size floor and the fractional tier."""
    answer = True

    def min_tradable(self, symbol):
        return 1000

    def takes_fractional_units(self, symbol):
        return self.answer


def _fractional(answer=True, *, price="100", fill=None):
    """A fractional venue that FILLS what it is asked (executedQty echoes the
    request) unless `fill` says otherwise."""
    c = _Fractional()
    c.answer = answer
    c.ticker = mock.MagicMock(return_value={"lastPrice": price})

    def _order(symbol, side, qty, **kw):
        if fill is not None:
            return dict(fill)
        return {"orderId": "o1", "status": "FILLED", "avgPrice": price,
                "executedQty": str(qty)}
    c.market_order = mock.MagicMock(side_effect=_order)
    c.get_positions = mock.MagicMock(return_value=[])
    return c


def _switch(on):
    from core.platform_control import PlatformComponent
    PlatformComponent.objects.update_or_create(
        key=SWITCH, defaults={"name": "t", "category": "system",
                              "is_enabled": on})


class TheTierIsDeclaredAndDerived(SimpleTestCase):

    def test_the_tier_is_one_method_and_etoro_alone_declares_it(self):
        from bot_program.engine import capabilities as cap
        from bot_program.engine.alpaca_client import AlpacaTrader
        from bot_program.engine.etoro_client import EtoroTrader
        from bot_program.engine.ibkr_client import IBKRTrader
        from bot_program.engine.paper_trader import PaperTrader
        from bot_program.engine.saxo_client import SaxoTrader
        self.assertEqual(cap.CAPABILITIES["fractional_units"],
                         ("takes_fractional_units",))
        self.assertEqual({k for k, v in cap.ADAPTER_CAPABILITIES.items()
                          if "fractional_units" in v}, {"etoro"})
        self.assertIn("fractional_units", cap.capabilities_of(EtoroTrader))
        for cls in (IBKRTrader, AlpacaTrader, SaxoTrader, PaperTrader):
            self.assertNotIn("fractional_units", cap.capabilities_of(cls),
                             cls.__name__)
        self.assertEqual(cap.CAPABILITIES["size_floor"], ("min_tradable",))
        self.assertEqual({k for k, v in cap.ADAPTER_CAPABILITIES.items()
                          if "size_floor" in v}, {"saxo"})


class TheAdapterAnswersABelief(SimpleTestCase):

    def test_the_answer_is_a_belief_and_costs_no_call(self):
        from bot_program.engine import capabilities as cap
        from bot_program.engine.etoro_client import EtoroTrader
        t, fake = _client([SEARCH_AAPL])
        self.assertIs(t.takes_fractional_units("AAPL"), True)
        self.assertEqual(fake.calls, [])
        self.assertEqual(cap.adapter_key(t), "etoro")
        self.assertIn("belie",
                      EtoroTrader.takes_fractional_units.__doc__.lower())
        self.assertFalse(hasattr(EtoroTrader, "min_position_notional"))


class TheStatusParserNeverRaises(SimpleTestCase):

    def test_int_object_and_garbage(self):
        from bot_program.engine.etoro_client import _status_of
        self.assertEqual(_status_of({"status": 3}), (3, ""))
        self.assertEqual(_status_of({"statusId": 4}), (4, ""))
        self.assertEqual(
            _status_of({"status": {"id": 4, "errorCode": 123,
                                   "errorMessage": "too small"}}),
            (4, "errorCode 123: too small"))
        self.assertEqual(_status_of({"status": {"id": "x"}}), (0, ""))
        self.assertEqual(_status_of({}), (0, ""))
        self.assertEqual(_status_of(None), (0, ""))

    def _order(self, lookup):
        t, _ = _client([SEARCH_AAPL,
                        ("POST", "/execution/demo/orders", 200,
                         {"orderId": 777, "referenceId": "ref-1"}),
                        ("GET", "orders:lookup", 200, lookup)])
        with mock.patch("time.sleep"):
            return t.market_order("AAPL", "BUY", 0.1234, stop_loss=180,
                                  take_profit=210)

    def test_an_object_status_reads_through_the_order(self):
        out = self._order({"status": {"id": 4, "errorCode": 123,
                                      "errorMessage": "too small"},
                           "positionExecutions": []})
        self.assertEqual(out["status"], "REJECTED")
        self.assertEqual(out["refusal"], "errorCode 123: too small")
        out = self._order({"status": {"id": 3}, "positionExecutions": [
            {"positionId": 9, "openingData": {"units": 0.1234,
                                              "avgPrice": 100.0}}]})
        self.assertEqual(out["status"], "FILLED")
        self.assertEqual(out["executedQty"], "0.1234")
        out = self._order({"status": {"id": "x"}})
        self.assertEqual(out["status"], "PENDING")
        self.assertTrue(out["working"])


class ThePostRefusalCarriesTheWords(SimpleTestCase):

    def test_a_4xx_at_the_post_says_the_venues_words_first(self):
        t, fake = _client([SEARCH_AAPL,
                           ("POST", "/execution/demo/orders", 400,
                            {"message": "units below minimum"})])
        with self.assertRaises(RuntimeError) as caught:
            with mock.patch("time.sleep"):
                t.market_order("AAPL", "BUY", 0.1234, stop_loss=180,
                               take_profit=210)
        msg = str(caught.exception)
        self.assertTrue(msg.startswith("eToro refused (400):"), msg)
        self.assertIn("units below minimum", msg[:88])
        self.assertEqual([c for c in fake.calls if "orders:lookup" in c[1]],
                         [])


class TheEngineReadsThreeStates(TestCase):

    def test_true_false_none_off_the_client_and_the_switch(self):
        from bot_program.asset_engine.base import AssetBot
        from bot_program.engine.etoro_client import EtoroTrader
        f = AssetBot._venue_fractional_units
        self.assertIsNone(f(_NoTier(), "AAPL"))
        self.assertIsNone(f(mock.MagicMock(), "AAPL"))
        self.assertIsNone(f(_fractional(), "AAPL"), "no switch row = OFF")
        _switch(False)
        self.assertIsNone(f(_fractional(), "AAPL"))
        _switch(True)
        self.assertIs(f(_fractional(), "AAPL"), True)
        self.assertIs(f(_fractional(answer=False), "AAPL"), False)
        self.assertIsNone(f(_fractional(answer="yes"), "AAPL"))
        self.assertIsNone(f(_fractional(answer=TimeoutError("x")), "AAPL"))
        real, _ = _client([])
        self.assertIs(f(real, "AAPL"), True)
        self.assertIsInstance(real, EtoroTrader)
        _switch(False)
        self.assertIsNone(f(real, "AAPL"))

    def test_the_second_read_is_silent(self):
        from bot_program.asset_engine.base import AssetBot
        _switch(True)
        with self.assertLogs("bot_program.asset_engine.base",
                             level="INFO") as said:
            self.assertIs(AssetBot._venue_fractional_units(
                _fractional(), "AAPL"), True)
        self.assertTrue(any("takes fractional units" in ln
                            for ln in said.output))
        with self.assertNoLogs("bot_program.asset_engine.base",
                               level="INFO"):
            AssetBot._venue_fractional_units(_fractional(), "AAPL",
                                             say=False)


class TheDeclaredMoneyFloorInUnits(TestCase):

    def test_operator_declared_and_measured_wins(self):
        from bot_program.asset_engine.base import AssetBot
        floor = AssetBot._venue_size_floor
        units, why = floor(_fractional(), "AAPL", price=200.0,
                           min_notional=10.0)
        self.assertAlmostEqual(units, 0.05)
        self.assertIn("operator-declared", why)
        self.assertIn("10", why)
        for bad in (0, None, "ten"):
            with self.subTest(bad=bad):
                units, why = floor(_fractional(), "AAPL", price=200.0,
                                   min_notional=bad)
                self.assertIsNone(units)
                self.assertIn("declares no size_floor", why)
        units, why = floor(_fractional(), "AAPL", min_notional=10.0)
        self.assertIsNone(units)
        self.assertIn("no price", why)
        self.assertEqual(floor(_Both(), "AAPL", price=100.0, min_notional=10.0),
                         (1000.0, ""))
        self.assertEqual(floor(_venue(1000), "AAPL"), (1000.0, ""))
        units, why = floor(_venue(None), "AAPL")
        self.assertIsNone(units)
        self.assertIn("could not state", why)


class TheStockBotRoundsByTheAnswer(TestCase):

    def test_only_true_in_live_changes_the_arithmetic(self):
        from bot_program.asset_engine.base import make_bot
        from bot_program.asset_engine.stock_bot import StockBot
        from tests.test_hardening import _forex_bot
        user = _user("frac_round")
        live = StockBot(_live_cfg(user, name="FR"))
        self.assertEqual(live._round_qty(0.37, 200.0), 0.0)
        self.assertEqual(live._round_qty(0.37, 200.0, fractional=None), 0.0)
        self.assertEqual(live._round_qty(0.37, 200.0, fractional=False), 0.0)
        self.assertEqual(live._round_qty(0.37, 200.0, fractional=True), 0.37)
        self.assertEqual(live._round_qty(1.23456, 200.0, fractional=True),
                         1.2346)
        self.assertEqual(live._round_qty(3.7, 200.0, fractional=True), 3.7)
        self.assertEqual(live._round_qty(3.7, 200.0, fractional=None), 3.0)
        r = live._round_qty(0.123456, 200.0, fractional=True)
        self.assertEqual(live._round_qty(r, 200.0, fractional=True), r)
        paper = StockBot(_live_cfg(user, mode="paper", name="FRP"))
        for state in (None, True, False):
            self.assertEqual(paper._round_qty(0.37, 200.0, fractional=state),
                             0.37)
        fx = _forex_bot(user)
        self.assertEqual(fx._round_qty(1666.67, 150.0, fractional=True),
                         fx._round_qty(1666.67, 150.0))
        self.assertEqual(fx._round_qty(1666.67, 150.0), 1700.0)
        for cls in ("crypto", "commodity"):
            bot = make_bot(_live_cfg(user, asset_class=cls, mode="paper",
                                     name=f"FR_{cls}"))
            self.assertEqual(bot._round_qty(1.5, 10.0, fractional=True),
                             bot._round_qty(1.5, 10.0))
        self.assertEqual(StockBot.FRACTIONAL_DECIMALS, 4)


class TheEntryPathOnAFractionalVenue(TestCase):
    """The harness of tests/test_venue_min_size.TheEntryRefusesAndNeverResizes,
    with the pool lowered to 300 so a whole-share venue sizes to zero and a
    fractional one to 0.6 of a share."""

    def setUp(self):
        from bot_program.models import AssetBotConfig
        self.user = _user("frac_u")
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        self.cfg = _live_cfg(self.user, name="FRAC")
        AssetBotConfig.objects.filter(pk=self.cfg.pk).update(
            capital=Decimal("300"))
        self.cfg.refresh_from_db()
        self.inst = _instrument()
        _signal(self.inst)

    def _scan(self, client):
        from bot_program.asset_engine.stock_bot import StockBot
        with mock.patch(ROUTER, return_value=client):
            StockBot(self.cfg).scan_symbol("AAPL")
        self.cfg.refresh_from_db()
        return client

    def _skip(self):
        return (self.cfg.extras.get("skips") or {}).get("AAPL", {})

    def test_a_fraction_is_sent_where_the_venue_takes_it(self):
        from bot_program.asset_engine import skips
        from bot_program.models import AssetBotTrade
        _switch(True)
        client = self._scan(_fractional())
        client.market_order.assert_called_once()
        q = client.market_order.call_args.args[2]
        self.assertGreater(q, 0)
        self.assertLess(q, 1)
        self.assertEqual(q, round(q, 4))
        row = AssetBotTrade.objects.get(config=self.cfg)
        self.assertEqual(row.qty, Decimal(str(round(q, 8))))
        self.assertFalse(row.paper)
        self.assertIs(row.metadata.get("fractional_units"), True)
        self.assertNotIn(self._skip().get("code"),
                         (skips.SIZED_TO_ZERO, skips.VENUE_MIN_SIZE,
                          skips.GATE_BLOCKED))

    def test_the_switch_off_is_todays_behaviour(self):
        from bot_program.asset_engine import skips
        from bot_program.models import AssetBotTrade
        _switch(False)
        client = self._scan(_fractional())
        client.market_order.assert_not_called()
        self.assertFalse(AssetBotTrade.objects.filter(config=self.cfg)
                         .exists())
        self.assertEqual(self._skip().get("code"), skips.SIZED_TO_ZERO)

    def test_a_whole_share_venue_still_sizes_to_zero(self):
        from bot_program.asset_engine import skips
        _switch(True)
        client = self._scan(_venue(None))
        client.market_order.assert_not_called()
        self.assertEqual(self._skip().get("code"), skips.SIZED_TO_ZERO)

    def test_under_the_declared_floor_is_refused_with_the_label(self):
        from alerts.models import Notification
        from bot_program.asset_engine import skips
        _switch(True)
        self.cfg.extras = dict(self.cfg.extras or {},
                               venue_min_notional=1_000_000)
        self.cfg.save(update_fields=["extras"])
        client = self._scan(_fractional())
        client.market_order.assert_not_called()
        note = self._skip()
        self.assertEqual(note.get("code"), skips.VENUE_MIN_SIZE)
        detail = note["detail"]
        for needle in ("1e+06", "units from the stop distance",
                       "x the chosen risk", "operator-declared"):
            self.assertIn(needle, detail, detail)
        self.assertEqual(
            (self.cfg.extras.get("skip_counts") or {})
            .get(skips.VENUE_MIN_SIZE), 1)
        n = Notification.objects.filter(user=self.user,
                                        title__contains="AAPL").first()
        self.assertIsNotNone(n)
        self.assertIn(self.cfg.name, n.title)
        self.assertIn("operator-declared", n.body)
        self.assertIn("TIGHTER stop", n.body)
        self.assertNotIn("widen the stop", n.body)

    def test_a_refused_fraction_carries_the_words_and_quiets_the_symbol(self):
        from alerts.models import Notification
        from bot_program.asset_engine import skips
        _switch(True)
        refused = _fractional(fill={"orderId": "o1", "status": "REJECTED",
                                    "executedQty": "0",
                                    "refusal": "errorCode 123: too small"})
        self._scan(refused)
        note = self._skip()
        self.assertEqual(note.get("code"), skips.ORDER_REJECTED)
        self.assertIn("errorCode 123: too small", note["detail"])
        self.assertEqual(
            self.cfg.extras["entry_fraction_refused"]["AAPL"]["words"],
            "errorCode 123: too small")
        self.assertTrue(Notification.objects.filter(
            user=self.user,
            title__contains="the venue refused a fractional size").exists())
        again = self._scan(_fractional())
        again.market_order.assert_not_called()
        note = self._skip()
        self.assertEqual(note.get("code"), skips.VENUE_MIN_SIZE)
        self.assertIn("errorCode 123: too small", note["detail"][:88])

    def test_a_refused_post_of_a_fraction_is_remembered_too(self):
        from bot_program.asset_engine import skips
        _switch(True)
        client = _fractional()
        client.market_order = mock.MagicMock(
            side_effect=RuntimeError("eToro refused (400): units below "
                                     "minimum"))
        self._scan(client)
        note = self._skip()
        self.assertEqual(note.get("code"), skips.ORDER_ERROR)
        self.assertIn("units below minimum", note["detail"])
        self.assertIn("units below minimum",
                      self.cfg.extras["entry_fraction_refused"]["AAPL"]["words"])

    def test_an_over_fill_is_booked_stamped_and_said(self):
        from alerts.models import Notification
        from bot_program.models import AssetBotTrade
        _switch(True)
        self._scan(_fractional(fill={"orderId": "o1", "status": "FILLED",
                                     "avgPrice": "100",
                                     "executedQty": "1.0"}))
        row = AssetBotTrade.objects.get(config=self.cfg)
        self.assertEqual(row.qty, Decimal("1.0"))
        over = row.metadata["overfilled"]
        self.assertEqual(over["filled"], 1.0)
        self.assertGreater(over["requested"], 0)
        self.assertLess(over["requested"], 1)
        self.assertTrue(Notification.objects.filter(
            title__contains="filled more than was sized").exists())

    def test_the_route_moving_between_proposal_and_order_is_refused(self):
        from bot_program.asset_engine import skips
        from bot_program.asset_engine.stock_bot import StockBot
        from bot_program.models import AssetBotTrade
        _switch(True)
        bot = StockBot(self.cfg)
        with mock.patch(ROUTER, return_value=_fractional()):
            cand = bot.propose_entry("AAPL")
        self.assertIsNotNone(cand)
        self.assertIs(cand.fractional_units, True)
        self.assertGreater(cand.qty_default, 0)
        self.assertLess(cand.qty_default, 1)
        whole = _venue(None)
        with mock.patch(ROUTER, return_value=whole):
            bot.execute_entry(cand)
        whole.market_order.assert_not_called()
        self.assertFalse(AssetBotTrade.objects.filter(config=self.cfg)
                         .exists())
        self.cfg.refresh_from_db()
        note = self._skip()
        self.assertEqual(note.get("code"), skips.GATE_BLOCKED)
        self.assertIn("route moved", note["detail"])
        self.assertIn("Nothing sent, nothing resized", note["detail"])
        fresh = _fractional()
        with mock.patch(ROUTER, return_value=fresh):
            bot.execute_entry(cand)
        fresh.market_order.assert_called_once()
        self.assertEqual(fresh.market_order.call_args.args[2],
                         float(cand.qty_default))

    def test_paper_is_unchanged(self):
        from bot_program.asset_engine.base import AssetBot
        from bot_program.engine.paper_trader import PaperTrader
        _switch(True)
        paper_cfg = _live_cfg(self.user, mode="paper", name="FRACP")
        self.assertIsNone(AssetBot._venue_fractional_units(
            PaperTrader(paper_cfg), "AAPL"))


class ThePreflightIsVenueAware(TestCase):

    def _etoro_pool(self, *, capital, price=230, extras=None):
        from market_data.models import PriceData
        from tests.test_preflight_live import _bars, _cfg, _pin
        from tests.test_preflight_live import _user as _pf_user
        from tests.test_saxo_wiring import etoro
        u = _pf_user()
        etoro(u, flags=("stock",))
        _pin(u)
        cfg = _cfg(u, capital=str(capital), base_currency="USD",
                   symbols=("AAPL",))
        if extras:
            cfg.extras = extras
            cfg.save(update_fields=["extras"])
        inst = _bars("AAPL", age_hours=1.0)
        PriceData.objects.filter(instrument=inst, timeframe="4h").update(
            close=price)
        return u, cfg

    def test_switch_off_is_tonights_honest_state(self):
        from tests.test_preflight_live import _blockers, _run
        self._etoro_pool(capital=150)
        _switch(False)
        out = _run()
        self.assertIn("FRACTIONS at etoro", out)
        self.assertIn("OFF — whole shares", out)
        self.assertIn("ONE UNIT", out)
        self.assertIn("rounds to zero", _blockers(out))

    def test_switch_on_prints_the_fuel_arithmetic_and_no_one_unit_blocker(self):
        from tests.test_preflight_live import _blockers, _run, _worth
        self._etoro_pool(capital=150)
        _switch(True)
        out = _run()
        self.assertIn("ON — fractions sent", out)
        self.assertIn("no venue minimum declared", out)
        self.assertIn("a fraction fits", out)
        self.assertNotIn("ONE UNIT", out)
        self.assertNotIn("rounds to zero", _blockers(out))
        self.assertIn("sellShort", _worth(out))

    def test_a_declared_minimum_prints_the_stop_bound(self):
        from tests.test_preflight_live import _run, _worth
        _, cfg = self._etoro_pool(capital=150,
                                  extras={"venue_min_notional": 10})
        _switch(True)
        out = _run()
        self.assertIn("needs a stop within 3.75%", out)
        self.assertNotIn("tighter than", _worth(out))
        # the same config, a smaller pool: bound < floor <=> pool * cap
        # < minimum, the risk fraction cancels out (40 * 0.20 = 8 < 10);
        # a wider risk_per_trade_pct moves both sides and changes nothing
        cfg.capital = Decimal("40")
        cfg.save(update_fields=["capital"])
        out = _run()
        self.assertIn("tighter than", _worth(out))
        self.assertIn("at most 8.00 of notional", _worth(out))
        self.assertIn("raise max_notional_fraction", _worth(out))
        self.assertNotIn("risk_per_trade_pct", _worth(out))

    def test_an_ibkr_pool_keeps_the_whole_share_blocker(self):
        from tests.test_preflight_live import (_acct, _bars, _blockers, _cfg,
                                               _pin, _run)
        from tests.test_preflight_live import _user as _pf_user
        from market_data.models import PriceData
        u = _pf_user()
        _acct(u, port=4003, equity=100000, currency="USD",
              is_primary_for_stocks=True)
        _pin(u)
        _cfg(u, capital="500", base_currency="USD", symbols=("AAPL",))
        inst = _bars("AAPL", age_hours=1.0)
        PriceData.objects.filter(instrument=inst, timeframe="4h").update(
            close=230)
        _switch(True)
        out = _run()
        self.assertIn("ONE UNIT", out)
        self.assertIn("rounds to zero", _blockers(out))
        self.assertNotIn("FRACTIONS at", out)


class TheComponentRow(TestCase):

    def test_the_row_is_seeded_off_and_under_the_column(self):
        from core.platform_control import (DEFAULT_COMPONENTS,
                                           PlatformComponent,
                                           is_component_enabled,
                                           seed_components)
        rows = [c for c in DEFAULT_COMPONENTS if c["key"] == SWITCH]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["category"], "system")
        self.assertLessEqual(len(rows[0]["description"]), 300)
        self.assertFalse(is_component_enabled(SWITCH))
        seed_components()
        self.assertFalse(PlatformComponent.objects.get(key=SWITCH).is_enabled)


class TheBrokersPageBadgesTheBelief(TestCase):

    def test_the_badge_says_believed(self):
        from django.contrib.auth.models import User
        from django.urls import reverse
        from tests.test_saxo_wiring import etoro
        user = User.objects.create_superuser("frac_page", "f@x", "x")
        etoro(user, flags=("stock",))
        self.client.force_login(user)
        body = self.client.get(reverse("brokers_page")).content.decode()
        self.assertIn("fractional_units", body)
        self.assertIn("(believed)", body)


class ConsumerKeyTests(SimpleTestCase):

    def test_the_adapter_method_is_the_one_the_engine_calls(self):
        import inspect
        from pathlib import Path

        from django.conf import settings

        from bot_program.asset_engine.base import AssetBot
        from bot_program.asset_engine.commodity_bot import CommodityBot
        from bot_program.asset_engine.crypto_bot import CryptoBot
        from bot_program.asset_engine.forex_bot import ForexBot
        from bot_program.asset_engine.stock_bot import StockBot
        root = Path(settings.BASE_DIR)
        base = (root / "bot_program" / "asset_engine" / "base.py"
                ).read_text(encoding="utf-8")
        for needle in ('has_capability(client, "fractional_units")',
                       "client.takes_fractional_units(symbol)",
                       "is_component_enabled(AssetBot.FRACTIONAL_UNITS_COMPONENT)",
                       'res.get("refusal")', 'entry_meta["overfilled"]',
                       'entry_meta["fractional_units"]',
                       "fractional=fractional", "fractional=_fr"):
            self.assertIn(needle, base, needle)
        self.assertIn("fractional_units: Optional[bool] = None",
                      (root / "bot_program" / "asset_engine" / "candidates.py"
                       ).read_text(encoding="utf-8"))
        self.assertIn('out["refusal"]',
                      (root / "bot_program" / "engine" / "etoro_client.py"
                       ).read_text(encoding="utf-8"))
        self.assertIn("fractional is True",
                      (root / "bot_program" / "asset_engine" / "stock_bot.py"
                       ).read_text(encoding="utf-8"))
        for cls in (AssetBot, StockBot, ForexBot, CryptoBot, CommodityBot):
            p = inspect.signature(cls._round_qty).parameters["fractional"]
            self.assertEqual(p.kind, inspect.Parameter.KEYWORD_ONLY,
                             cls.__name__)
            self.assertIsNone(p.default, cls.__name__)
