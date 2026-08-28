"""Is the pool every risk limit divides by the money that actually exists?

`AssetBotConfig.capital` is the denominator of the entire per-config risk
stack:

    sizing.py       divides the risk budget by it
    base.py         the daily-loss floor is -capital x max_daily_loss_pct
    safety.py       the drawdown curve starts at it
    base.py         it is the capital_base both single_position_state calls
                    pass, under the label "bot pool"

And it is a number typed into a form. `hq_save_asset_bot` writes it
straight from the POST with no reference to any account, and arming live
checks only the PIN. Meanwhile every live client already implements
`balance_usdt()`, and nothing has ever compared the two.

The direction of the error is what matters. If the declared pool is LARGER
than the broker's equity, every limit derived from it is looser than the
operator set — a "2% daily loss" on a declared 100,000 against a real
20,000 is a 10% daily loss. That is the dangerous direction, and it is the
easy mistake to make: the pool is a plan, and the account is what funded it.

This module only measures and reports. It deliberately does not gate
entries: a broker call on the entry path is a network round trip in front
of every order, and an operator who can SEE the mismatch can fix it in one
edit. The value is in the seeing.
"""
import logging

logger = logging.getLogger(__name__)

# One broker call per config per this many seconds. Equity moves slowly
# relative to a tick loop, and a health page refresh must not become a
# burst of broker traffic.
CACHE_SECONDS = 900

# Below this the two numbers are the same for every practical purpose and
# saying otherwise is noise an operator learns to ignore.
TOLERANCE_PCT = 5.0


def broker_equity(user, cfg):
    """The broker's own equity for this config's account, or None.

    None means "not measured" and NEVER 0.0. A paper config has no broker
    account to ask, and a failed call is an unknown — booking either as
    zero would report the account as empty, which is both alarming and
    false.
    """
    from django.utils import timezone

    extras = dict(getattr(cfg, "extras", None) or {})
    cached, stamped = extras.get("broker_equity"), extras.get("broker_equity_at")
    if cached is not None and stamped:
        try:
            from django.utils.dateparse import parse_datetime
            when = parse_datetime(str(stamped))
            if when and (timezone.now() - when).total_seconds() < CACHE_SECONDS:
                return float(cached)
        except (TypeError, ValueError):
            pass

    if (getattr(cfg, "mode", "") or "").lower() == "paper":
        return None

    symbols = list(getattr(cfg, "symbols", None) or [])
    if not symbols:
        return None

    try:
        from bot_program.engine.broker_router import client_for_symbol
        client = client_for_symbol(user, symbols[0], cfg)
    except Exception as e:  # noqa: BLE001 — an unknown must not raise
        logger.debug("capital_truth: no client for %s: %s",
                     getattr(cfg, "name", "?"), e)
        return None

    # A PaperTrader answers `get_balance`, not `balance_usdt`, and its
    # answer is a simulation. Asking it would compare a real pool against
    # an imaginary account.
    fn = getattr(client, "balance_usdt", None)
    if not callable(fn):
        return None

    try:
        equity = float(fn() or 0)
    except Exception as e:  # noqa: BLE001
        logger.debug("capital_truth: balance unreadable for %s: %s",
                     getattr(cfg, "name", "?"), e)
        return None
    if equity <= 0:
        # Zero from a live broker is either an empty account or an API
        # answering badly, and this module cannot tell which. Unmeasured.
        return None

    try:
        extras["broker_equity"] = equity
        extras["broker_equity_at"] = timezone.now().isoformat()
        cfg.extras = extras
        cfg.save(update_fields=["extras"])
    except Exception as e:  # noqa: BLE001 — caching is a convenience
        logger.debug("capital_truth: could not cache equity: %s", e)
    return equity


def capital_mismatches(user) -> list:
    """Live configs whose declared pool disagrees with the broker.

    Returns one dict per mismatch:
        {config, declared, actual, ratio, direction}

    `direction` is "over" when the declared pool exceeds broker equity —
    the dangerous way, because every limit derived from it is then looser
    than it reads.
    """
    from bot_program.models import AssetBotConfig

    out = []
    configs = (AssetBotConfig.objects
               .filter(user=user, enabled=True)
               .exclude(mode="paper"))
    for cfg in configs:
        declared = float(getattr(cfg, "capital", 0) or 0)
        if declared <= 0:
            continue
        actual = broker_equity(user, cfg)
        if actual is None:
            continue
        drift = abs(declared - actual) / max(actual, 1e-9) * 100.0
        if drift <= TOLERANCE_PCT:
            continue
        out.append({
            "config": cfg.name,
            "declared": round(declared, 2),
            "actual": round(actual, 2),
            "ratio": round(declared / actual, 2) if actual else None,
            "direction": "over" if declared > actual else "under",
        })
    return out
