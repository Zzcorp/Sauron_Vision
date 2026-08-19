"""Phase-20 bot notification dispatcher.

A thin orchestration layer that takes a (user, kind, title, body) tuple,
checks the user's preferences, and fans out to:
  - in-app `Notification` row (always, when prefs allow)
  - configured external channels (telegram, email, discord) — gracefully
    degrades when credentials missing

Hook points:
  - `gate_new_entry` reject  → "orchestrator_reject"
  - bot opens a position     → "bot_fill_open"
  - bot closes a position    → "bot_fill_close"
  - daily-loss limit reached → "drawdown_warning"

All hooks are wrapped in try/except so a notification failure never breaks
trading logic.
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


# All bot-event kinds. Adding new ones requires no schema change — they all
# map to the in-app `Notification.notification_type="bot"` and are gated by
# the single `UserNotificationPrefs.receive_bot_alerts` flag.
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


def dispatch_notification(user, kind: str, *, title: str, body: str = "",
                          url: str = "", payload=None) -> bool:
    """Send a bot-event notification to `user`.

    Returns True if at least one delivery channel succeeded (including in-app).
    Returns False if the user has bot alerts disabled OR all channels failed.

    Phase-45: `payload` is an optional kind-specific object (e.g. a
    `StrategistBriefing` row) used by channels that render structured
    templates (HTML email). Plain channels fall back to the title+body
    pair so callers don't need to know which channel is in use.
    """
    if kind not in BOT_KINDS:
        logger.warning("dispatch_notification: unknown kind=%r", kind)
        return False

    # Phase-43 — briefings have their own pref toggle (opt-in, default OFF).
    if kind == "strategist_briefing":
        if not _user_wants_briefing(user):
            return False
    elif not _user_wants_bot_alerts(user):
        return False

    delivered = False

    # ── In-app row (bell dropdown) — ALWAYS created, even in quiet hours ──
    # The user can still see the row when they open the bell; we just
    # don't buzz an external channel while they're sleeping.
    try:
        from alerts.models import Notification
        n = Notification(
            user=user, notification_type="bot",
            title=title[:200], body=body, url=url[:200],
        )
        # Fills already raise their own richer live banner straight from
        # the engine (fill_open/fill_close on /ws/eye/). Mark this row
        # banner-silent so the bell badge still updates live but the same
        # event never shows two cards.
        n._banner_silent = kind in ("bot_fill_open", "bot_fill_close")
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

def _send_telegram(user, title: str, body: str) -> bool:
    """Send via the platform Telegram bot to the user's chat_id.

    Requires `TELEGRAM_BOT_TOKEN` env var (platform-wide) and the user's
    `UserNotificationPrefs.telegram_chat_id` (per-user).
    """
    try:
        import os, requests
        token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        if not token:
            return False
        chat_id = getattr(user.notification_prefs, "telegram_chat_id", "")
        if not chat_id:
            return False
        text = f"*{title}*\n\n{body}" if body else f"*{title}*"
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
            timeout=5,
        )
        return r.ok
    except Exception as e:
        logger.warning("telegram dispatch failed: %s", e)
        return False


def _send_email(user, title: str, body: str) -> bool:
    """Send via Django's email backend to user.email."""
    try:
        if not user.email:
            return False
        from alerts.channels.email_alert import send_email_alert
        return send_email_alert(user.email, title, body)
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
        content = f"**{title}**\n{body}" if body else f"**{title}**"
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
        title=f"🛰 Orchestrator blocked {symbol} {side}",
        body=f"{asset_class.upper()} · {reason}",
        url="/eye/",
    )


def notify_bot_fill_open(user, *, asset_class: str, symbol: str, side: str,
                          qty, entry_price, rule_name: str = "",
                          trade_id=None) -> bool:
    from alerts.links import page_url
    return dispatch_notification(
        user, "bot_fill_open",
        title=f"📈 {symbol} {side} opened",
        body=f"{asset_class.upper()} · qty {qty} @ {entry_price}"
             + (f" · {rule_name}" if rule_name else ""),
        # The fill has a page: forensics carries the rule that fired, the
        # signals that voted and the gate decision behind THIS trade —
        # "why did it just buy that?", which is the question the banner
        # provokes. /asset-bots/ is the config list and answers none of it.
        url=page_url("forensics_detail", trade_id) or "/asset-bots/",
    )


def notify_bot_fill_close(user, *, asset_class: str, symbol: str, side: str,
                           qty, exit_price, pnl, outcome: str = "",
                           trade_id=None) -> bool:
    from alerts.links import page_url
    icon = "🎯" if outcome == "hit_target" else (
        "🛑" if outcome == "stopped_out" else "🔚")
    sign = "+" if (pnl is not None and pnl > 0) else ""
    return dispatch_notification(
        user, "bot_fill_close",
        title=f"{icon} {symbol} {side} closed · {sign}{pnl}",
        body=f"{asset_class.upper()} · qty {qty} @ {exit_price}"
             + (f" · {outcome}" if outcome else ""),
        # Same trade, same page — the close's own timeline, grade and R
        # multiple. /bot-performance/ aggregates every rule instead.
        url=page_url("forensics_detail", trade_id) or "/bot-performance/",
    )


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

    title = f"⛔ Close refused: {symbol}"
    try:
        from alerts.models import Notification
        recent = Notification.objects.filter(
            user=user, notification_type="bot", title=title,
            created_at__gte=_tz.now() - _td(hours=1)).exists()
        if recent:
            return False
    except Exception as e:  # noqa: BLE001 — dedupe failure must not mute it
        logger.warning("close-refused dedupe failed: %s", e)

    return dispatch_notification(
        user, "bot_error", title=title,
        body=(f"{asset_class.upper()} trade #{trade_id} is LIVE and its "
              f"broker is unreachable, so the close was refused rather than "
              f"stamped on a position that is still open. The position is "
              f"STILL OPEN at the broker."),
        url=page_url("forensics_detail", trade_id) or "/eye/fills/",
    )


def notify_drawdown_warning(user, *, asset_class: str, config_name: str,
                             realized_pnl, limit) -> bool:
    return dispatch_notification(
        user, "drawdown_warning",
        title=f"⚠ Drawdown limit reached · {config_name}",
        body=(f"{asset_class.upper()} · realized 24h P&L {realized_pnl} "
              f"≤ limit {limit}. New entries halted."),
        url="/risk/",
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
        title=(f"📉 {rule_name} decay · "
                f"recent {recent_avg_r:+.2f}R vs baseline {baseline_avg_r:+.2f}R"),
        body=(f"{asset_class.upper()} · last {recent_n} trades · "
              f"triggers: {', '.join(triggers) or '—'}"),
        url="/bot-performance/",
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
    body_parts = []
    if briefing.outlook_md:
        outlook = briefing.outlook_md.strip()
        if len(outlook) > 800:
            outlook = outlook[:800].rsplit(" ", 1)[0] + "…"
        body_parts.append(outlook)
    if briefing.posture_rationale:
        body_parts.append(f"Posture: {briefing.posture_rationale}")
    if briefing.ideas:
        idea_lines = []
        for i, idea in enumerate(briefing.ideas[:3], start=1):
            summary = (idea or {}).get("summary", "")
            if summary:
                idea_lines.append(f"{i}. {summary}")
        if idea_lines:
            body_parts.append("Ideas:\n" + "\n".join(idea_lines))
    body = "\n\n".join(body_parts)[:4000]

    n_delivered = 0
    n_skipped = 0
    for prefs in eligible_users:
        try:
            ok = dispatch_notification(
                prefs.user, "strategist_briefing",
                title=title, body=body, url="/briefing/",
                payload=briefing,  # Phase-45 — email path uses HTML template
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
            ok = dispatch_notification(
                u, "system_health", title=title, body=body, url=url,
            )
            if ok:
                n_delivered += 1
        except Exception as e:  # pragma: no cover
            logger.warning("notify_staff: dispatch failed for %s: %s", u.id, e)
    return {"n_staff": len(staff), "n_delivered": n_delivered,
            "n_skipped_cooldown": 0}
