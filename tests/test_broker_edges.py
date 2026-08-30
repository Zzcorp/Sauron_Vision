"""The edges where a broker answers something other than yes or no.

Five defects, all on paths that only run when an order half-worked:

 * A partial fill retracted the two protective children but passed
   `None` for the parent, leaving an unfilled MarketOrder remainder live
   at TWS under the default DAY TIF. We reported the partial as the
   fill, booked a row for that smaller quantity, and the rest filled
   after we had stopped looking — naked at the broker and absent from
   the row.

 * `ticker()` guarded on `if t.last`. ib_insync initialises
   Ticker.last/bid/ask to float("nan") and bool(nan) is True, so the
   bid/ask midpoint branch — written for FX on IDEALPRO, which has no
   last trade at all — never executed, and the method returned "nan".

 * `klines()` tested `isinstance(b.date, datetime)`. ib_insync returns a
   plain `date` for 1 day / 1 week / 1 month, and a `date` is not an
   instance of `datetime`; the inheritance runs the other way. Every
   daily and weekly bar was stamped 0.

 * The entry path refused on broker status alone. The close path in the
   same file has always honoured its refusal list only when nothing
   filled, because a broker that fills part of an order and cancels the
   remainder has still put real units in the account. IBKR reaches that
   state by design.

 * On the close-rejected retry branch, the answer from
   `_cancel_protective_orders` was discarded, so a stop we could not
   confirm cancelled left no trace once the retry succeeded.

Run with:  python manage.py test tests.test_broker_edges
"""
from datetime import date, datetime, timezone as dt_timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase


# ── ticker: a NaN is not a price ─────────────────────────────────────
class ANaNIsNeverAPriceTests(SimpleTestCase):
    def _tick(self, last, bid, ask):
        from bot_program.engine import ibkr_client
        from bot_program.engine.ibkr_client import IBKRTrader
        t = IBKRTrader.__new__(IBKRTrader)
        t._connected = True
        t._ib = MagicMock()
        t._ib.reqMktData.return_value = SimpleNamespace(
            last=last, bid=bid, ask=ask)
        with patch.object(ibkr_client, "_ib", MagicMock()), \
                patch.object(t, "_connect", return_value=True), \
                patch.object(t, "_build_contract", return_value=MagicMock()):
            return t.ticker("EURUSD")

    def test_a_forex_contract_with_no_last_uses_the_midpoint(self):
        """IDEALPRO quotes a bid and an ask and never a last trade. This
        is the case the fallback was written for and could not reach."""
        out = self._tick(float("nan"), 1.0840, 1.0842)
        self.assertAlmostEqual(float(out["lastPrice"]), 1.0841, places=6)

    def test_no_field_ever_serialises_as_nan(self):
        out = self._tick(float("nan"), float("nan"), float("nan"))
        for key in ("lastPrice", "bid", "ask"):
            self.assertNotIn("nan", out[key].lower(), key)
        self.assertEqual(float(out["lastPrice"]), 0.0)

    def test_a_real_last_still_wins(self):
        out = self._tick(1.0850, 1.0840, 1.0842)
        self.assertAlmostEqual(float(out["lastPrice"]), 1.0850, places=6)

    def test_the_price_survives_a_decimal_comparison(self):
        """`if last > 0` on a Decimal('NaN') raises InvalidOperation —
        which the data feed swallowed as an error count."""
        out = self._tick(float("nan"), float("nan"), float("nan"))
        self.assertFalse(Decimal(out["lastPrice"]) > 0)


# ── klines: a daily bar is a date, not a datetime ────────────────────
class ADailyBarHasATimestampTests(SimpleTestCase):
    def test_a_date_becomes_midnight_utc(self):
        from bot_program.engine.ibkr_client import _bar_millis
        ms = _bar_millis(date(2026, 8, 24))
        self.assertEqual(
            datetime.fromtimestamp(ms / 1000, tz=dt_timezone.utc),
            datetime(2026, 8, 24, tzinfo=dt_timezone.utc))

    def test_an_aware_datetime_is_unchanged(self):
        from bot_program.engine.ibkr_client import _bar_millis
        dt = datetime(2026, 8, 24, 13, 30, tzinfo=dt_timezone.utc)
        self.assertEqual(_bar_millis(dt), int(dt.timestamp() * 1000))

    def test_a_naive_datetime_is_read_as_utc(self):
        from bot_program.engine.ibkr_client import _bar_millis
        self.assertEqual(
            _bar_millis(datetime(2026, 8, 24, 13, 30)),
            int(datetime(2026, 8, 24, 13, 30,
                         tzinfo=dt_timezone.utc).timestamp() * 1000))

    def test_a_daily_bar_is_no_longer_stamped_zero(self):
        """The whole series used to arrive at epoch 0 and be dropped by
        every consumer that filters on a sane timestamp."""
        from bot_program.engine.ibkr_client import _bar_millis
        self.assertGreater(_bar_millis(date(2026, 8, 24)), 0)


# ── the bracket: a partial fill pulls the parent back too ────────────
class _FakeOrder:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class APartialFillRetractsTheParentTests(SimpleTestCase):
    def _trader(self, filled):
        from bot_program.engine.ibkr_client import IBKRTrader
        t = IBKRTrader.__new__(IBKRTrader)
        t.host, t.port, t.client_id = "127.0.0.1", 7497, 1
        t.account_id = "DU111"
        t._connected = True
        t._ib = MagicMock()
        t._ib.isConnected.return_value = True
        t._ib.managedAccounts.return_value = ["DU111"]
        t._ib.reqContractDetails.return_value = [SimpleNamespace(minTick=0.01)]
        t._ib.client = SimpleNamespace(getReqId=lambda: 1)

        def _bracket(action, qty, limitPrice=None, takeProfitPrice=None,
                     stopLossPrice=None):
            return [_FakeOrder(action=action, totalQuantity=qty,
                               orderType="MKT", transmit=True, orderId=1),
                    _FakeOrder(action="SELL", totalQuantity=qty,
                               lmtPrice=takeProfitPrice, orderType="LMT",
                               transmit=True, orderId=2),
                    _FakeOrder(action="SELL", totalQuantity=qty,
                               auxPrice=stopLossPrice, orderType="STP",
                               transmit=True, orderId=3)]

        t._ib.bracketOrder.side_effect = _bracket
        self.placed = []

        def _place(contract, order):
            self.placed.append(order)
            order.orderId = getattr(order, "orderId", 0) or len(self.placed)
            first = len(self.placed) == 1
            return SimpleNamespace(
                order=order,
                orderStatus=SimpleNamespace(
                    status="Submitted",
                    filled=(filled if first else 0),
                    avgFillPrice=(100.0 if first else 0.0)),
                log=[])

        t._ib.placeOrder.side_effect = _place
        self.cancelled = []
        t._ib.cancelOrder.side_effect = lambda o: self.cancelled.append(o)
        return t

    def _buy(self, t):
        from bot_program.engine import ibkr_client
        with patch.object(ibkr_client, "_ib", MagicMock()), \
                patch.object(t, "_connect", return_value=True), \
                patch.object(t, "_build_contract", return_value=MagicMock()):
            return t.market_order("AAPL", "BUY", 100,
                                  stop_loss=95.0, take_profit=110.0)

    def test_a_partial_fill_cancels_the_parents_remainder(self):
        """30 of 100 printed. The other 70 must not keep working after
        we have reported and stopped watching."""
        t = self._trader(filled=30)
        out = self._buy(t)
        self.assertEqual(float(out["executedQty"]), 30.0)
        self.assertNotIn("protectedOnFill", out)
        ids = {getattr(o, "orderId", None) for o in self.cancelled}
        self.assertIn(1, ids, "the parent's remainder was left working")
        self.assertIn(2, ids)
        self.assertIn(3, ids)

    def test_a_complete_fill_keeps_its_bracket(self):
        t = self._trader(filled=100)
        out = self._buy(t)
        self.assertTrue(out.get("protectedOnFill"))
        self.assertEqual(self.cancelled, [])


# ── the entry: a cancel that filled something is not a refusal ───────
class APartlyFilledEntryStillBooksARowTests(SimpleTestCase):
    """IBKR answers CANCELLED with a real fill quantity by design:
    `_dead_order_reason` returns None once anything has filled."""

    def test_the_refusal_list_now_requires_nothing_filled(self):
        import re
        from pathlib import Path

        from django.conf import settings
        src = (Path(settings.BASE_DIR) / "bot_program" / "asset_engine"
               / "base.py").read_text(encoding="utf-8")
        entry = src.split("Detect broker-side refusals")[1][:1800]
        self.assertIn("refused_qty", entry)
        self.assertTrue(
            re.search(r'"EXPIRED"\)\s*\\\s*\n\s*and refused_qty <= 0', entry),
            "the entry refusal must be conditional on nothing having filled")

    def test_the_close_path_still_agrees_with_it(self):
        """Both directions must read the same rule; they disagreed."""
        from bot_program.asset_engine.base import AssetBot
        self.assertIn("CANCELLED", AssetBot.CLOSE_REFUSED_STATUSES)


# ── the retry branch records an unconfirmed leg ──────────────────────
class AnUnconfirmedLegIsAlwaysRecordedTests(TestCase):
    def _bot(self):
        from bot_program.asset_engine.base import AssetBot
        from bot_program.models import AssetBotConfig
        user = User.objects.create_user("edge_u", password="x")
        cfg = AssetBotConfig.objects.create(
            user=user, asset_class="stock", name="EDGE", mode="live",
            symbols=["AAPL"], capital=Decimal("10000"), enabled=True)
        bot = AssetBot.__new__(AssetBot)
        bot.cfg, bot.user, bot.asset_class = cfg, user, "stock"
        return bot, cfg

    def test_both_branches_flag_a_leg_they_could_not_cancel(self):
        """The success branch always did; the retry branch threw the
        answer away, so a resting stop left no trace once the retry
        worked and the row went CLOSED."""
        from pathlib import Path

        from django.conf import settings
        src = (Path(settings.BASE_DIR) / "bot_program" / "asset_engine"
               / "base.py").read_text(encoding="utf-8")
        block = src.split("cancelling\n")[1] if "cancelling\n" in src else src
        self.assertEqual(
            src.count('meta["protective_legs_unconfirmed"] = True'), 2,
            "both close branches must record an unconfirmed protective leg")
        self.assertEqual(
            src.count("if not self._cancel_protective_orders(trade, client):"),
            2, "both branches must READ the cancellation answer")


# ── the gate says when it could not read the book ────────────────────
class ABlindGateSaysSoTests(TestCase):
    def _bot(self):
        from bot_program.asset_engine.base import AssetBot
        from bot_program.models import AssetBotConfig
        user = User.objects.create_user("blind_u", password="x")
        cfg = AssetBotConfig.objects.create(
            user=user, asset_class="stock", name="BLIND", mode="live",
            symbols=["AAPL"], capital=Decimal("10000"), enabled=True,
            max_concurrent_positions=5)
        bot = AssetBot.__new__(AssetBot)
        bot.cfg, bot.user, bot.asset_class = cfg, user, "stock"
        return bot

    def test_a_failed_open_preflight_is_named_in_the_gate_reason(self):
        """preflight fails open ON PURPOSE — halting a fleet on a
        database hiccup is worse. But `ok` True then means two opposite
        things, and the heartbeat was painting the reassuring one."""
        bot = self._bot()
        with patch("portfolio.risk_gate.preflight",
                   return_value={"ok": True, "failed_open": True,
                                 "reason": "book unreadable: db timeout",
                                 "checks": {}}):
            ok, reason = bot.can_open_new()
        self.assertTrue(ok, "the gate must still fail OPEN")
        self.assertIn("UNCHECKED", reason)
        self.assertIn("db timeout", reason)

    def test_a_healthy_preflight_still_reads_plainly(self):
        bot = self._bot()
        with patch("portfolio.risk_gate.preflight",
                   return_value={"ok": True, "failed_open": False,
                                 "reason": "", "checks": {}}):
            ok, reason = bot.can_open_new()
        self.assertTrue(ok)
        self.assertNotIn("UNCHECKED", reason)

    def test_a_real_breach_still_refuses(self):
        bot = self._bot()
        with patch("portfolio.risk_gate.preflight",
                   return_value={"ok": False, "failed_open": False,
                                 "reason": "daily loss limit hit",
                                 "checks": {}}):
            ok, reason = bot.can_open_new()
        self.assertFalse(ok)
        self.assertIn("daily loss", reason)


class TheTallStateFillsTheWorkingAreaTests(SimpleTestCase):
    """The state between normal and fullscreen.

    The first version grew the container WHERE IT STOOD, and the chart
    card sits partway down a scrolling page — so the "free" height it
    computed was about six pixels more than the height it already had.
    The button worked perfectly and nothing appeared to happen.

    Filling the working area means leaving the flow and pinning to the
    rectangle the fixed furniture leaves behind.
    """

    def _src(self):
        from pathlib import Path

        from django.conf import settings
        return (Path(settings.BASE_DIR) / "templates" / "_partials"
                / "chart_widget.html").read_text(encoding="utf-8")

    def test_it_pins_rather_than_growing_in_place(self):
        src = self._src()
        self.assertIn("container.style.position = 'fixed'", src)
        self.assertNotIn("function tallHeight()", src)

    def test_it_measures_every_piece_of_furniture(self):
        """Headbands collapse, the rail opens, the sidebar minifies —
        a hardcoded offset would put the chart under whichever moved."""
        seg = self._src().split("function tallBox")[1][:1200]
        for sel in (".topbar", ".ticker-bar", ".data-headband",
                    ".info-panel-wrap", ".sidebar", ".signals-rail"):
            self.assertIn(sel, seg, sel)

    def test_a_hidden_headband_takes_no_space(self):
        """A collapsed strip must not reserve a gap the chart cannot use.

        `display`/`visibility` are the easy half and NEITHER headband uses
        them: `.data-headband.collapsed` and `.ticker-bar.collapsed` both
        hide with `transform: translateX(110%); opacity: 0`, which leaves
        the box its full height and its original top. So this test used to
        assert a mechanism that could not fire on the two elements it was
        written about, and 48px of dead space survived under the topbar in
        exactly the case tallBox() measures for.
        """
        seg = self._src().split("function visibleRect")[1]
        end = seg.find("\n    function ")
        if end > 0:
            seg = seg[:end]
        self.assertIn("display === 'none'", seg)
        self.assertIn("visibility === 'hidden'", seg)
        # The half that actually applies to the real headbands.
        self.assertIn("parseFloat(cs.opacity) === 0", seg)
        self.assertIn("r.left >= window.innerWidth", seg)

    def test_the_pin_is_cleared_on_the_way_out(self):
        """A container left fixed after leaving the state would float
        over the page for the rest of the session."""
        src = self._src()
        self.assertIn("function clearPin()", src)
        seg = src.split("function clearPin")[1][:300]
        for prop in ("'position'", "'top'", "'right'", "'bottom'", "'left'"):
            self.assertIn(prop, seg)

    def test_fullscreen_clears_the_pin_too(self):
        """Both states set a height; only one may own the container."""
        # The whole function body, not a byte count — this assertion
        # broke when the portal was added above it, purely because the
        # slice was too short. A window is not a scope.
        src = self._src()
        seg = src.split("function layout()")[1]
        end = seg.find("\n    function ")
        if end > 0:
            seg = seg[:end]
        self.assertIn("if (inFs) {", seg)
        self.assertIn("clearPin();", seg)

    def test_the_pinned_card_has_a_ground(self):
        """Out of the flow, the page shows through without one."""
        seg = self._src().split(".sv-candle-container.sv-chart-tall")[1][:1400]
        self.assertIn("background:", seg)

    def test_it_sits_below_the_veil_and_the_dialogs(self):
        """An expanded chart must never cover a locked screen or a
        confirmation the operator has to answer."""
        seg = self._src().split(".sv-candle-container.sv-chart-tall")[1][:1400]
        self.assertIn("--z-hovercard", seg)
        self.assertNotIn("--z-dialog", seg)
