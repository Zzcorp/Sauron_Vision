"""Crypto market adapter — CoinGecko (free) + Binance public API."""
import requests
import logging
from decimal import Decimal

logger = logging.getLogger(__name__)

COINGECKO_BASE = "https://api.coingecko.com/api/v3"
BINANCE_BASE = "https://api.binance.com/api/v3"

# Map Sauron symbols to CoinGecko IDs
SYMBOL_MAP = {
    "BTCUSD": "bitcoin", "ETHUSD": "ethereum", "XRPUSD": "ripple",
    "SOLUSD": "solana", "ADAUSD": "cardano", "DOTUSD": "polkadot",
    "AVAXUSD": "avalanche-2", "DOGEUSD": "dogecoin", "MATICUSD": "matic-network",
    "LINKUSD": "chainlink", "UNIUSD": "uniswap", "AAVEUSD": "aave",
    "LTCUSD": "litecoin", "ATOMUSD": "cosmos", "NEARUSD": "near",
    "SHIBAUSD": "shiba-inu", "ARBUSD": "arbitrum", "OPUSD": "optimism",
    "SUIUSD": "sui", "APTUSD": "aptos",
}

# Map to Binance pairs
BINANCE_MAP = {
    "BTCUSD": "BTCUSDT", "ETHUSD": "ETHUSDT", "XRPUSD": "XRPUSDT",
    "SOLUSD": "SOLUSDT", "ADAUSD": "ADAUSDT", "DOTUSD": "DOTUSDT",
    "AVAXUSD": "AVAXUSDT", "DOGEUSD": "DOGEUSDT", "LINKUSD": "LINKUSDT",
    "LTCUSD": "LTCUSDT", "NEARUSD": "NEARUSDT",
}


def fetch_coingecko_prices(symbols=None):
    """Fetch crypto prices from CoinGecko (free, no key)."""
    if symbols is None:
        symbols = list(SYMBOL_MAP.keys())

    ids = [SYMBOL_MAP[s] for s in symbols if s in SYMBOL_MAP]
    if not ids:
        return {}

    try:
        resp = requests.get(f"{COINGECKO_BASE}/simple/price", params={
            "ids": ",".join(ids),
            "vs_currencies": "usd",
            "include_24hr_change": "true",
            "include_24hr_vol": "true",
            "include_market_cap": "true",
        }, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        results = {}
        id_to_symbol = {v: k for k, v in SYMBOL_MAP.items()}
        for cg_id, info in data.items():
            sym = id_to_symbol.get(cg_id)
            if sym:
                results[sym] = {
                    "price": Decimal(str(info.get("usd", 0))),
                    "change_24h": round(info.get("usd_24h_change", 0), 4),
                    "volume_24h": info.get("usd_24h_vol", 0),
                    "market_cap": info.get("usd_market_cap", 0),
                }
        return results
    except Exception as e:
        logger.error(f"CoinGecko error: {e}")
        return {}


def fetch_binance_ticker(symbol):
    """Fetch real-time ticker from Binance public API (no key)."""
    binance_sym = BINANCE_MAP.get(symbol)
    if not binance_sym:
        return None
    try:
        resp = requests.get(f"{BINANCE_BASE}/ticker/24hr", params={"symbol": binance_sym}, timeout=10)
        resp.raise_for_status()
        d = resp.json()
        return {
            "price": Decimal(d.get("lastPrice", "0")),
            "change_pct": Decimal(d.get("priceChangePercent", "0")),
            "high": Decimal(d.get("highPrice", "0")),
            "low": Decimal(d.get("lowPrice", "0")),
            "volume": Decimal(d.get("volume", "0")),
            "quote_volume": Decimal(d.get("quoteVolume", "0")),
        }
    except Exception as e:
        logger.error(f"Binance ticker error for {symbol}: {e}")
        return None


def fetch_binance_klines(symbol, interval="1d", limit=100):
    """Fetch OHLCV candles from Binance."""
    binance_sym = BINANCE_MAP.get(symbol)
    if not binance_sym:
        return []
    try:
        resp = requests.get(f"{BINANCE_BASE}/klines", params={
            "symbol": binance_sym, "interval": interval, "limit": limit,
        }, timeout=15)
        resp.raise_for_status()
        return [{
            "timestamp": k[0], "open": Decimal(k[1]), "high": Decimal(k[2]),
            "low": Decimal(k[3]), "close": Decimal(k[4]), "volume": Decimal(k[5]),
        } for k in resp.json()]
    except Exception as e:
        logger.error(f"Binance klines error: {e}")
        return []


def save_crypto_quotes_to_db(symbols=None):
    """Fetch and save crypto quotes, THROUGH the one writer.

    This wrote LiveQuote directly, which skipped both guards that
    make the quote table trustworthy: the source-precedence check
    and the zero/negative price refusal. CoinGecko sits at priority
    40 and the Binance stream at 100, so a five-minute poll could -
    and on any run where the stream was live, did - overwrite a
    real-time tick with a delayed one. `stream_oanda` carries a
    comment about being "the last streamer writing LiveQuote
    directly"; this was the last adapter still doing it.
    """
    from market_data.quotes import write_quote

    prices = fetch_coingecko_prices(symbols)
    saved = 0
    for sym, data in prices.items():
        if write_quote(sym, last=data.get("price"), source="coingecko",
                       change_pct=data.get("change_24h"),
                       volume=data.get("volume_24h", 0)):
            saved += 1
    return saved
