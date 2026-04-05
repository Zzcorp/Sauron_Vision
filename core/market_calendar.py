"""Market hours and session awareness."""
from datetime import datetime, time
import pytz


def is_forex_open(now=None):
    """Forex trades 24/5: Sunday 21:00 UTC to Friday 21:00 UTC."""
    now = now or datetime.now(pytz.UTC)
    weekday = now.weekday()
    t = now.time()

    if weekday == 6:  # Sunday
        return t >= time(21, 0)
    elif weekday == 4:  # Friday
        return t < time(21, 0)
    elif weekday == 5:  # Saturday
        return False
    return True


def is_us_market_open(now=None):
    """NYSE/NASDAQ: Mon-Fri 13:30-20:00 UTC."""
    now = now or datetime.now(pytz.UTC)
    weekday = now.weekday()
    t = now.time()

    if weekday >= 5:
        return False
    return time(13, 30) <= t < time(20, 0)


def is_eu_market_open(now=None):
    """European exchanges: Mon-Fri 07:00-15:30 UTC."""
    now = now or datetime.now(pytz.UTC)
    weekday = now.weekday()
    t = now.time()

    if weekday >= 5:
        return False
    return time(7, 0) <= t < time(15, 30)


def is_any_market_open(now=None):
    """Returns True if any major market session is active."""
    now = now or datetime.now(pytz.UTC)
    return is_forex_open(now) or is_us_market_open(now) or is_eu_market_open(now)


def get_active_sessions(now=None):
    """Returns list of currently active trading sessions."""
    now = now or datetime.now(pytz.UTC)
    sessions = []
    if is_us_market_open(now):
        sessions.append("new_york")
    if is_eu_market_open(now):
        sessions.append("london")
    if is_forex_open(now):
        sessions.append("forex")
    return sessions


def is_weekend(now=None):
    """Returns True if it's the weekend (Saturday or Sunday before forex open)."""
    now = now or datetime.now(pytz.UTC)
    weekday = now.weekday()
    if weekday == 5:
        return True
    if weekday == 6 and now.time() < time(21, 0):
        return True
    return False
