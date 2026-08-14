"""FinViz scraper — stock screener, heat maps.

Scrapes FinViz's stock screener and individual stock overview pages using
requests + BeautifulSoup.  Handles rate limiting and parsing errors gracefully.
"""
import logging
import re
from typing import Optional

import requests

logger = logging.getLogger(__name__)

FINVIZ_BASE = "https://finviz.com"
FINVIZ_SCREENER = f"{FINVIZ_BASE}/screener.ashx"
FINVIZ_QUOTE = f"{FINVIZ_BASE}/quote.ashx"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://finviz.com/",
}

# Default screener filters: top-gainers with unusual volume
DEFAULT_FILTERS = {
    "v": "111",         # table view
    "f": "ta_change_u5,sh_avgvol_o500",  # >5% change, avg vol >500k
    "o": "-change",     # sort by change descending
}


def _get_bs4():
    """Import BeautifulSoup or raise ImportError with a friendly message."""
    try:
        from bs4 import BeautifulSoup
        return BeautifulSoup
    except ImportError as exc:
        raise ImportError(
            "BeautifulSoup4 is required for the FinViz scraper. "
            "Install with: pip install beautifulsoup4 lxml"
        ) from exc


def _parse_market_cap(raw: str) -> Optional[float]:
    """Convert '1.23B' / '456.7M' etc. to a float (dollars)."""
    if not raw or raw == "-":
        return None
    raw = raw.strip()
    multipliers = {"B": 1e9, "M": 1e6, "K": 1e3, "T": 1e12}
    suffix = raw[-1].upper()
    if suffix in multipliers:
        try:
            return float(raw[:-1]) * multipliers[suffix]
        except ValueError:
            return None
    try:
        return float(raw.replace(",", ""))
    except ValueError:
        return None


def _parse_pct(raw: str) -> Optional[float]:
    """Convert '12.34%' to 12.34."""
    if not raw or raw == "-":
        return None
    try:
        return float(raw.replace("%", "").strip())
    except ValueError:
        return None


def fetch_screener_results(filters: Optional[dict] = None) -> list[dict]:
    """Fetch stock screener results from FinViz.

    Args:
        filters: Dict of FinViz URL query parameters.  Defaults to top-gainers
                 with unusual volume.

    Returns:
        List of dicts with keys: ticker, company, sector, market_cap, price,
        change_pct, volume.  Returns empty list on any error.
    """
    try:
        from core.rate_limiter import rate_limiter
        rate_limiter.wait_if_needed("finviz", calls_per_minute=6)
    except Exception:
        pass

    BeautifulSoup = _get_bs4() if True else None
    try:
        BeautifulSoup = _get_bs4()
    except ImportError as exc:
        logger.warning("finviz.fetch_screener_results disabled: %s", exc)
        return []

    params = dict(DEFAULT_FILTERS)
    if filters:
        params.update(filters)

    try:
        resp = requests.get(FINVIZ_SCREENER, params=params, headers=HEADERS, timeout=20)
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.error("FinViz screener request failed: %s", exc)
        return []

    soup = BeautifulSoup(resp.text, "lxml")
    results: list[dict] = []

    try:
        # screener-content is a <div> wrapping the results table, not the
        # table itself. Asking find() for a <table> with that id therefore
        # matched nothing, and the fallback class regex matched nothing
        # either because FinViz no longer emits `table-light`. The scraper
        # returned zero rows on a perfectly good HTTP 200 every single run.
        container = soup.find(id="screener-content") or soup
        table = container.find("table") if container else None
        if table is None:
            table = soup.find("table", class_=re.compile(r"table-light|screener"))

        if table is None:
            logger.warning("FinViz: could not locate screener table in HTML response")
            return []

        rows = table.find_all("tr")
        # Row 0 is usually a header; detect it
        headers_row = rows[0] if rows else None
        if headers_row is None:
            return []

        col_headers = [th.get_text(strip=True) for th in headers_row.find_all(["th", "td"])]

        # Build column index map
        col_map: dict[str, int] = {}
        for i, h in enumerate(col_headers):
            col_map[h] = i

        def _cell(cells, key, default=""):
            idx = col_map.get(key)
            if idx is None or idx >= len(cells):
                return default
            return cells[idx].get_text(strip=True)

        for row in rows[1:]:
            cells = row.find_all("td")
            if len(cells) < 3:
                continue

            ticker = _cell(cells, "Ticker") or _cell(cells, "No.")
            # Try positional fallback for common FinViz column layout:
            # 1=No, 2=Ticker, 3=Company, 4=Sector, 5=Industry, 6=Country,
            # 7=MarketCap, 8=P/E, 9=Price, 10=Change, 11=Volume
            if not ticker or ticker.isdigit():
                # Try column 1 (0-indexed)
                ticker_td = row.find("a", href=re.compile(r'quote\.ashx\?t='))
                ticker = ticker_td.get_text(strip=True) if ticker_td else ""

            if not ticker:
                continue

            company = _cell(cells, "Company")
            sector = _cell(cells, "Sector")
            raw_mcap = _cell(cells, "Market Cap")
            price_raw = _cell(cells, "Price")
            change_raw = _cell(cells, "Change")
            volume_raw = _cell(cells, "Volume")

            # Positional fallback (indices based on classic FinViz layout)
            if not company and len(cells) > 2:
                company = cells[2].get_text(strip=True)
            if not sector and len(cells) > 3:
                sector = cells[3].get_text(strip=True)
            if not price_raw and len(cells) > 8:
                price_raw = cells[8].get_text(strip=True)
            if not change_raw and len(cells) > 9:
                change_raw = cells[9].get_text(strip=True)
            if not volume_raw and len(cells) > 10:
                volume_raw = cells[10].get_text(strip=True)

            try:
                price = float(price_raw.replace(",", "")) if price_raw and price_raw != "-" else None
            except ValueError:
                price = None

            try:
                volume = int(volume_raw.replace(",", "")) if volume_raw and volume_raw != "-" else None
            except ValueError:
                volume = None

            results.append({
                "ticker": ticker,
                "company": company,
                "sector": sector,
                "market_cap": _parse_market_cap(raw_mcap),
                "price": price,
                "change_pct": _parse_pct(change_raw),
                "volume": volume,
            })

    except Exception as exc:
        logger.error("FinViz screener HTML parsing error: %s", exc)
        return []

    logger.info("FinViz screener: parsed %d rows", len(results))
    return results


def fetch_stock_overview(symbol: str) -> dict:
    """Fetch key stats for a single ticker from FinViz's quote page.

    Args:
        symbol: Uppercase ticker symbol, e.g. "AAPL".

    Returns:
        Dict with all key/value pairs from the FinViz fundamentals table.
        Returns empty dict on any error.
    """
    try:
        from core.rate_limiter import rate_limiter
        rate_limiter.wait_if_needed("finviz", calls_per_minute=6)
    except Exception:
        pass

    try:
        BeautifulSoup = _get_bs4()
    except ImportError as exc:
        logger.warning("finviz.fetch_stock_overview disabled: %s", exc)
        return {}

    try:
        resp = requests.get(
            FINVIZ_QUOTE,
            params={"t": symbol.upper()},
            headers=HEADERS,
            timeout=20,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.error("FinViz quote request for %s failed: %s", symbol, exc)
        return {}

    soup = BeautifulSoup(resp.text, "lxml")
    data: dict = {"symbol": symbol.upper()}

    try:
        # Company name
        name_el = soup.find("h2", class_=re.compile(r"quote-header"))
        if name_el:
            data["company"] = name_el.get_text(strip=True)

        # Fundamentals snapshot table
        table = soup.find("table", class_=re.compile(r"snapshot-table|fullview-title"))
        if table:
            cells = table.find_all("td")
            # FinViz alternates key/value in pairs
            for i in range(0, len(cells) - 1, 2):
                key = cells[i].get_text(strip=True)
                val = cells[i + 1].get_text(strip=True)
                if key:
                    data[key] = val

        # Price
        price_el = soup.find("strong", class_=re.compile(r"quote-price"))
        if not price_el:
            price_el = soup.find("span", class_=re.compile(r"price"))
        if price_el:
            data["price"] = price_el.get_text(strip=True)

    except Exception as exc:
        logger.error("FinViz quote parsing for %s failed: %s", symbol, exc)

    return data
