"""Phase-29 mobile responsiveness tests.

Pure CSS work has limited testability — we can't simulate viewport size or
visually validate. What we CAN check:
  1. Pages still render 200 (no regression from CSS changes)
  2. The new responsive CSS block is present in base.html
  3. The mobile menu button + sidebar overlay are rendered
  4. Inline grids in dashboards have the @media catch-all rule available

Run with:  python manage.py test tests.test_phase29_mobile
"""
from django.contrib.auth.models import User
from django.test import TestCase, Client


def _user(name="m_u"):
    return User.objects.create_user(username=name, password="x")


class MobileCSSPresenceTests(TestCase):
    """Verify the responsive CSS block landed in base.html and reaches each page."""

    def setUp(self):
        self.user = _user()
        self.client.force_login(self.user)

    # The design system now lives in a cacheable static file rather than
    # ~2,900 lines of CSS inlined into every page, so "the page carries the
    # responsive rules" means it links the stylesheet AND that stylesheet
    # contains them.
    @classmethod
    def _stylesheet(cls):
        from pathlib import Path
        from django.conf import settings
        return (Path(settings.BASE_DIR) / "static" / "css" / "sauron.css"
                ).read_text(encoding="utf-8")

    def _assert_responsive_markers(self, response):
        """Check the page reaches the Phase-29 responsive rules."""
        body = response.content.decode("utf-8", errors="ignore")
        self.assertIn("css/sauron.css", body)
        # Markup-side hooks still render inline.
        self.assertIn("mobile-menu-btn", body)

        css = self._stylesheet()
        # Catch-all inline-grid override.
        self.assertIn('[style*="grid-template-columns"]', css)
        # Table horizontal-scroll rule.
        self.assertIn(".table-wrapper", css)
        # Sidebar mobile-open class.
        self.assertIn("mobile-open", css)
        # And the rules are actually inside a mobile media query.
        self.assertIn("max-width: 768px", css)

    def test_eye_dashboard_carries_responsive_css(self):
        r = self.client.get("/eye/")
        self.assertEqual(r.status_code, 200)
        self._assert_responsive_markers(r)

    def test_profile_carries_responsive_css(self):
        r = self.client.get("/profile/")
        self.assertEqual(r.status_code, 200)
        self._assert_responsive_markers(r)

    def test_tax_lots_carries_responsive_css(self):
        r = self.client.get("/tax-lots/")
        self.assertEqual(r.status_code, 200)
        self._assert_responsive_markers(r)

    def test_bot_backtest_carries_responsive_css(self):
        r = self.client.get("/bot-backtest/")
        self.assertEqual(r.status_code, 200)
        self._assert_responsive_markers(r)

    def test_eye_gate_events_carries_responsive_css(self):
        r = self.client.get("/eye/gate-events/")
        self.assertEqual(r.status_code, 200)
        self._assert_responsive_markers(r)


class MobileMenuButtonTests(TestCase):
    """Verify the hamburger button + JS toggle wiring exists."""

    def setUp(self):
        self.user = _user("m_btn_u")
        self.client.force_login(self.user)

    def test_hamburger_button_present(self):
        r = self.client.get("/eye/")
        body = r.content.decode("utf-8", errors="ignore")
        self.assertIn('id="mobileMenuBtn"', body)
        self.assertIn('toggleMobileSidebar', body)

    def test_sidebar_overlay_present(self):
        r = self.client.get("/eye/")
        body = r.content.decode("utf-8", errors="ignore")
        self.assertIn('id="sidebarOverlay"', body)


class TabletBreakpointTests(TestCase):
    """The Phase-29 block adds an explicit tablet breakpoint between 769px and
    1024px. Just check it's wired into the rendered output."""

    def setUp(self):
        self.user = _user("m_tb_u")
        self.client.force_login(self.user)

    def test_tablet_media_query_present(self):
        r = self.client.get("/eye/")
        body = r.content.decode("utf-8", errors="ignore")
        self.assertIn("css/sauron.css", body)
        # The rules themselves now live in the extracted stylesheet.
        css = MobileCSSPresenceTests._stylesheet()
        self.assertIn("min-width: 769px", css)
        self.assertIn("max-width: 1024px", css)
