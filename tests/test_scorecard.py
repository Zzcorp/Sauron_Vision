"""The scorecard: which of win rate, average win and average loss is losing
the money (bot_program/scorecard.py, `manage.py scorecard`).

The week of 2026-10-02, as the operator's own open_trades printed it: 15 of
24 closed trades won (62%), the winners averaged +0.42R, 12 of them were
closed by hand at +0.28R, and two paper stops did not hold (-8.12R and
-1.84R). With those two the book needed winners of +1.09R; without them
it was level (+0.42R against the +0.43R a 68% win rate needs). The
diagnosis this module exists for: the win rate is fine; the payoff and
the stops are not.

Run with:  python manage.py test tests.test_scorecard
"""
from datetime import timedelta
from decimal import Decimal
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from bot_program import scorecard as sc


def _row(r, *, by_hand=False, mfe=None, outcome="", lane="bots", tid=0,
         sym="EURUSD"):
    return {"id": tid, "symbol": sym, "asset_class": "forex", "rule": "x",
            "lane": lane, "venue": "paper", "r": r, "outcome": outcome,
            "by_hand": by_hand, "mfe": mfe, "closed_at": None}


# The 24 closed rows of the week (open_trades --all, 2026-10-02).
WEEK = (
    [_row(x, by_hand=True) for x in
     (.30, .19, .09, .88, .59, .30, .27, .04, .15, .51, .04, .04)]
    + [_row(1.14), _row(.61), _row(1.11, outcome="hit_target")]
    + [_row(-1.21, tid=120, sym="RIO", outcome="manual_close")]
    + [_row(x, outcome="stopped_out") for x in
       (-1.03, -.04, -1.05, -1.05, -1.06, -1.01)]
    + [_row(-8.12, tid=68, sym="GBPUSD", outcome="stopped_out"),
       _row(-1.84, tid=61, sym="AAPL", outcome="time_stop")]
)


class TheArithmeticTests(SimpleTestCase):

    def test_the_week(self):
        s = sc.summarize(WEEK)
        self.assertEqual((s["n"], s["wins"], s["losses"]), (24, 15, 9))
        self.assertAlmostEqual(s["win_rate"], 0.625)
        self.assertAlmostEqual(s["avg_win"], 0.4173, places=3)
        self.assertEqual(s["by_hand_wins"], 12)
        self.assertAlmostEqual(s["by_hand_win_avg"], 0.2833, places=3)
        self.assertEqual(s["targets_hit"], 1)
        # RIO's -1.21R is a stop that slipped a fifth of 1R: flagged too.
        self.assertEqual([t[0] for t in s["overshoot"]], [120, 68, 61])
        self.assertLess(s["expectancy"], 0)
        self.assertAlmostEqual(s["needed_avg_win"], 1.094, places=2)

    def test_without_the_two_stops_that_did_not_hold(self):
        """Level, not paid: at a 68% win rate a winner must average +0.43R
        against a -0.92R loser, and they averaged +0.42R."""
        s = sc.summarize([r for r in WEEK if r["id"] not in (68, 61)])
        self.assertAlmostEqual(s["win_rate"], 15 / 22)
        self.assertAlmostEqual(s["avg_loss"], -0.9214, places=3)
        self.assertAlmostEqual(s["needed_avg_win"], 0.43, places=2)
        self.assertLess(s["avg_win"], s["needed_avg_win"])
        why = sc.diagnosis(s)
        self.assertIn("win rate is not the problem", why)
        self.assertIn("12 of 15 winners were closed by hand", why)

    def test_the_break_even_win_rate_is_one_over_one_plus_payoff(self):
        s = sc.summarize([_row(2.0), _row(-1.0), _row(-1.0)])
        self.assertAlmostEqual(s["payoff"], 2.0)
        self.assertAlmostEqual(s["breakeven_win_rate"], 1 / 3)

    def test_unmeasured_exits_are_counted_not_read_as_zero(self):
        s = sc.summarize([_row(None), _row(1.0), _row(-1.0)])
        self.assertEqual((s["n"], s["unmeasured"]), (2, 1))
        self.assertEqual(s["expectancy"], 0.0)

    def test_a_loser_that_had_been_one_r_gave_it_back(self):
        s = sc.summarize([_row(-1.0, mfe=1.3), _row(-1.0, mfe=0.4),
                          _row(-1.0)])
        self.assertEqual(s["gave_back"], 1)

    def test_a_paid_book_says_so(self):
        s = sc.summarize([_row(2.0), _row(-1.0)])
        self.assertTrue(sc.diagnosis(s).startswith("Paid: +0.50R"))

    def test_an_empty_window_says_so(self):
        self.assertIn("No measured", sc.diagnosis(sc.summarize([])))


class TheRowsTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        from bot_program.models import AssetBotConfig, AssetBotTrade
        user = get_user_model().objects.create_user("sc_u", password="x")
        cfg = AssetBotConfig.objects.create(
            user=user, asset_class="forex", name="manual", mode="live",
            symbols=[], capital=Decimal("1000"), enabled=True)
        now = timezone.now()

        def mk(r, reason="", paper=False, rule="manual_take", days=1,
               mfe=None):
            t = AssetBotTrade.objects.create(
                config=cfg, asset_class="forex", symbol="EURUSD", side="BUY",
                qty=Decimal("1"), entry_price=Decimal("1.1"),
                status="CLOSED", paper=paper, rule_name=rule, reason=reason,
                realized_r=r,
                metadata={"care": {"mfe_r": mfe}} if mfe is not None else {})
            AssetBotTrade.objects.filter(pk=t.pk).update(
                closed_at=now - timedelta(days=days))
        mk(0.2, reason="TAKE TRADE | closed:MANUAL", mfe=1.1)
        mk(-1.0, reason="x | closed:SL")
        mk(1.5, rule="golden_cross", paper=True)
        mk(-1.0, days=45)                        # outside 30 days
        mk(None, reason="x | closed:RECONCILE")  # unmeasured

    def test_rows_read_lane_venue_hand_and_mfe(self):
        rows = sc.rows(days=30)
        self.assertEqual(len(rows), 4)
        hand = [r for r in rows if r["by_hand"]]
        self.assertEqual(len(hand), 1)
        self.assertEqual(hand[0]["lane"], "manual")
        self.assertEqual(hand[0]["mfe"], 1.1)
        self.assertEqual({r["venue"] for r in sc.rows(days=30, venue="live")},
                         {"live"})
        self.assertEqual([r["lane"] for r in sc.rows(days=30, venue="paper")],
                         ["bots"])

    def test_the_command_prints_the_split_and_the_diagnosis(self):
        out = StringIO()
        call_command("scorecard", stdout=out)
        text = out.getvalue()
        self.assertIn("SCORECARD · last 30 days", text)
        self.assertIn("── lane manual", text)
        self.assertIn("── lane bots", text)
        self.assertIn("1 unmeasured", text)
        self.assertIn("closed by hand 1 (1 winners at +0.20R, best seen +1.10R)",
                      text)
        self.assertIn("→ ", text)

    def test_the_command_splits_by_rule(self):
        out = StringIO()
        call_command("scorecard", "--by", "rule", "--venue", "paper",
                     stdout=out)
        self.assertIn("── rule golden_cross", out.getvalue())
