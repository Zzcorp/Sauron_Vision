"""A day of Sauron, live, on the home page.

The Wall draws the loop the platform turns every day; /command/ draws the
same ring with the state of NOW on it (2026-09-29: "a similar design for
the welcome home page of the logged account with live data on it, and a
lot of metrics depicting every cycles, steps and process"). The live layer
is one JSON door, /api/day/live/ (dashboard.views_day), and one static
script, static/js/sv-day-live.js, over the ring static/js/sv-day-scheme.js
already draws.

What is pinned here:
  - the door needs a login, is per-user, never caches, and answers the
    seven stages with states from one vocabulary;
  - a stage's state is read off the PlatformComponent rows the task gate
    writes, judged against each beat entry's own cadence: a row that ran a
    minute ago is live, three days ago is stale, switched off is off, a
    failed run is broken, an entry the gate does not wrap is quiet;
  - the metrics move when rows land (a signal, a notification, a trade),
    a missing Morgul summary never raises, and a group that fails logs at
    WARNING and reads its fallback while the door still answers;
  - a query ceiling — one query for every component row, never one per
    entry;
  - the 24-hour strip's marks are exactly the daily crontab entries;
  - /command/ carries the ring, the panel, the JSON, the door's URL, the
    two scripts, the sheet and the localStorage key — and still every
    string tests/test_command_center.py asserts;
  - the new script parses under node, carries no template tag and opens
    no socket.

Run with:  python manage.py test tests.test_day_live
"""
import json
import re
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import User
from django.core.cache import cache
from django.db import connection
from django.test import SimpleTestCase, TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from config.celery import app
from core import day_of_sauron as day

URL = "/api/day/live/"
JS = Path(settings.BASE_DIR) / "static" / "js" / "sv-day-live.js"
RING_JS = Path(settings.BASE_DIR) / "static" / "js" / "sv-day-scheme.js"
SHEET = Path(settings.BASE_DIR) / "static" / "css" / "sv-day-scheme.css"
PAGE = Path(settings.BASE_DIR) / "templates" / "dashboard" / "command.html"

STATES = {"live", "stale", "off", "quiet", "broken"}
STAGE_KEYS = ["see", "think", "decide", "act", "watch", "tell", "learn"]


def _user(name="dl_u", staff=True):
    """The live door is for staff (review, 2026-09-29); every test that
    reads it signs in as staff unless it is testing the refusal."""
    return User.objects.create_user(username=name, password="x", is_staff=staff)


def _master(enabled=True):
    """The master switch's row. The gate reads a missing row as OFF, and so
    does the page: a test that expects a live stage seeds it on."""
    return _component("platform_master", ago=timedelta(minutes=1), enabled=enabled)


def _component(key, *, ago=None, enabled=True, status="success", message=""):
    from core.platform_control import PlatformComponent
    return PlatformComponent.objects.create(
        key=key, name=key, category="system", is_enabled=enabled,
        last_run_at=(timezone.now() - ago) if ago is not None else None,
        last_status=status, last_message=message, run_count=1)


def _config(user, name="B1", **kw):
    from decimal import Decimal
    from bot_program.models import AssetBotConfig
    defaults = dict(enabled=True, mode="paper", symbols=[],
                    capital=Decimal("10000"), base_currency="USD")
    defaults.update(kw)
    return AssetBotConfig.objects.create(
        user=user, asset_class="crypto", name=name, **defaults)


def _trade(user, status="OPEN", **kw):
    from decimal import Decimal
    from bot_program.models import AssetBotTrade
    cfg = kw.pop("config", None) or _config(user, name=f"cfg-{status}")
    return AssetBotTrade.objects.create(
        config=cfg, asset_class=cfg.asset_class, symbol="BTCUSD", side="BUY",
        qty=Decimal("1"), entry_price=Decimal("100"), status=status, **kw)


def _json_on(body):
    m = re.search(r'<script id="dayData" type="application/json">(.*?)</script>',
                  body, re.S)
    assert m, "the day's json_script is not on the page"
    return json.loads(m.group(1))


# ── 1. The door ──────────────────────────────────────────────────────────

class TheDoorTests(TestCase):
    def setUp(self):
        self.user = _user()
        self.client.force_login(self.user)

    def test_it_needs_a_login(self):
        self.client.logout()
        self.assertIn(self.client.get(URL).status_code, (302, 403))

    def test_it_answers_the_seven_stages_in_one_vocabulary(self):
        r = self.client.get(URL)
        self.assertEqual(r.status_code, 200)
        live = r.json()
        self.assertEqual(list(live["stages"]), STAGE_KEYS)
        for key in STAGE_KEYS:
            st = live["stages"][key]
            self.assertIn(st["state"], STATES, key)
            self.assertTrue(st["words"], key)
            self.assertIsInstance(st["metrics"], list)
            for n, words in st["metrics"]:
                self.assertIsInstance(n, (int, float))
                self.assertNotIsInstance(n, bool)
                self.assertTrue(words)
        self.assertIn(live["beat"]["state"], STATES)
        self.assertEqual(set(live["clusters"]), {"markets", "venues", "people"})
        for c in live["clusters"].values():
            self.assertIn(c["state"], STATES)
        self.assertRegex(live["now"], r"^\d\d:\d\d UTC$")
        self.assertEqual(set(live["tasks"]), set(app.conf.beat_schedule))
        for t in live["tasks"].values():
            self.assertIn(t["state"], STATES)
        self.assertEqual(live["counts"]["total"], len(app.conf.beat_schedule))

    def test_it_is_never_cached(self):
        r = self.client.get(URL)
        self.assertIn("no-store", r["Cache-Control"])

    def test_it_is_per_user(self):
        from alerts.models import Notification
        other = _user("dl_other")
        Notification.objects.create(user=other, notification_type="system",
                                    title="theirs")
        _trade(other, status="OPEN")
        live = self.client.get(URL).json()
        self.assertEqual(live["stages"]["tell"]["metrics"][0][0], 0)
        self.assertEqual(live["stages"]["tell"]["metrics"][1][0], 0)
        self.assertEqual(live["clusters"]["people"]["metrics"][0][0], 0)
        opened = dict((w, n) for n, w in live["stages"]["act"]["metrics"])
        self.assertEqual(opened["trades opened today"], 0)


# ── 2. The state of a stage is the state of its rows ─────────────────────

class StageStateTests(TestCase):
    def setUp(self):
        self.user = _user("dl_state")
        self.client.force_login(self.user)
        _master()

    def _live(self):
        return self.client.get(URL).json()

    def test_a_row_that_ran_a_minute_ago_makes_its_stage_live(self):
        _component("morgul_guards", ago=timedelta(minutes=1))
        live = self._live()
        self.assertEqual(live["stages"]["watch"]["state"], "live")
        self.assertEqual(live["stages"]["watch"]["words"], "ran 1 min ago")
        self.assertEqual(live["tasks"]["run-morgul-guards"]["state"], "live")
        self.assertEqual(live["tasks"]["run-morgul-guards"]["component"],
                         "morgul_guards")
        self.assertIsNotNone(live["tasks"]["run-morgul-guards"]["last"])

    def test_a_row_three_days_old_makes_its_stage_stale(self):
        _component("morgul_guards", ago=timedelta(days=3))
        live = self._live()
        self.assertEqual(live["stages"]["watch"]["state"], "stale")
        self.assertEqual(live["stages"]["watch"]["words"], "ran 3 d ago")
        self.assertEqual(live["tasks"]["run-morgul-guards"]["state"], "stale")

    def test_a_switched_off_row_reads_off(self):
        _component("morgul_guards", ago=timedelta(minutes=1), enabled=False)
        live = self._live()
        self.assertEqual(live["tasks"]["run-morgul-guards"]["state"], "off")
        # Every other entry of WATCH is wrapped by the gate and has no row
        # in this database, which the gate reads as off; all off is off.
        self.assertEqual(live["stages"]["watch"]["state"], "off")
        self.assertEqual(live["stages"]["watch"]["words"], "switched off")

    def test_a_failed_run_is_broken_above_everything_else(self):
        _component("morgul_guards", ago=timedelta(minutes=1), status="error",
                   message="boom")
        _component("telegram_alarm", ago=timedelta(minutes=1))
        live = self._live()
        self.assertEqual(live["stages"]["watch"]["state"], "broken")
        self.assertEqual(live["beat"]["state"], "broken")

    def test_the_bots_tick_lights_decide(self):
        _component("pipeline_asset_bots", ago=timedelta(minutes=1))
        live = self._live()
        self.assertEqual(live["stages"]["decide"]["state"], "live")
        self.assertEqual(live["tasks"]["tick-asset-bots"]["state"], "live")

    def test_an_entry_the_gate_does_not_wrap_is_quiet(self):
        live = self._live()
        t = live["tasks"]["refresh-saxo-sessions"]
        self.assertEqual(t["state"], "quiet")
        self.assertIsNone(t["component"])
        self.assertEqual(t["ago"], "never")

    def test_a_stage_with_no_run_says_so(self):
        live = self._live()
        # Nothing seeded: every wrapped entry reads off, none ever ran.
        self.assertEqual(live["stages"]["see"]["words"], "switched off")
        self.assertIn("no component row", live["stages"]["see"]["note"])

    def test_the_master_switch_off_is_the_beats_word(self):
        from core.platform_control import PlatformComponent
        PlatformComponent.objects.filter(key="platform_master").update(is_enabled=False)
        _component("morgul_guards", ago=timedelta(minutes=1))
        live = self._live()
        self.assertEqual(live["beat"]["state"], "off")
        self.assertEqual(live["beat"]["words"], "master switch off")

    def test_the_stage_rule_in_isolation(self):
        from dashboard.views_day import _stage_state
        self.assertEqual(_stage_state(["broken", "live"]), "broken")
        self.assertEqual(_stage_state(["stale", "live"]), "stale")
        self.assertEqual(_stage_state(["silent", "live"]), "stale")
        self.assertEqual(_stage_state(["off", "off", "quiet"]), "off")
        self.assertEqual(_stage_state(["off", "live"]), "live")
        self.assertEqual(_stage_state(["off", "idle"]), "quiet")
        self.assertEqual(_stage_state(["quiet"]), "quiet")
        self.assertEqual(_stage_state([]), "quiet")


# ── 3. The metrics move ──────────────────────────────────────────────────

class MetricsMoveTests(TestCase):
    def setUp(self):
        self.user = _user("dl_metrics")
        self.client.force_login(self.user)
        cache.delete("morgul:summary")

    def _metrics(self, stage):
        live = self.client.get(URL).json()
        return {words: n for n, words in live["stages"][stage]["metrics"]}

    def test_a_signal_today_moves_think(self):
        from instruments.models import Instrument
        from signals.models import Signal
        before = self._metrics("think")
        inst = Instrument.objects.create(symbol="DLX", name="DLX",
                                        asset_class="crypto")
        Signal.objects.create(instrument=inst, direction="bullish",
                              signal_type="technical", urgency="medium",
                              title="t", description="d", rule_name="dl_rule",
                              score=0.7, price_at_signal=1, is_active=True)
        after = self._metrics("think")
        self.assertEqual(before["signals raised today"], 0)
        self.assertEqual(after["signals raised today"], 1)
        self.assertEqual(after["signals active now"], 1)

    def test_a_notification_today_moves_tell_and_people(self):
        from alerts.models import Notification
        Notification.objects.create(user=self.user, notification_type="system",
                                    title="hello")
        live = self.client.get(URL).json()
        tell = {w: n for n, w in live["stages"]["tell"]["metrics"]}
        self.assertEqual(tell["notifications today"], 1)
        self.assertEqual(tell["unread now"], 1)
        self.assertEqual(live["clusters"]["people"]["metrics"][0],
                         [1, "unread notifications"])

    def test_a_trade_opened_today_moves_act(self):
        _trade(self.user, status="OPEN")
        _trade(self.user, status="CLOSE_PENDING")
        act = self._metrics("act")
        self.assertEqual(act["trades opened today"], 2)
        self.assertEqual(act["open now, paper"], 2)
        self.assertEqual(act["closes pending at the venue"], 1)
        live = self.client.get(URL).json()
        self.assertIn("not confirmed", live["stages"]["act"]["note"])

    def test_bot_configs_count_on_decide(self):
        _config(self.user, name="on", enabled=True)
        _config(self.user, name="off", enabled=False)
        decide = self._metrics("decide")
        self.assertEqual(decide["of 2 bot configs enabled"], 1)

    def test_an_empty_morgul_cache_never_raises(self):
        watch = self._metrics("watch")
        self.assertEqual(watch["Morgul guards ran — no run recorded"], 0)
        self.assertEqual(watch["guard findings standing"], 0)

    def test_a_morgul_summary_is_read(self):
        cache.set("morgul:summary", {
            "at": timezone.now().isoformat(), "guards": 10, "failed": [],
            "findings": [{"guard": "no_stop", "name": "Live without a stop",
                          "severity": "critical", "label": "x"}]}, 60)
        watch = self._metrics("watch")
        self.assertEqual(watch["Morgul guards ran"], 10)
        self.assertEqual(watch["guard findings standing"], 1)

    def test_a_group_that_fails_logs_and_the_door_still_answers(self):
        with patch("dashboard.views_day._see_metrics",
                   side_effect=RuntimeError("news table gone")):
            with self.assertLogs("dashboard.views_day", level="WARNING") as log:
                r = self.client.get(URL)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(any("news table gone" in line for line in log.output))
        see = r.json()["stages"]["see"]["metrics"]
        self.assertEqual(see[0], [0, "news items scraped today"])

    def test_no_accept_rate_is_ever_derived(self):
        """Allows are sampled (bot_program.orchestrator._log_decision);
        the gate's cell says rejects and says the allows are sampled."""
        decide = self._metrics("decide")
        self.assertIn("entries the gate refused today (allows are sampled)",
                      decide)
        self.assertFalse(any("%" in w or "rate" in w for w in decide))


# ── 4. One query for the rows, a ceiling on the door ─────────────────────

class QueryCeilingTests(TestCase):
    def setUp(self):
        self.user = _user("dl_queries")
        for i, key in enumerate(("morgul_guards", "pipeline_asset_bots",
                                 "telegram_eye", "telegram_alarm",
                                 "scraper_news", "pipeline_signals")):
            _component(key, ago=timedelta(minutes=i + 1))

    def test_the_builder_reads_the_rows_once(self):
        from dashboard.views_day import day_live_payload
        # 20 today: the component rows (1), SEE (3), THINK (4), DECIDE (2),
        # ACT (1), the broker book (3, cached on the user for VENUES),
        # TELL (1), LEARN (1), the quote feeds (1, plus the three IBKRAccount
        # row checks market_data.feeds makes for the broker-stream feeds).
        # One query per beat entry would be seventy-eight more.
        with self.assertNumQueries(20):
            day_live_payload(self.user)

    def test_the_door_stays_under_the_ceiling(self):
        self.client.force_login(self.user)
        self.client.get(URL)  # presence and the session's first sighting
        with CaptureQueriesContext(connection) as ctx:
            r = self.client.get(URL)
        self.assertEqual(r.status_code, 200)
        self.assertLessEqual(len(ctx.captured_queries), 35,
                             "\n".join(q["sql"][:120] for q in ctx.captured_queries))


# ── 5. The clock ─────────────────────────────────────────────────────────

class TheClockTests(TestCase):
    def setUp(self):
        self.user = _user("dl_clock")
        self.client.force_login(self.user)
        _master()

    def test_the_marks_are_the_daily_crontab_entries(self):
        live = self.client.get(URL).json()
        scheme = day.day_scheme()
        daily = {t["key"]: t for st in scheme["stages"] for t in st["tasks"]
                 if t["kind"] == "cron" and t["seconds"] == 86400.0}
        self.assertGreater(len(daily), 10)
        marks = live["clock"]["marks"]
        self.assertEqual({m["key"] for m in marks}, set(daily))
        for m in marks:
            self.assertEqual(m["m"], daily[m["key"]]["first"])
            self.assertEqual(m["label"], daily[m["key"]]["label"])
            self.assertIn(m["state"], STATES)
        self.assertEqual([m["m"] for m in marks], sorted(m["m"] for m in marks))
        # 03:00 nightly consolidation: minute 180 of the UTC day.
        self.assertEqual(next(m["m"] for m in marks
                              if m["key"] == "sauron-consolidation-nightly"), 180)
        # Weekly and monthly entries are not daily marks.
        self.assertNotIn("fetch-cot-reports", {m["key"] for m in marks})
        self.assertNotIn("sauron-horizon-monthly", {m["key"] for m in marks})

    def test_the_cursor_and_the_bands(self):
        live = self.client.get(URL).json()
        now = timezone.now()
        self.assertAlmostEqual(live["clock"]["minute"],
                               now.hour * 60 + now.minute, delta=1)
        # New York 13:30–20:00 UTC, off core.constants.MARKET_SESSIONS —
        # the strip typed 13:30–21:00 (review, 2026-09-29).
        self.assertEqual(live["clock"]["us_session"], [810, 1200])
        self.assertEqual(live["clock"]["night"], [120, 420])

    def test_a_mark_tints_with_its_row(self):
        _component("pipeline_snapshot", ago=timedelta(minutes=5))
        live = self.client.get(URL).json()
        mark = next(m for m in live["clock"]["marks"]
                    if m["key"] == "daily-portfolio-snapshot")
        self.assertEqual(mark["state"], "live")


# ── 6. The page ──────────────────────────────────────────────────────────

class ThePageTests(TestCase):
    def setUp(self):
        self.user = _user("dl_page")
        self.client.force_login(self.user)
        self.body = self.client.get("/command/").content.decode("utf-8", "ignore")

    def test_the_section_and_its_parts(self):
        body = self.body
        self.assertIn("A DAY OF SAURON · LIVE", body)
        self.assertIn('id="dayScheme"', body)
        self.assertIn('id="dayPanel"', body)
        self.assertIn('viewBox="0 0 1200 700"', body)
        self.assertIn('data-panel="dayPanel"', body)
        self.assertIn('<script id="dayData" type="application/json">', body)
        self.assertIn('data-day-live-url="/api/day/live/"', body)
        self.assertIn("js/sv-day-scheme.js", body)
        self.assertIn("js/sv-day-live.js", body)
        self.assertIn("css/sv-day-scheme.css", body)
        self.assertIn("sv-day-collapsed", body)
        self.assertIn('aria-expanded="true"', body)
        self.assertIn(f"{len(app.conf.beat_schedule)} scheduled tasks", body)
        self.assertEqual(body.count('data-day-tile="'), 7)
        self.assertIn('id="dayClock"', body)
        self.assertIn("US SESSION", body)
        self.assertIn("NIGHT OF LEARNING", body)

    def test_it_sits_between_the_hero_and_the_tabs(self):
        body = self.body
        hero = body.index('class="oc-hero"')
        section = body.index('<section class="day-home"')
        tabs = body.index('id="ocTabs"')
        self.assertLess(hero, section)
        self.assertLess(section, tabs)

    def test_the_json_is_the_schedule_read_whole_and_inside_the_section(self):
        body = self.body
        live = _json_on(body)
        self.assertEqual(live["total"], len(app.conf.beat_schedule))
        self.assertEqual([s["key"] for s in live["stages"]], STAGE_KEYS)
        start = body.index('<section class="day-home"')
        end = body.index("</section>", start)
        self.assertIn('<script id="dayData"', body[start:end])

    def test_the_scripts_load_once_and_in_order(self):
        body = self.body
        self.assertEqual(body.count("js/sv-day-scheme.js"), 1)
        self.assertEqual(body.count("js/sv-day-live.js"), 1)
        self.assertLess(body.index("js/sv-day-scheme.js"),
                        body.index("js/sv-day-live.js"))
        self.assertGreaterEqual(body.count("css/sv-day-scheme.css"), 1)

    def test_every_string_the_operations_center_tests_assert_survives(self):
        body = self.body
        for s in ("oc-hero", "PORTFOLIO VALUE", "ocClock", "ocWsStatus",
                  "OPERATIONS CENTER", 'data-tab="live"',
                  'data-tab="portfolio"', 'data-tab="history"',
                  'data-tab="bots"', 'hx-target="#ocTabBody"', "hx-push-url",
                  "oc-tab-metric-primary", "oc-tab-metric-secondary",
                  'data-oc-metric="live"', "/command/tab/metrics/",
                  'data-oc-hero="value"', "sv:eye-event", "fill_open",
                  "fill_close", "close_pending", "FALLBACK_MS",
                  "prefers-reduced-motion", "Operations Center",
                  'href="/command/"'):
            self.assertIn(s, body, s)

    def test_the_page_opens_no_socket_of_its_own(self):
        eye = self.client.get("/eye/").content.decode("utf-8", "ignore")
        self.assertEqual(self.body.count("new WebSocket"),
                         eye.count("new WebSocket"))

    def test_the_page_renders_when_the_schedule_cannot_be_read(self):
        with patch("core.day_of_sauron.day_scheme",
                   side_effect=RuntimeError("beat unreadable")):
            with self.assertLogs("dashboard.views_command", level="WARNING"):
                r = self.client.get("/command/")
        self.assertEqual(r.status_code, 200)
        self.assertIn('id="dayScheme"', r.content.decode())


# ── 7. The static files ──────────────────────────────────────────────────

class TheStaticFilesTests(SimpleTestCase):
    def test_the_live_script_parses_carries_no_tag_and_opens_no_socket(self):
        from tests.test_inline_js_parses import NODE, _parse_all
        js = JS.read_text(encoding="utf-8")
        for word in ("{{", "{%", "new WebSocket"):
            self.assertNotIn(word, js, word)
        for word in ("sv:day-mounted", "sv:eye-event", "setLive",
                     "visibilitychange", "prefers-reduced-motion",
                     "localStorage", "data-day-live-url", "fill_open",
                     "fill_close", "close_pending", "new_signal",
                     "run_complete", "document.hidden", "sv-day-collapsed"):
            self.assertIn(word, js, word)
        if NODE is None:
            self.skipTest("node is not installed on this machine")
        self.assertEqual(_parse_all([{"label": JS.name, "source": js}]), [])

    def test_the_ring_is_still_built_in_the_static_file(self):
        self.assertNotIn("createElementNS", PAGE.read_text(encoding="utf-8"))
        self.assertIn("createElementNS", RING_JS.read_text(encoding="utf-8"))

    def test_the_ring_takes_every_state_off_before_the_new_one_goes_on(self):
        """Review, 2026-09-29: setLive stripped four of the five states, so
        a stage that once read broken kept its red after it recovered."""
        js = RING_JS.read_text(encoding="utf-8")
        self.assertIn("var STATES = ['live', 'stale', 'off', 'quiet', 'broken'];", js)
        for s in STATES:
            self.assertIn(f"'{s}'", js, s)
        self.assertIn("STATES.length; s++) nd.g.classList.remove('day-' + STATES[s]);", js)

    def test_a_poll_that_changed_nothing_under_the_pointer_rewrites_nothing(self):
        """Review, 2026-09-29: every poll replayed the panel's entrance and,
        the panel being aria-live, re-read it whole to a screen reader
        once a minute. The ring re-renders only a changed slice, silently;
        the home page's panel is aria-live=\"off\" while the Wall's, which
        changes only on the reader's own hover, stays polite."""
        js = RING_JS.read_text(encoding="utf-8")
        self.assertIn("function sliceFor(key)", js)
        self.assertIn("sliceFor(current) !== lastSlice) render(current, true)", js)
        self.assertIn("if (!silent) panel.classList.add('day-pre');", js)
        page = PAGE.read_text(encoding="utf-8")
        self.assertIn('id="dayPanel" aria-live="off"', page)
        wall = (Path(settings.BASE_DIR) / "templates" / "landing"
                / "the_wall.html").read_text(encoding="utf-8")
        self.assertIn('id="dayPanel" aria-live="polite"', wall)

    def test_an_ended_session_stops_the_poll(self):
        """Review, 2026-09-29: login_required answers the Wall's HTML with
        a 200 after a redirect, so r.ok was true, r.json() threw, and the
        tab fetched the Wall once a minute for ever."""
        js = JS.read_text(encoding="utf-8")
        self.assertIn("r.redirected", js)
        self.assertIn("/json/i.test(type)", js)
        self.assertIn("!r.ok || r.redirected || !/json/i.test(type)", js)

    def test_the_see_tile_reads_no_bar_table(self):
        """Review, 2026-09-29: MAX(timestamp) over every stored bar was a
        full scan per poll (PriceData has no lone timestamp index); the
        newest quote comes off LiveQuote, one row per instrument."""
        src = (Path(settings.BASE_DIR) / "dashboard" / "views_day.py").read_text(encoding="utf-8")
        self.assertNotIn("PriceData.objects", src)
        self.assertNotIn("import LiveQuote, PriceData", src)
        self.assertIn('LiveQuote.objects.aggregate(m=Max("updated_at"))', src)

    def test_the_template_keeps_its_comments_single_line(self):
        src = PAGE.read_text(encoding="utf-8")
        for m in re.finditer(r"\{#(.*?)#\}", src, re.S):
            self.assertNotIn("\n", m.group(1), m.group(1)[:60])

    def test_the_sheet_grows_no_token_no_keyframe_and_stills_the_home(self):
        css = re.sub(r"/\*.*?\*/", "", SHEET.read_text(encoding="utf-8"), flags=re.S)
        self.assertNotIn(":root", css)
        self.assertNotIn("@keyframes", css)
        self.assertNotIn("animation", css)
        for cls in (".day-home", ".day-tile", ".day-clock", ".day-clock-cursor",
                    ".day-clock-mark", ".day-tiles"):
            self.assertIn(cls, css, cls)
        reduced = css.split("@media (prefers-reduced-motion: reduce)")[-1]
        for cls in (".day-tile", ".day-clock-cursor", ".day-tile-num b",
                    ".day-clock-mark"):
            self.assertIn(cls, reduced, cls)
        self.assertIn("transition: none", reduced)
        self.assertIn("home", SHEET.read_text(encoding="utf-8"))


# ── 8. The second review (2026-09-29): each finding, pinned ─────────────

class OneRowOneJudgementTests(TestCase):
    """Several beat entries write one component row. The row is judged
    once, against its most frequent writer that always writes, and handed
    to that writer alone; the others are shared."""

    def setUp(self):
        self.user = _user("dl_shared")
        self.client.force_login(self.user)
        _master()

    def _live(self):
        return self.client.get(URL).json()

    def test_a_daily_task_never_borrows_the_ticks_green(self):
        _component("pipeline_asset_bots", ago=timedelta(minutes=2))
        live = self._live()
        self.assertEqual(live["tasks"]["tick-asset-bots"]["state"], "live")
        decay = live["tasks"]["track-record-decay-check"]
        self.assertEqual(decay["state"], "quiet")
        self.assertEqual(decay["shared_with"], "tick-asset-bots")
        self.assertEqual(decay["ago"], "shared record")
        self.assertIsNone(decay["last"])
        mark = next(m for m in live["clock"]["marks"]
                    if m["key"] == "track-record-decay-check")
        self.assertEqual(mark["state"], "quiet")
        self.assertTrue(mark["shared"])

    def test_one_failed_row_is_one_broken_entry_not_five(self):
        _component("pipeline_asset_bots", ago=timedelta(minutes=2), status="error")
        live = self._live()
        self.assertEqual(live["counts"]["broken"], 1)
        broken = [k for k, t in live["tasks"].items() if t["state"] == "broken"]
        self.assertEqual(broken, ["tick-asset-bots"])

    def test_the_alarm_row_is_judged_by_the_sentinel_not_the_idle_poll(self):
        """The poll goes idle with nothing to read and writes nothing; the
        row moves every 10 min with the sentinel. Judged against 15 s it
        read stale 93% of the time."""
        _component("telegram_alarm", ago=timedelta(minutes=4))
        live = self._live()
        self.assertEqual(live["tasks"]["alarm-sentinel"]["state"], "live")
        self.assertEqual(live["tasks"]["poll-telegram-alarm"]["state"], "quiet")
        self.assertEqual(live["tasks"]["poll-telegram-alarm"]["shared_with"],
                         "alarm-sentinel")
        self.assertNotEqual(live["stages"]["tell"]["state"], "stale")

    def test_a_fifteen_second_poller_ten_hours_silent_is_stale(self):
        """The component states came from the system map's WIRING, which
        knows neither Telegram voice nor Morgul: 48 h for a 15 s poller."""
        _component("telegram_eye", ago=timedelta(hours=10))
        live = self._live()
        self.assertEqual(live["tasks"]["poll-telegram-eye"]["state"], "stale")
        self.assertIn("the Eye stale", live["clusters"]["people"]["words"])
        watch = {w: n for n, w in live["stages"]["watch"]["metrics"]}
        self.assertGreaterEqual(watch["components stale"], 1)

    def test_a_daily_task_that_missed_a_run_is_stale_as_the_digest_says(self):
        """31 h after a daily run is a missed run: the digest calls it
        stopped at 26 h; 2.5 periods said green until 60."""
        _component("pipeline_snapshot", ago=timedelta(hours=31))
        live = self._live()
        self.assertEqual(live["tasks"]["daily-portfolio-snapshot"]["state"], "stale")
        _component("pipeline_calibration", ago=timedelta(hours=20))
        live = self._live()
        self.assertEqual(live["tasks"]["resolve-pending-calibrations"]["state"], "live")

    def test_the_thresholds_in_isolation(self):
        from dashboard.views_day import STALE_FLOOR_S, _stale_after_s
        self.assertEqual(_stale_after_s(15.0), STALE_FLOOR_S)
        self.assertEqual(_stale_after_s(300.0), 750.0)
        self.assertEqual(_stale_after_s(86400.0), 26 * 3600.0)
        self.assertAlmostEqual(_stale_after_s(7 * 86400.0),
                               1.2 * 7 * 86400.0 + 2 * 3600.0)
        self.assertIsNone(_stale_after_s(None))


class TheMasterSwitchTests(TestCase):
    def setUp(self):
        self.user = _user("dl_master")
        self.client.force_login(self.user)

    def test_a_pause_reads_off_not_amber(self):
        """The gate skips every master-gated task without touching its row,
        so the rows only age: six stages read stale for a deliberate
        pause."""
        _master(enabled=False)
        for key in ("scraper_news", "pipeline_signals", "pipeline_asset_bots",
                    "morgul_guards", "telegram_eye"):
            _component(key, ago=timedelta(hours=2))
        live = self.client.get(URL).json()
        for stage in ("see", "think", "decide", "act", "watch"):
            self.assertEqual(live["stages"][stage]["state"], "off", stage)
        self.assertEqual(live["counts"]["stale"], 0)
        self.assertIn("master switch is off", live["stages"]["see"]["note"])
        self.assertEqual(live["beat"]["words"], "master switch off")

    def test_the_alarm_keeps_its_own_state_through_a_pause(self):
        _master(enabled=False)
        _component("telegram_alarm", ago=timedelta(minutes=3))
        live = self.client.get(URL).json()
        self.assertEqual(live["tasks"]["alarm-sentinel"]["state"], "live")

    def test_a_missing_master_row_is_a_pause_too(self):
        _component("morgul_guards", ago=timedelta(minutes=1))
        live = self.client.get(URL).json()
        self.assertEqual(live["tasks"]["run-morgul-guards"]["state"], "off")
        self.assertEqual(live["beat"]["state"], "off")
        self.assertIn("no row", live["beat"]["words"])


class OneVocabularyEvenWithRowsTests(TestCase):
    def test_silent_and_never_run_speak_the_pages_five_words(self):
        """The vocabulary test passed only because it seeded no row: a
        warning row sent 'silent', a never-run row 'idle', and the strip
        painted both as 'not gated'."""
        user = _user("dl_vocab")
        self.client.force_login(user)
        _master()
        _component("pipeline_snapshot", ago=timedelta(hours=1), status="warning")
        _component("scraper_sec", ago=None)
        live = self.client.get(URL).json()
        self.assertEqual(live["tasks"]["daily-portfolio-snapshot"]["state"], "stale")
        self.assertEqual(live["tasks"]["fetch-sec-filings"]["state"], "quiet")
        for t in live["tasks"].values():
            self.assertIn(t["state"], STATES)
        for m in live["clock"]["marks"]:
            self.assertIn(m["state"], STATES)
        self.assertEqual(set(live["counts"]) - {"total"}, STATES)


class StaffOnlyTests(TestCase):
    """/health/, the system map and oculus keep component states, the master
    switch and Morgul's findings from a non-staff login; the live door did
    not (review, 2026-09-29)."""

    def test_a_non_staff_login_is_refused_the_door(self):
        self.client.force_login(_user("dl_viewer", staff=False))
        r = self.client.get(URL)
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.json(), {"staff_only": True})

    def test_a_non_staff_home_page_draws_the_schedule_and_polls_nothing(self):
        self.client.force_login(_user("dl_viewer2", staff=False))
        body = self.client.get("/command/").content.decode()
        self.assertIn('id="dayScheme"', body)
        self.assertIn('<script id="dayData" type="application/json">', body)
        self.assertNotIn("data-day-live-url", body)
        self.assertNotIn('data-day-tile="', body)
        self.assertNotIn('id="dayClock"', body)
        self.assertIn('id="dayHomeTitle">A DAY OF SAURON</span>', body)
        self.assertIn("the schedule the platform ships with", body)

    def test_the_staff_page_carries_the_live_parts(self):
        self.client.force_login(_user("dl_staff"))
        body = self.client.get("/command/").content.decode()
        self.assertIn('data-day-live-url="/api/day/live/"', body)
        self.assertEqual(body.count('data-day-tile="'), 7)
        # The US band off the session table, never typed.
        self.assertIn('style="left:56.25%;width:27.083%"', body)
        self.assertIn("The US session, 13:30–20:00 UTC", body)
        # The tiles carry no aria-label: it replaced the state and numbers.
        tiles = re.findall(r'<button type="button" class="day-tile[^>]*>', body)
        self.assertEqual(len(tiles), 7)
        for t in tiles:
            self.assertNotIn("aria-label", t)


class TheScriptsAfterTheReviewTests(SimpleTestCase):
    def test_the_live_layer_resumes_after_an_unlock_and_rests_when_shut(self):
        js = JS.read_text(encoding="utf-8")
        self.assertIn("'sv:pin-unlocked'", js)
        unlock = js[js.index("'sv:pin-unlocked'"):]
        self.assertIn("stopped = false;", unlock[:200])
        self.assertIn("if (section.classList.contains('day-collapsed')) return;", js)
        self.assertIn("if (started || !LIVE_URL) return;", js)

    def test_the_ring_formats_decimals_and_names_its_buttons(self):
        js = RING_JS.read_text(encoding="utf-8")
        self.assertIn("var parts = String(n).split('.');", js)
        self.assertEqual(js.count("role: 'button'"), 3)
        self.assertEqual(js.count("'aria-label':"), 3)
        self.assertNotIn("container healthcheck", js)
        self.assertNotIn("on their own containers", js)
        self.assertIn("st.pace ||", js)
        if NODE_OK:
            import subprocess
            out = subprocess.run(
                ["node", "-e",
                 "function fmt(n){var parts=String(n).split('.');parts[0]=parts[0]"
                 ".replace(/\\B(?=(\\d{3})+(?!\\d))/g, ',');return parts.join('.');}"
                 "console.log(fmt(12.3457)+'|'+fmt(1234567)+'|'+fmt(1234.5678))"],
                capture_output=True, text=True, timeout=20)
            self.assertEqual(out.stdout.strip(), "12.3457|1,234,567|1,234.5678")

    def test_the_grid_asks_its_container_not_the_viewport(self):
        css = SHEET.read_text(encoding="utf-8")
        self.assertIn(".day-frame { container-type: inline-size; }", css)
        self.assertIn("@container (max-width: 1101px)", css)
        self.assertIn(".day-beat:focus-visible", css)
        page = PAGE.read_text(encoding="utf-8")
        self.assertIn('<div class="day-frame">', page)
        self.assertIn('role="group"', page.split('id="dayScheme"')[1][:200])


try:
    import shutil as _shutil
    NODE_OK = bool(_shutil.which("node"))
except Exception:  # noqa: BLE001
    NODE_OK = False
