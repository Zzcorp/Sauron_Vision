"""eToro public API trading client (2026-09-17).

Conforms to the duck-typed adapter contract in `engine/capabilities.py`,
declaring: market_data, execution, brackets, account.

    ping, ticker, klines, order_book            market_data
    market_order                                execution
    modify_protective, modify_target            brackets
    net_liquidation, broker_portfolio           account
    account, balance_usdt, get_positions        (used, not a tier on their own)

NOT declared, on purpose — see "What it refuses to claim" below.

WHY THIS BROKER

eToro authenticates with two LONG-LIVED keys sent as headers. No OAuth, no
token to refresh, no daily human at a phone. That is the property IBKR's
retail API withholds, and the reason the operator is moving live capital
here. It also holds the stop, the target AND a trailing stop at the broker,
so a position stays protected while this platform is down — which today's
engine only gets from OANDA and Alpaca.

THREE FACTS ABOUT THE API THAT SHAPE EVERYTHING BELOW

1. ORDERS ARE ASYNCHRONOUS. A 200 on POST /orders means "accepted for
   processing", not "filled". The fill is read by a second call,
   orders:lookup, keyed by the x-request-id this client sent. Status is a
   twelve-value table; 3 and 5 are fills, 4/7/8/9/10 are refusals. This
   client polls — bounded, best-effort, the way `AlpacaTrader._await_fill`
   does — and NEVER reports an acceptance as a fill. OANDA's own history
   here is the warning: "a completely unfilled order was booked as a
   complete fill on both sides".

2. TWO API VERSIONS, TWO PATH RULES. Opening and modifying are v2, where
   the REAL account OMITS the environment segment:
       /api/v2/trading/execution/demo/orders   vs   /api/v2/trading/execution/orders
   Portfolio, rates and closing are v1, where the real account WRITES it:
       /api/v1/trading/info/demo/portfolio     vs   /api/v1/trading/info/real/portfolio
   Encoded in two helpers rather than discovered in production on a real
   key. Everything under /market-data/ carries no environment at all.

3. EVERYTHING IS KEYED ON AN INTEGER instrumentId — candles, rates,
   closing. Only order creation accepts a ticker. Ids are immutable
   (the docs: "they never change, even if a company rebrands"), so they
   are resolved once through /market-data/search and cached for the life
   of the client. An unresolvable symbol RAISES: asking for bars on a
   wrong id answers an empty list, which is indistinguishable from "no
   history" and is exactly how `market_data/bot_bars.py` documents a bot
   going blind one spelling at a time.

WHAT IT REFUSES TO CLAIM

  * `orders` — the reference documents no way to cancel a pending order
    (`positionIds` / `action: close` are marked "not yet supported").
    `get_positions` exists because reconciliation needs it; `cancel_order`
    does not, so the tier is honestly absent. A method that existed and
    could not act would pass the conformance test and lie.
  * `fills` — no closed-position history is documented anywhere, and the
    close-confirmation shape has not met a real key. `closing_fill` is
    therefore not implemented: the engine falls down its own ladder to a
    ticker read flagged `exit_price_inferred`, which is the honest path it
    already has. It gets implemented the day the confirmation is verified.
  * `options`, `leverage` — leverage on eToro is per-order (`leverage` in
    the body, defaulting to 1); this client always sends 1.

Symbol convention: the platform's spelling is passed to /search as
`internalSymbolFull`. No renaming table exists yet because none has been
measured; the first symbol eToro spells differently will fail loudly here
rather than silently elsewhere, and that is where the table starts.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

import requests

log = logging.getLogger(__name__)

BASE = "https://public-api.etoro.com"

#: Platform timeframe -> eToro candle interval enum.
INTERVAL_MAP = {
    "1m": "OneMinute", "5m": "FiveMinutes", "10m": "TenMinutes",
    "15m": "FifteenMinutes", "30m": "ThirtyMinutes",
    "1h": "OneHour", "4h": "FourHours", "1d": "OneDay", "1w": "OneWeek",
}
#: Seconds per interval, for the close-time column of a kline row.
INTERVAL_SECONDS = {
    "1m": 60, "5m": 300, "10m": 600, "15m": 900, "30m": 1800,
    "1h": 3600, "4h": 14400, "1d": 86400, "1w": 604800,
}
CANDLES_MAX = 1000

#: eToro order status ids (orders:lookup). Two fills, five refusals, the
#: rest pending. Mapped onto the vocabulary `asset_engine` already refuses
#: on: REJECTED / CANCELLED / EXPIRED with no fill is a skipped entry.
STATUS_FILLED = {3, 5}
STATUS_REFUSED = {4: "REJECTED", 7: "CANCELLED", 8: "EXPIRED",
                  9: "CANCELLED", 10: "REJECTED"}
STATUS_NAMES = {1: "Received", 2: "Placed", 3: "Filled", 4: "Rejected",
                5: "PartiallyFilled", 6: "PendingCancel", 7: "Canceled",
                8: "Expired", 9: "CanceledPartiallyFilled",
                10: "RejectedPartiallyFilled", 11: "WaitingForMarket",
                12: "PendingTriggeredRate"}

#: Polling for the async fill — bounded and best-effort, matching
#: AlpacaTrader._await_fill. A still-pending order is reported PENDING with
#: no quantity, never as a fill.
FILL_ATTEMPTS = 5
FILL_DELAY_S = 0.6


def _iso_to_ms(ts: str) -> int:
    """'2026-09-17T08:00:00Z' -> epoch ms; 0 when unreadable."""
    s = (ts or "").rstrip("Z")
    if "." in s:
        whole, frac = s.split(".", 1)
        s = whole + "." + frac[:6].ljust(6, "0")
    try:
        return int(datetime.fromisoformat(s).replace(
            tzinfo=timezone.utc).timestamp() * 1000)
    except ValueError:
        return 0


class EtoroTrader:
    """eToro REST trading client."""

    def __init__(self, api_key: str, user_key: str, env: str = "demo",
                 timeout: float = 10.0):
        self.api_key = api_key
        self.user_key = user_key
        self.env = (env or "demo").lower()
        self.demo = self.env != "live"
        self.timeout = timeout
        self._session: Optional[requests.Session] = None
        # symbol -> instrumentId, and the reverse for reading positions back.
        self._ids: dict = {}
        self._symbols: dict = {}

    # ── plumbing ───────────────────────────────────────────────────────────

    def _sess(self) -> requests.Session:
        if self._session is None:
            s = requests.Session()
            s.headers.update({"x-api-key": self.api_key,
                              "x-user-key": self.user_key,
                              "Content-Type": "application/json"})
            self._session = s
        return self._session

    @staticmethod
    def _rid(client_order_id: Optional[str] = None) -> str:
        """x-request-id: required on every call, and the idempotency key of
        an order. A caller's client_order_id is used when it is a UUID;
        anything else gets a fresh one and the caller's id is recorded in
        the raw payload instead."""
        if client_order_id:
            try:
                return str(uuid.UUID(str(client_order_id)))
            except ValueError:
                pass
        return str(uuid.uuid4())

    def _headers(self, rid: Optional[str] = None) -> dict:
        return {"x-request-id": rid or self._rid()}

    # Path rule 2: v1 writes the environment, v2 omits it for real.
    def _v1_info(self, tail: str) -> str:
        env = "demo" if self.demo else "real"
        return f"{BASE}/api/v1/trading/info/{env}/{tail}"

    def _v1_exec(self, tail: str) -> str:
        env = "demo" if self.demo else "real"
        return f"{BASE}/api/v1/trading/execution/{env}/{tail}"

    def _v2(self, tail: str) -> str:
        seg = "demo/" if self.demo else ""
        return f"{BASE}/api/v2/trading/{seg}{tail}"

    def _v2_exec_orders(self) -> str:
        seg = "demo/" if self.demo else ""
        return f"{BASE}/api/v2/trading/execution/{seg}orders"

    def _v2_lookup(self) -> str:
        seg = "demo/" if self.demo else ""
        return f"{BASE}/api/v2/trading/info/{seg}orders:lookup"

    # ── instruments (fact 3) ───────────────────────────────────────────────

    def instrument_id(self, symbol: str) -> int:
        """The immutable integer id for `symbol`, resolved once and cached.

        Raises LookupError when eToro does not know the spelling. Silently
        returning 0 would make every later call answer "nothing here",
        which reads as a quiet market and is a blind bot.
        """
        key = str(symbol).upper()
        if key in self._ids:
            return self._ids[key]
        r = self._sess().get(f"{BASE}/api/v1/market-data/search",
                             params={"internalSymbolFull": key},
                             headers=self._headers(), timeout=self.timeout)
        r.raise_for_status()
        data = r.json()
        items = data if isinstance(data, list) else (
            data.get("items") or data.get("instruments") or data.get("data")
            or ([data] if data.get("instrumentId") else []))
        for it in items:
            sym = str(it.get("internalSymbolFull") or it.get("symbol")
                      or "").upper()
            iid = it.get("instrumentId") or it.get("instrumentID")
            if iid and (sym == key or len(items) == 1):
                iid = int(iid)
                self._ids[key] = iid
                self._symbols[iid] = key
                return iid
        raise LookupError(f"eToro knows no instrument spelled {key!r}")

    def _symbol_for(self, instrument_id) -> str:
        """Reverse lookup for positions read back. Warm for every symbol
        this client resolved; a cold id is reported as its number rather
        than guessed at, and says so."""
        try:
            iid = int(instrument_id)
        except (TypeError, ValueError):
            return str(instrument_id)
        return self._symbols.get(iid, f"ETORO:{iid}")

    def _named(self, instrument_id) -> bool:
        """Can THIS client put a platform symbol on that instrument id?

        The reverse map is warm only for the symbols this instance itself
        resolved, and the router builds a fresh client for every call
        (broker_router.py:229) — so a reader that placed no order sees a
        book it cannot name. `get_positions` says so beside the name
        instead of letting `ETORO:1001` travel as though it were a symbol:
        every consumer compares that name against the platform's spelling
        and reads a miss as "the position is gone", which books a live row
        CLOSED.
        """
        try:
            return int(instrument_id) in self._symbols
        except (TypeError, ValueError):
            return False

    # ── market data ────────────────────────────────────────────────────────

    def ping(self) -> bool:
        try:
            r = self._sess().get(self._v1_info("aggregate-portfolio"),
                                 headers=self._headers(),
                                 timeout=self.timeout)
            return r.status_code == 200
        except Exception as e:  # noqa: BLE001
            log.warning("eToro ping failed: %s", e)
            return False

    def ticker(self, symbol: str) -> dict:
        iid = self.instrument_id(symbol)
        r = self._sess().get(f"{BASE}/api/v1/market-data/instruments/rates",
                             params={"instrumentIds": str(iid)},
                             headers=self._headers(), timeout=self.timeout)
        r.raise_for_status()
        rates = (r.json() or {}).get("rates") or []
        if not rates:
            return {"lastPrice": "0", "symbol": symbol}
        p = rates[0]
        bid = float(p.get("bid") or 0)
        ask = float(p.get("ask") or 0)
        last = float(p.get("lastExecution") or 0)
        if not last:
            last = (bid + ask) / 2 if bid and ask else (bid or ask)
        return {"lastPrice": str(last), "symbol": symbol,
                "bid": str(bid), "ask": str(ask)}

    def klines(self, symbol: str, interval: str = "15m",
               limit: int = 200) -> list[list]:
        """Binance-style 12-element rows: [openTime, o, h, l, c, v,
        closeTime, quoteVol, trades, takerBase, takerQuote, ignore].
        Oldest first, like every other adapter. The runner reads only
        o/h/l/c/v; the tail is parity padding."""
        iid = self.instrument_id(symbol)
        enum = INTERVAL_MAP.get(interval, "FifteenMinutes")
        span_ms = INTERVAL_SECONDS.get(interval, 900) * 1000
        n = max(1, min(int(limit), CANDLES_MAX))
        r = self._sess().get(
            f"{BASE}/api/v1/market-data/instruments/{iid}/history/candles"
            f"/asc/{enum}/{n}",
            headers=self._headers(), timeout=self.timeout)
        r.raise_for_status()
        data = r.json() or {}
        candles = (data.get("candles") if isinstance(data, dict) else data) or []
        rows = []
        for c in candles:
            ts = _iso_to_ms(str(c.get("fromDate") or c.get("date") or ""))
            rows.append([
                ts,
                str(c.get("open", "0")), str(c.get("high", "0")),
                str(c.get("low", "0")), str(c.get("close", "0")),
                str(c.get("volume", 0)),
                ts + span_ms,
                "0", 0, "0", "0", "0",
            ])
        return rows

    def order_book(self, symbol: str, limit: int = 50) -> dict:
        """Synthetic single-level book from bid/ask — eToro exposes no
        depth on the public API. Same posture as OANDA."""
        tk = self.ticker(symbol)
        bid = float(tk.get("bid", "0") or 0)
        ask = float(tk.get("ask", "0") or 0)
        if not (bid and ask):
            return {"bids": [], "asks": []}
        n = min(limit, 20)
        return {
            "bids": [[str(round(bid * (1 - i * 0.0001), 6)), "1000000"]
                     for i in range(n)],
            "asks": [[str(round(ask * (1 + i * 0.0001), 6)), "1000000"]
                     for i in range(n)],
        }

    # ── account ────────────────────────────────────────────────────────────

    def account(self) -> dict:
        r = self._sess().get(self._v1_info("aggregate-portfolio"),
                             headers=self._headers(), timeout=self.timeout)
        r.raise_for_status()
        return r.json() or {}

    def balance_usdt(self) -> float:
        """Available cash in the ACCOUNT currency, not USDT — the name is the
        contract's, the unit is eToro's. Caller converts if it must."""
        try:
            return float(self.account().get("accountAvailableCash") or 0)
        except Exception as e:  # noqa: BLE001
            log.warning("eToro balance fetch failed: %s", e)
            return 0.0

    def net_liquidation(self) -> "tuple[float, str] | None":
        """(total value, currency) or None when unreadable — the same
        contract as IBKRTrader, so sync_broker_account can read it."""
        try:
            info = self.account()
        except Exception as e:  # noqa: BLE001
            log.warning("eToro net_liquidation failed: %s", e)
            return None
        try:
            value = float(info.get("accountTotalValue"))
        except (TypeError, ValueError):
            return None
        if value <= 0:
            return None
        return value, str(info.get("accountCurrency") or "")

    def _open_positions(self) -> list:
        r = self._sess().get(self._v1_info("portfolio"),
                             headers=self._headers(), timeout=self.timeout)
        r.raise_for_status()
        data = r.json() or {}
        return (data.get("positions")
                or (data.get("clientPortfolio") or {}).get("positions")
                or [])

    def get_positions(self) -> list[dict]:
        """Open positions — Phase-33 reconciliation shape. Raises on
        transport errors so reconcile counts the broker unavailable rather
        than assuming flat (the same rule as OANDA and IBKR)."""
        out = []
        for p in self._open_positions():
            qty = float(p.get("units") or 0)
            if qty == 0:
                continue
            iid = p.get("instrumentID") or p.get("instrumentId")
            row = {
                "symbol": self._symbol_for(iid),
                "qty": abs(qty),
                "side": "BUY" if p.get("isBuy", True) else "SELL",
                "position_id": str(p.get("positionID") or p.get("positionId")
                                   or ""),
            }
            if not self._named(iid):
                # THREE STATES. eToro holds this; what it is called HERE is
                # unmeasured. Not a symbol, and above all not an absence —
                # the readers that compare this name book a row CLOSED on a
                # miss.
                row["symbol_unresolved"] = True
            out.append(row)
        return out

    def broker_portfolio(self) -> "list[dict] | None":
        """Holdings as the broker values them, or None when unreadable —
        IBKRTrader's contract, for the portfolio views. Marks are not on
        the position row on eToro, so market_price is left 0 rather than
        invented; the aggregate endpoint has exposure per instrument if a
        caller needs it."""
        try:
            positions = self._open_positions()
        except Exception as e:  # noqa: BLE001
            log.warning("eToro broker_portfolio failed: %s", e)
            return None
        out = []
        for p in positions:
            qty = float(p.get("units") or 0)
            if qty == 0:
                continue
            out.append({
                "symbol": self._symbol_for(p.get("instrumentID")
                                           or p.get("instrumentId")),
                "sec_type": "CFD",
                "qty": abs(qty),
                "side": "BUY" if p.get("isBuy", True) else "SELL",
                "avg_cost": float(p.get("openRate") or 0),
                "market_price": 0.0,
                "market_value": 0.0,
                "unrealized_pnl": 0.0,
                "currency": "",
            })
        return out

    # ── execution (fact 1) ─────────────────────────────────────────────────

    def _await_fill(self, reference_id: str, attempts: int = FILL_ATTEMPTS,
                    delay: float = FILL_DELAY_S) -> Optional[dict]:
        """Poll orders:lookup by the x-request-id until a terminal status
        or attempts run out. Returns the last payload seen, or None."""
        import time
        last = None
        for _ in range(attempts):
            time.sleep(delay)
            try:
                r = self._sess().get(self._v2_lookup(),
                                     params={"referenceId": reference_id},
                                     headers=self._headers(),
                                     timeout=self.timeout)
                r.raise_for_status()
                last = r.json() or {}
            except Exception as e:  # noqa: BLE001
                log.warning("eToro fill poll failed for %s: %s",
                            reference_id, e)
                return last
            status = int(last.get("status") or last.get("statusId") or 0)
            if status in STATUS_FILLED or status in STATUS_REFUSED:
                return last
        return last

    def market_order(self, symbol: str, side: str, quantity: float,
                     **kwargs) -> dict:
        """Open a position. side BUY -> `buy`, SELL -> `sellShort`.

        stop_loss / take_profit kwargs become stopLossRate / takeProfitRate,
        absolute prices held AT THE BROKER on fill. The fill itself is read
        back by polling; an order still pending when polling stops is
        reported PENDING with executedQty 0, never as a fill.
        """
        rid = self._rid(kwargs.get("client_order_id"))
        body = {
            "action": "open",
            "transaction": "buy" if side == "BUY" else "sellShort",
            "symbol": str(symbol),
            "units": float(quantity),
            "leverage": 1,
        }
        stop_loss = kwargs.get("stop_loss")
        take_profit = kwargs.get("take_profit")
        protected = False
        if stop_loss:
            body["stopLossRate"] = float(stop_loss)
            body["stopLossType"] = "fixed"
        if take_profit:
            body["takeProfitRate"] = float(take_profit)
        if stop_loss and take_profit:
            protected = True

        r = self._sess().post(self._v2_exec_orders(), json=body,
                              headers=self._headers(rid),
                              timeout=self.timeout)
        try:
            r.raise_for_status()
        except Exception:
            log.error("eToro order failed: %s", r.text)
            raise
        accepted = r.json() or {}
        order_id = str(accepted.get("orderId") or "")
        reference = str(accepted.get("referenceId") or rid)

        polled = self._await_fill(reference) or {}
        status_id = int(polled.get("status") or polled.get("statusId") or 0)
        executions = polled.get("positionExecutions") or []
        first = executions[0] if executions else {}
        opening = first.get("openingData") or {}

        filled_units = 0.0
        avg_price = 0.0
        if status_id in STATUS_FILLED:
            try:
                filled_units = float(opening.get("units")
                                     or first.get("remainingUnits") or 0)
                avg_price = float(opening.get("avgPrice") or 0)
            except (TypeError, ValueError):
                filled_units, avg_price = 0.0, 0.0

        if status_id in STATUS_FILLED:
            status = "FILLED" if status_id == 3 else "PARTIALLY_FILLED"
        elif status_id in STATUS_REFUSED:
            status = STATUS_REFUSED[status_id]
        else:
            status = "PENDING"

        out = {
            "orderId": order_id,
            "symbol": symbol,
            "side": side,
            "executedQty": str(filled_units),
            "avgPrice": str(avg_price),
            "status": status,
            "raw": {"accepted": accepted, "lookup": polled,
                    "requestId": rid,
                    "clientOrderId": kwargs.get("client_order_id"),
                    "statusName": STATUS_NAMES.get(status_id, str(status_id))},
        }
        position_id = first.get("positionId") or first.get("positionID")
        if position_id:
            # THE HANDLE THE CLOSE NEEDS, on every fill. It used to be
            # reported only beside an accepted bracket (below), so exactly
            # the rows whose bracket eToro refused had nothing to close BY —
            # and at this venue a close without a position id cannot be sent
            # at all. Reported under its own key rather than as
            # protectiveTradeId, because it is not a claim about protection.
            out["positionId"] = str(position_id)
        if protected and filled_units > 0 and position_id:
            # Protection rides the POSITION, as on OANDA: nothing to cancel,
            # and the position id is the handle for moving the legs later.
            out["protectedOnFill"] = True
            out["protectiveOrders"] = []
            out["protectiveTradeId"] = str(position_id)
        return out

    # ── brackets ───────────────────────────────────────────────────────────

    def _patch_position(self, position_id: str, body: dict,
                        what: str) -> dict:
        try:
            r = self._sess().patch(self._v2(f"positions/{position_id}"),
                                   json=body, headers=self._headers(),
                                   timeout=self.timeout)
            if r.status_code in (200, 202):
                return {"ok": True, "reason": ""}
            return {"ok": False,
                    "reason": f"eToro refused ({r.status_code}): "
                              f"{r.text[:160]}"}
        except Exception as e:  # noqa: BLE001
            log.error("eToro %s(%s) failed: %s", what, position_id, e)
            return {"ok": False, "reason": str(e)}

    def modify_protective(self, trade_id: str, new_price: float) -> dict:
        """Move the stop on position `trade_id`. One field, so the target is
        untouched — a mover that sent both would be the bug it exists to
        prevent. 202 means accepted for asynchronous execution."""
        res = self._patch_position(str(trade_id),
                                   {"stopLossRate": float(new_price)},
                                   "modify_protective")
        res["price"] = float(new_price) if res["ok"] else None
        return res

    def modify_target(self, trade_id: str, new_price: float) -> dict:
        """Move the take-profit on position `trade_id`. The sibling of
        modify_protective, deliberately separate."""
        res = self._patch_position(str(trade_id),
                                   {"takeProfitRate": float(new_price)},
                                   "modify_target")
        res["price"] = float(new_price) if res["ok"] else None
        return res

    # ── closing ────────────────────────────────────────────────────────────

    def close_needs_position_id(self) -> bool:
        """ALWAYS true here, and it is not a netting profile.

        market_order sends {"action": "open", ...} and has no close branch —
        eToro's API separates the two — so an "opposite market order", which
        is what the engine's default close is, OPENS a position instead of
        closing one: a SELL becomes `sellShort` beside the long. The row then
        books CLOSED at that fill while the account holds DOUBLE, hedged,
        paying both spreads.

        The engine asks this before every close and closes by PositionId when
        the answer is yes, through close_position below — the market-close
        endpoint, which is the only thing at eToro that reduces a position.
        """
        return True

    def close_position(self, position_id: str, symbol: str,
                       units: Optional[float] = None) -> dict:
        """Submit a market close. Asynchronous: 200 means submitted. The
        closing order id is returned so a caller can confirm later; this
        client does not yet read that confirmation (see the module
        docstring on `fills`)."""
        body = {"InstrumentID": self.instrument_id(symbol)}
        if units:
            body["UnitsToDeduct"] = float(units)
        r = self._sess().post(
            self._v1_exec(f"market-close-orders/positions/{position_id}"),
            json=body, headers=self._headers(), timeout=self.timeout)
        r.raise_for_status()
        data = r.json() or {}
        ofc = data.get("orderForClose") or {}
        return {"orderId": str(ofc.get("orderID") or ofc.get("orderId")
                               or ""),
                "positionId": str(position_id), "status": "PENDING",
                "raw": data}
