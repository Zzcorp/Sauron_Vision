"""One overlay system, and scrapers that report what they stored.

Three audits over this codebase produced one recurring shape of bug: a surface
that renders a confident number nobody computed, and a task that reports
success for work it did not do. This module pins the fixes.

The overlay half
----------------
Six independent overlay implementations had grown up, with two modal systems
at z-index 1000 and 9999, a hover card at 2147483000, and event banners at 900
underneath all of them. Worse, three ancestors created stacking contexts that
clamped their descendants, so several of those numbers never meant anything at
all.

The ingest half
---------------
Six scraper components reported last_status='success' with zero rows between
them. The one that mattered: market_data.EconomicEvent was empty, so the
earnings blackout in stock_bot had never once fired.

Run with:  python manage.py test tests.test_overlays_and_ingest
"""
from datetime import date, datetime, timedelta, timezone as dt_timezone
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.test import RequestFactory, TestCase
from django.utils import timezone


def _read(*parts):
    return (Path(settings.BASE_DIR).joinpath(*parts)
            .read_text(encoding="utf-8", errors="replace"))


# ─────────────────────────── the overlay system ───────────────────────────

class OverlayAssetsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="ov_u", password="x")
        self.client.force_login(self.user)

    def test_the_controller_and_ladder_ship_to_the_browser(self):
        body = self.client.get("/signals/", HTTP_HOST="127.0.0.1").content.decode(
            "utf-8", "replace")
        self.assertIn("css/sv-overlay.css", body)
        self.assertIn("js/sv-overlay.js", body)
        self.assertIn("js/sv-flash.js", body)

    def test_the_assets_are_collected_so_they_do_not_404_in_production(self):
        """WhiteNoise serves from STATIC_ROOT. staticfiles/js did not exist at
        all, so a {% static %} tag for it resolved without raising and then
        404'd — the whole system would have been silently absent in prod."""
        root = Path(settings.STATIC_ROOT)
        for rel in ("js/sv-overlay.js", "js/sv-flash.js", "css/sv-overlay.css"):
            self.assertTrue((root / rel).exists(), f"{rel} was never collected")


class ZIndexLadderTests(TestCase):
    def setUp(self):
        self.css = _read("static", "css", "sv-overlay.css")
        self.base = _read("static", "css", "sauron.css")

    def test_the_ladder_is_declared_once_as_tokens(self):
        for token in ("--z-hovercard", "--z-menu", "--z-panel", "--z-banner",
                      "--z-backdrop", "--z-dialog", "--z-toast", "--z-sidebar"):
            self.assertIn(token, self.css)

    def test_the_maximum_integer_hack_is_retired(self):
        """.sr-popup declared z-index 2147483000 and still painted below the
        topbar, because it was competing inside .signals-rail's own stacking
        context. The number was never the problem."""
        self.assertIn(".sr-popup", self.css)
        self.assertIn("var(--z-hovercard)", self.css)

    def test_the_app_shell_no_longer_traps_every_dialog(self):
        """`.app-layout { z-index: 1 }` established a stacking context over the
        whole application, so a modal rendered into the content block painted
        at 1 against the root and could never rise above the floating eye."""
        self.assertNotIn("min-height: 100vh; position: relative; z-index: 1;",
                         self.base)

    def test_the_banners_outrank_the_hover_cards(self):
        """A banner reporting a fill was at 900, below tooltips at 1000 — so a
        position opening could be covered by a hover card about something
        else."""
        import re
        vals = {}
        for name in ("hovercard", "menu", "banner", "backdrop", "dialog"):
            m = re.search(rf"--z-{name}:\s*(\d+)", self.css)
            self.assertIsNotNone(m, f"--z-{name} is not defined")
            vals[name] = int(m.group(1))
        self.assertLess(vals["hovercard"], vals["menu"])
        self.assertLess(vals["menu"], vals["banner"])
        self.assertLess(vals["banner"], vals["backdrop"])
        self.assertLess(vals["backdrop"], vals["dialog"])

    def test_the_clamping_ancestors_are_laddered(self):
        """backdrop-filter creates a stacking context on its own, so .topbar
        clamps every dropdown it contains no matter what they declare."""
        for sel in (".topbar", ".signals-rail", ".sidebar-overlay"):
            self.assertIn(sel, self.css)


class TemplateCommentTests(TestCase):
    """Django's {# #} is a SINGLE-LINE comment. Spanning it over two lines
    does not make a comment at all — the text renders verbatim into the page.
    This has now bitten this codebase twice, once inside an SVG where it also
    broke the markup, so it gets a guard."""

    def test_no_template_uses_a_multiline_hash_comment(self):
        import re
        from django.conf import settings
        offenders = []
        for path in Path(settings.BASE_DIR).joinpath("templates").rglob("*.html"):
            text = path.read_text(encoding="utf-8", errors="replace")
            for m in re.finditer(r"\{#(.*?)#\}", text, re.S):
                if "\n" in m.group(1):
                    offenders.append(f"{path.name}: {m.group(1).strip()[:50]}")
        self.assertEqual(offenders, [],
                         "use {% comment %}…{% endcomment %} for multi-line")

    def test_no_comment_markup_reaches_the_browser(self):
        user = User.objects.create_user(username="cm_u", password="x")
        self.client.force_login(user)
        body = self.client.get("/signals/", HTTP_HOST="127.0.0.1").content.decode(
            "utf-8", "replace")
        self.assertNotIn("{#", body)
        self.assertNotIn("{% comment", body)


class BackgroundArtTests(TestCase):
    """The eye and the board it sits on."""

    def setUp(self):
        self.user = User.objects.create_user(username="bg_u", password="x")
        self.client.force_login(self.user)
        self.body = self.client.get(
            "/signals/", HTTP_HOST="127.0.0.1").content.decode("utf-8", "replace")

    def _svg(self, cls):
        import re
        m = re.search(rf'<svg class="{cls}".*?</svg>', self.body, re.S)
        self.assertIsNotNone(m, f"{cls} is not in the page")
        return m.group(0)

    def test_both_background_layers_are_well_formed(self):
        """A malformed background SVG does not fail loudly — the browser drops
        the rest of the drawing and the page still renders."""
        import xml.etree.ElementTree as ET
        for cls in ("globe-eye-bg", "globe-circuits-bg"):
            try:
                ET.fromstring(self._svg(cls))
            except ET.ParseError as exc:
                self.fail(f"{cls} is not well-formed: {exc}")

    def test_the_iris_has_structure(self):
        """It was a bare circle. An iris without fibres or a limbal ring reads
        as a logo, not an eye."""
        svg = self._svg("globe-eye-bg")
        self.assertIn("iris-fibres", svg)
        self.assertIn("pupil-breathe", svg)
        self.assertIn("corneaHi", svg)

    def test_the_highlight_does_not_track_the_gaze(self):
        """A specular reflection is fixed to the light source. Moving it with
        the pupil is the classic tell of a fake eye, so it must live outside
        the group the cursor tracker transforms."""
        import re
        svg = self._svg("globe-eye-bg")
        pupil = re.search(r'<g id="globePupilGroup".*?</g>\s*</g>', svg, re.S)
        self.assertIsNotNone(pupil)
        self.assertNotIn("cornea-hi", pupil.group(0))

    def _traces(self):
        import re
        return re.findall(r'<path class="bg-circuit[^"]*" d="([^"]+)"',
                          self._svg("globe-circuits-bg"))

    @staticmethod
    def _points(d):
        import re
        nums = [float(n) for n in re.findall(r"-?\d+\.?\d*", d)]
        return list(zip(nums[::2], nums[1::2]))

    def test_no_trace_has_a_right_angle(self):
        """A 90° corner traps etchant when the board is made and causes an
        impedance discontinuity when it is used, so layout tools will not
        emit one. Every turn goes through a diagonal."""
        traces = self._traces()
        self.assertGreaterEqual(len(traces), 8, "traces are missing")
        for d in traces:
            pts = self._points(d)
            for a, b, c in zip(pts, pts[1:], pts[2:]):
                square = ((a[0] == b[0] and b[1] == c[1]) or
                          (a[1] == b[1] and b[0] == c[0]))
                self.assertFalse(square, f"right angle at {b} in {d[:50]}")

    def test_every_miter_is_exactly_45_degrees(self):
        """An almost-45 corner reads as a mistake rather than as a style."""
        for d in self._traces():
            pts = self._points(d)
            for a, b in zip(pts, pts[1:]):
                dx, dy = b[0] - a[0], b[1] - a[1]
                if dx and dy:
                    self.assertAlmostEqual(abs(dx), abs(dy), places=6,
                                           msg=f"non-45 segment {a}->{b}")

    def test_nothing_is_routed_off_the_canvas(self):
        for d in self._traces():
            for x, y in self._points(d):
                self.assertTrue(0 <= x <= 800 and 0 <= y <= 800,
                                f"point ({x},{y}) is outside the viewBox")

    def test_the_bond_pads_sit_on_their_wires(self):
        """The pads are the join between die and package; a pad floating off
        its wire is the detail that gives the whole drawing away."""
        import math, re
        svg = self._svg("globe-circuits-bg")
        wires = [tuple(float(v) for v in re.findall(r"-?\d+\.?\d*", d))[:2]
                 for d in re.findall(r'<path d="(M [^"]+)"/>', svg)]
        self.assertTrue(wires, "the bond wires are gone")
        pads = re.findall(r'<rect x="([\d.]+)" y="([\d.]+)" width="9" height="10"', svg)
        self.assertEqual(len(pads), 10, "there should be ten die pads")
        for rx, ry in pads:
            cx, cy = float(rx) + 4.5, float(ry) + 5
            self.assertLess(min(math.hypot(cx - wx, cy - wy) for wx, wy in wires),
                            0.05, f"pad at ({cx},{cy}) is off its wire")

    def test_the_board_travels_with_the_eye(self):
        """The circuit layer is registered to eye coordinates — pads on the die
        edge, traces leaving the lid apexes. The mouse parallax moved the eye
        by up to 60px and left the board behind, so the registration came
        apart on the first pointer move."""
        self.assertIn("circuits.style.transform = eyeShift", self.body)

    def test_the_board_is_populated(self):
        """Bond wires, vias, footprints and silkscreen are what separate a
        circuit board from a flowchart."""
        svg = self._svg("globe-circuits-bg")
        for part in ("bg-bond", "bg-via", "bg-pad", "bg-ic", "bg-smd",
                     "bg-silk", "bg-diff", "copperHatch"):
            self.assertIn(part, svg, f"{part} is missing from the board")

    def test_a_via_is_a_hole_not_a_dot(self):
        css = _read("static", "css", "sauron.css")
        import re
        m = re.search(r"\.globe-circuits-bg \.bg-via circle \{([^}]+)\}", css)
        self.assertIsNotNone(m, "the via rule is gone")
        self.assertIn("fill: none", m.group(1))

    def test_power_traces_are_wider_than_signal_traces(self):
        import re
        css = _read("static", "css", "sauron.css")
        sig = re.search(r"\.globe-circuits-bg \.bg-circuit \{[^}]*stroke-width:\s*([\d.]+)", css)
        pwr = re.search(r"\.bg-circuit--power \{[^}]*stroke-width:\s*([\d.]+)", css)
        self.assertIsNotNone(sig)
        self.assertIsNotNone(pwr)
        self.assertGreater(float(pwr.group(1)), float(sig.group(1)))

    def test_the_ambient_motion_respects_reduced_motion(self):
        """A permanent crawl behind text is what triggers vestibular
        discomfort, and none of it carries information."""
        css = _read("static", "css", "sauron.css")
        block = css[css.find("prefers-reduced-motion"):]
        self.assertIn("pupil-breathe", css)
        self.assertIn("prefers-reduced-motion", css)
        self.assertIn("bg-circuit", block)

    def test_light_mode_recolour_does_not_outline_the_gradients(self):
        """As `*` this also hit the sclera fill and the corneal highlight,
        drawing a hard green outline around two soft gradients."""
        css = _read("static", "css", "sauron.css")
        self.assertNotIn("body.light-mode .globe-eye-bg * {", css)
        self.assertIn('body.light-mode .globe-eye-bg [stroke]:not([stroke="none"])', css)


class LegacyModalMigrationTests(TestCase):
    """The backtest and add-user dialogs were shown by writing
    element.style.display from six call sites, with no Escape, no focus
    management and no scroll lock."""

    def setUp(self):
        self.user = User.objects.create_superuser(
            username="lm_u", password="x", email="a@b.c")
        self.client.force_login(self.user)

    def test_the_backtest_modals_are_declared_to_the_controller(self):
        html = _read("templates", "dashboard", "backtest_list.html")
        self.assertEqual(html.count('data-sv-overlay="dialog"'), 2)
        self.assertIn("SV.overlay.open('btModal')", html)
        self.assertNotIn("style.display='flex'", html)
        self.assertNotIn("style.display = 'flex';", html)

    def test_the_add_user_modal_is_declared_to_the_controller(self):
        html = _read("templates", "dashboard", "admin_dashboard.html")
        self.assertIn('data-sv-open="addUserModal"', html)
        self.assertIn("data-sv-close", html)
        self.assertNotIn("classList.add('active')", html)

    def test_a_self_scrim_dialog_does_not_get_a_second_backdrop(self):
        """These overlays are already a full-viewport dimmed box; the shared
        backdrop on top would dim the page twice."""
        js = _read("static", "js", "sv-overlay.js")
        self.assertIn('if (sel === "none") return null;', js)

    def test_clicking_the_scrim_of_a_self_scrim_dialog_closes_it(self):
        js = _read("static", "js", "sv-overlay.js")
        self.assertIn("t === top.el && isModal(top.el)", js)

    def test_a_tall_modal_can_be_scrolled_to_its_submit_button(self):
        css = _read("static", "css", "sauron.css")
        import re
        m = re.search(r"\n        \.modal \{([^}]+)\}", css)
        self.assertIsNotNone(m)
        self.assertIn("overflow-y: auto", m.group(1))

    def test_the_pages_still_render(self):
        for path in ("/admin-dashboard/", "/backtest/"):
            self.assertEqual(
                self.client.get(path, HTTP_HOST="127.0.0.1").status_code, 200,
                f"{path} broke")


class DestructiveActionTests(TestCase):
    """window.confirm cannot show the thing being destroyed. On this platform
    the guarded actions are disarming a bot and flattening the book, where the
    details ARE the decision."""

    def test_the_flatten_guard_is_a_real_dialog(self):
        html = _read("templates", "dashboard", "admin_dashboard.html")
        self.assertNotIn("onsubmit=\"return confirm(", html)
        self.assertIn("SV.overlay.confirm", html)
        self.assertIn('requireText: "FLATTEN"', html)

    def test_arming_a_bot_is_confirmed_and_names_the_bot(self):
        html = _read("templates", "dashboard", "_admin_bots.html")
        self.assertIn("SV.overlay.confirm", html)
        self.assertIn("data-bot-name", html)

    def test_resetting_a_circuit_breaker_is_confirmed(self):
        """It trips to stop a bot trading; re-arming it silently was the most
        dangerous unguarded control on the page."""
        html = _read("templates", "dashboard", "_admin_bots.html")
        self.assertIn("Reset circuit breaker", html)

    def test_no_native_dialogs_survive_on_the_destructive_surfaces(self):
        import re
        native = re.compile(r"(?<![.\w])(?:window\.)?(?:confirm|alert)\s*\(")
        # Comments discuss the calls that were removed, so strip prose before
        # scanning or the explanation trips the check it is explaining.
        comments = re.compile(r"/\*.*?\*/|//[^\n]*|\{#.*?#\}|\{%\s*comment.*?endcomment\s*%\}",
                              re.S)
        for tpl in ("admin_dashboard.html", "bot_console.html",
                    "_admin_bots.html", "dashboard.html",
                    "_profile_credentials.html"):
            code = comments.sub("", _read("templates", "dashboard", tpl))
            code = code.replace("SV.overlay.confirm(", "").replace(
                "SV.overlay.alert(", "")
            self.assertIsNone(native.search(code),
                              f"{tpl} still calls a native dialog")


class LiveIndicatorTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="li_u", password="x")
        self.client.force_login(self.user)
        self.body = self.client.get(
            "/signals/", HTTP_HOST="127.0.0.1").content.decode("utf-8", "replace")

    def test_the_hardcoded_live_pill_is_gone(self):
        """It was driven by nothing and sat FIRST in the topbar — left of, and
        read before, the real poller that correctly says OFFLINE."""
        self.assertNotIn('<span class="status-dot online"></span> LIVE', self.body)

    def test_the_real_pill_does_not_assert_liveness_before_it_has_checked(self):
        self.assertIn("liveStatusPill", self.body)
        self.assertIn("label0.textContent='…'", self.body)

    def test_a_failed_health_check_degrades_visibly(self):
        """Both failure paths used to exit without touching the DOM, so the
        freshness widget froze while still showing green and '4s ago'."""
        self.assertIn("function degrade(", self.body)
        self.assertIn("STALE", self.body)


# ───────────────────────── panel content honesty ──────────────────────────

class PanelHonestyTests(TestCase):
    """Fourteen of the thirty panel_* names base.html renders were assigned by
    nothing at all."""

    def setUp(self):
        self.user = User.objects.create_user(username="pn_u", password="x")

    def _ctx(self):
        from core.context_processors import sauron_context
        req = RequestFactory().get("/")
        req.user = self.user
        return sauron_context(req)

    def test_the_bot_cell_reports_the_real_bot(self):
        """panel_bot_armed was never set, so the header said OFF / OFFLINE /
        0 open on every page regardless of what the bot was doing."""
        from bot_program.models import AssetBotConfig
        AssetBotConfig.objects.create(user=self.user, asset_class="crypto",
                                      name="c", enabled=True, mode="paper")
        ctx = self._ctx()
        self.assertIs(ctx["panel_bot_armed"], True)
        self.assertEqual(ctx["panel_bot_mode"], "paper")
        self.assertEqual(ctx["panel_bot_open"], 0)

    def test_new_signals_in_24h_are_counted(self):
        from instruments.models import Instrument
        from signals.models import Signal
        inst, _ = Instrument.objects.get_or_create(
            symbol="BTCUSD", defaults={"name": "B", "asset_class": "crypto"})
        Signal.objects.create(instrument=inst, signal_type="technical",
                              direction="bullish", urgency="high", title="t",
                              score=0.5, is_active=True, price_at_signal=100)
        self.assertEqual(self._ctx()["panel_signals_24h"], 1)

    def test_an_unmeasured_figure_is_none_and_never_a_confident_zero(self):
        """A red 0.0% drawdown reads as "no downside", not as "we have never
        taken a snapshot"."""
        ctx = self._ctx()
        for key in ("panel_drawdown", "panel_daily_pnl_display",
                    "panel_liq_24h_display", "panel_funding_display"):
            self.assertIsNone(ctx[key], f"{key} fabricates a measurement")

    def test_the_template_renders_a_dash_rather_than_a_zero(self):
        self.client.force_login(self.user)
        body = self.client.get("/signals/", HTTP_HOST="127.0.0.1").content.decode(
            "utf-8", "replace")
        self.assertIn("sv-unknown", body)
        self.assertNotIn('{{ panel_drawdown|default:"0" }}', body)

    def test_large_money_is_compacted_to_fit_its_cell(self):
        from core.context_processors import _compact
        self.assertEqual(_compact(1_238_904_551), "1.2B")
        self.assertEqual(_compact(340_000), "340.0K")
        self.assertIsNone(_compact(None))


# ──────────────────────────── ingest honesty ──────────────────────────────

class TaskGateJudgementTests(TestCase):
    """The gate called mark_run(success=True) for any return that did not
    raise, and every scraper returns a hardcoded {"status": "success"}. So no
    scraper could ever mark itself unhealthy."""

    def test_parsing_rows_and_storing_none_is_a_warning(self):
        from core.task_gate import judge_result
        status, msg = judge_result({"status": "success", "parsed": 40, "stored": 0})
        self.assertEqual(status, "warning")
        self.assertIn("40", msg)

    def test_storing_rows_is_a_success(self):
        from core.task_gate import judge_result
        self.assertEqual(judge_result({"parsed": 40, "stored": 12})[0], "success")

    def test_a_missing_credential_is_a_warning_not_a_quiet_success(self):
        from core.task_gate import judge_result
        self.assertEqual(
            judge_result({"status": "success", "skipped": "no_api_key"})[0],
            "warning")

    def test_nested_source_results_are_summed(self):
        from core.task_gate import judge_result
        status, _ = judge_result({"status": "success",
                                  "rss": {"parsed": 9, "stored": 0},
                                  "api": {"parsed": 0, "stored": 0}})
        self.assertEqual(status, "warning")

    def test_a_task_with_no_counts_keeps_the_benefit_of_the_doubt(self):
        from core.task_gate import judge_result
        self.assertEqual(judge_result({"status": "success"})[0], "success")
        self.assertEqual(judge_result(None)[0], "success")

    def test_a_warning_does_not_inflate_the_error_count(self):
        from core.platform_control import PlatformComponent
        c = PlatformComponent.objects.create(key="k_warn", name="W",
                                             category="scraper")
        c.mark_run(success=False, message="parsed 5 stored 0", status="warning")
        c.refresh_from_db()
        self.assertEqual(c.last_status, "warning")
        self.assertEqual(c.error_count, 0)


class RssTimestampTests(TestCase):
    """Django 5.0 removed django.utils.timezone.utc. The expression building
    every article's published_at raised AttributeError on every entry, a bare
    except substituted now(), and the column silently became "time we
    scraped it" — which every 24h window on the platform then measured."""

    def test_django_really_did_remove_the_attribute(self):
        self.assertFalse(hasattr(timezone, "utc"),
                         "the premise of this fix no longer holds")

    def test_a_feed_timestamp_is_preserved_not_replaced_with_now(self):
        from scraping.scrapers.news_aggregator import _published_at
        got = _published_at({"published_parsed": (2026, 3, 4, 5, 6, 7, 0, 0, 0)})
        self.assertEqual(got, datetime(2026, 3, 4, 5, 6, 7, tzinfo=dt_timezone.utc))

    def test_an_entry_with_no_date_reports_that_rather_than_guessing(self):
        from scraping.scrapers.news_aggregator import _published_at
        self.assertIsNone(_published_at({}))

    def test_the_dead_reuters_feeds_are_gone(self):
        from scraping.scrapers.news_aggregator import RSS_FEEDS
        self.assertNotIn("reuters_business", RSS_FEEDS)


class EarningsBlackoutTests(TestCase):
    """The blackout has never fired: EconomicEvent was empty because this
    scraper had no persist helper at all."""

    def test_the_calendar_now_writes_events(self):
        from market_data.models import EconomicEvent
        from scraping.scrapers.earnings_calendar import _persist_earnings
        n = _persist_earnings([{"symbol": "AAPL", "date": "2026-09-01",
                                "time": "amc", "eps_estimated": 1.5}])
        self.assertEqual(n, 1)
        self.assertTrue(EconomicEvent.objects.filter(title="AAPL Earnings").exists())

    def test_the_stored_title_is_what_the_bot_guard_matches_on(self):
        """The wording is load-bearing: stock_bot filters on the symbol AND
        the word "earnings" being in the title."""
        from scraping.scrapers.earnings_calendar import _persist_earnings
        from bot_program.asset_engine.stock_bot import _has_upcoming_earnings

        soon = (timezone.now() + timedelta(days=2)).date().isoformat()
        _persist_earnings([{"symbol": "MSFT", "date": soon, "time": "bmo"}])
        blocked, label = _has_upcoming_earnings("MSFT", days_ahead=5)
        self.assertTrue(blocked, "the blackout still does not fire")
        self.assertIn("MSFT", label)

    def test_re_running_updates_rather_than_duplicating(self):
        from market_data.models import EconomicEvent
        from scraping.scrapers.earnings_calendar import _persist_earnings
        row = [{"symbol": "TSLA", "date": "2026-09-02", "time": "amc"}]
        _persist_earnings(row)
        _persist_earnings(row)
        self.assertEqual(EconomicEvent.objects.filter(title="TSLA Earnings").count(), 1)

    def test_a_quarter_later_is_a_separate_event(self):
        from market_data.models import EconomicEvent
        from scraping.scrapers.earnings_calendar import _persist_earnings
        _persist_earnings([{"symbol": "TSLA", "date": "2026-09-02", "time": "amc"}])
        _persist_earnings([{"symbol": "TSLA", "date": "2026-12-02", "time": "amc"}])
        self.assertEqual(EconomicEvent.objects.filter(title="TSLA Earnings").count(), 2)

    def test_a_junk_date_is_skipped_rather_than_stored_as_today(self):
        from scraping.scrapers.earnings_calendar import _persist_earnings
        self.assertEqual(_persist_earnings([{"symbol": "X", "date": "soon"}]), 0)

    def test_a_missing_key_is_reported_not_silently_empty(self):
        import os
        from unittest.mock import patch
        from scraping.scrapers.earnings_calendar import fetch_earnings_calendar_fmp
        with patch.dict(os.environ, {"FMP_API_KEY": ""}, clear=False):
            out = fetch_earnings_calendar_fmp()
        self.assertEqual(out["skipped"], "no_api_key")


class SentimentWiringTests(TestCase):
    def setUp(self):
        from instruments.models import Instrument
        self.inst, _ = Instrument.objects.get_or_create(
            symbol="AAPL", defaults={"name": "Apple", "asset_class": "stock"})

    def test_a_trending_symbol_is_stored_as_trending(self):
        """fetch_symbol_sentiment persisted before returning, so a caller
        setting item["trending"] afterwards changed nothing about the row."""
        from scraping.scrapers.stocktwits import _persist_sentiment_snapshot
        from scraping.models import SentimentSnapshot
        n = _persist_sentiment_snapshot({
            "symbol": "AAPL", "bullish_count": 7, "bearish_count": 2,
            "neutral_count": 1, "composite_score": 0.5, "volume": 10,
            "trending": True})
        self.assertEqual(n, 1)
        self.assertTrue(SentimentSnapshot.objects.get(instrument=self.inst).trending)

    def test_a_payload_missing_the_tallies_does_not_raise_into_a_swallow(self):
        """The trending payload has a different shape to the stream payload,
        and hard subscripts raised KeyError straight into a DEBUG-level
        except that hid it."""
        from scraping.scrapers.stocktwits import _persist_sentiment_snapshot
        self.assertEqual(_persist_sentiment_snapshot(
            {"symbol": "AAPL", "trending": True}), 1)

    def test_an_unknown_symbol_is_dropped_without_raising(self):
        from scraping.scrapers.stocktwits import _persist_sentiment_snapshot
        self.assertEqual(_persist_sentiment_snapshot({"symbol": "NOPE"}), 0)


class InsiderFilingTests(TestCase):
    def test_insider_rows_reach_the_database(self):
        """fetch_insider_trades built rows with a resolvable instrument — the
        only path that could satisfy the persist guard — and then never called
        the helper."""
        from instruments.models import Instrument
        from scraping.models import InstitutionalFiling
        from scraping.scrapers.sec_edgar import _persist_institutional_filings

        Instrument.objects.get_or_create(
            symbol="NVDA", defaults={"name": "Nvidia", "asset_class": "stock"})
        n = _persist_institutional_filings([{
            "filer_name": "A Person", "filing_type": "4",
            "filing_date": date(2026, 5, 1).isoformat(), "instrument": "NVDA",
            "source_url": "https://sec.gov/x/1"}])
        self.assertEqual(n, 1)
        self.assertEqual(InstitutionalFiling.objects.count(), 1)

    def test_a_13f_with_no_resolvable_holding_is_still_recorded(self):
        """13F holdings live in a separate attachment this scraper does not
        follow, so instrument was hardcoded None and every row was discarded
        at write time. Knowing a manager filed is worth keeping."""
        from scraping.models import InstitutionalFiling
        from scraping.scrapers.sec_edgar import _persist_institutional_filings
        n = _persist_institutional_filings([{
            "filer_name": "Big Fund LP", "filing_type": "13F",
            "filing_date": "2026-05-01", "instrument": None,
            "source_url": "https://sec.gov/x/2"}])
        self.assertEqual(n, 1)
        self.assertIsNone(InstitutionalFiling.objects.get().instrument)

    def test_the_same_filing_twice_is_stored_once(self):
        """SQL treats two NULL instruments as distinct, so unique_together
        cannot dedupe these — the accession URL has to."""
        from scraping.models import InstitutionalFiling
        from scraping.scrapers.sec_edgar import _persist_institutional_filings
        row = [{"filer_name": "Big Fund LP", "filing_type": "13F",
                "filing_date": "2026-05-01", "instrument": None,
                "source_url": "https://sec.gov/x/3"}]
        _persist_institutional_filings(row)
        _persist_institutional_filings(row)
        self.assertEqual(InstitutionalFiling.objects.count(), 1)


class DeadModuleTests(TestCase):
    def test_the_unreferenced_scrapers_are_gone(self):
        """investing_com had zero callers and its only write targeted a model
        that does not exist. models_options declared a second OptionsFlow with
        the same related_name as the real one."""
        base = Path(settings.BASE_DIR)
        self.assertFalse((base / "scraping" / "scrapers" / "investing_com.py").exists())
        self.assertFalse((base / "scraping" / "models_options.py").exists())

    def test_an_empty_watchlist_no_longer_makes_a_scraper_a_no_op(self):
        """Zero of 179 instruments had is_watchlist set, so every per-symbol
        loop iterated nothing and reported success."""
        from instruments.models import Instrument
        from market_data.models import PriceData
        from scraping.tasks import _scan_universe

        inst, _ = Instrument.objects.get_or_create(
            symbol="ETHUSD", defaults={"name": "Ether", "asset_class": "crypto"})
        PriceData.objects.create(instrument=inst, timeframe="1d",
                                 timestamp=timezone.now(), open=1, high=1,
                                 low=1, close=1, volume=1)
        self.assertEqual([i.symbol for i in _scan_universe()], ["ETHUSD"])

    def test_a_real_watchlist_still_wins(self):
        from instruments.models import Instrument
        from scraping.tasks import _scan_universe
        Instrument.objects.get_or_create(
            symbol="SOLUSD",
            defaults={"name": "Sol", "asset_class": "crypto", "is_watchlist": True})
        self.assertEqual([i.symbol for i in _scan_universe()], ["SOLUSD"])
