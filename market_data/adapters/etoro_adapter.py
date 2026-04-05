"""eToro API adapter — portfolio sync, positions, trading."""
import os
import requests
import logging

logger = logging.getLogger(__name__)

API_KEY = os.getenv("ETORO_API_KEY", "")
BASE_URL = "https://api.etoro.com"  # Official eToro API


class EtoroClient:
    """Client for eToro Public API."""

    def __init__(self, api_key=None):
        self.api_key = api_key or API_KEY
        self.session = requests.Session()
        if self.api_key:
            self.session.headers.update({
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            })

    def is_configured(self):
        return bool(self.api_key)

    def get_portfolio(self):
        """Fetch current portfolio positions from eToro."""
        try:
            resp = self.session.get(f"{BASE_URL}/api/v1/portfolio")
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"eToro portfolio fetch failed: {e}")
            return None

    def get_positions(self):
        """Fetch open positions."""
        try:
            resp = self.session.get(f"{BASE_URL}/api/v1/positions")
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"eToro positions fetch failed: {e}")
            return None

    def get_account_balance(self):
        """Fetch account balance and equity."""
        try:
            resp = self.session.get(f"{BASE_URL}/api/v1/account/balance")
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"eToro balance fetch failed: {e}")
            return None


def sync_etoro_positions():
    """Sync eToro positions into Sauron Vision portfolio."""
    from instruments.models import Instrument
    from portfolio.models import Position
    from portfolio.services import get_or_create_default_portfolio
    from django.utils import timezone

    client = EtoroClient()
    if not client.is_configured():
        logger.warning("eToro API key not configured")
        return {"status": "not_configured"}

    positions_data = client.get_positions()
    if not positions_data:
        return {"status": "fetch_failed"}

    portfolio = get_or_create_default_portfolio()
    synced = 0

    for pos in positions_data.get("positions", []):
        symbol = pos.get("symbol", "")
        instrument, _ = Instrument.objects.get_or_create(
            symbol=symbol,
            defaults={
                "name": pos.get("name", symbol),
                "asset_class": "stock",
                "exchange": "ETORO",
                "is_active": True,
            }
        )

        Position.objects.update_or_create(
            portfolio=portfolio,
            instrument=instrument,
            closed_at__isnull=True,
            defaults={
                "direction": "long" if pos.get("isBuy", True) else "short",
                "quantity": pos.get("amount", 0),
                "entry_price": pos.get("openRate", 0),
                "current_price": pos.get("currentRate", 0),
                "stop_loss": pos.get("stopLossRate"),
                "take_profit": pos.get("takeProfitRate"),
                "unrealized_pnl": pos.get("netProfit", 0),
                "unrealized_pnl_pct": pos.get("netProfitPercentage", 0),
                "opened_at": timezone.now(),
            }
        )
        synced += 1

    # Sync balance
    balance = client.get_account_balance()
    if balance:
        portfolio.current_value = balance.get("equity", portfolio.current_value)
        portfolio.cash_available = balance.get("availableBalance", portfolio.cash_available)
        portfolio.save()

    return {"status": "success", "synced": synced}
