"""Unified pre-trade risk gate — Phase 2, plus the book-level limits.

TWO things live here, and they have very different reach.

`evaluate_proposed_trade()` is the Phase-2 sizing advisor. Its only caller is
`bot_program/engine/runner.py`, the legacy crypto runner, which has no beat
entry and therefore never runs. It is kept because it is the AI-sanity and
decay plumbing, but nothing it decides reaches a live order today.

The second half of this module — `preflight()` and the four `*_state()`
readers below it — is the part that binds. It is the enforcement side of the
/setup/ "Risk Limits" card, which for its whole life wrote four numbers onto
the shared Main portfolio that nothing on the execution path ever read:
`max_total_exposure_pct` had zero readers repo-wide, `max_daily_loss_pct`
reached a context processor and an LLM prompt but no entry gate, and the
other two reached trading only through the dead runner above. An operator
could set MAX DAILY LOSS 3%, arm a bot, and lose whatever the market cared
to take. The most reassuring screen in the platform enforced the least.

`preflight()` is now called by `AssetBot.can_open_new()` and by both manual
take-trade paths, which between them are every way this platform opens a
position.

`evaluate_proposed_trade()` combines every Phase-1 + Phase-2 check a proposed
trade should pass:

  - position-size cap vs. portfolio max_single_position_pct
  - correlation to the existing open book (PositionSizer.correlation_aware_scale)
  - signal-rule decay (signals.performance.decay_flag), if a rule_name is given
  - portfolio risk metrics snapshot (RiskEngine.calculate_var)
  - a unified scale factor (product of correlation + future per-check scales)

Returns a dict the caller can act on:

    {
      "ok": bool,                  # True iff no hard block
      "scale": 0..1,               # multiplicative size scale to apply
      "intended_size_usd": float,
      "approved_size_usd": float,  # intended * scale, capped to position limit
      "reasons": [str, ...],       # human-readable explanations (always non-empty)
      "checks": {
          "position_cap":       {...},
          "correlation":        {...},
          "decay":              {...},   # only present if rule_name supplied
          "var_snapshot":       {...},
      },
    }
"""
from __future__ import annotations

import logging
from datetime import timedelta

logger = logging.getLogger(__name__)


def evaluate_proposed_trade(
    portfolio,
    instrument,
    intended_size_usd: float,
    *,
    rule_name: str | None = None,
    side: str = "long",
    use_ai_check: bool = False,
    ai_context: dict | None = None,
) -> dict:
    """Run every gate check and return a single decision dict.

    `use_ai_check=True` adds a Phase-3 PreTradeSanityAgent call (slow, costs
    Claude tokens). Off by default — the bot's hot path should not block on
    a network round-trip without explicit opt-in.
    """
    from portfolio.position_sizing import PositionSizer
    from portfolio.risk_engine import RiskEngine

    reasons: list[str] = []
    checks: dict = {}
    scale = 1.0

    intended_size_usd = float(intended_size_usd)
    portfolio_value = float(portfolio.current_value or 0)
    sizer = PositionSizer(portfolio)

    # ── 1. position-size cap ────────────────────────────────────────────────
    max_pct = float(portfolio.max_single_position_pct or 100) / 100.0
    cap_usd = portfolio_value * max_pct
    capped = intended_size_usd
    over_cap = False
    if portfolio_value > 0 and intended_size_usd > cap_usd:
        capped = cap_usd
        over_cap = True
        reasons.append(
            f"intended ${intended_size_usd:,.0f} exceeds position cap "
            f"${cap_usd:,.0f} ({max_pct:.0%} of book) — capping"
        )
    checks["position_cap"] = {
        "intended_usd": intended_size_usd,
        "cap_usd": round(cap_usd, 2),
        "max_pct": max_pct,
        "over_cap": over_cap,
    }

    # ── 2. correlation to open book ────────────────────────────────────────
    corr_result = sizer.correlation_aware_scale(instrument)
    checks["correlation"] = corr_result
    scale *= float(corr_result["scale"])
    if corr_result["scale"] < 1.0:
        reasons.append(corr_result["reason"])

    # ── 3. signal-rule decay (Phase 1 → Phase 2 link) ──────────────────────
    if rule_name:
        from signals.performance import decay_flag
        decay = decay_flag(rule_name)
        checks["decay"] = decay
        if decay["is_decaying"]:
            scale *= 0.5
            reasons.append(
                f"rule '{rule_name}' is decaying "
                f"(recent {decay['recent_expectancy']:+.2f}R vs baseline "
                f"{decay['baseline_expectancy']:+.2f}R) — halving size"
            )

    # ── 4. portfolio-level risk snapshot ───────────────────────────────────
    try:
        engine = RiskEngine(portfolio)
        var = engine.calculate_var()
    except Exception as e:
        var = {"error": str(e)}
    checks["var_snapshot"] = var

    # ── 5. (optional) Phase-3 AI sanity check ──────────────────────────────
    if use_ai_check:
        try:
            from ai_agents.agents.pretrade_sanity import check_proposed_trade
            from ai_agents.calibration import trust_adjustment_for
            ai_kwargs = ai_context or {}
            verdict = check_proposed_trade(
                symbol=instrument.symbol,
                direction=side,
                entry=ai_kwargs.get("entry"),
                stop=ai_kwargs.get("stop"),
                target=ai_kwargs.get("target"),
                rule_name=rule_name,
                regime_summary=ai_kwargs.get("regime_summary", ""),
                news_summary=ai_kwargs.get("news_summary", ""),
                rule_perf_summary=ai_kwargs.get("rule_perf_summary", ""),
            )

            # Phase-6 calibration: dampen the AI scale by the agent's
            # historical reliability. Untrusted agents have less influence.
            raw_scale = float(verdict.get("scale", 1.0))
            trust = trust_adjustment_for("pretrade_sanity")
            # Scale toward 1.0 when trust is low (agent has less ability
            # to push the gate away from "go").
            adjusted_scale = 1.0 - (1.0 - raw_scale) * trust

            verdict["raw_scale"] = raw_scale
            verdict["trust_adjustment"] = trust
            verdict["adjusted_scale"] = round(adjusted_scale, 4)
            checks["ai_sanity"] = verdict
            scale *= adjusted_scale

            if verdict.get("verdict") == "abort" and trust >= 1.0:
                reasons.append(f"AI sanity check ABORT: {verdict.get('rationale', '')}")
            elif adjusted_scale < 1.0:
                trust_note = f" (trust ×{trust:.2f})" if abs(trust - 1.0) > 0.01 else ""
                reasons.append(
                    f"AI sanity scale {adjusted_scale:.2f}{trust_note}: "
                    f"{verdict.get('rationale', '')}"
                )

            # Phase-6: log the prediction itself for calibration. We tie it
            # to the linked Signal if the caller passed one in ai_context.
            linked_signal = (ai_context or {}).get("linked_signal")
            if linked_signal is not None:
                try:
                    from ai_agents.calibration import log_trade_prediction
                    # Confidence: scale of 1.0 = strong "go" (high prob hit_target);
                    # scale of 0.0 = strong "abort". Map linearly.
                    log_trade_prediction(
                        agent="pretrade_sanity",
                        signal=linked_signal,
                        predicted_outcome="hit_target" if raw_scale >= 0.5 else "stopped_out",
                        confidence=raw_scale if raw_scale >= 0.5 else 1.0 - raw_scale,
                    )
                except Exception as e:
                    import logging
                    logging.getLogger(__name__).warning(
                        "[risk_gate] log_trade_prediction failed: %s", e
                    )
        except Exception as e:
            checks["ai_sanity"] = {"error": str(e), "verdict": "go", "scale": 1.0}
            # Best-effort: AI failure must not block trading.

    # ── final composite ────────────────────────────────────────────────────
    approved = round(capped * scale, 2)
    ok = approved > 0  # the gate itself does not hard-block; it sizes down.

    if not reasons:
        reasons.append("no risk constraints triggered")

    return {
        "ok": ok,
        "scale": round(scale, 4),
        "intended_size_usd": round(intended_size_usd, 2),
        "approved_size_usd": approved,
        "reasons": reasons,
        "checks": checks,
    }


# ═══════════════════════════════════════════════════════════════════════════
# The /setup/ Risk Limits card, made real
# ═══════════════════════════════════════════════════════════════════════════

# The window "today's loss" means on this platform.
#
# NOT a calendar day, and the choice is not free: `AssetBot.can_open_new` has
# always measured a trailing 24 hours against `AssetBotConfig.max_daily_loss_pct`,
# and two definitions of "today" on one platform is a defect of its own — an
# operator reading "3% daily loss" on the setup card and "2% daily loss" on a
# bot config has to be able to reason about one clock. A trailing window also
# survives the thing a calendar day does not: a book that trades Sydney through
# New York has no midnight that everyone agrees on, and a calendar reset hands
# a bot that just lost its limit a fresh budget at whichever hour the server
# happens to call midnight.
DAILY_LOSS_WINDOW_HOURS = 24

# Correlation lookback and taper floor.
#
# Both mirror `PositionSizer.correlation_aware_scale`, deliberately: the taper
# it implements (full size at the threshold, falling linearly to a floor at
# perfect correlation) is the platform's shipped answer for "you already own
# this bet", and a second answer would mean two screens disagreeing about what
# the same number does. It is re-implemented here rather than called because
# `correlation_aware_scale` reads `portfolio.Position` ONLY — on a book whose
# exposure lives mostly in AssetBotTrade it reports "no open positions" and
# tapers nothing, which is the same protects-nothing failure this module is
# closing. The version below unions both books.
CORRELATION_LOOKBACK_DAYS = 90
CORRELATION_MIN_SCALE = 0.25


def limits_book():
    """The Portfolio row the /setup/ Risk Limits card actually writes to.

    `get_or_create_default_portfolio()` with NO user — the shared "Main" book.
    That is deliberate and it is the only choice that makes this module true:
    the setup view saves the four limits onto exactly that row, so a gate
    reading the per-user `<username>_main` row would read factory defaults
    nobody set and go on protecting nothing. `unified_open_positions` defaults
    to the same book, for the same reason.

    The consequence is worth stating out loud rather than discovering: these
    four limits are SHARED. Anyone who can reach /setup/ moves them for
    everyone. The setup view therefore clamps what may be written — see
    `RISK_LIMIT_BOUNDS` there — so neither a fat finger nor a hostile POST can
    halt the whole fleet with a 0, and the card names whose limits these are.
    """
    from portfolio.services import get_or_create_default_portfolio
    return get_or_create_default_portfolio()


def gate_book_value(user, portfolio) -> float | None:
    """The size the limits are percentages OF, for THIS operator.

    The four percentages live on the shared limits book, deliberately —
    see `limits_book`. The book VALUE does not, and that split is what
    made every gate on this platform scale against the wrong number.

    `/setup/`'s capital form writes `current_value` onto the OPERATOR's
    own row (`dashboard.views.setup_view` resolves
    `get_or_create_default_portfolio(user=request.user)` and saves the
    three capital fields there), while every gate below read the size
    from the shared row. Nothing puts the operator's money on that row:
    `recalculate_exposure` re-values EVERY book from its own positions,
    and the shared book's bot half is empty by construction, so on any
    deploy without the global eToro sync it settles back to the seeded
    `PORTFOLIO_INITIAL_CAPITAL` — 10,000 by default — and stays there.

    Meanwhile the numerator is already per-operator: `realized_since`
    and `open_capital_at_work` both filter `config__user=user`. So a
    real 50,000 book was measured against a 10,000 denominator, and a
    3% daily-loss floor stopped the fleet at -300 instead of -1,500 with
    a reason that never mentioned the book it used. The error runs the
    other way for a book under the seed, which is the dangerous
    direction.

    The operator's own row is the right answer AND the self-maintaining
    one: the hourly re-valuation already keeps it true from that book's
    own positions. Falls back to the passed book when there is no user
    or no per-user row, so a shared-book caller keeps its old meaning.
    """
    from portfolio.models import Portfolio
    from portfolio.services import PER_USER_SUFFIX

    # LOOKED UP, never created. `get_or_create_default_portfolio` seeds a
    # new row at PORTFOLIO_INITIAL_CAPITAL, so calling it here would turn
    # "this book's size was never set" — which `book_value` deliberately
    # answers None to, so a gate abstains instead of enforcing a number
    # nobody entered — into a confident 10,000. That is the same
    # fabrication this function exists to remove, one level up.
    username = getattr(user, "username", "") if user is not None else ""
    if username and getattr(user, "is_authenticated", True):
        try:
            own = Portfolio.objects.filter(
                name=f"{username}{PER_USER_SUFFIX}").first()
        except Exception:  # pragma: no cover - never break a gate on lookup
            own = None
        if own is not None:
            value = book_value(own)
            if value is not None:
                return value
    return book_value(portfolio)


def book_value(portfolio) -> float | None:
    """The book value the limits are percentages OF, or None if unusable.

    None, not 0.0: a portfolio whose `current_value` has never been set is a
    book of unknown size, and every one of these limits is a percentage of it.
    A 3% limit on an unknown book is not "stop at zero" — it is not a limit at
    all, and the gates below say so instead of halting the fleet on a number
    nobody entered.
    """
    try:
        value = float(portfolio.current_value)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _limit_pct(portfolio, field: str) -> float | None:
    """One limit off the card, or None when it is not set to a usable number."""
    raw = getattr(portfolio, field, None)
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def capital_at_work(asset_class: str, notional: float) -> float:
    """Account-currency cash a position of this notional actually ties up.

    Margin-aware, through `bot_program.manual_trade.CAPITAL_USE_FRACTION` —
    the one place this platform records that an FX position ties up broker
    margin rather than its levered notional. Imported rather than copied,
    because two tables would drift and this one is now load-bearing on both
    the pool-accounting side and the limits side.

    Notional is the wrong basis without it, and unusably so: `sizing`'s forex
    notional cap is 4.0x the pool BECAUSE the leverage lives at the broker, so
    one legitimate FX trade is 400% of a book the same size as that pool. A
    "max total exposure 100%" card read against raw notional would refuse every
    forex entry the platform is built to take, which is a halt dressed as a
    limit.
    """
    from bot_program.manual_trade import CAPITAL_USE_FRACTION
    return abs(float(notional)) * CAPITAL_USE_FRACTION.get(asset_class or "", 1.0)


def open_capital_at_work(user, portfolio) -> dict:
    """Capital tied up by the open book — BOTH books — at entry prices.

    Returns {"total": float, "n": int} plus the venue split described below.
    Both halves, because exposure genuinely lives in two places here:
    `portfolio.Position` and `bot_program.AssetBotTrade` (the bots, TAKE
    TRADE, the LONG/SHORT buttons). CLOSE_PENDING is counted — the broker
    position is still on.

    LIVE and PAPER capital are counted apart and NEVER added. `paper` is not a
    property of a config an operator can reason about from the outside: a LIVE
    config runs its paper-stage rules on the paper venue at full nominal size
    (`paper = mode == "paper" or stage["force_paper"]`), and every hand-taken
    TAKE TRADE writes `paper=True` today, so one user's book routinely carries
    both at once. Adding them let five simulated positions eat a ceiling that
    exists to bound real money and refuse the live entry behind them. The
    ceiling is applied to each venue on its own instead — `total` is whichever
    binds — so neither venue can spend the other's room.

    Position rows carry no venue flag of their own and are counted as live:
    they describe holdings at a real broker, which is what the operator
    entered them for.

    The Position rows reaching this are the setup form's and the eToro sync's,
    and only those: both write to the shared no-user "Main" row `limits_book`
    returns. The NL trader writes to `<username>_main`, a book nothing in this
    module reads, so nothing it opens is ever charged against this ceiling.

    Measured at ENTRY, not at the mark, and that is not a shortcut. Committed
    capital is what was committed, it is how the manual path's own pool
    accounting measures it (`manual_trade._trade_notional_usd`), so the
    exposure limit and the "insufficient capital in the pool" refusal agree
    about what a position costs. Marking to live quotes would additionally
    make exposure UNMEASURABLE whenever the quote feed is behind — and a gate
    that goes blind exactly when the market is moving is not a gate.

    Legacy Position rows are charged at `entry_price x quantity` with no
    value_per_unit: that column was never recorded on this book, and the rows
    that reach it are the stock/ETF ones the setup form and the eToro sync
    create, where the multiplier is 1 anyway.
    """
    from bot_program.models import AssetBotTrade
    from portfolio.models import Position
    from portfolio.services import value_per_unit

    live_total = 0.0
    live_n = 0
    paper_total = 0.0
    paper_n = 0
    for trade in AssetBotTrade.objects.filter(
            config__user=user,
            status__in=("OPEN", "CLOSE_PENDING")).only(
                "asset_class", "entry_price", "qty", "metadata", "paper"):
        notional = (float(trade.entry_price or 0) * float(trade.qty or 0)
                    * value_per_unit(trade))
        at_work = capital_at_work(trade.asset_class, notional)
        if trade.paper:
            paper_total += at_work
            paper_n += 1
            continue
        live_total += at_work
        live_n += 1

    # The legacy half is counted, AND its age is carried out with it.
    #
    # Nothing on this platform routinely closes a portfolio.Position: the
    # only writers of `closed_at` are the NL trader and the kill switch, and
    # on this book only the second one — called with no user, so that it
    # sweeps every portfolio — reaches these rows at all. A row the setup
    # form or the eToro sync created therefore stays open until a human
    # intervenes. That is fine for a display, and dangerous for a gate
    # that can halt trading — stale bookkeeping would eat the exposure
    # ceiling permanently and every entry would be refused by rows nobody
    # can see and nothing can close.
    #
    # The answer is not to stop counting it. Exposure the platform cannot
    # close is still exposure, and silently discounting it would be the gate
    # lying in the one direction that costs money. The answer is to say so:
    # the refusal names this book's share and the age of its oldest row, so
    # "you are at your ceiling" and "stale rows are holding your ceiling"
    # are different sentences instead of the same silence.
    legacy_total = 0.0
    legacy_n = 0
    oldest = None
    for pos in Position.objects.filter(
            portfolio=portfolio,
            closed_at__isnull=True).select_related("instrument"):
        notional = float(pos.entry_price or 0) * float(pos.quantity or 0)
        legacy_total += capital_at_work(
            getattr(pos.instrument, "asset_class", ""), notional)
        legacy_n += 1
        if pos.opened_at and (oldest is None or pos.opened_at < oldest):
            oldest = pos.opened_at
    live_total += legacy_total
    live_n += legacy_n

    # `total` is what the ceiling is judged against: the LARGER venue, not the
    # sum. Both figures travel out so a refusal can name which book filled the
    # ceiling — "you are fully invested" and "your paper experiment is holding
    # your live ceiling" are different sentences and the operator acts on them
    # differently.
    paper_binds = paper_total > live_total
    return {"total": round(paper_total if paper_binds else live_total, 2),
            "n": paper_n if paper_binds else live_n,
            "live_total": round(live_total, 2), "live_n": live_n,
            "paper_total": round(paper_total, 2), "paper_n": paper_n,
            "legacy_total": round(legacy_total, 2), "legacy_n": legacy_n,
            "legacy_oldest": oldest}


def realized_since(user, portfolio, *, hours: int = DAILY_LOSS_WINDOW_HOURS,
                   now=None) -> dict:
    """Realized P&L over the trailing window, across BOTH position books.

    Returns {"realized": float | None, "live_realized", "paper_realized",
    "n": int, "unmeasured": int, "since": datetime}. `realized` is None when
    nothing in the window could be measured and something was there to measure
    — an unmeasurable book is unknown, not flat, and a confident 0.00 is how a
    losing day gets waved through.

    LIVE and PAPER closes are measured apart and NEVER netted, and `realized`
    is the WORSE of the two venues rather than their sum. Netting them was a
    hole big enough to drive the whole card through: a live config runs its
    paper-stage rules at full nominal size and every hand-taken TAKE TRADE is
    paper today, so a book that lost 2,400 of real money while simulated rules
    booked +2,600 reported +200 realized, the card read green, and every bot
    kept opening while the real account fell. Simulated profit cannot pay for a
    real loss, so it is not allowed to. Nor is the reverse arithmetic — two
    venues each 200 down are not a 400-down day on a book that only lost the
    live 200.

    The bot half is `AssetBotTrade.pnl` over `status="CLOSED"` inside the
    window, which on the live clock is the query `AssetBot.can_open_new` runs
    for the per-config limit. Matching it is the point: the fleet limit and the
    book limit must not disagree about which closes happened today.

    The window is closed at BOTH ends — [now - hours, now]. `now` is an as-of
    instant, and an answer that included closes booked after it would not be a
    reading of that instant. That bound is what lets the manual take-trade
    path ask where the day stood BEFORE its own funding closes, which is the
    difference between a close that pays for a trade and a close that trips
    the gate which then refuses it.

    The legacy half is derived, because `portfolio.Position` has no realized
    P&L column at all — `unrealized_pnl` defaults to 0 and its only writer is
    an hourly mark task, so reading it would book every unmarked close as a
    scratch. `current_price` is the only exit figure a closed Position row
    carries, so the derivation uses that and counts a row without one as
    unmeasured rather than as zero.

    On the book this reads, that lane is dormant, and saying so beats implying
    a coverage it does not have. Both paths that close a Position — the NL
    trader and a kill switch called with a user — work on `<username>_main`,
    while `limits_book` is the shared "Main" row; only a kill switch run with
    no user reaches these rows, and it writes no exit price, so what the
    derivation would find there is the last hourly mark. The query stays
    because a book that does start closing rows has to be measured rather than
    assumed flat, which is the posture of this whole module.

    Currencies are added as they are. `AssetBotTrade.pnl` is in the config's
    base currency and the portfolio carries its own, and this platform has no
    FX conversion anywhere — every existing cross-book total adds these same
    numbers. A gate that refused to measure until one existed would be the
    same protects-nothing this module is here to end.
    """
    from django.utils import timezone
    from bot_program.models import AssetBotTrade
    from portfolio.models import Position

    now = now or timezone.now()
    since = now - timedelta(hours=hours)

    live = 0.0
    live_n = 0
    paper = 0.0
    paper_n = 0
    unmeasured = 0

    for trade in AssetBotTrade.objects.filter(
            config__user=user, status="CLOSED",
            closed_at__gte=since,
            closed_at__lte=now).only("pnl", "paper", "metadata"):
        # A row reconciliation had to close with no price available carries a
        # fabricated 0.00 in a column that cannot hold NULL. Summing it would
        # book a real stop-out as a scratch — invisible to this floor, which
        # is the one number an operator trusts to stop the day.
        if (trade.metadata or {}).get("exit_price_unavailable"):
            unmeasured += 1
            continue
        if trade.paper:
            paper += float(trade.pnl or 0)
            paper_n += 1
            continue
        live += float(trade.pnl or 0)
        live_n += 1

    for pos in Position.objects.filter(portfolio=portfolio,
                                       closed_at__gte=since,
                                       closed_at__lte=now):
        entry = float(pos.entry_price or 0)
        exit_mark = float(pos.current_price or 0)
        qty = float(pos.quantity or 0)
        if entry <= 0 or exit_mark <= 0 or qty == 0:
            unmeasured += 1
            continue
        sign = -1 if (pos.direction or "").lower() in ("short", "sell") else 1
        live += (exit_mark - entry) * qty * sign
        live_n += 1

    n = live_n + paper_n
    # A venue with nothing closed in it is not a 0.00 to be compared against
    # the other: on a book that only trades live, "min(live, paper)" with an
    # empty paper side would report a +500 day as a flat one. Only venues that
    # actually closed something are candidates.
    venues = [v for v, count in ((live, live_n), (paper, paper_n)) if count]
    return {
        # Nothing closed at all IS a measurement (no loss). Rows that closed
        # and none of them measurable is not.
        "realized": (round(min(venues), 2) if venues else 0.0)
                    if (n or not unmeasured) else None,
        "live_realized": round(live, 2) if (n or not unmeasured) else None,
        "paper_realized": round(paper, 2) if (n or not unmeasured) else None,
        "live_n": live_n, "paper_n": paper_n,
        "n": n, "unmeasured": unmeasured, "since": since,
    }


def daily_loss_state(user, *, portfolio=None, now=None) -> dict:
    """Where the book stands against MAX DAILY LOSS. Never raises on data.

    {"ok", "reason", "limit_pct", "limit_money", "realized", "book_value",
     "unmeasured", "measured", "live_realized", "paper_realized"}

    `ok` False is a hard refusal: this is the one number on the card an
    operator reads as "the platform stops here".

    `realized` is the worse of the live and paper venues, never their sum —
    see `realized_since`. The floor therefore binds each venue on its own, and
    the reason names both whenever both closed something, because "you are
    down 2,400 of real money" and "your paper experiment is down 2,400" are
    the same refusal wearing very different consequences.
    """
    portfolio = portfolio if portfolio is not None else limits_book()
    limit_pct = _limit_pct(portfolio, "max_daily_loss_pct")
    book = gate_book_value(user, portfolio)
    state = {"ok": True, "limit_pct": limit_pct, "book_value": book,
             "limit_money": None, "realized": None, "unmeasured": 0,
             "measured": False, "reason": ""}

    if limit_pct is None:
        state["reason"] = "no daily-loss limit set on the book"
        return state
    if book is None:
        state["reason"] = (f"daily-loss limit {limit_pct:g}% is a percentage "
                           f"of a book value that has never been set — "
                           f"nothing to measure it against")
        return state

    window = realized_since(user, portfolio, now=now)
    limit_money = -book * limit_pct / 100.0
    state["limit_money"] = round(limit_money, 2)
    state["realized"] = window["realized"]
    state["live_realized"] = window["live_realized"]
    state["paper_realized"] = window["paper_realized"]
    state["unmeasured"] = window["unmeasured"]
    state["measured"] = window["realized"] is not None

    if window["realized"] is None:
        state["reason"] = (
            f"{window['unmeasured']} position(s) closed in the last "
            f"{DAILY_LOSS_WINDOW_HOURS}h and none of them carries a price to "
            f"measure — the day's P&L is unknown, so the "
            f"{limit_pct:g}% limit cannot be applied")
        return state

    blind = (f" ({window['unmeasured']} further close(s) had no price and are "
             f"not in this figure)") if window["unmeasured"] else ""
    # Both venues named the moment any simulated close is in the window.
    # Without it the operator reads one number and cannot tell whether the
    # platform stopped because their money is gone or because a simulation is.
    split = ""
    if window["paper_n"]:
        split = (f" (live {window['live_realized']:,.2f}, paper "
                 f"{window['paper_realized']:,.2f} — measured apart, never "
                 f"netted)")
    if window["realized"] <= limit_money:
        state["ok"] = False
        state["reason"] = (
            f"daily loss limit hit: {window['realized']:,.2f} realized in the "
            f"last {DAILY_LOSS_WINDOW_HOURS}h against a "
            f"{limit_money:,.2f} floor ({limit_pct:g}% of the "
            f"{book:,.2f} book){split}{blind}")
        return state

    state["reason"] = (
        f"{window['realized']:,.2f} realized in the last "
        f"{DAILY_LOSS_WINDOW_HOURS}h, floor {limit_money:,.2f}{split}{blind}")
    return state


def exposure_state(user, *, portfolio=None, adding: float = 0.0,
                   venue: str = "") -> dict:
    """Where the book stands against MAX TOTAL EXPOSURE. Never raises on data.

    {"ok", "reason", "limit_pct", "cap_money", "committed", "n_open",
     "headroom", "book_value"}

    Live and paper capital are judged separately (see `open_capital_at_work`);
    `committed` is whichever venue binds, and the reason names the other.

    `venue` is "live" or "paper" when a SPECIFIC entry is being judged, and
    empty for the display call that describes the book as a whole. It is
    what stops a simulation spending real money's room: `open_capital_at_work`
    reports the two venues apart and `committed` defaults to whichever is
    larger, which is the right summary for a card — but judging a LIVE entry
    against it means five paper positions can refuse a real one, which is the
    same defect as the netting this split was written to remove, pointed the
    other way. With a venue named, the ceiling binds that venue's own capital
    and the reason still names the other.

    `adding` is the CAPITAL AT WORK of the position about to be opened, and
    passing it turns this from "am I already over?" into "would this put me
    over?". Without it the ceiling can only ever refuse the entry AFTER the
    one that breached it: committed at 99,500 of a 100,000 ceiling reads as
    headroom, `scan_symbol` opens a position at the 20% single-position cap,
    and the book sits at 119.5% of a limit the operator set to 100% with
    nothing having refused anything.

    Pass `capital_at_work(asset_class, notional)`, not the raw notional —
    the ceiling is margin-aware and a forex ticket would otherwise be
    charged its levered size and refused for nothing.
    """
    portfolio = portfolio if portfolio is not None else limits_book()
    limit_pct = _limit_pct(portfolio, "max_total_exposure_pct")
    book = gate_book_value(user, portfolio)
    adding = abs(float(adding or 0.0))
    state = {"ok": True, "limit_pct": limit_pct, "book_value": book,
             "cap_money": None, "committed": None, "headroom": None,
             "n_open": 0, "adding": round(adding, 2), "reason": ""}

    if limit_pct is None:
        state["reason"] = "no total-exposure limit set on the book"
        return state
    if book is None:
        state["reason"] = (f"exposure limit {limit_pct:g}% is a percentage of "
                           f"a book value that has never been set")
        return state

    open_book = open_capital_at_work(user, portfolio)
    cap = book * limit_pct / 100.0
    state["cap_money"] = round(cap, 2)
    # The venue's own committed capital when one is named; the binding
    # venue otherwise.
    if venue == "live":
        committed = open_book.get("live_total", open_book["total"])
        n_open = open_book.get("live_n", open_book["n"])
    elif venue == "paper":
        committed = open_book.get("paper_total", open_book["total"])
        n_open = open_book.get("paper_n", open_book["n"])
    else:
        committed, n_open = open_book["total"], open_book["n"]
    open_book = {**open_book, "total": committed, "n": n_open}

    state["venue"] = venue or "both"
    state["committed"] = open_book["total"]
    state["n_open"] = open_book["n"]
    state["headroom"] = round(cap - open_book["total"], 2)

    state["legacy_committed"] = open_book.get("legacy_total")
    state["legacy_n"] = open_book.get("legacy_n", 0)
    state["live_committed"] = open_book.get("live_total")
    state["paper_committed"] = open_book.get("paper_total")

    # Both venues named whenever any simulated capital is open, for the same
    # reason the daily-loss refusal names them: an operator whose entries are
    # being refused needs to know whether it is their money holding the
    # ceiling or a simulation, and that is the one sentence that tells them.
    split = ""
    if open_book.get("paper_n"):
        split = (f" (live {open_book['live_total']:,.2f} across "
                 f"{open_book['live_n']}, paper "
                 f"{open_book['paper_total']:,.2f} across "
                 f"{open_book['paper_n']} — each judged on its own, never "
                 f"added)")

    # `>= cap` with nothing proposed, `> cap` once something is: the first
    # is "the book is full", the second is "this ticket is the one that would
    # overflow it". The 1e-9 is float noise on an exactly-fitting size, the
    # same slack the sibling gates allow.
    breached = ((open_book["total"] + adding > cap + 1e-9) if adding
                else (open_book["total"] >= cap))
    if breached:
        state["ok"] = False
        if adding and open_book["total"] < cap:
            # The book is not full; THIS ticket is the one that would
            # overflow it. Naming which of the two it is decides what the
            # operator does next — size this entry down, or close something.
            state["reason"] = (
                f"this position would take total exposure past its ceiling: "
                f"{open_book['n']} open position(s) tie up "
                f"{open_book['total']:,.2f} of a {cap:,.2f} ceiling "
                f"({limit_pct:g}% of the {book:,.2f} book) and this one adds "
                f"{adding:,.2f}{split}")
        else:
            state["reason"] = (
                f"total exposure limit reached: {open_book['n']} open position(s) "
                f"tie up {open_book['total']:,.2f} against a {cap:,.2f} ceiling "
                f"({limit_pct:g}% of the {book:,.2f} book){split}")
        # A halt whose cause the operator cannot see is a halt they cannot
        # clear. Nothing on this platform routinely closes the legacy book,
        # so if its rows are what filled the ceiling, that is the single
        # most useful sentence this refusal can carry — and the difference
        # between "you are fully invested" and "a year-old bookkeeping row
        # is holding your ceiling".
        oldest = open_book.get("legacy_oldest")
        if open_book.get("legacy_n") and open_book.get("legacy_total"):
            share = open_book["legacy_total"]
            from django.utils import timezone as _tz
            age = ""
            if oldest is not None:
                days = max(0, (_tz.now() - oldest).days)
                age = f", oldest opened {days} day(s) ago"
            state["reason"] += (
                f" — {open_book['legacy_n']} of those are portfolio-book rows "
                f"holding {share:,.2f}{age}. Nothing closes that book "
                f"automatically, so check they are still real positions")
        return state

    state["reason"] = (f"{open_book['total']:,.2f} of {cap:,.2f} committed "
                       f"across {open_book['n']} position(s){split}")
    return state


def single_position_state(portfolio, *, asset_class: str, user=None,
                          notional: float, capital_base: float = None,
                          base_label: str = "book") -> dict:
    """Whether one proposed position clears MAX SINGLE POSITION.

    Judged on capital AT WORK, the same margin-aware basis `exposure_state`
    uses, so a 20% cap means the same 20% whether the position is a share
    that settles in full or an FX ticket the broker margins at 30:1.

    `capital_base` is THE CAPITAL BACKING THIS POSITION, and passing the
    right one is the whole correctness of this gate.

    The limit reads "no single position may tie up more than X% of my
    capital". A bot sizes from `AssetBotConfig.capital` — a pool the
    operator arms separately — while `Portfolio.current_value` is a
    different number that no bot consults. Measuring a bot's position
    against the portfolio book therefore compares a size to a denominator
    it was never derived from: a bot armed with 100,000 on a book recorded
    as 10,000 had every entry refused for "exceeding 20% of the book",
    which was true and meaningless. The pool was not a violation of the
    book; it was simply a different number.

    So the caller names the base: the bot path passes its config's capital,
    the manual path its manual config's, and a portfolio-book caller passes
    nothing and keeps the book. `base_label` is what the refusal calls it,
    so the operator reads a sentence about the pool that actually refused.
    """
    limit_pct = _limit_pct(portfolio, "max_single_position_pct")
    base = (capital_base if capital_base is not None
            else gate_book_value(user, portfolio))
    at_work = capital_at_work(asset_class, notional)
    state = {"ok": True, "limit_pct": limit_pct, "book_value": base,
             "capital_base": base, "base_label": base_label,
             "cap_money": None, "capital_at_work": round(at_work, 2),
             "reason": ""}

    if limit_pct is None:
        state["reason"] = "no single-position limit set on the book"
        return state
    if base is None or base <= 0:
        state["reason"] = (f"single-position limit {limit_pct:g}% is a "
                           f"percentage of a {base_label} that has never "
                           f"been set")
        return state

    cap = base * limit_pct / 100.0
    state["cap_money"] = round(cap, 2)
    # The 1e-9 is float noise on an exactly-at-the-cap size, not tolerance —
    # the same slack manual_trade.judge_qty allows, for the same reason.
    if at_work > cap + 1e-9:
        state["ok"] = False
        state["reason"] = (
            f"this position ties up {at_work:,.2f} — past the {cap:,.2f} a "
            f"single position may hold ({limit_pct:g}% of the {base:,.2f} "
            f"{base_label})")
        return state

    state["reason"] = f"{at_work:,.2f} of {cap:,.2f} single-position ceiling"
    return state


# How many full-size clips one bet may be built from before the
# concentration ceiling refuses another.
#
# DERIVED, not a second knob. The concentration ceiling is the operator's own
# `max_single_position_pct` times this number, so the two limits cannot
# disagree and there is still only one percentage to set. A second
# independent percentage would drift out of step with the first and mean the
# operator had to reason about which one bit.
#
# 2, because 1 bans scaling into a position outright — a legitimate thing a
# discretionary trader does on purpose — and the failure this exists to stop
# was FIVE clips on one instrument reaching 42% of the book. Two full clips
# is "add to a winner"; five is a different bet wearing the same name.
CONCENTRATION_CLIP_ALLOWANCE = 2.0

def symbol_side_exposure(user, symbol: str, side: str, *, portfolio=None) -> dict:
    """Capital already at work in ONE symbol on ONE side, across both books.

    A "position" is a symbol and a direction, not a ticket. The single-position
    ceiling judged each ticket on its own, so five clips each comfortably under
    it summed to 42% of the book on one instrument — five tickets wearing the
    costume of five decisions when they were one bet, and one adverse print
    hits all five at once.

    Both books, because the bet does not care which table recorded it, and both
    OPEN and CLOSE_PENDING, because a close that has not filled is still
    exposure.
    """
    from bot_program.models import AssetBotTrade
    from portfolio.models import Position
    from portfolio.services import value_per_unit

    want_long = str(side or "").upper() in ("BUY", "LONG")
    total, n, rules = 0.0, 0, []

    for trade in AssetBotTrade.objects.filter(
            config__user=user, symbol__iexact=symbol,
            status__in=("OPEN", "CLOSE_PENDING")).select_related("config"):
        if (str(trade.side or "").upper() in ("BUY", "LONG")) != want_long:
            continue
        notional = (float(trade.entry_price or 0) * float(trade.qty or 0)
                    * value_per_unit(trade))
        total += capital_at_work(trade.asset_class, notional)
        n += 1
        rules.append(trade.rule_name or "—")

    pf = portfolio if portfolio is not None else limits_book()
    for pos in Position.objects.filter(
            portfolio=pf, closed_at__isnull=True,
            instrument__symbol__iexact=symbol).select_related("instrument"):
        if (str(pos.direction or "").lower() in ("long", "buy")) != want_long:
            continue
        notional = float(pos.entry_price or 0) * float(pos.quantity or 0)
        total += capital_at_work(
            getattr(pos.instrument, "asset_class", ""), notional)
        n += 1
        rules.append(getattr(pos.strategy, "name", "") or "—")

    return {"committed": round(total, 2), "n": n, "rules": rules}


def concentration_state(user, *, symbol: str, side: str, asset_class: str,
                        notional: float, capital_base: float = None,
                        base_label: str = "book", portfolio=None) -> dict:
    """Would this ticket put too much of one bet on one instrument?

    The SAME `max_single_position_pct` the card already carries, applied to
    what the operator meant by "a single position": everything they hold in
    that symbol on that side, plus the ticket they are about to add. Judging
    one ticket at a time let the limit be walked past a clip at a time, which
    is exactly how a book ends up with 42% in one name and nothing on any
    screen having refused anything.

    A separate knob was the obvious alternative and the wrong one — a second
    percentage would let the two disagree, and an operator who set "no more
    than 20% in one position" did not mean "per ticket".
    """
    pf = portfolio if portfolio is not None else limits_book()
    limit_pct = _limit_pct(pf, "max_single_position_pct")
    base = (capital_base if capital_base is not None
            else gate_book_value(user, pf))
    held = symbol_side_exposure(user, symbol, side, portfolio=pf)
    adding = capital_at_work(asset_class, notional)
    after = held["committed"] + adding

    state = {"ok": True, "limit_pct": limit_pct, "capital_base": base,
             "base_label": base_label, "held": held["committed"],
             "n_held": held["n"], "rules": held["rules"],
             "adding": round(adding, 2), "after": round(after, 2),
             "cap_money": None, "reason": ""}

    if limit_pct is None:
        state["reason"] = "no single-position limit set on the book"
        return state
    if base is None or base <= 0:
        state["reason"] = (f"the {limit_pct:g}% concentration ceiling is a "
                           f"percentage of a {base_label} that has never "
                           f"been set")
        return state

    cap = base * limit_pct / 100.0 * CONCENTRATION_CLIP_ALLOWANCE
    state["cap_money"] = round(cap, 2)
    state["clip_allowance"] = CONCENTRATION_CLIP_ALLOWANCE
    # Same float slack as the sibling gates, for the same reason.
    if after > cap + 1e-9:
        state["ok"] = False
        already = (f"{held['n']} open ticket(s) already hold "
                   f"{held['committed']:,.2f}" if held["n"]
                   else "nothing is open in it yet")
        state["reason"] = (
            f"this would put {after:,.2f} into {symbol.upper()} "
            f"{'long' if str(side or '').upper() in ('BUY', 'LONG') else 'short'} "
            f"— past the {cap:,.2f} this one bet may hold "
            f"({CONCENTRATION_CLIP_ALLOWANCE:g} clips of {limit_pct:g}% of "
            f"the {base:,.2f} {base_label}); {already}")
        return state

    state["reason"] = (f"{after:,.2f} of {cap:,.2f} in this symbol and side "
                       f"after the add")
    return state


def _position_books(user, portfolio=None) -> set:
    """The legacy-Position books a user's bets can live on: the shared
    limits book AND the user's own `<username>_main` row.

    The NL trader writes to the per-user book, the setup form and the
    eToro sync to the shared one — and a gate that scanned only the
    shared book would let the NL trader's AAPL long hide from a duplicate
    check the setup form's identical long would trip. An explicit
    `portfolio=` stays an override so tests can pin one book.

    (The money gates — symbol_side_exposure, open_capital_at_work — still
    read the shared book alone; their docstrings state that boundary and
    widening it changes limits arithmetic this wave does not touch.)
    """
    if portfolio is not None:
        return {portfolio.pk}
    books = {limits_book().pk}
    if user is not None:
        try:
            from portfolio.services import get_or_create_default_portfolio
            books.add(get_or_create_default_portfolio(user=user).pk)
        except Exception:  # noqa: BLE001 — one unreadable book must not
            pass           # blind the gate to the other
    return books


def _holder_is_long(trade) -> bool:
    """The DIRECTIONAL EXPRESSION an open AssetBotTrade row carries.

    trade.side for every ordinary lane — but the options lane always BUYS
    premium, so a bought PUT is a short expression stored as side="BUY".
    Reading the raw side there inverts this gate both ways at once: a held
    PUT on AAPL falsely refuses a new LONG (the opposite bet) and waves
    through a new SHORT (the same bet, doubled — the one case the gate
    exists for). The lane records its own truth in
    metadata["underlying_signal_direction"]; the contract right is the
    fallback because this lane only ever buys premium, so a PUT can only
    mean short. The write stays side="BUY" — the close path sells the
    premium it bought and must keep reading it that way.
    """
    if str(trade.asset_class or "").lower() == "options":
        meta = trade.metadata or {}
        expr = str(meta.get("underlying_signal_direction") or "").upper()
        if expr:
            return expr in ("BUY", "LONG")
        right = str(meta.get("right") or "").upper()
        if right.startswith("P"):
            return False
        if right.startswith("C"):
            return True
    return str(trade.side or "").upper() in ("BUY", "LONG")


def duplicate_state(user, *, symbol: str, side: str,
                    config_id=None, portfolio=None) -> dict:
    """Is this exact directional bet already on, booked by someone else?

    A refusal, not a taper, and count-based, not money-based — which is why
    `concentration_state` never caught it: two half-size tickets from two
    rules sail under any money ceiling while still being 2x the intended
    expression of one idea. EURGBP BUY held by bollinger_squeeze_breakout
    while manual_take BUYs it again was flagged by the anomaly scanner
    fourteen times in one day, and nothing refused the second ticket,
    because nothing asked the question this function answers.

    `config_id` is the asker's own config: tickets from the SAME config are
    not duplication, they are that one strategy adding a clip, and the
    money ceilings already govern how far that goes. Everything else —
    another bot's config, the manual config when a bot asks, the legacy
    Position book — is a second author writing the same sentence.
    """
    from bot_program.models import AssetBotTrade
    from portfolio.models import Position

    want_long = str(side or "").upper() in ("BUY", "LONG")
    holders: list[str] = []

    qs = AssetBotTrade.objects.filter(
        config__user=user, symbol__iexact=symbol,
        status__in=("OPEN", "CLOSE_PENDING")).select_related("config")
    if config_id is not None:
        qs = qs.exclude(config_id=config_id)
    for trade in qs:
        if _holder_is_long(trade) != want_long:
            continue
        holders.append(trade.rule_name or trade.config.name or "another bot")

    for pos in Position.objects.filter(
            portfolio_id__in=_position_books(user, portfolio),
            closed_at__isnull=True,
            instrument__symbol__iexact=symbol):
        if (str(pos.direction or "").lower() in ("long", "buy")) != want_long:
            continue
        holders.append(getattr(pos.strategy, "name", "") or "portfolio position")

    state = {"ok": True, "holders": holders, "n": len(holders), "reason": ""}
    if holders:
        direction = "long" if want_long else "short"
        state["ok"] = False
        state["reason"] = (
            f"{symbol.upper()} {direction} is already on the book via "
            f"{', '.join(sorted(set(holders)))} — a second ticket doubles "
            f"the bet, it does not diversify it; close that leg first if "
            f"this entry should replace it")
    return state


# The currencies the platform's seeded forex universe actually quotes —
# the 20 bases and quotes of instruments/services.py's 47 pairs. A real
# vocabulary rather than "any six letters", because XAUUSD is six letters
# and alpha too: gold parsed as a currency pair would fabricate an "XAU"
# theme and lend its short-USD leg to the USD crowd the moment a metal
# ever reaches this tally on a misclassified forex row — and the
# asset-class filters are routing, not proof of what a symbol is.
THEME_CURRENCIES = frozenset({
    "AUD", "CAD", "CHF", "CNH", "CZK", "EUR", "GBP", "HKD", "HUF", "JPY",
    "MXN", "NOK", "NZD", "PLN", "RON", "SEK", "SGD", "TRY", "USD", "ZAR",
})


# Forex symbols this platform seeds are six letters, base then quote —
# EURUSD is long EUR / short USD when bought. Anything whose halves are
# not both known currencies (a metal, an odd length, a venue suffix) has
# no currency legs to count.
#: Commodity complexes, by the symbols this catalogue actually carries.
#:
#: The theme gate was forex-only on a stated principle: currencies are the
#: one theme vocabulary a symbol names, and "pretending a ticker names its
#: theme would make this gate lie". That is exactly right for equities —
#: AAPL does not say technology — and exactly wrong for commodities, where
#: BRNUSD, WTIUSD and NGUSD each name their complex as plainly as EURUSD
#: names its currencies.
#:
#: The 2026-08-28 briefing is the evidence: eight of eleven open positions
#: were commodities, six long, and "BRN/WTI/NG is one energy bet wearing
#: three tickets" — the EUR problem this gate was built for, in the one
#: asset class it declined to cover. Every leg cleared every money limit,
#: because every money limit judges a symbol and a complex is not a symbol.
#:
#: Enumerated rather than inferred, and that is the point: this is the same
#: grouping `seed_bots.py` already uses for its starter fleet, so a symbol
#: whose complex is not written here is not GUESSED at — it simply does not
#: participate, which keeps the gate honest about what it knows.
COMMODITY_THEMES: dict[str, str] = {
    # energy
    "WTIUSD": "energy", "BRNUSD": "energy", "NGUSD": "energy",
    "GASUSD": "energy", "HOUSD": "energy",
    # precious and industrial metals
    "XAUUSD": "precious", "XAGUSD": "precious",
    "XPTUSD": "precious", "XPDUSD": "precious",
    "HGUSD": "industrial_metals",
    # grains and softs
    "WHEATUSD": "grains", "CORNUSD": "grains", "SOYUSD": "grains",
    "COFFEEUSD": "softs", "SUGARUSD": "softs",
    "COCOAUSD": "softs", "COTTONUSD": "softs",
}


def _commodity_legs(symbol: str, side: str) -> dict:
    """{complex: +1 long | -1 short} for a commodity this file knows.

    One complex per symbol, unlike a currency pair's two legs: a long
    Brent expresses long energy and nothing else.
    """
    complex_name = COMMODITY_THEMES.get(str(symbol or "").strip().upper())
    if not complex_name:
        return {}
    long_side = str(side or "").upper() in ("BUY", "LONG")
    return {complex_name: 1 if long_side else -1}


def _theme_legs(symbol: str, side: str, asset_class: str) -> dict:
    """The themes this ticket expresses, whatever kind of thing it is."""
    cls = str(asset_class or "").lower()
    if cls == "forex":
        return _currency_legs(symbol, side)
    if cls == "commodity":
        return _commodity_legs(symbol, side)
    return {}


def _currency_legs(symbol: str, side: str) -> dict:
    s = str(symbol or "").strip().upper()
    if len(s) != 6 or not s.isalpha():
        return {}
    if s[:3] not in THEME_CURRENCIES or s[3:] not in THEME_CURRENCIES:
        return {}
    long_side = str(side or "").upper() in ("BUY", "LONG")
    return {s[:3]: 1 if long_side else -1, s[3:]: -1 if long_side else 1}


def theme_state(user, *, symbol: str, side: str, asset_class: str,
                portfolio=None) -> dict:
    """Would this ticket crowd one currency past the book's leg cap?

    The EUR problem, made refusable: six of twelve open positions were EUR
    crosses, five of them long EUR — one ECB headline marking five tickets
    at once — and every leg individually cleared every money limit,
    because every existing limit judges a SYMBOL and a theme is not a
    symbol. This counts open tickets that share a same-direction currency
    with the candidate (long EURUSD and long EURJPY are both long EUR;
    long EURUSD and long USDJPY disagree about USD and do not stack), and
    refuses when the crowd is already at `max_theme_legs`.

    Forex AND commodities: both are asset classes whose symbols NAME
    their theme. Currencies are stated by the pair; complexes are stated
    by the ticker and enumerated in `COMMODITY_THEMES`. Equities are still
    excluded — AAPL does not say technology, and pretending a ticker names
    its sector would make this gate lie. `0` on the card turns it off.

    Commodities were excluded too until the 2026-08-28 briefing measured
    the cost: eight of eleven open positions commodities, six long, and
    three energy legs expressing one view. Every one cleared every money
    limit, because every money limit judges a symbol.
    """
    pf = portfolio if portfolio is not None else limits_book()
    cap = _limit_pct(pf, "max_theme_legs")
    state = {"ok": True, "cap": cap, "currency": None, "n": 0,
             "tickets": [], "reason": ""}

    cls = str(asset_class or "").lower()
    if cls not in ("forex", "commodity"):
        state["reason"] = ("theme legs are counted for forex and "
                           "commodities — a ticker does not name its sector")
        return state
    if cap is None:
        state["reason"] = "no theme-leg cap set on the book"
        return state
    candidate = _theme_legs(symbol, side, cls)
    if not candidate:
        state["reason"] = (
            f"{symbol} does not parse as a currency pair" if cls == "forex"
            else f"{symbol} is not in the commodity complex map")
        return state

    from bot_program.models import AssetBotTrade
    from portfolio.models import Position

    counts: dict[str, int] = {}
    tickets: dict[str, list[str]] = {}

    def _tally(sym, trade_side, label, tally_class=None):
        legs = _theme_legs(sym, trade_side, tally_class or cls)
        for ccy, sign in legs.items():
            if candidate.get(ccy) == sign:
                counts[ccy] = counts.get(ccy, 0) + 1
                tickets.setdefault(ccy, []).append(f"{sym.upper()} ({label})")
                # One ticket counts once per currency, but a pair that
                # shares BOTH currencies with the candidate (the same
                # pair, same side, under another rule) is still one
                # ticket in each crowd — that is what it does to risk.

    # Scoped to the candidate's OWN class. A long EUR leg and a long
    # energy leg are not the same crowd, and counting them together would
    # refuse a perfectly diversified book.
    for trade in AssetBotTrade.objects.filter(
            config__user=user, asset_class=cls,
            status__in=("OPEN", "CLOSE_PENDING")).select_related("config"):
        _tally(trade.symbol, trade.side,
               trade.rule_name or trade.config.name or "bot")
    for pos in Position.objects.filter(
            portfolio_id__in=_position_books(user, portfolio),
            closed_at__isnull=True,
            instrument__asset_class=cls).select_related("instrument"):
        _tally(pos.instrument.symbol, pos.direction,
               getattr(pos.strategy, "name", "") or "position")

    if not counts:
        state["reason"] = ("no open ticket shares a directional currency"
                           if cls == "forex"
                           else "no open ticket shares this complex")
        return state

    worst = max(counts, key=lambda c: counts[c])
    state["currency"] = worst
    state["n"] = counts[worst]
    state["tickets"] = tickets[worst]
    if counts[worst] >= cap:
        direction = ("long" if candidate[worst] > 0 else "short")
        theme_word = "currency" if cls == "forex" else "commodity"
        mover = (worst if cls == "forex"
                 else f"{worst.replace('_', ' ')} complex")
        state["ok"] = False
        state["reason"] = (
            f"{counts[worst]} open ticket(s) already express {direction} "
            f"{mover} ({', '.join(tickets[worst])}) — the book caps one "
            f"{theme_word} theme at {cap:g} leg(s); one {mover} repricing "
            f"marks them all at once")
        return state
    state["reason"] = (f"{counts[worst]} of {cap:g} allowed leg(s) share "
                       f"{'long' if candidate[worst] > 0 else 'short'} "
                       f"{worst} with this ticket")
    return state


def correlation_state(user, instrument, *, portfolio=None,
                      lookback_days: int = CORRELATION_LOOKBACK_DAYS) -> dict:
    """How correlated a candidate is to the open book, and the size taper.

    {"scale", "max_corr", "peer", "threshold", "measured", "reason"}

    A taper and not a refusal, because that is what this platform's shipped
    correlation machinery does and what the number can honestly support:
    `max_corr` is a 90-day daily-return correlation, which says a second
    position is a partly-duplicated bet, not that it is a mistake. Sizing it
    down is the proportionate answer; a hard block on 0.70 would refuse most
    of a forex book outright, and refusing everything is how a limit gets
    turned off.

    `measured` False means there was nothing to correlate against — an empty
    book, or not enough daily history — and the scale is then 1.0 because
    nothing was measured, not because the candidate was cleared.
    """
    from instruments.models import Instrument
    from portfolio.correlation import compute_correlation
    from portfolio.models import Position
    from bot_program.models import AssetBotTrade

    portfolio = portfolio if portfolio is not None else limits_book()
    threshold = _limit_pct(portfolio, "max_correlation_threshold")
    blank = {"scale": 1.0, "max_corr": None, "peer": None,
             "threshold": threshold, "measured": False, "reason": ""}

    if threshold is None or threshold >= 1.0:
        # `_limit_pct` returns None for a threshold of 0 as well as an unset
        # one, and both mean off here: nothing correlates above 1.0, and a 0
        # threshold would put every position that correlates with anything at
        # all on the taper, which is a size cut nobody asked for rather than a
        # limit. Either way the several PriceData scans below are dead work, so
        # they never run.
        blank["reason"] = ("correlation taper off — the threshold is not a "
                           "number strictly between 0 and 1")
        return blank
    if instrument is None or getattr(instrument, "pk", None) is None:
        blank["reason"] = "candidate has no instrument row to correlate"
        return blank

    symbols = set(AssetBotTrade.objects.filter(
        config__user=user, status__in=("OPEN", "CLOSE_PENDING")
    ).values_list("symbol", flat=True))
    peer_ids = set(Position.objects.filter(
        portfolio=portfolio, closed_at__isnull=True
    ).values_list("instrument_id", flat=True))
    if symbols:
        peer_ids |= set(Instrument.objects.filter(symbol__in=symbols)
                        .values_list("id", flat=True))
    peer_ids.discard(instrument.pk)
    if not peer_ids:
        blank["reason"] = "nothing open to be correlated with"
        return blank

    peers = list(Instrument.objects.filter(id__in=peer_ids))
    matrix = compute_correlation([instrument, *peers],
                                 lookback_days=lookback_days)
    best_corr, best_peer, best_abs = None, None, -1.0
    for peer in peers:
        corr = matrix.get(instrument.symbol, peer.symbol)
        if corr is None:
            continue
        if abs(corr) > best_abs:
            best_abs, best_corr, best_peer = abs(corr), corr, peer.symbol

    if best_peer is None:
        blank["reason"] = (f"{len(peers)} position(s) open but none has "
                           f"{lookback_days}d of daily bars to correlate")
        return blank

    state = {"scale": 1.0, "max_corr": round(best_corr, 4), "peer": best_peer,
             "threshold": threshold, "measured": True, "reason": ""}
    if best_abs <= threshold:
        state["reason"] = (f"correlation {best_abs:.2f} to {best_peer} is "
                           f"within the {threshold:.2f} threshold")
        return state

    # Linear from full size at the threshold to CORRELATION_MIN_SCALE at
    # perfect correlation — the shape PositionSizer.correlation_aware_scale
    # already applies, so the two never disagree about what the number does.
    room = max(1.0 - threshold, 1e-6)
    scale = max(CORRELATION_MIN_SCALE,
                1.0 - (1.0 - CORRELATION_MIN_SCALE) * (best_abs - threshold) / room)
    state["scale"] = round(scale, 4)
    state["reason"] = (f"correlation {best_abs:.2f} to {best_peer} exceeds the "
                       f"{threshold:.2f} threshold — sizing to {scale:.0%}")
    return state


def preflight(user, *, portfolio=None, now=None) -> dict:
    """The book-level limits, checked before any new position anywhere.

    Returns {"ok": bool, "failed_open": bool, "reason": str, "checks": {...}}.
    Only the two limits that need no candidate — daily loss and total exposure
    — because this is what `AssetBot.can_open_new()` can answer: it runs once
    per tick, before any symbol has been chosen. The size-dependent limits are
    `single_position_state` (checked where the quantity exists) and
    `correlation_state` (checked where the instrument does).

    FAILS OPEN on an exception, loudly. A gate that cannot read the book is a
    gate with nothing to say, and halting an entire fleet on a transient
    database hiccup is a worse failure than the one tick of unenforced trading
    it would prevent — the same posture the orchestrator and brain advisories
    take at this point in the entry path. The ERROR line and the returned
    reason are what stop that being silent: the reason travels into the bot's
    heartbeat note and into the manual popup.

    `failed_open` is that state made answerable rather than inferred. `ok`
    True carries two opposite meanings — the limits were read and cleared, or
    they could not be read and are binding nothing — and a screen that cannot
    tell them apart paints its most reassuring badge exactly when the gate is
    broken. Anything that renders this reads the flag, not `ok` alone.
    """
    checks: dict = {}
    try:
        portfolio = portfolio if portfolio is not None else limits_book()
        checks["daily_loss"] = daily_loss_state(user, portfolio=portfolio,
                                                now=now)
        checks["exposure"] = exposure_state(user, portfolio=portfolio)
    except Exception as e:  # noqa: BLE001 — see the fail-open note above
        logger.error("[risk_gate] book limits unreadable, entries NOT gated "
                     "this pass: %s", e, exc_info=True)
        return {"ok": True, "failed_open": True, "checks": checks,
                "reason": f"book risk limits could not be read ({e}) — "
                          f"entries are not gated by them right now"}

    blocked = [c["reason"] for c in checks.values() if not c["ok"]]
    if blocked:
        return {"ok": False, "failed_open": False, "checks": checks,
                "reason": "book risk limits: " + "; ".join(blocked)}
    return {"ok": True, "failed_open": False, "checks": checks,
            "reason": "; ".join(c["reason"] for c in checks.values()
                                if c["reason"])}
