"""A SHARED CHAT'S DIGEST IS CHOSEN, NOT DRAWN (2026-10-24).

The 07:00 and 17:00 UTC digests (pipeline_digest: alerts.tasks
send_morning_digest and send_eod_digest) post one digest per Telegram
chat. A chat several active users share got the digest of whichever of
them an UNORDERED query returned first, and that digest shows the user's
real eToro equity, cash and used margin to everyone in the chat.

Now the users are walked in a fixed order (alerts.scheduled_digests
.digest_users): staff and superusers first, each group by id. A shared
chat gets a staff member's digest when one shares it (the lowest id),
else the lowest-id user's; the digest names whose account it is ("User:
<username>", alerts/digest_book.owner_line). A chat of one user, and the
bell of every user, are unchanged.

Run with:  python manage.py test tests.test_shared_chat_digest
"""
import os
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase

ENV = {"TELEGRAM_BOT_TOKEN": "123456:TEST-shared-chat", "DOMAIN": ""}
SHARED = "-4000000077"


def _ok():
    return MagicMock(ok=True, status_code=200, text='{"ok":true}')


def _user(name, chat, *, staff=False, superuser=False, active=True):
    from alerts.models import UserNotificationPrefs
    u = User.objects.create(username=name, is_staff=staff,
                            is_superuser=superuser, is_active=active)
    UserNotificationPrefs.objects.create(user=u, telegram_chat_id=chat)
    return u


def _named(kind):
    def build(user=None):
        name = user.username if user is not None else "nobody"
        return {"type": kind, "summary": [f"User: {name}"], "sections": {}}
    return build


class TheSharedChatTests(TestCase):

    def setUp(self):
        cache.clear()
        env = patch.dict(os.environ, ENV)
        env.start()
        self.addCleanup(env.stop)

    def run_digests(self):
        """{kind: {chat: text}} for one morning and one end-of-day run."""
        from alerts.tasks import send_eod_digest, send_morning_digest
        out = {}
        for task, kind in ((send_morning_digest, "morning_brief"),
                           (send_eod_digest, "end_of_day")):
            with patch("requests.post", return_value=_ok()) as post, \
                    patch("alerts.scheduled_digests.generate_morning_digest",
                          side_effect=_named(kind)), \
                    patch("alerts.scheduled_digests.generate_eod_digest",
                          side_effect=_named(kind)), \
                    patch("ai_agents.next_steps.extract"):
                task.__wrapped__.__wrapped__()  # past the component gate
            out[kind] = {c.kwargs["json"]["chat_id"]: c.kwargs["json"]["text"]
                         for c in post.call_args_list}
        return out

    def test_the_order_is_staff_first_then_by_id(self):
        from alerts.scheduled_digests import digest_users
        a = _user("sc_a", SHARED)
        b = _user("sc_b", SHARED, staff=True)
        c = _user("sc_c", "")
        d = _user("sc_d", SHARED, superuser=True)
        _user("sc_gone", SHARED, staff=True, active=False)
        qs = digest_users()
        self.assertTrue(qs.ordered)
        self.assertEqual(list(qs), [b, d, a, c])

    def test_a_shared_chat_gets_the_lowest_id_staff_members_digest(self):
        _user("sc_first", SHARED)
        _user("sc_staff_low", SHARED, staff=True)
        _user("sc_staff_high", SHARED, staff=True)
        for kind, texts in self.run_digests().items():
            with self.subTest(kind):
                self.assertEqual(list(texts), [SHARED])
                self.assertIn("User: sc_staff_low", texts[SHARED])

    def test_a_superuser_counts_as_staff(self):
        _user("sc_plain", SHARED)
        _user("sc_root", SHARED, superuser=True)
        for kind, texts in self.run_digests().items():
            with self.subTest(kind):
                self.assertIn("User: sc_root", texts[SHARED])

    def test_without_staff_the_lowest_id_user_speaks_for_the_chat(self):
        low = _user("sc_low", SHARED)
        _user("sc_high", SHARED)
        # An unordered read is free to return the newest row first.
        reversed_qs = User.objects.filter(is_active=True).order_by("-pk")
        with patch.object(User.objects, "filter",
                          return_value=reversed_qs):
            texts = self.run_digests()
        for kind in texts:
            with self.subTest(kind):
                self.assertIn(f"User: {low.username}", texts[kind][SHARED])

    def test_a_chat_of_one_and_every_bell_are_unchanged(self):
        from alerts.models import Notification
        _user("sc_solo", "-4000000088")
        _user("sc_pair_a", SHARED)
        _user("sc_pair_b", SHARED, staff=True)
        texts = self.run_digests()
        for kind in texts:
            with self.subTest(kind):
                self.assertIn("User: sc_solo", texts[kind]["-4000000088"])
        # The bell is per user: each reads their own digest.
        for name in ("sc_solo", "sc_pair_a", "sc_pair_b"):
            bodies = list(Notification.objects.filter(
                user__username=name).values_list("body", flat=True))
            self.assertEqual(len(bodies), 2)
            self.assertTrue(all(f"User: {name}" in b for b in bodies))
