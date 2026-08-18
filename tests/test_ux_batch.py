"""The 2026-08-19 UX truth batch.

Every item here was a user-visible lie or dead end: headband counters
frozen at render time, notification links that 404ed for months, a
strategies page that hid the seeded strategies, portfolio/positions pages
blind to the book every interactive trade actually writes, and a signals
popup that disagreed with the rail about what "the current signals" are.

Run with:  python manage.py test tests.test_ux_batch
"""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone


def _instrument(symbol="BTCUSD", asset_class="crypto", **kw):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class,
                                 **kw})
    return inst


def _bot_trade(user, symbol="BTCUSD", status="OPEN", **kw):
    from bot_program.models import AssetBotConfig, AssetBotTrade
    cfg, _ = AssetBotConfig.objects.get_or_create(
        user=user, asset_class="crypto", name="manual",
        defaults={"symbols": [], "enabled": True, "mode": "paper"})
    defaults = dict(
        config=cfg, asset_class="crypto", symbol=symbol, side="BUY",
        qty=Decimal("0.5"), entry_price=Decimal("100"),
        stop_loss=Decimal("95"), take_profit=Decimal("110"),
        status=status, paper=True, rule_name="manual_take",
        opened_at=timezone.now())
    defaults.update(kw)
    return AssetBotTrade.objects.create(**defaults)


# ── Notifications: links must lead somewhere real ───────────────────────

class NotificationLinkTests(TestCase):
    def test_safe_url_blanks_dead_paths_and_keeps_live_ones(self):
        from alerts.models import Notification
        self.assertEqual(Notification.safe_url("/market-data/"), "")
        self.assertEqual(Notification.safe_url("/quotes/"), "/quotes/")
        self.assertEqual(Notification.safe_url("/briefing/"), "/briefing/")
        self.assertEqual(Notification.safe_url("https://example.com/x"),
                         "https://example.com/x")
        self.assertEqual(Notification.safe_url(""), "")

    def test_create_for_all_guards_the_url(self):
        from alerts.models import Notification
        User.objects.create_user("nb_u")
        Notification.create_for_all(
            notification_type="system", title="t", url="/market-data/")
        self.assertEqual(Notification.objects.get(title="t").url, "",
                         "a dead link must be stored empty, not 404 later")

    def test_repair_command_rewrites_shipped_404s(self):
        from django.core.management import call_command
        from alerts.models import Notification
        u = User.objects.create_user("nb_u2")
        Notification.objects.create(
            user=u, notification_type="system", title="anomaly",
            url="/market-data/")
        Notification.objects.create(
            user=u, notification_type="system", title="briefing",
            url="/dashboard/")
        call_command("repair_notification_urls")
        self.assertEqual(
            Notification.objects.get(title="anomaly").url, "/quotes/")
        self.assertEqual(
            Notification.objects.get(title="briefing").url, "/briefing/")


class NotificationsInboxTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("inbox_u")

    def setUp(self):
        self.client.force_login(self.user)

    def _notif(self, **kw):
        from alerts.models import Notification
        defaults = dict(user=self.user, notification_type="system",
                        title="Anomaly alert", body="Full body text here.",
                        url="/quotes/")
        defaults.update(kw)
        return Notification.objects.create(**defaults)

    def test_the_inbox_lists_everything_with_full_bodies(self):
        self._notif()
        resp = self.client.get("/notifications/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Anomaly alert")
        self.assertContains(resp, "Full body text here.")
        self.assertContains(resp, 'href="/quotes/"')

    def test_settings_moved_but_kept_their_name(self):
        resp = self.client.get("/notifications/settings/")
        self.assertEqual(resp.status_code, 200)

    def test_unread_filter(self):
        self._notif(title="unread one")
        self._notif(title="read one", read=True)
        resp = self.client.get("/notifications/?unread=1")
        # Assert on the view's context — the page chrome (bell dropdown,
        # bottom headband drawer) legitimately shows recent notifications
        # regardless of the inbox filter.
        titles = [n.title for n in resp.context["page_obj"].object_list]
        self.assertIn("unread one", titles)
        self.assertNotIn("read one", titles)

    def test_mark_all_read_refuses_get(self):
        """A state change on GET let prefetching proxies clear the inbox."""
        self._notif()
        resp = self.client.get("/notifications/read-all/")
        self.assertEqual(resp.status_code, 405)
        resp = self.client.post("/notifications/read-all/")
        self.assertIn(resp.status_code, (200, 302))
        from alerts.models import Notification
        self.assertFalse(Notification.objects.filter(
            user=self.user, read=False).exists())

    def test_single_mark_read(self):
        n = self._notif()
        self.client.post(f"/notifications/read/{n.id}/")
        n.refresh_from_db()
        self.assertTrue(n.read)


# ── Headband: live numbers, one truth ───────────────────────────────────

class PanelCountsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("panel_u")

    def setUp(self):
        self.client.force_login(self.user)

    def test_counts_include_the_book_trades_actually_land_in(self):
        _bot_trade(self.user, status="OPEN")
        _bot_trade(self.user, symbol="ETHUSD", status="CLOSE_PENDING",
                   closed_at=None)
        inst = _instrument("STARX", "stock")
        inst.is_watchlist = True
        inst.is_active = True
        inst.save()
        resp = self.client.get("/partials/panel-counts/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["bot_open"], 2)
        self.assertGreaterEqual(data["positions"], 2,
                                "open AssetBotTrades must count as positions")
        self.assertGreaterEqual(data["watchlist"], 1)

    def test_the_positions_cell_counts_both_books(self):
        from core.context_processors import sauron_context
        from django.test import RequestFactory
        _bot_trade(self.user, status="OPEN")
        req = RequestFactory().get("/")
        req.user = self.user
        ctx = sauron_context(req)
        self.assertGreaterEqual(ctx.get("panel_positions", 0), 1,
                                "the cell froze at the empty legacy book")

    def test_headband_signals_popup_matches_the_rail(self):
        """The cell showed top-4 BY SCORE while the rail showed the newest
        five — two truths on one screen."""
        from core.context_processors import _panel_detail
        from signals.models import Signal
        inst = _instrument()
        now = timezone.now()
        for i, score in enumerate([0.9, 0.2, 0.8, 0.3, 0.7, 0.4]):
            s = Signal.objects.create(
                instrument=inst, signal_type="technical",
                direction="bullish", urgency="high", title=f"s{i}",
                description="d", rule_name=f"r{i}", score=score,
                sub_scores={}, price_at_signal=Decimal("100"),
                is_active=True)
            Signal.objects.filter(pk=s.pk).update(
                created_at=now - timedelta(minutes=60 - i))
        out = _panel_detail(self.user)
        rules = [row["rule"] for row in out["panel_top_signals"]]
        self.assertEqual(rules, ["r5", "r4", "r3", "r2", "r1"],
                         "popup must list the newest five, like the rail")

    def test_starring_broadcasts_the_absolute_count(self):
        inst = _instrument("PUSHX", "stock")
        with patch("dashboard.consumers.push_watchlist_update") as pushed:
            resp = self.client.post(f"/instruments/{inst.symbol}/watchlist/",
                                    {"next": ""})
        self.assertIn(resp.status_code, (302, 200))
        pushed.assert_called_once()


# ── Portfolio/positions: the union of both books ────────────────────────

class UnifiedPositionsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("uni_u")

    def setUp(self):
        self.client.force_login(self.user)

    def test_a_taken_trade_reaches_the_positions_page(self):
        _instrument()
        _bot_trade(self.user, status="OPEN")
        resp = self.client.get("/positions/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "BTCUSD",
                            msg_prefix="the trade every other surface shows")

    def test_a_taken_trade_reaches_the_portfolio_page(self):
        _instrument()
        _bot_trade(self.user, status="OPEN")
        resp = self.client.get("/portfolio/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "BTCUSD")

    def test_closed_trades_carry_their_real_pnl(self):
        from portfolio.services import unified_closed_positions
        _bot_trade(self.user, status="CLOSED", pnl=Decimal("12.5"),
                   exit_price=Decimal("125"),
                   closed_at=timezone.now())
        rows = unified_closed_positions(self.user)
        self.assertEqual(len(rows), 1)
        self.assertEqual(float(rows[0].unrealized_pnl), 12.5)
        self.assertEqual(rows[0].direction, "long")

    def test_close_pending_still_counts_as_exposure(self):
        from portfolio.services import unified_open_positions
        _bot_trade(self.user, status="CLOSE_PENDING")
        self.assertEqual(len(unified_open_positions(self.user)), 1)


# ── Strategies: the page tells the whole story ──────────────────────────

class StrategiesPageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("strat_u")

    def setUp(self):
        self.client.force_login(self.user)

    def test_seeded_setups_appear_with_their_state(self):
        from signals.management.commands.seed_strategies import seed_setups
        seed_setups(activate=False)
        resp = self.client.get("/strategies/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Automated setups")
        self.assertContains(resp, "starter_stock_momentum")
        self.assertContains(resp, "PAUSED")

    def test_reseeding_never_disarms_a_hand_activated_setup(self):
        from signals.management.commands.seed_strategies import seed_setups
        from signals.models_opportunity import OpportunitySetup
        seed_setups(activate=False)
        OpportunitySetup.objects.filter(
            name="starter_stock_momentum").update(is_active=True)
        seed_setups(activate=False)
        self.assertTrue(OpportunitySetup.objects.get(
            name="starter_stock_momentum").is_active,
            "a re-run without --activate silently disarmed the operator")


# ── Evolution: visible to every registered user ─────────────────────────

class EvolutionVisibilityTests(TestCase):
    def test_a_regular_user_sees_the_family_tree_read_only(self):
        from signals.models_control import RuleControl, RuleMutation
        user = User.objects.create_user("evo_viewer")
        RuleControl.objects.create(rule_name="golden_cross",
                                   promotion_stage="live_full")
        RuleControl.objects.create(rule_name="golden_cross_evolved_v1",
                                   promotion_stage="research",
                                   parameters={"fast": 30})
        RuleMutation.objects.create(
            parent_rule="golden_cross",
            forked_rule="golden_cross_evolved_v1",
            parent_params={}, mutated_params={"fast": 30},
            parameters_changed=["fast"], proposed_score=0.4,
            score_method="walk_forward",
            score_details={"train_delta": 0.11, "test_delta": 0.06,
                           "notes": "ROBUST (both halves improve)"},
            state=RuleMutation.STATE_APPLIED,
            applied_at=timezone.now())
        self.client.force_login(user)
        resp = self.client.get("/evolution/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "golden_cross_evolved_v1")
        self.assertContains(resp, "ROBUST")
        self.assertNotContains(resp, ">Fork<",
                               msg_prefix="a viewer must not see decide buttons")

    def test_the_nav_links_the_evolution_page(self):
        user = User.objects.create_user("evo_nav")
        self.client.force_login(user)
        resp = self.client.get("/evolution/")
        self.assertContains(resp, "Strategy Evolution")
        self.assertContains(resp, 'href="/opportunities/"')
