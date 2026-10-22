"""The deterministic journal (spec §1.4, O1): facts written by code about
what the row and the platform did, each once, when it changed.

  the care     its own stop moved (by the quarter R: a trail grind is one
               fact per 0.25R, not one per tick); an event window opened;
               a paper scale-out banked; the care decided to close
  the mirror   the venue took the stop, or refused it (the venue's own
               words are not copied)
  the hand     a hand levels edit (care["venue_stop_hand"], PR O0b): a fact
               and a hand act for the grade
  the thesis   the thesis check's verdict changed (metadata["thesis"])
  the reviewer a reviewer's verdict (never its reasoning)
  the venue    what the platform read of it, as stamped on the row
               (bot_program/venue_exit.py), in the order it happened and
               saying no more than the stamp proves: the first mark
               beyond a level the venue holds (CROSSED_KEY); the first
               tick list that did not show the position (MISSING_AT_KEY,
               the care's read: nothing is booked on it, the reconcile
               asks the venue first); the venue's own order read saying
               the position is still open (SAID_OPEN_AT_KEY, once per run
               of misses); the list showing it again (LISTED_AT_KEY, once
               after a miss the journal wrote); a close pending at the
               venue; the close itself (lifecycle)

R is the price-distance R: d x (level - entry) / |entry - initial stop|.
Prices go through core.price_format.format_price. No money, balance or
account figure is ever written.

Every reader here costs nothing on a quiet tick: the row's metadata is
already in memory (the care just merged it, position_care._save_care),
compared against the Orc's own memory (`Orc.seen`), and an entry is
written only on a change.
"""
import logging
import math
from datetime import datetime
from datetime import timezone as dt_tz

from core.price_format import format_price

from bot_program.orcs import journal
from bot_program.orcs.constants import (CARE_FACT_STEP_R,
                                        REVIEW_FACT_VERDICTS, STATE_DEAD)

logger = logging.getLogger(__name__)

#: The rows a fact reader walks: a leg still held at the venue.
OPEN_STATUSES = ("OPEN", "CLOSE_PENDING")
REVIEW_WORDS = {"hold": "hold", "tighten": "tighten",
                "take_part": "take part", "exit": "exit"}
#: The venue's evidence on the row (bot_program/venue_exit.py:43-45, :49;
#: the same strings, so the package imports nothing of the venue's here).
VENUE_LISTED_KEY = "venue_listed_at"
VENUE_SAID_OPEN_KEY = "venue_said_open_at"
VENUE_MISSING_KEY = "venue_missing_at"
VENUE_CROSSED_KEY = "venue_level_crossed"
#: brain/thesis_check.UNREAD: the check read nothing, no verdict.
THESIS_UNREAD = "unread"


# ── the arithmetic and the words ─────────────────────────────────────────

def _f(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def initial_stop(trade):
    """The stop the row opened with (manual_close._initial_stop's rule)."""
    meta = trade.metadata if isinstance(trade.metadata, dict) else {}
    stop = _f(meta.get("initial_stop_loss"))
    if stop is None:
        stop = _f(trade.stop_loss)
    return stop if stop and stop > 0 else None


def r_at(trade, level):
    """d x (level - entry) / |entry - initial stop|, or None unmeasured."""
    entry, stop, level = _f(trade.entry_price), initial_stop(trade), _f(level)
    if not entry or stop is None or level is None:
        return None
    risk = abs(entry - stop)
    if risk <= 0:
        return None
    d = 1.0 if str(trade.side).upper() == "BUY" else -1.0
    return d * (level - entry) / risk


def px(trade, value) -> str:
    return format_price(value, getattr(trade, "asset_class", ""),
                        getattr(trade, "symbol", ""))


def with_r(head: str, r) -> str:
    """"<head>, +0.25R." or "<head>; its R is not measured."."""
    if r is None:
        return f"{head}; its R is not measured."
    return f"{head}, {r:+.2f}R."


def _bucket(trade, level):
    """The quarter-R bucket of a stop level (the level itself, rounded,
    when the row has no R)."""
    r = r_at(trade, level)
    if r is None:
        lv = _f(level)
        return None if lv is None else round(lv, 8)
    return int(math.floor(r / CARE_FACT_STEP_R + 1e-9))


def _when(at):
    """A stamp as an aware UTC moment, or None when it does not read."""
    if isinstance(at, datetime):
        moment = at
    else:
        from django.utils.dateparse import parse_datetime
        try:
            moment = parse_datetime(str(at or ""))
        except (TypeError, ValueError):
            return None
    if moment is None:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt_tz.utc)
    return moment.astimezone(dt_tz.utc)


def _hhmm(at) -> str:
    moment = _when(at)
    return "an unread time" if moment is None else moment.strftime("%H:%M")


# ── birth ─────────────────────────────────────────────────────────────────

def birth_line(trade, *, adopted: bool) -> str:
    entry = px(trade, trade.entry_price)
    stop = initial_stop(trade)
    if stop is None:
        head = (f"Adopted at {entry}" if adopted else f"Born at {entry}")
        tail = " Its thesis is reconstructed from the row." if adopted else ""
        return (f"{head} with no stop: no R, so this Orc stays in shadow for "
                f"life.{tail}")
    if adopted:
        return (f"Adopted at {entry}, stop {px(trade, stop)}. Its thesis is "
                f"reconstructed from the row: the entry's record, the care's "
                f"history and the latest reviews.")
    return (f"Born at {entry}, stop {px(trade, stop)}: 1R is the distance to "
            f"that stop.")


def _sentence(parts) -> str:
    text = "; ".join(str(p) for p in parts if str(p or "").strip())
    return text[:1].upper() + text[1:] if text else ""


def army_line(assigned) -> str:
    from bot_program.orcs.army import name_of
    return f"Army: {name_of(assigned.get('base'))}. " \
           f"{_sentence(assigned.get('why') or [])}."


def overlay_line(assigned) -> str:
    return f"Corsair overlay: {'; '.join(assigned.get('overlay_why') or [])}."


def _care_state(trade) -> dict:
    meta = trade.metadata if isinstance(trade.metadata, dict) else {}
    care = meta.get("care")
    return care if isinstance(care, dict) else {}


def baseline(orc, trade) -> None:
    """The observer's memory at birth: what the row already says is not
    news. An adopted row's history is in its thesis, not in facts."""
    meta = trade.metadata if isinstance(trade.metadata, dict) else {}
    care = _care_state(trade)
    soft = _f(care.get("soft_stop"))
    venue = _f(care.get("venue_stop"))
    hand = care.get("venue_stop_hand")
    event = care.get("event")
    th = meta.get("thesis")
    crossed = meta.get(VENUE_CROSSED_KEY)
    memory = {
        # the same key observe_tick builds, default included: a stop with
        # no recorded why is the care's lock there, so it is here
        "care_stop": ([_bucket(trade, soft),
                       str(care.get("soft_why") or "lock")]
                      if soft is not None else None),
        "venue_stop": _bucket(trade, venue) if venue is not None else None,
        "venue_refused": (_bucket(trade, care.get("venue_asked_for"))
                          if care.get("venue_stop_refusal") else None),
        "hand_at": (str(hand.get("at") or "")
                    if isinstance(hand, dict) else None),
        "event_at": (str(event.get("at") or "")
                     if isinstance(event, dict) else None),
        "scaled_out": bool(care.get("scaled_out")),
        "care_close": False,
        "thesis": ([th.get("verdict"), _f(th.get("stop"))]
                   if isinstance(th, dict) and th.get("verdict") else None),
        "review_id": _latest_review_id(trade),
        "venue_missing_at": (str(meta.get(VENUE_MISSING_KEY))
                             if meta.get(VENUE_MISSING_KEY) else None),
        "venue_crossed_at": (str(crossed.get("at"))
                             if isinstance(crossed, dict)
                             and crossed.get("at") else None),
        "venue_said_open_at": (str(meta.get(VENUE_SAID_OPEN_KEY))
                               if meta.get(VENUE_SAID_OPEN_KEY) else None),
        # a run of misses this journal wrote, so a listing after it is
        # news (none at birth: the row's history is not journaled again)
        "venue_unlisted": None,
        "pending": [],
        "closed_legs": [],
        # the facts the birth itself wrote (the army type, the overlay):
        # thesis.complete_provenance acts only while nothing came after
        "birth_seq": int((orc.seen or {}).get("fact_seq") or 0),
    }
    journal.remember(orc, **memory)


def _latest_review_id(trade) -> int:
    try:
        from brain.position_review_models import PositionReview
        rid = (PositionReview.objects
               .filter(book="bot", position_id=trade.pk,
                       verdict__in=REVIEW_FACT_VERDICTS)
               .order_by("-id").values_list("id", flat=True).first())
        return int(rid or 0)
    except Exception:  # noqa: BLE001 — an unread table starts at zero
        return 0


# ── the tick ──────────────────────────────────────────────────────────────

def observe_tick(bot, trade, price, cared, orc) -> int:
    """Right after the care, for a row with a live Orc: one fact per change
    the care, the mirror, a hand edit or the thesis check left on the row.
    Returns the facts written. A dead Orc hears only its care's close."""
    meta = trade.metadata if isinstance(trade.metadata, dict) else {}
    care = _care_state(trade)
    seen = orc.seen if isinstance(orc.seen, dict) else {}
    n = 0

    def fact(headline, *, author="code", body=None, remember=None,
             fields=None):
        nonlocal n
        journal.append(orc, "fact", headline, author=author, body=body,
                       fact=True, remember=remember, fields=fields)
        n += 1

    if orc.state != STATE_DEAD:
        soft = _f(care.get("soft_stop"))
        if soft is not None:
            why = str(care.get("soft_why") or "lock")
            key = [_bucket(trade, soft), why]
            if key != seen.get("care_stop"):
                fact(with_r(f"The care moved its stop to {px(trade, soft)} "
                            f"({why})", r_at(trade, soft)),
                     author="care", body={"level": soft, "why": why},
                     remember={"care_stop": key})
        venue = _f(care.get("venue_stop"))
        if venue is not None:
            key = _bucket(trade, venue)
            if key != seen.get("venue_stop"):
                fact(with_r(f"The venue now holds the stop at "
                            f"{px(trade, venue)}", r_at(trade, venue)),
                     body={"level": venue}, remember={"venue_stop": key})
        if care.get("venue_stop_refusal"):
            asked = _f(care.get("venue_asked_for"))
            key = _bucket(trade, asked) if asked is not None else "?"
            if key != seen.get("venue_refused"):
                where = (f" at {px(trade, asked)}" if asked is not None
                         else "")
                fact(f"The venue refused the stop{where}; the care keeps it "
                     f"on the platform.", body={"level": asked},
                     remember={"venue_refused": key})
        elif seen.get("venue_refused") is not None:
            journal.remember(orc, venue_refused=None)
        hand = care.get("venue_stop_hand")
        if isinstance(hand, dict) and hand.get("at") \
                and str(hand.get("at")) != seen.get("hand_at"):
            level = _f(hand.get("level"))
            fact(with_r(f"A hand edit set the venue's stop at "
                        f"{px(trade, level)}", r_at(trade, level))
                 + " The grade counts it as a hand act.", author="operator",
                 body={"level": level, "at": str(hand.get("at"))},
                 remember={"hand_at": str(hand.get("at"))},
                 fields={"hand_touched": True})
        event = care.get("event")
        if isinstance(event, dict) and event.get("at") \
                and str(event.get("at")) != seen.get("event_at"):
            fact(f"An event window opened: a high-impact print at "
                 f"{_hhmm(event.get('at'))} UTC.",
                 author="care",
                 body={"title": str(event.get("title") or "")[:80],
                       "at": str(event.get("at"))},
                 remember={"event_at": str(event.get("at"))})
        if care.get("scaled_out") and not seen.get("scaled_out"):
            so = meta.get("scale_out") if isinstance(meta.get("scale_out"),
                                                     dict) else {}
            part = _part_words(so)
            r = _f(so.get("r"))
            head = f"The care banked {part}"
            fact((f"{head} at {r:+.2f}R (paper)." if r is not None
                  else f"{head} (paper); its R is not measured."),
                 author="care", body={"r": r},
                 remember={"scaled_out": True})
        th = meta.get("thesis")
        if isinstance(th, dict) and th.get("verdict"):
            verdict = str(th.get("verdict"))
            stop = _f(th.get("stop"))
            key = [verdict, stop]
            if key != seen.get("thesis"):
                if verdict == "adjust" and stop is not None:
                    text = (f"The thesis check reads adjust: a structure "
                            f"stop at {px(trade, stop)}.")
                elif verdict == THESIS_UNREAD:
                    text = "The thesis check could not read the structure."
                else:
                    text = f"The thesis check reads {verdict}."
                fact(text, body={"verdict": verdict, "stop": stop},
                     remember={"thesis": key})
        for headline, kw in _venue_news(trade, meta, seen):
            fact(headline, **kw)
    if cared in ("closed", "attempted") and not seen.get("care_close"):
        why = str(meta.get("care_exit") or care.get("exit") or "its stop")
        fact(with_r(f"The care decided to close ({why}) at "
                    f"{px(trade, price)}", r_at(trade, price)),
             author="care", body={"why": why, "price": _f(price),
                                  "sent": cared},
             remember={"care_close": True})
    return n


_NEVER = datetime(1970, 1, 1, tzinfo=dt_tz.utc)


def _venue_news(trade, meta, seen) -> list:
    """The venue's evidence on the row the journal has not written yet,
    oldest first: [(headline, fact kwargs)]. Each says only what its
    stamp proves (bot_program/venue_exit.py):

      CROSSED_KEY     base.py stamps it before the care: a mark beyond a
                      level the venue holds; once per `at`.
      MISSING_AT_KEY  the care's read of the tick's list did not show the
                      position (position_care._venue_still_holds ->
                      note_missing). It books nothing: the reconcile books
                      a close only on the venue's own order read
                      (word_on_miss), so the fact never says a close will
                      be booked. Once per stamp.
      SAID_OPEN_AT_KEY  the list missed it and the venue's order read said
                      OPEN (said_open): nothing booked. Stamped at every
                      such answer, so written once per run of misses: a
                      run ends when the list shows the position again.
      LISTED_AT_KEY   the reconcile's read listed the position (note_listed
                      pops MISSING_AT_KEY): written once, only after a miss
                      or an "open" answer this journal wrote.
    The stamps come from separate readers (the tick, the care, the
    reconcile), so they are written in the order their times say, and
    one tick's crossing comes before the same tick's miss."""
    news = []           # (moment, order, headline, kwargs)
    crossed = meta.get(VENUE_CROSSED_KEY)
    if isinstance(crossed, dict) and crossed.get("at") \
            and str(crossed.get("at")) != seen.get("venue_crossed_at"):
        at = str(crossed.get("at"))
        which = "target" if str(crossed.get("level")) == "target" else "stop"
        level = _f(crossed.get("price"))
        where = f" at {px(trade, level)}" if level is not None else ""
        news.append((_when(at), 0,
                     f"The mark crossed the venue's {which}{where} "
                     f"({_hhmm(at)} UTC).",
                     {"body": {"level": which, "price": level,
                               "mark": _f(crossed.get("mark")), "at": at},
                      "remember": {"venue_crossed_at": at}}))
    missing = meta.get(VENUE_MISSING_KEY)
    if missing and str(missing) != seen.get("venue_missing_at"):
        at = str(missing)
        news.append((_when(at), 1,
                     f"The tick's position list did not show this position "
                     f"at {_hhmm(at)} UTC; the reconcile asks the venue "
                     f"before it books anything.",
                     {"author": "care", "body": {"at": at},
                      "remember": {"venue_missing_at": at,
                                   "venue_unlisted": at}}))
    listed = _when(meta.get(VENUE_LISTED_KEY))
    said = _when(meta.get(VENUE_SAID_OPEN_KEY))
    told = _when(seen.get("venue_said_open_at"))
    if said is not None and (listed is None or said > listed) \
            and (told is None or (listed is not None and told < listed)):
        at = str(meta.get(VENUE_SAID_OPEN_KEY))
        news.append((said, 2,
                     f"The venue's position list missed this position, but "
                     f"its own order read says it is still open "
                     f"({_hhmm(at)} UTC); nothing was booked.",
                     {"body": {"at": at},
                      "remember": {"venue_said_open_at": at,
                                   "venue_unlisted": at}}))
    unlisted = seen.get("venue_unlisted")
    if unlisted and listed is not None and not missing \
            and listed > (_when(unlisted) or _NEVER):
        at = str(meta.get(VENUE_LISTED_KEY))
        news.append((listed, 3,
                     f"The venue's position list shows this position again "
                     f"({_hhmm(at)} UTC).",
                     {"body": {"at": at},
                      "remember": {"venue_unlisted": None,
                                   "venue_missing_at": None}}))
    news.sort(key=lambda n: (n[0] is None, n[0] or _NEVER, n[1]))
    return [(headline, kw) for _, _, headline, kw in news]


def _part_words(so) -> str:
    qty, whole = _f(so.get("qty")), _f(so.get("original_qty"))
    if qty and whole and whole > 0:
        frac = qty / whole
        if abs(frac - 0.5) < 1e-6:
            return "half the position"
        return f"{frac:.0%} of the position"
    return "a part of the position"


# ── the census's readers ──────────────────────────────────────────────────

def _open_legs():
    from bot_program.orcs.models import OrcLeg
    return list(OrcLeg.objects.select_related("orc", "trade")
                .filter(trade__status__in=OPEN_STATUSES)
                .exclude(orc__state=STATE_DEAD))


def observe_reviews(now=None, legs=None) -> int:
    """One fact per new reviewer verdict on an open leg (one query for the
    reviews): the verdict, the mark and its R. Never the reasoning."""
    legs = _open_legs() if legs is None else legs
    if not legs:
        return 0
    from brain.position_review_models import PositionReview
    by_trade = {leg.trade_id: leg for leg in legs}
    floor = min(int((leg.orc.seen or {}).get("review_id") or 0)
                for leg in legs)
    reviews = (PositionReview.objects
               .filter(book="bot", position_id__in=list(by_trade),
                       id__gt=floor, verdict__in=REVIEW_FACT_VERDICTS)
               .order_by("id")
               .only("id", "position_id", "verdict", "mark", "unrealized_r"))
    n = 0
    for rv in reviews:
        leg = by_trade.get(rv.position_id)
        if leg is None:
            continue
        orc, trade = leg.orc, leg.trade
        if rv.id <= int((orc.seen or {}).get("review_id") or 0):
            continue
        try:
            words = REVIEW_WORDS.get(rv.verdict, rv.verdict)
            r = _f(rv.unrealized_r)
            head = (f"The reviewer reads {words} at {px(trade, rv.mark)}"
                    if rv.mark is not None
                    else f"The reviewer reads {words}")
            journal.append(orc, "fact", with_r(head, r), body={
                "review": rv.id, "verdict": rv.verdict, "leg": trade.pk},
                fact=True, remember={"review_id": rv.id})
            n += 1
        except Exception as e:  # noqa: BLE001 — one review never stops it
            logger.warning("[orcs] review #%s not journaled: %s", rv.id, e)
    return n


def observe_pending(now=None, legs=None) -> int:
    """One fact per leg the venue has not closed yet (CLOSE_PENDING)."""
    legs = _open_legs() if legs is None else legs
    n = 0
    for leg in legs:
        if leg.trade.status != "CLOSE_PENDING":
            continue
        said = list((leg.orc.seen or {}).get("pending") or [])
        if leg.trade_id in said:
            continue
        try:
            journal.append(leg.orc, "fact", "A close is pending at the venue "
                           "for this position.", body={"leg": leg.trade_id},
                           fact=True,
                           remember={"pending": said + [leg.trade_id]})
            n += 1
        except Exception as e:  # noqa: BLE001
            logger.warning("[orcs] pending close of #%s not journaled: %s",
                           leg.trade_id, e)
    return n


# ── the close ─────────────────────────────────────────────────────────────

def is_hand_close(trade) -> bool:
    """A hand close on the platform (closed:MANUAL), or one in the venue's
    app that the reconcile booked as a manual close."""
    from bot_program.scorecard import HAND_CLOSE_TAG, RECONCILED_TAG
    reason = trade.reason or ""
    return (HAND_CLOSE_TAG in reason
            or (RECONCILED_TAG in reason and trade.outcome == "manual_close"))


def close_how(orc, trade) -> str:
    """Which exit closed the leg, in the scorecard's words (exit_of)."""
    if orc.killed:
        return "the kill switch"
    from bot_program.scorecard import RECONCILED_TAG, exit_of
    words = exit_of(trade)
    if RECONCILED_TAG in (trade.reason or ""):
        if trade.outcome == "manual_close":
            return "a hand close at the venue, found by the reconcile"
        return f"{words} at the venue, found by the reconcile"
    return words


def close_line(orc, trade) -> str:
    how = close_how(orc, trade)
    if trade.status == "CANCELED":
        return "The order was cancelled before it filled."
    if trade.exit_price is None:
        return f"The position closed ({how}); the exit is not priced."
    head = f"The position closed at {px(trade, trade.exit_price)} ({how})"
    r = _f(trade.realized_r)
    if r is None:
        return f"{head}; its R is not measured."
    return f"{head}, {r:+.2f}R booked."
