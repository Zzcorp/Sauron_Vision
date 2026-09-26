"""The Telegram eye: Sauron answers its group (2026-09-26).

The operator's ask, 2026-09-26: "Sauron peut-il faire un état des lieux
sur Telegram? Répondre quand demandé entre guillemets." The alerts
already reach the group "Sauron Vision" (the telegram_chat_id on the
staff user's UserNotificationPrefs). From 2026-09-28 the operator's
father runs Sauron for three weeks from his phone; this module is what
he can ask it.

Every reply is in ENGLISH and in one house style: the operator's rule of
2026-09-26, "messages en anglais toujours, et un style irréprochable".
French command aliases are accepted because the father may type them;
the answer is English all the same.

    /status  /etat  "état des lieux"   the status report (no LLM)
    /positions                          the open book
    /why SYMBOL  /pourquoi SYMBOL       the last recorded skip, per bot
    /help  /aide                        the commands
    /q QUESTION  /ask  "a quoted line"  the research agent, in English
    /stop ID  /stopall                  THE BRAKE: bots OFF, never ON

WHAT IT REFUSES
  * Any chat but the configured one. A message counts only when its chat
    id is the telegram_chat_id of exactly ONE active staff user whose
    TraderProfile.notify_channel is telegram. Everything else is dropped
    in silence and logged at INFO by chat id and type, never by text. A
    chat two such users claim is refused (a WARNING naming them, one
    reply an hour): acting for the wrong account stops the wrong bots.
  * Any write to trading state but `enabled = False` on that user's own
    configs (a question writes its ResearchMessage rows). No bot
    on, no order, no exit, no level, no Demo untick, no class tick, no
    risk change, no PIN; tests/test_telegram_eye.py greps this file.
  * A command older than STALE_AFTER_S, so a backlog after an outage does
    not replay itself. The brake is the exception: a stop applied late is
    still safe, a stop ignored is not; its reply then says when it was
    sent.
  * More than one reply per RATE_S per chat (the brake again excepted).

HOW IT READS: getUpdates with no stored cursor. Fetch (timeout 0, only
"message" updates, up to MAX_PAGES pages), handle, then confirm with
getUpdates(offset = last update handled + 1), below which Telegram
forgets. One poll at a time: a Postgres advisory lock taken without
waiting, so a second worker skips at once. Not the component row:
guarded_task's mark_run writes that row after every run and would wait
behind a poll holding it. SQLite, the suite's database, has no such lock.

WHAT WAITS FOR THE COMMIT: every reply, and the cache belt (the last
update id handled, two days, per bot), which stops a confirm lost on the
wire from answering twice. A batch ENDS at a brake; what follows waits
for the next poll. So a brake commits within one confirm call, and no
reply can announce a brake the database does not hold. Each update runs
in its own savepoint: one that fails rolls back alone, with its reply.

GROUP PRIVACY: with privacy ON (the default for a bot in a group) the
bot receives /commands and replies to its own messages, not plain text.
/q always works, and so does a quoted question sent as a reply to one of
Sauron's messages; a bare quoted line needs privacy turned off at
@BotFather, then the bot removed and re-added to the group.

Doors: bot_program.tasks.poll_telegram_eye (every 15 s, fast queue,
gated by the telegram_eye component, OFF on arrival) and
bot_program.tasks.answer_telegram_question (the ai queue: one LLM turn
takes tens of seconds and must not sit in front of the quote poller).
alerts/channels/telegram_alert.py holds an older reader with no sender
check; this module supersedes it, and it must never be scheduled.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import unicodedata
from datetime import datetime, timedelta
from datetime import timezone as dt_tz
from decimal import Decimal, InvalidOperation
from functools import partial
from html import escape

import requests

logger = logging.getLogger(__name__)

COMPONENT_KEY = "telegram_eye"
API_URL = "https://api.telegram.org/bot{token}/{method}"
HTTP_TIMEOUT_S = 10
#: A command older than this is dropped unanswered (the brake excepted).
STALE_AFTER_S = 600
#: One reply per chat per this many seconds (the brake excepted).
RATE_S = 3
#: The house cap on one message; past it, "+N more on the platform".
MAX_LINES = 25
MAX_POSITIONS_IN_REPORT = 10
MAX_POSITIONS_LISTED = 20
MAX_BOTS_LISTED = 8
MAX_WHY_BOTS = 4
#: The research answer as sent: trimmed, then "… (continued on the platform)".
ANSWER_MAX_CHARS = 3500
CONTINUED = "… (continued on the platform)"
#: Questions per chat per UTC day, counted from ResearchMessage rows.
QUESTIONS_PER_DAY = 30
QUESTION_MAX_CHARS = 1000
#: getUpdates pages per poll, and their size. The bot can be added to
#: any group and written to by anyone: a flood from other chats is
#: drained, not left queued in front of a stop.
PAGE_SIZE = 100
MAX_PAGES = 5
#: Only messages: edits, channel posts, joins and reactions are no command.
ALLOWED_UPDATES = json.dumps(["message"])
#: Telegram refuses a longer message once escaped (a 400: the message lost).
TELEGRAM_MAX_CHARS = 4096
#: The cache belt: the last update id handled, per bot (a hash of the
#: token, never the token). Telegram keeps an unconfirmed update 24 h and
#: numbers updates in sequence unless a week passes without one, so two
#: days never outlives the sequence.
CURSOR_KEY = "telegram_eye:last_update_id"
CURSOR_TTL_S = 2 * 86400
RATE_KEY = "telegram_eye:rate:{chat}"
#: A repeated fault (a 409, a revoked token, a chat claimed twice) is
#: logged at WARNING once, then at most once per NOTE_EVERY_S.
NOTE_KEY = "telegram_eye:note:{kind}"
NOTE_EVERY_S = 3600
FAILING_KEY = "telegram_eye:failing:{method}"
#: The batch lock's key (pg_try_advisory_xact_lock); nothing else in this
#: repository takes an advisory lock.
BATCH_LOCK_ID = 20260927
#: A batch ends at these: the brake commits before anything else runs.
BRAKE_VERDICTS = ("answered:stop", "answered:stopall")
OPEN_STATUSES = ("OPEN", "CLOSE_PENDING")

DASH = "—"
BULLET = "  • "

MARK_STATUS = "\U0001F4CB"
MARK_POSITIONS = "\U0001F4D2"
MARK_WHY = "\U0001F50E"
MARK_HELP = "ℹ️"
MARK_BRAKE = "\U0001F6D1"
MARK_THINKING = "⏳"
MARK_ANSWER = "\U0001F4AC"
MARK_WARN = "⚠️"

PRIVACY_LINE = ("/q <question> always works; for bare quotes, turn the "
                "bot's Group Privacy off at @BotFather (Bot Settings → "
                "Group Privacy → Turn off), then remove and re-add the bot "
                "to the group.")

#: The brake's own words, every time it answers.
BRAKE_WORDS = ("No position was closed.",
               "Stops stay at the broker.",
               "To re-arm: the server, never Telegram.")

#: Appended to a question before it reaches the research agent, whose
#: system prompt asks for Markdown: the group reads plain English.
ASK_SUFFIX = ("\n\n(Asked on Telegram. Answer in English, in plain text "
              "without Markdown, in under 200 words.)")

_COMMANDS = {
    "status": "status", "etat": "status",
    "positions": "positions",
    "why": "why", "pourquoi": "why",
    "help": "help", "aide": "help", "start": "help",
    "stop": "stop", "stopall": "stopall",
    "ask": "ask", "q": "ask",
}
_STATUS_PHRASES = {"status", "etat des lieux"}
_OPEN_QUOTES = "\"“«„"
_CLOSE_QUOTES = "\"”»“"

CLASS_WORDS = {"stock": "Stocks", "etf": "ETFs", "index": "Indices",
               "forex": "Forex", "commodity": "Commodities",
               "crypto": "Crypto", "options": "Options", "cfd": "CFDs"}
PROOF_WORDS = dict(CLASS_WORDS, short="Short selling")
SIDE_WORDS = {"BUY": "long", "SELL": "short"}

#: Every skip code bot_program/asset_engine/skips.py can record, in the
#: words the group reads (tests pin that none is missing).
SKIP_WORDS = {
    "no_instrument": "the symbol is not in the instrument list",
    "no_signals": "no fresh signal to vote on",
    "stale_signals": "the signals were too old",
    "hold": "the signals voted to hold",
    "cooldown": "this symbol traded too recently",
    "already_open": "a position is already open",
    "gate_blocked": "the risk gate declined",
    "stage_blocked": "the rule is not promoted far enough to trade",
    "paper_fallback": "a live bot had no working broker",
    "no_price": "no usable price",
    "cost_filter": "the planned move could not cover the costs",
    "sized_to_zero": "the risk budget buys less than one unit",
    "shadow": "shadow mode: computed, not sent",
    "order_rejected": "the broker refused the order",
    "error": "an error on the entry path",
    "brain_paused": "the brain advised a pause",
    "order_in_doubt": "the order did not come back; check the broker",
    "order_error": "the order failed before it was confirmed",
    "venue_min_size": "below the broker's minimum trade size",
    "desk_displaced": "the capital desk chose other entries",
    "leverage_refused": "a levered order was refused before it left",
    "eligibility_refused": "eToro's eligibility rules refused the entry",
}


# ── the house style ──────────────────────────────────────────────────────

class Reply:
    """One message: a mark, a title, then fact lines (or a prose body)."""

    __slots__ = ("mark", "title", "lines", "body", "meta")

    def __init__(self, mark, title, lines=(), body="", meta=None):
        self.mark = mark
        self.title = title
        self.lines = list(lines)
        self.body = body
        self.meta = dict(meta or {})

    def text(self) -> str:
        """The HTML Telegram receives (notifications._telegram_text)."""
        from bot_program.notifications import _telegram_text
        return _telegram_text(self.title, self.body,
                              lines=self.lines or None, mark=self.mark)


def heading(text: str):
    """A bold section header inside a message."""
    from bot_program.notifications import TelegramHeading
    return TelegramHeading(text)


def _dec(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return d if d.is_finite() else None


def money(value, currency: str = "") -> str:
    """332,443.09 USD: separators, two decimals, the code after. An
    unmeasured amount reads as an em dash, never 0."""
    d = _dec(value)
    if d is None:
        return DASH
    text = f"{d.quantize(Decimal('0.01')):,.2f}"
    if text == "-0.00":
        text = "0.00"
    code = (currency or "").strip().upper()
    return f"{text} {code}" if code else text


def quantity(value) -> str:
    """0.04, 1, 10,000: no trailing zeros."""
    d = _dec(value)
    if d is None:
        return DASH
    return f"{d.normalize():,f}"


def price(value) -> str:
    """336.10, 1.08345, 60,123.50: at least two decimals, at most eight."""
    d = _dec(value)
    if d is None:
        return DASH
    d = d.normalize()
    exp = d.as_tuple().exponent
    places = max(2, min(8, -exp if exp < 0 else 0))
    return f"{d.quantize(Decimal(1).scaleb(-places)):,.{places}f}"


def percent(value) -> str:
    """7.0%: one decimal, no space (the English norm)."""
    d = _dec(value)
    return DASH if d is None else f"{float(d):.1f}%"


def ago(moment, now=None) -> str:
    """12 min ago, 3 h ago, 2 d ago; an em dash when never."""
    if moment is None:
        return DASH
    from django.utils import timezone
    now = now or timezone.now()
    seconds = (now - moment).total_seconds()
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{int(seconds // 60)} min ago"
    if seconds < 48 * 3600:
        return f"{int(seconds // 3600)} h ago"
    return f"{int(seconds // 86400)} d ago"


def when(moment) -> str:
    """2026-09-27 14:05 UTC."""
    if moment is None:
        return DASH
    return moment.astimezone(dt_tz.utc).strftime("%Y-%m-%d %H:%M UTC")


def _parse_iso(text):
    try:
        moment = datetime.fromisoformat(str(text))
    except (TypeError, ValueError):
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=dt_tz.utc)


def _sentence(text: str) -> str:
    return text[:1].upper() + text[1:] if text else text


def _plural(n: int, word: str) -> str:
    return f"{n:,} {word}" + ("" if n == 1 else "s")


def _cap(lines, limit: int = MAX_LINES) -> list:
    """At most `limit` lines; the rest counted, never silently dropped."""
    lines = [ln for ln in lines if str(ln or "").strip()]
    if len(lines) <= limit:
        return lines
    keep = lines[:limit - 1]
    return keep + [f"+{len(lines) - len(keep)} more on the platform"]


_MORE_RE = re.compile(r"\+([\d,]+) more")


def fit(reply, limit: int = TELEGRAM_MAX_CHARS):
    """The reply as Telegram accepts it: at most `limit` characters once
    escaped (one quote character is six). Facts are dropped from the end
    of the body and counted; the reply's protected tail, meta
    "keep_tail" (the brake's own words), stays whole."""
    if len(reply.text()) <= limit:
        return reply
    lines = [ln for ln in reply.lines if str(ln or "").strip()]
    keep = min(int(reply.meta.get("keep_tail") or 0), len(lines))
    head, tail = lines[:len(lines) - keep], lines[len(lines) - keep:]
    dropped = 0
    while head:
        match = _MORE_RE.match(str(head.pop()))
        dropped += int(match.group(1).replace(",", "")) if match else 1
        out = Reply(reply.mark, reply.title,
                    head + [f"+{dropped:,} more on the platform"] + tail,
                    reply.body, reply.meta)
        if len(out.text()) <= limit:
            return out
    more = [f"+{dropped:,} more on the platform"] if dropped else []
    return Reply(reply.mark, reply.title,
                 more + [type(ln)(str(ln)[:120]) for ln in tail],
                 trim_answer(reply.body, limit // 2) if reply.body else "",
                 reply.meta)


def config_label(cfg) -> str:
    """The config as the operator named it, with its number."""
    from bot_program.manual_trade import MANUAL_CONFIG_NAME
    name = (cfg.name or "").strip() or "Unnamed bot"
    if name == MANUAL_CONFIG_NAME:
        name = ("Hand-taken trades ("
                f"{CLASS_WORDS.get(cfg.asset_class, cfg.asset_class)})")
    return f"{name} #{cfg.pk}"


def skip_words(code: str) -> str:
    code = str(code or "")
    return _sentence(SKIP_WORDS.get(code) or code.replace("_", " ")
                     or "no reason recorded")


_URL_RE = re.compile(r"https?://\S+")
_REPR_RE = re.compile(r"Decimal\(\s*['\"]?([^'\")]*)['\"]?\s*\)")
#: PaperTrader, leverageValues, maxStopLossPercentage; not eToro (one
#: lower-case letter first), not IBKR.
_CAMEL_RE = re.compile(r"\b(?:[A-Z][a-z]+|[a-z]{2,})(?:[A-Z][a-z]+)+\b")


def plain_detail(text, limit: int = 200) -> str:
    """An engine's skip detail in the group's words. It is free text
    written for the log ("brain pause_recommended for momentum_breakout",
    "fell back to PaperTrader", an exception's own words), so: secrets
    scrubbed, links dropped, reprs unwrapped, identifiers split into
    words, at most `limit` characters."""
    from core.secret_scrub import scrub
    s = scrub(str(text or ""))
    s = _URL_RE.sub("(a link)", s)
    s = _REPR_RE.sub(r"\1", s)
    s = re.sub(r"\bNone\b", DASH, s)
    s = s.replace("_", " ")
    s = _CAMEL_RE.sub(lambda m: re.sub(r"(?<=[a-z])(?=[A-Z])", " ",
                                       m.group(0)).lower(), s)
    s = " ".join(s.split())
    return s if len(s) <= limit else s[:limit - 1].rstrip() + "…"


def position_line(trade, *, now=None, detailed: bool = False,
                  bullet: bool = True) -> str:
    """AAPL long 0.04 @ 336.10 · stop 326.02 · paper."""
    side = SIDE_WORDS.get(trade.side, str(trade.side or "").lower())
    parts = [f"{trade.symbol} {side} {quantity(trade.qty)} @ "
             f"{price(trade.entry_price)}",
             f"stop {price(trade.stop_loss)}"]
    if detailed:
        parts.append(f"target {price(trade.take_profit)}")
    parts.append("paper" if trade.paper else "live")
    if trade.status == "CLOSE_PENDING":
        parts.append("closing")
    if detailed:
        parts.append(f"opened {ago(trade.opened_at, now)}")
    return (BULLET if bullet else "") + " · ".join(parts)


# ── who may speak ────────────────────────────────────────────────────────

def _once(kind: str) -> bool:
    """True the first time `kind` comes up in NOTE_EVERY_S (cache.add);
    True as well when the cache is down: better twice than never."""
    from django.core.cache import cache
    try:
        return bool(cache.add(NOTE_KEY.format(kind=kind), 1, NOTE_EVERY_S))
    except Exception:  # noqa: BLE001
        return True


def _note(kind: str, text: str) -> None:
    """A repeated fault at WARNING once an hour, at DEBUG in between: a
    409 every 15 s would otherwise write 5,760 lines a day."""
    if _once(kind):
        logger.warning("[telegram eye] %s", text)
    else:
        logger.debug("[telegram eye] %s", text)


def _chat_map() -> tuple:
    """({chat id: user}, {chat id: [users]}): the chats this module
    answers, from the telegram_chat_id of every active staff user whose
    notify_channel is telegram, and the chats it refuses because several
    such users claim them (it cannot tell whose bots a /stopall means)."""
    from alerts.models import UserNotificationPrefs
    from bot_program.notifications import _user_channel
    owners = {}
    rows = (UserNotificationPrefs.objects.exclude(telegram_chat_id="")
            .select_related("user").order_by("user_id"))
    for prefs in rows:
        user = prefs.user
        if not (user.is_staff and user.is_active):
            continue
        if _user_channel(user) != "telegram":
            continue
        chat = str(prefs.telegram_chat_id or "").strip()
        if chat:
            owners.setdefault(chat, []).append(user)
    chats = {c: us[0] for c, us in owners.items() if len(us) == 1}
    ambiguous = {c: us for c, us in owners.items() if len(us) > 1}
    for chat, users in ambiguous.items():
        _note(f"ambiguous:{chat}",
              f"chat {chat} is configured for several accounts "
              f"({', '.join(u.username for u in users)}): nothing there is "
              f"answered until one account keeps it")
    return chats, ambiguous


def authorised_chats() -> dict:
    """{chat id: user}: the only chats this module answers."""
    return _chat_map()[0]


def _still_authorised(user) -> bool:
    try:
        chat = str(user.notification_prefs.telegram_chat_id or "").strip()
    except Exception:  # noqa: BLE001 (no prefs row: not a chat)
        return False
    found = authorised_chats().get(chat)
    return found is not None and found.pk == user.pk


def _send(user, reply) -> bool:
    """To the user's configured chat, through the platform sender, cut
    to what Telegram accepts (fit)."""
    from bot_program import notifications as N
    reply = fit(reply)
    return N._send_telegram(user, reply.title, reply.body,
                            lines=reply.lines or None, mark=reply.mark)


# ── what was said ────────────────────────────────────────────────────────

def _fold(text: str) -> str:
    """Lower case, accents dropped, spaces collapsed: /État is /etat."""
    text = unicodedata.normalize("NFKD", str(text or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(text.lower().split())


def _unquote(text: str):
    """The inside of "...", « ... » or “...”, else None."""
    if (len(text) > 2 and text[0] in _OPEN_QUOTES
            and text[-1] in _CLOSE_QUOTES):
        return text[1:-1].strip()
    return None


def parse(text: str) -> tuple:
    """(command, argument), or (None, "") for anything not addressed to
    Sauron: ordinary chatter is never answered."""
    raw = str(text or "").strip()
    if not raw:
        return None, ""
    if raw.startswith("/"):
        parts = raw.split(None, 1)
        word = _fold(parts[0][1:].split("@", 1)[0])
        command = _COMMANDS.get(word)
        if command is None:
            return None, ""
        return command, (parts[1].strip() if len(parts) > 1 else "")
    inner = _unquote(raw)
    phrase = _fold(inner if inner is not None else raw).strip(" .!?")
    if phrase in _STATUS_PHRASES:
        return "status", ""
    if inner:
        return "ask", inner
    return None, ""


# ── the answers ──────────────────────────────────────────────────────────

def read_live_account(api_key: str, user_key: str) -> dict:
    """READ-ONLY: the LIVE world's equity and open-position count, two GETs
    through EtoroTrader. Raises what the client raises."""
    from bot_program.engine.etoro_client import EtoroTrader
    client = EtoroTrader(api_key, user_key, env="live", timeout=5.0)
    return {"equity": client.net_liquidation(),
            "positions": len(client.get_positions())}


def _live_lines(acct) -> list:
    try:
        api_key, user_key = acct.get_credentials()
        if not api_key:
            return ["Live account: no keys stored"]
        reading = read_live_account(api_key, user_key)
    except Exception as e:  # noqa: BLE001 (a status report never raises)
        return [f"Live account: unreadable ({type(e).__name__})"]
    value, code = reading.get("equity") or (None, "")
    count = reading.get("positions")
    return [heading("Live account · read now"),
            f"Equity: {money(value, code)}",
            f"Open positions: {DASH if count is None else count}"]


def _etoro_lines(user, now) -> list:
    from bot_program.models import EtoroAccount
    acct = EtoroAccount.objects.filter(user=user).first()
    out = [heading("eToro")]
    if acct is None:
        out.append("Connection: not set up")
        return out
    world = "Demo" if acct.demo else "Live"
    classes = [word for flag, word in (
        (acct.is_primary_for_stocks, "Stocks"),
        (acct.is_primary_for_forex, "Forex"),
        (acct.is_primary_for_commodity, "Commodities"),
        (acct.is_primary_for_crypto, "Crypto")) if flag]
    out.append(f"World: {world}")
    out.append("Classes routed here: "
               + (", ".join(classes) if classes else "none ticked"))
    synced = acct.last_equity_at or acct.last_sync
    out.append(heading(f"{world} account · "
                       + (f"synced {ago(synced, now)}" if synced
                          else "never synced")))
    code = acct.last_equity_currency
    out.append(f"Equity: {money(acct.last_equity, code)}")
    out.append(f"Available cash: {money(acct.last_available_cash, code)}")
    out.append(f"Used margin: {money(acct.last_used_margin, code)}")
    out.extend(_live_lines(acct))
    return out


def _bot_lines(user) -> list:
    from bot_program.asset_models import AssetBotConfig
    rows = list(AssetBotConfig.objects.filter(user=user, enabled=True)
                .order_by("pk"))
    out = [heading(f"Bots running ({len(rows)})")]
    if not rows:
        out.append("No bot is running")
    for cfg in rows[:MAX_BOTS_LISTED]:
        out.append(f"{BULLET}{config_label(cfg)} — {cfg.mode}")
    if len(rows) > MAX_BOTS_LISTED:
        out.append(f"+{len(rows) - MAX_BOTS_LISTED} more on the platform")
    return out


def _health_lines(now) -> list:
    try:
        from core.component_digest import collect_faults
        faults = collect_faults(now)
    except Exception as e:  # noqa: BLE001
        return [f"Platform health: unreadable ({type(e).__name__})"]
    groups = (("Failing", faults.get("errors") or []),
              ("Ran but did nothing", faults.get("warnings") or []),
              ("Stopped", faults.get("silent") or []),
              ("Feeds not delivering", faults.get("feeds") or []))
    total = sum(len(items) for _, items in groups)
    if not total:
        checked = int(faults.get("checked") or 0)
        return [f"Platform health: all clear "
                f"({_plural(checked, 'component')} checked)"]
    out = [heading(f"Platform health: {_plural(total, 'issue')}")]
    for label, items in groups:
        if not items:
            continue
        names = ", ".join(str(it.get("name")
                              or str(it.get("key") or DASH).replace("_", " "))
                          for it in items[:3])
        more = f", +{len(items) - 3} more" if len(items) > 3 else ""
        out.append(f"{label}: {len(items)} ({names}{more})")
    return out


def _proof_words() -> str:
    from bot_program.asset_engine import base
    tokens = sorted(getattr(base, "ETORO_PROVEN", ()) or ())
    words = [PROOF_WORDS.get(t, _sentence(str(t).replace("_", " ")))
             for t in tokens]
    return ", ".join(words) if words else "none yet"


def _open_trades(user):
    from bot_program.asset_models import AssetBotTrade
    return (AssetBotTrade.objects
            .filter(config__user=user, status__in=OPEN_STATUSES)
            .order_by("opened_at", "pk"))


def build_status(user, *, now=None) -> Reply:
    """THE STATUS REPORT: deterministic, read-only, no LLM. Positions come
    last so the line cap trims them first."""
    from django.utils import timezone
    from core.build_stamp import build_age_hours, git_sha
    now = now or timezone.now()
    sha, age = git_sha(), build_age_hours()
    version = sha or DASH
    if sha and age is not None:
        version += f" (built {ago(now - timedelta(hours=age), now)})"
    lines = [f"Version: {version}"]
    lines.extend(_etoro_lines(user, now))
    lines.extend(_bot_lines(user))
    lines.extend(_health_lines(now))
    lines.append(f"Demo proofs pinned: {_proof_words()}")
    trades = list(_open_trades(user))
    lines.append(heading(f"Open on the platform ({len(trades)})"))
    if not trades:
        lines.append("No open position")
    # As many as the line cap leaves room for (ten at most), and the rest
    # counted with the command that lists them all.
    room = max(1, MAX_LINES - len(lines))
    fits = len(trades) <= min(room, MAX_POSITIONS_IN_REPORT)
    shown = trades[:min(MAX_POSITIONS_IN_REPORT, room if fits else room - 1)]
    lines.extend(position_line(trade, now=now) for trade in shown)
    if len(trades) > len(shown):
        lines.append(f"+{len(trades) - len(shown)} more: send /positions")
    return Reply(MARK_STATUS, "Sauron — status report", _cap(lines))


def build_positions(user, *, now=None) -> Reply:
    """The open book: every platform position, then what eToro held at
    the last sync."""
    from django.utils import timezone
    from bot_program.models import EtoroAccount
    now = now or timezone.now()
    trades = list(_open_trades(user))
    live = sum(1 for t in trades if not t.paper)
    head = f"Open on the platform: {len(trades)}"
    if trades:
        head += f" ({live} live · {len(trades) - live} paper)"
    lines = [head]
    for trade in trades[:MAX_POSITIONS_LISTED]:
        lines.append(position_line(trade, now=now, detailed=True))
    if len(trades) > MAX_POSITIONS_LISTED:
        lines.append(f"+{len(trades) - MAX_POSITIONS_LISTED} more on the "
                     f"platform")
    acct = EtoroAccount.objects.filter(user=user).first()
    if acct is not None:
        world = "demo" if acct.demo else "live"
        held = acct.broker_positions
        if acct.broker_positions_at is None or not isinstance(held, list):
            lines.append(f"Held at eToro ({world}): {DASH}")
        else:
            lines.append(f"Held at eToro ({world}, synced "
                         f"{ago(acct.broker_positions_at, now)}): "
                         f"{len(held)}")
    return Reply(MARK_POSITIONS, "Sauron — open positions", _cap(lines))


def _overall_line(cfg) -> str:
    from bot_program.asset_engine import skips
    counts = skips.summary(cfg)
    total = sum(int(n) for n in counts.values())
    if not total:
        return "Bot overall: no scan completed yet"
    top, n = next(iter(counts.items()))
    return (f"Bot overall: {skip_words(top).lower()} in "
            f"{percent(100.0 * int(n) / total)} of {_plural(total, 'skip')}")


def build_why(user, symbol: str, *, now=None) -> Reply:
    """Why no trade on SYMBOL: per bot of this user that watches it or
    recorded a skip on it, the last reason, its age and detail, and the
    bot's most frequent reason."""
    from django.utils import timezone
    from bot_program.asset_engine import skips
    from bot_program.asset_models import AssetBotConfig
    now = now or timezone.now()
    words = str(symbol or "").split()
    sym = words[0].upper() if words else ""
    if not sym:
        return Reply(MARK_WHY, "Sauron — why no trade",
                     ["Give a symbol, for example: /why AAPL"])
    rows = []
    for cfg in AssetBotConfig.objects.filter(user=user).order_by("pk"):
        last = None
        for key, entry in skips.last_by_symbol(cfg).items():
            if str(key).upper() == sym and isinstance(entry, dict):
                last = entry
        watched = sym in {str(s).upper() for s in (cfg.symbols or [])}
        if last is not None or watched:
            rows.append((cfg, last))
    lines = []
    for trade in _open_trades(user).filter(symbol__iexact=sym)[:3]:
        lines.append("Open now: "
                     + position_line(trade, now=now, bullet=False))
    if not rows:
        lines.append(f"No bot watches {sym}.")
        lines.append("Symbols are set per bot on the platform.")
    for cfg, last in rows[:MAX_WHY_BOTS]:
        state = "running" if cfg.enabled else "stopped"
        lines.append(heading(f"{config_label(cfg)} — {state} · {cfg.mode}"))
        if last is None:
            lines.append("Last reason: none recorded yet")
        else:
            lines.append(f"Last reason: {skip_words(last.get('code'))}")
            lines.append(f"When: {ago(_parse_iso(last.get('at')), now)}")
            detail = plain_detail(last.get("detail"))
            if detail:
                lines.append(f"Detail: {detail}")
        lines.append(_overall_line(cfg))
    if len(rows) > MAX_WHY_BOTS:
        lines.append(f"+{len(rows) - MAX_WHY_BOTS} more bots on the "
                     f"platform")
    return Reply(MARK_WHY, f"Sauron — why no trade on {sym}", _cap(lines))


def build_help() -> Reply:
    lines = [
        heading("Commands"),
        f"{BULLET}/status — the status report (also /etat)",
        f"{BULLET}/positions — the open positions",
        f"{BULLET}/why SYMBOL — why a symbol did not trade (also /pourquoi)",
        f"{BULLET}/q QUESTION — ask Sauron (also /ask, or the question in "
        f"quotes)",
        f"{BULLET}/stop ID — stop one bot (numbers are in /status)",
        f"{BULLET}/stopall — stop every running bot",
        f"{BULLET}/help — this list (also /aide)",
        heading("Good to know"),
        "Replies are always in English.",
        "The brake never closes a position; stops stay at the broker.",
        "A stopped bot is re-armed on the server, never here.",
        "A quoted question sent as a reply to a Sauron message works too.",
        PRIVACY_LINE,
    ]
    return Reply(MARK_HELP, "Sauron — commands", lines)


def which_bot() -> Reply:
    """/stop without a clean number: nothing is guessed from free text."""
    return Reply(MARK_BRAKE, "Sauron — which bot?",
                 ["Give the bot number, for example: /stop 4",
                  "Numbers only: /stop 4 7 stops two bots.",
                  "The numbers are in /status, under Bots running.",
                  "/stopall stops every running bot."])


def ambiguous_reply() -> Reply:
    return Reply(MARK_WARN, "Sauron — this chat is not answered",
                 ["This chat is configured for several accounts.",
                  "Fix it on the server; until then, nothing here is "
                  "answered or stopped."])


def apply_brake(user, ids=(), *, everything: bool = False,
                now=None, sent_at=None) -> Reply:
    """THE BRAKE, the one write in this module: `enabled = False` on this
    user's own configs, the same write as `manage.py bot off ID`. Nothing
    is closed, cancelled or moved, and nothing reaches the broker.

    `sent_at`, the message's own time: a brake older than STALE_AFTER_S
    says when it was sent, and is applied all the same. Comparing it with
    the config's updated_at cannot tell a re-arm on the server from the
    engine's own writes: asset_engine/safety._save_extras stamps
    updated_at on every skip it records, so that test would refuse fresh
    stops."""
    from django.utils import timezone
    from bot_program.asset_models import AssetBotConfig, AssetBotTrade
    now = now or timezone.now()
    stopped, already, unknown = [], [], []
    if everything:
        targets = list(AssetBotConfig.objects
                       .filter(user=user, enabled=True).order_by("pk"))
    else:
        targets = []
        for pk in dict.fromkeys(ids):
            cfg = AssetBotConfig.objects.filter(pk=pk, user=user).first()
            if cfg is None:
                unknown.append(pk)
            elif not cfg.enabled:
                already.append(cfg)
            else:
                targets.append(cfg)
    for cfg in targets:
        cfg.enabled = False
        cfg.save(update_fields=["enabled", "updated_at"])
        stopped.append(cfg)
    head = []
    if stopped:
        head.append(heading(f"Stopped ({len(stopped)})"))
        head.extend(f"{BULLET}{config_label(c)} — {c.mode}"
                    for c in stopped)
    if already:
        head.append(heading("Already stopped"))
        head.extend(f"{BULLET}{config_label(c)}" for c in already)
    for pk in unknown:
        head.append(f"No bot #{pk} on this account.")
    if everything and not stopped:
        head.append("No bot was running.")
    trades = (list(AssetBotTrade.objects.filter(
        config__in=stopped, status__in=OPEN_STATUSES)) if stopped else [])
    # THE TAIL: the brake's own words, never cut by the line cap or by
    # fit() however long the list above.
    tail = []
    if trades:
        live = sum(1 for t in trades if not t.paper)
        tail.append(f"Positions left open: {len(trades)} "
                    f"({live} live · {len(trades) - live} paper)")
    tail.extend(BRAKE_WORDS)
    # "protected" is the engine's own fact that a stop RESTS at the venue
    # (asset_engine/base.py; broker_vision reads it too). A live row
    # without it was guarded by the bot, and the bot is now stopped.
    bare = sum(1 for t in trades
               if not t.paper and not (t.metadata or {}).get("protected"))
    if bare:
        tail.append(f"Live without a stop at the broker: {bare}")
        tail.append("The bot managed those stops; while it is stopped, "
                    "nothing protects them.")
    if any(t.paper for t in trades):
        tail.append("Paper stops are simulated by the bot and pause "
                    "while it is stopped.")
    if (sent_at is not None
            and (now - sent_at).total_seconds() > STALE_AFTER_S):
        tail.append(f"Sent: {when(sent_at)} ({ago(sent_at, now)})")
    tail.append(f"Applied: {when(now)}")
    title = ("Sauron — brake applied" if stopped
             else "Sauron — nothing to stop")
    return Reply(MARK_BRAKE, title, _cap(head, MAX_LINES - len(tail)) + tail,
                 meta={"stopped": [c.pk for c in stopped],
                       "keep_tail": len(tail)})


def could_not_answer(why: str) -> Reply:
    return Reply(MARK_WARN, "Sauron — no answer",
                 [f"Sauron could not answer ({why})."])


# ── the quoted question ──────────────────────────────────────────────────

def _conversation_title(chat_id) -> str:
    return f"Telegram · chat {chat_id}"


def _conversation(user, chat_id):
    """One ResearchConversation per chat, reused. Created INACTIVE so the
    web panel keeps showing the thread the operator left open there."""
    from brain.research_models import ResearchConversation
    title = _conversation_title(chat_id)
    conv = (ResearchConversation.objects.filter(user=user, title=title)
            .order_by("-last_message_at", "-pk").first())
    if conv is None:
        conv = ResearchConversation.objects.create(
            user=user, title=title, is_active=False)
    return conv


def questions_today(user, chat_id, now=None) -> int:
    """Questions this chat asked since 00:00 UTC (the cap's count)."""
    from django.utils import timezone
    from brain.research_models import ResearchMessage
    now = now or timezone.now()
    start = now.astimezone(dt_tz.utc).replace(hour=0, minute=0, second=0,
                                              microsecond=0)
    return ResearchMessage.objects.filter(
        conversation__user=user,
        conversation__title=_conversation_title(chat_id),
        role=ResearchMessage.ROLE_USER, created_at__gte=start).count()


def ask_question(user, chat_id, question: str, *, now=None) -> Reply:
    """Persist the question (brain.research_agent.begin_ask) and reply that
    the answer is coming. The reply carries the queueing as meta "then":
    handle() registers it for the commit BEHIND the reply, so the group
    reads "received" before any "could not answer"."""
    q = " ".join(str(question or "").split())
    if not q:
        return Reply(MARK_HELP, "Sauron — ask a question",
                     ["Write the question after /q, for example:",
                      "/q What is the market doing today?"])
    asked = questions_today(user, chat_id, now)
    if asked >= QUESTIONS_PER_DAY:
        return Reply(MARK_WARN, "Sauron — daily question limit reached",
                     [f"Questions today: {asked} of {QUESTIONS_PER_DAY}",
                      "The limit resets at 00:00 UTC.",
                      "The platform's Research page still answers."])
    from brain.research_agent import begin_ask
    _question_row, pending = begin_ask(
        _conversation(user, chat_id), q[:QUESTION_MAX_CHARS] + ASK_SUFFIX)
    pending_id = pending.pk

    def _queue():
        try:
            from bot_program.tasks import answer_telegram_question
            answer_telegram_question.delay(pending_id)
        except Exception as e:  # noqa: BLE001 (a broker down is an answer)
            name = type(e).__name__
            logger.warning("[telegram eye] the answer was not queued (%s)",
                           name)
            try:
                from brain.research_agent import fail_pending
                fail_pending(pending_id, f"not queued: {name}")
            finally:
                _send(user, could_not_answer(name))

    # "A few minutes": the ai queue is served by worker-slow, beside the
    # backtests (deploy/docker-compose.yml), so an answer can wait.
    return Reply(MARK_THINKING, "Sauron — question received",
                 ["The answer follows here in a few minutes.",
                  f"Questions today: {asked + 1} of {QUESTIONS_PER_DAY}"],
                 meta={"then": _queue})


_FENCE_RE = re.compile(r"```.*?(?:```|$)", re.DOTALL)
_MARKER_RE = re.compile(r"<<\s*([A-Za-z_]+)\s*:\s*([^>]+?)\s*>>")
#: The research agent's inline citations, in words (brain/research_renderer
#: turns them into links for the web page; the group gets the words).
#: The action markers (approve, reject, restore) are dropped: nothing is
#: approved from Telegram.
_MARKER_WORDS = {"RULE": "rule {v}", "HYP": "hypothesis #{v}",
                 "REPORT": "brain report #{v}", "AUDIT": "audit entry #{v}",
                 "BRIEFING": "briefing #{v}",
                 "EARNINGS": "earnings review #{v}",
                 "KNOWLEDGE": "knowledge note #{v}"}
_ACTION_MARKERS = {"APPROVE", "REJECT", "RESTORE"}
_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
_ITALIC_RE = re.compile(r"(?<![\w*])\*(?!\s)([^*\n]+?)(?<!\s)\*(?![\w*])")


def plain_answer(markdown: str) -> str:
    """The research agent's Markdown as plain text for the group: markers
    named in words, links as their words, no stars, no hashes, bullets
    as bullets. Escaping is the sender's (notifications._telegram_text)."""
    def _words(match):
        kind, value = match.group(1).upper(), match.group(2).strip()
        if kind in _ACTION_MARKERS:
            return ""
        shape = _MARKER_WORDS.get(kind)
        return shape.format(v=value) if shape else value

    text = _FENCE_RE.sub("(a block for the platform: open the Research "
                         "page)", str(markdown or ""))
    text = _MARKER_RE.sub(_words, text)
    text = _LINK_RE.sub(lambda m: m.group(1).replace("→", "").strip(), text)
    text = re.sub(r"(?<=\S) {2,}", " ", text)
    out = []
    for line in text.splitlines():
        s = line.rstrip()
        if s.strip() in ("---", "***", "___"):
            s = ""
        s = re.sub(r"^\s{0,3}#{1,6}\s*", "", s)
        s = re.sub(r"^(\s*)[-*+]\s+", r"\1• ", s)
        s = s.replace("**", "").replace("__", "")
        s = re.sub(r"`([^`]*)`", r"\1", s)
        s = _ITALIC_RE.sub(r"\1", s)
        out.append(s)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


def trim_answer(text: str, limit: int = ANSWER_MAX_CHARS) -> str:
    """At most `limit` characters once escaped, cut on a word, then
    "… (continued on the platform)"."""
    if len(escape(text)) <= limit:
        return text
    budget = limit - len(CONTINUED)
    cut = text[:budget]
    while cut and len(escape(cut)) > budget:
        cut = cut[:max(0, len(cut) - max(1, len(escape(cut)) - budget))]
    edge = max(cut.rfind(" "), cut.rfind("\n"))
    if edge > budget * 0.6:
        cut = cut[:edge]
    return cut.rstrip(" ,;:.\n") + CONTINUED


def answer_question(pending_id: int) -> dict:
    """The worker half: brain.research_agent.complete_ask, then the answer
    to the group, in plain English, trimmed. Any failure is said there."""
    from brain.research_agent import complete_ask, fail_pending
    from brain.research_models import ResearchMessage
    row = (ResearchMessage.objects.select_related("conversation__user")
           .filter(pk=pending_id).first())
    if row is None:
        return {"status": "error", "error": "message not found"}
    user = row.conversation.user
    if not _still_authorised(user):
        logger.info("[telegram eye] answer %s not sent: the chat is no "
                    "longer configured", pending_id)
        return {"status": "skipped", "reason": "chat no longer configured"}
    try:
        result = complete_ask(pending_id)
    except Exception as e:  # noqa: BLE001
        name = type(e).__name__
        logger.warning("[telegram eye] the research agent raised (%s)", name)
        try:
            fail_pending(pending_id, name)
        finally:
            _send(user, could_not_answer(name))
        return {"status": "error", "error": name}
    if result.get("already_settled"):
        return {"status": "success", "sent": 0}
    row.refresh_from_db()
    if not result.get("ok"):
        why = ("daily AI budget spent"
               if str(row.error or "").startswith("budget")
               else "research agent unavailable")
        _send(user, could_not_answer(why))
        return {"status": "error", "error": why}
    body = trim_answer(plain_answer(row.content)) or DASH
    sent = _send(user, Reply(MARK_ANSWER, "Sauron — answer", body=body))
    return {"status": "success", "sent": int(bool(sent))}


# ── one update ───────────────────────────────────────────────────────────

def _rate_ok(chat_id) -> bool:
    from django.core.cache import cache
    try:
        return bool(cache.add(RATE_KEY.format(chat=chat_id), 1,
                              timeout=RATE_S))
    except Exception:  # noqa: BLE001 (a cache down never silences a reply)
        return True


#: /stop's argument: bot numbers and nothing else ("4", "#4", "4 7",
#: "4, 7"). "/stop 4 à 14h30" must not also stop #14 and #30.
_IDS_RE = re.compile(r"#?\d+(?:\s*[,;]?\s*#?\d+)*")


def route(command: str, arg: str, user, chat_id, *, now=None,
          sent_at=None) -> Reply:
    if command == "status":
        return build_status(user, now=now)
    if command == "positions":
        return build_positions(user, now=now)
    if command == "why":
        return build_why(user, arg, now=now)
    if command == "stopall" or (command == "stop"
                                and _fold(arg) in ("all", "tout", "tous")):
        return apply_brake(user, everything=True, now=now, sent_at=sent_at)
    if command == "stop":
        text = str(arg or "").strip().rstrip(" .!")
        if not _IDS_RE.fullmatch(text):
            return which_bot()
        ids = [int(n) for n in re.findall(r"\d+", text)]
        return apply_brake(user, ids, now=now, sent_at=sent_at)
    if command == "ask":
        return ask_question(user, chat_id, arg, now=now)
    return build_help()


def _migration(msg, chat_id, chats, ambiguous) -> bool:
    """A basic group upgraded to a supergroup gets a new chat id, and
    every reply and alert to the old one fails from then on. Said at
    WARNING with the account to fix; the stored id is never rewritten
    from here. True for either service message, ours or not."""
    to_id = msg.get("migrate_to_chat_id")
    from_id = msg.get("migrate_from_chat_id")
    if not to_id and not from_id:
        return False
    old, new = (chat_id, str(to_id)) if to_id else (str(from_id), chat_id)
    owners = [chats[old]] if old in chats else list(ambiguous.get(old) or [])
    if owners:
        logger.warning("[telegram eye] the group %s is now the supergroup "
                       "%s: set telegram_chat_id to %s in the notification "
                       "settings of %s; until then the eye and the alerts "
                       "reach nobody", old, new, new,
                       ", ".join(u.username for u in owners))
    return True


def handle(update, *, chats=None, ambiguous=None, now=None,
           quiet=None) -> str:
    """One Telegram update. Returns a verdict word for the log and tests.

    The reply leaves after the COMMIT (transaction.on_commit): a reply
    whose update rolls back is never sent, so the group is never told of
    a brake the database does not hold. `quiet` (a set, per poll) logs
    an ignored chat once per batch rather than once per message."""
    from django.db import transaction
    from django.utils import timezone
    now = now or timezone.now()
    msg = update.get("message") if isinstance(update, dict) else None
    if not isinstance(msg, dict):
        return "ignored"
    chat = msg.get("chat") or {}
    chat_id = str(chat.get("id", "")).strip()
    if chats is None:
        chats, ambiguous = _chat_map()
    ambiguous = ambiguous or {}
    if _migration(msg, chat_id, chats, ambiguous):
        return "migrated"
    user = chats.get(chat_id)
    if user is None:
        owners = ambiguous.get(chat_id)
        if owners:
            if (parse(msg.get("text") or "")[0] is not None
                    and _once(f"ambiguous-reply:{chat_id}")):
                transaction.on_commit(
                    partial(_send, owners[0], ambiguous_reply()), robust=True)
            return "ambiguous"
        if quiet is None or chat_id not in quiet:
            logger.info("[telegram eye] ignored chat %s (%s)",
                        chat_id or "?", chat.get("type") or "?")
            if quiet is not None:
                quiet.add(chat_id)
        return "unauthorised"
    sender = msg.get("from") or {}
    # An anonymous admin posts as the group itself (from: the
    # GroupAnonymousBot, sender_chat: this chat). Any other bot: ignored.
    sender_chat = msg.get("sender_chat") or {}
    if (sender.get("is_bot")
            and str(sender_chat.get("id", "")).strip() != chat_id):
        return "ignored"
    command, arg = parse(msg.get("text") or "")
    if command is None:
        return "chatter"
    logger.info("[telegram eye] chat %s · %s · sender %s", chat_id, command,
                sender.get("id", "?"))
    brake = command in ("stop", "stopall")
    date = msg.get("date")
    sent = (datetime.fromtimestamp(date, dt_tz.utc)
            if isinstance(date, (int, float)) else None)
    age = (now - sent).total_seconds() if sent is not None else 0
    if not brake and age > STALE_AFTER_S:
        logger.info("[telegram eye] dropped a stale %s in chat %s (%d s old)",
                    command, chat_id, int(age))
        return "stale"
    if not brake and not _rate_ok(chat_id):
        logger.info("[telegram eye] rate-limited %s in chat %s", command,
                    chat_id)
        return "rate_limited"
    try:
        # Its own savepoint: a database error in a builder rolls back the
        # builder alone, and the "could not answer" below still leaves.
        with transaction.atomic():
            reply = route(command, arg, user, chat_id, now=now, sent_at=sent)
    except Exception as e:  # noqa: BLE001 (say it, do not crash the batch)
        logger.warning("[telegram eye] %s failed (%s)", command,
                       type(e).__name__, exc_info=True)
        reply = could_not_answer(type(e).__name__)
    if brake:
        logger.warning("[telegram eye] BRAKE from chat %s (sender %s): "
                       "configs %s turned off", chat_id,
                       sender.get("id", "?"),
                       reply.meta.get("stopped", []))
    transaction.on_commit(partial(_send, user, reply), robust=True)
    then = reply.meta.get("then")
    if callable(then):
        transaction.on_commit(then, robust=True)
    return f"answered:{command}"


# ── the poll ─────────────────────────────────────────────────────────────

def _failing(method: str, kind: str, why: str) -> None:
    from django.core.cache import cache
    try:
        cache.set(FAILING_KEY.format(method=method), why, CURSOR_TTL_S)
    except Exception:  # noqa: BLE001
        pass
    _note(kind, why)


def _recovered(method: str) -> None:
    """The first answer after a fault, said once."""
    from django.core.cache import cache
    key = FAILING_KEY.format(method=method)
    try:
        was = cache.get(key)
        if was is None:
            return
        cache.delete(key)
    except Exception:  # noqa: BLE001
        return
    logger.info("[telegram eye] %s answers again (last fault: %s)", method,
                was)


def _api(token: str, method: str, params: dict):
    """(result, None) or (None, why). Never raises, and never logs the
    URL: it carries the token, and so does the text of a transport error.
    A fault is logged at WARNING once an hour (_note), its end once."""
    url = API_URL.format(token=token, method=method)
    try:
        r = requests.get(url, params=params, timeout=HTTP_TIMEOUT_S)
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
        said = str(data.get("description") or "")[:200]
        why = f"{method} refused ({status})" + (f": {said}" if said else "")
        _failing(method, f"{method}:{status}", why)
        return None, why
    _recovered(method)
    return data.get("result"), None


def _take_lock() -> bool:
    """The batch lock, taken WITHOUT waiting: False while another poll
    holds it. pg_try_advisory_xact_lock, released by the commit. Not the
    telegram_eye row: guarded_task's mark_run writes that row after every
    run, so on Postgres the poll that skipped would wait behind the one
    holding it, and so would `component off telegram_eye`. SQLite (the
    suite's database) has no such lock: True."""
    from django.db import connection
    if connection.vendor != "postgresql":
        return True
    with connection.cursor() as cur:
        cur.execute("SELECT pg_try_advisory_xact_lock(%s)", [BATCH_LOCK_ID])
        row = cur.fetchone()
    return bool(row and row[0])


def _cursor_key(token: str) -> str:
    """The belt's key, per bot: a new token (a new bot, a new numbering)
    must not inherit the old one's last id. A hash, never the token."""
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()[:12]
    return f"{CURSOR_KEY}:{digest}"


def _last_handled(token: str):
    from django.core.cache import cache
    try:
        value = cache.get(_cursor_key(token))
        return None if value is None else int(value)
    except Exception:  # noqa: BLE001
        return None


def _remember(token: str, update_id: int) -> None:
    from django.core.cache import cache
    try:
        cache.set(_cursor_key(token), int(update_id), CURSOR_TTL_S)
    except Exception:  # noqa: BLE001
        logger.warning("[telegram eye] could not remember update %s",
                       update_id)


def _update_id(update) -> int:
    try:
        return int(update.get("update_id"))
    except (AttributeError, TypeError, ValueError):
        return -1


def _chat_of(update) -> str:
    try:
        return str(update["message"]["chat"]["id"])
    except (KeyError, TypeError):
        return "?"


def poll(*, now=None) -> dict:
    """Fetch, handle, confirm: one batch at a time, ending at a brake. The
    replies and the belt wait for the commit (handle, on_commit)."""
    from django.db import transaction
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        return {"status": "skipped",
                "reason": "TELEGRAM_BOT_TOKEN is not set"}
    chats, ambiguous = _chat_map()
    if not chats and not ambiguous:
        return {"status": "skipped",
                "reason": "no staff user has a Telegram chat configured"}
    with transaction.atomic():
        if not _take_lock():
            return {"status": "skipped",
                    "reason": "another poll holds the batch"}
        seen = _last_handled(token)
        verdicts, quiet = [], set()
        fetched, last, offset = 0, None, None
        for _page in range(MAX_PAGES):
            params = {"timeout": 0, "limit": PAGE_SIZE,
                      "allowed_updates": ALLOWED_UPDATES}
            if offset is not None:
                params["offset"] = offset
            updates, why = _api(token, "getUpdates", params)
            if updates is None:
                if last is None:
                    return {"status": "error", "error": why}
                break
            updates = updates if isinstance(updates, list) else []
            batch = sorted((u for u in updates if _update_id(u) >= 0),
                           key=_update_id)
            fetched += len(batch)
            braked = False
            for update in batch:
                uid = _update_id(update)
                if seen is not None and uid <= seen:
                    logger.warning("[telegram eye] update %s from chat %s "
                                   "was handled before; skipped", uid,
                                   _chat_of(update))
                    verdict = "seen"
                else:
                    try:
                        with transaction.atomic():
                            verdict = handle(update, chats=chats,
                                             ambiguous=ambiguous, now=now,
                                             quiet=quiet)
                    except Exception as e:  # noqa: BLE001
                        logger.warning("[telegram eye] update %s failed (%s)",
                                       uid, type(e).__name__, exc_info=True)
                        verdict = "failed"
                verdicts.append(verdict)
                last = uid
                if verdict in BRAKE_VERDICTS:
                    # The brake commits now; the rest waits 15 s.
                    braked = True
                    break
            if braked or last is None or len(updates) < PAGE_SIZE:
                break
            offset = last + 1
        if last is None:
            return {"status": "success", "updates": 0, "answered": 0}
        transaction.on_commit(partial(_remember, token, last), robust=True)
        confirmed, _why = _api(token, "getUpdates",
                               {"offset": last + 1, "timeout": 0, "limit": 1,
                                "allowed_updates": ALLOWED_UPDATES})
    return {"status": "success", "updates": fetched,
            "answered": sum(1 for v in verdicts if v.startswith("answered")),
            "confirmed": confirmed is not None}
