"""The alarm bot, by hand (bot_program/alarm.py).

Prints the configuration verdict (the token and the chat present, never
the token's value, and why the bot refuses to run if it does) and every
critical problem the sentinel sees now, with its key. READ ONLY by
default: nothing is sent and no memory is written. --send runs one
sentinel pass instead: the dedupe, the messages to the alarm chat and the
memory -- nothing is sent while the telegram_alarm switch is off. --test
sends ONE message to the alarm chat whatever the switch says: the
operator proving the token and the chat, not an all-clear. --chats lists
the chats in the updates Telegram holds for the alarm bot (getUpdates
without an offset: nothing is confirmed, nothing forgotten), to read the
new group's id once someone has written in it.

    python manage.py alarm
    python manage.py alarm --send
    python manage.py alarm --test
    python manage.py alarm --chats
"""
from django.core.management.base import BaseCommand

TEST_TITLE = ("Sauron alarm — test: this chat will hear about critical "
              "problems only")


class Command(BaseCommand):
    help = ("Print what the alarm bot sees now. Sends nothing unless "
            "--send (one sentinel pass) or --test (one test message).")

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group()
        group.add_argument(
            "--send", action="store_true",
            help="run one sentinel pass: dedupe, messages, memory")
        group.add_argument(
            "--test", action="store_true",
            help="send one test message to the alarm chat")
        group.add_argument(
            "--chats", action="store_true",
            help="list the chats the alarm bot has been written from")

    def handle(self, *args, **opts):
        from bot_program import alarm
        from bot_program import telegram_eye as eye
        from django.utils import timezone
        if opts.get("chats"):
            return self._chats(alarm)
        now = timezone.now()
        on = alarm.enabled()
        token, chat, why = alarm.config()
        self.stdout.write(f"Alarm bot · {eye.when(now)}")
        self.stdout.write(
            f"Switch: {'on' if on else 'off'}"
            + ("" if on else " (manage.py component on telegram_alarm)"))
        self.stdout.write(f"Configuration: refused — {why}" if why else
                          f"Configuration: ready — token set, chat {chat}")
        if opts.get("test"):
            if why:
                self.stdout.write("Not sent: the configuration is refused.")
                return
            sent = alarm._deliver(token, chat, eye.Reply(
                alarm.MARK, TEST_TITLE,
                ["Sent by hand with manage.py alarm --test.",
                 "Commands here: /status and /stopall.",
                 f"At: {eye.when(now)}"]))
            self.stdout.write("Test message: " + (
                "delivered" if sent
                else "NOT delivered (the worker log has Telegram's words)"))
            return
        if opts.get("send"):
            if not on:
                self.stdout.write("Not sent: the switch is off.")
                return
            result = alarm.sentinel(now=now)
            if result.get("idle"):
                self.stdout.write(f"Nothing done: {result['idle']}.")
                return
            if result.get("skipped"):
                self.stdout.write(f"Not sent: {result['skipped']}.")
                return
            self.stdout.write(
                f"Problems: {result.get('problems', 0)} · due: "
                f"{result.get('due', 0)} · messages sent: "
                f"{result.get('sent', 0)} · not delivered: "
                f"{result.get('failed', 0)}")
            return
        found = alarm.problems(now)
        self.stdout.write(f"Critical problems now: {len(found)}")
        for a in found:
            self.stdout.write(f"  [{a.kind}] {a.title}  ({a.key})")
        self.stdout.write("Read only: nothing was sent (--send runs one "
                          "pass; --test sends one message; Morgul's "
                          "criticals are relayed after each Morgul run).")

    def _chats(self, alarm):
        import os
        if not os.getenv(alarm.TOKEN_ENV, "").strip():
            self.stdout.write(f"{alarm.TOKEN_ENV} is not set.")
            return
        rows = alarm.seen_chats()
        if not rows:
            self.stdout.write("No chat seen: write any message in the new "
                              "group (a /status will do), then run this "
                              "again.")
            return
        for chat_id, kind, title in rows:
            self.stdout.write(f"{chat_id}  {kind}  {title}")
        self.stdout.write(f"Put the group's id in .env as {alarm.CHAT_ENV}, "
                          f"then ./deploy/dc up -d.")
