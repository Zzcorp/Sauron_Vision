"""scan_symbol() and persist_cards() — the entry points the rest of
Sauron Vision should call into for SMC/ICT setup detection.

Two things this module is deliberately strict about:

  * The hit rate on a card is MEASURED or it is absent. It used to be a
    literal dict copied out of the strategy author's PDF (RP_BREAKER 0.76,
    RANGE_MSB_SD 0.61, ...), written to `SmcSignal.rule_hit_rate_30d`,
    rendered as "30d hit" and fed into the conviction bonus that the feed
    sorts by — so on day one, with zero closed signals, the platform was
    showing a marketing number as its own track record and ranking by it.
    Those priors are gone from the code path entirely; anything a card
    reports about its own record now comes from `setup_performance_summary`,
    which counts closed SmcSignal rows. The author's claims survive where
    they belong, as prose in the `signals.smc.detectors` docstrings, where
    nothing can mistake them for a measurement.

  * A setup detected twice is stored once. Every detector evaluates the LAST
    bar, so a live OB_RETEST re-detects on every 900s SignalEngine pass and
    every 1800s universe scan — roughly 18 identical rows per 4h bar per
    symbol. See `persist_cards`.

  * Nothing here is scored with knowledge the trigger bar did not have. The
    killzone term reads the New-York-anchored session table rather than the
    fixed-UTC one, so it does not name the wrong hour for four months of the
    year, and the equal-levels term only counts swings that had already
    printed when the sweep ran. See `killzone_for` and `_swept_cluster`.

  * A structure break is not a shift until something moved it. `structure`
    calls a break on a single close beyond a swing with no size, body or
    velocity test, so a one-tick drift and a violent expansion arrived here
    as the same event and every zone either of them created was traded the
    same way. `scan_symbol` now qualifies breaks through
    `smc.displacement` and drops the measured drifts before a detector sees
    them, and reads a direction for the frame from `smc.bias` so the scan
    stops offering a long and a short on the same chart at the same moment.
    See `scan_symbol`.

  * A detector nothing calls produces nothing. Mitigation blocks, optimal
    trade entry, the Judas swing, the Silver Bullet and SMT divergence were
    each built and tested as primitives and each returned a `setup` string
    `SmcSignal.SETUP_CHOICES` could not store, so the scan could find them and
    the platform could not keep them. All five are wired into `scan_symbol`
    now, through the same displacement qualification, daily-bias filter,
    inducement scoring and conviction trail as the seven that were already
    there. Two of them are session-scoped and are silent on a 4h frame by
    construction — see `scan_symbol` — and the fifth needs a second
    instrument, see `smt_partner_for`.
"""
import logging

logger = logging.getLogger(__name__)


# ── Measured performance ────────────────────────────────────────────────────

# Window for the card's self-reported hit rate. 30 days is what the field is
# named after, what `_signal_performance.html` shows beside it, and what the
# lifecycle tracker's TTLs (168h on 4h, 720h on 1d) let close inside.
HIT_RATE_WINDOW_DAYS = 30


# ── ICT context filters (killzone / equal levels / premium-discount) ────────

# Default for the three ICT filters below. ON: they are the difference
# between ICT and generic pattern matching, and a setup that cannot survive
# them is one the strategy would not have taken. Override per-deployment with
# `SMC_ICT_FILTERS = False` in settings, or per-call with
# `scan_symbol(..., ict_filters=False)` when backtesting the unfiltered feed.
ICT_FILTERS_DEFAULT = True

# Which sessions count as killzones, read from `sessions.ICT_SESSIONS_NY` —
# the New-York-anchored table, NOT the fixed-UTC `KILLZONES_UTC` beside it.
# sessions.py says it plainly: New York moves an hour twice a year, so from
# the first Sunday in November to the second Sunday in March the fixed table
# names the wrong window. A 12:00 UTC trigger in January is 07:00 in New York
# — a dead hour between the London and AM killzones — and the fixed table
# scored it as the New York open.
#
# `ny_lunch` is deliberately absent: it is the hour ICT teaches you to sit
# out, so paying it a confluence bonus would invert the idea. The four windows
# below do not overlap, so their order here is only a tiebreak.
KILLZONE_SESSIONS = ("london", "ny_am", "ny_pm", "asia")

# Conviction points for a setup whose trigger bar opens inside one of those
# killzones. A bonus, never a gate: on the 4h series this platform scans, bars
# open every four hours and two or three of the six opens land in a killzone
# depending on the season, so gating would delete a third of the 4h feed over
# what is really an intraday-timing idea. 8 points is slightly under one
# confluence chip — enough to separate two otherwise identical cards, not
# enough to carry a setup on its own.
KILLZONE_BONUS = 8

# A sweep that takes a cluster of equal highs/lows took ENGINEERED liquidity
# — the stops resting above a double top — not one incidental wick. Worth
# more than the killzone bonus because it is evidence about the setup, not
# about the clock; kept below the R ladder's top rung so geometry still wins.
EQUAL_LEVELS_BONUS = 12

# How near the swept price must sit to a cluster to count as having taken it.
# Same 0.1% that `find_equal_levels` uses to call two swings equal in the
# first place — a wider tolerance here would credit a sweep for taking a
# cluster that the clustering itself says it missed.
EQUAL_LEVELS_MATCH_PCT = 0.001

# How many cluster members must already have printed when the sweep ran. Two,
# because two is what makes a double top: one swing is a level, and the
# engineered-liquidity claim this bonus pays for is specifically that stops
# had piled up against a REPEATED high. `find_equal_levels` uses the same
# floor when it forms a cluster in the first place.
EQUAL_LEVELS_MIN_MEMBERS = 2

# Premium/discount is judged at the ENTRY price against the most recent
# swing-high-to-swing-low leg, not at the last close against the whole
# window: a trend-continuation long retracing into a discount of the last
# impulse is exactly the trade ICT wants, and a window-wide range would
# score it as premium purely because the trend is up.
#
# Wrong side of the leg costs more than either bonus pays, because it is a
# defect in the setup rather than a missing confluence.
PD_WRONG_SIDE_PENALTY = 15

# ...and past the top/bottom quartile of the leg the setup is refused
# outright. `premium_discount` already calls anything above 0.55 premium;
# refusing there would delete every equilibrium retest the strategy teaches.
# At 0.75 the entry is nearer the leg high than the middle, so a long is
# buying the liquidity the setup was supposed to sell into.
PD_REFUSE_POS = 0.75


# ── Displacement, daily bias, inducement ────────────────────────────────────

# These three terms are scored AFTER `build_card`, through
# `apply_conviction_term`, rather than through `evaluate_ict_context`'s
# `adjust`. See that function for why; the short version is that
# `explain.formatter` clamps to 0-100 and writes its trail from the unclamped
# sum, and its own terms are sized to land on exactly those bounds.

# Conviction for the displacement behind the break a setup is built on, scaled
# by the 0-1 score `displacement.measure_displacement` measured. Capped at the
# same 12 the equal-levels bonus pays, because both are evidence about the
# setup itself rather than about the clock. The scale is what makes it worth
# paying at all: a leg that only just qualifies (1.5 ATR, half body, no
# imbalance) scores 0.40 and earns 5, while a 3-ATR expansion that left an
# imbalance behind it scores 0.90 and earns 11.
DISPLACEMENT_MAX_BONUS = 12

# Confidence a measured daily bias needs before the scan refuses the other side
# of the book outright — necessary, and on its own not sufficient.
# `bias.daily_bias` weights higher-timeframe structure 0.4 and location in the
# dealing range 0.3, so 0.7 is the two terms that matter added together. It is
# also, and this is the trap, several other things added together: structure 0.4
# with pool strength 0.2 and room to run 0.1 reaches the same 0.7, and that is a
# direction with the sequence behind it being taken at a poor price. A sum
# cannot tell those apart, so `bias_may_refuse` asks for the two terms by name
# as well as for the number, and the refinements can never delete half the book
# between them.
BIAS_MIN_CONFIDENCE = 0.7

# Conviction for a setup that runs with a bias the scan may act on — the bar
# above, with the two named terms behind it. One confluence chip's worth
# (`explain.formatter.CONFLUENCE_POINTS_PER_CHIP`), and not the 12
# `mtf.HTF_AGREE_BONUS` pays: the bias is read from the same frame as the setup,
# so it is one more thing agreeing rather than the independent second opinion a
# higher timeframe gives. Setups against a bias that has cleared all of that are
# not penalised here — they are gone, dropped by `filter_setups_to_bias`.
BIAS_AGREE_BONUS = 10

# Conviction for a zone whose inducement has been taken. The pool of stops in
# front of a zone is the liquidity the market has to run before it can afford
# to trade there, so a zone price reached THROUGH that pool has completed the
# sequence ICT actually waits for, where a zone with nothing in front of it was
# merely arrived at. One confluence chip's worth, same as the bias bonus above
# and for the same reason: one more thing agreeing about an entry the detectors
# had already found.
#
# There is deliberately no penalty for the other side of the test. An
# inducement sits ABOVE a demand zone and below a supply one, so any bar whose
# low is deep enough to tag a demand zone has already traded through the pool
# guarding it — an unswept pool and a zone being retested cannot both be true
# in this scan, and a threshold that can never fire is not a threshold. The
# unswept case is still reported on the card, at +0, for callers that ask about
# a zone price has not reached yet.
INDUCEMENT_ARMED_BONUS = 10


# ── SFP (Swing Failure Pattern) ─────────────────────────────────────────────

# `SmcSignal.SETUP_CHOICES` has advertised "SFP" since the model was written
# and no detector could emit one. These two numbers are what it takes to.

# The failure must be fresh: the sweep bar is the current bar or the one
# before it. An SFP is traded on the reclaim; three bars later the wick is
# history and the entry is a different trade with a different invalidation.
SFP_MAX_AGE_BARS = 1

# Stop buffer beyond the failure wick, matching the 0.3% the OB-retest setups
# use, and for the same reason: a stop resting exactly on the level gets
# taken out by the next wick of the same size that made the level.
SFP_STOP_BUFFER_PCT = 0.003

# Fallback target when no opposing swing sits beyond the entry — the same 2%
# the OB-retest and FVG-tap detectors fall back to, so an SFP's R is
# comparable with theirs instead of being generated on a different scale.
SFP_FALLBACK_TARGET_PCT = 0.02


# ── Session-scoped setups ───────────────────────────────────────────────────

# Which sessions the scan hunts a Judas swing in. The two killzones the pattern
# is actually taught in: London, whose fake-out sets up the day, and the New
# York AM, whose sets up the second half. `asia` is deliberately absent — the
# Asian range is the liquidity these two sessions are engineered to take, not a
# window that traps anyone — and so is `ny_pm`, which opens into a day whose
# direction is already established, so an early extreme there is the trend
# rather than a trap.
JUDAS_SESSIONS = ("london", "ny_am")


# ── SMT divergence ──────────────────────────────────────────────────────────

# Which second instrument is worth loading a frame for, by symbol. CANDIDATES,
# not claims: what makes two instruments comparable is that their returns
# actually moved together, and `smt.detect_smt_setups` measures exactly that
# over the shared history and refuses the read below `smt.SMT_MIN_CORRELATION`.
# So an entry here costs a wrong pairing nothing but one wasted frame load —
# it can never put a divergence between unrelated charts on the feed.
#
# The pairs are ICT's own: the index triad, the two majors that share a dollar
# leg, the metals pair, and the two crypto majors this deployment scans.
# Symmetric, because either side can be the one that fails to confirm. A symbol
# absent from the table is free: no partner, no second load, no SMT cards.
# Override per-deployment with `SMC_SMT_PARTNERS = {...}` in settings.
SMT_CANDIDATE_PARTNERS = {
    "ES": "NQ", "NQ": "ES", "YM": "ES", "RTY": "ES",
    "SPY": "QQQ", "QQQ": "SPY",
    "EURUSD": "GBPUSD", "GBPUSD": "EURUSD",
    "XAUUSD": "XAGUSD", "XAGUSD": "XAUUSD",
    "BTCUSD": "ETHUSD", "ETHUSD": "BTCUSD",
    "BTCUSDT": "ETHUSDT", "ETHUSDT": "BTCUSDT",
}


# Statuses that mean "this card is still someone's open idea". Mirrors the
# feed query in `dashboard.views_signals_htmx.signal_cards_htmx`.
OPEN_STATUSES = ("ACTIVE", "TRIGGERED")


def ict_filters_enabled():
    """Whether the ICT context filters are on for this deployment."""
    from django.conf import settings
    return bool(getattr(settings, "SMC_ICT_FILTERS", ICT_FILTERS_DEFAULT))


def smt_partner_for(symbol):
    """The symbol worth loading a second frame for, or None.

    Deployment settings win over `SMT_CANDIDATE_PARTNERS`, and a symbol mapped
    to None in the setting is how a deployment switches one pairing off without
    replacing the whole table.

    None is the common answer and it is a cheap one: the scan only pays for a
    second OHLCV read when there is a partner named here, so most symbols never
    load one at all. That is the whole reason this is a lookup rather than a
    correlation sweep of the universe — measuring which instrument correlates
    best with this one would mean reading 90 days of daily bars for every
    instrument on every 900-second pass, to answer a question whose answer
    barely moves. The correlation that decides whether the pairing is real is
    still measured, but only for the one pair, and only on the bars the two
    frames already share; see `smt.detect_smt_setups`.
    """
    from django.conf import settings
    configured = getattr(settings, "SMC_SMT_PARTNERS", None)
    if isinstance(configured, dict) and symbol in configured:
        return configured[symbol]
    return SMT_CANDIDATE_PARTNERS.get(symbol)


def measured_hit_rates(days=HIT_RATE_WINDOW_DAYS):
    """{setup: (hit_rate | None, n_closed)} from closed SmcSignal rows.

    hit_rate is None when the sample is below `performance.MIN_EMPIRICAL_N` —
    a number computed from two closed cards is noise wearing a percent sign,
    and the card renders an em-dash for it.

    Returns None — not {} — when the record could not be read at all, so the
    caller can tell "no closed cards" (n=0, a measurement) apart from "we
    never looked" (n=None). One aggregate per scan_symbol call; the 30-day
    window moves far slower than the 900s scan cadence, but caching it would
    hand every test in the suite a stale copy, so it is simply re-read.
    """
    try:
        from signals.performance import setup_performance_summary
        summary = setup_performance_summary(days=days)
    except Exception as e:
        # Degrade to "not measured", never to zero: the DB being unreachable
        # is not evidence that a setup never wins. SimpleTestCase-based
        # detector tests land here too, by design — they have no DB.
        logger.warning("smc: setup performance unavailable, cards will show "
                       "no hit rate: %s", e)
        return None
    return {
        setup: (p.get("hit_rate") if p.get("is_empirical") else None,
                p.get("n_closed") or 0)
        for setup, p in summary.items()
    }


# ── ICT context ─────────────────────────────────────────────────────────────

def killzone_for(ts):
    """(killzone name or None, whether the question could be answered).

    `in_ny_session` converts to America/New_York before it compares, so the
    same New York hour scores identically in January and July. It returns None
    — distinct from False — when the host has no tz database, and that has to
    survive the trip out of here: a killzone guessed from a fixed offset would
    be wrong for eight months of the year while still reading as a finding, so
    the caller pays no bonus and says on the card that it did not check.
    """
    from signals.smc.sessions import in_ny_session

    for name in KILLZONE_SESSIONS:
        answer = in_ny_session(ts, name)
        if answer is None:
            return None, False
        if answer:
            return name, True
    return None, True


def dealing_range(swings):
    """(high, low) of the current swing-high-to-swing-low leg, or None.

    None means the leg is not measurable — fewer than one swing of each type,
    or an inverted pair — and the premium/discount filter then reports
    nothing rather than defaulting the entry to "equilibrium", which would
    read as a measured verdict.
    """
    last_h = next((s for s in reversed(swings) if s["type"] == "H"), None)
    last_l = next((s for s in reversed(swings) if s["type"] == "L"), None)
    if last_h is None or last_l is None:
        return None
    if last_h["price"] <= last_l["price"]:
        return None
    return last_h["price"], last_l["price"]


def _near(level, price):
    """Whether two prices are the same level within EQUAL_LEVELS_MATCH_PCT."""
    if not level:
        return False
    return abs(level - price) / abs(level) <= EQUAL_LEVELS_MATCH_PCT


def _swept_cluster(sweep, equal_levels, swings=None):
    """The equal-highs/lows cluster this sweep took, AS IT STOOD AT THE SWEEP.

    Returns `(cluster, note)`. `cluster` is {type, price, count} rebuilt from
    the members that had already printed, or None; `note` is a trail line for
    a cluster that matched on price but did not earn the bonus, so a +0 is
    never silent.

    The dating is the point. `find_equal_levels` clusters over the WHOLE
    frame, so a cluster arriving here can be built from swings that printed
    AFTER the bar that supposedly swept it — and paying the engineered-
    liquidity bonus for those is lookahead: at the sweep bar those stops were
    not on the chart to be taken, and every backtest scoring them would be
    scoring the future. Only members whose swing bar closed strictly before
    the sweep count, which is the same window `detect_sweeps` uses when it
    decides which swings a bar could have swept (`s["idx"] < i`), and the
    price and count reported back are theirs rather than the full cluster's.
    """
    if not sweep or not equal_levels:
        return None, None
    want = "EQH" if sweep.get("type") == "SWEEP_HIGH" else "EQL"
    price = sweep.get("swept_price")
    if not price:
        return None, None

    sweep_idx = sweep.get("idx")
    if sweep_idx is None or swings is None:
        # No bar for the sweep, or no swing list to date the cluster against.
        # Undated is exactly the case this guard exists to refuse, so it is
        # refused rather than waved through on the price match alone.
        return None, "equal-level cluster not dateable against the sweep +0"

    stale = None
    for cluster in equal_levels:
        if cluster["type"] != want:
            continue
        prior = [swings[i]["price"] for i in cluster.get("swing_indices", ())
                 if 0 <= i < len(swings) and swings[i]["idx"] < sweep_idx]
        if len(prior) < EQUAL_LEVELS_MIN_MEMBERS:
            if stale is None and _near(cluster.get("price"), price):
                stale = ("equal %s at %.4f had only %d swing(s) on the chart "
                         "when the sweep ran +0"
                         % ("highs" if want == "EQH" else "lows",
                            cluster["price"], len(prior)))
            continue
        # Re-matched against the members that existed, not the full cluster's
        # average: a level the later swings dragged onto the swept price was
        # never the level the sweep took.
        as_it_stood = sum(prior) / len(prior)
        if not _near(as_it_stood, price):
            continue
        return {"type": want, "price": as_it_stood, "count": len(prior)}, None
    return None, stale


def apply_conviction_term(card, delta, why):
    """Move a built card's conviction and write what LANDED into its trail.

    `explain.formatter.score_conviction` clamps to 0-100 but writes its reasons
    from the unclamped sum, and its own terms are sized to reach exactly 0 and
    exactly 100 and no further — base 30, one chip, 3R geometry and a maximal
    hit-rate bonus plus both ICT bonuses is 100 on the nose. Any term added on
    top of that has to be applied out here, or a strong card would render a
    trail summing to 112 under a heading reading "How this scored 100/100".

    Recording the landed delta rather than the nominal one is the same rule
    `signals.mtf` follows, which is why it now calls this instead of keeping
    its own copy.
    """
    before = card.get("conviction", 0) or 0
    after = max(0, min(100, before + delta))
    card["conviction"] = after
    card["reasons"] = list(card.get("reasons", [])) + [
        "%s %+d" % (why, after - before)
    ]
    return card


def structure_break_for(setup_dict, breaks_by_bar):
    """The qualified structure break a setup stands on, or None.

    Two of the detectors hand their break back directly as `bos`, and because
    `scan_symbol` passes the qualified copies into them, that dict already
    carries the displacement fields. The zone setups name it indirectly, by the
    break that created the order block — for a breaker, the block it was
    flipped from, and for a mitigation block the shift away from the unswept
    swing — so those are looked up.

    Keyed by (bar, break type), never by bar alone: a single wide bar can close
    above a swing high and below a swing low, producing two breaks on one
    index, and the zone's own polarity says which of the two made it.

    None is the honest answer for an FVG tap, an SFP, a PO3, an OTE, a Judas
    swing, a Silver Bullet or an SMT read: none of them is built on a structure
    break, so there is no displacement behind one to ask about. The OTE and the
    Silver Bullet do stand on a measured displacement LEG, but a leg is not a
    break and `_displacement_term` would have to be handed a break-shaped dict
    that no break produced to score it.
    """
    bos = setup_dict.get("bos")
    if bos is not None:
        return bos
    zone = setup_dict.get("order_block")
    if zone is None:
        breaker = setup_dict.get("breaker")
        zone = breaker.get("origin_ob") if breaker else None
    if zone is None:
        zone = setup_dict.get("mitigation_block")
    if zone is None:
        return None
    kind = "BOS_UP" if zone.get("type") in ("OB_BULL", "MB_BULL") else "BOS_DOWN"
    return breaks_by_bar.get((zone.get("created_by_break_idx"), kind))


def inducement_for(setup_dict, guards):
    """The inducement pool guarding this setup's zone, or None.

    Only for setups entering AT a live order block. A breaker is a zone whose
    liquidity was already taken and whose polarity has flipped, so the pool
    that once guarded its approach is not the pool standing in front of the
    entry any more — asking the question there would answer a different one.

    A MITIGATION BLOCK is not asked either, and the reason is structural rather
    than a judgement call: `detect_mitigation_blocks` draws the zone on the LAST
    swing of its type before the break, and `find_inducement` looks for a swing
    of that same type between the zone and the break. There is never one — any
    such swing would have been picked as the origin instead — and the origin
    swing itself sits on the far side of the zone, where the separation test
    refuses it. The question is therefore unanswerable by construction, not
    unanswered, and a "+0, no pool in front of the zone" line printed on every
    mitigation card would be a measurement nobody took. Confirmed on 351 blocks
    across 400 synthetic frames and pinned by
    `tests/test_ict_cards.MitigationBlocksCannotHaveAnInducement`.

    Keyed by (zone bar, break bar), because two breaks can pick the same
    opposing candle as their order block and those are two zones with two
    different pools in front of them.
    """
    ob = setup_dict.get("order_block")
    if ob is None:
        return None
    return guards.get((ob.get("idx"), ob.get("created_by_break_idx")))


def _displacement_term(break_dict):
    """(what was measured about the break, (delta, why)) or (None, None).

    Three outcomes, kept apart. A break with a measured displacement is paid in
    proportion to it. A break inside the ATR warm-up was never measured and is
    paid nothing while saying so — reporting it as a drift would retire every
    early break in the frame on the strength of a missing number. A break
    measured as a drift is paid nothing either, and normally never reaches
    here at all: `scan_symbol` drops those before the detectors run.
    """
    if break_dict is None:
        return None, None

    leg = break_dict.get("displacement") or {}
    displaced = break_dict.get("displaced")
    score = break_dict.get("displacement_score")
    kind = break_dict.get("type")
    atr_multiple = leg.get("atr_multiple")
    fact = {
        "break": kind,
        "displaced": displaced,
        "score": round(float(score), 4) if score is not None else None,
        "atr_multiple": round(float(atr_multiple), 2) if atr_multiple is not None else None,
        "bars": leg.get("bars"),
        "has_imbalance": bool(leg.get("has_imbalance")),
    }

    if displaced is None:
        return fact, (0, "displacement behind the %s not measurable — atr has "
                         "not warmed up here" % kind)
    if not displaced:
        return fact, (0, "%s carried no displacement behind it — a drift, not "
                         "a shift" % kind)
    return fact, (
        int(round((score or 0.0) * DISPLACEMENT_MAX_BONUS)),
        "%s displaced %.1f atr in %d bar(s)%s" % (
            kind, fact["atr_multiple"] or 0.0, leg.get("bars") or 0,
            ", leaving an imbalance" if fact["has_imbalance"] else ""),
    )


def bias_terms_behind(bias):
    """(is the sequence behind this bias, is the location behind it).

    Read from the facts `daily_bias` reports — its `structure` label and the
    zone half of its `location` — rather than from its prose reasons, so a
    reworded reason cannot change a verdict.

    A term nobody could measure is False here, not None. The caller is deciding
    whether to delete every setup on the other side of the chart, and a
    measurement that was never taken is not support for doing that.
    """
    direction = bias.get("bias")
    structure = bias.get("structure")
    location = bias.get("location")
    zone = location[0] if location else None
    return (
        (direction == "long" and structure == "up")
        or (direction == "short" and structure == "down"),
        (direction == "long" and zone == "discount")
        or (direction == "short" and zone == "premium"),
    )


def bias_may_refuse(bias):
    """Whether this bias is strong enough to delete the counter-direction book.

    `BIAS_MIN_CONFIDENCE` is where the sequence and the location together land,
    but reaching that number is a weaker claim than having them: the
    refinements `daily_bias` scores on top add to the same total from a worse
    chart. So the two terms are required by name, and the number is kept beside
    them — the card quotes it, and a later reweight in `bias` that moves either
    term cannot quietly reopen the gap.
    """
    if not isinstance(bias, dict):
        return False
    if bias.get("bias") not in ("long", "short"):
        return False
    confidence = bias.get("confidence")
    if confidence is None or confidence < BIAS_MIN_CONFIDENCE:
        return False
    return all(bias_terms_behind(bias))


def _bias_missing_term(bias):
    """Which of the two named terms a bias over the bar is missing, or None.

    Quoting the threshold at a reader who is looking at a confidence above it
    explains nothing, so the card names the term instead.
    """
    structure_behind, location_behind = bias_terms_behind(bias)
    if structure_behind and location_behind:
        return None
    if not structure_behind and not location_behind:
        return "neither the higher-timeframe sequence nor the location is behind it"
    if not structure_behind:
        return "the higher-timeframe sequence is not behind it"
    return "the location in the dealing range is not behind it"


def _bias_term(setup_dict, bias):
    """(what the daily bias measured, (delta, why)) or (None, None).

    A setup only reaches here against an actionable bias when the scan chose not
    to act on it, so the conflicting branch pays nothing and says which way the
    bias read — a card the reader can argue with beats a card that hides the
    disagreement.
    """
    if bias is None:
        return None, None

    direction = bias.get("bias")
    confidence = bias.get("confidence")
    draw = bias.get("draw")
    location = bias.get("location")
    fact = {
        "bias": direction,
        "confidence": confidence,
        "structure": bias.get("structure"),
        # The zone half only. It is the term the refusal turns on, and it
        # belongs on the card beside the structure label for the same reason.
        "location": location[0] if location else None,
        "draw": round(float(draw["price"]), 4) if draw else None,
    }

    if direction is None:
        # `daily_bias` always records why, and its last line is the one that
        # explains the None. An unmeasured bias filters nothing and scores
        # nothing; it is not evidence against the setup.
        why = (bias.get("reasons") or ["no reason recorded"])[-1]
        return fact, (0, "no daily bias measured — %s" % why)

    wanted = "LONG" if direction == "long" else "SHORT"
    label = "%.2f" % confidence if confidence is not None else "unscored"
    clears_bar = confidence is not None and confidence >= BIAS_MIN_CONFIDENCE
    actionable = bias_may_refuse(bias)
    missing = _bias_missing_term(bias) if clears_bar and not actionable else None

    if setup_dict["direction"] != wanted:
        # Three ways to be here and they are not the same statement. Normally
        # the bias was one `filter_setups_to_bias` was never asked to act on,
        # and saying which test it failed explains why the card exists at all.
        # An actionable bias means the caller scored this setup without
        # filtering to it, and the card must not then claim the bias fell short.
        if actionable:
            return fact, (0, "against the %s daily bias (%s confidence), which "
                             "this scan did not filter to"
                             % (direction, label))
        if missing:
            return fact, (0, "daily bias reads %s at %s confidence, but %s — it "
                             "takes both to refuse the other side"
                             % (direction, label, missing))
        return fact, (0, "daily bias reads %s at %s confidence — under the "
                         "%.2f it takes to refuse the other side"
                         % (direction, label, BIAS_MIN_CONFIDENCE))
    if actionable:
        return fact, (BIAS_AGREE_BONUS,
                      "runs with the %s daily bias (%s confidence)"
                      % (direction, label))
    if missing:
        return fact, (0, "daily bias reads %s too, at %s confidence, but %s — "
                         "it takes both to score"
                         % (direction, label, missing))
    return fact, (0, "daily bias reads %s too, at %s confidence — under the "
                     "%.2f it takes to score" % (direction, label,
                                                 BIAS_MIN_CONFIDENCE))


def _inducement_term(setup_dict, inducement):
    """(what the zone's inducement is doing, (delta, why)) or (None, None).

    A zone with no pool in front of it is neither armed nor unarmed — the
    question does not apply — so it is reported as +0 with the reason, not as a
    failed arming test that would hold back a perfectly valid entry forever.

    The unswept branch is +0 rather than a penalty, and no scan card reaches
    it: the pool sits between price and the zone, so a bar that tags the zone
    has already traded through it. See `INDUCEMENT_ARMED_BONUS`.
    """
    if setup_dict.get("order_block") is None:
        return None, None
    if inducement is None:
        return None, (0, "no inducement pool in front of the zone — nothing "
                         "for price to take first")

    from signals.smc.inducement import zone_is_armed

    armed = zone_is_armed(inducement)
    fact = {
        "price": round(float(inducement["price"]), 4),
        "separation_atr": round(float(inducement["separation_atr"]), 2),
        "armed": bool(armed),
    }
    if armed:
        return fact, (INDUCEMENT_ARMED_BONUS,
                      "the %.4f inducement in front of the zone has been taken"
                      % inducement["price"])
    return fact, (0, "the %.4f inducement in front of the zone has not been "
                     "taken — price has not reached through it yet"
                     % inducement["price"])


def evaluate_ict_context(setup_dict, equal_levels, leg, swings=None,
                         bias=None, structure_break=None, inducement=None):
    """Score one setup against the ICT filters.

    `swings` is the frame's swing list — the one `find_equal_levels` was given
    — and it is what dates an equal-levels cluster against the sweep. Omitting
    it costs the liquidity bonus rather than granting it unchecked; see
    `_swept_cluster`.

    `bias`, `structure_break` and `inducement` are the newer primitives, and
    they are scored differently from the three above them: their terms come
    back in `terms` for the caller to apply through `apply_conviction_term`
    AFTER the card is built, instead of being folded into `adjust`. The reason
    is arithmetic, not taste — `explain.formatter` clamps conviction to 0-100
    and writes its trail from the unclamped sum, so a term added inside
    `adjust` can push a strong card past 100 and leave the card's own listed
    reasons summing to a number it does not show. All of them are optional:
    None means the question was not asked, and nothing is scored for it.

    Returns a dict the card carries into `SmcSignal.raw` and `reasons`:

        {"killzone": str|None, "zone": str|None, "zone_pos": float|None,
         "equal_levels": dict|None, "displacement": dict|None,
         "bias": dict|None, "inducement": dict|None,
         "adjust": int, "reasons": [str, ...], "terms": [(int, str), ...],
         "refused": str|None}

    `refused` is a sentence, not a bool, because the caller drops the card
    and the only trace left is the log line it writes.
    """
    from signals.smc.sessions import NY_TZ_NAME
    from signals.smc.structure import premium_discount

    reasons = []
    adjust = 0

    killzone = None
    ts = setup_dict.get("trigger_ts")
    if ts is None:
        # Every detector stamps one; a card without it came from somewhere
        # else, and saying so beats leaving a silent gap in the trail.
        reasons.append("killzone not checked — no trigger timestamp")
    else:
        killzone, checked = killzone_for(ts)
        if not checked:
            reasons.append("killzone not checked — no %s time zone on this "
                           "host" % NY_TZ_NAME)
        elif killzone:
            adjust += KILLZONE_BONUS
            reasons.append("triggered in the %s killzone +%d"
                           % (killzone.replace("_", " "), KILLZONE_BONUS))
        else:
            reasons.append("triggered outside every killzone +0")

    cluster, cluster_note = _swept_cluster(
        setup_dict.get("sweep"), equal_levels, swings)
    if cluster:
        adjust += EQUAL_LEVELS_BONUS
        reasons.append("swept %d equal %s at %.4f +%d" % (
            cluster["count"],
            "highs" if cluster["type"] == "EQH" else "lows",
            cluster["price"], EQUAL_LEVELS_BONUS,
        ))
    elif cluster_note:
        reasons.append(cluster_note)

    zone = None
    pos = None
    refused = None
    if leg is None:
        reasons.append("premium/discount not measurable — no complete leg")
    else:
        high, low = leg
        zone, pos = premium_discount(high, low, setup_dict["entry"])
        is_long = setup_dict["direction"] == "LONG"
        wrong_side = (is_long and zone == "premium") or (not is_long and zone == "discount")
        # Mirrored quartiles: a long is refused in the top 25% of the leg, a
        # short in the bottom 25%.
        beyond_quartile = pos >= PD_REFUSE_POS if is_long else pos <= 1 - PD_REFUSE_POS
        if not wrong_side:
            reasons.append("entry at %.0f%% of the %.4f-%.4f leg (%s) +0"
                           % (pos * 100, low, high, zone))
        elif beyond_quartile:
            refused = ("%s entry at %.0f%% of the %.4f-%.4f leg is deep %s"
                       % (setup_dict["direction"], pos * 100, low, high, zone))
        else:
            adjust -= PD_WRONG_SIDE_PENALTY
            reasons.append("entry at %.0f%% of the %.4f-%.4f leg is %s for a "
                           "%s -%d" % (pos * 100, low, high, zone,
                                       setup_dict["direction"].lower(),
                                       PD_WRONG_SIDE_PENALTY))

    displacement_fact, displacement_term = _displacement_term(structure_break)
    bias_fact, bias_term = _bias_term(setup_dict, bias)
    inducement_fact, inducement_term = _inducement_term(setup_dict, inducement)

    return {
        "killzone": killzone,
        "zone": zone,
        "zone_pos": round(pos, 4) if pos is not None else None,
        "equal_levels": ({"type": cluster["type"], "price": cluster["price"],
                          "count": cluster["count"]} if cluster else None),
        "displacement": displacement_fact,
        "bias": bias_fact,
        "inducement": inducement_fact,
        "adjust": adjust,
        "reasons": reasons,
        # Only the facts above are persisted with the card; `scan_symbol` drops
        # this list once it has applied it, because these are the nominal
        # deltas and the trail records what actually landed after the clamp.
        "terms": [t for t in (displacement_term, bias_term, inducement_term)
                  if t is not None],
        "refused": refused,
    }


# ── SFP detector ────────────────────────────────────────────────────────────

def detect_sfp_setups(df, swings, sfps, current_idx=None):
    """Swing Failure Pattern: fade the bar that failed to hold beyond a swing.

    `signals.smc.liquidity.detect_sfp` supplies the shape (a sweep with a
    stricter wick ratio); this turns the fresh ones into tradeable cards.
    Entry is the reclaim close itself — the failure IS the signal. Waiting for
    price to come back and retest the swept area would be a different setup
    with different levels, and the platform already has it: THREE_TAP.
    """
    setups = []
    if current_idx is None:
        current_idx = len(df) - 1
    if current_idx < 1:
        return setups

    for sw in sfps:
        if sw["idx"] < current_idx - SFP_MAX_AGE_BARS or sw["idx"] > current_idx:
            continue
        entry = float(sw["close"])
        short = sw["type"] == "SWEEP_HIGH"

        if short:
            stop = float(sw["wick_high"]) * (1 + SFP_STOP_BUFFER_PCT)
            target = next((s["price"] for s in reversed(swings)
                           if s["type"] == "L" and s["price"] < entry), None)
            if target is None:
                target = entry * (1 - SFP_FALLBACK_TARGET_PCT)
            denom = stop - entry
            r = (entry - target) / denom if denom > 0 else 0
            invalidation = "close above %.4f" % stop
        else:
            stop = float(sw["wick_low"]) * (1 - SFP_STOP_BUFFER_PCT)
            target = next((s["price"] for s in reversed(swings)
                           if s["type"] == "H" and s["price"] > entry), None)
            if target is None:
                target = entry * (1 + SFP_FALLBACK_TARGET_PCT)
            denom = entry - stop
            r = (target - entry) / denom if denom > 0 else 0
            invalidation = "close below %.4f" % stop

        setups.append({
            "setup": "SFP",
            "direction": "SHORT" if short else "LONG",
            "entry": entry,
            "stop": stop,
            "target": float(target),
            "r_multiple": round(r, 2),
            "sweep": sw,
            "trigger_idx": current_idx,
            "trigger_ts": df.index[current_idx],
            "invalidation": invalidation,
            "components": ["sweep_high" if short else "sweep_low",
                           "close_back_inside", "sfp"],
        })
    return setups


# ── Card language for setups the shared templates do not name ───────────────

def _apply_detector_language(card, setup_dict):
    """Let a detector's own sentence stand in where `explain.templates` is mute.

    `THESIS_TEMPLATES` has a line for the seven original setups and none for the
    five ICT ones, so `build_card` falls through to "OTE setup at 1.2345" — a
    sentence that repeats the setup name and the entry and says nothing about
    why the setup exists. Each of the five builds its own from the numbers it
    measured, next to the geometry that produced them.

    The shared table still wins wherever it has a line, so this never becomes a
    second place card language is edited: adding an OTE entry to
    `explain.templates` retires this branch for OTE without touching anything
    here.
    """
    from signals.explain.templates import THESIS_TEMPLATES

    thesis = setup_dict.get("thesis")
    if thesis and card["setup"] not in THESIS_TEMPLATES:
        card["thesis"] = thesis
    why_now = setup_dict.get("why_now")
    if why_now:
        # Prepended, not replacing: `build_why_now` writes the facts it can read
        # off the shared keys (a sweep, a gap, an order block) and this adds the
        # one it cannot.
        card["why_now"] = "%s %s" % (why_now, card["why_now"])
    return card


def _on_this_bar(setups, current_idx):
    """Only the setups whose trigger bar is the one the scan is standing on.

    `detect_judas_swings` reports every qualifying session in the frame, which
    is what a backtest wants and not what a live scan may publish: a card for a
    London session three weeks ago is an idea nobody can take, and
    `persist_cards` would store the oldest of them and drop the rest as
    duplicates of a setup already open. The other four already evaluate the last
    bar; this holds all five to the rule rather than trusting each to keep it.
    """
    return [s for s in setups if s.get("trigger_idx") == current_idx]


# ── Entry points ────────────────────────────────────────────────────────────

def scan_symbol(symbol, timeframe="4h", bars=500, df=None, ict_filters=None,
                smt_partner=None, partner_df=None):
    """Run all SMC detectors on a symbol/timeframe and return list of cards.

    If `df` is provided, uses it directly (for tests). Otherwise loads
    OHLCV via signals.smc.dataframe.load_ohlcv.

    `ict_filters` defaults to the deployment setting (see
    `ict_filters_enabled`); pass False to get the raw detector output with no
    killzone/liquidity/premium-discount scoring, no displacement or bias
    filtering, and no refusals. It does not switch detectors off — the ICT
    setups are detectors, not filters, and they run either way.

    `smt_partner` / `partner_df` are the second instrument SMT divergence needs.
    Left unset, the partner is looked up with `smt_partner_for` and its frame
    loaded only if there is one; a symbol with no partner is scanned with the
    other twelve detectors and no SMT read, which is the honest outcome rather
    than a missing one. Pass `partner_df` directly to skip the load.

    Thirteen setups come out of here, and two of them are session-scoped: the
    Judas swing needs three bars inside a session window and the Silver Bullet
    needs three consecutive bars inside a one-hour window, so on the 4h series
    this scan usually runs, both are correctly and permanently silent. They earn
    their keep on the intraday frames `mtf.scan_symbol_mtf` also scans.

    With the filters on, the detectors run between two extra steps:

      * Before any of them, structure breaks are qualified by the displacement
        behind them and the measured drifts are dropped. Every zone in this
        scan is drawn from a break, so a drift that reached the detectors
        seeded an order block, a breaker and an MSB retest that ICT would never
        have taken.

      * After all of them, a direction is read for the frame and the setups
        against it are dropped, which is how the scan stops publishing a long
        and a short on one chart on the same bar. That half runs last on
        purpose: `daily_bias` is the most expensive read here, and there is
        nothing to filter when no detector found anything. It only refuses when
        the bias has both the terms `bias_may_refuse` asks for; otherwise
        nothing is filtered, because an unmeasured — or a thinly measured —
        bias is not evidence against either side.
    """
    from signals.smc.dataframe import load_ohlcv
    from signals.smc.pivots import get_swings, classify_swings
    from signals.smc.structure import detect_market_structure_breaks
    from signals.smc.liquidity import detect_sweeps, detect_sfp, find_equal_levels
    from signals.smc.zones import (
        detect_fvgs, detect_order_blocks, find_breakers, detect_ranges,
    )
    from signals.smc.bias import daily_bias, filter_setups_to_bias
    from signals.smc.displacement import qualify_breaks_with_displacement
    from signals.smc.inducement import detect_inducements
    from signals.smc.fibonacci import detect_ote_entries
    from signals.smc.mitigation import (
        detect_mitigation_blocks, detect_mitigation_retest_setups,
    )
    from signals.smc.sessions import SILVER_BULLET_SESSIONS
    from signals.smc.session_setups import (
        detect_judas_swings, detect_silver_bullet_setups,
    )
    from signals.smc.smt import detect_smt_setups
    from signals.smc.detectors import (
        detect_rp_breaker_setups,
        detect_three_tap_setups,
        detect_range_msb_setups,
        detect_reversal_pattern_setups,
        detect_fvg_tap_setups,
        detect_ob_retest_setups,
        detect_po3_setups,
    )
    from signals.explain.formatter import build_card

    if ict_filters is None:
        ict_filters = ict_filters_enabled()

    if df is None:
        df = load_ohlcv(symbol, timeframe, bars)
    if df is None or len(df) < 50:
        return []

    # Resolved before the detectors so a caller-supplied frame and a looked-up
    # one take the same path. No partner means no second read at all: most
    # symbols have none, and the ones that do pay for exactly one extra load.
    if partner_df is None:
        if smt_partner is None:
            smt_partner = smt_partner_for(symbol)
        if smt_partner:
            partner_df = load_ohlcv(smt_partner, timeframe, bars)

    swings = classify_swings(get_swings(df, left=3, right=3))
    detected_breaks = detect_market_structure_breaks(df, swings)

    if ict_filters:
        qualified = qualify_breaks_with_displacement(df, detected_breaks)
        # `displaced` is tri-state and only an explicit False is a drift. A
        # break sitting inside the ATR warm-up was never measured, and dropping
        # those would quietly retire every early break in the frame on the
        # strength of a number that does not exist yet.
        breaks = [b for b in qualified if b["displaced"] is not False]
        drifts = len(qualified) - len(breaks)
        if drifts:
            logger.debug("[smc] %s %s: %d of %d structure breaks were drifts "
                         "with no displacement behind them",
                         symbol, timeframe, drifts, len(qualified))
    else:
        breaks = detected_breaks

    sweeps = detect_sweeps(df, swings)
    fvgs = detect_fvgs(df)
    obs = detect_order_blocks(df, breaks)
    breakers = find_breakers(obs)
    ranges = detect_ranges(swings)

    current_idx = len(df) - 1

    setups = []
    setups.extend(detect_rp_breaker_setups(df, swings, sweeps, breaks, breakers))
    setups.extend(detect_three_tap_setups(df, swings, sweeps))
    setups.extend(detect_range_msb_setups(df, swings, sweeps, breaks, ranges))
    setups.extend(detect_reversal_pattern_setups(df, swings, sweeps, breaks))
    setups.extend(detect_fvg_tap_setups(df, fvgs, swings))
    setups.extend(detect_ob_retest_setups(df, obs, swings))
    setups.extend(detect_po3_setups(df, swings))
    setups.extend(detect_sfp_setups(df, swings, detect_sfp(df, swings)))

    # The five ICT setups. `breaks` is the qualified list, so a mitigation block
    # is drawn from a shift for the same reason an order block is, and the
    # drifts never reach it.
    mitigation_blocks = detect_mitigation_blocks(df, swings, breaks, sweeps=sweeps)
    setups.extend(_on_this_bar(
        detect_mitigation_retest_setups(df, mitigation_blocks, swings),
        current_idx))
    setups.extend(_on_this_bar(detect_ote_entries(df, swings), current_idx))
    for session in JUDAS_SESSIONS:
        setups.extend(_on_this_bar(
            detect_judas_swings(df, swings, session=session), current_idx))
    # All three of ICT's Silver Bullet windows, not just the AM one. A gap stays
    # live for `SILVER_BULLET_MAX_AGE_BARS`, three hours on a 15m frame, so
    # scanning the AM window alone would leave the setup unreachable for most of
    # the trading day rather than merely absent from it.
    #
    # No bias is passed even though the detector accepts one: the scan reads its
    # bias below, after the detectors, because `daily_bias` is the most expensive
    # read here and there is nothing to filter when nothing fired.
    # `filter_setups_to_bias` then applies that one read to every setup on the
    # list, these included.
    for session in SILVER_BULLET_SESSIONS:
        setups.extend(_on_this_bar(
            detect_silver_bullet_setups(df, swings, session=session),
            current_idx))
    if partner_df is not None:
        setups.extend(_on_this_bar(
            detect_smt_setups(df, swings, partner_df, label=symbol,
                              partner_label=smt_partner or "partner"),
            current_idx))

    bias = None
    guards = {}
    breaks_by_bar = {}
    # Nothing below this line matters when no detector found anything, and
    # `daily_bias` is the most expensive read in the scan — it qualifies every
    # break, walks the pools and measures the IPDA ranges.
    if ict_filters and setups:
        # The raw breaks, not the filtered ones: `daily_bias` runs its own
        # displacement qualification and wants the whole picture to do it.
        bias = daily_bias(df, swings, breaks=detected_breaks)
        # The gate is decided here rather than handed to `filter_setups_to_bias`
        # as a confidence floor, because a floor is the test that let a bias at
        # a poor location delete the other side of the book. See
        # `bias_may_refuse`.
        if bias_may_refuse(bias):
            kept = filter_setups_to_bias(setups, bias)
            if len(kept) != len(setups):
                logger.info("[smc] %s %s: %d setup(s) dropped for trading "
                            "against the %s daily bias (%s confidence)",
                            symbol, timeframe, len(setups) - len(kept),
                            bias["bias"], bias.get("confidence"))
            setups = kept
        breaks_by_bar = {(b["idx"], b["type"]): b for b in breaks}
        # One bar can break several swings at once, and `detect_order_blocks`
        # then returns the same zone once per break. Collapsing them here keeps
        # the inducement scan from walking the same bars seven times over.
        zones = {(ob["idx"], ob.get("created_by_break_idx")): ob for ob in obs}
        for pool in detect_inducements(df, swings, list(zones.values())):
            guards[(pool["zone_idx"], pool["break_idx"])] = pool

    hit_rates = measured_hit_rates()
    equal_levels = find_equal_levels(swings) if ict_filters else []
    leg = dealing_range(swings) if ict_filters else None

    cards = []
    for s in setups:
        if hit_rates is None:
            hit_rate, n_closed = None, None
        else:
            hit_rate, n_closed = hit_rates.get(s["setup"], (None, 0))

        ict = (evaluate_ict_context(
            s, equal_levels, leg, swings, bias=bias,
            structure_break=structure_break_for(s, breaks_by_bar),
            inducement=inducement_for(s, guards),
        ) if ict_filters else None)
        if ict and ict["refused"]:
            logger.info("[smc] %s %s %s dropped by the premium/discount "
                        "filter: %s", symbol, timeframe, s["setup"],
                        ict["refused"])
            continue

        card = build_card(s, symbol, timeframe, hit_rate=hit_rate,
                          hit_rate_n=n_closed, ict=ict)
        _apply_detector_language(card, s)
        if ict:
            for delta, why in ict["terms"]:
                apply_conviction_term(card, delta, why)
            # What persists with the card is the measurement, not the nominal
            # delta: the trail already records what each term actually moved,
            # and after a clamp the two disagree.
            ict.pop("terms", None)
        cards.append(card)
    return cards


def persist_cards(cards, symbol, timeframe):
    """Save cards into the SmcSignal table. Returns the created instances.

    Deduped on two levels, because every detector evaluates the LAST bar and
    both schedulers re-scan it: the 900s SignalEngine pass and the 1800s
    universe scan between them re-detected a live OB_RETEST roughly 18 times
    per 4h bar per symbol. That is not just clutter — duplicates share a
    conviction, so one lingering setup fills the whole feed, and they inflate
    `n_closed`, which flips `setup_performance_summary`'s empirical threshold
    on five copies of a single event.

      1. An open card for the same (symbol, timeframe, setup, direction) wins:
         the same zone being retested on three consecutive bars is one idea,
         not three. Mirrors the plain-Signal path in `signals.tasks`.
      2. The DB constraint `uniq_smcsignal_per_bar` catches what the check
         above cannot — two workers racing on the same bar, and two zones of
         the same type detected on one bar — so the IntegrityError is an
         expected outcome here, not a failure.
    """
    from django.db import IntegrityError, transaction
    from signals.models_smc import SmcSignal

    created = []
    skipped = 0
    for c in cards:
        chips = c.get("chips", {})
        if SmcSignal.objects.filter(
            symbol=symbol, timeframe=timeframe, setup=c["setup"],
            direction=c["direction"], status__in=OPEN_STATUSES,
        ).exists():
            skipped += 1
            continue
        try:
            # atomic() per row: on Postgres an IntegrityError poisons the
            # surrounding transaction, so without it one duplicate would take
            # down the whole batch.
            with transaction.atomic():
                sig = SmcSignal.objects.create(
                    symbol=symbol,
                    timeframe=timeframe,
                    setup=c["setup"],
                    direction=c["direction"],
                    headline=c["headline"],
                    thesis=c["thesis"],
                    why_now=c["why_now"],
                    invalidation=c["invalidation"],
                    entry=c["entry"],
                    stop=c["stop"],
                    target=c["target"],
                    r_multiple=c["r_multiple"],
                    chip_structure=chips.get("structure", 0),
                    chip_momentum=chips.get("momentum", 0),
                    chip_flow=chips.get("flow", 0),
                    chip_macro=chips.get("macro", 0),
                    chip_sentiment=chips.get("sentiment", 0),
                    conviction=c.get("conviction", 0),
                    components=c.get("components", []),
                    reasons=c.get("reasons", []),
                    raw={"ict": c.get("ict") or {}},
                    rule_hit_rate_30d=c.get("hit_rate_30d"),
                    rule_hit_rate_n=c.get("hit_rate_n"),
                    trigger_ts=c.get("trigger_ts"),
                )
        except IntegrityError:
            skipped += 1
            continue
        created.append(sig)

    if skipped:
        logger.debug("[smc] %s %s: %d card(s) already on record, %d stored",
                     symbol, timeframe, skipped, len(created))
    return created
