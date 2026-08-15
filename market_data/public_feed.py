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

# Yahoo only serves intraday history for a limited window.
YF_PERIOD_FOR = {
    "1m": "7d", "5m": "60d", "15m": "60d", "30m": "60d",
    "1h": "730d", "4h": "730d", "1d": "10y", "1wk": "10y",
}

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

        period = YF_PERIOD_FOR.get(fetch_interval, "60d")
        try:
            df = yf.Ticker(ysym).history(period=period, interval=fetch_interval)
        except Exception as e:
            logger.warning("[public_feed] %s (%s) history failed: %s",
                           symbol, ysym, e)
            return []

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
