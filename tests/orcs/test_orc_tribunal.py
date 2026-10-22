"""THE COUNCIL OF WAR'S CLASS (bot_program/orcs/tribunal.py, spec §6.10):
code sets the class from the graded arms; a fault only on a decision code
can prove was available and wrong; labels are never a penalty; early and
late hands judged alike by the block statistic.

Run with:  python manage.py test tests.orcs.test_orc_tribunal
"""
import ast
import inspect

from django.test import SimpleTestCase


class TheClassTests(SimpleTestCase):

    def test_won_honourable_fault(self):
        from bot_program.orcs.tribunal import IdeaFacts, classify
        self.assertEqual(classify(IdeaFacts(orc_r_gross=0.4,
                                            delta_care=0.0)).fell, "won")
        self.assertEqual(classify(IdeaFacts(orc_r_gross=0.0)).fell, "won")
        self.assertEqual(classify(IdeaFacts(orc_r_gross=-0.6,
                                            delta_care=0.0)).fell,
                         "honourable")
        fault = classify(IdeaFacts(orc_r_gross=0.9, breaches=1))
        self.assertEqual(fault.fell, "fault",
                         "a binding breach, even on a winner")
        self.assertIn("breach", fault.causes[0])
        self.assertEqual(classify(IdeaFacts(orc_r_gross=None)).fell, "")

    def test_costly_labels_not_faults(self):
        from bot_program.orcs.tribunal import IdeaFacts, classify
        late = classify(IdeaFacts(orc_r_gross=-0.9, delta_care=-0.4,
                                  first_divergence="hold"))
        self.assertEqual((late.fell, late.sub_label),
                         ("honourable", "costly_late"))
        early = classify(IdeaFacts(orc_r_gross=0.2, delta_care=-0.4,
                                   first_divergence="reduce"))
        self.assertEqual((early.fell, early.sub_label),
                         ("won", "costly_early"))
        small = classify(IdeaFacts(orc_r_gross=-0.5, delta_care=-0.04,
                                   first_divergence="hold"))
        self.assertEqual(small.sub_label, "", "inside the tolerance")

    def test_victory_in_defeat(self):
        from bot_program.orcs.tribunal import IdeaFacts, classify
        v = classify(IdeaFacts(orc_r_gross=-0.3, delta_care=0.6,
                               first_divergence="reduce"))
        self.assertEqual((v.fell, v.sub_label),
                         ("honourable", "victory_in_defeat"))

    def test_no_fault_without_exit_in_menu(self):
        from bot_program.orcs.tribunal import IdeaFacts, classify
        held = classify(IdeaFacts(orc_r_gross=-1.0, delta_care=-0.5,
                                  signpost_unacted=True,
                                  exit_available=False))
        self.assertEqual(held.fell, "honourable",
                         "at L0-L1 no exit is in the menu")
        faulted = classify(IdeaFacts(orc_r_gross=-1.0, signpost_unacted=True,
                                     exit_available=True))
        self.assertEqual(faulted.fell, "fault")

    def test_refusal_never_fault(self):
        from bot_program.orcs.tribunal import IdeaFacts, classify
        self.assertEqual(classify(IdeaFacts(orc_r_gross=-0.8,
                                            refusals=9)).fell, "honourable")


class TheBlockTests(SimpleTestCase):

    def _rows(self, deltas, divergence="", gave_back=False):
        return [{"delta_care": d, "first_divergence": divergence,
                 "gave_back": gave_back} for d in deltas]

    def test_block_faults_symmetric_ub80_min_n(self):
        from bot_program.orcs.tribunal import block_faults, block_stats
        bad = [-0.3, -0.25, -0.35, -0.2, -0.3, -0.28]
        late = block_faults(self._rows(bad, "hold"))
        early = block_faults(self._rows(bad, "reduce"))
        self.assertEqual(late[0]["kind"], "late hands")
        self.assertEqual(early[0]["kind"], "early hands")
        self.assertAlmostEqual(late[0]["ub80"], early[0]["ub80"],
                               msg="one threshold on both sides")
        self.assertEqual(block_faults(self._rows(bad[:4], "hold")), [],
                         "under the minimum n")
        noisy = [-0.3, 0.4, -0.2, 0.3, -0.1, 0.2]
        self.assertEqual(block_faults(self._rows(noisy, "hold")), [])
        both = (self._rows(bad, "hold")
                + self._rows([d * 2 for d in bad], "reduce")
                + self._rows(bad, gave_back=True))
        self.assertEqual(len(block_faults(both)), 1, "one fault a block")
        self.assertEqual(block_faults(both)[0]["kind"], "early hands")
        st = block_stats([0.1, 0.3])
        self.assertAlmostEqual(st["mean"], 0.2)
        self.assertGreater(st["ub80"], st["lb80"])

    def test_no_ai_import(self):
        from bot_program.orcs import tribunal
        tree = ast.parse(inspect.getsource(tribunal))
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                names.add(node.module or "")
        self.assertFalse([n for n in names if n.startswith("ai_agents")])
        self.assertFalse([n for n in names if "django.db" in n],
                         "pure: no database")
