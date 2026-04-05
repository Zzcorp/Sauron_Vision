"""Platform-wide market configuration — admin controls which markets are active."""
from django.db import models


class MarketConfig(models.Model):
    """Global market enable/disable — controlled by admin."""
    market_key = models.CharField(max_length=20, unique=True)  # stock, forex, commodity, crypto, index, etf
    display_name = models.CharField(max_length=50)
    is_enabled = models.BooleanField(default=True)
    description = models.CharField(max_length=200, blank=True)
    icon = models.CharField(max_length=10, default="")
    scraper_component_key = models.CharField(max_length=50, blank=True)  # links to PlatformComponent
    order = models.IntegerField(default=0)

    class Meta:
        ordering = ["order"]

    def __str__(self):
        return f"{'ON' if self.is_enabled else 'OFF'} {self.display_name}"


DEFAULT_MARKETS = [
    {"market_key": "stock", "display_name": "Stocks", "icon": "S", "is_enabled": True, "order": 1,
     "description": "US, EU, Asia equities (NYSE, NASDAQ, LSE, etc.)"},
    {"market_key": "forex", "display_name": "Forex", "icon": "F", "is_enabled": True, "order": 2,
     "description": "49 currency pairs — majors, minors, exotics"},
    {"market_key": "commodity", "display_name": "Commodities", "icon": "C", "is_enabled": True, "order": 3,
     "description": "Gold, oil, gas, agriculture, metals"},
    {"market_key": "crypto", "display_name": "Crypto", "icon": "B", "is_enabled": False, "order": 4,
     "description": "Bitcoin, Ethereum, and 18+ altcoins via CoinGecko/Binance"},
    {"market_key": "index", "display_name": "Indices", "icon": "I", "is_enabled": True, "order": 5,
     "description": "S&P 500, Nasdaq, FTSE, DAX, Nikkei, etc."},
    {"market_key": "etf", "display_name": "ETFs", "icon": "E", "is_enabled": False, "order": 6,
     "description": "SPY, QQQ, GLD, ARKK, sector ETFs"},
]


def seed_market_configs():
    created = 0
    for m in DEFAULT_MARKETS:
        _, was = MarketConfig.objects.get_or_create(market_key=m["market_key"], defaults=m)
        if was:
            created += 1
    return created


def get_enabled_markets():
    """Return list of enabled market keys."""
    return list(MarketConfig.objects.filter(is_enabled=True).values_list("market_key", flat=True))
