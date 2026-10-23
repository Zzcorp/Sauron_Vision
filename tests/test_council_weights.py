"""THE COUNCIL's weights (2026-10-08, ai_agents/council_grading.py).

"No voice is trusted by assertion": a voice weighs exactly 1.00 until
COUNCIL_MIN_N of its weight calls are graded; then its weight is the
house's Brier bands (trust_from_brier) on those calls scored against the
base rate of the rung (always saying it scores b(1 - b)), read per
(regime, class) down a four-rung ladder. A voice with no discrimination
weighs 1.00 at any base rate. Paper never counts; the bot and the hand
lanes pool; specialty hit rates are shown beside the weight, never in it;
and three benchmark rows, graded on the same sittings, measure whether
weighting helps at all.

Run with:  python manage.py test tests.test_council_weights
"""
from datetime import timedelta

from django.test import SimpleTestCase, TestCase
from django.utils import timezone


def _claims(voice, n, *, p=0.8, y=1, regime="trending", asset_class="forex",
            venue="live", origin="bot", kind="work", grade=None):
    from ai_agents.council_models import (CouncilClaim, CouncilSession,
                                          CouncilVoice)
    s = CouncilSession.objects.create(origin=origin, venue=venue,
                                      status="done", symbol="X",
                                      asset_class=asset_class, regime=regime)
    row = CouncilVoice.objects.create(session=s, voice=voice, wave=1,
                                      status="spoke")
    now = timezone.now()
    for _ in range(n):
        brier = (p - y) ** 2 if kind in ("work", "attack") else None
        CouncilClaim.objects.create(
            session=s, voice=row, voice_key=voice, regime=regime,
            asset_class=asset_class, venue=venue, origin=origin, kind=kind,
            p=p, y=y, brier=brier,
            grade=grade or ("right" if abs(p - y) < 0.5 else "wrong"),
            graded_at=now)


class TheBandsTests(SimpleTestCase):

    def test_the_house_bands_as_a_pure_function(self):
        from ai_agents.calibration import trust_from_brier
        for b, w in ((0.0, 1.30), (0.10, 1.30), (0.15, 1.15), (0.20, 1.15),
                     (0.25, 1.00), (0.30, 0.80), (0.35, 0.80), (0.5, 0.50)):
            with self.subTest(brier=b):
                self.assertEqual(trust_from_brier(b), w)

    def test_trust_adjustment_for_still_reads_the_same_bands(self):
        import inspect

        from ai_agents import calibration
        src = inspect.getsource(calibration.trust_adjustment_for)
        self.assertIn("return trust_from_brier(bs)", src)
        self.assertIn("MIN_SAMPLE_FOR_TRUST", src)


class TheLadderTests(TestCase):

    def test_under_ten_graded_calls_a_voice_is_neutral_and_says_why(self):
        from ai_agents.council_grading import voice_weight
        _claims("gambler", 3)
        w = voice_weight("gambler", regime="trending", asset_class="forex")
        self.assertEqual((w["factor"], w["lane"], w["n"]), (1.0, "neutral", 3))
        self.assertEqual(w["reason"],
                         "neutral: 3 graded calls in this cell, 10 needed")

    def test_the_ladder_names_its_rung(self):
        from ai_agents.council_grading import voice_weight
        _claims("champion", 5, p=0.8, y=1)           # Brier 0.04
        _claims("champion", 5, p=0.2, y=0)           # an even base rate
        tail = ("10 graded calls, Brier 0.04 against 0.25 for always saying "
                "the base rate")
        cases = (("trending", "forex", "regime_class",
                  f"measured in trending on forex, {tail}"),
                 ("trending", "stock", "regime",
                  f"measured in trending across classes, {tail}"),
                 ("risk_on", "forex", "class",
                  f"measured on forex across regimes, {tail}"),
                 ("risk_on", "stock", "all",
                  f"measured across regimes and classes, {tail}"))
        for regime, cls, rung, reason in cases:
            with self.subTest(regime=regime, cls=cls):
                w = voice_weight("champion", regime=regime, asset_class=cls)
                self.assertEqual((w["factor"], w["rung"], w["reason"]),
                                 (1.30, rung, reason))

    def test_an_unknown_regime_skips_the_regime_rungs(self):
        from ai_agents.council_grading import voice_weight
        _claims("striker", 5, regime="unknown", asset_class="forex", p=0.5,
                y=1)                                  # Brier 0.25
        _claims("striker", 5, regime="unknown", asset_class="forex", p=0.5,
                y=0)
        w = voice_weight("striker", regime="unknown", asset_class="forex")
        self.assertEqual((w["rung"], w["factor"]), ("class", 1.0))
        _claims("fixer", 6, regime="trending", asset_class="stock")
        w = voice_weight("fixer", regime="unknown", asset_class="stock")
        self.assertEqual(w["lane"], "neutral")
        self.assertIn("6 graded calls", w["reason"])

    def test_paper_never_counts_and_the_two_lanes_pool(self):
        from ai_agents.council_grading import voice_weight
        _claims("theorist", 12, venue="paper")
        self.assertEqual(voice_weight("theorist", regime="trending",
                                      asset_class="forex")["lane"], "neutral")
        _claims("awakened", 5, origin="bot", p=0.9, y=0)
        _claims("awakened", 5, origin="ticket", p=0.1, y=1)   # Brier 0.81
        w = voice_weight("awakened", regime="trending", asset_class="forex")
        self.assertEqual((w["lane"], w["n"], w["factor"]),
                         ("measured", 10, 0.5))

    def test_specialty_counts_are_shown_and_stay_out_of_the_factor(self):
        from ai_agents.council_grading import voice_weight, voice_weights
        _claims("gambler", 5, p=0.8, y=1)
        _claims("gambler", 5, p=0.2, y=0)
        _claims("gambler", 10, kind="boldness", p=None, y=0, grade="wrong")
        w = voice_weight("gambler", regime="trending", asset_class="forex")
        self.assertEqual(w["factor"], 1.30)
        self.assertEqual(w["specialty"], {"right": 0, "wrong": 10})
        every = voice_weights("trending", "forex")
        self.assertEqual(set(every), {"executioner", "champion",
                                      "opportunist", "striker", "fixer",
                                      "gambler", "emperor", "skeptic",
                                      "awakened", "theorist"})
        self.assertEqual(every["gambler"]["factor"], 1.30)
        self.assertEqual(every["emperor"]["lane"], "neutral")

    def test_a_voice_is_scored_against_its_base_rate(self):
        """A lopsided cell: 4 winners in 20. Always saying the base rate
        (0.2) shows no skill and weighs exactly 1.00; always saying 0.0
        (the Executioner's missing-conviction default) is worse than that
        and loses trust; on the raw bands both read as earned trust
        (Brier 0.16 and 0.20: 1.15)."""
        from ai_agents.council_grading import voice_weight
        for voice, p in (("champion", 0.2), ("executioner", 0.0),
                         ("fixer", None)):
            _claims(voice, 4, p=1.0 if p is None else p, y=1)
            _claims(voice, 16, p=0.0 if p is None else p, y=0)
        rate = voice_weight("champion", regime="trending",
                            asset_class="forex")
        self.assertEqual(rate["factor"], 1.00)
        self.assertEqual((rate["brier"], rate["base_rate"],
                          rate["reference"]), (0.16, 0.2, 0.16))
        self.assertTrue(rate["reason"].endswith(
            "20 graded calls, Brier 0.16 against 0.16 for always saying the "
            "base rate"), rate["reason"])
        never = voice_weight("executioner", regime="trending",
                             asset_class="forex")
        self.assertEqual((never["brier"], never["factor"]), (0.2, 0.80))
        perfect = voice_weight("fixer", regime="trending",
                               asset_class="forex")
        self.assertEqual((perfect["brier"], perfect["factor"]), (0.0, 1.30))

    def test_the_mirror_cell_and_a_cell_with_one_outcome(self):
        from ai_agents.council_grading import voice_weight
        # 16 winners in 20: "back, 0.9" every time is no skill, not trust
        _claims("champion", 16, p=0.9, y=1)
        _claims("champion", 4, p=0.9, y=0)
        w = voice_weight("champion", regime="trending", asset_class="forex")
        self.assertEqual(w["factor"], 0.80)    # 0.17 against 0.16: worse
        # every graded call the same outcome: nothing can show skill
        _claims("striker", 10, p=0.8, y=1)
        w = voice_weight("striker", regime="trending", asset_class="forex")
        self.assertEqual((w["lane"], w["factor"]), ("measured", 1.0))
        self.assertIn("every outcome alike (base rate 100%), so no skill "
                      "can show", w["reason"])

    def test_the_skeptic_is_scored_against_how_often_his_targets_were_wrong(self):
        from ai_agents.council_grading import voice_weight
        # targets wrong 3 times in 10; attacking every time at 1.0 is
        # worse than the base rate, not "measured" trust
        _claims("skeptic", 3, kind="attack", p=1.0, y=1)
        _claims("skeptic", 7, kind="attack", p=1.0, y=0)
        w = voice_weight("skeptic", regime="trending", asset_class="forex")
        self.assertEqual(w["base_rate"], 0.3)
        self.assertEqual(w["factor"], 0.50)

    def test_the_regime_matrix_is_scored_against_the_base_rate_too(self):
        from ai_agents.council_grading import record_matrix
        _claims("champion", 4, p=0.2, y=1)
        _claims("champion", 16, p=0.2, y=0)
        rows = {r["voice"]: r for r in record_matrix()["matrix"]}
        cell = next(c for c in rows["champion"]["cells"]
                    if c["regime"] == "trending")
        self.assertEqual((cell["lane"], cell["n"], cell["factor"]),
                         ("measured", 20, 1.0))

    def test_the_chair_reads_the_base_rate_beside_the_specialty(self):
        from ai_agents.agents.council import record_text
        from ai_agents.council_models import CouncilSession, CouncilVoice
        s = CouncilSession.objects.create(origin="bot", status="sitting",
                                          symbol="X")
        for v in ("executioner", "skeptic", "gambler"):
            CouncilVoice.objects.create(session=s, voice=v, wave=1,
                                        status="spoke")
        weights = {
            "executioner": {"factor": 0.8, "lane": "measured",
                            "reason": "measured", "base_rate": 0.2,
                            "specialty": {"right": 9, "wrong": 4}},
            "skeptic": {"factor": 1.0, "lane": "measured",
                        "reason": "measured", "base_rate": 0.3,
                        "specialty": {}},
            "gambler": {"factor": 1.0, "lane": "neutral",
                        "reason": "neutral: 3 graded calls in this cell, "
                                  "10 needed", "base_rate": 0.5,
                        "specialty": {}}}
        text = record_text(s, weights)
        self.assertIn("The Executioner: weight 0.80, measured; specialty 9 "
                      "of 13 right; base rate: the trades it judged here "
                      "won 20%", text)
        self.assertIn("The Skeptic: weight 1.00, measured; base rate: its "
                      "targets were wrong 30% of the time", text)
        self.assertIn("The Gambler: weight 1.00, neutral: 3 graded calls in "
                      "this cell, 10 needed\n", text + "\n")

    def test_the_weights_read_in_one_aggregate_query(self):
        from ai_agents.council_grading import voice_weights
        _claims("gambler", 10)
        with self.assertNumQueries(2):     # the weight cells, the specialty
            voice_weights("trending", "forex")


class TheBenchmarkTests(TestCase):

    def test_the_chair_the_weighted_and_the_plain_council_are_graded(self):
        from ai_agents.council_grading import record_matrix
        from ai_agents.council_models import CouncilSession
        now = timezone.now()
        for p_chair, p_w, p_m, y in ((0.9, 0.8, 0.6, 1), (0.2, 0.3, 0.5, 0)):
            CouncilSession.objects.create(
                origin="bot", status="done", symbol="X", p_chair=p_chair,
                p_weighted=p_w, p_mean=p_m, y=y, graded_at=now)
        CouncilSession.objects.create(origin="bot", status="done",
                                      symbol="X", p_chair=0.9, y=None,
                                      graded_at=now)
        rec = record_matrix()
        rows = {b["name"]: b for b in rec["benchmarks"]}
        self.assertEqual(rec["benchmarks_unpaired"], 0)
        self.assertAlmostEqual(rows["The Emperor"]["brier"],
                               (0.01 + 0.04) / 2)
        self.assertAlmostEqual(
            rows["The council, weighted by record"]["brier"],
            (0.04 + 0.09) / 2)
        self.assertAlmostEqual(rows["The council, plain average"]["brier"],
                               (0.16 + 0.25) / 2)
        self.assertEqual({b["n"] for b in rows.values()}, {2})

    def test_the_three_rows_are_graded_on_the_same_sittings(self):
        """A sitting the chair never judged (wave 2 refused by the budget)
        counts against none of the three: the chair cannot beat the
        arithmetic on a sitting he never saw."""
        from ai_agents.council_grading import record_matrix
        from ai_agents.council_models import CouncilSession
        now = timezone.now()
        CouncilSession.objects.create(origin="bot", status="done",
                                      symbol="X", p_chair=0.9, p_mean=0.9,
                                      p_weighted=0.9, y=1, graded_at=now)
        CouncilSession.objects.create(origin="bot", status="partial",
                                      symbol="X", p_chair=None, p_mean=0.9,
                                      p_weighted=None, y=0, graded_at=now)
        rec = record_matrix()
        for b in rec["benchmarks"]:
            with self.subTest(row=b["name"]):
                self.assertEqual(b["n"], 1)
                self.assertAlmostEqual(b["brier"], 0.01)
        self.assertEqual(rec["benchmarks_unpaired"], 1)

    def test_the_gambler_split_the_executioners_saving_and_the_replay(self):
        """The page's own measures of whether boldness, vetoes and the
        replay pay."""
        from ai_agents.council_grading import record_matrix
        from ai_agents.council_models import (CouncilClaim, CouncilSession,
                                              CouncilVoice)
        now = timezone.now()
        for verdict, r in (("all_in", 2.0), ("press", -1.0)):
            s = CouncilSession.objects.create(
                origin="bot", status="done", symbol="X", truth="realized",
                truth_r=r, replay_r=r, graded_at=now)
            CouncilVoice.objects.create(session=s, voice="gambler", wave=1,
                                        status="spoke", verdict=verdict)
        # a third realized sitting whose replay disagrees in sign
        CouncilSession.objects.create(origin="bot", status="done",
                                      symbol="X", truth="realized",
                                      truth_r=1.0, replay_r=-0.5,
                                      graded_at=now)
        s = CouncilSession.objects.create(origin="bot", status="done",
                                          symbol="X")
        row = CouncilVoice.objects.create(session=s, voice="executioner",
                                          wave=0, status="copied")
        for value, grade in ((1.0, "right"), (-0.5, "unresolvable"),
                             (None, "pending")):
            CouncilClaim.objects.create(
                session=s, voice=row, voice_key="executioner",
                kind="stance", stance="against", grade=grade,
                value_r=value, graded_at=None if grade == "pending" else now)
        rec = record_matrix()
        lines = {v["voice"]: v["specialty"] for v in rec["voices"]}
        self.assertEqual(lines["gambler"],
                         "all in: +2.00R average (n 1) against the rest "
                         "-1.00R (n 1)")
        self.assertEqual(lines["executioner"],
                         "his vetoes and cuts would have saved +0.50R")
        self.assertEqual(rec["replay"], {"n": 3, "agree": 2})

    def test_the_record_matrix_shows_each_voices_specialty_line(self):
        from ai_agents.council_grading import record_matrix
        rec = record_matrix()
        lines = {v["voice"]: v["specialty"] for v in rec["voices"]}
        self.assertEqual(lines["executioner"],
                         "his vetoes and cuts: none graded yet")
        self.assertTrue(lines["striker"].startswith("waits:"))
        self.assertTrue(lines["fixer"].startswith("measured fixes:"))
        self.assertTrue(lines["theorist"].endswith("not yet measured"))
        self.assertIn("of the voices he overruled", lines["emperor"])
        self.assertEqual(rec["schema_version"], 1)
        self.assertFalse(rec["graded_any"])
