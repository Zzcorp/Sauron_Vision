"""CommodityBot — trades where the router sends it (2026-09-26).

Until 2026-09-26 this class rewrote every live commodity config to paper
in __init__ ("no live commodity broker integrated"). That stopped being
true when eToro gained a commodities box on /brokers/: eToro carries
commodities as CFDs (MEASURED 2026-09-23: WHEAT.FUT 97 and PLATINUM 40,
CFD only, a 1,000 USD minimum exposure; the platform spells them
WHEATUSD and XPTUSD, etoro_client.VENUE_SPELLING). The mode is the
config's now. With no commodity box ticked (Saxo, eToro or IBKR) the
router hands a live config a PaperTrader (broker_router's default for
commodity is paper), and AssetBot refuses a live config on a
PaperTrader loudly (PAPER_FALLBACK) — one refusal for every class, not
a mode rewritten here. An eToro commodity entry still meets the proof
gate (ETORO_PROVEN) and the floor before any POST. A live commodity
order the router hands to IBKR or Saxo (their commodity flags, which
the old rewrite kept asleep; IBKR's reads True until
deploy/ETORO_DEPARTURE.md §2a) is refused at the same gate
(AssetBot._etoro_entry_refusal, step 0): neither venue has a commodity
proof, and IBKR is being retired.
"""
import logging

from .base import AssetBot

logger = logging.getLogger(__name__)


class CommodityBot(AssetBot):
    asset_class = "commodity"

    def _round_qty(self, qty: float, price: float, *,
                   fractional=None) -> float:
        """Fractional units, 4 decimals (eToro's commodity rows read
        unitsQuantityType 'fractional', measured 2026-09-23).

        Contract size is unmeasured on every venue (futures: CL = 1000
        bbl, GC = 100 oz; eToro's WHEAT.FUT and PLATINUM: requestedAmount /
        units is read by the commodity proof). Until it is, _value_per_unit
        stays the base class's 1.0: risk sizing counts a point of price as
        one unit of account.
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
