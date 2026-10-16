"""THE COUNCIL's voices (2026-10-08, ai_agents/agents/council.py).

The operator asked for eight more personalities beside the Executioner
("nothing is possible") and the Champion ("all is good"): the
Opportunist, the Striker, the Fixer, the Gambler, the Emperor, the
Skeptic, the Awakened and the Theorist. Each speaks once, in its own
lane, under THE COUNCIL'S LAW: no voice moves a limit, the Gambler and
the Emperor included, and every answer is read into claims a grader can
check — or refused, said.

Run with:  python manage.py test tests.test_council_voices
"""
import json
import re

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

CTX = {"entry": 100.0, "stop": 98.0, "target": 106.0, "side": "BUY",
       "instruments": {"EURUSD", "AAPL", "BTCUSD"},
       "footprint_ids": {"F1", "F2"}, "theory_ids": {7},
       "spoke": {"executioner", "champion", "opportunist", "gambler",
                 "awakened", "theorist", "skeptic", "fixer", "striker"}}


def parse(voice, answer, **over):
    from ai_agents.agents.council import parse_answer
    raw = answer if isinstance(answer, str) else json.dumps(answer)
    return parse_answer(voice, raw, dict(CTX, **over))


VALID = {
    "opportunist": {"verdict": "seize", "p_work": 0.6, "asymmetry": "a",
                    "alternative": None, "reasons": ["r"]},
    "striker": {"verdict": "take", "p_work": 0.55, "trigger": None,
                "decision": "take it", "reasons": []},
    "fixer": {"verdict": "no_fix", "p_work": 0.5, "p_work_fixed": None,
              "flaw": "", "flaw_from": "", "fix": None},
    "gambler": {"verdict": "press", "p_work": 0.7, "case": "c",
                "binding_limit": "open_risk", "elite_worthy": False},
    "skeptic": {"verdict": "sound", "conviction": 0.3, "target": "",
                "claim": "", "flaw": "none", "falsifier": ""},
    "awakened": {"verdict": "clean", "p_work": 0.6, "hunter": "h",
                 "prey": "p", "trap": "t", "footprints": ["F1"],
                 "level": 104, "within_hours": 24},
    "theorist": {"verdict": "serves", "p_work": 0.6, "theory_id": 7,
                 "how": "h", "new_theory": None},
    "emperor": {"verdict": "fight", "p_work": 0.6, "followed": ["champion"],
                "overruled": [{"voice": "executioner", "why": "w"}],
                "battle": "b", "war_cost": "c", "plan": "p"},
}


class TheParsersTests(SimpleTestCase):

    def test_every_voice_reads_a_valid_answer(self):
        for voice, answer in VALID.items():
            with self.subTest(voice=voice):
                out = parse(voice, answer)
                self.assertEqual(out["verdict"], answer["verdict"])

    def test_an_unknown_verdict_or_no_json_raises(self):
        for voice in VALID:
            with self.subTest(voice=voice):
                with self.assertRaises(ValueError):
                    parse(voice, {"verdict": "maybe", "p_work": 0.5})
                with self.assertRaises(ValueError):
                    parse(voice, "no json here")

    def test_a_missing_or_unreadable_p_work_is_silence_and_values_clamp(self):
        self.assertIsNone(parse("gambler", {"verdict": "normal"})["p_work"])
        self.assertIsNone(parse("gambler", '{"verdict": "normal", '
                                           '"p_work": NaN}')["p_work"])
        self.assertIsNone(parse("gambler", {"verdict": "normal",
                                            "p_work": "x"})["p_work"])
        self.assertIsNone(parse("gambler", {"verdict": "normal",
                                            "p_work": True})["p_work"])
        self.assertEqual(parse("gambler", {"verdict": "normal",
                                           "p_work": 1.7})["p_work"], 1.0)
        self.assertEqual(parse("gambler", {"verdict": "normal",
                                           "p_work": -2})["p_work"], 0.0)

    def test_the_last_verdict_object_wins(self):
        out = parse("striker", 'draft {"verdict": "skip"} then {"verdict": '
                               '"take", "p_work": 0.6} done {x}')
        self.assertEqual(out["verdict"], "take")

    def test_an_elsewhere_needs_a_checkable_alternative(self):
        good = {"verdict": "elsewhere", "p_work": 0.4,
                "alternative": {"symbol": "eurusd", "direction": "Up",
                                "horizon_hours": 24, "confidence": 0.7,
                                "why": "w"}}
        out = parse("opportunist", good)
        self.assertEqual(out["verdict"], "elsewhere")
        self.assertEqual(out["alternative"]["symbol"], "EURUSD")
        self.assertEqual(out["alternative"]["direction"], "up")
        for bad in (None, {"symbol": "NOPE", "direction": "up",
                           "horizon_hours": 24},
                    {"symbol": "EURUSD", "direction": "sideways",
                     "horizon_hours": 24},
                    {"symbol": "EURUSD", "direction": "up", "horizon_hours": 3},
                    {"symbol": "EURUSD", "direction": "up",
                     "horizon_hours": 900}):
            with self.subTest(alt=bad):
                out = parse("opportunist", dict(good, alternative=bad))
                self.assertEqual(out["verdict"], "pass")
                self.assertIsNone(out["alternative"])
                self.assertEqual(out["note"],
                                 "elsewhere without a checkable alternative")

    def test_a_wait_without_a_valid_trigger_is_a_skip(self):
        ok = parse("striker", {"verdict": "wait", "p_work": 0.5,
                               "trigger": {"level": 103, "within_hours": 24}})
        self.assertEqual(ok["verdict"], "wait")
        self.assertEqual(ok["trigger"], {"level": 103.0, "within_hours": 24.0})
        for trig in (None, {"level": 97, "within_hours": 24},   # beyond the stop
                     {"level": 107, "within_hours": 24},        # beyond the target
                     {"level": 100.1, "within_hours": 24},      # at the entry
                     {"level": 103, "within_hours": 80},        # past 72h
                     {"level": 103, "within_hours": 0}):
            with self.subTest(trigger=trig):
                out = parse("striker", {"verdict": "wait", "p_work": 0.5,
                                        "trigger": trig})
                self.assertEqual(out["verdict"], "skip")
                self.assertEqual(out["note"], "a wait without a valid "
                                              "trigger is recorded as a skip")

    def test_a_fix_that_removes_or_misplaces_the_stop_is_refused(self):
        from ai_agents.agents.council import STOP_REFUSED
        for value in (None, 100, 101, "x"):
            with self.subTest(value=value):
                out = parse("fixer", {"verdict": "fix", "p_work": 0.4,
                                      "fix": {"kind": "stop", "value": value,
                                              "words": "w"}})
                self.assertEqual(out["verdict"], "fix", "the verdict is kept")
                self.assertEqual(out["fix_refused"], STOP_REFUSED)
        good = parse("fixer", {"verdict": "fix", "p_work": 0.4,
                               "fix": {"kind": "stop", "value": 97.5}})
        self.assertEqual(good["fix_refused"], "")
        # a SELL's stop sits above the entry
        sell = parse("fixer", {"verdict": "fix", "fix": {"kind": "stop",
                                                         "value": 97.5}},
                     side="SELL", stop=102.0, target=94.0)
        self.assertEqual(sell["fix_refused"], STOP_REFUSED)

    def test_a_size_is_never_raised_and_a_tiny_one_is_clamped(self):
        out = parse("fixer", {"verdict": "fix",
                              "fix": {"kind": "size", "value": 3.0}})
        self.assertEqual(out["fix_refused"], "a size is never raised")
        out = parse("fixer", {"verdict": "fix",
                              "fix": {"kind": "size", "value": 0.1}})
        self.assertEqual(out["fix_refused"], "")
        self.assertEqual(out["fix"]["value"], 0.25)
        out = parse("fixer", {"verdict": "fix",
                              "fix": {"kind": "target", "value": 99}})
        self.assertIn("losing side", out["fix_refused"])
        out = parse("fixer", {"verdict": "fix",
                              "fix": {"kind": "entry", "value": 99.5}})
        self.assertIn("valid number of hours", out["fix_refused"])
        out = parse("fixer", {"verdict": "fix",
                              "fix": {"kind": "timing"}})
        self.assertIn("valid number of hours", out["fix_refused"])

    def test_the_fixer_names_only_a_voice_that_spoke(self):
        out = parse("fixer", {"verdict": "no_fix", "flaw_from": "The Skeptic"})
        self.assertEqual(out["flaw_from"], "skeptic")
        out = parse("fixer", {"verdict": "no_fix", "flaw_from": "The Oracle"})
        self.assertEqual(out["flaw_from"], "")

    def test_the_gambler_holds_no_size_number(self):
        from ai_agents.agents.council import GamblerAgent
        out = parse("gambler", {"verdict": "all_in", "p_work": 0.8,
                                "size": 5, "qty": 100, "leverage": 30,
                                "binding_limit": "moon",
                                "elite_worthy": "yes"})
        self.assertNotIn("size", out)
        self.assertNotIn("qty", out)
        self.assertNotIn("leverage", out)
        self.assertEqual(out["binding_limit"], "none")
        self.assertFalse(out["elite_worthy"], "only a JSON true is worthy")
        numbers = [k for k, v in out.items()
                   if isinstance(v, (int, float)) and not isinstance(v, bool)]
        self.assertEqual(numbers, ["p_work"])
        self.assertNotIn('"size"', GamblerAgent.SCHEMA)

    def test_the_skeptic_attacks_only_a_voice_that_spoke_and_has_no_p_work(self):
        out = parse("skeptic", {"verdict": "unfounded", "conviction": 0.8,
                                "target": "The Executioner", "claim": "c",
                                "flaw": "thin_sample"})
        self.assertEqual((out["verdict"], out["target"]),
                         ("unfounded", "executioner"))
        self.assertNotIn("p_work", out)
        for target, spoke in (("The Emperor", CTX["spoke"]),
                              ("The Skeptic", CTX["spoke"] | {"skeptic"}),
                              ("nobody", CTX["spoke"])):
            with self.subTest(target=target):
                out = parse("skeptic", {"verdict": "shaky", "target": target},
                            spoke=spoke)
                self.assertEqual(out["verdict"], "sound")
                self.assertEqual(out["note"],
                                 "an attack must name a voice that spoke")

    def test_no_trap_stands_without_a_footprint(self):
        out = parse("awakened", {"verdict": "trap", "footprints": ["F9"]})
        self.assertEqual(out["verdict"], "unread")
        self.assertEqual(out["note"], "no claim stands without a footprint")
        out = parse("awakened", {"verdict": "trap", "footprints": ["f2", "F9"]})
        self.assertEqual(out["verdict"], "trap")
        self.assertEqual(out["footprints"], ["F2"])
        near = parse("awakened", {"verdict": "unread", "level": 100.3,
                                  "within_hours": 24})
        self.assertFalse(near["touch_ok"])
        self.assertEqual(near["touch_note"], "a level at the price is no claim")
        far = parse("awakened", {"verdict": "unread", "level": 104,
                                 "within_hours": 200})
        self.assertFalse(far["touch_ok"])
        ok = parse("awakened", {"verdict": "unread", "level": 104,
                                "within_hours": 24})
        self.assertTrue(ok["touch_ok"])

    def test_a_theory_id_must_be_live(self):
        out = parse("theorist", {"verdict": "serves", "theory_id": 9})
        self.assertEqual((out["verdict"], out["theory_id"]), ("none", None))
        out = parse("theorist", {"verdict": "contradicts", "theory_id": "7"})
        self.assertEqual((out["verdict"], out["theory_id"]), ("contradicts", 7))
        out = parse("theorist", {"verdict": "none", "new_theory": {
            "claim_text": "x" * 900, "kind": "price_direction",
            "symbol": "eurusd", "direction": "UP", "horizon_hours": 48,
            "confidence": 2}})
        nt = out["new_theory"]
        self.assertEqual(len(nt["claim_text"]), 400)
        self.assertEqual((nt["symbol"], nt["direction"], nt["confidence"]),
                         ("EURUSD", "up", 1.0))

    def test_the_emperor_commits_at_most_the_proposed_size(self):
        self.assertEqual(parse("emperor", {"verdict": "fight"})["commit"], 1.0)
        self.assertEqual(parse("emperor", {"verdict": "refuse"})["commit"], 0.0)
        self.assertEqual(parse("emperor", {"verdict": "fight_smaller",
                                           "commit": 0.9})["commit"], 0.75)
        self.assertEqual(parse("emperor", {"verdict": "fight_smaller",
                                           "commit": 0.1})["commit"], 0.25)
        self.assertEqual(parse("emperor", {"verdict": "fight_smaller",
                                           "commit": 50})["commit"], 0.5)
        out = parse("emperor", {"verdict": "fight",
                                "followed": ["The Champion", "The Oracle",
                                             "emperor"],
                                "overruled": [{"voice": "nobody"},
                                              {"voice": "The Gambler",
                                               "why": "w"}]},
                    spoke={"champion", "gambler"})
        self.assertEqual(out["followed"], ["champion"])
        self.assertEqual(out["overruled"], [{"voice": "gambler", "why": "w"}])


class TheClaimsTests(SimpleTestCase):

    def _claims(self, voice, answer, **kw):
        from ai_agents.agents.council import claims_for
        return {c["kind"]: c for c in claims_for(voice, answer, **kw)}

    def test_the_debaters_claim_the_common_event(self):
        c = self._claims("executioner", {"verdict": "veto",
                                         "conviction": 0.9})
        self.assertAlmostEqual(c["work"]["p"], 0.1)
        self.assertEqual(c["stance"]["stance"], "against")
        c = self._claims("champion", {"verdict": "neutral",
                                      "conviction": 0.4})
        self.assertEqual(set(c), {"work"})

    def test_each_voice_leaves_its_specialty_claim(self):
        self.assertIn("boldness", self._claims(
            "gambler", {"verdict": "all_in", "p_work": 0.9}))
        self.assertIn("trigger", self._claims(
            "striker", {"verdict": "wait", "p_work": 0.5,
                        "trigger": {"level": 103, "within_hours": 24}}))
        c = self._claims("emperor", {"verdict": "fight_smaller",
                                     "commit": 0.5, "p_work": 0.6})
        self.assertEqual(c["battle"]["payload"]["commit"], 0.5)
        c = self._claims("skeptic", {"verdict": "shaky", "conviction": 0.7,
                                     "target": "champion"})
        self.assertEqual(set(c), {"attack"}, "the Skeptic has no p_work")
        self.assertEqual(c["attack"]["p"], 0.7)

    def test_refused_and_word_fixes_are_never_measured(self):
        c = self._claims("fixer", {"verdict": "fix", "p_work": 0.4,
                                   "fix": {"kind": "stop", "value": None},
                                   "fix_refused": "nope"})
        self.assertEqual(c["fix"]["grade"], "refused")
        c = self._claims("fixer", {"verdict": "fix", "p_work": 0.4,
                                   "fix": {"kind": "hedge", "words": "w"},
                                   "fix_refused": ""})
        self.assertEqual(c["fix"]["grade"], "ungraded")

    def test_a_late_opportunist_or_theorist_posts_nothing(self):
        alt = {"symbol": "EURUSD", "direction": "up", "horizon_hours": 24,
               "confidence": 0.6}
        c = self._claims("opportunist", {"verdict": "elsewhere",
                                         "alternative": alt}, late=True)
        self.assertEqual(c["direction"]["grade"], "ungraded")
        self.assertEqual(c["direction"]["grade_notes"], "late: not posted")
        c = self._claims("theorist", {"verdict": "none", "new_theory": {
            "kind": "regime_holds", "regime": "trending"}}, late=True)
        self.assertEqual(c["theory"]["grade"], "ungraded")


class TheLawTests(SimpleTestCase):

    def _prompts(self):
        from ai_agents.agents import council as C
        return {v: cls.__new__(cls).get_system_prompt()
                for v, cls in C.AGENTS.items()}

    def test_every_new_voice_carries_the_law(self):
        from ai_agents.agents import council as C
        prompts = self._prompts()
        for v in C.COUNCIL_VOICES:
            with self.subTest(voice=v):
                self.assertIn(C.COUNCIL_LAW, prompts[v])

    def test_the_gambler_and_the_emperor_argue_inside_the_limits(self):
        prompts = self._prompts()
        for v in ("gambler", "emperor"):
            with self.subTest(voice=v):
                own = prompts[v].split("THE COUNCIL'S LAW")[0]
                self.assertRegex(own, r"averag(e|ing) down a\s+loser")
                self.assertIn("stop", own)
                self.assertIn("limits", own)
                self.assertTrue("never more" in own
                                or "at most the proposed size" in own)

    def test_no_prompt_names_a_model_and_every_prompt_is_ascii_english(self):
        for v, p in self._prompts().items():
            with self.subTest(voice=v):
                self.assertNotIn("claude-", p)
                self.assertTrue(p.isascii(), v)
                for french in (" le ", " la ", " les ", " est ", " une "):
                    self.assertNotIn(french, p)

    def test_each_prompt_names_its_lane_and_its_neighbours(self):
        p = self._prompts()
        self.assertRegex(p["skeptic"], r"Your lane\s+is the evidence")
        self.assertIn("Executioner", p["skeptic"])
        self.assertIn("Opportunist", p["awakened"])
        self.assertIn("Awakened", p["opportunist"])
        self.assertIn("Emperor", p["gambler"])
        self.assertIn("Champion", p["gambler"])
        self.assertIn("Emperor", p["striker"])
        self.assertIn("Fixer", p["striker"])
        self.assertIn("Striker", p["fixer"])
        self.assertIn("Gambler", p["emperor"])
        self.assertIn("Executioner and the Champion", p["theorist"])
        # main has the Big Money board: one footprint source,
        # never "not built yet"
        self.assertRegex(p["awakened"], r"The Big Money board, where the "
                                        r"large players must move, is one\s+"
                                        r"footprint source")
        self.assertNotIn("not built yet", p["awakened"])
        self.assertRegex(p["emperor"], r"no season\s+objective")
        # THE WAR says where the book stands in each limit IT CAN READ: the
        # account's current pledge is not read there, and he is told so
        self.assertRegex(p["emperor"], r"each limit it can read, and says "
                                       r"so\s+when it cannot \(the "
                                       r"account's current pledge is not "
                                       r"read there\)")

    def test_the_council_run_debaters_keep_the_debates_prompts(self):
        from ai_agents.agents.council import CouncilChampion, CouncilExecutioner
        from ai_agents.agents.trade_debate import ChampionAgent, ExecutionerAgent
        for council_cls, debate_cls in ((CouncilExecutioner, ExecutionerAgent),
                                        (CouncilChampion, ChampionAgent)):
            self.assertEqual(
                council_cls.__new__(council_cls).get_system_prompt(),
                debate_cls.__new__(debate_cls).get_system_prompt())


class TheModelTests(TestCase):

    def test_names_fit_the_ledger_and_the_eight_are_pickable(self):
        from ai_agents.agents import council as C
        from dashboard.views_ai_models import AGENT_GROUPS
        rows = {name: tier for _, rs in AGENT_GROUPS for name, _, tier in rs}
        for cls in C.AGENTS.values():
            self.assertLessEqual(len(cls.agent_name), 30, cls.agent_name)
        self.assertEqual(len(C.COUNCIL_AGENT_NAMES), 8)
        for name in C.COUNCIL_AGENT_NAMES:
            self.assertEqual(rows.get(name), "fast", name)
            self.assertIn(name, {c.agent_name for c in C.AGENTS.values()})
        for name in C.COUNCIL_DEBATER_NAMES:
            self.assertNotIn(name, rows, "they read the debate rows")

    def test_every_voice_answers_on_the_debate_model_unless_a_row_says(self):
        from ai_agents.agents.council import (CouncilExecutioner,
                                              GamblerAgent)
        from ai_agents.agents.trade_debate import DEBATE_MODEL
        from ai_agents.models import AIModelSetting
        g = GamblerAgent()
        self.assertEqual(g.model, DEBATE_MODEL)
        self.assertEqual(g.effort, "low")
        AIModelSetting.objects.create(scope="agent", key="council_gambler",
                                      model_id="claude-sonnet-5")
        self.assertEqual(GamblerAgent().model, "claude-sonnet-5")
        # one Executioner, one setting: the council's reads the debate's row
        AIModelSetting.objects.create(scope="agent", key="debate_executioner",
                                      model_id="claude-opus-5",
                                      effort="high")
        ex = CouncilExecutioner()
        self.assertEqual((ex.model, ex.effort), ("claude-opus-5", "high"))
        self.assertEqual(ex.agent_name, "council_executioner")

    def test_the_models_page_shows_what_the_ten_run_on(self):
        from ai_agents.agents.council import COUNCIL_AGENT_NAMES
        from ai_agents.agents.trade_debate import DEBATE_MODEL
        staff = get_user_model().objects.create_user(
            "cv_staff", password="x", is_staff=True, is_superuser=True)
        self.client.force_login(staff)
        resp = self.client.get("/ai-models/")
        self.assertEqual(resp.status_code, 200)
        rows = {r["name"]: r for g in resp.context["agent_groups"]
                for r in g["rows"]}
        for name in ("debate_executioner", "debate_champion") \
                + COUNCIL_AGENT_NAMES:
            with self.subTest(agent=name):
                self.assertEqual(rows[name]["resolved"], DEBATE_MODEL)
                self.assertEqual(rows[name]["effort"], "low")
        self.assertContains(resp, "The council (shadow)")
        self.assertContains(resp, "The Emperor (chair)")
        # an agent outside the debate and the council still shows its tier
        self.assertEqual(rows["close_advisor"]["resolved"],
                         __import__("ai_agents.catalog", fromlist=["x"])
                         .resolve_agent("close_advisor", "balanced"))
        self.assertTrue(re.search("Model Selection|model", resp.content.decode()))
