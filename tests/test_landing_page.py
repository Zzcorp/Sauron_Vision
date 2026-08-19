"""Smoke test for the public landing page (templates/landing/the_wall.html).

Anonymous + authenticated paths both render 200 and carry the content
markers for what the platform actually does today.

Two rules the wall has to keep, and which the assertions below pin:

  1. Every number on the page is a server-side aggregate COUNT handed
     over in the ``wall`` context. Nothing is hardcoded into the markup,
     so the page cannot go stale behind the platform again.
  2. Nothing on the page is a market quote. The ticker and the hero
     particles used to scroll invented prices; they now scroll the
     platform's own counters, and the old literals must never come back.
"""
import re

from django.test import TestCase


# The exact fabricated quotes the wall used to ship. If any of these
# reappears, someone has put invented market data back on a public page.
FABRICATED_PRICES = [
    "5,842.31", "20,614.50", "43,729.80", "97,234.00", "3,521.40",
    "2,714.30", "1.0847", "154.32", "71.42", "106.14",
    "227.48", "141.20", "352.80",
    "+0.67%", "+2.41%", "-3.21%", "-0.89%",
]

# Every integer the shared wall context promises, all safe for a public
# page: aggregate counts only, never a symbol, price, P&L or account.
WALL_KEYS = [
    "tests_green", "asset_classes", "broker_adapters", "evaluators",
    "instruments", "signals_graded", "trades_graded", "strategies",
    "chain_length", "news_24h", "bots",
]


class LandingPageSmokeTests(TestCase):
    def test_anonymous_user_renders_200(self):
        r = self.client.get("/wall/")
        # Authenticated users get redirected to dashboard; anon sees the wall.
        self.assertEqual(r.status_code, 200)

    def test_landing_carries_new_section_anchors(self):
        r = self.client.get("/wall/")
        body = r.content.decode("utf-8", errors="ignore")
        # Sections added as the platform grew.
        self.assertIn('id="operations"', body)
        self.assertIn('id="fleet"', body)
        self.assertIn('id="evolution"', body)
        self.assertIn('id="mind"', body)
        self.assertIn('id="research"', body)
        # Earlier sections we added.
        self.assertIn('id="pipeline"', body)
        self.assertIn('id="demo"', body)
        self.assertIn('id="brokers"', body)
        self.assertIn('id="trust"', body)
        # Existing platform sections preserved.
        self.assertIn('id="platform"', body)
        self.assertIn('id="technology"', body)

    def test_landing_carries_new_capability_copy(self):
        r = self.client.get("/wall/")
        body = r.content.decode("utf-8", errors="ignore")
        # Hero claim — the count is rendered from context, never literal.
        self.assertIn("tests green", body)
        self.assertNotIn("667 tests green", body)
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
        # Animation classes from the earlier refresh.
        self.assertIn("pipe-flow", body)
        self.assertIn("hash-shimmer", body)
        self.assertIn("tick-strip", body)
        self.assertIn("theme-bar-row", body)
        self.assertIn("broker-tile", body)
        # @keyframes the page still owns.
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
        """Pupil group + JS cursor-tracking handler present."""
        r = self.client.get("/wall/")
        body = r.content.decode("utf-8", errors="ignore")
        self.assertIn('id="wallPupilGroup"', body)
        self.assertIn("PUPIL_RANGE_X", body)  # tracking constant
        self.assertIn("prefers-reduced-motion", body)  # accessibility

    def test_orchestrator_demo_section_present(self):
        """Demo with sliders + presets + exposure bars + log."""
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
        # The redesigned SVGs all set linecap="square" + linejoin="miter".
        # At least 10 of those should be present (1 buffer for any other svg).
        self.assertGreaterEqual(body.count('stroke-linecap="square"'), 10)
        self.assertGreaterEqual(body.count('stroke-linejoin="miter"'), 10)
        # Hexagram (6-pointed star) appears in orchestrator + LEARN nodes
        self.assertIn('points="12,2.5 20.5,17.5 3.5,17.5"', body)  # orchestrator
        self.assertIn('points="12,3 20,17 4,17"', body)  # LEARN hexagram


class WallCountersAreServerSideTests(TestCase):
    """The wall's numbers are aggregate counts from the view, not literals
    baked into the template. This is what stopped '667 tests green' from
    sitting on a public page for a thousand commits."""

    def setUp(self):
        self.response = self.client.get("/wall/")
        self.body = self.response.content.decode("utf-8", errors="ignore")

    def test_view_supplies_the_whole_wall_contract(self):
        """Both halves of the page — markup and ticker JS — read these."""
        wall = self.response.context["wall"]
        for key in WALL_KEYS:
            self.assertIn(key, wall, f"wall context is missing {key!r}")
            self.assertIsInstance(
                wall[key], int,
                f"wall.{key} must be an aggregate count, got {wall[key]!r}")
            self.assertGreaterEqual(wall[key], 0, f"wall.{key} went negative")

    def test_tests_green_is_rendered_from_the_context(self):
        wall = self.response.context["wall"]
        self.assertIn(f'{wall["tests_green"]} tests green', self.body)
        self.assertIn(f'data-target="{wall["tests_green"]}"', self.body)

    def test_stats_bar_targets_all_come_from_the_context(self):
        wall = self.response.context["wall"]
        for key in ("asset_classes", "broker_adapters", "evaluators",
                    "tests_green"):
            self.assertIn(f'data-target="{wall[key]}"', self.body,
                          f"stats bar is not reading wall.{key}")
        # Every count-up target must be a number — an empty one means a
        # context key was dropped and the counter would render NaN.
        targets = re.findall(r'data-target="([^"]*)"', self.body)
        self.assertTrue(targets)
        for t in targets:
            self.assertRegex(t, r"^\d+$")

    def test_the_ticker_scrolls_counters_not_quotes(self):
        # The ticker payload is built from the same context object.
        self.assertIn("var WALL = {", self.body)
        self.assertIn("SIGNALS GRADED", self.body)
        self.assertIn("CHAIN LENGTH", self.body)
        self.assertIn("STRATEGIES", self.body)
        self.assertIn("TESTS GREEN", self.body)
        self.assertIn("wallTickerTrack", self.body)

    def test_no_fabricated_market_data_anywhere_on_the_page(self):
        for quote in FABRICATED_PRICES:
            self.assertNotIn(quote, self.body,
                             f"invented market data back on the wall: {quote}")
        # The old machinery that generated and drifted them is gone too.
        self.assertNotIn("var prices", self.body)
        self.assertNotIn("p.sym", self.body)
        self.assertNotIn('ticker-chg down', self.body)
        # ...and the particles now carry platform counters instead.
        self.assertIn("particleTags", self.body)

    def test_public_copy_carries_no_internal_phase_numbers(self):
        """The wall says what the platform does, not which sprint built it."""
        self.assertNotIn("Phase-9", self.body)
        self.assertNotIn("PHASE 28", self.body)
        self.assertNotIn("Phase-trio", self.body)


class WallGrewWithThePlatformTests(TestCase):
    """The sections added once the platform outgrew the original wall.
    Each one is in the page's own language: an anchor, reveal classes and
    the existing card/split idiom."""

    def setUp(self):
        self.body = self.client.get("/wall/").content.decode(
            "utf-8", errors="ignore")

    def test_operations_section_shows_the_cockpit(self):
        self.assertIn('id="operations"', self.body)
        self.assertIn("ops-frame", self.body)
        # One-click execution straight off a signal.
        self.assertIn("TAKE TRADE", self.body)
        # Live status pill + exchange sessions + the headband.
        self.assertIn("sess-pill", self.body)
        self.assertIn("LONDON", self.body)
        self.assertIn("NEW YORK", self.body)
        self.assertIn("TOKYO", self.body)
        self.assertIn("SYDNEY", self.body)
        self.assertIn("ops-band", self.body)
        # Notifications inbox.
        self.assertIn("ops-inbox-row", self.body)

    def test_fleet_section_shows_bots_and_the_promotion_ladder(self):
        self.assertIn('id="fleet"', self.body)
        self.assertIn("ladder", self.body)
        for rung in ("RESEARCH", "PAPER", "LIVE · SMALL", "LIVE · FULL"):
            self.assertIn(rung, self.body)
        self.assertIn("FORENSICS", self.body)
        self.assertIn("BACKTEST", self.body)

    def test_evolution_section_states_what_evolution_does(self):
        self.assertIn('id="evolution"', self.body)
        self.assertIn("Adaptive cadence", self.body)
        self.assertIn("Walk-forward", self.body)
        self.assertIn("MUTATION LINEAGE", self.body)

    def test_mind_section_covers_the_brain_layer(self):
        self.assertIn('id="mind"', self.body)
        self.assertIn("Brain Synthesis", self.body)
        self.assertIn("Knowledge Graph", self.body)
        self.assertIn("Hypothesis Market", self.body)
        self.assertIn("The Critic", self.body)
        self.assertIn("Consolidation", self.body)

    def test_research_section_is_the_ask_sauron_chat(self):
        self.assertIn('id="research"', self.body)
        self.assertIn("ASK_SAURON", self.body)
        self.assertIn("READ-ONLY", self.body)
        self.assertIn("briefing", self.body.lower())
        self.assertIn("Earnings reviews", self.body)

    def test_trust_section_now_carries_the_security_story(self):
        self.assertIn('id="trust"', self.body)
        # The hash chain that was already there.
        self.assertIn("AUDIT CHAIN", self.body)
        # ...plus the three PIN gates that now exist.
        self.assertIn("Second Gate", self.body)
        self.assertIn("PIN on Login", self.body)
        self.assertIn("PIN to Go Live", self.body)
        self.assertIn("Auto-Lock", self.body)
        self.assertIn("kill switch", self.body)

    def test_new_sections_reuse_the_reveal_and_motion_guards(self):
        """New markup animates through the same system as the old, and the
        added motion honours prefers-reduced-motion."""
        for anchor, marker in (
            ('id="operations"', "reveal-scale"),
            ('id="fleet"', "reveal-scale"),
            ('id="evolution"', "reveal-left"),
            ('id="research"', "reveal-right"),
        ):
            self.assertIn(anchor, self.body)
            self.assertIn(marker, self.body)
        self.assertIn("@media (prefers-reduced-motion: reduce)", self.body)

    def test_the_new_anchors_are_reachable_from_the_nav(self):
        self.assertIn('href="#operations"', self.body)
        self.assertIn('href="#mind"', self.body)
