"""THE HAND OF THE EMPEROR (2026-10-16, ai_agents/agents/council.py and
ai_agents/council_grading.py).

The operator: "Maybe a voice that predicts better should gain in
influence, no? Maybe it can be listened to more by the Emperor." One seat
per (regime, class), held by the voice with the best MEASURED weight in
that very cell (at least COUNCIL_HAND_MIN_N graded calls there and a
weight of at least COUNCIL_HAND_MIN_FACTOR; ties to more graded calls,
then the lower Brier), lost automatically when another does better or it
falls below the bar. The chair reads the Hand and its record and says why
when he overrules it; every overruling is graded. The other voices still
read arguments, not records: only the Skeptic is told which voice is the
most trusted, to attack its evidence first.

Run with:  python manage.py test tests.test_council_hand
"""
import re
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from tests.test_council_sitting import _Sitting
from tests.test_council_voices import parse
from tests.test_council_weights import _claims


def _good(voice, n, *, regime="trending", asset_class="crypto", p=0.9):
    """n calls on an even base rate, every one on the right side at p:
    Brier (1 - p)^2 against 0.25 for always saying the base rate."""
    _claims(voice, n - n // 2, p=p, y=1, regime=regime,
            asset_class=asset_class)
    _claims(voice, n // 2, p=1.0 - p, y=0, regime=regime,
            asset_class=asset_class)


def _bad(voice, n, *, regime="trending", asset_class="crypto"):
    """n calls on the wrong side at 0.9."""
    _claims(voice, n, p=0.9, y=0, regime=regime, asset_class=asset_class)


def _hand(regime="trending", asset_class="crypto"):
    from ai_agents.council_grading import hand_of, voice_weights
    return hand_of(voice_weights(regime, asset_class), regime, asset_class)


class TheSeatTests(TestCase):

    def test_a_hand_is_earned_with_thirty_calls_in_the_cell_and_a_trusted_weight(self):
        from ai_agents.agents.council import (COUNCIL_HAND_MIN_FACTOR,
                                              COUNCIL_HAND_MIN_N)
        from ai_agents.calibration import trust_from_brier
        self.assertEqual(COUNCIL_HAND_MIN_N, 30)
        self.assertEqual(COUNCIL_HAND_MIN_FACTOR, trust_from_brier(0.20))
        self.assertEqual(COUNCIL_HAND_MIN_FACTOR, 1.15)
        _good("gambler", 30)
        h = _hand()
        self.assertEqual((h["voice"], h["name"], h["factor"], h["n"],
                          h["cell"], h["why_empty"]),
                         ("gambler", "The Gambler", 1.30, 30,
                          "trending on crypto", ""))
        self.assertIn("measured in trending on crypto, 30 graded calls",
                      h["reason"])
        self.assertAlmostEqual(h["brier"], 0.01)

    def test_twenty_nine_calls_or_a_neutral_weight_holds_no_seat(self):
        from ai_agents.council_grading import voice_weights
        _good("gambler", 29)                       # 1.30, n 29
        _good("champion", 30, p=0.5)               # Brier 0.25: 1.00
        _claims("opportunist", 15, p=0.6, y=1, asset_class="crypto")
        _claims("opportunist", 15, p=0.6, y=0, asset_class="crypto")
        w = voice_weights("trending", "crypto")
        self.assertEqual((w["gambler"]["factor"], w["gambler"]["n"]),
                         (1.30, 29))
        self.assertEqual((w["champion"]["factor"], w["champion"]["n"]),
                         (1.00, 30))
        self.assertEqual((w["opportunist"]["factor"], w["opportunist"]["n"]),
                         (0.80, 30))
        h = _hand()
        self.assertEqual(h["voice"], "")
        self.assertEqual(h["why_empty"], "no voice has earned it yet")

    def test_a_record_measured_outside_the_cell_holds_no_seat(self):
        from ai_agents.council_grading import voice_weights
        _good("gambler", 40, asset_class="forex")
        _good("gambler", 5, asset_class="crypto")
        w = voice_weights("trending", "crypto")["gambler"]
        self.assertEqual((w["rung"], w["factor"], w["n"]), ("regime", 1.30, 45))
        self.assertEqual(_hand()["voice"], "", "a fallback rung never counts")
        _good("gambler", 7, asset_class="crypto")
        w = voice_weights("trending", "crypto")["gambler"]
        self.assertEqual((w["rung"], w["n"]), ("regime_class", 12))
        self.assertEqual(_hand()["voice"], "", "under thirty in the cell")

    def test_the_hand_is_lost_when_another_does_better_and_ties_go_to_more_calls_then_the_lower_brier(self):
        # more graded calls in the cell win a tie of weight
        _good("champion", 30)
        _good("gambler", 34)
        self.assertEqual(_hand()["voice"], "gambler")
        # at equal weight and equal calls, the lower Brier
        _good("champion", 30, asset_class="stock", p=0.9)     # Brier 0.01
        _good("gambler", 30, asset_class="stock", p=1.0)      # Brier 0.00
        self.assertEqual(_hand(asset_class="stock")["voice"], "gambler")
        # another does better: the seat moves
        _good("champion", 6)                                  # n 36 > 34
        self.assertEqual(_hand()["voice"], "champion")
        # its record falls: the seat moves back
        _bad("champion", 6)
        h = _hand()
        self.assertEqual(h["voice"], "gambler")
        # everyone below the bar: the seat is empty
        _bad("gambler", 10)
        _bad("champion", 6)
        h = _hand()
        self.assertEqual((h["voice"], h["why_empty"]),
                         ("", "no voice has earned it yet"))

    def test_the_emperor_never_holds_his_own_hand(self):
        _claims("emperor", 15, p=1.0, y=1, asset_class="crypto")
        _claims("emperor", 15, p=0.0, y=0, asset_class="crypto")
        self.assertEqual(_hand()["voice"], "")
        _good("striker", 30)
        self.assertEqual(_hand()["voice"], "striker")

    def test_an_unknown_regime_measures_no_cell(self):
        _good("gambler", 40, regime="unknown")
        h = _hand(regime="unknown")
        self.assertEqual(h["voice"], "")
        self.assertEqual(h["why_empty"], "no voice has earned it yet: the "
                                         "regime is unknown, so no cell is "
                                         "measured")

    def test_the_cells_of_the_page(self):
        from ai_agents.council_grading import hands
        _good("gambler", 30)
        _good("champion", 12, asset_class="forex")
        _good("fixer", 30, regime="unknown")
        rows = {(h["regime"], h["asset_class"]): h for h in hands()}
        self.assertEqual(set(rows), {("trending", "crypto"),
                                     ("trending", "forex")})
        self.assertEqual(rows[("trending", "crypto")]["voice"], "gambler")
        self.assertEqual(rows[("trending", "forex")]["why_empty"],
                         "no voice has earned it yet")
        self.assertEqual([(h["regime"], h["asset_class"])
                          for h in hands(asset_class="forex")],
                         [("trending", "forex")])


class TheWordsTests(SimpleTestCase):

    def test_an_empty_seat_says_no_voice_has_earned_it_yet(self):
        from ai_agents.agents.council import hand_text
        from ai_agents.council_grading import hand_of
        empty = hand_of({}, "trending", "crypto")
        self.assertEqual(
            hand_text(empty),
            "THE HAND OF THE EMPEROR (trending on crypto): no voice has "
            "earned it yet (the seat needs 30 graded calls in this regime "
            "and class and a weight of at least 1.15).")
        unknown = hand_text(hand_of({}, "unknown", "crypto"))
        self.assertIn("no voice has earned it yet", unknown)
        self.assertIn("the regime is unknown", unknown)

    def test_a_seat_held_says_its_record_and_its_side(self):
        from ai_agents.agents.council import hand_text
        hand = {"cell": "trending on crypto", "voice": "gambler",
                "name": "The Gambler", "factor": 1.3, "n": 34,
                "reason": "measured in trending on crypto, 34 graded calls, "
                          "Brier 0.06 against 0.25 for always saying the "
                          "base rate", "why_empty": ""}
        self.assertEqual(
            hand_text(dict(hand, side="for")),
            "THE HAND OF THE EMPEROR (trending on crypto): The Gambler holds "
            "it.\n  Its record: weight 1.30, measured in trending on crypto, "
            "34 graded calls, Brier 0.06 against 0.25 for always saying the "
            "base rate.\n  Its side in this sitting: for the trade. When "
            "your verdict goes against it, say why in hand_why.")
        self.assertIn("Its side in this sitting: against the trade.",
                      hand_text(dict(hand, side="against")))
        self.assertIn("Its side in this sitting: none (silent, or no side "
                      "taken): there is nothing of it to overrule.",
                      hand_text(dict(hand, side="")))


class TheOverrulingTests(SimpleTestCase):

    def _e(self, verdict, side="for", voice="gambler", **kw):
        return parse("emperor", dict({"verdict": verdict, "commit": 0.5,
                                      "p_work": 0.4}, **kw),
                     hand={"voice": voice, "side": side})

    def test_an_overruling_is_measured_by_code_and_needs_a_reason(self):
        out = self._e("refuse", hand_why="the record is a bull market's")
        self.assertEqual((out["hand"], out["hand_side"], out["hand_overruled"],
                          out["hand_why"], out["hand_note"]),
                         ("gambler", "for", True,
                          "the record is a bull market's", ""))
        out = self._e("refuse")
        self.assertTrue(out["hand_overruled"])
        self.assertEqual(out["hand_note"],
                         "overruled the Hand without saying why")
        out = self._e("fight", hand_why="ignored")
        self.assertEqual((out["hand_overruled"], out["hand_why"],
                          out["hand_note"]), (False, "", ""))
        # fight_smaller commits less than the trade: against a Hand "for"
        self.assertTrue(self._e("fight_smaller")["hand_overruled"])
        self.assertFalse(self._e("refuse", side="against")["hand_overruled"])
        self.assertTrue(self._e("fight", side="against")["hand_overruled"])
        # a silent Hand, or one that took no side, has nothing to overrule
        out = self._e("refuse", side="")
        self.assertEqual((out["hand_side"], out["hand_overruled"]), ("", False))
        # leaving the Hand off his own "overruled" list changes nothing
        out = self._e("refuse", overruled=[], followed=["gambler"])
        self.assertTrue(out["hand_overruled"])
        out = self._e("refuse", overruled=[{"voice": "gambler", "why": "w"}])
        self.assertTrue(out["hand_overruled"])

    def test_no_hand_in_the_brief_is_an_empty_seat(self):
        from tests.test_council_voices import CTX
        out = parse("emperor", {"verdict": "refuse"})
        self.assertNotIn("hand", CTX)
        self.assertEqual((out["hand"], out["hand_side"], out["hand_overruled"],
                          out["hand_why"], out["hand_note"]),
                         ("", "", False, "", ""))
        long = self._e("refuse", hand_why="x" * 900)
        self.assertEqual(len(long["hand_why"]), 200)


class TheGradingTests(TestCase):
    """The Emperor against his Hand: when they disagreed, who was right."""

    @classmethod
    def setUpTestData(cls):
        from django.contrib.auth import get_user_model
        from tests.test_risk_limits_bind import _config
        cls.user = get_user_model().objects.create_user("ch_g", password="x")
        cls.cfg = _config(cls.user, asset_class="stock", mode="live")

    def _sat(self, r, *, emperor="refuse", hand="gambler", hand_side="for",
             overruled=True, why="w", hand_kind="stance"):
        from ai_agents.council_models import CouncilVoice
        from tests.test_council_grading import _claim, _grade, _session
        from tests.test_council_grading import _Rows
        t = _Rows._trade(self, r=r)
        s = _session(trade=t)
        commit = {"fight": 1.0, "fight_smaller": 0.5, "refuse": 0.0}[emperor]
        _claim(s, "emperor", "battle", payload={"commit": commit,
                                                "verdict": emperor})
        if hand_kind == "stance":
            _claim(s, hand, "stance", stance=hand_side,
                   payload={"verdict": "press"})
        CouncilVoice.objects.filter(session=s, voice="emperor").update(
            answer={"verdict": emperor, "commit": commit, "hand": hand,
                    "hand_side": hand_side, "hand_overruled": overruled,
                    "hand_why": why if overruled else "",
                    "hand_note": "" if why or not overruled else
                    "overruled the Hand without saying why"})
        return _grade(s)

    def test_an_overruling_is_graded_both_ways(self):
        from ai_agents.council_grading import record_matrix
        self._sat(-1.0)                       # the Emperor was right
        self._sat(2.0, why="")                # the Hand was right
        self._sat(0.1)                        # inside a quarter R
        self._sat(1.0, emperor="fight", overruled=False)   # they agreed
        a = record_matrix()["against_hand"]
        self.assertEqual((a["overruled"], a["graded"], a["emperor_right"],
                          a["hand_right"], a["unresolved"], a["pending"],
                          a["no_reason"]), (3, 2, 1, 1, 1, 0, 1))
        self.assertEqual(a["agreed"], {"n": 1, "right": 1})
        self.assertEqual(a["by_voice"]["gambler"],
                         {"graded": 2, "emperor_right": 1, "hand_right": 1})

    def test_the_skeptic_as_hand_is_overruled_when_the_chair_sides_with_his_target(self):
        from ai_agents.agents.council import claim_side
        from ai_agents.council_grading import record_matrix
        from ai_agents.council_models import CouncilSession, CouncilVoice
        from tests.test_council_grading import _claim, _grade, _session
        from tests.test_council_grading import _Rows
        s = _session(trade=_Rows._trade(self, r=2.0))
        _claim(s, "champion", "stance", stance="for",
               payload={"verdict": "back"})
        _claim(s, "skeptic", "attack", p=0.8,
               payload={"target": "champion", "flaw": "noise"})
        _claim(s, "emperor", "battle", payload={"commit": 1.0})
        self.assertEqual(claim_side(s, "skeptic"), "against")
        self.assertEqual(claim_side(s, "champion"), "for")
        self.assertEqual(claim_side(s, "gambler"), "", "never spoke")
        out = parse("emperor", {"verdict": "fight"},
                    hand={"voice": "skeptic", "side": "against"})
        self.assertTrue(out["hand_overruled"])
        CouncilVoice.objects.filter(session=s, voice="emperor").update(
            answer=out)
        _grade(CouncilSession.objects.get(id=s.id))
        a = record_matrix()["against_hand"]
        # the trade won: the Champion was right, the attack on it wrong
        self.assertEqual((a["graded"], a["emperor_right"], a["hand_right"]),
                         (1, 1, 0))
        self.assertEqual(s.claims.get(kind="attack").grade, "wrong")

    def test_the_side_of_a_work_claim_and_of_a_silent_voice(self):
        from ai_agents.agents.council import claim_side, emperor_side
        from ai_agents.council_models import CouncilVoice
        from tests.test_council_grading import _claim, _session
        s = _session()
        _claim(s, "theorist", "work", p=0.7)
        _claim(s, "awakened", "work", p=0.3)
        _claim(s, "opportunist", "work", p=0.5)
        _claim(s, "striker", "work", p=0.9)
        CouncilVoice.objects.filter(session=s, voice="striker").update(
            status="late")
        self.assertEqual([claim_side(s, v) for v in
                          ("theorist", "awakened", "opportunist", "striker")],
                         ["for", "against", "", ""])
        self.assertEqual([emperor_side(v) for v in
                          ("fight", "fight_smaller", "refuse", "")],
                         ["for", "against", "against", ""])


class TheChairTests(_Sitting):

    def setUp(self):
        from ai_agents.council_models import CouncilSession
        super().setUp()
        CouncilSession.objects.filter(id=self.sid).update(regime="trending")

    def test_the_chair_reads_the_hand_and_its_record(self):
        _good("gambler", 34)
        rec, s = self.sit()
        brief = rec.briefs["emperor"]
        self.assertIn("THE HAND OF THE EMPEROR (trending on crypto): The "
                      "Gambler holds it.", brief)
        self.assertIn("Its record: weight 1.30, measured in trending on "
                      "crypto, 34 graded calls", brief)
        self.assertIn("Its side in this sitting: for the trade", brief)
        self.assertEqual((s.hand["voice"], s.hand["side"], s.hand["n"]),
                         ("gambler", "for", 34))
        self.assertEqual((s.hand["trusted"], s.hand["trusted_why"]),
                         ("gambler", "hand"))
        # the Hand is said on the chair's brief AFTER the record
        self.assertLess(brief.index("THE RECORD"),
                        brief.index("THE HAND OF THE EMPEROR"))

    def test_an_overruling_in_a_sitting_is_measured_from_its_own_sides(self):
        """The chair's ctx carries the Hand and its side as the sitting
        measured them; his answer is read against them by code."""
        import json

        from ai_agents.agents import council as C
        from ai_agents.council_models import CouncilSession
        from tests.test_council_sitting import Recorder
        _good("gambler", 34)
        raw = json.dumps({"verdict": "refuse", "p_work": 0.3,
                          "hand_why": "the stop sits in the pool"})
        seen = {}

        class Chair(C.EmperorAgent):
            """The fake chair reads his answer with the ctx the sitting
            gave him, as the real one does (parse_response)."""

            def run(self, **kw):
                seen.update(self.ctx)
                return C.parse_answer("emperor", raw, self.ctx)

        rec = Recorder()
        with rec.patched(), patch.dict(C.AGENTS, {"emperor": Chair}):
            C.run_sitting(self.sid)
        self.assertEqual(seen["hand"], {"voice": "gambler", "side": "for"})
        s = CouncilSession.objects.get(id=self.sid)
        a = s.voices.get(voice="emperor").answer
        self.assertEqual((a["hand"], a["hand_side"], a["hand_overruled"],
                          a["hand_why"], a["hand_note"]),
                         ("gambler", "for", True,
                          "the stop sits in the pool", ""))

    def test_an_empty_seat_is_said_to_the_chair(self):
        rec, s = self.sit()
        self.assertIn("THE HAND OF THE EMPEROR (trending on crypto): no voice "
                      "has earned it yet", rec.briefs["emperor"])
        self.assertEqual((s.hand["voice"], s.hand["why_empty"]),
                         ("", "no voice has earned it yet"))
        self.assertEqual(s.hand["trusted_why"], "none")

    def test_the_members_briefs_carry_no_records(self):
        _good("gambler", 34)
        afraid = {"level": "afraid", "reasons": ["the governor at its floor"],
                  "inputs": {}, "measured_n": 1, "of": 7, "at": ""}
        with patch("ai_agents.council_mood.people_mood", return_value=afraid):
            rec, s = self.sit()
        self.assertEqual(s.mood, "afraid")
        b = rec.briefs
        self.assertEqual(b["opportunist"], b["gambler"])
        self.assertEqual(b["gambler"], b["awakened"])
        self.assertTrue(b["theorist"].startswith(b["opportunist"] + "\n\n"
                                                 "LIVE THEORIES"))
        self.assertEqual(b["fixer"], b["striker"])
        for v in ("opportunist", "gambler", "awakened", "theorist", "fixer",
                  "striker"):
            for word in ("THE RECORD", "weight ", "graded calls", "Brier",
                         "THE HAND OF THE EMPEROR", "the people's mood",
                         "MOST TRUSTED"):
                with self.subTest(voice=v, word=word):
                    self.assertNotIn(word, b[v])
        self.assertIn("the people's mood: afraid", b["emperor"])

    def _skeptic_line(self, how, line):
        from ai_agents.agents.council import trusted_text
        rec, s = self.sit({"skeptic": parse(
            "skeptic", {"verdict": "shaky", "conviction": 0.7,
                        "target": "champion", "flaw": "noise"})})
        self.assertEqual(trusted_text(s.hand), line)
        self.assertEqual(s.hand["trusted_why"], how)
        self.assertEqual(rec.briefs["skeptic"],
                         rec.briefs["fixer"] + "\n\n" + line)
        self.assertNotRegex(line, r"weight|Brier|\d")
        # his grade does not change: his attack is a pending claim on the
        # voice he named, graded as before
        attack = s.claims.get(voice_key="skeptic", kind="attack")
        self.assertEqual((attack.grade, attack.payload["target"]),
                         ("pending", "champion"))

    def test_the_skeptic_is_pointed_at_the_hand_that_spoke_before_him(self):
        _good("gambler", 34)
        self._skeptic_line(
            "hand",
            "THE MOST TRUSTED VOICE: The Gambler, the Hand of the Emperor in "
            "trending on crypto. Attack its evidence first when it gives "
            "you something to attack.")

    def test_a_hand_after_him_points_him_at_the_best_record_before_him(self):
        _good("fixer", 30)                     # the Hand speaks in wave 2
        _good("champion", 12, p=0.65)          # Brier 0.1225: 1.15
        self._skeptic_line(
            "highest",
            "THE MOST TRUSTED VOICE: The Champion, the voice before you with "
            "the best measured record in trending on crypto. Attack its "
            "evidence first when it gives you something to attack.")

    def test_no_earned_trust_names_no_target(self):
        _good("opportunist", 12, p=0.5)        # measured, 1.00: not trust
        self._skeptic_line(
            "none",
            "THE MOST TRUSTED VOICE: none named: no voice before you has "
            "earned trust in trending on crypto. Choose your target on the "
            "evidence alone.")


class ThePromptTests(SimpleTestCase):

    def _prompts(self):
        from ai_agents.agents import council as C
        return {v: cls.__new__(cls).get_system_prompt()
                for v, cls in C.AGENTS.items()}

    def test_the_prompts_carry_the_new_sentences_and_no_member_reads_of_the_hand_or_the_mood(self):
        from ai_agents.agents import council as C
        p = self._prompts()
        for words in ("THE HAND OF THE EMPEROR",
                      "with at least 30 graded calls in this cell and a "
                      "weight of at least 1.15",
                      "A content people is never a reason to press",
                      "never read it as calm", "say why in hand_why",
                      "Every such overruling is graded"):
            with self.subTest(words=words):
                self.assertIn(words, " ".join(p["emperor"].split()))
        self.assertIn('"hand_why":', C.EmperorAgent.SCHEMA)
        self.assertLess(C.EmperorAgent.SCHEMA.index('"hand_why"'),
                        C.EmperorAgent.SCHEMA.index('"plan"'))
        self.assertIn("THE MOST TRUSTED VOICE", p["skeptic"])
        self.assertRegex(p["skeptic"], r"Your lane\s+is the evidence")
        self.assertRegex(p["skeptic"], r"Your grade does not\s+change")
        for v in ("opportunist", "striker", "fixer", "gambler", "awakened",
                  "theorist"):
            for word in ("Hand", "mood", "MOST TRUSTED"):
                with self.subTest(voice=v, word=word):
                    self.assertNotIn(word, p[v])
        for v, text in p.items():
            with self.subTest(voice=v):
                self.assertTrue(text.isascii(), v)
        self.assertIsNone(re.search(r"[{}]", C.EmperorAgent.PROMPT))
