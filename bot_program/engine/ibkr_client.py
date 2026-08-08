"""Interactive Brokers adapter — Phase-14.

IBKR's TWS / IB Gateway speaks a socket protocol (not HTTP). The standard
Python wrapper is `ib_insync`, which sits on top of `ibapi` and gives us a
synchronous-feeling API.

Design constraints:
  * The platform must keep working without `ib_insync` installed.
  * Tests must run without a live TWS connection.
  * The IBKRTrader honours the same duck-typed interface as Binance/OANDA/
    Alpaca/Paper: `ping`, `ticker`, `klines`, `order_book`, `market_order`,
    `account`, `balance_usdt`.
  * It adds options-only methods on top: `option_chain`, `option_greeks`,
    `market_order_option`.

Graceful-degrade strategy:
  - If `ib_insync` import fails → `IBKRTrader.available()` returns False.
    All public methods return safe-empty values (paper-style stubs) and the
    broker_router falls back to PaperTrader.
  - If TWS/Gateway is not reachable on connect() → same fallback path.
  - Any per-call exception is caught and degrades to an empty/zero result;
    the bot continues, just without IBKR for that tick.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone as dt_tz
from typing import Optional

log = logging.getLogger(__name__)


# Try to import ib_insync, but never fail at import time. The platform must
# work without it — we only need it when a user actually wires their IBKR
# credentials AND TWS is running.
try:  # pragma: no cover — import behaviour is environment-specific
    import ib_insync as _ib  # type: ignore
    _IB_AVAILABLE = True
except Exception as _ib_import_err:  # pragma: no cover
    _ib = None
    _IB_AVAILABLE = False
    log.info("ib_insync not installed (%s) — IBKRTrader will degrade to stubs.",
             _ib_import_err)


# IB bar size codes — Binance kline interval → IBKR bar size string.
BAR_SIZE_MAP = {
    "1m": "1 min", "5m": "5 mins", "15m": "15 mins", "30m": "30 mins",
    "1h": "1 hour", "4h": "4 hours", "1d": "1 day", "1w": "1 week",
}


def is_ibkr_available() -> bool:
    """True when `ib_insync` is importable. Does NOT check TWS connectivity."""
    return _IB_AVAILABLE


# ── Symbol classification (best-effort) ────────────────────────────────────
# IBKR contracts are typed: Stock, Forex, Future, Option, CFD. The router knows
# the asset_class from the Instrument record, but the trader is also called
# with bare symbols, so we try to infer.
#
# Authoritative source of truth: Instrument.metadata["ibkr"], which can carry
#   sec_type:    "STK" | "CASH" | "FUT" | "CFD" | "IND"
#   exchange:    e.g. "SMART", "NYMEX", "COMEX", "CBOT", "GLOBEX", "IDEALPRO"
#   currency:    e.g. "USD", "EUR"
#   expiry:      "YYYYMM" or "YYYYMMDD" — required for FUT
#   multiplier:  e.g. "1000" for CL, "100" for ES — optional
#   localSymbol: optional override for IBKR localSymbol field
#
# Falls back to symbol-pattern heuristic if metadata is absent.

# Phase-14.2 default exchanges per common futures root.
FUTURES_DEFAULT_EXCHANGE = {
    # Energies / metals — NYMEX / COMEX
    "CL": "NYMEX", "NG": "NYMEX", "RB": "NYMEX", "HO": "NYMEX",
    "GC": "COMEX", "SI": "COMEX", "HG": "COMEX",
    # Equity index futures — CME Globex
    "ES": "GLOBEX", "NQ": "GLOBEX", "YM": "CBOT",
    "RTY": "GLOBEX", "MES": "GLOBEX", "MNQ": "GLOBEX",
    # Rates — CBOT
    "ZB": "CBOT", "ZN": "CBOT", "ZF": "CBOT", "ZT": "CBOT",
    # Ags — CBOT
    "ZC": "CBOT", "ZS": "CBOT", "ZW": "CBOT",
    # FX futures — CME
    "6E": "GLOBEX", "6B": "GLOBEX", "6J": "GLOBEX", "6A": "GLOBEX",
}


def _looks_like_forex(symbol: str) -> bool:
    """6-char like 'EURUSD' or 'EUR/USD' → forex."""
    s = symbol.replace("/", "").replace("_", "").upper()
    if len(s) == 6 and s.isalpha():
        return True
    return False


def _split_forex(symbol: str) -> "tuple[str, str]":
    s = symbol.replace("/", "").replace("_", "").upper()
    return s[:3], s[3:]


def _ibkr_meta_for(symbol: str) -> dict:
    """Look up the Instrument's `metadata["ibkr"]` block, or {} on miss."""
    try:
        from instruments.models import Instrument
        inst = Instrument.objects.filter(symbol=symbol).first()
        if inst is None:
            return {}
        return (inst.metadata or {}).get("ibkr") or {}
    except Exception:
        return {}


# ── Adapter ────────────────────────────────────────────────────────────────

class IBKRTrader:
    """Duck-typed IBKR client.

    Connection is lazy — established on first real call so tests that only
    construct an IBKRTrader for routing checks don't trigger a socket attempt.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 7497,
        client_id: int = 1,
        account_id: Optional[str] = None,
        paper: bool = True,
        timeout: float = 5.0,
    ):
        self.host = host
        self.port = port
        self.client_id = client_id
        self.account_id = account_id or ""
        self.paper = paper
        self.timeout = timeout
        self._ib = None  # lazily-instantiated IB() instance
        self._connected = False

    # ── connection management ─────────────────────────────────────────────

    @staticmethod
    def available() -> bool:
        return _IB_AVAILABLE

    def _connect(self) -> bool:
        """Try to connect to TWS/IB Gateway. Returns True on success."""
        if not _IB_AVAILABLE:
            return False
        if self._ib is not None and self._connected:
            return True
        try:
            ib = _ib.IB()
            ib.connect(self.host, self.port, clientId=self.client_id,
                       timeout=self.timeout, readonly=False)
            self._ib = ib
            self._connected = True
            return True
        except Exception as e:
            log.warning("IBKR connect to %s:%s failed: %s", self.host, self.port, e)
            self._ib = None
            self._connected = False
            return False

    def disconnect(self) -> None:
        if self._ib is not None and self._connected:
            try:
                self._ib.disconnect()
            except Exception:
                pass
        self._ib = None
        self._connected = False

    # ── duck-typed broker interface ───────────────────────────────────────

    def ping(self) -> bool:
        if not _IB_AVAILABLE:
            return False
        return self._connect() and bool(self._ib and self._ib.isConnected())

    def ticker(self, symbol: str) -> dict:
        empty = {"lastPrice": "0", "symbol": symbol}
        if not self._connect():
            return empty
        try:
            contract = self._build_contract(symbol)
            if contract is None:
                return empty
            self._ib.qualifyContracts(contract)
            t = self._ib.reqMktData(contract, "", False, False)
            self._ib.sleep(1.0)  # let the tick stream warm up
            last = float(t.last) if t.last else (
                (float(t.bid) + float(t.ask)) / 2 if (t.bid and t.ask) else 0.0
            )
            return {
                "lastPrice": str(last),
                "symbol": symbol,
                "bid": str(t.bid) if t.bid else "0",
                "ask": str(t.ask) if t.ask else "0",
            }
        except Exception as e:
            log.warning("IBKR ticker(%s) failed: %s", symbol, e)
            return empty

    def klines(self, symbol: str, interval: str = "1h", limit: int = 200) -> list:
        if not self._connect():
            return []
        bar_size = BAR_SIZE_MAP.get(interval, "1 hour")
        try:
            contract = self._build_contract(symbol)
            if contract is None:
                return []
            self._ib.qualifyContracts(contract)
            bars = self._ib.reqHistoricalData(
                contract, endDateTime="",
                durationStr=self._duration_for(limit, bar_size),
                barSizeSetting=bar_size,
                whatToShow="TRADES" if not _looks_like_forex(symbol) else "MIDPOINT",
                useRTH=False, formatDate=2,
            )
            rows = []
            for b in bars[-limit:]:
                ts = int(b.date.replace(tzinfo=dt_tz.utc).timestamp() * 1000) \
                    if isinstance(b.date, datetime) else 0
                rows.append([
                    ts,
                    str(b.open), str(b.high), str(b.low), str(b.close),
                    str(b.volume), ts + 60_000,
                    "0", 0, "0", "0", "0",
                ])
            return rows
        except Exception as e:
            log.warning("IBKR klines(%s) failed: %s", symbol, e)
            return []

    def order_book(self, symbol: str, limit: int = 50) -> dict:
        """IBKR has L2 via reqMktDepth but it requires a separate subscription.
        Synthesise from ticker for parity with the rest of the platform."""
        tk = self.ticker(symbol)
        bid = float(tk.get("bid", "0") or 0)
        ask = float(tk.get("ask", "0") or 0)
        if not (bid and ask):
            return {"bids": [], "asks": []}
        return {
            "bids": [[str(round(bid * (1 - i * 0.0001), 4)), "100"]
                     for i in range(min(limit, 20))],
            "asks": [[str(round(ask * (1 + i * 0.0001), 4)), "100"]
                     for i in range(min(limit, 20))],
        }

    def account(self) -> dict:
        if not self._connect():
            return {}
        try:
            vals = self._ib.accountValues(account=self.account_id or "")
            out = {}
            for v in vals:
                out[v.tag] = v.value
            return out
        except Exception as e:
            log.warning("IBKR account() failed: %s", e)
            return {}

    def balance_usdt(self) -> float:
        """IBKR base currency may not be USD — best-effort read of NetLiquidation."""
        info = self.account()
        for tag in ("NetLiquidation", "AvailableFunds", "TotalCashValue"):
            v = info.get(tag)
            if v:
                try:
                    return float(v)
                except (TypeError, ValueError):
                    continue
        return 0.0

    def get_positions(self) -> list[dict]:
        """Open positions via ib.positions() — Phase-33 reconciliation.

        Raises when TWS is unreachable: returning [] would read as
        "everything flat" and reconcile would close live DB rows for
        positions that are still open at the broker. For OPT positions the
        reported symbol is the UNDERLYING, matching AssetBotTrade.symbol.
        """
        if not self._connect():
            raise RuntimeError("IBKR unavailable — cannot list positions")
        out = []
        for pos in self._ib.positions(self.account_id or ""):
            qty = float(pos.position or 0)
            if qty == 0:
                continue
            contract = pos.contract
            sec_type = str(getattr(contract, "secType", ""))
            symbol = str(getattr(contract, "symbol", "")).upper()
            # ib_insync Forex contracts carry only the base currency in
            # .symbol ("EUR"); rebuild the bot's pair form ("EURUSD").
            if sec_type == "CASH":
                symbol += str(getattr(contract, "currency", "")).upper()
            out.append({
                "symbol": symbol,
                "qty": abs(qty),
                "side": "BUY" if qty > 0 else "SELL",
                "sec_type": sec_type,
            })
        return out

    def market_order(self, symbol: str, side: str, quantity: float, **kwargs) -> dict:
        empty = {
            "orderId": "", "symbol": symbol, "side": side,
            "executedQty": "0", "avgPrice": "0",
            "status": "REJECTED", "raw": {"reason": "ibkr_unavailable"},
        }
        if not self._connect():
            return empty
        try:
            contract = self._build_contract(symbol)
            if contract is None:
                return empty
            self._ib.qualifyContracts(contract)
            action = "BUY" if side.upper() == "BUY" else "SELL"
            order = _ib.MarketOrder(action, abs(float(quantity)))
            trade = self._ib.placeOrder(contract, order)
            self._ib.sleep(1.0)
            filled_qty = float(trade.orderStatus.filled or 0)
            avg_px = float(trade.orderStatus.avgFillPrice or 0)
            return {
                "orderId": str(trade.order.orderId or ""),
                "symbol": symbol, "side": side,
                "executedQty": str(filled_qty or quantity),
                "avgPrice": str(avg_px or 0),
                "status": (trade.orderStatus.status or "PENDING").upper(),
                "raw": trade.dict() if hasattr(trade, "dict") else {},
            }
        except Exception as e:
            log.error("IBKR market_order(%s, %s, %s) failed: %s",
                      symbol, side, quantity, e)
            return empty

    # ── options-specific surface ──────────────────────────────────────────

    def option_chain(self, underlying: str, expiry: Optional[str] = None) -> list[dict]:
        """Return a list of option contracts for `underlying`.

        Each entry: {strike, expiry (YYYY-MM-DD), right ('C'|'P'), bid, ask,
                     last, iv, delta, gamma, theta, vega, oi, volume}.

        `expiry` filters to that specific expiry (YYYYMMDD or YYYY-MM-DD); if
        None, returns the chain for the nearest available expiry.
        """
        if not self._connect():
            return []
        try:
            stk = _ib.Stock(underlying, "SMART", "USD")
            self._ib.qualifyContracts(stk)
            params = self._ib.reqSecDefOptParams(
                stk.symbol, "", stk.secType, stk.conId,
            )
            if not params:
                return []
            chain = next((p for p in params if p.exchange == "SMART"), params[0])
            expiries = sorted(chain.expirations)
            target_exp = self._normalise_expiry(expiry, expiries)
            if not target_exp:
                return []

            contracts = []
            for strike in sorted(chain.strikes):
                for right in ("C", "P"):
                    contracts.append(_ib.Option(
                        underlying, target_exp, strike, right, "SMART",
                    ))
            self._ib.qualifyContracts(*contracts)

            tickers = self._ib.reqTickers(*contracts)
            out = []
            for t in tickers:
                c = t.contract
                greeks = t.modelGreeks or t.lastGreeks
                out.append({
                    "symbol": c.localSymbol,
                    "strike": float(c.strike),
                    "expiry": self._iso_expiry(c.lastTradeDateOrContractMonth),
                    "right": c.right,
                    "bid": float(t.bid) if t.bid else None,
                    "ask": float(t.ask) if t.ask else None,
                    "last": float(t.last) if t.last else None,
                    "iv": float(greeks.impliedVol) if greeks and greeks.impliedVol else None,
                    "delta": float(greeks.delta) if greeks and greeks.delta is not None else None,
                    "gamma": float(greeks.gamma) if greeks and greeks.gamma is not None else None,
                    "theta": float(greeks.theta) if greeks and greeks.theta is not None else None,
                    "vega": float(greeks.vega) if greeks and greeks.vega is not None else None,
                    "open_interest": 0,
                    "volume": int(t.volume) if t.volume else 0,
                })
            return out
        except Exception as e:
            log.warning("IBKR option_chain(%s) failed: %s", underlying, e)
            return []

    def option_greeks(self, underlying: str, strike: float, expiry: str,
                      right: str) -> dict:
        """Greeks for a single contract. Empty dict if the broker can't deliver."""
        if not self._connect():
            return {}
        try:
            opt = _ib.Option(
                underlying, expiry.replace("-", ""), strike, right.upper(), "SMART",
            )
            self._ib.qualifyContracts(opt)
            t = self._ib.reqMktData(opt, "", False, False)
            self._ib.sleep(1.0)
            g = t.modelGreeks or t.lastGreeks
            if not g:
                return {}
            return {
                "iv": float(g.impliedVol) if g.impliedVol else None,
                "delta": float(g.delta) if g.delta is not None else None,
                "gamma": float(g.gamma) if g.gamma is not None else None,
                "theta": float(g.theta) if g.theta is not None else None,
                "vega": float(g.vega) if g.vega is not None else None,
            }
        except Exception as e:
            log.warning("IBKR option_greeks(%s) failed: %s", underlying, e)
            return {}

    def market_order_option(self, underlying: str, strike: float, expiry: str,
                            right: str, side: str, contracts: int) -> dict:
        empty = {
            "orderId": "", "symbol": f"{underlying} {expiry} {strike}{right}",
            "side": side, "executedQty": "0", "avgPrice": "0",
            "status": "REJECTED", "raw": {"reason": "ibkr_unavailable"},
        }
        if not self._connect():
            return empty
        try:
            opt = _ib.Option(
                underlying, expiry.replace("-", ""), strike, right.upper(), "SMART",
            )
            self._ib.qualifyContracts(opt)
            action = "BUY" if side.upper() == "BUY" else "SELL"
            order = _ib.MarketOrder(action, abs(int(contracts)))
            trade = self._ib.placeOrder(opt, order)
            self._ib.sleep(1.0)
            return {
                "orderId": str(trade.order.orderId or ""),
                "symbol": f"{underlying} {expiry} {strike}{right.upper()}",
                "side": side,
                "executedQty": str(trade.orderStatus.filled or contracts),
                "avgPrice": str(trade.orderStatus.avgFillPrice or 0),
                "status": (trade.orderStatus.status or "PENDING").upper(),
            }
        except Exception as e:
            log.error("IBKR market_order_option failed: %s", e)
            return empty

    # ── helpers ───────────────────────────────────────────────────────────

    def _build_contract(self, symbol: str):
        """Build the right IBKR contract type for `symbol`.

        Order of resolution:
          1. Instrument.metadata["ibkr"] explicit sec_type → authoritative.
          2. Symbol-pattern heuristic — 6-letter alpha → Forex; else Stock SMART/USD.
        """
        if not _IB_AVAILABLE:
            return None

        meta = _ibkr_meta_for(symbol)
        sec_type = (meta.get("sec_type") or "").upper()

        # ── Future (FUT) — requires expiry, exchange best-effort by root ──
        if sec_type == "FUT":
            return self._build_future(symbol, meta)

        # ── CFD ─────────────────────────────────────────────────────────
        if sec_type == "CFD":
            return _ib.CFD(
                meta.get("localSymbol") or symbol,
                exchange=meta.get("exchange") or "SMART",
                currency=meta.get("currency") or "USD",
            )

        # ── Index (IND) — for index quotes/derivatives ──────────────────
        if sec_type == "IND":
            return _ib.Index(
                meta.get("localSymbol") or symbol,
                exchange=meta.get("exchange") or "CBOE",
                currency=meta.get("currency") or "USD",
            )

        # ── Forex (CASH) — explicit metadata wins over heuristic ────────
        if sec_type == "CASH":
            base, quote = _split_forex(meta.get("localSymbol") or symbol)
            return _ib.Forex(f"{base}{quote}")

        # ── Stock (STK) — explicit metadata ─────────────────────────────
        if sec_type == "STK":
            return _ib.Stock(
                meta.get("localSymbol") or symbol,
                exchange=meta.get("exchange") or "SMART",
                currency=meta.get("currency") or "USD",
            )

        # ── Heuristic fallback ──────────────────────────────────────────
        if _looks_like_forex(symbol):
            base, quote = _split_forex(symbol)
            return _ib.Forex(f"{base}{quote}")
        return _ib.Stock(symbol, "SMART", "USD")

    def _build_future(self, symbol: str, meta: dict):
        """Build a Future contract from `Instrument.metadata["ibkr"]`.

        Required: meta["expiry"] = "YYYYMM" or "YYYYMMDD".
        Falls back to a continuous front-month (`ContFuture`) when no expiry
        is specified — useful for price-data scans, NOT for live orders
        (IBKR rejects orders on continuous contracts).
        """
        # Pick the futures root: explicit symbol (CL, GC, ES, ...) or strip
        # any leading metadata override.
        root = (meta.get("localSymbol") or symbol).upper()
        exchange = meta.get("exchange") or FUTURES_DEFAULT_EXCHANGE.get(root, "GLOBEX")
        currency = meta.get("currency") or "USD"
        expiry = meta.get("expiry") or ""

        if not expiry:
            # Continuous front-month — read-only.
            try:
                return _ib.ContFuture(root, exchange=exchange, currency=currency)
            except Exception:
                return _ib.Future(root, exchange=exchange, currency=currency)

        kwargs = {"exchange": exchange, "currency": currency,
                  "lastTradeDateOrContractMonth": str(expiry).replace("-", "")}
        if meta.get("multiplier"):
            kwargs["multiplier"] = str(meta["multiplier"])
        return _ib.Future(root, **kwargs)

    @staticmethod
    def _duration_for(limit: int, bar_size: str) -> str:
        """Map (limit, bar_size) → IB durationStr.

        Heuristic: ask for enough history to satisfy `limit` bars, capped at
        IB's typical limits per bar size.
        """
        if "min" in bar_size:
            mins = int(bar_size.split()[0]) if bar_size.split()[0].isdigit() else 1
            seconds = max(60, limit * mins * 60)
            if seconds <= 86400:
                return f"{seconds} S"
            days = max(1, (seconds // 86400) + 1)
            return f"{min(days, 30)} D"
        if "hour" in bar_size:
            hours = int(bar_size.split()[0]) if bar_size.split()[0].isdigit() else 1
            days = max(1, (limit * hours) // 24 + 1)
            return f"{min(days, 365)} D"
        if "day" in bar_size:
            return f"{min(limit, 365)} D"
        if "week" in bar_size:
            return f"{min(limit, 52)} W"
        return f"{limit} D"

    @staticmethod
    def _normalise_expiry(req: Optional[str], available: list[str]) -> Optional[str]:
        """`available` is a list of YYYYMMDD strings. Return matching one."""
        if not available:
            return None
        if not req:
            return available[0]
        norm = req.replace("-", "")
        return norm if norm in available else None

    @staticmethod
    def _iso_expiry(yyyymmdd: str) -> str:
        if not yyyymmdd or len(yyyymmdd) < 8:
            return ""
        return f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:8]}"
