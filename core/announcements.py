"""ANNOUNCEMENTS (2026-10-03): what the platform tells its group, in the
house style and in the lore.

The operator: "make the telegram bot send it in his group... with great
styling and lore". The release notes the viewers and the loyals read, as
data: one entry per announcement — a title, an italic subtitle, one
summary paragraph, the facts as lines (a TelegramHeading renders bold),
and a folded record (Telegram's expandable blockquote) for the lore's
who-is-who. Rendered by alerts/channels/telegram_alert.fit_text, the one
renderer every message goes through: HTML parse mode, every field
escaped, under Telegram's 4,096 characters, English only.

Sent by `manage.py announce NAME` to the platform chat (TELEGRAM_CHAT_ID,
the group the Eye answers in) or to `--chat`; once per chat — the cache
remembers a send for SENT_TTL_DAYS and `--force` sends again. Nothing
here says a number of the book, promises a return, or names a person.
"""
from __future__ import annotations

import logging
import os

from bot_program.notifications import TelegramHeading

logger = logging.getLogger(__name__)

#: The Eye, drawn by the Telegram client in front of the title.
MARK = "\U0001F441️"
#: A send is remembered this long per chat, so a release goes out once.
SENT_TTL_DAYS = 7


OCTOBER_TURN = {
    "title": "THE EYE TURNS · Sauron Vision, October 2026",
    "subtitle": "The Eye has looked at itself. What it saw, and what it built.",
    "summary": (
        "We measured ourselves before building anything. The honest finding: "
        "our losses did not come from being wrong often. They came from "
        "winners cut too early, and from a few stops that did not hold when "
        "they should have. So this release is not another indicator. It is a "
        "system that reads the market like a trader, proves before it "
        "trusts, and keeps its own score."),
    "lines": [
        TelegramHeading("WHAT IS NEW"),
        "• THE PROVING GROUND — every strategy, live or candidate, "
        "replayed on real history: fills at the next bar's open, costs "
        "doubled, 30% of the data kept untouched as a holdout, five time "
        "folds, and a significance bar that gets harder the more candidates "
        "we tried. Four verdicts only: PROVEN, PROMISING, FAILED, "
        "INSUFFICIENT. Nothing goes to real money on a story.",
        "• THE SETUP MEMORY — before a trade, what happened the last "
        "sixty times this setup fired on this asset class, in this kind of "
        "tape: how often it won, how far it went, how long it took.",
        "• THE THESIS CHECK — open positions are no longer judged on "
        "the P&L alone. The structure first: was the dip a stop hunt that "
        "reversed, or a real break? Is the bias still with us? A thesis that "
        "is alive is held, the stop moved under the sweep. A dead one is "
        "called dead, whatever the P&L says.",
        "• THE LIVING LEVELS — on every chart, where the crowd keeps "
        "its stops: unswept swings, liquidity pools, the latest extreme, the "
        "round numbers. Recomputed every minute; a level the price trades "
        "through disappears.",
        "• THE POSITIONING MAP — who is already placed, from the data "
        "that exists: speculators and hedgers (COT), funding, flow, "
        "sentiment. Where their stops sit, where a hunt runs first, where "
        "the market is pulled after. Nobody sees other desks' orders, and we "
        "never print a probability we cannot measure.",
        "• ARAGORN, THE STEWARD — break-even, trailing and structure "
        "stops, all placed beyond the crowd's hunt zone. It only ever "
        "reduces risk. It never widens a stop.",
        "• THE WARNINGS ON EVERY TICKET — reward-to-risk under one; "
        "no signal behind the trade; closing a winner earlier than this lane "
        "usually pays. Warnings, never blocks: the operator keeps the last "
        "word.",
        "• THE SCORECARD AND THE RECORD — win rate, payoff, "
        "expectancy, by lane and by rule. Every thesis verdict is graded "
        "later against what the position did. If our holds stop paying, we "
        "see it first.",
        TelegramHeading("WHY THIS COULD BE THE TURN"),
        "The edge we were missing was not in finding trades. It was in "
        "holding the right ones, protecting them where the crowd gets "
        "hunted, and refusing the ones the data never backed. That is what "
        "this release does, in code, every thirty minutes, on every open "
        "position.",
        "No promises. The proving ground exists so that we never promise "
        "what the data has not shown. The scorecard will tell the story, "
        "and we will share it.",
    ],
    "details": [
        "WHO IS WHO — Sauron, the Eye that watches every tick and every "
        "position. Morgul, the alarm that speaks only when something is "
        "wrong and never says all is well. Aragorn, the steward of open "
        "positions: break-even, trailing, structure. The proving ground, "
        "where a strategy earns the right to exist. The Wall, where the "
        "whole day is drawn.",
    ],
}

ANNOUNCEMENTS = {"october_turn": OCTOBER_TURN}


def render(name: str) -> str:
    """The HTML Telegram receives for `name`, as fit_text renders it."""
    from alerts.channels.telegram_alert import fit_text
    a = ANNOUNCEMENTS[name]
    return fit_text(a["title"], lines=a["lines"], mark=MARK,
                    subtitle=a.get("subtitle", ""),
                    summary=a.get("summary", ""),
                    details=a.get("details"))


def _sent_key(name: str, chat: str) -> str:
    return f"announce:sent:{name}:{chat}"


def already_sent(name: str, chat: str) -> bool:
    from django.core.cache import cache
    return bool(cache.get(_sent_key(name, chat)))


def send(name: str, *, chat=None, force: bool = False) -> dict:
    """{outcome, chat, why}: the announcement to `chat` (the platform
    chat when None), once per chat unless `force`. Outcomes are
    telegram_alert's: sent, refused, unsent, unknown — plus "repeat" when
    the cache remembers a send and `force` is off. Never raises."""
    from django.core.cache import cache

    from alerts.channels.telegram_alert import (SENT, UNKNOWN, UNSENT,
                                                send_to_chat_outcome)
    a = ANNOUNCEMENTS[name]
    chat = str(chat or os.getenv("TELEGRAM_CHAT_ID", "") or "").strip()
    if not chat:
        return {"outcome": UNSENT, "chat": "", "why": "no chat: TELEGRAM_CHAT_ID "
                                                    "is not set and no --chat"}
    if not os.getenv("TELEGRAM_BOT_TOKEN", ""):
        return {"outcome": UNSENT, "chat": chat,
                "why": "TELEGRAM_BOT_TOKEN is not set"}
    if already_sent(name, chat) and not force:
        return {"outcome": "repeat", "chat": chat,
                "why": (f"{name} already went to this chat inside "
                        f"{SENT_TTL_DAYS} days; --force sends it again")}
    outcome = send_to_chat_outcome(chat, a["title"], lines=a["lines"],
                                   mark=MARK, subtitle=a.get("subtitle", ""),
                                   summary=a.get("summary", ""),
                                   details=a.get("details"))
    if outcome in (SENT, UNKNOWN):
        # UNKNOWN too: the answer was lost, it may have been posted, and
        # posting it again may post it twice.
        cache.set(_sent_key(name, chat), outcome, SENT_TTL_DAYS * 86400)
    why = {SENT: "Telegram took it",
           UNKNOWN: "the answer was lost: it may have been posted, so it is "
                    "remembered as sent (--force to send again)",
           "refused": "Telegram refused it (the WARNING line says why)",
           UNSENT: "it never reached Telegram (the WARNING line says why)"
           }.get(outcome, "")
    return {"outcome": outcome, "chat": chat, "why": why}
