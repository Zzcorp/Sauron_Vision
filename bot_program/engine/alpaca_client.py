"""Alpaca v2 trading client — Phase-4 stock execution.

Conforms to the same duck-typed interface as `BinanceClient` / `OANDATrader` /
`PaperTrader`: ping, ticker, klines, order_book, market_order, account,
balance_usdt.

Endpoint roots:
  paper https://paper-api.alpaca.markets
  live  https://api.alpaca.markets

Market data is on a separate host: https://data.alpaca.markets

Symbols map 1:1 to Alpaca tickers (e.g. "AAPL", "SPY"). `klines()` returns
Binance-style 11-element rows for parity with the runner's `_parse_klines`.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

import requests

log = logging.getLogger(__name__)


TRADING_PAPER = "https://paper-api.alpaca.markets"
TRADING_LIVE = "https://api.alpaca.markets"
DATA_API = "https://data.alpaca.markets"

# Alpaca bar timeframe codes.
TIMEFRAME_MAP = {
    "1m": "1Min", "5m": "5Min", "15m": "15Min", "30m": "30Min",
    "1h": "1Hour", "4h": "4Hour", "1d": "1Day", "1w": "1Week",
}


def _to_iso_ms(ts_str: str) -> int:
    """Alpaca bar timestamps are RFC3339 like '2026-04-30T14:30:00Z'."""
    try:
        s = ts_str.rstrip("Z")
        return int(datetime.fromisoformat(s).replace(tzinfo=timezone.utc).timestamp() * 1000)
    except ValueError:
        return 0


class AlpacaTrader:
    """Alpaca v2 REST trading client."""

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        env: str = "paper",
        timeout: float = 10.0,
    ):
        self.api_key = api_key
        self.api_secret = api_secret
        self.env = env.lower()
        self.trading_base = TRADING_PAPER if self.env != "live" else TRADING_LIVE
        self.data_base = DATA_API
        self.timeout = timeout
        self._session: Optional[requests.Session] = None

    def _sess(self) -> requests.Session:
        if self._session is None:
            s = requests.Session()
            s.headers.update({
                "APCA-API-KEY-ID": self.api_key,
                "APCA-API-SECRET-KEY": self.api_secret,
                "Content-Type": "application/json",
            })
            self._session = s
        return self._session

    # ── public ─────────────────────────────────────────────────────────────

    def ping(self) -> bool:
        try:
            r = self._sess().get(f"{self.trading_base}/v2/account", timeout=self.timeout)
            return r.status_code == 200
        except Exception as e:
            log.warning("Alpaca ping failed: %s", e)
            return False

    def ticker(self, symbol: str) -> dict:
        r = self._sess().get(
            f"{self.data_base}/v2/stocks/{symbol}/quotes/latest",
            timeout=self.timeout,
        )
        r.raise_for_status()
        q = r.json().get("quote") or {}
        bid = float(q.get("bp", 0))
        ask = float(q.get("ap", 0))
        last = (bid + ask) / 2 if bid and ask else (bid or ask)
        return {"lastPrice": str(last), "symbol": symbol,
                "bid": str(bid), "ask": str(ask)}

    def klines(self, symbol: str, interval: str = "15m", limit: int = 200) -> list[list]:
        tf = TIMEFRAME_MAP.get(interval, "15Min")
        r = self._sess().get(
            f"{self.data_base}/v2/stocks/{symbol}/bars",
            params={"timeframe": tf, "limit": min(limit, 10_000)},
            timeout=self.timeout,
        )
        r.raise_for_status()
        bars = r.json().get("bars") or []
        rows = []
        for b in bars:
            ts = _to_iso_ms(b.get("t", ""))
            rows.append([
                ts,
                str(b.get("o", "0")),
                str(b.get("h", "0")),
                str(b.get("l", "0")),
                str(b.get("c", "0")),
                str(b.get("v", 0)),
                ts + 60_000,
                "0", 0, "0", "0", "0",
            ])
        return rows

    def order_book(self, symbol: str, limit: int = 50) -> dict:
        """Synthesise a thin book from latest quote — Alpaca's L2 endpoint
        requires a separate market-data subscription."""
        tk = self.ticker(symbol)
        bid = float(tk.get("bid", "0") or 0)
        ask = float(tk.get("ask", "0") or 0)
        if not (bid and ask):
            return {"bids": [], "asks": []}
        return {
            "bids": [[str(round(bid * (1 - i * 0.0001), 4)), "100"] for i in range(min(limit, 20))],
            "asks": [[str(round(ask * (1 + i * 0.0001), 4)), "100"] for i in range(min(limit, 20))],
        }

    # ── signed ─────────────────────────────────────────────────────────────

    def account(self) -> dict:
        r = self._sess().get(f"{self.trading_base}/v2/account", timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def balance_usdt(self) -> float:
        """Returns account cash in USD (Alpaca's base currency)."""
        try:
            return float(self.account().get("cash", 0))
        except Exception as e:
            log.warning("Alpaca balance fetch failed: %s", e)
            return 0.0

    def market_order(self, symbol: str, side: str, quantity: float, **kwargs) -> dict:
        body = {
            "symbol": symbol,
            "qty": str(quantity),
            "side": side.lower(),  # alpaca uses lowercase
            "type": "market",
            "time_in_force": "day",
        }
        # Phase-33 idempotency — Alpaca dedups via client_order_id (max 48 chars).
        coid = kwargs.get("client_order_id")
        if coid:
            body["client_order_id"] = coid[:48]
        r = self._sess().post(
            f"{self.trading_base}/v2/orders", json=body, timeout=self.timeout,
        )
        try:
            r.raise_for_status()
        except Exception:
            log.error("Alpaca order failed: %s", r.text)
            raise
        data = r.json()
        return {
            "orderId": str(data.get("id", "")),
            "symbol": symbol,
            "side": side,
            "executedQty": str(data.get("filled_qty", quantity) or quantity),
            "avgPrice": str(data.get("filled_avg_price", "0") or "0"),
            "status": data.get("status", "PENDING").upper(),
            "raw": data,
        }
