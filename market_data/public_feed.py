"""Keyless market data, so every asset class can produce bars.

Requiring broker credentials for BARS was a structural dead end. No keys
meant no bars, no bars meant no indicators and no rule could fire, so the
platform could not generate the evidence that would justify opening a
broker account in the first place. Crypto escaped that because Binance
klines are public — which made crypto the only asset class that could reach
a first trade, and made the platform look crypto-only when it is not.

yfinance closes the gap for everything except options: stocks, ETFs,
indices, commodity futures and FX majors all have free OHLCV.

Two translations are needed, and both are the sort of thing that fails
silently if you get it wrong:

  * SYMBOLS. The platform says XAUUSD; Yahoo says GC=F. It says EURUSD;
    Yahoo says EURUSD=X. A wrong mapping returns an empty frame rather than
    an error, which is indistinguishable from "no history available".

  * INTERVALS. Yahoo has no 4h bar, and 4h is the timeframe the whole rule
    layer reads. 1h data is fetched and resampled, which is exact — a 4h
    candle IS the aggregate of its four hours — but only when the boundaries
    align, so resampling is anchored to the hour.

The client deliberately mimics `BinanceClient.klines`, returning the same
row shape, so `bot_bars._upsert_rows` and `backfill_bars` consume it without
knowing which venue produced it.
"""
from __future__ import annotations

import logging
import math
import time

logger = logging.getLogger(__name__)

# Platform spelling -> Yahoo spelling. Only entries that genuinely differ.
#
# Every entry was verified against the live API before it was written down
# (2026-08-15): a wrong mapping returns an empty frame rather than an error,
# so an unverified guess here is a symbol that silently never has bars.
YF_SYMBOL_MAP = {
    # Metals and energy: Yahoo quotes the front-month future.
    "XAUUSD": "GC=F", "XAGUSD": "SI=F", "XPTUSD": "PL=F", "XPDUSD": "PA=F",
    "WTIUSD": "CL=F", "BRNUSD": "BZ=F", "NGUSD": "NG=F", "HGUSD": "HG=F",
    "HEATOILUSD": "HO=F", "GASOLINEUSD": "RB=F", "OILFUTURES": "CL=F",
    "ALUMUSD": "ALI=F",
    # Grains, softs and meats, in the catalogue's spelling. The short forms
    # (ZCUSD, KCUSD...) predate seed_instruments and are kept as aliases.
    "WHEATUSD": "ZW=F", "CORNUSD": "ZC=F", "SOYUSD": "ZS=F",
    "COFFEEUSD": "KC=F", "COCOAUSD": "CC=F", "COTTONUSD": "CT=F",
    "SUGARUSD": "SB=F", "OATS": "ZO=F", "RICE": "ZR=F",
    "ORANGEJUICE": "OJ=F", "LUMBER": "LBR=F",
    "LIVECATTLE": "LE=F", "LEANHOGS": "HE=F",
    "ZCUSD": "ZC=F", "ZWUSD": "ZW=F", "ZSUSD": "ZS=F",
    "KCUSD": "KC=F", "CTUSD": "CT=F", "SBUSD": "SB=F", "CCUSD": "CC=F",
    # Indices, in the catalogue's spelling. The short forms are aliases.
    "SPX500": "^GSPC", "NSDQ100": "^NDX", "DJ30": "^DJI",
    "RUSSELL2000": "^RUT", "FTSE100": "^FTSE", "DAX40": "^GDAXI",
    "CAC40": "^FCHI", "STOXX50": "^STOXX50E", "NIKKEI225": "^N225",
    "HANGSENG": "^HSI", "ASX200": "^AXJO", "IBEX35": "^IBEX",
    "DXY": "DX-Y.NYB",
    "SPX": "^GSPC", "NDX": "^NDX", "DJI": "^DJI", "RUT": "^RUT",
    "VIX": "^VIX", "FTSE": "^FTSE", "DAX": "^GDAXI", "N225": "^N225",
}

# Catalogue symbols with NO free keyless source. The LME base metals are not
# on Yahoo (ZINC.L and TIN.L look plausible and return an LSE equity and NaN
# closes — worse than nothing), and the gold/silver crosses have no =X pair.
# Pollers skip these by name instead of warning about them forever; they get
# data the day a broker feed covers them.
YF_UNAVAILABLE = {
    "ZINCUSD", "NICKELUSD", "LEADUSD", "TINUSD",
    "XAUGBP", "XAUEUR", "XAGEUR",
}

# ── How much history one call asks for ────────────────────────────────
#
# Yahoo has no 4h bar, so 4h is resampled from 1h — and the first version
# asked for the full 730-day hourly window, twice per symbol per pass (once
# for each interval), to keep 200 rows of it. A research fleet of 150
# symbols would have made that 300 two-year downloads every ten minutes.
# The window is now sized from what the caller keeps, on the worst case
# the platform trades (US equities: 6.5 hours a day, five days in seven —
# forex and crypto over-fetch a little, which costs rows, not rules), and
# the fetched frame is remembered for a few minutes so the 1h request that
# follows the 4h one reuses the same download.
BAR_HOURS = {"1m": 1 / 60, "5m": 5 / 60, "15m": 0.25, "30m": 0.5,
             "1h": 1.0, "2h": 2.0, "4h": 4.0, "6h": 6.0, "8h": 8.0,
             "12h": 12.0}
TRADING_HOURS_PER_DAY = 6.5
CALENDAR_PER_TRADING_DAY = 7.0 / 5.0
WINDOW_SLACK = 1.15
# Yahoo only serves intraday history for a limited window.
YF_MAX_DAYS = {"1m": 7, "5m": 60, "15m": 60, "30m": 60, "1h": 730,
               "1d": 3650, "1wk": 3650}
FRAME_MEMO_S = 300.0
_FRAME_MEMO: dict = {}
_FRAME_MEMO_MAX = 600


def days_for(interval: str, limit: int) -> int:
    """Calendar days of history that keep `limit` bars of `interval`."""
    fetch_interval = RESAMPLE_FROM.get(interval, interval)
    cap = YF_MAX_DAYS.get(fetch_interval, 60)
    try:
        limit = int(limit or 0)
    except (TypeError, ValueError):
        limit = 0
    if limit <= 0:
        return cap
    if fetch_interval == "1d":
        days = limit * CALENDAR_PER_TRADING_DAY * WINDOW_SLACK + 5
    elif fetch_interval == "1wk":
        days = limit * 7 * WINDOW_SLACK + 7
    else:
        hours = limit * BAR_HOURS.get(interval, 1.0)
        days = (hours / TRADING_HOURS_PER_DAY * CALENDAR_PER_TRADING_DAY
                * WINDOW_SLACK + 3)
    return int(min(cap, max(2, math.ceil(days))))


def period_for(days: int) -> str:
    """Yahoo's period spelling for a day count."""
    if days > 730:
        return f"{min(10, math.ceil(days / 365))}y"
    return f"{int(days)}d"


def clear_frame_memo() -> None:
    _FRAME_MEMO.clear()


def _remember_frame(key, days: int, df) -> None:
    if len(_FRAME_MEMO) >= _FRAME_MEMO_MAX:
        cutoff = time.monotonic() - FRAME_MEMO_S
        for k in [k for k, v in _FRAME_MEMO.items() if v[0] < cutoff]:
            _FRAME_MEMO.pop(k, None)
    _FRAME_MEMO[key] = (time.monotonic(), days, df)


def _recall_frame(key, days: int):
    hit = _FRAME_MEMO.get(key)
    if not hit:
        return None
    fetched_at, had_days, df = hit
    if time.monotonic() - fetched_at > FRAME_MEMO_S or had_days < days:
        return None
    return df

# Intervals Yahoo serves natively. Anything else is resampled from these.
YF_NATIVE = {"1m", "5m", "15m", "30m", "1h", "1d", "1wk"}
RESAMPLE_FROM = {"2h": "1h", "4h": "1h", "6h": "1h", "8h": "1h", "12h": "1h"}
PANDAS_RULE = {"2h": "2h", "4h": "4h", "6h": "6h", "8h": "8h", "12h": "12h"}

SUPPORTED_ASSET_CLASSES = {"stock", "etf", "index", "commodity", "forex"}


def yf_symbol(symbol: str, asset_class: str = "") -> str:
    """Platform symbol -> Yahoo symbol."""
    s = (symbol or "").upper()
    if s in YF_SYMBOL_MAP:
        return YF_SYMBOL_MAP[s]
    if asset_class == "forex" and len(s) == 6 and s.isalpha():
        # EURUSD -> EURUSD=X. Yahoo has every major and most crosses.
        return f"{s}=X"
    return s


class YFinanceFeed:
    """Read-only market data. Exposes the subset bot_bars needs.

    Not a broker: it cannot place an order, and nothing should ever route
    execution through it. It exists so the rule layer has something to read
    before a broker relationship exists.
    """

    # bot_bars tags the source from the class name; this keeps a data-only
    # bar distinguishable from one that came from the execution venue.
    _sv_public_feed = True

    def __init__(self, asset_class: str = ""):
        self.asset_class = asset_class

    def klines(self, symbol: str, interval: str = "1h", limit: int = 200,
               start_time=None, end_time=None) -> list[list]:
        """Binance-shaped kline rows: [open_ms, o, h, l, c, volume, ...].

        Returned in the same shape as BinanceClient.klines so the existing
        upsert path does not need to know where the data came from.
        """
        import pandas as pd
        import yfinance as yf

        ysym = yf_symbol(symbol, self.asset_class)
        fetch_interval = RESAMPLE_FROM.get(interval, interval)
        if fetch_interval not in YF_NATIVE:
            logger.warning("[public_feed] %s: interval %r is not available "
                           "from Yahoo and cannot be resampled", symbol, interval)
            return []

        days = days_for(interval, limit)
        memo_key = (ysym, fetch_interval)
        df = _recall_frame(memo_key, days)
        if df is None:
            try:
                df = yf.Ticker(ysym).history(period=period_for(days),
                                             interval=fetch_interval)
            except Exception as e:
                logger.warning("[public_feed] %s (%s) history failed: %s",
                               symbol, ysym, e)
                return []
            if df is not None and not df.empty:
                _remember_frame(memo_key, days, df)

        if df is None or df.empty:
            # An unmapped symbol returns an empty frame rather than raising,
            # which otherwise reads as "this instrument has no history".
            logger.warning("[public_feed] %s resolved to Yahoo symbol %r and "
                           "returned no rows — check the symbol mapping",
                           symbol, ysym)
            return []

        if interval in RESAMPLE_FROM:
            rule = PANDAS_RULE[interval]
            df = (df.resample(rule, origin="start_day")
                    .agg({"Open": "first", "High": "max", "Low": "min",
                          "Close": "last", "Volume": "sum"})
                    .dropna())

        if limit:
            df = df.tail(int(limit))

        rows = []
        for ts, r in df.iterrows():
            try:
                open_ms = int(pd.Timestamp(ts).timestamp() * 1000)
                rows.append([
                    open_ms,
                    str(r["Open"]), str(r["High"]), str(r["Low"]),
                    str(r["Close"]), str(r.get("Volume", 0) or 0),
                ])
            except Exception:
                continue
        return rows

    def ticker(self, symbol: str) -> dict:
        """Last price, in the shape the bots read."""
        import yfinance as yf
        ysym = yf_symbol(symbol, self.asset_class)
        try:
            df = yf.Ticker(ysym).history(period="1d", interval="1m")
            if df is not None and not df.empty:
                return {"symbol": symbol,
                        "lastPrice": str(float(df["Close"].iloc[-1]))}
        except Exception as e:
            logger.warning("[public_feed] ticker(%s) failed: %s", symbol, e)
        return {"symbol": symbol, "lastPrice": "0"}


def public_feed_for(asset_class: str):
    """A keyless market-data client for this asset class, or None.

    Options are absent on purpose: there is no free option-chain source
    worth trusting, and options route exclusively through IBKR.
    """
    if asset_class == "crypto":
        from bot_program.engine.binance_client import BinanceClient
        client = BinanceClient("", "", testnet=False)
        client._sv_public_feed = True
        return client
    if asset_class in SUPPORTED_ASSET_CLASSES:
        return YFinanceFeed(asset_class=asset_class)
    return None
