"""The investor window — a read-only view that can never become a door.

An investor login sees ONE funded account's book and touches nothing.
The cage is a deny-by-default middleware: everything not explicitly
allowed redirects to the panel, so every route this platform ships next
year is investor-proof on arrival. These tests are the proof, and the
walk over sensitive routes is the most important part — a cage is only
as strong as the doors someone forgot to list.

Run with:  python manage.py test tests.test_investor_window
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

# The doors an investor must NEVER open — a sample across every kind of
# surface: pages, money APIs, admin, settings, the trade paths.
CAGED_ROUTES = [
    "/", "/positions/", "/portfolio/", "/setup/", "/signals/",
    "/admin-dashboard/", "/bot/", "/api/kill-switch/",
    "/api/nav-activity/", "/api/exchange-status/",
    "/instruments/", "/profile/", "/brain/", "/generated/",
    # The review's additions: the trade-execution doors, the Django
    # admin, the unlock API and the research spender — the gate fires
    # before URL resolution, so nonexistent ids still prove the cage.
    "/admin/", "/api/session/unlock/", "/research/ask/",
    "/instruments/BTCUSD/take-trade/", "/signals/1/take-trade/",
    "/bot/toggle/",
]


def _owner_with_book(username="fund_a"):
    from portfolio.models import PortfolioSnapshot
    from portfolio.services import get_or_create_default_portfolio
    owner = get_user_model().objects.create_user(username, password="x")
    pf = get_or_create_default_portfolio(user=owner)
    pf.current_value = Decimal("125000")
    pf.save()
    PortfolioSnapshot.objects.create(
        portfolio=pf, date="2026-08-20", total_value=Decimal("120000"),
        cash=Decimal("100000"), daily_pnl=Decimal("500"),
        daily_pnl_pct=0.4, cumulative_pnl_pct=20.0, max_drawdown=3.2)
    return owner


def _investor(owner, **flags):
    from portfolio.investor_models import InvestorAccess
    investor = get_user_model().objects.create_user(
        f"lp_{owner.username}", password="investorpass")
    access = InvestorAccess.objects.create(
        investor=investor, owner=owner, label="Fund A", **flags)
    return investor, access


class TheCageTests(TestCase):
    def setUp(self):
        self.owner = _owner_with_book()
        self.investor, self.access = _investor(self.owner)
        self.client.force_login(self.investor)

    def test_every_caged_route_bounces_to_the_panel(self):
        for route in CAGED_ROUTES:
            resp = self.client.get(route)
            self.assertEqual(resp.status_code, 302, route)
            self.assertEqual(resp["Location"], "/investor/", route)

    def test_posts_bounce_too(self):
        """Reading is bounced politely; WRITING must never even reach a
        view — the kill switch, a trade execution and the bot toggle are
        the loudest examples. (The test client skips CSRF enforcement,
        so these verdicts are the GATE's, not a 403 masking it.)"""
        for route in ("/api/kill-switch/", "/instruments/BTCUSD/take-trade/",
                      "/bot/toggle/", "/api/session/unlock/"):
            resp = self.client.post(route, {})
            self.assertEqual(resp.status_code, 302, route)
            self.assertEqual(resp["Location"], "/investor/", route)

    def test_the_live_sockets_refuse_an_investor(self):
        """The cage is HTTP middleware and websockets never meet it —
        the consumers must ask the question themselves, and fail CLOSED:
        an investor session on /ws/dashboard/ would stream the
        platform's entire live signal feed. Active AND revoked deny."""
        from asgiref.sync import async_to_sync

        from dashboard.consumers import _investor_socket_denied

        self.assertTrue(async_to_sync(_investor_socket_denied)(
            self.investor))
        self.access.is_active = False
        self.access.save()
        self.assertTrue(async_to_sync(_investor_socket_denied)(
            self.investor), "revoked still denies")
        operator = get_user_model().objects.create_user("op_ws",
                                                        password="x")
        self.assertFalse(async_to_sync(_investor_socket_denied)(operator))

    def test_both_consumers_ask_the_socket_question(self):
        """Source-pinned like the entry gates: a consumer that stops
        asking reopens the hole silently."""
        import inspect

        from dashboard import consumers
        for cls in (consumers.DashboardConsumer, consumers.EyeConsumer):
            src = inspect.getsource(cls.connect)
            self.assertIn("_investor_socket_denied", src, cls.__name__)

    def test_an_unreadable_access_row_fails_closed(self):
        """A database hiccup must never promote a maybe-outsider into a
        full operator — UNREADABLE lands on the wall, not the app."""
        from unittest import mock

        from core import investor_gate

        with mock.patch.object(investor_gate, "investor_access_for",
                               return_value=investor_gate.UNREADABLE):
            resp = self.client.get("/positions/")
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], "/wall/")

    def test_the_panel_and_the_exit_are_the_whole_world(self):
        self.assertEqual(self.client.get("/investor/").status_code, 200)
        self.assertEqual(self.client.get("/investor/live/").status_code, 200)

    def test_revocation_ends_the_session_at_the_gate(self):
        self.access.is_active = False
        self.access.save()
        resp = self.client.get("/investor/")
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], "/wall/")
        # And the session is genuinely gone, not merely redirected.
        resp = self.client.get("/positions/")
        self.assertNotEqual(resp.get("Location"), "/investor/")

    def test_operators_are_untouched_by_the_gate(self):
        operator = get_user_model().objects.create_user("op_x", password="x")
        self.client.force_login(operator)
        self.assertEqual(self.client.get("/positions/").status_code, 200)
        # And an operator pasting the investor URL finds nothing there.
        self.assertEqual(self.client.get("/investor/")["Location"], "/")


class ThePanelShowsExactlyWhatIsGrantedTests(TestCase):
    def setUp(self):
        self.owner = _owner_with_book("fund_b")

    def _open_trade(self):
        from bot_program.models import AssetBotConfig, AssetBotTrade
        cfg = AssetBotConfig.objects.create(
            user=self.owner, asset_class="crypto", name="c", enabled=True,
            mode="paper", symbols=[], capital=Decimal("10000"))
        return AssetBotTrade.objects.create(
            config=cfg, asset_class="crypto", symbol="BTCUSD", side="BUY",
            qty=Decimal("1"), entry_price=Decimal("4000"), status="OPEN",
            metadata={"value_per_unit": 1.0})

    def test_the_floor_is_percentages_and_the_curve(self):
        investor, _ = _investor(self.owner)
        self.client.force_login(investor)
        resp = self.client.get("/investor/")
        self.assertContains(resp, "Fund A")
        self.assertContains(resp, "+20.00%")
        self.assertContains(resp, "READ ONLY")
        # The owner's LOGIN NAME is internal plumbing — it must never
        # reach the outsider's HTML, on the shell or the live twin.
        self.assertNotContains(resp, self.owner.username)
        live = self.client.get("/investor/live/")
        self.assertNotContains(live, self.owner.username)
        # percents_only default: the book VALUE never renders.
        self.assertNotContains(resp, "125,000")
        # positions not granted: the section is absent entirely.
        self.assertNotContains(resp, "Open positions")

    def test_dollar_amounts_appear_only_when_granted(self):
        investor, _ = _investor(self.owner, percents_only=False)
        self.client.force_login(investor)
        resp = self.client.get("/investor/")
        self.assertContains(resp, "125,000")

    def test_positions_appear_only_when_granted(self):
        self._open_trade()
        investor, _ = _investor(self.owner, show_positions=True)
        self.client.force_login(investor)
        resp = self.client.get("/investor/")
        self.assertContains(resp, "Open positions")
        self.assertContains(resp, "BTCUSD")

    def test_the_panel_is_scoped_to_its_own_owner_only(self):
        """Two funds, two investors — investor B's page must not know
        fund A exists. The view takes nothing from the request, but the
        assertion belongs here anyway: this is the promise."""
        other_owner = _owner_with_book("fund_c")
        from bot_program.models import AssetBotConfig, AssetBotTrade
        cfg = AssetBotConfig.objects.create(
            user=other_owner, asset_class="crypto", name="c2", enabled=True,
            mode="paper", symbols=[], capital=Decimal("10000"))
        AssetBotTrade.objects.create(
            config=cfg, asset_class="crypto", symbol="SOLUSD", side="BUY",
            qty=Decimal("1"), entry_price=Decimal("100"), status="OPEN",
            metadata={"value_per_unit": 1.0})

        self._open_trade()  # fund_b's BTCUSD
        investor, _ = _investor(self.owner, show_positions=True)
        self.client.force_login(investor)
        resp = self.client.get("/investor/")
        self.assertContains(resp, "BTCUSD")
        self.assertNotContains(resp, "SOLUSD")


class HQManagementTests(TestCase):
    def setUp(self):
        # Superuser, matching the house HQ gate — staff alone is not
        # enough to mint an investor, exactly as it is not enough to save
        # broker keys.
        self.admin = get_user_model().objects.create_superuser(
            "hq_admin", password="x")
        self.owner = _owner_with_book("fund_d")
        self.client.force_login(self.admin)

    def test_create_revoke_restore_round_trip(self):
        from portfolio.investor_models import InvestorAccess
        resp = self.client.post("/admin-dashboard/investors/create/", {
            "owner_username": "fund_d", "investor_username": "lp_one",
            "investor_password": "longenough1", "label": "Mandate One",
            "show_positions": "on"}, follow=True)
        self.assertEqual(resp.status_code, 200)
        access = InvestorAccess.objects.get(investor__username="lp_one")
        self.assertTrue(access.show_positions)
        self.assertTrue(access.percents_only,
                        "dollars are disclosed only by explicit grant")

        self.client.post("/admin-dashboard/investors/toggle/",
                         {"access_id": access.pk})
        access.refresh_from_db()
        self.assertFalse(access.is_active)

    def test_a_weak_password_is_refused(self):
        from portfolio.investor_models import InvestorAccess
        for bad in ("short", "12345678"):  # length, then all-numeric
            self.client.post("/admin-dashboard/investors/create/", {
                "owner_username": "fund_d", "investor_username": "lp_two",
                "investor_password": bad, "label": "L"}, follow=True)
            self.assertFalse(InvestorAccess.objects.filter(
                investor__username="lp_two").exists(), bad)

    def test_a_blank_label_is_refused(self):
        """The blank-label fallback used to print the owner's internal
        username on the investor's screen — the label is mandatory."""
        from portfolio.investor_models import InvestorAccess
        self.client.post("/admin-dashboard/investors/create/", {
            "owner_username": "fund_d", "investor_username": "lp_lbl",
            "investor_password": "longenough1"}, follow=True)
        self.assertFalse(InvestorAccess.objects.filter(
            investor__username="lp_lbl").exists())

    def test_an_admin_account_cannot_be_windowed(self):
        """A window onto the admin's book hands an outsider the
        platform's own ledger under a friendly label."""
        from portfolio.investor_models import InvestorAccess
        self.client.post("/admin-dashboard/investors/create/", {
            "owner_username": "hq_admin", "investor_username": "lp_adm",
            "investor_password": "longenough1", "label": "L"}, follow=True)
        self.assertFalse(InvestorAccess.objects.filter(
            investor__username="lp_adm").exists())

    def test_the_hq_card_lists_the_window_and_its_revoke_control(self):
        """The context wiring broke once already — spliced into another
        view's f-string — so the card's rendering is pinned end to end."""
        _investor(self.owner)
        resp = self.client.get("/admin-dashboard/")
        self.assertContains(resp, "lp_fund_d")
        self.assertContains(resp, "Revoke")

    def test_component_toggle_still_answers(self):
        """The same splice turned every component toggle into a 500 —
        the neighbour this wave must never break again."""
        from core.platform_control import seed_components
        seed_components()
        resp = self.client.post("/admin-dashboard/toggle/",
                                {"key": "platform_master"})
        self.assertEqual(resp.status_code, 302)

    def test_an_investor_login_cannot_be_an_owner(self):
        """Chaining windows would cage the funded account itself."""
        from portfolio.investor_models import InvestorAccess
        _investor(self.owner)  # lp_fund_d exists as an investor
        self.client.post("/admin-dashboard/investors/create/", {
            "owner_username": "lp_fund_d", "investor_username": "lp_three",
            "investor_password": "longenough1"}, follow=True)
        self.assertFalse(InvestorAccess.objects.filter(
            investor__username="lp_three").exists())

    def test_non_staff_cannot_reach_the_management_endpoints(self):
        self.client.force_login(
            get_user_model().objects.create_user("pleb", password="x"))
        resp = self.client.post("/admin-dashboard/investors/create/", {})
        self.assertIn(resp.status_code, (302, 403))
        from portfolio.investor_models import InvestorAccess
        self.assertEqual(InvestorAccess.objects.count(), 0)
