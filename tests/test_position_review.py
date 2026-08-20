"""Phase 61 — the open-position watcher.

The question this feature answers: between entry and exit, was ANYTHING
re-examining an open position? It was not. Stop, target, an opt-in trailing
stop and a time stop nobody configures were the whole of it.

What these tests pin, in the order the risk runs:

  triggers        each one fires on constructed facts and stays quiet on a
                  healthy position — a watcher that flags everything is the
                  same as one that flags nothing
  no quote        no usable mark = no verdict, said out loud, never advice
                  computed from a fossil price
  the gate        the model pass costs nothing when layer one is silent
  the caps        per-pass and per-day ceilings, and the same-facts skip
  the record      the recommendation is stored WITH the evidence, and posts a
                  hypothesis the platform can grade
  the component   a guarded task with no DEFAULT_COMPONENTS row never runs
  the hard rule   nothing is ever auto-closed
"""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.utils import timezone


# ── Fixtures ─────────────────────────────────────────────────────────────

def _instrument(symbol, asset_class="stock"):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class})
    return inst


def _quote(symbol, price, *, asset_class="stock"):
    """A LiveQuote fresh enough for PaperTrader.ticker to accept it."""
    from market_data.models import LiveQuote
    inst = _instrument(symbol, asset_class)
    lq, _ = LiveQuote.objects.update_or_create(
        instrument=inst, defaults={"last": Decimal(str(price)),
                                    "source": "test"})
    return lq


def _config(user=None, name="pr_cfg"):
    from bot_program.models import AssetBotConfig
    if user is None:
        user, _ = User.objects.get_or_create(
            username="pr_trader", defaults={"password": "x"})
    cfg, _ = AssetBotConfig.objects.get_or_create(
        user=user, asset_class="stock", name=name,
        defaults=dict(
            enabled=True, mode="paper", symbols=[],
            capital=Decimal("10000"), base_currency="USD",
            position_size_pct=2.0, max_concurrent_positions=5,
            max_daily_loss_pct=2.0, stop_loss_pct=1.5, take_profit_pct=3.0,
            entry_score_min=0.6, min_signals_for_entry=1,
        ),
    )
    return cfg


def _trade(symbol="ACME", *, entry="100", initial_stop="99", stop="99",
           target="103", side="BUY", rule_name="", user=None,
           opened_hours_ago=2, cfg_name="pr_cfg"):
    from bot_program.models import AssetBotTrade
    cfg = _config(user, name=cfg_name)
    _instrument(symbol)
    t = AssetBotTrade.objects.create(
        config=cfg, asset_class="stock", symbol=symbol, side=side,
        qty=Decimal("10"), entry_price=Decimal(entry),
        stop_loss=Decimal(stop) if stop is not None else None,
        take_profit=Decimal(target) if target is not None else None,
        rule_name=rule_name, paper=True, status="OPEN",
        reason="momentum breakout above the prior high",
        metadata={"initial_stop_loss": float(initial_stop)},
    )
    # opened_at is auto_now_add; rewrite it so age-based triggers are testable.
    AssetBotTrade.objects.filter(pk=t.pk).update(
        opened_at=timezone.now() - timedelta(hours=opened_hours_ago))
    t.refresh_from_db()
    return t


def _facts(**over):
    """A healthy position's fact block — nothing should fire on it."""
    base = {
        "stale_quote": False,
        "symbol": "ACME", "side": "BUY", "book": "bot", "position_id": 1,
        "mark": 101.0, "entry": 100.0, "stop": 99.0, "target": 103.0,
        "unrealized_r": 1.0, "r_to_stop": 2.0, "r_to_target": 2.0,
        "mae_r": 1.0, "mfe_r": 1.0,
        "age_days": 1.0, "age_hours": 24.0, "horizon_days": None,
        "regime_at_entry": "trending", "regime_now": "trending",
        "regime_confidence_now": 0.9, "brain_trust_band": "high",
        "vol_ratio": 1.0, "vol_now": 0.01, "vol_at_entry": 0.01,
        "rule_state": {"rule_name": "r1", "control_status": "active",
                       "advisory": "allow", "open_decay_alert": False},
        "imminent_events": [],
        "concentration": {"dominant_theme": "equity", "dominant_exposure": 1.0,
                          "brain_pressure": 0.1, "overlap_rules": []},
    }
    base.update(over)
    return base


def _codes(facts):
    from brain.position_review import evaluate_triggers
    return {t["code"] for t in evaluate_triggers(facts)}


def _stub_agent(parsed, *, usage=None, recorder=None):
    """Patch the agent so no network call is made and the call is countable."""
    import json
    raw = json.dumps(parsed)
    usage = usage or {"input_tokens": 1200, "output_tokens": 400,
                      "cost_usd": 0.011}

    def patched_init(self, *a, **kw):
        self.agent_name = "position_reviewer"
        self.provider_name = "stub"
        self.model = "claude-stub"
        self.provider = MagicMock()
        self.provider.complete = MagicMock(return_value=(raw, usage))
        if recorder is not None:
            recorder.append(self)
    return patch(
        "brain.position_review_agent.PositionReviewerAgent.__init__",
        patched_init)


HOLD = {"verdict": "hold", "reasoning_md": "Thesis intact.",
        "confidence": 0.6, "suggested_stop": None, "take_part_pct": None,
        "falsifiable_claim": None}
EXIT = {"verdict": "exit", "reasoning_md": "The reason it was taken is gone.",
        "confidence": 0.72, "suggested_stop": None, "take_part_pct": None,
        "falsifiable_claim": "This position closes worse than it stands now."}


# ══════════════════════════════════════════════════════════════════════════
# Layer 1 — each trigger, firing and staying quiet
# ══════════════════════════════════════════════════════════════════════════

class HealthyPositionIsSilentTests(SimpleTestCase):
    def test_nothing_fires_on_a_healthy_position(self):
        self.assertEqual(_codes(_facts()), set())


class GiveBackTriggerTests(SimpleTestCase):
    def test_fires_when_more_than_half_the_open_profit_is_gone(self):
        self.assertIn("give_back", _codes(_facts(mfe_r=2.0, unrealized_r=0.8)))

    def test_quiet_while_most_of_the_profit_is_still_held(self):
        self.assertNotIn("give_back",
                         _codes(_facts(mfe_r=2.0, unrealized_r=1.8)))

    def test_quiet_below_one_r_of_peak_profit(self):
        """Under 1R the excursion is noise, not a win worth protecting."""
        self.assertNotIn("give_back",
                         _codes(_facts(mfe_r=0.8, unrealized_r=0.1)))


class RiskExceedsRewardTriggerTests(SimpleTestCase):
    def test_fires_when_the_remaining_leg_is_upside_down(self):
        self.assertIn("risk_exceeds_reward",
                      _codes(_facts(r_to_stop=3.0, r_to_target=1.0)))

    def test_quiet_just_past_halfway(self):
        self.assertNotIn("risk_exceeds_reward",
                         _codes(_facts(r_to_stop=2.4, r_to_target=1.7)))


class AdverseExcursionTriggerTests(SimpleTestCase):
    def test_fires_deep_in_the_hole_with_nothing_to_show(self):
        self.assertIn("adverse_excursion",
                      _codes(_facts(mae_r=-0.9, unrealized_r=-0.4,
                                     r_to_stop=0.6)))

    def test_quiet_when_the_dip_recovered_into_profit(self):
        self.assertNotIn("adverse_excursion",
                         _codes(_facts(mae_r=-0.9, unrealized_r=0.7)))

    def test_quiet_on_a_shallow_dip(self):
        self.assertNotIn("adverse_excursion",
                         _codes(_facts(mae_r=-0.4, unrealized_r=-0.2)))


class NearLevelTriggerTests(SimpleTestCase):
    def test_near_stop_fires_inside_a_quarter_r(self):
        self.assertIn("near_stop", _codes(_facts(r_to_stop=0.2)))

    def test_near_stop_quiet_at_a_full_r_away(self):
        self.assertNotIn("near_stop", _codes(_facts(r_to_stop=1.0)))

    def test_a_mark_through_the_stop_is_the_loudest_case(self):
        """The bracket did not fire and the position is still open."""
        from brain.position_review import evaluate_triggers
        fired = {t["code"]: t for t in evaluate_triggers(_facts(r_to_stop=-0.5))}
        self.assertIn("near_stop", fired)
        self.assertEqual(fired["near_stop"]["severity"], 1.0)
        self.assertTrue(fired["near_stop"]["values"]["through_stop"])

    def test_near_target_fires_inside_a_quarter_r(self):
        self.assertIn("near_target", _codes(_facts(r_to_target=0.1)))

    def test_near_target_quiet_far_from_the_target(self):
        self.assertNotIn("near_target", _codes(_facts(r_to_target=1.5)))


class HorizonTriggerTests(SimpleTestCase):
    def test_fires_past_the_setups_own_horizon_while_flat(self):
        self.assertIn("horizon_exceeded",
                      _codes(_facts(horizon_days=3, age_days=9.0,
                                     unrealized_r=0.1)))

    def test_quiet_inside_the_horizon(self):
        self.assertNotIn("horizon_exceeded",
                         _codes(_facts(horizon_days=30, age_days=9.0,
                                        unrealized_r=0.1)))

    def test_quiet_when_the_trade_is_actually_working(self):
        """Past its horizon but 2R onside is not stale, it is working."""
        self.assertNotIn("horizon_exceeded",
                         _codes(_facts(horizon_days=3, age_days=9.0,
                                        unrealized_r=2.0, mfe_r=2.0)))

    def test_unknown_horizon_never_fires(self):
        """Unknown is not zero — a fabricated horizon would flag everything."""
        self.assertNotIn("horizon_exceeded",
                         _codes(_facts(horizon_days=None, age_days=400.0,
                                        unrealized_r=0.0)))


class RegimeFlipTriggerTests(SimpleTestCase):
    def test_fires_on_a_confident_flip(self):
        self.assertIn("regime_flip",
                      _codes(_facts(regime_at_entry="risk_on",
                                     regime_now="risk_off",
                                     regime_confidence_now=0.8)))

    def test_quiet_when_the_brain_is_guessing(self):
        self.assertNotIn("regime_flip",
                         _codes(_facts(regime_at_entry="risk_on",
                                        regime_now="risk_off",
                                        regime_confidence_now=0.3)))

    def test_quiet_when_the_regime_was_never_classified(self):
        """'unknown' is the not-measured sentinel, not an observed flip."""
        self.assertNotIn("regime_flip",
                         _codes(_facts(regime_at_entry="risk_on",
                                        regime_now="unknown",
                                        regime_confidence_now=0.9)))


class VolExpansionTriggerTests(SimpleTestCase):
    def test_fires_when_vol_expanded_past_the_ratio(self):
        self.assertIn("vol_expansion", _codes(_facts(vol_ratio=1.8)))

    def test_quiet_on_a_mild_expansion(self):
        self.assertNotIn("vol_expansion", _codes(_facts(vol_ratio=1.2)))

    def test_quiet_when_vol_could_not_be_measured(self):
        self.assertNotIn("vol_expansion", _codes(_facts(vol_ratio=None)))


class EventTriggerTests(SimpleTestCase):
    def test_fires_on_an_imminent_high_impact_event(self):
        self.assertIn("event_imminent", _codes(_facts(imminent_events=[
            {"title": "ACME Q3 Earnings", "impact": "high",
             "datetime": "2026-08-20T12:00:00Z"}])))

    def test_quiet_with_an_empty_calendar(self):
        self.assertNotIn("event_imminent", _codes(_facts(imminent_events=[])))


class RuleDecayTriggerTests(SimpleTestCase):
    def test_fires_when_the_rule_is_paused(self):
        self.assertIn("rule_decayed", _codes(_facts(rule_state={
            "rule_name": "r1", "control_status": "paused",
            "advisory": "allow", "open_decay_alert": False})))

    def test_fires_on_an_open_track_record_decay_alert(self):
        self.assertIn("rule_decayed", _codes(_facts(rule_state={
            "rule_name": "r1", "control_status": "active",
            "advisory": "allow", "open_decay_alert": True})))

    def test_quiet_on_a_healthy_rule(self):
        self.assertNotIn("rule_decayed", _codes(_facts()))


class ConcentrationTriggerTests(SimpleTestCase):
    def test_fires_at_the_exposure_level_the_entry_gate_already_refuses(self):
        self.assertIn("concentration", _codes(_facts(concentration={
            "dominant_theme": "usd", "dominant_exposure": -3.0,
            "brain_pressure": 0.1, "overlap_rules": []})))

    def test_fires_when_two_rules_hold_the_same_symbol_and_side(self):
        self.assertIn("concentration", _codes(_facts(concentration={
            "dominant_theme": "equity", "dominant_exposure": 1.0,
            "brain_pressure": 0.1, "overlap_rules": ["r1", "r2"]})))

    def test_fires_on_saturated_brain_theme_pressure(self):
        self.assertIn("concentration", _codes(_facts(concentration={
            "dominant_theme": "equity", "dominant_exposure": 1.0,
            "brain_pressure": 0.85, "overlap_rules": []})))

    def test_quiet_on_an_independent_bet(self):
        self.assertNotIn("concentration", _codes(_facts()))


class StaleQuoteEvaluatesNothingTests(SimpleTestCase):
    def test_no_trigger_is_evaluated_without_a_mark(self):
        """Not 'no triggers' — no evaluation at all. Anything else would let a
        stale row be read as a clean bill of health."""
        facts = _facts(stale_quote=True, r_to_stop=0.01, mae_r=-3.0)
        self.assertEqual(_codes(facts), set())


# ══════════════════════════════════════════════════════════════════════════
# Measurement over the real books
# ══════════════════════════════════════════════════════════════════════════

class BothBooksAreReadTests(TestCase):
    def test_open_positions_unions_bot_trades_and_portfolio_positions(self):
        from brain.position_review import open_positions
        from instruments.models import Instrument
        from portfolio.models import Portfolio, Position

        _trade("BOTSYM")
        pf = Portfolio.objects.create(
            name="P", initial_capital=Decimal("1000"),
            current_value=Decimal("1000"), cash_available=Decimal("1000"))
        Position.objects.create(
            portfolio=pf, instrument=Instrument.objects.create(
                symbol="PFSYM", name="PFSYM", asset_class="stock"),
            direction="long", quantity=Decimal("5"),
            entry_price=Decimal("50"), current_price=Decimal("52"),
            stop_loss=Decimal("48"), take_profit=Decimal("56"),
            opened_at=timezone.now() - timedelta(days=1))

        books = {(p["book"], p["symbol"]) for p in open_positions()}
        self.assertIn(("bot", "BOTSYM"), books)
        self.assertIn(("pf", "PFSYM"), books)

    def test_closed_rows_are_not_watched(self):
        from brain.position_review import open_positions
        t = _trade("GONE")
        t.status = "CLOSED"
        t.save()
        self.assertNotIn("GONE", {p["symbol"] for p in open_positions()})


class RIsDenominatedByTheOpeningStopTests(TestCase):
    def test_a_trailed_stop_does_not_flatter_the_r(self):
        """The trailing stop rewrote stop_loss to 101; R must still be
        measured against the 99 the trade was actually taken with."""
        from brain.position_review import measure, open_positions
        _quote("TRAIL", 102)
        _trade("TRAIL", entry="100", initial_stop="99", stop="101",
                target="106")
        pos = [p for p in open_positions() if p["symbol"] == "TRAIL"][0]
        facts = measure(pos)
        self.assertEqual(facts["risk_per_unit"], 1.0)
        self.assertAlmostEqual(facts["unrealized_r"], 2.0, places=3)
        # R still at risk is measured to the CURRENT stop, in initial-R units.
        self.assertAlmostEqual(facts["r_to_stop"], 1.0, places=3)

    def test_two_rules_on_one_symbol_read_as_concentration_end_to_end(self):
        """Exercises the real overlap index, not a constructed fact block."""
        from brain.position_review import deterministic_pass
        _quote("STACK", 101)
        _trade("STACK", entry="100", initial_stop="99", stop="99",
                target="103", rule_name="rule_a", cfg_name="cfg_a")
        _trade("STACK", entry="100", initial_stop="99", stop="99",
                target="103", rule_name="rule_b", cfg_name="cfg_b")
        codes = set()
        for v in deterministic_pass():
            codes |= {t["code"] for t in v["triggers"]}
        self.assertIn("concentration", codes)

    def test_no_initial_stop_leaves_r_unmeasurable_not_zero(self):
        from brain.position_review import measure, open_positions
        _quote("NOSTOP", 102)
        t = _trade("NOSTOP", stop=None, target=None)
        t.metadata = {}
        t.stop_loss = None
        t.save()
        pos = [p for p in open_positions() if p["symbol"] == "NOSTOP"][0]
        facts = measure(pos)
        self.assertIsNone(facts["unrealized_r"])
        self.assertIsNone(facts["r_to_stop"])


# ══════════════════════════════════════════════════════════════════════════
# No quote = no verdict
# ══════════════════════════════════════════════════════════════════════════

class NoQuoteNoVerdictTests(TestCase):
    def test_measure_refuses_to_compute_anything_without_a_mark(self):
        from brain.position_review import measure, open_positions
        _trade("SILENT")  # no LiveQuote, no bars
        pos = [p for p in open_positions() if p["symbol"] == "SILENT"][0]
        facts = measure(pos)
        self.assertTrue(facts["stale_quote"])
        self.assertIsNone(facts["mark"])
        self.assertIsNone(facts["unrealized_r"])
        self.assertIn("no usable mark", facts["no_verdict_reason"])

    def test_a_stale_mark_persists_a_no_quote_row_and_pays_for_nothing(self):
        from brain.position_review_agent import review_open_positions_now
        from brain.position_review_models import PositionReview
        _trade("SILENT2")
        built = []
        with _stub_agent(EXIT, recorder=built):
            result = review_open_positions_now()
        self.assertEqual(result["n_stale_quote"], 1)
        self.assertEqual(result["n_model_reviews"], 0)
        self.assertEqual(built, [], "a stale mark must never reach the model")
        row = PositionReview.objects.get(symbol="SILENT2")
        self.assertEqual(row.verdict, PositionReview.VERDICT_NO_QUOTE)
        self.assertTrue(row.stale_quote)
        self.assertIn("no usable mark", row.skipped_reason)

    def test_a_stale_quote_is_not_a_usable_mark(self):
        from brain.position_review import usable_mark
        from market_data.models import LiveQuote
        _quote("FOSSIL", 100)
        LiveQuote.objects.filter(instrument__symbol="FOSSIL").update(
            updated_at=timezone.now() - timedelta(hours=6))
        price, reason = usable_mark("FOSSIL")
        self.assertIsNone(price)
        self.assertIn("no fresh quote", reason)


# ══════════════════════════════════════════════════════════════════════════
# The gate: layer 2 only runs when layer 1 fires
# ══════════════════════════════════════════════════════════════════════════

class ModelPassIsGatedTests(TestCase):
    def test_a_quiet_position_costs_nothing_and_writes_nothing(self):
        from brain.position_review_agent import review_open_positions_now
        from brain.position_review_models import PositionReview
        _quote("CALM", 101)
        _trade("CALM", entry="100", initial_stop="99", stop="99", target="103")
        built = []
        with _stub_agent(HOLD, recorder=built):
            result = review_open_positions_now()
        self.assertEqual(result["n_flagged"], 0)
        self.assertEqual(result["n_model_reviews"], 0)
        self.assertEqual(result["n_rows_written"], 0)
        self.assertEqual(built, [])
        self.assertEqual(PositionReview.objects.count(), 0)

    def test_a_flagged_position_reaches_the_model(self):
        from brain.position_review_agent import review_open_positions_now
        _quote("EDGE", 99.2)
        _trade("EDGE", entry="100", initial_stop="99", stop="99", target="103")
        built = []
        with _stub_agent(HOLD, recorder=built):
            result = review_open_positions_now()
        self.assertEqual(result["n_flagged"], 1)
        self.assertEqual(result["n_model_reviews"], 1)
        self.assertEqual(len(built), 1)


# ══════════════════════════════════════════════════════════════════════════
# Cost bounds
# ══════════════════════════════════════════════════════════════════════════

class CostBoundTests(TestCase):
    def _five_flagged(self):
        for i in range(5):
            sym = f"CAP{i}"
            _quote(sym, 99.2)
            _trade(sym, entry="100", initial_stop="99", stop="99",
                    target="103", cfg_name=f"cfg{i}")

    def test_per_pass_cap_bounds_the_model_calls(self):
        from brain.position_review_agent import review_open_positions_now
        self._five_flagged()
        built = []
        with _stub_agent(HOLD, recorder=built):
            result = review_open_positions_now(max_reviews=2)
        self.assertEqual(result["n_model_reviews"], 2)
        self.assertEqual(len(built), 2)
        self.assertEqual(result["n_skipped_capped"], 3)

    def test_capped_positions_say_why_on_their_own_row(self):
        from brain.position_review_agent import review_open_positions_now
        from brain.position_review_models import PositionReview
        self._five_flagged()
        with _stub_agent(HOLD):
            review_open_positions_now(max_reviews=1)
        capped = PositionReview.objects.filter(
            skipped_reason__icontains="per-pass cap")
        self.assertEqual(capped.count(), 4)

    def test_daily_cap_stops_the_spend(self):
        from brain.position_review_agent import review_open_positions_now
        self._five_flagged()
        with _stub_agent(HOLD):
            first = review_open_positions_now(max_reviews=5, daily_cap=2)
        self.assertEqual(first["n_model_reviews"], 2)

    def test_the_same_facts_are_not_paid_for_twice(self):
        from brain.position_review_agent import review_open_positions_now
        from brain.position_review_models import PositionReview
        _quote("DUP", 99.2)
        _trade("DUP", entry="100", initial_stop="99", stop="99", target="103")
        with _stub_agent(HOLD):
            first = review_open_positions_now()
            second = review_open_positions_now()
        self.assertEqual(first["n_model_reviews"], 1)
        self.assertEqual(second["n_model_reviews"], 0)
        self.assertEqual(second["n_skipped_same_facts"], 1)
        self.assertEqual(PositionReview.objects.count(), 1)

    def test_an_exhausted_ai_budget_still_runs_the_free_pass(self):
        """The deterministic half is the half that answers the question. It
        must not go dark because the day's tokens are gone."""
        from brain.position_review_agent import review_open_positions_now
        from brain.position_review_models import PositionReview
        _quote("BROKE", 99.2)
        _trade("BROKE", entry="100", initial_stop="99", stop="99", target="103")
        built = []
        with patch("ai_agents.spend.can_spend",
                    return_value=(False, "daily AI budget spent")):
            with _stub_agent(HOLD, recorder=built):
                result = review_open_positions_now()
        self.assertEqual(result["n_flagged"], 1)
        self.assertEqual(result["n_model_reviews"], 0)
        self.assertEqual(built, [])
        row = PositionReview.objects.get(symbol="BROKE")
        self.assertTrue(row.triggers, "the evidence is recorded regardless")
        self.assertIn("AI budget", row.skipped_reason)


# ══════════════════════════════════════════════════════════════════════════
# The record: evidence, clamping, hypothesis
# ══════════════════════════════════════════════════════════════════════════

class RecommendationIsPersistedWithEvidenceTests(TestCase):
    def test_the_row_carries_the_facts_that_produced_it(self):
        from brain.position_review_agent import review_open_positions_now
        from brain.position_review_models import PositionReview
        _quote("EVID", 99.2)
        _trade("EVID", entry="100", initial_stop="99", stop="99", target="103")
        with _stub_agent(EXIT):
            review_open_positions_now()
        row = PositionReview.objects.get(symbol="EVID")
        self.assertEqual(row.verdict, "exit")
        self.assertEqual(row.confidence, 0.72)
        self.assertTrue(row.triggers)
        self.assertIn("near_stop", row.trigger_codes)
        self.assertEqual(float(row.mark), 99.2)
        self.assertAlmostEqual(row.unrealized_r, -0.8, places=3)
        self.assertIsNotNone(row.r_at_review)
        self.assertEqual(row.facts["symbol"], "EVID")
        self.assertEqual(row.model_used, "claude-stub")
        self.assertEqual(float(row.cost_usd), 0.011)
        self.assertTrue(row.facts_hash)

    def test_a_hypothesis_is_posted_when_the_claim_is_gradeable(self):
        from brain.knowledge_models import Hypothesis
        from brain.position_review_agent import review_open_positions_now
        from brain.position_review_models import PositionReview
        from signals.models_control import RuleControl
        RuleControl.objects.create(rule_name="decayed_rule", status="paused")
        _quote("HYP", 101)
        _trade("HYP", entry="100", initial_stop="99", stop="99", target="103",
                rule_name="decayed_rule")
        with _stub_agent(EXIT):
            review_open_positions_now()
        row = PositionReview.objects.get(symbol="HYP")
        self.assertIn("rule_decayed", row.trigger_codes)
        self.assertIsNotNone(row.hypothesis_id)
        hyp = Hypothesis.objects.get(pk=row.hypothesis_id)
        self.assertEqual(hyp.source_agent, "position_reviewer")
        self.assertEqual(hyp.resolution_criteria["kind"], "rule_avg_r")
        self.assertEqual(hyp.resolution_criteria["rule_name"], "decayed_rule")
        # The criteria must name a resolver the platform actually owns, or
        # the claim is an opinion with a deadline.
        from brain.hypotheses import RESOLVERS
        self.assertIn(hyp.resolution_criteria["kind"], RESOLVERS)

    def test_hold_posts_no_hypothesis(self):
        from brain.position_review_agent import review_open_positions_now
        from brain.position_review_models import PositionReview
        from signals.models_control import RuleControl
        RuleControl.objects.create(rule_name="paused_rule", status="paused")
        _quote("NOHYP", 101)
        _trade("NOHYP", entry="100", initial_stop="99", stop="99",
                target="103", rule_name="paused_rule")
        with _stub_agent(HOLD):
            review_open_positions_now()
        row = PositionReview.objects.get(symbol="NOHYP")
        self.assertIsNone(row.hypothesis_id)


class ClampingTests(SimpleTestCase):
    def test_a_garbled_verdict_reads_as_hold_never_exit(self):
        from brain.position_review_agent import _clamp
        out = _clamp({"verdict": "SELL EVERYTHING", "confidence": 5},
                      facts=_facts(), dir_sign=1)
        self.assertEqual(out["verdict"], "hold")
        self.assertEqual(out["confidence"], 1.0)

    def test_a_widened_stop_is_discarded(self):
        """Widening the stop on a live position proposes MORE risk. It must
        never be renderable as advice next to a CLOSE button."""
        from brain.position_review_agent import clamp_suggested_stop
        facts = _facts(mark=101.0, stop=99.0)
        self.assertIsNone(clamp_suggested_stop(97.0, facts=facts, dir_sign=1))

    def test_a_tightened_stop_survives(self):
        from brain.position_review_agent import clamp_suggested_stop
        facts = _facts(mark=101.0, stop=99.0)
        self.assertEqual(clamp_suggested_stop(100.0, facts=facts, dir_sign=1),
                         100.0)

    def test_a_short_tightens_downward(self):
        from brain.position_review_agent import clamp_suggested_stop
        facts = _facts(mark=99.0, stop=101.0)
        self.assertEqual(clamp_suggested_stop(100.0, facts=facts, dir_sign=-1),
                         100.0)
        self.assertIsNone(clamp_suggested_stop(103.0, facts=facts, dir_sign=-1))

    def test_take_part_pct_only_survives_a_take_part_verdict(self):
        from brain.position_review_agent import _clamp
        out = _clamp({"verdict": "exit", "take_part_pct": 50},
                      facts=_facts(), dir_sign=1)
        self.assertIsNone(out["take_part_pct"])
        out = _clamp({"verdict": "take_part", "take_part_pct": 900},
                      facts=_facts(), dir_sign=1)
        self.assertEqual(out["take_part_pct"], 90)


# ══════════════════════════════════════════════════════════════════════════
# Surfacing + the read side the position card consumes
# ══════════════════════════════════════════════════════════════════════════

class NotificationTests(TestCase):
    def test_an_actionable_verdict_reaches_the_bell(self):
        from alerts.models import Notification
        from brain.position_review_agent import review_open_positions_now
        _quote("BELL", 99.2)
        _trade("BELL", entry="100", initial_stop="99", stop="99", target="103")
        with _stub_agent(EXIT):
            review_open_positions_now()
        n = Notification.objects.get(notification_type="portfolio")
        self.assertIn("BELL", n.title)
        self.assertIn("exit", n.title)
        self.assertEqual(n.data.get("kind"), "position_review")
        self.assertIn("nothing has been closed", n.body)

    def test_hold_does_not_ring_the_bell(self):
        from alerts.models import Notification
        from brain.position_review_agent import review_open_positions_now
        _quote("QUIETBELL", 99.2)
        _trade("QUIETBELL", entry="100", initial_stop="99", stop="99",
                target="103")
        with _stub_agent(HOLD):
            review_open_positions_now()
        self.assertEqual(Notification.objects.count(), 0)


class CardReadSideTests(TestCase):
    def test_latest_verdicts_keys_by_book_and_position_id(self):
        from brain.position_review import latest_verdicts
        from brain.position_review_agent import review_open_positions_now
        _quote("CARD", 99.2)
        t = _trade("CARD", entry="100", initial_stop="99", stop="99",
                    target="103")
        with _stub_agent(EXIT):
            review_open_positions_now()
        payload = latest_verdicts()
        key = f"bot:{t.id}"
        self.assertIn(key, payload)
        card = payload[key]
        self.assertEqual(card["verdict"], "exit")
        self.assertTrue(card["actionable"])
        self.assertTrue(card["triggers"])
        self.assertIn("unrealized_r", card)

    def test_unmeasurable_numbers_reach_the_card_as_none_not_zero(self):
        from brain.position_review import latest_verdicts
        from brain.position_review_agent import review_open_positions_now
        _trade("EMDASH")  # no quote at all
        with _stub_agent(EXIT):
            review_open_positions_now()
        card = list(latest_verdicts().values())[0]
        self.assertEqual(card["verdict"], "no_quote")
        self.assertIsNone(card["unrealized_r"])
        self.assertIsNone(card["confidence"])

    def test_a_position_with_nothing_to_say_is_absent(self):
        from brain.position_review import latest_verdicts
        from brain.position_review_agent import review_open_positions_now
        _quote("ABSENT", 101)
        _trade("ABSENT", entry="100", initial_stop="99", stop="99",
                target="103")
        with _stub_agent(HOLD):
            review_open_positions_now()
        self.assertEqual(latest_verdicts(), {})


# ══════════════════════════════════════════════════════════════════════════
# Grading — the reviewer earns a track record
# ══════════════════════════════════════════════════════════════════════════

class GradingTests(TestCase):
    def _reviewed(self, symbol="GRADE"):
        from brain.position_review_agent import review_open_positions_now
        from brain.position_review_models import PositionReview
        _quote(symbol, 99.2)
        t = _trade(symbol, entry="100", initial_stop="99", stop="99",
                    target="103")
        with _stub_agent(EXIT):
            review_open_positions_now()
        return t, PositionReview.objects.get(symbol=symbol)

    def test_an_open_position_is_not_graded_yet(self):
        from brain.position_review_agent import grade_due_reviews
        self._reviewed("OPENSTILL")
        out = grade_due_reviews()
        self.assertEqual(out["still_pending"], 1)

    def test_exit_was_right_when_holding_cost_r(self):
        from brain.position_review_agent import grade_due_reviews
        from brain.position_review_models import PositionReview
        t, review = self._reviewed("RIGHT")
        t.status = "CLOSED"
        # The call was made at -0.8R; the position then gapped through the
        # stop and booked -1.5R. Holding cost 0.7R.
        t.realized_r = -1.5
        t.closed_at = timezone.now()
        t.save()
        grade_due_reviews()
        review.refresh_from_db()
        self.assertEqual(review.graded_outcome, PositionReview.OUTCOME_RIGHT)
        self.assertEqual(review.r_at_close, -1.5)

    def test_exit_was_wrong_when_holding_paid(self):
        from brain.position_review_agent import grade_due_reviews
        from brain.position_review_models import PositionReview
        t, review = self._reviewed("WRONG")
        t.status = "CLOSED"
        t.realized_r = 2.0
        t.closed_at = timezone.now()
        t.save()
        grade_due_reviews()
        review.refresh_from_db()
        self.assertEqual(review.graded_outcome, PositionReview.OUTCOME_WRONG)

    def test_a_difference_inside_the_noise_band_scores_nobody(self):
        from brain.position_review_agent import grade_due_reviews
        from brain.position_review_models import PositionReview
        t, review = self._reviewed("NOISE")
        t.status = "CLOSED"
        t.realized_r = -0.9          # 0.1R from the -0.8R call
        t.closed_at = timezone.now()
        t.save()
        grade_due_reviews()
        review.refresh_from_db()
        self.assertEqual(review.graded_outcome,
                         PositionReview.OUTCOME_UNRESOLVABLE)
        self.assertIn("noise band", review.grading_notes)

    def test_a_close_with_no_r_is_unresolvable_not_wrong(self):
        """A measurement failure must never be charged to the agent."""
        from brain.position_review_agent import grade_due_reviews
        from brain.position_review_models import PositionReview
        t, review = self._reviewed("NOR")
        t.status = "CLOSED"
        t.realized_r = None
        t.closed_at = timezone.now()
        t.save()
        grade_due_reviews()
        review.refresh_from_db()
        self.assertEqual(review.graded_outcome,
                         PositionReview.OUTCOME_UNRESOLVABLE)


# ══════════════════════════════════════════════════════════════════════════
# The component gate + the beat entry
# ══════════════════════════════════════════════════════════════════════════

class ComponentGateTests(TestCase):
    def test_the_task_is_registered_in_default_components(self):
        """A @guarded_task whose component row nobody seeds silently no-ops
        forever — registration is part of the task, not an ops afterthought."""
        from core.platform_control import DEFAULT_COMPONENTS
        self.assertIn("agent_position_review",
                      {c["key"] for c in DEFAULT_COMPONENTS})

    def test_the_beat_entry_points_at_the_registered_task(self):
        from config.celery import app
        entry = app.conf.beat_schedule["sauron-position-review"]
        self.assertEqual(entry["task"], "brain.tasks.run_position_review")

    def test_a_disabled_component_never_runs_the_watcher(self):
        from core.platform_control import PlatformComponent
        from brain.tasks import run_position_review
        PlatformComponent.objects.create(
            key="platform_master", name="master", category="system",
            is_enabled=True)
        # agent_position_review deliberately absent — the exact state a
        # forgotten DEFAULT_COMPONENTS entry would leave forever.
        result = run_position_review()
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "agent_position_review_disabled")

    def test_the_master_switch_outranks_the_component(self):
        from core.platform_control import PlatformComponent
        from brain.tasks import run_position_review
        PlatformComponent.objects.create(
            key="platform_master", name="master", category="system",
            is_enabled=False)
        PlatformComponent.objects.create(
            key="agent_position_review", name="watcher", category="agent",
            is_enabled=True)
        result = run_position_review()
        self.assertEqual(result["reason"], "platform_disabled")

    def test_seeding_registers_the_component(self):
        from core.platform_control import PlatformComponent, seed_components
        seed_components()
        comp = PlatformComponent.objects.get(key="agent_position_review")
        self.assertFalse(comp.is_enabled, "must be opt-in, like every agent")


# ══════════════════════════════════════════════════════════════════════════
# The hard rule: it proposes, it never acts
# ══════════════════════════════════════════════════════════════════════════

class NothingIsEverAutoClosedTests(TestCase):
    def test_an_exit_verdict_leaves_the_position_open(self):
        from brain.position_review_agent import review_open_positions_now
        _quote("KEEP", 99.2)
        t = _trade("KEEP", entry="100", initial_stop="99", stop="99",
                    target="103")
        with _stub_agent(EXIT):
            review_open_positions_now()
        t.refresh_from_db()
        self.assertEqual(t.status, "OPEN")
        self.assertIsNone(t.closed_at)
        self.assertIsNone(t.exit_price)
        self.assertEqual(t.pnl, Decimal("0"))

    def test_a_tighten_verdict_does_not_move_the_real_stop(self):
        """The suggested stop is a PROPOSAL on the review row. Writing it
        onto the trade would be the module acting on live capital."""
        from brain.position_review_agent import review_open_positions_now
        from brain.position_review_models import PositionReview
        _quote("STOPMOVE", 101)
        t = _trade("STOPMOVE", entry="100", initial_stop="99", stop="99",
                    target="101.1")
        tighten = dict(EXIT, verdict="tighten", suggested_stop=100.5)
        with _stub_agent(tighten):
            review_open_positions_now()
        t.refresh_from_db()
        self.assertEqual(t.stop_loss, Decimal("99.00000000"))
        row = PositionReview.objects.get(symbol="STOPMOVE")
        self.assertEqual(float(row.suggested_stop), 100.5)


class NoCloseMachineryIsReachableTests(SimpleTestCase):
    """Source-level guard. The behavioural test above proves this pass did
    not close anything; this one proves no future edit can, without a
    reviewer noticing the test that says it must not."""

    FORBIDDEN = ("execute_close", "_close_trade", "retry_trade_close",
                 "kill_switch", "market_order", "_submit_close_order")

    def _source(self, module_name):
        import importlib
        import pathlib
        mod = importlib.import_module(module_name)
        return pathlib.Path(mod.__file__).read_text(encoding="utf-8")

    def test_the_watcher_cannot_close_anything(self):
        for name in ("brain.position_review", "brain.position_review_agent"):
            src = self._source(name)
            for token in self.FORBIDDEN:
                self.assertNotIn(
                    f"{token}(", src,
                    f"{name} calls {token}() — this slice PROPOSES, the "
                    f"operator acts through dashboard/views_close.py")
