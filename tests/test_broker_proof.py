"""Proof, precedence, and a name on every forced exit.

Three defects the adversarial sweep found, each of a kind that only
shows up when something else has already gone wrong:

1. `_leg_is_resting` ended `return bool(status)`, so PendingSubmit —
   which ib_insync assigns LOCALLY the instant placeOrder is called,
   before TWS has said anything — counted as an accepted protective
   leg. `protectedOnFill` then turns OFF bot-side SL/TP management over
   a position whose stop may never have existed at the broker.

2. `save_crypto_quotes_to_db` wrote LiveQuote directly, skipping the
   source-precedence guard and the zero-price refusal. CoinGecko is
   priority 40; the Binance stream is 100. A five-minute poll could
   overwrite a real-time tick with a delayed one — which matters a great
   deal more now that the streamers are the recommended feed.

3. The kill switch sent its flatten with no client_order_id. It is the
   worst place on the platform for an anonymous order: it fires when
   something is already wrong, and two overlapping flattens mean two
   full-size market orders — the second of which is a reversal.

Run with:  python manage.py test tests.test_broker_proof
"""
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import TestCase


# ── 1. a leg is resting only when TWS says so ────────────────────────
class OnlyTWSCanProveALegTests(TestCase):
    def _leg(self, status, errors=()):
        return SimpleNamespace(
            orderStatus=SimpleNamespace(status=status),
            log=[SimpleNamespace(errorCode=e) for e in errors])

    def _resting(self, leg):
        from bot_program.engine.ibkr_client import IBKRTrader
        return IBKRTrader._leg_is_resting(leg)

    def test_pending_submit_is_not_proof(self):
        """ib_insync sets this locally at placeOrder — TWS has not
        spoken. A leg still here a second later was accepted by nobody."""
        self.assertFalse(self._resting(self._leg("PendingSubmit")))

    def test_presubmitted_is_proof(self):
        self.assertTrue(self._resting(self._leg("PreSubmitted")))

    def test_submitted_is_proof(self):
        self.assertTrue(self._resting(self._leg("Submitted")))

    def test_a_refused_leg_is_still_refused(self):
        for bad in ("Cancelled", "ApiCancelled", "Inactive"):
            self.assertFalse(self._resting(self._leg(bad)), bad)

    def test_an_error_line_still_refutes_a_good_status(self):
        self.assertFalse(self._resting(self._leg("Submitted", errors=(110,))))

    def test_an_empty_status_is_not_proof(self):
        self.assertFalse(self._resting(self._leg("")))


# ── 2. CoinGecko goes through the one writer ─────────────────────────
class TheCrpytoPollCannotClobberAStreamTests(TestCase):
    def setUp(self):
        from instruments.models import Instrument
        self.inst = Instrument.objects.create(
            symbol="BTCUSDT", name="Bitcoin", asset_class="crypto",
            is_active=True)

    def _poll(self, price, change=1.0, volume=10):
        from unittest.mock import patch as p
        from market_data.adapters import crypto_adapter
        with p.object(crypto_adapter, "fetch_coingecko_prices",
                      return_value={"BTCUSDT": {"price": price,
                                                "change_24h": change,
                                                "volume_24h": volume}}):
            return crypto_adapter.save_crypto_quotes_to_db()

    def test_a_delayed_poll_does_not_overwrite_a_live_stream_tick(self):
        """binance_ws is priority 100, coingecko 40. This is the whole
        reason the precedence table exists."""
        from market_data.models import LiveQuote
        from market_data.quotes import write_quote
        write_quote("BTCUSDT", last=Decimal("70000"), source="binance_ws")

        saved = self._poll(Decimal("61000"))

        row = LiveQuote.objects.get(instrument=self.inst)
        self.assertEqual(row.source, "binance_ws")
        self.assertEqual(Decimal(str(row.last)), Decimal("70000"))
        self.assertEqual(saved, 0, "a refused write must not be counted")

    def test_a_zero_price_is_refused(self):
        """Adapters default missing fields to 0; a 0 in LiveQuote reads
        downstream as a real price of zero."""
        from market_data.models import LiveQuote
        self.assertEqual(self._poll(Decimal("0")), 0)
        self.assertFalse(LiveQuote.objects.filter(instrument=self.inst).exists())

    def test_a_normal_poll_still_writes(self):
        from market_data.models import LiveQuote
        self.assertEqual(self._poll(Decimal("61000")), 1)
        row = LiveQuote.objects.get(instrument=self.inst)
        self.assertEqual(row.source, "coingecko")
        self.assertEqual(Decimal(str(row.last)), Decimal("61000"))

    def test_an_unknown_symbol_is_dropped_not_crashed(self):
        from market_data.adapters import crypto_adapter
        with patch.object(crypto_adapter, "fetch_coingecko_prices",
                          return_value={"NOPE": {"price": Decimal("1"),
                                                 "change_24h": 0,
                                                 "volume_24h": 0}}):
            self.assertEqual(crypto_adapter.save_crypto_quotes_to_db(), 0)


# ── 3. the flatten carries a name ────────────────────────────────────
class AForcedFlattenIsNotAnonymousTests(TestCase):
    def test_the_flatten_passes_a_client_order_id(self):
        from bot_program.engine.kill_switch import _try_broker_close
        client = MagicMock()
        client.market_order.return_value = {"executedQty": "1"}
        _try_broker_close(client, "BTCUSDT", "BUY", 1,
                          client_order_id="sv-abc123")
        self.assertEqual(client.market_order.call_args.kwargs
                         .get("client_order_id"), "sv-abc123")

    def test_an_absent_id_is_simply_omitted(self):
        """A client without the kwarg must not start raising TypeError
        in the middle of a kill switch."""
        from bot_program.engine.kill_switch import _try_broker_close
        client = MagicMock()
        client.market_order.return_value = {"executedQty": "1"}
        _try_broker_close(client, "BTCUSDT", "BUY", 1)
        self.assertNotIn("client_order_id", client.market_order.call_args.kwargs)

    def test_the_same_row_always_gets_the_same_id(self):
        """Determinism is the point: a repeated flatten must look like a
        duplicate to the broker, not like a second order."""
        from bot_program.engine.kill_switch import _kill_order_id
        row = SimpleNamespace(id=42, config_id=7, symbol="BTCUSDT")
        self.assertEqual(_kill_order_id(row), _kill_order_id(row))
        self.assertTrue(_kill_order_id(row).startswith("sv-"))

    def test_two_different_rows_get_different_ids(self):
        from bot_program.engine.kill_switch import _kill_order_id
        a = SimpleNamespace(id=42, config_id=7, symbol="BTCUSDT")
        b = SimpleNamespace(id=43, config_id=7, symbol="BTCUSDT")
        self.assertNotEqual(_kill_order_id(a), _kill_order_id(b))

    def test_a_broken_row_never_blocks_the_flatten(self):
        """The kill switch must fire even if naming fails."""
        from bot_program.engine.kill_switch import _kill_order_id
        self.assertEqual(_kill_order_id(object()), "")


class IBKROrdersCarryTheirRowsNameTests(TestCase):
    """IBKR has no server-enforced dedup key, so orderRef buys
    traceability — which is what makes a duplicate visible at all."""

    def test_the_order_ref_is_stamped_from_the_client_order_id(self):
        from bot_program.engine import ibkr_client
        from bot_program.engine.ibkr_client import IBKRTrader

        t = IBKRTrader.__new__(IBKRTrader)
        t.host, t.port, t.client_id = "127.0.0.1", 7497, 1
        t.account_id = "DU111"
        t._connected = True
        t._ib = MagicMock()
        t._ib.isConnected.return_value = True
        t._ib.managedAccounts.return_value = ["DU111"]
        t._ib.bracketOrder.side_effect = AttributeError("plain order")
        t._ib.reqContractDetails.return_value = [SimpleNamespace(minTick=0.01)]
        t._ib.client = SimpleNamespace(getReqId=lambda: 1)

        seen = []

        def _place(contract, order):
            seen.append(order)
            order.orderId = 5
            return SimpleNamespace(
                order=order,
                orderStatus=SimpleNamespace(status="Filled", filled=10,
                                            avgFillPrice=100.0),
                log=[])

        t._ib.placeOrder.side_effect = _place
        with patch.object(ibkr_client, "_ib", MagicMock()), \
                patch.object(t, "_connect", return_value=True), \
                patch.object(t, "_build_contract", return_value=MagicMock()):
            t.market_order("AAPL", "BUY", 10, client_order_id="sv-deadbeef")

        self.assertTrue(seen, "no order was placed")
        self.assertEqual(getattr(seen[0], "orderRef", None), "sv-deadbeef")
