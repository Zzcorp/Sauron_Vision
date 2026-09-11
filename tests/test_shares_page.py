"""The share allocator's page — /shares/ — and its four decisions.

The page shows what share of the broker account each live follower pool
takes and what the allocator proposes, with '—' wherever nothing has
been measured (no reading, no plan) rather than a confident zero. The
decisions are the service's, behind the page's own gates: apply takes
the PIN in LIVE mode and is refused outright in shadow, rollback takes
the PIN, reject takes nothing, and a plan is only ever the acting
user's. These tests pin that the page mirrors `shares` (the shell twin)
and the service rather than re-implementing either.

Run with:  python manage.py test tests.test_shares_page
"""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

User = get_user_model()
XHR = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"}
PIN = "1234"


def _acct(user, equity="2000.00", currency="EUR", *, age_seconds=0):
    from bot_program.models import IBKRAccount
    acct = IBKRAccount.objects.create(user=user, port=4003,
                                      is_primary_for_stocks=True)
    acct.set_credentials("U1234567")
    acct.username_enc, acct.password_enc = "x", "y"
    acct.last_equity = Decimal(equity)
    acct.last_equity_currency = currency
    acct.last_equity_at = timezone.now() - timedelta(seconds=age_seconds)
    acct.save()
    return acct


def _cfg(user, *, name, asset_class="stock", mode="live", enabled=True,
         capital="100", tracks=False, share=None, symbols=("AAPL",)):
    from bot_program.models import AssetBotConfig
    ex = {}
    if tracks:
        ex["capital_tracks_broker"] = True
    if share is not None:
        ex["account_share_pct"] = share
    return AssetBotConfig.objects.create(
        user=user, asset_class=asset_class, name=name, mode=mode,
        enabled=enabled, symbols=list(symbols), capital=Decimal(capital),
        extras=ex)


def _fill(cfg, r, *, paper=False, rule="r1", days_ago=1.0):
    from bot_program.models import AssetBotTrade
    t = AssetBotTrade.objects.create(
        config=cfg, asset_class=cfg.asset_class, symbol="AAPL", side="BUY",
        qty=Decimal("1"), entry_price=Decimal("100"),
        exit_price=Decimal("101"), status="CLOSED", pnl=Decimal("1"),
        rule_name=rule, paper=paper, realized_r=r, outcome="hit_target")
    AssetBotTrade.objects.filter(pk=t.pk).update(
        closed_at=timezone.now() - timedelta(days=days_ago))
    return t


def _set_live(enabled: bool):
    from core.platform_control import PlatformComponent
    c, _ = PlatformComponent.objects.get_or_create(
        key="share_allocator_mode_live",
        defaults={"name": "Share Allocator Live Mode", "category": "system"})
    c.is_enabled = enabled
    c.save()


def _pin(user, pin=PIN):
    from django.contrib.auth.hashers import make_password
    from portfolio.trader_profile import TraderProfile
    prof, _ = TraderProfile.objects.get_or_create(user=user)
    prof.access_pin_hash = make_password(pin)
    prof.save(update_fields=["access_pin_hash"])


def _flashes(resp) -> str:
    return " | ".join(str(m) for m in get_messages(resp.wsgi_request))


class _Fixture(TestCase):
    """The ADMIN owns the account and the followers: a at 50% with ten
    winning live fills, b automatic — a proposal moves a to 55 and b to
    45, exactly as the service and command tests see it. The page filters
    every plan by the acting user, so the operator must be the owner."""

    def setUp(self):
        from django.core.cache import cache
        cache.clear()   # the run-now dispatch locks live here
        self.admin = User.objects.create_superuser("sp_admin", "a@x", "x")
        _pin(self.admin)
        self.acct = _acct(self.admin)
        self.a = _cfg(self.admin, name="alpha_stock", tracks=True, share=50,
                      capital="1000")
        self.b = _cfg(self.admin, name="beta_fx", tracks=True, capital="1000",
                      asset_class="forex", symbols=["EURUSD"])
        for _ in range(10):
            _fill(self.a, 1.0)
        _set_live(False)
        self.client.force_login(self.admin)

    def _propose(self):
        from bot_program.share_allocator import propose_share_plan
        plan = propose_share_plan(self.admin)
        self.assertIsNotNone(plan)
        return plan

    def _post(self, name, plan, pin=None, **extra):
        data = {"plan_id": plan.pk}
        if pin is not None:
            data["pin"] = pin
        data.update(extra)
        return self.client.post(reverse(name), data)


class PageGetTests(_Fixture):

    def test_login_is_required(self):
        self.client.logout()
        resp = self.client.get("/shares/")
        self.assertEqual(resp.status_code, 302)

    def test_the_page_renders_heading_followers_and_nav_label(self):
        resp = self.client.get("/shares/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "SHARE ALLOCATOR")
        self.assertContains(resp, "alpha_stock")
        self.assertContains(resp, "beta_fx")
        self.assertContains(resp, "Share Allocator")          # the nav row
        self.assertContains(resp, 'href="/shares/"')
        self.assertContains(resp, "SHADOW")
        self.assertContains(resp, "2,000.00 EUR")
        self.assertEqual(resp.context["page_id"], "shares")
        self.assertEqual(resp.context["MAX_APPLIES_PER_DAY"], 3)
        self.assertEqual(resp.context["daily_applies_used"], 0)
        self.assertTrue(resp.context["is_admin"])
        self.assertFalse(resp.context["live_mode"])

    def test_the_nav_row_has_no_activity_dot(self):
        """The sidebar dots are wired to a fixed set of sections
        (test_nothing_unseen pins it); a data-nav-id here would be a dot
        that can never light."""
        body = self.client.get("/shares/").content.decode()
        self.assertNotIn('data-nav-id="shares"', body)

    def test_without_a_reading_the_account_cell_is_a_dash_not_a_zero(self):
        """No IBKRAccount: the page must still render, with '—' where
        the reading and the drawdown would be — an unmeasured account
        is not a 0.00 account."""
        self.acct.delete()
        resp = self.client.get("/shares/")
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.context["reading"])
        self.assertIsNone(resp.context["drawdown"])
        self.assertContains(resp, "no broker reading yet")
        self.assertContains(resp, "—")
        self.assertNotContains(resp, "0.00 EUR")
        # And every follower is still listed, its target unmeasured.
        self.assertContains(resp, "alpha_stock")
        for row in resp.context["rows"]:
            self.assertIsNone(row["target"])

    def test_without_a_plan_the_target_column_is_a_dash(self):
        resp = self.client.get("/shares/")
        self.assertIsNone(resp.context["plan"])
        self.assertEqual(resp.context["pending"], [])
        self.assertContains(resp, "No pending plan")
        rows = {r["cfg"].name: r for r in resp.context["rows"]}
        self.assertEqual(rows["alpha_stock"]["current"], "50%")
        self.assertEqual(rows["beta_fx"]["current"], "auto 50%")
        self.assertIsNone(rows["alpha_stock"]["target"])
        self.assertIsNone(rows["alpha_stock"]["delta"])
        self.assertEqual(rows["alpha_stock"]["floor"], 2.0)
        self.assertEqual(rows["alpha_stock"]["ceiling"], 60.0)

    def test_a_pending_plan_fills_the_rows_and_the_pending_table(self):
        plan = self._propose()
        resp = self.client.get("/shares/")
        self.assertEqual(resp.context["plan"].pk, plan.pk)
        self.assertEqual([p.pk for p in resp.context["pending"]], [plan.pk])
        rows = {r["cfg"].name: r for r in resp.context["rows"]}
        self.assertEqual(rows["alpha_stock"]["target"], 55.0)
        self.assertAlmostEqual(rows["alpha_stock"]["delta"], 5.0)
        self.assertEqual(rows["beta_fx"]["target"], 45.0)
        self.assertAlmostEqual(rows["beta_fx"]["delta"], -5.0)
        self.assertIn("evidence 1.50", rows["alpha_stock"]["why"])
        self.assertContains(resp, f"#{plan.pk}")
        self.assertContains(resp, "55.00%")
        self.assertContains(resp, "evidence 1.50")
        self.assertContains(resp, "50% → 55%")
        # Apply is on the page but disabled until LIVE; Reject is not.
        self.assertContains(resp, 'title="Promote to LIVE first"')
        self.assertContains(resp, reverse("hq_apply_share_plan"))
        self.assertContains(resp, reverse("hq_reject_share_plan"))
        self.assertContains(resp, 'data-run-job="Share-allocator proposal"')

    def test_a_held_row_wears_the_badge(self):
        plan = self._propose()
        inputs = plan.inputs
        inputs[str(self.a.pk)]["held"] = True
        plan.inputs = inputs
        plan.save(update_fields=["inputs"])
        resp = self.client.get("/shares/")
        self.assertContains(resp, ">held<")

    def test_live_mode_enables_apply(self):
        _set_live(True)
        self._propose()
        resp = self.client.get("/shares/")
        self.assertTrue(resp.context["live_mode"])
        self.assertContains(resp, "LIVE")
        self.assertNotContains(resp, 'title="Promote to LIVE first"')

    def test_a_viewer_sees_the_page_without_the_decide_column(self):
        self._propose()
        viewer = User.objects.create_user("sp_viewer", password="x")
        self.client.force_login(viewer)
        resp = self.client.get("/shares/")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.context["is_admin"])
        self.assertNotContains(resp, reverse("hq_apply_share_plan"))
        # And not the admin's plan either — plans are the acting user's.
        self.assertEqual(resp.context["pending"], [])

    def test_history_and_applied_tables_list_decided_plans(self):
        from bot_program.share_models import SharePlan
        _set_live(True)
        plan = self._propose()
        from bot_program.share_allocator import apply_share_plan
        apply_share_plan(plan.pk, self.admin)
        graded = SharePlan.objects.create(
            user=self.admin, state=SharePlan.STATE_REJECTED,
            targets={str(self.a.pk): 60}, current_shares={str(self.a.pk): 50},
            inputs={str(self.a.pk): {"name": "alpha_stock", "why": "w"}},
            rejected_at=timezone.now(), graded_at=timezone.now(),
            grade_score=0.25)
        resp = self.client.get("/shares/")
        self.assertEqual([p.pk for p in resp.context["applied"]], [plan.pk])
        self.assertEqual({p.pk for p in resp.context["history"]},
                         {plan.pk, graded.pk})
        self.assertContains(resp, "0.2500")
        self.assertContains(resp, reverse("hq_rollback_share_plan"))
        self.assertEqual(resp.context["daily_applies_used"], 1)

    def test_a_reader_that_raises_does_not_take_the_page_down(self):
        """A pending plan an operator cannot see expires undecided —
        every read on the page is fenced."""
        self._propose()
        with patch("bot_program.capital_truth.equity_drawdown",
                   side_effect=RuntimeError("history table gone")):
            resp = self.client.get("/shares/")
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.context["drawdown"])
        self.assertContains(resp, "alpha_stock")


class ApplyViewTests(_Fixture):

    def test_shadow_mode_refuses_with_the_services_sentence(self):
        from bot_program.share_models import SharePlan
        plan = self._propose()
        resp = self._post("hq_apply_share_plan", plan, pin=PIN)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], "/shares/")
        self.assertIn("shadow mode", _flashes(resp))
        plan.refresh_from_db()
        self.assertEqual(plan.state, SharePlan.STATE_PROPOSED)
        self.a.refresh_from_db(); self.b.refresh_from_db()
        self.assertEqual(self.a.extras["account_share_pct"], 50)
        self.assertNotIn("account_share_pct", self.b.extras)
        self.assertEqual(float(self.a.capital), 1000.0)

    def test_live_without_the_pin_is_refused_and_writes_nothing(self):
        from bot_program.share_models import SharePlan
        _set_live(True)
        plan = self._propose()
        for bad in (None, "", "9999"):
            resp = self._post("hq_apply_share_plan", plan, pin=bad)
            self.assertIn("PIN required — applying a share plan re-sizes "
                          "live pools.", _flashes(resp))
        plan.refresh_from_db()
        self.assertEqual(plan.state, SharePlan.STATE_PROPOSED)
        self.a.refresh_from_db()
        self.assertEqual(self.a.extras["account_share_pct"], 50)
        self.assertEqual(float(self.a.capital), 1000.0)

    def test_live_with_the_pin_writes_every_share_and_resplits_capital(self):
        from bot_program.models import AuditLogEntry
        from bot_program.share_models import SharePlan
        _set_live(True)
        plan = self._propose()
        resp = self._post("hq_apply_share_plan", plan, pin=PIN)
        self.assertEqual(resp["Location"], "/shares/")
        self.assertIn(f"Applied share plan #{plan.pk}", _flashes(resp))
        self.assertIn("2 pool(s) re-sized", _flashes(resp))
        plan.refresh_from_db()
        self.assertEqual(plan.state, SharePlan.STATE_APPLIED)
        self.assertEqual(plan.confirmed_by, self.admin)
        self.assertEqual(plan.previous_shares,
                         {str(self.a.pk): 50, str(self.b.pk): None})
        self.a.refresh_from_db(); self.b.refresh_from_db()
        self.assertEqual(self.a.extras["account_share_pct"], 55.0)
        self.assertEqual(self.b.extras["account_share_pct"], 45.0)
        self.assertEqual(float(self.a.capital), 1100.0)    # 55% of 2000
        self.assertEqual(float(self.b.capital), 900.0)
        row = AuditLogEntry.objects.filter(kind="share_plan").last()
        self.assertEqual(row.data["decision"], "applied")
        self.assertEqual(row.user, self.admin)

    def test_the_daily_cap_is_the_services(self):
        from bot_program.share_allocator import MAX_APPLIES_PER_DAY
        from bot_program.share_models import SharePlan
        _set_live(True)
        for _ in range(MAX_APPLIES_PER_DAY):
            SharePlan.objects.create(
                user=self.admin, state=SharePlan.STATE_APPLIED,
                targets={str(self.a.pk): 50},
                previous_shares={str(self.a.pk): 50},
                applied_at=timezone.now() - timedelta(hours=2))
        plan = self._propose()
        resp = self._post("hq_apply_share_plan", plan, pin=PIN)
        self.assertIn("Daily cap", _flashes(resp))
        self.a.refresh_from_db()
        self.assertEqual(self.a.extras["account_share_pct"], 50)

    def test_another_users_plan_is_not_found_even_with_the_pin(self):
        """Ownership: plan_id is a form field, and a share plan re-sizes
        its OWNER's pools."""
        from bot_program.share_models import SharePlan
        _set_live(True)
        other = User.objects.create_user("sp_other", password="x")
        theirs = SharePlan.objects.create(
            user=other, state=SharePlan.STATE_PROPOSED,
            targets={str(self.a.pk): 60}, current_shares={str(self.a.pk): 50})
        resp = self._post("hq_apply_share_plan", theirs, pin=PIN)
        self.assertIn("not found", _flashes(resp))
        theirs.refresh_from_db()
        self.assertEqual(theirs.state, SharePlan.STATE_PROPOSED)
        self.a.refresh_from_db()
        self.assertEqual(self.a.extras["account_share_pct"], 50)

    def test_a_bad_plan_id_is_a_flash_not_a_500(self):
        resp = self.client.post(reverse("hq_apply_share_plan"),
                                {"plan_id": "abc", "pin": PIN})
        self.assertEqual(resp.status_code, 302)
        self.assertIn("Invalid plan_id", _flashes(resp))


class RejectAndRollbackViewTests(_Fixture):

    def test_reject_needs_no_pin_and_writes_nothing(self):
        from bot_program.models import AuditLogEntry
        from bot_program.share_models import SharePlan
        plan = self._propose()
        resp = self._post("hq_reject_share_plan", plan)
        self.assertEqual(resp["Location"], "/shares/")
        self.assertIn(f"Rejected share plan #{plan.pk}", _flashes(resp))
        plan.refresh_from_db()
        self.assertEqual(plan.state, SharePlan.STATE_REJECTED)
        self.assertIsNotNone(plan.rejected_at)
        self.a.refresh_from_db(); self.b.refresh_from_db()
        self.assertEqual(self.a.extras["account_share_pct"], 50)
        self.assertNotIn("account_share_pct", self.b.extras)
        self.assertEqual(float(self.a.capital), 1000.0)
        self.assertEqual(AuditLogEntry.objects.filter(kind="share_plan")
                         .last().data["decision"], "rejected")
        # A second reject is refused by the service, in its words.
        resp = self._post("hq_reject_share_plan", plan)
        self.assertIn("not proposed", _flashes(resp))

    def test_rollback_without_the_pin_is_refused(self):
        from bot_program.share_allocator import apply_share_plan
        from bot_program.share_models import SharePlan
        _set_live(True)
        plan = self._propose()
        apply_share_plan(plan.pk, self.admin)
        resp = self._post("hq_rollback_share_plan", plan, pin="0000")
        self.assertIn("PIN required", _flashes(resp))
        plan.refresh_from_db()
        self.assertEqual(plan.state, SharePlan.STATE_APPLIED)
        self.a.refresh_from_db()
        self.assertEqual(self.a.extras["account_share_pct"], 55.0)

    def test_rollback_with_the_pin_restores_exactly(self):
        from bot_program.share_allocator import apply_share_plan
        from bot_program.share_models import SharePlan
        _set_live(True)
        plan = self._propose()
        apply_share_plan(plan.pk, self.admin)
        resp = self._post("hq_rollback_share_plan", plan, pin=PIN)
        self.assertIn(f"Rolled back share plan #{plan.pk}", _flashes(resp))
        plan.refresh_from_db()
        self.assertEqual(plan.state, SharePlan.STATE_ROLLED_BACK)
        self.a.refresh_from_db(); self.b.refresh_from_db()
        self.assertEqual(self.a.extras["account_share_pct"], 50)
        self.assertNotIn("account_share_pct", self.b.extras)   # key popped
        self.assertTrue(self.b.extras["capital_tracks_broker"])
        self.assertEqual(float(self.a.capital), 1000.0)
        self.assertEqual(float(self.b.capital), 1000.0)

    def test_rollback_of_a_proposed_plan_is_refused_in_the_services_words(self):
        plan = self._propose()
        resp = self._post("hq_rollback_share_plan", plan, pin=PIN)
        self.assertIn("not applied", _flashes(resp))


class GateTests(_Fixture):
    """The four POST views share the admin-HQ shape: superuser-only,
    POST-only."""

    VIEWS = ("hq_propose_share_plan", "hq_apply_share_plan",
             "hq_reject_share_plan", "hq_rollback_share_plan")

    def test_a_non_superuser_post_is_403(self):
        from bot_program.share_models import SharePlan
        plan = self._propose()
        staff = User.objects.create_user("sp_staff", password="x",
                                         is_staff=True)
        _pin(staff)
        self.client.force_login(staff)
        for name in self.VIEWS:
            resp = self.client.post(reverse(name),
                                    {"plan_id": plan.pk, "pin": PIN})
            self.assertEqual(resp.status_code, 403, name)
        plan.refresh_from_db()
        self.assertEqual(plan.state, SharePlan.STATE_PROPOSED)

    def test_a_get_on_a_post_view_is_405(self):
        for name in self.VIEWS:
            resp = self.client.get(reverse(name))
            self.assertEqual(resp.status_code, 405, name)

    def test_anonymous_is_sent_to_login(self):
        self.client.logout()
        resp = self.client.post(reverse("hq_reject_share_plan"),
                                {"plan_id": 1})
        self.assertEqual(resp.status_code, 302)
        # The wall (settings.LOGIN_URL), with the way back — not a 403,
        # which would tell an anonymous caller the route exists and gates.
        self.assertIn("next=/admin-dashboard/shares/reject/", resp["Location"])


class ProposeViewTests(_Fixture):

    def test_a_plain_post_proposes_synchronously_and_redirects(self):
        from bot_program.share_models import SharePlan
        resp = self.client.post(reverse("hq_propose_share_plan"))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], "/shares/")
        plan = SharePlan.objects.get(user=self.admin)
        self.assertEqual(plan.state, SharePlan.STATE_PROPOSED)
        self.assertIn(f"proposed plan #{plan.pk}", _flashes(resp))
        # A proposal writes its own row and nothing else.
        self.a.refresh_from_db()
        self.assertEqual(self.a.extras["account_share_pct"], 50)
        self.assertEqual(float(self.a.capital), 1000.0)

    def test_a_plain_post_says_why_when_nothing_is_proposed(self):
        from bot_program.share_models import SharePlan
        self.acct.last_equity_at = timezone.now() - timedelta(hours=3)
        self.acct.save(update_fields=["last_equity_at"])
        resp = self.client.post(reverse("hq_propose_share_plan"))
        self.assertIn("nothing proposed", _flashes(resp))
        self.assertIn("no fresh reading", _flashes(resp))
        self.assertFalse(SharePlan.objects.exists())

    def test_an_xhr_click_enqueues_the_beat_task_and_returns_202(self):
        from bot_program.tasks import propose_share_plans
        with patch.object(propose_share_plans, "apply_async",
                          return_value=MagicMock(id="task-1")) as enq:
            resp = self.client.post(reverse("hq_propose_share_plan"), **XHR)
        self.assertEqual(resp.status_code, 202)
        self.assertTrue(resp.json()["ok"])
        self.assertEqual(resp.json()["job"], "Share-allocator proposal")
        enq.assert_called_once()
        self.assertEqual(enq.call_args.kwargs["kwargs"], {})

    def test_a_second_click_is_refused_while_in_flight(self):
        from bot_program.tasks import propose_share_plans
        with patch.object(propose_share_plans, "apply_async",
                          return_value=MagicMock(id="t")) as enq:
            first = self.client.post(reverse("hq_propose_share_plan"), **XHR)
            second = self.client.post(reverse("hq_propose_share_plan"), **XHR)
        self.assertEqual(first.status_code, 202)
        self.assertEqual(second.status_code, 409)
        enq.assert_called_once()


class AdminDashboardPanelTests(_Fixture):

    def test_the_admin_dashboard_carries_the_live_toggle(self):
        from core.platform_control import seed_components
        seed_components()
        self._propose()
        resp = self.client.get("/admin-dashboard/")
        self.assertEqual(resp.status_code, 200)
        comp = resp.context["share_allocator_live_component"]
        self.assertIsNotNone(comp)
        self.assertEqual(comp.key, "share_allocator_mode_live")
        self.assertEqual(resp.context["share_plans_pending"], 1)
        self.assertContains(resp, 'value="share_allocator_mode_live"')
        self.assertContains(resp, "PROMOTE TO LIVE")
        self.assertContains(resp, 'href="/shares/"')
        self.assertContains(resp, 'data-run-job="Share-allocator proposal"')
