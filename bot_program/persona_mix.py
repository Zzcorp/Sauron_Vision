"""THE MIX MOVES WITH THE MARKET — which personality the tape rewards.

The operator's ask, in their words: "Make the three personalities interact
continuously. Under certain market states some personalities should be
used more, no? Quiet market: swing++ or short-term+++, to maximise the
benefit over a period, with different angles of attack."

The intuition is sound and every piece already exists — the brain records
a regime every half hour, configs wear personalities, and every fill is
graded in R. What does NOT exist is the answer. NOBODY KNOWS which
personality suits which regime: not the operator, not the specification
this module was written from, and not this module. The deployment has ten
graded signals across its designed rules and no config has ever worn a
personality. So this file does not encode a belief about markets. It
builds the machine that FINDS OUT, in the two lanes every other evidence
reader on this platform already uses:

  MEASURED — what configs wearing this personality actually earned while
             the platform RECORDED this regime, above the platform's own
             sample floor (evidence.MIN_EVIDENCE_N, imported, not
             redefined). This wins whenever it exists.
  PRIOR    — a small, explicitly-labelled, UNPROVEN tilt that applies
             ONLY where nothing is measured. See `PRIORS` below: every
             entry carries its one-line reason in `PRIOR_WHY`, the tilts
             are in [-1, +1] and are multiplied by PRIOR_STRENGTH (0.15),
             so the loudest guess in this file moves a band by 15%.
             A MEASURED CELL REPLACES ITS PRIOR ENTIRELY — the prior is
             not averaged in, not decayed, not blended. It is gone.
  NEUTRAL  — exactly 1.0, when the regime is unknown or the prior has
             nothing to say about that cell.

Every answer records WHICH LANE SPOKE and with what n, so over weeks the
priors retire cell by cell and the /personas/ matrix shows the operator
exactly which of the eighteen cells are still guesses. That visibility is
the feature. A clever regime rule that nobody could audit would be worth
less than this and would look like more.

WHY 'unknown' IS NEVER MEASURED. BrainReport.REGIME_UNKNOWN is the
classifier's "we could not classify it" sentinel, not an observed state
of the market — brain.hypotheses says so by name (REGIME_NOT_MEASURED).
Trades opened while the brain was down or unsure share no market
condition; measuring them would measure the brain's downtime and then
size a book on it. `mix_factor` short-circuits 'unknown' to 1.0 before it
reads a single trade.

HOW FAR A REGIME MAY MOVE A POOL IN ONE DAY. The factor moves a BAND,
never a share: `shift_band` shifts the band's centre and keeps its width,
by at most MAX_BAND_SHIFT_PCT points, and everything the allocator does
under that band — the water-fill, the half-way smoothing, the per-day
allowance and the hysteresis — still binds. So a flip moves a pool no
further in one day than the allowance the allocator ALREADY granted it:
share_allocator.MAX_CHANGE_PCT_PER_DAY in NORMAL and SHOCK, and the
wider EXPANSION_CAP_PCT_PER_DAY an EXPANSION tape already allowed
upward. That second number is named here because "still 10 points" is
not true on an expanding tape and never was (2026-09-12).

WHAT THIS MODULE DELIBERATELY DOES NOT TOUCH, and the reason is
attribution: risk_per_trade_pct and max_notional_fraction. THE MIX MOVES
SHARES ONLY. Two dials moving at once make the grade unattributable — if
a regime flip shifted the share AND the risk per trade in the same week,
no reading afterwards could say which of the two earned the R, and the
whole point of recording the lane and the n is to be able to say. The
risk dial stays exactly where each persona's preset put it (2026-09-12).
"""
from __future__ import annotations

import bisect
import logging
from datetime import timedelta
from types import MappingProxyType, SimpleNamespace

from django.utils import timezone

# The floor and the graded-outcome vocabulary are the EVIDENCE MODULE'S,
# imported rather than restated. A second copy of MIN_EVIDENCE_N is a
# second floor: the day one of them moved, this module would call a cell
# measured that the evidence ledger on the same page called unmeasured,
# and the operator would have no way to tell which number was the lie.
from bot_program.evidence import GRADED_OUTCOMES, MIN_EVIDENCE_N
from bot_program.personas import (PERSONA_EXTRAS_KEY, PERSONA_KEYS, PERSONAS,
                                  persona_of)

logger = logging.getLogger(__name__)

# ── The regime vocabulary ────────────────────────────────────────────────
# READ FROM THE CODE, not invented: these are exactly BrainReport's own
# REGIME_CHOICES values, which are also the vocabulary
# brain.hypotheses.canonical_regime maps free text onto. They are written
# out here rather than imported at module scope so importing this file
# does not require the app registry, and tests/test_persona_mix.py pins
# the tuple against BrainReport.REGIME_CHOICES — if the model ever grows a
# regime, that test fails rather than this file silently ignoring it.
REGIME_RISK_ON = "risk_on"
REGIME_RISK_OFF = "risk_off"
REGIME_MEAN_REVERTING = "mean_reverting"
REGIME_TRENDING = "trending"
REGIME_BLOW_OFF = "blow_off"
REGIME_UNKNOWN = "unknown"
REGIMES = (REGIME_RISK_ON, REGIME_RISK_OFF, REGIME_MEAN_REVERTING,
           REGIME_TRENDING, REGIME_BLOW_OFF, REGIME_UNKNOWN)

# The two venues, from the module that owns the rule. VENUE_ALL exists in
# bot_grading for dashboards and is REFUSED here: pooling paper and live
# is exactly the mistake the venue argument exists to prevent, and a
# pooled cell would size a live book on a simulation.
VENUE_LIVE = "live"
VENUE_PAPER = "paper"
VENUES = (VENUE_LIVE, VENUE_PAPER)

# ── The strengths, and why each is small ─────────────────────────────────
# A measured cell's average R becomes a factor at a QUARTER of its face
# value: +1.0R average over the floor moves a band by 25%, not by 100%.
MEASURED_STRENGTH = 0.25
# And nothing measured may move it further than this, whatever the
# average — one hot month of scalps in a range is a month, not a law.
MAX_TILT = 0.25
# A prior is a guess wearing a label. At 0.15 the loudest entry in the
# table below (±0.6) is a 9% nudge, and the largest possible entry (±1.0)
# is 15% — smaller than the smallest measured cell that clears the floor
# would typically be. That ordering is deliberate: evidence must always be
# able to out-argue the guess it replaces.
PRIOR_STRENGTH = 0.15
# How far a regime may move a persona's SHARE BAND, in percentage points
# of the account (see `shift_band`). The band's width never changes; only
# its centre moves, and only this far.
MAX_BAND_SHIFT_PCT = 5.0


def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


# ── The priors — UNPROVEN, SMALL, AND LABELLED AS SUCH ───────────────────
#
# Read this table as "what a reasonable trader would guess before any
# evidence exists", never as "what this platform has found". Not one cell
# below is backed by a single graded fill on this deployment. They exist
# so the mix has something better than 1.0 to say on day one, and they are
# built to be REPLACED: the first time a cell clears MIN_EVIDENCE_N,
# `mix_factor` stops reading this dict for that cell for ever.
#
# Every tilt is in [-1, +1] and becomes `1 + tilt × PRIOR_STRENGTH`.
PRIORS = MappingProxyType({
    # A range pays for going in and out. Holding through an oscillation
    # earns the oscillation and keeps none of it.
    ("scalp", REGIME_MEAN_REVERTING): +0.6,
    ("swing", REGIME_MEAN_REVERTING): +0.3,
    ("position", REGIME_MEAN_REVERTING): -0.6,
    # A trend pays for holding. A scalper pays the spread again on every
    # leg of the same move.
    ("scalp", REGIME_TRENDING): -0.4,
    ("swing", REGIME_TRENDING): +0.4,
    ("position", REGIME_TRENDING): +0.6,
    # Shorter exposure when the tape gaps. A long hold in a falling
    # market is a hold in a falling market.
    ("scalp", REGIME_RISK_OFF): +0.3,
    ("swing", REGIME_RISK_OFF): -0.3,
    ("position", REGIME_RISK_OFF): -0.6,
    ("scalp", REGIME_RISK_ON): -0.2,
    ("swing", REGIME_RISK_ON): +0.4,
    ("position", REGIME_RISK_ON): +0.4,
    # The phase where holding hurts most and reversals are fastest.
    ("scalp", REGIME_BLOW_OFF): +0.4,
    ("swing", REGIME_BLOW_OFF): -0.2,
    ("position", REGIME_BLOW_OFF): -0.5,
    # 'unknown' is the absence of a reading, not a state of the market.
    # Zero, and `mix_factor` never even gets here for it.
    ("scalp", REGIME_UNKNOWN): 0.0,
    ("swing", REGIME_UNKNOWN): 0.0,
    ("position", REGIME_UNKNOWN): 0.0,
})

#: One line per cell saying WHY that guess was made, printed verbatim in
#: the plan's why sentence and on the matrix. A prior with no stated
#: reason is a magic number, and a magic number nobody can argue with is
#: one nobody can retire.
PRIOR_WHY = MappingProxyType({
    ("scalp", REGIME_MEAN_REVERTING):
        "a range pays for going in and out",
    ("swing", REGIME_MEAN_REVERTING):
        "a range still has swings, just shorter ones",
    ("position", REGIME_MEAN_REVERTING):
        "holding through an oscillation earns it and keeps none of it",
    ("scalp", REGIME_TRENDING):
        "a scalper pays the spread again on every leg of the same move",
    ("swing", REGIME_TRENDING):
        "the 4h trend is the thing this persona was built to ride",
    ("position", REGIME_TRENDING):
        "a trend pays for holding, and this is the persona that holds",
    ("scalp", REGIME_RISK_OFF):
        "shorter exposure when the tape gaps",
    ("swing", REGIME_RISK_OFF):
        "days of exposure into a falling tape is days of exposure",
    ("position", REGIME_RISK_OFF):
        "a long hold in a falling market is a hold in a falling market",
    ("scalp", REGIME_RISK_ON):
        "fewer false breaks to fade when everything is bid",
    ("swing", REGIME_RISK_ON):
        "the multi-day leg is where a risk-on tape pays",
    ("position", REGIME_RISK_ON):
        "risk-on is the tape a weeks-long thesis was written for",
    ("scalp", REGIME_BLOW_OFF):
        "reversals are fastest here, and this persona is out by dinner",
    ("swing", REGIME_BLOW_OFF):
        "a three-session hold spans the reversal, not the run",
    ("position", REGIME_BLOW_OFF):
        "the phase where holding hurts most",
    ("scalp", REGIME_UNKNOWN): "no reading — no guess",
    ("swing", REGIME_UNKNOWN): "no reading — no guess",
    ("position", REGIME_UNKNOWN): "no reading — no guess",
})


def _canonical(label) -> str:
    """`label` mapped onto REGIMES, else 'unknown' — never raises.

    A hand-edited row or an older writer can put anything in
    regime_label; brain.hypotheses.canonical_regime is the platform's own
    normaliser and it answers None for a token it does not know. An
    unmapped token must read as 'unknown' (no claim) rather than as a
    regime nobody has a prior or a measurement for.
    """
    token = str(label or "").strip().lower()
    if token in REGIMES:
        return token
    try:
        from brain.hypotheses import canonical_regime
        return canonical_regime(token) or REGIME_UNKNOWN
    except Exception as e:  # noqa: BLE001 — an unreadable label is unknown
        logger.debug("[mix] regime label %r unmappable: %s", label, e)
        return REGIME_UNKNOWN


# ── What the platform RECORDED, and when ─────────────────────────────────

def latest_report(when=None) -> dict:
    """{regime, confidence, at, report_id, age_minutes, source} — the
    newest usable BrainReport at or before `when`.

    ONE query. A report carrying an `error` is skipped: a synthesis run
    that failed recorded nothing, and its default regime_label ('unknown')
    would otherwise read as a measurement. No report at all is 'unknown'
    with the reason in `source`, never an exception — a mix that cannot
    read the brain is a neutral mix, not a broken plan.
    """
    when = when or timezone.now()
    out = {"regime": REGIME_UNKNOWN, "confidence": 0.0, "at": None,
           "report_id": None, "age_minutes": None,
           "source": "no brain report — unknown"}
    try:
        from brain.models import BrainReport
        row = (BrainReport.objects
               .filter(error="", created_at__lte=when)
               .order_by("-created_at")
               .values("id", "regime_label", "regime_confidence",
                       "created_at")
               .first())
    except Exception as e:  # noqa: BLE001 — unreadable is unknown, with a reason
        logger.warning("[mix] brain report unreadable: %s", e)
        out["source"] = f"brain report unreadable: {e}"
        return out
    if row is None:
        return out
    age_min = max(0.0, (when - row["created_at"]).total_seconds() / 60.0)
    return {"regime": _canonical(row["regime_label"]),
            "confidence": float(row["regime_confidence"] or 0.0),
            "at": row["created_at"], "report_id": row["id"],
            "age_minutes": age_min,
            "source": (f"BrainReport #{row['id']}, {age_min:.0f}m old, "
                       f"confidence {float(row['regime_confidence'] or 0.0):.2f}")}


def regime_at(when) -> str:
    """The regime the platform RECORDED at `when` — never the current one.

    This is the whole join, and the place it would be quietly wrong. A
    trade that opened on Tuesday was opened into Tuesday's tape; reading
    today's BrainReport for it would label every trade in history with
    this morning's regime, every cell of the matrix would fill with the
    same label, and the measured lane would look like it was working
    while measuring nothing at all. So: the newest report with error=''
    whose created_at <= `when`, and 'unknown' when there is none.

    ONE query. A caller with many timestamps (a pass over hundreds of
    trades) must use `regime_series` instead — this function per trade is
    one query per trade.
    """
    return latest_report(when)["regime"]


def regime_series(since, until=None) -> list:
    """[(from, to, label, confidence)] tiling [since, until] exactly.

    THE COST, which is the reason this function exists: ONE query, then a
    bisect per lookup (`regime_in_series`). A pass over hundreds of
    trades that called `regime_at` per row would be hundreds of queries
    against a table the synthesizer writes to every 30 minutes; this is
    one, and the reports are read newest-first through `.iterator()` and
    abandoned as soon as the one in force at `since` is found, so the
    query is bounded by the window rather than by the table.

    The stretches are half-open [from, to) and consecutive — the `to` of
    each is the `from` of the next, the first starts exactly at `since`
    and the last ends exactly at `until`. No gaps: the stretch before the
    first report in the window carries the label of the last report
    BEFORE it (that is what the platform was recording then), or
    'unknown' when nothing preceded it. No overlaps: two reports sharing
    a timestamp collapse to the later label rather than producing a
    zero-width stretch a bisect could land inside.
    """
    until = until or timezone.now()
    if until < since:
        until = since
    inside, anchor = [], None
    try:
        from brain.models import BrainReport
        qs = (BrainReport.objects
              .filter(error="", created_at__lte=until)
              .order_by("-created_at")
              .values_list("created_at", "regime_label",
                           "regime_confidence"))
        for created, label, conf in qs.iterator():
            if created > since:
                inside.append((created, label, conf))
            else:
                anchor = (created, label, conf)
                break
    except Exception as e:  # noqa: BLE001 — unreadable is one unknown stretch
        logger.warning("[mix] regime series unreadable: %s", e)
        return [(since, until, REGIME_UNKNOWN, 0.0)]
    inside.reverse()

    label = _canonical(anchor[1]) if anchor else REGIME_UNKNOWN
    conf = float(anchor[2] or 0.0) if anchor else 0.0
    cursor = since
    out = []
    for created, raw_label, raw_conf in inside:
        if created > cursor:
            out.append((cursor, created, label, conf))
            cursor = created
        label, conf = _canonical(raw_label), float(raw_conf or 0.0)
    out.append((cursor, until, label, conf))
    return out


def regime_in_series(series, when) -> str:
    """The label of the stretch containing `when` — a bisect, no query.

    A timestamp BEFORE the series starts answers 'unknown' rather than
    borrowing the first stretch's label: the series was built over a
    window, and a caller asking outside it is asking about a moment
    nothing in this series witnessed.
    """
    return labels_in_series(series, [when])[0]


def labels_in_series(series, whens) -> list:
    """One label per timestamp, index built ONCE — the bulk form.

    `regime_in_series` in a loop would rebuild the list of stretch starts
    for every trade, which turns the bisect this module exists to use
    back into a scan. The matrix pass reads hundreds of opens against one
    series, so it calls this.
    """
    whens = list(whens)
    if not series:
        return [REGIME_UNKNOWN] * len(whens)
    starts = [s[0] for s in series]
    out = []
    for when in whens:
        if when < starts[0]:
            out.append(REGIME_UNKNOWN)
            continue
        i = bisect.bisect_right(starts, when) - 1
        out.append(series[i][2] if i >= 0 else REGIME_UNKNOWN)
    return out


# ── What each personality earned in each regime ──────────────────────────

def _venue_ok(venue: str) -> str:
    """`venue` or ValueError. Raising, not defaulting: a typo'd venue that
    quietly pooled would reinstate exactly the bug the argument prevents,
    and it would do so invisibly (bot_grading._venue_filter, same rule)."""
    v = str(venue or "").strip().lower()
    if v not in VENUES:
        raise ValueError(f"venue must be one of {VENUES}, got {venue!r} "
                         f"— live and paper are never pooled here")
    return v


def _wearing() -> dict:
    """{persona_key: [config_pk]} — ONE query over AssetBotConfig.

    `extras` is a JSON blob and its persona key is matched in Python
    through `personas.persona_of`, exactly as `evidence.persona_rows`
    does: a `extras__persona=` lookup would answer differently on SQLite
    and Postgres for a key stored with different case or whitespace, and
    persona_of is the one definition of what wearing a persona means.
    """
    out = {k: [] for k in PERSONA_KEYS}
    try:
        from bot_program.models import AssetBotConfig
        rows = AssetBotConfig.objects.values_list("pk", "extras")
    except Exception as e:  # noqa: BLE001 — no configs readable is no record
        logger.warning("[mix] configs unreadable: %s", e)
        return out
    for pk, extras in rows:
        key = persona_of(SimpleNamespace(extras=extras or {}))
        if key in out:
            out[key].append(pk)
    return out


def _graded_fills(config_pks, since, venue) -> list:
    """[(opened_at, realized_r)] — ONE query.

    The same rows the evidence ledger reads and the same exclusions:
    CLOSED with a graded outcome and a priced realized_r (a NULL R is an
    unpriced exit, not a zero-R trade), no blank rule name, and never
    `manual_take` — a hand-taken position is the operator's evidence, not
    a personality's. The WINDOW is on closed_at, as everywhere else in
    this platform; the REGIME is joined on opened_at, which is the whole
    point of this module.
    """
    if not config_pks:
        return []
    try:
        from bot_program.models import AssetBotTrade
        return list(AssetBotTrade.objects
                    .filter(config_id__in=list(config_pks), status="CLOSED",
                            paper=(venue == VENUE_PAPER),
                            closed_at__gte=since,
                            outcome__in=GRADED_OUTCOMES,
                            realized_r__isnull=False)
                    .exclude(rule_name="").exclude(rule_name="manual_take")
                    .values_list("opened_at", "realized_r"))
    except Exception as e:  # noqa: BLE001 — unreadable is unmeasured
        logger.warning("[mix] graded fills unreadable: %s", e)
        return []


def _blank_record(persona_key, regime, days, venue, reason) -> dict:
    return {"persona": persona_key, "regime": regime, "venue": venue,
            "n": 0, "avg_r": None, "r_sum": None, "win_rate": None,
            "measured": False, "days": days, "reason": reason}


def _record_from(rs, persona_key, regime, days, venue) -> dict:
    """Build one cell from the R values of the fills that landed in it.

    Below the floor, avg_r AND win_rate are None — never 0.0. A cell
    nothing has traded has earned NOTHING MEASURED, and 0.0 R reads as
    "broke even", which is a claim; an average over three fills is the
    same claim with a decimal point. `r_sum` and `n` survive below the
    floor because they are counts, not expectancies, and the page needs
    them to say how far a cell is from retiring its prior.
    """
    n = len(rs)
    if n == 0:
        return _blank_record(persona_key, regime, days, venue,
                             f"no graded {venue} fill of a {persona_key} "
                             f"config opened in {regime} in {days}d — "
                             f"unmeasured, which is not zero")
    r_sum = sum(rs)
    if n < MIN_EVIDENCE_N:
        return {"persona": persona_key, "regime": regime, "venue": venue,
                "n": n, "avg_r": None, "r_sum": r_sum, "win_rate": None,
                "measured": False, "days": days,
                "reason": (f"{n} graded {venue} fill{'' if n == 1 else 's'} "
                           f"of {persona_key} opened in {regime} in {days}d "
                           f"— the floor is {MIN_EVIDENCE_N}")}
    wins = sum(1 for r in rs if r > 0)
    return {"persona": persona_key, "regime": regime, "venue": venue,
            "n": n, "avg_r": r_sum / n, "r_sum": r_sum,
            "win_rate": wins / n, "measured": True, "days": days,
            "reason": (f"{persona_key} earned {r_sum / n:+.2f}R on average "
                       f"over {n} {venue} fills opened in {regime} "
                       f"in {days}d")}


def record_matrix(*, venue=VENUE_LIVE, now=None) -> dict:
    """{persona_key: {regime: record}} — every cell, in bounded queries.

    Three queries per persona at most (configs once for all three, then
    that persona's fills and the regime stretches those fills opened in),
    rather than one per cell: the eighteen-cell page and the allocator's
    one-call-per-proposal both need the whole matrix, and eighteen
    separate `persona_regime_record` calls would be eighteen passes over
    the same rows.

    Each persona is windowed by ITS OWN evidence_days — 21 days of scalps
    is a sample and 21 days of position trades is one trade, which is the
    same reason `config_evidence` takes the window from the persona.
    """
    venue = _venue_ok(venue)
    now = now or timezone.now()
    wearing = _wearing()
    out = {}
    for key in PERSONA_KEYS:
        persona = PERSONAS[key]
        days = int(persona.evidence_days)
        since = now - timedelta(days=days)
        fills = _graded_fills(wearing.get(key) or [], since, venue)
        buckets = {r: [] for r in REGIMES}
        if fills:
            # The series must cover every OPEN, and an open can be far
            # older than the closed_at window (a position trade opened in
            # January and closed in March is a March fill). Building it
            # from `since` would silently answer 'unknown' for exactly
            # the longest-held trades — the ones this platform has least
            # of and can least afford to mislabel.
            first_open = min(o for o, _r in fills)
            series = regime_series(first_open, now)
            labels = labels_in_series(series, [o for o, _r in fills])
            for (_opened_at, r), label in zip(fills, labels):
                buckets.setdefault(label, []).append(float(r))
        out[key] = {reg: _record_from(buckets.get(reg) or [], key, reg,
                                      days, venue)
                    for reg in REGIMES}
    return out


def persona_regime_record(persona_key, regime, *, days=None,
                          venue=VENUE_LIVE, now=None) -> dict:
    """{n, avg_r, r_sum, win_rate, measured, days, reason} for ONE cell.

    The graded closed fills of every config wearing `persona_key` whose
    OPEN fell inside a stretch the platform recorded as `regime`.

    `days` defaults to the persona's own grading window (the number
    `personas.persona_evidence_days` answers for a config wearing it):
    scalp 21, swing 90, position 365. An explicit `days` wins outright.

    `venue` is 'live' or 'paper' and NEVER both. Paper and live are two
    different measurements of the same personality, not two samples of
    one — a paper fill is charged a modelled half-spread and has no
    resting stop at a broker — and their average describes neither. A
    caller that wants both calls twice and prints two numbers.
    """
    key = str(persona_key or "").strip().lower()
    venue = _venue_ok(venue)
    reg = _canonical(regime)
    persona = PERSONAS.get(key)
    if persona is None:
        return _blank_record(key, reg, int(days or 0), venue,
                             f"no persona named {persona_key!r} — the three "
                             f"are {', '.join(PERSONA_KEYS)}")
    now = now or timezone.now()
    days = int(persona.evidence_days if days is None else days)
    since = now - timedelta(days=days)
    fills = _graded_fills(_wearing().get(key) or [], since, venue)
    if not fills:
        return _record_from([], key, reg, days, venue)
    series = regime_series(min(o for o, _r in fills), now)
    labels = labels_in_series(series, [o for o, _r in fills])
    rs = [float(r) for (_o, r), label in zip(fills, labels) if label == reg]
    return _record_from(rs, key, reg, days, venue)


# ── The factor ───────────────────────────────────────────────────────────

def _measured_factor(avg_r) -> float:
    return _clamp(1.0 + float(avg_r) * MEASURED_STRENGTH,
                  1.0 - MAX_TILT, 1.0 + MAX_TILT)


def _neutral(persona_key, regime, reason, *, record=None) -> dict:
    return {"factor": 1.0, "lane": "neutral", "persona": persona_key,
            "regime": regime, "n": int((record or {}).get("n") or 0),
            "avg_r": None, "reason": reason}


def mix_factor(persona_key, regime, *, venue=VENUE_LIVE, now=None,
               record=None) -> dict:
    """{factor, lane, n, avg_r, reason} — how much this regime should move
    this personality's band.

    THE LANE ORDER, and it is the whole design:

      measured  the cell cleared MIN_EVIDENCE_N. factor =
                clamp(1 + avg_r × MEASURED_STRENGTH, 1 ± MAX_TILT). The
                prior for this cell is not consulted, not blended, not
                decayed — it is GONE.
      prior     nothing measured, and PRIORS has a non-zero guess.
                factor = 1 + tilt × PRIOR_STRENGTH, and the reason says
                "(unproven)" in those words, on the plan and on the page.
      neutral   exactly 1.0. The regime is 'unknown' (an absence of a
                reading, not a market state), or the prior has nothing to
                say about this cell.

    `record` lets a caller that already built the matrix pass the cell in
    rather than re-query it — the allocator reads the regime ONCE per
    proposal and must not pay three queries per config.
    """
    key = str(persona_key or "").strip().lower()
    reg = _canonical(regime)
    if key not in PERSONAS:
        return _neutral(key, reg, f"no persona named {persona_key!r} — neutral")
    # 'unknown' is the classifier's "could not classify", not an observed
    # state (brain.hypotheses.REGIME_NOT_MEASURED). Short-circuited before
    # any query: trades opened while the brain was down share no market
    # condition, and a cell built from them would measure the downtime.
    if reg == REGIME_UNKNOWN:
        return _neutral(key, reg,
                        "neutral: the platform recorded no regime — "
                        "unknown is an absence of a reading, not a state "
                        "of the market")
    if record is None:
        record = persona_regime_record(key, reg, venue=venue, now=now)
    if record.get("measured") and record.get("avg_r") is not None:
        avg = float(record["avg_r"])
        n = int(record.get("n") or 0)
        return {"factor": _measured_factor(avg), "lane": "measured",
                "persona": key, "regime": reg, "n": n, "avg_r": avg,
                "reason": (f"measured: {key} earned {avg:+.2f}R over {n} "
                           f"{record.get('venue', venue)} fills recorded "
                           f"in {reg}")}
    tilt = float(PRIORS.get((key, reg), 0.0) or 0.0)
    if tilt == 0.0:
        return _neutral(key, reg,
                        f"neutral: nothing measured for {key} in {reg} "
                        f"and no prior says otherwise", record=record)
    why = PRIOR_WHY.get((key, reg), "")
    return {"factor": 1.0 + tilt * PRIOR_STRENGTH, "lane": "prior",
            "persona": key, "regime": reg,
            "n": int(record.get("n") or 0), "avg_r": None,
            "reason": (f"prior (unproven): {why}"
                       if why else
                       f"prior (unproven): {key} in {reg} tilt {tilt:+.2f}")}


def current_mix(user=None, *, venue=VENUE_LIVE, now=None) -> dict:
    """{regime, confidence, source, age_minutes, personas, bands, measured,
    cells} — ONE call the allocator, the page and the command all share.

    Three surfaces reading three different regimes, or the page printing
    a factor the plan did not use, is the failure this single entry point
    exists to make impossible.

    `user` is accepted and deliberately unused by the record: what a
    personality has earned is the FLEET'S evidence, and this deployment
    has one operator. The argument is here so the allocator's call site
    reads like every other reader it calls and a future multi-operator
    install has one place to scope it.
    """
    now = now or timezone.now()
    head = latest_report(now)
    reg = head["regime"]
    matrix = record_matrix(venue=venue, now=now)
    personas = {k: mix_factor(k, reg, venue=venue, now=now,
                              record=matrix[k][reg])
                for k in PERSONA_KEYS}
    return {
        "regime": reg,
        "confidence": head["confidence"],
        "source": head["source"],
        "age_minutes": head["age_minutes"],
        "report_id": head["report_id"],
        "venue": venue,
        "personas": personas,
        "bands": {k: (float(PERSONAS[k].share_floor_pct),
                      float(PERSONAS[k].share_ceiling_pct))
                  for k in PERSONA_KEYS},
        # How many of the three factors in force right now are evidence
        # rather than guesswork. The page prints the same count over all
        # eighteen cells; this one is about the regime the tape is in.
        "measured": sum(1 for d in personas.values()
                        if d["lane"] == "measured"),
        "cells": matrix,
    }


# ── The band the factor moves ────────────────────────────────────────────

def shift_band(lo, hi, factor) -> tuple:
    """(lo, hi) shifted by `factor`, WIDTH PRESERVED and shift CLAMPED.

    The band's centre moves to centre × factor; its width never changes;
    and the move is held to ±MAX_BAND_SHIFT_PCT percentage points of the
    account whatever the factor says. Worked: swing is 20-60, centre 40,
    width 40. A factor of 1.15 asks for centre 46, a shift of +6, which
    is clamped to +5 — so the band becomes 25-65. It never becomes 40-80,
    and the width the persona declared (how much room the allocator has
    to move this pool at all) is the same 40 points it was before the
    regime was read.

    Why the centre and not the ends: scaling both ends would widen a
    ceiling faster than a floor (60 × 1.15 is +9, 20 × 1.15 is +3), so a
    single hot cell would hand one persona nine points of ceiling and
    call it the same tilt it gave the floor. A shift moves the whole
    band by one number, which is what "this style suits this tape" means.

    Pure arithmetic, no queries — the allocator calls it inside
    `bounds_for`, and it is tested here on its own numbers.
    """
    lo, hi = float(lo), float(hi)
    width = hi - lo
    centre = (lo + hi) / 2.0
    try:
        shift = centre * (float(factor) - 1.0)
    except (TypeError, ValueError):
        return lo, hi
    shift = _clamp(shift, -MAX_BAND_SHIFT_PCT, MAX_BAND_SHIFT_PCT)
    new_lo = lo + shift
    new_hi = hi + shift
    # bounds_for requires 0 < floor <= ceiling <= 100, so the shifted band
    # is kept inside the account rather than handed back as a bound that
    # would be rejected as "out of range" and silently replaced by the
    # 2-60 defaults — which would UNDO the persona band entirely, the one
    # outcome worse than not shifting at all.
    if new_lo < 0.01:
        new_hi += 0.01 - new_lo
        new_lo = 0.01
    if new_hi > 100.0:
        new_lo -= new_hi - 100.0
        new_hi = 100.0
        new_lo = max(0.01, new_lo)
    return round(new_lo, 4), round(new_hi, 4)
