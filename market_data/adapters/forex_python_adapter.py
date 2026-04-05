"""forex-python adapter — free ECB rates."""
import logging

logger = logging.getLogger(__name__)


def fetch_rate(from_currency: str, to_currency: str) -> float:
    """Fetch current exchange rate from ECB."""
    # TODO: Implement
    # from forex_python.converter import CurrencyRates
    # c = CurrencyRates()
    # return c.get_rate(from_currency, to_currency)
    raise NotImplementedError("forex-python adapter not yet implemented")
