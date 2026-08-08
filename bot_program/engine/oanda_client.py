"""OANDA v20 trading client — Phase-4 forex execution.

Conforms to the same duck-typed interface as `BinanceClient` / `PaperTrader`:
  ping, ticker, klines, order_book, market_order, account, balance_usdt.

Endpoint roots:
  practice  https://api-fxpractice.oanda.com    https://stream-fxpractice.oanda.com
  live      https://api-fxtrade.oanda.com       https://stream-fxtrade.oanda.com

Symbol convention: OANDA uses underscore form ("EUR_USD"). The Instrument table
uses joined form ("EURUSD"). The adapter accepts the joined form and normalises
internally. `klines()` returns Binance-style 11-element rows for parity with the
runner's `_parse_klines` helper.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

import requests

log = logging.getLogger(__name__)


PRACTICE_API = "https://api-fxpractice.oanda.com"
LIVE_API = "https://api-fxtrade.oanda.com"

# OANDA candle granularity matching our Timeframe codes.
GRANULARITY_MAP = {
    "1m": "M1", "5m": "M5", "15m": "M15", "30m": "M30",
    "1h": "H1", "4h": "H4", "1d": "D", "1w": "W",
}


def _to_oanda_symbol(symbol: str) -> str:
    """EURUSD → EUR_USD. Already-formatted symbols pass through."""
    if "_" in symbol:
        return symbol
    if len(symbol) == 6:
        return f"{symbol[:3]}_{symbol[3:]}"
    return symbol


def _to_iso_ms(ts_str: str) -> int:
    """OANDA timestamps like '2026-04-30T13:00:00.000000000Z' → epoch ms."""
    # OANDA appends nanoseconds; truncate to microseconds for fromisoformat.
    s = ts_str.rstrip("Z").rstrip("0")
    if "." in s:
        whole, frac = s.split(".", 1)
        s = whole + "." + frac[:6]
    try:
        return int(datetime.fromisoformat(s).replace(tzinfo=timezone.utc).timestamp() * 1000)
    except ValueError:
        return 0


class OANDATrader:
    """OANDA REST trading client."""

    def __init__(
        self,
        api_key: str,
        account_id: str,
        env: str = "practice",
        timeout: float = 10.0,
    ):
        self.api_key = api_key
        self.account_id = account_id
        self.env = env.lower()
        self.base = PRACTICE_API if self.env != "live" else LIVE_API
        self.timeout = timeout
        self._session: Optional[requests.Session] = None

    def _sess(self) -> requests.Session:
        if self._session is None:
            s = requests.Session()
            s.headers.update({
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept-Datetime-Format": "RFC3339",
            })
            self._session = s
        return self._session

    # ── public ─────────────────────────────────────────────────────────────

    def ping(self) -> bool:
        try:
            r = self._sess().get(f"{self.base}/v3/accounts/{self.account_id}/summary",
                                 timeout=self.timeout)
            return r.status_code == 200
        except Exception as e:
            log.warning("OANDA ping failed: %s", e)
            return False

    def ticker(self, symbol: str) -> dict:
        instr = _to_oanda_symbol(symbol)
        r = self._sess().get(
            f"{self.base}/v3/accounts/{self.account_id}/pricing",
            params={"instruments": instr}, timeout=self.timeout,
        )
        r.raise_for_status()
        prices = r.json().get("prices", [])
        if not prices:
            return {"lastPrice": "0", "symbol": symbol}
        p = prices[0]
        # OANDA returns bids/asks as lists of {price, liquidity}. Mid as last price.
        bid = float(p["bids"][0]["price"]) if p.get("bids") else 0.0
        ask = float(p["asks"][0]["price"]) if p.get("asks") else 0.0
        last = (bid + ask) / 2 if bid and ask else (bid or ask)
        return {"lastPrice": str(last), "symbol": symbol, "bid": str(bid), "ask": str(ask)}

    def klines(self, symbol: str, interval: str = "15m", limit: int = 200) -> list[list]:
        """Return Binance-style 11-element rows: [openTime, o, h, l, c, v, closeTime, ...]."""
        instr = _to_oanda_symbol(symbol)
        gran = GRANULARITY_MAP.get(interval, "M15")
        r = self._sess().get(
            f"{self.base}/v3/instruments/{instr}/candles",
            params={"granularity": gran, "count": min(limit, 5000)},
            timeout=self.timeout,
        )
        r.raise_for_status()
        candles = r.json().get("candles", [])
        rows = []
        for c in candles:
            if not c.get("complete"):
                continue
            mid = c.get("mid", {})
            ts = _to_iso_ms(c.get("time", ""))
            rows.append([
                ts,
                str(mid.get("o", "0")),
                str(mid.get("h", "0")),
                str(mid.get("l", "0")),
                str(mid.get("c", "0")),
                str(c.get("volume", 0)),
                ts + 60_000,  # close-time approx; OANDA doesn't return it
                "0", 0, "0", "0", "0",
            ])
        return rows

    def order_book(self, symbol: str, limit: int = 50) -> dict:
        """Synthesise a thin book from the current bid/ask. OANDA does not
        expose an aggregated order book on the retail v20 endpoint, so we
        return a minimal structure parity-compatible with Binance."""
        tk = self.ticker(symbol)
        bid = float(tk.get("bid", "0") or 0)
        ask = float(tk.get("ask", "0") or 0)
        if not (bid and ask):
            return {"bids": [], "asks": []}
        # Synthetic depth — single level ladder around bid/ask.
        return {
            "bids": [[str(round(bid * (1 - i * 0.0001), 6)), "1000000"] for i in range(min(limit, 20))],
            "asks": [[str(round(ask * (1 + i * 0.0001), 6)), "1000000"] for i in range(min(limit, 20))],
        }

    # ── signed ─────────────────────────────────────────────────────────────

    def account(self) -> dict:
        r = self._sess().get(f"{self.base}/v3/accounts/{self.account_id}/summary",
                             timeout=self.timeout)
        r.raise_for_status()
        return r.json().get("account", {})

    def balance_usdt(self) -> float:
        """Account balance — OANDA reports in the account base currency, not
        USDT. Returns the raw balance; caller is responsible for FX conversion
        if needed."""
        try:
            return float(self.account().get("balance", 0))
        except Exception as e:
            log.warning("OANDA balance fetch failed: %s", e)
            return 0.0

    def get_positions(self) -> list[dict]:
        """Open positions via /v3/accounts/{id}/openPositions — Phase-33
        reconciliation. Symbols are returned in bot format (EURUSD, not
        EUR_USD). Raises on transport errors so reconcile counts the broker
        unavailable instead of assuming flat."""
        r = self._sess().get(
            f"{self.base}/v3/accounts/{self.account_id}/openPositions",
            timeout=self.timeout,
        )
        r.raise_for_status()
        out = []
        for p in r.json().get("positions", []):
            instr = str(p.get("instrument", ""))
            long_units = float((p.get("long") or {}).get("units", 0) or 0)
            short_units = float((p.get("short") or {}).get("units", 0) or 0)
            # Gross, not net: on a hedging-enabled account offsetting legs
            # net to zero while both remain open at the broker.
            gross = abs(long_units) + abs(short_units)
            if gross == 0:
                continue
            net = long_units + short_units
            out.append({
                "symbol": instr.replace("_", "").upper(),
                "qty": gross,
                "side": "BUY" if net >= 0 else "SELL",
            })
        return out

    def market_order(self, symbol: str, side: str, quantity: float, **kwargs) -> dict:
        """side: BUY/SELL. quantity in base units (positive for BUY, negative
        for SELL — OANDA convention; we accept BUY/SELL and sign internally)."""
        instr = _to_oanda_symbol(symbol)
        units = float(quantity) if side == "BUY" else -float(quantity)
        order = {
            "type": "MARKET",
            "instrument": instr,
            "units": f"{units:.4f}".rstrip("0").rstrip(".") or "0",
            "timeInForce": "FOK",
            "positionFill": "DEFAULT",
        }
        # Broker-side protection: OANDA attaches SL/TP to the trade created by
        # this order, so the position stays protected when the bot is down.
        stop_loss = kwargs.get("stop_loss")
        take_profit = kwargs.get("take_profit")
        protected = False
        if stop_loss and take_profit:
            digits = 3 if instr.endswith("_JPY") else 5
            order["stopLossOnFill"] = {
                "price": f"{float(stop_loss):.{digits}f}", "timeInForce": "GTC"}
            order["takeProfitOnFill"] = {
                "price": f"{float(take_profit):.{digits}f}", "timeInForce": "GTC"}
            protected = True
        # Phase-33 idempotency — OANDA's clientExtensions.id provides dedup.
        coid = kwargs.get("client_order_id")
        if coid:
            order["clientExtensions"] = {"id": coid[:64]}
        body = {"order": order}
        r = self._sess().post(
            f"{self.base}/v3/accounts/{self.account_id}/orders",
            json=body, timeout=self.timeout,
        )
        try:
            r.raise_for_status()
        except Exception:
            log.error("OANDA order failed: %s", r.text)
            raise
        data = r.json()
        fill = data.get("orderFillTransaction", {})
        out = {
            "orderId": str(fill.get("id") or data.get("orderCreateTransaction", {}).get("id", "")),
            "symbol": symbol,
            "side": side,
            "executedQty": str(abs(float(fill.get("units", units)))),
            "avgPrice": str(fill.get("price", "0")),
            "status": "FILLED" if fill else "PENDING",
            "raw": data,
        }
        if protected and fill:
            out["protectedOnFill"] = True
            # SL/TP ride on the trade itself; closing the trade cancels them,
            # so there are no standalone order ids to track.
            out["protectiveOrders"] = []
        return out

    def cancel_order(self, order_id: str) -> bool:
        """Cancel a pending order. OANDA's on-fill SL/TP are attached to the
        trade (cancelled automatically when it closes), so this is only for
        standalone orders."""
        r = self._sess().put(
            f"{self.base}/v3/accounts/{self.account_id}/orders/{order_id}/cancel",
            timeout=self.timeout,
        )
        if r.status_code in (200, 404):
            return r.status_code == 200
        r.raise_for_status()
        return False
