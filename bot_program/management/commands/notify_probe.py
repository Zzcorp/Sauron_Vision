"""CLI: where do this user's alerts go — and does Telegram answer?

    python manage.py notify_probe --user Sauron          (read-only)
    python manage.py notify_probe --user Sauron --send   (one test push)

Prints the channel (TraderProfile.notify_channel), the preference that
gates every bot event (receive_bot_alerts), the quiet hours, and whether a
Telegram chat id and the platform token are present IN THIS PROCESS (the
senders run in worker-fast, worker-slow and beat: probe them with
`./deploy/dc exec worker-fast python manage.py notify_probe ...`). With
--send it pushes ONE test message through the Telegram sender itself and
prints the answer; a refusal is also logged with Telegram's own words
(\"telegram refused\"). Nothing here trades, ticks or arms anything.
"""
import os

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Show a user's alert routing; --send pushes one test Telegram message."

    def add_arguments(self, parser):
        parser.add_argument("--user", required=True)
        parser.add_argument("--send", action="store_true",
                            help="push one test message through the sender")

    def handle(self, *args, **opts):
        from django.contrib.auth import get_user_model
        from bot_program import notifications as N

        User = get_user_model()
        try:
            user = User.objects.get(username=opts["user"])
        except User.DoesNotExist:
            raise CommandError(f"no user {opts['user']!r}")
        try:
            prefs = user.notification_prefs
        except Exception:  # noqa: BLE001 — no row is a state
            prefs = None
        w = self.stdout.write
        w(f"NOTIFY PROBE — {user.username} · staff={user.is_staff}")
        w(f"  channel            {N._user_channel(user)}"
          f"  (TraderProfile.notify_channel)")
        w(f"  bot alerts         {'ON' if N._user_wants_bot_alerts(user) else 'OFF'}"
          + ("  (no prefs row: the default)" if prefs is None
             else "  (UserNotificationPrefs.receive_bot_alerts)"))
        chat = (str(getattr(prefs, "telegram_chat_id", "") or "")
                if prefs is not None else "")
        w(f"  telegram chat id   {'present' if chat else 'ABSENT'}"
          f"  (UserNotificationPrefs.telegram_chat_id)")
        w(f"  telegram token     "
          f"{'present' if os.getenv('TELEGRAM_BOT_TOKEN') else 'ABSENT'}"
          f"  (TELEGRAM_BOT_TOKEN in THIS process)")
        qs = getattr(prefs, "quiet_start", None) if prefs is not None else None
        qe = getattr(prefs, "quiet_end", None) if prefs is not None else None
        w(f"  quiet hours (UTC)  {qs or '—'} → {qe or '—'}"
          f"  · quiet now: {N._in_quiet_hours(user)}")
        if not opts["send"]:
            w("  (pass --send to push one test message through the Telegram "
              "sender)")
            return
        ok = N._send_telegram(
            user, "◉ Sauron notification probe",
            "A test push through the same sender a bot fill uses.",
            lines=["This is a test — nothing traded",
                   "Sent by manage.py notify_probe --send",
                   "If you read this, bot fills and closes reach you"],
            mark="\U0001F514")
        w(f"  telegram           "
          + ("answered OK" if ok else
             "REFUSED or unreachable — read the worker log line "
             "'telegram refused' (or 'telegram dispatch failed')"))
