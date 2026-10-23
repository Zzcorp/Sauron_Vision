"""THE ORCS ON TELEGRAM (spec §9.1, O1d): /orc and /orcs on the operator's
own Eye chat, answered by code. No model, no write, no notification.

Pinned here:
  - while `orcs` is ON: /orc N answers the idea (a leg's number too), a
    quoted "orc N" answers without a model, another user's or an unknown
    number names nobody, a missing number says how;
  - the commands that would make an Orc act answer in words and change
    nothing: a question (no ResearchMessage), "stand down", "/orcs off";
  - /orcs lists the ideas on watch, 20 at most, and filters by class;
  - replies carry R and prices only; the stale and rate limits apply;
  - /help lists the two commands while ON;
  - the module writes nothing and sends nothing itself; the alarm bot
    never answers /orc;
  - a dead idea shows its grade.

Run with:  python manage.py test tests.orcs.test_orc_telegram
"""
import ast
import inspect
import re
from decimal import Decimal
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from bot_program import telegram_eye as eye
from tests.orcs.helpers import (_config, _paper_cap, _row, _switch, born)
from tests.test_telegram_eye import GROUP, SEND, _staff, _texts, _update


def _on(on=True):
    _switch("platform_master", True)
    _switch("orcs", on)


class _OrcEye(TestCase):

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        _on()
        self.user = _staff()
        self.cfg = _config(self.user, "commodity", symbols=["XAUUSD"])
        self.row = _row(self.cfg, symbol="XAUUSD", entry="2400", stop="2380",
                        target="2460", paper=False,
                        meta={"broker": "etoro",
                              "care": {"r_now": 0.42, "mfe_r": 0.9,
                                       "soft_stop": 2385.5,
                                       "soft_why": "breakeven"}})
        self.orc = born(self, self.row)
        self.uid = 100

    def said(self, text, *, fresh=True, **kw):
        """handle() one update; `fresh` forgets the chat's rate limit (one
        reply per RATE_S), so a test may say several things in a row."""
        if fresh:
            cache.delete(eye.RATE_KEY.format(chat=GROUP))
        self.uid += 1
        with patch(SEND, return_value=True) as send:
            with self.captureOnCommitCallbacks(execute=True):
                verdict = eye.handle(_update(self.uid, text, **kw))
        return verdict, _texts(send)


class TheOrcCommandTests(_OrcEye):

    def test_slash_orc_on_answers_the_idea(self):
        verdict, texts = self.said(f"/orc {self.row.pk}")
        self.assertEqual(verdict, "answered:orc")
        self.assertEqual(len(texts), 1)
        t = texts[0]
        self.assertIn(f"Orc #{self.row.pk} — XAUUSD long", t)
        self.assertIn("REAL MONEY · bot idea", t)
        self.assertIn("Rank: L0 · Snaga (watches and writes: shadow only) "
                      "· n 0", t)
        self.assertIn("State: Watching: a journal written by code, no "
                      "model.", t)
        self.assertIn("R at the last tick +0.42R · best +0.90R", t)
        self.assertIn("Stops: eToro holds 2380.00 · the care&#x27;s soft "
                      "stop 2385.50 (breakeven)", t)
        self.assertIn("Thesis: the entry&#x27;s own record", t)
        self.assertIn("No plan yet: Orcs write plans once they reason.", t)
        self.assertIn("Last fact ", t)
        self.assertIn("Model calls today: 0", t)
        self.assertIn(f"Page: /orcs/{self.row.pk}/", t)

    def test_quoted_orc_on_answers_without_a_model(self):
        with patch("brain.research_agent.begin_ask",
                   side_effect=AssertionError("a model")):
            verdict, texts = self.said(f'"orc {self.row.pk}"')
        self.assertEqual(verdict, "answered:orc")
        self.assertIn(f"Orc #{self.row.pk}", texts[0])

    def test_a_leg_number_resolves_to_its_idea(self):
        from bot_program.orcs.models import OrcLeg
        add = _row(self.cfg, symbol="XAUUSD", entry="2410", stop="2390",
                   paper=False, meta={"broker": "etoro"})
        OrcLeg.objects.create(orc=self.orc, trade=add, kind="add", seq=2)
        verdict, texts = self.said(f"/orc #{add.pk}")
        self.assertIn(f"Orc #{self.row.pk} — XAUUSD long", texts[0])

    def test_an_unknown_or_anothers_number_names_nobody(self):
        other = _staff("Other", chat="-4000000002")
        ocfg = _config(other, "commodity", symbols=["XAGUSD"])
        orow = _row(ocfg, symbol="XAGUSD")
        born(self, orow)
        for n in (orow.pk, 999999):
            verdict, texts = self.said(f"/orc {n}")
            self.assertEqual(texts[0].count("No Orc numbered"), 1)
            self.assertIn(f"No Orc numbered {n} in your book: /orcs lists "
                          f"them.", texts[0])
            self.assertNotIn("XAGUSD", texts[0])
            self.assertNotIn("Other", texts[0])

    def test_no_number_says_how(self):
        for text in ("/orc", "/orc gold"):
            verdict, texts = self.said(text)
            self.assertIn("Give the Orc&#x27;s number, as /orcs lists it: "
                          "/orc &lt;number&gt;.", texts[0])

    def test_a_question_calls_no_model_and_writes_nothing(self):
        from brain.research_models import ResearchMessage
        from bot_program.orcs.models import OrcJournal
        before = OrcJournal.objects.count()
        with patch("brain.research_agent.begin_ask",
                   side_effect=AssertionError("a model")):
            verdict, texts = self.said(f"/orc {self.row.pk} why hold?")
        self.assertIn("Orcs do not answer questions yet: none calls a "
                      "model. Ask Sauron instead: /q &lt;question&gt;.",
                      texts[0])
        self.assertEqual(ResearchMessage.objects.count(), 0)
        self.assertEqual(OrcJournal.objects.count(), before)

    def test_stand_down_writes_nothing(self):
        from bot_program.orcs.models import Orc
        before = Orc.objects.values().get(pk=self.orc.pk)
        verdict, texts = self.said(f"/orc {self.row.pk} stand down")
        self.assertIn(f"Nothing to stand down: Orc #{self.row.pk} watches "
                      f"only (L0 · Snaga); the care holds your position.",
                      texts[0])
        self.assertEqual(Orc.objects.values().get(pk=self.orc.pk), before)


class TheOrcsCommandTests(_OrcEye):

    def test_orcs_lists_ideas_capped_at_20(self):
        _paper_cap()
        for _ in range(21):
            born(self, _row(self.cfg, symbol="XAUUSD"))
        verdict, texts = self.said("/orcs")
        t = texts[0]
        self.assertIn("Orcs on watch: 22 (1 real money · 21 simulated)", t)
        self.assertRegex(t, rf"Orc #{self.row.pk} XAUUSD long · REAL MONEY "
                            rf"· L0 Snaga · \S+ \(care \S+\) · ")
        self.assertEqual(t.count("Orc #"), 20)
        self.assertIn("+2 more on the platform", t)

    def test_orcs_filters_by_class(self):
        fx = _config(self.user, "forex", symbols=["EURUSD"])
        born(self, _row(fx, symbol="EURUSD", entry="1.1", stop="1.09",
                        target="1.12"))
        verdict, texts = self.said("/orcs forex")
        self.assertIn("Orcs on watch: 1", texts[0])
        self.assertIn("EURUSD", texts[0])
        self.assertNotIn("XAUUSD", texts[0])
        verdict, texts = self.said("/orcs Commodities")
        self.assertIn("XAUUSD", texts[0])
        verdict, texts = self.said("/orcs metals")
        self.assertIn("No class named metals. Classes: ", texts[0])

    def test_orcs_off_writes_nothing_and_turns_nothing_off(self):
        from core.platform_control import PlatformComponent
        verdict, texts = self.said("/orcs off")
        self.assertIn("Nothing to switch off: no Orc acts on a position; "
                      "each keeps a journal only, and the care holds every "
                      "position.", texts[0])
        self.assertTrue(PlatformComponent.objects.get(key="orcs").is_enabled)

    def test_no_orc_on_watch(self):
        from bot_program.orcs.models import Orc
        Orc.objects.update(state="dead", died_at=timezone.now())
        verdict, texts = self.said("/orcs")
        self.assertIn("No Orc is on watch. Each open position gets one "
                      "within 5 minutes.", texts[0])


class TheRulesTests(_OrcEye):

    def test_replies_carry_r_and_prices_only(self):
        self.orc.r_money = Decimal("123.45")
        self.orc.save(update_fields=["r_money"])
        texts = (self.said(f"/orc {self.row.pk}")[1]
                 + self.said("/orcs")[1])
        self.assertEqual(len(texts), 2)
        self.assertIn(f"Orc #{self.row.pk}", texts[0])
        self.assertIn("Orcs on watch: 1", texts[1])
        for t in texts:
            for word in ("$", "€", "£", "¥", "balance", "equity", "account",
                         "123.45", "qty"):
                self.assertNotIn(word, t)
            self.assertNotRegex(t, r"\b\d+(\.\d+)? (USD|EUR|GBP)\b")

    def test_stale_and_rate_limit_apply(self):
        verdict, texts = self.said(f"/orc {self.row.pk}", age_s=3600)
        self.assertEqual((verdict, texts), ("stale", []))
        cache.clear()
        first, _ = self.said(f"/orc {self.row.pk}")
        second, texts = self.said(f"/orc {self.row.pk}", fresh=False)
        self.assertEqual((first, second), ("answered:orc", "rate_limited"))

    def test_help_on_lists_the_two_commands(self):
        verdict, texts = self.said("/help")
        self.assertIn("/orc NUMBER — one Orc: its thesis, journal and the "
                      "care beside it (no model)", texts[0])
        self.assertIn("/orcs [CLASS] — every Orc on watch, one line each",
                      texts[0])

    def test_a_dead_idea_shows_its_grade(self):
        from bot_program.models import AssetBotTrade
        from bot_program.orcs.models import Orc, OrcGrade
        now = timezone.now()
        # the idea ended because its real-money row closed
        AssetBotTrade.objects.filter(pk=self.row.pk).update(
            status="CLOSED", closed_at=now, exit_price=Decimal("2390"),
            realized_r=-0.5)
        Orc.objects.filter(pk=self.orc.pk).update(state="dead",
                                                  died_at=now)
        OrcGrade.objects.create(orc=self.orc, orc_r_gross=-0.4, ghost_r=0.3,
                                delta_care=-0.7)
        verdict, texts = self.said(f"/orc {self.row.pk}")
        self.assertIn("State: Ended.", texts[0])
        self.assertIn("Graded: the position -0.40R, the care ghost +0.30R; "
                      "Δ against the care -0.70R (shadow: no Orc acted).",
                      texts[0])
        # a closed position holds no stop and no risk: where it closed and
        # the R it booked, nothing else
        self.assertIn("Position closed at 2390.00: booked -0.50R.", texts[0])
        for gone in ("holds", "Stops:", "R at the last tick", "risk "):
            self.assertNotIn(gone, texts[0])

    def test_a_closed_row_with_no_r_says_so(self):
        from bot_program.models import AssetBotTrade
        AssetBotTrade.objects.filter(pk=self.row.pk).update(
            status="CLOSED", closed_at=timezone.now())
        verdict, texts = self.said(f"/orc {self.row.pk}")
        self.assertIn("Position closed: its R is not measured.", texts[0])
        self.assertNotIn("holds", texts[0])

    def test_the_alarm_bot_never_answers_orc(self):
        from bot_program import alarm
        for text in ("/orc 12", "/orcs", '"orc 12"'):
            self.assertEqual(alarm.parse(text), (None, ""))


class TheEdgeTests(_OrcEye):

    def test_a_number_that_is_not_ascii_never_raises(self):
        """str.isdigit() accepts "²" and "①"; int() refuses them. With the
        switch ON, a quoted "orc ²" stays a question to Sauron, as it is
        OFF, and the slash form asks for a number: never a ValueError out
        of parse() or handle()."""
        self.assertEqual(eye.parse('"orc ²"', orcs=True), ("ask", "orc ²"))
        self.assertEqual(eye.parse('"orc ①"', orcs=True), ("ask", "orc ①"))
        self.assertEqual(eye.parse('"orc ²"'), ("ask", "orc ²"))
        asked = []

        def begin_ask(conv, question, **kw):
            asked.append(question)
            raise RuntimeError("stop here")
        with patch("brain.research_agent.begin_ask", begin_ask):
            verdict, texts = self.said('"orc ²"')
        self.assertEqual(verdict, "answered:ask")
        self.assertEqual(len(asked), 1)
        for text in ("/orc ①", "/orc ²", "/orc #①"):
            verdict, texts = self.said(text)
            self.assertEqual(verdict, "answered:orc", text)
            self.assertIn("Give the Orc&#x27;s number", texts[0])
            self.assertNotIn("could not answer", texts[0].lower())

    def test_a_parse_that_fails_stays_a_question(self):
        with patch("bot_program.orcs.surfaces.parse_quoted",
                   side_effect=RuntimeError("boom")), \
                self.assertLogs("bot_program.telegram_eye", level="WARNING"):
            self.assertEqual(eye.parse('"orc 12"', orcs=True),
                             ("ask", "orc 12"))

    def test_the_operators_thesis_is_never_the_last_fact(self):
        from bot_program.orcs import journal
        journal.append(self.orc, "thesis", "Your thesis: gold to 2500",
                       author="operator", body={"thesis": {
                           "source": "operator", "text": "gold to 2500"}})
        verdict, texts = self.said(f"/orc {self.row.pk}")
        t = texts[0]
        self.assertIn("Thesis: yours: gold to 2500", t)
        self.assertIn("Last fact ", t)
        self.assertNotRegex(t, r"Last fact \S+ UTC: Your thesis")

    def test_the_latest_note_and_its_age(self):
        from datetime import timedelta

        from bot_program.orcs.models import Orc
        Orc.objects.filter(pk=self.orc.pk).update(
            latest_note="Nothing new: +0.4R, care BE at 2400.00.",
            latest_note_at=timezone.now() - timedelta(hours=2, minutes=5))
        verdict, texts = self.said(f"/orc {self.row.pk}")
        self.assertIn("Latest note: Nothing new: +0.4R, care BE at 2400.00. "
                      "(2 h ago)", texts[0])

    def test_a_paper_idea_never_says_etoro(self):
        _paper_cap()
        row = _row(self.cfg, symbol="XAUUSD", entry="2400", stop="2380",
                   target="2460", meta={"broker": "paper"})
        born(self, row)
        verdict, texts = self.said(f"/orc {row.pk}")
        t = texts[0]
        self.assertIn("paper · bot idea", t)
        self.assertIn("Stops: the row&#x27;s stop 2380.00", t)
        self.assertNotIn("eToro", t)
        self.assertNotIn("REAL MONEY", t)

    def test_a_demo_idea_counts_as_simulated(self):
        from bot_program.orcs.models import Orc, OrcSeat
        _paper_cap()
        demo_row = _row(self.cfg, symbol="XAUUSD", entry="2400",
                        stop="2380", target="2460")
        demo = born(self, demo_row)
        seat = OrcSeat.objects.create(venue="demo",
                                      asset_class=demo.asset_class,
                                      rule_key="demo_probe")
        Orc.objects.filter(pk=demo.pk).update(seat=seat)
        verdict, texts = self.said("/orcs")
        self.assertIn("Orcs on watch: 2 (1 real money · 1 simulated)",
                      texts[0])
        self.assertRegex(texts[0], rf"Orc #{demo_row.pk} XAUUSD long · demo ")
        verdict, texts = self.said(f"/orc {demo_row.pk}")
        self.assertIn("demo · bot idea", texts[0])
        self.assertNotIn("REAL MONEY", texts[0])

    def test_an_adopted_row_says_its_thesis_is_reconstructed(self):
        row = _row(self.cfg, symbol="XAUUSD", entry="2400", stop="2380",
                   target="2460", paper=False, meta={"broker": "etoro"})
        born(self, row, adopted=True)
        verdict, texts = self.said(f"/orc {row.pk}")
        self.assertIn("Thesis: reconstructed from the row", texts[0])
        self.assertNotIn("the entry&#x27;s own record", texts[0])

    def test_a_demo_seat_names_its_own_venue(self):
        """An OANDA practice row (broker_env "paper", paper=False) sits on
        a demo seat: OANDA holds its stop, never eToro."""
        _paper_cap()
        fx = _config(self.user, "forex", symbols=["EURUSD"], name="fx")
        row = _row(fx, symbol="EURUSD", cls="forex", entry="1.08500",
                   stop="1.08320", target="1.08900", paper=False,
                   meta={"broker": "oanda", "broker_env": "paper"})
        orc = born(self, row)
        self.assertEqual(orc.seat.venue, "demo")
        verdict, texts = self.said(f"/orc {row.pk}")
        t = texts[0]
        self.assertIn("Stops: OANDA practice holds 1.0832", t)
        self.assertNotIn("eToro", t)
        self.assertNotIn("REAL MONEY", t)
        # a live row of another carrier, and one that never named one
        saxo = _row(self.cfg, symbol="XAUUSD", entry="2400", stop="2380",
                    target="2460", paper=False, meta={"broker": "saxo"})
        born(self, saxo)
        verdict, texts = self.said(f"/orc {saxo.pk}")
        self.assertIn("Stops: Saxo holds 2380.00", texts[0])
        self.assertNotIn("eToro", texts[0])
        bare = _row(self.cfg, symbol="XAUUSD", entry="2400", stop="2380",
                    target="2460", paper=False)
        born(self, bare)
        verdict, texts = self.said(f"/orc {bare.pk}")
        self.assertIn("Stops: the venue holds 2380.00", texts[0])

    def test_the_operators_thesis_that_may_name_money_is_withheld(self):
        """PR68's plain words, applied once in notes.slot: /orc says what
        the Horde says."""
        from bot_program.orcs import journal
        text = "Long gold into FOMC, risking $400"
        journal.append(self.orc, "thesis", "Your thesis: " + text,
                       author="operator", body={"thesis": {
                           "source": "operator", "text": text}})
        verdict, texts = self.said(f"/orc {self.row.pk}")
        t = texts[0]
        self.assertIn("Thesis: yours: Withheld: this line may name an "
                      "amount of money.", t)
        self.assertNotIn("400", t)
        self.assertNotIn("FOMC", t)


class TheSourceTests(TestCase):

    def test_surfaces_writes_nothing(self):
        from bot_program.orcs import surfaces
        tree = ast.parse(inspect.getsource(surfaces))
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                names.add(node.attr)
            elif isinstance(node, ast.Name):
                names.add(node.id)
        for banned in ("save", "create", "update", "delete",
                       "select_for_update", "bulk_create", "bulk_update",
                       "get_or_create", "update_or_create", "append_entry",
                       "dispatch_notification", "_send_telegram",
                       "notify_staff", "send_alarm", "begin_ask",
                       "remember", "merge_seen"):
            self.assertNotIn(banned, names, banned)
        self.assertNotIn("journal.append", inspect.getsource(surfaces))

    def test_the_eye_reads_the_switch_only_for_the_orcs(self):
        _on(True)
        user = _staff()
        with patch("bot_program.orcs.switches.orcs_on",
                   side_effect=AssertionError("read")) as read, \
                patch(SEND, return_value=True):
            with self.captureOnCommitCallbacks(execute=True):
                eye.handle(_update(1, "/positions"))
        read.assert_not_called()
        self.assertTrue(user.pk)
        # a parse with the switch off is today's parse
        self.assertEqual(eye.parse("/orc 12"), (None, ""))
        self.assertEqual(eye.parse('"orc 12"'), ("ask", "orc 12"))
        self.assertEqual(eye.parse("/orc 12", orcs=True), ("orc", "12"))
        self.assertEqual(eye.parse('"orcs forex"', orcs=True),
                         ("orcs", "forex"))
        self.assertEqual(eye.parse('"orchids are nice"', orcs=True),
                         ("ask", "orchids are nice"))
        # a quoted question that starts with the word stays a question
        for q in ('"orcs are slow today?"', '"orc of the week?"',
                  '"orcs forex and gold?"'):
            self.assertEqual(eye.parse(q, orcs=True)[0], "ask", q)
        self.assertEqual(eye.parse('"orcs off"', orcs=True), ("orcs", "off"))
        self.assertEqual(eye.parse('"orc #12 stand down"', orcs=True),
                         ("orc", "#12 stand down"))
        self.assertEqual(re.findall(r"(\w+)\.objects\.create\(",
                                    inspect.getsource(eye)),
                         ["ResearchConversation"])
