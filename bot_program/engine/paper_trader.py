"""Paper trading engine — simulates fills without real orders."""
import logging
import uuid
from decimal import Decimal
from django.utils import timezone

logger = logging.getLogger(__name__)


class PaperTrader:
    """Simulates order execution with realistic fills."""

    def __init__(self, config):
        self.config = config
        self.slippage_bps = 5  # basis points

    def ping(self):
        """Always reachable in paper mode."""
        return True

    def market_order(self, symbol, side, quantity, current_price=None, **kwargs):
        """Simulate a market order fill."""
        from bot_program.models import BotTrade

        if current_price is None:
            # Try to get latest price from market data
            try:
                from market_data.models import LiveQuote
                from instruments.models import Instrument
                instrument = Instrument.objects.filter(symbol=symbol).first()
                if instrument:
                    lq = LiveQuote.objects.get(instrument=instrument)
                    current_price = Decimal(str(lq.last))
                else:
                    current_price = Decimal("0")
            except Exception:
                current_price = Decimal("0")

        current_price = Decimal(str(current_price))

        # Apply slippage
        slip = Decimal(str(self.slippage_bps)) / Decimal("10000")
        if side == "BUY":
            fill_price = current_price * (1 + slip)
        else:
            fill_price = current_price * (1 - slip)

        order_id = f"PAPER-{uuid.uuid4().hex[:12]}"

        logger.info(
            "[PAPER] %s %s %s @ %.8f (slip from %s)",
            side, quantity, symbol, fill_price, current_price,
        )

        return {
            "orderId": order_id,
            "symbol": symbol,
            "side": side,
            "executedQty": str(quantity),
            "avgPrice": str(fill_price),
            "status": "FILLED",
            "paper": True,
        }

    def ticker(self, symbol):
        """Return a simulated ticker using the latest live quote."""
        try:
            from market_data.models import LiveQuote
            from instruments.models import Instrument
            instrument = Instrument.objects.filter(symbol=symbol).first()
            if instrument:
                lq = LiveQuote.objects.get(instrument=instrument)
                return {"lastPrice": str(lq.last), "symbol": symbol}
        except Exception:
            pass
        return {"lastPrice": "0", "symbol": symbol}

    def klines(self, symbol, interval="1h", limit=200):
        """Return historical OHLCV data from local PriceData."""
        try:
            from market_data.models import PriceData
            from instruments.models import Instrument
            instrument = Instrument.objects.filter(symbol=symbol).first()
            if not instrument:
                return []
            rows = PriceData.objects.filter(
                instrument=instrument, timeframe=interval
            ).order_by("-timestamp")[:limit]
            # Return in ascending order matching Binance kline format
            result = []
            for r in reversed(list(rows)):
                result.append([
                    int(r.timestamp.timestamp() * 1000),  # openTime
                    str(r.open), str(r.high), str(r.low), str(r.close),
                    str(r.volume),
                    int(r.timestamp.timestamp() * 1000) + 3600000,  # closeTime
                    "0", 0, "0", "0", "0",
                ])
            return result
        except Exception:
            return []

    def order_book(self, symbol, limit=50):
        """Return a minimal simulated order book."""
        try:
            from market_data.models import LiveQuote
            from instruments.models import Instrument
            instrument = Instrument.objects.filter(symbol=symbol).first()
            if instrument:
                lq = LiveQuote.objects.get(instrument=instrument)
                price = float(lq.last)
                bids = [[str(round(price * (1 - i * 0.0001), 8)), "10"] for i in range(limit)]
                asks = [[str(round(price * (1 + i * 0.0001), 8)), "10"] for i in range(limit)]
                return {"bids": bids, "asks": asks}
        except Exception:
            pass
        return {"bids": [], "asks": []}

    def get_balance(self):
        """Get simulated balance from portfolio."""
        from portfolio.services import get_or_create_default_portfolio
        portfolio = get_or_create_default_portfolio()
        return float(portfolio.cash_available)

    def get_positions(self):
        """Get open paper positions."""
        from bot_program.models import BotTrade
        return list(BotTrade.objects.filter(
            config=self.config,
            exit_price__isnull=True,
            binance_order_id__startswith="PAPER-",
        ).values("symbol", "side", "qty", "entry_price"))
