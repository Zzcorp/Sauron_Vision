"""Signal dispatch — route notifications to users based on their preferences and rules."""
import logging
from django.contrib.auth.models import User
from alerts.models import AlertRule, UserNotificationPrefs

logger = logging.getLogger(__name__)


#: Signal messages per chat per rolling hour; past it they are held and
#: counted, and the next message that goes out says how many (T7).
SIGNAL_FLOOD_MAX = 20
SIGNAL_FLOOD_WINDOW_S = 3600
_FLOOD_SENT_KEY = "telegram:signal_flood:sent:{chat}"
_FLOOD_HELD_KEY = "telegram:signal_flood:held:{chat}"    # how many held
_FLOOD_SINCE_KEY = "telegram:signal_flood:since:{chat}"  # the first held
_FLOOD_HELD_TTL_S = 7 * 86400

#: The side a signal's direction trades, as its Telegram title says it.
SIGNAL_SIDES = {"bullish": "BUY", "bearish": "SELL"}


def signal_telegram(signal) -> tuple:
    """(title, lines, mark): one signal as the house message.

        📈 Signal · MSFT · BUY
        Score: 0.82
        Rule: starter_stock_momentum
        Entry 421.37 · stop 410.00 · target 440.00
        Reward to risk: 1.85
        Urgency: medium
        Page: https://<DOMAIN>/instruments/MSFT/

    Prices at the instrument's own decimals (core.price_format, the
    convention every page uses); a level the signal does not carry is
    left out, never printed as zero.
    """
    import math

    from alerts.channels.telegram_alert import MARKS, page_line
    from alerts.links import instrument_url
    from core.price_format import format_price

    inst = signal.instrument
    symbol = inst.symbol
    asset_class = getattr(inst, "asset_class", "") or ""
    direction = str(signal.direction or "").lower()
    side = SIGNAL_SIDES.get(direction) or (direction.upper() or "SIGNAL")
    mark = MARKS.get(f"signal_{direction}") or MARKS["signal"]
    lines = [f"Score: {float(signal.score or 0):.2f}"]
    if signal.rule_name:
        lines.append(f"Rule: {signal.rule_name}")
    levels = []
    for word, value in (
            ("entry", signal.suggested_entry or signal.price_at_signal),
            ("stop", signal.suggested_stop),
            ("target", signal.suggested_target)):
        if value:
            levels.append(f"{word} {format_price(value, asset_class, symbol)}")
    if levels:
        joined = " · ".join(levels)
        lines.append(joined[:1].upper() + joined[1:])
    rr = signal.risk_reward_ratio
    if rr and math.isfinite(float(rr)):
        lines.append(f"Reward to risk: {float(rr):.2f}")
    if signal.urgency:
        lines.append(f"Urgency: {signal.urgency}")
    try:
        path = instrument_url(symbol) or "/signals/"
    except Exception:  # noqa: BLE001 — a link is never worth the message
        path = "/signals/"
    line = page_line(path)
    if line:
        lines.append(line)
    return f"Signal · {symbol} · {side}", lines, mark


def _utc_words(ts, now) -> str:
    """HH:MM UTC, with the date when it is not today's."""
    from datetime import datetime
    from datetime import timezone as dt_tz
    at = datetime.fromtimestamp(float(ts), tz=dt_tz.utc)
    today = datetime.fromtimestamp(float(now), tz=dt_tz.utc).date()
    return (f"{at:%H:%M} UTC" if at.date() == today
            else f"{at:%Y-%m-%d %H:%M} UTC")


def _flood_admit(chat, signal) -> tuple:
    """(admitted, extra line, the held count it tells) for one signal
    message to `chat`.

    A rolling hour, kept in the cache as the send times inside it. Past
    SIGNAL_FLOOD_MAX the message is held: nothing is posted, an INFO line
    says so, and the count waits for the next message that does go out,
    which carries "+N more signals since HH:MM UTC on the platform". A
    cache that cannot be read admits the message: a busy chat is better
    than a silent one.

    The held count is one integer (cache.add then cache.incr, atomic on
    Redis), so two workers holding at once both count. The send times are
    a read-then-write list: two workers admitting at the same instant can
    let one message past the twentieth, never lose one.
    """
    import time

    from django.core.cache import cache
    now = time.time()
    sent_key = _FLOOD_SENT_KEY.format(chat=chat)
    held_key = _FLOOD_HELD_KEY.format(chat=chat)
    since_key = _FLOOD_SINCE_KEY.format(chat=chat)
    try:
        sent = [float(t) for t in (cache.get(sent_key) or [])
                if now - float(t) < SIGNAL_FLOOD_WINDOW_S]
        if len(sent) >= SIGNAL_FLOOD_MAX:
            cache.add(since_key, now, _FLOOD_HELD_TTL_S)
            cache.add(held_key, 0, _FLOOD_HELD_TTL_S)
            n = cache.incr(held_key)
            logger.info(
                "[signal telegram] chat %s had %d signal messages in the "
                "last hour: signal #%s (%s) not posted; %d held since %s",
                chat, len(sent), getattr(signal, "pk", None),
                signal.instrument.symbol, n,
                _utc_words(cache.get(since_key) or now, now))
            return False, "", 0
        sent.append(now)
        cache.set(sent_key, sent, SIGNAL_FLOOD_WINDOW_S)
        n = int(cache.get(held_key) or 0)
        since = float(cache.get(since_key) or now)
    except Exception as e:  # noqa: BLE001
        logger.debug("[signal telegram] flood guard unreadable: %s", e)
        return True, "", 0
    if n <= 0:
        return True, "", 0
    noun = "signal" if n == 1 else "signals"
    return True, (f"+{n} more {noun} since {_utc_words(since, now)} "
                  f"on the platform"), n


def _flood_release(chat, told: int) -> None:
    """`told` held signals were announced: take exactly those off the
    count. A signal held while that message was on its way stays counted
    for the next one (a delete here used to lose it)."""
    import time

    from django.core.cache import cache
    held_key = _FLOOD_HELD_KEY.format(chat=chat)
    since_key = _FLOOD_SINCE_KEY.format(chat=chat)
    try:
        try:
            left = cache.decr(held_key, told)
        except ValueError:  # the count expired meanwhile: nothing is left
            left = 0
        if left <= 0:
            cache.delete_many([held_key, since_key])
        else:
            cache.set(since_key, time.time(), _FLOOD_HELD_TTL_S)
    except Exception:  # noqa: BLE001
        pass


def _add_chat(chats: list, user) -> None:
    """The user's Telegram chat, once in `chats` however many users share it."""
    try:
        chat = str(user.notification_prefs.telegram_chat_id or "").strip()
    except Exception:  # noqa: BLE001 — no preferences row: no chat
        return
    if chat and chat not in chats:
        chats.append(chat)


def _telegram_signal(signal, chats: list) -> dict:
    """Post the signal's house message to each chat once, flood-guarded."""
    import os
    from html import escape
    out = {"chats": len(chats), "sent": 0, "held": 0, "refused": 0}
    if not chats or not os.getenv("TELEGRAM_BOT_TOKEN", ""):
        return out
    from alerts.channels.telegram_alert import fit_text, send_to_chat
    title, lines, mark = signal_telegram(signal)
    for chat in chats:
        admitted, extra, held = _flood_admit(chat, signal)
        if not admitted:
            out["held"] += 1
            continue
        told = lines + ([extra] if extra else [])
        if send_to_chat(chat, title, lines=told, mark=mark):
            out["sent"] += 1
            # The count is cleared only when its line was in the text that
            # went out: a message cut to fit loses its last line first.
            if extra and escape(extra) in fit_text(title, lines=told,
                                                   mark=mark):
                _flood_release(chat, held)
        else:
            out["refused"] += 1
    return out


def dispatch_signal_alert(signal):
    """Send a signal notification to all users whose rules match.

    The rules, receive_signals, email and WhatsApp work as they always
    did. Telegram changed on 2026-09-26:
      * one house message per signal (signal_telegram), posted through
        alerts.channels.telegram_alert.send_to_chat, which reads the
        answer and logs a refusal with Telegram's words. The legacy
        Markdown posted here before read an underscore in a rule name as
        italics, and the 400 that followed vanished without a line;
      * each chat receives a signal ONCE, however many users point at it
        (the Sauron group is one chat);
      * at most SIGNAL_FLOOD_MAX signal messages per chat per rolling hour;
      * Telegram goes first. _match_users walks the users and gathers the
        chats, the emails and the WhatsApp messages; the chats are posted,
        then the emails and WhatsApp messages go out in the order they were
        met, so an SMTP server taking its 20 seconds a mail never holds the
        group's message. A walk that fails half way still posts to the
        chats and sends the messages it had gathered, then raises as it
        always did (signals.announce logs it).
    Returns what the Telegram step did: {"chats", "sent", "held",
    "refused"}.
    """
    pk = getattr(signal, "pk", None)
    chats = []  # the Telegram chats, in the order first met, each once
    later = []  # the emails and WhatsApp messages, sent after Telegram
    out = {"chats": 0, "sent": 0, "held": 0, "refused": 0}
    try:
        _match_users(signal, chats, later)
    finally:
        try:
            out = _telegram_signal(signal, chats)
        except Exception:  # noqa: BLE001 — the other channels still go out
            logger.exception("signal #%s: the Telegram step failed", pk)
            out = {"chats": len(chats), "sent": 0, "held": 0, "refused": 0}
        for send in later:
            try:
                send()
            except Exception as e:  # noqa: BLE001
                logger.warning("signal #%s: %s failed: %s", pk,
                               getattr(send.func, "__name__", "a send"), e)
    return out


def _match_users(signal, chats: list, later: list) -> None:
    """The users walked as dispatch_signal_alert always walked them: a
    user's first matching rule, else their preferences when they have no
    rule. Each user's Telegram chat joins `chats` once (_add_chat); each
    email and WhatsApp message joins `later`, in the order met."""
    from functools import partial

    from alerts.channels.email_alert import send_email_to_user
    from alerts.channels.whatsapp_alert import send_whatsapp_to_user

    for user in User.objects.filter(is_active=True):
        # Check user's alert rules
        rules = AlertRule.objects.filter(user=user, is_active=True)

        matched = False
        for rule in rules:
            if _rule_matches(rule, signal):
                matched = True
                title = f"Signal: {signal.instrument.symbol} {signal.direction.upper()}"
                message = (
                    f"Score: {signal.score:.2f}\n"
                    f"Type: {signal.signal_type}\n"
                    f"{signal.title}\n"
                    f"Urgency: {signal.urgency}"
                )

                if rule.notify_telegram:
                    _add_chat(chats, user)

                if rule.notify_email:
                    later.append(partial(send_email_to_user, user, title,
                                         message))

                if rule.notify_whatsapp:
                    later.append(partial(send_whatsapp_to_user, user, title,
                                         message))

                break  # One match is enough

        # If no custom rules, check global prefs
        if not matched and not rules.exists():
            try:
                prefs = user.notification_prefs
                if prefs.receive_signals:
                    title = f"Signal: {signal.instrument.symbol} {signal.direction.upper()}"
                    message = f"Score: {signal.score:.2f} | {signal.title}"
                    if prefs.telegram_chat_id:
                        _add_chat(chats, user)
                    if prefs.email_notifications and user.email:
                        later.append(partial(send_email_to_user, user,
                                             title, message))
            except Exception:
                pass


def _rule_matches(rule, signal):
    """Check if a signal matches an alert rule."""
    if rule.instrument_symbol and rule.instrument_symbol != signal.instrument.symbol:
        return False
    if rule.asset_class and rule.asset_class != signal.instrument.asset_class:
        return False
    if rule.direction and rule.direction != signal.direction:
        return False
    if signal.score < rule.min_score:
        return False
    return True


def dispatch_strategy_alert(strategy):
    """Notify users about a new strategy proposal."""
    from alerts.channels.telegram_alert import send_strategy_proposal
    send_strategy_proposal(strategy)


def dispatch_news_alert(article):
    """Notify users about critical news."""
    if not article.ai_urgency or article.ai_urgency not in ["critical", "high"]:
        return

    from alerts.channels.telegram_alert import MARKS, page_line, send_telegram
    from alerts.links import page_url
    lines = [" ".join(str(article.title or "").split()) or "Untitled article",
             f"Source: {article.source}",
             f"Urgency: {article.ai_urgency}"]
    try:
        line = page_line(page_url("news_detail", article.pk))
    except Exception:  # noqa: BLE001 — a link is never worth the message
        line = ""
    if line:
        lines.append(line)
    return send_telegram("Breaking news", lines=lines, mark=MARKS["news"])
