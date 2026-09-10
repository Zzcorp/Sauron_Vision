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

import math as _math
from datetime import date as _date, datetime as _datetime
from datetime import timezone as _utc


def _num(v) -> float:
    """A price, or 0.0 - never a NaN.

    ib_insync initialises Ticker.last/bid/ask to float("nan"), and
    bool(nan) is True, so every `if t.last` guard in this file was
    passing on a value that is not a number. Downstream that became
    the string "nan" in a price field, and Decimal("NaN") does not
    compare quietly: `if last > 0` raises InvalidOperation rather
    than returning False.
    """
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if (_math.isnan(f) or _math.isinf(f)) else f


def _bar_millis(d) -> int:
    """Epoch ms for a bar stamp that may be a `date` OR a `datetime`.

    ib_insync returns a `datetime` for intraday bars and a plain
    `date` for 1 day / 1 week / 1 month. A `date` is NOT an instance
    of `datetime` - the inheritance runs the other way - so an
    isinstance(d, datetime) test stamped every daily and weekly bar
    0, and every consumer that filters on a sane timestamp dropped
    them. Daily sessions file at midnight UTC, the convention the
    rest of the platform already uses.
    """
    if isinstance(d, _datetime):
        if d.tzinfo is None:
            d = d.replace(tzinfo=_utc.utc)
        return int(d.timestamp() * 1000)
    if isinstance(d, _date):
        return int(_datetime(d.year, d.month, d.day,
                             tzinfo=_utc.utc).timestamp() * 1000)
    return 0

import logging
import re as _re
import time as _time
from datetime import datetime, timezone as dt_tz
from typing import Optional

log = logging.getLogger(__name__)


def _ensure_event_loop() -> None:
    """Give this thread an asyncio loop if it has none.

    ib_insync drives its socket from the thread's event loop. A Celery
    prefork child and a Django request thread both start without one, and
    without this the very first connect raised before any socket I/O —
    the failure the HQ ping and the sync beat each had to guard against
    on their own. One place now.

    DEFINED ABOVE THE IMPORT ON PURPOSE. See `_try_import_ib`.
    """
    import asyncio
    import warnings
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())


def _try_import_ib():
    """Import ib_insync with a loop already in place, or return None.

    ib_insync calls `asyncio.get_event_loop()` AT IMPORT TIME, so the import
    itself fails in a thread that has no loop — and it raises RuntimeError,
    not ImportError. This module's import guard caught that and recorded
    "ib_insync not installed", which was false and, worse, PERMANENT: the
    flag was a module global set once, so the first unlucky thread poisoned
    the entire process until it restarted.

    That is what an operator hit for a whole afternoon. Daphne runs a sync
    view in a ThreadPoolExecutor worker with no event loop; the manual-lane
    arming button was the first thing in that web process to touch this
    module; the import failed with

        There is no current event loop in thread 'ThreadPoolExecutor-33_0'

    and from then on every IBKR call from the web container degraded to a
    stub. The button reported "LIVE route unavailable — credentials missing,
    broker library absent, or the account disconnected" against a funded,
    logged-in, healthy Gateway, with the library installed and working — and
    a shell in the SAME container routed the same symbol to a live socket
    seconds later, because `manage.py shell` runs on the main thread.
    """
    _ensure_event_loop()
    try:  # pragma: no cover — import behaviour is environment-specific
        import ib_insync as mod  # type: ignore
        return mod
    except Exception as err:  # pragma: no cover
        log.info("ib_insync unavailable (%s) — IBKRTrader will degrade to "
                 "stubs. This is RETRIED on the next is_ibkr_available().",
                 err)
        return None


# Never fails at import time: the platform must work without ib_insync, since
# it is only needed once a user has wired IBKR credentials AND TWS is running.
_ib = _try_import_ib()
_IB_AVAILABLE = _ib is not None


# IB bar size codes — Binance kline interval → IBKR bar size string.
BAR_SIZE_MAP = {
    "1m": "1 min", "5m": "5 mins", "15m": "15 mins", "30m": "30 mins",
    "1h": "1 hour", "4h": "4 hours", "1d": "1 day", "1w": "1 week",
}


def purpose_client_id(base, purpose: str, slot: int = 0) -> int:
    """A distinct clientId per (account, purpose, process slot).

    See IBKRTrader.CLIENT_ID_PURPOSE_OFFSET and CLIENT_ID_SLOT_STRIDE. Bases
    must be distinct across accounts and below 100, which the admin form
    documents. `slot` is the process slot ibkr_sessions leases; 0 is the
    id a single process has always used, so nothing an operator set changes.
    """
    try:
        n = int(base)
    except (TypeError, ValueError):
        n = 1
    n += IBKRTrader.CLIENT_ID_PURPOSE_OFFSET.get(purpose, 0)
    if slot and purpose != "trade":
        # NEVER for trading. An order is visible only to the clientId that
        # placed it (ib_insync seeds its order table with reqOpenOrders,
        # and openOrder documents that another client's orders arrive only
        # for the Gateway's master id), so a per-process trading id would
        # make every stored orderId unreadable from a sibling process —
        # and the readers cannot tell "not mine" from "gone". The trading
        # session is exclusive instead; see bot_program/engine/
        # ibkr_sessions.py.
        n += IBKRTrader.CLIENT_ID_SLOT_STRIDE * int(slot)
    return n


def is_ibkr_available() -> bool:
    """True when `ib_insync` is importable. Does NOT check TWS connectivity.

    RETRIES a failed import instead of trusting a flag set once, because the
    thing that fails the import is a property of the CALLING THREAD, not of
    the installation: no event loop, no import. The first thread to touch
    this module in a Daphne process is a pool worker without one, and a
    module global set at that moment condemned every later request — on any
    thread, forever — to a paper stub.

    Cheap: Python caches the module in sys.modules, so a retry after the loop
    exists is a dict lookup, and a genuinely absent library re-raises the
    same ImportError each time.
    """
    global _ib, _IB_AVAILABLE
    if not _IB_AVAILABLE:
        _ib = _try_import_ib()
        _IB_AVAILABLE = _ib is not None
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
        # After a failed connect, do not try again before this monotonic
        # instant. A Gateway that is down answers every attempt with the
        # full timeout, and manage_positions asks once per open trade —
        # without a backoff one tick could spend its whole five minutes
        # waiting on a socket that will not open.
        self._next_connect_at = 0.0

    # How long a failed connect silences further attempts on this trader.
    CONNECT_BACKOFF_S = 30.0

    # ── connection management ─────────────────────────────────────────────

    @staticmethod
    def available() -> bool:
        return is_ibkr_available()

    def is_connected(self) -> bool:
        """True iff an API session is up right now — asks the socket, not
        the flag. A Gateway restart leaves the flag True and the socket dead."""
        if self._ib is None or not self._connected:
            return False
        try:
            return bool(self._ib.isConnected())
        except Exception:  # noqa: BLE001
            return False

    def _connect(self) -> bool:
        """Connect to TWS/IB Gateway, or reuse the session already open.

        Returns True on success. Reconnects when the Gateway has dropped
        the session (its nightly restart, a re-login, an operator kill);
        backs off for CONNECT_BACKOFF_S after a failure.
        """
        if not is_ibkr_available():
            return False
        if self._ib is not None and self._connected:
            if self.is_connected():
                return True
            # The object says connected, the socket says otherwise.
            log.warning("IBKR session to %s:%s clientId %s was dropped by the "
                        "Gateway — reconnecting", self.host, self.port,
                        self.client_id)
            self.disconnect()
        now = _time.monotonic()
        if now < self._next_connect_at:
            return False
        try:
            _ensure_event_loop()
            ib = _ib.IB()
            ib.connect(self.host, self.port, clientId=self.client_id,
                       timeout=self.timeout, readonly=False)
            self._ib = ib
            self._connected = True
            self._shield_orders_from_notices(ib)
            self._next_connect_at = 0.0
            return True
        except Exception as e:
            log.warning("IBKR connect to %s:%s clientId %s failed: %s "
                        "(next attempt in %.0fs)", self.host, self.port,
                        self.client_id, e, self.CONNECT_BACKOFF_S)
            self._ib = None
            self._connected = False
            self._next_connect_at = now + self.CONNECT_BACKOFF_S
            return False

    def disconnect(self) -> None:
        """Close the session and let the Gateway see it close.

        ib_insync's disconnect shuts the socket's write side synchronously
        (the FIN the Gateway needs to free this clientId) but closes the
        descriptor from the event loop; one zero-length turn of the loop
        finishes that instead of leaving it to the collector.
        """
        ib = self._ib
        if ib is not None and self._connected:
            try:
                ib.disconnect()
            except Exception:
                pass
            try:
                ib.sleep(0)
            except Exception:  # noqa: BLE001 — a closed or foreign loop
                pass
        self._ib = None
        self._connected = False

    # ── duck-typed broker interface ───────────────────────────────────────

    def ping(self) -> bool:
        if not is_ibkr_available():
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
            # `if t.last` was never False when it mattered - see _num.
            # The midpoint branch below was written for exactly the
            # case it could never reach: FX on IDEALPRO has no last
            # trade at all, only a bid and an ask, and any contract
            # without a market-data subscription leaves last unset. So
            # the one venue an operator would set as primary for forex
            # was the one that answered "nan".
            bid, ask = _num(getattr(t, "bid", None)), _num(getattr(t, "ask", None))
            last = _num(getattr(t, "last", None))
            if last <= 0 and bid > 0 and ask > 0:
                last = (bid + ask) / 2

            # DELAYED, RATHER THAN NOTHING — AND SAID SO.
            #
            # An account with no market-data subscription gets error 10089
            # ("Requested market data requires additional subscription for
            # API. Delayed market data is available.") and every field comes
            # back unset, so `last` is 0 and the manual lane refuses with "no
            # usable price mark — the quote feeds have nothing fresh". Which
            # is true and unhelpful: the operator has a funded, logged-in
            # Gateway and a valid contract, and the data IS available one flag
            # away. reqMarketDataType(3) asks for the free delayed feed.
            #
            # NEVER SILENTLY. A delayed mark is ~15 minutes old, and the
            # levels derived from it — the stop and the target — are the part
            # that matters: a market order still fills at the real price, but
            # a stop computed off a stale mark can be born on the wrong side
            # of the market. So the payload carries `delayed: True` and every
            # reader is free to refuse it. This module's whole doctrine is
            # that a number arrives with what it is; a price with no age
            # beside it is the lie removed everywhere else here.
            if last <= 0:
                try:
                    self._ib.reqMarketDataType(3)      # 3 = delayed
                    t = self._ib.reqMktData(contract, "", False, False)
                    self._ib.sleep(1.5)
                    d_bid = _num(getattr(t, "bid", None))
                    d_ask = _num(getattr(t, "ask", None))
                    d_last = _num(getattr(t, "last", None))
                    if d_last <= 0 and d_bid > 0 and d_ask > 0:
                        d_last = (d_bid + d_ask) / 2
                    if d_last > 0:
                        log.info("IBKR ticker(%s): no real-time subscription "
                                 "— using DELAYED mark %.4f", symbol, d_last)
                        return {
                            "lastPrice": str(d_last),
                            "symbol": symbol,
                            "bid": str(d_bid),
                            "ask": str(d_ask),
                            "delayed": True,
                        }
                finally:
                    # Back to real time for every later call on this session,
                    # so one unsubscribed symbol cannot quietly downgrade the
                    # whole process.
                    try:
                        self._ib.reqMarketDataType(1)
                    except Exception:  # noqa: BLE001
                        pass

            return {
                "lastPrice": str(last),
                "symbol": symbol,
                "bid": str(bid),
                "ask": str(ask),
                "delayed": False,
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
                ts = _bar_millis(b.date)
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
        """NetLiquidation as a bare float.

        The name is a legacy of the crypto bot and has to stay: it is the
        cross-broker duck type `capital_truth.broker_equity` looks for on
        every client. What changed is where the number comes from.

        This read used to go through `account()`, and `account_values()`
        exists precisely because `account()` carries two defects for its
        legacy callers — it discards `v.currency` and overwrites duplicate
        tags, so on a multi-currency account NetLiquidation was whichever row
        arrived LAST; and it passes account="" when no id is stored, which
        spans EVERY account under the login. Both defects landed here, on the
        one number that is the denominator of the entire per-config risk stack
        (sizing divides by it, the daily-loss floor is a percentage of it, the
        drawdown curve starts at it — see capital_truth's docstring). On a GBP
        ISA sitting under a login with other accounts, that made every risk
        limit a division by a figure of unknown currency from an unknown
        account, and the module whose whole job is to catch a mis-declared
        pool was the thing reading it.

        `net_liquidation` already solved this — BASE wins its tag, otherwise
        first-seen, and a read with no account id is refused rather than
        broadened. Delegating is the whole fix.

        Still 0.0 when unreadable, deliberately unchanged: `broker_equity`
        maps <= 0 to "unmeasured", and an unmeasured pool the operator is
        told about beats a confident number from the wrong account.
        """
        reading = self.net_liquidation()
        return reading[0] if reading else 0.0

    def account_values(self) -> "dict | None":
        """{tag: (value, currency)} for THIS account, or None when unreadable.

        Fixes two defects `account()` above still carries for its legacy
        callers:

        * It discards `v.currency` and overwrites on duplicate tags, so on
          a multi-currency account NetLiquidation is whichever currency row
          arrived LAST — nondeterministic, not merely unlabelled. Here the
          currency travels with every value; a BASE row always wins its
          tag, and otherwise the first row seen holds it, which is at least
          deterministic.
        * It passes account="" when no account id is stored, which spans
          EVERY account under the login. The order path refuses exactly
          that ambiguity (`_bind_order_account`); the balance path silently
          resolved it — so a panel labelled with one account could show
          another account's money. Refused here.

        None means UNREADABLE — never {} and never zeros. A caller that
        cannot tell "no reading" from "an empty account" will eventually
        tell an operator their money is gone.
        """
        if not self.account_id:
            log.warning("IBKR account_values(): no account id — a read "
                        "scoped to no account spans every account under "
                        "the login, refusing")
            return None
        if not self._connect():
            return None
        try:
            vals = self._ib.accountValues(account=self.account_id)
        except Exception as e:  # noqa: BLE001
            log.warning("IBKR account_values() failed: %s", e)
            return None
        out: dict = {}
        for v in vals:
            tag = str(getattr(v, "tag", "") or "")
            ccy = str(getattr(v, "currency", "") or "")
            if not tag:
                continue
            if tag not in out or ccy == "BASE":
                out[tag] = (str(getattr(v, "value", "") or ""), ccy)
        return out or None

    def net_liquidation(self) -> "tuple[float, str] | None":
        """(equity, currency) for this account, or None when unreadable.

        The currency is part of the reading, not decoration: a UK ISA is
        GBP, the platform's book defaults to EUR, and this codebase has no
        FX conversion anywhere by design — so a bare float here becomes a
        number printed behind the wrong symbol somewhere downstream.
        """
        info = self.account_values()
        if not info:
            return None
        for tag in ("NetLiquidation", "AvailableFunds", "TotalCashValue"):
            row = info.get(tag)
            if not row:
                continue
            value, ccy = row
            try:
                n = float(value)
            except (TypeError, ValueError):
                continue
            if n > 0:
                return n, (ccy if ccy and ccy != "BASE" else "")
        return None

    def broker_portfolio(self) -> "list[dict] | None":
        """The account's holdings AS THE BROKER VALUES THEM, or None.

        `ib.portfolio()` rather than `ib.positions()`: this is the read
        with marks on it — marketPrice, marketValue, averageCost,
        unrealizedPNL, each row carrying its own currency — which is what
        a portfolio VIEW needs and what `get_positions()` deliberately
        does not fetch. `get_positions()` keeps its exact shape and its
        raise-on-unreachable contract untouched: reconcile and the
        close-retry path depend on both.

        None means unreadable, and an empty account id is refused for the
        same reason as `account_values()` — an unscoped read spans the
        whole login. Symbols follow `get_positions()`'s convention so a
        row here can be matched against AssetBotTrade.symbol: CASH pairs
        are rebuilt ("EUR" -> "EURUSD"), everything else is the contract
        symbol uppercased.
        """
        if not self.account_id:
            log.warning("IBKR broker_portfolio(): no account id — refusing "
                        "an unscoped read of the whole login")
            return None
        if not self._connect():
            return None
        try:
            items = self._ib.portfolio()
        except Exception as e:  # noqa: BLE001
            log.warning("IBKR broker_portfolio() failed: %s", e)
            return None
        out = []
        for it in items:
            acct = str(getattr(it, "account", "") or "")
            if acct and acct != self.account_id:
                continue
            qty = float(getattr(it, "position", 0) or 0)
            if qty == 0:
                continue
            contract = getattr(it, "contract", None)
            sec_type = str(getattr(contract, "secType", "") or "")
            symbol = str(getattr(contract, "symbol", "") or "").upper()
            if sec_type == "CASH":
                symbol += str(getattr(contract, "currency", "") or "").upper()
            out.append({
                "symbol": symbol,
                "sec_type": sec_type,
                "qty": qty,
                "side": "BUY" if qty > 0 else "SELL",
                "avg_cost": float(getattr(it, "averageCost", 0) or 0),
                "market_price": float(getattr(it, "marketPrice", 0) or 0),
                "market_value": float(getattr(it, "marketValue", 0) or 0),
                "unrealized_pnl": float(getattr(it, "unrealizedPNL", 0) or 0),
                "currency": str(getattr(contract, "currency", "") or ""),
            })
        return out

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

    # Codes TWS sends about an order it has ACCEPTED and adjusted — a
    # comment, not a verdict. 10349: "Order TIF was set to DAY based on
    # order preset". The text pattern catches its siblings (an outsideRth
    # or a price-cap preset says the same sentence with another noun) and
    # the entries the shield below writes itself.
    ORDER_NOTICE_CODES = frozenset({10349})
    _ORDER_NOTICE_TEXT = _re.compile(
        r"\bbased on (?:the )?order preset\b|^Notice \d+, reqId \d+:",
        _re.IGNORECASE)

    @classmethod
    def _is_order_notice(cls, code, text) -> bool:
        """True for a message that comments on an order without killing it."""
        try:
            code = int(code or 0)
        except (TypeError, ValueError):
            code = 0
        if code in cls.ORDER_NOTICE_CODES:
            return True
        return bool(cls._ORDER_NOTICE_TEXT.search(str(text or "")))

    def _shield_orders_from_notices(self, ib) -> None:
        """Keep an accepted order alive in memory when TWS merely comments.

        ib_insync 0.9.86 knows eight warning codes; every other code that
        arrives with an order's reqId is treated as fatal — the trade is
        marked Cancelled IN MEMORY (the broker cancels nothing), its
        cancelledEvent fires, and because the trade now counts as done,
        every later error on that order is dropped from its log. TWS 10.4x
        sends 10349, "Order TIF was set to DAY based on order preset", for
        an order it has ACCEPTED and adjusted. On 2026-09-07 the first live
        order on this deployment died of exactly that: a notice read as a
        rejection, and the real answer, if the broker gave one, thrown
        away before anyone could read it.

        The wrapper's `error` is replaced on the instance — the decoder
        looks it up by name on every message — with one that passes every
        code it does not recognise straight through and, for a notice,
        logs it, records it on the trade WITHOUT touching its status, and
        still raises errorEvent for anyone listening. Nothing else about
        the library's handling changes, and a library that one day
        classifies these codes itself is not disturbed: the shield only
        ever pre-empts the path it would have taken.
        """
        wrapper = getattr(ib, "wrapper", None)
        if wrapper is None or getattr(wrapper, "_sv_notice_shield", False):
            return
        original = wrapper.error
        trader = self

        def error(reqId, errorCode, errorString, *rest, **kw):
            if not trader._is_order_notice(errorCode, errorString):
                return original(reqId, errorCode, errorString, *rest, **kw)
            msg = f"Notice {errorCode}, reqId {reqId}: {errorString}"
            log.info("IBKR %s", msg)
            try:
                trade = wrapper.trades.get((wrapper.clientId, reqId))
            except Exception:  # noqa: BLE001 — a stand-in without trades
                trade = None
            if trade is not None:
                try:
                    trade.log.append(_ib.TradeLogEntry(
                        wrapper.lastTime, trade.orderStatus.status, msg, 0))
                except Exception:  # noqa: BLE001 — the entry is a courtesy
                    pass
            try:
                contract = getattr(wrapper, "_reqId2Contract", {}).get(reqId)
                ib.errorEvent.emit(reqId, errorCode, errorString, contract)
            except Exception:  # noqa: BLE001 — listeners are optional
                pass
            return None

        wrapper.error = error
        wrapper._sv_notice_shield = True

    @classmethod
    def _substantive_log(cls, trade) -> list:
        """The trade-log messages that say something went WRONG."""
        out = []
        for entry in (getattr(trade, "log", None) or []):
            message = str(getattr(entry, "message", "") or "")
            if not message:
                continue
            if cls._is_order_notice(getattr(entry, "errorCode", 0), message):
                continue
            out.append(message)
        return out

    @classmethod
    def _dead_order_reason(cls, trade, filled_qty,
                           children=()) -> "Optional[str]":
        """A dead, unfilled order's reason string — or None while alive.

        Cancelled/ApiCancelled/Inactive with zero filled is a rejection
        whatever TWS chooses to call it; the reason is fished out of the
        trade log because the status alone says only that it died.

        NOTICES ARE NOT REASONS. The first version joined every log line,
        so the one readable line on the 2026-09-07 order — "Order TIF was
        set to DAY based on order preset" — was presented as why it died,
        and it was a comment on an order TWS had accepted. The rejection
        that kills a bracket is often on a CHILD (a stop TWS will not take
        takes the parent down with it), so the children's logs are read
        when the parent's says nothing; and when nothing says anything the
        string says THAT, and where to look, rather than dressing the
        status up as a cause.
        """
        status = getattr(trade.orderStatus, "status", "") or ""
        if status not in cls._DEAD_STATES:
            return None
        if filled_qty:
            return None
        notes = cls._substantive_log(trade)
        if not notes:
            for child in (children or []):
                cid = getattr(getattr(child, "order", None), "orderId", "")
                for line in cls._substantive_log(child):
                    notes.append(f"leg {cid}: {line}" if cid else line)
        if not notes:
            oid = getattr(getattr(trade, "order", None), "orderId", "")
            notes = [f"{status} with no message on this order — the "
                     f"container log (ib_insync.wrapper) holds any error "
                     f"TWS sent for reqId {oid}"]
        return f"broker_rejected: {'; '.join(notes)[:300]}"

    # Every concurrent connection to one Gateway needs its OWN clientId.
    # Connect twice with the same one and IBKR REFUSES the newcomer with
    # error 326 — it does not evict the earlier holder, whatever older
    # comments here said — and ib_insync reports that refusal as a plain
    # connect timeout. Sauron opens sockets from at least three places at
    # once — the trading router on a worker, the bar/quote feed on another
    # worker, and an operator clicking "test connection" on the web
    # container — and all three once passed the configured id verbatim.
    # So a routine bar refresh could hold the id the trader needed, and a
    # test-connection click could fail against a slot a worker held, in a
    # way that read as a flaky broker rather than as us.
    #
    # The configured number is a BASE and keeps its old meaning for
    # trading, so nothing an operator already set has to change. Purposes
    # are spaced 100 apart, which leaves room for bases 1..99 — far more
    # accounts than the five Gateway slots compose ships. On top of that,
    # ibkr_sessions leases each PROCESS a slot and shifts the whole band
    # by CLIENT_ID_SLOT_STRIDE per slot, so the two prefork children and
    # the web workers hold different ids at the same time.
    CLIENT_ID_PURPOSE_OFFSET = {"trade": 0, "data": 100, "probe": 200}
    CLIENT_ID_SLOT_STRIDE = 300     # wider than bases (<100) + purposes (<300)
    CLIENT_ID_SLOTS = 8             # concurrent processes per Gateway

    def _bind_order_account(self, order) -> "Optional[str]":
        """Stamp `order.account` with this trader's account, or name the
        reason the order must NOT be sent.

        With account_id set, every order says where it belongs — the
        session default never decides. Without one, a single-account
        session is unambiguous and passes; a multi-account session is
        refused: an unstamped BUY lands on whichever account TWS calls
        primary, and an unstamped CLOSE against the wrong book does not
        close anything — it opens a fresh position there. If the managed
        list itself cannot be read, the order passes with a loud log:
        every current deployment is single-account, and bricking those
        on a flaky library call would strand real exposure.
        """
        if self.account_id:
            order.account = self.account_id
            return None
        try:
            managed = [a for a in (self._ib.managedAccounts() or []) if a]
        except Exception as e:  # noqa: BLE001 — see docstring
            log.warning("IBKR managedAccounts() unreadable (%s) — "
                        "sending unstamped order on the single-account "
                        "assumption", e)
            return None
        if len(managed) > 1:
            return (f"ambiguous_account: session manages {len(managed)} "
                    f"accounts and this trader has no account_id — refusing "
                    f"to trade on the session default")
        return None

    def _min_tick_for(self, contract) -> float:
        """The contract's REAL minimum price variation, or 0 if unknown.

        Guessing decimal places was wrong for almost everything that is
        not a US equity: IDEALPRO forex ticks 0.00005 (0.005 on JPY
        crosses), ES ticks 0.25, CL 0.01. A price off the tick is
        rejected by TWS with error 110 — and a rejected stop is a naked
        position that still LOOKS protected, which is the one outcome
        this whole module exists to prevent. minTick lives on
        ContractDetails, not on Contract, so qualifyContracts cannot
        supply it.
        """
        try:
            details = self._ib.reqContractDetails(contract)
        except Exception as e:  # noqa: BLE001 — an unknown tick is handled
            log.warning("IBKR contract details unreadable (%s)", e)
            return 0.0
        if not details:
            return 0.0
        try:
            return float(getattr(details[0], "minTick", 0) or 0)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _snap_to_tick(price, min_tick: float, *, widen: bool) -> "Optional[float]":
        """Snap a price onto a multiple of `min_tick`, never tightening.

        `widen` says which way to break the tie: a stop rounds AWAY from
        the position (more room, never less), a target rounds toward it
        (achievable). Decimal, because float arithmetic lands prices a
        hair off the tick and TWS counts hairs.
        """
        from decimal import Decimal, ROUND_DOWN, ROUND_UP
        try:
            p = Decimal(str(float(price)))
        except (TypeError, ValueError, ArithmeticError):
            return None
        if p <= 0:
            return None
        if min_tick <= 0:
            return None          # unknown tick — the caller must refuse
        tick = Decimal(str(min_tick))
        mode = ROUND_DOWN if widen else ROUND_UP
        snapped = (p / tick).quantize(Decimal(1), rounding=mode) * tick
        if snapped <= 0:
            return None
        return float(snapped)

    def _bracket_orders(self, action: str, quantity: float, symbol: str,
                        stop_loss, take_profit,
                        min_tick: float = 0.0) -> "Optional[list]":
        """Parent MARKET + protective STP and LMT children, or None.

        IBKR's own bracket helper builds the OCA group and the parent
        linkage, which is what makes the two children cancel each other
        when either fills. `transmit` discipline is the whole game here:
        every order but the LAST must be transmit=False, or TWS starts
        working a parent whose protection has not arrived yet — the
        exact unprotected window this method exists to close. The helper
        sets that; we only re-assert it so a library change cannot
        silently open the window again.
        """
        exit_action = "SELL" if action == "BUY" else "BUY"
        # A long's stop sits BELOW and rounds down; its target sits above
        # and rounds down toward it. Mirrored for a short. Either way the
        # snap never moves a stop closer to the entry.
        sl = self._snap_to_tick(stop_loss, min_tick,
                                widen=(action == "BUY"))
        tp = self._snap_to_tick(take_profit, min_tick,
                                widen=(action != "BUY"))
        if sl is None or tp is None:
            log.warning("IBKR %s: cannot price protection on a %s tick "
                        "(sl=%s tp=%s) — refusing the bracket rather than "
                        "sending legs TWS will reject",
                        symbol, min_tick or "unknown", stop_loss, take_profit)
            return None
        # A stop on the wrong side of the entry is not protection, it is
        # an instant exit at the worst price on the sheet.
        if action == "BUY" and not (tp > sl):
            return None
        if action == "SELL" and not (tp < sl):
            return None
        try:
            bracket = self._ib.bracketOrder(
                action, abs(float(quantity)),
                limitPrice=None, takeProfitPrice=tp, stopLossPrice=sl,
            )
        except Exception as e:  # noqa: BLE001 — see the fallback below
            log.warning("IBKR bracketOrder() unavailable (%s) — building "
                        "the legs by hand", e)
            # The parent's orderId is 0 until placeOrder mints one, and a
            # child carrying parentId=0 is not a child at all: TWS holds
            # the untransmitted parent forever and releases the STOP as a
            # standalone order, which then OPENS a position when it fires
            # against a book that never got the entry. Mint the id here
            # or refuse — an unprotected entry the bot still manages is
            # far safer than an orphan stop nobody owns.
            try:
                parent_id = int(self._ib.client.getReqId())
            except Exception as exc:  # noqa: BLE001
                log.error("IBKR %s: no order id for a hand-built bracket "
                          "(%s) — refusing to emit orphan legs", symbol, exc)
                return None
            if not parent_id:
                return None
            parent = _ib.MarketOrder(action, abs(float(quantity)))
            parent.orderId = parent_id
            parent.transmit = False
            self._entry_good_for_the_day(parent)
            oca = f"SV{parent_id}"
            tp_order = _ib.LimitOrder(exit_action, abs(float(quantity)), tp)
            tp_order.parentId = parent_id
            tp_order.ocaGroup, tp_order.ocaType = oca, 1
            tp_order.transmit = False
            sl_order = _ib.StopOrder(exit_action, abs(float(quantity)), sl)
            sl_order.parentId = parent_id
            sl_order.ocaGroup, sl_order.ocaType = oca, 1
            sl_order.transmit = True
            self._protection_outlives_the_session([tp_order, sl_order])
            return [parent, tp_order, sl_order]
        orders = list(bracket)
        if not orders:
            return None
        self._protection_outlives_the_session(orders[1:])
        # The helper builds a LIMIT parent, so it carries an lmtPrice —
        # here that price is None (we passed limitPrice=None) and TWS
        # rejects a market order that still carries a limit field. Clear
        # it with the type rather than leaving the two disagreeing.
        orders[0].orderType = "MKT"
        self._entry_good_for_the_day(orders[0])
        for attr in ("lmtPrice", "auxPrice"):
            if hasattr(orders[0], attr):
                try:
                    setattr(orders[0], attr, 0.0)
                except Exception:  # noqa: BLE001 — a frozen field is fine
                    pass
        for o in orders[:-1]:
            o.transmit = False
        orders[-1].transmit = True
        return orders

    # Time-in-force for the protective legs. ib_insync leaves Order.tif
    # empty and TWS reads empty as DAY — so the stop and the target that
    # rested all afternoon EXPIRED at the session close while the row went
    # on saying `protected`, and protected rows skip every bot-side SL/TP
    # check. Every shipped default holds positions for days (see
    # asset_models.DEFAULT_MAX_HOLD_HOURS): from the first close onward
    # the position was naked and nothing was watching. Good-till-cancelled
    # is what OANDA and Alpaca already give the same legs.
    PROTECTIVE_LEG_TIF = "GTC"

    # The entry's own time-in-force, said out loud. An EMPTY tif is not
    # "DAY": it is "whatever the account's order preset says", and TWS
    # announces the substitution with notice 10349 — which the library
    # then read as a rejection (see _shield_orders_from_notices). A
    # market entry is good for the day: it fills now or is held for the
    # open, and an entry that could still fill a week later at any price
    # is not one anyone asked for.
    ENTRY_TIF = "DAY"

    def _entry_good_for_the_day(self, order) -> None:
        try:
            order.tif = self.ENTRY_TIF
        except Exception:  # noqa: BLE001 — a frozen stand-in is fine
            pass

    def _protection_outlives_the_session(self, legs) -> None:
        """Stamp the protective legs GTC; the entry carries ENTRY_TIF.

        A STAMP, not a fact: what TWS keeps is read back after placement
        by _protection_downgraded, because an account preset can rewrite
        it and the library never shows the rewrite on the trade.
        """
        for leg in legs:
            try:
                leg.tif = self.PROTECTIVE_LEG_TIF
            except Exception:  # noqa: BLE001 — a frozen stand-in is fine
                pass

    def _accepted_tifs(self, order_ids) -> "Optional[dict]":
        """{orderId: TIF} for our open orders AS TWS REPORTS THEM, or None.

        reqOpenOrders() answers with TWS's own Order objects for this
        client's open orders — the one place the accepted `tif` is
        visible: ib_insync's openOrder callback copies permId, quantity,
        prices, type and ref onto a trade it already tracks, and not tif,
        so `trade.order.tif` reads whatever we stamped forever. One round
        trip per bracket. None means the socket could not be asked, which
        is not the same as "as stamped".
        """
        wanted = {str(i) for i in (order_ids or []) if i}
        if not wanted:
            return {}
        try:
            reported = self._ib.reqOpenOrders() or []
        except Exception as e:  # noqa: BLE001
            log.error("IBKR reqOpenOrders failed while verifying "
                      "protection: %s", e)
            return None
        out = {}
        for o in reported:
            oid = str(getattr(o, "orderId", "") or "")
            if oid in wanted:
                out[oid] = str(getattr(o, "tif", "") or "").upper()
        return out

    def _protection_downgraded(self, symbol, legs, stop_leg_id) -> str:
        """Why the resting stop is NOT good-till-cancelled — or ''.

        An IBKR order preset rewrites API orders on the way in ("Order TIF
        was set to DAY based on order preset"). A DAY stop dies at the
        session close while the row says `protected`, and protected rows
        skip every bot-side SL/TP check: the exact naked overnight
        position commit 9e2bc10 exists to prevent, reintroduced by one
        account setting. The stop is the leg that matters; a rewritten
        target is logged and does not decide.
        """
        accepted = self._accepted_tifs(legs)
        if accepted is None:
            log.warning("IBKR %s: could not read the legs' time-in-force "
                        "back from TWS — keeping the bracket as stamped; "
                        "the vanished-stop check watches it from here",
                        symbol)
            return ""
        wrong = {oid: tif for oid, tif in accepted.items()
                 if tif and tif != self.PROTECTIVE_LEG_TIF}
        if not wrong:
            return ""
        held = ", ".join(f"leg {oid} is {tif}"
                         for oid, tif in sorted(wrong.items()))
        stop_wrong = (str(stop_leg_id) in wrong) if stop_leg_id else True
        if not stop_wrong:
            log.warning("IBKR %s: %s — the stop is %s, so the position "
                        "stays protected", symbol, held,
                        self.PROTECTIVE_LEG_TIF)
            return ""
        return (f"the broker kept the protection as {held}, not "
                f"{self.PROTECTIVE_LEG_TIF}: an IBKR order preset rewrites "
                f"API orders — set the preset's Time in Force to GTC "
                f"(TWS: Global Configuration → Presets)")

    # States ib_insync reports for an order TWS is still working.
    _WORKING_STATES = ("PendingSubmit", "PreSubmitted", "Submitted",
                       "ApiPending")
    # `Inactive` is IBKR's word for an order it accepted and then refused or
    # parked (margin 201, an off-tick price, an order held outside RTH it
    # will not release). ib_insync does NOT count it as done, so such an
    # order sits in openTrades() indefinitely; treating that as "working"
    # would have a refused order read as live forever.
    _DEAD_STATES = ("Cancelled", "ApiCancelled", "Inactive")
    # ib_insync writes this SYNCHRONOUSLY inside cancelOrder (ib.py:697-706)
    # and it is not a done state, so the order stays in openTrades until TWS
    # confirms. It is neither working nor dead: the cancel has been sent and
    # the order can still fill in the race.
    _CANCELLING_STATES = ("PendingCancel",)
    # How long to wait for TWS to confirm a cancellation before answering.
    CANCEL_CONFIRM_WAIT_S = 1.0

    @classmethod
    def _classify_order(cls, status: str, filled: float, *, in_open: bool) -> str:
        """One place decides what a TWS order status means.

        Both of order_status's sources need the same reading, and the two
        drifting apart is how `Inactive` — a REFUSAL — came to read as
        "working" from one table and "dead" from the other.

        `in_open` says the order was still in openTrades(): from that table
        an unrecognised status is a live order (it has not reached a done
        state), while from the session's whole trade list it is genuinely
        something this code does not model.
        """
        if filled > 0 and (status == "Filled" or status in cls._DEAD_STATES):
            return "filled"
        if status == "Filled":
            return "filled"
        if status in cls._DEAD_STATES:
            return "dead"
        if status in cls._CANCELLING_STATES:
            return "cancelling"
        if status in cls._WORKING_STATES:
            return "working"
        return "working" if in_open else "unknown"

    def order_status(self, order_id: str) -> "Optional[dict]":
        """Where one order stands now: working, filled, dead, or unknown.

        Returns {"state", "status", "filled", "avgPrice", "remaining"} or
        None when the socket could not be asked. Looks at the orders TWS is
        working, then at this session's own trades (a fill or a cancel that
        arrived since placement).

        Then — and this is the source that makes a cross-tick fill
        readable at all — the day's EXECUTIONS. The trading session is
        released after every task, so the tick that polls a queued order is
        always on a socket opened after the order was placed, and a filled
        order is in neither of the tables above. `reqExecutions` re-fetches
        the day's executions for this clientId, and ib_insync's decoder
        DOES set `execution.orderId` (objects.Execution.orderId, decoded at
        decoder.py:415) — unlike the completedOrder message, which carries
        permId only and is therefore deliberately not consulted: a source
        that can never match is worse than none, because it reads as having
        been checked.

        "unknown" means none of the three knew the id. It is a REAL answer
        with two causes the API cannot separate: the order belongs to
        another clientId (an order is visible only to the session that
        placed it), or it is older than today's executions.
        """
        if not self._connect():
            return None
        wanted = str(order_id)

        def _pick(trades):
            for tr in trades or []:
                oid = str(getattr(getattr(tr, "order", None), "orderId", "")
                          or "")
                if oid == wanted:
                    return tr
            return None

        try:
            tr = _pick(self._ib.openTrades())
            if tr is not None:
                st = tr.orderStatus
                status = str(st.status or "")
                filled = _num(st.filled)
                # openTrades() filters only ib_insync's DoneStates
                # (Filled / Cancelled / ApiCancelled), so being in it is not
                # the same as being live: a refused order sits there as
                # Inactive and a cancelled-but-unconfirmed one as
                # PendingCancel. Classify by the status, not by membership.
                state = self._classify_order(status, filled, in_open=True)
                return {"state": state, "status": status, "filled": filled,
                        "avgPrice": _num(st.avgFillPrice),
                        "remaining": _num(st.remaining)}
            for source in (self._ib.trades,):
                try:
                    tr = _pick(source())
                except Exception as e:  # noqa: BLE001 — one source failing
                    log.debug("IBKR order_status(%s): %s", wanted, e)
                    tr = None
                if tr is None:
                    continue
                st = tr.orderStatus
                status = str(st.status or "")
                filled = _num(st.filled)
                state = self._classify_order(status, filled, in_open=False)
                return {"state": state, "status": status, "filled": filled,
                        "avgPrice": _num(st.avgFillPrice),
                        "remaining": _num(st.remaining)}
            # The day's executions: the only place a fill placed on an
            # EARLIER socket of this same clientId can still be found.
            ex = self._executions_for(wanted)
            if ex is not None:
                return ex
            return {"state": "unknown", "status": "", "filled": 0.0,
                    "avgPrice": 0.0, "remaining": 0.0}
        except Exception as e:  # noqa: BLE001
            log.error("IBKR order_status(%s) failed: %s", wanted, e)
            return None

    def _executions_for(self, order_id: str) -> "Optional[dict]":
        """What this clientId's executions say about one order, or None.

        Sums every execution carrying that orderId — a market order can
        print in several — and returns the size-weighted average price, so
        a partially filled parent reads as the units that actually printed
        rather than as all or nothing. Covers today only, which is what
        IBKR's execution report covers.

        `reqExecutions` is asked rather than `fills()`: a session opened
        after the order was placed has an empty fill table until it does,
        and that is exactly the case this method exists for.
        """
        try:
            flt = _ib.ExecutionFilter()
            try:
                fills = self._ib.reqExecutions(flt) or []
            except Exception:  # noqa: BLE001 — older signatures take nothing
                fills = self._ib.reqExecutions() or []
            wanted = str(order_id)
            shares = 0.0
            notional = 0.0
            for fill in fills:
                execution = getattr(fill, "execution", None) or fill
                if str(getattr(execution, "orderId", "") or "") != wanted:
                    continue
                q = _num(getattr(execution, "shares", 0))
                p = _num(getattr(execution, "price", 0))
                if q <= 0:
                    continue
                shares += q
                notional += q * p
            if shares <= 0:
                return None
            return {"state": "filled", "status": "Filled", "filled": shares,
                    "avgPrice": (notional / shares) if shares else 0.0,
                    "remaining": 0.0, "source": "executions"}
        except Exception as e:  # noqa: BLE001
            log.warning("IBKR executions lookup for %s failed: %s",
                        order_id, e)
            return None

    def position_avg_cost(self, symbol: str,
                          sec_types=None) -> "Optional[dict]":
        """{"qty", "side", "avg_cost", "sec_type"} for the account's position
        in `symbol`, {} when flat, None when unreadable.

        `sec_types` restricts the match — pass ("STK",) for a stock row so
        an option or future on the same underlying cannot answer for it.
        IBKR reports an OPT position under its UNDERLYING symbol, so a
        symbol-only match let an AAPL call answer for AAPL shares.

        avg_cost is PER UNIT. IBKR's avgCost is per contract for anything
        with a multiplier (options, futures) — price x multiplier — so it
        is divided back out here rather than left for a caller to
        remember; forgetting it once put a 250,000 entry price on a 5,000
        future.
        """
        if not self._connect():
            return None
        try:
            want = symbol.upper()
            allowed = {str(s).upper() for s in (sec_types or ())}
            for pos in self._ib.positions(self.account_id or ""):
                qty = float(pos.position or 0)
                if qty == 0:
                    continue
                contract = pos.contract
                sec_type = str(getattr(contract, "secType", "") or "").upper()
                sym = str(getattr(contract, "symbol", "")).upper()
                if sec_type == "CASH":
                    sym += str(getattr(contract, "currency", "")).upper()
                if sym != want:
                    continue
                if allowed and sec_type and sec_type not in allowed:
                    continue
                avg = _num(getattr(pos, "avgCost", 0.0))
                mult = 1.0
                try:
                    mult = float(str(getattr(contract, "multiplier", "") or 1)
                                 or 1)
                except (TypeError, ValueError):
                    mult = 1.0
                if mult > 1:
                    avg = avg / mult
                return {"qty": abs(qty),
                        "side": "BUY" if qty > 0 else "SELL",
                        "avg_cost": avg, "sec_type": sec_type,
                        "multiplier": mult}
            return {}
        except Exception as e:  # noqa: BLE001
            log.error("IBKR position_avg_cost(%s) failed: %s", symbol, e)
            return None

    def resting_order_ids(self) -> "Optional[set]":
        """The orderIds TWS currently holds as working, or None if unreadable.

        One openTrades() read, so a caller walking every protected row
        pays for the snapshot once per tick. A leg missing from this set
        is no longer protecting anything: it filled, was cancelled at TWS,
        or expired. None means the socket could not be asked — and "could
        not look" must never be read as "gone".
        """
        if not self._connect():
            return None
        try:
            out = set()
            for trade in (self._ib.openTrades() or []):
                status = str(getattr(getattr(trade, "orderStatus", None),
                                     "status", "") or "")
                # A leg being cancelled is not resting protection either.
                if status in self._DEAD_STATES or \
                        status in self._CANCELLING_STATES:
                    continue
                oid = str(getattr(getattr(trade, "order", None),
                                  "orderId", "") or "")
                if oid:
                    out.add(oid)
            return out
        except Exception as e:  # noqa: BLE001
            log.error("IBKR resting_order_ids failed: %s", e)
            return None

    @classmethod
    def _leg_is_resting(cls, trade) -> bool:
        """True when TWS has ACCEPTED this protective leg.

        ib_insync's active vocabulary is PendingSubmit / PreSubmitted /
        Submitted; Cancelled, ApiCancelled and Inactive mean the leg was
        refused (error 110 off-tick, 201 margin, an order type the
        exchange will not take). An error line in the trade log says the
        same thing earlier.
        """
        status = str(getattr(getattr(trade, "orderStatus", None),
                             "status", "") or "")
        if status in ("Cancelled", "ApiCancelled", "Inactive"):
            return False
        for entry in (getattr(trade, "log", None) or []):
            code = getattr(entry, "errorCode", None)
            if code and not cls._is_order_notice(
                    code, getattr(entry, "message", "")):
                return False
        # PROVEN, not merely un-refused. `bool(status)` accepted
        # PendingSubmit, which ib_insync assigns LOCALLY the instant
        # placeOrder is called - before TWS has said anything at all.
        # A leg still in that state one second later has not been
        # accepted by anyone, and claiming `protectedOnFill` for it
        # turns OFF bot-side SL/TP management over a position whose
        # stop may never have existed. PreSubmitted, Submitted and
        # Filled are the states TWS itself sends. Being strict here
        # costs only a fallback to bot-side management, which is the
        # safe direction to be wrong in.
        return status in ("PreSubmitted", "Submitted", "Filled")

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
            # Broker-side protection, the same contract OANDA and Alpaca
            # keep: the stop and the target rest AT IBKR, so the position
            # survives this process dying. Without it the only thing
            # standing between a live position and an unbounded loss is a
            # five-minute tick loop on a machine that can reboot.
            stop_loss = kwargs.get("stop_loss")
            take_profit = kwargs.get("take_profit")
            bracket = None
            if stop_loss and take_profit:
                bracket = self._bracket_orders(
                    action, quantity, symbol, stop_loss, take_profit,
                    min_tick=self._min_tick_for(contract))
                if bracket is None:
                    log.warning("IBKR %s: protective levels unusable "
                                "(sl=%s tp=%s) — sending the entry "
                                "UNPROTECTED, bot-side management owns it",
                                symbol, stop_loss, take_profit)
            if bracket:
                orders = bracket
            else:
                orders = [_ib.MarketOrder(action, abs(float(quantity)))]
                self._entry_good_for_the_day(orders[0])
            # EVERY leg carries the account. A child that lands on the
            # session default is a stop resting against a book that does
            # not hold the position — it opens one when it fires.
            # IBKR was the only live broker here dropping
            # `client_order_id` on the floor: OANDA sends it as
            # clientExtensions.id, Alpaca as client_order_id, Binance
            # as newClientOrderId. IBKR offers no server-enforced
            # dedup key, so `orderRef` buys traceability rather than
            # idempotency - every order at TWS can be traced to the
            # row that sent it, which is what makes a duplicate
            # visible at all. Preventing one stays the row-claim
            # layer's job.
            coid = str(kwargs.get("client_order_id") or "")
            for o in orders:
                if coid:
                    try:
                        o.orderRef = coid[:60]
                    except Exception:  # pragma: no cover - defensive
                        pass
                refusal = self._bind_order_account(o)
                if refusal:
                    log.error("IBKR market_order(%s) refused: %s",
                              symbol, refusal)
                    empty["raw"] = {"reason": refusal}
                    return empty
            legs, child_trades, stop_leg_id, target_leg_id = [], [], "", ""
            trade = None
            parent_id = 0
            for o in orders:
                if trade is not None and bracket is not None:
                    # The parent is held (transmit=False) until the last
                    # leg arrives, so its id is known by now — re-stamp
                    # every child from the id TWS actually assigned
                    # rather than the one we guessed before placement.
                    if not parent_id:
                        log.error("IBKR %s: parent has no order id after "
                                  "placement — refusing to release "
                                  "children that would rest alone", symbol)
                        self._retract(contract, child_trades, trade)
                        empty["raw"] = {"reason": "bracket_parent_unidentified"}
                        return empty
                    o.parentId = parent_id
                placed = self._ib.placeOrder(contract, o)
                if trade is None:
                    trade = placed          # the parent owns the fill
                    parent_id = int(getattr(getattr(placed, "order", None),
                                            "orderId", 0) or 0)
                else:
                    child_trades.append(placed)
                    leg_id = str(getattr(getattr(placed, "order", None),
                                         "orderId", "") or "")
                    if leg_id:
                        legs.append(leg_id)
                        # NAME the stop. `legs` is flat and in placement
                        # order, and the target is placed first, so a caller
                        # walking it blind reaches the wrong leg. Alpaca
                        # reports `protectiveStopId` for exactly this reason
                        # and the entry path already maps it onto the row as
                        # `protective_stop_id`; IBKR simply never sent it.
                        leg_kind = str(getattr(
                            getattr(placed, "order", None),
                            "orderType", "") or "").upper()
                        if leg_kind.startswith("STP"):
                            stop_leg_id = leg_id
                        elif leg_kind.startswith("LMT"):
                            target_leg_id = leg_id
            self._ib.sleep(1.0)
            filled_qty = float(trade.orderStatus.filled or 0)
            avg_px = float(trade.orderStatus.avgFillPrice or 0)
            # TWS-side rejections never say "Rejected" — ib_insync's
            # vocabulary surfaces them as Cancelled/ApiCancelled/Inactive
            # with nothing filled. Raw, that status walked straight past
            # the engine's REJECTED check and booked a full-size phantom
            # live trade at the pre-order ticker price. Normalize at the
            # boundary so every consumer's existing check catches it.
            dead = self._dead_order_reason(trade, filled_qty, child_trades)
            if dead:
                log.error("IBKR market_order(%s, %s, %s) dead on "
                          "arrival: %s", symbol, side, quantity, dead)
                empty["orderId"] = str(trade.order.orderId or "")
                empty["raw"] = {"reason": dead}
                return empty
            # The time-in-force the broker KEPT on the legs, read back
            # before anything is claimed for them — the stamp cannot be
            # trusted, see _protection_downgraded.
            downgraded = ""
            if bracket is not None and legs:
                downgraded = self._protection_downgraded(
                    symbol, legs, stop_leg_id)
            out = {
                "orderId": str(trade.order.orderId or ""),
                "symbol": symbol, "side": side,
                # The TRUTH, not the request. `filled_qty or quantity`
                # substituted the full order size whenever IBKR reported 0
                # filled after the one-second wait — which is exactly what a
                # market order held pre-open, on a halted symbol, or simply
                # not acked inside that second looks like. Downstream,
                # `broker_filled_qty` documents the opposite contract: a
                # reported 0 means "nothing gone yet, the position is live".
                # Fabricating the size made `complete` True in
                # `resolve_exit_fill`, which short-circuits the
                # `order_still_working` branch, cancels the resting bracket
                # and books the row CLOSED — leaving a full-size order still
                # working at IBKR against a position that is still on the
                # account, naked, and scanned by no sweep. It also disabled
                # the refusal gate itself: `_submit_close_or_raise` raises
                # only when `filled <= 0`. Alpaca has always reported
                # honestly here and says why in its own comment.
                # Safe on the way in: the entry path only overwrites `qty`
                # `if fill_qty > 0`, and `qty` already holds what we asked.
                "executedQty": str(filled_qty),
                "avgPrice": str(avg_px or 0),
                "status": (trade.orderStatus.status or "PENDING").upper(),
                "raw": trade.dict() if hasattr(trade, "dict") else {},
            }
            if filled_qty <= 0:
                # WORKING, not filled. A market order held outside regular
                # hours, on a halted symbol, or simply not acked inside the
                # second sits PreSubmitted/Submitted with nothing printed.
                # That is not a position, and the engine used to book it as
                # one: a full-size OPEN row at the pre-order ticker, marked
                # protected because the children rested — and reconcile,
                # seeing no position at the broker, then cancelled those
                # children and let the parent fill naked. The answer is
                # named for what it is; the entry path books a WORKING row
                # and manage_positions polls the order until it fills, dies
                # or is cancelled. The legs stay attached (they arm on the
                # fill) and are reported for tracking, but protection is
                # not claimed for a position that does not exist yet.
                out["status"] = "WORKING"
                out["working"] = True
                if bracket is not None and downgraded:
                    # The parent keeps working. Legs that would die at
                    # the close are withdrawn now rather than reported as
                    # the protection the fill will inherit.
                    log.error("IBKR %s: %s — withdrawing the legs; the "
                              "fill will be bot-managed", symbol, downgraded)
                    self._retract(contract, child_trades, None)
                    out["protectionNote"] = (
                        f"{downgraded}; protective legs withdrawn — "
                        f"bot-side management owns the exit")
                elif bracket is not None:
                    out["protectiveOrders"] = legs
                    if stop_leg_id:
                        out["protectiveStopId"] = stop_leg_id
                    if target_leg_id:
                        out["protectiveTargetId"] = target_leg_id
                return out
            if bracket is not None:
                # PROVEN, not assumed. `protected` turns OFF bot-side
                # SL/TP management, so claiming it for a leg TWS refused
                # leaves the position naked AND unwatched — strictly
                # worse than never bracketing at all. The stop is the leg
                # that matters; a target without it is just an order.
                refused = [ct for ct in child_trades
                           if not self._leg_is_resting(ct)]
                partial = 0 < filled_qty < abs(float(quantity))
                if refused or partial or downgraded:
                    why = ("a protective leg was refused" if refused
                           else f"the parent filled {filled_qty} of "
                                f"{quantity} and the legs would over-cover"
                           if partial else downgraded)
                    log.error("IBKR %s: %s — cancelling the bracket and "
                              "leaving this position to bot-side "
                              "management", symbol, why)
                    # An over-sized stop is not a smaller problem than no
                    # stop: on a partial fill it closes what filled and
                    # OPENS the remainder the other way.
                    #
                    # The PARENT goes back too when this is a partial.
                    # Passing None cancelled the two children and left
                    # an unfilled MarketOrder remainder live at TWS
                    # under the default DAY TIF. We reported the partial
                    # as the fill, the engine booked a row for that
                    # smaller quantity, and the rest filled after we had
                    # stopped looking: naked at the broker, absent from
                    # the row, invisible to reconciliation - which walks
                    # AssetBotTrade rows and so can only ever see
                    # quantities some row already claims.
                    self._retract(contract, child_trades,
                                  trade if partial else None)
                    out["protectionNote"] = (
                        f"{why}; protective legs withdrawn — bot-side "
                        f"management owns the exit")
                else:
                    out["protectedOnFill"] = True
                    out["protectiveOrders"] = legs
                    if stop_leg_id:
                        out["protectiveStopId"] = stop_leg_id
                    if target_leg_id:
                        out["protectiveTargetId"] = target_leg_id
            return out
        except Exception as e:
            log.error("IBKR market_order(%s, %s, %s) failed: %s",
                      symbol, side, quantity, e)
            return empty

    def _retract(self, contract, child_trades, parent_trade) -> None:
        """Pull back legs that must not rest — best effort, never raises.

        Used when a bracket cannot be completed honestly: a leg TWS
        refused, a partial fill the legs would over-cover, or a parent we
        could not identify. Anything left resting here is an order no
        part of the platform knows about, and a resting exit against a
        flat book opens a position rather than closing one.
        """
        for placed in list(child_trades or []):
            try:
                self._ib.cancelOrder(placed.order)
            except Exception as e:  # noqa: BLE001
                log.error("IBKR retract leg failed (%s) — an unmanaged "
                          "order may be resting at the broker", e)
        if parent_trade is not None:
            try:
                self._ib.cancelOrder(parent_trade.order)
            except Exception as e:  # noqa: BLE001
                log.error("IBKR retract parent failed: %s", e)

    def cancel_order(self, order_id: str) -> bool:
        """Cancel one resting order — a bracket leg before a flatten.

        The engine reaches for this by name
        (`getattr(client, "cancel_order", None)`) and skips the whole
        cancellation step when it is absent, which is what made shipping
        brackets without it dangerous: the close would sell the position
        and leave the stop resting, and a resting stop against a flat
        book does not protect anything — it opens a fresh position the
        other way when it fires.

        True when the cancel was sent. An order already filled or gone is
        not an error: the leg is no longer resting either way.
        """
        if not self._connect():
            # NOT the same as "already gone". The caller flattens on this
            # answer, and a stop we could not even look at may still be
            # resting — say so loudly rather than reporting a tidy False.
            log.error("IBKR cancel_order(%s): no session — the leg may "
                      "still be resting at the broker", order_id)
            raise ConnectionError(f"IBKR unreachable, cannot cancel {order_id}")
        try:
            wanted = str(order_id)
            for trade in (self._ib.openTrades() or []):
                oid = str(getattr(getattr(trade, "order", None),
                                  "orderId", "") or "")
                if oid != wanted:
                    continue
                self._ib.cancelOrder(trade.order)
                # PROVE it, here, once — because every caller needs the same
                # proof and none of them can get it on its own. ib_insync
                # writes PendingCancel into the order SYNCHRONOUSLY inside
                # cancelOrder (ib.py:697-706), and PendingCancel is not a
                # done state, so an immediate re-read ALWAYS finds the order
                # still open: a caller that read the status straight after
                # this call could never see a confirmed cancellation, and
                # every withdrawal would report failure. Give TWS its turn,
                # then answer on what it says.
                try:
                    self._ib.sleep(self.CANCEL_CONFIRM_WAIT_S)
                except Exception:  # noqa: BLE001 — a closed loop
                    pass
                after = self.order_status(wanted)
                state = str((after or {}).get("state") or "")
                if state in ("dead", "unknown"):
                    # unknown = no longer in this session's tables at all,
                    # which for an id we were just holding means gone.
                    return True
                if state == "filled":
                    log.warning("IBKR cancel %s: it FILLED in the race — "
                                "nothing was cancelled", wanted)
                    return False
                log.warning("IBKR cancel %s: TWS still reports %s after "
                            "%.1fs — not confirmed",
                            wanted, state or "no answer",
                            self.CANCEL_CONFIRM_WAIT_S)
                return False
            log.info("IBKR cancel %s: not among the open orders — already "
                     "filled or cancelled", wanted)
            return False
        except ConnectionError:
            raise
        except Exception as e:
            log.error("IBKR cancel_order(%s) failed: %s", order_id, e)
            raise

    def modify_protective(self, order_id: str, new_price: float) -> dict:
        """Move a resting stop or target to `new_price`.

        IN PLACE, not cancel-then-replace. ib_insync re-places an order
        carrying the SAME orderId as a modification, so the leg never
        stops existing — which matters more here than anywhere else on
        this client. Cancel-first leaves the position bare for as long as
        the round trip takes; place-first leaves TWO stops resting, and
        an over-covered position closes on one and OPENS THE OTHER WAY on
        the other. Neither window is acceptable on a live stop, and
        neither is necessary.

        The leg's own type decides which field moves: a STP carries its
        trigger in auxPrice, a LMT its price in lmtPrice. Reading that
        off the resting order rather than off our own bookkeeping is what
        makes this safe when `protective_order_ids` has drifted — it is a
        flat list with no record of which id is which.

        Returns {"ok": bool, "reason": str, "price": float|None}. Never
        raises for a leg that is simply gone: an order already filled is
        not an error, it is an answer.
        """
        empty = {"ok": False, "reason": "ibkr_unavailable", "price": None}
        if not self._connect():
            log.error("IBKR modify_protective(%s): no session — the leg "
                      "still rests at whatever it was", order_id)
            return empty
        try:
            wanted = str(order_id)
            for trade in (self._ib.openTrades() or []):
                order = getattr(trade, "order", None)
                oid = str(getattr(order, "orderId", "") or "")
                if oid != wanted or order is None:
                    continue

                kind = str(getattr(order, "orderType", "") or "").upper()
                contract = getattr(trade, "contract", None)
                tick = self._min_tick_for(contract) if contract else 0.0

                # The account is bound FIRST, before anything on the live
                # order is touched. `openTrades()` hands back ib_insync's own
                # objects, so a refusal that happened AFTER the write left
                # this leg carrying a price nobody sent — and the next tick
                # reads the same object back. Every refusal below now leaves
                # the resting order exactly as it was found.
                #
                # A leg re-placed without an account lands on the session
                # default, which is a stop resting against a book that does
                # not hold the position.
                refusal = self._bind_order_account(order)
                if refusal:
                    return {"ok": False, "reason": refusal, "price": None}
                if "STP" in kind:
                    # `widen` is KEYWORD-ONLY and has no default. This call
                    # passed two positional arguments, so every invocation
                    # raised TypeError, the outer except swallowed it, and
                    # the method answered ok=False. Break-even and trailing
                    # have never moved a stop on this venue — and the row was
                    # not marked stop_rules_inert either, because that only
                    # happens when a client exposes no mover at all. The
                    # position read as managed while nothing managed it.
                    #
                    # WIDEN, never tighten: a stop nudged the wrong way by a
                    # rounding step fires earlier than the operator asked
                    # for. The leg's own action says which side we are on —
                    # a long is closed by a SELL and its stop rests BELOW, so
                    # it rounds down for more room; a short's rounds up.
                    if not tick:
                        return {"ok": False, "price": None,
                                "reason": f"leg {wanted}: minTick unreadable "
                                          f"— refusing to send an off-tick "
                                          f"price TWS would reject, which "
                                          f"leaves the position naked and "
                                          f"still looking protected"}
                    exit_action = str(
                        getattr(order, "action", "") or "").upper()
                    px = self._snap_to_tick(new_price, tick,
                                            widen=(exit_action == "SELL"))
                    if px is None:
                        return {"ok": False, "price": None,
                                "reason": f"leg {wanted}: {new_price} will "
                                          f"not snap onto a {tick} tick"}
                    order.auxPrice = px
                elif "LMT" in kind:
                    # A REFUSAL, not a best effort — the rule Alpaca's client
                    # already states for itself. Every caller of this method
                    # is moving a STOP, and the id list they walk holds the
                    # take-profit too: `protectiveOrders` is flat and ordered
                    # by placement, and IBKR places the TARGET first
                    # (bracketOrder yields parent, takeProfit, stopLoss), so
                    # a blind walk reaches this leg first.
                    #
                    # Accepting it wrote the break-even price into lmtPrice:
                    # a sell limit BELOW the mark on a long, filled on the
                    # next tick and booked as a take-profit, while the stop
                    # was never touched. Answering False lets the caller's
                    # loop walk on to the leg it actually wanted.
                    return {"ok": False, "price": None,
                            "reason": f"leg {wanted} is a take-profit, not a "
                                      f"stop — refusing to move it"}
                else:
                    return {"ok": False, "price": None,
                            "reason": f"leg {wanted} is a {kind or 'unknown'} "
                                      f"order — refusing to guess which "
                                      f"field carries its price"}

                placed = self._ib.placeOrder(contract, order)
                # placeOrder is NON-BLOCKING. Returning ok on the next line
                # reported a success TWS had not agreed to: an off-tick 110
                # where the market rule is coarser than minTick, a modify
                # racing a fill, a leg dropped to Inactive — every rejection
                # the refusals above were written to ANTICIPATE arrives
                # asynchronously, and none of them were ever read. The gate
                # refused on a predicted rejection and reported success on a
                # real one.
                #
                # It is not merely a false report. base.py stamps
                # `breakeven_armed` on ok=True, which disarms the rule for
                # the life of the trade — so an unverified True leaves the
                # stop at its original wide level while every surface says
                # break-even, and no later tick tries again.
                #
                # The entry path already waits and PROVES the leg is resting
                # before it will claim `protectedOnFill`. A move has to
                # clear the same bar: the one second is what lets
                # PendingSubmit — which ib_insync assigns locally the
                # instant placeOrder is called, before TWS has said
                # anything — resolve into an answer.
                self._ib.sleep(1.0)
                if not self._leg_is_resting(placed):
                    why = (self._dead_order_reason(placed, 0)
                           or "TWS did not accept the modification")
                    log.error("IBKR leg %s (%s) REFUSED the move to %s: %s "
                              "— the stop still rests where it was",
                              wanted, kind, px, why)
                    return {"ok": False, "reason": why, "price": None}
                log.info("IBKR modified leg %s (%s) to %s", wanted, kind, px)
                return {"ok": True, "reason": "", "price": px}

            return {"ok": False, "price": None,
                    "reason": f"leg {wanted} is not among the open orders — "
                              f"already filled or cancelled"}
        except Exception as e:  # noqa: BLE001
            log.error("IBKR modify_protective(%s) failed: %s", order_id, e)
            return {"ok": False, "reason": str(e), "price": None}

    def modify_target(self, order_id: str, new_price: float) -> dict:
        """Move the resting TAKE-PROFIT leg to `new_price`.

        The sibling of modify_protective, and deliberately separate. That
        method refuses a limit leg because every one of its callers is
        moving a stop, and a mover that could be talked into either would
        put the two back in one code path — which is the bug it exists to
        prevent.

        Snapping is mirrored, not shared: a target rounds AWAY from the
        position too, so it is never quoted better than the venue will
        actually give.
        """
        empty = {"ok": False, "reason": "ibkr_unavailable", "price": None}
        if not self._connect():
            return empty
        try:
            wanted = str(order_id)
            for trade in (self._ib.openTrades() or []):
                order = getattr(trade, "order", None)
                oid = str(getattr(order, "orderId", "") or "")
                if oid != wanted or order is None:
                    continue

                kind = str(getattr(order, "orderType", "") or "").upper()
                contract = getattr(trade, "contract", None)
                tick = self._min_tick_for(contract) if contract else 0.0

                refusal = self._bind_order_account(order)
                if refusal:
                    return {"ok": False, "reason": refusal, "price": None}

                if "STP" in kind:
                    return {"ok": False, "price": None,
                            "reason": f"leg {wanted} is a stop, not a "
                                      f"take-profit — refusing to move it"}
                if "LMT" not in kind:
                    return {"ok": False, "price": None,
                            "reason": f"leg {wanted} is a {kind or 'unknown'} "
                                      f"order — refusing to guess which "
                                      f"field carries its price"}
                if not tick:
                    return {"ok": False, "price": None,
                            "reason": f"leg {wanted}: minTick unreadable — "
                                      f"refusing to send an off-tick price "
                                      f"TWS would reject"}
                # A long's target sits ABOVE and rounds up; a short's sits
                # below and rounds down. Either way away from the position,
                # so the quoted level is one the venue will honour.
                exit_action = str(getattr(order, "action", "") or "").upper()
                px = self._snap_to_tick(new_price, tick,
                                        widen=(exit_action != "SELL"))
                if px is None:
                    return {"ok": False, "price": None,
                            "reason": f"leg {wanted}: {new_price} will not "
                                      f"snap onto a {tick} tick"}
                order.lmtPrice = px

                placed = self._ib.placeOrder(contract, order)
                # placeOrder is non-blocking — the same reason the stop
                # mover waits before it will claim anything.
                self._ib.sleep(1.0)
                if not self._leg_is_resting(placed):
                    why = (self._dead_order_reason(placed, 0)
                           or "TWS did not accept the modification")
                    log.error("IBKR leg %s REFUSED the target move to %s: "
                              "%s", wanted, px, why)
                    return {"ok": False, "reason": why, "price": None}
                log.info("IBKR modified target leg %s to %s", wanted, px)
                return {"ok": True, "reason": "", "price": px}

            return {"ok": False, "price": None,
                    "reason": f"leg {wanted} is not among the open orders — "
                              f"already filled or cancelled"}
        except Exception as e:  # noqa: BLE001
            log.error("IBKR modify_target(%s) failed: %s", order_id, e)
            return {"ok": False, "reason": str(e), "price": None}

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
            self._entry_good_for_the_day(order)
            refusal = self._bind_order_account(order)
            if refusal:
                log.error("IBKR market_order_option(%s) refused: %s",
                          underlying, refusal)
                empty["raw"] = {"reason": refusal}
                return empty
            trade = self._ib.placeOrder(opt, order)
            self._ib.sleep(1.0)
            dead = self._dead_order_reason(
                trade, float(trade.orderStatus.filled or 0))
            if dead:
                log.error("IBKR market_order_option(%s) dead on "
                          "arrival: %s", underlying, dead)
                empty["orderId"] = str(trade.order.orderId or "")
                empty["raw"] = {"reason": dead}
                return empty
            filled_qty = float(trade.orderStatus.filled or 0)
            out = {
                "orderId": str(trade.order.orderId or ""),
                "symbol": f"{underlying} {expiry} {strike}{right.upper()}",
                "side": side,
                # Same fabrication as the equity path above, and this one
                # is not opt-in: options and CFDs route to IBKR
                # unconditionally, and a thin option book is where a
                # one-second unfilled market order is most likely of all.
                "executedQty": str(filled_qty),
                "avgPrice": str(trade.orderStatus.avgFillPrice or 0),
                "status": (trade.orderStatus.status or "PENDING").upper(),
            }
            if filled_qty <= 0:
                # WORKING, exactly as on the equity path — and the reason
                # given there applies here MORE, not less: a thin option
                # book is where an unfilled one-second market order is
                # likeliest, so this is the path that produced the
                # full-size phantom row most often.
                out["status"] = "WORKING"
                out["working"] = True
            return out
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
        if not is_ibkr_available():
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
