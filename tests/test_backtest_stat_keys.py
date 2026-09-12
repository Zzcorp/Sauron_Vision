"""The page and the engine must agree on the name of a number (2026-09-13).

`/bot-backtest/` averaged the trade count with `stats.get("n_trades", 0)`.
`bot_program/backtest_asset.py` writes that count under `"n"` — both in
`compute_stats` and in `_empty_stats` — and nothing anywhere has ever
written `"n_trades"`. So `.get`'s default did its job perfectly and the
page showed a hard `0.0` on every run it had ever displayed.

That is the worst shape a wrong number can take on this platform. It did
not raise, it did not look empty, and it did not look broken: it looked
like a measured average of zero trades per run, which is a claim, and a
false one. It is the same failure class as the retired "667 tests green"
that `core/wall_facts.py` exists to prevent, and the same one the Oculus
answers with an em-dash — except here there was not even a dash to see.

A test that only pinned the one key would be worth little; the bug is not
`n_trades`, it is that a view can read any key it likes from a JSONField
and be quietly wrong forever. So this reads the keys the VIEW asks for
out of the view's own source and checks each one against the keys the
ENGINE actually writes.
"""
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

VIEW = Path(settings.BASE_DIR) / "dashboard" / "views_bot_backtest.py"
ENGINE = Path(settings.BASE_DIR) / "bot_program" / "backtest_asset.py"

#: Keys the view may read that the engine does not write, with the reason.
#: Empty on purpose — an entry here is a claim that a missing key is fine,
#: and that claim should have to be written down.
ALLOWED_ABSENT: dict = {}


def _keys_the_view_reads() -> set:
    src = VIEW.read_text(encoding="utf-8")
    return set(re.findall(r'\.stats\.get\(\s*["\']([a-z_]+)["\']', src))


def _keys_the_engine_writes() -> set:
    """Every literal key in the two dicts compute_stats/_empty_stats return.

    Read out of the source rather than by calling them, so the test needs
    no bars, no instruments and no database.
    """
    src = ENGINE.read_text(encoding="utf-8")
    keys = set()
    for marker in ("def compute_stats", "def _empty_stats"):
        start = src.index(marker)
        body = src[start:src.index("\ndef ", start + 1)
                   if "\ndef " in src[start + 1:] else len(src)]
        # the returned dict literals
        for block in re.findall(r"return \{(.*?)\n    \}", body, re.S):
            keys.update(re.findall(r'"([a-z_]+)":', block))
    return keys


class TheViewAndTheEngineAgreeOnKeyNamesTests(SimpleTestCase):

    def test_the_engine_writes_the_trade_count_as_n(self):
        written = _keys_the_engine_writes()
        self.assertIn("n", written)
        self.assertNotIn(
            "n_trades", written,
            "the engine grew an n_trades key — if that is deliberate, the "
            "view and this test should move to it together, not drift apart "
            "again")

    def test_every_key_the_page_reads_is_a_key_the_engine_writes(self):
        reads = _keys_the_view_reads()
        writes = _keys_the_engine_writes()
        self.assertTrue(reads, "no .stats.get(...) calls found — the view was "
                               "restructured and this guard is now blind")
        missing = {k for k in reads if k not in writes} - set(ALLOWED_ABSENT)
        self.assertEqual(
            missing, set(),
            f"the page reads {sorted(missing)} from stats and nothing writes "
            f"it. .get's default will render a plausible number that was "
            f"never measured — add the key to the engine, fix the spelling, "
            f"or justify it in ALLOWED_ABSENT.")

    def test_the_trade_average_reads_the_key_that_exists(self):
        """The specific regression, pinned by name."""
        src = VIEW.read_text(encoding="utf-8")
        self.assertIn('avg_trades', src)
        avg = src[src.index("avg_trades"):]
        avg = avg[:avg.index("\n\n")] if "\n\n" in avg else avg
        self.assertIn('.stats.get("n", 0)', avg)
        self.assertNotIn("n_trades", avg)
