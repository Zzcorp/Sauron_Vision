"""Phase-20 bot notification dispatcher.

A thin orchestration layer that takes a (user, kind, title, body) tuple,
checks the user's preferences, and fans out to:
  - in-app `Notification` row (always, when prefs allow)
  - configured external channels (telegram, email, discord) — gracefully
    degrades when credentials missing

Hook points:
  - `gate_new_entry` reject   → "orchestrator_reject"
  - bot opens a position      → "bot_fill_open"
  - bot closes a position     → "bot_fill_close"
  - daily-loss limit reached  → "drawdown_warning"
  - operator presses TAKE TRADE → "manual_fill_open"

The last one is not a bot event and the dispatcher treats it as its own
population — see OPERATOR_KINDS, which exists because routing it through
the bot path told the operator that the trade they had just taken by hand
was automation, and then silenced it for anyone who had muted the bots.

All hooks are wrapped in try/except so a notification failure never breaks
trading logic.
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


# All bot-event kinds — things the PROGRAM did on its own. Adding new ones
# requires no schema change: they map to `Notification.notification_type="bot"`
# and are gated by the single `UserNotificationPrefs.receive_bot_alerts` flag
# (the briefing is the one exception, with its own opt-in toggle below).
BOT_KINDS = {
    "orchestrator_reject",
    "bot_fill_open",
    "bot_fill_close",
    "drawdown_warning",
    "bot_error",
    "track_record_decay",
    # Phase-43 — daily Sauron's Mind strategist briefing push.
    "strategist_briefing",
    # Phase-46 — operational health alerts (brain failures, critic miscalibration).
    "system_health",
}


#: The fill messages' marks (2026-09-27). An open says its side: green
#: bought, red sold short (a hand-taken open keeps the hand,
#: NOTIFY_MARKS["manual_fill_open"]). A close says its RESULT: a gain, a
#: loss, or nothing (zero, or a result nobody could price); how it ended
#: is a line of its own, in words (position_summary.ending_words).
OPEN_MARKS = {"long": "\U0001F7E2", "short": "\U0001F534"}
CLOSE_MARKS = {"gain": "\u2705", "loss": "\U0001F53B", "flat": "\u26AA"}

#: The emoji every other notifier leads its Telegram message with
#: (2026-09-26), reusing a mark where the event is the same: the hand of
#: a hand-taken close for a hand-taken open, the warning sign the Eye and
#: the digest already use. The bell keeps the platform's geometric mark
#: in the title (_plain_title strips it on the way out); Telegram gets
#: this one.
NOTIFY_MARKS = {
    "orchestrator_reject": "\u26D4",
    "manual_fill_open": "\u270B",
    "manual_fill_queued": "\u23F3",
    "manual_lane_live": "\U0001F534",
    "manual_lane_paper": "\U0001F4C4",
    "manual_close_refused": "\U0001F6AB",
    "drawdown_warning": "\u23F8\uFE0F",
    "protection_vanished": "\u26A0\uFE0F",
    "unclaimed_position": "\u2753",
    "track_record_decay": "\u2198\uFE0F",
    "strategist_briefing": "\U0001F9ED",
    "system_health": "\U0001F6E0\uFE0F",
    "staff_warning": "\u26A0\uFE0F",
    "broker_unreachable": "\U0001F50C",
    "evidence_chain_cold": "\u2744\uFE0F",
}


def _staff_mark(title) -> str:
    """notify_staff's mark. A caller that opens its title with \u26A0 (a
    queued order that cannot be withdrawn, a leg that may still be live)
    keeps a warning sign on Telegram, where the \u26A0 itself is stripped with
    the platform's marks; any other health alert gets the tools."""
    if str(title or "").lstrip().startswith("\u26A0"):
        return NOTIFY_MARKS["staff_warning"]
    return NOTIFY_MARKS["system_health"]

#: The decay triggers in words.
DECAY_WORDS = {
    "avg_r_drop": "average R dropped",
    "win_rate_drop": "win rate dropped",
    "gone_negative": "average R turned negative",
}


# ── The words a person reads (2026-09-27) ────────────────────────────────
# The operator, 2026-09-27: "the telegram messages are still basic still".
# The fills read like a log line ("FOREX · qty 7900.00000000 @
# 1.60725571", "Rule golden_cross") and the father reads them on a phone
# for three weeks. ONE place decides how a number reads in a sent text,
# on the position page's own formatters (dashboard.position_summary) and
# the platform's price convention (core.price_format), so the phone and
# the page never print one figure two ways:
#   money      "1,234.56 USD", "+17.38 USD", "−45.79 USD": a true minus
#              sign, and a figure that rounds to zero is never signed
#   price      the instrument's own decimals: 1.60726, 148.325, 227.53
#   quantity   no trailing zeros, grouped: 7,900 / 0.0002
#   percent    one decimal; under 1% two, which one would halve (0.15%)
#   duration   in words: "3 days 4 hours" (position_summary.duration_words)
# An unknown is "" and the line that needed it is left out: never
# "None", never "Decimal(...)", never eight decimals.

#: The minus sign a loss is printed with.
MINUS = "\u2212"

#: The attack mode's tiers (asset_engine/base.py) in words.
TIER_WORDS = {
    "HIGH": "high conviction",
    "STRONG": "strong conviction",
    "STANDARD": "standard conviction",
}


def _number(value):
    """A finite float, or None for anything that is not one."""
    from dashboard.position_summary import _num
    n = _num(value)
    if n is None or n in (float("inf"), float("-inf")):
        return None
    return n


def money_words(value, ccy="", *, signed=False) -> str:
    """"1,234.56 USD"; signed, "+17.38 USD" or "−45.79 USD"; "" when the
    value is not a number. A figure that rounds to zero reads "0.00",
    never "+0.00" or "−0.00"."""
    from dashboard.position_summary import money
    n = _number(value)
    if n is None:
        return ""
    if round(n, 2) == 0:
        n, signed = 0.0, False
    return money(n, str(ccy or "").strip(), signed=signed).replace("-", MINUS)


def price_words(value, asset_class="", symbol="") -> str:
    """A price at the instrument's own decimals (core.price_format), or ""."""
    from core.price_format import format_price
    if _number(value) is None:
        return ""
    return format_price(value, asset_class, symbol, dash="")


def qty_words(value) -> str:
    """A quantity without trailing zeros, grouped ("7,900", "0.0002"), or ""."""
    from dashboard.position_summary import quantity
    if _number(value) is None:
        return ""
    return quantity(value)


def pct_words(value) -> str:
    """"5.0%"; under 1% two decimals ("0.15%"); "" when not a number."""
    n = _number(value)
    if n is None:
        return ""
    text = ("{:.2f}%" if 0 < abs(n) < 1 else "{:.1f}%").format(n)
    return text.replace("-", MINUS)


def price_pair_words(first, second, asset_class="", symbol="") -> tuple:
    """Two prices at the instrument's decimals, with as many more decimals
    as it takes (up to seven) when those would print two different prices
    as one: "220.704" and "220.700", never "220.70" twice."""
    one = price_words(first, asset_class, symbol)
    two = price_words(second, asset_class, symbol)
    a, b = _number(first), _number(second)
    if not (one and two) or one != two or a == b:
        return one, two
    from decimal import Decimal
    shown = len(one.split(".", 1)[1]) if "." in one else 0
    for places in range(shown + 1, 8):
        wa = "{:.{p}f}".format(Decimal(str(a)), p=places)
        wb = "{:.{p}f}".format(Decimal(str(b)), p=places)
        if wa != wb:
            return wa, wb
    return one, two


def units_words(qty, asset_class="") -> str:
    """"7,900 units", "1 share", "2 contracts", or ""."""
    from dashboard.position_summary import _units
    amount = qty_words(qty)
    if not amount:
        return ""
    word = _units(asset_class)
    if abs(_number(qty)) == 1:
        word = word[:-1]
    return f"{amount} {word}"


def _telegram_lines(items):
    """The bell card's items as Telegram lines. A string (a
    TelegramHeading too) passes as it is; a {label, detail} dict, the
    shape the briefing hands the bell, reads "Label: detail" (an all-caps
    label in sentence case), where Telegram printed the dict's repr until
    2026-09-26."""
    if not items:
        return items
    out = []
    for it in items:
        if isinstance(it, dict):
            label = str(it.get("label") or "").strip()
            detail = str(it.get("detail") or "").strip()
            if label.isupper() and all(ch.isalnum() or ch == " "
                                       for ch in label):
                label = label.capitalize()
            words = (f"{label}: {detail}" if label and detail
                     else (label or detail))
            if words:
                out.append(words)
        else:
            out.append(it)
    return out


# Kinds the OPERATOR caused with their own hands. They ride this same
# dispatcher — one bell, one set of channels, one quiet-hours rule — but they
# are not bot events, and the two differences that follow from that are the
# whole reason the set is separate:
#
#   * `receive_bot_alerts` does NOT gate them. That switch answers "tell me
#     when the program acts on its own"; an operator who turns it off is
#     silencing the bots, not asking to stop hearing about the trades they
#     take themselves. Gating these on it meant the fills an operator most
#     wants confirmed were the first ones to go quiet.
#   * the in-app row is not typed "bot" (see _ROW_TYPE), so the bell stops
#     filing a deliberate click under "Bot Event".
OPERATOR_KINDS = {
    "manual_fill_open",
    # A position the BROKER holds that no row claims. Operator-side
    # deliberately: it is not the bot reporting what it did, it is the
    # platform admitting to something it did not know about, and there
    # is no "stop telling me" preference that should silence it.
    "unclaimed_position",
    # The manual lane changed venue — armed live or stood down. The
    # operator did it themselves, PIN in hand, and the record of WHEN a
    # chart button started being able to move real funds must never be
    # gated behind a bot-chatter preference.
    "manual_lane_mode",
    # A live position whose broker-side stop is GONE while the position is
    # still held. Operator-side because it is the one message that says
    # real money is running without a stop; a muted bot feed must not
    # mute it.
    "protection_vanished",
}

# The in-app row's type, per kind — "bot" for everything not listed, because
# every BOT_KINDS row IS the program acting.
#
# `alerts.Notification.TYPES` carries no "manual" member and adding one is a
# migration in another app, so a hand-taken fill files under "portfolio": the
# existing type for "something happened on your book". It is true of the
# event, it already has an inbox tab and a colour in the bell, and it is not
# the word "bot" — which is the claim that was wrong.
_ROW_TYPE = {kind: "portfolio" for kind in OPERATOR_KINDS}
# The daily briefing is neither a bot event nor a portfolio alert — it is
# the one row the operator reads rather than reacts to, and it dresses
# accordingly (ni-briefing in sauron.css).
_ROW_TYPE["strategist_briefing"] = "briefing"

# Rows whose event already drew a richer live banner straight from its
# producer (fill_open/fill_close on /ws/eye/). The row is still pushed so the
# bell badge moves live; the client just draws no second card. manual_trade
# pushes the same fill_open the engine does, so a hand-taken open belongs
# here for the same reason a bot's does.
_BANNER_SILENT_KINDS = {"bot_fill_open", "bot_fill_close", "manual_fill_open"}


def dispatch_notification(user, kind: str, *, title: str, body: str = "",
                          url: str = "", payload=None,
                          row_data=None, telegram=None) -> bool:
    """Send a bot-event or operator-event notification to `user`.

    Returns True if at least one delivery channel succeeded (including in-app).
    Returns False if the user has the relevant alerts disabled OR all channels
    failed.

    Phase-45: `payload` is an optional kind-specific object (e.g. a
    `StrategistBriefing` row) used by channels that render structured
    templates (HTML email). Plain channels fall back to the title+body
    pair so callers don't need to know which channel is in use.

    `telegram` (2026-09-27) is a notifier's own Telegram message, written
    for people: {"title", "mark", "subtitle", "summary", "lines",
    "details", "button"} (see _telegram_text). The bell row is built from
    title, body, url and row_data exactly as before; only the Telegram
    channel reads it.
    """
    if kind not in BOT_KINDS and kind not in OPERATOR_KINDS:
        logger.warning("dispatch_notification: unknown kind=%r", kind)
        return False

    # Only the bot's own events answer to the bot preferences. An operator
    # kind passes untouched — there is no preference for "stop telling me
    # what I did", and reading the bot switch here is what made a muted
    # fleet also mute the operator's own fills.
    if kind in BOT_KINDS:
        # Phase-43 — briefings have their own pref toggle (opt-in, default OFF).
        wanted = (_user_wants_briefing(user)
                  if kind == "strategist_briefing"
                  else _user_wants_bot_alerts(user))
        if not wanted:
            return False

    delivered = False

    # ── In-app row (bell dropdown) — ALWAYS created, even in quiet hours ──
    # The user can still see the row when they open the bell; we just
    # don't buzz an external channel while they're sleeping.
    try:
        from alerts.models import Notification
        n = Notification(
            user=user, notification_type=_ROW_TYPE.get(kind, "bot"),
            title=title[:200], body=body, url=url[:200],
        )
        if isinstance(row_data, dict) and row_data:
            # Structured facts for the dwell card (rides as json_script,
            # server-escaped) — the card renders data["items"] as lines
            # and a posture chip from data["briefing"].
            n.data = row_data
        n._banner_silent = kind in _BANNER_SILENT_KINDS
        n.save()
        delivered = True
    except Exception as e:
        logger.warning("dispatch_notification: in-app log failed: %s", e)

    # ── Phase-44 quiet hours — block external dispatch only ─────────
    if _in_quiet_hours(user):
        logger.info("dispatch_notification: quiet hours active for user=%s; "
                    "in-app row created, external channels muted",
                    getattr(user, "id", "?"))
        return delivered

    # ── External channels ───────────────────────────────────────────
    channel = _user_channel(user)
    if channel == "telegram":
        # The structured facts (row_data["items"], the bell card's own
        # lines) and the notifier's emoji ride to Telegram when a
        # notifier hands them over; a plain call keeps its shape.
        rd = row_data if isinstance(row_data, dict) else {}
        tg = telegram if isinstance(telegram, dict) else {}
        if tg.get("title"):
            # A message written for people (the fills, 2026-09-27): its
            # own title in words, a sentence, the facts, the folded record
            # and a button. The bell above kept its row.
            delivered = _send_telegram(
                user, str(tg["title"]), "",
                lines=tg.get("lines") or None,
                mark=str(tg.get("mark") or ""),
                subtitle=str(tg.get("subtitle") or ""),
                summary=str(tg.get("summary") or ""),
                details=tg.get("details") or None,
                button=tg.get("button")) or delivered
        elif rd.get("items") or rd.get("mark"):
            delivered = _send_telegram(
                user, title, body, lines=_telegram_lines(rd.get("items")),
                mark=str(rd.get("mark") or "")) or delivered
        else:
            delivered = _send_telegram(user, title, body) or delivered
    elif channel == "email":
        # Phase-45 — when delivering a briefing via email, render the
        # Sauron-themed HTML template instead of a plain-text dump.
        if kind == "strategist_briefing" and payload is not None:
            delivered = _send_briefing_email(user, payload) or delivered
        else:
            delivered = _send_email(user, title, body) or delivered
    elif channel == "discord":
        delivered = _send_discord(user, title, body) or delivered
    # "none" → skip external; in-app row already created.

    return delivered


# ── Preference resolution ────────────────────────────────────────────────

def _user_wants_bot_alerts(user) -> bool:
    """Default ON. False only when the user has explicitly disabled bot alerts."""
    try:
        prefs = user.notification_prefs  # alerts.UserNotificationPrefs
        return bool(getattr(prefs, "receive_bot_alerts", True))
    except Exception:
        return True


def _user_wants_briefing(user) -> bool:
    """Default OFF — daily push must be explicitly opted into."""
    try:
        prefs = user.notification_prefs
        return bool(getattr(prefs, "receive_strategist_briefing", False))
    except Exception:
        return False


def _in_quiet_hours(user, *, now=None) -> bool:
    """Phase-44 — return True if the current UTC time falls within the user's
    `quiet_start..quiet_end` window. Handles midnight wraparound:

        start=22:00, end=07:00  → quiet across midnight
        start=09:00, end=17:00  → quiet during the day
        start==end OR either None → no quiet hours configured (always False)

    Assumes both fields are stored in UTC (matches the existing model
    convention — TimeField with no TZ info, daily push is UTC-based).
    """
    try:
        prefs = user.notification_prefs
    except Exception:
        return False
    start = getattr(prefs, "quiet_start", None)
    end = getattr(prefs, "quiet_end", None)
    if start is None or end is None or start == end:
        return False

    from datetime import datetime
    from django.utils import timezone as tz
    if now is None:
        now = tz.now()
    # Compare as time-of-day in UTC.
    t = now.time()

    if start < end:
        # Same-day window: quiet if start ≤ t < end
        return start <= t < end
    else:
        # Wraps midnight: quiet if t ≥ start OR t < end
        return t >= start or t < end


def _user_channel(user) -> str:
    """Read TraderProfile.notify_channel ∈ {telegram, email, discord, none}.
    Defaults to 'none' if profile missing."""
    try:
        return getattr(user.trader_profile, "notify_channel", "none") or "none"
    except Exception:
        return "none"


# ── External channel adapters ────────────────────────────────────────────

# Titles lead with the platform's own geometric mark, which the bell renders
# in the fonts this app ships. Telegram, mail and Discord draw the same title
# in whatever font the reader's client happens to have, where a geometric mark
# is a coin-flip between the glyph and a tofu box on someone's phone. Every
# title already states its event in words ("Close refused: BTCUSDT"), so the
# mark is dropped on the way out rather than gambling on a foreign font stack.
# ▸ is the platform's mark for the operator speaking rather than the Eye
# answering (brain.research_models draws the two apart the same way), so it
# leads a hand-taken fill — and it is stripped on the way out with all the
# others.
# ◆ ◇ (the manual lane) and ⚠ (an unprotected position) lead titles
# too, and reached Telegram in front of its emoji until 2026-09-26.
_PLATFORM_MARKS = "✕▲⊠⊟⟳◉⊕◯◌●▸◆◇⚠" + "\uFE0F"


def _plain_title(title: str) -> str:
    """Strip the leading platform mark — external clients get words only."""
    return title.lstrip(_PLATFORM_MARKS).lstrip() or title


class TelegramHeading(str):
    """A section header inside a Telegram message: rendered bold.

    A plain str subclass, so whatever joins, measures or logs the lines
    keeps working and only _telegram_text reads the difference. Added
    2026-09-26 for bot_program/telegram_eye.py, whose status report has
    sections; every notifier before it hands plain strings and renders
    exactly as it did.
    """


def _detail_html(item) -> str:
    """One folded detail: a string, escaped; a (label, key) pair as
    "Label: <code>key</code>" -- the one place a raw key (a rule's) may
    stand in a sent text, set as code so it reads as a key."""
    from html import escape
    if isinstance(item, (tuple, list)) and len(item) == 2:
        label, key = (" ".join(str(x or "").split()) for x in item)
        if not key:
            return ""
        code = f"<code>{escape(key)}</code>"
        return f"{escape(label)}: {code}" if label else code
    return escape(" ".join(str(item or "").split()))


def _telegram_text(title: str, body: str = "", *, lines=None,
                   mark: str = "", subtitle: str = "", summary: str = "",
                   details=None) -> str:
    """The HTML Telegram renders: a bold title, then one fact per line.

    HTML parse mode with every field escaped, because the legacy
    Markdown mode this sent until 2026-09-26 read every underscore as
    italics: a body carrying `golden_cross`, `stopped_out` or
    `hit_target` — every bot open and every bot close — came back 400
    "can't parse entities" and was dropped without a log line, while a
    hand-taken fill (no rule name, no outcome word) went through. That
    is how "the trades the machine takes and closes never reach
    Telegram" looked from the operator's phone. `lines` are the
    structured facts a notifier hands over (row_data["items"], the
    same lines the bell's dwell card shows) and replace `body`; `mark`
    is a plain emoji for the Telegram client — the bell keeps the
    platform's geometric mark, which _plain_title strips on the way
    out.

    A MESSAGE WRITTEN FOR PEOPLE (2026-09-27), for a notifier that opts
    in: `subtitle` is one italic line under the title (whose money it
    is: "Simulated", "Real money · eToro"), `summary` ONE plain
    sentence; the facts follow after a blank line; `details` fold into
    Telegram's expandable blockquote (the technical record: the trade
    number, the rule's key, the config), each a string or a (label, key)
    pair whose key is set as code. A caller that passes none of the
    three renders exactly as before: the Eye's replies, the digest, and
    every message that has not opted in.
    """
    from html import escape
    head = escape(_plain_title(title))
    if mark:
        head = f"{mark} {head}"
    out = [f"<b>{head}</b>"]
    lead = []
    sub = " ".join(str(subtitle or "").split())
    if sub:
        lead.append(f"<i>{escape(sub)}</i>")
    said = " ".join(str(summary or "").split())
    if said:
        lead.append(escape(said))
    out.extend(lead)
    if lines:
        facts = [(f"<b>{escape(str(ln))}</b>"
                  if isinstance(ln, TelegramHeading)
                  else escape(str(ln)))
                 for ln in lines if str(ln or "").strip()]
        if lead and facts:
            out.append("")
        out.extend(facts)
    elif body:
        out.append("")
        out.append(escape(str(body)))
    folded = [text for text in (_detail_html(d) for d in (details or ()))
              if text]
    if folded:
        out.append("<blockquote expandable>" + "\n".join(folded)
                   + "</blockquote>")
    return "\n".join(out)


def _send_telegram(user, title: str, body: str, *, lines=None,
                   mark: str = "", subtitle: str = "", summary: str = "",
                   details=None, button=None) -> bool:
    """Send via the platform Telegram bot to the user's chat_id.

    Requires `TELEGRAM_BOT_TOKEN` env var (platform-wide) and the user's
    `UserNotificationPrefs.telegram_chat_id` (per-user). HTML, escaped
    (_telegram_text). An answer that is not OK is LOGGED with
    Telegram's own words at WARNING — until 2026-09-26 it vanished into
    a bare False, which is why a month of refused bot fills left no
    trace anywhere.

    `subtitle`, `summary` and `details` render as _telegram_text says
    (2026-09-27). `button` is (label, platform path): ONE inline URL
    button under the message (telegram_alert.button_markup), only when
    the deployment names a host a phone can open; when Telegram refuses
    the BUTTON, the message goes again without it, its page as a line
    (message_parts, post_message). Never a callback button: nothing is
    done from Telegram but the Eye's commands.
    """
    try:
        import os
        token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        if not token:
            return False
        chat_id = getattr(user.notification_prefs, "telegram_chat_id", "")
        if not chat_id:
            return False
        # Cut under Telegram's 4,096 characters like every other path:
        # fit_text renders through _telegram_text and returns it as it is
        # whenever it fits (2026-09-26). The button is not text.
        from alerts.channels.telegram_alert import (message_parts,
                                                    post_message)
        text, markup, fallback = message_parts(
            title, body, lines=lines, mark=mark, subtitle=subtitle,
            summary=summary, details=details, button=button)
        r, refused = post_message(
            token, {"chat_id": chat_id, "text": text, "parse_mode": "HTML",
                    "disable_web_page_preview": True},
            timeout=5, markup=markup, fallback_text=fallback)
        if refused is not None:
            logger.warning("telegram refused the button (%s) %r: %s; sent "
                           "again without it",
                           getattr(refused, "status_code", "?"),
                           _plain_title(title),
                           str(getattr(refused, "text", ""))[:200])
        if not r.ok:
            logger.warning("telegram refused (%s) %r: %s",
                           getattr(r, "status_code", "?"),
                           _plain_title(title),
                           str(getattr(r, "text", ""))[:200])
        return bool(r.ok)
    except Exception as e:
        # A connection error quotes the address, and the address carries
        # the bot token: scrubbed before the line is logged (2026-09-26),
        # as alerts.channels.telegram_alert.send_to_chat does.
        import os as _os
        token = _os.getenv("TELEGRAM_BOT_TOKEN", "")
        words = str(e).replace(token, "<token>") if token else str(e)
        logger.warning("telegram dispatch failed: %s", words[:300])
        return False


def _send_email(user, title: str, body: str) -> bool:
    """Send via Django's email backend to user.email."""
    try:
        if not user.email:
            return False
        from alerts.channels.email_alert import send_email_alert
        return send_email_alert(user.email, _plain_title(title), body)
    except Exception as e:
        logger.warning("email dispatch failed: %s", e)
        return False


def _send_briefing_email(user, briefing) -> bool:
    """Phase-45 — Sauron-themed HTML briefing email.

    Falls back to the plain `_send_email` path on any failure so the user
    still gets the morning push even if the template breaks.
    """
    try:
        if not getattr(user, "email", ""):
            return False
        from alerts.channels.briefing_email import send_briefing_email
        return send_briefing_email(user.email, briefing)
    except Exception as e:
        logger.warning("briefing email dispatch failed: %s", e)
        return False


def _send_discord(user, title: str, body: str) -> bool:
    """POST to user-configured Discord webhook (TraderProfile or env fallback)."""
    try:
        import os, requests
        url = (
            getattr(user.trader_profile, "discord_webhook_url", "")
            or os.getenv("DISCORD_WEBHOOK_URL", "")
        )
        if not url:
            return False
        plain = _plain_title(title)
        content = f"**{plain}**\n{body}" if body else f"**{plain}**"
        r = requests.post(url, json={"content": content[:1900]}, timeout=5)
        return r.ok
    except Exception as e:
        logger.warning("discord dispatch failed: %s", e)
        return False


# ── Convenience helpers used by the hook points ─────────────────────────

def notify_orchestrator_reject(user, *, asset_class: str, symbol: str,
                                side: str, reason: str) -> bool:
    return dispatch_notification(
        user, "orchestrator_reject",
        title=f"✕ Orchestrator blocked {symbol} {side}",
        body=f"{asset_class.upper()} · {reason}",
        url="/eye/",
        row_data={"items": [f"Asset class: {asset_class.upper()}",
                            f"Reason: {reason}"],
                  "mark": NOTIFY_MARKS["orchestrator_reject"]},
    )


# ── The fill messages, written for people (2026-09-27) ───────────────────
# Each builder returns the Telegram message a fill sends: {"title",
# "mark", "subtitle", "summary", "lines", "details", "button"}. The facts
# come from the ROW (the caller's own, else the one trade_id names), read
# the way the position page reads them (dashboard.position_summary: the
# venue from the row's own stamps, the risk at the stop the trade opened
# with, the rule and the ending in words), so the phone and the page
# agree. Without a row a fill still reads in words, from the arguments.

def _fill_row(trade, trade_id):
    """The AssetBotTrade a fill is about: the caller's own row, else the
    one `trade_id` names, else None. A row that cannot be read costs the
    message some words (the levels, the venue), never the message."""
    if trade is not None:
        return trade
    if trade_id in (None, ""):
        return None
    try:
        from bot_program.models import AssetBotTrade
        return (AssetBotTrade.objects.select_related("config")
                .filter(pk=trade_id).first())
    except Exception as e:  # noqa: BLE001
        logger.debug("fill message: trade #%s unreadable: %s", trade_id, e)
        return None


def _is_long(side) -> bool:
    return str(side or "").strip().upper() not in ("SELL", "SHORT")


def _row_ccy(row) -> str:
    """The account currency a row's money is in, as the position page
    reads it; "" without a row (a figure is then printed bare)."""
    if row is None:
        return ""
    try:
        return (str(getattr(row.config, "base_currency", "") or "").strip()
                or "USD")
    except Exception:  # noqa: BLE001
        return "USD"


def _venue_line(row, live=None) -> str:
    """"Simulated", "Simulated · eToro demo" or "Real money · eToro": the
    row's own stamps as the position page reads them (venue_of). Without
    a row only "not live" is certain ("Simulated"): a live config can
    place on an eToro DEMO account, which the page calls Simulated, so a
    live caller without a row says nothing rather than "Real money"."""
    if row is not None:
        from dashboard.position_summary import venue_of
        money_text, _real, broker = venue_of(row)
        if broker == "Paper trading":
            return money_text
        if broker == "Broker not recorded":
            broker = "broker not recorded"
        return f"{money_text} · {broker}"
    return "Simulated" if live is not None and not live else ""


def _level_line(label, level, entry, asset_class, symbol,
                held_by="") -> str:
    """"Stop: 1.52689 (5.0% below)", "Target: 1.76798 (10.0% above)";
    "Stop: 1.14000 at eToro (3.1% below)" for a stop the venue holds at a
    level of its own; "Stop: not set". The distance is from `entry`; none
    without one."""
    lv, at = _number(level), _number(entry)
    if lv is None or lv <= 0:
        return f"{label}: not set"
    words = price_words(level, asset_class, symbol)
    if held_by:
        words += f" at {held_by}"
    if at is not None and at > 0 and lv != at:
        where = "below" if lv < at else "above"
        return (f"{label}: {words} "
                f"({pct_words(abs(lv - at) / at * 100)} {where})")
    return f"{label}: {words}"


def _about(value, ccy) -> str:
    """"about 9,269 USD" (whole units from 100 up), or ""."""
    n = _number(value)
    if n is None or n <= 0 or not ccy:
        return ""
    text = "{:,.0f}".format(n) if n >= 100 else "{:,.2f}".format(n)
    return f"about {text} {ccy}"


def _size_sentence(row, qty, price, asset_class, symbol, ccy) -> str:
    """"7,900 units at 1.60726 — about 9,269 USD" (the notional as the
    position page computes it, in the currency it is really in)."""
    said = units_words(qty, asset_class)
    at = price_words(price, asset_class, symbol)
    if at:
        said = f"{said} at {at}" if said else f"At {at}"
    q, p = _number(qty), _number(price)
    if row is not None and said and q and p:
        from dashboard.position_summary import _unconverted_ccy
        from portfolio.services import value_per_unit
        about = _about(abs(q) * p * value_per_unit(row),
                       _unconverted_ccy(row, ccy) or ccy)
        if about:
            said += f" — {about}"
    return said


def _held_stop(row):
    """The stop the venue HOLDS when it rewrote the one sent at the fill
    (metadata "stop_rewritten_by_venue" {sent, held}: AssetBot.execute_
    entry, _finish_working_entry, and the hand lane): the held level, 0.0
    for eToro's "no stop" (at or under 0.0001), or None when the venue
    kept the stop sent. The row's stop_loss stays the SENT stop (the risk
    denominator must not move), and a row the venue protects skips every
    bot-side stop check, so the held stop is the only one that can be hit."""
    moved = (getattr(row, "metadata", None) or {}).get(
        "stop_rewritten_by_venue")
    if not isinstance(moved, dict):
        return None
    held = _number(moved.get("held"))
    if held is None:
        return None
    return held if held > 0.0001 else 0.0


def _open_levels(row, asset_class, symbol, entry, ccy, *,
                 distance=True, long_=True) -> list:
    """The stop, the target, and the risk at the stop (manual_close.
    _risk_dollars: the close dialog's and the page's 1R), from the row; []
    without one.

    A stop the venue rewrote at the fill is the one that can be hit
    (_held_stop): the Stop line names the HELD level, the risk is measured
    at it and says the planned figure beside it (2026-09-27), and a venue
    that holds no stop is an uncapped risk, never a number."""
    if row is None:
        return []
    at = entry if distance else None
    held = _held_stop(row) if distance else None
    if held is None:
        stop_line = _level_line("Stop", row.stop_loss, at, asset_class,
                                symbol)
    elif held > 0:
        stop_line = _level_line("Stop", held, at, asset_class, symbol,
                                held_by="eToro")
    else:
        stop_line = "Stop: none at eToro"
    lines = [stop_line,
             _level_line("Target", row.take_profit, at, asset_class, symbol)]
    try:
        from bot_program.manual_close import _initial_stop, _risk_dollars
        risk = _risk_dollars(row)
        planned = _initial_stop(row)
    except Exception:  # noqa: BLE001 — an unread risk is a missing line
        risk, planned = 0.0, None
    if held is not None:
        if held <= 0:
            lines.append("Risk: not capped, since eToro holds no stop")
            return lines
        e, p = _number(row.entry_price), _number(planned)
        if risk > 0 and e and p and e != p:
            loss = (e - held) if long_ else (held - e)
            if loss <= 0:
                lines.append("Risk if the stop is hit: none, since eToro "
                             "holds the stop past the entry")
            else:
                lines.append(
                    "Risk if the stop is hit: "
                    f"{money_words(risk * loss / abs(e - p), ccy)}, not the "
                    f"{money_words(risk, ccy)} planned")
        return lines
    if risk > 0 and distance:
        lines.append(f"Risk if the stop is hit: {money_words(risk, ccy)}")
    elif (_number(row.stop_loss) or 0) <= 0:
        lines.append("Risk: not capped, since no stop is set")
    return lines


def _partial_line(row, qty, asset_class) -> str:
    """"Filled: 3 of the 20 shares ordered", for a fill short of its order."""
    meta = getattr(row, "metadata", None) or {}
    asked, got = _number(meta.get("qty_requested")), _number(qty)
    if asked and got and 0 < got < asked * 0.999:
        return (f"Filled: {qty_words(got)} of the "
                f"{units_words(asked, asset_class)} ordered")
    return ""


def _taken_line(row, meta) -> str:
    """How a hand-taken trade was taken: from which signal, or by hand."""
    from dashboard.position_summary import _signal_rule, rule_words
    sid = meta.get("signal_id")
    if sid:
        rule = rule_words(_signal_rule(sid))
        return (f"Taken: by hand, from signal #{sid}"
                + (f" ({rule})" if rule else ""))
    if row is not None:
        return "Taken: by hand, from the instrument page"
    return "Taken: by hand"


def _record(row, trade_id, rule_key="") -> list:
    """The folded technical record: the trade, the rule's key, the config."""
    out = []
    if trade_id:
        out.append(f"Trade: #{trade_id}")
    if rule_key:
        out.append(("Rule key", rule_key))
    name = ""
    if row is not None:
        try:
            name = str(row.config.name or "").strip()
        except Exception:  # noqa: BLE001
            name = ""
    if name:
        out.append(f"Config: {name}")
    return out


def _page_button(trade_id) -> tuple:
    """("Open position", the position page), or ("Open positions",
    "/positions/") when the trade has no page."""
    from alerts.links import page_url
    path = page_url("forensics_detail", trade_id) if trade_id else ""
    return (("Open position", path) if path
            else ("Open positions", "/positions/"))


def _bell_items(message) -> list:
    """The bell card's lines: whose money it is (the subtitle), the
    message's facts, then its record flat. A rule's key reads in words
    there ("Rule: Golden cross"), and not at all when a fact already names
    the rule ("Why: Golden cross"): the bell sets no key as code."""
    from dashboard.position_summary import rule_words
    out = [str(x) for x in [message.get("subtitle")]
           + list(message.get("lines") or ()) if str(x or "").strip()]
    for d in message.get("details") or ():
        if isinstance(d, (tuple, list)) and len(d) == 2:
            words = rule_words(str(d[1] or ""))
            if words and not any(words in ln for ln in out):
                out.append(f"Rule: {words}")
        elif str(d or "").strip():
            out.append(str(d))
    return out


def _rule_key(rule_name) -> tuple:
    """(the rule's key, the facts a caller still carries inside rule_name).

    Until 2026-09-27 the engine handed the attack mode and a moved stop
    as extra lines of rule_name; a caller that still does keeps working:
    the first line is the key, the others are facts."""
    first, *carried = str(rule_name or "").split("\n")
    key = first.strip()
    if key == "—":
        key = ""
    return key, [" ".join(c.split()) for c in carried if c.strip()]


def _built(build, **kwargs):
    """build(**kwargs), or None when it raises: a sentence never costs
    the bell row (the caller falls back to its plain body)."""
    try:
        return build(**kwargs)
    except Exception:  # noqa: BLE001
        logger.exception("the %s message could not be built",
                         getattr(build, "__name__", "fill"))
        return None


def fill_open_message(*, asset_class, symbol, side, qty, entry_price,
                      rule_name="", trade=None, trade_id=None, manual=False,
                      live=None, attack="", stop_moved="") -> dict:
    """The Telegram message of a fill that OPENED a position:

        🟢 Bought EURCAD                 (🔴 Sold short AAPL; ✋ … by hand)
        Simulated                        (Real money · eToro)
        7,900 units at 1.60726 — about 9,269 USD.

        Stop: 1.52689 (5.0% below)
        Target: 1.76798 (10.0% above)
        Risk if the stop is hit: 463.45 USD
        Why: Golden cross                (a hand-taken one: "Taken: …")
        Attack mode: …                   (when the row is attack mode)
        Stop moved by eToro: …           (when the venue rewrote it)
        ▸ Trade: #108 · Rule key: golden_cross · Config: FX trend
        [Open position]

    A waiting order that filled says so first; a fill short of its order
    says how much of it filled. `rule_name` is the rule's KEY (_rule_key
    reads the old multi-line shape too). A stop the venue rewrote is the
    one the Stop and risk lines read (_open_levels); a caller that hands
    no stop-moved line (the hand lane) gets the row's own
    (stop_moved_words)."""
    row = _fill_row(trade, trade_id)
    tid = getattr(row, "id", None) or trade_id
    meta = (getattr(row, "metadata", None) or {}) if row is not None else {}
    long_ = _is_long(side)
    rule_key, carried = _rule_key(rule_name)
    ccy = _row_ccy(row)
    if not stop_moved and not carried and meta.get("stop_rewritten_by_venue"):
        try:
            from bot_program.asset_engine.base import stop_moved_words
            stop_moved = stop_moved_words(meta, entry_price, asset_class,
                                          symbol)
        except Exception:  # noqa: BLE001 — the levels still say it
            stop_moved = ""

    title = f"Bought {symbol}" if long_ else f"Sold short {symbol}"
    if manual:
        title += " by hand"
        mark = NOTIFY_MARKS["manual_fill_open"]
    else:
        mark = OPEN_MARKS["long" if long_ else "short"]
    said = _size_sentence(row, qty, entry_price, asset_class, symbol, ccy)
    summary = f"{said}." if said else ""
    if summary and meta.get("entry_filled_at"):
        summary = "The waiting order filled: " + summary

    lines = []
    if row is not None:
        partial = _partial_line(row, qty, asset_class)
        if partial:
            lines.append(partial)
    lines.extend(_open_levels(row, asset_class, symbol, entry_price, ccy,
                              long_=long_))
    if manual:
        lines.append(_taken_line(row, meta))
    else:
        from dashboard.position_summary import rule_words
        sid = meta.get("signal_id")
        why = [w for w in (rule_words(rule_key),
                           f"signal #{sid}" if sid else "") if w]
        if why:
            lines.append("Why: " + " — ".join(why))
    for fact in [attack, stop_moved] + carried:
        fact = " ".join(str(fact or "").split())
        if fact:
            lines.append(fact)
    return {"title": title, "mark": mark,
            "subtitle": _venue_line(row, live), "summary": summary,
            "lines": lines,
            "details": _record(row, tid, "" if manual else rule_key),
            "button": _page_button(tid)}


def fill_queued_message(*, asset_class, symbol, side, qty, trade=None,
                        trade_id=None, live=False) -> dict:
    """A hand-placed order the broker took and filled NOTHING of (a market
    order outside regular hours queues for the next open): no price, no
    distance from a price nobody paid.

        ⏳ Waiting to buy AAPL
        Real money · eToro
        The broker has the order for 1 share; nothing has filled yet, so
        no position is open.
    """
    row = _fill_row(trade, trade_id)
    tid = getattr(row, "id", None) or trade_id
    meta = (getattr(row, "metadata", None) or {}) if row is not None else {}
    long_ = _is_long(side)
    size = units_words(qty, asset_class)
    lines = [_taken_line(row, meta)]
    lines.extend(_open_levels(row, asset_class, symbol, None,
                              _row_ccy(row), distance=False))
    # Without a row only "not live" is certain (_venue_line): a live config
    # can place on an eToro demo account.
    venue = _venue_line(row, live)
    return {"title": (f"Waiting to buy {symbol}" if long_
                      else f"Waiting to sell {symbol} short"),
            "mark": NOTIFY_MARKS["manual_fill_queued"],
            "subtitle": venue,
            "summary": ("The broker has the order"
                        + (f" for {size}" if size else "")
                        + "; nothing has filled yet, so no position is "
                          "open."),
            "lines": lines, "details": _record(row, tid),
            "button": _page_button(tid)}


def fill_close_message(*, asset_class, symbol, side, qty, exit_price, pnl,
                       outcome="", trade=None, trade_id=None) -> dict:
    """The Telegram message of a close:

        ✅ Closed EURCAD · +17.84 USD     (🔻 a loss, ⚪ zero or unknown)
        Sold 7,900 units at 1.61035 after 3 days 4 hours.

        Result: +17.84 USD · 0.04 times the risk
        How it ended: closed by hand     (position_summary.ending_words)
        Simulated                        (Real money · eToro)
        ▸ Trade · Rule key · Config · Entry price · Opened · Closed
        [Open position]

    A result of None is UNMEASURED (no exit price could be read) and is
    said so, never printed as a number."""
    from dashboard.position_summary import (_MANUAL_RULES, ENDINGS,
                                            duration_words, ending_words,
                                            utc_clock)
    row = _fill_row(trade, trade_id)
    tid = getattr(row, "id", None) or trade_id
    ccy = _row_ccy(row)
    n = _number(pnl)
    if n is None:
        mark, result = CLOSE_MARKS["flat"], "result unknown"
    else:
        n = round(n, 2)
        mark = CLOSE_MARKS["gain" if n > 0 else "loss" if n < 0 else "flat"]
        result = money_words(n, ccy, signed=True)

    said = ("Sold" if _is_long(side) else "Bought back")
    size = units_words(qty, asset_class)
    if size:
        said += f" {size}"
    exit_words = price_words(exit_price, asset_class, symbol)
    if exit_words:
        said += f" at {exit_words}"
    opened = getattr(row, "opened_at", None) if row is not None else None
    closed = getattr(row, "closed_at", None) if row is not None else None
    if opened and closed:
        said += f" after {duration_words((closed - opened).total_seconds())}"
    summary = said + "."
    if not exit_words:
        summary += " The exit price could not be read."

    if n is None:
        lines = ["Result: unknown, since the exit could not be priced"]
    else:
        r = (_number(getattr(row, "realized_r", None))
             if row is not None else None)
        r_words = ""
        if r is not None:
            # rounded first, as the money is: a result that reads 0.00
            # is never "a loss of 0.00 times the risk"
            r = round(r, 2) or 0.0
            r_words = ("{:.2f} times the risk".format(r) if r >= 0 else
                       "a loss of {:.2f} times the risk".format(abs(r)))
        lines = [f"Result: {result}" + (f" · {r_words}" if r_words else "")]
    ending = (ending_words(row) if row is not None
              else ENDINGS.get(str(outcome or ""), "Closed"))
    lines.append("How it ended: " + ending[:1].lower() + ending[1:])
    venue = _venue_line(row)
    if venue:
        lines.append(venue)

    rule_key = str(getattr(row, "rule_name", "") or "").strip()
    if rule_key.lower() in _MANUAL_RULES:
        rule_key = ""
    details = _record(row, tid, rule_key)
    if row is not None:
        entry = price_words(row.entry_price, asset_class, symbol)
        if entry:
            details.append(f"Entry price: {entry}")
        if opened:
            details.append(f"Opened: {utc_clock(opened, True)}")
        if closed:
            details.append(f"Closed: {utc_clock(closed, True)}")
    return {"title": f"Closed {symbol} · {result}", "mark": mark,
            "subtitle": "", "summary": summary, "lines": lines,
            "details": details, "button": _page_button(tid)}


def notify_bot_fill_open(user, *, asset_class: str, symbol: str, side: str,
                          qty, entry_price, rule_name: str = "",
                          trade_id=None, trade=None, attack: str = "",
                          stop_moved: str = "") -> bool:
    """A bot's entry filled. The bell row keeps its title, body and url;
    Telegram gets the message written for people (fill_open_message).
    `trade` is the row (else `trade_id` names it); `attack` and
    `stop_moved` are the engine's own facts (AssetBot._fill_words), their
    own arguments since 2026-09-27 rather than lines inside rule_name."""
    from alerts.links import page_url
    tid = trade_id or getattr(trade, "id", None)
    rule_key, carried = _rule_key(rule_name)
    body = (f"{asset_class.upper()} · qty {qty} @ {entry_price}"
            + (f" · {rule_key}" if rule_key else ""))
    message = _built(fill_open_message, asset_class=asset_class,
                     symbol=symbol, side=side, qty=qty,
                     entry_price=entry_price, rule_name=rule_name,
                     trade=trade, trade_id=tid, attack=attack,
                     stop_moved=stop_moved)
    # A message that could not be built still carries the engine's own
    # facts: the body names only the rule, and they no longer ride in it.
    plain = [body] + [" ".join(str(f or "").split())
                      for f in [attack, stop_moved] + carried
                      if str(f or "").strip()]
    return dispatch_notification(
        user, "bot_fill_open",
        title=f"◉ {symbol} {side} opened",
        body=body,
        # the bell card renders the message's facts and its record
        row_data=({"items": _bell_items(message),
                   "mark": message["mark"]} if message else
                  {"items": plain, "mark": OPEN_MARKS["long"]}),
        # The fill has a page: forensics carries the rule that fired, the
        # signals that voted and the gate decision behind THIS trade —
        # "why did it just buy that?", which is the question the banner
        # provokes. /asset-bots/ is the config list and answers none of it.
        url=page_url("forensics_detail", tid) or "/asset-bots/",
        telegram=message,
    )


def notify_manual_fill_open(user, *, asset_class: str, symbol: str, side: str,
                             qty, entry_price, trade_id=None,
                             live: bool = False, working: bool = False,
                             trade=None) -> bool:
    """The OPERATOR opened this position by hand — TAKE TRADE, not a bot.

    Same shape as `notify_bot_fill_open` minus `rule_name`, and the omission
    is the point: every hand-taken trade carries rule_name="manual_take", and
    printing it in the body where a bot fill prints "· rsi_reversal" makes
    the operator's own click look like a rule that fired. The title says "by
    hand" in words instead, so the attribution survives the external channels
    that strip the mark (see _plain_title).

    `live` marks the venue in both title and body: since the LIVE manual
    ticket exists, a fill notification that cannot say which venue the
    money moved on tells the operator half a fact.

    `working` is the case where the broker took the order and filled
    NOTHING (a market order sent outside regular hours queues for the next
    open). "Opened" would then be a claim about the future — and the price
    shown would be the pre-order quote, not a fill — so the message says
    queued instead, and names no price.

    Telegram gets the message written for people (2026-09-27): the side
    in words and "by hand" in the title, whose money it is under it
    (fill_open_message); a queued order says it is waiting and names no
    price (fill_queued_message). `trade` is the row (else `trade_id`).
    The bell row keeps its title, body and url.
    """
    from alerts.links import page_url
    tid = trade_id or getattr(trade, "id", None)
    if working:
        body = (f"{asset_class.upper()} · qty {qty} · TAKE TRADE · the "
                f"order is working and nothing has filled — no position "
                f"is open yet"
                + (" · LIVE — real funds once it fills" if live else ""))
        message = _built(fill_queued_message, asset_class=asset_class,
                         symbol=symbol, side=side, qty=qty, trade=trade,
                         trade_id=tid, live=live)
        return dispatch_notification(
            user, "manual_fill_open",
            title=(f"▸ {symbol} {side} QUEUED at the broker"
                   + (" · LIVE" if live else "")),
            body=body,
            row_data={"items": (_bell_items(message) if message
                                else [body]),
                      "mark": NOTIFY_MARKS["manual_fill_queued"]},
            url=page_url("forensics_detail", tid) or "/positions/",
            telegram=message,
        )
    body = (f"{asset_class.upper()} · qty {qty} @ {entry_price} · "
            f"TAKE TRADE"
            + (" · LIVE — real funds" if live else ""))
    message = _built(fill_open_message, asset_class=asset_class,
                     symbol=symbol, side=side, qty=qty,
                     entry_price=entry_price, trade=trade, trade_id=tid,
                     manual=True, live=live)
    return dispatch_notification(
        user, "manual_fill_open",
        title=(f"▸ {symbol} {side} opened by hand"
               + (" · LIVE" if live else "")),
        body=body,
        row_data={"items": (_bell_items(message) if message else [body]),
                  "mark": NOTIFY_MARKS["manual_fill_open"]},
        telegram=message,
        # Forensics renders any of this user's trades, and a hand-taken one
        # has a story too: the levels it opened with, the signal it was taken
        # from, its audit trail and lifecycle. The FALLBACK differs from the
        # bot's, though — /asset-bots/ is the fleet's config list, which is
        # not where a trade the operator took themselves lives. /positions/
        # is their own book, which is.
        url=page_url("forensics_detail", tid) or "/positions/",
    )


def notify_manual_lane_mode(user, *, asset_class: str, mode: str,
                            capital=None) -> bool:
    """The manual lane's venue changed — the operator armed it live or
    stood it down. A durable record, because the moment a LONG/SHORT
    button starts moving real funds is the single most consequential
    click this platform offers."""
    live = (mode == "live")
    return dispatch_notification(
        user, "manual_lane_mode",
        title=(f"◆ Manual lane ARMED LIVE — {asset_class}" if live
               else f"◇ Manual lane back to paper — {asset_class}"),
        body=((f"TAKE TRADE on {asset_class} instruments now moves REAL "
               f"funds at the broker"
               + (f" · pool ${float(capital):,.2f}" if capital else ""))
              if live else
              f"TAKE TRADE on {asset_class} instruments is back on the "
              f"paper venue — rehearsal money only"),
        url="/positions/",
        row_data=({"items": ([f"Asset class: {asset_class}",
                              "TAKE TRADE now moves real funds at the broker"]
                             + ([f"Pool: ${float(capital):,.2f}"]
                                if capital else [])),
                   "mark": NOTIFY_MARKS["manual_lane_live"]} if live else
                  {"items": [f"Asset class: {asset_class}",
                             "TAKE TRADE is back on the paper venue: "
                             "rehearsal money only"],
                   "mark": NOTIFY_MARKS["manual_lane_paper"]}),
    )


def notify_bot_fill_close(user, *, asset_class: str, symbol: str, side: str,
                           qty, exit_price, pnl, outcome: str = "",
                           trade_id=None, trade=None) -> bool:
    """A position closed. The bell row keeps its title, body and url;
    Telegram gets the message written for people (fill_close_message,
    2026-09-27): the result in the title, the closing side and how long
    it was held, how it ended in words. `trade` is the row (else
    `trade_id` names it)."""
    from alerts.links import page_url
    tid = trade_id or getattr(trade, "id", None)
    # ⊕ target struck · ⊟ cut at the stop · ◯ closed flat by anything else.
    icon = "⊕" if outcome == "hit_target" else (
        "⊟" if outcome == "stopped_out" else "◯")
    sign = "+" if (pnl is not None and pnl > 0) else ""
    # A P&L of None is UNMEASURED (no exit price could be read, the
    # reconciled close with no quote) — never printed as a number.
    pnl_words = f"{sign}{pnl}" if pnl is not None else "P&L unmeasured"
    body = (f"{asset_class.upper()} · qty {qty} @ {exit_price}"
            + (f" · {outcome}" if outcome else ""))
    message = _built(fill_close_message, asset_class=asset_class,
                     symbol=symbol, side=side, qty=qty,
                     exit_price=exit_price, pnl=pnl, outcome=outcome,
                     trade=trade, trade_id=tid)
    return dispatch_notification(
        user, "bot_fill_close",
        title=f"{icon} {symbol} {side} closed · {pnl_words}",
        body=body,
        row_data=({"items": _bell_items(message),
                   "mark": message["mark"]} if message else
                  {"items": [body], "mark": CLOSE_MARKS["flat"]}),
        # Same trade, same page — the close's own timeline, grade and R
        # multiple. /bot-performance/ aggregates every rule instead.
        url=page_url("forensics_detail", tid) or "/bot-performance/",
        telegram=message,
    )


def _plain_message(title, items, mark, *, summary="", button=None) -> dict:
    """A notifier's own facts (its bell items) opted into the message
    written for people (2026-09-27): one summary sentence above them and
    a button to the page they concern. The facts stay as they were."""
    return {"title": _plain_title(title), "mark": mark, "summary": summary,
            "lines": _telegram_lines(items), "button": button}


def notify_manual_close_refused(user, *, asset_class: str, symbol: str,
                                 trade_id=None) -> bool:
    """The operator pressed CLOSE on a live position and the platform
    refused because the broker is unreachable.

    Deliberately louder than the dialog that already said so: the dialog is
    dismissed in a second while the position stays live and unmanaged, and
    "I thought I closed that" is the most expensive belief in the system.
    Deduped per trade per hour so a frustrated operator clicking four times
    does not bury the rest of the bell.
    """
    from datetime import timedelta as _td
    from django.utils import timezone as _tz
    from alerts.links import page_url

    title = f"✕ Close refused: {symbol}"
    try:
        from alerts.models import Notification
        recent = Notification.objects.filter(
            user=user, notification_type="bot", title=title,
            created_at__gte=_tz.now() - _td(hours=1)).exists()
        if recent:
            return False
    except Exception as e:  # noqa: BLE001 — dedupe failure must not mute it
        logger.warning("close-refused dedupe failed: %s", e)

    page = page_url("forensics_detail", trade_id)
    items = [(f"{asset_class.upper()} · trade #{trade_id}" if trade_id
              else asset_class.upper()),
             "The broker is unreachable, so the close was refused",
             "The position is STILL OPEN at the broker"]
    return dispatch_notification(
        user, "bot_error", title=title,
        body=(f"{asset_class.upper()} trade #{trade_id} is LIVE and its "
              f"broker is unreachable, so the close was refused rather than "
              f"stamped on a position that is still open. The position is "
              f"STILL OPEN at the broker."),
        url=page or "/eye/fills/",
        row_data={"items": items,
                  "mark": NOTIFY_MARKS["manual_close_refused"]},
        telegram=_plain_message(
            title, items, NOTIFY_MARKS["manual_close_refused"],
            summary=(f"The broker could not be reached, so the close of "
                     f"{symbol} was refused and the position is still "
                     f"open."),
            button=(("Open position", page) if page
                    else ("Open positions", "/positions/"))),
    )


def notify_drawdown_warning(user, *, asset_class: str, config_name: str,
                             realized_pnl, limit, currency: str = "",
                             unpriced: int = 0) -> bool:
    """The daily loss limit halted a bot's entries. `currency` is the
    config's (2026-09-27): the amounts read "−200.00 USD". `unpriced` is
    the count of closes in the window nobody could price: the gate sums
    only the priced ones, so the loss is then AT LEAST the figure."""
    title = f"▲ Drawdown limit reached · {config_name}"
    try:
        unpriced = max(int(unpriced or 0), 0)
    except (TypeError, ValueError):
        unpriced = 0
    items = [f"Bot: {config_name}",
             f"Asset class: {asset_class.upper()}",
             "Realized 24h P&L: "
             + (money_words(realized_pnl, currency) or str(realized_pnl)),
             "Limit: " + (money_words(limit, currency) or str(limit)),
             "New entries halted"]
    if unpriced:
        # the priced closes only: the loss is at least the figure above
        items.insert(3, f"Closes that could not be priced: {unpriced}")
    lost, cap = _number(realized_pnl), _number(limit)
    if lost is not None and lost < 0 and cap is not None:
        closes = f"{unpriced} close{'' if unpriced == 1 else 's'}"
        summary = (f"{config_name} has lost "
                   + ("at least " if unpriced else "")
                   + f"{money_words(-lost, currency)} in the last 24 hours"
                   + (f" ({closes} could not be priced)" if unpriced else "")
                   + f", past its limit of {money_words(abs(cap), currency)}"
                   f", so it opens no new trades for now.")
    else:
        summary = (f"{config_name} has reached its daily loss limit, so it "
                   f"opens no new trades for now.")
    return dispatch_notification(
        user, "drawdown_warning",
        title=title,
        body=(f"{asset_class.upper()} · realized 24h P&L {realized_pnl} "
              f"≤ limit {limit}. New entries halted."),
        url="/risk/",
        row_data={"items": items,
                  "mark": NOTIFY_MARKS["drawdown_warning"]},
        telegram=_plain_message(title, items,
                                NOTIFY_MARKS["drawdown_warning"],
                                summary=summary,
                                button=("Open risk page", "/risk/")),
    )


def notify_protection_vanished(user, *, asset_class: str, symbol: str,
                               side: str, qty, stop_loss, reason: str,
                               trade_id=None) -> bool:
    """A live position's broker-side stop is gone while the position is
    still held. Operator-kind on purpose: a muted bot feed must not mute
    the one message that says real money is running without a stop."""
    from alerts.links import page_url
    from core.price_format import format_price
    title = f"⚠ {symbol} is UNPROTECTED at the broker"
    items = ([f"Position: {'long' if _is_long(side) else 'short'} "
              f"{units_words(qty, asset_class) or qty}",
              f"Reason: {reason}",
              "Bot-side management has taken the position back at stop "
              f"{format_price(stop_loss, asset_class, symbol)}",
              "Check the broker's open orders"]
             + ([f"Trade #{trade_id}"] if trade_id else []))
    page = page_url("forensics_detail", trade_id)
    return dispatch_notification(
        user, "protection_vanished",
        title=title,
        body=(f"{asset_class.upper()} · {side} qty {qty} · {reason}. "
              f"Bot-side stop/target management has taken the position "
              f"back at stop {stop_loss}; check the broker's open orders."),
        url=page or "/positions/",
        row_data={"items": items,
                  "mark": NOTIFY_MARKS["protection_vanished"]},
        telegram=_plain_message(
            title, items, NOTIFY_MARKS["protection_vanished"],
            summary=(f"The stop at the broker is gone while the {symbol} "
                     f"position is still open."),
            button=(("Open position", page) if page
                    else ("Open positions", "/positions/"))),
    )


def notify_unclaimed_position(user, *, symbols: list, venue: str) -> bool:
    """A position the broker holds that no row in this platform claims.

    Deliberately a notification and NOT an auto-close. The operator may
    have opened it by hand at the broker, and an automated system that
    starts flattening positions it does not recognise is far more
    dangerous than one that reports them.
    """
    listed = ", ".join(sorted(symbols)[:6])
    more = f" (+{len(symbols) - 6} more)" if len(symbols) > 6 else ""
    one = len(symbols) == 1
    title = (f"▲ {len(symbols)} "
             f"position{'' if one else 's'} at {venue} "
             f"that no row claims")
    items = [f"Venue: {venue}",
             f"Symbols: {listed}{more}",
             "Invisible to every exposure and daily-loss gate",
             "No bot-side stop, and the kill switch cannot "
             "flatten them",
             "Check the broker"]
    return dispatch_notification(
        user, "unclaimed_position",
        title=title,
        body=(f"{listed}{more}. These are invisible to every exposure and "
              f"daily-loss gate, carry no bot-side stop, and the kill "
              f"switch cannot flatten them — it walks database rows. "
              f"Check the broker."),
        url="/positions/",
        row_data={"items": items,
                  "mark": NOTIFY_MARKS["unclaimed_position"]},
        telegram=_plain_message(
            title, items, NOTIFY_MARKS["unclaimed_position"],
            summary=(f"{venue} holds {'a position' if one else 'positions'} "
                     f"Sauron has no record of, so nothing on the platform "
                     f"guards {'it' if one else 'them'}."),
            button=("Open positions", "/positions/")),
    )


def notify_track_record_decay(user, *, rule_name: str, asset_class: str,
                                recent_avg_r: float, baseline_avg_r: float,
                                recent_n: int,
                                triggers: list) -> bool:
    """Phase-26: rule's bot-trade performance has decayed.

    Triggers list: ["avg_r_drop", "win_rate_drop", "gone_negative"] (any subset).
    """
    delta = recent_avg_r - baseline_avg_r
    sign = "" if delta >= 0 else ""  # delta is negative when decaying
    return dispatch_notification(
        user, "track_record_decay",
        title=(f"▲ {rule_name} decay · "
                f"recent {recent_avg_r:+.2f}R vs baseline {baseline_avg_r:+.2f}R"),
        body=(f"{asset_class.upper()} · last {recent_n} trades · "
              f"triggers: {', '.join(triggers) or '—'}"),
        url="/bot-performance/",
        row_data={"items": [
            f"Rule: {rule_name}",
            f"Asset class: {asset_class.upper()}",
            f"Recent: {recent_avg_r:+.2f}R over the last {recent_n} trades",
            f"Baseline: {baseline_avg_r:+.2f}R",
            "Triggers: " + (", ".join(
                DECAY_WORDS.get(t, str(t).replace("_", " "))
                for t in triggers) or "none recorded")],
            "mark": NOTIFY_MARKS["track_record_decay"]},
    )


# ── Phase-43 daily briefing fan-out ──────────────────────────────────────

def notify_strategist_briefing_to_all(briefing) -> dict:
    """Push a freshly-produced StrategistBriefing to every user with the
    `receive_strategist_briefing` pref enabled.

    Returns counts: {n_eligible, n_delivered, n_skipped}. Always succeeds —
    individual delivery failures are logged but don't propagate.
    """
    try:
        from alerts.models import UserNotificationPrefs
    except Exception:
        return {"n_eligible": 0, "n_delivered": 0, "n_skipped": 0}

    eligible_users = list(
        UserNotificationPrefs.objects
        .filter(receive_strategist_briefing=True)
        .select_related("user")
    )
    if not eligible_users:
        return {"n_eligible": 0, "n_delivered": 0, "n_skipped": 0}

    title = (
        f"Sauron briefing — {briefing.posture.upper()} "
        f"({briefing.created_at:%Y-%m-%d})"
    )
    # Strip the strategist's **emphasis** BEFORE truncation: the bell
    # body, Telegram and Discord all render plain text, and an 800-char
    # cut could otherwise land mid-marker.
    from core.templatetags.sauron_tags import briefing_plain

    body_parts = []
    if briefing.outlook_md:
        outlook = briefing_plain(briefing.outlook_md).strip()
        if len(outlook) > 800:
            outlook = outlook[:800].rsplit(" ", 1)[0] + "…"
        body_parts.append(outlook)
    if briefing.posture_rationale:
        body_parts.append(
            f"Posture: {briefing_plain(briefing.posture_rationale)}")
    if briefing.ideas:
        idea_lines = []
        for i, idea in enumerate(briefing.ideas[:3], start=1):
            summary = briefing_plain((idea or {}).get("summary", ""))
            if summary:
                idea_lines.append(f"{i}. {summary}")
        if idea_lines:
            body_parts.append("Ideas:\n" + "\n".join(idea_lines))
    body = "\n\n".join(body_parts)[:4000]

    # Structured facts for the bell row's dwell card — the card was
    # showing a text stub while every one of these already existed.
    briefing_url = f"/briefing/?id={briefing.pk}"
    items = []
    if briefing.posture_rationale:
        items.append({"label": "POSTURE",
                      "detail": briefing.posture_rationale[:160],
                      "url": briefing_url})
    for i, idea in enumerate((briefing.ideas or [])[:3], start=1):
        summary = (idea or {}).get("summary", "")
        if summary:
            items.append({"label": f"IDEA {i}",
                          "detail": summary[:160], "url": briefing_url})
    if briefing.watchlist:
        heads = ", ".join(
            str((w or {}).get("ref", ""))[:28]
            for w in briefing.watchlist[:3] if (w or {}).get("ref"))
        items.append({"label": "WATCHLIST",
                      "detail": (f"{len(briefing.watchlist)} item"
                                 + ("" if len(briefing.watchlist) == 1
                                    else "s")
                                 + (f" · {heads}" if heads else "")),
                      "url": briefing_url})
    items.append({"label": "COST",
                  "detail": (f"${float(briefing.cost_usd or 0):.4f} · "
                             f"{briefing.tokens_in or 0} in / "
                             f"{briefing.tokens_out or 0} out"),
                  "url": ""})
    row_data = {"items": items,
                "mark": NOTIFY_MARKS["strategist_briefing"],
                "briefing": {"posture": briefing.posture,
                             "id": briefing.pk}}

    n_delivered = 0
    n_skipped = 0
    for prefs in eligible_users:
        try:
            ok = dispatch_notification(
                prefs.user, "strategist_briefing",
                title=title, body=body, url=briefing_url,
                payload=briefing,  # Phase-45 — email path uses HTML template
                row_data=row_data,
            )
            if ok:
                n_delivered += 1
            else:
                n_skipped += 1
        except Exception as e:  # pragma: no cover
            logger.warning("notify_strategist_briefing failed for %s: %s",
                            prefs.user_id, e)
            n_skipped += 1

    return {"n_eligible": len(eligible_users),
            "n_delivered": n_delivered, "n_skipped": n_skipped}


# ── Phase-46 staff-only health alerts ────────────────────────────────────

def notify_staff(*, title: str, body: str = "", url: str = "",
                  cooldown_hours: int = 3) -> dict:
    """Push an operational health alert to all staff users.

    De-dupes via the in-app `Notification` table — if a row with the same
    title already exists within `cooldown_hours`, skips. Useful for
    "brain failed N times in a row" type alerts that shouldn't spam.

    Returns counts: {n_staff, n_delivered, n_skipped_cooldown}.
    """
    from datetime import timedelta as _td
    from django.contrib.auth.models import User
    from django.utils import timezone as _tz

    # Cooldown check (global, not per-user — health alerts are platform-wide).
    try:
        from alerts.models import Notification
        cutoff = _tz.now() - _td(hours=max(1, int(cooldown_hours)))
        if Notification.objects.filter(title=title[:200],
                                          created_at__gte=cutoff).exists():
            return {"n_staff": 0, "n_delivered": 0, "n_skipped_cooldown": 1}
    except Exception:
        pass  # If lookup fails, still try to dispatch.

    staff = list(User.objects.filter(is_staff=True, is_active=True))
    n_delivered = 0
    for u in staff:
        try:
            # A caller's free body, not facts: the mark alone, and
            # Telegram renders the body under the bold title.
            ok = dispatch_notification(
                u, "system_health", title=title, body=body, url=url,
                row_data={"mark": _staff_mark(title)},
            )
            if ok:
                n_delivered += 1
        except Exception as e:  # pragma: no cover
            logger.warning("notify_staff: dispatch failed for %s: %s", u.id, e)
    return {"n_staff": len(staff), "n_delivered": n_delivered,
            "n_skipped_cooldown": 0}


#: What to DO, per venue, when the sync stops answering. The remedy is
#: the whole point of the alert: a Gateway instruction sent to a Saxo
#: operator is an instruction to read the logs of a component that is not
#: involved, at the moment something real is broken.
BROKER_REMEDY = {
    "ibkr": ("A Gateway container that is up is not one that is logged in — "
             "check `dc ps` for (unhealthy) and `dc logs ibgateway` for a "
             "'Gateway' dialog IBC could not read.", "/system-health/"),
    "saxo": ("Saxo answers the sync only while the OAuth session is alive, "
             "and its refresh token lives forty minutes and rotates. Open "
             "/brokers/ and press 'Connect Saxo — sign in once'. A box that "
             "was down longer than forty minutes always needs this.",
             "/brokers/"),
    "etoro": ("eToro answers with two long-lived keys and no sign-in, so this "
              "is the keys or the account: re-save them on /brokers/, which "
              "probes them once and reports ok, refused or unverified — three "
              "states, not two.", "/brokers/"),
}


def notify_broker_unreachable(user, *, label: str, host: str, port: int,
                              misses: int, broker: str = "ibkr") -> bool:
    """The interfaced broker has not answered for several syncs running.

    Filed under system_health because that is what it is. The operator's
    first real Gateway sat behind a notice dialog IBC could not read for
    three hours while `ps` said "Up 3 hours" — a container that is up is
    not a Gateway that is logged in, and nothing on the platform said so.
    The sync task is the one thing that asks every 15 minutes, so it is
    the one thing that can.
    """
    remedy, url = BROKER_REMEDY.get(broker or "ibkr",
                                    BROKER_REMEDY["ibkr"])
    # A socket only where there is one. Saxo and eToro have no host and no
    # port, and "api:0 has not answered" is a fact about nothing.
    where = f"{host}:{port}" if (broker or "ibkr") == "ibkr" else label
    return dispatch_notification(
        user, "system_health",
        title=f"▲ {label}: broker unreachable for {misses} syncs running",
        body=(f"{where} has not answered the account sync since "
              f"{misses * 15} minutes ago. {remedy} Equity and holdings on "
              f"every page are showing their last reading with its age, not "
              f"a live one."),
        url=url,
        row_data={"items": [
            f"Account: {label}",
            f"Not answering: {where}",
            f"Silent for {misses} syncs running (about {misses * 15} minutes)",
            f"What to do: {remedy.replace('`', '')}",
            "Equity and holdings on every page show their last reading, "
            "with its age"],
            "mark": NOTIFY_MARKS["broker_unreachable"]},
    )


def notify_evidence_chain_cold(user, *, cold: list, blockers: list) -> bool:
    """A link in the paper-campaign evidence chain has gone cold.

    Filed under system_health for the same reason as the broker alert: it is
    not a trading event, it is the platform failing to measure itself.

    The distinction that makes this worth sending: a cold link costs nothing
    TODAY and everything in ninety days. Nothing breaks, no page goes red, no
    task raises — `guarded_task` simply no-ops on a component that is off or
    has no row, and the ladder reads n=0 at the end of a campaign that was
    never running. By then the time is spent and cannot be bought back.

    The body names the links rather than a count, because "2 links cold" sends
    an operator to a page and "pipeline_promotion is off" sends them to a
    switch.
    """
    names = ", ".join(cold) if cold else "the chain"
    first = blockers[0] if blockers else ""
    return dispatch_notification(
        user, "system_health",
        title=f"▲ Evidence chain cold: {names}",
        body=(f"The paper-campaign chain is not complete, so the days passing "
              f"now are producing nothing the promotion ladder can grade. "
              f"Cold: {names}. {first} "
              f"Run `manage.py paper_readiness` for the full chain — it "
              f"writes nothing. A link that is off is a decision; a link with "
              f"NO ROW was never seeded, and the two are fixed by different "
              f"commands."),
        url="/ops/",
        row_data={"items": (
            [f"Cold: {names}"] + ([first] if first else [])
            + ["Run manage.py paper_readiness for the full chain; it "
               "writes nothing",
               "A link that is off is a decision; a link with no row was "
               "never seeded"]),
            "mark": NOTIFY_MARKS["evidence_chain_cold"]},
    )
