"""THE PEOPLE'S MOOD (2026-10-16): a gauge of the real-money book, read
by code at every council sitting, shown to the Emperor at the end of THE
WAR, recorded on the sitting and graded on /council/.

The operator: "the people could be happy or not depending on PnL,
regime, etc." Seven inputs, each read from the platform's own numbers and
judged against the platform's own threshold where one exists:

  r_short          R summed over the last MOOD_SHORT_DAYS trading days
  r_long           R summed over the last MOOD_LONG_DAYS trading days
  drawdown         the fall from the book's peak (capital_truth
                   .equity_drawdown, the reader posture.drawdown_scale uses)
  streak           the current losing streak of real closes
  day_stop         the day against its stop (risk_gate.daily_loss_state)
  stress           the market's measured stress (brain.strategist
                   .measured_posture)
  open_risk_share  open risk against its ceiling (risk_gate.open_risk_state)

THE STRICT RULE: the mood may only counsel caution, never boldness. There
is no level above steady, so a good run reads steady; an input that could
not be read is said unmeasured, never calm, and a gauge with nothing
measured is "unmeasured", never steady. Nothing that sizes, gates or
sends an order reads it (tests/test_council_mood.py pins all three).

The real-money book is world "live" (dashboard.position_summary.world_of):
the R windows and the streak leave out paper and a venue's demo world.
The gates' own states (daily_loss_state, open_risk_state) count every
paper=False row, a venue's demo world included: the mood reads the very
numbers those gates refuse on, and does not correct them here, because
that would change a gate.

Pure code: no model, no AI budget, no alarm path. R, fractions and counts
only: no amount of money is kept or said.
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta, timezone as dt_tz

from django.utils import timezone

from bot_program import posture as _posture
from bot_program import share_allocator as _shares
from bot_program.asset_engine import safety as _safety
from bot_program.evidence import MIN_EVIDENCE_N

logger = logging.getLogger(__name__)

STEADY, UNEASY, RESTLESS, AFRAID = "steady", "uneasy", "restless", "afraid"
#: In order of caution. There is NO level above steady: a good run reads
#: steady, and no level argues for pressing.
MOOD_LEVELS = (STEADY, UNEASY, RESTLESS, AFRAID)
#: Nothing could be read: never steady, never calm.
UNMEASURED = "unmeasured"
#: A graded sitting from before the gauge, on /council/.
NOT_READ = "not read"

#: The two windows, in trading days (weekdays, UTC): about a week and
#: about a month. A weekend close (crypto) inside the span counts.
MOOD_SHORT_DAYS, MOOD_LONG_DAYS = 5, 20
#: The R windows: (uneasy, restless). 4R is the loss of
#: safety.DEFAULT_MAX_LOSS_STREAK full losses, where a bot's own breaker
#: stops opening; the long window doubles it. Never afraid alone.
R_SHORT_BANDS = (-2.0, -4.0)
R_LONG_BANDS = (-4.0, -8.0)
#: The fall from the peak, a fraction: the drawdown governor's knee (it
#: starts cutting), halfway down its slope, its floor (share_allocator).
DD_BANDS = (_shares.DD_KNEE, (_shares.DD_KNEE + _shares.DD_MAX) / 2,
            _shares.DD_MAX)
#: The losing streak: the posture shrinks a real entry; a bot's breaker
#: stops opening. Never afraid alone.
STREAK_BANDS = (_posture.STREAK_N, _safety.DEFAULT_MAX_LOSS_STREAK)
#: The market's measured stress (bot_program/market_stress.py LEVELS).
STRESS_BANDS = {"calm": 0, "recovery": 1, "stressed": 2, "crisis": 3}
#: Open risk as a share of its ceiling: half, three quarters, the ceiling
#: itself (where the gate refuses every new entry).
OPEN_RISK_BANDS = (0.5, 0.75, 1.0)
#: The day: half its stop spent; then the gate's own modes, "elite" past
#: the limit and "shut" past the absolute stop (risk_gate).
DAY_BANDS = (0.5,)
DAY_MODES = {"elite": 2, "shut": 3}
#: This many inputs at least uneasy at once take the mood one step up.
BREADTH_N = 3

CAUTION_ONLY = ("The mood counsels caution only: a content people is never "
                "a reason to press.")

INPUTS = ("r_short", "r_long", "drawdown", "streak", "day_stop", "stress",
          "open_risk_share")
LABELS = {
    "r_short": f"R, last {MOOD_SHORT_DAYS} trading days",
    "r_long": f"R, last {MOOD_LONG_DAYS} trading days",
    "drawdown": "fall from the book's peak",
    "streak": "losing streak of real closes",
    "day_stop": "the day against its stop",
    "stress": "market stress",
    "open_risk_share": "open risk",
}
#: What each level means, said on the page and in the reasons.
LEVEL_WORDS = {
    STEADY: "no measured input counsels caution",
    UNEASY: "an input at its first band",
    RESTLESS: "an input at its second band, or three at their first",
    AFRAID: ("a hard line is reached (the governor's floor, a market "
             "crisis, open risk at its ceiling, the day's absolute stop), or "
             "a restless reading with breadth"),
    UNMEASURED: "nothing could be read, so it is never read as calm",
}
#: Why an input sits in its band: the platform's own line, in words.
BAND_WHY = {
    "r_short": {1: f"at or under {R_SHORT_BANDS[0]:g}R",
                2: f"at or under {R_SHORT_BANDS[1]:g}R"},
    "r_long": {1: f"at or under {R_LONG_BANDS[0]:g}R",
               2: f"at or under {R_LONG_BANDS[1]:g}R"},
    "drawdown": {1: f"past the drawdown governor's {DD_BANDS[0]:.0%} knee",
                 2: f"halfway down the governor's slope, {DD_BANDS[1]:.1%}",
                 3: f"the governor at its floor, {DD_BANDS[2]:.0%} under "
                    f"the peak"},
    "streak": {1: f"the posture shrinks a real entry after "
                  f"{STREAK_BANDS[0]} losses in a row",
               2: f"a bot's own breaker stops opening after "
                  f"{STREAK_BANDS[1]}"},
    "day_stop": {1: f"{DAY_BANDS[0]:.0%} of the day's stop spent",
                 2: "past the daily stop: elite entries only",
                 3: "past the absolute stop: nothing opens"},
    "stress": {1: "recovery: risk-on longs come back in steps",
               2: "stressed: leverage halved",
               3: "crisis: no new real-money risk-on long"},
    "open_risk_share": {1: "half its ceiling",
                        2: "three quarters of its ceiling",
                        3: "at its ceiling: the gate refuses every new "
                           "entry"},
}


def _num(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


# ── pure: the bands and the level ─────────────────────────────────────────

def trading_days_start(now, n: int) -> datetime:
    """Midnight UTC of the n-th weekday back, today counted when it is a
    weekday (a Saturday's first trading day is the Friday)."""
    day = now.astimezone(dt_tz.utc).date()
    count = 0
    while True:
        if day.weekday() < 5:
            count += 1
            if count >= max(1, int(n)):
                break
        day -= timedelta(days=1)
    return datetime(day.year, day.month, day.day, tzinfo=dt_tz.utc)


def _r_band(v, bands) -> int:
    return 2 if v <= bands[1] else 1 if v <= bands[0] else 0


def input_band(name: str, value):
    """0 (calm) to 3 (afraid) for one input, or None when it is
    unmeasured. Pure. The R windows and the streak stop at 2: they are
    never a hard line alone."""
    if value is None:
        return None
    try:
        if name == "r_short":
            return _r_band(float(value), R_SHORT_BANDS)
        if name == "r_long":
            return _r_band(float(value), R_LONG_BANDS)
        if name == "drawdown":
            v = float(value)
            return (3 if v >= DD_BANDS[2] else 2 if v >= DD_BANDS[1]
                    else 1 if v >= DD_BANDS[0] else 0)
        if name == "streak":
            v = int(value)
            return (2 if v >= STREAK_BANDS[1] else 1 if v >= STREAK_BANDS[0]
                    else 0)
        if name == "day_stop":
            if not isinstance(value, dict):
                return None
            by_mode = DAY_MODES.get(str(value.get("mode") or "open"), 0)
            spent = _num(value.get("spent"))
            if spent is None:
                return by_mode or None
            return max(by_mode, 1 if spent >= DAY_BANDS[0] else 0)
        if name == "stress":
            return STRESS_BANDS.get(str(value))
        if name == "open_risk_share":
            v = float(value)
            return (3 if v >= OPEN_RISK_BANDS[2] else
                    2 if v >= OPEN_RISK_BANDS[1] else
                    1 if v >= OPEN_RISK_BANDS[0] else 0)
    except (TypeError, ValueError):
        return None
    return None


def _shown(name: str, value) -> str:
    if name in ("r_short", "r_long"):
        return f"{float(value):+.2f}R"
    if name == "drawdown":
        return f"{float(value):.1%}"
    if name == "streak":
        return f"{int(value)}"
    if name == "day_stop":
        spent = _num(value.get("spent"))
        mode = value.get("mode") or "open"
        return (f"{spent:.0%} of the daily stop spent, mode {mode}"
                if spent is not None else f"mode {mode}")
    if name == "open_risk_share":
        return f"{float(value):.0%} of its ceiling"
    return str(value)


def input_entry(name: str, value, *, shown: str = "", detail: str = "",
                why: str = "") -> dict:
    """One input as the gauge keeps it: {label, measured, reading, band,
    words}. `reading` is an R, a fraction, a count or a level word, never
    money; an unmeasured input says why in its words."""
    band = input_band(name, value)
    if band is None:
        return {"label": LABELS[name], "measured": False, "reading": None,
                "band": None,
                "words": f"unmeasured ({why or 'not read'})"}
    words = (shown or _shown(name, value)) + detail
    if band:
        words += f" ({MOOD_LEVELS[band]}: {BAND_WHY[name][band]})"
    return {"label": LABELS[name], "measured": True, "reading": value,
            "band": band, "words": words}


def mood_level(inputs: dict) -> dict:
    """{level, reasons, measured_n, of} from the inputs' bands. Pure.

    The worst band sets the level; BREADTH_N inputs at least uneasy at
    once take it one step up; afraid is the ceiling. Nothing measured is
    UNMEASURED, never steady."""
    bands = {k: (inputs.get(k) or {}).get("band") for k in INPUTS}
    measured = [k for k in INPUTS if bands[k] is not None]
    of = len(INPUTS)
    if not measured:
        return {"level": UNMEASURED, "reasons": [LEVEL_WORDS[UNMEASURED]],
                "measured_n": 0, "of": of}
    worst = max(bands[k] for k in measured)
    uneasy = [k for k in measured if bands[k] >= 1]
    broad = len(uneasy) >= BREADTH_N
    level = MOOD_LEVELS[min(len(MOOD_LEVELS) - 1, worst + (1 if broad else 0))]
    reasons = [f"{LABELS[k]}: {MOOD_LEVELS[bands[k]]} "
               f"({BAND_WHY[k][bands[k]]})" for k in uneasy]
    if broad:
        reasons.append(f"{len(uneasy)} inputs counsel caution at once: one "
                       f"step up")
    if not reasons:
        reasons = [LEVEL_WORDS[STEADY]]
    return {"level": level, "reasons": reasons, "measured_n": len(measured),
            "of": of}


def mood_of(inputs: dict, at: str = "") -> dict:
    """The whole gauge from its inputs: what a sitting stores (mood_read)."""
    out = mood_level(inputs)
    out.update({"inputs": {k: inputs[k] for k in INPUTS if k in inputs},
                "at": at})
    return out


def mood_text(mood: dict) -> str:
    """The lines the chair reads at the end of THE WAR, R and percent
    only, always ending with CAUTION_ONLY."""
    mood = mood or {}
    level = mood.get("level") or UNMEASURED
    lines = [f"  the people's mood: {level} ({int(mood.get('measured_n') or 0)}"
             f" of {int(mood.get('of') or len(INPUTS))} inputs measured)"]
    if mood.get("why"):
        lines.append(f"    {mood['why']}")
    inputs = mood.get("inputs") or {}
    for k in INPUTS:
        e = inputs.get(k)
        if isinstance(e, dict):
            lines.append(f"    {LABELS[k]}: {e.get('words') or 'not read'}")
    lines.append("  " + CAUTION_ONLY)
    return "\n".join(lines)


# ── the reads (each fenced; never raises) ─────────────────────────────────

def _closes(user, now) -> list:
    """The real-money book's closes of the long window, newest first, as
    scorecard rows (world "live": no paper, no demo world)."""
    from bot_program import scorecard
    start = trading_days_start(now, MOOD_LONG_DAYS)
    days = (now - start).total_seconds() / 86400.0 + 1.0
    rows = scorecard.rows(days=days, user=user, venue="live", world="live",
                          now=now)
    return [r for r in rows
            if r.get("closed_at") is not None and r["closed_at"] >= start]


def _r_entry(name: str, rows: list, start) -> dict:
    inside = [r for r in rows if r["closed_at"] >= start]
    priced = [float(r["r"]) for r in inside if _num(r.get("r")) is not None]
    unpriced = len(inside) - len(priced)
    if inside and not priced:
        return input_entry(name, None, why=f"every close in the window "
                                           f"unpriced ({unpriced})")
    if not inside:
        return input_entry(name, 0.0, detail=" (no real close in the "
                                             "window: a flat run)")
    detail = (f" over {len(priced)} real close"
              f"{'' if len(priced) == 1 else 's'}"
              + (f", {unpriced} unpriced left out" if unpriced else ""))
    return input_entry(name, round(sum(priced), 4), detail=detail)


def _streak_entry(rows: list) -> dict:
    """The current run of losing real closes, newest first: an unpriced
    close is stepped over (safety.check_consecutive_losses' rule), the
    first close at or above 0R ends it."""
    priced = [r for r in rows if _num(r.get("r")) is not None]
    if rows and not priced:
        return input_entry("streak", None, why=f"every close in the window "
                                               f"unpriced ({len(rows)})")
    streak = skipped = 0
    ended = False
    for r in rows:
        v = _num(r.get("r"))
        if v is None:
            skipped += 1
            continue
        if v < 0:
            streak += 1
        else:
            ended = True
            break
    if not rows:
        return input_entry("streak", 0, detail=" (no real close in the "
                                               "window)")
    shown = f"at least {streak}" if streak and not ended else f"{streak}"
    detail = f" ({skipped} unpriced skipped)" if skipped else ""
    return input_entry("streak", streak, shown=shown, detail=detail)


def _drawdown_entry(user) -> dict:
    from bot_program.capital_truth import (broker_backed, broker_env,
                                           equity_drawdown)
    acct = broker_backed(user)
    if acct is None:
        return input_entry("drawdown", None, why="no broker-backed account")
    env = broker_env(acct)
    if env != "live":
        return input_entry("drawdown", None, why=(
            "the account reads its rehearsal world (paper)" if env == "paper"
            else "the account cannot say its world"))
    dd = equity_drawdown(user)
    if not dd:
        return input_entry("drawdown", None, why="no equity reading")
    if not dd.get("n"):
        return input_entry("drawdown", None, why="one reading is no peak")
    if dd.get("stale"):
        age = _num(dd.get("age_seconds"))
        return input_entry("drawdown", None, why=(
            "the last reading is stale"
            + (f", {age / 3600:.0f}h old" if age is not None else "")))
    v = _num(dd.get("drawdown_pct"))
    if v is None:
        return input_entry("drawdown", None, why="no fall measured")
    return input_entry("drawdown", round(max(0.0, v), 4))


def _day_entry(user, now) -> dict:
    from portfolio.risk_gate import daily_loss_state
    st = daily_loss_state(user, now=now, venue="live")
    limit = _num(st.get("limit_pct"))
    book = _num(st.get("book_value"))
    lost = _num(st.get("realized"))
    mode = str(st.get("mode") or "open")
    if limit is None or limit <= 0:
        return input_entry("day_stop", None,
                           why="no daily-loss limit set on the book")
    if not book:
        return input_entry("day_stop", None, why="no book value")
    if lost is None and mode not in DAY_MODES:
        return input_entry("day_stop", None,
                           why="the day's closes carry no price")
    spent = (None if lost is None
             else round(max(0.0, -lost / book / (limit / 100.0)), 4))
    return input_entry("day_stop", {"spent": spent, "mode": mode})


def _stress_entry(now) -> dict:
    from brain.strategist import UNMEASURED as NOT_MEASURED
    from brain.strategist import measured_posture
    m = measured_posture(now)
    if not m.get("crisis_mode_on"):
        return input_entry("stress", None, why="crisis mode OFF: unmeasured")
    word = str(m.get("level") or "")
    raw = str(m.get("raw_level") or "")
    if not word or word == NOT_MEASURED:
        return input_entry("stress", None, why="no fresh stress reading")
    if word.endswith("(override)") and raw == "calm":
        return input_entry("stress", None, why=(
            "a calm override: calm is only read from a measurement"))
    if raw not in STRESS_BANDS:
        return input_entry("stress", None, why="a level the gauge does not "
                                               "know")
    return input_entry("stress", raw, shown=word[:60])


def _open_risk_entry(user) -> dict:
    # Only the share is kept: the state's own reason prints money and is
    # never read here.
    from portfolio.risk_gate import open_risk_state
    st = open_risk_state(user, venue="live")
    limit = _num(st.get("limit_pct"))
    book = _num(st.get("book_value"))
    if limit is None or limit <= 0:
        return input_entry("open_risk_share", None,
                           why="no open-risk limit set on the book")
    if not book:
        return input_entry("open_risk_share", None, why="no book value")
    of_book = (_num(st.get("open_risk")) or 0.0) / book
    share = of_book / (limit / 100.0)
    return input_entry("open_risk_share", round(share, 4),
                       shown=(f"{of_book:.1%} of the book, {share:.0%} of "
                              f"its {limit:g}% ceiling"))


def _fence(name: str, fn) -> dict:
    try:
        return fn()
    except Exception as e:  # noqa: BLE001 — an unread input is said
        logger.info("[council mood] %s unread: %s", name, e)
        return input_entry(name, None, why=f"not read ({type(e).__name__})")


def read_inputs(user, now=None) -> dict:
    """{input: entry} for the seven inputs, each read on its own and
    fenced: one that fails is unmeasured, never calm."""
    now = now or timezone.now()
    out = {}
    try:
        rows = _closes(user, now)
        err = ""
    except Exception as e:  # noqa: BLE001
        logger.info("[council mood] closes unread: %s", e)
        rows, err = None, type(e).__name__
    for name, days in (("r_short", MOOD_SHORT_DAYS),
                       ("r_long", MOOD_LONG_DAYS)):
        start = trading_days_start(now, days)
        out[name] = (input_entry(name, None, why=f"not read ({err})")
                     if rows is None else
                     _fence(name, lambda n=name, s=start: _r_entry(n, rows, s)))
    out["streak"] = (input_entry("streak", None, why=f"not read ({err})")
                     if rows is None else
                     _fence("streak", lambda: _streak_entry(rows)))
    out["drawdown"] = _fence("drawdown", lambda: _drawdown_entry(user))
    out["day_stop"] = _fence("day_stop", lambda: _day_entry(user, now))
    out["stress"] = _fence("stress", lambda: _stress_entry(now))
    out["open_risk_share"] = _fence("open_risk_share",
                                    lambda: _open_risk_entry(user))
    return out


def people_mood(user, now=None) -> dict:
    """{level, reasons, inputs, measured_n, of, at}: the gauge for one
    owner's real-money book. Never raises on a read (each is fenced)."""
    now = now or timezone.now()
    return mood_of(read_inputs(user, now), at=now.isoformat())


def unmeasured_mood(why: str) -> dict:
    """The gauge when it could not be read at all: unmeasured, said."""
    return {"level": UNMEASURED, "reasons": [LEVEL_WORDS[UNMEASURED]],
            "inputs": {}, "measured_n": 0, "of": len(INPUTS), "at": "",
            "why": why[:200]}


# ── graded: what the argued trades returned under each mood ───────────────

def mood_outcomes(since) -> list:
    """One row per level (and "not read"), over the live sittings graded
    since `since` with an R: how many, their average R, how often they won
    and how much the Emperor committed. A level with fewer than
    MIN_EVIDENCE_N sittings is thin. If the mood predicts nothing, the
    rows will not differ: the page shows it."""
    from django.apps import apps
    session_model = apps.get_model("ai_agents", "CouncilSession")
    voice_model = apps.get_model("ai_agents", "CouncilVoice")
    rows = list(session_model.objects
                .filter(venue="live", truth_r__isnull=False,
                        graded_at__gte=since)
                .exclude(status="record")
                .values("id", "mood", "truth_r", "y"))
    commits = {}
    for sid, answer in (voice_model.objects
                        .filter(voice="emperor", status="spoke",
                                session__venue="live",
                                session__truth_r__isnull=False,
                                session__graded_at__gte=since)
                        .values_list("session_id", "answer")):
        c = _num((answer or {}).get("commit"))
        if c is not None:
            commits[sid] = c
    out = []
    for level in MOOD_LEVELS + (UNMEASURED, NOT_READ):
        key = "" if level == NOT_READ else level
        rs = [r for r in rows if (r["mood"] or "") == key]
        n = len(rs)
        avg = sum(float(r["truth_r"]) for r in rs) / n if n else None
        ys = [r["y"] for r in rs if r["y"] is not None]
        won = 100.0 * sum(ys) / len(ys) if ys else None
        cs = [commits[r["id"]] for r in rs if r["id"] in commits]
        commit = 100.0 * sum(cs) / len(cs) if cs else None
        out.append({
            "level": level, "n": n, "avg_r": avg, "won_pct": won,
            "commit_pct": commit, "thin": n < MIN_EVIDENCE_N,
            "not_read": level == NOT_READ,
            "avg_r_text": f"{avg:+.2f}R" if avg is not None else "none",
            "won_text": f"{won:.0f}%" if won is not None else "none",
            "commit_text": (f"{commit:.0f}%" if commit is not None
                            else "none")})
    return out
