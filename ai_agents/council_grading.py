"""THE COUNCIL's grader and its weights (2026-10-08).

Every voice is graded on what the market did next, and its record is its
only weight: no voice is trusted by assertion.

THE TRUTH of a sitting (grade_due, run inside the 03:30 calibration task,
ai_agents/tasks.py: resolve_pending_calibrations):
  - a sent trade is judged by its own realized R (bot_grading);
  - anything else (a candidate refused after the debate, a ticket nobody
    took, a trade still open after COUNCIL_MAX_WAIT_DAYS, an unpriced
    close, a ticket whose levels moved) is judged by walking its own
    bracket over the bars with the capital desk's walk_bracket and
    _decision_bars (bot_program/capital_desk.py), minus the round trip
    in R, so a replay pays what a real trade pays.

THE HAND OF THE EMPEROR (hand_of, 2026-10-16): the seat each (regime,
class) gives the voice with the best measured weight there; the
Emperor's overrulings of it are graded (against_hand).

THE WEIGHT (voice_weight): the house's Brier bands (trust_from_brier,
ai_agents/calibration.py) over ONE weight claim per voice per sitting
(the common event p_work, or the Skeptic's attack), read per (regime,
class) down a four-rung ladder, neutral 1.00 until COUNCIL_MIN_N graded
calls. The voice's Brier is scored AGAINST THE BASE RATE of its own
rung (2026-10-16): always saying the base rate b scores b(1 - b), which
is 0.25 only on an even base rate, so the bands read 0.25 x Brier /
b(1 - b). A voice with no discrimination weighs exactly 1.00 at any base
rate; a perfect one still weighs 1.30; a rung whose outcomes were all
alike measures no skill and weighs 1.00, said. The weight is computed
and shown, and the Emperor reads it. Nothing else does: no sizing, no
gate, no debate binding.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from django.db.models import Count, Q, Sum
from django.utils import timezone

from ai_agents.agents import council as C
from ai_agents.calibration import trust_from_brier

logger = logging.getLogger(__name__)

WEIGHT_KINDS = ("work", "attack")
#: Sessions graded per pass, oldest first.
SESSION_BATCH = 500
#: A sitting queued or sitting longer than this never finished.
STUCK_SITTING_MIN = 30
#: A voice still "asked" after this long is silent ("timeout").
STUCK_VOICE_HOURS = 1
#: A direction call or a theory still pending after this long is
#: unresolvable.
CLAIM_MAX_PENDING_DAYS = 60
#: A not-sent candidate is judged not sent only after this long: the row
#: an order writes lands in the same call as the debate.
NOT_SENT_AFTER = timedelta(hours=1)

PRICE_FIXES = ("stop", "target", "entry", "timing")


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _y(r):
    if r is None:
        return None
    if r >= C.COUNCIL_NOISE_R:
        return 1
    if r <= -C.COUNCIL_NOISE_R:
        return 0
    return None


# ── the replay ────────────────────────────────────────────────────────────

def cost_r(cost_fraction, price, stop) -> float:
    """The round trip in R: cost_fraction x price / |price - stop|."""
    price, stop = _f(price), _f(stop)
    if price is None or stop is None or abs(price - stop) <= 0:
        return 0.0
    return float(cost_fraction or 0.0) * price / abs(price - stop)


def _walk(side, price, stop, target, bars, cost_fraction):
    """walk_bracket minus the round trip, or None when there is no risk to
    measure. No bars after the fill marks the leg flat."""
    from bot_program.capital_desk import walk_bracket
    if not bars:
        return 0.0
    r, _outcome = walk_bracket(direction=side, price=price, stop=stop,
                               target=target, bars=bars)
    if r is None:
        return None
    return r - cost_r(cost_fraction, price, stop)


def replay_leg(symbol, side, entry, stop, target, start, end,
               cost_fraction=0.0, bars=None):
    """(r, outcome) for one bracket walked over [start, end], minus the
    round trip, or None (no bars, or no risk). The desk's rules hold: the
    finest of 1h, 4h and 1d with any bar in the window; a bar touching both
    levels is a stop; neither touched is marked to market at the last bar.
    `target=None` is allowed."""
    from bot_program.capital_desk import _decision_bars, walk_bracket
    if bars is None:
        _tf, bars = _decision_bars(symbol, start, end)
    if not bars:
        return None
    r, outcome = walk_bracket(direction=side, price=entry, stop=stop,
                              target=target, bars=bars)
    if r is None:
        return None
    return r - cost_r(cost_fraction, entry, stop), outcome


class _Legs:
    """The session's bars over [t0, t0 + H], read once, and its own replay
    (R_now): the comparison claims compare replayed legs with replayed
    legs."""

    def __init__(self, session, now):
        self.s = session
        self.now = now
        self.t0 = session.created_at
        self.end = self.t0 + timedelta(hours=float(session.horizon_hours
                                                   or C.COUNCIL_HORIZON_DEFAULT_H))
        self._bars = None

    @property
    def due(self):
        return self.now >= self.end

    @property
    def lapsed(self):
        return self.now >= self.end + timedelta(hours=C.COUNCIL_GRACE_H)

    def bars(self):
        if self._bars is None:
            from bot_program.capital_desk import _decision_bars
            _tf, rows = _decision_bars(self.s.symbol, self.t0, self.end)
            self._bars = [(ts, _f(h), _f(lo), _f(c)) for ts, h, lo, c in rows]
        return self._bars

    def state(self):
        """"ready", "wait" or "none" (no bars past the grace)."""
        if self.s.entry is None or self.s.stop is None:
            return "none"
        if not self.due:
            return "wait"
        if self.bars():
            return "ready"
        return "none" if self.lapsed else "wait"

    def r_now(self):
        s = self.s
        return _walk(s.side, s.entry, s.stop, s.target, self.bars(),
                     s.cost_fraction)


# ── the truth of a session ────────────────────────────────────────────────

def _truth(session, legs, now) -> dict:
    """{"state": "ready", "r", "kind", "notes"} | {"state": "wait"} |
    {"state": "none", "notes"}."""
    t = session.trade
    if t is not None:
        ticket_moved = session.origin == "ticket" and session.levels_match \
            is not True
        if ticket_moved:
            reason = ("levels moved" if session.levels_match is False
                      else "levels not checked")
        elif t.status == "CLOSED" and t.realized_r is not None:
            return {"state": "ready", "r": float(t.realized_r),
                    "kind": "realized", "notes": "realized"}
        elif t.status in ("OPEN", "CLOSE_PENDING"):
            opened = t.opened_at or session.created_at
            if now - opened < timedelta(days=C.COUNCIL_MAX_WAIT_DAYS):
                return {"state": "wait"}
            reason = f"still open after {C.COUNCIL_MAX_WAIT_DAYS} days"
        elif t.status == "CLOSED":
            reason = "realized R unpriced"
        else:
            reason = "never filled"
    else:
        reason = "not sent" if session.origin == "bot" else "not taken"
    st = legs.state()
    if st == "wait":
        return {"state": "wait"}
    if st == "none":
        return {"state": "none", "notes": f"{reason}; no bars"
                if session.entry is not None else f"{reason}; no levels"}
    r = legs.r_now()
    if r is None:
        return {"state": "none", "notes": f"{reason}; no risk to measure"}
    return {"state": "ready", "r": r, "kind": "replay",
            "notes": f"replayed: {reason}"}


# ── links ─────────────────────────────────────────────────────────────────

def _levels_match(session, trade) -> bool:
    meta = trade.metadata or {}
    stop = _f(meta.get("initial_stop_loss")) or _f(trade.stop_loss)
    target = _f(trade.take_profit)
    ok = True
    for asked, got in ((session.stop, stop), (session.target, target)):
        if asked is None or got is None:
            return False
        if abs(got - asked) > 0.001 * abs(asked):
            ok = False
    return ok


#: A row booked in eToro's DEMO world (a live config with Demo ticked on
#: /brokers/ stamps metadata broker_env "paper", manual_trade.venue_stamps):
#: never linked, so a rehearsal never grades into the live record. Written
#: with has_key, as manage.py council --backfill-debates writes it, so a
#: row with no stamp at all is never excluded by a NULL comparison.
_DEMO_WORLD = (Q(metadata__has_key="broker_env")
               & Q(metadata__broker_env="paper"))


#: Why a record whose order filled in a rehearsal world is closed ungraded.
REHEARSAL_NOTES = ("a rehearsal fill (paper, or the venue's demo or SIM "
                   "world): not real money, not graded")
#: Why a debate argued on a rehearsal client (stamped venue "demo" by
#: open_debate_session, 2026-10-16) is closed ungraded, sent or not.
REHEARSAL_ARGUED_NOTES = ("argued on a rehearsal client (the venue's demo, "
                          "SIM, practice or paper world): not real money, "
                          "not graded")


def close_rehearsal(session_id, now=None, *, notes=REHEARSAL_NOTES,
                    why="the order filled in a rehearsal world") -> int:
    """Close a record whose order filled in a rehearsal world (paper, or a
    venue's demo / SIM / practice world, dashboard.position_summary
    .world_of), or that was argued on a rehearsal client: its pending
    claims are ungraded and the session is graded with `notes`, so a
    simulator never moves a live weight and is never replayed as "not
    sent". Returns the claims closed."""
    from ai_agents.council_models import CouncilClaim, CouncilSession
    now = now or timezone.now()
    n = CouncilClaim.objects.filter(
        session_id=session_id, grade="pending").update(
        grade="ungraded", grade_notes=notes[:300], graded_at=now)
    CouncilSession.objects.filter(id=session_id, graded_at__isnull=True
                                  ).update(graded_at=now,
                                           grade_notes=notes[:300])
    CouncilSession.objects.filter(id=session_id, why="").update(why=why)
    return n


def _link(session, now) -> str:
    """Link the session to its row. Answers "rehearsal" when a bot
    record's only rows filled in a rehearsal world, else ""."""
    from bot_program.models import AssetBotTrade
    from dashboard.position_summary import world_of
    if session.trade_id is not None:
        return ""
    if session.origin == "bot":
        rows = list(AssetBotTrade.objects
                    .filter(metadata__debate__council_id=session.id)
                    .order_by("id")[:10])
        row = next((r for r in rows if world_of(r) == "live"), None)
        if row is not None:
            session.trade = row
            session.linked_by = "meta"
            session.save(update_fields=["trade", "linked_by"])
            return ""
        return "rehearsal" if rows else ""
    if session.origin == "ticket" and session.user_id:
        from bot_program.manual_trade import MANUAL_RULE
        from ai_agents.council_models import CouncilSession
        taken = set(CouncilSession.objects.filter(
            trade__isnull=False, origin="ticket",
            user_id=session.user_id).values_list("trade_id", flat=True))
        row = (AssetBotTrade.objects
               .filter(config__user_id=session.user_id,
                       rule_name=MANUAL_RULE, paper=False,
                       symbol=session.symbol, side=session.side,
                       opened_at__gte=session.created_at,
                       opened_at__lte=session.created_at + timedelta(
                           minutes=C.COUNCIL_LINK_WINDOW_MIN))
               .exclude(id__in=taken).exclude(_DEMO_WORLD)
               .order_by("opened_at").first())
        if row is not None:
            session.trade = row
            session.linked_by = "time"
            session.levels_match = _levels_match(session, row)
            session.save(update_fields=["trade", "linked_by",
                                        "levels_match"])
    return ""


# ── grading one claim ─────────────────────────────────────────────────────

def _set(c, now, grade, *, y=None, brier=None, r=None, value_r=None,
         notes=""):
    c.grade = grade
    c.y = y
    c.brier = None if brier is None else round(brier, 6)
    c.r = None if r is None else round(r, 6)
    c.value_r = None if value_r is None else round(value_r, 6)
    if notes:
        c.grade_notes = notes[:300]
    c.graded_at = now
    c.save(update_fields=["grade", "y", "brier", "r", "value_r",
                          "grade_notes", "graded_at"])


def _band(value, *, notes=""):
    """right / wrong / unresolvable for a value_r or an R against the
    noise band."""
    if value >= C.COUNCIL_NOISE_R:
        return "right"
    if value <= -C.COUNCIL_NOISE_R:
        return "wrong"
    return "unresolvable"


def _grade_truth_claim(c, R, now) -> None:
    """work, stance, boldness, battle and the size fix: R alone decides."""
    p = c.p
    payload = c.payload or {}
    y = _y(R)
    if c.kind == "work":
        if p is None:
            _set(c, now, "ungraded", r=R, notes="no probability given")
        elif y is None:
            _set(c, now, "unresolvable", r=R,
                 notes="inside a quarter R either way")
        else:
            # 0.5 is "cannot tell" (COUNCIL_LAW): its Brier of 0.25 counts
            # in the weight, but it took no side, so it is neither right
            # nor wrong, and no attack on it can be right.
            g = ("unresolvable" if p == 0.5
                 else "right" if abs(p - y) < 0.5 else "wrong")
            _set(c, now, g, y=y, brier=(p - y) ** 2, r=R,
                 notes="0.5: no side taken" if p == 0.5 else "")
        return
    if c.kind == "stance":
        value_r = None
        if c.voice_key == "executioner":
            v = payload.get("verdict")
            scale = _f(payload.get("scale")) or 1.0
            value_r = (-R if v == "veto" else -(1.0 - scale) * R
                       if v == "cut" else 0.0)
        g = _band(R if c.stance == "for" else -R)
        _set(c, now, g, y=None if g == "unresolvable" else int(g == "right"),
             r=R, value_r=value_r,
             notes="" if g != "unresolvable" else
             "inside a quarter R either way")
        return
    if c.kind == "boldness":
        if R >= C.COUNCIL_ALL_IN_WIN_R:
            _set(c, now, "right", y=1, r=R)
        elif R < 0:
            _set(c, now, "wrong", y=0, r=R)
        else:
            _set(c, now, "unresolvable", r=R,
                 notes="won, but less than its full risk")
        return
    if c.kind == "battle":
        commit = _f(payload.get("commit"))
        commit = 1.0 if commit is None else commit
        value_r = (commit - 1.0) * R
        if commit >= 1.0:
            g = _band(R)
        else:
            g = _band(-R)
        _set(c, now, g, y=None if g == "unresolvable" else int(g == "right"),
             r=R, value_r=value_r)
        return
    if c.kind == "fix" and payload.get("kind") == "size":
        k = _f(payload.get("value")) or 1.0
        value_r = (k - 1.0) * R
        g = _band(value_r)
        _set(c, now, g, y=None if g == "unresolvable" else int(g == "right"),
             r=R, value_r=value_r)
        return
    _set(c, now, "ungraded", notes=f"no grader for {c.kind}")


def _first_touch(bars, level, start, end):
    for i, (ts, hi, lo, _c) in enumerate(bars):
        if ts < start or ts > end:
            continue
        if lo is not None and hi is not None and lo <= level <= hi:
            return i
    return None


def _walk_from_fill(side, fill, stop, target, bars, idx, cost):
    """The waited leg filled in bar `idx`: a stop that same bar touched
    wins, as walk_bracket rules a bar that holds both levels ("the stop
    wins"); otherwise the walk runs from the next bar. None when there is
    no risk to measure."""
    fill, stop = _f(fill), _f(stop)
    if fill is None or stop is None or abs(fill - stop) <= 0:
        return None
    _ts, hi, lo, _c = bars[idx]
    buy = str(side).upper() != "SELL"
    stopped = ((lo is not None and lo <= stop) if buy
               else (hi is not None and hi >= stop))
    if stopped:
        return -1.0 - cost_r(cost, fill, stop)
    return _walk(side, fill, stop, target, bars[idx + 1:], cost)


def _grade_leg_claim(c, legs, now) -> None:
    """trigger and the price-level fixes: replayed legs against R_now."""
    s = legs.s
    payload = c.payload or {}
    bars = legs.bars()
    r_now = legs.r_now()
    if r_now is None:
        _set(c, now, "unresolvable", notes="no risk to measure")
        return
    cost = s.cost_fraction
    if c.kind == "trigger":
        level = _f(payload.get("level"))
        hours = _f(payload.get("within_hours")) or 0.0
        idx = _first_touch(bars, level, legs.t0,
                           legs.t0 + timedelta(hours=hours))
        if idx is None:
            r_wait = 0.0
            g = ("right" if r_now <= -C.COUNCIL_NOISE_R else "wrong"
                 if r_now >= C.COUNCIL_NOISE_R else "unresolvable")
            note = "never fired"
        else:
            r_wait = _walk_from_fill(s.side, level, s.stop, s.target, bars,
                                     idx, cost)
            if r_wait is None:
                _set(c, now, "unresolvable", notes="no risk at the trigger")
                return
            g = _band(r_wait - r_now)
            note = "fired"
        _set(c, now, g, y=None if g == "unresolvable" else int(g == "right"),
             r=r_now, value_r=r_wait - r_now, notes=note)
        return
    kind = payload.get("kind")
    value = _f(payload.get("value"))
    hours = _f(payload.get("valid_hours"))
    if kind == "stop":
        r_fix = _walk(s.side, s.entry, value, s.target, bars, cost)
    elif kind == "target":
        r_fix = _walk(s.side, s.entry, s.stop, value, bars, cost)
    elif kind == "entry":
        idx = _first_touch(bars, value, legs.t0,
                           legs.t0 + timedelta(hours=hours or 0.0))
        r_fix = 0.0 if idx is None else _walk_from_fill(
            s.side, value, s.stop, s.target, bars, idx, cost)
    elif kind == "timing":
        at = legs.t0 + timedelta(hours=hours or 0.0)
        idx = next((i for i, b in enumerate(bars) if b[0] >= at), None)
        if idx is None:
            _set(c, now, "unresolvable", notes="no bar at the named hour")
            return
        from bot_program.capital_desk import CF_STOP, CF_TARGET, walk_bracket
        _r, outcome = walk_bracket(direction=s.side, price=s.entry,
                                   stop=s.stop, target=s.target,
                                   bars=bars[:idx + 1])
        close = bars[idx][3]
        buy = str(s.side).upper() != "SELL"
        beyond = close is None or (
            (buy and (close <= s.stop or (s.target and close >= s.target)))
            or (not buy and (close >= s.stop
                             or (s.target and close <= s.target))))
        if outcome in (CF_STOP, CF_TARGET) or beyond:
            _set(c, now, "ungraded",
                 notes="the levels were gone at the named hour")
            return
        r_fix = _walk(s.side, close, s.stop, s.target, bars[idx + 1:], cost)
    else:
        _set(c, now, "ungraded", notes=f"no grader for a {kind} fix")
        return
    if r_fix is None:
        _set(c, now, "unresolvable", notes="no risk to measure")
        return
    value_r = r_fix - r_now
    g = _band(value_r)
    _set(c, now, g, y=None if g == "unresolvable" else int(g == "right"),
         r=r_now, value_r=value_r)


def _grade_touch(c, s, now) -> None:
    from bot_program.capital_desk import _decision_bars
    payload = c.payload or {}
    level = _f(payload.get("level"))
    hours = _f(payload.get("within_hours")) or 0.0
    t0 = s.created_at
    end = t0 + timedelta(hours=hours)
    _tf, rows = _decision_bars(s.symbol, t0, end)
    bars = [(ts, _f(h), _f(lo), _f(cl)) for ts, h, lo, cl in rows]
    if _first_touch(bars, level, t0, end) is not None:
        _set(c, now, "right", y=1, notes="touched")
        return
    if now < end:
        return
    if bars:
        _set(c, now, "wrong", y=0, notes="not touched in the window")
    elif now >= end + timedelta(hours=C.COUNCIL_GRACE_H):
        _set(c, now, "unresolvable", notes="no bars")


def _grade_direction(c, now) -> None:
    pred = c.prediction
    old = now - c.created_at >= timedelta(days=CLAIM_MAX_PENDING_DAYS)
    if pred is None:
        if old:
            _set(c, now, "unresolvable", notes="no call was registered")
        return
    p = c.p if c.p is not None else _f(pred.confidence)
    if pred.was_correct is True:
        _set(c, now, "right", y=1, brier=None if p is None else (p - 1) ** 2,
             notes=pred.evaluation_notes or "")
    elif pred.was_correct is False:
        _set(c, now, "wrong", y=0, brier=None if p is None else p ** 2,
             notes=pred.evaluation_notes or "")
    elif str(pred.actual_value or "").startswith("ungradeable"):
        _set(c, now, "unresolvable", notes=str(pred.actual_value))
    elif old:
        _set(c, now, "unresolvable",
             notes=f"still pending after {CLAIM_MAX_PENDING_DAYS} days")


def _grade_theory(c, now) -> None:
    hyp = c.hypothesis
    old = now - c.created_at >= timedelta(days=CLAIM_MAX_PENDING_DAYS)
    if hyp is None:
        if old:
            _set(c, now, "unresolvable", notes="no theory was posted")
        return
    p = c.p
    if hyp.outcome == "confirmed":
        _set(c, now, "right", y=1, brier=None if p is None else (p - 1) ** 2,
             notes=hyp.resolution_notes or "")
    elif hyp.outcome == "refuted":
        _set(c, now, "wrong", y=0, brier=None if p is None else p ** 2,
             notes=hyp.resolution_notes or "")
    elif hyp.outcome == "unresolvable":
        _set(c, now, "unresolvable", notes=hyp.resolution_notes or "")
    elif old:
        _set(c, now, "unresolvable",
             notes=f"still pending after {CLAIM_MAX_PENDING_DAYS} days")


def _grade_attack(c, session, now) -> None:
    """The Skeptic is right when the voice he attacked was wrong: its
    stance claim, else its work claim, in the same sitting."""
    target = (c.payload or {}).get("target")
    others = [x for x in session.claims.filter(voice_key=target)
              if x.kind in ("stance", "work")]
    pick = ([x for x in others if x.kind == "stance"]
            or [x for x in others if x.kind == "work"])
    p = c.p
    if not pick:
        _set(c, now, "unresolvable",
             notes="the voice he attacked made no graded claim")
        return
    t = pick[0]
    if t.grade == "pending":
        return
    if t.grade == "wrong":
        _set(c, now, "right", y=1, brier=None if p is None else (p - 1) ** 2,
             notes=f"{target}'s {t.kind} claim was wrong")
    elif t.grade == "right":
        _set(c, now, "wrong", y=0, brier=None if p is None else p ** 2,
             notes=f"{target}'s {t.kind} claim was right")
    else:
        _set(c, now, "unresolvable",
             notes=f"{target}'s {t.kind} claim is {t.grade}")


# ── one session ───────────────────────────────────────────────────────────

TRUTH_KINDS = ("work", "stance", "boldness", "battle")


def grade_session(session, now=None) -> int:
    """Grade what can be graded now; return the number of claims graded.
    Idempotent: only pending claims are touched."""
    from ai_agents.council_models import CouncilSession
    now = now or timezone.now()
    if (session.venue or "live") != "live":
        # a debate argued on a rehearsal client (a SIM, practice or paper
        # client, 2026-10-16): sent or not, never graded as real money and
        # never replayed as "not sent" into the live weights
        n = close_rehearsal(session.id, now, notes=REHEARSAL_ARGUED_NOTES,
                            why="argued on a rehearsal client: not real "
                                "money")
        session.graded_at, session.grade_notes = (now,
                                                  REHEARSAL_ARGUED_NOTES[:300])
        return n
    if _link(session, now) == "rehearsal":
        # the debate's record of an order that filled in a rehearsal world
        # (a SIM, practice or demo client the debate argued): closed
        # ungraded, never replayed as "not sent" into the live weights
        n = close_rehearsal(session.id, now)
        session.graded_at, session.grade_notes = now, REHEARSAL_NOTES[:300]
        return n
    pending = list(session.claims.filter(grade="pending")
                   .select_related("prediction", "hypothesis"))
    before = len(pending)
    # A not-sent candidate argued again inside the hold window: the
    # shadow debate re-argues it every tick; each billed debate keeps its
    # record, but only the first is graded.
    if (session.origin == "bot" and session.trade_id is None
            and now - session.created_at >= NOT_SENT_AFTER):
        # live records only: a rehearsal's record never makes a live one a
        # repeat (2026-10-16)
        prev = (CouncilSession.objects
                .filter(origin="bot", trade__isnull=True, venue="live",
                        config_id=session.config_id, symbol=session.symbol,
                        side=session.side, rule_name=session.rule_name,
                        created_at__lt=session.created_at,
                        created_at__gte=session.created_at - timedelta(
                            hours=C.COUNCIL_REPEAT_HOURS))
                .exclude(id=session.id).order_by("-created_at").first())
        if prev is not None:
            for c in pending:
                _set(c, now, "ungraded", notes=f"a repeat of session #{prev.id}")
            session.graded_at = now
            session.grade_notes = f"a repeat of session #{prev.id}"
            session.save(update_fields=["graded_at", "grade_notes"])
            return before

    legs = _Legs(session, now)
    truth = None
    if session.origin == "bot" and session.trade_id is None \
            and now - session.created_at < NOT_SENT_AFTER:
        truth = {"state": "wait"}
    else:
        truth = _truth(session, legs, now)
    if truth["state"] == "ready":
        session.truth = truth["kind"]
        session.truth_r = round(truth["r"], 6)
        session.y = _y(truth["r"])
        session.grade_notes = truth["notes"][:300]
    if legs.state() == "ready":
        rep = legs.r_now()
        if rep is not None:
            session.replay_r = round(rep, 6)
            from bot_program.capital_desk import walk_bracket
            _r, outcome = walk_bracket(direction=session.side,
                                       price=session.entry,
                                       stop=session.stop,
                                       target=session.target,
                                       bars=legs.bars())
            session.replay_outcome = outcome or ""

    for c in pending:
        if c.kind == "attack":
            continue
        try:
            if c.kind == "direction":
                _grade_direction(c, now)
            elif c.kind == "theory":
                _grade_theory(c, now)
            elif c.kind == "touch":
                _grade_touch(c, session, now)
            elif c.kind == "trigger" or (
                    c.kind == "fix"
                    and (c.payload or {}).get("kind") in PRICE_FIXES):
                st = legs.state()
                if st == "ready":
                    _grade_leg_claim(c, legs, now)
                elif st == "none":
                    _set(c, now, "unresolvable", notes="no bars")
            else:
                if truth["state"] == "ready":
                    _grade_truth_claim(c, truth["r"], now)
                elif truth["state"] == "none":
                    _set(c, now, "unresolvable", notes=truth.get("notes", ""))
        except Exception as e:  # noqa: BLE001 — one claim, said
            logger.warning("[council] claim #%s not graded: %s", c.id, e)
    for c in pending:
        if c.kind == "attack" and c.grade == "pending":
            _grade_attack(c, session, now)

    left = session.claims.filter(grade="pending").count()
    graded = before - left
    if left == 0:
        session.graded_at = now
    if truth["state"] == "none" and not session.grade_notes:
        session.grade_notes = truth.get("notes", "")[:300]
    session.save(update_fields=["truth", "truth_r", "y", "replay_r",
                                "replay_outcome", "graded_at",
                                "grade_notes"])
    return graded


def _settle_stuck(now) -> int:
    from ai_agents.council_models import CouncilSession, CouncilVoice
    n = 0
    old = now - timedelta(minutes=STUCK_SITTING_MIN)
    for s in CouncilSession.objects.filter(
            status__in=(CouncilSession.QUEUED, CouncilSession.SITTING),
            created_at__lt=old):
        why = ("never sat: the queue did not take it"
               if s.status == CouncilSession.QUEUED
               else "the sitting did not finish")
        n += CouncilSession.objects.filter(id=s.id, status=s.status).update(
            status=CouncilSession.SILENT, why=why, finished_at=now)
    CouncilVoice.objects.filter(
        status=CouncilVoice.ASKED,
        created_at__lt=now - timedelta(hours=STUCK_VOICE_HOURS)).update(
        status=CouncilVoice.SILENT, why="timeout")
    return n


def grade_due(now=None) -> dict:
    """The nightly pass: settle stuck sittings, link, grade. Never raises
    for one session; the caller fences the whole."""
    from ai_agents.council_models import CouncilSession
    now = now or timezone.now()
    out = {"sessions": 0, "graded": 0, "claims": 0, "stuck": 0, "failed": 0}
    out["stuck"] = _settle_stuck(now)
    qs = (CouncilSession.objects.filter(graded_at__isnull=True)
          .exclude(status__in=(CouncilSession.QUEUED,
                               CouncilSession.SITTING))
          .select_related("trade").order_by("created_at")[:SESSION_BATCH])
    for s in qs:
        out["sessions"] += 1
        try:
            out["claims"] += grade_session(s, now)
            if s.graded_at is not None:
                out["graded"] += 1
        except Exception as e:  # noqa: BLE001
            out["failed"] += 1
            logger.warning("[council] session #%s not graded: %s", s.id, e)
    return out


# ── the weights ───────────────────────────────────────────────────────────

def _cells(now):
    """{(voice, regime, class): (n, sum of brier, sum of y)} over the live
    weight claims of the record window. ONE aggregate query. The sum of y
    is the cell's base rate times n: how often the event the voice
    forecast came true (the trade won; for the Skeptic, his target was
    wrong)."""
    from ai_agents.council_models import CouncilClaim
    rows = (CouncilClaim.objects
            .filter(kind__in=WEIGHT_KINDS, venue="live", y__isnull=False,
                    brier__isnull=False,
                    graded_at__gte=now - timedelta(days=C.COUNCIL_RECORD_DAYS))
            .values("voice_key", "regime", "asset_class")
            .annotate(n=Count("id"), s=Sum("brier"), ys=Sum("y")))
    return {(r["voice_key"], r["regime"], r["asset_class"]):
            (int(r["n"]), float(r["s"] or 0.0), float(r["ys"] or 0.0))
            for r in rows}


def skill_factor(n, brier_sum, y_sum):
    """(factor, brier, base_rate, reference) for n graded weight calls.

    The house's bands, read against the base rate: always forecasting the
    base rate b scores Brier b(1 - b) (the reference), so the bands read
    0.25 x Brier / reference. No discrimination maps to exactly 1.00 at
    any base rate (decision 10, amended 2026-10-16: the raw bands were
    neutral only on a near-even base rate, and a voice that always said
    "no" in a losing cell read as earned trust). A reference of 0 (every
    outcome alike) measures no skill: 1.00."""
    b = brier_sum / n
    ybar = y_sum / n
    ref = ybar * (1.0 - ybar)
    # rounded before the bands: always saying the base rate is exactly the
    # reference, and a float's last digit must not push it past 0.25
    factor = (trust_from_brier(round(0.25 * b / ref, 6)) if ref > 1e-12
              else 1.0)
    return factor, b, ybar, ref


def skill_words(b, ybar, ref) -> str:
    if ref > 0:
        return (f"Brier {b:.2f} against {ref:.2f} for always saying the "
                f"base rate")
    return (f"Brier {b:.2f}; every outcome alike (base rate {ybar:.0%}), so "
            f"no skill can show")


def _specialty_cells(now):
    from ai_agents.council_models import CouncilClaim
    rows = (CouncilClaim.objects
            .exclude(kind__in=WEIGHT_KINDS)
            .filter(venue="live", grade__in=("right", "wrong"),
                    graded_at__gte=now - timedelta(days=C.COUNCIL_RECORD_DAYS))
            .values("voice_key", "regime", "asset_class", "grade")
            .annotate(n=Count("id")))
    out = {}
    for r in rows:
        key = (r["voice_key"], r["regime"], r["asset_class"])
        out.setdefault(key, {"right": 0, "wrong": 0})[r["grade"]] += int(r["n"])
    return out


def _rungs(regime, asset_class):
    rungs = []
    if regime and regime != "unknown":
        rungs.append(("regime_class",
                      lambda rg, cl: rg == regime and cl == asset_class,
                      f"measured in {regime} on {asset_class}"))
        rungs.append(("regime", lambda rg, cl: rg == regime,
                      f"measured in {regime} across classes"))
    rungs.append(("class", lambda rg, cl: cl == asset_class,
                  f"measured on {asset_class} across regimes"))
    rungs.append(("all", lambda rg, cl: True,
                  "measured across regimes and classes"))
    return rungs


def _ladder(cells, spec, voice, regime, asset_class, *, rungs=None) -> dict:
    first_n = None
    rungs = rungs or _rungs(regime, asset_class)
    for name, match, words in rungs:
        n = s = ys = 0
        sp = {"right": 0, "wrong": 0}
        for (vk, rg, cl), (cn, cs, cy) in cells.items():
            if vk == voice and match(rg, cl):
                n += cn
                s += cs
                ys += cy
        for (vk, rg, cl), counts in spec.items():
            if vk == voice and match(rg, cl):
                sp["right"] += counts["right"]
                sp["wrong"] += counts["wrong"]
        if first_n is None:
            first_n = n
            first_sp = sp
            first_rate = (ys / n) if n else None
        if n >= C.COUNCIL_MIN_N:
            factor, b, ybar, ref = skill_factor(n, s, ys)
            return {"factor": factor, "lane": "measured", "n": n,
                    "brier": round(b, 4), "base_rate": round(ybar, 4),
                    "reference": round(ref, 4), "rung": name,
                    "reason": (f"{words}, {n} graded calls, "
                               f"{skill_words(b, ybar, ref)}"),
                    "specialty": sp}
    return {"factor": 1.0, "lane": "neutral", "n": first_n or 0,
            "brier": None,
            "base_rate": (None if first_rate is None
                          else round(first_rate, 4)),
            "reference": None, "rung": "",
            "reason": (f"neutral: {first_n or 0} graded calls in this cell, "
                       f"{C.COUNCIL_MIN_N} needed"),
            "specialty": first_sp}


def voice_weight(voice, *, regime, asset_class, now=None) -> dict:
    """{factor, lane, n, brier, base_rate, reference, rung, reason,
    specialty} for one voice.
    Shown, read by the Emperor, never applied to an order."""
    now = now or timezone.now()
    return _ladder(_cells(now), _specialty_cells(now), voice, regime or "",
                   asset_class or "")


def voice_weights(regime, asset_class, now=None) -> dict:
    """{voice: weight} for the ten, from one aggregate query (and one for
    the specialty counts)."""
    now = now or timezone.now()
    cells, spec = _cells(now), _specialty_cells(now)
    return {v: _ladder(cells, spec, v, regime or "", asset_class or "")
            for v in C.ALL_VOICES}


# ── the Hand of the Emperor (2026-10-16) ──────────────────────────────────
#
# One seat per (regime, class), held by the voice with the best MEASURED
# weight in that very cell: lane "measured" on the regime_class rung (a
# fallback rung never counts), at least COUNCIL_HAND_MIN_N graded calls
# there and a weight of at least COUNCIL_HAND_MIN_FACTOR. Ties go to more
# graded calls, then the lower Brier, then a fixed order. Recomputed from
# the live weights at every sitting: the seat is lost the day another
# voice does better, the voice falls below the bar, or its calls age out
# of the COUNCIL_RECORD_DAYS window. The Emperor never holds his own Hand.

HAND_EMPTY = "no voice has earned it yet"


def _seat_key(v, w):
    b = _f(w.get("brier"))
    return (-float(w["factor"]), -int(w.get("n") or 0),
            b if b is not None else 1.0, C.ALL_VOICES.index(v))


def hand_of(weights: dict, regime: str, asset_class: str) -> dict:
    """{cell, voice, name, factor, n, brier, reference, reason, why_empty}
    for one cell, from its weights. Pure: no query. voice "" is an empty
    seat, and why_empty says why."""
    regime = regime or "unknown"
    cell = f"{regime} on {asset_class or 'every class'}"
    best = None
    for v in C.ALL_VOICES:
        w = (weights or {}).get(v)
        if v == "emperor" or not isinstance(w, dict):
            continue
        factor = _f(w.get("factor"))
        if (w.get("lane") != "measured" or w.get("rung") != "regime_class"
                or factor is None
                or int(w.get("n") or 0) < C.COUNCIL_HAND_MIN_N
                or factor < C.COUNCIL_HAND_MIN_FACTOR - 1e-9):
            continue
        key = _seat_key(v, w)
        if best is None or key < best[0]:
            best = (key, v, w)
    if best is None:
        return {"cell": cell, "voice": "", "name": "", "factor": None,
                "n": 0, "brier": None, "reference": None, "reason": "",
                "why_empty": (HAND_EMPTY if regime != "unknown" else
                              f"{HAND_EMPTY}: the regime is unknown, so no "
                              f"cell is measured")}
    _key, v, w = best
    return {"cell": cell, "voice": v, "name": C.VOICE_NAMES[v],
            "factor": _f(w.get("factor")), "n": int(w.get("n") or 0),
            "brier": _f(w.get("brier")), "reference": _f(w.get("reference")),
            "reason": str(w.get("reason") or ""), "why_empty": ""}


def most_trusted(weights: dict, hand_voice: str, spoke) -> tuple:
    """(voice, how) the Skeptic is pointed at: the Hand when it spoke
    before him ("hand"); else, among the voices that spoke before him, the
    best weight above 1.00 measured in this very cell (the regime_class
    rung, as the Hand), earned trust ("highest"); else ("", "none"). A
    best weight of 0.80 is not "most trusted", and a weight read from a
    fallback rung (the regime, the class, or all of them) is not a record
    "in this cell", which is what the Skeptic is told."""
    spoke = set(spoke or ())
    if hand_voice and hand_voice in spoke:
        return hand_voice, "hand"
    best = None
    for v in C.ALL_VOICES:
        w = (weights or {}).get(v)
        if v in ("skeptic", "emperor") or v not in spoke \
                or not isinstance(w, dict) or w.get("lane") != "measured" \
                or w.get("rung") != "regime_class":
            continue
        factor = _f(w.get("factor"))
        if factor is None or factor <= 1.0:
            continue
        key = _seat_key(v, w)
        if best is None or key < best[0]:
            best = (key, v)
    return (best[1], "highest") if best else ("", "none")


def hands(asset_class: str = "", now=None) -> list:
    """The seat of every (regime, class) with a graded live call in the
    record window (an unknown regime measures no cell), for /council/."""
    now = now or timezone.now()
    cells, spec = _cells(now), _specialty_cells(now)
    keys = sorted({(rg, cl) for (_v, rg, cl) in cells
                   if rg and rg != "unknown"
                   and (not asset_class or cl == asset_class)})
    out = []
    for rg, cl in keys:
        rung = [_rungs(rg, cl)[0]]          # the regime_class rung only
        weights = {v: _ladder(cells, spec, v, rg, cl, rungs=rung)
                   for v in C.ALL_VOICES}
        out.append({"regime": rg, "asset_class": cl,
                    **hand_of(weights, rg, cl)})
    return out


def against_hand(since) -> dict:
    """The Emperor against his Hand: in the live sittings since `since`
    where the Hand took a side and the chair went against it, how often
    each was right (the chair on his battle claim, the Hand on the claim
    its side was read from, council.deciding_claim). The sittings where
    they agreed are counted apart, for contrast."""
    from ai_agents.council_models import CouncilClaim, CouncilVoice
    out = {"overruled": 0, "graded": 0, "emperor_right": 0, "hand_right": 0,
           "unresolved": 0, "pending": 0, "no_reason": 0, "by_voice": {},
           "agreed": {"n": 0, "right": 0}}
    sits = []
    for e in CouncilVoice.objects.filter(
            voice="emperor", status="spoke", session__venue="live",
            session__created_at__gte=since).values("session_id", "answer"):
        a = e["answer"] or {}
        if a.get("hand") and a.get("hand_side"):
            sits.append((e["session_id"], a))
    if not sits:
        return out
    claims = {}
    for c in CouncilClaim.objects.filter(
            session_id__in=[sid for sid, _a in sits],
            kind__in=("battle", "stance", "attack", "work")):
        claims.setdefault((c.session_id, c.voice_key), []).append(c)
    decided = ("right", "wrong")
    for sid, a in sits:
        battle = next((c for c in claims.get((sid, "emperor"), [])
                       if c.kind == "battle"), None)
        eg = battle.grade if battle is not None else ""
        if not a.get("hand_overruled"):
            if eg in decided:
                out["agreed"]["n"] += 1
                out["agreed"]["right"] += eg == "right"
            continue
        hv = a["hand"]
        out["overruled"] += 1
        out["no_reason"] += not a.get("hand_why")
        hc = C.deciding_claim(claims.get((sid, hv), []), hv)
        hg = hc.grade if hc is not None else ""
        if "pending" in (eg, hg):
            out["pending"] += 1
        elif eg in decided and hg in decided:
            out["graded"] += 1
            out["emperor_right"] += eg == "right"
            out["hand_right"] += hg == "right"
            bv = out["by_voice"].setdefault(hv, {"graded": 0,
                                                 "emperor_right": 0,
                                                 "hand_right": 0})
            bv["graded"] += 1
            bv["emperor_right"] += eg == "right"
            bv["hand_right"] += hg == "right"
        else:
            out["unresolved"] += 1
    return out


def skeptic_first(since) -> dict:
    """In the live sittings where the Skeptic was told the most trusted
    voice, how often his attack named it, and how many of those attacks
    were right. Told means he answered (spoke, or late: his answer is
    stored and graded): the trusted voice is saved on the sitting before
    wave 2, so a sitting whose wave 2 the AI budget refused, or whose
    Skeptic fell silent or is still being asked, never read the line and
    is not counted."""
    from ai_agents.council_models import (CouncilClaim, CouncilSession,
                                          CouncilVoice)
    named = {}
    told = CouncilVoice.objects.filter(
        voice="skeptic", status__in=(CouncilVoice.SPOKE, CouncilVoice.LATE)
    ).values("session_id")
    for s in CouncilSession.objects.filter(
            venue="live", created_at__gte=since, id__in=told).exclude(
            status=CouncilSession.RECORD).values("id", "hand"):
        trusted = (s["hand"] or {}).get("trusted") \
            if isinstance(s["hand"], dict) else ""
        if trusted:
            named[s["id"]] = trusted
    out = {"named": len(named), "attacked": 0, "first": 0, "right": 0,
           "graded": 0}
    if not named:
        return out
    for c in CouncilClaim.objects.filter(
            session_id__in=list(named), voice_key="skeptic",
            kind="attack").values("session_id", "payload", "grade"):
        out["attacked"] += 1
        if (c["payload"] or {}).get("target") == named[c["session_id"]]:
            out["first"] += 1
            if c["grade"] in ("right", "wrong"):
                out["graded"] += 1
                out["right"] += c["grade"] == "right"
    return out


# ── the record matrix (/council/, the command, the readers) ───────────────

def _brier(rows):
    rows = [(p, y) for p, y in rows if p is not None and y is not None]
    if not rows:
        return None, 0
    return sum((p - y) ** 2 for p, y in rows) / len(rows), len(rows)


def _agents_for(voice):
    if voice in ("executioner", "champion"):
        return (f"debate_{voice}", f"council_{voice}")
    return (f"council_{voice}",)


#: The claim each voice's specialty line on /council/ is read from: the
#: Executioner's stance (the R his vetoes and cuts saved), the Striker's
#: trigger, the Fixer's fix, the Opportunist's direction call, the
#: Awakened's level, the Skeptic's attack, the Emperor's battle.
SPECIALTY_KIND = {"executioner": "stance", "champion": "stance",
                  "striker": "trigger", "fixer": "fix",
                  "opportunist": "direction", "awakened": "touch",
                  "skeptic": "attack", "emperor": "battle",
                  "gambler": "boldness", "theorist": "theory"}


def _r_worth(v) -> str:
    """'saved +0.50R', 'cost 1.10R', 'changed nothing': the verb follows
    the sign, never "saved -1.10"."""
    return (f"saved {v:+.2f}R" if v > 0 else f"cost {-v:.2f}R" if v < 0
            else "changed nothing")


def specialty_line(voice, stats) -> str:
    s = stats
    graded = s.get("right", 0) + s.get("wrong", 0)
    if voice == "executioner":
        if not graded and not s["value_r"]:
            return "his vetoes and cuts: none graded yet"
        return f"his vetoes and cuts would have {_r_worth(s['value_r'])}"
    if voice == "gambler":
        a, n1, b, n2 = s["all_in_avg"], s["all_in_n"], s["rest_avg"], s["rest_n"]
        return (f"all in: {a:+.2f}R average (n {n1}) against the rest "
                f"{b:+.2f}R (n {n2})" if n1 and n2 else
                f"all in: {n1 or 'none yet'}; other calls: {n2 or 'none yet'}")
    if voice == "striker":
        return f"waits: {s['value_r']:+.2f}R against taking at once"
    if voice == "fixer":
        return f"measured fixes: {s['value_r']:+.2f}R; refused {s['refused']}"
    if voice == "opportunist":
        return f"alternatives right {s['right']} of {s['right'] + s['wrong']}"
    if voice == "awakened":
        return f"levels touched {s['right']} of {s['right'] + s['wrong']}"
    if voice == "skeptic":
        return f"attacks right {s['right']} of {s['right'] + s['wrong']}"
    if voice == "theorist":
        t = s.get("trust")
        return (f"theories posted {s['posted']}; trust in the hypothesis "
                f"market " + (f"{t:.2f}" if t is not None
                              else "not yet measured"))
    if voice == "emperor":
        head = ("his commitment: none graded yet"
                if not graded and not s["value_r"] else
                f"his commitment {_r_worth(s['value_r'])} in total")
        over = ("none graded yet" if not s["over_n"] else
                f"{s['over_wrong']} of {s['over_n']} "
                f"{'was' if s['over_wrong'] == 1 else 'were'} wrong")
        return f"{head}; of the voices he overruled, {over}"
    if voice == "champion":
        # his stance: for or against the trade, beside the weight's own
        # right/wrong count (round 2: two "right" counts side by side)
        return (f"for-or-against calls right {s['right']} of "
                f"{s['right'] + s['wrong']}")
    return f"calls right {s['right']} of {s['right'] + s['wrong']}"


def record_matrix(asset_class: str = "", now=None) -> dict:
    """Everything /council/ and `manage.py council show` print."""
    from django.db.models import Q

    from ai_agents.council_models import (CouncilClaim, CouncilSession,
                                          CouncilVoice)
    from ai_agents.models import AgentTask
    from bot_program.persona_mix import REGIMES
    now = now or timezone.now()
    since = now - timedelta(days=C.COUNCIL_RECORD_DAYS)
    cells, spec = _cells(now), _specialty_cells(now)
    claims = CouncilClaim.objects.filter(venue="live", graded_at__gte=since)

    weight_counts = {}
    for r in (claims.filter(kind__in=WEIGHT_KINDS,
                            grade__in=("right", "wrong"))
              .values("voice_key", "grade", "origin")
              .annotate(n=Count("id"))):
        d = weight_counts.setdefault(r["voice_key"], {"right": 0, "wrong": 0,
                                                      "bot": 0, "ticket": 0})
        d[r["grade"]] += r["n"]
        if r["origin"] in ("bot", "ticket"):
            d[r["origin"]] += r["n"]

    # Each voice's specialty line reads its OWN specialty claim (the
    # Skeptic's attack included, though it is also his weight claim): the
    # Opportunist's line counts his direction calls, never his stance.
    special = {}
    for r in (claims.values("voice_key", "kind", "grade")
              .annotate(n=Count("id"), v=Sum("value_r"))):
        if SPECIALTY_KIND.get(r["voice_key"]) != r["kind"]:
            continue
        d = special.setdefault(r["voice_key"], {"right": 0, "wrong": 0,
                                                "refused": 0, "value_r": 0.0})
        if r["grade"] in ("right", "wrong", "refused"):
            d[r["grade"]] += r["n"]
        if r["grade"] in ("right", "wrong", "unresolvable"):
            d["value_r"] += float(r["v"] or 0.0)

    cost_since = now - timedelta(days=30)
    costs = {r["agent"]: float(r["c"] or 0) for r in (
        AgentTask.objects.filter(created_at__gte=cost_since)
        .values("agent").annotate(c=Sum("cost_usd")))}

    gamb = {"all_in": [], "rest": []}
    for verdict, r in (CouncilVoice.objects
                       .filter(voice="gambler", session__venue="live",
                               session__truth_r__isnull=False,
                               session__created_at__gte=since,
                               status__in=("spoke", "late"))
                       .values_list("verdict", "session__truth_r")):
        gamb["all_in" if verdict == "all_in" else "rest"].append(float(r))

    # The chair's statistics: what became of the voices he followed and
    # overruled, from their own claims in the same sittings.
    chair = {"over_wrong": 0, "over_n": 0, "follow_right": 0, "follow_n": 0}
    emperor_rows = list(CouncilVoice.objects.filter(
        voice="emperor", status="spoke", session__venue="live",
        session__created_at__gte=since).values("session_id", "answer"))
    if emperor_rows:
        verdicts = {}
        for c in CouncilClaim.objects.filter(
                session_id__in=[e["session_id"] for e in emperor_rows],
                kind__in=("stance", "work"),
                grade__in=("right", "wrong")).values(
                "session_id", "voice_key", "kind", "grade"):
            key = (c["session_id"], c["voice_key"])
            if key not in verdicts or c["kind"] == "stance":
                verdicts[key] = c["grade"]
        for e in emperor_rows:
            a = e["answer"] or {}
            for o in a.get("overruled") or []:
                g = verdicts.get((e["session_id"], o.get("voice")))
                if g:
                    chair["over_n"] += 1
                    chair["over_wrong"] += g == "wrong"
            for v in a.get("followed") or []:
                g = verdicts.get((e["session_id"], v))
                if g:
                    chair["follow_n"] += 1
                    chair["follow_right"] += g == "right"

    try:
        from brain.hypotheses import agent_trust_score
        theorist_trust = agent_trust_score("council_theorist")
    except Exception:  # noqa: BLE001
        theorist_trust = None
    posted = CouncilClaim.objects.filter(kind="theory",
                                         hypothesis__isnull=False).count()

    voices = []
    all_rung = [r for r in _rungs("", "") if r[0] == "all"]
    for v in C.ALL_VOICES:
        # the table's weight is the (all regimes, all classes) rung
        w = _ladder(cells, spec, v, "", "", rungs=all_rung)
        wc = weight_counts.get(v, {"right": 0, "wrong": 0, "bot": 0,
                                   "ticket": 0})
        sp = special.get(v, {"right": 0, "wrong": 0, "refused": 0,
                             "value_r": 0.0})
        stats = dict(sp)
        stats.update({"posted": posted, "trust": theorist_trust,
                      "over_wrong": chair["over_wrong"],
                      "over_n": chair["over_n"],
                      "all_in_n": len(gamb["all_in"]),
                      "all_in_avg": (sum(gamb["all_in"]) / len(gamb["all_in"])
                                     if gamb["all_in"] else 0.0),
                      "rest_n": len(gamb["rest"]),
                      "rest_avg": (sum(gamb["rest"]) / len(gamb["rest"])
                                   if gamb["rest"] else 0.0)})
        voices.append({
            "voice": v, "name": C.VOICE_NAMES[v], "factor": w["factor"],
            "lane": w["lane"], "n": w["n"], "brier": w["brier"],
            "base_rate": w["base_rate"], "reference": w["reference"],
            "reason": w["reason"], "right": wc["right"],
            "wrong": wc["wrong"], "bot_n": wc["bot"], "hand_n": wc["ticket"],
            "specialty": specialty_line(v, stats),
            "cost_30d": round(sum(costs.get(a, 0.0) for a in _agents_for(v)),
                              4)})

    sess = list(CouncilSession.objects.filter(
        venue="live", y__isnull=False, graded_at__gte=since).values(
        "p_chair", "p_weighted", "p_mean", "y"))
    # The three rows are graded on the SAME sittings: a sitting the chair
    # never judged (a budget refusal, a late or silent Emperor) or whose
    # weights were never read would otherwise count against the average
    # alone, and the chair would beat the arithmetic for free.
    paired = [r for r in sess
              if None not in (r["p_chair"], r["p_mean"], r["p_weighted"])]
    benchmarks = []
    for label, key in (("The Emperor", "p_chair"),
                       ("The council, weighted by record", "p_weighted"),
                       ("The council, plain average", "p_mean")):
        b, n = _brier([(r[key], r["y"]) for r in paired])
        benchmarks.append({"name": label, "brier": b, "n": n})

    both = list(CouncilSession.objects.filter(
        truth="realized", replay_r__isnull=False,
        truth_r__isnull=False).values_list("truth_r", "replay_r"))
    agree = sum(1 for a, b in both if (a > 0) == (b > 0) and (a < 0) == (b < 0))

    regimes = [r for r in REGIMES]
    matrix = []
    for v in C.ALL_VOICES:
        row = []
        for rg in regimes:
            n = s = ys = 0
            for (vk, crg, ccl), (cn, cs, cy) in cells.items():
                if vk == v and crg == rg and (not asset_class
                                              or ccl == asset_class):
                    n += cn
                    s += cs
                    ys += cy
            if n >= C.COUNCIL_MIN_N and rg != "unknown":
                row.append({"regime": rg, "factor": skill_factor(n, s, ys)[0],
                            "n": n, "lane": "measured"})
            else:
                row.append({"regime": rg, "factor": 1.0, "n": n,
                            "lane": "neutral"})
        matrix.append({"voice": v, "name": C.VOICE_NAMES[v], "cells": row})

    graded_any = CouncilClaim.objects.filter(
        Q(grade="right") | Q(grade="wrong")).exists()
    from ai_agents.council_mood import mood_outcomes
    return {"schema_version": C.COUNCIL_SCHEMA_VERSION, "voices": voices,
            "benchmarks": benchmarks,
            "benchmarks_unpaired": len(sess) - len(paired),
            "regimes": regimes, "matrix": matrix,
            "replay": {"n": len(both), "agree": agree},
            "chair": chair, "graded_any": graded_any,
            "asset_class": asset_class,
            # THE HAND OF THE EMPEROR and THE PEOPLE'S MOOD (2026-10-16)
            "hands": hands(asset_class, now),
            "against_hand": against_hand(since),
            "skeptic_first": skeptic_first(since),
            "moods": mood_outcomes(since)}
