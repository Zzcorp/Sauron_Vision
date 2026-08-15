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

# The LEGACY futures-only sources: the current-week text file plus the
# yearly deacot archive. The archive was previously fut_fin_xls_{year}.zip —
# an Excel workbook that, decoded as latin-1 "text", produced mojibake with
# no parseable header, which is why this scraper stored zero rows for its
# whole life. deacot{year}.zip contains annual.txt: a real CSV with a header
# row AND the commercial/noncommercial columns the COTReport model wants
# (the fut_fin "financial" format carries Dealer/Asset-Mgr columns instead).
CFTC_CURRENT_TXT = "https://www.cftc.gov/dea/newcot/deafut.txt"
CFTC_ZIP_URL = "https://www.cftc.gov/files/dea/history/deacot{year}.zip"

HEADERS = {
    "User-Agent": "SauronVision/1.0 (financial intelligence platform)",
    "Accept": "text/html,application/xhtml+xml,application/zip,*/*",
}

# CFTC market name (the part before " - EXCHANGE") → catalogue symbol.
# EXACT names, matched whole, verified against the live deafut.txt on
# 2026-08-16 — fragment matching bled across contracts ("GOLD" also matched
# MICRO GOLD, "WHEAT" let WHEAT-HRW overwrite WHEAT-SRW for the same date),
# and the old values (SPX, GC, ZC...) were spellings no Instrument row has
# ever had, so even a parsed row could never persist.
MARKET_NAME_MAP: dict[str, str] = {
    # Equity indices
    "E-MINI S&P 500": "SPX500",
    "NASDAQ-100 CONSOLIDATED": "NSDQ100",
    "RUSSELL E-MINI": "RUSSELL2000",
    "NIKKEI STOCK AVERAGE YEN DENOM": "NIKKEI225",
    "USD INDEX": "DXY",
    # Metals
    "GOLD": "XAUUSD",
    "SILVER": "XAGUSD",
    "PLATINUM": "XPTUSD",
    "PALLADIUM": "XPDUSD",
    "COPPER- #1": "HGUSD",
    # Energy
    "WTI-PHYSICAL": "WTIUSD",
    "BRENT LAST DAY": "BRNUSD",
    "NAT GAS NYME": "NGUSD",
    "NY HARBOR ULSD": "HEATOILUSD",
    "GASOLINE RBOB": "GASOLINEUSD",
    # Grains, softs, meats
    "WHEAT-SRW": "WHEATUSD",
    "CORN": "CORNUSD",
    "SOYBEANS": "SOYUSD",
    "OATS": "OATS",
    "ROUGH RICE": "RICE",
    "COFFEE C": "COFFEEUSD",
    "COCOA": "COCOAUSD",
    "COTTON NO. 2": "COTTONUSD",
    "SUGAR NO. 11": "SUGARUSD",
    "FRZN CONCENTRATED ORANGE JUICE": "ORANGEJUICE",
    "LUMBER": "LUMBER",
    "LEAN HOGS": "LEANHOGS",
    "LIVE CATTLE": "LIVECATTLE",
    # FX futures (CFTC quotes the foreign currency as the contract unit)
    "EURO FX": "EURUSD",
    "JAPANESE YEN": "USDJPY",
    "BRITISH POUND": "GBPUSD",
    "SWISS FRANC": "USDCHF",
    "CANADIAN DOLLAR": "USDCAD",
    "AUSTRALIAN DOLLAR": "AUDUSD",
    "NZ DOLLAR": "NZDUSD",
    "MEXICAN PESO": "USDMXN",
    "EURO FX/BRITISH POUND XRATE": "EURGBP",
    "EURO FX/JAPANESE YEN XRATE": "EURJPY",
    # Crypto
    "BITCOIN": "BTCUSD",
}


def _map_market_to_symbol(market_name: str) -> Optional[str]:
    """Catalogue symbol for a CFTC market name, or None.

    Matches the exact name part before the exchange suffix, so MICRO GOLD
    and WHEAT-HRW stay unmapped instead of colliding with the flagship
    contract's row for the same report date.
    """
    name_part = (market_name or "").split(" - ")[0].strip().upper()
    return MARKET_NAME_MAP.get(name_part)


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

                # The first names are what deacot's annual.txt ACTUALLY
                # carries (verified against the live archive 2026-08-16);
                # the rest are aliases from other CFTC exports.
                comm_long = (_int("Commercial Positions-Long (All)")
                             or _int("Comm_Positions_Long_All")
                             or _int("Commercial Long"))
                comm_short = (_int("Commercial Positions-Short (All)")
                              or _int("Comm_Positions_Short_All")
                              or _int("Commercial Short"))
                nc_long = (_int("Noncommercial Positions-Long (All)")
                           or _int("NonComm_Positions_Long_All")
                           or _int("NonCommercial Long"))
                nc_short = (_int("Noncommercial Positions-Short (All)")
                            or _int("NonComm_Positions_Short_All")
                            or _int("NonCommercial Short"))
                open_int = (_int("Open Interest (All)")
                            or _int("Open_Interest_All")
                            or _int("Open Interest"))

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


# deafut.txt column positions (headerless legacy futures-only format,
# verified against the live file 2026-08-16):
#   0 market name · 2 date YYYY-MM-DD · 7 open interest ·
#   8 noncommercial long · 9 noncommercial short ·
#   11 commercial long · 12 commercial short
_TXT_MIN_FIELDS = 13


def _parse_fixed_width_txt(text: str) -> list[dict]:
    """Parse the legacy deafut.txt current-week file.

    Comma-separated but HEADERLESS — handing it to DictReader consumed the
    first market's record as the field names, so every subsequent header
    lookup missed and this parser returned [] for its whole life. The
    positions are fixed; parse by index.
    """
    results: list[dict] = []
    for row in csv.reader(io.StringIO(text)):
        try:
            if len(row) < _TXT_MIN_FIELDS:
                continue
            market_name = row[0].strip()
            report_date = datetime.strptime(row[2].strip(), "%Y-%m-%d").date()

            def _int(raw) -> int:
                raw = str(raw).replace(",", "").strip()
                try:
                    return int(float(raw)) if raw else 0
                except (ValueError, TypeError):
                    return 0

            nc_long, nc_short = _int(row[8]), _int(row[9])
            comm_long, comm_short = _int(row[11]), _int(row[12])
            results.append({
                "market_name": market_name,
                "report_date": report_date.isoformat(),
                "commercial_long": comm_long,
                "commercial_short": comm_short,
                "non_commercial_long": nc_long,
                "non_commercial_short": nc_short,
                "open_interest": _int(row[7]),
                "net_speculative": nc_long - nc_short,
                "instrument_symbol": _map_market_to_symbol(market_name),
            })
        except Exception as row_exc:
            logger.debug("COT txt: skipping row: %s", row_exc)
            continue
    return results


def fetch_latest_cot_report() -> list[dict]:
    """Download and parse the most recent CFTC COT report.

    Tries multiple sources in order:
    1. Raw current-week TXT file (headerless positional CSV)
    2. Current-year legacy ZIP (headered CSV, all weeks)

    Returns:
        List of dicts with keys: market_name, report_date,
        commercial_long, commercial_short, non_commercial_long,
        non_commercial_short, open_interest, net_speculative,
        instrument_symbol.  Returns empty list on total failure.
    """
    current_year = datetime.utcnow().year
    results: list[dict] = []

    # Strategy 1: the current-week text file — freshest and smallest.
    logger.debug("COT: trying plain-text endpoint")
    txt = _fetch_txt_direct()
    if txt:
        results = _parse_fixed_width_txt(txt)

    # Strategy 2: the yearly legacy archive (headers + every week so far).
    if not results:
        zip_url = CFTC_ZIP_URL.format(year=current_year)
        logger.debug("COT: trying zip source %s", zip_url)
        content = _fetch_zip(zip_url)
        if content:
            results = _parse_cot_csv(content)

    if not results:
        logger.error("fetch_latest_cot_report: all sources exhausted — returning empty list")
        return []

    logger.info("fetch_latest_cot_report: parsed %d markets", len(results))
    upserted = _persist_cot_reports(results)
    # Stashed for the task's gate report: rows UPSERTED, not just created —
    # a same-week re-run re-asserts existing rows and must judge green.
    fetch_latest_cot_report.last_upserted = upserted
    return results


def _persist_cot_reports(reports: list[dict]) -> int:
    """Upsert COTReport rows for instruments we track. Returns rows UPSERTED
    (created or refreshed) — not just created: a re-run over the same report
    week re-asserts existing rows, and counting those as zero made the gate
    flag scraper_cot amber every week the CFTC release slipped past the
    Saturday beat."""
    if not reports:
        return 0
    try:
        from scraping.models import COTReport
        from instruments.models import Instrument

        upserted = 0
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
            upserted += 1
            if was_created:
                created += 1

        logger.debug("COT persistence: %d upserted (%d new)", upserted, created)
        return upserted

    except Exception as exc:
        logger.debug("COTReport persistence skipped: %s", exc)
        return 0
