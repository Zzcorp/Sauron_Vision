"""Saxo Bank OpenAPI adapter — SaxoTrader.

The fourth live venue, and the first whose session the platform keeps
alive on its own (engine/saxo_oauth.py). Every endpoint, parameter and
field name here was read off developer.saxo on 2026-09-17 by two
independent readers and rechecked; where the documentation is silent the
code names the gap and takes the defensive reading.

WHAT SAXO IS, IN THIS PLATFORM'S TERMS

  * Identity is the pair (Uic, AssetType). A stock and its CFD share a
    Uic; a forex pair shares one across FxSpot/forwards/options. The
    platform's symbols ("AAPL", "EURUSD") are resolved once through
    /ref/v1/instruments and cached per process.
  * Prices are request/response (/trade/v1/infoprices): on SIM, FX is
    real-time and everything else is delayed (Quote.DelayedByMinutes) or
    NoAccess unless the demo account is linked to a funded live one. The
    adapter returns the delay beside the price; it never hides it.
  * Bars come from /chart/v3/charts by Horizon in minutes. FX and index
    CFDs carry bid/ask bars only — the mid is returned, as Saxo's own
    support suggests. The last sample is the live, incomplete bar.
  * An order is POST /trade/v2/orders; the response carries an OrderId
    and NOTHING about the fill. The fill is read from the audit log
    (/cs/v1/audit/orderactivities), polled a few times like eToro's async
    orders. An order still pending when polling stops is PENDING with
    executedQty 0, never a fill. A 202 TradeNotCompleted means "Saxo does
    not know yet" — it is reported UNKNOWN and MUST NOT be resent.
  * Brackets are related orders (one stop-type, one Limit) attached at
    placement; under the FifoEndOfDay netting profile they ride the
    position and can be moved by PositionId; under the real-time
    profiles they are free-standing and are found by OrderId.
  * Duplicate protection is Saxo's: an identical order body within
    fifteen seconds is a 409 unless X-Request-ID differs — every write
    carries a fresh one.

WHAT IS DELIBERATELY NOT HERE

  * No streaming. A bot that decides on 4h bars polls.
  * No SIM balance reset, no pre-trade disclaimer acceptance: a rejected
    order surfaces Saxo's ErrorCode and the operator reads it.

The capability table (engine/capabilities.py) declares what this class
promises; the conformance test holds the method set; `saxo_smoke` is the
command the operator runs against SIM to prove each promise live.
"""
from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone as dt_tz
from typing import Optional
from urllib.parse import urlencode

import requests

from . import saxo_oauth

log = logging.getLogger(__name__)

HORIZON = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "2h": 120,
           "4h": 240, "1d": 1440, "1w": 10080}
CHART_MAX = 1200               # documented cap on Count
FILL_ATTEMPTS = 5
FILL_DELAY_S = 0.6
TIMEOUT_S = 20
#: Order writes wait longer than Saxo's own sixty-second broker deadline,
#: so its 202 TradeNotCompleted (which carries an OrderId) always arrives
#: before this client gives up. A client-side timeout on a placement is
#: the worst state there is: the order may be live and nothing names it.
ORDER_TIMEOUT_S = 75

#: Chart samples for these asset types carry bid/ask legs only.
BID_ASK_BARS = {"FxSpot", "CfdOnIndex", "CfdOnFutures"}
#: The platform's asset classes, as Saxo names them. Commodities and
#: indices are CFDs on Saxo's retail side.
ASSET_TYPE_FOR_CLASS = {"forex": "FxSpot", "stock": "Stock", "etf": "Etf",
                        "index": "CfdOnIndex", "commodity": "CfdOnFutures"}
#: Catalogue exchange strings that are Saxo ExchangeId literals verbatim.
#: Everything else searches without ExchangeId and prefers the primary
#: listing — Saxo publishes no complete ExchangeId list.
EXCHANGE_IDS = {"NASDAQ": "NASDAQ", "NYSE": "NYSE"}
#: Stop-type spelling differs per instrument (KO: StopIfTraded; AAPL:
#: Stop); the instrument's own SupportedOrderTypes decides, in this order.
STOP_TYPES = ("Stop", "StopIfTraded")
TRAIL_TYPES = ("TrailingStop", "TrailingStopIfTraded")
OPEN_STATUSES = {"Open", "PartiallyClosed"}
SEC_TYPE = {"Stock": "STK", "Etf": "STK", "FxSpot": "CASH"}

_UIC_CACHE: dict = {}          # (symbol, asset_type) -> (uic, asset_type, details)
_SYMBOL_BY_UIC: dict = {}      # (uic, asset_type) -> symbol
_DETAILS_CACHE: dict = {}      # (uic, asset_type) -> details


class SaxoApiError(RuntimeError):
    """A refused request, carrying Saxo's ErrorCode, Message and the
    X-Correlation the support desk asks for. Never carries a token."""

    def __init__(self, status: int, code: str, message: str,
                 correlation: str = ""):
        super().__init__(f"HTTP {status} {code}: {message}".strip())
        self.status, self.code, self.message = status, code, message
        self.correlation = correlation


class SaxoAuthError(SaxoApiError):
    """401 — the bearer was refused. The body is EMPTY (observed), so it
    is never parsed; the keeper decides whether the session is lost."""


class SaxoOrderInDoubt(SaxoApiError):
    """A placement whose outcome is unknown: the request did not come back.

    Distinct from a refusal on purpose — a caller that retried this would
    double the position. It carries the ExternalReference the order was
    sent with, which is what the operator searches on in SaxoTraderGO or
    in /cs/v1/audit/orderactivities.
    """

    def __init__(self, reference: str, detail: str):
        super().__init__(0, "OrderInDoubt",
                         f"the order request did not come back ({detail}). "
                         f"It MAY be live at Saxo under ExternalReference "
                         f"{reference!r}. Do not resend it: check "
                         f"/brokers/ and the order list first.")
        self.reference = reference


class SaxoRateLimited(SaxoApiError):
    """429 — with the seconds until the session window resets, when the
    X-RateLimit-Session-Reset header says so."""

    def __init__(self, reset_s: Optional[int], correlation: str = ""):
        super().__init__(429, "RateLimitExceeded", "Rate limit exceeded!",
                         correlation)
        self.reset_s = reset_s


def _iso_to_ms(ts: str) -> int:
    s = (ts or "").strip()
    if not s:
        return 0
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    head, _dot, frac = s.partition(".")
    if frac:
        digits = "".join(ch for ch in frac if ch.isdigit())[:6]
        tail = frac[len("".join(ch for ch in frac if ch.isdigit())):]
        s = f"{head}.{digits.ljust(6, '0')}{tail}"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return 0
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=dt_tz.utc)
    return int(dt.timestamp() * 1000)


def _is_fx(symbol: str) -> bool:
    s = (symbol or "").upper()
    return len(s) == 6 and s.isalpha()


def _round_to_tick(price: float, tick: Optional[float]) -> float:
    if not tick or tick <= 0:
        return float(price)
    steps = round(float(price) / tick)
    return round(steps * tick, 10)


class SaxoTrader:
    """One account, one environment, one bearer that renews itself.

    `acct` is a SaxoAccount; the bearer is `saxo_oauth.ensure_access_token`
    at every request, so a token about to die is rotated in place and a
    dead session raises rather than 401-ing quietly. Tests pass `token`
    and a fake `session` and need no row.
    """

    def __init__(self, acct=None, *, env: Optional[str] = None,
                 token: Optional[str] = None, session=None,
                 timeout: float = TIMEOUT_S):
        self.acct = acct
        self.env = env or (saxo_oauth.env_of(acct) if acct is not None else "sim")
        self.base = saxo_oauth.API_BASE[self.env]
        self._token = token
        self._session = session
        self.timeout = timeout
        self._identity: Optional[dict] = None

    # ── transport ──────────────────────────────────────────────────────────

    def _sess(self):
        if self._session is None:
            self._session = requests.Session()
        return self._session

    def _bearer(self) -> str:
        if self._token:
            return self._token
        # An instance outlives a keeper cycle (a bot loop holds one for
        # minutes). The row in memory then carries a refresh token the
        # keeper has already rotated — and rotation KILLS the old one — so
        # refreshing from this stale copy fails and reads as a lost
        # session. Re-read the row before deciding it needs a refresh.
        acct = self.acct
        if acct is not None and getattr(acct, "pk", None) and \
                not acct.access_token_valid():
            try:
                acct.refresh_from_db()
            except Exception as e:  # noqa: BLE001 — no DB is not a dead session
                log.debug("saxo: could not re-read the account row (%s)", e)
        return saxo_oauth.ensure_access_token(acct, session=self._session)

    def _headers(self, write: bool = False) -> dict:
        h = {"Authorization": f"Bearer {self._bearer()}",
             "Accept": "application/json"}
        if write:
            h["Content-Type"] = "application/json"
            h["X-Request-ID"] = uuid.uuid4().hex
        return h

    def _url(self, path: str, params: Optional[dict] = None) -> str:
        url = f"{self.base}/{path.lstrip('/')}"
        if params:
            url += "?" + urlencode({k: v for k, v in params.items()
                                    if v is not None and v != ""})
        return url

    @staticmethod
    def _raise_for(r):
        corr = ""
        try:
            corr = r.headers.get("X-Correlation", "") if getattr(r, "headers", None) else ""
        except Exception:  # noqa: BLE001
            corr = ""
        if r.status_code == 401:
            raise SaxoAuthError(401, "Unauthorized", "bearer refused", corr)
        if r.status_code == 429:
            reset = None
            try:
                reset = int(r.headers.get("X-RateLimit-Session-Reset"))
            except Exception:  # noqa: BLE001
                reset = None
            raise SaxoRateLimited(reset, corr)
        if r.status_code >= 400:
            body = {}
            try:
                body = r.json() or {}
            except Exception:  # noqa: BLE001
                body = {}
            info = body.get("ErrorInfo") or {}
            code = str(body.get("ErrorCode") or info.get("ErrorCode") or "").strip()
            msg = str(body.get("Message") or info.get("Message") or "").strip()
            state = body.get("ModelState")
            if state:
                msg = (msg + " " + str(state)).strip()
            raise SaxoApiError(r.status_code, code or "Unknown", msg, corr)

    def _get(self, path: str, params: Optional[dict] = None) -> dict:
        r = self._sess().get(self._url(path, params), headers=self._headers(),
                             timeout=self.timeout)
        self._raise_for(r)
        if r.status_code == 204:
            return {}
        return r.json() or {}

    def _write(self, method: str, path: str, body: Optional[dict] = None,
               params: Optional[dict] = None, timeout: Optional[float] = None):
        fn = getattr(self._sess(), method)
        kw = {"headers": self._headers(write=True),
              "timeout": timeout or self.timeout}
        if body is not None:
            kw["json"] = body
        r = fn(self._url(path, params), **kw)
        return r

    # ── identity ───────────────────────────────────────────────────────────

    def identity(self) -> dict:
        """ClientKey, the default AccountKey, its currency and the netting
        profile — read once per client instance. The netting profile
        decides how brackets and closes work; nothing here guesses it."""
        if self._identity is not None:
            return self._identity
        client = self._get("port/v1/clients/me")
        account_key = str(client.get("DefaultAccountKey") or "")
        currency = str(client.get("DefaultCurrency") or "")
        accounts = self._get("port/v1/accounts/me").get("Data") or []
        for row in accounts:
            if str(row.get("AccountKey") or "") == account_key:
                currency = str(row.get("Currency") or currency)
                break
        self._identity = {
            "client_key": str(client.get("ClientKey") or ""),
            "account_key": account_key,
            "account_id": str(client.get("DefaultAccountId") or ""),
            "currency": currency,
            "netting_profile": str(client.get("PositionNettingProfile") or ""),
            "netting_mode": str(client.get("PositionNettingMode") or ""),
        }
        return self._identity

    def ping(self) -> bool:
        """Authenticated reachability: the session's own capabilities.
        (/root/v1/diagnostics/get answers 200 with no token at all, so it
        proves nothing about the session.)"""
        try:
            caps = self._get("root/v1/sessions/capabilities")
            return bool(caps.get("AuthenticationLevel"))
        except Exception as e:  # noqa: BLE001
            log.warning("saxo ping failed: %s", e)
            return False

    # ── reference data ─────────────────────────────────────────────────────

    def _asset_type_for(self, symbol: str, asset_type: Optional[str] = None) -> str:
        if asset_type:
            return asset_type
        try:
            from instruments.models import Instrument
            inst = Instrument.objects.filter(symbol=symbol).only(
                "asset_class").first()
            if inst is not None:
                return ASSET_TYPE_FOR_CLASS.get(inst.asset_class, "Stock")
        except Exception:  # noqa: BLE001 — no DB, no catalogue: fall through
            pass
        return "FxSpot" if _is_fx(symbol) else "Stock"

    def _exchange_for(self, symbol: str) -> Optional[str]:
        try:
            from instruments.models import Instrument
            inst = Instrument.objects.filter(symbol=symbol).only("exchange").first()
            if inst is not None:
                return EXCHANGE_IDS.get((inst.exchange or "").upper())
        except Exception:  # noqa: BLE001
            pass
        return None

    def resolve(self, symbol: str, asset_type: Optional[str] = None) -> tuple:
        """(Uic, AssetType, details) for a platform symbol.

        Search by keyword, pinned to the listing when the catalogue names
        an exchange Saxo spells the same way; otherwise prefer the row
        whose Symbol is exactly TICKER:x<mic> and which IS its primary
        listing. Raises LookupError — the router treats that as "cannot
        route", never as "route anyway".
        """
        sym = (symbol or "").upper().strip()
        atype = self._asset_type_for(sym, asset_type)
        key = (sym, atype)
        if key in _UIC_CACHE:
            return _UIC_CACHE[key]
        params = {"Keywords": sym, "AssetTypes": atype, "$top": 50}
        exch = self._exchange_for(sym)
        if exch:
            params["ExchangeId"] = exch
        rows = [r for r in (self._get("ref/v1/instruments", params).get("Data") or [])
                if r.get("SummaryType", "Instrument") == "Instrument"
                and str(r.get("AssetType")) == atype]
        if not rows:
            raise LookupError(f"Saxo knows no {atype} named {sym}")

        def score(r):
            s = str(r.get("Symbol") or "").upper()
            exact = s == sym or s.startswith(sym + ":")
            primary = r.get("PrimaryListing") == r.get("Identifier")
            return (exact, primary, r.get("IsKeywordMatch", False))
        best = sorted(rows, key=score, reverse=True)[0]
        s = str(best.get("Symbol") or "").upper()
        if not (s == sym or s.startswith(sym + ":")):
            raise LookupError(f"Saxo's best match for {sym} is {s!r}, not {sym}")
        uic = int(best["Identifier"])
        details = self._details(uic, atype)
        out = (uic, atype, details)
        _UIC_CACHE[key] = out
        _SYMBOL_BY_UIC[(uic, atype)] = sym
        return out

    def _details(self, uic: int, atype: str) -> dict:
        """The instrument's details by (Uic, AssetType) — cached per
        process. Needs no symbol, so a mover that only holds a leg can
        still find the tick size."""
        key = (int(uic), str(atype))
        if key in _DETAILS_CACHE:
            return _DETAILS_CACHE[key]
        try:
            out = self._get(f"ref/v1/instruments/details/{uic}/{atype}",
                            {"FieldGroups": "SupportedOrderTypeSettings"})
        except SaxoApiError as e:
            log.warning("saxo: no details for %s/%s (%s)", uic, atype, e)
            return {}
        _DETAILS_CACHE[key] = out
        return out

    def _symbol_for(self, uic, atype: str, display: Optional[dict] = None) -> str:
        cached = _SYMBOL_BY_UIC.get((int(uic or 0), str(atype)))
        if cached:
            return cached
        s = str((display or {}).get("Symbol") or "")
        return s.split(":")[0].upper() if s else f"UIC{uic}"

    @staticmethod
    def _tick(details: dict, kind: str, price: float) -> Optional[float]:
        """The tick size that applies at `price`: the order-type specific
        one when given, else the scheme element for the band, else the
        instrument's flat TickSize. Prices off-tick are rejected by Saxo."""
        specific = details.get("TickSizeStopOrder" if kind == "stop"
                               else "TickSizeLimitOrder")
        if specific:
            return float(specific)
        scheme = details.get("TickSizeScheme") or {}
        for el in scheme.get("Elements") or []:
            try:
                if float(price) <= float(el.get("HighPrice")):
                    return float(el.get("TickSize"))
            except (TypeError, ValueError):
                continue
        if scheme.get("DefaultTickSize"):
            return float(scheme["DefaultTickSize"])
        return float(details["TickSize"]) if details.get("TickSize") else None

    @staticmethod
    def _amount(details: dict, quantity: float) -> float:
        """Quantity as Saxo will accept it: on the lot grid when lots are
        enforced, at the instrument's decimals — and NEVER larger than
        asked.

        The first draft raised a sub-minimum quantity to MinimumTradeSize.
        That silently overrides the risk sizing: a bot that computed 400
        units from its stop distance would have traded 1 000 on EURUSD,
        two and a half times the risk it chose. Refusing is the honest
        answer — the engine turns the ValueError into an ORDER_ERROR skip
        carrying this sentence, so the operator reads the minimum instead
        of discovering the size.
        """
        qty = float(quantity)
        lot = details.get("LotSize")
        if lot and details.get("LotSizeType") not in (None, "NotUsed"):
            floored = (int(qty // float(lot))) * float(lot)
            if floored <= 0:
                raise ValueError(
                    f"Saxo trades this instrument in lots of {lot}; "
                    f"{qty} is less than one lot. No order was placed.")
            qty = floored
        minimum = details.get("MinimumTradeSize")
        if minimum and qty < float(minimum):
            raise ValueError(
                f"Saxo's minimum trade size here is {minimum}; the size "
                f"asked was {quantity}. Refusing rather than trading "
                f"{minimum} — that would be "
                f"{float(minimum) / float(quantity):.1f}x the intended "
                f"risk. No order was placed.")
        decimals = details.get("AmountDecimals")
        return round(qty, int(decimals)) if decimals is not None else qty

    @staticmethod
    def _pick(details: dict, preference: tuple) -> Optional[str]:
        supported = details.get("SupportedOrderTypes") or []
        for name in preference:
            if name in supported:
                return name
        return preference[0] if not supported else None

    # ── market data ────────────────────────────────────────────────────────

    def _infoprice(self, symbol: str, groups: str) -> dict:
        uic, atype, _ = self.resolve(symbol)
        params = {"Uic": uic, "AssetType": atype, "FieldGroups": groups}
        ident = self.identity()
        if ident.get("account_key"):
            params["AccountKey"] = ident["account_key"]
        return self._get("trade/v1/infoprices", params)

    def ticker(self, symbol: str) -> dict:
        """{symbol, lastPrice, bid, ask, delayed_minutes, price_type}.

        `lastPrice` — the platform's key, not the documentation's: every
        other adapter returns it and every consumer reads it
        (asset_engine/base.py:2222 for the entry price, :1421 for the mark
        that drives bot-side SL/TP, reconcile_asset, kill_switch,
        pending_closes, manual_trade). Returning "last" instead made every
        Saxo entry skip with NO_PRICE and every position unmanaged — the
        whole adapter inert, silently. "last" is kept as an alias.

        It is the last trade for exchange-traded products and the mid for
        FX (Saxo prints no trades for FX); the delay and the price quality
        are returned beside it so a delayed SIM quote is never mistaken
        for a live one.
        """
        data = self._infoprice(symbol, "Quote,PriceInfoDetails,DisplayAndFormat")
        q = data.get("Quote") or {}
        det = data.get("PriceInfoDetails") or {}
        bid = float(q.get("Bid") or 0)
        ask = float(q.get("Ask") or 0)
        last = float(det.get("LastTraded") or 0)
        if last <= 0:
            last = float(q.get("Mid") or 0) or ((bid + ask) / 2 if bid and ask else 0.0)
        return {
            "symbol": symbol,
            "lastPrice": str(last), "last": str(last),
            "bid": str(bid), "ask": str(ask),
            "delayed_minutes": int(q.get("DelayedByMinutes") or 0),
            "price_type": str(q.get("PriceTypeBid") or q.get("PriceTypeAsk") or ""),
            "market_state": str(q.get("MarketState") or ""),
        }

    def klines(self, symbol: str, interval: str = "1h", limit: int = 200) -> list:
        """Binance-style 12-element rows, oldest first: [openTime, o, h, l,
        c, v, closeTime, quoteVol, trades, takerBase, takerQuote, ignore].
        Bid/ask-only asset types return the mid, volume 0. The last row is
        the live, incomplete bar — as on every other adapter."""
        uic, atype, _ = self.resolve(symbol)
        horizon = HORIZON.get(interval)
        if horizon is None:
            raise ValueError(f"Saxo has no horizon for interval {interval!r}")
        n = max(1, min(int(limit), CHART_MAX))
        data = self._get("chart/v3/charts", {
            "Uic": uic, "AssetType": atype, "Horizon": horizon, "Count": n,
            "FieldGroups": "ChartInfo,Data"})
        span_ms = horizon * 60 * 1000
        rows = []
        for s in data.get("Data") or []:
            ts = _iso_to_ms(str(s.get("Time") or ""))
            if atype in BID_ASK_BARS or "Close" not in s:
                def mid(a, b):
                    try:
                        return (float(s.get(a) or 0) + float(s.get(b) or 0)) / 2
                    except (TypeError, ValueError):
                        return 0.0
                o, h = mid("OpenBid", "OpenAsk"), mid("HighBid", "HighAsk")
                lo, c = mid("LowBid", "LowAsk"), mid("CloseBid", "CloseAsk")
                v = 0
            else:
                o, h = float(s.get("Open") or 0), float(s.get("High") or 0)
                lo, c = float(s.get("Low") or 0), float(s.get("Close") or 0)
                v = s.get("Volume") or 0
            rows.append([ts, str(o), str(h), str(lo), str(c), str(v),
                         ts + span_ms, "0", 0, "0", "0", "0"])
        return rows

    def order_book(self, symbol: str, limit: int = 50) -> dict:
        """Saxo's MarketDepth when the feed carries it; otherwise the same
        synthetic book from bid/ask as OANDA and eToro. On SIM depth is
        not available, so expect the synthetic one there."""
        data = self._infoprice(symbol, "Quote,MarketDepth")
        depth = data.get("MarketDepth") or {}
        bids = list(zip(depth.get("Bid") or [], depth.get("BidSize") or []))
        asks = list(zip(depth.get("Ask") or [], depth.get("AskSize") or []))
        if bids and asks:
            n = max(1, int(limit))
            return {"bids": [[str(p), str(s)] for p, s in bids[:n]],
                    "asks": [[str(p), str(s)] for p, s in asks[:n]]}
        q = data.get("Quote") or {}
        bid, ask = float(q.get("Bid") or 0), float(q.get("Ask") or 0)
        if not (bid and ask):
            return {"bids": [], "asks": []}
        n = min(int(limit), 20)
        return {
            "bids": [[str(round(bid * (1 - i * 0.0001), 6)), "1000000"] for i in range(n)],
            "asks": [[str(round(ask * (1 + i * 0.0001), 6)), "1000000"] for i in range(n)],
        }

    # ── account ────────────────────────────────────────────────────────────

    def balances(self) -> dict:
        ident = self.identity()
        return self._get("port/v1/balances", {"ClientKey": ident["client_key"],
                                              "AccountKey": ident["account_key"]})

    def balance_usdt(self) -> float:
        """Total account value as a bare float, 0.0 when unreadable.

        The name is capital_truth.broker_equity()'s probe — every adapter
        has it — and without it capital_mismatches, pool_oversubscription,
        the engine's pool note and /health/'s capital check were all blind
        on a Saxo-routed config. The currency is the account's;
        net_liquidation() is the pair when the caller needs both.
        """
        try:
            return float((self.balances() or {}).get("TotalValue") or 0.0)
        except Exception as e:  # noqa: BLE001 — 0.0 is the documented contract
            log.warning("saxo balance_usdt failed: %s", e)
            return 0.0

    def net_liquidation(self) -> "tuple[float, str] | None":
        """(TotalValue, Currency) or None when unreadable — IBKRTrader's
        contract, so the sync can file a BrokerEquityReading."""
        try:
            b = self.balances()
            value = float(b.get("TotalValue"))
        except Exception as e:  # noqa: BLE001
            log.warning("saxo net_liquidation failed: %s", e)
            return None
        if value <= 0:
            return None
        return value, str(b.get("Currency") or self.identity().get("currency") or "")

    def _positions(self) -> list:
        ident = self.identity()
        data = self._get("port/v1/positions", {
            "ClientKey": ident["client_key"], "AccountKey": ident["account_key"],
            "FieldGroups": "PositionBase,PositionView,DisplayAndFormat"})
        return [p for p in (data.get("Data") or [])
                if (p.get("PositionBase") or {}).get("Status") in OPEN_STATUSES]

    def get_positions(self) -> list:
        """Open positions in the reconciliation shape. Raises on transport
        errors so reconcile counts the broker unavailable rather than
        assuming flat. Under EndOfDay netting closed lots linger in the
        list until end of day with Status Closed — the filter is what
        keeps them out. Amount's sign for shorts is not documented; a
        negative Amount is read as a short."""
        out = []
        for p in self._positions():
            base, view = p.get("PositionBase") or {}, p.get("PositionView") or {}
            amt = float(base.get("Amount") or 0)
            if amt == 0:
                continue
            out.append({
                "symbol": self._symbol_for(base.get("Uic"), base.get("AssetType"),
                                           p.get("DisplayAndFormat")),
                "qty": abs(amt), "side": "BUY" if amt > 0 else "SELL",
                "position_id": str(p.get("PositionId") or ""),
                "entry": float(base.get("OpenPrice") or 0),
                "current": float(view.get("CurrentPrice") or 0),
                "pnl": float(view.get("ProfitLossOnTrade") or 0),
            })
        return out

    def broker_portfolio(self) -> "list[dict] | None":
        """Holdings as Saxo values them, or None when unreadable —
        IBKRTrader's contract for the portfolio views."""
        try:
            positions = self._positions()
        except Exception as e:  # noqa: BLE001
            log.warning("saxo broker_portfolio failed: %s", e)
            return None
        out = []
        for p in positions:
            base, view = p.get("PositionBase") or {}, p.get("PositionView") or {}
            disp = p.get("DisplayAndFormat") or {}
            amt = float(base.get("Amount") or 0)
            if amt == 0:
                continue
            atype = str(base.get("AssetType") or "")
            out.append({
                "symbol": self._symbol_for(base.get("Uic"), atype, disp),
                "sec_type": SEC_TYPE.get(atype, "CFD"),
                "qty": abs(amt), "side": "BUY" if amt > 0 else "SELL",
                "avg_cost": float(base.get("OpenPrice") or 0),
                "market_price": float(view.get("CurrentPrice") or 0),
                "market_value": float(view.get("MarketValue") or 0),
                "unrealized_pnl": float(view.get("ProfitLossOnTrade") or 0),
                "currency": str(disp.get("Currency") or view.get("ExposureCurrency") or ""),
                "position_id": str(p.get("PositionId") or ""),
                "delayed_minutes": int(view.get("CurrentPriceDelayMinutes") or 0),
            })
        return out

    # ── execution ──────────────────────────────────────────────────────────

    def _order_activities(self, order_id: str) -> list:
        data = self._get("cs/v1/audit/orderactivities",
                         {"OrderId": order_id, "EntryType": "All", "$top": 200})
        return data.get("Data") or []

    def _await_fill(self, order_id: str, attempts: int = FILL_ATTEMPTS,
                    delay: float = FILL_DELAY_S) -> dict:
        """Poll the audit log for the order's fill. Returns the verdict
        {status, executedQty, avgPrice, positionId, rows}. Status is
        FILLED / PARTIALLY_FILLED / CANCELLED / EXPIRED / REJECTED /
        PENDING — PENDING is honest for "not yet", never a fill."""
        last_rows: list = []
        for i in range(max(1, attempts)):
            try:
                rows = self._order_activities(order_id)
            except SaxoApiError as e:
                log.debug("saxo orderactivities(%s): %s", order_id, e)
                rows = []
            last_rows = rows
            final = [r for r in rows if r.get("Status") == "FinalFill"]
            if final:
                r = final[-1]
                return {"status": "FILLED",
                        "executedQty": float(r.get("FilledAmount") or r.get("FillAmount") or 0),
                        "avgPrice": float(r.get("AveragePrice") or r.get("ExecutionPrice") or 0),
                        "positionId": str(r.get("PositionId") or ""), "rows": rows}
            dead = [r for r in rows if r.get("Status") in ("Cancelled", "Expired")
                    or r.get("SubStatus") == "Rejected"]
            if dead:
                r = dead[-1]
                status = ("REJECTED" if r.get("SubStatus") == "Rejected"
                          else str(r.get("Status")).upper())
                # A cancel can arrive AFTER a partial fill: the remainder
                # was pulled, the filled units are real and at the broker.
                # Reporting 0 there would leave a live position no row
                # claims — so the fill wins and the status says PARTIALLY_
                # FILLED, with the cancellation kept in `rows`.
                got = [p for p in rows if p.get("Status") in ("Fill", "FinalFill")]
                if got:
                    p = got[-1]
                    return {"status": "PARTIALLY_FILLED",
                            "executedQty": float(p.get("FilledAmount")
                                                 or p.get("FillAmount") or 0),
                            "avgPrice": float(p.get("AveragePrice")
                                              or p.get("ExecutionPrice") or 0),
                            "positionId": str(p.get("PositionId") or ""),
                            "rows": rows}
                return {"status": status, "executedQty": 0.0, "avgPrice": 0.0,
                        "positionId": "", "rows": rows}
            partial = [r for r in rows if r.get("Status") == "Fill"]
            if partial and i == attempts - 1:
                r = partial[-1]
                return {"status": "PARTIALLY_FILLED",
                        "executedQty": float(r.get("FilledAmount") or 0),
                        "avgPrice": float(r.get("AveragePrice") or 0),
                        "positionId": str(r.get("PositionId") or ""), "rows": rows}
            if i < attempts - 1:
                time.sleep(delay)
        return {"status": "PENDING", "executedQty": 0.0, "avgPrice": 0.0,
                "positionId": "", "rows": last_rows}

    def _child(self, ident: dict, uic: int, atype: str, opposite: str,
               amount: float, order_type: str, price: Optional[float],
               **extra) -> dict:
        # The reference example spells every field on a child; the Learn
        # example omits some. Whether omission inherits from the parent is
        # undocumented, so every field is sent.
        body = {"AccountKey": ident["account_key"], "Uic": uic, "AssetType": atype,
                "BuySell": opposite, "Amount": amount, "OrderType": order_type,
                "ManualOrder": False,
                "OrderDuration": {"DurationType": "GoodTillCancel"}}
        if price is not None:
            body["OrderPrice"] = price
        body.update(extra)
        return body

    def market_order(self, symbol: str, side: str, quantity: float, **kwargs) -> dict:
        """Open a position at market, with the brackets attached at the
        broker. stop_loss / take_profit are absolute prices; `trailing` is
        an absolute distance to market (with stop_loss as the initial
        level, which the help desk says the request still needs).

        The response carries an OrderId only; the fill is read from the
        audit log. PENDING and UNKNOWN are honest states, and UNKNOWN
        (Saxo's 202 TradeNotCompleted) must not be retried by the caller.
        """
        uic, atype, details = self.resolve(symbol)
        ident = self.identity()
        buy = str(side).upper() == "BUY"
        buysell, opposite = ("Buy", "Sell") if buy else ("Sell", "Buy")
        amount = self._amount(details, quantity)
        reference = str(kwargs.get("client_order_id") or uuid.uuid4().hex)[:50]

        body = {"AccountKey": ident["account_key"], "Uic": uic, "AssetType": atype,
                "BuySell": buysell, "Amount": amount, "OrderType": "Market",
                "ManualOrder": False, "OrderDuration": {"DurationType": "DayOrder"},
                "ExternalReference": reference}
        children = []
        stop_loss, take_profit = kwargs.get("stop_loss"), kwargs.get("take_profit")
        trailing = kwargs.get("trailing")
        if stop_loss:
            stop_price = _round_to_tick(float(stop_loss), self._tick(details, "stop", float(stop_loss)))
            if trailing:
                otype = self._pick(details, TRAIL_TYPES) or TRAIL_TYPES[0]
                tick = self._tick(details, "stop", float(stop_loss)) or 0.0
                children.append(self._child(
                    ident, uic, atype, opposite, amount, otype, stop_price,
                    TrailingStopDistanceToMarket=float(trailing),
                    TrailingStopStep=float(tick or trailing)))
            else:
                otype = self._pick(details, STOP_TYPES) or STOP_TYPES[0]
                children.append(self._child(ident, uic, atype, opposite, amount,
                                            otype, stop_price))
        if take_profit:
            target = _round_to_tick(float(take_profit), self._tick(details, "limit", float(take_profit)))
            children.append(self._child(ident, uic, atype, opposite, amount,
                                        "Limit", target))
        if children:
            body["Orders"] = children

        try:
            r = self._write("post", "trade/v2/orders", body,
                            timeout=ORDER_TIMEOUT_S)
        except requests.RequestException as e:
            # The request did not come back. Saxo may have taken the order.
            raise SaxoOrderInDoubt(reference,
                                   f"{type(e).__name__}: {e}") from e
        accepted = {}
        try:
            accepted = r.json() or {}
        except Exception:  # noqa: BLE001 — an unparseable body is judged below
            accepted = {}
        order_id = str(accepted.get("OrderId") or "")

        # An ORDER THAT EXISTS must never be reported as a refusal. Saxo
        # answers a partially accepted order with HTTP 400 and an OrderId
        # (documented: the master is placed, then each related order in
        # turn) — raising there left the parent live at Saxo with no row
        # to own it, which is the one state reconciliation cannot see.
        # So the OrderId decides, not the status code.
        if r.status_code >= 400 and not order_id:
            self._raise_for(r)
        info = accepted.get("ErrorInfo") or {}
        if not order_id:
            if info.get("ErrorCode"):
                raise SaxoApiError(r.status_code, str(info.get("ErrorCode")),
                                   str(info.get("Message") or ""))
            raise SaxoApiError(r.status_code, "NoOrderId",
                               "Saxo accepted nothing and named no order")

        placed = accepted.get("Orders") or []
        child_ids = [str(o.get("OrderId")) for o in placed if o.get("OrderId")]
        child_errors = [o.get("ErrorInfo") for o in placed if o.get("ErrorInfo")]
        # Which child is the stop and which the target, paired by POSITION
        # in the request — Saxo places master, then related #1, then #2, in
        # the order sent. Labelling by index into the RESPONSE made the
        # limit the "stop" whenever the stop child was refused, and the
        # stop rules would then have moved the target.
        stop_id = target_id = ""
        for i, entry in enumerate(placed):
            oid = entry.get("OrderId")
            if not oid or i >= len(children):
                continue
            if children[i].get("OrderType") == "Limit":
                target_id = str(oid)
            else:
                stop_id = str(oid)

        note_bits = []
        if info.get("ErrorCode"):
            note_bits.append(f"order: {info.get('ErrorCode')}")
        for err in child_errors:
            note_bits.append(f"leg refused: {(err or {}).get('ErrorCode')}")

        unknown = r.status_code == 202
        if unknown:
            # Saxo did not hear from the broker within sixty seconds. The
            # order may or may not exist, so it is neither filled nor
            # refused — and it is NEVER resent. `working` gives it an owner.
            polled = {"status": "UNKNOWN", "executedQty": 0.0, "avgPrice": 0.0,
                      "positionId": "", "rows": []}
            note_bits.append("Saxo did not confirm within 60s: this order "
                             "may exist — it is not retried")
        else:
            try:
                polled = self._await_fill(order_id)
            except Exception as e:  # noqa: BLE001
                # The order IS placed. A failure while reading its fill is
                # not a failed order, and letting it escape here made the
                # engine skip with ORDER_ERROR and write no row at all.
                log.warning("saxo: order %s placed, fill unreadable (%s: %s)",
                            order_id, type(e).__name__, e)
                polled = {"status": "PENDING", "executedQty": 0.0,
                          "avgPrice": 0.0, "positionId": "", "rows": []}
                note_bits.append(f"fill unreadable: {type(e).__name__}")

        out = {
            "orderId": order_id, "symbol": symbol, "side": side,
            "executedQty": str(polled["executedQty"]),
            "avgPrice": str(polled["avgPrice"]),
            "status": polled["status"],
            "raw": {"accepted": accepted, "activities": polled["rows"],
                    "reference": reference, "childErrors": child_errors,
                    "httpStatus": r.status_code,
                    "nettingProfile": ident.get("netting_profile")},
        }
        # The brackets are reported as soon as Saxo has ACCEPTED them, fill
        # or no fill: they are GTC and already resting. Withholding them
        # until a fill left the engine holding a position whose legs it
        # could neither move nor cancel.
        if child_ids:
            out["protectiveOrders"] = child_ids
            out["protectedOnFill"] = (not child_errors
                                      and polled["executedQty"] > 0)
            if polled["positionId"]:
                out["protectiveTradeId"] = polled["positionId"]
            if stop_id:
                out["protectiveStopId"] = stop_id
            if target_id:
                out["protectiveTargetId"] = target_id
        if polled["executedQty"] <= 0 and polled["status"] in ("PENDING",
                                                               "UNKNOWN"):
            # base.py books a WORKING row on this flag and polls it; without
            # it the engine booked a full-size OPEN position at the
            # pre-order ticker for an order that had not filled.
            out["working"] = True
        if note_bits:
            out["protectionNote"] = " · ".join(note_bits)
        return out

    # ── orders ─────────────────────────────────────────────────────────────

    def cancel_order(self, order_id: str) -> bool:
        """DELETE one order. True only when Saxo CONFIRMED the cancel.

        A bool, not a dict, and False rather than an exception on a
        refusal: `_cancel_protective_orders` tests `cancel(oid) is False`
        (asset_engine/base.py:1503), so a dict — always truthy — recorded
        a refused cancel as done. A stop that is still resting and read as
        cancelled fires against a flat book and OPENS a reverse position;
        that is the failure this return type exists to prevent.

        Saxo answers 200 with a per-order ErrorInfo on failure, so 200 is
        not success until Orders[] has been read. The success body is not
        documented (it may be empty), so an unparseable 2xx is taken as
        confirmed — the status code is Saxo's own answer — while anything
        that names an error is not.
        """
        ident = self.identity()
        r = self._write("delete", f"trade/v2/orders/{order_id}",
                        params={"AccountKey": ident["account_key"]})
        try:
            self._raise_for(r)
        except SaxoApiError as e:
            log.error("saxo cancel_order(%s) refused: %s — the leg may "
                      "still be resting (GTC)", order_id, e)
            return False
        body = {}
        if r.status_code not in (202, 204):
            try:
                body = r.json() or {}
            except Exception:  # noqa: BLE001 — undocumented success shape
                body = {}
        for o in (body or {}).get("Orders") or []:
            info = o.get("ErrorInfo")
            if info:
                log.error("saxo cancel_order(%s) refused: %s: %s — the leg "
                          "may still be resting (GTC)", order_id,
                          info.get("ErrorCode"), info.get("Message"))
                return False
        if (body or {}).get("ErrorInfo"):
            info = body["ErrorInfo"]
            log.error("saxo cancel_order(%s) refused: %s: %s", order_id,
                      info.get("ErrorCode"), info.get("Message"))
            return False
        return True

    def _related_legs(self, handle: str) -> tuple:
        """(legs, position) — the related open orders of a position, or of
        a parent order, whichever `handle` names.

        Both routes are tried, in that order, and the position route
        answering is not enough: under the FifoRealTime and
        AverageRealTime netting profiles a position has NO related orders
        (Saxo says so plainly) while the stop and the limit exist as
        free-standing orders. Returning the position's empty list there
        made every stop move fail with "no stop leg" on exactly the
        accounts whose brackets are not position-related.
        """
        ident = self.identity()
        try:
            pos = self._get(f"port/v1/positions/{handle}", {
                "ClientKey": ident["client_key"], "AccountKey": ident["account_key"],
                "FieldGroups": "PositionBase"})
            base = pos.get("PositionBase") or {}
            legs = list(base.get("RelatedOpenOrders") or [])
            # A related leg names no instrument — Uic and AssetType sit on
            # the position. Carry them down so the tick size can be found
            # and the PATCH can name them, as the Learn example does.
            for leg in legs:
                leg.setdefault("Uic", base.get("Uic"))
                leg.setdefault("AssetType", base.get("AssetType"))
            if legs:
                return legs, pos
        except SaxoApiError as e:
            if e.status not in (400, 404):
                raise
        data = self._get(f"port/v1/orders/{ident['client_key']}/{handle}",
                         {"FieldGroups": "DisplayAndFormat"})
        rows = data.get("Data") or []
        if not rows:
            return [], None
        order = rows[0]
        legs = list(order.get("RelatedOpenOrders") or [])
        if not legs and order.get("OpenOrderType"):
            legs = [order]          # the handle IS the leg
        return legs, None

    def _move_leg(self, handle: str, kinds: tuple, new_price: float, what: str) -> dict:
        try:
            legs, _pos = self._related_legs(str(handle))
            leg = next((l for l in legs if l.get("OpenOrderType") in kinds), None)
            if leg is None:
                return {"ok": False, "price": None,
                        "reason": f"no {what} leg on {handle}"}
            # The tick size comes from the instrument, and the leg names
            # (Uic, AssetType) — which is all the details endpoint needs.
            # Going through the symbol cache meant a cold worker PATCHed a
            # raw price and Saxo answered PriceNotInTickSizeIncrements.
            details = {}
            uic, atype = leg.get("Uic"), leg.get("AssetType")
            if uic and atype:
                details = self._details(int(uic), str(atype))
            price = _round_to_tick(float(new_price), self._tick(
                details, "stop" if what == "stop" else "limit", float(new_price)))
            ident = self.identity()
            body = {"AccountKey": ident["account_key"],
                    "OrderId": str(leg.get("OrderId")),
                    "OrderType": leg.get("OpenOrderType"),
                    "OrderPrice": price,
                    "Amount": leg.get("Amount"),
                    "OrderDuration": leg.get("Duration") or {"DurationType": "GoodTillCancel"}}
            for k in ("AssetType", "Uic", "BuySell", "StopLimitPrice",
                      "TrailingStopDistanceToMarket", "TrailingStopStep"):
                if leg.get(k) is not None:
                    body[k] = leg[k]
            r = self._write("patch", "trade/v2/orders", body)
            self._raise_for(r)
            res = {}
            try:
                res = r.json() or {}
            except Exception:  # noqa: BLE001
                res = {}
            if r.status_code == 202:
                # Saxo has not heard from the broker. The stop may or may
                # not have moved; recording it as moved would leave the
                # platform showing a level the broker never accepted.
                return {"ok": False, "price": None,
                        "reason": "Saxo did not confirm within 60s "
                                  "(TradeNotCompleted) — the level is "
                                  "unknown, not moved"}
            for o in res.get("Orders") or []:
                if o.get("ErrorInfo"):
                    info = o["ErrorInfo"]
                    return {"ok": False, "price": None,
                            "reason": f"{info.get('ErrorCode')}: {info.get('Message')}"}
            if res.get("ErrorInfo"):
                info = res["ErrorInfo"]
                return {"ok": False, "price": None,
                        "reason": f"{info.get('ErrorCode')}: {info.get('Message')}"}
            return {"ok": True, "price": price, "reason": "",
                    "orderId": str(res.get("OrderId") or leg.get("OrderId"))}
        except Exception as e:  # noqa: BLE001
            log.error("saxo %s(%s) failed: %s", what, handle, e)
            return {"ok": False, "price": None, "reason": str(e)}

    def modify_protective(self, trade_id: str, new_price: float) -> dict:
        """Move the stop leg of position (or parent order) `trade_id`. One
        leg, one field — the target is untouched."""
        return self._move_leg(trade_id, STOP_TYPES + TRAIL_TYPES + ("StopLimit",),
                              new_price, "stop")

    def modify_target(self, trade_id: str, new_price: float) -> dict:
        """Move the Limit leg. The sibling of modify_protective."""
        return self._move_leg(trade_id, ("Limit",), new_price, "target")

    # ── closing ────────────────────────────────────────────────────────────

    def close_needs_position_id(self) -> bool:
        """True when an opposite market order would NOT flatten a position.

        Under the FifoEndOfDay netting profile Saxo keeps BOTH lots Open
        until the evening netting — so the engine's default close (an
        opposite market order) would leave the position live at the broker
        while the platform booked the row CLOSED: double exposure, and a
        P&L from a fill that closed nothing. Under the real-time profiles
        the netting is immediate and the default close is correct.

        The engine asks this before every close; a raise or an unreadable
        identity answers False, which is the pre-2026-09-20 behaviour.
        """
        try:
            return self.identity().get("netting_profile") == "FifoEndOfDay"
        except Exception as e:  # noqa: BLE001 — unknown profile: keep the old path
            log.warning("saxo: netting profile unreadable (%s) — closing with "
                        "an opposite market order", e)
            return False

    def close_position(self, position_id: str, symbol: str,
                       units: Optional[float] = None) -> dict:
        """Close at market. Under FifoEndOfDay the order names the
        PositionId (Saxo's explicit close); under the real-time profiles
        an opposite market order is netted immediately. Returns the
        closing OrderId and the fill verdict from the audit log."""
        ident = self.identity()
        pos = self._get(f"port/v1/positions/{position_id}", {
            "ClientKey": ident["client_key"], "AccountKey": ident["account_key"],
            "FieldGroups": "PositionBase"})
        base = pos.get("PositionBase") or {}
        amt = float(base.get("Amount") or 0)
        amount = abs(float(units)) if units else abs(amt)
        opposite = "Sell" if amt > 0 else "Buy"
        leg = {"AccountKey": ident["account_key"], "Uic": base.get("Uic"),
               "AssetType": base.get("AssetType"), "BuySell": opposite,
               "Amount": amount, "OrderType": "Market", "ManualOrder": False,
               "OrderDuration": {"DurationType": "DayOrder"}}
        if ident.get("netting_profile") == "FifoEndOfDay":
            body = {"PositionId": str(position_id), "Orders": [leg]}
        else:
            body = leg
        r = self._write("post", "trade/v2/orders", body)
        self._raise_for(r)
        acc = r.json() or {}
        order_id = str(acc.get("OrderId") or
                       next((o.get("OrderId") for o in acc.get("Orders") or []
                             if o.get("OrderId")), "") or "")
        polled = self._await_fill(order_id, attempts=3) if order_id else {
            "status": "REJECTED", "executedQty": 0.0, "avgPrice": 0.0, "rows": []}
        return {"orderId": order_id, "positionId": str(position_id),
                "status": polled["status"], "executedQty": str(polled["executedQty"]),
                "avgPrice": str(polled["avgPrice"]), "raw": acc}

    def closing_fill(self, trade) -> "dict | None":
        """What Saxo's OWN exit filled at, or None — Alpaca's contract, read
        by reconcile_asset. The handles are the ones market_order stored:
        the PositionId (closedpositions, ClosingPrice) and the bracket
        OrderIds (the audit log's FinalFill). None means "the broker did
        not tell us", never a number made up."""
        meta = getattr(trade, "metadata", None) or {}
        # snake_case: these are the keys asset_engine/base.py:2710-2727
        # WRITES (protective_trade_id, protective_stop_id,
        # protective_target_id, protective_order_ids). Reading the result
        # spellings instead left the closedpositions path dead in
        # production while passing every test that built its own dict.
        position_id = str(meta.get("protective_trade_id")
                          or meta.get("broker_position_id") or "")
        if position_id:
            try:
                ident = self.identity()
                data = self._get("port/v1/closedpositions", {
                    "ClientKey": ident["client_key"], "AccountKey": ident["account_key"],
                    "FieldGroups": "ClosedPosition", "$top": 500})
                for row in data.get("Data") or []:
                    cp = row.get("ClosedPosition") or {}
                    if str(cp.get("OpeningPositionId") or "") == position_id and cp.get("ClosingPrice"):
                        return {"price": float(cp["ClosingPrice"]),
                                "qty": abs(float(cp.get("Amount") or 0)),
                                "source": "saxo:closedpositions",
                                "time": str(cp.get("ExecutionTimeClose") or "")}
            except Exception as e:  # noqa: BLE001
                log.debug("closing_fill(%s): closedpositions: %s", position_id, e)
        ids = [meta.get("protective_stop_id"), meta.get("protective_target_id")]
        ids += list(meta.get("protective_order_ids") or [])
        for oid in [i for i in ids if i]:
            try:
                rows = self._order_activities(str(oid))
            except Exception as e:  # noqa: BLE001
                log.debug("closing_fill(%s): %s", oid, e)
                continue
            final = [r for r in rows if r.get("Status") == "FinalFill"]
            if final:
                r = final[-1]
                return {"price": float(r.get("AveragePrice") or r.get("ExecutionPrice") or 0),
                        "qty": abs(float(r.get("FilledAmount") or 0)),
                        "source": "saxo:orderactivities",
                        "time": str(r.get("ActivityTime") or "")}
        return None
