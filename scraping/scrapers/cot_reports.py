"""CFTC Commitments of Traders report downloader.

Downloads the weekly COT report from the CFTC website, parses the
fixed-width / CSV format, and returns structured data per market.
Also attempts to match CFTC market names to known instrument symbols.
"""
import io
import csv
import logging
import zipfile
from datetime import date, datetime
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# CFTC publishes a current-year CSV in a zip archive (most reliable source)
CFTC_ZIP_URL = "https://www.cftc.gov/files/dea/history/fut_fin_xls_{year}.zip"
CFTC_CURRENT_TXT = "https://www.cftc.gov/dea/newcot/deafut.txt"
CFTC_DISAGG_ZIP = "https://www.cftc.gov/files/dea/history/fut_disagg_xls_{year}.zip"

HEADERS = {
    "User-Agent": "SauronVision/1.0 (financial intelligence platform)",
    "Accept": "text/html,application/xhtml+xml,application/zip,*/*",
}

# Mapping from CFTC "Market and Exchange Names" fragments → instrument symbols
MARKET_NAME_MAP: dict[str, str] = {
    "S&P 500": "SPX",
    "E-MINI S&P": "ES",
    "NASDAQ": "NQ",
    "DOW JONES": "YM",
    "RUSSELL 2000": "RTY",
    "GOLD": "GC",
    "SILVER": "SI",
    "CRUDE OIL": "CL",
    "BRENT CRUDE": "BNO",
    "NATURAL GAS": "NG",
    "EURO FX": "EURUSD",
    "JAPANESE YEN": "USDJPY",
    "BRITISH POUND": "GBPUSD",
    "SWISS FRANC": "USDCHF",
    "CANADIAN DOLLAR": "USDCAD",
    "AUSTRALIAN DOLLAR": "AUDUSD",
    "U.S. T-BONDS": "ZB",
    "10-YEAR T-NOTES": "ZN",
    "COPPER": "HG",
    "CORN": "ZC",
    "WHEAT": "ZW",
    "SOYBEANS": "ZS",
    "BITCOIN": "BTC",
}


def _map_market_to_symbol(market_name: str) -> Optional[str]:
    """Return a symbol if market_name matches a known mapping."""
    upper = market_name.upper()
    for fragment, sym in MARKET_NAME_MAP.items():
        if fragment in upper:
            return sym
    return None


def _parse_cot_csv(content: str) -> list[dict]:
    """Parse the CFTC legacy futures-only CSV format.

    The CFTC CSV has many columns; we extract only the columns relevant to
    commercial / non-commercial positioning and open interest.
    """
    results: list[dict] = []

    try:
        reader = csv.DictReader(io.StringIO(content))

        for row in reader:
            try:
                # Normalise column names (strip whitespace)
                row = {k.strip(): v.strip() for k, v in row.items()}

                market_name = (
                    row.get("Market and Exchange Names", "")
                    or row.get("Market_and_Exchange_Names", "")
                    or row.get("Market", "")
                ).strip()

                report_date_str = (
                    row.get("As of Date in Form YYYY-MM-DD", "")
                    or row.get("Report_Date_as_YYYY-MM-DD", "")
                    or row.get("As of Date", "")
                ).strip()

                if not market_name or not report_date_str:
                    continue

                report_date = None
                for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y%m%d"):
                    try:
                        report_date = datetime.strptime(report_date_str, fmt).date()
                        break
                    except ValueError:
                        continue

                if report_date is None:
                    continue

                def _int(key: str) -> int:
                    raw = row.get(key, "0").replace(",", "").strip()
                    try:
                        return int(float(raw)) if raw else 0
                    except (ValueError, TypeError):
                        return 0

                # Column names differ between "financial" and "legacy" formats
                comm_long = _int("Comm_Positions_Long_All") or _int("Commercial Long")
                comm_short = _int("Comm_Positions_Short_All") or _int("Commercial Short")
                nc_long = _int("NonComm_Positions_Long_All") or _int("NonCommercial Long")
                nc_short = _int("NonComm_Positions_Short_All") or _int("NonCommercial Short")
                open_int = _int("Open_Interest_All") or _int("Open Interest")

                net_spec = nc_long - nc_short
                instrument_symbol = _map_market_to_symbol(market_name)

                results.append({
                    "market_name": market_name,
                    "report_date": report_date.isoformat(),
                    "commercial_long": comm_long,
                    "commercial_short": comm_short,
                    "non_commercial_long": nc_long,
                    "non_commercial_short": nc_short,
                    "open_interest": open_int,
                    "net_speculative": net_spec,
                    "instrument_symbol": instrument_symbol,
                })

            except Exception as row_exc:
                logger.debug("COT: skipping row due to error: %s", row_exc)
                continue

    except Exception as exc:
        logger.error("COT CSV parsing error: %s", exc)

    return results


def _fetch_zip(url: str) -> Optional[str]:
    """Download a zip file from CFTC and return the first text file content."""
    try:
        from core.rate_limiter import rate_limiter
        rate_limiter.wait_if_needed("cftc", calls_per_minute=5)
    except Exception:
        pass

    try:
        resp = requests.get(url, headers=HEADERS, timeout=60)
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.error("CFTC zip download failed (%s): %s", url, exc)
        return None

    try:
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            names = zf.namelist()
            # Prefer CSV/TXT over XLS
            preferred = [n for n in names if n.lower().endswith((".csv", ".txt"))]
            target = preferred[0] if preferred else (names[0] if names else None)
            if target is None:
                logger.error("CFTC zip is empty: %s", url)
                return None
            logger.debug("CFTC: reading '%s' from zip", target)
            return zf.read(target).decode("latin-1", errors="replace")
    except zipfile.BadZipFile as exc:
        logger.error("CFTC: bad zip file from %s: %s", url, exc)
        return None


def _fetch_txt_direct() -> Optional[str]:
    """Download the plain-text COT report (fixed-width, legacy format)."""
    try:
        from core.rate_limiter import rate_limiter
        rate_limiter.wait_if_needed("cftc", calls_per_minute=5)
    except Exception:
        pass

    try:
        resp = requests.get(CFTC_CURRENT_TXT, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        return resp.text
    except requests.RequestException as exc:
        logger.error("CFTC TXT download failed: %s", exc)
        return None


def _parse_fixed_width_txt(text: str) -> list[dict]:
    """Parse the legacy fixed-width deafut.txt format.

    This format has one record per line with comma-separated but
    fixed-position fields.  We attempt CSV parsing as a first pass.
    """
    # The .txt file is actually comma-delimited despite the .txt extension
    return _parse_cot_csv(text)


def fetch_latest_cot_report() -> list[dict]:
    """Download and parse the most recent CFTC COT report.

    Tries multiple sources in order:
    1. Current-year ZIP (CSV inside)
    2. Raw TXT file (comma-separated fixed-width)

    Returns:
        List of dicts with keys: market_name, report_date,
        commercial_long, commercial_short, non_commercial_long,
        non_commercial_short, open_interest, net_speculative,
        instrument_symbol.  Returns empty list on total failure.
    """
    current_year = datetime.utcnow().year
    results: list[dict] = []

    # Strategy 1: current-year financial futures zip
    zip_url = CFTC_ZIP_URL.format(year=current_year)
    logger.debug("COT: trying zip source %s", zip_url)
    content = _fetch_zip(zip_url)

    if content:
        results = _parse_cot_csv(content)

    # Strategy 2: disaggregated futures zip
    if not results:
        zip_url2 = CFTC_DISAGG_ZIP.format(year=current_year)
        logger.debug("COT: trying disaggregated zip %s", zip_url2)
        content2 = _fetch_zip(zip_url2)
        if content2:
            results = _parse_cot_csv(content2)

    # Strategy 3: plain-text endpoint
    if not results:
        logger.debug("COT: trying plain-text endpoint")
        txt = _fetch_txt_direct()
        if txt:
            results = _parse_fixed_width_txt(txt)

    if not results:
        logger.error("fetch_latest_cot_report: all sources exhausted — returning empty list")
        return []

    logger.info("fetch_latest_cot_report: parsed %d markets", len(results))
    _persist_cot_reports(results)
    return results


def _persist_cot_reports(reports: list[dict]) -> None:
    """Attempt to upsert COTReport rows for instruments we track."""
    if not reports:
        return
    try:
        from scraping.models import COTReport
        from instruments.models import Instrument

        created = 0
        for r in reports:
            sym = r.get("instrument_symbol")
            if not sym:
                continue
            try:
                instrument = Instrument.objects.get(symbol=sym)
            except Instrument.DoesNotExist:
                continue

            report_date_str = r.get("report_date")
            if not report_date_str:
                continue
            try:
                report_date = date.fromisoformat(report_date_str)
            except ValueError:
                continue

            _, was_created = COTReport.objects.update_or_create(
                instrument=instrument,
                report_date=report_date,
                defaults={
                    "commercial_long": r["commercial_long"],
                    "commercial_short": r["commercial_short"],
                    "non_commercial_long": r["non_commercial_long"],
                    "non_commercial_short": r["non_commercial_short"],
                    "open_interest": r["open_interest"],
                    "net_speculative": r["net_speculative"],
                },
            )
            if was_created:
                created += 1

        logger.debug("COT persistence: %d new rows saved", created)

    except Exception as exc:
        logger.debug("COTReport persistence skipped: %s", exc)
