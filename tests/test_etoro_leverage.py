"""eToro leverage: a PASS-THROUGH behind a proof switch (2026-09-23).

extras["leverage"] on a config is a whole number the ENGINE hands to
EtoroTrader.market_order as a kwarg and records on the row. It changes the
margin eToro locks and nothing this engine measures: units still come from
risk_per_trade_pct and the stop (sizing.qty_for_risk), the notional cap and
the stop floor are judged on qty x price, and the loss at the stop is the
same at any multiplier. Every refusal is a `leverage_refused` skip that
sends nothing: an unreadable value, a carrier that is not eToro, a value
past the platform cap or the believed class ceiling, the switch OFF, no own
book on /setup/, and — past the switch — an account whose available cash
(the sync's cells) is unmeasured, stale, in another currency, too small, or
that would be pledged past its ceiling; and, after eToro refused a levered
order on a symbol, that symbol for the quiet hours.

The eToro client is the REAL class with its transport replaced — never a
subclass, because capabilities.adapter_key reads the class name.
"""
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from tests.test_desk_seam import _client as _mock_client
from tests.test_etoro_client import SEARCH_AAPL, _FakeSession, _lookup
from tests.test_execution_trust import _cfg as _live_cfg
from tests.test_execution_trust import _instrument, _signal, _trade, _user

ROUTER = "bot_program.engine.broker_router.client_for_symbol"
POSTED = ("POST", "/execution/demo/orders", 200,
          {"orderId": 777, "referenceId": "ref-1"})
RATES = ("GET", "/rates", 200, {"rates": [
    {"bid": 99.9, "ask": 100.1, "lastExecution": 100.0}]})


def _etoro(routes=None, *, echo_stop=None):
    """The real adapter over a fake wire. The lookup fixture hard-codes a
    venue stop of 180; it is DROPPED here so the pass-through tests do not
    record a rewrite by accident, and set to `echo_stop` when a test wants
    the venue to answer a different stop than the one sent."""
    from bot_program.engine.etoro_client import EtoroTrader
    lk = _lookup(3, units=3.0, avg=100.0)
    ex = lk["positionExecutions"][0]
    if echo_stop is None:
        ex.pop("stopLossRate", None)
        ex.pop("takeProfitRate", None)
    else:
        ex["stopLossRate"] = echo_stop
    t = EtoroTrader("api-k", "user-k", env="demo")
    t._session = _FakeSession(list(routes or [
        SEARCH_AAPL, RATES, POSTED, ("GET", "orders:lookup", 200, lk)]))
    return t, t._session


def _switch(on):
    from bot_program.asset_engine.base import LEVERAGE_SWITCH_KEY
    from core.platform_control import PlatformComponent
    PlatformComponent.objects.update_or_create(
        key=LEVERAGE_SWITCH_KEY,
        defaults={"name": "t", "category": "system", "is_enabled": on})


def _book(user, value="100000"):
    """The operator's OWN book on /setup/ — what MAX TOTAL EXPOSURE is a
    percentage of once it exists."""
    from portfolio.models import Portfolio
    return Portfolio.objects.create(
        name=f"{user.username}_main", initial_capital=Decimal(value),
        current_value=Decimal(value), cash_available=Decimal(value),
        currency="USD")


def _account(user, *, cash=None, used=0, age_s=60, currency="USD",
             equity=100000):
    from bot_program.models import EtoroAccount
    acct = EtoroAccount.objects.create(user=user, demo=True, label="Main",
                                       is_primary_for_stocks=True)
    acct.set_credentials("k", "u")
    acct.last_equity = Decimal(str(equity))
    acct.last_equity_currency = currency
    acct.last_equity_at = timezone.now()
    if cash is not None:
        acct.last_available_cash = Decimal(str(cash))
        acct.last_used_margin = Decimal(str(used))
        acct.last_margin_at = timezone.now() - timedelta(seconds=age_s)
    acct.save()
    return acct


class TheRuleTests(TestCase):
    """judge_order_leverage — the one rule the tick, the preflight and the
    TAKE TRADE lane share."""

    def setUp(self):
        self.user = _user("lev_rule")

    def _cfg(self, **extras):
        # one row per call: (user, asset_class, name) is unique and a
        # subTest loop asks for several
        self._n = getattr(self, "_n", 0) + 1
        cfg = _live_cfg(self.user, name="LEV%d" % self._n)
        cfg.extras = extras
        val = extras.get("leverage")
        if isinstance(val, float) and val != val:
            # NaN is not JSON: no row can carry it (JSON_VALID refuses
            # it) — the judge is handed it in memory only
            return cfg
        cfg.save(update_fields=["extras"])
        return cfg

    def test_no_key_means_no_kwarg_and_no_claim(self):
        from bot_program.asset_engine.base import judge_order_leverage
        self.assertEqual(judge_order_leverage(self._cfg(), "stock", "etoro"),
                         (None, ""))

    def test_a_typed_one_is_said_not_silent(self):
        from bot_program.asset_engine.base import judge_order_leverage
        self.assertEqual(
            judge_order_leverage(self._cfg(leverage=1), "stock", "etoro"),
            (1, ""))

    def test_an_unreadable_value_is_refused_not_defaulted(self):
        from bot_program.asset_engine.base import judge_order_leverage
        _switch(True)
        for bad in ("2x", "2", 1.5, 0, -2, True, None, float("nan")):
            with self.subTest(bad=bad):
                lev, why = judge_order_leverage(self._cfg(leverage=bad),
                                                "stock", "etoro")
                self.assertIsNone(lev)
                self.assertIn("leverage", why)

    def test_a_carrier_that_is_not_etoro_is_refused(self):
        from bot_program.asset_engine.base import judge_order_leverage
        _switch(True)
        for carrier in ("saxo", "ibkr", "paper", ""):
            with self.subTest(carrier=carrier):
                lev, why = judge_order_leverage(self._cfg(leverage=2),
                                                "stock", carrier)
                self.assertIsNone(lev)
                self.assertIn("eToro per-order", why)

    def test_past_the_platform_cap_and_the_class_belief_are_refused_not_clamped(self):
        from bot_program.asset_engine.base import (MAX_ORDER_LEVERAGE,
                                                   ORDER_LEVERAGE_CEILING,
                                                   judge_order_leverage)
        _switch(True)
        lev, why = judge_order_leverage(
            self._cfg(leverage=MAX_ORDER_LEVERAGE + 1), "stock", "etoro")
        self.assertIsNone(lev)
        self.assertIn(f"platform cap of {MAX_ORDER_LEVERAGE}x", why)
        self.assertIn("not clamped", why)
        for cls, cap in ORDER_LEVERAGE_CEILING.items():
            with self.subTest(cls=cls):
                self.assertLessEqual(cap, MAX_ORDER_LEVERAGE)
                lev, why = judge_order_leverage(self._cfg(leverage=cap + 1),
                                                cls, "etoro")
                self.assertIsNone(lev)
                self.assertIn("x", why)
        lev, why = judge_order_leverage(self._cfg(leverage=2), "forex",
                                        "etoro")
        self.assertIsNone(lev)
        self.assertIn("1x ceiling", why)
        lev, why = judge_order_leverage(self._cfg(leverage=3), "crypto",
                                        "etoro")
        self.assertIn("2x", why)
        self.assertIn("belief", why)

    def test_the_switch_off_or_missing_refuses_and_names_the_proof(self):
        from bot_program.asset_engine.base import judge_order_leverage
        lev, why = judge_order_leverage(self._cfg(leverage=2), "stock",
                                        "etoro")
        self.assertIsNone(lev, "a missing switch row must read OFF")
        self.assertIn("etoro_leverage_live is OFF", why)
        self.assertIn("D2b", why)
        _switch(False)
        self.assertIn("OFF", judge_order_leverage(
            self._cfg(leverage=2), "stock", "etoro")[1])

    def test_no_own_book_refuses_naming_setup(self):
        from bot_program.asset_engine.base import judge_order_leverage
        _switch(True)
        lev, why = judge_order_leverage(self._cfg(leverage=2), "stock",
                                        "etoro")
        self.assertIsNone(lev)
        self.assertIn("/setup/", why)
        _book(self.user, value="0")
        lev, why = judge_order_leverage(self._cfg(leverage=2), "stock",
                                        "etoro")
        self.assertIsNone(lev)
        self.assertIn("/setup/", why)

    def test_allowed_is_the_integer(self):
        from bot_program.asset_engine.base import judge_order_leverage
        _switch(True)
        _book(self.user)
        self.assertEqual(
            judge_order_leverage(self._cfg(leverage=2.0), "stock", "etoro"),
            (2, ""))


class TheCapsAgreeTests(SimpleTestCase):
    """LEVERAGE_MAX is restated in the adapter (engine/ never imports
    asset_engine/); this pins the two numbers equal."""

    def test_the_adapter_ceiling_is_the_engine_cap(self):
        from bot_program.asset_engine.base import (MAX_ORDER_LEVERAGE,
                                                   ORDER_LEVERAGE_CEILING)
        from bot_program.engine.etoro_client import LEVERAGE_MAX
        self.assertEqual(LEVERAGE_MAX, MAX_ORDER_LEVERAGE)
        for cls, cap in ORDER_LEVERAGE_CEILING.items():
            self.assertLessEqual(cap, MAX_ORDER_LEVERAGE, cls)
        self.assertEqual(ORDER_LEVERAGE_CEILING["forex"], 1)


class TheEntryPassesItThroughTests(TestCase):
    """execute_entry on a LIVE stock config: the candidate is priced through
    the desk-seam MagicMock (propose), the order goes through the REAL
    EtoroTrader with a fake wire (execute). The rule is promoted to a live
    stage by tests.test_execution_trust._signal, or the stage forces paper."""

    def setUp(self):
        self.user = _user("lev_entry")
        self.cfg = _live_cfg(self.user, name="LEV")
        self.cfg.base_currency = "USD"
        self.cfg.extras = {"leverage": 2}
        self.cfg.save(update_fields=["base_currency", "extras"])
        _signal(_instrument(), rule="lev_rule")
        _book(self.user)
        # C0 (2026-09-24): ETORO_PROVEN ships EMPTY, so every eToro-carried
        # entry below is gate_blocked before the floor and the multiplier
        # unless its class is named. These tests are about the multiplier:
        # "stock" is stated proven HERE, for this class only, never in the
        # tree — the empty-set case has its own test below.
        self._proven("stock")

    def _proven(self, *tokens):
        """State `tokens` as proven for the rest of this test. The gate
        reads base.ETORO_PROVEN at CALL time, so a patch on the module
        global is what it sees; undone at cleanup (LIFO, so a second call
        with the empty set wins until the test ends)."""
        p = mock.patch("bot_program.asset_engine.base.ETORO_PROVEN",
                       frozenset(tokens))
        p.start()
        self.addCleanup(p.stop)
        return p

    def _cand(self):
        from bot_program.asset_engine.stock_bot import StockBot
        self.bot = StockBot(self.cfg)
        with mock.patch(ROUTER, return_value=_mock_client("100.00")):
            cand = self.bot.propose_entry("AAPL")
        self.assertIsNotNone(cand)
        self.assertGreater(cand.qty_default, 0)
        return cand

    def _skip_note(self):
        from bot_program.asset_engine import skips
        self.cfg.refresh_from_db()
        return skips.last_by_symbol(self.cfg)["AAPL"]

    def _execute(self, cand, t):
        with mock.patch(ROUTER, return_value=t), mock.patch("time.sleep"):
            return self.bot.execute_entry(cand)

    def test_an_unproven_class_is_gate_blocked_before_the_floor_and_the_post(self):
        """ETORO_PROVEN as the tree ships it (empty, 2026-09-24): the same
        LIVE stock config, the switch ON, the cells fresh, the same real
        adapter — and the gate refuses naming "stock" before the venue
        floor (no _notify_venue_min_size), before the multiplier (the
        skip is gate_blocked, not leverage_refused) and before any POST.
        EtoroTrader declares no size_floor, so the floor is made REACHABLE
        here by declaring extras['venue_min_notional'] far above the order:
        a gate placed after the floor would record venue_min_size and
        notify — which is what makes the two floor pins bite."""
        from bot_program.asset_engine import skips
        from bot_program.models import AssetBotTrade
        _switch(True)
        _account(self.user, cash=100000)
        self.cfg.extras = {"leverage": 2, "venue_min_notional": 1e9}
        self.cfg.save(update_fields=["extras"])
        cand = self._cand()
        self._proven()                        # the shipped set: nothing
        t, fake = _etoro()
        with mock.patch("bot_program.asset_engine.base.AssetBot"
                        "._notify_venue_min_size") as floor_note:
            res = self._execute(cand, t)
        self.assertIsNone(res)
        self.assertEqual([c for c in fake.calls if c[0] == "POST"], [],
                         "an order left the box on an unproven class")
        floor_note.assert_not_called()
        self.assertEqual(AssetBotTrade.objects.count(), 0)
        note = self._skip_note()
        self.assertEqual(note["code"], skips.GATE_BLOCKED)
        self.assertTrue(note["detail"].startswith("eToro AAPL (stock, BUY): "),
                        note)
        self.assertIn("no demo fill-and-close proof pinned for ['stock']",
                      note["detail"])

    def test_the_whole_refusal_words_reach_the_log_where_the_record_cuts_them(self):
        """The DIRECT refusal (a REJECTED answered by market_order, not a
        held order): the skip detail keeps the verdict first and
        skips.record keeps 200 characters, so the venue's minimum — the
        LAST words of the measured 720 message — falls off the record.
        Since 2026-09-24 the log line carries the whole message, so the
        number debt 1 set out to keep is somewhere on every direct
        refusal too (the held-order path lands it whole in
        entry_withdrawn_reason)."""
        from bot_program.asset_engine import skips
        from tests.test_etoro_client import REJECTED_720
        _switch(True)
        _account(self.user, cash=100000)
        cand = self._cand()
        t, fake = _etoro([SEARCH_AAPL, RATES, POSTED,
                          ("GET", "orders:lookup", 200, REJECTED_720)])
        with self.assertLogs("bot_program.asset_engine.base",
                             level="WARNING") as cm:
            res = self._execute(cand, t)
        self.assertIsNone(res)
        self.assertEqual(len([c for c in fake.calls if c[0] == "POST"]), 1)
        note = self._skip_note()
        self.assertEqual(note["code"], skips.ORDER_REJECTED)
        self.assertTrue(note["detail"].startswith(
            "at 2x: broker status REJECTED: errorCode 720: Error opening "
            "position"), note)
        tail = "InitialPositionAmount: 8.44 MinimumPositionAmount: 10 (Dollars)"
        self.assertLessEqual(len(note["detail"]), 200, "skips.record's bound")
        self.assertNotIn(tail, note["detail"], "the record's cut, measured")
        self.assertTrue(any(tail in line for line in cm.output), cm.output)

    def test_the_kwarg_reaches_the_body_and_the_row_records_it(self):
        from bot_program.models import AssetBotTrade
        _switch(True)
        _account(self.user, cash=100000)
        cand = self._cand()
        t, fake = _etoro()
        res = self._execute(cand, t)
        self.assertIsNotNone(res)
        body = [c for c in fake.calls if c[0] == "POST"][0][2]["json"]
        self.assertEqual(body["leverage"], 2)
        self.assertAlmostEqual(body["units"], float(cand.qty_default),
                               places=6, msg="leverage must not touch units")
        trade = AssetBotTrade.objects.get(id=res["trade_id"])
        self.assertEqual(trade.metadata["leverage"], 2)
        self.assertEqual(trade.metadata["broker"], "etoro")
        self.assertAlmostEqual(float(trade.metadata["risk_dollars"]),
                               cand.sizing["risk_dollars"], places=6)
        self.assertNotIn("stop_rewritten_by_venue", trade.metadata)

    def test_the_switch_off_sends_nothing_at_any_multiplier(self):
        from bot_program.asset_engine import skips
        from bot_program.models import AssetBotTrade
        _switch(False)
        _account(self.user, cash=100000)
        cand = self._cand()
        t, fake = _etoro()
        res = self._execute(cand, t)
        self.assertIsNone(res)
        self.assertEqual([c for c in fake.calls if c[0] == "POST"], [],
                         "an order left the box while the switch was OFF")
        self.assertEqual(AssetBotTrade.objects.count(), 0)
        note = self._skip_note()
        self.assertEqual(note["code"], skips.LEVERAGE_REFUSED)
        self.assertIn("etoro_leverage_live", note["detail"])

    def test_a_config_without_the_key_passes_no_kwarg_and_records_nothing(self):
        from bot_program.models import AssetBotTrade
        self.cfg.extras = {}
        self.cfg.save(update_fields=["extras"])
        cand = self._cand()
        t, fake = _etoro()
        res = self._execute(cand, t)
        self.assertIsNotNone(res)
        body = [c for c in fake.calls if c[0] == "POST"][0][2]["json"]
        self.assertEqual(body["leverage"], 1, "the adapter's own default")
        trade = AssetBotTrade.objects.get(id=res["trade_id"])
        self.assertNotIn("leverage", trade.metadata)

    def test_a_typed_one_passes_no_kwarg_and_records_one(self):
        from bot_program.models import AssetBotTrade
        self.cfg.extras = {"leverage": 1}
        self.cfg.save(update_fields=["extras"])
        cand = self._cand()
        t, fake = _etoro()
        with mock.patch.object(t, "market_order",
                               wraps=t.market_order) as spy, \
                mock.patch(ROUTER, return_value=t), \
                mock.patch("time.sleep"):
            res = self.bot.execute_entry(cand)
        self.assertIsNotNone(res)
        self.assertNotIn("leverage", spy.call_args.kwargs,
                         "a typed 1 is the default: no kwarg")
        body = [c for c in fake.calls if c[0] == "POST"][0][2]["json"]
        self.assertEqual(body["leverage"], 1)
        trade = AssetBotTrade.objects.get(id=res["trade_id"])
        self.assertEqual(trade.metadata["leverage"], 1)

    def test_a_non_etoro_carrier_is_refused_before_anything_is_sent(self):
        """The desk-seam MagicMock is a client the adapter map has never
        heard of — adapter_key answers "" — and above 1 that is refused,
        exactly as Saxo or IBKR would be."""
        from bot_program.asset_engine import skips
        _switch(True)
        cand = self._cand()
        other = _mock_client("100.00")
        with mock.patch(ROUTER, return_value=other):
            res = self.bot.execute_entry(cand)
        self.assertIsNone(res)
        other.market_order.assert_not_called()
        self.assertEqual(self._skip_note()["code"], skips.LEVERAGE_REFUSED)

    def _refused_for(self, **acct_kw):
        from bot_program.asset_engine import skips
        _switch(True)
        _account(self.user, **acct_kw)
        cand = self._cand()
        t, fake = _etoro()
        res = self._execute(cand, t)
        self.assertIsNone(res)
        self.assertEqual([c for c in fake.calls if c[0] == "POST"], [])
        note = self._skip_note()
        self.assertEqual(note["code"], skips.LEVERAGE_REFUSED)
        return note["detail"], cand

    def test_headroom_never_stored_is_refused(self):
        detail, _ = self._refused_for(cash=None)
        self.assertIn("never been stored", detail)

    def test_headroom_stale_is_refused(self):
        detail, _ = self._refused_for(cash=100000, age_s=2 * 3600)
        self.assertIn("h old", detail)

    def test_headroom_in_another_currency_is_refused(self):
        detail, _ = self._refused_for(cash=100000, currency="EUR")
        self.assertIn("nothing here converts", detail)

    def test_headroom_too_small_names_both_numbers(self):
        detail, cand = self._refused_for(cash=1)
        self.assertIn("of margin and", detail)
        self.assertIn("is free", detail)

    def test_pledged_past_the_ceiling_is_refused(self):
        detail, _ = self._refused_for(cash=10 ** 6, used=60000,
                                      equity=100000)
        self.assertIn("pledged after", detail)
        self.assertIn("50%", detail)

    def test_rows_opened_since_the_reading_are_charged_first(self):
        """cash = need + 100, and a levered eToro row opened after the
        reading pledges 200 (qty 4 x 100 / 2): free = need - 100 -> refused."""
        from bot_program.models import AssetBotTrade
        _switch(True)
        cand = self._cand()
        need = float(cand.qty_default) * 100.0 / 2.0
        acct = _account(self.user, cash=need + 100, age_s=120)
        row = _trade(self.cfg, symbol="MSFT", qty=Decimal("4"),
                     entry_price=Decimal("100"))
        row.metadata = {"broker": "etoro", "leverage": 2}
        row.save(update_fields=["metadata"])
        AssetBotTrade.objects.filter(pk=row.pk).update(
            opened_at=acct.last_margin_at + timedelta(seconds=1))
        t, fake = _etoro()
        res = self._execute(cand, t)
        self.assertIsNone(res)
        self.assertIn("200.00 pledged since", self._skip_note()["detail"])

    def test_an_unkeyed_etoro_row_is_charged_in_full_and_a_saxo_row_is_not(self):
        from bot_program.models import AssetBotTrade
        _switch(True)
        cand = self._cand()
        need = float(cand.qty_default) * 100.0 / 2.0
        acct = _account(self.user, cash=need + 100, age_s=120)
        row_a = _trade(self.cfg, symbol="MSFT", qty=Decimal("4"),
                       entry_price=Decimal("100"))
        row_a.metadata = {"broker": "etoro"}
        row_a.save(update_fields=["metadata"])
        AssetBotTrade.objects.filter(pk=row_a.pk).update(
            opened_at=acct.last_margin_at + timedelta(seconds=1))
        t, fake = _etoro()
        res = self._execute(cand, t)
        self.assertIsNone(res)
        self.assertIn("400.00 pledged since", self._skip_note()["detail"])
        row_a.delete()
        row_b = _trade(self.cfg, symbol="MSFT", qty=Decimal("4"),
                       entry_price=Decimal("100"))
        row_b.metadata = {"broker": "saxo"}
        row_b.save(update_fields=["metadata"])
        AssetBotTrade.objects.filter(pk=row_b.pk).update(
            opened_at=acct.last_margin_at + timedelta(seconds=1))
        acct.last_available_cash = Decimal(str(round(need + 1, 2)))
        acct.save(update_fields=["last_available_cash"])
        cand = self._cand()
        t, fake = _etoro()
        res = self._execute(cand, t)
        # the note is read only when there is one to read: a success
        # leaves no skip for the symbol and _skip_note would raise
        self.assertIsNotNone(res, None if res is not None
                             else self._skip_note())

    def test_a_levered_rejection_quiets_the_symbol(self):
        from bot_program.asset_engine import skips
        _switch(True)
        _account(self.user, cash=100000)
        cand = self._cand()
        t, fake = _etoro([SEARCH_AAPL, RATES, POSTED,
                          ("GET", "orders:lookup", 200,
                           _lookup(4, units=0, avg=0))])
        res = self._execute(cand, t)
        self.assertIsNone(res)
        first = self._skip_note()
        self.assertEqual(first["code"], skips.ORDER_REJECTED)
        self.assertTrue(first["detail"].startswith("at 2x: broker status "
                                                   "REJECTED"), first)
        self.assertEqual(len([c for c in fake.calls if c[0] == "POST"]), 1)
        cand = self._cand()
        t2, fake2 = _etoro()
        res = self._execute(cand, t2)
        self.assertIsNone(res)
        second = self._skip_note()
        self.assertEqual(second["code"], skips.LEVERAGE_REFUSED)
        self.assertIn("quiet for 12h", second["detail"])
        self.assertEqual([c for c in fake2.calls if c[0] == "POST"], [],
                         "a second POST left the box inside the quiet hours")

    def test_a_rewritten_stop_is_recorded_on_the_row(self):
        from bot_program.models import AssetBotTrade
        _switch(True)
        _account(self.user, cash=100000)
        cand = self._cand()
        t, _ = _etoro(echo_stop=170.0)
        res = self._execute(cand, t)
        self.assertIsNotNone(res)
        trade = AssetBotTrade.objects.get(id=res["trade_id"])
        self.assertEqual(trade.metadata["stop_rewritten_by_venue"],
                         {"sent": float(cand.stop), "held": 170.0})
        self.assertEqual(float(trade.metadata["initial_stop_loss"]),
                         float(cand.stop),
                         "the risk denominator must not move")

    def test_a_failed_poll_books_working_and_says_so(self):
        from bot_program.models import AssetBotTrade
        _switch(True)
        _account(self.user, cash=100000)
        cand = self._cand()
        t, _ = _etoro([SEARCH_AAPL, RATES, POSTED,
                       ("GET", "orders:lookup", 503, {})])
        res = self._execute(cand, t)
        self.assertIsNotNone(res)
        trade = AssetBotTrade.objects.get(id=res["trade_id"])
        self.assertEqual(trade.status, "OPEN")
        self.assertTrue(trade.metadata.get("entry_working"))
        self.assertTrue(trade.metadata.get("entry_poll_failed"))
        self.assertFalse(trade.metadata.get("protected"))
        self.assertEqual(trade.metadata["leverage"], 2)

    def test_the_open_order_id_is_stored_on_the_row_as_broker_order_id(self):
        """The regression pin for the first demo night's row: a filled order
        whose poll went by referenceId booked WORKING/pollFailed. Polled by
        the acceptance's orderId, the row records the fill and the handles
        the close will need."""
        from bot_program.models import AssetBotTrade
        from tests.test_etoro_client import (ACCEPTED, _lookup_router,
                                             _measured_lookup)
        _switch(True)
        _account(self.user, cash=100000)
        cand = self._cand()
        t, fake = _etoro([SEARCH_AAPL, RATES,
                          ("POST", "/execution/demo/orders", 200, ACCEPTED)])
        _lookup_router(fake, by_order=(200, _measured_lookup(
            stop=float(cand.stop), units=float(cand.qty_default),
            avg=100.0)))
        res = self._execute(cand, t)
        self.assertIsNotNone(res, self._skip_note() if res is None else "")
        trade = AssetBotTrade.objects.get(id=res["trade_id"])
        self.assertEqual(trade.broker_order_id, "383454450")
        self.assertEqual(trade.metadata["broker_position_id"], "3603281458")
        self.assertEqual(trade.metadata["leverage"], 2)
        for absent in ("entry_working", "entry_poll_failed",
                       "stop_rewritten_by_venue"):
            self.assertNotIn(absent, trade.metadata, absent)
        for _m, _u, k in fake.calls:
            self.assertNotIn("referenceId", k.get("params") or {})


class TheSyncStoresTheMarginCellsTests(TestCase):

    def setUp(self):
        from django.contrib.auth.models import User
        from django.core.cache import cache
        from tests.test_sync_walks_etoro import _etoro as _acct
        cache.clear()
        self.user = User.objects.create_user("lev_sync", password="x")
        self.acct = _acct(self.user)

    def _run(self, cells):
        from tests.test_sync_walks_etoro import _client, _sync_etoro
        from bot_program.models import EtoroAccount
        c = _client()
        if cells is not ...:
            c.margin_cells.return_value = cells
        out = _sync_etoro(c)
        return out, EtoroAccount.objects.get(pk=self.acct.pk)

    def test_cells_land_with_the_equity_on_one_clock(self):
        out, acct = self._run({"available_cash": 1.4, "used_margin": 0.0,
                               "currency": "USD"})
        self.assertEqual(out["stored"], 1)
        self.assertEqual(acct.last_available_cash, Decimal("1.40"))
        self.assertEqual(acct.last_used_margin, Decimal("0.00"))
        self.assertEqual(acct.last_margin_at, acct.last_equity_at)

    def test_a_mock_that_answers_no_dict_leaves_the_cells_none(self):
        out, acct = self._run(...)
        self.assertEqual(out["stored"], 1)
        self.assertIsNone(acct.last_available_cash)
        self.assertIsNone(acct.last_used_margin)
        self.assertIsNone(acct.last_margin_at)

    def test_each_cell_lands_on_its_own(self):
        _, acct = self._run({"available_cash": None, "used_margin": 5.0,
                             "currency": "USD"})
        self.assertIsNone(acct.last_available_cash)
        self.assertEqual(acct.last_used_margin, Decimal("5.00"))
        self.assertIsNotNone(acct.last_margin_at)


class MarginCellsReadTests(SimpleTestCase):
    """The REAL payload shape (tests/test_etoro_client.TheTotalsAreNestedTests,
    measured 2026-09-22) read for the two margin figures."""

    def _t(self, payload):
        from bot_program.engine.etoro_client import EtoroTrader
        t = EtoroTrader("k", "u", env="live")
        t.account = lambda: payload
        return t

    def test_the_two_figures_come_from_the_nested_block(self):
        from tests.test_etoro_client import TheTotalsAreNestedTests as R
        self.assertEqual(self._t(R.REAL).margin_cells(),
                         {"available_cash": 1000.0, "used_margin": 0.0,
                          "currency": "USD"})

    def test_a_missing_block_is_none_per_figure_and_a_failed_read_is_none(self):
        cells = self._t({"accountCurrency": "USD"}).margin_cells()
        self.assertEqual(cells, {"available_cash": None, "used_margin": None,
                                 "currency": "USD"})
        from bot_program.engine.etoro_client import EtoroTrader
        t = EtoroTrader("k", "u", env="live")

        def boom():
            raise RuntimeError("HTTP 503")
        t.account = boom
        self.assertIsNone(t.margin_cells())


class ConsumerKeyTests(SimpleTestCase):
    """The keys, read out of the CONSUMERS — tests/test_saxo_client.py's
    pattern — never out of the adapter alone."""

    def test_the_engine_writes_the_kwarg_and_the_row_key_the_readers_read(self):
        import inspect
        import textwrap
        from pathlib import Path

        from django.conf import settings

        from bot_program.asset_engine.base import AssetBot
        src = textwrap.dedent(inspect.getsource(AssetBot.execute_entry))
        for needle in ('order_kwargs["leverage"] = leverage',
                       'entry_meta["leverage"]', "skips.LEVERAGE_REFUSED",
                       'entry_meta["stop_rewritten_by_venue"]',
                       'entry_meta["entry_poll_failed"]',
                       '"venueStopLoss"', '"pollFailed"'):
            self.assertIn(needle, src)
        root = Path(settings.BASE_DIR)
        self.assertIn('"leverage"', (root / "bot_program" / "broker_vision.py"
                                     ).read_text(encoding="utf-8"))
        self.assertIn("leverage", (root / "bot_program" / "management"
                                   / "commands" / "treasury.py"
                                   ).read_text(encoding="utf-8"))
        adapter = (root / "bot_program" / "engine" / "etoro_client.py"
                   ).read_text(encoding="utf-8")
        for needle in ('kwargs.get("leverage")', "def margin_cells",
                       '"venueStopLoss"', '"pollFailed"'):
            self.assertIn(needle, adapter)
        for rel in ("bot_program/tasks.py",
                    "bot_program/management/commands/etoro_smoke.py"):
            self.assertIn("margin_cells",
                          (root / rel).read_text(encoding="utf-8"), rel)
        for rel in ("bot_program/management/commands/preflight_live.py",
                    "bot_program/manual_trade.py"):
            self.assertIn("judge_order_leverage",
                          (root / rel).read_text(encoding="utf-8"), rel)

    def test_sizing_never_reads_it(self):
        """House rule 5, greppable: the module that decides units has no
        seat for a multiplier (its one 'leverage' is the comment at :101)."""
        from pathlib import Path

        from django.conf import settings
        body = (Path(settings.BASE_DIR) / "bot_program" / "asset_engine"
                / "sizing.py").read_text(encoding="utf-8")
        self.assertNotIn('"leverage"', body)
        self.assertNotIn("leverage", body.replace(
            "the leverage is at the broker", ""))

    def test_the_skip_code_is_its_own_word(self):
        from bot_program.asset_engine import skips
        self.assertEqual(skips.LEVERAGE_REFUSED, "leverage_refused")
        self.assertNotIn(skips.LEVERAGE_REFUSED, {
            skips.GATE_BLOCKED, skips.ORDER_ERROR, skips.VENUE_MIN_SIZE,
            skips.SIZED_TO_ZERO})


class TheAdviceLineTests(TestCase):

    def test_diagnose_has_an_advice_line(self):
        """diagnose() reads a CONFIG and reports its top code, so the advice
        is reached the way the operator reaches it: through a recorded
        skip (tests/test_venue_min_size.py's idiom)."""
        from bot_program.asset_engine import skips
        cfg = _live_cfg(_user("lev_advice"), name="LADV")
        skips.record(cfg, "AAPL", skips.LEVERAGE_REFUSED,
                     "at 2x: etoro_leverage_live is OFF")
        cfg.refresh_from_db()
        self.assertIn("nothing was sent at 1", skips.diagnose(cfg))


class TheComponentShipsOffTests(TestCase):

    def test_the_row_is_seeded_off_and_under_the_column(self):
        from core.platform_control import (PlatformComponent,
                                           is_component_enabled,
                                           seed_components)
        self.assertFalse(is_component_enabled("etoro_leverage_live"))
        seed_components()
        row = PlatformComponent.objects.get(key="etoro_leverage_live")
        self.assertFalse(row.is_enabled)
        self.assertLessEqual(len(row.description), 300)
        self.assertIn("D2b", row.description)
