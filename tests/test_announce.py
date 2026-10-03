"""Announcements to the platform's Telegram group (core/announcements.py,
2026-10-03): the October release note, in the house style and the lore.

The operator: "make the telegram bot send it in his group... with great
styling and lore". Pinned: the note renders under Telegram's limit with
nothing cut, in the house HTML (the Eye's mark, a bold title, an italic
subtitle, bold section headings, the who-is-who folded), English only,
with no number of the book and no promise; the command prints on
--dry-run and sends nothing, sends once per chat, says what Telegram
answered, and is registered as an ops write.

Run with:  python manage.py test tests.test_announce
"""
import html
import re
from io import StringIO
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase

from core import announcements as A

TOKEN = "123456:announce-test-token"
ENV = {"TELEGRAM_BOT_TOKEN": TOKEN, "TELEGRAM_CHAT_ID": "-100777"}
#: tests/test_telegram_house_style.py's list: words and letters that
#: cannot be English.
FRENCH = (" le ", " la ", " les ", " des ", " du ", " une ", " est ",
          " pour ", " avec ", " sur ", " vous ", "é", "è",
          "ê", "à ", "ç", "ù")


def _ok():
    return MagicMock(ok=True, status_code=200, text='{"ok":true}')


def _refused():
    return MagicMock(ok=False, status_code=400,
                     text='{"ok":false,"description":"Bad Request"}')


class TheNoteTests(SimpleTestCase):

    def test_it_fits_whole_in_one_message(self):
        from alerts.channels.telegram_alert import (CONTINUED,
                                                    TELEGRAM_MAX_CHARS, _units)
        text = A.render("october_turn")
        self.assertLessEqual(_units(text), TELEGRAM_MAX_CHARS)
        self.assertNotIn(CONTINUED, text)
        # every fact survived the fit
        for line in A.OCTOBER_TURN["lines"]:
            self.assertIn(html.escape(str(line))[:60], text)
        self.assertIn("WHO IS WHO", text)

    def test_the_house_style_and_the_lore(self):
        text = A.render("october_turn")
        first = text.splitlines()[0]
        # the house style: the mark inside the bold title, one line
        self.assertTrue(first.startswith("<b>" + A.MARK + " "), first)
        self.assertTrue(first.endswith("</b>"), first)
        self.assertIn("THE EYE TURNS", first)
        self.assertIn("<i>The Eye has looked at itself.", text)
        self.assertIn("<b>WHAT IS NEW</b>", text)
        self.assertIn("<b>WHY THIS COULD BE THE TURN</b>", text)
        self.assertIn("<blockquote expandable>WHO IS WHO", text)
        for name in ("Sauron", "Morgul", "Aragorn", "The proving ground",
                     "The Wall"):
            self.assertIn(name, text)
        # the P&L is escaped, never raw
        self.assertIn("P&amp;L", text)
        self.assertNotIn("P&L ", text)

    def test_english_only_no_book_numbers_no_promise(self):
        text = html.unescape(re.sub(r"<[^>]+>", "", A.render("october_turn")))
        low = f" {text.lower()} "
        for word in FRENCH:
            self.assertNotIn(word, low, word)
        # no R figure, no percentage of the book, no money
        self.assertIsNone(re.search(r"[+-]\d+(\.\d+)?R\b", text), text)
        self.assertNotIn("62%", text)
        self.assertNotIn("$", text)
        self.assertNotIn("€", text)
        self.assertIn("No promises.", text)
        self.assertIn("never print a probability we cannot measure", text)

    def test_the_registry_names_it(self):
        self.assertEqual(list(A.ANNOUNCEMENTS), ["october_turn"])


class TheCommandTests(TestCase):

    def setUp(self):
        cache.clear()

    def test_list_and_an_unknown_name(self):
        out = StringIO()
        call_command("announce", "list", stdout=out)
        self.assertIn("october_turn", out.getvalue())
        self.assertIn("THE EYE TURNS", out.getvalue())
        out = StringIO()
        with patch("requests.post") as post:
            call_command("announce", "nope", stdout=out)
        self.assertIn("no announcement 'nope'", out.getvalue())
        post.assert_not_called()

    def test_dry_run_prints_the_html_and_sends_nothing(self):
        out = StringIO()
        with patch.dict("os.environ", ENV), patch("requests.post") as post:
            call_command("announce", "october_turn", "--dry-run", stdout=out)
        post.assert_not_called()
        text = out.getvalue()
        self.assertIn("<b>WHAT IS NEW</b>", text)
        self.assertIn("nothing sent", text)

    def test_it_is_sent_to_the_platform_chat_in_house_html_once(self):
        out = StringIO()
        with patch.dict("os.environ", ENV), \
                patch("requests.post", return_value=_ok()) as post:
            call_command("announce", "october_turn", stdout=out)
            call_command("announce", "october_turn", stdout=out)
        self.assertEqual(post.call_count, 1, "a release goes out once")
        url = post.call_args.args[0]
        payload = post.call_args.kwargs["json"]
        self.assertIn(f"/bot{TOKEN}/sendMessage", url)
        self.assertEqual(payload["chat_id"], "-100777")
        self.assertEqual(payload["parse_mode"], "HTML")
        self.assertTrue(payload["disable_web_page_preview"])
        self.assertTrue(payload["text"].startswith("<b>" + A.MARK + " "))
        lines = out.getvalue().splitlines()
        self.assertIn("SENT", lines[0])
        self.assertIn("REPEAT", lines[1])
        self.assertIn("--force sends it again", lines[1])

    def test_force_and_another_chat(self):
        with patch.dict("os.environ", ENV), \
                patch("requests.post", return_value=_ok()) as post:
            call_command("announce", "october_turn", stdout=StringIO())
            call_command("announce", "october_turn", "--force",
                         stdout=StringIO())
            call_command("announce", "october_turn", "--chat", "-100999",
                         stdout=StringIO())
        self.assertEqual(post.call_count, 3)
        self.assertEqual(post.call_args.kwargs["json"]["chat_id"], "-100999")

    def test_a_refusal_and_a_missing_token_are_said(self):
        out = StringIO()
        with patch.dict("os.environ", ENV), \
                patch("requests.post", return_value=_refused()):
            call_command("announce", "october_turn", stdout=out)
        self.assertIn("REFUSED", out.getvalue())
        self.assertFalse(A.already_sent("october_turn", "-100777"),
                         "a refusal is not a send")
        out = StringIO()
        with patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN": "",
                                       "TELEGRAM_CHAT_ID": "-100777"}), \
                patch("requests.post") as post:
            call_command("announce", "october_turn", stdout=out)
        post.assert_not_called()
        self.assertIn("UNSENT", out.getvalue())
        self.assertIn("TELEGRAM_BOT_TOKEN is not set", out.getvalue())

    def test_no_chat_at_all_is_said(self):
        out = StringIO()
        with patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN": TOKEN,
                                       "TELEGRAM_CHAT_ID": ""}), \
                patch("requests.post") as post:
            call_command("announce", "october_turn", stdout=out)
        post.assert_not_called()
        self.assertIn("no chat", out.getvalue())

    def test_it_is_registered_as_an_ops_write(self):
        from core import ops_commands
        entry = ops_commands.get("announce")
        self.assertEqual(entry["category"], "ops")
        self.assertFalse(entry["read_only"])
        self.assertNotIn("announce", ops_commands.runnable_names())
