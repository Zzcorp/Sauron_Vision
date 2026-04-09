"""Test that the clientOrderId generator is deterministic."""
from django.test import SimpleTestCase


class IdempotencyTests(SimpleTestCase):
    def test_same_inputs_same_id(self):
        from bot_program.engine.idempotency import make_client_order_id
        a = make_client_order_id(1, "BTCUSDT", "sig123", "ENTRY", "2025-01-01T00:00")
        b = make_client_order_id(1, "BTCUSDT", "sig123", "ENTRY", "2025-01-01T00:00")
        self.assertEqual(a, b)

    def test_different_inputs_different_ids(self):
        from bot_program.engine.idempotency import make_client_order_id
        a = make_client_order_id(1, "BTCUSDT", "sig123", "ENTRY", "2025-01-01T00:00")
        b = make_client_order_id(1, "BTCUSDT", "sig999", "ENTRY", "2025-01-01T00:00")
        c = make_client_order_id(1, "ETHUSDT", "sig123", "ENTRY", "2025-01-01T00:00")
        d = make_client_order_id(2, "BTCUSDT", "sig123", "ENTRY", "2025-01-01T00:00")
        self.assertEqual(len({a, b, c, d}), 4)

    def test_id_length_safe_for_binance(self):
        from bot_program.engine.idempotency import make_client_order_id
        oid = make_client_order_id(1, "BTCUSDT", "sig123", "ENTRY", "2025-01-01T00:00")
        self.assertLessEqual(len(oid), 36)
        self.assertTrue(oid.startswith("sv-"))
