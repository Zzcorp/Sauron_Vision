"""The brain reads live, demo and paper apart (2026-10-08).

The morning brief of 2026-10-08 said "one rsi_bull_divergence forex trade
lost -8.12R. That is a failed stop or a sizing error". It was a PAPER row, a
simulator stop nobody managed for weeks. The Mind's 14-day track record
called bot_performance_summary with the pooled default (VENUE_ALL) and
dropped the venue label, and VENUE_LIVE also counts eToro demo, so a
simulator booking read as a live failure, and the operator's real
manual_take commodity trades (slightly positive) read -0.42R pooled with
demo and paper.

Pinned here:
  - bot_grading: the three money worlds as query filters (live = real
    money, demo = eToro's virtual account, paper = the simulator), agreeing
    with position_summary.world_of on every stamp; performance_by_venue
    returns each world's rows labelled; VENUE_LIVE, read by the order
    paths, is unchanged (no change to any real-money order path);
  - the Mind's snapshot, prompt and stored report carry the venue on every
    row, the legend says what each venue is, and paper rows can never push
    live rows out; open positions and decay alerts carry their venue;
  - the Mind's predictions and every rule_avg_r claim carry their venue, a
    legacy claim with none still grades on the pooled record; calibration
    reads "rule@venue";
  - the critic, the strategist, the demoter, the generator, the mutator,
    the decay detector, the decay investigator and the position review all
    name the venue they read.

Run with:  python manage.py test tests.test_brain_reads_venues
"""
import json
from datetime import timedelta
from decimal import Decimal as D
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

LIVE = {"broker": "etoro", "broker_env": "live"}
DEMO = {"broker": "etoro", "broker_env": "paper"}


def _cfg(user, name="venues", asset_class="forex"):
    from bot_program.asset_models import AssetBotConfig
    return AssetBotConfig.objects.create(
        user=user, asset_class=asset_class, name=name, enabled=True,
        mode="paper", capital=D("10000"), symbols=[])


def _closed(cfg, *, rule, r, paper, metadata=None, asset_class="forex",
            symbol="GBPUSD", days_ago=1, outcome=None):
    from bot_program.asset_models import AssetBotTrade
    t = AssetBotTrade.objects.create(
        config=cfg, asset_class=asset_class, symbol=symbol, side="BUY",
        qty=D("1000"), entry_price=D("1.34991"), stop_loss=D("1.34690"),
        exit_price=D("1.33"), pnl=D("-1"), paper=paper, status="CLOSED",
        rule_name=rule, realized_r=r,
        outcome=outcome or ("hit_target" if r > 0 else "stopped_out"),
        metadata=dict(metadata or {}))
    AssetBotTrade.objects.filter(pk=t.pk).update(
        closed_at=timezone.now() - timedelta(days=days_ago))
    t.refresh_from_db()
    return t


def _the_book(test):
    """The brief's book: a paper row (-8.12R), the operator's manual_take
    commodity trades: one real (+0.3R), one demo (-0.5R), one paper
    (-1.06R)."""
    test.user = User.objects.create_user(f"venue_{id(test)}")
    test.cfg = _cfg(test.user)
    test.paper68 = _closed(test.cfg, rule="rsi_bull_divergence", r=-8.12,
                           paper=True)
    test.live = _closed(test.cfg, rule="manual_take", r=0.3, paper=False,
                        metadata=LIVE, asset_class="commodity",
                        symbol="XAUUSD")
    test.demo = _closed(test.cfg, rule="manual_take", r=-0.5, paper=False,
                        metadata=DEMO, asset_class="commodity",
                        symbol="XAUUSD")
    test.paper_mt = _closed(test.cfg, rule="manual_take", r=-1.06,
                            paper=True, asset_class="commodity",
                            symbol="XAUUSD")


def _rows_by(rows):
    return {(r["rule_name"], r["asset_class"], r["venue"]): r for r in rows}


class TheWorldsAsQueriesTests(TestCase):
    def test_the_filter_and_world_of_agree_on_every_stamp(self):
        from bot_program.asset_models import AssetBotTrade
        from bot_program.bot_grading import WORLDS, world_performance_summary
        from dashboard.position_summary import world_of
        user = User.objects.create_user("venue_agree")
        cfg = _cfg(user)
        rows = [
            _closed(cfg, rule="r_live_bare", r=1.0, paper=False),
            _closed(cfg, rule="r_live", r=1.0, paper=False, metadata=LIVE),
            _closed(cfg, rule="r_demo", r=1.0, paper=False, metadata=DEMO),
            _closed(cfg, rule="r_paper", r=1.0, paper=True),
            # a non-paper row carried by the simulator: world_of calls it
            # paper, and so must the query
            _closed(cfg, rule="r_carrier_paper", r=1.0, paper=False,
                    metadata={"broker": "paper"}),
        ]
        for world in WORLDS:
            with self.subTest(world=world):
                got = {r["rule_name"] for r in
                       world_performance_summary(world, days=30)}
                want = {t.rule_name for t in rows
                        if world_of(AssetBotTrade.objects.get(pk=t.pk))
                        == world}
                self.assertEqual(got, want)

    def test_performance_by_venue_labels_every_row_and_pools_nothing(self):
        from bot_program.bot_grading import performance_by_venue
        _the_book(self)
        out = performance_by_venue(days=14, min_n=1)
        self.assertEqual(list(out), ["live", "demo", "paper"])
        for venue, rows in out.items():
            for r in rows:
                self.assertEqual(r["venue"], venue)
        live = _rows_by(out["live"])
        self.assertEqual(live[("manual_take", "commodity", "live")]["n"], 1)
        self.assertEqual(live[("manual_take", "commodity", "live")]["avg_r"],
                         0.3)
        self.assertNotIn("rsi_bull_divergence",
                         {r["rule_name"] for r in out["live"]})
        paper = _rows_by(out["paper"])
        self.assertEqual(
            paper[("rsi_bull_divergence", "forex", "paper")]["avg_r"], -8.12)

    def test_venue_live_read_by_the_order_paths_is_unchanged(self):
        """No change to any real-money order path: VENUE_LIVE still reads
        every non-paper row, demo included, exactly as before."""
        from bot_program.bot_grading import VENUE_LIVE, bot_performance_summary
        _the_book(self)
        rows = _rows_by(bot_performance_summary(days=14, venue=VENUE_LIVE))
        self.assertEqual(rows[("manual_take", "commodity", "live")]["n"], 2)

    def test_an_unknown_world_raises(self):
        from bot_program.bot_grading import world_performance_summary
        with self.assertRaises(ValueError):
            world_performance_summary("real")


class TheMindsSnapshotTests(TestCase):
    def setUp(self):
        _the_book(self)

    def test_every_row_names_its_venue_and_none_is_pooled(self):
        from brain.synthesizer import _build_world_snapshot
        snap = _build_world_snapshot()
        rows = _rows_by(snap["rule_track_records"])
        self.assertEqual(rows[("rsi_bull_divergence", "forex", "paper")]["n"],
                         1)
        self.assertEqual(rows[("manual_take", "commodity", "live")]["avg_r"],
                         0.3)
        self.assertEqual(rows[("manual_take", "commodity", "demo")]["avg_r"],
                         -0.5)
        self.assertEqual(rows[("manual_take", "commodity", "paper")]["avg_r"],
                         -1.06)
        self.assertFalse([r for r in snap["rule_track_records"]
                          if r["venue"] not in ("live", "demo", "paper")])
        # live first: the rows the money rests on lead the table
        self.assertEqual(snap["rule_track_records"][0]["venue"], "live")

    def test_the_legend_says_what_each_venue_is(self):
        from brain.synthesizer import _build_world_snapshot
        legend = _build_world_snapshot()["track_record_venues"]
        self.assertIn("real money", legend["live"])
        self.assertIn("eToro", legend["demo"])
        self.assertIn("not money", legend["demo"])
        self.assertIn("simulator", legend["paper"])
        self.assertIn("far beyond -1R", legend["paper"])

    def test_paper_rows_never_push_live_rows_out(self):
        from brain.synthesizer import (TRACK_RECORD_ROWS_PER_VENUE,
                                       _build_world_snapshot)
        for i in range(TRACK_RECORD_ROWS_PER_VENUE + 15):
            _closed(self.cfg, rule=f"paper_rule_{i:02d}", r=-1.0, paper=True)
            _closed(self.cfg, rule=f"paper_rule_{i:02d}", r=-1.0, paper=True)
        snap = _build_world_snapshot()
        by_venue = {}
        for r in snap["rule_track_records"]:
            by_venue.setdefault(r["venue"], []).append(r)
        self.assertEqual(len(by_venue["paper"]), TRACK_RECORD_ROWS_PER_VENUE)
        self.assertEqual(len(by_venue["live"]), 1)
        self.assertEqual(snap["rule_track_records_shown"]["paper"],
                         TRACK_RECORD_ROWS_PER_VENUE)
        self.assertGreater(snap["rule_track_records_total"]["paper"],
                           TRACK_RECORD_ROWS_PER_VENUE)

    def test_a_venue_with_no_rows_says_why(self):
        from bot_program.asset_models import AssetBotTrade
        from brain.synthesizer import _build_world_snapshot
        AssetBotTrade.objects.filter(pk=self.demo.pk).delete()
        snap = _build_world_snapshot()
        self.assertIn("demo", snap["rule_track_records_venue_notes"])
        self.assertIn("NO REALIZED R YET",
                      snap["rule_track_records_venue_notes"]["demo"])
        self.assertNotIn("rule_track_records_note", snap)

    def test_open_positions_and_decay_alerts_carry_their_venue(self):
        from bot_program.asset_models import AssetBotTrade
        from bot_program.track_record_models import RuleTrackRecordAlert
        from brain.synthesizer import _build_world_snapshot
        AssetBotTrade.objects.create(
            config=self.cfg, asset_class="commodity", symbol="XAGUSD",
            side="BUY", qty=D("1"), entry_price=D("30"), status="OPEN",
            paper=False, rule_name="manual_take", metadata=DEMO)
        RuleTrackRecordAlert.objects.create(
            user=self.user, rule_name="rsi_bull_divergence",
            asset_class="forex", venue="paper", triggers=["gone_negative"])
        snap = _build_world_snapshot()
        (pos,) = [p for p in snap["open_positions"] if p["book"] == "bot"]
        self.assertEqual(pos["venue"], "demo")
        self.assertNotIn("paper", pos)
        (alert,) = snap["unresolved_decay_alerts"]
        self.assertEqual(alert["venue"], "paper")


def _stub_provider(parsed):
    from unittest.mock import MagicMock
    raw = json.dumps(parsed)

    def patched_init(self, *a, **kw):
        self.agent_name = "sauron_mind"
        self.provider_name = "stub"
        self.model = "claude-stub"
        self.provider = MagicMock()
        self.provider.complete = MagicMock(
            return_value=(raw, {"input_tokens": 1, "output_tokens": 1,
                                "cost_usd": 0.0}))

    return patch("brain.synthesizer.SauronMindAgent.__init__", patched_init)


class TheMindsPromptAndReportTests(TestCase):
    def setUp(self):
        _the_book(self)

    def test_the_system_prompt_states_the_venue_rule(self):
        from brain.synthesizer import SauronMindAgent
        prompt = SauronMindAgent.__new__(SauronMindAgent).get_system_prompt()
        self.assertIn("Every R you cite names its venue", prompt)
        self.assertIn("A paper or demo result is never a live failure", prompt)
        self.assertIn("pause_recommended only on live evidence", prompt)

    def test_the_context_carries_the_rows_and_the_legend(self):
        from brain.synthesizer import SauronMindAgent, _build_world_snapshot
        agent = SauronMindAgent.__new__(SauronMindAgent)
        context = agent.build_context(snapshot=_build_world_snapshot())
        self.assertIn('"track_record_venues"', context)
        self.assertIn('"venue": "paper"', context)
        self.assertIn('"venue": "live"', context)

    def test_the_stored_report_carries_the_venue_split(self):
        from ai_agents.models import AgentPrediction
        from brain.knowledge_models import Hypothesis
        from brain.models import BrainReport
        from brain.synthesizer import synthesize_now
        parsed = {
            "regime_label": "trending", "regime_confidence": 0.7,
            "portfolio_health_score": 0.6,
            "top_concerns": [
                {"kind": "paper_stop", "severity": 0.4,
                 "ref": "rsi_bull_divergence", "venue": "paper",
                 "text": "paper -8.12R: an unmanaged simulator stop"},
                {"kind": "x", "severity": 0.2, "ref": "y",
                 "venue": "bogus", "text": "z"}],
            "rule_status_overlay": {},
            "narrative_md": "Paper only.",
            "predictions": [{"prediction_type": "rule_recovers",
                             "predicted_value": "manual_take",
                             "venue": "live", "confidence": 0.6,
                             "horizon_hours": 48, "rationale": "r"}],
        }
        with _stub_provider(parsed), \
                patch("brain.hypotheses._refuse_if_the_rule_cannot_trade"):
            result = synthesize_now()
        self.assertTrue(result["ok"])
        report = BrainReport.objects.get(pk=result["report_id"])
        rows = _rows_by(report.track_records["rows"])
        self.assertIn(("rsi_bull_divergence", "forex", "paper"), rows)
        self.assertIn("simulator", report.track_records["venues"]["paper"])
        self.assertEqual(report.track_records["window_days"], 14)
        self.assertEqual(report.top_concerns[0]["venue"], "paper")
        self.assertEqual(report.top_concerns[1]["venue"], "")
        pred = AgentPrediction.objects.get(agent="sauron_mind")
        self.assertEqual(pred.predicted_value, "manual_take@live")
        hyp = Hypothesis.objects.get(agent_prediction=pred)
        self.assertEqual(hyp.resolution_criteria["venue"], "live")
        self.assertEqual(hyp.resolution_criteria["rule_name"], "manual_take")

    def test_the_critic_reads_the_same_labelled_snapshot(self):
        from brain.critic import CriticAgent
        from brain.knowledge_models import Hypothesis
        from brain.synthesizer import _build_world_snapshot
        hyp = Hypothesis.objects.create(
            claim_text="c", source_agent="sauron_mind", confidence=0.5,
            resolution_criteria={"kind": "rule_avg_r", "rule_name": "x"},
            resolution_deadline=timezone.now() + timedelta(days=2))
        agent = CriticAgent.__new__(CriticAgent)
        context = agent.build_context(hypothesis=hyp,
                                      snapshot=_build_world_snapshot())
        self.assertIn('"venue": "paper"', context)
        self.assertIn("never a live failure", agent.get_system_prompt())


class ClaimsCarryTheirVenueTests(TestCase):
    def setUp(self):
        _the_book(self)

    def _hyp(self, criteria):
        from brain.knowledge_models import Hypothesis
        hyp = Hypothesis.objects.create(
            claim_text="c", source_agent="sauron_mind", confidence=0.5,
            resolution_criteria=criteria,
            resolution_deadline=timezone.now() + timedelta(days=2))
        Hypothesis.objects.filter(pk=hyp.pk).update(
            created_at=timezone.now() - timedelta(days=3))
        hyp.refresh_from_db()
        return hyp

    def test_a_legacy_claim_with_no_venue_still_grades_pooled(self):
        from brain.hypotheses import _resolve_rule_avg_r_threshold
        hyp = self._hyp({"kind": "rule_avg_r", "rule_name": "manual_take",
                         "comparator": ">=", "threshold": 0.0, "min_n": 1})
        ok, note = _resolve_rule_avg_r_threshold(hyp)
        self.assertFalse(ok)
        self.assertIn("n=3", note)

    def test_a_live_claim_grades_on_live_rows_only(self):
        from brain.hypotheses import _resolve_rule_avg_r_threshold
        hyp = self._hyp({"kind": "rule_avg_r", "rule_name": "manual_take",
                         "comparator": ">=", "threshold": 0.0, "min_n": 1,
                         "venue": "live"})
        ok, note = _resolve_rule_avg_r_threshold(hyp)
        self.assertTrue(ok)
        self.assertIn("n=1", note)
        self.assertIn("live", note)

    def test_an_unknown_venue_is_refused_at_creation(self):
        from brain.hypotheses import UnmeasurableClaim, _validate_criteria
        with self.assertRaises(UnmeasurableClaim):
            _validate_criteria({"kind": "rule_avg_r", "rule_name": "x",
                                "venue": "real"})

    def test_calibration_reads_rule_at_venue(self):
        from brain.calibration import _rule_avg_r_measurement
        with patch("brain.hypotheses.MIN_TRADES_FOR_RULE_R", 1):
            live, live_note = _rule_avg_r_measurement("manual_take@live")
            pooled, pooled_note = _rule_avg_r_measurement("manual_take")
        self.assertAlmostEqual(live, 0.3)
        self.assertIn("live", live_note)
        self.assertAlmostEqual(pooled, (0.3 - 0.5 - 1.06) / 3)

    def test_the_position_review_claim_carries_the_rows_world(self):
        from types import SimpleNamespace
        from brain.position_review_agent import _post_hypothesis_for
        from brain.position_review_models import PositionReview
        review = SimpleNamespace(
            id=1, position_key="bot:1", trigger_codes=["rule_decayed"],
            confidence=0.6, symbol="XAUUSD",
            verdict=PositionReview.VERDICT_EXIT,
            facts={"rule_state": {"rule_name": "manual_take"},
                   "venue": "demo"},
            save=lambda **kw: None)
        with patch("brain.hypotheses.post_hypothesis") as post:
            _post_hypothesis_for(review, {}, {})
        self.assertEqual(post.call_args.kwargs["resolution_criteria"]["venue"],
                         "demo")


class TheOtherReadersNameTheVenueTests(TestCase):
    def setUp(self):
        _the_book(self)

    def test_the_strategist_reads_the_reports_split_and_the_rule(self):
        from brain.models import BrainReport
        from brain.strategist import StrategistAgent, _build_strategist_snapshot
        BrainReport.objects.create(
            regime_label="trending", regime_confidence=0.6,
            track_records={"rows": [{"rule_name": "rsi_bull_divergence",
                                     "asset_class": "forex",
                                     "venue": "paper", "n": 1,
                                     "avg_r": -8.12}],
                           "venues": {"paper": "the platform simulator"},
                           "window_days": 14})
        snap = _build_strategist_snapshot()
        self.assertEqual(snap["track_records"]["rows"][0]["venue"], "paper")
        prompt = StrategistAgent.__new__(StrategistAgent).get_system_prompt()
        self.assertIn("A paper or demo result is never a live failure",
                      prompt)

    def test_the_demoter_names_the_venue_it_judged(self):
        from brain.demoter import _check_sustained_negative
        out = _check_sustained_negative("rsi_bull_divergence", window_days=14,
                                        min_n=1, min_avg_r=0.0)
        self.assertEqual(out["venue"], "paper")
        self.assertEqual(out["avg_r"], -8.12)
        self.assertIsNone(_check_sustained_negative(
            "manual_take", window_days=14, min_n=2, min_avg_r=0.0))

    def test_the_demoters_loss_streak_is_one_venues(self):
        from brain.demoter import _check_consecutive_losses
        self.assertIsNone(_check_consecutive_losses(
            "manual_take", consec_threshold=2))

    def test_the_generator_and_the_mutator_print_the_venue(self):
        from ai_agents.agents.strategy_mutator import StrategyMutatorAgent
        from brain.strategy_generator import _build_generation_snapshot
        for _ in range(3):
            _closed(self.cfg, rule="gen_rule", r=0.8, paper=True)
            _closed(self.cfg, rule="gen_rule", r=0.4, paper=False,
                    metadata=DEMO)
        snap = _build_generation_snapshot()
        rows = _rows_by(snap["top_performing_rules"])
        self.assertEqual(set(rows), {("gen_rule", "forex", "paper"),
                                     ("gen_rule", "forex", "demo")})
        self.assertEqual(rows[("gen_rule", "forex", "demo")]["avg_r"], 0.4)
        self.assertIn("demo", snap["evidence_ledger_note"])
        agent = StrategyMutatorAgent.__new__(StrategyMutatorAgent)
        with patch("brain.context.context_for_prompt", return_value=""):
            ctx = agent.build_context(
                rule_name="manual_take", schema={}, current_params={},
                track_record={"venue": "live", "n": 1, "win_rate": 1.0,
                              "avg_r": 0.3, "expectancy": 0.3})
        self.assertIn("venue:      live", ctx)

    def test_the_mutator_reads_live_first(self):
        from ai_agents.agents.strategy_mutator import _track_record_for
        rec = _track_record_for("manual_take")
        self.assertEqual(rec["venue"], "live")
        self.assertEqual(rec["avg_r"], 0.3)
        self.assertEqual(_track_record_for("rsi_bull_divergence")["venue"],
                         "paper")

    def test_the_decay_detector_alerts_per_venue(self):
        from bot_program.track_record_decay import check_user_decay
        from bot_program.track_record_models import RuleTrackRecordAlert
        from brain.models import BrainObservation
        user = User.objects.create_user("venue_decay")
        cfg = _cfg(user, name="decay")
        for i in range(12):
            _closed(cfg, rule="dec_rule", r=1.0, paper=True, days_ago=20 + i % 5)
        for i in range(6):
            _closed(cfg, rule="dec_rule", r=-1.0, paper=True, days_ago=1)
        for i in range(12):
            _closed(cfg, rule="dec_rule", r=1.0, paper=False, metadata=LIVE,
                    days_ago=20 + i % 5)
        for i in range(6):
            _closed(cfg, rule="dec_rule", r=1.0, paper=False, metadata=LIVE,
                    days_ago=1)
        out = check_user_decay(user)
        self.assertEqual(out["alerts_fired"], 1)
        (alert,) = RuleTrackRecordAlert.objects.filter(user=user)
        self.assertEqual(alert.venue, "paper")
        obs = BrainObservation.objects.get(kind="rule_decayed")
        self.assertEqual(obs.payload["venue"], "paper")

    def test_the_decay_investigator_says_signal_outcomes(self):
        from ai_agents.agents.decay_investigator import DecayInvestigatorAgent
        prompt = DecayInvestigatorAgent.__new__(
            DecayInvestigatorAgent).get_system_prompt()
        self.assertIn("signal outcomes, not fills", prompt)

    def test_the_position_review_calls_demo_demo(self):
        from bot_program.asset_models import AssetBotTrade
        from brain.position_review import bot_position, measure
        t = AssetBotTrade.objects.create(
            config=self.cfg, asset_class="commodity", symbol="XAUUSD",
            side="BUY", qty=D("1"), entry_price=D("2000"),
            stop_loss=D("1990"), status="OPEN", paper=False,
            rule_name="manual_take", metadata=DEMO)
        with patch("brain.position_review.usable_mark",
                   return_value=(None, "no mark")):
            facts = measure(bot_position(t))
        self.assertEqual(facts["venue"], "demo")


# ── The review of 2026-10-15 ──────────────────────────────────────────────

class TheDemoterJudgesLiveFirstTests(TestCase):
    """A demotion pauses the rule's REAL entries too: a live record that
    passes is never outvoted by paper or demo (review: live n=6 +0.40R,
    paper n=8 -0.10R paused a rule trading real money at a profit)."""

    def setUp(self):
        self.user = User.objects.create_user("demote_live_first")
        self.cfg = _cfg(self.user, name="demote")

    def test_a_live_record_that_passes_spares_the_rule(self):
        from brain.demoter import _check_sustained_negative
        for _ in range(6):
            _closed(self.cfg, rule="lf_rule", r=0.4, paper=False,
                    metadata=LIVE)
        for _ in range(8):
            _closed(self.cfg, rule="lf_rule", r=-0.1, paper=True)
        self.assertIsNone(_check_sustained_negative(
            "lf_rule", window_days=30, min_n=5, min_avg_r=0.0))

    def test_paper_decides_only_when_live_and_demo_hold_too_few(self):
        from brain.demoter import _check_sustained_negative
        for _ in range(2):
            _closed(self.cfg, rule="lf_rule", r=1.0, paper=False,
                    metadata=LIVE)
        for _ in range(8):
            _closed(self.cfg, rule="lf_rule", r=-0.1, paper=True)
        out = _check_sustained_negative("lf_rule", window_days=30, min_n=5,
                                        min_avg_r=0.0)
        self.assertEqual(out["venue"], "paper")
        self.assertEqual(out["n"], 8)

    def test_a_live_record_that_fails_is_named_live(self):
        from brain.demoter import _check_sustained_negative
        for _ in range(6):
            _closed(self.cfg, rule="lf_rule", r=-0.5, paper=False,
                    metadata=LIVE)
        for _ in range(8):
            _closed(self.cfg, rule="lf_rule", r=1.0, paper=True)
        out = _check_sustained_negative("lf_rule", window_days=30, min_n=5,
                                        min_avg_r=0.0)
        self.assertEqual(out["venue"], "live")

    def test_five_paper_losses_never_pause_a_rule_winning_live(self):
        from brain.demoter import _check_consecutive_losses
        for _ in range(5):
            _closed(self.cfg, rule="lf_rule", r=-1.0, paper=True)
        for _ in range(5):
            _closed(self.cfg, rule="lf_rule", r=0.8, paper=False,
                    metadata=LIVE, days_ago=2)
        self.assertIsNone(_check_consecutive_losses("lf_rule",
                                                    consec_threshold=5))

    def test_a_paper_streak_decides_when_live_holds_too_few(self):
        from brain.demoter import _check_consecutive_losses
        for _ in range(5):
            _closed(self.cfg, rule="lf_rule", r=-1.0, paper=True)
        for _ in range(3):
            _closed(self.cfg, rule="lf_rule", r=0.8, paper=False,
                    metadata=LIVE)
        out = _check_consecutive_losses("lf_rule", consec_threshold=5)
        self.assertEqual(out["venue"], "paper")


class APauseRestsOnLiveEvidenceTests(TestCase):
    """pause_recommended stops every entry of the rule, real ones included
    (context.brain_rule_advisory, base.py's BRAIN_PAUSED skip). One resting
    on paper or demo evidence alone is a watch."""

    def _report(self, concerns, overlay, snapshot=None):
        from brain.synthesizer import _persist_report
        parsed = {"regime_label": "trending", "regime_confidence": 0.6,
                  "portfolio_health_score": 0.6, "top_concerns": concerns,
                  "rule_status_overlay": overlay, "narrative_md": "n"}
        return _persist_report(parsed, snapshot or {}, model="m",
                               tokens_in=0, tokens_out=0, cost_usd=0.0,
                               n_consumed=0)

    def test_the_rule_no_longer_allows_a_pause_on_paper(self):
        from brain.synthesizer import VENUE_RULE
        self.assertNotIn("or name the venue", VENUE_RULE)
        self.assertIn("a paper or demo decline is at most watch", VENUE_RULE)

    def test_a_pause_resting_on_paper_is_stored_as_watch(self):
        from brain.context import brain_rule_advisory
        report = self._report(
            [{"kind": "rule_decay", "severity": 0.6, "venue": "paper",
              "ref": "rsi_bull_divergence", "text": "-1.4R on paper"}],
            {"rsi_bull_divergence": "pause_recommended"})
        self.assertEqual(report.rule_status_overlay,
                         {"rsi_bull_divergence": "watch"})
        self.assertEqual(report.rule_status_venue,
                         {"rsi_bull_divergence": "paper"})
        status, _ = brain_rule_advisory("rsi_bull_divergence")
        self.assertEqual(status, "watch")

    def test_a_pause_on_a_live_concern_stands(self):
        from brain.context import brain_rule_advisory
        report = self._report(
            [{"kind": "rule_decay", "severity": 0.6, "venue": "live",
              "ref": "rsi_bull_divergence, macd_cross",
              "text": "-1.1R on real money"}],
            {"rsi_bull_divergence": "pause_recommended"})
        self.assertEqual(report.rule_status_overlay["rsi_bull_divergence"],
                         "pause_recommended")
        self.assertEqual(report.rule_status_venue["rsi_bull_divergence"],
                         "live")
        self.assertEqual(brain_rule_advisory("rsi_bull_divergence")[0],
                         "pause_recommended")

    def test_a_live_row_below_zero_in_the_snapshot_is_live_evidence(self):
        report = self._report(
            [], {"x_rule": "pause_recommended", "y_rule": "pause_recommended"},
            snapshot={"rule_track_records": [
                {"rule_name": "x_rule", "venue": "live", "avg_r": -0.3},
                {"rule_name": "y_rule", "venue": "demo", "avg_r": -0.9},
                {"rule_name": "y_rule", "venue": "live", "avg_r": 0.2}]})
        self.assertEqual(report.rule_status_overlay,
                         {"x_rule": "pause_recommended", "y_rule": "watch"})
        self.assertEqual(report.rule_status_venue,
                         {"x_rule": "live", "y_rule": "demo"})


class TheContextNamesTheVenueTests(TestCase):
    """context_for_prompt feeds the trade debate that gates live entries:
    a concern's R travels with its venue, and the overlay with its own."""

    def test_concerns_and_overlay_carry_their_venue_and_the_legend(self):
        from brain.context import context_for_prompt
        from brain.models import BrainReport
        BrainReport.objects.create(
            regime_label="trending", regime_confidence=0.6,
            portfolio_health_score=0.5,
            top_concerns=[{"kind": "rule_decay", "severity": 0.7,
                           "venue": "paper", "ref": "rsi_bull_divergence",
                           "text": "rsi_bull_divergence lost -8.12R"}],
            rule_status_overlay={"rsi_bull_divergence": "watch"},
            rule_status_venue={"rsi_bull_divergence": "paper"})
        text = context_for_prompt()
        self.assertIn("- [rule_decay / paper] rsi_bull_divergence lost "
                      "-8.12R", text)
        self.assertIn("rsi_bull_divergence: watch (paper)", text)
        self.assertIn("a paper or demo loss is never a live failure", text)


class RuleClaimsNameTheirVenueTests(TestCase):
    """A model-written rule_avg_r claim with no venue would grade on the
    pooled record and move a trust score printed with no venue."""

    def test_a_venueless_rule_claim_from_the_strategist_is_refused(self):
        from brain.hypotheses import UnmeasurableClaim, post_hypothesis
        with self.assertRaises(UnmeasurableClaim):
            post_hypothesis(
                claim_text="rsi keeps losing", source_agent="strategist",
                resolution_criteria={"kind": "rule_avg_r",
                                     "rule_name": "rsi_bull_divergence",
                                     "comparator": "<", "threshold": 0.0})

    def test_a_programmatic_authors_claim_keeps_the_pooled_record(self):
        from brain.hypotheses import post_hypothesis
        with patch("brain.hypotheses._refuse_if_the_rule_cannot_trade"):
            hyp = post_hypothesis(
                claim_text="mutated", source_agent="strategy_mutator",
                resolution_criteria={"kind": "rule_avg_r",
                                     "rule_name": "rsi_bull_divergence",
                                     "comparator": ">=", "threshold": 0.0})
        self.assertNotIn("venue", hyp.resolution_criteria)

    def test_the_strategists_ideas_post_only_with_a_venue(self):
        from brain.knowledge_models import Hypothesis
        from brain.strategist import STRATEGIST_SCHEMA, _emit_idea_hypotheses
        from types import SimpleNamespace
        self.assertIn('"venue"', STRATEGIST_SCHEMA)
        ideas = [
            {"summary": "no venue", "hypothesis_kind": "rule_avg_r",
             "hypothesis_payload": {"rule_name": "rsi_bull_divergence",
                                    "comparator": "<", "threshold": 0.0}},
            {"summary": "live", "hypothesis_kind": "rule_avg_r",
             "hypothesis_payload": {"rule_name": "rsi_bull_divergence",
                                    "comparator": "<", "threshold": 0.0,
                                    "venue": "live"}}]
        with patch("brain.hypotheses._refuse_if_the_rule_cannot_trade"):
            n = _emit_idea_hypotheses(SimpleNamespace(id=1), ideas)
        self.assertEqual(n, 1)
        (hyp,) = Hypothesis.objects.filter(source_agent="strategist")
        self.assertEqual(hyp.resolution_criteria["venue"], "live")

    def test_a_mind_rule_prediction_with_no_venue_posts_no_claim(self):
        from ai_agents.models import AgentPrediction
        from brain.knowledge_models import Hypothesis
        from brain.synthesizer import _emit_predictions
        from types import SimpleNamespace
        parsed = {"predictions": [{"prediction_type": "rule_recovers",
                                   "predicted_value": "rsi_bull_divergence",
                                   "confidence": 0.6, "horizon_hours": 48}]}
        with patch("brain.hypotheses._refuse_if_the_rule_cannot_trade"):
            _emit_predictions(SimpleNamespace(id=None, pk=None), parsed)
        self.assertEqual(AgentPrediction.objects.filter(
            agent="sauron_mind").count(), 1)
        self.assertFalse(Hypothesis.objects.filter(
            source_agent="sauron_mind").exists())

    def test_the_trust_basis_says_what_each_score_was_earned_on(self):
        from brain.knowledge_models import Hypothesis
        from brain.strategist import _build_strategist_snapshot
        deadline = timezone.now() + timedelta(days=1)
        for crit, outcome in (
                ({"kind": "rule_avg_r", "rule_name": "a", "venue": "live"},
                 Hypothesis.OUTCOME_CONFIRMED),
                ({"kind": "rule_avg_r", "rule_name": "a"},
                 Hypothesis.OUTCOME_REFUTED),
                ({"kind": "regime_holds", "regime": "trending"},
                 Hypothesis.OUTCOME_CONFIRMED),
                ({"kind": "rule_avg_r", "rule_name": "a", "venue": "paper"},
                 Hypothesis.OUTCOME_UNRESOLVABLE)):
            Hypothesis.objects.create(
                claim_text="c", source_agent="strategist", confidence=0.6,
                resolution_criteria=crit, resolution_deadline=deadline,
                outcome=outcome)
        basis = _build_strategist_snapshot()["agent_trust_basis"]
        self.assertEqual(basis["strategist"]["graded_by_venue"],
                         {"live": 1, "pooled": 1, "other": 1})


class ObservationsNameTheirVenueTests(TestCase):
    def test_a_demo_close_reaches_the_mind_as_demo(self):
        from brain.observations import record_observation
        from brain.synthesizer import _build_world_snapshot
        record_observation(kind="fill_closed", source="audit", payload={
            "mode": "live", "world": "demo", "realized_r": -2.1,
            "symbol": "XAUUSD"})
        (obs,) = [o for o in _build_world_snapshot()["observations"]
                  if o["kind"] == "fill_closed"]
        self.assertEqual(obs["payload"]["venue"], "demo")
        self.assertNotIn("mode", obs["payload"])

    def test_a_close_says_how_its_exit_was_priced(self):
        from bot_program.audit import record_trade_close
        from brain.models import BrainObservation
        user = User.objects.create_user("exit_model")
        cfg = _cfg(user, name="exit model")
        rows = {
            "bar_replay": _closed(cfg, rule="r", r=-1.0, paper=True,
                                  metadata={"paper_exit": {
                                      "model": "bar_replay"}}),
            "mark": _closed(cfg, rule="r", r=-1.0, paper=True),
            "unmanaged": _closed(cfg, rule="r", r=-1.0, paper=True,
                                 metadata={"unmanaged_exit": {"why": "x"}}),
            "broker": _closed(cfg, rule="r", r=-1.0, paper=False,
                              metadata=LIVE),
        }
        for want, trade in rows.items():
            record_trade_close(user, trade=trade)
            obs = (BrainObservation.objects.filter(kind="fill_closed")
                   .order_by("-id").first())
            self.assertEqual(obs.payload["exit_model"], want)


class TheDecayVenuesAreKeptApartTests(TestCase):
    """The venue split of the decay detector and its readers, pinned (each
    behaviour below survived its own mutation in the review)."""

    def _decaying_paper_healthy_live(self, user):
        cfg = _cfg(user, name="decay apart")
        for i in range(12):
            _closed(cfg, rule="dec_rule", r=1.0, paper=True,
                    days_ago=20 + i % 5)
            _closed(cfg, rule="dec_rule", r=1.0, paper=False, metadata=LIVE,
                    days_ago=20 + i % 5)
        for _ in range(6):
            _closed(cfg, rule="dec_rule", r=-1.0, paper=True, days_ago=1)
            _closed(cfg, rule="dec_rule", r=1.0, paper=False, metadata=LIVE,
                    days_ago=1)

    def test_a_paper_decay_alert_never_triggers_a_live_review(self):
        from bot_program.track_record_models import RuleTrackRecordAlert
        from brain.position_review import _rule_state
        user = User.objects.create_user("rv_decay")
        RuleTrackRecordAlert.objects.create(
            user=user, rule_name="rsi_bull_divergence", asset_class="forex",
            venue="paper", triggers=["gone_negative"])
        live = {"rule_name": "rsi_bull_divergence", "paper": False,
                "metadata": dict(LIVE), "asset_class": "forex",
                "symbol": "GBPUSD", "book": "bot"}
        paper = dict(live, paper=True, metadata={})
        self.assertFalse(_rule_state(live).get("open_decay_alert"))
        self.assertTrue(_rule_state(paper).get("open_decay_alert"))

    def test_a_second_pass_never_resolves_another_venues_alert(self):
        from bot_program.track_record_decay import check_user_decay
        from bot_program.track_record_models import RuleTrackRecordAlert
        user = User.objects.create_user("rv_decay2")
        self._decaying_paper_healthy_live(user)
        check_user_decay(user)
        second = check_user_decay(user)
        self.assertEqual(second["alerts_fired"], 0)
        self.assertEqual(RuleTrackRecordAlert.objects.filter(
            user=user, resolved_at__isnull=True).count(), 1)

    def test_a_pooled_alert_from_before_the_split_is_resolved(self):
        from bot_program.track_record_decay import check_user_decay
        from bot_program.track_record_models import RuleTrackRecordAlert
        user = User.objects.create_user("rv_decay3")
        old = RuleTrackRecordAlert.objects.create(
            user=user, rule_name="dec_rule", asset_class="forex",
            venue="all", triggers=["gone_negative"])
        out = check_user_decay(user)
        old.refresh_from_db()
        self.assertIsNotNone(old.resolved_at)
        self.assertEqual(out["resolved"], 1)

    def test_the_decay_notification_says_where_it_was_measured(self):
        from bot_program.notifications import notify_track_record_decay
        user = User.objects.create_user("rv_decay4")
        with patch("bot_program.notifications.dispatch_notification",
                   return_value=True) as send:
            notify_track_record_decay(
                user, rule_name="dec_rule", asset_class="forex",
                recent_avg_r=-0.5, baseline_avg_r=0.6, recent_n=6,
                triggers=["gone_negative"], venue="paper")
        items = send.call_args.kwargs["row_data"]["items"]
        self.assertTrue(any(i.startswith("Measured on: paper")
                            for i in items))
