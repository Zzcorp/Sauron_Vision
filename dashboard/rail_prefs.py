"""The rail's filters and display choices, per user (2026-11-06).

The operator asked for filters and display choices in the bands — for the
signals and for the watchlist, by asset class or otherwise. They are kept
on the operator's profile (portfolio.TraderProfile.rail_prefs), not in a
browser, so every browser and the phone draw the same rail, and base.html
renders them on the hosts' attributes and in <style id="svRuleOff"> so the
first paint is already filtered.

The filters themselves run in the browser (static/js/sv-rail-filters.js,
static/css/sv-rail.css) on facts the server renders on every row; this
module only says what may be stored, and cleans every write against that
whitelist: an unknown key is dropped, an unknown value falls back to its
default, and the muted rules are bounded (MAX_RULES names of at most
MAX_RULE_LEN characters each).

Signals (`sig`):
  cls        the asset classes shown; [] is all
  side       all | long | short
  score      the minimum score band: 0 (any) or 5..9 (0.5..0.9)
  stage      all | votes (the bots count it) | live (a live-venue stage)
  held       all | held | not (the operator holds the instrument or not)
  rules_off  the rules MUTED — a rule that appears later is shown, never
             silently hidden
  sort       new | score | class
  group      group by class
  dense      the compact density
  gone       LEFT THE RAIL shown
  shut_off   the cards whose market is shut now are HIDDEN (2026-11-12);
             off by default: every signal is shown the moment it fires,
             a shut market's with its MARKET SHUT badge
  shut       the MARKET SHUT section shown (the optional market hold,
             the switch signal_market_hold); hidden by default

Watchlist (`watch`): cls, held, sort (class | symbol | held), group, dense.

DISPLAY ONLY: nothing in the engine, the bots, the alerts or the take-trade
path reads these prefs, and no filter writes Instrument.is_watchlist (the
flag that widens the scan universe).
"""
from __future__ import annotations

import json

from core.constants import AssetClass

CLASSES = [key for key, _label in AssetClass.CHOICES]

SIDES = ("all", "long", "short")
SCORES = (0, 5, 6, 7, 8, 9)
STAGES = ("all", "votes", "live")
HELDS = ("all", "held", "not")
SIG_SORTS = ("new", "score", "class")
WATCH_SORTS = ("class", "symbol", "held")
MAX_RULES = 100
MAX_RULE_LEN = 100

SIG_DEFAULT = {"cls": [], "side": "all", "score": 0, "stage": "all",
               "held": "all", "rules_off": [], "sort": "new", "group": False,
               "dense": False, "gone": False, "shut_off": False,
               "shut": False}
WATCH_DEFAULT = {"cls": [], "held": "all", "sort": "class", "group": False,
                 "dense": False}


def _bool(value, default=False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value == 1
    if isinstance(value, str) and value.strip().lower() in ("1", "true", "on", "yes"):
        return True
    if isinstance(value, str) and value.strip().lower() in ("0", "false", "off", "no", ""):
        return False
    return default


def _classes(value) -> list:
    if not isinstance(value, (list, tuple)):
        return []
    out = []
    for v in value:
        if isinstance(v, str) and v in CLASSES and v not in out:
            out.append(v)
    return out


def _rules(value) -> list:
    """The muted rules, deduped and bounded. The empty name is a rule too:
    the signals that name none, muted by the "(no rule)" toggle (its key is
    "r-none", dashboard.signal_rail.rule_key) — 2026-11-06, the review."""
    if not isinstance(value, (list, tuple)):
        return []
    out = []
    for v in value:
        if not isinstance(v, str):
            continue
        name = v.strip()
        if len(name) > MAX_RULE_LEN or name in out:
            continue
        out.append(name)
        if len(out) >= MAX_RULES:
            break
    return out


def _choice(value, allowed, default):
    return value if isinstance(value, str) and value in allowed else default


def _score(value) -> int:
    try:
        n = int(str(value).strip())
    except (TypeError, ValueError):
        return 0
    return n if n in SCORES else 0


def _sig(raw) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    return {
        "cls": _classes(raw.get("cls")),
        "side": _choice(raw.get("side"), SIDES, "all"),
        "score": _score(raw.get("score")),
        "stage": _choice(raw.get("stage"), STAGES, "all"),
        "held": _choice(raw.get("held"), HELDS, "all"),
        "rules_off": _rules(raw.get("rules_off")),
        "sort": _choice(raw.get("sort"), SIG_SORTS, "new"),
        "group": _bool(raw.get("group")),
        "dense": _bool(raw.get("dense")),
        "gone": _bool(raw.get("gone")),
        "shut_off": _bool(raw.get("shut_off")),
        "shut": _bool(raw.get("shut")),
    }


def _watch(raw) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    return {
        "cls": _classes(raw.get("cls")),
        "held": _choice(raw.get("held"), HELDS, "all"),
        "sort": _choice(raw.get("sort"), WATCH_SORTS, "class"),
        "group": _bool(raw.get("group")),
        "dense": _bool(raw.get("dense")),
    }


def clean(raw) -> dict:
    """{"v": 1, "sig": {...}, "watch": {...}} — the whitelist rebuilt from
    `raw`, whatever it holds."""
    raw = raw if isinstance(raw, dict) else {}
    return {"v": 1, "sig": _sig(raw.get("sig")), "watch": _watch(raw.get("watch"))}


def merge(current, incoming) -> dict:
    """The stored prefs with the sections `incoming` carries replaced, the
    others kept, all of it cleaned."""
    base = clean(current)
    incoming = incoming if isinstance(incoming, dict) else {}
    if "sig" in incoming:
        base["sig"] = _sig(incoming.get("sig"))
    if "watch" in incoming:
        base["watch"] = _watch(incoming.get("watch"))
    return base


def prefs_for(user) -> dict:
    """The operator's prefs, cleaned; the defaults for anyone without a
    profile. Reads the reverse one-to-one the context processor already
    fetched for the timezone — no query of its own."""
    raw = {}
    if user is not None and getattr(user, "is_authenticated", False):
        try:
            raw = user.trader_profile.rail_prefs or {}
        except Exception:  # noqa: BLE001 — no profile is the defaults
            raw = {}
    return clean(raw)


def rule_off_keys(prefs) -> list:
    from dashboard.signal_rail import rule_key
    return [rule_key(name) for name in (prefs or {}).get("sig", {}).get("rules_off", [])]


def rule_off_css(prefs) -> str:
    """One rule per muted rule; keys are hex, so nothing needs escaping."""
    return "".join(
        f'[data-sv-fhost="signals"]:not([data-f-peek="1"]) [data-sv-row]'
        f'[data-rule-key="{key}"]{{display:none!important}}'
        for key in rule_off_keys(prefs))


def rule_off_json(prefs) -> str:
    """[[name, key], ...] of the muted rules, for the browser to save."""
    from dashboard.signal_rail import rule_key
    names = (prefs or {}).get("sig", {}).get("rules_off", [])
    return json.dumps([[name, rule_key(name)] for name in names])


def rule_rows(rail_rules, prefs) -> list:
    """[(name, key, count, shown)] for the rules toggle list: every rule on
    the rail with its count, then every muted rule the rail does not carry
    now, at 0 — a muted rule stays listed, so it can be brought back."""
    from dashboard.signal_rail import rule_key
    off = set((prefs or {}).get("sig", {}).get("rules_off", []))
    rows, seen = [], set()
    for name, key, count in rail_rules or []:
        rows.append((name, key, count, name not in off))
        seen.add(name)
    for name in sorted(off - seen):
        rows.append((name, rule_key(name), 0, False))
    return rows
