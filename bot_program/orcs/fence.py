"""THE FENCE (spec §5.2a "The fence against prompt injection", §1.5 article
IX): pure. Text written by others enters the dossier only through here.

  T0    code facts: F-ids, and DR-ids whose trigger is a price, a stop, a
        fill, a lock or a predicate; they may justify an action, within
        the relevance set of its kind (V10)
  T1    platform model prose (the Mind's narrative, the strategist's
        outlook, the reviewer's reasoning, the debate's words, an Orc's
        earlier note, a lesson): inside <view source=...>, labelled
        "may be wrong; facts win"
  T2/N  third-party text and what derives from it (headlines, calendar
        titles, the news_shock drum): inside <untrusted kind=... id=N...>;
        never justifies a binding action

`sanitize` folds the text to plain ASCII (NFKC first), strips control,
zero-width and bidi characters, `< > \` { }` and URLs, collapses the
whitespace and caps it. `quarantine` withholds instruction-like text
whole: role words, "ignore ... previous", "you are now", a closing tag,
JSON that looks like an action. No news body and no analyst's summary
(model text laundered from an untrusted body) ever reaches this module:
the readers never load them (bot_program/orcs/sources.py).

# O2: the validator enforces v10_satisfied on every binding non-hold
# action; O1 ships the table (constants.V10_RELEVANCE) and the check.
"""
import re
import unicodedata

from bot_program.orcs.constants import FENCE_CAPS, V10_RELEVANCE

WITHHELD = "[withheld: instruction-like text]"
VIEW_NOTE = "may be wrong; facts win"
#: Every kind a fact maps to (fact_kind). "army" and "arm" never satisfy
#: V10: they are facts about the Orc, not the market.
FACT_KINDS = ("bar", "structure", "predicate", "care", "hand", "calendar",
              "gap", "venue", "review", "arm", "drum", "level_reached",
              "army")

_ZW_BIDI = re.compile("[­​-‏‪-‮⁠-⁩"
                      "﻿]")
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_URL = re.compile(r"(?:https?://|ftp://|www\.)\S+", re.I)
_STRIP = {ord(c): None for c in "<>`{}"}
_INSTRUCTION = (
    re.compile(r"\bignore\b.{0,60}?\b(previous|prior|above|earlier|all)\b",
               re.I | re.S),
    re.compile(r"\b(disregard|forget|override)\b.{0,40}?"
               r"\b(instructions?|rules?|previous|above|prompt)\b",
               re.I | re.S),
    re.compile(r"\byou\s+are\s+now\b", re.I),
    re.compile(r"\bnew\s+instructions?\b", re.I),
    re.compile(r"(^|[^\w])(system|assistant|developer)\s*:", re.I),
    re.compile(r"\[/?(inst|sys)\]", re.I),
    re.compile(r"<\s*/\s*[a-z_][\w-]*\s*>", re.I),
    re.compile(r"<\s*/?\s*(untrusted|view|system|instructions?|prompt)\b",
               re.I),
    re.compile(r"\{[^{}]*[\"']?(action|candidate|level_id|facts_cited|"
               r"risk_share)[\"']?\s*:", re.I),
)


def sanitize(text, cap) -> str:
    """Plain ASCII, no markup, no link, one space between words, at most
    `cap` characters (a cut ends in "...")."""
    s = unicodedata.normalize("NFKC", str(text or ""))
    s = _ZW_BIDI.sub("", s)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore") \
        .decode("ascii")
    s = _CONTROL.sub(" ", s)
    s = _URL.sub(" ", s)
    s = s.translate(_STRIP)
    s = " ".join(s.split())
    cap = int(cap or 0)
    if cap > 0 and len(s) > cap:
        s = s[:max(0, cap - 3)].rstrip() + "..."
        s = s[:cap]
    return s


def quarantine(text) -> tuple:
    """(text, withheld): instruction-like text is withheld WHOLE. Read on
    the raw text, so a closing tag is seen before sanitising strips it."""
    raw = str(text or "")
    folded = unicodedata.normalize("NFKC", raw)
    folded = _ZW_BIDI.sub("", folded)
    for pattern in _INSTRUCTION:
        if pattern.search(folded):
            return WITHHELD, True
    return raw, False


def _content(text, cap) -> tuple:
    q, withheld = quarantine(text)
    return (WITHHELD if withheld else sanitize(q, cap)), withheld


def untrusted(kind, nid, text, cap=None) -> str:
    """Third-party text (T2/N) in its envelope."""
    body, _w = _content(text, cap or FENCE_CAPS.get(kind, 120))
    return (f'<untrusted kind="{sanitize(kind, 32)}" '
            f'id="{sanitize(nid, 16)}">{body}</untrusted>')


def view(source, text, cap=None) -> str:
    """Platform model prose (T1) in its labelled envelope."""
    body, _w = _content(text, cap or FENCE_CAPS.get(source, 280))
    return (f'<view source="{sanitize(source, 32)}" note="{VIEW_NOTE}">'
            f"{body}</view>")


def withheld_in(text) -> bool:
    return WITHHELD in str(text or "")


# ── the facts' kinds and bands ──────────────────────────────────────────

def fact_kind(entry) -> str:
    """The kind of a journal fact (an OrcJournal or a dict with kind,
    author and body): body["fk"] first (O1c's own facts carry it), else
    read from the body keys the O1a and O1b producers write
    (bot_program/orcs/facts.py, predicates.py, ghost.py, grading.py,
    birth.py, lifecycle.py)."""
    get = (entry.get if isinstance(entry, dict)
           else lambda k, d=None: getattr(entry, k, d))
    body = get("body") or {}
    body = body if isinstance(body, dict) else {}
    author = str(get("author") or "")
    if body.get("fk") in FACT_KINDS:
        return str(body["fk"])
    if str(get("kind") or "") == "drum":
        return "drum"
    if "predicate" in body:
        return "predicate"
    if "arm" in body or "faithfulness" in body:
        return "arm"
    if "army" in body or "overlay" in body:
        return "army"
    if "menu" in body:
        return "structure"
    if "review" in body:
        return "review"
    if "verdict" in body:
        return "structure"
    if "title" in body:
        return "calendar"
    if author == "operator":
        return "hand"
    if "sent" in body or ("why" in body and "price" in body):
        return "care"
    if author == "care" and ("level" in body or "r" in body):
        return "care"
    return "venue"


def band_of(fact_id, facts_index=None) -> str:
    """T0 for a code fact (F-n) or a drum (DR-n) whose trigger is a price;
    N for third-party text and the news_shock drum; T1 for a view (V-n)."""
    fid = str(fact_id or "")
    if fid.startswith("DR"):
        info = (facts_index or {}).get(fid) or {}
        return "N" if info.get("drum_kind") == "news_shock" else "T0"
    if re.fullmatch(r"F\d+", fid):
        return "T0"
    if fid.startswith("N"):
        return "N"
    return "T1"


def v10_satisfied(action_kind, cited_ids, facts_index, symbol, *, event=None,
                  since=None) -> tuple:
    """(ok, why): does the action cite at least one T0 fact from the
    relevance set fixed for its kind (V10)? `facts_index`: {id: {kind,
    symbol, at, event?, drum_kind?}}. A hold needs nothing; a plan accepts
    any T0 fact newer than `since` (its current version)."""
    kind = "plan" if action_kind in ("plan", "revise_plan") \
        else str(action_kind or "")
    if kind in ("hold", "note"):
        return True, "a hold needs no fact"
    rule = V10_RELEVANCE.get(kind)
    if rule is None:
        return False, f"no relevance set for {kind!r}"
    index = facts_index or {}
    for fid in cited_ids or ():
        if band_of(fid, index) != "T0":
            continue
        info = index.get(fid) or {}
        fk = str(info.get("kind") or "")
        if rule.get("kinds") != "any" and fk not in rule["kinds"]:
            continue
        if rule.get("symbol") and str(info.get("symbol") or "") != \
                str(symbol or ""):
            continue
        if rule.get("event") and event and str(info.get("event") or "") \
                != str(event):
            continue
        if rule.get("newer") and since and str(info.get("at") or "") \
                <= str(since):
            continue
        return True, f"{fid} ({fk}) is in the relevance set of {kind}"
    want = rule.get("kinds")
    want = "any newer fact" if want == "any" else ", ".join(want)
    return False, (f"{kind} cites no T0 fact of its set ({want}"
                   f"{' on ' + str(symbol) if rule.get('symbol') else ''}): "
                   f"advisory to the phone")
