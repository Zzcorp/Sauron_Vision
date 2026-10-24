"""THE PLAIN WORDS FOR A VOICE (bot_program/orcs/plain.py, PR68's rule
outside the Horde). A voice's words (the debate's two sides, the
reviewer's reasoning, the operator's own thesis) are kept as written or
withheld whole: when they name an exception, or may name an amount of
money, read against the row's own amounts by value. Never cut.

Pinned here (O1a): the Executioner's killer reason in a thesis's
provenance is kept whole past 200 characters, and withheld whole when it
echoes the brief's amount, the row's own amount said bare, or an
exception.

Run with:  python manage.py test tests.orcs.test_orc_plain
"""
from django.test import SimpleTestCase, TestCase

from tests.orcs.helpers import _config, _on, _row, _user, born


def _debate(killer):
    return {"debate": {"ran": True, "binding": False,
                       "champion_wins": False,
                       "executioner": {"verdict": "cut", "killer": killer},
                       "champion": {"verdict": "back"}}}


class TheKillerInAThesisTests(TestCase):

    def setUp(self):
        _on()
        self.user = _user("orc_plain")
        self.cfg = _config(self.user)

    def _killer(self, killer, **kw):
        row = _row(self.cfg, meta=_debate(killer), **kw)
        return born(self, row).thesis["provenance"]["debate"]["killer"]

    def test_a_long_killer_is_kept_whole(self):
        said = ("Chasing into resistance after a three-day run, with the "
                "weekly pool still untaken above and a print tomorrow "
                "morning that has moved this pair two ATRs on each of its "
                "last four releases; the edge is thin and the stop sits "
                "inside the noise.")
        self.assertGreater(len(said), 200)
        self.assertEqual(self._killer(said), said)

    def test_the_briefs_amount_is_withheld_whole(self):
        from dashboard.plain_words import WITHHELD
        got = self._killer("Chasing into resistance; a stop-out costs "
                           "1,234.56 for a thin edge")
        self.assertEqual(got, WITHHELD)

    def test_the_rows_own_amount_said_bare_is_withheld_whole(self):
        """qty 125 x |100 - 98| = 250 at the stop: no money word, no sign,
        read by value. A level and an R stay."""
        from dashboard.plain_words import WITHHELD
        self.assertEqual(self._killer("worst case 250 if the level fails",
                                      qty="125", symbol="ETHUSD"), WITHHELD)
        self.assertEqual(self._killer("fails below 98.00 for -1R",
                                      qty="125", symbol="SOLUSD"),
                         "fails below 98.00 for -1R")

    def test_an_exception_is_withheld_whole(self):
        from dashboard.plain_words import WITHHELD_ERROR
        self.assertEqual(self._killer("KeyError: 'bias' so no read"),
                         WITHHELD_ERROR)


class TheVoiceTests(SimpleTestCase):

    def test_no_row_no_mark_and_no_words_no_line(self):
        from bot_program.orcs.plain import row_marks, voice
        self.assertIsNone(row_marks(None))
        self.assertEqual(voice(""), "")
        self.assertEqual(voice(None), "")

    def test_never_cut(self):
        from bot_program.orcs.plain import voice
        said = "holds above the level " * 30
        self.assertEqual(voice(said), " ".join(said.split()))
