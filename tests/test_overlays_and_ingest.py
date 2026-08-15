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


class NotificationPanelTests(TestCase):
    """The bell panel opened underneath the signals rail, because it lived
    inside .topbar — which carries backdrop-filter, and that creates a
    stacking context no descendant can climb out of by declaring a bigger
    z-index."""

    def setUp(self):
        self.user = User.objects.create_user(username="np_u", password="x")
        self.client.force_login(self.user)
        from alerts.models import Notification
        Notification.objects.create(user=self.user, notification_type="bot",
                                    title="Bot disarmed", body="after 3 losses",
                                    url="/asset-bots/")
        self.body = self.client.get(
            "/signals/", HTTP_HOST="127.0.0.1").content.decode("utf-8", "replace")

    def test_the_panel_leaves_the_topbar_when_it_opens(self):
        self.assertIn('id="notifPanel"', self.body)
        self.assertIn("data-sv-portal", self.body)

    def test_the_controller_really_moves_it_to_the_body(self):
        js = _read("static", "js", "sv-overlay.js")
        self.assertIn("d.body.appendChild(el)", js)
        self.assertIn("portalHome", js)

    def test_it_is_returned_to_its_own_parent_on_close(self):
        """An overlay orphaned on <body> survives an htmx swap of the region
        it came from, and the next render produces a second copy."""
        js = _read("static", "js", "sv-overlay.js")
        self.assertIn("home.parent.insertBefore(el, home.next)", js)

    def test_the_bell_is_a_button_the_keyboard_can_reach(self):
        self.assertIn('<button type="button" class="notif-bell"', self.body)
        self.assertIn('data-sv-open="notifPanel"', self.body)

    def test_the_bespoke_outside_click_handler_is_gone(self):
        self.assertNotIn("bell.classList.remove('open')", self.body)

    def test_a_row_says_what_kind_of_event_it_was(self):
        """Ten identically-styled titles gave the operator no way to pick the
        one that mattered."""
        self.assertIn("ni-kind", self.body)
        self.assertIn("ni-bot", self.body)


class InfoPanelDetailTests(TestCase):
    """Several bottom-headband dropdowns held a title and a link to the page
    you were one click from anyway. ALERTS and WATCHLIST held nothing else at
    all; DRAWDOWN and VOLATILITY had no panel."""

    def setUp(self):
        self.user = User.objects.create_user(username="ipd_u", password="x")
        from django.core.cache import cache
        cache.clear()

    def _detail(self):
        from core.context_processors import _panel_detail
        return _panel_detail(self.user)

    def test_an_open_position_carries_its_live_r(self):
        """R is the number that says whether a position is working, and it is
        computable from the entry, the opening stop and a live quote."""
        from bot_program.models import AssetBotConfig, AssetBotTrade
        from instruments.models import Instrument
        from market_data.models import LiveQuote
        from decimal import Decimal

        inst, _ = Instrument.objects.get_or_create(
            symbol="BTCUSD", defaults={"name": "B", "asset_class": "crypto"})
        LiveQuote.objects.update_or_create(
            instrument=inst, defaults={"last": Decimal("110")})
        cfg = AssetBotConfig.objects.create(user=self.user, asset_class="crypto",
                                            name="c", enabled=True, mode="paper")
        AssetBotTrade.objects.create(config=cfg, asset_class="crypto",
                                     symbol="BTCUSD", side="BUY", qty=1,
                                     entry_price=100, stop_loss=95, status="OPEN")
        row = self._detail()["panel_open_trades"][0]
        # entry 100, stop 95 -> 5 of risk; last 110 -> +10 -> 2R
        self.assertAlmostEqual(row["r"], 2.0, places=2)
        self.assertAlmostEqual(row["pct"], 10.0, places=2)

    def test_a_position_with_no_quote_reports_unknown_not_zero(self):
        from bot_program.models import AssetBotConfig, AssetBotTrade
        cfg = AssetBotConfig.objects.create(user=self.user, asset_class="crypto",
                                            name="c2", enabled=True, mode="paper")
        AssetBotTrade.objects.create(config=cfg, asset_class="crypto",
                                     symbol="NOQUOTE", side="BUY", qty=1,
                                     entry_price=100, stop_loss=95, status="OPEN")
        row = next(r for r in self._detail()["panel_open_trades"]
                   if r["symbol"] == "NOQUOTE")
        self.assertIsNone(row["r"])

    def test_the_signals_panel_names_the_signals(self):
        """It rendered four counts and not one of the actual signals."""
        from instruments.models import Instrument
        from signals.models import Signal
        inst, _ = Instrument.objects.get_or_create(
            symbol="ETHUSD", defaults={"name": "E", "asset_class": "crypto"})
        Signal.objects.create(instrument=inst, signal_type="technical",
                              direction="bullish", urgency="high", title="t",
                              score=0.8, is_active=True, price_at_signal=1)
        top = self._detail()["panel_top_signals"]
        self.assertEqual(top[0]["symbol"], "ETHUSD")
        self.assertEqual(top[0]["score_pct"], 80)

    def test_volatility_is_not_pinned_to_a_timeframe_we_may_not_hold(self):
        """It asked for 1d bars. This deployment holds 4h and 1h and no daily
        bars at all, so the cell could never have filled."""
        from instruments.models import Instrument
        from market_data.models import PriceData
        inst, _ = Instrument.objects.get_or_create(
            symbol="VOLT", defaults={"name": "V", "asset_class": "crypto"})
        base = timezone.now()
        for i in range(30):
            PriceData.objects.create(
                instrument=inst, timeframe="4h",
                timestamp=base - timedelta(hours=4 * i),
                open=100 + i, high=101 + i, low=99 + i,
                close=100 + (i % 5), volume=1)
        d = self._detail()
        self.assertIsNotNone(d.get("panel_vol_pct"))
        self.assertEqual(d.get("panel_vol_tf"), "4h")

    def test_the_detail_is_cached_so_it_does_not_cost_every_page(self):
        import inspect
        from core import context_processors
        src = inspect.getsource(context_processors._panel_detail)
        self.assertIn("cache.set(", src)

    def test_the_cache_is_bypassed_under_the_test_runner(self):
        """Primary keys restart after every rollback, so a payload cached for
        user 3 in one test would be served to a different user 3 in the next —
        which made any assertion touching the headband depend on how long the
        preceding test happened to take."""
        import inspect
        from core import context_processors
        src = inspect.getsource(context_processors._panel_detail)
        self.assertIn("testing", src)
        self.assertIn("if not testing:", src)


class AskSauronTests(TestCase):
    """The chat was a form POST that reloaded the whole page, messages could
    not be deleted, and past conversations were listed in a table with no way
    to open one."""

    def setUp(self):
        self.user = User.objects.create_user(username="as_u", password="x")
        self.client.force_login(self.user)

    def _conv(self):
        from brain.research_agent import get_or_create_active_conversation
        return get_or_create_active_conversation(self.user)

    def _msg(self, role, content, conv=None):
        from brain.research_models import ResearchMessage
        return ResearchMessage.objects.create(
            conversation=conv or self._conv(), role=role, content=content)

    def test_the_page_renders_as_a_chat(self):
        body = self.client.get("/research/", HTTP_HOST="127.0.0.1").content.decode(
            "utf-8", "replace")
        for part in ("chat-log", "chat-compose", "turn-tool", "chat-intro"):
            self.assertIn(part, body)

    def test_deleting_a_question_takes_its_answer_with_it(self):
        """A question and the reply it produced are one exchange; deleting the
        question alone leaves the assistant talking to itself."""
        from brain.research_models import ResearchMessage
        q = self._msg("user", "why?")
        a = self._msg("assistant", "because.")
        r = self.client.post(f"/research/message/{q.id}/delete/",
                             HTTP_HOST="127.0.0.1")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])
        self.assertFalse(ResearchMessage.objects.filter(
            pk__in=[q.pk, a.pk]).exists())

    def test_deleting_an_answer_leaves_the_question(self):
        from brain.research_models import ResearchMessage
        q = self._msg("user", "why?")
        a = self._msg("assistant", "because.")
        self.client.post(f"/research/message/{a.id}/delete/", HTTP_HOST="127.0.0.1")
        self.assertTrue(ResearchMessage.objects.filter(pk=q.pk).exists())
        self.assertFalse(ResearchMessage.objects.filter(pk=a.pk).exists())

    def test_another_users_message_cannot_be_deleted(self):
        from brain.research_agent import get_or_create_active_conversation
        from brain.research_models import ResearchMessage
        other = User.objects.create_user(username="as_other", password="x")
        theirs = ResearchMessage.objects.create(
            conversation=get_or_create_active_conversation(other),
            role="user", content="private")
        r = self.client.post(f"/research/message/{theirs.id}/delete/",
                             HTTP_HOST="127.0.0.1")
        self.assertEqual(r.status_code, 404)
        self.assertTrue(ResearchMessage.objects.filter(pk=theirs.pk).exists())

    def test_deleting_a_conversation_removes_its_messages(self):
        from brain.research_models import ResearchConversation, ResearchMessage
        conv = self._conv()
        self._msg("user", "a", conv)
        r = self.client.post(f"/research/conversation/{conv.id}/delete/",
                             HTTP_HOST="127.0.0.1")
        self.assertTrue(r.json()["ok"])
        self.assertFalse(ResearchConversation.objects.filter(pk=conv.pk).exists())
        self.assertFalse(ResearchMessage.objects.filter(conversation_id=conv.pk).exists())

    def test_deleting_the_open_thread_leaves_one_to_type_into(self):
        from brain.research_models import ResearchConversation
        conv = self._conv()
        self.client.post(f"/research/conversation/{conv.id}/delete/",
                         HTTP_HOST="127.0.0.1")
        self.assertTrue(ResearchConversation.objects.filter(
            user=self.user, is_active=True).exists())

    def test_a_past_conversation_can_be_reopened(self):
        """The history was visible and unreachable: the only thing you could
        do with a thread was start a new one on top of it."""
        from brain.research_agent import archive_active_conversation
        from brain.research_models import ResearchConversation
        old = self._conv()
        self._msg("user", "older question", old)
        archive_active_conversation(self.user)
        self._conv()                                  # a new active thread

        r = self.client.post(f"/research/conversation/{old.id}/open/",
                             HTTP_HOST="127.0.0.1")
        self.assertEqual(r.status_code, 302)
        old.refresh_from_db()
        self.assertTrue(old.is_active)
        self.assertEqual(ResearchConversation.objects.filter(
            user=self.user, is_active=True).count(), 1,
            "exactly one thread may be active")

    def test_the_floating_panel_can_delete_a_turn_too(self):
        body = self.client.get("/signals/", HTTP_HOST="127.0.0.1").content.decode(
            "utf-8", "replace")
        self.assertIn("data-se-del", body)
        self.assertIn("se-bubble-tools", body)


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


class SystemMapTests(TestCase):
    """The admin panel could say whether a task was switched on and whether it
    raised. It could not say whether anything arrived — which is why six
    scrapers sat at last_status='success' holding zero rows between them, with
    the earnings calendar among them and the bot's earnings blackout silently
    inert."""

    def setUp(self):
        self.user = User.objects.create_superuser(
            username="sm_u", password="x", email="sm@x.co")
        self.client.force_login(self.user)

    def _map(self):
        from dashboard.views_system_map import collect_system_map
        return collect_system_map(self.user)

    def _nodes(self):
        out = {}
        for stage in self._map()["stages"]:
            for n in stage["nodes"]:
                out[n["key"]] = n
        return out

    def test_the_page_renders_for_staff(self):
        r = self.client.get("/admin-dashboard/system-map/", HTTP_HOST="127.0.0.1")
        self.assertEqual(r.status_code, 200)

    def test_it_is_not_reachable_by_a_normal_operator(self):
        User.objects.create_user(username="sm_plain", password="x")
        self.client.logout()
        self.client.login(username="sm_plain", password="x")
        r = self.client.get("/admin-dashboard/system-map/", HTTP_HOST="127.0.0.1")
        self.assertIn(r.status_code, (302, 403))

    def test_every_node_carries_a_state_and_an_explanation(self):
        """A state with no sentence behind it sends the admin hunting, which is
        the thing this page exists to stop."""
        from dashboard.views_system_map import STATE_META
        for key, n in self._nodes().items():
            self.assertIn(n["state"], STATE_META, key)
            self.assertTrue(n["why"].strip(), f"{key} has a state and no reason")
            self.assertTrue(n["purpose"].strip(), f"{key} does not say what it does")

    def test_an_empty_table_is_never_reported_as_healthy(self):
        n = self._nodes()["calendar"]
        self.assertIn(n["state"], ("idle", "stale", "unconfigured", "off"))
        self.assertNotEqual(n["state"], "live")

    def test_the_empty_calendar_names_the_guard_it_disables(self):
        """The whole point of the page: say what the empty table costs."""
        why = self._nodes()["calendar"]["why"].lower()
        self.assertIn("blackout", why)

    def test_data_that_stopped_arriving_reads_stale_not_live(self):
        from instruments.models import Instrument
        from market_data.models import PriceData
        inst, _ = Instrument.objects.get_or_create(
            symbol="OLD", defaults={"name": "O", "asset_class": "crypto"})
        PriceData.objects.create(
            instrument=inst, timeframe="4h",
            timestamp=timezone.now() - timedelta(days=9),
            open=1, high=1, low=1, close=1, volume=1)
        n = self._nodes()["bars"]
        self.assertEqual(n["state"], "stale")
        self.assertIn("nothing new", n["why"])

    def test_fresh_data_reads_live(self):
        from instruments.models import Instrument
        from market_data.models import PriceData
        inst, _ = Instrument.objects.get_or_create(
            symbol="NEW", defaults={"name": "N", "asset_class": "crypto"})
        PriceData.objects.create(
            instrument=inst, timeframe="4h", timestamp=timezone.now(),
            open=1, high=1, low=1, close=1, volume=1)
        self.assertEqual(self._nodes()["bars"]["state"], "live")

    def test_a_disabled_component_outranks_its_data_verdict(self):
        """OFF is an answer. STALE on a switched-off task is a red herring."""
        from core.platform_control import PlatformComponent
        PlatformComponent.objects.update_or_create(
            key="scraper_calendar",
            defaults={"name": "Economic Calendar", "category": "scraper",
                      "is_enabled": False})
        self.assertEqual(self._nodes()["calendar"]["state"], "off")

    def test_a_component_that_stored_nothing_reads_stale(self):
        """This is the exact failure the platform had: the task returns without
        raising, the gate marks it a warning, and the map must show it."""
        from core.platform_control import PlatformComponent
        PlatformComponent.objects.update_or_create(
            key="scraper_news",
            defaults={"name": "Breaking News", "category": "scraper",
                      "is_enabled": True, "last_status": "warning",
                      "last_message": "parsed 40 rows and stored none"})
        n = self._nodes()["news"]
        self.assertEqual(n["state"], "stale")
        self.assertIn("stored none", n["why"])

    def test_a_stranded_close_is_the_worst_state_available(self):
        """A position still open at the broker after a failed close needs a
        human, so it must outrank everything else on the page."""
        from bot_program.models import AssetBotConfig, AssetBotTrade
        cfg = AssetBotConfig.objects.create(
            user=self.user, asset_class="crypto", name="c",
            enabled=True, mode="paper")
        AssetBotTrade.objects.create(
            config=cfg, asset_class="crypto", symbol="BTCUSD", side="BUY",
            qty=1, entry_price=100, status="CLOSE_PENDING")
        m = self._map()
        trades = self._nodes()["trades"]
        self.assertEqual(trades["state"], "broken")
        self.assertEqual(m["verdict"], "critical")
        self.assertEqual(m["problems"][0]["key"], "trades")

    def test_problems_are_ranked_worst_first(self):
        from dashboard.views_system_map import STATE_ORDER
        problems = self._map()["problems"]
        ranks = [STATE_ORDER.index(p["state"]) for p in problems]
        self.assertEqual(ranks, sorted(ranks))

    def test_healthy_nodes_stay_out_of_the_problem_list(self):
        for p in self._map()["problems"]:
            self.assertIn(p["state"], ("broken", "stale", "unconfigured"))

    def test_throughput_bars_are_proportional_to_the_busiest_stage(self):
        for row in self._map()["stage_rows"]:
            self.assertGreaterEqual(row["pct"], 0)
            self.assertLessEqual(row["pct"], 100)

    def test_a_state_is_never_communicated_by_colour_alone(self):
        """Every pill ships a glyph and a word beside its tone."""
        from dashboard.views_system_map import STATE_META
        for key, meta in STATE_META.items():
            self.assertTrue(meta["glyph"], key)
            self.assertTrue(meta["label"], key)
            self.assertTrue(meta["hint"], key)

    def test_the_admin_panel_links_to_both_divisions(self):
        body = self.client.get(
            "/admin-dashboard/", HTTP_HOST="127.0.0.1").content.decode("utf-8", "replace")
        self.assertIn("hq-divisions", body)
        self.assertIn("/admin-dashboard/system-map/", body)

    def test_the_page_renders_no_leaked_template_tags(self):
        """Django's {# #} is single-line only; a multi-line one is not a
        comment and renders as literal text on the page."""
        body = self.client.get(
            "/admin-dashboard/system-map/", HTTP_HOST="127.0.0.1").content.decode("utf-8", "replace")
        self.assertNotIn("{#", body)
        self.assertNotIn("{% comment", body)


class TopologyMapTests(TestCase):
    """The map draws Sauron as a machine you can reach into. Two things have to
    hold or it is worse than no map: an edge must correspond to a real
    read/write relationship, and a switch must reflect what the server
    actually did."""

    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="tm_admin", password="x", email="a@b.co")
        self.client.force_login(self.admin)

    def _topo(self):
        from dashboard.views_topology import build_topology
        return build_topology(self.admin)

    def _payload(self, script_id):
        import json
        import re
        body = self.client.get(
            "/admin-dashboard/system-map/", HTTP_HOST="127.0.0.1").content.decode(
            "utf-8", "replace")
        m = re.search(r'id="' + script_id + r'"[^>]*>(.*?)</script>', body, re.S)
        self.assertIsNotNone(m, script_id + " is not on the page")
        return json.loads(m.group(1))

    def test_the_map_renders_for_staff(self):
        r = self.client.get("/admin-dashboard/system-map/", HTTP_HOST="127.0.0.1")
        self.assertEqual(r.status_code, 200)

    def test_the_payloads_are_real_json(self):
        """They are handed over with json_script. Interpolating a Python dict
        into a <script> emits repr() — single quotes, True, None — which is a
        syntax error the moment a label carries an apostrophe."""
        nodes = self._payload("tmNodeData")
        self.assertTrue(nodes)
        self.assertIn("key", nodes[0])

    def test_every_node_has_a_state_and_a_reason(self):
        from dashboard.views_topology import STATE_META
        for n in self._topo()["nodes"]:
            self.assertIn(n["state"], STATE_META, n["key"])
            self.assertTrue(n["why"].strip(), n["key"] + " has no reason")

    def test_an_edge_never_points_at_a_node_that_is_not_drawn(self):
        """A dangling edge draws a line to nowhere."""
        topo = self._topo()
        keys = {n["key"] for n in topo["nodes"]}
        for e in topo["edges"]:
            self.assertIn(e["from"], keys)
            self.assertIn(e["to"], keys)

    def test_no_node_feeds_itself(self):
        for e in self._topo()["edges"]:
            self.assertNotEqual(e["from"], e["to"])

    def test_an_edge_only_animates_when_its_source_is_producing(self):
        """A moving dash on a dead feed is the map telling a lie."""
        topo = self._topo()
        by_key = {n["key"]: n for n in topo["nodes"]}
        for e in topo["edges"]:
            if e["live"]:
                self.assertEqual(by_key[e["from"]]["state"], "live", e["from"])

    def test_a_component_that_stored_nothing_reads_silent_not_live(self):
        """The exact failure this platform had: the task runs, does not raise,
        and writes no rows."""
        from core.platform_control import PlatformComponent
        PlatformComponent.objects.update_or_create(
            key="scraper_news",
            defaults={"name": "Breaking News", "category": "scraper",
                      "is_enabled": True, "last_status": "warning",
                      "last_message": "parsed 40 rows and stored none",
                      "last_run_at": timezone.now()})
        node = next(n for n in self._topo()["nodes"] if n["key"] == "scraper_news")
        self.assertEqual(node["state"], "silent")
        self.assertIn("stored nothing", node["why"])

    def test_the_eye_goes_dark_with_the_master_switch(self):
        from core.platform_control import PlatformComponent
        PlatformComponent.objects.update_or_create(
            key="platform_master",
            defaults={"name": "Master", "category": "system", "is_enabled": False})
        eye = next(n for n in self._topo()["nodes"] if n["key"] == "eye_core")
        self.assertEqual(eye["state"], "off")
        self.assertIn("master switch", eye["why"].lower())

    def test_toggling_a_component_flips_it_and_says_so(self):
        from core.platform_control import PlatformComponent
        PlatformComponent.objects.update_or_create(
            key="scraper_cot",
            defaults={"name": "COT", "category": "scraper", "is_enabled": True})
        r = self.client.post("/admin-dashboard/system-map/toggle/",
                             {"kind": "component", "key": "scraper_cot"},
                             HTTP_HOST="127.0.0.1")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()["enabled"])
        self.assertFalse(PlatformComponent.objects.get(key="scraper_cot").is_enabled)

    def test_toggling_something_that_does_not_exist_is_refused(self):
        r = self.client.post("/admin-dashboard/system-map/toggle/",
                             {"kind": "component", "key": "no_such_component"},
                             HTTP_HOST="127.0.0.1")
        self.assertEqual(r.status_code, 404)
        self.assertFalse(r.json()["ok"])

    def test_a_bot_toggle_is_scoped_to_its_owner(self):
        """Arming another operator's bot from a map should not be one request
        away."""
        from bot_program.models import AssetBotConfig
        other = User.objects.create_user(username="tm_other", password="x")
        theirs = AssetBotConfig.objects.create(
            user=other, asset_class="crypto", name="theirs",
            enabled=True, mode="paper")
        r = self.client.post("/admin-dashboard/system-map/toggle/",
                             {"kind": "bot", "key": theirs.id},
                             HTTP_HOST="127.0.0.1")
        self.assertEqual(r.status_code, 404)
        theirs.refresh_from_db()
        self.assertTrue(theirs.enabled)

    def test_a_staff_reader_cannot_arm_the_platform(self):
        """Reading the map is a staff activity; arming and disarming is not."""
        staff = User.objects.create_user(username="tm_staff", password="x",
                                         is_staff=True)
        self.client.force_login(staff)
        self.assertEqual(
            self.client.get("/admin-dashboard/system-map/",
                            HTTP_HOST="127.0.0.1").status_code, 200)
        r = self.client.post("/admin-dashboard/system-map/toggle/",
                             {"kind": "component", "key": "scraper_cot"},
                             HTTP_HOST="127.0.0.1")
        self.assertIn(r.status_code, (302, 403))

    def test_the_state_endpoint_carries_every_node(self):
        """The map refreshes from this rather than re-rendering, which would
        throw away the inspector and the scroll position every 15 seconds."""
        topo = self._topo()
        r = self.client.get("/admin-dashboard/system-map/state/",
                            HTTP_HOST="127.0.0.1")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json()["nodes"]), len(topo["nodes"]))

    def test_a_bot_with_a_stranded_close_is_drawn_broken(self):
        from bot_program.models import AssetBotConfig, AssetBotTrade
        cfg = AssetBotConfig.objects.create(
            user=self.admin, asset_class="crypto", name="c",
            enabled=True, mode="paper")
        AssetBotTrade.objects.create(
            config=cfg, asset_class="crypto", symbol="BTCUSD", side="BUY",
            qty=1, entry_price=100, status="CLOSE_PENDING")
        node = next(n for n in self._topo()["nodes"]
                    if n["key"] == "bot_" + str(cfg.id))
        self.assertEqual(node["state"], "broken")
        self.assertIn("broker", node["why"])

    def test_mode_flags_are_folded_into_their_parent(self):
        """actuator_mode_live has no task, no schedule and no output. As its
        own node it would be a box with no edges, which reads as broken."""
        from dashboard.views_topology import MODE_FLAGS
        keys = {n["key"] for n in self._topo()["nodes"]}
        for flag in MODE_FLAGS:
            self.assertNotIn(flag, keys)


class TaskGateThroughputTests(TestCase):
    """The gate judges a task by what it produced, not by whether it raised.

    It already caught the scrapers, which report parsed/stored. It did not
    catch the market-data pollers, which predate that convention and report a
    single `fetched` count — so judge_result looked at them, found neither key,
    and waved them through. A quote poller writing zero rows stayed permanently
    green, which is the exact failure this function exists to catch, one module
    over."""

    def test_a_poller_that_wrote_nothing_is_a_warning(self):
        from core.task_gate import judge_result
        state, msg = judge_result({"status": "success", "fetched": 0})
        self.assertEqual(state, "warning")
        self.assertIn("nothing", msg)

    def test_a_poller_that_wrote_rows_is_healthy(self):
        from core.task_gate import judge_result
        self.assertEqual(judge_result({"status": "success", "fetched": 6})[0], "success")

    def test_requests_that_stored_nothing_are_a_warning(self):
        from core.task_gate import judge_result
        state, msg = judge_result({"status": "success", "attempted": 10, "fetched": 0})
        self.assertEqual(state, "warning")
        self.assertIn("10", msg)

    def test_every_count_key_the_platform_uses_is_recognised(self):
        """bars_saved and observations_saved are real return keys in
        market_data.tasks; missing one silently re-opens the hole."""
        from core.task_gate import judge_result
        self.assertEqual(judge_result({"status": "success", "bars_saved": 12})[0], "success")
        self.assertEqual(judge_result({"status": "success", "bars_saved": 0})[0], "warning")
        self.assertEqual(judge_result({"status": "success", "observations_saved": 31})[0], "success")

    def test_a_legitimate_skip_is_not_a_warning(self):
        """Markets being shut is not a fault."""
        from core.task_gate import judge_result
        self.assertEqual(
            judge_result({"status": "skipped", "reason": "markets_closed"})[0], "success")

    def test_a_task_with_no_counts_keeps_the_benefit_of_the_doubt(self):
        """This must not turn unrelated healthy tasks red."""
        from core.task_gate import judge_result
        self.assertEqual(judge_result({"status": "success"})[0], "success")
        self.assertEqual(judge_result("not a dict")[0], "success")


class ForexBudgetTests(TestCase):
    """Alpha Vantage's free tier is 25 requests a day, and the key was never
    even set — which used to mean forex had no quote path at all: bars,
    signals, an enabled bot, and no mark to measure a stop against. The task
    now covers every pair keylessly through yfinance, and the paid budget is
    only ever charged for requests that actually went out."""

    def setUp(self):
        self._forget_budget()

    def tearDown(self):
        # A spent allowance must not leak into whatever test runs next — but
        # only THIS key is deleted: with a real Redis behind the cache,
        # cache.clear() is FLUSHDB on the db that also carries the Celery
        # broker and the channel layer.
        self._forget_budget()

    def _forget_budget(self):
        from django.core.cache import cache
        from market_data.tasks import _budget_key
        cache.delete(_budget_key("alpha_vantage"))

    def _fake_yf(self, price=1.0912):
        from unittest.mock import MagicMock
        fake = MagicMock()
        fake.Ticker.return_value.info = {
            "regularMarketPrice": price,
            "regularMarketChangePercent": 0.12,
        }
        return fake

    def test_no_key_charges_nothing_and_yfinance_covers_the_universe(self):
        from unittest.mock import patch
        from instruments.models import Instrument
        Instrument.objects.get_or_create(
            symbol="EURUSD", defaults={"name": "EURUSD", "asset_class": "forex"})
        fake = self._fake_yf()
        with patch("market_data.tasks._record_api_call") as charged, \
             patch("market_data.adapters.alpha_vantage.API_KEY", ""), \
             patch("core.market_calendar.is_forex_open", return_value=True), \
             patch.dict("sys.modules", {"yfinance": fake}):
            from market_data.tasks import fetch_forex_quotes
            result = fetch_forex_quotes.__wrapped__.__wrapped__()
        charged.assert_not_called()
        self.assertGreaterEqual(result["fetched"], 1)
        self.assertEqual(result["av_used"], 0)
        # A covered universe is healthy, not a 'not configured' warning.
        self.assertNotIn("skipped", result)
        # The pair went out in Yahoo's spelling, or the empty frame would
        # have read as 'no history available'.
        fake.Ticker.assert_any_call("EURUSD=X")
        from market_data.models import LiveQuote
        self.assertEqual(
            LiveQuote.objects.get(instrument__symbol="EURUSD").source,
            "yfinance")

    def test_the_unconfigured_case_is_not_dressed_as_an_exhausted_quota(self):
        from unittest.mock import patch
        with patch("market_data.adapters.alpha_vantage.API_KEY", ""), \
             patch("core.market_calendar.is_forex_open", return_value=True), \
             patch.dict("sys.modules", {"yfinance": self._fake_yf()}):
            from market_data.tasks import fetch_forex_quotes
            result = fetch_forex_quotes.__wrapped__.__wrapped__()
        self.assertNotIn("budget", str(result.get("note", "")).lower())
        self.assertIn("ALPHA_VANTAGE_API_KEY", result["note"])

    def test_a_spent_budget_no_longer_silences_forex_marks(self):
        """The budget caps what Alpha Vantage is asked; it must not cap the
        keyless fallback that keeps the marks alive."""
        from unittest.mock import patch
        from instruments.models import Instrument
        from market_data.tasks import _record_api_call, AV_DAILY_LIMIT
        Instrument.objects.get_or_create(
            symbol="EURUSD", defaults={"name": "EURUSD", "asset_class": "forex"})
        _record_api_call("alpha_vantage", AV_DAILY_LIMIT)
        fake = self._fake_yf()
        with patch("market_data.adapters.alpha_vantage.API_KEY", "a-key"), \
             patch("core.market_calendar.is_forex_open", return_value=True), \
             patch.dict("sys.modules", {"yfinance": fake}):
            from market_data.tasks import fetch_forex_quotes
            result = fetch_forex_quotes.__wrapped__.__wrapped__()
        self.assertEqual(result["av_used"], 0)
        self.assertGreaterEqual(result["fetched"], 1)


class QuotePrecedenceTests(TestCase):
    """LiveQuote is one row per instrument with a single source column, so the
    last writer wins unless something stops it. market_data/quotes.py exists to
    stop it — and the commodity poller was the one feed writing the row
    directly, bypassing the rule entirely."""

    def setUp(self):
        from instruments.models import Instrument
        self.inst, _ = Instrument.objects.get_or_create(
            symbol="XAUUSD", defaults={"name": "Gold", "asset_class": "commodity"})

    def test_a_delayed_feed_cannot_overwrite_a_live_broker_tick(self):
        """yfinance is fifteen minutes delayed for most listings and is the
        lowest-priority source on the platform."""
        from decimal import Decimal
        from market_data.models import LiveQuote
        from market_data.quotes import write_quote

        LiveQuote.objects.update_or_create(
            instrument=self.inst,
            defaults={"last": Decimal("2400"), "source": "ibkr"})
        wrote = write_quote("XAUUSD", last=2350, source="yfinance")
        self.assertFalse(wrote, "a delayed print overwrote a broker tick")
        self.assertEqual(LiveQuote.objects.get(instrument=self.inst).source, "ibkr")

    def test_a_source_may_always_refresh_itself(self):
        from decimal import Decimal
        from market_data.models import LiveQuote
        from market_data.quotes import write_quote
        LiveQuote.objects.update_or_create(
            instrument=self.inst,
            defaults={"last": Decimal("2400"), "source": "yfinance"})
        self.assertTrue(write_quote("XAUUSD", last=2410, source="yfinance"))
        self.assertEqual(
            LiveQuote.objects.get(instrument=self.inst).last, Decimal("2410"))

    def test_the_commodity_poller_goes_through_the_one_writer(self):
        """Asserted on the source, because the alternative is mocking yfinance
        to prove a negative about a write that should no longer exist."""
        import inspect
        from market_data import tasks
        src = inspect.getsource(tasks.fetch_commodity_quotes)
        self.assertIn("write_quote", src)
        self.assertNotIn("LiveQuote.objects.update_or_create", src)


class AskSauronLaunchTests(TestCase):
    """Anything on the platform can hand Sauron a subject.

    Before this, asking about a signal meant opening the panel and retyping
    which instrument and which rule you meant — so nobody did it from the
    place where the question occurred to them."""

    def setUp(self):
        self.user = User.objects.create_user(username="ask_u", password="x")
        self.client.force_login(self.user)
        from instruments.models import Instrument
        from signals.models import Signal
        inst, _ = Instrument.objects.get_or_create(
            symbol="USDJPY", defaults={"name": "Yen", "asset_class": "forex"})
        Signal.objects.create(
            instrument=inst, signal_type="technical", direction="bullish",
            urgency="high", title="USDJPY long", rule_name="golden_cross",
            score=0.7, is_active=True, price_at_signal=150)
        self.body = self.client.get(
            "/signals/", HTTP_HOST="127.0.0.1").content.decode("utf-8", "replace")

    def test_a_signal_row_can_hand_itself_to_sauron(self):
        self.assertIn("data-ask-sauron", self.body)
        self.assertIn("USDJPY", self.body)

    def test_the_subject_names_the_direction_and_the_rule(self):
        """'What do you think about USDJPY' is a worse question than 'what do
        you make of the BULLISH USDJPY (golden_cross) signal'."""
        import re
        subjects = re.findall(r'data-ask-sauron="([^"]+)"', self.body)
        self.assertTrue(any("USDJPY" in s and "golden_cross" in s for s in subjects),
                        f"no subject carried the rule: {subjects[:4]}")

    def test_the_launcher_is_wired_to_a_handler(self):
        self.assertIn("askSauronAbout", self.body)
        self.assertIn("data-ask-kind", self.body)

    def test_the_subject_is_carried_as_a_chip_not_baked_into_the_text(self):
        """The operator rewrites the question; the subject has to survive
        that."""
        self.assertIn('id="seCtx"', self.body)
        self.assertIn("askContext", self.body)

    def test_the_subject_is_appended_to_what_is_actually_sent(self):
        """A follow-up like 'why is it firing?' reaches the agent with no idea
        what 'it' is unless the subject travels with it."""
        self.assertIn("(About: ", self.body)

    def test_each_kind_offers_its_own_follow_ups(self):
        for kind in ("signal", "instrument", "rule", "bot"):
            self.assertIn(kind + ":", self.body, f"{kind} has no suggestion set")


class ChatMessageToolTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="cmt_u", password="x")
        self.client.force_login(self.user)
        self.body = self.client.get(
            "/signals/", HTTP_HOST="127.0.0.1").content.decode("utf-8", "replace")

    def test_an_answer_can_be_retried(self):
        self.assertIn("data-se-regen", self.body)
        self.assertIn("lastQuestion", self.body)

    def test_a_question_can_be_edited(self):
        self.assertIn("data-se-edit", self.body)

    def test_an_answer_that_lands_on_a_closed_panel_is_announced(self):
        """A pulsing orb says something happened. It does not say what."""
        self.assertIn("notifyAnswer", self.body)
        self.assertIn("sauron_answer", self.body)

    def test_the_preview_carries_the_start_of_the_answer(self):
        self.assertIn("preview", self.body)
        self.assertIn("text.slice(0, 180)", self.body)

    def test_focus_is_not_stolen_into_a_closed_panel(self):
        """Focusing a textarea inside a shut panel silently swallows every
        global keyboard shortcut."""
        self.assertIn("if (panel.classList.contains('open')) input.focus();", self.body)


class EyeFabAffordanceTests(TestCase):
    """The orb was labelled SEND while also being the open/close control, so
    two things on screen looked like the way to submit and only one was."""

    def setUp(self):
        self.user = User.objects.create_user(username="fab_u", password="x")
        self.client.force_login(self.user)
        self.body = self.client.get(
            "/signals/", HTTP_HOST="127.0.0.1").content.decode("utf-8", "replace")
        self.css = _read("static", "css", "sv-overlay.css")

    def test_the_orb_no_longer_claims_to_send(self):
        self.assertIn('class="se-fab-label">ASK', self.body)
        self.assertNotIn('class="se-fab-label">SEND', self.body)

    def test_it_grows_and_shows_corner_marks_on_hover(self):
        self.assertIn("se-fab-corners", self.body)
        self.assertIn(".se-eye-fab:hover { transform: scale(", self.css)
        self.assertIn(".se-eye-fab:hover .se-fab-corner", self.css)

    def test_once_open_the_orb_offers_close_instead_of_corners(self):
        self.assertIn("se-fab-close", self.body)
        self.assertIn(".se-eye-fab.open:hover .se-fab-close", self.css)
        self.assertIn(".se-eye-fab.open:hover .se-fab-corner { opacity: 0; }", self.css)

    def test_an_unread_answer_is_marked_on_the_orb(self):
        self.assertIn(".se-eye-fab.answered::after", self.css)

    def test_the_send_control_sits_beside_the_input(self):
        """Structural: the textarea and the send button share one flex row,
        and the button follows the textarea."""
        i = self.body.index('id="seChatInput"')
        j = self.body.index('id="seChatSend"')
        self.assertLess(i, j, "the send button is not after the input")
        self.assertIn('title="Send — Enter"', self.body)

    def test_the_hover_growth_respects_reduced_motion(self):
        self.assertIn("prefers-reduced-motion", self.css)
        self.assertIn(".se-eye-fab:hover { transform: none; }", self.css)
