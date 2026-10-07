"""Who turned a bot off, and whether what it holds is still managed
(2026-10-07).

WHY THIS EXISTS. On 2026-10-06 at 13:12 UTC Morgul's G1 brake stopped
config 26 for a booking made while the exchange was shut, and PG #138 sat
OPEN on it from then on with nothing running its exits: no time stop, no
trailing, no break-even, no weekend or event window, no venue-mirrored
soft stop. The runner skipped every disabled config whole, on purpose
(runner.unmanaged_on_disable, 2026-09-26), because the kill switch, `bot
off`, the HQ toggle and the brake all wrote the same `enabled=False` and
nothing recorded which of them had done it. A runner that managed every
disabled config would have gone back to closing rows the kill switch had
left for reconciliation by hand. So the safe reading was the only one
available, and a brake meant to stop new entries also switched the exits
off.

THE RECORD. Every path that turns an AssetBotConfig off now goes through
disable_config here and leaves extras["disabled_by"]:

    {"by": code, "at": ISO UTC, "why": up to 200 characters,
     "who": up to 80 characters}

extras is a JSON column, so there is no migration; the record rides the
same row the heartbeat and the skip counters write, through the same
re-read under lock (safety._save_extras), so neither can drop it. Turning
the config back on (enable_config) clears it.

A BRAKE KEEPS MANAGING. The four brake codes (Morgul, the Telegram
group's /stop and /stopall, the alarm chat's /stopall, `bot brake` on the
server) mean "open nothing new", and nothing more: the runner runs a
braked config's manage pass every tick while it holds an OPEN row
(runner.manage_braked) and never its scan. The kill switch and a stop by
hand (`bot off`, the HQ and system-map toggles, the brain page's button, a
seed command) still mean what they always meant: not ticked at all. The
kill switch in particular leaves its rows for reconciliation by hand
(engine/kill_switch.py, its docstring and step 3), so it must never find a
manage pass closing behind it; that is why it supersedes a brake's record
on a config the brake had already stopped.

WHY MANAGING A STALE ROW IS SAFE. The manage pass closes or moves stops;
the only thing it can book is exposure that already exists at the venue (a
WORKING entry the broker has already filled). A managed close at eToro goes
by position id or sends nothing (venue_close.py, its docstring), so a
close on a row the broker no longer holds cannot open the opposite
position.

NO RECORD IS NOT A BRAKE. A config switched off before this module
existed, or by a path that keeps no record, reads "off with no record of
who" and is treated exactly as before: not ticked. Config 26 is such a
config until `bot brake 26` records it.
"""
from __future__ import annotations

import logging
from datetime import timezone as dt_tz

logger = logging.getLogger(__name__)

#: The key in AssetBotConfig.extras that holds the record.
RECORD_KEY = "disabled_by"

# The codes, one per path that can turn a config off.
BY_KILL_SWITCH = "kill_switch"
BY_BOT_OFF = "bot_off"
BY_HQ_TOGGLE = "hq_toggle"
BY_SYSTEM_MAP = "system_map"
BY_BRAIN = "brain_page"
BY_SEED = "seed_reset"
BY_MORGUL = "morgul"
BY_EYE = "eye_stop"
BY_ALARM = "alarm_stopall"
BY_BOT_BRAKE = "bot_brake"

#: The stops that mean "open nothing new" and nothing more: the runner keeps
#: managing what a config stopped by one of these holds.
BRAKES = frozenset({BY_MORGUL, BY_EYE, BY_ALARM, BY_BOT_BRAKE})

#: Every code in the words an operator reads. A code missing here is not a
#: record (record_of), so a typo can never pass for a brake.
BY_WORDS = {
    BY_KILL_SWITCH: "the kill switch",
    BY_BOT_OFF: "`bot off` on the server",
    BY_HQ_TOGGLE: "the HQ toggle",
    BY_SYSTEM_MAP: "the system map toggle",
    BY_BRAIN: "the brain page's Disable manual",
    BY_SEED: "a seed command",
    BY_MORGUL: "Morgul's brake",
    BY_EYE: "the Telegram group's /stop",
    BY_ALARM: "the alarm chat's /stopall",
    BY_BOT_BRAKE: "`bot brake` on the server",
}

NO_RECORD_WORDS = ("off with no record of who turned it off (before "
                   "2026-10-07, or a path that keeps none)")
NO_RECORD_SHORT = "off, with no record of who"


def record_of(cfg) -> dict:
    """The config's record, or {} when there is none, it is not a dict, or
    its code is not one this module knows. A malformed record is no record:
    it can never make a config read as braked."""
    extras = getattr(cfg, "extras", None)
    if not isinstance(extras, dict):
        return {}
    rec = extras.get(RECORD_KEY)
    if not isinstance(rec, dict):
        return {}
    by = rec.get("by")
    if not isinstance(by, str) or by not in BY_WORDS:
        return {}
    return dict(rec)


def keeps_managing(cfg) -> bool:
    """True when the config is off and a BRAKE turned it off: the runner
    still runs its exits every tick and never its entries."""
    return (not getattr(cfg, "enabled", True)
            and record_of(cfg).get("by") in BRAKES)


def _record(by: str, why: str, who: str, now) -> dict:
    from django.utils import timezone
    now = now or timezone.now()
    return {"by": by, "at": now.astimezone(dt_tz.utc).isoformat(),
            "why": str(why or "")[:200], "who": str(who or "")[:80]}


def _locked(cfg):
    """The config's row re-read under a row lock, as safety._save_extras
    does: the record is merged into the extras as they stand NOW, never
    into the snapshot a tick or a page loaded minutes ago (an operator's
    risk edit, a skip counter or a heartbeat written since stays). Call
    inside transaction.atomic."""
    return (cfg.__class__._default_manager
            .select_for_update().filter(pk=cfg.pk).first())


def _mirror(cfg, row) -> None:
    cfg.enabled = row.enabled
    cfg.extras = row.extras


def disable_config(cfg, *, by: str, why: str = "", who: str = "",
                   now=None) -> bool:
    """Turn the config off and record who did it. True when this call
    turned it off.

    On a config already off nothing is written, with one exception: the
    kill switch supersedes a BRAKE's record, so a config Morgul or the
    group had stopped is no longer managed once the kill switch has been
    pressed (the kill switch leaves its rows for reconciliation by hand,
    and a manage pass must not close them behind it). A brake never
    relabels a stop it did not make, and a hand stop of a braked config
    (`bot off`, the brain page's button) leaves it as found, still
    managed: the conservative side for real money. The operator's ways to
    end that management are closing the positions, or the kill switch."""
    from django.db import transaction
    if by not in BY_WORDS:
        raise ValueError(f"unknown disable code {by!r}; expected one of "
                         f"{sorted(BY_WORDS)}")
    record = _record(by, why, who, now)
    if getattr(cfg, "pk", None) is None:
        # An unsaved config (a dry run): nothing to re-read or lock, and a
        # stop must never raise, so it is stopped in memory alone.
        was_on = bool(getattr(cfg, "enabled", False))
        if was_on:
            extras = dict(cfg.extras) if isinstance(cfg.extras, dict) else {}
            extras[RECORD_KEY] = record
            cfg.enabled, cfg.extras = False, extras
        return was_on
    turned_off = False
    with transaction.atomic():
        row = _locked(cfg)
        if row is None:
            return False
        extras = dict(row.extras) if isinstance(row.extras, dict) else {}
        if row.enabled:
            extras[RECORD_KEY] = record
            row.enabled = False
            row.extras = extras
            row.save(update_fields=["enabled", "extras", "updated_at"])
            turned_off = True
        elif by == BY_KILL_SWITCH and keeps_managing(row):
            extras[RECORD_KEY] = record
            row.extras = extras
            row.save(update_fields=["extras", "updated_at"])
            logger.warning("[KILL SWITCH] config %s was stopped by a brake; "
                           "the kill switch's stop now stands — not managed",
                           row.pk)
    _mirror(cfg, row)
    if turned_off:
        logger.warning("[disarm] config %s (%s) stopped by %s: %s",
                       row.pk, row.name, BY_WORDS[by], record["why"])
    return turned_off


def enable_config(cfg) -> dict:
    """Turn the config on and clear its record, under the same lock.
    Returns the record it cleared ({} when there was none), so the caller
    can say whose stop it lifted."""
    from django.db import transaction
    if getattr(cfg, "pk", None) is None:
        raise ValueError("enable_config needs a saved config")
    with transaction.atomic():
        row = _locked(cfg)
        if row is None:
            return {}
        cleared = record_of(row)
        extras = dict(row.extras) if isinstance(row.extras, dict) else {}
        extras.pop(RECORD_KEY, None)
        row.enabled = True
        row.extras = extras
        row.save(update_fields=["enabled", "extras", "updated_at"])
    _mirror(cfg, row)
    return cleared


def adopt_unrecorded(cfg, *, why: str, who: str, now=None) -> bool:
    """`bot brake` on a config already off with NO record (one switched
    off before 2026-10-07, config 26 among them): record it as a brake, so
    the runner manages what it holds from the next tick. A config with a
    record, or one that is on, is left as found (False)."""
    from django.db import transaction
    if getattr(cfg, "pk", None) is None:
        return False
    record = _record(BY_BOT_BRAKE, why, who, now)
    adopted = False
    with transaction.atomic():
        row = _locked(cfg)
        if row is None:
            return False
        if not row.enabled and not record_of(row):
            extras = dict(row.extras) if isinstance(row.extras, dict) else {}
            extras[RECORD_KEY] = record
            row.extras = extras
            row.save(update_fields=["extras", "updated_at"])
            adopted = True
    _mirror(cfg, row)
    if adopted:
        logger.warning("[disarm] config %s (%s), off with no record, is now "
                       "recorded as stopped by %s: %s", row.pk, row.name,
                       BY_WORDS[BY_BOT_BRAKE], record["why"])
    return adopted


def record_words(cfg, *, short: bool = False) -> str:
    """Who stopped the config, in words. "" while it is on.

    The long form, for the server and the HQ pages: "stopped by Morgul's
    brake (Morgul) on 2026-10-06 13:12 UTC: Market-shut booking: ...".
    The short form, for a chat a person reads on a phone, never carries
    the who (a username) or the why (a config name, free text): "stopped
    by Morgul's brake on 2026-10-06 13:12 UTC"."""
    if getattr(cfg, "enabled", False):
        return ""
    rec = record_of(cfg)
    if not rec:
        return NO_RECORD_SHORT if short else NO_RECORD_WORDS
    from bot_program import telegram_eye as eye
    out = f"stopped by {BY_WORDS[rec['by']]}"
    who = str(rec.get("who") or "").strip()
    if who and not short:
        out += f" ({who})"
    at = eye._parse_iso(rec.get("at")) if rec.get("at") else None
    if at is not None:
        out += f" on {eye.when(at)}"
    why = str(rec.get("why") or "").strip()
    if why and not short:
        out += f": {why}"
    return out


def braked_with_open_rows() -> list:
    """The configs a brake stopped that still hold an OPEN row: the ones
    the runner's braked pass manages. OPEN only, because manage_positions
    walks OPEN only; a WORKING entry is an OPEN row, so it is included. The
    brake test runs in Python over the record, not as a JSON lookup, so
    SQLite (the suite) and Postgres agree."""
    from bot_program.models import AssetBotConfig
    return [c for c in (AssetBotConfig.objects
                        .filter(enabled=False, trades__status="OPEN")
                        .distinct().select_related("user").order_by("pk"))
            if keeps_managing(c)]
