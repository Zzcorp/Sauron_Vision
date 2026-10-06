"""The day of Sauron is read off the beat, not typed.

core.day_of_sauron groups config/celery.py's beat_schedule into the seven
stages the Wall and the home page draw. These tests pin the two promises
that make the picture worth trusting: every entry of the real schedule has
a stage (a new beat entry fails the suite until someone places it), and
every cadence on the page is the schedule's own words, so a rhythm changed
in celery.py changes on the page with the next request.

Run with:  python manage.py test tests.test_day_of_sauron
"""
import json
from unittest import mock

from celery.schedules import crontab
from django.test import SimpleTestCase, TestCase

from core import day_of_sauron as day
from config.celery import app


def _when(scheme, entry_key):
    for stage in scheme["stages"]:
        for task in stage["tasks"]:
            if task["key"] == entry_key:
                return task["when"]
    raise AssertionError(f"{entry_key} is not on the picture")


def _stage_of(scheme, entry_key):
    for stage in scheme["stages"]:
        if any(t["key"] == entry_key for t in stage["tasks"]):
            return stage["key"]
    return None


class EveryBeatEntryHasAStageTests(SimpleTestCase):
    def test_the_real_schedule_is_placed_whole(self):
        scheme = day.day_scheme()
        self.assertEqual(
            [t["key"] for t in scheme["unplaced"]], [],
            "a beat entry has no stage in core.day_of_sauron.STAGE_OF — "
            "place it, so the picture keeps telling the whole schedule")
        self.assertEqual(scheme["total"], len(app.conf.beat_schedule))
        self.assertEqual(sum(s["count"] for s in scheme["stages"]), scheme["total"])
        self.assertGreater(scheme["total"], 60)

    def test_seven_stages_in_the_ring_s_order(self):
        scheme = day.day_scheme()
        self.assertEqual([s["title"] for s in scheme["stages"]],
                         ["SEE", "THINK", "DECIDE", "ACT", "WATCH", "TELL", "LEARN"])
        self.assertEqual([s["n"] for s in scheme["stages"]], list(range(1, 8)))
        for stage in scheme["stages"]:
            self.assertGreater(stage["count"], 0, stage["title"])
            self.assertTrue(stage["job"].endswith("."), stage["job"])
            self.assertTrue(stage["next"].startswith("Feeds "), stage["next"])
            self.assertEqual(stage["fastest"], stage["tasks"][0]["when"])
            # The rows are the tasks grouped by cadence, in cadence order.
            self.assertEqual([r["when"] for r in stage["rows"]],
                             [w for i, w in enumerate(t["when"] for t in stage["tasks"])
                              if i == 0 or stage["tasks"][i - 1]["when"] != w])

    def test_the_stages_read_as_the_operator_placed_them(self):
        scheme = day.day_scheme()
        for key, stage in (("poll-telegram-eye", "tell"),
                           ("tick-asset-bots", "decide"),
                           ("run-morgul-guards", "watch"),
                           ("run-signal-engine", "think"),
                           ("fetch-live-quotes-watchlist", "see"),
                           ("retry-pending-closes", "act"),
                           ("sauron-consolidation-nightly", "learn"),
                           # Review, 2026-09-29: market data is SEE, the
                           # night's governance and grading is LEARN, a
                           # watcher of open positions is WATCH, an alert
                           # scanner is TELL.
                           ("ibkr-data-feed", "see"),
                           ("refresh-option-chains", "see"),
                           ("propose-rule-actions", "learn"),
                           ("propose-strategy-evolutions", "learn"),
                           ("grade-capital-desk", "learn"),
                           ("sauron-position-review", "watch"),
                           ("scan-funding-signals", "tell")):
            self.assertEqual(_stage_of(scheme, key), stage, key)

    def test_no_typed_count_rides_a_label(self):
        """The Wall's numbers are counted, never typed: 'ten guards' would
        drift the day an eleventh lands."""
        import re
        for key, (_stage, label) in day.STAGE_OF.items():
            self.assertIsNone(
                re.search(r"\b(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\b",
                          label.lower()), f"{key}: {label}")

    def test_a_new_beat_entry_is_counted_and_named_not_dropped(self):
        extra = {"zz-something-new": {"task": "zz.tasks.new_thing", "schedule": 42.0}}
        with mock.patch.dict(app.conf.beat_schedule, extra):
            scheme = day.day_scheme()
        self.assertEqual(scheme["total"], len(app.conf.beat_schedule) + 1)
        self.assertEqual([t["key"] for t in scheme["unplaced"]], ["zz-something-new"])
        self.assertEqual(scheme["unplaced"][0]["when"], "42 s")
        self.assertEqual(scheme["unplaced"][0]["label"], "zz-something-new")

    def test_a_schedule_it_cannot_read_never_blanks_the_page(self):
        """Review, 2026-09-29: an unreadable schedule (a custom
        BaseSchedule, a solar event) had period Infinity, json_script
        wrote `Infinity`, the ring's JSON.parse threw and the drawing
        stayed blank. The period is None now and the JSON is strict."""
        from celery.schedules import BaseSchedule

        class Odd(BaseSchedule):
            """Neither a crontab nor an interval: a custom schedule."""

        odd = Odd()
        with mock.patch.dict(app.conf.beat_schedule,
                             {"zz-odd": {"task": "zz.tasks.odd", "schedule": odd}}):
            scheme = day.day_scheme()
        self.assertEqual(scheme["unplaced"][0]["seconds"], None)
        self.assertEqual(scheme["unplaced"][0]["widest"], None)
        self.assertEqual(scheme["unplaced"][0]["when"], "Odd")
        json.dumps(scheme, allow_nan=False)
        blob = json.dumps(day.page_scheme(scheme), allow_nan=False)
        self.assertEqual(json.loads(blob)["unplaced"], 1)
        self.assertEqual(day.schedule_words(None)[1], None)


class ThePageCopyTests(SimpleTestCase):
    """page_scheme: what the drawing reads, and nothing else — the public
    Wall shipped every task's import path, beat key and queue to every
    visitor while the drawing read none of it (review, 2026-09-29)."""

    def test_it_keeps_what_the_ring_draws_and_drops_the_internals(self):
        full = day.day_scheme({"instruments": 5})
        page = day.page_scheme(full)
        blob = json.dumps(page, allow_nan=False)
        for internal in ("bot_program.tasks", "market_data.tasks", '"task"',
                         '"queue"', "run-morgul-guards", '"widest"'):
            self.assertNotIn(internal, blob, internal)
        for stage in page["stages"]:
            self.assertEqual(set(stage), {"key", "n", "title", "job", "next", "rows",
                                          "count", "fastest", "pace", "facts"})
        self.assertEqual(page["total"], full["total"])
        self.assertEqual(page["queues"], full["queues"])
        self.assertEqual(page["unplaced"], 0)
        self.assertLess(len(blob), len(json.dumps(full)) / 2)


class TheCadencesAreTheSchedulesOwnWordsTests(SimpleTestCase):
    def test_interval_entries(self):
        scheme = day.day_scheme()
        self.assertEqual(_when(scheme, "poll-telegram-eye"), "15 s")
        self.assertEqual(_when(scheme, "fetch-live-quotes-watchlist"), "60 s")
        self.assertEqual(_when(scheme, "tick-asset-bots"), "5 min")
        self.assertEqual(_when(scheme, "refresh-bot-bars"), "10 min")
        self.assertEqual(_when(scheme, "sync-etoro-accounts"), "15 min")
        self.assertEqual(_when(scheme, "sauron-mind-synthesize"), "1 h")
        self.assertEqual(_when(scheme, "sauron-critic-pass"), "2 h")
        self.assertEqual(_when(scheme, "fetch-tradingview-ideas"), "6 h")

    def test_crontab_entries(self):
        scheme = day.day_scheme()
        self.assertEqual(_when(scheme, "sauron-consolidation-nightly"), "03:00")
        self.assertEqual(_when(scheme, "fetch-eod-prices-full-universe"), "22:30")
        self.assertEqual(_when(scheme, "fetch-cot-reports"), "Sat 00:00")
        self.assertEqual(_when(scheme, "ai-monday-game-plan"), "Sun 18:00")
        self.assertEqual(_when(scheme, "sauron-horizon-monthly"), "1st 04:45")
        self.assertEqual(_when(scheme, "propose-share-plans"), "every 4 h at :05")
        self.assertEqual(_when(scheme, "refresh-option-chains"), "hourly 13:15–20:15")
        self.assertEqual(_when(scheme, "reconcile-asset-bot-trades"),
                         "every 15 min")

    def test_a_changed_cadence_changes_the_words(self):
        entry = dict(app.conf.beat_schedule["tick-asset-bots"])
        entry["schedule"] = 1800.0
        with mock.patch.dict(app.conf.beat_schedule, {"tick-asset-bots": entry}):
            self.assertEqual(_when(day.day_scheme(), "tick-asset-bots"), "30 min")
        entry["schedule"] = crontab(hour=21, minute=5)
        with mock.patch.dict(app.conf.beat_schedule, {"tick-asset-bots": entry}):
            self.assertEqual(_when(day.day_scheme(), "tick-asset-bots"), "21:05")

    def test_the_words_of_every_crontab_shape(self):
        self.assertEqual(day.crontab_words(crontab(minute=0, hour="*"))[0], "hourly at :00")
        self.assertEqual(day.crontab_words(crontab(minute="*/30"))[0], "every 30 min")
        self.assertEqual(day.crontab_words(crontab(minute=0, hour="9,17"))[0], "at 09:00, 17:00")
        self.assertEqual(day.crontab_words(crontab(minute=0, hour=4, day_of_week="1,5"))[0],
                         "Mon · Fri 04:00")
        words, period, first = day.crontab_words(crontab(minute=45, hour=4, day_of_month=1))
        self.assertEqual((words, period, first), ("1st 04:45", 30 * 86400.0, 4 * 60 + 45))
        self.assertEqual(day.interval_words(45), "45 s")
        self.assertEqual(day.interval_words(90), "1.5 min")
        self.assertEqual(day.interval_words(172800), "2 d")

    def test_every_calendar_restriction_survives_every_shape(self):
        """Review, 2026-09-29: the weekday survived only on a single daily
        fire, the day of the month dropped it, the month was never read,
        and a step that does not divide the hour read as a list of times.
        The three entries commented "≈ NYSE hours" are one mon-fri edit
        away from each of those."""
        words = lambda **kw: day.crontab_words(crontab(**kw))[0]  # noqa: E731
        self.assertEqual(words(minute="*/15", hour="13-21", day_of_week="mon-fri"),
                         "Mon–Fri every 15 min, 13:00–21:45")
        self.assertEqual(words(minute=0, hour="*/4", day_of_week="sat"),
                         "Sat every 4 h at :00")
        self.assertEqual(words(minute=0, hour=9, month_of_year=1), "Jan 09:00")
        self.assertEqual(words(minute=0, hour=9, day_of_month=1, day_of_week="mon"),
                         "1st · Mon 09:00")
        self.assertEqual(words(minute=0, hour=9, day_of_week="sat,sun"),
                         "Sat · Sun 09:00")
        self.assertEqual(words(minute=15, hour="13-20", day_of_week="mon-fri"),
                         "Mon–Fri hourly 13:15–20:15")
        self.assertEqual(words(minute="*/15", hour="9,17"),
                         "every 15 min during 09h, 17h")
        w, period, _first = day.crontab_words(crontab(minute="*/7"))
        self.assertEqual(w, "every 7 min (:00–:56 each hour)")
        self.assertEqual(period, 7 * 60.0)
        # The period is the time-of-day gap when it fires more than once a
        # day, the calendar's when once.
        self.assertEqual(day.crontab_words(crontab(minute=0, hour="*/4", day_of_week="sat"))[1],
                         4 * 3600.0)
        self.assertEqual(day.crontab_words(crontab(minute=0, hour=9, month_of_year=1))[1],
                         365 * 86400.0)
        # Monday-first inside the week: Saturday sorts before Sunday.
        sat = day.crontab_words(crontab(minute=0, hour=9, day_of_week="sat"))[2]
        sun = day.crontab_words(crontab(minute=0, hour=9, day_of_week="sun"))[2]
        self.assertLess(sat, sun)

    def test_the_widest_gap_is_what_staleness_reads(self):
        """An hourly 13:15–20:15 entry is silent all night by design; its
        widest gap (the digest's own reading) is what a staleness
        judgement must use, never its hourly beat. (The reconcile was the
        example until 2026-10-06, when it began to run around the clock.)"""
        scheme = day.day_scheme()
        chains = next(t for s in scheme["stages"] for t in s["tasks"]
                      if t["key"] == "refresh-option-chains")
        self.assertEqual(chains["seconds"], 3600.0)
        self.assertEqual(chains["widest"], (24 - 20.25 + 13.25) * 3600.0)
        rec = next(t for s in scheme["stages"] for t in s["tasks"]
                   if t["key"] == "reconcile-asset-bot-trades")
        self.assertEqual((rec["seconds"], rec["widest"]),
                         (15 * 60.0, 15 * 60.0))
        eye = next(t for s in scheme["stages"] for t in s["tasks"]
                   if t["key"] == "poll-telegram-eye")
        self.assertEqual(eye["widest"], 15.0)

    def test_the_pace_says_a_speed_or_a_clock_never_a_clock_as_a_speed(self):
        scheme = day.day_scheme()
        pace = {s["key"]: s["pace"] for s in scheme["stages"]}
        self.assertEqual(pace["tell"], "fastest 15 s")
        self.assertEqual(pace["learn"], "first at 02:30")
        self.assertFalse(any(p.startswith("fastest ") and ":" in p for p in pace.values()), pace)

    def test_within_a_stage_the_fast_come_first_then_the_clock(self):
        scheme = day.day_scheme()
        learn = next(s for s in scheme["stages"] if s["key"] == "learn")
        secs = [t["seconds"] for t in learn["tasks"]]
        self.assertEqual(secs, sorted(secs))
        daily = [t for t in learn["tasks"] if t["seconds"] == 86400.0]
        self.assertEqual([t["first"] for t in daily], sorted(t["first"] for t in daily))


class TheQueuesAreResolvedLikeCeleryTests(SimpleTestCase):
    def test_exact_name_beats_the_glob_then_the_glob_then_default(self):
        routes = dict(app.conf.task_routes)
        self.assertEqual(day.queue_of("market_data.tasks.fetch_fred_updates", routes), "slow")
        self.assertEqual(day.queue_of("market_data.tasks.fetch_live_quotes", routes), "fast")
        self.assertEqual(day.queue_of("ai_agents.tasks.generate_daily_briefing", routes), "ai")
        self.assertEqual(day.queue_of("bot_program.tasks.tick_all_asset_bots", routes), "default")
        self.assertEqual(day.queue_of("nothing.at.all", {}), "default")

    def test_the_totals_count_every_queue(self):
        scheme = day.day_scheme()
        self.assertEqual(sum(scheme["queues"].values()), scheme["total"])
        self.assertLessEqual(set(scheme["queues"]), {"fast", "default", "slow", "ai"})
        self.assertEqual(scheme["fastest"], "15 s")


class TheFactsComeFromTheWallTests(TestCase):
    def test_the_counts_are_the_walls_and_a_missing_one_reads_zero(self):
        scheme = day.day_scheme({"instruments": 195, "news_24h": 12, "broker_adapters": 8})
        see = next(s for s in scheme["stages"] if s["key"] == "see")
        self.assertEqual(see["facts"], [[195, "instruments followed"],
                                        [12, "news items read in the last 24 h"]])
        think = next(s for s in scheme["stages"] if s["key"] == "think")
        self.assertEqual(think["facts"][0][0], 0)
        self.assertEqual(scheme["adapters"], 8)
        for stage in scheme["stages"]:
            for n, words in stage["facts"]:
                self.assertIsInstance(n, int)
                self.assertNotIsInstance(n, bool)
                self.assertTrue(words)

    def test_it_reads_no_database(self):
        with self.assertNumQueries(0):
            day.day_scheme({"instruments": 3})

    def test_it_is_json_for_the_page(self):
        blob = json.dumps(day.day_scheme({"bots": 4}), allow_nan=False)
        self.assertNotIn("{{", blob)
        self.assertNotIn("{%", blob)
        # The Wall forbids these words (tests/test_the_wall.py); the picture
        # goes on the Wall, so its wording may not carry them either.
        low = blob.lower()
        for word in ("proven", "phase-", "phase ", "outperform", "beats the market",
                     "fully autonomous", "hands-free", "no human needed", "667"):
            self.assertNotIn(word, low, word)


class BeatComponentsTests(SimpleTestCase):
    def test_gated_entries_name_their_component_and_ungated_ones_are_absent(self):
        mapping = day.beat_components()
        self.assertEqual(mapping.get("run-morgul-guards"), "morgul_guards")
        self.assertEqual(mapping.get("tick-asset-bots"), "pipeline_asset_bots")
        self.assertIn("run-signal-engine", mapping)
        self.assertNotIn("refresh-saxo-sessions", mapping)
        self.assertLessEqual(set(mapping), set(app.conf.beat_schedule))
