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


# ── 2026-11-12: a live operation is named as one ────────────────────────────
#
# The operator trades real money by decision, and the report listed his
# decision under "BLOCKERS — 90 days would produce nothing gradeable". Two of
# its checks ask whether the campaign is PAPER (the live-action switches off,
# a paper bot on). With a bot armed for real money they are a decision, and
# they are listed as one; everything about the chain itself stays a fault.

OPEN = {"session": "NYSE", "code": "NYSE", "is_open": True}
SHARE_ALLOCATOR_LINE = (
    "share_allocator_mode_live is ON — the share allocator's live mode (a "
    "share plan may be applied with the PIN, which re-sizes the pools), "
    "which is not a paper campaign")
ACTUATOR_LINE = (
    "actuator_mode_live is ON — the rule actuator's live mode (a superuser "
    "may apply a pause or a size cut to a rule; nothing applies by itself), "
    "which is not a paper campaign")


def _bot(user, name, mode, symbols, asset_class="stock"):
    from decimal import Decimal

    from bot_program.models import AssetBotConfig
    return AssetBotConfig.objects.create(
        user=user, asset_class=asset_class, name=name, mode=mode,
        symbols=list(symbols), capital=Decimal("1000"),
        base_currency="EUR", enabled=True)


def _bar(symbol, age_hours, exchange="NYSE", asset_class="stock"):
    from datetime import timedelta
    from decimal import Decimal

    from django.utils import timezone

    from instruments.models import Instrument
    from market_data.models import PriceData
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class,
                                 "exchange": exchange})
    PriceData.objects.update_or_create(
        instrument=inst, timeframe="4h",
        timestamp=timezone.now() - timedelta(hours=age_hours),
        defaults={"open": 1, "high": 2, "low": 1, "close": Decimal("10"),
                  "volume": 1, "source": "test"})
    return inst


def _closed_with_no_result(symbol="AAPL"):
    from decimal import Decimal

    from instruments.models import Instrument
    from signals.models import Signal
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": "stock",
                                 "exchange": "NYSE"})
    return Signal.objects.create(
        instrument=inst, signal_type="composite", direction="bullish",
        urgency="medium", title="t", description="t", rule_name="r1",
        score=0.8, sub_scores={}, price_at_signal=Decimal("100"),
        is_active=False, realized_r=None)


def _rendered_as_before(report):
    """The command's output as main rendered it until 2026-11-12, kept here
    as the reference: one BLOCKERS list, whatever the campaign."""
    lines = ["=" * 70,
             "PAPER READINESS — WILL 90 DAYS PRODUCE A GRADED TRACK RECORD",
             "=" * 70]
    for i, (title, rows) in enumerate(report["sections"], 1):
        lines.append(f"\n{i}. {title}")
        for left, middle, right in rows:
            lines.append(f"   {left:<30} {middle:<12} {right}".rstrip())
        if title == "THE EVIDENCE CHAIN":
            lines.append("\n   Ungated by design — no switch to look for:")
            for task, every, what in pr.UNGATED:
                lines.append(
                    f"   {task.split('.')[-1]:<30} every {every}s  {what}")
    lines.append("\n" + "=" * 70)
    if report["blockers"]:
        lines.append("BLOCKERS — 90 days would produce nothing gradeable:")
        for i, m in enumerate(report["blockers"], 1):
            lines.append(f"  {i}. {m}")
    else:
        lines.append("NO BLOCKERS — the chain is complete end to end.")
    if report["notes"]:
        lines.append("\nWORTH READING:")
        for i, m in enumerate(report["notes"], 1):
            lines.append(f"  {i}. {m}")
    lines.append("=" * 70)
    lines.append("This command writes nothing and makes no broker call. It says")
    lines.append("whether the chain CAN produce evidence, never whether the")
    lines.append("evidence is good.")
    return "\n".join(lines) + "\n"


class _Fleet(TestCase):

    def setUp(self):
        from django.contrib.auth.models import User
        _component("platform_master", True)
        for key, _why in pr.EVIDENCE_CHAIN:
            _component(key, True)
        for key in pr.MUST_BE_OFF:
            _component(key, False)
        self.user = User.objects.create_user("pr_fleet", password="x")

    def _report(self):
        with mock.patch("core.exchange_status.market_status_for",
                        return_value=OPEN):
            return pr.readiness()

    def _body(self):
        with mock.patch("core.exchange_status.market_status_for",
                        return_value=OPEN):
            return _run()


class TheKindOfCampaignTests(_Fleet):
    """Decided by the configs that SCAN. A TAKE TRADE lane is an enabled
    config with no symbols (bot_program/manual_trade), in live mode once it
    is armed: it is not a bot, and alone it changes nothing."""

    def test_a_scanning_live_bot_makes_it_a_live_operation(self):
        _bot(self.user, "l1", "live", ["AAPL"])
        _bot(self.user, "p1", "paper", ["XAUUSD"])
        report = self._report()
        self.assertEqual(report["campaign"], "live")
        self.assertEqual(report["fleet"]["live_bots"], 1)
        self.assertEqual(report["fleet"]["paper_bots"], 1)
        self.assertEqual(report["fleet"]["hand_lanes"], 0)

    def test_paper_bots_beside_a_live_hand_lane_are_a_paper_campaign(self):
        _bot(self.user, "p1", "paper", ["XAUUSD"])
        _bot(self.user, "manual", "live", [])
        report = self._report()
        self.assertEqual(report["campaign"], "paper")
        self.assertEqual(report["fleet"]["live_bots"], 0)
        self.assertEqual(report["fleet"]["hand_lanes"], 1)

    def test_a_live_hand_lane_and_nothing_else_is_no_campaign(self):
        _bot(self.user, "manual", "live", [])
        report = self._report()
        self.assertEqual(report["campaign"], "none")
        said = " | ".join(report["blockers"])
        self.assertIn("no enabled config is in paper mode", said)
        self.assertIn("no enabled config lists a symbol", said)

    def test_nothing_enabled_is_no_campaign(self):
        self.assertEqual(self._report()["campaign"], "none")

    def test_a_live_config_with_no_symbols_is_not_a_bot(self):
        _bot(self.user, "empty", "live", [])
        report = self._report()
        self.assertEqual(report["campaign"], "none")
        self.assertEqual(report["fleet"]["hand_lanes"], 0)

    def test_a_lane_is_a_lane_whatever_it_lists(self):
        """The lane is the config NAMED manual. Symbols on it are a drift
        the ticket refuses (manual_trade._config_error): it still scans
        nothing."""
        _bot(self.user, "manual", "live", ["AAPL"])
        _bot(self.user, "p1", "paper", ["XAUUSD"])
        report = self._report()
        self.assertEqual(report["campaign"], "paper")
        self.assertEqual(report["fleet"]["hand_lanes"], 1)

    def test_a_bot_that_is_off_does_not_count(self):
        cfg = _bot(self.user, "l1", "live", ["AAPL"])
        cfg.enabled = False
        cfg.save(update_fields=["enabled"])
        _bot(self.user, "p1", "paper", ["XAUUSD"])
        self.assertEqual(self._report()["campaign"], "paper")

    def test_a_paper_hand_lane_is_not_a_paper_bot(self):
        """Today's count of paper configs keeps it (so a paper lane alone
        is still a 'paper' campaign, as before); the fleet does not call
        it a bot."""
        _bot(self.user, "manual", "paper", [])
        report = self._report()
        self.assertEqual(report["campaign"], "paper")
        self.assertEqual(report["fleet"]["paper_bots"], 0)
        self.assertEqual(report["fleet"]["paper_lanes"], 1)

    def test_the_old_keys_of_the_report_are_all_still_there(self):
        report = self._report()
        for key in ("sections", "blockers", "notes", "cold_links",
                    "window_days", "campaign", "chain_faults",
                    "campaign_gaps", "armed", "paper_stage_stuck", "fleet"):
            self.assertIn(key, report)
        self.assertEqual([title for title, _rows in report["sections"]][:3],
                         ["MASTER SWITCH", "THE EVIDENCE CHAIN",
                          "MONEY MUST NOT MOVE"])


class ALiveOperationIsNamedAsOneTests(_Fleet):

    def test_an_armed_switch_is_a_decision_and_not_a_blocker(self):
        _bot(self.user, "l1", "live", ["AAPL"])
        _bar("AAPL", 1.0)
        _component("share_allocator_mode_live", True)
        report = self._report()
        self.assertEqual(report["blockers"], [])
        self.assertEqual(report["chain_faults"], [])
        self.assertEqual(report["armed"], ["share_allocator_mode_live"])
        self.assertEqual([str(g) for g in report["campaign_gaps"]],
                         [SHARE_ALLOCATOR_LINE,
                          "no paper bot is on — nothing trades on the "
                          "simulator except entries a live bot's rule sends "
                          "there"])
        body = self._body()
        self.assertNotIn("BLOCKERS", body)
        self.assertIn("NO CHAIN FAULTS — the chain is complete end to end.",
                      body)
        at = body.index("LIVE BY DECISION — not a paper campaign, and no "
                        "fault:")
        self.assertNotIn("share_allocator_mode_live is ON", body[:at])
        self.assertIn(f"  1. {SHARE_ALLOCATOR_LINE}", body[at:])
        self.assertIn("  2. no paper bot is on", body[at:])
        self.assertIn("A LIVE OPERATION, NOT A PAPER CAMPAIGN — 1 bot is "
                      "armed for real money.", body)

    def test_section_three_is_headed_for_what_it_lists(self):
        _bot(self.user, "l1", "live", ["AAPL"])
        body = self._body()
        self.assertIn("\n3. LIVE-ACTION SWITCHES — a paper campaign wants "
                      "all five off\n", body)
        self.assertNotIn("MONEY MUST NOT MOVE", body)
        self.assertEqual(
            len(pr.MUST_BE_OFF), 5,
            "the heading says 'all five off': a sixth key makes it a lie")

    def test_a_chain_fault_of_a_live_operation_is_listed_apart(self):
        _bot(self.user, "l1", "live", ["AAPL"])       # no bar at all
        _component("actuator_mode_live", True)
        _component("pipeline_promotion", False)
        body = self._body()
        start = body.index("CHAIN FAULTS — evidence is not being produced:")
        at = body.index("LIVE BY DECISION")
        self.assertLess(start, at)
        faults = body[start:at]
        self.assertIn("  1. pipeline_promotion is off", faults)
        self.assertIn("no 4h bars at all", faults)
        self.assertNotIn("actuator_mode_live is ON", faults)
        self.assertIn(f"  1. {ACTUATOR_LINE}", body[at:])
        self.assertNotIn("NO CHAIN FAULTS", body)
        self.assertNotIn("BLOCKERS", body)

    def test_nothing_to_decide_prints_no_empty_group(self):
        _bot(self.user, "l1", "live", ["AAPL"])
        _bot(self.user, "p1", "paper", ["XAUUSD"])
        _bar("AAPL", 1.0)
        _bar("XAUUSD", 1.0)
        body = self._body()
        self.assertNotIn("LIVE BY DECISION", body)
        self.assertIn("A LIVE OPERATION, NOT A PAPER CAMPAIGN", body)
        self.assertIn("NO CHAIN FAULTS", body)
        self.assertIn("WORTH READING:", body)      # the live-mode note stays

    def test_the_hand_lanes_are_counted_apart(self):
        _bot(self.user, "l1", "live", ["AAPL"])
        _bot(self.user, "l2", "live", ["XAUUSD"])
        _bot(self.user, "manual", "live", [], asset_class="forex")
        self.assertIn("A LIVE OPERATION, NOT A PAPER CAMPAIGN — 2 bots are "
                      "armed for real money; 1 hand lane is in live mode.",
                      self._body())

    def test_a_rule_stuck_at_the_paper_stage_is_listed_with_the_faults(self):
        from django.utils import timezone

        from signals.models_control import RuleControl
        _bot(self.user, "l1", "live", ["AAPL"])
        _bar("AAPL", 1.0)
        RuleControl.objects.create(
            rule_name="po3_london_sweep_short", promotion_stage="paper",
            stage_entered_at=timezone.now())
        report = self._report()
        self.assertEqual(report["paper_stage_stuck"],
                         ["po3_london_sweep_short"])
        self.assertEqual([b.key for b in report["blockers"]],
                         [("stuck", ("po3_london_sweep_short",))])
        body = self._body()
        faults = body[body.index("CHAIN FAULTS"):body.index(
            "LIVE BY DECISION")]
        self.assertIn("po3_london_sweep_short is at the paper stage with no "
                      "paper bot to trade on", faults)


class APaperCampaignReadsAsBeforeTests(_Fleet):
    """With no bot armed for real money the command prints what it printed
    before, the heading '3. MONEY MUST NOT MOVE' and the one BLOCKERS list
    included. Only the armed switch's own words changed."""

    def _same(self):
        """The command's output, checked byte for byte against the old
        rendering of the same report (one clock for both, so a bar's age
        cannot differ between the two reads)."""
        from datetime import timedelta

        from django.utils import timezone
        now = timezone.now() + timedelta(minutes=5)
        with mock.patch("django.utils.timezone.now", return_value=now), \
                mock.patch("core.exchange_status.market_status_for",
                           return_value=OPEN):
            body = _run()
            self.assertEqual(body, _rendered_as_before(pr.readiness()))
        return body

    def test_nothing_enabled(self):
        body = self._same()
        self.assertIn("\n3. MONEY MUST NOT MOVE\n", body)
        self.assertIn("BLOCKERS — 90 days would produce nothing gradeable:",
                      body)

    def test_a_paper_campaign_with_an_armed_switch_and_a_cold_link(self):
        _bot(self.user, "p1", "paper", ["AAPL", "XAUUSD"])
        _bar("AAPL", 1.0)
        _component("actuator_mode_live", True)
        _component("pipeline_promotion", False)
        _closed_with_no_result()
        body = self._same()
        self.assertIn("\n3. MONEY MUST NOT MOVE\n", body)
        self.assertIn(f"  2. {ACTUATOR_LINE}", body)
        for absent in ("LIVE BY DECISION", "LIVE OPERATION", "CHAIN FAULTS",
                       "LIVE-ACTION SWITCHES"):
            self.assertNotIn(absent, body)

    def test_a_complete_paper_campaign(self):
        _bot(self.user, "p1", "paper", ["AAPL"])
        _bar("AAPL", 1.0)
        with mock.patch("core.exchange_status.market_status_for",
                        return_value=OPEN):
            body = _run()
        self.assertIn("NO BLOCKERS — the chain is complete end to end.", body)

    def test_paper_bots_beside_a_live_hand_lane(self):
        _bot(self.user, "p1", "paper", ["AAPL"])
        _bot(self.user, "manual", "live", [])
        _component("actuator_mode_live", True)
        body = self._same()
        self.assertIn(f"  1. {ACTUATOR_LINE}", body)

    def test_the_blockers_keep_the_order_the_checks_run_in(self):
        _bot(self.user, "p1", "paper", ["AAPL"])
        _component("actuator_mode_live", True)
        _component("pipeline_promotion", False)
        _closed_with_no_result()
        report = self._report()
        self.assertEqual([b.key[0] for b in report["blockers"]],
                         ["link", "armed", "no_result", "no_bars"])
        self.assertEqual([b.key[0] for b in report["chain_faults"]],
                         ["link", "no_result", "no_bars"])
        self.assertEqual([b.key for b in report["campaign_gaps"]],
                         [("armed", "actuator_mode_live")])


class EachSwitchInItsOwnWordsTests(SimpleTestCase):
    """One sentence served all five: "a proposer is allowed to ACT on live
    capital". It is true of one of them. For the actuator, the
    meta-allocator and the share allocator's live mode a PERSON acts."""

    def test_every_key_that_must_be_off_has_its_words(self):
        self.assertEqual(set(pr.LIVE_ACTION_WORDS), set(pr.MUST_BE_OFF))

    def test_no_word_is_a_key(self):
        for key, words in pr.LIVE_ACTION_WORDS.items():
            name, allows = words
            for text in (name, allows):
                with self.subTest(key=key, text=text):
                    self.assertTrue(text.strip())
                    self.assertNotIn("_", text)
                    self.assertNotIn(key, text)

    def test_the_old_sentence_is_gone(self):
        src = (Path(settings.BASE_DIR) / "bot_program"
               / "campaign_readiness.py").read_text(encoding="utf-8")
        self.assertNotIn("a proposer is allowed to ACT on live", src)
        self.assertNotIn("allowed to ACT", " ".join(src.split()))


class EveryFindingCarriesAKeyTests(_Fleet):
    """The watchdog remembers WHAT is wrong, never the sentence that says
    it. Three sentences carry a number that moves from one morning to the
    next (the age of a stale bar, the days of bars missing, the count of
    closed signals with no result): a memory of the sentences would call an
    unchanged fault new every day, and alarm every day."""

    #: The first word of every key a finding can carry.
    KINDS = {"master", "beat", "link", "armed", "no_paper", "no_result",
             "no_bars", "bars_stopped", "no_symbol", "stuck"}

    def _everything_wrong_in_a_paper_campaign(self):
        from django_celery_beat.models import IntervalSchedule, PeriodicTask

        from core.platform_control import PlatformComponent
        _component("platform_master", False)
        every = IntervalSchedule.objects.create(
            every=600, period=IntervalSchedule.SECONDS)
        PeriodicTask.objects.create(
            name="refresh-saxo-sessions", interval=every, enabled=False,
            task="bot_program.tasks.refresh_saxo_sessions")
        _component("pipeline_promotion", False)
        PlatformComponent.objects.filter(key="pipeline_signals").delete()
        for key in pr.MUST_BE_OFF:
            _component(key, True)
        _bot(self.user, "p1", "paper", ["NOBAR", "LATE", "DEAD"])
        _bar("LATE", 12.0, exchange="NYSE")
        _bar("DEAD", 120.0, exchange="LSE")
        _closed_with_no_result()

    def _report_at(self, days):
        from datetime import timedelta

        from django.utils import timezone

        def market(asset_class, exchange="", now_utc=None, symbol=""):
            return {"session": exchange, "code": exchange,
                    "is_open": exchange == "NYSE"}

        now = self.base + timedelta(days=days)
        with mock.patch.object(timezone, "now", return_value=now), \
                mock.patch("core.exchange_status.market_status_for",
                           side_effect=market):
            return pr.readiness()

    def setUp(self):
        from django.utils import timezone
        super().setUp()
        self.base = timezone.now()

    def _assert_keyed(self, report):
        for group in ("blockers", "chain_faults", "campaign_gaps"):
            for finding in report[group]:
                with self.subTest(group=group, finding=str(finding)[:60]):
                    key = getattr(finding, "key", None)
                    self.assertIsInstance(key, tuple)
                    self.assertIn(key[0], self.KINDS)
                    for part in key:
                        parts = part if isinstance(part, tuple) else (part,)
                        for p in parts:
                            self.assertIsInstance(
                                p, str, f"{key}: a number in a key is an "
                                        f"age, a count or a day")

    def test_every_blocker_carries_a_key_and_no_key_moves(self):
        self._everything_wrong_in_a_paper_campaign()
        day0 = self._report_at(0)
        _closed_with_no_result()
        day1 = self._report_at(1)
        self._assert_keyed(day0)
        self._assert_keyed(day1)
        self.assertEqual([b.key for b in day0["blockers"]],
                         [b.key for b in day1["blockers"]])
        # ...while the sentences did move, or this proves nothing.
        moved = [k for k, a, b in zip(
            (b.key[0] for b in day0["blockers"]), day0["blockers"],
            day1["blockers"]) if str(a) != str(b)]
        self.assertEqual(sorted(moved),
                         ["bars_stopped", "bars_stopped", "no_result"])
        self.assertEqual(
            sorted(b.key for b in day0["blockers"]),
            sorted([
                ("master",),
                ("beat", "bot_program.tasks.refresh_saxo_sessions"),
                ("link", "pipeline_signals", "NO ROW"),
                ("link", "pipeline_promotion", "off"),
                *[("armed", key) for key in pr.MUST_BE_OFF],
                ("no_result",),
                ("no_bars", ("NOBAR",)),
                ("bars_stopped", "NYSE", ("LATE",)),
                ("bars_stopped", "LSE", ("DEAD",)),
            ]))

    def test_the_same_dead_feed_is_one_fault_open_or_shut(self):
        """A bar feed that stopped reads 'OPEN and behind' while its market
        is open and 'days missing' once it is shut. At the task's hour that
        flips with the weekend: the same fault, so the same key."""
        from datetime import timedelta

        from django.utils import timezone
        _bot(self.user, "p1", "paper", ["DEAD"])
        _bar("DEAD", 120.0, exchange="LSE")

        def keys(is_open):
            now = self.base + timedelta(hours=1)
            with mock.patch.object(timezone, "now", return_value=now), \
                    mock.patch("core.exchange_status.market_status_for",
                               return_value={"session": "LSE", "code": "LSE",
                                             "is_open": is_open}):
                report = pr.readiness()
            return [(b.key, str(b)) for b in report["blockers"]]

        (shut_key, shut_text), = keys(False)
        (open_key, open_text), = keys(True)
        self.assertIn("days of 4h bars", shut_text)
        self.assertIn("is OPEN", open_text)
        self.assertEqual(shut_key, open_key)

    def test_no_campaign_and_a_live_operation(self):
        from django.utils import timezone

        from signals.models_control import RuleControl
        nothing = self._report_at(0)
        self._assert_keyed(nothing)
        self.assertEqual([b.key for b in nothing["blockers"]],
                         [("no_paper",), ("no_symbol",)])
        _bot(self.user, "l1", "live", ["LATE"])
        _bar("LATE", 1.0)
        _component("actuator_mode_live", True)
        for name in ("po3_london_sweep_short", "death_cross"):
            RuleControl.objects.create(rule_name=name,
                                       promotion_stage="paper",
                                       stage_entered_at=timezone.now())
        live = self._report_at(0)
        self._assert_keyed(live)
        self.assertEqual(
            [b.key for b in live["blockers"]],
            [("stuck", ("death_cross", "po3_london_sweep_short"))])
        self.assertEqual([g.key for g in live["campaign_gaps"]],
                         [("armed", "actuator_mode_live"), ("no_paper",)])

    def test_a_finding_is_still_a_sentence_wherever_a_sentence_goes(self):
        """A plain str to whatever prints, joins, copies or stores it; the
        key rides along and survives a copy and a pickle."""
        import copy
        import json
        import pickle
        finding = pr.Finding(("bars_stopped", "NYSE", ("AAPL", "XAUUSD")),
                             "NYSE is OPEN and 2 symbol(s) have a 4h bar")
        self.assertIsInstance(finding, str)
        self.assertEqual(finding, "NYSE is OPEN and 2 symbol(s) have a 4h bar")
        self.assertIn("is OPEN", finding)
        self.assertEqual(json.dumps([finding]),
                         '["NYSE is OPEN and 2 symbol(s) have a 4h bar"]')
        for twin in (copy.copy(finding), copy.deepcopy(finding),
                     pickle.loads(pickle.dumps(finding))):
            self.assertEqual(twin, finding)
            self.assertEqual(twin.key, ("bars_stopped", "NYSE",
                                        ("AAPL", "XAUUSD")))

    def test_these_tests_have_seen_every_kind_of_finding(self):
        """A finding added to readiness() without a key, or with a kind no
        test above has looked at, fails here."""
        src = (Path(settings.BASE_DIR) / "bot_program"
               / "campaign_readiness.py").read_text(encoding="utf-8")
        self.assertNotIn(
            "blockers.append(", src,
            "a blocker is appended as a bare sentence: it has no key, so "
            "the watchdog cannot tell it from another")
        written = set(re.findall(
            r'\b(?:fault|gap|stuck)\(\s*\(\s*"([a-z_]+)"', src))
        self.assertEqual(written, self.KINDS)
