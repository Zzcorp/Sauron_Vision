"""Telegram alert channel — two-way bot with command support.

SUPERSEDED FOR COMMANDS (2026-09-26): bot_program/telegram_eye.py reads
the group now, from the configured chat only, in English, and its one
write to trading state is the brake. The reader below
(check_bot_updates and
process_commands, wrapped by alerts.tasks.check_telegram_commands) has
no sender check and no offset: it would approve a strategy for anyone
who can write to the bot; it passes no offset, so it would re-read every
unconfirmed update and act on it again, and its getUpdates would collide
with the eye's (409 Conflict). It must never be scheduled;
tests/test_telegram_eye.py pins
that no beat entry names it. The senders (send_telegram,
send_strategy_proposal) stay in use.
"""
import os
import re
import requests
import logging

logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"


# ── The one per-chat sender (2026-09-26) ─────────────────────────────────
# Every Telegram message outside bot_program.notifications leaves through
# send_to_chat, in the house style of the bot's fills: HTML parse mode,
# every field escaped, one leading emoji mark, a bold title, one fact per
# line, rendered by bot_program.notifications._telegram_text (the one
# renderer). Until 2026-09-26 these paths posted legacy Markdown and most
# never read the answer: a signal whose words carried an underscore was a
# 400 "can't parse entities" that vanished without a line.

#: Telegram refuses a longer message.
TELEGRAM_MAX_CHARS = 4096
#: The last line of a message cut to fit.
CONTINUED = "… (continued on the platform)"
#: A title longer than this is cut before it is rendered.
TITLE_MAX_CHARS = 200
SEND_TIMEOUT_S = 10

#: The leading emoji of each message these paths send (the Telegram
#: client draws it; the bell keeps the platform's own marks).
MARKS = {
    "signal_bullish": "\U0001F4C8",
    "signal_bearish": "\U0001F4C9",
    "signal": "\U0001F4E1",
    "price_alert": "\U0001F514",
    "morning_brief": "\u2600\uFE0F",
    "end_of_day": "\U0001F319",
    "digest": "\U0001F4CB",
    "news": "\U0001F6A8",
    "newsletter": "\U0001F4F0",
    "proposal": "\U0001F4DD",
}

_HOST_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?(?::\d{1,5})?")
_MD_HEADING = re.compile(r"^#{1,6}\s+(.*?)\s*#*$")
_MD_BULLET = re.compile(r"^[-*+]\s+(.*)$")
_MD_MARKERS = re.compile(r"\*\*|__|`")
#: [text](url) and ![alt](url); an optional <url> and "title".
_MD_LINK = re.compile(
    r"!?\[([^\]\n]*)\]\(\s*<?([^()\s<>]+)>?(?:\s+\"[^\"\n]*\")?\s*\)")
#: *word* and _word_ emphasis. Never inside a word, so a rule name such
#: as rates_up or golden_cross keeps its underscore.
_MD_EMPHASIS = re.compile(
    r"(?<![\w*])\*(?=\S)([^*\n]+?)(?<=\S)\*(?![\w*])"
    r"|(?<![\w_])_(?=\S)([^_\n]+?)(?<=\S)_(?![\w_])")


def _md_plain(text: str) -> str:
    """One line of Markdown as plain words: a link reads "text (url)",
    the emphasis markers and code ticks come off."""
    def link(m):
        words, url = m.group(1).strip(), m.group(2)
        return f"{words} ({url})" if words and words != url else url
    text = _MD_LINK.sub(link, text)
    text = _MD_MARKERS.sub("", text)
    text = _MD_EMPHASIS.sub(lambda m: m.group(1) or m.group(2), text)
    return text.strip()


def _units(text: str) -> int:
    """A length as Telegram counts it (UTF-16 code units: an emoji is two)."""
    return len(text.encode("utf-16-le")) // 2


def _cut_to_fit(render, plain: str) -> str:
    """render(the longest prefix of `plain`) that fits, found by halving.

    The overflow of the rendered text says little about how many plain
    characters to drop: "&" renders as five ("&amp;") and an emoji counts
    two, so subtracting it threw away text that would have fitted. A
    longer prefix never renders shorter, so a binary search finds the
    longest one in about log2(len) renders (14 for 10,000 characters).
    """
    text = render(plain.rstrip())
    if _units(text) <= TELEGRAM_MAX_CHARS:
        return text
    best = render("")
    lo, hi = 0, len(plain) - 1  # the longest fitting prefix is in [lo, hi]
    while lo < hi:
        mid = (lo + hi + 1) // 2
        text = render(plain[:mid].rstrip())
        if _units(text) <= TELEGRAM_MAX_CHARS:
            lo, best = mid, text
        else:
            hi = mid - 1
    return best


def fit_text(title, body="", *, lines=None, mark="") -> str:
    """The house HTML for one message, under TELEGRAM_MAX_CHARS.

    Too long, it loses whole lines from the end and ends on CONTINUED; a
    single line or a body too long on its own is cut on its plain words
    and rendered again, so a cut never lands inside an escape or a tag.
    """
    from bot_program.notifications import _telegram_text
    title = str(title or "")
    if len(title) > TITLE_MAX_CHARS:
        title = title[:TITLE_MAX_CHARS - 1].rstrip() + "…"
    text = _telegram_text(title, body, lines=lines, mark=mark)
    if _units(text) <= TELEGRAM_MAX_CHARS:
        return text
    if lines:
        kept = [ln for ln in lines if str(ln or "").strip()]
        while len(kept) > 1:
            kept.pop()
            text = _telegram_text(title, "", lines=kept + [CONTINUED],
                                  mark=mark)
            if _units(text) <= TELEGRAM_MAX_CHARS:
                return text
        return _cut_to_fit(
            lambda s: _telegram_text(title, "", lines=[s, CONTINUED],
                                     mark=mark),
            str(kept[0]) if kept else "")
    return _cut_to_fit(
        lambda s: _telegram_text(title, (s + "\n" + CONTINUED) if s
                                 else CONTINUED, mark=mark),
        str(body or ""))


def platform_link(path) -> str:
    """The absolute address of a platform page, or "" when this
    deployment does not name its host.

    DOMAIN is the host Caddy serves the platform on (deploy/Caddyfile):
    docker-compose refuses to start without it, and every container reads
    the same .env. Nothing else here builds an absolute link (the fills,
    the Eye and the component digest send none), so a missing or
    placeholder DOMAIN leaves the path in words instead.
    """
    path = str(path or "").strip()
    if not path.startswith("/") or path.startswith("//"):
        return ""
    host = os.getenv("DOMAIN", "").strip().rstrip("/")
    if (not host or not _HOST_RE.fullmatch(host)
            or host.lower().endswith("example.com")):
        return ""
    return f"https://{host}{path}"


def page_line(path, label: str = "Page") -> str:
    """"Page: https://…" when the host is known, else the path in words."""
    path = str(path or "").strip()
    if not path:
        return ""
    link = platform_link(path)
    return f"{label}: {link}" if link else f"{label}: {path} on the platform"


def markdown_lines(markdown) -> list:
    """Markdown written for a page (the newsletter) as Telegram lines: a
    heading becomes a bold line, a bullet "• …", a link "text (url)";
    emphasis markers and code ticks come off. Nothing in it is read as
    HTML: the renderer escapes every line."""
    from bot_program.notifications import TelegramHeading
    out = []
    for raw in str(markdown or "").splitlines():
        line = raw.strip()
        if not line or re.fullmatch(r"[-*_]{3,}", line):
            continue
        m = _MD_HEADING.match(line)
        if m:
            words = _md_plain(m.group(1))
            if words:
                out.append(TelegramHeading(words))
            continue
        m = _MD_BULLET.match(line)
        if m:
            line = "• " + m.group(1)
        line = _md_plain(line)
        if line:
            out.append(line)
    return out


def send_to_chat(chat_id, title, body="", *, lines=None, mark="") -> bool:
    """Post one house-style message to `chat_id`: True when Telegram took it.

    HTML parse mode, every field escaped (fit_text), no link preview, a
    10-second timeout, and it never raises. A refusal is logged at WARNING
    with Telegram's own words (its status and the first 200 characters of
    its answer), and so is a transport error, token scrubbed: the address
    carries it, and a connection error quotes the address.
    """
    chat = str(chat_id or "").strip()
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not (token and chat):
        logger.debug("telegram: %r not sent (no bot token or no chat)",
                     str(title)[:120])
        return False
    try:
        text = fit_text(title, body, lines=lines, mark=mark)
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat, "text": text, "parse_mode": "HTML",
                  "disable_web_page_preview": True},
            timeout=SEND_TIMEOUT_S,
        )
    except Exception as e:  # noqa: BLE001 — a message never breaks its caller
        logger.warning("telegram send failed %r: %s", str(title)[:120],
                       str(e).replace(token, "<token>")[:200])
        return False
    if not getattr(r, "ok", False):
        logger.warning("telegram refused (%s) %r: %s",
                       getattr(r, "status_code", "?"), str(title)[:120],
                       str(getattr(r, "text", ""))[:200])
        return False
    return True


def send_telegram(title, message="", *, lines=None, mark="") -> bool:
    """To the platform chat (TELEGRAM_CHAT_ID), in the house style.

    The signature its callers have always used, now through send_to_chat:
    True when Telegram took it, and it never raises (until 2026-09-26 it
    posted Markdown and raised on a refusal).
    """
    chat = os.getenv("TELEGRAM_CHAT_ID", "")
    if not (os.getenv("TELEGRAM_BOT_TOKEN", "") and chat):
        logger.warning("Telegram not configured")
        return False
    return send_to_chat(chat, title, message, lines=lines, mark=mark)


def send_strategy_proposal(strategy) -> bool:
    """A strategy proposal to the platform chat, in the house style.

    The /approve and /reject lines stay as text. The reader that acted on
    them (process_commands, below) is dormant and must stay so; see the
    module docstring.
    """
    lines = [f"Horizon: {strategy.time_horizon}",
             f"Maximum allocation: {strategy.max_portfolio_allocation_pct}%"]
    about = " ".join(str(strategy.description or "").split())
    if about:
        lines.append(about if len(about) <= 500
                     else about[:499].rstrip() + "…")
    lines.append(f"Reply /approve {strategy.id} to approve it")
    lines.append(f"Reply /reject {strategy.id} to reject it")
    return send_telegram(f"New strategy proposal · {strategy.name}",
                         lines=lines, mark=MARKS["proposal"])


def check_bot_updates():
    """Check for incoming Telegram messages (commands)."""
    if not BOT_TOKEN:
        return []

    try:
        resp = requests.get(f"{BASE_URL}/getUpdates", params={"timeout": 1, "limit": 10})
        if not resp.ok:
            return []
        data = resp.json()
        return data.get("result", [])
    except Exception:
        return []


def process_commands():
    """Process incoming Telegram commands."""
    from strategies.models import Strategy

    updates = check_bot_updates()
    processed = 0

    for update in updates:
        msg = update.get("message", {})
        text = msg.get("text", "").strip()

        if text.startswith("/approve "):
            try:
                strategy_id = int(text.split(" ")[1])
                strategy = Strategy.objects.get(id=strategy_id, status="proposed")
                strategy.status = "approved"
                strategy.save()
                send_telegram("Strategy Approved", f"{strategy.name} is now approved.")
                processed += 1
            except (ValueError, Strategy.DoesNotExist):
                send_telegram("Error", "Strategy not found or already processed.")

        elif text.startswith("/reject "):
            try:
                strategy_id = int(text.split(" ")[1])
                strategy = Strategy.objects.get(id=strategy_id, status="proposed")
                strategy.status = "rejected"
                strategy.save()
                send_telegram("Strategy Rejected", f"{strategy.name} has been rejected.")
                processed += 1
            except (ValueError, Strategy.DoesNotExist):
                send_telegram("Error", "Strategy not found or already processed.")

        elif text == "/status":
            from signals.models import Signal
            from portfolio.services import get_or_create_default_portfolio
            portfolio = get_or_create_default_portfolio()
            active_signals = Signal.objects.filter(is_active=True).count()
            send_telegram("Platform Status",
                f"Portfolio: {portfolio.currency} {portfolio.current_value}\n"
                f"Active signals: {active_signals}\n"
                f"Positions: {portfolio.positions.filter(closed_at__isnull=True).count()}"
            )
            processed += 1

        elif text == "/signals":
            from signals.models import Signal
            signals = Signal.objects.filter(is_active=True).order_by("-score")[:5]
            if signals:
                lines = []
                for s in signals:
                    # The direction is already a word on this line, so the
                    # coloured dot it duplicated is gone rather than replaced
                    # — a Telegram client picks its own font for any mark.
                    lines.append(f"{s.instrument.symbol} {s.direction} — {s.score:.2f}")
                send_telegram("Active signals", lines=lines)
            else:
                send_telegram("Signals", "No active signals.")
            processed += 1

    return processed
