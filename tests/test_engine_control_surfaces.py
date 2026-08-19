"""The engine's control surfaces, held to what they claim.

Four defects, one shape: a control surface reported a number or a decision that
did not describe what the engine was actually doing.

  1. `status="active"` is not the population the engine runs. `reduced` is a
     running state, and a `paused` rule whose `paused_until` has elapsed is
     running again — `is_effectively_active()` computes that expiry on the fly
     while nothing writes the column back. The meta-allocator filtered on the
     raw column, so a rule that served its pause was frozen out of every
     rebalance from then on, trading forever at whatever `allocator_weight` it
     carried the day it was paused.

  2. `scan_all_setups` counted every pair it attempted and every flag it wrote,
     and nothing in between. A gate deliberately drops most of a setup's
     universe before any evidence is read; on that dict it was indistinguishable
     from an evaluator that had started raising.

  3. Approval can be REFUSED — the stored conditions are re-validated at arming
     time — and the view discarded the boolean, so the operator got a redirect
     to a page that still showed the proposal pending.

  4. The operator's own setup form wrote raw JSON straight into an ARMED row.
     The generated path was validated twice; this one, zero times.

Run with:  python manage.py test tests.test_engine_control_surfaces
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone


# ── Fixtures ───────────────────────────────────────────────────────────────

def _instrument(symbol, asset_class="crypto"):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class},
    )
    return inst


def _closed_signals(rule_name, rs):
    """N closed, graded signals for one rule — the allocator's only input."""
    from signals.models import Signal
    inst = _instrument(f"CS_{rule_name}")
    for i, r in enumerate(rs):
        Signal.objects.create(
            instrument=inst, signal_type="composite", direction="bullish",
            urgency="medium", title="t", description="t", rule_name=rule_name,
            score=0.7, sub_scores={}, price_at_signal=Decimal("100"),
            suggested_entry=Decimal("100"), suggested_stop=Decimal("95"),
            suggested_target=Decimal("110"), risk_reward_ratio=2.0,
            is_active=False, outcome="hit_target" if r > 0 else "stopped_out",
            realized_r=r, expired_at=timezone.now() - timedelta(days=i),
        )


def _set_component(key, enabled):
    from core.platform_control import PlatformComponent
    c, _ = PlatformComponent.objects.get_or_create(
        key=key, defaults={"name": key, "category": "system"})
    c.is_enabled = enabled
    c.save()


def _messages(response):
    return [str(m) for m in get_messages(response.wsgi_request)]


# ── 1. The running-rules predicate ─────────────────────────────────────────

class RunningRulesPredicateTests(TestCase):
    """`RuleControl.running_q()` is an ORM restatement of a Python method, and
    the two are only useful if they cannot drift."""

    def _rules(self, now):
        from signals.models_control import RuleControl
        RuleControl.objects.create(rule_name="r_active", status="active")
        RuleControl.objects.create(rule_name="r_reduced", status="reduced",
                                   weight_multiplier=0.5)
        RuleControl.objects.create(rule_name="r_paused_live", status="paused",
                                   paused_until=now + timedelta(days=3))
        RuleControl.objects.create(rule_name="r_paused_expired", status="paused",
                                   paused_until=now - timedelta(days=1))
        RuleControl.objects.create(rule_name="r_paused_forever", status="paused",
                                   paused_until=None)

    def test_the_filter_and_the_method_agree_on_every_state(self):
        from signals.models_control import RuleControl
        now = timezone.now()
        self._rules(now)
        by_filter = set(RuleControl.objects.filter(RuleControl.running_q(now))
                        .values_list("rule_name", flat=True))
        by_method = {r.rule_name for r in RuleControl.objects.all()
                     if r.is_effectively_active(now)}
        self.assertEqual(by_filter, by_method)
        self.assertEqual(
            by_filter, {"r_active", "r_reduced", "r_paused_expired"},
            msg="reduced is a running state, and a served pause is running again",
        )

    def test_an_expired_pause_is_running_even_though_the_column_still_says_paused(self):
        """The database is never written back on expiry, so the column and the
        engine disagree by design. Anything counting rules has to know that."""
        from signals.models_control import RuleControl
        now = timezone.now()
        self._rules(now)
        rule = RuleControl.objects.get(rule_name="r_paused_expired")
        self.assertEqual(rule.status, RuleControl.STATUS_PAUSED)
        self.assertTrue(rule.is_effectively_active(now))

    def test_the_context_processor_predicate_matches_the_model_one(self):
        """`core.context_processors.running_rules_q` was added the same wave and
        states the same predicate. Two copies of a rule are one rule until they
        are not; this fails the moment they diverge."""
        from core.context_processors import running_rules_q
        from signals.models_control import RuleControl
        now = timezone.now()
        self._rules(now)
        self.assertEqual(
            set(RuleControl.objects.filter(running_rules_q(now))
                .values_list("rule_name", flat=True)),
            set(RuleControl.objects.filter(RuleControl.running_q(now))
                .values_list("rule_name", flat=True)),
        )


class AllocatorRunningRuleTests(TestCase):
    """The freeze: `_collect_rule_stats` dropped every rule whose status column
    was not literally "active", and `apply_allocation` guarded on the same
    column, so a served pause was excluded from the risk budget permanently."""

    def setUp(self):
        from core.platform_control import seed_components
        seed_components()
        self.user = User.objects.create_user(username="alloc_hq", is_superuser=True)

    def test_a_rule_whose_pause_expired_is_budgeted_again(self):
        from signals.meta_allocator import _collect_rule_stats
        from signals.models_control import RuleControl
        RuleControl.objects.create(
            rule_name="thawed", status=RuleControl.STATUS_PAUSED,
            paused_until=timezone.now() - timedelta(days=1),
            weight_multiplier=0.0, allocator_weight=2.7,
        )
        _closed_signals("thawed", [1.0, -0.5, 0.8, 1.2, -0.3, 0.9])
        self.assertIn("thawed", _collect_rule_stats(180))

    def test_a_reduced_rule_is_budgeted_because_it_is_still_trading(self):
        from signals.meta_allocator import _collect_rule_stats
        from signals.models_control import RuleControl
        RuleControl.objects.create(rule_name="smaller",
                                   status=RuleControl.STATUS_REDUCED,
                                   weight_multiplier=0.5)
        _closed_signals("smaller", [1.0, -0.5, 0.8, 1.2, -0.3, 0.9])
        self.assertIn("smaller", _collect_rule_stats(180))

    def test_a_pause_still_in_force_is_not_budgeted(self):
        """The narrower half of the predicate has to keep biting, or the fix
        would have handed the allocator the rules the admin took off the book."""
        from signals.meta_allocator import _collect_rule_stats
        from signals.models_control import RuleControl
        RuleControl.objects.create(
            rule_name="frozen", status=RuleControl.STATUS_PAUSED,
            paused_until=timezone.now() + timedelta(days=10),
        )
        _closed_signals("frozen", [1.0, -0.5, 0.8, 1.2, -0.3, 0.9])
        self.assertNotIn("frozen", _collect_rule_stats(180))

    def test_apply_writes_a_budget_to_a_rule_whose_pause_expired(self):
        from signals.meta_allocator import apply_allocation, propose_allocation
        from signals.models_control import RuleControl
        _set_component("meta_allocator_mode_live", True)
        RuleControl.objects.create(
            rule_name="thawed", status=RuleControl.STATUS_PAUSED,
            paused_until=timezone.now() - timedelta(days=1),
            allocator_weight=2.7,
        )
        RuleControl.objects.create(rule_name="other", status="active",
                                   allocator_weight=1.0)
        _closed_signals("thawed", [1.0] * 6)
        _closed_signals("other", [0.5] * 6)
        alloc = propose_allocation()
        apply_allocation(alloc.id, self.user)
        self.assertNotEqual(
            RuleControl.objects.get(rule_name="thawed").allocator_weight, 2.7,
            msg="the stale weight it carried into the pause must be re-budgeted",
        )

    def test_the_uniform_denominator_counts_every_running_rule(self):
        """`_to_allocator_multipliers` divides by 1/N. Dropping a live rule from
        N over-allocates the whole book, not just that rule."""
        from signals.meta_allocator import _collect_rule_stats
        from signals.models_control import RuleControl
        RuleControl.objects.create(rule_name="a", status="active")
        RuleControl.objects.create(rule_name="b", status="reduced",
                                   weight_multiplier=0.5)
        RuleControl.objects.create(
            rule_name="c", status="paused",
            paused_until=timezone.now() - timedelta(hours=1))
        for name in ("a", "b", "c"):
            _closed_signals(name, [1.0, -0.4, 0.7, 0.9, -0.2, 1.1])
        self.assertEqual(len(_collect_rule_stats(180)), 3)


# ── 2. The scan result an operator sees ────────────────────────────────────

class ScanResultAccountingTests(TestCase):
    """Every pair counted in `evaluations` is accounted for by name."""

    def _setup(self, conditions, *, name="acct", asset_classes=None,
               min_match_score=0.6):
        from signals.models_opportunity import OpportunitySetup
        return OpportunitySetup.objects.create(
            name=name, description="", direction="bullish",
            asset_classes=asset_classes or [], conditions=conditions,
            min_match_score=min_match_score, suggested_horizon_days=5,
            sizing={"stop_pct": 2.0, "target_rr": 2.0}, is_active=True,
        )

    def test_a_gated_pair_is_counted_as_gate_skipped_not_as_a_silent_miss(self):
        from signals.opportunity_scanner import scan_all_setups
        self._setup([{"kind": "quote_currency",
                      "params": {"currency": "USD"}, "gate": True},
                     {"kind": "price_pattern",
                      "params": {"pattern": "above_ma", "ma_period": 5},
                      "weight": 1.0}],
                    asset_classes=["forex"])
        _instrument("EURUSD", asset_class="forex")
        _instrument("USDJPY", asset_class="forex")
        result = scan_all_setups()
        self.assertEqual(result["gate_skipped"], 1)
        self.assertEqual(result["scored"], 1)

    def test_the_counters_account_for_every_evaluation(self):
        from signals.opportunity_scanner import scan_all_setups
        self._setup([{"kind": "quote_currency",
                      "params": {"currency": "USD"}, "gate": True}],
                    asset_classes=["forex"])
        _instrument("GBPUSD", asset_class="forex")
        _instrument("USDCHF", asset_class="forex")
        _instrument("BTCUSD", asset_class="crypto")   # outside asset_classes
        result = scan_all_setups()
        self.assertEqual(
            result["scored"] + result["asset_class_skipped"]
            + result["gate_skipped"] + result["errors"],
            result["evaluations"],
        )
        self.assertEqual(result["asset_class_skipped"], 1)
        self.assertEqual(result["gate_skipped"], 1)

    def test_an_evaluator_that_raises_is_counted_not_only_logged(self):
        """The exception is caught inside `scan_setup` and scored 0, which is
        right — one broken source must not void a composite — but it leaves the
        score quietly understated with only a log line to say so."""
        from signals import opportunity_scanner as scanner

        def _boom(params, instrument, now):
            raise RuntimeError("data source down")

        scanner.register_kind("acct_explodes", _boom, params=())
        self.addCleanup(scanner.EVALUATOR_REGISTRY.pop, "acct_explodes", None)
        self.addCleanup(scanner.PARAM_KEYS.pop, "acct_explodes", None)
        self.addCleanup(scanner.PARAM_CHOICES.pop, "acct_explodes", None)
        self.addCleanup(scanner.ACCEPTS_AS_OF.pop, "acct_explodes", None)

        self._setup([{"kind": "acct_explodes", "params": {}, "weight": 1.0}])
        _instrument("EXPL1")
        result = scanner.scan_all_setups()
        self.assertEqual(result["evaluator_errors"], 1)
        self.assertEqual(result["matches"], 0)

    def test_matches_is_still_the_number_of_flags_written(self):
        """The counters are additions; the number that was already there has to
        keep meaning what it meant."""
        from market_data.models import LiveQuote
        from signals.models import OpportunityFlag
        from signals.opportunity_scanner import scan_all_setups
        self._setup([{"kind": "quote_currency",
                      "params": {"currency": "USD"}, "weight": 1.0}],
                    asset_classes=["forex"], min_match_score=0.5)
        inst = _instrument("EURUSD", asset_class="forex")
        LiveQuote.objects.create(instrument=inst, last=Decimal("1.09"),
                                 source="test")
        _instrument("USDJPY", asset_class="forex")
        result = scan_all_setups()
        self.assertEqual(result["matches"], 1)
        self.assertEqual(OpportunityFlag.objects.count(), 1)
        # Both pairs reached the composite — this condition is a scoring leg,
        # not a gate, so USDJPY was scored 0 rather than skipped.
        self.assertEqual(result["scored"], 2)
        self.assertEqual(result["gate_skipped"], 0)

    def test_the_new_keys_do_not_restate_a_healthy_scan_as_a_warning(self):
        """`judge_result` reads a top-level `skipped` as "not configured" and
        treats parsed/attempted/stored/written/saved/fetched as work counts —
        either would turn a scan that legitimately matched nothing red."""
        from core.task_gate import judge_result
        from signals.opportunity_scanner import scan_all_setups
        result = scan_all_setups()
        status, _msg = judge_result(result)
        self.assertEqual(status, "success")
        WORK_AND_DONE = {"parsed", "attempted", "stored", "written", "saved",
                         "fetched", "observations_saved", "bars_saved",
                         "articles", "skipped"}
        self.assertEqual(set(result) & WORK_AND_DONE, set())

    def test_a_scan_with_gate_skips_is_still_success(self):
        from core.task_gate import judge_result
        from signals.opportunity_scanner import scan_all_setups
        self._setup([{"kind": "quote_currency",
                      "params": {"currency": "USD"}, "gate": True}],
                    asset_classes=["forex"])
        _instrument("USDJPY", asset_class="forex")
        result = scan_all_setups()
        self.assertEqual(result["gate_skipped"], 1)
        self.assertEqual(judge_result(result)[0], "success")


# ── 3. Approval feedback ───────────────────────────────────────────────────

class ApprovalFeedbackTests(TestCase):
    """A refusal the operator cannot see is a button that does nothing."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="gen_admin", password="x", is_staff=True, is_superuser=True)
        self.client.force_login(self.user)

    def _proposal(self, conditions):
        from brain.generator_models import GeneratedSetupProposal
        from signals.models_opportunity import OpportunitySetup
        setup = OpportunitySetup.objects.create(
            name="generated_test_row", description="", direction="bullish",
            asset_classes=["stock"], conditions=conditions,
            min_match_score=0.6, suggested_horizon_days=5,
            sizing={"stop_pct": 2.0, "target_rr": 2.0}, is_active=False,
        )
        return GeneratedSetupProposal.objects.create(
            proposed_name=setup.name, direction="bullish",
            asset_classes=["stock"], conditions=conditions,
            min_match_score=0.6, suggested_horizon_days=5, setup=setup,
        )

    def test_a_refused_approval_tells_the_operator_why(self):
        """Every PENDING row in a live DB was validated under the old kind-only
        rule, so this is the first click, not a hypothetical future one."""
        proposal = self._proposal(
            [{"kind": "volatility_regime", "params": {"regime": "low"},
              "weight": 1.0}])
        resp = self.client.post(
            reverse("generated_approve", args=[proposal.id]))
        self.assertEqual(resp.status_code, 302)
        msgs = _messages(resp)
        self.assertTrue(msgs, msg="the refusal produced no operator-visible message")
        self.assertIn("regime", " ".join(msgs))
        proposal.setup.refresh_from_db()
        self.assertFalse(proposal.setup.is_active)

    def test_a_successful_approval_says_so_too(self):
        proposal = self._proposal(
            [{"kind": "price_pattern",
              "params": {"pattern": "above_ma", "ma_period": 20},
              "weight": 1.0}])
        resp = self.client.post(
            reverse("generated_approve", args=[proposal.id]))
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(_messages(resp))
        proposal.setup.refresh_from_db()
        self.assertTrue(proposal.setup.is_active)

    def test_the_page_that_receives_the_redirect_renders_the_message(self):
        """base.html has no messages region, so a bare `messages.error` would
        have been just as invisible as the discarded boolean."""
        proposal = self._proposal(
            [{"kind": "volatility_regime", "params": {"regime": "low"},
              "weight": 1.0}])
        self.client.post(reverse("generated_approve", args=[proposal.id]))
        page = self.client.get(reverse("generated_dashboard"))
        self.assertContains(page, "Not armed")

    def test_the_blocker_names_the_reason_the_approve_call_returns_false(self):
        from brain.strategy_generator import approval_blocker, approve_proposal
        proposal = self._proposal(
            [{"kind": "volatility_regime", "params": {"regime": "low"},
              "weight": 1.0}])
        blocker = approval_blocker(proposal)
        self.assertTrue(blocker)
        self.assertFalse(approve_proposal(proposal, reviewed_by="me"))

    def test_an_already_decided_proposal_is_refused_with_its_state(self):
        from brain.generator_models import GeneratedSetupProposal
        from brain.strategy_generator import approval_blocker
        proposal = self._proposal(
            [{"kind": "price_pattern",
              "params": {"pattern": "above_ma"}, "weight": 1.0}])
        proposal.status = GeneratedSetupProposal.STATUS_REJECTED
        proposal.save(update_fields=["status"])
        self.assertIn("rejected", approval_blocker(proposal))


# ── 4. The operator's own setup form ───────────────────────────────────────

class OperatorSetupFormGuardTests(TestCase):
    """The hand-authored path was validated zero times and armed instantly,
    while the generated path was validated twice and landed as a draft."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="hq_admin", password="x", is_staff=True, is_superuser=True)
        self.client.force_login(self.user)
        self.url = reverse("hq_create_opportunity_setup")

    def _post(self, **overrides):
        import json
        payload = {
            "name": "operator_setup",
            "direction": "bullish",
            "description": "",
            "conditions": json.dumps(
                [{"kind": "price_pattern",
                  "params": {"pattern": "above_ma", "ma_period": 20}}]),
            "asset_classes": json.dumps(["stock"]),
            "sizing": json.dumps({"stop_pct": 2.0, "target_rr": 2.0}),
            "min_match_score": "0.7",
            "suggested_horizon_days": "5",
        }
        payload.update(overrides)
        return self.client.post(self.url, payload)

    def _count(self):
        from signals.models_opportunity import OpportunitySetup
        return OpportunitySetup.objects.count()

    def test_a_param_key_no_evaluator_reads_is_rejected(self):
        """`{"regime": "low"}` on volatility_regime: the key is never read, the
        evaluator defaults to direction="above", and the condition then scores
        the exact inversion of what was typed."""
        import json
        resp = self._post(conditions=json.dumps(
            [{"kind": "volatility_regime", "params": {"regime": "low"}}]))
        self.assertEqual(self._count(), 0)
        self.assertIn("regime", " ".join(_messages(resp)))

    def test_a_value_outside_the_vocabulary_is_rejected(self):
        """On a two-branch evaluator an unrecognised direction does not go
        quiet — it selects the ELSE branch."""
        import json
        resp = self._post(conditions=json.dumps(
            [{"kind": "volatility_regime",
              "params": {"direction": "sideways", "threshold_pct": 2.0}}]))
        self.assertEqual(self._count(), 0)
        self.assertIn("sideways", " ".join(_messages(resp)))

    def test_an_unregistered_kind_is_rejected(self):
        import json
        resp = self._post(conditions=json.dumps(
            [{"kind": "vibes_check", "params": {}}]))
        self.assertEqual(self._count(), 0)
        self.assertIn("vibes_check", " ".join(_messages(resp)))

    def test_a_dead_sizing_key_is_rejected(self):
        """`target_pct` is discarded and the target falls back to 2R."""
        import json
        resp = self._post(sizing=json.dumps({"stop_pct": 2.0, "target_pct": 4.0}))
        self.assertEqual(self._count(), 0)
        self.assertIn("target_pct", " ".join(_messages(resp)))

    def test_out_of_range_bounds_are_rejected_server_side(self):
        """The form's min/max attributes are client-side only."""
        resp = self._post(min_match_score="1.4")
        self.assertEqual(self._count(), 0)
        self.assertIn("1.4", " ".join(_messages(resp)))
        resp = self._post(suggested_horizon_days="900")
        self.assertEqual(self._count(), 0)
        self.assertIn("900", " ".join(_messages(resp)))

    def test_a_valid_setup_is_created_but_not_armed(self):
        from signals.models_opportunity import OpportunitySetup
        resp = self._post()
        setup = OpportunitySetup.objects.get(name="operator_setup")
        self.assertFalse(
            setup.is_active,
            msg=("every other authoring path lands disarmed; this one used to "
                 "hard-code is_active=True and scan on the next pass"))
        self.assertIn("INACTIVE", " ".join(_messages(resp)))

    def test_an_unarmed_setup_is_not_scanned(self):
        from signals.opportunity_scanner import scan_all_setups
        self._post()
        _instrument("FORMTEST", asset_class="stock")
        self.assertEqual(scan_all_setups()["setups_scanned"], 0)

    def test_the_validator_is_the_same_one_the_generated_path_uses(self):
        """Two guards would be two vocabularies. The point of the repair is that
        there is exactly one."""
        import dashboard.views_admin_hq as hq
        import inspect
        source = inspect.getsource(hq.hq_create_opportunity_setup)
        self.assertIn("validate_conditions", source)
        self.assertIn("unknown_sizing_keys", source)
