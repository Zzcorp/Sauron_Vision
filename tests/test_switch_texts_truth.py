"""THE /ops/ TEXTS SAY WHAT THE SWITCHES DO (2026-10-24).

  * proving_ground said "Verdicts only; nothing trades." Since size by
    proof (backtester/proving/proof.py, GATE on outside the test suite),
    its saved verdicts size every live bot entry: FAILED is refused on
    that class and side, PROVEN keeps full size, any other trades at a
    quarter unless the rule's own graded record proves it.
  * newsletter_send said "to the users who opted in", but the weekly
    newsletter preference is ON by default: it is opt-out.
  * `backfill_bars --proving` closed with "Nothing trades." while the next
    step it names, `prove rules --save`, binds real money.

seed_components rewrites each row's name and description on deploy
(core/platform_control.py), so the server reads the new text with no
migration; the description column is 300 characters on Postgres.

Run with:  python manage.py test tests.test_switch_texts_truth
"""
import inspect

from django.test import SimpleTestCase


def _description(key):
    from core.platform_control import DEFAULT_COMPONENTS
    return next(c for c in DEFAULT_COMPONENTS if c["key"] == key)["description"]


class TheSwitchTextsTests(SimpleTestCase):

    def test_the_proving_ground_says_its_verdicts_size_real_money(self):
        text = _description("proving_ground")
        self.assertLess(len(text), 300)
        self.assertNotIn("nothing trades", text.lower())
        self.assertNotIn("verdicts only", text.lower())
        # The verdicts bind whatever the switch says: the gate reads
        # proof.GATE, and the switch only runs the nightly judge.
        self.assertIn("On or off, saved verdicts size live bot entries",
                      text)
        for words in ("FAILED refuses the rule on that class and side",
                      "PROVEN allows full size", "a quarter"):
            self.assertIn(words, text)

    def test_the_gate_it_describes_is_on_in_the_code(self):
        from backtester.proving import proof
        src = inspect.getsource(proof)
        self.assertIn("\nGATE = True\n", src)
        # "On or off": the gate never reads the component.
        self.assertNotIn("proving_ground", src)
        self.assertEqual(proof.MULTIPLIER[proof.FAILED], 0.0)
        self.assertEqual(proof.MULTIPLIER[proof.PROVEN], 1.0)
        self.assertEqual(proof.MULTIPLIER[proof.UNPROVEN], 0.25)

    def test_the_newsletter_says_it_is_opt_out(self):
        from alerts.models import UserNotificationPrefs
        text = _description("newsletter_send")
        self.assertLess(len(text), 300)
        self.assertNotIn("opted in", text)
        self.assertIn("on by default: opt-out", text)
        self.assertIn("non-investor", text)
        self.assertIs(UserNotificationPrefs._meta.get_field(
            "receive_weekly_newsletter").default, True)

    def test_the_proving_run_does_not_say_nothing_trades(self):
        from market_data.management.commands import backfill_bars
        src = inspect.getsource(backfill_bars)
        self.assertNotIn("Nothing trades", src)
        self.assertIn("A saved verdict binds", src)
        # The beat entry's comment said "verdicts only" too.
        from pathlib import Path

        from django.conf import settings
        beat = (Path(settings.BASE_DIR) / "config" / "celery.py").read_text(
            encoding="utf-8")
        self.assertNotIn("proving_ground; verdicts only", beat)
