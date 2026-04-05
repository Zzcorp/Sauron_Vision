"""Sauron Vision — Custom exceptions."""


class SauronVisionError(Exception):
    """Base exception for Sauron Vision."""
    pass


class DataFetchError(SauronVisionError):
    """Failed to fetch data from an external source."""
    pass


class RateLimitError(SauronVisionError):
    """API rate limit exceeded."""
    pass


class AIProviderError(SauronVisionError):
    """AI provider returned an error."""
    pass


class InsufficientDataError(SauronVisionError):
    """Not enough data to perform the requested analysis."""
    pass


class PortfolioConstraintError(SauronVisionError):
    """A portfolio risk constraint would be violated."""
    pass
