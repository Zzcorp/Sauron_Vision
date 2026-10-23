"""The Orc's card and the one read API every surface uses (spec §9.5,
§10.2): the Horde's seats and bands, the positions page's line, the close
dialog's note, the /orcs/ pages and /orc on Telegram.

THE CARD (O1a, O1c). What the surfaces read without a query per row: the
last three journal entries, refreshed at every append; the last wake's
`intellect` (its score, band and the day's class) and `integrity` flag,
the next metronome (`next_wake_due`) and the last three `drums` heard,
merged by O1c (card_extra); and, from O1d, the operator's own thesis
(`thesis_operator`, the last one he wrote). The card stays v1: every key
O1d adds is additive.

THE READS (O1d). `for_rows` is the Horde's seat read and the base of the
others: at most two queries whatever the number of rows (the legs with
their Orc and seat; the care ghost and the O arm). `for_trades` gates it on
the row's own stamp (`stamped`, the one place outside Morgul's G8 that
reads metadata["orc"]) and the switch, so a page with no Orc pays no
query. `for_classes` is the band's day: one query. Nothing here writes a
row, calls a model or reads a broker; the card is changed in memory only,
by `refresh`, inside journal.append's own transaction.

THE SLOT (O1, §9.5). Every key that describes an Orc's act or outcome
carries `mode` ("shadow" for every Orc in O1, §9.5's rule of 2026-10-15),
and no Orc verb is printed: in O1 no Orc has acted. The slot carries no
money: no cost, token, model, R-money or spend key at any depth (horde
§13.2 item 7), and the operator's own words in it (his thesis, his thesis
entries) pass PR68's plain words once, here (`_plain_voice`): every
surface shows them as written or withheld whole. The rank's key is `lineage`, never `seat` (horde C18).
Every sentence that names an Orc is listed in RESERVED_SENTENCES or
matches RESERVED_PATTERNS, so the Horde's reserved-word walk can read it.

THE SEAMS. effective_level is O3/O4a's §3.1 min(); the plan line, the
intents, temperament, honor and the lineage's record are O2's.
"""
import logging
import math
import re
from datetime import datetime
from datetime import timezone as dt_tz

from bot_program.orcs import ranks
from bot_program.orcs.constants import (ARM_CARE, ARM_ORC, GROSS_MAX_R,
                                        MODE_SHADOW, RANK_GATE_N, SLOT_V,
                                        THESIS_OPERATOR_MAX)

logger = logging.getLogger(__name__)

CARD_VERSION = 1
#: The journal entries the card keeps, newest last.
CARD_JOURNAL = 3
#: The drums heard the card keeps, newest last.
CARD_DRUMS = 3
#: Journal kinds kept off the card's lines (O1c: a detected wake is a
#: record for replay; its numbers ride the card's `intellect`).
OFF_CARD_KINDS = ("wake",)
#: A drum's kind in the card's words.
DRUM_WORDS = {"stop_hit": "a stop hit", "sweep": "a sweep",
              "thesis_turned": "a thesis turned", "level_break":
              "a level break", "news_shock": "a news shock",
              "print_surprise": "a print surprise", "fill": "a fill",
              "lock": "a lock"}
#: The journal kind and author of the operator's own thesis (O1d).
KIND_THESIS = "thesis"
AUTHOR_OPERATOR = "operator"


# ── the card ─────────────────────────────────────────────────────────────

def _iso(at) -> str:
    return at.isoformat() if hasattr(at, "isoformat") else str(at or "")


def _line(entry) -> dict:
    return {"at": _iso(getattr(entry, "at", None)),
            "kind": str(getattr(entry, "kind", "") or ""),
            "author": str(getattr(entry, "author", "") or ""),
            "t": str(getattr(entry, "headline", "") or "")}


def _drum(entry) -> dict:
    body = getattr(entry, "body", None) or {}
    return {"kind_t": DRUM_WORDS.get(str(body.get("drum_kind") or ""),
                                     "a drum"),
            "from_symbol": str(body.get("symbol") or ""),
            "relation": str(body.get("relation") or ""),
            "at": _iso(getattr(entry, "at", None))}


def _thesis_operator(entry):
    """{t, at} of an operator's thesis entry, or None for any other."""
    if getattr(entry, "kind", "") != KIND_THESIS \
            or getattr(entry, "author", "") != AUTHOR_OPERATOR:
        return None
    body = getattr(entry, "body", None) or {}
    th = body.get("thesis") if isinstance(body.get("thesis"), dict) else {}
    text = " ".join(str(th.get("text") or "").split())
    if not text:
        return None
    return {"t": text[:THESIS_OPERATOR_MAX],
            "at": _iso(getattr(entry, "at", None))}


def refresh(orc, *, entry=None, journal_entry=True, extra=None) -> dict:
    """The Orc's card with `entry` appended (no query), set on `orc.card`
    and returned; the caller saves it in the same transaction as the entry.
    Without an entry the last three are read again (one query).
    `journal_entry` False keeps `entry` off the lines; `extra` merges keys
    into the card (O1c's intellect, integrity, next_wake_due). An
    operator's thesis entry (O1d) is kept whole under `thesis_operator`."""
    card = dict(orc.card or {}) if isinstance(orc.card, dict) else {}
    lines = [j for j in (card.get("journal") or []) if isinstance(j, dict)]
    if entry is not None:
        if journal_entry and getattr(entry, "kind", "") not in OFF_CARD_KINDS:
            lines.append(_line(entry))
        if getattr(entry, "kind", "") == "drum":
            drums = [d for d in (card.get("drums") or [])
                     if isinstance(d, dict)]
            drums.append(_drum(entry))
            card["drums"] = drums[-CARD_DRUMS:]
        mine = _thesis_operator(entry)
        if mine is not None:
            card["thesis_operator"] = mine
    elif journal_entry:
        from bot_program.orcs.models import OrcJournal
        rows = list(OrcJournal.objects.filter(orc_id=orc.pk)
                    .exclude(kind__in=OFF_CARD_KINDS)
                    .order_by("-at", "-id")[:CARD_JOURNAL])
        lines = [_line(e) for e in reversed(rows)]
    if isinstance(extra, dict):
        card.update(extra)
    card["v"] = CARD_VERSION
    card["journal"] = lines[-CARD_JOURNAL:]
    orc.card = card
    return card


# ── the words (every sentence the slot, the line and the note print) ─────

DASH = "—"
STATE_WORDS = {
    "born": "Watching: a journal written by code, no model.",
    "active": "Active.",
    "care_owned": "Stood aside: the care holds this position.",
    "reentry_window": "Waiting: the re-entry window is open.",
    "dead": "Ended.",
}
#: The state in one word, for the close note and the lists.
STATE_SHORT = {"born": "watching", "active": "active",
               "care_owned": "stood aside", "reentry_window": "waiting",
               "dead": "ended"}
COMMISSION_WORDS = {
    "advise": "advise: journal and notes only; the care runs as it always "
              "has",
    "class": "class: its class seat decides, in shadow",
    "reduce": "reduce: reduce-only steps, under your PIN",
    "trail": "trail: the trail as well, under your PIN",
}
SOURCE_WORDS = {"entry": "the entry's own record",
                "reconstructed": "reconstructed from the row",
                "operator": "yours"}
RECONSTRUCTED_T = ("Reconstructed from the row: it was open before the "
                   "Orcs.")
NO_REASON_T = "The entry recorded no reason."
INVALID_CLOSE = "invalidates on a {tf} close {side} {price}"
INVALID_BOS = "invalidates on a displaced break against it on the {tf}"
INVALID_TIME = "invalidates after {h} market hours without {r}"
INVALID_MET = " (met {hhmm} UTC)"
INVALID_UNCHECKED = " (unchecked: no fresh {tf} bars)"
INVALID_UNCHECKED_TIME = " (unchecked: the care measures no best excursion)"
NO_INVALIDATION = "no invalidation is written"
PLAN_NONE = "No plan yet: Orcs write plans once they reason."
PLAN_SHORT = "no plan yet"
RISK = "risk {r:.1f}R of {cap:g}R"
RISK_NO_R = "no R: the position opened with no stop"
RISK_NO_STOP = "no stop at the venue: the risk is not capped"
COMPARE = ("The position {orc} and the care ghost {care} so far; the Orc "
           "has taken no step.")
COMPARE_NONE = "Not measured yet: the arms have not stepped."
NEXT_WAKE_T = "Next wake {when} UTC: detected and recorded only, no model."
NEXT_WAKE_LATE = ("Next wake overdue since {when} UTC: detected and recorded "
                  "only, no model.")
NEXT_WAKE_NONE = "No wake scheduled: no model is called."
LATEST_NOTE_MAX = 40
RUNG_NONE = "No model (code only)"
SCORE_T = "score {n} · {band}"
INTEGRITY_OK = "The dossier is whole: nothing stale or contradictory."
INTEGRITY_NONE = "Not read yet: no wake has been detected."
DAY_T = "{cls} · score {n}"
VENUE_WORDS = {"paper": "on paper", "demo": "on demo", "live": "real money"}
CORSAIR_T = "Corsair overlay"
INFO_ONLY = "Information only: the choice is yours."


def _f(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _when(at):
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


def hhmm(at) -> str:
    moment = _when(at)
    return DASH if moment is None else moment.strftime("%H:%M")


def day_hhmm(at, now=None) -> str:
    """"14:05" on `now`'s UTC day, "Sat 24 Oct 00:05" on any other: a
    time alone never reads as today when it is not."""
    moment = _when(at)
    if moment is None:
        return DASH
    from django.utils import timezone
    today = _when(now or timezone.now())
    if today is not None and moment.date() == today.date():
        return moment.strftime("%H:%M")
    return moment.strftime("%a %d %b %H:%M")


def next_wake_t(due, now=None) -> str:
    """The next metronome in words: its day when it is not today, and
    "overdue since" when it has passed (a shut market runs no tick)."""
    moment = _when(due) if due else None
    if moment is None:
        return NEXT_WAKE_NONE
    from django.utils import timezone
    now = _when(now or timezone.now())
    words = NEXT_WAKE_LATE if now is not None and moment < now \
        else NEXT_WAKE_T
    return words.format(when=day_hhmm(moment, now))


def r_words(r) -> str:
    return DASH if r is None else f"{r:+.2f}R"


def _px(target, value) -> str:
    from core.price_format import format_price
    return format_price(value, getattr(target, "asset_class", ""),
                        getattr(target, "symbol", ""))


# ── the stamp (the one reader outside Morgul's G8) ───────────────────────

def stamped(trades) -> list:
    """The ids of the rows whose own stamp names an idea (metadata["orc"],
    written at the birth, §10.1). Pure: no query."""
    out = []
    for t in trades or ():
        meta = getattr(t, "metadata", None)
        if not isinstance(meta, dict):
            continue
        stamp = meta.get("orc")
        if isinstance(stamp, dict) and stamp.get("idea"):
            pk = getattr(t, "pk", None)
            if pk is not None:
                out.append(pk)
    return out


# ── pure helpers ─────────────────────────────────────────────────────────

#: A row still holds a position, and so a risk and a stop, in these.
OPEN_STATUSES = ("OPEN", "CLOSE_PENDING")


def is_open(trade) -> bool:
    return str(getattr(trade, "status", "") or "") in OPEN_STATUSES


def effective_level(orc) -> int:
    """The level the Orc acts at. 0 in O1: every seat is L0.
    O3/O4a: min(seat level, commission cap, probation cap) (§3.1)."""
    return 0


def held_stop(trade):
    """The stop the venue holds: the fill's echo while it is still in force
    (notifications._held_stop_in_force; 0.0 is eToro's "no stop"), else the
    row's stop (what the venue took, §2.1). None when the row has none."""
    from bot_program.notifications import _held_stop_in_force
    held = _held_stop_in_force(trade)
    if held is not None:
        return float(held)
    return _f(getattr(trade, "stop_loss", None))


def _original_qty(trade):
    meta = getattr(trade, "metadata", None)
    meta = meta if isinstance(meta, dict) else {}
    so = meta.get("scale_out") if isinstance(meta.get("scale_out"),
                                             dict) else {}
    return _f(so.get("original_qty")) or _f(getattr(trade, "qty", None))


def risk_r(trade, *, root=None):
    """The open risk of a leg at the stop the venue holds, in the idea's R
    (§2.1 gross_I: a stop in profit risks 0): q·max(0, d·(e − s)) over the
    root's birth size times |e − initial stop|. None when the idea has no R,
    the venue holds no stop, or the row is closed (no position, no risk)."""
    from bot_program.orcs.facts import initial_stop
    if not is_open(trade):
        return None
    root = root if root is not None else trade
    e0, s0 = _f(getattr(root, "entry_price", None)), initial_stop(root)
    if not e0 or s0 is None:
        return None
    unit = abs(e0 - s0)
    q0 = _original_qty(root)
    if unit <= 0 or not q0:
        return None
    stop = held_stop(trade)
    if stop is None or stop <= 0:
        return None
    entry = _f(getattr(trade, "entry_price", None))
    q = _f(getattr(trade, "qty", None))
    if not entry or not q:
        return None
    d = 1.0 if str(getattr(trade, "side", "")).upper() == "BUY" else -1.0
    return q * max(0.0, d * (entry - stop)) / (q0 * unit)


def risk_line(trade, *, root=None):
    """"risk 0.6R of 2R", or why there is no figure; None for a closed row
    (its stop and size are history, not a risk)."""
    from bot_program.orcs.facts import initial_stop
    if not is_open(trade):
        return None
    root = root if root is not None else trade
    if initial_stop(root) is None:
        return RISK_NO_R
    r = risk_r(trade, root=root)
    if r is None:
        return RISK_NO_STOP
    return RISK.format(r=r, cap=GROSS_MAX_R)


def compare(tracks) -> dict:
    """The O arm (the position itself: no Orc steps in O1) against the care
    ghost so far, from the arms (ghost.compare_line)."""
    from bot_program.orcs.ghost import compare_line
    try:
        got = compare_line(list(tracks or ()))
    except Exception as e:  # noqa: BLE001 — an unread arm is unmeasured
        logger.info("[orcs] the arms could not be compared: %s", e)
        got = {}
    o, c = _f(got.get("orc_r")), _f(got.get("care_r"))
    t = (COMPARE.format(orc=r_words(o), care=r_words(c))
         if o is not None and c is not None else COMPARE_NONE)
    return {"mode": MODE_SHADOW, "orc_r": o, "care_r": c, "t": t}


def _preds(orc) -> list:
    return [p for p in ((orc.thesis or {}).get("invalidation") or [])
            if isinstance(p, dict)]


def invalidation_t(orc, trade=None) -> list:
    """Each predicate of the thesis in words, with its state (§1.4): met
    (and when), unchecked, or nothing while it reads unmet."""
    from bot_program.orcs.predicates import (BOS, CLOSE, DEFAULT_TF, TIME,
                                             key_of)
    from bot_program.orcs.constants import PRED_MET, PRED_UNCHECKED
    target = trade if trade is not None else orc
    states = (orc.seen or {}).get("predicates") or {}
    out = []
    for p in _preds(orc):
        kind = p.get("kind")
        tf = str(p.get("tf") or DEFAULT_TF)
        if kind == CLOSE:
            side = "below" if p.get("side") == "below" else "above"
            text = INVALID_CLOSE.format(tf=tf, side=side,
                                        price=_px(target, p.get("level")))
        elif kind == BOS:
            text = INVALID_BOS.format(tf=tf)
        elif kind == TIME:
            h = _f(p.get("market_h"))
            r = _f(p.get("min_mfe_r"))
            text = INVALID_TIME.format(
                h=f"{h:g}" if h is not None else DASH,
                r=f"{r:+g}R" if r is not None else "an R")
        else:
            continue
        st = states.get(key_of(p)) if isinstance(states, dict) else None
        st = st if isinstance(st, dict) else {}
        if st.get("state") == PRED_MET:
            text += INVALID_MET.format(hhmm=hhmm(st.get("at")))
        elif st.get("state") == PRED_UNCHECKED:
            text += (INVALID_UNCHECKED_TIME if kind == TIME
                     else INVALID_UNCHECKED.format(tf=tf))
        out.append(text)
    return out


def _thesis(orc, card, trade) -> dict:
    mine = card.get("thesis_operator") if isinstance(
        card.get("thesis_operator"), dict) else None
    inval = invalidation_t(orc, trade)
    if mine and mine.get("t"):
        return {"source": "operator", "source_t": SOURCE_WORDS["operator"],
                "t": str(mine["t"]), "at": mine.get("at"),
                "invalidation_t": inval}
    th = orc.thesis if isinstance(orc.thesis, dict) else {}
    source = "reconstructed" if th.get("source") == "reconstructed" \
        else "entry"
    reason = " ".join(str(th.get("reason") or "").split())
    if source == "reconstructed":
        t = RECONSTRUCTED_T + (f" {reason}" if reason else "")
    else:
        t = reason or NO_REASON_T
    return {"source": source, "source_t": SOURCE_WORDS[source], "t": t,
            "at": None, "invalidation_t": inval}


def _intellect(card):
    it = card.get("intellect")
    if not isinstance(it, dict):
        return None
    score = _f(it.get("score_v"))
    band = str(it.get("band") or "")
    return {"score_v": None if score is None else int(round(score)),
            "score_t": (SCORE_T.format(n=int(round(score)), band=band)
                        if score is not None else DASH),
            "band": band, "day_class": str(it.get("day_class") or ""),
            "rung_t": RUNG_NONE, "escalated": False, "late": False,
            "at": it.get("at")}


def _integrity(card):
    it = card.get("integrity")
    if not isinstance(it, dict):
        return None
    flag = str(it.get("flag") or "ok")
    if flag == "ok":
        return {"flag": flag, "t": INTEGRITY_OK}
    words = str(it.get("t") or flag).strip()
    if words.startswith(f"{flag}:"):
        words = words[len(flag) + 1:].strip()
    return {"flag": flag, "t": f"{flag.capitalize()}: {words.rstrip('.')}."}


def army_words(orc) -> dict:
    from bot_program.orcs.army import name_of
    why = orc.army_why if isinstance(orc.army_why, dict) else {}
    overlay = str(why.get("overlay") or "")
    base_t = name_of(orc.army_type) if orc.army_type else DASH
    return {"type": str(orc.army_type or ""),
            "type_t": base_t + (f" · {CORSAIR_T}" if overlay else ""),
            "overlay": overlay,
            "overlay_t": "; ".join(str(w) for w in
                                   why.get("overlay_why") or []
                                   if str(w or "").strip())}


def _lineage(orc, level) -> dict:
    seat = getattr(orc, "seat", None)
    stats = (seat.stats if seat is not None and isinstance(seat.stats, dict)
             else {})
    try:
        n = int(stats.get("n") or 0)
    except (TypeError, ValueError):
        n = 0
    venue = str(getattr(seat, "venue", "") or "")
    return {"rank": level, "rank_t": f"{ranks.name(level)} · n {n}",
            "badge": ranks.badge(level), "earned_level": level,
            "white_hand": False,
            "provisional_t": f"n {n} of {RANK_GATE_N}",
            "venue_t": VENUE_WORDS.get(venue, DASH), "probation_t": "",
            "scars": [], "breaches_t": "", "disbanded": False}


def _journal(card) -> list:
    out = []
    for j in card.get("journal") or []:
        if not isinstance(j, dict):
            continue
        out.append({"at": str(j.get("at") or ""),
                    "kind": str(j.get("kind") or ""),
                    "author": str(j.get("author") or ""),
                    "t": str(j.get("t") or ""), "mode": MODE_SHADOW})
    return out


def _drums(card) -> list:
    return [{"kind_t": str(d.get("kind_t") or "a drum"),
             "from_symbol": str(d.get("from_symbol") or ""),
             "at": str(d.get("at") or "")}
            for d in card.get("drums") or [] if isinstance(d, dict)]


def plan_line(orc) -> str:
    """The plan in one line. O1: no Orc writes a plan.
    O2: the model's plan, rendered by code (prices through format_price)."""
    return PLAN_NONE


def slot(orc, *, trade=None, root=None, tracks=(), now=None) -> dict:
    """The Horde's seat.orc for one idea (§9.5, the O1 keys). `trade` is
    the row the seat shows (its risk), `root` the idea's root row when it
    differs; `tracks` its care ghost and O arm. No query: `orc.seat` is
    expected selected."""
    card = orc.card if isinstance(orc.card, dict) else {}
    level = effective_level(orc)
    due = getattr(orc, "next_wake_due", None)
    if now is None:
        from django.utils import timezone
        now = timezone.now()
    return _plain_voice({
        "v": SLOT_V, "mode": MODE_SHADOW, "id": orc.pk, "label": orc.label,
        "state": orc.state,
        "state_t": STATE_WORDS.get(orc.state, str(orc.state or "")),
        "authority": {"level": level, "level_t": ranks.level_t(level),
                      "commission": orc.commission,
                      "commission_t": COMMISSION_WORDS.get(
                          orc.commission, str(orc.commission or "")),
                      "stood_down": bool(orc.stood_down),
                      "care_owned_reason": str(orc.care_owned_reason or "")},
        "thesis": _thesis(orc, card, root if root is not None else trade),
        "plan_line": plan_line(orc),
        "latest_note": str(orc.latest_note or ""),
        "latest_note_at": (_iso(orc.latest_note_at)
                           if orc.latest_note_at else None),
        "risk_line": (risk_line(trade, root=root) if trade is not None
                      else None),
        "care_compare": compare(tracks),
        "next_wake_at": _iso(due) if due else None,
        "next_wake_t": next_wake_t(due, now),
        "journal": _journal(card),
        "intents": [],
        "intellect": _intellect(card),
        "lineage": _lineage(orc, level),
        "integrity": _integrity(card),
        "army": army_words(orc),
        "drums": _drums(card),
        "page": f"/orcs/{orc.root_trade_id}/",
    }, trade if trade is not None else root)


def _plain_voice(sl, trade) -> dict:
    """PR68's plain words on the operator's own words in a slot: his
    thesis (source "operator") and his thesis entries in the journal
    (kind KIND_THESIS by AUTHOR_OPERATOR, both) are kept as written, or
    withheld whole when they name an exception or may name an amount of
    money, read against the row's own amounts by value
    (bot_program/orcs/plain.py). Every surface reads the slot, so the
    Horde, /orc on Telegram, the positions line and the close note say
    the same. A fact code writes under his name (a hand edit's) is code's,
    never touched here. No query; `sl` is the slot just built."""
    th = sl.get("thesis") if isinstance(sl.get("thesis"), dict) else {}
    mine = th.get("source") == "operator" and bool(th.get("t"))
    lines = [j for j in sl.get("journal") or []
             if j.get("author") == AUTHOR_OPERATOR
             and j.get("kind") == KIND_THESIS and j.get("t")]
    if not mine and not lines:
        return sl
    from bot_program.orcs.plain import row_marks, voice
    marks = row_marks(trade)
    if mine:
        th["t"] = voice(th["t"], marks)
    for j in lines:
        j["t"] = voice(j["t"], marks)
    return sl


def _first_invalidation(sl) -> str:
    inval = (sl.get("thesis") or {}).get("invalidation_t") or []
    return inval[0] if inval else NO_INVALIDATION


def _note_short(sl) -> str:
    """The latest note quoted, cut at LATEST_NOTE_MAX, with its time:
    '"Nothing new: +0.4R, care BE at 1.0832…" 14:05'; "" for none."""
    note = " ".join(str(sl.get("latest_note") or "").split())
    if not note:
        return ""
    if len(note) <= LATEST_NOTE_MAX:
        cut = note
    else:
        # at a word, never inside a price
        head = note[:LATEST_NOTE_MAX + 1]
        head = head.rsplit(" ", 1)[0] if " " in head else head
        cut = head[:LATEST_NOTE_MAX].rstrip(" ,;:") + "…"
    return f'"{cut}" {hhmm(sl.get("latest_note_at"))}'


def line(sl) -> str:
    """The positions page's line under the symbol (§9.2): the rank and the
    commission, the first invalidation, the plan, the latest note and its
    time, the risk:
    'Orc #12 · L0 · Snaga, class · invalidates on a 4h close below 98.00 ·
    no plan yet · "Nothing new: +0.4R…" 14:05 · risk 1.0R of 2R'."""
    auth = sl.get("authority") or {}
    rank = str(auth.get("level_t") or "")
    commission = str(auth.get("commission") or "")
    if rank and commission:
        rank = f"{rank}, {commission}"
    parts = [sl.get("label") or "", rank, _first_invalidation(sl),
             PLAN_SHORT, _note_short(sl), sl.get("risk_line") or ""]
    return " · ".join(p for p in parts if p)


def _j_line(j) -> str:
    return f"{hhmm(j.get('at'))} {j.get('author') or ''}: {j.get('t') or ''}"


def line_dict(sl) -> dict:
    """What the positions row carries: the line, the page, and the dwell
    card's plan, comparison and last three entries (newest first)."""
    js = list(reversed(sl.get("journal") or []))[:3]
    out = {"label": sl.get("label") or "", "line": line(sl),
           "page": sl.get("page") or "", "plan": sl.get("plan_line") or "",
           "compare": (sl.get("care_compare") or {}).get("t") or ""}
    for i in range(3):
        out[f"j{i + 1}"] = _j_line(js[i]) if i < len(js) else ""
    return out


def last_fact(journal_lines):
    """The newest card line written by code, never the operator's own
    words (his thesis is his text, not a fact: no F-id). None for none."""
    for j in reversed(list(journal_lines or ())):
        if isinstance(j, dict) and j.get("author") != AUTHOR_OPERATOR \
                and str(j.get("t") or "").strip():
            return j
    return None


def _sentence(text) -> str:
    t = str(text or "").strip()
    return t + "." if t and t[-1] not in ".!?…" else t


def close_note(sl) -> dict:
    """The close dialog's note, beside the early-close warning: the Orc's
    rank, state, plan, thesis, latest note and last fact. Information
    only."""
    level_t = (sl.get("authority") or {}).get("level_t") or ""
    short = STATE_SHORT.get(sl.get("state"), str(sl.get("state") or ""))
    th = sl.get("thesis") or {}
    inval = th.get("invalidation_t") or []
    parts = [f"{level_t}, {short}: {PLAN_SHORT}.",
             f"Thesis: {th.get('source_t') or DASH}"
             + (f"; it {inval[0]}." if inval else ".")]
    note = " ".join(str(sl.get("latest_note") or "").split())
    if note:
        parts.append(f"Latest note {hhmm(sl.get('latest_note_at'))} UTC: "
                     f"{_sentence(note)}")
    last = last_fact(sl.get("journal"))
    if last is not None:
        parts.append(f"Last fact {hhmm(last.get('at'))} UTC: "
                     f"{_sentence(last.get('t'))}")
    parts.append(INFO_ONLY)
    return {"label": sl.get("label") or "", "t": " ".join(parts),
            "page": sl.get("page") or ""}


# ── the bulk reads ───────────────────────────────────────────────────────

def _as_dict(trades) -> dict:
    if isinstance(trades, dict):
        return {k: v for k, v in trades.items() if v is not None}
    return {getattr(t, "pk", None): t for t in trades or ()
            if getattr(t, "pk", None) is not None}


def for_rows(trade_ids, *, user=None, trades=None, now=None) -> dict:
    """{"bot:<trade id>": slot} for every row of `trade_ids` that is a leg
    of an idea (any leg resolves to its idea, §1.1), scoped to `user` when
    given. Two queries whatever the number of rows: the legs with their
    Orc, its seat and the row; the care ghost and the O arm of those
    ideas. `trades` ({id: row} or rows) are used in place of the rows read
    (the caller's, already marked). O2: a third, the lineages' scars and
    breaches. O5: an idea's risk sums its open legs."""
    ids = set()
    for i in trade_ids or ():
        try:
            ids.add(int(i))
        except (TypeError, ValueError):
            continue
    if not ids:
        return {}
    from bot_program.orcs.models import OrcLeg, OrcTrack
    qs = (OrcLeg.objects.filter(trade_id__in=sorted(ids))
          .select_related("orc", "orc__seat", "trade"))
    if user is not None:
        qs = qs.filter(orc__user=user)
    legs = list(qs)
    if not legs:
        return {}
    given = _as_dict(trades)
    orcs, by_orc = {}, {}
    for leg in legs:
        orcs[leg.orc_id] = leg.orc
        by_orc.setdefault(leg.orc_id, []).append(leg)
    tracks = {}
    for t in OrcTrack.objects.filter(orc_id__in=list(orcs),
                                     arm__in=(ARM_CARE, ARM_ORC)):
        tracks.setdefault(t.orc_id, []).append(t)
    out = {}
    for oid, orc in orcs.items():
        rows = {leg.trade_id: given.get(leg.trade_id) or leg.trade
                for leg in by_orc[oid]}
        root = rows.get(orc.root_trade_id)
        for leg in by_orc[oid]:
            out[f"bot:{leg.trade_id}"] = slot(
                orc, trade=rows[leg.trade_id], root=root,
                tracks=tracks.get(oid, ()), now=now)
    return out


def for_trades(trades, *, user) -> dict:
    """{trade id: slot} for the stamped rows of `trades` while the switch is
    ON: no query at all when no row carries a stamp, one for the switch,
    two for the rows (for_rows)."""
    trades = [t for t in trades or () if t is not None]
    ids = stamped(trades)
    if not ids:
        return {}
    from bot_program.orcs.switches import orcs_on
    if not orcs_on():
        return {}
    rows = for_rows(ids, user=user, trades=trades)
    return {int(k.split(":", 1)[1]): v for k, v in rows.items()}


def close_note_for(trade, *, user):
    """The close dialog's note for `trade`, or None (no stamp, the switch
    OFF, no idea of this user's)."""
    sl = for_trades([trade], user=user).get(getattr(trade, "pk", None))
    return close_note(sl) if sl else None


def for_classes(user, classes, *, now=None) -> dict:
    """{class: {"day": {...}}}: the day's weather per class band (§7.5.3),
    one query. No `label` key: no Captain is seated before O2.
    O2: the Captain, its orders, the open waves, the fallen and the
    Emperor's line."""
    classes = sorted({str(c) for c in classes or () if c})
    if not classes or user is None:
        return {}
    from django.utils import timezone

    from bot_program.orcs.models import OrcDayBaseline
    from bot_program.orcs.sessions import trading_day
    td = trading_day(now or timezone.now())
    out = {}
    for row in OrcDayBaseline.objects.filter(
            user=user, asset_class__in=classes, trading_day=td):
        score = _f(row.score)
        n = DASH if score is None else f"{score:.0f}"
        out[row.asset_class] = {"day": {
            "class": str(row.day_class or ""),
            "score_t": f"score {n}",
            "t": DAY_T.format(cls=str(row.day_class or DASH), n=n)}}
    return out


# ── the reserved words (the Horde's walk, horde §12.9) ───────────────────

def _army_names() -> tuple:
    from bot_program.orcs.army import ARMY_TYPES
    return tuple(t.name for t in ARMY_TYPES.values())


RESERVED_SENTENCES = frozenset({PLAN_NONE, RECONSTRUCTED_T, COMPARE_NONE,
                                NEXT_WAKE_NONE, INTEGRITY_NONE})
RESERVED_PATTERNS = (
    re.compile(r"^Orc #\d+$"),
    re.compile(r"^Open Orc #\d+ ›$"),
    re.compile(r"^The position [+−-]?\d+\.\d\dR and the care ghost "
               r"[+−-]?\d+\.\d\dR so far; the Orc has taken no step\.$"),
    re.compile(r"^(Line Orcs|Mercenaries|Olog-hai|Uruk-hai|Corsairs of "
               r"Umbar)( · Corsair overlay)?$"),
)


def is_reserved(sentence) -> bool:
    s = str(sentence or "").strip()
    return s in RESERVED_SENTENCES or any(p.match(s)
                                          for p in RESERVED_PATTERNS)
