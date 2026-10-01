"""The trade debate: the Executioner and the Champion (2026-10-01).

The operator: a personality that argues why every position will fail, and
its opposite. Every LIVE bot entry is argued before its order; the
verdicts ride the row. Shadow for the first 30 graded live trades (the
operator: "30 trades à blanc"), binding after: the Executioner may cut
(never below 0.25x) or veto, and an elite entry past the day's loss limit
needs the Champion to win. A debate that could not run changes nothing
and keeps the elite door shut. Paper entries are never debated.

Run with:  python manage.py test tests.test_trade_debate
"""
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

EX_RUN = "ai_agents.agents.trade_debate.ExecutionerAgent.run"
CH_RUN = "ai_agents.agents.trade_debate.ChampionAgent.run"
SPEND = "ai_agents.spend.can_spend"


def _switch(on=True):
    from core.platform_control import PlatformComponent
    PlatformComponent.objects.update_or_create(
        key="trade_debate", defaults={"name": "Trade Debate",
                                      "category": "system",
                                      "is_enabled": on})


def _ex(verdict="pass", conviction=0.3, scale=1.0, killer="k"):
    return {"verdict": verdict, "conviction": conviction,
            "size_scale": scale, "killer": killer, "reasons": []}


def _ch(verdict="back", conviction=0.7):
    return {"verdict": verdict, "conviction": conviction, "edge": "e",
            "reasons": []}


class TheParsersTests(SimpleTestCase):

    def _ex(self):
        from ai_agents.agents.trade_debate import ExecutionerAgent
        return ExecutionerAgent.__new__(ExecutionerAgent)

    def _ch(self):
        from ai_agents.agents.trade_debate import ChampionAgent
        return ChampionAgent.__new__(ChampionAgent)

    def test_the_executioner_cuts_never_below_a_quarter(self):
        out = self._ex().parse_response(
            '```json\n{"verdict": "cut", "conviction": 0.6, '
            '"size_scale": 0.1, "killer": "fights the trend", '
            '"reasons": ["a", "b"]}\n```')
        self.assertEqual((out["verdict"], out["size_scale"]), ("cut", 0.25))
        self.assertEqual(out["killer"], "fights the trend")

    def test_a_pass_keeps_the_size_and_a_veto_is_read(self):
        self.assertEqual(self._ex().parse_response(
            '{"verdict": "pass", "conviction": 0.2, "size_scale": 0.5}'
        )["size_scale"], 1.0)
        self.assertEqual(self._ex().parse_response(
            'The call: {"verdict": "veto", "conviction": 0.9}')["verdict"],
            "veto")

    def test_an_unknown_verdict_or_no_json_raises(self):
        with self.assertRaises(ValueError):
            self._ex().parse_response('{"verdict": "maybe"}')
        with self.assertRaises(ValueError):
            self._ex().parse_response("no json here")
        with self.assertRaises(ValueError):
            self._ch().parse_response('{"verdict": "love it"}')

    def test_prose_braces_drafts_and_percent_are_read(self):
        ex = self._ex()
        out = ex.parse_response(
            'Thinking: the {regime} matters. Draft {"verdict": "pass"} -> '
            'final: {"verdict": " Veto ", "conviction": 0.8} note {x}')
        self.assertEqual(out["verdict"], "veto", "the LAST verdict object")
        out = ex.parse_response('{"verdict": "cut", "size_scale": "50%"}')
        self.assertEqual(out["size_scale"], 0.5)
        self.assertEqual(out["conviction"], 1.0,
                         "a missing prosecutor conviction reads full")

    def test_the_champion_is_read_and_conviction_clamped(self):
        out = self._ch().parse_response(
            '{"verdict": "back", "conviction": 1.7, "edge": "measured edge"}')
        self.assertEqual((out["verdict"], out["conviction"]), ("back", 1.0))


class TheModelTests(TestCase):

    def test_both_sides_answer_on_opus_5_5_unless_the_operator_sets_one(self):
        from ai_agents.agents.trade_debate import (ChampionAgent,
                                                   ExecutionerAgent,
                                                   _agent_model)
        from ai_agents.models import AIModelSetting
        self.assertEqual(_agent_model("debate_executioner"), "claude-opus-5-5")
        AIModelSetting.objects.create(scope="agent", key="debate_champion",
                                      model_id="claude-sonnet-5")
        self.assertEqual(_agent_model("debate_champion"), "claude-sonnet-5")
        self.assertEqual(ExecutionerAgent.agent_name, "debate_executioner")
        self.assertEqual(ChampionAgent.agent_name, "debate_champion")

    def test_the_catalog_prices_opus_5_5(self):
        from ai_agents.catalog import MODELS, pricing_for
        self.assertEqual(pricing_for("claude-opus-5-5"),
                         {"input": 4.0, "output": 20.0})
        self.assertTrue(MODELS["claude-opus-5-5"]["effort"])

    def test_the_switch_is_seeded_off(self):
        from core.platform_control import PlatformComponent, seed_components
        seed_components()
        self.assertFalse(PlatformComponent.objects.get(
            key="trade_debate").is_enabled)


class TheDebateTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("deb_u",
                                                        password="x")

    def setUp(self):
        from bot_program.asset_engine.base import make_bot
        from tests.test_risk_limits_bind import _config
        self.bot = make_bot(_config(self.user, symbols=["BTCUSD"],
                                    mode="live"))
        self.cand = SimpleNamespace(
            symbol="BTCUSD", asset_class="crypto", price=60000.0,
            stop=59100.0, target=61800.0, value_per_unit=1.0,
            cost={"fraction": 0.001}, elite={},
            decision=SimpleNamespace(direction="BUY", rule_name="golden_cross",
                                     score=0.8, reasons=["golden cross"]))

    def _debate(self, ex=None, ch=None, ex_raise=None, ch_raise=None):
        from ai_agents.agents.trade_debate import debate_candidate
        with patch(SPEND, return_value=(True, "")), \
                patch(EX_RUN, side_effect=ex_raise, return_value=ex), \
                patch(CH_RUN, side_effect=ch_raise, return_value=ch):
            return debate_candidate(self.bot, self.cand, 0.01)

    def test_off_nothing_runs(self):
        from ai_agents.agents.trade_debate import debate_candidate
        with patch(EX_RUN) as ex:
            out = debate_candidate(self.bot, self.cand, 0.01)
        ex.assert_not_called()
        self.assertFalse(out["ran"])
        self.assertIn("trade_debate is OFF", out["why"])

    def test_shadow_until_thirty_graded(self):
        _switch()
        out = self._debate(_ex("veto", 0.9), _ch("back", 0.4))
        self.assertTrue(out["ran"])
        self.assertFalse(out["binding"])
        self.assertTrue(out["veto"])          # what it WOULD do
        self.assertFalse(out["champion_wins"])

    def test_binding_from_thirty_graded_live_trades(self):
        from bot_program.models import AssetBotTrade
        _switch()
        for _ in range(30):
            AssetBotTrade.objects.create(
                config=self.bot.cfg, asset_class="crypto", symbol="BTCUSD",
                side="BUY", qty=Decimal("1"), entry_price=Decimal("100"),
                status="CLOSED", paper=False, pnl=Decimal("1"),
                metadata={"debate": {"ran": True}})
        # a paper row, an open row, a debate that did not run and a demo
        # fill do not count: none of them is real-money shadow evidence
        for status, paper, ran, env in (("CLOSED", True, True, "live"),
                                        ("OPEN", False, True, "live"),
                                        ("CLOSED", False, False, "live"),
                                        ("CLOSED", False, True, "paper")):
            AssetBotTrade.objects.create(
                config=self.bot.cfg, asset_class="crypto", symbol="BTCUSD",
                side="BUY", qty=Decimal("1"), entry_price=Decimal("100"),
                status=status, paper=paper, pnl=Decimal("1"),
                metadata={"debate": {"ran": ran}, "broker_env": env})
        out = self._debate(_ex("cut", 0.5, 0.5), _ch("back", 0.8))
        self.assertTrue(out["binding"])
        self.assertEqual(out["graded"], 30)
        self.assertEqual(out["scale"], 0.5)
        self.assertTrue(out["champion_wins"])

    def test_a_silent_side_keeps_the_elite_door_shut(self):
        _switch()
        out = self._debate(ex=_ex("pass", 0.1), ch_raise=RuntimeError("api"))
        self.assertFalse(out["ran"])
        self.assertFalse(out["champion_wins"])
        self.assertIn("champion unavailable", out["why"])
        out = self._debate(ex_raise=RuntimeError("api"), ch=_ch("back", 0.9))
        self.assertFalse(out["veto"])         # never a veto by silence
        self.assertFalse(out["champion_wins"])

    def test_a_side_too_slow_is_silent_and_the_sides_run_together(self):
        import threading
        import time
        _switch()
        seen = set()

        def slow(**_):
            seen.add(threading.current_thread().name)
            time.sleep(0.5)
            return _ex("veto", 0.9)

        def fast(**_):
            seen.add(threading.current_thread().name)
            return _ch("back", 0.9)

        from ai_agents.agents.trade_debate import debate_candidate
        with patch("ai_agents.agents.trade_debate.DEBATE_TIMEOUT_S", 0.1), \
                patch(SPEND, return_value=(True, "")), \
                patch(EX_RUN, side_effect=slow), \
                patch(CH_RUN, side_effect=fast):
            out = debate_candidate(self.bot, self.cand, 0.01)
        self.assertFalse(out["ran"])
        self.assertFalse(out["veto"])          # never a veto by silence
        self.assertFalse(out["champion_wins"])
        self.assertIn("executioner unavailable (timeout)", out["why"])
        self.assertEqual(len(seen), 2)
        self.assertTrue(all(n.startswith("debate") for n in seen))

    def test_the_champion_wins_only_backing_with_more_conviction(self):
        _switch()
        self.assertFalse(self._debate(_ex("pass", 0.6),
                                      _ch("back", 0.6))["champion_wins"])
        self.assertFalse(self._debate(_ex("pass", 0.1),
                                      _ch("neutral", 0.9))["champion_wins"])

    def test_rows_stamped_while_off_never_shorten_the_shadow(self):
        from ai_agents.agents.trade_debate import graded_count
        from bot_program.models import AssetBotTrade
        for _ in range(40):
            AssetBotTrade.objects.create(
                config=self.bot.cfg, asset_class="crypto", symbol="BTCUSD",
                side="BUY", qty=Decimal("1"), entry_price=Decimal("100"),
                status="CLOSED", paper=False, pnl=Decimal("1"),
                metadata={"debate": {"ran": False,
                                     "why": "trade_debate is OFF"}})
        self.assertEqual(graded_count(), 0)

    def test_a_binding_refusal_is_held_and_not_reargued(self):
        from ai_agents.agents.trade_debate import (debate_candidate,
                                                   remember_refusal)
        from django.core.cache import cache
        cache.clear()
        _switch()
        with patch("ai_agents.agents.trade_debate.graded_count",
                   return_value=30):
            remember_refusal(self.bot, self.cand, "the Executioner vetoed it")
            with patch(EX_RUN) as ex:
                out = debate_candidate(self.bot, self.cand, 0.01)
        ex.assert_not_called()
        self.assertTrue(out["held"])
        self.assertIn("vetoed", out["why"])
        cache.clear()

    def test_a_spent_ai_budget_runs_nothing(self):
        from ai_agents.agents.trade_debate import debate_candidate
        _switch()
        with patch(SPEND, return_value=(False, "daily AI budget spent")), \
                patch(EX_RUN) as ex:
            out = debate_candidate(self.bot, self.cand, 0.01)
        ex.assert_not_called()
        self.assertIn("AI budget", out["why"])

    def test_the_brief_says_the_trade_and_the_record(self):
        from ai_agents.agents.trade_debate import candidate_brief
        brief = candidate_brief(self.bot, self.cand, 0.01)
        self.assertIn("BTCUSD (crypto) BUY — real money", brief)
        self.assertIn("net reward:risk", brief)
        self.assertIn("rule golden_cross", brief)


class TheWiringTests(SimpleTestCase):

    def test_execute_entry_debates_real_money_only_and_binds_after_shadow(self):
        import inspect

        from bot_program.asset_engine.base import AssetBot
        src = inspect.getsource(AssetBot.execute_entry)
        self.assertEqual(src.count("debate_candidate(self, cand, qty)"), 1)
        self.assertIn('if debate.get("binding"):', src)
        self.assertIn('if debate.get("veto"):', src)
        self.assertIn("qty = self._round_qty(qty * _scale", src)
        self.assertIn('and not debate.get("champion_wins")', src)
        self.assertIn('entry_meta["debate"] = {', src)
        self.assertIn('remember_refusal(self, cand, _veto, kind="veto")', src)
        # the kill switch / disarm is read AGAIN after the debate
        self.assertLess(src.index("debate_candidate(self, cand, qty)"),
                        src.rindex("self._still_armed()"))
        self.assertLess(src.rindex("self._still_armed()"),
                        src.index("client.market_order("))
        # a cut size meets the fee, the multiplier and the headroom again
        cut = src.index("THE CUT SIZE meets")
        for again in ("self._venue_fee_refusal(", "self._order_leverage(",
                      "self._leverage_headroom("):
            self.assertGreater(src.index(again, cut), cut, again)
        # 2026-10-02: argued after EVERY deterministic refusal — the proof
        # gate, the fee, the floor, the multiplier, the headroom, the
        # disarm — and right before the order: only an order about to be
        # sent is debated (and billed)
        at = src.index("debate_candidate(self, cand, qty)")
        for gate in ("self._etoro_entry_refusal(", "self._venue_fee_refusal(",
                     "self._venue_size_floor(", "self._order_leverage(",
                     "self._leverage_headroom(", "self._still_armed()"):
            self.assertLess(src.index(gate), at, gate)   # first occurrence
        self.assertLess(at, src.index("client.market_order("))
