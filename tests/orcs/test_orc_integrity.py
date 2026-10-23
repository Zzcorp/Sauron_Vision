"""PS13, THE INTEGRITY VERDICT (bot_program/orcs/integrity.py, spec §5.2a
"What PS13 does", §7.5.2 F5, code of honor article VI): three critical
items only (the venue mark, the decision frame's bars, the row's own
state); under one of them the menu holds no discretionary R3-R6 kind and a
tighten only while the mark is fresh. A stale posture, a blind analyst, an
unread calendar or an unmeasured correlation never abstain.

Run with:  python manage.py test tests.orcs.test_orc_integrity
"""
from datetime import datetime, timedelta
from datetime import timezone as dt_tz

from django.test import SimpleTestCase

NOW = datetime(2026, 10, 21, 15, 0, tzinfo=dt_tz.utc)
FRESH = dict(mark_source="venue", mark_age_s=30, real=True,
             decision_tf="4h", frame_fresh=True,
             frame_end=NOW - timedelta(hours=1), row_ok=True)


class TheVerdictTests(SimpleTestCase):

    def test_the_three_critical_items_and_their_words(self):
        from bot_program.orcs.integrity import verdict
        v = verdict(**{**FRESH, "mark_age_s": 300})
        self.assertEqual(v["critical"],
                         ["the venue mark is 300 s old (over 120 s)"])
        v = verdict(**{**FRESH, "mark_source": "quote"})
        self.assertEqual(v["critical"],
                         ["the mark is not the venue's (quote)"])
        v = verdict(**{**FRESH, "frame_fresh": False,
                       "frame_end": datetime(2026, 10, 20, 8, 0,
                                             tzinfo=dt_tz.utc)})
        self.assertEqual(v["critical"],
                         ["the 4h venue bars are older than two bar lengths "
                          "(last 2026-10-20 08:00 UTC)"])
        v = verdict(**{**FRESH, "row_ok": False})
        self.assertEqual(v["critical"], ["the row's state is unreadable"])
        for v in (verdict(**{**FRESH, "row_ok": False}),):
            self.assertEqual(v["flag"], "critical")

    def test_a_paper_row_reads_its_own_venue_the_quote(self):
        from bot_program.orcs.integrity import verdict
        v = verdict(**{**FRESH, "real": False, "mark_source": "quote"})
        self.assertEqual(v["critical"], [])
        v = verdict(**{**FRESH, "real": False, "mark_source": "quote",
                       "mark_age_s": 600})
        self.assertEqual(len(v["critical"]), 1)

    def test_non_critical_items_never_abstain(self):
        from bot_program.orcs.integrity import verdict
        v = verdict(**FRESH,
                    stale=["— (not measured: crisis_mode off)",
                           "— (tags blind since 2026-10-21 09:00 UTC)",
                           "— (calendar unread)"],
                    missing=["— (ρ unmeasured: EURUSD/GBPUSD)"],
                    contradictions=["the Mind reads risk_on during a crisis "
                                    "posture"])
        self.assertEqual(v["critical"], [])
        self.assertEqual(v["flag"], "contradiction")
        self.assertEqual(verdict(**FRESH, stale=["x"])["flag"], "stale")
        self.assertEqual(verdict(**FRESH)["flag"], "ok")


class TheMenuShrinkTests(SimpleTestCase):

    def _cands(self):
        from bot_program.orcs.playbook import Candidate
        return [Candidate(i, a) for i, a in (
            ("H-HOLD", "hold"), ("K-DRAW", "trim"), ("P-HOLD", "hold"),
            ("P-LOCK", "tighten"), ("P-TRIM", "trim"), ("T-CARE", "tighten"),
            ("T-STRUCT", "tighten"), ("X-THESIS", "exit"))]

    def test_whole_without_f5(self):
        from bot_program.orcs.integrity import shrink
        self.assertEqual(shrink(self._cands(), False), self._cands())

    def test_under_f5_no_discretionary_kind(self):
        from bot_program.orcs.integrity import shrink
        kept = [c.id for c in shrink(self._cands(), True, mark_fresh=True)]
        self.assertEqual(kept, ["H-HOLD", "P-LOCK", "T-CARE", "T-STRUCT"])
        self.assertNotIn("P-HOLD", kept, "a lock waiver is R3")
        self.assertNotIn("X-THESIS", kept)

    def test_tighten_only_on_a_fresh_mark(self):
        from bot_program.orcs.integrity import shrink
        kept = [c.id for c in shrink(self._cands(), True, mark_fresh=False)]
        self.assertEqual(kept, ["H-HOLD"])

    def test_allowed_actions_at_l0(self):
        from bot_program.orcs.integrity import R3_R6, allowed_actions_l0
        allowed, why_not = allowed_actions_l0(f5=False, mark_fresh=True)
        self.assertIn("hold", allowed)
        self.assertIn("tighten", allowed)
        self.assertTrue(any("L0" in w for w in why_not))
        allowed, why_not = allowed_actions_l0(f5=["the row's state is "
                                                  "unreadable"],
                                              mark_fresh=True)
        self.assertFalse(set(allowed) & set(R3_R6))
        self.assertEqual(allowed, ["hold", "revise_plan", "tighten"])
        self.assertIn("F5: the row's state is unreadable: no discretionary "
                      "exit, trim, waiver or add is on the menu", why_not)
        allowed, _ = allowed_actions_l0(f5=["x"], mark_fresh=False)
        self.assertEqual(allowed, ["hold", "revise_plan"])
        self.assertEqual(R3_R6, ("exit", "trim", "lock_waive", "add",
                                 "reenter", "be_swap", "widen_with_cut",
                                 "reverse"))
