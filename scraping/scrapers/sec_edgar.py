"""SEC EDGAR scraper — 13F filings, insider trades.

Uses the SEC EDGAR full-text search API and the submissions JSON endpoint.
The SEC requires a descriptive User-Agent with contact info; configure via the
SEC_EDGAR_USER_AGENT environment variable.
"""
import os
import logging
import time
from datetime import date, datetime
from typing import Optional

import requests

logger = logging.getLogger(__name__)

SEC_USER_AGENT = os.getenv(
    "SEC_EDGAR_USER_AGENT",
    "SauronVision/1.0 contact@example.com",
)

EDGAR_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
EDGAR_BROWSE_URL = "https://www.sec.gov/cgi-bin/browse-edgar"

HEADERS = {
    "User-Agent": SEC_USER_AGENT,
    "Accept": "application/json",
}

REQUEST_DELAY = 0.15  # SEC fair-use: no more than 10 req/sec


def _get(url: str, params: dict | None = None, timeout: int = 20) -> Optional[requests.Response]:
    """GET with SEC-required headers and basic retry."""
    from core.rate_limiter import rate_limiter
    rate_limiter.wait_if_needed("sec_edgar", calls_per_minute=10)

    for attempt in range(3):
        try:
            resp = requests.get(url, params=params, headers=HEADERS, timeout=timeout)
            if resp.status_code == 429:
                wait = 2 ** attempt * 5
                logger.warning("SEC EDGAR 429 — waiting %ds", wait)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp
        except requests.exceptions.Timeout:
            logger.warning("SEC EDGAR timeout on attempt %d for %s", attempt + 1, url)
        except requests.RequestException as exc:
            logger.error("SEC EDGAR request error: %s", exc)
            break
    return None


def fetch_recent_13f_filings(limit: int = 20) -> list[dict]:
    """Fetch the most recent 13-F filings from SEC EDGAR.

    Uses the EDGAR browse endpoint (Atom feed) to retrieve the most recent
    13F-HR filings across all filers.

    Args:
        limit: Maximum number of filings to return.

    Returns:
        List of dicts with keys: filer_name, filing_type, filing_date,
        accession_number, source_url.  Returns empty list on any error.
    """
    # browse-edgar returns an Atom XML feed of the most recent filings
    resp = _get(
        "https://www.sec.gov/cgi-bin/browse-edgar",
        params={
            "action": "getcurrent",
            "type": "13F-HR",
            "dateb": "",
            "owner": "include",
            "count": str(min(limit, 40)),
            "search_text": "",
            "output": "atom",
        },
    )

    results: list[dict] = []

    if resp is None:
        logger.warning("fetch_recent_13f_filings: no response from SEC EDGAR")
        return results

    # Try to parse Atom/XML feed from browse-edgar
    try:
        import xml.etree.ElementTree as ET
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        root = ET.fromstring(resp.text)
        entries = root.findall("atom:entry", ns)

        for entry in entries[:limit]:
            title_el = entry.find("atom:title", ns)
            updated_el = entry.find("atom:updated", ns)
            link_el = entry.find("atom:link", ns)
            category_el = entry.find("atom:category", ns)

            title = title_el.text if title_el is not None else ""
            filing_date_str = (updated_el.text or "")[:10] if updated_el is not None else ""
            source_url = link_el.get("href", "") if link_el is not None else ""

            # Title format: "13F-HR - FILER NAME (CIK)"
            parts = title.split(" - ", 1)
            filing_type = parts[0].strip() if parts else "13F-HR"
            filer_name = parts[1].strip() if len(parts) > 1 else title

            # Strip CIK from filer name if present
            filer_name = filer_name.split("(")[0].strip()

            filing_date = None
            if filing_date_str:
                try:
                    filing_date = date.fromisoformat(filing_date_str)
                except ValueError:
                    pass

            results.append({
                "filer_name": filer_name,
                "filing_type": filing_type,
                "filing_date": filing_date.isoformat() if filing_date else filing_date_str,
                "source_url": source_url,
                "accession_number": "",
                "instrument": None,
                "shares": None,
                "value": None,
            })

    except Exception as exc:
        logger.error("fetch_recent_13f_filings: XML parsing error: %s", exc)
        return []

    logger.info("fetch_recent_13f_filings: retrieved %d filings", len(results))
    _persist_institutional_filings(results)
    return results


def fetch_insider_trades(symbol: Optional[str] = None, limit: int = 20) -> list[dict]:
    """Fetch Form-4 insider trade filings from SEC EDGAR.

    Args:
        symbol: Optional ticker symbol to filter by.  If None, returns
                the most recent Form-4 filings across all companies.
        limit:  Maximum number of results.

    Returns:
        List of dicts with keys: filer_name, filing_type, filing_date,
        instrument, shares, value, change_type, source_url.
    """
    params: dict = {
        "action": "getcurrent",
        "type": "4",
        "dateb": "",
        "owner": "include",
        "count": str(min(limit, 40)),
        "search_text": "",
        "output": "atom",
    }

    if symbol:
        # Search by company ticker/name
        params["company"] = symbol
        params["CIK"] = symbol
        params["action"] = "getcompany"
        params["type"] = "4"
        params["output"] = "atom"

    resp = _get("https://www.sec.gov/cgi-bin/browse-edgar", params=params)
    results: list[dict] = []

    if resp is None:
        logger.warning("fetch_insider_trades: no response from SEC EDGAR")
        return results

    try:
        import xml.etree.ElementTree as ET
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        root = ET.fromstring(resp.text)
        entries = root.findall("atom:entry", ns)

        for entry in entries[:limit]:
            title_el = entry.find("atom:title", ns)
            updated_el = entry.find("atom:updated", ns)
            link_el = entry.find("atom:link", ns)
            summary_el = entry.find("atom:summary", ns)

            title = title_el.text if title_el is not None else ""
            filing_date_str = (updated_el.text or "")[:10] if updated_el is not None else ""
            source_url = link_el.get("href", "") if link_el is not None else ""
            summary = summary_el.text if summary_el is not None else ""

            # Title format: "4 - INSIDER NAME (CIK) (Form-4)"
            parts = title.split(" - ", 1)
            filer_name = parts[1].strip().split("(")[0].strip() if len(parts) > 1 else title

            filing_date = None
            if filing_date_str:
                try:
                    filing_date = date.fromisoformat(filing_date_str)
                except ValueError:
                    pass

            results.append({
                "filer_name": filer_name,
                "filing_type": "4",
                "filing_date": filing_date.isoformat() if filing_date else filing_date_str,
                "instrument": symbol,
                "shares": None,
                "value": None,
                "change_type": "",
                "source_url": source_url,
                "summary": summary[:500],
            })

    except Exception as exc:
        logger.error("fetch_insider_trades: XML parsing error: %s", exc)
        return []

    # This call was simply missing. The function built rows with a resolvable
    # "instrument" key — the only path in this module that can satisfy the
    # persist guard below — and then returned them straight to a caller that
    # took len() and dropped the list.
    stored = _persist_institutional_filings(results)
    logger.info("fetch_insider_trades: retrieved %d filings, stored %d (symbol=%s)",
                len(results), stored, symbol)
    return results


def _persist_institutional_filings(filings: list[dict]) -> int:
    """Save parsed filings to InstitutionalFiling. Returns rows written."""
    if not filings:
        return 0
    written = 0
    skipped_unknown = 0
    try:
        from scraping.models import InstitutionalFiling
        from instruments.models import Instrument
        from django.utils import timezone as dj_tz

        for f in filings:
            sym = f.get("instrument")
            instrument = None
            if sym:
                instrument = Instrument.objects.filter(symbol__iexact=sym).first()
                if instrument is None:
                    skipped_unknown += 1
                    continue

            filing_date = f.get("filing_date")
            if isinstance(filing_date, str):
                try:
                    filing_date = date.fromisoformat(filing_date)
                except ValueError:
                    filing_date = date.today()

            source_url = (f.get("source_url") or "")[:200]

            # A 13F from the current-filings feed names the filer but not the
            # holdings — those live in the INFORMATION TABLE attachment, which
            # this scraper does not follow. So instrument stays null rather
            # than the row being thrown away: knowing that a given manager
            # filed on a given date is genuinely useful, and discarding it was
            # why the 13F path could never write anything at all.
            #
            # Dedupe by accession URL when we have one. unique_together cannot
            # do this job here because SQL treats two NULL instruments as
            # distinct, so every run would re-insert the same 13F rows.
            existing = None
            if source_url:
                existing = InstitutionalFiling.objects.filter(
                    source_url=source_url).first()
            if existing is None:
                existing = InstitutionalFiling.objects.filter(
                    filing_type=f.get("filing_type", "")[:10],
                    filer_name=f.get("filer_name", "")[:300],
                    instrument=instrument,
                    filing_date=filing_date,
                ).first()

            if existing is None:
                InstitutionalFiling.objects.create(
                    filing_type=f.get("filing_type", "")[:10],
                    filer_name=f.get("filer_name", "")[:300],
                    instrument=instrument,
                    filing_date=filing_date,
                    shares=f.get("shares"),
                    value=f.get("value"),
                    change_type=f.get("change_type", "")[:20],
                    source_url=source_url,
                )
                written += 1

        if skipped_unknown:
            # Previously a bare `continue` with no counter, so a run that
            # resolved none of its filings looked identical to a quiet day.
            logger.info(
                "InstitutionalFiling: %d of %d filings named a symbol we do "
                "not carry and were dropped", skipped_unknown, len(filings))

    except Exception as exc:
        # WARNING, not DEBUG: a database error here used to abort the rest of
        # the batch without appearing in the logs at all.
        logger.warning("InstitutionalFiling persistence failed: %s", exc)

    return written
