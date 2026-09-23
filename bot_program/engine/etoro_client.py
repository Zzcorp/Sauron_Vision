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

2. THE ENVIRONMENT SEGMENT IS NOT A RULE, IT IS A TABLE. v2 omits it for
   the real account:
       /api/v2/trading/execution/demo/orders   vs   /api/v2/trading/execution/orders
   v1 omits it for portfolio, aggregate-portfolio and the close — and WRITES
   it for pnl:
       /api/v1/trading/info/demo/portfolio     vs   /api/v1/trading/info/portfolio
       /api/v1/trading/info/demo/pnl           vs   /api/v1/trading/info/real/pnl
   This header used to claim v1 always wrote "real", and called that "encoded
   in two helpers rather than discovered in production on a real key". It was
   discovered in production on a real key: the operator's first live save
   probed a 404 on 2026-09-22, and every real-account read AND the close were
   wrong while order placement (v2) was right — a venue that would take an
   order and refuse every exit. Each entry in `_V1_INFO_REAL_SEG` and
   `_V1_EXEC_REAL_SEG` now carries the status code that measured it, and an
   unattested tail raises. Everything under /market-data/ carries no
   environment at all.

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
  * `options` — none.
  * `leverage` as a TIER — no. The capabilities tier of that name means
    set_leverage/set_margin_type: Binance futures' per-SYMBOL venue state,
    set once before a plain order (binance_futures_client.ensure_config).
    eToro's leverage is a FIELD OF EACH ORDER BODY. This client sends 1
    unless the caller passes `leverage=`: a whole number in
    [1, LEVERAGE_MAX] rides the body as-is, anything else is refused
    before the POST (`_leverage`), and above 1 a missing stop_loss is
    refused too — from the public reference (unmeasured): "a stopLossRate
    is required when leverage is greater than 1". The fill result carries
    what the venue ECHOES (`venueStopLoss`/`venueTakeProfit` off
    positionExecutions[0], absent when the wire lacks them) and says when
    the lookup could not be read at all (`pollFailed`). Nothing here reads
    eToro's per-instrument `leverageValues` (its eligibility endpoint has
    met no key), and no leveraged order has ever met eToro
    (deploy/ETORO_DEPARTURE.md §4 D2b).
  * an UNPROTECTED order nobody asked for — a stop_loss or take_profit that
    is present and not a price is refused before the POST (`_level`), never
    dropped; and a rates payload without a `rates` list, or a rate row
    spelled with none of bid/ask/lastExecution, raises rather than reading
    as a quiet market (`ticker`), because neither shape has met a real key.

Symbol convention: the platform's spelling is passed to /search as
`internalSymbolFull`. No renaming table exists yet because none has been
measured; the first symbol eToro spells differently will fail loudly here
rather than silently elsewhere, and that is where the table starts.
"""
from __future__ import annotations

import logging
import math
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

#: THE MOST THIS ADAPTER WILL EVER PUT IN AN ORDER BODY, whatever the caller
#: asks. EQUAL to asset_engine/base.MAX_ORDER_LEVERAGE and pinned equal by
#: tests/test_etoro_leverage.py — restated rather than imported because
#: engine/ does not import asset_engine/ (base.py imports this package).
#: A ceiling on what LEAVES the box, not a claim about what eToro accepts:
#: the allowed multipliers are per instrument, settlementType and direction
#: (`leverageValues`, public reference, unmeasured). A shell caller on the
#: live key cannot send more than the engine could ever ask for.
LEVERAGE_MAX = 5


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


def _level(value, name: str, symbol: str, side: str):
    """A protective level for the order body, or None when the caller sent
    none — and a RAISE, before any POST, for a level that is not a price.

    `market_order` used to attach the legs under `if stop_loss:`, so a stop
    the engine computed at 0.0 was dropped SILENTLY and the order went out
    unprotected at leverage 1 — while a NEGATIVE stop, being truthy, was
    sent as stopLossRate. The routes to such a stop, most open first: the
    Take Trade lane, where an engine-derived BUY stop of 0 passes the
    wrong-side check `stop < price < target` and the cost filter is
    information, never a refusal (manual_trade); the bot lane's
    sizing.apply_stop_floor, which widens a BUY stop to entry * (1 - f/cap)
    AFTER the cost filter and before the order when an extras
    max_notional_fraction sits below the risk fraction; and stop_and_target's
    pct fallback with stop_loss_pct >= 100 (asset_models.AssetBotConfig, no
    validator, no form clean), which the bot lane's cost filter refuses
    unless extras use_cost_filter is False. None stays None: a caller that
    sent no level asked for no leg, and that is its choice.

    ValueError is what both callers already catch: asset_engine/base.py
    execute_entry's `except Exception` books it as skips.ORDER_ERROR
    ("live order failed: ..."); manual_trade returns it in the error dict.
    The message LEADS with the fact because skips.record keeps 200
    characters and why_no_trade prints 88.

    KNOWN, 2026-09-23: the Take Trade lane wraps that dict in "The order
    MAY have reached the broker" (manual_trade, the except after
    client.market_order), which is false for this refusal — nothing was
    sent. Until that except reads the refusal apart from a transport
    error, the operator is told to check the broker for an order that
    never left the box.
    """
    if value is None:
        return None
    try:
        if isinstance(value, bool):
            raise ValueError
        level = float(value)
    except (TypeError, ValueError):
        raise ValueError(
            f"eToro NOT SENT: {name} {value!r} is not a number "
            f"({symbol} {side}). The caller asked for a broker-held leg; "
            f"an order without it would be unprotected at leverage 1."
        ) from None
    if not math.isfinite(level) or level <= 0:
        raise ValueError(
            f"eToro NOT SENT: {name} {level!r} is not a price "
            f"({symbol} {side}). The caller asked for a broker-held leg; "
            f"an order without it would be unprotected at leverage 1."
        )
    return level


def _leverage(value, symbol: str, side: str) -> int:
    """The `leverage` field of the order body: 1 when the caller sent none,
    else a whole number in [1, LEVERAGE_MAX] — and a RAISE, before any
    POST, for anything else. A string, a bool, a fraction, a NaN, a zero
    or a negative is refused rather than rounded or defaulted: a multiplier
    this adapter silently replaced with 1 is a default nobody asked for.
    ValueError, as `_level` raises it, so both callers book it the same
    way (execute_entry: skips.ORDER_ERROR; manual_trade: the error dict);
    the message LEADS with the fact (skips.record keeps 200 chars,
    why_no_trade prints 88).
    """
    if value is None:
        return 1
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(
            f"eToro NOT SENT: leverage {value!r} is not a number "
            f"({symbol} {side}). Nothing here sends 1 in its place."
        )
    lev = float(value)
    if not math.isfinite(lev) or lev < 1 or lev != int(lev):
        raise ValueError(
            f"eToro NOT SENT: leverage {value!r} is not a whole number >= 1 "
            f"({symbol} {side}). eToro's multiplier is an integer and "
            f"nothing here rounds one."
        )
    if lev > LEVERAGE_MAX:
        raise ValueError(
            f"eToro NOT SENT: leverage {int(lev)} is past this adapter's "
            f"{LEVERAGE_MAX} ceiling ({symbol} {side}). The cap is on what "
            f"leaves the box; the venue refuses at the order what it will "
            f"not take."
        )
    return int(lev)


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
        # instrumentId -> the spelling eToro itself answered on /search.
        # Kept because instrument_id accepts a LONE result of any
        # spelling; a reader (etoro_smoke) shows the mismatch instead
        # of painting the id green. No consumer reads it.
        self._venue_spelling: dict = {}

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

    #: WHAT THE REAL ACCOUNT DOES WITH THE ENVIRONMENT SEGMENT, PER TAIL.
    #:
    #: Not a rule — a TABLE, because eToro is not consistent and a rule would
    #: be wrong for `pnl`. Every entry was MEASURED on 2026-09-22 with a live
    #: real key, read-only, each beside a known-200 control:
    #:
    #:   /info/aggregate-portfolio        200   /info/real/aggregate-portfolio  404
    #:   /info/portfolio                  200   /info/real/portfolio            404
    #:   /info/pnl                        404   /info/real/pnl                  200
    #:   /execution/market-close-orders/  405   /execution/real/market-close-*  404
    #:
    #: The 405 attests the close WITHOUT sending one: the close is a POST, so a
    #: GET cannot close anything, and Method Not Allowed proves the path exists
    #: where 404 proves it does not.
    #:
    #: DEMO writes "demo/" for every tail measured. An unlisted tail RAISES
    #: rather than composing a URL nobody has ever seen answer: this adapter's
    #: previous header called its paths "encoded ... rather than discovered in
    #: production on a real key", and they were discovered in production on a
    #: real key. A tail nobody measured is "could not ask", not "probably".
    _V1_INFO_REAL_SEG = {
        "aggregate-portfolio": "",
        "portfolio": "",
        "pnl": "real/",
    }
    _V1_EXEC_REAL_SEG = {
        "market-close-orders": "",
    }

    def _seg(self, table: dict, key: str, tail: str) -> str:
        """The environment segment for `key`, or a raise naming the tail.

        Demo writes "demo/" for everything measured. Real reads the table,
        and an unattested tail is refused — loudly, at the call, rather than
        as a 404 nobody connects to a guess made months earlier.
        """
        if self.demo:
            return "demo/"
        try:
            return table[key]
        except KeyError:
            raise LookupError(
                f"eToro path not attested: {tail!r}. Nobody has measured "
                f"whether the real account writes the environment segment "
                f"for this endpoint, and eToro is not consistent — "
                f"/info/pnl writes it while /info/portfolio omits it. Check "
                f"api-portal.etoro.com for your tail and add it to the "
                f"table, with the status codes you measured."
            ) from None

    def _v1_info(self, tail: str) -> str:
        seg = self._seg(self._V1_INFO_REAL_SEG, tail.split("/")[0], tail)
        return f"{BASE}/api/v1/trading/info/{seg}{tail}"

    def _v1_exec(self, tail: str) -> str:
        seg = self._seg(self._V1_EXEC_REAL_SEG, tail.split("/")[0], tail)
        return f"{BASE}/api/v1/trading/execution/{seg}{tail}"

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
                self._venue_spelling[iid] = sym
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
        """{lastPrice, symbol[, bid, ask]} — THREE STATES, never two.

          raise           could not ask: a transport/HTTP error, an unknown
                          spelling (instrument_id), a 200 whose body has no
                          `rates` list, or a rate row spelled with none of
                          bid/ask/lastExecution — shapes this adapter has
                          never seen answer, which is unmeasured, not empty.
          lastPrice "0"   the venue ANSWERED and had no rate: an empty list,
                          or a row whose believed keys are all 0/None. The
                          platform's own no-price sentinel — ibkr_client,
                          oanda_client, paper_trader and public_feed return
                          this literal and every reader tests `> 0` and
                          skips. One spelling, "0", from both branches.
          lastPrice > 0   a price, with bid/ask beside it.

        The keys `rates` and bid/ask/lastExecution are a BELIEF from the
        public reference; this GET was not among the reads measured on
        2026-09-22. Record the measured keys here the day it meets a real
        key, as _V1_INFO_REAL_SEG records its status codes.
        """
        iid = self.instrument_id(symbol)
        r = self._sess().get(f"{BASE}/api/v1/market-data/instruments/rates",
                             params={"instrumentIds": str(iid)},
                             headers=self._headers(), timeout=self.timeout)
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, dict) or "rates" not in data:
            # THREE STATES. A 200 whose body does not carry `rates` is not
            # "no rates" — it is a shape this adapter has never seen answer.
            # The rates endpoint was NOT among the reads measured on
            # 2026-09-22 (search, aggregate-portfolio, portfolio, real/pnl,
            # the close's 405), so the key is still a belief; read as an
            # empty list it would make every symbol a quiet market forever,
            # which is how the nested totals block hid for four commands.
            # Raise, naming what came back, as `_seg` does for an unattested
            # tail and instrument_id for an unknown spelling. Every reader
            # catches it: base.py's manage tick logs it and still runs the
            # clock exit; propose_entry skips NO_PRICE "ticker failed".
            keys = (sorted(data) if isinstance(data, dict)
                    else type(data).__name__)
            raise LookupError(
                f"eToro rates payload for {symbol!r} (id {iid}) carries no "
                f"'rates' key — got {keys}. The shape has not met a real "
                f"key; measure the GET beside a known-200 control and fix "
                f"the key before trusting a 0 here."
            )
        rates = data.get("rates")
        if rates is not None and not isinstance(rates, list):
            raise LookupError(
                f"eToro rates payload for {symbol!r} (id {iid}) carries "
                f"'rates' as {type(rates).__name__}, not a list — an "
                f"unmeasured shape; measure the GET before trusting a 0 here."
            )
        rates = rates or []
        p = rates[0] if rates else {}
        if rates and (not isinstance(p, dict)
                      or not ({"bid", "ask", "lastExecution"} & set(p))):
            # THE SAME RULE ONE LEVEL DOWN. The per-rate keys are as
            # unmeasured as the top-level one: a row spelled any other way
            # used to read `.get(...) or 0` as a quiet market with no line
            # at all — the failure the raise above exists to end.
            row = sorted(p) if isinstance(p, dict) else type(p).__name__
            raise LookupError(
                f"eToro rate row for {symbol!r} (id {iid}) carries none of "
                f"bid/ask/lastExecution — got {row}. Measure the row's keys "
                f"before trusting a 0 here."
            )
        bid = float(p.get("bid") or 0)
        ask = float(p.get("ask") or 0)
        last = float(p.get("lastExecution") or 0)
        if not last:
            last = (bid + ask) / 2 if bid and ask else (bid or ask)
        if not last:
            # THE VENUE ANSWERED: nothing — an empty list, or a row whose
            # believed keys are all 0/None. lastPrice "0" is the platform's
            # no-price sentinel: ibkr_client, oanda_client, paper_trader and
            # public_feed return this same literal, and every reader
            # (base._mark_price, propose_entry, manual_trade._mark_for,
            # pending_closes, reconcile_asset, kill_switch) tests `> 0` and
            # skips. ONE spelling from both empty branches — "0", never the
            # "0.0" str(0.0) used to give the row branch. Not None: the
            # readers call .get on the dict. Not a raise: a shut market is an
            # answer, not a failure to ask. Said with the id, because the
            # engine's own line ("no usable mark from the broker") carries
            # only the name; INFO rather than WARNING because base.py already
            # WARNs per position per tick and US stocks are shut two thirds
            # of the day.
            log.info("eToro ticker(%s): instrument %s answered 200 with no "
                     "price (%s) — reporting the platform's 0 sentinel, "
                     "which every reader skips on", symbol, iid,
                     "empty rates list" if not rates
                     else "bid/ask/lastExecution all empty")
            return {"lastPrice": "0", "symbol": symbol}
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
        # MEASURED 2026-09-23 on the real key (GLDM, FourHours, 5):
        #   {"candles": [{"instrumentId": 3190,
        #                 "candles": [{close, fromDate, high, instrumentID,
        #                              low, open, volume}, ... x5],
        #                 "rangeOpen", "rangeHigh", "rangeLow", "rangeClose",
        #                 "volume"}],
        #    "interval": ...}
        # One GROUP per instrument, the bars one level down. This method
        # used to read the group as a bar: one row, close "0", for every
        # symbol — which bot_bars refused (close <= 0) WITHOUT falling back
        # to the public feed, because the venue had "answered" a row. A
        # config on eToro would have had no 4h bars at all. THREE STATES: a
        # group's inner list is the bars; a flat list of bars (the shape
        # this adapter believed before it met a key) is still read; a
        # group that carries neither is an unmeasured shape and RAISES —
        # bot_bars logs "klines failed" and then does fall back.
        groups = (data.get("candles") if isinstance(data, dict) else data) or []
        candles = []
        for g in groups:
            if isinstance(g, dict) and isinstance(g.get("candles"), list):
                candles.extend(c for c in g["candles"] if isinstance(c, dict))
            elif isinstance(g, dict) and "close" in g:
                candles.append(g)
            else:
                shape = sorted(g) if isinstance(g, dict) else type(g).__name__
                raise LookupError(
                    f"eToro candles payload for {symbol!r} (id {iid}) carries "
                    f"a row with neither a 'candles' list nor a 'close' — "
                    f"got {shape}. An unmeasured shape; measure the GET "
                    f"before trusting a bar here.")
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

    #: WHERE THE MONEY IS IN THE AGGREGATE PAYLOAD. Measured 2026-09-22
    #: against a live real account: `account()` returns accountCurrency at
    #: the TOP level and every figure one level down, under `accountTotals`
    #: — accountTotalValue, accountAvailableCash, accountBalance,
    #: accountCurrentPnl, accountFrozenCash, accountTotalUsedMargin, all
    #: numeric. This adapter read the first two at the top level and found
    #: neither: the URLs were corrected in ea0bb54 and the field names were
    #: still wrong, so the sync ran clean and wrote no equity at all.
    @staticmethod
    def _totals(info: dict) -> dict:
        """The nested totals block, or {} when the payload has no such shape.

        {} rather than a raise: a caller reading a missing figure gets None
        from `.get`, which is already every caller's unmeasured answer.
        """
        if not isinstance(info, dict):
            return {}
        block = info.get("accountTotals")
        return block if isinstance(block, dict) else {}

    def margin_cells(self) -> "dict | None":
        """{"available_cash", "used_margin", "currency"} from ONE aggregate
        read, or None when the read failed. Each figure is None when the
        payload lacks its key — three states; a 0 is a measurement. The
        KEY NAMES were measured 2026-09-22 (accountAvailableCash,
        accountTotalUsedMargin under accountTotals, see the comment above
        `_totals`); their arithmetic (available + used + pnl = total) is
        the public reference's claim, unmeasured. One more GET per sync;
        nothing on an entry path calls this — the gate reads the cells."""
        try:
            info = self.account()
        except Exception as e:  # noqa: BLE001
            log.warning("eToro margin_cells failed: %s", e)
            return None
        totals = self._totals(info)

        def _num(key):
            raw = totals.get(key)
            try:
                return None if raw is None else float(raw)
            except (TypeError, ValueError):
                return None

        return {"available_cash": _num("accountAvailableCash"),
                "used_margin": _num("accountTotalUsedMargin"),
                "currency": str(info.get("accountCurrency") or "")}

    def balance_usdt(self) -> float:
        """Available cash in the ACCOUNT currency, not USDT — the name is the
        contract's, the unit is eToro's. Caller converts if it must.

        A FAILED READ ANSWERS 0.0, which cannot be told from an empty
        account. That is not a choice made here: six adapters return a bare
        float on this method and `capital_truth` reads it duck-typed, so one
        of them answering None would break the contract the other five keep.
        The consumer is honest about it — capital_truth treats a zero from a
        live broker as unmeasured, "this module cannot tell which" — so the
        gap is contained rather than corrected, and it is named here so the
        next reader meets it before they trust the number.
        """
        try:
            return float(self._totals(self.account())
                         .get("accountAvailableCash") or 0)
        except Exception as e:  # noqa: BLE001
            log.warning("eToro balance fetch failed: %s", e)
            return 0.0

    def net_liquidation(self) -> "tuple[float, str] | None":
        """(total value, currency) or None when unreadable — the same
        contract as IBKRTrader, so sync_broker_account can read it.

        The value comes from the nested totals block; the CURRENCY does not
        — eToro puts accountCurrency at the top level, and that read was
        always right.

        A zero answers None, deliberately and in step with SaxoTrader's
        identical rule: capital_truth states the reasoning, that a zero from
        a live broker cannot be told from an API answering badly. It means an
        empty account reads as unmeasured, which is this platform's
        convention and not eToro's peculiarity; changing it belongs in a
        change that moves every adapter at once.
        """
        try:
            info = self.account()
        except Exception as e:  # noqa: BLE001
            log.warning("eToro net_liquidation failed: %s", e)
            return None
        try:
            value = float(self._totals(info).get("accountTotalValue"))
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
            row = {
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
            }
            # THE VENUE'S OWN MULTIPLIER, when the row carries one. From the
            # public reference (unmeasured): a /portfolio position has a
            # `leverage` field. Absent on the wire -> absent here, never 1:
            # /treasury/ prints the em dash for a row that did not say.
            # `units` stay units at any leverage (believed; §4 D2b measures).
            lev = p.get("leverage")
            if lev is not None and not isinstance(lev, bool):
                try:
                    if float(lev) >= 1 and float(lev) == int(float(lev)):
                        row["leverage"] = int(float(lev))
                except (TypeError, ValueError):
                    pass
            out.append(row)
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

        A stop_loss / take_profit that is PRESENT and not a price (0, a
        negative, NaN, a non-number) RAISES ValueError before any POST: the
        caller asked for a broker-held leg, and an order sent without it is
        unprotected at leverage 1. None means no leg was asked for.

        `leverage` (kwarg, default absent) rides the body as an integer in
        [1, LEVERAGE_MAX] or RAISES before the POST (`_leverage`); above 1
        a None stop_loss raises too (public reference, unmeasured: eToro
        requires a stopLossRate there). Units are untouched by it: leverage
        changes the margin eToro locks for the same units and nothing else
        this adapter sends. No settlementType is sent: what eToro assigns
        when the body omits it is unmeasured (§4 D2b reads it back).
        `venueStopLoss`/`venueTakeProfit` echo what the lookup says the
        venue holds; `pollFailed` says the lookup itself could not be read.
        """
        rid = self._rid(kwargs.get("client_order_id"))
        # THE MULTIPLIER, validated before anything else is built: 1 when
        # the caller sent none (the literal this body carried until
        # 2026-09-23), the caller's whole number otherwise, a raise for
        # anything that is neither. It scales the margin eToro locks, not
        # `units` — the same units at any leverage lose the same money at
        # the stop, which is the invariant asset_engine/sizing.py keeps.
        leverage = _leverage(kwargs.get("leverage"), symbol, side)
        body = {
            "action": "open",
            "transaction": "buy" if side == "BUY" else "sellShort",
            "symbol": str(symbol),
            "units": float(quantity),
            "leverage": leverage,
        }
        # REFUSED BEFORE THE POST when a level is present and not a price.
        # `if stop_loss:` dropped a 0.0 leg silently and SENT a negative
        # one; `_level` raises for both, and None stays "no leg asked for".
        stop_loss = _level(kwargs.get("stop_loss"), "stop_loss", symbol, side)
        take_profit = _level(kwargs.get("take_profit"), "take_profit",
                             symbol, side)
        protected = False
        if stop_loss is not None:
            body["stopLossRate"] = stop_loss
            body["stopLossType"] = "fixed"
        if take_profit is not None:
            body["takeProfitRate"] = take_profit
        if stop_loss is not None and take_profit is not None:
            protected = True
        if leverage > 1 and stop_loss is None:
            # From the public reference (unmeasured): "a stopLossRate is
            # required when leverage is greater than 1". Refused here, in
            # `_level`'s voice, rather than sent for eToro to refuse — and
            # never sent at 1 instead. The bot lane always passes both legs
            # (asset_engine/base.py execute_entry); this protects every
            # other caller and the D2b shell snippet.
            raise ValueError(
                f"eToro NOT SENT: leverage {leverage} with no stop_loss "
                f"({symbol} {side}). eToro requires a stop above leverage 1; "
                f"an order without one is refused here, before the POST."
            )

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

        polled = self._await_fill(reference)
        # THREE STATES for the lookup: a payload (read), None (no poll could
        # be read — a transport error or the shared 20/60 s quota, public
        # reference, unmeasured). `poll_failed` travels out as `pollFailed`
        # so a WORKING row can say "the lookup failed" instead of "eToro is
        # holding it"; {} is never invented as a reading.
        poll_failed = polled is None
        polled = polled or {}
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
        # WHAT THE VENUE HOLDS, when the lookup says: the fixture and the
        # public reference (unmeasured) put stopLossRate/takeProfitRate on
        # positionExecutions[]. Absent on the wire -> absent here. base.py
        # compares them with what was SENT; eToro's 0.0001 "no stop"
        # sentinel (public reference, unmeasured) then reads as a rewrite,
        # which is the truth: the venue holds no stop.
        for key, wire in (("venueStopLoss", "stopLossRate"),
                          ("venueTakeProfit", "takeProfitRate")):
            raw_level = first.get(wire)
            if raw_level is not None and not isinstance(raw_level, bool):
                try:
                    out[key] = float(raw_level)
                except (TypeError, ValueError):
                    pass
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
        if status == "PENDING":
            if poll_failed:
                # NOT "eToro is holding it": nobody could read the lookup.
                # Filled, refused and waiting are all possible; the row
                # books WORKING either way and the alert says which.
                out["pollFailed"] = True
            # AN ACCEPTANCE IS NOT A POSITION. Every non-terminal lookup
            # status (Received, Placed, WaitingForMarket, PendingTriggered
            # Rate) — and a poll that could not be read at all, which also
            # lands here — has nothing filled. base.py and manual_trade book
            # a WORKING row on this flag, the contract IBKR (ibkr_client
            # .market_order) and Saxo (saxo_client.market_order) already
            # keep; without it both lanes booked a full-size OPEN position
            # at the pre-order ticker for an order eToro was merely holding,
            # and the pre-open reconcile (13:00/13:15 UTC) then orphan-
            # closed the row at a mark while the order filled at 13:30 with
            # a bracket the platform never saw.
            #
            # WHAT THIS ADAPTER CANNOT DO NEXT, said here so nobody reads
            # "working" as "watched": it has no order_status — orders:lookup
            # is keyed by the x-request-id, which neither lane persists —
            # and no cancel_order ("WHAT IT REFUSES TO CLAIM" above). A
            # WORKING eToro row is therefore polled by nobody and withdrawn
            # by nobody: it stays WORKING, alerts daily while its tick runs,
            # and is resolved at eToro by hand. Loud and never CLOSED is the
            # better of the two wrongs.
            out["working"] = True
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
