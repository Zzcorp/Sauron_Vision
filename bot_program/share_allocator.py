"""The share allocator — what share of the account each live pool should take.

Every few hours (propose_share_plans, beat) this computes a TARGET
`account_share_pct` for every live follower config (capital_truth
.followers_of) from five inputs — graded evidence, regime fit,
opportunity density, news risk, and the horizon prior (the monthly
5-10 year view's asset-class tilt, ±10% at most; 2026-09-12) — under
per-config floor/ceiling, a max
change per day and a drawdown governor, and writes it as a SharePlan in
state PROPOSED. That is a SHADOW: nothing moves. A plan moves only when
an admin applies it — PIN on /shares/, --yes on `shares apply` — and
only in LIVE mode (component share_allocator_mode_live). Applying
writes extras["account_share_pct"] and calls tasks._follow_the_account,
so the sync's own arithmetic re-sizes the pools. This module never
writes cfg.capital, never does broker I/O, and never touches an
IBKRAccount column: the reading is the sync's, the pool size is the
sync's, the share is the only thing decided here (2026-09-12).

Each reader is wrapped: a reader that raises degrades to 1.0 with the
reason recorded on the plan, so a stopped scanner or an idle analyst
costs a factor, never a proposal. Every number that went into a target
is on the plan, and `grade_plans` scores it 24h later against what the
live book actually paid — positive when the plan leaned toward the
configs that then earned R.
"""
import logging
import math
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

# ── Tunables ─────────────────────────────────────────────────────────────
# Per-config bounds on the share, in percent of the account. Overridable
# per config through extras["share_floor_pct"] / ["share_ceiling_pct"].
# The floor keeps a measured-bad pool alive at a size that still grades
# — a pool at 0% produces no evidence and can never earn its way back.
DEFAULT_FLOOR_PCT = 2.0
# 60% because the 2026-09-10 deployment had ONE lane on the whole account
# and the operator's ask was to share it, not to let a hot week hand the
# account back to one bot.
DEFAULT_CEILING_PCT = 60.0
# Percentage points per config per rolling 24h, counting what applied
# plans already moved today: three applies of 10 points are not thirty.
MAX_CHANGE_PCT_PER_DAY = 10.0
# Hysteresis. A move below this is HELD — the target repeats the current
# share exactly — so the sync does not re-size every pool by 0.3% four
# times a day and the audit log stays readable.
MIN_DELTA_PCT = 1.0
# Half the distance per plan, as the rule meta-allocator does; the other
# half comes in the next plan if the evidence still says so.
SMOOTHING_ALPHA = 0.5
# The drawdown governor: full deployment until 5% under the 90-day
# high-water mark, then linear down to 40% deployment at 20% under, and
# never below 40% — the rest is cash by construction, not by a stop.
DD_KNEE = 0.05
DD_MAX = 0.20
DD_FLOOR = 0.4
# Applies per user per rolling 24h. A share is a slow variable; more than
# three re-sizings a day is an operator fighting the allocator.
MAX_APPLIES_PER_DAY = 3
# A proposal older than this describes a reading and a tape that are
# gone; it expires rather than waiting for a click on stale numbers.
PROPOSAL_TTL_HOURS = 8
# Evidence window and the graded fills needed before a lane counts.
EVIDENCE_DAYS = 90
MIN_EVIDENCE_N = 10
# The HORIZON prior (2026-09-12): the monthly 5-10 year synthesis
# (brain.horizon) tilts each asset class -2..+2 with a confidence. Each
# tilt point is 5%, scaled by confidence, so the factor runs 0.90..1.10
# — a weak prior by construction, never a vote that outweighs graded
# evidence. A view older than HORIZON_MAX_AGE_DAYS is history, not a
# prior, and costs a factor of 1.0 with the reason on the plan.
HORIZON_TILT_STEP = 0.05
HORIZON_MAX_AGE_DAYS = 45

LIVE_COMPONENT = "share_allocator_mode_live"
GRADED_OUTCOMES = ["hit_target", "stopped_out", "manual_close", "expired",
                   "time_stop"]

# ── Market state: DE-RISK FAST, RE-RISK SLOW (2026-09-12) ────────────────
# The 10-point cap and the half-way smoothing above are symmetric, so a
# 20% crash whose governor says 0.4 took three days to reach the pools —
# every day of which the pools were sized against money that was gone.
# The operator's ask: "today the cap is small, but in a strong rally or a
# big crash Sauron must be able to respond." Three modes follow:
#   shock      — de-risk only: down UNCAPPED and unsmoothed, up frozen,
#                nothing redistributed (what a pool releases is cash);
#   expansion  — at the high-water mark with measured positive evidence,
#                the upward allowance is EXPANSION_CAP_PCT_PER_DAY;
#   normal     — the rule exactly as it was.
# Equity fell this fraction or more from the highest reading of the last
# 24 h → shock. 3% because the governor's own knee is 5% off the 90-day
# high: a shock is the day the road turns, not the drawdown afterwards.
SHOCK_DROP_PCT = 0.03
# Brain regimes that are a shock on their own, at this confidence or
# more. 'unknown' never counts — an idle brain is not a crash.
SHOCK_REGIMES = ("risk_off", "blow_off")
SHOCK_REGIME_MIN_CONF = 0.65
# A detected shock keeps re-risking frozen for this long after the last
# shock plan: a bounce the morning after a 4% day is not a rally, and a
# plan that re-risked into it would buy the shares it sold yesterday.
SHOCK_HOLD_HOURS = 24
# Upward allowance in expansion, per config per rolling 24h (down stays
# MAX_CHANGE_PCT_PER_DAY): a proven rally expands faster than a quiet
# week, still never in one step.
EXPANSION_CAP_PCT_PER_DAY = 20.0
# The sync trigger (tasks.sync_broker_account) proposes at most once per
# this many seconds on a shock, so a 15-minute beat on a bad day does not
# write four shock plans an hour that supersede one another.
SHOCK_TRIGGER_COOLDOWN_S = 3600
# The opt-in that lets a pure de-risk shock plan apply itself in LIVE mode.
AUTO_DERISK_COMPONENT = "share_allocator_auto_derisk"
MODE_NORMAL, MODE_SHOCK, MODE_EXPANSION = "normal", "shock", "expansion"
# The reason string the hold writes on a plan; `_hold_only` reads it
# back so a plan that was a shock ONLY because of the hold does not
# re-arm the hold (see market_state).
HOLD_REASON_PREFIX = "shock hold until"


class ShareAllocatorError(Exception):
    pass


def is_live_mode() -> bool:
    """True iff an admin may apply — otherwise every plan is a shadow."""
    from core.platform_control import is_component_enabled
    return is_component_enabled(LIVE_COMPONENT)


def is_auto_derisk_enabled() -> bool:
    """True iff a pure de-risk shock plan may apply itself (LIVE mode is
    checked separately — both switches must be on)."""
    from core.platform_control import is_component_enabled
    return is_component_enabled(AUTO_DERISK_COMPONENT)


# ── Market state readers (pure DB reads; never raise to the caller) ──────

def _hold_only(reasons) -> bool:
    """True iff `reasons` is non-empty and every entry is the hold itself
    — a shock plan proposed inside the hold with no fresh detection of
    its own. An empty list counts as fresh: a real shock plan always
    records its trigger, so a plan with none is a hand-made anchor."""
    rs = [str(r) for r in (reasons or [])]
    return bool(rs) and all(r.startswith(HOLD_REASON_PREFIX) for r in rs)


def drop_24h(user, *, now=None):
    """The fraction the current reading sits under the highest reading of
    the last 24 h in the current currency — 0.042 is 4.2% under — or None
    when no history row landed in the window. The current reading is part
    of the max, so the answer is never negative; a history in another
    currency is an exchange rate, not a drop, and does not count."""
    from bot_program.capital_truth import account_equity, broker_backed
    from bot_program.equity_models import BrokerEquityReading
    now = now or timezone.now()
    acct = broker_backed(user)
    reading = account_equity(user)
    if acct is None or reading is None:
        return None
    current = float(reading["value"])
    rows = BrokerEquityReading.objects.filter(
        account=acct, currency=reading["currency"] or "",
        at__gte=now - timedelta(hours=24)).values_list("value", flat=True)
    values = [float(v) for v in rows]
    if not values:
        return None
    top = max(max(values), current)
    if top <= 0:
        return None
    return max(0.0, (top - current) / top)


def shock_detected(user, *, now=None) -> bool:
    """The cheap half of `market_state`, for the sync trigger: equity fell
    SHOCK_DROP_PCT or more in 24 h, or the drawdown is past the governor's
    knee — from the rows the sync just wrote, no brain context. False on
    any reader failure: a trigger that cannot read must not fire."""
    from bot_program.capital_truth import equity_drawdown
    try:
        drop = drop_24h(user, now=now)
        if drop is not None and drop >= SHOCK_DROP_PCT:
            return True
        dd = equity_drawdown(user)
        return bool(dd and float(dd["drawdown_pct"] or 0.0) > DD_KNEE)
    except Exception as e:  # noqa: BLE001 — unreadable is not a shock
        logger.warning("[shares] shock detection failed: %s", e)
        return False


def market_state(user, ctx, *, evidence=None, now=None) -> dict:
    """{mode, reasons, drop_24h_pct, drawdown_pct, at_hwm, regime}.

    shock when the drawdown is past DD_KNEE, or equity fell SHOCK_DROP_PCT
    in 24 h, or the brain's regime is one of SHOCK_REGIMES at
    SHOCK_REGIME_MIN_CONF or more, or a shock plan was proposed within
    SHOCK_HOLD_HOURS (the hold). expansion when no shock, the current
    reading IS the high-water mark, and at least one follower's evidence
    is measured with avg_r > 0 over MIN_EVIDENCE_N fills or more —
    `evidence` is {label: evidence dict} as the proposer already read it;
    this function re-queries nothing. Else normal. Never raises: a reader
    that fails answers normal with the reason, because a market state
    nobody can read must not freeze or expand anything.
    """
    from bot_program.capital_truth import equity_drawdown
    from bot_program.share_models import SharePlan
    now = now or timezone.now()
    out = {"mode": MODE_NORMAL, "reasons": [], "drop_24h_pct": None,
           "drawdown_pct": None, "at_hwm": False, "regime": None}
    try:
        dd = equity_drawdown(user)
        dd_pct = float(dd["drawdown_pct"] or 0.0) if dd else None
        out["drawdown_pct"] = dd_pct
        out["at_hwm"] = dd_pct is not None and dd_pct <= 1e-12
        drop = drop_24h(user, now=now)
        out["drop_24h_pct"] = drop
        label = str((ctx or {}).get("regime_label") or "unknown")
        conf = float((ctx or {}).get("regime_confidence") or 0.0)
        out["regime"] = label if ctx else None

        reasons = []
        if dd_pct is not None and dd_pct > DD_KNEE:
            reasons.append(f"drawdown {dd_pct * 100:.1f}% past the "
                           f"{DD_KNEE * 100:g}% knee")
        if drop is not None and drop >= SHOCK_DROP_PCT:
            reasons.append(f"equity −{drop * 100:.1f}% in 24h")
        if label != "unknown" and label in SHOCK_REGIMES \
                and conf >= SHOCK_REGIME_MIN_CONF:
            reasons.append(f"regime {label} {conf:.2f}")
        # The hold is anchored on the last shock plan that carried a
        # FRESH detection (drop, drawdown, regime). A plan proposed inside
        # the hold on the hold alone is a shock plan too; if it restarted
        # the clock, the 4-hourly beat would re-arm the hold every 4 h
        # and the account would never re-risk again (2026-09-12).
        last_fresh = None
        for p in (SharePlan.objects
                  .filter(user=user, mode=MODE_SHOCK,
                          proposed_at__gte=now - timedelta(hours=SHOCK_HOLD_HOURS))
                  .order_by("-proposed_at")):
            if not _hold_only(p.mode_reasons):
                last_fresh = p
                break
        if last_fresh is not None:
            until = last_fresh.proposed_at + timedelta(hours=SHOCK_HOLD_HOURS)
            reasons.append(f"{HOLD_REASON_PREFIX} {until:%m-%d %H:%M} "
                           f"(plan #{last_fresh.pk})")
        if reasons:
            out.update({"mode": MODE_SHOCK, "reasons": reasons})
            return out

        proven = []
        for label_, ev in (evidence or {}).items():
            try:
                if ev.get("measured") and float(ev.get("avg_r") or 0.0) > 0 \
                        and int(ev.get("n") or 0) >= MIN_EVIDENCE_N:
                    proven.append(f"{label_}: avg_r {float(ev['avg_r']):+.2f} "
                                  f"over {int(ev['n'])} fills")
            except (TypeError, ValueError):
                continue
        if out["at_hwm"] and proven:
            out.update({"mode": MODE_EXPANSION,
                        "reasons": ["at the high-water mark"] + proven})
            return out
        why = []
        if dd_pct is None:
            why.append("no reading")
        elif not out["at_hwm"]:
            why.append(f"{dd_pct * 100:.1f}% under the high-water mark")
        else:
            why.append("at the high-water mark, no measured positive lane")
        out["reasons"] = why
        return out
    except Exception as e:  # noqa: BLE001 — unreadable is normal, with the reason
        logger.warning("[shares] market state unreadable: %s", e)
        out.update({"mode": MODE_NORMAL,
                    "reasons": [f"market state unreadable: {e}"]})
        return out


# ── Pieces of the arithmetic (pure; the tests pin each one) ──────────────

def governor_for(drawdown_pct) -> float:
    """1.0 down to DD_FLOOR as the drawdown runs from DD_KNEE to DD_MAX."""
    dd = float(drawdown_pct or 0.0)
    if dd <= DD_KNEE:
        return 1.0
    if dd >= DD_MAX:
        return DD_FLOOR
    return 1.0 - (dd - DD_KNEE) / (DD_MAX - DD_KNEE) * (1.0 - DD_FLOOR)


def _is_manual_lane(cfg) -> bool:
    """The config TAKE TRADE books hand-taken positions against: the
    reserved name and no symbols (core.context_processors._is_manual_config
    is the platform's definition; mirrored here so this module stays free
    of the dashboard)."""
    try:
        from bot_program.manual_trade import MANUAL_CONFIG_NAME
    except Exception:  # noqa: BLE001
        MANUAL_CONFIG_NAME = "manual"
    return (getattr(cfg, "name", None) == MANUAL_CONFIG_NAME
            and not getattr(cfg, "symbols", None))


def bounds_for(cfg) -> tuple:
    """(floor, ceiling, reason) — the config's own bounds when they are
    sane (finite, 0 < floor <= ceiling <= 100), else the defaults.

    The manual lane has NO default ceiling. The first plan on the live
    account (2026-09-11 22:52, #1) proposed moving the operator's own
    pool 80% -> 70% and the ETF bot 20% -> 30% with every evidence lane
    unmeasured: the 60% ceiling, a concentration guard written for BOTS,
    was binding on the hand-taken pool and the water-fill handed the
    excess to the only other follower. A default constant was moving ten
    points of a 2,000 EUR account on no information. The operator's pool
    is the operator's; a bot that earns its way up still stops at 60%.
    An explicit extras["share_ceiling_pct"] on the manual lane is honoured.
    """
    ex = getattr(cfg, "extras", None) or {}
    raw_lo, raw_hi = ex.get("share_floor_pct"), ex.get("share_ceiling_pct")
    lo, hi = DEFAULT_FLOOR_PCT, DEFAULT_CEILING_PCT
    if _is_manual_lane(cfg):
        hi = 100.0
    try:
        if raw_lo not in (None, ""):
            lo = float(raw_lo)
        if raw_hi not in (None, ""):
            hi = float(raw_hi)
    except (TypeError, ValueError):
        return DEFAULT_FLOOR_PCT, DEFAULT_CEILING_PCT, "bounds not numeric — defaults"
    if not (math.isfinite(lo) and math.isfinite(hi)) \
            or not (0.0 < lo <= hi <= 100.0):
        return (DEFAULT_FLOOR_PCT, DEFAULT_CEILING_PCT,
                f"bounds {raw_lo}/{raw_hi} out of range — defaults")
    return lo, hi, ""


def water_fill(raw: dict, bounds: dict, total: float) -> dict:
    """Scale `raw` to sum to `total`, then hold every key inside its own
    [floor, ceiling] by water-filling: a key that overflows is fixed at
    its ceiling, one that underflows at its floor, and the rest of the
    mass is re-shared proportionally among the free keys. Like
    signals.meta_allocator._apply_caps, but with per-key bounds. When
    the ceilings together cannot hold `total` the remainder is left
    undeployed (cash) — never forced above a ceiling.

    Solved as one scale `s` with Σ clamp(s·raw_k, floor_k, ceiling_k) ==
    total, not by fixing the overflowing and the underflowing keys in
    the same pass. That pass lost mass: raw 90/0.5/0.5 under floors of 2
    and ceilings of 60 came back 60/2/2 — 36% of the account parked in
    cash that two pools had room for — and with a floor above what the
    ceilings left it came back OVER-deployed (55 + 50 = 105% of one
    account), which is the direction every limit is looser than it
    reads (2026-09-12). The sum is monotone in `s`, so the scale is
    found by bisection and the last gap closed exactly among the keys
    that sit strictly inside their bounds.
    """
    keys = list(raw)
    if not keys:
        return {}
    lo = {k: float(bounds[k][0]) for k in keys}
    hi = {k: float(bounds[k][1]) for k in keys}
    w = {k: max(0.0, float(raw[k])) for k in keys}
    if sum(w.values()) <= 0:
        # Nothing has weight: share evenly, still inside the bounds.
        w = {k: 1.0 for k in keys}

    def at(s):
        return {k: min(hi[k], max(lo[k], s * w[k])) for k in keys}

    # At s_hi every weighted key sits at its ceiling (a weightless key
    # stays at its floor whatever s is). If even that cannot hold
    # `total`, the rest is cash by construction.
    s_hi = max(hi[k] / w[k] for k in keys if w[k] > 0)
    if sum(at(s_hi).values()) <= total + 1e-9:
        return at(s_hi)
    s_lo = 0.0
    for _ in range(100):
        mid = (s_lo + s_hi) / 2.0
        if sum(at(mid).values()) < total:
            s_lo = mid
        else:
            s_hi = mid
    alloc = at(s_hi)
    free = [k for k in keys if lo[k] + 1e-9 < alloc[k] < hi[k] - 1e-9]
    if not free:
        return alloc
    free_mass = total - sum(v for k, v in alloc.items() if k not in free)
    free_w = sum(w[k] for k in free)
    if free_mass < 0 or free_w <= 0:
        return alloc
    for k in free:
        alloc[k] = free_mass * w[k] / free_w
    return alloc


def opportunity_factor(share, measured) -> float:
    """0.8 at no density, 1.2 at a quarter of the universe or more."""
    if not measured:
        return 1.0
    return 0.8 + 0.4 * min(1.0, float(share or 0.0) / 0.25)


def news_factor(slot, *, min_articles=3) -> float:
    """Tighten-only: 1.0 when blind, else down for a sour tape and for a
    high-impact event ahead, floored at 0.6."""
    if not slot or slot.get("blind"):
        return 1.0
    f = 1.0
    avg = slot.get("avg_sent")
    if avg is not None and int(slot.get("n_graded") or 0) >= min_articles:
        f -= 0.3 * max(0.0, -float(avg))
    if int(slot.get("events_24h") or 0) > 0:
        f -= 0.1
    return max(0.6, f)


_THEME_BY_CLASS = {"stock": "equity", "cfd": "equity", "crypto": "equity",
                   "forex": "usd"}
_RISK_OFF_CLASSES = ("stock", "crypto", "cfd")
_TRUST_FACTOR = {"high": 1.0, "unknown": 1.0, "medium": 0.6, "low": 0.2}


def regime_for(cfg, ctx) -> dict:
    """{regime, factor, reason, theme, theme_factor, riskoff} from the
    brain context; neutral when there is none."""
    if not ctx:
        return {"regime": "none", "factor": 1.0, "theme": None,
                "theme_factor": 1.0, "riskoff": 1.0,
                "reason": "no fresh brain context — neutral"}
    from brain.context import brain_theme_pressure_multiplier, brain_trust_band
    ac = getattr(cfg, "asset_class", "") or ""
    theme = _THEME_BY_CLASS.get(ac)
    theme_f = 1.0
    if theme:
        theme_f = float(brain_theme_pressure_multiplier(theme))
    label = str(ctx.get("regime_label") or "unknown")
    conf = float(ctx.get("regime_confidence") or 0.0)
    riskoff = 1.0
    if label == "risk_off" and conf >= 0.65 and ac in _RISK_OFF_CLASSES:
        band = brain_trust_band(ctx.get("trust_score"))
        riskoff = 1.0 - 0.2 * _TRUST_FACTOR.get(band, 1.0)
    factor = theme_f * riskoff
    reason = f"regime {label} ({conf:.2f})"
    if theme:
        reason += f", theme {theme} ×{theme_f:.2f}"
    if riskoff < 1.0:
        reason += f", risk-off ×{riskoff:.2f}"
    return {"regime": label, "factor": factor, "theme": theme,
            "theme_factor": theme_f, "riskoff": riskoff, "reason": reason}


def _neutral_horizon(reason: str, label: str, *, age_days=None) -> dict:
    return {"factor": 1.0, "tilt": None, "confidence": None,
            "age_days": age_days, "label": label, "reason": reason}


def horizon_for(cfg, view, *, now=None) -> dict:
    """{factor, tilt, confidence, age_days, label, reason} from the latest
    HorizonView for the config's asset class.

    factor = 1 + HORIZON_TILT_STEP × tilt × confidence, so ±2 at full
    confidence is ±10% and nothing more. No view, a stale view, or a
    class the view did not tilt → 1.0 with the reason: a missing prior
    must never read as a bearish one. `label` is the short form the why
    sentence prints ('stock tilt +1, conf 0.8').
    """
    if view is None:
        return _neutral_horizon("no horizon view — neutral", "no view")
    now = now or timezone.now()
    try:
        age_days = (now - view.created_at).total_seconds() / 86400.0
    except (TypeError, AttributeError):
        age_days = None
    if age_days is not None and age_days > HORIZON_MAX_AGE_DAYS:
        return _neutral_horizon(
            f"horizon view #{getattr(view, 'pk', '?')} is {age_days:.0f}d old "
            f"(max {HORIZON_MAX_AGE_DAYS}) — neutral",
            f"stale {age_days:.0f}d", age_days=age_days)
    ac = getattr(cfg, "asset_class", "") or ""
    tilts = getattr(view, "asset_class_tilts", None) or {}
    slot = tilts.get(ac) if isinstance(tilts, dict) else None
    if not isinstance(slot, dict):
        return _neutral_horizon(
            f"horizon view #{getattr(view, 'pk', '?')} has no {ac} tilt — neutral",
            f"no {ac} tilt", age_days=age_days)
    try:
        tilt = int(round(float(slot.get("tilt") or 0)))
        conf = float(slot.get("confidence") or 0.0)
    except (TypeError, ValueError):
        return _neutral_horizon(
            f"horizon view #{getattr(view, 'pk', '?')}: {ac} tilt not numeric — neutral",
            f"bad {ac} tilt", age_days=age_days)
    # Clamped again here, not only at parse time: a row edited by hand or
    # written by an older version must still be a ±10% prior at most.
    tilt = max(-2, min(2, tilt))
    conf = max(0.0, min(1.0, conf))
    factor = 1.0 + HORIZON_TILT_STEP * tilt * conf
    label = f"{ac} tilt {tilt:+d}, conf {conf:.1f}"
    return {"factor": factor, "tilt": tilt, "confidence": conf,
            "age_days": age_days, "label": label,
            "reason": (f"horizon view #{getattr(view, 'pk', '?')} "
                       f"({age_days:.0f}d old): {label}"
                       + (f" — {slot.get('why')}" if slot.get("why") else ""))}


def _classes_of(cfg) -> dict:
    """{asset_class: symbol_count} for the config's symbols, through the
    Instrument table — a 'stock' config holding GLDM holds an 'etf'."""
    from instruments.models import Instrument
    symbols = [str(s) for s in (getattr(cfg, "symbols", None) or [])]
    own = getattr(cfg, "asset_class", "") or ""
    if not symbols:
        return {own: 1}
    known = dict(Instrument.objects.filter(symbol__in=symbols)
                 .values_list("symbol", "asset_class"))
    out: dict = {}
    for s in symbols:
        ac = known.get(s) or own
        out[ac] = out.get(ac, 0) + 1
    return out


def _applied_today(user, now) -> dict:
    """{pk: points already moved by APPLIED plans in the last 24h}."""
    from bot_program.share_models import SharePlan
    moved: dict = {}
    for p in SharePlan.objects.filter(
            user=user, state=SharePlan.STATE_APPLIED,
            applied_at__gte=now - timedelta(hours=24)):
        prev, cur = p.previous_shares or {}, p.current_shares or {}
        for k, target in (p.targets or {}).items():
            before = prev.get(k)
            if before is None:
                before = cur.get(k)
            try:
                moved[k] = moved.get(k, 0.0) + abs(float(target)
                                                  - float(before or 0.0))
            except (TypeError, ValueError):
                continue
    return moved


def _shave_to_100(targets: dict, bounds: dict, held: set) -> dict:
    """Cut the targets until they sum to 100 or less; {pk: points cut}.

    Rounding pushes a full account a few hundredths past 100, and a
    follower lifted to its floor pushes it further. The cut comes off
    the largest target that MOVED first — a held target repeats its
    current share exactly and stays exact — and off a held one only when
    nothing else has room. Never below a floor, never a sub-cent cut
    that rounding would eat (a 0.004 shave off 55.00 stayed 55.00 and
    looped). What cannot be shaved the share rule refuses next, with
    its reason. Mutates `targets`.
    """
    from bot_program.capital_truth import SHARE_SLACK
    cuts: dict = {}
    for pool in (set(targets) - set(held), set(held)):
        while sum(targets.values()) - 100.0 > SHARE_SLACK:
            over = sum(targets.values()) - 100.0
            room = {pk: targets[pk] - bounds[pk][0] for pk in pool
                    if targets[pk] - bounds[pk][0] >= 0.01 - 1e-9}
            if not room:
                break
            big = max(room, key=targets.get)
            new = round(targets[big] - min(over, room[big]), 2)
            if new >= targets[big]:
                new = round(targets[big] - 0.01, 2)
            cuts[big] = cuts.get(big, 0.0) + (targets[big] - new)
            targets[big] = new
    return cuts


def _why(ev, rg, opp, nw, raw, capped, smoothed, target, held, *,
         mode=MODE_NORMAL, allowance_up=None, allowance_down=None,
         hz=None) -> str:
    ev_bits = ev.get("lane", "none")
    if ev.get("measured"):
        ev_bits += (f", n={ev.get('n')}, wr {float(ev.get('win_rate') or 0):.2f}, "
                    f"avg_r {float(ev.get('avg_r') or 0):+.2f}")
    else:
        ev_bits += ", unmeasured"
    opp_bits = "measured" if opp.get("measured") else "unmeasured"
    nw_bits = "blind" if nw.get("blind") else "measured"
    # The fifth factor, named only on plans that carried one (older
    # plans' inputs have no "horizon" and their sentence reads as before).
    hz_bits = ""
    if isinstance(hz, dict) and hz.get("factor") is not None:
        hz_bits = (f" × horizon {float(hz['factor']):.2f} "
                   f"({hz.get('label') or 'no view'})")
    s = (f"evidence {ev['score']:.2f} ({ev_bits}) × regime {rg['factor']:.2f} "
         f"× opportunity {opp['factor']:.2f} ({opp_bits}) × news "
         f"{nw['factor']:.2f} ({nw_bits}){hz_bits} → {raw:.1f}% capped {capped:.1f}% "
         f"smoothed {smoothed:.1f}% (max change {MAX_CHANGE_PCT_PER_DAY:g}/day)")
    if held:
        s += f" — held at {target:.1f}% (move under {MIN_DELTA_PCT:g} pt)"
    # The mode tail is appended only off the normal path so a normal
    # plan's sentence reads exactly as it did before the modes existed.
    if mode == MODE_SHOCK:
        s += (" — SHOCK: de-risk only (no smoothing, down uncapped, "
              "up frozen)")
    elif mode == MODE_EXPANSION:
        s += (f" — EXPANSION: up to {float(allowance_up or 0):g} pt up / "
              f"{float(allowance_down or 0):g} pt down today")
    return s


# ── Propose ──────────────────────────────────────────────────────────────

def propose_share_plan(user, *, now=None):
    """A PROPOSED SharePlan for `user`'s followers, or None with the reason
    logged (no fresh reading, no followers, floors that do not fit,
    shares the rule refuses)."""
    plan, _reason = propose_share_plan_with_reason(user, now=now)
    return plan


def propose_share_plan_with_reason(user, *, now=None):
    """(plan, reason) — `reason` is '' when a plan was written."""
    from bot_program.capital_truth import (TRACKING_FRESH_SECONDS,
                                           account_equity, account_share_pct,
                                           allocate_shares, equity_drawdown,
                                           followers_of)
    from bot_program.share_models import SharePlan

    now = now or timezone.now()
    name = getattr(user, "username", str(user))

    # a. the reading, and it must be fresh
    reading = account_equity(user)
    if reading is None or reading["age_seconds"] > TRACKING_FRESH_SECONDS:
        age = "none" if reading is None else f"{reading['age_seconds']}s"
        reason = f"no fresh reading (age {age})"
        logger.info("[shares] user %s: %s — nothing proposed", name, reason)
        return None, reason

    # b. the followers and their current shares
    followers = followers_of(user)
    if not followers:
        reason = "no live follower configs"
        logger.info("[shares] user %s: %s — nothing proposed", name, reason)
        return None, reason
    alloc_now = allocate_shares(followers)
    plan_now = alloc_now["plan"] if alloc_now["ok"] else {}
    current: dict = {}
    for cfg in followers:
        pct = account_share_pct(cfg)
        if pct is None and cfg.pk in plan_now:
            pct = float(plan_now[cfg.pk]) * 100.0
        current[cfg.pk] = pct

    # the drawdown governor
    dd = None
    try:
        dd = equity_drawdown(user)
    except Exception as e:  # noqa: BLE001 — a missing history is not a missing plan
        logger.warning("[shares] user %s: drawdown unreadable: %s", name, e)
    dd_pct = float(dd["drawdown_pct"]) if dd else 0.0
    governor = governor_for(dd_pct)
    hwm = float(dd["hwm"]) if dd else float(reading["value"])
    notes = []
    if dd is None or int(dd.get("n") or 0) == 0:
        notes.append("hwm from 1 reading")
    else:
        notes.append(f"hwm {hwm:,.2f} {dd['currency']} over {dd['n']} readings, "
                     f"drawdown {dd_pct * 100:.1f}%, governor {governor:.2f}")
    if not alloc_now["ok"]:
        notes.append(f"current shares do not fit: {alloc_now['reason']}")

    # shared readers, once per proposal
    ctx = None
    try:
        from brain.context import get_brain_context
        ctx = get_brain_context(max_age_minutes=90)
    except Exception as e:  # noqa: BLE001
        notes.append(f"brain context unreadable: {e}")
    density, density_err = {}, ""
    try:
        from signals.opportunity_density import opportunity_density
        density = opportunity_density(now=now)
    except Exception as e:  # noqa: BLE001
        density_err = f"opportunity reader failed: {e}"
    news, news_err = {}, ""
    try:
        from bot_program.news_risk import news_risk_by_class
        news = news_risk_by_class(now=now)
    except Exception as e:  # noqa: BLE001
        news_err = f"news reader failed: {e}"
    # The horizon view is read ONCE per proposal, never per config: one
    # row, one age, one set of tilts for every follower on the plan.
    horizon_view, horizon_err = None, ""
    try:
        from brain.horizon_models import latest_view
        horizon_view = latest_view(max_age_days=HORIZON_MAX_AGE_DAYS)
    except Exception as e:  # noqa: BLE001
        horizon_err = f"horizon reader failed: {e}"

    # c. per config: the five factors and the raw share
    inputs: dict = {}
    raw: dict = {}
    bounds: dict = {}
    evidence_by_name: dict = {}
    for cfg in followers:
        try:
            from bot_program.evidence import config_evidence
            ev = config_evidence(cfg, days=EVIDENCE_DAYS)
        except Exception as e:  # noqa: BLE001
            ev = {"lane": "none", "n": 0, "win_rate": None, "avg_r": None,
                  "r_sum": 0.0, "measured": False, "score": 1.0,
                  "reason": f"evidence reader failed: {e}"}
        evidence_by_name[cfg.name] = ev
        try:
            rg = regime_for(cfg, ctx)
        except Exception as e:  # noqa: BLE001
            rg = {"regime": "none", "factor": 1.0, "theme": None,
                  "theme_factor": 1.0, "riskoff": 1.0,
                  "reason": f"regime reader failed: {e}"}
        try:
            classes = _classes_of(cfg)
        except Exception as e:  # noqa: BLE001
            classes = {cfg.asset_class: 1}
            notes.append(f"{cfg.name}: instrument lookup failed: {e}")
        if density_err:
            opp = {"factor": 1.0, "measured": False, "classes": {},
                   "reason": density_err}
        else:
            total_syms = sum(classes.values()) or 1
            f_sum, measured_any, per_class = 0.0, False, {}
            for ac, n_sym in classes.items():
                slot = density.get(ac) or {"measured": False, "share": 0.0,
                                           "reason": "class not in the universe"}
                f = opportunity_factor(slot.get("share"), slot.get("measured"))
                measured_any = measured_any or bool(slot.get("measured"))
                per_class[ac] = {"share": slot.get("share"),
                                 "measured": bool(slot.get("measured")),
                                 "factor": f, "symbols": n_sym,
                                 "reason": slot.get("reason", "")}
                f_sum += f * n_sym
            opp = {"factor": f_sum / total_syms, "measured": measured_any,
                   "classes": per_class,
                   "reason": "; ".join(f"{ac}: {d['reason']}"
                                       for ac, d in per_class.items())}
        if news_err:
            nw = {"factor": 1.0, "blind": True, "classes": {},
                  "reason": news_err}
        else:
            per_class, f_min, blind_all = {}, 1.0, True
            for ac in classes:
                slot = news.get(ac) or {"blind": True,
                                        "reason": "class not graded"}
                f = news_factor(slot)
                blind_all = blind_all and bool(slot.get("blind"))
                per_class[ac] = {**slot, "factor": f}
                f_min = min(f_min, f)
            nw = {"factor": f_min, "blind": blind_all, "classes": per_class,
                  "reason": "; ".join(f"{ac}: {d.get('reason', '')}"
                                      for ac, d in per_class.items())}
        if horizon_err:
            hz = _neutral_horizon(horizon_err, "unreadable")
        else:
            try:
                hz = horizon_for(cfg, horizon_view, now=now)
            except Exception as e:  # noqa: BLE001
                hz = _neutral_horizon(f"horizon reader failed: {e}",
                                      "unreadable")
        cur = current.get(cfg.pk)
        raw[cfg.pk] = (float(cur or 0.0) * float(ev["score"]) * rg["factor"]
                       * opp["factor"] * nw["factor"] * hz["factor"])
        lo, hi, why_bounds = bounds_for(cfg)
        bounds[cfg.pk] = (lo, hi)
        if why_bounds:
            notes.append(f"{cfg.name}: {why_bounds}")
        inputs[str(cfg.pk)] = {
            "name": cfg.name, "asset_class": cfg.asset_class,
            "mode": cfg.mode, "current": cur, "floor": lo, "ceiling": hi,
            "evidence": ev, "regime": rg, "opportunity": opp, "news": nw,
            "horizon": hz,
        }

    # the market state — after the evidence is read (expansion needs it),
    # before the caps (shock and expansion change them)
    state = market_state(user, ctx, evidence=evidence_by_name, now=now)
    mode = state["mode"]
    if mode == MODE_SHOCK:
        notes.append("SHOCK: de-risk only — " + "; ".join(state["reasons"]))
    elif mode == MODE_EXPANSION:
        notes.append(f"EXPANSION: up to {EXPANSION_CAP_PCT_PER_DAY:g} pt/day "
                     f"up — " + "; ".join(state["reasons"]))

    # d. normalise to the deployable share of the account
    deployable = 100.0 * governor
    mass = sum(raw.values())
    if mass <= 0:
        raw = {k: deployable / len(raw) for k in raw}
    else:
        raw = {k: v * deployable / mass for k, v in raw.items()}

    # e. floors and ceilings by water-fill
    floors = sum(lo for lo, _hi in bounds.values())
    if floors > deployable + 1e-9:
        reason = (f"floors sum to {floors:.1f}% but only {deployable:.1f}% "
                  f"is deployable (governor {governor:.2f})")
        logger.info("[shares] user %s: %s — nothing proposed", name, reason)
        return None, reason
    capped = water_fill(raw, bounds, deployable)

    # f. smoothing, the per-day cap, hysteresis — by mode. NORMAL is the
    # rule exactly as it was: one symmetric allowance, half-way smoothing.
    # EXPANSION widens the UPWARD allowance only. SHOCK is de-risk only:
    # no smoothing and no redistribution — the target is min(current,
    # capped), so a pool only ever goes down or holds, the mass it
    # releases is cash (the sum may sit well under 100 × governor, by
    # design), the move down is uncapped and the move up is frozen at 0.
    # A 20% crash used to take three plans to reach the pools (2026-09-12).
    moved = _applied_today(user, now)
    targets: dict = {}
    held_pks: set = set()
    for cfg in followers:
        pk = cfg.pk
        lo = bounds[pk][0]
        cur = current.get(pk)
        cur_num = float(cur or 0.0)
        used = float(moved.get(str(pk), 0.0))
        if mode == MODE_SHOCK:
            smoothed = min(cur_num, capped[pk]) if cur is not None else capped[pk]
            # 100 points is the whole account: "uncapped" as a number the
            # page can print, and a bound nothing can exceed.
            allowance_up, allowance_down = 0.0, 100.0
        elif mode == MODE_EXPANSION:
            smoothed = cur_num + SMOOTHING_ALPHA * (capped[pk] - cur_num)
            allowance_up = max(0.0, EXPANSION_CAP_PCT_PER_DAY - used)
            allowance_down = max(0.0, MAX_CHANGE_PCT_PER_DAY - used)
        else:
            smoothed = cur_num + SMOOTHING_ALPHA * (capped[pk] - cur_num)
            allowance_up = allowance_down = max(0.0, MAX_CHANGE_PCT_PER_DAY
                                                - used)
        allowance = allowance_up
        move = max(-allowance_down, min(allowance_up, smoothed - cur_num))
        held = False
        # In SHOCK the floor guard comes off the hysteresis: a pool under
        # its floor cannot move up (up is frozen) and must not move down
        # by the rounding of its own share either — an automatic third,
        # 33.3333, written as 33.33 was a "move" the sync re-sized on and
        # is_pure_derisk counted as a de-risk (2026-09-12). The floor
        # lift below still runs on it. NORMAL keeps the guard: there the
        # pool smooths up toward its floor.
        hold_ok = (mode == MODE_SHOCK) or cur_num >= lo
        if cur is not None and hold_ok \
                and abs(smoothed - cur_num) < MIN_DELTA_PCT:
            # Hysteresis: the target repeats the current share EXACTLY —
            # not rounded. Three automatic followers hold 33.333…% each;
            # 33.33 left 0.01% of the account unclaimed and re-sized
            # every pool by a few cents on a plan that said "held", so
            # the sync wrote where it should have written nothing
            # (2026-09-12). An equal share is a no-op for the sync.
            held, target = True, float(cur)
        else:
            # g. two decimals on a real move.
            target = round(cur_num + move, 2)
        # A follower under its floor is never STUCK there. Smoothing
        # halves the distance each plan, so a share typed at 1% under a
        # 2% floor goes 1.5, 1.75, … and hysteresis would hold it under
        # the floor for ever; once the gap is under the hysteresis the
        # target is the floor itself, as far as the day's allowance
        # reaches. A follower with no current share at all enters at its
        # floor: a share must stay a share — 0 reads as "automatic" to
        # account_share_pct and hands this follower the whole remainder,
        # so with no allowance left it still gets its floor. A share
        # further under an operator-set floor keeps the smoothed path
        # (50 → 52.5 → 53.75 → 55 under a 55% floor).
        if target < lo and (cur is None or lo - target < MIN_DELTA_PCT):
            reach = round(min(lo, cur_num + allowance), 2)
            if reach <= 0.0 or mode == MODE_SHOCK:
                # In shock the upward allowance is 0, which would leave a
                # pool under its floor there; the floor is the size that
                # still grades, and it holds in every mode.
                reach = round(lo, 2)
            if reach > target:
                target = reach
                held = False   # lifted: the target is the floor, not cur
                notes.append(f"{cfg.name}: below its floor — lifted to "
                             f"{target:g}%")
        if held:
            held_pks.add(pk)
        targets[pk] = target
        row = inputs[str(pk)]
        row.update({"raw": round(raw[pk], 4), "capped": round(capped[pk], 4),
                    "smoothed": round(smoothed, 4), "held": held,
                    "target": target, "mode": mode,
                    "allowance_up": round(allowance_up, 4),
                    "allowance_down": round(allowance_down, 4),
                    "why": _why(row["evidence"], row["regime"],
                                row["opportunity"], row["news"], raw[pk],
                                capped[pk], smoothed, target, held,
                                mode=mode, allowance_up=allowance_up,
                                allowance_down=allowance_down,
                                hz=row.get("horizon"))})

    # Rounding and the lifts above can push a full account past 100 —
    # shave the excess (moved targets first, held ones only when nothing
    # else has room, never below a floor) rather than let the rule refuse.
    cuts = _shave_to_100(targets, bounds, held_pks)
    for pk, cut in cuts.items():
        row = inputs[str(pk)]
        held_pks.discard(pk)
        row["held"] = False
        row["target"] = targets[pk]
        row["why"] = _why(row["evidence"], row["regime"], row["opportunity"],
                          row["news"], row["raw"], row["capped"],
                          row["smoothed"], targets[pk], False, mode=mode,
                          allowance_up=row.get("allowance_up"),
                          allowance_down=row.get("allowance_down"),
                          hz=row.get("horizon")) + \
            f" — {cut:.2f} pt shaved to fit 100%"
    if sum(cuts.values()) > 0.01 + 1e-9:
        notes.append(f"targets summed past 100% — {sum(cuts.values()):.2f} pt "
                     f"shaved off the largest")

    check = allocate_shares(followers, shares=targets)
    if not check["ok"]:
        reason = f"targets refused by allocate_shares: {check['reason']}"
        logger.info("[shares] user %s: %s — nothing proposed", name, reason)
        return None, reason

    # h. the plan, and the older proposals it supersedes
    from decimal import Decimal
    with transaction.atomic():
        plan = SharePlan.objects.create(
            user=user, state=SharePlan.STATE_PROPOSED,
            reading_value=Decimal(str(round(float(reading["value"]), 2))),
            reading_currency=reading["currency"] or "",
            reading_at=reading["at"], reading_age_s=reading["age_seconds"],
            hwm=Decimal(str(round(hwm, 2))), drawdown_pct=dd_pct,
            governor=governor, mode=mode, mode_reasons=list(state["reasons"]),
            inputs=inputs, targets={str(k): v for k, v in targets.items()},
            current_shares={str(k): v for k, v in current.items()},
            configs_considered=len(followers), configs_skipped=0,
            notes="; ".join(notes))
        for old in (SharePlan.objects.select_for_update()
                    .filter(user=user, state=SharePlan.STATE_PROPOSED)
                    .exclude(pk=plan.pk)):
            old.state = SharePlan.STATE_EXPIRED
            old.notes = ((old.notes + "; ") if old.notes else "") + \
                f"superseded by #{plan.pk}"
            old.save(update_fields=["state", "notes"])
    logger.info("[shares] user %s: proposed plan #%s for %d follower(s) "
                "(governor %.2f, mode %s)", name, plan.pk, len(followers),
                governor, mode)
    # The opt-in automatic de-risk — only a SHOCK plan that lowers every
    # share, only with both switches on. Wrapped: an apply that fails
    # (daily cap, stale reading) leaves the plan PROPOSED for a human and
    # must never undo the proposal that was just written.
    try:
        if auto_derisk_if_allowed(plan, now=now):
            plan.refresh_from_db()
    except Exception as e:  # noqa: BLE001
        logger.warning("[shares] auto de-risk of plan #%s failed: %s",
                       plan.pk, e)
    return plan, ""


# ── Automatic de-risking (opt-in) ────────────────────────────────────────

def is_pure_derisk(plan) -> bool:
    """True iff every target is at or under its current share (within
    1e-9) and at least one is strictly under. A follower with no current
    share (entering at its floor) is an UPWARD move and disqualifies the
    plan: automatic means down only, never a new pool sized by nobody."""
    current = plan.current_shares or {}
    lowered = False
    for k, target in (plan.targets or {}).items():
        cur = current.get(k)
        if cur is None:
            return False
        try:
            t, c = float(target), float(cur)
        except (TypeError, ValueError):
            return False
        if t > c + 1e-9:
            return False
        if t < c - 1e-9:
            lowered = True
    return lowered


def auto_derisk_if_allowed(plan, *, now=None) -> bool:
    """Apply `plan` with no human when — and only when — LIVE mode and the
    share_allocator_auto_derisk component are both on, the plan is a
    SHOCK plan, and it is a pure de-risk (is_pure_derisk). The apply is
    the same apply_share_plan an admin runs: daily cap, fresh reading,
    snapshot for rollback, audit row (decision 'auto_derisk'). Re-risking
    is never automatic. A ShareAllocatorError is logged and the plan
    stays PROPOSED for a human. Returns True iff the plan was applied."""
    from bot_program.share_models import SharePlan
    # The plan's own mode first: a NORMAL proposal must not cost two
    # component reads to learn it was never a candidate.
    if plan.mode != MODE_SHOCK or plan.state != SharePlan.STATE_PROPOSED:
        return False
    if not is_live_mode() or not is_auto_derisk_enabled():
        return False
    if not is_pure_derisk(plan):
        logger.info("[shares] plan #%s is not a pure de-risk — left for "
                    "a human", plan.pk)
        return False
    try:
        applied = apply_share_plan(plan.pk, None, decision="auto_derisk")
    except ShareAllocatorError as e:
        logger.warning("[shares] auto de-risk of plan #%s refused: %s "
                       "— left PROPOSED", plan.pk, e)
        return False
    applied.notes = ((applied.notes + "; ") if applied.notes else "") + \
        "auto de-risk applied"
    applied.save(update_fields=["notes"])
    inputs = applied.inputs or {}
    current = applied.current_shares or {}
    moves = []
    for k, target in (applied.targets or {}).items():
        name = (inputs.get(k) or {}).get("name") or f"#{k}"
        cur = current.get(k)
        cur_s = f"{float(cur):g}%" if cur is not None else "auto"
        moves.append(f"{name} {cur_s} → {float(target):g}%")
    try:
        from bot_program.notifications import notify_staff
        notify_staff(
            title="⚠ Shares de-risked automatically",
            body=(f"{getattr(applied.user, 'username', applied.user_id)}: "
                  f"plan #{applied.pk} — " + "; ".join(moves)
                  + ". Rollback on /shares/ restores the previous shares "
                    "exactly."),
            url="/shares/", cooldown_hours=1)
    except Exception as e:  # noqa: BLE001 — the apply stands, the alert is beside it
        logger.warning("[shares] auto de-risk alert failed: %s", e)
    logger.info("[shares] auto de-risk applied plan #%s: %s", applied.pk,
                "; ".join(moves))
    return True


# ── Apply / rollback / reject ────────────────────────────────────────────

def _locked_plan(plan_id):
    from bot_program.share_models import SharePlan
    plan = SharePlan.objects.select_for_update().filter(pk=plan_id).first()
    if plan is None:
        raise ShareAllocatorError(f"share plan #{plan_id} not found")
    return plan


def applies_used_today(user, now=None) -> int:
    from bot_program.share_models import SharePlan
    now = now or timezone.now()
    return SharePlan.objects.filter(
        user=user, state=SharePlan.STATE_APPLIED,
        applied_at__gte=now - timedelta(hours=24)).count()


@transaction.atomic
def apply_share_plan(plan_id, user, *, decision="applied"):
    """Write every surviving target as the follower's explicit share and
    re-split the pools through the sync's own arithmetic. LIVE mode only,
    PROPOSED only, fresh reading only, MAX_APPLIES_PER_DAY per user.
    `decision` is the audit row's word: 'applied' for a human, 'auto_derisk'
    for auto_derisk_if_allowed — same kind, same gates, same snapshot."""
    from bot_program.audit import record_share_plan
    from bot_program.capital_truth import (TRACKING_FRESH_SECONDS,
                                           account_equity, allocate_shares,
                                           followers_of)
    from bot_program.models import AssetBotConfig
    from bot_program.share_models import SharePlan
    from bot_program.tasks import _follow_the_account

    if not is_live_mode():
        raise ShareAllocatorError(
            "Share allocator is in shadow mode — apply is disabled.")
    plan = _locked_plan(plan_id)
    if plan.state != SharePlan.STATE_PROPOSED:
        raise ShareAllocatorError(
            f"share plan #{plan.pk} is {plan.state}, not proposed")
    reading = account_equity(plan.user)
    if reading is None:
        raise ShareAllocatorError(
            "no broker reading has landed — run sync_broker_account first")
    if reading["age_seconds"] > TRACKING_FRESH_SECONDS:
        raise ShareAllocatorError(
            f"the broker reading is {reading['age_seconds'] / 3600:.1f}h old "
            f"— a plan is applied against a fresh reading only")
    now = timezone.now()
    if applies_used_today(plan.user, now) >= MAX_APPLIES_PER_DAY:
        raise ShareAllocatorError(
            f"Daily cap reached for share plans ({MAX_APPLIES_PER_DAY}/day). "
            f"Try again later or raise the cap.")

    followers = followers_of(plan.user)
    by_pk = {c.pk: c for c in followers}
    targets = {}
    for k, v in (plan.targets or {}).items():
        try:
            targets[int(k)] = float(v)
        except (TypeError, ValueError):
            continue
    vanished = sorted(k for k in targets if k not in by_pk)
    surviving = {k: v for k, v in targets.items() if k in by_pk}
    if not surviving:
        raise ShareAllocatorError(
            f"none of plan #{plan.pk}'s configs still follows the account")
    check = allocate_shares(followers, shares=surviving)
    if not check["ok"]:
        raise ShareAllocatorError(
            f"plan #{plan.pk} no longer fits the account: {check['reason']}")

    previous = {}
    for pk, target in surviving.items():
        row = AssetBotConfig.objects.select_for_update().get(pk=pk)
        ex = dict(row.extras or {})
        previous[str(pk)] = ex.get("account_share_pct")
        ex["account_share_pct"] = target
        row.extras = ex
        row.save(update_fields=["extras", "updated_at"])
    _follow_the_account(plan.user, float(reading["value"]),
                        reading["currency"])

    plan.previous_shares = previous
    plan.state = SharePlan.STATE_APPLIED
    plan.applied_at = now
    plan.confirmed_by = (user if getattr(user, "is_authenticated", False)
                         and getattr(user, "pk", None) else None)
    plan.configs_skipped = len(vanished)
    if vanished:
        names = ", ".join(f"#{k} {(plan.inputs or {}).get(str(k), {}).get('name', '?')}"
                          for k in vanished)
        plan.notes = ((plan.notes + "; ") if plan.notes else "") + \
            f"skipped at apply (no longer a follower): {names}"
    plan.save(update_fields=["previous_shares", "state", "applied_at",
                             "confirmed_by", "configs_skipped", "notes"])
    record_share_plan(plan, decision, user)
    logger.info("[shares] applied plan #%s — %d pool(s) re-sized (%s)",
                plan.pk, len(surviving), decision)
    return plan


@transaction.atomic
def rollback_share_plan(plan_id, user):
    """Put every follower's share back exactly as the apply found it —
    the key removed where the follower was automatic — and re-split."""
    from bot_program.audit import record_share_plan
    from bot_program.capital_truth import account_equity, followers_of
    from bot_program.models import AssetBotConfig
    from bot_program.share_models import SharePlan
    from bot_program.tasks import _follow_the_account

    plan = _locked_plan(plan_id)
    if plan.state != SharePlan.STATE_APPLIED:
        raise ShareAllocatorError(
            f"share plan #{plan.pk} is {plan.state}, not applied")
    followers = {c.pk for c in followers_of(plan.user)}
    skipped, restored = [], 0
    for k, prev in (plan.previous_shares or {}).items():
        pk = int(k)
        if pk not in followers:
            skipped.append(k)
            continue
        row = AssetBotConfig.objects.select_for_update().get(pk=pk)
        ex = dict(row.extras or {})
        if prev is None:
            ex.pop("account_share_pct", None)
        else:
            ex["account_share_pct"] = prev
        row.extras = ex
        row.save(update_fields=["extras", "updated_at"])
        restored += 1
    reading = account_equity(plan.user)
    if reading is not None:
        _follow_the_account(plan.user, float(reading["value"]),
                            reading["currency"])
    else:
        plan.notes = ((plan.notes + "; ") if plan.notes else "") + \
            "rolled back without a reading — pools re-size on the next sync"
    if skipped:
        names = ", ".join(f"#{k} {(plan.inputs or {}).get(k, {}).get('name', '?')}"
                          for k in skipped)
        plan.notes = ((plan.notes + "; ") if plan.notes else "") + \
            f"skipped at rollback (no longer a follower): {names}"
    plan.state = SharePlan.STATE_ROLLED_BACK
    plan.rolled_back_at = timezone.now()
    plan.save(update_fields=["state", "rolled_back_at", "notes"])
    record_share_plan(plan, "rolled_back", user)
    logger.info("[shares] rolled back plan #%s — %d share(s) restored",
                plan.pk, restored)
    return plan


@transaction.atomic
def reject_share_plan(plan_id, user):
    """PROPOSED -> REJECTED. No PIN, no writes to any config."""
    from bot_program.audit import record_share_plan
    from bot_program.share_models import SharePlan

    plan = _locked_plan(plan_id)
    if plan.state != SharePlan.STATE_PROPOSED:
        raise ShareAllocatorError(
            f"share plan #{plan.pk} is {plan.state}, not proposed")
    plan.state = SharePlan.STATE_REJECTED
    plan.rejected_at = timezone.now()
    plan.save(update_fields=["state", "rejected_at"])
    record_share_plan(plan, "rejected", user)
    return plan


# ── Housekeeping: expiry and the grade ───────────────────────────────────

def expire_stale_plans(now=None) -> int:
    """PROPOSED plans older than PROPOSAL_TTL_HOURS become EXPIRED."""
    from bot_program.share_models import SharePlan
    now = now or timezone.now()
    n = 0
    for plan in SharePlan.objects.filter(
            state=SharePlan.STATE_PROPOSED,
            proposed_at__lt=now - timedelta(hours=PROPOSAL_TTL_HOURS)):
        plan.state = SharePlan.STATE_EXPIRED
        plan.notes = ((plan.notes + "; ") if plan.notes else "") + \
            f"expired after {PROPOSAL_TTL_HOURS}h without a decision"
        plan.save(update_fields=["state", "notes"])
        n += 1
    return n


def grade_plans(now=None) -> int:
    """Score every ungraded plan whose 24h window has closed.

    grade_score = Σ over configs with a live close in the window of
    (target - current) / 100 × Σ realized_r. Positive means the plan
    leaned toward what paid. A plan with no live close in its window is
    ungradeable — grade_score None, graded_at set — which is not wrong.
    """
    from django.db.models import Sum

    from bot_program.models import AssetBotTrade
    from bot_program.share_models import SharePlan

    now = now or timezone.now()
    n = 0
    plans = SharePlan.objects.filter(
        graded_at__isnull=True,
        proposed_at__lte=now - timedelta(hours=24),
        state__in=[SharePlan.STATE_APPLIED, SharePlan.STATE_ROLLED_BACK,
                   SharePlan.STATE_EXPIRED, SharePlan.STATE_PROPOSED])
    for plan in plans:
        start, end = plan.proposed_at, plan.proposed_at + timedelta(hours=24)
        detail, score, graded = {}, 0.0, 0
        current = plan.current_shares or {}
        for k, target in (plan.targets or {}).items():
            try:
                pk, tgt = int(k), float(target)
            except (TypeError, ValueError):
                continue
            agg = (AssetBotTrade.objects
                   .filter(config_id=pk, status="CLOSED", paper=False,
                           realized_r__isnull=False,
                           outcome__in=GRADED_OUTCOMES,
                           closed_at__gte=start, closed_at__lte=end)
                   .aggregate(r=Sum("realized_r")))
            r = agg["r"]
            r = float(r) if r is not None else None
            delta = tgt - float(current.get(k) or 0.0)
            detail[k] = {"r": r, "delta": round(delta, 4)}
            if r is not None:
                graded += 1
                score += delta / 100.0 * r
        detail["n_graded_configs"] = graded
        if graded == 0:
            plan.grade_score = None
            plan.grade_detail = {"reason": "no live closes in the window",
                                 "n_graded_configs": 0}
        else:
            plan.grade_score = round(score, 6)
            plan.grade_detail = detail
        plan.graded_at = now
        plan.save(update_fields=["grade_score", "grade_detail", "graded_at"])
        n += 1
    return n
