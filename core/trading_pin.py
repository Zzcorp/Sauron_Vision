"""THE trading PIN check for a session, at every door (2026-10-23, D1).

The operator's decision ("Oui fait les deux"): every door that checks the
trading PIN counts wrong answers on one session counter, the idle lock's
own (ATTEMPTS_KEY, MAX_ATTEMPTS). This module is the only place a session's
PIN is verified (TraderProfile.check_pin, through _hash_ok); every door
names its class, and the class decides what a wrong or a right answer does.

The classes (`door=`, keyword-only, no default: a call site that forgets
its class fails with TypeError in its tests):

* STOP: the act only reduces risk or stops something: closing one
  position, close-all, close-selected, both kill switches, a stop edit
  that only tightens. A wrong PIN is counted but NEVER ends the session,
  and a right PIN ALWAYS stops, whatever the counter says. Stopping must
  never be harder than starting. The login mark is not asked.
* ACT: anything that opens, arms, moves or withdraws money, changes the
  PIN or a live setting. The switch's rule (PR69): the fifth wrong answer
  ends the session, and a spent counter ends it before anything else is
  read, blank PIN included. Only a session that logged in under the
  account's CURRENT PIN may act (the login mark): a PIN set or changed
  since must come back through a login, with the password.
* LOCK: the idle lock screen. Counted as ACT is; the login mark is not
  asked (unlocking only resumes the session, and every ACT door behind it
  still asks). Past five it gives one check: a right PIN unlocks without
  clearing the counter, so a session spent at STOP doors can still reach a
  close; a wrong one ends the session.

The counter is reserved BEFORE any hash is checked: an atomic counter in
the cache keyed on a hash of the session key, mirrored into the session.
The cache is the authority whenever it holds the key, so a request that
loaded the session earlier and saved it later can neither write the count
back down (after a wrong answer) nor back up (after a right one or a
login); the session's copy answers only when the cache has no key (a
session from before this module, an eviction) or fails, which is the
protection the lock and the switch had before. Each request decides on
its own reserved number, never on a read taken before: a burst of
parallel guesses gets numbers 1, 2, ... N, and only those numbered five
or less are ever checked at an ACT door. A right answer clears the
counter only when its own number was five or less; past five only a
fresh login clears it (on_login: every login proves the password, and the
PIN step when the account has one; Django keeps the session and its key
when the same user logs in again over a live one).

Blank, and an account with no PIN set, are refused and never counted (a
mistake, not a guess). The profile is read, never created.

What is recorded (bot_program.audit, the chain; core.audit.AuditLog):
guesses one to five (pin_refused), the fifth (pin_spent, once), a right PIN
past five (pin_ok_spent), every ended session (pin_refused, locked_out, and
the AuditLog "session terminated" line). Past five at a STOP door, where
guesses are unlimited by design, at most one summary row a minute; a "log
in again" refusal once per session and act. Never the PIN, its length or
its hash. The alarm chat (bot_program.alarm, critical only) hears, once
per session, a right PIN given after five misses or ten wrong answers at
a stopping door; never a session the check already ended. The Telegram
call runs on a short thread of the request's own process, never on the
request path: a slow Telegram never holds up the close, the flatten or
the unlock it reports. Every side
effect is fenced: the check never raises, and at a STOP door a right PIN
stops whatever failed.
"""
from __future__ import annotations

import hashlib
import logging
import threading
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# ── the door classes ────────────────────────────────────────────────────
STOP = "stop"
ACT = "act"
LOCK = "lock"
DOOR_CLASSES = frozenset({STOP, ACT, LOCK})

# ── the counter ─────────────────────────────────────────────────────────
#: One session, five guesses (moved from dashboard/lock_views.py, same
#: values: live sessions keep their count across the deploy).
MAX_ATTEMPTS = 5
ATTEMPTS_KEY = "pin_lock_attempts"
#: The pre-session login step's own count (dashboard/auth_views.login_pin).
LOGIN_ATTEMPTS_KEY = "login_pin_attempts"
SESSION = "session"
LOGIN = "login"

# ── the login mark (moved from core/switch_pin.py, same values) ────────
#: The session key holding the login's mark of the stored PIN hash. A
#: keyed HMAC of the hash, never the hash nor the PIN.
LOGIN_MARK_KEY = "switch_pin_login_mark"
_LOGIN_MARK_SALT = "core.switch_pin.login_mark"

# ── the refusal codes (the audit row's "reason") ───────────────────────
PIN_MISSING = "pin_missing"
PIN_NOT_SET = "pin_not_set"
PIN_WRONG = "pin_wrong"
LOCKED_OUT = "locked_out"
LOGIN_AGAIN = "login_again"
UNCHECKED = "pin_unchecked"
NO_PIN_HERE = "no_pin_here"

#: Past five at a STOP door: the guess that rings the alarm chat.
PROBING_AT = 2 * MAX_ATTEMPTS
#: Past five at a STOP door: at most one summary chain row this often.
SUMMARY_EVERY_S = 60
_ACT_MAX = 40
#: The name of the short thread that carries one alarm to Telegram.
ALARM_THREAD = "trading-pin-alarm"


@dataclass(frozen=True)
class PinVerdict:
    ok: bool
    refusal: str = ""
    attempts_left: Optional[int] = None
    logged_out: bool = False
    spent: bool = False          # this session has used up its five
    door: str = ""


# ── small fenced helpers ────────────────────────────────────────────────
def _cache():
    from django.core.cache import cache
    return cache


def _warn(what: str, e: Exception) -> None:
    # The type only: an exception's text can carry a cache address.
    logger.warning("trading PIN: %s (%s)", what, type(e).__name__)


def _ttl() -> int:
    from django.conf import settings
    try:
        return int(getattr(settings, "SESSION_COOKIE_AGE", 0) or 1209600)
    except (TypeError, ValueError):
        return 1209600


def _tag(request) -> str:
    """A hash of the session key: the raw cookie value never names a
    cache key nor reaches a log."""
    key = getattr(getattr(request, "session", None), "session_key", None)
    if not key:
        return ""
    return hashlib.sha256(str(key).encode()).hexdigest()[:32]


def _key(tag: str, what: str) -> str:
    return f"trading_pin:{what}:{tag}"


def _mirror_key(scope: str) -> str:
    return LOGIN_ATTEMPTS_KEY if scope == LOGIN else ATTEMPTS_KEY


def _mirror(request, scope: str) -> int:
    try:
        return max(0, int(request.session.get(_mirror_key(scope), 0) or 0))
    except Exception:  # noqa: BLE001 — a garbled value counts as nothing
        return 0


def _label(act) -> str:
    return " ".join(str(act or "").split())[:_ACT_MAX] or "a PIN door"


def _who(user) -> str:
    try:
        return user.get_username()
    except Exception:  # noqa: BLE001
        return ""


def _once(request, what: str, ttl: int) -> bool:
    """True the first time `what` happens for this session within `ttl`.
    A cache that fails, or a request with no session, says no: a record or
    an alarm lost is better than an unbounded stream of them."""
    tag = _tag(request)
    if not tag:
        return False
    try:
        return bool(_cache().add(_key(tag, what), 1, ttl))
    except Exception as e:  # noqa: BLE001
        _warn("a once-guard could not be read", e)
        return False


# ── the counter ─────────────────────────────────────────────────────────
def attempts(request, *, scope: str = SESSION) -> int:
    """How many wrong answers this session has given: the cache's atomic
    count whenever it holds the key (a stale session copy, lower or higher,
    never wins over it); the session's own copy when the cache has no key
    or cannot be read."""
    floor = _mirror(request, scope)
    tag = _tag(request)
    if not tag:
        return floor
    try:
        n = _cache().get(_key(tag, scope))
    except Exception as e:  # noqa: BLE001
        _warn("the counter's cache could not be read", e)
        return floor
    if n is None:
        return floor
    try:
        return max(0, int(n))
    except (TypeError, ValueError):
        return floor


def _reserve(request, scope: str) -> int:
    """This request's number, itself included, taken BEFORE any hash. The
    cache's count is seeded from the session's copy only when it holds no
    key; once it does, its own atomic increment is the number."""
    floor = _mirror(request, scope)
    n = floor + 1
    tag = _tag(request)
    if tag:
        try:
            c = _cache()
            key = _key(tag, scope)
            c.add(key, floor, _ttl())
            n = int(c.incr(key))
        except Exception as e:  # noqa: BLE001 — the session's copy alone
            _warn("the counter's cache failed; the session's copy is used", e)
            n = floor + 1
    try:
        request.session[_mirror_key(scope)] = n
    except Exception:  # noqa: BLE001
        pass
    return n


def _forget(request, scope: str) -> None:
    """The session ends (logout flushes it and its key): drop its count."""
    tag = _tag(request)
    if tag:
        try:
            _cache().delete(_key(tag, scope))
        except Exception as e:  # noqa: BLE001
            _warn("the counter's cache could not be cleared", e)


def _clear(request, scope: str) -> None:
    """The count goes back to zero for a session that goes on. The cache
    keeps the key at zero rather than losing it, so a stale save of the
    session's older copy cannot bring the count back."""
    try:
        request.session.pop(_mirror_key(scope), None)
    except Exception:  # noqa: BLE001
        pass
    tag = _tag(request)
    if tag:
        try:
            _cache().set(_key(tag, scope), 0, _ttl())
        except Exception as e:  # noqa: BLE001
            _warn("the counter's cache could not be cleared", e)


# ── the login's mark of the PIN ─────────────────────────────────────────
def _pin_mark(stored_hash: str) -> str:
    from django.utils.crypto import salted_hmac
    return salted_hmac(_LOGIN_MARK_SALT, stored_hash or "",
                       algorithm="sha256").hexdigest()


def _stored_hash(user) -> str:
    # Read, never create: a login must not write a TraderProfile row.
    from portfolio.trader_profile import TraderProfile
    return (TraderProfile.objects.filter(user=user)
            .values_list("access_pin_hash", flat=True).first() or "")


def stamp_login_mark(request, user) -> None:
    """At login (core.models' user_logged_in receiver): remember which PIN
    this session logged in under. Every login proves the password, so a
    session that changes its PIN afterwards has to come back through
    here before it can act. A failure leaves no mark, which refuses."""
    session = getattr(request, "session", None)
    if session is None:
        return
    try:
        session[LOGIN_MARK_KEY] = _pin_mark(_stored_hash(user))
    except Exception:  # noqa: BLE001 — a login must never fail on this
        session.pop(LOGIN_MARK_KEY, None)
        logger.warning("switch PIN: could not mark the login of %s",
                       _who(user))


def on_login(request, user) -> None:
    """Every login (core.models' user_logged_in receiver): the mark of the
    PIN it logged in under, and a fresh count. A login proves the password,
    and the PIN step when the account has one: that is the fresh proof a
    spent count asks for. Django's login() keeps the session, and its key,
    when the same user logs in again over a live session, so without this
    the count would outlive the very login its refusals send him to. Never
    raises."""
    stamp_login_mark(request, user)
    if getattr(request, "session", None) is not None:
        _clear(request, SESSION)


def _logged_in_with_current_pin(request, profile) -> bool:
    from django.utils.crypto import constant_time_compare
    mark = request.session.get(LOGIN_MARK_KEY) or ""
    return bool(mark) and constant_time_compare(
        mark, _pin_mark(profile.access_pin_hash))


# ── the profile and the hash ────────────────────────────────────────────
def _profile(user):
    """Read, never create (a PIN door must not write a profile row)."""
    from portfolio.trader_profile import TraderProfile
    return TraderProfile.objects.filter(user=user).first()


def _hash_ok(profile, pin) -> bool:
    """THE one hash check of a session's PIN."""
    return bool(profile.check_pin(str(pin or "")))


# ── what is recorded ────────────────────────────────────────────────────
def _record(kind: str, *, user, door: str, act: str, reason: str = "",
            n: Optional[int] = None, ended: bool = False, **extra) -> None:
    try:
        from bot_program.audit import record_pin
        record_pin(kind, who=_who(user), user=user, door=door, act=act,
                   reason=reason, attempts=n, ended=ended, **extra)
    except Exception as e:  # noqa: BLE001
        _warn("a chain row was not written", e)


def _audit_log(request, user, description: str) -> None:
    try:
        from django.db import transaction

        from core.audit import AuditLog
        from core.presence import client_ip
        with transaction.atomic():    # a failed insert spoils no outer block
            AuditLog.log(user, "login", description, target_type="Session",
                         ip_address=client_ip(request))
    except Exception as e:  # noqa: BLE001
        _warn("the audit log line was not written", e)


def _alarm(title: str, lines) -> None:
    """To the alarm chat on the commit (a TAKE TRADE demand can run under
    a row lock), from the request's own process (never a worker, like the
    kill switch's own alarm) but OFF the request path: a short daemon
    thread makes the Telegram call, bounded by the sender's own timeout,
    so a slow or unreachable Telegram never delays the close, the flatten
    or the unlock this alarm reports. Never fails its caller. No money
    figure: names, counts and words only (bot_program/alarm.py)."""
    lines = [str(x) for x in lines]

    def _send(send_alarm, prefix):
        try:
            send_alarm(prefix + title, lines)
        except Exception as e:  # noqa: BLE001
            _warn("the alarm chat was not told", e)
        finally:
            try:          # the thread's own connection, if the send opened one
                from django.db import connections
                connections.close_all()
            except Exception:  # noqa: BLE001
                pass

    def _spawn():
        try:
            from bot_program.alarm import PREFIX, send_alarm
            threading.Thread(target=_send, args=(send_alarm, PREFIX),
                             name=ALARM_THREAD, daemon=True).start()
        except Exception as e:  # noqa: BLE001
            _warn("the alarm thread could not start", e)

    try:
        from django.db import transaction
        transaction.on_commit(_spawn, robust=True)
    except Exception as e:  # noqa: BLE001
        _warn("the alarm could not be queued", e)


def _alarm_stop(request, user, act: str, *, found: bool, n: int) -> None:
    if not _once(request, "alarm", _ttl()):
        return
    if found:
        title = "the trading PIN was given after five wrong answers"
    else:
        title = "wrong trading PINs keep coming on one session"
    _alarm(title, [
        f"Account: {_who(user)}",
        f"At: {act}",
        f"PIN attempts on this session: {int(n)}",
        "The session goes on: the right PIN still closes; anything that "
        "opens or arms ends it.",
        "If this was not you, change the account password now.",
    ])


# ── the check ───────────────────────────────────────────────────────────
def check(request, pin, *, door: str, act: str) -> PinVerdict:
    """The requesting user's trading PIN at a door of class `door` (STOP,
    ACT or LOCK), counted on the session counter. `act` is a short label
    from the code (the audit row, the alarm), never a figure. Never
    raises: a failure refuses, except a right PIN at a STOP door, which
    stops whatever failed."""
    if door not in DOOR_CLASSES:
        raise ValueError(f"unknown PIN door class {door!r}")
    user = getattr(request, "user", None)
    if user is None or not getattr(user, "is_authenticated", False):
        return PinVerdict(ok=False, refusal=PIN_MISSING, door=door)
    act = _label(act)
    try:
        return _check(request, user, pin, door, act)
    except Exception as e:  # noqa: BLE001
        _warn(f"the check failed at {act}", e)
        return _fallback(user, pin, door)


def _fallback(user, pin, door) -> PinVerdict:
    if door == STOP and str(pin or "").strip():
        try:
            profile = _profile(user)
            if profile is not None and profile.has_pin \
                    and _hash_ok(profile, pin):
                return PinVerdict(ok=True, door=door)
        except Exception as e:  # noqa: BLE001
            _warn("the fallback check failed", e)
    return PinVerdict(ok=False, refusal=UNCHECKED, door=door)


def _check(request, user, pin, door, act) -> PinVerdict:
    # ACT: a spent counter ends the session before anything else is read.
    if door == ACT and attempts(request) >= MAX_ATTEMPTS:
        return _end(request, user, door, act, None, first=False)
    if not str(pin or "").strip():
        return PinVerdict(ok=False, refusal=PIN_MISSING, door=door)
    profile = _profile(user)
    if profile is None or not profile.has_pin:
        return PinVerdict(ok=False, refusal=PIN_NOT_SET, door=door)
    if door == ACT and not _logged_in_with_current_pin(request, profile):
        if _once(request, f"again:{act}", _ttl()):
            _record("pin_refused", user=user, door=door, act=act,
                    reason=LOGIN_AGAIN)
        return PinVerdict(ok=False, refusal=LOGIN_AGAIN, door=door)

    n = _reserve(request, SESSION)
    spent = n > MAX_ATTEMPTS
    if spent and door == ACT:
        return _end(request, user, door, act, n, first=False)

    if _hash_ok(profile, pin):
        if not spent:
            _clear(request, SESSION)
            return PinVerdict(ok=True, door=door)
        # STOP: it stops. LOCK: it unlocks. The count stays spent.
        _record("pin_ok_spent", user=user, door=door, act=act, n=n)
        _alarm_stop(request, user, act, found=True, n=n)
        return PinVerdict(ok=True, spent=True, door=door)

    if door == STOP:
        if n < MAX_ATTEMPTS:
            _record("pin_refused", user=user, door=door, act=act,
                    reason=PIN_WRONG, n=n)
            return PinVerdict(ok=False, refusal=PIN_WRONG,
                              attempts_left=MAX_ATTEMPTS - n, door=door)
        if n == MAX_ATTEMPTS:
            _record("pin_spent", user=user, door=door, act=act,
                    reason=PIN_WRONG, n=n, ended=False)
        else:
            if _once(request, "summary", SUMMARY_EVERY_S):
                _record("pin_refused", user=user, door=door, act=act,
                        reason=PIN_WRONG, n=n, summary=True)
            if n == PROBING_AT:
                _alarm_stop(request, user, act, found=False, n=n)
        return PinVerdict(ok=False, refusal=PIN_WRONG, attempts_left=0,
                          spent=True, door=door)

    if spent:                      # LOCK, past five: one guess, and out
        return _end(request, user, door, act, n, first=False)
    if n < MAX_ATTEMPTS:
        _record("pin_refused", user=user, door=door, act=act,
                reason=PIN_WRONG, n=n)
        return PinVerdict(ok=False, refusal=PIN_WRONG,
                          attempts_left=MAX_ATTEMPTS - n, door=door)
    return _end(request, user, door, act, n, first=True)


def _end(request, user, door, act, n, *, first: bool) -> PinVerdict:
    """The session ends: recorded while request.user is still the user,
    then logout() (which flushes the session and its copy of the count).
    No alarm: a session ended is contained."""
    from django.contrib.auth import logout
    if first:
        _record("pin_spent", user=user, door=door, act=act,
                reason=PIN_WRONG, n=n, ended=True)
    else:
        _record("pin_refused", user=user, door=door, act=act,
                reason=LOCKED_OUT, n=n, ended=True)
    label = act[:1].upper() + act[1:]
    _audit_log(request, user, f"{label}: {MAX_ATTEMPTS} failed PIN attempts "
                              f"— session terminated")
    _forget(request, SESSION)
    try:
        logout(request)
    except Exception as e:  # noqa: BLE001
        _warn("the session could not be ended", e)
        return PinVerdict(ok=False, refusal=LOCKED_OUT, attempts_left=0,
                          spent=True, door=door)
    return PinVerdict(ok=False, refusal=LOCKED_OUT, attempts_left=0,
                      logged_out=True, spent=True, door=door)


# ── the login step (pre-session) ────────────────────────────────────────
def check_login_pin(request, user, pin) -> PinVerdict:
    """The PIN step of the two-step login (dashboard/auth_views.login_pin),
    on the pending, anonymous session: its own count (LOGIN_ATTEMPTS_KEY),
    reserved before the hash. Five wrong answers drop the pending login,
    so the password must be proven again (the IP limiter bounds that);
    the caller pops the pending keys when `logged_out` is set. A right
    answer clears the count. Never raises."""
    try:
        if not str(pin or "").strip():
            return PinVerdict(ok=False, refusal=PIN_MISSING, door=LOGIN)
        profile = _profile(user)
        if profile is None or not profile.has_pin:
            return PinVerdict(ok=False, refusal=PIN_NOT_SET, door=LOGIN)
        n = _reserve(request, LOGIN)
        if n <= MAX_ATTEMPTS and _hash_ok(profile, pin):
            _clear(request, LOGIN)
            return PinVerdict(ok=True, door=LOGIN)
        if n < MAX_ATTEMPTS:
            return PinVerdict(ok=False, refusal=PIN_WRONG,
                              attempts_left=MAX_ATTEMPTS - n, door=LOGIN)
        _clear(request, LOGIN)
        _record("pin_spent", user=user, door=LOGIN, act="the login PIN",
                reason=PIN_WRONG, n=n, ended=True)
        _audit_log(request, user, f"Login PIN: {MAX_ATTEMPTS} failed "
                                  f"attempts — password asked again")
        if _account_once(user, "login_alarm", 3600):
            _alarm("five wrong login PINs after the right password", [
                f"Account: {_who(user)}",
                "The pending login was dropped: the password is asked "
                "again.",
                "If this was not you, someone knows the account password: "
                "change it now.",
            ])
        return PinVerdict(ok=False, refusal=LOCKED_OUT, attempts_left=0,
                          logged_out=True, spent=True, door=LOGIN)
    except Exception as e:  # noqa: BLE001
        _warn("the login PIN check failed", e)
        return PinVerdict(ok=False, refusal=UNCHECKED, door=LOGIN)


def _account_once(user, what: str, ttl: int) -> bool:
    try:
        return bool(_cache().add(f"trading_pin:{what}:{user.pk}", 1, ttl))
    except Exception as e:  # noqa: BLE001
        _warn("a once-guard could not be read", e)
        return False


# ── the lazy gate ───────────────────────────────────────────────────────
class PinGate:
    """A verdict asked for only where a PIN is demanded: truthy iff the
    PIN checked out. Code that already asks `if not pin_ok` takes it in
    place of a bool. Never asked (a paper close, a disarm, a book with no
    live row), it counts nothing; asked twice, it counts once."""

    __slots__ = ("_request", "_pin", "_door", "_act", "_verdict")

    def __init__(self, request, pin, *, door: str, act: str):
        if door not in DOOR_CLASSES:
            raise ValueError(f"unknown PIN door class {door!r}")
        self._request = request
        self._pin = pin
        self._door = door
        self._act = act
        self._verdict = None

    def __bool__(self) -> bool:
        if self._verdict is None:
            self._verdict = check(self._request, self._pin,
                                  door=self._door, act=self._act)
        return bool(self._verdict.ok)

    @property
    def verdict(self) -> Optional[PinVerdict]:
        return self._verdict

    @property
    def refused(self) -> bool:
        return self._verdict is not None and not self._verdict.ok

    def __repr__(self) -> str:      # never the PIN
        return f"<PinGate {self._door} {self._act!r}>"


def gate(request, pin, *, door: str, act: str) -> PinGate:
    return PinGate(request, pin, door=door, act=act)


def refusal_of(answer) -> Optional[PinVerdict]:
    """The refused verdict behind a gate, or None (not asked, ok, or a
    plain bool from a test's patch)."""
    if isinstance(answer, PinGate) and answer.refused:
        return answer.verdict
    return None


def arms_live(*, was_enabled, was_mode, want_enabled, want_mode) -> bool:
    """True when this write would leave a config armed LIVE that was not:
    OFF -> ON in live mode, or an enabled config moved to live. OFF and
    paper never."""
    return bool(want_enabled) and want_mode == "live" and not (
        bool(was_enabled) and was_mode == "live")


# ── the words ───────────────────────────────────────────────────────────
def sentence(verdict, *, subject: str, nothing: str) -> str:
    """One English sentence for a refused verdict: what it was, what did
    not happen, and what to do. Never how close a PIN was, never the PIN,
    its length or its hash."""
    refusal = getattr(verdict, "refusal", "") or UNCHECKED
    door = getattr(verdict, "door", "") or ACT
    if refusal == PIN_MISSING:
        return (f"{subject} takes your trading PIN and none was entered, "
                f"so {nothing}.")
    if refusal == PIN_NOT_SET:
        then = ("then log in again with it" if door == ACT
                else "then try again")
        return (f"{subject} takes your trading PIN and your account has "
                f"none, so {nothing}: set one on your profile, {then}.")
    if refusal == LOGIN_AGAIN:
        return (f"This session did not log in with your current trading "
                f"PIN, so {nothing}: log in again with your password and "
                f"PIN first.")
    if refusal == PIN_WRONG:
        if getattr(verdict, "spent", False):
            return (f"Incorrect trading PIN, so {nothing}; the right PIN "
                    f"still works here, but this session must log in again "
                    f"before it opens anything.")
        n = getattr(verdict, "attempts_left", None) or 0
        left = f"{n} attempt{'' if n == 1 else 's'} left"
        if door == STOP:
            return (f"Incorrect trading PIN, so {nothing}; {left} before "
                    f"this session can no longer open or arm anything.")
        return (f"Incorrect trading PIN, so {nothing}; {left} before this "
                f"session ends.")
    if refusal == LOCKED_OUT:
        return f"Too many incorrect PINs: the session has ended and {nothing}."
    return (f"Your trading PIN could not be checked just now, so "
            f"{nothing}: try again.")


def json_refusal(verdict, *, subject: str, nothing: str, extra=None) -> dict:
    """A JSON door's refusal: its own keys, plus the sentence, the
    pin_required flag and whether the session ended."""
    out = dict(extra or {})
    out.update({"error": sentence(verdict, subject=subject, nothing=nothing),
                "pin_required": True,
                "logged_out": bool(getattr(verdict, "logged_out", False))})
    return out


def no_pin_here(request, *, act: str, via: str, user=None) -> None:
    """Record a live arm refused at a door that never takes a PIN (a form
    that cannot ask, the Django admin); once per session and act."""
    try:
        user = user if user is not None else getattr(request, "user", None)
        if request is not None and not _once(request, f"nopin:{act}",
                                             _ttl()):
            return
        _record("pin_refused", user=user, door=ACT, act=_label(act),
                reason=NO_PIN_HERE, via=str(via)[:20])
    except Exception as e:  # noqa: BLE001
        _warn("a refusal was not recorded", e)
