"""THE MARK SANITY: the engine never decides on a dead or aberrant mark
(2026-10-05, the operator asked for more resilience on open positions).

One print far from the last accepted mark — past the class's bar — is
suspect until a second print confirms it or the platform's own quote agrees
with it; a REAL row's mark far from the platform's fresh quote is suspect
on its own; the same print for FROZEN_MINUTES in an open market is a dead
feed, told once. A suspect or frozen tick manages nothing on the row: no
soft stop, no mirror, no scale-out, no SL/TP, no trailing move — and the
skip says why. Options are never judged.

Run with:  python manage.py test tests.test_mark_sanity
"""
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from tests.test_aragorn import _switch
from tests.test_risk_limits_bind import _config, _quote
from tests.test_scale_out import _trade


def _row(cls="crypto", care=None, paper=False):
    return SimpleNamespace(asset_class=cls, paper=paper, symbol="BTCUSD", id=1,
                           metadata={"care": dict(care or {})})


class TheJudgeTests(SimpleTestCase):
    """Pure reads: entry 100, the crypto bar 3%."""

    def setUp(self):
        self.now = timezone.now()

    def _accepted(self, price, at=None):
        return {"last_mark": price, "last_mark_at": (at or self.now).isoformat(),
                "mark_same_since": (at or self.now).isoformat()}

    def test_the_bars_and_the_constants(self):
        from bot_program import mark_sanity as ms
        self.assertEqual(ms.JUMP_PCT["forex"], 0.005)
        self.assertEqual(ms.JUMP_PCT["crypto"], 0.03)
        self.assertEqual((ms.JUMP_WINDOW_MINUTES, ms.CONFIRMING_TICKS,
                          ms.FROZEN_MINUTES, ms.SECOND_OPINION_MAX_AGE_S),
                         (15, 2, 45, 900))
        self.assertEqual(ms.bar_for("options"), 0.0)
        self.assertEqual(ms.bar_for("unknown"), 0.0)
        self.assertIn("options", ms.NEVER_JUDGED)

    def test_an_ordinary_print_is_accepted_and_remembered(self):
        from bot_program.mark_sanity import judge
        v = judge(_row(), 101.0, now=self.now)
        self.assertTrue(v["ok"])
        self.assertTrue(v["changed"])
        self.assertEqual(v["care"]["last_mark"], 101.0)
        self.assertEqual(v["care"]["last_mark_at"], self.now.isoformat())
        later = self.now + timedelta(minutes=2)
        v2 = judge(_row(care=v["care"]), 101.5, now=later)
        self.assertTrue(v2["ok"])
        self.assertEqual(v2["care"]["last_mark"], 101.5)
        self.assertEqual(v2["care"]["mark_same_since"], later.isoformat())

    def test_a_jump_is_suspect_once_then_confirmed_by_the_next_print(self):
        from bot_program.mark_sanity import judge
        care = self._accepted(100.0)
        t1 = self.now + timedelta(minutes=1)
        v = judge(_row(care=care), 96.0, now=t1)              # -4% in a minute
        self.assertFalse(v["ok"])
        self.assertIn("suspect mark", v["why"])
        self.assertIn("print 1 of 2", v["why"])
        self.assertEqual(v["care"]["last_mark"], 100.0, "the last accepted mark "
                         "does not move on a suspect print")
        self.assertEqual(v["care"]["mark_suspect"]["ticks"], 1)
        self.assertEqual(v["care"]["mark_suspect"]["price"], 96.0)
        # the next print at about the same level: the market moved
        t2 = t1 + timedelta(minutes=1)
        v2 = judge(_row(care=v["care"]), 96.2, now=t2)
        self.assertTrue(v2["ok"])
        self.assertEqual(v2["care"]["last_mark"], 96.2)
        self.assertNotIn("mark_suspect", v2["care"])

    def test_a_glitch_clears_when_the_next_print_is_back(self):
        from bot_program.mark_sanity import judge
        care = self._accepted(100.0)
        t1 = self.now + timedelta(minutes=1)
        v = judge(_row(care=care), 96.0, now=t1)
        self.assertFalse(v["ok"])
        v2 = judge(_row(care=v["care"]), 100.1, now=t1 + timedelta(minutes=1))
        self.assertTrue(v2["ok"])
        self.assertEqual(v2["care"]["last_mark"], 100.1)
        self.assertNotIn("mark_suspect", v2["care"])
        # a second glitch at another level starts the count over
        v3 = judge(_row(care=v2["care"]), 104.0, now=t1 + timedelta(minutes=2))
        self.assertFalse(v3["ok"])
        self.assertEqual(v3["care"]["mark_suspect"]["ticks"], 1)

    def test_the_second_opinion_confirms_a_jump_at_once_or_makes_a_quiet_mark_suspect(self):
        from bot_program.mark_sanity import judge
        care = self._accepted(100.0)
        t1 = self.now + timedelta(minutes=1)
        # the platform's quote agrees with the jump: accepted at once
        v = judge(_row(care=care), 96.0, now=t1, reference=96.1)
        self.assertTrue(v["ok"])
        self.assertEqual(v["care"]["last_mark"], 96.0)
        # the platform's quote is far from a quiet mark: suspect
        v2 = judge(_row(care=care), 100.2, now=t1, reference=95.0)
        self.assertFalse(v2["ok"])
        self.assertIn("platform's quote 95", v2["why"])
        # and a disagreeing second opinion is never out-voted by repetition
        v3 = judge(_row(care=v2["care"]), 100.2, now=t1 + timedelta(minutes=1),
                   reference=95.0)
        self.assertFalse(v3["ok"])
        self.assertEqual(v3["care"]["mark_suspect"]["ticks"], 2)

    def test_an_old_last_mark_is_not_compared(self):
        from bot_program.mark_sanity import judge
        care = self._accepted(100.0, at=self.now - timedelta(minutes=40))
        v = judge(_row(care=care), 92.0, now=self.now)
        self.assertTrue(v["ok"], "hours apart, prices differ — no jump")
        self.assertEqual(v["care"]["last_mark"], 92.0)

    def test_the_bar_is_the_classs_own(self):
        from bot_program.mark_sanity import judge
        care = self._accepted(1.17)
        t1 = self.now + timedelta(minutes=1)
        self.assertFalse(judge(_row(cls="forex", care=care), 1.1765, now=t1)["ok"],
                         "+0.56% on a pair is a jump")
        self.assertTrue(judge(_row(cls="forex", care=care), 1.1745, now=t1)["ok"],
                        "+0.38% on a pair is a tick")
        care_s = self._accepted(100.0)
        self.assertTrue(judge(_row(cls="stock", care=care_s), 102.5, now=t1)["ok"])
        self.assertFalse(judge(_row(cls="index", care=care_s), 102.0, now=t1)["ok"])

    def test_options_are_never_judged(self):
        from bot_program.mark_sanity import judge
        care = self._accepted(2.0)
        v = judge(_row(cls="options", care=care), 3.5,
                  now=self.now + timedelta(minutes=1))
        self.assertTrue(v["ok"])
        self.assertFalse(v["changed"])
        self.assertEqual(v["care"], care)

    def test_a_frozen_feed_in_an_open_market_is_said_once_and_clears_on_the_first_move(self):
        from bot_program.mark_sanity import judge
        t0 = self.now
        care = self._accepted(100.0, at=t0)
        # the same print 20 minutes on: quiet, not dead
        v = judge(_row(care=care), 100.0, now=t0 + timedelta(minutes=20))
        self.assertTrue(v["ok"])
        self.assertEqual(v["care"]["mark_same_since"], t0.isoformat())
        # 46 minutes on, the market open: frozen, the alert asked once
        t1 = t0 + timedelta(minutes=46)
        v2 = judge(_row(care=v["care"]), 100.0, now=t1)
        self.assertFalse(v2["ok"])
        self.assertTrue(v2["frozen"])
        self.assertTrue(v2["alert"])
        self.assertIn("frozen mark", v2["why"])
        self.assertIn("46 minutes", v2["why"])
        self.assertEqual(v2["care"]["mark_frozen_alerted_at"], t1.isoformat())
        v3 = judge(_row(care=v2["care"]), 100.0, now=t1 + timedelta(minutes=5))
        self.assertFalse(v3["ok"])
        self.assertFalse(v3["alert"], "told once per freeze")
        # the same print in a SHUT market is the close, not a dead feed
        v4 = judge(_row(care=v["care"]), 100.0, now=t1, market_open=False)
        self.assertTrue(v4["ok"])
        # the first different print clears everything
        v5 = judge(_row(care=v3["care"]), 100.3, now=t1 + timedelta(minutes=6))
        self.assertTrue(v5["ok"])
        self.assertNotIn("mark_frozen_alerted_at", v5["care"])
        self.assertEqual(v5["care"]["mark_same_since"],
                         (t1 + timedelta(minutes=6)).isoformat())

    def test_a_bad_price_judges_nothing(self):
        from bot_program.mark_sanity import judge
        care = self._accepted(100.0)
        for bad in (None, 0, -1, "x", float("nan")):
            v = judge(_row(care=care), bad, now=self.now)
            self.assertTrue(v["ok"])
            self.assertFalse(v["changed"])


class TheSecondOpinionTests(TestCase):

    def test_a_fresh_platform_quote_counts_a_stale_or_venue_one_does_not(self):
        from market_data.models import LiveQuote
        from bot_program.mark_sanity import second_opinion
        inst = _quote("BTCUSD", "101.5")
        self.assertEqual(second_opinion("BTCUSD"), 101.5)
        self.assertIsNone(second_opinion("NOPE"))
        LiveQuote.objects.filter(instrument=inst).update(
            updated_at=timezone.now() - timedelta(seconds=1000))
        self.assertIsNone(second_opinion("BTCUSD"), "older than 900 s")
        LiveQuote.objects.filter(instrument=inst).update(
            updated_at=timezone.now(), source="etoro_rates")
        self.assertIsNone(second_opinion("BTCUSD"), "the venue's own rate is "
                          "not a second opinion")


class TheEngineTests(TestCase):
    """manage_positions on a paper crypto bot: entry 100, stop 98."""

    def setUp(self):
        self.user = get_user_model().objects.create_user("mark_u", password="x")
        self.cfg = _config(self.user, symbols=["BTCUSD"])
        _switch("aragorn")
        from bot_program.asset_engine.base import make_bot
        self.bot = make_bot(self.cfg)

    def _tick(self, price):
        _quote("BTCUSD", str(price))
        with mock.patch("bot_program.engine.paper_trader.paper_market_shut",
                        return_value=""):
            return self.bot.manage_positions()

    def test_a_suspect_print_through_the_stop_closes_nothing_until_confirmed(self):
        from bot_program.asset_engine.safety import _extras
        t = _trade(self.cfg)
        self.assertEqual(self._tick(100.5), 0)
        t.refresh_from_db()
        self.assertEqual(t.metadata["care"]["last_mark"], 100.5)
        # a -4% print through the stop, one minute later: left alone
        self.assertEqual(self._tick(96.0), 0)
        t.refresh_from_db()
        self.assertEqual(t.status, "OPEN")
        self.assertEqual(t.metadata["care"]["last_mark"], 100.5)
        self.assertEqual(t.metadata["care"]["mark_suspect"]["price"], 96.0)
        skips = _extras(self.cfg).get("skips") or {}
        self.assertEqual(skips["BTCUSD"]["code"], "suspect_mark")
        self.assertIn("print 1 of 2", skips["BTCUSD"]["detail"])
        # the next print confirms it: the stop fires
        self.assertEqual(self._tick(96.1), 1)
        t.refresh_from_db()
        self.assertEqual(t.status, "CLOSED")

    def test_an_ordinary_print_through_the_stop_closes_as_before(self):
        t = _trade(self.cfg)
        self.assertEqual(self._tick(99.0), 0)
        self.assertEqual(self._tick(97.9), 1)
        t.refresh_from_db()
        self.assertEqual(t.status, "CLOSED")

    def test_a_frozen_feed_tells_the_staff_once_and_manages_nothing(self):
        t = _trade(self.cfg, meta={"care": {
            "last_mark": 100.0,
            "last_mark_at": (timezone.now() - timedelta(minutes=50)).isoformat(),
            "mark_same_since": (timezone.now() - timedelta(minutes=50)).isoformat(),
            "peak": 100.0, "worst": 100.0}})
        with mock.patch("bot_program.notifications.notify_staff") as told:
            self.assertEqual(self._tick(100.0), 0)
            self.assertEqual(self._tick(100.0), 0)
        self.assertEqual(told.call_count, 1)
        self.assertIn("has not moved", told.call_args.kwargs["title"])
        t.refresh_from_db()
        self.assertEqual(t.status, "OPEN")
        self.assertIn("mark_frozen_alerted_at", t.metadata["care"])
        self.assertNotIn("soft_stop", t.metadata["care"], "the care did not run")

    def test_a_read_that_fails_lets_the_tick_run(self):
        t = _trade(self.cfg)
        with mock.patch("bot_program.mark_sanity.judge",
                        side_effect=RuntimeError("boom")):
            self.assertEqual(self._tick(97.9), 1)
        t.refresh_from_db()
        self.assertEqual(t.status, "CLOSED")


class TheWiringTests(SimpleTestCase):

    def test_the_gate_sits_after_the_no_price_gate_and_before_everything_that_acts(self):
        import inspect

        from bot_program.asset_engine.base import AssetBot
        src = inspect.getsource(AssetBot.manage_positions)
        no_price = src.index("if price is None or price <= 0:")
        gate = src.index('mark_sanity.check(self, trade, price, client)["ok"]')
        vanished = src.index("self._protection_vanished(trade, client)")
        care = src.index("_care(self, trade, price, client)")
        self.assertLess(no_price, gate)
        self.assertLess(gate, vanished)
        self.assertLess(gate, care)

    def test_the_skip_code_has_its_advice(self):
        from bot_program.asset_engine import skips
        self.assertEqual(skips.SUSPECT_MARK, "suspect_mark")
        import inspect
        self.assertIn("SUSPECT_MARK:", inspect.getsource(skips))
