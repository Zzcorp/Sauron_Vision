"""CryptoBot — the asset class the modern engine never had.

`AssetBotConfig.ASSET_CLASS_CHOICES` offered stock, forex, commodity,
options and cfd. Crypto was missing entirely, even though the rest of the
platform is full of crypto handling: `broker_router` routes crypto symbols
to Binance, `risk_levels.DEFAULT_COST_BPS` carries a crypto entry,
`market_data/bot_bars.py` special-cases it, and there are three Binance
streamers. Crypto lived only in the LEGACY `BotConfig` engine, which no
scheduler entry drives.

That mattered more than a missing option in a dropdown, because crypto is
the only asset class whose market data is free and keyless. Every other
class needs broker credentials before it can produce a single bar — so on a
fresh install with no broker relationship, crypto was the one path from
"nothing" to "a graded paper trade", and it was the one path that did not
exist.

The class itself is deliberately thin. Everything that makes crypto
different from equities is already handled elsewhere:
  * routing to Binance — broker_router
  * 24/7 trading — the base class never gated on market hours anyway
  * cost model — risk_levels.DEFAULT_COST_BPS["crypto"]
  * bars without credentials — bot_bars._public_market_data_client

What is left is the quantity convention: crypto is divisible far below one
unit, so rounding to whole units would size almost every position to zero
at any sane risk budget. 0.0003 BTC is a normal position.
"""
from __future__ import annotations

import logging

from .base import AssetBot

logger = logging.getLogger(__name__)

# Binance quantity precision varies per symbol (LOT_SIZE stepSize). Eight
# decimals is the finest any spot pair uses, so it never rounds a valid size
# up to something the venue rejects for being too large.
QTY_DECIMALS = 8


class CryptoBot(AssetBot):
    asset_class = "crypto"

    def _round_qty(self, qty: float, price: float) -> float:
        """Fractional units, to eight decimals.

        A $25 risk budget on BTC at $65,000 with a 3% stop is 0.0128 BTC.
        Whole-unit rounding would make that 0, and the entry path treats 0 as
        "do not trade" — so the bot would silently never trade the one asset
        class it can get free data for.
        """
        rounded = round(float(qty), QTY_DECIMALS)
        if rounded <= 0 and qty > 0:
            logger.info(
                "[crypto_bot] %s: size %.12f rounds to zero at %d decimals "
                "— the risk budget is below the venue's minimum increment",
                self.cfg.name, qty, QTY_DECIMALS)
        return rounded
