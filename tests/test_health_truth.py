# -*- coding: utf-8 -*-
"""The health surfaces are only worth reading if they are measured.

Three ways this platform's own diagnostics lied, each pinned here:

  * one 48-hour staleness rule applied to every component, so the four
    weekly ones read STALE for five days out of every seven and a 60-second
    quote poller could be ten minutes dead and read LIVE;
  * the same mark, ◌, meaning SILENT on the topology legend and NOT SET UP
    in the problem list rendered underneath it on the same page;
  * the COT node narrating a parser bug that had already been fixed, so the
    operator was sent to repair working code.

Run with:  python manage.py test tests.test_health_truth
"""
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.utils import timezone


def _component(key, **kw):
    from core.platform_control import PlatformComponent
    defaults = dict(name=key, description="", category="scraper",
                    is_enabled=True, last_status="success",
                    last_message="", run_count=10, error_count=0)
    defaults.update(kw)
    return PlatformComponent.objects.create(key=key, **defaults)


def _instrument(symbol="GC", asset_class="commodity"):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class})
    return inst


def _cot(inst, report_date, net=1000):
    from scraping.models import COTReport
    return COTReport.objects.create(
        instrument=inst, report_date=report_date,
        commercial_long=5000, commercial_short=4000,
        non_commercial_long=3000, non_commercial_short=2000,
        open_interest=20000, net_speculative=net)


# ── cadence-aware staleness ─────────────────────────────────────────────

class ComponentCadenceTests(TestCase):
    """A component is late against its OWN schedule, not against 48 hours."""

    def test_a_weekly_component_three_days_old_is_not_stale(self):
        """scraper_cot fires Saturday 00:00. Under the old blanket rule it
        read STALE from Monday to Friday every single week."""
        from dashboard.views_topology import _component_state
        comp = _component("scraper_cot",
                          last_run_at=timezone.now() - timedelta(days=3))
        state, why = _component_state(comp)
        self.assertEqual(state, "live", why)
        self.assertIn("weekly", why)

    def test_a_weekly_component_stays_live_for_six_days(self):
        from dashboard.views_topology import _component_state
        comp = _component("agent_weekly_review", category="agent",
                          last_run_at=timezone.now() - timedelta(days=6))
        self.assertEqual(_component_state(comp)[0], "live")

    def test_a_weekly_component_three_weeks_old_is_stale(self):
        """Past 2.5 missed publications the schedule really has stopped."""
        from dashboard.views_topology import _component_state
        comp = _component("pipeline_meta_allocator", category="pipeline",
                          last_run_at=timezone.now() - timedelta(days=21))
        state, why = _component_state(comp)
        self.assertEqual(state, "stale", why)

    def test_a_sixty_second_poller_ten_minutes_old_is_stale(self):
        """The quote poller feeds every open position's mark. Ten minutes
        dead is not 'fine until Thursday'."""
        from dashboard.views_topology import _component_state
        comp = _component("scraper_live_quotes",
                          last_run_at=timezone.now() - timedelta(minutes=10))
        state, why = _component_state(comp)
        self.assertEqual(state, "stale", why)
        self.assertIn("every minute", why)

    def test_a_sixty_second_poller_two_minutes_old_is_live(self):
        """One missed beat is a worker restart, not a stopped schedule."""
        from dashboard.views_topology import _component_state
        comp = _component("scraper_live_quotes",
                          last_run_at=timezone.now() - timedelta(minutes=2))
        self.assertEqual(_component_state(comp)[0], "live")

    def test_an_unscheduled_component_keeps_the_old_48h_rule(self):
        """scraper_etoro has no task and no beat entry — there is no rhythm
        to measure it against, so it keeps the blanket threshold."""
        from dashboard.views_topology import _component_state
        fresh = _component("scraper_etoro",
                           last_run_at=timezone.now() - timedelta(hours=30))
        self.assertEqual(_component_state(fresh)[0], "live")
        fresh.last_run_at = timezone.now() - timedelta(hours=60)
        fresh.save(update_fields=["last_run_at"])
        state, why = _component_state(fresh)
        self.assertEqual(state, "stale", why)
        self.assertIn("no declared cadence", why)

    def test_the_verdict_names_the_schedule_it_was_judged_against(self):
        """'STALE' with no cadence beside it is a verdict the operator has
        to take on faith."""
        from dashboard.views_topology import _component_state
        comp = _component("scraper_sec",
                          last_run_at=timezone.now() - timedelta(hours=6))
        state, why = _component_state(comp)
        self.assertEqual(state, "live", why)
        self.assertIn("daily", why)
        self.assertIn("last ran", why)

    def test_the_node_carries_its_cadence_for_the_inspector(self):
        from dashboard.views_topology import build_topology
        user = User.objects.create_user(username="ht_map", password="x")
        _component("scraper_cot", last_run_at=timezone.now() - timedelta(days=3))
        node = [n for n in build_topology(user)["nodes"]
                if n["key"] == "scraper_cot"][0]
        self.assertEqual(node["cadence"], 604800.0)
        self.assertEqual(node["cadence_label"], "weekly")


class CadenceSourceTests(SimpleTestCase):
    """The cadences must keep matching config/celery.py, or this page goes
    back to judging components against a schedule they no longer run on."""

    def test_interval_cadences_are_read_from_the_live_beat_schedule(self):
        from dashboard.views_topology import _expected_cadence
        self.assertEqual(_expected_cadence("scraper_live_quotes"), 60.0)
        self.assertEqual(_expected_cadence("pipeline_signals"), 900.0)

    def test_crontab_cadences_are_declared_because_beat_cannot_state_them(self):
        from dashboard.views_topology import _expected_cadence
        self.assertEqual(_expected_cadence("scraper_cot"), 604800.0)
        self.assertEqual(_expected_cadence("pipeline_pattern_miner"), 604800.0)
        self.assertEqual(_expected_cadence("agent_daily_briefing"), 86400.0)

    def test_an_unscheduled_component_declares_no_cadence(self):
        from dashboard.views_topology import _expected_cadence
        self.assertIsNone(_expected_cadence("scraper_etoro"))
        self.assertIsNone(_expected_cadence("pipeline_ai_journal"))

    def test_every_wired_task_still_exists_in_the_beat_schedule(self):
        """A renamed task would silently fall back to the 48h default and
        take the weekly components' STALE bug with it."""
        from config.celery import app
        from dashboard.views_topology import WIRING
        scheduled = {e.get("task") for e in app.conf.beat_schedule.values()}
        for key, wiring in WIRING.items():
            task = wiring.get("task")
            if task:
                self.assertIn(task, scheduled,
                              f"{key} names a task beat does not schedule")

    def test_every_crontab_component_declares_its_own_period(self):
        """crontab states when it next fires, not how often. Anything on a
        crontab that forgets to declare `cadence` is judged at 48h again."""
        from config.celery import app
        from dashboard.views_topology import WIRING
        by_task = {e.get("task"): e.get("schedule")
                   for e in app.conf.beat_schedule.values()}
        for key, wiring in WIRING.items():
            task = wiring.get("task")
            if not task:
                continue
            sched = by_task.get(task)
            if not isinstance(sched, (int, float, timedelta)):
                self.assertTrue(wiring.get("cadence"),
                                f"{key} runs on a crontab and declares no cadence")


# ── one mark, one meaning ───────────────────────────────────────────────

class GlyphVocabularyTests(SimpleTestCase):
    """The map page renders topology nodes and splices in the system map's
    problem list. Both drew from their own STATE_META, and ◌ appeared in the
    legend as SILENT and three inches below it as NOT SET UP."""

    def test_no_glyph_carries_two_meanings_across_the_two_vocabularies(self):
        from dashboard import views_system_map, views_topology
        meanings = {}
        for meta in list(views_topology.STATE_META.values()) + \
                list(views_system_map.STATE_META.values()):
            meanings.setdefault(meta["glyph"], set()).add(meta["label"])
        collisions = {g: sorted(v) for g, v in meanings.items() if len(v) > 1}
        self.assertEqual(collisions, {},
                         f"one mark, two meanings on one page: {collisions}")

    def test_the_hollow_ring_stays_the_not_set_up_mark(self):
        """◌ is the platform-wide 'not set up / nothing measured' mark — it
        is the empty-state icon on a dozen templates the operator reaches
        from this very map. The topology must not redefine it."""
        from dashboard import views_system_map, views_topology
        self.assertEqual(views_system_map.STATE_META["unconfigured"]["glyph"], "◌")
        self.assertNotIn("◌", {m["glyph"] for m in views_topology.STATE_META.values()})

    def test_silent_still_has_a_mark_of_its_own(self):
        from dashboard.views_topology import STATE_META
        glyph = STATE_META["silent"]["glyph"]
        self.assertTrue(glyph.strip())
        self.assertEqual(
            1, sum(1 for m in STATE_META.values() if m["glyph"] == glyph))

    def test_the_problem_list_labels_the_marks_it_borrows(self):
        """Those states have no row in the map's own legend, so the mark has
        to say what it means without one."""
        from pathlib import Path

        from django.conf import settings
        tpl = (Path(settings.BASE_DIR) / "templates" / "dashboard"
               / "system_map.html").read_text(encoding="utf-8")
        block = tpl[tpl.index("tm-problem\">"):tpl.index("tm-problem-body")]
        self.assertIn("p.meta.label", block)


class SilentIsWhatTheGateRecordsTests(TestCase):
    """SILENT is not a mood — it is core.task_gate's 'warning' verdict, the
    one raised when a task handles rows and stores none."""

    def test_a_task_that_parsed_and_stored_nothing_reads_silent(self):
        from core.task_gate import judge_result
        from dashboard.views_topology import _component_state
        status, msg = judge_result({"parsed": 42, "stored": 0})
        self.assertEqual(status, "warning")
        comp = _component("scraper_news", last_status=status, last_message=msg,
                          last_run_at=timezone.now())
        state, why = _component_state(comp)
        self.assertEqual(state, "silent")
        self.assertIn("42", why)

    def test_a_skipped_key_with_a_reason_is_the_not_configured_verdict(self):
        """The vocabulary the gate already speaks: a missing credential is
        'not configured', not a crash and not a clean run."""
        from core.task_gate import judge_result
        status, msg = judge_result({"skipped": "FMP_API_KEY missing"})
        self.assertEqual(status, "warning")
        self.assertIn("not configured", msg)


# ── the COT node says what it measured ──────────────────────────────────

class CotNodeTests(TestCase):
    """It used to hardcode a diagnosis — 'the CFTC parser reads column names
    that the current release does not use' — and kept stating it after the
    parser was rewritten positional and verified storing rows."""

    def setUp(self):
        self.user = User.objects.create_user(username="ht_cot", password="x")

    def _cot_node(self):
        from dashboard.views_system_map import collect_system_map
        data = collect_system_map(self.user)
        return [n for st in data["stages"] for n in st["nodes"]
                if n["key"] == "cot"][0]

    def test_a_fresh_report_reads_live_and_names_the_report_date(self):
        inst = _instrument()
        newest = timezone.now().date() - timedelta(days=4)
        _cot(inst, newest)
        _cot(inst, newest - timedelta(days=7))
        n = self._cot_node()
        self.assertEqual(n["state"], "live", n["why"])
        self.assertIn(str(newest), n["why"])
        self.assertEqual(n["metric"], 2)

    def test_two_missed_weekly_releases_read_stale(self):
        inst = _instrument()
        _cot(inst, timezone.now().date() - timedelta(days=30))
        n = self._cot_node()
        self.assertEqual(n["state"], "stale", n["why"])
        self.assertIn("30 days old", n["why"])

    def test_a_ten_day_gap_is_not_stale_because_the_source_is_weekly(self):
        """A daily threshold would have flagged the normal gap between two
        CFTC publications."""
        inst = _instrument()
        _cot(inst, timezone.now().date() - timedelta(days=10))
        self.assertEqual(self._cot_node()["state"], "live")

    def test_the_empty_table_no_longer_blames_the_parser(self):
        n = self._cot_node()
        self.assertEqual(n["state"], "idle", n["why"])
        self.assertNotIn("column name", n["why"].lower())

    def test_the_verdict_is_computed_not_written_down(self):
        """The failing shape: a row count that changes while the sentence
        underneath it does not."""
        inst = _instrument()
        _cot(inst, timezone.now().date() - timedelta(days=3))
        first = self._cot_node()["why"]
        _cot(_instrument("SI"), timezone.now().date() - timedelta(days=3))
        self.assertNotEqual(first, self._cot_node()["why"])
