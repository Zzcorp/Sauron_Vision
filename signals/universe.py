"""The instrument universe the scheduled pipeline actually works on.

The watchlist is a *display* concept — it drives the dashboard headband and
the quote pollers. The bots trade whatever sits in `AssetBotConfig.symbols`,
which is a different set. Scanning only the watchlist meant a bot symbol
could have fresh bars and still never receive a Signal row, so `decide()`
returned HOLD forever: the chain bars -> rules -> signals -> decision was
broken at the third link.

Everything scheduled (indicators, signal scan) resolves its universe here,
so the two can never drift apart again.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def bot_symbols() -> set[str]:
    """Every symbol an enabled bot config trades."""
    try:
        from bot_program.models import AssetBotConfig
    except Exception:
        return set()
    out: set[str] = set()
    for cfg in AssetBotConfig.objects.filter(enabled=True).only("symbols"):
        out.update(s for s in (cfg.symbols or []) if s)
    return out


def scan_universe(include_watchlist: bool = True):
    """Instruments the scheduled pipeline should process.

    Union of the watchlist and every enabled bot's symbols — a bot symbol
    must be scanned whether or not a human starred it.
    """
    from django.db.models import Q
    from instruments.models import Instrument

    symbols = bot_symbols()
    q = Q(symbol__in=symbols) if symbols else Q(pk__in=[])
    if include_watchlist:
        q = Q(is_watchlist=True) | q
    qs = Instrument.objects.filter(q, is_active=True).distinct()
    logger.debug("[universe] %d instruments (%d bot symbols)",
                 qs.count(), len(symbols))
    return qs
