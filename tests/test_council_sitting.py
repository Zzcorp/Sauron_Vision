"""THE COUNCIL's sitting (2026-10-08, ai_agents/agents/council.py).

The debate's two verdicts are recorded where they can be graded; once a
LIVE bot order has left, the eight shadow voices sit on the ai queue in
three waves (the Emperor last, reading everyone and each voice's record);
every call goes through the daily AI budget; an unavailable voice is
silent and changes nothing. FAKE models only: every agent's run() is
patched, as tests/test_trade_debate.py does. No network, no key.

Run with:  python manage.py test tests.test_council_sitting
"""
import contextlib
import re
import sys
import threading
import time
import types
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

EX_RUN = "ai_agents.agents.trade_debate.ExecutionerAgent.run"
CH_RUN = "ai_agents.agents.trade_debate.ChampionAgent.run"
SPEND = "ai_agents.spend.can_spend"
DELAY = "ai_agents.tasks.run_council_sitting.apply_async"
CLASSES = {"executioner": "CouncilExecutioner", "champion": "CouncilChampion",
           "opportunist": "OpportunistAgent", "striker": "StrikerAgent",
           "fixer": "FixerAgent", "gambler": "GamblerAgent",
           "emperor": "EmperorAgent", "skeptic": "SkepticAgent",
           "awakened": "AwakenedAgent", "theorist": "TheoristAgent"}


def switch(key, on=True):
    from core.platform_control import PlatformComponent
    PlatformComponent.objects.update_or_create(
        key=key, defaults={"name": key, "category": "agent",
                           "is_enabled": on})


def default_answers() -> dict:
    from tests.test_council_voices import VALID, parse
    out = {v: parse(v, a) for v, a in VALID.items()}
    out["executioner"] = {"verdict": "pass", "conviction": 0.3,
                          "size_scale": 1.0, "killer": "k", "reasons": []}
    out["champion"] = {"verdict": "back", "conviction": 0.7, "edge": "e",
                       "reasons": []}
    return out


class Recorder:
    """The fake models: one answer per voice (a dict, an exception to
    raise, or a callable), and what each voice was sent."""

    def __init__(self, answers=None):
        self.answers = dict(default_answers(), **(answers or {}))
        self.briefs, self.threads, self.calls = {}, {}, []
        self.lock = threading.Lock()

    def side(self, voice):
        def run(**kw):
            with self.lock:
                self.briefs[voice] = kw.get("brief", "")
                self.threads[voice] = threading.current_thread().name
                self.calls.append(voice)
            a = self.answers[voice]
            if isinstance(a, Exception):
                raise a
            if callable(a):
                return a()
            return a
        return run

    @contextlib.contextmanager
    def patched(self, spend=None):
        with contextlib.ExitStack() as stack:
            for voice, cls in CLASSES.items():
                stack.enter_context(patch(
                    f"ai_agents.agents.council.{cls}.run",
                    side_effect=self.side(voice)))
            self.spend = stack.enter_context(patch(
                SPEND, side_effect=spend or (lambda **kw: (True, ""))))
            yield self


def make_bot_and_cand(user, symbol="BTCUSD"):
    from bot_program.asset_engine.base import make_bot
    from tests.test_risk_limits_bind import _config
    bot = make_bot(_config(user, symbols=[symbol], mode="live"))
    cand = SimpleNamespace(
        symbol=symbol, asset_class="crypto", price=60000.0, stop=59100.0,
        target=61800.0, value_per_unit=1.0, cost={"fraction": 0.001},
        elite={}, level_meta={"smart_money": {"ict_bias": "long",
                                              "sweep_against": True}},
        stage={"proof": {"words": "proven"}},
        decision=SimpleNamespace(direction="BUY", rule_name="golden_cross",
                                 score=0.8, reasons=["golden cross"]))
    return bot, cand


def debated_session(bot, cand, ex=None, ch=None):
    """A real debate (both sides patched) that opened its record."""
    from ai_agents.agents.trade_debate import debate_candidate
    switch("trade_debate")
    with patch(SPEND, return_value=(True, "")), \
            patch(EX_RUN, return_value=ex or {
                "verdict": "veto", "conviction": 0.9, "size_scale": 1.0,
                "killer": "fights the trend", "reasons": []}), \
            patch(CH_RUN, return_value=ch or {
                "verdict": "back", "conviction": 0.6, "edge": "trend",
                "reasons": []}):
        return debate_candidate(bot, cand, 0.01)


def live_row(bot, *, council_id=None, paper=False, env=None, **kw):
    from bot_program.models import AssetBotTrade
    meta = {}
    if council_id is not None:
        meta["debate"] = {"ran": True, "council_id": council_id}
    if env:
        meta["broker_env"] = env
    return AssetBotTrade.objects.create(
        config=bot.cfg, asset_class="crypto", symbol="BTCUSD", side="BUY",
        qty=Decimal("0.01"), entry_price=Decimal("60000"),
        stop_loss=Decimal("59100"), take_profit=Decimal("61800"),
        paper=paper, metadata=meta, **kw)


class TheRecordOpensTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("cs_rec", password="x")

    def setUp(self):
        self.bot, self.cand = make_bot_and_cand(self.user)

    def test_a_debate_that_ran_opens_its_record_at_no_ai_cost(self):
        from ai_agents.council_models import CouncilSession
        rep = {"regime": "trending", "confidence": 0.7, "report_id": 5,
               "source": "BrainReport #5"}
        with patch("bot_program.persona_mix.latest_report", return_value=rep):
            out = debated_session(self.bot, self.cand)
        self.assertTrue(out["ran"])
        s = CouncilSession.objects.get(id=out["council_id"])
        self.assertEqual((s.origin, s.venue, s.status), ("bot", "live",
                                                         "record"))
        self.assertEqual((s.regime, s.regime_report_id), ("trending", 5))
        self.assertIn("BTCUSD (crypto) BUY", s.brief)
        self.assertEqual((s.entry, s.stop, s.target), (60000.0, 59100.0,
                                                       61800.0))
        self.assertEqual(s.cost_fraction, 0.001)
        self.assertEqual(s.facts["smart_money"]["ict_bias"], "long")
        self.assertEqual(s.facts["proof"], "proven")
        voices = {v.voice: v for v in s.voices.all()}
        self.assertEqual({v.status for v in voices.values()}, {"copied"})
        self.assertEqual(voices["executioner"].wave, 0)
        self.assertAlmostEqual(voices["executioner"].p_work, 0.1)
        claims = {(c.voice_key, c.kind): c for c in s.claims.all()}
        self.assertAlmostEqual(claims[("executioner", "work")].p, 0.1)
        self.assertEqual(claims[("executioner", "stance")].stance, "against")
        self.assertEqual(claims[("champion", "stance")].stance, "for")
        self.assertEqual({c.regime for c in claims.values()}, {"trending"})

    def test_a_silent_side_is_recorded_silent(self):
        from ai_agents.agents.trade_debate import debate_candidate
        from ai_agents.council_models import CouncilSession
        switch("trade_debate")
        with patch(SPEND, return_value=(True, "")), \
                patch(EX_RUN, side_effect=RuntimeError("api")), \
                patch(CH_RUN, return_value={"verdict": "back",
                                            "conviction": 0.6, "edge": "e",
                                            "reasons": []}):
            out = debate_candidate(self.bot, self.cand, 0.01)
        s = CouncilSession.objects.get(id=out["council_id"])
        ex = s.voices.get(voice="executioner")
        self.assertEqual(ex.status, "silent")
        self.assertIn("executioner unavailable", ex.why)
        self.assertFalse(s.claims.filter(voice_key="executioner").exists())

    def test_off_held_refused_or_briefless_writes_nothing(self):
        from ai_agents.agents.trade_debate import (debate_candidate,
                                                   remember_refusal)
        from ai_agents.council_models import CouncilSession
        from django.core.cache import cache
        out = debate_candidate(self.bot, self.cand, 0.01)         # OFF
        self.assertIsNone(out["council_id"])
        switch("trade_debate")
        with patch(SPEND, return_value=(False, "daily AI budget spent")):
            self.assertIsNone(debate_candidate(self.bot, self.cand,
                                               0.01)["council_id"])
        with patch(SPEND, return_value=(True, "")), \
                patch("ai_agents.agents.trade_debate.candidate_brief",
                      side_effect=RuntimeError("brief")):
            self.assertIsNone(debate_candidate(self.bot, self.cand,
                                               0.01)["council_id"])
        cache.clear()
        with patch("ai_agents.agents.trade_debate.graded_count",
                   return_value=30):
            remember_refusal(self.bot, self.cand, "vetoed")
            self.assertIsNone(debate_candidate(self.bot, self.cand,
                                               0.01)["council_id"])
        cache.clear()
        self.assertEqual(CouncilSession.objects.count(), 0)

    def test_a_failed_insert_leaves_the_debate_and_the_transaction_whole(self):
        from django.db import connection, transaction

        from ai_agents.council_models import CouncilSession

        def broken(*a, **k):
            with connection.cursor() as cur:
                cur.execute("SELECT * FROM no_such_council_table")

        with transaction.atomic():
            with patch("ai_agents.agents.council.p_and_conviction",
                       side_effect=broken):
                out = debated_session(self.bot, self.cand)
            self.assertTrue(out["ran"])
            self.assertTrue(out["veto"])
            self.assertIsNone(out["council_id"])
            # the surrounding transaction still works: the savepoint took it
            self.assertEqual(CouncilSession.objects.count(), 0)
            switch("council_bots", False)


class TheAfterSendTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("cs_aft", password="x")

    def setUp(self):
        self.bot, self.cand = make_bot_and_cand(self.user)

    def test_the_record_is_linked_whatever_the_council_switches_say(self):
        from ai_agents.agents.council import after_send
        from ai_agents.council_models import CouncilSession
        sid = debated_session(self.bot, self.cand)["council_id"]
        trade = live_row(self.bot, council_id=sid)
        with patch(DELAY) as delay:
            after_send(self.bot, self.cand, 0.01, trade)
        s = CouncilSession.objects.get(id=sid)
        self.assertEqual((s.trade_id, s.linked_by, s.status),
                         (trade.id, "hook", "record"))
        delay.assert_not_called()

    def test_on_it_queues_once_after_commit(self):
        from ai_agents.agents.council import after_send
        from ai_agents.council_models import CouncilSession
        switch("council_bots")
        sid = debated_session(self.bot, self.cand)["council_id"]
        trade = live_row(self.bot, council_id=sid)
        with patch(DELAY) as delay, \
                self.captureOnCommitCallbacks(execute=True):
            after_send(self.bot, self.cand, 0.01, trade)
        # with an expiry: a bot sitting the worker has not picked up in
        # its first 30 minutes is dropped by the broker
        delay.assert_called_once_with((sid,), expires=1800)
        self.assertEqual(CouncilSession.objects.get(id=sid).status, "queued")

    def test_demo_paper_and_a_demo_fill_are_never_argued(self):
        from ai_agents.agents.council import after_send
        from ai_agents.council_models import CouncilSession
        switch("council_bots")
        sid = debated_session(self.bot, self.cand)["council_id"]
        for trade, demo in ((live_row(self.bot, council_id=sid), True),
                            (live_row(self.bot, council_id=sid, paper=True),
                             False),
                            (live_row(self.bot, council_id=sid, env="paper"),
                             False)):
            with patch(DELAY) as delay, \
                    self.captureOnCommitCallbacks(execute=True):
                after_send(self.bot, self.cand, 0.01, trade, demo=demo)
            delay.assert_not_called()
        s = CouncilSession.objects.get(id=sid)
        self.assertIsNone(s.trade_id)
        self.assertEqual(s.status, "record")

    def test_a_rehearsal_fill_closes_the_debates_record_ungraded(self):
        """A bot order filled on a SIM, practice or demo client (stamped
        broker_env "paper" by venue_stamps) is a rehearsal: the debate's
        record is closed with its claims ungraded, nothing is queued, and
        the nightly pass never replays it as "not sent" into the live
        weights."""
        from ai_agents.agents.council import after_send
        from ai_agents.council_grading import REHEARSAL_NOTES, grade_due
        from ai_agents.council_models import CouncilSession
        switch("council_bots")
        sid = debated_session(self.bot, self.cand)["council_id"]
        self.assertTrue(CouncilSession.objects.get(id=sid).claims.exists())
        trade = live_row(self.bot, council_id=sid, env="paper")
        with patch(DELAY) as delay, \
                self.captureOnCommitCallbacks(execute=True):
            after_send(self.bot, self.cand, 0.01, trade)
        delay.assert_not_called()
        s = CouncilSession.objects.get(id=sid)
        self.assertIsNone(s.trade_id)
        self.assertEqual(s.status, "record")
        self.assertIsNotNone(s.graded_at)
        self.assertEqual(s.grade_notes, REHEARSAL_NOTES)
        self.assertEqual(set(s.claims.values_list("grade", flat=True)),
                         {"ungraded"})
        self.assertFalse(s.claims.filter(y__isnull=False).exists())
        CouncilSession.objects.filter(id=sid).update(
            created_at=timezone.now() - timedelta(days=3))
        self.assertEqual(grade_due()["sessions"], 0)
        self.assertEqual(CouncilSession.objects.get(id=sid).truth, "")

    def test_every_rehearsal_client_is_said_to_after_send(self):
        """The hook's demo flag is main's three-world rule, not eToro's
        .demo alone: a Saxo SIM, OANDA practice or Alpaca paper client has
        no .demo and fills in its venue's rehearsal world."""
        from unittest.mock import MagicMock

        from bot_program.asset_engine.base import AssetBot
        for env in ("sim", "SIM", "practice", "paper", "demo", "testnet"):
            with self.subTest(env=env):
                self.assertTrue(AssetBot.rehearsal_client(
                    SimpleNamespace(env=env)))
        self.assertTrue(AssetBot.rehearsal_client(
            SimpleNamespace(env="live", demo=True)))
        for real in (SimpleNamespace(env="live"), SimpleNamespace(),
                     MagicMock(name="a live client")):
            with self.subTest(client=real):
                self.assertFalse(AssetBot.rehearsal_client(real))

    def test_with_the_debate_off_the_council_opens_its_own_and_asks_both(self):
        from ai_agents.agents.council import after_send, run_sitting
        from ai_agents.council_models import CouncilSession
        switch("council_bots")
        switch("platform_master")
        trade = live_row(self.bot)
        with patch(DELAY), self.captureOnCommitCallbacks(execute=True):
            after_send(self.bot, self.cand, 0.01, trade)
        s = CouncilSession.objects.get()
        self.assertEqual((s.trade_id, s.linked_by, s.status),
                         (trade.id, "hook", "queued"))
        self.assertIn("BTCUSD (crypto) BUY", s.brief)
        self.assertFalse(s.voices.exists())
        rec = Recorder()
        with rec.patched():
            run_sitting(s.id)
        self.assertIn("executioner", rec.calls)
        self.assertIn("champion", rec.calls)
        ex = s.voices.get(voice="executioner")
        self.assertEqual((ex.agent, ex.wave, ex.status),
                         ("council_executioner", 1, "spoke"))

    def test_the_days_cap_keeps_the_record_and_says_why(self):
        from ai_agents.agents.council import (COUNCIL_BOT_SITTINGS_PER_DAY,
                                              after_send)
        from ai_agents.council_models import CouncilSession
        switch("council_bots")
        for _ in range(COUNCIL_BOT_SITTINGS_PER_DAY):
            CouncilSession.objects.create(origin="bot", status="done",
                                          symbol="X")
        sid = debated_session(self.bot, self.cand)["council_id"]
        trade = live_row(self.bot, council_id=sid)
        with patch(DELAY) as delay, \
                self.captureOnCommitCallbacks(execute=True):
            after_send(self.bot, self.cand, 0.01, trade)
        delay.assert_not_called()
        s = CouncilSession.objects.get(id=sid)
        self.assertEqual(s.status, "record")
        self.assertEqual(s.trade_id, trade.id)
        self.assertEqual(s.why, "the day's 12 bot sittings are spent")

    def test_a_queue_that_refuses_leaves_the_sitting_silent(self):
        from ai_agents.agents.council import after_send
        from ai_agents.council_models import CouncilSession
        switch("council_bots")
        sid = debated_session(self.bot, self.cand)["council_id"]
        trade = live_row(self.bot, council_id=sid)
        with patch(DELAY, side_effect=ConnectionError("broker down")), \
                self.captureOnCommitCallbacks(execute=True):
            after_send(self.bot, self.cand, 0.01, trade)
        s = CouncilSession.objects.get(id=sid)
        self.assertEqual((s.status, s.why), ("silent",
                                             "the queue did not take it"))

    def test_after_send_never_raises(self):
        from ai_agents.agents.council import after_send
        with patch("ai_agents.council_models.CouncilSession.objects") as qs:
            qs.filter.side_effect = RuntimeError("db down")
            after_send(self.bot, self.cand, 0.01,
                       SimpleNamespace(paper=False, metadata={
                           "debate": {"council_id": 3}}))


class _Sitting(TestCase):
    """A queued bot sitting over a real debate's record."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("cs_wave",
                                                        password="x")

    def setUp(self):
        from ai_agents.council_models import CouncilSession
        switch("platform_master")
        switch("council_bots")
        self.bot, self.cand = make_bot_and_cand(self.user)
        self.sid = debated_session(self.bot, self.cand)["council_id"]
        self.trade = live_row(self.bot, council_id=self.sid)
        CouncilSession.objects.filter(id=self.sid).update(
            trade=self.trade, linked_by="hook", status="queued")

    def sit(self, answers=None, spend=None):
        from ai_agents.agents.council import run_sitting
        from ai_agents.council_models import CouncilSession
        rec = Recorder(answers)
        with rec.patched(spend=spend):
            run_sitting(self.sid)
        return rec, CouncilSession.objects.get(id=self.sid)


class TheWavesTests(_Sitting):

    def test_three_waves_the_emperor_last_and_the_debate_not_billed_twice(self):
        rec, s = self.sit()
        self.assertEqual(s.status, "done")
        self.assertIsNotNone(s.finished_at)
        self.assertNotIn("executioner", rec.calls, "copied from the debate")
        self.assertNotIn("champion", rec.calls)
        self.assertEqual(rec.calls[-1], "emperor")
        waves = {v.voice: v.wave for v in s.voices.all()}
        self.assertEqual(waves, {"executioner": 0, "champion": 0,
                                 "opportunist": 1, "gambler": 1,
                                 "awakened": 1, "theorist": 1, "skeptic": 2,
                                 "fixer": 2, "striker": 2, "emperor": 3})
        self.assertEqual(set(rec.calls[:4]), {"opportunist", "gambler",
                                              "awakened", "theorist"})
        self.assertEqual(set(rec.calls[4:7]), {"skeptic", "fixer",
                                               "striker"})
        # the benchmark rows: plain, weighted (all neutral: equal) and chair
        heard = [0.1, 0.6, 0.6, 0.7, 0.6, 0.6, 0.5, 0.55]
        self.assertAlmostEqual(s.p_mean, sum(heard) / len(heard))
        self.assertAlmostEqual(s.p_weighted, s.p_mean)
        self.assertEqual(s.p_chair, 0.6)
        self.assertEqual(s.voices.get(voice="emperor").weight_seen, 1.0)
        self.assertIn("neutral", s.weights["gambler"]["reason"])

    def test_later_waves_read_the_earlier_ones_and_the_chair_reads_the_record(self):
        rec, s = self.sit()
        self.assertNotIn("THE COUNCIL SO FAR", rec.briefs["opportunist"])
        self.assertIn("LIVE THEORIES", rec.briefs["theorist"])
        self.assertNotIn("LIVE THEORIES", rec.briefs["gambler"])
        for v in ("skeptic", "fixer", "striker", "emperor"):
            self.assertIn("THE COUNCIL SO FAR", rec.briefs[v])
            self.assertIn("The Gambler: press", rec.briefs[v])
            self.assertIn("The Executioner: would veto it", rec.briefs[v])
        self.assertIn("THE RECORD", rec.briefs["emperor"])
        self.assertIn("THE WAR", rec.briefs["emperor"])
        self.assertIn("The Gambler: weight 1.00, neutral", rec.briefs["emperor"])
        self.assertNotIn("THE RECORD", rec.briefs["skeptic"])
        self.assertIn("The Skeptic: the evidence is sound",
                      rec.briefs["emperor"])
        for v, brief in rec.briefs.items():
            self.assertIn("THE COUNCIL'S SITTING", brief, v)
            self.assertIn("FOOTPRINTS", brief, v)
            # no "not built yet": the board is read, or said unread
            self.assertRegex(brief, r"(?i)the big money board", v)
            self.assertNotIn("not built yet", brief, v)
            self.assertIn("season objective: none set by the operator",
                          brief, v)

    def test_a_silent_voice_changes_nothing_else(self):
        rec, s = self.sit({"gambler": ValueError("unparseable")})
        g = s.voices.get(voice="gambler")
        self.assertEqual((g.status, g.why), ("silent", "ValueError"))
        self.assertFalse(s.claims.filter(voice_key="gambler").exists())
        self.assertEqual(s.voices.filter(status="spoke").count(), 7)
        self.assertEqual(s.status, "partial")
        self.assertIn("The Gambler: silent (ValueError)", rec.briefs["emperor"])

    def test_a_budget_refusal_before_the_chair_silences_only_him(self):
        answers = iter([(True, ""), (True, ""), (False, "deep-tier reserve")])
        rec, s = self.sit(spend=lambda **kw: next(answers))
        e = s.voices.get(voice="emperor")
        self.assertEqual((e.status, e.why),
                         ("silent", "AI budget: deep-tier reserve"))
        self.assertNotIn("emperor", rec.calls)
        self.assertEqual(s.voices.filter(status="spoke").count(), 7)
        self.assertIsNone(s.p_chair)
        self.assertEqual(s.status, "partial")

    def test_a_budget_refusal_at_the_first_wave_silences_every_wave(self):
        rec, s = self.sit(spend=lambda **kw: (False, "daily AI budget spent"))
        self.assertEqual(rec.calls, [])
        self.assertEqual(s.status, "silent")
        # the debate's two copied voices make a plain average, but no
        # weight was read: the sitting is never shown as "weighted"
        self.assertAlmostEqual(s.p_mean, (0.1 + 0.6) / 2)
        self.assertIsNone(s.p_weighted)
        self.assertEqual(s.weights, {})
        for v in ("opportunist", "skeptic", "emperor"):
            self.assertEqual(s.voices.get(voice=v).why,
                             "AI budget: daily AI budget spent")

    def test_the_bot_lane_checks_the_deep_tier_with_a_priced_estimate(self):
        rec, s = self.sit()
        tiers = {c.kwargs["tier"] for c in rec.spend.call_args_list}
        self.assertEqual(tiers, {"deep"})
        first = rec.spend.call_args_list[0].kwargs["estimated_usd"]
        self.assertGreater(first, 4 * 0.03, "priced from the text, floored")

    def test_one_wave_runs_its_voices_together_on_council_threads(self):
        barrier = threading.Barrier(4, timeout=5)

        def together(voice):
            def run():
                barrier.wait()
                return default_answers()[voice]
            return run

        rec, s = self.sit({v: together(v) for v in
                           ("opportunist", "gambler", "awakened",
                            "theorist")})
        self.assertFalse(barrier.broken)
        self.assertEqual(s.voices.filter(wave=1, status="spoke").count(), 4)
        self.assertTrue(all(n.startswith("council")
                            for n in rec.threads.values()), rec.threads)

    def test_a_second_run_is_a_noop(self):
        from ai_agents.agents.council import run_sitting
        rec, s = self.sit()
        again = Recorder()
        with again.patched():
            self.assertEqual(run_sitting(self.sid)["status"], "noop")
        self.assertEqual(again.calls, [])

    def test_the_switch_or_the_master_off_silences_the_sitting(self):
        switch("council_bots", False)
        rec, s = self.sit()
        self.assertEqual((s.status, s.why), ("silent", "council_bots is OFF"))
        self.assertEqual(rec.calls, [])

    def test_the_opportunists_alternative_is_a_graded_direction_call(self):
        from ai_agents.models import AgentPrediction
        from tests.test_take_trade_live import _quote
        _quote("EURUSD", "1.1000", asset_class="forex")
        alt = {"verdict": "elsewhere", "p_work": 0.4, "asymmetry": "a",
               "alternative": {"symbol": "EURUSD", "direction": "up",
                               "horizon_hours": 24, "confidence": 0.7,
                               "why": "w"}}
        from tests.test_council_voices import parse
        rec, s = self.sit({"opportunist": parse("opportunist", alt)})
        claim = s.claims.get(kind="direction")
        pred = AgentPrediction.objects.get()
        self.assertEqual(claim.prediction_id, pred.id)
        self.assertEqual((pred.agent, pred.instrument_symbol,
                          pred.predicted_value),
                         ("council_opportunist", "EURUSD", "up"))
        self.assertIn(f"council #{s.id}", pred.evaluation_notes)
        self.assertEqual(claim.grade, "pending")

    def test_a_call_the_logger_refuses_is_stored_refused(self):
        from tests.test_council_voices import parse
        from tests.test_take_trade_live import _quote
        _quote("EURUSD", "1.1000", asset_class="forex")
        alt = {"verdict": "elsewhere", "alternative": {
            "symbol": "EURUSD", "direction": "up", "horizon_hours": 24}}
        with patch("ai_agents.calibration.log_direction_prediction",
                   return_value=None):
            rec, s = self.sit({"opportunist": parse("opportunist", alt)})
        claim = s.claims.get(kind="direction")
        self.assertEqual(claim.grade, "refused")
        self.assertIn("not registered", claim.grade_notes)

    def test_the_theorist_posts_to_the_hypothesis_market_under_his_name(self):
        from brain.knowledge_models import Hypothesis
        from tests.test_council_voices import parse
        theory = {"verdict": "none", "p_work": 0.5, "new_theory": {
            "claim_text": "the tape keeps trending", "kind": "regime_holds",
            "regime": "trending", "horizon_hours": 48, "confidence": 0.65}}
        rec, s = self.sit({"theorist": parse("theorist", theory)})
        hyp = Hypothesis.objects.get()
        self.assertEqual(hyp.source_agent, "council_theorist")
        self.assertIsNone(hyp.agent_prediction_id)
        self.assertEqual(hyp.claim_payload, {"council_session": s.id})
        self.assertEqual(hyp.resolution_criteria,
                         {"kind": "regime_holds", "regime": "trending"})
        claim = s.claims.get(kind="theory")
        self.assertEqual((claim.hypothesis_id, claim.grade),
                         (hyp.id, "pending"))
        self.assertIn(f"posted theory #{hyp.id}", rec.briefs["emperor"])

    def test_a_rule_theory_is_graded_on_the_live_book_only(self):
        """Main's paper-honesty rule (brain.hypotheses.VENUE_REQUIRED_FROM):
        a rule's theory names its venue, or it would be graded on the
        pooled record where one paper booking decides it. The council
        argues real money: the Theorist's is the live book, whatever the
        model wrote, and the door refuses one under his name with none."""
        from brain.hypotheses import UnmeasurableClaim, post_hypothesis
        from brain.knowledge_models import Hypothesis
        from tests.test_council_voices import parse
        theory = {"verdict": "none", "p_work": 0.5, "new_theory": {
            "claim_text": "the golden cross keeps paying", "kind": "rule_avg_r",
            "rule_name": "golden_cross", "comparator": ">=", "threshold": 0.3,
            "window_days": 30, "min_n": 3, "venue": "paper",
            "horizon_hours": 168, "confidence": 0.6}}
        rec, s = self.sit({"theorist": parse("theorist", theory)})
        hyp = Hypothesis.objects.get()
        self.assertEqual(hyp.source_agent, "council_theorist")
        self.assertEqual(hyp.resolution_criteria["venue"], "live")
        self.assertEqual(hyp.resolution_criteria["rule_name"], "golden_cross")
        self.assertEqual(s.claims.get(kind="theory").hypothesis_id, hyp.id)
        with self.assertRaisesRegex(UnmeasurableClaim, "must name its venue"):
            post_hypothesis(claim_text="pooled",
                            source_agent="council_theorist",
                            resolution_criteria={
                                "kind": "rule_avg_r",
                                "rule_name": "golden_cross",
                                "comparator": ">=", "threshold": 0.3})
        self.assertEqual(Hypothesis.objects.count(), 1)

    def test_the_live_theories_say_the_book_a_rule_theory_is_graded_on(self):
        """A paper-venue claim says nothing about a live trade, and one
        with no venue is graded on the pooled record: the Theorist reads
        which."""
        from ai_agents.agents.council import live_theories
        from ai_agents.council_models import CouncilSession
        from brain.hypotheses import post_hypothesis
        s = CouncilSession.objects.get(id=self.sid)
        crit = {"kind": "rule_avg_r", "rule_name": s.rule_name,
                "comparator": ">=", "threshold": 0.3}
        paper = post_hypothesis(claim_text="on paper", source_agent="critic",
                                resolution_criteria=dict(crit,
                                                         venue="paper"))
        pooled = post_hypothesis(claim_text="pooled",
                                 source_agent="position_reviewer",
                                 resolution_criteria=crit)
        text, ids = live_theories(s)
        self.assertEqual(ids, {paper.id, pooled.id})
        self.assertIn(f"#{paper.id} [rule_avg_r/paper] \"on paper\"", text)
        self.assertIn(f"#{pooled.id} [rule_avg_r/pooled: live, demo and "
                      f"paper] \"pooled\"", text)

    def test_an_unmeasurable_theory_is_refused_at_the_door(self):
        from brain.knowledge_models import Hypothesis
        from tests.test_council_voices import parse
        theory = {"verdict": "none", "new_theory": {
            "claim_text": "c", "kind": "regime_holds", "regime": "sideways",
            "horizon_hours": 48}}
        rec, s = self.sit({"theorist": parse("theorist", theory)})
        self.assertFalse(Hypothesis.objects.exists())
        claim = s.claims.get(kind="theory")
        self.assertEqual(claim.grade, "refused")
        self.assertIn("regime_holds needs a classifiable regime",
                      claim.grade_notes)

    def test_the_days_theories_are_capped(self):
        from ai_agents.agents.council import COUNCIL_THEORIES_PER_DAY
        from brain.hypotheses import post_hypothesis
        from tests.test_council_voices import parse
        for _ in range(COUNCIL_THEORIES_PER_DAY):
            post_hypothesis(claim_text="t", source_agent="council_theorist",
                            resolution_criteria={"kind": "regime_holds",
                                                 "regime": "risk_on"})
        theory = {"verdict": "none", "new_theory": {
            "claim_text": "c", "kind": "regime_holds", "regime": "trending",
            "horizon_hours": 48}}
        rec, s = self.sit({"theorist": parse("theorist", theory)})
        claim = s.claims.get(kind="theory")
        self.assertEqual(claim.grade, "refused")
        self.assertEqual(claim.grade_notes, "the day's 3 theories are posted")

    def test_a_theory_outside_6_to_720_hours_is_refused_at_the_door(self):
        from brain.knowledge_models import Hypothesis
        from tests.test_council_voices import parse
        theory = {"verdict": "none", "new_theory": {
            "claim_text": "c", "kind": "regime_holds", "regime": "trending",
            "horizon_hours": 3}}
        rec, s = self.sit({"theorist": parse("theorist", theory)})
        self.assertFalse(Hypothesis.objects.exists())
        claim = s.claims.get(kind="theory")
        self.assertEqual((claim.grade, claim.grade_notes),
                         ("refused", "a horizon outside 6 to 720 hours"))

    def test_an_alternative_with_no_price_to_measure_from_is_refused(self):
        from ai_agents.models import AgentPrediction
        from instruments.models import Instrument
        from tests.test_council_voices import parse
        Instrument.objects.get_or_create(
            symbol="NOQT", defaults={"name": "NOQT", "asset_class": "forex"})
        alt = {"verdict": "elsewhere", "p_work": 0.4, "asymmetry": "a",
               "alternative": {"symbol": "NOQT", "direction": "up",
                               "horizon_hours": 24, "confidence": 0.6}}
        rec, s = self.sit({"opportunist": parse("opportunist", alt,
                                                instruments={"NOQT"})})
        claim = s.claims.get(kind="direction")
        self.assertEqual((claim.grade, claim.grade_notes),
                         ("refused", "no price to measure from"))
        self.assertFalse(AgentPrediction.objects.exists())

    def test_a_bot_sitting_queued_past_30_minutes_is_silent_and_unbilled(self):
        from ai_agents.council_models import CouncilSession
        CouncilSession.objects.filter(id=self.sid).update(
            created_at=timezone.now() - timedelta(minutes=31))
        rec, s = self.sit()
        self.assertEqual((s.status, s.why),
                         ("silent", "too late to sit: queued 31 minutes"))
        self.assertEqual(rec.calls, [])
        rec.spend.assert_not_called()

    def test_a_bot_sitting_inside_its_30_minutes_sits(self):
        from ai_agents.council_models import CouncilSession
        CouncilSession.objects.filter(id=self.sid).update(
            created_at=timezone.now() - timedelta(minutes=20))
        rec, s = self.sit()
        self.assertEqual(s.status, "done")
        self.assertIn("emperor", rec.calls)


class TheWarAndFootprintsTests(_Sitting):
    """THE WAR and the FOOTPRINTS carry percent, R and price levels, never
    an amount of money (the alarm tripwire's currency and money-word
    clauses, tests/test_alarm_bot.MONEY, minus its decimal and percent
    clauses: a level and a share of the book are exactly what the war
    and the footprints are made of)."""

    def _currency(self):
        from tests.test_alarm_bot import MONEY
        pattern = (MONEY.pattern
                   .replace(r"|\d[\d,]*\.\d+\b", "")
                   .replace(r"|[-+−]?\d+(?:\.\d+)?\s?%", ""))
        self.assertNotEqual(pattern, MONEY.pattern)
        return re.compile(pattern, MONEY.flags)

    def test_the_war_says_shares_of_the_book_never_money(self):
        from ai_agents.agents.council import war_text
        from ai_agents.council_models import CouncilSession
        s = CouncilSession.objects.get(id=self.sid)
        daily = {"ok": False, "limit_pct": 8.0, "book_value": 10000.0,
                 "realized": -1234.56, "mode": "elite",
                 "reason": "daily loss limit hit: -1,234.56 realized"}
        opened = {"ok": True, "limit_pct": 15.0, "book_value": 10000.0,
                  "open_risk": 900.5, "rows": 3,
                  "reason": "900.50 at the stops"}
        with patch("portfolio.risk_gate.daily_loss_state",
                   return_value=daily), \
                patch("portfolio.risk_gate.open_risk_state",
                      return_value=opened):
            war = war_text(s)
        self.assertIn("daily stop: -12.35% realized in the window, limit 8%; "
                      "mode elite", war)
        self.assertIn("open risk: 9.0% of the book at the stops of 3 "
                      "positions, limit 15%", war)
        self.assertIn("per-trade ceiling is 7%", war)
        self.assertIn("elite entries: 0 of 2 used in the window", war)
        # the cap, and plainly that the account's pledge is not read here
        self.assertRegex(war, r"pledge cap: \d+% of the account; the "
                              r"account's current pledge is not read here")
        self.assertIn("season objective: none set by the operator", war)
        for money in ("1234", "1,234", "900.5", "10000", "10,000"):
            self.assertNotIn(money, war)
        self.assertIsNone(self._currency().search(war), war)

    def test_the_live_book_leaves_out_the_demo_world(self):
        """venue "live" alone is paper=False, which eToro's DEMO world is
        too (broker_env "paper"): THE WAR's live book is world "live"."""
        from ai_agents.agents.council import war_text
        from ai_agents.council_models import CouncilSession
        s = CouncilSession.objects.get(id=self.sid)
        live_row(self.bot, env="paper", status="CLOSED", realized_r=-2.0,
                 closed_at=timezone.now() - timedelta(days=1))
        self.assertIn("  the live book, 30 days: none closed", war_text(s))
        live_row(self.bot, env="live", status="CLOSED", realized_r=1.0,
                 closed_at=timezone.now() - timedelta(days=1))
        self.assertIn("  the live book, 30 days: 1 closed, average R +1.00, "
                      "win rate 100%", war_text(s))

    def test_an_unmeasured_posture_is_never_called_calm(self):
        """Main's measured posture (brain.strategist.measured_posture): with
        crisis mode OFF no stress reading is taken and the posture sizes
        nothing; THE WAR says so and never "calm"."""
        from ai_agents.agents.council import war_text
        from ai_agents.council_models import CouncilSession
        s = CouncilSession.objects.get(id=self.sid)
        switch("crisis_mode", False)
        war = war_text(s)
        self.assertIn("  posture: crisis mode OFF: unmeasured (no stress "
                      "reading yet; crisis mode is OFF: no stress reading is "
                      "taken and this posture sizes nothing until it is on)",
                      war)
        self.assertNotIn("posture: calm", war)
        self.assertNotIn("this entry:", war)
        # ON, the measured word and this entry's own posture are said
        switch("crisis_mode", True)
        war = war_text(s)
        self.assertRegex(war, r"  posture: unmeasured \(.*crisis mode is ON: "
                              r"this posture sizes real-money orders\); this "
                              r"entry: [a-z ]+, size x[\d.]+")
        self.assertNotIn("posture: calm", war)

    def test_the_footprints_carry_ids_and_no_money(self):
        from ai_agents.agents.council import footprints
        from ai_agents.council_models import CouncilSession
        s = CouncilSession.objects.get(id=self.sid)
        pmap = {"ok": True, "label": "crowded long", "score": 0.62,
                "components": {"retail": {"score": 0.7,
                                          "words": "retail is long"}},
                "stops": {"below": {"price": 59000.0, "kind": "equal lows",
                                    "side": "below", "pool": True,
                                    "touches": 3, "atr_away": 1.2},
                          "above": None},
                "path": [{"leg": "hunt", "why": "the longs' stops",
                          "price": 59000.0, "kind": "equal lows",
                          "side": "below", "pool": True, "touches": 3,
                          "atr_away": 1.2},
                         {"leg": "draw", "why": "no bias", "side": "above"}],
                "odds": {"verdict": "unjudged"},
                "po3": {"words": "the day is accumulating"},
                "side": {"words": "You join the crowd"}}
        with patch("bot_program.positioning.positioning_map",
                   return_value={"ok": True}), \
                patch("bot_program.positioning.compact", return_value=pmap), \
                patch.dict(sys.modules, {"bigmoney.read": None}):
            text, ids = footprints(s)
        self.assertIn("F1. the crowd: crowded long (score +0.62)", text)
        self.assertIn("crowd component retail: retail is long", text)
        self.assertIn("the hunt: below to equal lows 59000", text)
        self.assertIn("smart money ict_bias: long", text)
        self.assertIn("THE BIG MONEY BOARD: unread (the board is not on this "
                      "server); never speak for it.", text)
        self.assertNotIn("not built yet", text)
        self.assertEqual(ids, {f"F{i}" for i in range(1, len(ids) + 1)})
        self.assertGreaterEqual(len(ids), 6)
        self.assertIsNone(self._currency().search(text), text)

    def _board(self, out):
        """A Big Money board answering `out` (bigmoney.read.ticket_words's
        contract on main)."""
        pkg = types.ModuleType("bigmoney")
        pkg.__path__ = []
        read = types.ModuleType("bigmoney.read")
        read.calls = []

        def ticket_words(symbol, side):
            read.calls.append((symbol, side))
            if isinstance(out, Exception):
                raise out
            return out
        read.ticket_words = ticket_words
        return read, patch.dict(sys.modules, {"bigmoney": pkg,
                                              "bigmoney.read": read})

    def test_the_big_money_board_is_one_footprint_when_it_read(self):
        from ai_agents.agents.council import footprints
        from ai_agents.council_models import CouncilSession
        s = CouncilSession.objects.get(id=self.sid)
        read, board = self._board({
            "ok": True, "as_of": "2026-10-16",
            "words": "BTCUSD: leans up this week (flows). Your buy is with "
                     "it. Read Fri 07:10 UTC."})
        with board, patch("bot_program.positioning.positioning_map",
                          side_effect=RuntimeError("bars")):
            text, ids = footprints(s)
        self.assertEqual(read.calls, [("BTCUSD", "BUY")])
        line = next(ln for ln in text.splitlines() if "Big Money" in ln)
        self.assertRegex(line, r"^  F\d+\. the Big Money board: BTCUSD: "
                               r"leans up this week \(flows\)\. Your buy is "
                               r"with it\.")
        fid = line.split(".")[0].strip()
        self.assertIn(fid, ids)
        self.assertNotIn("THE BIG MONEY BOARD: unread", text)
        self.assertIsNone(self._currency().search(text), text)

    def test_an_unread_board_is_said_and_offers_no_id(self):
        from ai_agents.agents.council import footprints
        from ai_agents.council_models import CouncilSession
        s = CouncilSession.objects.get(id=self.sid)
        s.facts = {}
        for out, why in (({"ok": False, "words": "The board is off: nothing "
                                                 "read."},
                          "The board is off: nothing read"),
                         ({"ok": False, "words": ""}, "nothing on this symbol"),
                         (RuntimeError("db"),
                          "the board could not be read (RuntimeError)")):
            with self.subTest(why=why):
                _read, board = self._board(out)
                with board, patch("bot_program.positioning.positioning_map",
                                  side_effect=RuntimeError("bars")):
                    text, ids = footprints(s)
                self.assertEqual(ids, set())
                self.assertIn(f"THE BIG MONEY BOARD: unread ({why}); never "
                              f"speak for it.", text)

    def test_unread_footprints_are_said_and_offer_no_id(self):
        from ai_agents.agents.council import footprints
        from ai_agents.council_models import CouncilSession
        s = CouncilSession.objects.get(id=self.sid)
        s.facts = {}
        with patch("bot_program.positioning.positioning_map",
                   side_effect=RuntimeError("bars")):
            text, ids = footprints(s)
        self.assertEqual(ids, set())
        self.assertIn("FOOTPRINTS: none could be read", text)


class TheTicketLaneTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("cs_tk", password="x")

    def test_the_ticket_lane_checks_the_balanced_tier(self):
        from ai_agents.agents.council import run_sitting
        from ai_agents.council_models import CouncilSession
        switch("platform_master")
        switch("council_ticket")
        s = CouncilSession.objects.create(
            origin="ticket", status="queued", user=self.user,
            symbol="EURUSD", asset_class="forex", side="BUY", entry=1.10,
            stop=1.09, target=1.13, qty=1000)
        rec = Recorder()
        with patch("ai_agents.agents.council.ticket_brief",
                   return_value="THE TRADE\n  EURUSD (forex) BUY — a HAND "
                                "trade"), rec.patched():
            run_sitting(s.id)
        s.refresh_from_db()
        self.assertEqual({c.kwargs["tier"] for c in rec.spend.call_args_list},
                         {"balanced"})
        self.assertIn("a HAND trade", rec.briefs["emperor"])
        self.assertIn("the operator's hand ticket, not yet taken",
                      rec.briefs["emperor"])
        self.assertEqual(s.status, "done")

    def test_a_ticket_queued_past_ten_minutes_is_silent_and_unbilled(self):
        """The ticket stopped polling after five minutes and its owner may
        ask again after ten: a sitting the worker reaches later bills
        nothing and says why."""
        from ai_agents.agents.council import run_sitting
        from ai_agents.council_models import CouncilSession
        switch("platform_master")
        switch("council_ticket")
        s = CouncilSession.objects.create(
            origin="ticket", status="queued", user=self.user,
            symbol="EURUSD", asset_class="forex", side="BUY", entry=1.10,
            stop=1.09, target=1.13, qty=1000)
        CouncilSession.objects.filter(id=s.id).update(
            created_at=timezone.now() - timedelta(minutes=15))
        rec = Recorder()
        with patch("ai_agents.agents.council.ticket_brief") as brief, \
                rec.patched():
            out = run_sitting(s.id)
        s.refresh_from_db()
        self.assertEqual(out["status"], "silent")
        self.assertEqual((s.status, s.why),
                         ("silent", "too late to sit: queued 15 minutes"))
        self.assertEqual(rec.calls, [])
        rec.spend.assert_not_called()
        brief.assert_not_called()
        self.assertFalse(s.voices.exists())


class TheLateVoiceTests(TransactionTestCase):
    """A voice that answers after its wave's deadline is stored and graded,
    and no later wave hears it. A TransactionTestCase: the late answer is
    written by its own thread, on its own connection."""

    def test_a_late_voice_is_kept_and_unheard(self):
        from ai_agents.agents import council as C
        from ai_agents.council_models import CouncilSession, CouncilVoice
        user = get_user_model().objects.create_user("cs_late", password="x")
        switch("platform_master")
        switch("council_bots")
        s = CouncilSession.objects.create(
            origin="bot", status="queued", user=user, symbol="BTCUSD",
            asset_class="crypto", side="BUY", entry=100.0, stop=98.0,
            target=104.0, qty=1, brief="THE TRADE")
        landed = threading.Event()
        real_land = C._land

        def land(meta, voice, outcome, *, late):
            real_land(meta, voice, outcome, late=late)
            if late:
                landed.set()

        def slow():
            time.sleep(1.5)
            return default_answers()["gambler"]

        rec = Recorder({"gambler": slow})
        with patch("ai_agents.agents.council.COUNCIL_WAVE_TIMEOUT_S", 0.3), \
                patch("ai_agents.agents.council._land", side_effect=land), \
                patch("ai_agents.agents.council.council_extras",
                      return_value={"war": "THE WAR", "footprints":
                                    "FOOTPRINTS: none", "footprint_ids": set()}), \
                rec.patched():
            C.run_sitting(s.id)
            self.assertTrue(landed.wait(10), "the late answer never landed")
        g = CouncilVoice.objects.get(session=s, voice="gambler")
        self.assertEqual((g.status, g.why),
                         ("late", "late: not heard by the chair"))
        self.assertTrue(s.claims.filter(voice_key="gambler",
                                        kind="work").exists())
        self.assertIn("The Gambler: silent (timeout)", rec.briefs["skeptic"])
        self.assertNotIn("The Gambler: press", rec.briefs["emperor"])
        s.refresh_from_db()
        self.assertEqual(s.status, "partial")
