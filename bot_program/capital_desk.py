"""The capital desk — how a tick's opportunities share one risk budget.

The operator's ask, in their words: "The trading rules are too simplistic.
Dedicate an agent that continuously recomputes, from the opportunities
available and the risk, the best way to place capital to maximise gains and
snuff out risk."

This is that agent, and it is DETERMINISTIC. No LLM sizes anything here and
nothing here places an order. The desk ranks candidates the bots have ALREADY
cleared through every gate they own, and its only power over a size is to
shrink it: `size_mult` is never above 1.0, and `execute_entry` re-judges the
multiplied quantity against MAX_RISK_FRACTION, the single-position cap and
the duplicate/theme gates before anything is sent. A desk that is wrong costs
an opportunity. It cannot cost more risk than the fleet had already approved.

WHAT IT ACTUALLY DOES, in one pass per (user, venue):

  1. EXPECTED R (`expected_r`) — what this rule has really paid, on the
     narrowest population that has ten graded fills: this config live, then
     this user's fleet in the class, then everyone's, then paper with a
     haircut, then the Signal lane with a haircut. Below the floor there is
     no expected R at all and the candidate is ranked on conviction times
     its planned net reward-to-risk, flagged `measured=False`. The score is
     NEVER multiplied into a measured expectancy: `allocator_weight` and
     `rule_weight` already carried the rule's expectancy into the size and
     the vote, and multiplying it in again would count one edge three times.

  2. CORRELATION (`correlation_matrix`) — 4h log-return correlation over 45
     days, timestamp-aligned, between every candidate and every open
     position. A pair with fewer than 60 shared bars is UNMEASURED and
     enters the arithmetic at rho = 0, which is recorded on the plan rather
     than assumed away silently.

  3. THE BUDGET (`budget_for`) — 2% of the venue's capital, through the
     drawdown governor on live, minus the risk already at stop in the open
     book. Paper and live never share a budget, a book or a matrix penalty.

  4. THE CHOICE (`choose`) — greedy on expected R per unit of MARGINAL risk,
     where marginal risk is the portfolio increment sqrt((r+ri)'C(r+ri)) -
     sqrt(r'Cr) over the chosen set plus the open book. Two 40-dollar bets
     that correlate 0.9 cost nearly 80; two that correlate 0.0 cost 57. That
     is the whole "snuff out risk" half of the ask, and it is why the best
     candidate in R is sometimes ranked below one that diversifies.

  5. THE RECORD (`plan_for`) — a DeskPlan and one DeskDecision per candidate,
     taken or refused, with the counterfactual fields a displaced entry needs
     so Stage 3 can grade the desk against the fleet it overruled.

SHADOW IS THE DEFAULT. With `capital_desk_mode_live` off the fleet executes
every candidate at its own size exactly as it always has, and the plan is a
record of what the desk WOULD have done — the counterfactual being graded.
The switch goes live only after weeks of positive edge in shadow, the same
bar the share allocator had to clear (2026-09-12).
"""
import hashlib
import logging
import math
import uuid
from collections import defaultdict
from datetime import timedelta

from django.utils import timezone

logger = logging.getLogger(__name__)

# ── The two switches ─────────────────────────────────────────────────────
PIPELINE_COMPONENT = "pipeline_capital_desk"
LIVE_COMPONENT = "capital_desk_mode_live"


# ── Tunables ─────────────────────────────────────────────────────────────
# Sigma of risk-at-stop, open positions plus this tick's new ones, as a
# percent of the venue's capital. 2% is the classic single-trade number used
# here as a BOOK ceiling on purpose: the bots already size each entry at
# their own risk_per_trade_pct, and what nothing measured before was the
# total. Five bots each correctly risking 1% is 5% of the account on one
# tick, and no gate in this platform ever noticed.
DESK_RISK_BUDGET_PCT = 2.0
# One rule may not own more than this share of the tick's new risk. Six
# entries from one squeeze-breakout scan are one idea wearing six tickets;
# the duplicate and theme gates catch the same symbol and the same currency
# leg, and neither catches the same RULE firing across a whole universe.
DESK_MAX_RULE_SHARE = 0.40
# The same for an asset class, looser because a class is a broader bucket
# than a rule and a forex-only fleet would otherwise refuse itself.
DESK_MAX_CLASS_SHARE = 0.60
# Below this multiplier an entry is not worth taking: a quarter-size
# position pays a full round trip, and its R is measured against a stop the
# operator would not have chosen for a bet that small. Displaced instead.
DESK_MIN_MULT = 0.25
# Ten graded fills before a lane may state an expected R. Under it the lane
# is not "slightly worse evidence", it is noise, and the desk says so with
# measured=False rather than ranking on a mean of three.
DESK_MIN_N = 10
DESK_EVIDENCE_DAYS = 180
# Paper fills never queue, never gap through a stop and never partial. The
# default haircut applies when nothing has measured the drag for this rule;
# a measured drag replaces it (see `_paper_factor`).
DESK_PAPER_HAIRCUT = 0.7
# A rule whose recent expectancy has fallen against its own baseline keeps
# its lane and its n — the evidence is real — but ranks at half. Nothing on
# the entry path reads decay_flag today; this is the first thing that does.
DESK_DECAY_HAIRCUT = 0.5

# Correlation. 4h because 1d bars exist only for the EOD classes and the
# desk must rank crypto and forex on the same matrix; 60 shared bars is ten
# days of 4h data, the least that makes a correlation worth acting on.
CORR_BARS = 60
CORR_TIMEFRAME = "4h"
CORR_LOOKBACK_DAYS = 45
CORR_CACHE_S = 600

# A candidate displaced within this window is not re-decided and not
# re-logged. The fleet pass runs every few minutes and a displaced setup
# usually survives several of them; without this the operator would get the
# same displacement notice forty times an hour and the AgentPrediction
# ledger would fill with one call repeated.
DESK_MEMORY_HOURS = 4

# The graded population, identical to bot_grading's: `time_stop` belongs
# inside it, because a rule that keeps timing out is precisely the one whose
# measured expectancy should be falling.
GRADED_OUTCOMES = ("hit_target", "stopped_out", "manual_close", "expired",
                   "time_stop")
# The manual lane is the operator's own hand, not a rule's track record, and
# the two consensus tags are the placeholder `decide()` writes when no rule
# named itself — neither is evidence ABOUT a rule.
EXCLUDED_RULES = ("manual_take", "asset_bot_weighted_consensus",
                  "asset_bot_signal_consensus")

LANE_UNMEASURED = "unmeasured"


# ── Switches ─────────────────────────────────────────────────────────────

def is_desk_enabled() -> bool:
    """True iff the fleet pass runs two-phase and writes plans."""
    from core.platform_control import is_component_enabled
    return is_component_enabled(PIPELINE_COMPONENT)


def is_live_mode() -> bool:
    """True iff the plan is OBEYED — displaced entries skipped, sizes cut."""
    from core.platform_control import is_component_enabled
    return is_component_enabled(LIVE_COMPONENT)


# ── Small arithmetic helpers ─────────────────────────────────────────────

def _f(value, default=0.0) -> float:
    """A float out of a Decimal / str / None without ever raising."""
    try:
        if value is None:
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _sign(direction) -> int:
    """+1 for a long, -1 for a short. The desk correlates BETS, not prices:
    two instruments correlated 0.9 held in opposite directions hedge each
    other, and treating that as concentration would refuse the one entry
    that reduces the book's risk."""
    d = str(direction or "").upper()
    if d in ("SELL", "SHORT", "BEARISH"):
        return -1
    return 1


def _clip(value, lo, hi) -> float:
    return max(lo, min(hi, value))


# ── 1. Expected R ────────────────────────────────────────────────────────

def _stats(rs) -> dict:
    """mean / win rate / average win / average loss over raw graded R.

    Zero-R rows are KEPT in n and in the mean. A trade that closed exactly
    flat happened; dropping it would inflate both the mean and the win rate
    of every rule whose losers are cut at break-even.
    """
    values = [float(r) for r in rs if r is not None]
    n = len(values)
    if n == 0:
        return {}
    wins = [r for r in values if r > 0]
    losses = [r for r in values if r < 0]
    return {
        "e_r": sum(values) / n,
        "p_win": len(wins) / n,
        "avg_win_r": (sum(wins) / len(wins)) if wins else None,
        "avg_loss_r": (sum(losses) / len(losses)) if losses else None,
        "n": n,
    }


def _trade_rs(*, rule, asset_class, paper, cutoff, config=None, user=None):
    """Raw realized_r of the graded closes in one lane. A list, not an
    aggregate: p_win and the average win need the rows, and the population
    is at most a few hundred per rule over six months."""
    from bot_program.models import AssetBotTrade

    qs = (AssetBotTrade.objects
          .filter(status="CLOSED", rule_name=rule, paper=paper,
                  realized_r__isnull=False, outcome__in=GRADED_OUTCOMES,
                  closed_at__gte=cutoff))
    if config is not None:
        qs = qs.filter(config=config)
    else:
        if asset_class:
            qs = qs.filter(asset_class=asset_class)
        if user is not None:
            qs = qs.filter(config__user=user)
    return list(qs.values_list("realized_r", flat=True))


def _signal_rs(*, rule, cutoff):
    """The Signal lane: resolved signals for this rule with an R on them.

    The weakest lane and the last one tried. A Signal's R is what the RULE
    would have paid with no execution at all — no spread, no slippage, no
    partial — so it carries the same haircut as paper.
    """
    from signals.models import Signal

    return list(Signal.objects
                .filter(is_active=False, rule_name=rule,
                        realized_r__isnull=False,
                        expired_at__gte=cutoff)
                .values_list("realized_r", flat=True))


def _paper_factor(rule, asset_class) -> tuple:
    """(factor, why) for a paper-measured lane.

    `paper_live_expectancy_gap` reports gap = live - paper, so the DRAG the
    simulator hides is its negation. When that drag is measured and positive
    it replaces the flat haircut with the number this rule actually lost on
    the way to the broker; anything else falls back to DESK_PAPER_HAIRCUT.
    Clipped into [0, 1] — a drag larger than the whole paper edge means the
    edge does not survive execution, which is an expectancy of zero, not a
    sign flip.
    """
    try:
        from bot_program.bot_grading import paper_live_expectancy_gap
        rows = paper_live_expectancy_gap(rule_name=rule,
                                         asset_class=asset_class or None,
                                         days=DESK_EVIDENCE_DAYS,
                                         min_n=DESK_MIN_N)
        for row in rows:
            gap = row.get("gap")
            if gap is None:
                continue
            drag = -float(gap)
            if drag > 0:
                return (_clip(1.0 - drag, 0.0, 1.0),
                        f"measured paper->live drag {drag:.2f}R")
    except Exception as e:  # noqa: BLE001 — a haircut must never cost a rank
        logger.debug("[desk] paper/live gap unreadable for %s: %s", rule, e)
    return (DESK_PAPER_HAIRCUT,
            f"default paper haircut x{DESK_PAPER_HAIRCUT:.2f}")


def planned_net_rr(cand) -> float:
    """(reward - cost) / (risk + cost), all as fractions of the entry price.

    The same arithmetic `passes_cost_filter` uses to decide whether a setup
    survives its own round trip, reused here because it is the only honest
    reward-to-risk available before the trade exists. The cost comes from the
    function the filter itself called; an unreadable cost model degrades to a
    gross RR rather than refusing to rank the candidate.
    """
    price = _f(cand.price)
    stop = _f(cand.stop)
    target = _f(cand.target)
    if price <= 0:
        return 0.0
    risk = abs(price - stop) / price
    reward = abs(target - price) / price
    if risk <= 0:
        return 0.0
    cost = 0.0
    try:
        from bot_program.asset_engine.risk_levels import (
            round_trip_cost_fraction,
        )
        cost = float(round_trip_cost_fraction(cand.bot.cfg, cand.symbol))
    except Exception as e:  # noqa: BLE001 — see the docstring
        logger.debug("[desk] cost model unreadable for %s: %s",
                     cand.symbol, e)
    return max(0.0, (reward - cost)) / (risk + cost)


def _is_decaying(rule) -> bool:
    """signals.performance.decay_flag, which nothing on the entry path has
    ever read. Unreadable means NOT decaying: a missing measurement must not
    halve a rule's rank."""
    if not rule:
        return False
    try:
        from signals.performance import decay_flag
        return bool(decay_flag(rule).get("is_decaying"))
    except Exception as e:  # noqa: BLE001 — see the docstring
        logger.debug("[desk] decay_flag(%s) unreadable: %s", rule, e)
        return False


def expected_r(cand, *, user, signal_stats=None, now=None) -> dict:
    """What this candidate's rule has really paid, on the narrowest lane
    that clears the floor.

    {"e_r", "p_win", "avg_win_r", "avg_loss_r", "n", "lane", "window_days",
     "measured", "decaying", "reason", "rank_key"}

    The lanes, in order, each on RAW graded rows (never on a pre-aggregated
    multiplier): this config live -> this user's fleet live in the class ->
    every user's fleet live in the class -> fleet paper in the class, cut by
    the paper haircut -> the Signal lane, cut the same way. The FIRST lane
    with n >= DESK_MIN_N wins; narrower evidence beats more of it, because a
    rule's expectancy is a property of the rule AND the broker it trades
    through.

    `rank_key` is what `choose` ranks on. When a lane is measured it is the
    expectancy itself, halved if the rule is decaying. When nothing is
    measured there is NO expected R — e_r stays None and the key falls back
    to conviction times planned net reward-to-risk, which is an ordering, not
    a probability, and is flagged `measured=False` everywhere it surfaces.

    `decision.score` is NEVER multiplied into a measured expectancy, and
    neither is `allocator_weight`: both already shaped the size the candidate
    arrived with, and counting an edge twice is how a modest one becomes a
    conviction.

    `signal_stats` is accepted so a fleet pass can hand down its tick-wide
    aggregate; the lanes above read trades and signals directly, so it is
    unused today and the parameter exists to keep one call signature as the
    evidence set grows.
    """
    now = now or timezone.now()
    cutoff = now - timedelta(days=DESK_EVIDENCE_DAYS)
    rule = (cand.rule_name or "").strip()
    asset_class = cand.asset_class or ""
    decaying = _is_decaying(rule)

    out = {
        "e_r": None, "p_win": None, "avg_win_r": None, "avg_loss_r": None,
        "n": 0, "lane": LANE_UNMEASURED, "window_days": DESK_EVIDENCE_DAYS,
        "measured": False, "decaying": decaying, "reason": "", "rank_key": 0.0,
    }

    def _fallback(reason):
        key = float(_f(cand.decision.score)) * planned_net_rr(cand)
        if decaying:
            key *= DESK_DECAY_HAIRCUT
        out["rank_key"] = key
        out["reason"] = reason
        return out

    if not rule or rule in EXCLUDED_RULES:
        return _fallback(
            "no rule to measure — ranked on conviction x planned net RR")

    lanes = [
        ("config_live", lambda: _trade_rs(rule=rule, asset_class=asset_class,
                                          paper=False, cutoff=cutoff,
                                          config=cand.bot.cfg), 1.0, ""),
        ("user_live", lambda: _trade_rs(rule=rule, asset_class=asset_class,
                                        paper=False, cutoff=cutoff,
                                        user=user), 1.0, ""),
        ("fleet_live", lambda: _trade_rs(rule=rule, asset_class=asset_class,
                                         paper=False, cutoff=cutoff), 1.0, ""),
        ("fleet_paper", lambda: _trade_rs(rule=rule, asset_class=asset_class,
                                          paper=True, cutoff=cutoff),
         None, "paper"),
        ("signal", lambda: _signal_rs(rule=rule, cutoff=cutoff),
         None, "signal"),
    ]

    for lane, fetch, factor, kind in lanes:
        try:
            rows = fetch()
        except Exception as e:  # noqa: BLE001 — a broken lane is not a rank
            logger.warning("[desk] lane %s unreadable for %s: %s",
                           lane, rule, e)
            continue
        stats = _stats(rows)
        if not stats or stats["n"] < DESK_MIN_N:
            continue

        why = f"{lane}: {stats['n']} graded fills over {DESK_EVIDENCE_DAYS}d"
        if factor is None:
            factor, note = _paper_factor(rule, asset_class)
            why = f"{why}, {note}"
        e_r = stats["e_r"] * factor
        out.update({
            "e_r": e_r, "p_win": stats["p_win"],
            "avg_win_r": stats["avg_win_r"],
            "avg_loss_r": stats["avg_loss_r"],
            "n": stats["n"], "lane": lane, "measured": True,
        })
        key = e_r
        if decaying:
            key *= DESK_DECAY_HAIRCUT
            why = f"{why}, decaying x{DESK_DECAY_HAIRCUT:.2f}"
        out["rank_key"] = key
        out["reason"] = why
        return out

    return _fallback(
        f"under the {DESK_MIN_N}-fill floor on every lane — ranked on "
        f"conviction x planned net RR")


# ── 2. Correlation ───────────────────────────────────────────────────────

def _floor_bucket(ts, hours=4):
    """Floor a timestamp onto the timeframe's own boundary.

    Bars from different feeds land on different minutes for the same 4h
    window (one venue stamps 12:00, another 12:00:03, a backfill 11:59).
    Inner-joining on the raw timestamp then finds almost no shared bars and
    every pair comes back unmeasured — which is not a missing history, it is
    an alignment bug that reads exactly like one.
    """
    base = ts.replace(minute=0, second=0, microsecond=0)
    return base - timedelta(hours=base.hour % hours)


def correlation_matrix(user, symbols, *, now=None, timeframe=CORR_TIMEFRAME,
                       min_bars=CORR_BARS, lookback_days=CORR_LOOKBACK_DAYS):
    """Pairwise price correlation over the candidates AND the open book.

    {"rho": {(a, b): float}, "measured": {(a, b), ...}, "n_bars": {(a, b): n},
     "symbols": [...], "pairs_total": int}

    Pair keys are sorted tuples; read them through `rho_of` so a caller
    cannot depend on the order. A pair with fewer than `min_bars` shared
    buckets is NOT in `measured` and its rho is 0.0 — the honest value for
    "nothing was measured", and the count of measured pairs against
    `pairs_total` goes onto the plan so the page can say how much of the
    diversification penalty was assumed away.

    4h and not 1d: daily bars exist only for the EOD classes (stock, etf,
    index, commodity, forex) while 4h exists for every enabled-config symbol,
    and a matrix that silently omits crypto would let a crypto entry look
    like free diversification.
    """
    from django.core.cache import cache
    from django.db.models import Max
    from instruments.models import Instrument
    from market_data.models import PriceData
    from bot_program.models import AssetBotTrade

    now = now or timezone.now()
    wanted = {str(s).strip().upper() for s in (symbols or []) if s}
    try:
        wanted |= {str(s).strip().upper() for s in AssetBotTrade.objects.filter(
            config__user=user, status__in=("OPEN", "CLOSE_PENDING")
        ).values_list("symbol", flat=True)}
    except Exception as e:  # noqa: BLE001 — an unreadable book is rho 0
        logger.warning("[desk] open book unreadable for the matrix: %s", e)

    blank = {"rho": {}, "measured": set(), "n_bars": {},
             "symbols": sorted(wanted), "pairs_total": 0}
    if len(wanted) < 2:
        return blank

    id_by_symbol = dict(Instrument.objects.filter(symbol__in=wanted)
                        .values_list("symbol", "id"))
    if len(id_by_symbol) < 2:
        return blank
    symbol_by_id = {v: k for k, v in id_by_symbol.items()}
    ids = sorted(symbol_by_id)

    pairs_total = len(ids) * (len(ids) - 1) // 2
    cutoff = now - timedelta(days=lookback_days)

    newest = (PriceData.objects
              .filter(instrument_id__in=ids, timeframe=timeframe)
              .aggregate(m=Max("timestamp"))["m"])
    fingerprint = hashlib.md5(
        ",".join(str(i) for i in ids).encode("utf-8")).hexdigest()[:16]
    key = (f"desk:corr:{getattr(user, 'id', 0)}:{timeframe}:{fingerprint}:"
           f"{newest.isoformat() if newest else 'none'}")
    try:
        hit = cache.get(key)
    except Exception:  # noqa: BLE001 — no cache is not an error
        hit = None
    if hit is not None:
        return hit

    rows = (PriceData.objects
            .filter(instrument_id__in=ids, timeframe=timeframe,
                    timestamp__gte=cutoff)
            .values_list("instrument_id", "timestamp", "close"))

    series = defaultdict(dict)
    for inst_id, ts, close in rows:
        px = _f(close)
        if px <= 0:
            continue
        series[symbol_by_id[inst_id]][_floor_bucket(ts)] = px

    out = {"rho": {}, "measured": set(), "n_bars": {},
           "symbols": sorted(symbol_by_id.values()),
           "pairs_total": pairs_total}
    names = sorted(symbol_by_id.values())
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            pair = (a, b)
            sa, sb = series.get(a, {}), series.get(b, {})
            shared = sorted(set(sa) & set(sb))
            out["n_bars"][pair] = len(shared)
            out["rho"][pair] = 0.0
            if len(shared) < min_bars:
                continue
            ra, rb = [], []
            for prev, cur in zip(shared, shared[1:]):
                try:
                    ra.append(math.log(sa[cur] / sa[prev]))
                    rb.append(math.log(sb[cur] / sb[prev]))
                except (ValueError, ZeroDivisionError):
                    ra, rb = [], []
                    break
            if len(ra) < min_bars - 1 or len(ra) < 2:
                continue
            try:
                import numpy as np
                rho = float(np.corrcoef(np.array(ra), np.array(rb))[0, 1])
            except Exception as e:  # noqa: BLE001 — flat series, no numpy
                logger.debug("[desk] corrcoef(%s,%s) failed: %s", a, b, e)
                continue
            if rho != rho:  # NaN: one leg never moved
                continue
            out["rho"][pair] = _clip(rho, -1.0, 1.0)
            out["measured"].add(pair)

    try:
        cache.set(key, out, CORR_CACHE_S)
    except Exception:  # noqa: BLE001 — see above
        pass
    return out


def rho_of(matrix, a, b) -> float:
    """Raw price correlation between two symbols; 1.0 for the same symbol,
    0.0 for an unmeasured pair."""
    if a == b:
        return 1.0
    pair = (a, b) if a < b else (b, a)
    return float((matrix or {}).get("rho", {}).get(pair, 0.0))


def bet_rho(matrix, a, dir_a, b, dir_b) -> float:
    """rho x sign(dir_a) x sign(dir_b) — the correlation of the BETS."""
    return rho_of(matrix, a, b) * _sign(dir_a) * _sign(dir_b)


# ── 3. The open book and the budget ──────────────────────────────────────

def book_risk(user, venue) -> dict:
    """Risk-at-stop already committed on this venue.

    {"risk", "n_open", "unmeasured_open", "entries": [{symbol, direction,
     risk}]}

    Sigma of qty x |entry - metadata.initial_stop_loss| x value_per_unit over
    every OPEN or CLOSE_PENDING row of the venue. CLOSE_PENDING counts: the
    broker position is still live while the platform wants it flat, and a
    budget that forgets it would let the desk re-spend risk that has not
    actually been released.

    THE MANUAL LANE IS IN. Hand-taken positions bypass can_open_new and the
    desk entirely, and they are still the operator's money at risk on the
    same account. Excluding them would let the desk hand out a full 2% budget
    on top of a book the operator had already filled by hand.

    A row with no `initial_stop_loss` in its metadata is UNMEASURED, not
    zero: it is counted in `unmeasured_open` and contributes nothing, so the
    plan can say how much of its own book it could not price.
    """
    from bot_program.models import AssetBotTrade

    paper = (str(venue) == "paper")
    out = {"risk": 0.0, "n_open": 0, "unmeasured_open": 0, "entries": []}
    rows = AssetBotTrade.objects.filter(
        config__user=user, paper=paper,
        status__in=("OPEN", "CLOSE_PENDING"),
    ).only("symbol", "side", "qty", "entry_price", "metadata")
    for row in rows:
        out["n_open"] += 1
        meta = row.metadata or {}
        stop = meta.get("initial_stop_loss")
        if stop is None:
            out["unmeasured_open"] += 1
            continue
        vpu = _f(meta.get("value_per_unit", 1.0), 1.0)
        risk = _f(row.qty) * abs(_f(row.entry_price) - _f(stop)) * vpu
        if risk <= 0:
            out["unmeasured_open"] += 1
            continue
        out["risk"] += risk
        out["entries"].append({"symbol": (row.symbol or "").upper(),
                               "direction": row.side, "risk": risk})
    return out


def venue_capital(user, venue) -> float:
    """Sigma of `capital` over this user's ENABLED configs that can FILL on
    this venue.

    THE DENOMINATOR, stated plainly: the desk's budget is a percent of the
    capital the operator has assigned to the bots that can trade on this
    venue right now — not the broker's equity, and not the portfolio book.
    That is the same pool `_size_position` divides its risk budget by and the
    same pool MAX_RISK_FRACTION is measured against, so the desk's ceiling
    and the per-order ceiling are denominated in the same money. A disabled
    config contributes nothing: its capital cannot be spent this tick.

    LIVE is live-mode configs only — it is the only budget guarding real
    money and nothing that cannot reach the broker may enlarge it.

    PAPER is every enabled config that can EMIT a paper candidate, which is
    the paper-mode ones AND the live-mode ones. `propose_entry` files a
    candidate under venue='paper' when `cfg.mode == 'paper'` OR
    `stage['force_paper']`, and `stage_policy` forces the paper venue for
    every rule with no RuleControl row and every rule still at the paper
    stage — which today is nearly all of them. Summing paper-mode configs
    alone therefore returned 0.00 for an operator whose configs are all
    mode='live' (the live deployment's own shape), every paper-venue
    candidate was displaced with 'budget — 0.00 free', and because SHADOW
    executes everything anyway the fleet would only have gone quiet on the
    day `capital_desk_mode_live` was switched on (2026-09-12).

    A live config's capital consequently appears in BOTH venues'
    denominators. That is correct and deliberate: these are two separate
    books which are never summed, never netted and never ranked against each
    other. The two budgets exist so a paper flood is never ranked against
    real money — not because paper capital needs protecting — so the paper
    denominator's job is to size the paper book, and the live budget remains
    the only ceiling standing in front of the broker.
    """
    from bot_program.models import AssetBotConfig

    modes = ("paper", "live") if str(venue) == "paper" else ("live",)
    total = 0.0
    for cap in (AssetBotConfig.objects
                .filter(user=user, enabled=True, mode__in=modes)
                .values_list("capital", flat=True)):
        total += _f(cap)
    return total


def budget_for(user, venue, *, now=None) -> dict:
    """What is left to spend on new risk this tick.

    {"budget", "gross", "capital", "book_risk", "unmeasured_open",
     "governor", "drawdown_pct", "entries", "reason"}

    gross = venue_capital x DESK_RISK_BUDGET_PCT/100, times the drawdown
    governor ON LIVE ONLY and only when a reading exists. Paper has no
    account to draw down and a governor there would shrink the very lane that
    produces the evidence to promote a rule. budget = gross - book_risk, and
    it can be negative, which means the book is already past the ceiling and
    nothing new is taken.
    """
    now = now or timezone.now()
    capital = venue_capital(user, venue)
    gross = capital * DESK_RISK_BUDGET_PCT / 100.0
    governor, dd_pct, reason = 1.0, None, ""
    if str(venue) == "live":
        try:
            from bot_program.capital_truth import equity_drawdown
            from bot_program.share_allocator import governor_for
            reading = equity_drawdown(user)
            if reading is not None:
                dd_pct = float(reading.get("drawdown_pct") or 0.0)
                governor = float(governor_for(dd_pct))
                reason = (f"governor {governor:.2f} — "
                          f"{dd_pct * 100:.1f}% under the high-water mark")
            else:
                reason = "no equity reading — governor 1.00"
        except Exception as e:  # noqa: BLE001 — a missing governor is 1.0
            logger.warning("[desk] drawdown governor unreadable: %s", e)
            reason = f"governor unreadable ({e}) — 1.00"
    else:
        reason = "paper venue — no drawdown governor"
    gross *= governor
    book = book_risk(user, venue)
    return {
        "budget": gross - book["risk"], "gross": gross, "capital": capital,
        "book_risk": book["risk"], "unmeasured_open": book["unmeasured_open"],
        "n_open": book["n_open"], "entries": book["entries"],
        "governor": governor, "drawdown_pct": dd_pct, "reason": reason,
    }


# ── 4. The choice ────────────────────────────────────────────────────────

def _portfolio_risk(entries, matrix) -> float:
    """sqrt(r' C r) over a set of bets — the book's risk at stop AFTER
    correlation. Sigma of the raw risks is what every naive budget uses and
    it is wrong in both directions: it over-counts a hedged pair and
    under-counts six EUR crosses that mark together."""
    total = 0.0
    for a in entries:
        for b in entries:
            if a is b:
                total += a["risk"] * b["risk"]
                continue
            total += (a["risk"] * b["risk"]
                      * bet_rho(matrix, a["symbol"], a["direction"],
                                b["symbol"], b["direction"]))
    return math.sqrt(max(0.0, total))


def _entry_of(cand, mult=1.0) -> dict:
    return {"symbol": (cand.symbol or "").upper(),
            "direction": cand.direction,
            "risk": _f(cand.risk_dollars_default) * float(mult)}


def _corr_max(cand, entries, matrix):
    """The largest |bet correlation| between this candidate and anything
    already in the set. None when no pair was measured — an unmeasured
    matrix must not render as 'uncorrelated' on the page."""
    best = None
    sym = (cand.symbol or "").upper()
    for e in entries:
        pair = (sym, e["symbol"]) if sym < e["symbol"] else (e["symbol"], sym)
        if sym != e["symbol"] and pair not in (matrix or {}).get("measured", set()):
            continue
        value = bet_rho(matrix, sym, cand.direction, e["symbol"],
                        e["direction"])
        if best is None or abs(value) > abs(best):
            best = value
    return best


def _slots_left(cand, taken) -> int:
    """max_concurrent_positions minus what is already open on this config,
    minus what this plan has already given it."""
    from bot_program.models import AssetBotTrade
    cfg = cand.bot.cfg
    try:
        open_now = AssetBotTrade.objects.filter(
            config=cfg, status__in=("OPEN", "CLOSE_PENDING")).count()
    except Exception as e:  # noqa: BLE001 — unreadable means do not refuse
        logger.warning("[desk] slot count unreadable for cfg %s: %s",
                       cfg.pk, e)
        return 1
    return int(cfg.max_concurrent_positions or 0) - open_now - taken


def choose(candidates, *, user, venue, book, rho, budget,
           evidence=None, gates=None, signal_stats=None, now=None) -> dict:
    """Rank a tick's candidates against one budget and return the plan.

    Returns a dict — NOT a model — so the arithmetic can be tested and
    re-read without a database write:

      {"venue", "budget", "book_risk", "new_risk_chosen",
       "committed_marginal", "n_candidates", "n_chosen", "n_resized",
       "n_displaced", "n_duplicate", "matrix_pairs_measured",
       "matrix_pairs_total", "decisions": [...]}

    `new_risk_chosen` is the RAW sum of risk-at-stop over what was taken;
    `committed_marginal` is what the BUDGET was spent in — the correlation-
    aware increment of each pick, which is the quantity `remaining` below is
    measured in. They are different numbers and must never be swapped: the
    first is what the account has at stake if every stop is hit, the second
    is what the chooser spent. Both go onto the plan.

    Each decision carries its candidate under "cand" so the executing phase
    can hand it straight back to the bot that made it.

    The order of business per pick, and why:
      1. THE CONFIG'S OWN SLOT. A config at max_concurrent cannot take the
         entry however good it is, and finding that out at execution time
         would waste the pick.
      2. THE BUDGET, spent in MARGINAL risk. Full size when it fits, else
         cut to what is left, else displaced — never clamped upward, never
         above 1.0.
      3. THE RULE SHARE, then THE CLASS SHARE, on the size actually taken.
         Judged against the BUDGET — the tick's risk allowance — rather than
         against the tick's realised total, and skipped entirely while the
         bucket is still empty. Both details exist for the same reason: a
         cap denominated in "this tick's new risk" makes the only candidate
         of a quiet tick 100% of it, and a cap applied to the first entry of
         a rule refuses every entry a one-config fleet could ever make.
         These caps bound the SECOND ticket on one idea; the budget bounds
         the first.

    Ties and duplicates are settled before the loop: the same (symbol,
    direction) proposed by two configs is ONE bet, and the copy that keeps it
    is the one with measured evidence, then the higher key. The loser is
    'duplicate', not 'displaced' — nothing refused it.
    """
    now = now or timezone.now()
    matrix = rho or {}
    budget = float(budget)
    share_base = max(0.0, budget)
    evidence = dict(evidence or {})
    gate_cache = dict(gates or {})

    decisions = []
    rank = 0

    # ── evidence, once per candidate ────────────────────────────────────
    live = []
    for cand in candidates:
        ev = evidence.get(id(cand))
        if ev is None:
            try:
                ev = expected_r(cand, user=user, signal_stats=signal_stats,
                                now=now)
            except Exception as e:  # noqa: BLE001 — rank it unmeasured
                logger.warning("[desk] expected_r failed for %s: %s",
                               cand.symbol, e)
                ev = {"e_r": None, "p_win": None, "n": 0,
                      "lane": LANE_UNMEASURED, "measured": False,
                      "decaying": False, "rank_key": 0.0,
                      "reason": f"evidence unreadable: {e}"[:120]}
            evidence[id(cand)] = ev
        live.append(cand)

    # ── dedup: one expression per bet ───────────────────────────────────
    by_bet = defaultdict(list)
    for cand in live:
        by_bet[((cand.symbol or "").upper(), cand.direction)].append(cand)
    kept, dupes = [], []
    for _bet, group in by_bet.items():
        if len(group) == 1:
            kept.append(group[0])
            continue
        group.sort(key=lambda c: (evidence[id(c)]["measured"],
                                  evidence[id(c)]["rank_key"]), reverse=True)
        kept.append(group[0])
        for loser in group[1:]:
            dupes.append((loser, group[0]))

    # ── greedy on key per unit of marginal risk ─────────────────────────
    open_entries = list((book or {}).get("entries") or [])
    sel = []
    committed = 0.0
    new_risk = 0.0
    rule_risk = defaultdict(float)
    class_risk = defaultdict(float)
    taken_by_cfg = defaultdict(int)
    pool = list(kept)

    while pool:
        base = _portfolio_risk(open_entries + sel, matrix)
        scored = []
        for cand in pool:
            mr = _portfolio_risk(open_entries + sel + [_entry_of(cand)],
                                 matrix) - base
            mr = max(0.0, mr)
            key = float(evidence[id(cand)]["rank_key"])
            if mr > 1e-9:
                ratio = key / mr
            else:
                ratio = float("inf") if key > 0 else float("-inf")
            scored.append((ratio, key, cand, mr))
        # Deterministic: ratio, then key, then the symbol, so two identical
        # candidates never depend on dict ordering.
        scored.sort(key=lambda row: (row[0], row[1], row[2].symbol),
                    reverse=True)
        _ratio, key, cand, mr = scored[0]
        pool.remove(cand)
        rank += 1
        ev = evidence[id(cand)]
        risk1 = _f(cand.risk_dollars_default)
        row = {
            "cand": cand, "rank": rank, "ev": ev, "marginal_risk": mr,
            "corr_max": _corr_max(cand, open_entries + sel, matrix),
            "size_mult": 1.0, "outcome": "displaced", "reason": "",
        }

        # 1. the config's own slot / gate
        gate_ok, gate_reason = gate_cache.get(cand.cfg_id, (None, ""))
        if gate_ok is None:
            try:
                gate_ok, gate_reason = cand.bot.can_open_new()
            except Exception as e:  # noqa: BLE001 — an unreadable gate is open
                gate_ok, gate_reason = True, f"gate unreadable: {e}"
            gate_cache[cand.cfg_id] = (gate_ok, gate_reason)
        if not gate_ok:
            row["reason"] = f"config_halted — {gate_reason}"[:120]
            decisions.append(row)
            continue
        slots = _slots_left(cand, taken_by_cfg[cand.cfg_id])
        if slots <= 0:
            row["reason"] = (
                f"config_halted — no slot left on "
                f"{cand.bot.cfg.name} (max {cand.bot.cfg.max_concurrent_positions})"
            )[:120]
            decisions.append(row)
            continue

        # 2. the budget, spent in marginal risk
        remaining = budget - committed
        if mr <= remaining + 1e-9:
            mult = 1.0
        elif remaining > 0 and mr > 0:
            mult = remaining / mr
            if mult < DESK_MIN_MULT:
                row["reason"] = (
                    f"budget — {remaining:,.2f} free against {mr:,.2f} of "
                    f"marginal risk, under the {DESK_MIN_MULT:.2f} floor")[:120]
                decisions.append(row)
                continue
        else:
            row["reason"] = (
                f"budget — {max(0.0, remaining):,.2f} free against "
                f"{mr:,.2f} of marginal risk")[:120]
            decisions.append(row)
            continue

        # 3. the rule share, then the class share, on the size actually taken
        rule = cand.rule_name or "(unnamed)"
        taken_risk = risk1 * mult
        # A CONCENTRATION CAP CANNOT BIND ON AN EMPTY BUCKET. Measured
        # against the budget, one entry of 2% risk is 100% of a 2% budget,
        # so a cap applied to the first candidate of a rule (or of a class)
        # would refuse every entry a single-config fleet ever proposed — the
        # cap would read as a working limit while actually switching the
        # bots off. What these caps are for is the SECOND, third and sixth
        # ticket on one idea; the budget already bounds the first.
        if share_base > 0:
            after_rule = rule_risk[rule] + taken_risk
            if (rule_risk[rule] > 0
                    and after_rule > DESK_MAX_RULE_SHARE * share_base + 1e-9):
                row["reason"] = (
                    f"rule_share — {rule} would hold "
                    f"{after_rule / share_base * 100:.0f}% of the tick's risk "
                    f"(cap {DESK_MAX_RULE_SHARE * 100:.0f}%)")[:120]
                decisions.append(row)
                continue
            after_class = class_risk[cand.asset_class] + taken_risk
            if (class_risk[cand.asset_class] > 0
                    and after_class > DESK_MAX_CLASS_SHARE * share_base + 1e-9):
                row["reason"] = (
                    f"class_share — {cand.asset_class} would hold "
                    f"{after_class / share_base * 100:.0f}% of the tick's "
                    f"risk (cap {DESK_MAX_CLASS_SHARE * 100:.0f}%)")[:120]
                decisions.append(row)
                continue

        # taken
        row["size_mult"] = mult
        row["outcome"] = "chosen" if mult >= 1.0 - 1e-9 else "resized"
        if row["outcome"] == "chosen":
            row["reason"] = (
                f"taken at full size — adds {mr:,.2f} of the "
                f"{max(0.0, remaining):,.2f} free")[:120]
        else:
            row["reason"] = (
                f"resized to x{mult:.2f} — {remaining:,.2f} free against "
                f"{mr:,.2f} of marginal risk")[:120]
        sel.append(_entry_of(cand, mult))
        committed += mr * mult
        new_risk += taken_risk
        rule_risk[rule] += taken_risk
        class_risk[cand.asset_class] += taken_risk
        taken_by_cfg[cand.cfg_id] += 1
        decisions.append(row)

    # ── the duplicates, after the ladder ────────────────────────────────
    for loser, winner in sorted(dupes,
                                key=lambda p: -evidence[id(p[0])]["rank_key"]):
        rank += 1
        decisions.append({
            "cand": loser, "rank": rank, "ev": evidence[id(loser)],
            "marginal_risk": 0.0,
            "corr_max": None, "size_mult": 1.0, "outcome": "duplicate",
            "reason": (
                f"duplicate — config #{winner.cfg_id} proposed the same "
                f"{loser.symbol} {loser.direction} on the "
                f"{evidence[id(winner)]['lane']} lane")[:120],
        })

    counts = defaultdict(int)
    for row in decisions:
        counts[row["outcome"]] += 1
    return {
        "venue": venue,
        "budget": budget,
        "book_risk": float((book or {}).get("risk", 0.0)),
        "new_risk_chosen": new_risk,
        "committed_marginal": committed,
        "n_candidates": len(decisions),
        "n_chosen": counts["chosen"],
        "n_resized": counts["resized"],
        "n_displaced": counts["displaced"],
        "n_duplicate": counts["duplicate"],
        "matrix_pairs_measured": len(matrix.get("measured", ()) or ()),
        "matrix_pairs_total": int(matrix.get("pairs_total", 0) or 0),
        "decisions": decisions,
    }


# ── 5. The record ────────────────────────────────────────────────────────

def _remembered(user, venue, candidates, *, now):
    """{(cfg_id, symbol, direction, rule): previous decision id} for the
    candidates displaced inside DESK_MEMORY_HOURS.

    Re-deciding one every few minutes would be honest but useless: the same
    displacement would be written forty times an hour, the operator's
    AgentPrediction ledger would carry one call repeated, and the ladder on
    /desk/ would be a list of the same six refusals. The memory skips them
    with the id of the decision that already explains why.
    """
    from bot_program.models import DeskDecision

    if not candidates:
        return {}
    cutoff = now - timedelta(hours=DESK_MEMORY_HOURS)
    index = {}
    try:
        rows = (DeskDecision.objects
                .filter(outcome=DeskDecision.OUTCOME_DISPLACED,
                        created_at__gte=cutoff, plan__user=user,
                        plan__venue=venue,
                        config_id__in={c.cfg_id for c in candidates})
                .order_by("-created_at")
                .values("id", "config_id", "symbol", "direction",
                        "rule_name", "reason"))
        for row in rows:
            key = (row["config_id"], row["symbol"], row["direction"],
                   row["rule_name"])
            index.setdefault(key, row)
    except Exception as e:  # noqa: BLE001 — no memory is not an error
        logger.warning("[desk] desk memory unreadable: %s", e)
    return index


def _audit_plan(plan, extra=None):
    """One audit row per plan, through the hook in bot_program.audit that
    every other chained event uses. Never raises: a desk that cannot write
    its audit line still has a plan worth executing."""
    try:
        from bot_program.audit import record_desk_plan
        record_desk_plan(plan, extra)
    except Exception as e:  # noqa: BLE001 — see the docstring
        logger.warning("[desk] audit write failed for plan %s: %s",
                       getattr(plan, "pk", "?"), e)


def plan_for(user, venue, candidates, *, tick_id=None, now=None,
             signal_stats=None, not_desked=None, mode=None) -> dict:
    """Rank one venue's candidates, write the plan, and return what to run.

    {"plan": DeskPlan, "decisions": [(DeskDecision, cand)], "remembered":
     [(cand, previous_id, reason)], "mode": "shadow"|"live"}

    The decisions are returned in RANK order so the executing phase offers
    the money in the order the desk ranked it. `remembered` are the
    candidates the desk memory skipped: they get no new row and no new
    prediction, and in SHADOW they still execute at full size like every
    other candidate, because shadow must leave the fleet byte-for-byte as it
    was.
    """
    from bot_program.models import DeskPlan, DeskDecision

    now = now or timezone.now()
    mode = mode or (DeskPlan.MODE_LIVE if is_live_mode()
                    else DeskPlan.MODE_SHADOW)
    mine = [c for c in (candidates or []) if c.venue == venue]

    memory = _remembered(user, venue, mine, now=now)
    remembered, fresh = [], []
    for cand in mine:
        key = (cand.cfg_id, cand.symbol, cand.direction, cand.rule_name)
        prev = memory.get(key)
        if prev is not None:
            remembered.append((cand, prev["id"], prev.get("reason") or ""))
        else:
            fresh.append(cand)

    budget_info = budget_for(user, venue, now=now)
    book = {"risk": budget_info["book_risk"], "entries": budget_info["entries"]}
    matrix = correlation_matrix(user, [c.symbol for c in fresh], now=now)
    result = choose(fresh, user=user, venue=venue, book=book, rho=matrix,
                    budget=budget_info["budget"], signal_stats=signal_stats,
                    now=now)

    extras = list(not_desked or [])
    plan = DeskPlan.objects.create(
        tick_id=tick_id or uuid.uuid4(), user=user, venue=venue, mode=mode,
        budget=round(budget_info["budget"], 2),
        book_risk=round(budget_info["book_risk"], 2),
        new_risk_chosen=round(result["new_risk_chosen"], 2),
        # The budget was spent in MARGINAL risk, so the plan records the
        # marginal total as well as the raw one: /desk/ draws the number the
        # chooser actually consumed against the budget, and the raw
        # risk-at-stop beside it as its own labelled figure.
        new_risk_marginal=round(result["committed_marginal"], 2),
        n_candidates=result["n_candidates"] + len(extras),
        n_chosen=result["n_chosen"], n_resized=result["n_resized"],
        n_displaced=result["n_displaced"],
        n_duplicate=result["n_duplicate"], n_not_desked=len(extras),
        matrix_pairs_measured=result["matrix_pairs_measured"],
        matrix_pairs_total=result["matrix_pairs_total"],
    )

    written = []
    for row in result["decisions"]:
        cand = row["cand"]
        ev = row["ev"]
        written.append((DeskDecision.objects.create(
            plan=plan, config=cand.bot.cfg, symbol=cand.symbol,
            direction=cand.direction, rule_name=(cand.rule_name or "")[:100],
            lane=ev.get("lane", LANE_UNMEASURED), n=int(ev.get("n") or 0),
            e_r=ev.get("e_r"), p_win=ev.get("p_win"),
            rank_key=float(ev.get("rank_key") or 0.0),
            measured=bool(ev.get("measured")),
            decaying=bool(ev.get("decaying")),
            risk_dollars_default=round(_f(cand.risk_dollars_default), 2),
            marginal_risk=round(_f(row["marginal_risk"]), 2),
            corr_max=row["corr_max"], rank=row["rank"],
            outcome=row["outcome"], reason=row["reason"][:120],
            size_mult=float(row["size_mult"]),
            qty_default=round(_f(cand.qty_default), 8),
            price=round(_f(cand.price), 8), stop=round(_f(cand.stop), 8),
            target=round(_f(cand.target), 8),
            horizon_hours=float(cand.horizon_hours),
        ), cand))

    rank = result["n_candidates"]
    for entry in extras:
        rank += 1
        DeskDecision.objects.create(
            plan=plan, config_id=entry["config_id"],
            symbol=entry.get("symbol", "")[:40],
            direction=entry.get("direction", "")[:4],
            rule_name=(entry.get("rule_name") or "")[:100],
            lane=LANE_UNMEASURED, n=0, rank_key=0.0, measured=False,
            rank=rank, outcome=DeskDecision.OUTCOME_NOT_DESKED,
            reason=("the options lane trades through scan_symbol whole — "
                    "never displaced, never resized")[:120],
            qty_default=round(_f(entry.get("qty")), 8),
            price=round(_f(entry.get("price")), 8),
            stop=entry.get("stop"), target=entry.get("target"),
            trade_id=entry.get("trade_id"),
            qty_final=round(_f(entry.get("qty")), 8),
        )

    _audit_plan(plan, {"remembered": len(remembered),
                       "governor": budget_info["governor"],
                       "capital": budget_info["capital"]})
    return {"plan": plan, "decisions": written, "remembered": remembered,
            "mode": mode, "budget_info": budget_info, "matrix": matrix}


def fail_open_plan(user, venue, *, error, tick_id=None, mode=None):
    """The plan row a failed desk leaves behind before the fleet runs
    undesked. A desk that cannot rank must not stop the bots — but it must
    not be invisible either, and an empty plan with an error on it is how
    /desk/ and the audit chain find out."""
    from bot_program.models import DeskPlan

    try:
        return DeskPlan.objects.create(
            tick_id=tick_id or uuid.uuid4(), user=user, venue=venue,
            mode=mode or (DeskPlan.MODE_LIVE if is_live_mode()
                          else DeskPlan.MODE_SHADOW),
            error=str(error)[:2000],
        )
    except Exception as e:  # noqa: BLE001 — nothing here may raise
        logger.error("[desk] could not even record the failure: %s", e)
        return None


# ── 6. The grade ─────────────────────────────────────────────────────────
#
# A desk that ranks is only worth keeping if the ranking beats the fleet it
# overruled, and that comparison is impossible unless the REFUSED entries are
# priced too. So every displaced and duplicate decision carries the five
# fields a bracket needs — price, stop, target, direction, horizon — and this
# is where those get walked against the bars that actually printed.
#
# The desk is then scored on the DIFFERENCE between two sets over one plan:
#
#   the desk's set     Σ over chosen/resized of realized_r × size_mult
#   the default set    Σ over every desked candidate AT SIZE 1.0 — the chosen
#                      ones' realized_r plus the displaced ones'
#                      counterfactual_r — which is what the fleet would have
#                      booked with no desk in the picture at all
#
# edge_r is the first minus the second. Positive means the ranking earned its
# keep on that plan. It is NEVER an opinion about an unresolved row: an
# ungradeable decision leaves both sums and is counted separately, because a
# missing measurement folded in as zero would flatter whichever side of the
# subtraction happened to hold more of them (2026-09-12).

# 1h first, then 4h, then 1d: the finest bar that exists for the symbol wins,
# because a bracket walked on daily bars cannot say which of the stop and the
# target was touched first on the day both were.
COUNTERFACTUAL_TIMEFRAMES = ("1h", "4h", "1d")
# How long past its horizon a decision keeps waiting for bars before it is
# called ungradeable. The bar refresh runs every 600 s over the enabled
# configs' symbols; two days is long enough that a worker outage or a feed
# gap resolves itself, and short enough that a plan is graded the same week.
COUNTERFACTUAL_GRACE_HOURS = 48.0
# A plan is graded when every decision on it is resolved OR this long has
# passed since it was made. Without the second clause one symbol that never
# prints a bar would hold a whole plan — and therefore the desk's whole
# score — unresolved forever.
PLAN_GRADE_GRACE_HOURS = 48.0
# Unresolved decisions are walked in Python (the horizon is a per-row float,
# and adding it to a timestamp is not something a portable ORM filter can
# do), so the pass is bounded. At one fleet tick every few minutes this is
# several days of backlog; the task runs nightly.
DESK_RESOLVE_BATCH = 2000

CF_STOP = "stop"                  # the stop printed first
CF_TARGET = "target"              # the target printed first
CF_OPEN = "open"                  # neither — marked to market at the horizon
CF_UNGRADEABLE = "ungradeable"    # no bars, or no risk to measure R against

# The outcomes that are the desk's OWN decision and therefore belong in the
# grade. `not_desked` is a lane the desk does not control, and
# `chosen_then_refused` is the book refusing an entry the desk wanted —
# neither says anything about the quality of the ranking.
TAKEN_OUTCOMES = ("chosen", "resized")
REFUSED_OUTCOMES = ("displaced", "duplicate")
GRADED_DECISION_OUTCOMES = TAKEN_OUTCOMES + REFUSED_OUTCOMES


def _decision_bars(symbol, start, end):
    """(timeframe, [(ts, high, low, close)]) over the horizon window.

    The finest timeframe that has ANY bar in the window wins. Returns
    (None, []) when the symbol is not in the catalogue or nothing printed —
    which is a reason to wait, not a reason to book a zero.
    """
    from instruments.models import Instrument
    from market_data.models import PriceData

    inst_id = (Instrument.objects
               .filter(symbol=(symbol or "").strip().upper())
               .values_list("id", flat=True).first())
    if inst_id is None:
        return None, []
    for tf in COUNTERFACTUAL_TIMEFRAMES:
        rows = list(PriceData.objects
                    .filter(instrument_id=inst_id, timeframe=tf,
                            timestamp__gte=start, timestamp__lte=end)
                    .order_by("timestamp")
                    .values_list("timestamp", "high", "low", "close"))
        if rows:
            return tf, rows
    return None, []


def walk_bracket(*, direction, price, stop, target, bars):
    """(r, outcome) for one bracket walked over `bars`.

    Stop first is −1.0 by construction — that is what 1R means. Target first
    is the planned reward in units of that same risk. Neither, and the
    position is marked to market at the last bar inside the horizon, which is
    exactly what the time stop would have booked.

    WHEN ONE BAR CONTAINS BOTH, THE STOP WINS. A bar says what was touched,
    never in what order, and assuming the good half printed first is how a
    backtest invents an edge. The bias is against the counterfactual, which
    on a displaced entry is the side that makes the DESK look good — the safe
    direction for a number whose whole job is to justify the desk.
    """
    sign = _sign(direction)
    price, stop = _f(price), _f(stop)
    risk = abs(price - stop)
    if price <= 0 or risk <= 0:
        return None, CF_UNGRADEABLE
    tgt = _f(target) if target is not None else None
    for _ts, high, low, _close in bars:
        hi, lo = _f(high), _f(low)
        if sign > 0:
            if lo <= stop:
                return -1.0, CF_STOP
            if tgt and hi >= tgt:
                return abs(tgt - price) / risk, CF_TARGET
        else:
            if hi >= stop:
                return -1.0, CF_STOP
            if tgt and lo <= tgt:
                return abs(tgt - price) / risk, CF_TARGET
    last_close = _f(bars[-1][3])
    if last_close <= 0:
        return None, CF_UNGRADEABLE
    return ((last_close - price) * sign) / risk, CF_OPEN


def _mark_ungradeable(decision, now) -> None:
    decision.counterfactual_r = None
    decision.counterfactual_outcome = CF_UNGRADEABLE
    decision.resolved_at = now
    decision.save(update_fields=["counterfactual_r", "counterfactual_outcome",
                                 "resolved_at"])


def _resolve_taken(now) -> int:
    """chosen / resized: the decision's R is the TRADE's R, once graded.

    `realized_r` is size-invariant, so the row's own R is the candidate at
    size 1.0 and the multiplier is applied where the two sets are summed, not
    here. A closed trade whose exit could not be priced has realized_r NULL,
    and NULL STAYS NULL: it is counted as ungradeable rather than folded in
    as a break-even that never happened.
    """
    from bot_program.models import DeskDecision

    # THE BATCH MUST HOLD ONLY ROWS THAT CAN RESOLVE. A chosen decision
    # whose trade is still OPEN never resolves, and it stays in this
    # queryset forever: filtered in Python, a few thousand long-held
    # positions would fill the batch, oldest first, and a trade that closed
    # last night would never be reached again. So the closed-and-graded test
    # is an ORM filter, and the batch is spent on work (2026-09-12).
    rows = (DeskDecision.objects
            .filter(outcome__in=TAKEN_OUTCOMES, resolved_at__isnull=True,
                    trade__isnull=False, trade__status="CLOSED")
            .exclude(trade__outcome="")
            .select_related("trade")
            .order_by("created_at")[:DESK_RESOLVE_BATCH])
    n = 0
    for decision in rows:
        trade = decision.trade
        if trade is None or trade.status != "CLOSED" or not trade.outcome:
            continue
        decision.counterfactual_r = trade.realized_r
        decision.counterfactual_outcome = (
            str(trade.outcome)[:16] if trade.realized_r is not None
            else CF_UNGRADEABLE)
        decision.resolved_at = now
        decision.save(update_fields=["counterfactual_r",
                                     "counterfactual_outcome", "resolved_at"])
        n += 1
    return n


def _resolve_refused(now) -> int:
    """displaced / duplicate: walk the bars the entry never got to trade."""
    from bot_program.models import DeskDecision

    rows = (DeskDecision.objects
            .filter(outcome__in=REFUSED_OUTCOMES, resolved_at__isnull=True,
                    created_at__lte=now)
            .order_by("created_at")[:DESK_RESOLVE_BATCH])
    n = 0
    for decision in rows:
        horizon = float(decision.horizon_hours or 168.0)
        end = decision.created_at + timedelta(hours=horizon)
        if end > now:
            continue                      # the horizon has not closed yet
        price = _f(decision.price)
        stop = None if decision.stop is None else _f(decision.stop)
        if stop is None or price <= 0 or abs(price - stop) <= 0:
            # No risk to measure an R against. Waiting cannot fix that, so it
            # is settled now rather than re-walked every night forever.
            _mark_ungradeable(decision, now)
            n += 1
            continue
        _tf, bars = _decision_bars(decision.symbol, decision.created_at, end)
        if not bars:
            if now >= end + timedelta(hours=COUNTERFACTUAL_GRACE_HOURS):
                _mark_ungradeable(decision, now)
                n += 1
            continue                      # still inside the grace — wait
        r, outcome = walk_bracket(direction=decision.direction,
                                  price=decision.price, stop=decision.stop,
                                  target=decision.target, bars=bars)
        decision.counterfactual_r = r
        decision.counterfactual_outcome = outcome
        decision.resolved_at = now
        decision.save(update_fields=["counterfactual_r",
                                     "counterfactual_outcome", "resolved_at"])
        n += 1
    return n


def resolve_counterfactuals(now=None) -> int:
    """Price every decision whose horizon has closed. Returns how many.

    Two populations, two methods: an entry the desk TOOK is priced by its own
    trade, and an entry the desk REFUSED is priced by walking the bars over
    the horizon it was given. Both write `counterfactual_r`, so the edge
    arithmetic below reads exactly one column.
    """
    now = now or timezone.now()
    return _resolve_taken(now) + _resolve_refused(now)


def _edge_of(decisions) -> dict:
    """{"edge_r", "detail"} over one plan's decisions.

    desk_r     Σ over chosen/resized of r × size_mult — what the desk did.
    default_r  Σ over every desked candidate at size 1.0 — what the fleet
               would have booked with no desk at all.
    """
    desk_r = default_r = 0.0
    n_graded = n_ungradeable = 0
    by_rule, by_class = {}, {}

    for decision in decisions:
        if decision.outcome not in GRADED_DECISION_OUTCOMES:
            continue
        r = decision.counterfactual_r
        if r is None:
            n_ungradeable += 1
            continue
        r = float(r)
        n_graded += 1
        mine = (r * float(decision.size_mult or 1.0)
                if decision.outcome in TAKEN_OUTCOMES else 0.0)
        desk_r += mine
        default_r += r
        rule = decision.rule_name or "(unnamed)"
        cls = getattr(decision.config, "asset_class", "") or "(unknown)"
        for bucket, key in ((by_rule, rule), (by_class, cls)):
            row = bucket.setdefault(key, {"desk_r": 0.0, "default_r": 0.0,
                                          "edge_r": 0.0, "n": 0})
            row["desk_r"] = round(row["desk_r"] + mine, 6)
            row["default_r"] = round(row["default_r"] + r, 6)
            row["edge_r"] = round(row["desk_r"] - row["default_r"], 6)
            row["n"] += 1

    detail = {
        "n_graded": n_graded, "n_ungradeable": n_ungradeable,
        "desk_r": round(desk_r, 6), "default_r": round(default_r, 6),
        "by_rule": by_rule, "by_class": by_class,
    }
    edge = None if n_graded == 0 else round(desk_r - default_r, 6)
    return {"edge_r": edge, "detail": detail}


def grade_plans(now=None) -> int:
    """Score every plan whose decisions are settled. Returns how many.

    A plan is ready when every decision the desk made on it is resolved, or
    when PLAN_GRADE_GRACE_HOURS have passed since it was written — one symbol
    that never prints a bar must not hold the desk's whole score hostage.

    `edge_r` is None when nothing on the plan could be graded, and that is
    NOT zero: zero would say the ranking made no difference, when what
    actually happened is that nothing was measured.
    """
    from bot_program.models import DeskPlan

    now = now or timezone.now()
    graded = 0
    plans = (DeskPlan.objects.filter(graded_at__isnull=True)
             .prefetch_related("decisions__config"))
    for plan in plans:
        decisions = [d for d in plan.decisions.all()
                     if d.outcome in GRADED_DECISION_OUTCOMES]
        pending = [d for d in decisions if d.resolved_at is None]
        if pending and now < plan.created_at + timedelta(
                hours=PLAN_GRADE_GRACE_HOURS):
            continue
        result = _edge_of(decisions)
        detail = dict(result["detail"])
        # How many rows were still open when the grace ran out. A plan graded
        # with three of its five decisions pending is a weaker reading than
        # one graded complete, and the page must be able to say so.
        detail["n_pending_at_grade"] = len(pending)
        plan.edge_r = result["edge_r"]
        plan.edge_detail = detail
        plan.graded_at = now
        plan.save(update_fields=["edge_r", "edge_detail", "graded_at"])
        graded += 1
    return graded
