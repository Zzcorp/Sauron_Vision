"""THE COUNCIL's surfaces (2026-10-08): /council/, the position page's
"The council at entry" card, the two switches on /ops/, the Book and the
Wall. Every sentence in English; no money in any alarm path (no council
module imports one).

Run with:  python manage.py test tests.test_council_surfaces
"""
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

REPO = Path(settings.BASE_DIR)


class TheRecordPageTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.staff = get_user_model().objects.create_user(
            "csf_staff", password="x", is_staff=True)
        cls.user = get_user_model().objects.create_user("csf_u", password="x")

    def test_the_page_is_staffs_and_says_what_it_is(self):
        resp = self.client.get("/council/")
        self.assertEqual(resp.status_code, 302)
        self.client.force_login(self.user)
        self.assertEqual(self.client.get("/council/").status_code, 302)
        self.client.force_login(self.staff)
        resp = self.client.get("/council/")
        self.assertEqual(resp.status_code, 200)
        for words in ("Ten voices argue live trades. Each is graded on what "
                      "the market did next, and its record is its only "
                      "weight.",
                      "Bot orders: <strong>OFF</strong>",
                      "Tickets: <strong>OFF</strong>",
                      "The debate: <strong>OFF</strong>",
                      "Council AI spend today:",
                      "No call graded yet: a voice weighs 1.00 until ten of "
                      "its calls are graded.",
                      "The Emperor: no graded sitting yet",
                      "The council, weighted by record: no graded sitting yet",
                      "The council, plain average: no graded sitting yet",
                      "Weights by regime", "Recent sittings",
                      "No sitting yet.", "The Gambler", "neutral (0)"):
            with self.subTest(words=words):
                self.assertContains(resp, words)

    def test_a_sitting_and_a_graded_record_show(self):
        from ai_agents.council_models import (CouncilClaim, CouncilSession,
                                              CouncilVoice)
        from django.utils import timezone
        from tests.test_council_sitting import switch
        switch("council_bots")
        s = CouncilSession.objects.create(origin="bot", status="done",
                                          symbol="EURUSD", side="BUY",
                                          asset_class="forex",
                                          regime="trending", truth="replay",
                                          truth_r=1.25, y=1,
                                          graded_at=timezone.now(),
                                          p_chair=0.7, p_mean=0.6,
                                          p_weighted=0.65)
        row = CouncilVoice.objects.create(
            session=s, voice="emperor", wave=3, status="spoke",
            verdict="fight_smaller",
            answer={"verdict": "fight_smaller", "commit": 0.5})
        CouncilClaim.objects.create(session=s, voice=row, voice_key="emperor",
                                    kind="work", p=0.7, y=1, brier=0.09,
                                    grade="right", graded_at=timezone.now(),
                                    regime="trending", asset_class="forex")
        self.client.force_login(self.staff)
        resp = self.client.get("/council/?class=forex")
        self.assertContains(resp, "Bot orders: <strong>ON</strong>")
        self.assertContains(resp, "not sent", msg_prefix="no trade linked")
        self.assertContains(resp, "The Emperor: fight smaller, commit 50%")
        self.assertContains(resp, "+1.25R (replayed)")
        self.assertContains(resp, "Brier 0.090 over 1 graded sittings")
        self.assertNotContains(resp, "No call graded yet")

    def test_a_sitting_graded_without_an_r_says_not_measured(self):
        """grade_session is done with a repeat or a sitting with no bars:
        it never says "not graded yet" of it again."""
        from io import StringIO

        from django.core.management import call_command
        from django.utils import timezone

        from ai_agents.council_models import CouncilSession
        CouncilSession.objects.create(
            origin="bot", status="record", symbol="BTCUSD", side="BUY",
            graded_at=timezone.now(), grade_notes="a repeat of session #4")
        CouncilSession.objects.create(origin="bot", status="record",
                                      symbol="ETHUSD", side="SELL")
        self.client.force_login(self.staff)
        resp = self.client.get("/council/")
        self.assertContains(resp, "BTCUSD BUY · The Emperor: silent · "
                                  "record · not measured (a repeat of "
                                  "session #4)")
        self.assertContains(resp, "ETHUSD SELL · The Emperor: silent · "
                                  "record · not graded yet")
        out = StringIO()
        call_command("council", "show", stdout=out)
        self.assertIn("BTCUSD BUY [record] not measured (a repeat of "
                      "session #4)", out.getvalue())
        self.assertIn("ETHUSD SELL [record] not graded yet", out.getvalue())

    def test_the_record_shows_each_voices_base_rate(self):
        from ai_agents.council_models import (CouncilClaim, CouncilSession,
                                              CouncilVoice)
        from django.utils import timezone
        s = CouncilSession.objects.create(origin="bot", status="done",
                                          symbol="EURUSD",
                                          asset_class="forex")
        row = CouncilVoice.objects.create(session=s, voice="gambler",
                                          wave=1, status="spoke")
        now = timezone.now()
        for y in (1, 1, 1, 0, 0, 0, 0, 0, 0, 0):
            CouncilClaim.objects.create(
                session=s, voice=row, voice_key="gambler", kind="work",
                p=0.3, y=y, brier=(0.3 - y) ** 2, grade="right",
                graded_at=now, regime="trending", asset_class="forex")
        self.client.force_login(self.staff)
        resp = self.client.get("/council/")
        self.assertContains(resp, "Base rate")
        # 30% of its graded calls came true; always saying 30% is the
        # reference Brier 0.21, and saying it is exactly neutral
        self.assertContains(resp, '<td class="num" data-role="base-rate">'
                                  '30% (ref 0.210)</td>', html=False)
        self.assertContains(resp, "Brier 0.21 against 0.21 for always "
                                  "saying the base rate")

    def test_the_benchmarks_say_what_they_leave_out(self):
        from ai_agents.council_models import CouncilSession
        from django.utils import timezone
        now = timezone.now()
        CouncilSession.objects.create(origin="bot", status="done",
                                      symbol="X", p_chair=0.9, p_mean=0.9,
                                      p_weighted=0.9, y=1, graded_at=now)
        CouncilSession.objects.create(origin="bot", status="partial",
                                      symbol="X", p_chair=None, p_mean=0.9,
                                      p_weighted=None, y=0, graded_at=now)
        self.client.force_login(self.staff)
        resp = self.client.get("/council/")
        self.assertContains(resp, "The council, plain average: Brier 0.010 "
                                  "over 1 graded sittings")
        self.assertContains(resp, "1 graded sitting without the Emperor's "
                                  "call or the weights are left out of all "
                                  "three.")


class TheCardTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        from tests.test_risk_limits_bind import _config
        cls.user = get_user_model().objects.create_user("csf_card",
                                                        password="x")
        cls.cfg = _config(cls.user, asset_class="crypto", mode="live")

    def _trade(self, status="OPEN"):
        from bot_program.models import AssetBotTrade
        return AssetBotTrade.objects.create(
            config=self.cfg, asset_class="crypto", symbol="BTCUSD",
            side="BUY", qty=Decimal("0.01"), entry_price=Decimal("60000"),
            stop_loss=Decimal("59100"), take_profit=Decimal("61800"),
            status=status, paper=False)

    def test_the_card_shows_the_sitting_on_its_trade(self):
        from ai_agents.council_models import CouncilSession, CouncilVoice
        t = self._trade()
        s = CouncilSession.objects.create(origin="bot", status="done",
                                          trade=t, symbol="BTCUSD",
                                          side="BUY", regime="trending")
        CouncilVoice.objects.create(session=s, voice="executioner", wave=0,
                                    status="copied", verdict="veto",
                                    answer={"verdict": "veto",
                                            "conviction": 0.9,
                                            "killer": "fights the trend"})
        CouncilVoice.objects.create(session=s, voice="emperor", wave=3,
                                    status="spoke", verdict="refuse",
                                    answer={"verdict": "refuse"},
                                    weight_seen=1.0,
                                    weight_reason="neutral: 0 graded calls "
                                                  "in this cell, 10 needed")
        CouncilVoice.objects.create(session=s, voice="gambler", wave=1,
                                    status="late", answer={"verdict": "press"})
        CouncilVoice.objects.create(session=s, voice="skeptic", wave=2,
                                    status="silent", why="timeout")
        self.client.force_login(self.user)
        resp = self.client.get(f"/forensics/{t.id}/")
        self.assertEqual(resp.status_code, 200)
        for words in ("The council at entry",
                      "on the bot&#x27;s order · regime trending · the "
                      "Emperor: refuse the battle",
                      "Not graded yet: the trade is still open.",
                      "The Executioner: would veto it. fights the trend.",
                      "The Gambler: late, not heard by the chair.",
                      "The Skeptic: silent (timeout)",
                      "Shadow: the council is graded on what the market "
                      "does next."):
            with self.subTest(words=words):
                self.assertContains(resp, words)

    def test_a_graded_card_names_who_was_right(self):
        from django.utils import timezone

        from ai_agents.council_models import (CouncilClaim, CouncilSession,
                                              CouncilVoice)
        t = self._trade(status="CLOSED")
        s = CouncilSession.objects.create(
            origin="ticket", status="done", trade=t, symbol="BTCUSD",
            side="BUY", truth="realized", truth_r=-1.0,
            graded_at=timezone.now())
        for voice, grade in (("executioner", "right"), ("champion", "wrong"),
                             ("gambler", "unresolvable")):
            row = CouncilVoice.objects.create(session=s, voice=voice, wave=1,
                                              status="spoke",
                                              answer={"verdict": "x"})
            CouncilClaim.objects.create(session=s, voice=row, voice_key=voice,
                                        kind="stance", grade=grade)
        self.client.force_login(self.user)
        resp = self.client.get(f"/forensics/{t.id}/")
        self.assertContains(resp, "on the ticket you asked about")
        self.assertContains(resp, "Graded: -1.00R (realized). Right: The "
                                  "Executioner. Wrong: The Champion. Not "
                                  "measured: The Gambler.")

    def test_a_closed_trade_not_yet_graded_says_graded_nightly(self):
        from ai_agents.council_models import CouncilSession
        t = self._trade(status="CLOSED")
        CouncilSession.objects.create(origin="bot", status="done", trade=t,
                                      symbol="BTCUSD", side="BUY")
        self.client.force_login(self.user)
        resp = self.client.get(f"/forensics/{t.id}/")
        self.assertContains(resp, "Not graded yet: the council is graded "
                                  "nightly.")
        self.assertNotContains(resp, "the trade is still open")

    def test_a_card_graded_without_an_r_says_not_measured(self):
        from django.utils import timezone

        from ai_agents.council_models import CouncilSession
        t = self._trade(status="CLOSED")
        CouncilSession.objects.create(
            origin="bot", status="done", trade=t, symbol="BTCUSD",
            side="BUY", graded_at=timezone.now(),
            grade_notes="realized R unpriced; no bars")
        self.client.force_login(self.user)
        resp = self.client.get(f"/forensics/{t.id}/")
        self.assertContains(resp, "Graded: not measured (realized R "
                                  "unpriced; no bars).")
        self.assertNotContains(resp, "graded nightly")
        self.assertNotContains(resp, "Not graded yet")

    def test_no_sitting_no_card(self):
        t = self._trade()
        self.client.force_login(self.user)
        resp = self.client.get(f"/forensics/{t.id}/")
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, "The council at entry")


class TheSwitchesTests(TestCase):

    def test_two_agent_switches_seeded_off_and_never_live_money(self):
        from core.platform_control import (BULK_ENABLE_EXEMPT,
                                           DEFAULT_COMPONENTS,
                                           LIVE_MONEY_SWITCHES,
                                           PlatformComponent,
                                           seed_components)
        seed_components()
        rows = {c["key"]: c for c in DEFAULT_COMPONENTS}
        for key in ("council_bots", "council_ticket"):
            with self.subTest(key=key):
                self.assertFalse(PlatformComponent.objects.get(
                    key=key).is_enabled)
                self.assertEqual(rows[key]["category"], "agent")
                self.assertLessEqual(len(rows[key]["description"]), 300)
                self.assertTrue(rows[key]["description"].startswith(
                    "Off (default)."))
                self.assertNotIn(key, LIVE_MONEY_SWITCHES)
                self.assertNotIn(key, BULK_ENABLE_EXEMPT)
                self.assertFalse(key.endswith("_live"))


class TheWordsTests(SimpleTestCase):

    def test_a_voice_still_answering_is_not_called_silent(self):
        from ai_agents.agents.council import voice_line
        self.assertEqual(voice_line({"name": "The Opportunist",
                                     "status": "asked", "why": ""}),
                         "The Opportunist: not answered yet")
        self.assertEqual(voice_line({"name": "The Skeptic",
                                     "status": "asked", "why": "timeout"}),
                         "The Skeptic: silent (timeout)")
        self.assertEqual(voice_line({"name": "The Fixer", "status": "silent",
                                     "why": "ValueError"}),
                         "The Fixer: silent (ValueError)")
        js = (REPO / "static" / "js" / "sv-council.js").read_text(
            encoding="utf-8")
        body = js[js.index("function voiceLine("):js.index("function render(")]
        asked = body.index("if (v.status === 'asked' && !v.why) return "
                           "v.name + ': not answered yet';")
        self.assertLess(asked, body.index("v.status === 'silent' ||"))

    def test_every_new_sentence_is_ascii_english(self):
        from ai_agents.agents import council as C
        sentences = [C.COUNCIL_LAW, C.OFF_WORDS, C.NO_KEY_WORDS,
                     C.PAPER_WORDS, C.BUSY_WORDS, C.FOOTER_WORDS,
                     C.HINT_WORDS, C.cap_words(12), C.budget_words("x"),
                     C.STOP_REFUSED, *C.FLAW_WORDS.values(),
                     *C.VOICE_NAMES.values()]
        samples = {
            "executioner": [{"verdict": v, "size_scale": 0.5}
                            for v in ("pass", "cut", "veto")],
            "champion": [{"verdict": v} for v in ("back", "neutral")],
            "opportunist": [{"verdict": "seize"}, {"verdict": "pass"},
                            {"verdict": "elsewhere", "alternative": {
                                "symbol": "EURUSD", "direction": "up",
                                "horizon_hours": 24}}],
            "striker": [{"verdict": "take"}, {"verdict": "skip"},
                        {"verdict": "wait", "trigger": {
                            "level": 1.1, "within_hours": 6}}],
            "fixer": [{"verdict": "no_fix"},
                      {"verdict": "fix", "fix": {"kind": "stop",
                                                 "value": 1.0}},
                      {"verdict": "fix", "fix": {"kind": "hedge",
                                                 "words": "hedge"}},
                      {"verdict": "fix", "fix_refused": "nope"}],
            "gambler": [{"verdict": v, "elite_worthy": True}
                        for v in ("all_in", "press", "normal", "small")],
            "skeptic": [{"verdict": "sound"},
                        {"verdict": "shaky", "target": "executioner",
                         "flaw": "noise"},
                        {"verdict": "unfounded", "target": "champion",
                         "flaw": "thin_sample"}],
            "awakened": [{"verdict": "trap", "prey": "late longs"},
                         {"verdict": "clean", "level": 1.2,
                          "within_hours": 4, "touch_ok": True},
                         {"verdict": "unread"}],
            "theorist": [{"verdict": "serves", "theory_id": 3,
                          "posted_theory": 4},
                         {"verdict": "contradicts", "theory_id": 3},
                         {"verdict": "none"}],
            "emperor": [{"verdict": "fight"}, {"verdict": "refuse"},
                        {"verdict": "fight_smaller", "commit": 0.5}],
        }
        for voice, answers in samples.items():
            for a in answers:
                sentences.append(C.verdict_words(voice, a))
        self.assertIn("the evidence is shaky: the Executioner, noise",
                      sentences)
        self.assertIn("fight smaller, commit 50%", sentences)
        self.assertIn("better elsewhere: EURUSD up within 24 hours",
                      sentences)
        for text in sentences:
            with self.subTest(text=text[:40]):
                self.assertTrue(text.isascii(), text)
                for french in (" le ", " la ", " les ", " des ", " une "):
                    self.assertNotIn(french, f" {text} ")

    def test_no_council_module_reaches_an_alarm_path(self):
        for path in ("ai_agents/agents/council.py",
                     "ai_agents/council_grading.py",
                     "ai_agents/council_models.py",
                     "dashboard/views_council.py",
                     "ai_agents/management/commands/council.py",
                     "static/js/sv-council.js"):
            text = (REPO / path).read_text(encoding="utf-8")
            for banned in ("bot_program.alarm", "telegram_eye", "alerts.",
                           "notify_"):
                with self.subTest(path=path, banned=banned):
                    self.assertNotIn(banned, text)

    def test_the_wall_names_the_council_beside_the_debate(self):
        wall = (REPO / "templates" / "landing" / "the_wall.html").read_text(
            encoding="utf-8")
        agents = wall[wall.index('id="agents"'):]
        agents = agents[:agents.index("</section>")]
        self.assertIn("Emperor", agents)
        self.assertIn("Executioner", agents)
        self.assertIn("never raise it", agents)
        self.assertIn("its weight earned only by its record", agents)

    def test_the_book_tells_of_the_council(self):
        from core import book_content as book
        found = [i["text"] for c in book.CHAPTERS for i in c.get("items", [])
                 if i.get("title") == "The council"]
        self.assertEqual(len(found), 1)
        self.assertIn("eight more AI voices", found[0])
        self.assertIn("ten of its calls", found[0])
        # the eight bind nothing; the debate's two keep the debate's powers
        # (the card above: a cut, never below a quarter, or a refusal once
        # 30 trades are graded), so "no voice" would be false
        self.assertIn("none of them moves an order, a size, a stop or a limit",
                      found[0])
        self.assertIn("keep only the debate's own powers", found[0])
        self.assertNotIn("no voice moves", found[0])
        # never "every" order: the bot lane stops at 12 a day and at the
        # day's AI budget (COUNCIL_BOT_SITTINGS_PER_DAY, run_wave)
        self.assertIn("(up to twelve a day, within the day's AI budget)",
                      found[0])
        self.assertNotIn("every real-money bot order", found[0])
        from core.platform_control import DEFAULT_COMPONENTS
        bots = next(c for c in DEFAULT_COMPONENTS
                    if c["key"] == "council_bots")
        self.assertIn("once a LIVE bot order has left (up to 12 a day)",
                      bots["description"])
