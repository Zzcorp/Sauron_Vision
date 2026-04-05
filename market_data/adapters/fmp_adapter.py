"""Financial Modeling Prep adapter — fundamentals & SEC data."""
import os
import logging
from core.rate_limiter import rate_limiter

logger = logging.getLogger(__name__)

API_KEY = os.getenv("FMP_API_KEY", "")
BASE_URL = "https://financialmodelingprep.com/api/v3"


def fetch_company_profile(symbol: str) -> dict:
    """Fetch company fundamentals."""
    rate_limiter.wait_if_needed("fmp", 5)
    raise NotImplementedError("FMP adapter not yet implemented")


def fetch_financial_statements(symbol: str, statement_type: str = "income-statement") -> list:
    """Fetch financial statements (income, balance sheet, cash flow)."""
    rate_limiter.wait_if_needed("fmp", 5)
    raise NotImplementedError("FMP adapter not yet implemented")
