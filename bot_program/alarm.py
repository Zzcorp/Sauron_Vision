"""THE ALARM BOT: a second bot that rings only when Sauron is in trouble (2026-09-28).

The operator, 2026-09-28: "pour éviter de spammer le grand Gandalf de
messages de trading et ne le sonner que pour de vraies urgences". Le grand
Gandalf is his father, who runs Sauron from his phone while the operator
is away. The Eye's group carries every fill, signal, digest and Morgul
warning; this bot carries none of it. It is a second bot (its own token,
TOKEN_ENV) in a second group (CHAT_ENV: the operator, his father and this
bot -- the Eye's bot is not in it), and it says one kind of thing.

WHAT HE DECIDED
  * Critical only: no warning reaches this chat.
  * Both of them, in one shared group.
  * NEVER an all-is-well message: no heartbeat, no daily "nothing wrong",
    no "back to normal". A problem that stops is silence. A reply to a
    command somebody typed says what is true, "No critical problem now"
    included: that is an answer, not a message nobody asked for.
  * Two commands, and nothing else: /status and /stopall.
  * No money figure in any text it sends: no amount, no P&L, no equity,
    no margin, no price. Counts, names, symbols, numbers of rows and
    times; tests/test_alarm_bot.py runs a money pattern over every text.

WHAT IT SAYS (each an Alarm: a stable key, a title, a few lines)
  A  Morgul (bot_program/morgul.py), relayed after each run of its beat
     (relay_morgul): every CRITICAL finding, by its own severity, never
     its guard's -- its title and its label, never its facts, which carry
     amounts (margin, daily loss); a guard that can find something
     critical and could not run, which Morgul files as a warning ("a
     safety check cannot run": a blind guard is not a healthy one); the
     brake stopping bots, once, in the brake's own words (brake_lines).
  B  Automation paused: the platform_master switch off, one line. While
     it is off the component, feed and broker faults are the pause
     itself, not N faults, and are not said; a close abandoned at the
     broker still is. Once it is back on, a row the pause froze (every
     gated task skips before mark_run) is not called stopped until its
     beat has had its grace to stamp it again (RESUME_GRACE_S).
  C  A close the platform gave up on (pending_closes._give_up: ERROR,
     closed_at unset, a real position): nobody retries it any more.
  D  A safety-critical component (CRITICAL_COMPONENTS) failing or stopped,
     and a declared quote feed not delivering: the digest's own
     collect_faults, its "ran but did nothing" bucket never. Its NAME and
     the kind in words, never its message (ages, and sometimes amounts).
     FLOOD_AT or more stopped at once is the scheduler, said once.
  E  A live-world broker account that has not answered
     BROKER_MISS_ALERT_AFTER syncs in a row (the sync's own miss count),
     named by broker and number, never by username.
  F  The emergency flatten (engine/kill_switch.execute_kill_switch) having
     run, counts only, on the commit and from the kill's own process
     (after_kill_switch): a flatten is the moment the workers may be
     what is broken, so its announcement never waits behind one.
  The brain being down is not here: no money moves on it, and its skip
  is a feed fault by design (the feeds are in D).

HOW OFTEN (the memory: STATE_KEY per source, seven days, never raises)
  A standing problem is said when first seen and again every three hours
  while it stands (Morgul's REMIND_S); a component or feed fault, and the
  pause, every 24 hours; an event (a booking, the brake, the flatten)
  once. Nothing is ever said about a problem that stopped. A delivery
  Telegram refused is not remembered as said, so the next pass says it
  (an event from its own memory, once its source is gone). A cache that
  is down or flushed forgets, and a standing problem is said again: said
  twice is better than never said. More than MAX_MESSAGES due at once
  go as ONE message that names them. One pass per source at a time.

WHAT IT OBEYS: the alarm chat, and nothing else
    /status  /etat              counts and names: automation, bots and
                                positions (how many, how many live), the
                                guards, the critical problems now, the time
    /stopall  /stop all|tout    THE BRAKE, the Eye's own apply_brake for
                                every account with a bot running:
                                bots OFF, never on, their unfilled live
                                orders withdrawn (withdraw=True, the
                                human's brake of 213c716); no position is
                                closed, the master switch is not touched
    /help  /aide  /start        the two commands
  Another chat, another bot's command (/cmd@OtherBot, against getMe),
  anything else: no reply. The Eye's order, kept whole: one batch at a
  time under an advisory lock of its own (BATCH_LOCK_ID), a stale or
  rate-limited command dropped but never the brake, a batch that ends at
  the brake, the replies and the belt on the commit, and the confirm
  getUpdates(offset = last + 1) only after it.

THE GATE: its own switch, COMPONENT_KEY, OFF on arrival, and never the
master switch -- a pause it could not report would be a gate that goes
quiet exactly when the platform does. alarm_task gates the two beat
tasks; send_alarm reads the switch itself, because Morgul's run and the
kill switch call it directly. config() refuses the Eye's token (two
pollers on one bot steal each other's updates) and the Eye's chats (the
trading messages would pour into the father's).

Doors: bot_program.tasks.poll_telegram_alarm (every 15 s, fast queue) and
run_alarm_sentinel (every 10 min); the hook in run_morgul_guards; the
hook in the two kill-switch views (after_kill_switch); `manage.py alarm`
(prints; --send, --test, --chats); the /health/ row (health_row).
"""
from __future__ import annotations

import hashlib
import logging
import os
from datetime import datetime
from datetime import timezone as dt_tz
from functools import partial, wraps

import requests

from bot_program import morgul
from bot_program import telegram_eye as eye

logger = logging.getLogger(__name__)

COMPONENT_KEY = "telegram_alarm"
#: Read at call time, never at import: a new token reaches the next pass.
#: The _TOKEN suffix is what core.secret_scrub redacts from every log.
TOKEN_ENV = "TELEGRAM_ALARM_BOT_TOKEN"
CHAT_ENV = "TELEGRAM_ALARM_CHAT_ID"
#: SOS: every message nobody asked for leads with it. Not the siren: the
#: Eye's news alerts already wear that one (telegram_alert.MARKS).
MARK = "\U0001F198"
PREFIX = "Sauron alarm — "

STANDING, FAULT, EVENT = "standing", "fault", "event"
#: How long before a problem still standing is said again; an event never.
REMIND_S = {STANDING: morgul.REMIND_S, FAULT: 24 * 3600, EVENT: None}
#: One memory per source ("morgul", "sentinel"): each is written by one
#: pass at a time under its own lock, so neither overwrites the other.
STATE_KEY = "telegram_alarm:state:{source}"
STATE_TTL_S = 7 * 86400
LOCK_KEY = "telegram_alarm:lock:{source}"
#: The sentinel runs every 10 min; a pass that died frees its lock first.
LOCK_S = 540
#: More due at once than this, and they go as one message that names them:
#: a flushed cache or a bad morning must not ring the phone ten times.
MAX_MESSAGES = 5
#: This many safety-critical components stopped at once is the beat or
#: the workers, not N faults: one line.
FLOOD_AT = 4

#: The components whose failure or silence can cost money, by their
#: PlatformComponent keys (collect_faults reports only those switched on).
#: The close drain (retry_pending_closes) and the bar refresh carry no
#: switch: nothing can call them stopped, and the closes they give up on
#: are said by C.
CRITICAL_COMPONENTS = (
    "pipeline_asset_bots",   # the bot tick and the reconcile: without it
                             # no bot manages its positions
    "broker_account_sync",   # the three broker walks: what the account
                             # holds, and the miss count E reads
    "scraper_live_quotes",   # the marks the bots decide and fill paper on
    "scraper_crypto",        # crypto marks
    "scraper_forex",         # forex marks
    "scraper_commodities",   # commodity marks
    "pipeline_indicators",   # the indicators the signals read
    "pipeline_signals",      # the signals the bots vote on
    "morgul_guards",         # the watchdog itself: a stopped guard is blind
)
FAULT_WORDS = {"errors": "is failing", "silent": "has stopped running",
               "feeds": "is not delivering quotes"}
#: After START PLATFORM, a row that last ran before the switch came back
#: on is the pause, not a stop: guarded_task skips before mark_run, so
#: every gated row froze for the whole pause, and the digest calls a row
#: of a day's beat stopped at 26 h. Not said until its beat has had time
#: to stamp it again -- RESUME_PERIODS of its period (one late beat and
#: one slow run), RESUME_GRACE_S at least; still silent past that, it is
#: the scheduler.
RESUME_PERIODS = 2
RESUME_GRACE_S = 15 * 60
BROKER_WORDS = {"ibkr": "IBKR", "saxo": "Saxo", "etoro": "eToro"}
#: Filed as a warning guard, and turns critical at four hours
#: (morgul.STUCK_CRIT_S): blind, it hides criticals too.
ESCALATING_GUARDS = ("stuck_close",)

# ── the poll ─────────────────────────────────────────────────────────────
#: The alarm poll's batch lock (pg_try_advisory_xact_lock), not the Eye's
#: (telegram_eye.BATCH_LOCK_ID): sharing one, either poll would skip
#: while the other held it, and a /stopall would wait.
BATCH_LOCK_ID = 20260928
BRAKE_VERDICT = "answered:stopall"
NOTE_KEY = "telegram_alarm:note:{kind}"
NOTE_EVERY_S = 3600
FAILING_KEY = "telegram_alarm:failing:{method}"
RATE_KEY = "telegram_alarm:rate:{chat}"
#: The bot's own username (getMe), a day, per bot: a hash, never the token.
ME_KEY = "telegram_alarm:me:{digest}"
ME_TTL_S = 86400
MAX_PROBLEMS_LISTED = 12


class Alarm:
    """One critical problem: its stable key (the dedupe's), the words
    after PREFIX, its lines, and its kind (STANDING, FAULT or EVENT)."""

    __slots__ = ("key", "words", "lines", "kind")

    def __init__(self, key, words, lines=(), *, kind=STANDING):
        assert kind in REMIND_S, kind
        self.key = str(key)
        self.words = str(words)
        self.lines = [str(ln) for ln in lines if str(ln or "").strip()]
        self.kind = kind

    @property
    def title(self) -> str:
        return PREFIX + self.words

    def __repr__(self):
        return f"Alarm({self.key})"


# ── the switch and the configuration ─────────────────────────────────────

def enabled() -> bool:
    """Its own switch, and only its own: never platform_master."""
    from core.platform_control import is_component_enabled
    return is_component_enabled(COMPONENT_KEY)


def _eye_chats() -> set:
    from alerts.models import UserNotificationPrefs
    return {str(c or "").strip() for c in UserNotificationPrefs.objects
            .exclude(telegram_chat_id="")
            .values_list("telegram_chat_id", flat=True)}


def config() -> tuple:
    """(token, chat, why not): `why not` is "" when the alarm bot may run,
    else one sentence -- never the token."""
    token = os.getenv(TOKEN_ENV, "").strip()
    chat = os.getenv(CHAT_ENV, "").strip()
    if not token:
        why = f"{TOKEN_ENV} is not set"
    elif not chat:
        why = f"{CHAT_ENV} is not set"
    elif token == os.getenv("TELEGRAM_BOT_TOKEN", "").strip():
        why = (f"{TOKEN_ENV} is the Eye's token: two pollers on one bot "
               f"steal each other's updates; create a second bot")
    elif chat == os.getenv("TELEGRAM_CHAT_ID", "").strip():
        why = (f"{CHAT_ENV} is TELEGRAM_CHAT_ID: the platform's trading "
               f"messages go to that chat")
    elif chat in _eye_chats():
        why = (f"{CHAT_ENV} is a chat saved on /notifications/settings/: "
               f"the Eye's replies and alerts go to that chat")
    else:
        why = ""
    return token, chat, why


def _once(kind: str) -> bool:
    """True the first time `kind` comes up in NOTE_EVERY_S; True as well
    when the cache is down: better twice than never."""
    from django.core.cache import cache
    try:
        return bool(cache.add(NOTE_KEY.format(kind=kind), 1, NOTE_EVERY_S))
    except Exception:  # noqa: BLE001
        return True


def _note(kind: str, text: str) -> None:
    """A repeated fault at WARNING once an hour, at DEBUG in between."""
    if _once(kind):
        logger.warning("[telegram alarm] %s", text)
    else:
        logger.debug("[telegram alarm] %s", text)


def _clean(text, token) -> str:
    """Log text with the token out of it, whatever its variable is named."""
    from core.secret_scrub import scrub
    out = scrub(str(text or ""))
    return out.replace(token, "<token>") if token else out


def alarm_task(func):
    """The gate of the two beat tasks: the telegram_alarm switch, and
    NOTHING else (core.task_gate.guarded_task reads platform_master
    first, and the pause is one of the things this bot reports). Off, a
    pass returns skipped and writes nothing; on, it runs and the row is
    stamped as the gate stamps it (judge_result, mark_run; a truthy
    `idle` writes nothing, and a pass that raised is an error). The key
    is stamped on the wrapper, so the digest reads the beat's cadence
    off it and calls the row stopped when it stops moving."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        from core.platform_control import get_component
        from core.task_gate import judge_result
        if not enabled():
            logger.info("[telegram alarm] %s is off: %s skipped",
                        COMPONENT_KEY, func.__name__)
            return {"status": "skipped", "reason": f"{COMPONENT_KEY} off"}
        comp = get_component(COMPONENT_KEY)
        try:
            result = func(*args, **kwargs)
        except Exception as e:
            if comp:
                comp.mark_run(success=False, message=str(e)[:500])
            raise
        if comp and not (isinstance(result, dict) and result.get("idle")):
            status, msg = judge_result(result)
            comp.mark_run(success=status == "success", message=msg,
                          status=status)
        return result

    wrapper.component_key = COMPONENT_KEY
    return wrapper


# ── the sender ───────────────────────────────────────────────────────────

def _deliver(token, chat, reply) -> bool:
    """One Reply to the alarm chat as the alarm bot, in the house style
    (message_parts: HTML, every field escaped, under 4,096; fit first, so
    the brake's closing words stay whole). True when Telegram took it.
    Never raises: a refusal is logged with Telegram's own words, a
    transport error without the token."""
    from alerts.channels.telegram_alert import (SEND_TIMEOUT_S,
                                                message_parts, post_message)
    title = str(getattr(reply, "title", ""))[:120]
    try:
        reply = eye.fit(reply)
        text, _markup, _fallback = message_parts(
            reply.title, reply.body, lines=reply.lines or None,
            mark=reply.mark)
        answer, _refused = post_message(
            token, {"chat_id": chat, "text": text, "parse_mode": "HTML",
                    "disable_web_page_preview": True},
            timeout=SEND_TIMEOUT_S)
    except Exception as e:  # noqa: BLE001 (an alarm never breaks its caller)
        logger.warning("[telegram alarm] %r not sent: %s", title,
                       _clean(e, token)[:200])
        return False
    if not getattr(answer, "ok", False):
        logger.warning("[telegram alarm] refused (%s) %r: %s",
                       getattr(answer, "status_code", "?"), title,
                       _clean(getattr(answer, "text", ""), token)[:200])
        return False
    return True


def send_alarm(title, lines=()) -> bool:
    """One alarm to the alarm chat: True when Telegram took it. Nothing
    while the switch is off or the configuration is refused (said at
    WARNING once an hour). No quiet hours, no bot-alert preference, no
    Notification row: this chat is the whole of it."""
    if not enabled():
        logger.debug("[telegram alarm] off: %r not sent", str(title)[:120])
        return False
    token, chat, why = config()
    if why:
        _note("config", f"nothing sent: {why}")
        return False
    return _deliver(token, chat, eye.Reply(MARK, title, list(lines)))


# ── the memory ───────────────────────────────────────────────────────────

def _load(key) -> dict:
    from django.core.cache import cache
    try:
        value = cache.get(key)
    except Exception:  # noqa: BLE001 (a cache down forgets: said twice)
        logger.warning("[telegram alarm] the cache could not be read")
        return {}
    return value if isinstance(value, dict) else {}


def _store(key, value) -> None:
    from django.core.cache import cache
    try:
        cache.set(key, value, STATE_TTL_S)
    except Exception:  # noqa: BLE001
        logger.warning("[telegram alarm] the cache could not be written")


def _lock(source) -> bool:
    """One pass per source at a time; a cache that cannot answer lets the
    pass go on (said twice is better than never said)."""
    from django.core.cache import cache
    try:
        return bool(cache.add(LOCK_KEY.format(source=source), "held",
                              LOCK_S))
    except Exception:  # noqa: BLE001
        logger.warning("[telegram alarm] the lock could not be read; "
                       "running")
        return True


def _unlock(source) -> None:
    from django.core.cache import cache
    try:
        cache.delete(LOCK_KEY.format(source=source))
    except Exception:  # noqa: BLE001 (it expires in LOCK_S anyway)
        logger.warning("[telegram alarm] the lock could not be released")


def _parse(value):
    return eye._parse_iso(value) if value else None


def _due(alarm, entry, now) -> bool:
    last = _parse(entry.get("sent"))
    if last is None:
        return True
    every = REMIND_S[alarm.kind]
    return every is not None and (now - last).total_seconds() >= every


def _bundle(due, now):
    """Too many at once: one message naming them all."""
    return eye.Reply(MARK, PREFIX + f"{len(due)} critical problems at once",
                     eye._cap([f"{eye.BULLET}{a.words}" for a in due],
                              eye.MAX_LINES - 1)
                     + [f"Checked: {eye.when(now)}"])


def _settle(source, alarms, now) -> dict:
    """Say what is due, remember what was said. Due: never said, or said
    REMIND_S of its kind ago and still standing; an event once. A problem
    absent from this pass is not said and not cleared: nothing here ever
    says a problem stopped, and one that comes back inside its window is
    not said again. An event Telegram refused is said from memory on the
    next pass even once its source is gone. Entries unseen for
    STATE_TTL_S drop out."""
    key = STATE_KEY.format(source=source)
    stamp = now.isoformat()
    cur = {}
    for k, entry in _load(key).items():
        seen = _parse(entry.get("seen")) if isinstance(entry, dict) else None
        if seen is not None and (now - seen).total_seconds() < STATE_TTL_S:
            cur[k] = dict(entry)
    due, present = [], set()
    for alarm in alarms:
        if alarm.key in present:
            continue
        present.add(alarm.key)
        entry = cur.setdefault(alarm.key, {"first": stamp})
        entry.update(seen=stamp, kind=alarm.kind)
        if alarm.kind == EVENT:
            entry.update(words=alarm.words, lines=list(alarm.lines))
        if _due(alarm, entry, now):
            due.append(alarm)
    for k, entry in cur.items():
        if (k not in present and entry.get("kind") == EVENT
                and not entry.get("sent") and entry.get("words")):
            due.append(Alarm(k, entry["words"], entry.get("lines") or (),
                             kind=EVENT))
    sent = failed = 0
    if len(due) > MAX_MESSAGES:
        batches = [(due, _bundle(due, now))]
    else:
        batches = [([a], eye.Reply(MARK, a.title, a.lines)) for a in due]
    for said, reply in batches:
        if send_alarm(reply.title, reply.lines):
            for a in said:
                cur[a.key]["sent"] = stamp
            sent += 1
        else:
            failed += len(said)
    _store(key, cur)
    return {"problems": len(present), "due": len(due), "sent": sent,
            "failed": failed}


# ── A: Morgul's run ──────────────────────────────────────────────────────

def _morgul_words(title) -> str:
    """"Morgul — a close stuck at the broker" -> "a close stuck at the
    broker"."""
    text = str(title or "")
    return text.split("—", 1)[1].strip() if "—" in text else text


def morgul_alarms(report) -> list:
    """What of one Morgul run this chat hears: each critical finding
    (its title and its label; its facts carry amounts and never leave
    Morgul), a guard that can find something critical and could not run,
    and the brake having stopped bots (an event)."""
    out = []
    for f in report.findings:
        if f.subject == "error":
            if (f.guard.severity == "critical"
                    or f.guard.key in ESCALATING_GUARDS):
                out.append(Alarm(
                    f"morgul|{f.key}",
                    f"a safety check cannot run: {f.guard.name}",
                    [f"The Morgul guard {f.guard.name.lower()} raised "
                     f"instead of reading the book.",
                     "Until it runs again, nothing watches what it "
                     "watches."]))
            continue
        if f.severity != "critical":
            continue
        out.append(Alarm(f"morgul|{f.key}", _morgul_words(f.title),
                         [f.label, "Morgul watches it; details on /health/."],
                         kind=EVENT if f.event else STANDING))
    for key, outcome in (report.outcomes or {}).items():
        if not outcome or outcome[0] != "stopped" or not outcome[1]:
            continue
        out.append(Alarm(
            f"brake|{key}",
            f"the brake stopped {eye._plural(len(outcome[1]), 'bot')}",
            morgul.brake_lines([outcome])
            + [f"At: {eye.when(report.ctx.now)}"], kind=EVENT))
    return out


def relay_morgul(report) -> dict:
    """After each Morgul run of the beat (tasks.run_morgul_guards): its
    critical findings to the alarm chat, on this bot's own memory and
    cadence, never Morgul's (a finding Morgul said as a warning, or while
    this switch was off, is new here). Nothing while the switch is off,
    the configuration is refused, or Morgul's run was idle."""
    if report is None or (report.result or {}).get("idle"):
        return {}
    if not enabled():
        return {}
    _token, _chat, why = config()
    if why:
        _note("config", f"Morgul not relayed: {why}")
        return {}
    if not _lock("morgul"):
        logger.warning("[telegram alarm] another relay holds the lock; this "
                       "Morgul run was not relayed")
        return {}
    try:
        return _settle("morgul", morgul_alarms(report), report.ctx.now)
    finally:
        _unlock("morgul")


# ── B to E: the sentinel's reads ─────────────────────────────────────────

def _paused() -> bool:
    from core.platform_control import is_component_enabled
    return not is_component_enabled("platform_master")


def read_pause(now) -> list:
    """B: the master switch off."""
    if not _paused():
        return []
    return [Alarm("master|off",
                  "automation is paused: no bot trades and no safety check "
                  "runs",
                  ["While it is paused no bot manages its positions; stops "
                   "resting at the broker still hold.",
                   "START PLATFORM on /admin-dashboard/ resumes it."],
                  kind=FAULT)]


def read_abandoned(now) -> list:
    """C: closes the platform gave up on (pending_closes._give_up flips
    the row to ERROR and never sets closed_at; dashboard/views_close
    ._abandoned_count reads the same rows): still open at the broker, and
    nothing retries them."""
    from bot_program.asset_models import AssetBotTrade
    rows = (AssetBotTrade.objects.filter(status="ERROR", paper=False,
                                         closed_at__isnull=True)
            .order_by("pk"))
    return [Alarm(f"abandoned|trade:{t.pk}",
                  f"a close was abandoned: {str(t.symbol).upper()} #{t.pk} "
                  f"may still be open at the broker",
                  ["The platform stopped retrying this close.",
                   "Close it at the broker; the history is on /forensics/."])
            for t in rows]


def _name(entry) -> str:
    return (str(entry.get("name") or "").strip()
            or str(entry.get("key") or "a component").replace("_", " "))


def _resumed_at():
    """When the master switch was last flipped: its row's updated_at,
    which the toggle views and `manage.py component` stamp when they
    save it (nothing runs mark_run on a switch). None without a row."""
    from core.platform_control import PlatformComponent
    return (PlatformComponent.objects.filter(key="platform_master")
            .values_list("updated_at", flat=True).first())


def _frozen_by_the_pause(entry, now, resumed, periods) -> bool:
    """A silent row whose silence began before the resume (its last run,
    or never), inside its grace since the resume: the pause, not a stop.
    A resume in the future is no resume (a clock that disagrees)."""
    began = entry.get("last_run")
    if began is not None and began >= resumed:
        return False
    hours = float((periods or {}).get(entry.get("key")) or 0)
    grace = max(RESUME_PERIODS * hours * 3600, RESUME_GRACE_S)
    return 0 <= (now - resumed).total_seconds() < grace


def read_faults(now) -> list:
    """D: the digest's collect_faults, its errors and silent buckets for
    CRITICAL_COMPONENTS only, and every quote feed not delivering. A row
    the pause froze is not silent until its grace after the resume has
    passed (_frozen_by_the_pause)."""
    from core.component_digest import beat_periods, collect_faults
    faults = collect_faults(now)
    errors = [e for e in faults.get("errors") or []
              if e.get("key") in CRITICAL_COMPONENTS]
    silent = [e for e in faults.get("silent") or []
              if e.get("key") in CRITICAL_COMPONENTS]
    resumed = _resumed_at() if silent else None
    if resumed is not None:
        periods = beat_periods()
        silent = [e for e in silent
                  if not _frozen_by_the_pause(e, now, resumed, periods)]
    out = []
    if len(silent) >= FLOOD_AT:
        out.append(Alarm(
            "fault|flood",
            f"the scheduler seems stopped: {len(silent)} safety-critical "
            f"tasks have not run",
            ["Their names: " + ", ".join(_name(e) for e in silent) + ".",
             "Check the beat and the workers: ./deploy/dc ps"], kind=FAULT))
        silent = []
    for bucket, items in (("errors", errors), ("silent", silent),
                          ("feeds", faults.get("feeds") or [])):
        for e in items:
            out.append(Alarm(f"fault|{bucket}|{e.get('key')}",
                             f"{_name(e)} {FAULT_WORDS[bucket]}",
                             ["Details on /health/."], kind=FAULT))
    return out


def read_brokers(now) -> list:
    """E: every keyed LIVE-world account the sync walks (IBKR on a port
    that is not paper, Saxo not SIM, eToro not demo) whose consecutive
    miss count stands at BROKER_MISS_ALERT_AFTER or more. Not while the
    sync's switch is off: its count is then frozen, not current."""
    from django.core.cache import cache

    from bot_program.models import EtoroAccount, IBKRAccount, SaxoAccount
    from bot_program.tasks import BROKER_MISS_ALERT_AFTER, _broker_kind
    from core.platform_control import is_component_enabled
    if not is_component_enabled("broker_account_sync"):
        return []
    rows = ([a for a in IBKRAccount.objects.exclude(account_id_enc="")
             .order_by("pk") if a.env != "paper"]
            + list(SaxoAccount.objects.exclude(app_key_enc="")
                   .filter(sim=False).order_by("pk"))
            + list(EtoroAccount.objects.exclude(api_key_enc="")
                   .filter(demo=False).order_by("pk")))
    out = []
    for acct in rows:
        kind = _broker_kind(acct)
        misses = int(cache.get(f"broker_sync:miss:{kind}:{acct.pk}") or 0)
        if misses < BROKER_MISS_ALERT_AFTER:
            continue
        out.append(Alarm(
            f"broker|{kind}:{acct.pk}",
            f"{BROKER_WORDS.get(kind, kind)} account #{acct.pk} has not "
            f"answered {misses} syncs in a row",
            ["The platform cannot read this live account; what it shows "
             "of it is going stale.", "Check the connection on /brokers/."]))
    return out


#: (what, reader): a reader that raises is said, never silence.
READERS = (("the automation switch", read_pause),
           ("abandoned closes", read_abandoned),
           ("platform health", read_faults),
           ("the broker syncs", read_brokers))
#: What the pause itself causes: not said while paused.
PAUSED_OUT = (read_faults, read_brokers)


def problems(now=None) -> list:
    """Every critical problem B to E, now. Never raises."""
    from django.utils import timezone
    now = now or timezone.now()
    try:
        paused = _paused()
    except Exception:  # noqa: BLE001 (read_pause says it)
        paused = False
    out = []
    for what, reader in READERS:
        if paused and reader in PAUSED_OUT:
            continue
        try:
            out.extend(reader(now))
        except Exception as e:  # noqa: BLE001
            logger.warning("[telegram alarm] %s could not be read (%s)",
                           what, type(e).__name__, exc_info=True)
            out.append(Alarm(f"blind|{reader.__name__}",
                             f"the alarm bot cannot check {what}",
                             [f"The read raised {type(e).__name__}; the "
                              f"worker log has it."], kind=FAULT))
    return out


def sentinel(*, now=None) -> dict:
    """One pass of B to E (tasks.run_alarm_sentinel, `manage.py alarm
    --send`): the problems, the dedupe, the messages, the memory. A pass
    whose alarm Telegram refused is an error, so the component row (and
    the Eye's morning digest) says the alarm bot cannot speak."""
    from django.utils import timezone
    now = now or timezone.now()
    _token, _chat, why = config()
    if why:
        _note("config", f"the sentinel did not run: {why}")
        return {"status": "success", "skipped": why}
    if not _lock("sentinel"):
        return {"status": "success",
                "idle": "another alarm pass is in progress"}
    try:
        out = _settle("sentinel", problems(now), now)
    finally:
        _unlock("sentinel")
    result = {"status": "success", **out}
    if out["failed"]:
        result.update(status="error",
                      error=f"{out['failed']} alarm(s) not delivered; said "
                            f"again on the next pass")
    return result


# ── F: the emergency flatten ─────────────────────────────────────────────

def kill_counts(results, now=None) -> dict:
    """The counts of execute_kill_switch's results, and nothing else: its
    errors name symbols and broker words, its reason is typed text."""
    from django.utils import timezone
    r = results if isinstance(results, dict) else {}

    def n(*keys):
        return sum(int(r.get(k) or 0) for k in keys)
    return {"bots": n("bots_disabled", "asset_bots_disabled"),
            "closed": n("positions_closed", "asset_positions_closed",
                        "portfolio_positions_closed"),
            "errors": len(r.get("errors") or []),
            "waiting": len(r.get("paper_waiting") or []),
            "at": (now or timezone.now()).isoformat()}


def announce_kill_switch(counts) -> bool:
    """The flatten, said once per execution, in counts."""
    counts = counts if isinstance(counts, dict) else {}
    lines = [f"Bots turned off: {int(counts.get('bots') or 0)}",
             f"Positions closed: {int(counts.get('closed') or 0)}",
             f"Close errors: {int(counts.get('errors') or 0)}"]
    if counts.get("errors"):
        lines.append("Some positions may still be open at the broker — "
                     "check /positions/.")
    if counts.get("waiting"):
        lines.append(f"Paper positions left open, their market shut: "
                     f"{int(counts['waiting'])}")
    lines.append(f"At: {eye.when(_parse(counts.get('at')))}")
    return send_alarm(PREFIX + "the emergency flatten ran", lines)


def after_kill_switch(results) -> None:
    """The two kill-switch views call this once execute_kill_switch has
    returned: the counts, and only the counts, to the alarm chat on the
    commit (transaction.on_commit; at once in a view that runs in
    autocommit). From the kill's own process, never through a worker: a
    flatten is the moment the workers may be what is broken, and one
    fenced call bounded by the sender's timeout costs the page nothing
    it has not already paid at the broker. Never raises."""
    try:
        if not enabled():
            return
        from django.db import transaction
        transaction.on_commit(partial(announce_kill_switch,
                                      kill_counts(results)), robust=True)
    except Exception as e:  # noqa: BLE001 (the kill is done; never fail it)
        logger.warning("[telegram alarm] the flatten was not announced (%s)",
                       type(e).__name__)


# ── the commands ─────────────────────────────────────────────────────────

STATUS_TITLE = PREFIX + "status"
STOP_TITLE = PREFIX + "stop all"
HELP_TITLE = PREFIX + "commands"


def parse(text) -> tuple:
    """(command, "") for the two commands and the help, else (None, ""):
    telegram_eye.parse reads the words (case, accents, French aliases),
    and everything but these is not answered here."""
    command, arg = eye.parse(text)
    if command == "status":
        return "status", ""
    if command == "stopall" or (command == "stop"
                                and eye._fold(arg) in ("all", "tout",
                                                       "tous")):
        return "stopall", ""
    if command == "help":
        return "help", ""
    return None, ""


def build_help():
    return eye.Reply(eye.MARK_HELP, HELP_TITLE, [
        "/status — what is wrong now, in counts and names, never an amount",
        "/stopall — every bot OFF, never on; no position is closed; "
        "re-arm on the server"])


def could_not_answer(name):
    return eye.Reply(eye.MARK_WARN, PREFIX + "could not answer",
                     [f"The command failed ({name}); nothing was changed.",
                      "Send it again in a minute."])


def build_status(now=None):
    """Counts and names, never an amount: the platform's own words for
    what is on, how many bots and positions (how many live), the guards'
    line, and the critical problems the sentinel sees now."""
    from django.utils import timezone

    from bot_program.asset_engine.base import is_entry_working
    from bot_program.asset_models import AssetBotConfig, AssetBotTrade
    now = now or timezone.now()
    lines = [("Automation: paused — no bot trades and no safety check "
              "runs") if _paused() else "Automation: on"]
    # every enabled config, whatever its account's state: the fleet ticks
    # them all (asset_engine/runner), and /stopall stops them all
    bots = AssetBotConfig.objects.filter(enabled=True)
    lines.append(f"Bots running: {bots.count()} "
                 f"({bots.filter(mode='live').count()} live)")
    rows = list(AssetBotTrade.objects.filter(status__in=eye.OPEN_STATUSES))
    orders = [t for t in rows if not t.paper and is_entry_working(t)]
    held = [t for t in rows if t not in orders]
    lines.append(f"Open positions: {len(held)} "
                 f"({sum(1 for t in held if not t.paper)} live)")
    if orders:
        lines.append(f"Orders waiting at the broker: {len(orders)}")
    try:
        lines.append(morgul.status_line(now))
    except Exception as e:  # noqa: BLE001 (a status never raises)
        lines.append(f"Guards: unreadable ({type(e).__name__})")
    found = problems(now)
    if found:
        lines.append(eye.heading(f"Critical problems now: {len(found)}"))
        lines.extend(f"{eye.BULLET}{a.words}"
                     for a in found[:MAX_PROBLEMS_LISTED])
        if len(found) > MAX_PROBLEMS_LISTED:
            lines.append(f"+{len(found) - MAX_PROBLEMS_LISTED} more on "
                         f"/health/")
    else:
        lines.append("No critical problem now.")
    lines.append(f"Checked: {eye.when(now)}")
    return eye.Reply(eye.MARK_STATUS, STATUS_TITLE,
                     eye._cap(lines[:-1], eye.MAX_LINES - 1) + lines[-1:])


def stop_all(*, now=None, sent_at=None) -> list:
    """THE BRAKE from the alarm chat: telegram_eye.apply_brake, the Eye's
    own write, for every account with a bot running -- an inactive
    account's too, since the fleet ticks every enabled config whatever
    the account's state (asset_engine/runner) -- with withdraw=True as
    the Eye's /stopall passes it (the operator and his father share one
    account; nothing maps this chat to a user). Never the kill switch,
    never the master switch, never a close. One reply per account, named
    by number: a username is typed by a person and may read like code
    on the phone."""
    from django.contrib.auth import get_user_model
    from django.utils import timezone
    now = now or timezone.now()
    users = list(get_user_model().objects
                 .filter(asset_bot_configs__enabled=True)
                 .distinct().order_by("pk"))
    if not users:
        return [eye.Reply(eye.MARK_BRAKE, STOP_TITLE,
                          ["No bot was running: nothing was stopped.",
                           f"Checked: {eye.when(now)}"])]
    out = []
    for user in users:
        reply = eye.apply_brake(user, everything=True, now=now,
                                sent_at=sent_at, withdraw=True)
        lines = list(reply.lines)
        if len(users) > 1:
            keep = min(int(reply.meta.get("keep_tail") or 0), len(lines))
            head, tail = lines[:len(lines) - keep], lines[len(lines) - keep:]
            lines = ([eye.heading(f"Account #{user.pk}")]
                     + eye._cap(head, eye.MAX_LINES - 1 - keep) + tail)
        out.append(eye.Reply(eye.MARK_BRAKE, STOP_TITLE, lines,
                             meta=reply.meta))
    return out


def route(command, *, now=None, sent_at=None) -> list:
    if command == "status":
        return [build_status(now)]
    if command == "stopall":
        return stop_all(now=now, sent_at=sent_at)
    return [build_help()]


# ── one update ───────────────────────────────────────────────────────────

def _rate_ok(chat_id) -> bool:
    from django.core.cache import cache
    try:
        return bool(cache.add(RATE_KEY.format(chat=chat_id), 1,
                              timeout=eye.RATE_S))
    except Exception:  # noqa: BLE001 (a cache down never silences a reply)
        return True


def _me(token):
    """The bot's own username (getMe), cached a day; None when unknown."""
    from django.core.cache import cache
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()[:12]
    key = ME_KEY.format(digest=digest)
    try:
        known = cache.get(key)
    except Exception:  # noqa: BLE001
        known = None
    if known:
        return str(known)
    result, _why = _api(token, "getMe", {})
    name = str((result or {}).get("username") or "").strip()
    if not name:
        return None
    try:
        cache.set(key, name, ME_TTL_S)
    except Exception:  # noqa: BLE001
        pass
    return name


def _addressed_here(text, token) -> bool:
    """False for "/stopall@AnotherBot": with two bots in one group, a
    command named for the other is not this one's. getMe unanswered:
    True -- both commands are safe to act on."""
    raw = str(text or "").strip()
    first = raw.split(None, 1)[0] if raw.startswith("/") else ""
    if "@" not in first:
        return True
    me = _me(token)
    return me is None or first.split("@", 1)[1].lower() == me.lower()


def _migration(msg, chat_id, chat) -> bool:
    """The alarm group upgraded to a supergroup changes its id, and every
    alarm to the old one fails from then on: said at WARNING with the
    variable to change. True for either service message."""
    to_id = msg.get("migrate_to_chat_id")
    from_id = msg.get("migrate_from_chat_id")
    if not to_id and not from_id:
        return False
    old, new = (chat_id, str(to_id)) if to_id else (str(from_id), chat_id)
    if old == chat:
        logger.warning("[telegram alarm] the alarm group %s is now the "
                       "supergroup %s: set %s=%s in .env, then ./deploy/dc "
                       "up -d; until then no alarm reaches it", old, new,
                       CHAT_ENV, new)
    return True


def _answer(token, chat, replies) -> None:
    for reply in replies:
        _deliver(token, chat, reply)


def handle(update, *, token, chat, now=None, quiet=None) -> str:
    """One Telegram update. Returns a verdict word for the log and tests.
    The replies leave after the COMMIT: none announces a brake the
    database does not hold."""
    from django.db import transaction
    from django.utils import timezone
    now = now or timezone.now()
    msg = update.get("message") if isinstance(update, dict) else None
    if not isinstance(msg, dict):
        return "ignored"
    where = msg.get("chat") or {}
    chat_id = str(where.get("id", "")).strip()
    if _migration(msg, chat_id, chat):
        return "migrated"
    if chat_id != chat:
        if quiet is None or chat_id not in quiet:
            logger.info("[telegram alarm] ignored chat %s (%s)",
                        chat_id or "?", where.get("type") or "?")
            if quiet is not None:
                quiet.add(chat_id)
        return "unauthorised"
    sender = msg.get("from") or {}
    sender_chat = msg.get("sender_chat") or {}
    if (sender.get("is_bot")
            and str(sender_chat.get("id", "")).strip() != chat_id):
        return "ignored"
    text = msg.get("text") or ""
    command, _arg = parse(text)
    if command is None:
        return "chatter"
    if not _addressed_here(text, token):
        return "elsewhere"
    brake = command == "stopall"
    date = msg.get("date")
    sent = (datetime.fromtimestamp(date, dt_tz.utc)
            if isinstance(date, (int, float)) else None)
    age = (now - sent).total_seconds() if sent is not None else 0
    if not brake and age > eye.STALE_AFTER_S:
        logger.info("[telegram alarm] dropped a stale %s (%d s old)",
                    command, int(age))
        return "stale"
    if not brake and not _rate_ok(chat_id):
        logger.info("[telegram alarm] rate-limited %s", command)
        return "rate_limited"
    try:
        with transaction.atomic():
            replies = route(command, now=now, sent_at=sent)
    except Exception as e:  # noqa: BLE001 (say it, do not crash the batch)
        logger.warning("[telegram alarm] %s failed (%s)", command,
                       type(e).__name__, exc_info=True)
        replies = [could_not_answer(type(e).__name__)]
    if brake:
        logger.warning("[telegram alarm] BRAKE from the alarm chat (sender "
                       "%s): configs %s turned off", sender.get("id", "?"),
                       sorted(pk for r in replies
                              for pk in r.meta.get("stopped") or []))
    transaction.on_commit(partial(_answer, token, chat, replies),
                          robust=True)
    return f"answered:{command}"


# ── the poll ─────────────────────────────────────────────────────────────

def _failing(method, kind, why) -> None:
    from django.core.cache import cache
    try:
        cache.set(FAILING_KEY.format(method=method), why, eye.CURSOR_TTL_S)
    except Exception:  # noqa: BLE001
        pass
    _note(kind, why)


def _recovered(method) -> None:
    from django.core.cache import cache
    key = FAILING_KEY.format(method=method)
    try:
        was = cache.get(key)
        if was is None:
            return
        cache.delete(key)
    except Exception:  # noqa: BLE001
        return
    logger.info("[telegram alarm] %s answers again (last fault: %s)",
                method, was)


def _api(token, method, params):
    """(result, None) or (None, why), as telegram_eye._api, with this
    bot's own fault memory and log words: the two bots' refusals must not
    silence or clear each other. Never raises, never logs the URL."""
    url = eye.API_URL.format(token=token, method=method)
    try:
        r = requests.get(url, params=params, timeout=eye.HTTP_TIMEOUT_S)
    except Exception as e:  # noqa: BLE001
        why = f"{method} unreachable ({type(e).__name__})"
        _failing(method, f"{method}:unreachable", why)
        return None, why
    try:
        data = r.json()
    except Exception:  # noqa: BLE001
        data = {}
    if not isinstance(data, dict):
        data = {}
    if not getattr(r, "ok", False) or not data.get("ok"):
        status = getattr(r, "status_code", "?")
        said = _clean(data.get("description") or "", token)[:200]
        why = f"{method} refused ({status})" + (f": {said}" if said else "")
        _failing(method, f"{method}:{status}", why)
        return None, why
    _recovered(method)
    return data.get("result"), None


def _take_lock() -> bool:
    """The batch lock, taken WITHOUT waiting (pg_try_advisory_xact_lock,
    released by the commit), its own id; True on SQLite, which has none."""
    from django.db import connection
    if connection.vendor != "postgresql":
        return True
    with connection.cursor() as cur:
        cur.execute("SELECT pg_try_advisory_xact_lock(%s)", [BATCH_LOCK_ID])
        row = cur.fetchone()
    return bool(row and row[0])


def poll(*, now=None) -> dict:
    """Fetch, handle, commit, confirm: telegram_eye.poll's order, kept
    whole (213c716). The replies and the belt (the Eye's per-bot cursor,
    keyed on a hash of THIS token) wait for the commit, the confirm is
    issued after the atomic block, and a batch ends at the brake. A pass
    that read nothing is idle: the row keeps the sentinel's verdict."""
    from django.db import transaction
    token, chat, why = config()
    if why:
        _note("config", f"not polling: {why}")
        return {"status": "success", "skipped": why}
    with transaction.atomic():
        if not _take_lock():
            return {"status": "success",
                    "idle": "another alarm poll holds the batch"}
        seen = eye._last_handled(token)
        verdicts, quiet = [], set()
        fetched, last, offset = 0, None, None
        for _page in range(eye.MAX_PAGES):
            params = {"timeout": 0, "limit": eye.PAGE_SIZE,
                      "allowed_updates": eye.ALLOWED_UPDATES}
            if offset is not None:
                params["offset"] = offset
            updates, why = _api(token, "getUpdates", params)
            if updates is None:
                if last is None:
                    return {"status": "error", "error": why}
                break
            updates = updates if isinstance(updates, list) else []
            batch = sorted((u for u in updates if eye._update_id(u) >= 0),
                           key=eye._update_id)
            fetched += len(batch)
            braked = False
            for update in batch:
                uid = eye._update_id(update)
                if seen is not None and uid <= seen:
                    logger.warning("[telegram alarm] update %s was handled "
                                   "before; skipped", uid)
                    verdict = "seen"
                else:
                    try:
                        with transaction.atomic():
                            verdict = handle(update, token=token, chat=chat,
                                             now=now, quiet=quiet)
                    except Exception as e:  # noqa: BLE001
                        logger.warning("[telegram alarm] update %s failed "
                                       "(%s)", uid, type(e).__name__,
                                       exc_info=True)
                        verdict = "failed"
                verdicts.append(verdict)
                last = uid
                if verdict == BRAKE_VERDICT:
                    braked = True     # the brake commits now; the rest
                    break             # waits for the next poll
            if braked or last is None or len(updates) < eye.PAGE_SIZE:
                break
            offset = last + 1
        if last is None:
            return {"status": "success", "idle": "nothing to read"}
        transaction.on_commit(partial(eye._remember, token, last),
                              robust=True)
    # COMMITTED: the replies left, the belt holds `last`. Now Telegram may
    # forget the batch.
    confirmed, _why = _api(token, "getUpdates",
                           {"offset": last + 1, "timeout": 0, "limit": 1,
                            "allowed_updates": eye.ALLOWED_UPDATES})
    return {"status": "success", "updates": fetched,
            "answered": sum(1 for v in verdicts if v.startswith("answered")),
            "confirmed": confirmed is not None}


def seen_chats() -> list:
    """(chat id, type, title) of every chat in the updates Telegram holds
    for this bot, for `manage.py alarm --chats`: getUpdates WITHOUT an
    offset, so nothing is confirmed and nothing is forgotten."""
    token = os.getenv(TOKEN_ENV, "").strip()
    if not token:
        return []
    updates, _why = _api(token, "getUpdates",
                         {"timeout": 0, "limit": eye.PAGE_SIZE,
                          "allowed_updates": eye.ALLOWED_UPDATES})
    out = {}
    for update in updates if isinstance(updates, list) else []:
        where = ((update.get("message") or {}).get("chat") or {}
                 if isinstance(update, dict) else {})
        if where.get("id") is not None:
            out[str(where["id"])] = (str(where["id"]),
                                     str(where.get("type") or "?"),
                                     str(where.get("title") or ""))
    return list(out.values())


# ── what the platform shows ──────────────────────────────────────────────

def health_row(make) -> dict:
    """The /health/ row, through the page's own _check (`make`)."""
    label = "Alarm bot"
    if not enabled():
        # Not a fault: nothing set up yet (configured=False: NOT SET UP).
        return make("alarm", label, "ok",
                    "off — no critical problem reaches the alarm chat",
                    "manage.py component on telegram_alarm",
                    configured=False)
    _token, _chat, why = config()
    if why:
        return make("alarm", label, "fail", f"refused: {why}",
                    f"set {TOKEN_ENV} and {CHAT_ENV} in .env, then "
                    f"./deploy/dc up -d; manage.py alarm --test")
    return make("alarm", label, "ok",
                "configured — delivery unverified; critical problems only",
                "manage.py alarm --test proves the delivery")
