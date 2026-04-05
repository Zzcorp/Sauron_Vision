"""Global context processors for Sauron Vision."""
from .exchange_status import get_exchange_status


def sauron_context(request):
    """Inject exchange status and user timezone into every template."""
    user_tz = "UTC"
    if request.user.is_authenticated:
        try:
            user_tz = request.user.trader_profile.timezone_preference or "UTC"
        except Exception:
            pass

    exchange_data = get_exchange_status()

    # Enabled markets
    try:
        from core.market_config import get_enabled_markets
        enabled_markets = get_enabled_markets()
    except Exception:
        enabled_markets = ["stock", "forex", "commodity"]

    return {
        "enabled_markets": enabled_markets,
        "user_timezone": user_tz,
        "exchanges_open_count": exchange_data["open_count"],
        "exchanges_total": exchange_data["total"],
        "exchanges_list": exchange_data["exchanges"],
    }
