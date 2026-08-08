"""Cross-asset orchestrator (Phase 15 + Phase 24).

The platform now has bots in every major asset class. Without coordination
they can stack exposure to the same underlying theme — a long-call on AAPL
+ long crypto + short USD/JPY + long gold are four trades but one bet (dollar
weakness, risk-on). The orchestrator gates new entries against per-user
theme caps so the bots can't unintentionally pyramid themed risk.

Phase 15 (legacy) themes:
  USD beta     +1 = long USD,    -1 = short USD
  EQUITY beta  +1 = long equity, -1 = short

Phase 24 additions:
  VOL_LONG     +1 per long-premium options trade (vega-positive). All long
               calls + long puts contribute; selling premium is out of scope.
  CURRENCIES   per-currency exposure for forex (handles non-USD crosses
               like EURGBP that the Phase-15 USD-only model missed)
  SECTORS      per-sector concentration count; uses Instrument.sector

Each Phase-24 dimension is INDEPENDENTLY OPT-IN via its cap field — set to 0
on TraderProfile to disable. Default 0 means existing users get exactly
Phase 15 behaviour until they configure the new caps.

Closes are NEVER gated — orchestrator only blocks new exposure.

Per-user opt-in via `TraderProfile.cross_asset_orchestrator_enabled`. When
the master toggle is off, `gate_new_entry` always returns (True, "orchestrator_off").
"""
from __future__ import annotations

import logging
from typing import Tuple

logger = logging.getLogger(__name__)


# Phase 24 — currencies recognised in forex symbol parsing.
KNOWN_CURRENCIES = {"USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD"}


# ── Theme classification ────────────────────────────────────────────────────

# Symbol-pattern hints for FX. We don't keep an exhaustive map — the heuristic
# is: split a 6-letter pair, look at base/quote against USD.
_FX_USD_PATTERNS = ("USD",)

# Equity-beta crypto and equity-beta commodities. Crypto-equity correlation
# has been positive since 2020; gold/silver behave more like USD-shorts.
_EQUITY_LIKE_CRYPTO = {"BTC", "ETH", "SOL"}
_USD_SHORT_COMMODITIES = {"GC", "SI", "GOLD", "SILVER", "XAUUSD", "XAGUSD"}


def classify_position(asset_class: str, symbol: str, side: str) -> dict:
    """Return theme contributions for one position.

    Result keys: 'usd', 'equity'. Values in [-1, +1] (or 0 = no exposure).

    Conventions:
      - BUY = long, SELL = short.
      - Forex BUY EURUSD = +1 EUR / -1 USD → usd: -1.
      - Stock BUY AAPL = equity: +1, usd: 0 (the bet is on the company, not FX).
      - Commodity BUY GC (gold) = usd: -1 (gold rallies on dollar weakness).
      - Crypto BUY BTC = equity: +1, usd: -1 (risk-on + USD short historically).
      - Options BUY (long call) = same direction as the underlying; long put
        = opposite. Encoded via metadata.right when present.
    """
    if not symbol:
        return {"usd": 0.0, "equity": 0.0}

    sign = +1 if str(side).upper() == "BUY" else -1
    asset_class = (asset_class or "").lower()
    sym_norm = symbol.replace("/", "").replace("_", "").upper()

    # ── FOREX ────────────────────────────────────────────────────────
    if asset_class == "forex" and len(sym_norm) == 6 and sym_norm.isalpha():
        base, quote = sym_norm[:3], sym_norm[3:]
        usd = 0.0
        if base == "USD":
            usd = +1.0 * sign  # BUY USD/JPY = long USD
        elif quote == "USD":
            usd = -1.0 * sign  # BUY EUR/USD = long EUR ⇒ short USD
        return {"usd": usd, "equity": 0.0}

    # ── STOCK / ETF / INDEX / CFD on equities ───────────────────────
    if asset_class in ("stock", "etf", "index"):
        return {"usd": 0.0, "equity": +1.0 * sign}

    # ── COMMODITIES (futures or spot) ───────────────────────────────
    if asset_class == "commodity":
        if sym_norm in _USD_SHORT_COMMODITIES or sym_norm.startswith("XAU") \
                or sym_norm.startswith("XAG"):
            # Precious metals → USD-short proxy.
            return {"usd": -1.0 * sign, "equity": 0.0}
        # Industrial / energy commodities — moderate equity-beta proxy.
        return {"usd": 0.0, "equity": +0.5 * sign}

    # ── CRYPTO ──────────────────────────────────────────────────────
    if asset_class == "crypto":
        # Strip USDT/USD/USDC suffix to get the base coin.
        base = sym_norm
        for suffix in ("USDT", "USDC", "USD", "BUSD"):
            if base.endswith(suffix) and len(base) > len(suffix):
                base = base[:-len(suffix)]
                break
        if base in _EQUITY_LIKE_CRYPTO or len(base) <= 5:
            return {"usd": -1.0 * sign, "equity": +1.0 * sign}
        return {"usd": -0.5 * sign, "equity": +0.5 * sign}

    # ── OPTIONS — direction follows the right (call/put) × side ─────
    # Long call (BUY C) = +equity on underlying; long put (BUY P) = -equity.
    # We don't have right info from (asset_class, symbol, side) alone — the
    # caller passes a `right` keyword for options below.
    if asset_class == "options":
        # Default: treat like equity-long without more info.
        return {"usd": 0.0, "equity": +1.0 * sign}

    # ── CFDs — depends on the underlying. Best-effort: index-like by default.
    if asset_class == "cfd":
        return {"usd": 0.0, "equity": +1.0 * sign}

    return {"usd": 0.0, "equity": 0.0}


def classify_option_position(side: str, right: str) -> dict:
    """Options: long call = +equity; long put = -equity. Short either is
    out of scope per Phase-14 (long premium only)."""
    sign = +1 if str(side).upper() == "BUY" else -1
    if str(right).upper() == "C":
        return {"usd": 0.0, "equity": +1.0 * sign}
    if str(right).upper() == "P":
        return {"usd": 0.0, "equity": -1.0 * sign}
    return {"usd": 0.0, "equity": 0.0}


# ── Phase 24 — richer classification ────────────────────────────────────

def classify_currencies(asset_class: str, symbol: str, side: str) -> dict:
    """Per-currency contributions for forex. {} for non-forex.

    BUY EURUSD → {EUR: +1, USD: -1}
    SELL EURUSD → {EUR: -1, USD: +1}
    BUY EURGBP → {EUR: +1, GBP: -1}  (cross — Phase-15 missed this entirely)
    """
    if (asset_class or "").lower() != "forex":
        return {}
    sign = +1 if str(side).upper() == "BUY" else -1
    s = symbol.replace("/", "").replace("_", "").upper()
    if len(s) != 6 or not s.isalpha():
        return {}
    base, quote = s[:3], s[3:]
    if base not in KNOWN_CURRENCIES or quote not in KNOWN_CURRENCIES:
        return {}
    return {base: +1.0 * sign, quote: -1.0 * sign}


def classify_sector(asset_class: str, symbol: str) -> str:
    """Sector concentration — only for stocks/options. Reads
    `Instrument.sector` field. Empty string when unknown or N/A.
    """
    if (asset_class or "").lower() not in ("stock", "etf", "options"):
        return ""
    try:
        from instruments.models import Instrument
        inst = Instrument.objects.filter(symbol=symbol).only("sector").first()
        if inst is None:
            return ""
        return (inst.sector or "").strip().lower()
    except Exception:
        return ""


def classify_vol_long(asset_class: str, side: str) -> float:
    """Vega-long contribution. Long premium options (any side, any right)
    are vega-positive — buying premium means betting volatility expands.

    Out-of-scope (selling premium = vega-negative) is not modelled per
    Phase 14 (long premium only).
    """
    if (asset_class or "").lower() != "options":
        return 0.0
    # We only ever BUY premium (Phase 14 scope), so the contribution is
    # always +1 regardless of call/put.
    if str(side).upper() == "BUY":
        return +1.0
    return 0.0


def classify_full(asset_class: str, symbol: str, side: str,
                   *, right: str = "") -> dict:
    """Phase-24 unified classifier. Returns a dict with three keys:
        themes:     legacy {usd, equity} + new {vol_long}
        currencies: per-currency contributions (forex only)
        sector:     normalised sector string (stocks/options/ETF only)

    Used internally by `gate_new_entry`. Backwards-compatible with the
    legacy `classify_position` / `classify_option_position` results — the
    `themes.usd` and `themes.equity` values match Phase 15 exactly.
    """
    if (asset_class or "").lower() == "options":
        legacy = classify_option_position(side, right)
    else:
        legacy = classify_position(asset_class, symbol, side)

    themes = {
        "usd": legacy.get("usd", 0.0),
        "equity": legacy.get("equity", 0.0),
        "vol_long": classify_vol_long(asset_class, side),
    }
    return {
        "themes": themes,
        "currencies": classify_currencies(asset_class, symbol, side),
        "sector": classify_sector(asset_class, symbol),
    }


# ── Exposure aggregation ───────────────────────────────────────────────────

def trade_size_weight(trade) -> float:
    """Phase-25 position-size weight relative to the config's default.

    A trade sized at exactly `capital × position_size_pct%` returns 1.0.
    A 2x-sized trade returns 2.0; half-sized returns 0.5. Clamped to
    `[0.1, 5.0]` so a single rogue trade can't dominate the gate.

    Returns 1.0 (neutral) when config or sizing data is missing/invalid —
    safer to under-weight than to crash the gate.
    """
    try:
        cfg = trade.config
        if cfg is None:
            return 1.0
        capital = float(cfg.capital or 0)
        pct = float(cfg.position_size_pct or 0) / 100.0
        default_notional = capital * pct
        if default_notional <= 0:
            return 1.0
        qty = float(getattr(trade, "qty", 0) or 0)
        entry = float(getattr(trade, "entry_price", 0) or 0)
        notional = qty * entry
        if notional <= 0:
            return 1.0
        weight = notional / default_notional
        return max(0.1, min(5.0, weight))
    except Exception:
        return 1.0


def _user_size_weighted(user) -> bool:
    try:
        return bool(getattr(user.trader_profile,
                              "size_weighted_orchestrator", False))
    except Exception:
        return False


def current_exposures(user) -> dict:
    """Phase-24 multi-dimensional exposure aggregator (Phase-25 size-weighted).

    Returns:
        {
          "themes":     {usd, equity, vol_long},
          "currencies": {EUR: ..., GBP: ..., ...},
          "sectors":    {tech: count, finance: count, ...},
        }

    Sector counts are **always integer counts** (not size-weighted) — sector
    concentration is a count concept, not a notional concept.

    Theme + currency contributions are scaled by `trade_size_weight(trade)`
    iff the user has `size_weighted_orchestrator=True`; otherwise each
    open position contributes ±1 (Phase 15-24 behaviour preserved).

    `current_theme_exposure(user)` (Phase 15) returns just `{usd, equity}`.
    """
    out = {
        "themes": {"usd": 0.0, "equity": 0.0, "vol_long": 0.0},
        "currencies": {},
        "sectors": {},
    }
    weighted = _user_size_weighted(user)

    def _accum(asset_class, symbol, side, right="", weight=1.0):
        c = classify_full(asset_class, symbol, side, right=right)
        for k, v in c["themes"].items():
            out["themes"][k] = out["themes"].get(k, 0.0) + v * weight
        for ccy, v in c["currencies"].items():
            out["currencies"][ccy] = out["currencies"].get(ccy, 0.0) + v * weight
        sec = c.get("sector") or ""
        if sec:
            # Sector is always count-based, not weighted.
            out["sectors"][sec] = out["sectors"].get(sec, 0) + 1

    # AssetBotTrade
    try:
        from .models import AssetBotTrade
        qs = AssetBotTrade.objects.filter(
            config__user=user, status__in=("OPEN", "CLOSE_PENDING")
        ).select_related("config")
        for t in qs:
            right = (t.metadata or {}).get("right", "") if t.asset_class == "options" else ""
            w = trade_size_weight(t) if weighted else 1.0
            _accum(t.asset_class, t.symbol, t.side, right=right, weight=w)
    except Exception as e:
        logger.warning("orchestrator: AssetBotTrade aggregation failed: %s", e)

    # Legacy crypto BotTrade
    try:
        from .models import BotTrade
        qs = BotTrade.objects.filter(
            config__user=user, exit_price__isnull=True
        ).select_related("config")
        for t in qs:
            w = trade_size_weight(t) if weighted else 1.0
            _accum("crypto", t.symbol, t.side, weight=w)
    except Exception as e:
        logger.warning("orchestrator: BotTrade aggregation failed: %s", e)

    return out


def current_theme_exposure(user) -> dict:
    """Sum theme contributions across the user's open positions:
      - AssetBotTrade rows status='OPEN'
      - BotTrade rows (legacy crypto bot) where exit_price is null

    Returns {'usd': float, 'equity': float}.
    """
    totals = {"usd": 0.0, "equity": 0.0}

    # ── AssetBotTrade ──────────────────────────────────────────────
    try:
        from .models import AssetBotTrade
        for t in AssetBotTrade.objects.filter(
                config__user=user, status__in=("OPEN", "CLOSE_PENDING")
        ).only("asset_class", "symbol", "side", "metadata"):
            if t.asset_class == "options":
                meta = t.metadata or {}
                contrib = classify_option_position(t.side, meta.get("right", ""))
            else:
                contrib = classify_position(t.asset_class, t.symbol, t.side)
            totals["usd"] += contrib["usd"]
            totals["equity"] += contrib["equity"]
    except Exception as e:
        logger.warning("orchestrator: AssetBotTrade aggregation failed: %s", e)

    # ── Legacy crypto BotTrade ─────────────────────────────────────
    try:
        from .models import BotTrade
        for t in BotTrade.objects.filter(
                config__user=user, exit_price__isnull=True
        ).only("symbol", "side"):
            contrib = classify_position("crypto", t.symbol, t.side)
            totals["usd"] += contrib["usd"]
            totals["equity"] += contrib["equity"]
    except Exception as e:
        logger.warning("orchestrator: BotTrade aggregation failed: %s", e)

    return totals


# ── Gate ───────────────────────────────────────────────────────────────────

def gate_new_entry(user, asset_class: str, symbol: str, side: str,
                   *, right: str = "") -> Tuple[bool, str]:
    """Return (allowed, reason).

    Rules:
      1. If the user has no `TraderProfile` or `cross_asset_orchestrator_enabled`
         is False → always allow (returns (True, 'orchestrator_off')).
      2. Compute current theme exposure + the new entry's contribution.
      3. If |exposure_after| > threshold for any theme → reject.
      4. Otherwise allow.

    All decisions for opted-in users are logged to OrchestratorEvent so the
    Sauron's-Eye dashboard can replay history.
    """
    try:
        from portfolio.trader_profile import TraderProfile
    except Exception:
        return True, "orchestrator_unavailable"

    profile = TraderProfile.objects.filter(user=user).first()
    if profile is None or not profile.cross_asset_orchestrator_enabled:
        return True, "orchestrator_off"

    new_contrib = classify_full(asset_class, symbol, side, right=right)
    cur = current_exposures(user)

    # ── Build "after" snapshot across all dimensions ───────────────
    after_themes = {
        k: cur["themes"].get(k, 0.0) + new_contrib["themes"].get(k, 0.0)
        for k in ("usd", "equity", "vol_long")
    }
    after_currencies = dict(cur["currencies"])
    for ccy, v in new_contrib["currencies"].items():
        after_currencies[ccy] = after_currencies.get(ccy, 0.0) + v
    after_sectors = dict(cur["sectors"])
    new_sector = new_contrib.get("sector") or ""
    if new_sector:
        after_sectors[new_sector] = after_sectors.get(new_sector, 0) + 1

    caps = {
        "usd": float(profile.max_usd_theme_exposure or 0),
        "equity": float(profile.max_equity_theme_exposure or 0),
        "vol_long": float(getattr(profile, "max_vol_theme_exposure", 0) or 0),
        "currency": float(getattr(profile, "max_currency_exposure", 0) or 0),
        "sector": int(getattr(profile, "max_sector_exposure", 0) or 0),
    }

    # Phase-39 brain pressure squeeze — when the central synthesizer reports
    # high pressure for a theme, soft-tighten its cap proportionally. Caps
    # are only ever made *tighter* by the brain, never loosened. Fails-open
    # if brain is unreachable.
    brain_squeeze = {}
    try:
        from brain.context import brain_theme_pressure_multiplier
        for theme in ("usd", "equity", "vol_long"):
            mult = brain_theme_pressure_multiplier(theme)
            if mult < 1.0:
                brain_squeeze[theme] = mult
                caps[theme] = caps[theme] * mult
    except Exception:
        pass

    decision = "allow"
    reason = "orchestrator_pass"

    # ── Theme caps (USD / equity / vol_long) ───────────────────────
    for theme, after_val in after_themes.items():
        cap = caps.get(theme, 0)
        if cap <= 0:
            continue
        prev = cur["themes"].get(theme, 0.0)
        if abs(after_val) > cap and abs(after_val) > abs(prev):
            decision = "reject"
            reason = (
                f"orchestrator: {theme} theme cap "
                f"|{after_val:+.1f}| > {cap:.1f} "
                f"(was |{prev:+.1f}|, +{new_contrib['themes'].get(theme, 0):+.1f})"
            )
            break

    # ── Currency caps (per-currency, only when forex contributes) ─
    if decision == "allow" and caps["currency"] > 0 and new_contrib["currencies"]:
        for ccy, v in new_contrib["currencies"].items():
            if v == 0:
                continue
            after_val = after_currencies.get(ccy, 0.0)
            prev = cur["currencies"].get(ccy, 0.0)
            if abs(after_val) > caps["currency"] and abs(after_val) > abs(prev):
                decision = "reject"
                reason = (
                    f"orchestrator: {ccy} currency cap "
                    f"|{after_val:+.1f}| > {caps['currency']:.1f}"
                )
                break

    # ── Sector cap (only when a sector applies) ────────────────────
    if (decision == "allow" and caps["sector"] > 0 and new_sector
            and after_sectors[new_sector] > caps["sector"]):
        decision = "reject"
        reason = (
            f"orchestrator: {new_sector} sector cap "
            f"{after_sectors[new_sector]} > {caps['sector']}"
        )

    # Build flat-ish dicts for the audit log.
    cur_log = {**cur["themes"],
                **{f"ccy_{k}": v for k, v in cur["currencies"].items()},
                **{f"sec_{k}": v for k, v in cur["sectors"].items()}}
    after_log = {**after_themes,
                  **{f"ccy_{k}": v for k, v in after_currencies.items()},
                  **{f"sec_{k}": v for k, v in after_sectors.items()}}

    _log_decision(user, asset_class, symbol, side, right,
                  decision, reason, cur_log, after_log, caps)

    # Phase-20 — fire a notification on rejects so the user sees the gate
    # acting in real time, not just on the Eye dashboard.
    if decision == "reject":
        try:
            from .notifications import notify_orchestrator_reject
            notify_orchestrator_reject(user,
                asset_class=asset_class, symbol=symbol, side=side, reason=reason)
        except Exception as e:
            logger.warning("orchestrator: notification failed: %s", e)
        # Phase-28 — append the reject to the immutable audit log.
        try:
            from .audit import record_gate_reject
            record_gate_reject(
                user, asset_class=asset_class, symbol=symbol, side=side,
                right=right, reason=reason,
                exposure_before=cur_log, exposure_after=after_log, caps=caps,
            )
        except Exception as e:
            logger.warning("orchestrator: audit record failed: %s", e)

        # Phase-23 — push to the user's Eye WebSocket (no-op if WS not connected).
        try:
            from dashboard.consumers import push_eye_event
            push_eye_event(user, "gate_reject", {
                "asset_class": asset_class, "symbol": symbol,
                "side": side, "reason": reason,
            })
        except Exception as e:
            logger.warning("orchestrator: WS push failed: %s", e)

    return (decision == "allow"), reason


def _log_decision(user, asset_class, symbol, side, right,
                   decision, reason, exposure_before, exposure_after, caps):
    """Persist gate decision for audit + dashboard replay. All-rejects are
    logged; allows are logged at 1-in-N to avoid bloating the table."""
    try:
        from .orchestrator_models import OrchestratorEvent
        # Sample allows: keep ~10% of them so the timeline isn't sparse on
        # quiet days but doesn't explode on busy ones.
        if decision == "allow":
            import random
            if random.random() > 0.10:
                return
        OrchestratorEvent.objects.create(
            user=user, asset_class=asset_class or "", symbol=symbol or "",
            side=side or "", right=right or "",
            decision=decision, reason=reason[:300],
            exposure_before=exposure_before, exposure_after=exposure_after,
            caps=caps,
        )
    except Exception as e:
        logger.warning("orchestrator: event log failed: %s", e)
