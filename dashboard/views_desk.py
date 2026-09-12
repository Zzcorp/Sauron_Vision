"""The capital desk's page — /desk/.

The operator asked for this in these words: "a graphical interface and a page
that illustrates the capital desk, giving perfect understanding and vision of
what Sauron is doing". So this page EXPLAINS; it does not merely tabulate.
Every section answers one question in plain words before it shows a number:

  1. one sentence — what happened on the last tick, in English
  2. the KPI strip — mode, age, budget, candidates, edge, matrix coverage
  3. the risk budget bar — how much risk is on the table and how much is left
  4. the candidate ladder — every entry the tick produced, ranked, with ONE
     sentence of why it was taken, resized or displaced
  5. what the desk changed — in shadow, the counterfactual being graded
  6. the correlation heat of the chosen set plus the open book
  7. concentration by rule and by class, each against its cap
  8. the record — the last twenty plans and whether the desk earned its keep

SERVER-RENDERED ONLY. No JavaScript, no chart library, no external asset:
every bar is a div width this view computed, and the ladder marks and the
sparkline are inline SVG whose points this view computed. A page about risk
that cannot render without a CDN is a page that goes blank on the day the
network is the problem.

EVERY NUMBER CARRIES ITS SOURCE AND ITS AGE, and an unmeasured quantity
renders an em dash — never a zero. On a platform with almost no track record
that is the whole difference between "the desk measured no edge" and "the
desk could not measure one" (2026-09-12).

Every read is fenced. A page that 500s because the correlation matrix or the
drawdown governor is unreadable hides the plan the operator came to read, and
a desk nobody can read is a desk nobody should switch to live.
"""
import logging
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils import timezone

logger = logging.getLogger(__name__)

# What a non-staff login reads in place of the platform-wide zone, the same
# rule /ops/ and /health/ follow: the per-user plan is for anyone who owns
# it; the switch states and the beat's own error text are staff's.
STAFF_ONLY = "staff only — platform-wide, as on /health/"

# At most twelve symbols in the heat map: a thirteenth column makes every
# cell too narrow to carry its number, and a correlation you cannot read is
# decoration.
HEAT_MAX = 12

# The command that changes each empty state. An empty state that does not
# name its own fix is a dead end.
CMD_ON = "./deploy/dc exec web python manage.py component on pipeline_capital_desk"
CMD_LIVE = "./deploy/dc exec web python manage.py component on capital_desk_mode_live"
CMD_GRADE = "./deploy/dc exec web python manage.py desk grade"

_WORDS = {0: "none", 1: "one", 2: "two", 3: "three", 4: "four", 5: "five",
          6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten",
          11: "eleven", 12: "twelve"}

# The stored `reason` on a decision starts with a machine token; these are the
# plain words for it. The rest of the stored string is appended verbatim —
# the page NEVER recomputes a reason, because a reason recomputed at read
# time is a reason about today's book, not the one the desk actually saw.
_WHY = {
    "budget": "the tick's risk budget was spent",
    "rule_share": "one rule already held its share of the tick's risk",
    "class_share": "one asset class already held its share of the tick's risk",
    "config_halted": "its own bot could not take another position",
    "duplicate": "another config proposed the same bet",
}

# The lane, short enough to sit inside a sentence. get_lane_display() is
# written for a column header ("This config, live") and reads badly mid-
# clause ("on the this config, live lane"), so the ladder uses these.
_LANE_PHRASE = {
    "config_live": "this bot's own live record",
    "user_live": "this account's live fleet",
    "fleet_live": "every account's live fleet",
    "fleet_paper": "the paper fleet, haircut for execution",
    "signal": "the signal lane, haircut for execution",
}


def _f(value, default=0.0) -> float:
    try:
        if value is None:
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _pct(part, whole) -> float:
    """A bar width in percent, clipped into [0, 100]. Never divides by zero —
    a bar whose denominator is unmeasured is a bar of width nothing."""
    whole = _f(whole)
    if whole <= 0:
        return 0.0
    return max(0.0, min(100.0, _f(part) / whole * 100.0))


def _word(n) -> str:
    return _WORDS.get(int(n), str(int(n)))


def _reason_words(reason: str) -> str:
    """'rule_share — X would hold 55% …' → 'one rule already held its share
    of the tick's risk: X would hold 55% …'.

    Only the machine token in front is translated; the rest of the stored
    string is passed through verbatim, and an unrecognised reason is returned
    untouched. Inventing a phrase for a reason the desk did not write would
    put words in the desk's mouth, which is worse than a raw token.
    """
    text = str(reason or "")
    token, sep, rest = text.partition(" — ")
    phrase = _WHY.get(token.strip())
    if phrase is None:
        return text
    return f"{phrase}: {rest}" if sep and rest else phrase


def _detail_only(reason: str) -> str:
    """The half of a stored reason after its leading clause — used where the
    badge already says what happened ('RESIZED ×0.60' then 'resized to
    x0.60 — …' twice over is noise, not explanation)."""
    text = str(reason or "")
    _token, sep, rest = text.partition(" — ")
    return rest if sep and rest else text


def _marginal(plan):
    """The MARGINAL total the chooser actually spent on a plan, or None.

    THE BUDGET IS NOT SPENT IN RISK-AT-STOP. `choose` spends it in marginal
    risk — the correlation-aware increment each pick adds to the book — and
    `new_risk_chosen` is the raw sum of risk-at-stop, a different quantity.
    Drawing the raw sum against the budget showed "30 of 78 spent" on a tick
    the chooser had stopped at the budget's own edge: a number the desk never
    used, on the page whose job is to say what it did.

    None for a plan written before `new_risk_marginal` existed, and that is
    an em dash on the page — the desk spent something and nobody recorded how
    much, which is not zero (2026-09-12).
    """
    value = getattr(plan, "new_risk_marginal", None)
    return None if value is None else _f(value)


def _currency(user) -> str:
    from bot_program.models import AssetBotConfig
    return (AssetBotConfig.objects.filter(user=user, enabled=True)
            .values_list("base_currency", flat=True).first() or "USD")


# ── the ladder ───────────────────────────────────────────────────────────

def _lane_phrase(decision) -> str:
    """What the rank was built on, in words. An unmeasured candidate says so
    and shows NO expected R — the badge is the honest answer, and a 0.00 in
    the same column as a real edge is the lie this page exists to avoid."""
    if decision.measured and decision.e_r is not None:
        lane = _LANE_PHRASE.get(decision.lane, decision.get_lane_display())
        sign = "+" if decision.e_r >= 0 else ""
        phrase = (f"{sign}{decision.e_r:.2f}R over {decision.n} graded "
                  f"fill{'s' if decision.n != 1 else ''} of {lane}")
        if decision.decaying:
            phrase += ", halved because the rule is decaying"
        return phrase
    return ("ranked on conviction only — this rule is under the floor of "
            "ten graded fills")


def _ladder(plan, decisions, *, budget_base, currency):
    """One row per decision, in the order the money was offered."""
    best = 0.0
    for d in decisions:
        key = _f(d.e_r) if (d.measured and d.e_r is not None) else _f(d.rank_key)
        best = max(best, key)

    rows = []
    for d in decisions:
        key = _f(d.e_r) if (d.measured and d.e_r is not None) else _f(d.rank_key)
        corr = ("" if d.corr_max is None
                else f", correlation {d.corr_max:+.2f} to what is open")
        lane = _lane_phrase(d)
        marginal = _f(d.marginal_risk)
        adds = (f"adds {marginal:,.2f} of the {budget_base:,.2f} "
                f"{currency} budget" if budget_base > 0 else
                f"adds {marginal:,.2f} {currency}")

        if d.outcome == "chosen":
            badge, tone = "CHOSEN", "up"
            why = f"taken at full size — {lane}, {adds}{corr}"
        elif d.outcome == "resized":
            badge, tone = f"RESIZED ×{d.size_mult:.2f}", "up"
            why = (f"taken at ×{d.size_mult:.2f} of the size its own bot had "
                   f"already cleared — {lane}; {_detail_only(d.reason)}")
        elif d.outcome == "displaced":
            badge, tone = "DISPLACED", "down"
            why = f"displaced — {_reason_words(d.reason)}"
        elif d.outcome == "duplicate":
            badge, tone = "DUPLICATE", "muted"
            why = _reason_words(d.reason)
        elif d.outcome == "not_desked":
            badge, tone = "NOT DESKED", "muted"
            why = d.reason or "this lane trades whole — never desked"
        else:
            badge, tone = "REFUSED AFTERWARDS", "down"
            why = (f"the desk chose it and the book would not take it — "
                   f"{d.reason}")

        rows.append({
            "d": d, "badge": badge, "tone": tone, "why": why,
            "key": key, "key_pct": _pct(key, best),
            "risk_pct": _pct(marginal, budget_base),
            "measured": bool(d.measured and d.e_r is not None),
        })
    return rows


# ── the sentence at the top ──────────────────────────────────────────────

def _headline(plan, decisions, *, currency, desk_on, live_mode):
    """The card that makes this page understandable in three seconds."""
    if plan is None:
        if not desk_on:
            return ("The desk has not run — pipeline_capital_desk is OFF. "
                    f"Turn it on with `{CMD_ON}`.")
        return ("No candidate cleared the gates on the last tick — the desk "
                "ran and there was nothing to rank.")
    if plan.error:
        return (f"The desk FAILED on the last tick and the fleet ran undesked "
                f"— every candidate executed at its own size, exactly as it "
                f"does with the component off. The error was: {plan.error}")

    bots = len({d.config_id for d in decisions})
    kept = plan.n_chosen + plan.n_resized
    gross = _f(plan.budget) + _f(plan.book_risk)
    took = _f(plan.new_risk_chosen)
    marginal = _marginal(plan)
    verb = "committed" if live_mode else "would have committed"

    text = (f"Last tick the desk saw {_word(plan.n_candidates)} "
            f"candidate{'s' if plan.n_candidates != 1 else ''} across "
            f"{_word(bots)} bot{'s' if bots != 1 else ''}, kept "
            f"{_word(kept)}, and ")
    # THE BUDGET WAS SPENT IN MARGINAL RISK, so that is the number this
    # sentence puts against it. The raw risk at stop follows, named, because
    # it is the other true thing about the same entries — what the account
    # loses if every one of those stops is hit.
    if marginal is None:
        text += (f"{verb} a MARGINAL total this plan did not record — it was "
                 f"written before the desk stored one and this page will not "
                 f"invent it. The RAW risk at stop on those entries was "
                 f"{took:,.0f} {currency}, against a {gross:,.0f} {currency} "
                 f"{plan.venue} budget")
    else:
        text += (f"{verb} {marginal:,.0f} of the {gross:,.0f} {currency} of "
                 f"MARGINAL risk the {plan.venue} budget allows — the "
                 f"correlation-aware increment the chooser actually spends. "
                 f"The RAW risk at stop on the same entries is {took:,.0f} "
                 f"{currency}, which is what the account loses if every one "
                 f"of those stops is hit")

    refused = [d for d in decisions if d.outcome in ("displaced", "duplicate")]
    if refused:
        buckets = {}
        for d in refused:
            token = str(d.reason or "").partition(" — ")[0].strip() or "other"
            buckets[token] = buckets.get(token, 0) + 1
        parts = []
        for token, n in sorted(buckets.items(), key=lambda kv: -kv[1]):
            parts.append(f"{_word(n)} because "
                         f"{_WHY.get(token, 'the desk ranked them lower')}")
        text += (f"; it displaced {_word(len(refused))} — "
                 + ", ".join(parts))
    text += "."
    if not live_mode:
        text += (" In SHADOW nothing was changed: every candidate traded at "
                 "its own size and this plan is the counterfactual being "
                 "graded.")
    return text


# ── the heat map ─────────────────────────────────────────────────────────

def _heat(user, decisions, book_entries, *, now):
    """A square of |bet correlation| over the chosen set plus the open book.

    An unmeasured pair is BLANK with a middle dot, never a zero: rho = 0 is
    what the arithmetic has to assume, and rendering that assumption as a
    measurement is how a page turns "we have no history for this pair" into
    "these two are unrelated".
    """
    from bot_program import capital_desk

    chosen = [d for d in decisions if d.outcome in ("chosen", "resized")]
    wanted, direction = [], {}
    for d in chosen:
        sym = (d.symbol or "").upper()
        if sym not in direction:
            wanted.append(sym)
            direction[sym] = d.direction
    for entry in sorted(book_entries, key=lambda e: -_f(e.get("risk"))):
        sym = (entry.get("symbol") or "").upper()
        if sym and sym not in direction:
            wanted.append(sym)
            direction[sym] = entry.get("direction", "BUY")

    truncated = len(wanted) > HEAT_MAX
    wanted = wanted[:HEAT_MAX]
    if len(wanted) < 2:
        return {"symbols": [], "rows": [], "truncated": False,
                "measured": 0, "total": 0,
                "note": "fewer than two positions to correlate"}

    try:
        matrix = capital_desk.correlation_matrix(user, wanted, now=now)
    except Exception as e:  # noqa: BLE001 — the page renders regardless
        logger.warning("[desk page] correlation matrix unreadable: %s", e)
        return {"symbols": [], "rows": [], "truncated": False,
                "measured": 0, "total": 0,
                "note": f"correlation matrix unreadable: {e}"[:160]}

    measured_pairs = matrix.get("measured") or set()
    rows = []
    measured = total = 0
    for a in wanted:
        cells = []
        for b in wanted:
            if a == b:
                cells.append({"self": True, "value": None, "tint": 0.0})
                continue
            total += 1
            pair = (a, b) if a < b else (b, a)
            if pair not in measured_pairs:
                cells.append({"self": False, "value": None, "tint": 0.0})
                continue
            measured += 1
            rho = capital_desk.bet_rho(matrix, a, direction.get(a),
                                       b, direction.get(b))
            cells.append({"self": False, "value": round(rho, 2),
                          "tint": round(min(1.0, abs(rho)), 3)})
        rows.append({"symbol": a, "direction": direction.get(a, ""),
                     "cells": cells})
    return {"symbols": wanted, "rows": rows, "truncated": truncated,
            "measured": measured // 2, "total": total // 2, "note": ""}


# ── concentration ────────────────────────────────────────────────────────

def _concentration(decisions, *, budget_base, currency):
    from bot_program.capital_desk import (DESK_MAX_CLASS_SHARE,
                                          DESK_MAX_RULE_SHARE)

    by_rule, by_class = {}, {}
    for d in decisions:
        if d.outcome not in ("chosen", "resized"):
            continue
        risk = _f(d.risk_dollars_default) * _f(d.size_mult, 1.0)
        by_rule[d.rule_name or "(unnamed)"] = (
            by_rule.get(d.rule_name or "(unnamed)", 0.0) + risk)
        cls = getattr(d.config, "asset_class", "") or "(unknown)"
        by_class[cls] = by_class.get(cls, 0.0) + risk

    def _bars(bucket, cap):
        out = []
        for name, risk in sorted(bucket.items(), key=lambda kv: -kv[1]):
            share = _pct(risk, budget_base)
            out.append({"name": name, "risk": risk, "pct": share,
                        "at_cap": budget_base > 0 and share >= cap * 100 - 0.5})
        return out

    return {
        "rules": _bars(by_rule, DESK_MAX_RULE_SHARE),
        "classes": _bars(by_class, DESK_MAX_CLASS_SHARE),
        "rule_cap_pct": DESK_MAX_RULE_SHARE * 100,
        "class_cap_pct": DESK_MAX_CLASS_SHARE * 100,
        "base": budget_base, "currency": currency,
        "measured": budget_base > 0,
    }


# ── the record ───────────────────────────────────────────────────────────

def _sparkline(plans, *, width=560.0, height=44.0):
    """Inline-SVG points for edge_r across the plans, oldest first, with the
    zero line. Computed here because the template cannot do arithmetic and
    this page ships no JavaScript."""
    graded = [p for p in reversed(plans) if p.edge_r is not None]
    if len(graded) < 2:
        return {"points": "", "zero_y": height / 2, "n": len(graded),
                "width": width, "height": height}
    values = [float(p.edge_r) for p in graded]
    lo, hi = min(values + [0.0]), max(values + [0.0])
    span = (hi - lo) or 1.0
    step = width / (len(values) - 1)
    pts = []
    for i, v in enumerate(values):
        y = height - (v - lo) / span * height
        pts.append(f"{i * step:.1f},{y:.1f}")
    return {"points": " ".join(pts),
            "zero_y": round(height - (0.0 - lo) / span * height, 1),
            "n": len(values), "width": width, "height": height}


# ── the page ─────────────────────────────────────────────────────────────

@login_required
def desk_dashboard(request):
    from bot_program import capital_desk
    from bot_program.models import DeskPlan

    user = request.user
    now = timezone.now()
    is_staff = bool(user.is_staff or user.is_superuser)
    currency = "USD"
    try:
        currency = _currency(user)
    except Exception as e:  # noqa: BLE001
        logger.warning("[desk page] currency unreadable: %s", e)

    desk_on = live_mode = False
    try:
        desk_on = capital_desk.is_desk_enabled()
        live_mode = capital_desk.is_live_mode()
    except Exception as e:  # noqa: BLE001
        logger.warning("[desk page] switches unreadable: %s", e)

    plans = list(DeskPlan.objects.filter(user=user)[:20])
    plan = plans[0] if plans else None
    decisions = []
    if plan is not None:
        try:
            decisions = list(plan.decisions.select_related("config")
                             .order_by("rank", "id"))
        except Exception as e:  # noqa: BLE001
            logger.warning("[desk page] decisions unreadable: %s", e)

    # ── the budget bar, one per venue ────────────────────────────────
    latest_by_venue = {}
    for p in plans:
        latest_by_venue.setdefault(p.venue, p)
    venues = []
    for venue in ("live", "paper"):
        row = {"venue": venue, "currency": currency, "error": "",
               "plan": latest_by_venue.get(venue)}
        try:
            info = capital_desk.budget_for(user, venue, now=now)
        except Exception as e:  # noqa: BLE001
            logger.warning("[desk page] %s budget unreadable: %s", venue, e)
            venues.append(dict(row, error=f"{type(e).__name__}: {e}"[:160],
                               capital=None))
            continue
        governor = _f(info.get("governor"), 1.0)
        full = _f(info["capital"]) * capital_desk.DESK_RISK_BUDGET_PCT / 100.0
        governed = full * governor
        book = max(0.0, _f(info["book_risk"]))
        # `new` is the MARGINAL total the chooser spent — the unit the budget
        # was consumed in — and `new_raw` is the raw risk at stop on the same
        # entries. Both are rendered, each labelled, because a bar that shows
        # one under the other's heading is the page lying about arithmetic it
        # did not do. `new` is None on a plan older than the column.
        new = _marginal(row["plan"])
        new_raw = _f(getattr(row["plan"], "new_risk_chosen", 0.0))
        free = max(0.0, governed - book - _f(new))
        row.update({
            "capital": _f(info["capital"]), "full": full,
            "governed": governed, "book": book, "new": new,
            "new_raw": new_raw, "free": free,
            "cut": max(0.0, full - governed), "governor": governor,
            "governor_text": info.get("reason", ""),
            "unmeasured_open": info.get("unmeasured_open", 0),
            "n_open": info.get("n_open", 0),
            "book_pct": _pct(book, full), "new_pct": _pct(new, full),
            "free_pct": _pct(free, full),
            "cut_pct": _pct(max(0.0, full - governed), full),
            "governed_pct": _pct(governed, full),
            "entries": info.get("entries", []),
        })
        venues.append(row)

    budget_base = _f(getattr(plan, "budget", 0.0))
    ladder = _ladder(plan, decisions, budget_base=budget_base,
                     currency=currency) if plan is not None else []

    # ── what the desk changed ────────────────────────────────────────
    changed = {"mode": "live" if live_mode else "shadow", "fleet": None,
               "desk": None, "differ": [], "applied": ""}
    if plan is not None:
        traded = [d for d in decisions if d.trade_id]
        desk_set = [d for d in decisions if d.outcome in ("chosen", "resized")]
        changed["fleet"] = {
            "entries": len(traded),
            "risk": sum(_f(d.risk_dollars_default) for d in traded),
            "symbols": sorted({d.symbol for d in traded}),
        }
        changed["desk"] = {
            "entries": len(desk_set),
            "risk": sum(_f(d.risk_dollars_default) * _f(d.size_mult, 1.0)
                        for d in desk_set),
            "symbols": sorted({d.symbol for d in desk_set}),
        }
        changed["differ"] = sorted(
            set(changed["fleet"]["symbols"]) ^ set(changed["desk"]["symbols"]))
        changed["applied"] = (f"{plan.n_resized} resized, "
                              f"{plan.n_displaced} displaced")

    # ── the KPI strip ────────────────────────────────────────────────
    week = [p for p in DeskPlan.objects.filter(
        user=user, graded_at__isnull=False,
        graded_at__gte=now - timedelta(days=7)) if p.edge_r is not None]
    edge_7d = sum(float(p.edge_r) for p in week) if week else None

    # The book behind the heat map is the PLAN'S OWN VENUE. Paper and live
    # never share a budget, a book or a correlation penalty anywhere else in
    # this platform, and a heat map that mixed them would show a paper
    # position "concentrating" a live one.
    book_entries = []
    for row in venues:
        if plan is not None and row["venue"] != plan.venue:
            continue
        book_entries.extend(row.get("entries") or [])
    heat = _heat(user, decisions, book_entries, now=now)

    # ── the platform-wide zone: staff only, the rule /ops/ follows ───
    platform = {"staff_only": True, "error": STAFF_ONLY, "components": [],
                "last_grade": None}
    if is_staff:
        platform = {"staff_only": False, "error": "", "components": [],
                    "last_grade": None}
        try:
            from core.platform_control import PlatformComponent
            rows = {c.key: c for c in PlatformComponent.objects.filter(
                key__in=(capital_desk.PIPELINE_COMPONENT,
                         capital_desk.LIVE_COMPONENT))}
            for key in (capital_desk.PIPELINE_COMPONENT,
                        capital_desk.LIVE_COMPONENT):
                comp = rows.get(key)
                platform["components"].append({
                    "key": key, "row": comp,
                    "on": bool(comp and comp.is_enabled),
                    "registered": comp is not None,
                    "command": (f"./deploy/dc exec web python manage.py "
                                f"component on {key}"),
                })
            platform["last_grade"] = (
                DeskPlan.objects.filter(graded_at__isnull=False)
                .order_by("-graded_at").first())
        except Exception as e:  # noqa: BLE001
            logger.warning("[desk page] platform zone unreadable: %s", e)
            platform["error"] = f"{type(e).__name__}: {e}"[:160]

    context = {
        "page_id": "desk",
        "now": now,
        "currency": currency,
        "desk_on": desk_on,
        "live_mode": live_mode,
        "is_staff": is_staff,
        "is_admin": bool(user.is_superuser),
        "headline": _headline(plan, decisions, currency=currency,
                              desk_on=desk_on, live_mode=live_mode),
        "plan": plan,
        "plans": plans,
        "decisions": decisions,
        "ladder": ladder,
        "venues": venues,
        "budget_base": budget_base,
        "changed": changed,
        "heat": heat,
        "concentration": _concentration(decisions, budget_base=budget_base,
                                        currency=currency),
        "sparkline": _sparkline(plans),
        "edge_7d": edge_7d,
        "edge_7d_n": len(week),
        "platform": platform,
        "cmd_on": CMD_ON,
        "cmd_live": CMD_LIVE,
        "cmd_grade": CMD_GRADE,
        "risk_pct": capital_desk.DESK_RISK_BUDGET_PCT,
        "min_n": capital_desk.DESK_MIN_N,
        "min_mult": capital_desk.DESK_MIN_MULT,
        "corr_bars": capital_desk.CORR_BARS,
        "heat_max": HEAT_MAX,
    }
    return render(request, "dashboard/desk.html", context)
