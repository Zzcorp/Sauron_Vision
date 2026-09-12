"""The share allocator's page as a shell command — `shares`.

`/shares/` proposes, applies, rejects and rolls back share plans behind
the trading PIN. The command is that page without the browser, through
the SAME service functions: the same one-sentence refusal in shadow
mode, the same writes in LIVE mode (every follower's explicit share and
a re-split of the pools), the same exact restore on rollback, and
nothing written by reject or by a call without `--yes`. These tests
pin that the twin mirrors the page rather than re-implementing it.

Run with:  python manage.py test tests.test_shares_command
"""
from datetime import timedelta
from decimal import Decimal
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command
from django.test import TestCase
from django.utils import timezone

User = get_user_model()


def _run(*args, **kw):
    out = StringIO()
    call_command(*args, stdout=out, **kw)
    return out.getvalue()


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


class _Fixture(TestCase):
    """One user, a fresh reading, two followers — a at 50% with ten winning
    live fills, b automatic — so a proposal moves a to 55 and b to 45,
    exactly as ApplyTests in test_share_allocator sees it."""

    def setUp(self):
        self.user = User.objects.create_user("sh_u", password="x")
        self.admin = User.objects.create_superuser("sh_admin", "a@x", "x")
        self.acct = _acct(self.user)
        self.a = _cfg(self.user, name="alpha_stock", tracks=True, share=50,
                      capital="1000")
        self.b = _cfg(self.user, name="beta_fx", tracks=True, capital="1000",
                      asset_class="forex", symbols=["EURUSD"])
        for _ in range(10):
            _fill(self.a, 1.0)
        _set_live(False)

    def _propose(self):
        from bot_program.share_allocator import propose_share_plan
        plan = propose_share_plan(self.user)
        self.assertIsNotNone(plan)
        return plan


class ListAndProposeTests(_Fixture):

    def test_list_says_the_mode_and_names_every_follower(self):
        out = _run("shares", "list")
        self.assertIn("SHADOW (apply disabled)", out)
        self.assertIn("sh_u: account 2000.00 EUR", out)
        self.assertIn("2 follower(s)", out)
        self.assertIn("alpha_stock", out)
        self.assertIn("beta_fx", out)
        self.assertIn("50%", out)
        self.assertIn("auto 50%", out)
        self.assertIn("PROPOSED (0)", out)
        self.assertIn("LAST GRADED", out)
        self.assertIn("none yet", out)

    def test_list_in_live_mode_says_so(self):
        _set_live(True)
        out = _run("shares", "list")
        self.assertIn("LIVE (apply allowed)", out)

    def test_list_shows_a_pending_plan_with_current_target_and_why(self):
        plan = self._propose()
        out = _run("shares", "list")
        self.assertIn("PROPOSED (1)", out)
        self.assertIn(f"#{plan.pk}", out)
        self.assertIn("50% → 55%", out)
        # b is automatic; the plan records the share the split GIVES it
        # (50% of what a's explicit 50% leaves), not the word "auto".
        self.assertIn("50% → 45%", out)
        self.assertIn("evidence 1.50", out)         # the why line
        self.assertIn("governor 1.00", out)

    def test_list_filters_by_user_and_refuses_an_unknown_one(self):
        other = User.objects.create_user("sh_other", password="x")
        _acct(other)
        _cfg(other, name="other_pool", tracks=True, capital="500")
        out = _run("shares", "list", user="sh_u")
        self.assertIn("alpha_stock", out)
        self.assertNotIn("other_pool", out)
        with self.assertRaises(CommandError):
            _run("shares", "list", user="nobody")

    def test_propose_writes_a_plan_and_prints_it(self):
        from bot_program.share_models import SharePlan
        out = _run("shares", "propose", user="sh_u")
        plan = SharePlan.objects.get(user=self.user)
        self.assertEqual(plan.state, SharePlan.STATE_PROPOSED)
        self.assertIn(f"proposed plan #{plan.pk}", out)
        self.assertIn("nothing is re-sized until it is applied", out)
        self.assertIn("50% → 55%", out)
        # A proposal writes its own row and nothing else.
        self.a.refresh_from_db()
        self.assertEqual(self.a.extras["account_share_pct"], 50)
        self.assertEqual(float(self.a.capital), 1000.0)

    def test_list_and_propose_print_the_mode_and_its_reasons(self):
        """A plan proposed 20% under the high is a SHOCK plan and the
        shell says so, with the reason, before the targets — an operator
        reading "50% → 20%" must know the cap was off on purpose."""
        from bot_program.models import BrokerEquityReading
        BrokerEquityReading.objects.create(
            account=self.acct, value=Decimal("2500"), currency="EUR",
            env="live", at=timezone.now() - timedelta(days=10))
        out = _run("shares", "propose", user="sh_u")
        self.assertIn("mode SHOCK — drawdown 20.0% past the 5% knee", out)
        # 60/40 by evidence, × the 0.4 governor: 24/16, the whole way in
        # one plan — the 10-point cap would have printed 40/40.
        self.assertIn("50% → 24%", out)
        self.assertIn("50% → 16%", out)
        self.assertIn("SHOCK: de-risk only (no smoothing, down uncapped, "
                      "up frozen)", out)
        out = _run("shares", "list")
        self.assertIn("mode SHOCK — drawdown 20.0% past the 5% knee", out)
        # And the fixture's own plan — at the high-water mark with a
        # measured positive lane — reads EXPANSION, with its reasons, once
        # the shock plan's 24h hold has passed (the hold is a shock too).
        BrokerEquityReading.objects.filter(account=self.acct).delete()
        from bot_program.share_models import SharePlan
        SharePlan.objects.filter(user=self.user).update(
            proposed_at=timezone.now() - timedelta(hours=25))
        out = _run("shares", "propose", user="sh_u")
        self.assertIn("mode EXPANSION — at the high-water mark; alpha_stock: "
                      "avg_r +1.00 over 10 fills", out)

    def test_propose_prints_the_reason_when_nothing_is_proposed(self):
        from bot_program.share_models import SharePlan
        self.acct.last_equity_at = timezone.now() - timedelta(hours=3)
        self.acct.save(update_fields=["last_equity_at"])
        out = _run("shares", "propose", user="sh_u")
        self.assertIn("nothing proposed", out)
        self.assertIn("no fresh reading", out)
        self.assertFalse(SharePlan.objects.exists())

    def test_propose_needs_a_known_user(self):
        with self.assertRaises(CommandError) as ctx:
            _run("shares", "propose")
        self.assertIn("--user", str(ctx.exception))
        with self.assertRaises(CommandError):
            _run("shares", "propose", user="nobody")


class ApplyTests(_Fixture):

    def test_without_yes_only_prints_the_plan(self):
        from bot_program.share_models import SharePlan
        plan = self._propose()
        out = _run("shares", "apply", str(plan.pk))
        self.assertIn("plan only", out)
        self.assertIn("50% → 55%", out)
        plan.refresh_from_db()
        self.assertEqual(plan.state, SharePlan.STATE_PROPOSED)
        self.a.refresh_from_db()
        self.assertEqual(self.a.extras["account_share_pct"], 50)

    def test_shadow_mode_refuses_with_the_services_sentence(self):
        from bot_program.share_models import SharePlan
        plan = self._propose()
        out = _run("shares", "apply", str(plan.pk), yes=True)
        self.assertIn(f"#{plan.pk}: Share allocator is in shadow mode — "
                      f"apply is disabled.", out)
        plan.refresh_from_db()
        self.assertEqual(plan.state, SharePlan.STATE_PROPOSED)
        self.a.refresh_from_db(); self.b.refresh_from_db()
        self.assertEqual(self.a.extras["account_share_pct"], 50)
        self.assertNotIn("account_share_pct", self.b.extras)
        self.assertEqual(float(self.a.capital), 1000.0)

    def test_yes_in_live_mode_writes_the_shares_like_the_page(self):
        from bot_program.models import AuditLogEntry
        from bot_program.share_models import SharePlan
        _set_live(True)
        plan = self._propose()
        out = _run("shares", "apply", str(plan.pk), yes=True, by="sh_admin")
        self.assertIn(f"#{plan.pk}: APPLIED", out)
        self.assertIn("2 pool(s) re-sized", out)
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

    def test_without_by_nobody_is_linked(self):
        _set_live(True)
        plan = self._propose()
        _run("shares", "apply", str(plan.pk), yes=True)
        plan.refresh_from_db()
        self.assertEqual(plan.state, "applied")
        self.assertIsNone(plan.confirmed_by)

    def test_the_daily_cap_is_the_services(self):
        from bot_program.share_allocator import MAX_APPLIES_PER_DAY
        from bot_program.share_models import SharePlan
        _set_live(True)
        for _ in range(MAX_APPLIES_PER_DAY):
            SharePlan.objects.create(
                user=self.user, state=SharePlan.STATE_APPLIED,
                targets={str(self.a.pk): 50},
                previous_shares={str(self.a.pk): 50},
                applied_at=timezone.now() - timedelta(hours=2))
        plan = self._propose()
        out = _run("shares", "apply", str(plan.pk), yes=True)
        self.assertIn("Daily cap", out)
        self.a.refresh_from_db()
        self.assertEqual(self.a.extras["account_share_pct"], 50)

    def test_missing_ids_unknown_by_and_unknown_plan(self):
        with self.assertRaises(CommandError) as ctx:
            _run("shares", "apply")
        self.assertIn("at least one id", str(ctx.exception))
        plan = self._propose()
        with self.assertRaises(CommandError):
            _run("shares", "apply", str(plan.pk), yes=True, by="nobody")
        out = _run("shares", "apply", "999999", yes=True)
        self.assertIn("#999999: not found", out)


class RejectRollbackGradeTests(_Fixture):

    def test_reject_writes_nothing_and_needs_no_mode(self):
        from bot_program.models import AuditLogEntry
        from bot_program.share_models import SharePlan
        plan = self._propose()
        out = _run("shares", "reject", str(plan.pk))
        self.assertIn(f"#{plan.pk}: rejected", out)
        plan.refresh_from_db()
        self.assertEqual(plan.state, SharePlan.STATE_REJECTED)
        self.assertIsNotNone(plan.rejected_at)
        self.a.refresh_from_db(); self.b.refresh_from_db()
        self.assertEqual(self.a.extras["account_share_pct"], 50)
        self.assertNotIn("account_share_pct", self.b.extras)
        self.assertEqual(AuditLogEntry.objects.filter(kind="share_plan")
                         .last().data["decision"], "rejected")
        # A second reject is refused by the service, in its words.
        out = _run("shares", "reject", str(plan.pk))
        self.assertIn("not proposed", out)

    def test_rollback_without_yes_prints_what_it_would_restore(self):
        from bot_program.share_models import SharePlan
        _set_live(True)
        plan = self._propose()
        _run("shares", "apply", str(plan.pk), yes=True)
        out = _run("shares", "rollback", str(plan.pk))
        self.assertIn("plan only", out)
        self.assertIn("back to 50%", out)
        self.assertIn("back to auto (key removed)", out)
        plan.refresh_from_db()
        self.assertEqual(plan.state, SharePlan.STATE_APPLIED)
        self.a.refresh_from_db()
        self.assertEqual(self.a.extras["account_share_pct"], 55.0)

    def test_rollback_yes_restores_exactly(self):
        from bot_program.share_models import SharePlan
        _set_live(True)
        plan = self._propose()
        _run("shares", "apply", str(plan.pk), yes=True)
        out = _run("shares", "rollback", str(plan.pk), yes=True)
        self.assertIn(f"#{plan.pk}: ROLLED BACK", out)
        plan.refresh_from_db()
        self.assertEqual(plan.state, SharePlan.STATE_ROLLED_BACK)
        self.a.refresh_from_db(); self.b.refresh_from_db()
        self.assertEqual(self.a.extras["account_share_pct"], 50)
        self.assertNotIn("account_share_pct", self.b.extras)
        self.assertTrue(self.b.extras["capital_tracks_broker"])
        self.assertEqual(float(self.a.capital), 1000.0)
        self.assertEqual(float(self.b.capital), 1000.0)

    def test_rollback_of_a_proposed_plan_is_refused(self):
        plan = self._propose()
        out = _run("shares", "rollback", str(plan.pk), yes=True)
        self.assertIn("not applied", out)

    def test_grade_runs_the_services_grader(self):
        from bot_program.share_models import SharePlan
        plan = SharePlan.objects.create(
            user=self.user, state=SharePlan.STATE_APPLIED,
            targets={str(self.a.pk): 60}, current_shares={str(self.a.pk): 50},
            applied_at=timezone.now() - timedelta(hours=30))
        SharePlan.objects.filter(pk=plan.pk).update(
            proposed_at=timezone.now() - timedelta(hours=30))
        _fill(self.a, 2.0, days_ago=1.0)
        out = _run("shares", "grade")
        self.assertIn("graded 1 plan(s)", out)
        plan.refresh_from_db()
        self.assertIsNotNone(plan.graded_at)
        # The fixture's ten R=1 fills (one day ago) sit inside the window
        # too: 10/100 × (10 + 2) = 1.2.
        self.assertAlmostEqual(plan.grade_score, 1.2)
        out = _run("shares", "list")
        self.assertIn("LAST GRADED", out)
        self.assertIn("+1.2000", out)
