"""Why a symbol did not trade.

`scan_symbol` has fourteen `return None` exits. Several logged nothing at
all, and none of them left anything queryable behind — so from the outside,
"the market was quiet" and "this bot has been structurally incapable of
trading since it was created" produce the identical observation: no trades,
a green health page, and nothing to look at.

That is the single most expensive property of a system with no track record.
In the first weeks the skip-reason DISTRIBUTION matters more than the trade
count: `no_signals` every tick on every symbol is a quiet market;
`no_instrument` every tick is a typo in the symbol list; `stage_blocked`
every tick means the rule was never promoted and never will be.

Deliberately stored on `AssetBotConfig.extras` rather than in a new table.
At zero trades nobody knows what the real row volume looks like, so a
retention policy would be a guess — and the JSON version answers the same
question in a fraction of the code. Bounded by construction: one entry per
symbol the config trades, one counter per reason code.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# The vocabulary. Keeping it closed means the counters stay comparable and
# a typo cannot silently invent a new category.
NO_INSTRUMENT = "no_instrument"       # symbol is not in the Instrument table
NO_SIGNALS = "no_signals"             # nothing active and fresh to vote on
STALE_SIGNALS = "stale_signals"       # active signals exist but all too old
HOLD = "hold"                         # signals voted, consensus was HOLD
COOLDOWN = "cooldown"                 # traded this symbol too recently
ALREADY_OPEN = "already_open"         # a position is already on
GATE_BLOCKED = "gate_blocked"         # orchestrator / exposure declined
STAGE_BLOCKED = "stage_blocked"       # promotion stage forbids orders
PAPER_FALLBACK = "paper_fallback"     # live config, no working broker
NO_PRICE = "no_price"                 # ticker gave nothing usable
COST_FILTER = "cost_filter"           # planned move cannot cover the spread
SIZED_TO_ZERO = "sized_to_zero"       # risk budget below one tradeable unit
SHADOW = "shadow"                     # shadow mode: computed, not submitted
ORDER_REJECTED = "order_rejected"     # broker refused
ERROR = "error"                       # an exception on the entry path

MAX_SYMBOLS_TRACKED = 200


def record(cfg, symbol: str, code: str, detail: str = "") -> None:
    """Note why `symbol` produced no trade on this tick. Never raises."""
    from django.utils import timezone
    from bot_program.asset_engine.safety import _extras, _save_extras

    try:
        extras = _extras(cfg)
        skips = dict(extras.get("skips") or {})
        counts = dict(extras.get("skip_counts") or {})

        if symbol not in skips and len(skips) >= MAX_SYMBOLS_TRACKED:
            # A config with a runaway symbol list must not grow extras without
            # bound; the counters still tell the story.
            skips.pop(next(iter(skips)), None)

        skips[symbol] = {"code": code, "detail": str(detail)[:200],
                         "at": timezone.now().isoformat()}
        counts[code] = int(counts.get(code, 0)) + 1
        _save_extras(cfg, skips=skips, skip_counts=counts)
    except Exception:
        # Diagnostics must never be the reason a tick fails.
        logger.debug("[skips] could not record %s/%s for config %s",
                     symbol, code, getattr(cfg, "id", "?"))


def clear(cfg, symbol: str) -> None:
    """Forget the last skip for a symbol that has just traded."""
    from bot_program.asset_engine.safety import _extras, _save_extras
    try:
        skips = dict(_extras(cfg).get("skips") or {})
        if skips.pop(symbol, None) is not None:
            _save_extras(cfg, skips=skips)
    except Exception:
        logger.debug("[skips] could not clear %s for config %s",
                     symbol, getattr(cfg, "id", "?"))


def summary(cfg) -> dict:
    """{code: count} for this config, most frequent first."""
    from bot_program.asset_engine.safety import _extras
    counts = dict(_extras(cfg).get("skip_counts") or {})
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))


def last_by_symbol(cfg) -> dict:
    from bot_program.asset_engine.safety import _extras
    return dict(_extras(cfg).get("skips") or {})


def diagnose(cfg) -> str:
    """One sentence an operator can act on, from the distribution alone."""
    counts = summary(cfg)
    if not counts:
        return "no skips recorded yet — the bot has not completed a scan"
    top, n = next(iter(counts.items()))
    total = sum(counts.values())
    share = n / total if total else 0
    advice = {
        NO_INSTRUMENT: "the symbol list does not match any seeded Instrument — "
                       "check spelling (EURUSD not EUR_USD, BTCUSD not BTCUSDT)",
        NO_SIGNALS: "no rule is producing signals — check that bars exist and "
                    "the signal scan is running",
        STALE_SIGNALS: "signals exist but are older than the age window; the "
                       "lifecycle pass may be stuck for want of fresh quotes",
        STAGE_BLOCKED: "the rule is not promoted far enough to place orders",
        PAPER_FALLBACK: "a live config has no working broker credentials",
        NO_PRICE: "the market-data client returns no usable price",
        COST_FILTER: "planned moves are too small to cover the round trip",
        SIZED_TO_ZERO: "the risk budget is below one tradeable unit — fund more "
                       "capital or raise extras['risk_per_trade_pct']",
        SHADOW: "shadow mode is on: everything is computed, nothing submitted",
    }.get(top, "")
    return (f"{top} accounts for {share:.0%} of {total} skips"
            + (f" — {advice}" if advice else ""))
