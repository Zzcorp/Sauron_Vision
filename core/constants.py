"""Sauron Vision — Global constants and enums."""


# Asset classes
class AssetClass:
    STOCK = "stock"
    FOREX = "forex"
    COMMODITY = "commodity"
    INDEX = "index"
    ETF = "etf"
    CRYPTO = "crypto"
    BOND = "bond"
    OPTIONS = "options"
    CFD = "cfd"

    CHOICES = [
        (STOCK, "Stock"),
        (FOREX, "Forex"),
        (COMMODITY, "Commodity"),
        (INDEX, "Index"),
        (ETF, "ETF"),
        (CRYPTO, "Cryptocurrency"),
        (BOND, "Bond"),
        (OPTIONS, "Options"),
        (CFD, "CFD"),
    ]


# Timeframes for price data
class Timeframe:
    M1 = "1m"
    M5 = "5m"
    M15 = "15m"
    M30 = "30m"
    H1 = "1h"
    H4 = "4h"
    D1 = "1d"
    W1 = "1w"

    CHOICES = [
        (M1, "1 Minute"),
        (M5, "5 Minutes"),
        (M15, "15 Minutes"),
        (M30, "30 Minutes"),
        (H1, "1 Hour"),
        (H4, "4 Hours"),
        (D1, "1 Day"),
        (W1, "1 Week"),
    ]


# Signal directions
class Direction:
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"

    CHOICES = [
        (BULLISH, "Bullish"),
        (BEARISH, "Bearish"),
        (NEUTRAL, "Neutral"),
    ]


# Signal urgency levels
class Urgency:
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

    CHOICES = [
        (CRITICAL, "Critical — Act Now"),
        (HIGH, "High — Act Today"),
        (MEDIUM, "Medium — Watch Closely"),
        (LOW, "Low — On Radar"),
    ]


# Market trading sessions (UTC)
MARKET_SESSIONS = {
    "tokyo": {"open": "00:00", "close": "06:00"},
    "london": {"open": "07:00", "close": "15:30"},
    "new_york": {"open": "13:30", "close": "20:00"},
    "sydney": {"open": "21:00", "close": "05:00"},
}

# Major forex pairs
MAJOR_FOREX_PAIRS = [
    "EURUSD", "GBPUSD", "USDJPY", "USDCHF",
    "AUDUSD", "USDCAD", "NZDUSD",
]

# Key commodities
KEY_COMMODITIES = [
    "XAUUSD",   # Gold
    "XAGUSD",   # Silver
    "WTIUSD",   # WTI Crude Oil
    "BRNUSD",   # Brent Crude
    "NGUSD",    # Natural Gas
    "HGUSD",    # Copper
    "WHEATUSD", # Wheat
    "CORNUSD",  # Corn
]

# Key FRED series for macro monitoring
FRED_SERIES = {
    "FEDFUNDS": "Federal Funds Rate",
    "DGS10": "10-Year Treasury Yield",
    "DGS2": "2-Year Treasury Yield",
    "T10Y2Y": "10Y-2Y Treasury Spread",
    "CPIAUCSL": "Consumer Price Index",
    "UNRATE": "Unemployment Rate",
    "GDP": "Gross Domestic Product",
    "DEXUSEU": "USD/EUR Exchange Rate",
    "VIXCLS": "VIX Volatility Index",
    "DCOILWTICO": "WTI Crude Oil Price",
    "M2SL": "M2 Money Supply",
    "BAMLH0A0HYM2": "High Yield Bond Spread",
}
