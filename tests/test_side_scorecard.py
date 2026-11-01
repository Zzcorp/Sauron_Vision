"""THE SCORECARD BY SIDE (2026-10-31, bot_program/evidence.side_rows):
long against short per rule and class. Display only.

What the file pins:
  * graded signals split by side (bullish long, bearish short; neutral is
    no side) and by the instrument's class;
  * closed fills split by side and by world (paper, live), an option's
    side read from the decision it bought premium on (a put bought on a
    SELL is a short, though its row says BUY);
  * one proving-ground verdict read per side, or why there is none;
  * a born name with no row reads "born at research";
  * the gap shows only once each side has 20 graded signals;
  * the crowded long's two gates are two rules, each its own row: the COT
    gate reads its verdict, the crowd gate why it has none;
  * /evidence/ shows the table, and an unreadable scorecard hides nothing
    else; manage.py side_scorecard prints it.

Run with:  python manage.py test tests.test_side_scorecard
"""
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import Client, TestCase

from tests.test_evidence_honesty import _cfg, _instrument


def _graded(inst, rule, direction, r, n=1):
    from signals.models import Signal
    for _ in range(n):
        Signal.objects.create(
            instrument=inst, signal_type="technical", direction=direction,
            urgency="medium", title="t", description="d", rule_name=rule,
            score=0.7, sub_scores={},
            price_at_signal=Decimal("100"), is_active=False,
            outcome="hit_target" if r > 0 else "hit_stop", realized_r=r)


def _fill(cfg, rule, side, r, *, paper=True, asset_class=None, meta=None):
    from bot_program.models import AssetBotTrade
    return AssetBotTrade.objects.create(
        config=cfg, asset_class=asset_class or cfg.asset_class,
        symbol="SIDEX", side=side, qty=Decimal("1"),
        entry_price=Decimal("100"), status="CLOSED", rule_name=rule,
        paper=paper, realized_r=r, metadata=meta or {})


def _row(rows, rule, cls):
    return next(r for r in rows if r["rule"] == rule and r["asset_class"] == cls)


class TheSideRowsTests(TestCase):

    def setUp(self):
        self.stock = _instrument("SIDEX", asset_class="stock")
        self.fx = _instrument("SIDEFX", asset_class="forex")
        self.user = User.objects.create_user("side_u", password="x")

    def test_graded_signals_split_by_side_and_class(self):
        from bot_program.evidence import side_rows
        _graded(self.stock, "bollinger_squeeze_breakout", "bullish", 2.0)
        _graded(self.stock, "bollinger_squeeze_breakout", "bearish", -1.0, n=2)
        _graded(self.stock, "bollinger_squeeze_breakout", "neutral", 5.0)
        _graded(self.fx, "bollinger_squeeze_breakout", "bearish", 2.0)
        rows = side_rows()
        stock = _row(rows, "bollinger_squeeze_breakout", "stock")
        self.assertEqual((stock["long"]["sig_n"], stock["long"]["sig_avg"]),
                         (1, 2.0))
        self.assertEqual((stock["short"]["sig_n"], stock["short"]["sig_avg"],
                          stock["short"]["sig_hit"]), (2, -1.0, 0.0))
        fx = _row(rows, "bollinger_squeeze_breakout", "forex")
        self.assertEqual((fx["long"]["sig_n"], fx["short"]["sig_n"]), (0, 1))
        self.assertEqual(stock["stage"], "no row (paper)")

    def test_fills_split_by_side_and_world_and_an_option_by_its_decision(self):
        from bot_program.evidence import side_rows, trade_side
        cfg = _cfg(self.user, asset_class="stock", name="Side", mode="paper",
                   symbols=["SIDEX"])
        _fill(cfg, "golden_cross", "BUY", 1.0)
        _fill(cfg, "golden_cross", "SELL", -1.0)
        _fill(cfg, "golden_cross", "SELL", 3.0, paper=False)
        opt = _cfg(self.user, asset_class="options", name="Opt", mode="paper",
                   symbols=["SIDEX"])
        _fill(opt, "golden_cross", "BUY", 2.0,
              meta={"right": "P", "underlying_signal_direction": "SELL"})
        _fill(opt, "golden_cross", "BUY", 0.5, meta={"right": "C"})
        rows = side_rows()
        stock = _row(rows, "golden_cross", "stock")
        self.assertEqual((stock["long"]["paper_n"], stock["long"]["paper_avg"]),
                         (1, 1.0))
        self.assertEqual((stock["short"]["paper_n"],
                          stock["short"]["live_n"],
                          stock["short"]["live_avg"]), (1, 1, 3.0))
        options = _row(rows, "golden_cross", "options")
        self.assertEqual((options["short"]["paper_n"],
                          options["short"]["paper_avg"]), (1, 2.0))
        self.assertEqual((options["long"]["paper_n"],
                          options["long"]["paper_avg"]), (1, 0.5))
        self.assertEqual(trade_side("BUY", "options",
                                    {"underlying_signal_direction": "SELL"}),
                         "short")
        self.assertEqual(trade_side("SELL", "stock", {}), "short")
        self.assertEqual(trade_side("HOLD", "stock", {}), "")

    def test_one_verdict_per_side_or_why_none(self):
        from backtester.models_proving import ProvingVerdict
        from bot_program.evidence import side_rows
        _graded(self.stock, "golden_cross", "bullish", 1.0)
        for side, verdict in (("long", "proven"),):
            ProvingVerdict.objects.create(
                run_id="rules-side", family="ma_cross",
                live_rule="golden_cross", params={}, direction=side,
                asset_class="stock", timeframe="4h", verdict=verdict,
                expectancy=0.3, trades_n=80, why="test")
        row = _row(side_rows(), "golden_cross", "stock")
        self.assertEqual(row["long"]["verdict"]["verdict"], "proven")
        self.assertEqual(row["long"]["verdict"]["trades_n"], 80)
        self.assertIsNone(row["short"]["verdict"])
        self.assertIn("replays golden_cross long only",
                      row["short"]["unjudged"])

    def test_a_born_name_with_no_row_reads_born_at_research(self):
        from bot_program.evidence import side_rows
        from signals.models import RuleControl
        _graded(self.stock, "death_cross", "bearish", 2.0)
        self.assertEqual(_row(side_rows(), "death_cross", "stock")["stage"],
                         "born at research")
        RuleControl.objects.create(rule_name="death_cross",
                                   promotion_stage="paper")
        self.assertEqual(_row(side_rows(), "death_cross", "stock")["stage"],
                         "paper")

    def test_the_gap_shows_from_twenty_graded_a_side(self):
        from bot_program.evidence import side_rows
        _graded(self.stock, "bollinger_squeeze_breakout", "bullish", 1.0, n=20)
        _graded(self.stock, "bollinger_squeeze_breakout", "bearish", -0.5,
                n=19)
        self.assertIsNone(_row(side_rows(), "bollinger_squeeze_breakout",
                               "stock")["gap"])
        _graded(self.stock, "bollinger_squeeze_breakout", "bearish", -0.5)
        self.assertAlmostEqual(_row(side_rows(), "bollinger_squeeze_breakout",
                                    "stock")["gap"], -1.5)

    def test_the_crowded_long_s_two_gates_are_two_rows(self):
        from backtester.models_proving import ProvingVerdict
        from backtester.proving import proof
        from backtester.proving.run import RULES_RUN_PREFIX
        from bot_program.evidence import side_rows
        cot, crowd = ("crowded_long_reversal_short",
                      "positioning_crowd_reversal_short")
        _graded(self.stock, cot, "bearish", 2.0, n=2)
        _graded(self.stock, crowd, "bearish", -1.0)
        ProvingVerdict.objects.create(
            run_id=f"{RULES_RUN_PREFIX}t", family="crowded_long",
            live_rule=cot, asset_class="stock", direction="short",
            timeframe="4h", policy=proof.POLICY, filter=proof.FILTER,
            generated=False, verdict="promising", trades_n=30)
        rows = side_rows()
        a, b = _row(rows, cot, "stock")["short"], _row(rows, crowd, "stock")["short"]
        self.assertEqual((a["sig_n"], a["sig_avg"]), (2, 2.0))
        self.assertEqual((b["sig_n"], b["sig_avg"]), (1, -1.0))
        self.assertEqual(a["verdict"]["verdict"], "promising")
        self.assertIsNone(b["verdict"])
        self.assertIn("replays no family for positioning_crowd_reversal_short",
                      b["unjudged"])
        self.assertNotIn("by_gate", _row(rows, cot, "stock"))

    def test_narrowing_by_rule_and_class(self):
        from bot_program.evidence import side_rows
        _graded(self.stock, "golden_cross", "bullish", 1.0)
        _graded(self.fx, "death_cross", "bearish", 1.0)
        self.assertEqual({r["rule"] for r in side_rows(rule="death_cross")},
                         {"death_cross"})
        self.assertEqual({r["asset_class"]
                          for r in side_rows(asset_class="stock")}, {"stock"})


class TheSurfacesTests(TestCase):

    def setUp(self):
        inst = _instrument("SIDEX", asset_class="stock")
        _graded(inst, "death_cross", "bearish", 2.0)
        self.user = User.objects.create_user("side_staff", password="x",
                                             is_staff=True)
        self.client = Client()
        self.client.force_login(self.user)

    def test_the_page_shows_the_table(self):
        html = self.client.get("/evidence/").content.decode()
        self.assertIn("By side — long against short, per rule and class", html)
        self.assertIn("born at research", html)

    def test_an_unreadable_scorecard_hides_nothing_else(self):
        with patch("dashboard.views_evidence.side_rows",
                   side_effect=RuntimeError("boom")):
            resp = self.client.get("/evidence/")
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn("The scorecard by side could not be read (boom)", html)
        self.assertIn("Rules — signals graded, paper proven, live taken", html)

    def test_the_command_prints_it(self):
        out = StringIO()
        call_command("side_scorecard", "--rule", "death_cross", stdout=out)
        text = out.getvalue()
        self.assertIn("death_cross · stock · stage born at research", text)
        self.assertIn("short  graded 1 · hit 100% · avg +2.00R", text)
