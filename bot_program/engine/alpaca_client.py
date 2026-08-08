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

    def get_positions(self) -> list[dict]:
        """Open positions via GET /v2/positions — Phase-33 reconciliation.

        Returns [{"symbol", "qty", "side"}, ...]. Raises on transport errors
        so reconcile counts the broker unavailable instead of assuming flat.
        """
        r = self._sess().get(f"{self.trading_base}/v2/positions",
                             timeout=self.timeout)
        r.raise_for_status()
        out = []
        for p in r.json() or []:
            out.append({
                "symbol": str(p.get("symbol", "")).upper(),
                "qty": float(p.get("qty", 0) or 0),
                "side": str(p.get("side", "")).upper(),
            })
        return out

    def market_order(self, symbol: str, side: str, quantity: float, **kwargs) -> dict:
        """Market order, optionally as a BRACKET with broker-side SL/TP.

        Passing stop_loss/take_profit submits a bracket order: Alpaca holds
        the protective legs itself, so the position stays protected even when
        this bot is not running. Bracket orders require GTC and whole shares.
        """
        stop_loss = kwargs.get("stop_loss")
        take_profit = kwargs.get("take_profit")
        bracket = bool(stop_loss and take_profit) and float(quantity) >= 1
        body = {
            "symbol": symbol,
            # Bracket legs are only valid on whole-share orders.
            "qty": str(int(quantity)) if bracket else str(quantity),
            "side": side.lower(),  # alpaca uses lowercase
            "type": "market",
            "time_in_force": "gtc" if bracket else "day",
        }
        if bracket:
            body["order_class"] = "bracket"
            body["stop_loss"] = {"stop_price": f"{float(stop_loss):.2f}"}
            body["take_profit"] = {"limit_price": f"{float(take_profit):.2f}"}
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
        # Market orders return 'accepted' with a null fill price; poll briefly
        # so the recorded entry is the REAL fill, not the pre-order ticker.
        if not data.get("filled_avg_price") and data.get("id"):
            data = self._await_fill(str(data["id"])) or data
        out = {
            "orderId": str(data.get("id", "")),
            "symbol": symbol,
            "side": side,
            "executedQty": str(data.get("filled_qty", quantity) or quantity),
            "avgPrice": str(data.get("filled_avg_price", "0") or "0"),
            "status": data.get("status", "PENDING").upper(),
            "raw": data,
        }
        if bracket:
            out["protectedOnFill"] = True
            out["protectiveOrders"] = [
                str(leg.get("id")) for leg in (data.get("legs") or [])
                if leg.get("id")
            ]
        return out

    def _await_fill(self, order_id: str, attempts: int = 5,
                    delay: float = 0.6) -> Optional[dict]:
        """Poll an order until it reports a fill price (or attempts run out).

        Returns the last order payload seen, or None on error. Bounded and
        best-effort: a still-unfilled order just falls back to the ticker.
        """
        import time
        last = None
        for _ in range(attempts):
            time.sleep(delay)
            try:
                r = self._sess().get(f"{self.trading_base}/v2/orders/{order_id}",
                                     timeout=self.timeout)
                r.raise_for_status()
                last = r.json()
            except Exception as e:
                log.warning("Alpaca fill poll failed for %s: %s", order_id, e)
                return last
            if last.get("filled_avg_price"):
                return last
            if str(last.get("status", "")).lower() in (
                    "canceled", "expired", "rejected"):
                return last
        return last

    def cancel_order(self, order_id: str) -> bool:
        """Cancel a resting order (e.g. a bracket leg). True when accepted."""
        r = self._sess().delete(f"{self.trading_base}/v2/orders/{order_id}",
                                timeout=self.timeout)
        if r.status_code in (200, 204):
            return True
        # 404/422 = already gone or not cancelable; treat as done, don't raise.
        if r.status_code in (404, 422):
            log.info("Alpaca cancel %s: already inactive (%s)", order_id,
                     r.status_code)
            return False
        r.raise_for_status()
        return False
