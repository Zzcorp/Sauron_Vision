"""Binance USDT-M futures REST client.

Mirrors the public interface of BinanceClient (spot) so runner.py
can pick the right client based on BotConfig.market_type without
branching on every call. Endpoints: fapi.binance.com (live) or
testnet.binancefuture.com (testnet).
"""
from __future__ import annotations
import time, hmac, hashlib, urllib.parse, logging
import requests

log = logging.getLogger(__name__)

FAPI_LIVE    = "https://fapi.binance.com"
FAPI_TESTNET = "https://testnet.binancefuture.com"

class BinanceFuturesClient:
    def __init__(self, api_key: str | None, api_secret: str | None, testnet: bool = True):
        self.api_key = api_key or ""
        self.api_secret = (api_secret or "").encode()
        self.base = FAPI_TESTNET if testnet else FAPI_LIVE
        self._leverage_set = set()  # symbols already configured

    # ── Public ─────────────────────────────────────────────
    def ping(self) -> bool:
        try:
            r = requests.get(f"{self.base}/fapi/v1/ping", timeout=8)
            return r.status_code == 200
        except Exception as e:
            log.warning("futures ping failed: %s", e); return False

    def ticker(self, symbol: str) -> dict:
        r = requests.get(f"{self.base}/fapi/v1/ticker/24hr",
                         params={"symbol": symbol}, timeout=8)
        r.raise_for_status(); return r.json()

    def klines(self, symbol: str, interval: str = "15m", limit: int = 200) -> list[list]:
        r = requests.get(f"{self.base}/fapi/v1/klines",
                         params={"symbol": symbol, "interval": interval, "limit": limit}, timeout=10)
        r.raise_for_status(); return r.json()

    def order_book(self, symbol: str, limit: int = 100) -> dict:
        r = requests.get(f"{self.base}/fapi/v1/depth",
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
        r = requests.get(f"{self.base}/fapi/v2/account",
                         params=self._sign({}), headers=self._headers(), timeout=10)
        r.raise_for_status(); return r.json()

    def balance_usdt(self) -> float:
        try:
            acct = self.account()
            for a in acct.get("assets", []):
                if a["asset"] == "USDT":
                    return float(a.get("walletBalance") or 0)
        except Exception as e:
            log.warning("futures balance fetch failed: %s", e)
        return 0.0

    def set_leverage(self, symbol: str, leverage: int) -> dict:
        try:
            r = requests.post(f"{self.base}/fapi/v1/leverage",
                              params=self._sign({"symbol": symbol, "leverage": int(leverage)}),
                              headers=self._headers(), timeout=8)
            r.raise_for_status(); return r.json()
        except Exception as e:
            log.warning("set_leverage(%s, %s) failed: %s", symbol, leverage, e); return {}

    def set_margin_type(self, symbol: str, margin_type: str) -> dict:
        """margin_type: ISOLATED or CROSSED"""
        try:
            r = requests.post(f"{self.base}/fapi/v1/marginType",
                              params=self._sign({"symbol": symbol, "marginType": margin_type.upper()}),
                              headers=self._headers(), timeout=8)
            # -4046 = "No need to change margin type" — not an error
            if r.status_code == 400 and "-4046" in r.text: return {}
            r.raise_for_status(); return r.json()
        except Exception as e:
            log.debug("set_margin_type(%s) soft-fail: %s", symbol, e); return {}

    def ensure_config(self, symbol: str, leverage: float, margin_mode: str):
        """Idempotent per-symbol setup called once from the runner."""
        if symbol in self._leverage_set: return
        lev = max(1, int(round(leverage)))
        self.set_margin_type(symbol, "ISOLATED" if margin_mode == "isolated" else "CROSSED")
        self.set_leverage(symbol, lev)
        self._leverage_set.add(symbol)

    def market_order(self, symbol: str, side: str, quantity: float,
                     reduce_only: bool = False, **kwargs) -> dict:
        """**kwargs absorbs the shared interface's optional arguments
        (client_order_id, stop_loss/take_profit) so a caller that passes them
        doesn't TypeError here; futures protection is not wired yet."""
        params = {
            "symbol": symbol, "side": side, "type": "MARKET",
            "quantity": f"{quantity:.8f}".rstrip("0").rstrip("."),
        }
        coid = kwargs.get("client_order_id")
        if coid:
            params["newClientOrderId"] = str(coid)[:36]
        if reduce_only:
            params["reduceOnly"] = "true"
        r = requests.post(f"{self.base}/fapi/v1/order",
                          params=self._sign(params),
                          headers=self._headers(), timeout=10)
        try: r.raise_for_status()
        except Exception: log.error("futures order failed: %s", r.text); raise
        return r.json()

    def positions(self) -> list[dict]:
        try:
            r = requests.get(f"{self.base}/fapi/v2/positionRisk",
                             params=self._sign({}), headers=self._headers(), timeout=10)
            r.raise_for_status(); return r.json()
        except Exception as e:
            log.warning("positions fetch failed: %s", e); return []

    def get_positions(self) -> list[dict]:
        """Non-zero open positions — Phase-33 reconciliation contract.

        Unlike positions(), transport errors RAISE here: returning [] on
        failure would read as "everything flat" and reconcile would close
        live DB rows for positions that are still open at the broker.
        """
        r = requests.get(f"{self.base}/fapi/v2/positionRisk",
                         params=self._sign({}), headers=self._headers(), timeout=10)
        r.raise_for_status()
        out = []
        for p in r.json() or []:
            amt = float(p.get("positionAmt", 0) or 0)
            if amt == 0:
                continue
            out.append({
                "symbol": str(p.get("symbol", "")).upper(),
                "qty": abs(amt),
                "side": "BUY" if amt > 0 else "SELL",
            })
        return out
