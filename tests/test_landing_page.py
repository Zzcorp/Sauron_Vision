"""Smoke test for the public landing page (templates/landing/the_wall.html).

Anonymous + authenticated paths both render 200 and contain the new
content markers added in the refresh (Phases 13-33 capabilities).
"""
from django.test import TestCase


class LandingPageSmokeTests(TestCase):
    def test_anonymous_user_renders_200(self):
        r = self.client.get("/wall/")
        # Authenticated users get redirected to dashboard; anon sees the wall.
        self.assertEqual(r.status_code, 200)

    def test_landing_carries_new_section_anchors(self):
        r = self.client.get("/wall/")
        body = r.content.decode("utf-8", errors="ignore")
        # Phase-13-33 sections we added.
        self.assertIn('id="pipeline"', body)
        self.assertIn('id="brokers"', body)
        self.assertIn('id="trust"', body)
        # Existing platform sections preserved.
        self.assertIn('id="platform"', body)
        self.assertIn('id="technology"', body)

    def test_landing_carries_new_capability_copy(self):
        r = self.client.get("/wall/")
        body = r.content.decode("utf-8", errors="ignore")
        # Hero claim
        self.assertIn("667 tests green", body)
        # Sauron's Eye dashboard card
        self.assertIn("Sauron's Eye", body)
        # Cross-asset orchestrator card
        self.assertIn("Cross-Asset Orchestrator", body)
        # Audit chain section
        self.assertIn("AUDIT CHAIN", body)
        # Pipeline labels
        self.assertIn("RISK GATE", body)
        self.assertIn("EXECUTE", body)
        self.assertIn("LEARN", body)
        # Broker tiles
        self.assertIn("BINANCE", body)
        self.assertIn("ALPACA", body)
        self.assertIn("OANDA", body)
        self.assertIn("IBKR", body)
        # Tech stack additions
        self.assertIn("Channels", body)
        self.assertIn("Sentry SDK", body)
        self.assertIn("ib_insync", body)

    def test_landing_keeps_animation_classes(self):
        """Animation framework still wired in — reveal classes + count-up + ticker."""
        r = self.client.get("/wall/")
        body = r.content.decode("utf-8", errors="ignore")
        # Substring checks (more tolerant of attribute-order normalisation).
        self.assertIn("reveal-left", body)
        self.assertIn("reveal-right", body)
        self.assertIn("reveal-scale", body)
        self.assertIn("count-up", body)
        self.assertIn("wallTickerTrack", body)
        # New animation classes added in this refresh.
        self.assertIn("pipe-flow", body)
        self.assertIn("hash-shimmer", body)
        self.assertIn("tick-strip", body)
        self.assertIn("theme-bar-row", body)
        self.assertIn("broker-tile", body)
        # New @keyframes added.
        self.assertIn("@keyframes pipeFlow", body)
        self.assertIn("@keyframes hashShimmer", body)
        self.assertIn("@keyframes brokerOrbit", body)

    def test_login_overlay_present(self):
        """The Wall ships an inline login overlay (no separate page jump)."""
        r = self.client.get("/wall/")
        body = r.content.decode("utf-8", errors="ignore")
        self.assertIn("loginOverlay", body)
        self.assertIn('id="loginForm"', body)

    def test_cursor_tracking_pupil_wired(self):
        """Phase-trio: pupil group + JS cursor-tracking handler present."""
        r = self.client.get("/wall/")
        body = r.content.decode("utf-8", errors="ignore")
        self.assertIn('id="wallPupilGroup"', body)
        self.assertIn("PUPIL_RANGE_X", body)  # tracking constant
        self.assertIn("prefers-reduced-motion", body)  # accessibility

    def test_orchestrator_demo_section_present(self):
        """Phase-trio v2: demo with sliders + presets + exposure bars + log."""
        r = self.client.get("/wall/")
        body = r.content.decode("utf-8", errors="ignore")
        # Section structure
        self.assertIn('id="demo"', body)
        self.assertIn('id="demoStage"', body)
        self.assertIn('id="demoUsd"', body)
        self.assertIn('id="demoEq"', body)
        self.assertIn('id="demoSec"', body)
        # v2: live exposure bars on the left
        self.assertIn('id="expUsdFill"', body)
        self.assertIn('id="expEqFill"', body)
        self.assertIn('id="expSecFill"', body)
        # v2: persistent decision log on the right
        self.assertIn('id="demoLogList"', body)
        self.assertIn("Decision Log", body)
        # v2: scenario preset buttons (5)
        self.assertIn('data-preset="random"', body)
        self.assertIn('data-preset="usd-bull"', body)
        self.assertIn('data-preset="eur-cross"', body)
        self.assertIn('data-preset="tech-rotate"', body)
        self.assertIn('data-preset="balanced"', body)
        # Hover-fix: dots no longer have pointer-events:none blocking interaction
        # (the v2 design uses persistent log rows instead of hover tooltips).
        self.assertIn("ORCHESTRATOR_GATE", body)
        self.assertIn("Touch the Gate", body)
        self.assertIn('href="#demo"', body)

    def test_platform_base_has_pupil_tracking(self):
        """The platform pages (base.html) also get the cursor-tracking pupil."""
        from django.contrib.auth.models import User
        u = User.objects.create_user(username="pupil_u", password="x")
        self.client.force_login(u)
        # Any logged-in page that extends base.html will do — try /eye/.
        r = self.client.get("/eye/")
        body = r.content.decode("utf-8", errors="ignore")
        self.assertIn('id="globePupilGroup"', body)
        # Tracking JS marker (range constant)
        self.assertIn("PUPIL_RANGE_X", body)

    def test_redesigned_icons_use_sigil_geometry(self):
        """Icons should use square line-caps + miter joins (Sauron sigil aesthetic),
        not the rounded Lucide-style. Spot-check the feature grid + pipeline."""
        r = self.client.get("/wall/")
        body = r.content.decode("utf-8", errors="ignore")
        # The 11 redesigned SVGs all set linecap="square" + linejoin="miter".
        # At least 10 of those should be present (1 buffer for any other svg).
        self.assertGreaterEqual(body.count('stroke-linecap="square"'), 10)
        self.assertGreaterEqual(body.count('stroke-linejoin="miter"'), 10)
        # Hexagram (6-pointed star) appears in orchestrator + LEARN nodes
        self.assertIn('points="12,2.5 20.5,17.5 3.5,17.5"', body)  # orchestrator
        self.assertIn('points="12,3 20,17 4,17"', body)  # LEARN hexagram
