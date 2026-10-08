"""A day of Sauron, on the Wall.

The ring scheme (seven stages around the beat, markets in, venues and
people out) is drawn from the beat schedule the page was served with, by
static/js/sv-day-scheme.js off a json_script the view hands it. These
tests pin that the section is on the page, that the JSON on it is the
schedule read whole, that the drawing lives in a static file (the chart
tests forbid SVG built inside a template), that the section and its script
keep the stripe parity of the sections after them, and that the two
cadences the brokers pillar used to type wrongly are gone.

Run with:  python manage.py test tests.test_wall_day
"""
import json
import re
from pathlib import Path

from django.conf import settings
from django.test import TestCase

from config.celery import app

WALL = Path(settings.BASE_DIR) / "templates" / "landing" / "the_wall.html"
SCRIPT = Path(settings.BASE_DIR) / "static" / "js" / "sv-day-scheme.js"
SHEET = Path(settings.BASE_DIR) / "static" / "css" / "sv-day-scheme.css"


def _json_on(body):
    m = re.search(r'<script id="dayData" type="application/json">(.*?)</script>', body, re.S)
    assert m, "the day's json_script is not on the page"
    return json.loads(m.group(1))


class TheDayIsOnTheWallTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.src = WALL.read_text(encoding="utf-8")

    def setUp(self):
        self.body = self.client.get("/wall/").content.decode()

    def test_the_section_and_its_parts(self):
        body = self.body
        self.assertIn('<section class="wall-section" id="day">', body)
        self.assertIn("A Day of Sauron", body)
        self.assertIn("What the Machine Does,", body)
        self.assertIn('id="dayScheme"', body)
        self.assertIn('id="dayPanel"', body)
        self.assertIn('viewBox="0 0 1200 700"', body)
        self.assertIn('data-panel="dayPanel"', body)
        self.assertIn("js/sv-day-scheme.js", body)
        self.assertIn("css/sv-day-scheme.css", body)
        # The reader is told the number the picture is drawn from.
        self.assertIn(f"{len(app.conf.beat_schedule)} scheduled tasks", body)

    def test_it_claims_the_shipped_schedule_not_the_running_one(self):
        """Review, 2026-09-29: the beat runs the database scheduler, whose
        rows an admin can edit or disable (and which adds celery's own
        result cleanup), and every price stream is opt-in. The page reads
        the code's schedule and says so."""
        body = self.body
        self.assertIn("the schedule the platform ships with", body)
        self.assertIn("price streams where they are enabled", body)
        self.assertNotIn("as it runs on this deployment", body)
        self.assertNotIn("streams that never stop", body)

    def test_the_nav_reaches_it_and_stands_it_down_with_the_others(self):
        nav = re.search(r'<nav class="wall-nav" id="wallNav">(.*?)</nav>', self.body, re.S).group(1)
        self.assertIn('<a href="#day">Day</a>', nav)
        self.assertLess(nav.index('href="#pipeline"'), nav.index('href="#day"'))
        self.assertLess(nav.index('href="#day"'), nav.index('href="#demo"'))
        narrow = (self.src.split("@media (min-width: 769px) and (max-width: 1080px) {")[1]
                  .split("display: none;")[0])
        self.assertIn('.nav-links a[href="#day"]', narrow)

    def test_the_json_is_the_schedule_read_whole(self):
        day = _json_on(self.body)
        self.assertEqual(day["total"], len(app.conf.beat_schedule))
        self.assertEqual([s["title"] for s in day["stages"]],
                         ["SEE", "THINK", "DECIDE", "ACT", "WATCH", "TELL", "LEARN"])
        self.assertEqual(day["unplaced"], 0)
        self.assertEqual(sum(s["count"] for s in day["stages"]), day["total"])
        # Only what the drawing reads (review, 2026-09-29): no import
        # path, beat key or queue per task for an anonymous visitor.
        blob = json.dumps(day)
        for internal in ("bot_program.tasks", "market_data.tasks", '"task"',
                         '"tasks"', "run-morgul-guards"):
            self.assertNotIn(internal, blob, internal)
        tell = next(s for s in day["stages"] if s["key"] == "tell")
        self.assertEqual(tell["rows"][0]["when"], "15 s")
        self.assertIn("the Eye reads its Telegram group", tell["rows"][0]["what"])
        # The facts are the Wall's own counts, ints, never a typed figure.
        for stage in day["stages"]:
            for n, words in stage["facts"]:
                self.assertIsInstance(n, int)
                self.assertTrue(words)

    def test_the_section_is_one_child_so_the_stripes_keep_alternating(self):
        """`.wall-section:nth-child(even)` tints every second child of
        #wallContent. A sibling <script> kept the parity of the sections
        after it but left #day and #demo two untinted neighbours, the one
        break in the pattern (review, 2026-09-29). Everything lives inside
        the section, like #demo's own script: one child, every later
        stripe flips, the alternation holds everywhere."""
        src = self.src
        start = src.index('<section class="wall-section" id="day">')
        end = src.index('<section class="wall-section" id="demo">')
        between = src[start:end]
        self.assertEqual(between.count("<section"), 1)
        self.assertEqual(between.count("</section>"), 1)
        inside = between[:between.index("</section>")]
        after = between[between.index("</section>"):]
        self.assertEqual(re.findall(r"<script[^>]*>", after), [])
        self.assertIn("sv-day-scheme.js", inside)
        self.assertIn('json_script:"dayData"', inside)

    def test_the_drawing_is_a_static_file_and_parses(self):
        """tests/test_chart_surfaces.py forbids createElementNS inside a
        template; the ring is built in static/js/sv-day-scheme.js."""
        src = self.src
        self.assertNotIn("createElementNS", src)
        js = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("createElementNS", js)
        self.assertIn("window.SVDay", js)
        self.assertIn("pauseAnimations", js)
        self.assertIn("prefers-reduced-motion", js)
        self.assertIn("'dayData'", js)
        for word in ("{{", "{%"):
            self.assertNotIn(word, js)

    def test_the_sheet_adds_no_token_and_no_keyframe(self):
        """The Book copies the Wall's :root and pins every token; the Wall
        keeps its keyframe list short. The ring's sheet reads the tokens
        both pages define and animates through SMIL instead."""
        css = re.sub(r"/\*.*?\*/", "", SHEET.read_text(encoding="utf-8"), flags=re.S)
        self.assertNotIn(":root", css)
        self.assertNotIn("@keyframes", css)
        self.assertIn("prefers-reduced-motion", css)
        for token in ("--bg2", "--bg3", "--border", "--text2", "--text3",
                      "--accent", "--accent-dim", "--accent-bright"):
            self.assertIn(f"var({token}", css, token)
        wall_root = self.src.split(":root {")[1].split("}")[0]
        self.assertNotIn("--day", wall_root)

    def test_the_brokers_pillar_reads_the_beat_s_own_clock(self):
        """It typed a 06:30 snapshot and a 03:30 pg_dump; the snapshot runs
        at 23:30 and no backup is on the beat (deploy/backup.sh has its own
        clock)."""
        body = self.body
        self.assertNotIn("pg_dump</code> at 03:30", body)
        self.assertNotIn("30-day retention", body)
        self.assertNotIn('<div class="pillar-num">06:30</div>', body)
        self.assertIn('<div class="pillar-num">23:30</div>', body)
        self.assertIn("snapshot at 23:30 UTC, decay scan at 06:15 UTC", body)

    def test_it_says_nothing_the_wall_forbids(self):
        low = _json_on(self.body)
        blob = json.dumps(low).lower()
        for word in ("proven", "fully autonomous", "hands-free", "no human needed",
                     "trades your account", "allocates your capital", "667"):
            self.assertNotIn(word, blob, word)

    def test_the_people_cluster_names_no_command(self):
        """The PEOPLE panel named the two Telegram commands and the health
        page's path to every visitor (2026-10-08): the requests are said
        in words now, and the brake says what it keeps. The ring's own
        label said the same command in capitals, so the file is read
        lowercased and the words are looked for unquoted."""
        js = SCRIPT.read_text(encoding="utf-8").lower()
        for word in ("/status", "/stopall", "/health/"):
            self.assertFalse(word in js, "the ring script names %s" % word)

    def test_the_narrow_tier_stands_the_new_anchor_down(self):
        """Safeguards joined the nav after Fleet (2026-10-08). Measured in
        a browser, the bar with it ran past the Access button at 1100,
        1200, 1440 and 1500 px, so the link stands down on the whole
        769–1420 tier (not only Day's 1080 one) and the wide tier closes
        its gap up to 1600 px."""
        nav = re.search(r'<nav class="wall-nav" id="wallNav">(.*?)</nav>', self.body, re.S).group(1)
        self.assertIn('<a href="#safeguards">Safeguards</a>', nav)
        self.assertLess(nav.index('href="#fleet"'), nav.index('href="#safeguards"'))
        self.assertLess(nav.index('href="#safeguards"'), nav.index('href="#desk"'))
        tier = (self.src.split("@media (min-width: 769px) and (max-width: 1420px) {")[1]
                .split("@media")[0])
        self.assertRegex(tier, r'\.nav-links a\[href="#safeguards"\] \{ display: none; \}')
        wide = (self.src.split("@media (min-width: 1421px) and (max-width: 1600px) {")[1]
                .split("@media")[0])
        self.assertIn(".nav-links { gap: 20px; }", wide)
        # and the phone tier's rule, which names its two exceptions, hides it too
        self.assertIn(".nav-links a:not(.btn-access):not(.nav-book) { display: none; }", self.src)

    def test_a_signed_in_reader_is_still_sent_home(self):
        from django.contrib.auth import get_user_model
        user = get_user_model().objects.create_user("zz_day_reader", password="x")
        self.client.force_login(user)
        self.assertEqual(self.client.get("/wall/").status_code, 302)
