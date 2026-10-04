"""Where a rule may fire, how often, and how loudly (2026-10-04).

The weekly review of 2026-10-02 read 151 signals in a week, 58 resolved,
13 hit — 22% — and one detector, the RSI bullish divergence, hitting 17%
while labelling every one of its signals HIGH urgency, many of them on
commodities and mining stocks. Three faults, one module:

  SCOPE.    A rule may be kept off an asset class, a sector, a symbol or
            a named group (the miners). Code defaults name what the
            review asked for — rsi_bull_divergence off commodities and
            miners — and the RuleControl row's `scope` JSON overrides
            them: {} means "the defaults", an explicit empty list lifts
            one. The operator keeps the last word (`rule_scope`).
  COOLDOWN. The engine re-fired a rule on the same symbol the scan after
            its signal closed, because the condition that fired it (an
            RSI under 35 in a downtrend) was still true. No second signal
            for (rule, symbol) within SIGNAL_COOLDOWN_HOURS of the last
            one's close — its birth while it still lives, which the
            active-signal dedupe already covers. Per rule via `scope`,
            a key of its own: a row that names only a cooldown keeps
            the default exclusions, and the other way round.
  URGENCY.  A constant score is not a conviction. Past RECORD_MIN_RESOLVED
            graded signals, a rule whose hit rate reads under the floors
            has its urgency capped — under RECORD_LOW_HIT_RATE to low,
            under RECORD_MEDIUM_HIT_RATE to medium — and the signal says
            so. The record is the evidence ledger's (bot_program.evidence
            .rule_rows: graded Signals, all time), never a second grader.

Enforced in signals.tasks._create_signals_and_notify, the one persister
of the scheduled engine's output. The fast rules keep their own 60-second
intraday cooldown (signals/fast_rules.py); the scanner's flags are a
different lane.
"""
from __future__ import annotations

import logging
import re
from datetime import timedelta

from django.utils import timezone

logger = logging.getLogger(__name__)

#: No second signal for (rule, symbol) within this many hours of the last
#: one's close. A 4h-bar rule reads six bars; a condition that is still
#: true after a day is a new reading, not the same one re-announced.
SIGNAL_COOLDOWN_HOURS = 24.0

#: Graded signals a rule needs before its record may lower its urgency.
#: Below it the rate is not a number (the ledger's own floor is the
#: evidence page's; this one is the urgency's).
RECORD_MIN_RESOLVED = 20
#: Hit rate under which a measured rule's urgency is capped at low …
RECORD_LOW_HIT_RATE = 0.35
#: … and under which it is capped at medium.
RECORD_MEDIUM_HIT_RATE = 0.50

URGENCY_ORDER = ("low", "medium", "high", "critical")

#: The miners: the mining stocks and the metal proxies the catalogue
#: carries or may carry. Membership is the symbol, the sector when a
#: feed has written one, or a word in the name — GOLD here is Barrick
#: (the catalogue's stock), GLD the bullion trust; Goldman Sachs is not a
#: miner, and the word match is on whole words so it never is.
MINER_SYMBOLS = frozenset({
    "GOLD", "NEM", "RIO", "BHP", "VALE", "FCX", "SCCO", "AEM", "WPM",
    "KGC", "AU", "FNV", "AA", "CLF", "MP", "GLD", "GLDM", "SLV", "GDX",
    "GDXJ", "SIL", "CPER", "IAU", "SGOL",
})
MINER_SECTORS = frozenset({
    "basic materials", "metals & mining", "metals and mining", "mining",
    "gold", "precious metals",
})
MINER_NAME_WORDS = re.compile(
    r"\b(gold|silver|mining|miners?|minerals?|copper|metals?|uranium|"
    r"lithium|platinum|palladium|bullion)\b", re.IGNORECASE)

#: Named groups a scope may exclude by name.
GROUPS = ("miners",)

#: The review's ask, as code: these apply to a rule with no RuleControl
#: row and to one whose `scope` is {}. A row that names the key decides.
DEFAULT_RULE_SCOPE = {
    "rsi_bull_divergence": {
        "exclude": {"asset_classes": ["commodity"], "groups": ["miners"]},
    },
}

SCOPE_KEYS = ("asset_classes", "sectors", "symbols", "groups")


def _lower_list(values) -> list:
    if not isinstance(values, (list, tuple, set, frozenset)):
        return []
    return [str(v).strip().lower() for v in values if str(v).strip()]


def _control(rule_name, ctrl=None):
    if ctrl is not None:
        return ctrl
    try:
        from signals.rule_actuator import _control_for
        return _control_for(rule_name)
    except Exception:  # noqa: BLE001 — an unreadable row is "no row"
        return None


def effective_scope(rule_name: str, ctrl=None) -> dict:
    """The scope that governs `rule_name`, key by key: the row's
    `exclude` when the row carries that key (an explicit {} or empty
    lists lift the default), the code default otherwise; the row's
    `cooldown_hours` when it is a number, the platform's otherwise.
    Always {exclude: {...}, cooldown_hours: float|None,
    source: "row"|"default"|"none"} — `source` is the exclusions'."""
    ctrl = _control(rule_name, ctrl)
    raw = getattr(ctrl, "scope", None) if ctrl is not None else None
    raw = raw if isinstance(raw, dict) else {}
    default = DEFAULT_RULE_SCOPE.get(rule_name or "", {})
    if isinstance(raw.get("exclude"), dict):
        exclude, source = raw["exclude"], "row"
    else:
        exclude = default.get("exclude") or {}
        source = "default" if exclude else "none"
    out = {"exclude": {k: _lower_list(exclude.get(k)) for k in SCOPE_KEYS},
           "cooldown_hours": None, "source": source}
    hours = raw.get("cooldown_hours", default.get("cooldown_hours"))
    if isinstance(hours, (int, float)) and not isinstance(hours, bool) \
            and hours >= 0:
        out["cooldown_hours"] = float(hours)
    return out


def is_miner(instrument) -> bool:
    """A mining stock or a metal proxy, by symbol, sector or name."""
    symbol = str(getattr(instrument, "symbol", "") or "").upper()
    if symbol in MINER_SYMBOLS:
        return True
    sector = str(getattr(instrument, "sector", "") or "").strip().lower()
    if sector and sector in MINER_SECTORS:
        return True
    name = str(getattr(instrument, "name", "") or "")
    return bool(name and MINER_NAME_WORDS.search(name))


def in_group(group: str, instrument) -> bool:
    if group == "miners":
        return is_miner(instrument)
    return False


def exclusion_reason(rule_name: str, instrument, ctrl=None) -> str:
    """Why `rule_name` may not fire on `instrument`, or "" when it may."""
    scope = effective_scope(rule_name, ctrl)
    ex = scope["exclude"]
    symbol = str(getattr(instrument, "symbol", "") or "").upper()
    cls = str(getattr(instrument, "asset_class", "") or "").lower()
    sector = str(getattr(instrument, "sector", "") or "").lower()
    where = "the row's scope" if scope["source"] == "row" else "the default scope"
    if cls and cls in ex["asset_classes"]:
        return f"{rule_name} is off {cls} ({where})"
    if sector and sector in ex["sectors"]:
        return f"{rule_name} is off the {sector} sector ({where})"
    if symbol and symbol.lower() in ex["symbols"]:
        return f"{rule_name} is off {symbol} ({where})"
    for group in ex["groups"]:
        if group in GROUPS and in_group(group, instrument):
            return f"{rule_name} is off the {group} ({where}): {symbol}"
    return ""


def cooldown_hours(rule_name: str, ctrl=None) -> float:
    """The rule's cooldown in hours: the row's when it names one, else
    SIGNAL_COOLDOWN_HOURS. 0 switches it off for that rule."""
    hours = effective_scope(rule_name, ctrl)["cooldown_hours"]
    return SIGNAL_COOLDOWN_HOURS if hours is None else hours


def cooldown_reason(rule_name: str, instrument, *, hours: float,
                    now=None) -> str:
    """Why a new (rule, instrument) signal is too soon, or "".

    Anchored on the newest signal's close (`expired_at`), or its birth
    when it never closed — a signal still active is the dedupe's, not
    this one's, but a row deactivated without a close stamp counts from
    the moment it fired."""
    if not hours or hours <= 0:
        return ""
    from signals.models import Signal
    now = now or timezone.now()
    last = (Signal.objects.filter(instrument=instrument, rule_name=rule_name)
            .order_by("-created_at").values("created_at", "expired_at",
                                            "outcome").first())
    if not last:
        return ""
    anchor = last["expired_at"] or last["created_at"]
    if anchor is None:
        return ""
    age = now - anchor
    if age >= timedelta(hours=hours):
        return ""
    ago = max(age.total_seconds(), 0) / 3600.0
    what = (f"closed {last['outcome'] or 'inactive'}" if last["expired_at"]
            else "fired")
    return (f"the last {rule_name} signal on "
            f"{getattr(instrument, 'symbol', instrument)} {what} "
            f"{ago:.1f}h ago — cooldown {hours:g}h")


# ── the record, and the urgency it allows ───────────────────────────────

def rule_records() -> dict:
    """{rule_name: {"n": graded, "hit_rate": 0..1 | None}} off the
    evidence ledger — the one grader. Empty when it cannot be read."""
    try:
        from bot_program.evidence import rule_rows
        rows = rule_rows()
    except Exception as e:  # noqa: BLE001
        logger.warning("[rule scope] evidence ledger unreadable: %s", e)
        return {}
    out = {}
    for row in rows:
        name = row.get("rule") or ""
        if not name:
            continue
        n = int(row.get("sig_n") or 0)
        hit = row.get("sig_hit")
        out[name] = {"n": n, "hit_rate": (float(hit) if hit is not None
                                          and n else None)}
    return out


def urgency_cap(record) -> str:
    """The highest urgency a rule's record allows, or "" when it allows
    any: unmeasured rules (under RECORD_MIN_RESOLVED) are never capped."""
    if not record:
        return ""
    n = int(record.get("n") or 0)
    hit = record.get("hit_rate")
    if n < RECORD_MIN_RESOLVED or hit is None:
        return ""
    if hit < RECORD_LOW_HIT_RATE:
        return "low"
    if hit < RECORD_MEDIUM_HIT_RATE:
        return "medium"
    return ""


def capped(urgency: str, cap: str) -> str:
    """The lower of the two on URGENCY_ORDER; an unknown word is kept."""
    u = (urgency or "").lower()
    if not cap or u not in URGENCY_ORDER or cap not in URGENCY_ORDER:
        return urgency
    return cap if URGENCY_ORDER.index(cap) < URGENCY_ORDER.index(u) else urgency


def record_sentence(record, cap: str) -> str:
    """One sentence for the signal's text when its urgency was capped."""
    n = int(record.get("n") or 0)
    hits = int(round(float(record.get("hit_rate") or 0.0) * n))
    pct = float(record.get("hit_rate") or 0.0) * 100
    return (f"Rule record: {hits} of {n} graded signals hit ({pct:.0f}%), "
            f"all time — urgency capped at {cap}.")
