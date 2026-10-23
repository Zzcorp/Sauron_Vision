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
  request, checked against the same TraderProfile hash every other PIN
  act uses (TraderProfile.check_pin), behind the idle lock's own session
  counter (dashboard.lock_views.MAX_ATTEMPTS): wrong answers at a switch
  and at the lock screen add up, and the fifth ends the session.
* A missing, blank or wrong PIN changes nothing and says why. A blank
  PIN, or an account with no PIN set, is not counted as a guess.
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
NOT_FOUND = "not_found"
PIN_MISSING = "pin_missing"
PIN_NOT_SET = "pin_not_set"
PIN_WRONG = "pin_wrong"
LOCKED_OUT = "locked_out"
NO_PIN_HERE = "no_pin_here"


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


@dataclass(frozen=True)
class PinVerdict:
    ok: bool
    refusal: str = ""
    attempts_left: Optional[int] = None
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
                f"PIN yet: set one on your profile first. Nothing was "
                f"changed.")
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
    """The requesting user's trading PIN, checked on their own profile's
    hash, behind the idle lock's session counter.

    Blank, or no PIN set on the account: refused, not counted (a mistake,
    not a guess). Wrong: counted; at MAX_ATTEMPTS the session ends, as on
    the lock screen (dashboard/lock_views.session_unlock). Right: the
    counter is cleared. The PIN itself is never logged or stored.
    """
    from django.contrib.auth import logout

    from core.audit import AuditLog
    from core.presence import client_ip
    from dashboard.lock_views import ATTEMPTS_KEY, MAX_ATTEMPTS
    from portfolio.trader_profile import get_or_create_profile

    user = getattr(request, "user", None)
    if user is None or not getattr(user, "is_authenticated", False):
        return PinVerdict(ok=False, refusal=PIN_MISSING)
    if not (pin or "").strip():
        return PinVerdict(ok=False, refusal=PIN_MISSING)
    profile = get_or_create_profile(user)
    if not profile.has_pin:
        return PinVerdict(ok=False, refusal=PIN_NOT_SET)
    if profile.check_pin(pin):
        request.session.pop(ATTEMPTS_KEY, None)
        return PinVerdict(ok=True)

    attempts = int(request.session.get(ATTEMPTS_KEY, 0) or 0) + 1
    if attempts >= MAX_ATTEMPTS:
        # Log while request.user is still the user: logout() clears it.
        AuditLog.log(
            user, "login",
            f"{act}: {MAX_ATTEMPTS} failed attempts — session terminated",
            target_type="Session", ip_address=client_ip(request))
        logout(request)   # flushes the session, the counter with it
        return PinVerdict(ok=False, refusal=LOCKED_OUT, attempts_left=0,
                          logged_out=True)
    request.session[ATTEMPTS_KEY] = attempts
    return PinVerdict(ok=False, refusal=PIN_WRONG,
                      attempts_left=MAX_ATTEMPTS - attempts)


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
