"""THE MONDAY GAME PLAN, READ WHOLE (2026-09-27).

The operator: "the monday game plan is not fully visible it seems, only on
hover... fix it". generate_monday_plan put the plan in the bell alone, cut
at 2,000 characters, linked to /briefing/, which never showed it. What
this file pins:

  * the store: the run's own AgentTask row keeps the WHOLE plan and the
    week it is for; an older row without the week gets it from its time;
  * the page: /briefing/#monday-plan renders the latest plan whole (a plan
    longer than 2,000 characters, every line of it), its week and when it
    was written; headings, lists and bold render, a table becomes a list,
    the calls block is said in words; the four plans before it fold
    underneath, one per week; with no plan the page says so and answers
    200;
  * nothing of the text is lost on the way: only the calls block and the
    one line that heads it leave the prose (a closing line, bold rules or a
    last section above the block stay); a table keeps every cell; a fenced
    code block stays as written;
  * the model's text is escaped: a <script> in the plan is text on the
    page, in the bell and on Telegram; a link to another site is words on
    the page, not a link;
  * the bell: url /briefing/#monday-plan, a short summary of whole
    sentences ("U.S.", "Dr." or "e.g." never end one), never cut inside a
    word, and "Read the full plan";
  * Telegram: the staff group gets one house-style message (HTTP patched)
    with the week, the summary and the "Read the full plan" button when
    the platform names its host; the words stand in without one; a
    refusal is logged and costs neither the task nor the bell.

Run with:  python manage.py test tests.test_monday_plan_visible
"""
import os
import re
from datetime import date, datetime, timedelta
from datetime import timezone as dt_tz
from unittest import mock

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase

UTC = dt_tz.utc
#: Sunday 2026-09-27, 18:00 UTC: the beat's hour.
SUNDAY = datetime(2026, 9, 27, 18, 0, tzinfo=UTC)
GROUP = "-1001234567890"
HOST = "platform.sauron-vision.net"

LEAD = ("The dollar starts the week on the back foot after a soft "
        "inflation print. Risk assets stay bid while yields drift lower. "
        "Sauron keeps its size modest until the Fed minutes on Wednesday.")
FILLER = ["Risk note %d keeps the desk careful through session number %d, "
          "whatever the tape says that day." % (n, n) for n in range(1, 31)]
LAST = ("The last line of the plan says the stop is never moved against "
        "a position.")
SCRIPT_LINE = "Watch for <script>alert(1)</script> in the tape."

PLAN = "\n".join([
    "# Monday Game Plan",
    "",
    "## Weekly Macro Outlook",
    LEAD,
    "",
    "## Priority Strategies",
    "- **Golden cross on EURUSD** stays the lead strategy this week.",
    "- The gold breakout waits for a close above 2,700.",
    "",
    "**Key Levels to Watch**",
    "",
    "| Instrument | Support | Resistance |",
    "|---|---|---|",
    "| EURUSD | 1.0850 | 1.0950 |",
    "| XAUUSD | 2,650 | 2,720 |",
    "",
    "---",
    "",
    "## Economic Event Risk",
] + FILLER + [
    "",
    "## Risk Management Reminders",
    SCRIPT_LINE,
    LAST,
    "",
    "## Calls",
    "```json",
    '{"calls": [{"symbol": "EURUSD", "direction": "up", "horizon_hours": '
    '72, "confidence": 0.6, "why": "a soft dollar after the print"}]}',
    "```",
])

TITLE = "Monday game plan — week of 28 September 2026"
PAGE = "/briefing/#monday-plan"
WHERE = "Read the full plan on the Strategist Briefing page."


class _Provider:
    """The model, answering with a fixed plan."""

    def __init__(self, text):
        self.text = text

    def complete(self, **_kw):
        return self.text, {"input_tokens": 1200, "output_tokens": 900,
                           "cost_usd": 0.02}


def _staff(name="operator", chat=GROUP):
    from alerts.models import UserNotificationPrefs
    from portfolio.trader_profile import TraderProfile
    user = User.objects.create_user(username=name, password="x",
                                    is_staff=True)
    profile, _ = TraderProfile.objects.get_or_create(user=user)
    profile.notify_channel = "telegram"
    profile.save()
    prefs, _ = UserNotificationPrefs.objects.get_or_create(user=user)
    prefs.telegram_chat_id = chat
    prefs.save()
    return user


def _answer(ok=True, status=200, text='{"ok": true}'):
    return mock.Mock(ok=ok, status_code=status, text=text)


def _run(text=PLAN, *, now=SUNDAY, env=None, answer=None):
    """generate_monday_plan past its gate, with the model and the clock
    fixed and Telegram's HTTP patched: (result, the patched post)."""
    from ai_agents.tasks import MondayPlanAgent, generate_monday_plan
    environ = {"TELEGRAM_BOT_TOKEN": "123:abc", "DOMAIN": ""}
    environ.update(env or {})
    with mock.patch.object(MondayPlanAgent, "_get_provider",
                           lambda self, name: _Provider(text)), \
            mock.patch("django.utils.timezone.now", return_value=now), \
            mock.patch.dict(os.environ, environ), \
            mock.patch("alerts.channels.telegram_alert.requests.post",
                       return_value=answer or _answer()) as post:
        result = generate_monday_plan.__wrapped__.__wrapped__()
    return result, post


def _plan_row(text, when, *, week=None, success=True):
    from ai_agents.models import AgentTask
    out = {"plan": text}
    if week is not None:
        out["week_of"] = week
    row = AgentTask.objects.create(
        agent="monday_plan", provider="claude", model="m",
        prompt_summary="p", structured_output=out, success=success)
    AgentTask.objects.filter(pk=row.pk).update(created_at=when)
    return row


class _Page(TestCase):
    def setUp(self):
        self.reader = User.objects.create_user(username="father",
                                               password="x")
        self.client.force_login(self.reader)

    def page(self):
        r = self.client.get("/briefing/")
        self.assertEqual(r.status_code, 200)
        return r.content.decode("utf-8")

    def section(self, body):
        m = re.search(r'<section class="card mp-card" id="monday-plan".*?'
                      r'</section>', body, re.S)
        self.assertIsNotNone(m, "no #monday-plan section on /briefing/")
        return m.group(0)


class TheWholePlanIsStoredTests(_Page):

    def test_the_run_keeps_the_whole_plan_and_its_week(self):
        from ai_agents.models import AgentTask
        self.assertGreater(len(PLAN), 2000)
        result, _post = _run()
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["week_of"], "2026-09-28")
        self.assertEqual(result["plan_length"], len(PLAN))
        rows = AgentTask.objects.filter(agent="monday_plan")
        self.assertEqual(rows.count(), 1)
        self.assertEqual(rows[0].structured_output,
                         {"plan": PLAN, "week_of": "2026-09-28"})

    def test_the_week_is_the_coming_monday_on_a_weekend(self):
        from ai_agents.monday_plan import week_of
        monday = date(2026, 9, 28)
        for day in (SUNDAY, datetime(2026, 9, 26, 9, 0, tzinfo=UTC),
                    date(2026, 9, 28), date(2026, 9, 30),
                    datetime(2026, 10, 2, 23, 59, tzinfo=UTC)):
            with self.subTest(day=day):
                self.assertEqual(week_of(day), monday)
        self.assertEqual(week_of(date(2026, 10, 3)), date(2026, 10, 5))

    def test_an_older_row_without_its_week_takes_it_from_its_time(self):
        _plan_row("An older plan written before the week was kept.",
                  SUNDAY - timedelta(days=7))
        section = self.section(self.page())
        self.assertIn("Week of 21 September 2026", section)
        self.assertIn("An older plan written before the week was kept.",
                      section)


class ThePageShowsItWholeTests(_Page):

    def setUp(self):
        super().setUp()
        _run()
        self.body = self.page()
        self.mp = self.section(self.body)

    def test_every_line_of_a_plan_past_2000_characters_is_on_the_page(self):
        for line in [LEAD] + FILLER + [LAST]:
            with self.subTest(line=line[:40]):
                self.assertIn(line, self.mp)
        self.assertIn("Week of 28 September 2026", self.mp)
        self.assertIn("Written Sunday 27 September 2026 at 18:00 UTC.",
                      self.mp)

    def test_headings_lists_and_bold_render_and_a_table_is_a_list(self):
        self.assertIn('<h4 class="rs-h">Weekly Macro Outlook</h4>', self.mp)
        self.assertIn('<h4 class="rs-h">Key Levels to Watch</h4>', self.mp)
        self.assertIn("<li><strong>Golden cross on EURUSD</strong> stays "
                      "the lead strategy this week.</li>", self.mp)
        self.assertIn("<li>EURUSD — Support: 1.0850, Resistance: 1.0950"
                      "</li>", self.mp)
        self.assertNotIn("**", self.mp)
        self.assertNotIn("|---", self.mp)

    def test_the_calls_block_is_said_in_words_not_printed_as_json(self):
        self.assertIn("<li>EURUSD — up within 3 days, confidence 60%. A "
                      "soft dollar after the print.</li>", self.mp)
        self.assertNotIn('"calls"', self.mp)
        self.assertNotIn("&quot;calls&quot;", self.mp)
        self.assertNotIn("```", self.mp)

    def test_a_script_in_the_plan_is_text(self):
        self.assertIn("Watch for &lt;script&gt;alert(1)&lt;/script&gt; in "
                      "the tape.", self.mp)
        self.assertNotIn("<script>alert(1)</script>", self.body)

    def test_the_top_of_the_page_leads_to_it(self):
        self.assertIn('<a class="mp-jump" href="#monday-plan">Monday game '
                      'plan — week of 28 September 2026', self.body)
        self.assertLess(self.body.index('class="mp-jump"'),
                        self.body.index('id="brfMain"'))
        # The section comes after the briefings' history, the last thing
        # inside #brfMain: outside the region the run-now refresh swaps.
        self.assertGreater(self.body.index('id="monday-plan"'),
                           self.body.index('id="brfHistory"'))

    def test_the_page_carries_its_own_phone_first_styles(self):
        self.assertIn(".mp-old > summary", self.body)
        self.assertIn("min-height: 48px", self.body)
        self.assertIn("@media (max-width: 768px)", self.body)


class NothingOfTheTextIsLostTests(_Page):
    """Lens 1 (2026-09-27): the lines above the calls block were dropped
    while they were blank, a heading or a bold line, and the plan's last
    section went with them; a link to another site was a live link."""

    def test_the_last_section_above_the_calls_block_is_on_the_page(self):
        plan = "\n".join([
            "## Weekly Macro Outlook",
            "The dollar is soft.",
            "",
            "## Risk Management Reminders",
            "**Never move a stop against a position**",
            "**Stop for the day at a 2% loss**",
            "",
            "**Bottom line: stay small until payrolls print**",
            "",
            "## Directional Calls",
            '```json\n{"calls": [{"symbol": "EURUSD", "direction": "up"}]}'
            "\n```",
        ])
        _plan_row(plan, SUNDAY)
        section = self.section(self.page())
        for words in ("Risk Management Reminders",
                      "Never move a stop against a position",
                      "Stop for the day at a 2% loss",
                      "Bottom line: stay small until payrolls print"):
            with self.subTest(words=words):
                self.assertIn(words, section)
        self.assertNotIn("Directional Calls", section)
        self.assertNotIn("```", section)
        self.assertIn("<li>EURUSD — up</li>", section)

    def test_a_link_to_another_site_is_words_not_a_link(self):
        _plan_row("Before the open: [Confirm your account](https://evil."
                  "example/login). The rules are in [the book](/book/).",
                  SUNDAY)
        section = self.section(self.page())
        self.assertNotIn('href="https://evil.example', section)
        self.assertIn("Confirm your account (https://evil.example/login)",
                      section)
        self.assertIn('<a class="rs-link" href="/book/">the book</a>',
                      section)


class NoPlanYetTests(_Page):

    def test_the_page_answers_and_says_so(self):
        body = self.page()
        section = self.section(body)
        self.assertIn("No plan yet — it is written every Sunday evening.",
                      section)
        self.assertNotIn('class="mp-jump"', body)

    def test_a_failed_run_or_a_row_without_a_plan_is_not_a_plan(self):
        _plan_row("A failed run.", SUNDAY, week="2026-09-28", success=False)
        _plan_row("", SUNDAY - timedelta(days=7))
        from ai_agents.models import AgentTask
        AgentTask.objects.create(agent="monday_plan", provider="claude",
                                 model="m", prompt_summary="p",
                                 structured_output={"plan": 5})
        section = self.section(self.page())
        self.assertIn("No plan yet", section)

    def test_a_plan_that_cannot_be_read_never_takes_the_page_down(self):
        with mock.patch("ai_agents.monday_plan.recent_plans",
                        side_effect=RuntimeError("boom")), \
                self.assertLogs("ai_agents.monday_plan", "ERROR"):
            section = self.section(self.page())
        self.assertIn("No plan yet", section)


class TheEarlierPlansTests(_Page):

    def test_the_four_before_the_latest_fold_underneath_one_per_week(self):
        for weeks_ago in range(6, 0, -1):
            _plan_row("The plan written %d weeks ago." % weeks_ago,
                      SUNDAY - timedelta(weeks=weeks_ago))
        _plan_row("A first draft for this week.", SUNDAY - timedelta(hours=2))
        _plan_row("The plan for this week.", SUNDAY)
        section = self.section(self.page())
        latest = section.split('<div class="mp-older">')[0]
        self.assertIn("The plan for this week.", latest)
        self.assertIn("Week of 28 September 2026", latest)
        self.assertNotIn("A first draft for this week.", section)
        self.assertEqual(section.count('<details class="mp-old"'), 4)
        for weeks_ago in (1, 2, 3, 4):
            self.assertIn("The plan written %d weeks ago." % weeks_ago,
                          section)
        for weeks_ago in (5, 6):
            self.assertNotIn("The plan written %d weeks ago." % weeks_ago,
                             section)
        self.assertIn("Week of 21 September 2026", section)


class TheBellTests(TestCase):

    def setUp(self):
        self.reader = User.objects.create_user(username="father",
                                               password="x")

    def _row(self):
        from alerts.models import Notification
        rows = Notification.objects.filter(user=self.reader,
                                           notification_type="system")
        self.assertEqual(rows.count(), 1)
        return rows[0]

    def test_it_links_the_section_and_says_a_summary_in_whole_sentences(self):
        _run()
        n = self._row()
        self.assertEqual(n.url, PAGE)
        self.assertEqual(n.title, TITLE)
        summary, where = n.body.split("\n\n")
        self.assertEqual(where, WHERE)
        lines = summary.split("\n")
        self.assertEqual(lines[0], LEAD)
        self.assertTrue(2 <= len(lines) <= 5, lines)
        self.assertLess(len(n.body), 1000)
        self.assertNotIn(LAST, n.body)
        self.assertNotIn("**", n.body)
        self.assertNotIn("#", n.body)
        for line in lines:
            words = line.lstrip("• ")
            with self.subTest(line=line):
                self.assertIn(words, PLAN.replace("**", "")
                              + "\nEURUSD — Support: 1.0850, Resistance: "
                                "1.0950\nXAUUSD — Support: 2,650, "
                                "Resistance: 2,720")
        self.assertEqual(n.data["items"][0]["url"], PAGE)
        self.assertEqual(n.data["items"][0]["label"], "Read the full plan")

    def test_the_summary_keeps_whole_sentences_and_never_cuts_a_word(self):
        from ai_agents.monday_plan import summary_lines
        para = ("First sentence here. Second sentence follows it. A third "
                "one closes the paragraph.")
        self.assertEqual(summary_lines(para, max_chars=60),
                         ["First sentence here. Second sentence follows "
                          "it."])
        long_one = " ".join(["overextended"] * 40) + "."
        cut, = summary_lines(long_one, max_chars=100)
        self.assertTrue(cut.endswith("…"), cut)
        self.assertLessEqual(len(cut), 100)
        kept = cut[:-1]
        self.assertTrue(long_one.startswith(kept))
        self.assertEqual(long_one[len(kept)], " ")

    def test_a_script_in_the_summary_is_text_in_the_bell(self):
        _run("Sauron reads " + SCRIPT_LINE + " It never runs it.")
        n = self._row()
        self.assertIn(SCRIPT_LINE, n.body)   # plain text in the row...
        self.client.force_login(self.reader)
        body = self.client.get("/briefing/").content.decode("utf-8")
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", body)
        self.assertNotIn("<script>alert(1)</script>", body)   # ...escaped

    def test_an_empty_answer_is_not_announced(self):
        from alerts.models import Notification
        with self.assertLogs("ai_agents.monday_plan", "WARNING"):
            result, post = _run("   ")
        self.assertEqual(result["announced"]["bell"], 0)
        self.assertEqual(Notification.objects.count(), 0)
        post.assert_not_called()


class TheStaffGroupTests(TestCase):

    def setUp(self):
        self.staff = _staff()
        User.objects.create_user(username="father", password="x")

    def _sent(self, post):
        self.assertEqual(post.call_count, 1)
        return post.call_args.kwargs["json"]

    def test_one_message_with_the_week_the_summary_and_the_button(self):
        _staff("operator_two")  # the same group: said once
        result, post = _run(env={"DOMAIN": HOST})
        sent = self._sent(post)
        self.assertEqual(sent["chat_id"], GROUP)
        self.assertEqual(sent["parse_mode"], "HTML")
        text = sent["text"]
        self.assertTrue(text.startswith(
            "<b>\U0001F5D3️ " + TITLE + "</b>\n"), text[:80])
        self.assertIn(LEAD, text)
        lines = text.split("\n")[1:]
        self.assertTrue(3 <= len(lines) <= 6, lines)
        self.assertNotIn(WHERE, text)
        self.assertEqual(sent["reply_markup"], {"inline_keyboard": [[{
            "text": "Read the full plan",
            "url": "https://%s/briefing/#monday-plan" % HOST}]]})
        self.assertEqual(result["announced"]["telegram"],
                         {"chats": 1, "sent": 1, "refused": 0})

    def test_without_a_host_the_words_stand_in_for_the_button(self):
        _result, post = _run()
        sent = self._sent(post)
        self.assertNotIn("reply_markup", sent)
        self.assertTrue(sent["text"].endswith("\n" + WHERE), sent["text"])

    def test_the_plan_is_escaped_on_telegram(self):
        _result, post = _run("Sauron reads " + SCRIPT_LINE
                             + " It never runs it.")
        text = self._sent(post)["text"]
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", text)
        self.assertNotIn("<script>", text)

    def test_a_refusal_is_logged_and_costs_neither_the_task_nor_the_bell(self):
        from alerts.models import Notification
        with self.assertLogs("ai_agents.monday_plan", "WARNING") as said:
            result, post = _run(answer=_answer(
                ok=False, status=400, text="Bad Request: chat not found"))
        self.assertEqual(post.call_count, 1)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["announced"]["telegram"],
                         {"chats": 1, "sent": 0, "refused": 1})
        self.assertIn(GROUP, "\n".join(said.output))
        self.assertEqual(Notification.objects.filter(
            notification_type="system", url=PAGE).count(), 2)

    def test_no_staff_chat_or_no_token_sends_nothing(self):
        from alerts.models import UserNotificationPrefs
        _result, post = _run(env={"TELEGRAM_BOT_TOKEN": ""})
        post.assert_not_called()
        UserNotificationPrefs.objects.update(telegram_chat_id="")
        result, post = _run()
        post.assert_not_called()
        self.assertEqual(result["announced"]["telegram"]["chats"], 0)

    def test_every_word_sent_is_english(self):
        _result, post = _run(env={"DOMAIN": HOST})
        text = self._sent(post)["text"]
        for word in (" le ", " la ", " les ", " des ", " est ", " du "):
            self.assertNotIn(word, text)


class TheTextTests(SimpleTestCase):

    def test_a_bold_label_is_a_heading_and_a_bold_sentence_stays_one(self):
        from ai_agents.monday_plan import readable
        self.assertEqual(readable("**Key Levels:**"), "### Key Levels")
        self.assertEqual(readable("**Never move a stop.**"),
                         "**Never move a stop.**")
        self.assertNotIn("---", readable("a\n\n---\n\nb"))
        self.assertEqual(readable("| A | B |\n|---|---|\n| x | 1 |"),
                         "- x — B: 1")

    def test_a_long_first_paragraph_gives_its_lead_then_the_next_lines(self):
        from ai_agents.monday_plan import summary_lines
        first = " ".join("Sentence number %d of the outlook is here." % n
                         for n in range(1, 11))
        text = "\n\n".join([first, "- Keep the golden cross on.",
                            "- Halve the gold bot."])
        lines = summary_lines(text)
        self.assertEqual(len(lines), 3, lines)
        self.assertTrue(first.startswith(lines[0]))
        self.assertTrue(lines[0].endswith("of the outlook is here."))
        self.assertLessEqual(len(lines[0]), 240)
        self.assertEqual(lines[1:], ["• Keep the golden cross on.",
                                     "• Halve the gold bot."])

    def test_only_the_graded_calls_block_leaves_the_prose(self):
        from ai_agents.monday_plan import split_plan
        prose, calls = split_plan(
            "Plan.\n\n```json\n{\"levels\": [1]}\n```\n\n## Calls\n"
            "```json\n{\"calls\": [{\"symbol\": \"AAPL\"}]}\n```")
        self.assertEqual(calls, [{"symbol": "AAPL"}])
        self.assertIn('{"levels": [1]}', prose)
        self.assertNotIn("calls", prose)
        self.assertNotIn("## Calls", prose)

    def test_only_the_line_that_heads_the_calls_goes_with_them(self):
        from ai_agents.monday_plan import split_plan
        calls = ('```json\n{"calls": [{"symbol": "EURUSD", "direction": '
                 '"up"}]}\n```')
        closing = ("## 6. Risk Management Reminders\n- Never move a stop.\n"
                   "- Stop at a 2% daily loss.\n\n"
                   "**Trade the plan, not the noise**\n\n")
        prose, found = split_plan(closing + calls)
        self.assertEqual(found, [{"symbol": "EURUSD", "direction": "up"}])
        self.assertEqual(prose, closing.strip())
        rules = ("## 6. Risk Management Reminders\n"
                 "**Never move a stop against a position**\n"
                 "**Stop for the day at a 2% loss**")
        self.assertEqual(split_plan(rules + "\n\n" + calls)[0], rules)
        final = ("## Summary\nKeep it small.\n\n## Final Word\n"
                 "**Discipline beats conviction this week**")
        self.assertEqual(split_plan(final + "\n\n## Directional Calls\n"
                                    + calls)[0], final)
        for head in ("## Calls", "**Calls:**",
                     "### 7. Directional calls (JSON)", "The calls:"):
            with self.subTest(head=head):
                self.assertEqual(
                    split_plan("Body.\n\n" + head + "\n" + calls)[0],
                    "Body.")
        self.assertEqual(
            split_plan("Body.\n\n## Calls\n" + calls
                       + "\n\n## After the calls\nStill here.")[0],
            "Body.\n\n## After the calls\nStill here.")

    def test_an_abbreviation_does_not_end_a_sentence(self):
        from ai_agents.monday_plan import _sentences, summary_lines
        cpi = ("The week turns on the U.S. CPI print on Wednesday, which "
               "the market expects at 0.3% month on month; a hotter number "
               "revives the higher-for-longer trade, lifts the dollar "
               "against every major and pushes gold back under its "
               "breakout level before Friday's payrolls. Keep size modest.")
        first = summary_lines("## Weekly Macro Outlook\n" + cpi
                              + "\n- Second line.")[0]
        self.assertFalse(first.endswith("U.S."), first)
        self.assertTrue(cpi.startswith(first.rstrip("…")), first)
        gold = "Gold holds its range into the week."
        fed = ("The dollar leans on the U.S. CPI print on Wednesday and on "
               "the words of Dr. Smith at the Fed on Thursday, and a hot "
               "number would lift yields, press gold under its breakout "
               "level and pull the euro back toward its summer lows before "
               "payrolls.")
        self.assertGreater(len(gold + " " + fed), 240)
        self.assertEqual(summary_lines(gold + " " + fed)[0], gold)
        for text in ("Fed Chair J. Powell speaks on Tuesday.",
                     "Buy gold, e.g. GLDM, on a dip.",
                     "The data lands at 8:30 a.m. ET on Friday.",
                     "The S&P 500 is at 5,800 after Dr. Smith spoke."):
            with self.subTest(text=text):
                self.assertEqual(_sentences(text), [text])
        self.assertEqual(_sentences("Gold is up. Silver is down."),
                         ["Gold is up.", "Silver is down."])

    def test_a_table_keeps_every_cell(self):
        from ai_agents.monday_plan import readable
        out = readable("| Pair | Support |\n|---|---|\n"
                       "| EURUSD | 1.0850 | 1.0950 | fragile note |\n\n"
                       "| Only | Header |\n|---|---|\n")
        self.assertIn("- EURUSD — Support: 1.0850, 1.0950, fragile note",
                      out)
        self.assertIn("- Only · Header", out)

    def test_a_code_block_is_left_as_the_model_wrote_it(self):
        from ai_agents.monday_plan import readable
        fence = "```\n| a | b |\n|---|---|\n| 1 | 2 |\n---\n**label**\n```"
        self.assertEqual(
            readable("Body.\n\n" + fence + "\n\n**Key Levels:**"),
            "Body.\n\n" + fence + "\n\n### Key Levels")

    def test_a_link_to_another_site_is_said_not_followed(self):
        from ai_agents.monday_plan import readable
        self.assertEqual(
            readable("[Confirm your account](https://evil.example/login) "
                     "and [the book](/book/)"),
            "Confirm your account (https://evil.example/login) and "
            "[the book](/book/)")
        self.assertEqual(
            readable("[x](//evil.com) [y](/\\evil.com) "
                     "[z](javascript:alert(1)) [[w](https://a.example)]"
                     "(https://b.example)"),
            "x (//evil.com) y (/\\evil.com) z (javascript:alert(1)) "
            "w (https://a.example) (https://b.example)")


class TheMapNamesThePageTests(TestCase):

    def test_the_system_map_says_where_the_plan_is_read(self):
        from dashboard.views_topology import WIRING
        node = WIRING["agent_monday_plan"]
        self.assertIn("/briefing/", node["pages"])
        self.assertIn("/ai/", node["pages"])
        self.assertIn("#monday-plan", node["note"])
