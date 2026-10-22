"""THE PEOPLE'S MOOD (2026-10-16, ai_agents/council_mood.py).

The operator: "the people could be happy or not depending on PnL, regime,
etc." A deterministic gauge, code only, no model, read from the
real-money book (world live only): its R over the last 5 and 20 trading
days, its fall from its peak, its losing streak of real closes, the day
against its stop, the market's measured stress and its open risk against
the ceiling. THE STRICT RULE: the mood may only counsel caution, never
boldness. There is no level above steady; an input not measured is said
unmeasured, never calm. It is shown to the Emperor in THE WAR, recorded
on every sitting, and graded on /council/ by what the trades returned
under each mood. R and percent only, never money.

Run with:  python manage.py test tests.test_council_mood
"""
import itertools
import json
import random
import re
from datetime import datetime, timedelta, timezone as dt_tz
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from tests.test_council_sitting import _Sitting, switch

REPO = Path(settings.BASE_DIR)

#: every input from its best reading to its worst, unmeasured first
GRID = {
    "r_short": [None, 50.0, 0.0, -1.99, -2.0, -3.99, -4.0, -50.0],
    "r_long": [None, 80.0, 0.0, -3.99, -4.0, -7.99, -8.0, -80.0],
    "drawdown": [None, 0.0, 0.049, 0.05, 0.124, 0.125, 0.199, 0.20, 0.9],
    "streak": [None, 0, 2, 3, 4, 12],
    "day_stop": [None, {"spent": 0.0, "mode": "open"},
                 {"spent": 0.49, "mode": "open"},
                 {"spent": 0.5, "mode": "open"},
                 {"spent": 1.1, "mode": "elite"},
                 {"spent": 1.6, "mode": "shut"}],
    "stress": [None, "calm", "recovery", "stressed", "crisis"],
    "open_risk_share": [None, 0.0, 0.49, 0.5, 0.75, 0.99, 1.0, 2.5],
}
BEST = {k: v[1] for k, v in GRID.items()}
WORST = {k: v[-1] for k, v in GRID.items()}
BOLD = ("press", "bold", "all in", "aggressive", "more", "raise",
        "increase")


def _mood(values: dict) -> dict:
    from ai_agents import council_mood as M
    inputs = {k: M.input_entry(k, values.get(k)) for k in M.INPUTS}
    return M.mood_of(inputs)


def _rank(level):
    from ai_agents import council_mood as M
    return M.MOOD_LEVELS.index(level)


class TheGaugeTests(SimpleTestCase):

    def _cases(self):
        rnd = random.Random(1016)
        out = [dict(BEST), dict(WORST), {k: None for k in GRID}]
        for k, values in GRID.items():
            for bg in (BEST, WORST, {kk: None for kk in GRID}):
                for v in values:
                    out.append(dict(bg, **{k: v}))
        for _ in range(1500):
            out.append({k: rnd.choice(v) for k, v in GRID.items()})
        return out

    def test_the_mood_never_argues_boldness_at_any_input(self):
        from ai_agents import council_mood as M
        self.assertEqual(M.MOOD_LEVELS, ("steady", "uneasy", "restless",
                                         "afraid"))
        self.assertEqual(M.MOOD_LEVELS[0], "steady", "no level above steady")
        self.assertEqual(_mood(BEST)["level"], "steady",
                         "a good run reads steady")
        self.assertEqual(M.CAUTION_ONLY, "The mood counsels caution only: a "
                                         "content people is never a reason "
                                         "to press.")
        for values in self._cases():
            mood = _mood(values)
            self.assertIn(mood["level"], M.MOOD_LEVELS + (M.UNMEASURED,))
            text = M.mood_text(mood)
            self.assertTrue(text.endswith(M.CAUTION_ONLY), text)
            said = " ".join([mood["level"], *mood["reasons"],
                             text.replace(M.CAUTION_ONLY, ""),
                             *M.LEVEL_WORDS.values()]).lower()
            for word in BOLD:
                self.assertNotIn(word, said, (word, values))

    def test_the_mood_is_monotone(self):
        """Worsening any single measured input never reads calmer."""
        rnd = random.Random(7)
        backgrounds = [BEST, WORST, {k: None for k in GRID}] + [
            {k: rnd.choice(v) for k, v in GRID.items()} for _ in range(40)]
        for bg in backgrounds:
            for k, values in GRID.items():
                ranks = [_rank(_mood(dict(bg, **{k: v}))["level"])
                         for v in values[1:]
                         if _mood(dict(bg, **{k: v}))["level"] != "unmeasured"]
                self.assertEqual(ranks, sorted(ranks), (k, bg))

    def test_each_band_is_the_platforms_own_threshold(self):
        from ai_agents import council_mood as M
        from bot_program import market_stress, posture, share_allocator
        from bot_program.asset_engine import safety
        self.assertEqual(M.DD_BANDS, (share_allocator.DD_KNEE,
                                      (share_allocator.DD_KNEE
                                       + share_allocator.DD_MAX) / 2,
                                      share_allocator.DD_MAX))
        self.assertEqual(M.STREAK_BANDS, (posture.STREAK_N,
                                          safety.DEFAULT_MAX_LOSS_STREAK))
        self.assertEqual(set(M.STRESS_BANDS), set(market_stress.LEVELS))
        self.assertEqual((M.MOOD_SHORT_DAYS, M.MOOD_LONG_DAYS), (5, 20))
        self.assertEqual((M.R_SHORT_BANDS, M.R_LONG_BANDS),
                         ((-2.0, -4.0), (-4.0, -8.0)))
        self.assertEqual(M.input_band("drawdown", 0.20), 3)
        self.assertEqual(M.input_band("stress", "crisis"), 3)
        self.assertEqual(M.input_band("open_risk_share", 1.0), 3)
        # the day's afraid level is the gate's own "shut", nothing else
        self.assertEqual(M.input_band("day_stop", {"spent": 0.0,
                                                   "mode": "shut"}), 3)
        self.assertEqual(M.input_band("day_stop", {"spent": 9.0,
                                                   "mode": "open"}), 1)
        self.assertEqual(M.input_band("day_stop", {"spent": 1.2,
                                                   "mode": "elite"}), 2)
        # the R windows and the streak never reach afraid alone
        for k in ("r_short", "r_long", "streak"):
            self.assertLessEqual(M.input_band(k, WORST[k]), 2, k)
        # three inputs at their first band: one step up
        self.assertEqual(M.BREADTH_N, 3)
        three = dict(BEST, r_short=-2.0, streak=3, open_risk_share=0.5)
        self.assertEqual(_mood(three)["level"], "restless")
        self.assertEqual(_mood(dict(three, stress="stressed"))["level"],
                         "afraid")

    def test_the_trading_days_count_weekdays(self):
        from ai_agents.council_mood import trading_days_start
        monday = datetime(2026, 10, 19, 10, 0, tzinfo=dt_tz.utc)
        self.assertEqual(trading_days_start(monday, 5),
                         datetime(2026, 10, 13, tzinfo=dt_tz.utc))
        self.assertEqual(trading_days_start(monday, 1),
                         datetime(2026, 10, 19, tzinfo=dt_tz.utc))
        saturday = datetime(2026, 10, 17, 10, 0, tzinfo=dt_tz.utc)
        self.assertEqual(trading_days_start(saturday, 1),
                         datetime(2026, 10, 16, tzinfo=dt_tz.utc))
        self.assertEqual(trading_days_start(monday, 20),
                         datetime(2026, 9, 22, tzinfo=dt_tz.utc))


class _Book(TestCase):

    @classmethod
    def setUpTestData(cls):
        from tests.test_risk_limits_bind import _config
        cls.user = get_user_model().objects.create_user("cm_u", password="x")
        cls.cfg = _config(cls.user, asset_class="stock", mode="live")

    def _close(self, r, *, at, paper=False, env=None):
        from bot_program.models import AssetBotTrade
        t = AssetBotTrade.objects.create(
            config=self.cfg, asset_class="stock", symbol="MOOD", side="BUY",
            qty=Decimal("1"), entry_price=Decimal("100"),
            stop_loss=Decimal("98"), take_profit=Decimal("104"),
            status="CLOSED", realized_r=r, paper=paper,
            metadata={"broker_env": env} if env else {})
        AssetBotTrade.objects.filter(id=t.id).update(closed_at=at)
        return t

    def read(self, now=None):
        from ai_agents.council_mood import people_mood
        return people_mood(self.user, now=now)


MONDAY = datetime(2026, 10, 19, 10, 0, tzinfo=dt_tz.utc)


class TheReadTests(_Book):

    def test_unmeasured_inputs_are_said_unmeasured_never_calm(self):
        from ai_agents import council_mood as M
        switch("crisis_mode", False)
        # no broker, no book value, crisis mode OFF, no close
        nobook = {"limit_pct": 3.0, "book_value": None, "realized": None,
                  "mode": "open", "open_risk": 0.0}
        with patch("portfolio.risk_gate.daily_loss_state",
                   return_value=nobook), \
                patch("portfolio.risk_gate.open_risk_state",
                      return_value=nobook):
            mood = self.read()
        inputs = mood["inputs"]
        for k, why in (("drawdown", "no broker-backed account"),
                       ("day_stop", "no book value"),
                       ("open_risk_share", "no book value"),
                       ("stress", "crisis mode OFF: unmeasured")):
            with self.subTest(k=k):
                self.assertFalse(inputs[k]["measured"])
                self.assertIsNone(inputs[k]["band"])
                self.assertIn(f"unmeasured ({why}", inputs[k]["words"])
        text = M.mood_text(mood)
        self.assertIn("market stress: unmeasured (crisis mode OFF: "
                      "unmeasured)", text)
        # no close at all is a flat run, measured
        self.assertEqual((inputs["r_short"]["measured"],
                          inputs["r_short"]["reading"]), (True, 0.0))
        # every close unpriced: unmeasured, never a flat run
        self._close(None, at=timezone.now() - timedelta(hours=2))
        inputs = self.read()["inputs"]
        for k in ("r_short", "r_long", "streak"):
            self.assertFalse(inputs[k]["measured"], k)
            self.assertIn("unpriced", inputs[k]["words"])
        # an equity reading that cannot say: each named
        acct = SimpleNamespace(pk=1)
        cases = (("live", None, "no equity reading"),
                 ("paper", {"drawdown_pct": 0.3, "n": 5, "stale": False},
                  "the account reads its rehearsal world"),
                 ("live", {"drawdown_pct": 0.3, "n": 0, "stale": False},
                  "one reading is no peak"),
                 ("live", {"drawdown_pct": 0.3, "n": 5, "stale": True,
                           "age_seconds": 7200}, "the last reading is stale"))
        for env, dd, why in cases:
            with self.subTest(why=why), \
                    patch("bot_program.capital_truth.broker_backed",
                          return_value=acct), \
                    patch("bot_program.capital_truth.broker_env",
                          return_value=env), \
                    patch("bot_program.capital_truth.equity_drawdown",
                          return_value=dd):
                e = self.read()["inputs"]["drawdown"]
                self.assertEqual((e["measured"], e["band"]), (False, None))
                self.assertIn(why, e["words"])
        # no limit set, or a day whose closes carry no price
        for state, k, why in (
                ({"limit_pct": None, "book_value": 100.0}, "day_stop",
                 "no daily-loss limit set on the book"),
                ({"limit_pct": None, "book_value": 100.0}, "open_risk_share",
                 "no open-risk limit set on the book"),
                ({"limit_pct": 3.0, "book_value": 100.0, "realized": None,
                  "mode": "open"}, "day_stop",
                 "the day's closes carry no price")):
            with self.subTest(k=k, why=why), \
                    patch("portfolio.risk_gate.daily_loss_state",
                          return_value=state), \
                    patch("portfolio.risk_gate.open_risk_state",
                          return_value=state):
                e = self.read()["inputs"][k]
                self.assertEqual((e["measured"], e["words"]),
                                 (False, f"unmeasured ({why})"))
        # every input unmeasured: the mood is unmeasured, never steady
        nothing = {k: M.input_entry(k, None, why="x") for k in M.INPUTS}
        self.assertEqual(M.mood_of(nothing)["level"], "unmeasured")
        self.assertIn("never", M.LEVEL_WORDS["unmeasured"])

    def test_a_calm_override_is_unmeasured_and_a_stressed_one_counts(self):
        base = {"score": None, "fresh": True, "crisis_mode_on": True,
                "why": "operator override until 2026-10-17", "note": ""}
        with patch("brain.strategist.measured_posture",
                   return_value=dict(base, level="calm (override)",
                                     raw_level="calm")):
            e = self.read()["inputs"]["stress"]
        self.assertEqual((e["measured"], e["band"]), (False, None))
        self.assertIn("calm is only read from a measurement", e["words"])
        with patch("brain.strategist.measured_posture",
                   return_value=dict(base, level="stressed (override)",
                                     raw_level="stressed")):
            e = self.read()["inputs"]["stress"]
        self.assertEqual((e["measured"], e["band"]), (True, 2))
        with patch("brain.strategist.measured_posture",
                   return_value=dict(base, level="unmeasured",
                                     raw_level="calm", why="")):
            e = self.read()["inputs"]["stress"]
        self.assertFalse(e["measured"])
        with patch("brain.strategist.measured_posture",
                   return_value=dict(base, level="calm", raw_level="calm",
                                     score=12.0, why="score 12")):
            e = self.read()["inputs"]["stress"]
        self.assertEqual((e["measured"], e["band"], e["reading"]),
                         (True, 0, "calm"))

    def test_the_mood_reads_the_live_world_only(self):
        sat = datetime(2026, 10, 17, 12, 0, tzinfo=dt_tz.utc)
        last_monday = datetime(2026, 10, 12, 12, 0, tzinfo=dt_tz.utc)
        # the demo world (broker_env "paper") and paper: never the book
        self._close(-5.0, at=sat, env="paper")
        self._close(-5.0, at=sat, paper=True)
        inputs = self.read(MONDAY)["inputs"]
        self.assertEqual((inputs["r_short"]["reading"],
                          inputs["r_long"]["reading"],
                          inputs["streak"]["reading"]), (0.0, 0.0, 0))
        # live closes count; a weekend close is inside the five days
        self._close(-1.0, at=sat)
        self._close(-3.0, at=last_monday)       # before Tuesday the 13th
        self._close(-2.0, at=MONDAY - timedelta(days=40))   # outside both
        inputs = self.read(MONDAY)["inputs"]
        self.assertEqual(inputs["r_short"]["reading"], -1.0)
        self.assertEqual(inputs["r_long"]["reading"], -4.0)
        self.assertEqual(inputs["r_long"]["band"], 1)
        self.assertIn("over 2 real closes", inputs["r_long"]["words"])
        self.assertEqual(inputs["streak"]["reading"], 2)

    def test_the_losing_streak_skips_unpriced_and_ends_at_a_win(self):
        now = timezone.now()
        for hours, r in ((1, -1.0), (2, None), (3, -1.0), (4, 0.5),
                         (5, -1.0), (6, -1.0)):
            self._close(r, at=now - timedelta(hours=hours))
        e = self.read()["inputs"]["streak"]
        self.assertEqual((e["reading"], e["band"]), (2, 0))
        self.assertIn("1 unpriced skipped", e["words"])
        self._close(-1.0, at=now - timedelta(minutes=30))
        e = self.read()["inputs"]["streak"]
        self.assertEqual((e["reading"], e["band"]), (3, 1))
        # every priced close in the window lost: at least that many
        from bot_program.models import AssetBotTrade
        AssetBotTrade.objects.filter(realized_r__gt=0).delete()
        e = self.read()["inputs"]["streak"]
        self.assertEqual((e["reading"], e["band"]), (5, 2))
        self.assertTrue(e["words"].startswith("at least 5"), e["words"])

    def test_no_money_in_the_mood(self):
        from ai_agents import council_mood as M
        from tests.test_council_sitting import TheWarAndFootprintsTests
        daily = {"ok": False, "limit_pct": 8.0, "book_value": 10000.0,
                 "realized": -1234.56, "mode": "elite", "measured": True,
                 "limit_money": -800.0,
                 "reason": "daily loss limit hit: -1,234.56 realized"}
        opened = {"ok": True, "limit_pct": 15.0, "book_value": 10000.0,
                  "open_risk": 900.5, "rows": 3, "limit_money": 1500.0,
                  "reason": "900.50 at the stops"}
        equity = {"value": 52340.12, "hwm": 60000.0, "drawdown_pct": 0.1277,
                  "n": 12, "stale": False, "age_seconds": 60,
                  "currency": "USD"}
        with patch("portfolio.risk_gate.daily_loss_state",
                   return_value=daily), \
                patch("portfolio.risk_gate.open_risk_state",
                      return_value=opened), \
                patch("bot_program.capital_truth.broker_backed",
                      return_value=SimpleNamespace(pk=1)), \
                patch("bot_program.capital_truth.broker_env",
                      return_value="live"), \
                patch("bot_program.capital_truth.equity_drawdown",
                      return_value=equity):
            mood = self.read()
        inputs = mood["inputs"]
        self.assertEqual(inputs["day_stop"]["band"], 2)
        self.assertEqual(inputs["drawdown"]["band"], 2)
        self.assertEqual(inputs["open_risk_share"]["band"], 1)
        self.assertIn("9.0% of the book, 60% of its 15% ceiling",
                      inputs["open_risk_share"]["words"])
        # the reading's time aside (its digits are a clock, not money)
        stored = json.dumps({k: v for k, v in mood.items() if k != "at"})

        def keys(obj):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    yield k
                    yield from keys(v)
            elif isinstance(obj, (list, tuple)):
                for v in obj:
                    yield from keys(v)

        banned = {"value", "hwm", "book_value", "open_risk", "limit_money",
                  "realized", "currency"}
        self.assertEqual(set(keys(json.loads(stored))) & banned, set())
        text = M.mood_text(mood)
        for money in ("1234", "1,234", "900.5", "10000", "10,000", "52340",
                      "60000", "USD"):
            self.assertNotIn(money, stored)
            self.assertNotIn(money, text)
        currency = TheWarAndFootprintsTests._currency(self)
        self.assertIsNone(currency.search(text), text)
        self.assertIsNone(currency.search(stored), stored)


class TheChairsWarTests(_Sitting):

    def test_the_mood_is_shown_to_the_chair_in_the_war_and_recorded(self):
        rec, s = self.sit()
        self.assertIn(s.mood, ("steady", "uneasy", "restless", "afraid",
                               "unmeasured"))
        self.assertEqual(s.mood_read["level"], s.mood)
        self.assertEqual(set(s.mood_read["inputs"]),
                         {"r_short", "r_long", "drawdown", "streak",
                          "day_stop", "stress", "open_risk_share"})
        e = rec.briefs["emperor"]
        war, mood, prints = (e.index("THE WAR"),
                             e.index("the people's mood:"),
                             e.index("FOOTPRINTS"))
        self.assertLess(war, mood)
        self.assertLess(mood, prints)
        self.assertIn("The mood counsels caution only: a content people is "
                      "never a reason to press.", e)
        for v, brief in rec.briefs.items():
            if v != "emperor":
                self.assertNotIn("the people's mood", brief, v)
        self.assertNotIn("the people's mood", s.extras)

    def test_a_sitting_refused_at_the_first_wave_still_records_the_mood(self):
        rec, s = self.sit(spend=lambda **kw: (False, "daily AI budget spent"))
        self.assertEqual(rec.calls, [])
        self.assertNotEqual(s.mood, "")
        self.assertEqual(s.mood_read["level"], s.mood)

    def test_a_mood_that_cannot_be_read_is_unmeasured_and_the_sitting_sits(self):
        with patch("ai_agents.council_mood.people_mood",
                   side_effect=RuntimeError("db")):
            rec, s = self.sit()
        self.assertEqual(s.status, "done")
        self.assertEqual(s.mood, "unmeasured")
        self.assertIn("the people's mood: unmeasured", rec.briefs["emperor"])

    def test_the_mood_is_pure_code_no_model_call(self):
        from ai_agents import council_mood as M
        with patch("ai_agents.base_agent.BaseAgent.run") as run, \
                patch("ai_agents.spend.can_spend") as spend:
            mood = M.people_mood(self.user)
        run.assert_not_called()
        spend.assert_not_called()
        self.assertIn(mood["level"], M.MOOD_LEVELS + (M.UNMEASURED,))
        rec, s = self.sit()
        self.assertEqual(len(rec.calls), 8, rec.calls)
        src = (REPO / "ai_agents" / "council_mood.py").read_text(
            encoding="utf-8")
        for banned in ("agents.", "BaseAgent", "anthropic", "run(",
                       "can_spend", "voice_weight", "Portfolio.objects",
                       ".max_daily_loss", "telegram", "alerts."):
            self.assertNotIn(banned, src, banned)


class TheOutcomesTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.staff = get_user_model().objects.create_user(
            "cm_staff", password="x", is_staff=True)

    def _sat(self, mood, r, commit):
        from ai_agents.council_models import CouncilSession, CouncilVoice
        s = CouncilSession.objects.create(
            origin="bot", status="done", symbol="X", venue="live",
            mood=mood, truth="realized", truth_r=r,
            y=1 if r >= 0.25 else 0 if r <= -0.25 else None,
            graded_at=timezone.now())
        CouncilVoice.objects.create(session=s, voice="emperor", wave=3,
                                    status="spoke",
                                    answer={"verdict": "x", "commit": commit})
        return s

    def test_outcomes_are_shown_by_mood_level(self):
        from ai_agents.council_mood import mood_outcomes
        for i in range(10):
            self._sat("steady", 1.0 if i < 6 else -1.0, 1.0)
        self._sat("uneasy", -1.0, 0.5)
        self._sat("afraid", -2.0, 0.0)
        self._sat("", 1.0, 1.0)                      # before the gauge
        rows = {r["level"]: r for r in mood_outcomes(
            timezone.now() - timedelta(days=1))}
        self.assertEqual(list(rows), ["steady", "uneasy", "restless",
                                      "afraid", "unmeasured", "not read"])
        st = rows["steady"]
        self.assertEqual((st["n"], st["thin"]), (10, False))
        self.assertAlmostEqual(st["avg_r"], 0.2)
        self.assertAlmostEqual(st["won_pct"], 60.0)
        self.assertAlmostEqual(st["commit_pct"], 100.0)
        self.assertEqual((rows["uneasy"]["n"], rows["uneasy"]["thin"]),
                         (1, True))
        self.assertAlmostEqual(rows["afraid"]["commit_pct"], 0.0)
        self.assertEqual(rows["restless"]["n"], 0)
        self.assertEqual(rows["not read"]["n"], 1)
        self.client.force_login(self.staff)
        resp = self.client.get("/council/")
        html = resp.content.decode()
        section = html[html.index('data-role="council-mood"'):
                       html.index('data-role="council-recent"')]
        self.assertIn("too few to read", section)
        self.assertIn("+0.20R", section)
        self.assertIn("60%", section)
        self.assertNotIn("$", section)
        self.assertIn("It may only counsel caution: a good run reads steady.",
                      section)


class TheBindingTests(SimpleTestCase):

    def test_nothing_that_binds_reads_the_mood_or_the_hand(self):
        for path in ("bot_program/asset_engine/base.py",
                     "bot_program/manual_trade.py",
                     "bot_program/asset_engine/sizing.py",
                     "portfolio/risk_gate.py", "bot_program/posture.py",
                     "ai_agents/agents/trade_debate.py"):
            text = (REPO / path).read_text(encoding="utf-8")
            for name in ("council_mood", "people_mood", "hand_of",
                         "most_trusted"):
                with self.subTest(path=path, name=name):
                    self.assertNotIn(name, text)
