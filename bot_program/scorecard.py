"""THE SCORECARD (2026-10-02): is the book paid for its losses?

The operator: "our Sauron is unfortunately not winning over the long run...
too many losing trades on my part, maybe?" The week's closed rows said
otherwise. 15 of 24 won — 62%, a good rate. What lost was the PAYOFF and
two stops: the average winner was +0.42R, 12 of the 15 winners were closed
by hand at +0.28R on average (several in one minute), and two paper stops
did not hold (-8.12R, -1.84R). With those two the book needed winners of
+1.09R; without them it was level — +0.42R paid against the +0.43R a 68%
win rate needs. Never paid.

No page said so. Aragorn grades a rule by its expectancy, which is the
right verdict and the wrong diagnosis: a negative number does not say
whether the fault is the win rate, the size of the wins or the size of
the losses. This module splits it:

  win rate, average win, average loss   the three numbers expectancy is
  payoff, break-even win rate           the payoff a book needs at its win
                                        rate, against the one it gets
  closed by hand                        how many winners were cut short,
                                        at what R, and what they had seen
                                        (MFE, from position care)
  gave back                             losers that had been +1R first
  overshoot                             a loss past -OVERSHOOT_R: a stop
                                        that did not hold

Read-only and pure where it can be: `summarize` takes plain rows, so the
scorecard command, the close dialog and a test all ask the same question
of the same arithmetic. Unmeasured exits (realized_r NULL) are counted
and left out — never read as zero.
"""
from __future__ import annotations

from datetime import timedelta

#: A closed loss worse than this is a stop that did not hold: a gap, a
#: stop nobody watched, a reconciliation that booked late.
OVERSHOOT_R = 1.2
#: The R a winner is said to have "reached" before it was cut or given back.
REACHED_R = 1.0
#: Fewer closed trades than this, and the scorecard says the sample is thin.
THIN_SAMPLE = 20
#: The tag manual_close.CLOSE_REASON leaves on a row closed by hand.
HAND_CLOSE_TAG = "closed:MANUAL"


def row_of(trade) -> dict:
    """The fields the scorecard reads, from one AssetBotTrade."""
    from bot_program.manual_trade import MANUAL_RULE
    meta = trade.metadata or {}
    care = meta.get("care") or {}
    mfe = care.get("mfe_r")
    try:
        mfe = float(mfe) if mfe is not None else None
    except (TypeError, ValueError):
        mfe = None
    rule = trade.rule_name or ""
    return {
        "id": trade.pk,
        "symbol": trade.symbol,
        "asset_class": trade.asset_class,
        "rule": rule,
        "lane": "manual" if rule == MANUAL_RULE else "bots",
        "venue": "paper" if trade.paper else "live",
        "r": trade.realized_r,
        "outcome": trade.outcome or "",
        "by_hand": HAND_CLOSE_TAG in (trade.reason or ""),
        # Whether a Sauron signal stood behind the entry: a bot's always
        # does; a hand-taken one carries its signal_id when it had one.
        "backed": rule != MANUAL_RULE or bool(meta.get("signal_id")),
        "mfe": mfe,
        "closed_at": trade.closed_at,
    }


def rows(*, days=30, user=None, venue=None, now=None) -> list:
    """Closed rows of the last `days` days, as scorecard rows."""
    from django.utils import timezone

    from bot_program.asset_models import AssetBotTrade
    now = now or timezone.now()
    qs = AssetBotTrade.objects.filter(
        status="CLOSED", closed_at__gte=now - timedelta(days=days))
    if user is not None:
        qs = qs.filter(config__user=user)
    if venue == "live":
        qs = qs.filter(paper=False)
    elif venue == "paper":
        qs = qs.filter(paper=True)
    return [row_of(t) for t in qs.order_by("-closed_at")]


def _mean(xs):
    return sum(xs) / len(xs) if xs else None


def summarize(rows_) -> dict:
    """Every number the scorecard prints, for one group of rows.

    `expectancy` is the mean R per measured trade. `payoff` is the average
    win over the average loss; `breakeven_win_rate` the win rate that
    payoff needs to stand still, and `needed_avg_win` the average win the
    ACTUAL win rate needs — the two ways of saying the same gap."""
    measured = [r for r in rows_ if r.get("r") is not None]
    rs = [float(r["r"]) for r in measured]
    wins = [x for x in rs if x > 0]
    losses = [x for x in rs if x < 0]
    n = len(rs)
    win_rate = len(wins) / n if n else None
    avg_win = _mean(wins)
    avg_loss = _mean(losses)
    payoff = (avg_win / abs(avg_loss)
              if avg_win is not None and avg_loss else None)
    breakeven = 1.0 / (1.0 + payoff) if payoff else None
    needed = (abs(avg_loss) * (1 - win_rate) / win_rate
              if avg_loss is not None and win_rate else None)

    hand = [r for r in measured if r["by_hand"]]
    hand_wins = [r for r in hand if float(r["r"]) > 0]
    hand_win_mfe = [r["mfe"] for r in hand_wins if r["mfe"] is not None]
    gave_back = [r for r in measured
                 if float(r["r"]) < 0 and r["mfe"] is not None
                 and r["mfe"] >= REACHED_R]
    overshoot = [r for r in measured if float(r["r"]) < -OVERSHOOT_R]
    return {
        "n": n,
        "unmeasured": len(rows_) - n,
        "thin": n < THIN_SAMPLE,
        "wins": len(wins), "losses": len(losses),
        "win_rate": win_rate,
        "avg_win": avg_win, "avg_loss": avg_loss,
        "expectancy": _mean(rs),
        "sum_r": sum(rs) if rs else None,
        "payoff": payoff,
        "breakeven_win_rate": breakeven,
        "needed_avg_win": needed,
        "by_hand": len(hand),
        "by_hand_wins": len(hand_wins),
        "by_hand_win_avg": _mean([float(r["r"]) for r in hand_wins]),
        "by_hand_win_mfe": _mean(hand_win_mfe),
        "targets_hit": sum(1 for r in measured
                           if r["outcome"] == "hit_target"),
        "gave_back": len(gave_back),
        "overshoot": [(r["id"], r["symbol"], round(float(r["r"]), 2))
                      for r in overshoot],
    }


def diagnosis(s) -> str:
    """One sentence: which of the three numbers is losing the money."""
    if not s["n"]:
        return "No measured closed trade in this window."
    if s["expectancy"] is not None and s["expectancy"] > 0:
        return (f"Paid: {s['expectancy']:+.2f}R a trade.")
    if s["avg_win"] is None:
        return "No winner in this window: the entries, not the exits."
    if s["avg_loss"] is None:
        return "No loser in this window."
    if (s["needed_avg_win"] is not None
            and s["avg_win"] < s["needed_avg_win"]
            and (s["win_rate"] or 0) >= 0.5):
        cut = ""
        if s["by_hand_wins"]:
            cut = (f" {s['by_hand_wins']} of {s['wins']} winners were closed "
                   f"by hand at {s['by_hand_win_avg']:+.2f}R on average.")
        return (f"The win rate is not the problem ({s['win_rate'] * 100:.0f}%): "
                f"winners average {s['avg_win']:+.2f}R where this win rate "
                f"needs {s['needed_avg_win']:+.2f}R.{cut}")
    if s["overshoot"]:
        return (f"{len(s['overshoot'])} loss(es) went past -{OVERSHOOT_R}R: "
                f"stops that did not hold.")
    return (f"The win rate is: {s['win_rate'] * 100:.0f}% against the "
            f"{s['breakeven_win_rate'] * 100:.0f}% this payoff needs.")


def group(rows_, key) -> dict:
    """{key value: rows}, in first-seen order."""
    out = {}
    for r in rows_:
        out.setdefault(key(r), []).append(r)
    return out
