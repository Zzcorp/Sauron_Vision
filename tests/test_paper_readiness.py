"""Will 90 days of paper produce anything? (2026-09-15)

The operator decided to spend two to three months on a full paper campaign
and then arrive with evidence. That is what a real firm would ask for, and
it is also what this platform can silently fail to produce, because every
link in the chain

    bars -> indicators -> signals -> fills -> outcomes -> the ladder

is gated by a `PlatformComponent`, and `is_component_enabled` returns False
for a MISSING ROW. So a link can be cold in two ways — switched off, or never
seeded — and neither raises, neither logs, and `guarded_task` no-ops. Ninety
days later the ladder reads n=0 and there is nothing to show.

`manage.py paper_readiness` is the mirror of `preflight_live`: not "is it safe
to arm money" but "can this produce evidence at all".

WHAT THESE TESTS CONFRONT

A readiness report is only worth the accuracy of what it names, and it names
things it does not own:

  - four component keys, owned by `core/platform_control.py`
  - two task cadences, owned by `config/celery.py`
  - three promotion gates, owned by `signals/promotion_pipeline.py`

Each of those is read from its owner here and compared, so the report cannot
drift into describing a platform that no longer exists. A key that is not a
real component would print "NO ROW" forever and read as a switch somebody
forgot — the most expensive shape a wrong report can take, because it sends
the operator to turn on something that was never there.
"""
import re
from io import StringIO
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase

from bot_program import campaign_readiness as pr

CELERY = Path(settings.BASE_DIR) / "config" / "celery.py"


def _run(**kw):
    out = StringIO()
    call_command("paper_readiness", stdout=out, **kw)
    return out.getvalue()


def _component(key, enabled):
    from core.platform_control import PlatformComponent
    row, _ = PlatformComponent.objects.get_or_create(
        key=key, defaults={"name": key, "description": ""})
    row.is_enabled = enabled
    row.save(update_fields=["is_enabled"])
    return row


class EveryKeyItNamesIsRealTests(SimpleTestCase):
    """A key that is not a component prints NO ROW forever, and reads as a
    switch somebody forgot to seed."""

    def setUp(self):
        from core.platform_control import DEFAULT_COMPONENTS
        self.known = {c["key"] for c in DEFAULT_COMPONENTS}

    def test_the_chain_keys_are_components(self):
        unknown = [k for k, _why in pr.EVIDENCE_CHAIN if k not in self.known]
        self.assertEqual(
            unknown, [],
            f"{unknown} are reported as links in the evidence chain and are "
            f"not components at all — the report would send an operator to "
            f"turn on a switch that does not exist")

    def test_the_must_be_off_keys_are_components(self):
        unknown = [k for k in pr.MUST_BE_OFF if k not in self.known]
        self.assertEqual(unknown, [], f"{unknown} are not components")

    def test_every_chain_link_actually_gates_a_task(self):
        """A component nothing is guarded by is not a link — it is a switch
        with no wire, and reporting it ON would be a false reassurance."""
        import subprocess
        for key, why in pr.EVIDENCE_CHAIN:
            with self.subTest(key=key):
                found = subprocess.run(
                    ["git", "grep", "-l", f'guarded_task("{key}")'],
                    cwd=str(settings.BASE_DIR), capture_output=True,
                    text=True).stdout.strip()
                self.assertTrue(
                    found,
                    f"nothing is decorated @guarded_task({key!r}), so the "
                    f"report claims {why!r} is gated by a switch that gates "
                    f"nothing")

    def test_the_actuator_list_is_named_not_pattern_matched(self):
        """Matching on "_mode_live" would let a new actuator inherit an
        exemption from a naming convention. Each one is listed on purpose."""
        src = (Path(settings.BASE_DIR) / "bot_program"
               / "campaign_readiness.py").read_text(encoding="utf-8")
        self.assertNotIn('endswith("_mode_live")', src)
        for key in pr.MUST_BE_OFF:
            self.assertIn(f'"{key}"', src)

    def test_every_live_mode_component_is_on_the_list(self):
        """The other half: a component whose own name says it arms live
        action must be one this command refuses during a paper campaign."""
        from core.platform_control import DEFAULT_COMPONENTS
        arming = {c["key"] for c in DEFAULT_COMPONENTS
                  if c["key"].endswith("_mode_live")}
        missing = arming - set(pr.MUST_BE_OFF)
        self.assertEqual(
            missing, set(),
            f"{sorted(missing)} arm live action and are not checked — a paper "
            f"campaign would run with a proposer allowed to spend")


class TheCadencesItQuotesAreTheRealOnesTests(SimpleTestCase):
    """The report states "every 300s". config/celery.py owns that number."""

    def setUp(self):
        self.celery = CELERY.read_text(encoding="utf-8")

    def test_each_ungated_task_is_scheduled_at_the_stated_interval(self):
        for task, every, _why in pr.UNGATED:
            with self.subTest(task=task):
                self.assertIn(
                    f'"{task}"', self.celery,
                    f"{task} is reported as running on a schedule and is not "
                    f"in the beat schedule at all")
                block = self.celery[self.celery.index(f'"{task}"'):][:300]
                found = re.search(r'"schedule":\s*([0-9.]+)', block)
                self.assertIsNotNone(
                    found, f"{task}'s schedule is not a plain interval any "
                           f"more; the report's 'every Ns' is now a guess")
                self.assertEqual(
                    float(found.group(1)), float(every),
                    f"{task} runs every {found.group(1)}s and the report says "
                    f"every {every}s")

    def test_the_lifecycle_pass_is_still_ungated(self):
        """It is reported as having no switch. If it grows one, an operator
        told 'no switch to look for' would stop looking for the one thing
        that writes realized_r."""
        src = (Path(settings.BASE_DIR) / "signals"
               / "tasks_lifecycle.py").read_text(encoding="utf-8")
        self.assertNotIn("guarded_task", src)

    def test_the_promotion_gates_are_read_from_the_pipeline(self):
        """The report quotes three thresholds it does not own. Naming the
        constants keeps them true when the ladder is retuned; typing the
        numbers would make this report the place they go stale."""
        src = (Path(settings.BASE_DIR) / "bot_program"
               / "campaign_readiness.py").read_text(encoding="utf-8")
        self.assertIn("from signals.promotion_pipeline import", src)
        for constant in ("PROMO_RESEARCH_TO_PAPER_MIN_N",
                         "PROMO_PAPER_TO_LIVE_SMALL_MIN_N",
                         "PROMO_PAPER_TO_LIVE_SMALL_MIN_DAYS"):
            self.assertIn(constant, src)
        # And the numbers they currently hold must not be typed anywhere.
        from signals import promotion_pipeline as pp
        for value in (pp.PROMO_RESEARCH_TO_PAPER_MIN_N,
                      pp.PROMO_PAPER_TO_LIVE_SMALL_MIN_N,
                      pp.PROMO_PAPER_TO_LIVE_SMALL_MIN_DAYS):
            self.assertNotIn(
                f"n>={value}", src,
                f"the gate {value} is typed into the report; retuning the "
                f"ladder would leave it describing the old one")


class ItWritesNothingTests(TestCase):
    """It is run while deciding whether to spend three months. It must not be
    able to change what it is describing."""

    def test_it_changes_no_component_row(self):
        from core.platform_control import PlatformComponent
        _component("platform_master", True)
        _component("pipeline_signals", False)
        before = sorted(PlatformComponent.objects.values_list(
            "key", "is_enabled"))
        _run()
        after = sorted(PlatformComponent.objects.values_list(
            "key", "is_enabled"))
        self.assertEqual(before, after)

    def test_it_makes_no_broker_call(self):
        with mock.patch("bot_program.engine.broker_router.client_for_symbol",
                        side_effect=AssertionError("a broker was called")):
            _run()


class AColdLinkIsABlockerTests(TestCase):

    def setUp(self):
        _component("platform_master", True)
        for key, _why in pr.EVIDENCE_CHAIN:
            _component(key, True)

    def test_a_complete_chain_reports_no_chain_blocker(self):
        body = _run()
        for key, _why in pr.EVIDENCE_CHAIN:
            self.assertNotIn(f"{key} is off", body)

    def test_one_switched_off_link_blocks_and_names_the_page(self):
        _component("pipeline_promotion", False)
        body = _run()
        self.assertIn("pipeline_promotion is off", body)
        self.assertIn("/ops/", body)
        self.assertIn("n=0", body)

    def test_a_missing_row_is_not_reported_as_off(self):
        """"off" is a decision, "NO ROW" is an omission, and they are fixed
        by two different commands. `is_component_enabled` collapses them into
        False — right for a task gate, wrong for a report."""
        from core.platform_control import PlatformComponent
        PlatformComponent.objects.filter(key="pipeline_promotion").delete()
        body = _run()
        self.assertIn("NO ROW", body)
        self.assertIn("seed_components", body)
        chain = body[body.index("2. THE EVIDENCE CHAIN"):body.index("3. MONEY")]
        self.assertNotIn(
            "pipeline_promotion       off", chain,
            "a component with no row was printed as 'off', which sends the "
            "operator to a switch page instead of to seed_components")

    def test_the_master_switch_overrides_every_green_link(self):
        _component("platform_master", False)
        body = _run()
        self.assertIn("platform_master is not ON", body)
        self.assertIn("whatever its own switch says", body)

    def test_an_armed_actuator_blocks_a_paper_campaign(self):
        _component("share_allocator_mode_live", True)
        body = _run()
        self.assertIn("share_allocator_mode_live is ON", body)
        self.assertIn("is not a paper campaign", body)

    def test_no_paper_config_is_a_blocker(self):
        body = _run()
        self.assertIn("no enabled config is in paper mode", body)

    def test_a_paper_config_clears_it_and_live_ones_are_flagged(self):
        from decimal import Decimal

        from django.contrib.auth.models import User

        from bot_program.models import AssetBotConfig
        user = User.objects.create_user("pr_u", password="x")
        AssetBotConfig.objects.create(
            user=user, asset_class="crypto", name="p1", mode="paper",
            symbols=["BTCUSD"], capital=Decimal("1000"),
            base_currency="EUR", enabled=True)
        AssetBotConfig.objects.create(
            user=user, asset_class="stock", name="l1", mode="live",
            symbols=["AAPL"], capital=Decimal("1000"),
            base_currency="EUR", enabled=True)
        body = _run()
        self.assertNotIn("no enabled config is in paper mode", body)
        self.assertIn("1 paper, 1 live", body)
        self.assertIn("never pooled", body)


class TheLadderCountIsTheGradedRowsTests(TestCase):
    """The ladder counts rows with a realized_r. A count of CLOSED rows would
    overstate the evidence by every row the lifecycle could not price."""

    def setUp(self):
        _component("platform_master", True)
        for key, _why in pr.EVIDENCE_CHAIN:
            _component(key, True)

    def _signal(self, *, closed, realized_r):
        from decimal import Decimal

        from instruments.models import Instrument
        from signals.models import Signal
        inst, _ = Instrument.objects.get_or_create(
            symbol="AAPL", defaults={"name": "AAPL", "asset_class": "stock"})
        return Signal.objects.create(
            instrument=inst, signal_type="composite", direction="bullish",
            urgency="medium", title="t", description="t", rule_name="r1",
            score=0.8, sub_scores={}, price_at_signal=Decimal("100"),
            is_active=not closed, realized_r=realized_r)

    def test_closed_without_a_price_does_not_count_as_evidence(self):
        for _ in range(3):
            self._signal(closed=True, realized_r=None)
        body = _run()
        # Asserted on the numbers rather than on column widths: a report
        # whose tests break when a column moves is a report nobody reformats.
        self.assertRegex(body, r"signals closed\s+3")
        self.assertRegex(body, r"carrying a realized_r\s+0")

    def test_all_closed_and_none_graded_is_a_blocker(self):
        self._signal(closed=True, realized_r=None)
        body = _run()
        self.assertIn("NOT ONE carries a realized_r", body)

    def test_graded_rows_clear_it(self):
        self._signal(closed=True, realized_r=1.5)
        body = _run()
        self.assertNotIn("NOT ONE carries a realized_r", body)
        self.assertRegex(body, r"carrying a realized_r\s+1")


class TheReportRefusesToFlatterTests(TestCase):

    def test_it_says_it_cannot_judge_the_evidence_itself(self):
        """A readiness check that read as a quality verdict would be worse
        than none: a complete chain says nothing about whether the strategy
        works."""
        body = _run()
        self.assertIn("never whether the", body)
        self.assertIn("evidence is good", body)
