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


# ── The account itself, as the broker reports it ──────────────────────────
#
# Everything below is USER-scoped where everything above is CONFIG-scoped,
# because the operator's question changed shape: not "does this bot's pool
# match the account" but "what does the account actually hold". The
# config-scoped helper cannot answer it — broker_equity(user, cfg) returns
# None for a paper config and for a config with no symbols, so a funded ISA
# with no bot armed on it is structurally unmeasurable through that path.


def broker_backed(user):
    """The IBKRAccount that makes this user's book broker-backed, or None.

    INTERFACED is a durable configuration fact: an IBKRAccount row whose
    account id decrypts to something non-empty. Deliberately NOT
    `connected` — that is a boolean with no expiry meaning "a socket
    answered once", and a gateway that restarts nightly for 2FA leaves it
    True forever. Reachability is a different question and it is answered
    by the AGE of the last reading, never by a stored flag.
    """
    acct = getattr(user, "ibkr_account", None)
    if acct is None:
        return None
    try:
        account_id = acct.get_account_id() or ""
    except Exception:  # noqa: BLE001 — an undecryptable id is not backed
        return None
    return acct if account_id else None


def account_equity(user):
    """{"value", "currency", "at", "age_seconds"} from the LAST SYNC, or None.

    Reads the cached columns only. Broker I/O lives in the
    sync_broker_account beat task and nowhere else — a broker round trip
    does not belong on a render path, and definitely not on an entry path.
    None means no reading has ever landed; the caller renders an em-dash
    and the AGE tells the operator whether the number can be believed.
    """
    from django.utils import timezone

    acct = broker_backed(user)
    if acct is None or acct.last_equity is None or acct.last_equity_at is None:
        return None
    value = float(acct.last_equity)
    return {
        "value": value,
        # Pre-grouped here because the templates that render this do not
        # all load humanize, and 52340.12 without separators misreads at
        # a glance in exactly the way a money cell must not.
        "value_text": f"{value:,.2f}",
        "currency": acct.last_equity_currency or "",
        "at": acct.last_equity_at,
        "age_seconds": int(
            (timezone.now() - acct.last_equity_at).total_seconds()),
    }


def broker_positions(user):
    """{"rows", "at", "age_seconds"} from the last sync, or None.

    The broker's OWN holdings, verbatim from broker_portfolio() — a
    display snapshot, never imported into Position or AssetBotTrade.
    """
    from django.utils import timezone

    acct = broker_backed(user)
    if acct is None or acct.broker_positions is None \
            or acct.broker_positions_at is None:
        return None
    return {
        "rows": list(acct.broker_positions or []),
        "at": acct.broker_positions_at,
        "age_seconds": int(
            (timezone.now() - acct.broker_positions_at).total_seconds()),
    }


def pool_oversubscription(user):
    """Live pools summed per venue against that venue's equity, or [].

    `capital_mismatches` above compares EACH config against the WHOLE
    account, so three configs each declaring the full balance all read
    "agrees" while the fleet is 3x oversubscribed — the exact dangerous
    direction this module was written to catch, invisible to the check
    whose entire value is being believed. This is the aggregate half.

    Returns [{venue, declared_total, actual, ratio, configs}] for every
    venue where the SUM of declared pools exceeds the broker's equity by
    more than TOLERANCE_PCT.
    """
    from collections import defaultdict

    from bot_program.models import AssetBotConfig

    groups = defaultdict(lambda: {"declared": 0.0, "configs": [],
                                  "actual": None})
    configs = (AssetBotConfig.objects
               .filter(user=user, enabled=True)
               .exclude(mode="paper"))
    for cfg in configs:
        declared = float(getattr(cfg, "capital", 0) or 0)
        if declared <= 0:
            continue
        symbols = list(getattr(cfg, "symbols", None) or [])
        if not symbols:
            continue
        try:
            from bot_program.engine.broker_router import client_for_symbol
            client = client_for_symbol(user, symbols[0], cfg)
        except Exception:  # noqa: BLE001
            continue
        venue = type(client).__name__
        if venue == "PaperTrader":
            continue
        g = groups[venue]
        g["declared"] += declared
        g["configs"].append(cfg.name)
        if g["actual"] is None:
            g["actual"] = broker_equity(user, cfg)

    out = []
    for venue, g in groups.items():
        actual = g["actual"]
        if actual is None or len(g["configs"]) < 2:
            # One config per venue is already covered by
            # capital_mismatches; the aggregate only says something new
            # when several pools draw on one account.
            continue
        drift = (g["declared"] - actual) / max(actual, 1e-9) * 100.0
        if drift <= TOLERANCE_PCT:
            continue
        out.append({
            "venue": venue,
            "declared_total": round(g["declared"], 2),
            "actual": round(actual, 2),
            "ratio": round(g["declared"] / actual, 2),
            "configs": sorted(g["configs"]),
        })
    return out


# ── Pools that follow the account ────────────────────────────────────────
#
# extras["capital_tracks_broker"] marks a pool whose capital the
# sync_broker_account beat keeps equal to the broker's own reading — the
# operator's request that sizing use the funds actually available rather
# than a number typed once. One narrow exception to this module's
# measure-only charter: when such a pool's reading is stale, NEW entries
# are refused, because the number being followed is no longer known.
TRACKING_FRESH_SECONDS = 3600


def tracks_broker(cfg) -> bool:
    """Does this pool follow the broker's account reading?"""
    try:
        return bool((getattr(cfg, "extras", None) or {}).get(
            "capital_tracks_broker"))
    except Exception:  # noqa: BLE001
        return False


def tracking_freeze_reason(user, cfg):
    """Why an account-following pool must not OPEN right now, or None.

    Pure DB reads (the cached columns) — safe on entry paths. Only opens
    are affected: exits, stops and management keep running whatever the
    reading's age, because an existing position must stay managed.
    """
    if not tracks_broker(cfg):
        return None
    reading = account_equity(user)
    if reading is None:
        return ("this pool follows the broker account and no reading has "
                "landed yet — enable broker_account_sync and let it store "
                "one")
    if reading["age_seconds"] > TRACKING_FRESH_SECONDS:
        hours = reading["age_seconds"] / 3600.0
        return (f"this pool follows the broker account and the last "
                f"reading is {hours:.1f}h old — new entries wait until a "
                f"fresh reading lands (is the Gateway logged in?)")
    return None


def broker_view(user):
    """Everything a broker-truth CELL needs, or None when not interfaced.

    One builder so the Operations Center, the portfolio page, /setup/ and
    the positions page cannot drift apart on what "interfaced" means or
    which columns they read. Pure DB reads — safe on any render path.
    """
    acct = broker_backed(user)
    if acct is None:
        return None
    return {
        "label": acct.label,
        "env": acct.env_label,
        "equity": account_equity(user),
        "positions": broker_positions(user),
    }
