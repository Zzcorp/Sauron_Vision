"""The Mind is read until its next report lands (2026-10-24, PR2 item 1).

What "the Mind says X" means where it is read (brain/context.py): the
newest error-free BrainReport younger than `mind_fresh_minutes()` is the
Mind's current word. That window is the synthesis beat's widest gap plus
MIND_GRACE_MINUTES, read from the beat itself (config/celery.py), so 75
minutes on today's hourly beat.

Before this, every reader that did not pass its own window used 45
minutes, a figure left over from a 30-minute cadence. From minute 45 until
the next report landed, a fresh live-evidence pause stopped blocking bot
entries (the BRAIN_PAUSED skip in bot_program/asset_engine/base.py), the
theme squeeze lifted, the debate and council prompts lost the Mind's block
and the crisis score dropped its "brain" component.

Run with:  python manage.py test tests.test_mind_contract
"""
from datetime import timedelta
from unittest import mock
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from tests.test_desk_seam import ROUTER, _client, _config, _signal, _user


def _report(age_minutes, **kw):
    """A clean report `age_minutes` old (created_at is auto_now_add)."""
    from brain.models import BrainReport
    fields = dict(regime_label="risk_off", regime_confidence=0.8,
                  portfolio_health_score=0.5,
                  theme_pressures={"usd_long": 1.0},
                  rule_status_overlay={"mc_paused": "pause_recommended",
                                       "mc_watch": "watch"},
                  rule_status_venue={"mc_paused": "live",
                                     "mc_watch": "live"},
                  narrative_md="synthetic")
    fields.update(kw)
    r = BrainReport.objects.create(**fields)
    BrainReport.objects.filter(pk=r.pk).update(
        created_at=timezone.now() - timedelta(minutes=age_minutes))
    r.refresh_from_db()
    return r


def _beat(schedule):
    """Patch the Mind's beat entry in the loaded Celery app."""
    from brain.context import MIND_BEAT_KEY
    from config.celery import app
    entry = dict(app.conf.beat_schedule[MIND_BEAT_KEY], schedule=schedule)
    return mock.patch.dict(app.conf.beat_schedule, {MIND_BEAT_KEY: entry})


class TheMindIsReadUntilTheNextOneLandsTests(TestCase):

    def test_the_window_covers_the_beat_and_its_grace(self):
        from brain.context import (MIND_BEAT_KEY, MIND_GRACE_MINUTES,
                                   mind_fresh_minutes)
        from config.celery import app
        beat = app.conf.beat_schedule[MIND_BEAT_KEY]["schedule"]
        self.assertGreaterEqual(mind_fresh_minutes() * 60,
                                float(beat) + MIND_GRACE_MINUTES * 60)
        self.assertEqual(mind_fresh_minutes(), 75)

    def test_the_window_is_derived_from_the_beat_not_copied(self):
        from celery.schedules import crontab, schedule
        from brain.context import mind_fresh_minutes
        for sched, want in ((7200.0, 135), (timedelta(hours=2), 135),
                            (crontab(minute=0), 75),
                            (schedule(timedelta(minutes=90)), 105)):
            with _beat(sched):
                self.assertEqual(mind_fresh_minutes(), want, sched)

    def test_an_unreadable_beat_falls_back_to_an_hour(self):
        from brain.context import MIND_BEAT_KEY, mind_fresh_minutes
        from config.celery import app
        with _beat(object()):
            self.assertEqual(mind_fresh_minutes(), 75)
        with _beat(0):
            self.assertEqual(mind_fresh_minutes(), 75)
        # patch.dict restores the whole schedule on exit
        with mock.patch.dict(app.conf.beat_schedule):
            del app.conf.beat_schedule[MIND_BEAT_KEY]
            self.assertEqual(mind_fresh_minutes(), 75)
        self.assertIn(MIND_BEAT_KEY, app.conf.beat_schedule)
        with mock.patch("core.day_of_sauron.widest_gap",
                        side_effect=RuntimeError("boom")):
            self.assertEqual(mind_fresh_minutes(), 75)

    def test_a_report_fifty_and_seventy_minutes_old_is_still_the_minds_word(self):
        from brain import context as c
        for age in (50, 70):
            from brain.models import BrainReport
            BrainReport.objects.all().delete()
            _report(age)
            self.assertIsNotNone(c.get_brain_context(), age)
            status, why = c.brain_rule_advisory("mc_paused")
            self.assertEqual(status, "pause_recommended", age)
            self.assertIn("brain_report", why)
            self.assertLess(c.brain_theme_pressure_multiplier("usd_long"),
                            1.0, age)
            self.assertNotEqual(c.context_for_prompt(), "", age)

    def test_past_the_window_every_reader_still_fails_open(self):
        """A guard, not a fix: this already held at 45 minutes and must
        keep holding at 75 (critique L1)."""
        from brain import context as c
        _report(80)
        self.assertIsNone(c.get_brain_context())
        self.assertEqual(c.brain_rule_advisory("mc_paused"), ("allow", ""))
        self.assertEqual(c.brain_theme_pressure_multiplier("usd_long"), 1.0)
        self.assertEqual(c.context_for_prompt(), "")

    def test_an_explicit_window_is_still_the_callers(self):
        """A guard: the share allocator (90), /shares/ (90) and the
        horizon (180) keep their own windows."""
        from brain.context import get_brain_context
        _report(80)
        self.assertIsNotNone(get_brain_context(max_age_minutes=90))
        self.assertIsNone(get_brain_context(max_age_minutes=60))

    def test_a_newer_errored_report_does_not_hide_the_clean_one(self):
        from brain import context as c
        _report(50)
        _report(5, error="the model timed out", rule_status_overlay={})
        ctx = c.get_brain_context()
        self.assertIsNotNone(ctx)
        self.assertEqual(ctx["rule_status_overlay"].get("mc_paused"),
                         "pause_recommended")

    def test_low_trust_still_softens_a_report_pause_inside_the_window(self):
        from brain.context import brain_rule_advisory
        _report(50)
        with patch("brain.context._brain_trust_score", return_value=0.2):
            status, why = brain_rule_advisory("mc_paused")
        self.assertEqual(status, "watch")
        self.assertIn("softened", why)

    def test_the_synthesizer_stamps_valid_until_from_the_same_window(self):
        from brain.synthesizer import _persist_report
        report = _persist_report(
            parsed={"regime_label": "trending"}, snapshot={},
            model="t", tokens_in=0, tokens_out=0, cost_usd=0.0,
            n_consumed=0)
        span = (report.valid_until - report.created_at).total_seconds()
        self.assertAlmostEqual(span, 75 * 60, delta=5)
        with _beat(7200.0):
            report = _persist_report(
                parsed={"regime_label": "trending"}, snapshot={},
                model="t", tokens_in=0, tokens_out=0, cost_usd=0.0,
                n_consumed=0)
        span = (report.valid_until - report.created_at).total_seconds()
        self.assertAlmostEqual(span, 135 * 60, delta=5)

    def test_the_unread_second_freshness_is_gone(self):
        from brain.models import BrainReport
        self.assertFalse(hasattr(BrainReport, "is_fresh"))


class TheReadersOfTheWindowTests(TestCase):

    def test_a_bot_entry_fifty_minutes_after_a_live_pause_is_skipped(self):
        """A REAL report, not a patched advisory: the entry gate reads it
        through brain_rule_advisory (base.py's BRAIN_PAUSED skip)."""
        from bot_program.asset_engine import StockBot, skips
        from bot_program.models import AssetBotTrade
        _report(50, rule_status_overlay={"parked_rule": "pause_recommended"},
                rule_status_venue={"parked_rule": "live"})
        cfg = _config(_user("mc_entry"), symbols=["MCE1"])
        _signal("MCE1", "bullish", 0.85, rule="parked_rule")
        bot = StockBot(cfg)
        with patch(ROUTER, return_value=_client()) as router:
            self.assertIsNone(bot.scan_symbol("MCE1"))
        router.assert_not_called()
        cfg.refresh_from_db()
        note = skips.last_by_symbol(cfg)["MCE1"]
        self.assertEqual(note["code"], skips.BRAIN_PAUSED)
        self.assertIn("brain_report", note["detail"])
        self.assertEqual(AssetBotTrade.objects.count(), 0)

    def test_the_stress_read_keeps_the_minds_component_inside_the_window(self):
        from bot_program import market_stress
        _report(50)
        components, _ = market_stress.read_components()
        self.assertEqual(components.get("brain"),
                         {"label": "risk_off", "confidence": 0.8})

    def test_the_position_review_fingerprint_is_stable_fifty_minutes_after_a_report(self):
        """Critique M5: the review's fingerprint carries the advisory, and
        the 30-minute review pass re-asked the model every hour when the
        report's pause lapsed at minute 45."""
        from brain.models import BrainReport
        from brain.position_review import _rule_state, facts_fingerprint
        r = _report(20, rule_status_overlay={"fp_rule": "pause_recommended"},
                    rule_status_venue={"fp_rule": "live"})
        pos = {"rule_name": "fp_rule"}
        at_20 = facts_fingerprint({"rule_state": _rule_state(pos)}, [])
        self.assertEqual(_rule_state(pos)["advisory"], "pause_recommended")
        BrainReport.objects.filter(pk=r.pk).update(
            created_at=timezone.now() - timedelta(minutes=50))
        at_50 = facts_fingerprint({"rule_state": _rule_state(pos)}, [])
        self.assertEqual(at_20, at_50)

    def test_the_council_band_is_overdue_past_the_same_window(self):
        from brain.models import BrainReport
        from dashboard import council_band as B
        from django.contrib.auth.models import User
        user = User.objects.create_user(username="mc_band", password="x",
                                        is_staff=True)

        def thinks(minutes):
            cache.clear()
            BrainReport.objects.all().delete()
            _report(minutes)
            return B.build_room(user)["direction"]["thinks"]["t"]

        self.assertNotIn("(overdue)", thinks(74))
        self.assertIn("(overdue)", thinks(76))
        # Derived, not a second copy of 75 (critique L1): a two-hour beat
        # is not overdue at 76 minutes, and is past its own window.
        with _beat(7200.0):
            self.assertNotIn("(overdue)", thinks(76))
            self.assertIn("(overdue)", thinks(140))


class NoSecondCopyOfTheWindowTests(TestCase):
    """Review F11: the Orcs kept their own 75, the system map called the
    Mind live up to two hours ("every 30 minutes"), and /brain/ still said
    30 minutes. Each now reads brain.context.mind_fresh_minutes()."""

    def test_the_orcs_read_the_mind_by_the_contracts_window(self):
        from bot_program.orcs import sources
        self.assertFalse(hasattr(sources, "MIND_FRESH_MIN"))

        def mind(minutes):
            from brain.models import BrainReport
            BrainReport.objects.all().delete()
            _report(minutes)
            return sources.mind(timezone.now())

        self.assertEqual(mind(70)["dash"], "")
        self.assertIn("overdue", mind(80)["dash"])
        with _beat(7200.0):
            self.assertEqual(mind(80)["dash"], "")
            self.assertIn("overdue", mind(140)["dash"])

    def test_the_system_map_calls_the_mind_stale_past_the_window(self):
        from django.contrib.auth.models import User
        from dashboard.views_system_map import collect_system_map
        user = User.objects.create_superuser("mc_map", "mc_map@example.test",
                                             "x")

        def brain_node(minutes):
            from brain.models import BrainReport
            BrainReport.objects.all().delete()
            _report(minutes)
            for stage in collect_system_map(user)["stages"]:
                for n in stage["nodes"]:
                    if n["key"] == "brain":
                        return n
            self.fail("no brain node")

        self.assertEqual(brain_node(70)["state"], "live")
        stale = brain_node(80)
        self.assertEqual(stale["state"], "stale")
        self.assertIn("synthesises every 60 min and the bots read a report "
                      "for 75 min", stale["why"])
        self.assertNotIn("30 minutes", stale["why"])
        with _beat(7200.0):
            self.assertEqual(brain_node(80)["state"], "live")

    def test_the_brain_page_names_the_hourly_cadence(self):
        from django.contrib.auth.models import User
        self.client.force_login(User.objects.create_user(
            username="mc_brain", password="x"))
        html = self.client.get("/brain/").content.decode()
        self.assertIn("The synthesizer runs every hour", html)
        self.assertNotIn("every 30 minutes", html)
