"""THE MARK SANITY (2026-10-05): the engine never decides on a dead or an
aberrant mark.

The operator asked for more resilience on open positions. Everything in
manage_positions that acts on a row — the soft stop and its mirror at the
venue, the scale-out, the bot-side SL/TP, the trailing move — compares
against ONE number: the mark the venue's ticker answered this tick. The
paper venue already refuses a quote older than its MAX_QUOTE_AGE_SECONDS
and a shut market's last print; a REAL venue's rate carried no such guard.
A one-tick aberrant print (a bad lastExecution, a rate row off its grid) or
a feed frozen in an open market could close a position, bank a half, move
a stop or write a false best/worst — and nothing would have said so.

Three reads, in `judge` (pure) and `check` (the engine's call):

  THE JUMP        the mark against the LAST ACCEPTED mark, when that one is
                  younger than JUMP_WINDOW_MINUTES: a move past the class's
                  bar (JUMP_PCT) is SUSPECT — unless the second opinion
                  agrees with it, or the previous tick was already suspect
                  at about the same price (CONFIRMING_TICKS prints in a row
                  are the market, not a glitch). A suspect mark manages
                  nothing this tick; the row waits for the next print.
  THE SECOND      a REAL row's mark against the platform's own fresh quote
  OPINION         (market_data.LiveQuote, another source, younger than
                  SECOND_OPINION_MAX_AGE_S): past the bar apart, the mark is
                  suspect even without a jump; within it, a jump is
                  confirmed at once. A paper row's mark IS the platform's
                  quote, so it gets no second opinion.
  THE FREEZE      the same mark, to the last decimal, for FROZEN_MINUTES in
                  a market the clock says is open: the feed is dead, not
                  quiet. Nothing is managed on it, and the staff are told
                  once per freeze (notifications.notify_staff); the first
                  different print clears it.

Options are never judged: a premium jumps for a living. What the read
decided is written on the row's care (metadata["care"]: last_mark,
last_mark_at, mark_same_since, mark_suspect, mark_frozen_alerted_at) and a
suspect or frozen tick is a skip (skips.SUSPECT_MARK) so the operator reads
why a row was left alone. Never raises: a read that fails lets the tick run
as before.
"""
import logging
from datetime import timedelta

from django.utils import timezone
from django.utils.dateparse import parse_datetime

logger = logging.getLogger(__name__)

#: The move, as a fraction of the last accepted mark, past which one print
#: is suspect until confirmed — by class. Generous on purpose: a crash is
#: confirmed by its second print one tick later; a glitch never is.
JUMP_PCT = {"forex": 0.005, "crypto": 0.03, "stock": 0.03, "etf": 0.03,
            "index": 0.015, "commodity": 0.02}
#: A last mark older than this is not compared: hours apart, prices differ.
JUMP_WINDOW_MINUTES = 15
#: Prints in a row at about the same level that make a jump the market's.
CONFIRMING_TICKS = 2
#: The platform's own quote counts as a second opinion while this young.
SECOND_OPINION_MAX_AGE_S = 900
#: The same mark for this long in an open market is a dead feed.
FROZEN_MINUTES = 45
#: Sources whose quote is the venue's own rate: no second opinion there.
VENUE_SOURCES = ("etoro",)
#: Classes never judged.
NEVER_JUDGED = frozenset({"options"})


def _f(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def _when(s):
    if not s:
        return None
    try:
        return parse_datetime(str(s))
    except (TypeError, ValueError):
        return None


def bar_for(asset_class) -> float:
    """The jump bar for a class, or 0 when the class is never judged."""
    return float(JUMP_PCT.get(str(asset_class or "").lower()) or 0.0)


def judge(trade, price, *, now=None, reference=None, market_open=True) -> dict:
    """{ok, why, care, changed, frozen, alert}: whether `price` may be acted
    on for `trade` this tick, and the care keys to write. Pure: no I/O.
    `reference` is the second opinion's price (None when there is none),
    `market_open` the clock's word for the freeze read."""
    now = now or timezone.now()
    care = dict((getattr(trade, "metadata", None) or {}).get("care") or {})
    out = {"ok": True, "why": "", "care": care, "changed": False,
           "frozen": False, "alert": False}
    p = _f(price)
    cls = str(getattr(trade, "asset_class", "") or "").lower()
    if p is None or p <= 0 or cls in NEVER_JUDGED:
        return out
    bar = bar_for(cls)
    last = _f(care.get("last_mark"))
    last_at = _when(care.get("last_mark_at"))
    suspect = dict(care.get("mark_suspect") or {})
    ref = _f(reference)
    agreed = (ref is not None and ref > 0 and bar > 0
              and abs(p - ref) / ref <= bar)
    disagreed = (ref is not None and ref > 0 and bar > 0
                 and abs(p - ref) / ref > bar)

    def _accept(care_now):
        same = last is not None and abs(p - last) <= 1e-12
        care_now["last_mark"] = p
        care_now["last_mark_at"] = now.isoformat()
        if not same or not care_now.get("mark_same_since"):
            care_now["mark_same_since"] = now.isoformat()
        care_now.pop("mark_suspect", None)
        if not same:
            care_now.pop("mark_frozen_alerted_at", None)
        out["care"] = care_now
        out["changed"] = True
        return out

    # THE JUMP, read against the last accepted mark while it is young
    jumped = False
    if bar > 0 and last is not None and last > 0 and last_at is not None \
            and (now - last_at) <= timedelta(minutes=JUMP_WINDOW_MINUTES):
        jumped = abs(p - last) / last > bar

    if bar > 0 and (disagreed or (jumped and not agreed)):
        # the same suspect level printed again: the market, not a glitch
        prev = _f(suspect.get("price"))
        ticks = int(suspect.get("ticks") or 0)
        if prev is not None and prev > 0 and abs(p - prev) / prev <= bar:
            ticks += 1
        else:
            ticks = 1
        if ticks >= CONFIRMING_TICKS and not disagreed:
            return _accept(care)
        if disagreed:
            why = (f"the venue's mark {p:g} is {abs(p - ref) / ref:.1%} from "
                   f"the platform's quote {ref:g} (bar {bar:.1%})")
        else:
            why = (f"the mark {p:g} is {abs(p - last) / last:.1%} from the "
                   f"last accepted {last:g} (bar {bar:.1%}); print "
                   f"{ticks} of {CONFIRMING_TICKS}")
        care["mark_suspect"] = {"price": p, "at": now.isoformat(),
                                "ticks": ticks, "why": why}
        out.update(ok=False, why=f"suspect mark: {why}", care=care,
                   changed=True)
        return out

    # THE FREEZE: the same print for FROZEN_MINUTES in an open market
    same = last is not None and abs(p - last) <= 1e-12
    if same and market_open and bar > 0:
        since = _when(care.get("mark_same_since")) or last_at
        if since is not None and (now - since) >= timedelta(
                minutes=FROZEN_MINUTES):
            minutes = int((now - since).total_seconds() // 60)
            care["last_mark_at"] = now.isoformat()
            care.setdefault("mark_same_since", since.isoformat())
            alert = not care.get("mark_frozen_alerted_at")
            if alert:
                care["mark_frozen_alerted_at"] = now.isoformat()
            out.update(ok=False, frozen=True, alert=alert, care=care,
                       changed=True,
                       why=(f"frozen mark: {p:g} unchanged for {minutes} "
                            f"minutes in an open market"))
            return out
    return _accept(care)


def second_opinion(symbol, *, now=None, max_age_s=SECOND_OPINION_MAX_AGE_S):
    """The platform's own fresh quote for `symbol` from a source that is
    not the venue's, as a float — or None (none, stale, or the venue's)."""
    now = now or timezone.now()
    try:
        from market_data.models import LiveQuote
        q = (LiveQuote.objects.filter(instrument__symbol=symbol)
             .only("last", "updated_at", "source").first())
    except Exception as e:  # noqa: BLE001 — no opinion is an answer
        logger.debug("[mark] %s: second opinion unread (%s)", symbol, e)
        return None
    if q is None or q.updated_at is None:
        return None
    src = str(q.source or "").lower()
    if any(src.startswith(v) for v in VENUE_SOURCES):
        return None
    if (now - q.updated_at).total_seconds() > max_age_s:
        return None
    last = _f(q.last)
    return last if last and last > 0 else None


def check(bot, trade, price, client=None, *, now=None) -> dict:
    """The engine's read for one row at one mark (manage_positions, after
    the no-price gate): judge, write the care keys, record a skip and the
    freeze alert. {ok, why}. Never raises — a read that fails is ok."""
    now = now or timezone.now()
    try:
        if str(trade.asset_class or "").lower() in NEVER_JUDGED:
            return {"ok": True, "why": ""}
        reference = None if trade.paper else second_opinion(trade.symbol,
                                                            now=now)
        market_open = True
        try:
            from bot_program.engine.paper_trader import paper_market_shut
            market_open = not paper_market_shut(trade.symbol,
                                                trade.asset_class, now=now)
        except Exception:  # noqa: BLE001 — an unread clock reads open
            market_open = True
        verdict = judge(trade, price, now=now, reference=reference,
                        market_open=market_open)
        if verdict["changed"]:
            from bot_program.position_care import _save_care
            _save_care(trade, verdict["care"])
        if verdict["ok"]:
            return {"ok": True, "why": ""}
        logger.warning("[mark] %s #%s: %s — nothing managed on this row this "
                       "tick", trade.symbol, trade.id, verdict["why"])
        try:
            from bot_program.asset_engine import skips
            skips.record(bot.cfg, trade.symbol, skips.SUSPECT_MARK,
                         verdict["why"])
        except Exception as e:  # noqa: BLE001
            logger.debug("[mark] skip not recorded: %s", e)
        if verdict["alert"]:
            try:
                from bot_program.notifications import notify_staff
                notify_staff(
                    title=f"⚠ {trade.symbol}: the mark has not moved "
                          f"for {FROZEN_MINUTES} minutes in an open market",
                    body=(f"Trade #{trade.id} ({'paper' if trade.paper else 'REAL MONEY'}) "
                          f"is priced by a feed that prints the same figure. "
                          f"Nothing is managed on it until the mark moves; "
                          f"read the feed and the venue."),
                    url="/positions/")
            except Exception as e:  # noqa: BLE001
                logger.warning("[mark] freeze alert failed: %s", e)
        return {"ok": False, "why": verdict["why"]}
    except Exception as e:  # noqa: BLE001 — the read never blocks the tick
        logger.warning("[mark] %s #%s: sanity unread (%s) — the tick runs",
                       getattr(trade, "symbol", "?"), getattr(trade, "id", "?"),
                       e)
        return {"ok": True, "why": ""}
