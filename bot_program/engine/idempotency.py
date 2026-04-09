"""Deterministic clientOrderId generation.

Binance accepts a client-provided order id (max 36 chars). Using a
deterministic hash means a retry of the *same logical order* uses the
*same id*, so Binance rejects the duplicate instead of opening two positions.
"""
import hashlib


def make_client_order_id(config_id: int, symbol: str, signal_id: str = "",
                         intent: str = "ENTRY", bar_ts: str = "") -> str:
    """Build a deterministic, Binance-safe clientOrderId.

    Format:  sv-{first 28 chars of sha256 of inputs}
    Binance allows [A-Za-z0-9_-:.] up to 36 chars; sha256 hex is safe.
    """
    raw = f"{config_id}|{symbol}|{intent}|{signal_id}|{bar_ts}"
    digest = hashlib.sha256(raw.encode()).hexdigest()[:28]
    return f"sv-{digest}"


def split_intent(intent: str):
    """Validate intent strings."""
    return intent if intent in ("ENTRY", "EXIT", "SL", "TP", "TRAIL", "RECONCILE") else "ENTRY"
