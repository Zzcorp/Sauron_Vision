"""The weekly letter, redesigned (2026-09-29).

The operator's decisions, pinned:
  * ONE WEEKLY LETTER: the Saturday review is the edition, READY and
    scheduled for the next Sunday 08:00 Europe/Paris (DST-correct), the
    staff told at once on the bell and on Telegram; an ad-hoc edition is
    written by a Celery task, never inside the admin's POST.
  * THE AUDIENCE: active, an email, "Weekly newsletter" on, the profile's
    one channel ("none" nothing, "telegram" the user's own chat, "email"
    and "discord" by email); prefs created with the defaults when missing.
  * A REAL EMAIL: text and HTML, absolute links only, List-Unsubscribe
    and its one-click twin, the brand once in the subject, the markdown
    rendered and escaped.
  * UNSUBSCRIBE: a signed token, a page that asks, a POST (the mail
    client's one-click POST too) that turns the letter off; a bad token
    is a 400.
  * A RELIABLE SEND: a ledger row per recipient, batches over one
    connection, a failure recorded and retried (3 attempts at most), a
    delivered row never sent again, "sent" / "failed" by the rules, and a
    row another worker holds is left alone.
  * The admin page, the archive, and the wiring (the beat entry, the
    switch, the route).

Run with:  python manage.py test tests.test_newsletter
"""
import os
import re
import smtplib
from datetime import datetime, timedelta
from datetime import timezone as dt_tz
from unittest import mock

from django.contrib.auth.models import User
from django.core import mail
from django.core.cache import cache
from django.core.mail.backends.locmem import EmailBackend as LocMemBackend
from django.test import Client, TestCase, override_settings
from django.utils import timezone

DOMAIN = "letters.sauron.test"
TOKEN = "123456:newsletter-test-token"
ENV = {"TELEGRAM_BOT_TOKEN": TOKEN, "TELEGRAM_CHAT_ID": "-100999",
       "DOMAIN": DOMAIN}
MAIL = dict(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
            DEFAULT_FROM_EMAIL="letters@sauron.test")
LETTER = ("# Market Overview\n\n"
          "**Risk** on, rates_up & golden_cross; watch <script>alert(1)"
          "</script> closely.\n"
          "- EURUSD *holds* 1.0850\n"
          "- Gold waits\n\n"
          "Read [the briefing](/briefing/) and [the note](https://x.io/n).\n"
          "\n## Calls\n```json\n"
          '{"calls": [{"symbol": "EURUSD", "direction": "up", '
          '"horizon_hours": 72, "confidence": 0.6}]}\n```\n')


class BouncingBackend(LocMemBackend):
    """locmem, but an address containing "bounce" is refused by the
    server, and every open() is counted (one connection per batch)."""
    opened = 0

    def open(self):
        type(self).opened += 1
        return super().open()

    def send_messages(self, messages):
        for m in messages:
            if any("bounce" in r for r in m.recipients()):
                raise smtplib.SMTPRecipientsRefused(
                    {r: (550, b"5.1.1 no such user") for r in
                     m.recipients()})
        return super().send_messages(messages)


class UnreachableBackend(LocMemBackend):
    def open(self):
        raise OSError("connection refused by smtp.sauron.test:587")


def _ok():
    return mock.MagicMock(ok=True, status_code=200, text='{"ok":true}')


def _refused():
    return mock.MagicMock(ok=False, status_code=403,
                          text="Forbidden: bot was blocked by the user")


def _reader(name, *, channel="email", chat="", opted=True, email=True,
            active=True, prefs=True, staff=False, superuser=False):
    from alerts.models import UserNotificationPrefs
    from portfolio.trader_profile import TraderProfile
    # No password: hashing one costs a PBKDF2 run per reader, and
    # force_login needs none.
    u = User.objects.create(
        username=name, email=f"{name}@readers.test" if email is True
        else (email or ""), is_active=active, is_staff=staff or superuser,
        is_superuser=superuser)
    if prefs:
        UserNotificationPrefs.objects.create(
            user=u, telegram_chat_id=chat,
            receive_weekly_newsletter=opted)
    if channel is not None:
        TraderProfile.objects.create(user=u, notify_channel=channel)
    return u


def _edition(**kw):
    from alerts.models import Newsletter
    fields = dict(title="Weekly Market Report", frequency="weekly",
                  status="approved", content_markdown=LETTER)
    fields.update(kw)
    return Newsletter.objects.create(**fields)


def _switch(key, on=True):
    from core.platform_control import PlatformComponent
    PlatformComponent.objects.update_or_create(
        key=key, defaults={"name": key, "category": "pipeline",
                           "is_enabled": on})


class _Base(TestCase):
    def setUp(self):
        cache.clear()
        self.env = mock.patch.dict(os.environ, ENV)
        self.env.start()
        self.addCleanup(self.env.stop)
        BouncingBackend.opened = 0


# ── the renderer ─────────────────────────────────────────────────────────

class RendererTests(_Base):
    def md(self, text):
        from core.templatetags.sauron_tags import newsletter_md
        return str(newsletter_md(text))

    def test_headings_lists_bold_links_render(self):
        html = self.md("# Title\n### Sub\n- one **two**\n1. first\n"
                       "[page](/briefing/) [ext](https://x.io/a_b)")
        self.assertIn('<h2 class="nl-h2"', html)
        self.assertIn('<h3 class="nl-h3"', html)
        self.assertIn('<ul class="nl-ul"', html)
        self.assertIn('<ol class="nl-ol"', html)
        self.assertIn('<strong style="font-weight:700;">two</strong>', html)
        self.assertIn(f'href="https://{DOMAIN}/briefing/"', html)
        self.assertIn('href="https://x.io/a_b"', html)

    def test_everything_is_escaped_first(self):
        html = self.md("<script>alert(1)</script> & <b>x</b>")
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)
        self.assertIn("&amp;", html)
        self.assertNotIn("<b>", html)

    def test_only_https_and_same_site_links_are_followed(self):
        html = self.md("[a](javascript:alert(1)) [b](//evil.io/x) "
                       "[c](/\\evil.io) [d](http://plain.io) [e](data:x)")
        self.assertNotIn("<a ", html)
        for label in "abcde":
            self.assertIn(label, html)

    def test_no_relative_link_without_a_domain(self):
        with mock.patch.dict(os.environ, {"DOMAIN": ""}):
            html = self.md("[the briefing](/briefing/)")
        self.assertNotIn("href", html)
        self.assertIn("the briefing", html)

    def test_emphasis_never_inside_a_word_and_code_is_left_alone(self):
        html = self.md("rates_up and golden_cross, 5 * 3, *now* _here_ "
                       "`a **b** _c_`")
        self.assertIn("rates_up and golden_cross, 5 * 3", html)
        self.assertIn("<em>now</em>", html)
        self.assertIn("<em>here</em>", html)
        self.assertIn(">a **b** _c_</code>", html)

    def test_fenced_code_and_rules(self):
        html = self.md("```\n<x> **y**\n```\n---\ntext")
        self.assertIn('<pre class="nl-pre"', html)
        self.assertIn("&lt;x&gt; **y**", html)
        self.assertIn('<hr class="nl-hr"', html)

    def test_the_plain_twin(self):
        from core.templatetags.sauron_tags import newsletter_plain
        text = newsletter_plain("# Title\n- **one** & *two*\n"
                                "[page](/briefing/) [ext](https://x.io)")
        self.assertEqual(text.split("\n"), [
            "TITLE", "", "• one & two",
            f"page (https://{DOMAIN}/briefing/) ext (https://x.io)"])
        with mock.patch.dict(os.environ, {"DOMAIN": ""}):
            self.assertEqual(newsletter_plain("[page](/briefing/)"), "page")

    def test_the_letter_prose_drops_the_calls_block(self):
        from alerts.newsletter_service import letter_prose
        prose = letter_prose(LETTER)
        self.assertNotIn('"calls"', prose)
        self.assertNotIn("## Calls", prose)
        self.assertIn("Market Overview", prose)
        self.assertIn(f"](https://{DOMAIN}/briefing/)", prose)
        # A link elsewhere is said, never followed (the platform's rule
        # for model text, monday_plan.readable).
        self.assertIn("the note (https://x.io/n)", prose)


# ── the audience ─────────────────────────────────────────────────────────

class AudienceTests(_Base):
    def people(self, newsletter=None):
        from alerts.newsletter_service import audience
        return {r.user.username: (r.channel, r.address, r.skip)
                for r in audience(newsletter)}

    def test_only_active_opted_in_users_with_an_email(self):
        _reader("in")
        _reader("out", opted=False)
        _reader("asleep", active=False)
        _reader("nomail", email="")
        _reader("blank", email="   ")
        self.assertEqual(set(self.people()), {"in"})

    def test_the_profile_channel_decides(self):
        _reader("by_mail", channel="email")
        _reader("by_discord", channel="discord")
        _reader("by_tg", channel="telegram", chat="555")
        _reader("by_none", channel="none")
        people = self.people()
        self.assertEqual(people["by_mail"][:2],
                         ("email", "by_mail@readers.test"))
        self.assertEqual(people["by_discord"][:2],
                         ("email", "by_discord@readers.test"))
        self.assertEqual(people["by_tg"], ("telegram", "555", ""))
        self.assertNotIn("by_none", people)

    def test_telegram_without_a_chat_is_listed_skipped(self):
        _reader("no_chat", channel="telegram", chat="")
        channel, _addr, skip = self.people()["no_chat"]
        self.assertEqual(channel, "telegram")
        self.assertIn("no Telegram chat id", skip)

    def test_a_shared_chat_is_sent_once(self):
        _reader("first", channel="telegram", chat="-100group")
        _reader("second", channel="telegram", chat="-100group")
        people = self.people()
        self.assertEqual(people["first"][2], "")
        self.assertIn("sent there once", people["second"][2])

    def test_missing_prefs_are_created_with_the_model_defaults(self):
        from alerts.models import UserNotificationPrefs
        _reader("fresh", prefs=False)
        self.assertIn("fresh", self.people())
        prefs = UserNotificationPrefs.objects.get(user__username="fresh")
        self.assertTrue(prefs.receive_weekly_newsletter)

    def test_a_user_without_a_profile_has_the_model_default_channel(self):
        _reader("noprofile", channel=None, chat="777")
        self.assertEqual(self.people()["noprofile"],
                         ("telegram", "777", ""))

    def test_an_investor_login_never_receives_it(self):
        from portfolio.investor_models import InvestorAccess
        owner = _reader("owner")
        investor = _reader("investor")
        InvestorAccess.objects.create(investor=investor, owner=owner)
        self.assertEqual(set(self.people()), {"owner"})

    def test_an_edition_without_a_channel_skips_its_users(self):
        _reader("tg", channel="telegram", chat="1")
        _reader("em", channel="email")
        nl = _edition(send_telegram=False)
        people = self.people(nl)
        self.assertIn("does not go out on Telegram", people["tg"][2])
        self.assertEqual(people["em"][2], "")

    def test_the_counts_in_words(self):
        from alerts.newsletter_service import (audience, audience_counts,
                                               reach_words)
        _reader("a")
        _reader("b", channel="telegram", chat="2")
        _reader("c", channel="telegram")
        counts = audience_counts(audience())
        self.assertEqual(counts, {"people": 2, "email": 1, "telegram": 1,
                                  "skipped": 1})
        self.assertEqual(reach_words(counts),
                         "will reach 2 people: 1 by email, 1 by Telegram "
                         "(1 skipped)")


# ── unsubscribe ──────────────────────────────────────────────────────────

class UnsubscribeTests(_Base):
    def setUp(self):
        super().setUp()
        from alerts.newsletter_service import unsubscribe_path
        self.user = _reader("leaver")
        self.path = unsubscribe_path(self.user)

    def prefs(self):
        from alerts.models import UserNotificationPrefs
        return UserNotificationPrefs.objects.get(user=self.user)

    def test_the_token_carries_the_user_and_is_signed(self):
        from alerts.newsletter_service import (unsubscribe_token,
                                               user_for_token)
        token = unsubscribe_token(self.user)
        self.assertEqual(user_for_token(token), self.user)
        self.assertIsNone(user_for_token(token[:-2] + "xx"))
        self.assertIsNone(user_for_token("garbage"))
        from django.core import signing
        other_salt = signing.dumps({"u": self.user.pk}, salt="another")
        self.assertIsNone(user_for_token(other_salt))

    def test_get_asks_and_changes_nothing(self):
        r = self.client.get(self.path)
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertIn('<form method="post">', body)
        self.assertIn("Unsubscribe", body)
        self.assertTrue(self.prefs().receive_weekly_newsletter)

    def test_post_turns_the_letter_off(self):
        r = self.client.post(self.path)
        self.assertEqual(r.status_code, 200)
        self.assertIn("You are unsubscribed", r.content.decode())
        self.assertFalse(self.prefs().receive_weekly_newsletter)
        # Then the page says so, and the audience no longer has them.
        self.assertIn("You are not subscribed",
                      self.client.get(self.path).content.decode())
        from alerts.newsletter_service import audience
        self.assertEqual(audience(), [])

    def test_the_one_click_post_needs_no_csrf_token_and_no_login(self):
        client = Client(enforce_csrf_checks=True)
        r = client.post(self.path, data="List-Unsubscribe=One-Click",
                        content_type="application/x-www-form-urlencoded")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(self.prefs().receive_weekly_newsletter)

    def test_a_bad_token_is_a_400_never_a_500(self):
        for token in ("garbage", self.path.split("/")[-2][:-3] + "abc",
                      "a:b:c"):
            r = self.client.post(f"/newsletter/unsubscribe/{token}/")
            self.assertEqual(r.status_code, 400, token)
            self.assertIn("This link does not work", r.content.decode())
        self.assertTrue(self.prefs().receive_weekly_newsletter)

    def test_a_deleted_user_is_a_400(self):
        self.user.delete()
        self.assertEqual(self.client.get(self.path).status_code, 400)

    def test_other_methods_are_refused(self):
        self.assertEqual(self.client.put(self.path).status_code, 405)


# ── the email ────────────────────────────────────────────────────────────

@override_settings(**MAIL)
class EmailTests(_Base):
    def build(self, **kw):
        from alerts.newsletter_service import build_email
        self.user = (User.objects.filter(username="mailreader").first()
                     or _reader("mailreader"))
        self.nl = _edition(**kw)
        return build_email(self.nl, self.user)

    def test_text_and_one_html_alternative(self):
        msg = self.build()
        self.assertEqual(msg.content_subtype, "plain")
        self.assertEqual(len(msg.alternatives), 1)
        self.assertEqual(msg.alternatives[0][1], "text/html")
        self.assertEqual(msg.from_email, "letters@sauron.test")
        self.assertEqual(msg.to, ["mailreader@readers.test"])

    def test_the_subject_names_the_brand_once(self):
        msg = self.build(title="Sauron Vision Weekly Review — Week of 26 Sep")
        self.assertEqual(msg.subject,
                         "Sauron Vision — Weekly Review — Week of 26 Sep")
        self.assertEqual(msg.subject.lower().count("sauron"), 1)
        self.assertEqual(self.build(title="Weekly Market Report").subject,
                         "Sauron Vision — Weekly Market Report")

    def test_list_unsubscribe_headers_point_at_the_personal_link(self):
        from alerts.newsletter_service import unsubscribe_token
        msg = self.build()
        link = (f"https://{DOMAIN}/newsletter/unsubscribe/"
                f"{unsubscribe_token(self.user)}/")
        self.assertEqual(msg.extra_headers["List-Unsubscribe"], f"<{link}>")
        self.assertEqual(msg.extra_headers["List-Unsubscribe-Post"],
                         "List-Unsubscribe=One-Click")
        html = msg.alternatives[0][0]
        self.assertIn(f'href="{link}"', html)
        self.assertIn(link, msg.body)
        # The token in the header unsubscribes this reader.
        path = link[len(f"https://{DOMAIN}"):]
        self.client.post(path)
        self.user.notification_prefs.refresh_from_db()
        self.assertFalse(self.user.notification_prefs
                         .receive_weekly_newsletter)

    def test_every_link_is_absolute(self):
        msg = self.build()
        html = msg.alternatives[0][0]
        hrefs = re.findall(r'href="([^"]*)"', html)
        self.assertTrue(hrefs)
        for href in hrefs:
            self.assertTrue(href.startswith("https://"), href)
        self.assertIn(f"https://{DOMAIN}/newsletters/{self.nl.pk}/", html)
        self.assertIn(f"https://{DOMAIN}/notifications/settings/", html)
        self.assertNotRegex(msg.body, r"(?<![\w/.:])/(?:newsletters|"
                                      r"notifications|briefing)/")

    def test_without_a_domain_the_links_are_omitted_not_relative(self):
        with mock.patch.dict(os.environ, {"DOMAIN": ""}):
            msg = self.build()
        html = msg.alternatives[0][0]
        self.assertEqual(re.findall(r'href="([^"]*)"', html), [])
        self.assertNotIn("List-Unsubscribe", msg.extra_headers)
        self.assertIn("untick &ldquo;Weekly newsletter&rdquo;", html)
        self.assertIn('untick "Weekly newsletter"', msg.body)

    def test_the_markdown_is_rendered_and_escaped(self):
        msg = self.build()
        html = msg.alternatives[0][0]
        self.assertIn('<h2 class="nl-h2"', html)
        self.assertIn("<strong", html)
        self.assertIn('<li class="nl-li"', html)
        self.assertNotIn("<script>alert(1)", html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)
        self.assertNotIn('"calls"', html)
        self.assertNotIn("**", html)
        # The text part is text: no tags, no entities.
        self.assertIn("MARKET OVERVIEW", msg.body)
        self.assertIn("Risk on, rates_up & golden_cross", msg.body)
        self.assertNotIn("&amp;", msg.body)
        self.assertNotIn("<h2", msg.body)

    def test_the_mail_client_contract(self):
        html = self.build().alternatives[0][0]
        self.assertIn('<meta name="viewport"', html)
        self.assertIn('<meta name="color-scheme" content="light dark">', html)
        self.assertIn('<meta name="supported-color-schemes" '
                      'content="light dark">', html)
        self.assertIn("max-width:600px", html)
        self.assertIn("#00e868", html)
        self.assertIn("SAURON VISION", html)
        self.assertIn("prefers-color-scheme: dark", html)
        # The body text is never pure black, the paper never black.
        self.assertNotRegex(html, r"color:\s*#000(?:000)?\b")
        self.assertNotRegex(html, r"background:\s*#000(?:000)?\b")


# ── the ledger ───────────────────────────────────────────────────────────

@override_settings(**MAIL)
class LedgerTests(_Base):
    def send(self, nl, **kw):
        from alerts.newsletter_service import send_newsletter
        with mock.patch("requests.post", return_value=_ok()) as post:
            out = send_newsletter(nl, **kw)
        return out, post

    def rows(self, nl):
        from alerts.models import NewsletterDelivery
        return {d.user.username: d for d in
                NewsletterDelivery.objects.filter(newsletter=nl)
                .select_related("user")}

    def test_pending_to_sent_across_both_channels(self):
        from alerts.models import Notification
        _reader("m1")
        _reader("m2", channel="discord")
        _reader("t1", channel="telegram", chat="901")
        nl = _edition()
        out, post = self.send(nl)
        self.assertEqual(out["status"], "sent")
        self.assertEqual(out["recipients"], 3)
        self.assertEqual((out["email"], out["telegram"]), (2, 1))
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(len(post.call_args_list), 1)
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["chat_id"], "901")
        self.assertTrue(payload["text"].startswith(
            "<b>\U0001F4F0 Sauron Vision · Weekly Market Report</b>"))
        self.assertEqual(payload["reply_markup"]["inline_keyboard"][0][0]
                         ["url"], f"https://{DOMAIN}/newsletters/{nl.pk}/")
        for d in self.rows(nl).values():
            self.assertEqual((d.status, d.attempts), ("sent", 1))
            self.assertIsNotNone(d.sent_at)
        nl.refresh_from_db()
        self.assertEqual(nl.status, "sent")
        self.assertEqual(nl.recipients_count, 3)
        self.assertIsNotNone(nl.sent_at)
        self.assertIsNone(nl.send_started_at)
        bells = Notification.objects.filter(notification_type="newsletter")
        self.assertEqual(bells.count(), 3)
        self.assertEqual({b.url for b in bells}, {f"/newsletters/{nl.pk}/"})

    @override_settings(EMAIL_BACKEND="tests.test_newsletter.BouncingBackend")
    def test_a_refused_recipient_is_recorded_and_the_others_go(self):
        _reader("good1")
        _reader("bounce_me", email="bounce@readers.test")
        _reader("good2")
        nl = _edition()
        with self.assertLogs("alerts.newsletter_service", "WARNING") as cm:
            out, _post = self.send(nl)
        self.assertIn("1 delivery failed", "\n".join(cm.output))
        rows = self.rows(nl)
        self.assertEqual(rows["good1"].status, "sent")
        self.assertEqual(rows["good2"].status, "sent")
        self.assertEqual(rows["bounce_me"].status, "failed")
        self.assertIn("no such user", rows["bounce_me"].error)
        self.assertEqual(len(mail.outbox), 2)
        # A retry is left: the edition stays "sending", its lease free,
        # and it is already readable in the archive.
        nl.refresh_from_db()
        self.assertEqual(out["status"], "sending")
        self.assertEqual(nl.status, "sending")
        self.assertIsNone(nl.send_started_at)
        self.assertIsNotNone(nl.sent_at)
        self.assertEqual(nl.recipients_count, 2)
        self.assertIn("tried again", nl.last_error)

    @override_settings(EMAIL_BACKEND="tests.test_newsletter.BouncingBackend")
    def test_a_rerun_never_resends_and_stops_at_three_attempts(self):
        from alerts.newsletter_service import due_newsletter_ids
        _reader("kept")
        _reader("bounce_me", email="bounce@readers.test")
        nl = _edition()
        with self.assertLogs("alerts.newsletter_service", "WARNING"):
            self.send(nl)
        self.assertIn(nl.pk, due_newsletter_ids())
        for attempt in (2, 3):
            with self.assertLogs("alerts.newsletter_service", "WARNING"):
                self.send(nl, scheduled=True)
            self.assertEqual(self.rows(nl)["bounce_me"].attempts, attempt)
        # "kept" received it once, whatever the reruns did.
        self.assertEqual([m.to for m in mail.outbox], [["kept@readers.test"]])
        self.assertEqual(self.rows(nl)["kept"].attempts, 1)
        nl.refresh_from_db()
        self.assertEqual(nl.status, "sent")
        self.assertEqual(nl.recipients_count, 1)
        self.assertIn("after 3 attempts", nl.last_error)
        self.assertNotIn(nl.pk, due_newsletter_ids())
        out, _post = self.send(nl, scheduled=True)
        self.assertEqual(out["status"], "skipped")
        self.assertEqual(self.rows(nl)["bounce_me"].attempts, 3)

    @override_settings(EMAIL_BACKEND="tests.test_newsletter.BouncingBackend")
    def test_every_delivery_failing_is_failed(self):
        _reader("b1", email="bounce1@readers.test")
        nl = _edition()
        for _ in range(3):
            with self.assertLogs("alerts.newsletter_service", "WARNING"):
                out, _post = self.send(nl)
        self.assertEqual(out["status"], "failed")
        nl.refresh_from_db()
        self.assertEqual((nl.status, nl.recipients_count), ("failed", 0))
        self.assertIsNone(nl.sent_at)

    def test_nobody_to_send_to_is_failed_not_sent(self):
        _reader("unsubscribed", opted=False)
        nl = _edition()
        with self.assertLogs("alerts.newsletter_service", "WARNING"):
            out, _post = self.send(nl)
        nl.refresh_from_db()
        self.assertEqual((out["status"], nl.status), ("failed", "failed"))
        self.assertEqual(nl.recipients_count, 0)
        self.assertIn("nobody receives it", nl.last_error)

    def test_skipped_recipients_are_recorded(self):
        _reader("mail")
        _reader("chatless", channel="telegram")
        nl = _edition()
        out, _post = self.send(nl)
        self.assertEqual((out["status"], out["skipped"]), ("sent", 1))
        self.assertEqual(self.rows(nl)["chatless"].status, "skipped")
        from alerts.newsletter_service import delivery_words, ledger_counts
        self.assertEqual(delivery_words(ledger_counts([nl.pk])[nl.pk]),
                         "1 sent by email, 0 by Telegram, 0 failed, "
                         "1 skipped")

    @override_settings(EMAIL_BACKEND="tests.test_newsletter.BouncingBackend")
    def test_one_connection_per_batch_of_fifty(self):
        from alerts.newsletter_service import EMAIL_BATCH
        from portfolio.trader_profile import TraderProfile
        self.assertEqual(EMAIL_BATCH, 50)
        users = User.objects.bulk_create([
            User(username=f"bulk{i:03d}", email=f"bulk{i:03d}@readers.test")
            for i in range(120)])
        users = list(User.objects.filter(username__startswith="bulk"))
        TraderProfile.objects.bulk_create([
            TraderProfile(user=u, notify_channel="email") for u in users])
        nl = _edition()
        out, _post = self.send(nl)
        self.assertEqual(out["email"], 120)
        self.assertEqual(len(mail.outbox), 120)
        self.assertEqual(BouncingBackend.opened, 3)
        # One message per recipient: the unsubscribe link is personal.
        links = {m.extra_headers["List-Unsubscribe"] for m in mail.outbox}
        self.assertEqual(len(links), 120)

    @override_settings(EMAIL_BACKEND="tests.test_newsletter.UnreachableBackend")
    def test_an_unreachable_server_fails_the_batch_with_its_reason(self):
        _reader("r1")
        _reader("r2")
        nl = _edition()
        with self.assertLogs("alerts.newsletter_service", "WARNING"):
            out, _post = self.send(nl)
        self.assertEqual(out["failed"], 2)
        for d in self.rows(nl).values():
            self.assertIn("could not be reached", d.error)
            self.assertEqual(d.attempts, 1)

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.console.EmailBackend")
    def test_the_console_backend_is_not_a_delivery(self):
        _reader("console_reader")
        nl = _edition()
        with self.assertLogs("alerts.newsletter_service", "WARNING"):
            out, _post = self.send(nl)
        self.assertEqual(out["recipients"], 0)
        self.assertIn("EMAIL_HOST is empty",
                      self.rows(nl)["console_reader"].error)

    def test_telegram_without_a_bot_token_is_a_failure_said(self):
        _reader("tg", channel="telegram", chat="42")
        nl = _edition()
        with mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": ""}), \
                self.assertLogs("alerts.newsletter_service", "WARNING"):
            self.send(nl)
        self.assertEqual(self.rows(nl)["tg"].error,
                         "TELEGRAM_BOT_TOKEN is not set")

    def test_a_refused_telegram_message_is_failed_and_never_raises(self):
        from alerts.newsletter_service import send_newsletter
        _reader("tg", channel="telegram", chat="42")
        nl = _edition()
        with mock.patch("requests.post", return_value=_refused()), \
                self.assertLogs("alerts.channels.telegram_alert", "WARNING"):
            out = send_newsletter(nl)
        self.assertEqual((out["recipients"], out["failed"]), (0, 1))

    def test_the_telegram_text_is_english_escaped_one_mark(self):
        _reader("tg", channel="telegram", chat="42")
        nl = _edition(title="Rates <up> & away")
        _out, post = self.send(nl)
        text = post.call_args.kwargs["json"]["text"]
        self.assertEqual(post.call_args.kwargs["json"]["parse_mode"], "HTML")
        self.assertTrue(text.startswith(
            "<b>\U0001F4F0 Sauron Vision · Rates &lt;up&gt; &amp; away</b>"))
        self.assertEqual(text.count("\U0001F4F0"), 1)
        self.assertIn("&lt;script&gt;", text)
        self.assertNotIn("<script>", text)
        self.assertNotIn('"calls"', text)

    def test_a_reader_who_left_before_the_retry_is_skipped(self):
        from alerts.models import NewsletterDelivery, UserNotificationPrefs
        leaver = _reader("leaver")
        nl = _edition(status="sending", send_started_at=None)
        NewsletterDelivery.objects.create(newsletter=nl, user=leaver,
                                          channel="email", status="failed",
                                          attempts=1, error="timeout")
        UserNotificationPrefs.objects.filter(user=leaver).update(
            receive_weekly_newsletter=False)
        with self.assertLogs("alerts.newsletter_service", "WARNING"):
            self.send(nl, scheduled=True)
        row = self.rows(nl)["leaver"]
        self.assertEqual(row.status, "skipped")
        self.assertIn("no longer in the audience", row.error)
        self.assertEqual(mail.outbox, [])

    def test_a_channel_changed_between_attempts_follows_the_user(self):
        from alerts.models import NewsletterDelivery
        from portfolio.trader_profile import TraderProfile
        mover = _reader("mover", channel="telegram", chat="77")
        nl = _edition(status="sending", send_started_at=None)
        NewsletterDelivery.objects.create(newsletter=nl, user=mover,
                                          channel="telegram",
                                          status="failed", attempts=1)
        TraderProfile.objects.filter(user=mover).update(
            notify_channel="email")
        _out, post = self.send(nl, scheduled=True)
        post.assert_not_called()
        self.assertEqual(len(mail.outbox), 1)
        rows = NewsletterDelivery.objects.filter(newsletter=nl, user=mover)
        self.assertEqual([(d.channel, d.status) for d in rows],
                         [("email", "sent")])

    def test_a_row_another_worker_holds_is_left_alone(self):
        _reader("r")
        nl = _edition(status="sending",
                      send_started_at=timezone.now() - timedelta(minutes=5))
        out, post = self.send(nl)
        self.assertEqual(out, {"status": "skipped",
                               "reason": "another worker is sending it",
                               "recipients": 0})
        self.assertEqual(mail.outbox, [])
        post.assert_not_called()

    def test_an_abandoned_row_is_resumed_without_resending(self):
        from alerts.models import NewsletterDelivery
        from alerts.newsletter_service import due_newsletter_ids
        done = _reader("done")
        _reader("left")
        nl = _edition(status="sending", sent_at=timezone.now(),
                      send_started_at=timezone.now() - timedelta(minutes=45))
        NewsletterDelivery.objects.create(
            newsletter=nl, user=done, channel="email", status="sent",
            attempts=1, sent_at=timezone.now())
        self.assertIn(nl.pk, due_newsletter_ids())
        out, _post = self.send(nl, scheduled=True)
        self.assertEqual([m.to for m in mail.outbox], [["left@readers.test"]])
        self.assertEqual((out["status"], out["recipients"]), ("sent", 2))

    def test_the_claim_is_under_select_for_update(self):
        from alerts import newsletter_service as ns
        from alerts.models import Newsletter
        nl = _edition()
        real = Newsletter.objects.select_for_update
        with mock.patch.object(Newsletter.objects, "select_for_update",
                               side_effect=real) as sfu:
            claimed, why = ns.claim(nl.pk)
        sfu.assert_called_once()
        self.assertEqual((claimed.pk, why), (nl.pk, ""))
        nl.refresh_from_db()
        self.assertEqual(nl.status, "sending")
        self.assertIsNotNone(nl.send_started_at)
        # The second worker finds the lease and stops.
        self.assertEqual(ns.claim(nl.pk), (None,
                                           "another worker is sending it"))

    def test_a_sent_edition_is_never_sent_again(self):
        _reader("once")
        nl = _edition()
        self.send(nl)
        self.assertEqual(len(mail.outbox), 1)
        out, _post = self.send(nl)
        self.assertEqual(out["status"], "skipped")
        self.assertEqual(len(mail.outbox), 1)

    def test_an_explicit_send_of_a_failed_edition_gives_fresh_attempts(self):
        from alerts.models import NewsletterDelivery
        r = _reader("retry_me")
        nl = _edition(status="failed")
        NewsletterDelivery.objects.create(newsletter=nl, user=r,
                                          channel="email", status="failed",
                                          attempts=3, error="old")
        out, _post = self.send(nl)
        self.assertEqual(out["status"], "sent")
        self.assertEqual(self.rows(nl)["retry_me"].attempts, 1)

    def test_a_crash_marks_the_edition_failed_and_says_why(self):
        from alerts.newsletter_service import send_newsletter
        _reader("r")
        nl = _edition()
        with mock.patch("alerts.newsletter_service._run",
                        side_effect=RuntimeError("disk full")), \
                self.assertLogs("alerts.newsletter_service", "ERROR"), \
                self.assertRaises(RuntimeError):
            send_newsletter(nl)
        nl.refresh_from_db()
        self.assertEqual(nl.status, "failed")
        self.assertIn("disk full", nl.last_error)
        self.assertIsNone(nl.send_started_at)


# ── the schedule ─────────────────────────────────────────────────────────

class ScheduleTests(_Base):
    def at(self, *args):
        return datetime(*args, tzinfo=dt_tz.utc)

    def test_next_sunday_eight_in_paris_summer_and_winter(self):
        from alerts.newsletter_service import next_send_time
        # Summer time: 08:00 CEST is 06:00 UTC.
        self.assertEqual(next_send_time(self.at(2026, 10, 3, 10, 0)),
                         self.at(2026, 10, 4, 6, 0))
        # The clocks go back on Sunday 25 October 2026 at 03:00: that
        # Sunday's 08:00 is CET, 07:00 UTC.
        self.assertEqual(next_send_time(self.at(2026, 10, 24, 10, 0)),
                         self.at(2026, 10, 25, 7, 0))
        # And forward on Sunday 28 March 2027: 06:00 UTC again.
        self.assertEqual(next_send_time(self.at(2027, 3, 27, 10, 0)),
                         self.at(2027, 3, 28, 6, 0))

    def test_strictly_after(self):
        from alerts.newsletter_service import next_send_time
        # Sunday 07:00 Paris (05:00 UTC): the same morning.
        self.assertEqual(next_send_time(self.at(2026, 10, 4, 5, 0)),
                         self.at(2026, 10, 4, 6, 0))
        # Sunday 08:00 Paris exactly, or later: the next Sunday.
        self.assertEqual(next_send_time(self.at(2026, 10, 4, 6, 0)),
                         self.at(2026, 10, 11, 6, 0))

    def test_the_admin_input_is_paris_time(self):
        from alerts.newsletter_service import paris_input, parse_paris_input
        self.assertEqual(parse_paris_input("2026-10-04T08:00"),
                         self.at(2026, 10, 4, 6, 0))
        self.assertEqual(parse_paris_input("2026-12-06T08:00"),
                         self.at(2026, 12, 6, 7, 0))
        self.assertIsNone(parse_paris_input("next sunday"))
        self.assertEqual(paris_input(self.at(2026, 10, 4, 6, 0)),
                         "2026-10-04T08:00")

    def test_paris_words(self):
        from alerts.newsletter_service import paris_words
        self.assertEqual(paris_words(self.at(2026, 10, 25, 7, 0)),
                         "Sunday 25 October 2026 at 08:00 Paris time")


@override_settings(**MAIL)
class SendDueTests(_Base):
    def setUp(self):
        super().setUp()
        _switch("platform_master")
        _switch("newsletter_send")
        self.now = timezone.now()

    def run_due(self):
        from alerts.tasks import send_due_newsletters
        with mock.patch("alerts.tasks.send_newsletter_task.delay") as delay:
            out = send_due_newsletters()
        return out, [c.args[0] for c in delay.call_args_list], delay

    def test_a_due_edition_is_queued_the_others_are_not(self):
        due = _edition(status="ai_generated",
                       scheduled_for=self.now - timedelta(minutes=1))
        approved = _edition(status="approved",
                            scheduled_for=self.now - timedelta(hours=2))
        _edition(status="cancelled",
                 scheduled_for=self.now - timedelta(minutes=1))
        _edition(status="ai_generated",
                 scheduled_for=self.now + timedelta(hours=1))
        _edition(status="ai_generated", scheduled_for=None)
        _edition(status="draft", scheduled_for=self.now - timedelta(hours=1))
        _edition(status="sent", scheduled_for=self.now - timedelta(hours=1))
        retry = _edition(status="sending", send_started_at=None)
        _edition(status="sending",
                 send_started_at=self.now - timedelta(minutes=3))
        stuck = _edition(status="sending",
                         send_started_at=self.now - timedelta(minutes=31))
        out, queued, delay = self.run_due()
        self.assertEqual(sorted(queued),
                         sorted([due.pk, approved.pk, retry.pk, stuck.pk]))
        for call in delay.call_args_list:
            self.assertEqual(call.kwargs, {"scheduled": True})
        self.assertEqual(out, {"status": "ok", "due": 4, "queued": 4})

    def test_the_switch_off_sends_nothing(self):
        _switch("newsletter_send", on=False)
        _edition(status="ai_generated",
                 scheduled_for=self.now - timedelta(minutes=1))
        out, queued, _delay = self.run_due()
        self.assertEqual(queued, [])
        self.assertEqual(out["status"], "skipped")

    def test_the_whole_path_sends_a_due_edition(self):
        from alerts.tasks import send_due_newsletters, send_newsletter_task
        _reader("sunday_reader")
        nl = _edition(status="ai_generated",
                      scheduled_for=self.now - timedelta(minutes=1))
        cancelled = _edition(status="cancelled",
                             scheduled_for=self.now - timedelta(minutes=1))
        with mock.patch("alerts.tasks.send_newsletter_task.delay",
                        side_effect=lambda pk, **kw:
                        send_newsletter_task(pk, **kw)):
            send_due_newsletters()
        nl.refresh_from_db()
        cancelled.refresh_from_db()
        self.assertEqual(nl.status, "sent")
        self.assertEqual(cancelled.status, "cancelled")
        self.assertEqual(len(mail.outbox), 1)

    def test_a_queued_task_does_not_send_what_was_cancelled_or_moved(self):
        from alerts.tasks import send_newsletter_task
        _reader("r")
        cancelled = _edition(status="cancelled",
                             scheduled_for=self.now - timedelta(minutes=1))
        moved = _edition(status="ai_generated",
                         scheduled_for=self.now + timedelta(days=1))
        for nl in (cancelled, moved):
            out = send_newsletter_task(nl.pk, scheduled=True)
            self.assertEqual(out["status"], "skipped")
        self.assertEqual(mail.outbox, [])
        self.assertEqual(send_newsletter_task(999999)["status"], "skipped")

    def test_an_empty_due_edition_fails_instead_of_sending(self):
        from alerts.tasks import send_newsletter_task
        _reader("r")
        nl = _edition(status="ai_generated", content_markdown="  ",
                      scheduled_for=self.now - timedelta(minutes=1))
        send_newsletter_task(nl.pk, scheduled=True)
        nl.refresh_from_db()
        self.assertEqual(nl.status, "failed")
        self.assertIn("empty", nl.last_error)
        self.assertEqual(mail.outbox, [])


# ── the Saturday review is the week's letter ─────────────────────────────

class _Provider:
    def __init__(self, text):
        self.text = text
        self.seen = []

    def complete(self, **kw):
        self.seen.append(kw)
        return self.text, {"input_tokens": 100, "output_tokens": 200,
                           "cost_usd": 0.01}


SATURDAY = datetime(2026, 10, 3, 10, 0, tzinfo=dt_tz.utc)


class WeeklyReviewTests(_Base):
    def setUp(self):
        super().setUp()
        from alerts.models import UserNotificationPrefs
        from portfolio.trader_profile import TraderProfile
        self.staff = User.objects.create(username="operator",
                                         email="op@sauron.test",
                                         is_staff=True)
        TraderProfile.objects.create(user=self.staff,
                                     notify_channel="telegram")
        UserNotificationPrefs.objects.create(user=self.staff,
                                             telegram_chat_id="-100staff")
        self.reader = _reader("plain_reader")

    def review(self, text=LETTER, now=SATURDAY):
        from ai_agents.agents.weekly_reviewer import WeeklyReviewerAgent
        from ai_agents.tasks import generate_weekly_review
        provider = _Provider(text)
        with mock.patch.object(WeeklyReviewerAgent, "_get_provider",
                               lambda self: provider), \
                mock.patch("django.utils.timezone.now", return_value=now), \
                mock.patch("requests.post", return_value=_ok()) as post:
            result = generate_weekly_review.__wrapped__.__wrapped__()
        return result, post

    def test_the_review_is_scheduled_for_sunday_and_the_staff_told(self):
        from alerts.models import Newsletter, Notification
        result, post = self.review()
        nl = Newsletter.objects.get(pk=result["newsletter_id"])
        self.assertEqual(nl.status, "ai_generated")
        self.assertEqual(nl.frequency, "weekly")
        self.assertEqual(nl.title, "Weekly Review · week of 28 September 2026")
        self.assertEqual(nl.scheduled_for,
                         datetime(2026, 10, 4, 6, 0, tzinfo=dt_tz.utc))
        self.assertEqual(nl.content_markdown, LETTER)
        self.assertEqual(result["scheduled_for"], nl.scheduled_for.isoformat())
        # The bell: every staff user, nobody else.
        bells = Notification.objects.filter(notification_type="newsletter")
        self.assertEqual([b.user for b in bells], [self.staff])
        bell = bells.get()
        self.assertIn("Sunday 4 October 2026 at 08:00 Paris time", bell.body)
        self.assertEqual(bell.url, "/admin-dashboard/newsletters/")
        # Telegram: one house-style message to the staff chat.
        self.assertEqual(len(post.call_args_list), 1)
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["chat_id"], "-100staff")
        self.assertEqual(payload["parse_mode"], "HTML")
        text = payload["text"]
        self.assertTrue(text.startswith("<b>\U0001F4F0 Weekly letter ready"))
        self.assertIn("Goes out: Sunday 4 October 2026 at 08:00 Paris time",
                      text)
        self.assertIn(f"https://{DOMAIN}/admin-dashboard/newsletters/", text)
        self.assertEqual(result["staff_told"]["telegram"],
                         {"chats": 1, "sent": 1})

    def test_a_newer_review_supersedes_the_one_still_waiting(self):
        older = _edition(status="ai_generated",
                         scheduled_for=SATURDAY + timedelta(hours=20))
        result, _post = self.review(now=SATURDAY + timedelta(days=7))
        older.refresh_from_db()
        self.assertEqual(older.status, "cancelled")
        self.assertIsNone(older.scheduled_for)
        self.assertIn("Superseded", older.last_error)

    def test_an_empty_review_is_failed_not_scheduled(self):
        from alerts.models import Newsletter
        with self.assertLogs("alerts.newsletter_service", "WARNING"):
            result, post = self.review(text="   ")
        nl = Newsletter.objects.get(pk=result["newsletter_id"])
        self.assertEqual(nl.status, "failed")
        self.assertIsNone(nl.scheduled_for)
        self.assertIn("Weekly letter not ready",
                      post.call_args.kwargs["json"]["text"])

    def test_the_monday_plan_still_reads_the_latest_weekly_row(self):
        from ai_agents.tasks import MondayPlanAgent, generate_monday_plan
        _edition(title="Old", content_markdown="OLDER REVIEW TEXT",
                 status="sent", sent_at=timezone.now())
        self.review()
        # A cancelled special edition written after it is not the review.
        _edition(title="X", frequency="weekly", status="cancelled",
                 content_markdown="CANCELLED TEXT")
        provider = _Provider("## Plan\nHold.")
        with mock.patch.object(MondayPlanAgent, "_get_provider",
                               lambda self, name: provider), \
                mock.patch("requests.post", return_value=_ok()):
            generate_monday_plan.__wrapped__.__wrapped__()
        context = provider.seen[0]["user_message"]
        self.assertIn("LAST WEEKLY REVIEW:\n# Market Overview", context)
        self.assertNotIn("OLDER REVIEW TEXT", context)
        self.assertNotIn("CANCELLED TEXT", context)

    def test_the_monday_plan_reads_a_row_still_sending(self):
        from ai_agents.tasks import MondayPlanAgent, generate_monday_plan
        _edition(content_markdown="SENDING REVIEW", status="sending",
                 sent_at=timezone.now())
        provider = _Provider("## Plan\nHold.")
        with mock.patch.object(MondayPlanAgent, "_get_provider",
                               lambda self, name: provider), \
                mock.patch("requests.post", return_value=_ok()):
            generate_monday_plan.__wrapped__.__wrapped__()
        self.assertIn("SENDING REVIEW", provider.seen[0]["user_message"])


# ── the ad-hoc edition, written in the background ────────────────────────

class GenerateTaskTests(_Base):
    def fake_agent(self, markdown=None, error=None):
        agent = mock.MagicMock()
        if error:
            agent.run.side_effect = error
        else:
            agent.run.return_value = {"markdown": markdown}
        return mock.patch("alerts.newsletter_service._NewsletterWriterAgent",
                          return_value=agent)

    def test_success_lands_ready_and_unscheduled(self):
        from alerts.tasks import generate_newsletter_task
        nl = _edition(status="generating", content_markdown="",
                      frequency="adhoc")
        with self.fake_agent("## Special\nText."):
            out = generate_newsletter_task(nl.pk)
        nl.refresh_from_db()
        self.assertEqual(out["status"], "generated")
        self.assertEqual((nl.status, nl.content_markdown),
                         ("ai_generated", "## Special\nText."))
        self.assertIsNone(nl.scheduled_for)

    def test_failure_is_recorded_on_the_row(self):
        from alerts.tasks import generate_newsletter_task
        nl = _edition(status="generating", content_markdown="")
        with self.fake_agent(error=RuntimeError("provider 529")), \
                self.assertLogs("alerts.newsletter_service", "WARNING"):
            generate_newsletter_task(nl.pk)
        nl.refresh_from_db()
        self.assertEqual(nl.status, "failed")
        self.assertIn("provider 529", nl.last_error)
        self.assertEqual(nl.content_markdown, "")

    def test_a_row_cancelled_meanwhile_stays_cancelled(self):
        from alerts.newsletter_service import generate_newsletter_with_ai
        nl = _edition(status="generating", content_markdown="")
        from alerts.models import Newsletter
        Newsletter.objects.filter(pk=nl.pk).update(status="cancelled")
        with self.fake_agent("text"):
            generate_newsletter_with_ai(nl)
        nl.refresh_from_db()
        self.assertEqual((nl.status, nl.content_markdown), ("cancelled", ""))


# ── the admin page ───────────────────────────────────────────────────────

@override_settings(**MAIL)
class AdminPageTests(_Base):
    URL = "/admin-dashboard/newsletters/"

    def setUp(self):
        super().setUp()
        self.admin = _reader("boss", superuser=True)
        self.client.force_login(self.admin)

    def post(self, **data):
        return self.client.post(self.URL, data)

    def test_superuser_only(self):
        staff = _reader("staffer", staff=True)
        client = Client()
        client.force_login(staff)
        self.assertEqual(client.get(self.URL).status_code, 403)
        self.assertEqual(client.post(self.URL, {"action": "delete"})
                         .status_code, 403)
        anonymous = Client().get(self.URL)
        self.assertEqual(anonymous.status_code, 302)

    def test_every_status_wears_its_badge(self):
        for status in ("draft", "generating", "ai_generated", "approved",
                       "sending", "sent", "failed", "cancelled"):
            _edition(title=f"E {status}", status=status)
        _edition(title="Scheduled one", status="ai_generated",
                 scheduled_for=timezone.now() + timedelta(days=1))
        body = self.client.get(self.URL).content.decode()
        for badge in ("DRAFT", "GENERATING", "READY", "APPROVED", "SENDING",
                      "SENT", "FAILED", "CANCELLED", "SCHEDULED"):
            self.assertIn(f">{badge}</span>", body)
        self.assertIn("Paris time", body)

    def test_the_page_carries_preview_edit_reach_and_overlay(self):
        _reader("someone")
        _edition()
        body = self.client.get(self.URL).content.decode()
        self.assertIn('<iframe class="nl-preview"', body)
        self.assertIn('sandbox="allow-popups', body)
        self.assertIn("srcdoc=", body)
        # The preview is escaped into the attribute: no raw tag leaks.
        srcdoc = re.search(r'srcdoc="([^"]*)"', body).group(1)
        self.assertNotIn("<", srcdoc)
        self.assertIn('value="edit"', body)
        self.assertIn('name="content"', body)
        self.assertIn("will reach 2 people: 2 by email, 0 by Telegram", body)
        self.assertIn("SV.overlay.confirm", body)
        self.assertIn("Send a test to me", body)
        # The create form: no monthly, no WhatsApp.
        self.assertNotIn('value="monthly"', body)
        self.assertNotIn("send_whatsapp", body)
        from pathlib import Path

        from django.conf import settings
        src = (Path(settings.BASE_DIR) / "templates" / "dashboard"
               / "admin_newsletters.html").read_text(encoding="utf-8")
        self.assertNotIn("WhatsApp", src)

    def test_no_native_dialog_on_the_page(self):
        from pathlib import Path

        from django.conf import settings
        src = (Path(settings.BASE_DIR) / "templates" / "dashboard"
               / "admin_newsletters.html").read_text(encoding="utf-8")
        code = re.sub(r"/\*.*?\*/|//[^\n]*", "", src, flags=re.S)
        code = code.replace("SV.overlay.confirm(", "")
        self.assertIsNone(re.search(
            r"(?<![.\w])(?:window\.)?(?:confirm|alert)\s*\(", code))
        self.assertNotIn("onsubmit=", src)
        for action in ("send", "cancel", "reschedule", "approve", "delete"):
            self.assertRegex(
                src, r'class="nl-confirm"[^>]*>\{% csrf_token %\}<input '
                     r'type="hidden" name="action" value="' + action + '"')

    def test_create_queues_the_writer_and_returns(self):
        from alerts.models import Newsletter
        with mock.patch("alerts.tasks.generate_newsletter_task.delay") as d:
            r = self.post(action="create", title="Fed special",
                          frequency="monthly", send_email="on")
        self.assertEqual(r.status_code, 302)
        nl = Newsletter.objects.get(title="Fed special")
        d.assert_called_once_with(nl.pk)
        self.assertEqual((nl.status, nl.frequency), ("generating", "adhoc"))
        self.assertTrue(nl.send_email)
        self.assertFalse(nl.send_telegram)
        self.assertFalse(nl.send_whatsapp)

    def test_create_without_a_channel_is_refused(self):
        from alerts.models import Newsletter
        with mock.patch("alerts.tasks.generate_newsletter_task.delay") as d:
            self.post(action="create", title="Nowhere")
        d.assert_not_called()
        self.assertFalse(Newsletter.objects.filter(title="Nowhere").exists())

    def test_a_queue_that_cannot_be_reached_is_said_on_the_row(self):
        from alerts.models import Newsletter
        with mock.patch("alerts.tasks.generate_newsletter_task.delay",
                        side_effect=ConnectionError("redis down")):
            self.post(action="create", title="Q", send_email="on")
        nl = Newsletter.objects.get(title="Q")
        self.assertEqual(nl.status, "failed")
        self.assertIn("redis down", nl.last_error)

    def test_approve_cancel_reschedule_edit_delete(self):
        from alerts.models import Newsletter
        nl = _edition(status="ai_generated",
                      scheduled_for=timezone.now() + timedelta(days=1))
        self.post(action="approve", newsletter_id=nl.pk)
        nl.refresh_from_db()
        self.assertEqual(nl.status, "approved")

        self.post(action="cancel", newsletter_id=nl.pk)
        nl.refresh_from_db()
        self.assertEqual((nl.status, nl.scheduled_for), ("cancelled", None))

        future = (timezone.now() + timedelta(days=3)).astimezone(
            __import__("zoneinfo").ZoneInfo("Europe/Paris"))
        value = future.strftime("%Y-%m-%dT%H:%M")
        self.post(action="reschedule", newsletter_id=nl.pk,
                  scheduled_for=value)
        nl.refresh_from_db()
        self.assertEqual(nl.status, "approved")
        self.assertEqual(nl.scheduled_for.astimezone(future.tzinfo)
                         .strftime("%Y-%m-%dT%H:%M"), value)

        before = nl.scheduled_for
        self.post(action="reschedule", newsletter_id=nl.pk,
                  scheduled_for="2020-01-01T08:00")
        nl.refresh_from_db()
        self.assertEqual(nl.scheduled_for, before)

        self.post(action="edit", newsletter_id=nl.pk, title="New title",
                  content="## New\nBody")
        nl.refresh_from_db()
        self.assertEqual((nl.title, nl.content_markdown),
                         ("New title", "## New\nBody"))

        self.post(action="delete", newsletter_id=nl.pk)
        self.assertFalse(Newsletter.objects.filter(pk=nl.pk).exists())

    def test_send_now_queues_the_send_and_returns(self):
        nl = _edition(status="ai_generated")
        with mock.patch("alerts.tasks.send_newsletter_task.delay") as d:
            r = self.post(action="send", newsletter_id=nl.pk)
        self.assertEqual(r.status_code, 302)
        d.assert_called_once_with(nl.pk, scheduled=False)
        self.assertEqual(mail.outbox, [])

    def test_a_sent_edition_can_be_neither_sent_nor_edited(self):
        nl = _edition(status="sent", sent_at=timezone.now())
        with mock.patch("alerts.tasks.send_newsletter_task.delay") as d:
            self.post(action="send", newsletter_id=nl.pk)
            self.post(action="edit", newsletter_id=nl.pk, content="x")
        d.assert_not_called()
        nl.refresh_from_db()
        self.assertEqual(nl.content_markdown, LETTER)

    def test_a_stale_or_malformed_id_is_a_404_never_a_500(self):
        for action in ("approve", "send", "cancel", "reschedule", "edit",
                       "test", "delete"):
            for bad in ("987654", "abc", ""):
                r = self.post(action=action, newsletter_id=bad,
                              scheduled_for="2030-01-01T08:00")
                self.assertEqual(r.status_code, 404, (action, bad))

    def test_the_test_goes_to_the_requester_only_and_marks_nothing(self):
        from alerts.models import NewsletterDelivery
        _reader("subscriber")
        nl = _edition(status="ai_generated")
        self.post(action="test", newsletter_id=nl.pk)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["boss@readers.test"])
        self.assertTrue(mail.outbox[0].subject.startswith(
            "[Test] Sauron Vision — "))
        nl.refresh_from_db()
        self.assertEqual(nl.status, "ai_generated")
        self.assertIsNone(nl.sent_at)
        self.assertFalse(NewsletterDelivery.objects.exists())

    def test_a_test_without_an_email_is_refused(self):
        self.admin.email = ""
        self.admin.save()
        nl = _edition()
        r = self.client.post(self.URL, {"action": "test",
                                        "newsletter_id": nl.pk}, follow=True)
        self.assertIn("no email address", r.content.decode())
        self.assertEqual(mail.outbox, [])


# ── the archive ──────────────────────────────────────────────────────────

class ArchiveTests(_Base):
    def setUp(self):
        super().setUp()
        self.reader = _reader("archivist")
        self.client.force_login(self.reader)

    def test_login_required(self):
        nl = _edition(status="sent", sent_at=timezone.now())
        for path in ("/newsletters/", f"/newsletters/{nl.pk}/"):
            r = Client().get(path)
            self.assertEqual(r.status_code, 302)
            self.assertIn("next=" + path, r["Location"])

    def test_the_list_shows_what_went_out_newest_first(self):
        old = _edition(title="Old one", status="sent",
                       sent_at=timezone.now() - timedelta(days=7))
        new = _edition(title="New one", status="sent",
                       sent_at=timezone.now())
        retrying = _edition(title="Retrying one", status="sending",
                            sent_at=timezone.now() - timedelta(hours=1))
        _edition(title="Draft one", status="draft")
        _edition(title="Ready one", status="ai_generated")
        _edition(title="Starting one", status="sending", sent_at=None)
        body = self.client.get("/newsletters/").content.decode()
        self.assertLess(body.index("New one"), body.index("Retrying one"))
        self.assertLess(body.index("Retrying one"), body.index("Old one"))
        for hidden in ("Draft one", "Ready one", "Starting one"):
            self.assertNotIn(hidden, body)
        self.assertIn(f"/newsletters/{new.pk}/", body)
        self.assertIn(f"/newsletters/{old.pk}/", body)
        self.assertIn(f"/newsletters/{retrying.pk}/", body)

    def test_one_edition_renders_escaped(self):
        nl = _edition(status="sent", sent_at=timezone.now())
        r = self.client.get(f"/newsletters/{nl.pk}/")
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertIn('<h2 class="nl-h2"', body)
        self.assertIn("&lt;script&gt;alert(1)", body)
        self.assertNotIn("<script>alert(1)", body)

    def test_a_draft_is_a_404_for_a_reader_and_a_page_for_staff(self):
        nl = _edition(status="ai_generated")
        self.assertEqual(self.client.get(f"/newsletters/{nl.pk}/")
                         .status_code, 404)
        staff = _reader("staff_reader", staff=True)
        client = Client()
        client.force_login(staff)
        r = client.get(f"/newsletters/{nl.pk}/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Not sent yet", r.content.decode())
        self.assertEqual(self.client.get("/newsletters/424242/")
                         .status_code, 404)

    def test_the_rail_links_the_archive(self):
        body = self.client.get("/newsletters/").content.decode()
        self.assertIn('<span class="label-text">Weekly Letter</span>', body)


# ── the wiring ───────────────────────────────────────────────────────────

class WiringTests(TestCase):
    def test_the_beat_entry_runs_every_quarter_hour(self):
        from celery.schedules import crontab

        from config.celery import app
        entry = app.conf.beat_schedule["send-due-newsletters"]
        self.assertEqual(entry["task"], "alerts.tasks.send_due_newsletters")
        self.assertEqual(entry["schedule"], crontab(minute="*/15"))

    def test_it_is_placed_in_the_day(self):
        from core.day_of_sauron import STAGE_OF
        self.assertEqual(STAGE_OF["send-due-newsletters"],
                         ("tell", "the newsletter, when an edition is due"))

    def test_the_switch_is_registered_and_arrives_off(self):
        from core.platform_control import (DEFAULT_COMPONENTS,
                                           PlatformComponent,
                                           seed_components)
        row = next(c for c in DEFAULT_COMPONENTS
                   if c["key"] == "newsletter_send")
        self.assertEqual(row["category"], "pipeline")
        self.assertLess(len(row["description"]), 300)
        seed_components()
        self.assertFalse(PlatformComponent.objects.get(
            key="newsletter_send").is_enabled)
        from alerts.tasks import send_due_newsletters
        self.assertEqual(send_due_newsletters.run.component_key,
                         "newsletter_send")

    def test_the_send_runs_on_the_slow_queue(self):
        from config.celery import app
        routes = app.conf.task_routes
        self.assertEqual(routes["alerts.tasks.send_newsletter_task"],
                         {"queue": "slow"})
        self.assertEqual(routes["alerts.tasks.generate_newsletter_task"],
                         {"queue": "ai"})

    def test_the_dead_code_is_gone(self):
        from pathlib import Path

        from django.conf import settings
        src = (Path(settings.BASE_DIR) / "alerts"
               / "newsletter_service.py").read_text(encoding="utf-8")
        self.assertNotIn("send_mass_mail", src)
        self.assertNotIn("os.getenv(\"DEFAULT_FROM_EMAIL\"", src)
        self.assertNotIn("whatsapp", src.lower())
        import alerts.tasks as tasks
        self.assertFalse(hasattr(tasks, "auto_generate_newsletter"))

    def test_the_unsubscribe_link_is_not_behind_the_idle_lock(self):
        from core.idle_lock import EXEMPT_PREFIXES
        self.assertIn("/newsletter/unsubscribe/", EXEMPT_PREFIXES)
