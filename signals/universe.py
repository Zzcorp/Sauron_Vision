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


def scan_universe(include_watchlist: bool = True, asset_class: str = ""):
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
    if asset_class:
        qs = qs.filter(asset_class=asset_class)
    logger.debug("[universe] %d instruments (%d bot symbols)",
                 qs.count(), len(symbols))
    return qs


def quote_targets(asset_class: str, limit: int = 0) -> list:
    """Instruments to poll for live quotes, bot symbols first.

    The quote pollers used to read the watchlist alone. A bot trading a
    symbol nobody had starred therefore got bars and signals but no
    LiveQuote — and LiveQuote is what `_mark_price` and the paper fill path
    read, so the bot could form a decision it could never act on.

    Free-tier providers cap how many symbols one run may fetch, so ordering
    matters as much as membership: when the list is truncated the symbols
    with real money behind them must be the ones that survive.
    """
    from django.utils import timezone

    traded = bot_symbols()
    rows = list(scan_universe(asset_class=asset_class))
    rows.sort(key=lambda i: (i.symbol not in traded, i.symbol))

    # Rotate the traded block. A fixed alphabetical order means that once
    # the provider cap binds, the SAME funded symbols are polled every run
    # and the ones past the cut never get a quote at all — a permanent
    # blind spot rather than the reduced refresh rate the cap implies.
    funded = [i for i in rows if i.symbol in traded]
    if limit and len(funded) > limit:
        offset = int(timezone.now().timestamp() // 60) % len(funded)
        funded = funded[offset:] + funded[:offset]
        rows = funded + [i for i in rows if i.symbol not in traded]

    if limit and len(rows) > limit:
        dropped = [i.symbol for i in rows[limit:] if i.symbol in traded]
        if dropped:
            logger.warning("[universe] %s quote budget of %d truncates %d "
                           "traded symbol(s) this run: %s", asset_class, limit,
                           len(dropped), ", ".join(sorted(dropped)))
        rows = rows[:limit]
    return rows
