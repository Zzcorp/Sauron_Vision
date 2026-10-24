"""Turning a live-money switch on takes the trading PIN, on every path.

The operator's ask (2026-10-23): "Go for the PIN on the switches." Every
door that writes PlatformComponent.is_enabled reached every key in
LIVE_MONEY_SWITCHES with no PIN: the /ops/ toggle and the admin
dashboard's forms (dashboard.views.admin_toggle_component), the system
map (dashboard.views_topology.system_map_toggle), the Django admin, and
the shell's component command. Closing a position, the kill switch and
arming a live bot all asked for the PIN; arming real money through a
switch did not, so a hijacked superuser session could do it in one POST.

The rule, kept here and only here:

* OFF -> ON of a live-money key takes the PIN of the user making the
  request, through THE counted check every PIN door shares
  (core.trading_pin.check, as an ACT door): wrong answers at a switch, at
  the lock screen and at every other PIN door add up on one session
  counter, and the fifth ends the session.
* A missing, blank or wrong PIN changes nothing and says why. A blank
  PIN, or an account with no PIN set, is not counted as a guess. A
  session that has already spent its five is refused, and ended, before
  anything else is read (a blank PIN included, since 2026-10-23).
* Only a session that logged in under the account's CURRENT PIN can arm.
  Login stamps the session with a keyed mark of the stored PIN hash
  (stamp_login_mark, the way Django keeps the password's own mark in
  HASH_SESSION_KEY). A PIN set or changed afterwards, by any door (the
  profile's change-PIN forms, which ask nothing when no PIN is set yet,
  or the Django admin's TraderProfile page), leaves the session's mark
  behind: it must log in again, with the password, before it arms. So a
  hijacked session cannot set or replace the PIN and then use it here.
* The shell and the Django admin never take a PIN: they refuse and point
  to /ops/. The shell is run without a terminal (`dc exec -T`), has no
  logged-in user to count against, and whoever reaches it already holds
  the database; a PIN typed on its command line would sit in the shell
  history.
* Turning OFF never asks. Stopping must never be harder than starting.
* Every ON, every refused ON and every OFF of a live-money key lands on
  the audit chain (bot_program.audit.record_switch) with who, the door
  and when. Never the PIN, its length or its hash.
* Non-live keys, and the "all on" exemptions, are as they were.

What stays out of reach of any PIN: the ORM, `manage.py shell`, dbshell
and SQL. Whoever can run those holds the database.

Closed (D1, 2026-10-23, "Oui fait les deux"): every door that checks the
trading PIN now counts on this same session counter, through the one
check in core/trading_pin.py, each door with its class. A stopping door
(a close, close-all, close-selected, both kill switches, a stop edit that
only tightens) counts but never ends the session, and a right PIN always
stops; every other door, the switches included, ends the session at the
fifth wrong answer. The change-PIN forms judge the new PIN before the
current one, and the system map and the admin bot panel ask the PIN to
arm a live bot.

Still without a PIN, by design or awaiting the operator: `manage.py bot on
ID --yes` (and `follow --yes`, `persona --yes`), where `--yes` plays the
PIN's role at a shell that already holds the database; and the venue
doors that make an armed live config's next order real (Saxo SIM to LIVE,
a new eToro row saved live, keys re-attached to a live eToro row, OANDA
and Alpaca unticked, Binance testnet unticked).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from django.db import transaction
from django.utils import timezone

from bot_program.audit import (SWITCH_ARMED, SWITCH_DISARMED,
                               SWITCH_REFUSED, record_switch)
from core.platform_control import (BULK_ENABLE_EXEMPT, DEFAULT_COMPONENTS,
                                   LIVE_MONEY_SWITCHES, PlatformComponent)

logger = logging.getLogger(__name__)

# The doors, as recorded in each audit row's "via".
VIA_OPS = "ops"
VIA_ADMIN_DASHBOARD = "admin_dashboard"
VIA_SYSTEM_MAP = "system_map"
VIA_SHELL = "shell"
VIA_DJANGO_ADMIN = "django_admin"
VIA_ALL_ON = "all_on"
VIA_ALL_OFF = "all_off"

#: What a page that cannot ask for the PIN says to do instead.
OPS_POINTER = ("Live-money switches are turned on from /ops/ with your "
               "trading PIN.")

# The refusal codes (SwitchResult.refusal, and the audit row's "reason").
# The PIN's own codes, the verdict and the login mark live in
# core/trading_pin.py (the one check); re-exported here unchanged.
NOT_FOUND = "not_found"
from core.trading_pin import (LOCKED_OUT, LOGIN_AGAIN,  # noqa: E402,F401
                              LOGIN_MARK_KEY, NO_PIN_HERE, PIN_MISSING,
                              PIN_NOT_SET, PIN_WRONG, PinVerdict,
                              _LOGIN_MARK_SALT, _logged_in_with_current_pin,
                              _pin_mark, _stored_hash, stamp_login_mark)
from core import trading_pin  # noqa: E402


@dataclass(frozen=True)
class SwitchResult:
    ok: bool                # the row now holds the requested state
    changed: bool           # this call wrote the row
    key: str
    name: str
    before: Optional[bool]
    after: Optional[bool]
    message: str            # one English sentence for the page or the shell
    refusal: str = ""
    logged_out: bool = False


def is_live(key: str) -> bool:
    return key in LIVE_MONEY_SWITCHES


def needs_pin(key: str, *, was_on: bool, want_on: bool) -> bool:
    """True only for OFF -> ON of a live-money key. OFF is always free."""
    return bool(want_on) and not bool(was_on) and is_live(key)


def _name_of(key: str) -> str:
    row = PlatformComponent.objects.filter(key=key).only("name").first()
    if row is not None and row.name:
        return row.name
    for c in DEFAULT_COMPONENTS:
        if c["key"] == key:
            return c.get("name") or key
    return key


def _who(request=None, user=None) -> str:
    u = user if user is not None else getattr(request, "user", None)
    if u is not None and getattr(u, "is_authenticated", False):
        return u.get_username()
    return VIA_SHELL if request is None and user is None else ""


# ── the sentences ───────────────────────────────────────────────────────
def refusal_sentence(keys, *, via: str) -> str:
    """The sentence a door that never takes a PIN answers with."""
    keys = list(keys)
    subject = ", ".join(keys)
    it = "it" if len(keys) == 1 else "them"
    verb = "moves" if len(keys) == 1 else "move"
    door = {VIA_SHELL: "the shell never asks for one",
            VIA_DJANGO_ADMIN: "this admin page never asks for one",
            }.get(via, "this door never asks for one")
    return (f"{subject} {verb} real money: turning {it} on takes your "
            f"trading PIN, and {door}. Turn {it} on from /ops/ (Switches, "
            f"System) with your PIN. Nothing was changed.")


def _pin_sentence(refusal: str, name: str, verdict: PinVerdict = None) -> str:
    if refusal == PIN_MISSING:
        return (f"{name} moves real money: turning it on takes your "
                f"trading PIN. Nothing was changed.")
    if refusal == PIN_NOT_SET:
        return (f"{name} moves real money and your account has no trading "
                f"PIN yet: set one on your profile, then log out and log "
                f"in again with it. Nothing was changed.")
    if refusal == LOGIN_AGAIN:
        return (f"Log in again first: this session did not log in with "
                f"your current trading PIN, so it cannot turn {name} on. "
                f"Log out, log back in with your password and PIN, then "
                f"try again. Nothing was changed.")
    if refusal == PIN_WRONG:
        n = verdict.attempts_left if verdict else None
        left = ("" if n is None else
                f" {n} attempt{'' if n == 1 else 's'} left before this "
                f"session ends.")
        return f"Incorrect PIN: {name} stays OFF.{left}"
    if refusal == LOCKED_OUT:
        return (f"Too many incorrect PINs: the session has ended and "
                f"{name} stays OFF.")
    return f"{name} stays OFF. Nothing was changed."


# ── the PIN ─────────────────────────────────────────────────────────────
def check_trading_pin(request, pin, *, act: str = "Switch PIN") -> PinVerdict:
    """The requesting user's trading PIN at a switch: THE counted check
    (core.trading_pin.check) as an ACT door. Blank, or no PIN set:
    refused, not counted. A session that did not log in under the current
    PIN: refused, not counted, no hash checked. A spent counter: the
    session ends before anything else is read. Wrong: counted; the fifth
    ends the session. Right: the counter is cleared."""
    return trading_pin.check(request, pin, door=trading_pin.ACT, act=act)


# ── the writes ──────────────────────────────────────────────────────────
def set_switch(key: str, want_on: bool, *, via: str, request=None,
               pin: Optional[str] = None) -> SwitchResult:
    """THE write for one switch, from every door that sets one.

    A missing row is not created. A row already in the asked state is
    left alone, with no PIN asked. OFF -> ON of a live-money key takes
    the PIN: from `request`'s user when there is a request, and never
    without one (the shell, a programmatic call). Any refusal writes
    nothing to the row.
    """
    want_on = bool(want_on)
    row = PlatformComponent.objects.filter(key=key).first()
    if row is None:
        return SwitchResult(ok=False, changed=False, key=key, name=key,
                            before=None, after=None,
                            message=f"Component '{key}' not found.",
                            refusal=NOT_FOUND)
    name = row.name or key
    was_on = bool(row.is_enabled)
    user = getattr(request, "user", None) if request is not None else None
    who = _who(request)

    if was_on == want_on:
        return SwitchResult(ok=True, changed=False, key=key, name=name,
                            before=was_on, after=was_on,
                            message=f"{name} is already "
                                    f"{'ON' if was_on else 'OFF'}.")

    if needs_pin(key, was_on=was_on, want_on=want_on):
        if request is None:
            message = refusal_sentence([key], via=via)
            record_switch(SWITCH_REFUSED, key=key, name=name, via=via,
                          who=who, before=was_on, after=was_on,
                          reason=NO_PIN_HERE)
            return SwitchResult(ok=False, changed=False, key=key, name=name,
                                before=was_on, after=was_on,
                                message=message, refusal=NO_PIN_HERE)
        verdict = check_trading_pin(request, pin)
        if not verdict.ok:
            # `user` was read before a lockout's logout() replaced it.
            record_switch(SWITCH_REFUSED, key=key, name=name, via=via,
                          who=who, before=was_on, after=was_on,
                          reason=verdict.refusal, user=user)
            return SwitchResult(ok=False, changed=False, key=key, name=name,
                                before=was_on, after=was_on,
                                message=_pin_sentence(verdict.refusal, name,
                                                      verdict),
                                refusal=verdict.refusal,
                                logged_out=verdict.logged_out)

    with transaction.atomic():
        locked = PlatformComponent.objects.select_for_update().get(pk=row.pk)
        before = bool(locked.is_enabled)
        changed = before != want_on
        if changed:
            locked.is_enabled = want_on
            # updated_at is auto_now, which update_fields skips: it is the
            # instant of the flip, and the alarm bot reads it off
            # platform_master to tell a pause from a stop
            # (bot_program/alarm._resumed_at).
            locked.save(update_fields=["is_enabled", "updated_at"])

    if changed and is_live(key):
        record_switch(SWITCH_ARMED if want_on else SWITCH_DISARMED,
                      key=key, name=name, via=via, who=who, before=before,
                      after=want_on, user=user)
    verb = "started" if want_on else "stopped"
    message = (f"{name} {verb}." if changed else
               f"{name} is already {'ON' if want_on else 'OFF'}.")
    return SwitchResult(ok=True, changed=changed, key=key, name=name,
                        before=before, after=want_on, message=message)


def set_category(category: str, want_on: bool, *, via: str,
                 request=None) -> int:
    """THE write for a category's "all on" / "all off": the same query
    and the same count as before. ON never reaches a held switch
    (BULK_ENABLE_EXEMPT), and the live-money keys are excluded a second
    time by name, so an edit of the exempt set cannot open this door.
    OFF records each live-money switch it turned off."""
    rows = PlatformComponent.objects.filter(category=category)
    now = timezone.now()
    if want_on:
        rows = (rows.exclude(key__in=BULK_ENABLE_EXEMPT)
                .exclude(key__in=LIVE_MONEY_SWITCHES))
        # updated_at is auto_now, which a queryset update skips: it is the
        # instant of the flip (alarm._resumed_at reads it).
        return rows.update(is_enabled=True, updated_at=now)
    live_on = list(rows.filter(key__in=LIVE_MONEY_SWITCHES, is_enabled=True)
                   .values_list("key", "name"))
    count = rows.update(is_enabled=False, updated_at=now)
    user = getattr(request, "user", None) if request is not None else None
    who = _who(request)
    for key, name in live_on:
        record_switch(SWITCH_DISARMED, key=key, name=name or key, via=via,
                      who=who, before=True, after=False, user=user)
    return count


def refuse_here(key: str, *, via: str, user=None) -> str:
    """Record an ON refused at a door that never takes a PIN (the shell,
    the Django admin) and return that door's sentence."""
    who = _who(user=user) if user is not None else VIA_SHELL
    name = _name_of(key)
    row = PlatformComponent.objects.filter(key=key).only("is_enabled").first()
    before = bool(row.is_enabled) if row is not None else None
    record_switch(SWITCH_REFUSED, key=key, name=name, via=via, who=who,
                  before=before, after=before, reason=NO_PIN_HERE, user=user)
    return refusal_sentence([key], via=via)


def record_disarm(key: str, *, via: str, user=None) -> None:
    """A live-money switch turned off by a door that writes the row
    itself (the Django admin's save)."""
    if not is_live(key):
        return
    record_switch(SWITCH_DISARMED, key=key, name=_name_of(key), via=via,
                  who=_who(user=user) if user is not None else VIA_SHELL,
                  before=True, after=False, user=user)
