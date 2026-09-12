"""Why a setup never fires — the diagnostic, the command, the page.

Sixteen of twenty-six research rules on this platform had never produced one
gradable signal in their life (2026-09-12), and a setup that never matched was
SILENT: nothing said whether its conditions were too strict, its data was
missing, or it missed its threshold by 0.02. These tests pin the distinction
that ends that silence — "evaluated and refused" versus "could not evaluate" —
and the one property the whole instrument rests on: it writes NOTHING.

Every fixture below builds real OpportunitySetup rows over real PriceData, so
the scanner's own arithmetic runs. A diagnostic tested against a stubbed
scorer would be a test of the stub.

Run with:  python manage.py test tests.test_setup_diagnostics
"""
from datetime import timedelta
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

User = get_user_model()


def _instrument(symbol, asset_class):
    from instruments.models import Instrument
    return Instrument.objects.create(symbol=symbol, name=symbol,
                                     asset_class=asset_class, is_active=True)


def _bars(instrument, n=40, *, timeframe="1d", start=100.0, step=1.0):
    """`n` ascending closes ending today — so breakout_high matches, breakout_low
    does not, and `below_ma` evaluates and refuses. Ascending is deliberate:
    it makes every price verdict deterministic instead of data-dependent."""
    from market_data.models import PriceData
    now = timezone.now()
    rows = []
    for i in range(n):
        price = Decimal(str(round(start + i * step, 8)))
        rows.append(PriceData(
            instrument=instrument, timeframe=timeframe,
            timestamp=now - timedelta(days=(n - i)),
            open=price, high=price, low=price, close=price,
            volume=1000, source="test"))
    PriceData.objects.bulk_create(rows)


def _setup(name, conditions, *, classes, threshold, active=True):
    from signals.models import OpportunitySetup
    return OpportunitySetup.objects.create(
        name=name, direction="bullish", asset_classes=list(classes),
        conditions=conditions, min_match_score=threshold, is_active=active,
        suggested_horizon_days=5, sizing={"stop_pct": 2.0, "target_rr": 2.0})


def _pp(pattern, **params):
    return {"kind": "price_pattern", "weight": 1.0,
            "params": {"pattern": pattern, **params}}


class _Fixture(TestCase):
    """One universe: a commodity with forty daily bars, a crypto with none."""

    def setUp(self):
        cache.clear()
        self.gold = _instrument("XAUUSD", "commodity")
        _bars(self.gold, 40)
        # Four-hour bars ONLY. `_recent_closes` filters timeframe="1d", so
        # every price condition on this instrument cannot evaluate — which is
        # exactly the live symptom: crypto with no daily bars.
        self.eth = _instrument("ETHUSD", "crypto")
        _bars(self.eth, 6, timeframe="4h")

    def _diag(self, **kw):
        from signals.setup_diagnostics import diagnose_setups
        return diagnose_setups(**kw)

    def _row(self, rep, name):
        return next(r for r in rep["setups"] if r["name"] == name)


class VerdictTests(_Fixture):

    def test_a_setup_that_matches_reads_fires(self):
        s = _setup("fires_one", [_pp("breakout_high", lookback=5)],
                   classes=["commodity"], threshold=0.5)
        row = self._row(self._diag(setups=[s]), "fires_one")
        self.assertEqual(row["verdict"], "fires")
        self.assertEqual(row["n_matched"], 1)
        self.assertEqual(row["best_instrument"], "XAUUSD")

    def test_a_setup_short_of_its_threshold_reads_near_and_names_both_numbers(self):
        """One leg fires at 1.0, one refuses at 0.0 — composite 0.50 against a
        0.55 threshold, which is inside the default 0.10 near-miss band."""
        s = _setup("near_one",
                   [_pp("breakout_high", lookback=5),
                    _pp("breakout_low", lookback=5)],
                   classes=["commodity"], threshold=0.55)
        row = self._row(self._diag(setups=[s]), "near_one")
        self.assertEqual(row["verdict"], "near")
        self.assertEqual(row["n_near_miss"], 1)
        self.assertEqual(row["composite_max"], 0.5)
        # The sentence has to carry BOTH numbers, or it tells an operator
        # there is a gap without telling them how wide it is.
        self.assertIn("0.50", row["verdict_detail"])
        self.assertIn("0.55", row["verdict_detail"])

    def test_a_setup_whose_conditions_all_evaluate_and_refuse_reads_strict(self):
        s = _setup("strict_one", [_pp("below_ma", ma_period=10)],
                   classes=["commodity"], threshold=0.7)
        rep = self._diag(setups=[s])
        row = self._row(rep, "strict_one")
        self.assertEqual(row["verdict"], "strict")
        self.assertEqual(row["conditions"][0]["n_no_match"], 1)
        self.assertEqual(row["conditions"][0]["n_unevaluable"], 0)

    def test_a_setup_whose_condition_cannot_evaluate_reads_blind_and_names_it(self):
        """The crypto has no 1d bars at all. The sentence must name the
        condition AND the count — "it did not match" would be a lie about a
        leg that never looked."""
        s = _setup("blind_one",
                   [_pp("above_ma", ma_period=10),
                    {"kind": "news_volume", "weight": 1.0,
                     "params": {"min_count": 1, "lookback_days": 2}}],
                   classes=["crypto"], threshold=0.7)
        row = self._row(self._diag(setups=[s]), "blind_one")
        self.assertEqual(row["verdict"], "blind")
        self.assertIn("price_pattern", row["verdict_detail"])
        self.assertIn("1 of 1", row["verdict_detail"])
        self.assertIn("could not evaluate", row["verdict_detail"])

    def test_a_setup_with_no_instrument_in_its_classes_reads_empty(self):
        s = _setup("empty_one", [_pp("breakout_high", lookback=5)],
                   classes=["bond"], threshold=0.5)
        row = self._row(self._diag(setups=[s]), "empty_one")
        self.assertEqual(row["verdict"], "empty")
        self.assertEqual(row["n_evaluated"], 0)
        self.assertIn("bond", row["verdict_detail"])

    def test_unevaluable_is_counted_apart_from_no_match(self):
        """THE distinction. On the same instrument, one leg cannot evaluate
        (no 1d bars) and one evaluates and refuses (no news rows). They must
        land in two different counters, or the operator cannot tell a dead
        setup from a strict one."""
        s = _setup("blind_two",
                   [_pp("above_ma", ma_period=10),
                    {"kind": "news_volume", "weight": 1.0,
                     "params": {"min_count": 1, "lookback_days": 2}}],
                   classes=["crypto"], threshold=0.7)
        row = self._row(self._diag(setups=[s]), "blind_two")
        price_leg, news_leg = row["conditions"]
        self.assertEqual((price_leg["n_unevaluable"], price_leg["n_no_match"]),
                         (1, 0))
        self.assertEqual((news_leg["n_unevaluable"], news_leg["n_no_match"]),
                         (0, 1))
        self.assertTrue(price_leg["sample_reason"])
        self.assertFalse(news_leg["sample_reason"])


class PurityTests(_Fixture):

    def test_the_pass_writes_no_flag_and_no_signal(self):
        """The one property everything else rests on. The `fires` setup is in
        the population on purpose: a pass that writes only when nothing
        matched would pass a weaker version of this test."""
        from signals.models import OpportunityFlag, Signal

        _setup("fires_two", [_pp("breakout_high", lookback=5)],
               classes=["commodity"], threshold=0.5)
        _setup("blind_three", [_pp("above_ma", ma_period=10)],
               classes=["crypto"], threshold=0.7)
        before = (OpportunityFlag.objects.count(), Signal.objects.count())
        rep = self._diag()
        after = (OpportunityFlag.objects.count(), Signal.objects.count())
        self.assertEqual(before, after)
        # And it really did reach a match — otherwise the counts prove nothing.
        self.assertEqual(rep["by_verdict"]["fires"], 1)
        self.assertGreaterEqual(rep["seconds"], 0.0)


class GradingAuditTests(TestCase):

    def setUp(self):
        cache.clear()
        self.inst = _instrument("EURUSD", "forex")

    def _signal(self, rule, **kw):
        from signals.models import Signal
        fields = dict(instrument=self.inst, signal_type="composite",
                      direction="bullish", urgency="medium", title="t",
                      description="d", rule_name=rule, score=0.8,
                      price_at_signal=Decimal("1"), is_active=True)
        fields.update(kw)
        return Signal.objects.create(**fields)

    def test_graded_ungraded_and_no_outcome_land_in_three_counters(self):
        """A signal that closes with no outcome, and one that closes with an
        outcome and no realized_r, are BOTH invisible to the promotion ladder
        and to every evidence lane — and they are invisible for different
        reasons, so they are counted apart."""
        from signals.setup_diagnostics import diagnose_grading

        self._signal("r_graded", is_active=False, outcome="hit_target",
                     realized_r=1.5)
        self._signal("r_ungraded", is_active=False, outcome="expired",
                     realized_r=None)
        self._signal("r_no_outcome", is_active=False, outcome="")
        rep = diagnose_grading(days=30)
        by = {r["rule_name"]: r for r in rep["rules"]}
        self.assertEqual(by["r_graded"]["n_graded"], 1)
        self.assertEqual(by["r_graded"]["n_closed_ungraded"], 0)
        self.assertEqual(by["r_ungraded"]["n_closed_ungraded"], 1)
        self.assertEqual(by["r_ungraded"]["n_graded"], 0)
        self.assertEqual(by["r_no_outcome"]["n_expired_no_outcome"], 1)
        self.assertEqual(by["r_no_outcome"]["n_graded"], 0)
        self.assertEqual(rep["totals"]["n_created"], 3)
        self.assertEqual(rep["totals"]["n_graded"], 1)
        self.assertEqual(rep["totals"]["n_lost"], 2)


class ArmTests(TestCase):

    def setUp(self):
        cache.clear()
        self.inst = _instrument("USDJPY", "forex")
        self.setup = _setup("unarmed_one", [_pp("breakout_high", lookback=5)],
                            classes=["forex"], threshold=0.6, active=False)
        from signals.models import RuleControl
        RuleControl.objects.create(rule_name="unarmed_one",
                                   promotion_stage="research")

    def _run(self, *args):
        out = StringIO()
        call_command("setups", *args, stdout=out, stderr=out)
        return out.getvalue()

    def test_arm_without_yes_writes_nothing(self):
        out = self._run("arm", "unarmed_one")
        self.setup.refresh_from_db()
        self.assertFalse(self.setup.is_active)
        self.assertIn("plan only", out)
        # And it says the safe thing about a research-stage arm.
        self.assertIn("research", out)

    def test_arm_with_a_proposal_goes_through_approve_proposal(self):
        """The generator's own path, so the re-validation and the audit row
        are the /generated/ page's and not a second one."""
        from brain.generator_models import GeneratedSetupProposal

        p = GeneratedSetupProposal.objects.create(
            proposed_name="unarmed_one", direction="bullish",
            asset_classes=["forex"], conditions=self.setup.conditions,
            min_match_score=0.6, setup=self.setup,
            status=GeneratedSetupProposal.STATUS_PENDING)
        with patch("brain.strategy_generator.approve_proposal",
                   return_value=True) as approve:
            out = self._run("arm", "unarmed_one", "--yes")
        self.assertTrue(approve.called)
        self.assertIs(approve.call_args.args[0].pk, p.pk)
        self.assertIn("approve_proposal", out)

    def test_arm_without_a_proposal_flips_is_active_and_audits(self):
        from bot_program.audit_models import AuditLogEntry

        out = self._run("arm", "unarmed_one", "--yes")
        self.setup.refresh_from_db()
        self.assertTrue(self.setup.is_active)
        self.assertIn("armed", out)
        row = AuditLogEntry.objects.filter(kind="setup_armed").first()
        self.assertIsNotNone(row)
        self.assertEqual(row.data["setup"], "unarmed_one")
        self.assertEqual(row.data["path"], "direct")


class CommandTests(_Fixture):

    def setUp(self):
        super().setUp()
        from signals.models import RuleControl
        _setup("cmd_fires", [_pp("breakout_high", lookback=5)],
               classes=["commodity"], threshold=0.5)
        _setup("cmd_blind", [_pp("above_ma", ma_period=10)],
               classes=["crypto"], threshold=0.7)
        RuleControl.objects.create(rule_name="cmd_fires",
                                   promotion_stage="research")

    def _run(self, *args):
        out = StringIO()
        call_command("setups", *args, stdout=out, stderr=out)
        return out.getvalue()

    def test_list_prints_armed_stage_and_counts(self):
        out = self._run("list")
        self.assertIn("cmd_fires", out)
        self.assertIn("research", out)
        self.assertIn("graded", out)
        self.assertIn("never", out)  # no flag has ever been written

    def test_diagnose_prints_a_verdict_and_a_sentence(self):
        out = self._run("diagnose")
        self.assertIn("cmd_fires", out)
        self.assertIn("cmd_blind", out)
        self.assertIn("blind", out)
        self.assertIn("could not evaluate", out)

    def test_show_prints_per_condition_counts(self):
        out = self._run("show", "cmd_blind")
        self.assertIn("CANNOT EVAL", out)
        self.assertIn("price_pattern", out)
        self.assertIn("composite", out)
        self.assertIn("writing nothing", out)

    def test_grading_prints_the_window_and_the_counters(self):
        out = self._run("grading", "--days", "14")
        self.assertIn("14 days", out)
        self.assertIn("graded", out)
        self.assertIn("closed ungraded", out)


class PageTests(_Fixture):

    def setUp(self):
        super().setUp()
        self.user = User.objects.create_superuser("setups_su", "a@b.c", "x")
        self.client.force_login(self.user)

    def test_the_page_renders_with_a_diagnostic(self):
        _setup("page_blind", [_pp("above_ma", ma_period=10)],
               classes=["crypto"], threshold=0.7)
        _setup("page_unarmed", [_pp("breakout_high", lookback=5)],
               classes=["commodity"], threshold=0.5, active=False)
        resp = self.client.get("/setups/")
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn("page_blind", body)
        self.assertIn("could not evaluate", body)
        # The unarmed setup gets an Arm form, for a superuser.
        self.assertIn("Arm page_unarmed", body)

    def test_the_page_renders_when_the_diagnostic_has_never_run(self):
        """Every verdict blank, and a full sentence naming the command that
        fills it — never a silent table of em-dashes."""
        _setup("page_quiet", [_pp("above_ma", ma_period=10)],
               classes=["crypto"], threshold=0.7)
        with patch("dashboard.views_setups._diagnostic", return_value=None):
            resp = self.client.get("/setups/")
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn("THE DIAGNOSTIC HAS NEVER RUN", body)
        self.assertIn("manage.py setups diagnose", body)

    def test_the_page_renders_with_no_setup_at_all(self):
        resp = self.client.get("/setups/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("NO OPPORTUNITY SETUP EXISTS", resp.content.decode())

    def test_the_arm_form_is_superuser_only(self):
        _setup("page_locked", [_pp("breakout_high", lookback=5)],
               classes=["commodity"], threshold=0.5, active=False)
        plain = User.objects.create_user("setups_plain", password="x")
        self.client.force_login(plain)
        self.assertNotIn("Arm page_locked",
                         self.client.get("/setups/").content.decode())
        resp = self.client.post("/setups/arm/", {"name": "page_locked"})
        self.assertEqual(resp.status_code, 403)
        from signals.models import OpportunitySetup
        self.assertFalse(OpportunitySetup.objects.get(
            name="page_locked").is_active)


# ══ Adversarial review, 2026-09-12 ═════════════════════════════════════════
#
# Five defects found by reading the instrument against the scanner it reports
# on, each pinned here so it cannot come back.


class QuorumHonestyTests(_Fixture):
    """A composite the SCANNER refused is not a composite.

    `scan_setup` drops every leg whose evaluator answered `measured: False`
    from BOTH sides of the weighted average, and then refuses the whole pair
    when less than half the authored weight answered — `not_enough_measured`.
    The score that rides out on that refusal is the surviving legs
    renormalised to themselves, and it is a number the scanner never compares
    to anything. The diagnostic used to put it straight into
    `composite_max` / `composite_p90` and into the near-miss count, so a setup
    that can never fire reported a confident 1.00, drew the page's p90 bar
    clean past its own threshold notch, and — inside the band — read verdict
    'near', which tells an operator to lower a threshold that was never what
    was stopping them.
    """

    def _quorum_setup(self):
        # Leg 1 matches at 1.0. Leg 2 is a cross-sectional rank with no field
        # to rank in — the ONE refusal shape `scan_setup` itself acts on — so
        # exactly half the authored weight is measured and the quorum (which
        # wants strictly more than half) refuses.
        return _setup("quorum_one",
                      [_pp("breakout_high", lookback=5),
                       {"kind": "cross_sectional_rank", "weight": 1.0,
                        "params": {"metric": "momentum", "lookback": 60,
                                   "side": "top"}}],
                      classes=["commodity"], threshold=0.95)

    def test_the_scanner_really_does_refuse_this_pair_with_a_score_on_it(self):
        """The premise of the test below: without this, a green assertion
        there could just mean the pair never scored at all."""
        from signals.opportunity_scanner import scan_setup

        raw = scan_setup(self._quorum_setup(), self.gold, now=timezone.now(),
                         as_of=False, emit=False)
        self.assertEqual(raw["reason"], "not_enough_measured")
        self.assertEqual(raw["score"], 1.0)
        self.assertFalse(raw["matched"])

    def test_a_quorum_refusal_never_becomes_a_composite_or_a_near_miss(self):
        row = self._row(self._diag(setups=[self._quorum_setup()]), "quorum_one")
        self.assertEqual(row["n_quorum_failed"], 1)
        self.assertEqual(row["n_near_miss"], 0)
        self.assertEqual(row["n_matched"], 0)
        # No distribution at all: nothing here was ever compared to 0.95.
        self.assertIsNone(row["composite_max"])
        self.assertIsNone(row["composite_p90"])
        self.assertIsNone(row["composite_p50"])
        self.assertIsNone(row["best_instrument"])
        self.assertEqual(row["verdict"], "blind")
        # And the sentence must not print the refused number anywhere.
        self.assertNotIn("1.00", row["verdict_detail"])
        self.assertIn("cross_sectional_rank", row["verdict_detail"])

    def test_the_command_does_not_print_the_refused_number_either(self):
        self._quorum_setup()
        out = StringIO()
        call_command("setups", "show", "quorum_one", stdout=out, stderr=out)
        body = out.getvalue()
        self.assertIn("below quorum 1", body)
        self.assertIn("composite  p50 ", body)
        self.assertNotIn("max 1.000", body)


class ClassifierTests(TestCase):
    """'could not evaluate' vs 'evaluated and refused' — the whole point.

    Four evaluators (`_eval_seasonality`, `_eval_funding_carry` twice,
    `_eval_earnings_surprise`) write `measured: False` INSIDE `details`
    instead of at the top level where `scan_setup` reads it. The scanner
    therefore scores those refusals as measured zeros — its own bug, and not
    this module's to fix — but the evaluator HAS made a machine-readable
    statement, and reading it is free. Without it, "no reported EPS pair for
    'AAPL' on or before this scan" matched no token in the substring
    vocabulary and an earnings leg with no EPS row anywhere on the platform
    was reported as a condition that looked and refused: BLIND misread as
    STRICT, which is the one confusion this module exists to end.
    """

    def test_measured_false_is_unevaluable_at_either_level(self):
        from signals.setup_diagnostics import _classify

        top = {"kind": "cross_sectional_rank", "matched": False, "score": 0.0,
               "measured": False, "details": {"reason": "field of 3 is thin"}}
        self.assertEqual(_classify(top)[0], "unevaluable")

        nested = {"kind": "earnings_surprise", "matched": False, "score": 0.0,
                  "details": {"measured": False, "surprise_pct": None,
                              "reason": "no reported EPS pair for AAPL on "
                                        "or before this scan"}}
        verdict, reason = _classify(nested)
        self.assertEqual(verdict, "unevaluable")
        self.assertIn("EPS", reason)

    def test_a_real_refusal_and_a_real_match_are_still_themselves(self):
        """The classifier must not answer 'unevaluable' to everything: a
        condition that looked and said no is a STRICT setup, and telling its
        operator to go find data would waste their week."""
        from signals.setup_diagnostics import _classify

        no_match = {"kind": "price_pattern", "matched": False, "score": 0.0,
                    "details": {"last": 100.0, "ma": 105.0, "period": 10}}
        self.assertEqual(_classify(no_match)[0], "no_match")
        matched = {"kind": "price_pattern", "matched": True, "score": 1.0,
                   "details": {"last": 110.0, "ma": 105.0}}
        self.assertEqual(_classify(matched)[0], "matched")
        # `measured: True` must not be read as a refusal — `_rank_refusal`
        # marks an AUTHORING error that way on purpose, and it is caught by
        # its reason, not by the flag.
        measured_zero = {"kind": "x", "matched": False, "score": 0.0,
                         "measured": True, "details": {"n": 4}}
        self.assertEqual(_classify(measured_zero)[0], "no_match")


class TruncationHonestyTests(_Fixture):
    """A verdict over 60 of 179 instruments is a verdict about 60.

    `limit_instruments` exists so the page renders in a second. It also means
    'relative_volume never matches' is a claim about the rows actually
    walked — so the sentence carries the cap, and so does the command's
    header, which otherwise printed the whole universe's instrument count
    above rows that had each seen a fraction of it.
    """

    def test_a_capped_sentence_says_it_is_capped(self):
        s = _setup("capped_one", [_pp("above_ma", ma_period=10)],
                   classes=[], threshold=0.7)          # empty = every class
        full = self._row(self._diag(setups=[s]), "capped_one")
        self.assertEqual(full["n_evaluated"], 2)
        self.assertFalse(full["truncated"])
        self.assertNotIn("not all of them", full["verdict_detail"])

        capped = self._row(self._diag(setups=[s], limit_instruments=1),
                           "capped_one")
        self.assertTrue(capped["truncated"])
        self.assertEqual(capped["n_evaluated"], 1)
        self.assertIn("not all of them", capped["verdict_detail"])
        self.assertIn("setups diagnose", capped["verdict_detail"])

    def test_the_command_header_says_the_reading_was_capped(self):
        _setup("capped_two", [_pp("above_ma", ma_period=10)],
               classes=[], threshold=0.7)
        out = StringIO()
        call_command("setups", "diagnose", "--limit", "1",
                     stdout=out, stderr=out)
        body = out.getvalue()
        self.assertIn("CAPPED at --limit 1", body)
        self.assertIn("not all of them", body)


class ArmSafetyTests(TestCase):
    """Arming says what arming THIS setup means, and refuses what the
    generator would refuse."""

    def setUp(self):
        cache.clear()
        self.inst = _instrument("AUDUSD", "forex")
        self.user = User.objects.create_superuser("arm_su", "a@b.c", "x")

    def test_a_blocked_proposal_is_refused_and_nothing_is_armed(self):
        """`approval_blocker` re-validates at the moment of arming, because a
        pending proposal can sit for a fortnight while the evaluator's
        accepted params change underneath it. The command must not walk past
        that on --yes."""
        from brain.generator_models import GeneratedSetupProposal
        from signals.models import OpportunitySetup

        bad = _setup("blocked_one",
                     [{"kind": "no_such_evaluator", "weight": 1.0,
                       "params": {}}],
                     classes=["forex"], threshold=0.6, active=False)
        GeneratedSetupProposal.objects.create(
            proposed_name="blocked_one", direction="bullish",
            asset_classes=["forex"], conditions=bad.conditions,
            min_match_score=0.6, setup=bad,
            status=GeneratedSetupProposal.STATUS_PENDING)
        out = StringIO()
        call_command("setups", "arm", "blocked_one", "--yes",
                     stdout=out, stderr=out)
        self.assertIn("cannot arm", out.getvalue())
        self.assertFalse(OpportunitySetup.objects.get(
            name="blocked_one").is_active)

    def test_the_page_does_not_promise_the_research_gate_to_a_live_setup(self):
        """The success message used to say "the stage gate keeps every bot
        off it while it is at research" for EVERY arm, including a setup
        whose rule sits at live_full. A reassurance that is only sometimes
        true is worse than none."""
        from django.contrib.messages import get_messages

        from signals.models import RuleControl

        _setup("live_stage_one", [_pp("breakout_high", lookback=5)],
               classes=["forex"], threshold=0.6, active=False)
        RuleControl.objects.create(rule_name="live_stage_one",
                                   promotion_stage="live_full")
        self.client.force_login(self.user)
        resp = self.client.post("/setups/arm/", {"name": "live_stage_one"},
                                follow=True)
        self.assertEqual(resp.status_code, 200)
        said = " ".join(str(m) for m in get_messages(resp.wsgi_request))
        self.assertIn("NOT research", said)
        self.assertIn("may reach a venue", said)
        self.assertNotIn("this is safe", said)

    def test_a_research_setup_is_still_told_it_is_safe(self):
        from django.contrib.messages import get_messages

        from signals.models import OpportunitySetup, RuleControl

        _setup("research_stage_one", [_pp("breakout_high", lookback=5)],
               classes=["forex"], threshold=0.6, active=False)
        RuleControl.objects.create(rule_name="research_stage_one",
                                   promotion_stage="research")
        self.client.force_login(self.user)
        resp = self.client.post("/setups/arm/", {"name": "research_stage_one"},
                                follow=True)
        said = " ".join(str(m) for m in get_messages(resp.wsgi_request))
        self.assertIn("this is safe", said)
        self.assertTrue(OpportunitySetup.objects.get(
            name="research_stage_one").is_active)


class PageTruncationTests(_Fixture):

    def setUp(self):
        super().setUp()
        self.user = User.objects.create_superuser("setups_cap", "a@b.c", "x")
        self.client.force_login(self.user)

    def test_the_page_says_when_ANY_row_of_its_reading_was_capped(self):
        """The cap sentence used to be keyed on `rows.0.truncated` — the FIRST
        row of a table sorted by verdict, which has nothing to do with which
        rows were capped.

        The fixture is the hole itself. `aaa_narrow` admits ONE instrument, so
        a cap of one does not truncate it, and it is `blind`, which sorts
        first. `zzz_wide` admits both, IS truncated, and its surviving
        instrument matches — so it reads `fires` and sorts last. Under the old
        key the page said nothing at all while half its verdicts had been
        taken over a fraction of the universe.
        """
        from dashboard import views_setups

        narrow = _setup("aaa_narrow", [_pp("above_ma", ma_period=10)],
                        classes=["crypto"], threshold=0.7)
        wide = _setup("zzz_wide", [_pp("above_ma", ma_period=10)],
                      classes=[], threshold=0.7)
        rep = self._diag(setups=[narrow, wide], limit_instruments=1)
        self.assertFalse(self._row(rep, "aaa_narrow")["truncated"])
        self.assertTrue(self._row(rep, "zzz_wide")["truncated"])
        # The one that is NOT truncated is the one the old key looked at.
        self.assertEqual(rep["setups"][0]["name"], "aaa_narrow")

        with patch.object(views_setups, "PAGE_INSTRUMENT_LIMIT", 1):
            body = self.client.get("/setups/").content.decode()
        self.assertIn("This reading is CAPPED", body)
        self.assertIn("not all of them", body)

    def test_an_uncapped_page_does_not_claim_to_be_capped(self):
        _setup("cap_small", [_pp("above_ma", ma_period=10)],
               classes=["commodity"], threshold=0.7)
        body = self.client.get("/setups/").content.decode()
        self.assertNotIn("This reading is CAPPED", body)
