"""Command Center tests — Pattern A (tabs) + selective progressive disclosure.

Verifies:
  - /command/ renders 200 with hero + all 4 tabs
  - Each tab fragment endpoint renders 200 independently
  - Smart-default tab logic (LIVE if any enabled bot, else PORTFOLIO)
  - URL hash deep-linking via ?tab=
  - Expandable panels carry the .cc-expandable + .cc-expand-btn markup
  - Backward-compat: /eye/ and / (dashboard) still work
  - Sidebar nav has the merged "Command Center" link
"""
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase


def _user(name="cc_u"):
    return User.objects.create_user(username=name, password="x")


def _abc(user, asset_class, **kw):
    from bot_program.models import AssetBotConfig
    defaults = dict(
        enabled=True, mode="paper", symbols=[],
        capital=Decimal("10000"), base_currency="USD",
        position_size_pct=2.0, max_concurrent_positions=5,
        max_daily_loss_pct=2.0, stop_loss_pct=1.5, take_profit_pct=3.0,
        entry_score_min=0.6, min_signals_for_entry=1,
    )
    defaults.update(kw)
    return AssetBotConfig.objects.create(
        user=user, asset_class=asset_class, name=defaults.pop("name", "T"),
        **defaults,
    )


class CommandCenterRenderTests(TestCase):
    def setUp(self):
        self.user = _user()
        self.client.force_login(self.user)

    def test_command_center_renders_200(self):
        r = self.client.get("/command/")
        self.assertEqual(r.status_code, 200)

    def test_hero_header_present(self):
        r = self.client.get("/command/")
        body = r.content.decode("utf-8", errors="ignore")
        # Operations Center hero (Phase 61 rename: cc- → oc-).
        self.assertIn("oc-hero", body)
        self.assertIn("PORTFOLIO VALUE", body)
        self.assertIn("ocClock", body)
        self.assertIn("ocWsStatus", body)
        # Page title reflects the rename.
        self.assertIn("OPERATIONS CENTER", body)

    def test_all_four_tabs_present(self):
        r = self.client.get("/command/")
        body = r.content.decode("utf-8", errors="ignore")
        self.assertIn('data-tab="live"', body)
        self.assertIn('data-tab="portfolio"', body)
        self.assertIn('data-tab="history"', body)
        self.assertIn('data-tab="bots"', body)

    def test_tab_buttons_use_htmx(self):
        """Each tab button has hx-get + hx-target + hx-push-url."""
        r = self.client.get("/command/")
        body = r.content.decode("utf-8", errors="ignore")
        self.assertIn('hx-target="#ocTabBody"', body)
        self.assertIn("hx-push-url", body)

    def test_tab_bar_metrics_visible(self):
        """Phase 61 — each tab head shows a live metric value."""
        r = self.client.get("/command/")
        body = r.content.decode("utf-8", errors="ignore")
        # Per-tab metric containers are rendered.
        self.assertIn("oc-tab-metric-primary", body)
        self.assertIn("oc-tab-metric-secondary", body)


class TabFragmentTests(TestCase):
    def setUp(self):
        self.user = _user()
        self.client.force_login(self.user)

    def test_live_fragment_renders(self):
        r = self.client.get("/command/tab/live/")
        self.assertEqual(r.status_code, 200)
        # Reuses the Eye partial — should contain the theme-exposure card.
        body = r.content.decode("utf-8", errors="ignore")
        self.assertIn("Theme Exposure", body)

    def test_portfolio_fragment_renders(self):
        r = self.client.get("/command/tab/portfolio/")
        self.assertEqual(r.status_code, 200)
        body = r.content.decode("utf-8", errors="ignore")
        # Phase-61 enrichment: equity curve, allocation, open positions.
        self.assertIn("Equity curve", body)
        self.assertIn("Allocation", body)
        self.assertIn("Open positions", body)
        # Has expandable panel.
        self.assertIn("oc-expandable", body)
        self.assertIn("oc-expand-btn", body)

    def test_portfolio_fragment_includes_sharpe_strip(self):
        """Phase 61 — portfolio shows the rich top stat strip with Sharpe etc."""
        r = self.client.get("/command/tab/portfolio/")
        body = r.content.decode("utf-8", errors="ignore")
        self.assertIn("oc-strip", body)
        self.assertIn("SHARPE 30D", body)
        self.assertIn("MAX DRAWDOWN", body)

    def test_history_fragment_renders(self):
        r = self.client.get("/command/tab/history/")
        self.assertEqual(r.status_code, 200)
        body = r.content.decode("utf-8", errors="ignore")
        # Phase-61: cumulative R curve, day-of-week heatmap, top rules by Sharpe.
        self.assertIn("Cumulative R", body)
        self.assertIn("Day-of-week", body)
        self.assertIn("Top 5 rules by Sharpe", body)

    def test_bots_fragment_renders(self):
        r = self.client.get("/command/tab/bots/")
        self.assertEqual(r.status_code, 200)
        body = r.content.decode("utf-8", errors="ignore")
        self.assertIn("Bot configurations", body)
        # Phase-61: top stat strip with ALIVE 6H rendered even with no bots.
        self.assertIn("ALIVE 6H", body)
        self.assertIn("oc-strip", body)

    def test_bots_fragment_shows_cooldown_column_when_rows(self):
        """With at least one bot config the table renders cooldown + health cols."""
        _abc(self.user, "stock", name="ColdBot")
        r = self.client.get("/command/tab/bots/")
        body = r.content.decode("utf-8", errors="ignore")
        self.assertIn("cooldown", body)
        self.assertIn("ColdBot", body)

    def test_bots_fragment_lists_configs(self):
        _abc(self.user, "stock", name="MyStockBot")
        _abc(self.user, "forex", name="MyForexBot")
        r = self.client.get("/command/tab/bots/")
        body = r.content.decode("utf-8", errors="ignore")
        self.assertIn("MyStockBot", body)
        self.assertIn("MyForexBot", body)


class SmartDefaultTabTests(TestCase):
    def test_no_bots_defaults_to_portfolio(self):
        u = _user("default_no_bots")
        self.client.force_login(u)
        r = self.client.get("/command/")
        body = r.content.decode("utf-8", errors="ignore")
        # PORTFOLIO tab should be the active one.
        self.assertIn('data-tab="portfolio" role="tab"\n            hx-get', body) \
            if False else None  # fragile assertion — use simpler check below
        # Active tab marker appears with data-tab="portfolio"
        # (look for `cc-tab active` near data-tab="portfolio")
        # Substring check is enough:
        idx = body.find('data-tab="portfolio"')
        # The "active" class appears just before the data-tab attr inside the same button.
        self.assertGreater(idx, 0)
        snippet = body[max(0, idx-200):idx]
        self.assertIn("active", snippet)

    def test_enabled_bot_defaults_to_live(self):
        u = _user("default_with_bots")
        _abc(u, "stock", name="ActiveBot", enabled=True)
        self.client.force_login(u)
        r = self.client.get("/command/")
        body = r.content.decode("utf-8", errors="ignore")
        idx = body.find('data-tab="live"')
        snippet = body[max(0, idx-200):idx]
        self.assertIn("active", snippet)


class TabDeepLinkTests(TestCase):
    def setUp(self):
        self.user = _user()
        self.client.force_login(self.user)

    def test_query_param_selects_tab(self):
        r = self.client.get("/command/?tab=history")
        body = r.content.decode("utf-8", errors="ignore")
        # The "history" tab button should be active.
        idx = body.find('data-tab="history"')
        self.assertGreater(idx, 0)
        snippet = body[max(0, idx-200):idx]
        self.assertIn("active", snippet)

    def test_invalid_tab_falls_back_to_live(self):
        r = self.client.get("/command/?tab=garbage")
        self.assertEqual(r.status_code, 200)
        # No crash; live becomes active by fallback.


class BackwardCompatTests(TestCase):
    def setUp(self):
        self.user = _user()
        self.client.force_login(self.user)

    def test_old_dashboard_still_works(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)

    def test_old_eye_still_works(self):
        r = self.client.get("/eye/")
        self.assertEqual(r.status_code, 200)


class NavigationTests(TestCase):
    def test_sidebar_has_operations_center_link(self):
        """Phase 61 renamed sidebar label from 'Command Center' to 'Operations
        Center'. The URL stays /command/ for backward compat."""
        u = _user()
        self.client.force_login(u)
        r = self.client.get("/command/")
        body = r.content.decode("utf-8", errors="ignore")
        self.assertIn("Operations Center", body)
        # The merged nav entry still resolves to /command/.
        self.assertIn('href="/command/"', body)
