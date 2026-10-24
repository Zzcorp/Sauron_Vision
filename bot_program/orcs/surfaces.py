"""THE ORCS ON TELEGRAM (spec §9.1, O1d): /orc and /orcs on the operator's
own Eye chat (bot_program/telegram_eye.py), answered by code from the Orc
tables. No model, no write, no notification: a reply is built here and
the Eye sends it to the chat that asked, after its commit, as it sends
every other reply. Never the alarm group (bot_program/alarm.py does not
know these commands).

    /orc NUMBER       one Orc: its rank, state, R and stops (or, once its
                      row is closed, where it closed and the R booked),
                      thesis, plan, latest note, last fact (never the
                      operator's own words), next wake, the care beside
                      it, its army
    /orcs [CLASS]     every Orc on watch, one line each (20 at most)

NUMBER is the Orc's number, its idea's root trade, or any of its legs.
In O1 an Orc reasons about nothing, so the commands that would make one
act answer in words and change nothing: "/orc N <question>" (O2 answers
it), "/orc N stand down" and "/orcs off" (O4a gives them their write).

Every reply carries R and prices only: never a balance, an amount, a
quantity or an account figure. The operator's own thesis is shown as he
wrote it, or withheld whole when it may name an amount or names an
exception (PR68's plain words, applied once in notes.slot). The stops
line names the row's own venue (eToro, OANDA practice, Saxo
simulation...), never eToro for every seat.
"""
import re

#: The mark of the Orcs' messages (notifications.NOTIFY_MARKS
#: "orc_adopted").
MARK_ORC = "\U0001F4DC"

NO_NUMBER = "Give the Orc's number, as /orcs lists it: /orc <number>."
NOT_FOUND = "No Orc numbered {n} in your book: /orcs lists them."
QUESTION_LATER = ("Orcs do not answer questions yet: none calls a model. "
                  "Ask Sauron instead: /q <question>.")
STAND_DOWN_NONE = ("Nothing to stand down: {label} watches only ({level}); "
                   "the care holds your position.")
ORCS_OFF_NONE = ("Nothing to switch off: no Orc acts on a position; each "
                 "keeps a journal only, and the care holds every position.")
ORCS_HEAD = "Orcs on watch: {n} ({real} real money · {sim} simulated)"
ORCS_NONE = ("No Orc is on watch. Each open position gets one within 5 "
             "minutes.")
UNKNOWN_CLASS = "No class named {word}. Classes: {names}."
MODEL_CALLS = "Model calls today: 0"
HELP_LINES = ("/orc NUMBER — one Orc: its thesis, journal and the care "
              "beside it (no model)",
              "/orcs [CLASS] — every Orc on watch, one line each")

_DIGITS = re.compile(r"[0-9]{1,18}")
_SLASH = re.compile(r"^/(orcs?)(?:@\S+)?(?:\s|$)", re.I)
_QUOTED = re.compile(r"^(orcs?)(?:\s|$)", re.I)
#: The Eye's quotes (telegram_eye._OPEN_QUOTES, _CLOSE_QUOTES).
_OPEN_QUOTES = "\"“«„"
_CLOSE_QUOTES = "\"”»“"


# ── what was said (pure) ─────────────────────────────────────────────────

def _inner(raw: str):
    if len(raw) > 2 and raw[0] in _OPEN_QUOTES and raw[-1] in _CLOSE_QUOTES:
        return raw[1:-1].strip()
    return None


def names_orcs(text) -> bool:
    """True when `text` is addressed to the Orcs: "/orc ...", "/orcs ...",
    or a quoted "orc ..." / "orcs ...". Pure, no query: the Eye reads the
    switch only for these."""
    raw = str(text or "").strip()
    if _SLASH.match(raw):
        return True
    inner = _inner(raw)
    return bool(inner and _QUOTED.match(inner))


def parse_quoted(inner):
    """("orc" | "orcs", argument) for a quoted command: "orc 12" (a number
    first), "orcs", "orcs forex" (one class word) or "orcs off"; None for
    anything else, so a quoted question that merely starts with the word
    ("orcs are slow today?") still goes to Sauron as a question."""
    text = str(inner or "").strip()
    m = _QUOTED.match(text)
    if m is None:
        return None
    word = m.group(1).lower()
    arg = text[len(word):].strip()
    tokens = arg.split()
    if word == "orc":
        return (word, arg) if tokens and _number(tokens[0]) is not None \
            else None
    if not tokens:
        return word, ""
    if len(tokens) == 1 and (tokens[0].lower() == "off"
                             or _class_of(tokens[0])):
        return word, arg
    return None


def help_lines() -> list:
    return list(HELP_LINES)


# ── the reads ────────────────────────────────────────────────────────────

def _number(token):
    """An Orc's number: ASCII digits only. str.isdigit() also accepts "²"
    and "①", which int() refuses: never a ValueError out of a parse."""
    text = str(token or "").strip().lstrip("#")
    return int(text) if _DIGITS.fullmatch(text) else None


def resolve(user, n):
    """The user's Orc numbered `n`: its root trade's id, or any of its
    legs' (§1.1). One query. None when the number is not an Orc of this
    user's."""
    from django.db.models import Q

    from bot_program.orcs.models import Orc
    try:
        n = int(n)
    except (TypeError, ValueError):
        return None
    return (Orc.objects.select_related("seat", "root_trade", "grade")
            .filter(user=user)
            .filter(Q(root_trade_id=n) | Q(legs__trade_id=n))
            .distinct().first())


def _tracks(orc_ids) -> dict:
    from bot_program.orcs.constants import ARM_CARE, ARM_ORC
    from bot_program.orcs.models import OrcTrack
    out = {}
    for t in OrcTrack.objects.filter(orc_id__in=list(orc_ids),
                                     arm__in=(ARM_CARE, ARM_ORC)):
        out.setdefault(t.orc_id, []).append(t)
    return out


def _world(orc) -> str:
    from bot_program.telegram_eye import WORLD_LINE_WORDS
    venue = str(getattr(orc.seat, "venue", "") or "")
    return WORLD_LINE_WORDS.get(venue, "paper" if orc.paper else
                                "REAL MONEY")


def _side(orc) -> str:
    return "long" if str(orc.side).upper() == "BUY" else "short"


def _f(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


# ── /orc N ───────────────────────────────────────────────────────────────

def _carrier(orc, trade) -> str:
    """The venue that holds the row's stop, by the row's own carrier stamp
    (metadata["broker"], asset_engine.base venue_stamps), in the
    positions page's words: "eToro", "OANDA practice", "Saxo
    simulation"; "the venue" when the row never named one."""
    from dashboard.position_summary import BROKER_NAMES, DEMO_NAMES
    meta = trade.metadata if isinstance(trade.metadata, dict) else {}
    key = str(meta.get("broker") or "").strip().lower()
    names = (DEMO_NAMES if str(getattr(orc.seat, "venue", "")) == "demo"
             else BROKER_NAMES)
    return names.get(key) or "the venue"


def _stops_line(orc, trade) -> str:
    from bot_program.orcs import notes
    from bot_program.telegram_eye import level
    # a real or a demo seat: the stop rests at the row's own venue
    at_venue = str(getattr(orc.seat, "venue", "")) in ("live", "demo")
    held = notes.held_stop(trade)
    if at_venue:
        carrier = _carrier(orc, trade)
        first = (f"{carrier} holds no stop" if held is None or held <= 0
                 else f"{carrier} holds {level(held, trade)}")
    else:
        first = ("the row holds no stop" if held is None or held <= 0
                 else f"the row's stop {level(held, trade)}")
    meta = trade.metadata if isinstance(trade.metadata, dict) else {}
    care = meta.get("care") if isinstance(meta.get("care"), dict) else {}
    out = f"Stops: {first}"
    if care.get("soft_stop") is not None:
        why = str(care.get("soft_why") or "").strip()
        out += (f" · the care's soft stop {level(care['soft_stop'], trade)}"
                + (f" ({why})" if why else ""))
    return out


def _r_line(trade) -> str:
    from bot_program.orcs.notes import r_words
    meta = trade.metadata if isinstance(trade.metadata, dict) else {}
    care = meta.get("care") if isinstance(meta.get("care"), dict) else {}
    return (f"R at the last tick {r_words(_f(care.get('r_now')))} · best "
            f"{r_words(_f(care.get('mfe_r')))}")


def _closed_line(trade) -> str:
    """A row that no longer holds a position: where it closed and the R it
    booked. Never a risk or a resting stop: there is none."""
    from bot_program.orcs.notes import r_words
    from bot_program.telegram_eye import level
    px = _f(getattr(trade, "exit_price", None))
    at = f" at {level(px, trade)}" if px else ""
    r = _f(getattr(trade, "realized_r", None))
    return (f"Position closed{at}: "
            + (f"booked {r_words(r)}." if r is not None
               else "its R is not measured."))


def _grade_line(orc):
    from bot_program.orcs.notes import r_words
    g = getattr(orc, "grade", None)
    if g is None:
        return None
    return (f"Graded: the position {r_words(g.orc_r_gross)}, the care ghost "
            f"{r_words(g.ghost_r)}; Δ against the care "
            f"{r_words(g.delta_care)} (shadow: no Orc acted).")


def orc_card(orc, *, tracks=(), now=None):
    """The /orc reply for one Orc (no query: its seat, root row and grade
    are selected, its arms given)."""
    from bot_program.orcs import notes, ranks
    from bot_program.telegram_eye import BULLET, Reply, _cap, ago
    trade = orc.root_trade
    sl = notes.slot(orc, trade=trade, tracks=tracks, now=now)
    auth = sl["authority"]
    lane = "your ticket" if orc.manual else "bot idea"
    lineage = sl["lineage"]
    th = sl["thesis"]
    lines = [
        f"{_world(orc)} · {lane} · {auth['commission_t']}",
        f"Rank: {auth['level_t']} ({ranks.holds(auth['level'])}) · "
        f"{lineage['provisional_t'].split(' of ')[0]}",
        f"State: {sl['state_t']} Born {ago(orc.born_at, now)}.",
    ]
    if notes.is_open(trade):
        lines += [_r_line(trade), _stops_line(orc, trade)]
    else:
        lines.append(_closed_line(trade))
    lines += [
        f"Thesis: {th['source_t']}"
        + (f": {th['t']}" if th["source"] == "operator" else ""),
    ]
    lines.extend(f"{BULLET}{t}" for t in th["invalidation_t"])
    lines.append(sl["plan_line"])
    if sl["latest_note"]:
        lines.append(f"Latest note: {sl['latest_note']} "
                     f"({ago(orc.latest_note_at, now)})")
    last = notes.last_fact(sl["journal"])
    if last is not None:
        lines.append(f"Last fact {notes.hhmm(last['at'])} UTC: {last['t']}")
    lines.append(sl["next_wake_t"])
    lines.append(sl["care_compare"]["t"])
    lines.append(f"Army: {sl['army']['type_t']}")
    if orc.state == "dead":
        g = _grade_line(orc)
        if g:
            lines.append(g)
    lines.append(MODEL_CALLS)
    lines.append(f"Page: {sl['page']}")
    title = f"{orc.label} — {orc.symbol} {_side(orc)}"
    return Reply(MARK_ORC, title, _cap(lines))


def orc_reply(user, arg, *, now=None):
    from bot_program.orcs import ranks
    from bot_program.orcs.notes import effective_level
    from bot_program.telegram_eye import Reply, _fold
    tokens = str(arg or "").split()
    n = _number(tokens[0]) if tokens else None
    if n is None:
        return Reply(MARK_ORC, "Sauron — which Orc?", [NO_NUMBER])
    orc = resolve(user, n)
    if orc is None:
        return Reply(MARK_ORC, "Sauron — no such Orc",
                     [NOT_FOUND.format(n=n)])
    rest = _fold(" ".join(tokens[1:]))
    if rest in ("stand down", "standdown"):
        return Reply(MARK_ORC, f"{orc.label} — nothing to stand down", [
            STAND_DOWN_NONE.format(
                label=orc.label,
                level=ranks.level_t(effective_level(orc)))])
    if rest:
        return Reply(MARK_ORC, f"{orc.label} — no answers yet",
                     [QUESTION_LATER])
    return orc_card(orc, tracks=_tracks([orc.pk]).get(orc.pk, ()), now=now)


# ── /orcs [CLASS] ────────────────────────────────────────────────────────

def _class_of(word):
    """The asset class a word names ("forex", "Forex", "commodities"), or
    None. "" for no word."""
    from bot_program.telegram_eye import CLASS_WORDS, _fold
    w = _fold(word)
    if not w:
        return ""
    for key, label in CLASS_WORDS.items():
        if w in (key, _fold(label), key + "s"):
            return key
    return None


def orcs_reply(user, arg, *, now=None):
    from bot_program.orcs import notes, ranks
    from bot_program.orcs.constants import STATE_DEAD
    from bot_program.orcs.models import Orc
    from bot_program.telegram_eye import (BULLET, CLASS_WORDS,
                                          MAX_POSITIONS_LISTED, Reply, _cap,
                                          _fold)
    word = _fold(arg)
    if word == "off":
        return Reply(MARK_ORC, "Sauron — nothing to switch off",
                     [ORCS_OFF_NONE])
    cls = _class_of(word)
    if cls is None:
        return Reply(MARK_ORC, "Sauron — which class?", [UNKNOWN_CLASS.format(
            word=str(arg or "").strip()[:40],
            names=", ".join(sorted(k for k in CLASS_WORDS)))])
    qs = (Orc.objects.select_related("seat", "root_trade")
          .filter(user=user).exclude(state=STATE_DEAD)
          .order_by("born_at", "pk"))
    if cls:
        qs = qs.filter(asset_class=cls)
    orcs = list(qs)
    if not orcs:
        return Reply(MARK_ORC, "Sauron — the Orcs", [ORCS_NONE])
    tracks = _tracks([o.pk for o in orcs])
    real = sum(1 for o in orcs if str(o.seat.venue) == "live")
    lines = [ORCS_HEAD.format(n=len(orcs), real=real, sim=len(orcs) - real)]
    for orc in orcs[:MAX_POSITIONS_LISTED]:
        cmp_ = notes.compare(tracks.get(orc.pk, ()))
        level = notes.effective_level(orc)
        lines.append(
            f"{BULLET}{orc.label} {orc.symbol} {_side(orc)} · {_world(orc)} "
            f"· L{level} {ranks.name(level)} · "
            f"{notes.r_words(cmp_['orc_r'])} (care "
            f"{notes.r_words(cmp_['care_r'])}) · "
            f"{notes.army_words(orc)['type_t']}")
    if len(orcs) > MAX_POSITIONS_LISTED:
        lines.append(f"+{len(orcs) - MAX_POSITIONS_LISTED} more on the "
                     f"platform")
    return Reply(MARK_ORC, "Sauron — the Orcs", _cap(lines))
