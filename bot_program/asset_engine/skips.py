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
# The two exits that were still a bare `return None` when the entry path was
# split for the capital desk (2026-09-12). Both looked, from outside, like a
# quiet market.
BRAIN_PAUSED = "brain_paused"         # the brain advised pause_recommended
# An order that MAY BE LIVE. Distinct from order_error on purpose: that
# one means "no order exists", and this one means "nobody knows" — the
# request did not come back. A caller that treats them alike retries, and
# doubles the position.
ORDER_IN_DOUBT = "order_in_doubt"
ORDER_ERROR = "order_error"           # the live order raised (never sent, or unknown)
# 2026-09-20. THE SIZE IS FINE AND THE VENUE WILL NOT TAKE IT. Distinct from
# sized_to_zero, which means the risk budget bought less than one unit of the
# bot's OWN rounding granularity, and from order_error, whose advice sends
# the operator to the gateway. This is neither: the quantity is positive,
# judged and correct, and the venue's floor is above it. A forex bot sizing
# 400 units from its stop distance (_round_qty snaps to 100, which is
# OANDA/IBKR granularity and no venue's rule) was refused by the adapter on
# every tick and recorded as order_error, so a repeated line read as a broken
# connection instead of a decision to make. NOTHING IS RESIZED: raising the
# size to the floor is a different trade (see SaxoTrader._amount), so the
# operator is handed both numbers and chooses.
VENUE_MIN_SIZE = "venue_min_size"
# The capital desk ranked this candidate below the tick's budget, a rule or
# class share cap, or an open position it correlates with — and the desk was
# in LIVE mode, so nothing was sent. A CHOICE, not a fault: the detail names
# the plan and the reason so the operator can read the ladder on /desk/ and
# see what took the capital instead (2026-09-12).
DESK_DISPLACED = "desk_displaced"
# 2026-09-23. A LEVERED order the platform refused to send: extras['leverage']
# is not a whole number or is past a cap, the order would be carried by a
# venue other than eToro, the component etoro_leverage_live is OFF, the
# operator's own book on /setup/ was never saved, the account's available
# cash (the sync's cells) is unmeasured, stale, in another currency or too
# small, the account would be pledged past its ceiling, or eToro refused a
# levered order on that symbol within the quiet hours. Its own code so a
# repeated line reads as a DECISION with both numbers, never as a broken
# connection (order_error) or a small pool (sized_to_zero). NOTHING IS
# RESIZED OR DE-LEVERED: the operator is handed the numbers and chooses.
LEVERAGE_REFUSED = "leverage_refused"

# 2026-09-25 (Stage 1). eToro's OWN eligibility row said no — read once per
# instrument per UTC day once read, an unread row asked again on every ask
# (EtoroTrader.eligibility, MEASURED 2026-09-23), by step 2 of
# AssetBot._etoro_entry_refusal, on every lane: the venue lists no row for
# the id today ("absent"), allowOpenPosition is false, the size is past
# maxUnitsPerOrder (refused, never clamped), or the row could not be read
# today for a levered order or for a class whose measured floor is 1,000
# USD (forex, index, commodity). Its own code so the operator reads the
# venue's answer, never a broken connection (order_error) or a small pool
# (sized_to_zero). NOTHING IS RESIZED OR CLAMPED.
ELIGIBILITY_REFUSED = "eligibility_refused"

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
        BRAIN_PAUSED: "the brain has this rule on pause_recommended — read "
                      "the latest BrainReport before overriding it",
        ORDER_IN_DOUBT: "the order request did not come back, so the order "
                        "MAY be live at the broker with no row here — "
                        "search the broker for the reference in the detail "
                        "before arming this symbol again",
        ORDER_ERROR: "the broker client raised on the order — check the "
                     "gateway and the bot log; nothing was booked",
        # The remedies raise the UNIT COUNT, and a wider stop lowers it:
        # units = risk budget / stop distance. This advice said "widen the
        # stop" first, which would drive the size further below the floor it
        # is meant to clear.
        VENUE_MIN_SIZE: "the venue's minimum trade size is above the size "
                        "the stop distance buys — nothing is wrong with the "
                        "connection and nothing was resized. Raise the "
                        "pool's capital, raise extras['risk_per_trade_pct'], "
                        "or TIGHTEN the stop: a tighter stop buys more "
                        "units, a wider one buys fewer. Moving the whole "
                        "asset class off this venue on /brokers/ also works, "
                        "but it moves every symbol in the class — close any "
                        "position still open there first. The detail carries "
                        "both numbers",
        DESK_DISPLACED: "the capital desk is ranking these entries below "
                        "others — read the ladder on /desk/ to see what "
                        "took the risk budget instead",
        LEVERAGE_REFUSED: "a levered eToro order was refused before it left "
                          "— read the detail: the value, the carrier, the "
                          "etoro_leverage_live switch, the instrument's "
                          "LIVE leverageValues and maxStopLossPercentage "
                          "(eligibility, doc 2026-09-23 §9), the class's "
                          "ETORO_PROVEN token (ETORO_DEPARTURE §7-0), the "
                          "book on /setup/, the account's cash and its "
                          "world stamp, or a refusal eToro gave within the "
                          "quiet hours; nothing was sent at 1 (since "
                          "2026-09-26 a 1x eToro order needs the cells "
                          "too) and nothing was de-levered",
        ELIGIBILITY_REFUSED: "eToro's own eligibility row refused the entry "
                             "before it left — read the detail: no row for "
                             "the symbol today, allowOpenPosition false, a "
                             "size past maxUnitsPerOrder, or a row unread "
                             "today for a levered order or a forex/index/"
                             "commodity symbol (their measured floor is "
                             "1,000 USD). Nothing was sent and nothing was "
                             "clamped; the row is re-read once per UTC day, "
                             "an unread one on every ask",
    }.get(top, "")
    return (f"{top} accounts for {share:.0%} of {total} skips"
            + (f" — {advice}" if advice else ""))
