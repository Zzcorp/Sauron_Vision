"""Announcements to the platform's Telegram group (core/announcements.py):
the release notes the viewers read, in the house style, with the lore.

Writes to Telegram. A release goes to a chat once; --force sends it again.

    python manage.py announce list                        # what can be sent
    python manage.py announce october_turn --dry-run      # print it, send nothing
    python manage.py announce october_turn                # send it to the platform chat
    python manage.py announce october_turn --chat -1001234567890   # another chat
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = ("Send a release announcement to the platform's Telegram chat, "
            "in the house style; --dry-run prints it.")

    def add_arguments(self, parser):
        parser.add_argument("name", help="an announcement, or `list`")
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--chat", default=None,
                            help="a chat id other than TELEGRAM_CHAT_ID")
        parser.add_argument("--force", action="store_true",
                            help="send again to a chat that already had it")

    def handle(self, *args, **opts):
        from core import announcements as A
        name = opts["name"]
        if name == "list":
            for key, a in A.ANNOUNCEMENTS.items():
                self.stdout.write(f"{key:<16} {a['title']}")
            return
        if name not in A.ANNOUNCEMENTS:
            self.stdout.write(f"no announcement {name!r}; one of: "
                              + ", ".join(sorted(A.ANNOUNCEMENTS)))
            return
        if opts["dry_run"]:
            text = A.render(name)
            self.stdout.write(text)
            self.stdout.write(f"\n-- {len(text)} characters of HTML, nothing "
                              f"sent")
            return
        out = A.send(name, chat=opts["chat"], force=opts["force"])
        self.stdout.write(f"{name} -> chat {out['chat'] or '—'}: "
                          f"{out['outcome'].upper()} — {out['why']}")
