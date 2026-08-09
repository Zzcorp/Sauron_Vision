"""CommodityBot — paper-only by design (no live commodity broker integrated).

Phase-4 broker_router routes commodity asset_class to PaperTrader explicitly
since CFD / futures brokers (IG, IBKR, etc.) have heavy regulatory requirements
that vary by jurisdiction. The bot still runs the full decision loop and
records paper trades; admin uses these for strategy validation only.
"""
import logging

from .base import AssetBot

logger = logging.getLogger(__name__)


class CommodityBot(AssetBot):
    asset_class = "commodity"

    def __init__(self, config):
        super().__init__(config)
        # Force paper mode regardless of config — no live commodity broker.
        if config.mode == "live":
            logger.warning(
                "[commodity_bot] no live broker integrated; forcing paper mode for cfg=%s",
                config.id,
            )
            config.mode = "paper"
            # Don't .save() — caller might prefer ephemeral override; runners
            # set this every tick anyway.

    def _round_qty(self, qty: float, price: float) -> float:
        """Fractional contracts allowed (paper-only for now).

        Real commodity sizing needs contract specs (CL = 1000 bbl, GC =
        100 oz); when a live broker is added those belong in
        _value_per_unit, so that risk sizing counts a point of price as the
        dollars it actually is.
        """
        return round(float(qty), 4)

    def position_size(self, price: float) -> float:
        """LEGACY notional sizing — see AssetBot.position_size.

        Real commodity sizing depends on contract specs (CL = 1000 bbl, GC =
        100 oz, etc.) — those go in `extras = {"contract_size": 1000}` per
        symbol when a live broker is added.
        """
        cap = float(self.cfg.capital)
        dollars = cap * (self.cfg.position_size_pct / 100.0)
        if price <= 0:
            return 0.0
        return round(dollars / price, 4)
