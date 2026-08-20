"""Exits must be booked from the broker, not from the bot's own mark.

The entry path already reads its fill back off the broker. The exit path did
the opposite: `_submit_close_order` threw the response away and every close
path booked the ticker mark it had read BEFORE sending the order. Two things
were invisible as a result:

  * all exit slippage — and exits are where slippage lives, because stop-outs
    fire into fast one-sided markets. Every realized_r and every expectancy
    above it was the money the bot EXPECTED to move.
  * partial closes. `executedQty` was never read on a close, so a half-filled
    flatten was booked CLOSED while the residual stayed live at the broker —
    and `reconcile_asset` only scans OPEN/CLOSE_PENDING, so nothing was
    watching it, permanently.

Run with:  python manage.py test tests.test_exit_truth
"""
import pathlib
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.utils import timezone


def _user(name="exit_u"):
    return User.objects.create_user(username=name, password="x")


def _cfg(user, *, mode="live", name="EXIT", asset_class="stock"):
    from bot_program.models import AssetBotConfig
    return AssetBotConfig.objects.create(
        user=user, asset_class=asset_class, name=name, mode=mode,
        symbols=["AAPL"], capital=Decimal("10000"), enabled=True,
    )


def _trade(cfg, **kw):
    """A 10-share long at 100 with a 98 stop: one R is exactly $20."""
    from bot_program.models import AssetBotTrade
    defaults = dict(
        config=cfg, asset_class=cfg.asset_class, symbol="AAPL", side="BUY",
        qty=Decimal("10"), entry_price=Decimal("100"),
        stop_loss=Decimal("98"), take_profit=Decimal("104"),
        status="OPEN", paper=False,
        metadata={"initial_stop_loss": 98.0},
    )
    defaults.update(kw)
    return AssetBotTrade.objects.create(**defaults)


def _client(order=None, *, last="98"):
    c = MagicMock()
    c.market_order = MagicMock(return_value=order if order is not None
                               else {"orderId": "o1"})
    c.ticker = MagicMock(return_value={"lastPrice": last})
    c.get_positions = MagicMock(return_value=[{"symbol": "AAPL"}])
    return c


class _StubTrade:
    """Just enough of an AssetBotTrade for the pure resolver."""

    def __init__(self, qty="10", metadata=None, asset_class="stock"):
        self.id = 1
        self.qty = Decimal(qty)
        self.entry_price = Decimal("100")
        self.metadata = metadata or {}
        self.side = "BUY"
        self.asset_class = asset_class


# ── the resolver itself ─────────────────────────────────────────────────

class ExitFillResolverTests(SimpleTestCase):
    def test_broker_fill_price_beats_the_mark(self):
        from bot_program.pending_closes import resolve_exit_fill
        fill = resolve_exit_fill(
            _StubTrade(), {"avgPrice": "97.42", "executedQty": "10"},
            mark=Decimal("98"))
        self.assertEqual(fill["price"], Decimal("97.42"))
        self.assertEqual(fill["source"], "broker")
        self.assertTrue(fill["complete"])

    def test_a_response_without_a_fill_price_falls_back_and_says_so(self):
        """A degraded exit is allowed. Pretending it was measured is not."""
        from bot_program.pending_closes import resolve_exit_fill
        fill = resolve_exit_fill(_StubTrade(), {"orderId": "o1"},
                                 mark=Decimal("98"))
        self.assertEqual(fill["price"], Decimal("98"))
        self.assertEqual(fill["source"], "mark")
        self.assertTrue(fill["metadata"]["close_qty_assumed"])

    def test_a_non_dict_response_is_unmeasured_not_a_crash(self):
        from bot_program.pending_closes import resolve_exit_fill
        for result in (None, object(), "FILLED"):
            fill = resolve_exit_fill(_StubTrade(), result, mark=Decimal("98"))
            self.assertEqual(fill["source"], "mark")
            self.assertTrue(fill["complete"])

    def test_binance_spot_average_is_derived_from_the_quote_total(self):
        """Binance reports no avgPrice; without this branch every live crypto
        exit would be mark-booked forever."""
        from bot_program.pending_closes import resolve_exit_fill
        fill = resolve_exit_fill(
            _StubTrade(),
            {"executedQty": "10", "cummulativeQuoteQty": "994.2"},
            mark=Decimal("100"))
        self.assertEqual(fill["price"], Decimal("99.42"))
        self.assertEqual(fill["source"], "broker")

    def test_a_partial_fill_is_not_complete_and_records_the_residual(self):
        from bot_program.pending_closes import resolve_exit_fill
        fill = resolve_exit_fill(
            _StubTrade(), {"avgPrice": "99", "executedQty": "6"},
            mark=Decimal("98"))
        self.assertFalse(fill["complete"])
        self.assertEqual(fill["residual_qty"], Decimal("4"))
        self.assertEqual(fill["metadata"]["close_residual_qty"], "4")

    def test_an_accepted_but_unfilled_order_leaves_the_whole_position(self):
        """executedQty "0" is an answer, not silence: nothing filled, so the
        entire position is still live."""
        from bot_program.pending_closes import resolve_exit_fill
        fill = resolve_exit_fill(
            _StubTrade(), {"avgPrice": "0", "executedQty": "0",
                           "status": "ACCEPTED"}, mark=Decimal("98"))
        self.assertFalse(fill["complete"])
        self.assertEqual(fill["residual_qty"], Decimal("10"))

    def test_an_order_still_working_is_recorded_not_written_off(self):
        """Alpaca's fill poll gives up after 5 x 0.6s and answers `accepted`
        with filled_qty 0 — an order that is alive and will likely print
        seconds later. Nothing has filled YET, so the position stays live;
        what the flag adds is the retry loop's next move, which is to CANCEL
        that order rather than send a second close alongside it."""
        from bot_program.pending_closes import resolve_exit_fill
        fill = resolve_exit_fill(
            _StubTrade(), {"orderId": "o7", "avgPrice": "0",
                           "executedQty": "0", "status": "ACCEPTED"},
            mark=Decimal("98"))
        self.assertFalse(fill["complete"])
        self.assertEqual(fill["residual_qty"], Decimal("10"))
        self.assertTrue(fill["metadata"]["close_order_working"])
        self.assertEqual(fill["metadata"]["close_working_order_id"], "o7")

    def test_a_finished_order_that_filled_nothing_is_not_working(self):
        """REJECTED is terminal: there is no resting order to cancel, and the
        retry has to be free to send a fresh one."""
        from bot_program.pending_closes import resolve_exit_fill
        fill = resolve_exit_fill(
            _StubTrade(), {"orderId": "o8", "executedQty": "0",
                           "status": "REJECTED"}, mark=Decimal("98"))
        self.assertFalse(fill["complete"])
        self.assertFalse(fill["metadata"]["close_order_working"])

    def test_a_response_with_no_status_is_not_read_as_a_working_order(self):
        """Silence is not evidence of a resting order — treating it as one
        would stop the retry loop resubmitting for every terse client."""
        from bot_program.pending_closes import resolve_exit_fill
        fill = resolve_exit_fill(
            _StubTrade(), {"avgPrice": "99", "executedQty": "6"},
            mark=Decimal("98"))
        self.assertFalse(fill["metadata"]["close_order_working"])

    def test_the_working_flag_clears_once_the_order_finishes(self):
        """Metadata is MERGED into the row, so a True left behind by one
        attempt would block every later resubmit for the life of the trade."""
        from bot_program.pending_closes import resolve_exit_fill
        working = resolve_exit_fill(
            _StubTrade(), {"orderId": "o7", "executedQty": "0",
                           "status": "ACCEPTED"}, mark=Decimal("98"))
        after = resolve_exit_fill(
            _StubTrade(metadata=dict(working["metadata"])),
            {"avgPrice": "97", "executedQty": "10", "status": "FILLED"},
            mark=Decimal("98"))
        self.assertTrue(after["complete"])
        self.assertFalse(after["metadata"]["close_order_working"])
        self.assertEqual(after["metadata"]["close_working_order_id"], "")

    def test_slices_blend_into_a_quantity_weighted_price(self):
        from bot_program.pending_closes import resolve_exit_fill
        first = resolve_exit_fill(
            _StubTrade(), {"avgPrice": "99", "executedQty": "6"},
            mark=Decimal("98"))
        second = resolve_exit_fill(
            _StubTrade(metadata=dict(first["metadata"])),
            {"avgPrice": "98", "executedQty": "4"}, mark=Decimal("98"))
        # (6×99 + 4×98) / 10
        self.assertEqual(second["price"], Decimal("98.6"))
        self.assertTrue(second["complete"])
        self.assertEqual(second["source"], "broker")

    def test_one_assumed_slice_makes_the_blended_price_an_assumption(self):
        from bot_program.pending_closes import resolve_exit_fill
        first = resolve_exit_fill(
            _StubTrade(), {"avgPrice": "99", "executedQty": "6"},
            mark=Decimal("98"))
        second = resolve_exit_fill(
            _StubTrade(metadata=dict(first["metadata"])),
            {"orderId": "o2"}, mark=Decimal("97"))
        self.assertEqual(second["source"], "mark")

    def test_rounding_dust_is_not_a_partial(self):
        """A residual under the asset class's dust line is broker precision,
        not a position — stranding the row over it would fire a live market
        order every five minutes for a size no venue accepts."""
        from bot_program.pending_closes import resolve_exit_fill
        fill = resolve_exit_fill(
            _StubTrade(), {"avgPrice": "99", "executedQty": "9.9999999"},
            mark=Decimal("98"))
        self.assertTrue(fill["complete"])

    def test_a_tradeable_residual_on_a_large_size_is_never_dust(self):
        """The dust line is ABSOLUTE, not a share of the order. 0.1% of a
        120,000 DOGE close is 120 DOGE — above Binance's minQty and its
        MIN_NOTIONAL, a position someone could sell — and a proportional band
        would write it off as rounding."""
        from bot_program.pending_closes import resolve_exit_fill
        fill = resolve_exit_fill(
            _StubTrade(qty="120000", asset_class="crypto"),
            {"avgPrice": "0.12", "executedQty": "119880"},
            mark=Decimal("0.12"))
        self.assertFalse(fill["complete"])
        self.assertEqual(fill["residual_qty"], Decimal("120"))
        self.assertEqual(fill["metadata"]["close_residual_qty"], "120")

    def test_crypto_dust_below_the_printed_precision_still_closes(self):
        """Binance prints base quantity to 8dp: a residual in the last place
        cannot be ordered, so the row must not strand on it."""
        from bot_program.pending_closes import resolve_exit_fill
        fill = resolve_exit_fill(
            _StubTrade(qty="0.5", asset_class="crypto"),
            {"avgPrice": "60000", "executedQty": "0.499999999"},
            mark=Decimal("60000"))
        self.assertTrue(fill["complete"])

    def test_the_dust_line_is_per_asset_class(self):
        """Each number is its venue's own reporting precision, so the classes
        that count in whole units get a coarser line than the ones that count
        in eight decimal places."""
        from bot_program.pending_closes import dust_qty
        self.assertLess(dust_qty("crypto"), dust_qty("stock"))
        self.assertLess(dust_qty("stock"), dust_qty("forex"))
        self.assertEqual(dust_qty("options"), dust_qty("forex"))
        # An asset class with no venue wired yet gets the TIGHTEST line:
        # calling a live position dust hides it from every sweep permanently,
        # while calling dust a residual costs bounded retries and one alert.
        self.assertEqual(dust_qty("futures"), dust_qty("crypto"))

    def test_residual_qty_reads_back_what_was_filled(self):
        from bot_program.pending_closes import residual_qty
        self.assertEqual(residual_qty(_StubTrade()), Decimal("10"))
        self.assertEqual(
            residual_qty(_StubTrade(metadata={"close_filled_qty": "6"})),
            Decimal("4"))
        # A reported zero-fill is not "nothing left" — it is "nothing gone".
        self.assertEqual(
            residual_qty(_StubTrade(metadata={"close_filled_qty": "0"})),
            Decimal("10"))


# ── the bot's own close ─────────────────────────────────────────────────

class LiveExitBookingTests(TestCase):
    def setUp(self):
        self.user = _user()
        self.cfg = _cfg(self.user)

    def test_stop_out_is_booked_at_the_broker_fill_and_r_follows(self):
        """The point of the change: realized_r moves for live trades. A stop
        at 98 that fills at 97.50 is a 1.25R loss, not the 1.0R the bot
        planned — and the ledger has to say so."""
        from bot_program.asset_engine.stock_bot import StockBot

        trade = _trade(self.cfg)
        client = _client({"avgPrice": "97.50", "executedQty": "10",
                          "status": "FILLED"})
        ok = StockBot(self.cfg)._close_trade(trade, Decimal("98"), client,
                                             reason="SL")

        self.assertTrue(ok)
        trade.refresh_from_db()
        self.assertEqual(trade.exit_price, Decimal("97.50"))
        self.assertEqual(trade.pnl, Decimal("-25"))
        self.assertEqual(trade.realized_r, -1.25)
        self.assertEqual(trade.metadata["exit_fill_source"], "broker")

    def test_a_broker_that_reports_no_fill_price_degrades_honestly(self):
        from bot_program.asset_engine.stock_bot import StockBot

        trade = _trade(self.cfg)
        ok = StockBot(self.cfg)._close_trade(
            trade, Decimal("98"), _client({"orderId": "o1"}), reason="SL")

        self.assertTrue(ok)
        trade.refresh_from_db()
        self.assertEqual(trade.exit_price, Decimal("98"))
        self.assertEqual(trade.realized_r, -1.0)
        self.assertEqual(trade.metadata["exit_fill_source"], "mark")

    def test_paper_exits_are_unchanged_and_never_read_a_broker_fill(self):
        """PaperTrader has no real fill. paper_fill_price already models the
        adverse half-spread, so the paper venue must keep booking exactly what
        it booked before — only the LIVE path became honest."""
        from bot_program.asset_engine.risk_levels import paper_fill_price
        from bot_program.asset_engine.stock_bot import StockBot

        cfg = _cfg(self.user, mode="paper", name="PAPER")
        trade = _trade(cfg, paper=True)
        client = _client({"avgPrice": "1.23", "executedQty": "10"})

        ok = StockBot(cfg)._close_trade(trade, Decimal("104"), client,
                                        reason="TP")

        self.assertTrue(ok)
        client.market_order.assert_not_called()
        trade.refresh_from_db()
        expected = paper_fill_price(cfg, "AAPL", 104.0, "SELL")
        # 7 places, not exact: the column is DecimalField(_, 8) and both the
        # old and new code hand it the same float — the rounding is the DB's.
        self.assertAlmostEqual(float(trade.exit_price), expected, places=7)
        self.assertLess(expected, 104.0, "the exit must be charged adversely")
        self.assertEqual(trade.metadata["exit_fill_source"], "paper")


# ── partial closes ──────────────────────────────────────────────────────

class PartialCloseTests(TestCase):
    def setUp(self):
        self.user = _user("partial_u")
        self.cfg = _cfg(self.user, name="PARTIAL")

    def _partial_close(self):
        from bot_program.asset_engine.stock_bot import StockBot
        trade = _trade(self.cfg)
        ok = StockBot(self.cfg)._close_trade(
            trade, Decimal("98"),
            _client({"avgPrice": "97.90", "executedQty": "6"}), reason="SL")
        trade.refresh_from_db()
        return trade, ok

    def test_a_half_filled_close_is_never_marked_closed(self):
        trade, ok = self._partial_close()
        self.assertFalse(ok)
        self.assertEqual(trade.status, "CLOSE_PENDING")
        self.assertIsNone(trade.closed_at)
        self.assertIsNone(trade.exit_price)
        self.assertIsNone(trade.realized_r)

    def test_the_residual_is_recorded_on_the_row(self):
        trade, _ = self._partial_close()
        self.assertEqual(trade.metadata["close_filled_qty"], "6")
        self.assertEqual(trade.metadata["close_residual_qty"], "4")

    def test_the_row_stays_in_reach_of_the_retry_and_reconcile_sweeps(self):
        """Both only scan OPEN/CLOSE_PENDING. A CLOSED row with a live
        remainder behind it is watched by nothing, forever."""
        from bot_program.models import AssetBotTrade
        trade, _ = self._partial_close()
        self.assertTrue(AssetBotTrade.objects
                        .filter(pk=trade.pk, status="CLOSE_PENDING",
                                paper=False).exists())
        self.assertTrue(AssetBotTrade.objects
                        .filter(pk=trade.pk,
                                status__in=("OPEN", "CLOSE_PENDING")).exists())

    def test_the_operator_is_told(self):
        from alerts.models import Notification
        self._partial_close()
        self.assertTrue(Notification.objects.filter(
            user=self.user, title__startswith="◧ Partial close").exists())

    def test_the_bot_will_not_resubmit_the_full_size_over_a_residual(self):
        """Flattening trade.qty again would sell units the account no longer
        holds — that opens a position the other way instead of closing one."""
        from bot_program.asset_engine.stock_bot import StockBot

        trade = _trade(self.cfg, status="CLOSE_PENDING",
                       metadata={"initial_stop_loss": 98.0,
                                 "close_filled_qty": "6",
                                 "close_residual_qty": "4"})
        client = _client({"avgPrice": "98", "executedQty": "10"})
        ok = StockBot(self.cfg)._close_trade(trade, Decimal("98"), client,
                                             reason="SL")
        self.assertFalse(ok)
        client.market_order.assert_not_called()

    def test_a_dust_residual_still_closes(self):
        from bot_program.asset_engine.stock_bot import StockBot
        trade = _trade(self.cfg)
        ok = StockBot(self.cfg)._close_trade(
            trade, Decimal("98"),
            _client({"avgPrice": "99", "executedQty": "9.9999999"}),
            reason="SL")
        self.assertTrue(ok)
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSED")


# ── the retry loop ──────────────────────────────────────────────────────

class RetryExitBookingTests(TestCase):
    def setUp(self):
        self.user = _user("retry_u")
        self.cfg = _cfg(self.user, name="RETRY")

    def test_the_retry_submits_only_the_residual(self):
        from bot_program.pending_closes import retry_trade_close

        trade = _trade(self.cfg, status="CLOSE_PENDING",
                       metadata={"initial_stop_loss": 98.0,
                                 "close_filled_qty": "6",
                                 "close_fills": [{"qty": "6", "price": "99",
                                                  "source": "broker"}]})
        client = _client({"avgPrice": "98", "executedQty": "4"}, last="100")
        with patch("bot_program.engine.broker_router.client_for_symbol",
                   return_value=client):
            self.assertTrue(retry_trade_close(trade))

        self.assertEqual(float(client.market_order.call_args.args[2]), 4.0)
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSED")
        # (6×99 + 4×98) / 10 — both slices, not just the last one.
        self.assertEqual(trade.exit_price, Decimal("98.6"))
        self.assertEqual(trade.pnl, Decimal("-14"))

    def test_a_retry_that_only_part_fills_stays_pending(self):
        from bot_program.pending_closes import retry_trade_close

        trade = _trade(self.cfg, status="CLOSE_PENDING")
        client = _client({"avgPrice": "99", "executedQty": "3"}, last="100")
        with patch("bot_program.engine.broker_router.client_for_symbol",
                   return_value=client):
            self.assertFalse(retry_trade_close(trade))

        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSE_PENDING")
        self.assertEqual(trade.metadata["close_residual_qty"], "7")
        # A partial made progress but still leaves a live position, so it has
        # to be bounded by the same attempt ceiling a rejection is.
        self.assertEqual(trade.metadata["close_retry_attempts"], 1)

    def test_the_retry_books_the_broker_fill_not_the_ticker(self):
        from bot_program.pending_closes import retry_trade_close

        trade = _trade(self.cfg, status="CLOSE_PENDING")
        client = _client({"avgPrice": "97.25", "executedQty": "10"},
                         last="100")
        with patch("bot_program.engine.broker_router.client_for_symbol",
                   return_value=client):
            self.assertTrue(retry_trade_close(trade))

        trade.refresh_from_db()
        self.assertEqual(trade.exit_price, Decimal("97.25"))
        self.assertEqual(trade.metadata["exit_fill_source"], "broker")

    def test_an_already_flat_position_books_the_mark_and_flags_it(self):
        """No order is sent on this branch, so there is no fill to read. The
        mark is the only number available — and the row must say so."""
        from bot_program.pending_closes import retry_trade_close

        trade = _trade(self.cfg, status="CLOSE_PENDING")
        client = _client(last="97")
        client.get_positions = MagicMock(return_value=[])
        with patch("bot_program.engine.broker_router.client_for_symbol",
                   return_value=client):
            self.assertTrue(retry_trade_close(trade))

        client.market_order.assert_not_called()
        trade.refresh_from_db()
        self.assertEqual(trade.exit_price, Decimal("97"))
        self.assertEqual(trade.metadata["exit_fill_source"], "mark")

    def test_the_retry_cancels_a_working_close_before_sending_another(self):
        """Two live closes for one position is how a flatten becomes a naked
        reverse: the resting order prints while the replacement is in flight
        and the account ends up short what it just closed."""
        from bot_program.pending_closes import retry_trade_close

        trade = _trade(self.cfg, status="CLOSE_PENDING",
                       metadata={"initial_stop_loss": 98.0,
                                 "close_order_working": True,
                                 "close_working_order_id": "o7"})
        client = _client({"avgPrice": "97", "executedQty": "10",
                          "status": "FILLED"}, last="100")
        with patch("bot_program.engine.broker_router.client_for_symbol",
                   return_value=client):
            self.assertTrue(retry_trade_close(trade))

        client.cancel_order.assert_called_once_with("o7")
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSED")
        self.assertEqual(trade.exit_price, Decimal("97"))
        self.assertFalse(trade.metadata["close_order_working"])

    def test_the_retry_will_not_stack_a_close_it_could_not_cancel(self):
        """An order still resting at the broker that we failed to pull is the
        one state where sending another close is worse than waiting."""
        from bot_program.pending_closes import retry_trade_close

        trade = _trade(self.cfg, status="CLOSE_PENDING",
                       metadata={"initial_stop_loss": 98.0,
                                 "close_order_working": True,
                                 "close_working_order_id": "o7"})
        client = _client({"avgPrice": "97", "executedQty": "10"}, last="100")
        client.cancel_order = MagicMock(return_value=False)
        with patch("bot_program.engine.broker_router.client_for_symbol",
                   return_value=client):
            self.assertFalse(retry_trade_close(trade))

        client.market_order.assert_not_called()
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSE_PENDING")
        # Waiting is not free: the attempt counts, so a working order that
        # never resolves still reaches the operator alert and the ceiling.
        self.assertEqual(trade.metadata["close_retry_attempts"], 1)


# ── the kill switch ─────────────────────────────────────────────────────

class KillSwitchExitBookingTests(TestCase):
    def setUp(self):
        self.user = _user("kill_u")
        self.cfg = _cfg(self.user, name="KILL")

    def test_a_forced_flatten_books_the_broker_fill(self):
        from bot_program.engine.kill_switch import _close_asset_trade

        trade = _trade(self.cfg)
        client = _client({"avgPrice": "96.80", "executedQty": "10"})
        with patch("bot_program.engine.broker_router.client_for_symbol",
                   return_value=client):
            _close_asset_trade(trade, timezone.now())

        trade.refresh_from_db()
        self.assertEqual(trade.exit_price, Decimal("96.80"))
        self.assertEqual(trade.pnl, Decimal("-32"))
        self.assertEqual(trade.metadata["exit_fill_source"], "broker")

    def test_a_partly_filled_flatten_is_reported_not_booked(self):
        """The sweep's `errors` channel is where the operator reads 'these may
        still be open at the broker'. A partial belongs in it."""
        from bot_program.engine.kill_switch import execute_kill_switch

        trade = _trade(self.cfg)
        client = _client({"avgPrice": "96.80", "executedQty": "6"})
        with patch("bot_program.engine.broker_router.client_for_symbol",
                   return_value=client):
            res = execute_kill_switch(user=self.user, reason="test")

        self.assertEqual(res["asset_positions_closed"], 0)
        self.assertEqual(len(res["errors"]), 1)
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSE_PENDING")
        self.assertEqual(trade.metadata["close_residual_qty"], "4")
        self.assertIsNone(trade.exit_price)

    def test_a_close_pending_row_is_flattened_at_its_residual(self):
        from bot_program.engine.kill_switch import _close_asset_trade

        trade = _trade(self.cfg, status="CLOSE_PENDING",
                       metadata={"initial_stop_loss": 98.0,
                                 "close_filled_qty": "6",
                                 "close_fills": [{"qty": "6", "price": "99",
                                                  "source": "broker"}]})
        client = _client({"avgPrice": "98", "executedQty": "4"})
        with patch("bot_program.engine.broker_router.client_for_symbol",
                   return_value=client):
            _close_asset_trade(trade, timezone.now())

        self.assertEqual(float(client.market_order.call_args.args[2]), 4.0)
        trade.refresh_from_db()
        self.assertEqual(trade.exit_price, Decimal("98.6"))


# ── the live row handed a simulator ─────────────────────────────────────

class PaperFallbackProvenanceTests(TestCase):
    """`broker_router` returns PaperTrader whenever credentials are missing,
    so a LIVE row can be handed one. Its response is `status: FILLED` at a
    simulated price in exactly a broker's shape — booking it would stamp the
    exit `broker` in the one case that flag exists to catch, while the real
    position stays open at a broker nothing can reach."""

    def setUp(self):
        self.user = _user("paperfb_u")
        self.cfg = _cfg(self.user, name="FALLBACK")

    def _simulator(self):
        from bot_program.engine.paper_trader import PaperTrader
        return PaperTrader(self.cfg)

    def test_the_retry_loop_refuses_to_book_a_simulated_fill(self):
        from bot_program.pending_closes import retry_trade_close

        trade = _trade(self.cfg, status="CLOSE_PENDING")
        with patch("bot_program.engine.broker_router.client_for_symbol",
                   return_value=self._simulator()):
            self.assertFalse(retry_trade_close(trade))

        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSE_PENDING")
        self.assertIsNone(trade.exit_price)
        self.assertNotIn("exit_fill_source", trade.metadata)
        self.assertIn("PaperTrader", trade.metadata["close_retry_last_error"])

    def test_the_kill_switch_reports_the_symbol_instead_of_faking_a_close(self):
        """`errors` is where the operator reads 'these may still be OPEN at
        the broker' — a position nothing can reach belongs in it."""
        from bot_program.engine.kill_switch import execute_kill_switch

        trade = _trade(self.cfg)
        with patch("bot_program.engine.broker_router.client_for_symbol",
                   return_value=self._simulator()):
            res = execute_kill_switch(user=self.user, reason="test")

        self.assertEqual(res["asset_positions_closed"], 0)
        self.assertEqual(len(res["errors"]), 1)
        self.assertIn("PaperTrader", res["errors"][0])
        trade.refresh_from_db()
        self.assertEqual(trade.status, "OPEN")
        self.assertIsNone(trade.exit_price)

    def test_a_paper_row_is_still_flattened_by_the_kill_switch(self):
        """The guard is about LIVE rows only: a paper row has no broker-side
        position, books at its own mark, and must keep doing so."""
        from bot_program.engine.kill_switch import _close_asset_trade

        cfg = _cfg(self.user, mode="paper", name="FALLBACK_PAPER")
        trade = _trade(cfg, paper=True)
        client = _client(last="103")
        with patch("bot_program.engine.broker_router.client_for_symbol",
                   return_value=client):
            _close_asset_trade(trade, timezone.now())

        client.market_order.assert_not_called()
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSED")
        self.assertEqual(trade.exit_price, Decimal("103"))


# ── the options asset class ─────────────────────────────────────────────

def _opt_cfg(user, *, mode="live", name="OPT"):
    from bot_program.models import AssetBotConfig
    return AssetBotConfig.objects.create(
        user=user, asset_class="options", name=name, mode=mode,
        symbols=["AAPL"], capital=Decimal("10000"), enabled=True,
    )


def _opt_trade(cfg, **kw):
    """2 contracts of a $3.00 call with a $2.50 stop: one R is $100."""
    from bot_program.models import AssetBotTrade
    defaults = dict(
        config=cfg, asset_class="options", symbol="AAPL", side="BUY",
        qty=Decimal("2"), entry_price=Decimal("3.00"),
        stop_loss=Decimal("2.50"), take_profit=Decimal("4.00"),
        status="OPEN", paper=False,
        metadata={"initial_stop_loss": 2.5, "multiplier": 100,
                  "right": "C", "strike": 190.0, "expiry": "2027-01-15",
                  "occ_symbol": "AAPL270115C00190000"},
    )
    defaults.update(kw)
    return AssetBotTrade.objects.create(**defaults)


def _opt_client(order):
    c = MagicMock()
    c.market_order_option = MagicMock(return_value=order)
    return c


class OptionsExitBookingTests(TestCase):
    """Options override `_submit_close_order`, so they are the one asset
    class that can silently miss the exit-truth fix while every other class
    has it."""

    def setUp(self):
        self.user = _user("opt_u")
        self.cfg = _opt_cfg(self.user)

    def test_an_options_stop_out_is_booked_at_the_broker_premium(self):
        from bot_program.asset_engine.options_bot import OptionsBot

        trade = _opt_trade(self.cfg)
        client = _opt_client({"avgPrice": "2.40", "executedQty": "2",
                              "status": "FILLED"})
        ok = OptionsBot(self.cfg)._close_trade(trade, Decimal("2.50"), client,
                                               reason="SL")

        self.assertTrue(ok)
        trade.refresh_from_db()
        self.assertEqual(trade.exit_price, Decimal("2.40"))
        # (2.40 - 3.00) premium points x 2 contracts x 100 multiplier.
        self.assertEqual(trade.pnl, Decimal("-120"))
        self.assertEqual(trade.metadata["exit_fill_source"], "broker")

    def test_a_partly_filled_options_close_stays_close_pending(self):
        """One contract of two left live at the broker. Marking the row CLOSED
        would leave it watched by nothing: both sweeps scan only OPEN and
        CLOSE_PENDING."""
        from bot_program.asset_engine.options_bot import OptionsBot

        trade = _opt_trade(self.cfg)
        client = _opt_client({"avgPrice": "2.40", "executedQty": "1",
                              "status": "PARTIALLY_FILLED"})
        ok = OptionsBot(self.cfg)._close_trade(trade, Decimal("2.50"), client,
                                               reason="SL")

        self.assertFalse(ok)
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSE_PENDING")
        self.assertIsNone(trade.exit_price)
        self.assertEqual(trade.metadata["close_residual_qty"], "1")


# ── reconciliation's provenance ─────────────────────────────────────────

class OrphanProvenanceTests(TestCase):
    def setUp(self):
        self.user = _user("orphan_u")
        self.cfg = _cfg(self.user, name="ORPHAN")

    def test_an_inferred_orphan_close_drops_the_broker_stamp(self):
        """Two provenance flags on one closed row is worse than either alone:
        a reader who sees `broker` treats the price as measured, and this one
        is a ticker read taken now, for the whole size."""
        from bot_program.reconcile_asset import _close_as_orphan

        trade = _trade(self.cfg, status="CLOSE_PENDING",
                       metadata={"initial_stop_loss": 98.0,
                                 "exit_fill_source": "broker",
                                 "close_filled_qty": "6",
                                 "close_residual_qty": "4"})
        with patch("bot_program.engine.broker_router.client_for_symbol",
                   return_value=_client(last="97")):
            _close_as_orphan(trade)

        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSED")
        self.assertTrue(trade.metadata["exit_price_inferred"])
        self.assertEqual(trade.metadata["exit_fill_source"], "mark")


# ── contracts a future edit must not quietly drop ───────────────────────

class CloseContractTests(SimpleTestCase):
    def test_submit_close_order_hands_the_broker_response_back(self):
        """Discarding it is the original defect. Guard the return value."""
        from bot_program.asset_engine.stock_bot import StockBot

        trade = MagicMock()
        trade.side = "BUY"
        trade.symbol = "AAPL"
        trade.qty = Decimal("5")
        client = MagicMock()
        client.market_order = MagicMock(return_value={"avgPrice": "1"})

        out = StockBot(MagicMock())._submit_close_order(trade, client, "cid")
        self.assertEqual(out, {"avgPrice": "1"})

    def test_the_options_override_hands_the_broker_response_back_too(self):
        """It is the ONLY override of this hook, so dropping the response
        leaves exactly one asset class booking exits at the pre-order mark
        while every other class books the fill."""
        from bot_program.asset_engine.options_bot import OptionsBot

        trade = MagicMock()
        trade.side = "BUY"
        trade.symbol = "AAPL"
        trade.qty = Decimal("2")
        trade.metadata = {"strike": 190.0, "expiry": "2027-01-15", "right": "C"}
        client = MagicMock()
        client.market_order_option = MagicMock(
            return_value={"avgPrice": "3.20", "executedQty": "2"})

        out = OptionsBot(MagicMock())._submit_close_order(trade, client, "cid")
        self.assertEqual(out, {"avgPrice": "3.20", "executedQty": "2"})

    def test_every_close_path_books_through_the_shared_step(self):
        """Three paths, one exit-booking step. A path that re-derives the exit
        price locally would silently reintroduce mark-booked exits on one of
        them only, which is worse than having them all wrong."""
        import importlib

        for name in ("bot_program.asset_engine.base",
                     "bot_program.engine.kill_switch"):
            mod = importlib.import_module(name)
            src = pathlib.Path(mod.__file__).read_text(encoding="utf-8")
            self.assertIn(
                "resolve_exit_fill", src,
                f"{name} books an exit without the shared resolver")
