"""The board's markets: the six rows, their proxies, and the ticket map
(spec §2.3). Symbols are the catalogue's (instruments/services.py)."""
from __future__ import annotations

#: row key -> what it reads and what it is graded on. `cot` is the legacy
#: COT market (scraping/scrapers/cot_reports.py MARKET_NAME_MAP); None for
#: Treasuries until PR3 adds the Treasury futures.
ROWS = {
    "us_equities": {"title": "US equities", "graded_on": "SPX500",
                    "etf": "SPY", "cot": "SPX500", "crypto": False},
    "treasuries": {"title": "US Treasuries", "graded_on": "TLT",
                   "etf": "TLT", "cot": None, "crypto": False},
    "us_dollar": {"title": "US dollar", "graded_on": "DXY",
                  "etf": "UUP", "cot": "DXY", "crypto": False},
    "gold": {"title": "Gold", "graded_on": "XAUUSD",
             "etf": "GLD", "cot": "XAUUSD", "crypto": False},
    "crude_oil": {"title": "Crude oil", "graded_on": "WTIUSD",
                  "etf": "USO", "cot": "WTIUSD", "crypto": False},
    "crypto": {"title": "Crypto", "graded_on": "BTCUSD",
               "etf": "IBIT", "cot": "BTCUSD", "crypto": True},
}
ROW_ORDER = tuple(ROWS)
GLOBAL = "global"
INSTRUMENTS = "instruments"

#: The bond leg of the 60/40 drift: AGG first (what balanced and
#: target-date funds hold), TLT the stated fallback (spec §0.3, item 3).
BOND_LEG = ("AGG", "TLT")

#: The four month-end fix pairs and the foreign index each one's hedge
#: follows (Melvin & Prins 2015).
FX_FIX_PAIRS = {"EURUSD": "STOXX50", "GBPUSD": "FTSE100",
                "USDJPY": "NIKKEI225", "AUDUSD": "ASX200"}
FIX_INDEX_NAMES = {"STOXX50": "The Euro Stoxx 50", "FTSE100": "The FTSE 100",
                   "NIKKEI225": "The Nikkei 225", "ASX200": "The ASX 200"}
FIX_CCY = {"EURUSD": "EUR", "GBPUSD": "GBP", "USDJPY": "JPY", "AUDUSD": "AUD"}

#: Every FX pair the legacy COT reader maps (cot_reports.MARKET_NAME_MAP).
COT_FX_PAIRS = ("EURUSD", "USDJPY", "GBPUSD", "USDCHF", "USDCAD", "AUDUSD",
                "NZDUSD", "USDMXN", "EURGBP", "EURJPY")

#: Crypto closes at 00:00 UTC: horizons count calendar days, the bound is 2.
#: Every other market has closed by the evening read (23:20 UTC, after the
#: 22:30 bars), which says "no close yet" when the as-of close is missing
#: rather than reading yesterday's as today's (bigmoney/cells.py Ctx._tape).
CRYPTO_SYMBOLS = frozenset({"BTCUSD", "ETHUSD"})

#: The ticket map (spec §2.3, last column). Stocks on NYSE or NASDAQ and
#: every pair with a USD side are resolved in `ticket_target`.
_TICKET = {}
for _s in ("SPX500", "NSDQ100", "DJ30", "RUSSELL2000", "SPY", "QQQ", "IWM",
           "VTI", "DIA", "ARKK", "VNQ", "XLF", "XLE", "XLK", "XLV", "XLI",
           "XLY", "XLP", "XLU", "XLB", "XLRE", "XLC"):
    _TICKET[_s] = "us_equities"
for _s in ("TLT", "AGG"):
    _TICKET[_s] = "treasuries"
for _s in ("DXY", "UUP"):
    _TICKET[_s] = "us_dollar"
for _s in ("XAUUSD", "GLD"):
    _TICKET[_s] = "gold"
for _s in ("WTIUSD", "BRNUSD", "USO"):
    _TICKET[_s] = "crude_oil"
for _s in ("BTCUSD", "ETHUSD", "IBIT"):
    _TICKET[_s] = "crypto"
TICKET_ROWS = dict(_TICKET)


def usd_side(symbol: str):
    """+1 when buying the pair buys the dollar (USDXXX), -1 when it sells it
    (XXXUSD), None for a pair with no USD side or not a pair at all."""
    s = (symbol or "").upper()
    if len(s) != 6 or s in ("DXY",):
        return None
    if s.startswith("USD") and s[3:] != "USD":
        return 1
    if s.endswith("USD") and s[:3] != "USD":
        return -1
    return None


def ticket_target(symbol: str, instrument=None) -> dict | None:
    """Where the ticket note for `symbol` reads: {"kind": "row"|"fix_pair"|
    "pair"|"instrument", "row": row key or None, "usd": +1/-1 or None}.
    None: outside the board's markets."""
    s = (symbol or "").upper()
    if s in TICKET_ROWS:
        return {"kind": "row", "row": TICKET_ROWS[s], "usd": None}
    asset_class = (getattr(instrument, "asset_class", "") or "").lower()
    exchange = (getattr(instrument, "exchange", "") or "").upper()
    if s in FX_FIX_PAIRS:
        return {"kind": "fix_pair", "row": "us_dollar", "usd": usd_side(s)}
    if asset_class == "forex" or (instrument is None and usd_side(s)):
        side = usd_side(s)
        if side is not None:
            return {"kind": "pair", "row": "us_dollar", "usd": side}
        return None
    if asset_class == "commodity":
        return {"kind": "instrument", "row": None, "usd": None}
    if asset_class == "stock" and exchange in ("NYSE", "NASDAQ"):
        return {"kind": "row", "row": "us_equities", "usd": None}
    return None
