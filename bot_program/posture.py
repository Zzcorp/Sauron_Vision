"""THE POSTURE: what the market's stress does to one real-money entry
(2026-10-02, the crisis mode's hands; bot_program/market_stress.py is its
eyes).

The operator, on leverage in a crash: "un mix des deux vraiment smart,
adapté et résilient". So nothing here is a blanket switch-off: each entry
is classified by what it does in a crash, and the posture treats it by
that:

  risk_on_long   buys what falls in a crash (stocks, indices, crypto,
                 risk ETFs, industrial commodities, a risk currency
                 against a haven)
  risk_on_short  sells one of those: rides the crash
  haven_long     buys what a crash bids (gold, treasuries, the yen and the
                 franc, the dollar against risk currencies)
  haven_short    sells a haven: fights the crash's flight to safety
  neutral        neither (a cross of equals)

POSTURE_TABLE gives each (level, kind) its size scale, its leverage cap
(as a fraction of the class ceiling, and an absolute cap) and whether a
REAL-MONEY entry may open at all — one refused goes to PAPER instead (the
evidence keeps flowing; nothing is sent). In recovery, risk-on longs come
back in steps by days since the crisis eased (RECOVERY_STEPS).

Two dark-water scales sit beside it and bind in every level:
  drawdown_scale  the account under its 90-day high-water mark ->
                  share_allocator.governor_for (1.0 down to 0.4 between 5%
                  and 20%), unless the share allocator or the desk live
                  mode already applies it
  streak_scale    the last STREAK_N real-money closes all losses ->
                  STREAK_SCALE until a win

Paper entries are never touched: the posture protects money, and the
paper book is the evidence Aragorn promotes on.
"""
import logging

logger = logging.getLogger(__name__)

RISK_ON, RISK_ON_SHORT = "risk_on_long", "risk_on_short"
HAVEN, HAVEN_SHORT, NEUTRAL = "haven_long", "haven_short", "neutral"

#: Symbols that ARE a haven when bought (gold, silver, treasuries, the
#: dollar index). Silver is half a haven; it rides with gold here.
HAVEN_SYMBOLS = frozenset({
    "XAUUSD", "GOLD", "GLD", "GLDM", "IAU", "SGOL", "XAGUSD", "SILVER", "SLV",
    "TLT", "IEF", "SHY", "GOVT", "BND", "AGG", "UUP", "DXY"})
#: Currency haven rank: buying a higher rank against a lower one is a
#: haven trade (the yen and the franc first, then the dollar).
CCY_RANK = {"JPY": 3, "CHF": 3, "USD": 2, "EUR": 1, "GBP": 1}

#: (level, kind) -> (size scale, leverage fraction of the class ceiling,
#: absolute leverage cap or None, real money allowed)
POSTURE_TABLE = {
    ("calm", RISK_ON): (1.0, 1.0, None, True),
    ("calm", RISK_ON_SHORT): (1.0, 1.0, None, True),
    ("calm", HAVEN): (1.0, 1.0, None, True),
    ("calm", HAVEN_SHORT): (1.0, 1.0, None, True),
    ("calm", NEUTRAL): (1.0, 1.0, None, True),
    ("stressed", RISK_ON): (0.6, 0.5, None, True),
    ("stressed", RISK_ON_SHORT): (0.8, 0.5, None, True),
    ("stressed", HAVEN): (1.0, 0.5, None, True),
    ("stressed", HAVEN_SHORT): (0.6, 0.5, None, True),
    ("stressed", NEUTRAL): (0.8, 0.5, None, True),
    ("crisis", RISK_ON): (0.0, 0.0, 1, False),
    ("crisis", RISK_ON_SHORT): (1.0, 0.5, None, True),
    ("crisis", HAVEN): (1.0, 0.5, None, True),
    ("crisis", HAVEN_SHORT): (0.0, 0.0, 1, False),
    ("crisis", NEUTRAL): (0.5, 0.0, 2, True),
    ("recovery", RISK_ON): (None, 0.0, 2, True),   # size from RECOVERY_STEPS
    ("recovery", RISK_ON_SHORT): (0.5, 0.5, None, True),
    ("recovery", HAVEN): (0.7, 0.5, None, True),
    ("recovery", HAVEN_SHORT): (0.5, 0.5, None, True),
    ("recovery", NEUTRAL): (0.8, 0.5, None, True),
}
#: days since the crisis eased -> risk-on long size in recovery
RECOVERY_STEPS = ((0.0, 0.33), (2.0, 0.5), (4.0, 0.75))

STREAK_N = 3
STREAK_SCALE = 0.6

RISK_CLASSES = frozenset({"stock", "index", "crypto", "etf", "commodity",
                          "options", "cfd"})

SWITCH = "crisis_mode"


def crisis_mode_on() -> bool:
    """The crisis mode's switch (LIVE_MONEY_SWITCHES): OFF, the posture
    changes nothing anywhere."""
    from core.platform_control import is_component_enabled
    try:
        return bool(is_component_enabled(SWITCH))
    except Exception:  # noqa: BLE001
        return False


def classify(symbol, asset_class, side) -> str:
    """What this entry does in a crash (see the module docstring)."""
    sym = str(symbol or "").upper().replace("/", "")
    cls = str(asset_class or "")
    buy = str(side or "BUY").upper() == "BUY"
    if cls == "forex" and len(sym) >= 6:
        base, quote = sym[:3], sym[3:6]
        rb, rq = CCY_RANK.get(base, 0), CCY_RANK.get(quote, 0)
        bought, sold = (rb, rq) if buy else (rq, rb)
        if bought > sold:
            return HAVEN
        if bought < sold:
            return RISK_ON
        return NEUTRAL
    if sym in HAVEN_SYMBOLS:
        return HAVEN if buy else HAVEN_SHORT
    if cls in RISK_CLASSES:
        return RISK_ON if buy else RISK_ON_SHORT
    return NEUTRAL


def recovery_size(days) -> float:
    size = RECOVERY_STEPS[0][1]
    for start, s in RECOVERY_STEPS:
        if days >= start:
            size = s
    return size


def posture_rule(level, kind, *, recovery_days=0.0) -> dict:
    """{size, lev_frac, lev_abs, live} for one (level, kind)."""
    size, frac, abs_cap, live = POSTURE_TABLE.get(
        (level, kind), POSTURE_TABLE[("calm", kind if kind in (
            RISK_ON, RISK_ON_SHORT, HAVEN, HAVEN_SHORT) else NEUTRAL)])
    if size is None:
        size = recovery_size(recovery_days)
    return {"size": float(size), "lev_frac": float(frac),
            "lev_abs": abs_cap, "live": bool(live)}


def leverage_cap(level, kind, class_ceiling, *, recovery_days=0.0):
    """The highest multiplier the posture lets this entry carry, or None
    for no cap. Never below 1."""
    rule = posture_rule(level, kind, recovery_days=recovery_days)
    caps = []
    if rule["lev_frac"] and rule["lev_frac"] < 1.0:
        caps.append(max(1, int(float(class_ceiling or 1) * rule["lev_frac"])))
    if rule["lev_abs"]:
        caps.append(int(rule["lev_abs"]))
    if not caps:
        return None
    return max(1, min(caps))


def drawdown_scale(user) -> tuple:
    """(scale, why) from the account's drawdown under its high-water mark —
    unless the share allocator or the capital desk already applies the
    same governor (their live modes), which would square it."""
    try:
        from core.platform_control import is_component_enabled
        for key in ("share_allocator_mode_live", "capital_desk_mode_live"):
            if is_component_enabled(key):
                return 1.0, ""
    except Exception:  # noqa: BLE001
        pass
    try:
        from bot_program.capital_truth import equity_drawdown
        from bot_program.share_allocator import governor_for
        dd = equity_drawdown(user)
        if not dd:
            return 1.0, ""
        pct = float(dd.get("drawdown_pct") or 0.0)
        g = float(governor_for(pct))
        if g < 1.0:
            return g, f"account {pct * 100:.1f}% under its high-water mark"
        return 1.0, ""
    except Exception as e:  # noqa: BLE001 — an unread drawdown scales nothing
        return 1.0, f"drawdown unread ({type(e).__name__})"


def streak_scale(user) -> tuple:
    """(scale, why): the last STREAK_N real-money closes all lost."""
    try:
        from bot_program.asset_models import AssetBotTrade
        last = list(AssetBotTrade.objects.filter(
            config__user=user, paper=False, status="CLOSED",
            pnl__isnull=False).order_by("-closed_at")
            .values_list("pnl", flat=True)[:STREAK_N])
        if len(last) == STREAK_N and all(float(p) < 0 for p in last):
            return STREAK_SCALE, f"the last {STREAK_N} real-money closes lost"
        return 1.0, ""
    except Exception as e:  # noqa: BLE001
        return 1.0, f"streak unread ({type(e).__name__})"


def entry_posture(user, symbol, asset_class, side, *, now=None) -> dict:
    """The whole posture for one REAL-MONEY entry:
    {level, kind, live, size, lev_cap_frac, lev_abs, recovery_days, why}
    where size already multiplies the posture, the drawdown and the
    streak scales."""
    from bot_program import market_stress
    cur = market_stress.current(now)
    level = cur["level"]
    kind = classify(symbol, asset_class, side)
    rdays = market_stress.recovery_days(now) if level == "recovery" else 0.0
    rule = posture_rule(level, kind, recovery_days=rdays)
    dd, dd_why = drawdown_scale(user)
    st, st_why = streak_scale(user)
    why = [f"posture {level} ({cur['why']}), {kind.replace('_', ' ')}"]
    if rule["size"] < 1.0:
        why.append(f"posture size x{rule['size']:g}")
    if dd < 1.0:
        why.append(f"{dd_why}: x{dd:.2f}")
    if st < 1.0:
        why.append(f"{st_why}: x{st:g}")
    return {"level": level, "kind": kind, "live": rule["live"],
            "size": round(rule["size"] * dd * st, 4),
            "lev_frac": rule["lev_frac"], "lev_abs": rule["lev_abs"],
            "recovery_days": rdays, "why": "; ".join(why)}
