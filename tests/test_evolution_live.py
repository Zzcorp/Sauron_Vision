"""The evolution layer comes alive: schema + evaluator registered, the
golden-cross family parameter-aware and fork-executing, decay-triggered
proposals, and the evidence-adaptive cadence gate.

Phase 9 shipped complete machinery with zero registrations — no rule had
a schema, so the weekly sweep skipped everything, forever; and applied
forks created RuleControl rows no engine ever executed.

Run with:  python manage.py test tests.test_evolution_live
"""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User  # noqa: F401 — parity with peers
from django.test import TestCase
from django.utils import timezone


def _instrument(symbol="BTCUSD", asset_class="crypto"):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class})
    return inst


def _enable(*keys):
    from core.platform_control import PlatformComponent, seed_components
    seed_components()
    PlatformComponent.objects.filter(
        key__in=("platform_master",) + keys).update(is_enabled=True)


class RegistrationTests(TestCase):
    def test_golden_cross_registers_schema_and_evaluator(self):
        from signals.evolution import _ensure_rules_registered, has_schema
        from signals.evolution_backtest import has_evaluator
        _ensure_rules_registered()
        self.assertTrue(has_schema("golden_cross"),
                        "no schema — the evolution layer is dormant again")
        self.assertTrue(has_evaluator("golden_cross"),
                        "no evaluator — proposals fall back to the heuristic")


class ParameterAwareRuleTests(TestCase):
    def _df(self, closes):
        import pandas as pd
        return pd.DataFrame({"close": closes})

    def test_parameters_drive_the_levels(self):
        from signals.rules.technical_rules import GoldenCrossRule
        rule = GoldenCrossRule(params={"fast": 2, "slow": 3,
                                       "stop_pct": 0.06, "target_pct": 0.12})
        df = self._df([100.0] * 12 + [120.0])  # cross on the last bar
        with patch("signals.rules.technical_rules._load_df",
                   return_value=("BTCUSD", df)):
            card = rule.evaluate(_instrument())
        self.assertIsNotNone(card, "the engineered cross did not fire")
        self.assertAlmostEqual(card["stop"], 120.0 * 0.94, places=6)
        self.assertAlmostEqual(card["target"], 120.0 * 1.12, places=6)
        self.assertIn("SMA2", card["thesis"])

    def test_a_degenerate_mutant_goes_silent(self):
        """fast >= slow describes nothing — it must not trade nonsense."""
        from signals.rules.technical_rules import GoldenCrossRule
        rule = GoldenCrossRule(params={"fast": 50, "slow": 50})
        with patch("signals.rules.technical_rules._load_df") as mock_load:
            self.assertIsNone(rule.evaluate(_instrument()))
        mock_load.assert_not_called()

    def test_applied_forks_join_the_engine(self):
        """apply_evolution used to create RuleControl rows no engine ever
        executed — forks now run under their own name and parameters."""
        from signals.models import RuleControl
        from signals.rules.technical_rules import get_rules
        RuleControl.objects.create(
            rule_name="golden_cross_evolved_v1",
            status=RuleControl.STATUS_ACTIVE,
            parameters={"fast": 30, "slow": 150,
                        "stop_pct": 0.04, "target_pct": 0.08})
        rules = get_rules()
        fork = next((r for r in rules
                     if r.name == "golden_cross_evolved_v1"), None)
        self.assertIsNotNone(fork, "the fork never reached the engine")
        self.assertEqual(fork.params["fast"], 30)
        # The base rule is still there too — may the better one win.
        self.assertTrue(any(r.name == "golden_cross" for r in rules))

    def test_reduced_and_pause_expired_forks_still_run(self):
        """Demoted-not-dead: a REDUCED fork trades at reduced size and an
        expired pause auto-reactivates. Filtering on status=='active' made
        both vanish from the engine permanently — no recovery, no further
        demotion, no evaluation ever again."""
        from signals.models import RuleControl
        from signals.rules.technical_rules import get_rules
        RuleControl.objects.create(
            rule_name="golden_cross_evolved_v2",
            status=RuleControl.STATUS_REDUCED, weight_multiplier=0.5,
            parameters={"fast": 20, "slow": 140})
        RuleControl.objects.create(
            rule_name="golden_cross_evolved_v3",
            status=RuleControl.STATUS_PAUSED,
            paused_until=timezone.now() - timedelta(hours=1),
            parameters={"fast": 25, "slow": 160})
        RuleControl.objects.create(
            rule_name="golden_cross_evolved_v4",
            status=RuleControl.STATUS_PAUSED,
            paused_until=timezone.now() + timedelta(days=1),
            parameters={"fast": 35, "slow": 170})
        names = {r.name for r in get_rules()}
        self.assertIn("golden_cross_evolved_v2", names,
                      "a REDUCED fork must keep trading")
        self.assertIn("golden_cross_evolved_v3", names,
                      "an expired pause must auto-reactivate")
        self.assertNotIn("golden_cross_evolved_v4", names,
                         "a live pause must still exclude the fork")


class EvaluatorTests(TestCase):
    def test_walk_forward_evaluator_replays_a_cross_to_target(self):
        from market_data.models import PriceData
        from signals.evolution_rules import golden_cross_evaluator
        inst = _instrument("EVALX", asset_class="stock")
        now = timezone.now()
        # 15 flat bars, then a jump (the cross), then a bar through target.
        closes = [100.0] * 15 + [110.0, 111.0]
        highs = list(closes)
        highs[16] = 140.0  # rips through the 132 target
        rows = []
        for i, c in enumerate(closes):
            rows.append(PriceData(
                instrument=inst, timeframe="4h",
                timestamp=now - timedelta(hours=4 * (len(closes) - i)),
                open=Decimal(str(c)), high=Decimal(str(highs[i])),
                low=Decimal("100"), close=Decimal(str(c)),
                volume=1, source="test"))
        PriceData.objects.bulk_create(rows)

        params = {"fast": 2, "slow": 6, "stop_pct": 0.10, "target_pct": 0.20}
        start = now - timedelta(hours=4 * 3)   # window holds the cross bar
        with patch("signals.evolution_rules._gc_universe",
                   return_value=[inst.id]):
            rs = golden_cross_evaluator(params, start, now)
        self.assertEqual(rs, [2.0],
                         "target at +20% against a 10% stop is exactly +2R")

    def test_degenerate_params_return_nothing(self):
        from signals.evolution_rules import golden_cross_evaluator
        self.assertEqual(
            golden_cross_evaluator({"fast": 10, "slow": 10},
                                   timezone.now(), timezone.now()), [])

    def test_insufficient_warmup_skips_not_truncates(self):
        """Warm-up is counted in BARS, not calendar days. The old day-based
        budget assumed 24/7 markets, so a stock's scan silently started
        deep inside the window at a depth depending on the candidate's own
        `slow` — walk-forward halves compared different regimes. Now an
        instrument without `slow` bars of history before the window is
        skipped outright."""
        from market_data.models import PriceData
        from signals.evolution_rules import golden_cross_evaluator
        inst = _instrument("WARMX", asset_class="stock")
        now = timezone.now()
        closes = [100.0] * 4 + [100.0, 110.0, 111.0]  # only 4 warm-up bars
        highs = list(closes)
        highs[6] = 140.0
        PriceData.objects.bulk_create([
            PriceData(
                instrument=inst, timeframe="4h",
                timestamp=now - timedelta(hours=4 * (len(closes) - i)),
                open=Decimal(str(c)), high=Decimal(str(highs[i])),
                low=Decimal("100"), close=Decimal(str(c)),
                volume=1, source="test")
            for i, c in enumerate(closes)])
        params = {"fast": 2, "slow": 6, "stop_pct": 0.10, "target_pct": 0.20}
        start = now - timedelta(hours=4 * 3)
        with patch("signals.evolution_rules._gc_universe",
                   return_value=[inst.id]):
            rs = golden_cross_evaluator(params, start, now)
        self.assertEqual(rs, [], "4 warm-up bars < slow=6 must skip, "
                                 "not scan a truncated slice")

    def test_universe_deduplicates_hot_instruments(self):
        """Signal's Meta.ordering used to ride into the DISTINCT, making it
        a no-op over (instrument_id, created_at) pairs — one hot instrument
        occupied several capped slots (its R-multiples double-counted) and
        the watchlist top-up starved."""
        from instruments.models import Instrument
        from signals.models import Signal
        from signals.evolution_rules import _gc_universe
        hot = _instrument("HOTX", asset_class="crypto")
        for _ in range(3):
            Signal.objects.create(
                instrument=hot, signal_type="technical", direction="bullish",
                urgency="high", title="t", description="d",
                rule_name="golden_cross", score=0.7, sub_scores={},
                price_at_signal=Decimal("100"))
        watch = _instrument("WATCHX", asset_class="stock")
        Instrument.objects.filter(id=watch.id).update(
            is_watchlist=True, is_active=True)
        ids = _gc_universe()
        self.assertEqual(ids.count(hot.id), 1,
                         "a hot instrument must occupy exactly one slot")
        self.assertIn(watch.id, ids, "the watchlist top-up must fire")

    def test_universe_eligibility_is_uniform_across_candidates(self):
        """Eligibility at the schema's max `slow`, not the candidate's own:
        a per-candidate warm-up gate let a slow=120 mutant trade
        instruments a slow=200 parent never saw, so their walk-forward
        delta measured instrument mix, not the parameter change."""
        from market_data.models import PriceData
        from signals.evolution_rules import _gc_universe_at
        now = timezone.now()
        deep = _instrument("DEEPX", asset_class="crypto")
        shallow = _instrument("SHALX", asset_class="stock")
        rows = []
        for inst, n in ((deep, 6), (shallow, 3)):
            for i in range(n):
                rows.append(PriceData(
                    instrument=inst, timeframe="4h",
                    timestamp=now - timedelta(hours=4 * (i + 1)),
                    open=Decimal("100"), high=Decimal("100"),
                    low=Decimal("100"), close=Decimal("100"),
                    volume=1, source="test"))
        PriceData.objects.bulk_create(rows)
        with patch("signals.evolution_rules.GC_WARMUP_BARS", 6), \
             patch("signals.evolution_rules._gc_universe",
                   return_value=[deep.id, shallow.id]):
            eligible = _gc_universe_at(now)
        self.assertEqual(eligible, [deep.id],
                         "eligibility must be identical for every candidate")


class DecayTriggeredEvolutionTests(TestCase):
    def _close_signals(self, rule_name, n, r):
        """A batch of closed signals so the parent has an expectancy."""
        from signals.models import Signal
        inst = _instrument()
        now = timezone.now()
        for i in range(n):
            Signal.objects.create(
                instrument=inst, signal_type="technical",
                direction="bullish", urgency="high", title="t",
                description="d", rule_name=rule_name, score=0.7,
                sub_scores={}, price_at_signal=Decimal("100"),
                is_active=False, outcome="stopped_out", realized_r=r,
                expired_at=now - timedelta(days=1))

    def test_propose_if_fresh_creates_then_dedupes(self):
        from signals.evolution import propose_if_fresh
        from signals.models import RuleMutation
        _enable("pipeline_evolution")
        self._close_signals("golden_cross", 6, -0.4)
        first = propose_if_fresh("golden_cross")
        self.assertGreater(first["proposed"], 0, first)
        self.assertTrue(RuleMutation.objects.filter(
            parent_rule="golden_cross",
            state=RuleMutation.STATE_PROPOSED).exists())
        second = propose_if_fresh("golden_cross")
        self.assertEqual(second["proposed"], 0)
        self.assertIn("awaiting review", second["reason"])

    def test_a_stale_proposal_expires_and_reopens_the_question(self):
        """The dedupe must not be a padlock: an unreviewed batch past the
        TTL expires, and the next trigger asks again with fresh scores —
        otherwise one ignored batch silenced evolution for that rule
        forever, its frozen walk-forward scores only growing staler."""
        from signals.evolution import PROPOSAL_TTL_DAYS, propose_if_fresh
        from signals.models import RuleMutation
        _enable("pipeline_evolution")
        self._close_signals("golden_cross", 6, -0.4)
        first = propose_if_fresh("golden_cross")
        self.assertGreater(first["proposed"], 0, first)
        RuleMutation.objects.filter(
            state=RuleMutation.STATE_PROPOSED).update(
            proposed_at=timezone.now()
            - timedelta(days=PROPOSAL_TTL_DAYS + 1))
        again = propose_if_fresh("golden_cross")
        self.assertGreater(again["proposed"], 0, again)
        self.assertTrue(RuleMutation.objects.filter(
            parent_rule="golden_cross",
            state=RuleMutation.STATE_EXPIRED).exists(),
            "the stale batch must be marked EXPIRED, not deleted")

    def test_keyless_deployments_still_trigger_evolution(self):
        """The decay scan and the evolution trigger are pure DB statistics
        — behind the AI-key gate they were silently dead on keyless
        deployments while the docs promised a nightly reflex."""
        from ai_agents.tasks import investigate_decaying_rules
        _enable("pipeline_ai_decay", "pipeline_evolution")
        self._close_signals("golden_cross", 6, -0.4)
        with patch("ai_agents.tasks._ai_enabled", return_value=False), \
             patch("signals.performance.decay_flag",
                   return_value={"is_decaying": True}), \
             patch("signals.evolution.propose_if_fresh",
                   return_value={"proposed": 3,
                                 "reason": "decay-triggered"}) as mock_pif:
            out = investigate_decaying_rules()
        self.assertEqual(out["status"], "skipped")
        self.assertEqual(out["evolutions_triggered"], 3, out)
        mock_pif.assert_called()

    def test_the_component_switch_is_honoured(self):
        from signals.evolution import propose_if_fresh
        out = propose_if_fresh("golden_cross")
        self.assertEqual(out["proposed"], 0)
        self.assertIn("off", out["reason"])

    def test_confirmed_decay_triggers_a_proposal_the_same_night(self):
        from ai_agents.tasks import investigate_decaying_rules
        _enable("pipeline_ai_decay", "pipeline_evolution")
        self._close_signals("golden_cross", 6, -0.4)
        with patch("ai_agents.tasks._ai_enabled", return_value=True), \
             patch("ai_agents.agents.decay_investigator."
                   "investigate_decaying_rule", return_value=None), \
             patch("signals.performance.decay_flag",
                   return_value={"is_decaying": True}), \
             patch("signals.evolution.propose_if_fresh",
                   return_value={"proposed": 3,
                                 "reason": "decay-triggered"}) as mock_pif:
            out = investigate_decaying_rules()
        self.assertGreater(out["evolutions_triggered"], 0, out)
        mock_pif.assert_called()


class AdaptiveCadenceTests(TestCase):
    def test_a_quiet_midweek_skips_with_the_reason(self):
        from signals.tasks import propose_strategy_evolutions
        _enable("pipeline_evolution")
        tuesday = timezone.now().replace(
            year=2026, month=8, day=18, hour=5, minute=0)
        with patch("django.utils.timezone.now", return_value=tuesday):
            out = propose_strategy_evolutions()
        self.assertEqual(out["status"], "skipped")
        self.assertIn("cadence gate", out["reason"])

    def test_sunday_always_runs(self):
        from signals.tasks import propose_strategy_evolutions
        _enable("pipeline_evolution")
        sunday = timezone.now().replace(
            year=2026, month=8, day=23, hour=5, minute=0)
        with patch("django.utils.timezone.now", return_value=sunday), \
             patch("signals.evolution.propose_for_decaying_rules",
                   return_value={"total_proposals": 0}) as mock_sweep:
            out = propose_strategy_evolutions()
        self.assertEqual(out["status"], "ok")
        mock_sweep.assert_called_once()

    def test_a_busy_midweek_runs(self):
        """Fifty closed trades in a week is real evidence — cadence
        densifies to react to it."""
        from bot_program.models import AssetBotConfig, AssetBotTrade
        from signals.tasks import (EVOLUTION_DENSE_MIN_CLOSED_7D,
                                   propose_strategy_evolutions)
        _enable("pipeline_evolution")
        user = User.objects.create_user("evo_u", password="x")
        cfg = AssetBotConfig.objects.create(
            user=user, asset_class="crypto", name="starter_crypto",
            symbols=["BTCUSD"], enabled=True)
        now = timezone.now()
        AssetBotTrade.objects.bulk_create([
            AssetBotTrade(
                config=cfg, asset_class="crypto", symbol="BTCUSD",
                side="BUY", qty=Decimal("0.1"), entry_price=Decimal("100"),
                status="CLOSED", paper=True, rule_name="r",
                opened_at=now - timedelta(days=2),
                closed_at=now - timedelta(days=1))
            for _ in range(EVOLUTION_DENSE_MIN_CLOSED_7D)
        ])
        tuesday = now.replace(year=2026, month=8, day=18, hour=5, minute=0)
        with patch("django.utils.timezone.now", return_value=tuesday), \
             patch("signals.evolution.propose_for_decaying_rules",
                   return_value={"total_proposals": 0}) as mock_sweep:
            out = propose_strategy_evolutions()
        self.assertEqual(out["status"], "ok")
        mock_sweep.assert_called_once()


class ResearchStageVoteTests(TestCase):
    """A research-stage fork is the same detector as its parent with
    different constants. Its signals must not count as 'independent'
    confirmations that tip the parent's live orders into existence."""

    def _cfg(self, **overrides):
        from bot_program.models import AssetBotConfig
        user = User.objects.create_user("vote_u", password="x")
        defaults = dict(
            user=user, asset_class="stock", name="Vote Bot",
            enabled=True, mode="paper", symbols=["VOTEX"],
            capital=Decimal("10000"), base_currency="USD",
            position_size_pct=2.0, max_concurrent_positions=5,
            max_daily_loss_pct=2.0, stop_loss_pct=1.5, take_profit_pct=3.0,
            entry_score_min=0.6, min_signals_for_entry=2,
            cool_down_minutes=0)
        defaults.update(overrides)
        return AssetBotConfig.objects.create(**defaults)

    def _signal(self, rule_name, score=0.85):
        from signals.models import Signal
        inst = _instrument("VOTEX", asset_class="stock")
        return Signal.objects.create(
            instrument=inst, signal_type="technical", direction="bullish",
            urgency="high", title="t", description="d", rule_name=rule_name,
            score=score, sub_scores={}, price_at_signal=Decimal("100"),
            suggested_entry=Decimal("100"), suggested_stop=Decimal("95"),
            suggested_target=Decimal("110"), is_active=True)

    def test_research_stage_signals_do_not_vote(self):
        from bot_program.asset_engine import StockBot
        from signals.models import RuleControl
        RuleControl.objects.create(
            rule_name="golden_cross", status=RuleControl.STATUS_ACTIVE,
            promotion_stage=RuleControl.STAGE_LIVE_FULL)
        fork = RuleControl.objects.create(
            rule_name="golden_cross_evolved_v1",
            status=RuleControl.STATUS_ACTIVE,
            promotion_stage=RuleControl.STAGE_RESEARCH)
        self._signal("golden_cross")
        self._signal("golden_cross_evolved_v1")
        cfg = self._cfg()
        decision = StockBot(cfg).decide("VOTEX")
        self.assertEqual(decision.direction, "HOLD",
                         "a research fork's vote manufactured an entry: "
                         f"{decision.reasons}")
        # The same fork at PAPER stage has earned a venue — now it votes.
        fork.promotion_stage = RuleControl.STAGE_PAPER
        fork.save()
        decision = StockBot(cfg).decide("VOTEX")
        self.assertEqual(decision.direction, "BUY", decision.reasons)

    def test_research_forks_cannot_crowd_out_tradeable_votes(self):
        """The stage filter must run BEFORE the 8-vote cap: research forks
        tie or beat the tradeable rules' scores, and filtering after the
        slice let them occupy slots they cannot vote from — starving real
        signals out of the consensus into a silent HOLD."""
        from bot_program.asset_engine import StockBot
        from signals.models import RuleControl
        RuleControl.objects.create(
            rule_name="golden_cross", status=RuleControl.STATUS_ACTIVE,
            promotion_stage=RuleControl.STAGE_LIVE_FULL)
        for n in range(1, 9):
            RuleControl.objects.create(
                rule_name=f"golden_cross_evolved_v{n}",
                status=RuleControl.STATUS_ACTIVE,
                promotion_stage=RuleControl.STAGE_RESEARCH)
            self._signal(f"golden_cross_evolved_v{n}", score=0.9)
        self._signal("golden_cross", score=0.85)
        self._signal("macd_live", score=0.85)  # no control → paper venue
        cfg = self._cfg()
        decision = StockBot(cfg).decide("VOTEX")
        self.assertEqual(decision.direction, "BUY",
                         f"research forks crowded out the tradeable votes: "
                         f"{decision.reasons}")


class PromotionGateForkTests(TestCase):
    """The walk-forward evidence gate used an exact-name evaluator lookup,
    so every evolved fork hit 'no evaluator' and reached live stages
    through the fail-open path unbacktested."""

    def _fork(self):
        from signals.models import RuleControl
        return RuleControl.objects.create(
            rule_name="golden_cross_evolved_v1",
            status=RuleControl.STATUS_ACTIVE,
            promotion_stage=RuleControl.STAGE_PAPER,
            parameters={"fast": 30, "slow": 150,
                        "stop_pct": 0.04, "target_pct": 0.08})

    def test_forks_resolve_to_the_parent_evaluator_with_their_own_params(self):
        from signals.evolution import _ensure_rules_registered
        from signals.promotion_evidence import evaluate_rule
        _ensure_rules_registered()  # so the patch below is not overwritten
        self._fork()
        seen = []

        def fake_eval(params, start, end, universe=None):
            seen.append(dict(params))
            return [0.5] * 25

        with patch.dict("signals.evolution_backtest.EVALUATOR_REGISTRY",
                        {"golden_cross": fake_eval}):
            result = evaluate_rule("golden_cross_evolved_v1")
        self.assertTrue(result["available"],
                        "the fork never reached the parent's evaluator")
        self.assertTrue(result["passed"], result["reason"])
        self.assertEqual(seen[0]["fast"], 30,
                         "the fork must be backtested with ITS parameters")

    def test_a_bad_fork_is_blocked_from_live(self):
        from signals.evolution import _ensure_rules_registered
        from signals.promotion_evidence import gate_promotion
        _ensure_rules_registered()
        self._fork()
        with patch.dict("signals.evolution_backtest.EVALUATOR_REGISTRY",
                        {"golden_cross":
                         lambda p, s, e, universe=None: [-0.5] * 25}):
            allowed, reason = gate_promotion(
                "golden_cross_evolved_v1", "live_small")
        self.assertFalse(allowed, reason)


class SweepEconomyTests(TestCase):
    def test_a_sweep_computes_the_parent_baseline_once(self):
        """The parent's train/test backtests were recomputed for every one
        of the 20 mutants — half of a sweep's ~80 evaluator invocations —
        on a window drifting with each timezone.now(). One frozen context
        per sweep: exactly two parent-param invocations, however many
        mutants are scored."""
        from signals.evolution import (_ensure_rules_registered,
                                       current_params, propose_evolution)
        _ensure_rules_registered()
        parent = current_params("golden_cross")
        calls = []

        def fake_eval(params, start, end, universe=None):
            calls.append(dict(params))
            return [0.5] * 10

        with patch.dict("signals.evolution_backtest.EVALUATOR_REGISTRY",
                        {"golden_cross": fake_eval}):
            saved = propose_evolution("golden_cross", n_mutants=6, seed=7)
        self.assertTrue(saved, "the sweep produced no proposals")
        parent_calls = [c for c in calls if c == parent]
        self.assertEqual(
            len(parent_calls), 2,
            f"parent baselines must be computed once per sweep, "
            f"not per mutant — saw {len(parent_calls)} of {len(calls)} calls")

    def test_the_universe_is_pinned_for_a_whole_score(self):
        """The instrument set must be resolved once per walk-forward score
        and fed to all four legs — re-resolving per leg let a signal scan
        landing mid-sweep score mutants against a universe the frozen
        parent baselines never saw."""
        from signals.evolution_backtest import score_mutant_walkforward
        resolves = []
        seen = []

        def resolver(start):
            resolves.append(start)
            return [111, 222]

        def ev(params, start, end, universe=None):
            seen.append(list(universe or []))
            return [0.5] * 10

        with patch.dict("signals.evolution_backtest.EVALUATOR_REGISTRY",
                        {"pinned_rule": ev}), \
             patch.dict("signals.evolution_backtest.UNIVERSE_REGISTRY",
                        {"pinned_rule": resolver}):
            score_mutant_walkforward("pinned_rule", {"a": 2}, {"a": 1})
        self.assertEqual(len(resolves), 1,
                         "the universe must be resolved exactly once")
        self.assertEqual(seen, [[111, 222]] * 4,
                         "all four legs must run the identical pinned set")

    def test_a_failing_resolver_fails_closed_not_unpinned(self):
        """A resolver that raises must pin the EMPTY set: mapping failure
        to None silently handed every leg back to per-call self-resolution
        — the drifting, candidate-dependent universe the registry exists
        to eliminate — on any transient DB hiccup mid-sweep."""
        from signals.evolution_backtest import resolve_universe

        def boom(start):
            raise RuntimeError("transient db hiccup")

        with patch.dict("signals.evolution_backtest.UNIVERSE_REGISTRY",
                        {"pinned_rule": boom}):
            self.assertEqual(resolve_universe("pinned_rule", timezone.now()),
                             [], "failure must pin empty, not unpin")
        self.assertIsNone(
            resolve_universe("rule_without_resolver", timezone.now()),
            "no resolver still means self-resolving evaluator")
