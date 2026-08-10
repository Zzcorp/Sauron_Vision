"""Thin Binance REST/WebSocket wrapper. Uses `python-binance` if installed,
otherwise falls back to a minimal REST client."""
from __future__ import annotations
import time, hmac, hashlib, urllib.parse, logging
import requests

log = logging.getLogger(__name__)

SPOT_LIVE    = "https://api.binance.com"
SPOT_TESTNET = "https://testnet.binance.vision"

class BinanceClient:
    def __init__(self, api_key: str | None, api_secret: str | None, testnet: bool = True):
        self.api_key = api_key or ""
        self.api_secret = (api_secret or "").encode()
        self.base = SPOT_TESTNET if testnet else SPOT_LIVE

    # ── Public ─────────────────────────────────────────────
    def ping(self) -> bool:
        try:
            r = requests.get(f"{self.base}/api/v3/ping", timeout=8)
            return r.status_code == 200
        except Exception as e:
            log.warning("binance ping failed: %s", e); return False

    def ticker(self, symbol: str) -> dict:
        r = requests.get(f"{self.base}/api/v3/ticker/24hr", params={"symbol": symbol}, timeout=8)
        r.raise_for_status(); return r.json()

    def klines(self, symbol: str, interval: str = "15m", limit: int = 200,
               start_time: int | None = None, end_time: int | None = None) -> list[list]:
        """Public endpoint — no key required.

        start_time/end_time are epoch MILLISECONDS. Without them the API
        returns only the most recent `limit` bars, which caps history at
        1000 and makes a 200-period moving average unreachable on any
        timeframe longer than an hour. Backfill paginates with start_time.
        """
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        if start_time is not None:
            params["startTime"] = int(start_time)
        if end_time is not None:
            params["endTime"] = int(end_time)
        r = requests.get(f"{self.base}/api/v3/klines", params=params, timeout=15)
        r.raise_for_status(); return r.json()

    def order_book(self, symbol: str, limit: int = 100) -> dict:
        r = requests.get(f"{self.base}/api/v3/depth",
                         params={"symbol": symbol, "limit": limit}, timeout=8)
        r.raise_for_status(); return r.json()

    # ── Signed ─────────────────────────────────────────────
    def _sign(self, params: dict) -> dict:
        params["timestamp"] = int(time.time() * 1000)
        q = urllib.parse.urlencode(params)
        sig = hmac.new(self.api_secret, q.encode(), hashlib.sha256).hexdigest()
        params["signature"] = sig
        return params

    def _headers(self): return {"X-MBX-APIKEY": self.api_key}

    def account(self) -> dict:
        r = requests.get(f"{self.base}/api/v3/account",
                         params=self._sign({}), headers=self._headers(), timeout=10)
        r.raise_for_status(); return r.json()

    def balance_usdt(self) -> float:
        try:
            acct = self.account()
            for b in acct.get("balances", []):
                if b["asset"] == "USDT":
                    return float(b["free"]) + float(b["locked"])
        except Exception as e:
            log.warning("balance fetch failed: %s", e)
        return 0.0

    def market_order(self, symbol: str, side: str, quantity: float, **kwargs) -> dict:
        """side: BUY/SELL. Quantity in base asset.

        kwargs: `client_order_id` (Phase-33 idempotency) is passed through to
        Binance as `newClientOrderId`. Other kwargs ignored.
        """
        body = {
            "symbol": symbol, "side": side, "type": "MARKET",
            "quantity": f"{quantity:.8f}".rstrip("0").rstrip("."),
        }
        coid = kwargs.get("client_order_id")
        if coid:
            body["newClientOrderId"] = coid[:36]  # Binance cap
        params = self._sign(body)
        r = requests.post(f"{self.base}/api/v3/order",
                          params=params, headers=self._headers(), timeout=10)
        try: r.raise_for_status()
        except Exception: log.error("order failed: %s", r.text); raise
        return r.json()
