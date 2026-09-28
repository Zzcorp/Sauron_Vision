"""IS IT A GOOD IDEA TO CLOSE? — Sauron's answer about the positions an
operator ticked.

The gap this closes
-------------------
The positions page could close one row, or the whole book, and it could not
say whether either was a good idea. The platform already measures every open
position for exactly that question — `brain/position_review.py` computes the
facts and fires plain-English triggers on a beat — but nothing on a page ever
read it, so the operator (or Gandalf, logged in as the operator) stood over a
CLOSE button with twelve columns of numbers and no opinion.

This module answers, for the rows somebody ticked, one position at a time and
for the selection as a whole:

    close            closing looks right
    trim_or_tighten  watch it — tighten the stop or take some off
    hold             the reason it was opened still stands
    unknown          no fresh price, so it cannot be judged

with the reasons in plain English, most important first, and the numbers
behind them.

Three rules that outrank everything else here
---------------------------------------------
1. It never closes anything. Not a single call in this module can, and a
   source test pins that. The answer is advice; the human closes through the
   PIN-confirmed "Close selected" flow in dashboard/views_close.py, which runs
   the same engine close every other button runs.
2. No verdict on a stale price. `position_review.measure` refuses to compute
   R without a usable mark, and so does this: "unknown" is the answer, and
   it says why. A verdict computed from yesterday's price looks exactly like
   one computed from today's.
3. Never call a demo row "live". eToro's demo and Saxo's simulation are
   `paper=False` rows at a broker — simulated money that still needs the PIN
   to close. The world word comes from `position_summary.venue_of`, the
   reader the father's page uses, never from `trade.paper` alone.

What this adds to the watcher's facts
-------------------------------------
`measure()` answers "how is the position doing"; closing it has four more
questions the watcher never needed:

  * WHICH STOP IS REAL. eToro clamps a stop on fill rather than refuse it —
    measured on the real account, 5% sent and 9.98% held. The row keeps the
    SENT stop (the R denominator must not move) and records the divergence
    in metadata["stop_rewritten_by_venue"]. A protected row's exit is the
    broker's, so the distance that matters is to the HELD stop, and "R to
    stop" is recomputed against it; a held value at or under 0.0001 is
    eToro's "no stop" sentinel and means nothing rests at the broker at all.
  * IS IT AN ORDER. A working entry has not filled: no position, no P&L, no
    R. Its question is withdraw or keep, and it is answered as one.
  * CAN A CLOSE HAPPEN NOW. A shut market means a close would wait for the
    open (a paper close is refused outright until then). A CLOSE_PENDING row
    is already being retried.
  * WHAT THE PLATFORM THINKS TODAY. Fresh active signals on the symbol in
    the last 24 hours, split into agreeing and opposing the position's side;
    the time stop's own clock; the watcher's latest model verdict if it has
    one from the last day.

The model half
--------------
`use_model=True` makes ONE synchronous call for the whole selection — never
one per row — on the balanced tier, through the house pattern (the provider
writes the AgentTask ledger, `can_spend` gates it). A missing key, a refused
budget, an error or an answer that is not the JSON asked for all return the
deterministic answer with a sentence saying why the AI part is missing. A
model verdict outside the four words is clamped back to the rule-based one:
a garbled answer must never read as "close". Nothing else is written — no
Notification, no PositionReview row, no hypothesis: asking a question is
not an event.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import timedelta
from typing import Optional

from django.utils import timezone

from ai_agents.base_agent import BaseAgent

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════
# The four answers
# ══════════════════════════════════════════════════════════════════════════

VERDICT_CLOSE = "close"
VERDICT_TRIM = "trim_or_tighten"
VERDICT_HOLD = "hold"
VERDICT_UNKNOWN = "unknown"
VERDICTS = (VERDICT_CLOSE, VERDICT_TRIM, VERDICT_HOLD, VERDICT_UNKNOWN)

VERDICT_WORDS = {
    VERDICT_CLOSE: "Closing looks right",
    VERDICT_TRIM: "Watch it — tighten the stop or take some off",
    VERDICT_HOLD: "Hold — the reason it was opened still stands",
    VERDICT_UNKNOWN: "Can't judge — no fresh price",
}

# A CLOSE_PENDING row is already being closed: the broker refused the close
# and the retry task sends it again every five minutes. Its facts are still
# measured and its verdict still computed — if the retries are abandoned,
# the operator closing it at the broker wants to know what the facts said —
# but the verdict cannot wear its ordinary words. "Hold — the reason it was
# opened still stands" over a row the platform is closing reads as "this
# stays open", which it does not, and the top reason on the same card says
# the opposite. So the chip leads with what is HAPPENING and gives the
# facts' reading second, and the selection's line counts these rows apart.
PENDING_WORDS = {
    VERDICT_CLOSE: "Already being closed — and its facts say closing is "
                   "right",
    VERDICT_TRIM: "Already being closed — on its facts alone Sauron would "
                  "say watch it",
    VERDICT_HOLD: "Already being closed — on its facts alone Sauron would "
                  "not have closed it",
    VERDICT_UNKNOWN: "Already being closed — no fresh price to judge it by",
}

# A working entry is an ORDER, so the same two answers wear their own words:
# "close" is "withdraw it", "hold" is "leave it working". Trim and tighten
# mean nothing for an order that holds no position, and an order needs no
# price to judge, so neither of the other two is ever given to one.
ORDER_WORDS = {
    VERDICT_CLOSE: "Withdrawing the order looks right",
    VERDICT_HOLD: "Keep the order working",
}

KIND_POSITION = "position"
KIND_ORDER = "order"

WORLD_LIVE = "live"
WORLD_DEMO = "demo"
WORLD_PAPER = "paper"

DASH = "—"

# The endpoint caps a request at this many ids; the domain caps it too, so a
# direct caller cannot turn one question into a measurement of the platform.
MAX_POSITIONS = 50

# Reasons per position. Six is what fits on a phone card without scrolling
# past the verdict, and past six the seventh is never the one that matters.
MAX_REASONS = 6

# "Fresh" signals. The same window the engine's own vote reads by default
# (`max_signal_age_hours`, 24): a signal the bot would no longer act on is
# not a reason to close a position either.
SIGNAL_WINDOW_HOURS = 24

# The watcher's model verdict counts as current for a day, the same TTL the
# position card would read it with (`position_review.CARD_TTL_HOURS`).
REVIEW_TTL_HOURS = 24

# eToro's "no stop" sentinel: a held stop at or under this is NO stop, never
# a distance (asset_engine/base.py stop_moved_words; Morgul G2 reads it too).
NO_STOP_SENTINEL = 0.0001

# A venue-held stop farther than this many R from entry is flagged: the
# position is carrying at least half as much risk again as it was sized for.
VENUE_STOP_WIDER_R = 1.5

# What one question is estimated to cost, handed to can_spend. It is worked
# out from what is actually about to be sent, not a flat figure: one call
# covers the whole selection, and a selection runs from one row to fifty.
# A flat $0.08 was right for a handful and several times short at the cap —
# fifty rows of pretty-printed facts is ~60k tokens in before the model says
# a word — so the budget guard waved the last call of the day through and
# the day overshot by the difference.
#
#   in   the system prompt and the snapshot, counted in characters and
#        divided by CHARS_PER_TOKEN — three, not the usual four, because
#        indented JSON of numbers and keys tokenises denser than prose;
#   out  a base for the frame, the overall line and adaptive thinking, plus
#        a few sentences of reasoning per position;
#   then priced at the agent's own model's rates and multiplied by the
#        margin, with a floor, so the guard trips before the budget does.
CHARS_PER_TOKEN = 3.0
OUTPUT_TOKENS_BASE = 2000
OUTPUT_TOKENS_PER_POSITION = 400
ESTIMATE_MARGIN = 1.5
MIN_ESTIMATED_USD = 0.02


# ══════════════════════════════════════════════════════════════════════════
# The rules — written down, because an operator will ask "why close?"
# ══════════════════════════════════════════════════════════════════════════
#
# The watcher's trigger codes (brain/position_review.evaluate_triggers) fall
# into two families, and the verdict turns on which family fired.
#
# THESIS codes say the REASON the trade was opened is failing:
#   adverse_excursion  it has spent most of its risk and never paid
#   horizon_exceeded   the setup's own clock ran out with nothing to show
#   regime_flip        the market regime it was opened in is gone
#   rule_decayed       the rule that opened it has since been judged
# plus one of this module's own: fresh signals on the symbol point the OTHER
# way, more strongly than any that agree.
#
# WATCH codes say the trade may be right but its RISK has changed shape:
#   give_back, risk_exceeds_reward, near_stop (not yet through), near_target,
#   vol_expansion, event_imminent, concentration, self_hedge
# plus the time stop approaching, and a broker that holds no stop or a wider
# one than was sent.
#
#   UNKNOWN  no usable price (or an options row, which has no premium feed).
#            Nothing below is evaluated — every rule is arithmetic on a mark.
#   CLOSE    any one of:
#            C1 the mark is beyond the stop the trade planned to exit at and
#               it is still open (the bracket did not fire, or the broker
#               holds a wider stop than was sent) — the loss is already past
#               the risk the position was sized for;
#            C2 the time stop's ceiling is reached — the platform's own rule
#               says this position has had its time;
#            C3 a thesis reason fired AND the position is not paying (R at or
#               under zero, or the P&L when R cannot be measured) — nothing
#               is left to wait for;
#            C4 two or more thesis reasons fired at once, whatever the P&L;
#            C5 give_back fired and the handed-back winner is now a loser.
#   TRIM     not CLOSE, and any one of:
#            T1 a WATCH code fired (an event_imminent that is only the blind
#               "no macro calendar" marker does not count: unchecked is not
#               an event);
#            T2 a thesis reason fired while the position is still in profit —
#               protect what it has made rather than hand it back;
#            T3 the time stop is approaching (past its warning fraction);
#            T4 the broker holds no stop at all, or holds one more than
#               VENUE_STOP_WIDER_R from entry;
#            T5 the ROW carries no stop. Nothing limits the loss, and
#               without a stop there is no R, so near_stop, give_back,
#               adverse_excursion and risk_exceeds_reward can never fire:
#               without this rule such a row could only ever come back
#               "hold", however much it was losing.
#   HOLD     nothing above: the stop (and the target, when one is set) are
#            doing their job. The sentence that says so names only the
#            levels the row actually has — a target can be cleared from
#            the positions page, and "the target is doing its job" about a
#            target that does not exist is a sentence the operator would
#            rightly stop trusting.
#
# A CLOSE_PENDING row is judged by the same rules — its facts are real —
# but it wears PENDING_WORDS and is counted apart in the selection's line:
# the platform is already closing it, and "hold" must never read as "this
# stays open".
#
# For an ORDER (a working entry) only two answers exist. WITHDRAW (close)
# when fresh signals oppose its side more strongly than any agree, or the
# rule behind it has been judged since; otherwise KEEP (hold).
#
# The watcher's own latest model verdict, when it has one, is REPORTED as a
# reason and never moves the rule-based answer: it was computed on older
# facts, and this answer has to be explainable from the facts on screen.

THESIS_CODES = ("adverse_excursion", "horizon_exceeded", "regime_flip",
                "rule_decayed")
WATCH_CODES = ("give_back", "risk_exceeds_reward", "near_stop", "near_target",
               "vol_expansion", "event_imminent", "concentration", "self_hedge")


def _f(value) -> Optional[float]:
    """float or None — never raises, never invents a 0."""
    if value is None or value == "":
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out == out else None      # NaN is not a number here


def _r_text(value) -> str:
    v = _f(value)
    return DASH if v is None else "{:+.2f}R".format(v)


def _dist_text(value) -> str:
    """An R DISTANCE (to a stop, to a target): unsigned while on the right
    side, and said as "past" when the mark is already beyond the level."""
    v = _f(value)
    if v is None:
        return DASH
    if v < 0:
        return "past it by {:.2f}R".format(abs(v))
    return "{:.2f}R".format(v)


# ══════════════════════════════════════════════════════════════════════════
# The facts position_review does not have
# ══════════════════════════════════════════════════════════════════════════

def world_of(trade) -> tuple:
    """(world, words, requires_pin) from the ROW's own stamps.

    `position_summary.venue_of` is the one reader that tells an eToro demo
    row from a real one: `trade.paper` is False for both, which is why the
    watcher's own "venue" fact calls every demo row "live". This never uses
    that fact.
    """
    from bot_program.manual_close import requires_pin
    from dashboard.position_summary import venue_of

    money_words, real, broker_words = venue_of(trade)
    if broker_words == "Paper trading":
        world, words = WORLD_PAPER, "Paper trading"
    elif real:
        world = WORLD_LIVE
        words = "Real money · " + broker_words
    else:
        world, words = WORLD_DEMO, broker_words
    return world, words, bool(requires_pin(trade))


def venue_stop(trade) -> dict:
    """The stop the VENUE holds, from the fill's own echo.

    Returns {"stamped", "sent", "held", "none", "applies"}. `applies` is
    True only when the held stop is the one in force: a real price, and the
    row's stop is still the one that was sent. Once break-even or a trail
    has moved the row's stop, the fill's echo describes a stop that no
    longer exists and quoting it would be quoting history.
    """
    out = {"stamped": False, "sent": None, "held": None, "none": False,
           "applies": False}
    moved = (trade.metadata or {}).get("stop_rewritten_by_venue")
    if not isinstance(moved, dict):
        return out
    sent, held = _f(moved.get("sent")), _f(moved.get("held"))
    if sent is None or held is None:
        return out
    out.update(stamped=True, sent=sent, held=held)
    if held <= NO_STOP_SENTINEL:
        out["none"] = True
        return out
    current = _f(trade.stop_loss)
    if current is not None and abs(current - sent) <= max(1e-9,
                                                          abs(sent) * 1e-7):
        out["applies"] = True
    return out


def fresh_signals(symbol: str, side: str, *, now=None) -> dict:
    """Active signals on the symbol from the last SIGNAL_WINDOW_HOURS,
    split by whether they point the position's way.

    Neutral signals are neither: a signal with no direction says nothing
    about whether to be long or short. "Dominates" means the strongest
    opposing score beats the strongest agreeing one — a count would let
    three weak signals outvote one strong one.
    """
    from dashboard.position_summary import rule_words
    from signals.models import Signal

    now = now or timezone.now()
    want = "bearish" if str(side).upper() in ("SELL", "SHORT") else "bullish"
    against = "bullish" if want == "bearish" else "bearish"
    rows = list(Signal.objects
                .filter(instrument__symbol__iexact=symbol, is_active=True,
                        created_at__gte=now - timedelta(
                            hours=SIGNAL_WINDOW_HOURS))
                .order_by("-score")
                .values("id", "direction", "score", "rule_name", "title"))
    agree = [r for r in rows if r["direction"] == want]
    oppose = [r for r in rows if r["direction"] == against]

    def strongest(group):
        if not group:
            return None
        top = group[0]
        return {"id": top["id"], "score": _f(top["score"]),
                "rule": rule_words(top["rule_name"]) or top["title"][:60]}

    best_for, best_against = strongest(agree), strongest(oppose)
    dominates = bool(best_against) and (
        best_for is None
        or (best_against["score"] or 0.0) > (best_for["score"] or 0.0))
    return {"agree": len(agree), "oppose": len(oppose),
            "strongest_agree": best_for, "strongest_oppose": best_against,
            "opposing_dominates": dominates}


def market_now(trade, instrument) -> dict:
    """Is the market open, and if not, when does it reopen."""
    try:
        from core.exchange_status import market_clock
        clock = market_clock(
            getattr(instrument, "asset_class", "") or trade.asset_class or "",
            getattr(instrument, "exchange", "") or "",
            symbol=trade.symbol or "")
    except Exception:  # noqa: BLE001 — no answer is no note
        logger.debug("[close-advice] market clock unavailable", exc_info=True)
        return {"known": False, "is_open": True, "reopens_words": ""}
    return {"known": bool(clock.get("modelled")),
            "is_open": bool(clock.get("is_open", True)),
            "reopens_words": clock.get("reopens_words") or ""}


# ══════════════════════════════════════════════════════════════════════════
# One position
# ══════════════════════════════════════════════════════════════════════════

class _Reasons:
    """Reasons with a priority, read back most important first.

    The watcher's trigger severities are 0..1; this module's own facts are
    placed on the same scale so one ordering serves both.
    """

    def __init__(self):
        self._rows = []

    def add(self, priority: float, text: str):
        text = (text or "").strip()
        if text and text not in (t for _, _, t in self._rows):
            self._rows.append((float(priority), len(self._rows), text))

    def top(self, n: int = MAX_REASONS) -> list:
        return [t for _, _, t in sorted(self._rows,
                                        key=lambda r: (-r[0], r[1]))[:n]]


def _pending_words(trade) -> str:
    tries = int(_f((trade.metadata or {}).get("close_retry_attempts")) or 0)
    return ("A close is already being retried: the broker refused it"
            + (" %d time%s" % (tries, "" if tries == 1 else "s") if tries
               else "")
            + ", so the position is still open there and Sauron tries again "
              "every 5 minutes.")


def _signal_words(sig: dict) -> list:
    """(priority, sentence) pairs about the fresh signals, or []."""
    out = []
    if sig["oppose"]:
        o = sig["strongest_oppose"]
        text = ("%d fresh signal%s in the last %dh point%s the other way "
                "(strongest: %s, score %.2f)" % (
                    sig["oppose"], "" if sig["oppose"] == 1 else "s",
                    SIGNAL_WINDOW_HOURS, "s" if sig["oppose"] == 1 else "",
                    o["rule"], o["score"] or 0.0))
        if sig["agree"]:
            a = sig["strongest_agree"]
            text += (", against %d agreeing (strongest %.2f)"
                     % (sig["agree"], a["score"] or 0.0))
        text += "."
        out.append((0.7 if sig["opposing_dominates"] else 0.35, text))
    elif sig["agree"]:
        a = sig["strongest_agree"]
        out.append((0.2, "%d fresh signal%s in the last %dh still agree%s "
                          "with it (strongest: %s, score %.2f)." % (
                              sig["agree"], "" if sig["agree"] == 1 else "s",
                              SIGNAL_WINDOW_HOURS,
                              "s" if sig["agree"] == 1 else "",
                              a["rule"], a["score"] or 0.0)))
    return out


def _review_words(review: Optional[dict], now) -> str:
    """The watcher's latest model verdict, as one sentence, or ""."""
    if not review:
        return ""
    verdict = review.get("verdict") or ""
    names = {"hold": "hold", "tighten": "tighten the stop",
             "take_part": "take part off", "exit": "exit"}
    if verdict not in names:
        return ""
    ago = ""
    at = review.get("as_of_iso")
    if at:
        try:
            from datetime import datetime
            from dashboard.position_summary import duration_words
            when = datetime.fromisoformat(at)
            ago = " " + duration_words((now - when).total_seconds()) + " ago"
        except (TypeError, ValueError):
            ago = ""
    conf = review.get("confidence")
    text = "Sauron's position watcher said \"%s\"%s" % (names[verdict], ago)
    if conf is not None:
        text += " (confidence %.2f)" % float(conf)
    reasoning = str(review.get("reasoning_md") or "").strip()
    if reasoning:
        first = reasoning.split("\n")[0].strip()
        text += ": " + (first[:200] + ("…" if len(first) > 200 else ""))
    return text if text.endswith((".", "…")) else text + "."


def _level(value) -> Optional[float]:
    """A stop or target price, or None when the row has none. Zero is how
    an older row spells "none" — never a level at price zero."""
    v = _f(value)
    return v if v is not None and v > 0 else None


def _hold_words(has_stop: bool, has_target: bool) -> str:
    """Why "hold", in terms of the levels this row actually carries."""
    head = "Nothing the watcher measures has fired"
    if has_stop and has_target:
        return head + ": the stop and the target are doing their job."
    if has_stop:
        return head + ": the stop is doing its job; no target is set."
    if has_target:
        return head + "; a target is set, but no stop is."
    return head + "; neither a stop nor a target is set."


def _decide_position(*, triggers, facts, r_to_planned_stop, time_stop, vstop,
                     venue_risk_r, sig, pnl, has_stop=True) -> str:
    """The rules at the top of this file, in code. See them for the why."""
    codes = {}
    for t in triggers:
        codes.setdefault(t["code"], t)
    ur = _f(facts.get("unrealized_r"))
    if ur is not None:
        paying = ur > 0
    else:
        paying = pnl is not None and pnl > 0

    through = r_to_planned_stop is not None and r_to_planned_stop < 0
    near_stop = codes.get("near_stop")
    if near_stop and (near_stop.get("values") or {}).get("through_stop"):
        through = True
    thesis = sum(1 for c in THESIS_CODES if c in codes)
    if sig["opposing_dominates"]:
        thesis += 1

    # CLOSE
    if through:                                             # C1
        return VERDICT_CLOSE
    if time_stop.get("hit"):                                # C2
        return VERDICT_CLOSE
    if thesis >= 1 and not paying:                          # C3
        return VERDICT_CLOSE
    if thesis >= 2:                                         # C4
        return VERDICT_CLOSE
    if "give_back" in codes and ur is not None and ur <= 0:  # C5
        return VERDICT_CLOSE

    # TRIM
    for code in WATCH_CODES:                                # T1
        hit = codes.get(code)
        if not hit:
            continue
        if code == "event_imminent":
            events = (hit.get("values") or {}).get("events") or []
            if events and all(e.get("blind") for e in events):
                continue
        return VERDICT_TRIM
    if thesis >= 1:                                         # T2 (paying)
        return VERDICT_TRIM
    if time_stop.get("approaching"):                        # T3
        return VERDICT_TRIM
    if vstop["none"] or (venue_risk_r is not None
                         and venue_risk_r >= VENUE_STOP_WIDER_R):  # T4
        return VERDICT_TRIM
    if not has_stop:                                        # T5
        return VERDICT_TRIM
    return VERDICT_HOLD


def _decide_order(*, sig, rule_state) -> str:
    judged = (rule_state.get("control_status") in ("paused", "reduced")
              or rule_state.get("advisory") == "pause_recommended"
              or rule_state.get("open_decay_alert"))
    if sig["opposing_dominates"] or judged:
        return VERDICT_CLOSE
    return VERDICT_HOLD


def _committed(trade, qty, entry):
    """(committed, kind) — what closing this position frees, in the
    config's currency, through the SAME function the positions card prints
    its capital with. None when it cannot be measured."""
    from dashboard.views import _pos_committed
    from portfolio.services import value_per_unit
    if not qty or not entry:
        return None, ""
    notional = abs(qty) * entry * value_per_unit(trade)
    try:
        committed, levered = _pos_committed(trade.asset_class or "", notional,
                                            trade.metadata or {})
    except Exception:  # noqa: BLE001 — a missing figure is a dash
        return None, ""
    return _f(committed), ("margin" if levered else "cost")


def _advise_one(trade, *, cache: dict, reviews: dict, now) -> dict:
    """Everything the card shows about one ticked row."""
    from bot_program.asset_engine.base import (is_entry_working,
                                               time_stop_status)
    from core.price_format import format_price
    from dashboard.position_summary import (_unconverted_ccy, duration_words,
                                            money)
    from instruments.models import Instrument
    from portfolio.services import is_option_row, value_per_unit

    from .position_review import (_rule_state, bot_position,
                                  evaluate_triggers, measure)

    sym = trade.symbol or ""
    ac = trade.asset_class or ""
    is_long = (trade.side or "").upper() in ("BUY", "LONG")
    world, world_words, needs_pin = world_of(trade)
    ccy = (getattr(trade.config, "base_currency", "") or "USD").strip()
    mark_ccy = _unconverted_ccy(trade, ccy) or ccy
    instrument = Instrument.objects.filter(symbol=sym).first()
    pos = bot_position(trade)
    order = is_entry_working(trade)
    pending = trade.status == "CLOSE_PENDING"
    reasons = _Reasons()

    base = {
        "trade_id": trade.id,
        "symbol": sym,
        "side": pos["side"],
        "headline": "%s %s" % ("Long" if is_long else "Short", sym),
        "status": trade.status,
        # Already being closed: its verdict wears PENDING_WORDS, and the
        # selection counts it apart (see PENDING_WORDS for why).
        "pending": pending,
        "kind": KIND_ORDER if order else KIND_POSITION,
        "world": world,
        "world_words": world_words,
        "requires_pin": needs_pin,
        "rule": trade.rule_name or "",
    }

    if trade.status == "CLOSE_PENDING":
        reasons.add(1.2, _pending_words(trade))

    market = market_now(trade, instrument)
    if not market["is_open"]:
        reasons.add(0.8, "The market for %s is shut: a close now would wait "
                         "for the open%s%s." % (
                             sym,
                             (" (" + market["reopens_words"] + ")")
                             if market["reopens_words"] else "",
                             "; a paper close is refused until then"
                             if world == WORLD_PAPER else ""))

    sig = fresh_signals(sym, pos["side"], now=now)
    review = reviews.get("bot:%d" % trade.id)
    review_text = _review_words(review, now)
    age_seconds = ((now - trade.opened_at).total_seconds()
                   if trade.opened_at else None)

    # ── An ORDER: withdraw or keep, never R ─────────────────────────────
    if order:
        rule_state = _rule_state(pos)
        verdict = _decide_order(sig=sig, rule_state=rule_state)
        reasons.add(1.1, "This is an ORDER waiting at the broker, not a "
                         "position: nothing has filled, so there is no "
                         "profit, loss or R to judge.")
        for pr, text in _signal_words(sig):
            reasons.add(pr + 0.1 if sig["opposing_dominates"] else pr, text)
        judged = []
        if rule_state.get("control_status") in ("paused", "reduced"):
            judged.append("its rule control says %s"
                          % rule_state["control_status"])
        if rule_state.get("advisory") == "pause_recommended":
            judged.append("the brain recommends pausing it")
        if rule_state.get("open_decay_alert"):
            judged.append("a track-record decay alert is open on it")
        if judged:
            reasons.add(0.75, "The rule behind the order has been judged "
                              "since it was placed: %s." % "; ".join(judged))
        if review_text:
            reasons.add(0.3, review_text)
        if verdict == VERDICT_HOLD and not judged and not sig["oppose"]:
            reasons.add(0.1, "Nothing speaks against the order: no fresh "
                             "signal points the other way and its rule "
                             "stands.")
        return {**base,
                "verdict": verdict,
                "verdict_words": ORDER_WORDS[verdict],
                "reasons": reasons.top(),
                "severity": 0.0,
                "triggers": [],
                "numbers": {
                    "mark": None, "mark_text": DASH, "mark_source": "",
                    "entry": _f(trade.entry_price),
                    "entry_text": format_price(trade.entry_price, ac, sym),
                    "pnl": None, "pnl_text": DASH, "ccy": mark_ccy,
                    "r_now": None, "r_now_text": DASH,
                    "r_to_stop": None, "r_to_stop_text": DASH,
                    "r_to_planned_stop": None,
                    "r_to_target": None, "r_to_target_text": DASH,
                    "age_hours": (round(age_seconds / 3600.0, 2)
                                  if age_seconds is not None else None),
                    "age_text": duration_words(age_seconds),
                    "committed": None, "committed_text": DASH,
                    "committed_kind": "",
                },
                "facts": {"signals": sig, "market": market,
                          "venue_stop": venue_stop(trade),
                          "time_stop": None, "review": review,
                          "rule_state": rule_state}}

    # ── A POSITION ──────────────────────────────────────────────────────
    facts = measure(pos, cache)
    mark = _f(facts.get("mark"))
    option = is_option_row(trade)
    time_stop = time_stop_status(trade, now=now)
    vstop = venue_stop(trade)
    entry = _f(trade.entry_price)
    qty = _f(trade.qty)
    risk = _f(facts.get("risk_per_unit"))
    sign = pos["dir_sign"]
    has_stop = _level(pos.get("stop")) is not None
    has_target = _level(pos.get("target")) is not None

    # The P&L off the SAME mark the R was measured on, with the positions
    # page's own value-per-unit — so the money and the R on the card are two
    # readings of one price, not two prices. None without a mark, and for an
    # options row, whose only quote is the underlying's.
    pnl = None
    if mark is not None and entry and qty and not option:
        pnl = round((mark - entry) * qty * value_per_unit(trade) * sign, 2)

    committed, committed_kind = _committed(trade, qty, entry)

    # Which stop is real — recompute the distance against the HELD stop
    # when the venue holds a different one, and judge the triggers on that.
    judged_facts = dict(facts)
    r_to_planned = _f(facts.get("r_to_stop"))
    if not has_stop:
        # The watcher measures any stop that is not None, and 0 is how an
        # older row spells "none" — so it would compute a distance to a stop
        # at price ZERO: "50R still at risk to the stop" on a long, and on a
        # short a mark "through" it, which reads as C1 and says close. A
        # row with no stop has no distance to one; T5 says so instead.
        r_to_planned = None
        judged_facts["r_to_stop"] = None
        judged_facts["stop"] = None
    r_to_held = None
    venue_risk_r = None
    initial = _f(pos.get("initial_stop"))
    one_r = (abs(entry - initial) if entry is not None
             and initial is not None and abs(entry - initial) > 0 else None)
    if vstop["applies"]:
        if one_r:
            venue_risk_r = round(abs(entry - vstop["held"]) / one_r, 2)
        if mark is not None and risk:
            r_to_held = round(sign * (mark - vstop["held"]) / risk, 4)
            judged_facts["r_to_stop"] = r_to_held

    no_price = mark is None or option
    triggers = [] if no_price else evaluate_triggers(judged_facts)

    if option:
        reasons.add(1.05, "No option-price feed exists, so what this "
                          "contract is worth now cannot be measured — "
                          "Sauron can't judge it.")
    elif mark is None:
        reasons.add(1.05, "No fresh price for %s — %s — so Sauron can't "
                          "judge it." % (sym, facts.get("mark_source")
                                         or "no quote"))

    for t in triggers:
        reasons.add(float(t.get("severity") or 0.0), t.get("text") or "")

    if not no_price and vstop["applies"] and r_to_planned is not None \
            and r_to_planned < 0 and (r_to_held is None or r_to_held >= 0):
        reasons.add(1.0, "The mark is past the stop Sauron sent (%s), but "
                         "the broker holds its stop at %s, so the position "
                         "stays open — the loss is already beyond the risk "
                         "it was sized for." % (
                             format_price(vstop["sent"], ac, sym),
                             format_price(vstop["held"], ac, sym)))
    if vstop["none"]:
        reasons.add(0.9, "The broker holds NO stop on this position: the "
                         "stop Sauron sent (%s) was not kept, so nothing "
                         "rests at the broker if Sauron goes offline."
                         % format_price(vstop["sent"], ac, sym))
    elif vstop["applies"]:
        text = ("The broker holds the stop at %s, not the %s Sauron sent"
                % (format_price(vstop["held"], ac, sym),
                   format_price(vstop["sent"], ac, sym)))
        if venue_risk_r is not None:
            text += " — that stop risks %.2fR, not 1R" % venue_risk_r
        text += "."
        reasons.add(0.65 if (venue_risk_r or 0) >= VENUE_STOP_WIDER_R
                    else 0.4, text)
    elif vstop["stamped"]:
        reasons.add(0.3, "The broker rewrote the stop at the fill (sent %s, "
                         "held %s), and the stop has been moved since, so "
                         "what the broker holds now is not recorded." % (
                             format_price(vstop["sent"], ac, sym),
                             format_price(vstop["held"], ac, sym)))

    if not has_stop:
        # T5's sentence. Said whatever the price: an unpriced row with no
        # stop is still a row with nothing limiting it.
        text = "No stop is set: nothing limits the loss"
        if not no_price and _f(facts.get("unrealized_r")) is None:
            text += (", and with no stop to measure against there is no R, "
                     "so the warnings that read R (near the stop, adverse "
                     "excursion, give-back, risk against reward) cannot fire")
        reasons.add(0.85, text + ".")

    if time_stop.get("hit"):
        reasons.add(0.95, "Its time limit is reached: held %s of the %s it "
                          "was allowed." % (
                              duration_words(time_stop["hours_held"] * 3600),
                              duration_words(time_stop["max_hold_hours"]
                                             * 3600)))
    elif time_stop.get("approaching"):
        reasons.add(0.55, "It has used %d%% of its time limit — %s left "
                          "before the time stop closes it." % (
                              int(round((time_stop.get("fraction") or 0)
                                        * 100)),
                              duration_words((time_stop.get("hours_left")
                                              or 0) * 3600)))

    for pr, text in _signal_words(sig):
        reasons.add(pr, text)
    if review_text:
        reasons.add(0.45, review_text)

    if no_price:
        verdict = VERDICT_UNKNOWN
    else:
        verdict = _decide_position(
            triggers=triggers, facts=facts, r_to_planned_stop=r_to_planned,
            time_stop=time_stop, vstop=vstop, venue_risk_r=venue_risk_r,
            sig=sig, pnl=pnl, has_stop=has_stop)
    if verdict == VERDICT_HOLD and not triggers:
        reasons.add(0.15, _hold_words(has_stop, has_target))

    severity = max((float(t.get("severity") or 0) for t in triggers),
                   default=0.0)
    r_to_stop = r_to_held if r_to_held is not None else r_to_planned
    return {**base,
            "verdict": verdict,
            "verdict_words": (PENDING_WORDS if pending
                              else VERDICT_WORDS)[verdict],
            "reasons": reasons.top(),
            "severity": round(severity, 3),
            "triggers": [{"code": t["code"], "severity": t["severity"],
                          "text": t["text"]} for t in triggers],
            "numbers": {
                "mark": mark,
                "mark_text": format_price(mark, ac, sym) if not option
                else DASH,
                "mark_source": facts.get("mark_source") or "",
                "entry": entry,
                "entry_text": format_price(trade.entry_price, ac, sym),
                "pnl": pnl,
                "pnl_text": money(pnl, mark_ccy, signed=True),
                "ccy": mark_ccy,
                "r_now": None if no_price else _f(facts.get("unrealized_r")),
                "r_now_text": DASH if no_price
                else _r_text(facts.get("unrealized_r")),
                "r_to_stop": None if no_price else r_to_stop,
                "r_to_stop_text": DASH if no_price else _dist_text(r_to_stop),
                # Only when the venue holds a different stop: the distance
                # to the one Sauron SENT, beside the one that is in force.
                "r_to_planned_stop": (r_to_planned if r_to_held is not None
                                      else None),
                "r_to_target": None if no_price
                else _f(facts.get("r_to_target")),
                "r_to_target_text": DASH if no_price
                else _dist_text(facts.get("r_to_target")),
                "age_hours": facts.get("age_hours"),
                "age_text": duration_words(age_seconds),
                "committed": committed,
                # Same currency as the P&L: both are value-per-unit figures,
                # so an older forex row's are in its quote currency.
                "committed_text": money(committed, mark_ccy),
                "committed_kind": committed_kind,
            },
            "facts": {
                "signals": sig, "market": market, "venue_stop": vstop,
                "venue_risk_r": venue_risk_r,
                "time_stop": {k: time_stop.get(k) for k in (
                    "applies", "enabled", "max_hold_hours", "hours_held",
                    "hours_left", "fraction", "approaching", "hit")},
                "review": review,
                "regime_at_entry": facts.get("regime_at_entry"),
                "regime_now": facts.get("regime_now"),
                "vol_ratio": facts.get("vol_ratio"),
                "horizon_days": facts.get("horizon_days"),
                "mae_r": facts.get("mae_r"), "mfe_r": facts.get("mfe_r"),
                "rule_state": facts.get("rule_state"),
                "stale_quote": bool(no_price),
            }}


def _unmeasured(trade, err) -> dict:
    """The card for a row whose measurement raised — one bad row must not
    take the whole answer down, and it must not read as a clean bill."""
    world, world_words, needs_pin = world_of(trade)
    pending = trade.status == "CLOSE_PENDING"
    return {
        "trade_id": trade.id, "symbol": trade.symbol or "",
        "side": "SELL" if (trade.side or "").upper() in ("SELL", "SHORT")
        else "BUY",
        "headline": trade.symbol or "", "status": trade.status,
        "pending": pending,
        "kind": KIND_POSITION, "world": world, "world_words": world_words,
        "requires_pin": needs_pin, "rule": trade.rule_name or "",
        "verdict": VERDICT_UNKNOWN,
        "verdict_words": ("Already being closed — it could not be measured"
                          if pending
                          else "Can't judge — it could not be measured"),
        "reasons": ["Sauron could not measure this position (%s), so it "
                    "can't judge it." % str(err)[:120]],
        "severity": 0.0, "triggers": [],
        "numbers": {"mark": None, "mark_text": DASH, "pnl": None,
                    "pnl_text": DASH, "ccy": "", "r_now": None,
                    "r_now_text": DASH, "r_to_stop": None,
                    "r_to_stop_text": DASH, "r_to_planned_stop": None,
                    "r_to_target": None, "r_to_target_text": DASH,
                    "age_hours": None, "age_text": DASH, "committed": None,
                    "committed_text": DASH, "committed_kind": "",
                    "entry": _f(trade.entry_price), "entry_text": DASH,
                    "mark_source": ""},
        "facts": {},
    }


# ══════════════════════════════════════════════════════════════════════════
# The selection
# ══════════════════════════════════════════════════════════════════════════

def _summary(positions: list, not_found: list) -> dict:
    """What closing the whole selection would mean, and one line on it."""
    from dashboard.position_summary import money

    count = len(positions)
    worlds = {WORLD_LIVE: 0, WORLD_DEMO: 0, WORLD_PAPER: 0}
    # The four verdict counts cover the rows NOT already being closed; a
    # CLOSE_PENDING row is counted under `pending` instead. Counted as a
    # "hold", a row the retry task is closing would make "hold 1" and "1
    # already being closed" two readings of one position — so the five
    # counts add up to `count`, each row in exactly one of them.
    by_verdict = {v: 0 for v in VERDICTS}
    pending = 0
    for p in positions:
        worlds[p["world"]] = worlds.get(p["world"], 0) + 1
        if p.get("pending"):
            pending += 1
        else:
            by_verdict[p["verdict"]] = by_verdict.get(p["verdict"], 0) + 1

    # Money is only added up when every figure is measured AND in one
    # currency. One unmeasured row makes the TOTAL unmeasured — summing the
    # rest and printing it as the whole would understate what closing
    # realises — and 12 USD plus 900 JPY is not a number.
    held = [p for p in positions if p["kind"] == KIND_POSITION]
    ccys = sorted({p["numbers"].get("ccy") or "" for p in held} - {""})
    pnl, pnl_note = None, ""
    if held:
        figures = [p["numbers"].get("pnl") for p in held]
        if any(f is None for f in figures):
            pnl_note = ("Not added up: %d of the %d positions have no "
                        "measured profit or loss."
                        % (sum(1 for f in figures if f is None), len(held)))
        elif len(ccys) > 1:
            pnl_note = ("Not added up: the positions are in different "
                        "currencies (%s)." % ", ".join(ccys))
        else:
            pnl = round(sum(figures), 2)
    freed, freed_note = None, ""
    if held:
        caps = [p["numbers"].get("committed") for p in held]
        kinds = {p["numbers"].get("committed_kind") for p in held}
        if any(c is None for c in caps):
            freed_note = "Not measurable for every position."
        elif len(ccys) > 1:
            freed_note = "In different currencies, so not added up."
        else:
            freed = round(sum(caps), 2)
            if "margin" in kinds:
                freed_note = ("Includes modelled margin for levered "
                              "positions, not their full exposure.")
    ccy = ccys[0] if len(ccys) == 1 else ""

    return {
        "count": count,
        "positions": len(held),
        "orders": count - len(held),
        "live": worlds[WORLD_LIVE],
        "demo": worlds[WORLD_DEMO],
        "paper": worlds[WORLD_PAPER],
        "needs_pin": any(p["requires_pin"] for p in positions),
        "close": by_verdict[VERDICT_CLOSE],
        "trim_or_tighten": by_verdict[VERDICT_TRIM],
        "hold": by_verdict[VERDICT_HOLD],
        "unknown": by_verdict[VERDICT_UNKNOWN],
        "pending": pending,
        "pnl": pnl,
        "pnl_text": money(pnl, ccy, signed=True),
        "pnl_note": pnl_note,
        "capital_freed": freed,
        "capital_freed_text": money(freed, ccy),
        "capital_freed_note": freed_note,
        "ccy": ccy,
        "not_found": len(not_found),
        "overall": _overall(positions, by_verdict, worlds),
    }


def _overall(positions, by_verdict, worlds) -> str:
    """One line a person can act on.

    Rows already being closed are said first and kept out of the read of
    the rest: "Nothing here needs closing — hold all 3" over a selection in
    which the platform is retrying one close is a line that says a
    position stays open while it is being closed.
    """
    n = len(positions)
    if not n:
        return "Nothing to judge: none of the ticked rows is open."
    if n == 1:
        # One row: its own verdict words ARE the read, and they already say
        # "withdraw" rather than "close" when the row is an order, and
        # "already being closed" when it is pending.
        line = positions[0]["verdict_words"] + "."
        return line + (" It is real money." if worlds[WORLD_LIVE] else "")

    judged = [p for p in positions if not p.get("pending")]
    pending = n - len(judged)
    m = len(judged)

    def names(verdict):
        syms = [p["symbol"] for p in judged if p["verdict"] == verdict]
        head = ", ".join(syms[:4])
        return head + (" and %d more" % (len(syms) - 4) if len(syms) > 4
                       else "")

    # Each reading is written to stand after "Of the other N:" as well as
    # on its own, where it gets its capital letter.
    closing = by_verdict[VERDICT_CLOSE]
    if not m:
        read = ""
    elif closing == m:
        read = "closing looks right for all %d" % m
    elif by_verdict[VERDICT_HOLD] == m:
        read = "nothing here needs closing — hold all %d" % m
    elif by_verdict[VERDICT_UNKNOWN] == m:
        read = "Sauron can't judge any of them: no fresh price"
    else:
        parts = []
        if closing:
            parts.append("close %d (%s)" % (closing, names(VERDICT_CLOSE)))
        if by_verdict[VERDICT_TRIM]:
            parts.append("watch or tighten %d (%s)" % (
                by_verdict[VERDICT_TRIM], names(VERDICT_TRIM)))
        if by_verdict[VERDICT_HOLD]:
            parts.append("hold %d" % by_verdict[VERDICT_HOLD])
        if by_verdict[VERDICT_UNKNOWN]:
            parts.append("%d can't be judged (no fresh price)"
                         % by_verdict[VERDICT_UNKNOWN])
        read = "; ".join(parts)
        if not pending:
            read = "Sauron's read: " + read

    if not pending:
        line = read[0].upper() + read[1:] + "."
    elif not m:
        line = ("All %d are already being closed: the broker refused each "
                "close and Sauron retries them every 5 minutes." % n)
    elif m == 1:
        # "Of the other 1: closing looks right for all 1" is arithmetic, not
        # English — one remaining row is named and given its own words.
        words = judged[0]["verdict_words"]
        line = ("%d %s already being closed (Sauron retries %s every 5 "
                "minutes). The other one, %s: %s." % (
                    pending, "is" if pending == 1 else "are",
                    "it" if pending == 1 else "them", judged[0]["symbol"],
                    words[0].lower() + words[1:]))
    else:
        line = ("%d %s already being closed (Sauron retries %s every 5 "
                "minutes). Of the other %d: %s." % (
                    pending, "is" if pending == 1 else "are",
                    "it" if pending == 1 else "them", m, read))
    if worlds[WORLD_LIVE]:
        line += " %d of them %s real money." % (
            worlds[WORLD_LIVE], "is" if worlds[WORLD_LIVE] == 1 else "are")
    return line


def _own_overlap_index(user) -> dict:
    """{(SYMBOL, side): [rules]} over THIS user's open trades only.

    The watcher's concentration reading takes its rule overlap from the
    Phase-52 audit, which walks every open trade on the platform — right
    for a platform-level watcher, wrong for an answer served to one
    person: "3 rules hold this same symbol and side" would count, and name,
    rules that only another user's book is running. Seeded into the pass
    cache under the key `position_review._concentration` reads, so the
    measurement is the watcher's own and only its reach is narrowed.
    """
    from bot_program.models import AssetBotTrade

    from .position_review import OPEN_BOT_STATUSES, OVERLAP_MIN_RULES

    groups: dict = {}
    for row in (AssetBotTrade.objects
                .filter(config__user=user, status__in=OPEN_BOT_STATUSES)
                .exclude(rule_name="")
                .values("symbol", "side", "rule_name")):
        key = ((row["symbol"] or "").upper(), row["side"])
        groups.setdefault(key, set()).add(row["rule_name"])
    return {key: sorted(rules) for key, rules in groups.items()
            if len(rules) >= OVERLAP_MIN_RULES}


def _parse_ids(trade_ids) -> tuple:
    """(ids in the order asked, not_found) — duplicates dropped, anything
    that is not a positive whole number reported rather than guessed at."""
    ids, bad = [], []
    for raw in list(trade_ids or [])[:MAX_POSITIONS]:
        if isinstance(raw, bool):
            bad.append(raw)
            continue
        try:
            value = int(raw)
        except (TypeError, ValueError):
            bad.append(raw)
            continue
        if value <= 0 or (isinstance(raw, float) and raw != value):
            bad.append(raw)
            continue
        if value not in ids:
            ids.append(value)
    return ids, bad


def advise(user, trade_ids, *, use_model: bool = False) -> dict:
    """Is closing these positions now a good idea? — see the module docstring.

    Only the user's own AssetBotTrade rows in OPEN or CLOSE_PENDING are
    judged. Anything else asked about — another user's row, a closed one,
    one that never existed — lands in `not_found` with one sentence that
    does not say which of those it was: answering "not yours" would confirm
    the row exists.
    """
    from bot_program.models import AssetBotTrade

    from .position_review import OPEN_BOT_STATUSES, latest_verdicts

    now = timezone.now()
    ids, bad = _parse_ids(trade_ids)
    rows = {t.id: t for t in (
        AssetBotTrade.objects.select_related("config", "config__user")
        .filter(pk__in=ids, config__user=user,
                status__in=OPEN_BOT_STATUSES))} if ids else {}
    not_found = [i for i in ids if i not in rows] + bad

    reviews = {}
    if rows:
        try:
            reviews = latest_verdicts(keys=["bot:%d" % i for i in rows],
                                      user=user, ttl_hours=REVIEW_TTL_HOURS)
        except Exception:  # noqa: BLE001 — a missing review is no reason
            logger.warning("[close-advice] reading reviews failed",
                           exc_info=True)

    # The book-wide reads, once for the whole selection — the overlap index
    # narrowed to this user's own book (see _own_overlap_index).
    cache: dict = {"overlap": _own_overlap_index(user)} if rows else {}
    positions = []
    for trade_id in ids:
        trade = rows.get(trade_id)
        if trade is None:
            continue
        try:
            positions.append(_advise_one(trade, cache=cache, reviews=reviews,
                                         now=now))
        except Exception as e:  # noqa: BLE001 — one row must not blind the rest
            logger.exception("[close-advice] measuring trade %s failed",
                             trade_id)
            positions.append(_unmeasured(trade, e))

    answer = {
        "as_of": now.isoformat(),
        "positions": positions,
        # Ids stay ids; anything else that was sent is echoed as text so
        # the answer is always JSON, whatever the caller put in the list.
        "not_found": [i if isinstance(i, int) and not isinstance(i, bool)
                      else str(i) for i in not_found],
        "not_found_words": ("%d of the ticked rows %s not found, not yours, "
                            "or no longer open, and %s left out." % (
                                len(not_found),
                                "was" if len(not_found) == 1 else "were",
                                "was" if len(not_found) == 1 else "were")
                            if not_found else ""),
        "summary": _summary(positions, not_found),
        "never_closes": ("Advice only: nothing was closed. Closing is your "
                         "decision, and it asks for confirmation (and your "
                         "trading PIN when a position is held at a broker)."),
        "model": {"requested": bool(use_model), "used": False, "note": "",
                  "model": None, "overall": ""},
    }
    if use_model:
        _model_pass(user, answer)
    return answer


# ══════════════════════════════════════════════════════════════════════════
# The model half — one call for the selection
# ══════════════════════════════════════════════════════════════════════════

ADVICE_SCHEMA = """{
  "positions": [
    {"trade_id": integer,
     "verdict": "close | trim_or_tighten | hold | unknown",
     "reasoning": "2-4 plain-English sentences, in the position's own numbers. No preamble.",
     "confidence": 0.0..1.0}
  ],
  "overall": "one or two sentences about the selection as a whole"
}"""


# Module-level, not built inside the agent: the budget estimate has to count
# what will be sent BEFORE an agent is constructed (a refused budget
# constructs nothing and calls nothing), and one text read in two places
# cannot drift apart.
SYSTEM_PROMPT = (
    "You are Sauron Vision's Close Advisor. A person has ticked one "
    "or more OPEN positions and asks: is closing them NOW a good "
    "idea? You receive, for each position, the measured facts, the "
    "triggers that fired, the rule-based verdict and its reasons, "
    "and a summary of the selection.\n\n"
    "Answer per position with one of:\n"
    "  close            — closing now looks right\n"
    "  trim_or_tighten  — keep it, but tighten the stop or take some "
    "off\n"
    "  hold             — the reason it was opened still stands\n"
    "  unknown          — there is no fresh price, so it cannot be "
    "judged\n\n"
    "Rules you must follow:\n"
    "- A position whose rule-based verdict is 'unknown' has no fresh "
    "price. Say so; do not guess its value.\n"
    "- A row of kind 'order' is an unfilled ORDER, not a position: "
    "'close' means withdraw it and 'hold' means keep it working.\n"
    "- A row with pending true (status CLOSE_PENDING) is ALREADY being "
    "closed: the broker refused the close and the platform retries it "
    "every 5 minutes. Your verdict is what its facts say; say that it is "
    "being closed, and never write as if it will stay open.\n"
    "- Reason in R where R is given. A number given as null is "
    "UNKNOWN — never treat it as zero and never invent it.\n"
    "- World 'demo' and 'paper' are simulated money; only 'live' is "
    "real money. Never call a demo position live.\n"
    "- 'hold' is a real answer and often the right one. A trigger "
    "firing is a reason to look, not a reason to act.\n"
    "- You may disagree with the rule-based verdict; when you do, "
    "say which fact decides it.\n"
    "- Plain English for a non-specialist. Short sentences.\n"
    "- You are ADVISING. Nothing you say closes anything; a person "
    "presses the button.\n\n"
    f"Respond ONLY with valid JSON in this schema:\n{ADVICE_SCHEMA}"
    "\n\nNo code fences, no surrounding text."
)


def context_for(snapshot: dict) -> str:
    """The user message for one question — the agent's build_context."""
    return ("Positions the person is thinking of closing (JSON):\n\n"
            f"{json.dumps(snapshot or {}, indent=2, default=str)}\n\n"
            "Produce the close-advice JSON now.")


def estimated_usd(user_message: str, n_positions: int, *,
                  model: Optional[str] = None) -> float:
    """What one question should cost at most, for can_spend.

    Counted from the text about to be sent and the number of positions the
    answer has to cover — see CHARS_PER_TOKEN and its neighbours for the
    arithmetic and why a flat figure was wrong. Priced at the rates of the
    model the agent will actually run on (a per-agent override included);
    an unreadable setting falls back to the balanced tier's price rather
    than to zero, because an estimate of zero is a guard that never trips.
    """
    from ai_agents.catalog import pricing_for, resolve_agent

    if model is None:
        try:
            model = resolve_agent(CloseAdvisorAgent.agent_name,
                                  CloseAdvisorAgent.default_tier)
        except Exception:  # noqa: BLE001 — price it, whatever it runs on
            model = ""
    price = pricing_for(model or "")
    tokens_in = (len(SYSTEM_PROMPT) + len(user_message or "")) \
        / CHARS_PER_TOKEN
    tokens_out = (OUTPUT_TOKENS_BASE
                  + OUTPUT_TOKENS_PER_POSITION * max(0, int(n_positions)))
    usd = (tokens_in * price["input"]
           + tokens_out * price["output"]) / 1_000_000
    return round(max(MIN_ESTIMATED_USD, usd * ESTIMATE_MARGIN), 4)


class CloseAdvisorAgent(BaseAgent):
    """One bounded judgment on a handful of positions somebody is about to
    close. Balanced tier: the facts are measured already, and the question
    is narrow — the deep tier is for work that reasons across the platform."""

    agent_name = "close_advisor"
    default_tier = "balanced"

    def get_system_prompt(self) -> str:
        return SYSTEM_PROMPT

    def build_context(self, **kwargs) -> str:
        return context_for(kwargs.get("snapshot") or {})

    def parse_response(self, raw_response: str) -> dict:
        text = (raw_response or "").strip()
        if text.startswith("```"):
            lines = text.splitlines()[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            text = "\n".join(lines)
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise ValueError(f"non-JSON close advisor output: {e}: "
                             f"{text[:200]}")
        if not isinstance(data, dict):
            raise ValueError("close advisor returned non-dict")
        return data


def build_snapshot(answer: dict) -> dict:
    """What the model may see: the rule-based answer and the facts under it.

    No user, no account, no broker ids — the question is about positions,
    and nothing beyond them needs to leave the building.
    """
    rows = []
    for p in answer["positions"]:
        n = p.get("numbers") or {}
        f = p.get("facts") or {}
        rows.append({
            "trade_id": p["trade_id"],
            "symbol": p["symbol"], "side": p["side"], "kind": p["kind"],
            "status": p["status"], "pending": bool(p.get("pending")),
            "world": p["world"],
            "rule": p.get("rule", ""),
            "rule_based_verdict": p["verdict"],
            "rule_based_reasons": p["reasons"],
            "triggers": p.get("triggers", []),
            "numbers": {k: n.get(k) for k in (
                "mark", "entry", "pnl", "ccy", "r_now", "r_to_stop",
                "r_to_planned_stop", "r_to_target", "age_hours",
                "committed", "committed_kind")},
            "facts": {k: f.get(k) for k in (
                "signals", "market", "venue_stop", "venue_risk_r",
                "time_stop", "regime_at_entry", "regime_now", "vol_ratio",
                "horizon_days", "mae_r", "mfe_r", "rule_state") if k in f},
        })
    s = answer["summary"]
    return {"as_of": answer["as_of"], "positions": rows,
            "selection": {k: s.get(k) for k in (
                "count", "positions", "orders", "live", "demo", "paper",
                "pnl", "ccy", "capital_freed", "overall")}}


def _clamp(parsed: dict, positions: list) -> tuple:
    """({trade_id: model part}, overall) — only what the model may have said.

    A verdict outside the four words falls back to the rule-based one: a
    garbled answer must never read as "close". An "unknown" rule-based
    verdict stays unknown — there is no price, and the model has none
    either. An order only ever gets withdraw (close) or keep (hold).
    """
    by_id = {p["trade_id"]: p for p in positions}
    out = {}
    items = parsed.get("positions") if isinstance(parsed, dict) else None
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        try:
            tid = int(item.get("trade_id"))
        except (TypeError, ValueError):
            continue
        det = by_id.get(tid)
        if det is None or tid in out:
            continue
        verdict = str(item.get("verdict") or "").strip().lower()
        if verdict not in VERDICTS or det["verdict"] == VERDICT_UNKNOWN:
            verdict = det["verdict"]
        if det["kind"] == KIND_ORDER and verdict not in ORDER_WORDS:
            verdict = det["verdict"]
        if det["kind"] == KIND_POSITION and verdict == VERDICT_UNKNOWN:
            verdict = det["verdict"]
        try:
            confidence = float(item.get("confidence"))
            confidence = (round(max(0.0, min(1.0, confidence)), 2)
                          if confidence == confidence else None)
        except (TypeError, ValueError):
            confidence = None
        reasoning = item.get("reasoning")
        reasoning = reasoning.strip()[:1500] if isinstance(reasoning, str) \
            else ""
        words = (ORDER_WORDS if det["kind"] == KIND_ORDER
                 else PENDING_WORDS if det.get("pending")
                 else VERDICT_WORDS)[verdict]
        out[tid] = {"verdict": verdict, "verdict_words": words,
                    "reasoning": reasoning, "confidence": confidence,
                    "agrees": verdict == det["verdict"]}
    overall = parsed.get("overall") if isinstance(parsed, dict) else ""
    overall = overall.strip()[:800] if isinstance(overall, str) else ""
    return out, overall


RULE_ONLY = " This is Sauron's rule-based answer only."


def _model_pass(user, answer: dict) -> None:
    """Fold ONE model answer for the selection into `answer`, in place.

    Never raises: every way the AI part can be missing ends in a sentence
    in answer["model"]["note"], and the rule-based answer stands as it was.
    """
    from ai_agents.spend import can_spend

    part = answer["model"]
    if not answer["positions"]:
        part["note"] = "Nothing to ask about: none of the ticked rows is open."
        return
    if not os.getenv("ANTHROPIC_API_KEY", "").strip():
        part["note"] = ("The AI part is missing: no Anthropic API key is "
                        "configured on this server." + RULE_ONLY)
        return
    # The message is built first so the estimate prices what will actually
    # be sent — fifty rows cost several times what one does — and the same
    # text is then sent, not rebuilt.
    user_message = context_for(build_snapshot(answer))
    allowed, reason = can_spend(
        tier=CloseAdvisorAgent.default_tier,
        estimated_usd=estimated_usd(user_message, len(answer["positions"])))
    if not allowed:
        part["note"] = ("The AI part is missing: today's AI budget refused "
                        "the call (%s)." % reason + RULE_ONLY)
        return

    ids = [p["trade_id"] for p in answer["positions"]]
    try:
        agent = CloseAdvisorAgent()
        raw, usage = agent.provider.complete(
            system_prompt=agent.get_system_prompt(),
            user_message=user_message,
            model=agent.model,
            agent_name=agent.agent_name,
            # Which question this cost answered, for the ledger — the user
            # and the rows, never anything a person could act on.
            source_ref=("close_advice:user=%s:trades=%s"
                        % (getattr(user, "pk", ""),
                           ",".join(str(i) for i in ids)))[:250],
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("[close-advice] model call failed: %s", e)
        part["note"] = ("The AI part is missing: the model call failed (%s)."
                        % str(e)[:160] + RULE_ONLY)
        return
    try:
        parsed = agent.parse_response(raw)
    except ValueError as e:
        logger.warning("[close-advice] unreadable model answer: %s", e)
        part["note"] = ("The AI part is missing: its answer could not be "
                        "read." + RULE_ONLY)
        return

    parts, overall = _clamp(parsed, answer["positions"])
    if not parts and not overall:
        part["note"] = ("The AI part is missing: its answer said nothing "
                        "about these positions." + RULE_ONLY)
        return
    for p in answer["positions"]:
        if p["trade_id"] in parts:
            p["model"] = parts[p["trade_id"]]
    missing = [p["symbol"] for p in answer["positions"]
               if p["trade_id"] not in parts]
    part.update(
        used=True, model=agent.model, overall=overall,
        cost_usd=round(float((usage or {}).get("cost_usd", 0) or 0), 6),
        note=("The AI said nothing about %s; the rule-based answer stands "
              "there." % ", ".join(missing)) if missing else "")
