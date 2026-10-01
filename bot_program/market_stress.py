"""THE MARKET'S STRESS, MEASURED (2026-10-02) — the crisis mode's eyes.

The operator: "a crash is coming ... we have to be ready, armed for such a
situation ... from crisis comes opportunity". Until now the only regime that
moved money was an hourly LLM label built from the symbols the book already
held; nothing that trades read the indices, the volatility, the VIX or the
credit spread. This module reads them, deterministically, every 15 minutes,
and sets the POSTURE the rest of the platform obeys (bot_program/posture.py):

  calm      business as usual
  stressed  smaller risk-on longs, half leverage
  crisis    no new risk-on long with real money, shorts and havens keep
            trading, leverage capped
  recovery  after a crisis: risk-on longs come back in steps

THE SCORE (0-100) is a weighted mean of the components that could be read,
each mapped to 0-100 by fixed breakpoints (COMPONENTS, below):
  index_drawdown   the worse of SPX500 / NSDQ100 under its 60-day high
  index_5d         SPX500's 5-day return
  realized_vol     SPX500's 20-day realized vol against its 1-year level
  vix              FRED VIXCLS, when fresh
  hy_spread        FRED BAMLH0A0HYM2 (US high yield OAS), when fresh
  brain            the brain's risk_off / blow_off label, when confident
A component nobody can read is left out and SAID; with no index and no VIX
the score is unmeasured and the posture holds its last level (calm if none).

THE LEVELS go up at once and come down slowly (de-risk fast, re-risk slow):
calm -> stressed at SCORE_STRESSED, -> crisis at SCORE_CRISIS, the moment a
reading says so. Down needs CALM_CONFIRM readings in a row spanning
CALM_CONFIRM_HOURS. A crisis ends in RECOVERY (score under RECOVERY_BELOW
and the index up over 5 days), which lasts until calm is confirmed, a new
crisis, or RECOVERY_MAX_DAYS.

An operator override (manage.py steward posture <level> [--hours N]) wins
until it expires. Never raises: a reading that fails holds the last level.
"""
import logging
import math
from datetime import timedelta

from django.utils import timezone

logger = logging.getLogger(__name__)

CALM, STRESSED, CRISIS, RECOVERY = "calm", "stressed", "crisis", "recovery"
LEVELS = (CALM, STRESSED, CRISIS, RECOVERY)

SCORE_STRESSED = 30.0
SCORE_CRISIS = 55.0
RECOVERY_BELOW = 45.0
CALM_CONFIRM = 2
CALM_CONFIRM_HOURS = 4.0
RECOVERY_MAX_DAYS = 10
#: a reading older than this is not the posture any more: the last level
#: holds for HOLD_HOURS, then calm with the reason said
STALE_HOURS = 2.0
HOLD_HOURS = 24.0

INDEX_SYMBOLS = ("SPX500", "NSDQ100")
VIX_SERIES = "VIXCLS"
HY_SERIES = "BAMLH0A0HYM2"
MACRO_FRESH_DAYS = 5
OVERRIDE_KEY = "posture_override"

#: component -> (weight, breakpoints [(x, score)], ascending in x)
COMPONENTS = {
    "index_drawdown": (0.25, [(0.0, 0), (0.05, 40), (0.10, 75), (0.15, 100)]),
    # the 5-day return, NEGATED so a fall is a positive x
    "index_5d": (0.15, [(0.0, 0), (0.03, 50), (0.06, 100)]),
    "realized_vol": (0.20, [(1.0, 0), (1.5, 50), (2.5, 100)]),
    "vix": (0.20, [(16.0, 0), (22.0, 40), (30.0, 75), (40.0, 100)]),
    "hy_spread": (0.10, [(3.5, 0), (5.0, 50), (7.0, 100)]),
    "brain": (0.10, None),
}


def _interp(x, points) -> float:
    if x <= points[0][0]:
        return float(points[0][1])
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x <= x1:
            return float(y0 + (y1 - y0) * (x - x0) / (x1 - x0))
    return float(points[-1][1])


def _daily_closes(symbol, n=260):
    """Oldest-first daily closes of an instrument, with the live quote as
    the last close when it is fresher than the last bar."""
    from instruments.models import Instrument
    from market_data.models import LiveQuote, PriceData
    inst = Instrument.objects.filter(symbol=symbol).first()
    if inst is None:
        return []
    bars = list(PriceData.objects.filter(instrument=inst, timeframe="1d")
                .order_by("-timestamp").values_list("timestamp", "close")[:n])
    closes = [float(c) for _t, c in reversed(bars)]
    q = LiveQuote.objects.filter(instrument=inst).first()
    if q is not None and q.last and bars:
        age = (timezone.now() - q.updated_at).total_seconds()
        if age < 3600 and q.updated_at > bars[0][0]:
            closes.append(float(q.last))
    return closes


def _index_components(out, reasons):
    worst_dd, spx = None, None
    for sym in INDEX_SYMBOLS:
        closes = _daily_closes(sym)
        if len(closes) < 61:
            reasons.append(f"{sym}: {len(closes)} daily closes, 61 needed")
            continue
        last = closes[-1]
        high60 = max(closes[-61:])
        dd = max(0.0, 1.0 - last / high60) if high60 > 0 else 0.0
        worst_dd = dd if worst_dd is None else max(worst_dd, dd)
        if sym == "SPX500":
            spx = closes
    if worst_dd is not None:
        out["index_drawdown"] = round(worst_dd, 4)
    if spx and len(spx) >= 6:
        out["index_5d"] = round(spx[-1] / spx[-6] - 1.0, 4)
    if spx and len(spx) >= 120:
        rets = [math.log(b / a) for a, b in zip(spx, spx[1:]) if a > 0 and b > 0]
        if len(rets) >= 100:
            def _vol(xs):
                m = sum(xs) / len(xs)
                return math.sqrt(sum((x - m) ** 2 for x in xs) / max(1, len(xs) - 1))
            v20, v1y = _vol(rets[-20:]), _vol(rets[-250:])
            if v1y > 0:
                out["realized_vol"] = round(v20 / v1y, 3)


def _macro(series, now):
    from market_data.models import MacroIndicator, MacroObservation
    ind = MacroIndicator.objects.filter(series_id=series).first()
    if ind is None:
        return None, None
    obs = list(MacroObservation.objects.filter(indicator=ind)
               .order_by("-date").values_list("date", "value")[:25])
    if not obs or (now.date() - obs[0][0]).days > MACRO_FRESH_DAYS:
        return None, None
    change = (float(obs[0][1]) - float(obs[-1][1])) if len(obs) >= 20 else None
    return float(obs[0][1]), change


def read_components(now=None) -> tuple:
    """({component: raw value}, [reasons]) — every input that could be read,
    and why each one that could not was left out."""
    now = now or timezone.now()
    out, reasons = {}, []
    try:
        _index_components(out, reasons)
    except Exception as e:  # noqa: BLE001
        reasons.append(f"indices unreadable: {type(e).__name__}: {e}")
    for key, series in (("vix", VIX_SERIES), ("hy_spread", HY_SERIES)):
        try:
            val, change = _macro(series, now)
            if val is None:
                reasons.append(f"{series}: no fresh observation (FRED)")
            else:
                out[key] = val
                if key == "hy_spread" and change is not None:
                    out["hy_change"] = round(change, 3)
        except Exception as e:  # noqa: BLE001
            reasons.append(f"{series} unreadable: {type(e).__name__}")
    try:
        from brain.context import get_brain_context
        ctx = get_brain_context() or {}
        label = str(ctx.get("regime_label") or "")
        conf = float(ctx.get("regime_confidence") or 0.0)
        if label:
            out["brain"] = {"label": label, "confidence": round(conf, 2)}
    except Exception as e:  # noqa: BLE001
        reasons.append(f"brain unreadable: {type(e).__name__}")
    return out, reasons


def score(components: dict) -> tuple:
    """(score 0-100 or None, {component: sub-score}). None when neither an
    index nor the VIX could be read: too little to call a crisis on."""
    if not any(k in components for k in ("index_drawdown", "vix")):
        return None, {}
    subs, total, weights = {}, 0.0, 0.0
    for key, (weight, points) in COMPONENTS.items():
        if key not in components:
            continue
        raw = components[key]
        if key == "brain":
            label = (raw or {}).get("label")
            conf = float((raw or {}).get("confidence") or 0.0)
            s = (80.0 if label == "blow_off" else 60.0
                 if label == "risk_off" else 0.0) if conf >= 0.65 else 0.0
        elif key == "index_5d":
            s = _interp(-float(raw), points)
        else:
            s = _interp(float(raw), points)
            if key == "hy_spread" and (components.get("hy_change") or 0) >= 1.0:
                s = min(100.0, s + 25.0)
        subs[key] = round(s, 1)
        total += weight * s
        weights += weight
    return round(total / weights, 1) if weights else None, subs


def raw_level(sc) -> str:
    if sc is None:
        return ""
    if sc >= SCORE_CRISIS:
        return CRISIS
    if sc >= SCORE_STRESSED:
        return STRESSED
    return CALM


def next_level(prev, sc, raw, components, history, now) -> tuple:
    """(level, why) from the previous level, this reading and the recent
    readings (newest first): up at once, down slowly, a crisis ends in a
    recovery."""
    if not raw:
        return (prev or CALM), "score unmeasured: the last level holds"
    prev = prev or CALM

    def _calm_confirmed():
        calm_run = [r for r in history[:CALM_CONFIRM - 1]
                    if r.raw_level == CALM]
        if len(calm_run) < CALM_CONFIRM - 1:
            return False
        oldest = calm_run[-1].at if calm_run else now
        return (now - oldest) >= timedelta(hours=CALM_CONFIRM_HOURS)

    if raw == CRISIS:
        return CRISIS, f"score {sc:g} >= {SCORE_CRISIS:g}"
    if prev == CRISIS:
        up5 = (components.get("index_5d") or 0.0) > 0
        if sc < RECOVERY_BELOW and up5:
            return RECOVERY, (f"score {sc:g} under {RECOVERY_BELOW:g} and "
                              f"the index up over 5 days: the crisis eases")
        return CRISIS, f"crisis holds until the score is under {RECOVERY_BELOW:g} with the index rising"
    if prev == RECOVERY:
        started = None
        for r in history:
            if r.level != RECOVERY:
                break
            started = r.at
        if started and (now - started) > timedelta(days=RECOVERY_MAX_DAYS):
            return raw, f"recovery ran {RECOVERY_MAX_DAYS} days: {raw} by the score"
        if raw == CALM and _calm_confirmed():
            return CALM, "calm confirmed after the recovery"
        return RECOVERY, "recovering: risk-on longs come back in steps"
    if raw == STRESSED:
        return STRESSED, f"score {sc:g} >= {SCORE_STRESSED:g}"
    # raw calm
    if prev == STRESSED and not _calm_confirmed():
        return STRESSED, (f"calm reading; {CALM_CONFIRM} in a row over "
                          f"{CALM_CONFIRM_HOURS:g}h needed to stand down")
    return CALM, f"score {sc:g} under {SCORE_STRESSED:g}"


def override(now=None):
    """The operator's override {level, until, by} while it lasts, else None."""
    from bot_program.steward_models import StewardSetting
    now = now or timezone.now()
    row = StewardSetting.objects.filter(key=OVERRIDE_KEY).first()
    if row is None or not isinstance(row.value, dict):
        return None
    level = row.value.get("level")
    until = row.value.get("until")
    if level not in LEVELS:
        return None
    try:
        from django.utils.dateparse import parse_datetime
        until_dt = parse_datetime(until) if until else None
    except (TypeError, ValueError):
        until_dt = None
    if until_dt is not None and until_dt <= now:
        return None
    return {"level": level, "until": until, "by": row.updated_by}


def set_override(level, *, hours=24.0, by="operator", now=None):
    """level in LEVELS, or "auto" to clear. Returns the stored value."""
    from bot_program.steward_models import StewardAction, StewardSetting
    now = now or timezone.now()
    if level == "auto":
        StewardSetting.objects.filter(key=OVERRIDE_KEY).delete()
        StewardAction.objects.create(kind="posture_override",
                                     detail="override cleared: auto", by=by)
        return None
    if level not in LEVELS:
        raise ValueError(f"posture must be one of {LEVELS} or auto")
    until = (now + timedelta(hours=float(hours))).isoformat()
    value = {"level": level, "until": until}
    StewardSetting.objects.update_or_create(
        key=OVERRIDE_KEY, defaults={"value": value, "updated_by": by})
    StewardAction.objects.create(
        kind="posture_override", by=by,
        detail=f"posture forced to {level} until {until[:16]}")
    return value


def evaluate(now=None, *, save=True):
    """Read, score, step the level; store the reading. Returns it."""
    from bot_program.steward_models import MarketStressReading
    now = now or timezone.now()
    components, reasons = read_components(now)
    sc, subs = score(components)
    raw = raw_level(sc)
    history = list(MarketStressReading.objects.order_by("-at")[:12])
    prev = history[0].level if history else None
    level, why = next_level(prev, sc, raw, components, history, now)
    ov = override(now)
    reading = MarketStressReading(
        at=now, score=sc, raw_level=raw, level=(ov["level"] if ov else level),
        components={"raw": components, "sub": subs},
        reasons=[why] + reasons + ([f"operator override until {ov['until'][:16]}"]
                                   if ov else []),
        override=(ov["level"] if ov else ""))
    if save:
        reading.save()
        if prev and prev != reading.level:
            _announce(prev, reading)
    return reading


def _announce(prev, reading):
    """A posture change goes to the journal and to the operator (no money
    figure in the text: the alarm house rule)."""
    from bot_program.steward_models import StewardAction
    text = (f"Market posture: {prev.upper()} -> {reading.level.upper()} "
            f"(stress score {reading.score if reading.score is not None else 'unmeasured'}). "
            f"{POSTURE_WORDS.get(reading.level, '')}")
    StewardAction.objects.create(kind="posture", detail=text,
                                 stats={"score": reading.score,
                                        "from": prev, "to": reading.level})
    # Only an ESCALATION goes to the alarm chat (critical only, never an
    # all-is-well); standing down is in the journal and the daily report.
    rank = {CALM: 0, RECOVERY: 1, STRESSED: 2, CRISIS: 3}
    if rank.get(reading.level, 0) > rank.get(prev, 0):
        try:
            from bot_program.alarm import send_alarm
            send_alarm(f"Market posture {reading.level.upper()}",
                       [f"Was {prev}. Stress score "
                        f"{reading.score if reading.score is not None else 'unmeasured'}.",
                        POSTURE_WORDS.get(reading.level, "")])
        except Exception as e:  # noqa: BLE001 — telling is beside deciding
            logger.info("[stress] posture alarm not sent: %s", e)


POSTURE_WORDS = {
    CALM: "Business as usual.",
    STRESSED: "Risk-on longs smaller, leverage halved, stops tighter.",
    CRISIS: ("No new real-money risk-on long; shorts and safe havens keep "
             "trading; leverage capped; open risk-on longs tightened."),
    RECOVERY: "Risk-on longs come back in steps, small first.",
}


def current(now=None) -> dict:
    """{level, score, at, fresh, why}: the posture the platform obeys now.
    The override first; then the latest reading if fresh; a stale one
    holds its level for HOLD_HOURS; after that calm, said."""
    from bot_program.steward_models import MarketStressReading
    now = now or timezone.now()
    try:
        ov = override(now)
        if ov:
            return {"level": ov["level"], "score": None, "at": now,
                    "fresh": True, "why": f"operator override until {ov['until'][:16]}"}
        r = MarketStressReading.objects.order_by("-at").first()
        if r is None:
            return {"level": CALM, "score": None, "at": None, "fresh": False,
                    "why": "no stress reading yet"}
        age_h = (now - r.at).total_seconds() / 3600.0
        if age_h <= STALE_HOURS:
            return {"level": r.level, "score": r.score, "at": r.at,
                    "fresh": True, "why": (r.reasons or [""])[0]}
        if age_h <= HOLD_HOURS:
            return {"level": r.level, "score": r.score, "at": r.at,
                    "fresh": False,
                    "why": f"last reading {age_h:.1f}h old: its level holds"}
        return {"level": CALM, "score": None, "at": r.at, "fresh": False,
                "why": f"last reading {age_h:.0f}h old: calm by default"}
    except Exception as e:  # noqa: BLE001
        return {"level": CALM, "score": None, "at": None, "fresh": False,
                "why": f"posture unreadable: {type(e).__name__}"}


def recovery_days(now=None) -> float:
    """Days since the current recovery began (0 when not recovering)."""
    from bot_program.steward_models import MarketStressReading
    now = now or timezone.now()
    started = None
    for r in MarketStressReading.objects.order_by("-at")[:2000]:
        if r.level != RECOVERY:
            break
        started = r.at
    return ((now - started).total_seconds() / 86400.0) if started else 0.0
