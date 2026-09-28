# -*- coding: utf-8 -*-
"""THE MONDAY GAME PLAN, READ WHOLE (2026-09-27).

The operator, 2026-09-27: "the monday game plan is not fully visible it
seems, only on hover... fix it". generate_monday_plan (ai_agents/tasks.py)
put the plan in one place a person could read: the bell's notification,
cut at 2,000 characters and linked to /briefing/, which never showed it.

  * THE STORE is the row the agent's run already writes: AgentTask(agent
    "monday_plan", success) holds the model's whole answer in
    structured_output["plan"], and since 2026-09-27 "week_of", the Monday
    of the week it is for. An older row has no week_of: it is worked out
    from the row's own time by the same rule (week_of). No new table.
  * THE PAGE: /briefing/#monday-plan shows the latest plan whole and the
    four before it, folded, one per week (plans_for_page). The text is
    model output: the template renders it through research_md, the
    platform's safe renderer (everything escaped first; headings, lists,
    bold, code and links allowed) and never marks it safe raw. Here
    (readable) a Markdown table becomes a list a phone can read, every
    cell kept; a fenced code block is left as the model wrote it; and a
    link to anything but a same-site path becomes words, "label
    (address)", the way telegram_alert.markdown_lines says a link, so
    model text never puts a live link to another site on a staff page.
    The ```json calls block the calibration grades comes out of the prose
    with the one line that only heads it, and is said in words
    (split_plan, call_words); nothing else above it is taken.
  * THE BELL: a short plain summary (summary_lines: the plan's first
    lines, whole sentences, never cut inside a word), "Read the full
    plan", and the link to /briefing/#monday-plan.
  * TELEGRAM: the staff group (bot_program.morgul.recipients: one active
    staff user per configured chat, notify_channel telegram) gets the
    house-style message through send_to_chat, the platform's one
    per-chat sender: the title with its week, the summary lines, and the
    button "Read the full plan" when the platform names its host
    (telegram_alert.button_markup); without one, the last line says where
    to read it. A refusal is logged by send_to_chat with Telegram's own
    words, and again here with its chat.

Nothing here trades, sizes or switches anything.
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import date, datetime, timedelta
from datetime import timezone as dt_tz

logger = logging.getLogger(__name__)

#: The AgentTask.agent the plan's run writes (MondayPlanAgent.agent_name).
AGENT = "monday_plan"
#: The section on /briefing/, and the one address the bell and Telegram give.
ANCHOR = "monday-plan"
PAGE_PATH = "/briefing/#" + ANCHOR
READ_WORDS = "Read the full plan"
#: The end of the bell's body, and Telegram's last line when no button
#: can be drawn.
WHERE_WORDS = "Read the full plan on the Strategist Briefing page."
#: The Telegram client's mark for the plan: a calendar.
MARK = "\U0001F5D3️"
#: The earlier plans the page keeps within reach, under the latest.
OLDER_PLANS = 4
#: The rows read to find them (a failed run writes no plan).
SCAN_ROWS = 30
#: The summary: at most this many lines, this many characters in all and
#: this many on one line — whole sentences only.
SUMMARY_MAX_LINES = 5
SUMMARY_MAX_CHARS = 600
LINE_MAX_CHARS = 240
#: Less room than this is not worth starting another line in.
MIN_ROOM = 40
#: A call's reason is cut past this, at a word.
WHY_MAX_CHARS = 200

_RULE = re.compile(r"^\s*([-*_])(?:\s*\1){2,}\s*$")
_BOLD_LABEL = re.compile(r"^\s*\*\*([^*\n]{1,80}?)\*\*\s*:?\s*$")
_HEADING = re.compile(r"^\s*#{1,6}\s")
_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")
_TABLE_SEP = re.compile(r"^\s*\|?[\s:|-]*-[\s:|-]*\|?\s*$")
_SENTENCE_GAP = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(£$€])")
_LIST_NUMBER = re.compile(r"^\d{1,2}[.)]$")
#: A part that ends in one of these did not end a sentence: "the U.S. CPI
#: print", "Dr. Smith", "J. Powell", "e.g. GLDM", "8:30 a.m. ET". When in
#: doubt two parts stay one sentence: a summary line may run longer, never
#: stop in the middle of one.
_ABBREVIATION = re.compile(
    r"(?:(?:\b[A-Za-z]\.){2,}|\b[A-Z]\.|\b(?:Dr|Mr|Mrs|Ms|Prof|St|Jr|Sr|"
    r"Gov|Rep|Sen|vs|etc|approx|Inc|Corp|Co|Ltd|No|Jan|Feb|Mar|Apr|Jun|"
    r"Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.)$")
#: A label that heads the calls block names them: "## Directional Calls",
#: "**Calls:**", "The calls:". Longer than this, it is the plan's words.
_CALLS_WORD = re.compile(r"\bcalls?\b", re.I)
CALLS_LABEL_MAX_WORDS = 6
#: A fenced code block exactly as research_md reads one; readable leaves
#: what is inside as the model wrote it.
_CODE_FENCE = re.compile(r"(?ms)^```[^\n]*\n.*?^```[ \t]*$")
#: A Markdown link exactly as research_md reads one, and the one kind of
#: address it may keep: a same-site path ("/book/", never "//host" or
#: "/\host", which leave the site).
_MD_LINK = re.compile(r"\[([^\]\n]+)\]\(((?:[^()\s]|\([^()\s]*\))+)\)")
_SAME_SITE = re.compile(r"^/(?![/\\])")


# ── the week ──────────────────────────────────────────────────────────────

def week_of(moment) -> date:
    """The Monday of the trading week a plan written at `moment` is for:
    on a Saturday or a Sunday the coming Monday, on a weekday the Monday
    of that same week. The beat writes it on Sunday evening (UTC)."""
    if isinstance(moment, datetime):
        if moment.tzinfo is not None:
            moment = moment.astimezone(dt_tz.utc)
        moment = moment.date()
    wd = moment.weekday()
    if wd >= 5:
        return moment + timedelta(days=7 - wd)
    return moment - timedelta(days=wd)


def week_words(day) -> str:
    """"28 September 2026"."""
    return "%d %s" % (day.day, day.strftime("%B %Y"))


def title_for(week) -> str:
    return "Monday game plan — week of %s" % week_words(week)


def written_words(moment) -> str:
    """"Sunday 27 September 2026 at 18:00 UTC"; "" when absent."""
    if moment is None:
        return ""
    m = moment.astimezone(dt_tz.utc) if moment.tzinfo else moment
    return "%s %d %s at %s UTC" % (m.strftime("%A"), m.day,
                                   m.strftime("%B %Y"), m.strftime("%H:%M"))


def _stored_week(value):
    try:
        return date.fromisoformat(str(value or ""))
    except ValueError:
        return None


# ── the text ──────────────────────────────────────────────────────────────

def _bold_label(line) -> str:
    """The words of a bold LABEL on its own line ("**Key Levels:**" ->
    "Key Levels"), or "". A bold sentence ("**Never move a stop.**") is
    emphasis, not a heading: it ends like a sentence and stays as it is."""
    m = _BOLD_LABEL.match(line)
    if not m:
        return ""
    words = m.group(1).strip().rstrip(":").strip()
    return "" if words.endswith((".", "!", "?")) else words


def _calls_label(line) -> bool:
    """A line that only heads the calls block: a heading, a bold label or a
    short line ending in ":" whose words name the calls ("## Directional
    Calls", "**Calls:**", "The calls:"). Anything else is the plan's own
    words — a closing line, a bold rule, a last section — and stays."""
    s = str(line or "").strip()
    if _HEADING.match(s):
        words = s.lstrip("#")
    else:
        words = _bold_label(s) or (s[:-1] if s.endswith(":") else "")
    words = words.replace("*", "").strip().rstrip(":").strip()
    return (bool(words) and len(words.split()) <= CALLS_LABEL_MAX_WORDS
            and bool(_CALLS_WORD.search(words)))


def split_plan(text) -> tuple:
    """(the prose, the calls). The fenced ```json block the calibration
    grades — ai_agents.calibration._FENCE, extract_calls' own reading (the
    last such block gives the calls) — is taken out of the text, and so is
    the ONE line right above it that only heads it (_calls_label). Nothing
    else goes: whatever the model wrote above or below the block stays, and
    so does any other fence. The calls come back as the dicts the model
    wrote."""
    from ai_agents.calibration import _FENCE
    source = str(text or "").replace("\r\n", "\n")
    found, kept, last = [], [], 0
    for m in _FENCE.finditer(source):
        try:
            data = json.loads(m.group(1))
        except (TypeError, ValueError):
            continue
        if not (isinstance(data, dict)
                and isinstance(data.get("calls"), list)):
            continue
        found = [c for c in data["calls"] if isinstance(c, dict)]
        before = source[last:m.start()].rstrip().split("\n")
        if _calls_label(before[-1]):
            before.pop()
        kept.append("\n".join(before))
        last = m.end()
    kept.append(source[last:])
    prose = "\n\n".join(p.strip("\n") for p in kept if p.strip())
    return prose.strip(), found


def _cells(row) -> list:
    return [c.strip() for c in row.strip().strip("|").split("|")]


def _table_as_list(rows) -> list:
    """A Markdown table as list lines: "- EURUSD — Support: 1.0850,
    Resistance: 1.0950" when it has a header, the cells joined otherwise.
    No cell is lost: one past the header's width is said after the named
    ones, and a header with no row under it stays as a line."""
    head = None
    if len(rows) >= 2 and _TABLE_SEP.match(rows[1]):
        head, rows = _cells(rows[0]), rows[2:]
    out = []
    for row in rows:
        if _TABLE_SEP.match(row):
            continue
        cells = _cells(row)
        if not any(cells):
            continue
        if head:
            facts = ["%s: %s" % (h, c) if h else c
                     for h, c in zip(head[1:], cells[1:]) if c]
            facts += [c for c in cells[len(head):] if c]
            first = cells[0]
            text = (first + (" — " + ", ".join(facts) if facts else "")
                    if first else ", ".join(facts))
        else:
            text = " · ".join(c for c in cells if c)
        if text:
            out.append("- " + text)
    if head and not out and any(head):
        out.append("- " + " · ".join(h for h in head if h))
    return out


def _link_words(m) -> str:
    """A Markdown link as the page may show it: a same-site path stays a
    link; any other address is said, not followed — "label (address)", the
    words telegram_alert.markdown_lines gives a link on Telegram."""
    label, url = m.group(1), m.group(2)
    if "\\" not in url and _SAME_SITE.match(url):
        return m.group(0)
    return "%s (%s)" % (label, url)


def _unlinked(text) -> str:
    """`text` with every link elsewhere turned into words. Again until
    nothing changes: a link written inside another's label is found once
    the outer one is words."""
    for _ in range(20):
        said = _MD_LINK.sub(_link_words, text)
        if said == text:
            break
        text = said
    return text


def _readable_lines(text) -> str:
    """readable() for text outside any fenced code block."""
    out, table = [], []

    def flush():
        if table:
            out.extend(_table_as_list(table))
            out.append("")
            table.clear()

    for line in _unlinked(text).split("\n"):
        if _TABLE_ROW.match(line):
            table.append(line)
            continue
        flush()
        if _RULE.match(line):
            out.append("")
            continue
        label = _bold_label(line)
        if label:
            out.append("### " + label)
            continue
        out.append(line)
    flush()
    return "\n".join(out)


def readable(prose) -> str:
    """The prose as the page and the summary read it: a Markdown table
    becomes a list (a phone has no room for one) with every cell kept, a
    rule (---) goes, a bold line on its own becomes the heading it stands
    for, and a link to anything but a same-site path becomes words (model
    text never puts a live link to another site on a staff page). A fenced
    code block — as research_md finds one — is left exactly as written, and
    so is everything else."""
    text = str(prose or "").replace("\r\n", "\n")
    parts, last = [], 0
    for m in _CODE_FENCE.finditer(text):
        parts.append(_readable_lines(text[last:m.start()]))
        parts.append(m.group(0))
        last = m.end()
    parts.append(_readable_lines(text[last:]))
    return "".join(parts).strip()


def _sentences(text) -> list:
    parts = [p.strip() for p in _SENTENCE_GAP.split(text) if p.strip()]
    out = []
    for part in parts:
        # "1. Buy the dip." is one sentence, not "1." and "Buy the dip.";
        # "the U.S. CPI print" and "Dr. Smith" do not end at their stop.
        if out and (_LIST_NUMBER.match(out[-1])
                    or _ABBREVIATION.search(out[-1])):
            out[-1] = out[-1] + " " + part
        else:
            out.append(part)
    return out


def _lead(text, room) -> str:
    """`text`'s leading whole sentences within `room` characters; "" when
    not even the first one fits."""
    kept = ""
    for sentence in _sentences(text):
        candidate = (kept + " " + sentence) if kept else sentence
        if len(candidate) > room:
            break
        kept = candidate
    return kept


def _words(text, room) -> str:
    """`text` within `room` characters, cut at a space and ended with an
    ellipsis — only for a first sentence too long to stand whole. Never
    inside a word."""
    text = " ".join(str(text or "").split())
    if len(text) <= room:
        return text
    head = text[:room - 1]
    if not text[room - 1:room].isspace():
        cut_at = head.rfind(" ")
        if cut_at > 0:
            head = head[:cut_at]
    return head.rstrip(" ,;:—–-") + "…"


def summary_lines(prose, *, max_lines=SUMMARY_MAX_LINES,
                  max_chars=SUMMARY_MAX_CHARS) -> list:
    """The plan's first lines in plain words, for the bell and Telegram.

    Headings and lines that only introduce a list ("Key levels:") are
    skipped; each line keeps its leading WHOLE sentences within the room
    left (a long paragraph gives its lead, and the walk goes on to the
    next line); it stops at max_lines, or at a line whose first sentence
    no longer fits. Only a first line whose first sentence is too long on
    its own is cut, at a word, with an ellipsis. Markdown comes off
    (telegram_alert.
    markdown_lines, the platform's reader); nothing is escaped here —
    every sender escapes."""
    from alerts.channels.telegram_alert import markdown_lines
    from bot_program.notifications import TelegramHeading
    out, used = [], 0
    for line in markdown_lines(readable(prose)):
        if len(out) >= max_lines:
            break
        if isinstance(line, TelegramHeading):
            continue
        text = " ".join(str(line).split())
        if not re.search(r"[A-Za-z]", text) or text.endswith(":"):
            continue
        room = min(LINE_MAX_CHARS, max_chars - used)
        if room < MIN_ROOM:
            break
        said = text if len(text) <= room else _lead(text, room)
        if not said:
            if out:
                break
            said = _words(text, room)
        out.append(said)
        used += len(said)
    return out


def notification_body(lines) -> str:
    """The bell's body: the summary, then where to read the rest."""
    parts = ["\n".join(lines)] if lines else []
    parts.append(WHERE_WORDS)
    return "\n\n".join(parts)


def _num(value):
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out == out else None


def _hours_words(hours) -> str:
    if hours < 48:
        n = max(1, int(round(hours)))
        return "%d hour%s" % (n, "" if n == 1 else "s")
    n = int(round(hours / 24.0))
    return "%d days" % n


def call_words(call) -> str:
    """One call of the plan in words: "EURUSD — up within 3 days,
    confidence 60%. A soft dollar." "" for one without a symbol."""
    from ai_agents.calibration import normalise_direction
    if not isinstance(call, dict):
        return ""
    symbol = " ".join(str(call.get("symbol") or "").split())[:24]
    if not symbol:
        return ""
    way = normalise_direction(call.get("direction")) or "no clear direction"
    text = "%s — %s" % (symbol, way)
    hours = _num(call.get("horizon_hours"))
    if hours is not None and hours > 0:
        text += " within " + _hours_words(hours)
    conf = _num(call.get("confidence"))
    if conf is not None and 0 <= conf <= 1:
        text += ", confidence %d%%" % int(round(conf * 100))
    elif conf is not None and 1 < conf <= 100:
        text += ", confidence %d%%" % int(round(conf))
    why = " ".join(str(call.get("why") or call.get("reason") or "").split())
    if why:
        why = _words(why, WHY_MAX_CHARS)
        if not why.endswith((".", "!", "?", "…")):
            why += "."
        text += ". " + why[:1].upper() + why[1:]
    return text


# ── the plans on the page ────────────────────────────────────────────────

def plan_view(task):
    """What the page shows of one AgentTask row, or None when the row
    holds no plan."""
    stored = task.structured_output if isinstance(
        task.structured_output, dict) else {}
    text = stored.get("plan")
    if not isinstance(text, str) or not text.strip():
        return None
    week = _stored_week(stored.get("week_of")) or week_of(task.created_at)
    prose, calls = split_plan(text)
    return {
        "id": task.pk,
        "week": week,
        "week_words": week_words(week),
        "written_words": written_words(task.created_at),
        "prose": readable(prose),
        "calls": [w for w in (call_words(c) for c in calls) if w],
    }


def recent_plans(limit=1 + OLDER_PLANS) -> list:
    """The latest plans, newest first, one per week (a run made again for
    the same week replaces the one before it on the page)."""
    from ai_agents.models import AgentTask
    rows = (AgentTask.objects.filter(agent=AGENT, success=True)
            .order_by("-created_at", "-pk")
            .only("pk", "created_at", "structured_output")[:SCAN_ROWS])
    out, weeks = [], set()
    for row in rows:
        view = plan_view(row)
        if view is None or view["week"] in weeks:
            continue
        weeks.add(view["week"])
        out.append(view)
        if len(out) >= limit:
            break
    return out


def plans_for_page() -> dict:
    """{"latest": the latest plan or None, "older": up to OLDER_PLANS
    before it}. Never raises: the page then says there is no plan yet."""
    try:
        plans = recent_plans()
    except Exception:  # noqa: BLE001 — a page never dies of its plan
        logger.exception("[monday plan] the plans could not be read for "
                         "/briefing/")
        plans = []
    return {"latest": plans[0] if plans else None, "older": plans[1:]}


# ── announcing a new plan ────────────────────────────────────────────────

def telegram_to_staff(title, lines) -> dict:
    """The house message to each staff chat once: {chats, sent, refused}."""
    from alerts.channels.telegram_alert import button_markup, send_to_chat
    from bot_program.morgul import recipients
    out = {"chats": 0, "sent": 0, "refused": 0}
    if not os.getenv("TELEGRAM_BOT_TOKEN", ""):
        logger.info("[monday plan] no Telegram bot token: the plan went to "
                    "the bell only")
        return out
    button = (READ_WORDS, PAGE_PATH)
    told = list(lines)
    if button_markup(button) is None:
        # No address a phone can open (no DOMAIN): the words stand in.
        told.append(WHERE_WORDS)
    for user in recipients():
        prefs = getattr(user, "notification_prefs", None)
        chat = str(getattr(prefs, "telegram_chat_id", "") or "").strip()
        if not chat:
            continue
        out["chats"] += 1
        if send_to_chat(chat, title, lines=told, mark=MARK, button=button):
            out["sent"] += 1
        else:
            out["refused"] += 1
            logger.warning("[monday plan] Telegram did not take the plan for "
                           "chat %s (the line before says why)", chat)
    if not out["chats"]:
        logger.info("[monday plan] no staff Telegram chat is configured: "
                    "the plan went to the bell only")
    return out


def announce(plan_text, week) -> dict:
    """A new plan: the bell for every active user, then the staff group on
    Telegram. {"bell": rows, "telegram": {chats, sent, refused}}. An empty
    answer from the model is not announced (the warning says so)."""
    from alerts.models import Notification
    nothing = {"bell": 0, "telegram": {"chats": 0, "sent": 0, "refused": 0}}
    if not str(plan_text or "").strip():
        logger.warning("[monday plan] the model returned an empty plan for "
                       "the week of %s: nothing announced", week)
        return nothing
    prose, _calls = split_plan(plan_text)
    lines = summary_lines(prose)
    title = title_for(week)
    bell = Notification.create_for_all(
        notification_type="system", title=title,
        body=notification_body(lines), url=PAGE_PATH,
        data={"items": [{
            "label": READ_WORDS,
            "detail": "Week of %s, on the Strategist Briefing page"
                      % week_words(week),
            "url": PAGE_PATH}]},
    )
    try:
        told = telegram_to_staff(title, lines)
    except Exception:  # noqa: BLE001 — Telegram never costs the bell
        logger.exception("[monday plan] the Telegram message could not be "
                         "sent")
        told = dict(nothing["telegram"], failed=True)
    return {"bell": bell, "telegram": told}
